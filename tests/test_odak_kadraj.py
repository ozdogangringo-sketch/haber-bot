"""
tests/test_odak_kadraj.py — Otomatik Odak (odak_x_yuzde) ve Telegram Kadraj Testleri.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

from PIL import Image

from src import gorsel_denetim, slaytlar, make_image
from scripts import onay_isle


class TestOdakKadraj(unittest.TestCase):
    def test_odak_x_al_sinirlar_ve_varsayilan(self):
        """odak_x_yuzde sınırları, 0 değeri ve varsayılan 50 denetlenir."""
        self.assertEqual(slaytlar._odak_x_al({}), 50)
        self.assertEqual(slaytlar._odak_x_al({"odak_x_yuzde": None}), 50)
        self.assertEqual(slaytlar._odak_x_al({"odak_x_yuzde": ""}), 50)
        # 0 en sol kenardır; 50'ye düşmemeli
        self.assertEqual(slaytlar._odak_x_al({"odak_x_yuzde": 0}), 0)
        self.assertEqual(slaytlar._odak_x_al({"odak_x_yuzde": "0"}), 0)
        self.assertEqual(slaytlar._odak_x_al({"odak_x_yuzde": 35}), 35)
        self.assertEqual(slaytlar._odak_x_al({"odak_x_yuzde": 100}), 100)
        self.assertEqual(slaytlar._odak_x_al({"odak_x_yuzde": 150}), 100)
        self.assertEqual(slaytlar._odak_x_al({"odak_x_yuzde": -20}), 0)

    @patch("src.gorsel_denetim.gorseli_denetle")
    def test_odak_noktasi_tespit_et_mock(self, mock_denetle):
        """Gemini Vision'ın döndürdüğü odak_x_yuzde başarıyla okunur."""
        img = Image.new("RGB", (1200, 675), (50, 60, 70))
        mock_denetle.return_value = {
            "fotografta_ne_var": "Bakan Şimşek solda konuşuyor",
            "konuyu_gosteriyor_mu": True,
            "baglam_uyuyor_mu": True,
            "sebep": "Uygun",
            "odak_x_yuzde": 28,
        }
        odak = gorsel_denetim.odak_noktasi_tespit_et(img, baslik="Ekonomi Zirvesi")
        self.assertEqual(odak, 28)

        # Hata / None durumunda 50 döner
        mock_denetle.return_value = None
        self.assertEqual(gorsel_denetim.odak_noktasi_tespit_et(img), 50)

    def test_fotograftan_arkaplan_odak_oranlari(self):
        """Yatay fotoğrafta sol, orta ve sağ kadraj 1080x1920 tuvalde sorunsuz üretilir."""
        img = Image.new("RGB", (1600, 900), (30, 40, 50))
        bg_sol = make_image.fotograftan_arkaplan(img, 1080, 1920, odak_x_yuzde=0)
        bg_orta = make_image.fotograftan_arkaplan(img, 1080, 1920, odak_x_yuzde=50)
        bg_sag = make_image.fotograftan_arkaplan(img, 1080, 1920, odak_x_yuzde=100)
        self.assertEqual(bg_sol.size, (1080, 1920))
        self.assertEqual(bg_orta.size, (1080, 1920))
        self.assertEqual(bg_sag.size, (1080, 1920))

    @patch("scripts.onay_isle._gorsel_adayini_uygula")
    @patch("scripts.onay_isle.upload_image.hepsini_yukle")
    @patch("src.slaytlar.son_dakika_uret")
    @patch("scripts.onay_isle.telegram_bot.mesaj_gonder")
    def test_foto_odak_islemi_akisi(self, mock_msg, mock_uret, mock_yukle, mock_uygula):
        """Telegram'dan gelen kadraj kaydırma komutu DB'yi günceller ve kapağı yeniden çizer."""
        con = MagicMock()
        h = {"id": 142, "ig_baslik": "Merkez Bankası Faizi Açıkladı", "son_dakika": 1, "gorsel_deneme": 0}
        mock_uret.return_value = [{"yol": "/tmp/s1.jpg", "katman": "haber", "atif": "AA"}]
        mock_yukle.return_value = [{"url": "https://img.cdn/s1.jpg"}]
        mock_uygula.return_value = 0

        ayarlar = {"gorsel": {"genislik": 1080, "yukseklik": 1920}}
        res = onay_isle.foto_odak_islemi(con, ayarlar, [h], mesaj_id=999, odak_yuzde=20)

        self.assertEqual(res, 0)
        self.assertEqual(h["odak_x_yuzde"], 20)
        con.execute.assert_called_with("UPDATE haberler SET odak_x_yuzde = ? WHERE id = ?", (20, 142))
        con.commit.assert_called()
        self.assertTrue(mock_uret.called)
        self.assertTrue(mock_uygula.called)


if __name__ == "__main__":
    unittest.main()
