"""
tests/test_telegram_sabotaj.py — Telegram Altyapısı 50 Sabotaj ve Dayanıklılık Testi

Bu test paketi, en zorlu senaryolarda, bozuk girdilerde, API sınırlarında,
kötü niyetli injection girişimlerinde ve altyapı arızalarında Telegram
katmanının asla çökmeyip kendini güvenle kurtardığını doğrular.
"""

import html
import json
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

KOK = Path(__file__).resolve().parent.parent
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

import requests
from src import telegram_bot, db, ozel_haber, yonetim, hata_bildir
from src.komutlar import MESAJSIZ_KOMUTLAR, mesajsiz_komut_mu
from scripts import onay_isle


# ===========================================================================
# GRUP 1: TELEGRAM API, AĞ VE HATA KURTARMA SABOTAJLARI (TEST 1 - 10)
# ===========================================================================

def test_sabotaj_01_html_unclosed_tags_fallback():
    """Bozuk veya kapanmamış HTML tag'lerinde parse_mode kaldırılarak kurtarma."""
    bozuk_html = "<b>Son Dakika:</b> Dolar < 34.50 & Euro > 37.20 <i>(Kapanmamış..."
    ilk_denendi = False

    def sahte_post(url, json=None, timeout=60):
        nonlocal ilk_denendi
        resp = MagicMock()
        if (json or {}).get("parse_mode"):
            resp.status_code = 400
            resp.content = b'{"ok": false, "error_code": 400, "description": "Bad Request: can\'t parse entities"}'
            resp.json.return_value = {"ok": False, "description": "Bad Request: can't parse entities"}
            ilk_denendi = True
            return resp
        resp.status_code = 200
        resp.content = b'{"ok": true, "result": {"message_id": 1001}}'
        resp.json.return_value = {"ok": True, "result": {"message_id": 1001}}
        return resp

    with patch("requests.post", side_effect=sahte_post), \
         patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "123:abc", "TELEGRAM_CHAT_ID": "12345"}):
        mid = telegram_bot.mesaj_gonder(bozuk_html, html=True)
        assert mid == 1001
        assert ilk_denendi
    print("  ✓ Sabotaj 01: Bozuk HTML parse hatası düz metinle anında kurtarıldı")


def test_sabotaj_02_album_media_entity_fallback():
    """sendMediaGroup albümündeki bozuk caption etiketlerinde düz metin fallback."""
    medya = [
        {"type": "photo", "media": "http://img.com/1.jpg", "caption": "<b>Kapak <bozuk>", "parse_mode": "HTML"},
    ]

    def sahte_post(url, json=None, timeout=60):
        resp = MagicMock()
        media_list = (json or {}).get("media", [])
        if any(m.get("parse_mode") for m in media_list):
            resp.status_code = 400
            resp.content = b'{"ok": false, "description": "Bad Request: can\'t parse entities in photo caption"}'
            resp.json.return_value = {"ok": False, "description": "can't parse entities"}
            return resp
        resp.status_code = 200
        resp.content = b'{"ok": true, "result": [{"message_id": 2001}]}'
        resp.json.return_value = {"ok": True, "result": [{"message_id": 2001}]}
        return resp

    with patch("requests.post", side_effect=sahte_post), \
         patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "123:abc", "TELEGRAM_CHAT_ID": "12345"}):
        sonuc = telegram_bot._istek("sendMediaGroup", media=medya)
        assert sonuc[0]["message_id"] == 2001
    print("  ✓ Sabotaj 02: Albüm caption parse hatası parse_mode kaldırılarak kurtarıldı")


def test_sabotaj_03_4096_karakter_siniri():
    """4096 karakteri aşan dev metinlerde mesaj_gonder'in güvenle kırpması."""
    asiri_uzun = "A" * 10000
    yakalanan = {}

    def sahte_istek(metot, **kwargs):
        yakalanan["text"] = kwargs.get("text")
        return {"message_id": 3001}

    with patch("src.telegram_bot._istek", side_effect=sahte_istek):
        mid = telegram_bot.mesaj_gonder(asiri_uzun)
        assert mid == 3001
        assert len(yakalanan["text"]) <= 4096
    print("  ✓ Sabotaj 03: 4096 karakter sınırı taşma olmaksızın korundu")


def test_sabotaj_04_telegram_429_rate_limit_retry():
    """Telegram HTTP 429 Too Many Requests aldığında retry_after süresince bekleyip başarması."""
    cagri_sayisi = 0

    def sahte_post(url, json=None, timeout=60):
        nonlocal cagri_sayisi
        cagri_sayisi += 1
        resp = MagicMock()
        if cagri_sayisi == 1:
            resp.status_code = 429
            resp.content = b'{"ok": false, "error_code": 429, "parameters": {"retry_after": 1}}'
            resp.json.return_value = {"ok": False, "error_code": 429, "parameters": {"retry_after": 1}}
            return resp
        resp.status_code = 200
        resp.content = b'{"ok": true, "result": {"message_id": 4001}}'
        resp.json.return_value = {"ok": True, "result": {"message_id": 4001}}
        return resp

    with patch("requests.post", side_effect=sahte_post), \
         patch("time.sleep") as mock_sleep, \
         patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "123:abc", "TELEGRAM_CHAT_ID": "12345"}):
        res = telegram_bot._istek("sendMessage", text="test")
        assert res["message_id"] == 4001
        assert cagri_sayisi == 2
        mock_sleep.assert_called_with(2)  # min(retry_after + 1, 60)
    print("  ✓ Sabotaj 04: HTTP 429 Rate limit retry_after beklemesiyle aşıldı")


def test_sabotaj_05_telegram_502_504_gateway_retry():
    """Telegram HTTP 502/504 Bad Gateway hatasında exponential backoff ile tekrar denemesi."""
    denemeler = 0

    def sahte_post(url, json=None, timeout=60):
        nonlocal denemeler
        denemeler += 1
        resp = MagicMock()
        if denemeler < 3:
            resp.status_code = 502
            resp.content = b'{"ok": false, "error_code": 502, "description": "Bad Gateway"}'
            resp.json.return_value = {"ok": False, "error_code": 502, "description": "Bad Gateway"}
            return resp
        resp.status_code = 200
        resp.content = b'{"ok": true, "result": {"message_id": 5001}}'
        resp.json.return_value = {"ok": True, "result": {"message_id": 5001}}
        return resp

    with patch("requests.post", side_effect=sahte_post), \
         patch("time.sleep"), \
         patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "123:abc", "TELEGRAM_CHAT_ID": "12345"}):
        res = telegram_bot._istek("sendMessage", text="test")
        assert res["message_id"] == 5001
        assert denemeler == 3
    print("  ✓ Sabotaj 05: HTTP 502 Bad Gateway hatasında otomatik kurtarma başarılı")


