"""
generate_text.py — ADIM 2
durum='yeni' haberleri alır, Gemini ile Instagram metni üretir,
durum='metin_hazir' yapar.

TASARIMIN EN ÖNEMLİ KARARI — neden makale gövdesini çekiyoruz:

    RSS özetleri "devamı sitemizde" teaser'ları. Ölçtük: haberlerin
    %76'sının özeti 200 karakterin altında.

    120 karakterlik bir teaser'dan 2-3 cümlelik caption isteyince model
    aradaki boşluğu UYDURUYOR. Gerçek testte üç ayrı Gemini modeli de
    kaynakta olmayan iddialar üretti — üstelik adı geçen gerçek bir kişi
    ve ciddi bir suçlama hakkında. Böyle bir metni yayınlamak iftira olur.

    Aynı haberi makalenin 4000 karakterlik gövdesiyle verdiğimizde
    modellerin yazdığı her cümle kaynakta doğrulanabilir çıktı.

    Bu yüzden önce fetch_article ile gövdeyi çekiyoruz, ancak
    çekemezsek RSS özetine düşüyoruz — ve o durumda modele
    "elindeki bilgi az, kısa yaz, uydurma" diyoruz.

Dışarıdan kullanımı:
    from src.generate_text import metinleri_uret
    rapor = metinleri_uret(limit=5)
"""

from __future__ import annotations

import json
import logging
import os
import time

import requests
from dotenv import load_dotenv

from . import db
from .fetch_article import makale_metni_cek
from .fetch_news import ayarlari_oku

log = logging.getLogger(__name__)

load_dotenv()

UC_NOKTA = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Geçici hatalar — bunlarda tekrar denemek mantıklı.
# 503 = model yoğun, 429 = kota/hız sınırı, 500/502/504 = sunucu hıçkırığı
GECICI_HATALAR = {429, 500, 502, 503, 504}

# ⚠️ GÜNLÜK KOTASI TÜKENMİŞ (model, anahtar) İKİLİLERİ.
#
# Ölçüldü (20 Ağu 2026): akşam turu 13 dakika sürüyordu ve süresinin
# %92'si metin üretimindeydi. Log'a bakınca sebep açıktı — ücretsiz
# kota günde 20 istek, tur 25 adaya metin üretiyor. Kota bitince HER
# HABER aynı ölü kapıyı 3 kez çalıyordu:
#     429 -> 2 sn bekle -> 429 -> 4 sn bekle -> 429 -> 6 sn bekle
# yani haber başına ~12 saniye SAF BEKLEME, 25 haberde 5 dakika.
#
# Bir model+anahtar ikilisi günlük kota hatası verdiyse aynı süreç
# içinde bir daha denenmiyor; doğrudan sıradaki modele/anahtara
# geçiliyor. Süreç bitince küme de gidiyor, yani ertesi çalıştırmada
# kota yeniden deneniyor (Pasifik gece yarısı sıfırlanıyor).
_TUKENMIS: set[tuple[str, str]] = set()


def _gunluk_kota_hatasi(cevap) -> bool:
    """429 cevabı GÜNLÜK kota mı, yoksa dakikalık hız sınırı mı?"""
    try:
        mesaj = cevap.json().get("error", {}).get("message", "")
    except Exception:                                 # noqa: BLE001
        return False
    # Google günlük kotayı "PerDay" içeren quotaId ile bildiriyor.
    return "PerDay" in mesaj or "per day" in mesaj.lower()

# Gemini'den JSON istiyoruz. Şema vermek, "bazen düz metin döndürme"
# sorununu tamamen ortadan kaldırıyor.
# ⚠️ KATEGORİ LİSTESİ SABİT VE KAPALI.
#
# Model buraya yazılı olmayan bir kategori üretirse:
#   * `config.yaml → gorsel.serit_renkleri` o kategoriyi tanımıyor ve
#     slayt sessizce "turkiye" rengine düşüyor,
#   * `secim.kategori_katsayilari` de tanımıyor, ön elemede varsayılan
#     katsayı uygulanıyor.
# Bu yüzden şemada `enum` ile kapatıldı — model yalnızca bunlardan
# birini seçebiliyor. Yeni kategori eklemek isteyen ÜÇ yeri birden
# güncellemeli: burası, serit_renkleri, kategori_katsayilari.
KATEGORILER = ["turkiye", "dunya", "ekonomi", "spor",
               "bilim", "teknoloji", "kultur", "yasam"]

CEVAP_SEMASI = {
    "type": "object",
    "properties": {
        "ig_baslik": {"type": "string"},
        "ig_caption": {"type": "string"},
        "ig_hashtag": {"type": "array", "items": {"type": "string"}},
        "onem_puani": {"type": "integer"},
        # Slaytta başlığın altına basılan kısa cümle
        "slayt_ozet": {"type": "string"},
        "detay_metni": {"type": "string"},
        # Vurgu öğeleri — yoksa boş string
        "vurgu_sayi": {"type": "string"},
        "vurgu_etiket": {"type": "string"},
        "alinti": {"type": "string"},
        "alinti_sahibi": {"type": "string"},
        # Commons araması için kişi/kurum. Yoksa boş string.
        "gorsel_konu": {"type": "string"},
        # Pexels araması için İngilizce temsili terim.
        "gorsel_temsili": {"type": "string"},
        # ⚠️ HABERİN KENDİ KATEGORİSİ — kaynağınki DEĞİL.
        # `fetch_news` kategoriyi RSS beslemesinden atıyor ve o çoğu
        # zaman yanlış: "ABD, Katar'a yakıt ikmal uçağı satışını
        # onayladı" AA'nın ekonomi beslemesinden geldiği için
        # "ekonomi" damgası yiyordu. Model haberin TAM METNİNİ zaten
        # okuyor; doğru cevabı verebilecek tek yer burası.
        "kategori": {"type": "string", "enum": KATEGORILER},
        # Slaytın sağ üstündeki bayrak için ISO 3166-1 alpha-2 kodu
        "ulke_kodu": {"type": "string"},
        # Bayrağın altına yazılan Türkçe ülke adı
        "ulke_adi": {"type": "string"},
        # Smart Brevity editoryal alanları
        "neden_onemli": {"type": "string"},
        "sirada_ne_var": {"type": "string"},
        # Slayt içi mini veri rozeti (infografik) alanları
        "veri_karti_etiket": {"type": "string"},
        "veri_karti_eski": {"type": "string"},
        "veri_karti_yeni": {"type": "string"},
        "veri_karti_yon": {"type": "string"},
        # İkili aktör / Split-Screen için 2 kişinin adı (varsa)
        "gorsel_ikili": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "ig_baslik", "ig_caption", "ig_hashtag", "onem_puani",
        "slayt_ozet", "detay_metni", "vurgu_sayi", "vurgu_etiket",
        "alinti", "alinti_sahibi", "gorsel_konu", "gorsel_temsili",
        "kategori", "ulke_kodu", "ulke_adi", "neden_onemli",
        "sirada_ne_var", "veri_karti_etiket", "veri_karti_eski",
        "veri_karti_yeni", "veri_karti_yon", "gorsel_ikili",
    ],
}


