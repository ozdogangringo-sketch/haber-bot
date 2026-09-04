"""
MAKALE METNİ TESTİ
Çalıştır:  python scripts/test_2_makale_metni.py

Ne yapar:
  Her kaynaktan 2 haber seçip tam metnini çekmeyi dener,
  RSS özetiyle karşılaştırır.

Neden önemli:
  RSS özetleri teaser. Ölçtük: haberlerin %76'sı 200 karakterin altında.
  Bu kadar az bilgiyle model caption uyduruyor. Tam metni çekebilirsek
  bu sorun ortadan kalkar — ama önce ÇEKEBİLİYOR MUYUZ, onu görmeliyiz.

  Bu script hiçbir şeyi değiştirmez, sadece ölçer.
"""

import sqlite3
import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

from src.fetch_article import makale_metni_cek     # noqa: E402

HER_KAYNAKTAN = 2


def main():
    con = sqlite3.connect(KOK / "data" / "haber.db")
    kaynaklar = [r[0] for r in con.execute(
        "SELECT DISTINCT kaynak FROM haberler ORDER BY kaynak"
    )]

    print("=" * 78)
    print("MAKALE METNİ ÇEKME TESTİ")
    print("=" * 78)
    print(f"{'KAYNAK':<20} {'RSS ÖZET':>9} {'TAM METİN':>10} {'KAZANÇ':>8}  DURUM")
    print("-" * 78)

    basarili = toplam = 0
    kaynak_sonuc = {}

    for kaynak in kaynaklar:
        satirlar = con.execute(
            "SELECT link, ozet_orj, baslik_orj FROM haberler WHERE kaynak = ? "
            "ORDER BY yayin_tarihi DESC LIMIT ?",
            (kaynak, HER_KAYNAKTAN),
        ).fetchall()

        kaynak_sonuc[kaynak] = []
        for link, ozet, baslik in satirlar:
            toplam += 1
            ozet_uz = len(ozet or "")
            # Başlığı da veriyoruz: yanlış haberin metnini çekmişsek yakalansın
            metin = makale_metni_cek(link, baslik)

            if metin:
                basarili += 1
                kat = metin and ozet_uz and (len(metin) / ozet_uz)
                durum = "✓ çekildi"
                print(f"{kaynak:<20} {ozet_uz:>9} {len(metin):>10} "
                      f"{kat:>7.1f}x  {durum}")
                kaynak_sonuc[kaynak].append(metin)
            else:
                print(f"{kaynak:<20} {ozet_uz:>9} {'-':>10} {'-':>8}  ✗ ÇEKİLEMEDİ")
                kaynak_sonuc[kaynak].append(None)

    print("-" * 78)
    print(f"Başarılı: {basarili} / {toplam}")

    print()
    print("=" * 78)
    print("ÖRNEK: her kaynaktan çekilen metnin ilk 200 karakteri")
    print("=" * 78)
    for kaynak, metinler in kaynak_sonuc.items():
        ilk = next((m for m in metinler if m), None)
        print(f"\n[{kaynak}]")
        if ilk:
            print(f"  {ilk[:200]}...")
        else:
            print("  (çekilemedi)")


if __name__ == "__main__":
    main()
