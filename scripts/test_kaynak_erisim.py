"""
KAYNAK ERİŞİM TEŞHİSİ
Çalıştır:  python scripts/test_kaynak_erisim.py

Ne yapar:
  Her RSS kaynağına tek tek bağlanıp SADECE erişilebilirliğini ölçer.
  Veritabanına hiçbir şey yazmaz, hiçbir şey değiştirmez.

Neden ayrı bir script?
  Bu botu GitHub Actions çalıştıracak. GitHub'ın sunucuları veri merkezi
  IP'si kullanıyor ve bazı haber siteleri (Cloudflare koruması olanlar)
  veri merkezi IP'lerine 403 döndürüp ev internetine döndürmüyor.

  Yani bir kaynak senin bilgisayarında çalışıp GitHub'da sessizce ölebilir.
  Bu scripti iki yerde de çalıştırıp çıktıları yan yana koyunca
  hangi kaynakların gerçekten güvenilir olduğunu görürüz.

Çıkış kodu her zaman 0 — bu bir teşhis aracı, bir test değil.
Kaynak patlasa bile GitHub Actions'ta kırmızı görünmesin istiyoruz.
"""

import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests                                      # noqa: E402

from src.fetch_news import (                         # noqa: E402
    ATOM,
    BASLIKLAR,
    ayarlari_oku,
    feed_ayristir,
)


def nerede_calisiyoruz() -> str:
    """
    Bu makinenin dışarıya görünen IP'sini ve sağlayıcısını yazar.
    Karşılaştırma yaparken 'bu çıktı nereden geldi' karışmasın diye.
    """
    try:
        c = requests.get("https://ipinfo.io/json", timeout=10)
        d = c.json()
        return (
            f"IP: {d.get('ip', '?')}  |  "
            f"Konum: {d.get('city', '?')}/{d.get('country', '?')}  |  "
            f"Sağlayıcı: {d.get('org', '?')}"
        )
    except Exception as e:
        return f"IP tespit edilemedi ({type(e).__name__})"


def kaynagi_dene(kaynak: dict, zaman_asimi: int) -> dict:
    """
    Tek bir kaynağa bağlanır. Asla exception fırlatmaz;
    ne olduğunu sözlük olarak döner.
    """
    sonuc = {
        "ad": kaynak["ad"],
        "http": "-",
        "boyut_kb": 0,
        "haber": 0,
        "sure_ms": 0,
        "durum": "?",
        "not": "",
    }

    basla = time.monotonic()
    try:
        cevap = requests.get(kaynak["url"], headers=BASLIKLAR, timeout=zaman_asimi)
        sonuc["sure_ms"] = int((time.monotonic() - basla) * 1000)
        sonuc["http"] = cevap.status_code
        sonuc["boyut_kb"] = round(len(cevap.content) / 1024, 1)

        if cevap.status_code != 200:
            sonuc["durum"] = "✗ ENGEL" if cevap.status_code in (401, 403, 429) else "✗ HTTP"
            sonuc["not"] = _engel_yorumu(cevap.status_code)
            return sonuc

        # 200 döndü ama içi gerçekten RSS mi? Cloudflare bazen 200 ile
        # "bot musun?" HTML sayfası döndürüyor — bu en sinsi durum.
        try:
            girdiler = feed_ayristir(cevap.content)
        except ET.ParseError as e:
            sonuc["durum"] = "✗ XML"
            sonuc["not"] = f"200 döndü ama XML değil ({e})"
            return sonuc

        sonuc["haber"] = len(girdiler)
        if not girdiler:
            sonuc["durum"] = "⚠ BOŞ"
            sonuc["not"] = "XML geçerli ama içinde haber yok"
        else:
            sonuc["durum"] = "✓ ok"

    except requests.Timeout:
        sonuc["sure_ms"] = int((time.monotonic() - basla) * 1000)
        sonuc["durum"] = "✗ SÜRE"
        sonuc["not"] = f"{zaman_asimi} sn içinde cevap vermedi"
    except Exception as e:
        sonuc["sure_ms"] = int((time.monotonic() - basla) * 1000)
        sonuc["durum"] = "✗ HATA"
        sonuc["not"] = f"{type(e).__name__}: {e}"

    return sonuc


def _engel_yorumu(kod: int) -> str:
    if kod == 403:
        return "403 — büyük ihtimalle Cloudflare bu IP'yi engelliyor"
    if kod == 429:
        return "429 — çok fazla istek, hız sınırı"
    if kod == 404:
        return "404 — feed adresi değişmiş olabilir"
    return f"HTTP {kod}"


def main():
    ayarlar = ayarlari_oku()
    zaman_asimi = ayarlar["genel"]["istek_zaman_asimi"]

    print("=" * 78)
    print("KAYNAK ERİŞİM TEŞHİSİ")
    print("=" * 78)
    print(nerede_calisiyoruz())
    print()

    print(f"{'KAYNAK':<20} {'DURUM':<9} {'HTTP':>5} {'KB':>7} {'HABER':>6} {'MS':>6}  NOT")
    print("-" * 78)

    sonuclar = []
    for kaynak in ayarlar["kaynaklar"]:
        s = kaynagi_dene(kaynak, zaman_asimi)
        sonuclar.append(s)
        print(
            f"{s['ad']:<20} {s['durum']:<9} {str(s['http']):>5} "
            f"{s['boyut_kb']:>7} {s['haber']:>6} {s['sure_ms']:>6}  {s['not']}"
        )

    calisan = [s for s in sonuclar if s["durum"] == "✓ ok"]
    print("-" * 78)
    print(f"Çalışan: {len(calisan)} / {len(sonuclar)}")

    sorunlu = [s for s in sonuclar if s["durum"] != "✓ ok"]
    if sorunlu:
        print("\nSORUNLU KAYNAKLAR:")
        for s in sorunlu:
            print(f"  • {s['ad']}: {s['not']}")

    print()
    print("Bu çıktıyı, aynı scriptin diğer ortamdaki çıktısıyla karşılaştır.")
    print("Sadece birinde patlayan kaynak varsa sebep IP engeli demektir.")


if __name__ == "__main__":
    main()
