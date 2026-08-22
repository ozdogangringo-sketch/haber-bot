"""
piyasa_kart.py — 1080x1350 Instagram Carousel 1. Slaytı için Lüks Yeşil Piyasa İnfografiği üretir.
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
RENK_ARKA_UST = (3, 22, 16)           # #031610 (Derin Koyu Zümrüt)
RENK_ARKA_ALT = (7, 40, 30)           # #07281E (Orman Yeşili)
RENK_KART_BG = (12, 48, 38)           # #0C3026 (Şık Zümrüt Kart)
RENK_KART_BORDER = (22, 78, 62)       # #164E3E (Vurgulu Kenar)
RENK_BEYAZ = (255, 255, 255)
RENK_METIN_GRI = (175, 209, 196)      # #AFD1C4 (Açık Nane Tonlu Gri)
RENK_SOLUK = (115, 158, 142)          # #739E8E
RENK_MINT = (52, 211, 153)            # #34D399 (Parlak Nane Yeşili)
RENK_ALTIN = (251, 191, 36)           # #FBBF24 (Altın / Amber)

# Pozitif / Negatif Rozetler
RENK_YESIL_BG = (5, 88, 58)           # #05583A
RENK_YESIL_TXT = (110, 231, 183)      # #6EE7B7
RENK_KIRMIZI_BG = (136, 19, 19)       # #881313
RENK_KIRMIZI_TXT = (254, 202, 202)    # #FECA22


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

    # Üst sol ve sağ alta nane ve altın ışıltısı
    glow = Image.new("RGBA", (GENISLIK, YUKSEKLIK), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.ellipse([(-100, -100), (600, 500)], fill=(5, 150, 105, 45))   # Zümrüt nane ışıltısı
    gdraw.ellipse([(600, 850), (1200, 1450)], fill=(217, 119, 6, 25))   # Sıcak altın ışıltısı
    glow = glow.filter(ImageFilter.GaussianBlur(100))

    img.paste(Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB"), (0, 0))
    return img


def piyasa_karti_uret(veriler: dict | None = None) -> Path:
    """
    1080x1350 Instagram 1. slayt yeşil temalı piyasa infografik kartını üretir (2x Logo ile).
    """
    if not veriler:
        veriler = piyasa.piyasa_verileri_getir()

    CIKTI_KLASORU.mkdir(parents=True, exist_ok=True)
    img = _arka_plan_ciz()
    draw = ImageDraw.Draw(img)

    f_etiket = _font(21, 800.0)
    f_baslik = _font(50, 800.0)
    f_tarih = _font(24, 500.0)
    f_badge = _font(19, 800.0)
    f_kart_ad = _font(25, 600.0)
    f_fiyat = _font(48, 800.0)
    f_rozet = _font(22, 700.0)
    f_alt = _font(21, 400.0)

    # --- 1. HEADER (2X BÜYÜK LOGO + BAŞLIK ALANI) ---
    # Logo yükle (2X Boyut: 180x180 px)
    logo_boyut = 180
    if LOGO_YOLU.exists():
        try:
            logo = Image.open(LOGO_YOLU).convert("RGBA")
            logo = logo.resize((logo_boyut, logo_boyut), Image.Resampling.LANCZOS)
            img.paste(logo, (60, 55), mask=logo)
        except Exception as e:
            log.warning("Logo yüklenemedi: %s", e)

    # Header Metinleri (Logonun Sağında)
    header_x = 265
    rozet_txt = "DAILYBRIEF · PİYASA AÇILIŞI"
    rw = draw.textlength(rozet_txt, font=f_etiket)
    draw.rounded_rectangle(
        [(header_x, 58), (header_x + rw + 28, 98)],
        radius=10,
        fill=(6, 78, 59),
        outline=(16, 185, 129),
        width=1,
    )
    draw.text((header_x + 14, 67), rozet_txt, font=f_etiket, fill=RENK_MINT)

    draw.text((header_x, 114), "Piyasalar Güne", font=f_baslik, fill=RENK_BEYAZ)
    draw.text((header_x, 168), "Nasıl Başladı?", font=f_baslik, fill=RENK_BEYAZ)

    # Tarih Satırı
    aylar = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
             "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
    gunler = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    simdi = datetime.now(timezone.utc)
    tarih_metni = f"{simdi.day} {aylar[simdi.month - 1]} {simdi.year} · {gunler[simdi.weekday()]}"
    draw.text((60, 248), tarih_metni, font=f_tarih, fill=RENK_METIN_GRI)

    # İnce ayırıcı çizgi
    draw.line([(60, 290), (1020, 290)], fill=(22, 78, 60), width=2)

    # --- 2. 6'LI GÖSTERGE GRID (2 Kolon x 3 Satır) ---
    kart_ogeleri = [
        ("bist100", "BIST 100", "BIST", (6, 78, 59), (110, 231, 183), veriler.get("bist100", {})),
        ("dolar", "Dolar / TL", "USD", (20, 83, 45), (134, 239, 172), veriler.get("dolar", {})),
        ("euro", "Euro / TL", "EUR", (19, 78, 74), (94, 234, 212), veriler.get("euro", {})),
        ("gram_altin", "Gram Altın", "ALTIN", (120, 53, 15), (252, 211, 77), veriler.get("gram_altin", {})),
        ("btc", "Bitcoin", "BTC", (154, 52, 18), (253, 186, 116), veriler.get("btc", {})),
        ("brent", "Brent Petrol", "PETROL", (15, 118, 110), (153, 246, 228), veriler.get("brent", {})),
    ]

    kart_w = 460
    kart_h = 245
    kolon_x = [60, 560]
    satir_y = [320, 595, 870]

    for idx, (anahtar, ad, etiket, bg_pill, txt_pill, veri) in enumerate(kart_ogeleri):
        kolon = idx % 2
        satir = idx // 2
        kx = kolon_x[kolon]
        ky = satir_y[satir]

        # Kart Arka Planı (Şık Yeşil Kart + İnce Parlama Kenarı)
        draw.rounded_rectangle(
            [(kx, ky), (kx + kart_w, ky + kart_h)],
            radius=22,
            fill=RENK_KART_BG,
            outline=RENK_KART_BORDER,
            width=2,
        )

        # Kart İçi Üst Satır: Varlık Rozeti + Adı
        bw = draw.textlength(etiket, font=f_badge)
        draw.rounded_rectangle(
            [(kx + 24, ky + 24), (kx + 24 + bw + 18, ky + 56)],
            radius=8,
            fill=bg_pill,
        )
        draw.text((kx + 33, ky + 29), etiket, font=f_badge, fill=txt_pill)
        draw.text((kx + 24 + bw + 28, ky + 29), ad, font=f_kart_ad, fill=RENK_METIN_GRI)

        # Fiyat Metni
        fiyat_val = veri.get("fiyat", 0.0)
        ondalik = 2 if anahtar in ("dolar", "euro", "brent", "gram_altin") else 0
        if anahtar == "btc":
            fiyat_str = f"${piyasa.turkce_sayi(fiyat_val, 0)}"
        elif anahtar == "brent":
            fiyat_str = f"${piyasa.turkce_sayi(fiyat_val, 2)}"
        elif anahtar in ("dolar", "euro", "gram_altin"):
            fiyat_str = f"{piyasa.turkce_sayi(fiyat_val, 2)} ₺"
        else:
            fiyat_str = piyasa.turkce_sayi(fiyat_val, 0)

        draw.text((kx + 24, ky + 88), fiyat_str, font=f_fiyat, fill=RENK_BEYAZ)

        # Değişim Rozeti (Pill)
        degisim = veri.get("degisim", 0.0)
        pozitif = degisim >= 0
        yon_oku = "▲ +" if pozitif else "▼ -"
        rozet_txt = f"{yon_oku}%{abs(degisim):.2f}"

        bg_color = RENK_YESIL_BG if pozitif else RENK_KIRMIZI_BG
        txt_color = RENK_YESIL_TXT if pozitif else RENK_KIRMIZI_TXT

        rw = draw.textlength(rozet_txt, font=f_rozet)
        rx = kx + 24
        ry = ky + 172
        draw.rounded_rectangle(
            [(rx, ry), (rx + rw + 24, ry + 44)],
            radius=10,
            fill=bg_color,
        )
        draw.text((rx + 12, ry + 9), rozet_txt, font=f_rozet, fill=txt_color)

    # --- 3. FOOTER ---
    draw.line([(60, 1150), (1020, 1150)], fill=(22, 78, 60), width=1)
    draw.text(
        (60, 1180),
        "DailyBrief.co News  ·  Piyasa açılış göstergeleri anlık verilerdir.",
        font=f_alt,
        fill=RENK_SOLUK,
    )
    draw.text(
        (60, 1220),
        "Yatırım tavsiyesi değildir.",
        font=f_alt,
        fill=(15, 118, 110),
    )

    cikti_yolu = CIKTI_KLASORU / f"piyasa_karti_{simdi.strftime('%Y%m%d')}.jpg"
    img.save(cikti_yolu, "JPEG", quality=95)
    log.info("Zümrüt yeşili 2x logolu piyasa kartı üretildi: %s", cikti_yolu)
    return cikti_yolu
