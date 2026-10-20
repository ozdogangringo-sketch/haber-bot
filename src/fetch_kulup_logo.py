"""
fetch_kulup_logo.py — Futbol kulüplerinin resmi yüksek çözünürlüklü şeffaf armalarını (PNG) sağlar.

Özellikler:
  - Yerel önbellek: `assets/club_badges/{takim_slug}.png`
  - Popüler takımlar için hazır eşleme sözlüğü
  - TheSportsDB ücretsiz test API (key 123) üzerinden otomatik arama ve indirme
  - Ağ kesintisi veya logo bulunamaması durumunda zarif hata yönetimi (None döner)
"""

from __future__ import annotations

import io
import logging
import re
import urllib.parse
from pathlib import Path
from typing import Optional

import requests
from PIL import Image

log = logging.getLogger(__name__)

KOK = Path(__file__).resolve().parent.parent
BADGE_KLASORU = KOK / "assets" / "club_badges"

# Türkiye Süper Lig ve popüler Avrupa kulüpleri için standart arama/slug haritası
POPULER_KULUPLER: dict[str, str] = {
    "galatasaray": "Galatasaray",
    "fenerbahce": "Fenerbahce",
    "besiktas": "Besiktas",
    "trabzonspor": "Trabzonspor",
    "basaksehir": "Istanbul Basaksehir",
    "samsunspor": "Samsunspor",
    "eyupspor": "Eyupspor",
    "goztepe": "Goztepe",
    "sivasspor": "Sivasspor",
    "antalyaspor": "Antalyaspor",
    "konyaspor": "Konyaspor",
    "kasimpasa": "Kasimpasa",
    "alanyaspor": "Alanyaspor",
    "rizespor": "Caykur Rizespor",
    "gaziantep": "Gaziantep FK",
    "kayserispor": "Kayserispor",
    "bodrumspor": "Bodrum FK",
    "adana demirspor": "Adana Demirspor",
    "hatayspor": "Hatayspor",
    # Popüler Avrupa
    "real madrid": "Real Madrid",
    "barcelona": "Barcelona",
    "manchester city": "Manchester City",
    "liverpool": "Liverpool",
    "arsenal": "Arsenal",
    "bayern munih": "Bayern Munich",
    "bayern munich": "Bayern Munich",
    "borussia dortmund": "Borussia Dortmund",
    "inter": "Inter Milan",
    "juventus": "Juventus",
    "milan": "AC Milan",
    "paris saint-germain": "Paris Saint-Germain",
    "psg": "Paris Saint-Germain",
    "chelsea": "Chelsea",
    "tottenham": "Tottenham",
}

_ONBELLEK_IMG: dict[str, Image.Image] = {}


def takim_slug_yap(ad: str) -> str:
    """Türkçe ve boşluklu takım adını standart dosya slug'ına çevirir."""
    t = ad.lower().strip()
    harf_map = {
        "ç": "c", "ğ": "g", "ı": "i", "i": "i", "ö": "o", "ş": "s", "ü": "u",
    }
    for tr, en in harf_map.items():
        t = t.replace(tr, en)
    t = re.sub(r"\b(s\.?k\.?|f\.?k\.?|a\.?ş\.?|j\.?k\.?)\b", "", t)
    t = re.sub(r"[^a-z0-9]+", "_", t).strip("_")
    return t


