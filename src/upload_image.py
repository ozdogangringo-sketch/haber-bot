"""
upload_image.py — ADIM 4a
Üretilen görselleri imgbb'ye yükleyip herkese açık URL alır.

NEDEN GEREKLİ:
    Instagram Graph API görseli dosya olarak KABUL ETMİYOR. Sadece
    "şu adresteki görseli al" diyebiliyorsun — yani görselin internette
    herkese açık bir adreste durması şart. Bizim sunucumuz olmadığı için
    imgbb'yi ara depo olarak kullanıyoruz.

YAYIN SONRASI:
    Instagram post'u yayınlarken görselin kendi kopyasını alıyor. Yani
    imgbb'deki dosya yayından sonra silinse bile post etkilenmiyor.
    Bu yüzden yüklemelere son kullanma tarihi veriyoruz — hesabımız
    zamanla çöp dolmasın.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import logging
import mimetypes
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

log = logging.getLogger(__name__)
load_dotenv()

UC_NOKTA = "https://api.imgbb.com/1/upload"
GECICI_HATALAR = {429, 500, 502, 503, 504}

# ⚠️ HTTP KODUNA BAKMAK YETMİYOR — imgbb iç hatalarını 400 ile veriyor.
#
# 21 Ağu 2026, 08:31'de bir tekil post şu hatayla düştü:
#   HTTP 400: {"error":{"message":"Internal upload error","code":111}}
# 400 "kalıcı hata" sayıldığı için HİÇ tekrar denenmedi. Oysa aynı
# görsel 35 saniye sonra (08:32) sorunsuz yüklendi — hata tamamen
# imgbb tarafındaydı ve geçiciydi.
#
# Bu, projede ÜÇÜNCÜ kez görülen desen: Instagram 2207052, Telegram
# WEBPAGE_CURL_FAILED ve şimdi imgbb code 111. Üçü de "400 döndürüyor
# ama saniyeler sonra çalışıyor".
# imgbb iç hatasında sabit bekleme. Artan bekleme denenmedi:
# Instagram ve Threads'te ölçüldü, sorun karşı tarafın anlık
# durumu ve 2 saniye sonra tekrar sormak aynı yüke biniyor.
GECICI_BEKLEME = 8

GECICI_MESAJLAR = (
    "internal upload error",
    "internal error",
    "try again",
    "temporarily",
)


def _anahtarlar() -> list[str]:
    """Tüm tanımlı ImgBB anahtarlarını döner (virgülle ayrılmış veya _2, _3 ekli)."""
    anahtarlar = []
    ana = os.getenv("IMGBB_API_KEY", "").strip()
    if ana:
        for k in ana.split(","):
            k_temiz = k.strip()
            if k_temiz and k_temiz not in anahtarlar:
                anahtarlar.append(k_temiz)

    for ek in ("IMGBB_API_KEY_2", "IMGBB_API_KEY_3", "IMGBB_API_KEY_YEDEK"):
        k = os.getenv(ek, "").strip()
        if k and k not in anahtarlar:
            anahtarlar.append(k)

    if not anahtarlar:
        raise RuntimeError(
            "IMGBB_API_KEY bulunamadı. imgbb.com/api adresinden alıp "
            ".env dosyasına ekle."
        )
    return anahtarlar


def _r2_bilgileri() -> tuple[str, str, str, str, str] | None:
    """R2 ortam değişkenlerini kontrol eder: (account_id, access_key, secret_key, bucket, domain) veya None."""
    acc_id = os.getenv("R2_ACCOUNT_ID", "").strip()
    key_id = os.getenv("R2_ACCESS_KEY_ID", "").strip()
    sec_key = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()
    bucket = os.getenv("R2_BUCKET_NAME", "dailybrief-media").strip()
    domain = os.getenv("R2_PUBLIC_DOMAIN", "media.dailybrief.ozbornstudio.com").strip().rstrip("/")
    if acc_id and key_id and sec_key and bucket:
        return acc_id, key_id, sec_key, bucket, domain
    return None


def r2ye_yukle(yol: Path | str, alt_klasor: str = "sosyal", zaman_asimi: int = 40) -> dict:
    """
    Dosyayı Cloudflare R2 bucket'ına S3 SigV4 ile yükler ve herkese açık custom domain URL'ini döner.
    """
    bilgi = _r2_bilgileri()
    if not bilgi:
        raise RuntimeError("R2 ortam değişkenleri tanımlı değil")

    acc_id, key_id, sec_key, bucket, domain = bilgi
    p = Path(yol)
    ham = p.read_bytes()

    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    guvenli_ad = f"{ts}_{p.name}"
    object_key = f"{alt_klasor}/{guvenli_ad}" if alt_klasor else guvenli_ad

    content_type = mimetypes.guess_type(p.name)[0] or "application/octet-stream"

    # AWS SigV4 imzası
    now = datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    region = "auto"
    service = "s3"
    host = f"{acc_id}.r2.cloudflarestorage.com"
    endpoint = f"https://{host}"

    payload_hash = hashlib.sha256(ham).hexdigest()

    canonical_uri = f"/{bucket}/{object_key}"
    canonical_querystring = ""
    canonical_headers = f"host:{host}\nx-amz-content-sha256:{payload_hash}\nx-amz-date:{amz_date}\n"
    signed_headers = "host;x-amz-content-sha256;x-amz-date"

    canonical_request = f"PUT\n{canonical_uri}\n{canonical_querystring}\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
    algorithm = "AWS4-HMAC-SHA256"
    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = f"{algorithm}\n{amz_date}\n{credential_scope}\n{hashlib.sha256(canonical_request.encode()).hexdigest()}"

    def sign(key, msg):
        if isinstance(msg, str):
            msg = msg.encode("utf-8")
        return hmac.new(key, msg, hashlib.sha256).digest()

    k_date = sign(("AWS4" + sec_key).encode("utf-8"), date_stamp)
    k_region = sign(k_date, region)
    k_service = sign(k_region, service)
    k_signing = sign(k_service, "aws4_request")

    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    auth_header = f"{algorithm} Credential={key_id}/{credential_scope}, SignedHeaders={signed_headers}, Signature={signature}"

    headers = {
        "host": host,
        "x-amz-date": amz_date,
        "x-amz-content-sha256": payload_hash,
        "Authorization": auth_header,
        "Content-Type": content_type,
    }

    url = f"{endpoint}/{bucket}/{object_key}"
    cevap = requests.put(url, data=ham, headers=headers, timeout=zaman_asimi)
    if cevap.status_code not in (200, 204):
        raise RuntimeError(f"R2 yükleme hatası HTTP {cevap.status_code}: {cevap.text[:150]}")

    public_url = f"https://{domain}/{object_key}"
    return {
        "url": public_url,
        "silme_url": None,
        "boyut_kb": round(len(ham) / 1024, 1),
    }


def _litterboxa_yukle(yol: Path, zaman_asimi: int) -> dict:
    """
    Yedek barındırıcı #1 — catbox'ın GEÇİCİ dosya servisi.
    72 saat saklar — Meta (Instagram, Facebook, Threads) sunucuları doğrudan indirebilir.
    """
    with open(yol, "rb") as f:
        cevap = requests.post(
            "https://litterbox.catbox.moe/resources/internals/api.php",
            data={"reqtype": "fileupload", "time": "72h"},
            files={"fileToUpload": (yol.name, f, "image/jpeg")},
            timeout=zaman_asimi,
        )
    if cevap.status_code != 200 or not cevap.text.startswith("http"):
        raise RuntimeError(f"litterbox: HTTP {cevap.status_code}: {cevap.text[:120]}")
    return {"url": cevap.text.strip(), "silme_url": None,
            "boyut_kb": round(yol.stat().st_size / 1024, 1)}


def _uguya_yukle(yol: Path, zaman_asimi: int) -> dict:
    """Yedek barındırıcı #2 — litterbox da düşerse."""
    with open(yol, "rb") as f:
        cevap = requests.post(
            "https://uguu.se/upload",
            files={"files[]": (yol.name, f, "image/jpeg")},
            timeout=zaman_asimi,
        )
    veri = cevap.json()
    url = (veri.get("files") or [{}])[0].get("url")
    if not url:
        raise RuntimeError(f"uguu: HTTP {cevap.status_code}: {str(veri)[:120]}")
    return {"url": url, "silme_url": None,
            "boyut_kb": round(yol.stat().st_size / 1024, 1)}


