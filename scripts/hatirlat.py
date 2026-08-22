"""
hatirlat.py — Onaylanmamış turu hatırlatır, geç kalırsa havuza döndürür.

NE ZAMAN NE YAPAR:
    Onay bekleyen tur varsa ve üzerinden yeterli süre geçtiyse gruba
    hatırlatma atar. Son turda (gece) hatırlatmak yerine haberleri
    havuza geri koyar.

HABERLER ELENMİYOR:
    Onay verilmeyen haber silinmiyor, `durum='yeni'` yapılıp havuza
    dönüyor ve ertesi turda yeni haberlerle yeniden yarışıyor. Yalnızca
    48 saatlik bayatlama sınırını geçenler kendiliğinden aday olmaktan
    çıkıyor (bu eleme secim.py'de, burada değil).

TELEGRAM OKUNMUYOR:
    Webhook kurulu olduğu için getUpdates çalışmaz. Bu script yalnızca
    veritabanına bakıyor; onay gelip gelmediğini `durum` sütunundan
    anlıyor.
"""

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import yaml                                  # noqa: E402

from src import db, telegram_bot, yonetim             # noqa: E402

log = logging.getLogger("hatirlat")

# Onay bekleyen tur kaç saat sonra havuza dönsün (24 saat).
# Kullanıcı kararı: Görselleri hazırlanmış bir tur en az 1 gün boyunca
# Telegram'da onaylanmaya hazır beklemelidir.
AZAMI_BEKLEME_SAAT = 24


def _tur_yasi_dakika(haber) -> float | None:
    """Tur Telegram'a düşeli kaç dakika oldu? Bilinmiyorsa None."""
    ham = haber["gonderim_zamani"]
    if not ham:
        return None
    try:
        # `datetime('now')` ile yazılıyor, yani UTC ve saat dilimi eki yok.
        gonderim = datetime.fromisoformat(ham).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - gonderim).total_seconds() / 60


def bekleyen_tur(con):
    """Onay bekleyen en son turu döner."""
    # SON DAKİKA TURLARI HARİÇ: onların kendi ömrü var ve son_dakika.py yönetiyor.
    return list(con.execute(
        # ⚠️ Planlanmış yayın (yayınla > "2 saat sonra") burada
        # GÖRÜNMEMELİ: 24 saatlik bekleme kuralı turu havuza döndürür
        # ve o ana kadar her saat gereksiz hatırlatma atılırdı.
        # Zamanı gelince son dakika kontrolü yayınlıyor.
        "SELECT * FROM haberler WHERE planlanan_yayin IS NULL "
        "AND durum IN ('onay_bekliyor', 'ertelendi', 'baslik_onayi') "
        "AND telegram_message_id IS NOT NULL "
        "AND (son_dakika IS NULL OR son_dakika = 0) "
        "ORDER BY onem_puani DESC, yayin_tarihi DESC"
    ))


def _turu_isle(con, mesaj_id: int, haberler: list, simdi) -> None:
    """
    Tek bir turu değerlendirir: 24 saat dolduysa kapat, dolmadıysa hatırlat.
    """
    yas = _tur_yasi_dakika(haberler[0])
    cok_bekledi = yas is not None and yas >= AZAMI_BEKLEME_SAAT * 60

    if cok_bekledi:
        con.execute(
            "UPDATE haberler SET telegram_message_id = NULL, "
            "durum = CASE WHEN ig_baslik IS NOT NULL THEN 'metin_hazir' "
            "             ELSE 'yeni' END "
            "WHERE telegram_message_id = ?",
            (mesaj_id,),
        )
        con.commit()
        try:
            telegram_bot.sonucu_yaz(
                mesaj_id,
                f"⌛️ 24 saat boyunca onay gelmediği için tur kapandı.\n"
                f"{len(haberler)} haber havuza döndü — elenmediler, "
                f"sonraki turlarda yeniden yarışacaklar.",
                bildir=True,
            )
        except Exception as e:
            log.warning("sonuç mesajı yazılamadı: %s", e)
        log.info("%s haber 24 saat sonra havuza döndürüldü", len(haberler))
        return

    # --- 24 saat dolmadı: hatırlat ---
    sayi = (haberler[0]["hatirlatma_sayisi"] or 0) + 1
    con.execute(
        "UPDATE haberler SET hatirlatma_sayisi = ? WHERE telegram_message_id = ?",
        (sayi, mesaj_id),
    )
    con.commit()

    telegram_bot.mesaj_gonder(
        f"⏳ Onay bekleyen {len(haberler)} haberlik tur var ({sayi}. hatırlatma).\n"
        f"Yukarıdaki mesajdan yayınlayabilir veya atlayabilirsin.\n"
        f"Onay gelmezse gece havuza dönecek — haberler elenmiyor."
    )
    log.info("hatırlatma gönderildi (%s.)", sayi)
    return




def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")

    yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    db.kur()
    con = db.baglan()

    # ⚠️ BOT DURAKLATILDI MI KONTROLÜ (Acil durum / Mute)
    duraklatildi, kalan = yonetim.duraklatildi_mi(con)
    if duraklatildi:
        log.info("Bot duraklatılmış durumda (kalan: %s), hatırlatma atlandı.", kalan)
        con.close()
        return 0

    haberler = bekleyen_tur(con)
    if not haberler:
        log.info("onay bekleyen tur yok, yapacak bir şey yok")
        return 0

    # ⚠️ AYNI ANDA BİRDEN FAZLA AÇIK TUR OLABİLİR ve hepsi işlenmeli.
    #
    # 21 Ağu 2026: sabah 09:23'te kurulan tur hiç kapanmadı çünkü bu
    # fonksiyon yalnızca `haberler[0]`ın turunu işliyordu. Akşam yeni
    # tur kurulunca hatırlatma hep ONU görüyor, sabahki tur sonsuza
    # kadar açık kalıyordu. Kullanıcı "sırada 20 küsür bekliyor"
    # uyarısını böyle aldı: 10 + 10 + 1 = 21 haber, üç tur birden.
    turlar: dict = {}
    for h in haberler:
        turlar.setdefault(h["telegram_message_id"], []).append(h)
    log.info("%s açık tur var: %s", len(turlar), list(turlar))

    simdi = datetime.now(timezone.utc)
    for mesaj_id, tur_haberleri in sorted(turlar.items()):
        try:
            _turu_isle(con, mesaj_id, tur_haberleri, simdi)
        except Exception as e:                        # noqa: BLE001
            # Bir turun hatası diğerlerini engellememeli.
            log.exception("tur %s işlenemedi: %s", mesaj_id, e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
