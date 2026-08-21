"""
SESSİZ BAŞARISIZLIK AVI

Arıyor: bir iş YAPILMADAN `return 0` (başarı) ile çıkan ve kullanıcıya
hiçbir şey söylemeyen kod yolları.

21 Ağu 2026'da bu desen dört kez canlıda hataya dönüştü:
  * günlük sınır dolu -> return 0, kullanıcı "hazırlanıyor"da kaldı
  * fuzzy sonuçlar alt satırda elendi -> "bulunamadı"
  * kuyrukta iptal -> hiçbir bildirim
  * Threads kapalıysa NameError riski
"""
import ast
import pathlib

KOK = pathlib.Path(".")
BILDIRIM = ("mesaj_gonder", "sonucu_yaz", "hata_bildir", "bildir",
            "onay_iste", "oneri_gonder", "foto_gonder", "basliklari_sun",
            "paylasim_bildir", "menuyu_geri_koy", "slaytlari_gonder")


def _bildirim_var(dugum) -> bool:
    """Bu dal kullanıcıya bir şey söylüyor mu?"""
    for n in ast.walk(dugum):
        if isinstance(n, ast.Call):
            ad = ""
            if isinstance(n.func, ast.Attribute):
                ad = n.func.attr
            elif isinstance(n.func, ast.Name):
                ad = n.func.id
            if ad in BILDIRIM:
                return True
    return False


def tara(yol: pathlib.Path) -> list:
    kaynak = yol.read_text(encoding="utf-8")
    agac = ast.parse(kaynak)
    satirlar = kaynak.splitlines()
    bulgular = []
    for islev in ast.walk(agac):
        if not isinstance(islev, ast.FunctionDef):
            continue
        # Yardımcı fonksiyonlar (alt çizgili) kullanıcıya bildirim
        # yapmaz; onları çağıran akış yapar.
        if islev.name.startswith("_"):
            continue
        # Fonksiyon genelinde bildirim varsa, dal bazlı bakmaya gerek yok
        for dal in ast.walk(islev):
            if not isinstance(dal, (ast.If, ast.Try)):
                continue
            for govde in ([dal.body] + ([dal.orelse] if hasattr(dal, "orelse") else [])):
                # Dalın SON ifadesi "return 0" mu?
                if not govde:
                    continue
                son = govde[-1]
                # ⚠️ `return False` de `== 0` veriyor — tip kontrolü şart.
                if not (isinstance(son, ast.Return)
                        and isinstance(son.value, ast.Constant)
                        and son.value.value == 0
                        and isinstance(son.value.value, int)
                        and not isinstance(son.value.value, bool)):
                    continue
                # Bu dalda kullanıcıya bir şey söyleniyor mu?
                if any(_bildirim_var(x) for x in govde):
                    continue
                kosul = ""
                if isinstance(dal, ast.If):
                    kosul = satirlar[dal.lineno - 1].strip()[:70]
                # `--kuru` dalları bilerek sessiz: kuru çalışmanın
                # sözleşmesi "Telegram'a gönderme".
                if "kuru" in kosul or "sadece_bak" in kosul:
                    continue
                bulgular.append((islev.name, son.lineno, kosul))
    return bulgular


print(f"{'dosya':<26}{'fonksiyon':<26}{'satır':>7}  koşul")
print("-" * 100)
toplam = 0
for yol in sorted(list(KOK.glob("scripts/*.py")) + list(KOK.glob("src/*.py"))):
    if yol.name.startswith("test_"):
        continue
    for ad, satir, kosul in tara(yol):
        print(f"{yol.name:<26}{ad:<26}{satir:>7}  {kosul}")
        toplam += 1
print("-" * 100)
print(f"  {toplam} sessiz 'return 0' bulundu")
