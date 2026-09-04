"""
ADIM 2 TESTİ — Gemini ile metin üretimi
Çalıştır:  python scripts/test_3_metin_uret.py
Kaç haber: python scripts/test_3_metin_uret.py 5     (varsayılan 3)

Ne yapar:
  1. durum='yeni' haberlerden birkaçını alır
  2. Her biri için makalenin tam metnini çeker
  3. Gemini'ye verip Instagram metni ürettirir
  4. Veritabanına yazar, durumu 'metin_hazir' yapar

DİKKAT: Bu script veritabanını DEĞİŞTİRİR ve Gemini kotasından yer.
O yüzden varsayılanı 3 haber tuttuk.

Çıktıyı okurken şuna bak: "KAYNAK" satırındaki metin uzunluğu.
Küçükse (200 civarı) model az bilgiyle çalışmış demektir; caption'ın
kısa ve iddiasız olması BEKLENEN davranış, kusur değil.
"""

import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

from src import db                            # noqa: E402
from src.generate_text import metinleri_uret   # noqa: E402


def cizgi(baslik=""):
    print("\n" + "=" * 74)
    if baslik:
        print(baslik)
        print("=" * 74)


def main():
    kac = int(sys.argv[1]) if len(sys.argv) > 1 else 3

    cizgi(f"GEMINI İLE METİN ÜRETİLİYOR ({kac} haber)")
    print("Her haber için önce makalenin tam metni çekiliyor,")
    print("sonra Gemini'ye veriliyor. Biraz sürebilir...\n")

    rapor = metinleri_uret(limit=kac)

    for h in rapor["haberler"]:
        print("-" * 74)
        print(f"[{h['id']}] {h['kaynak']}")
        print(f"ORİJİNAL : {h['baslik_orj']}")

        if h["durum"] != "ok":
            print(f"✗ HATA   : {h['hata']}")
            continue

        s = h["sonuc"]
        kaynak_uz = h["kaynak_uzunluk"]
        nereden = f"makale gövdesi ({kaynak_uz} karakter)" if kaynak_uz else "RSS özeti (az bilgi)"
        print(f"KAYNAK   : {nereden}")
        print()
        print(f"  BAŞLIK  : {s['ig_baslik']}")
        print(f"  PUAN    : {s['onem_puani']}/10")
        print(f"  CAPTION : {s['ig_caption']}")
        print(f"  HASHTAG : {' '.join('#' + e.lstrip('#') for e in s['ig_hashtag'])}")

    cizgi("ÖZET")
    print(f"Başarılı            : {rapor['basarili']}")
    print(f"Hatalı              : {rapor['hatali']}")
    print(f"  tam metinle       : {rapor['tam_metin']}")
    print(f"  sadece özetle     : {rapor['ozet_ile']}")

    cizgi("VERİTABANI DURUMU")
    with db.baglan() as con:
        for satir in db.ozet_istatistik(con):
            print(f"  {satir['durum']:<18} {satir['adet']}")

    print()
    print("Doğrulama için: caption'daki her iddianın haberin kendisinde")
    print("gerçekten geçtiğini kontrol et. Makale metni veritabanında")
    print("makale_metni kolonunda duruyor:")
    print("  SELECT makale_metni FROM haberler WHERE id = <id>;")


if __name__ == "__main__":
    main()
