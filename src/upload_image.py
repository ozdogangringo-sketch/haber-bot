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
import logging
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


def _anahtar() -> str:
    a = os.getenv("IMGBB_API_KEY", "").strip()
    if not a:
        raise RuntimeError(
            "IMGBB_API_KEY bulunamadı. imgbb.com/api adresinden alıp "
            ".env dosyasına ekle."
        )
    return a


def _litterboxa_yukle(yol: Path, zaman_asimi: int) -> dict:
    """
    Yedek barındırıcı #1 — catbox'ın GEÇİCİ dosya servisi.

    ⚠️ ANA CATBOX ÇALIŞMIYOR, litterbox ÇALIŞIYOR. GitHub runner'dan
    ölçüldü (21 Ağu 2026): `catbox.moe` veri merkezi IP'lerine
    `HTTP 412 Invalid uploader` veriyor, `litterbox.catbox.moe` aynı
    IP'den sorunsuz kabul ediyor.

    72 saat saklıyor — imgbb ömrümüz (48 saat) ile uyumlu. Instagram
    görseli bir kez indirip kendi CDN'ine kopyaladığı için uzun
    saklama zaten şart değil; süre Telegram önizlemesi ve onay
    penceresi için gerekiyor.
    """
    with open(yol, "rb") as f:
        cevap = requests.post(
            "https://litterbox.catbox.moe/resources/internals/api.php",
            data={"reqtype": "fileupload", "time": "72h"},
            files={"fileToUpload": (yol.name, f, "image/jpeg")},
            timeout=zaman_asimi,
        )
    if cevap.status_code != 200 or not cevap.text.startswith("http"):
        raise RuntimeError(f"litterbox: HTTP {cevap.status_code}: "
                           f"{cevap.text[:120]}")
    return {"url": cevap.text.strip(), "silme_url": None,
            "boyut_kb": round(yol.stat().st_size / 1024, 1)}


def _uguya_yukle(yol: Path, zaman_asimi: int) -> dict:
    """
    Yedek barındırıcı #2 — litterbox da düşerse.

    Runner'dan doğrulandı: yükleme 0.5 sn, dönen URL Instagram'ın
    User-Agent'ıyla indirilebiliyor. Saklama süresi kısa (saatler),
    o yüzden ikinci sırada.
    """
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


# ⚠️ SIRA ÖNEMLİ ve YEREL TESTE GÜVENME. Bu liste GitHub runner'dan
# ölçülerek kuruldu (`scripts/test_barindirici.py`): catbox ve
# tmpfiles ev bağlantısından çalışıyor ama veri merkezi IP'sinden
# reddediliyor. Yeni aday eklemeden önce o scripti Actions'ta çalıştır.
YEDEK_BARINDIRICILAR = (
    ("uguu", _uguya_yukle),
    ("litterbox", _litterboxa_yukle),
)


def gorsel_yukle(yol: Path, ayarlar: dict) -> dict:
    """
    Tek bir görseli yükler.

    Döner: {'url', 'silme_url', 'boyut_kb'}
    Başaramazsa exception fırlatır — çağıran taraf yakalamalı.
    """
    g = ayarlar["imgbb"]
    yol = Path(yol)
    ham = yol.read_bytes()

    son_hata = None
    for deneme in range(1, g["deneme_sayisi"] + 1):
        try:
            cevap = requests.post(
                UC_NOKTA,
                data={
                    "key": _anahtar(),
                    "image": base64.b64encode(ham).decode("ascii"),
                    "name": yol.stem,
                    # Saniye cinsinden ömür. Yayından sonra Instagram kendi
                    # kopyasını tuttuğu için kısa tutmak güvenli.
                    "expiration": g["omur_saniye"],
                },
                timeout=g["zaman_asimi"],
            )
        except requests.RequestException as e:
            son_hata = f"{type(e).__name__}: {e}"
            log.warning("imgbb ağ hatası (deneme %d): %s", deneme, e)
            time.sleep(2 * deneme)
            continue

        if cevap.status_code == 200:
            veri = cevap.json()
            if not veri.get("success"):
                raise RuntimeError(f"imgbb reddetti: {str(veri)[:200]}")
            d = veri["data"]
            return {
                "url": d["url"],
                "silme_url": d.get("delete_url"),
                "boyut_kb": round(len(ham) / 1024, 1),
            }

        son_hata = f"HTTP {cevap.status_code}: {cevap.text[:200]}"
        if cevap.status_code in GECICI_HATALAR:
            time.sleep(2 * deneme)
            continue

        # 400 ama imgbb'nin kendi iç hatası: tekrar denemeye değer.
        govde = (cevap.text or "").lower()
        if any(k in govde for k in GECICI_MESAJLAR):
            log.warning("imgbb iç hatası, %s sn sonra tekrar (%s/%s): %s",
                        GECICI_BEKLEME, deneme, g["deneme_sayisi"],
                        cevap.text[:100])
            time.sleep(GECICI_BEKLEME)
            continue
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
    # 1. uguu.se (Hızlı, Instagram / Meta sunucuları doğrudan indirebiliyor)
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
