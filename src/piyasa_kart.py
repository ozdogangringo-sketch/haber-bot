"""
piyasa_kart.py — 1080x1350 Instagram Carousel 1. Slaytı için BİST Odaklı, Pastel Renkli & Yumuşak Köşeli Borsa Isı Haritası (Heatmap).
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

# Ferah & Açık Koyu Pastel Finans Paleti
RENK_ARKA_UST = (19, 25, 36)            # #131924 (Daha Açık & Ferah Grafit)
RENK_ARKA_ALT = (28, 36, 52)            # #1C2434 (Yumuşak Slate)
RENK_SEKTOR_BG = (34, 44, 64)           # #222C40 (Sektör Şerit Zemini)
RENK_SEKTOR_BORDER = (55, 70, 98)       # #374662 (Sektör İnce Çerçevesi)
RENK_BEYAZ = (255, 255, 255)
RENK_GRI_METIN = (160, 174, 192)        # #A0AEC0
RENK_MINT = (52, 211, 153)              # #34D399


def _font(punto: int, agirlik: float = 600.0) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT_YOLU), punto)
    try:
        f.set_variation_by_axes([20.0, agirlik])
    except Exception:
        pass
    return f


def _renk_hesapla_pastel(degisim: float) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """
    Pastel ve göz yormayan yumuşak tonlar döner.
    Döner: (Kutu_Zemin_Rengi, Kutu_Cerceve_Rengi)
    """
    if degisim >= 2.5:
        # Canlı Pastel Zümrüt
        return (42, 118, 84), (72, 187, 120)
    elif degisim >= 0.5:
        # Yumuşak Adaçayı / Orman Yeşili
        return (36, 92, 68), (56, 161, 105)
    elif degisim > 0.1:
        # Muted Koyu Yosun
        return (28, 68, 52), (47, 133, 90)
    elif degisim >= -0.1:
        # Nötr Yumuşak Grafit
        return (48, 62, 84), (74, 85, 104)
    elif degisim > -0.5:
        # Muted Pastel Şarap
        return (78, 34, 44), (120, 48, 58)
    elif degisim > -2.5:
        # Yumuşak Terracotta Kırmızı
        return (124, 46, 60), (229, 62, 62)
    else:
        # Asil Pastel Yakut Kırmızı
        return (156, 44, 62), (245, 101, 101)


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


def _arka_plan_ciz() -> Image.Image:
    """Açık & ferah koyu slate arka plan ve hafif mavi/nane ambiyansı üretir."""
    img = Image.new("RGB", (GENISLIK, YUKSEKLIK))
    draw = ImageDraw.Draw(img)

    for y in range(YUKSEKLIK):
        oran = y / YUKSEKLIK
        r = int(RENK_ARKA_UST[0] * (1 - oran) + RENK_ARKA_ALT[0] * oran)
        g = int(RENK_ARKA_UST[1] * (1 - oran) + RENK_ARKA_ALT[1] * oran)
        b = int(RENK_ARKA_UST[2] * (1 - oran) + RENK_ARKA_ALT[2] * oran)
        draw.line([(0, y), (GENISLIK, y)], fill=(r, g, b))

    # Yumuşak ambiyans ışıltısı
    glow = Image.new("RGBA", (GENISLIK, YUKSEKLIK), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.ellipse([(-120, -120), (650, 500)], fill=(30, 58, 138, 30))
    gdraw.ellipse([(550, 750), (1250, 1450)], fill=(14, 116, 144, 25))
    glow = glow.filter(ImageFilter.GaussianBlur(130))

    img.paste(Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB"), (0, 0))
    return img


def piyasa_karti_uret(veriler: dict | None = None) -> Path:
    """
    1080x1350 Instagram 1. slayt için BİST öncelikli, pastel renkli ve yumuşak kenarlı borsa ısı haritasını üretir.
    """
    CIKTI_KLASORU.mkdir(parents=True, exist_ok=True)

    sektor_verileri = piyasa.isi_haritasi_verileri_getir()

    img = _arka_plan_ciz()
    draw = ImageDraw.Draw(img)

    f_etiket = _font(20, 800.0)
    f_baslik = _font(44, 800.0)
    f_tarih_buyuk = _font(24, 700.0)
    f_tarih_kucuk = _font(19, 500.0)
    f_sektor = _font(18, 800.0)
    f_alt_kucuk = _font(17, 600.0)

    # --- 1. HEADER (Logo + Başlık + Tarih) ---
    logo_boyut = 124
    logo_x = 45
    logo_y = 36

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
    header_x = 190
    rozet_txt = "DAILYBRIEF · PİYASALAR"
    rw = draw.textlength(rozet_txt, font=f_etiket)
    draw.rounded_rectangle(
        [(header_x, 42), (header_x + rw + 22, 76)],
        radius=8,
        fill=(18, 88, 136),
        outline=(56, 189, 248),
        width=1,
    )
    draw.text((header_x + 11, 48), rozet_txt, font=f_etiket, fill=(56, 189, 248))
    draw.text((header_x, 88), "Borsa & Piyasa Isı Haritası", font=f_baslik, fill=RENK_BEYAZ)

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
    draw.text((sag_kenar - w_t1, 46), tarih_satir1, font=f_tarih_buyuk, fill=RENK_BEYAZ)
    draw.text((sag_kenar - w_t2, 82), tarih_satir2, font=f_tarih_kucuk, fill=RENK_GRI_METIN)

    # --- 2. BİST VE MAKRO ÖNCELİKLİ HİYERARŞİK ISI HARİTASI ---
    # Toplam Alan: X: 45..1035 (W=990), Y: 180..1230 (H=1050)
    sektor_yerlesimi = [
        # (Sektor_Adi, (X, Y, W, H))
        # ÜST: BİST 100 & Türkiye Hisseleri (Geniş & Ana Odak)
        ("BİST & TÜRKİYE HİSSELERİ", (45, 180, 990, 490)),
        # ALT SOL: Döviz & Kıymetli Madenler
        ("DÖVİZ & EMTİA (MAKRO)", (45, 688, 490, 545)),
        # ALT SAĞ: Küresel Devler & Kripto
        ("KÜRESEL DEVLER & KRİPTO", (545, 688, 490, 545)),
    ]

    ribbon_h = 36

    for sektor_adi, (sx, sy, sw, sh) in sektor_yerlesimi:
        ogeler = sektor_verileri.get(sektor_adi, [])
        if not ogeler:
            continue

        # Sektör Başlık Şeridi (Soft çerçeveli ve ferah)
        draw.rounded_rectangle(
            [(sx, sy), (sx + sw, sy + ribbon_h)],
            radius=8,
            fill=RENK_SEKTOR_BG,
            outline=RENK_SEKTOR_BORDER,
            width=1,
        )
        draw.text((sx + 14, sy + 8), f"› {sektor_adi}", font=f_sektor, fill=(241, 245, 249))

        # Sektör İçi Isı Haritası Treemap Hesaplama
        icerik_rect = (sx, sy + ribbon_h + 3, sw, sh - ribbon_h - 3)
        hucreler = _squarify(ogeler, icerik_rect)

        for oge, (cx, cy, cw, ch) in hucreler:
            degisim = oge["degisim"]
            c_bg, c_border = _renk_hesapla_pastel(degisim)

            # Yumuşak Köşeli Kutu (Soft Rounded Rectangle, radius=12)
            draw.rounded_rectangle(
                [(cx + 3, cy + 3), (cx + cw - 3, cy + ch - 3)],
                radius=12,
                fill=c_bg,
                outline=c_border,
                width=1,
            )

            # Hücre Metinleri (KUTUYA ÖZEL OTOMATİK SIĞAN PUNTOLAR)
            sembol = oge["etiket"]
            chg_str = f"{'+' if degisim > 0 else ''}{degisim:.2f}%" if abs(degisim) >= 0.01 else "0.00%"

            # Kutu sınırlarına göre en büyük sığan puntoyu belirle (kenarlarda ferah boşluk)
            max_w = cw - 32
            max_p = 44 if (cw >= 200 and ch >= 120) else (34 if (cw >= 130 and ch >= 80) else (24 if (cw >= 80 and ch >= 55) else 18))

            # Sembol Fontu
            p_sym = max_p
            f_sym = _font(p_sym, 900.0)
            while draw.textlength(sembol, font=f_sym) > max_w and p_sym > 13:
                p_sym -= 2
                f_sym = _font(p_sym, 900.0)

            # Yüzde Değişim Fontu
            p_chg = max(12, int(p_sym * 0.70))
            f_chg = _font(p_chg, 800.0)
            while draw.textlength(chg_str, font=f_chg) > max_w and p_chg > 10:
                p_chg -= 2
                f_chg = _font(p_chg, 800.0)

            sw_s = draw.textlength(sembol, font=f_sym)
            sw_c = draw.textlength(chg_str, font=f_chg)
            mid_x = cx + cw / 2
            mid_y = cy + ch / 2

            aralik = int(p_sym * 0.45)
            draw.text((mid_x - sw_s / 2, mid_y - aralik - int(p_sym * 0.4)), sembol, font=f_sym, fill=RENK_BEYAZ)
            draw.text((mid_x - sw_c / 2, mid_y + 4), chg_str, font=f_chg, fill=RENK_BEYAZ)

    # --- 3. FOOTER & RENK SKALASI ---
    draw.line([(45, 1245), (1035, 1245)], fill=(45, 58, 80), width=1)

    skala_x = 45
    skala_y = 1262
    skala_ogeleri = [
        ("<-2.5%", (156, 44, 62)),
        ("-1.5%", (124, 46, 60)),
        ("-0.5%", (78, 34, 44)),
        ("0%", (48, 62, 84)),
        ("+0.5%", (28, 68, 52)),
        ("+1.5%", (36, 92, 68)),
        (">+2.5%", (42, 118, 84)),
    ]

    draw.text((skala_x, skala_y + 2), "SKALA:", font=f_alt_kucuk, fill=RENK_GRI_METIN)
    skala_x += 70

    for txt, rnk in skala_ogeleri:
        draw.rounded_rectangle([(skala_x, skala_y), (skala_x + 40, skala_y + 20)], radius=4, fill=rnk)
        draw.text((skala_x + 4, skala_y + 24), txt, font=_font(12, 600.0), fill=RENK_GRI_METIN)
        skala_x += 46

    # Sağ altta kaynak notu
    not_txt = "DailyBrief · BİST & Küresel Canlı Borsa Haritası"
    nw = draw.textlength(not_txt, font=f_alt_kucuk)
    draw.text((1035 - nw, 1264), not_txt, font=f_alt_kucuk, fill=(56, 189, 248))
    draw.text((1035 - 200, 1292), "Yatırım tavsiyesi değildir.", font=_font(14, 400.0), fill=RENK_GRI_METIN)

    cikti_yolu = CIKTI_KLASORU / f"piyasa_karti_{simdi.strftime('%Y%m%d')}.jpg"
    img.save(cikti_yolu, "JPEG", quality=95)
    log.info("BİST öncelikli pastel borsa ısı haritası üretildi: %s", cikti_yolu)
    return cikti_yolu
