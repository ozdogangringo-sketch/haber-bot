"""
threads.py — Aynı içeriği Threads'e de paylaşır.

⚠️ AYRI JETON GEREKİYOR — Instagram/Facebook jetonu BURADA ÇALIŞMAZ.
    Threads'in kendi API'si var (graph.threads.net) ve kendi
    yetkilendirmesi. Meta altyapısında olmasına rağmen jeton paylaşımı
    yok; `THREADS_ACCESS_TOKEN` ve `THREADS_USER_ID` ayrı duruyor.

AKIŞ — Instagram'a çok benziyor:
    Tek görsel:
        POST /{user-id}/threads   media_type=IMAGE, image_url, text
        POST /{user-id}/threads_publish   creation_id
    Çoklu görsel (carousel):
        her görsel için  media_type=IMAGE + is_carousel_item=true
        sonra            media_type=CAROUSEL + children=[...]
        sonra            threads_publish

KISITLAR (Meta'nın, bizim değil):
    * Carousel'de 2-20 görsel (Instagram'da 10'du, burada daha bol)
    * Günde 250 post — bizim 3 postumuz sınırın çok altında
    * Görsel herkese açık URL'de olmalı (imgbb zaten öyle)
    * Container işlenene kadar beklemek gerekiyor

İKİNCİL KANAL:
    Threads paylaşımı patlarsa Instagram postu YAYINDA KALIYOR.
    Hata yutuluyor, Telegram sonucuna not düşülüyor.
"""

from __future__ import annotations

import logging
import os
import time

import requests
from dotenv import load_dotenv

log = logging.getLogger(__name__)
load_dotenv()

TABAN = "https://graph.threads.net/v1.0"
GECICI_HATALAR = {429, 500, 502, 503, 504}
ZAMAN_ASIMI = 60


def kullanilabilir_mi() -> bool:
    """
    Threads anahtarları tanımlı mı?

    Tanımlı değilse paylaşım sessizce atlanıyor — anahtar yok diye tur
    düşmemeli. Böylece jeton alınmadan önce de kod güvenle çalışıyor.
    """
    return bool(os.getenv("THREADS_ACCESS_TOKEN", "").strip()
                and os.getenv("THREADS_USER_ID", "").strip())


def _jeton() -> str:
    j = os.getenv("THREADS_ACCESS_TOKEN", "").strip()
    if not j:
        raise RuntimeError("THREADS_ACCESS_TOKEN bulunamadı (.env)")
    return j


def _kullanici() -> str:
    k = os.getenv("THREADS_USER_ID", "").strip()
    if not k:
        raise RuntimeError("THREADS_USER_ID bulunamadı (.env)")
    return k


def _istek(yontem: str, yol: str, **parametreler) -> dict:
    url = f"{TABAN}{yol}"
    parametreler["access_token"] = _jeton()

    son_hata = None
    for deneme in range(1, 4):
        try:
            if yontem.upper() == "GET":
                cevap = requests.get(url, params=parametreler,
                                     timeout=ZAMAN_ASIMI)
            else:
                cevap = requests.post(url, data=parametreler,
                                      timeout=ZAMAN_ASIMI)
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

    raise RuntimeError(f"Threads API hatası ({yol}): {son_hata}")


def hesap_bilgisi() -> dict:
    """Jetonun hangi Threads hesabına ait olduğunu döner."""
    return _istek("GET", f"/{_kullanici()}",
                  fields="id,username,threads_profile_picture_url")


def _container_bekle(container_id: str, azami: int = 12) -> None:
    """
    Container'ın işlenmesini bekler.

    Threads görseli indirip işliyor; hazır olmadan publish çağırmak
    hata veriyor. Instagram'daki aynı mantık.
    """
    for _ in range(azami):
        d = _istek("GET", f"/{container_id}", fields="status,error_message")
        durum = d.get("status")
        if durum == "FINISHED":
            return
        if durum == "ERROR":
            raise RuntimeError(f"container işlenemedi: {d.get('error_message')}")
        time.sleep(5)
    raise RuntimeError(f"container zamanında hazır olmadı: {container_id}")


def yayinla(gorsel_urlleri: list[str], metin: str) -> str:
    """
    Görselleri Threads'e paylaşır, post id'sini döner.

    Tek görselde carousel'e gerek yok; çoklu görselde Instagram'daki
    üç aşamalı akış uygulanıyor.
    """
    if not gorsel_urlleri:
        raise ValueError("paylaşılacak görsel yok")

    kullanici = _kullanici()

    # --- Tek görsel ---
    if len(gorsel_urlleri) == 1:
        d = _istek("POST", f"/{kullanici}/threads",
                   media_type="IMAGE", image_url=gorsel_urlleri[0],
                   text=metin[:500])
        _container_bekle(d["id"])
        d = _istek("POST", f"/{kullanici}/threads_publish",
                   creation_id=d["id"])
        log.info("Threads tek görsel yayınlandı: %s", d.get("id"))
        return d["id"]

    # --- Carousel ---
    cocuklar = []
    for i, url in enumerate(gorsel_urlleri, 1):
        d = _istek("POST", f"/{kullanici}/threads",
                   media_type="IMAGE", image_url=url,
                   is_carousel_item="true")
        cocuklar.append(d["id"])
        log.info("Threads container %d/%d", i, len(gorsel_urlleri))

    for cocuk in cocuklar:
        _container_bekle(cocuk)

    d = _istek("POST", f"/{kullanici}/threads",
               media_type="CAROUSEL", children=",".join(cocuklar),
               text=metin[:500])
    _container_bekle(d["id"])

    d = _istek("POST", f"/{kullanici}/threads_publish", creation_id=d["id"])
    log.info("Threads carousel yayınlandı: %s", d.get("id"))
    return d["id"]


def post_baglantisi(post_id: str) -> str:
    """Threads post bağlantısı — Telegram sonucunda göstermek için."""
    try:
        d = _istek("GET", f"/{post_id}", fields="permalink")
        return d.get("permalink", "")
    except Exception:
        return ""
