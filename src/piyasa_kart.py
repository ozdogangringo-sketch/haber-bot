"""
piyasa_kart.py — 1080x1350 Instagram Carousel 1. Slaytı için Finviz & TradingView Stili Borsa & Piyasa Isı Haritası (Heatmap).
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

# Finviz / TradingView Koyu Tema Renkleri
RENK_ARKA = (9, 13, 22)                # #090D16 (Derin Grafit Arka Plan)
RENK_AYIRICI = (9, 13, 22)             # Bloklar arası siyah ayırıcı
RENK_SEKTOR_BG = (18, 24, 38)          # Sektör başlık şeridi
RENK_BEYAZ = (255, 255, 255)
RENK_GRI_METIN = (148, 163, 184)       # #94A3B8
RENK_MINT = (52, 211, 153)             # #34D399


def _font(punto: int, agirlik: float = 600.0) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT_YOLU), punto)
    try:
        f.set_variation_by_axes([20.0, agirlik])
    except Exception:
        pass
    return f


def _renk_hesapla(degisim: float) -> tuple[int, int, int]:
    """
    Finviz stili yüzde değişimine göre renk döner.
    Kırmızı (Düşüş) <-> Nötr Slate <-> Yeşil (Yükseliş)
    """
    if degisim <= -3.0:
        return (195, 28, 28)       # Parlak Kırmızı (#C31C1C)
    elif degisim <= -1.5:
        return (155, 25, 25)       # Orta Kırmızı (#9B1919)
    elif degisim < -0.2:
        return (85, 25, 25)        # Koyu Bordo / Şarap (#551919)
    elif degisim <= 0.2:
        return (42, 48, 62)        # Nötr Slate / Grafit (#2A303E)
    elif degisim < 1.5:
        return (22, 75, 45)        # Koyu Zümrüt / Orman (#164B2D)
    elif degisim < 3.0:
        return (16, 140, 75)       # Orta Canlı Yeşil (#108C4B)
    else:
        return (16, 185, 129)      # Parlak Neon Yeşil (#10B981)


def _squarify(children: list[dict], rect: tuple[int, int, int, int]) -> list[tuple[dict, tuple[int, int, int, int]]]:
    """
    Verilen alanı çocuk elemanların ağırlıklarına (val) göre orantılı dikdörtgenlere böler.
    """
    x, y, w, h = rect
    if not children or w <= 0 or h <= 0:
        return []
    if len(children) == 1:
        return [(children[0], (x, y, w, h))]

    total_val = sum(c["val"] for c in children)
    if total_val <= 0:
        total_val = 1

    results = []
    if w >= h:
        # Dikey bölme (Sol / Sağ)
        half_val = 0
        split_idx = 0
        for i, c in enumerate(children):
            half_val += c["val"]
            if half_val >= total_val / 2 or i == len(children) - 1:
                split_idx = i + 1
                break
        left_children = children[:split_idx]
        right_children = children[split_idx:]
        left_val = sum(c["val"] for c in left_children)
        left_w = int(round(w * (left_val / total_val)))
        left_w = max(1, min(w - 1, left_w))
        right_w = w - left_w
        results.extend(_squarify(left_children, (x, y, left_w, h)))
        results.extend(_squarify(right_children, (x + left_w, y, right_w, h)))
    else:
        # Yatay bölme (Üst / Alt)
        half_val = 0
        split_idx = 0
        for i, c in enumerate(children):
            half_val += c["val"]
            if half_val >= total_val / 2 or i == len(children) - 1:
                split_idx = i + 1
                break
        top_children = children[:split_idx]
        bottom_children = children[split_idx:]
        top_val = sum(c["val"] for c in top_children)
        top_h = int(round(h * (top_val / total_val)))
        top_h = max(1, min(h - 1, top_h))
        bottom_h = h - top_h
        results.extend(_squarify(top_children, (x, y, w, top_h)))
        results.extend(_squarify(bottom_children, (x, y + top_h, w, bottom_h)))
    return results


def piyasa_karti_uret(veriler: dict | None = None) -> Path:
    """
    1080x1350 Instagram 1. slayt için Finviz stili Canlı Piyasa & Borsa Isı Haritasını (Heatmap) üretir.
    """
    CIKTI_KLASORU.mkdir(parents=True, exist_ok=True)

    sektor_verileri = piyasa.isi_haritasi_verileri_getir()

    img = Image.new("RGB", (GENISLIK, YUKSEKLIK), RENK_ARKA)
    draw = ImageDraw.Draw(img)

    f_etiket = _font(20, 800.0)
    f_baslik = _font(44, 800.0)
    f_tarih_buyuk = _font(24, 700.0)
    f_tarih_kucuk = _font(19, 500.0)
    f_sektor = _font(16, 800.0)
    f_alt = _font(20, 500.0)
    f_alt_kucuk = _font(17, 600.0)

    # --- 1. HEADER (Logo + Başlık + Tarih) ---
    logo_boyut = 120
    logo_x = 45
    logo_y = 38

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
    header_x = 185
    rozet_txt = "DAILYBRIEF · ISI HARİTASI"
    rw = draw.textlength(rozet_txt, font=f_etiket)
    draw.rounded_rectangle(
        [(header_x, 44), (header_x + rw + 22, 78)],
        radius=8,
        fill=(15, 76, 117),
        outline=(56, 189, 248),
        width=1,
    )
    draw.text((header_x + 11, 50), rozet_txt, font=f_etiket, fill=(56, 189, 248))
    draw.text((header_x, 90), "Borsa & Piyasa Isı Haritası", font=f_baslik, fill=RENK_BEYAZ)

    # Tarih Alanı (Sağda)
    aylar = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
             "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
    gunler = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    simdi = datetime.now(timezone.utc)
    tarih_satir1 = f"{simdi.day} {aylar[simdi.month - 1]} {simdi.year}"
    tarih_satir2 = f"{gunler[simdi.weekday()]} · Açılış"

    w_t1 = draw.textlength(tarih_satir1, font=f_tarih_buyuk)
    w_t2 = draw.textlength(tarih_satir2, font=f_tarih_kucuk)

    sag_kenar = 1035
    draw.text((sag_kenar - w_t1, 48), tarih_satir1, font=f_tarih_buyuk, fill=RENK_BEYAZ)
    draw.text((sag_kenar - w_t2, 84), tarih_satir2, font=f_tarih_kucuk, fill=RENK_GRI_METIN)

    # --- 2. ISI HARİTASI GRID YERLEŞİMİ (Finviz Treemap) ---
    # Toplam Alan: X: 40..1040 (W=1000), Y: 180..1230 (H=1050)
    sektor_yerlesimi = [
        # (Sektor_Adi, (X, Y, W, H))
        # Sol Kolon
        ("TEKNOLOJİ", (40, 180, 495, 465)),
        ("FİNANS & BANKA", (40, 652, 495, 285)),
        ("İLETİŞİM & MEDYA", (40, 944, 495, 286)),
        # Sağ Kolon
        ("TÜKETİM & OTO", (545, 180, 495, 430)),
        ("SAĞLIK & İLAÇ", (545, 618, 495, 275)),
        ("DÖVİZ, EMTİA & KRİPTO", (545, 900, 495, 330)),
    ]

    ribbon_h = 26

    for sektor_adi, (sx, sy, sw, sh) in sektor_yerlesimi:
        ogeler = sektor_verileri.get(sektor_adi, [])
        if not ogeler:
            continue

        # Sektör Başlık Şeridi
        draw.rectangle([(sx, sy), (sx + sw, sy + ribbon_h)], fill=RENK_SEKTOR_BG)
        draw.text((sx + 8, sy + 4), f"› {sektor_adi}", font=f_sektor, fill=(226, 232, 240))

        # Sektör İçi Isı Haritası Treemap Hesaplama
        icerik_rect = (sx, sy + ribbon_h, sw, sh - ribbon_h)
        hucreler = _squarify(ogeler, icerik_rect)

        for oge, (cx, cy, cw, ch) in hucreler:
            degisim = oge["degisim"]
            renk = _renk_hesapla(degisim)

            # Hücre kutusu (1px iç pay ile Finviz çizgileri)
            draw.rectangle(
                [(cx + 1, cy + 1), (cx + cw - 1, cy + ch - 1)],
                fill=renk,
                outline=RENK_ARKA,
                width=1,
            )

            # Hücre Metinleri (Sembol + Yüzde)
            sembol = oge["etiket"]
            chg_str = f"{'+' if degisim > 0 else ''}{degisim:.2f}%" if abs(degisim) >= 0.01 else "0.00%"

            # Boyuta göre dinamik punto seçimi
            if cw >= 85 and ch >= 55:
                f_sym = _font(28, 800.0)
                f_chg = _font(20, 700.0)
                sw_s = draw.textlength(sembol, font=f_sym)
                sw_c = draw.textlength(chg_str, font=f_chg)
                mid_x = cx + cw / 2
                mid_y = cy + ch / 2
                draw.text((mid_x - sw_s / 2, mid_y - 22), sembol, font=f_sym, fill=RENK_BEYAZ)
                draw.text((mid_x - sw_c / 2, mid_y + 6), chg_str, font=f_chg, fill=RENK_BEYAZ)

            elif cw >= 55 and ch >= 40:
                f_sym = _font(20, 800.0)
                f_chg = _font(15, 700.0)
                sw_s = draw.textlength(sembol, font=f_sym)
                sw_c = draw.textlength(chg_str, font=f_chg)
                mid_x = cx + cw / 2
                mid_y = cy + ch / 2
                draw.text((mid_x - sw_s / 2, mid_y - 17), sembol, font=f_sym, fill=RENK_BEYAZ)
                draw.text((mid_x - sw_c / 2, mid_y + 4), chg_str, font=f_chg, fill=RENK_BEYAZ)

            elif cw >= 35 and ch >= 24:
                f_sym = _font(14, 700.0)
                sw_s = draw.textlength(sembol, font=f_sym)
                mid_x = cx + cw / 2
                mid_y = cy + ch / 2
                draw.text((mid_x - sw_s / 2, mid_y - 8), sembol, font=f_sym, fill=RENK_BEYAZ)

    # --- 3. FOOTER & RENK SKALASI (Color Scale Legend) ---
    draw.line([(40, 1245), (1040, 1245)], fill=(30, 41, 59), width=1)

    # Renk Skalası Lejantı
    skala_x = 40
    skala_y = 1262
    skala_ogeleri = [
        ("<-3%", (195, 28, 28)),
        ("-2%", (155, 25, 25)),
        ("-1%", (85, 25, 25)),
        ("0%", (42, 48, 62)),
        ("+1%", (22, 75, 45)),
        ("+2%", (16, 140, 75)),
        (">+3%", (16, 185, 129)),
    ]

    draw.text((skala_x, skala_y + 2), "SKALA:", font=f_alt_kucuk, fill=RENK_GRI_METIN)
    skala_x += 70

    for txt, rnk in skala_ogeleri:
        draw.rectangle([(skala_x, skala_y), (skala_x + 38, skala_y + 20)], fill=rnk)
        draw.text((skala_x + 4, skala_y + 24), txt, font=_font(12, 600.0), fill=RENK_GRI_METIN)
        skala_x += 44

    # Sağ altta kaynak notu
    not_txt = "DailyBrief · Finviz / TradingView Stili Canlı Borsa Haritası"
    nw = draw.textlength(not_txt, font=f_alt_kucuk)
    draw.text((1040 - nw, 1264), not_txt, font=f_alt_kucuk, fill=(56, 189, 248))
    draw.text((1040 - 200, 1292), "Yatırım tavsiyesi değildir.", font=_font(14, 400.0), fill=RENK_GRI_METIN)

    cikti_yolu = CIKTI_KLASORU / f"piyasa_karti_{simdi.strftime('%Y%m%d')}.jpg"
    img.save(cikti_yolu, "JPEG", quality=95)
    log.info("Finviz stili borsa ısı haritası üretildi: %s", cikti_yolu)
    return cikti_yolu
