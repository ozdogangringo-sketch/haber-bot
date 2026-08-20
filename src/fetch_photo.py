"""
fetch_photo.py — Wikimedia Commons'tan lisansı uygun fotoğraf çeker.

NEDEN COMMONS:
    Kullanıcı haberle ilgili gerçek görsel istiyor. Güncel olay fotoğrafları
    ajanslara ait ve telifli — kırpmak, küçültmek, kaynak yazmak bu durumu
    değiştirmiyor. Commons'ta ise kamu malı ve serbest CC lisanslı görseller
    var, bunları yasal olarak kullanabiliyoruz.

NE İŞE YARIYOR, NE YARAMIYOR (ölçüldü, 14 Ağu 2026):
    ✓ KİŞİ ve KURUM aramaları çok iyi:
        "Donald Trump"   -> resmi portreler, kamu malı, 4/4 uygun
        "Hakan Fidan"    -> resmi fotoğraflar, 4/4 uygun
    ✗ OLAY aramaları kullanılamaz:
        "Istanbul earthquake" -> 1509 depremi gravürü, 1754 çizimi
        "Besiktas"            -> 1911 kadro fotoğrafı

    Bu yüzden SADECE kişi/kurum için kullanıyoruz. Konu araması yapma,
    alakasız arşiv görselleri gelir.

ARŞİV FOTOĞRAFI UYARISI:
    Gelen görsel olayın anına ait değil, arşivden bir portre. Gazetecilikte
    standart pratik ama takipçiye "bu olayın fotoğrafı" hissi vermemeli.
    O yüzden görselde tarih/olay iddiası taşıyan bir şey yazmıyoruz.
"""

from __future__ import annotations

import io
import logging
import re
import threading
import time

import requests
from PIL import Image

log = logging.getLogger(__name__)

API = "https://commons.wikimedia.org/w/api.php"

# Wikimedia kimliğimizi ve iletişim adresini görmek istiyor.
# Yetersiz User-Agent gönderirsek 429 (Too Many Requests) yiyoruz —
# ilk denemede tam olarak bu oldu.
BASLIKLAR = {
    "User-Agent": (
        "haber-bot/1.0 "
        "(https://github.com/ozdogangringo-sketch/haber-bot; "
        "Instagram haber botu, kisisel proje)"
    ),
    "Accept": "application/json",
}

# Wikimedia'ya saniyede birden fazla istek atmıyoruz. Ücretsiz ve
# gönüllü bir hizmet; nazik davranmak hem doğru hem de engellenmemizi
# önlüyor.
_ISTEKLER_ARASI_SANIYE = 1.2
_son_istek = 0.0
_kilit = threading.Lock()


def _nazik_bekle():
    global _son_istek
    with _kilit:
        gecen = time.monotonic() - _son_istek
        if gecen < _ISTEKLER_ARASI_SANIYE:
            time.sleep(_ISTEKLER_ARASI_SANIYE - gecen)
        _son_istek = time.monotonic()


def _istek(url: str, parametreler: dict | None = None, deneme: int = 3):
    """429 yersek bekleyip tekrar dener."""
    for sira in range(1, deneme + 1):
        _nazik_bekle()
        cevap = requests.get(url, params=parametreler, headers=BASLIKLAR, timeout=30)
        if cevap.status_code == 429:
            bekle = 3 * sira
            log.warning("Wikimedia 429, %d sn bekleniyor", bekle)
            time.sleep(bekle)
            continue
        cevap.raise_for_status()
        return cevap
    raise RuntimeError("Wikimedia ısrarla 429 döndürüyor")

# Ticari kullanıma açık lisanslar. NC (non-commercial) ve ND (türev yasak)
# olanları ELEMEK zorundayız — Instagram hesabı ticari sayılabilir.
UYGUN_LISANSLAR = ("public domain", "cc0", "cc by", "cc-by", "pd-", "attribution")
YASAK_PARCALAR = ("nc", "non-commercial", "noncommercial", "nd", "no derivative")

ASGARI_GENISLIK = 500        # bundan küçük görsel 1080'e büyütülünce bozuluyor

