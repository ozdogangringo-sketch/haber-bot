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

    if len(metin) < ASGARI_UZUNLUK:
        log.info("makale metni çok kısa (%s, %d karakter): %s",
                 yontem, len(metin), link)
        return None

    if baslik and not _baslikla_ilgili_mi(metin, baslik):
        log.warning("çekilen metin başlıkla ilgisiz görünüyor, atlanıyor: %s", link)
        return None

    return metin[:AZAMI_UZUNLUK]
