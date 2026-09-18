"""
test_piyasa_ozet.py — Canlı piyasa bülteni ekonomi özet kartı motoru testleri.
"""

from pathlib import Path
from PIL import Image
import pytest

from src import piyasa_ozet


def test_bos_haber_listesi():
    """Haber yoksa boş liste dönmeli, bülten çökmemeli."""
    assert piyasa_ozet.ekonomi_ozet_sayfalari_uret([]) == []


def test_tek_haber_tek_sayfa():
    """1-3 haber tek bir 1080x1920 özet sayfası üretmeli."""
    haberler = [
        {
            "ig_baslik": "Merkez Bankası faiz kararını açıkladı",
            "slayt_ozet": "Politika faizi yüzde 50 seviyesinde sabit tutuldu.",
            "kaynak": "AA Finans",
            "yayin_tarihi": "2026-09-18T10:00:00Z",
        }
    ]
    yollar = piyasa_ozet.ekonomi_ozet_sayfalari_uret(haberler)
    assert len(yollar) == 1
    yol = yollar[0]
    assert Path(yol).exists()
    with Image.open(yol) as im:
        assert im.size == (1080, 1920)


def test_uc_haber_tek_sayfa():
    """Tam 3 haber yine tek sayfaya sığmalı."""
    haberler = [
        {
            "ig_baslik": f"Ekonomi Haberi {i}",
            "slayt_ozet": f"Haber {i} detay ve özet metni burada yer almaktadır.",
            "kaynak": "Bloomberg HT",
            "yayin_tarihi": "2026-09-18T11:00:00Z",
        }
        for i in range(1, 4)
    ]
    yollar = piyasa_ozet.ekonomi_ozet_sayfalari_uret(haberler)
    assert len(yollar) == 1
    assert Path(yollar[0]).exists()


def test_dort_veya_bes_haber_iki_sayfa():
    """3'ten fazla haber (örn. 5 haber) 2 sayfaya bölünmeli (azami 3 haber/sayfa)."""
    haberler = [
        {
            "ig_baslik": f"Kritik Gelişme {i}",
            "slayt_ozet": f"Gelişme {i} piyasaların seyrini belirledi.",
            "kaynak": "TRT Ekonomi",
            "yayin_tarihi": "2026-09-18T12:00:00Z",
        }
        for i in range(1, 6)
    ]
    yollar = piyasa_ozet.ekonomi_ozet_sayfalari_uret(haberler)
    assert len(yollar) == 2
    for y in yollar:
        assert Path(y).exists()
        with Image.open(y) as im:
            assert im.size == (1080, 1920)


def test_alti_haberden_fazlasi_sinirlanir():
    """6'dan fazla haber verilse bile en fazla 6 haber alınarak 2 sayfa üretilmeli."""
    haberler = [
        {
            "ig_baslik": f"Haber {i}",
            "slayt_ozet": f"Özet {i}",
            "kaynak": "Kaynak",
        }
        for i in range(1, 10)
    ]
    yollar = piyasa_ozet.ekonomi_ozet_sayfalari_uret(haberler)
    assert len(yollar) == 2


def test_etiket_belirleme():
    """Kelimelere göre doğru kategori etiketi seçilmeli."""
    assert "FON" in piyasa_ozet._etiket_belirle({"ig_baslik": "SPK yeni yatırım fonu tasfiyesini duyurdu"})
    assert "FAİZ" in piyasa_ozet._etiket_belirle({"ig_baslik": "TCMB faiz oranını sabit tuttu"})
    assert "DÖVİZ" in piyasa_ozet._etiket_belirle({"ig_baslik": "Dolar kuru yeni güne nasıl başladı"})
    assert "MAKRO" in piyasa_ozet._etiket_belirle({"ig_baslik": "Cari işlemler açığı geriledi"})


def test_mod_kapanis_ve_acilis():
    """Moda göre (kapanış veya açılış) doğru başlık ve rozet basılmalı."""
    haberler = [
        {
            "ig_baslik": "Piyasa Kapanışında BIST 100 Rekor Kırdı",
            "slayt_ozet": "BIST 100 endeksi günü yükselişle tamamladı.",
            "kaynak": "AA Finans",
        }
    ]

    from PIL import ImageDraw
    for mod, beklenen_baslik, beklenen_rozet in [
        ("kapanis", "Günü Kapatırken", "Kapanış Özeti"),
        ("acilis", "Günün Öne Çıkanları", "Açılış Özeti"),
    ]:
        yakalanan = []
        orj = ImageDraw.ImageDraw.text

        def _sahte_text(self, xy, text, *a, **k):
            if isinstance(text, str):
                yakalanan.append(text)
            return orj(self, xy, text, *a, **k)

        ImageDraw.ImageDraw.text = _sahte_text
        try:
            yollar = piyasa_ozet.ekonomi_ozet_sayfalari_uret(haberler, mod=mod)
        finally:
            ImageDraw.ImageDraw.text = orj

        assert len(yollar) == 1
        assert any(beklenen_baslik in t for t in yakalanan)
        assert any(beklenen_rozet in t for t in yakalanan)
        assert f"_{mod}" in str(yollar[0])

