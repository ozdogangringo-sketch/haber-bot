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
