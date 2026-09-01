"""
fetch_article.py — Haberin TAM METNİNİ çeker

Neden var?
    RSS özetleri "devamı sitemizde" mantığıyla yazılmış teaser'lar.
    Ölçtük: haberlerin %76'sının özeti 200 karakterin altında, bazıları
    cümlenin ortasında kesiliyor.

    Böyle bir teaser'dan 2-3 cümlelik caption isteyince model aradaki
    boşluğu UYDURUYOR. Gerçek bir testte üç farklı Gemini modeli de
    kaynakta olmayan iddialar üretti ("suçlamaları reddetti" gibi) —
    üstelik adı geçen gerçek bir kişi ve ciddi bir suçlama hakkında.

    Bu yüzden habere gidip asıl metni alıyoruz. Model gerçek malzemeyle
    çalışınca uydurma ihtimali ciddi şekilde düşüyor.

Dışarıdan kullanımı:
    from src.fetch_article import makale_metni_cek
    metin = makale_metni_cek("https://...")     # str veya None
"""

from __future__ import annotations

import json
import logging
import re

import requests
from bs4 import BeautifulSoup

from .fetch_news import BASLIKLAR, html_temizle

log = logging.getLogger(__name__)

# Prompt'u şişirmemek için üst sınır. 4000 karakter ~ 1000 kelime,
# bir haber için fazlasıyla yeterli.
AZAMI_UZUNLUK = 4000

# Bu kadarından kısa bir metin "çekemedik" sayılır — muhtemelen
# çerez uyarısı veya "bot musun" sayfası yakalamışız.
ASGARI_UZUNLUK = 200

# Haber gövdesinde işimize yaramayan, neredeyse her sitede olan bloklar
GEREKSIZ_ETIKETLER = [
    "script", "style", "nav", "header", "footer", "aside",
    "form", "iframe", "noscript", "figcaption",
]


def _jsonld_articlebody(corba: BeautifulSoup) -> str | None:
    """
    Çoğu haber sitesi schema.org verisini sayfaya gömüyor:
        <script type="application/ld+json">{"@type":"NewsArticle",
         "articleBody":"..."}</script>

    Bu en güvenilir kaynak — sitenin kendi yapılandırılmış verisi,
    HTML tahmini değil. O yüzden ilk burada arıyoruz.
    """
    for etiket in corba.find_all("script", attrs={"type": "application/ld+json"}):
        if not etiket.string:
            continue
        try:
            veri = json.loads(etiket.string)
        except (json.JSONDecodeError, TypeError):
            continue

        # Yapı üç şekilde gelebiliyor: tek nesne, liste, ya da @graph içinde
        adaylar = []
        if isinstance(veri, dict):
            adaylar = veri.get("@graph") if "@graph" in veri else [veri]
        elif isinstance(veri, list):
            adaylar = veri

        for aday in adaylar or []:
            if not isinstance(aday, dict):
                continue
            govde = aday.get("articleBody")
            if govde and isinstance(govde, str) and len(govde) >= ASGARI_UZUNLUK:
                return govde
    return None


def _paragraf_metni(oge) -> str:
    """
    Bir kapsayıcının içindeki işe yarar paragraf metnini toplar.
    40 karakterden kısa parçalar genelde resim altı yazısı, tarih,
    "Paylaş" gibi arayüz metni — atıyoruz.
    """
    paragraflar = [p.get_text(" ", strip=True) for p in oge.find_all("p")]
    return " ".join(p for p in paragraflar if len(p) > 40)


