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
        self.assertTrue(len(sm) >= 5)
        for ad, durum in sm:
            self.assertTrue(len(ad) > 0)
            self.assertIn("[✓]", durum)

    def test_icerik_ve_rezerv_durumu_donus_yapisi(self):
        ic = kota_uretici.icerik_ve_rezerv_durumu()
        self.assertIn("yayinlanan", ic)
        self.assertIn("taze_havuz", ic)
        self.assertIn("bekleyen", ic)
        self.assertIn("toplam", ic)

    def test_kota_metni_uret_tam_metin_ve_format(self):
        metin = kota_uretici.kota_metni_uret()
        self.assertIn("HABER BOT SİSTEM & KOTA RAPORU", metin)
        self.assertIn("<pre>", metin)
        self.assertIn("</pre>", metin)
        self.assertIn("GITHUB ACTIONS", metin)
        self.assertIn("YAPAY ZEKA", metin)
        self.assertIn("SOSYAL MEDYA & API", metin)

        # <pre> içi satırların genişliği 35 karakter mi?
        pre_ici = metin.split("<pre>")[1].split("</pre>")[0].strip().splitlines()
        for idx, s in enumerate(pre_ici):
            self.assertEqual(
                len(s), 35,
                f"Kart satırı {idx} tam 35 karakter olmalı, {len(s)} bulundu: '{s}'"
            )

    @patch("src.telegram_bot.mesaj_gonder")
    def test_kota_gonder_yeni_mesaj(self, mock_gonder):
        mock_gonder.return_value = 999
        res = kota_uretici.kota_gonder()
        self.assertEqual(res, 999)
        mock_gonder.assert_called_once()


if __name__ == "__main__":
    unittest.main()
