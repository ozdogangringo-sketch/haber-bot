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
# Seçenekler DÖNGÜSEL: butona her basışta sıradaki değere geçiyor.
# Serbest sayı girişi yerine sabit seçenek listesi tercih edildi —
# Telegram'da metin girişi ayrı bir akış gerektiriyor ve hatalı değer
# (eşik 99 gibi) botu sessizce durdurabilir.
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


def sonraki_degere_gec(con, ayarlar: dict, yol: str):
    """Ayarı seçenek listesindeki bir sonraki değere çevirir."""
    if yol not in DEGISTIRILEBILIR:
        raise ValueError(f"değiştirilemez ayar: {yol}")

    _, secenekler = DEGISTIRILEBILIR[yol]
    simdi = gecerli_deger(con, ayarlar, yol)
    try:
        sonraki = secenekler[(secenekler.index(simdi) + 1) % len(secenekler)]
    except ValueError:
        # Config'deki değer seçenek listesinde yoksa baştan başla.
        sonraki = secenekler[0]

    db.ayar_yaz(con, yol, sonraki)
    con.commit()
    log.info("ayar değişti: %s = %s", yol, sonraki)
    return sonraki


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
    satirlar.append("Değiştirmek için düğmeye bas — her basış sıradaki "
                    "değere geçer.")
    return "\n".join(satirlar)


def panel_butonlari(con, ayarlar: dict) -> list:
    tuslar = []
    for yol, (etiket, _) in DEGISTIRILEBILIR.items():
        deger = gecerli_deger(con, ayarlar, yol)
        tuslar.append([{
            "text": f"{etiket} → {_goster(deger)}",
            # Yol callback_data'ya gömülü; 64 bayt sınırının altında.
            "callback_data": f"ayar:{yol}",
        }])
    return tuslar