def kulup_logosu_al(takim_adi: str, boyut: int = 220) -> Optional[Image.Image]:
    """
    Verilen takımın şeffaf PNG armasını döner.
    Önce disk önbelleğine bakar, yoksa TheSportsDB'den indirip kaydeder.
    """
    if not takim_adi or not takim_adi.strip():
        return None

    slug = takim_slug_yap(takim_adi)
    onbellek_anahtari = f"{slug}_{boyut}"

    if onbellek_anahtari in _ONBELLEK_IMG:
        return _ONBELLEK_IMG[onbellek_anahtari].copy()

    BADGE_KLASORU.mkdir(parents=True, exist_ok=True)
    yerel_dosya = BADGE_KLASORU / f"{slug}.png"

    # 1. Disk önbelleği kontrolü
    if yerel_dosya.exists():
        try:
            im = Image.open(yerel_dosya).convert("RGBA")
            im = im.resize((boyut, boyut), Image.Resampling.LANCZOS)
            _ONBELLEK_IMG[onbellek_anahtari] = im
            return im.copy()
        except Exception as e:
            log.warning("Yerel kulüp arması okunamadı (%s): %s", yerel_dosya, e)

    # 2. TheSportsDB API üzerinden sorgulama
    arama_adi = POPULER_KULUPLER.get(slug.replace("_", " ")) or takim_adi
    url = f"https://www.thesportsdb.com/api/v1/json/123/searchteams.php?t={urllib.parse.quote(arama_adi)}"

    try:
        r = requests.get(url, timeout=6)
        if r.status_code == 200:
            veri = r.json()
            teams = veri.get("teams") or []
            if teams:
                badge_url = teams[0].get("strBadge")
                if badge_url:
                    img_resp = requests.get(badge_url, timeout=8)
                    if img_resp.status_code == 200:
                        ham_img = Image.open(io.BytesIO(img_resp.content)).convert("RGBA")
                        ham_img.save(yerel_dosya, "PNG")
                        im_boyutlu = ham_img.resize((boyut, boyut), Image.Resampling.LANCZOS)
                        _ONBELLEK_IMG[onbellek_anahtari] = im_boyutlu
                        log.info("Yeni kulüp arması indirildi ve kaydedildi: %s -> %s", takim_adi, yerel_dosya)
                        return im_boyutlu.copy()
    except Exception as e:
        log.warning("TheSportsDB kulüp arması indirilemedi (%s): %s", takim_adi, e)

    return None


# =============================================================================
# KULÜP RESMİ RENK SÖZLÜĞÜ & DİNAMİK RENK YÖNETİMİ
# =============================================================================

