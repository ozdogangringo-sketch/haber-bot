"""
piyasa_kart.py — 1080x1350 Instagram Carousel 1. Slaytı için Beyaz/Açık Temalı, Canlı Renkli, Fiyatlı Borsa & Piyasa Özeti.
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

# Açık / Beyaz Lüks Minimalist Palet (Yüksek Zıtlık & Karşıtlık)
RENK_ARKA_UST = (248, 250, 252)          # #F8FAFC (Açık Beyaz / Slate)
RENK_ARKA_ALT = (241, 245, 249)          # #F1F5F9 (Ferah Gri-Beyaz)
RENK_KART_CONTAINER = (255, 255, 255)    # #FFFFFF (Saf Beyaz Konteyner)
RENK_KART_BORDER = (226, 232, 240)       # #E2E8F0 (İnce Zarif Çerçeve)
RENK_SEKTOR_BG = (15, 23, 42)            # #0F172A (Derin Lacivert Şerit)
RENK_BASLIK_KOYU = (15, 23, 42)          # #0F172A (Net Koyu Başlık)
RENK_GRI_METIN = (100, 116, 139)         # #64748B (Slate Gri)
RENK_BEYAZ = (255, 255, 255)
RENK_AYIRICI_BEYAZ = (255, 255, 255)     # Kutular arası 2px beyaz çizgi


def _font(punto: int, agirlik: float = 600.0) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT_YOLU), punto)
    try:
        f.set_variation_by_axes([20.0, agirlik])
    except Exception:
        pass
    return f


def _renk_hesapla_canli(degisim: float) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """
    Beyaz zemin üstünde parlayan canlı, kontrastlı ve zıt renkler döner.
    Döner: (Kutu_Zemin_Rengi, Kutu_Cerceve_Rengi)
    """
    if degisim >= 2.5:
        # Parlak Canlı Zümrüt Yeşili
        return (16, 185, 129), (5, 150, 105)
    elif degisim >= 0.5:
        # Canlı Yeşil
        return (22, 163, 74), (21, 128, 61)
    elif degisim > 0.05:
        # Zengin Koyu Yeşil
        return (21, 128, 61), (20, 83, 45)
    elif degisim >= -0.05:
        # Nötr Slate Grafit
        return (71, 85, 105), (51, 65, 85)
    elif degisim > -0.5:
        # Zengin Koyu Kırmızı
        return (185, 28, 28), (153, 27, 27)
    elif degisim > -2.5:
        # Canlı Kırmızı
        return (220, 38, 38), (185, 28, 28)
    else:
        # Parlak Canlı Yakut Kırmızı
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
        # Gram Altın (Ons ve Dolar üzerinden hesaplanan değer)
        return f"{piyasa.turkce_sayi(fiyat, 0)} ₺" if fiyat > 1000 else f"${piyasa.turkce_sayi(fiyat, 0)}"
    elif sym == "SI=F":
        return f"{piyasa.turkce_sayi(fiyat, 2)} ₺" if fiyat < 100 else f"${piyasa.turkce_sayi(fiyat, 2)}"
    elif sym == "BZ=F":
        return f"${piyasa.turkce_sayi(fiyat, 2)}"
    elif sym in ("BTC-USD", "ETH-USD"):
        return f"${piyasa.turkce_sayi(fiyat, 0)}"
    else:
        # Yabancı hisseler
        return f"${piyasa.turkce_sayi(fiyat, 2)}"


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
    """Açık beyaz/slate lüks arka plan ve hafif ambiyans üretir."""
    img = Image.new("RGB", (GENISLIK, YUKSEKLIK))
    draw = ImageDraw.Draw(img)

    for y in range(YUKSEKLIK):
        oran = y / YUKSEKLIK
        r = int(RENK_ARKA_UST[0] * (1 - oran) + RENK_ARKA_ALT[0] * oran)
        g = int(RENK_ARKA_UST[1] * (1 - oran) + RENK_ARKA_ALT[1] * oran)
        b = int(RENK_ARKA_UST[2] * (1 - oran) + RENK_ARKA_ALT[2] * oran)
        draw.line([(0, y), (GENISLIK, y)], fill=(r, g, b))

    # Yumuşak açık mavi & zümrüt ışık ambiyansı
    glow = Image.new("RGBA", (GENISLIK, YUKSEKLIK), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.ellipse([(-100, -100), (600, 450)], fill=(56, 189, 248, 25))
    gdraw.ellipse([(600, 700), (1200, 1400)], fill=(52, 211, 153, 20))
    glow = glow.filter(ImageFilter.GaussianBlur(130))

    img.paste(Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB"), (0, 0))
    return img


def piyasa_karti_uret(veriler: dict | None = None) -> Path:
    """
    1080x1350 Instagram 1. slayt için Beyaz temalı, Canlı renkli, Fiyatlı ve BİST odaklı borsa infografiğini üretir.
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

    # --- 1. HEADER (Logo + Güne Nasıl Başladı? + Aşağı İndirilmiş Tarih) ---
    logo_boyut = 126
    logo_x = 45
    logo_y = 38

    if LOGO_YOLU.exists():
        try:
            golge = Image.new("RGBA", (GENISLIK, YUKSEKLIK), (0, 0, 0, 0))
            ImageDraw.Draw(golge).ellipse(
                [logo_x - 3, logo_y - 1, logo_x + logo_boyut + 5, logo_y + logo_boyut + 7],
                fill=(0, 0, 0, 40),
            )
            golge = golge.filter(ImageFilter.GaussianBlur(12))
            img.paste(Image.alpha_composite(img.convert("RGBA"), glow_or_shadow := golge).convert("RGB"), (0, 0))

            logo = Image.open(LOGO_YOLU).convert("RGBA")
            logo = logo.resize((logo_boyut, logo_boyut), Image.Resampling.LANCZOS)
            img.paste(logo, (logo_x, logo_y), mask=logo)
        except Exception as e:
            log.warning("Logo yüklenemedi: %s", e)

    draw = ImageDraw.Draw(img)

    # Rozet (Logonun Sağ Üstünde) - Logodaki Derin Lacivert & Altın Amber Teması
    header_x = 192
    rozet_txt = "DAILYBRIEF · PİYASALAR"
    rw = draw.textlength(rozet_txt, font=f_etiket)
    draw.rounded_rectangle(
        [(header_x, 42), (header_x + rw + 22, 78)],
        radius=8,
        fill=(15, 23, 42),
        outline=(245, 158, 11),
        width=2,
    )
    draw.text((header_x + 11, 48), rozet_txt, font=f_etiket, fill=(245, 158, 11))

    # Ana Başlık (Isı Haritası ifadesi kaldırıldı)
    draw.text((header_x, 92), "Güne Nasıl Başladı?", font=f_baslik, fill=RENK_BASLIK_KOYU)

    # Tarih Alanı (Sağda ve Doğrudan Başlık Çizgisine İndirilmiş)
    aylar = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
             "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
    gunler = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    simdi = datetime.now(timezone.utc)
    tarih_satir1 = f"{simdi.day} {aylar[simdi.month - 1]} {simdi.year}"
    tarih_satir2 = f"{gunler[simdi.weekday()]} · Açılış"

    w_t1 = draw.textlength(tarih_satir1, font=f_tarih_buyuk)
    w_t2 = draw.textlength(tarih_satir2, font=f_tarih_kucuk)

    sag_kenar = 1035
    # Tarih Y koordinatı başlığın hizasına (`92`) dayandırıldı
    draw.text((sag_kenar - w_t1, 86), tarih_satir1, font=f_tarih_buyuk, fill=RENK_BASLIK_KOYU)
    draw.text((sag_kenar - w_t2, 118), tarih_satir2, font=f_tarih_kucuk, fill=RENK_GRI_METIN)

    # --- 2. BEYAZ ZEMİN ÜSTÜNDE CANLI VE ZIT KUTULAR (3 Sektör) ---
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

        # Sektör Çerçevesi & Başlık Şeridi
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

        # Sektör İçi Treemap Hesaplama
        icerik_rect = (sx + 2, sy + ribbon_h + 3, sw - 4, sh - ribbon_h - 5)
        hucreler = _squarify(ogeler, icerik_rect)

        for oge, (cx, cy, cw, ch) in hucreler:
            degisim = oge["degisim"]
            fiyat = oge.get("fiyat", 0.0)
            sym = oge.get("sym", "")
            fiyat_str = _fiyat_bicimlendir(sym, fiyat)

            c_bg, c_border = _renk_hesapla_canli(degisim)

            # Yumuşak Köşeli Canlı Kutu (Soft Rounded, radius=10, 2px beyaz kenarlıkla temiz ayrım)
            draw.rounded_rectangle(
                [(cx + 2, cy + 2), (cx + cw - 2, cy + ch - 2)],
                radius=10,
                fill=c_bg,
                outline=c_border,
                width=1,
            )

            # Hücre Metinleri (Sembol + Anlık Fiyat + % Değişim)
            sembol = oge["etiket"]
            chg_str = f"{'▲ +' if degisim >= 0 else '▼ -'}{abs(degisim):.2f}%"

            max_w = cw - 24
            max_p = 42 if (cw >= 200 and ch >= 120) else (32 if (cw >= 130 and ch >= 80) else (22 if (cw >= 80 and ch >= 55) else 17))

            # 1. Sembol Fontu
            # 1. Sembol Fontu
            p_sym = max_p
            f_sym = _font(p_sym, 900.0)
            while draw.textlength(sembol, font=f_sym) > max_w and p_sym > 13:
                p_sym -= 2
                f_sym = _font(p_sym, 900.0)

            # 2. Fiyat Fontu
            p_fiyat = max(11, int(p_sym * 0.65))
            f_fiyat = _font(p_fiyat, 700.0)
            while draw.textlength(fiyat_str, font=f_fiyat) > max_w and p_fiyat > 10:
                p_fiyat -= 2
                f_fiyat = _font(p_fiyat, 700.0)

            # 3. Yüzde Değişim Fontu
            p_chg = max(12, int(p_sym * 0.70))
            f_chg = _font(p_chg, 800.0)
            while draw.textlength(chg_str, font=f_chg) > max_w and p_chg > 10:
                p_chg -= 2
                f_chg = _font(p_chg, 800.0)

            sw_s = draw.textlength(sembol, font=f_sym)
            sw_f = draw.textlength(fiyat_str, font=f_fiyat)
            sw_c = draw.textlength(chg_str, font=f_chg)
            mid_x = cx + cw / 2
            mid_y = cy + ch / 2

            # Kutu yüksekliğine göre dikey yerleşim
            if ch >= 90 and fiyat_str:
                # 3 Satırlı Dikey Yerleşim: Sembol -> Fiyat -> % Değişim
                draw.text((mid_x - sw_s / 2, mid_y - int(p_sym * 0.95)), sembol, font=f_sym, fill=RENK_BEYAZ)
                draw.text((mid_x - sw_f / 2, mid_y - int(p_fiyat * 0.05)), fiyat_str, font=f_fiyat, fill=(241, 245, 249))
                draw.text((mid_x - sw_c / 2, mid_y + int(p_chg * 0.70)), chg_str, font=f_chg, fill=RENK_BEYAZ)
            elif ch >= 55 and fiyat_str:
                # 2 Satırlı Yerleşim: Sembol -> % Değişim (Fiyatla yan yana)
                alt_metin = f"{fiyat_str} {chg_str}" if cw >= 130 else chg_str
                sw_alt = draw.textlength(alt_metin, font=f_chg)
                draw.text((mid_x - sw_s / 2, mid_y - int(p_sym * 0.8)), sembol, font=f_sym, fill=RENK_BEYAZ)
                draw.text((mid_x - sw_alt / 2, mid_y + int(p_chg * 0.2)), alt_metin, font=f_chg, fill=RENK_BEYAZ)
            else:
                draw.text((mid_x - sw_s / 2, mid_y - int(p_sym * 0.7)), sembol, font=f_sym, fill=RENK_BEYAZ)
                draw.text((mid_x - sw_c / 2, mid_y + int(p_chg * 0.2)), chg_str, font=f_chg, fill=RENK_BEYAZ)

    # --- 3. FOOTER & RENK SKALASI ---
    draw.line([(45, 1245), (1035, 1245)], fill=(203, 213, 225), width=1)

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

    # Sağ altta kaynak notu
    not_txt = "DailyBrief · BİST & Küresel Canlı Piyasa Göstergeleri"
    nw = draw.textlength(not_txt, font=f_alt_kucuk)
    draw.text((1035 - nw, 1264), not_txt, font=f_alt_kucuk, fill=RENK_BASLIK_KOYU)
    draw.text((1035 - 200, 1292), "Yatırım tavsiyesi değildir.", font=_font(14, 500.0), fill=RENK_GRI_METIN)

    cikti_yolu = CIKTI_KLASORU / f"piyasa_karti_{simdi.strftime('%Y%m%d')}.jpg"
    img.save(cikti_yolu, "JPEG", quality=95)
    log.info("Açık beyaz temalı canlı piyasa kartı üretildi: %s", cikti_yolu)
    return cikti_yolu
