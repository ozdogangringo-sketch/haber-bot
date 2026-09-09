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
                fiyat = float(meta.get("regularMarketPrice", 0.0))
                kapanis = float(meta.get("previousClose") or meta.get("chartPreviousClose") or fiyat)
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

    # Eksik kalan varsa varsayılanla doldur — AMA İŞARETLE.
    #
    # ⚠️ 6 Eyl 2026'ya kadar bu dolgu SESSİZDİ: canlı veri gelmeyince
    # BIST 100 için sabit "14.500 puan, +%0,50" basılıyor ve kartta
    # gerçek piyasa verisinden ayırt edilemiyordu. Yani "veri
    # çekilemedi" değil, UYDURMA FİNANSAL RAKAM yayınlanıyordu —
    # `/menu` düğmelerinden kaldırılan uydurma faiz oranıyla ve
    # piyasa tablosundaki (sayfa 2) aynı kusurla aynı sınıf.
    #
    # ⚠️ Varsayılan SİLİNMEDİ, çünkü çizim kodu beş ayrı yerden
    # `fiyat`/`degisim` okuyor ve hepsini None'a hazırlamak bu
    # düzeltmenin riskini gereksiz büyütürdü. Bunun yerine `veri_yok`
    # işareti konuyor ve YAYIN KAPISI o bülteni hiç yayınlamıyor:
    # uydurma rakam ekrana hiç ulaşmıyor.
    for k, varsayilan in VARSAYILAN_VERILER.items():
        if k not in sonuclar:
            sonuclar[k] = {**varsayilan, "veri_yok": True}

    return sonuclar


def eksik_varliklar(veriler: dict) -> list[str]:
    """
    Canlı veri alınamayıp varsayılana düşen varlıkların adları.

    Boş liste = her şey canlı. Dolu liste = o bülten yayınlanmamalı;
    kartta uydurma rakam görünür.
    """
    eksik = []
    for anahtar, deger in (veriler or {}).items():
        if isinstance(deger, dict) and deger.get("veri_yok"):
            eksik.append(deger.get("ad") or anahtar)
    return eksik


def varlik_sorgula(girdi: str) -> dict | None:
    """
    Kullanıcının yazdığı sembolü (BİST hissesi, kripto para, döviz, emtia veya ABD hissesi)
    canlı olarak sorgular ve güncel fiyat, değişim, gün aralığı verilerini döner.
    """
    if not girdi or not girdi.strip():
        return None

    sembol = girdi.upper().strip()
    # Özel takma adlar
    if sembol in ("DOLAR", "USD", "USDTRY"):
        sym = "TRY=X"
        ad = "Dolar / TL"
    elif sembol in ("EURO", "EUR", "EURTRY"):
        sym = "EURTRY=X"
        ad = "Euro / TL"
    elif sembol in ("ALTIN", "GOLD"):
        sym = "GC=F"
        ad = "Gram Altın"
    elif sembol in ("GUMUS", "SILVER"):
        sym = "SI=F"
        ad = "Gümüş"
    elif sembol in ("BTC", "BITCOIN"):
        sym = "BTC-USD"
        ad = "Bitcoin"
    elif sembol in ("ETH", "ETHEREUM"):
        sym = "ETH-USD"
        ad = "Ethereum"
    elif sembol in ("SOL", "SOLANA"):
        sym = "SOL-USD"
        ad = "Solana"
    elif "." not in sembol and "-" not in sembol and len(sembol) <= 5:
        # BİST hissesi varsayımı
        sym = f"{sembol}.IS"
        ad = sembol
    else:
        sym = sembol
        ad = sembol

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d"
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
    try:
        r = requests.get(url, headers=headers, timeout=6)
        if r.status_code != 200 and sym.endswith(".IS"):
            # Belki BİST değil ABD hissesidir
            sym = sembol
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d"
            r = requests.get(url, headers=headers, timeout=6)

        if r.status_code == 200:
            veri = r.json()
            meta = veri["chart"]["result"][0]["meta"]
            fiyat = float(meta.get("regularMarketPrice", 0.0))
            kapanis = float(meta.get("previousClose") or meta.get("chartPreviousClose") or fiyat)
            degisim = ((fiyat - kapanis) / kapanis) * 100 if kapanis else 0.0
            currency = meta.get("currency", "")
            high = float(meta.get("regularMarketDayHigh", fiyat))
            low = float(meta.get("regularMarketDayLow", fiyat))

            # Gram altın özel hesaplama
            if sym == "GC=F":
                try:
                    dolar_r = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/TRY=X?interval=1d", headers=headers, timeout=5)
                    if dolar_r.status_code == 200:
                        dolar_fiyat = float(dolar_r.json()["chart"]["result"][0]["meta"]["regularMarketPrice"])
                        gram_tl = (fiyat / 31.1034768) * dolar_fiyat
                        ad = "Gram Altın (TL)"
                        fiyat = gram_tl
                        currency = "TRY"
                except Exception:
                    pass

            return {
                "ad": ad,
                "sembol": sym,
                "fiyat": fiyat,
                "degisim": degisim,
                "currency": currency,
                "gun_yuksek": high,
                "gun_dusuk": low,
            }
    except Exception as e:
        log.warning("varlik_sorgula hatası (%s): %s", girdi, e)

    return None


