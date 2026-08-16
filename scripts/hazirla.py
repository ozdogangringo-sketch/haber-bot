"""
hazirla.py — Bir turu baştan sona hazırlar ve onaya sunar.

AKIŞ:
    RSS çek → ön eleme → adaylara metin üret → skorla seç
    → slaytları üret → imgbb'ye yükle → caption kur
    → Telegram'a onay mesajı gönder

Bu script YAYINLAMAZ. Yalnızca hazırlar ve gruba sorar. Yayın,
Telegram'daki butona basılınca `onay_isle.py` üzerinden oluyor.

ÇALIŞTIRMA:
    python scripts/hazirla.py            (normal tur)
    python scripts/hazirla.py --kuru     (Telegram'a GÖNDERMEZ, sadece üretir)

`--kuru` neden var: akışı gruba mesaj düşürmeden denemek için. Görseller
üretilir, maliyet yine sıfırdır, ama kimse rahatsız olmaz.

HATA POLİTİKASI:
    Herhangi bir adım patlarsa Telegram'a hata mesajı gidiyor. Gözetimsiz
    çalışan bir botta sessiz başarısızlık en kötü senaryo — post gelmediğini
    ertesi gün fark etmektense hatayı anında görmek gerekiyor.
"""

import logging
import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import yaml                                       # noqa: E402

from src import (                                  # noqa: E402
    caption, db, dogrula, fetch_news, make_image, secim, slaytlar,
    telegram_bot, upload_image,
)
from src.generate_text import metinleri_uret       # noqa: E402

log = logging.getLogger("hazirla")