# ⚠️ SIRA ÖNEMLİ: Litterbox 72 saat saklar ve Meta Graph API doğrudan erişebilir.
YEDEK_BARINDIRICILAR = (
    ("litterbox", _litterboxa_yukle),
    ("uguu", _uguya_yukle),
)


# ⚠️ BU SÜREÇTE YÜKLENEN DOSYALARIN HARİTASI: url -> yerel yol.
# Neden var (6 Eyl 2026): yayın job'ı slaytları üretip imgbb'ye
# yüklüyor, sonra Reels videosunu kurmak için AYNI dosyaları imgbb'den
# GERİ İNDİRİYORDU. i.ibb.co cevap vermeyince (read timeout) dört
# karenin dördü de düştü ve "Reels videosu için 9:16 görsel üretilemedi"
# hatasıyla video hiç üretilmedi — Telegram'a da düşmedi.
# ⚠️ Bu harita "eski yerel dosyayı kullan" DEĞİL: yalnızca AYNI süreçte
# o URL'i üretmek için yüklediğimiz dosyayı hatırlıyor. 3 Eyl'deki
# "onaylanan görsel ≠ videodaki görsel" kusuru bayat yerel dosyadan
# çıkmıştı; burada dosya ile URL'in aynı içerik olduğu garanti.
_YUKLENEN_YEREL: dict[str, str] = {}


