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

# Bu saatten sonra hatırlatmak yerine havuza döndürüyoruz.
# UTC 20:00 = TR 23:00 — gece yarısı post atmanın anlamı yok.
HAVUZA_DON_SAATI_UTC = 20

# ⚠️ TAZE TUR KAPATILMAZ. Tur bu süreden yeniyse, saat geç olsa bile
# havuza döndürmüyoruz — yalnızca hatırlatıyoruz.
#
# 17 Ağu 2026: akşam turu bir arıza yüzünden elle TR 22:56'da kuruldu ve
# 11 dakika sonraki hatırlatma job'ı onu "onay gelmedi" diye kapatacaktı.
# Kullanıcıya onaylaması için 11 dakika tanımak yanlış; normal 20:07
# turunda 3 saatlik pay var, elle kurulan turda yok.
TAZE_TUR_DAKIKA = 90

# ⚠️ TUR SONSUZA KADAR AÇIK KALMASIN.
#
# Havuza dönüş eskiden YALNIZCA saate bakıyordu (TR 23:00) çünkü günde
# tek tur vardı. 19 Ağu 2026'da sabah turu (TR 08:07) eklendi ve o kural
# yetersiz kaldı: sabah onaylanmayan tur akşam 23:00'e kadar açık
# kalıyor, akşam turu kurulduğunda iki tur çakışıyordu.
#
# Artık tur şu kadar saat onaysız beklerse saat kaç olursa olsun havuza
# dönüyor. 6 saat seçildi: sabah turuna öğlene kadar, akşam turuna gece
# yarısına kadar süre tanıyor — ikisi de rahat, ama üst üste binmiyorlar.
AZAMI_BEKLEME_SAAT = 6


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
    # SON DAKİKA TURLARI HARİÇ: onların kendi ömrü var (gündüz 1 saat,
    # gece sabaha kadar) ve son_dakika.py onları kendisi düşürüyor.
    # Buraya karışırsa aynı tur iki yerden yönetilmiş oluyor ve
    # hatırlatma, birazdan iptal olacak bir turu işaret ediyor.
    return list(con.execute(
        # ⚠️ Planlanmış yayın (yayınla > "2 saat sonra") burada
        # GÖRÜNMEMELİ: 6 saatlik bekleme kuralı turu havuza döndürür
        # ve o ana kadar her saat gereksiz hatırlatma atılırdı.
        # Zamanı gelince son dakika kontrolü yayınlıyor.
        "SELECT * FROM haberler WHERE planlanan_yayin IS NULL "
        # ⚠️ `baslik_onayi` DA BURADA OLMALI. İki aşamalı tur akışında
        # başlıkları sunulmuş ama onaylanmamış tur bu durumda bekliyor;
        # listeye alınmazsa ne hatırlatılır ne kapanır, sonsuza kadar
        # açık kalır ve ertesi turla çakışır.
        "AND durum IN ('onay_bekliyor', 'ertelendi', 'baslik_onayi') "
        "AND telegram_message_id IS NOT NULL "
        "AND (son_dakika IS NULL OR son_dakika = 0) "
        "ORDER BY onem_puani DESC, yayin_tarihi DESC"
    ))


def _turu_isle(con, mesaj_id: int, haberler: list, simdi) -> None:
    """
    Tek bir turu değerlendirir: hatırlat, kapat ya da dokunma.

    `main` her açık tur için ayrı ayrı çağırıyor — önce yalnızca
    en yüksek puanlı haberin turu işleniyordu ve diğerleri
    sonsuza kadar açık kalıyordu.
    """

    # --- Gece: havuza döndür (ama taze turu değil) ---
    yas = _tur_yasi_dakika(haberler[0])
    taze = yas is not None and yas < TAZE_TUR_DAKIKA
    if taze:
        log.info("tur %.0f dakikalık, kapatılmıyor", yas)

    cok_bekledi = yas is not None and yas >= AZAMI_BEKLEME_SAAT * 60
    if cok_bekledi:
        log.info("tur %.1f saattir onaysız, havuza dönüyor", yas / 60)

    if (simdi.hour >= HAVUZA_DON_SAATI_UTC or cok_bekledi) and not taze:
        # ⚠️ METNİ OLAN HABER 'metin_hazir'E DÖNER, 'yeni'YE DEĞİL.
        # 'yeni' yapılırsa sonraki tur o haberi Gemini'ye TEKRAR
        # gönderiyor ve zaten üretilmiş metin için ikinci kez kota
        # harcanıyor. 20 Ağu 2026'da 10 haberlik tur kapanırken tam
        # bu oldu — hepsi 'yeni' yazıldı.
        # `son_dakika.suresi_gecmisi_iptal_et` bunu baştan doğru
        # yapıyordu; kural iki yerde yaşıyor ve biri unutulmuştu
        # (CLAUDE.md 1f/1j'deki desenin aynısı).
        con.execute(
            "UPDATE haberler SET telegram_message_id = NULL, "
            "durum = CASE WHEN ig_baslik IS NOT NULL THEN 'metin_hazir' "
            "             ELSE 'yeni' END "
            "WHERE telegram_message_id = ?",
            (mesaj_id,),
        )
        con.commit()
        try:
            # ⚠️ bildir=True ŞART. `editMessageText` Telegram'da
            # BİLDİRİM ÜRETMİYOR; onay mesajı sohbette yukarıda kaldığı
            # için kullanıcı turun kapandığını hiç görmüyor ve ertesi
            # gün "tur neden yayınlanmadı" diye soruyor (20 Ağu 2026).
            telegram_bot.sonucu_yaz(
                mesaj_id,
                f"🌙 Onay gelmedi, tur kapandı.\n"
                f"{len(haberler)} haber havuza döndü — elenmediler, "
                f"yarınki turda yeniden yarışacaklar.",
                bildir=True,
            )
        except Exception as e:
            # Mesaj düzenlenemese bile veritabanı doğru; tur kapanmış olmalı
            log.warning("sonuç mesajı yazılamadı: %s", e)
        log.info("%s haber havuza döndürüldü", len(haberler))
        return

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