KULUP_RENKLERI: dict[str, dict[str, tuple[int, int, int]]] = {
    # 4 Büyükler
    "galatasaray": {
        "primary": (169, 4, 50),       # Karanfil Kırmızı
        "secondary": (253, 185, 19),    # Parlak Sarı/Altın
        "atmosphere": (180, 20, 50),
        "number": (253, 185, 19),
    },
    "fenerbahce": {
        "primary": (0, 45, 114),        # Derin Lacivert
        "secondary": (254, 209, 0),     # Kanarya Sarısı
        "atmosphere": (15, 55, 145),
        "number": (254, 209, 0),
    },
    "besiktas": {
        "primary": (22, 22, 28),        # Asil Siyah / Karbon
        "secondary": (240, 240, 248),   # Platin Beyaz / Gümüş
        "atmosphere": (140, 145, 165),
        "number": (255, 255, 255),
    },
    "trabzonspor": {
        "primary": (119, 13, 44),       # Bordo
        "secondary": (88, 184, 237),    # Açık Mavi
        "atmosphere": (130, 15, 50),
        "number": (88, 184, 237),
    },
    # Süper Lig Kulüpleri
    "basaksehir": {
        "primary": (237, 113, 23),
        "secondary": (15, 34, 64),
        "atmosphere": (220, 100, 20),
        "number": (237, 113, 23),
    },
    "samsunspor": {
        "primary": (195, 20, 35),
        "secondary": (245, 245, 250),
        "atmosphere": (180, 25, 40),
        "number": (255, 255, 255),
    },
    "eyupspor": {
        "primary": (115, 20, 75),
        "secondary": (245, 195, 25),
        "atmosphere": (130, 25, 85),
        "number": (245, 195, 25),
    },
    "goztepe": {
        "primary": (235, 180, 10),
        "secondary": (190, 20, 30),
        "atmosphere": (210, 160, 15),
        "number": (235, 180, 10),
    },
    "sivasspor": {
        "primary": (200, 25, 35),
        "secondary": (245, 245, 250),
        "atmosphere": (185, 25, 35),
        "number": (255, 255, 255),
    },
    "antalyaspor": {
        "primary": (210, 30, 40),
        "secondary": (245, 245, 250),
        "atmosphere": (190, 30, 40),
        "number": (255, 255, 255),
    },
    "konyaspor": {
        "primary": (0, 115, 60),
        "secondary": (245, 245, 250),
        "atmosphere": (10, 130, 70),
        "number": (255, 255, 255),
    },
    "kasimpasa": {
        "primary": (20, 35, 80),
        "secondary": (245, 245, 250),
        "atmosphere": (25, 45, 110),
        "number": (255, 255, 255),
    },
    "alanyaspor": {
        "primary": (235, 120, 20),
        "secondary": (0, 130, 70),
        "atmosphere": (220, 110, 20),
        "number": (235, 120, 20),
    },
    "rizespor": {
        "primary": (0, 115, 65),
        "secondary": (20, 70, 150),
        "atmosphere": (10, 120, 70),
        "number": (88, 184, 237),
    },
    "caykur_rizespor": {
        "primary": (0, 115, 65),
        "secondary": (20, 70, 150),
        "atmosphere": (10, 120, 70),
        "number": (88, 184, 237),
    },
    "gaziantep": {
        "primary": (190, 20, 30),
        "secondary": (25, 25, 30),
        "atmosphere": (180, 25, 35),
        "number": (190, 20, 30),
    },
    "gaziantep_fk": {
        "primary": (190, 20, 30),
        "secondary": (25, 25, 30),
        "atmosphere": (180, 25, 35),
        "number": (190, 20, 30),
    },
    "kayserispor": {
        "primary": (235, 180, 15),
        "secondary": (190, 20, 30),
        "atmosphere": (210, 160, 20),
        "number": (235, 180, 15),
    },
    "bodrumspor": {
        "primary": (0, 115, 65),
        "secondary": (245, 245, 250),
        "atmosphere": (10, 120, 70),
        "number": (255, 255, 255),
    },
    "bodrum_fk": {
        "primary": (0, 115, 65),
        "secondary": (245, 245, 250),
        "atmosphere": (10, 120, 70),
        "number": (255, 255, 255),
    },
    "adana_demirspor": {
        "primary": (20, 60, 140),
        "secondary": (245, 245, 250),
        "atmosphere": (25, 75, 160),
        "number": (88, 184, 237),
    },
    "hatayspor": {
        "primary": (120, 20, 30),
        "secondary": (245, 245, 250),
        "atmosphere": (130, 25, 35),
        "number": (255, 255, 255),
    },
    # Popüler Avrupa Kulüpleri
    "lille": {
        "primary": (210, 25, 45),
        "secondary": (15, 30, 75),
        "atmosphere": (190, 25, 45),
        "number": (210, 25, 45),
    },
    "real_madrid": {
        "primary": (240, 240, 250),
        "secondary": (220, 180, 40),
        "atmosphere": (160, 140, 90),
        "number": (220, 180, 40),
    },
    "barcelona": {
        "primary": (140, 15, 45),
        "secondary": (0, 77, 152),
        "atmosphere": (140, 15, 60),
        "number": (254, 209, 0),
    },
    "manchester_city": {
        "primary": (108, 171, 221),
        "secondary": (255, 255, 255),
        "atmosphere": (80, 150, 210),
        "number": (108, 171, 221),
    },
    "liverpool": {
        "primary": (200, 16, 46),
        "secondary": (245, 245, 250),
        "atmosphere": (190, 20, 45),
        "number": (255, 255, 255),
    },
    "arsenal": {
        "primary": (219, 0, 7),
        "secondary": (255, 255, 255),
        "atmosphere": (200, 15, 25),
        "number": (255, 255, 255),
    },
    "bayern_munich": {
        "primary": (220, 5, 45),
        "secondary": (0, 102, 178),
        "atmosphere": (200, 15, 45),
        "number": (255, 255, 255),
    },
    "bayern_munih": {
        "primary": (220, 5, 45),
        "secondary": (0, 102, 178),
        "atmosphere": (200, 15, 45),
        "number": (255, 255, 255),
    },
    "inter": {
        "primary": (2, 66, 156),
        "secondary": (20, 20, 25),
        "atmosphere": (10, 65, 160),
        "number": (88, 184, 237),
    },
    "juventus": {
        "primary": (25, 25, 28),
        "secondary": (245, 245, 250),
        "atmosphere": (140, 145, 160),
        "number": (255, 255, 255),
    },
    "ac_milan": {
        "primary": (210, 20, 30),
        "secondary": (20, 20, 25),
        "atmosphere": (190, 25, 35),
        "number": (210, 20, 30),
    },
    "psg": {
        "primary": (0, 65, 112),
        "secondary": (218, 41, 28),
        "atmosphere": (15, 65, 130),
        "number": (218, 41, 28),
    },
    "chelsea": {
        "primary": (3, 70, 148),
        "secondary": (255, 255, 255),
        "atmosphere": (10, 75, 160),
        "number": (255, 255, 255),
    },
    "tottenham": {
        "primary": (19, 34, 87),
        "secondary": (255, 255, 255),
        "atmosphere": (25, 45, 110),
        "number": (255, 255, 255),
    },
    "borussia_dortmund": {
        "primary": (253, 225, 0),
        "secondary": (17, 17, 17),
        "atmosphere": (220, 190, 15),
        "number": (253, 225, 0),
    },
    "atletico_madrid": {
        "primary": (203, 53, 36),
        "secondary": (31, 58, 126),
        "atmosphere": (190, 45, 35),
        "number": (203, 53, 36),
    },
}


