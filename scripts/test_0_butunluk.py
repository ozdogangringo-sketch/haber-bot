"""
BÜTÜNLÜK TESTİ — kod çalıştırmadan hataları yakalar.
Çalıştır:  python scripts/test_0_butunluk.py

NEDEN VAR:
    İki kez aynı hataya düştük: `hazirla.py` var olmayan fonksiyonları
    çağırıyordu (`fetch_news.hepsini_cek`, ve `metinleri_uret` yanlış
    imzayla). İkisi de sözdizimi açısından geçerliydi, testler geçiyordu,
    ama ilk gerçek çalıştırmada patladılar.

    Python bunu kendiliğinden yakalamıyor: modül çağrısı ancak o satır
    çalıştığında çözümleniyor. Gözetimsiz çalışan bir botta bu, "gece
    yarısı job patlar, sabah fark edilir" demek.

BU TEST NE YAPIYOR:
    Scriptleri ÇALIŞTIRMADAN ayrıştırıyor, `modul.fonksiyon()` biçimindeki
    her çağrıyı bulup fonksiyonun gerçekten var olduğunu ve argüman
    sayısının uyduğunu denetliyor.

    Ağa çıkmıyor, veritabanına dokunmuyor, para harcamıyor. Her değişiklik
    sonrası çalıştırılabilir.
"""

import ast
import importlib
import inspect
import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

DENETLENEN = [
    "scripts/hazirla.py",
    "scripts/onay_isle.py",
    "scripts/hatirlat.py",
    "scripts/jeton_yenile.py",
    "scripts/test_6_tur_gorsel.py",
    "scripts/son_dakika.py",
]


def modul_adlarini_bul(agac: ast.AST) -> dict[str, str]:
    """`from src import a, b` ile gelen adları gerçek modül yoluna eşler."""
    esleme = {}
    for dugum in ast.walk(agac):
        if isinstance(dugum, ast.ImportFrom) and dugum.module:
            if not dugum.module.startswith("src"):
                continue
            for ad in dugum.names:
                esleme[ad.asname or ad.name] = f"src.{ad.name}"
    return esleme


def argumanlari_denetle(fn, cagri: ast.Call) -> str | None:
    """Çağrıdaki argüman sayısı fonksiyonun imzasına uyuyor mu?"""
    try:
        imza = inspect.signature(fn)
    except (TypeError, ValueError):
        return None

    konumlu = len(cagri.args)
    anahtarli = {k.arg for k in cagri.keywords if k.arg}

    # *args / **kwargs varsa sayım anlamsız
    if any(p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
           for p in imza.parameters.values()):
        return None

    azami = len([p for p in imza.parameters.values()
                 if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)])
    if konumlu > azami:
        return f"{konumlu} konumlu argüman verildi, en fazla {azami} alıyor"

    for ad in anahtarli:
        if ad not in imza.parameters:
            return f"'{ad}' diye bir parametresi yok"

    return None


def main() -> int:
    hatalar = []
    denetlenen_cagri = 0

    for yol in DENETLENEN:
        tam = KOK / yol
        if not tam.exists():
            hatalar.append(f"{yol}: dosya yok")
            continue

        agac = ast.parse(tam.read_text(encoding="utf-8"))
        esleme = modul_adlarini_bul(agac)

        for dugum in ast.walk(agac):
            if not isinstance(dugum, ast.Call):
                continue
            if not isinstance(dugum.func, ast.Attribute):
                continue
            if not isinstance(dugum.func.value, ast.Name):
                continue

            takma = dugum.func.value.id
            if takma not in esleme:
                continue

            denetlenen_cagri += 1
            fn_ad = dugum.func.attr
            try:
                modul = importlib.import_module(esleme[takma])
            except Exception as e:
                hatalar.append(f"{yol}:{dugum.lineno} — {esleme[takma]} "
                               f"içe aktarılamadı: {e}")
                continue

            fn = getattr(modul, fn_ad, None)
            if fn is None:
                hatalar.append(f"{yol}:{dugum.lineno} — "
                               f"{esleme[takma]}.{fn_ad}() YOK")
                continue

            sorun = argumanlari_denetle(fn, dugum)
            if sorun:
                hatalar.append(f"{yol}:{dugum.lineno} — "
                               f"{esleme[takma]}.{fn_ad}(): {sorun}")

    print("=" * 70)
    print("BÜTÜNLÜK TESTİ")
    print("=" * 70)
    print(f"  Denetlenen dosya : {len(DENETLENEN)}")
    print(f"  Denetlenen çağrı : {denetlenen_cagri}")
    print()

    if hatalar:
        print(f"  ✗ {len(hatalar)} SORUN:\n")
        for h in hatalar:
            print(f"    {h}")
        return 1

    print("  ✓ Bütün modül çağrıları geçerli — fonksiyonlar var, "
          "imzalar uyuyor.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
