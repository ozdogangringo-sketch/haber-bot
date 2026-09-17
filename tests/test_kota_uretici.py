"""
tests/test_kota_uretici.py — Kompakt Kota ve Sistem Tablosu Testleri
"""

import unittest
from unittest.mock import patch, MagicMock

from src import kota_uretici


class TestKotaUretici(unittest.TestCase):
    def test_cizgi_bar_uzunluk_ve_sinirlar(self):
        self.assertEqual(kota_uretici.cizgi_bar(0, 10), "□□□□□□□□□□")
        self.assertEqual(kota_uretici.cizgi_bar(100, 10), "■■■■■■■■■■")
        self.assertEqual(kota_uretici.cizgi_bar(50, 10), "■■■■■□□□□□")
        self.assertEqual(len(kota_uretici.cizgi_bar(33, 10)), 10)
        self.assertEqual(len(kota_uretici.cizgi_bar(-10, 10)), 10)
        self.assertEqual(len(kota_uretici.cizgi_bar(150, 10)), 10)

    def test_sifirlanma_fonksiyonlari(self):
        ay = kota_uretici.sifirlanma_ay_basi()
        self.assertIn("gun", ay)
        self.assertRegex(ay, r"\d{2}\.\d{2} \(\d+ gun\)")

        gece = kota_uretici.sifirlanma_gece_yarisi()
        self.assertIn("00:00", gece)
        self.assertIn("saat", gece)

        yt = kota_uretici.sifirlanma_youtube()
        self.assertIn("10:00 TSI", yt)

        saat = kota_uretici.sifirlanma_saatlik()
        self.assertIn("Saatlik", saat)
        self.assertIn("d)", saat)

    def test_cloudflare_kullanimi(self):
        cf = kota_uretici.cloudflare_kullanimi()
        self.assertIn("worker_istek", cf)
        self.assertIn("kv_yazma", cf)
        self.assertIn("r2_depolama", cf)
        self.assertIn("sifirlanma", cf)

    def test_github_rest_api_kullanimi(self):
        gh_api = kota_uretici.github_rest_api_kullanimi()
        self.assertIn("istek", gh_api)
        self.assertIn("sifirlanma", gh_api)

    def test_sosyal_medya_ve_yayin_kotalari(self):
        sm = kota_uretici.sosyal_medya_ve_yayin_kotalari()
        self.assertIn("ig_kullanilan", sm)
        self.assertIn("ig_kalan", sm)
        self.assertIn("yt_birim", sm)
        self.assertIn("yt_kalan_shorts", sm)
        self.assertIn("yt_sifirlanma", sm)
        self.assertIn("db_mb", sm)
        self.assertIn("git_mb", sm)
        self.assertIn("disk_gb", sm)

    def test_format_kompakt_kutu_35_karakter_genislik(self):
        """Monospace kartın her satırı tam 35 karakter olmalı (telefonda kayma yapmaz)."""
        bolumler = [
            ("BOLUM 1", [("Anahtar 1", "Deger 1"), ("Anahtar 2", "Deger 2")]),
            ("BOLUM 2", [("Cok Uzun Bir Anahtar Ismi", "123,456 dk")]),
        ]
        kutu = kota_uretici.format_kompakt_kutu(
            baslik="TEST BASLIK",
            tarih_str="18.09.2026 02:00 UTC",
            bolumler=bolumler,
            w_k=15,
            w_v=14,
        )
        satirlar = kutu.splitlines()
        self.assertEqual(satirlar[0], "<pre>")
        self.assertEqual(satirlar[-1], "</pre>")

        govde = satirlar[1:-1]
        for idx, s in enumerate(govde):
            self.assertEqual(
                len(s), 35,
                f"Satır {idx} genişliği 35 değil ({len(s)}): '{s}'"
            )

    def test_github_actions_kullanimi_donus_yapisi(self):
        gh = kota_uretici.github_actions_kullanimi()
        self.assertIn("harcanan_dk", gh)
        self.assertIn("kalan_dk", gh)
        self.assertIn("yuzde", gh)
        self.assertIn("toplam_kosu", gh)
        self.assertGreaterEqual(gh["harcanan_dk"], 0)
        self.assertGreaterEqual(gh["kalan_dk"], 0)

    def test_yapay_zeka_kullanimi_donus_yapisi(self):
        ai = kota_uretici.yapay_zeka_kullanimi()
        self.assertIn("bu_ay_haber", ai)
        self.assertIn("bugun_haber", ai)
        self.assertIn("tahmini_token", ai)
        self.assertIn("gunluk_cagri", ai)
        self.assertIn("kalan_cagri", ai)

    def test_sosyal_medya_sagligi_donus_yapisi(self):
        sm = kota_uretici.sosyal_medya_ve_api_sagligi()
        self.assertIsInstance(sm, list)
        self.assertTrue(len(sm) >= 4)
        for ad, durum in sm:
            self.assertTrue(len(ad) > 0)
            self.assertIn("[✓]", durum)

    def test_icerik_ve_rezerv_durumu_donus_yapisi(self):
        ic = kota_uretici.icerik_ve_rezerv_durumu()
        self.assertIn("yayinlanan", ic)
        self.assertIn("taze_havuz", ic)
        self.assertIn("bekleyen", ic)
        self.assertIn("toplam", ic)

    def test_kota_secenek_menusu(self):
        metin, butonlar = kota_uretici.kota_secenek_menusu()
        self.assertIn("HABER BOT SİSTEM & KOTA İZLEME MERKEZİ", metin)
        self.assertIn("1. Bulut, Yapay Zeka & API Kotaları", metin)
        self.assertIn("2. Sosyal Medya, Yayın & Depolama Kotaları", metin)
        self.assertIn("inline_keyboard", butonlar)
        tous = [btn["callback_data"] for row in butonlar["inline_keyboard"] for btn in row]
        self.assertIn("kota_kat:1", tous)
        self.assertIn("kota_kat:2", tous)
        self.assertIn("yonetim_panel", tous)

    def test_kota_metni_uret_kategori_1(self):
        metin = kota_uretici.kota_metni_uret(kategori=1)
        self.assertIn("HABER BOT BULUT, AI & API KOTALARI", metin)
        self.assertIn("<pre>", metin)
        self.assertIn("</pre>", metin)
        self.assertIn("GITHUB ACTIONS (3.000 dk)", metin)
        self.assertIn("YAPAY ZEKA (Gemini AI)", metin)
        self.assertIn("CLOUDFLARE (Worker & KV)", metin)
        self.assertIn("GITHUB REST API", metin)

        # <pre> içi satırların genişliği 35 karakter mi?
        pre_ici = metin.split("<pre>")[1].split("</pre>")[0].strip().splitlines()
        for idx, s in enumerate(pre_ici):
            self.assertEqual(
                len(s), 35,
                f"Kart satırı {idx} tam 35 karakter olmalı, {len(s)} bulundu: '{s}'"
            )

    def test_kota_metni_uret_kategori_2(self):
        metin = kota_uretici.kota_metni_uret(kategori=2)
        self.assertIn("HABER BOT SOSYAL MEDYA & YAYIN KOTALARI", metin)
        self.assertIn("<pre>", metin)
        self.assertIn("</pre>", metin)
        self.assertIn("INSTAGRAM GRAPH API", metin)
        self.assertIn("YOUTUBE DATA API", metin)
        self.assertIn("TOKEN & SERVIS GUVENCESI", metin)
        self.assertIn("DEPOLAMA & VERITABANI", metin)
        self.assertIn("YAYIN HAVUZU & REZERV", metin)

        # <pre> içi satırların genişliği 35 karakter mi?
        pre_ici = metin.split("<pre>")[1].split("</pre>")[0].strip().splitlines()
        for idx, s in enumerate(pre_ici):
            self.assertEqual(
                len(s), 35,
                f"Kart satırı {idx} tam 35 karakter olmalı, {len(s)} bulundu: '{s}'"
            )

    @patch("src.telegram_bot.mesaj_gonder")
    @patch("src.telegram_bot.mesaji_guncelle")
    def test_kota_gonder(self, mock_guncelle, mock_gonder):
        mock_gonder.return_value = 999
        mock_guncelle.return_value = 888

        # 1. Menü gönderimi
        res = kota_uretici.kota_gonder(kategori="menu")
        self.assertEqual(res, 999)
        mock_gonder.assert_called_once()
        args, kwargs = mock_gonder.call_args
        self.assertIn("HABER BOT SİSTEM & KOTA İZLEME MERKEZİ", args[0])

        # 2. Kategori 1 güncelleme
        res = kota_uretici.kota_gonder(mesaj_id=888, kategori=1)
        self.assertEqual(res, 888)
        mock_guncelle.assert_called_once()
        args, kwargs = mock_guncelle.call_args
        self.assertEqual(args[0], 888)
        self.assertIn("BULUT, AI & API KOTALARI", args[1])

        # 3. Kategori 2 gönderimi
        res = kota_uretici.kota_gonder(mesaj_id=None, kategori=2)
        self.assertEqual(res, 999)
        self.assertEqual(mock_gonder.call_count, 2)
        args, kwargs = mock_gonder.call_args
        self.assertIn("SOSYAL MEDYA & YAYIN KOTALARI", args[0])


if __name__ == "__main__":
    unittest.main()
