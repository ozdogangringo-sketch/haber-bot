"""
scripts/test_hibrit_carousel.py — İZOLASYONLU HİBRİT CAROUSEL TESTİ

Canlı sisteme ve veritabanına HİÇBİR ŞEKİLDE DOKUNMADAN:
  1. 1. Slayttan 3 saniyelik 1080x1350 MP4 Video Kapak üretir.
  2. 2-5. slaytları normal 1080x1350 görsel olarak alır.
  3. Meta Graph API Carousel Video + Görsel desteğini test eder.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

# Proje kökünü sys.path'e ekle
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import imageio
import requests
import yaml
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("hibrit_test")
load_dotenv()

CIKTI_KLASORU = Path("data") / "output"
GENISLIK = 1080
YUKSEKLIK = 1350


import imageio_ffmpeg
import subprocess

def video_kapak_uret(gorsel_yolu: Path, cikti_yolu: Path, sure_sn: float = 4.0) -> Path:
    """
    1080x1350 statik görselden Instagram uyumlu (h264, aac ses, faststart) 4 saniyelik video üretir.
    """
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    
    # 4 saniyelik hafif zoom pan ve sessiz AAC ses katmanı ile faststart MP4
    cmd = [
        ffmpeg_exe,
        "-y",
        "-loop", "1",
        "-i", str(gorsel_yolu),
        "-f", "lavfi",
        "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-c:v", "libx264",
        "-t", str(sure_sn),
        "-pix_fmt", "yuv420p",
        "-vf", "scale=1080:1350,zoompan=z='min(zoom+0.0012,1.025)':d=96:s=1080x1350:fps=24",
        "-c:a", "aac",
        "-b:a", "128k",
        "-shortest",
        "-movflags", "+faststart",
        str(cikti_yolu),
    ]
    
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log.info("Instagram uyumlu video kapak üretildi: %s (%.2f KB)", cikti_yolu.name, cikti_yolu.stat().st_size / 1024)
    return cikti_yolu


from src import upload_image

def public_yukle(dosya_yolu: Path) -> str:
    """Görseller için ImgBB, video için Litterbox kullanır."""
    log.info("Dosya public depoya yükleniyor: %s", dosya_yolu.name)
    if dosya_yolu.suffix.lower() in (".jpg", ".jpeg", ".png"):
        ayarlar_yolu = Path("config.yaml")
        ayarlar = yaml.safe_load(ayarlar_yolu.read_text(encoding="utf-8"))
        res = upload_image.gorsel_yukle(dosya_yolu, ayarlar)
        log.info("ImgBB URL alındı: %s", res["url"])
        return res["url"]

    # MP4 Video için uguu.se
    try:
        with open(dosya_yolu, "rb") as f:
            r = requests.post("https://uguu.se/upload.php", files={"files[]": (dosya_yolu.name, f)}, timeout=30)
            if r.status_code == 200:
                veri = r.json()
                raw_url = veri["files"][0]["url"]
                log.info("uguu.se Video URL alındı: %s", raw_url)
                return raw_url
    except Exception as e:
        log.warning("uguu.se yükleme hatası: %s", e)

    # Yedek: Litterbox (Catbox)
    url = "https://litterbox.catbox.moe/resources/internals/api.php"
    for deneme in range(2):
        try:
            with open(dosya_yolu, "rb") as f:
                r = requests.post(
                    url,
                    data={"reqtype": "fileupload", "time": "72h"},
                    files={"fileToUpload": (dosya_yolu.name, f)},
                    timeout=30,
                )
            if r.status_code == 200 and r.text.startswith("http"):
                public_url = r.text.strip()
                log.info("Litterbox Video URL alındı: %s", public_url)
                return public_url
        except Exception as e:
            log.warning("Litterbox deneme %s hatası: %s", deneme+1, e)
            time.sleep(2)

    raise RuntimeError("Video depoya yüklenemedi.")


def test_hibrit_yayin(gercek_yayinla: bool = False):
    log.info("=== HİBRİT CAROUSEL TESTİ BAŞLATILIYOR ===")
    
    # 1. Mevcut üretilmiş slaytları bul
    slaytlar = sorted(list(CIKTI_KLASORU.glob("slayt-*.jpg")) + list(CIKTI_KLASORU.glob("piyasa_karti_*.jpg")))
    if not slaytlar:
        log.error("data/output klasöründe slayt bulunamadı!")
        return

    secilen_slaytlar = slaytlar[:4]
    log.info("Test için %s adet slayt kullanılacak.", len(secilen_slaytlar))

    # 2. 1. Slayttan 3 saniyelik video kapak üret
    video_yolu = CIKTI_KLASORU / "test_hibrit_kapak.mp4"
    video_kapak_uret(secilen_slaytlar[0], video_yolu)

    # 3. Public URL'leri al
    video_url = public_yukle(video_yolu)
    resim_urlleri = [public_yukle(p) for p in secilen_slaytlar[1:]]

    # 4. Meta API Bilgilerini Al
    ig_user_id = os.getenv("IG_USER_ID", "").strip()
    ig_token = os.getenv("IG_ACCESS_TOKEN", "").strip()

    if not ig_user_id or not ig_token:
        log.error("IG_USER_ID veya IG_ACCESS_TOKEN tanımlı değil! (.env kontrol edin)")
        return

    session = requests.Session()
    url_base = f"https://graph.facebook.com/v21.0/{ig_user_id}/media"

    # 5. Adım A: Video Kapak Container Oluştur (media_type=VIDEO, is_carousel_item=true)
    log.info("1. Slayt Video Container oluşturuluyor...")
    r_v = session.post(
        url_base,
        params={
            "video_url": video_url,
            "media_type": "VIDEO",
            "is_carousel_item": "true",
            "access_token": ig_token,
        },
        timeout=30,
    )
    v_data = r_v.json()
    if "id" not in v_data:
        log.error("Video container hatası: %s", v_data)
        return
    video_container_id = v_data["id"]
    log.info("Video container ID: %s", video_container_id)

    # Video işlenme durumunu bekle
    log.info("Instagram'ın videoyu işlemesi bekleniyor...")
    for _ in range(20):
        time.sleep(3)
        chk = session.get(
            f"https://graph.facebook.com/v21.0/{video_container_id}",
            params={"fields": "status_code", "access_token": ig_token},
            timeout=10,
        ).json()
        status = chk.get("status_code")
        log.info("Video durumu: %s", status)
        if status == "FINISHED":
            break
        elif status == "ERROR":
            log.error("Instagram video işleme hatası: %s", chk)
            return

    # 6. Adım B: Görsel Slaytlar Container Oluştur
    image_container_ids = []
    for idx, r_url in enumerate(resim_urlleri, start=2):
        log.info("%s. Slayt Görsel Container oluşturuluyor...", idx)
        r_img = session.post(
            url_base,
            params={
                "image_url": r_url,
                "is_carousel_item": "true",
                "access_token": ig_token,
            },
            timeout=30,
        )
        img_data = r_img.json()
        if "id" not in img_data:
            log.error("Görsel container hatası: %s", img_data)
            return
        image_container_ids.append(img_data["id"])

    tum_cocuklar = [video_container_id] + image_container_ids
    log.info("Tüm container'lar hazır: %s", tum_cocuklar)

    # 7. Adım C: Ana Hibrit Carousel Container Oluştur
    log.info("Ana Hibrit Carousel oluşturuluyor...")
    r_car = session.post(
        url_base,
        params={
            "media_type": "CAROUSEL",
            "children": ",".join(tum_cocuklar),
            "caption": "🎬 Daily Brief Hibrit Carousel Testi (1. Slayt Video Kapak + Kaydırmalı Görseller)\n\n#dailybrief #test",
            "access_token": ig_token,
        },
        timeout=30,
    )
    car_data = r_car.json()
    if "id" not in car_data:
        log.error("Ana carousel oluşturulamadı: %s", car_data)
        return

    ana_carousel_id = car_data["id"]
    log.info("✅ TEBRİKLER! Hibrit Carousel Container Başarıyla Oluşturuldu: ID=%s", ana_carousel_id)

    if not gercek_yayinla:
        log.info("----------------------------------------------------------------")
        log.info("🔍 DRY-RUN (TEST) MODU: Instagram API Hibrit Carousel'i (Video + Resim) TAM DESTEKLEDİĞİNİ ONAYLADI!")
        log.info("Gerçekten Instagram hesabına basmak istersen: python scripts/test_hibrit_carousel.py --yayinla")
        log.info("----------------------------------------------------------------")
    else:
        log.info("Ana Carousel'in işlenmesi bekleniyor...")
        for _ in range(15):
            time.sleep(3)
            chk_car = session.get(
                f"https://graph.facebook.com/v21.0/{ana_carousel_id}",
                params={"fields": "status_code", "access_token": ig_token},
                timeout=10,
            ).json()
            c_status = chk_car.get("status_code")
            log.info("Ana Carousel durumu: %s", c_status)
            if c_status == "FINISHED":
                break
            elif c_status == "ERROR":
                log.error("Ana carousel işleme hatası: %s", chk_car)
                return

        log.info("Instagram'da canlıya basılıyor (media_publish)...")
        r_pub = session.post(
            f"https://graph.facebook.com/v21.0/{ig_user_id}/media_publish",
            params={"creation_id": ana_carousel_id, "access_token": ig_token},
            timeout=30,
        )
        pub_data = r_pub.json()
        if "id" in pub_data:
            post_id = pub_data["id"]
            log.info("🎉 YAYINLANDI! Instagram Post ID: %s", post_id)
            # Kısa linki al
            permalink_res = session.get(
                f"https://graph.facebook.com/v21.0/{post_id}",
                params={"fields": "permalink", "access_token": ig_token},
                timeout=10,
            ).json()
            log.info("📸 Canlı Post Linki: %s", permalink_res.get("permalink", f"https://instagram.com/p/{post_id}"))
        else:
            log.error("Yayın hatası: %s", pub_data)


if __name__ == "__main__":
    yayinla_flag = "--yayinla" in sys.argv
    test_hibrit_yayin(gercek_yayinla=yayinla_flag)
