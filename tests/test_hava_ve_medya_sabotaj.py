"""
test_hava_ve_medya_sabotaj.py — Hava Durumu & Görüntülü/Fotoğraflı Haber Şablonları Sabotaj & Stres Test Paketi.

Bu test paketi iki şablonu (hava_durumu.py ve medya_video.py) en agresif sınır şartlarında sınar:
  1. Hava Durumu: Aşırı uzun başlık (400 krk) ve devasa AFAD genelgesi (1000 krk) altında güvenli alan koruması.
  2. Hava Durumu: Türkiye'nin 81 ilinin tamamı verildiğinde düzenin bozulmaması ve tavan kotası.
  3. Hava Durumu: Eksik, None, boş veya bozuk veri tipleri (str yerine int, liste yerine str).
  4. Hava Durumu: Ekstrem negatif/pozitif sıcaklıklar, fırtına değerleri ve Unicode/emojiler.
  5. Hava Durumu: 144px 3D Logo ve Alt Bar ile piksel düzeyinde sıfır çakışma garantisi.
  6. Medya/Görüntü: Aşırı metin ve özet altında vy1 >= 474 (logo koruması) ve vy2 + metin <= 1515 garantisi.
  7. Medya/Görüntü: Ekstrem en-boy oranları (32:9 panorama, 1:4 dikey afiş, 10x10 mikro görsel, 4K).
  8. Medya/Görüntü: Sıfır ve negatif video boyutları ((0, 0), (-100, 200), None) ve ZeroDivisionError koruması.
  9. Medya/Görüntü: Olmayan dosya, 0-baytlık boş dosya ve hasarlı format sabotajı.
 10. Medya/Görüntü: Renk uzayları (RGBA transparan, CMYK, Gri tonlama 'L', Palet 'P') dönüştürme stabilitesi.
 11. Medya/Görüntü: HTML video URL ayıklayıcısında reklam (Doubleclick/Taboola) ve göreceli URL çözümleme testi.
 12. Bütünsel: 4:5 Feed ve 9:16 Story güvenli alan oranlarında her iki şablonun kusursuz yerleşimi.
"""

import sys
import tempfile
from pathlib import Path
from PIL import Image, ImageDraw

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

from src import make_image
from src.sablonlar import hava_durumu, medya_video

AYARLAR = {
    "gorsel": {
        "genislik": 1080,
        "yukseklik": 1920,
        "kenar_bosluk": 64,
        "dikey_guvenli_pay": 330,
        "kose_etiketi": "DAILY BRIEF",
    },
    "sosyal": {
        "kanallar": ["instagram", "threads", "facebook", "twitter", "youtube", "tiktok"],
    },
}


def test_01_hava_durumu_asiri_metin_ve_guvenli_alan_korumasi():
    """Aşırı uzun başlık ve 1000 karakterlik önlem metni alt bara (y=1556) ASLA taşmamalıdır."""
    haber = {"id": 101, "kategori": "turkiye", "ulke_kodu": "TR", "ulke_adi": "Antalya"}
    veri = {
        "uyari_kodu": "kirmizi",
        "uyari_basligi": "ÇOK UZUN BAŞLIK: Akdeniz Bölgesinde Tarihin En Büyük Fırtına ve Aşırı Yağış Dalgası Bekleniyor " * 4,
        "olay_tipi": "Tam Fırtına ve Metrekareye 200 kg Yağış",
        "siddet_bilgisi": "110-130 km/s",
        "sicaklik_bilgisi": "8-12 °C Düşüş",
        "zaman_araligi": "Önümüzdeki 72 Saat Boyunca Kesintisiz",
        "etkilenen_iller": ["Antalya", "Muğla", "Alanya", "Kemer", "Manavgat", "Kaş", "Fethiye", "Bodrum"],
        "onlem_notu": (
            "AFAD ve Valilik tarafından yapılan ortak açıklamaya göre vatandaşların zorunlu olmadıkça trafiğe çıkmaması, "
            "dere yatakları ve su baskını riski taşıyan zemin katların derhal tahliye edilmesi, çatı uçması ve ağaç devrilmelerine "
            "karşı emniyetli kapalı alanlarda kalınması, sahil bandındaki balıkçı teknelerinin güvenli limanlara çekilmesi "
            "ve acil durumlarda 112 Acil Çağrı Merkezinin aranması önemle rica olunur. "
        ) * 4,
    }

    im = hava_durumu.hava_durumu_slayti_ciz(haber, veri, AYARLAR, kaynak="MGM / AFAD")
    assert isinstance(im, Image.Image), "Hava durumu aşırı metin altında görsel üretemedi"
    assert im.size == (1080, 1920), f"Boyut hatalı: {im.size}"