PROMPT = """Sen bir Türk haber Instagram hesabının editörüsün.
Aşağıdaki haberi Instagram paylaşımına dönüştür.

EN ÖNEMLİ KURAL — BUNU ASLA ÇİĞNEME:
Sadece aşağıdaki HABER METNİNDE yazan bilgileri kullan. Metinde geçmeyen
hiçbir iddiayı, sayıyı, ismi, tepkiyi veya sonucu yazma. Emin değilsen o
cümleyi hiç kurma. Eksik yazmak, uydurmaktan iyidir.

SAYILAR — KAYNAKTAKİ GİBİ YAZ, YUVARLAMA:
Kaynakta "2 milyar 841 milyon lira" yazıyorsa aynen öyle yaz.
"2,8 milyar" diye yuvarlama — matematiksel olarak doğru olsa bile
okuyucu rakamı senin verdiğin haliyle alıntılıyor ve kaynakla
karşılaştırıldığında tutmuyor. Otomatik doğrulama da bunu uydurma
sanıp uyarı üretiyor. Tarih, oran, kişi sayısı için de aynı kural.

HUKUKİ DİKKAT:
Suçlama, soruşturma veya dava içeren haberlerde "iddia edildi",
"öne sürüldü", "hakkında soruşturma başlatıldı" gibi ifadeler kullan.
Hiç kimseyi suçlu ilan etme. Mahkeme kararı olmadan kesin dille yazma.

DEĞİŞEN SAYILAR — ÖLÜ/YARALI SAYISINDA "EN AZ" KULLAN:
Deprem, kaza, saldırı gibi haberlerde can kaybı saatlik güncelleniyor.
"47 kişi öldü" yarım saat sonra YANLIŞ olur; "en az 47 kişi hayatını
kaybetti" olmaz — sayı artsa bile ifade doğru kalır.
  KÖTÜ: "Depremde 47 kişi hayatını kaybetti"
  İYİ : "Depremde en az 47 kişi hayatını kaybetti"
  İYİ : "Ölü sayısı 47'ye yükseldi"   (yükseldi = o anki durum)
Aynı kural yaralı, kayıp, gözaltı, tahliye sayıları için de geçerli.
Kaynak "en az" demiyorsa bile sen "en az" yaz — sayının artabileceği
her durumda bu daha doğru.

DİĞER KURALLAR:
- Çıktının tamamı Türkçe olacak. Haber İngilizceyse Türkçeye çevir.
  ★ KANCA ETKİSİ VE DİKKAT ÇEKİCİ MANŞET DİLİ (ASLA MANİPÜLE ETMEDEN) ★
  Başlık akışta kaydırmayı durduran güçlü bir KANCA (Hook) olmalıdır:
  1. Haberdeki en can alıcı eylemi, etkiyi veya değişimi doğrudan ilk kelimelere yerleştir.
  2. Gerçeği zerre manipüle etmeden, abartısız ama vurucu bir fiil veya somut sonuç kullan.
  3. "Önemli gelişme", "açıklama yapıldı" gibi pasif laflar yerine; doğrudan olayı anlatan dinamik manşet kur ("Fed faizi indirdi", "TCMB rezervleri rekor kırdı", "THY 50 yeni uçak siparişi verdi").
  4. Başlığı okuyan kişi haberin sonucunu %100 öğrenmeli, fakat detayları okumak için slaytı kaydırma isteği uyandırmalıdır.

  ★ EN ÖNEMLİ KURAL — BAŞLIK HABERİN SONUCUNU SÖYLEMELİ ★
  Bu bir haber hesabı, tıklama tuzağı değil. Takipçiye link vermiyoruz,
  okuyacağı başka bir yer yok. Slaytı kaydırıp geçen kişi haberi
  ÖĞRENMİŞ olmalı. Konuyu duyurup sonucu saklamak, tam da clickbait
  sayfalarının yaptığı şey — bizim yapmadığımız şey.

  Kendine şunu sor: "Bu başlığı okuyan biri NE OLDUĞUNU biliyor mu?"
  Cevap hayırsa başlık yanlıştır.

  ŞU KALIPLARI KULLANMA — hepsi konuyu söyleyip sonucu saklıyor:
      "...'a ilişkin açıklama"      "...'a dair açıklama"
      "...hakkında konuştu"          "...değerlendirdi"
      "...anlattı"                   "...ele aldı"
      "...mesaj verdi"               "...görüş bildirdi"
      "...gündeme getirdi"           "...dikkat çekti"

  KÖTÜ  → "Bakan Göktaş'tan taciz iddialarına ilişkin açıklama"
  İYİ   → "Bakan Göktaş: Taciz iddiaları vahim, süreci takip edeceğiz"

  KÖTÜ  → "Afgan kadınlar Taliban yönetimindeki yılları anlattı"
  İYİ   → "Afgan kadınlar 6. sınıftan sonra okula gidemiyor"

  KÖTÜ  → "Bakan Fidan Mısır ziyaretini değerlendirdi"
  İYİ   → "Türkiye ve Mısır ticareti artıracak anlaşmalara imza attı"

  Biri konuşuyorsa NE DEDİĞİNİ yaz. Bir karar alındıysa KARARIN NE
  OLDUĞUNU yaz. Bir sayı varsa SAYIYI yaz.

  ABARTMA DA YOK: "şok", "bomba", "herkesi şaşırttı", "işte o an" gibi
  ifadeler kullanma. Sonucu düz ve net söylemek zaten yeterince ilgi
  çekici — abartı güveni düşürür.

  BÜYÜK HARF KURALI: normal cümle yazımı kullan — yalnızca ilk kelime ve
  özel adlar büyük harfle başlasın ("Ankara'da toplu ulaşım ücretlerine
  zam yapıldı"). Her Kelimeyi Büyük Harfle Başlatma. Bu bir tutarlılık
  kuralı: aynı carousel'de iki üslup yan yana gelince özensiz duruyor.
  Sonuna nokta koyma.
- ig_caption: 2-3 cümle, haberin özü. Haberdeki en can alıcı anahtar terimleri, kurumları veya oranları **bold** (çift yıldız) ile vurgula. Kişi söylemlerini çift tırnak "..." içine al. Kaynak adını yazma.
- ig_hashtag: 5-8 adet, Türkçe ve konuyla ilgili, '#' işareti OLMADAN.
- Taraf tutma, yorum katma, spekülasyon yapma.

GÖRSEL ALANLARI — slaytın arka planını bunlar belirliyor:

- slayt_ozet: TEK cümle, en fazla 18 kelime. Başlıkta OLMAYAN somut bir
  bilgi ver (sayı, oran, sonuç, kim söyledi). Başlığı farklı kelimelerle
  tekrar etme — slaytta ikisi alt alta görünüyor.

  Başlık + özet birlikte okunduğunda takipçi o haberi ÖĞRENMİŞ olmalı.
  Başka kaynağa gitmesine gerek kalmamalı; zaten link vermiyoruz.
  Özet, başlıkta yer kalmayan ikinci en önemli bilgiyi taşısın.

- detay_metni: 120-220 kelime, PARAGRAFLAR HÂLİNDE. Haberin ayrıntılı
  anlatımı — slaytlara yayılıyor.

  VURGULAMA VE SÖYLEMLER (TİPOGRAFİK HİYERARŞİ):
  * Paragraf içinde ilk bakışta yakalanması gereken kritik rakamları, tarihleri, kişi veya kurum isimlerini **vurgulu** (çift yıldız) yaz.
  * Kişilerin doğrudan ağzından çıkan söylemleri, demeçleri ve resmi açıklamaları mutlaka çift tırnak içine al: "..." veya “...”.

  BİÇİM: 3-5 paragraf, her biri 20-32 kelime. KISA TUT — uzun paragraf
  slaytta tek başına sayfayı dolduruyor ve düzen yine tekdüze oluyor.
  Paragrafları BOŞ SATIRLA
  ayır (\n\n). Tek blok hâlinde yazma — slaytta duvar gibi görünüyor
  ve kimse okumuyor.

  İLK PARAGRAF EN ÇARPICI BİLGİYİ TAŞISIN. Slaytta iri puntoyla
  basılıyor, okuyan ilk onu görüyor. Gazetecilikteki "spot" mantığı:
  en önemli sonuç, en büyük sayı, en dikkat çekici ayrıntı önce gelir.
  Kronolojik anlatma — "önce şu oldu, sonra bu oldu" diye başlama.

  Sonraki paragraflar bağlamı açar: nasıl oldu, kim ne dedi, bundan
  sonra ne olacak. Her paragraf TEK bir konuyu anlatsın.

  ÖRNEK BİÇİM:
    Depremde en az 47 kişi hayatını kaybetti, 200'den fazla kişi yaralandı.

    Sarsıntı yerel saatle 03.20'de meydana geldi ve merkez üssü kıyıya
    12 kilometre uzaklıktaydı.

    Bölgeye 14 arama kurtarma ekibi sevk edildi; yetkililer enkaz
    altında kalan olabileceğini bildirdi.

  Kaynak metinde ne varsa onu anlat; BİLGİ UYDURMA, kaynakta olmayan
  ayrıntı ekleme. Kaynak kısaysa 2 paragraf yeter — doldurmak için
  cümle üretme.

- vurgu_sayi / vurgu_etiket: haberin EN ÇARPICI rakamı ve ne olduğu.
  Slaytta iri puntoyla ayrı basılıyor, ilk göze çarpan şey o oluyor.
    vurgu_sayi   : EN FAZLA 3 KELİME. "2.352 yıl" / "en az 47" / "%14,3"
                   KÖTÜ: "828 yıldan 2.352 yıla" (çok uzun, slayta sığmıyor)
                   İYİ : "2.352 yıl"  — en çarpıcı olan tek rakamı seç
    vurgu_etiket : "istenen hapis cezası" / "hayatını kaybeden" / "zam oranı"
  Etiket 2-5 kelime, küçük harfle. Rakamı KAYNAKTAKİ GİBİ yaz.
  ⚠️ BAŞLIKTA GEÇEN SAYIYI VURGU OLARAK VERME. Başlık "32 kişi
  tutuklandı" diyorsa vurgu_sayi "32" olmamalı — aynı bilgiyi iki kez
  vermiş olursun. Başlıkta OLMAYAN, ikinci derecede çarpıcı bir rakam
  seç (tutar, süre, oran, adres sayısı) ya da boş bırak.

  Haberde öne çıkan bir rakam yoksa İKİSİNİ DE BOŞ BIRAK — zorlama
  rakam bulma, sıradan bir sayıyı büyütmek okuyucuyu yanıltır.

- alinti / alinti_sahibi: haberde geçen çarpıcı bir SÖZ ve kimin söylediği.
    alinti        : en fazla 18 kelime, tırnak İŞARETİ OLMADAN
    alinti_sahibi : "Ekrem İmamoğlu" / "Bakan Göktaş" / "BM Sözcüsü"

  ⚠️ ALINTI KAYNAK METİNDE AYNEN GEÇMELİ. Kelimeleri değiştirme,
  kısaltma, güzelleştirme, birleştirme. Birinin ağzına söylemediği sözü
  koymak yapabileceğin en ağır hata — sistem bunu kaynakta arıyor ve
  bulamazsa alıntıyı ATIYOR.
  Haberde doğrudan alıntı yoksa İKİSİNİ DE BOŞ BIRAK.

- neden_onemli: 1 VEYA 2 CÜMLE (en fazla 25 kelime).
  Haberin arka planını, kritik önemini, insani/sektörel/küresel etkisini veya olayın büyüklüğünü anlatan net ve vurucu bir cümle yaz.
  Önemli kelimeleri **kalın** ile vurgula (örn: "**muson yağmurları** ve **altyapı hasarı** kurtarma çalışmalarını aksatıyor").
  Spot metindeki bilgiyi birebir kopyalama; olayın NEDEN KRİTİK olduğunu ve yarattığı etkiyi açıkla.

- sirada_ne_var: TEK CÜMLE (en fazla 18 kelime). Haberde açıkça belirtilen
  sonraki resmi adım, duruşma tarihi, toplantı veya yürürlük tarihi.
  ⚠️ KAYNAKTA GELECEĞE DAİR RESMİ BİR BİLGİ/TARİH YOKSA BOŞ STRING ("") BIRAK.
  Asla kendi kafandan tahmin veya spekülasyon uydurma.

- veri_karti_*: Haberde somut bir karşılaştırma, oran veya değişim varsa doldur,
  yoksa boş bırak:
    veri_karti_etiket : "Yıllık Enflasyon", "Hedef Fiyat", "Kâr Artışı", "Faiz Oranı"
    veri_karti_eski   : "%48,2" veya "80 $" (varsa, yoksa "")
    veri_karti_yeni   : "%42,0" veya "86 $"
    veri_karti_yon    : "artis" (artış/yükseliş) | "azalis" (düşüş/gerileme) | "hedef" (hedef/beklenti) | "notr" (sabit) | "" (veri yoksa)
  ⚠️ SAYILARI KAYNAKTAN AL, UYDURMA.

- gorsel_konu: SADECE GERÇEK BİR İNSANIN ADI VE SOYADI. Başka hiçbir şey.
  (örn: "Hakan Fidan", "Ekrem İmamoğlu")

- gorsel_ikili: İki lider, bakan veya aktör arasındaki diplomatik zirve,
  anlaşma veya temas haberi ise iki kişinin adı: ["Recep Tayyip Erdoğan", "Abdülfettah es-Sisi"].
  Tek kişi varsa veya kişi yoksa boş dizi [] bırak.

- gorsel_temsili: Konuyu temsil eden İNGİLİZCE stok fotoğraf arama terimi.

  İKİ ŞART BİRDEN — biri olmadan diğeri işe yaramıyor:

  1) KONUYA DOĞRUDAN BAĞLI OLACAK. Fotoğrafa bakan kişi haberin neyle
     ilgili olduğunu anlamalı.
     ⚠️ Ölçüldü (21 Ağu 2026): soyut ve manzara terimleri konuyu
     kaybettiriyor. Orman yangını haberine "aerial view of forest
     canopy" istendiğinde Pexels YEMYEŞİL huzurlu bir orman verdi —
     yangın haberinin altında yanlış his uyandırıyor.
        KÖTÜ: "storm clouds over field"  (deprem haberi için soyut)
        KÖTÜ: "long exposure dust particles"  (hiçbir şey anlatmıyor)

  2) YAZI/TABELA İÇEREBİLECEK SAHNE İSTEME. Asıl sorun "geniş" olması
     değil, ÜSTÜNDE YAZI olması: tabelalar yabancı dilde çıkıyor ve
     Türkiye haberinde İspanyolca hastane tabelası özensiz görünüyor.
     Aynı sebeple yer adı geçen terim isteme — "storm clouds over
     empty field" araması "a road in Nagka, India" getirdi.
        KÖTÜ: "hospital corridor", "city bus stop", "courthouse"

  KOMPOZİSYON SERBEST — "close up" ZORUNLU DEĞİL. Yakın plan nesne de,
  sahne de olabilir; yeter ki yukarıdaki iki şartı sağlasın. Hep aynı
  kalıbı kullanmak hesabı tekdüze gösteriyor.
        İYİ: "firefighter helmet close up"          (yakın plan nesne)
        İYİ: "burning forest branches at night"     (sahne, konuya bağlı)
        İYİ: "stethoscope on medical chart"         (nesne, düzenlenmiş)
        İYİ: "dry cracked earth"                    (doku, kuraklık haberi)

  ÜRÜN, DONANIM, FİNANS VE TEKNOLOJİ HABERLERİNDE NOKTA ATIŞI SOMUT TERİMLER:
        İYİ: "silicon wafer AI microchip closeup"   (çip/yapay zeka haberi)
        İYİ: "commercial passenger jet airplane"    (uçak/havacılık haberi)
        İYİ: "gold bullion bars dark vault luxury"  (altın/emtia haberi)
        İYİ: "stock market trading chart screen"    (borsa/hisse haberi)
        İYİ: "modern electric car charging station" (otomotiv/araç haberi)
        İYİ: "modern clean energy turbine facility" (enerji/nükleer haberi)

    * 3-6 kelime yeter.
    * Asla genel/soyut ofis tokalaşması veya bulanık genel manzara isteme.
    * İnsan YÜZÜ içeren sahne isteme — tanımadığımız biri haberle
      ilişkilendirilmiş görünür. (El, silüet, arkadan görünüm sorun değil.)

- kategori: Haberin KENDİ konusu. Yalnızca şunlardan biri:
    turkiye   — Türkiye gündemi, iç siyaset, asayiş, adliye, yerel olaylar
    dunya     — yurt dışı olaylar, uluslararası ilişkiler, savaş/diplomasi
    ekonomi   — borsa, hisse, piyasa, altın, döviz, faiz, merkez bankası, enflasyon, şirket bilançosu, makroekonomi, fon ve kripto
    spor      — müsabaka, transfer, kulüp, sporcu
    bilim     — araştırma, uzay, sağlık/tıp bulgusu, çevre, arkeoloji
    teknoloji — yazılım, yapay zeka, donanım, siber güvenlik, internet, oyun
    kultur    — sanat, edebiyat, sinema, müzik, tarih/miras
    yasam     — turizm istatistikleri, havalimanı/uçuş sayıları, belediye/esnaf/KOSGEB duyuruları, tüketici denetimleri, tarım destekleri, eğitim, ulaşım, gündelik hayat

  ⚠️ KATEGORİ AYRIMI KURALLARI:
  * Turist sayısı, havalimanı yolcu rekoru, tarımsal destek/gübre ödemesi, zabıta denetimi veya KOSGEB hibesi gibi haberler "ekonomi" DEĞİLDİR; bunlar "yasam" veya "turkiye"dir.
  * "ekonomi" kategorisini YALNIZCA gerçek finans, borsa, piyasa, şirket bilançoları, altın/döviz ve para politikası haberleri için kullan.
  * Haberi yayınlayan kaynağın adına göre DEĞİL, haberin içeriğine göre seç. (Bir ekonomi servisinin yayınladığı silah satışı haberi "dunya"dır).

  Olay Türkiye'de geçiyorsa ve konusu özel bir alan değilse "turkiye"
  seç. Türkiye'de geçen bir maç "spor", Türkiye'de açıklanan enflasyon
  "ekonomi"dir — yani özel alan Türkiye'yi yener.

- ulke_kodu / ulke_adi: Haberin GEÇTİĞİ ülke — haberi yayınlayan kaynağın
  ülkesi değil. BBC'nin Belçika'daki bir olayı aktardığı haberde ülke
  Belçika'dır, İngiltere değil.
    ulke_kodu: ISO 3166-1 alpha-2, KÜÇÜK harf ("tr", "us", "be")
    ulke_adi : Türkçe ülke adı ("Türkiye", "ABD", "Belçika")
  Birden fazla ülke geçiyorsa olayın YAŞANDIĞI ülkeyi seç.

  ÜLKESİ OLMAYAN HABERDE İKİSİNİ DE BOŞ BIRAK. Zorlama ülke atama.
  Bir coğrafyaya bağlı olmayan haberler var: bilim buluşu, teknoloji,
  küresel bir araştırma, borsa/kripto, uzay. Bunlarda bayrak basmak
  yanlış bir yer bilgisi vermek olur — boş bırakmak DOĞRU cevaptır.

  Haber uluslararası bir KURULUŞUN kendi kararı/açıklamasıysa, ülke
  yerine kuruluş kodunu yazabilirsin. Tanınan kodlar yalnızca şunlar:
    nato, un, eu, who, unesco, unicef, opec, oic, africanunion,
    arableague, commonwealth, redcross
  ulke_adi'na Türkçe adını yaz ("NATO", "Birleşmiş Milletler",
  "Avrupa Birliği", "Dünya Sağlık Örgütü").
  Listede olmayan bir kuruluş için BOŞ bırak — spor kulübü, şirket,
  siyasi parti kodu YAZMA, onların logoları tescilli marka.

onem_puani (1-10) — Türkiye'deki ortalama bir takipçinin bu haberi
görmek isteme derecesi. Devlet önceliği değil, TAKİPÇİ önceliği ölçüyorsun.
Üç şeye birlikte bak:
  * Etki: kaç kişinin hayatına dokunuyor?
  * Aciliyet: bugün bilinmesi gerekiyor mu?
  * Konuşulurluk: insanlar bunu birbirine anlatır mı, merak eder mi?
Bu üçünü ORTALAMA. Birinde çok güçlüyse diğerleri zayıf diye düşürme:
çok konuşulacak bir olay, dar bir kesimi ilgilendirse bile yüksek alır.

  9-10 — günün EN ÖNEMLİ birkaç haberinden biri. Ertesi gün insanlar
         hâlâ bundan konuşuyorsa buraya girer.
         · büyük deprem, sel, yangın, afet
         · savaş, ateşkes, sınır ötesi operasyon kararı
         · seçim sonucu, hükümet krizi, istifa eden bakan/başkan
         · herkesin cebini etkileyen karar: asgari ücret, büyük zam,
           faiz kararı, vergi düzenlemesi
         · çok sayıda can kaybı olan kaza (uçak, tren, maden, deprem)
         · tanınan bir ismin ölümü ya da ağır bir suça karışması
         · büyük çaplı operasyon, toplu gözaltı, kayyum ataması
         · milli takımın büyük turnuvadaki sonucu, tarihi şampiyonluk
         · salgın ilanı, geniş bölgeyi kapsayan sağlık uyarısı

         ⚠️ 9 VERMEKTEN ÇEKİNME. Bu ölçek yalnızca siyasi olaylar için
         değil. Bir haber yukarıdaki tanıma uyuyorsa 9 ver; "daha
         önemlisi olabilir" diye 7-8'e çekme. Gün içinde birkaç haber
         9 alabilir, bu normaldir.

  7-8  — çoğu insanın bilmek isteyeceği haber. Siyaset ŞART DEĞİL,
         aşağıdakiler de bu banda girer:
         · dikkat çekici bilim/uzay keşfi
         · herkesi ilgilendiren sağlık bulgusu veya uyarı
         · çok konuşulacak adli olay, tanınan bir ismin karıştığı olay
         · büyük kaza, yangın, salgın, karantina
         · büyük spor sonucu, şampiyonluk, milli takım başarısı
         · geniş ilgi gören kültür/sinema/müzik gelişmesi
         · gündelik hayatı değiştiren düzenleme (trafik, okul, fatura)
         · ★ HERKESİN YARARLANABİLECEĞİ SOMUT İMKÂN: ücretsiz erişim,
           kampanya, burs, hibe, indirim, yeni ücretsiz hizmet
           (örnek: "Google öğrencilere Gemini Pro'yu ücretsiz açtı",
            "Şu tarihe kadar başvuranlara ulaşım kartı bedava")
         · son başvuru tarihi olan fırsatlar — kaçırılırsa geri gelmez

  4-6  — orta: ilgi alanına göre değişir, rutin gelişme
  1-3  — niş veya önemsiz

⚠️ AÇIKLAMA HABERİ İLE OLAY HABERİNİ AYIR — en sık yapılan hata bu.
Bir yetkilinin bir konuda konuşmuş olması, tek başına haber değildir.
Sor: burada YENİ BİR ŞEY OLDU mu, yoksa biri bilinen bir konuda görüş
mü bildirdi?
  · "Bakan X, Y konusunu değerlendirdi"      -> 3-5 (yeni bilgi yok)
  · "X, Y'yi kınadı / temenni etti / andı"   -> 3-5
  · protokol, ziyaret, tören, anma           -> 3-4
  · "X kararı alındı / yasa çıktı / imzalandı" -> gerçek sonuç, yüksek olabilir
Açıklamanın İÇİNDE somut ve yeni bir bilgi varsa (rakam, tarih, karar,
taahhüt) o zaman puanı o bilgiye göre ver, açıklama olduğuna bakma.

⚠️ İSTİSNA — SOMUT İMKÂN DUYURUSU AÇIKLAMA DEĞİLDİR:
Bir şirket ya da kurum insanların DOĞRUDAN yararlanabileceği bir şey
duyuruyorsa (ücretsiz erişim, indirim, burs, kampanya, yeni hizmet)
bu "biri konuştu" değil, OLAYDIR — düşürme, 7-8 bandında değerlendir.
  · "Google öğrencilere Gemini Pro'yu ücretsiz açtı"  -> 7-8
  · "Bakan yapay zekânın önemini vurguladı"            -> 3-5
Ayrım şu: birincisinde okuyucunun YAPABİLECEĞİ bir şey var.

{bilgi_uyarisi}
HABER
Kaynak : {kaynak}
Başlık : {baslik}
Metin  : {metin}
"""

