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

from dotenv import load_dotenv
import requests

load_dotenv()

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


def youtube_icin_sesli_video_hazirla(
    video_yolu: Path | str,
    cikti_yolu: Path | str | None = None,
) -> Path:
    """
    YouTube Shorts ve Facebook Reels için videoya hafif, telifsiz haber ambiyans fon müziği miksler.
    """
    yol = Path(video_yolu)
    if not yol.exists():
        return yol
    # "🎙️ Sesli Yayınla" videosu (ses.anlatimli_video_uret, "_sesli"): sesi son hâlinde.
    # Aşağıdaki komut sesi fon müziğiyle DEĞİŞTİRİYOR — anlatım silinirdi (2026-09-26).
    if yol.stem.endswith("_sesli"):
        return yol

    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        if cikti_yolu is not None:
            yt_cikti = Path(cikti_yolu)
        else:
            import uuid
            yt_cikti = yol.with_name(f"{yol.stem}_yt_{uuid.uuid4().hex[:6]}.mp4")

        # 1. assets/audio klasöründe özel hazır müzik var mı?
        kok = Path(__file__).resolve().parent.parent
        ses_klasoru = kok / "assets" / "audio"
        ozel_muzik = None
        if ses_klasoru.exists():
            for aday in ses_klasoru.glob("*.mp3"):
                ozel_muzik = aday
                break

        if ozel_muzik and ozel_muzik.exists():
            # Harici fon müziğini arka plana hafif (-14dB) miksle
            komut = [
                ffmpeg_exe, "-y",
                "-i", str(yol),
                "-stream_loop", "-1", "-i", str(ozel_muzik),
                "-filter_complex", "[1:a]volume=0.20[a1]",
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


def projeleri_getir() -> list[dict[str, Any]]:
    """Tanımlı YouTube projelerini (Client ID, Secret, Refresh Token) döner."""
    projeler = []
    # 1. Ana Proje
    c1 = os.getenv("YOUTUBE_CLIENT_ID", "").strip()
    s1 = os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()
    r1 = os.getenv("YOUTUBE_REFRESH_TOKEN", "").strip()
    if c1 and s1 and r1:
        projeler.append({"proje_no": 1, "client_id": c1, "client_secret": s1, "refresh_token": r1})

    # 2. Yedek Proje (2. Google Cloud Projesi)
    c2 = os.getenv("YOUTUBE_CLIENT_ID_2", "").strip()
    s2 = os.getenv("YOUTUBE_CLIENT_SECRET_2", "").strip()
    r2 = os.getenv("YOUTUBE_REFRESH_TOKEN_2", "").strip()
    if c2 and s2 and r2:
        projeler.append({"proje_no": 2, "client_id": c2, "client_secret": s2, "refresh_token": r2})

    return projeler


def azami_gunluk_video() -> int:
    """Mevcut YouTube proje sayısına göre günlük yüklenebilecek azami video kotasını döner (proje başına 5 video)."""
    p_sayisi = len(projeleri_getir())
    return max(5, p_sayisi * 5)


def access_token_al(proje_no: int | None = None) -> str | None:
    """
    Belirtilen YouTube projesi veya ilk uygun proje için taze bir OAuth2 Access Token alır.
    """
    projeler = projeleri_getir()
    if not projeler:
        log.warning("YouTube API kimlik bilgileri eksik (CLIENT_ID, CLIENT_SECRET veya REFRESH_TOKEN).")
        return None

    secilenler = [p for p in projeler if p["proje_no"] == proje_no] if proje_no else projeler
    for p in secilenler:
        try:
            data = {
                "client_id": p["client_id"],
                "client_secret": p["client_secret"],
                "refresh_token": p["refresh_token"],
                "grant_type": "refresh_token",
            }
            res = requests.post(YOUTUBE_TOKEN_URL, data=data, timeout=10)
            if res.status_code == 200:
                token = res.json().get("access_token")
                if token:
                    return token
            log.warning("YouTube Proje %d token yenileme başarısız (%s): %s", p["proje_no"], res.status_code, res.text[:200])
        except Exception as e:
            log.warning("YouTube Proje %d token alma hatası: %s", p["proje_no"], e)
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

    # 1. Günlük YouTube Kota Denetimi (Mevcut proje sayısına göre dinamik)
    yuklenen_bugun = gunluk_yukleme_sayisi_al()
    azami_video = azami_gunluk_video()
    if yuklenen_bugun >= azami_video:
        log.warning(
            "YouTube günlük kota koruması: bugün zaten %d video yüklendi (azami: %d). Kota aşımını önlemek için atlanıyor.",
            yuklenen_bugun,
            azami_video,
        )
        return {
            "durum": False,
            "hata": f"YouTube günlük kota sınırına ({yuklenen_bugun}/{azami_video} video) ulaşıldı. Shorts atlandı.",
            "kota_siniri": True,
        }

    projeler = projeleri_getir()
    if not projeler:
        return {"durum": False, "hata": "YouTube API kimlik bilgileri eksik veya tanımlanmamış."}

    # 2. SADECE YouTube Shorts için hafif ambiyans fon müziği ekle (zaten sesli değilse)
    if "_yt" not in yol.name:
        yuklenecek_yol = youtube_icin_sesli_video_hazirla(yol)
        gecici_dosya = (yuklenecek_yol != yol)
    else:
        yuklenecek_yol = yol
        gecici_dosya = False

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

    # Proje öncelik sırası: Bugün 5'ten fazla video yüklendiyse 2. projeyi ilk sıraya al
    sirali_projeler = list(projeler)
    if len(sirali_projeler) > 1 and yuklenen_bugun >= 5:
        sirali_projeler.reverse()

    son_hata = ""
    try:
        for idx, p in enumerate(sirali_projeler, 1):
            token = access_token_al(p["proje_no"])
            if not token:
                son_hata = f"Proje {p['proje_no']} erişim jetonu alınamadı."
                continue

            headers_init = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": "video/mp4",
                "X-Upload-Content-Length": str(yuklenecek_yol.stat().st_size),
            }

            # 1. Resumable Upload Başlat
            r_init = requests.post(
                YOUTUBE_UPLOAD_URL,
                headers=headers_init,
                data=json.dumps(meta_payload),
                timeout=15,
            )
            if r_init.status_code != 200 or "Location" not in r_init.headers:
                hata_metni = r_init.text
                log.warning("YouTube Proje %d upload başlatılamadı (%s): %s", p["proje_no"], r_init.status_code, hata_metni[:200])
                if "quotaExceeded" in hata_metni or "exceeded your quota" in hata_metni or r_init.status_code == 403:
                    son_hata = f"Proje {p['proje_no']} kotası aşıldı ({r_init.status_code})"
                    if idx < len(sirali_projeler):
                        log.info("YouTube Proje %d kotası doldu, Proje %d deneniyor...", p["proje_no"], sirali_projeler[idx]["proje_no"])
                        continue
                return {
                    "durum": False,
                    "hata": f"Upload URL başlatılamadı ({r_init.status_code}): {hata_metni[:150]}",
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
                log.info("YouTube Shorts başarıyla yüklendi (Proje %d): %s", p["proje_no"], video_link)
                return {
                    "durum": True,
                    "video_id": video_id,
                    "url": video_link,
                    "yanit": veri,
                    "proje": p["proje_no"],
                }
            else:
                log.error("YouTube video yükleme başarısız (%s): %s", r_up.status_code, r_up.text)
                son_hata = f"Video yükleme başarısız ({r_up.status_code}): {r_up.text[:150]}"
                if idx < len(sirali_projeler):
                    continue
                return {
                    "durum": False,
                    "hata": son_hata,
                }

        return {"durum": False, "hata": son_hata or "Hiçbir YouTube projesi ile video yüklenemedi."}

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
    projeler = projeleri_getir()

    if not aktif and not projeler:
        return {
            "ad": "YouTube Shorts API",
            "durum": True,
            "mesaj": "Devre dışı (config'de kapalı)",
        }

    if not projeler:
        return {
            "ad": "YouTube Shorts API",
            "durum": False,
            "mesaj": "YOUTUBE_CLIENT_ID veya YOUTUBE_REFRESH_TOKEN eksik.",
        }

    basarili_projeler = []
    for p in projeler:
        tok = access_token_al(p["proje_no"])
        if tok:
            basarili_projeler.append(p["proje_no"])

    if basarili_projeler:
        p_str = ", ".join(f"Proje {p}" for p in basarili_projeler)
        return {
            "ad": "YouTube Shorts API",
            "durum": True,
            "mesaj": f"Bağlantı ve OAuth2 aktif ({p_str}) — Günlük kota: {azami_gunluk_video()} video",
        }
    else:
        return {
            "ad": "YouTube Shorts API",
            "durum": False,
            "mesaj": "OAuth2 Token yenilenemedi, kimlik bilgilerini kontrol edin.",
        }


def video_sil(video_id: str) -> bool:
    """Yayınlanmış bir YouTube Shorts / video içeriğini siler."""
    if not video_id:
        return False
    if "youtu" in video_id:
        video_id = video_id.rstrip("/").split("/")[-1].split("?")[0]
    token = access_token_al()
    if not token:
        log.warning("YouTube video silmek için access token alınamadı.")
        return False
    try:
        r = requests.delete(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"id": video_id},
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        if r.status_code in (200, 204):
            log.info("YouTube videosu başarıyla silindi: %s", video_id)
            return True
        log.warning("YouTube videosu silinemedi (%s): %s %s", video_id, r.status_code, r.text[:120])
        return False
    except Exception as e:
        log.warning("YouTube video silme hatası (%s): %s", video_id, e)
        return False

