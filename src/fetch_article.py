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
import time

import requests
from bs4 import BeautifulSoup

from .fetch_news import BASLIKLAR, html_temizle

log = logging.getLogger(__name__)

# Prompt'u şişirmemek için üst sınır. 12000 karakter ~ 2500 kelime,
# uzun siyasi ve kabine konuşmalarındaki tüm gündem maddelerini kapsar.
AZAMI_UZUNLUK = 12000

# Bu kadarından kısa bir metin "çekemedik" sayılır — muhtemelen
# çerez uyarısı veya "bot musun" sayfası yakalamışız.
ASGARI_UZUNLUK = 200
# Çapa yönteminde 'gerçek paragraf' sayılma eşiği (ölçüldü: gövdenin ilk
# paragrafı 135 karakter, foto altyazıları ve 'Abone ol' metinleri kısa).
CAPA_ASGARI_PARAGRAF = 60

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
    cevap = _sayfayi_getir(link, zaman_asimi)
    if cevap is None:
        return None
    try:
        corba = BeautifulSoup(cevap.content, "html.parser")
    except Exception as e:                            # noqa: BLE001
        log.warning("Haber sayfası ayrıştırılamadı %s: %s", link, e)
        return None

    # İstenmeyen görsel kalıpları (avatar, logo, sayaç, banner reklam, küçük thumbnail, ilan formları)
    YASAK_DESENLER = [
        "avatar", "author", "yazar", "logo", "banner_ad", "pixel",
        "tracker", "spacer", "placeholder", "icon", ".svg", ".gif",
        "share-button", "default_image", "no-image", "-150x150", "-300x",
        "-thumb", "small_thumb", "widget", "advert/documents", "ilan.memurlar",
        "kamuilan", "documents", "tablo", "dilekce", "ahaber2.png", "logo-text",
        "/site/v2/i/", "channel_logo", "site_logo"
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
        # DH cache-v2 wrapper'ını çöz ve tam boy orijinal galeri görseline ulaş
        if "donanimhaber.com" in u and "path=" in u:
            m = re.search(r"path=(https?://[^\&]+)", u)
            if m:
                u = m.group(1)
            u = re.sub(r"\d+x\d+_", "", u)
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

    # 0. Donanım Haber Makale İçi Temiz Basın Görselleri ve Galerisi
    # DH, JSON-LD ve og:image alanına kendi kırmızı banner'ını basıyor.
    # Makale galerisindeki fotoğraflar ise orijinal ve temiz lansman fotoğraflarıdır.
    if "donanimhaber.com" in link:
        galeri_adaylar = []
        for img_el in corba.find_all("img"):
            src = img_el.get("src") or img_el.get("data-src") or ""
            if "galeri" in src and _gecerli_url_mi(src):
                u = _temiz_url(src)
                if u not in galeri_adaylar:
                    galeri_adaylar.append(u)
        if galeri_adaylar:
            # -3.jpg veya -4.jpg / -2.jpg genelde ana ürünün en net ve temiz açılı basın karesidir
            # (-1.jpg ortak lansmanlarda telefon veya aksesuara denk gelebiliyor)
            for tercih in ("-3.jpg", "-4.jpg", "-2.jpg", "-5.jpg"):
                for u in galeri_adaylar:
                    if tercih in u:
                        return u
            return galeri_adaylar[0]
        for img_el in corba.find_all("img"):
            src = img_el.get("src") or img_el.get("data-src") or ""
            if "/src/" in src and _gecerli_url_mi(src):
                return _temiz_url(src)

    # 1. JSON-LD Yapılandırılmış Veri (Sitenin doğrudan sunduğu orijinal yüksek çözünürlüklü basın görseli)
    for script in corba.find_all("script", attrs={"type": "application/ld+json"}):
        text = script.string or script.text
        if not text:
            continue
        try:
            veri = json.loads(text)
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
            # Yalnızca haber/makale şemalarını kabul et, Organization/Person/WebSite logolarını atla
            tip = str(aday.get("@type", "")).lower()
            if tip in ("organization", "newsmediaorganization", "website", "person", "breadcrumblist"):
                continue

            img = aday.get("image")
            aday_urller = []
            if isinstance(img, str):
                aday_urller.append(img)
            elif isinstance(img, dict):
                u = img.get("contentUrl") or img.get("url")
                if isinstance(u, str):
                    aday_urller.append(u)
            elif isinstance(img, list):
                for eleman in img:
                    if isinstance(eleman, str):
                        aday_urller.append(eleman)
                    elif isinstance(eleman, dict):
                        u = eleman.get("contentUrl") or eleman.get("url")
                        if isinstance(u, str):
                            aday_urller.append(u)

            for u in aday_urller:
                if _gecerli_url_mi(u):
                    return _temiz_url(u)

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


def _capadan_topla(corba: BeautifulSoup, baslik: str | None = None) -> str | None:
    """
    Haberin KENDİ BAŞLIĞINI (h1) çapa alıp gövdeyi bulur.

    ⚠️ NİYE GEREKTİ (6 Eyl 2026, kullanıcı fikri). `_paragraflardan_topla`
    "en çok paragraf metni taşıyan kutuyu" seçiyor. Bazı sitelerde en
    uzun metin haber değil, sayfanın altındaki YASAL UYARI oluyor:
    borsaningundemi.com'da feragatname 2081 karakter, haberin kendisi
    667. Sonuç: alaka kapısı feragatnameyi doğru şekilde reddediyor ama
    haber de kayboluyor ve model 123 karakterlik RSS özetiyle baş başa
    kalıyor (ölçüldü — detay metni 895 yerine 223 karakter çıkıyor).

    ⚠️ "ALAKALI KUTULAR ARASINDAN EN BÜYÜĞÜ" ÇÖZMÜYOR — denendi ve
    ELENDİ: o kural 1019 karakterlik "diğer haberler" listesini seçti,
    çünkü o listede de aynı haberin başlığı geçiyor ve alaka kapısı
    kendi kendini onaylıyor. (Görsel tarafındaki `gorsel_konu` = Trump
    döngüselliğinin aynısı.)

    ⚠️ ASIL FİKİR "SONRAKİ BAŞLIĞA KADAR AL"DI ama ölçüldü: bu sayfada
    haberden sonra HİÇ başlık etiketi yok — 42 "diğer haber" `<a>`
    bağlantısı, `<h2>` değil. Duracak yer yapıdan gelmeli: paragrafın
    KENDİ KUTUSU, eksik olan "sonraki başlık"ın yerini tutuyor.

    ⚠️ Paragraf tek başına alaka testine SOKULMUYOR: başlıktaki
    kelimeler tek bir paragrafa sığmıyor ("açıklama" ≠ "açıkladı") ve
    test gerçek gövdeyi eliyordu. Alaka, toplanan kutunun TAMAMINDA
    ölçülüyor — çağıran taraf zaten bunu yapıyor.
    """
    h1 = corba.find("h1")
    if h1 is None:
        return None

    for p in h1.find_all_next("p"):
        if len(p.get_text(" ", strip=True)) < CAPA_ASGARI_PARAGRAF:
            continue
        kutu = p.parent
        if kutu is None:
            return None
        metin = _paragraf_metni(kutu)
        # Paragraf tek başına bir sarmalayıcıdaysa bir üst kata çık
        if len(metin) < ASGARI_UZUNLUK and kutu.parent is not None:
            ustu = _paragraf_metni(kutu.parent)
            if len(ustu) > len(metin):
                metin = ustu
        return metin or None
    return None


# Kalıcı HTTP hataları — tekrar denemek zaman kaybı.
# ⚠️ Investing.com bize 403 dönüyor (15/15 başarısızlığın sebebi); her
# haberde 3 kez denemek her çalışmaya boşuna saniyeler ekler.
KALICI_HTTP = {400, 401, 403, 404, 410, 451}


def _sayfayi_getir(link: str, zaman_asimi: int = 20,
                   deneme_adedi: int = 3, bekleme: int = 3):
    """
    Haber sayfasını indirir; GEÇİCİ hatada tekrar dener.

    ⚠️ NİYE GEREKTİ (7 Eyl 2026): hem gövde çekimi hem og:image çekimi
    TEK denemeydi. Ölçüldü — "başka fotoğraf" basılmamış 12 stok
    postunun 5'inde haberin og:image'ı bugün sorunsuz geliyor ve kalite
    kapısını geçiyor; yani üretim anında geçici bir ağ hatası yaşanmış
    ve post sessizce stok fotoğrafa düşmüş. Aynı desen gövde çekiminde
    de görüldü (kayıtta 0 karakter, bugün 513-2246 karakter).
    ⚠️ Aynı gün video karelerinde de yeniden deneme yokluğu bulunmuştu —
    projede geçici ağ hatasına karşı korunmayan üçüncü yol buydu.
    """
    son_hata = None
    for deneme in range(1, deneme_adedi + 1):
        try:
            cevap = requests.get(link, headers=BASLIKLAR, timeout=zaman_asimi)
            cevap.raise_for_status()
            return cevap
        except requests.HTTPError as e:
            kod = getattr(e.response, "status_code", 0)
            if kod in KALICI_HTTP:
                log.warning("sayfa alınamadı (kalıcı HTTP %s): %s", kod, link)
                return None
            son_hata = e
        except Exception as e:                        # noqa: BLE001
            son_hata = e
        if deneme < deneme_adedi:
            time.sleep(bekleme * deneme)
    log.warning("sayfa alınamadı (%d deneme) %s: %s",
                deneme_adedi, link, str(son_hata)[:120])
    return None


# ----------------------------------------------------------------------
# KUYRUK TEMİZLİĞİ — okur yorumu ve sayfa altı şablonu gövdeye girmesin
# ----------------------------------------------------------------------
#
# ⚠️ NEDEN GEREKTİ (18 Eyl 2026). Bir prompt testi sırasında görüldü:
# çekilen gövdenin sonunda OKUR YORUMLARI vardı —
#     "Allah'ım ülkemizi korusun", "Güvenenlere verin makarnayı yesinler",
#     "Bu adamin dediklerine 1 kisi bile itibar etmiyor"
# Bunlar iki yerde birden zarar veriyor:
#   1) Model bunları KAYNAK sanıyor ve bir okur yorumunu haber
#      gibi aktarabiliyor.
#   2) `dogrula` bu metni doğrulama kaynağı olarak kullanıyor, yani
#      yorumda geçen bir sayı "kaynakta var" sayılıyor.
#
# ⚠️ ÖLÇÜLDÜ, SEYREK AMA GERÇEK: 213 gövdeli haberin 23'ünde (%11)
# yatırım uyarısı şablonu var ve sonrasında medyan yalnızca 77
# karakter kalıyor — ama BİR vakada 4.197 karakterlik yorum bölümü
# gövdeye girmişti. Yani sık değil, olduğunda büyük.
#
# ⚠️ KESME NOKTASI ÖZGÜL OLMALI. Genel kelimeler ("yorum", "paylaş")
# makalenin İÇİNDE de geçebiliyor; buradaki desenler yalnızca sayfa
# altı şablonlarında bulunan tam ifadeler. Ayrıca kesme yalnızca
# metnin SON ÜÇTE BİRİNDE aranıyor: bir haber gerçekten "tüm hakları
# saklıdır" diye başlıyorsa gövdenin tamamı silinmesin.
# ⚠️ DESENLER İKİ KADEMELİ — konum kuralı hepsine aynı uygulanamaz.
#
# KESİN: yalnızca makalenin BİTTİĞİ yerde bulunan yasal uyarı ve yorum
# başlıkları. Bunlar makalenin İÇİNDE asla geçmez, o yüzden nerede
# görülürse görülsün kesiliyor.
# ⚠️ Bu ayrım ölçümden doğdu: ilk yazımda tek kademe vardı ve kesme
# yalnızca metnin son %45'inde aranıyordu. 4.249 karakterlik okur
# yorumu taşıyan #197576'da uyarı metnin **%32'sindeydi** (gerçek
# makale 1.960 karakter, kalanı yorum) ve hiç kesilmedi.
_KUYRUK_KESIN = re.compile(
    r"(sayfada yer alan bilgiler tavsiye niteli[gğ]i ta[sş][ıi]may[ıi]p"
    r"|yat[ıi]r[ıi]m dan[ıi][sş]manl[ıi][gğ][ıi] kapsam[ıi]nda de[gğ]ildir"
    r"|\bt[uü]m yorumlar\b|\byorum yaz\b|\bokur yorumlar[ıi]\b"
    r"|izinsiz ve kaynak g[oö]sterilmeden)",
    re.IGNORECASE,
)

# ZAYIF: makalenin içinde de geçebilen ifadeler ("ilgili haberler" bir
# cümlede kullanılabilir). Bunlar yalnızca metnin SON YARISINDA kesiyor.
_KUYRUK_ZAYIF = re.compile(
    r"(ilgili haberler|di[gğ]er haberler|bunlar da ilgin"
    r"|bizi takip edin|abone ol)",
    re.IGNORECASE,
)

# Kesimden sonra en az bu kadar metin kalmalı; altına düşüyorsa
# kesme güvenilmez sayılıp iptal ediliyor.
_KUYRUK_ASGARI_KALAN = 300


def kuyrugu_kes(metin: str | None) -> str:
    """
    Gövdenin sonundaki okur yorumu / sayfa altı şablonunu atar.

    İki kademeli: kesin işaretler her yerde, zayıf işaretler yalnızca
    metnin son yarısında kesiyor. Bkz. yukarıdaki not.
    """
    m = (metin or "").strip()
    if len(m) < 400:
        return m

    adaylar = []
    e = _KUYRUK_KESIN.search(m)
    if e:
        adaylar.append(e)
    esik = int(len(m) * 0.55)
    for z in _KUYRUK_ZAYIF.finditer(m):
        if z.start() >= esik:
            adaylar.append(z)
            break
    if not adaylar:
        return m

    eslesme = min(adaylar, key=lambda x: x.start())
    kesilen = m[: eslesme.start()].strip()
    # ⚠️ Kesim gövdeyi kullanılamaz hâle getiriyorsa iptal. Mutlak bir
    # alt sınır kullanılıyor, ORAN DEĞİL: yorum bölümü gövdenin %68'i
    # olabiliyor ve oransal bir kural tam da o vakayı engelliyordu.
    if len(kesilen) < _KUYRUK_ASGARI_KALAN:
        return m
    if len(m) - len(kesilen) > 50:
        log.info("gövde kuyruğu kesildi: %d karakter atıldı (%r)",
                 len(m) - len(kesilen), eslesme.group(0)[:40])
    return kesilen


def _kirp_baslik_oncelikli(metin: str, baslik: str | None, azami: int = AZAMI_UZUNLUK) -> str:
    """Metin azami sınırı aşıyorsa, başlıktaki anahtar kelimeleri içeren paragrafları korur."""
    if len(metin) <= azami:
        return metin
    if not baslik:
        return metin[:azami]

    anahtarlar = [k for k in re.findall(r"\w+", _kucult(baslik)) if len(k) >= 4]
    if not anahtarlar:
        return metin[:azami]

    paragraflar = [p.strip() for p in metin.split(". ") if len(p.strip()) > 30]
    secilen = []
    toplam = 0
    # Önce başlıktaki kelimeleri içeren kısımları ve giriş kısmını dahil et
    for p in paragraflar:
        p_k = _kucult(p)
        eslesiyor = any(k in p_k for k in anahtarlar)
        if eslesiyor or toplam < azami // 2:
            if toplam + len(p) < azami:
                secilen.append(p)
                toplam += len(p) + 2

    return ". ".join(secilen) if secilen else metin[:azami]


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
    cevap = _sayfayi_getir(link, zaman_asimi)
    if cevap is None:
        return None

    try:
        corba = BeautifulSoup(cevap.content, "html.parser")
    except Exception as e:
        log.warning("makale ayrıştırılamadı %s: %s", link, e)
        return None

    for etiket in corba.find_all(GEREKSIZ_ETIKETLER):
        etiket.decompose()

    # Güvenilirlik sırasına göre deniyoruz
    def _duzelt(ham: str) -> str:
        return re.sub(r"\s+", " ", html_temizle(ham)).strip()

    # ⚠️ REDDEDİLEN ADAY ZİNCİRİ BİTİRMİYOR — ÖNCE ELE, SONRA SEÇ.
    # Eski akışta tek bir aday seçilip en sonda alaka kapısından
    # geçiriliyordu; kapı reddedince "gövde yok" deniyor ve SIRADAKİ
    # YÖNTEM HİÇ DENENMİYORDU. borsaningundemi.com'da tam bu oldu:
    # "en büyük kutu" yasal uyarıyı (2081 kr) seçti, kapı onu haklı
    # olarak reddetti ve haberin kendi gövdesi (667 kr) hiç aranmadı.
    # Artık her yöntem kendi kapısından geçiyor; biri elenirse
    # diğerine geçiliyor.
    #
    # ⚠️ ÇAPA NEDEN PARAGRAFTAN SONRA: 22 kaynakla ölçüldü (6 Eyl 2026).
    # Çapa öne alındığında 0 kazanç / 5 GERİLEME çıktı — NTV Gündem ve
    # Habertürk Gündem'de sonuç sıfıra düştü. Çapa, paragraf yöntemini
    # değiştirmiyor; yalnızca o BAŞARISIZ olduğunda devreye giriyor.
    for uretici, ad in (
        (lambda: _jsonld_articlebody(corba), "json-ld"),
        (lambda: _paragraflardan_topla(corba), "paragraf"),
        (lambda: _capadan_topla(corba, baslik), "çapa"),
    ):
        try:
            aday = uretici()
        except Exception as e:                        # noqa: BLE001
            log.warning("%s yöntemi patladı %s: %s", ad, link, e)
            continue
        if not aday or len(aday) < ASGARI_UZUNLUK:
            continue
        temiz = _duzelt(aday)
        if baslik and not _baslikla_ilgili_mi(temiz, baslik):
            log.info("%s yöntemi başlıkla ilgisiz metin verdi, sıradaki "
                     "yöntem deneniyor: %s", ad, link)
            continue
        return _kirp_baslik_oncelikli(kuyrugu_kes(temiz), baslik, AZAMI_UZUNLUK)

    # Son çare: og:description. ASGARI_UZUNLUK aranmıyor — bu alan zaten
    # kısa olur ve RSS özetinden iyi bir şey vermese de zarar vermez.
    og = _og_aciklama(corba)
    if og:
        temiz = _duzelt(og)
        if not baslik or _baslikla_ilgili_mi(temiz, baslik):
            return _kirp_baslik_oncelikli(kuyrugu_kes(temiz), baslik, AZAMI_UZUNLUK)

    log.warning("gövde çekilemedi (hiçbir yöntem tutmadı): %s", link)
    return None


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
