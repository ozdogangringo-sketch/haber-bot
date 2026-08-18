"""
db_kaydet.py — veritabanını GitHub'a commit+push eder.

Her workflow'un SONUNDA çalışıyor. Runner geçici bir makine; `haber.db`
push edilmezse o turun bütün emeği (haberler, üretilen metinler, tur
kaydı) runner ile birlikte siliniyor.

⚠️ NEDEN AYRI BİR SCRIPT:
    Önce bu iş workflow YAML'ının içine gömülü git komutlarıyla
    yapılıyordu ve sonu şuydu:

        git push origin HEAD:main || (git fetch origin main &&
        git rebase origin/main && git push origin HEAD:main)

    `data/haber.db` İKİLİ bir dosya — iki job aynı anda yazdığında
    `git rebase` çakışıyor ve çözemiyor. 18 Ağu 2026 akşam turu böyle
    düştü: tur hazırlandı, push reddedildi (araya son dakika job'ı
    girmişti), rebase çakıştı, job kırmızı oldu ve turun tamamı
    kayboldu. Aynı arıza 17 Ağu'da da yaşanmış, o zaman `db_senkron`
    yazılarak Python tarafı düzeltilmiş ama YAML'daki bu ikinci kod
    yolu gözden kaçmıştı.

    `db_senkron.hemen_kaydet()` çakışmayı kendisi çözüyor (ikili
    dosyada birleştirme yok, taze turu seçiyor), çözemezse rebase'i
    iptal edip repoyu temiz bırakıyor — yarım rebase repoyu detached
    HEAD'de kilitliyor ve sonraki bütün job'ları da bozuyor.

ÇALIŞTIRMA:
    python scripts/db_kaydet.py "Tur hazırlandı"
    python scripts/db_kaydet.py "Tur hazırlandı" --ek assets/flags
"""

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

from src import db_senkron                          # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)s %(name)s: %(message)s",
                    datefmt="%H:%M:%S")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("etiket", help="commit mesajının başı")
    ap.add_argument("--ek", nargs="*", default=[],
                    help="veritabanı dışında eklenecek yollar")
    a = ap.parse_args()

    damga = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    tamam = db_senkron.hemen_kaydet(f"{a.etiket} {damga}", ek_yollar=a.ek)

    # Push edilemediyse job KIRMIZI olmalı: sessizce geçmek, verinin
    # kaybolduğunu sabaha kadar gizler.
    if not tamam:
        print("✗ veritabanı push EDİLEMEDİ", file=sys.stderr)
        return 1
    print("✓ veritabanı kaydedildi")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
