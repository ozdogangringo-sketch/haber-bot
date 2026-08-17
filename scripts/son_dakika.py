"""
son_dakika.py — Gün içinde önemli haber çıktıysa 2 slaytlık post hazırlar.

AKŞAM TURUNDAN FARKI:
    Akşam turu günün 10 haberini toplu veriyor. Bu script tek bir haberi,
    çıktığı anda veriyor. Format da farklı: 2 slayt — birincisi dikkat
    çeker (fotoğraf + başlık), ikincisi anlatır (sade zemin + detay).

KARARLAR (16 Ağu 2026, kullanıcıyla konuşuldu):
    * Eşik: onem_puani >= 8
    * Onay ŞART, ama 1 saat içinde onaylanmazsa kendiliğinden iptal.
      Bayat bir "son dakika" postu atmak, hiç atmamaktan kötü.
    * Günde en fazla 2 son dakika. Akşam turuyla birlikte günde 3 post —
      Instagram için sağlıklı aralık, takipçi yorulmuyor.

NEDEN ONAY KALDIRILMADI:
    Son dakika haberleri EN ÇOK düzeltilen haberlerdir; ilk dakikalarda
    sayılar ve isimler değişir. Doğrulama katmanımız "kaynakta ne yazıyorsa
    o" diyor ama kaynağın kendisi 20 dakika sonra güncelleniyor. Yani
    otomatik yayının en riskli olduğu yer tam burası.

ÇALIŞTIRMA:
    python scripts/son_dakika.py           (kontrol et, gerekiyorsa hazırla)
    python scripts/son_dakika.py --kuru    (Telegram'a GÖNDERME)
"""

import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import yaml                                       # noqa: E402

from src import (                                  # noqa: E402
    caption, db, dogrula, fetch_news, instagram, make_image, otomatik_onay,
    secim, slaytlar, telegram_bot, upload_image,
)
from src.generate_text import metinleri_uret       # noqa: E402

log = logging.getLogger("sondakika")

# Onaylanmayan son dakika turu kaç dakika sonra kendiliğinden düşsün.
OMUR_DAKIKA = 60

# Haber kaç saatten eskiyse artık "son dakika" sayılmaz.
TAZELIK_SAAT = 3

# TR saatiyle gece aralığı. UTC+3 sabit (yaz saati yok).
GECE_BASI_TR, GECE_SONU_TR = 23, 7


def _tr_saat() -> int:
    """Şu anki TR saati. Türkiye UTC+3, yaz saati uygulaması yok."""
    return (datetime.now(timezone.utc) + timedelta(hours=3)).hour


def gece_mi() -> bool:
    saat = _tr_saat()
    return saat >= GECE_BASI_TR or saat < GECE_SONU_TR


def gecerli_esik(ayarlar: dict) -> int:
    """
    Gece eşiği daha yüksek.

    Sebep: gece hazırlanan post sabaha kalıyor, yani onaylandığında
    5-8 saatlik bir haber oluyor. Bu gecikmeyi ancak gerçekten büyük
    bir olay hak ediyor — sıradan bir haber akşam turuna kalsın.
    """
    g = ayarlar["genel"]
    if gece_mi():
        return g.get("gece_puan_esigi", 9)
    return g.get("son_dakika_puan_esigi", 8)


def omru_bitti_mi(gonderim: str, ayarlar: dict) -> bool:
    """
    Bu tur düşürülmeli mi?

    Gündüz: 1 saat. Gece: sabah `gece_onay_biter_saat`e kadar bekler —
    gündüzki 1 saatlik ömür gece anlamsız, kimse uyanık değil.
    """
    try:
        t = datetime.fromisoformat(gonderim).replace(tzinfo=timezone.utc)
    except ValueError:
        return False

    simdi = datetime.now(timezone.utc)
    gonderim_tr = t + timedelta(hours=3)
    gece_hazirlanmis = (gonderim_tr.hour >= GECE_BASI_TR
                        or gonderim_tr.hour < GECE_SONU_TR)

    if not gece_hazirlanmis:
        return simdi - t > timedelta(minutes=OMUR_DAKIKA)

    # Gece hazırlanmış: sabah saatine kadar yaşasın
    bitis_saat = ayarlar["genel"].get("gece_onay_biter_saat", 8)
    simdi_tr = simdi + timedelta(hours=3)
    if simdi_tr.date() > gonderim_tr.date() or gonderim_tr.hour < GECE_SONU_TR:
        return simdi_tr.hour >= bitis_saat
    return False


def _bugun_anahtari() -> str:
    return "son_dakika_" + datetime.now(timezone.utc).strftime("%Y-%m-%d")


def bugunku_sayi(con) -> int:
    return int(db.ayar_oku(con, _bugun_anahtari(), 0) or 0)


