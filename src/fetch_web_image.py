"""
fetch_web_image.py — Güncel olaylar için webden yüksek çözünürlüklü (HD/4K) gerçek haber fotoğrafları çeker.

Haber sitelerinin kendi og:image'ı düşük çözünürlüklü, kırpık veya kalitesiz olduğunda;
olayın bizzat gerçekleştiği anı gösteren gerçek basın fotoğraflarını web üzerinden arar,
çözünürlük, netlik ve filigransızlık filtrelerinden geçirerek slayt motoruna aktarır.
"""

from __future__ import annotations

import html
import io
import json
import logging
import re
import urllib.parse
from typing import Any
import requests
from PIL import Image, ImageOps

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,tr;q=0.8",
}

# Görsel aramalarında filtrelenecek istenmeyen anahtar kelimeler
ISTENMEYEN_TERIMLER = (
    "logo", "icon", "cartoon", "vector", "drawing", "caricature",
    "chart", "graph", "diagram", "map", "flag", "symbol", "avatar",
    "thumbnail", "poster", "banner", "sticker", "form", "tablo",
    "belge", "ilan", "dilekce", "resmigazete", "document",
    # Mutfak ve yemek terimleri (alakasız trend görsellerini eler)
    "recipe", "tripe", "tarif", "yemek tarifi", "how to cook", "kinds of tripe",
    "cuts of meat"
)

# Başlıktan ayıklanacak anlamsız bağlaç, edat ve dolgu kelimeleri
STOPWORDS = {
    "ve", "ile", "icin", "için", "bu", "su", "şu", "o", "bir", "de", "da", "te", "ta",
    "den", "dan", "ten", "tan", "ye", "ya", "e", "a", "ne", "mi", "mu", "mü", "mı",
    "gibi", "kadar", "sonra", "once", "önce", "yeni", "son", "dakika", "flas", "flaş",
    "haber", "haberi", "haberleri", "gorusme", "aciklama", "duyuru", "belli", "oldu",
    "gelisme", "gelişme", "var", "yok", "iste", "işte", "cok", "çok", "en", "daha",
    "gore", "göre", "karsi", "karşı", "bomba", "sok", "şok", "iddiasi", "iddiası",
    "mesaji", "mesajı", "tepkisi", "aciklamasi", "açıklaması", "karari", "kararı",
    "fotograf", "fotoğraf", "resim", "video", "goruntu", "görüntü", "fotograflari"
}

# Filigran basan ücretli stok siteleri, taranmış ilan formları ve alakasız yemek blogları
YASAKLI_STOK_SITELERI = (
    "vecteezy", "shutterstock", "gettyimages", "alamy", "dreamstime",
    "istockphoto", "depositphotos", "123rf", "stockphoto", "freepik",
    "watermark", "pond5", "canva", "ilan.memurlar.net", "kamuilan",
    "ilan.gov.tr", "advert/documents",
    # Yemek, tarif ve alakasız mutfak blogları (arama motoru trend sızıntılarını engeller)
    "recipes.net", "thespruceeats.com", "chowhound.com", "cookingchew.com",
    "perfectketo.com", "bakeitwithlove.com", "mashed.com", "allrecipes.com",
    "foodnetwork.com", "tasteofhome.com", "epicurious.com", "delish.com",
    "heritagemama.com", "carnivorestyle.com", "simplyrecipes.com",
    "seriouseats.com", "food52.com", "bonappetit.com", "yemek.com",
    "nefisyemektarifleri.com", "lezzet.com.tr"
)


def _ddg_gorsel_ara(sorgu: str) -> list[dict[str, Any]]:
    """DuckDuckGo Image Search üzerinden yüksek çözünürlüklü görselleri listeler."""
    try:
        s = requests.Session()
        res = s.get(
            "https://duckduckgo.com/",
            params={"q": sorgu},
            headers=HEADERS,
            timeout=10,
        )
        m = re.search(r'vqd=([\d-]+)', res.text) or re.search(r'vqd=\"([\d-]+)\"', res.text)
        if not m:
            # Fallback regex for single quotes or json
            m = re.search(r"vqd='([\d-]+)'", res.text) or re.search(r'data-vqd="([\d-]+)"', res.text)
        if not m:
            return []
        vqd = m.group(1)

        r = s.get(
            "https://duckduckgo.com/i.js",
            params={"l": "wt-wt", "o": "json", "q": sorgu, "vqd": vqd, "f": ",,,", "p": "1"},
            headers=HEADERS,
            timeout=10,
        )
        if r.status_code != 200:
            return []
        return r.json().get("results", [])
    except Exception as e:
        log.warning("Web görsel arama hatası (%s): %s", sorgu, e)
        return []


