"""
fetch_stock.py — Pexels'ten TEMSİLİ fotoğraf çeker.

NEDEN VAR:
    `fetch_photo.py` (Commons) sadece kişi/kurum aramalarında iyi. Haberde
    tanınan biri geçmiyorsa ("Ankara'da ulaşıma zam", "barajların doluluk
    oranı düştü") elimizde gradyandan başka bir şey kalmıyordu.

    Pexels bu boşluğu dolduruyor: konuyu TEMSİL eden bir stok fotoğraf.
    Zam haberine belediye otobüsü, baraj haberine kurumuş göl.

NEDEN PEXELS (haber sitesinin fotoğrafı değil):
    Haber sitelerindeki fotoğraflar AA/Reuters/AFP gibi ajanslara ait ve
    ticari lisanslı. Kaynak yazmak izin yerine geçmiyor — Instagram'da
    telif şikayeti postun kaldırılmasıyla başlar, tekrarında hesap gider.
    Pexels lisansı ise ticari kullanıma açık ve atıf zorunlu değil.
    Yine de atıf yazıyoruz: bedava ve doğru olan bu.

TEMSİLİ GÖRSEL = OLAY FOTOĞRAFI DEĞİL:
    Otobüs fotoğrafı o zammın fotoğrafı değil, konunun görsel karşılığı.
    Takipçi bunu "olayın belgesi" sanmamalı; slayta "ARŞİV GÖRSELİ"
    ibaresi bu yüzden basılıyor (`make_image.yaziyi_bas`).

ARAMA TERİMİ İNGİLİZCE OLMALI:
    Ölçüldü: Pexels'in Türkçe arama sonuçları çok zayıf, çoğu sorguda boş
    dönüyor. Terimi Gemini `gorsel_temsili` alanında İngilizce üretiyor.
"""

from __future__ import annotations

import io
import logging
import os

import requests
from dotenv import load_dotenv
from PIL import Image

log = logging.getLogger(__name__)
load_dotenv()

API = "https://api.pexels.com/v1/search"
ZAMAN_ASIMI = 30

# Slaytlarımız 4:5 dikey. Pexels'ten doğrudan dikey isteyince kırpma payı
# azalıyor, yani fotoğrafın daha çok kısmı görünür kalıyor.
ORIENTASYON = "portrait"

# İlk sonucu körlemesine almıyoruz — Commons'ta bunu yapıp Trump için lise
# yıllığı fotoğrafı almıştık. Birkaç aday alıp puanlıyoruz.
ADAY_SAYISI = 8

# Instagram'da 1080x1350 basıyoruz; bunun altındaki fotoğraf büyütülünce
# bulanıklaşır.
ASGARI_GENISLIK = 1080
ASGARI_YUKSEKLIK = 1350


def _anahtar() -> str:
    k = os.getenv("PEXELS_API_KEY")
    if not k:
        raise RuntimeError(
            "PEXELS_API_KEY .env dosyasında yok. "
            "Eklemek için: python scripts/anahtar_ekle.py PEXELS_API_KEY"
        )
    return k