ISI_HARITASI_SEKTORLERI = {
    "VİTRİN_ÜST": [
        {"sym": "TRY=X", "etiket": "USD / TL", "icon": "dollar", "varsayilan": 0.10},
        {"sym": "EURTRY=X", "etiket": "EUR / TL", "icon": "euro", "varsayilan": 0.03},
        {"sym": "GC=F", "etiket": "GRAM ALTIN", "icon": "gold", "varsayilan": 0.30},
        {"sym": "SI=F", "etiket": "GRAM GÜMÜŞ", "icon": "silver", "varsayilan": -1.00},
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
    "EMTİA & KÜRESEL MAKRO": [
        {"sym": "BZ=F", "etiket": "BRENT", "icon": "oil", "varsayilan": -1.37},
        {"sym": "GC=F_ONS", "etiket": "ONS ALTIN", "icon": "gold_ons", "varsayilan": 0.45},
        {"sym": "SI=F_ONS", "etiket": "ONS GÜMÜŞ", "icon": "silver_ons", "varsayilan": -0.20},
        {"sym": "DX-Y.NYB", "etiket": "DXY", "icon": "dxy", "varsayilan": 0.18},
        {"sym": "NG=F", "etiket": "DOĞALGAZ", "icon": "gas", "varsayilan": 1.12},
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
                f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?interval=1h&range=5d",
                headers=headers,
                timeout=4,
            )
            if r.status_code == 200:
                veri = r.json()["chart"]["result"][0]
                res = veri["meta"]

                # ⚠️ İKİ FARKLI "ÖNCEKİ KAPANIŞ" VAR — KARIŞTIRMA (9 Eyl 2026).
                # `interval=1h&range=5d` isteğinde Yahoo iki ayrı referans
                # döndürüyor ve ikisi FARKLI günü gösteriyor:
                #   previousClose      → DÜNKÜ kapanış      (günlük değişim)
                #   chartPreviousClose → 5 GÜN ÖNCEKİ kapanış (serinin başı)
                #
                # Bu satır ikisini TERS sırada okuyordu ve kart günlük değişim
                # yerine 5 GÜNLÜK değişimi basıyordu. ÖLÇÜLDÜ (9 Eyl 2026):
                # BIST 100 kartta %4,39 — gerçek günlük değişim %0,97;
                # Bitcoin kartta ▼%0,45 — gerçekte +%1,32, yani İŞARET BİLE
                # TERSTİ. Sayfa 2 (`piyasa_tablo`) aynı veriyi doğru sırayla
                # okuduğu için iki sayfa aynı varlık için çelişen rakam
                # gösteriyordu; kullanıcının bildirdiği kusur buydu.
                #
                # ⚠️ Kart "Güne Nasıl Başladı? · günün açılış rakamları"
                # diyor — yani yalnızca tutarsızlık değil, BAŞLIĞIN
                # SÖYLEDİĞİNDEN farklı bir şey basıyordu.
                gunluk_kapanis = res.get("previousClose") or res.get("chartPreviousClose")
                seri_basi = res.get("chartPreviousClose") or res.get("previousClose")
                price = res.get("regularMarketPrice")
                chg = ((price - gunluk_kapanis) / gunluk_kapanis) * 100 if gunluk_kapanis else 0.0

                # 5 günlük gerçek fiyat serisi (Sparkline)
                # ⚠️ Serinin başına konan çapa `chartPreviousClose` OLMALI:
                # seri 5 gün önce başlıyor, başına dünkü kapanışı koymak
                # grafiğe sahte bir sıçrama çizer.
                closes = veri.get("indicators", {}).get("quote", [{}])[0].get("close", [])
                sparkline = [float(c) for c in closes if c is not None]
                if seri_basi and sparkline:
                    sparkline = [float(seri_basi)] + sparkline

                return s, {"price": price, "chg": chg, "sparkline": sparkline}
        except Exception:
            pass
        return s, None

    with ThreadPoolExecutor(max_workers=16) as ex:
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
            sparkline = canli.get("sparkline", []) if canli else []

            # Gram TL Çevrimleri
            if sym_raw == "GC=F" and fiyat:
                # Gram Altın (TL)
                fiyat = (fiyat / 31.1034768) * dolar_kuru
            elif sym_raw == "SI=F" and fiyat:
                # Gram Gümüş (TL)
                fiyat = (fiyat / 31.1034768) * dolar_kuru

            sektor_ogeleri.append({
                "sym": sym_raw,
                "etiket": oge["etiket"],
                "val": oge.get("val", 20),
                "icon": oge.get("icon", ""),
                "degisim": degisim,
                "fiyat": fiyat,
                "sparkline": sparkline,
            })
        sonuclar[sektor] = sektor_ogeleri

    return sonuclar
