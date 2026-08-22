"""
piyasa_kart.py — 1080x1350 Instagram Carousel 1. Slaytı için Lüks Piyasa İnfografiği üretir.
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

# Lüks Koyu Finans Renk Paleti
RENK_ARKA_UST = (8, 12, 22)          # #080C16
RENK_ARKA_ALT = (14, 20, 34)         # #0E1422
RENK_KART_BG = (20, 29, 46)          # #141D2E
RENK_KART_BORDER = (42, 58, 86)      # #2A3A56
RENK_BEYAZ = (255, 255, 255)
RENK_GRI_METIN = (148, 163, 184)     # #94A3B8
RENK_SOLUK = (100, 116, 139)         # #64748B
RENK_CYAN = (56, 189, 248)           # #38BDF8

# Pozitif / Negatif Rozetler
RENK_YESIL_BG = (6, 78, 59)          # #064E3B
RENK_YESIL_TXT = (52, 211, 153)      # #34D399
RENK_KIRMIZI_BG = (127, 29, 29)      # #7F1D1D
RENK_KIRMIZI_TXT = (248, 113, 113)   # #F87171


def _font(punto: int, agirlik: float = 600.0) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT_YOLU), punto)
    try:
        f.set_variation_by_axes([20.0, agirlik])
    except Exception:
        pass
    return f


def _arka_plan_ciz() -> Image.Image:
    """Derin gradyan ve radyal ışık efekti ile arka plan üretir."""
    img = Image.new("RGB", (GENISLIK, YUKSEKLIK))
    draw = ImageDraw.Draw(img)

    for y in range(YUKSEKLIK):
        oran = y / YUKSEKLIK
        r = int(RENK_ARKA_UST[0] * (1 - oran) + RENK_ARKA_ALT[0] * oran)
        g = int(RENK_ARKA_UST[1] * (1 - oran) + RENK_ARKA_ALT[1] * oran)
        b = int(RENK_ARKA_UST[2] * (1 - oran) + RENK_ARKA_ALT[2] * oran)
        draw.line([(0, y), (GENISLIK, y)], fill=(r, g, b))

    # Üst sol ve sağ alta hafif ışık ışıltısı
    glow = Image.new("RGBA", (GENISLIK, YUKSEKLIK), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.ellipse([(-100, -100), (500, 400)], fill=(30, 58, 138, 45))  # Mavi ışıltı
    gdraw.ellipse([(600, 900), (1200, 1500)], fill=(15, 118, 110, 35))  # Zümrüt ışıltı
    glow = glow.filter(ImageFilter.GaussianBlur(80))

    img.paste(Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB"), (0, 0))
    return img


def piyasa_karti_uret(veriler: dict | None = None) -> Path:
    """
    1080x1350 Instagram 1. slayt piyasa infografik kartını üretir.
    """
    if not veriler:
        veriler = piyasa.piyasa_verileri_getir()

    CIKTI_KLASORU.mkdir(parents=True, exist_ok=True)
    img = _arka_plan_ciz()
    draw = ImageDraw.Draw(img)

    f_etiket = _font(20, 800.0)
    f_baslik = _font(48, 800.0)
    f_tarih = _font(24, 500.0)
    f_badge = _font(19, 800.0)
    f_kart_ad = _font(24, 600.0)
    f_fiyat = _font(48, 800.0)
    f_rozet = _font(22, 700.0)
    f_alt = _font(21, 400.0)

    # --- 1. HEADER (LOGO + BAŞLIK) ---
    # Logo yükle
    if LOGO_YOLU.exists():
        try:
            logo = Image.open(LOGO_YOLU).convert("RGBA")
            logo = logo.resize((100, 100), Image.Resampling.LANCZOS)
            img.paste(logo, (60, 60), mask=logo)
        except Exception as e:
            log.warning("Logo yüklenemedi: %s", e)

    # Header Metinleri (Logonun Yanında)
    header_x = 180
    rozet_txt = "DAILYBRIEF · PİYASA BÜLTENİ"
    rw = draw.textlength(rozet_txt, font=f_etiket)
    draw.rounded_rectangle(
        [(header_x, 62), (header_x + rw + 28, 100)],
        radius=10,
        fill=(30, 41, 59),
        outline=(51, 65, 85),
        width=1,
    )
    draw.text((header_x + 14, 70), rozet_txt, font=f_etiket, fill=RENK_CYAN)

    draw.text((header_x, 112), "Piyasalar Güne Nasıl Başladı?", font=f_baslik, fill=RENK_BEYAZ)

    # Tarih Satırı
    aylar = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
             "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
    gunler = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    simdi = datetime.now(timezone.utc)
    tarih_metni = f"{simdi.day} {aylar[simdi.month - 1]} {simdi.year} · {gunler[simdi.weekday()]}"
    draw.text((60, 205), tarih_metni, font=f_tarih, fill=RENK_GRI_METIN)

    # İnce ayırıcı çizgi
    draw.line([(60, 255), (1020, 255)], fill=(30, 41, 59), width=2)

    # --- 2. 6'LI GÖSTERGE GRID (2 Kolon x 3 Satır) ---
    kart_ogeleri = [
        ("bist100", "BIST 100", "BIST", (30, 58, 138), (147, 197, 253), veriler.get("bist100", {})),
        ("dolar", "Dolar / TL", "USD", (6, 78, 59), (52, 211, 153), veriler.get("dolar", {})),
        ("euro", "Euro / TL", "EUR", (88, 28, 135), (216, 180, 254), veriler.get("euro", {})),
        ("gram_altin", "Gram Altın", "ALTIN", (120, 53, 15), (252, 211, 77), veriler.get("gram_altin", {})),
        ("btc", "Bitcoin", "BTC", (154, 52, 18), (253, 186, 116), veriler.get("btc", {})),
        ("brent", "Brent Petrol", "PETROL", (19, 78, 74), (94, 234, 212), veriler.get("brent", {})),
    ]

    kart_w = 460
    kart_h = 245
    kolon_x = [60, 560]
    satir_y = [290, 565, 840]

    for idx, (anahtar, ad, etiket, bg_pill, txt_pill, veri) in enumerate(kart_ogeleri):
        kolon = idx % 2
        satir = idx // 2
        kx = kolon_x[kolon]
        ky = satir_y[satir]

        # Kart Arka Planı (Şık Koyu Kart + İnce Parlama Kenarı)
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
        draw.text((kx + 24 + bw + 28, ky + 30), ad, font=f_kart_ad, fill=RENK_GRI_METIN)

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
    draw.line([(60, 1145), (1020, 1145)], fill=(30, 41, 59), width=1)
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
        fill=(71, 85, 105),
    )

    cikti_yolu = CIKTI_KLASORU / f"piyasa_karti_{simdi.strftime('%Y%m%d')}.jpg"
    img.save(cikti_yolu, "JPEG", quality=95)
    log.info("Lüks piyasa kartı üretildi: %s", cikti_yolu)
    return cikti_yolu