# Gövdeyi çekemediğimizde prompt'un başına eklenen uyarı.
AZ_BILGI_UYARISI = """DİKKAT — ELİNDEKİ BİLGİ ÇOK AZ:
Aşağıda haberin tam metni değil, sadece kısa bir özeti var. Bu özet
cümlenin ortasında kesilmiş olabilir. Bu durumda caption'ı TEK CÜMLE
yaz ve sadece başlıkta/özette açıkça yazanı tekrarla. Detay uydurma.

"""


def _anahtar_al() -> str:
    anahtar = os.getenv("GEMINI_API_KEY", "").strip()
    if not anahtar:
        raise RuntimeError(
            "GEMINI_API_KEY bulunamadı. .env dosyasına eklemen gerekiyor."
        )
    return anahtar


def _anahtarlar() -> list[tuple[str, str]]:
    """
    Denenecek anahtarlar, sırayla. `(ad, anahtar)` listesi döner.

    ⚠️ İKİNCİ ANAHTAR FATURALI PROJEDE (18 Ağu 2026, kullanıcı kararı).
    `GEMINI_IMAGE_API_KEY` görsel üretimi için alınmıştı ve metin kotası
    bakir. Ücretsiz projede kota bitince istek REDDEDİLİYOR; faturalı
    projede ise ÜCRETLENDİRİLİYOR. Yani bu yedek, kota aşımında sessizce
    para harcayabilir.

    Risk bilinçli kabul edildi çünkü:
      * Günlük kullanım 25-75 çağrı, ücretsiz kotanın (binlerce) çok
        altında; ücrete girmesi için olağandışı bir döngü gerekir.
      * Alternatif, turun tamamen düşmesi.

    Yalnızca birinci anahtar KOTA yüzünden tükendiğinde devreye giriyor;
    ağ hatası veya 503'te geçilmiyor — orada sorun kotada değil.
    """
    anahtarlar = [("birincil", _anahtar_al())]
    yedek = os.getenv("GEMINI_IMAGE_API_KEY", "").strip()
    if yedek and yedek != anahtarlar[0][1]:
        anahtarlar.append(("yedek (faturalı proje)", yedek))
    return anahtarlar