def _bing_gorsel_ara(sorgu: str) -> list[dict[str, Any]]:
    """Bing Görsel Arama üzerinden yüksek çözünürlüklü basın ve haber fotoğraflarını çeker."""
    try:
        q = urllib.parse.quote(str(sorgu).strip())
        url = f"https://www.bing.com/images/search?q={q}&form=HDRSC2&first=1"
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            return []
        matches = re.findall(r'm=\"({[^\"]+})\"', res.text) or re.findall(r'm=(&quot;{[^&]+}&quot;)', res.text)
        sonuclar = []
        for m in matches:
            s = html.unescape(m).strip('\"')
            try:
                d = json.loads(s)
                img_url = (d.get("murl") or "").strip()
                thumb_url = (d.get("turl") or "").strip()
                if img_url and img_url.startswith("http"):
                    sonuclar.append({
                        "image": img_url,
                        "thumbnail": thumb_url,
                        "title": d.get("t") or d.get("desc") or "",
                        "width": d.get("width") or 1200,
                        "height": d.get("height") or 800,
                        "source": "Bing",
                        "url": d.get("purl") or "",
                    })
            except Exception:
                continue
        return sonuclar
    except Exception as e:
        log.warning("Bing görsel arama hatası (%s): %s", sorgu, e)
        return []


from . import gorsel_kalite


# Oturum / tur içi görsel adayı önbelleği (aynı haberin çoklu adayları için mükerrer aramayı önler)
_GORSEL_ADAY_BELLEGI: dict[str, list[tuple[Image.Image, dict[str, Any]]]] = {}


