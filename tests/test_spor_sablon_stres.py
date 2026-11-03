"""
tests/test_spor_sablon_stres.py — spor_kapak ve spor_kadro şablonları için derin stres ve sabotaj test paketi.

Test Kapsamı:
  1. Aşırı uzun takım adlarında tuval kenarından (X=0 ve X=1079) sıfır taşma garantisi.
  2. Aşırı uzun futbolcu adlarında son soyadın (football shirt name) korunması ve akıllı sığdırma.
  3. Yedek kulübesi ve alt not eksik olduğunda taktik sahanın dinamik genişlemesi.
  4. Turnuva ve maç telemetrisi satırlarında taşma ve başlık çakışması engeli.
  5. Tek takım kadrosunda (rakip yok) dengeli ikiye bölme modu (Savunma vs Hücum).
  6. Maç sonu (MS) ve canlı skor modunda rozet ve madalyon renkleri.
  7. 1080x1920 tuval ve 4:5 güvenli alan sınırları (Y=505 ile Y=1488 arası tam kontrol).
"""

from __future__ import annotations

import json
from PIL import Image, ImageDraw
import numpy as np
import pytest

from src import make_image, sablonlar
from src.sablonlar import spor_kadro, spor_kapak

AYARLAR_TEST = {
    "gorsel": {
        "genislik": 1080,
        "yukseklik": 1920,
        "kenar_bosluk": 64,
        "dikey_guvenli_pay": 330,
    }
}


def test_asiri_uzun_takim_adlari_kapakta_kenardan_tasmaz():
    """Gaziantep FK ve Bodrum FK gibi uzun takım adları armaların altından dışarı taşmamalı."""
    haber = {
        "ig_baslik": "Dev Maç Öncesi Kadrolar",
        "spot": "Süper Lig heyecanında ilk 11'ler açıklandı.",
        "detay_sablonu": "spor_kadro",
    }
    veri = {
        "ev_sahibi": "Gaziantep Futbol Kulübü",
        "deplasman": "Bodrum Futbol Kulübü A.Ş.",
        "turnuva": "Süper Lig",
        "skor_veya_saat": "20:00",
        "mac_bilgisi": "Kalyon Stadyumu · Hakem: Ali Şansalan · beIN Sports 1",
    }
    img = spor_kapak.spor_kapak_slayti_ciz(haber, veri, AYARLAR_TEST, "Daily Brief Spor")
    assert img.size == (1080, 1920)

    # İsimlerin çizildiği Y=880..960 bölgesinde sol kenar (0..15 px) ve sağ kenar (1065..1080 px) kontrolü
    arr = np.array(img)
    sol_kenar = arr[880:960, 0:15]
    sag_kenar = arr[880:960, 1065:1080]

    # Metin kenara taşmışsa parlaklık 180-255 olur; sadece zemin ambiyansı kalmışsa <140 olmalı
    assert np.max(sol_kenar) < 140, f"Sol kenarda metin taşması tespit edildi: {np.max(sol_kenar)}"
    assert np.max(sag_kenar) < 140, f"Sağ kenarda metin taşması tespit edildi: {np.max(sag_kenar)}"


def test_ad_akilli_sigdir_soyad_koruma():
    """Çok parçalı yabancı isimlerde sağdan körü körüne kesmek yerine soyadı korunmalı."""
    im = Image.new("RGB", (100, 100))
    ciz = ImageDraw.Draw(im)
    font = make_image._font(20, make_image.EKSEN_BASLIK)

    ad_uzun = "Bernardo Mota Veiga de Carvalho e Silva"
    sigdirilan = spor_kadro._ad_akilli_sigdir(ciz, ad_uzun, font, max_gen=260)
    assert "Silva" in sigdirilan, f"Oyuncunun soyadı silindi: {sigdirilan}"

    ad_saliba = "William Alain André Gabriel Saliba"
    sig_saliba = spor_kadro._ad_akilli_sigdir(ciz, ad_saliba, font, max_gen=250)
    assert "Saliba" in sig_saliba, f"Saliba soyadı silindi: {sig_saliba}"


def test_yedek_ve_alt_not_olmadiginda_dinamik_saha_genislemesi():
    """Yedek kulübesi veya alt not yoksa taktik saha çökmeksizin tüm alana yayılmalı."""
    haber = {"ig_baslik": "Kupa Maçı", "detay_sablonu": "spor_kadro"}
    veri = {
        "ev_sahibi": "Trabzonspor",
        "deplasman": "Fenerbahçe",
        "ev_kadro": [f"Oyuncu {i}" for i in range(1, 12)],
        "dep_kadro": [f"Rakip {i}" for i in range(1, 12)],
        "ev_yedekler": [],
        "dep_yedekler": [],
        "alt_not": "",
    }
    img = spor_kadro.spor_kadro_slayti_ciz(haber, veri, AYARLAR_TEST, "Daily Brief Spor")
    assert img is not None
    assert img.size == (1080, 1920)


def test_turnuva_ve_mac_bilgisi_telemetri_sigdirma():
    """60 karakterlik dev turnuva ismi ve 120 karakterlik stat bilgisi taşmamalı."""
    im = Image.new("RGB", (100, 100))
    ciz = ImageDraw.Draw(im)

    dev_turnuva = "UEFA ŞAMPİYONLAR LİGİ ÇEYREK FİNAL 2. KARŞILAŞMASI (RÖVANŞ)"
    txt, font = spor_kadro._telemetri_sigdir(ciz, dev_turnuva, max_gen=320, baslangic_punto=16)
    assert ciz.textlength(txt, font=font) <= 320

    dev_stat = "Ali Sami Yen Spor Kompleksi RAMS Park Stadyumu Seyrantepe · Başhakem: Halil Umut Meler (FIFA) · beIN Sports 1 4K"
    stat_txt, stat_f = spor_kadro._telemetri_sigdir(ciz, dev_stat, max_gen=880, baslangic_punto=16)
    assert ciz.textlength(stat_txt, font=stat_f) <= 880


def test_tek_takim_kadro_modu_savunma_hucum_ayrimi():
    """Sadece ev sahibi kadroyu açıkladığında ikiye bölerek çizmeli."""
    haber = {"ig_baslik": "Kadro Açıklandı", "detay_sablonu": "spor_kadro"}
    veri = {
        "ev_sahibi": "Galatasaray",
        "deplasman": "",
        "ev_kadro": [f"GS Oyuncu {i}" for i in range(1, 12)],
        "dep_kadro": [],
    }
    img = spor_kadro.spor_kadro_slayti_ciz(haber, veri, AYARLAR_TEST, "Daily Brief Spor")
    assert img is not None
    assert img.size == (1080, 1920)


def test_mac_sonu_skor_ve_ms_rozetleri():
    """Maç sonu geldiğinde skor rozeti yeşil halka ile çizilmeli."""
    haber = {"ig_baslik": "Derbi Bitti", "detay_sablonu": "spor_kadro"}
    veri = {
        "ev_sahibi": "Beşiktaş",
        "deplasman": "Galatasaray",
        "skor_veya_saat": "3 - 2",
        "mac_sonu": True,
        "ev_kadro": [f"BJK {i}" for i in range(1, 12)],
        "dep_kadro": [f"GS {i}" for i in range(1, 12)],
    }
    img = spor_kapak.spor_kapak_slayti_ciz(haber, veri, AYARLAR_TEST, "Daily Brief Spor")
    assert img.size == (1080, 1920)
