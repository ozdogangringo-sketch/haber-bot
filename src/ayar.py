"""
ayar.py — Telegram'dan değiştirilebilen çalışma ayarları.

NEDEN VAR:
    Gece otomatik yayınını kapatmak, son dakika eşiğini yükseltmek ya da
    bir kanalı geçici durdurmak için `config.yaml` düzenleyip commit +
    push gerekiyordu. Telefondayken bu pratikte imkânsız.

TASARIM — İKİ KATMAN:
    `config.yaml`      : varsayılan değerler, git'te, kalıcı tercih
    `ayarlar` tablosu  : Telegram'dan yapılan değişiklikler, üste biner

    Veritabanı her job sonunda repoya commit edildiği için buradaki
    değişiklik kalıcı oluyor ve runner'lar arasında taşınıyor.

⚠️ BEYAZ LİSTE ZORUNLU. `DEGISTIRILEBILIR` dışındaki hiçbir anahtar
   yazılamıyor. Telegram grubuna herkes yazabiliyor (kullanıcının açık
   tercihi); keyfi anahtar/değer kabul etmek, grup üzerinden botun
   davranışını serbestçe değiştirmek demek olurdu.
"""

from __future__ import annotations

import logging

from . import db

log = logging.getLogger(__name__)

# Değiştirilebilir ayarlar: yol -> (etiket, seçenekler)
#
# Panelde her ayar bir düğme; basınca seçeneklerin listelendiği alt menü
# açılıyor. İlk sürüm düğmeye her basışta sıradaki değere geçiyordu ama
# üç seçenekli eşiklerde istenen değere ulaşmak birkaç basış gerektiriyor
# ve zahmetli oluyordu.
#
# Serbest sayı girişi yerine sabit seçenek listesi: Telegram'da metin
# girişi ayrı bir akış gerektiriyor ve hatalı değer (eşik 99 gibi) botu
# sessizce durdurabilir.
DEGISTIRILEBILIR: dict[str, tuple[str, list]] = {
    "genel.gece_otomatik_yayin": (
        "🌙 Gece otomatik yayın", [True, False]),
    "genel.son_dakika_puan_esigi": (
        "⚡ Son dakika eşiği (gündüz)", [7, 8, 9]),
    "genel.gece_puan_esigi": (
        "🌙 Son dakika eşiği (gece)", [8, 9, 10]),
    "genel.son_dakika_gunluk_azami": (
        "🔢 Günlük son dakika sınırı", [1, 2, 3]),
    "sosyal.facebooka_da_at": (
        "📘 Facebook paylaşımı", [True, False]),
    "sosyal.threadse_de_at": (
        "🧵 Threads paylaşımı", [True, False]),
}


def _cozumle(ham: str, ornek):
    """Metin olarak saklanan değeri örnek değerin türüne çevirir."""
    if isinstance(ornek, bool):
        return ham.lower() in ("true", "1", "evet", "acik")
    if isinstance(ornek, int):
        try:
            return int(ham)
        except ValueError:
            return ornek
    return ham


def _config_degeri(ayarlar: dict, yol: str):
    parca = ayarlar
    for ad in yol.split("."):
        parca = (parca or {}).get(ad)
    return parca


def yollari_dogrula(ayarlar: dict) -> list[str]:
    """
    Beyaz listedeki yollar `config.yaml`'de gerçekten var mı?

    ⚠️ SESSİZ HATA KORUMASI. Yol yanlış yazılırsa panel değeri "None"
    gösteriyor ve değiştirme hiçbir işe yaramıyor — ama hiçbir yerde
    hata çıkmıyor. Kurulumda tam olarak bu oldu:
    `gunluk_azami_son_dakika` yazılmıştı, doğrusu
    `son_dakika_gunluk_azami`.
    """
    return [yol for yol in DEGISTIRILEBILIR
            if _config_degeri(ayarlar, yol) is None]


def uygula(con, ayarlar: dict) -> dict:
    """
    Veritabanındaki değişiklikleri `config.yaml` sözlüğünün üstüne işler.

    Her script config'i yükledikten HEMEN SONRA bunu çağırmalı; yoksa
    Telegram'dan yapılan değişiklik o akışta geçersiz kalır.
    """
    for yol, (_, secenekler) in DEGISTIRILEBILIR.items():
        ham = db.ayar_oku(con, yol)
        if ham is None:
            continue
        deger = _cozumle(ham, secenekler[0])
        ust, alt = yol.split(".", 1)
        ayarlar.setdefault(ust, {})[alt] = deger
    return ayarlar


