"""
piyasa_kart.py — 1080x1350 Instagram Carousel 1. Slaytı için Derin Petrol & Siber Turkuaz (Varyasyon 14) Temalı,
3'lü Vitrin Kartı (Dolar, Euro, Altın), BİST Ağaç Haritası, 5'li Makro Emtia ve 5'li Kripto/Küresel Sparkline Tasarımı.
"""

from __future__ import annotations

import logging
import math
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
RENK_GLOW = (6, 182, 212, 45)            # #06B6D4 (Siber Turkuaz Parlama)

RENK_KART_CONTAINER = (8, 32, 38)        # #082026 (Petrol Koyu Konteyner)
RENK_KART_BORDER = (20, 68, 78)          # #14444E (Turkuaz İnce Çerçeve)
RENK_KART_IC_BG = (12, 45, 54)           # #0C2D36 (İç Kutu Zemin)
RENK_KART_IC_BORDER = (28, 85, 96)       # #1C5560 (İç Kutu Çerçeve)

RENK_BASLIK_KOYU = (255, 255, 255)       # #FFFFFF (Saf Beyaz Başlık)
RENK_GRI_METIN = (140, 185, 195)         # #8CB9C3 (Petrol Gri Metin)
RENK_BEYAZ = (255, 255, 255)
RENK_FIYAT_ACIK = (226, 232, 240)        # #E2E8F0 (Net Açık Fiyat Rengi)
RENK_CYAN = (6, 182, 212)                # #06B6D4 (Turkuaz Vurgu)


def _font(punto: int, agirlik: float = 600.0) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT_YOLU), punto)
    try:
        f.set_variation_by_axes([20.0, agirlik])
    except Exception:
        pass
    return f


def _lerp_renk(c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    """İki RGB renk arasında doğrusal yumuşak geçiş hesaplar."""
    t = max(0.0, min(1.0, t))
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )


def _renk_hesapla_canli(degisim: float) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """
    Finviz & TradingView standartlarında sürekli ve pürüzsüz (interpolasyonlu) renk motoru.
    Renkler sert basamaklar yerine yüzde oranına göre milimetrik ve hafif hafif geçiş yapar.
    Döner: (Kutu_Zemin_Rengi, Kutu_Cerceve_Rengi)
    """
    if abs(degisim) < 0.01:
        # Tam Nötr 0.00%
        return (42, 54, 68), (55, 70, 88)

    # Kırmızı Çapa Noktaları (0% -> -5% Sert Düşüş)
    kirmizi_capalar = [
        (0.0,  (65, 24, 24),  (90, 32, 32)),
        (-0.5, (105, 25, 25), (135, 32, 32)),
        (-1.5, (155, 28, 28), (185, 35, 35)),
        (-3.0, (200, 32, 32), (230, 42, 42)),
        (-5.0, (235, 38, 38), (255, 55, 55)),
    ]

    # Yeşil Çapa Noktaları (0% -> +5% Sert Ralli)
    yesil_capalar = [
        (0.0,  (18, 55, 42),  (26, 75, 58)),
        (0.5,  (18, 90, 58),  (24, 118, 75)),
        (1.5,  (22, 138, 72), (28, 172, 90)),
        (3.0,  (16, 185, 120), (20, 220, 140)),
        (5.0,  (10, 215, 135), (30, 245, 160)),
    ]

    if degisim < 0:
        val = abs(degisim)
        for i in range(len(kirmizi_capalar) - 1):
            v1, bg1, bd1 = kirmizi_capalar[i]
            v2, bg2, bd2 = kirmizi_capalar[i + 1]
            if abs(v1) <= val <= abs(v2):
                t = (val - abs(v1)) / (abs(v2) - abs(v1))
                return _lerp_renk(bg1, bg2, t), _lerp_renk(bd1, bd2, t)
        return kirmizi_capalar[-1][1], kirmizi_capalar[-1][2]
    else:
        val = degisim
        for i in range(len(yesil_capalar) - 1):
            v1, bg1, bd1 = yesil_capalar[i]
            v2, bg2, bd2 = yesil_capalar[i + 1]
            if v1 <= val <= v2:
                t = (val - v1) / (v2 - v1)
                return _lerp_renk(bg1, bg2, t), _lerp_renk(bd1, bd2, t)
        return yesil_capalar[-1][1], yesil_capalar[-1][2]


