"""
tests/test_okunus.py — Seslendirme okunuşu: sabotaj ve özellik testleri.

postedm'den taşındı (2026-09-26); src/okunus.py iki projede aynı.

NİYE VAR: ses metni gördüğünü okur. Başka bir üründe "Hz." "hezt" diye okundu
(doğrusu "Hazreti"); bizim örnekte "1/5000" "bir bölü beş bin", "0.50" "sıfır
nokta elli" olacaktı. Her satır bir okuma hatası sınıfıdır. İkinci yarı tabloya
güvenmez: rastgele sayıları yazıya çevirip geri çözer, çıktıyı ikinci kez
çevirip değişmediğini, rastgele karışık girdide çökmediğini denetler.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # tests/ doğrudan çalıştırılabilsin

import random
import re
import unicodedata
import unittest

from src.okunus import okunusa_cevir, sayi_yazi, sira_yazi

TABLO = [
    # Unvan ve kısaltmalar (kullanıcının örneği: "Hz." → "hezt")
    ("Hz. Muhammed", "Hazreti Muhammed"),
    ("Hz.Ali", "Hazreti Ali"),
    ("Prof. Dr. Ahmet Yılmaz", "Profesör Doktor Ahmet Yılmaz"),
    ("Doç.Dr. Mehmet", "Doçent Doktor Mehmet"),
    ("Av. Ayşe Kaya", "Avukat Ayşe Kaya"),
    ("tapu, imar vb. belgeler", "tapu, imar ve benzeri belgeler"),
    ("tapu, imar vb. Sonra", "tapu, imar ve benzeri. Sonra"),
    ("Alibey Mah. Albay Cad. Kılıç Sok. Apt.", "Alibey Mahallesi Albay Caddesi Kılıç Sokağı Apartmanı"),
    ("No: 58/A", "numara elli sekiz A"),
    ("T.C. Kimlik", "Türkiye Cumhuriyeti Kimlik"),
    ("5510 s. Kanun", "beş bin beş yüz on sayılı Kanun"),
    # Sıra sayıları
    ("3194 sayılı Kanunun 8. maddesi", "üç bin yüz doksan dört sayılı Kanunun sekizinci maddesi"),
    ("18. madde", "on sekizinci madde"),
    ("18'inci madde", "on sekizinci madde"),
    ("3. Kat", "üçüncü Kat"),
    ("4. etap", "dördüncü etap"),
    ("II. Etap", "ikinci Etap"),
    ("IV. Bölge", "dördüncü Bölge"),
    ("süre 30. Sonra", "süre otuz. Sonra"),  # cümle sonu, sıra sayısı değil
    # Kesir, ölçek, ada/parsel
    ("1/5000 ölçekli", "beş binde bir ölçekli"),
    ("1/5.000 ölçekli", "beş binde bir ölçekli"),
    ("1:5000 ölçekli", "beş binde bir ölçekli"),
    ("3/4 hisse", "dörtte üç hisse"),
    ("1/8 hisse", "sekizde bir hisse"),
    ("1/2 hisse", "yarı hisse"),  # "ikide bir" deyim olarak "sık sık"
    ("Ada/Parsel: 142/85", "yüz kırk iki ada seksen beş parsel"),
    ("142/85", "yüz kırk iki bölü seksen beş"),  # etiketsiz çift: kesir sanılmaz
    # Yüzde, ondalık, binlik
    ("%45 kesinti", "yüzde kırk beş kesinti"),
    ("%45'i", "yüzde kırk beşi"),
    ("45% artış", "yüzde kırk beş artış"),
    ("%8,4 düştü", "yüzde sekiz virgül dört düştü"),
    ("KAKS 0.50 ila 0.85", "kaks sıfır virgül elli ila sıfır virgül seksen beş"),
    ("E: 0,60", "emsal sıfır virgül altmış"),
    ("0,05", "sıfır virgül sıfır beş"),
    ("0.850", "sıfır virgül sekiz yüz elli"),
    ("2.5 kat", "iki virgül beş kat"),
    ("1.500 TL", "bin beş yüz lira"),
    ("1.000.000", "bir milyon"),
    ("1,5 milyon TL", "bir virgül beş milyon lira"),
    # Para ve birim
    ("18.000 TL/m²", "metrekaresi on sekiz bin lira"),
    ("18.000 TL/m²'den satıldı", "metrekaresi on sekiz bin liradan satıldı"),  # canlı denemede "başına'den"
    ("m²'si 500 lira", "metrekaresi beş yüz lira"),
    ("5.311.000 TL", "beş milyon üç yüz on bir bin lira"),
    ("₺500", "beş yüz lira"),
    ("$1.250", "bin iki yüz elli dolar"),
    ("45 TL'lik", "kırk beş liralık"),
    ("TL'ye", "liraya"),
    ("100 tl", "yüz lira"),
    ("250 m² arsa", "iki yüz elli metrekare arsa"),
    ("250m²", "iki yüz elli metrekare"),
    ("m² fiyatı", "metrekare fiyatı"),
    ("5 Km", "beş kilometre"),
    ("~50 m", "yaklaşık elli metre"),
    ("Hmax: 9.50 m", "azami yükseklik: dokuz virgül elli metre"),
    ("25°", "yirmi beş derece"),
    ("±5", "artı eksi beş"),
    ("3+1 daire", "üç artı bir daire"),
    ("10x20 m", "on çarpı yirmi metre"),
    # Tarih ve saat
    ("25.09.2026 tarihinde", "yirmi beş Eylül iki bin yirmi altı tarihinde"),
    ("25/09/2026", "yirmi beş Eylül iki bin yirmi altı"),
    ("2026-09-25", "yirmi beş Eylül iki bin yirmi altı"),
    ("saat 14.00'te", "saat on dörtte"),
    ("saat 14.00'e kadar", "saat on dörde kadar"),  # canlı denemede "on dörte"
    ("4'e bölündü", "dörde bölündü"),
    ("14'ten", "on dörtten"),
    ("40'a", "kırka"),
    ("14:30", "on dört otuz"),
    ("2026'da", "iki bin yirmi altıda"),
    ("30'dan fazla", "otuzdan fazla"),
    ("1990'lı yıllar", "bin dokuz yüz doksanlı yıllar"),
    # Kısaltmalar olduğu gibi (ses doğru okuyor; harf harf yazmak bozuyordu — ölçüldü),
    # kelime gibi okunanlar küçültülür, bilinen kurumlar açılır
    ("KDV'li fiyat", "KDV'li fiyat"),
    ("SGK'ya", "SGK'ya"),
    ("EDM Yapı", "EDM Yapı"),
    ("AVM", "AVM"),
    ("OSB", "OSB"),
    ("TBMM", "TBMM"),
    ("EPDK", "EPDK"),
    ("TOKİ", "toki"),
    ("İBB'nin kararı", "İstanbul Büyükşehir Belediyesinin kararı"),
    ("TKGM", "Tapu ve Kadastro Genel Müdürlüğü"),
    ("DOP", "düzenleme ortaklık payı"),
    ("E-5 ve D-100", "E-5 ve D-100"),  # "D yüz" → "Kazada 100" okundu
    ("A blok", "A blok"),  # küçük "a" yutuluyordu
    ("Uluslar A Ligi'ne", "Uluslar A Ligi'ne"),
    # Büyük harfli manşet: kelimeler harf harf okunmaz
    ("YENİ İMAR PLANI ASKIDA", "yeni imar planı askıda"),
    ("BÜTÇENİZ YOK", "bütçeniz yok"),
    ("HARÇ ŞERH RİSK MÜLK", "harç şerh risk mülk"),
    ("VE", "ve"),
    # Görünmez ve süs karakterleri
    ("✅ Tapu 🏠", "Tapu"),
    ("Konuk ekip **Mbappe'nin** 54. dakikada", "Konuk ekip Mbappe'nin elli dördüncü dakikada"),  # Instabot özeti
    ("__önemli__ not", "önemli not"),
    ("O​t​u​z", "Otuz"),
    ("‮tersine", "tersine"),
    ("satır bir\nsatır iki", "satır bir. satır iki"),
    ("tapu/imar", "tapu, imar"),
    ("emsal (KAKS) 0,60", "emsal, kaks, sıfır virgül altmış"),
    ("info@edmyapigayrimenkul.com", "info et edmyapigayrimenkul nokta com"),
    ("https://x.com/a", ""),
    # Sayı sınırları
    ("0", "sıfır"), ("100", "yüz"), ("101", "yüz bir"), ("1000", "bin"), ("1001", "bin bir"),
    ("10000000000000000", "10000000000000000"),  # trilyonun üstü: uydurulmaz, rakam kalır
]

INGILIZCE_TABLO = [
    # İngilizce kısaltmalar, unvanlar ve yaygın terimler (Türkçe fonetik okunuş)
    ("Apple CEO'su Tim Cook", "Apple si-i-o'su Tim Cook"),
    ("OpenAI CEOsu Sam Altman", "open ey-ay si-i-o'su Sam Altman"),
    ("Şirketin yeni CEO'su belli oldu.", "Şirketin yeni si-i-o'su belli oldu."),
    ("CEO'ya iletilen rapor", "si-i-o'ya iletilen rapor"),
    ("CEO'nun açıklaması", "si-i-o'nun açıklaması"),
    ("Eski CEO'dan sert tepki", "Eski si-i-o'dan sert tepki"),
    ("Tüm CEO'lar katıldı", "Tüm si-i-o'lar katıldı"),
    ("Yeni bir CEO arayışı", "Yeni bir si-i-o arayışı"),
    ("Şirketin CFO'su ve CTO'su", "Şirketin si-ef-o'su ve si-ti-o'su"),
    ("COO görevine atandı", "si-o-o görevine atandı"),
    ("Yapay zeka AI teknolojisi", "Yapay zeka ey-ay teknolojisi"),
    ("AI'ın gücü ve AI'ya yatırım", "ey-ay'ın gücü ve ey-ay'ya yatırım"),
    ("Aİ destekli yeni sistem", "ey-ay destekli yeni sistem"),
    ("Wi-Fi özellikleri", "vay-fay özellikleri"),
    ("Wi-Fi'a bağlandı", "vay-fay'a bağlandı"),
    ("Online alışveriş rekor kırdı", "onlayn alışveriş rekor kırdı"),
    ("Offline çalışan sistemler", "oflayn çalışan sistemler"),
    ("Yeni bir fintech startup'ı", "Yeni bir fintek startap'ı"),
    ("Startup ekosistemi ve startuplar", "startap ekosistemi ve startaplar"),
    ("Podcast yayını başladı", "podkast yayını başladı"),
    ("ChatGPT Plus aboneliği", "çet ci-pi-ti Plus aboneliği"),
    ("DeepSeek yapay zeka modeli", "dip siik yapay zeka modeli"),
    ("Instagram Reels ve Hikayeler", "Instagram rils ve Hikayeler"),
    ("Atılan tweet sayısı arttı", "Atılan tivit sayısı arttı"),
    ("IT departmanı teyakkuzda", "ay-ti departmanı teyakkuzda"),
    ("FBI ve CIA soruşturması", "ef-bi-ay ve si-ay-ey soruşturması"),
    ("B2B ve B2C e-ticaret", "bi-tu-bi ve bi-tu-si e-ticaret"),
    ("Fake hesaplar ve hacker saldırısı", "feyk hesaplar ve hekır saldırısı"),
    ("Influencer paylaşımları ve feedback", "influensır paylaşımları ve fidbek"),
    ("Yeni bir workshop ve deadline", "Yeni bir vörkşap ve dedlayn"),
    ("Nvidia yeni GPU modelini duyurdu", "Nvidia yeni ci-pi-yu modelini duyurdu"),
    ("Güçlü CPU ve LLM mimarisi", "Güçlü si-pi-yu ve el-el-em mimarisi"),
    ("SpaceX roketi fırlatıldı", "speys-eks roketi fırlatıldı"),
    ("Microsoft ve Google rekabeti", "maykrosoft ve gugıl rekabeti"),
    # Yeni eklenen tüketici elektroniği, otomotiv, sosyal medya ve güvenlik terimleri
    ("Apple yeni iPhone 16 modelini tanıttı.", "Apple yeni ayfon on altı modelini tanıttı."),
    ("iPhone'lar Türkiye'de satışta", "ayfon'lar Türkiye'de satışta"),
    ("iPad Pro ve iPad'ler güncellendi", "ayped Pro ve ayped'ler güncellendi"),
    ("Yeni iMac gücünü M4 çipten alıyor", "Yeni aymek gücünü M4 çipten alıyor"),
    ("MacBook Air ve MacBook Pro", "mekbuk Air ve mekbuk Pro"),
    ("AirPods kulaklıklar piyasada", "eyrpods kulaklıklar piyasada"),
    ("Apple Watch pil ömrü uzatıldı", "epıl voç pil ömrü uzatıldı"),
    ("App Store üzerinden indirildi", "ep stor üzerinden indirildi"),
    ("Google Play mağazasında yer aldı", "gugıl pley mağazasında yer aldı"),
    ("Google Cloud ve iCloud servisleri", "gugıl klaud ve ayklaud servisleri"),
    ("Bluetooth bağlantı sorunu çözüldü", "blutut bağlantı sorunu çözüldü"),
    ("YouTube üzerinden canlı yayın yapıldı", "yutub üzerinden canlı yayın yapıldı"),
    ("Threads kullanıcı sayısı rekor kırdı", "treds kullanıcı sayısı rekor kırdı"),
    ("LinkedIn profilinde paylaştı", "linkdin profilinde paylaştı"),
    ("Spotify müzik listelerinde zirvede", "spatifay müzik listelerinde zirvede"),
    ("Twitch canlı yayın platformu", "tiviç canlı yayın platformu"),
    ("Bana DM'den ulaşabilirsiniz", "Bana di-em'den ulaşabilirsiniz"),
    ("Haber Twitter'da TT oldu", "Haber Twitter'da ti-ti oldu"),
    ("Yeni elektrikli SUV modeli tanıtıldı", "Yeni elektrikli es-yu-vi modeli tanıtıldı"),
    ("SUV'lar çok satanlar arasında", "es-yu-vi'ler çok satanlar arasında"),
    ("Türkiye'de EV pazarı büyüyor", "Türkiye'de i-vi pazarı büyüyor"),
    ("EV'ler için yeni teşvikler geldi", "i-vi'ler için yeni teşvikler geldi"),
    ("Hızlı SSD ve USB bağlantı noktası", "Hızlı es-es-di ve yu-es-bi bağlantı noktası"),
    ("Tesla Cybertruck teslimatları başladı", "Tesla saybırtrak teslimatları başladı"),
    ("Autopilot sürüş modu devrede", "otopaylıt sürüş modu devrede"),
    ("Microsoft Copilot yapay zeka asistanı", "maykrosoft kopaylıt yapay zeka asistanı"),
    ("Midjourney ile görsel üretildi", "midcörni ile görsel üretildi"),
    ("Perplexity arama motoru geliştirildi", "pörpleksiti arama motoru geliştirildi"),
    ("Anthropic Claude modeli tanıtıldı", "Anthropic klod modeli tanıtıldı"),
    ("Big Tech şirketlerine ceza kesildi", "big tek şirketlerine ceza kesildi"),
    ("Phishing ve ransomware saldırıları arttı", "fişing ve rensımver saldırıları arttı"),
    ("Malware ve spyware tehlikesi", "melver ve spayver tehlikesi"),
    ("Clickbait başlıklardan kaçının", "klikbeyt başlıklardan kaçının"),
]

_KISALTMA_KALINTISI = re.compile(r"\b(?:Hz|Dr|Av|Prof|Doç|vb|vs|bkz|md|Mah|Cad|Sok|Apt)\.")


def _geri_coz(yazi: str) -> int:
    """sayi_yazi'nin tersi — testin kendi bağımsız çözücüsü."""
    birim = {w: i for i, w in enumerate(["sıfır", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"])}
    onluk = {w: (i + 1) * 10 for i, w in enumerate(["on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"])}
    buyuk = {"bin": 10 ** 3, "milyon": 10 ** 6, "milyar": 10 ** 9, "trilyon": 10 ** 12}
    toplam = grup = 0
    for w in yazi.split():
        if w in birim:
            grup += birim[w]
        elif w in onluk:
            grup += onluk[w]
        elif w == "yüz":
            grup = (grup or 1) * 100
        elif w in buyuk:
            toplam += (grup or 1) * buyuk[w]
            grup = 0
        else:
            raise ValueError(w)
    return toplam + grup


class TestOkunusTablosu(unittest.TestCase):
    def test_sabotaj_tablosu(self):
        for girdi, beklenen in TABLO:
            with self.subTest(girdi=girdi):
                self.assertEqual(okunusa_cevir(girdi), beklenen)

    def test_cikti_ikinci_kez_cevrilince_degismez(self):
        for girdi, _ in TABLO:
            with self.subTest(girdi=girdi):
                bir = okunusa_cevir(girdi)
                self.assertEqual(okunusa_cevir(bir), bir)

    def test_ciktida_rakam_gorunmez_karakter_ve_kisaltma_kalmaz(self):
        for girdi, _ in TABLO:
            cikti = okunusa_cevir(girdi)
            with self.subTest(girdi=girdi):
                if len(re.sub(r"\D", "", girdi)) < 16:
                    self.assertNotRegex(re.sub(r"[A-ZÇĞİÖŞÜ]-\d+", "", cikti), r"\d")  # "D-100" yol kodu kalır
                self.assertFalse(any(unicodedata.category(c)[0] == "C" for c in cikti))
                self.assertNotRegex(cikti, _KISALTMA_KALINTISI)

    def test_ingilizce_terimler_okunusu(self):
        for girdi, beklenen in INGILIZCE_TABLO:
            with self.subTest(girdi=girdi):
                cikti = okunusa_cevir(girdi)
                self.assertEqual(cikti, beklenen)
                self.assertEqual(okunusa_cevir(cikti), cikti)


class TestSayilar(unittest.TestCase):
    def test_rastgele_sayilar_geri_cozulur(self):
        """3000 rastgele sayı: yazıya çevir, bağımsız çözücüyle geri çöz, aynı sayı çıkmalı."""
        rnd = random.Random(20260926)
        ornekler = [rnd.randrange(0, 10 ** rnd.randint(1, 15)) for _ in range(3000)]
        ornekler += [0, 1, 10, 100, 1000, 1001, 10 ** 6, 10 ** 9, 10 ** 12, 10 ** 15 - 1]
        for n in ornekler:
            self.assertEqual(_geri_coz(sayi_yazi(n)), n, n)

    def test_metin_icindeki_sayi_da_geri_cozulur(self):
        rnd = random.Random(7)
        for _ in range(500):
            n = rnd.randrange(1, 10 ** 9)
            bicimli = f"{n:,}".replace(",", ".")  # Türkçe binlik ayraç
            self.assertEqual(_geri_coz(okunusa_cevir(bicimli)), n, bicimli)

    def test_sira_sayilari_unlu_uyumu(self):
        beklenen = {1: "birinci", 2: "ikinci", 3: "üçüncü", 4: "dördüncü", 5: "beşinci", 6: "altıncı",
                    7: "yedinci", 8: "sekizinci", 9: "dokuzuncu", 10: "onuncu", 20: "yirminci", 30: "otuzuncu",
                    40: "kırkıncı", 50: "ellinci", 60: "altmışıncı", 70: "yetmişinci", 80: "sekseninci",
                    90: "doksanıncı", 100: "yüzüncü", 1000: "bininci", 14: "on dördüncü"}
        for n, s in beklenen.items():
            self.assertEqual(sira_yazi(n), s)


class TestTekHarf(unittest.TestCase):
    """Tek harf sese tırnakla gider: düz hâli çok hızlı okunuyor ve yutuluyordu (ölçüldü)."""

    def test_tek_harf_tirnaklanir_yol_kodu_ve_kelime_icindeki_harf_degil(self):
        from src.okunus import tek_harfleri_belirginlestir as b
        self.assertEqual(b("A Milli Takım Uluslar A Ligi'ne"), '"A" Milli Takım Uluslar "A" Ligi\'ne')
        self.assertEqual(b("numara elli sekiz A."), 'numara elli sekiz "A".')
        self.assertEqual(b("D-100 ve F-16"), '"D"-100 ve "F"-16')  # düz hâli "Kazadei 100", "F-36" okundu
        self.assertEqual(b("TBMM ve KDV'li Ali"), "TBMM ve KDV'li Ali")
        self.assertEqual(b('"A" Milli'), '"A" Milli')  # ikinci kez uygulanınca değişmez
        self.assertEqual(b(""), "")

    def test_zincirin_ciktisi_tirnagi_korur(self):
        from src.okunus import tek_harfleri_belirginlestir as b
        self.assertEqual(b(okunusa_cevir("A Milli Takım 1-0 yenildi")), '"A" Milli Takım bir-sıfır yenildi')


class TestKaristirmaSabotaji(unittest.TestCase):
    """Tuzaklı parçaları rastgele birleştirir: hiçbir girdi çökertmemeli, çıktı kararlı olmalı."""

    PARCALAR = [girdi for girdi, _ in TABLO] + [
        "", " ", "\n\n", "...", ",,", "()", "''", "’", "/", "%", "₺", "12'", "'12", "3.", ".5", "5.", "1/0",
        "0/0", "1//2", "Hz", "hz.", "Dr", "A.", "Ş.", "İ", "ı", "I", "x", "X", "×", "²", "³", "°C", "1e10",
        "٣", "１２", "İ̇", "é", "﻿", "­", "🇹🇷", "👍🏽", "\t", "  ", "%%", "$$", "TL TL",
        "99999999999999999999", "0000", "-5", "−5", "5-", "a/b/c", "1/2/3", "25.13.2026", "31.02.2026",
        "24:00", "23:59", "7.00", "saat 7.00", "B1", "3D", "4K", "iPhone", "e-Devlet", "Silivri'de",
    ]

    def test_rastgele_karisik_girdi(self):
        rnd = random.Random(99)
        for _ in range(3000):
            girdi = rnd.choice([" ", "", "\n", ", "]).join(rnd.choices(self.PARCALAR, k=rnd.randint(1, 6)))
            with self.subTest(girdi=girdi):
                cikti = okunusa_cevir(girdi)
                self.assertIsInstance(cikti, str)
                self.assertFalse(any(unicodedata.category(c)[0] == "C" for c in cikti), repr(cikti))
                self.assertFalse(any(ord(c) > 0xFFFF for c in cikti), repr(cikti))
                self.assertEqual(okunusa_cevir(cikti), cikti)

    def test_metin_olmayan_girdi(self):
        for girdi in (None, 5, [], {}, b"Hz."):
            self.assertEqual(okunusa_cevir(girdi), "")  # type: ignore[arg-type]


class TestSabotajKorumasi(unittest.TestCase):
    """İngilizce terim havuzunun Türkçe kelimelerle çakışmadığını ve ek uyumunu denetler."""

    def test_turkce_kelimeler_ve_kisaltmalar_korunur(self):
        """Sabotaj: Türkçe kelimeler ve yerli kısaltmalar İngilizce fonetikle ezilmemeli."""
        tuzaklar = [
            # like != tehlike
            ("Büyük bir tehlike atlattık.", "Büyük bir tehlike atlattık."),
            ("Hep birlikte hareket ediyoruz.", "Hep birlikte hareket ediyoruz."),
            # reels != reel
            ("Reel sektör güven endeksi açıklandı.", "Reel sektör güven endeksi açıklandı."),
            ("Reel faiz oranları yükselişte.", "Reel faiz oranları yükselişte."),
            # IT != it
            ("İti an çomağı hazırla demişler.", "İti an çomağı hazırla demişler."),
            ("Kapıyı hafifçe it ve aç.", "Kapıyı hafifçe it ve aç."),
            # EV != ev
            ("Ev fiyatları son bir yılda arttı.", "Ev fiyatları son bir yılda arttı."),
            ("Ev sahibi ve kiracı anlaşmazlığı.", "Ev sahibi ve kiracı anlaşmazlığı."),
            ("Satılık ev ilanları güncellendi.", "Satılık ev ilanları güncellendi."),
            ("Evler kışa hazırlanıyor.", "Evler kışa hazırlanıyor."),
            ("Eve erken gelmesini söyledi.", "Eve erken gelmesini söyledi."),
            ("Evde huzur ve mutluluk var.", "Evde huzur ve mutluluk var."),
            ("Evden çalışma sistemi yaygınlaştı.", "Evden çalışma sistemi yaygınlaştı."),
            ("Ev alma komşu al atalar sözüdür.", "Ev alma komşu al atalar sözüdür."),
            ("Evlilik yıldönümü kutlaması.", "Evlilik yıldönümü kutlaması."),
            # SUV != su
            ("Su faturaları bu ay yüksek geldi.", "Su faturaları bu ay yüksek geldi."),
            ("Barajlardaki su seviyesi kritik.", "Barajlardaki su seviyesi kritik."),
            ("Bir bardak su ikram etti.", "Bir bardak su ikram etti."),
            ("Akar sular duruldu nihayet.", "Akar sular duruldu nihayet."),
            ("Karasu ilçesinde festival düzenlendi.", "Karasu ilçesinde festival düzenlendi."),
            # can, at, on, in
            ("Can sağlığı her şeyden önemli.", "Can sağlığı her şeyden önemli."),
            ("Ata binmek geleneksel sporumuz.", "Ata binmek geleneksel sporumuz."),
            ("On bir ayın sultanı Ramazan.", "On bir ayın sultanı Ramazan."),
            ("İn cin top oynuyor sokaklarda.", "İn cin top oynuyor sokaklarda."),
            # Yerli kısaltmalar ve kurumlar
            ("TBMM genel kurulunda oylandı.", "TBMM genel kurulunda oylandı."),
            ("SGK prim borçları yapılandırıldı.", "SGK prim borçları yapılandırıldı."),
            ("KDV indirim kararı Resmî Gazete'de.", "KDV indirim kararı Resmî Gazete'de."),
            ("İBB metrobüs hattında çalışma.", "İstanbul Büyükşehir Belediyesi metrobüs hattında çalışma."),
            ("BİST endeksi günü artıda kapattı.", "bist endeksi günü artıda kapattı."),
            ("TOKİ konut kura çekilişi yapıldı.", "toki konut kura çekilişi yapıldı."),
            # Karayolu ve unvan korumaları
            ("D-100 karayolunda kaza meydana geldi.", "D-100 karayolunda kaza meydana geldi."),
            ("E-5 trafiği yoğunlaştı.", "E-5 trafiği yoğunlaştı."),
            ("Prof. Dr. Ahmet Yılmaz açıkladı.", "Profesör Doktor Ahmet Yılmaz açıkladı."),
        ]
        for girdi, beklenen in tuzaklar:
            with self.subTest(girdi=girdi):
                self.assertEqual(okunusa_cevir(girdi), beklenen)

    def test_ingilizce_ek_ve_unlu_uyumu(self):
        """Sabotaj: İngilizce köklere gelen Türkçe eklerin ünlü ve ünsüz uyumu bozulmamalı."""
        ornekler = [
            ("iPhone'un kamerası çok gelişmiş.", "ayfon'un kamerası çok gelişmiş."),
            ("iPhone'lar Türkiye'de rekor kırdı.", "ayfon'lar Türkiye'de rekor kırdı."),
            ("iPhone'a yoğun ilgi gösterildi.", "ayfon'a yoğun ilgi gösterildi."),
            ("iPad'in yeni ekran teknolojisi.", "ayped'in yeni ekran teknolojisi."),
            ("iPad'ler piyasaya sürüldü.", "ayped'ler piyasaya sürüldü."),
            ("iPad'e yeni çip takıldı.", "ayped'e yeni çip takıldı."),
            ("Yeni SUV'lar yollarda görüldü.", "Yeni es-yu-vi'ler yollarda görüldü."),
            ("SUV'ye olan talep patladı.", "es-yu-vi'ye olan talep patladı."),
            ("SUV'un bagaj hacmi çok geniş.", "es-yu-vi'in bagaj hacmi çok geniş."),
            ("EV pazarı her geçen gün büyüyor.", "i-vi pazarı her geçen gün büyüyor."),
            ("Yeni EV'ler yollara çıkıyor.", "Yeni i-vi'ler yollara çıkıyor."),
            ("EV'ye geçiş teşvik ediliyor.", "i-vi'ye geçiş teşvik ediliyor."),
            ("Bana DM'den yazabilirsiniz.", "Bana di-em'den yazabilirsiniz."),
            ("DM kutusu mesajla doldu taştı.", "di-em kutusu mesajla doldu taştı."),
            ("Haber kısa sürede TT oldu.", "Haber kısa sürede ti-ti oldu."),
            ("Günün TT listesi belli oldu.", "Günün ti-ti listesi belli oldu."),
            ("YouTube'da canlı yayın açıldı.", "yutub'da canlı yayın açıldı."),
            ("Threads'te yeni akım başladı.", "treds'te yeni akım başladı."),
            ("LinkedIn'de yeni iş ilanları.", "linkdin'de yeni iş ilanları."),
            ("Spotify'da en çok dinlenenler.", "spatifay'da en çok dinlenenler."),
            ("Kulaklık Bluetooth'la bağlanıyor.", "Kulaklık blutut'la bağlanıyor."),
            ("Veriler hızlı SSD'ye yazılıyor.", "Veriler hızlı es-es-di'ye yazılıyor."),
            ("Cihaz USB'ye doğrudan takıldı.", "Cihaz yu-es-bi'ye doğrudan takıldı."),
            ("Uygulama App Store'dan indirildi.", "Uygulama ep stor'dan indirildi."),
            ("Oyun Google Play'de yayınlandı.", "Oyun gugıl pley'de yayınlandı."),
            ("Apple Watch'un nabız sensörü.", "epıl voç'un nabız sensörü."),
            ("Microsoft Copilot'a yeni yetenek.", "maykrosoft kopaylıt'a yeni yetenek."),
            ("Midjourney'ye yeni sürüm geldi.", "midcörni'ye yeni sürüm geldi."),
            ("Claude'un zeka puanı yükseldi.", "klod'un zeka puanı yükseldi."),
            ("Big Tech'e yönelik yeni düzenleme.", "big tek'e yönelik yeni düzenleme."),
        ]
        for girdi, beklenen in ornekler:
            with self.subTest(girdi=girdi):
                self.assertEqual(okunusa_cevir(girdi), beklenen)
                # İkinci kez çevrilince asla değişmemeli (idempotency)
                self.assertEqual(okunusa_cevir(beklenen), beklenen)


if __name__ == "__main__":
    unittest.main()
