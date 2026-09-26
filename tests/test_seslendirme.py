"""
tests/test_seslendirme.py — "🎙️ Sesli Yayınla" sözleşmesi (2026-09-26, postedm'den).

  * Okunan metin slayttakiyle AYNI: içerik filtresinden geçmiş başlık + özet.
  * Yalnızca kapak okunur; "basliklar" kipinde turdaki her haberin başlığı kendi
    slaytında. Ekonomi turunun ısı haritası/tablo slaytında haber metni okunmaz.
  * Ses config.yaml › seslendirme'den; kütüphaneden kalkarsa yedeğe düşülür.
  * Çıktı her zaman "_sesli": youtube_icin_sesli_video_hazirla adında "_yt" olmayan
    videonun sesini fon müziğiyle DEĞİŞTİRİYORDU — anlatım silinirdi.
  * Kapanış çağrısı son slaytın sonuna yaslanır; bu projede video sonu = süre toplamı.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import yaml  # noqa: E402

from src import ses, video, youtube  # noqa: E402

AYARLAR = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))


def _haber(i, **ek):
    h = {"id": i, "ig_baslik": f"Başlık {i}", "baslik_orj": f"Orijinal {i}", "slayt_ozet": f"Özet cümlesi {i}",
         "kategori": "turkiye", "tur": "sabah", "detay_metni": ""}
    h.update(ek)
    return h


def _ayar(**seslendirme):
    a = dict(AYARLAR)
    a["seslendirme"] = {**AYARLAR["seslendirme"], **seslendirme}
    return a


class TestNeOkunur(unittest.TestCase):
    def test_tek_haberde_kapak_baslik_ve_ozet_detay_sessiz(self):
        """Son dakika: 1 haber + detay sayfaları; tur_kipi ne olursa olsun kapak okunur."""
        for kip in ("basliklar", "kapak"):
            self.assertEqual(ses.slayt_metinleri([_haber(1)], _ayar(tur_kipi=kip), 3),
                             ["Başlık 1. Özet cümlesi 1.", None, None])

    def test_turda_yalniz_basliklar(self):
        """Kullanıcı kararı 2026-09-26: elle tetiklenen turda yalnızca başlıklar okunur."""
        self.assertEqual(AYARLAR["seslendirme"]["tur_kipi"], "basliklar")
        self.assertEqual(ses.slayt_metinleri([_haber(1), _haber(2), _haber(3)], AYARLAR, 3),
                         ["Başlık 1.", "Başlık 2.", "Başlık 3."])

    def test_tur_kapak_kipi_yalniz_ilk_slayt(self):
        self.assertEqual(ses.slayt_metinleri([_haber(1), _haber(2), _haber(3)], _ayar(tur_kipi="kapak"), 3),
                         ["Başlık 1. Özet cümlesi 1.", None, None])

    def test_ekonomi_turunda_okunmaz(self):
        self.assertEqual(ses.slayt_metinleri([_haber(1, tur="ekonomi")], AYARLAR, 3), [None, None, None])

    def test_slayttaki_filtrelenmis_metin_okunur(self):
        """İçerik filtresinin yumuşattığı kelime seste ham okunmamalı."""
        with patch("src.slaytlar._slayt_metni", side_effect=lambda h, alan, a: f"filtreli-{alan}") as f:
            metin = ses.slayt_metinleri([_haber(1)], AYARLAR, 1)[0]
        self.assertEqual(metin, "filtreli-ig_baslik. filtreli-slayt_ozet.")
        self.assertTrue(f.called)

    def test_ozet_basligi_tekrarlarsa_bir_kez(self):
        self.assertEqual(ses.slayt_metinleri([_haber(1, slayt_ozet="Başlık 1")], AYARLAR, 1), ["Başlık 1."])

    def test_kapanis_cagrisi_begenin_yok(self):
        cagri = ses.kapanis_cagrisi(AYARLAR)
        self.assertIn("istemiyorsanız", cagri)
        self.assertNotIn("beğen", cagri.lower())


class TestSesSecimi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cikti = Path(self.tmp.name) / "s.mp3"

    def tearDown(self):
        self.tmp.cleanup()

    def _yanit(self, kod, icerik=b"x" * 600, metin=""):
        r = MagicMock()
        r.status_code, r.content, r.text = kod, icerik, metin
        return r

    @patch.dict("os.environ", {"ELEVENLABS_API_KEY": "sahte", "ELEVENLABS_VOICE_ID": "ESKI"})
    @patch("src.ses.requests.post")
    def test_config_sesi_ayarlari_ve_okunus(self, post):
        post.return_value = self._yanit(200)
        self.assertEqual(ses.metin_seslendir("Hz. Ali 1/5000 ölçekli planı açıkladı.", AYARLAR, self.cikti), self.cikti)
        self.assertIn(AYARLAR["seslendirme"]["ses_id"], post.call_args[0][0])
        self.assertNotIn("ESKI", post.call_args[0][0])
        self.assertEqual(post.call_args.kwargs["json"]["voice_settings"], AYARLAR["seslendirme"]["ayarlar"])
        self.assertEqual(post.call_args.kwargs["json"]["text"], "Hazreti Ali beş binde bir ölçekli planı açıkladı.")

    @patch.dict("os.environ", {"ELEVENLABS_API_KEY": "sahte"})
    @patch("src.ses.time.sleep")
    @patch("src.ses.requests.post")
    def test_ses_kalkinca_yedege_kota_bitince_hemen_vazgecer(self, post, _):
        post.side_effect = [self._yanit(404, b"", '{"detail":{"status":"voice_not_found"}}'), self._yanit(200)]
        self.assertEqual(ses.metin_seslendir("Deneme.", AYARLAR, self.cikti), self.cikti)
        self.assertIn(AYARLAR["seslendirme"]["yedek_ses_id"], post.call_args_list[1][0][0])
        post.reset_mock(side_effect=True)
        post.return_value = self._yanit(402, b"", "quota")
        self.assertIsNone(ses.metin_seslendir("Deneme.", AYARLAR, self.cikti))
        self.assertEqual(post.call_count, 1)

    @patch.dict("os.environ", {"ELEVENLABS_API_KEY": ""})
    def test_anahtar_yoksa_sessiz(self):
        self.assertIsNone(ses.metin_seslendir("Deneme.", AYARLAR, self.cikti))


class TestKaristirma(unittest.TestCase):
    def _komut(self, konusma, muzik):
        with tempfile.TemporaryDirectory() as d, patch("src.ses.subprocess.run") as run:
            v = Path(d) / "reels_1.mp4"
            cikti = ses.sesli_video_hazirla(v, Path(d) / "k.wav" if konusma else None, muzik, AYARLAR)
        return cikti, " ".join(run.call_args[0][0])

    def test_kipler(self):
        cikti, k = self._komut(True, True)
        self.assertTrue(cikti.name.endswith("_sesli.mp4"))
        self.assertIn("volume=0.14", k)
        self.assertIn("loudnorm=I=-14", k)
        _, k = self._komut(True, False)
        self.assertNotIn("haber_fon", k)
        self.assertIn("loudnorm", k)
        _, k = self._komut(False, True)
        self.assertIn("volume=0.20", k)  # seslendirme düştü: eskisi gibi fon müzikli
        cikti, k = self._komut(False, False)
        self.assertIn("-c copy", k)  # müziksiz ve sessiz: yükleyici müzik eklemesin diye yine "_sesli"
        self.assertTrue(cikti.name.endswith("_sesli.mp4"))

    @patch("subprocess.run")
    def test_youtube_seslendirmeyi_silmez(self, run):
        with tempfile.TemporaryDirectory() as d:
            v = Path(d) / "reels_1_sesli.mp4"
            v.write_bytes(b"v")
            self.assertEqual(youtube.youtube_icin_sesli_video_hazirla(v), v)
        run.assert_not_called()


class TestZamanlama(unittest.TestCase):
    def _uret(self, kip="kapak", anahtar=True):
        yakalanan = {}
        sesler = {}

        def tts(metin, ayarlar=None, cikti_yolu=None):
            if not anahtar:
                return None
            sesler[metin] = Path(f"/tmp/{len(sesler)}.mp3")
            return sesler[metin]

        def reels(gorseller, **kw):
            yakalanan["sureler"] = kw["slayt_sureleri"]
            return Path("/tmp/reels_x.mp4")

        cagri = Path("/tmp/cagri.mp3")
        with patch.object(ses, "metin_seslendir", side_effect=tts), \
             patch.object(ses, "_onbellekli_seslendir", return_value=cagri), \
             patch.object(ses, "ses_suresi_ogren", side_effect=lambda y: 3.0 if y == cagri else (9.0 if str(y).endswith("0.mp3") else 2.0)), \
             patch.object(video, "slayt_surelerini_hesapla", return_value=[4.2, 5.0, 5.0]), \
             patch.object(video, "slaytlardan_reels_uret", side_effect=reels), \
             patch.object(ses, "_anlatim_izi", side_effect=lambda p, t, c: yakalanan.update(parcalar=p, toplam=t) or c), \
             patch.object(ses, "sesli_video_hazirla", side_effect=lambda v, k, m, a=None, **kw: yakalanan.update(konusma=k, muzik=m) or Path("/tmp/reels_x_sesli.mp4")):
            sonuc = {}
            ses.anlatimli_video_uret(["a.jpg", "b.jpg", "c.jpg"], [_haber(1), _haber(2), _haber(3)],
                                     _ayar(tur_kipi=kip), muzik=True, sonuc=sonuc)
        yakalanan["sonuc"] = sonuc
        return yakalanan, cagri

    def test_kapak_ses_bitene_kadar_cagri_sonda(self):
        y, cagri = self._uret()
        self.assertEqual(y["sureler"][0], 10.7)  # 0.4 + 9 + 0.8 + 0.5
        self.assertEqual(y["parcalar"][0][1], ses.ANLATIM_ONCESI_SN)
        cagri_bas = y["parcalar"][-1][1]
        self.assertEqual(y["parcalar"][-1][0], cagri)
        self.assertGreaterEqual(cagri_bas, sum(y["sureler"][:-1]) + ses.CAGRI_ARASI_SN)
        self.assertAlmostEqual(cagri_bas + 3.0 + ses.ANLATIM_SONRASI_SN, sum(y["sureler"]))
        self.assertTrue(y["sonuc"]["anlatim"])

    def test_basliklar_kipinde_her_ses_kendi_slaytinda(self):
        y, _ = self._uret(kip="basliklar")
        baslangiclar = [p[1] for p in y["parcalar"][:3]]
        self.assertEqual(baslangiclar, [ses.ANLATIM_ONCESI_SN + sum(y["sureler"][:i]) for i in range(3)])

    def test_anahtar_yoksa_seslendirmesiz_ama_muzikli(self):
        y, _ = self._uret(anahtar=False)
        self.assertFalse(y["sonuc"]["anlatim"])
        self.assertIsNone(y["konusma"])
        self.assertTrue(y["muzik"])
        self.assertNotIn("parcalar", y)


class TestYayinBaglantisi(unittest.TestCase):
    def test_onay_isle_ses_kipini_okur_ve_kanal_notuna_karistirmaz(self):
        kaynak = (KOK / "scripts" / "onay_isle.py").read_text(encoding="utf-8")
        govde = kaynak[kaynak.index("def yayinla(con, ayarlar, haberler"):kaynak.index("\ndef kanal_telafi_et(")]
        self.assertIn('"ses_muzikli" in ses_kumesi', govde)
        self.assertIn("ses.anlatimli_video_uret(", govde)
        self.assertIn("{tt_notu}{ses_notu}", govde)
        self.assertNotIn("⚠️", govde[govde.index("ses_notu = ("):govde.index("elif dikey_gorseller:")])

    def test_youtube_ve_facebook_her_turlu_sesli_ve_muzikli(self):
        """Kullanıcı kuralı 2026-09-26: YouTube ve Facebook her türlü sesli ve fon müzikli yayınlamalı."""
        kaynak = (KOK / "scripts" / "onay_isle.py").read_text(encoding="utf-8")
        govde = kaynak[kaynak.index("def yayinla(con, ayarlar, haberler"):kaynak.index("\ndef kanal_telafi_et(")]
        self.assertIn('ses_modu == "muziksiz" and ses_sonucu.get("video_muzikli")', govde)
        self.assertIn('sesli = ses.anlatimli_video_uret(dikey_gorseller, haberler, ayarlar,', govde)
        self.assertIn('muzik=True, sonuc=ses_sonucu_yt)', govde)

    def test_ses_modunda_instagrama_gonderi_degil_reels_gider(self):
        """Kullanıcı kuralı 2026-09-26: sesli video seçildiğinde IG gönderisi değil Reels yayınlanmalı."""
        kaynak = (KOK / "scripts" / "onay_isle.py").read_text(encoding="utf-8")
        govde = kaynak[kaynak.index("def yayinla(con, ayarlar, haberler"):kaynak.index("\ndef kanal_telafi_et(")]
        self.assertIn("if ses_modu:", govde)
        self.assertIn("paylas_reels = True", govde)
        self.assertIn("paylas_ig = False", govde)

    def test_her_durumda_telegrama_video_ve_aciklama_iletilir(self):
        """Kullanıcı kuralı 2026-09-26: her türlü telegrama video ve açıklaması düşsün."""
        kaynak = (KOK / "scripts" / "onay_isle.py").read_text(encoding="utf-8")
        govde = kaynak[kaynak.index("def yayinla(con, ayarlar, haberler"):kaynak.index("\ndef kanal_telafi_et(")]
        self.assertIn("v_telegram = paylasilan_video_yolu or sesli_video_yolu or sessiz_video_yolu", govde)
        self.assertIn("telegram_bot.video_gonder(", govde)
        self.assertIn("Reels Açıklama Metni (Kopyalamak için dokunun)", govde)

    def test_reels_instagram_api_ile_yayinlanir(self):
        """Reels yayını Instagram Graph API reels_yayinla üzerinden yapılır."""
        kaynak = (KOK / "scripts" / "onay_isle.py").read_text(encoding="utf-8")
        govde = kaynak[kaynak.index("def _is_instagram():"):kaynak.index("def _is_story():")]
        self.assertIn("instagram.reels_yayinla(", govde)
        self.assertIn("instagram.post_baglantisi(", govde)


if __name__ == "__main__":
    unittest.main()

