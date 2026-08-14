"""
upload_image.py — ADIM 4a
Üretilen görselleri imgbb'ye yükleyip herkese açık URL alır.

NEDEN GEREKLİ:
    Instagram Graph API görseli dosya olarak KABUL ETMİYOR. Sadece
    "şu adresteki görseli al" diyebiliyorsun — yani görselin internette
    herkese açık bir adreste durması şart. Bizim sunucumuz olmadığı için
    imgbb'yi ara depo olarak kullanıyoruz.

YAYIN SONRASI:
    Instagram post'u yayınlarken görselin kendi kopyasını alıyor. Yani
    imgbb'deki dosya yayından sonra silinse bile post etkilenmiyor.
    Bu yüzden yüklemelere son kullanma tarihi veriyoruz — hesabımız
    zamanla çöp dolmasın.
"""

from __future__ import annotations

import base64
import logging
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

log = logging.getLogger(__name__)
load_dotenv()

UC_NOKTA = "https://api.imgbb.com/1/upload"
GECICI_HATALAR = {429, 500, 502, 503, 504}


def _anahtar() -> str:
    a = os.getenv("IMGBB_API_KEY", "").strip()
    if not a:
        raise RuntimeError(
            "IMGBB_API_KEY bulunamadı. imgbb.com/api adresinden alıp "
            ".env dosyasına ekle."
        )
    return a


def gorsel_yukle(yol: Path, ayarlar: dict) -> dict:
    """
    Tek bir görseli yükler.

    Döner: {'url', 'silme_url', 'boyut_kb'}
    Başaramazsa exception fırlatır — çağıran taraf yakalamalı.
    """
    g = ayarlar["imgbb"]
    yol = Path(yol)
    ham = yol.read_bytes()

    son_hata = None
    for deneme in range(1, g["deneme_sayisi"] + 1):
        try:
            cevap = requests.post(
                UC_NOKTA,
                data={
                    "key": _anahtar(),
                    "image": base64.b64encode(ham).decode("ascii"),
                    "name": yol.stem,
                    # Saniye cinsinden ömür. Yayından sonra Instagram kendi
                    # kopyasını tuttuğu için kısa tutmak güvenli.
                    "expiration": g["omur_saniye"],
                },
                timeout=g["zaman_asimi"],
            )
        except requests.RequestException as e:
            son_hata = f"{type(e).__name__}: {e}"
            log.warning("imgbb ağ hatası (deneme %d): %s", deneme, e)
            time.sleep(2 * deneme)
            continue

        if cevap.status_code == 200:
            veri = cevap.json()
            if not veri.get("success"):
                raise RuntimeError(f"imgbb reddetti: {str(veri)[:200]}")
            d = veri["data"]
            return {
                "url": d["url"],
                "silme_url": d.get("delete_url"),
                "boyut_kb": round(len(ham) / 1024, 1),
            }

        son_hata = f"HTTP {cevap.status_code}: {cevap.text[:200]}"
        if cevap.status_code in GECICI_HATALAR:
            time.sleep(2 * deneme)
            continue
        break

    raise RuntimeError(f"imgbb yüklemesi başarısız: {son_hata}")


def hepsini_yukle(yollar: list[Path], ayarlar: dict) -> list[dict]:
    """
    Carousel için birden fazla görseli sırayla yükler.

    Biri patlarsa TAMAMI iptal edilir (exception fırlatır): eksik
    slaytla post atmak, hiç atmamaktan kötü.
    """
    sonuclar = []
    for i, yol in enumerate(yollar, 1):
        sonuc = gorsel_yukle(yol, ayarlar)
        log.info("yüklendi %d/%d: %s", i, len(yollar), sonuc["url"])
        sonuclar.append(sonuc)
    return sonuclar
