"""
ADIM 3 TESTİ — bir turluk carousel'in bütün slaytları
Çalıştır:  python scripts/test_6_tur_gorsel.py

Ne yapar:
  1. durum='metin_hazir' haberleri önem puanına göre sıralar
  2. Her biri için görsel katmanını seçer (Commons → Pexels → gradyan)
  3. Slaytları data/output/ altına yazar
  4. Hangi haberin hangi katmandan geldiğini tabloyla gösterir

MALİYET: sıfır. Bu akışta AI çağrılmıyor; üç katman da bedava.

Veritabanına yazdığı tek şey `gorsel_yolu` ve `gorsel_kaynagi` —
haberin durumunu DEĞİŞTİRMİYOR, yani istediğin kadar tekrar çalıştır.

Çıktıyı okurken şuna bak: "KATMAN" sütunu. Çoğunluk gradyansa
gorsel_konu/gorsel_temsili alanları zayıf üretilmiş demektir, Gemini
prompt'una dönmek gerekir.
"""

import sys
from collections import Counter
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import yaml                          # noqa: E402

from src import db, slaytlar         # noqa: E402


def main():
    ayarlar = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    kac = ayarlar["gorsel"]["slayt_sayisi"]

    db.kur()
    con = db.baglan()

    haberler = list(con.execute(
        """SELECT * FROM haberler
             WHERE durum = 'metin_hazir' AND ig_baslik IS NOT NULL
             ORDER BY onem_puani DESC, yayin_tarihi DESC
             LIMIT ?""",
        (kac,),
    ))

    if not haberler:
        print("Metni hazır haber yok. Önce: python scripts/test_3_metin_uret.py 10")
        return 1

    print("=" * 78)
    print(f"TUR GÖRSELLERİ ÜRETİLİYOR ({len(haberler)} slayt)")
    print("=" * 78)

    sonuclar = slaytlar.tur_uret(haberler, ayarlar, con)

    baslik_ile = {h["id"]: h for h in haberler}
    print(f"\n{'#':>5}  {'KATMAN':<9} {'PUAN':>4}  BAŞLIK")
    print("-" * 78)
    for s in sonuclar:
        h = baslik_ile[s["id"]]
        print(f"{s['id']:>5}  {s['katman']:<9} {h['onem_puani']:>4}  "
              f"{h['ig_baslik'][:52]}")

    sayim = Counter(s["katman"] for s in sonuclar)
    print("\n" + "=" * 78)
    print("KATMAN DAĞILIMI")
    print("=" * 78)
    for katman in ("commons", "pexels", "gradyan"):
        adet = sayim.get(katman, 0)
        if len(sonuclar):
            print(f"  {katman:<9} {adet:>2}  {'█' * adet}")

    print(f"\nÜretilen: {len(sonuclar)}/{len(haberler)}")
    print(f"Klasör  : {Path('data/output').resolve()}")

    atif = slaytlar.atif_bloku(sonuclar)
    if atif:
        print("\nCAPTION'A EKLENECEK ATIF BLOKU:")
        print(atif.strip())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