def _paragraflardan_topla(corba: BeautifulSoup) -> str | None:
    """
    JSON-LD yoksa HTML'den tahmin ediyoruz.

    İki aşama:

    1) En çok paragraf metni barındıran kapsayıcıyı bul. Haber gövdesi
       neredeyse her zaman budur — menü/reklam kutularında da <p> olur
       ama çok daha az.

    2) Sonra İÇERİ doğru in. Dıştaki kapsayıcı gövdeyi içerir ama yanında
       "WhatsApp kanalımıza katılın" gibi promosyon paragraflarını da
       taşır. Bir alt kapsayıcı metnin %90'ını hâlâ taşıyorsa, demek ki
       asıl gövde orası ve dışarıdaki fazlalık kırpılabilir.

    NOT: Burada find_all("p") bilerek özyinelemeli (varsayılan) —
    BBC gibi siteler paragrafları iç içe div'lerin derinine gömüyor,
    sadece doğrudan çocuklara bakmak sıfır sonuç veriyor.
    """
    adaylar = corba.find_all(["article", "main", "div", "section"])
    if not adaylar:
        return None

    en_iyi = max(adaylar, key=lambda e: len(_paragraf_metni(e)))
    en_iyi_uzunluk = len(_paragraf_metni(en_iyi))
    if en_iyi_uzunluk == 0:
        return None

    # Kademe kademe içeri in
    while True:
        daha_dar = None
        for cocuk in en_iyi.find_all(
            ["article", "main", "div", "section"], recursive=False
        ):
            if len(_paragraf_metni(cocuk)) >= en_iyi_uzunluk * 0.9:
                daha_dar = cocuk
                break
        if daha_dar is None:
            break
        en_iyi = daha_dar
        en_iyi_uzunluk = len(_paragraf_metni(en_iyi))

    return _paragraf_metni(en_iyi) or None


def _og_aciklama(corba: BeautifulSoup) -> str | None:
    """
    Son çare: sosyal medya paylaşım açıklaması.
    RSS özetinden genelde biraz daha uzun olur ama yine de kısadır.
    """
    for ozellik in ("og:description", "twitter:description", "description"):
        etiket = corba.find("meta", attrs={"property": ozellik}) or corba.find(
            "meta", attrs={"name": ozellik}
        )
        if etiket and etiket.get("content"):
            return etiket["content"]
    return None


def _kucult(metin: str) -> str:
    """Türkçe'ye dikkat ederek küçült: İ→i, I→ı."""
    return metin.replace("İ", "i").replace("I", "ı").lower()


