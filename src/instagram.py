"""
instagram.py — ADIM 4b
Carousel postu Instagram Graph API ile yayınlar.

CAROUSEL AKIŞI (tekli posttan farklı, üç aşamalı):

    1. Her görsel için ayrı container:
         POST /{ig_user_id}/media
              image_url=..., is_carousel_item=true      -> child_id
    2. Çocukları birleştiren carousel container:
         POST /{ig_user_id}/media
              media_type=CAROUSEL, children=[...], caption=...
                                                        -> carousel_id
    3. Yayınla:
         POST /{ig_user_id}/media_publish
              creation_id=carousel_id                   -> post_id

INSTAGRAM'IN KURALLARI (uyulmazsa API reddediyor):
    * Sadece JPEG. PNG kabul edilmiyor.
    * Görsel herkese açık bir URL'de olmalı (bu yüzden imgbb var).
    * Carousel'de 2-10 görsel. Tek görselle carousel olmuyor.
    * 24 saatte en fazla 100 post.
    * Container'lar 24 saat sonra kendiliğinden ölüyor.

HESAP GÜVENLİĞİ — BU KORUMAYI KALDIRMA:
    Jetonun birden fazla sayfaya erişimi var (DailyBrief, Animarch Studio,
    Edm Yapı). İlk yazılan script "son bulduğu" hesabı seçmiş ve emlak
    şirketinin hesabını hedeflemişti. Hedef hesap config.yaml'de AÇIKÇA
    yazılı; eşleşme bulunamazsa kod yayın yapmayı REDDEDİYOR.
"""

from __future__ import annotations

import logging
import os
import re
import time

import requests
from dotenv import load_dotenv

log = logging.getLogger(__name__)
load_dotenv()

TABAN = "https://graph.facebook.com"
GECICI_HATALAR = {429, 500, 502, 503, 504}

# ⚠️ HTTP KODUNA BAKMAK YETMİYOR — bazı geçici hatalar 400 ile geliyor.
#
# 2207003 "Medyanın indirilmesi çok uzun sürüyor": Instagram görseli
# imgbb'den kendisi çekiyor ve o çekme zaman aşımına uğruyor. Cevapta
# `is_transient: false` yazıyor ama YALAN — aynı URL saniyeler sonra
# sorunsuz iniyor. 17 Ağu 2026'da akşam turu 2. container'da bunun
# yüzünden düştü, hiç tekrar denenmeden.
GECICI_ALT_KODLAR = {2207003, 2207032, 2207052}

# Medya indirme hatasında daha uzun bekliyoruz: sorun bizim isteğimizde
# değil, imgbb ile Instagram arasındaki aktarımda. 2 saniye sonra tekrar
# sormak aynı yükün üstüne binmek oluyor.
MEDYA_BEKLEME_SANIYE = 15

# ⚠️ MEDYA HATALARINDA DAHA ÇOK DENEME.
#
# 18 Ağu 2026: bir son dakika turu 2207052 ("medya indirme başarısız")
# ile düştü, 3 deneme yetmedi. İki dakika sonra elle denendiğinde 5
# görselin 5'i de sorunsuz yüklendi — yani sorun görselde değil, karşı
# tarafın o anki durumundaydı.
#
# Threads'te aynı desen ölçülmüştü: bekleme süresini uzatmak tek başına
# çözmüyor (10/20/30 sn denendi, sonuç hata/başarı/hata), asıl güvence
# DENEME SAYISI. Bu yüzden medya hatalarında sabit bekleme + daha çok
# deneme kullanıyoruz.
MEDYA_AZAMI_DENEME = 6


def _jeton() -> str:
    j = os.getenv("IG_ACCESS_TOKEN", "").strip()
    if not j:
        raise RuntimeError("IG_ACCESS_TOKEN bulunamadı (.env)")
    return j


def _kullanici_id() -> str:
    k = os.getenv("IG_USER_ID", "").strip()
    if not k:
        raise RuntimeError("IG_USER_ID bulunamadı (.env)")
    return k


