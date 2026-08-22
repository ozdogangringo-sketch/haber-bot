"""
piyasa_kart.py — 1080x1350 Instagram Carousel 1. Slaytı için Piyasa İnfografiği üretir.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import piyasa

log = logging.getLogger(__name__)

KOK = Path(__file__).resolve().parent.parent
FONT_YOLU = KOK / "assets" / "fonts" / "Inter-Variable.ttf"
CIKTI_KLASORU = KOK / "data" / "output"

GENISLIK = 1080
YUKSEKLIK = 1350

# Renk Paleti (Koyu Finans Teması)
RENK_ARKA_PLAN_UST = (11, 15, 25)      # #0B0F19
RENK_ARKA_PLAN_ALT = (17, 24, 39)      # #111827
RENK_KART_ARKA_PLAN = (31, 41, 55)     # #1F2937
RENK_KART_KENAR = (55, 65, 81)         # #374151
RENK_BEYAZ = (255, 255, 255)
RENK_GRI_METIN = (156, 163, 175)       # #9CA3AF
RENK_SOLUK_GRI = (107, 114, 128)       # #6B7280

# Pozitif (Yeşil) / Negatif (Kırmızı) Rozet Renkleri
RENK_YESIL_ARKA = (6, 78, 59)          # #064E3B
RENK_YESIL_METIN = (52, 211, 153)      # #34D399
RENK_KIRMIZI_ARKA = (127, 29, 29)      # #7F1D1D
RENK_KIRMIZI_METIN = (248, 113, 113)   # #F87171


def _font_yukle(punto: int, agirlik: float = 600.0) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT_YOLU), punto)
    try:
        f.set_variation_by_axes([20.0, agirlik])
    except Exception:
        pass
    return f


def _gradyan_olustur() -> Image.Image:
    """1080x1350 dikey koyu gradyan oluşturur."""
    img = Image.new("RGB", (GENISLIK, YUKSEKLIK))
    draw = ImageDraw.Draw(img)
    for y in range(YUKSEKLIK):
        oran = y / YUKSEKLIK
        r = int(RENK_ARKA_PLAN_UST[0] * (1 - oran) + RENK_ARKA_PLAN_ALT[0] * oran)
        g = int(RENK_ARKA_PLAN_UST[1] * (1 - oran) + RENK_ARKA_PLAN_ALT[1] * oran)
        b = int(RENK_ARKA_PLAN_UST[2] * (1 - oran) + RENK_ARKA_PLAN_ALT[2] * oran)
        draw.line([(0, y), (GENISLIK, y)], fill=(r, g, b))
    return img


def piyasa_karti_uret(veriler: dict | None = None) -> Path:
    """
    Piyasa göstergeleri infografik kartını (1080x1350) üretir ve diske kaydeder.
    """
    if not veriler:
        veriler = piyasa.piyasa_verileri_getir()

    CIKTI_KLASORU.mkdir(parents=True, exist_ok=True)
    img = _gradyan_olustur()
    draw = ImageDraw.Draw(img)

    font_etiket = _font_yukle(22, 700.0)
    font_baslik = _font_yukle(52, 800.0)
    font_tarih = _font_yukle(26, 500.0)
    font_badge = _font_yukle(20, 800.0)
    font_kart_baslik = _font_yukle(26, 600.0)
    font_fiyat = _font_yukle(46, 800.0)
    font_rozet = _font_yukle(24, 700.0)
    font_alt_bilgi = _font_yukle(22, 400.0)

    # --- 1. ÜST BAŞLIK ALANI ---
    # Kategori Rozeti (Pill)
    rozet_metin = "GÜNE BAŞLARKEN PİYASALAR"
    rozet_w = draw.textlength(rozet_metin, font=font_etiket)
    draw.rounded_rectangle(
        [(60, 70), (60 + rozet_w + 32, 115)],
        radius=12,
        fill=(31, 41, 55),
        outline=(75, 85, 99),
        width=1,
    )
    draw.text((76, 80), rozet_metin, font=font_etiket, fill=(147, 197, 253))  # Mavi ton

    # Ana Başlık
    draw.text((60, 135), "Piyasa Açılış Bülteni", font=font_baslik, fill=RENK_BEYAZ)

    # Tarih Satırı
    aylar = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
             "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
    gunler = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    simdi = datetime.now(timezone.utc)
    tarih_metni = f"{simdi.day} {aylar[simdi.month - 1]} {simdi.year} · {gunler[simdi.weekday()]}"
    draw.text((60, 208), tarih_metni, font=font_tarih, fill=RENK_GRI_METIN)

    # İnce ayırıcı çizgi
    draw.line([(60, 260), (1020, 260)], fill=(55, 65, 81), width=1)

    # --- 2. 6'LI PİYASA GÖSTERGE KARTLARI ---
    kart_ogeleri = [
        ("bist100", "BIST 100", "BIST", (30, 58, 138), (147, 197, 253), veriler.get("bist100", {})),
        ("dolar", "Dolar / TL", "USD", (6, 78, 59), (52, 211, 153), veriler.get("dolar", {})),
        ("euro", "Euro / TL", "EUR", (88, 28, 135), (216, 180, 254), veriler.get("euro", {})),
        ("gram_altin", "Gram Altın", "ALTIN", (120, 53, 15), (252, 211, 77), veriler.get("gram_altin", {})),
        ("btc", "Bitcoin", "BTC", (154, 52, 18), (253, 186, 116), veriler.get("btc", {})),
        ("brent", "Brent Petrol", "PETROL", (19, 78, 74), (94, 234, 212), veriler.get("brent", {})),
    ]

    kart_w = 455
    kart_h = 240
    kolon_x = [60, 565]
    satir_y = [295, 570, 845]

    for idx, (anahtar, ad, etiket, bg_pill, txt_pill, veri) in enumerate(kart_ogeleri):
        kolon = idx % 2
        satir = idx // 2
        kx = kolon_x[kolon]
        ky = satir_y[satir]

        # Kart Arka Planı (Yuvarlatılmış Dikdörtgen)
        draw.rounded_rectangle(
            [(kx, ky), (kx + kart_w, ky + kart_h)],
            radius=20,
            fill=RENK_KART_ARKA_PLAN,
            outline=RENK_KART_KENAR,
            width=2,
        )

        # Varlık Etiket Rozeti (Pill)
        bw = draw.textlength(etiket, font=font_badge)
        draw.rounded_rectangle(
            [(kx + 25, ky + 25), (kx + 25 + bw + 18, ky + 58)],
            radius=8,
            fill=bg_pill,
        )
        draw.text((kx + 34, ky + 30), etiket, font=font_badge, fill=txt_pill)

        # Kart Başlığı
        draw.text((kx + 25 + bw + 32, ky + 31), ad, font=font_kart_baslik, fill=RENK_GRI_METIN)

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

        draw.text((kx + 25, ky + 85), fiyat_str, font=font_fiyat, fill=RENK_BEYAZ)

        # Değişim Rozeti (Pill)
        degisim = veri.get("degisim", 0.0)
        pozitif = degisim >= 0
        yon_oku = "+" if pozitif else "-"
        rozet_txt = f"{yon_oku}%{abs(degisim):.2f}"

        bg_color = RENK_YESIL_ARKA if pozitif else RENK_KIRMIZI_ARKA
        txt_color = RENK_YESIL_METIN if pozitif else RENK_KIRMIZI_METIN

        rw = draw.textlength(rozet_txt, font=font_rozet)
        rx = kx + 25
        ry = ky + 165
        draw.rounded_rectangle(
            [(rx, ry), (rx + rw + 24, ry + 44)],
            radius=10,
            fill=bg_color,
        )
        draw.text((rx + 12, ry + 8), rozet_txt, font=font_rozet, fill=txt_color)

    # --- 3. ALT BİLGİ ALANI ---
    draw.line([(60, 1140), (1020, 1140)], fill=(55, 65, 81), width=1)
    draw.text(
        (60, 1175),
        "Daily Briefing Finans  ·  Veriler anlık piyasa fiyatlarıdır",
        font=font_alt_bilgi,
        fill=RENK_SOLUK_GRI,
    )
    draw.text(
        (60, 1215),
        "Yatırım tavsiyesi değildir.",
        font=font_alt_bilgi,
        fill=(75, 85, 99),
    )

    cikti_yolu = CIKTI_KLASORU / f"piyasa_karti_{simdi.strftime('%Y%m%d')}.jpg"
    img.save(cikti_yolu, "JPEG", quality=95)
    log.info("Piyasa kartı üretildi: %s", cikti_yolu)
    return cikti_yolu
