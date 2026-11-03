#!/usr/bin/env python3
"""
scripts/paylas_29_ekim.py — 29 Ekim Özel Afiş Yayını (Afiş 1 - CUMHURİYET)
Görsel (4:5 Feed) ve Story (9:16) olarak Instagram, Facebook, Threads, X ve Telegram'a yayınlar.
"""

import os
import sys
import json
import logging
from pathlib import Path
import requests
from dotenv import load_dotenv

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("paylas_29_ekim")

def ayarları_yukle() -> dict:
    config_path = KOK / "config.yaml"
    try:
        import yaml
        return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except ImportError:
        log.info("pyyaml bulunamadı, temel ayarlar kullanılıyor")
        return {
            "instagram": {"hesap_kullanici_adi": "dailybrief.co", "api_surumu": "v23.0", "hazir_bekleme_saniye": 5, "hazir_azami_deneme": 12, "zaman_asimi": 60},
            "sosyal": {"instagrama_at": True, "story_at": True, "threadse_at": True, "twittera_at": True, "facebooka_da_at": True}
        }

def main():
    ayarlar = ayarları_yukle()
    
    # 1. Dosya Yolları (Afiş 1: CUMHURİYET)
    story_path = KOK / "data/output/afis_29_ekim_1_cumhuriyet.jpg"
    feed_path = KOK / "data/output/afis_29_ekim_1_cumhuriyet_4_5.jpg"
    
    if not story_path.exists():
        story_path = Path("/Users/macbook/.gemini/antigravity/brain/4b51c693-ddbf-4a88-aba5-083b33bb6dd2/afis_29_ekim_1_cumhuriyet.jpg")
    if not feed_path.exists():
        feed_path = Path("/Users/macbook/.gemini/antigravity/brain/4b51c693-ddbf-4a88-aba5-083b33bb6dd2/afis_29_ekim_1_cumhuriyet_4_5.jpg")

    if not story_path.exists() or not feed_path.exists():
        log.error("Afiş 1 dosyaları bulunamadı! Lütfen önce afiş üretimini kontrol edin.")
        return 1

    log.info("Afiş 1 hazır:")
    log.info("  Story (9:16): %s (%d bytes)", story_path, story_path.stat().st_size)
    log.info("  Feed  (4:5) : %s (%d bytes)", feed_path, feed_path.stat().st_size)

    # 2. R2 Depolama Alanına Yükle
    from src import upload_image
    log.info("Görseller Cloudflare R2'ye yükleniyor...")
    
    res_story = upload_image.r2ye_yukle(story_path, alt_klasor="ozel_yayin")
    res_feed = upload_image.r2ye_yukle(feed_path, alt_klasor="ozel_yayin")
    
    story_url = res_story.get("url")
    feed_url = res_feed.get("url")
    
    log.info("R2 Story URL: %s", story_url)
    log.info("R2 Feed  URL: %s", feed_url)

    if not story_url or not feed_url:
        log.error("R2 yüklemesi başarısız oldu!")
        return 1

    # 3. Editoryal Açıklama Metinleri (Sıfır Markdown)
    caption_full = (
        "“Türkiye Cumhuriyeti ilelebet payidar kalacaktır.”\n"
        "— Gazi Mustafa Kemal Atatürk\n\n"
        "Egemenliğin kayıtsız ve şartsız millete ait olduğu, bağımsızlık ve hürriyet meşalesinin sonsuza dek yanacağı Cumhuriyetimizin 103. yılı kutlu olsun.\n\n"
        "Büyük Önderimiz Gazi Mustafa Kemal Atatürk ve silah arkadaşlarını, bağımsızlığımız uğruna can veren tüm kahramanlarımızı saygı, minnet ve sonsuz rahmetle anıyoruz.\n\n"
        "29 Ekim Cumhuriyet Bayramımız kutlu olsun! 🇹🇷\n\n"
        "#29Ekim #CumhuriyetBayramı #Atatürk #Cumhuriyet103Yaşında #TürkiyeCumhuriyeti #DailyBrief"
    )

    caption_twitter = (
        "“Türkiye Cumhuriyeti ilelebet payidar kalacaktır.”\n"
        "— Gazi Mustafa Kemal Atatürk\n\n"
        "Cumhuriyetimizin 103. yılı kutlu olsun! 🇹🇷\n\n"
        "Büyük Önderimiz Gazi Mustafa Kemal Atatürk ve tüm kahramanlarımızı saygı, minnet ve rahmetle anıyoruz.\n\n"
        "#29Ekim #CumhuriyetBayramı #Atatürk"
    )

    sonuclar = {}

    # 4. INSTAGRAM YAYINI (Feed Post & Story)
    from src import instagram
    
    # 4A. Instagram Feed (4:5 Tekil Gönderi)
    try:
        log.info("Instagram Feed paylaşılıyor (4:5)...")
        ig_post_id = instagram.tekli_post_yayinla(feed_url, caption_full, ayarlar)
        ig_link = instagram.post_baglantisi(ig_post_id, ayarlar)
        sonuclar["instagram_feed"] = {"durum": "BAŞARILI", "id": ig_post_id, "url": ig_link}
        log.info("✅ Instagram Feed Post paylaşıldı: %s (%s)", ig_post_id, ig_link)
    except Exception as e:
        log.exception("Instagram Feed hatası: %s", e)
        sonuclar["instagram_feed"] = {"durum": "HATA", "hata": str(e)}

    # 4B. Instagram Story (9:16)
    try:
        log.info("Instagram Story paylaşılıyor (9:16)...")
        ig_story_id = instagram.story_yayinla(story_url, ayarlar)
        sonuclar["instagram_story"] = {"durum": "BAŞARILI", "id": ig_story_id}
        log.info("✅ Instagram Story paylaşıldı: %s", ig_story_id)
    except Exception as e:
        log.exception("Instagram Story hatası: %s", e)
        sonuclar["instagram_story"] = {"durum": "HATA", "hata": str(e)}

    # 5. THREADS YAYINI (4:5)
    from src import threads
    try:
        log.info("Threads paylaşılıyor (4:5)...")
        th_id = threads.yayinla([feed_url], caption_full)
        th_link = threads.post_baglantisi(th_id)
        sonuclar["threads"] = {"durum": "BAŞARILI", "id": th_id, "url": th_link}
        log.info("✅ Threads paylaşıldı: %s (%s)", th_id, th_link)
    except Exception as e:
        log.exception("Threads hatası: %s", e)
        sonuclar["threads"] = {"durum": "HATA", "hata": str(e)}

    # 6. TWITTER / X YAYINI (4:5)
    from src import twitter
    try:
        log.info("Twitter (X) paylaşılıyor (4:5)...")
        if twitter.kullanilabilir_mi():
            mid = twitter.medya_yukle(feed_path)
            tw_res = twitter.tweet_olustur(caption_twitter, medya_idler=[mid] if mid else None)
            if tw_res and tw_res.get("id"):
                tw_id = tw_res["id"]
                tw_link = twitter.post_baglantisi(tw_id)
                sonuclar["twitter"] = {"durum": "BAŞARILI", "id": tw_id, "url": tw_link}
                log.info("✅ Twitter (X) paylaşıldı: %s (%s)", tw_id, tw_link)
            else:
                sonuclar["twitter"] = {"durum": "HATA", "hata": "Tweet oluşturulamadı"}
        else:
            log.warning("Twitter anahtarları eksik")
            sonuclar["twitter"] = {"durum": "ATLANDI", "sebep": "Anahtar yok"}
    except Exception as e:
        log.exception("Twitter hatası: %s", e)
        sonuclar["twitter"] = {"durum": "HATA", "hata": str(e)}

    # 7. FACEBOOK YAYINI (Feed Post & Story)
    from src import facebook
    try:
        log.info("Facebook Feed paylaşılıyor (4:5)...")
        fb_id = facebook.albüm_yayinla([feed_url], caption_full, ayarlar)
        fb_link = facebook.post_baglantisi(fb_id)
        sonuclar["facebook_feed"] = {"durum": "BAŞARILI", "id": fb_id, "url": fb_link}
        log.info("✅ Facebook Feed paylaşıldı: %s (%s)", fb_id, fb_link)
        
        # Facebook Story
        try:
            fb_story_id = facebook.story_yayinla(story_url, ayarlar)
            sonuclar["facebook_story"] = {"durum": "BAŞARILI", "id": fb_story_id}
            log.info("✅ Facebook Story paylaşıldı: %s", fb_story_id)
        except Exception as e_fb_st:
            log.warning("Facebook Story paylaşımı başarısız: %s", e_fb_st)
            sonuclar["facebook_story"] = {"durum": "HATA", "hata": str(e_fb_st)}
    except Exception as e:
        log.exception("Facebook hatası: %s", e)
        sonuclar["facebook_feed"] = {"durum": "HATA", "hata": str(e)}

    # 8. TELEGRAM DUYURUSU (Gruba / Kanala Görsel ve Metin)
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
    tg_chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if tg_token and tg_chat_id:
        try:
            log.info("Telegram grubuna yayınlanıyor...")
            tg_url = f"https://api.telegram.org/bot{tg_token}/sendPhoto"
            with open(story_path, "rb") as photo_file:
                resp = requests.post(
                    tg_url,
                    data={
                        "chat_id": tg_chat_id,
                        "caption": f"🇹🇷 <b>29 EKİM CUMHURİYET BAYRAMI ÖZEL YAYINI</b>\n\n{caption_full}",
                        "parse_mode": "HTML"
                    },
                    files={"photo": photo_file},
                    timeout=30
                )
            if resp.status_code == 200:
                sonuclar["telegram"] = {"durum": "BAŞARILI"}
                log.info("✅ Telegram paylaşımı başarılı")
            else:
                sonuclar["telegram"] = {"durum": "HATA", "kod": resp.status_code, "cevap": resp.text[:200]}
        except Exception as e_tg:
            log.exception("Telegram hatası: %s", e_tg)
            sonuclar["telegram"] = {"durum": "HATA", "hata": str(e_tg)}

    print("\n" + "="*50)
    print("YAYIN SONUÇ RAPORU:")
    print("="*50)
    print(json.dumps(sonuclar, indent=2, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    sys.exit(main())
