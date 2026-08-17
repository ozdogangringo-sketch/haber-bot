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

from src import db, telegram_bot             # noqa: E402

log = logging.getLogger("hatirlat")

# Bu saatten sonra hatırlatmak yerine havuza döndürüyoruz.
# UTC 20:00 = TR 23:00 — gece yarısı post atmanın anlamı yok.
HAVUZA_DON_SAATI_UTC = 20


def bekleyen_tur(con):
    """Onay bekleyen en son turu döner."""
    # SON DAKİKA TURLARI HARİÇ: onların kendi ömrü var (gündüz 1 saat,
    # gece sabaha kadar) ve son_dakika.py onları kendisi düşürüyor.
    # Buraya karışırsa aynı tur iki yerden yönetilmiş oluyor ve
    # hatırlatma, birazdan iptal olacak bir turu işaret ediyor.
    return list(con.execute(
        "SELECT * FROM haberler WHERE durum IN ('onay_bekliyor', 'ertelendi') "
        "AND telegram_message_id IS NOT NULL "
        "AND (son_dakika IS NULL OR son_dakika = 0) "
        "ORDER BY onem_puani DESC, yayin_tarihi DESC"
    ))


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")

    yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    db.kur()
    con = db.baglan()

    haberler = bekleyen_tur(con)
    if not haberler:
        log.info("onay bekleyen tur yok, yapacak bir şey yok")
        return 0

    mesaj_id = haberler[0]["telegram_message_id"]
    simdi = datetime.now(timezone.utc)

    # --- Gece: havuza döndür ---
    if simdi.hour >= HAVUZA_DON_SAATI_UTC:
        con.execute(
            "UPDATE haberler SET durum = 'yeni', telegram_message_id = NULL "
            "WHERE telegram_message_id = ?",
            (mesaj_id,),
        )
        con.commit()
        try:
            telegram_bot.sonucu_yaz(
                mesaj_id,
                f"🌙 Onay gelmedi, tur kapandı.\n"
                f"{len(haberler)} haber havuza döndü — elenmediler, "
                f"yarınki turda yeniden yarışacaklar.",
            )
        except Exception as e:
            # Mesaj düzenlenemese bile veritabanı doğru; tur kapanmış olmalı
            log.warning("sonuç mesajı yazılamadı: %s", e)
        log.info("%s haber havuza döndürüldü", len(haberler))
        return 0

    # --- Erken saat: hatırlat ---
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