# Dosya adında bunlar geçiyorsa haber görseli olmaz — ele.
# ("Donald Trump" araması ilk denemede lise yıllığı fotoğrafı getirdi;
#  liste o hatadan doğdu.)
ISTENMEYEN = (
    "signature", "imza", "logo", "coat of arms", "seal", "stamp",
    "banner", "flag", "map", "chart", "graph", "diagram", "cartoon",
    "caricature", "statue", "monument", "grave", "yearbook", "school",
    "child", "young", "baby", "wax", "museum", "poster", "book cover",
    "protest sign", "graffiti", "mural", "sticker",
    # Harita/şema aileleri "map" kelimesini içermeden de geliyor.
    # Gerçek örnek (15 Ağu 2026): kadın hakları haberine
    # "2021 Taliban Offensive - Situation on 25 July" haritası geldi —
    # dosya adında "map" yok, o yüzden eski liste yakalayamadı.
    "situation on", "offensive", "territorial", "areas of control",
    "timeline", "infographic", "election results", "order of battle",
    "casualties", "deployment",
    # Şema/belge ailesi. Harita elendikten sonra aynı habere bu kez
    # "Government of the Islamic Emirate of Afghanistan" organizasyon
    # şeması geldi — teknik olarak fotoğraf, ama okunmayan bir kutu
    # yığını slaytta anlamsız duruyor.
    "government of", "structure", "organigram", "org chart", "hierarchy",
    "flowchart", "schematic", "family tree", "list of", "coat of",
)

# TEK KİŞİLİK kare işaretleri — bunlar aranan kişiyi yalnız gösteriyor.
TEK_KISI = ("official portrait", "portrait", "resmi portre", "headshot",
            "speech", "press conference", "interview")

# ÇOK KİŞİLİK kare işaretleri — ELEME DEĞİL, puan düşürme.
#
# Neden gerekli: eski listede "meeting", "summit", "conference", "visit"
# ÖDÜLLENDİRİLİYORDU. Sonuç: Bakan Göktaş haberine, kendisinin Bangladeşli
# bir yetkiliyle OIC konferansındaki fotoğrafı geldi — haber taciz
# iddiasıyla ilgiliydi, karede ise tanımadığımız ikinci bir kişi ve
# tamamen başka bir olay vardı. Bir haber görselinde bu yanıltıcı.
#
# Eleme değil düşürme, çünkü kişinin arşivde yalnızca grup fotoğrafı
# olabiliyor; hiç fotoğraf olmamasındansa düşük puanla o kalsın, ama
# tek kişilik bir kare varsa hep o kazansın.
COK_KISI = (" and ", " with ", " meets", "meeting", "summit", "delegation",
            "ceremony", "signing", "group photo", "handshake", "visit to",
            "receives", "welcomes", "bilateral")


def _metni_temizle(ham: str) -> str:
    """Commons meta verisi HTML içerebiliyor."""
    return re.sub(r"<[^>]+>", "", ham or "").strip()


def _lisans_uygun_mu(lisans: str) -> bool:
    l = (lisans or "").lower()
    # Kelime bazlı bak: "cc by-nc" elenmeli ama "cc by" geçmeli
    parcalar = re.split(r"[\s\-]+", l)
    if any(y in parcalar for y in ("nc", "nd")):
        return False
    if any(y in l for y in ("non-commercial", "noncommercial", "no derivative")):
        return False
    return any(iyi in l for iyi in UYGUN_LISANSLAR)


def _sadelestir(metin: str) -> str:
    """
    Türkçe karakterleri Latin karşılığına indirger ve küçük harfe çevirir.

    Commons dosya adları Latin harfle yazılıyor: Akın Gürlek'in fotoğrafı
    orada "Gurlek speech in 2026" adıyla duruyor. Ham karşılaştırma
    yapınca DOĞRU portreler eleniyordu — Erdoğan/Erdogan da öyle.
    """
    esler = str.maketrans("ğĞüÜşŞıİöÖçÇâÂîÎûÛ", "gGuUsSiIoOcCaAiIuU")
    return metin.translate(esler).casefold()