def _baslikla_ilgili_mi(metin: str, baslik: str) -> bool:
    """
    Çektiğimiz metin gerçekten BU haberin metni mi?

    Neden gerekli: bazı sayfalarda (video sayfası, canlı anlatım, çok
    reklamlı sayfalar) en kalabalık paragraf kümesi yan sütundaki BAŞKA
    bir haber olabiliyor. Gerçek bir örnekte Al Jazeera'dan alakasız bir
    haberin metni geldi.

    Yanlış haberin metnini modele vermek, kısa özet vermekten çok daha
    kötü: model o metne dayanıp kendinden emin ama tamamen alakasız
    bir post üretir. O yüzden şüphe varsa "çekemedik" demeyi tercih
    ediyoruz — çağıran taraf RSS özetine düşer.

    Ölçüt: başlıktaki anlamlı kelimelerin en az üçte biri metinde geçmeli.
    """
    if not baslik:
        return True                     # başlık yoksa kontrol edemeyiz

    govde = _kucult(metin)
    kelimeler = [k for k in re.findall(r"\w+", _kucult(baslik)) if len(k) >= 4]
    if len(kelimeler) < 2:
        return True                     # kontrol için fazla kısa başlık

    gecen = sum(1 for k in kelimeler if k in govde)
    return gecen >= max(2, len(kelimeler) // 3)


def og_gorseli_cek(link: str, zaman_asimi: int = 20) -> str | None:
    """
    Haber sayfasının en kaliteli kapak/ürün fotoğrafını döner.
    
    Arama Hiyerarşisi:
      1. OpenGraph & Twitter kart meta etiketleri (og:image, twitter:image)
      2. Schema.org JSON-LD NewsArticle 'image' alanı (Sitenin sunduğu orijinal tam boy basın görseli)
      3. Makale gövdesindeki ana manşet/ürün görseli (figure, featured-image, article img)
    """
    try:
        cevap = requests.get(link, headers=BASLIKLAR, timeout=zaman_asimi)
        cevap.raise_for_status()
        corba = BeautifulSoup(cevap.content, "html.parser")
    except Exception as e:
        log.warning("Haber görseli için sayfa alınamadı %s: %s", link, e)
        return None

    # İstenmeyen görsel kalıpları (avatar, logo, sayaç, banner reklam, küçük thumbnail, ilan formları)
    YASAK_DESENLER = [
        "avatar", "author", "yazar", "logo", "banner_ad", "pixel",
        "tracker", "spacer", "placeholder", "icon", ".svg", ".gif",
        "share-button", "default_image", "no-image", "-150x150", "-300x",
        "-thumb", "small_thumb", "widget", "advert/documents", "ilan.memurlar",
        "kamuilan", "documents", "tablo", "dilekce"
    ]

    def _gecerli_url_mi(u: str) -> bool:
        if not u or not isinstance(u, str):
            return False
        u_low = u.lower()
        if any(p in u_low for p in YASAK_DESENLER):
            return False
        return u.startswith("http://") or u.startswith("https://") or u.startswith("//")

    def _temiz_url(u: str) -> str:
        u = u.strip()
        if u.startswith("//"):
            u = "https:" + u
        # Anadolu Ajansı (AA) thumbs_ öneklerini kaldırarak ham 5K/4K görsele ulaş
        if "aa.com.tr" in u and "thumbs_" in u:
            u = re.sub(r"thumbs_[a-z0-9_]+_", "", u)
        # NTV / Milliyet / Hürriyet / Sözcü / Habertürk küçültme parametrelerini kaldır
        if any(d in u for d in ("ntv.com.tr", "hurriyet.com.tr", "milliyet.com.tr", "sozcu.com.tr", "haberturk.com")) and "?" in u:
            u = u.split("?")[0]
        # TRT boyut kalıplarını temizle / 1920x1080'e yükselt
        if "trt.com.tr" in u or "trthaber" in u:
            u = re.sub(r"_(?:640x360|800x450|1280x720)", "_1920x1080", u)
        # WordPress vb. thumbnail uzantılarını orijinaline çevir (örn: resim-300x200.jpg -> resim.jpg)
        u = re.sub(r"-\d{3,4}x\d{3,4}(\.[a-zA-Z]{3,4})$", r"\1", u)
        return u

    # 1. JSON-LD Yapılandırılmış Veri (Sitenin doğrudan sunduğu orijinal yüksek çözünürlüklü basın görseli)
    for script in corba.find_all("script", attrs={"type": "application/ld+json"}):
        if not script.string:
            continue
        try:
            veri = json.loads(script.string)
        except Exception:
            continue

        adaylar = []
        if isinstance(veri, dict):
            adaylar = veri.get("@graph") if "@graph" in veri else [veri]
        elif isinstance(veri, list):
            adaylar = veri

        for aday in adaylar or []:
            if not isinstance(aday, dict):
                continue
            img = aday.get("image")
            if isinstance(img, str) and _gecerli_url_mi(img):
                return _temiz_url(img)
            elif isinstance(img, dict) and _gecerli_url_mi(img.get("url", "")):
                return _temiz_url(img["url"])
            elif isinstance(img, list) and img and isinstance(img[0], str) and _gecerli_url_mi(img[0]):
                return _temiz_url(img[0])

    # 2. Makale İçi Orijinal Basın Görseli (figure, featured-image, news-detail)
    for secici in (
        "article figure img", ".news-detail-image img", "main figure img",
        ".featured-image img", ".post-thumbnail img", "figure.wp-block-image img",
        ".entry-content figure img", ".article-body figure img"
    ):
        img_el = corba.select_one(secici)
        if img_el:
            src = img_el.get("src") or img_el.get("data-src") or img_el.get("data-original")
            if src and _gecerli_url_mi(src):
                return _temiz_url(src)

    # 3. Meta Etiketleri (OpenGraph, Twitter kartı)
    for ozellik in ("og:image:secure_url", "og:image", "twitter:image", "twitter:image:src", "thumbnail"):
        etiket = (corba.find("meta", property=ozellik)
                  or corba.find("meta", attrs={"name": ozellik})
                  or corba.find("meta", attrs={"itemprop": "image"}))
        if etiket and etiket.get("content"):
            u = etiket["content"].strip()
            if _gecerli_url_mi(u):
                return _temiz_url(u)

    return None


def hd_gorsel_url_coz(u: str) -> list[str]:
    """
    Haber ajanslarının ve sitelerinin CDN'lerinden sıkıştırılmış küçük thumbnail'ler
    yerine tam çözünürlüklü (4K/2K/1080p) master basın fotoğrafı linklerini türetir.
    """
    if not u or not isinstance(u, str):
        return []
    u = u.strip()
    if u.startswith("//"):
        u = "https:" + u

    adaylar = []

    # 1. Anadolu Ajansı (AA) thumbs_ öneklerini kaldırarak ham 5K/4K görsele ulaş
    if "aa.com.tr" in u and "thumbs_" in u:
        temiz = re.sub(r"thumbs_[a-z0-9_]+_", "", u)
        if temiz != u:
            adaylar.append(temiz)

    # 2. NTV / Milliyet / Hürriyet / Sözcü / Habertürk kırpma parametreleri
    if any(d in u for d in ("ntv.com.tr", "hurriyet.com.tr", "milliyet.com.tr", "sozcu.com.tr", "haberturk.com")) and "?" in u:
        adaylar.append(u.split("?")[0])

    # 3. TRT Haber / Spor boyut kalıpları
    if "trt.com.tr" in u or "trthaber" in u:
        for kucuk in ("_640x360", "_800x450", "_1280x720"):
            if kucuk in u:
                adaylar.append(u.replace(kucuk, "_1920x1080"))
                adaylar.append(u.replace(kucuk, ""))

    # 4. Motorsport TR
    if "motorsport.com" in u:
        for s in ("/s6/", "/s8/", "/s1000/"):
            if s in u:
                adaylar.append(u.replace(s, "/s1600/").replace("/amp/", "/"))
                adaylar.append(u.replace(s, "/s1200/").replace("/amp/", "/"))

    # 5. WordPress boyut kırpıntıları (resim-300x200.jpg -> resim.jpg)
    wp_ham = re.sub(r"-\d{3,4}x\d{3,4}(\.[a-zA-Z]{3,4})$", r"\1", u)
    if wp_ham != u:
        adaylar.append(wp_ham)

    if u not in adaylar:
        adaylar.append(u)

    return adaylar


def makale_metni_cek(
    link: str, baslik: str | None = None, zaman_asimi: int = 20
) -> str | None:
    """
    Haber sayfasını indirip gövde metnini döner.
    Başaramazsa None döner — ASLA exception fırlatmaz.

    `baslik` verilirse, çekilen metnin gerçekten o haberle ilgili olduğu
    doğrulanır. Vermeni tavsiye ederim; yanlış haber metni çekmek
    sessiz ve tehlikeli bir hata.

    Çağıran taraf None gelirse RSS özetiyle devam etmeli
    (ve modele "elinde az bilgi var" demeli).
    """
    try:
        cevap = requests.get(link, headers=BASLIKLAR, timeout=zaman_asimi)
        cevap.raise_for_status()
    except Exception as e:
        log.warning("makale indirilemedi %s: %s", link, e)
        return None

    try:
        corba = BeautifulSoup(cevap.content, "html.parser")
    except Exception as e:
        log.warning("makale ayrıştırılamadı %s: %s", link, e)
        return None

    for etiket in corba.find_all(GEREKSIZ_ETIKETLER):
        etiket.decompose()

    # Güvenilirlik sırasına göre deniyoruz
    metin = _jsonld_articlebody(corba)
    yontem = "json-ld"
    if not metin or len(metin) < ASGARI_UZUNLUK:
        metin = _paragraflardan_topla(corba)
        yontem = "paragraf"
    if not metin or len(metin) < ASGARI_UZUNLUK:
        metin = _og_aciklama(corba)
        yontem = "og:description"

    if not metin:
        return None

    metin = html_temizle(metin)
    metin = re.sub(r"\s+", " ", metin).strip()

    if baslik and not _baslikla_ilgili_mi(metin, baslik):
        log.warning("çekilen metin başlıkla ilgisiz görünüyor, atlanıyor: %s", link)
        return None

    return metin[:AZAMI_UZUNLUK]


def olay_baglami_cek(baslik: str, zaman_asimi: int = 10) -> str | None:
    """
    Kısa haberlerde olayın arka planını, kurtarma detaylarını ve bağlamını
    webden araştırarak zenginleştirir.
    """
    if not baslik or len(baslik) < 10:
        return None
    try:
        res = requests.get(
            "https://duckduckgo.com/html/",
            params={"q": f"{baslik} news"},
            headers=BASLIKLAR,
            timeout=zaman_asimi
        )
        if res.status_code != 200:
            return None
        corba = BeautifulSoup(res.text, "html.parser")
        parcalar = [
            s.get_text(" ", strip=True)
            for s in corba.select(".result__snippet")[:5]
            if len(s.get_text(strip=True)) > 40
        ]
        if parcalar:
            toplam = " ".join(parcalar)
            return re.sub(r"\s+", " ", toplam).strip()[:1500]
    except Exception as e:
        log.warning("olay bağlamı çekilemedi (%s): %s", baslik, e)
    return None
