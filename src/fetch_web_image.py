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


from . import gorsel_kalite


def fotograf_ara(
    sorgular: list[str],
    asgari_genislik: int = 1600,
    asgari_yukseklik: int = 1000,
    atlanacak: int = 0,
) -> tuple[Image.Image, dict[str, Any]] | None:
    """
    Verilen sorgu listesini sırayla arar; 4K/HD çözünürlük ve kristal netlik kriterini
    karşılayan ilk editoryal basın fotoğrafını indirir.
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

            # Çözünürlük eşiği: en az 1600x1000 px (dikey kırpmada kristal netlik için)
            if w < asgari_genislik or h < asgari_yukseklik:
                # Dikey bir portre ise 1080x1350 de kabul edilir
                if not (w >= 1080 and h >= 1350):
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
                ham_boyut_kb = len(cevap.content) / 1024.0
                foto = Image.open(io.BytesIO(cevap.content))
                foto.load()

                # Piksel yoğunluğu, dikey kırpma ölçeği ve Laplacian netlik denetimi
                kaliteli, sebep = gorsel_kalite.gorsel_kalite_denetle(foto, dosya_boyutu_kb=ham_boyut_kb)
                if not kaliteli:
                    log.info("Web görsel adayı elendi (%s): %s", url, sebep)
                    continue

                log.info("Webden temiz HD basın fotoğrafı onaylandı (%sx%s, %.1f KB): %s",
                         foto.width, foto.height, ham_boyut_kb, url)
                return gorsel_kalite.kristal_netlestir(foto.convert("RGB")), aday
            except Exception as e:
                log.debug("Web görseli indirilemedi (%s): %s", url, e)
                continue

    return None


def haber_icin_fotograf(
    haber: Any,
    atlanacak: int = 0,
) -> tuple[Image.Image, dict[str, Any]] | None:
    """
    Haber için en uygun 4-5 editoryal basın arama kalıbını oluşturup webde gerçek HD fotoğraf arar.
    Kişi, sıcak olay, şirket, kurum ve teknoloji kategorilerine göre optimize edilmiş sorgular üretir.
    """
    h_dict = dict(haber) if hasattr(haber, "keys") else (haber or {})
    baslik = h_dict.get("orijinal_baslik") or h_dict.get("ig_baslik") or h_dict.get("baslik") or ""
    ulke = h_dict.get("ulke_adi") or ""
    konu = h_dict.get("gorsel_konu") or ""
    temsili = h_dict.get("gorsel_temsili") or ""
    kategori = h_dict.get("kategori") or ""

    # Başlığı temizle (özel karakterleri ve tırnakları ayıkla)
    temiz_baslik = re.sub(r'[^\w\sğüşıöçĞÜŞİÖÇ]', ' ', baslik).strip()
    kelimeler = temiz_baslik.split()
    kisa_baslik = " ".join(kelimeler[:6]) if len(kelimeler) > 6 else temiz_baslik

    sorgular = []

    # 1. Kişi / Lider Odaklı Sorgular
    if konu:
        sorgular.append(f"{konu} basın toplantısı")
        sorgular.append(f"{konu} press portrait HD")
        sorgular.append(f"{konu} news photo")

    # 2. Somut İngilizce Basın & Olay Sorguları
    if temsili:
        if ulke:
            sorgular.append(f"{ulke} {temsili} press photo")
        sorgular.append(f"{temsili} news editorial photo")
        sorgular.append(f"{temsili} press kit HD")

    # 3. Sıcak Türkçe Haber & Ajans Başlık Sorguları
    if kisa_baslik:
        sorgular.append(f"{kisa_baslik} haber fotoğrafları")
        sorgular.append(f"{kisa_baslik} basın görseli")

    # 4. Kategoriye Özel Zenginleştirme
    if kategori == "ekonomi" and kisa_baslik:
        sorgular.append(f"{kisa_baslik} bloomberg reuters")
    elif kategori in ("teknoloji", "bilim") and temsili:
        sorgular.append(f"{temsili} product launch press kit")

    return fotograf_ara(sorgular, asgari_genislik=1000, asgari_yukseklik=600, atlanacak=atlanacak)