def kur_gunluk():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Kütüphanelerin gürültüsü rapora karışmasın
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def main() -> int:
    kur_gunluk()
    kuru = "--kuru" in sys.argv
    metinsiz = "--metinsiz" in sys.argv

    ayarlar = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    db.kur()
    con = db.baglan()

    try:
        # --- 1) Yeni haberleri çek ---
        # `haberleri_cek` kendi bağlantısını açıyor ve rapor sözlüğü dönüyor.
        rapor = fetch_news.haberleri_cek(ayarlar)
        log.info("RSS: %s yeni, %s tekrar, %s bayat",
                 rapor["eklenen"], rapor["tekrar"], rapor["eski"])

        # --- 2) Ön eleme (bedava) + metin üretimi ---
        # Havuzun tamamına metin üretmek kotayı ve süreyi katlıyor;
        # önce ucuz sinyallerle aday sayısını indiriyoruz.
        #
        # `--metinsiz`: Gemini'ye hiç gitmeden, metni ZATEN hazır olan
        # haberlerle tur kurar. Ücretsiz kota dolduğunda (429) turu
        # tamamen kaçırmak yerine elimizdekiyle devam etmek için.
        if metinsiz:
            log.info("--metinsiz: metin üretimi atlandı")
        else:
            adaylar = secim.on_eleme(con, ayarlar)
            if adaylar:
                metinleri_uret(ayarlar=ayarlar, haberler=adaylar)

        # --- 3) Gerçek skorla seçim ---
        secilen = secim.tur_icin_sec(con, ayarlar)
        if len(secilen) < 2:
            # Instagram carousel en az 2 görsel istiyor.
            mesaj = f"Yayınlanacak yeterli haber yok ({len(secilen)} adet)."
            log.warning(mesaj)
            if not kuru:
                telegram_bot.mesaj_gonder(f"ℹ️ {mesaj} Bu tur atlandı.")
            return 0

        # --- 4) Slaytlar (Commons → Pexels → gradyan, hepsi bedava) ---
        sonuclar = slaytlar.tur_uret(secilen, ayarlar, con)
        if len(sonuclar) < 2:
            raise RuntimeError(
                f"yalnızca {len(sonuclar)} slayt üretilebildi, carousel için az"
            )

        # Slaytı üretilemeyen haber varsa listeden düşsün; caption'daki
        # numaralar slaytlarla birebir eşleşmek zorunda.
        uretilen_idler = {s["id"] for s in sonuclar}
        secilen = [h for h in secilen if h["id"] in uretilen_idler]

        # --- 5) imgbb'ye yükle ---
        yollar = [s["yol"] for s in sonuclar]
        yuklemeler = upload_image.hepsini_yukle(yollar, ayarlar)
        for haber, yukleme in zip(secilen, yuklemeler):
            con.execute(
                "UPDATE haberler SET gorsel_url = ? WHERE id = ?",
                (yukleme["url"], haber["id"]),
            )
        con.commit()

        # --- 5b) Story görseli ---
        # Şimdi üretiliyor ki yayın anında beklemeyelim; onay ile yayın
        # arasında saatler geçebiliyor ve o an hız önemli.
        story_url = None
        try:
            story_gorsel = make_image.story_kapak(
                [h["ig_baslik"] or h["baslik_orj"] for h in secilen], ayarlar
            )
            story_yol = make_image.CIKTI_KLASORU / "story-kapak.jpg"
            story_gorsel.save(story_yol, "JPEG",
                              quality=ayarlar["gorsel"]["jpeg_kalite"])
            story_url = upload_image.gorsel_yukle(story_yol, ayarlar)["url"]
            log.info("story görseli hazır")
        except Exception as e:
            # Story ikincil; patlarsa post yine çıkmalı.
            log.warning("story görseli üretilemedi: %s", e)

        # --- 6) Caption ---
        metin = caption.caption_kur(secilen, sonuclar, ayarlar=ayarlar)
        log.info("caption: %s karakter", len(metin))

        if kuru:
            print("\n" + "=" * 70)
            print("KURU ÇALIŞMA — Telegram'a gönderilmedi")
            print("=" * 70)
            print(metin)
            print("=" * 70)
            for s in sonuclar:
                print(f"  [{s['katman']:<8}] {s['yol']}")
            return 0

        # --- 7) Doğruluk denetimi + onaya sun ---
        # Uydurma metin akıcı ve inandırıcı göründüğü için insan onayı tek
        # başına yetmiyor. Bu süzgeç "kaynakta karşılığı olmayan sayı/isim"
        # arayıp onay mesajının başına uyarı koyuyor — kullanıcı neye
        # bakacağını onaylamadan ÖNCE görsün.
        uyari, isaretli = dogrula.turu_dogrula(secilen)
        if isaretli:
            log.warning("%s slayt doğrulama uyarısı aldı", isaretli)

        # Slaytlar en güncel hâliyle okunuyor: tur_uret sırasında
        # gorsel_kaynagi yazıldı, özet tablosu onu gösterecek.
        taze = list(con.execute(
            "SELECT * FROM haberler WHERE telegram_message_id IS NULL "
            "AND id IN ({})".format(",".join(str(h["id"]) for h in secilen))
        ))
        sira_ile = {h["id"]: h for h in taze}
        secilen = [sira_ile.get(h["id"], h) for h in secilen]

        urller = [y["url"] for y in yuklemeler]
        telegram_bot.slaytlari_gonder(
            urller, [h["ig_baslik"] or h["baslik_orj"] for h in secilen]
        )
        ozet = telegram_bot.tur_ozeti(secilen, isaretli)
        mesaj_id = telegram_bot.onay_iste(
            metin, len(urller), uyari=uyari, ozet=ozet
        )

        for haber in secilen:
            con.execute(
                "UPDATE haberler SET durum = 'onay_bekliyor', "
                "telegram_message_id = ?, gonderim_zamani = datetime('now'), "
                "story_url = ? WHERE id = ?",
                (mesaj_id, story_url if haber is secilen[0] else None,
                 haber["id"]),
            )
        con.commit()
        log.info("onay bekleniyor (message_id=%s)", mesaj_id)
        return 0

    except Exception as e:
        log.exception("tur hazırlanamadı")
        if not kuru:
            telegram_bot.hata_bildir(
                "Tur hazırlanamadı", f"{type(e).__name__}: {e}"
            )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