def _alt_kod(cevap) -> int | None:
    """Graph API hata cevabından `error_subcode`'u çıkarır."""
    try:
        return cevap.json().get("error", {}).get("error_subcode")
    except Exception:
        # Hata cevabı JSON olmayabilir; o zaman alt kod da yoktur.
        return None


def _istek(yontem: str, yol: str, ayarlar: dict, **parametreler) -> dict:
    """
    Graph API çağrısı. Geçici hatalarda bekleyip tekrar dener.

    Jeton parametrelere ekleniyor ama loga ASLA yazılmıyor — hata
    mesajlarında URL basmıyoruz, sadece yol ve durum kodu.
    """
    g = ayarlar["instagram"]
    url = f"{TABAN}/{g['api_surumu']}{yol}"
    parametreler["access_token"] = _jeton()

    # Deneme sayısı config'den geliyordu ama kod onu HİÇ OKUMUYORDU;
    # `range(1, 4)` sabitti ve `instagram.deneme_sayisi` ölü ayardı.
    azami = max(int(g.get("deneme_sayisi", 3)), MEDYA_AZAMI_DENEME)
    son_hata = None
    for deneme in range(1, azami + 1):
        try:
            # GET'te parametreler query string'e, POST'ta gövdeye gider.
            # İkisini karıştırmak "(#200) Provide valid app ID" gibi
            # alakasız görünen bir hataya yol açıyor: Graph API gövdedeki
            # parametreleri GET'te hiç okumuyor, jetonu görmemiş sanıyor.
            if yontem.upper() == "GET":
                cevap = requests.get(
                    url, params=parametreler, timeout=g["zaman_asimi"]
                )
            else:
                cevap = requests.post(
                    url, data=parametreler, timeout=g["zaman_asimi"]
                )
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
            # SABİT bekleme: bu bir hız sınırı değil, karşı tarafın
            # kararsızlığı. Artan bekleme yalnızca toplam süreyi
            # şişiriyor, başarı şansını artırmıyor (Threads'te ölçüldü).
            log.warning("medya indirme hatası, %s sn sonra tekrar (%s/%s)",
                        MEDYA_BEKLEME_SANIYE, deneme, azami)
            time.sleep(MEDYA_BEKLEME_SANIYE)
            continue
        break

    raise RuntimeError(f"Graph API hatası ({yol}): {son_hata}")


def hesabi_dogrula(ayarlar: dict) -> dict:
    """
    .env'deki IG_USER_ID'nin config'de yazan hesap olduğunu doğrular.

    Yayın öncesi HER ZAMAN çağrılmalı. Yanlış hesaba post atmak geri
    alınabilir ama itibar zararı geri alınamaz.
    """
    hedef = (ayarlar["instagram"].get("hesap_kullanici_adi") or "").strip().lstrip("@")
    if not hedef:
        raise RuntimeError(
            "config.yaml → instagram.hesap_kullanici_adi boş. "
            "Hedef hesap açıkça yazılmadan yayın yapılmaz."
        )

    d = _istek("GET", f"/{_kullanici_id()}", ayarlar, fields="id,username,name")
    if d.get("username") != hedef:
        raise RuntimeError(
            f"HESAP UYUŞMUYOR — yayın durduruldu.\n"
            f"  config.yaml hedefi : @{hedef}\n"
            f"  .env IG_USER_ID'si : @{d.get('username')}\n"
            f"Yanlış hesaba post gitmesin diye kod burada duruyor."
        )
    return d


def yayin_kotasi(ayarlar: dict) -> dict:
    """24 saatlik post kotası. Instagram sınırı 100."""
    d = _istek(
        "GET", f"/{_kullanici_id()}/content_publishing_limit", ayarlar,
        fields="config,quota_usage",
    )
    kayit = (d.get("data") or [{}])[0]
    return {
        "kullanilan": kayit.get("quota_usage", 0),
        "azami": (kayit.get("config") or {}).get("quota_total", 100),
    }