def yerel_karsiligi(url: str) -> Path | None:
    """Bu süreçte bu URL'i üretmek için yüklenen yerel dosya (varsa)."""
    yol = _YUKLENEN_YEREL.get(str(url or ""))
    if not yol:
        return None
    p = Path(yol)
    return p if p.exists() else None


def gorsel_yukle(yol: Path, ayarlar: dict) -> dict:
    """
    Tek bir görseli yükler.

    Döner: {'url', 'silme_url', 'boyut_kb'}
    Başaramazsa exception fırlatır — çağıran taraf yakalamalı.
    """
    g = ayarlar.get("imgbb", {})
    yol = Path(yol)
    ham = yol.read_bytes()

    # ⚡ 1. ÖNCELİKLİ BARINDIRICI: Cloudflare R2 (media.dailybrief.ozbornstudio.com)
    if _r2_bilgileri():
        try:
            r2_sonuc = r2ye_yukle(yol, alt_klasor="sosyal", zaman_asimi=g.get("zaman_asimi", 30))
            _YUKLENEN_YEREL[r2_sonuc["url"]] = str(yol)
            log.info("Görsel R2'ye yüklendi: %s", r2_sonuc["url"])
            return r2_sonuc
        except Exception as e:
            log.warning("R2 görsel yükleme başarısız, ImgBB/yedeğe geçiliyor: %s", e)

    son_hata = None
    tum_anahtarlar = _anahtarlar()

    # Önce tüm ImgBB anahtarlarını sırayla dene
    for anahtar_idx, anahtar in enumerate(tum_anahtarlar, 1):
        for deneme in range(1, g["deneme_sayisi"] + 1):
            try:
                cevap = requests.post(
                    UC_NOKTA,
                    data={
                        "key": anahtar,
                        "image": base64.b64encode(ham).decode("ascii"),
                        "name": yol.stem,
                        "expiration": g["omur_saniye"],
                    },
                    timeout=g["zaman_asimi"],
                )
            except requests.RequestException as e:
                son_hata = f"{type(e).__name__}: {e}"
                log.warning("imgbb ağ hatası (anahtar %d, deneme %d): %s", anahtar_idx, deneme, e)
                time.sleep(2 * deneme)
                continue

            if cevap.status_code == 200:
                veri = cevap.json()
                if not veri.get("success"):
                    raise RuntimeError(f"imgbb reddetti: {str(veri)[:200]}")
                d = veri["data"]
                _YUKLENEN_YEREL[d["url"]] = str(yol)
                return {
                    "url": d["url"],
                    "silme_url": d.get("delete_url"),
                    "boyut_kb": round(len(ham) / 1024, 1),
                }

            son_hata = f"HTTP {cevap.status_code}: {cevap.text[:200]}"
            if cevap.status_code in GECICI_HATALAR:
                time.sleep(2 * deneme)
                continue

            govde = (cevap.text or "").lower()
            if any(k in govde for k in GECICI_MESAJLAR):
                log.warning("imgbb iç hatası, %s sn sonra tekrar: %s", GECICI_BEKLEME, cevap.text[:100])
                time.sleep(GECICI_BEKLEME)
                continue

            # Kota veya rate limit ise sonraki anahtara geç
            if "rate limit" in govde or "limit reached" in govde:
                log.warning("imgbb anahtar %d kota doldu (%s), sonraki anahtar/yedeğe geçiliyor", anahtar_idx, son_hata)
                break
            break

    # ⚠️ İMGBB TAMAMEN KAPALIYSA TEKRAR DENEMEK ANLAMSIZ — yedeğe geç.
    # Bakım hatası (code 100) geçici bir dalgalanma değil; 3 deneme de
    # aynı cevabı veriyor. Post atamamaktansa başka barındırıcı.
    if (ayarlar.get("gorsel", {}) or {}).get("yedek_barindirici", True):
        log.warning("imgbb başarısız (%s), yedek barındırıcıya geçiliyor",
                    str(son_hata)[:120])
        for ad, islev in YEDEK_BARINDIRICILAR:
            try:
                sonuc = islev(Path(yol), g["zaman_asimi"])
                log.info("%s'e yüklendi: %s", ad, sonuc["url"])
                _YUKLENEN_YEREL[sonuc["url"]] = str(yol)
                return sonuc
            except Exception as e:                    # noqa: BLE001
                log.warning("%s olmadı: %s", ad, str(e)[:130])
        log.error("bütün yedek barındırıcılar başarısız")

    raise RuntimeError(f"imgbb yüklemesi başarısız: {son_hata}")