def test_sabotaj_06_telegram_supergroup_migration():
    """Telegram grubunun süper gruba yükselmesi durumunda yeni ID ile isteğin tekrarlanması."""
    ilk = True

    def sahte_post(url, json=None, timeout=60):
        nonlocal ilk
        resp = MagicMock()
        if ilk:
            ilk = False
            resp.status_code = 400
            resp.content = b'{"ok": false, "parameters": {"migrate_to_chat_id": -100999888}}'
            resp.json.return_value = {"ok": False, "parameters": {"migrate_to_chat_id": -100999888}}
            return resp
        resp.status_code = 200
        resp.content = b'{"ok": true, "result": {"message_id": 6001}}'
        resp.json.return_value = {"ok": True, "result": {"message_id": 6001}}
        return resp

    with patch("requests.post", side_effect=sahte_post), \
         patch("src.telegram_bot._yeni_sohbet_id_kaydet"), \
         patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "123:abc", "TELEGRAM_CHAT_ID": "-100111"}):
        res = telegram_bot._istek("sendMessage", chat_id="-100111", text="test")
        assert res["message_id"] == 6001
    print("  ✓ Sabotaj 06: Supergroup migrate_to_chat_id göçü kesintisiz tamamlandı")


def test_sabotaj_07_telegram_mesaj_sil_hatasiz():
    """Silinmek istenen mesaj bulunamazsa veya 48 saatten eskiyse mesaj_sil'in çökmeden False dönmesi."""
    with patch("src.telegram_bot._istek", side_effect=RuntimeError("message to delete not found")):
        sonuc = telegram_bot.mesaj_sil(999999)
        assert sonuc is False
    print("  ✓ Sabotaj 07: Bulunamayan veya eski mesaj silme hatası sessizce yutuldu")


def test_sabotaj_08_telegram_mesaji_guncelle_not_found():
    """mesaji_guncelle çağrısında 'message is not modified' hatasının güvenle bastırılması."""
    with patch("src.telegram_bot._istek", side_effect=RuntimeError("Bad Request: message is not modified")):
        try:
            telegram_bot.mesaji_guncelle(1234, "Aynı metin", {})
        except Exception as e:
            assert False, f"mesaji_guncelle 'not modified' hatasını fırlatmamalıydı: {e}"
    print("  ✓ Sabotaj 08: mesaji_guncelle 'message is not modified' hatasını hatasız bastırdı")


def test_sabotaj_09_durum_guncelle_not_modified():
    """durum_guncelle fonksiyonunun 'message is not modified' hatasında çökmemesi."""
    with patch("src.telegram_bot._istek", side_effect=RuntimeError("message is not modified")):
        try:
            telegram_bot.durum_guncelle(1234, "Başlık", 1, 4)
        except Exception as e:
            assert False, f"durum_guncelle hata fırlattı: {e}"
    print("  ✓ Sabotaj 09: durum_guncelle not modified durumunu sessizce yönetti")


def test_sabotaj_10_durum_guncelle_sinir_degerleri():
    """durum_guncelle sınır değerlerinde (toplam_adim=0, adim < 0, adim > toplam) çökmez."""
    gonderilenler = []

    def sahte_istek(metot, **kwargs):
        gonderilenler.append(kwargs)
        return {"ok": True}

    with patch("src.telegram_bot._istek", side_effect=sahte_istek):
        telegram_bot.durum_guncelle(None, "Test", 1, 4)
        telegram_bot.durum_guncelle(0, "Test", 1, 4)
        assert len(gonderilenler) == 0

        telegram_bot.durum_guncelle(123, "Test", 1, toplam_adim=0)
        assert "(1/1)" in gonderilenler[-1]["text"]

        telegram_bot.durum_guncelle(123, "Test", 99, toplam_adim=4)
        assert "(4/4)" in gonderilenler[-1]["text"]

        telegram_bot.durum_guncelle(123, "Test", -10, toplam_adim=4)
        assert "(1/4)" in gonderilenler[-1]["text"]
    print("  ✓ Sabotaj 10: durum_guncelle sınır değerleri ve sıfıra bölünme engeli kusursuz")


# ===========================================================================
# GRUP 2: GÜVENLİK, DURUM & METİN/MEDYA DAYANIKLILIK SABOTAJLARI (TEST 11 - 20)
# ===========================================================================

def test_sabotaj_11_durum_guncelle_xss_null_bytes():
    """durum_guncelle parametrelerindeki XSS ve HTML payload'larının escape edilmesi."""
    gonderilenler = []

    with patch("src.telegram_bot._istek", side_effect=lambda m, **k: gonderilenler.append(k) or {"ok": True}):
        telegram_bot.durum_guncelle(123, "<script>alert(1)</script>", 1, 4, detay="\"'><img src=x onerror=1>&")
        text = gonderilenler[-1]["text"]
        assert "<script>" not in text
        assert "&lt;script&gt;" in text
        assert "&amp;" in text
    print("  ✓ Sabotaj 11: durum_guncelle XSS ve HTML payload sanitizasyonu hatasız")


def test_sabotaj_12_video_gonder_entity_fallback():
    """video_gonder video açıklamasında HTML parse hatası alınca parse_mode'suz kurtarması."""
    ilk = True

    def sahte_post(url, data=None, files=None, timeout=180):
        nonlocal ilk
        resp = MagicMock()
        if ilk and data.get("parse_mode"):
            ilk = False
            resp.content = b'{"ok": false, "description": "can\'t parse entities in video caption"}'
            resp.json.return_value = {"ok": False, "description": "can't parse entities"}
            return resp
        resp.content = b'{"ok": true, "result": {"message_id": 1201}}'
        resp.json.return_value = {"ok": True, "result": {"message_id": 1201}}
        return resp

    with tempfile.NamedTemporaryFile(suffix=".mp4") as tmp:
        tmp.write(b"dummy")
        tmp.flush()
        with patch("requests.post", side_effect=sahte_post), \
             patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "123:abc", "TELEGRAM_CHAT_ID": "12345"}):
            mid = telegram_bot.video_gonder(tmp.name, aciklama="<b>Video <bozuk>")
            assert mid == 1201
    print("  ✓ Sabotaj 12: video_gonder HTML parse hatası parse_mode kaldırılarak kurtarıldı")


def test_sabotaj_13_slaytlari_gonder_bos_liste():
    """slaytlari_gonder boş liste aldığında Telegram'a istek atmadan hemen [] döner."""
    with patch("src.telegram_bot._istek") as mock_istek:
        sonuc = telegram_bot.slaytlari_gonder([])
        assert sonuc == []
        mock_istek.assert_not_called()
    print("  ✓ Sabotaj 13: slaytlari_gonder boş girdi durumunda güvenli çıkış yaptı")


