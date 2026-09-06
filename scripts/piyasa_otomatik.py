"""
piyasa_otomatik.py — Hafta içi sabah (TR 10:08) ve akşam (TR 18:20) Borsa Açılış/Kapanış Bülteni.

Yapı:
  * 1. Slayt: Canlı BIST 100, Dolar, Euro, Gram Altın, Bitcoin, Brent Petrol Isı Haritası (src/piyasa_kart.py)
  * 2. Slayt: 30 Varlık BİST Hisseleri & Piyasa Tablosu (src/piyasa_tablo.py)

Paylaşım Kanalları (Tam Otomatik — Onay Sorulmaz):
  * Instagram Carousel (2 Slayt)
  * Instagram Story (2 Slayt)
  * Facebook Albüm + Story
  * Threads (2 Görsel)
  * X / Twitter (2 Görsel)
  * ⚠️ VİDEO YOKTUR: YouTube Shorts, TikTok ve Instagram Reels üretilmez/yayınlanmaz.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from PIL import Image

import yaml

# Kök klasörü sys.path'e ekle
KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

from src import (  # noqa: E402
    caption, db, facebook, instagram, make_image,
    piyasa, piyasa_kart, piyasa_tablo, telegram_bot,
    threads, twitter, upload_image, video, yonetim,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("piyasa_otomatik")


def main() -> int:
    parser = argparse.ArgumentParser(description="Piyasa Açılış/Kapanış Bülteni Otomatik Yayınlayıcı")
    parser.add_argument("--mod", choices=["acilis", "kapanis", "oto"], default="oto",
                        help="Yayın modu: acilis, kapanis veya saate göre oto")
    parser.add_argument("--kuru", action="store_true", help="Kuru çalışma (API'lere paylaşım yapmaz)")
    parser.add_argument("--zorla", action="store_true", help="Mükerrer kilidini atla, zorla yayınla")
    args = parser.parse_args()

    ayarlar_yolu = KOK / "config.yaml"
    with open(ayarlar_yolu, encoding="utf-8") as f:
        ayarlar = yaml.safe_load(f)

    con = db.baglan()

    # 1. Bot duraklatılmış mı kontrol et
    duraklatildi, kalan = yonetim.duraklatildi_mi(con)
    if duraklatildi:
        log.info("Bot duraklatılmış (kalan: %s), piyasa bülteni atlanıyor.", kalan)
        con.close()
        return 0

    # 2. Mod ve Saat Penceresi Denetimi
    tr_simdi = datetime.now(timezone.utc) + timedelta(hours=3)
    hafta_ici = tr_simdi.weekday() < 5
    tr_saat = tr_simdi.hour
    tr_dakika = tr_simdi.minute
    toplam_dakika = tr_saat * 60 + tr_dakika
    bugun_str = tr_simdi.date().isoformat()

    if not hafta_ici and not args.zorla:
        log.info("Hafta sonu — Piyasa Bülteni yayınlanmaz.")
        con.close()
        return 0

    # Saat Pencereleri (TR Saati):
    # Açılış: 09:55 - 11:30 (Borsa 10:00 açılışı sonrası)
    # Kapanış: 18:15 - 20:00 (Borsa 18:00 kapanışı sonrası)
    dakika_acilis_bas = 9 * 60 + 55    # 09:55
    dakika_acilis_bit = 11 * 60 + 30   # 11:30

    dakika_kapanis_bas = 18 * 60 + 15  # 18:15
    dakika_kapanis_bit = 20 * 60 + 0   # 20:00

    if args.mod == "oto":
        if dakika_acilis_bas <= toplam_dakika <= dakika_acilis_bit:
            mod = "acilis"
        elif dakika_kapanis_bas <= toplam_dakika <= dakika_kapanis_bit:
            mod = "kapanis"
        elif args.zorla:
            mod = "acilis" if toplam_dakika < 15 * 60 else "kapanis"
        else:
            log.warning(
                "Piyasa bülteni açılış/kapanış saat penceresi dışında (şu an %02d:%02d TR) — atlanıyor.",
                tr_saat, tr_dakika
            )
            con.close()
            return 0
    else:
        mod = args.mod
        # Mod açıkça belirtilmişse bile saat penceresi dışındaysa --zorla olmadan yayınlama!
        if mod == "acilis" and not (dakika_acilis_bas <= toplam_dakika <= dakika_acilis_bit) and not args.zorla:
            log.warning("Açılış bülteni saat penceresi dışında (şu an %02d:%02d TR, geçerli: 09:55-11:30) — atlandı.", tr_saat, tr_dakika)
            con.close()
            return 0
        if mod == "kapanis" and not (dakika_kapanis_bas <= toplam_dakika <= dakika_kapanis_bit) and not args.zorla:
            log.warning("Kapanış bülteni saat penceresi dışında (şu an %02d:%02d TR, geçerli: 18:15-20:00) — atlandı.", tr_saat, tr_dakika)
            con.close()
            return 0

    # 3. Mükerrer Bülten Kilidi (Günde 1 kez açılış, 1 kez kapanış)
    anahtar_bulten = f"piyasa_bulteni_{mod}_{bugun_str}"
    zaten_var = con.execute(
        "SELECT deger FROM ayarlar WHERE anahtar = ?", (anahtar_bulten,)
    ).fetchone()
    if zaten_var and not args.kuru and not args.zorla:
        log.info("Bugün %s bülteni zaten yayınlanmış (%s), mükerrer yayın engellendi.",
                 mod.upper(), bugun_str)
        con.close()
        return 0

    log.info("--- PİYASA BÜLTENİ OTOMATİK YAYIN (%s) BAŞLATILDI ---", mod.upper())

    # 4. Canlı piyasa verilerini çek
    piyasa_verileri = piyasa.piyasa_verileri_getir()

    # 5. %100 Native 1080x1920 (9:16 Full-bleed) Slaytları Üret (Sıfır Çerçeve, Sıfır Blur)
    kart_yolu = piyasa_kart.piyasa_karti_uret_9_16(piyasa_verileri)
    # ⚠️ CANLI VERİ YETERSİZSE BÜLTEN YAYINLANMIYOR (6 Eyl 2026).
    # Kullanıcı "BIST hisse dataları çekilememişti" diye bildirdi;
    # gerçekte tablo eksik veriyi KODA GÖMÜLÜ yüzdelerle dolduruyor ve
    # canlı veriymiş gibi yeşil/kırmızı basıyordu. Artık eksik hücre
    # "veri yok" diyor — ama bir sütun büyük ölçüde boşken bülteni hiç
    # yayınlamamak doğru: yarım piyasa karnesi, karne olmaktan çıkıyor.
    canli_fiyatlar = piyasa_tablo._tum_fiyatlari_cek()
    yeterli, sebep = piyasa_tablo.veri_yeterli_mi(canli_fiyatlar)
    if not yeterli and not args.zorla:
        log.warning("Piyasa bülteni atlandı — %s", sebep)
        telegram_bot.mesaj_gonder(
            f"⚠️ <b>Piyasa bülteni yayınlanmadı</b>\n{sebep}.\n\n"
            "Canlı veri alınamadığı için uydurma rakam basmak yerine "
            "atlandı — bir sonraki pencerede yeniden denenecek.",
            html=True,
        )
        con.close()
        return 0
    tablo_yolu = piyasa_tablo.piyasa_tablosu_uret_9_16(canli_fiyatlar)

    kart_yukleme = upload_image.gorsel_yukle(kart_yolu, ayarlar)
    tablo_yukleme = upload_image.gorsel_yukle(tablo_yolu, ayarlar)
    kart_url = kart_yukleme["url"]
    tablo_url = tablo_yukleme["url"]
    slayt_urlleri = [kart_url, tablo_url]

    kart_story_url = kart_url
    tablo_story_url = tablo_url

    # 6. Açıklama metinlerini oluştur
    ig_caption = caption.piyasa_bulteni_caption(piyasa_verileri, ayarlar, mod=mod)
    tw_metin = caption.piyasa_twitter_metni(piyasa_verileri, ayarlar, mod=mod)

    if args.kuru:
        log.info("Kuru çalışma tamamlandı.")
        log.info("Slaytlar: %s, %s", kart_url, tablo_url)
        log.info("Instagram Caption:\n%s", ig_caption)
        log.info("X Metni:\n%s", tw_metin)
        return 0

    # 7. Kanallara Yayını Başlat
    sonuclar = []
    canli_link_dugmeleri = []

    # a) Instagram Carousel & Story
    post_id = None
    baglanti = None
    try:
        post_id = instagram.carousel_yayinla(slayt_urlleri, ig_caption, ayarlar)
        baglanti = instagram.post_baglantisi(post_id, ayarlar)
        sonuclar.append("📸 Instagram Gönderisi paylaşıldı")
        if baglanti:
            canli_link_dugmeleri.append([{"text": "📸 Instagram'da Gör", "url": baglanti}])
    except Exception as e:
        log.exception("Instagram piyasa bülteni yayın hatası: %s", e)
        sonuclar.append(f"⚠️ Instagram hatası: {type(e).__name__}")

    # Story
    try:
        instagram.story_yayinla(kart_story_url, ayarlar)
        instagram.story_yayinla(tablo_story_url, ayarlar)
        sonuclar.append("📱 Instagram Story (2 slayt) paylaşıldı")
    except Exception as e:
        log.warning("Instagram story hatası: %s", e)
        sonuclar.append(f"⚠️ Instagram Story hatası: {type(e).__name__}")

    # b) Facebook Albüm & Story
    fb_aktif = bool((ayarlar.get("sosyal", {}) or {}).get("facebooka_da_at"))
    if fb_aktif:
        try:
            fb_id = facebook.albüm_yayinla(slayt_urlleri, ig_caption, ayarlar)
            fb_url = facebook.post_baglantisi(fb_id)
            sonuclar.append("📘 Facebook albümü paylaşıldı")
            if fb_url:
                canli_link_dugmeleri.append([{"text": "📘 Facebook'ta Gör", "url": fb_url}])
            try:
                facebook.story_yayinla(kart_story_url, ayarlar)
            except Exception:
                pass
        except Exception as e:
            log.warning("Facebook bülten hatası: %s", e)
            sonuclar.append(f"⚠️ Facebook hatası: {type(e).__name__}")

    # c) Threads
    th_aktif = bool((ayarlar.get("sosyal", {}) or {}).get("threadse_de_at"))
    if th_aktif:
        try:
            halkalar = [
                {
                    "metin": ig_caption[:490],
                    "gorsel_url": kart_url,
                    "tip": "gorsel",
                },
                {
                    "metin": "📌 30 Varlık BİST Hisseleri, ABD Teknoloji ve Kripto Tablosu",
                    "gorsel_url": tablo_url,
                    "tip": "gorsel",
                }
            ]
            th_id, _ = threads.zincir_yayinla(halkalar)
            th_url = threads.post_baglantisi(th_id)
            sonuclar.append("🧵 Threads postu paylaşıldı")
            if th_url:
                canli_link_dugmeleri.append([{"text": "🧵 Threads'te Gör", "url": th_url}])
        except Exception as e:
            log.warning("Threads bülten hatası: %s", e)
            sonuclar.append(f"⚠️ Threads hatası: {type(e).__name__}")

    # d) X (Twitter)
    tw_aktif = bool((ayarlar.get("sosyal", {}) or {}).get("twittera_da_at"))
    if tw_aktif:
        try:
            # 2 görseli yükle
            tw_medya_idler = []
            for y in [kart_yolu, tablo_yolu]:
                m_id = twitter.medya_yukle(y)
                if m_id:
                    tw_medya_idler.append(m_id)

            tw_id = twitter.tweet_olustur(tw_metin, medya_idler=tw_medya_idler if tw_medya_idler else None)
            tw_url = twitter.post_baglantisi(tw_id)
            sonuclar.append("🐦 X (Twitter) gönderisi paylaşıldı")
            if tw_url:
                canli_link_dugmeleri.append([{"text": "🐦 X'te Gör", "url": tw_url}])
        except Exception as e:
            log.warning("Twitter bülten hatası: %s", e)
            sonuclar.append(f"⚠️ X hatası: {type(e).__name__}")

    # 8. Telegram Grubuna Canlı Bilgi Mesajı İlet
    import html as html_lib
    baslik_etiket = "AÇILIŞ" if mod == "acilis" else "KAPANIŞ"
    rapor_metni = "\n".join(f"• {s}" for s in sonuclar)
    temiz_caption = html_lib.escape(ig_caption.strip())
    
    telegram_bot.mesaj_gonder(
        f"📊 <b>GÜNLÜK PİYASA {baslik_etiket} BÜLTENİ OTOMATİK YAYINLANDI</b>\n\n"
        f"{rapor_metni}\n\n"
        f"📝 <b>Açıklama Metni (Kopyalamak için dokunun):</b>\n"
        f"<pre>{temiz_caption}</pre>",
        html=True,
        butonlar=canli_link_dugmeleri if canli_link_dugmeleri else None,
    )

    if not args.kuru:
        con.execute(
            "INSERT INTO ayarlar (anahtar, deger) VALUES (?, ?) "
            "ON CONFLICT(anahtar) DO UPDATE SET deger = excluded.deger",
            (anahtar_bulten, datetime.now(timezone.utc).isoformat()),
        )
        con.commit()

    con.close()
    log.info("Piyasa bülteni otomatik yayını tamamlandı.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
