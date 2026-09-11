"""
youtube.py — YouTube Data API v3 üzerinden 9:16 Shorts video yükleyici.

1080x1920 dikey haber ve borsa videolarını doğrudan YouTube Shorts olarak yayınlar.
OAuth 2.0 Client ID, Secret ve Refresh Token üzerinden kalıcı yetkilendirme sağlar.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

import requests

log = logging.getLogger(__name__)

YOUTUBE_TOKEN_URL = "https://oauth2.googleapis.com/token"
YOUTUBE_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
YOUTUBE_GUNLUK_AZAMI_VIDEO = 5


def gunluk_yukleme_sayisi_al(con=None) -> int:
    """Bugün YouTube'a başarıyla yüklenmiş Shorts videosu sayısını döner."""
    bugun = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    anahtar = f"youtube_gunluk_sayac_{bugun}"
    kendi_baglantisi = False
    if con is None:
        try:
            from src.db import baglan
            con = baglan()
            kendi_baglantisi = True
        except Exception:
            return 0
    try:
        satir = con.execute("SELECT deger FROM ayarlar WHERE anahtar = ?", (anahtar,)).fetchone()
        return int(satir["deger"]) if satir and satir["deger"] else 0
    except Exception:
        return 0
    finally:
        if kendi_baglantisi:
            try:
                con.close()
            except Exception:
                pass


def gunluk_yukleme_sayisi_artir(con=None) -> None:
    """Bugünkü YouTube yükleme sayacını 1 artırır."""
    bugun = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    anahtar = f"youtube_gunluk_sayac_{bugun}"
    mevcut = gunluk_yukleme_sayisi_al(con)
    kendi_baglantisi = False
    if con is None:
        try:
            from src.db import baglan
            con = baglan()
            kendi_baglantisi = True
        except Exception:
            return
    try:
        con.execute(
            "INSERT INTO ayarlar (anahtar, deger) VALUES (?, ?) "
            "ON CONFLICT(anahtar) DO UPDATE SET deger = excluded.deger",
            (anahtar, str(mevcut + 1)),
        )
        con.commit()
    except Exception as e:
        log.warning("YouTube günlük sayacı kaydedilemedi: %s", e)
    finally:
        if kendi_baglantisi:
            try:
                con.close()
            except Exception:
                pass