def _logodan_baskin_renk(logo: Image.Image) -> tuple[int, int, int] | None:
    """Logonun şeffaf olmayan piksellerinden en canlı rengi ayıklar."""
    try:
        kucuk = logo.resize((48, 48), Image.Resampling.NEAREST).convert("RGBA")
        renk_sayaci: dict[tuple[int, int, int], int] = {}
        if hasattr(kucuk, "get_flattened_data"):
            it = iter(kucuk.get_flattened_data())
            piksel_akisi = zip(it, it, it, it)
        else:
            piksel_akisi = kucuk.getdata()

        for r, g, b, a in piksel_akisi:
            if a < 140:
                continue
            parlaklik = 0.299 * r + 0.587 * g + 0.114 * b
            doygunluk = max(r, g, b) - min(r, g, b)
            if parlaklik < 20 or parlaklik > 245 or doygunluk < 25:
                continue
            anahtar = (r // 16 * 16, g // 16 * 16, b // 16 * 16)
            renk_sayaci[anahtar] = renk_sayaci.get(anahtar, 0) + 1
        if renk_sayaci:
            en_cok = max(renk_sayaci.items(), key=lambda x: x[1])[0]
            return en_cok
    except Exception:
        pass
    return None


def kulup_renkleri_al(takim_adi: str, logo_img: Image.Image | None = None) -> dict[str, tuple[int, int, int]]:
    """
    Kulübün resmi renk paletini döner:
      - primary: Ana kulüp rengi (RGB)
      - secondary: İkincil kulüp rengi (RGB)
      - atmosphere: Kapak diyagonal stadyum atmosfer rengi (RGB)
      - number: Forma numarası parıltı rengi (RGB)
    """
    slug = takim_slug_yap(takim_adi or "")
    if slug in KULUP_RENKLERI:
        return KULUP_RENKLERI[slug]

    for k_slug, data in KULUP_RENKLERI.items():
        if k_slug in slug or slug in k_slug:
            return data

    if logo_img is not None:
        baskin = _logodan_baskin_renk(logo_img)
        if baskin:
            return {
                "primary": baskin,
                "secondary": (245, 245, 250),
                "atmosphere": baskin,
                "number": baskin,
            }

    # Genel nötr atletik palet
    return {
        "primary": (14, 165, 233),
        "secondary": (245, 245, 250),
        "atmosphere": (14, 165, 233),
        "number": (14, 165, 233),
    }
