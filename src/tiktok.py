"""
tiktok.py — TikTok Content Posting API v2 üzerinden 9:16 dikey video yükleyici.

1080x1920 dikey haber ve borsa videolarını TikTok hesabına gönderir.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

TIKTOK_OAUTH_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
TIKTOK_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
TIKTOK_INBOX_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
TIKTOK_CREATOR_INFO_URL = "https://open.tiktokapis.com/v2/post/publish/creator_info/query/"
TIKTOK_CONTENT_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/content/init/"
TIKTOK_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TIKTOK_REDIRECT_URI = "https://dailybrief.ozbornstudio.com/callback"
TIKTOK_SCOPES = "user.info.basic,video.upload,video.publish"


def token_yenile(con=None) -> str | None:
    """
    TIKTOK_REFRESH_TOKEN kullanarak TikTok API'sinden 24 saat geçerli taze bir Access Token alır.
    Yeni jetonu ortam değişkenlerine, veritabanına ve .env dosyasına kalıcı olarak kaydeder.
    """
    client_key = os.getenv("TIKTOK_CLIENT_KEY", "").strip()
    client_secret = os.getenv("TIKTOK_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv("TIKTOK_REFRESH_TOKEN", "").strip()

    if not client_key or not client_secret or not refresh_token:
        log.warning("TikTok OAuth bilgileri eksik (CLIENT_KEY, CLIENT_SECRET veya REFRESH_TOKEN).")
        return None

    try:
        r = requests.post(
            TIKTOK_OAUTH_TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_key": client_key,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            timeout=15,
        )
        veri = r.json()
        if r.status_code == 200 and "access_token" in veri:
            yeni_token = veri["access_token"]
            yeni_refresh = veri.get("refresh_token")

            # 1. Ortam değişkenlerini güncelle
            os.environ["TIKTOK_ACCESS_TOKEN"] = yeni_token
            if yeni_refresh:
                os.environ["TIKTOK_REFRESH_TOKEN"] = yeni_refresh

            # 2. SQLite ayarlar tablosuna yaz
            if con:
                try:
                    con.execute(
                        "INSERT INTO ayarlar (anahtar, deger) VALUES ('tiktok_access_token', ?) "
                        "ON CONFLICT(anahtar) DO UPDATE SET deger = excluded.deger",
                        (yeni_token,),
                    )
                    if yeni_refresh:
                        con.execute(
                            "INSERT INTO ayarlar (anahtar, deger) VALUES ('tiktok_refresh_token', ?) "
                            "ON CONFLICT(anahtar) DO UPDATE SET deger = excluded.deger",
                            (yeni_refresh,),
                        )
                    con.commit()
                except Exception as e:
                    log.warning("TikTok jetonları DB'ye yazılamadı: %s", e)

            # 3. .env dosyası varsa güncelle
            env_yolu = Path(".env")
            if env_yolu.exists():
                try:
                    metin = env_yolu.read_text(encoding="utf-8")
                    if "TIKTOK_ACCESS_TOKEN=" in metin:
                        import re
                        metin = re.sub(r"TIKTOK_ACCESS_TOKEN=.*", f"TIKTOK_ACCESS_TOKEN={yeni_token}", metin)
                        if yeni_refresh and "TIKTOK_REFRESH_TOKEN=" in metin:
                            metin = re.sub(r"TIKTOK_REFRESH_TOKEN=.*", f"TIKTOK_REFRESH_TOKEN={yeni_refresh}", metin)
                        env_yolu.write_text(metin, encoding="utf-8")
                except Exception as e:
                    log.warning(".env TikTok jetonu güncellenemedi: %s", e)

            # 4. GitHub Secrets güncelle (Actions ortamında kalıcılık için)
            repo = os.getenv("GITHUB_REPOSITORY", "ozdogangringo-sketch/haber-bot")
            try:
                from . import refresh_token
                refresh_token.github_secret_guncelle(yeni_token, repo, ad="TIKTOK_ACCESS_TOKEN")
                if yeni_refresh:
                    refresh_token.github_secret_guncelle(yeni_refresh, repo, ad="TIKTOK_REFRESH_TOKEN")
            except Exception as e:
                log.warning("TikTok secret güncellenemedi: %s", e)

            log.info("TikTok erişim jetonu başarıyla yenilendi.")
            return yeni_token
        else:
            log.warning("TikTok jeton yenileme başarısız (%s): %s", r.status_code, veri)
    except Exception as e:
        log.warning("TikTok token yenileme isteğinde hata: %s", e)

    return None


def access_token_al(con=None) -> str | None:
    """
    TikTok erişim jetonunu döner. Jeton yoksa veya geçersizse otomatik yeniler.
    """
    token = os.getenv("TIKTOK_ACCESS_TOKEN", "").strip()
    if not token:
        token = token_yenile(con)
    return token or None


TIKTOK_AZAMI_BASLIK = 150


def baslik_kur(baslik: str, etiketler: list[str] | None = None) -> str:
    """
    TikTok başlığını kurar: manşet + sığdığı kadar etiket.

    ⚠️ AĞA ÇIKMAYAN SAF FONKSİYON — `video_yukle` içindeyken davranışı
    sınamanın tek yolu jeton ve gerçek dosyaydı, yani hiç sınanmıyordu.
    """
    temiz = (baslik or "").strip()
    ham = [str(e).strip().lstrip("#") for e in (etiketler or []) if str(e).strip()]
    if not ham:
        ham = ["DailyBrief", "Haber", "SonDakika"]

    for etiket in ham:
        aday = f"{temiz} #{etiket}".strip()
        if len(aday) > TIKTOK_AZAMI_BASLIK:
            break
        temiz = aday
    return temiz


def aciklama_kur(
    metin: str,
    etiketler: list[str] | None = None,
    azami_uzunluk: int = 4000,
    baslik: str | None = None,
) -> str:
    """
    TikTok fotoğraf modunun tam açıklama metnini kurar.
    Editoryal metni ve etiketleri tekrarsız (mükerrersiz) olarak 4000 karaktere kadar kurar.
    Metnin sonunda zaten etiket satırı varsa onu ayıklar ve tek bir temiz etiket bloğu üretir.
    Eğer `baslik` verilmişse veya metin başında başlık / 📌 satırları varsa, TikTok'ta başlık
    zaten `post_info.title` alanında gösterildiği için açıklamadan ayıklar (mükerrerlik engeli).
    """
    metin_temiz = (metin or "").strip()

    # 1. Metnin sonundaki mevcut hashtag kuyruğunu (yalnızca etiketlerden oluşan satırları) ayıkla
    satirlar = metin_temiz.splitlines()
    mevcut_kuyruk_etiketleri = []
    while satirlar:
        s = satirlar[-1].strip()
        if not s:
            satirlar.pop()
            continue
        tokens = s.split()
        if tokens and all(t.startswith("#") for t in tokens):
            for t in tokens:
                tag = t.lstrip("#").strip()
                if tag and tag.lower() not in [x.lower() for x in mevcut_kuyruk_etiketleri]:
                    mevcut_kuyruk_etiketleri.append(tag)
            satirlar.pop()
            continue
        break

    govde = "\n".join(satirlar).rstrip()

    # 1.5. TikTok Carousel'da başlık zaten ayrı 'title' alanına yazılıyor.
    # Açıklama (description) başında başlığın (📌 ... veya '🔴 SON DAKİKA') tekrarlanmasını ayıkla.
    if baslik or govde:
        temiz_baslik = re.sub(r"[^\w\s]", "", (baslik or "")).strip().lower()
        govde_satirlari = govde.splitlines()
        kirpilmis = []
        baslik_atlandi = False
        for s in govde_satirlari:
            s_str = s.strip()
            if not baslik_atlandi:
                if not s_str:
                    continue
                if s_str.startswith("🔴") or ("son dakika" in s_str.lower() and len(s_str) < 25):
                    continue
                if s_str.startswith("📌"):
                    continue
                s_norm = re.sub(r"[^\w\s]", "", s_str).strip().lower()
                if temiz_baslik and (s_norm == temiz_baslik or s_norm.startswith(temiz_baslik)):
                    continue
                baslik_atlandi = True
            kirpilmis.append(s)

        yeni_govde = "\n".join(kirpilmis).strip()
        if yeni_govde:
            govde = yeni_govde

    # 2. Etiketleri birleştir ve dedupe et (sıralamayı koru)
    hedef_etiketler = []
    goruldu = set()

    kaynak_etiketler = (etiketler or []) + mevcut_kuyruk_etiketleri
    if not kaynak_etiketler:
        kaynak_etiketler = ["DailyBrief", "Haber", "Gündem", "SonDakika"]

    for e in kaynak_etiketler:
        e_str = str(e).strip().lstrip("#")
        if not e_str:
            continue
        k = e_str.lower()
        if k not in goruldu:
            goruldu.add(k)
            hedef_etiketler.append(e_str)

    etiket_metni = " ".join(f"#{e}" for e in hedef_etiketler[:8])

    if govde and etiket_metni:
        birlestirilmis = f"{govde}\n\n{etiket_metni}"
    elif etiket_metni:
        birlestirilmis = etiket_metni
    else:
        birlestirilmis = govde

    return birlestirilmis[:azami_uzunluk].strip()


def foto_carousel_yukle(
    resim_urlleri: list[str],
    baslik: str,
    gizlilik: str = "PUBLIC_TO_EVERYONE",
    ayarlar: dict | None = None,
    etiketler: list[str] | None = None,
    aciklama: str | None = None,
) -> dict[str, Any]:
    """
    1080x1920 dikey haber ve analiz slaytlarını TikTok Content Posting API v2
    ile Photo Mode (Carousel / Fotoğraf Kaydırmalı Gönderi) olarak yayınlar.

    Girdi:
      * resim_urlleri: Herkese açık HTTPS görsel URL'leri listesi (1-35 adet, JPEG veya WEBP)
      * baslik: Gönderi başlığı (TikTok title azami 90 karakter)
      * aciklama: Gönderi açıklaması/caption (TikTok description azami 4000 karakter)
      * gizlilik: 'PUBLIC_TO_EVERYONE' | 'MUTUAL_FOLLOW_FRIENDS' | 'SELF_ONLY'
    """
    if not resim_urlleri:
        return {"durum": False, "hata": "Görsel URL listesi boş"}

    token = access_token_al()
    if not token:
        return {"durum": False, "hata": "TIKTOK_ACCESS_TOKEN eksik veya tanımlanmamış."}

    # TikTok Title (Azami 90 karakter)
    temiz_baslik = (baslik or "").strip()[:90]

    # TikTok Description (Azami 4000 karakter, başlık zaten title alanında olduğu için açıklamada tekrarlanmaz)
    tam_aciklama = aciklama_kur(aciklama or baslik, etiketler, azami_uzunluk=4000, baslik=temiz_baslik)

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
    }

    # Resim URL'lerini listeye filtrele (maksimum 35 adet)
    gecerli_urller = [str(u).strip() for u in resim_urlleri if str(u).strip().startswith("http")][:35]
    if not gecerli_urller:
        return {"durum": False, "hata": "Geçerli HTTPS görsel URL'si bulunamadı"}

    try:
        # 1. Önce Doğrudan Yayınlama (DIRECT_POST) Dene
        payload_direct = {
            "media_type": "PHOTO",
            "post_mode": "DIRECT_POST",
            "post_info": {
                "title": temiz_baslik,
                "description": tam_aciklama,
                "privacy_level": gizlilik,
                "disable_comment": False,
            },
            "source_info": {
                "source": "PULL_FROM_URL",
                "photo_cover_index": 1,
                "photo_images": gecerli_urller,
            },
        }

        r_init = requests.post(TIKTOK_CONTENT_INIT_URL, headers=headers, json=payload_direct, timeout=15)
        veri_init = r_init.json()
        mod = "direct_publish"

        # Token süresi dolduysa yenileyip tekrar dene
        if r_init.status_code == 401 or veri_init.get("error", {}).get("code") in ("access_token_invalid", "token_expired"):
            log.info("TikTok jetonu süresi dolmuş, yenilenip tekrar deneniyor...")
            token = token_yenile()
            if token:
                headers["Authorization"] = f"Bearer {token}"
                r_init = requests.post(TIKTOK_CONTENT_INIT_URL, headers=headers, json=payload_direct, timeout=15)
                veri_init = r_init.json()

        err_code = veri_init.get("error", {}).get("code", "")
        err_msg = veri_init.get("error", {}).get("message", "")

        # URL alan adı doğrulaması gerekiyorsa
        if err_code == "url_ownership_unverified":
            log.warning("TikTok görsel alan adı doğrulanmamış (url_ownership_unverified): %s", err_msg)
            return {
                "durum": False,
                "hata": (
                    "TikTok alan adı doğrulanmamış (url_ownership_unverified). "
                    "developers.tiktok.com üzerinden görsel CDN alan adı eklenmelidir."
                ),
                "url_unverified": True,
                "kod": err_code,
            }

        # App audit yoksa veya direct post kısıtlıysa Inbox/Taslak (MEDIA_UPLOAD) moduna geç
        if r_init.status_code != 200 or err_code != "ok":
            log.info(
                "TikTok Carousel direct publish reddedildi (%s: %s), MEDIA_UPLOAD (Inbox/Taslak) deneniyor...",
                err_code,
                err_msg,
            )
            payload_inbox = {
                "media_type": "PHOTO",
                "post_mode": "MEDIA_UPLOAD",
                "post_info": {
                    "title": temiz_baslik,
                    "description": tam_aciklama,
                    "disable_comment": False,
                },
                "source_info": {
                    "source": "PULL_FROM_URL",
                    "photo_cover_index": 1,
                    "photo_images": gecerli_urller,
                },
            }
            r_init = requests.post(TIKTOK_CONTENT_INIT_URL, headers=headers, json=payload_inbox, timeout=15)
            veri_init = r_init.json()
            mod = "inbox_draft"
            err_code = veri_init.get("error", {}).get("code", "")
            err_msg = veri_init.get("error", {}).get("message", "")

            if err_code == "url_ownership_unverified":
                return {
                    "durum": False,
                    "hata": (
                        "TikTok alan adı doğrulanmamış (url_ownership_unverified). "
                        "developers.tiktok.com üzerinden görsel CDN alan adı eklenmelidir."
                    ),
                    "url_unverified": True,
                    "kod": err_code,
                }

            if r_init.status_code != 200 or err_code != "ok":
                return {
                    "durum": False,
                    "hata": f"TikTok Carousel başlatma hatası ({err_code}): {err_msg}",
                    "kod": err_code,
                }

        data_block = veri_init.get("data", {})
        publish_id = data_block.get("publish_id")
        log.info("TikTok Carousel başarıyla başlatıldı (%s, publish_id: %s)", mod, publish_id)
        return {
            "durum": True,
            "mod": mod,
            "publish_id": publish_id,
            "yanit": veri_init,
        }
    except Exception as e:
        log.warning("TikTok Carousel yükleme hatası: %s", e)
        return {"durum": False, "hata": str(e)}


def video_yukle(
    video_yolu: str | Path,
    baslik: str,
    gizlilik: str = "PUBLIC_TO_EVERYONE",
    ayarlar: dict | None = None,
    etiketler: list[str] | None = None,
) -> dict[str, Any]:
    """
    1080x1920 MP4 videosunu TikTok Content Posting API v2 ile yükler.
    Direct Publish (video.publish) ve Inbox/Drafts (video.upload) modlarını otomatik destekler.
    """
    yol = Path(video_yolu)
    if not yol.exists() or yol.stat().st_size == 0:
        return {"durum": False, "hata": f"Video dosyası bulunamadı veya boş: {yol}"}

    token = access_token_al()
    if not token:
        return {"durum": False, "hata": "TIKTOK_ACCESS_TOKEN eksik veya tanımlanmamış."}

    dosya_boyutu = yol.stat().st_size

    # TikTok başlığı — TikTok'ta ayrı açıklama alanı YOK, etiketler
    # başlığın içinde yaşıyor. Sınır 150 karakter.
    #
    # ⚠️ ESKİDEN SABİT ÜÇ ETİKET BASILIYORDU (#DailyBrief #Haber
    # #SonDakika) — haber ne olursa olsun aynısı. YouTube/Reels'teki
    # "hep aynı 5 etiket" kusurunun TikTok'taki kardeşi; `caption`
    # habere özel etiketleri üretiyor ve `etiketler` ile geliyor.
    #
    # ⚠️ BAŞLIK ASLA KIRPILMAZ, ETİKET DÜŞER. Ölçüldü (8 gerçek başlık):
    # başlık + 5 etiket en fazla 142 karakter, hepsi sığıyor. Yine de
    # uzun bir başlık gelirse manşeti kesmek etiketi kesmekten kötü —
    # okuyucu için değerli olan manşet.
    temiz_baslik = baslik_kur(baslik, etiketler)

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
    }

    try:
        # 1. Önce Doğrudan Yayınlama (Direct Publish - video.publish) Dene
        payload_publish = {
            "post_info": {
                "title": temiz_baslik[:150],
                "privacy_level": gizlilik,
                "disable_duet": False,
                "disable_stitch": False,
                "disable_comment": False,
                "video_cover_timestamp_ms": 1000,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": dosya_boyutu,
                "chunk_size": dosya_boyutu,
                "total_chunk_count": 1,
            },
        }

        r_init = requests.post(TIKTOK_INIT_URL, headers=headers, json=payload_publish, timeout=15)
        veri_init = r_init.json()
        mod = "direct_publish"

        # 401 / Token süresi dolduysa anında yenile ve tekrar dene
        if r_init.status_code == 401 or veri_init.get("error", {}).get("code") in ("access_token_invalid", "token_expired"):
            log.info("TikTok jetonu süresi dolmuş, yenilenip tekrar deneniyor...")
            token = token_yenile()
            if token:
                headers["Authorization"] = f"Bearer {token}"
                r_init = requests.post(TIKTOK_INIT_URL, headers=headers, json=payload_publish, timeout=15)
                veri_init = r_init.json()

        # ⚠️ SEBEP "video.publish İZNİ YOK" DEĞİL — ÖLÇÜLDÜ (4 Eyl 2026).
        # Taze jetonun izinleri: video.upload, user.info.basic,
        # **video.publish** — yani izin ZATEN VAR. Doğrudan yayın
        # denendiğinde gelen cevap:
        #     HTTP 403 unaudited_client_can_only_post_to_private_accounts
        # Yani engel APP AUDIT: TikTok'un denetiminden geçmemiş
        # uygulamalar yalnızca GİZLİ hesaplara post atabiliyor,
        # @DailyBrief.co ise herkese açık. Jetonu tazelemek bunu
        # DEĞİŞTİRMİYOR — denendi, aynı 403 geldi.
        # Kalıcı çözüm: developers.tiktok.com üzerinden app audit
        # başvurusu. Kod tarafında yapılabilecek bir şey yok.
        if r_init.status_code != 200 or veri_init.get("error", {}).get("code") != "ok":
            hata_mesaji = veri_init.get("error", {}).get("message", "")
            log.info("Direct publish scope kısıtlı (%s), Inbox/Taslak moduna geçiliyor...", hata_mesaji)

            payload_inbox = {
                "post_info": {
                    "title": temiz_baslik[:150],
                },
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": dosya_boyutu,
                    "chunk_size": dosya_boyutu,
                    "total_chunk_count": 1,
                },
            }
            r_init = requests.post(TIKTOK_INBOX_INIT_URL, headers=headers, json=payload_inbox, timeout=15)
            veri_init = r_init.json()
            mod = "inbox_draft"

            if r_init.status_code != 200 or veri_init.get("error", {}).get("code") != "ok":
                hata_inbox = veri_init.get("error", {}).get("message", r_init.text[:150])
                return {
                    "durum": False,
                    "hata": f"TikTok video başlatma hatası: {hata_inbox}",
                }

        data_block = veri_init.get("data", {})
        publish_id = data_block.get("publish_id")
        upload_url = data_block.get("upload_url")

        if not upload_url:
            return {"durum": False, "hata": "TikTok upload URL alınamadı."}

        # 2. Video Baytlarını Yükle
        with open(yol, "rb") as f:
            headers_upload = {
                "Content-Type": "video/mp4",
                "Content-Range": f"bytes 0-{dosya_boyutu - 1}/{dosya_boyutu}",
            }
            r_up = requests.put(upload_url, headers=headers_upload, data=f, timeout=120)

        if r_up.status_code in (200, 201):
            log.info("TikTok video başarıyla yüklendi (%s, publish_id: %s)", mod, publish_id)
            return {
                "durum": True,
                "mod": mod,
                "publish_id": publish_id,
                "yanit": veri_init,
            }
        else:
            return {
                "durum": False,
                "hata": f"TikTok bayt yükleme hatası ({r_up.status_code}): {r_up.text[:150]}",
            }
    except Exception as e:
        log.warning("TikTok yükleme hatası: %s", e)
        return {"durum": False, "hata": str(e)}


def yayin_durumu_sorgula(publish_id: str) -> dict[str, Any]:
    """
    TikTok'a yüklenen videonun işlenme ve gelen kutusuna ulaşma durumunu sorgular.
    Döner: {'durum': True/False, 'status': 'SEND_TO_USER_INBOX'|'PROCESSING_UPLOAD'|'SUCCESS'|'FAILED', 'hata': '...'}
    """
    token = access_token_al()
    if not token or not publish_id:
        return {"durum": False, "status": "NO_TOKEN", "hata": "Token veya publish_id eksik."}

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
    }
    try:
        url = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
        r = requests.post(url, headers=headers, json={"publish_id": publish_id}, timeout=15)
        veri = r.json()
        if r.status_code == 401 or veri.get("error", {}).get("code") in ("access_token_invalid", "token_expired"):
            token = token_yenile()
            if token:
                headers["Authorization"] = f"Bearer {token}"
                r = requests.post(url, headers=headers, json={"publish_id": publish_id}, timeout=15)
                veri = r.json()

        if r.status_code == 200 and veri.get("error", {}).get("code") == "ok":
            status = veri.get("data", {}).get("status", "UNKNOWN")
            return {"durum": True, "status": status, "veri": veri}
        else:
            hata = veri.get("error", {}).get("message", r.text[:100])
            return {"durum": False, "status": "ERROR", "hata": hata}
    except Exception as e:
        return {"durum": False, "status": "EXCEPTION", "hata": str(e)}


def saglik_testi(ayarlar: dict) -> dict[str, Any]:
    """
    TikTok Content Posting API bağlantısını test eder.
    """
    aktif = bool((ayarlar.get("sosyal", {}) or {}).get("tiktoka_da_at"))
    token = access_token_al()

    if not aktif and not token:
        return {
            "ad": "TikTok API",
            "durum": True,
            "mesaj": "Devre dışı (config'de kapalı)",
        }

    if not token:
        return {
            "ad": "TikTok API",
            "durum": False,
            "mesaj": "TIKTOK_ACCESS_TOKEN eksik.",
        }

    headers = {"Authorization": f"Bearer {token}"}
    try:
        url = "https://open.tiktokapis.com/v2/user/info/?fields=open_id,display_name,avatar_url"
        r = requests.get(url, headers=headers, timeout=10)
        veri = r.json()
        if r.status_code == 401 or veri.get("error", {}).get("code") in ("access_token_invalid", "token_expired"):
            token = token_yenile()
            if token:
                headers["Authorization"] = f"Bearer {token}"
                r = requests.get(url, headers=headers, timeout=10)
                veri = r.json()

        if r.status_code == 200 and veri.get("error", {}).get("code") == "ok":
            display_name = veri.get("data", {}).get("user", {}).get("display_name", "TikTok Creator")
            return {
                "ad": "TikTok API",
                "durum": True,
                "mesaj": f"Bağlantı başarılı (@{display_name})",
            }
        else:
            hata = veri.get("error", {}).get("message", r.text[:80])
            return {
                "ad": "TikTok API",
                "durum": False,
                "mesaj": f"Hata: {hata}",
            }
    except Exception as e:
        return {
            "ad": "TikTok API",
            "durum": False,
            "mesaj": f"İstek hatası: {type(e).__name__}",
        }


def auth_url_uret() -> str:
    """TikTok OAuth 2.0 yetkilendirme bağlantısını üretir."""
    client_key = os.getenv("TIKTOK_CLIENT_KEY", "").strip()
    if not client_key:
        raise ValueError("TIKTOK_CLIENT_KEY tanımlı değil!")
    import urllib.parse
    params = {
        "client_key": client_key,
        "scope": TIKTOK_SCOPES,
        "response_type": "code",
        "redirect_uri": TIKTOK_REDIRECT_URI,
        "state": "dailybrief_tiktok_auth",
    }
    return f"{TIKTOK_AUTH_URL}?{urllib.parse.urlencode(params)}"


def yetki_al(manuel_kod: str | None = None, con=None) -> dict[str, Any]:
    """
    Kullanıcının callback sayfasından kopyaladığı authorization code'u
    kalıcı access_token ve refresh_token ile takas eder.
    """
    client_key = os.getenv("TIKTOK_CLIENT_KEY", "").strip()
    client_secret = os.getenv("TIKTOK_CLIENT_SECRET", "").strip()
    if not client_key or not client_secret:
        raise ValueError("TIKTOK_CLIENT_KEY veya TIKTOK_CLIENT_SECRET eksik!")

    code = (manuel_kod or "").strip()
    if not code:
        raise ValueError("TikTok authorization code belirtilmedi!")

    if "code=" in code:
        import urllib.parse
        parsed = urllib.parse.urlparse(code)
        qs = urllib.parse.parse_qs(parsed.query)
        code = qs.get("code", [code])[0]

    log.info("TikTok yetkilendirme kodu erişim jetonları ile takas ediliyor...")
    r = requests.post(
        TIKTOK_OAUTH_TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": TIKTOK_REDIRECT_URI,
        },
        timeout=30,
    )
    veri = r.json()
    if r.status_code != 200 or "access_token" not in veri:
        raise RuntimeError(f"TikTok token takası başarısız ({r.status_code}): {veri}")

    access_token = veri["access_token"]
    refresh_token = veri.get("refresh_token")
    open_id = veri.get("open_id")

    os.environ["TIKTOK_ACCESS_TOKEN"] = access_token
    if refresh_token:
        os.environ["TIKTOK_REFRESH_TOKEN"] = refresh_token
    if open_id:
        os.environ["TIKTOK_OPEN_ID"] = open_id

    # .env güncelle
    env_yolu = Path(".env")
    if env_yolu.exists():
        try:
            metin = env_yolu.read_text(encoding="utf-8")
            if "TIKTOK_ACCESS_TOKEN=" in metin:
                metin = re.sub(r"TIKTOK_ACCESS_TOKEN=.*", f"TIKTOK_ACCESS_TOKEN={access_token}", metin)
            else:
                metin += f"\nTIKTOK_ACCESS_TOKEN={access_token}\n"
            if refresh_token:
                if "TIKTOK_REFRESH_TOKEN=" in metin:
                    metin = re.sub(r"TIKTOK_REFRESH_TOKEN=.*", f"TIKTOK_REFRESH_TOKEN={refresh_token}", metin)
                else:
                    metin += f"\nTIKTOK_REFRESH_TOKEN={refresh_token}\n"
            if open_id:
                if "TIKTOK_OPEN_ID=" in metin:
                    metin = re.sub(r"TIKTOK_OPEN_ID=.*", f"TIKTOK_OPEN_ID={open_id}", metin)
                else:
                    metin += f"\nTIKTOK_OPEN_ID={open_id}\n"
            env_yolu.write_text(metin, encoding="utf-8")
        except Exception as e:
            log.warning(".env dosyasına TikTok jetonları yazılamadı: %s", e)

    # data/tiktok_token.json dosyasına da kaydet
    token_dosyasi = Path("data/tiktok_token.json")
    try:
        token_dosyasi.parent.mkdir(parents=True, exist_ok=True)
        import time
        token_kayit = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "open_id": open_id,
            "scope": veri.get("scope"),
            "expires_at": time.time() + veri.get("expires_in", 86400),
            "refresh_expires_at": time.time() + veri.get("refresh_expires_in", 31536000),
        }
        token_dosyasi.write_text(json.dumps(token_kayit, indent=2), encoding="utf-8")
    except Exception as e:
        log.warning("data/tiktok_token.json yazılamadı: %s", e)

    # DB güncelle
    if con:
        try:
            con.execute(
                "INSERT INTO ayarlar (anahtar, deger) VALUES ('tiktok_access_token', ?) "
                "ON CONFLICT(anahtar) DO UPDATE SET deger = excluded.deger",
                (access_token,),
            )
            if refresh_token:
                con.execute(
                    "INSERT INTO ayarlar (anahtar, deger) VALUES ('tiktok_refresh_token', ?) "
                    "ON CONFLICT(anahtar) DO UPDATE SET deger = excluded.deger",
                    (refresh_token,),
                )
            con.commit()
        except Exception as e:
            log.warning("DB'ye TikTok jetonu yazılamadı: %s", e)

    log.info("✅ TikTok erişim jetonları başarıyla alındı ve kalıcı olarak kaydedildi!")
    return veri


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    kod = sys.argv[1] if len(sys.argv) > 1 else None
    if kod:
        print(f"Girilen kod takas ediliyor: {kod}")
        yetki_al(manuel_kod=kod)
    else:
        url = auth_url_uret()
        print("\n" + "=" * 60)
        print("🔗 DAILY BRIEF TIKTOK GİRİŞ BAĞLANTISI:")
        print(url)
        print("=" * 60 + "\n")

