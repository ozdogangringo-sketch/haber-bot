"""
twitter.py — X (Twitter) API v2 üzerinden tweet ve zincir (thread) paylaşımı.

OAuth 1.0a User Context ile çalışır:
  * TWITTER_API_KEY (Consumer Key)
  * TWITTER_API_SECRET (Consumer Secret)
  * TWITTER_ACCESS_TOKEN
  * TWITTER_ACCESS_TOKEN_SECRET

Özellikler:
  * 4 adede kadar görsel desteği (1.1/media/upload.json)
  * 280 karakter sınırı ve akıllı metin biçimlendirme
  * Çoklu haberler için birbirine bağlı Flood (Thread) paylaşımı
  * İkincil kanal koruması: Twitter hatası diğer platformları engellemez
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import io
import json
import logging
import os
import secrets
import time
from pathlib import Path
from urllib.parse import quote, urlencode

import requests
from dotenv import load_dotenv

log = logging.getLogger("twitter")
load_dotenv()

MEDIA_UPLOAD_URL = "https://upload.twitter.com/1.1/media/upload.json"
TWEET_API_URL = "https://api.twitter.com/2/tweets"
USER_ME_URL = "https://api.twitter.com/2/users/me"


def _anahtarlari_al() -> dict[str, str] | None:
    """Twitter / X API anahtarlarını ortamdan okur. Eksik varsa None döner."""
    api_key = (
        os.getenv("TWITTER_API_KEY")
        or os.getenv("X_API_KEY")
        or os.getenv("TWITTER_CONSUMER_KEY")
        or ""
    ).strip()
    api_secret = (
        os.getenv("TWITTER_API_SECRET")
        or os.getenv("X_API_SECRET")
        or os.getenv("TWITTER_CONSUMER_SECRET")
        or ""
    ).strip()
    access_token = (
        os.getenv("TWITTER_ACCESS_TOKEN")
        or os.getenv("X_ACCESS_TOKEN")
        or ""
    ).strip()
    access_token_secret = (
        os.getenv("TWITTER_ACCESS_TOKEN_SECRET")
        or os.getenv("X_ACCESS_TOKEN_SECRET")
        or os.getenv("X_ACCESS_SECRET")
        or ""
    ).strip()

    if not (api_key and api_secret and access_token and access_token_secret):
        return None

    return {
        "api_key": api_key,
        "api_secret": api_secret,
        "access_token": access_token,
        "access_token_secret": access_token_secret,
    }


def kullanilabilir_mi() -> bool:
    """Twitter entegrasyonu için gerekli tüm anahtarların tanımlı olup olmadığını denetler."""
    return _anahtarlari_al() is not None


def _oauth1_header(
    method: str,
    url: str,
    anahtarlar: dict[str, str],
    extra_params: dict | None = None,
) -> str:
    """
    RFC 5849 standardına tam uyumlu saf Python OAuth 1.0a Authorization başlığı üretir.
    Harici bağımlılık gerektirmez.
    """
    oauth_params = {
        "oauth_consumer_key": anahtarlar["api_key"],
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": anahtarlar["access_token"],
        "oauth_version": "1.0",
    }

    # İmzalanacak parametreler (query veya form verileri dahil)
    all_params = dict(oauth_params)
    if extra_params:
        all_params.update(extra_params)

    # Parametreleri alfabetik sıralayıp URL encode et
    sorted_encoded = []
    for k in sorted(all_params.keys()):
        sorted_encoded.append(f"{quote(str(k), safe='')}={quote(str(all_params[k]), safe='')}")
    param_str = "&".join(sorted_encoded)

    # İmza tabanı (Signature Base String)
    base_string = f"{method.upper()}&{quote(url, safe='')}&{quote(param_str, safe='')}"

    # İmzalama anahtarı
    signing_key = f"{quote(anahtarlar['api_secret'], safe='')}&{quote(anahtarlar['access_token_secret'], safe='')}".encode("utf-8")

    # HMAC-SHA1
    hashed = hmac.new(signing_key, base_string.encode("utf-8"), hashlib.sha1)
    signature = base64.b64encode(hashed.digest()).decode("utf-8")

    oauth_params["oauth_signature"] = signature

    # Header formatı
    header_parts = [f'{k}="{quote(oauth_params[k], safe="")}"' for k in sorted(oauth_params.keys())]
    return f"OAuth {', '.join(header_parts)}"


def medya_yukle(gorsel_yolu_veya_url: str | Path) -> str | None:
    """
    Görseli Twitter'a yükleyip media_id_string döner.
    En fazla 4 görsel bir tweet'e eklenebilir.
    """
    anahtarlar = _anahtarlari_al()
    if not anahtarlar:
        log.warning("Twitter anahtarları eksik, medya yüklenemedi.")
        return None

    # Görsel verisini al
    icerik = None
    if isinstance(gorsel_yolu_veya_url, (str, Path)) and os.path.exists(str(gorsel_yolu_veya_url)):
        with open(str(gorsel_yolu_veya_url), "rb") as f:
            icerik = f.read()
    elif isinstance(gorsel_yolu_veya_url, str) and gorsel_yolu_veya_url.startswith("http"):
        try:
            r = requests.get(gorsel_yolu_veya_url, timeout=20)
            if r.status_code == 200:
                icerik = r.content
        except Exception as e:
            log.warning("Görsel URL'den indirilemedi: %s (%s)", gorsel_yolu_veya_url, e)
            return None

    if not icerik:
        return None

    auth_header = _oauth1_header("POST", MEDIA_UPLOAD_URL, anahtarlar)
    files = {"media": icerik}

    try:
        r = requests.post(
            MEDIA_UPLOAD_URL,
            headers={"Authorization": auth_header},
            files=files,
            timeout=30,
        )
        if r.status_code in (200, 201, 202):
            veri = r.json()
            media_id = veri.get("media_id_string")
            log.info("Twitter görsel yüklendi: %s", media_id)
            return media_id
        log.error("Twitter medya yükleme hatası %s: %s", r.status_code, r.text[:200])
        return None
    except Exception as e:
        log.exception("Twitter medya yükleme isteği başarısız: %s", e)
        return None


def tweet_olustur(
    metin: str,
    medya_idler: list[str] | None = None,
    yanitlanan_id: str | None = None,
) -> dict | None:
    """
    Twitter API v2 üzerinden yeni bir tweet veya yanıt tweeti oluşturur.
    """
    anahtarlar = _anahtarlari_al()
    if not anahtarlar:
        return None

    auth_header = _oauth1_header("POST", TWEET_API_URL, anahtarlar)

    payload: dict = {"text": metin[:280]}
    if medya_idler:
        # En fazla 4 görsel
        payload["media"] = {"media_ids": [str(m) for m in medya_idler[:4]]}
    if yanitlanan_id:
        payload["reply"] = {"in_reply_to_tweet_id": str(yanitlanan_id)}

    try:
        r = requests.post(
            TWEET_API_URL,
            headers={
                "Authorization": auth_header,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=20,
        )
        if r.status_code in (200, 201):
            veri = r.json()
            tweet_data = veri.get("data", {})
            log.info("Tweet paylaşıldı: %s", tweet_data.get("id"))
            return tweet_data
        log.error("Tweet oluşturma hatası %s: %s", r.status_code, r.text[:300])
        return None
    except Exception as e:
        log.exception("Tweet oluşturma isteği başarısız: %s", e)
        return None


def tekil_yayinla(haber: dict, urller: list[str], ayarlar: dict) -> str | None:
    """
    Tekil post / son dakika haberini Twitter'a (X) fotoğraflarıyla birlikte paylaşır.
    """
    if not kullanilabilir_mi():
        log.info("Twitter anahtarları tanımlı değil, tekil paylaşım atlandı.")
        return None

    # 1. Görselleri yükle (en fazla 4 adet)
    medya_idler = []
    for u in (urller or [])[:4]:
        mid = medya_yukle(u)
        if mid:
            medya_idler.append(mid)

    # 2. Metin oluştur
    from . import caption
    metin = caption.twitter_metni_kur(haber, ayarlar)

    # 3. Tweet at
    sonuc = tweet_olustur(metin, medya_idler=medya_idler)
    return sonuc.get("id") if sonuc else None


def zincir_yayinla(
    haberler: list[dict],
    urller: list[str],
    ayarlar: dict,
    son_dakika: bool = False,
) -> tuple[str | None, int]:
    """
    Çoklu haber turunu veya son dakika detaylarını Twitter'da birbirine bağlı Flood (Zincir) olarak paylaşır.

    1. Tweet: Giriş & Özet / Piyasa Kartı
    2..N Tweet: Her haberin slaytı ve özeti (önceki tweete yanıt olarak)
    """
    if not kullanilabilir_mi() or not haberler:
        return None, 0

    from . import caption

    halkalar = caption.twitter_zincir_metinleri(
        haberler, ayarlar, son_dakika=son_dakika, urller=urller
    )
    ilk_id = None
    onceki_id = None
    yayinlanan = 0

    for i, h_metin in enumerate(halkalar):
        # İlgili halkaya ait görsel
        medya_idler = []
        if i < len(urller) and urller[i]:
            mid = medya_yukle(urller[i])
            if mid:
                medya_idler.append(mid)

        tweet = tweet_olustur(
            metin=h_metin,
            medya_idler=medya_idler,
            yanitlanan_id=onceki_id,
        )

        if tweet and "id" in tweet:
            tid = tweet["id"]
            if ilk_id is None:
                ilk_id = tid
            onceki_id = tid
            yayinlanan += 1
            # Rate limit ve tweet işleme payı
            time.sleep(2)
        else:
            log.warning("Twitter zincirinin %s. halkası paylaşılamadı.", i + 1)
            break

    log.info("Twitter zinciri tamamlandı: %s/%s halka (ilk_id=%s)", yayinlanan, len(halkalar), ilk_id)
    return ilk_id, yayinlanan


def post_baglantisi(tweet_id: str, kullanici_adi: str = "dailybrief_co") -> str:
    """Tweetin doğrudan X web bağlantısını döner."""
    return f"https://x.com/{kullanici_adi}/status/{tweet_id}"


def api_saglik_testi() -> dict:
    """Twitter API v2 bağlantısını ve kimlik doğrulamasını test eder."""
    anahtarlar = _anahtarlari_al()
    if not anahtarlar:
        return {
            "ad": "X (Twitter) API v2",
            "durum": False,
            "mesaj": "TWITTER_API_KEY veya ACCESS_TOKEN eksik.",
        }

    try:
        auth_header = _oauth1_header("GET", USER_ME_URL, anahtarlar)
        r = requests.get(
            USER_ME_URL,
            headers={"Authorization": auth_header},
            timeout=10,
        )
        if r.status_code == 200:
            veri = r.json().get("data", {})
            username = veri.get("username", "Bilinmiyor")
            name = veri.get("name", "")
            return {
                "ad": "X (Twitter) API v2",
                "durum": True,
                "mesaj": f"Bağlantı ve bakiye aktif (@{username} - {name})",
            }
        else:
            hata = r.json().get("detail") or r.text[:80]
            return {
                "ad": "X (Twitter) API v2",
                "durum": False,
                "mesaj": f"API Hatası ({r.status_code}): {hata}",
            }
    except Exception as e:
        return {
            "ad": "X (Twitter) API v2",
            "durum": False,
            "mesaj": f"İstek hatası: {type(e).__name__}",
        }