def prompt_kur(kaynak: str, baslik: str, metin: str, tam_metin_var: bool) -> str:
    """Modele gidecek metni hazırlar."""
    return PROMPT.format(
        bilgi_uyarisi="" if tam_metin_var else AZ_BILGI_UYARISI,
        kaynak=kaynak,
        baslik=baslik,
        metin=metin,
    )


def gemini_cagir(prompt: str, ayarlar: dict) -> dict:
    """
    Gemini'yi çağırır, JSON sonucu döner.

    Geçici hatalarda (503 yoğunluk, 429 kota) bekleyip tekrar dener;
    birincil model ısrarla patlarsa yedek modele geçer.

    Bu gözetimsiz çalışan bir bot — gece 03:00'te 503 aldığında
    kimse müdahale edemeyeceği için dayanıklılık şart.
    """
    g = ayarlar["gemini"]
    modeller = [m for m in (g["model"], g.get("yedek_model")) if m]

    # ⚠️ ANAHTAR DÖNGÜSÜ EN DIŞTA. Önce bir anahtarla TÜM modeller
    # deneniyor; hepsi kota yüzünden düşerse ikinci anahtara geçiliyor.
    # Ters sıra (her model için iki anahtar) yanlış olurdu: kota
    # anahtara bağlı, modele değil.
    son_hata = None
    for anahtar_adi, anahtar in _anahtarlar():
        sonuc, son_hata, kota_doldu = _anahtarla_dene(
            prompt, ayarlar, modeller, anahtar, anahtar_adi)
        if sonuc is not None:
            return sonuc
        if not kota_doldu:
            # Sorun kotada değil (ağ, bozuk istek, yetki) — anahtar
            # değiştirmek bir şey çözmez, üstelik faturalı projeye
            # gereksiz istek gönderir.
            break

    raise RuntimeError(f"Gemini çağrısı başarısız: {son_hata}")


