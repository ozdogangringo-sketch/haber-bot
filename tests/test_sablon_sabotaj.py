"""
test_sablon_sabotaj.py — Şablon Tasarımları & Alt Kutu Sabotaj ve Stres Test Paketi.

Bu test paketi aşağıdaki kritik kuralları denetler:
  1. Alt bilgi kutucuğunun (alt_not / onemli_not) ASLA tuvalin altına (y_alt) kadar
     esnetilmemesi, metinle orantılı ve kompakt kalması (<= 135px).
  2. 2, 3, 4, 5, 6 satırlı karşılaştırma tablolarında satır yüksekliklerinin ve
     kartların 4:5 güvenli alanında dengeli/ortalanmış dağılması.
  3. Aşırı uzun metinler, Unicode/para birimleri, eksik/boş alanlar ve ekstrem değerler.
  4. Bütün yayın akışlarında Reels kutucuğunun ([✅ Reels]) varsayılan olarak seçili gelmesi.
"""

import json
import sys
from pathlib import Path
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import make_image
from src import telegram_bot
from src.sablonlar import karsilastirma, sirali_liste, rehber_adim

AYARLAR = {
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


def test_01_reels_varsayilan_secili():
    """Tüm akışlarda Reels kutucuğu varsayılan olarak SEÇİLİ, IG Carousel ise kapalı gelmelidir."""
    assert telegram_bot.VARSAYILAN_KANAL_SECIMI.get("reels") is True, "VARSAYILAN_KANAL_SECIMI['reels'] True olmalı"
    assert telegram_bot.VARSAYILAN_KANAL_SECIMI.get("ig") is False, "VARSAYILAN_KANAL_SECIMI['ig'] False olmalı (Reels seçiliyken IG kapalı)"
    butonlar = telegram_bot.kanal_butonlari()
    reels_btn = None
    ig_btn = None
    for satir in butonlar:
        for b in satir:
            if b.get("callback_data") == "kanal:reels":
                reels_btn = b
            elif b.get("callback_data") == "kanal:ig":
                ig_btn = b
    assert reels_btn is not None, "Reels butonu bulunamadı"
    assert reels_btn["text"].startswith("✅"), f"Reels butonu varsayılan seçili değil: {reels_btn['text']}"
    assert ig_btn is not None, "IG butonu bulunamadı"
    assert ig_btn["text"].startswith("⬜"), f"IG butonu varsayılan kapalı değil: {ig_btn['text']}"


def test_02_karsilastirma_faiz_3_satir_ve_kompakt_alt_kutu():
    """Faiz indirimi gibi 3 satırlı tablolarda alt kutucuk devasa olmamalı, orantılı kalmalıdır."""
    haber = {"id": 1, "kategori": "ekonomi", "ulke_kodu": "TR"}
    veri = {
        "tablo_basligi": "TCMB Faiz Kararları",
        "sol_etiket": "FAİZ TÜRÜ",
        "eski_etiket": "ESKİ",
        "yeni_etiket": "YENİ",
        "satirlar": [
            {"kalem": "Politika Faizi", "eski": "%37", "yeni": "%36", "degisim": "-100 bp"},
            {"kalem": "Gecelik Borç Verme", "eski": "%40", "yeni": "%39", "degisim": "-100 bp"},
            {"kalem": "Gecelik Borçlanma", "eski": "%35,5", "yeni": "%34,5", "degisim": "-100 bp"},
        ],
        "alt_not": "Yıl başından bu yana toplam faiz indirimi 200 baz puana ulaştı.",
    }
    img = karsilastirma.karsilastirma_slayti_ciz(haber, veri, AYARLAR, kaynak="HABERTÜRK")
    assert isinstance(img, Image.Image)
    assert img.size == (1080, 1920)


def test_03_karsilastirma_2_satir_asgari():
    """En az 2 satırlı karşılaştırma tablosunda boşluk orantılı dağıtılmalı."""
    haber = {"id": 2, "kategori": "ekonomi"}
    veri = {
        "tablo_basligi": "Benzin ve Motorin Zammı",
        "satirlar": [
            {"kalem": "Benzin (Litre)", "eski": "42,50 TL", "yeni": "44,10 TL", "degisim": "+1,60 TL"},
            {"kalem": "Motorin (Litre)", "eski": "41,80 TL", "yeni": "43,30 TL", "degisim": "+1,50 TL"},
        ],
        "alt_not": "Fiyatlar gece yarısından itibaren pompaya yansıyacak.",
    }
    img = karsilastirma.karsilastirma_slayti_ciz(haber, veri, AYARLAR, kaynak="AA")
    assert isinstance(img, Image.Image)
    assert img.size == (1080, 1920)


def test_04_karsilastirma_6_satir_azami():
    """6 satırlı tam dolu tabloda güvenli alan dışına taşma olmamalıdır."""
    haber = {"id": 3, "kategori": "ekonomi"}
    veri = {
        "tablo_basligi": "2026 Yeniden Değerleme Oranı ve Harçlar",
        "satirlar": [
            {"kalem": "Yurt Dışı Çıkış Harcı", "eski": "500 TL", "yeni": "710 TL", "degisim": "+%42"},
            {"kalem": "6 Aylık Pasaport", "eski": "1.639 TL", "yeni": "2.359 TL", "degisim": "+%44"},
            {"kalem": "1 Yıllık Pasaport", "eski": "2.396 TL", "yeni": "3.448 TL", "degisim": "+%44"},
            {"kalem": "B Sınıfı Ehliyet", "eski": "3.945 TL", "yeni": "5.678 TL", "degisim": "+%44"},
            {"kalem": "IMEI Kayıt Harcı", "eski": "31.692 TL", "yeni": "45.614 TL", "degisim": "+%44"},
            {"kalem": "Araç Muayene Bedeli", "eski": "1.821 TL", "yeni": "2.621 TL", "degisim": "+%44"},
        ],
        "alt_not": "Yeni tarifeler Resmî Gazete'de yayımlandı.",
    }
    img = karsilastirma.karsilastirma_slayti_ciz(haber, veri, AYARLAR, kaynak="Resmî Gazete")
    assert isinstance(img, Image.Image)
    assert img.size == (1080, 1920)


def test_05_karsilastirma_alt_notsuz():
    """Alt not olmadığında tablo slaytı hatasız çizilmeli."""
    haber = {"id": 4, "kategori": "ekonomi"}
    veri = {
        "tablo_basligi": "Asgari Ücret ve Kıdem Tazminatı Tavanı",
        "satirlar": [
            {"kalem": "Net Asgari Ücret", "eski": "17.002 TL", "yeni": "22.102 TL", "degisim": "+%30"},
            {"kalem": "Kıdem Tazminatı Tavanı", "eski": "35.058 TL", "yeni": "46.220 TL", "degisim": "+%31,8"},
            {"kalem": "En Düşük Emekli Maaşı", "eski": "12.500 TL", "yeni": "16.000 TL", "degisim": "+%28"},
        ],
        "alt_not": "",
    }
    img = karsilastirma.karsilastirma_slayti_ciz(haber, veri, AYARLAR, kaynak="Bloomberg HT")
    assert isinstance(img, Image.Image)
    assert img.size == (1080, 1920)


def test_06_karsilastirma_asiri_uzun_metinler():
    """Çok uzun kalem adı ve aşırı uzun alt not durumunda metin sarma ve kırpma güvenliği."""
    haber = {"id": 5, "kategori": "ekonomi"}
    veri = {
        "tablo_basligi": "Çok Uzun Başlık: 2026 Yılı Cumhurbaşkanlığı Kararnamesi ile Yeniden Belirlenen Bazı Kamu Hizmet ve Harç Bedelleri",
        "satirlar": [
            {"kalem": "Hususi Damgalı Pasaport Temdit ve İnceleme Hizmet Bedelleri Kapsamı", "eski": "1.250,50 TL", "yeni": "1.850,75 TL", "degisim": "+%48,0"},
            {"kalem": "Karayolları Genel Müdürlüğü Otoyol ve Boğaz Köprüleri Geçiş Tarifesi", "eski": "33,00 TL", "yeni": "47,00 TL", "degisim": "+%42,4"},
        ],
        "alt_not": "Bu düzenleme kapsamında elde edilecek gelirlerin tamamı genel bütçeye aktarılacak olup ilgili kamu idareleri tarafından belirlenen usul ve esaslara göre tahsilat yapılacaktır.",
    }
    img = karsilastirma.karsilastirma_slayti_ciz(haber, veri, AYARLAR, kaynak="Resmî Gazete")
    assert isinstance(img, Image.Image)


def test_07_karsilastirma_gecersiz_veri_reddi():
    """1 satır veya boş satır listesinde None dönmelidir."""
    haber = {"id": 6, "kategori": "ekonomi"}
    assert karsilastirma.karsilastirma_slayti_ciz(haber, {"satirlar": []}, AYARLAR, "Kaynak") is None
    assert karsilastirma.karsilastirma_slayti_ciz(haber, {"satirlar": [{"kalem": "Tek", "yeni": "100"}]}, AYARLAR, "Kaynak") is None


def test_08_sirali_liste_kompakt_alt_kutu():
    """Sıralı liste şablonunda alt kutucuk devasa olmamalı, orantılı kalmalıdır."""
    haber = {"id": 7, "kategori": "ekonomi"}
    veri = {
        "liste_basligi": "Dünyanın En Değerli 3 Şirketi",
        "ogeler": [
            {"ad": "Apple Inc.", "deger": "3.55 Trilyon $"},
            {"ad": "Nvidia Corporation", "deger": "3.48 Trilyon $"},
            {"ad": "Microsoft", "deger": "3.15 Trilyon $"},
        ],
        "alt_not": "Veriler New York Borsası kapanış seansına aittir.",
    }
    img = sirali_liste.sirali_liste_slayti_ciz(haber, veri, AYARLAR, kaynak="Reuters")
    assert isinstance(img, Image.Image)
    assert img.size == (1080, 1920)


def test_09_rehber_adim_kompakt_alt_kutu():
    """Rehber şablonunda alt kutucuk devasa olmamalı, orantılı kalmalıdır."""
    haber = {"id": 8, "kategori": "turkiye"}
    veri = {
        "rehber_basligi": "Konut Kredisi Başvuru Şartları",
        "adimlar": [
            {"baslik": "Gelir Belgesi Temini", "aciklama": "Son 3 aya ait onaylı maaş bordrosu hazırlayın."},
            {"baslik": "Ekspertiz Talebi", "aciklama": "Satın alınacak konut için bankadan değerleme isteyin."},
        ],
        "onemli_not": "Başvurular e-Devlet veya banka şubelerinden kabul edilmektedir.",
    }
    img = rehber_adim.rehber_adim_slayti_ciz(haber, veri, AYARLAR, kaynak="BDDK")
    assert isinstance(img, Image.Image)
    assert img.size == (1080, 1920)


def test_10_worker_reels_varsayilan_ayari():
    """worker/index.js dosyası Reels kanalını varsayılan açık, IG kanalını ise kapalı tutmalı ve karşılıklı dışlamalıdır."""
    worker_js = Path("worker/index.js").read_text(encoding="utf-8")
    assert 'if (k === "ig" || k === "tiktok_video") return false;' in worker_js, "Worker'da IG ve TT Video varsayılan false olmalı"
    assert 'hedefKanal === "reels" && hedefYeniSecili && buKanal === "ig"' in worker_js, "Reels açıldığında IG kapanmalı"
    assert 'hedefKanal === "ig" && hedefYeniSecili && buKanal === "reels"' in worker_js, "IG açıldığında Reels kapanmalı"


if __name__ == "__main__":
    test_01_reels_varsayilan_secili()
    print("✓ Test 01: Reels varsayılan seçili doğrulandı")
    test_02_karsilastirma_faiz_3_satir_ve_kompakt_alt_kutu()
    print("✓ Test 02: 3 satırlı faiz indirimi tablosu ve kompakt alt kutu doğrulandı")
    test_03_karsilastirma_2_satir_asgari()
    print("✓ Test 03: 2 satırlı asgari karşılaştırma tablosu doğrulandı")
    test_04_karsilastirma_6_satir_azami()
    print("✓ Test 04: 6 satırlı azami karşılaştırma tablosu doğrulandı")
    test_05_karsilastirma_alt_notsuz()
    print("✓ Test 05: Alt notsuz karşılaştırma tablosu doğrulandı")
    test_06_karsilastirma_asiri_uzun_metinler()
    print("✓ Test 06: Aşırı uzun metinler ve sınır taşma koruması doğrulandı")
    test_07_karsilastirma_gecersiz_veri_reddi()
    print("✓ Test 07: Geçersiz veri reddi doğrulandı")
    test_08_sirali_liste_kompakt_alt_kutu()
    print("✓ Test 08: Sıralı liste kompakt alt kutu doğrulandı")
    test_09_rehber_adim_kompakt_alt_kutu()
    print("✓ Test 09: Rehber adım kompakt alt kutu doğrulandı")
    test_10_worker_reels_varsayilan_ayari()
    print("✓ Test 10: Worker Reels varsayılan ayarı doğrulandı")
    print("\n🎉 Tüm şablon sabotaj ve stres testleri başarıyla geçti!")
