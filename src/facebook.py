"""
facebook.py — Aynı içeriği Facebook sayfasına da paylaşır.

NEDEN AYRI MODÜL AMA AYNI JETON:
    Instagram ile Facebook aynı Meta altyapısında; sayfa jetonumuz
    ikisini de kapsıyor. Ayrı anahtar, ayrı yenileme döngüsü yok —
    `pages_manage_posts` izni eklendi, o kadar.

CAROUSEL KARŞILIĞI — ALBÜM:
    Facebook'ta carousel yok, albüm var. Akış iki aşamalı:
      1. Her görsel `published=false` ile yükleniyor -> photo_id
      2. `/feed` çağrısında attached_media ile hepsi tek posta bağlanıyor
    Tek görselde albüme gerek yok, doğrudan /photos yeterli.

İKİNCİL KANAL:
    Facebook paylaşımı patlarsa Instagram postu YAYINDA KALIYOR.
    Hata yutuluyor ve Telegram sonucuna not düşülüyor — ikincil bir
    kanal yüzünden asıl yayını riske atmıyoruz.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import time

import requests
from dotenv import load_dotenv

from . import filtre

log = logging.getLogger(__name__)
load_dotenv()

TABAN = "https://graph.facebook.com"
GECICI_HATALAR = {429, 500, 502, 503, 504}


def _jeton() -> str:
    j = os.getenv("IG_ACCESS_TOKEN", "").strip()
    if not j:
        raise RuntimeError("IG_ACCESS_TOKEN bulunamadı (.env)")
    return j


def _istek(yontem: str, yol: str, ayarlar: dict, **parametreler) -> dict:
    g = ayarlar["instagram"]
    url = f"{TABAN}/{g['api_surumu']}{yol}"
    parametreler["access_token"] = _jeton()

    son_hata = None
    for deneme in range(1, 4):
        try:
            if yontem.upper() == "GET":
                cevap = requests.get(url, params=parametreler,
                                     timeout=g["zaman_asimi"])
            elif yontem.upper() == "DELETE":
                # Silme isteği query string ile gidiyor; gövdeye konursa
                # Graph API jetonu hiç görmüyor.
                cevap = requests.delete(url, params=parametreler,
                                        timeout=g["zaman_asimi"])
            else:
                cevap = requests.post(url, data=parametreler,
                                      timeout=g["zaman_asimi"])
        except requests.RequestException as e:
            son_hata = f"{type(e).__name__}: {e}"
            time.sleep(2 * deneme)
            continue

        if cevap.status_code == 200:
            return cevap.json()

        son_hata = f"HTTP {cevap.status_code}: {cevap.text[:300]}"
        alt_kod = None
        is_transient = False
        try:
            hata_obj = cevap.json().get("error", {})
            alt_kod = hata_obj.get("error_subcode")
            is_transient = bool(hata_obj.get("is_transient"))
        except Exception:
            pass

        if cevap.status_code in GECICI_HATALAR or is_transient or alt_kod in (2069019, 2207003, 2207052):
            time.sleep(5 * deneme)
            continue
        break

    raise RuntimeError(f"Facebook API hatası ({yol}): {son_hata}")


def sayfa_bilgisi(ayarlar: dict) -> dict:
    """Jetonun hangi sayfaya ait olduğunu döner."""
    return _istek("GET", "/me", ayarlar, fields="id,name,category")


def albüm_yayinla(gorsel_urlleri: list[str], metin: str,
                  ayarlar: dict) -> str:
    """
    Görselleri tek bir Facebook postu olarak paylaşır. Post id'sini döner.

    Tek görselde /photos, çoklu görselde albüm akışı kullanılıyor.
    """
    if not gorsel_urlleri:
        raise ValueError("paylaşılacak görsel yok")

    sayfa = sayfa_bilgisi(ayarlar)
    temiz_metin = filtre.markdown_temizle(metin)

    # --- Tek görsel: albüme gerek yok ---
    if len(gorsel_urlleri) == 1:
        d = _istek("POST", "/me/photos", ayarlar,
                   url=gorsel_urlleri[0], caption=temiz_metin)
        log.info("Facebook tek görsel yayınlandı (%s)", sayfa.get("name"))
        return d.get("post_id") or d["id"]

    # --- Çoklu görsel: önce yayınlanmamış yükle, sonra tek posta bağla ---
    fotograflar = []
    for i, url in enumerate(gorsel_urlleri, 1):
        d = _istek("POST", "/me/photos", ayarlar,
                   url=url, published="false")
        fotograflar.append(d["id"])
        log.info("Facebook görsel %d/%d yüklendi", i, len(gorsel_urlleri))

    ekler = {f"attached_media[{i}]": json.dumps({"media_fbid": fid})
             for i, fid in enumerate(fotograflar)}
    d = _istek("POST", "/me/feed", ayarlar, message=temiz_metin, **ekler)

    log.info("Facebook albümü yayınlandı (%s): %s",
             sayfa.get("name"), d.get("id"))
    return d["id"]


def story_yayinla(gorsel_url: str, ayarlar: dict) -> str:
    """
    Facebook sayfa story'si paylaşır.

    İKİ AŞAMA: Instagram'daki gibi doğrudan URL kabul etmiyor.
      1. Fotoğraf `published=false` ile yükleniyor -> photo_id
      2. `/photo_stories` çağrısında o id story'ye çevriliyor

    Instagram story'siyle aynı kısıtlar: sticker/link eklenemiyor,
    24 saat sonra kayboluyor, 9:16 bekleniyor. Bizim story görseli
    zaten 9:16 olduğu için ek üretim gerekmiyor — aynı dosya
    Instagram'a da Facebook'a da gidiyor.
    """
    d = _istek("POST", "/me/photos", ayarlar,
               url=gorsel_url, published="false")
    foto_id = d["id"]

    d = _istek("POST", "/me/photo_stories", ayarlar, photo_id=foto_id)
    story_id = d.get("post_id") or d.get("id") or foto_id
    log.info("Facebook story yayınlandı: %s", story_id)
    return story_id


def postu_sil(post_id: str, ayarlar: dict) -> bool:
    """
    Yayınlanmış Facebook postunu siler.

    `pages_manage_posts` izni bunu kapsıyor. Instagram'da karşılığı YOK:
    Graph API yayınlanmış Instagram postunu silmeye izin vermiyor, orada
    silme yalnızca uygulamadan yapılabiliyor.
    """
    try:
        _istek("DELETE", f"/{post_id}", ayarlar)
        log.info("Facebook postu silindi: %s", post_id)
        return True
    except Exception as e:
        log.warning("Facebook postu silinemedi (%s): %s", post_id, e)
        return False


def post_baglantisi(post_id: str) -> str:
    """Facebook post bağlantısı — Telegram sonucunda göstermek için."""
    return f"https://www.facebook.com/{post_id}"


def reels_baglantisi(video_id: str) -> str:
    """Facebook Reel doğrudan bağlantısı — Telegram sonucunda göstermek için."""
    return f"https://www.facebook.com/reel/{video_id}"


def reels_yayinla(
    video_yolu: Path | str,
    aciklama: str,
    ayarlar: dict,
) -> str:
    """
    Facebook Sayfasına 9:16 Reels videosu yükler ve yayınlar.
    Yayınlanan Reel video ID'sini döner.

    Üç Aşamalı Resumable Upload Akışı (Graph API v21.0+):
      1. Başlatma (upload_phase=start) -> video_id ve upload_url (rupload.facebook.com) alınır.
      2. İkili Yükleme -> rupload endpoint'ine Authorization, file_size ve offset header'ları ile video yüklenir.
      3. Yayını Tamamlama (upload_phase=finish) -> video_state='PUBLISHED' ve temiz editoryal açıklama ile yayınlanır.
    """
    video_p = Path(video_yolu)
    if not video_p.exists():
        raise FileNotFoundError(f"Reels videosu bulunamadı: {video_p}")

    # Müziksiz videolara hafif, telifsiz haber ambiyans fon müziğini miksle (zaten sesli değilse)
    if "_yt" not in video_p.name:
        try:
            from . import youtube
            video_p = youtube.youtube_icin_sesli_video_hazirla(video_p)
        except Exception as e:
            log.warning("Facebook Reels için fon müziği mikslenemedi, mevcut video ile devam: %s", e)

    sayfa = sayfa_bilgisi(ayarlar)
    sayfa_id = sayfa.get("id")
    if not sayfa_id:
        raise RuntimeError("Facebook sayfa ID'si alınamadı")

    jeton = _jeton()
    g = ayarlar.get("instagram", {})
    api_surumu = g.get("api_surumu", "v21.0")
    zaman_asimi = g.get("zaman_asimi", 30)
    temiz_metin = filtre.markdown_temizle(aciklama)

    # 1. Aşama: Oturumu başlat (upload_phase=start)
    init_url = f"{TABAN}/{api_surumu}/{sayfa_id}/video_reels"
    init_res = requests.post(
        init_url,
        data={
            "upload_phase": "start",
            "access_token": jeton,
        },
        timeout=zaman_asimi,
    )
    if init_res.status_code != 200:
        raise RuntimeError(f"Facebook Reels başlatma hatası: HTTP {init_res.status_code} - {init_res.text[:250]}")

    init_veri = init_res.json()
    video_id = init_veri.get("video_id") or init_veri.get("id")
    upload_url = init_veri.get("upload_url")
    if not video_id or not upload_url:
        raise RuntimeError(f"Facebook Reels video_id veya upload_url alınamadı: {init_veri}")

    log.info("Facebook Reels upload oturumu açıldı: video_id=%s", video_id)

    # 2. Aşama: İkili video dosyasını rupload.facebook.com'a yükle
    dosya_boyutu = video_p.stat().st_size
    headers = {
        "Authorization": f"OAuth {jeton}",
        "offset": "0",
        "file_size": str(dosya_boyutu),
        "Content-Type": "application/octet-stream",
    }
    with open(video_p, "rb") as f:
        up_res = requests.post(
            upload_url,
            headers=headers,
            data=f,
            timeout=180,
        )
    if up_res.status_code not in (200, 201):
        raise RuntimeError(f"Facebook Reels ikili yükleme hatası: HTTP {up_res.status_code} - {up_res.text[:250]}")

    log.info("Facebook Reels video dosyası rupload'a yüklendi (%d bayt)", dosya_boyutu)

    # 3. Aşama: Yayını tamamlama (upload_phase=finish)
    finish_url = f"{TABAN}/{api_surumu}/{sayfa_id}/video_reels"
    finish_res = requests.post(
        finish_url,
        data={
            "upload_phase": "finish",
            "access_token": jeton,
            "video_id": video_id,
            "video_state": "PUBLISHED",
            "description": temiz_metin,
        },
        timeout=zaman_asimi,
    )
    if finish_res.status_code != 200:
        raise RuntimeError(f"Facebook Reels yayını tamamlama hatası: HTTP {finish_res.status_code} - {finish_res.text[:250]}")

    log.info("Facebook Reels başarıyla yayınlandı (%s): %s", sayfa.get("name"), video_id)
    return str(video_id)