def youtube_icin_sesli_video_hazirla(video_yolu: Path | str) -> Path:
    """
    SADECE YouTube Shorts için videoya hafif, telifsiz haber ambiyans fon müziği miksler.
    Diğer platformlar (Instagram, TikTok, Facebook) bu fonksiyona uğramaz ve sessiz kalır.
    """
    yol = Path(video_yolu)
    if not yol.exists():
        return yol

    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        yt_cikti = yol.with_name(f"{yol.stem}_yt.mp4")

        # 1. assets/audio klasöründe özel hazır müzik var mı?
        kok = Path(__file__).resolve().parent.parent
        ses_klasoru = kok / "assets" / "audio"
        ozel_muzik = None
        if ses_klasoru.exists():
            for aday in ses_klasoru.glob("*.mp3"):
                ozel_muzik = aday
                break

        if ozel_muzik and ozel_muzik.exists():
            # Harici fon müziğini arka plana hafif (-18dB) miksle
            komut = [
                ffmpeg_exe, "-y",
                "-i", str(yol),
                "-stream_loop", "-1", "-i", str(ozel_muzik),
                "-filter_complex", "[1:a]volume=0.15[a1]",
                "-map", "0:v", "-map", "[a1]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                "-shortest", "-movflags", "+faststart",
                str(yt_cikti),
            ]
        else:
            # Telifsiz, hafif ve modern haber/bülten ambiyans armonisi üret
            komut = [
                ffmpeg_exe, "-y",
                "-i", str(yol),
                "-f", "lavfi", "-i",
                "aevalsrc=0.03*sin(2*PI*110*t)+0.02*sin(2*PI*164.81*t)+0.02*sin(2*PI*220*t)+0.015*sin(2*PI*329.63*t):s=44100",
                "-map", "0:v", "-map", "1:a",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                "-shortest", "-movflags", "+faststart",
                str(yt_cikti),
            ]

        subprocess.run(komut, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if yt_cikti.exists() and yt_cikti.stat().st_size > 0:
            log.info("YouTube Shorts için ambiyans fon müziği başarıyla mikslendi: %s", yt_cikti.name)
            return yt_cikti
    except Exception as e:
        log.warning("YouTube için fon müziği mikslenemedi, orijinal video ile devam ediliyor: %s", e)

    return yol


def access_token_al() -> str | None:
    """
    YOUTUBE_REFRESH_TOKEN kullanarak taze bir Google OAuth2 Access Token alır.
    """
    client_id = os.getenv("YOUTUBE_CLIENT_ID", "").strip()
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv("YOUTUBE_REFRESH_TOKEN", "").strip()

    if not client_id or not client_secret or not refresh_token:
        log.warning("YouTube API kimlik bilgileri eksik (CLIENT_ID, CLIENT_SECRET veya REFRESH_TOKEN).")
        return None

    try:
        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        res = requests.post(YOUTUBE_TOKEN_URL, data=data, timeout=10)
        if res.status_code == 200:
            token = res.json().get("access_token")
            return token
        log.warning("YouTube token yenileme başarısız (%s): %s", res.status_code, res.text[:200])
    except Exception as e:
        log.warning("YouTube token alma hatası: %s", e)
    return None


def shorts_yukle(
    video_yolu: str | Path,
    baslik: str,
    aciklama: str = "",
    etiketler: list[str] | None = None,
    gizlilik: str = "public",
    ayarlar: dict | None = None,
) -> dict[str, Any]:
    """
    1080x1920 MP4 videosunu YouTube Shorts olarak yükler ve yayınlar.
    """
    yol = Path(video_yolu)
    if not yol.exists() or yol.stat().st_size == 0:
        return {"durum": False, "hata": f"Video dosyası bulunamadı veya boş: {yol}"}

    # 1. Günlük YouTube Kota Denetimi (Maksimum 5 video / gün = 8000 birim)
    yuklenen_bugun = gunluk_yukleme_sayisi_al()
    if yuklenen_bugun >= YOUTUBE_GUNLUK_AZAMI_VIDEO:
        log.warning(
            "YouTube günlük kota koruması: bugün zaten %d video yüklendi. Kota aşımını önlemek için atlanıyor.",
            yuklenen_bugun,
        )
        return {
            "durum": False,
            "hata": f"YouTube günlük kota sınırına ({yuklenen_bugun}/{YOUTUBE_GUNLUK_AZAMI_VIDEO} video) ulaşıldı. Shorts atlandı.",
            "kota_siniri": True,
        }

    token = access_token_al()
    if not token:
        return {"durum": False, "hata": "YouTube erişim jetonu alınamadı."}

    # 2. SADECE YouTube Shorts için hafif ambiyans fon müziği ekle
    yuklenecek_yol = youtube_icin_sesli_video_hazirla(yol)
    gecici_dosya = (yuklenecek_yol != yol)

    # Shorts Başlık & Açıklama Optimizasyonu (100 karakter sınırına dikkat)
    temiz_baslik = baslik.strip()
    if "#Shorts" not in temiz_baslik and "#shorts" not in temiz_baslik:
        if len(temiz_baslik) <= 90:
            temiz_baslik = f"{temiz_baslik} #Shorts"

    if not aciklama:
        aciklama = f"{baslik}\n\n#Shorts #DailyBrief #Haber #Borsa #Gündem\n\nGüncel haberler için takipte kalın."

    default_tags = ["Shorts", "Daily Brief", "Haber", "Borsa", "Gündem", "Son Dakika"]
    tags = list(set((etiketler or []) + default_tags))

    meta_payload = {
        "snippet": {
            "title": temiz_baslik[:100],
            "description": aciklama,
            "tags": tags,
            "categoryId": "25",  # News & Politics
            "defaultLanguage": "tr",
        },
        "status": {
            "privacyStatus": gizlilik,
            "selfDeclaredMadeForKids": False,
        },
    }

    headers_init = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": "video/mp4",
        "X-Upload-Content-Length": str(yuklenecek_yol.stat().st_size),
    }

    try:
        # 1. Resumable Upload Başlat
        r_init = requests.post(
            YOUTUBE_UPLOAD_URL,
            headers=headers_init,
            data=json.dumps(meta_payload),
            timeout=15,
        )
        if r_init.status_code != 200 or "Location" not in r_init.headers:
            return {
                "durum": False,
                "hata": f"Upload URL başlatılamadı ({r_init.status_code}): {r_init.text[:150]}",
            }

        upload_url = r_init.headers["Location"]

        # 2. Video Baytlarını Yükle
        with open(yuklenecek_yol, "rb") as f:
            headers_upload = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "video/mp4",
            }
            r_up = requests.put(upload_url, headers=headers_upload, data=f, timeout=120)

        if r_up.status_code in (200, 201):
            veri = r_up.json()
            video_id = veri.get("id")
            video_link = f"https://youtube.com/shorts/{video_id}"
            gunluk_yukleme_sayisi_artir()
            log.info("YouTube Shorts başarıyla yüklendi: %s", video_link)
            return {
                "durum": True,
                "video_id": video_id,
                "url": video_link,
                "yanit": veri,
            }
        else:
            return {
                "durum": False,
                "hata": f"Video yükleme başarısız ({r_up.status_code}): {r_up.text[:150]}",
            }

    except Exception as e:
        log.warning("YouTube Shorts yükleme hatası: %s", e)
        return {"durum": False, "hata": str(e)}
    finally:
        if gecici_dosya and yuklenecek_yol.exists():
            try:
                yuklenecek_yol.unlink(missing_ok=True)
            except Exception:
                pass


def saglik_testi(ayarlar: dict) -> dict[str, Any]:
    """
    YouTube API bağlantısını ve OAuth jetonunu test eder.
    """
    aktif = bool((ayarlar.get("sosyal", {}) or {}).get("youtube_a_da_at"))
    client_id = os.getenv("YOUTUBE_CLIENT_ID", "").strip()
    refresh_token = os.getenv("YOUTUBE_REFRESH_TOKEN", "").strip()

    if not aktif and not refresh_token:
        return {
            "ad": "YouTube Shorts API",
            "durum": True,
            "mesaj": "Devre dışı (config'de kapalı)",
        }

    if not client_id or not refresh_token:
        return {
            "ad": "YouTube Shorts API",
            "durum": False,
            "mesaj": "YOUTUBE_CLIENT_ID veya YOUTUBE_REFRESH_TOKEN eksik.",
        }

    token = access_token_al()
    if token:
        return {
            "ad": "YouTube Shorts API",
            "durum": True,
            "mesaj": "Bağlantı ve OAuth2 yetkilendirmesi aktif",
        }
    else:
        return {
            "ad": "YouTube Shorts API",
            "durum": False,
            "mesaj": "OAuth2 Token yenilenemedi, kimlik bilgilerini kontrol edin.",
        }