def _anahtarla_dene(prompt, ayarlar, modeller, anahtar, anahtar_adi):
    """
    Tek anahtarla bütün modelleri sırayla dener.

    Döner: `(sonuc, son_hata, kota_doldu)`. `kota_doldu` yalnızca
    HTTP 429 görüldüğünde True — çağıran taraf anahtar değiştirmeye
    buna bakarak karar veriyor.
    """
    g = ayarlar["gemini"]
    son_hata = None
    kota_doldu = False

    for model in modeller:
        if (model, anahtar_adi) in _TUKENMIS:
            log.debug("%s/%s bugünlük tükenmiş, atlanıyor", model, anahtar_adi)
            kota_doldu = True
            continue
        for deneme in range(1, g["deneme_sayisi"] + 1):
            try:
                cevap = requests.post(
                    UC_NOKTA.format(model=model),
                    headers={"x-goog-api-key": anahtar},   # URL'ye değil başlığa
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {
                            "responseMimeType": "application/json",
                            "responseSchema": CEVAP_SEMASI,
                            "temperature": g["sicaklik"],
                        },
                    },
                    timeout=g["zaman_asimi"],
                )
            except requests.RequestException as e:
                son_hata = f"{type(e).__name__}: {e}"
                log.warning("%s ağ hatası (deneme %d): %s", model, deneme, e)
                time.sleep(2 * deneme)
                continue

            if cevap.status_code == 200:
                if anahtar_adi != "birincil":
                    log.warning("Gemini %s anahtarı kullanıldı", anahtar_adi)
                    # Ücretli anahtar kullanımını kaydet — günlük rapor burayı okuyor.
                    try:
                        from datetime import date
                        yol = os.path.join("data", "yedek_anahtar_kullanimi.txt")
                        os.makedirs("data", exist_ok=True)
                        with open(yol, "a", encoding="utf-8") as f:
                            f.write(f"{date.today().isoformat()}\n")
                    except Exception:
                        pass
                return _cevabi_coz(cevap.json()), None, False

            son_hata = f"HTTP {cevap.status_code}: {cevap.text[:200]}"
            if cevap.status_code == 429:
                kota_doldu = True
                if _gunluk_kota_hatasi(cevap):
                    # Günlük kota bitmiş: bu ikiliyi bir daha deneme.
                    _TUKENMIS.add((model, anahtar_adi))
                    log.warning("%s/%s günlük kotası doldu, bu çalıştırmada "
                                "bir daha denenmeyecek", model, anahtar_adi)
                    break

            if cevap.status_code in GECICI_HATALAR:
                bekle = 2 * deneme          # 2, 4, 6 saniye
                log.warning("%s geçici hata %d, %d sn sonra tekrar",
                            model, cevap.status_code, bekle)
                time.sleep(bekle)
                continue

            # Kalıcı hata (400 bozuk istek, 403 yetki) — tekrar denemek boşuna
            log.error("%s kalıcı hata: %s", model, son_hata)
            break

        log.warning("%s ile olmadı, yedek modele geçiliyor", model)

    return None, son_hata, kota_doldu


