"""
.env dosyasına bir anahtar ekler veya varsa günceller.

NEDEN VAR:
  1. `.env` nokta ile başladığı için macOS Finder'da görünmüyor,
     elle bulup açmak zor.
  2. Anahtarı `echo ... >> .env` gibi bir komutla eklersen anahtar
     terminal geçmişine (~/.zsh_history) yazılır ve orada kalır.
     Buradaki getpass anahtarı ekrana da geçmişe de yazmaz.
  3. Aynı anahtar zaten varsa satırı ikinci kez eklemek yerine
     günceller — mükerrer satır .env'i sessizce bozar.

KULLANIM:
    python scripts/anahtar_ekle.py PEXELS_API_KEY

Sonra anahtarı yapıştırıp Enter'a bas. Ekranda görünmemesi normal.
"""

from __future__ import annotations

import sys
from getpass import getpass
from pathlib import Path

ENV_YOLU = Path(__file__).resolve().parent.parent / ".env"


def anahtar_yaz(ad: str, deger: str) -> str:
    """Anahtarı .env'e yazar. 'eklendi' ya da 'güncellendi' döner."""
    satirlar = (
        ENV_YOLU.read_text(encoding="utf-8").splitlines()
        if ENV_YOLU.exists()
        else []
    )

    for i, satir in enumerate(satirlar):
        # Yorum satırlarını atla, yoksa "# PEXELS_API_KEY=..." örneğini
        # gerçek anahtar sanıp onu güncellerdik
        if satir.lstrip().startswith("#"):
            continue
        if satir.split("=", 1)[0].strip() == ad:
            satirlar[i] = f"{ad}={deger}"
            ENV_YOLU.write_text("\n".join(satirlar) + "\n", encoding="utf-8")
            return "güncellendi"

    satirlar.append(f"{ad}={deger}")
    ENV_YOLU.write_text("\n".join(satirlar) + "\n", encoding="utf-8")
    return "eklendi"


def main() -> int:
    if len(sys.argv) != 2:
        print("Kullanım: python scripts/anahtar_ekle.py ANAHTAR_ADI")
        print("Örnek   : python scripts/anahtar_ekle.py PEXELS_API_KEY")
        return 1

    ad = sys.argv[1].strip()
    print(f"\n{ad} değerini yapıştır ve Enter'a bas.")
    print("(Yazdığın ekranda GÖRÜNMEZ, bu normal — güvenlik için böyle.)\n")

    deger = getpass(f"{ad} = ").strip()
    if not deger:
        print("\n✗ Boş değer girildi, hiçbir şey yazılmadı.")
        return 1

    sonuc = anahtar_yaz(ad, deger)
    print(f"\n✓ {ad} .env dosyasına {sonuc} ({len(deger)} karakter).")
    print("  Anahtarın kendisi hiçbir yere yazdırılmadı.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