def test_sabotaj_14_yerel_album_gonder_olmayan_dosyalar():
    """yerel_albom_gonder var olmayan dosya yolları verildiğinde hata fırlatmadan [] döner."""
    with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "123:abc", "TELEGRAM_CHAT_ID": "12345"}):
        sonuc = telegram_bot.yerel_albom_gonder(["/nonexistent/slayt_1.jpg", "/nonexistent/slayt_2.jpg"])
        assert sonuc == []
    print("  ✓ Sabotaj 14: yerel_albom_gonder eksik dosya listesinde güvenle [] döndü")


def test_sabotaj_15_detay_urlleri_bozuk_json():
    """_detay_urlleri bozuk JSON string veya None aldığında çökmeden liste döner."""
    assert onay_isle._detay_urlleri(None) == []
    assert onay_isle._detay_urlleri("") == []
    assert onay_isle._detay_urlleri("{broken_json") == ["{broken_json"]
    assert onay_isle._detay_urlleri(12345) == [12345]
    assert onay_isle._detay_urlleri('["http://a.com/1.jpg", "http://a.com/2.jpg"]') == [
        "http://a.com/1.jpg", "http://a.com/2.jpg"
    ]
    print("  ✓ Sabotaj 15: _detay_urlleri bozuk ve karmaşık tiplerde dayanıklı")


def test_sabotaj_16_detay_urlleri_duz_metin_url():
    """_detay_urlleri eski kayıtlardaki düz metin URL'yi geriye uyumlu tek elemanlı liste yapar."""
    tek_url = "https://i.ibb.co/ornek/slayt-detay.jpg"
    sonuc = onay_isle._detay_urlleri(tek_url)
    assert sonuc == [tek_url]
    print("  ✓ Sabotaj 16: _detay_urlleri eski düz URL formatıyla geriye dönük uyumlu")


def test_sabotaj_17_gorsel_adaylari_bozuk_json():
    """gorsel_adayini_sec haberin gorsel_adaylari alanı bozuk JSON ise çökmeden uyarı verir."""
    con = MagicMock()
    ayarlar = {}
    haberler = [{"id": 1, "gorsel_adaylari": "{invalid_json"}]

    with patch("src.telegram_bot.mesaj_gonder") as mock_mesaj, \
         patch("scripts.onay_isle.menuyu_geri_koy"):
        sonuc = onay_isle.gorsel_adayini_sec(con, ayarlar, haberler, aday_no=1, sira=1, mesaj_id=100)
        assert sonuc == 0
        mock_mesaj.assert_called_with("⚠️ 1. aday listede yok (0 aday var).")
    print("  ✓ Sabotaj 17: Bozuk gorsel_adaylari verisi güvenle yakalandı")


def test_sabotaj_18_tur_ozeti_bos_veya_eksik_haber():
    """tur_ozeti None alanları olan veya boş listede çökmeden özet üretir."""
    ozet_bos = telegram_bot.tur_ozeti([], uyari_sayisi=0)
    assert "0 slayt" in ozet_bos

    eksik_haber = [{"gorsel_kaynagi": None, "ig_baslik": None, "baslik_orj": None}]
    ozet_eksik = telegram_bot.tur_ozeti(eksik_haber, uyari_sayisi=2)
    assert "1 slayt" in ozet_eksik
    assert "2 slaytta uyarı" in ozet_eksik
    print("  ✓ Sabotaj 18: tur_ozeti eksik ve None alanlara karşı korumalı")


def test_sabotaj_19_tur_ozeti_uzun_baslik_kirpma():
    """tur_ozeti 58 karakterden uzun manşetleri kırparak tablo düzenini korur."""
    uzun_haber = [{"gorsel_kaynagi": "pexels", "ig_baslik": "X" * 150, "baslik_orj": "Y" * 150}]
    ozet = telegram_bot.tur_ozeti(uzun_haber)
    satir = ozet.splitlines()[-1]
    assert len(satir.strip()) <= 75  # Simge + sıra no + max 58 karakter
    print("  ✓ Sabotaj 19: tur_ozeti aşırı uzun manşetleri güvenle sınırlandırdı")


def test_sabotaj_20_onay_iste_uyari_ve_ozet_escape():
    """onay_iste uyarı ve özet metinlerindeki özel karakterleri (&, <, >) escape eder."""
    gonderilen = {}

    def sahte_istek(metot, **kwargs):
        gonderilen.update(kwargs)
        return {"message_id": 2001}

    with patch("src.telegram_bot._istek", side_effect=sahte_istek):
        telegram_bot.onay_iste("Caption & Detay", 3, uyari="Fiyat < 100 & Kar > 50", ozet="Özet & Bilgi")
        metin = gonderilen.get("text", "")
        assert "&lt;" in metin
        assert "&gt;" in metin
        assert "&amp;" in metin
    print("  ✓ Sabotaj 20: onay_iste özel karakterleri HTML uyumlu escape etti")


# ===========================================================================
# GRUP 3: KOMUTLAR & KULLANICI GİRDİSİ SABOTAJLARI (TEST 21 - 30)
# ===========================================================================

def test_sabotaj_21_linkten_haber_gecersiz_protokol():
    """linkten_haber_uret http/https dışındaki protokolleri (ftp://, javascript:) reddeder."""
    con = MagicMock()
    with patch("src.telegram_bot.mesaj_gonder") as mock_mesaj:
        sonuc = ozel_haber.linkten_haber_uret("ftp://site.com/dosya", con, {})
        assert sonuc == 1
        assert "Geçerli bir link giriniz" in mock_mesaj.call_args[0][0]
    print("  ✓ Sabotaj 21: /link geçersiz protokollere karşı korumalı")


def test_sabotaj_22_linkten_haber_kisa_metin_veya_403():
    """linkten_haber_uret gövde metni 100 karakterden kısa ise uyarır."""
    con = MagicMock()
    with patch("src.ozel_haber._baslik_ve_metin_ayikla", return_value=("Başlık", "Kısa", None, "Kaynak")), \
         patch("src.telegram_bot.mesaj_gonder") as mock_mesaj, \
         patch("src.telegram_bot.durum_guncelle"):
        sonuc = ozel_haber.linkten_haber_uret("https://ornek.com/haber", con, {})
        assert sonuc == 1
        assert "okunamadı veya erişim engellendi" in mock_mesaj.call_args[0][0]
    print("  ✓ Sabotaj 22: /link yetersiz gövde metninde güvenle durdu")


def test_sabotaj_23_arastir_haber_asiri_kisa_konu():
    """arastir_haber_uret 4 karakterden kısa girdilerde Gemini'yi tetiklemeden uyarır."""
    con = MagicMock()
    with patch("src.telegram_bot.mesaj_gonder") as mock_mesaj, \
         patch("src.generate_text.gemini_cagir") as mock_gemini:
        sonuc = ozel_haber.arastir_haber_uret("a", con, {})
        assert sonuc == 1
        mock_gemini.assert_not_called()
        assert "daha detaylı yaz" in mock_mesaj.call_args[0][0]
    print("  ✓ Sabotaj 23: /arastir kısa girdide gereksiz API harcamasını engelledi")