def fotograf_ara(
    sorgular: list[str],
    asgari_genislik: int = 800,
    asgari_yukseklik: int = 450,
    atlanacak: int = 0,
) -> tuple[Image.Image, dict[str, Any]] | None:
    """
    Verilen sorgu listesini sırayla arar; 4K/HD çözünürlük ve kristal netlik kriterini
    karşılayan en uygun editoryal basın fotoğrafını indirir.
    atlanacak parametresine göre sıradaki farklı/alternatif fotoğrafı seçer.
    Adaylar tükendiğinde wrap-around (döngüsel modülo) ile başa sarar, asla None dönüp
    kullanıcı arayüzünü kapatmaz.
    """
    cache_key = "___".join(s.strip().lower() for s in sorgular if s.strip())
    if cache_key in _GORSEL_ADAY_BELLEGI and _GORSEL_ADAY_BELLEGI[cache_key]:
        havuz = _GORSEL_ADAY_BELLEGI[cache_key]
        secilen_idx = atlanacak % len(havuz)
        log.info("Görsel adayı önbellekten çekildi (atlanacak=%d -> indeks=%d/%d)",
                 atlanacak, secilen_idx, len(havuz))
        return havuz[secilen_idx]

    tum_adaylar = []
    gorulen_urller = set()

    # Sorgulardaki anlamlı anahtar kelimeleri topla (bağlamsal alaka denetimi)
    sorgu_kelimeleri = set()
    for s in sorgular:
        for k in re.sub(r'[\'\"«»“”‘’:,!?()\[\]\-_/\\.]', ' ', s.lower()).split():
            if len(k) >= 3 and k not in STOPWORDS:
                sorgu_kelimeleri.add(k)

    for sorgu in sorgular:
        if not sorgu or not str(sorgu).strip():
            continue
        ham_sonuclar = _bing_gorsel_ara(str(sorgu).strip())
        if not ham_sonuclar:
            ham_sonuclar = _ddg_gorsel_ara(str(sorgu).strip())
        if not ham_sonuclar:
            continue

        for item in ham_sonuclar:
            w = item.get("width", 0)
            h = item.get("height", 0)
            img_url = (item.get("image") or "").strip()
            img_url_l = img_url.lower()
            if not img_url or not img_url.startswith("http") or img_url in gorulen_urller:
                continue

            # Asgari boyut eşiği: 16:9 HD (800x450+) veya kare/portre (600x600+)
            if (w < asgari_genislik or h < asgari_yukseklik) and not (w >= 600 and h >= 600):
                continue

            # Filigranlı stok siteleri ele
            if any(yasak in img_url_l for yasak in YASAKLI_STOK_SITELERI):
                continue

            baslik = (item.get("title") or "").lower()
            if any(yasak in baslik for yasak in ISTENMEYEN_TERIMLER):
                continue

            # Aday başlığında sorguyla en az 1 anlamlı kelime örtüşmeli (alakasız yabancı trend/yemekleri eler)
            if sorgu_kelimeleri and not any(sk in baslik for sk in sorgu_kelimeleri):
                continue

            gorulen_urller.add(img_url)
            tum_adaylar.append(item)

    if not tum_adaylar:
        return None

    # İndirme ve kalite filtresi: geçerli adayları topla (en fazla 10 adet)
    gecerli_adaylar: list[tuple[Image.Image, dict[str, Any]]] = []
    for aday in tum_adaylar:
        if len(gecerli_adaylar) >= 10:
            break

        url_listesi = [aday["image"]]
        if aday.get("thumbnail") and aday["thumbnail"] != aday["image"]:
            url_listesi.append(aday["thumbnail"])

        for url in url_listesi:
            try:
                cevap = requests.get(url, headers=HEADERS, timeout=10)
                if cevap.status_code != 200:
                    continue
                ham_boyut_kb = len(cevap.content) / 1024.0
                foto = Image.open(io.BytesIO(cevap.content))
                foto = ImageOps.exif_transpose(foto)
                foto.load()

                # Piksel yoğunluğu, dikey kırpma ölçeği ve Laplacian netlik denetimi
                kaliteli, sebep = gorsel_kalite.gorsel_kalite_denetle(foto, dosya_boyutu_kb=ham_boyut_kb)
                if not kaliteli:
                    log.info("Web görsel adayı elendi (%s): %s", url, sebep)
                    continue

                net_foto = gorsel_kalite.kristal_netlestir(foto.convert("RGB"))
                gecerli_adaylar.append((net_foto, aday))
                log.info("Webden temiz HD basın fotoğrafı onaylandı (%sx%s, %.1f KB): %s",
                         foto.width, foto.height, ham_boyut_kb, url)
                break
            except Exception as e:
                log.debug("Web görseli indirilemedi (%s): %s", url, e)
                continue

    if not gecerli_adaylar:
        return None

    _GORSEL_ADAY_BELLEGI[cache_key] = gecerli_adaylar
    secilen_idx = atlanacak % len(gecerli_adaylar)
    log.info("Web görsel adayı seçildi: %d/%d (atlanacak=%d)",
             secilen_idx + 1, len(gecerli_adaylar), atlanacak)
    return gecerli_adaylar[secilen_idx]


def atif_metni(kayit: dict[str, Any] | None) -> str:
    """
    Web aramasından gelen fotoğraf için atıf satırı üretir.

    ⚠️ NEDEN ZORUNLU (3 Eyl 2026): bu katman 28 Ağustos'ta eklendiğinde
    `arkaplan_sec` atıf yerine boş string dönüyordu. Yayınlanan 10
    web_haber postunun 10'u da ATIFSIZ çıktı — yani görselin nereden
    geldiği hiçbir yerde kayıtlı değildi, ne caption'da ne veritabanında.
    Telif şikayeti gelse kaynağı bulmanın yolu yoktu.

    Atıf üretilemiyorsa çağıran taraf fotoğrafı BASMIYOR: kaynağı
    bilinmeyen bir fotoğrafı yayınlamak, hiç fotoğraf koymamaktan kötü.

    Alan adı yeterli — tam URL caption'da 100+ karakter yiyor ve
    takipçiye bir şey söylemiyor.
    """
    if not kayit:
        return ""
    url = (kayit.get("image") or kayit.get("url") or "").strip()
    if not url:
        return ""
    m = re.match(r"https?://(?:www\.)?([^/:]+)", url)
    if not m:
        return ""
    alan = m.group(1).strip()
    if not alan or "." not in alan:
        return ""
    return f"Foto: {alan}"



