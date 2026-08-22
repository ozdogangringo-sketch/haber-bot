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
    "TEKNOLOJİ & YAPAY ZEKA": [
        {"sym": "NVDA", "etiket": "NVDA", "val": 35, "varsayilan": -0.22},
        {"sym": "AAPL", "etiket": "AAPL", "val": 32, "varsayilan": -3.78},
        {"sym": "MSFT", "etiket": "MSFT", "val": 30, "varsayilan": 0.43},
        {"sym": "TSLA", "etiket": "TSLA", "val": 24, "varsayilan": 5.14},
        {"sym": "AMZN", "etiket": "AMZN", "val": 22, "varsayilan": -0.57},
    ],
    "DÖVİZ & EMTİA (MAKRO)": [
        {"sym": "GC=F", "etiket": "ALTIN", "val": 34, "varsayilan": 2.47},
        {"sym": "TRY=X", "etiket": "USD / TL", "val": 28, "varsayilan": 0.08},
        {"sym": "EURTRY=X", "etiket": "EUR / TL", "val": 24, "varsayilan": 0.06},
        {"sym": "BZ=F", "etiket": "BRENT", "val": 20, "varsayilan": 0.65},
    ],
    "İLETİŞİM & GLOBAL FİNANS": [
        {"sym": "META", "etiket": "META", "val": 32, "varsayilan": 0.75},
        {"sym": "GOOGL", "etiket": "GOOG", "val": 30, "varsayilan": 1.22},
        {"sym": "JPM", "etiket": "JPM", "val": 24, "varsayilan": 0.01},
        {"sym": "V", "etiket": "VISA", "val": 20, "varsayilan": -2.54},
    ],
    "KRİPTO & BORSA": [
        {"sym": "BTC-USD", "etiket": "BITCOIN", "val": 35, "varsayilan": -1.68},
        {"sym": "ETH-USD", "etiket": "ETHEREUM", "val": 26, "varsayilan": -3.72},
        {"sym": "XU100.IS", "etiket": "BIST 100", "val": 24, "varsayilan": 0.82},
        {"sym": "SOL-USD", "etiket": "SOLANA", "val": 18, "varsayilan": 2.10},
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
            tum_semboller.add(oge["sym"])

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

    with ThreadPoolExecutor(max_workers=12) as ex:
        for sym, res in ex.map(_tek_cek, list(tum_semboller)):
            if res:
                fiyat_verileri[sym] = res

    sonuclar = {}
    for sektor, ogeler in ISI_HARITASI_SEKTORLERI.items():
        sektor_ogeleri = []
        for oge in ogeler:
            sym = oge["sym"]
            canli = fiyat_verileri.get(sym)
            degisim = canli["chg"] if canli else oge["varsayilan"]
            fiyat = canli["price"] if canli else 0.0
            sektor_ogeleri.append({
                "sym": sym,
                "etiket": oge["etiket"],
                "val": oge["val"],
                "degisim": degisim,
                "fiyat": fiyat,
            })
        sonuclar[sektor] = sektor_ogeleri

    return sonuclar
