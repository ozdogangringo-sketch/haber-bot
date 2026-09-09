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


def piyasa_verileri_getir(fiyat_verileri: dict | None = None) -> dict[str, dict]:
    """
    Caption ve Twitter metnini besleyen 7 göstergeyi döner.

    `fiyat_verileri` verilirse yeniden çekim YAPILMAZ — bülten başına tek
    çekim için `piyasa_otomatik` bunu geçiyor.

    ⚠️ Eskiden bu fonksiyon KENDİ çekimini `interval=1d` ile yapıyordu,
    kart ve tablo ise `1h&range=5d` ile. Üç ayrı çekim, üç ayrı kural —
    9 Eyl 2026'da iki sayfanın zıt yüzde basmasının zemini buydu. Artık
    üçü de `tum_fiyatlari_cek` üzerinden aynı veriyi kullanıyor.
    """
    if fiyat_verileri is None:
        fiyat_verileri = tum_fiyatlari_cek(
            {m["sembol"] for m in SEMBOL_HARITASI.values()})

    sonuclar = {}
    for anahtar, meta_bilgi in SEMBOL_HARITASI.items():
        canli = fiyat_verileri.get(meta_bilgi["sembol"])
        if not canli or canli.get("price") is None:
            log.warning("piyasa verisi çekilemedi (%s)", meta_bilgi["sembol"])
            continue
        sonuclar[anahtar] = {
            "ad": meta_bilgi["ad"],
            "fiyat": float(canli["price"]),
            "degisim": float(canli["chg"]),
            "simge": meta_bilgi["simge"],
            "para": meta_bilgi["para"],
        }

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


def tum_fiyatlari_cek(semboller) -> dict[str, dict]:
    """
    Piyasa bülteninin TEK veri kapısı: verilen sembollerin canlı fiyatı,
    günlük değişimi ve 5 günlük serisi.

    ⚠️ NİYE TEK KAPI (9 Eyl 2026): aynı bülten için ÜÇ ayrı çekici vardı —
    kart (ısı haritası, 23 sembol), tablo (30 sembol), caption metni
    (7 varlık). Üçü de kendi HTTP turunu atıyor, kendi zaman aralığını
    seçiyor ve "önceki kapanış"ı kendi sırasıyla okuyordu. Sonuç:
    9 Eyl'de sayfa 1 ile sayfa 2 aynı varlık için ZIT yüzde bastı
    (BIST ▲%3,16 / ▼%0,22). Kural üç yerde yaşayınca biri kaçıyor.

    ⚠️ `previousClose` ile `chartPreviousClose` AYNI ŞEY DEĞİL:
    `interval=1h&range=5d` isteğinde ilki DÜNKÜ kapanış (günlük değişim),
    ikincisi 5 GÜNLÜK pencerenin öncesi (serinin başlangıç çapası).
    Bu ayrım burada BİR KEZ yapılıyor.
    """
    from concurrent.futures import ThreadPoolExecutor

    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

    def _tek(s):
        for _ in range(2):
            try:
                r = requests.get(
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{s}"
                    "?interval=1h&range=5d",
                    headers=headers, timeout=8,
                )
                if r.status_code != 200:
                    continue
                veri = r.json()["chart"]["result"][0]
                meta = veri["meta"]
                gunluk_kapanis = meta.get("previousClose") or meta.get("chartPreviousClose")
                seri_basi = meta.get("chartPreviousClose") or meta.get("previousClose")
                fiyat = meta.get("regularMarketPrice")
                if fiyat is None:
                    continue
                degisim = (((fiyat - gunluk_kapanis) / gunluk_kapanis) * 100
                           if gunluk_kapanis else 0.0)
                kapanislar = (veri.get("indicators", {}).get("quote", [{}])[0]
                              .get("close", []))
                seri = [float(c) for c in kapanislar if c is not None]
                if seri_basi and seri:
                    seri = [float(seri_basi)] + seri
                return s, {"price": fiyat, "chg": degisim, "sparkline": seri}
            except Exception:                          # noqa: BLE001
                continue
        return s, None

    sonuc = {}
    with ThreadPoolExecutor(max_workers=16) as ex:
        for sym, veri in ex.map(_tek, list(semboller)):
            if veri:
                sonuc[sym] = veri
    return sonuc