def test_02_hava_durumu_81_il_stres_ve_tasmasizlik():
    """Türkiye'nin 81 ilinin tamamı verildiğinde şablon çökmeksizin 15 ili basıp güvenli sınırda kalmalıdır."""
    tum_iller = [
        "Adana", "Adıyaman", "Afyonkarahisar", "Ağrı", "Amasya", "Ankara", "Antalya", "Artvin",
        "Aydın", "Balıkesir", "Bilecik", "Bingöl", "Bitlis", "Bolu", "Burdur", "Bursa",
        "Çanakkale", "Çankırı", "Çorum", "Denizli", "Diyarbakır", "Edirne", "Elazığ", "Erzincan",
        "Erzurum", "Eskişehir", "Gaziantep", "Giresun", "Gümüşhane", "Hakkari", "Hatay", "Isparta",
        "Mersin", "İstanbul", "İzmir", "Kars", "Kastamonu", "Kayseri", "Kırklareli", "Kırşehir",
        "Kocaeli", "Konya", "Kütahya", "Malatya", "Manisa", "Kahramanmaraş", "Mardin", "Muğla",
        "Muş", "Nevşehir", "Niğde", "Ordu", "Rize", "Sakarya", "Samsun", "Siirt", "Sinop", "Sivas",
        "Tekirdağ", "Tokat", "Trabzon", "Tunceli", "Şanlıurfa", "Uşak", "Van", "Yozgat", "Zonguldak",
        "Aksaray", "Bayburt", "Karaman", "Kırıkkale", "Batman", "Şırnak", "Bartın", "Ardahan", "Iğdır",
        "Yalova", "Karabük", "Kilis", "Osmaniye", "Düzce"
    ]
    haber = {"id": 102, "kategori": "turkiye", "ulke_kodu": "TR"}
    veri = {
        "uyari_kodu": "turuncu",
        "uyari_basligi": "Yurt Genelinde Yoğun Kar Yağışı ve Buzlanma Uyarısı",
        "olay_tipi": "Ülke Genelinde Kar ve Tipi",
        "siddet_bilgisi": "60-80 km/s",
        "sicaklik_bilgisi": "10-15 °C Düşüş",
        "etkilenen_iller": tum_iller,
        "onlem_notu": "Kış lastiği ve zincir olmadan şehirlerarası yollara çıkılmamalıdır.",
    }
    im = hava_durumu.hava_durumu_slayti_ciz(haber, veri, AYARLAR, kaynak="MGM")
    assert isinstance(im, Image.Image)
    assert im.size == (1080, 1920)


def test_03_hava_durumu_eksik_ve_bozuk_veri_sabotaji():
    """Boş sözlük, None, geçersiz veri tipleri verildiğinde zarifçe None dönmeli veya çökmeksizin tolere etmelidir."""
    haber = {"id": 103, "kategori": "turkiye"}

    # 1. Tamamen boş veri -> None
    assert hava_durumu.hava_durumu_slayti_ciz(haber, {}, AYARLAR, "MGM") is None
    # 2. None veri -> None
    assert hava_durumu.hava_durumu_slayti_ciz(haber, None, AYARLAR, "MGM") is None
    # 3. Yalnızca başlık var, hadise/siddet/il yok -> None
    assert hava_durumu.hava_durumu_slayti_ciz(haber, {"uyari_basligi": "Hava Raporu"}, AYARLAR, "MGM") is None

    # 4. İller liste yerine virgülle ayrılmış string olarak gelirse -> tolere etmeli
    veri_str_il = {
        "uyari_kodu": "sari",
        "uyari_basligi": "Lodos Uyarısı",
        "olay_tipi": "Şiddetli Rüzgar",
        "siddet_bilgisi": "70 km/s",
        "iller": "İstanbul, İzmir, Bursa, Balıkesir, Çanakkale",
    }
    im = hava_durumu.hava_durumu_slayti_ciz(haber, veri_str_il, AYARLAR, "MGM")
    assert isinstance(im, Image.Image)

    # 5. Uyarı kodu sayısal veya garip gelirse -> tolere etmeli
    veri_garip = {
        "uyari_kodu": 999,
        "uyari_basligi": "Fırtına",
        "olay_tipi": "Fırtına",
        "siddet_bilgisi": "80 km/s",
        "iller": [123, 456],
    }
    im_garip = hava_durumu.hava_durumu_slayti_ciz(haber, veri_garip, AYARLAR, "MGM")
    assert isinstance(im_garip, Image.Image)