def _cevabi_coz(veri: dict) -> dict:
    """
    Gemini cevabının içinden JSON'u çıkarır ve doğrular.

    ⚠️ HATA MESAJI TEŞHİSİ ZORLAŞTIRMASIN. Bu fonksiyon eskiden her
    beklenmedik yapıya aynı cevabı veriyordu:
        "Cevap beklenen yapıda değil (finishReason=?): 'candidates'"
    Oysa iki tamamen farklı durum bu mesaja düşüyor ve ikisinin de
    çözümü başka:
      * API hata döndürmüş (kota bitmiş, jeton geçersiz) — cevapta
        `error` var, `candidates` yok.
      * Sonuç ZATEN çözümlenmiş bir dict — yani çağıran taraf
        `_cevabi_coz`'u iki kez uygulamış.
    19 Ağu 2026'da bir ölçüm 20 istek harcayıp bu mesajla döndü ve
    kota dolduğu sanıldı; gerçek sebep ikinci maddeydi.
    """
    # API'nin kendi hata cevabı — 429 kota, 403 yetki, 400 bozuk istek
    if "error" in veri and "candidates" not in veri:
        h = veri["error"]
        kod = h.get("code", "?")
        mesaj = (h.get("message") or "")[:200]
        if kod == 429:
            raise RuntimeError(
                f"Gemini KOTASI DOLDU (HTTP 429). Ücretsiz katman model "
                f"başına günde 20 istek veriyor; kota Pasifik gece "
                f"yarısında (TR ~10:00) sıfırlanıyor. Ayrıntı: {mesaj}")
        raise RuntimeError(f"Gemini API hatası (HTTP {kod}): {mesaj}")

    # Zaten çözümlenmiş sonuç: gemini_cagir çıktısı doğrudan verilmiş
    if "candidates" not in veri and "ig_baslik" in veri:
        raise RuntimeError(
            "_cevabi_coz ZATEN çözümlenmiş bir sonuca uygulandı — "
            "gemini_cagir() çıktısı hazır dict döndürüyor, ikinci kez "
            "çözümlemeye gerek yok.")

    try:
        ham = veri["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        # Güvenlik filtresine takılmış olabilir — sebebi loga yazalım
        sebep = veri.get("candidates", [{}])[0].get("finishReason", "?")
        raise RuntimeError(f"Cevap beklenen yapıda değil (finishReason={sebep}): {e}")

    sonuc = json.loads(ham)

    # Şema zorlamasına rağmen puanın aralıkta olduğunu doğrula
    puan = sonuc.get("onem_puani")
    if not isinstance(puan, int) or not 1 <= puan <= 10:
        raise RuntimeError(f"onem_puani geçersiz: {puan!r}")

    for alan in ("ig_baslik", "ig_caption"):
        if not (sonuc.get(alan) or "").strip():
            raise RuntimeError(f"{alan} boş geldi")

    return sonuc


def tek_haber_uret(haber, ayarlar: dict) -> tuple[dict, str | None]:
    """
    Tek bir haber için metin üretir.
    Döner: (uretilen_sozluk, makale_metni_veya_None)
    """
    g = ayarlar["gemini"]

    # Önce makalenin gövdesini çekmeyi dene
    govde = makale_metni_cek(haber["link"], haber["baslik_orj"])
    tam_metin_var = bool(govde)

    if govde:
        metin = govde[: g["azami_makale_uzunlugu"]]
    else:
        # Çekemedik: RSS özetiyle idare edeceğiz ama modele bunu söylüyoruz
        metin = haber["ozet_orj"] or "(özet yok)"
        log.info("makale gövdesi çekilemedi, RSS özetiyle devam: %s",
                 haber["link"])

    prompt = prompt_kur(
        kaynak=haber["kaynak"],
        baslik=haber["baslik_orj"],
        metin=metin,
        tam_metin_var=tam_metin_var,
    )
    return gemini_cagir(prompt, ayarlar), govde


def metinleri_uret(limit: int = 10, ayarlar: dict | None = None,
                   haberler: list | None = None) -> dict:
    """
    Haberlere Instagram metni ürettirir.

    `haberler` verilirse YALNIZCA onlar işlenir. Verilmezse durum='yeni'
    havuzundan `limit` kadarı alınır.

    Liste parametresi şart: `secim.on_eleme()` havuzu tazelik ve kaynak
    ağırlığına göre süzüp aday listesi çıkarıyor. Liste geçirilemezse
    havuzdan rastgele haberler işlenir ve ön elemenin anlamı kalmaz —
    hem kota boşa gider hem seçim bozulur.

    Bir haber patlarsa diğerleri etkilenmez — o haber 'hata' durumuna geçer.

    Döner: {'basarili': int, 'hatali': int, 'haberler': [...]}
    """
    ayarlar = ayarlar or ayarlari_oku()
    db.kur()

    rapor = {"basarili": 0, "hatali": 0, "tam_metin": 0, "ozet_ile": 0,
             "haberler": []}

    with db.baglan() as con:
        bekleyen = (
            list(haberler) if haberler is not None
            else db.bekleyenler(con, durum="yeni", limit=limit)
        )

        for haber in bekleyen:
            satir = {"id": haber["id"], "kaynak": haber["kaynak"],
                     "baslik_orj": haber["baslik_orj"], "durum": "ok",
                     "hata": None, "sonuc": None, "kaynak_uzunluk": 0}

            try:
                uretilen, govde = tek_haber_uret(haber, ayarlar)
            except Exception as e:
                satir.update(durum="hata", hata=f"{type(e).__name__}: {e}")
                db.durum_guncelle(con, haber["id"], "hata", str(e)[:500])
                con.commit()
                rapor["hatali"] += 1
                rapor["haberler"].append(satir)
                log.error("haber %d başarısız: %s", haber["id"], e)
                continue

            db.metin_kaydet(con, haber["id"], uretilen, govde)
            con.commit()

            satir["sonuc"] = uretilen
            satir["kaynak_uzunluk"] = len(govde) if govde else 0
            rapor["basarili"] += 1
            rapor["tam_metin" if govde else "ozet_ile"] += 1
            rapor["haberler"].append(satir)

    return rapor


# ─────────────────────────────────────────────────────────────
#  TOPLU BAŞLIK PUANLAMA — tekil post önerisi için
# ─────────────────────────────────────────────────────────────
#
# ⚠️ NEDEN AYRI BİR YOL VAR (19 Ağu 2026):
#     Tekil post akışı eskiden şöyleydi: taze haberlere TAM metin
#     üret (başlık + caption + detay + görsel alanları), sonra
#     puanına bak, eşiği geçmiyorsa AT. Yani üretilen metnin çoğu
#     çöpe gidiyordu — haber başına ~4400 token boşa.
#
#     Yeni akış önce ucuz bir tarama yapıyor: 10 başlık TEK istekte
#     gönderilip yalnızca önem puanı isteniyor (~1500 token, yani
#     30 kat ucuz). Tam metin YALNIZCA kullanıcının Telegram'dan
#     seçtiği haber için üretiliyor.
#
#     Yan kazanç: kontrol job'ı 2.81 dk'dan ~0.55 dk'ya iniyor ve
#     bu sayede kontrol sıklığı saat başından 20 dakikaya çıkabiliyor.

TOPLU_PUAN_SEMASI = {
    "type": "object",
    "properties": {
        "puanlar": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "no": {"type": "integer"},
                    "puan": {"type": "integer"},
                },
                "required": ["no", "puan"],
            },
        },
    },
    "required": ["puanlar"],
}