CLEAN_PREFIX_RE = re.compile(
    r"^(?:son dakika|flaş gelişme|flaş|canlı|sıcak gelişme|bomba iddia|resmen açıklandı|duyuruldu|dikkat|şok|özel haber)\s*[:!,-]?\s*",
    re.IGNORECASE,
)


def akilli_haber_sorgulari(haber: Any) -> list[str]:
    """
    Haber için en yüksek alaka düzeyine sahip editoryal basın arama kalıplarını üretir.
    Haber başlığı ve Gemini tarafından çıkarılan somut aktör/varlık (gorsel_konu)
    üzerinden doğrudan olay basın fotoğraflarına odaklanır.
    Pexels İngilizce stok terimlerini (gorsel_temsili) asla web aramasına sokmaz.
    """
    h_dict = dict(haber) if hasattr(haber, "keys") else (haber or {})
    baslik = h_dict.get("baslik_orj") or h_dict.get("orijinal_baslik") or h_dict.get("ig_baslik") or h_dict.get("baslik") or ""
    konu = (h_dict.get("gorsel_konu") or "").strip()
    kategori = h_dict.get("kategori") or ""

    sorgular = []

    # 1. Gemini'nin tespit ettiği somut varlık/özne/olay (en temiz ve direkt terim)
    if konu and len(konu) >= 3:
        sorgular.append(konu)
        sorgular.append(f"{konu} haber")

    # 2. Başlıktan gereksiz önekleri ve tıklama tuzaklarını temizle
    b_temiz = CLEAN_PREFIX_RE.sub("", baslik).strip()

    # İki nokta (:) varsa sol taraf genelde özne/aktör, sağ taraf olaydır
    if ":" in b_temiz:
        sol, _, sag = b_temiz.partition(":")
        parcalar = [sol, sag]
    else:
        parcalar = [b_temiz]

    for p in parcalar:
        kelimeler = re.sub(r'[\'\"«»“”‘’:,!?()\[\]\-_/\\.]', ' ', p).split()
        temiz = [k.strip() for k in kelimeler if len(k.strip()) > 1 and k.strip().lower() not in STOPWORDS]
        if temiz:
            if len(temiz) >= 3:
                sorgular.append(" ".join(temiz[:4]))
            sorgular.append(" ".join(temiz[:6]))

    # 3. Kategoriye özel zenginleştirme (press kit / maç / resmi bülten)
    if kategori == "spor" and konu:
        sorgular.append(f"{konu} maç")
    elif kategori in ("teknoloji", "bilim") and konu:
        sorgular.append(f"{konu} tanıtım")

    # Tekilleştirirken sırayı koru
    tekil_sorgular = []
    gorulen = set()
    for sq in sorgular:
        s_temiz = sq.strip()
        if s_temiz and s_temiz.lower() not in gorulen:
            gorulen.add(s_temiz.lower())
            tekil_sorgular.append(s_temiz)

    return tekil_sorgular


def haber_icin_fotograf(
    haber: Any,
    atlanacak: int = 0,
) -> tuple[Image.Image, dict[str, Any]] | None:
    """
    Haber için en uygun editoryal basın arama kalıbını oluşturup webde gerçek HD fotoğraf arar.
    Kişi, sıcak olay, şirket, kurum ve teknoloji kategorilerine göre optimize edilmiş sorgular üretir.
    """
    tekil_sorgular = akilli_haber_sorgulari(haber)
    if not tekil_sorgular:
        return None

    return fotograf_ara(tekil_sorgular, asgari_genislik=800, asgari_yukseklik=450, atlanacak=atlanacak)