def _isim_tutuyor_mu(baslik: str, konu: str) -> bool:
    """
    Bulunan dosyanın gerçekten aranan kişiye ait olup olmadığını denetler.

    Commons'ın araması gevşek: "İSKİ" araması "Iski Kocsis Tibor" adlı
    Macar bir sanatçının portresini getirdi ve baraj haberinin arkasına
    o kondu. Aranan isim birden fazla kelimeyse SOYADI dosya adında
    geçmeli — geçmiyorsa bambaşka birini bulmuşuz demektir.

    Tek kelimelik aramalarda bu denetim yapılamıyor (kıyas edecek soyadı
    yok), o yüzden serbest bırakıyoruz; asıl koruma orada Gemini'ye
    "kurum adı yazma" demek.
    """
    parcalar = [p for p in konu.split() if len(p) > 2]
    if len(parcalar) < 2:
        return True
    return _sadelestir(parcalar[-1]) in _sadelestir(baslik)


def _aday_puani(baslik: str, genislik: int, yukseklik: int,
                konu: str = "") -> int:
    """
    Aday fotoğrafı puanlar. Yüksek puan = daha iyi haber görseli.
    Negatif dönerse aday elenir.

    "Lisansı uygun ilk sonuç" almak yetmiyor: uygun ≠ isabetli.
    İlk denemede Trump için lise yıllığı fotoğrafı geldi.
    """
    b = baslik.lower()

    if any(kotu in b for kotu in ISTENMEYEN):
        return -1

    if konu and not _isim_tutuyor_mu(baslik, konu):
        return -1

    puan = 0

    # Tek kişilik kare tercih ediliyor
    puan += sum(35 for iyi in TEK_KISI if iyi in b)

    # Çok kişilik kare cezalandırılıyor ama elenmiyor: kişinin arşivde
    # başka fotoğrafı olmayabilir, gradyana düşmektense bu iyidir.
    puan -= sum(30 for kotu in COK_KISI if kotu in b)

    # Aranan kişiden BAŞKA bir tam isim daha geçiyorsa karede muhtemelen
    # iki kişi var. Dosya adındaki büyük harfle başlayan ardışık kelime
    # çiftlerini sayıyoruz ("Zahid Hossain and Mahinur Ozdemir Goktas").
    if konu:
        kelimeler = baslik.replace("_", " ").split()
        isim_ciftleri = sum(
            1 for i in range(len(kelimeler) - 1)
            if kelimeler[i][:1].isupper() and kelimeler[i + 1][:1].isupper()
            and len(kelimeler[i]) > 2 and len(kelimeler[i + 1]) > 2
        )
        if isim_ciftleri >= 3:
            puan -= 25

    # Yeni tarihli olsun: dosya adındaki yılı yakala
    yillar = [int(y) for y in re.findall(r"(19\d{2}|20\d{2})", baslik)]
    if yillar:
        en_yeni = max(yillar)
        if en_yeni >= 2020:
            puan += 40
        elif en_yeni >= 2015:
            puan += 25
        elif en_yeni >= 2005:
            puan += 5
        else:
            puan -= 30          # çok eski, arşiv görseli
    # yıl yoksa nötr

    # Çözünürlük: büyük iyi ama devasa olması avantaj değil
    if genislik >= 2000:
        puan += 15
    elif genislik >= 1000:
        puan += 10

    # Dikey/kare görseller carousel'de daha iyi oturuyor
    if yukseklik and genislik:
        oran = yukseklik / genislik
        if 0.9 <= oran <= 1.6:
            puan += 10

    return puan