def _fiyat_bicimlendir(sym: str, fiyat: float) -> str:
    """Varlık türüne göre anlık fiyat metnini hazırlar."""
    if not fiyat:
        return ""
    if sym == "XU100.IS":
        return f"{piyasa.turkce_sayi(fiyat, 0)}"
    elif sym.endswith(".IS"):
        return f"{piyasa.turkce_sayi(fiyat, 2)} ₺"
    elif sym in ("TRY=X", "EURTRY=X"):
        return f"{piyasa.turkce_sayi(fiyat, 2)}"
    elif sym == "GC=F":
        return f"{piyasa.turkce_sayi(fiyat, 0)} ₺"
    elif sym == "SI=F":
        return f"{piyasa.turkce_sayi(fiyat, 2)} ₺"
    elif sym == "GC=F_ONS":
        return f"${piyasa.turkce_sayi(fiyat, 0)}"
    elif sym == "SI=F_ONS":
        return f"${piyasa.turkce_sayi(fiyat, 2)}"
    elif sym == "BZ=F":
        return f"{piyasa.turkce_sayi(fiyat, 2)} $"
    elif sym == "DX-Y.NYB":
        return f"{piyasa.turkce_sayi(fiyat, 2)}"
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
    gdraw.ellipse([(620, 680), (1250, 1450)], fill=(6, 182, 212, 30))
    glow = glow.filter(ImageFilter.GaussianBlur(140))

    img.paste(Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB"), (0, 0))
    return img


def _ciz_vektor_ikon(draw: ImageDraw.ImageDraw, icon: str, x: int, y: int, r: int, renk: tuple[int, int, int]):
    """İkonları pürüzsüz vektörel çizer."""
    if icon == "dollar":
        draw.text((x - 8, y - 16), "$", font=_font(28, 900.0), fill=renk)
    elif icon == "euro":
        draw.text((x - 8, y - 16), "€", font=_font(26, 900.0), fill=renk)
    elif icon in ("gold", "gold_ons"):
        draw.polygon([(x - 12, y + 5), (x - 3, y - 5), (x + 9, y - 5), (x + 12, y + 5)], fill=(245, 158, 11))
        draw.polygon([(x - 5, y - 5), (x + 2, y - 12), (x + 12, y - 12), (x + 9, y - 5)], fill=(251, 191, 36))
    elif icon in ("silver", "silver_ons"):
        draw.polygon([(x - 12, y + 5), (x - 3, y - 5), (x + 9, y - 5), (x + 12, y + 5)], fill=(148, 163, 184))
        draw.polygon([(x - 5, y - 5), (x + 2, y - 12), (x + 12, y - 12), (x + 9, y - 5)], fill=(203, 213, 225))
    elif icon == "oil":
        draw.rounded_rectangle([(x - 8, y - 11), (x + 8, y + 11)], radius=3, outline=renk, width=2)
        draw.line([(x - 8, y - 3), (x + 8, y - 3)], fill=renk, width=1)
        draw.line([(x - 8, y + 4), (x + 8, y + 4)], fill=renk, width=1)
    elif icon == "gas":
        # Doğalgaz Alev / Damla İkonu
        draw.polygon([(x, y - 12), (x + 8, y + 2), (x + 5, y + 11), (x - 5, y + 11), (x - 8, y + 2)], fill=(251, 146, 60))
        draw.polygon([(x, y - 5), (x + 4, y + 3), (x + 2, y + 8), (x - 2, y + 8), (x - 4, y + 3)], fill=(254, 215, 170))
    elif icon == "btc":
        draw.text((x - 7, y - 15), "₿", font=_font(26, 900.0), fill=(245, 158, 11))
    elif icon == "eth":
        draw.polygon([(x, y - 13), (x + 8, y), (x, y + 5), (x - 8, y)], fill=(148, 163, 184))
        draw.polygon([(x, y + 7), (x + 8, y + 2), (x, y + 14), (x - 8, y + 2)], fill=(203, 213, 225))
    elif icon == "nvda":
        draw.rounded_rectangle([(x - 10, y - 7), (x + 10, y + 7)], radius=4, fill=(34, 197, 94))
    elif icon == "aapl":
        draw.text((x - 7, y - 15), "", font=_font(26, 900.0), fill=(226, 232, 240))
    elif icon == "tsla":
        draw.text((x - 6, y - 15), "T", font=_font(26, 900.0), fill=(239, 68, 68))
    elif icon == "dxy":
        draw.ellipse([(x - 10, y - 10), (x + 10, y + 10)], outline=renk, width=2)
        draw.line([(x - 10, y), (x + 10, y)], fill=renk, width=1)
        draw.line([(x, y - 10), (x, y + 10)], fill=renk, width=1)
    else:
        draw.ellipse([(x - 7, y - 7), (x + 7, y + 7)], fill=renk)


def _ciz_sparkline_gercek(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    degisim: float,
    serisi: list[float] | None = None,
):
    """
    Finans standartlarında (TradingView / Bloomberg) pürüzsüz sparkline grafiği çizer.
    Fiyat değişimi ile grafik eğimi %100 uyumludur (Yeşilse yukarı, Kırmızıysa aşağı).
    """
    artis = degisim >= 0
    renk_cizgi = (34, 197, 94) if artis else (239, 68, 68)

    # 1. Gerçek veri serisi varsa
    if serisi and len(serisi) >= 3:
        min_p = min(serisi)
        max_p = max(serisi)
        fark = max_p - min_p if max_p > min_p else 1.0

        noktalar = []
        n = len(serisi)
        for i, val in enumerate(serisi):
            px = x + int(w * (i / (n - 1)))
            oran_y = (val - min_p) / fark
            # Ters Y koordinatı (Yüksek fiyat yukarıda - küçük Y)
            py = y + h - int(oran_y * (h - 16)) - 8
            py = max(y + 4, min(y + h - 4, py))
            noktalar.append((px, py))

        for i in range(len(noktalar) - 1):
            draw.line([noktalar[i], noktalar[i + 1]], fill=renk_cizgi, width=3)

        son_px, son_py = noktalar[-1]
        draw.ellipse([(son_px - 4, son_py - 4), (son_px + 4, son_py + 4)], fill=renk_cizgi)
        return

    # 2. Sentetik pürüzsüz eğri (Fallback — Asla ters kıvrılmaz)
    noktalar = []
    ad_sayisi = 16
    for i in range(ad_sayisi):
        oran = i / (ad_sayisi - 1)
        px = x + int(w * oran)
        t = (math.sin((oran - 0.5) * math.pi) + 1.0) / 2.0
        sonum = math.sin(oran * math.pi)
        dalga = math.sin(i * 1.5) * (h * 0.08) * sonum

        if artis:
            py = y + h - 8 - int(t * (h - 16)) + int(dalga)
        else:
            py = y + 8 + int(t * (h - 16)) + int(dalga)

        py = max(y + 4, min(y + h - 4, py))
        noktalar.append((px, py))

    for i in range(len(noktalar) - 1):
        draw.line([noktalar[i], noktalar[i + 1]], fill=renk_cizgi, width=3)

    son_px, son_py = noktalar[-1]
    draw.ellipse([(son_px - 4, son_py - 4), (son_px + 4, son_py + 4)], fill=renk_cizgi)


def piyasa_karti_uret(veriler: dict | None = None) -> Path:
    """
    1080x1350 Instagram 1. slayt için Varyasyon 14 Derin Petrol & Siber Turkuaz temalı
    mockup ile %100 birebir borsa & piyasa infografik kartını üretir.
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
    f_sektor = _font(19, 800.0)

    # --- 1. HEADER (ÜST ALAN) ---
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
    rozet_txt = "DAILYBRIEF · PİYASALAR"
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
    baslik_ana = "Günü Nasıl Kapattı?" if aksam_mi else "Güne Nasıl Başladı?"
    baslik_alt = "BİST ve piyasalarda günün kapanış rakamları" if aksam_mi else "BİST ve piyasalarda günün açılış rakamları"
    oturum_adi = "Kapanış" if aksam_mi else "Açılış"

    draw.text((header_x, 82), baslik_ana, font=f_baslik, fill=RENK_BASLIK_KOYU)
    draw.text((header_x, 134), baslik_alt, font=f_alt_baslik, fill=RENK_GRI_METIN)

    # Tarih Alanı (Sağ Blok)
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

    # --- 2. VİTRİN ÜST 4'LÜ KAHRAMAN KART (DOLAR, EURO, GRAM ALTIN, GRAM GÜMÜŞ) ---
    vitrin_ogeleri = sektor_verileri.get("VİTRİN_ÜST", [])
    vx = 45
    vy = 175
    vw = 236
    vh = 96
    v_gap = 15

    for i, v_oge in enumerate(vitrin_ogeleri[:4]):
        kutu_x = vx + i * (vw + v_gap)
        draw.rounded_rectangle(
            [(kutu_x, vy), (kutu_x + vw, vy + vh)],
            radius=15,
            fill=RENK_KART_CONTAINER,
            outline=RENK_KART_BORDER,
            width=2,
        )

        # Sol Dairesel İkon Kutusu
        ik_cx = kutu_x + 36
        ik_cy = vy + 48
        draw.ellipse([(ik_cx - 24, ik_cy - 24), (ik_cx + 24, ik_cy + 24)], fill=(15, 52, 62), outline=(25, 85, 96), width=1)
        _ciz_vektor_ikon(draw, v_oge.get("icon", ""), x=ik_cx, y=ik_cy, r=24, renk=RENK_CYAN)

        # Sağ Metinler (Sembol, Fiyat, Değişim)
        tx = kutu_x + 72
        degisim = v_oge["degisim"]
        fiyat_str = _fiyat_bicimlendir(v_oge["sym"], v_oge["fiyat"])
        chg_str = f"{'▲ %' if degisim >= 0 else '▼ %'}{abs(degisim):.2f}".replace(".", ",")

        draw.text((tx, vy + 12), v_oge["etiket"], font=_font(15, 700.0), fill=RENK_GRI_METIN)
        draw.text((tx, vy + 32), fiyat_str, font=_font(27, 900.0), fill=RENK_BEYAZ)

        c_chg = (34, 197, 94) if degisim > 0.05 else ((239, 68, 68) if degisim < -0.05 else RENK_GRI_METIN)
        draw.text((tx, vy + 66), chg_str, font=_font(17, 800.0), fill=c_chg)

    # --- 3. BÖLÜM 1: BİST & TÜRKİYE HİSSELERİ (AĞAÇ HARİTASI) ---
    bist_x = 45
    bist_y = 292
    bist_w = 990
    bist_h = 390
    ribbon_h = 38

    draw.rounded_rectangle(
        [(bist_x, bist_y), (bist_x + bist_w, bist_y + bist_h)],
        radius=14,
        fill=RENK_KART_CONTAINER,
        outline=RENK_KART_BORDER,
        width=2,
    )
    draw.text((bist_x + 18, bist_y + 10), "› BİST & TÜRKİYE HİSSELERİ", font=f_sektor, fill=(246, 243, 236))

    bist_icerik_rect = (bist_x + 4, bist_y + ribbon_h + 2, bist_w - 8, bist_h - ribbon_h - 6)
    bist_ogeler = sektor_verileri.get("BİST & TÜRKİYE HİSSELERİ", [])
    hucreler = _squarify(bist_ogeler, bist_icerik_rect)

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
        chg_str = f"{'▲ %' if degisim >= 0 else '▼ %'}{abs(degisim):.2f}".replace(".", ",")
        if abs(degisim) <= 0.05:
            chg_str = f"• %{abs(degisim):.2f}".replace(".", ",")

        max_w = cw - 16
        max_p = 42 if (cw >= 190 and ch >= 120) else (32 if (cw >= 120 and ch >= 80) else (24 if (cw >= 80 and ch >= 55) else 18))

        f_sym = _font(max_p, 900.0)
        f_fiyat = _font(max(13, int(max_p * 0.70)), 700.0)
        f_chg = _font(max(13, int(max_p * 0.72)), 800.0)

        sw_s = draw.textlength(sembol, font=f_sym)
        sw_f = draw.textlength(fiyat_str, font=f_fiyat)
        sw_c = draw.textlength(chg_str, font=f_chg)
        mid_x = cx + cw / 2

        if ch >= 120:
            y1 = cy + int(ch * 0.25) - int(max_p * 0.5)
            y2 = cy + int(ch * 0.54) - int(max_p * 0.35)
            y3 = cy + int(ch * 0.80) - int(max_p * 0.35)
            draw.text((mid_x - sw_s / 2, y1), sembol, font=f_sym, fill=RENK_BEYAZ)
            draw.text((mid_x - sw_f / 2, y2), fiyat_str, font=f_fiyat, fill=RENK_FIYAT_ACIK)
            draw.text((mid_x - sw_c / 2, y3), chg_str, font=f_chg, fill=RENK_BEYAZ)
        elif ch >= 75:
            y1 = cy + int(ch * 0.28) - int(max_p * 0.5)
            y2 = cy + int(ch * 0.58) - int(max_p * 0.35)
            y3 = cy + int(ch * 0.82) - int(max_p * 0.35)
            draw.text((mid_x - sw_s / 2, y1), sembol, font=f_sym, fill=RENK_BEYAZ)
            draw.text((mid_x - sw_f / 2, y2), fiyat_str, font=f_fiyat, fill=RENK_FIYAT_ACIK)
            draw.text((mid_x - sw_c / 2, y3), chg_str, font=f_chg, fill=RENK_BEYAZ)
        else:
            alt_metin = f"{fiyat_str} · {chg_str}" if cw >= 150 else chg_str
            sw_alt = draw.textlength(alt_metin, font=f_chg)
            y1 = cy + int(ch * 0.32) - int(max_p * 0.5)
            y2 = cy + int(ch * 0.72) - int(max_p * 0.35)
            draw.text((mid_x - sw_s / 2, y1), sembol, font=f_sym, fill=RENK_BEYAZ)
            draw.text((mid_x - sw_alt / 2, y2), alt_metin, font=f_chg, fill=RENK_BEYAZ)

    # --- 4. BÖLÜM 2: EMTİA & KÜRESEL MAKRO (5'Lİ KART + SPARKLINE) ---
    makro_x = 45
    makro_y = 702
    makro_w = 990
    makro_h = 246

    draw.rounded_rectangle(
        [(makro_x, makro_y), (makro_x + makro_w, makro_y + makro_h)],
        radius=14,
        fill=RENK_KART_CONTAINER,
        outline=RENK_KART_BORDER,
        width=2,
    )
    draw.text((makro_x + 18, makro_y + 10), "› EMTİA & KÜRESEL MAKRO", font=f_sektor, fill=(246, 243, 236))

    makro_ogeler = sektor_verileri.get("EMTİA & KÜRESEL MAKRO", [])
    kw = 186
    kh = 185
    k_gap = 12
    kx_start = makro_x + 10
    ky = makro_y + ribbon_h + 8

    for i, m_oge in enumerate(makro_ogeler[:5]):
        kx = kx_start + i * (kw + k_gap)
        draw.rounded_rectangle(
            [(kx, ky), (kx + kw, ky + kh)],
            radius=12,
            fill=RENK_KART_IC_BG,
            outline=RENK_KART_IC_BORDER,
            width=1,
        )

        # İkon & İsim
        ik_x = kx + 28
        ik_y = ky + 24
        _ciz_vektor_ikon(draw, m_oge.get("icon", ""), x=ik_x, y=ik_y, r=16, renk=RENK_CYAN)

        draw.text((kx + 50, ky + 14), m_oge["etiket"], font=_font(17, 800.0), fill=RENK_BEYAZ)

        degisim = m_oge["degisim"]
        fiyat_str = _fiyat_bicimlendir(m_oge["sym"], m_oge["fiyat"])
        chg_str = f"{'▲ %' if degisim >= 0 else '▼ %'}{abs(degisim):.2f}".replace(".", ",")

        # Fiyat ve Değişim
        draw.text((kx + 14, ky + 48), fiyat_str, font=_font(24, 900.0), fill=RENK_BEYAZ)

        c_chg = (34, 197, 94) if degisim > 0.05 else ((239, 68, 68) if degisim < -0.05 else RENK_GRI_METIN)
        draw.text((kx + 14, ky + 82), chg_str, font=_font(18, 800.0), fill=c_chg)

        # Alt Gerçek Sparkline Grafiği
        _ciz_sparkline_gercek(draw, kx + 12, ky + 115, kw - 24, 55, degisim, m_oge.get("sparkline"))

    # --- 5. BÖLÜM 3: KÜRESEL PİYASALAR & KRİPTO (5'Lİ KART + SPARKLINE) ---
    kuresel_x = 45
    kuresel_y = 964
    kuresel_w = 990
    kuresel_h = 246

    draw.rounded_rectangle(
        [(kuresel_x, kuresel_y), (kuresel_x + kuresel_w, kuresel_y + kuresel_h)],
        radius=14,
        fill=RENK_KART_CONTAINER,
        outline=RENK_KART_BORDER,
        width=2,
    )
    draw.text((kuresel_x + 18, kuresel_y + 10), "› KÜRESEL PİYASALAR & KRİPTO", font=f_sektor, fill=(246, 243, 236))

    kuresel_ogeler = sektor_verileri.get("KÜRESEL PİYASALAR & KRİPTO", [])
    ky2 = kuresel_y + ribbon_h + 8
    kh2 = 185

    for i, k_oge in enumerate(kuresel_ogeler[:5]):
        kx = kx_start + i * (kw + k_gap)
        draw.rounded_rectangle(
            [(kx, ky2), (kx + kw, ky2 + kh2)],
            radius=12,
            fill=RENK_KART_IC_BG,
            outline=RENK_KART_IC_BORDER,
            width=1,
        )

        # İkon & İsim
        ik_x = kx + 28
        ik_y = ky2 + 24
        _ciz_vektor_ikon(draw, k_oge.get("icon", ""), x=ik_x, y=ik_y, r=16, renk=RENK_CYAN)

        draw.text((kx + 50, ky2 + 14), k_oge["etiket"], font=_font(17, 800.0), fill=RENK_BEYAZ)

        degisim = k_oge["degisim"]
        fiyat_str = _fiyat_bicimlendir(k_oge["sym"], k_oge["fiyat"])
        chg_str = f"{'▲ %' if degisim >= 0 else '▼ %'}{abs(degisim):.2f}".replace(".", ",")

        # Fiyat ve Değişim
        draw.text((kx + 14, ky2 + 48), fiyat_str, font=_font(24, 900.0), fill=RENK_BEYAZ)

        c_chg = (34, 197, 94) if degisim > 0.05 else ((239, 68, 68) if degisim < -0.05 else RENK_GRI_METIN)
        draw.text((kx + 14, ky2 + 82), chg_str, font=_font(18, 800.0), fill=c_chg)

        # Alt Gerçek Sparkline Grafiği
        _ciz_sparkline_gercek(draw, kx + 12, ky2 + 115, kw - 24, 55, degisim, k_oge.get("sparkline"))

    # --- 6. FOOTER (RENK LEJANTI & YASAL UYARI) ---
    draw.line([(45, 1228), (1035, 1228)], fill=(24, 75, 85), width=1)

    skala_y = 1244
    draw.text((45, skala_y), "DEĞİŞİM ARALIĞI", font=_font(14, 800.0), fill=RENK_GRI_METIN)

    skala_noktalari = [
        ("≤ -3%", (225, 35, 35)),
        ("-1,5%", (185, 28, 28)),
        ("-0,5%", (145, 25, 25)),
        ("0,0%", (40, 52, 68)),
        ("+0,5%", (21, 128, 61)),
        ("+1,5%", (22, 163, 74)),
        ("≥ +3%", (16, 185, 129)),
    ]

    nx = 45
    ny = skala_y + 24
    for txt, col in skala_noktalari:
        draw.ellipse([(nx, ny + 3), (nx + 10, ny + 13)], fill=col)
        draw.text((nx + 14, ny), txt, font=_font(13, 600.0), fill=RENK_GRI_METIN)
        nx += int(draw.textlength(txt, font=_font(13, 600.0))) + 22

    tav_txt1 = "Yatırım tavsiyesi değildir."
    tav_txt2 = "Kaynak: Matriks, Investing, TradingView"
    w_tav1 = draw.textlength(tav_txt1, font=_font(14, 600.0))
    w_tav2 = draw.textlength(tav_txt2, font=_font(13, 500.0))

    draw.text((sag_kenar - w_tav1, skala_y), tav_txt1, font=_font(14, 600.0), fill=RENK_GRI_METIN)
    draw.text((sag_kenar - w_tav2, ny), tav_txt2, font=_font(13, 500.0), fill=(100, 145, 155))

    cikti_yolu = CIKTI_KLASORU / f"piyasa_karti_{simdi.strftime('%Y%m%d')}.jpg"
    img.save(cikti_yolu, "JPEG", quality=95)
    log.info("Varyasyon 14 piyasa kartı üretildi: %s", cikti_yolu)
    return cikti_yolu


def piyasa_karti_uret_9_16(sektor_verileri: dict | None = None) -> Path:
    """
    1080x1920 tam ekran (9:16 Full-bleed Native Story) Canlı Piyasa Isı Haritası üretir.
    Asla 4:5 kartı çerçevelemez veya blur kenar kullanmaz; doğrudan 1920px dikey tuvale
    ferah, yüksek çözünürlüklü ve interaktif infografik olarak sıfırdan çizilir.
    """
    if sektor_verileri is None or "BİST & TÜRKİYE HİSSELERİ" not in sektor_verileri:
        sektor_verileri = piyasa.isi_haritasi_verileri_getir()

    simdi = datetime.now(timezone.utc)
    aksam_mi = simdi.hour >= 15
    oturum_adi = "Kapanış" if aksam_mi else "Açılış"

    W_STORY = 1080
    H_STORY = 1920
    CIKTI_KLASORU.mkdir(parents=True, exist_ok=True)

    img = Image.new("RGB", (W_STORY, H_STORY), RENK_ARKA_UST)
    draw = ImageDraw.Draw(img)

    # 1. Derin Okyanus Degrade Zemin
    for y in range(H_STORY):
        t = y / H_STORY
        if t < 0.5:
            r = _lerp_renk(RENK_ARKA_UST, RENK_ARKA_ORTA, t * 2.0)
        else:
            r = _lerp_renk(RENK_ARKA_ORTA, RENK_ARKA_ALT, (t - 0.5) * 2.0)
        draw.line([(0, y), (W_STORY, y)], fill=r)

    # Turkuaz Arka Plan Işıltısı (Glow)
    glow = Image.new("RGBA", (W_STORY, H_STORY), (0, 0, 0, 0))
    g_draw = ImageDraw.Draw(glow)
    g_draw.ellipse([W_STORY // 2 - 380, 200, W_STORY // 2 + 380, 750], fill=RENK_GLOW)
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    img.paste(Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB"), (0, 0))
    draw = ImageDraw.Draw(img)

    f_etiket = _font(15, 800.0)
    f_baslik = _font(34, 900.0)
    f_alt_baslik = _font(20, 600.0)
    f_tarih_buyuk = _font(21, 800.0)
    f_tarih_kucuk = _font(17, 700.0)
    f_sektor = _font(17, 800.0)

    # 2. Header (Üst Alan — 80px Güvenli Pay)
    logo_boyut = 120
    logo_x = 45
    logo_y = 65

    if LOGO_YOLU.exists():
        try:
            golge = Image.new("RGBA", (W_STORY, H_STORY), (0, 0, 0, 0))
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
    rozet_txt = "DAILYBRIEF · CANLI PİYASA HARİTASI"
    rw = draw.textlength(rozet_txt, font=f_etiket)
    draw.rounded_rectangle(
        [(header_x, 68), (header_x + rw + 24, 102)],
        radius=8,
        fill=(18, 62, 72),
        outline=RENK_CYAN,
        width=2,
    )
    draw.text((header_x + 12, 74), rozet_txt, font=f_etiket, fill=RENK_CYAN)

    draw.text((header_x, 110), "Finans & Borsa Özeti", font=f_baslik, fill=RENK_BASLIK_KOYU)
    draw.text((header_x, 154), "BİST 100, Döviz, Emtia ve Kripto Piyasaları", font=f_alt_baslik, fill=RENK_GRI_METIN)

    # Tarih Alanı
    aylar = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
             "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
    gunler = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    tarih_satir1 = f"{simdi.day} {aylar[simdi.month - 1]} {simdi.year}"
    tarih_satir2 = f"{gunler[simdi.weekday()]} · {oturum_adi}"

    w_t1 = draw.textlength(tarih_satir1, font=f_tarih_buyuk)
    w_t2 = draw.textlength(tarih_satir2, font=f_tarih_kucuk)
    sag_kenar = 1035

    draw.text((sag_kenar - w_t1, 108), tarih_satir1, font=f_tarih_buyuk, fill=RENK_BASLIK_KOYU)
    draw.text((sag_kenar - w_t2, 138), tarih_satir2, font=f_tarih_kucuk, fill=RENK_GRI_METIN)

    # 3. Vitrin Blok (Dolar, Euro, Gram Altın, Gram Gümüş — 4'lü Kahraman Kart)
    vitrin_ogeleri = sektor_verileri.get("VİTRİN_ÜST", [])
    vx = 45
    vy = 195
    vw = 236
    vh = 105
    v_gap = 15

    for i, v_oge in enumerate(vitrin_ogeleri[:4]):
        kutu_x = vx + i * (vw + v_gap)
        draw.rounded_rectangle(
            [(kutu_x, vy), (kutu_x + vw, vy + vh)],
            radius=15,
            fill=RENK_KART_CONTAINER,
            outline=RENK_KART_BORDER,
            width=2,
        )

        ik_cx = kutu_x + 36
        ik_cy = vy + 52
        draw.ellipse([(ik_cx - 24, ik_cy - 24), (ik_cx + 24, ik_cy + 24)], fill=(15, 52, 62), outline=(25, 85, 96), width=1)
        _ciz_vektor_ikon(draw, v_oge.get("icon", ""), x=ik_cx, y=ik_cy, r=24, renk=RENK_CYAN)

        tx = kutu_x + 72
        degisim = v_oge["degisim"]
        fiyat_str = _fiyat_bicimlendir(v_oge["sym"], v_oge["fiyat"])
        chg_str = f"{'▲ %' if degisim >= 0 else '▼ %'}{abs(degisim):.2f}".replace(".", ",")

        draw.text((tx, vy + 14), v_oge["etiket"], font=_font(15, 700.0), fill=RENK_GRI_METIN)
        draw.text((tx, vy + 36), fiyat_str, font=_font(28, 900.0), fill=RENK_BEYAZ)

        c_chg = (34, 197, 94) if degisim > 0.05 else ((239, 68, 68) if degisim < -0.05 else RENK_GRI_METIN)
        draw.text((tx, vy + 72), chg_str, font=_font(17, 800.0), fill=c_chg)

    # 4. Bölüm 1: BİST & Türkiye Hisseleri (Genişletilmiş Ağaç Haritası)
    bist_x = 45
    bist_y = 320
    bist_w = 990
    bist_h = 510
    ribbon_h = 42

    draw.rounded_rectangle(
        [(bist_x, bist_y), (bist_x + bist_w, bist_y + bist_h)],
        radius=14,
        fill=RENK_KART_CONTAINER,
        outline=RENK_KART_BORDER,
        width=2,
    )
    draw.text((bist_x + 18, bist_y + 11), "› BİST & TÜRKİYE HİSSELERİ", font=f_sektor, fill=(246, 243, 236))

    bist_icerik_rect = (bist_x + 4, bist_y + ribbon_h + 2, bist_w - 8, bist_h - ribbon_h - 6)
    bist_ogeler = sektor_verileri.get("BİST & TÜRKİYE HİSSELERİ", [])
    hucreler = _squarify(bist_ogeler, bist_icerik_rect)

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
        chg_str = f"{'▲ %' if degisim >= 0 else '▼ %'}{abs(degisim):.2f}".replace(".", ",")
        if abs(degisim) <= 0.05:
            chg_str = f"• %{abs(degisim):.2f}".replace(".", ",")

        max_p = 46 if (cw >= 190 and ch >= 120) else (36 if (cw >= 120 and ch >= 80) else (26 if (cw >= 80 and ch >= 55) else 18))
        f_sym = _font(max_p, 900.0)
        f_fiyat = _font(max(14, int(max_p * 0.70)), 700.0)
        f_chg = _font(max(14, int(max_p * 0.72)), 800.0)

        sw_s = draw.textlength(sembol, font=f_sym)
        sw_f = draw.textlength(fiyat_str, font=f_fiyat)
        sw_c = draw.textlength(chg_str, font=f_chg)
        mid_x = cx + cw / 2

        if ch >= 120:
            y1 = cy + int(ch * 0.25) - int(max_p * 0.5)
            y2 = cy + int(ch * 0.54) - int(max_p * 0.35)
            y3 = cy + int(ch * 0.80) - int(max_p * 0.35)
            draw.text((mid_x - sw_s / 2, y1), sembol, font=f_sym, fill=RENK_BEYAZ)
            draw.text((mid_x - sw_f / 2, y2), fiyat_str, font=f_fiyat, fill=RENK_FIYAT_ACIK)
            draw.text((mid_x - sw_c / 2, y3), chg_str, font=f_chg, fill=RENK_BEYAZ)
        elif ch >= 75:
            y1 = cy + int(ch * 0.28) - int(max_p * 0.5)
            y2 = cy + int(ch * 0.58) - int(max_p * 0.35)
            y3 = cy + int(ch * 0.82) - int(max_p * 0.35)
            draw.text((mid_x - sw_s / 2, y1), sembol, font=f_sym, fill=RENK_BEYAZ)
            draw.text((mid_x - sw_f / 2, y2), fiyat_str, font=f_fiyat, fill=RENK_FIYAT_ACIK)
            draw.text((mid_x - sw_c / 2, y3), chg_str, font=f_chg, fill=RENK_BEYAZ)
        else:
            alt_metin = f"{fiyat_str} · {chg_str}" if cw >= 150 else chg_str
            sw_alt = draw.textlength(alt_metin, font=f_chg)
            y1 = cy + int(ch * 0.32) - int(max_p * 0.5)
            y2 = cy + int(ch * 0.72) - int(max_p * 0.35)
            draw.text((mid_x - sw_s / 2, y1), sembol, font=f_sym, fill=RENK_BEYAZ)
            draw.text((mid_x - sw_alt / 2, y2), alt_metin, font=f_chg, fill=RENK_BEYAZ)

    # 5. Bölüm 2: Emtia & Küresel Makro (5'li Kart + Genişletilmiş Sparkline)
    makro_x = 45
    makro_y = 850
    makro_w = 990
    makro_h = 425

    draw.rounded_rectangle(
        [(makro_x, makro_y), (makro_x + makro_w, makro_y + makro_h)],
        radius=14,
        fill=RENK_KART_CONTAINER,
        outline=RENK_KART_BORDER,
        width=2,
    )
    draw.text((makro_x + 18, makro_y + 11), "› EMTİA & KÜRESEL MAKRO", font=f_sektor, fill=(246, 243, 236))

    makro_ogeler = sektor_verileri.get("EMTİA & KÜRESEL MAKRO", [])
    kw = 186
    kh = 360
    k_gap = 12
    kx_start = makro_x + 10
    ky = makro_y + ribbon_h + 8

    for i, m_oge in enumerate(makro_ogeler[:5]):
        kx = kx_start + i * (kw + k_gap)
        draw.rounded_rectangle(
            [(kx, ky), (kx + kw, ky + kh)],
            radius=12,
            fill=RENK_KART_IC_BG,
            outline=RENK_KART_IC_BORDER,
            width=1,
        )

        ik_x = kx + 32
        ik_y = ky + 34
        _ciz_vektor_ikon(draw, m_oge.get("icon", ""), x=ik_x, y=ik_y, r=20, renk=RENK_CYAN)
        draw.text((kx + 60, ky + 22), m_oge["etiket"], font=_font(19, 800.0), fill=RENK_BEYAZ)

        degisim = m_oge["degisim"]
        fiyat_str = _fiyat_bicimlendir(m_oge["sym"], m_oge["fiyat"])
        chg_str = f"{'▲ %' if degisim >= 0 else '▼ %'}{abs(degisim):.2f}".replace(".", ",")

        draw.text((kx + 16, ky + 72), fiyat_str, font=_font(28, 900.0), fill=RENK_BEYAZ)
        c_chg = (34, 197, 94) if degisim > 0.05 else ((239, 68, 68) if degisim < -0.05 else RENK_GRI_METIN)
        draw.text((kx + 16, ky + 114), chg_str, font=_font(20, 800.0), fill=c_chg)

        # Genişletilmiş Sparkline
        _ciz_sparkline_gercek(draw, kx + 12, ky + 175, kw - 24, 170, degisim, m_oge.get("sparkline"))

    # 6. Bölüm 3: Küresel Piyasalar & Kripto (5'li Kart)
    kuresel_x = 45
    kuresel_y = 1295
    kuresel_w = 990
    kuresel_h = 425

    draw.rounded_rectangle(
        [(kuresel_x, kuresel_y), (kuresel_x + kuresel_w, kuresel_y + kuresel_h)],
        radius=14,
        fill=RENK_KART_CONTAINER,
        outline=RENK_KART_BORDER,
        width=2,
    )
    draw.text((kuresel_x + 18, kuresel_y + 11), "› KÜRESEL PİYASALAR & KRİPTO", font=f_sektor, fill=(246, 243, 236))

    kuresel_ogeler = sektor_verileri.get("KÜRESEL PİYASALAR & KRİPTO", [])
    ky2 = kuresel_y + ribbon_h + 8

    for i, k_oge in enumerate(kuresel_ogeler[:5]):
        kx = kx_start + i * (kw + k_gap)
        draw.rounded_rectangle(
            [(kx, ky2), (kx + kw, ky2 + kh)],
            radius=12,
            fill=RENK_KART_IC_BG,
            outline=RENK_KART_IC_BORDER,
            width=1,
        )

        ik_x = kx + 32
        ik_y = ky2 + 34
        _ciz_vektor_ikon(draw, k_oge.get("icon", ""), x=ik_x, y=ik_y, r=20, renk=RENK_CYAN)
        draw.text((kx + 60, ky2 + 22), k_oge["etiket"], font=_font(19, 800.0), fill=RENK_BEYAZ)

        degisim = k_oge["degisim"]
        fiyat_str = _fiyat_bicimlendir(k_oge["sym"], k_oge["fiyat"])
        chg_str = f"{'▲ %' if degisim >= 0 else '▼ %'}{abs(degisim):.2f}".replace(".", ",")

        draw.text((kx + 16, ky2 + 72), fiyat_str, font=_font(28, 900.0), fill=RENK_BEYAZ)
        c_chg = (34, 197, 94) if degisim > 0.05 else ((239, 68, 68) if degisim < -0.05 else RENK_GRI_METIN)
        draw.text((kx + 16, ky2 + 114), chg_str, font=_font(20, 800.0), fill=c_chg)

        _ciz_sparkline_gercek(draw, kx + 12, ky2 + 175, kw - 24, 170, degisim, k_oge.get("sparkline"))

    # 7. Footer (Lejant ve Yasal Uyarı)
    draw.line([(45, 1755), (1035, 1755)], fill=(24, 75, 85), width=1)
    skala_y = 1775
    draw.text((45, skala_y), "DEĞİŞİM ARALIĞI", font=_font(15, 800.0), fill=RENK_GRI_METIN)

    skala_noktalari = [
        ("≤ -3%", (225, 35, 35)),
        ("-1,5%", (185, 28, 28)),
        ("-0,5%", (145, 25, 25)),
        ("0,0%", (40, 52, 68)),
        ("+0,5%", (21, 128, 61)),
        ("+1,5%", (22, 163, 74)),
        ("≥ +3%", (16, 185, 129)),
    ]

    nx = 45
    ny = skala_y + 28
    for txt, col in skala_noktalari:
        draw.ellipse([(nx, ny + 3), (nx + 12, ny + 15)], fill=col)
        draw.text((nx + 16, ny), txt, font=_font(14, 600.0), fill=RENK_GRI_METIN)
        nx += int(draw.textlength(txt, font=_font(14, 600.0))) + 24

    tav_txt1 = "Yatırım tavsiyesi değildir."
    tav_txt2 = "Kaynak: Matriks, Investing, TradingView"
    w_tav1 = draw.textlength(tav_txt1, font=_font(15, 600.0))
    w_tav2 = draw.textlength(tav_txt2, font=_font(14, 500.0))

    draw.text((sag_kenar - w_tav1, skala_y), tav_txt1, font=_font(15, 600.0), fill=RENK_GRI_METIN)
    draw.text((sag_kenar - w_tav2, ny), tav_txt2, font=_font(14, 500.0), fill=(100, 145, 155))

    cikti_yolu = CIKTI_KLASORU / f"story_piyasa_karti_{simdi.strftime('%Y%m%d')}.jpg"
    img.save(cikti_yolu, "JPEG", quality=95)
    log.info("Native 1080x1920 9:16 Story Piyasa Kartı üretildi: %s", cikti_yolu)
    return cikti_yolu
