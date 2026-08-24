"""
piyasa_tablo.py — 1080x1350 Instagram Carousel 2. Slaytı için Derin Petrol & Siber Turkuaz Temalı
3 Sütunlu (BİST, ABD/Global Borsa, Kripto) Detaylı Piyasa Karnesi ve Fiyat Listesi.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import piyasa
from .piyasa_kart import _lerp_renk, _renk_hesapla_canli, _fiyat_bicimlendir

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

# 3 SÜTUNLU LİSTE YAPILANDIRMASI (8'er varlık)
SUTUNLAR = {
    "bist": {
        "baslik": "› BİST & TÜRKİYE",
        "ogeler": [
            {"sym": "XU100.IS", "etiket": "BIST 100", "varsayilan": 0.20},
            {"sym": "THYAO.IS", "etiket": "THYAO", "varsayilan": 0.00},
            {"sym": "TUPRS.IS", "etiket": "TUPRS", "varsayilan": -1.54},
            {"sym": "KCHOL.IS", "etiket": "KCHOL", "varsayilan": -1.62},
            {"sym": "GARAN.IS", "etiket": "GARAN", "varsayilan": 1.31},
            {"sym": "AKBNK.IS", "etiket": "AKBNK", "varsayilan": 3.44},
            {"sym": "BIMAS.IS", "etiket": "BIMAS", "varsayilan": -1.02},
            {"sym": "ASELS.IS", "etiket": "ASELS", "varsayilan": -0.87},
        ],
    },
    "global": {
        "baslik": "› ABD & GLOBAL",
        "ogeler": [
            {"sym": "^GSPC", "etiket": "S&P 500", "varsayilan": -0.31},
            {"sym": "^IXIC", "etiket": "NASDAQ", "varsayilan": -0.61},
            {"sym": "^DJI", "etiket": "DOW JONES", "varsayilan": 0.10},
            {"sym": "NVDA", "etiket": "NVIDIA", "varsayilan": -2.44},
            {"sym": "AAPL", "etiket": "APPLE", "varsayilan": 0.77},
            {"sym": "TSLA", "etiket": "TESLA", "varsayilan": -2.08},
            {"sym": "MSFT", "etiket": "MICROSOFT", "varsayilan": 1.00},
            {"sym": "AMZN", "etiket": "AMAZON", "varsayilan": 1.24},
        ],
    },
    "kripto": {
        "baslik": "› KRİPTO PARA",
        "ogeler": [
            {"sym": "BTC-USD", "etiket": "BITCOIN", "varsayilan": 1.38},
            {"sym": "ETH-USD", "etiket": "ETHEREUM", "varsayilan": 0.17},
            {"sym": "SOL-USD", "etiket": "SOLANA", "varsayilan": -0.18},
            {"sym": "BNB-USD", "etiket": "BNB", "varsayilan": -0.06},
            {"sym": "XRP-USD", "etiket": "RIPPLE", "varsayilan": -3.06},
            {"sym": "ADA-USD", "etiket": "CARDANO", "varsayilan": -3.59},
            {"sym": "AVAX-USD", "etiket": "AVALANCHE", "varsayilan": -0.92},
            {"sym": "DOGE-USD", "etiket": "DOGECOIN", "varsayilan": -5.09},
        ],
    },
}


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


def _tum_fiyatlari_cek() -> dict[str, dict]:
    """Tüm 24 sembolün canlı fiyat ve değişim verilerini çeker."""
    tum_semboller = set()
    for s_info in SUTUNLAR.values():
        for oge in s_info["ogeler"]:
            tum_semboller.add(oge["sym"])

    headers = {"User-Agent": "Mozilla/5.0"}
    fiyatlar = {}

    def _tek(s):
        try:
            r = requests.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?interval=1d",
                headers=headers,
                timeout=4,
            )
            if r.status_code == 200:
                res = r.json()["chart"]["result"][0]["meta"]
                p = res.get("regularMarketPrice")
                prev = res.get("chartPreviousClose") or res.get("previousClose")
                chg = ((p - prev) / prev) * 100 if prev else 0.0
                return s, {"price": p, "chg": chg}
        except Exception:
            pass
        return s, None

    with ThreadPoolExecutor(max_workers=20) as ex:
        for sym, res in ex.map(_tek, list(tum_semboller)):
            if res:
                fiyatlar[sym] = res

    return fiyatlar


def _temiz_fiyat_yazisi(sym: str, fiyat: float) -> str:
    """Kutular için sığabilir kısa ve okunaklı fiyat metni."""
    if not fiyat:
        return ""
    if sym in ("XU100.IS", "^GSPC", "^IXIC", "^DJI"):
        return f"{piyasa.turkce_sayi(fiyat, 0)}"
    elif sym.endswith(".IS"):
        return f"{piyasa.turkce_sayi(fiyat, 2)} ₺"
    elif sym.startswith("BTC") or sym.startswith("ETH"):
        return f"${piyasa.turkce_sayi(fiyat, 0)}"
    elif fiyat < 1.0:
        return f"${piyasa.turkce_sayi(fiyat, 3)}"
    elif fiyat < 100.0:
        return f"${piyasa.turkce_sayi(fiyat, 2)}"
    else:
        return f"${piyasa.turkce_sayi(fiyat, 1)}"


def piyasa_tablosu_uret(veriler: dict | None = None) -> Path:
    """
    1080x1350 Instagram 2. slayt için 3 sütunlu (BİST, ABD/Global, Kripto)
    detaylı piyasa karnesi tablosunu üretir.
    """
    CIKTI_KLASORU.mkdir(parents=True, exist_ok=True)

    canli_fiyatlar = _tum_fiyatlari_cek()

    img = _arka_plan_ciz()
    draw = ImageDraw.Draw(img)

    f_etiket = _font(20, 800.0)
    f_baslik = _font(44, 900.0)
    f_alt_baslik = _font(21, 500.0)
    f_tarih_buyuk = _font(24, 800.0)
    f_tarih_kucuk = _font(19, 600.0)
    f_sutun_baslik = _font(20, 900.0)
    f_sym = _font(16, 800.0)
    f_price = _font(16, 700.0)
    f_badge = _font(14, 800.0)

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
    rozet_txt = "DAILYBRIEF · PİYASA KARNESİ"
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
    baslik_alt = "Borsa İstanbul, Wall Street ve Kripto Piyasaları"
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

    # --- 2. 3 SÜTUNLU PİYASA TABLOSU ---
    col_w = 318
    col_gap = 18
    start_x = 45
    start_y = 175
    col_h = 1035
    ribbon_h = 44

    sutun_anahtarlari = ["bist", "global", "kripto"]

    for col_idx, s_key in enumerate(sutun_anahtarlari):
        col_x = start_x + col_idx * (col_w + col_gap)
        s_data = SUTUNLAR[s_key]

        # Sütun Konteyner
        draw.rounded_rectangle(
            [(col_x, start_y), (col_x + col_w, start_y + col_h)],
            radius=15,
            fill=RENK_KART_CONTAINER,
            outline=RENK_KART_BORDER,
            width=2,
        )

        # Başlık Şeridi
        draw.rounded_rectangle(
            [(col_x, start_y), (col_x + col_w, start_y + ribbon_h)],
            radius=12,
            fill=(18, 62, 74),
        )
        draw.text((col_x + 16, start_y + 11), s_data["baslik"], font=f_sutun_baslik, fill=(246, 243, 236))

        # Satırlar (8 Adet)
        ogeler = s_data["ogeler"]
        row_start_y = start_y + ribbon_h + 10
        row_avail_h = col_h - ribbon_h - 18
        row_h = row_avail_h / len(ogeler)

        for row_idx, oge in enumerate(ogeler):
            cur_y = row_start_y + row_idx * row_h
            bg_color = RENK_SATIR_EVEN if row_idx % 2 == 0 else RENK_SATIR_ODD

            sym = oge["sym"]
            canli = canli_fiyatlar.get(sym)
            degisim = canli["chg"] if canli else oge["varsayilan"]
            fiyat = canli["price"] if canli else 0.0

            # Satır Kutusu
            draw.rounded_rectangle(
                [(col_x + 8, cur_y + 3), (col_x + col_w - 8, cur_y + row_h - 3)],
                radius=8,
                fill=bg_color,
            )

            # Sembol / İsim (Sol)
            sembol_txt = oge["etiket"]
            draw.text((col_x + 16, cur_y + row_h * 0.18), sembol_txt, font=f_sym, fill=RENK_BEYAZ)

            # Fiyat (Sol Alt veya Orta)
            fiyat_txt = _temiz_fiyat_yazisi(sym, fiyat)
            draw.text((col_x + 16, cur_y + row_h * 0.54), fiyat_txt, font=f_price, fill=RENK_GRI_METIN)

            # Değişim Rozeti (Sağ)
            chg_str = f"{'▲ %' if degisim >= 0 else '▼ %'}{abs(degisim):.2f}".replace(".", ",")
            c_bg, c_bd = _renk_hesapla_canli(degisim)

            bw = draw.textlength(chg_str, font=f_badge) + 16
            bx = col_x + col_w - bw - 16
            by = cur_y + int(row_h * 0.24)
            bh = 32

            draw.rounded_rectangle([(bx, by), (bx + bw, by + bh)], radius=6, fill=c_bg, outline=c_bd, width=1)
            draw.text((bx + 8, by + 7), chg_str, font=f_badge, fill=RENK_BEYAZ)

    # --- 3. FOOTER (ALT BİLGİ & YASAL UYARI) ---
    draw.line([(45, 1228), (1035, 1228)], fill=(24, 75, 85), width=1)
    skala_y = 1244
    not_txt1 = "DailyBrief · 3 Sektörlü Detaylı Piyasa Karnesi"
    not_txt2 = "Yatırım tavsiyesi değildir · Kaynak: Matriks, TradingView"

    draw.text((45, skala_y), not_txt1, font=_font(15, 700.0), fill=RENK_BEYAZ)
    w_t2 = draw.textlength(not_txt2, font=_font(14, 500.0))
    draw.text((sag_kenar - w_t2, skala_y), not_txt2, font=_font(14, 500.0), fill=RENK_GRI_METIN)

    cikti_yolu = CIKTI_KLASORU / f"piyasa_tablosu_{simdi.strftime('%Y%m%d')}.jpg"
    img.save(cikti_yolu, "JPEG", quality=95)
    log.info("3 Sütunlu piyasa tablosu üretildi: %s", cikti_yolu)
    return cikti_yolu
