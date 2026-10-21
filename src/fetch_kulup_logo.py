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
    "lille": "Lille",
    "lille osc": "Lille",
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
        "alt_atmosphere": (205, 150, 15), # Altın Sarı Atmosfer (Kırmızı çakışmasında!)
        "number": (253, 185, 19),
        "alt_number": (253, 185, 19),
        "alt_primary": (245, 180, 20),
    },
    "fenerbahce": {
        "primary": (0, 45, 114),        # Derin Lacivert
        "secondary": (254, 209, 0),     # Kanarya Sarısı
        "atmosphere": (15, 55, 145),
        "alt_atmosphere": (200, 160, 15), # Altın Sarı Atmosfer (Lacivert/Mavi çakışmasında!)
        "number": (254, 209, 0),
        "alt_number": (254, 209, 0),
        "alt_primary": (245, 200, 10),
    },
    "besiktas": {
        "primary": (240, 240, 248),        # Platin Beyaz / Gümüş (Dark modda asil ve net!)
        "secondary": (22, 22, 28),         # Karbon Siyah
        "atmosphere": (175, 190, 220),      # Stadyum Gece Projektör Işıltısı
        "alt_atmosphere": (90, 110, 145),   # Karbon Projektör
        "number": (240, 240, 248),
        "alt_number": (240, 240, 248),
        "alt_primary": (240, 240, 248),
    },
    "trabzonspor": {
        "primary": (88, 184, 237),         # Açık Mavi (Dark modda harika parlar!)
        "secondary": (135, 15, 55),        # Bordo
        "atmosphere": (145, 18, 55),        # Bordo Gece Atmosferi
        "alt_atmosphere": (25, 115, 195),  # Açık Mavi Atmosfer
        "number": (88, 184, 237),
        "alt_number": (230, 45, 85),       # Bordo Numara
        "alt_primary": (145, 18, 55),
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
        "primary": (210, 25, 45),          # Lille Kırmızısı
        "secondary": (25, 75, 175),         # Lille Kraliyet Mavisi
        "atmosphere": (190, 25, 45),        # Kırmızı Stadyum Işıltısı
        "alt_atmosphere": (22, 70, 170),    # Mavi Stadyum Işıltısı (Kırmızı çakışmasında!)
        "number": (245, 60, 50),
        "alt_number": (56, 145, 255),       # Parlak Mavi Numara
        "alt_primary": (30, 85, 200),       # Mavi Vurgu Çentiği
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
        "primary": (240, 240, 248),
        "secondary": (25, 25, 28),
        "atmosphere": (175, 190, 220),
        "number": (240, 240, 248),
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


def rgb_to_hsv(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    """RGB (0-255) değerlerini HSV (H: 0-360, S: 0-1, V: 0-1) değerlerine dönüştürür."""
    r, g, b = [x / 255.0 for x in rgb]
    mx = max(r, g, b)
    mn = min(r, g, b)
    df = mx - mn
    if mx == mn:
        h = 0.0
    elif mx == r:
        h = (60 * ((g - b) / df) + 360) % 360
    elif mx == g:
        h = (60 * ((b - r) / df) + 120) % 360
    else:
        h = (60 * ((r - g) / df) + 240) % 360
    s = 0.0 if mx == 0 else (df / mx)
    v = mx
    return h, s, v


def renk_kategorisi(rgb: tuple[int, int, int]) -> str:
    """RGB renginin ana futbol renk ailesini döner."""
    h, s, v = rgb_to_hsv(rgb)
    if s < 0.22 or v < 0.15:
        if v > 0.65:
            return "beyaz"
        elif v < 0.25:
            return "siyah"
        return "gri"
    if h < 22 or h >= 335:
        return "kirmizi"
    elif 22 <= h < 48:
        return "turuncu"
    elif 48 <= h < 75:
        return "sari"
    elif 75 <= h < 165:
        return "yesil"
    elif 165 <= h < 195:
        return "turkuaz"
    elif 195 <= h < 265:
        return "mavi"
    elif 265 <= h < 335:
        return "mor"
    return "diger"


def kulup_alternatif_tema(takim_adi: str, ana_renkler: dict) -> dict[str, tuple[int, int, int]]:
    """
    Kulübün renk çakışması durumunda kullanacağı alternatif temasını döner.
    Örn: Lille kırmızı yerine maviye; Galatasaray sarıya; Fenerbahçe sarıya geçer.
    """
    slug = takim_slug_yap(takim_adi or "")
    ham_kayit = None
    if slug in KULUP_RENKLERI:
        ham_kayit = KULUP_RENKLERI[slug]
    else:
        for k_slug, data in KULUP_RENKLERI.items():
            if k_slug in slug or slug in k_slug:
                ham_kayit = data
                break

    if ham_kayit and "alt_atmosphere" in ham_kayit:
        return {
            "primary": ham_kayit.get("alt_primary") or ham_kayit.get("alt_atmosphere") or ham_kayit.get("secondary"),
            "secondary": ham_kayit.get("primary"),
            "atmosphere": ham_kayit.get("alt_atmosphere"),
            "number": ham_kayit.get("alt_number") or ham_kayit.get("number"),
        }

    # Dinamik alternatif tema üretimi
    sec = ana_renkler.get("secondary", (220, 220, 220))
    kat = renk_kategorisi(sec)

    if kat in ("beyaz", "gri"):
        atmo = (150, 175, 210)
        num = (240, 240, 248)
        p = (220, 225, 235)
    elif kat == "siyah":
        atmo = (80, 95, 120)
        num = (210, 215, 230)
        p = (180, 185, 200)
    else:
        r, g, b = sec
        max_c = max(r, g, b)
        if max_c < 140:
            scale = 160 / max(max_c, 1)
            atmo = (min(255, int(r * scale)), min(255, int(g * scale)), min(255, int(b * scale)))
        else:
            atmo = (r, g, b)
        if max_c < 200:
            scale_num = 225 / max(max_c, 1)
            num = (min(255, int(r * scale_num)), min(255, int(g * scale_num)), min(255, int(b * scale_num)))
        else:
            num = (r, g, b)
        p = atmo

    return {
        "primary": p,
        "secondary": ana_renkler.get("primary", (180, 20, 40)),
        "atmosphere": atmo,
        "number": num,
    }


def mac_renklerini_ayarla(
    ev_ad: str,
    dep_ad: str,
    logo_ev: Image.Image | None = None,
    logo_dep: Image.Image | None = None,
) -> tuple[dict[str, tuple[int, int, int]], dict[str, tuple[int, int, int]]]:
    """
    İki kulübün renklerini çakışma (renk körlüğü / tekdüzelik) denetiminden geçirerek ayarlar.

    Kural (Doğukan İlkesi):
      İki takımın da ortak bir rengi varsa (örn: her ikisi de kırmızı), her yerin aynı renkle
      boğulmaması için alternatif renk devreye girer. Örneğin Kırmızı-Mavi (Lille) ile
      Kırmızı-Sarı / Kırmızı-Beyaz (Galatasaray / Samsunspor) karşılaştığında; beyaz gibi
      sönük nötr renkler yerine, Lille maviye geçerken diğer takım kırmızı kalır veya
      Galatasaray sarıya geçer. Böylece her zaman zengin ve kontrastlı bir stadyum atmosferi oluşur.
    """
    ev_renkler = dict(kulup_renkleri_al(ev_ad, logo_ev))
    dep_renkler = dict(kulup_renkleri_al(dep_ad, logo_dep))

    kat_ev = renk_kategorisi(ev_renkler.get("atmosphere") or ev_renkler.get("primary"))
    kat_dep = renk_kategorisi(dep_renkler.get("atmosphere") or dep_renkler.get("primary"))

    # Eğer iki takımın atmosfer/ana rengi farklı kategorilerdeyse çakışma yoktur
    if kat_ev != kat_dep:
        return ev_renkler, dep_renkler

    # ÇAKIŞMA TESPİT EDİLDİ (örn: ikisi de "kirmizi" veya ikisi de "mavi")
    ev_sec = ev_renkler.get("secondary", (220, 220, 220))
    dep_sec = dep_renkler.get("secondary", (220, 220, 220))

    kat_ev_sec = renk_kategorisi(ev_sec)
    kat_dep_sec = renk_kategorisi(dep_sec)

    notr_kategoriler = {"beyaz", "siyah", "gri"}
    ev_has_chromatic = (kat_ev_sec not in notr_kategoriler)
    dep_has_chromatic = (kat_dep_sec not in notr_kategoriler)

    if ev_has_chromatic and not dep_has_chromatic:
        # Ev sahibinin canlı ikinci rengi var, deplasmanınki nötr (örn: Lille vs Samsunspor)
        # Nötr renge düşmemek için Ev sahibi ikinci rengine (Mavi) geçer
        ev_renkler = kulup_alternatif_tema(ev_ad, ev_renkler)
    elif not ev_has_chromatic and dep_has_chromatic:
        # Ev sahibi nötr ikinci renge sahip, deplasmanın canlı rengi var (örn: Samsunspor vs Galatasaray)
        # Deplasman ikinci rengine (Sarı) geçer
        dep_renkler = kulup_alternatif_tema(dep_ad, dep_renkler)
    elif ev_has_chromatic and dep_has_chromatic:
        # İki takımın da canlı ikinci rengi var (örn: Lille Kırmızı-Mavi vs Galatasaray Kırmızı-Sarı)
        # Kullanıcı kuralı: İkinci rengi mavi/lacivert olan takım maviye geçer, diğeri kırmızı/sarı kalır
        if kat_ev_sec in ("mavi", "turkuaz"):
            ev_renkler = kulup_alternatif_tema(ev_ad, ev_renkler)
        elif kat_dep_sec in ("mavi", "turkuaz"):
            dep_renkler = kulup_alternatif_tema(dep_ad, dep_renkler)
        else:
            # Diğer durumlarda deplasman alternatif rengine geçer
            dep_renkler = kulup_alternatif_tema(dep_ad, dep_renkler)
    else:
        # İkisinin de ikinci rengi nötr (örn: Samsunspor vs Sivasspor, ikisi de Kırmızı-Beyaz)
        # Deplasman takımı şık platin/buz mavisi temaya geçer
        dep_renkler = {
            "primary": (220, 225, 235),
            "secondary": dep_renkler.get("primary", (180, 20, 40)),
            "atmosphere": (160, 185, 220),
            "number": (240, 240, 248),
        }

    return ev_renkler, dep_renkler
