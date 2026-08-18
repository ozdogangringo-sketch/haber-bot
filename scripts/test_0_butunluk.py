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

# ⚠️ LİSTE ELLE TUTULMUYOR — src/ ve scripts/ altındaki HER .py dosyası
# otomatik denetleniyor.
#
# Önce sabit bir liste vardı ve iki kez aynı şekilde yanılttı:
#   * src/ modülleri listede yoktu -> `detay_slayti(son_dakika=...)`
#     hatası gözden kaçtı, bozuk kod push edildi (17 Ağu 2026).
#   * Sonradan eklenen dosyalar (ayar.py, threads.py, gunluk_rapor.py…)
#     listeye girmediği için denetim dışı kaldı; `instagram.kota_durumu`
#     diye var olmayan bir fonksiyon çağrısı testten TEMİZ geçti
#     (18 Ağu 2026).
#
# Yeni dosya eklerken hiçbir şey yapmaya gerek yok; kapsam kendiliğinden
# genişliyor.
DENETLENEN = sorted(
    str(p.relative_to(KOK))
    for klasor in ("src", "scripts")
    for p in (KOK / klasor).glob("*.py")
    if p.name != "__init__.py" and p.name != Path(__file__).name
)


def modul_adlarini_bul(agac: ast.AST) -> dict[str, str]:
    """`from src import a, b` ile gelen adları gerçek modül yoluna eşler."""
    esleme = {}
    for dugum in ast.walk(agac):
        # "from src import x" (scripts/) ve "from . import x" (src/)
        if isinstance(dugum, ast.ImportFrom):
            if dugum.module and dugum.module.startswith("src"):
                for ad in dugum.names:
                    esleme[ad.asname or ad.name] = f"src.{ad.name}"
            elif dugum.level == 1 and not dugum.module:
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


def config_denetle() -> list[str]:
    """
    `config.yaml` kodun beklediği anahtarları taşıyor mu?

    ⚠️ NEDEN GEREKTİ: 18 Ağu 2026'da config programatik olarak yeniden
    yazılırken `secim:` bloğunun tamamı silindi. Kod varsayılanlara
    düştüğü için HİÇBİR HATA ÇIKMADI — yalnızca `asgari_onem_puani`
    devre dışı kaldı ve o gün eklenen "esnek tur uzunluğu" özelliği
    sessizce etkisizleşti. Bu tür kayıplar ancak aranırsa bulunuyor.
    """
    import yaml

    sorunlar = []
    try:
        cfg = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    except Exception as e:
        return [f"config.yaml okunamadı: {e}"]

    # Kodun `ayarlar["x"]` ile doğrudan istediği üst anahtarlar
    gerekli = {"genel", "gemini", "gorsel", "imgbb", "instagram", "kaynaklar"}
    for anahtar in sorted(gerekli - set(cfg)):
        sorunlar.append(f"config.yaml: '{anahtar}' bloğu YOK")

    # Kod tarafında varsayılanı olan ama bilinçli konmuş ayarlar —
    # kaybolurlarsa özellik sessizce devre dışı kalıyor.
    beklenen = {
        "secim": ["asgari_onem_puani", "on_eleme_kategori_payi",
                  "konu_ortak_kelime_esigi"],
        "sosyal": ["kanallar"],
    }
    for blok, alanlar in beklenen.items():
        if blok not in cfg:
            sorunlar.append(f"config.yaml: '{blok}' bloğu YOK")
            continue
        for alan in alanlar:
            if alan not in (cfg[blok] or {}):
                sorunlar.append(f"config.yaml: {blok}.{alan} YOK")

    # Ayar panelindeki yollar config'de gerçekten var mı?
    try:
        from src import ayar
        for yol in ayar.yollari_dogrula(cfg):
            sorunlar.append(f"config.yaml: ayar paneli '{yol}' bulamıyor")
    except Exception as e:
        sorunlar.append(f"ayar yolları denetlenemedi: {e}")

    # Kaynaklar: zorunlu alanlar ve benzersiz adlar
    adlar = set()
    for k in cfg.get("kaynaklar") or []:
        for alan in ("ad", "url", "kategori", "agirlik"):
            if alan not in k:
                sorunlar.append(f"kaynak {k.get('ad', '?')}: '{alan}' eksik")
        if k.get("ad") in adlar:
            sorunlar.append(f"kaynak adı tekrar ediyor: {k['ad']}")
        adlar.add(k.get("ad"))

    return sorunlar


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

    hatalar += config_denetle()

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
