"""
piyasa.py — Canlı borsa, döviz, altın, kripto ve emtia piyasa verilerini çeker.

Veri Kaynağı:
    Yahoo Finance v8 API (ücretsiz, hızlı, API anahtarı gerektirmez).
    Gram altın, canlı Ons Altın ($) ve Dolar/TL ($/TL) üzerinden anlık hesaplanır.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

log = logging.getLogger(__name__)

SEMBOL_HARITASI = {
    "bist100": {
        "sembol": "XU100.IS",
        "ad": "BIST 100",
        "simge": "📈",
        "birim": "puan",
        "para": "",
    },
    "dolar": {
        "sembol": "TRY=X",
        "ad": "Dolar / TL",
        "simge": "💵",
        "birim": "TL",
        "para": "₺",
    },
    "euro": {
        "sembol": "EURTRY=X",
        "ad": "Euro / TL",
        "simge": "💶",
        "birim": "TL",
        "para": "₺",
    },
    "ons_altin": {
        "sembol": "GC=F",
        "ad": "Ons Altın",
        "simge": "🪙",
        "birim": "USD",
        "para": "$",
    },
    "btc": {
        "sembol": "BTC-USD",
        "ad": "Bitcoin",
        "simge": "₿",
        "birim": "USD",
        "para": "$",
    },
    "brent": {
        "sembol": "BZ=F",
        "ad": "Brent Petrol",
        "simge": "🛢️",
        "birim": "USD",
        "para": "$",
    },
}

VARSAYILAN_VERILER = {
    "bist100": {"ad": "BIST 100", "fiyat": 14500.0, "degisim": 0.50, "para": ""},
    "dolar": {"ad": "Dolar / TL", "fiyat": 48.00, "degisim": 0.10, "para": "₺"},
    "euro": {"ad": "Euro / TL", "fiyat": 56.00, "degisim": 0.10, "para": "₺"},
    "gram_altin": {"ad": "Gram Altın", "fiyat": 7200.0, "degisim": 0.80, "para": "₺"},
    "btc": {"ad": "Bitcoin", "fiyat": 77000.0, "degisim": -1.20, "para": "$"},
    "brent": {"ad": "Brent Petrol", "fiyat": 94.00, "degisim": 0.40, "para": "$"},
}


def turkce_sayi(sayi: float, ondalik: int = 2) -> str:
    """
    Sayıyı Türkçe formatına çevirir (binlik nokta, ondalık virgül).
    Örnek: 14514.82 -> 14.514,82
    """
    if ondalik == 0:
        return f"{int(round(sayi)):,}".replace(",", ".")
    metin = f"{sayi:,.{ondalik}f}"
    # İngilizce format: 14,514.82 -> Türkçe: 14.514,82
    ana, kusurat = metin.split(".")
    ana = ana.replace(",", ".")
    return f"{ana},{kusurat}"


def piyasa_verileri_getir() -> dict[str, dict]:
    """
    Canlı piyasa göstergelerini çeker ve sözlük olarak döner.
    """
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
    sonuclar = {}

    for anahtar, meta_bilgi in SEMBOL_HARITASI.items():
        sym = meta_bilgi["sembol"]
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d"
        try:
            r = requests.get(url, headers=headers, timeout=6)
            if r.status_code == 200:
                veri = r.json()
                meta = veri["chart"]["result"][0]["meta"]
                fiyat = float(meta["regularMarketPrice"])
                kapanis = float(meta.get("chartPreviousClose", meta.get("previousClose", fiyat)))
                degisim = ((fiyat - kapanis) / kapanis) * 100 if kapanis else 0.0
                sonuclar[anahtar] = {
                    "ad": meta_bilgi["ad"],
                    "fiyat": fiyat,
                    "degisim": degisim,
                    "simge": meta_bilgi["simge"],
                    "para": meta_bilgi["para"],
                }
            else:
                log.warning("piyasa verisi çekilemedi (%s): status=%s", sym, r.status_code)
        except Exception as e:
            log.warning("piyasa verisi hatası (%s): %s", sym, e)

    # Gram Altın (TL) hesaplama: (Ons Altın / 31.1034768) * Dolar/TL
    if "ons_altin" in sonuclar and "dolar" in sonuclar:
        ons = sonuclar["ons_altin"]["fiyat"]
        dolar_kuru = sonuclar["dolar"]["fiyat"]
        gram_fiyat = (ons / 31.1034768) * dolar_kuru
        gram_degisim = sonuclar["ons_altin"]["degisim"] + sonuclar["dolar"]["degisim"]
        sonuclar["gram_altin"] = {
            "ad": "Gram Altın",
            "fiyat": gram_fiyat,
            "degisim": gram_degisim,
            "simge": "🪙",
            "para": "₺",
        }
    elif "gram_altin" not in sonuclar:
        sonuclar["gram_altin"] = VARSAYILAN_VERILER["gram_altin"]

    # Eksik kalan varsa varsayılanla doldur
    for k, varsayilan in VARSAYILAN_VERILER.items():
        if k not in sonuclar:
            sonuclar[k] = varsayilan

    return sonuclar


ISI_HARITASI_SEKTORLERI = {
    "VİTRİN_ÜST": [
        {"sym": "TRY=X", "etiket": "USD / TL", "icon": "dollar", "varsayilan": 0.10},
        {"sym": "EURTRY=X", "etiket": "EUR / TL", "icon": "euro", "varsayilan": 0.03},
        {"sym": "GC=F", "etiket": "GRAM ALTIN", "icon": "gold", "varsayilan": 0.30},
    ],
    "BİST & TÜRKİYE HİSSELERİ": [
        {"sym": "XU100.IS", "etiket": "BIST 100", "val": 52, "varsayilan": 0.20},
        {"sym": "THYAO.IS", "etiket": "THYAO", "val": 35, "varsayilan": 0.00},
        {"sym": "TUPRS.IS", "etiket": "TUPRS", "val": 26, "varsayilan": -1.78},
        {"sym": "KCHOL.IS", "etiket": "KCHOL", "val": 24, "varsayilan": 0.36},
        {"sym": "GARAN.IS", "etiket": "GARAN", "val": 22, "varsayilan": 2.77},
        {"sym": "AKBNK.IS", "etiket": "AKBNK", "val": 20, "varsayilan": 3.95},
        {"sym": "BIMAS.IS", "etiket": "BIMAS", "val": 24, "varsayilan": -1.20},
        {"sym": "ASELS.IS", "etiket": "ASELS", "val": 18, "varsayilan": -0.56},
        {"sym": "EREGL.IS", "etiket": "EREGL", "val": 16, "varsayilan": 0.89},
    ],
    "DÖVİZ & EMTİA (MAKRO)": [
        {"sym": "BZ=F", "etiket": "BRENT", "icon": "oil", "varsayilan": -1.37},
        {"sym": "SI=F", "etiket": "GÜMÜŞ", "icon": "silver", "varsayilan": -1.00},
        {"sym": "GC=F_ONS", "etiket": "ONS ALTIN", "icon": "gold_ons", "varsayilan": 0.45},
        {"sym": "SI=F_ONS", "etiket": "ONS GÜMÜŞ", "icon": "silver_ons", "varsayilan": -0.20},
        {"sym": "DX-Y.NYB", "etiket": "DXY", "icon": "dxy", "varsayilan": 0.18},
    ],
    "KÜRESEL PİYASALAR & KRİPTO": [
        {"sym": "BTC-USD", "etiket": "BITCOIN", "icon": "btc", "varsayilan": -0.64},
        {"sym": "ETH-USD", "etiket": "ETHEREUM", "icon": "eth", "varsayilan": -0.59},
        {"sym": "NVDA", "etiket": "NVIDIA", "icon": "nvda", "varsayilan": -0.98},
        {"sym": "AAPL", "etiket": "APPLE", "icon": "aapl", "varsayilan": -0.63},
        {"sym": "TSLA", "etiket": "TESLA", "icon": "tsla", "varsayilan": 5.14},
    ],
}


def isi_haritasi_verileri_getir() -> dict[str, list[dict]]:
    """
    Tüm ısı haritası sektörlerindeki hisse ve varlıkların canlı verilerini paralel çeker.
    """
    from concurrent.futures import ThreadPoolExecutor

    tum_semboller = set()
    for ogeler in ISI_HARITASI_SEKTORLERI.values():
        for oge in ogeler:
            sym = oge["sym"]
            if sym.endswith("_ONS"):
                sym = sym.replace("_ONS", "")
            tum_semboller.add(sym)

    headers = {"User-Agent": "Mozilla/5.0"}
    fiyat_verileri = {}

    def _tek_cek(s):
        try:
            r = requests.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?interval=1d",
                headers=headers,
                timeout=4,
            )
            if r.status_code == 200:
                res = r.json()["chart"]["result"][0]["meta"]
                prev = res.get("chartPreviousClose") or res.get("previousClose")
                price = res.get("regularMarketPrice")
                chg = ((price - prev) / prev) * 100 if prev else 0.0
                return s, {"price": price, "chg": chg}
        except Exception:
            pass
        return s, None

    with ThreadPoolExecutor(max_workers=15) as ex:
        for sym, res in ex.map(_tek_cek, list(tum_semboller)):
            if res:
                fiyat_verileri[sym] = res

    sonuclar = {}
    dolar_kuru = (fiyat_verileri.get("TRY=X") or {}).get("price", 48.08)

    for sektor, ogeler in ISI_HARITASI_SEKTORLERI.items():
        sektor_ogeleri = []
        for oge in ogeler:
            sym_raw = oge["sym"]
            sym = sym_raw.replace("_ONS", "") if sym_raw.endswith("_ONS") else sym_raw
            canli = fiyat_verileri.get(sym)
            degisim = canli["chg"] if canli else oge["varsayilan"]
            fiyat = canli["price"] if canli else 0.0

            # Gram TL Çevrimleri
            if sym_raw == "GC=F" and fiyat:
                # Gram Altın (TL)
                fiyat = (fiyat / 31.1034768) * dolar_kuru
            elif sym_raw == "SI=F" and fiyat:
                # Gram Gümüş (TL)
                fiyat = (fiyat / 31.1034768) * dolar_kuru
            # GC=F_ONS ve SI=F_ONS saf dolar fiyatı olarak kalır ($2750, $32.40)

            sektor_ogeleri.append({
                "sym": sym_raw,
                "etiket": oge["etiket"],
                "val": oge.get("val", 20),
                "icon": oge.get("icon", ""),
                "degisim": degisim,
                "fiyat": fiyat,
            })
        sonuclar[sektor] = sektor_ogeleri

    return sonuclar
