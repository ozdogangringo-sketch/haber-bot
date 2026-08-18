"""
kaynak_dogrula.py — RSS kaynaklarını ölçer: çalışıyor mu, taze mi,
kategorisi doğru mu?

NEDEN VAR:
    18 Ağu 2026'da TRT'nin "teknoloji" beslemesi eklendi ve içindeki
    haberlerin HİÇBİRİ teknoloji değildi — 10 haberin 5'i gündem, 3'ü
    dünya. Sonuç: "Mustafa Bozbey CHP'den istifa etti" haberi slaytta
    "TRT TEKNOLOJİ" etiketiyle yayınlandı.

    Besleme adının kategoriyi doğru verdiğine güvenmek yetmiyor. Aynı
    şekilde bir beslemenin GÜNCEL olduğuna da güvenilemiyor: TRT'nin
    spor beslemesi 11 gün, çevre beslemesi 25 saat eskiydi.

    Bu script o denetimi tekrarlanabilir hale getiriyor. Yeni kaynak
    eklemeden ÖNCE çalıştır.

NE ÖLÇÜYOR:
    1. Çalışıyor mu       — indirilebiliyor ve ayrıştırılabiliyor mu
    2. Tazelik            — kaç haber son 24 saatte
    3. Kategori doğruluğu — linklerdeki kategori segmenti iddiayı tutuyor mu
    4. Örtüşme            — başka bir kaynağın kopyası mı

ÇALIŞTIRMA:
    python scripts/kaynak_dogrula.py           (config'deki tüm kaynaklar)
    python scripts/kaynak_dogrula.py <url> <beklenen_kategori>   (tek aday)
"""

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import yaml                                        # noqa: E402

from src import fetch_news                         # noqa: E402

# Link içinde kategoriyi taşıyan yaygın desenler.
# aa.com.tr/tr/ekonomi/... · trthaber.com/haber/gundem/... · ntv.com.tr/dunya/...
KATEGORI_DESENLERI = [
    re.compile(r"/haber/([a-z-]+)/"),
    re.compile(r"\.com(?:\.tr)?/tr/([a-z-]+)/"),
    re.compile(r"\.com(?:\.tr)?/([a-z-]+)/"),
]

# Kaynağın kategorisi ile linkteki segment aynı yazılmıyor olabilir.
ESANLAM = {
    "bilim": {"bilim-teknoloji", "bilim", "teknoloji"},
    "teknoloji": {"teknoloji", "bilim-teknoloji"},
    "kultur": {"kultur", "kultur-sanat", "kultur-yasam"},
    "yasam": {"yasam", "kultur-yasam", "saglik"},
    "dunya": {"dunya", "turk-dunyasi"},
    "turkiye": {"gundem", "turkiye", "guncel", "politika", "siyaset"},
    "spor": {"spor", "futbol", "motogp", "f1", "indycar", "wec"},
    "ekonomi": {"ekonomi", "finans"},
}

TAZE_ESIK = 0.25        # haberlerin en az %25'i 24 saatten yeni olmalı
KATEGORI_ESIK = 0.50    # linklerin en az %50'si kategoriyi tutmalı

# ⚠️ GENEL AKIŞLARDA KATEGORİ DENETİMİ YAPILMIYOR.
# Bunlar zaten karma içerik veriyor (gündem akışı, dünya servisi) ve
# "turkiye" etiketi bir iddia değil, varsayılan. BBC Türkçe'nin linki
# /turkce/articles/... biçiminde, Al Jazeera İngilizce — ölçüm anlamsız
# çıkıyor ve gerçek sorunları gölgeliyor.
GENEL_AKISLAR = {
    "TRT Haber", "BBC Türkçe", "Anadolu Ajansı", "NTV Gündem",
    "Habertürk Gündem", "Sözcü Gündem", "BBC World", "Al Jazeera",
    "Independent Türkçe",
}

# Bu kategorilerde günlük haber akışı doğal olarak seyrek; bayatlık
# uyarısı yanıltıcı olur. Bilim/kültür haberi her saat çıkmıyor.
SEYREK_KATEGORILER = {"bilim", "kultur", "yasam", "teknoloji"}


def _link_kategorisi(link: str) -> str | None:
    for desen in KATEGORI_DESENLERI:
        m = desen.search(link)
        if m:
            return m.group(1)
    return None


