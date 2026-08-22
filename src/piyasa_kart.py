"""
piyasa_kart.py — 1080x1350 Instagram Carousel 1. Slaytı için Modern, Çok Renkli & Ferah Piyasa İnfografiği.
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

# Modern & Ferah Koyu Palet (Boğucu yeşilden arındırılmış lüks finans teması)
RENK_ARKA_UST = (8, 14, 24)            # #080E18 (Derin Gece Mavisi / Grafit)
RENK_ARKA_ALT = (15, 23, 42)           # #0F172A (Lüks Slate / Gece Laciverti)
RENK_KART_BG = (22, 32, 54)            # #162036 (Ferah Koyu Cam Zemin)
RENK_KART_BORDER = (45, 62, 98)        # #2D3E62 (Zarif Kontrast Çerçeve)
RENK_BEYAZ = (255, 255, 255)
RENK_METIN_GRI = (226, 232, 240)       # #E2E8F0 (Temiz Açık Gri)
RENK_SOLUK = (148, 163, 184)           # #94A3B8 (Slate Soluk)
RENK_MINT = (52, 211, 153)             # #34D399 (Parlak Nane Yeşili)

# Pozitif / Negatif Rozetler
RENK_YESIL_BG = (5, 150, 105)          # #059669
RENK_YESIL_BORDER = (16, 185, 129)     # #10B981
RENK_YESIL_TXT = (236, 253, 245)       # #ECFDF5

RENK_KIRMIZI_BG = (220, 38, 38)        # #DC2626
RENK_KIRMIZI_BORDER = (248, 113, 113)  # #F87171
RENK_KIRMIZI_TXT = (254, 242, 242)     # #FEF2F2


def _font(punto: int, agirlik: float = 600.0) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT_YOLU), punto)
    try:
        f.set_variation_by_axes([20.0, agirlik])
    except Exception:
        pass
    return f


def _arka_plan_ciz() -> Image.Image:
    """Derin lacivert-grafit gradyanı ve köşelerde zarif ışıltı ile ferah arka plan üretir."""
    img = Image.new("RGB", (GENISLIK, YUKSEKLIK))
    draw = ImageDraw.Draw(img)

    for y in range(YUKSEKLIK):
        oran = y / YUKSEKLIK
        r = int(RENK_ARKA_UST[0] * (1 - oran) + RENK_ARKA_ALT[0] * oran)
        g = int(RENK_ARKA_UST[1] * (1 - oran) + RENK_ARKA_ALT[1] * oran)
        b = int(RENK_ARKA_UST[2] * (1 - oran) + RENK_ARKA_ALT[2] * oran)
        draw.line([(0, y), (GENISLIK, y)], fill=(r, g, b))

    # Üstte ve altta ferahlatıcı hafif mavi/zümrüt ambiyans ışıltıları
    glow = Image.new("RGBA", (GENISLIK, YUKSEKLIK), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.ellipse([(-150, -150), (650, 550)], fill=(14, 116, 144, 45))   # Okyanus mavisi ışıltısı
    gdraw.ellipse([(600, 750), (1250, 1450)], fill=(16, 185, 129, 30))   # Zümrüt nane ışıltısı
    glow = glow.filter(ImageFilter.GaussianBlur(130))

    img.paste(Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB"), (0, 0))
    return img


def piyasa_karti_uret(veriler: dict | None = None) -> Path:
    """
    1080x1350 Instagram 1. slayt için çok renkli, büyük kartlı ve ferah piyasa infografiğini üretir.
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
        fill=(15, 76, 117),
        outline=(56, 189, 248),
        width=1,
    )
    draw.text((header_x + 12, 55), rozet_txt, font=f_etiket, fill=(56, 189, 248))
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
    draw.line([(55, 202), (1025, 202)], fill=(38, 52, 84), width=2)

    # --- 2. 6'LI ÇOK RENKLİ GÖSTERGE GRID (2 Kolon x 3 Satır) ---
    # Her varlık için özgün ve canlı rozet/kenar renkleri
    kart_ogeleri = [
        # (anahtar, ad, rozet_kodu, rozet_bg, rozet_txt, kart_border, veri)
        (
            "bist100", "BIST 100", "BIST",
            (3, 105, 161), (224, 242, 254), (14, 165, 233),   # Gökyüzü / Safir Mavisi
            veriler.get("bist100", {}),
        ),
        (
            "dolar", "Dolar / TL", "USD",
            (4, 120, 87), (209, 250, 229), (16, 185, 129),    # Zümrüt Yeşili
            veriler.get("dolar", {}),
        ),
        (
            "euro", "Euro / TL", "EUR",
            (79, 70, 229), (238, 242, 255), (129, 140, 248),  # Asil İndigo / Mor
            veriler.get("euro", {}),
        ),
        (
            "gram_altin", "Gram Altın", "ALTIN",
            (180, 83, 9), (254, 243, 199), (245, 158, 11),    # Sıcak Altın / Amber
            veriler.get("gram_altin", {}),
        ),
        (
            "btc", "Bitcoin", "BTC",
            (194, 65, 12), (255, 237, 213), (249, 115, 22),   # Güneş Turuncusu
            veriler.get("btc", {}),
        ),
        (
            "brent", "Brent Petrol", "PETROL",
            (13, 148, 136), (204, 251, 241), (20, 184, 166),  # Okyanus Turkuazı
            veriler.get("brent", {}),
        ),
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

    for idx, (anahtar, ad, etiket, bg_pill, txt_pill, border_accent, veri) in enumerate(kart_ogeleri):
        kolon = idx % 2
        satir = idx // 2
        kx = kolon_x[kolon]
        ky = satir_y[satir]

        # Kart Zemin & Zarif Çerçeve
        draw.rounded_rectangle(
            [(kx, ky), (kx + kart_w, ky + kart_h)],
            radius=24,
            fill=RENK_KART_BG,
            outline=RENK_KART_BORDER,
            width=2,
        )

        # Kartın üst kenarına ince renkli vurgu çizgisi (kart kimliği)
        draw.rounded_rectangle(
            [(kx + 24, ky), (kx + kart_w - 24, ky + 3)],
            radius=2,
            fill=border_accent,
        )

        # Kart İçi Üst Satır: Varlık Rozeti + Adı
        bw = draw.textlength(etiket, font=f_badge)
        draw.rounded_rectangle(
            [(kx + 26, ky + 26), (kx + 26 + bw + 22, ky + 64)],
            radius=10,
            fill=bg_pill,
            outline=border_accent,
            width=1,
        )
        draw.text((kx + 37, ky + 33), etiket, font=f_badge, fill=txt_pill)
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
    draw.line([(55, 1235), (1025, 1235)], fill=(38, 52, 84), width=1)
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
    log.info("Çok renkli ferah piyasa kartı üretildi: %s", cikti_yolu)
    return cikti_yolu
