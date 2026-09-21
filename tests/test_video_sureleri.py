"""
test_video_sureleri.py — Video slayt sürelerinin içerik yoğunluğuna göre dinamik hesaplanma testleri.
"""

from pathlib import Path
import sys

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

from src.video import slayt_surelerini_hesapla


def test_slayt_sureleri_bos_ve_tekli():
    """Boş veya tek slayt durumlarında beklenen süreler dönmeli."""
    assert slayt_surelerini_hesapla(0) == []
    assert slayt_surelerini_hesapla(1) == [4.2]
    assert slayt_surelerini_hesapla(1, varsayilan_kapak_suresi=5.0) == [5.0]


def test_slayt_sureleri_varsayilan_haber_olmadan():
    """Haber listesi verilmediğinde varsayılan insani süreler hesaplanmalı."""
    # 3 slayt: 1 Kapak (4.2s) + 2 Detay (~5.62s her biri)
    sureler = slayt_surelerini_hesapla(3)
    assert len(sureler) == 3
    assert sureler[0] == 4.2
    for s in sureler[1:]:
        assert 4.8 <= s <= 6.2
    toplam = sum(sureler)
    assert 14.0 <= toplam <= 17.0


def test_slayt_sureleri_kisa_metin():
    """Kısa metinli haberlerde minimum taban süre (4.8s) uygulanmalı."""
    haberler = [{
        "detay_metni": "Kısa bir haber metni. Birkaç kelimeden ibaret.",
    }]
    sureler = slayt_surelerini_hesapla(3, haberler=haberler)
    assert len(sureler) == 3
    assert sureler[0] == 4.2
    # Çok az kelime olsa bile 4.8 saniyenin altına inmemeli (rahat okuma garantisi)
    for s in sureler[1:]:
        assert s >= 4.8
        assert s <= 6.2


def test_slayt_sureleri_uzun_metin():
    """Çok uzun ve veri dolu detay metinlerinde tavan süre (6.2s) aşılmamalı."""
    uzun_paragraf = " ".join(["kelime"] * 120)
    haberler = [{
        "detay_metni": f"{uzun_paragraf}\n\n{uzun_paragraf}",
    }]
    sureler = slayt_surelerini_hesapla(4, haberler=haberler)
    assert len(sureler) == 4
    assert sureler[0] == 4.2
    for s in sureler[1:]:
        assert s <= 6.2
    toplam = sum(sureler)
    # 4 slaytlık video 23 saniyenin altında kalmalı (sosyal medya algoritması ve izlenme tamamlanma oranı)
    assert toplam <= 23.0
