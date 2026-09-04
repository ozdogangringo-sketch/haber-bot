"""
ADIM 1 TESTİ
Çalıştır:  python scripts/test_1_rss.py

Ne yapar:
  1. Her RSS kaynağına tek tek bağlanır, çalışıyor mu söyler
  2. Yeni haberleri SQLite'a yazar
  3. Veritabanının son halini ekrana basar

Bu script hiçbir API key istemez. İlk çalışan parçamız bu.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db                       # noqa: E402
from src.fetch_news import haberleri_cek  # noqa: E402


def cizgi(baslik=""):
    print("\n" + "=" * 62)
    if baslik:
        print(baslik)
        print("=" * 62)


def main():
    cizgi("1) RSS KAYNAKLARI TARANIYOR")
    rapor = haberleri_cek()

    print(f"\n{'KAYNAK':<20} {'DURUM':<10} {'YENİ':>5} {'TEKRAR':>7} {'ESKİ':>5}  NOT")
    print("-" * 70)
    calisan = bozuk = 0
    for k in rapor["kaynaklar"]:
        isaret = "✓ ok" if k["durum"] == "ok" else "✗ HATA"
        if k["durum"] == "ok":
            calisan += 1
        else:
            bozuk += 1
        print(
            f"{k['ad']:<20} {isaret:<10} {k['eklenen']:>5} "
            f"{k['tekrar']:>7} {k['eski']:>5}  {k['hata'] or ''}"
        )

    print("-" * 70)
    print(f"Çalışan kaynak: {calisan}   Bozuk kaynak: {bozuk}")
    print(f"Bu turda veritabanına eklenen YENİ haber: {rapor['eklenen']}")
    print(f"Daha önce görülmüş (atlanan): {rapor['tekrar']}")
    print(f"Yaş sınırını geçtiği için atlanan: {rapor['eski']}")

    cizgi("2) VERİTABANI DURUMU")
    with db.baglan() as con:
        print("\nDuruma göre:")
        for satir in db.ozet_istatistik(con):
            print(f"   {satir['durum']:<16} {satir['adet']:>4}")

        print("\nKaynağa göre:")
        for satir in db.kaynak_dagilimi(con):
            print(f"   {satir['kaynak']:<20} {satir['adet']:>4}")

        cizgi("3) SIRADAKİ 10 HABER (Gemini'ye gidecek olanlar)")
        satirlar = db.bekleyenler(con, durum="yeni", limit=10)
        if not satirlar:
            print("\n(Yeni haber yok — muhtemelen hepsi daha önce eklenmiş.)")
        for i, s in enumerate(satirlar, 1):
            tarih = (s["yayin_tarihi"] or "")[:16].replace("T", " ")
            print(f"\n{i}. [{s['kaynak']} | {s['kategori']} | {tarih}]")
            print(f"   {s['baslik_orj']}")
            ozet = (s["ozet_orj"] or "")[:150]
            if ozet:
                print(f"   → {ozet}...")

    cizgi()
    if bozuk:
        print("NOT: Hata veren kaynaklar oldu. Bana çıktıyı gönder, ya")
        print("     alternatif kaynak bulalım ya da config.yaml'de kapatalım.")
    else:
        print("Hepsi çalıştı. Adım 2'ye (Gemini ile metin üretimi) geçebiliriz.")
    print()


if __name__ == "__main__":
    main()
