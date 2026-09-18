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
import builtins
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
    for klasor in ("src", "scripts", "tests")
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
            # ⚠️ `from scripts import X` DE SAYILMALI (4 Eyl 2026).
            # Eskiden yalnızca `src` eşleniyordu ve `onay_isle.py`
            # içindeki `from scripts import ekonomi_turu` +
            # `ekonomi_turu.main()` çağrısı DENETİM DIŞI kalıyordu —
            # oysa o dosya aylar önce silinmişti. Kullanıcı düğmeye
            # basınca ImportError alıyordu, test tertemiz geçiyordu.
            elif dugum.module and dugum.module.startswith("scripts"):
                for ad in dugum.names:
                    esleme[ad.asname or ad.name] = f"scripts.{ad.name}"
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



def tanimsiz_isimleri_bul(yol: str, agac: ast.AST) -> list[str]:
    """
    Dosya İÇİNDE çağrılan ama hiçbir yerde tanımlanmamış isimleri bulur.

    ⚠️ NEDEN GEREKTİ (20 Ağu 2026): `son_dakika.py` içinde
    `oneri_esigi(...)` çağrılıyordu ama fonksiyon bir düzenleme
    sırasında silinmişti. Bütünlük testi bunu GÖREMEDİ çünkü yalnızca
    `modul.fonksiyon()` biçimindeki çağrıları denetliyordu; düz
    `fonksiyon()` çağrıları kapsam dışıydı.

    Sonuç: kod sözdizimi açısından geçerliydi, test temiz geçti, ve
    hata ancak GECE YARISI cron çalışınca ortaya çıktı —
    `NameError: name 'oneri_esigi' is not defined`. Tam olarak bu
    testin var olma sebebi olan senaryo.
    """
    tanimli = set(dir(builtins))
    for dugum in ast.walk(agac):
        if isinstance(dugum, (ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.ClassDef)):
            tanimli.add(dugum.name)
            # Parametreler ve yerel değişkenler
            if isinstance(dugum, (ast.FunctionDef, ast.AsyncFunctionDef)):
                a = dugum.args
                for arg in (a.args + a.posonlyargs + a.kwonlyargs
                            + ([a.vararg] if a.vararg else [])
                            + ([a.kwarg] if a.kwarg else [])):
                    tanimli.add(arg.arg)
        elif isinstance(dugum, (ast.Import, ast.ImportFrom)):
            for ad in dugum.names:
                tanimli.add((ad.asname or ad.name).split(".")[0])
        elif isinstance(dugum, ast.Name) and isinstance(dugum.ctx, ast.Store):
            tanimli.add(dugum.id)
        elif isinstance(dugum, ast.ExceptHandler) and dugum.name:
            tanimli.add(dugum.name)
        elif isinstance(dugum, ast.Lambda):
            for arg in (dugum.args.args + dugum.args.posonlyargs + dugum.args.kwonlyargs
                        + ([dugum.args.vararg] if dugum.args.vararg else [])
                        + ([dugum.args.kwarg] if dugum.args.kwarg else [])):
                tanimli.add(arg.arg)
        elif isinstance(dugum, (ast.comprehension,)):
            pass

    eksik = []
    for dugum in ast.walk(agac):
        # Yalnızca ÇAĞRILAN düz isimler: fonksiyon() biçimi
        if (isinstance(dugum, ast.Call)
                and isinstance(dugum.func, ast.Name)
                and dugum.func.id not in tanimli):
            eksik.append(f"{yol}:{dugum.lineno} — {dugum.func.id}() tanımlı değil")

    # ⚠️ EKSİK IMPORT DENETİMİ (20 Ağu 2026).
    #
    # `onay_isle.py` içinde `secim.konu_imzasi(...)` çağrılıyordu ama
    # `secim` hiç import edilmemişti. Yukarıdaki denetim bunu göremiyor
    # çünkü `modul.fonksiyon()` bir `ast.Attribute`, düz `ast.Name`
    # değil. Kod sözdizimi açısından geçerliydi ve hata ancak `/haber`
    # komutu çalıştırıldığında NameError olarak çıkacaktı.
    for dugum in ast.walk(agac):
        if (isinstance(dugum, ast.Attribute)
                and isinstance(dugum.value, ast.Name)
                and dugum.value.id not in tanimli):
            eksik.append(f"{yol}:{dugum.lineno} — "
                         f"'{dugum.value.id}' tanımlı/import değil "
                         f"(.{dugum.attr} olarak kullanılıyor)")
    return eksik


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
        "secim": ["asgari_onem_puani", "kategori_katsayilari",
                  "konu_ortak_kelime_esigi", "gecmis_konu_gun"],
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

        # Aynı dosyada tanımsız fonksiyon çağrısı var mı?
        hatalar += tanimsiz_isimleri_bul(yol, agac)

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
