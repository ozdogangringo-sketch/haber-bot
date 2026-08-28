"""
fetch_web_image.py — Güncel olaylar için webden yüksek çözünürlüklü (HD/4K) gerçek haber fotoğrafları çeker.

Haber sitelerinin kendi og:image'ı düşük çözünürlüklü, kırpık veya kalitesiz olduğunda;
olayın bizzat gerçekleştiği anı gösteren gerçek basın fotoğraflarını web üzerinden arar,
çözünürlük, netlik ve filigransızlık filtrelerinden geçirerek slayt motoruna aktarır.
"""

from __future__ import annotations

import io
import logging
import re
from typing import Any
import requests
from PIL import Image

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,tr;q=0.8",
}

# Görsel aramalarında filtrelenecek istenmeyen anahtar kelimeler
ISTENMEYEN_TERIMLER = (
    "logo", "icon", "cartoon", "vector", "drawing", "caricature",
    "chart", "graph", "diagram", "map", "flag", "symbol", "avatar",
    "thumbnail", "poster", "banner", "sticker"
)

# Filigran basan ücretli stok siteleri (bunlar elenmeli, yalnızca haber ve basın fotoğrafları alınmalı)
YASAKLI_STOK_SITELERI = (
    "vecteezy", "shutterstock", "gettyimages", "alamy", "dreamstime",
    "istockphoto", "depositphotos", "123rf", "stockphoto", "freepik",
    "watermark", "pond5", "canva"
)


def _ddg_gorsel_ara(sorgu: str) -> list[dict[str, Any]]:
    """DuckDuckGo Image Search üzerinden yüksek çözünürlüklü görselleri listeler."""
    try:
        res = requests.get(
            "https://duckduckgo.com/",
            params={"q": sorgu},
            headers=HEADERS,
            timeout=10,
        )
        m = re.search(r'vqd=([\d-]+)', res.text) or re.search(r'vqd=\"([\d-]+)\"', res.text)
        if not m:
            return []
        vqd = m.group(1)

        r = requests.get(
            "https://duckduckgo.com/i.js",
            params={"l": "us-en", "o": "json", "q": sorgu, "vqd": vqd, "f": ",,,", "p": "1"},
            headers=HEADERS,
            timeout=10,
        )
        if r.status_code != 200:
            return []
        return r.json().get("results", [])
    except Exception as e:
        log.warning("Web görsel arama hatası (%s): %s", sorgu, e)
        return []


def fotograf_ara(
    sorgular: list[str],
    asgari_genislik: int = 1200,
    asgari_yukseklik: int = 700,
    atlanacak: int = 0,
) -> tuple[Image.Image, dict[str, Any]] | None:
    """
    Verilen sorgu listesini sırayla arar; HD çözünürlük kriterini karşılayan ilk fotoğrafı indirir.
    """
    for sorgu in sorgular:
        if not sorgu or not str(sorgu).strip():
            continue
        ham_sonuclar = _ddg_gorsel_ara(str(sorgu).strip())
        if not ham_sonuclar:
            continue

        adaylar = []
        for item in ham_sonuclar:
            w = item.get("width", 0)
            h = item.get("height", 0)
            img_url = (item.get("image") or "").lower()
            if not img_url or not img_url.startswith("http"):
                continue

            # Çözünürlük eşiği: en az 1200x700 px
            if w < asgari_genislik or h < asgari_yukseklik:
                continue

            # Filigranlı stok siteleri ele
            if any(yasak in img_url for yasak in YASAKLI_STOK_SITELERI):
                continue

            baslik = (item.get("title") or "").lower()
            if any(yasak in baslik for yasak in ISTENMEYEN_TERIMLER):
                continue

            adaylar.append(item)

        if not adaylar:
            continue

        # Belirtilen sıra adayını indir
        secilenler = adaylar[atlanacak % len(adaylar):] + adaylar[:atlanacak % len(adaylar)]
        for aday in secilenler:
            url = aday["image"]
            try:
                cevap = requests.get(url, headers=HEADERS, timeout=15)
                if cevap.status_code != 200:
                    continue
                # En az 60 KB dosya boyutu
                if len(cevap.content) < 60 * 1024:
                    continue
                foto = Image.open(io.BytesIO(cevap.content))
                foto.load()
                if foto.width >= asgari_genislik and foto.height >= asgari_yukseklik:
                    log.info("Webden temiz HD haber fotoğrafı bulundu (%sx%s): %s", foto.width, foto.height, url)
                    return foto.convert("RGB"), aday
            except Exception as e:
                log.debug("Web görseli indirilemedi (%s): %s", url, e)
                continue

    return None


def haber_icin_fotograf(
    haber: Any,
    atlanacak: int = 0,
) -> tuple[Image.Image, dict[str, Any]] | None:
    """
    Haber için en uygun 2-3 arama kalıbını oluşturup webde gerçek HD fotoğraf arar.
    """
    h_dict = dict(haber) if hasattr(haber, "keys") else (haber or {})
    baslik = h_dict.get("orijinal_baslik") or h_dict.get("ig_baslik") or h_dict.get("baslik") or ""
    ulke = h_dict.get("ulke_adi") or ""
    temsili = h_dict.get("gorsel_temsili") or ""

    sorgular = []
    if ulke and temsili:
        sorgular.append(f"{ulke} {temsili} news photo")
    if ulke and baslik:
        sorgular.append(f"{ulke} {baslik} news photo")
    if temsili:
        sorgular.append(f"{temsili} news photo HD")
    if baslik:
        sorgular.append(f"{baslik} fotoğrafları")

    return fotograf_ara(sorgular, atlanacak=atlanacak)