def sayaci_artir(con) -> None:
    db.ayar_yaz(con, _bugun_anahtari(), bugunku_sayi(con) + 1)


def suresi_gecmisi_iptal_et(con, ayarlar: dict) -> None:
    """
    1 saati dolmuş, onaylanmamış son dakika turunu düşürür.

    Haber ELENMİYOR — havuza dönüyor ve akşam turunda yeniden yarışıyor.
    Sadece "son dakika" olarak yayınlanma hakkını kaybediyor.
    """
    bekleyen = list(con.execute(
        "SELECT DISTINCT telegram_message_id, gonderim_zamani FROM haberler "
        "WHERE son_dakika = 1 AND durum = 'onay_bekliyor' "
        "AND gonderim_zamani IS NOT NULL"
    ))

    for satir in bekleyen:
        if not omru_bitti_mi(satir["gonderim_zamani"], ayarlar):
            continue
        mesaj_id = satir["telegram_message_id"]
        con.execute(
            "UPDATE haberler SET durum = 'yeni', son_dakika = 0, "
            "telegram_message_id = NULL WHERE telegram_message_id = ?",
            (mesaj_id,),
        )
        con.commit()
        try:
            telegram_bot.sonucu_yaz(
                mesaj_id,
                "⌛️ Son dakika postu onaylanmadı, iptal edildi.\n"
                "Haber elenmedi — akşam turunda yeniden değerlendirilecek.",
            )
        except Exception as e:
            log.warning("iptal mesajı yazılamadı: %s", e)
        log.info("süresi geçen son dakika turu iptal edildi (%s)", mesaj_id)


