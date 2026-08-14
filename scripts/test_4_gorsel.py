"""
ADIM 3 TESTİ — görsel üretimi
Çalıştır:  python scripts/test_4_gorsel.py           (1 görsel, AI arka plan)
           python scripts/test_4_gorsel.py 2         (2 görsel)
           python scripts/test_4_gorsel.py 1 yedek   (AI'sız, bedava test)

DİKKAT: 'yedek' yazmazsan her görsel ~$0.039 tutar ve günlük sayaçtan düşer.
Yazı yerleşimini denemek istiyorsan 'yedek' modu bedava ve anında.

durum='metin_hazir' haberleri kullanır (Adım 2'nin çıktısı).
"""

import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

from src import db                                    # noqa: E402
from src.fetch_news import ayarlari_oku               # noqa: E402
from src.make_image import (                          # noqa: E402
    arkaplan_uret_yedek,
    gorsel_uret,
    yaziyi_bas,
)


def main():
    kac = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    yedek_mi = len(sys.argv) > 2 and sys.argv[2] == "yedek"

    ayarlar = ayarlari_oku()
    db.kur()

    with db.baglan() as con:
        haberler = db.bekleyenler(con, durum="metin_hazir", limit=kac)

        if not haberler:
            print("durum='metin_hazir' haber yok.")
            print("Önce çalıştır: python scripts/test_3_metin_uret.py")
            return

        print("=" * 70)
        print("AI arka plan (ÜCRETLİ)" if not yedek_mi
              else "Yedek gradyan arka plan (bedava)")
        print("=" * 70)

        for haber in haberler:
            print(f"\n[{haber['id']}] {haber['kaynak']}")
            print(f"  başlık: {haber['ig_baslik']}")

            if yedek_mi:
                # AI'ya hiç gitmeden sadece yazı yerleşimini dene
                arkaplan = arkaplan_uret_yedek(
                    haber["kategori"], ayarlar["gorsel"]["boyut"]
                )
                gorsel = yaziyi_bas(
                    arkaplan, haber["ig_baslik"], haber["kaynak"], ayarlar
                )
                yol = KOK / "data" / "output" / f"haber-{haber['id']}-yedek.jpg"
                yol.parent.mkdir(parents=True, exist_ok=True)
                gorsel.save(yol, "JPEG", quality=ayarlar["gorsel"]["jpeg_kalite"])
            else:
                yol = gorsel_uret(haber, ayarlar, con)

            con.commit()
            boyut_kb = yol.stat().st_size / 1024
            print(f"  → {yol.name}  ({boyut_kb:.0f} KB)")

        # Sayacın durumu
        gun = db.ayar_oku(con, "gorsel_sayac_gun", "-")
        adet = db.ayar_oku(con, "gorsel_sayac_adet", 0)
        print(f"\nGünlük görsel sayacı: {adet}/{ayarlar['gorsel']['gunluk_azami']}"
              f"  (gün: {gun})")


if __name__ == "__main__":
    main()
