"""
sparkline.py — Finans ve borsa haberleri için şık mini trend grafikleri (Sparkline) üretir.

Varyasyon 14 Derin Okyanus Petrolü (#04181C) ve Siber Turkuaz (#06B6D4) / Mercan Kırmızı (#F43F5E)
paletinde, 30 günlük fiyat hareketini ve değişim yüzdesini gösteren profesyonel infografik kartları çizer.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import numpy as np
import requests
from PIL import Image, ImageDraw

from src import make_image

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
}

# Popüler Borsa ve Finans Sembolleri Eşleme Tablosu
SEMBOL_HARITASI: dict[str, dict[str, str]] = {
    # BİST 30 & Popüler Hisseler
    "THYAO": {"yahoo": "THYAO.IS", "ad": "Türk Hava Yolları", "para": "₺"},
    "GARAN": {"yahoo": "GARAN.IS", "ad": "Garanti BBVA", "para": "₺"},
    "AKBNK": {"yahoo": "AKBNK.IS", "ad": "Akbank", "para": "₺"},
    "ISCTR": {"yahoo": "ISCTR.IS", "ad": "İş Bankası (C)", "para": "₺"},
    "YKBNK": {"yahoo": "YKBNK.IS", "ad": "Yapı Kredi", "para": "₺"},
    "ASELS": {"yahoo": "ASELS.IS", "ad": "Aselsan Elektronik", "para": "₺"},
    "EREGL": {"yahoo": "EREGL.IS", "ad": "Ereğli Demir Çelik", "para": "₺"},
    "TUPRS": {"yahoo": "TUPRS.IS", "ad": "Tüpraş", "para": "₺"},
    "KCHOL": {"yahoo": "KCHOL.IS", "ad": "Koç Holding", "para": "₺"},
    "SAHOL": {"yahoo": "SAHOL.IS", "ad": "Sabancı Holding", "para": "₺"},
    "BIMAS": {"yahoo": "BIMAS.IS", "ad": "BİM Birleşik Mağazalar", "para": "₺"},
    "SISE":  {"yahoo": "SISE.IS", "ad": "Şişecam", "para": "₺"},
    "FROTO": {"yahoo": "FROTO.IS", "ad": "Ford Otosan", "para": "₺"},
    "TOASO": {"yahoo": "TOASO.IS", "ad": "Tofaş Oto", "para": "₺"},
    "PGSUS": {"yahoo": "PGSUS.IS", "ad": "Pegasus Hava Taşımacılığı", "para": "₺"},
    "TCELL": {"yahoo": "TCELL.IS", "ad": "Turkcell", "para": "₺"},
    "TTKOM": {"yahoo": "TTKOM.IS", "ad": "Türk Telekom", "para": "₺"},
    "PETKM": {"yahoo": "PETKM.IS", "ad": "Petkim", "para": "₺"},
    "KRDMD": {"yahoo": "KRDMD.IS", "ad": "Kardemir (D)", "para": "₺"},
    "KOZAL": {"yahoo": "KOZAL.IS", "ad": "Koza Altın", "para": "₺"},
    "MGROS": {"yahoo": "MGROS.IS", "ad": "Migros Ticaret", "para": "₺"},
    "SASA":  {"yahoo": "SASA.IS", "ad": "SASA Polyester", "para": "₺"},
    "EKGYO": {"yahoo": "EKGYO.IS", "ad": "Emlak Konut GYO", "para": "₺"},

    # Endeks, Döviz, Emtia & Kripto
    "BIST100": {"yahoo": "XU100.IS", "ad": "BIST 100 Endeksi", "para": ""},
    "XU100":   {"yahoo": "XU100.IS", "ad": "BIST 100 Endeksi", "para": ""},
    "DOLAR":   {"yahoo": "TRY=X", "ad": "Dolar / TL", "para": "₺"},
    "EURO":    {"yahoo": "EURTRY=X", "ad": "Euro / TL", "para": "₺"},
    "ALTIN":   {"yahoo": "GC=F", "ad": "Ons Altın ($)", "para": "$"},
    "GUMUS":   {"yahoo": "SI=F", "ad": "Ons Gümüş ($)", "para": "$"},
    "BTC":     {"yahoo": "BTC-USD", "ad": "Bitcoin", "para": "$"},
    "ETH":     {"yahoo": "ETH-USD", "ad": "Ethereum", "para": "$"},
    "BRENT":   {"yahoo": "BZ=F", "ad": "Brent Petrol", "para": "$"},
}


def sembol_tespit_et(metin: str) -> tuple[str, dict[str, str]] | None:
    """
    Haber başlığı veya özetinde geçen borsa/finans sembolünü tespit eder.
    """
    if not metin:
        return None

    # Kelime sınırlarına göre ara
    for kod, bilgi in SEMBOL_HARITASI.items():
        desen = rf"\b{kod}\b"
        if re.search(desen, metin, re.IGNORECASE):
            return kod, bilgi

    # Ek Türkçe aramalar
    metin_kucuk = metin.lower()
    if "bist 100" in metin_kucuk or "borsa istanbul" in metin_kucuk:
        return "BIST100", SEMBOL_HARITASI["BIST100"]
    if "türk hava yolları" in metin_kucuk:
        return "THYAO", SEMBOL_HARITASI["THYAO"]
    if "garanti" in metin_kucuk:
        return "GARAN", SEMBOL_HARITASI["GARAN"]
    if "tüpraş" in metin_kucuk or "tupras" in metin_kucuk:
        return "TUPRS", SEMBOL_HARITASI["TUPRS"]
    if "aselsan" in metin_kucuk:
        return "ASELS", SEMBOL_HARITASI["ASELS"]
    if "koç holding" in metin_kucuk or "koc holding" in metin_kucuk:
        return "KCHOL", SEMBOL_HARITASI["KCHOL"]

    return None


def hisse_gecmisi_getir(sembol_bilgi: dict[str, str], gun: int = 30) -> list[float]:
    """
    Yahoo Finance v8 API üzerinden son N günlük kapanış fiyat serisini çeker.
    """
    sym = sembol_bilgi["yahoo"]
    for host in ("query2.finance.yahoo.com", "query1.finance.yahoo.com"):
        url = f"https://{host}/v8/finance/chart/{sym}?range=1mo&interval=1d"
        try:
            r = requests.get(url, headers=HEADERS, timeout=8)
            if r.status_code == 200:
                veri = r.json()
                sonuclar = veri.get("chart", {}).get("result", [])
                if sonuclar:
                    quote = sonuclar[0].get("indicators", {}).get("quote", [{}])[0]
                    kapanislar = quote.get("close", [])
                    gecerli = [float(f) for f in kapanislar if f is not None]
                    if len(gecerli) >= 2:
                        return gecerli
        except Exception as e:
            log.warning("Yahoo Finance geçmiş veri hatası (%s, %s): %s", sym, host, e)
    return []


def trend_karti_ciz(
    sembol_kodu: str,
    sembol_bilgi: dict[str, str],
    fiyatlar: list[float],
    genislik: int = 880,
    yukseklik: int = 240,
) -> Image.Image | None:
    """
    30 günlük fiyat serisini içeren Varyasyon 14 temalı lüks bir trend kartı çizer.
    """
    if len(fiyatlar) < 2:
        return None

    ilk = fiyatlar[0]
    son = fiyatlar[-1]
    yuzde = ((son - ilk) / ilk) * 100
    artis = yuzde >= 0
    para = sembol_bilgi.get("para", "")

    # Renk Paleti (Varyasyon 14 Estetiği)
    if artis:
        renk_ana = (6, 182, 212)         # Siber Turkuaz
        renk_badge = (6, 182, 212, 40)
        badge_border = (6, 182, 212, 140)
        simge = "▲"
        yuzde_str = f"+%{abs(yuzde):.1f}"
    else:
        renk_ana = (244, 63, 94)         # Mercan Kırmızı
        renk_badge = (244, 63, 94, 40)
        badge_border = (244, 63, 94, 140)
        simge = "▼"
        yuzde_str = f"-%{abs(yuzde):.1f}"

    # Kart Arka Planı (Derin Okyanus Petrolü)
    kart = Image.new("RGBA", (genislik, yukseklik), (4, 24, 28, 220))
    ciz = ImageDraw.Draw(kart)

    # Dış Çerçeve
    ciz.rounded_rectangle(
        [0, 0, genislik - 1, yukseklik - 1],
        radius=20,
        outline=(14, 116, 144, 140),
        width=2,
    )

    # Tipografi
    f_sembol = make_image._font(34, 800.0)
    f_ad = make_image._font(22, 450.0)
    f_fiyat = make_image._font(36, 800.0)
    f_badge = make_image._font(22, 700.0)

    # Sembol ve Şirket Adı
    ciz.text((32, 24), sembol_kodu, font=f_sembol, fill=(246, 243, 236))
    ciz.text((32, 64), sembol_bilgi.get("ad", "")[:35], font=f_ad, fill=(148, 163, 184))

    # Son Fiyat
    if para:
        son_str = f"{son:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + f" {para}"
    else:
        son_str = f"{son:,.0f}".replace(",", ".")
    ciz.text((genislik - 32, 24), son_str, font=f_fiyat, fill=(255, 255, 255), anchor="ra")

    # Rozet (30 Günlük Değişim)
    badge_txt = f"{simge} {yuzde_str} (30G)"
    bw = int(ciz.textlength(badge_txt, font=f_badge)) + 20
    bh = 30
    bx = genislik - 32 - bw
    by = 68
    ciz.rounded_rectangle([bx, by, bx + bw, by + bh], radius=8, fill=renk_badge, outline=badge_border, width=1)
    ciz.text((bx + bw // 2, by + bh // 2), badge_txt, font=f_badge, fill=renk_ana, anchor="mm")

    # Sparkline Grafik Çizimi (Süper-Örnekleme 3x)
    gw = genislik - 64
    gh = 110
    gy = 108

    scale = 3
    sw = gw * scale
    sh = gh * scale
    spad_x = 8 * scale
    spad_y = 10 * scale

    min_val = min(fiyatlar)
    max_val = max(fiyatlar)
    fark = (max_val - min_val) or 1.0

    pts = []
    n = len(fiyatlar)
    for i, p in enumerate(fiyatlar):
        x = spad_x + (i / (n - 1)) * (sw - 2 * spad_x)
        y = (sh - spad_y) - ((p - min_val) / fark) * (sh - 2 * spad_y)
        pts.append((x, y))

    s_canvas = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(s_canvas)

    # Degrade Dolgulu Poligon
    poly_pts = pts + [(pts[-1][0], sh), (pts[0][0], sh)]
    grad_mask = Image.new("L", (sw, sh), 0)
    for y_i in range(sh):
        alpha = int(75 * (1.0 - (y_i / sh)**1.2))
        grad_mask.paste(alpha, (0, y_i, sw, y_i + 1))

    poly_img = Image.new("RGBA", (sw, sh), (*renk_ana, 255))
    poly_mask = Image.new("L", (sw, sh), 0)
    poly_draw = ImageDraw.Draw(poly_mask)
    poly_draw.polygon(poly_pts, fill=255)

    grad_arr = np.array(grad_mask)
    poly_arr = np.array(poly_mask)
    comb_arr = (grad_arr.astype(float) * poly_arr.astype(float) / 255.0).astype(np.uint8)
    combined_mask = Image.fromarray(comb_arr)
    s_canvas.paste(poly_img, (0, 0), combined_mask)

    # Ana Çizgi
    s_draw.line(pts, fill=(*renk_ana, 255), width=4 * scale, joint="curve")

    # Parlayan Bitiş Noktası
    end_x, end_y = pts[-1]
    s_draw.ellipse([end_x - 8 * scale, end_y - 8 * scale, end_x + 8 * scale, end_y + 8 * scale], fill=(*renk_ana, 160))
    s_draw.ellipse([end_x - 3.5 * scale, end_y - 3.5 * scale, end_x + 3.5 * scale, end_y + 3.5 * scale], fill=(255, 255, 255, 255))

    spark_img = s_canvas.resize((gw, gh), Image.Resampling.LANCZOS)
    kart.alpha_composite(spark_img, (32, gy))

    return kart


def haber_icin_trend_karti(haber: dict[str, Any]) -> Image.Image | None:
    """
    Verilen haber için borsa/finans sembolü varsa otomatik olarak trend kartını üretir.
    """
    baslik = haber.get("ig_baslik") or haber.get("baslik_orj") or ""
    ozet = haber.get("slayt_ozet") or haber.get("detay_metni") or ""
    metin = f"{baslik} {ozet}"

    sonuc = sembol_tespit_et(metin)
    if not sonuc:
        return None

    sembol_kodu, sembol_bilgi = sonuc
    fiyatlar = hisse_gecmisi_getir(sembol_bilgi)
    if len(fiyatlar) < 2:
        return None

    return trend_karti_ciz(sembol_kodu, sembol_bilgi, fiyatlar)