def gecerli_deger(con, ayarlar: dict, yol: str):
    """Şu an geçerli olan değer (veritabanı varsa o, yoksa config)."""
    ham = db.ayar_oku(con, yol)
    if ham is None:
        return _config_degeri(ayarlar, yol)
    return _cozumle(ham, DEGISTIRILEBILIR[yol][1][0])


def _goster(deger) -> str:
    if isinstance(deger, bool):
        return "AÇIK" if deger else "KAPALI"
    return str(deger)


def panel_metni(con, ayarlar: dict) -> str:
    satirlar = ["⚙️ AYARLAR", ""]
    for yol, (etiket, _) in DEGISTIRILEBILIR.items():
        deger = gecerli_deger(con, ayarlar, yol)
        varsayilan = _config_degeri(ayarlar, yol)
        # Varsayılandan farklıysa işaretliyoruz: hangi ayarın elle
        # değiştirildiği bir bakışta görünsün.
        isaret = "  ·değişik" if db.ayar_oku(con, yol) is not None \
                                 and deger != varsayilan else ""
        satirlar.append(f"{etiket}: {_goster(deger)}{isaret}")
    satirlar.append("")
    satirlar.append("Değiştirmek istediğin ayara bas, seçenekler açılsın.")
    return "\n".join(satirlar)


def _kodla(deger) -> str:
    """Seçeneği callback_data'ya sığacak biçimde kodlar."""
    if isinstance(deger, bool):
        return "true" if deger else "false"
    return str(deger)


def coz(yol: str, kod: str):
    """`ayarsec` ile gelen kodu gerçek değere çevirir."""
    secenekler = DEGISTIRILEBILIR[yol][1]
    for s in secenekler:
        if _kodla(s) == kod:
            return s
    raise ValueError(f"geçersiz değer: {kod}")


def panel_butonlari(con, ayarlar: dict) -> list:
    """
    Ana panel: her ayar bir satır, basınca alt menü açılıyor.

    ⚠️ SEÇENEKLER DÜĞMEYE GÖMÜLÜ ("...:true-false", "...:7-8-9").
    Alt menü Worker'da açılıyor çünkü GitHub Actions'ı uyandırmak 30+
    saniye sürüyor ve menü açmak anında olmalı. Ama Worker hangi ayarın
    hangi seçeneklere sahip olduğunu bilmiyor; listeyi oraya kopyalamak
    menüyü ÜÇÜNCÜ bir yerde tekrarlamak olurdu. Seçenekleri düğmeyle
    taşıyınca Worker onları veriden okuyor, tek kaynak burası kalıyor.
    """
    tuslar = []
    for yol, (etiket, secenekler) in DEGISTIRILEBILIR.items():
        deger = gecerli_deger(con, ayarlar, yol)
        kodlar = "-".join(_kodla(s) for s in secenekler)
        tuslar.append([{
            "text": f"{etiket}: {_goster(deger)}",
            "callback_data": f"ayarmenu:{yol}:{kodlar}",
        }])
    return tuslar


def alt_menu_butonlari(con, ayarlar: dict, yol: str) -> list:
    """Tek ayarın seçenekleri; geçerli değer ✅ ile işaretli."""
    etiket, secenekler = DEGISTIRILEBILIR[yol]
    simdi = gecerli_deger(con, ayarlar, yol)
    satir = []
    for s in secenekler:
        isaret = "✅ " if s == simdi else ""
        satir.append({"text": f"{isaret}{_goster(s)}",
                      "callback_data": f"ayarsec:{yol}:{_kodla(s)}"})
    return [satir, [{"text": "← Ayarlara dön", "callback_data": "ayar"}]]


def alt_menu_metni(con, ayarlar: dict, yol: str) -> str:
    # Etiket zaten kendi emojisini taşıyor; başına bir tane daha koymak
    # "⚙️ ⚡ Son dakika eşiği" gibi çift emoji üretiyordu.
    etiket, _ = DEGISTIRILEBILIR[yol]
    return (f"{etiket}\n\n"
            f"Şu an: {_goster(gecerli_deger(con, ayarlar, yol))}\n\n"
            f"Yeni değeri seç:")


def deger_ata(con, ayarlar: dict, yol: str, kod: str):
    """Alt menüden seçilen değeri yazar."""
    if yol not in DEGISTIRILEBILIR:
        raise ValueError(f"değiştirilemez ayar: {yol}")
    deger = coz(yol, kod)
    db.ayar_yaz(con, yol, deger)
    con.commit()
    log.info("ayar değişti: %s = %s", yol, deger)
    return deger
