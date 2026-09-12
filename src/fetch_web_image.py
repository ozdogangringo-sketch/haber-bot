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
    "belge", "ilan", "dilekce", "resmigazete", "document"
)

# Filigran basan ücretli stok siteleri ve taranmış ilan formları
YASAKLI_STOK_SITELERI = (
    "vecteezy", "shutterstock", "gettyimages", "alamy", "dreamstime",
    "istockphoto", "depositphotos", "123rf", "stockphoto", "freepik",
    "watermark", "pond5", "canva", "ilan.memurlar.net", "kamuilan",
    "ilan.gov.tr", "advert/documents"
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
            params={"l": "us-en", "o": "json", "q": sorgu, "vqd": vqd, "f": ",,,", "p": "1"},
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
                if img_url and img_url.startswith("http"):
                    sonuclar.append({
                        "image": img_url,
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
    """
    tum_adaylar = []
    gorulen_urller = set()

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

            gorulen_urller.add(img_url)
            tum_adaylar.append(item)

    if not tum_adaylar:
        return None

    # İndirme ve kalite filtresi: atlanacak kadar başarılı görseli atla
    gecerli_sayac = 0
    for aday in tum_adaylar:
        url = aday["image"]
        try:
            cevap = requests.get(url, headers=HEADERS, timeout=12)
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

            if gecerli_sayac < atlanacak:
                gecerli_sayac += 1
                log.info("Fotoğraf alternatifi için önceki aday atlandı (%d/%d): %s", gecerli_sayac, atlanacak, url)
                continue

            log.info("Webden temiz HD basın fotoğrafı onaylandı (%sx%s, %.1f KB): %s",
                     foto.width, foto.height, ham_boyut_kb, url)
            return gorsel_kalite.kristal_netlestir(foto.convert("RGB")), aday
        except Exception as e:
            log.debug("Web görseli indirilemedi (%s): %s", url, e)
            continue

    return None


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


def haber_icin_fotograf(
    haber: Any,
    atlanacak: int = 0,
) -> tuple[Image.Image, dict[str, Any]] | None:
    """
    Haber için en uygun editoryal basın arama kalıbını oluşturup webde gerçek HD fotoğraf arar.

    ⚠️ BAŞLIK ÖNCELİKLİ SORGU (8 Eyl 2026):
    Eskiden `gorsel_konu` (örn. "iPhone") önce geliyordu; bu da çok genel
    sonuçlar üretiyordu. Artık başlıktaki tam ifade (örn. "iPhone 18 Pro
    fiyatları sızdı") birinci sırada; `gorsel_konu` yalnızca destekleyici
    sorgu olarak ikinci sıraya alındı.

    Kişi, sıcak olay, şirket, kurum ve teknoloji kategorilerine göre
    optimize edilmiş sorgular üretir.
    """
    h_dict = dict(haber) if hasattr(haber, "keys") else (haber or {})
    baslik = h_dict.get("baslik_orj") or h_dict.get("orijinal_baslik") or h_dict.get("ig_baslik") or h_dict.get("baslik") or ""
    ulke = h_dict.get("ulke_adi") or ""
    konu = h_dict.get("gorsel_konu") or ""
    temsili = h_dict.get("gorsel_temsili") or ""
    kategori = h_dict.get("kategori") or ""

    # Başlığı temizle (özel karakterleri ve tırnakları ayıkla)
    temiz_baslik = re.sub(r'[^\w\sğüşıöçĞÜŞİÖÇ]', ' ', baslik).strip()
    kelimeler = temiz_baslik.split()
    kisa_baslik = " ".join(kelimeler[:6]) if len(kelimeler) > 6 else temiz_baslik
    # Daha spesifik 4 kelimelik versiyon — model/kişi adlarını korur
    ort_baslik = " ".join(kelimeler[:4]) if len(kelimeler) > 4 else temiz_baslik

    sorgular = []

    # 1. ÖNCELİKLİ: Tam başlık — en spesifik, yanlış fotoğraf riskini minimize eder
    if kisa_baslik:
        sorgular.append(kisa_baslik)
        sorgular.append(f"{kisa_baslik} fotoğraf")

    # 2. Konu / Model / Marka (ikincil — başlıktan daha genel)
    if konu:
        # Başlık konu içeriyorsa tekrar ekleme
        if konu.lower() not in temiz_baslik.lower():
            sorgular.append(konu)
            sorgular.append(f"{konu} press photo")
        else:
            # Başlıkta konu var ama İngilizce press photo ile zenginleştir
            sorgular.append(f"{ort_baslik} press photo")

    # 3. Haber sitesi tarzı sorgular
    if kisa_baslik:
        sorgular.append(f"{kisa_baslik} haber")

    # 4. Temsili + ülke/bağlam (fallback)
    if temsili:
        if ulke:
            sorgular.append(f"{ulke} {temsili} press photo")
        sorgular.append(f"{temsili} news editorial photo")
        sorgular.append(f"{temsili} HD")

    # 5. Kategoriye Özel Zenginleştirme
    if kategori == "ekonomi" and kisa_baslik:
        sorgular.append(f"{kisa_baslik} bloomberg reuters")
    elif kategori in ("teknoloji", "bilim") and konu:
        sorgular.append(f"{konu} launch press kit")

    # Dedupe queries while preserving order
    tekil_sorgular = []
    gorulen = set()
    for sq in sorgular:
        s_temiz = sq.strip()
        if s_temiz and s_temiz.lower() not in gorulen:
            gorulen.add(s_temiz.lower())
            tekil_sorgular.append(s_temiz)

    return fotograf_ara(tekil_sorgular, asgari_genislik=800, asgari_yukseklik=450, atlanacak=atlanacak)