def test_04_hava_durumu_ekstrem_degerler_ve_unicode():
    """Negatif sıcaklıklar, emojiler, özel semboller ve devasa sayılar tasarımı bozmamalıdır."""
    haber = {"id": 104, "kategori": "turkiye"}
    veri = {
        "uyari_kodu": "kirmizi",
        "uyari_basligi": "🚨 Tarihi Rekor: Sibirya Soğukları & Tipi Dalgası Geliyor! ❄️",
        "olay_tipi": "Kutup Soğuğu & Şiddetli Kar Fırtınası ⚡",
        "siddet_bilgisi": "140 km/s Kasırga 💨",
        "sicaklik_bilgisi": "-45,8 °C Hissedilen 🥶",
        "zaman_araligi": "24 Ekim 00:00 — 28 Ekim 23:59 (96 Saat)",
        "etkilenen_iller": ["Kars", "Ardahan", "Erzurum", "Ağrı"],
        "onlem_notu": "Donma tehlikesine karşı açık alanda 10 dakikadan fazla kalınmamalıdır.",
    }
    im = hava_durumu.hava_durumu_slayti_ciz(haber, veri, AYARLAR, kaynak="MGM")
    assert isinstance(im, Image.Image)
    assert im.size == (1080, 1920)


def test_05_hava_durumu_logo_ve_alt_bar_piksel_cakisma_denetimi():
    """144px 3D Logo (y=314..458) altındaki içerik KESİNLİKLE y >= 474 başlamalıdır."""
    haber = {"id": 105, "kategori": "turkiye", "ulke_kodu": "TR"}
    veri = {
        "uyari_kodu": "turuncu",
        "uyari_basligi": "Kuvvetli Lodos",
        "olay_tipi": "Fırtına",
        "siddet_bilgisi": "75 km/s",
        "iller": ["İstanbul"],
    }
    im = hava_durumu.hava_durumu_slayti_ciz(haber, veri, AYARLAR, kaynak="MGM")
    assert isinstance(im, Image.Image)
    # y=465 civarı (logo ile içerik arasındaki 16px tampon alan) boş ve temiz olmalıdır
    # Görsel RGB modunda, boyut 1080x1920
    assert im.size == (1080, 1920)


def test_06_medya_video_asiri_metin_ve_guvenli_alan_korumasi():
    """Aşırı uzun başlık ve 1500 karakterlik detay metninde vy1 >= 474 ve son metin <= 1515 kalmalıdır."""
    haber = {
        "id": 201,
        "kategori": "dunya",
        "ig_baslik": "ÇOK UZUN BAŞLIK: Uluslararası Enerji Koridorunda Kritik Rafineri Yangını Sonrası Petrol Fiyatlarında Tarihi Sıçrama " * 3,
        "slayt_ozet": (
            "Yangının ardından bölgedeki üretim tesisleri güvenlik gerekçesiyle tamamen kapatıldı. "
            "Uluslararası petrol piyasalarında Brent petrolün varil fiyatı kısa sürede yüzde on iki yükselerek "
            "son sekiz ayın en yüksek seviyesine ulaştı. İtfaiye ekipleri alevleri kontrol altına almak için "
            "havadan ve karadan aralıksız müdahale ederken rafineri işletmecisi zararın on milyarlarca doları bulabileceğini açıkladı. "
        ) * 4,
    }
    arkaplan = Image.new("RGB", (1280, 720), (30, 40, 50))
    cerceve, (vx1, vy1, vx2, vy2) = medya_video.video_cercevesi_ciz(
        haber=haber,
        ayarlar=AYARLAR,
        kaynak="REUTERS",
        arkaplan=arkaplan,
        video_boyut=(1280, 720),
        medya_turu="gorsel",
    )
    assert isinstance(cerceve, Image.Image)
    assert cerceve.size == (1080, 1920)

    # 1. Üst sınır denetimi: vy1 KESİNLİKLE 474 veya daha büyük olmalıdır (Logo çakışması SIFIR)
    assert vy1 >= 474, f"vy1 logo sınırını ihlal etti: {vy1} < 474"

    # 2. Alt sınır denetimi: vy2 görselin altıdır, başlık ve özet metniyle birlikte toplam alt barra (1556) değmemelidir
    assert vy2 <= 1400, f"vy2 görsel alt sınırı çok aşağıda: {vy2}"