def _container_bekle(container_id: str, ayarlar: dict) -> None:
    """
    Container'ın işlenmesini bekler.

    Instagram görseli indirip işliyor; hazır olmadan publish çağırırsan
    hata veriyor. 10 görselli carousel'de bu birkaç saniye sürebiliyor.
    """
    g = ayarlar["instagram"]
    for _ in range(g["hazir_azami_deneme"]):
        d = _istek("GET", f"/{container_id}", ayarlar,
                   fields="status_code,status")
        durum = d.get("status_code")
        if durum == "FINISHED":
            return
        if durum == "ERROR":
            raise RuntimeError(f"container işlenemedi: {d.get('status')}")
        time.sleep(g["hazir_bekleme_saniye"])

    raise RuntimeError(f"container zamanında hazır olmadı: {container_id}")


def carousel_yayinla(
    gorsel_urlleri: list[str], caption: str, ayarlar: dict
) -> str:
    """
    Carousel postu yayınlar, Instagram post id'sini döner.

    Yayın öncesi hesap doğrulaması ve kota kontrolü yapılıyor.
    """
    if not 2 <= len(gorsel_urlleri) <= 10:
        raise ValueError(
            f"carousel 2-10 görsel ister, {len(gorsel_urlleri)} verildi"
        )

    hesap = hesabi_dogrula(ayarlar)
    kota = yayin_kotasi(ayarlar)
    if kota["kullanilan"] >= kota["azami"]:
        raise RuntimeError(
            f"24 saatlik yayın kotası dolu ({kota['kullanilan']}/{kota['azami']})"
        )
    log.info("hedef @%s | kota %s/%s", hesap["username"],
             kota["kullanilan"], kota["azami"])

    # --- 1) Her görsel için çocuk container ---
    cocuklar = []
    for i, url in enumerate(gorsel_urlleri, 1):
        d = _istek("POST", f"/{_kullanici_id()}/media", ayarlar,
                   image_url=url, is_carousel_item="true")
        cocuklar.append(d["id"])
        log.info("container %d/%d hazırlandı", i, len(gorsel_urlleri))

    # Çocukların hepsi işlenene kadar bekle. Publish sırasında biri hazır
    # değilse tüm carousel patlıyor.
    for cocuk in cocuklar:
        _container_bekle(cocuk, ayarlar)

    # --- 2) Carousel container ---
    d = _istek("POST", f"/{_kullanici_id()}/media", ayarlar,
               media_type="CAROUSEL",
               children=",".join(cocuklar),
               caption=caption)
    carousel_id = d["id"]
    _container_bekle(carousel_id, ayarlar)

    # --- 3) Yayınla ---
    d = _istek("POST", f"/{_kullanici_id()}/media_publish", ayarlar,
               creation_id=carousel_id)
    post_id = d["id"]
    log.info("YAYINLANDI: %s", post_id)
    return post_id


def story_yayinla(gorsel_url: str, ayarlar: dict) -> str:
    """
    Story yayınlar, story id'sini döner.

    KISITLAR (Instagram'ın, bizim değil):
      * Sticker EKLENEMİYOR — link, mention, anket, "kaydır" oku hiçbiri
        API'den konulamıyor. Story düz görsel olarak gidiyor, bu yüzden
        tek başına anlamlı olmak zorunda (postu işaret edemiyoruz).
      * 9:16 (1080x1920) bekleniyor. 4:5 gönderilirse Instagram kırpıyor
        ya da bant ekliyor; ikisi de kötü duruyor.
      * 24 saat sonra kendiliğinden kayboluyor.

    Story yayını post kotasından SAYILIYOR (24 saatte 100), ama günde
    3 post + 3 story bile sınırın çok altında.
    """
    hesap = hesabi_dogrula(ayarlar)

    d = _istek("POST", f"/{_kullanici_id()}/media", ayarlar,
               media_type="STORIES", image_url=gorsel_url)
    container = d["id"]
    _container_bekle(container, ayarlar)

    d = _istek("POST", f"/{_kullanici_id()}/media_publish", ayarlar,
               creation_id=container)
    story_id = d["id"]
    log.info("story yayınlandı (@%s): %s", hesap["username"], story_id)
    return story_id


