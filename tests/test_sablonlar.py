"""
test_sablonlar.py — Dinamik Detay Sayfası Şablonları (src/sablonlar/) birim testleri.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db, instagram, sablonlar, slaytlar
from src.sablonlar import medya_video


ORNEK_AYARLAR = {
    "gorsel": {
        "kose_etiketi": "DAILY BRIEF",
    },
    "instagram": {
        "hesap_kullanici_adi": "dailybrief",
        "api_surumu": "v21.0",
        "zaman_asimi": 10,
        "deneme_sayisi": 1,
        "hazir_azami_deneme": 1,
        "hazir_bekleme_saniye": 0,
    },
}


def test_sablon_adini_dogrula():
    assert sablonlar.sablon_adini_dogrula("spor_kadro") == "spor_kadro"
    assert sablonlar.sablon_adini_dogrula("HAVA_DURUMU") == "hava_durumu"
    assert sablonlar.sablon_adini_dogrula("karsilastirma") == "karsilastirma"
    assert sablonlar.sablon_adini_dogrula("rehber_adim") == "rehber_adim"
    assert sablonlar.sablon_adini_dogrula("sirali_liste") == "sirali_liste"
    assert sablonlar.sablon_adini_dogrula("bilinmeyen_sablon") == "standart"
    assert sablonlar.sablon_adini_dogrula(None) == "standart"


def test_spor_kadro_sablonu_1080x1920():
    haber = {
        "id": 101,
        "kategori": "spor",
        "kaynak": "TRT Spor",
        "ulke_kodu": "TR",
        "detay_sablonu": "spor_kadro",
        "sablon_verisi": json.dumps({
            "turnuva": "UEFA Şampiyonlar Ligi • Lig Aşaması",
            "stadyum_saat": "RAMS Park • 22:00 • Hakem: D. Orsato",
            "ev_sahibi": "Galatasaray",
            "deplasman": "Bayern Münih",
            "ev_dizilis": "4-2-3-1",
            "dep_dizilis": "4-2-3-1",
            "ev_td": "Okan Buruk",
            "dep_td": "Vincent Kompany",
            "ev_11": [
                "Muslera", "Kaan Ayhan", "Sanchez", "Abdülkerim", "Jakobs",
                "Torreira", "Sara", "Barış Alper", "Mertens", "Yunus Akgün", "Osimhen"
            ],
            "dep_11": [
                "Neuer", "Guerreiro", "Upamecano", "Kim Min-jae", "Davies",
                "Kimmich", "Pavlovic", "Olise", "Musiala", "Gnabry", "Harry Kane"
            ],
            "eksikler": "Sakat/Cezalı: Icardi (GS), Boey (Bayern)",
        }, ensure_ascii=False),
    }
    im = sablonlar.ozel_detay_slayti_uret(haber, ORNEK_AYARLAR, sayfa=2, toplam_sayfa=4)
    assert isinstance(im, Image.Image)
    assert im.size == (1080, 1920)


def test_hava_durumu_sablonu_1080x1920():
    haber = {
        "id": 102,
        "kategori": "yasam",
        "kaynak": "MGM",
        "ulke_kodu": "TR",
        "detay_sablonu": "hava_durumu",
        "sablon_verisi": {
            "uyari_kodu": "turuncu",
            "baslik": "Marmara ve Kıyı Ege İçin Kuvvetli Lodos ve Sağanak Uyarısı",
            "hadise": "Kuvvetli Fırtına & Sağanak",
            "zaman_araligi": "Perşembe 06:00 — Cuma 18:00",
            "ruzgar": "75-90 km/sa",
            "yagis": "50-75 kg/m²",
            "sicaklik": "8°C Hissedilen",
            "iller": [
                "İstanbul", "İzmir", "Bursa", "Balıkesir",
                "Çanakkale", "Kocaeli", "Tekirdağ", "Aydın", "Muğla"
            ],
            "onlem": "Çatı uçması, ağaç devrilmesi ve vapur seferlerinde aksamalara karşı tedbirli olunmalı.",
        },
    }
    im = sablonlar.ozel_detay_slayti_uret(haber, ORNEK_AYARLAR, sayfa=2, toplam_sayfa=4)
    assert isinstance(im, Image.Image)
    assert im.size == (1080, 1920)


def test_karsilastirma_sablonu_1080x1920():
    haber = {
        "id": 103,
        "kategori": "ekonomi",
        "kaynak": "Resmî Gazete",
        "ulke_kodu": "TR",
        "detay_sablonu": "karsilastirma",
        "sablon_verisi": {
            "baslik": "2026 Yurt Dışı Çıkış Harcı ve Pasaport Harç Tutarları",
            "sol_etiket": "ESKİ TUTAR",
            "sag_etiket": "YENİ TUTAR",
            "satirlar": [
                {"kalem": "Yurt Dışı Çıkış Harcı", "eski": "500 TL", "yeni": "710 TL", "degisim": "+%42"},
                {"kalem": "6 Aylık Pasaport Harcı", "eski": "1.639 TL", "yeni": "2.359 TL", "degisim": "+%43,9"},
                {"kalem": "1 Yıllık Pasaport Harcı", "eski": "2.396 TL", "yeni": "3.448 TL", "degisim": "+%43,9"},
                {"kalem": "3+ Yıllık Pasaport Harcı", "eski": "7.833 TL", "yeni": "11.274 TL", "degisim": "+%43,9"},
                {"kalem": "Pasaport Defter Bedeli", "eski": "790 TL", "yeni": "1.135 TL", "degisim": "+%43,6"},
            ],
            "alt_not": "Yeni tarifeler 1 Ocak itibarıyla vergi daireleri ve dijital kanallarda yürürlüğe girecek.",
        },
    }
    im = sablonlar.ozel_detay_slayti_uret(haber, ORNEK_AYARLAR, sayfa=2, toplam_sayfa=4)
    assert isinstance(im, Image.Image)
    assert im.size == (1080, 1920)


def test_rehber_adim_sablonu_1080x1920():
    haber = {
        "id": 104,
        "kategori": "ekonomi",
        "kaynak": "TOKİ",
        "ulke_kodu": "TR",
        "detay_sablonu": "rehber_adim",
        "sablon_verisi": {
            "baslik": "TOKİ 100 Bin Sosyal Konut Başvuru Şartları ve Adımları",
            "ust_etiket": "BAŞVURU REHBERİ",
            "adimlar": [
                {"baslik": "Kimlik ve İkamet Şartı", "aciklama": "T.C. vatandaşı olmak ve proje ilinde en az 1 yıldır ikamet etmek."},
                {"baslik": "Konut Sahipliği Kriteri", "aciklama": "Başvuru sahibinin, eşinin ve çocuklarının üzerine kayıtlı tapu bulunmaması."},
                {"baslik": "Hane Halkı Gelir Sınırı", "aciklama": "Aylık toplam hane gelirinin net 45.000 TL'yi (İstanbul için 52.000 TL) aşmaması."},
                {"baslik": "e-Devlet Başvuru ve Harç", "aciklama": "e-Devlet üzerinden başvuru formunu doldurup 2.000 TL başvuru bedelini yatırmak."},
            ],
            "son_tarih": "Son Başvuru: 15 Kasım Cuma • Başvuru Kanalı: e-Devlet & Yetkili Bankalar",
        },
    }
    im = sablonlar.ozel_detay_slayti_uret(haber, ORNEK_AYARLAR, sayfa=2, toplam_sayfa=4)
    assert isinstance(im, Image.Image)
    assert im.size == (1080, 1920)


def test_sirali_liste_sablonu_1080x1920():
    haber = {
        "id": 105,
        "kategori": "teknoloji",
        "kaynak": "TİM",
        "ulke_kodu": "TR",
        "detay_sablonu": "sirali_liste",
        "sablon_verisi": {
            "baslik": "Türkiye'nin En Çok İhracat Yapan İlk 5 Sektörü",
            "ust_etiket": "İHRACAT LİDERLERİ",
            "birim": "Ekim Ayı Dış Satım Hacmi (Milyar $)",
            "ogeler": [
                {"isim": "Otomotiv Endüstrisi", "deger": "3,24 Milyar $", "alt_bilgi": "Yıllık +%8,4 artış", "oran": 100},
                {"isim": "Kimyevi Maddeler ve Ürünler", "deger": "2,65 Milyar $", "alt_bilgi": "Yıllık +%4,1 artış", "oran": 82},
                {"isim": "Hazır Giyim ve Konfeksiyon", "deger": "1,58 Milyar $", "alt_bilgi": "AB pazarı lider", "oran": 49},
                {"isim": "Çelik ve Demir Dışı Metaller", "deger": "1,42 Milyar $", "alt_bilgi": "Yıllık +%6,2 artış", "oran": 44},
                {"isim": "Elektrik ve Elektronik", "deger": "1,36 Milyar $", "alt_bilgi": "Savunma ve kablo etkisi", "oran": 42},
            ],
            "alt_not": "Toplam Ekim ayı ihracatı geçen yılın aynı ayına göre %3,6 artışla 23,6 milyar dolara ulaştı.",
        },
    }
    im = sablonlar.ozel_detay_slayti_uret(haber, ORNEK_AYARLAR, sayfa=2, toplam_sayfa=4)
    assert isinstance(im, Image.Image)
    assert im.size == (1080, 1920)


def test_eksik_veri_guvenli_fallback():
    """Şablon verisi eksik veya hatalıysa None dönmeli ve standart metin slaytına düşmeli."""
    for sablon_adi in ("spor_kadro", "hava_durumu", "karsilastirma", "rehber_adim", "sirali_liste"):
        haber = {"detay_sablonu": sablon_adi, "sablon_verisi": "{}"}
        assert sablonlar.ozel_detay_slayti_uret(haber, ORNEK_AYARLAR) is None


def test_html_icinden_video_url_bul():
    html_icerik = """
    <html>
      <head>
        <meta property="og:video" content="https://www.youtube.com/embed/xyz123" />
      </head>
      <body>
        <video controls src="/media/haber_videosu_2026.mp4"></video>
      </body>
    </html>
    """
    bulunan = medya_video.makaleden_video_url_cikar(html_icerik, "https://ornekhaber.com/gundem/test")
    assert bulunan == "https://ornekhaber.com/media/haber_videosu_2026.mp4"


def test_instagram_hibrit_carousel_video_container():
    """Carousel'de .mp4 URL varsa media_type=VIDEO ve video_url parametresiyle gönderilmeli."""
    cagrilar = []

    def sahte_istek(yontem, yol, ayarlar, **params):
        cagrilar.append((yontem, yol, params))
        if yontem == "GET" and yol.endswith("/content_publishing_limit"):
            return {"data": [{"quota_usage": 2, "config": {"quota_total": 100}}]}
        if yontem == "GET":
            return {"id": "123", "username": "dailybrief", "status_code": "FINISHED"}
        return {"id": f"cont_{len(cagrilar)}"}

    with patch.object(instagram, "_istek", side_effect=sahte_istek), \
         patch.object(instagram, "_kullanici_id", return_value="999"):
        urller = [
            "https://media.dailybrief.ozbornstudio.com/kapak.jpg",
            "https://media.dailybrief.ozbornstudio.com/haber_video.mp4",
            "https://media.dailybrief.ozbornstudio.com/detay.jpg",
        ]
        post_id = instagram.carousel_yayinla(urller, "Test açıklama", ORNEK_AYARLAR)
        assert post_id.startswith("cont_")

    medya_postlari = [p for (y, yol, p) in cagrilar if y == "POST" and yol == "/999/media" and p.get("is_carousel_item") == "true"]
    assert len(medya_postlari) == 3
    assert medya_postlari[0].get("image_url") == "https://media.dailybrief.ozbornstudio.com/kapak.jpg"
    assert medya_postlari[1].get("media_type") == "VIDEO"
    assert medya_postlari[1].get("video_url") == "https://media.dailybrief.ozbornstudio.com/haber_video.mp4"
    assert medya_postlari[2].get("image_url") == "https://media.dailybrief.ozbornstudio.com/detay.jpg"