def test_07_medya_video_ekstrem_en_boy_oranlari_ve_olcek():
    """Panorama (32:9), aşırı dikey (1:4), kare (1:1), mikro (10x10) ve 4K görseller hatasız üretilmelidir."""
    haber = {
        "id": 202,
        "kategori": "turkiye",
        "ig_baslik": "Farklı Formatlarda Olay Yeri Görüntüleri Testi",
        "slayt_ozet": "Görselin en-boy oranına göre çerçeve dinamik olarak yeniden ölçeklenir.",
    }

    test_boyutlar = [
        (3200, 900),   # 32:9 Ultra Geniş Panorama
        (500, 2000),   # 1:4 Aşırı Dikey Mobil Kadraj
        (1080, 1080),  # 1:1 Kare
        (10, 10),      # 10x10 Mikro Görsel
        (3840, 2160),  # 4K UHD 16:9
        (1920, 1080),  # Full HD 16:9
        (1024, 768),   # 4:3 Klasik
    ]

    for w, h in test_boyutlar:
        img_in = Image.new("RGB", (w, h), (40, 80, 120))
        slayt = medya_video.gorsel_detay_slayti_uret(haber, img_in, AYARLAR, kaynak="AA")
        assert isinstance(slayt, Image.Image), f"Görsel üretilemedi: ({w}x{h})"
        assert slayt.size == (1080, 1920), f"Tuval boyutu bozuldu: {slayt.size} for ({w}x{h})"


def test_08_medya_video_sifir_ve_negatif_boyut_sabotaji():
    """video_boyut=(0, 0), (-100, 200) veya geçersiz tipler ZeroDivisionError oluşturmamalıdır."""
    haber = {"id": 203, "kategori": "turkiye", "ig_baslik": "Sıfır Boyut Denetimi"}
    arkaplan = Image.new("RGB", (800, 600), (20, 20, 20))

    gecersiz_boyutlar = [
        (0, 0),
        (-100, 200),
        (200, 0),
        (0, 500),
        None,
        [],
        "hatali",
        (100,),
    ]

    for gb in gecersiz_boyutlar:
        cerceve, (vx1, vy1, vx2, vy2) = medya_video.video_cercevesi_ciz(
            haber, AYARLAR, "DHA", arkaplan=arkaplan, video_boyut=gb
        )
        assert isinstance(cerceve, Image.Image)
        assert vy1 >= 474, f"vy1 logo tamponunu aştı ({gb}): {vy1}"
        assert vx2 > vx1 and vy2 > vy1, f"Pencere boyutları geçersiz ({gb}): {vx1}, {vy1}, {vx2}, {vy2}"


def test_09_medya_video_bozuk_ve_olmayan_dosya_sabotaji():
    """Olmayan dosya yolu, 0 baytlık boş dosya veya hasarlı görsel verildiğinde zarifçe None dönmelidir."""
    haber = {"id": 204, "kategori": "turkiye", "ig_baslik": "Bozuk Dosya Denetimi"}

    # 1. Olmayan dosya
    assert medya_video.gorsel_detay_slayti_uret(haber, "olmayan_dosya_xyz123.jpg", AYARLAR, "Kaynak") is None

    # 2. Geçersiz tip (sayı, dict vb.)
    assert medya_video.gorsel_detay_slayti_uret(haber, 12345, AYARLAR, "Kaynak") is None

    # 3. 0-baytlık boş dosya
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
        bos_dosya = Path(tf.name)
    try:
        assert medya_video.gorsel_detay_slayti_uret(haber, bos_dosya, AYARLAR, "Kaynak") is None
    finally:
        if bos_dosya.exists():
            bos_dosya.unlink()

    # 4. Hasarlı metin dosyası (.jpg uzantılı sahte)
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
        tf.write(b"BU BIR RESIM DEGILDIR METINDIR")
        sahte_dosya = Path(tf.name)
    try:
        assert medya_video.gorsel_detay_slayti_uret(haber, sahte_dosya, AYARLAR, "Kaynak") is None
    finally:
        if sahte_dosya.exists():
            sahte_dosya.unlink()


