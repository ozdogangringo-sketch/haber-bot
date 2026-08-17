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
import time

import requests
from dotenv import load_dotenv

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
        if cevap.status_code in GECICI_HATALAR:
            time.sleep(2 * deneme)
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

    # --- Tek görsel: albüme gerek yok ---
    if len(gorsel_urlleri) == 1:
        d = _istek("POST", "/me/photos", ayarlar,
                   url=gorsel_urlleri[0], caption=metin)
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
    d = _istek("POST", "/me/feed", ayarlar, message=metin, **ekler)

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


def post_baglantisi(post_id: str) -> str:
    """Facebook post bağlantısı — Telegram sonucunda göstermek için."""
    return f"https://www.facebook.com/{post_id}"