def aday_bul(con, ayarlar: dict):
    """
    Son dakika adayı: yüksek puanlı, taze ve henüz yayınlanmamış haber.

    Yalnızca metni ZATEN hazır olanlara bakıyoruz. Her saat başı havuza
    metin ürettirmek kotayı yakar; akşam turu zaten adaylara metin
    üretiyor, buradaki iş onların arasından fırlayanı seçmek.
    """
    esik = gecerli_esik(ayarlar)
    sinir = (datetime.now(timezone.utc)
             - timedelta(hours=TAZELIK_SAAT)).isoformat()

    adaylar = [
        h for h in con.execute(
            "SELECT * FROM haberler WHERE durum = 'metin_hazir' "
            "AND ig_baslik IS NOT NULL AND onem_puani >= ? "
            "AND (son_dakika IS NULL OR son_dakika = 0) "
            "ORDER BY onem_puani DESC, yayin_tarihi DESC",
            (esik,),
        )
        if (h["yayin_tarihi"] or "") >= sinir
    ]
    return adaylar[0] if adaylar else None


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    kuru = "--kuru" in sys.argv
    ayarlar = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    db.kur()
    con = db.baglan()

    try:
        # --- 1) Süresi geçmiş turu düşür ---
        suresi_gecmisi_iptal_et(con, ayarlar)

        # --- 2) Zaten onay bekleyen son dakika varsa yenisini kurma ---
        acik = con.execute(
            "SELECT COUNT(*) FROM haberler WHERE son_dakika = 1 "
            "AND durum = 'onay_bekliyor'"
        ).fetchone()[0]
        if acik:
            log.info("onay bekleyen son dakika turu var, yeni tur kurulmadı")
            return 0

        # --- 3) Günlük sınır ---
        azami = ayarlar["genel"].get("son_dakika_gunluk_azami", 2)
        if bugunku_sayi(con) >= azami:
            log.info("günlük son dakika sınırı dolu (%s)", azami)
            return 0

        # --- 4) Taze haber çek, sonra aday ara ---
        rapor = fetch_news.haberleri_cek(ayarlar)
        log.info("RSS: %s yeni haber", rapor["eklenen"])

        aday = aday_bul(con, ayarlar)
        if not aday:
            # Metni hazır aday yoksa, yüksek puanlı olabilecek TAZE
            # haberlere metin ürettirip bir daha bak. Sadece birkaç tane —
            # her saat başı havuza metin üretmek kotayı yakar.
            yeniler = secim.on_eleme(con, ayarlar, kac=5)
            if yeniler:
                metinleri_uret(ayarlar=ayarlar, haberler=yeniler)
                aday = aday_bul(con, ayarlar)

        if not aday:
            log.info("son dakika seviyesinde haber yok")
            return 0

        log.info("aday: [%s] %s", aday["onem_puani"], aday["ig_baslik"])

        katman_raporu: list[str] = []

        # --- 5) İki slaytı üret ---
        sonuclar = slaytlar.son_dakika_uret(aday, ayarlar, con)
        taze = con.execute("SELECT * FROM haberler WHERE id = ?",
                           (aday["id"],)).fetchone()

        # Story carousel'e girmiyor, ayrı yükleniyor.
        carousel = [s for s in sonuclar if s["katman"] != "story"]
        story_slayt = next((s for s in sonuclar if s["katman"] == "story"), None)

        yuklemeler = upload_image.hepsini_yukle(
            [s["yol"] for s in carousel], ayarlar
        )
        urller = [y["url"] for y in yuklemeler]

        story_url = None
        if story_slayt:
            try:
                story_url = upload_image.gorsel_yukle(
                    story_slayt["yol"], ayarlar
                )["url"]
            except Exception as e:
                log.warning("story yüklenemedi: %s", e)

        metin = caption.son_dakika_caption(taze, sonuclar, ayarlar)
        uyari, isaretli = dogrula.turu_dogrula([taze])

        if kuru:
            print("\n" + "=" * 70)
            print("KURU ÇALIŞMA — Telegram'a gönderilmedi")
            print("=" * 70)
            print(metin)
            print("=" * 70)
            for s in sonuclar:
                print(f"  [{s['katman']:<8}] {s['yol']}")
            return 0

        # --- 6a) GECE: dört katmanlı denetimden geçerse otomatik yayınla ---
        #
        # Gece kimse uyanık değil; büyük bir olayda hesabın sabaha kadar
        # sessiz kalması kötü. Ama insan onayını kaldırmak doğruluk
        # güvencesini kaldırıyor, o yüzden yerine dört katman kondu.
        # ŞÜPHEDE REDDET: biri bile tereddüt ederse sabaha bırakılıyor.
        if gece_mi() and ayarlar["genel"].get("gece_otomatik_yayin", False):
            uygun, katman_raporu = otomatik_onay.otomatik_yayinlanabilir(
                con, taze, ayarlar
            )
            for satir in katman_raporu:
                log.info("  %s", satir)

            if uygun:
                post_id = instagram.carousel_yayinla(urller, metin, ayarlar)
                baglanti = instagram.post_baglantisi(post_id, ayarlar)
                if story_url:
                    try:
                        instagram.story_yayinla(story_url, ayarlar)
                    except Exception as e:
                        log.warning("story yayınlanamadı: %s", e)

                con.execute(
                    "UPDATE haberler SET durum = 'yayinlandi', son_dakika = 1, "
                    "ig_post_id = ?, gorsel_url = ?, detay_url = ?, story_url = ?, "
                    "gonderim_zamani = datetime('now') WHERE id = ?",
                    (post_id, urller[0], urller[1] if len(urller) > 1 else None,
                     story_url, aday["id"]),
                )
                con.commit()
                sayaci_artir(con)

                # Sabah görmek için: ne yayınlandı, hangi denetimlerden
                # geçti. Beğenilmezse Instagram'dan silinebilir.
                telegram_bot.slaytlari_gonder(urller, ["Haber", "Ayrıntı"])
                telegram_bot.mesaj_gonder(
                    "🌙 GECE OTOMATİK YAYINLANDI\n"
                    f"{taze['ig_baslik']}\n\n"
                    + "\n".join(katman_raporu)
                    + f"\n\n{baglanti or post_id}\n\n"
                    "Uygun bulmazsan Instagram'dan silebilirsin."
                )
                log.info("gece otomatik yayınlandı: %s", post_id)
                return 0

            log.info("otomatik yayın reddedildi, sabaha bırakılıyor")

        # --- 6b) Onaya sun ---
        telegram_bot.slaytlari_gonder(urller, ["Haber", "Ayrıntı"])
        mesaj_id = telegram_bot.onay_iste(
            metin, len(urller),
            uyari=(uyari or ""),
            ozet=(f"🔴 SON DAKİKA ÖNERİSİ  ·  puan {taze['onem_puani']}/10\n"
                  + ("🌙 Gece: sabah 08:00'e kadar bekler\n"
                     if gece_mi() else
                     f"⌛️ {OMUR_DAKIKA} dakika içinde onaylanmazsa iptal olur\n")
                  + ("\n".join(katman_raporu) if gece_mi() and katman_raporu
                     else "")),
        )

        con.execute(
            "UPDATE haberler SET durum = 'onay_bekliyor', son_dakika = 1, "
            "telegram_message_id = ?, gorsel_url = ?, detay_url = ?, "
            "story_url = ?, gonderim_zamani = datetime('now') WHERE id = ?",
            (mesaj_id, urller[0], urller[1] if len(urller) > 1 else None,
             story_url, aday["id"]),
        )
        con.commit()
        sayaci_artir(con)

        log.info("son dakika onaya sunuldu (message_id=%s)", mesaj_id)
        return 0

    except Exception as e:
        log.exception("son dakika turu hazırlanamadı")
        if not kuru:
            telegram_bot.hata_bildir(
                "Son dakika turu hazırlanamadı", f"{type(e).__name__}: {e}"
            )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
