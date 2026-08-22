"""
piyasa_kart.py — 1080x1350 Instagram Carousel 1. Slaytı için Lüks & Büyük Kartlı Yeşil Piyasa İnfografiği.
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

# Lüks Ekonomi & Finans Yeşili Renk Paleti
RENK_ARKA_UST = (2, 20, 14)           # #02140E
RENK_ARKA_ALT = (6, 38, 28)           # #06261C
RENK_KART_BG = (11, 46, 36)           # #0B2E24 (Derin Zümrüt Cam Zemin)
RENK_KART_BORDER = (27, 99, 78)       # #1B634E (Parlak Zümrüt Kenar)
RENK_BEYAZ = (255, 255, 255)
RENK_METIN_GRI = (209, 236, 226)      # #D1ECE2
RENK_SOLUK = (130, 175, 158)          # #82AF9E
RENK_MINT = (52, 211, 153)            # #34D399 (Parlak Nane Yeşili)

# Pozitif / Negatif Rozetler
RENK_YESIL_BG = (4, 120, 87)          # #047857
RENK_YESIL_BORDER = (16, 185, 129)    # #10B981
RENK_YESIL_TXT = (236, 253, 245)      # #ECFDF5

RENK_KIRMIZI_BG = (185, 28, 28)       # #B91C1C
RENK_KIRMIZI_BORDER = (239, 68, 68)   # #EF4444
RENK_KIRMIZI_TXT = (254, 242, 242)    # #FEF2F2


def _font(punto: int, agirlik: float = 600.0) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT_YOLU), punto)
    try:
        f.set_variation_by_axes([20.0, agirlik])
    except Exception:
        pass
    return f


def _arka_plan_ciz() -> Image.Image:
    """Zengin zümrüt yeşili gradyan ve nane yeşili ışık efekti ile arka plan üretir."""
    img = Image.new("RGB", (GENISLIK, YUKSEKLIK))
    draw = ImageDraw.Draw(img)

    for y in range(YUKSEKLIK):
        oran = y / YUKSEKLIK
        r = int(RENK_ARKA_UST[0] * (1 - oran) + RENK_ARKA_ALT[0] * oran)
        g = int(RENK_ARKA_UST[1] * (1 - oran) + RENK_ARKA_ALT[1] * oran)
        b = int(RENK_ARKA_UST[2] * (1 - oran) + RENK_ARKA_ALT[2] * oran)
        draw.line([(0, y), (GENISLIK, y)], fill=(r, g, b))

    # Üst sol ve sağ alta zümrüt ve altın ışıltısı
    glow = Image.new("RGBA", (GENISLIK, YUKSEKLIK), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.ellipse([(-120, -120), (700, 600)], fill=(5, 150, 105, 50))
    gdraw.ellipse([(550, 750), (1250, 1450)], fill=(16, 185, 129, 30))
    glow = glow.filter(ImageFilter.GaussianBlur(120))

    img.paste(Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB"), (0, 0))
    return img


def piyasa_karti_uret(veriler: dict | None = None) -> Path:
    """
    1080x1350 Instagram 1. slayt yeşil temalı, büyük kartlı ve sağda tarihli piyasa infografik kartını üretir.
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
            # Logo arkasına yumuşak gölge
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

    # Başlık Alanı (Logonun Sağında)
    header_x = 210
    rozet_txt = "DAILYBRIEF · PİYASALAR"
    rw = draw.textlength(rozet_txt, font=f_etiket)
    draw.rounded_rectangle(
        [(header_x, 48), (header_x + rw + 24, 84)],
        radius=8,
        fill=(6, 78, 59),
        outline=(16, 185, 129),
        width=1,
    )
    draw.text((header_x + 12, 55), rozet_txt, font=f_etiket, fill=RENK_MINT)
    draw.text((header_x, 98), "Güne Nasıl Başladı?", font=f_baslik, fill=RENK_BEYAZ)

    # Tarih Alanı (En Sağda, Sağa Hizalı)
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
    draw.line([(55, 202), (1025, 202)], fill=(22, 84, 66), width=2)

    # --- 2. 6'LI BÜYÜTÜLMÜŞ GÖSTERGE GRID (2 Kolon x 3 Satır) ---
    kart_ogeleri = [
        ("bist100", "BIST 100", "BIST", (6, 78, 59), (110, 231, 183), veriler.get("bist100", {})),
        ("dolar", "Dolar / TL", "USD", (20, 83, 45), (134, 239, 172), veriler.get("dolar", {})),
        ("euro", "Euro / TL", "EUR", (19, 78, 74), (94, 234, 212), veriler.get("euro", {})),
        ("gram_altin", "Gram Altın", "ALTIN", (120, 53, 15), (252, 211, 77), veriler.get("gram_altin", {})),
        ("btc", "Bitcoin", "BTC", (154, 52, 18), (253, 186, 116), veriler.get("btc", {})),
        ("brent", "Brent Petrol", "PETROL", (15, 118, 110), (153, 246, 228), veriler.get("brent", {})),
    ]

    # Büyütülmüş kart ölçüleri (Yükseklik 310px, Genişlik 470px)
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
            [(kx + 2, ky + 8), (kx + kart_w - 2, ky + kart_h + 10)],
            radius=26,
            fill=(0, 0, 0, 160),
        )
    kart_golge = kart_golge.filter(ImageFilter.GaussianBlur(14))
    img.paste(Image.alpha_composite(img.convert("RGBA"), kart_golge).convert("RGB"), (0, 0))

    draw = ImageDraw.Draw(img)

    for idx, (anahtar, ad, etiket, bg_pill, txt_pill, veri) in enumerate(kart_ogeleri):
        kolon = idx % 2
        satir = idx // 2
        kx = kolon_x[kolon]
        ky = satir_y[satir]

        # Kart Zemin & Parlak Vurgu Kenarı
        draw.rounded_rectangle(
            [(kx, ky), (kx + kart_w, ky + kart_h)],
            radius=24,
            fill=RENK_KART_BG,
            outline=RENK_KART_BORDER,
            width=2,
        )

        # Kart İçi Üst Satır: Varlık Rozeti + Adı
        bw = draw.textlength(etiket, font=f_badge)
        draw.rounded_rectangle(
            [(kx + 26, ky + 26), (kx + 26 + bw + 22, ky + 64)],
            radius=10,
            fill=bg_pill,
        )
        draw.text((kx + 37, ky + 33), etiket, font=f_badge, fill=txt_pill)
        draw.text((kx + 26 + bw + 32, ky + 32), ad, font=f_kart_ad, fill=RENK_METIN_GRI)

        # Fiyat Metni (Büyük 56pt)
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

        # Değişim Rozeti (Büyük ve Kontrastlı Kapsül)
        degisim = veri.get("degisim", 0.0)
        pozitif = degisim >= 0
        yon_oku = "▲ +" if pozitif else "▼ -"
        rozet_txt = f"{yon_oku}%{abs(degisim):.2f}"

        bg_color = RENK_YESIL_BG if pozitif else RENK_KIRMIZI_BG
        border_color = RENK_YESIL_BORDER if pozitif else RENK_KIRMIZI_BORDER
        txt_color = RENK_YESIL_TXT if pozitif else RENK_KIRMIZI_TXT

        rw = draw.textlength(rozet_txt, font=f_rozet)
        rx = kx + 26
        ry = ky + 220
        draw.rounded_rectangle(
            [(rx, ry), (rx + rw + 32, ry + 56)],
            radius=14,
            fill=bg_color,
            outline=border_color,
            width=2,
        )
        draw.text((rx + 16, ry + 12), rozet_txt, font=f_rozet, fill=txt_color)

    # --- 3. FOOTER ---
    draw.line([(55, 1235), (1025, 1235)], fill=(22, 84, 66), width=1)
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
        fill=(16, 185, 129),
    )

    cikti_yolu = CIKTI_KLASORU / f"piyasa_karti_{simdi.strftime('%Y%m%d')}.jpg"
    img.save(cikti_yolu, "JPEG", quality=95)
    log.info("Lüks büyük kartlı piyasa kartı üretildi: %s", cikti_yolu)
    return cikti_yolu
