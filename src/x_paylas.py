"""
x_paylas.py — Aynı gündemi X'e (Twitter) metin olarak paylaşır.

⚠️ SADECE METİN — kullanıcının kararı. Görsel yükleme ücretsiz katmanda
    kısıtlı ve ayrı bir yükleme akışı gerektiriyor; metin postu sınırların
    çok altında kalıyor.

⚠️ AYRI KİMLİK DOĞRULAMA — Meta jetonları burada çalışmaz. X, OAuth 1.0a
    kullanıyor ve DÖRT anahtar istiyor:
        X_API_KEY, X_API_SECRET          (uygulama kimliği)
        X_ACCESS_TOKEN, X_ACCESS_SECRET  (hesap kimliği)

    OAuth 2.0'ın Client ID/Secret'ı BİZE LAZIM DEĞİL: o, başkalarının
    uygulamamıza kendi hesabıyla girmesi için. Biz yalnızca kendi
    hesabımıza yazıyoruz ve OAuth 1.0a anahtarları SÜRESİZ — Threads'te
    uğraştığımız 60 günlük yenileme derdi burada yok.

⚠️ 280 KARAKTER. Instagram caption'ı 1100-1500 karakter; olduğu gibi
    gönderilemiyor. `metni_kur()` gündemi X'e sığacak şekilde yeniden
    yazıyor: tarih + sığdığı kadar manşet + hashtag.

İKİNCİL KANAL:
    Paylaşım patlarsa Instagram postu YAYINDA KALIR. Hata yutuluyor,
    Telegram sonucuna not düşülüyor.
"""

from __future__ import annotations

import logging
import os

import requests
from dotenv import load_dotenv
from requests_oauthlib import OAuth1

log = logging.getLogger(__name__)
load_dotenv()

TWEET_UCU = "https://api.x.com/2/tweets"
HESAP_UCU = "https://api.x.com/2/users/me"
ZAMAN_ASIMI = 60

# Ücretsiz katmanda tweet sınırı 280. Premium 25.000 ama ona geçmiyoruz.
AZAMI_KARAKTER = 280

ANAHTARLAR = ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")


def kullanilabilir_mi() -> bool:
    """
    Dört anahtar da tanımlı mı?

    Biri bile eksikse paylaşım sessizce atlanıyor — anahtar yok diye tur
    düşmemeli. Threads'teki desenin aynısı.
    """
    return all(os.getenv(a, "").strip() for a in ANAHTARLAR)


def _kimlik() -> OAuth1:
    eksik = [a for a in ANAHTARLAR if not os.getenv(a, "").strip()]
    if eksik:
        raise RuntimeError(f"X anahtarları eksik: {', '.join(eksik)}")
    return OAuth1(
        os.getenv("X_API_KEY").strip(),
        client_secret=os.getenv("X_API_SECRET").strip(),
        resource_owner_key=os.getenv("X_ACCESS_TOKEN").strip(),
        resource_owner_secret=os.getenv("X_ACCESS_SECRET").strip(),
    )


def hesap_bilgisi() -> dict:
    """Anahtarların hangi hesaba ait olduğunu döner."""
    cevap = requests.get(HESAP_UCU, auth=_kimlik(), timeout=ZAMAN_ASIMI)
    if cevap.status_code != 200:
        raise RuntimeError(
            f"X hesabı okunamadı (HTTP {cevap.status_code}): {cevap.text[:300]}"
        )
    return cevap.json().get("data", {})


def metni_kur(basliklar: list[str], tarih: str, hashtagler: list[str]) -> str:
    """
    Gündemi 280 karaktere sığdırır.

    NEDEN KIRPMA DEĞİL DE YENİDEN KURMA: Instagram caption'ını 280'de
    kesmek cümlenin ortasında bitiyor ve altındaki kaynak/atıf satırları
    zaten sığmıyor. Burada baştan X'e uygun bir metin kuruluyor.

    ÖNCELİK SIRASI: tarih ve ilk manşetler en değerli kısım; sığmayan
    manşetler düşüyor, hashtag'ler ondan da önce feda ediliyor.
    """
    bas = f"📰 {tarih} gündemi\n\n"
    etiket = " ".join(hashtagler[:3])
    kuyruk = f"\n\n{etiket}" if etiket else ""

    satirlar: list[str] = []
    for i, baslik in enumerate(basliklar, 1):
        aday = satirlar + [f"{i}. {baslik}"]
        deneme = bas + "\n".join(aday) + kuyruk
        if len(deneme) > AZAMI_KARAKTER:
            break
        satirlar = aday

    if not satirlar:
        # Tek manşet bile sığmadıysa hashtag'i at, manşeti kısalt.
        tek = basliklar[0] if basliklar else ""
        yer = AZAMI_KARAKTER - len(bas) - 1
        return (bas + tek[:yer] + "…")[:AZAMI_KARAKTER]

    kalan = len(basliklar) - len(satirlar)
    if kalan > 0:
        ek = f"\n+{kalan} haber daha"
        if len(bas + "\n".join(satirlar) + ek + kuyruk) <= AZAMI_KARAKTER:
            satirlar.append(ek.strip())

    return bas + "\n".join(satirlar) + kuyruk


def yayinla(metin: str) -> str:
    """Metni X'e gönderir, tweet id'sini döner."""
    if not metin.strip():
        raise ValueError("boş tweet gönderilemez")
    if len(metin) > AZAMI_KARAKTER:
        raise ValueError(f"tweet {len(metin)} karakter, sınır {AZAMI_KARAKTER}")

    cevap = requests.post(TWEET_UCU, json={"text": metin},
                          auth=_kimlik(), timeout=ZAMAN_ASIMI)
    if cevap.status_code not in (200, 201):
        # 403 genelde "Read and write" izni verilmemiş demek: anahtarlar
        # geçerli ama token okuma izniyle üretilmiş. Çözüm izni düzeltip
        # Access Token'ı YENİDEN üretmek — izin değişikliği eski token'a
        # geçmiyor.
        raise RuntimeError(
            f"X paylaşımı başarısız (HTTP {cevap.status_code}): "
            f"{cevap.text[:300]}"
        )
    return cevap.json().get("data", {}).get("id", "")


def post_baglantisi(tweet_id: str, kullanici: str) -> str:
    return f"https://x.com/{kullanici}/status/{tweet_id}" if tweet_id else ""