def kaynagi_olc(ad: str, url: str, kategori: str) -> dict:
    sonuc = {"ad": ad, "kategori": kategori, "durum": "ok", "not": ""}
    try:
        ogeler = fetch_news.feed_ayristir(fetch_news.feed_indir(url, 15))
    except Exception as e:
        return {**sonuc, "durum": "HATA", "not": type(e).__name__}

    if not ogeler:
        return {**sonuc, "durum": "BOŞ", "not": "hiç haber yok"}

    simdi = datetime.now(timezone.utc)
    yaslar = []
    for x in ogeler:
        if x.get("yayin_tarihi"):
            try:
                t = datetime.fromisoformat(x["yayin_tarihi"])
                yaslar.append((simdi - t).total_seconds() / 3600)
            except ValueError:
                pass

    taze = sum(1 for y in yaslar if y <= 24)
    sonuc["adet"] = len(ogeler)
    sonuc["taze_oran"] = taze / len(ogeler)

    # Kategori doğruluğu — genel akışlarda ölçülmüyor (bkz. GENEL_AKISLAR)
    kabul = ESANLAM.get(kategori, {kategori})
    if ad in GENEL_AKISLAR:
        sonuc["kategori_oran"] = None
        sonuc["baslıklar"] = {x["baslik_orj"] for x in ogeler}
        uyari = []
        if sonuc["taze_oran"] < TAZE_ESIK:
            uyari.append(f"BAYAT (%{sonuc['taze_oran']*100:.0f} taze)")
        if uyari:
            sonuc["durum"] = "⚠️"
            sonuc["not"] = " · ".join(uyari)
        return sonuc
    segmentli = [s for s in (_link_kategorisi(x["link"]) for x in ogeler) if s]
    sonuc["kategori_olculdu"] = bool(segmentli)
    sonuc["kategori_oran"] = (
        sum(1 for s in segmentli if s in kabul) / len(segmentli)
        if segmentli else None
    )
    sonuc["baslıklar"] = {x["baslik_orj"] for x in ogeler}

    uyarilar = []
    if sonuc["taze_oran"] < TAZE_ESIK and kategori not in SEYREK_KATEGORILER:
        uyarilar.append(f"BAYAT (%{sonuc['taze_oran']*100:.0f} taze)")
    if (sonuc["kategori_oran"] is not None
            and sonuc["kategori_oran"] < KATEGORI_ESIK):
        uyarilar.append(f"KATEGORİ YANLIŞ (%{sonuc['kategori_oran']*100:.0f})")
    if uyarilar:
        sonuc["durum"] = "⚠️"
        sonuc["not"] = " · ".join(uyarilar)
    return sonuc


def main() -> int:
    if len(sys.argv) >= 3:
        adaylar = [{"ad": "ADAY", "url": sys.argv[1], "kategori": sys.argv[2]}]
    else:
        cfg = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
        adaylar = [k for k in cfg["kaynaklar"] if k.get("aktif", True)]

    print(f"{len(adaylar)} kaynak ölçülüyor…\n")
    print(f"{'kaynak':24} {'kategori':11} {'haber':>5} {'taze':>6} "
          f"{'kat.doğru':>10}  durum")
    print("-" * 78)

    sonuclar = []
    for k in adaylar:
        s = kaynagi_olc(k["ad"], k["url"], k["kategori"])
        sonuclar.append(s)
        taze = f"%{s['taze_oran']*100:.0f}" if "taze_oran" in s else "-"
        kat = ("-" if s.get("kategori_oran") is None
               else f"%{s['kategori_oran']*100:.0f}")
        print(f"{s['ad']:24} {s['kategori']:11} {s.get('adet', 0):5} "
              f"{taze:>6} {kat:>10}  {s['durum']} {s['not']}")

    # Kaynaklar birbirinin kopyası mı? (Milliyet'in iki beslemesi aynıydı)
    print("\nörtüşme denetimi:")
    bulundu = False
    for i, a in enumerate(sonuclar):
        for b in sonuclar[i + 1:]:
            ka, kb = a.get("baslıklar"), b.get("baslıklar")
            if not ka or not kb:
                continue
            ortak = len(ka & kb)
            if ortak >= min(len(ka), len(kb)) * 0.8:
                print(f"  ⚠️ {a['ad']} ↔ {b['ad']}: {ortak} ortak haber "
                      f"— aynı besleme olabilir")
                bulundu = True
    if not bulundu:
        print("  ✓ kayda değer örtüşme yok")

    sorunlu = [s for s in sonuclar if s["durum"] != "ok"]
    print(f"\n{len(sonuclar) - len(sorunlu)}/{len(sonuclar)} kaynak sağlıklı")
    return 1 if sorunlu else 0


if __name__ == "__main__":
    raise SystemExit(main())
