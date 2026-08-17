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

# ⚠️ HTTP KODUNA BAKMAK YETMİYOR — Instagram'daki tuzağın aynısı.
#
# 2207052 "An unknown error occurred" HTTP 400 ile geliyor ve kalıcı bir
# hata gibi duruyor. 17 Ağu 2026'da kurulum sırasında ölçüldü: aynı
# görsel için 4 deneme üst üste bu hatayı verdi, sonra kendiliğinden
# geçti ve İKİ farklı barındırıcıdan görsel sorunsuz yüklendi.
# Görselde kusur yoktu (JPEG, 1080x1350, 170 KB) — Threads'in medya
# işleme tarafı hazır değildi.
GECICI_ALT_KODLAR = {2207003, 2207032, 2207052}

# Medya hatasında daha uzun bekleniyor: sorun bizim isteğimizde değil,
# görselin karşı tarafça indirilmesinde.
MEDYA_BEKLEME_SANIYE = 15

# ⚠️ CAROUSEL CONTAINER'LARI ARASINDA BEKLEMEK ZORUNLU.
#
# Threads art arda gelen medya isteklerini reddediyor. ÖLÇÜLDÜ
# (18 Ağu 2026, aynı 6 görsel, aynı hesap):
#     aralıksız      -> 1/6 başarılı (2207003 ve 2207052 hataları)
#     5 sn aralıklı  -> 6/6 başarılı
#
# Instagram aynı tempoya sorunsuz dayanıyor, bu yüzden Instagram'dan
# kopyalanan akış burada patlıyordu. Retry mantığı hatayı kurtarıyordu
# ama her görselde 15+ saniye kaybettiriyordu; aralık koymak hem daha
# hızlı hem daha temiz.
CONTAINER_ARASI_SANIYE = 5


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


def _alt_kod(cevap) -> int | None:
    """Threads hata cevabından `error_subcode`'u çıkarır."""
    try:
        return cevap.json().get("error", {}).get("error_subcode")
    except Exception:
        return None


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

        if _alt_kod(cevap) in GECICI_ALT_KODLAR:
            log.warning("Threads medya hatası, %s sn sonra tekrar (%s/3)",
                        MEDYA_BEKLEME_SANIYE, deneme)
            time.sleep(MEDYA_BEKLEME_SANIYE * deneme)
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
        # Aralık ZORUNLU — açıklaması CONTAINER_ARASI_SANIYE'de.
        if i > 1:
            time.sleep(CONTAINER_ARASI_SANIYE)
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


def jetonu_yenile() -> tuple[str, int]:
    """
    Jetonu 60 gün daha uzatır. `(yeni_jeton, kalan_gun)` döner.

    ⚠️ THREADS'TE SÜRESİZ JETON YOK. Instagram'da `/me/accounts` ile
    alınan sayfa jetonu süresiz (`expires_at = 0`) ve o yüzden orada
    yenileme yalnızca "öldü mü?" kontrolü. Threads'te öyle bir seçenek
    yok: jeton kullanıcıya ait ve 60 günde ölüyor. Yenilenmezse Threads
    paylaşımı sessizce durur — `kullanilabilir_mi()` True dönmeye devam
    eder, hata ancak yayın anında çıkar.

    ⚠️ JETON EN AZ 24 SAATLİK OLMALI. Yeni üretilmiş bir jetonu
    yenilemeye çalışmak hata veriyor. Haftalık cron'da bu hiç sorun
    değil, ama jeton alındığı gün elle çalıştırırsan patlar.

    Yenileme uç noktası sürüm ekisiz: `graph.threads.net/refresh_access_token`.
    """
    cevap = requests.get(
        "https://graph.threads.net/refresh_access_token",
        params={"grant_type": "th_refresh_token", "access_token": _jeton()},
        timeout=ZAMAN_ASIMI,
    )
    if cevap.status_code != 200:
        raise RuntimeError(
            f"Threads jetonu yenilenemedi (HTTP {cevap.status_code}): "
            f"{cevap.text[:300]}"
        )
    d = cevap.json()
    yeni = d.get("access_token", "")
    if not yeni:
        raise RuntimeError(f"cevapta access_token yok: {str(d)[:200]}")
    return yeni, int(d.get("expires_in", 0)) // 86400


def post_baglantisi(post_id: str) -> str:
    """Threads post bağlantısı — Telegram sonucunda göstermek için."""
    try:
        d = _istek("GET", f"/{post_id}", fields="permalink")
        return d.get("permalink", "")
    except Exception:
        return ""