def son_yayinlanan_basliklar(ayarlar: dict, adet: int = 25) -> list[str]:
    """
    Instagram'da GERÇEKTEN yayınlanmış postların manşetlerini döndürür.

    ⚠️ NEDEN GEREKTİ (20 Ağu 2026): mükerrer engeli veritabanındaki
    `durum='yayinlandi'` kayıtlarına bakıyordu ve veritabanı yanlış
    olabiliyor. Ölçüldü — "Merkez Bankası rezervleri" 17:47'de,
    "TUFAN Kamikaze İDA" 17:19'da Instagram'da yayınlandı ama DB'de
    ikisinin de hiçbir kaydı 'yayinlandi' değildi; ikisi de akşam
    turuna yeniden girdi ve kullanıcı fark etti.

    Aynı ders CLAUDE.md 1u'da zaten yazılıydı: bir haberin yayınlanıp
    yayınlanmadığının kesin cevabı burada, veritabanında değil.

    Caption biçimi "1. Manşet / 2. Manşet …" olduğu için numaralı
    satırlar ayrı ayrı çıkarılıyor — tek postta 10 haber olabiliyor
    ve hepsi ayrı ayrı karşılaştırılmalı.
    """
    try:
        cevap = _istek("GET", f"/{_kullanici_id()}/media", ayarlar,
                       fields="caption,timestamp", limit=adet)
    except Exception as e:
        # Ağ/jeton hatası mükerrer denetimini DURDURMAMALI — veritabanı
        # katmanı yine çalışıyor, burası ek güvence.
        log.warning("Instagram geçmişi okunamadı (%s); "
                    "mükerrer denetimi yalnızca veritabanına bakacak", e)
        return []

    basliklar = []
    for post in cevap.get("data", []):
        # ⚠️ HER POST KENDİ İÇİNDE değerlendirilmeli. İlk yazımda
        # "numarasız caption'ın ilk satırı manşettir" kuralı GLOBAL
        # listeye bakıyordu; ilk posttan sonra liste hep dolu olduğu
        # için tekil postların manşetleri HİÇ okunmadı ve "Merkez
        # Bankası rezervleri" ile "TUFAN Kamikaze İDA" gözden kaçtı.
        post_basliklari: list[str] = []
        for satir in (post.get("caption") or "").splitlines():
            satir = satir.strip()
            if not satir:
                continue
            # "1. Manşet" / "10. Manşet" -> carousel turunun manşetleri
            eslesme = re.match(r"^\d{1,2}[\.\)]\s+(.{15,})$", satir)
            if eslesme:
                post_basliklari.append(eslesme.group(1).strip())
                continue
            if post_basliklari:
                continue
            # Tekil postun caption'ı numarasız başlıyor: ilk anlamlı
            # satır manşettir. Etiket satırlarını ("🔴 SON DAKİKA",
            # hashtag'ler) atlıyoruz, yoksa manşet yerine onlar geçer.
            sade = satir.lstrip("🔴🚨⚡️ ").strip()
            if len(sade) > 25 and not sade.startswith("#") \
                    and sade.upper() != sade:
                post_basliklari.append(sade)
        basliklar += post_basliklari
    return basliklar


def post_baglantisi(post_id: str, ayarlar: dict) -> str:
    """Yayınlanan postun permalink'i — Telegram'da göstermek için."""
    try:
        d = _istek("GET", f"/{post_id}", ayarlar, fields="permalink")
        return d.get("permalink", "")
    except Exception as e:
        log.warning("permalink alınamadı: %s", e)
        return ""
