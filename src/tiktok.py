"""
tiktok.py — TikTok Content Posting API v2 üzerinden 9:16 dikey video yükleyici.

1080x1920 dikey haber ve borsa videolarını TikTok hesabına gönderir.
"""

from __future__ import annotations

import json
import logging
import os
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


def video_yukle(
    video_yolu: str | Path,
    baslik: str,
    gizlilik: str = "PUBLIC_TO_EVERYONE",
    ayarlar: dict | None = None,
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

    # TikTok başlığı (maksimum 150 karakter, hashtaglerle zenginleştirilmiş)
    temiz_baslik = baslik.strip()
    if "#dailybrief" not in temiz_baslik.lower():
        if len(temiz_baslik) <= 120:
            temiz_baslik = f"{temiz_baslik} #DailyBrief #Haber #SonDakika"

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