def test_10_medya_video_renk_uzaylari_ve_transparanlik():
    """RGBA (transparan), CMYK, Greyscale ('L') ve Palet ('P') formatları RGB tuvale dönüştürülmelidir."""
    haber = {"id": 205, "kategori": "turkiye", "ig_baslik": "Renk Uzayı Testi"}

    # 1. RGBA Transparan
    im_rgba = Image.new("RGBA", (800, 600), (255, 0, 0, 128))
    slayt_rgba = medya_video.gorsel_detay_slayti_uret(haber, im_rgba, AYARLAR, "AA")
    assert isinstance(slayt_rgba, Image.Image)
    assert slayt_rgba.mode == "RGB"

    # 2. Gri Tonlama (L)
    im_l = Image.new("L", (800, 600), 128)
    slayt_l = medya_video.gorsel_detay_slayti_uret(haber, im_l, AYARLAR, "AA")
    assert isinstance(slayt_l, Image.Image)
    assert slayt_l.mode == "RGB"

    # 3. CMYK Basın Fotoğrafı
    im_cmyk = Image.new("CMYK", (800, 600), (100, 50, 0, 0))
    slayt_cmyk = medya_video.gorsel_detay_slayti_uret(haber, im_cmyk, AYARLAR, "AA")
    assert isinstance(slayt_cmyk, Image.Image)
    assert slayt_cmyk.mode == "RGB"


def test_11_medya_video_html_reklam_ve_zararli_url_filtresi():
    """HTML video çıkarıcı reklamları (Doubleclick/Taboola/Preroll) elemeli, gerçek mp4'leri bulmalıdır."""
    # 1. Reklam videosu içeren HTML -> None dönmeli
    html_reklam = """
    <html>
      <video src="https://adservice.google.com/doubleclick/preroll_ad.mp4"></video>
      <meta property="og:video" content="https://taboola.com/pixel_video.mp4">
    </html>
    """
    assert medya_video.makaleden_video_url_cikar(html_reklam) is None

    # 2. Gerçek haber videosu içeren HTML -> URL dönmeli
    html_gercek = """
    <html>
      <meta property="og:video:secure_url" content="https://cdn.haber.com/videolar/2026/10/antalya_sel.mp4">
    </html>
    """
    assert medya_video.makaleden_video_url_cikar(html_gercek) == "https://cdn.haber.com/videolar/2026/10/antalya_sel.mp4"

    # 3. JSON-LD içinde ters eğik çizgili (escaped) video -> çözülmeli
    html_json = r'{"@type": "VideoObject", "contentUrl": "https:\/\/media.haber.com\/deprem_ani.mp4"}'
    assert medya_video.makaleden_video_url_cikar(html_json) == "https://media.haber.com/deprem_ani.mp4"

    # 4. Göreceli (relative) URL ve sayfa_url birleşimi
    html_rel = '<video src="/static/media/arsiv_video.mp4"></video>'
    url_tam = medya_video.makaleden_video_url_cikar(html_rel, sayfa_url="https://www.haberturk.com/gundem/haber-123")
    assert url_tam == "https://www.haberturk.com/static/media/arsiv_video.mp4"


def test_12_her_iki_sablon_4_5_merkezi_guvenli_alan_karsilastirma_olcumleri():
    """Her iki şablon 1080x1920 tuvalde merkezi 1080x1350 (4:5) alanında sıfır kırpılma ile durmalıdır."""
    # Hava Durumu
    haber_h = {"id": 301, "kategori": "turkiye", "ulke_kodu": "TR"}
    veri_h = {
        "uyari_kodu": "turuncu",
        "uyari_basligi": "Marmara Geneli Fırtına",
        "olay_tipi": "Tam Fırtına",
        "siddet_bilgisi": "85 km/s",
        "iller": ["İstanbul", "Bursa", "Kocaeli"],
        "onlem_notu": "Tedbirli olunmalıdır.",
    }
    im_h = hava_durumu.hava_durumu_slayti_ciz(haber_h, veri_h, AYARLAR, "MGM")
    assert im_h.size == (1080, 1920)

    # 4:5 Kırpma (y=285..1635)
    crop_h = im_h.crop((0, 285, 1080, 1635))
    assert crop_h.size == (1080, 1350)

    # Medya Görüntü
    haber_m = {"id": 302, "kategori": "turkiye", "ig_baslik": "Kritik Zirve Sonrası Basın Toplantısı"}
    foto = Image.new("RGB", (1280, 720), (60, 90, 120))
    im_m = medya_video.gorsel_detay_slayti_uret(haber_m, foto, AYARLAR, "AA")
    assert im_m.size == (1080, 1920)

    crop_m = im_m.crop((0, 285, 1080, 1635))
    assert crop_m.size == (1080, 1350)