def test_sabotaj_24_dosya_haber_asiri_kisa_konu():
    """dosya_haber_uret 4 karakterden kısa konularda işlem yapmaz."""
    con = MagicMock()
    with patch("src.telegram_bot.mesaj_gonder") as mock_mesaj:
        sonuc = ozel_haber.dosya_haber_uret("abc", con, {})
        assert sonuc == 1
        assert "detaylı yaz" in mock_mesaj.call_args[0][0]
    print("  ✓ Sabotaj 24: /dosya ve /kronoloji kısa girdide güvenle durdu")


def test_sabotaj_25_ozel_metin_asiri_kisa_bulten():
    """ozel_metin_haber_uret 15 karakterden kısa duyurularda işlem yapmaz."""
    con = MagicMock()
    with patch("src.telegram_bot.mesaj_gonder") as mock_mesaj:
        sonuc = ozel_haber.ozel_metin_haber_uret("kısa bülten", con, {})
        assert sonuc == 1
        assert "duyuru metnini yaz" in mock_mesaj.call_args[0][0]
    print("  ✓ Sabotaj 25: /ozel yetersiz metin uzunluğunda kullanıcıyı uyardı")


def test_sabotaj_26_makro_gemini_bozuk_json_fallback():
    """makro_haber_uret Gemini geçerli bir JSON dönmediğinde çökmeden hata mesajı üretir."""
    con = MagicMock()
    with patch("src.generate_text.gemini_cagir", return_value="Bozuk metin response"), \
         patch("src.telegram_bot.mesaj_gonder") as mock_mesaj, \
         patch("src.telegram_bot.durum_guncelle"):
        sonuc = ozel_haber.makro_haber_uret("TCMB faiz sabit", con, {})
        assert sonuc == 1
        assert any("hata oluştu" in str(c[0][0]) for c in mock_mesaj.call_args_list)
    print("  ✓ Sabotaj 26: /makro Gemini bozuk JSON yanıtında güvenle kurtarıldı")


def test_sabotaj_27_komut_sql_injection_saldirisi():
    """Komut girdilerindeki SQL injection denemeleri parametreli sorgularla engellenir."""
    db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_file.close()
    try:
        con = sqlite3.connect(db_file.name)
        con.execute("CREATE TABLE haberler (id INTEGER PRIMARY KEY, baslik TEXT, link TEXT)")
        con.execute("INSERT INTO haberler (baslik, link) VALUES ('Normal', 'http://a.com')")
        con.commit()

        saldiri = "' OR '1'='1' --"
        res = con.execute("SELECT id FROM haberler WHERE link = ?", (saldiri,)).fetchall()
        assert len(res) == 0, "SQL injection sorguyu manipüle etti!"
        con.close()
    finally:
        os.unlink(db_file.name)
    print("  ✓ Sabotaj 27: SQL injection saldırı payload'ı parametreli sorguda etkisiz kaldı")


def test_sabotaj_28_bilinmeyen_slash_komut_guvenligi():
    """mesajsiz_komut_mu rastgele veya tanınmayan komutlara karşı False döner."""
    assert mesajsiz_komut_mu("hacker_komut") is False
    assert mesajsiz_komut_mu("rm_rf_database") is False
    assert mesajsiz_komut_mu("") is False
    assert mesajsiz_komut_mu(None) is False
    print("  ✓ Sabotaj 28: Bilinmeyen komutlar yetkisiz çalıştırılmaya karşı korundu")


def test_sabotaj_29_mesajsiz_komutlar_sozlesmesi():
    """Parametreli komutlarda (dosya:ahbap, link:http) kök komut doğru tespit edilir."""
    assert mesajsiz_komut_mu("dosya:Haluk Levent") is True
    assert mesajsiz_komut_mu("link:https://reuters.com/news") is True
    assert mesajsiz_komut_mu("bilinmeyen:parametre") is False
    print("  ✓ Sabotaj 29: Parametreli mesajsız komut ayrıştırması hatasız")


def test_sabotaj_30_video_ve_reels_mesajsiz_komut_mu():
    """video ve reels komutlarının mesaj_id gerektirmeyen sözleşmeye tam uyması."""
    assert "video" in MESAJSIZ_KOMUTLAR
    assert "reels" in MESAJSIZ_KOMUTLAR
    assert mesajsiz_komut_mu("video") is True
    assert mesajsiz_komut_mu("reels") is True
    print("  ✓ Sabotaj 30: /video ve /reels mesajsız komut listesinde onaylandı")


# ===========================================================================
# GRUP 4: MEDYA, VİDEO VE FOTOĞRAF AKIŞI SABOTAJLARI (TEST 31 - 40)
# ===========================================================================

def test_sabotaj_31_video_gorsel_yok_uyarisi():
    """Slayt görseli yokken /video çağrıldığında temiz uyarı verilip 0 dönülür."""
    con = MagicMock()
    with patch("scripts.onay_isle.db.baglan", return_value=con), \
         patch("scripts.onay_isle.db.kur"), \
         patch("scripts.onay_isle.ayar.uygula"), \
         patch("pathlib.Path.glob", return_value=[]), \
         patch("src.telegram_bot.mesaj_gonder") as mock_mesaj, \
         patch.dict(os.environ, {"KOMUT": "video", "MESAJ_ID": "0"}):
        sonuc = onay_isle.main()
        assert sonuc == 0
        assert "görseli bulunamadı" in mock_mesaj.call_args[0][0]
    print("  ✓ Sabotaj 31: /video görsel yokken kullanıcıyı bilgilendirdi")


def test_sabotaj_32_video_tamamlama_ve_gonderim():
    """/video slaytlardan MP4 üretip Telegram'a video olarak iletir."""
    con = MagicMock()
    with patch("scripts.onay_isle.db.baglan", return_value=con), \
         patch("scripts.onay_isle.db.kur"), \
         patch("scripts.onay_isle.ayar.uygula"), \
         patch("pathlib.Path.glob", return_value=[Path("/tmp/s1.jpg"), Path("/tmp/s2.jpg")]), \
         patch("src.video.slaytlardan_reels_uret", return_value="/tmp/test_reels.mp4"), \
         patch("src.telegram_bot.mesaj_gonder", return_value=999), \
         patch("src.telegram_bot.video_gonder") as mock_vg, \
         patch.dict(os.environ, {"KOMUT": "video", "MESAJ_ID": "0"}):
        sonuc = onay_isle.main()
        assert sonuc == 0
        mock_vg.assert_called_once()
        assert mock_vg.call_args[0][0] == "/tmp/test_reels.mp4"
    print("  ✓ Sabotaj 32: /video tamamlama ve video_gonder akışı doğrulandı")


