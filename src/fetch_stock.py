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
    Adayları sıralar. Yüksek puan = daha uygun.

    Öncelik sırası çözünürlük değil ORAN: 4:5'e yakın bir fotoğraf
    kırpılmadan oturuyor, panoramik bir fotoğrafın ise yarısını atmak
    zorunda kalıyoruz.
    """
    genislik, yukseklik = foto["width"], foto["height"]
    if genislik < ASGARI_GENISLIK or yukseklik < ASGARI_YUKSEKLIK:
        return -1

    puan = 0

    # 4:5 = 0.8. Sapma ne kadar azsa o kadar iyi.
    oran = genislik / yukseklik
    sapma = abs(oran - 0.8)
    puan += max(0, int(40 - sapma * 100))

    # Çözünürlük ikincil kriter — yeter seviyenin üstünde fark yaratmıyor
    puan += min(20, (genislik * yukseklik) // 1_000_000)

    return puan


def fotograf_ara(terim: str, aday_sayisi: int = ADAY_SAYISI,
                 atlanacak: int = 0,
                 kullanilmis: set | None = None) -> dict | None:
    """
    Pexels'te arar, en uygun adayın kaydını döner. Bulamazsa None.

    Dönen sözlük `fetch_photo.fotograf_ara` ile aynı alanları taşıyor
    (`url`, `baslik`, `sanatci`, `lisans`) — böylece çağıran taraf iki
    kaynağı ayırt etmek zorunda kalmıyor.

    `kullanilmis`: son postlarda kullanılmış Pexels fotoğraf id'leri.
    ⚠️ NEDEN GEREKTİ (21 Ağu 2026): kullanıcı "görseller hep aynı
    şeyler gibi" dedi. Ölçüldü — aynı fotoğrafçının fotoğrafı 6, 5 ve
    4 kez tekrar etmişti. Sebep: aynı arama terimi hep aynı sonucu
    veriyor ve biz her zaman en yüksek puanlıyı alıyoruz. Bu küme
    daha önce kullanılanları listenin SONUNA atıyor — eleme değil,
    çünkü havuz darsa hiç fotoğraf bulamamaktansa tekrar iyidir.
    """
    try:
        cevap = requests.get(
            API,
            headers={"Authorization": _anahtar()},
            params={
                "query": terim,
                "per_page": aday_sayisi,
                "orientation": ORIENTASYON,
            },
            timeout=ZAMAN_ASIMI,
        )
        cevap.raise_for_status()
        sonuc = cevap.json()
    except Exception as e:
        log.warning("Pexels araması başarısız (%s): %s", terim, e)
        return None

    adaylar = []
    for foto in sonuc.get("photos", []):
        puan = _aday_puani(foto)
        if puan < 0:
            continue
        adaylar.append(
            {
                "id": foto.get("id"),
                # "original" kırpılmamış hâli; kırpmayı biz yapıyoruz
                "url": foto["src"]["original"],
                "baslik": foto.get("alt") or terim,
                "sanatci": foto.get("photographer", ""),
                "lisans": "Pexels Lisansı",
                "sayfa": foto.get("url", ""),
                "puan": puan,
            }
        )

    if not adaylar:
        log.info("Pexels'te uygun fotoğraf bulunamadı: %s", terim)
        return None

    # Daha önce kullanılanlar sona: aynı arama hep aynı fotoğrafı
    # döndürüyordu ve hesap tekdüze görünüyordu.
    onceki = kullanilmis or set()
    adaylar.sort(key=lambda a: (str(a.get("id")) in onceki, -a["puan"]))
    yeni = sum(1 for a in adaylar if str(a.get("id")) not in onceki)
    if onceki and yeni < len(adaylar):
        log.info("Pexels: %s/%s aday daha önce kullanılmış, sona alındı",
                 len(adaylar) - yeni, len(adaylar))
    # ⚠️ `atlanacak` — "başka fotoğraf" düğmesi için. Önce hep
    # `adaylar[0]` dönüyordu, yani düğmeye kaç kez basılırsa basılsın
    # aynı fotoğraf geliyordu. Liste biterse başa dönüyoruz: kullanıcı
    # sırayla gezinsin, hiç sonuç alamamaktansa tekrar görsün.
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
