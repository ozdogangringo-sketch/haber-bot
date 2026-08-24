"""
piyasa_tablo.py — 1080x1350 Instagram Carousel 2. Slaytı için Derin Petrol & Siber Turkuaz Temalı
Detaylı Piyasa Tablosu, Fiyat Listesi ve Günlük Piyasa Karnesi.
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

# Varyasyon 14 Renk Paleti
RENK_ARKA_UST = (4, 24, 28)
RENK_ARKA_ORTA = (8, 38, 44)
RENK_ARKA_ALT = (3, 16, 20)
RENK_GLOW = (6, 182, 212, 40)

RENK_KART_CONTAINER = (8, 32, 38)
RENK_KART_BORDER = (20, 68, 78)
RENK_SATIR_EVEN = (12, 45, 54)
RENK_SATIR_ODD = (10, 38, 46)

RENK_BASLIK_KOYU = (255, 255, 255)
RENK_GRI_METIN = (140, 185, 195)
RENK_BEYAZ = (255, 255, 255)
RENK_FIYAT_ACIK = (246, 243, 236)
RENK_CYAN = (6, 182, 212)


def _font(punto: int, agirlik: float = 600.0) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT_YOLU), punto)
    try:
        f.set_variation_by_axes([20.0, agirlik])
    except Exception:
        pass
    return f


def _arka_plan_ciz() -> Image.Image:
    img = Image.new("RGB", (GENISLIK, YUKSEKLIK))
    draw = ImageDraw.Draw(img)

    for y in range(YUKSEKLIK):
        oran = y / float(YUKSEKLIK)
        r = int(RENK_ARKA_UST[0] * (1 - oran) + RENK_ARKA_ALT[0] * oran)
        g = int(RENK_ARKA_UST[1] * (1 - oran) + RENK_ARKA_ALT[1] * oran)
        b = int(RENK_ARKA_UST[2] * (1 - oran) + RENK_ARKA_ALT[2] * oran)
        draw.line([(0, y), (GENISLIK, y)], fill=(r, g, b))

    glow = Image.new("RGBA", (GENISLIK, YUKSEKLIK), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.ellipse([(-120, -120), (600, 480)], fill=RENK_GLOW)
    gdraw.ellipse([(620, 680), (1250, 1450)], fill=(6, 182, 212, 30))
    glow = glow.filter(ImageFilter.GaussianBlur(140))

    img.paste(Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB"), (0, 0))
    return img


def piyasa_tablosu_uret(veriler: dict | None = None) -> Path:
    """
    1080x1350 Instagram 2. slayt için detaylı borsa & piyasa karnesi tablosunu üretir.
    """
    CIKTI_KLASORU.mkdir(parents=True, exist_ok=True)

    sektor_verileri = piyasa.isi_haritasi_verileri_getir()

    img = _arka_plan_ciz()
    draw = ImageDraw.Draw(img)

    f_etiket = _font(20, 800.0)
    f_baslik = _font(44, 900.0)
    f_alt_baslik = _font(21, 500.0)
    f_tarih_buyuk = _font(24, 800.0)
    f_tarih_kucuk = _font(19, 600.0)
    f_sektor = _font(18, 800.0)
    f_th = _font(14, 700.0)
    f_td_bold = _font(18, 800.0)
    f_badge = _font(15, 800.0)

    # --- 1. HEADER ---
    logo_boyut = 120
    logo_x = 45
    logo_y = 35

    if LOGO_YOLU.exists():
        try:
            golge = Image.new("RGBA", (GENISLIK, YUKSEKLIK), (0, 0, 0, 0))
            ImageDraw.Draw(golge).ellipse(
                [logo_x - 4, logo_y - 2, logo_x + logo_boyut + 6, logo_y + logo_boyut + 8],
                fill=(0, 0, 0, 140),
            )
            golge = golge.filter(ImageFilter.GaussianBlur(14))
            img.paste(Image.alpha_composite(img.convert("RGBA"), golge).convert("RGB"), (0, 0))

            logo = Image.open(LOGO_YOLU).convert("RGBA")
            logo = logo.resize((logo_boyut, logo_boyut), Image.Resampling.LANCZOS)
            img.paste(logo, (logo_x, logo_y), mask=logo)
        except Exception as e:
            log.warning("Logo yüklenemedi: %s", e)

    draw = ImageDraw.Draw(img)

    header_x = 182
    rozet_txt = "DAILYBRIEF · PİYASA LİSTESİ"
    rw = draw.textlength(rozet_txt, font=f_etiket)
    draw.rounded_rectangle(
        [(header_x, 38), (header_x + rw + 24, 72)],
        radius=8,
        fill=(18, 62, 72),
        outline=RENK_CYAN,
        width=2,
    )
    draw.text((header_x + 12, 43), rozet_txt, font=f_etiket, fill=RENK_CYAN)

    simdi = datetime.now(timezone.utc)
    aksam_mi = simdi.hour >= 15
    baslik_ana = "Piyasa Fiyat Listesi"
    baslik_alt = "BİST, döviz, emtia ve küresel hisselerin net tablosu"
    oturum_adi = "Kapanış" if aksam_mi else "Açılış"

    draw.text((header_x, 82), baslik_ana, font=f_baslik, fill=RENK_BASLIK_KOYU)
    draw.text((header_x, 134), baslik_alt, font=f_alt_baslik, fill=RENK_GRI_METIN)

    # Tarih Alanı
    aylar = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
             "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
    gunler = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    tarih_satir1 = f"{simdi.day} {aylar[simdi.month - 1]} {simdi.year}"
    tarih_satir2 = f"{gunler[simdi.weekday()]} · {oturum_adi}"

    w_t1 = draw.textlength(tarih_satir1, font=f_tarih_buyuk)
    w_t2 = draw.textlength(tarih_satir2, font=f_tarih_kucuk)

    sag_kenar = 1035
    draw.text((sag_kenar - w_t1, 80), tarih_satir1, font=f_tarih_buyuk, fill=RENK_BASLIK_KOYU)
    draw.text((sag_kenar - w_t2, 114), tarih_satir2, font=f_tarih_kucuk, fill=RENK_GRI_METIN)

    # --- 2. TABLO BÖLÜMLERİ ---
    tablo_bloklari = [
        ("BİST & TÜRKİYE HİSSELERİ", sektor_verileri.get("BİST & TÜRKİYE HİSSELERİ", [])[:7], 175, 335),
        ("DÖVİZ, ALTIN & EMTİA", (sektor_verileri.get("VİTRİN_ÜST", []) + sektor_verileri.get("EMTİA & KÜRESEL MAKRO", []))[:6], 530, 325),
        ("KÜRESEL PİYASALAR & KRİPTO", sektor_verileri.get("KÜRESEL PİYASALAR & KRİPTO", [])[:5], 875, 330),
    ]

    for baslik_sektor, ogeler, block_y, block_h in tablo_bloklari:
        if not ogeler:
            continue

        # Ana Konteyner
        draw.rounded_rectangle(
            [(45, block_y), (1035, block_y + block_h)],
            radius=14,
            fill=RENK_KART_CONTAINER,
            outline=RENK_KART_BORDER,
            width=2,
        )

        # Başlık Şeridi
        draw.rounded_rectangle(
            [(45, block_y), (1035, block_y + 36)],
            radius=10,
            fill=(18, 62, 74),
        )
        draw.text((60, block_y + 8), f"› {baslik_sektor}", font=f_sektor, fill=(246, 243, 236))

        # Tablo Sütun Başlıkları
        col_x_sym = 65
        col_x_price = 560
        col_x_chg = 860

        draw.text((col_x_sym, block_y + 44), "VARLIK / ENSTRÜMAN", font=f_th, fill=RENK_GRI_METIN)
        draw.text((col_x_price, block_y + 44), "FİYAT", font=f_th, fill=RENK_GRI_METIN)
        draw.text((col_x_chg, block_y + 44), "GÜNLÜK DEĞİŞİM", font=f_th, fill=RENK_GRI_METIN)

        row_y = block_y + 70
        row_h = (block_h - 78) / len(ogeler)

        for idx, oge in enumerate(ogeler):
            cur_y = row_y + idx * row_h
            bg_satir = RENK_SATIR_EVEN if idx % 2 == 0 else RENK_SATIR_ODD

            draw.rounded_rectangle(
                [(50, cur_y + 2), (1030, cur_y + row_h - 2)],
                radius=6,
                fill=bg_satir,
            )

            # Sembol ve İsim
            sym_txt = oge["etiket"]
            draw.text((col_x_sym, cur_y + row_h * 0.22), sym_txt, font=f_td_bold, fill=RENK_BEYAZ)

            # Fiyat
            from .piyasa_kart import _fiyat_bicimlendir
            fiyat_str = _fiyat_bicimlendir(oge["sym"], oge["fiyat"])
            draw.text((col_x_price, cur_y + row_h * 0.20), fiyat_str, font=f_td_bold, fill=RENK_FIYAT_ACIK)

            # Değişim Rozeti
            degisim = oge["degisim"]
            chg_str = f"{'▲ %' if degisim >= 0 else '▼ %'}{abs(degisim):.2f}".replace(".", ",")
            c_bg = (21, 128, 61) if degisim > 0.05 else ((185, 28, 28) if degisim < -0.05 else (51, 65, 85))
            c_txt = (255, 255, 255)

            bw = draw.textlength(chg_str, font=f_badge) + 20
            bx = col_x_chg + 20
            by = cur_y + row_h * 0.14
            draw.rounded_rectangle([(bx, by), (bx + bw, by + 28)], radius=6, fill=c_bg)
            draw.text((bx + 10, by + 4), chg_str, font=f_badge, fill=c_txt)

    # --- 3. FOOTER ---
    draw.line([(45, 1224), (1035, 1224)], fill=(24, 75, 85), width=1)
    skala_y = 1244
    not_txt1 = "DailyBrief · Canlı Piyasa & Sektör Karnesi"
    not_txt2 = "Yatırım tavsiyesi değildir · Kaynak: Matriks, Investing, TradingView"

    draw.text((45, skala_y), not_txt1, font=_font(15, 700.0), fill=RENK_BEYAZ)
    w_t2 = draw.textlength(not_txt2, font=_font(14, 500.0))
    draw.text((sag_kenar - w_t2, skala_y), not_txt2, font=_font(14, 500.0), fill=RENK_GRI_METIN)

    cikti_yolu = CIKTI_KLASORU / f"piyasa_tablosu_{simdi.strftime('%Y%m%d')}.jpg"
    img.save(cikti_yolu, "JPEG", quality=95)
    log.info("Piyasa tablosu üretildi: %s", cikti_yolu)
    return cikti_yolu