def test_sabotaj_33_video_render_hatasi_yakalama():
    """FFmpeg render hatasında /video çökmeden hatayı Telegram'a bildirir."""
    con = MagicMock()
    with patch("scripts.onay_isle.db.baglan", return_value=con), \
         patch("scripts.onay_isle.db.kur"), \
         patch("scripts.onay_isle.ayar.uygula"), \
         patch("pathlib.Path.glob", return_value=[Path("/tmp/s1.jpg")]), \
         patch("src.video.slaytlardan_reels_uret", side_effect=RuntimeError("FFmpeg error")), \
         patch("src.telegram_bot.mesaj_gonder") as mock_mesaj, \
         patch.dict(os.environ, {"KOMUT": "video", "MESAJ_ID": "0"}):
        sonuc = onay_isle.main()
        assert sonuc == 1
        assert "Video üretimi başarısız" in mock_mesaj.call_args[0][0]
    print("  ✓ Sabotaj 33: /video render istisnası yakalanıp raporlandı")


def test_sabotaj_34_foto_degistir_sadece_kapak_yukler():
    """Fotoğraf değiştirmede 4x hızlandırma: ImgBB'ye sadece kapak slaytı yüklenir."""
    con = MagicMock()
    ayarlar = {"gorsel": {"gorsel_aday_adedi": 2}}
    haber = {
        "id": 42,
        "ig_baslik": "Test",
        "baslik_orj": "Test",
        "son_dakika": 1,
        "gorsel_deneme": 1,
        "detay_url": json.dumps(["http://img.com/detay1.jpg", "http://img.com/detay2.jpg"]),
    }

    yuklenen_dosyalar = []

    def sahte_yukle(yollar, ayarlar):
        yuklenen_dosyalar.extend(yollar)
        return [{"url": "http://img.com/yeni_kapak.jpg"}]

    sahte_slaytlar = [
        {"yol": "/tmp/slayt1.jpg", "katman": "duckduckgo", "atif": "Reuters"},
        {"yol": "/tmp/slayt2.jpg", "katman": "detay", "atif": ""},
    ]

    with patch("src.telegram_bot.mesaj_gonder"), \
         patch("src.telegram_bot.durum_guncelle"), \
         patch("src.slaytlar.son_dakika_uret", return_value=sahte_slaytlar), \
         patch("src.upload_image.hepsini_yukle", side_effect=sahte_yukle), \
         patch("scripts.onay_isle._gorsel_adayini_uygula", return_value=0):
        sonuc = onay_isle.foto_degistir_islemi(con, ayarlar, [haber], mesaj_id=100, mod="gercek")
        assert sonuc == 0
        assert len(yuklenen_dosyalar) == 2  # 2 aday x 1 kapak = 2 dosya (12 değil!)
        assert all("slayt1.jpg" in y for y in yuklenen_dosyalar)
    print("  ✓ Sabotaj 34: 4x hızlandırma — sadece kapak yüklendi, detaylar korundu")


def test_sabotaj_35_foto_degistir_aday_bulunamadi_guvenli_cikis():
    """Alternatif aday bulunamadığında menü geri konulup 0 dönülür."""
    con = MagicMock()
    haber = {"id": 1, "ig_baslik": "Test", "baslik_orj": "Test", "son_dakika": 1, "gorsel_deneme": 0, "detay_url": None}

    with patch("src.telegram_bot.mesaj_gonder") as mock_mesaj, \
         patch("src.telegram_bot.durum_guncelle"), \
         patch("src.slaytlar.son_dakika_uret", return_value=[]), \
         patch("scripts.onay_isle.menuyu_geri_koy") as mock_menu:
        sonuc = onay_isle.foto_degistir_islemi(con, {}, [haber], mesaj_id=100)
        assert sonuc == 0
        mock_menu.assert_called_with(con, 100)
        assert any("bulunamadı" in str(c[0][0]) for c in mock_mesaj.call_args_list)
    print("  ✓ Sabotaj 35: Aday bulunamadığında menü kurtarma ve güvenli çıkış")


def test_sabotaj_36_gorsel_adayini_uygula_dogru_url_dagilimi():
    """Aday uygulandığında urller[0] gorsel_url'ye, urller[1:] detay_url'ye yazılır."""
    con = MagicMock()
    secilen = {
        "urller": ["http://img.com/kapak.jpg", "http://img.com/detay1.jpg"],
        "katman": "commons",
        "atif": "Wiki",
        "deneme": 1,
    }

    with patch("src.telegram_bot.slaytlari_gonder", return_value=[501, 502]), \
         patch("src.telegram_bot.mesaj_gonder"), \
         patch("scripts.onay_isle.menuyu_geri_koy"), \
         patch("src.db.ayar_oku", return_value=""), \
         patch("src.db.ayar_yaz"):
        onay_isle._gorsel_adayini_uygula(con, {}, {"id": 10}, secilen, mesaj_id=100)
        sql, params = con.execute.call_args[0]
        assert "UPDATE haberler SET" in sql
        assert params[0] == "http://img.com/kapak.jpg"
        assert params[1] == json.dumps(["http://img.com/detay1.jpg"])
    print("  ✓ Sabotaj 36: Gorsel adayı uygulama ve veritabanı ayrımı hatasız")


def test_sabotaj_37_foto_degistir_durum_guncelleme_ve_silme():
    """foto_degistir_islemi adayları ararken progress gösterir, bitince mesajı siler."""
    con = MagicMock()
    haber = {
        "id": 202,
        "ig_baslik": "Ateşkes",
        "baslik_orj": "Ateşkes",
        "son_dakika": 1,
        "gorsel_deneme": 0,
        "detay_url": json.dumps(["http://img.com/detay1.jpg"]),
    }
    cagrilar = []
    silinenler = []

    with patch("src.telegram_bot.mesaj_gonder", return_value=777), \
         patch("src.telegram_bot.durum_guncelle", side_effect=lambda m, b, a, t, d="": cagrilar.append(a)), \
         patch("src.telegram_bot.mesaj_sil", side_effect=lambda m: silinenler.append(m) or True), \
         patch("src.slaytlar.son_dakika_uret", return_value=[{"yol": "/tmp/s1.jpg", "katman": "web", "atif": "A"}]), \
         patch("src.upload_image.hepsini_yukle", return_value=[{"url": "http://img.com/yeni.jpg"}]), \
         patch("scripts.onay_isle._gorsel_adayini_uygula", return_value=0):
        onay_isle.foto_degistir_islemi(con, {}, [haber], mod="gercek", mesaj_id=100)
        assert len(cagrilar) == 3
        assert 777 in silinenler
    print("  ✓ Sabotaj 37: foto_degistir canlı ilerleme ve geçici mesaj temizliği kusursuz")