def fotograf_ara(konu: str, aday_sayisi: int = 20) -> dict | None:
    """
    Konu için lisansı uygun VE isabetli bir fotoğraf bulur.

    Tüm adayları puanlayıp en iyisini seçiyoruz; ilk uygun olanı almak
    kötü sonuç veriyor.

    Döner: {'url', 'lisans', 'sanatci', 'baslik', 'genislik', 'yukseklik'}
    veya None.
    """
    konu = (konu or "").strip()
    if not konu:
        return None

    # İkinci savunma hattı: kısaltmalar Commons'ta yanlış eşleşiyor
    # (İSKİ -> Macar sanatçı, TRT -> rastgele pavyon fotoğrafı) ve tek
    # kelime oldukları için soyadı denetiminden de kaçıyorlar. Gemini'ye
    # zaten "kurum yazma" dedik; bu, o kural delinirse diye duruyor.
    if len(konu.split()) == 1 and konu.isupper():
        log.info("kısaltma Commons'a sorulmuyor: %s", konu)
        return None

    parametreler = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"filetype:bitmap {konu}",
        "gsrnamespace": "6",                 # 6 = File: alanı
        "gsrlimit": str(aday_sayisi),
        "prop": "imageinfo",
        "iiprop": "url|size|extmetadata",
        "iiurlwidth": "2000",   # ⚠️ 1600'dü: portre kırpması sonrası 1080
                                #    genişliğe çıkarken pay kalmıyordu
    }

    try:
        veri = _istek(API, parametreler).json()
    except Exception as e:
        log.warning("Commons araması başarısız (%s): %s", konu, e)
        return None

    sayfalar = (veri.get("query", {}) or {}).get("pages") or {}
    adaylar = []

    for sayfa in sayfalar.values():
        bilgi = (sayfa.get("imageinfo") or [{}])[0]
        meta = bilgi.get("extmetadata") or {}

        def al(ad: str) -> str:
            return _metni_temizle((meta.get(ad) or {}).get("value", ""))

        lisans = al("LicenseShortName") or al("License")
        if not _lisans_uygun_mu(lisans):
            continue

        genislik = bilgi.get("width") or 0
        yukseklik = bilgi.get("height") or 0
        if genislik < ASGARI_GENISLIK:
            continue

        url = bilgi.get("thumburl") or bilgi.get("url")
        if not url:
            continue

        baslik = (sayfa.get("title") or "")[5:]      # "File:" önekini at
        puan = _aday_puani(baslik, genislik, yukseklik, konu)
        if puan < 0:
            continue

        adaylar.append({
            "url": url,
            "lisans": lisans,
            "sanatci": al("Artist")[:80],
            "baslik": baslik,
            "genislik": genislik,
            "yukseklik": yukseklik,
            "puan": puan,
        })

    if not adaylar:
        log.info("Commons'ta uygun görsel bulunamadı: %s", konu)
        return None

    adaylar.sort(key=lambda a: a["puan"], reverse=True)
    return adaylar[0]


def fotografi_indir(kayit: dict) -> Image.Image | None:
    """Bulunan fotoğrafı indirip Pillow görüntüsü olarak döner."""
    try:
        cevap = _istek(kayit["url"])
        return Image.open(io.BytesIO(cevap.content)).convert("RGB")
    except Exception as e:
        log.warning("fotoğraf indirilemedi (%s): %s", kayit.get("baslik"), e)
        return None


def atif_metni(kayit: dict) -> str:
    """
    Caption'a eklenecek atıf satırı.

    Kamu malı görsel için hukuken zorunlu değil ama CC BY için ŞART.
    Ayırt etmekle uğraşmayıp hepsine yazıyoruz — dürüst ve zararsız.
    """
    parcalar = [kayit.get("baslik", "").rsplit(".", 1)[0]]
    if kayit.get("sanatci"):
        parcalar.append(kayit["sanatci"])
    if kayit.get("lisans"):
        parcalar.append(kayit["lisans"])
    return "Foto: " + " / ".join(p for p in parcalar if p) + " (Wikimedia Commons)"


def konu_icin_fotograf(konu: str) -> tuple[Image.Image, dict] | None:
    """
    Tek adımda: ara + indir. Bulamazsa None.
    Çağıran taraf None gelirse soyut/gradyan arka plana düşmeli.
    """
    kayit = fotograf_ara(konu)
    if not kayit:
        return None
    gorsel = fotografi_indir(kayit)
    if gorsel is None:
        return None
    return gorsel, kayit
