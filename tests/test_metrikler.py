"""
test_metrikler.py — Algoritma geri besleme ve kanca öğrenme testleri.
"""

from pathlib import Path
import sqlite3
import sys
from unittest.mock import MagicMock, patch

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

from src import db, metrikler


def test_ek_kolonlar_metrikleri_iceriyor():
    """db.EK_KOLONLAR sözlüğü yeni etkileşim metrik kolonlarını içermeli."""
    kolonlar = db.EK_KOLONLAR
    assert "erisim" in kolonlar
    assert "kaydetme" in kolonlar
    assert "paylasim" in kolonlar
    assert "yorum" in kolonlar
    assert "begeni" in kolonlar
    assert "metrik_zamani" in kolonlar


def test_en_iyi_kancalari_getir_varsayilan():
    """Boş DB veya con=None durumunda kanıtlanmış şablonlar dönmeli."""
    ornekler = metrikler.en_iyi_kancalari_getir(None, limit=2)
    assert len(ornekler) == 2
    assert "kanca" in ornekler[0]
    assert "baslik" in ornekler[0]


def test_en_iyi_kancalari_getir_db_skor():
    """DB'deki postlar paylaşım ve kaydetme ağırlıklı skorla sıralanmalı."""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    db.kur(con)

    # 2 farklı haber ekle
    con.execute("""
        INSERT INTO haberler (link, baslik_orj, kaynak, kategori, ig_baslik, kanca, vurgu_sayi, vurgu_etiket, durum, gonderim_zamani, erisim, kaydetme, paylasim, begeni)
        VALUES ('http://a.com', 'Düşük Etkileşimli', 'AA', 'turkiye', 'Düşük Etkileşimli', 'DÜŞÜK KANCA', '10', 'adet', 'yayinlandi', '2026-10-18T10:00:00', 100, 2, 1, 10)
    """)
    con.execute("""
        INSERT INTO haberler (link, baslik_orj, kaynak, kategori, ig_baslik, kanca, vurgu_sayi, vurgu_etiket, durum, gonderim_zamani, erisim, kaydetme, paylasim, begeni)
        VALUES ('http://b.com', 'Yüksek Etkileşimli', 'AA', 'turkiye', 'Yüksek Etkileşimli', 'VURUCU KANCA', '500M₺', 'ceza', 'yayinlandi', '2026-10-18T11:00:00', 5000, 150, 80, 400)
    """)
    con.commit()

    en_iyiler = metrikler.en_iyi_kancalari_getir(con, limit=1)
    assert len(en_iyiler) == 1
    assert en_iyiler[0]["kanca"] == "VURUCU KANCA"
    assert en_iyiler[0]["paylasim"] == 80


def test_kanca_ogrenme_konteksti_format():
    """Few-shot prompt bloğu beklenen başlık ve kanca formatını üretmeli."""
    metin = metrikler.kanca_ogrenme_konteksti(None, limit=2)
    assert "İLHAM VERİCİ BAŞARILI KANCA" in metin
    assert "Başlık:" in metin
    assert "Kanca:" in metin


@patch("requests.get")
def test_instagram_metrikleri_guncelle(mock_get):
    """Instagram Graph API çağrısı simüle edilerek DB'nin güncellenmesi sınanır."""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    db.kur(con)

    con.execute("""
        INSERT INTO haberler (link, baslik_orj, kaynak, kategori, durum, ig_post_id, gonderim_zamani)
        VALUES ('http://test.com', 'Test Başlık', 'AA', 'turkiye', 'yayinlandi', '1799999999', '2026-10-18T12:00:00')
    """)
    con.commit()

    # Mock Graph API responses
    # 1. Temel veri: like_count=45, comments_count=12
    # 2. Insights: reach=1200, saved=35, shares=18
    resp_temel = MagicMock()
    resp_temel.status_code = 200
    resp_temel.json.return_value = {"like_count": 45, "comments_count": 12}

    resp_ins = MagicMock()
    resp_ins.status_code = 200
    resp_ins.json.return_value = {
        "data": [
            {"name": "reach", "values": [{"value": 1200}]},
            {"name": "saved", "values": [{"value": 35}]},
            {"name": "shares", "values": [{"value": 18}]},
        ]
    }

    mock_get.side_effect = [resp_temel, resp_ins]

    with patch.dict("os.environ", {"IG_ACCESS_TOKEN": "mock_token"}):
        sonuc = metrikler.instagram_metrikleri_guncelle(con, gun=7)
        assert sonuc["guncellenen"] == 1
        assert sonuc["hata"] == 0

    satir = con.execute("SELECT erisim, kaydetme, paylasim, yorum, begeni FROM haberler WHERE ig_post_id = '1799999999'").fetchone()
    assert satir["erisim"] == 1200
    assert satir["kaydetme"] == 35
    assert satir["paylasim"] == 18
    assert satir["yorum"] == 12
    assert satir["begeni"] == 45


def test_twitter_zincir_tekil_coklu_slayt():
    """Tekil bir haber 3 slayta sahip olduğunda 3 halkalık zincir üretmeli."""
    from src import caption
    haber = [{
        "ig_baslik": "Milyonlarca Araç Sahibini İlgilendiren Karar",
        "slayt_ozet": "Kasko ve sigorta primlerinde tavan fiyat değişti.",
        "detay_metni": "Sigortacılık Kurumu yeni tarifeyi duyurdu.\n\nPrim artışları enflasyona endekslendi.",
        "sana_etkisi": "Poliçe yenileme maliyeti %15 düşebilir.",
        "etkilesim_sorusu": "Sizce bu indirim yeterli mi?",
        "kaynak": "AA",
        "son_dakika": 0,
    }]
    urller = ["http://img1.jpg", "http://img2.jpg", "http://img3.jpg"]
    halkalar = caption.twitter_zincir_metinleri(haber, urller=urller)
    assert len(halkalar) == 3
    assert "Milyonlarca Araç" in halkalar[0]
    assert "zincirimizde" in halkalar[0]
    assert "Detay (1)" in halkalar[1]
    assert "Detay (2)" in halkalar[2]
    # Her tweet 280 karakterden kısa olmalı
    for h in halkalar:
        assert len(h) <= 280