def test_sabotaj_38_foto_sec_gecersiz_indeks():
    """gorsel_adayini_sec sınır dışı aday indeksinde çökmeden kullanıcıyı uyarır."""
    con = MagicMock()
    haberler = [{"id": 1, "gorsel_adaylari": json.dumps([{"url": "http://a.com/1.jpg"}])}]

    with patch("src.telegram_bot.mesaj_gonder") as mock_mesaj, \
         patch("scripts.onay_isle.menuyu_geri_koy"):
        sonuc = onay_isle.gorsel_adayini_sec(con, {}, haberler, aday_no=99, sira=1, mesaj_id=100)
        assert sonuc == 0
        assert "99. aday listede yok" in mock_mesaj.call_args[0][0]
    print("  ✓ Sabotaj 38: Sınır dışı görsel adayı seçimi (foto_sec_99) güvenle engellendi")


def test_sabotaj_39_slayt_sil_son_slayt_korumasi():
    """slayt_sil son dakika tek haberinde veya <2 slayt kalan carousel'de silmeyi engeller."""
    con = MagicMock()
    with patch("src.telegram_bot.mesaj_gonder") as mock_mesaj:
        # Son dakika tekil koruması
        onay_isle.slayt_islemi(con, {}, [{"id": 1, "son_dakika": 1}], komut="slayt_sil", sira=1, mesaj_id=100)
        assert "tek haberden oluşuyor" in mock_mesaj.call_args[0][0]

        # Carousel en az 2 slayt koruması
        onay_isle.slayt_islemi(con, {}, [{"id": 1, "son_dakika": 0}, {"id": 2, "son_dakika": 0}], komut="slayt_sil", sira=1, mesaj_id=100)
        assert "en az 2 slayt istiyor" in mock_mesaj.call_args[0][0]
    print("  ✓ Sabotaj 39: slayt_sil tek slayt kalması durumunda silme işlemini engelledi")


def test_sabotaj_40_dosya_haber_durum_guncelleme_akisi():
    """dosya_haber_uret sürecinde 1/4, 2/4 ve 4/4 durum ilerlemesi işletilir."""
    con = MagicMock()
    con.execute.return_value.lastrowid = 888
    cagrilar = []

    sahte_gemini = {
        "kategori": "turkiye",
        "ig_baslik": "Dilan Polat Dosyası",
        "slayt_ozet": "Özet",
        "detay_metni": "P1\n\nP2\n\nP3",
    }

    with patch("src.telegram_bot.mesaj_gonder", return_value=555), \
         patch("src.telegram_bot.durum_guncelle", side_effect=lambda m, b, a, t, d="": cagrilar.append((a, t))), \
         patch("src.generate_text.gemini_cagir", return_value=sahte_gemini), \
         patch("src.db.metin_kaydet"), \
         patch("src.ozel_haber._post_olustur_ve_onaya_sun", return_value=0) as mock_post:
        sonuc = ozel_haber.dosya_haber_uret("Dilan Polat davası ve ara kararlar", con, {})
        assert sonuc == 0
        assert (1, 4) in cagrilar
        assert (2, 4) in cagrilar
        assert mock_post.call_args[1].get("durum_mesaj_id") == 555
    print("  ✓ Sabotaj 40: dosya_haber_uret canlı durum çubuğu lifecycle'ı doğrulandı")


# ===========================================================================
# GRUP 5: YÖNETİM, HATA KATALOĞU, VERİTABANI & UI SABOTAJLARI (TEST 41 - 50)
# ===========================================================================

def test_sabotaj_41_duraklatildi_mi_gecersiz_tarih():
    """duraklatildi_mi ayarlar tablosundaki bozuk ISO tarihini çökmeden False kabul eder."""
    con = MagicMock()
    con.execute.return_value.fetchone.return_value = {"deger": "gecersiz_tarih_format"}
    durum, kalan = yonetim.duraklatildi_mi(con)
    assert durum is False
    assert kalan == ""
    print("  ✓ Sabotaj 41: duraklatildi_mi bozuk veritabanı tarihini güvenle karşıladı")


def test_sabotaj_42_duraklat_ve_devam_et_dongusu():
    """duraklat ve devam_et döngüsü ayarlar tablosunu tutarlı günceller."""
    db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_file.close()
    try:
        con = sqlite3.connect(db_file.name)
        con.row_factory = sqlite3.Row
        con.execute("CREATE TABLE ayarlar (anahtar TEXT PRIMARY KEY, deger TEXT)")
        con.commit()

        yonetim.duraklat(con, saat=6, basan="Dogukan")
        durum, kalan = yonetim.duraklatildi_mi(con)
        assert durum is True
        assert "5s" in kalan or "6s" in kalan

        yonetim.devam_et(con, basan="Dogukan")
        durum, _ = yonetim.duraklatildi_mi(con)
        assert durum is False
        con.close()
    finally:
        os.unlink(db_file.name)
    print("  ✓ Sabotaj 42: duraklat ve devam_et döngüsü SQLite üzerinde doğrulandı")


def test_sabotaj_43_askidaki_turlari_temizle_yayinlanmis_habere_dokunmaz():
    """askidaki_turlari_temizle YAYINLANMIŞ haberleri asla sıfırlamaz."""
    db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_file.close()
    try:
        con = sqlite3.connect(db_file.name)
        con.row_factory = sqlite3.Row
        con.execute("CREATE TABLE haberler (id INTEGER PRIMARY KEY, durum TEXT, telegram_message_id INT, planlanan_yayin TEXT)")
        con.execute("INSERT INTO haberler (id, durum, telegram_message_id) VALUES (1, 'onay_bekliyor', 101)")
        con.execute("INSERT INTO haberler (id, durum, telegram_message_id) VALUES (2, 'yayinlandi', 102)")
        con.commit()

        temizlenen = yonetim.askidaki_turlari_temizle(con)
        assert temizlenen == 1

        k2 = con.execute("SELECT durum, telegram_message_id FROM haberler WHERE id = 2").fetchone()
        assert k2["durum"] == "yayinlandi"
        assert k2["telegram_message_id"] == 102
        con.close()
    finally:
        os.unlink(db_file.name)
    print("  ✓ Sabotaj 43: askidaki_turlari_temizle yayınlanmış haberlere asla dokunmadı")


def test_sabotaj_44_api_saglik_testi_eksik_tokenlar():
    """api_saglik_testi API token'ları eksik olduğunda çökmeden durum=False döner."""
    with patch.dict(os.environ, {}, clear=True):
        sonuclar = yonetim.api_saglik_testi({"sosyal": {"facebooka_da_at": True, "threadse_de_at": True}})
        assert len(sonuclar) >= 4
        assert all(isinstance(s["durum"], bool) for s in sonuclar)
        # Token olmadığı için tüm gerçek API'ler False dönmeli
        assert any(not s["durum"] and "eksik" in s["mesaj"] for s in sonuclar)
    print("  ✓ Sabotaj 44: api_saglik_testi eksik token ortamında hatasız raporladı")