def hepsini_yukle(yollar: list[Path], ayarlar: dict) -> list[dict]:
    """
    Carousel için birden fazla görseli sırayla yükler.

    Biri patlarsa TAMAMI iptal edilir (exception fırlatır): eksik
    slaytla post atmak, hiç atmamaktan kötü.
    """
    sonuclar = []
    for i, yol in enumerate(yollar, 1):
        sonuc = gorsel_yukle(yol, ayarlar)
        log.info("yüklendi %d/%d: %s", i, len(yollar), sonuc["url"])
        sonuclar.append(sonuc)
    return sonuclar


def video_yukle(yol: Path | str, ayarlar: dict | None = None) -> str:
    """
    MP4 video dosyasını barındırıcıya yükleyip herkese açık HTTPS URL döner.
    Instagram Reels / Video Graph API'si için kullanılır.
    """
    p = Path(yol)
    if not p.exists():
        raise FileNotFoundError(f"Video dosyası bulunamadı: {p}")

    zaman_asimi = 90

    # ⚡ 1. ÖNCELİKLİ BARINDIRICI: Cloudflare R2 (media.dailybrief.ozbornstudio.com)
    if _r2_bilgileri():
        try:
            r2_sonuc = r2ye_yukle(p, alt_klasor="video", zaman_asimi=zaman_asimi)
            log.info("Video R2'ye yüklendi: %s", r2_sonuc["url"])
            return r2_sonuc["url"]
        except Exception as e:
            log.warning("Video R2'ye yüklenemedi, uguu/litterbox'a geçiliyor: %s", e)

    # 2. uguu.se (Hızlı, Instagram / Meta sunucuları doğrudan indirebiliyor)
    try:
        with open(p, "rb") as f:
            cevap = requests.post(
                "https://uguu.se/upload",
                files={"files[]": (p.name, f, "video/mp4")},
                timeout=zaman_asimi,
            )
        if cevap.status_code == 200:
            veri = cevap.json()
            url = (veri.get("files") or [{}])[0].get("url")
            if url:
                log.info("Video uguu'ya yüklendi: %s", url)
                return url
    except Exception as e:
        log.warning("Video uguu'ya yüklenemedi: %s", e)

    # 2. litterbox (Yedek servis)
    try:
        with open(p, "rb") as f:
            cevap = requests.post(
                "https://litterbox.catbox.moe/resources/internals/api.php",
                data={"reqtype": "fileupload", "time": "72h"},
                files={"fileToUpload": (p.name, f, "video/mp4")},
                timeout=zaman_asimi,
            )
        if cevap.status_code == 200 and cevap.text.startswith("http"):
            url = cevap.text.strip()
            log.info("Video litterbox'a yüklendi: %s", url)
            return url
    except Exception as e:
        log.warning("Video litterbox'a yüklenemedi: %s", e)

    raise RuntimeError(f"Video hiçbir barındırıcıya yüklenemedi ({p.name})")
