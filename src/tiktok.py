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

log = logging.getLogger(__name__)

TIKTOK_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
TIKTOK_CREATOR_INFO_URL = "https://open.tiktokapis.com/v2/post/publish/creator_info/query/"


def access_token_al() -> str | None:
    """
    Ortam değişkeninden TIKTOK_ACCESS_TOKEN değerini alır.
    """
    token = os.getenv("TIKTOK_ACCESS_TOKEN", "").strip()
    return token or None


def video_yukle(
    video_yolu: str | Path,
    baslik: str,
    gizlilik: str = "PUBLIC_TO_EVERYONE",
    ayarlar: dict | None = None,
) -> dict[str, Any]:
    """
    1080x1920 MP4 videosunu TikTok Content Posting API v2 ile yükler.
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

    payload = {
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

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
    }

    try:
        # 1. Video Upload Oturumu Başlat
        r_init = requests.post(TIKTOK_INIT_URL, headers=headers, data=json.dumps(payload), timeout=15)
        veri_init = r_init.json()

        if r_init.status_code != 200 or veri_init.get("error", {}).get("code") != "ok":
            hata_mesaji = veri_init.get("error", {}).get("message", r_init.text[:150])
            return {
                "durum": False,
                "hata": f"TikTok video başlatma hatası: {hata_mesaji}",
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
            log.info("TikTok video başarıyla yüklendi (publish_id: %s)", publish_id)
            return {
                "durum": True,
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
        r = requests.post(TIKTOK_CREATOR_INFO_URL, headers=headers, json={}, timeout=10)
        veri = r.json()
        if r.status_code == 200 and veri.get("error", {}).get("code") == "ok":
            creator_nickname = veri.get("data", {}).get("creator_nickname", "TikTok Creator")
            return {
                "ad": "TikTok API",
                "durum": True,
                "mesaj": f"Bağlantı başarılı ({creator_nickname})",
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