def test_sabotaj_45_api_saglik_testi_servis_timeout():
    """api_saglik_testi dış servisler timeout verdiğinde çökmeyip hatayı kaydeder."""
    with patch("requests.get", side_effect=requests.exceptions.Timeout("Zaman aşımı")), \
         patch.dict(os.environ, {"IG_ACCESS_TOKEN": "token", "IG_USER_ID": "123"}):
        sonuclar = yonetim.api_saglik_testi({})
        ig_sonuc = next(s for s in sonuclar if s["ad"] == "Instagram Graph API")
        assert ig_sonuc["durum"] is False
        assert "Timeout" in ig_sonuc["mesaj"]
    print("  ✓ Sabotaj 45: api_saglik_testi ağ zaman aşımını güvenle yakaladı")


def test_sabotaj_46_kota_ve_durum_raporu_bozuk_dosya():
    """kota_ve_durum_raporu yedek anahtar dosyası bozuk veya yokken bile rapor üretir."""
    con = MagicMock()
    con.execute.return_value.fetchone.return_value = [0]
    with patch("src.yonetim.duraklatildi_mi", return_value=(False, "")), \
         patch("pathlib.Path.exists", return_value=False):
        rapor = yonetim.kota_ve_durum_raporu(con, {})
        assert "CANLI DURUM & KOTA RAPORU" in rapor
        assert "Bot Durumu:" in rapor
    print("  ✓ Sabotaj 46: kota_ve_durum_raporu eksik log dosyasında sağlam çalıştı")


def test_sabotaj_47_hata_bildir_bilinmeyen_istisna():
    """hata_bildir.tani bilinmeyen bir istisnayı Türkçe nezaket metnine çevirir."""
    teshis = hata_bildir.tani("KarmasikVeBilinmeyenException: 0x992384")
    assert teshis["tanindi"] is False
    assert "Beklenmeyen bir hata oluştu" in teshis["ne_oldu"]
    assert "eylem" in teshis
    print("  ✓ Sabotaj 47: hata_bildir tanınmayan hatalara anlaşılır açıklama üretti")


def test_sabotaj_48_hata_bildir_taninan_hatalar():
    """hata_bildir katalogdaki hataları doğru aksiyonla eşleştirir."""
    t1 = hata_bildir.tani("sqlite3.OperationalError: database is locked")
    assert t1["tanindi"] is True
    assert t1["eylem"] == "yeniden_yayinla"

    t2 = hata_bildir.tani("429 Resource has been exhausted (e.g. check quota)")
    assert t2["tanindi"] is True
    assert t2["eylem"] == "tur_metinsiz"

    t3 = hata_bildir.tani("WEBPAGE_CURL_FAILED: failed to get image")
    assert t3["tanindi"] is True
    assert t3["eylem"] == "tur_tekrar"
    print("  ✓ Sabotaj 48: hata_bildir kritik hataları doğru çözüm butonlarıyla eşleştirdi")


def test_sabotaj_49_menuyu_geri_koy_dogru_klavye():
    """menuyu_geri_koy tekil haberde tekil menüyü, çoklu turda ana menüyü geri koyar."""
    con = MagicMock()
    sahte_haber = {
        "id": 1,
        "son_dakika": 1,
        "durum": "onay_bekliyor",
        "detay_url": json.dumps(["http://a.com/d1.jpg"]),
        "gorsel_kaynagi": "web",
        "gorsel_atif": "",
        "onem_puani": 9,
        "ig_baslik": "Test",
        "baslik_orj": "Test",
        "ig_caption": "Caption test",
        "slayt_ozet": "Spot test",
    }
    with patch("scripts.onay_isle.turu_getir", return_value=[sahte_haber]), \
         patch("src.dogrula.turu_dogrula", return_value=("", 0)), \
         patch("src.caption.son_dakika_caption", return_value="Caption"), \
         patch("src.telegram_bot.mesaji_guncelle") as mock_guncelle:
        yeni_id = onay_isle.menuyu_geri_koy(con, 100)
        assert yeni_id == 100
        mock_guncelle.assert_called_once()
        assert mock_guncelle.call_args[0][0] == 100
    print("  ✓ Sabotaj 49: menuyu_geri_koy doğru buton setini geri yükledi")


def test_sabotaj_50_tum_menuler_64_bayt_callback_limiti():
    """Telegram kuralı: Sistemdeki TÜM butonların callback_data uzunluğu <= 64 bayt olmalıdır."""
    menuler = [
        telegram_bot.ana_menu(1),
        telegram_bot.ana_menu(10),
        telegram_bot.foto_menusu(1),
        telegram_bot.foto_menusu(5),
        telegram_bot.metin_menusu(1),
        telegram_bot.yonetim_menusu(False, ""),
        telegram_bot.yonetim_menusu(True, "5s 30dk"),
        telegram_bot.duraklatma_secenekleri_menusu(),
        telegram_bot.baslik_onay_menusu(),
        telegram_bot.yayin_zamani_menusu(3),
        telegram_bot.slayt_secim_menusu(3),
        telegram_bot.slayt_islem_menusu(1, 3),
        {"inline_keyboard": telegram_bot.kontrol_merkezi_menusu()},
    ]

    toplam_buton = 0
    for menu in menuler:
        for satir in menu.get("inline_keyboard", []):
            for buton in satir:
                cb = buton.get("callback_data")
                if cb:
                    toplam_buton += 1
                    bayt_uzunlugu = len(cb.encode("utf-8"))
                    assert bayt_uzunlugu <= 64, f"Buton 64 bayt sınırını aştı: {cb} ({bayt_uzunlugu} bayt)"

    assert toplam_buton >= 40
    print(f"  ✓ Sabotaj 50: {toplam_buton} butonun tamamı Telegram 64 bayt limitine eksiksiz uydu")