TOPLU_PUAN_PROMPT = """Aşağıda numaralı haber başlıkları var. Her birine
1-10 arası bir ÖNEM PUANI ver ve yalnızca puanları döndür.

⚠️ HER HABERİ KENDİ BAŞINA DEĞERLENDİR — listedeki diğerleriyle
KIYASLAMA. Buradaki haberler rastgele bir zaman diliminden geliyor;
aralarında "en iyisi" olmak bir haberi önemli, "en kötüsü" olmak
önemsiz yapmaz. Liste zayıfsa hepsine düşük puan verme; liste güçlüyse
sıralamak için birine yapay olarak düşük puan verme.

Ölçüt mutlak: "Türkiye'deki ortalama bir takipçi bu haberi görmek
ister mi?" Aynı haber tek başına gelseydi kaç verirdin, burada da onu
ver. Aynı puanı birden çok habere vermekten çekinme.

onem_puani (1-10) — Türkiye'deki ortalama bir takipçinin bu haberi
görmek isteme derecesi. Devlet önceliği değil, TAKİPÇİ önceliği.
  * Etki: kaç kişinin hayatına dokunuyor?
  * Aciliyet: bugün bilinmesi gerekiyor mu?
  * Konuşulurluk: insanlar bunu birbirine anlatır mı, merak eder mi?
Birinde çok güçlüyse diğerleri zayıf diye düşürme.

  9-10 — günün EN ÖNEMLİ birkaç haberinden biri. Ertesi gün insanlar
         hâlâ bundan konuşuyorsa buraya girer: büyük afet · savaş ya da
         ateşkes kararı · seçim sonucu, istifa eden bakan/başkan ·
         herkesin cebini etkileyen karar (asgari ücret, büyük zam,
         faiz) · çok can kaybı olan kaza · tanınan bir ismin ölümü ya
         da ağır suça karışması · büyük operasyon, kayyum · milli
         takımın büyük turnuva sonucu · salgın ilanı.
         ⚠️ 9 VERMEKTEN ÇEKİNME — gün içinde birkaç haber 9 alabilir.
  7-8  — çoğu insanın bilmek isteyeceği haber. Siyaset ŞART DEĞİL:
         dikkat çekici bilim/uzay keşfi · herkesi ilgilendiren sağlık
         bulgusu · çok konuşulacak adli olay · tanınan ismin karıştığı
         olay · büyük kaza/yangın/salgın · büyük spor sonucu · geniş
         ilgi gören kültür-sinema gelişmesi · gündelik hayatı
         değiştiren düzenleme
         · ★ HERKESİN YARARLANABİLECEĞİ SOMUT İMKÂN: ücretsiz erişim,
           kampanya, burs, hibe, indirim, yeni ücretsiz hizmet, son
           başvuru tarihi olan fırsat
           (örnek: "Google öğrencilere Gemini Pro'yu ücretsiz açtı")
  4-6  — orta: ilgi alanına göre değişir, rutin gelişme
  1-3  — niş veya önemsiz

⚠️ AÇIKLAMA HABERİ İLE OLAY HABERİNİ AYIR — en sık yapılan hata bu.
Bir yetkilinin konuşmuş olması tek başına haber değildir:
  · "Bakan X, Y konusunu değerlendirdi"        -> 3-5
  · "X kınadı / temenni etti / mesaj yayımladı" -> 3-5
  · protokol, ziyaret, tören, anma              -> 3-4
  · "X kararı alındı / yasa çıktı / imzalandı"  -> gerçek sonuç, yüksek

⚠️ İSTİSNA — SOMUT İMKÂN DUYURUSU AÇIKLAMA DEĞİLDİR:
Bir şirket ya da kurum insanların DOĞRUDAN yararlanabileceği bir şey
duyuruyorsa (ücretsiz erişim, indirim, burs, kampanya, yeni hizmet)
bu "biri konuştu" değil, OLAYDIR — düşürme, 7-8 bandında değerlendir.
Ayrım: birincisinde okuyucunun YAPABİLECEĞİ bir şey var.

HABERLER
{liste}
"""


