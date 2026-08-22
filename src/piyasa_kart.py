"""
piyasa_kart.py — 1080x1350 Instagram Carousel 1. Slaytı için Artış/Azalış Renk Temalı Dinamik Piyasa İnfografiği.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import piyasa

log = logging.getLogger(__name__)

KOK = Path(__file__).resolve().parent.parent
FONT_YOLU = KOK / "assets" / "fonts" / "Inter-Variable.ttf"
LOGO_YOLU = KOK / "assets" / "logo_circular.png"
CIKTI_KLASORU = KOK / "data" / "output"

GENISLIK = 1080
YUKSEKLIK = 1350

# Modern Grafit Arka Plan (Yeşil ve Kırmızı kutuların kontrastla parlaması için nötr lüks zemin)
RENK_ARKA_UST = (9, 13, 22)             # #090D16 (Derin Grafit / Gece Mavisi)
RENK_ARKA_ALT = (14, 20, 34)            # #0E1422 (Lüks Koyu Zemin)
RENK_BEYAZ = (255, 255, 255)
RENK_METIN_GRI = (226, 232, 240)        # #E2E8F0 (Temiz Açık Gri)
RENK_SOLUK = (148, 163, 184)            # #94A3B8 (Slate Soluk)
RENK_MINT = (52, 211, 153)              # #34D399 (Parlak Nane Yeşili)

# --- POZİTİF KART TEMASI (Artış / Yeşil) ---
POS_KART_BG = (10, 36, 28)              # #0A241C (Derin Zümrüt Cam)
POS_KART_BORDER = (22, 105, 78)         # #16694E (Parlak Zümrüt Çerçeve)
POS_BADGE_BG = (4, 120, 87)             # #047857
POS_BADGE_BORDER = (16, 185, 129)       # #10B981
POS_BADGE_TXT = (209, 250, 229)         # #D1FAE5
POS_PILL_BG = (5, 150, 105)             # #059669
POS_PILL_BORDER = (52, 211, 153)        # #34D399
POS_PILL_TXT = (236, 253, 245)          # #ECFDF5

# --- NEGATİF KART TEMASI (Azalış / Kırmızı) ---
NEG_KART_BG = (38, 12, 18)              # #260C12 (Derin Yakut Cam)
NEG_KART_BORDER = (150, 32, 44)         # #96202C (Parlak Kırmızı Çerçeve)
NEG_BADGE_BG = (185, 28, 28)            # #B91C1C
NEG_BADGE_BORDER = (239, 68, 68)        # #EF4444
NEG_BADGE_TXT = (254, 226, 226)         # #FEE2E2
NEG_PILL_BG = (220, 38, 38)             # #DC2626
NEG_PILL_BORDER = (248, 113, 113)       # #F87171
NEG_PILL_TXT = (254, 242, 242)          # #FEF2F2


def _font(punto: int, agirlik: float = 600.0) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT_YOLU), punto)
    try:
        f.set_variation_by_axes([20.0, agirlik])
    except Exception:
        pass
    return f


def _arka_plan_ciz() -> Image.Image:
    """Nötr koyu grafit zemin üretir (kırmızı ve yeşil kartlar net görünsün)."""
    img = Image.new("RGB", (GENISLIK, YUKSEKLIK))
    draw = ImageDraw.Draw(img)

    for y in range(YUKSEKLIK):
        oran = y / YUKSEKLIK
        r = int(RENK_ARKA_UST[0] * (1 - oran) + RENK_ARKA_ALT[0] * oran)
        g = int(RENK_ARKA_UST[1] * (1 - oran) + RENK_ARKA_ALT[1] * oran)
        b = int(RENK_ARKA_UST[2] * (1 - oran) + RENK_ARKA_ALT[2] * oran)
        draw.line([(0, y), (GENISLIK, y)], fill=(r, g, b))

    # Üst köşelere hafif ambiyans ışıltısı
    glow = Image.new("RGBA", (GENISLIK, YUKSEKLIK), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.ellipse([(-120, -120), (600, 500)], fill=(30, 58, 138, 35))
    gdraw.ellipse([(650, 800), (1250, 1450)], fill=(15, 23, 42, 40))
    glow = glow.filter(ImageFilter.GaussianBlur(120))

    img.paste(Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB"), (0, 0))
    return img


def piyasa_karti_uret(veriler: dict | None = None) -> Path:
    """
    1080x1350 Instagram 1. slayt için artış/azalış renkli kutulara sahip piyasa infografiğini üretir.
    """
    if not veriler:
        veriler = piyasa.piyasa_verileri_getir()

    CIKTI_KLASORU.mkdir(parents=True, exist_ok=True)
    img = _arka_plan_ciz()
    draw = ImageDraw.Draw(img)

    f_etiket = _font(20, 800.0)
    f_baslik = _font(44, 800.0)
    f_tarih_buyuk = _font(24, 700.0)
    f_tarih_kucuk = _font(19, 500.0)
    f_badge = _font(20, 800.0)
    f_kart_ad = _font(27, 700.0)
    f_fiyat = _font(56, 800.0)
    f_rozet = _font(25, 800.0)
    f_alt = _font(21, 400.0)

    # --- 1. HEADER (Kompakt Üst Alan: Logo + Başlık Solda, Tarih Sağda) ---
    logo_boyut = 136
    logo_x = 55
    logo_y = 42

    if LOGO_YOLU.exists():
        try:
            golge = Image.new("RGBA", (GENISLIK, YUKSEKLIK), (0, 0, 0, 0))
            ImageDraw.Draw(golge).ellipse(
                [logo_x - 4, logo_y - 2, logo_x + logo_boyut + 6, logo_y + logo_boyut + 8],
                fill=(0, 0, 0, 180),
            )
            golge = golge.filter(ImageFilter.GaussianBlur(10))
            img.paste(Image.alpha_composite(img.convert("RGBA"), golge).convert("RGB"), (0, 0))

            logo = Image.open(LOGO_YOLU).convert("RGBA")
            logo = logo.resize((logo_boyut, logo_boyut), Image.Resampling.LANCZOS)
            img.paste(logo, (logo_x, logo_y), mask=logo)
        except Exception as e:
            log.warning("Logo yüklenemedi: %s", e)

    draw = ImageDraw.Draw(img)

    # Başlık Alanı
    header_x = 210
    rozet_txt = "DAILYBRIEF · PİYASALAR"
    rw = draw.textlength(rozet_txt, font=f_etiket)
    draw.rounded_rectangle(
        [(header_x, 48), (header_x + rw + 24, 84)],
        radius=8,
        fill=(15, 76, 117),
        outline=(56, 189, 248),
        width=1,
    )
    draw.text((header_x + 12, 55), rozet_txt, font=f_etiket, fill=(56, 189, 248))
    draw.text((header_x, 98), "Güne Nasıl Başladı?", font=f_baslik, fill=RENK_BEYAZ)

    # Tarih Alanı (Sağa Hizalı)
    aylar = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
             "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
    gunler = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    simdi = datetime.now(timezone.utc)
    tarih_satir1 = f"{simdi.day} {aylar[simdi.month - 1]} {simdi.year}"
    tarih_satir2 = f"{gunler[simdi.weekday()]} · Açılış"

    w_t1 = draw.textlength(tarih_satir1, font=f_tarih_buyuk)
    w_t2 = draw.textlength(tarih_satir2, font=f_tarih_kucuk)

    sag_kenar = 1025
    draw.text((sag_kenar - w_t1, 52), tarih_satir1, font=f_tarih_buyuk, fill=RENK_BEYAZ)
    draw.text((sag_kenar - w_t2, 88), tarih_satir2, font=f_tarih_kucuk, fill=RENK_SOLUK)

    # İnce ayırıcı çizgi
    draw.line([(55, 202), (1025, 202)], fill=(38, 50, 72), width=2)

    # --- 2. 6'LI ARTIŞ/AZALIŞ RENKLİ GÖSTERGE GRID (2 Kolon x 3 Satır) ---
    kart_ogeleri = [
        ("bist100", "BIST 100", "BIST", veriler.get("bist100", {})),
        ("dolar", "Dolar / TL", "USD", veriler.get("dolar", {})),
        ("euro", "Euro / TL", "EUR", veriler.get("euro", {})),
        ("gram_altin", "Gram Altın", "ALTIN", veriler.get("gram_altin", {})),
        ("btc", "Bitcoin", "BTC", veriler.get("btc", {})),
        ("brent", "Brent Petrol", "PETROL", veriler.get("brent", {})),
    ]

    kart_w = 470
    kart_h = 310
    kolon_x = [55, 555]
    satir_y = [225, 560, 895]

    # Kart arkalarına 3D yumuşak gölge katmanı
    kart_golge = Image.new("RGBA", (GENISLIK, YUKSEKLIK), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(kart_golge)
    for idx in range(6):
        kolon = idx % 2
        satir = idx // 2
        kx = kolon_x[kolon]
        ky = satir_y[satir]
        gdraw.rounded_rectangle(
            [(kx + 2, ky + 8), (kx + kart_w - 2, ky + kart_h + 12)],
            radius=26,
            fill=(0, 0, 0, 160),
        )
    kart_golge = kart_golge.filter(ImageFilter.GaussianBlur(14))
    img.paste(Image.alpha_composite(img.convert("RGBA"), kart_golge).convert("RGB"), (0, 0))

    draw = ImageDraw.Draw(img)

    for idx, (anahtar, ad, etiket, veri) in enumerate(kart_ogeleri):
        kolon = idx % 2
        satir = idx // 2
        kx = kolon_x[kolon]
        ky = satir_y[satir]

        degisim = veri.get("degisim", 0.0)
        pozitif = degisim >= 0

        # Doğrudan artış (Yeşil) / azalış (Kırmızı) renkleri
        if pozitif:
            c_bg = POS_KART_BG
            c_border = POS_KART_BORDER
            b_bg = POS_BADGE_BG
            b_border = POS_BADGE_BORDER
            b_txt = POS_BADGE_TXT
            p_bg = POS_PILL_BG
            p_border = POS_PILL_BORDER
            p_txt = POS_PILL_TXT
            yon_oku = "▲ +"
        else:
            c_bg = NEG_KART_BG
            c_border = NEG_KART_BORDER
            b_bg = NEG_BADGE_BG
            b_border = NEG_BADGE_BORDER
            b_txt = NEG_BADGE_TXT
            p_bg = NEG_PILL_BG
            p_border = NEG_PILL_BORDER
            p_txt = NEG_PILL_TXT
            yon_oku = "▼ -"

        # Kart Zemin & Çerçeve
        draw.rounded_rectangle(
            [(kx, ky), (kx + kart_w, ky + kart_h)],
            radius=24,
            fill=c_bg,
            outline=c_border,
            width=2,
        )

        # Kartın üst kenarına parlak renkli vurgu çizgisi
        draw.rounded_rectangle(
            [(kx + 24, ky), (kx + kart_w - 24, ky + 3)],
            radius=2,
            fill=p_border,
        )

        # Kart İçi Üst Satır: Varlık Rozeti + Adı
        bw = draw.textlength(etiket, font=f_badge)
        draw.rounded_rectangle(
            [(kx + 26, ky + 26), (kx + 26 + bw + 22, ky + 64)],
            radius=10,
            fill=b_bg,
            outline=b_border,
            width=1,
        )
        draw.text((kx + 37, ky + 33), etiket, font=f_badge, fill=b_txt)
        draw.text((kx + 26 + bw + 32, ky + 32), ad, font=f_kart_ad, fill=RENK_METIN_GRI)

        # Fiyat Metni (Büyük 56pt, saf beyaz)
        fiyat_val = veri.get("fiyat", 0.0)
        if anahtar == "btc":
            fiyat_str = f"${piyasa.turkce_sayi(fiyat_val, 0)}"
        elif anahtar == "brent":
            fiyat_str = f"${piyasa.turkce_sayi(fiyat_val, 2)}"
        elif anahtar in ("dolar", "euro", "gram_altin"):
            fiyat_str = f"{piyasa.turkce_sayi(fiyat_val, 2)} ₺"
        else:
            fiyat_str = piyasa.turkce_sayi(fiyat_val, 0)

        draw.text((kx + 26, ky + 106), fiyat_str, font=f_fiyat, fill=RENK_BEYAZ)

        # Değişim Rozeti (Büyük Kapsül)
        rozet_txt = f"{yon_oku}%{abs(degisim):.2f}"
        rw = draw.textlength(rozet_txt, font=f_rozet)
        rx = kx + 26
        ry = ky + 220
        draw.rounded_rectangle(
            [(rx, ry), (rx + rw + 32, ry + 56)],
            radius=14,
            fill=p_bg,
            outline=p_border,
            width=2,
        )
        draw.text((rx + 16, ry + 12), rozet_txt, font=f_rozet, fill=p_txt)

    # --- 3. FOOTER ---
    draw.line([(55, 1235), (1025, 1235)], fill=(38, 50, 72), width=1)
    draw.text(
        (55, 1260),
        "DailyBrief.co News  ·  Piyasa açılış göstergeleri anlık verilerdir.",
        font=f_alt,
        fill=RENK_SOLUK,
    )
    draw.text(
        (55, 1298),
        "Yatırım tavsiyesi değildir.",
        font=f_alt,
        fill=(56, 189, 248),
    )

    cikti_yolu = CIKTI_KLASORU / f"piyasa_karti_{simdi.strftime('%Y%m%d')}.jpg"
    img.save(cikti_yolu, "JPEG", quality=95)
    log.info("Artış/Azalış renkli piyasa kartı üretildi: %s", cikti_yolu)
    return cikti_yolu