def _aday_puani(foto: dict) -> int:
    """
    Adayları puanlar.
    
    Yüksek çözünürlüklü ve 4:5 dikey orana iyi kırpılabilecek fotoğraflar önceliklidir.
    """
    genislik, yukseklik = foto.get("width", 0), foto.get("height", 0)
    if (genislik < 1000 and yukseklik < 1000) or min(genislik, yukseklik) < 550:
        return -1

    puan = 0
    oran = genislik / yukseklik
    sapma = abs(oran - 0.8)  # 4:5 oranı idealdir
    puan += max(0, int(40 - sapma * 50))
    puan += min(30, (genislik * yukseklik) // 1_000_000)
    return puan


def fotograf_ara(terim: str, aday_sayisi: int = ADAY_SAYISI,
                 atlanacak: int = 0,
                 kullanilmis: set | None = None) -> dict | None:
    """
    Pexels'te arar, en uygun adayın kaydını döner.
    Önce dikey arar, sonuç yetersizse tüm yüksek çözünürlüklü yönleri tarar.
    """
    headers = {"Authorization": _anahtar()}
    
    ham_fotolar = []
    # 1. Aşama: Dikey formatta ara
    try:
        cevap = requests.get(
            API,
            headers=headers,
            params={"query": terim, "per_page": aday_sayisi, "orientation": "portrait"},
            timeout=ZAMAN_ASIMI,
        )
        if cevap.status_code == 200:
            ham_fotolar.extend(cevap.json().get("photos", []))
    except Exception as e:
        log.warning("Pexels dikey arama hatası (%s): %s", terim, e)

    # 2. Aşama: Dikeyde yeterli kaliteli fotoğraf yoksa genel yüksek çözünürlüklü havuzu ara
    if len(ham_fotolar) < 3:
        try:
            cevap = requests.get(
                API,
                headers=headers,
                params={"query": terim, "per_page": aday_sayisi},
                timeout=ZAMAN_ASIMI,
            )
            if cevap.status_code == 200:
                for f in cevap.json().get("photos", []):
                    if f.get("id") not in [x.get("id") for x in ham_fotolar]:
                        ham_fotolar.append(f)
        except Exception as e:
            log.warning("Pexels genel arama hatası (%s): %s", terim, e)

    adaylar = []
    for foto in ham_fotolar:
        puan = _aday_puani(foto)
        if puan < 0:
            continue
        
        # En net ve hızlı yüklenen yüksek çözünürlüklü kaynak URL'si (large2x veya original)
        src = foto.get("src", {})
        foto_url = src.get("large2x") or src.get("original") or src.get("large")
        if not foto_url:
            continue

        adaylar.append(
            {
                "id": foto.get("id"),
                "url": foto_url,
                "baslik": foto.get("alt") or terim,
                "sanatci": foto.get("photographer", ""),
                "lisans": "Pexels Lisansı",
                "sayfa": foto.get("url", ""),
                "puan": puan,
            }
        )

    if not adaylar:
        log.info("Pexels'te uygun kaliteli fotoğraf bulunamadı: %s", terim)
        return None

    onceki = kullanilmis or set()
    adaylar.sort(key=lambda a: (str(a.get("id")) in onceki, -a["puan"]))
    yeni = sum(1 for a in adaylar if str(a.get("id")) not in onceki)
    if onceki and yeni < len(adaylar):
        log.info("Pexels: %s/%s aday daha önce kullanılmış, sona alındı",
                 len(adaylar) - yeni, len(adaylar))

    if atlanacak:
        log.info("Pexels: %s. aday alınıyor (%s aday var)",
                 atlanacak % len(adaylar) + 1, len(adaylar))
    return adaylar[atlanacak % len(adaylar)]


def fotografi_indir(kayit: dict) -> Image.Image | None:
    """Bulunan fotoğrafı indirip Pillow görüntüsü olarak döner."""
    try:
        cevap = requests.get(kayit["url"], timeout=ZAMAN_ASIMI)
        cevap.raise_for_status()
        return Image.open(io.BytesIO(cevap.content)).convert("RGB")
    except Exception as e:
        log.warning("Pexels fotoğrafı indirilemedi (%s): %s", kayit.get("baslik"), e)
        return None


def atif_metni(kayit: dict) -> str:
    """
    Caption'a eklenecek atıf satırı.

    Pexels lisansı atıf ZORUNLU kılmıyor ama fotoğrafçıya hakkını teslim
    etmek bedava. Ayrıca görselin nereden geldiğini yazmak, takipçinin
    onu olay fotoğrafı sanmasını da önlüyor.
    """
    sanatci = kayit.get("sanatci") or "bilinmeyen"
    return f"Temsili foto: {sanatci} (Pexels)"


def konu_icin_fotograf(terim: str, atlanacak: int = 0,
                       kullanilmis: set | None = None
                       ) -> tuple[Image.Image, dict] | None:
    """
    Tek adımda: ara + indir. Bulamazsa None.

    `fetch_photo.konu_icin_fotograf` ile aynı imza — katman seçici
    ikisini de aynı şekilde çağırabilsin diye bilinçli.
    """
    kayit = fotograf_ara(terim, atlanacak=atlanacak,
                         kullanilmis=kullanilmis)
    if not kayit:
        return None
    gorsel = fotografi_indir(kayit)
    if gorsel is None:
        return None
    return gorsel, kayit