def isi_haritasi_eksikleri(sektor_verileri: dict) -> list[str]:
    """
    Karta basılan ısı haritasında canlı veri alınamayan varlıkların adları.

    Boş liste = her şey canlı. Dolu liste = o bülten yayınlanmamalı;
    kartta koda gömülü bir yüzde canlı veriymiş gibi görünür.

    ⚠️ `eksik_varliklar` ile AYNI ŞEY DEĞİL: o, `piyasa_verileri_getir`
    çıktısını (caption metnini besleyen 7 varlık) denetliyor. Karta
    basılan veri ise ısı haritasından geliyor ve 23 sembol taşıyor —
    yani iki ayrı veri kümesi, iki ayrı kapı gerekiyor.
    """
    eksik = []
    for ogeler in (sektor_verileri or {}).values():
        for oge in ogeler:
            if isinstance(oge, dict) and oge.get("veri_yok"):
                eksik.append(oge.get("etiket") or oge.get("sym") or "?")
    return eksik


def isi_haritasi_verileri_getir(fiyat_verileri: dict | None = None) -> dict[str, list[dict]]:
    """
    Isı haritası sektörlerini canlı fiyatlarla doldurur.

    `fiyat_verileri` verilirse yeniden çekim YAPILMAZ — bülten başına
    tek çekim için `piyasa_otomatik` bunu geçiyor.
    """

    tum_semboller = set()
    for ogeler in ISI_HARITASI_SEKTORLERI.values():
        for oge in ogeler:
            sym = oge["sym"]
            if sym.endswith("_ONS"):
                sym = sym.replace("_ONS", "")
            tum_semboller.add(sym)

    # ⚠️ Fiyatlar DIŞARIDAN verilebiliyor: `piyasa_otomatik` bülten
    # başına TEK çekim yapıp aynı veriyi kart, tablo ve caption'a
    # dağıtıyor. Verilmezse (elle çağrılar) kendi çekimini yapar.
    if fiyat_verileri is None:
        fiyat_verileri = tum_fiyatlari_cek(tum_semboller)

    headers = {"User-Agent": "Mozilla/5.0"}

    sonuclar = {}
    dolar_kuru = (fiyat_verileri.get("TRY=X") or {}).get("price", 48.08)

    for sektor, ogeler in ISI_HARITASI_SEKTORLERI.items():
        sektor_ogeleri = []
        for oge in ogeler:
            sym_raw = oge["sym"]
            sym = sym_raw.replace("_ONS", "") if sym_raw.endswith("_ONS") else sym_raw
            canli = fiyat_verileri.get(sym)

            # ⚠️ ÜÇÜNCÜ UYDURMA YOLU — 9 Eyl 2026'da kapatıldı.
            # Veri gelmezse `oge["varsayilan"]` yani KODA GÖMÜLÜ bir yüzde
            # basılıyordu ve kartta canlı veriden ayırt edilemiyordu
            # (23 sembolün 23'ünde varsayılan tanımlı). Bu, 6 Eyl'de
            # sayfa 1 (`VARSAYILAN_VERILER`) ve sayfa 2 (`piyasa_tablo`)
            # için kapatılan kusurun AYNISI — ve en önemlisi, karta
            # BASILAN veri bu yoldan geliyor.
            # ⚠️ Yayın kapısı bunu göremiyordu: `eksik_varliklar` yalnızca
            # `piyasa_verileri_getir` çıktısına bakıyor, o veri ise karta
            # hiç girmiyor (kart kendi ısı haritasını çekiyor).
            # Varsayılan SİLİNMEDİ — çizim kodu `degisim`/`fiyat` bekliyor;
            # bunun yerine İŞARETLENİYOR ve yayın kapısı bülteni durduruyor.
            degisim = canli["chg"] if canli else oge["varsayilan"]
            fiyat = canli["price"] if canli else 0.0
            sparkline = canli.get("sparkline", []) if canli else []
            veri_yok = canli is None

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
                "veri_yok": veri_yok,
            })
        sonuclar[sektor] = sektor_ogeleri

    return sonuclar