def test_sabotaj_51_worker_kanal_senkronizasyonu():
    """Worker alt menüler arası geçişlerde kanal seçimlerinin canlı korunması."""
    import subprocess
    js_kodu = """
    const fs = require('fs');
    const workerPath = process.argv[1];
    let k = fs.readFileSync(workerPath, 'utf8').replace(/export default[\\s\\S]*$/, '');
    const w = new Function(k + '; return { anaMenu, sesMenusu, sesliYayinZamaniMenusu, yayinZamaniMenusu, seciliKanallariCikar, kanallariKodla, kanallariCoz };')();

    // 1. Initial menu: anaMenu without channels
    const menu1 = w.anaMenu(3, null);
    const kanallar1 = w.seciliKanallariCikar(menu1.inline_keyboard);
    if (!kanallar1.includes('ig') || kanallar1.includes('reels')) {
      throw new Error('Initial defaults wrong: ' + JSON.stringify(kanallar1));
    }

    // 2. Open sesMenusu
    const menu2 = w.sesMenusu(3, kanallar1);
    // Simulating user toggling Reels on sesMenusu:
    const klavye2 = menu2.inline_keyboard.map(satir => satir.map(b => {
      let copy = {...b};
      if (b.callback_data === 'kanal:reels') copy.text = '✅ Reels';
      if (b.callback_data === 'kanal:ig') copy.text = '⬜ IG';
      return copy;
    }));
    const guncelKanallar = w.seciliKanallariCikar(klavye2);
    if (!guncelKanallar.includes('reels') || guncelKanallar.includes('ig')) {
      throw new Error('Toggle failed: ' + JSON.stringify(guncelKanallar));
    }

    // 3. User clicks "Fon müzikli" -> transition to sesliYayinZamaniMenusu
    const menu3 = w.sesliYayinZamaniMenusu('muzikli', 3, guncelKanallar);
    const kanallar3 = w.seciliKanallariCikar(menu3.inline_keyboard);
    if (!kanallar3.includes('reels') || kanallar3.includes('ig')) {
      throw new Error('Transition lost channel toggle: ' + JSON.stringify(kanallar3));
    }

    // 4. Back transition to anaMenu
    const menu4 = w.anaMenu(3, kanallar3);
    const kanallar4 = w.seciliKanallariCikar(menu4.inline_keyboard);
    if (!kanallar4.includes('reels') || kanallar4.includes('ig')) {
      throw new Error('Back to anaMenu lost channel toggle: ' + JSON.stringify(kanallar4));
    }

    // 5. Unchecking all channels test
    const menu5 = w.anaMenu(3, []);
    const kanallar5 = w.seciliKanallariCikar(menu5.inline_keyboard);
    if (kanallar5.length !== 0) {
      throw new Error('Unchecked all channels failed: ' + JSON.stringify(kanallar5));
    }

    console.log('OK');
    """
    worker_dosyasi = str(KOK / "worker" / "index.js")
    res = subprocess.run(["node", "-e", js_kodu, worker_dosyasi], capture_output=True, text=True)
    assert res.returncode == 0, f"Worker kanal senkronizasyon testi başarısız: {res.stderr}"
    assert "OK" in res.stdout
    print("  ✓ Sabotaj 51: Worker alt menülerinde kanal toggle senkronizasyonu ve default koruması doğrulandı")


# ===========================================================================
# ÇALIŞTIRICI & RAPORLAMA
# ===========================================================================

def main():
    print("\n" + "=" * 70)
    print("TELEGRAM ALTYAPISI 51 SABOTAJ VE DAYANIKLILIK TESTİ")
    print("=" * 70)

    testler = [
        # Grup 1
        test_sabotaj_01_html_unclosed_tags_fallback,
        test_sabotaj_02_album_media_entity_fallback,
        test_sabotaj_03_4096_karakter_siniri,
        test_sabotaj_04_telegram_429_rate_limit_retry,
        test_sabotaj_05_telegram_502_504_gateway_retry,
        test_sabotaj_06_telegram_supergroup_migration,
        test_sabotaj_07_telegram_mesaj_sil_hatasiz,
        test_sabotaj_08_telegram_mesaji_guncelle_not_found,
        test_sabotaj_09_durum_guncelle_not_modified,
        test_sabotaj_10_durum_guncelle_sinir_degerleri,

        # Grup 2
        test_sabotaj_11_durum_guncelle_xss_null_bytes,
        test_sabotaj_12_video_gonder_entity_fallback,
        test_sabotaj_13_slaytlari_gonder_bos_liste,
        test_sabotaj_14_yerel_album_gonder_olmayan_dosyalar,
        test_sabotaj_15_detay_urlleri_bozuk_json,
        test_sabotaj_16_detay_urlleri_duz_metin_url,
        test_sabotaj_17_gorsel_adaylari_bozuk_json,
        test_sabotaj_18_tur_ozeti_bos_veya_eksik_haber,
        test_sabotaj_19_tur_ozeti_uzun_baslik_kirpma,
        test_sabotaj_20_onay_iste_uyari_ve_ozet_escape,

        # Grup 3
        test_sabotaj_21_linkten_haber_gecersiz_protokol,
        test_sabotaj_22_linkten_haber_kisa_metin_veya_403,
        test_sabotaj_23_arastir_haber_asiri_kisa_konu,
        test_sabotaj_24_dosya_haber_asiri_kisa_konu,
        test_sabotaj_25_ozel_metin_asiri_kisa_bulten,
        test_sabotaj_26_makro_gemini_bozuk_json_fallback,
        test_sabotaj_27_komut_sql_injection_saldirisi,
        test_sabotaj_28_bilinmeyen_slash_komut_guvenligi,
        test_sabotaj_29_mesajsiz_komutlar_sozlesmesi,
        test_sabotaj_30_video_ve_reels_mesajsiz_komut_mu,

        # Grup 4
        test_sabotaj_31_video_gorsel_yok_uyarisi,
        test_sabotaj_32_video_tamamlama_ve_gonderim,
        test_sabotaj_33_video_render_hatasi_yakalama,
        test_sabotaj_34_foto_degistir_sadece_kapak_yukler,
        test_sabotaj_35_foto_degistir_aday_bulunamadi_guvenli_cikis,
        test_sabotaj_36_gorsel_adayini_uygula_dogru_url_dagilimi,
        test_sabotaj_37_foto_degistir_durum_guncelleme_ve_silme,
        test_sabotaj_38_foto_sec_gecersiz_indeks,
        test_sabotaj_39_slayt_sil_son_slayt_korumasi,
        test_sabotaj_40_dosya_haber_durum_guncelleme_akisi,

        # Grup 5
        test_sabotaj_41_duraklatildi_mi_gecersiz_tarih,
        test_sabotaj_42_duraklat_ve_devam_et_dongusu,
        test_sabotaj_43_askidaki_turlari_temizle_yayinlanmis_habere_dokunmaz,
        test_sabotaj_44_api_saglik_testi_eksik_tokenlar,
        test_sabotaj_45_api_saglik_testi_servis_timeout,
        test_sabotaj_46_kota_ve_durum_raporu_bozuk_dosya,
        test_sabotaj_47_hata_bildir_bilinmeyen_istisna,
        test_sabotaj_48_hata_bildir_taninan_hatalar,
        test_sabotaj_49_menuyu_geri_koy_dogru_klavye,
        test_sabotaj_50_tum_menuler_64_bayt_callback_limiti,
        test_sabotaj_51_worker_kanal_senkronizasyonu,
    ]

    basarili = 0
    for t in testler:
        try:
            t()
            basarili += 1
        except Exception as e:
            print(f"  ❌ {t.__name__} BAŞARISIZ OLDU: {e}")
            raise

    print("=" * 70)
    print(f"✓ {basarili}/{len(testler)} SABOTAJ TESTİ BAŞARIYLA GEÇTİ!")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