def basliklari_puanla(haberler: list, ayarlar: dict) -> dict[int, int]:
    """
    Birden çok haber başlığına TEK Gemini isteğiyle önem puanı verir.

    Döner: {haber_id: puan}. Puanlanamayan haber sözlükte yer almaz —
    çağıran taraf onları elemeli.
    """
    if not haberler:
        return {}

    satirlar = []
    sira_id = {}
    for i, h in enumerate(haberler, 1):
        sira_id[i] = h["id"]
        ozet = (h["ozet_orj"] or "")[:200].replace("\n", " ")
        satirlar.append(f"{i}. [{h['kaynak']}] {h['baslik_orj']}\n   {ozet}")

    prompt = TOPLU_PUAN_PROMPT.format(liste="\n".join(satirlar))

    g = ayarlar["gemini"]
    modeller = [m for m in (g["model"], g.get("yedek_model")) if m]
    for anahtar_adi, anahtar in _anahtarlar():
        for model in modeller:
            try:
                cevap = requests.post(
                    UC_NOKTA.format(model=model),
                    headers={"x-goog-api-key": anahtar},
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {
                            "responseMimeType": "application/json",
                            "responseSchema": TOPLU_PUAN_SEMASI,
                            "temperature": 0.2,
                        },
                    },
                    timeout=g["zaman_asimi"],
                )
            except requests.RequestException as e:
                log.warning("toplu puanlama ağ hatası: %s", e)
                continue

            if cevap.status_code != 200:
                log.warning("toplu puanlama HTTP %s (%s)",
                            cevap.status_code, model)
                continue

            try:
                ham = cevap.json()["candidates"][0]["content"]["parts"][0]["text"]
                veri = json.loads(ham)
            except Exception as e:
                log.warning("toplu puanlama çözümlenemedi: %s", e)
                continue

            sonuc = {}
            for kayit in veri.get("puanlar", []):
                no, puan = kayit.get("no"), kayit.get("puan")
                if no in sira_id and isinstance(puan, int) and 1 <= puan <= 10:
                    sonuc[sira_id[no]] = puan
            if anahtar_adi != "birincil":
                log.warning("Gemini %s anahtarı kullanıldı", anahtar_adi)
            log.info("toplu puanlama: %d başlığın %d tanesi puanlandı",
                     len(haberler), len(sonuc))
            return sonuc

    log.warning("toplu puanlama başarısız, hiçbir anahtar/model çalışmadı")
    return {}
