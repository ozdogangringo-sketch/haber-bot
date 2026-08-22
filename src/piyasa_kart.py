"""
piyasa_kart.py — 1080x1350 Instagram Carousel 1. Slaytı için Derin Petrol & Siber Turkuaz (Varyasyon 14) Temalı, Ferah Fiyatlı Borsa & Piyasa Özeti.
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

# Varyasyon 14: Derin Petrol & Siber Turkuaz Paleti
RENK_ARKA_UST = (4, 24, 28)              # #04181C (Derin Okyanus Petrolü)
RENK_ARKA_ORTA = (8, 38, 44)             # #08262C (Petrol Slate)
RENK_ARKA_ALT = (3, 16, 20)              # #031014 (Derin Gece Zemin)
RENK_GLOW = (6, 182, 212, 40)            # #06B6D4 (Siber Turkuaz Parlama)

RENK_KART_CONTAINER = (12, 45, 52)       # #0C2D34 (Petrol Konteyner)
RENK_KART_BORDER = (25, 85, 96)          # #195560 (Turkuaz Çerçeve)
RENK_SEKTOR_BG = (18, 62, 72)            # #123E48 (Sektör Şeridi)
RENK_BASLIK_KOYU = (255, 255, 255)       # #FFFFFF (Saf Beyaz Başlık)
RENK_GRI_METIN = (140, 185, 195)         # #8CB9C3 (Petrol Gri Metin)
RENK_BEYAZ = (255, 255, 255)
RENK_FIYAT_ACIK = (226, 232, 240)        # #E2E8F0 (Net Açık Fiyat Rengi)


def _font(punto: int, agirlik: float = 600.0) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT_YOLU), punto)
    try:
        f.set_variation_by_axes([20.0, agirlik])
    except Exception:
        pass
    return f


def _renk_hesapla_canli(degisim: float) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """
    Karanlık petrol zemin üstünde parlayan canlı, kontrastlı kutu renkleri.
    Döner: (Kutu_Zemin_Rengi, Kutu_Cerceve_Rengi)
    """
    if degisim >= 2.5:
        return (16, 185, 129), (5, 150, 105)
    elif degisim >= 0.5:
        return (22, 163, 74), (21, 128, 61)
    elif degisim > 0.05:
        return (21, 128, 61), (20, 83, 45)
    elif degisim >= -0.05:
        return (71, 85, 105), (51, 65, 85)
    elif degisim > -0.5:
        return (185, 28, 28), (153, 27, 27)
    elif degisim > -2.5:
        return (220, 38, 38), (185, 28, 28)
    else:
        return (239, 68, 68), (220, 38, 38)


def _fiyat_bicimlendir(sym: str, fiyat: float) -> str:
    """Varlık türüne göre anlık fiyat metnini hazırlar."""
    if not fiyat:
        return ""
    if sym == "XU100.IS":
        return f"{piyasa.turkce_sayi(fiyat, 0)} p"
    elif sym.endswith(".IS"):
        return f"{piyasa.turkce_sayi(fiyat, 2)} ₺"
    elif sym in ("TRY=X", "EURTRY=X"):
        return f"{piyasa.turkce_sayi(fiyat, 2)} ₺"
    elif sym == "GC=F":
        return f"{piyasa.turkce_sayi(fiyat, 0)} ₺"
    elif sym == "SI=F":
        return f"{piyasa.turkce_sayi(fiyat, 2)} ₺"
    elif sym == "BZ=F":
        return f"${piyasa.turkce_sayi(fiyat, 2)}"
    elif sym in ("BTC-USD", "ETH-USD"):
        return f"${piyasa.turkce_sayi(fiyat, 0)}"
    else:
        return f"${piyasa.turkce_sayi(fiyat, 2)}"


def _squarify(children: list[dict], rect: tuple[int, int, int, int]) -> list[tuple[dict, tuple[int, int, int, int]]]:
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
    """Derin petrol ve turkuaz gradyan ile lüks ambiyans üretir."""
    img = Image.new("RGB", (GENISLIK, YUKSEKLIK))
    draw = ImageDraw.Draw(img)

    for y in range(YUKSEKLIK):
        if y < 650:
            oran = y / 650.0
            r = int(RENK_ARKA_UST[0] * (1 - oran) + RENK_ARKA_ORTA[0] * oran)
            g = int(RENK_ARKA_UST[1] * (1 - oran) + RENK_ARKA_ORTA[1] * oran)
            b = int(RENK_ARKA_UST[2] * (1 - oran) + RENK_ARKA_ORTA[2] * oran)
        else:
            oran = (y - 650) / (YUKSEKLIK - 650.0)
            r = int(RENK_ARKA_ORTA[0] * (1 - oran) + RENK_ARKA_ALT[0] * oran)
            g = int(RENK_ARKA_ORTA[1] * (1 - oran) + RENK_ARKA_ALT[1] * oran)
            b = int(RENK_ARKA_ORTA[2] * (1 - oran) + RENK_ARKA_ALT[2] * oran)
        draw.line([(0, y), (GENISLIK, y)], fill=(r, g, b))

    glow = Image.new("RGBA", (GENISLIK, YUKSEKLIK), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.ellipse([(-120, -120), (600, 480)], fill=RENK_GLOW)
    gdraw.ellipse([(620, 680), (1250, 1450)], fill=(6, 182, 212, 25))
    glow = glow.filter(ImageFilter.GaussianBlur(140))

    img.paste(Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB"), (0, 0))
    return img


def piyasa_karti_uret(veriler: dict | None = None) -> Path:
    """
    1080x1350 Instagram 1. slayt için Derin Petrol & Siber Turkuaz temalı, ferah fiyatlı piyasa kartını üretir.
    """
    CIKTI_KLASORU.mkdir(parents=True, exist_ok=True)

    sektor_verileri = piyasa.isi_haritasi_verileri_getir()

    img = _arka_plan_ciz()
    draw = ImageDraw.Draw(img)

    f_etiket = _font(20, 800.0)
    f_baslik = _font(44, 900.0)
    f_tarih_buyuk = _font(24, 800.0)
    f_tarih_kucuk = _font(19, 600.0)
    f_sektor = _font(18, 800.0)
    f_alt_kucuk = _font(17, 600.0)

    # --- 1. HEADER ---
    logo_boyut = 126
    logo_x = 45
    logo_y = 38

    if LOGO_YOLU.exists():
        try:
            golge = Image.new("RGBA", (GENISLIK, YUKSEKLIK), (0, 0, 0, 0))
            ImageDraw.Draw(golge).ellipse(
                [logo_x - 4, logo_y - 2, logo_x + logo_boyut + 6, logo_y + logo_boyut + 8],
                fill=(0, 0, 0, 120),
            )
            golge = golge.filter(ImageFilter.GaussianBlur(14))
            img.paste(Image.alpha_composite(img.convert("RGBA"), golge).convert("RGB"), (0, 0))

            logo = Image.open(LOGO_YOLU).convert("RGBA")
            logo = logo.resize((logo_boyut, logo_boyut), Image.Resampling.LANCZOS)
            img.paste(logo, (logo_x, logo_y), mask=logo)
        except Exception as e:
            log.warning("Logo yüklenemedi: %s", e)

    draw = ImageDraw.Draw(img)

    header_x = 192
    rozet_txt = "DAILYBRIEF · PİYASALAR"
    rw = draw.textlength(rozet_txt, font=f_etiket)
    draw.rounded_rectangle(
        [(header_x, 42), (header_x + rw + 22, 78)],
        radius=8,
        fill=(18, 62, 72),
        outline=(6, 182, 212),
        width=2,
    )
    draw.text((header_x + 11, 48), rozet_txt, font=f_etiket, fill=(6, 182, 212))

    draw.text((header_x, 92), "Güne Nasıl Başladı?", font=f_baslik, fill=RENK_BASLIK_KOYU)

    # Tarih Alanı (Sağda ve Başlık Çizgisine İndirilmiş)
    aylar = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
             "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
    gunler = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    simdi = datetime.now(timezone.utc)
    tarih_satir1 = f"{simdi.day} {aylar[simdi.month - 1]} {simdi.year}"
    tarih_satir2 = f"{gunler[simdi.weekday()]} · Açılış"

    w_t1 = draw.textlength(tarih_satir1, font=f_tarih_buyuk)
    w_t2 = draw.textlength(tarih_satir2, font=f_tarih_kucuk)

    sag_kenar = 1035
    draw.text((sag_kenar - w_t1, 86), tarih_satir1, font=f_tarih_buyuk, fill=RENK_BASLIK_KOYU)
    draw.text((sag_kenar - w_t2, 118), tarih_satir2, font=f_tarih_kucuk, fill=RENK_GRI_METIN)

    # --- 2. SEKTÖRLER VE FERAH DÜZENLİ KUTULAR ---
    sektor_yerlesimi = [
        ("BİST & TÜRKİYE HİSSELERİ", (45, 180, 990, 490)),
        ("DÖVİZ & EMTİA (MAKRO)", (45, 688, 490, 545)),
        ("KÜRESEL DEVLER & KRİPTO", (545, 688, 490, 545)),
    ]

    ribbon_h = 36

    # Konteyner gölgeleri
    shadow_img = Image.new("RGBA", (GENISLIK, YUKSEKLIK), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow_img)
    for _, (sx, sy, sw, sh) in sektor_yerlesimi:
        sdraw.rounded_rectangle([(sx, sy + 3), (sx + sw, sy + sh + 5)], radius=14, fill=(0, 0, 0, 80))
    shadow_img = shadow_img.filter(ImageFilter.GaussianBlur(12))
    img.paste(Image.alpha_composite(img.convert("RGBA"), shadow_img).convert("RGB"), (0, 0))
    draw = ImageDraw.Draw(img)

    for sektor_adi, (sx, sy, sw, sh) in sektor_yerlesimi:
        ogeler = sektor_verileri.get(sektor_adi, [])
        if not ogeler:
            continue

        draw.rounded_rectangle(
            [(sx, sy), (sx + sw, sy + sh)],
            radius=12,
            fill=RENK_KART_CONTAINER,
            outline=RENK_KART_BORDER,
            width=2,
        )
        draw.rounded_rectangle(
            [(sx, sy), (sx + sw, sy + ribbon_h)],
            radius=10,
            fill=RENK_SEKTOR_BG,
        )
        draw.text((sx + 14, sy + 8), f"› {sektor_adi}", font=f_sektor, fill=RENK_BEYAZ)

        icerik_rect = (sx + 2, sy + ribbon_h + 3, sw - 4, sh - ribbon_h - 5)
        hucreler = _squarify(ogeler, icerik_rect)

        for oge, (cx, cy, cw, ch) in hucreler:
            degisim = oge["degisim"]
            fiyat = oge.get("fiyat", 0.0)
            sym = oge.get("sym", "")
            fiyat_str = _fiyat_bicimlendir(sym, fiyat)

            c_bg, c_border = _renk_hesapla_canli(degisim)

            draw.rounded_rectangle(
                [(cx + 2, cy + 2), (cx + cw - 2, cy + ch - 2)],
                radius=10,
                fill=c_bg,
                outline=c_border,
                width=1,
            )

            sembol = oge["etiket"]
            chg_str = f"{'▲ +' if degisim >= 0 else '▼ -'}{abs(degisim):.2f}%"

            max_w = cw - 18
            max_p = 44 if (cw >= 200 and ch >= 125) else (34 if (cw >= 130 and ch >= 80) else (24 if (cw >= 80 and ch >= 55) else 18))

            # 1. Sembol Fontu (Büyük & Vurgulu)
            p_sym = max_p
            f_sym = _font(p_sym, 900.0)
            while draw.textlength(sembol, font=f_sym) > max_w and p_sym > 14:
                p_sym -= 2
                f_sym = _font(p_sym, 900.0)

            # 2. Fiyat Fontu (Açık & Ferah)
            p_fiyat = max(13, int(p_sym * 0.70))
            f_fiyat = _font(p_fiyat, 700.0)
            while draw.textlength(fiyat_str, font=f_fiyat) > max_w and p_fiyat > 11:
                p_fiyat -= 2
                f_fiyat = _font(p_fiyat, 700.0)

            # 3. Yüzde Değişim Fontu
            p_chg = max(13, int(p_sym * 0.72))
            f_chg = _font(p_chg, 800.0)
            while draw.textlength(chg_str, font=f_chg) > max_w and p_chg > 11:
                p_chg -= 2
                f_chg = _font(p_chg, 800.0)

            sw_s = draw.textlength(sembol, font=f_sym)
            sw_f = draw.textlength(fiyat_str, font=f_fiyat)
            sw_c = draw.textlength(chg_str, font=f_chg)
            mid_x = cx + cw / 2

            # --- FERAH & DENGELİ DİKEY YERLEŞİM (Sıkışıklık Giderildi) ---
            if ch >= 130 and fiyat_str:
                # Büyük/Uzun Kutular (BIST 100, BITCOIN, NVDA, TSLA, ALTIN) -> Geniş 3 Satır
                y1 = cy + int(ch * 0.24) - int(p_sym * 0.5)
                y2 = cy + int(ch * 0.54) - int(p_fiyat * 0.5)
                y3 = cy + int(ch * 0.80) - int(p_chg * 0.5)

                draw.text((mid_x - sw_s / 2, y1), sembol, font=f_sym, fill=RENK_BEYAZ)
                draw.text((mid_x - sw_f / 2, y2), fiyat_str, font=f_fiyat, fill=RENK_FIYAT_ACIK)
                draw.text((mid_x - sw_c / 2, y3), chg_str, font=f_chg, fill=RENK_BEYAZ)

            elif ch >= 85 and fiyat_str:
                # Orta Boy Kutular (TUPRS, KCHOL, GARAN, AKBNK, USD/TL, AAPL, ETH)
                y1 = cy + int(ch * 0.28) - int(p_sym * 0.5)
                y2 = cy + int(ch * 0.58) - int(p_fiyat * 0.5)
                y3 = cy + int(ch * 0.82) - int(p_chg * 0.5)

                draw.text((mid_x - sw_s / 2, y1), sembol, font=f_sym, fill=RENK_BEYAZ)
                draw.text((mid_x - sw_f / 2, y2), fiyat_str, font=f_fiyat, fill=RENK_FIYAT_ACIK)
                draw.text((mid_x - sw_c / 2, y3), chg_str, font=f_chg, fill=RENK_BEYAZ)

            elif ch >= 55 and fiyat_str:
                # Dar Yatay Kutular (THYAO, ASELS, EREGL)
                alt_metin = f"{fiyat_str}  ·  {chg_str}" if cw >= 150 else f"{fiyat_str} {chg_str}"
                sw_alt = draw.textlength(alt_metin, font=f_chg)

                y1 = cy + int(ch * 0.32) - int(p_sym * 0.5)
                y2 = cy + int(ch * 0.72) - int(p_chg * 0.5)

                draw.text((mid_x - sw_s / 2, y1), sembol, font=f_sym, fill=RENK_BEYAZ)
                draw.text((mid_x - sw_alt / 2, y2), alt_metin, font=f_chg, fill=RENK_BEYAZ)

            else:
                # Küçük Kompakt Kutular (BIMAS, GÜMÜŞ)
                y1 = cy + int(ch * 0.30) - int(p_sym * 0.5)
                y2 = cy + int(ch * 0.58) - int(p_fiyat * 0.5)
                y3 = cy + int(ch * 0.82) - int(p_chg * 0.5)

                draw.text((mid_x - sw_s / 2, y1), sembol, font=f_sym, fill=RENK_BEYAZ)
                if fiyat_str:
                    draw.text((mid_x - sw_f / 2, y2), fiyat_str, font=f_fiyat, fill=RENK_FIYAT_ACIK)
                draw.text((mid_x - sw_c / 2, y3), chg_str, font=f_chg, fill=RENK_BEYAZ)

    # --- 3. FOOTER & RENK SKALASI ---
    draw.line([(45, 1245), (1035, 1245)], fill=(24, 75, 85), width=1)

    skala_x = 45
    skala_y = 1262
    skala_ogeleri = [
        ("<-2.5%", (239, 68, 68)),
        ("-1.5%", (220, 38, 38)),
        ("-0.5%", (185, 28, 28)),
        ("0%", (71, 85, 105)),
        ("+0.5%", (21, 128, 61)),
        ("+1.5%", (22, 163, 74)),
        (">+2.5%", (16, 185, 129)),
    ]

    draw.text((skala_x, skala_y + 2), "SKALA:", font=f_alt_kucuk, fill=RENK_GRI_METIN)
    skala_x += 70

    for txt, rnk in skala_ogeleri:
        draw.rounded_rectangle([(skala_x, skala_y), (skala_x + 40, skala_y + 20)], radius=4, fill=rnk)
        draw.text((skala_x + 4, skala_y + 24), txt, font=_font(12, 700.0), fill=RENK_GRI_METIN)
        skala_x += 46

    not_txt = "DailyBrief · BİST & Küresel Canlı Piyasa Göstergeleri"
    nw = draw.textlength(not_txt, font=f_alt_kucuk)
    draw.text((1035 - nw, 1264), not_txt, font=f_alt_kucuk, fill=RENK_BASLIK_KOYU)
    draw.text((1035 - 200, 1292), "Yatırım tavsiyesi değildir.", font=_font(14, 500.0), fill=RENK_GRI_METIN)

    cikti_yolu = CIKTI_KLASORU / f"piyasa_karti_{simdi.strftime('%Y%m%d')}.jpg"
    img.save(cikti_yolu, "JPEG", quality=95)
    log.info("Varyasyon 14 ferah fiyatlı piyasa kartı üretildi: %s", cikti_yolu)
    return cikti_yolu
