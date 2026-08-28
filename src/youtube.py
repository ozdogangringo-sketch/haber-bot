"""
youtube.py — YouTube Data API v3 üzerinden 9:16 Shorts video yükleyici.

1080x1920 dikey haber ve borsa videolarını doğrudan YouTube Shorts olarak yayınlar.
OAuth 2.0 Client ID, Secret ve Refresh Token üzerinden kalıcı yetkilendirme sağlar.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import requests

log = logging.getLogger(__name__)

YOUTUBE_TOKEN_URL = "https://oauth2.googleapis.com/token"
YOUTUBE_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"


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

    token = access_token_al()
    if not token:
        return {"durum": False, "hata": "YouTube erişim jetonu alınamadı."}

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
        "X-Upload-Content-Length": str(yol.stat().st_size),
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
        with open(yol, "rb") as f:
            headers_upload = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "video/mp4",
            }
            r_up = requests.put(upload_url, headers=headers_upload, data=f, timeout=120)

        if r_up.status_code in (200, 201):
            veri = r_up.json()
            video_id = veri.get("id")
            video_link = f"https://youtube.com/shorts/{video_id}"
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
