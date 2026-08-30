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
from .fetch_article import makale_metni_cek, olay_baglami_cek
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
        "baslik_alternatifleri": {
            "type": "array",
            "items": {"type": "string"},
            "description": "3 farklı stilde kurgulanmış manşet alternatifi: 1) Dinamik Sonuç, 2) Rakam & Veri Odaklı, 3) Vurucu Karar / Söylem",
        },
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
        # Haberin gerçek kategorisi
        "kategori": {"type": "string", "enum": KATEGORILER},
        # Slaytın sağ üstündeki bayrak için ISO 3166-1 alpha-2 kodu
        "ulke_kodu": {"type": "string"},
        # Bayrağın altına yazılan Türkçe ülke adı
        "ulke_adi": {"type": "string"},
        # Smart Brevity ve Etki Analizi Alanları
        "neden_onemli": {"type": "string"},
        "sirada_ne_var": {"type": "string"},
        "sana_etkisi": {"type": "string"},
        "etkilesim_sorusu": {"type": "string"},
        # Slayt içi mini veri rozeti (infografik) alanları
        "veri_karti_etiket": {"type": "string"},
        "veri_karti_eski": {"type": "string"},
        "veri_karti_yeni": {"type": "string"},
        "veri_karti_yon": {"type": "string"},
        # İkili aktör / Split-Screen için 2 kişinin adı (varsa)
        "gorsel_ikili": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "baslik_alternatifleri", "ig_baslik", "ig_caption", "ig_hashtag", "onem_puani",
        "slayt_ozet", "detay_metni", "vurgu_sayi", "vurgu_etiket",
        "alinti", "alinti_sahibi", "gorsel_konu", "gorsel_temsili",
        "kategori", "ulke_kodu", "ulke_adi", "neden_onemli",
        "sirada_ne_var", "sana_etkisi", "etkilesim_sorusu",
        "veri_karti_etiket", "veri_karti_eski", "veri_karti_yeni",
        "veri_karti_yon", "gorsel_ikili",
    ],
}


PROMPT = """Sen Türkiye'nin en kaliteli sosyal medya haber yayını Daily Brief'in baş editörüsün.
Aşağıdaki haberi Instagram, Threads ve sosyal medya için en yüksek kalitede, taranabilir ve etkileşimli bir yayına dönüştür.

EN ÖNEMLİ KURAL — BUNU ASLA ÇİĞNEME (SIFIR HALÜSİNASYON):
Sadece aşağıdaki HABER METNİNDE yazan bilgileri kullan. Metinde geçmeyen hiçbir iddiayı, sayıyı, ismi, tepkiyi veya sonucu yazma. Emin değilsen o cümleyi hiç kurma. Eksik yazmak, uydurmaktan iyidir.

SAYILAR — KAYNAKTAKİ GİBİ YAZ, YUVARLAMA:
Kaynakta "2 milyar 841 milyon lira" yazıyorsa aynen öyle yaz. "2,8 milyar" diye yuvarlama. Tarih, oran, kişi sayısı ve hedef fiyatlar için de aynı kural geçerlidir.

HUKUKİ DİKKAT:
Suçlama, soruşturma veya dava içeren haberlerde "iddia edildi", "öne sürüldü", "hakkında soruşturma başlatıldı" gibi ifadeler kullan. Kesin mahkeme kararı olmadan kimseyi suçlu ilan etme.

DEĞİŞEN SAYILAR — CAN KAYBINDA DİNAMİK DİL:
Deprem, kaza, saldırı gibi haberlerde can kaybı güncellenir. "47 kişi öldü" yerine "en az 47 kişi hayatını kaybetti" veya "Ölü sayısı 47'ye yükseldi" yaz.

★ YÜKSEK ETKİLİ KANCA (HOOK) VE EDİTORYAL BAŞLIK İLKELERİ ★
Haber için arka planda 3 farklı stilde başlık üret ve `baslik_alternatifleri` dizisine ekle:
  1. [Dinamik Sonuç Başlığı]: Olayın sonucunu, anlaşma bedelini veya resmi kararı doğrudan ilk kelimelerde ve aktif bir fiille veren başlık ("Fenerbahçe Amrabat transferini bitirdi: 15M€ ödenecek", "Fed faizi 25 baz puan indirdi").
  2. [Rakam & Veri Odaklı Başlık]: En çarpıcı oranı, sayıyı veya hedefi öne çıkaran başlık ("Yıllık enflasyon 8 ayın dibinde: %42'ye geriledi", "THYAO için hedef fiyat 450 TL'ye yükseltildi").
  3. [Vurucu Karar / Söylem Başlığı]: Liderin veya kurumun can alıcı kararını/sözünü aktaran başlık ("Bakan Bolat: İhracatta tüm zamanların aylık rekoru kırıldı").

`ig_baslik` ALANINA BU 3 ALTERNATİF ARASINDAN EN GÜÇLÜ OLANINI SEÇ:
  * Başlık akışta kaydırmayı durduran profesyonel bir KANCA olmalı, ancak ASLA gerçeği manipüle etmemeli.
  * Takipçi başlığı okuduğunda NE OLDUĞUNU ilk 0.5 saniyede %100 öğrenmiş olmalıdır.
  * YASAK PASİF KALIPLAR: "...'a ilişkin açıklama", "...hakkında konuştu", "...değerlendirdi", "...anlattı", "...mesaj verdi", "...gündeme getirdi", "...dikkat çekti". Bunları KESİNLİKLE KULLANMA.
  * YASAK TIKLAMA TUZAKLARI: "şok", "bomba", "herkesi şaşırttı", "işte o an" gibi ucuz clickbait ifadeleri KULLANMA.
  * BÜYÜK HARF KURALI: Cümle düzeni kullan (yalnızca ilk kelime ve özel adlar büyük). Sonuna nokta koyma.

★ KESİN BİÇİMLENDİRME KURALI: SIFIR MARKDOWN (DÜZ METİN) ★
Sosyal medya açıklamaları ve slaytlarda ASLA markdown yıldızları (**kalın**, *italik*, __vb__) KULLANMA. Tüm metinleri doğal, akıcı ve temiz düz metin (plain text) olarak yaz.

★ KATEGORİYE ÖZEL EDİTORYAL TON (TONE OF VOICE) ★
- ekonomi: Rakamlar, rasyolar, BİST 100 hisse etkileri, kâr marjı, faiz/dolar dengesi ve piyasa analizi odaklı keskin Bloomberg/FT standardı finans dili.
- teknoloji / bilim: Geleceğe yön veren inovasyonu ve keşfi yalın, vizyoner ve anlaşılır kılan dinamik dil.
- turkiye / dunya: Smart Brevity ilkelerine dayalı, tarafsız, analitik, jeopolitik derinliği olan net dil.

★ EDİTORYAL ALANLAR VE AÇIKLAMALAR ★
- slayt_ozet: TEK cümle, en fazla 18 kelime. Başlıkta OLMAYAN ikinci en somut bilgiyi ver (oran, tarih, kim söyledi). Başlığı tekrarlama.
- detay_metni: 120-220 kelime, 2 PARAGRAF.
  * 1. Paragraf (Spot): Olayın nerede/nasıl gerçekleştiği ve doğrudan ana sonucu (20-25 kelime).
  * 2. Paragraf (Gelişme & Arka Plan): Detaylar, etkilenen sektörler, açıklamalar. 1. paragraftaki bilgileri ASLA tekrarlama.
  * Doğrudan söylemleri çift tırnak "..." içine al. Asla markdown yıldız (**) kullanma.
- sana_etkisi: 1-2 CÜMLE (en fazla 25 kelime).
  * Haberin okuyucunun cebine, kredisini, mevduatını, portföyüne, faturasına veya günlük yaşamına doğrudan yansıması.
  * Yalın ve vurucu Türkçe cümleler kur. Asla markdown yıldız (**) kullanma. (Örn: "Mevduat getirilerinde yıllık %47 bandı korunurken ihtiyaç kredisi faizlerinde kısa vadede indirim beklenmiyor.")
- etkilesim_sorusu: TEK CÜMLE. Okuyucunun fikrini soran, kutuplaştırmayan ama yorum yapma isteği uyandıran zekice soru.
  (Örn: "Sizce TCMB'nin ilk faiz indirimi hangi ayda gelmeli?", "Bu hedef fiyat sonrası hisseyi takibe alır mısınız?")
- neden_onemli: 1-2 CÜMLE. Haberin makro, stratejik veya jeopolitik etki boyutu. Genel geçer soyut laflar yerine somut etkiyi net bir dille yaz. Asla markdown yıldız (**) kullanma.
- sirada_ne_var: TEK CÜMLE. Haberde açıkça geçen sonraki resmi adım, duruşma veya yürürlük tarihi. Bilgi yoksa boş string ("") bırak.
- veri_karti_*: Haberde herhangi bir karşılaştırma veya oran (eski vs yeni, hedef fiyat, kâr artışı, enflasyon vb.) varsa ZORUNLU olarak doldur:
    veri_karti_etiket : "Hedef Fiyat", "Politika Faizi", "Yıllık TÜFE", "Net Kâr Artışı"
    veri_karti_eski   : "380 ₺" veya "%50" (varsa, yoksa "")
    veri_karti_yeni   : "450 ₺" veya "%45"
    veri_karti_yon    : "artis" | "azalis" | "hedef" | "notr" | ""
- vurgu_sayi / vurgu_etiket: Başlıkta GEÇMEYEN ikinci en çarpıcı sayı ve etiketi (örn: "2.352 yıl" / "istenen ceza"). Yoksa boş bırak.
- alinti / alinti_sahibi: Haberde geçen doğrudan söz (en fazla 18 kelime, tırnaksız) ve sahibi. Kaynakta kelimesi kelimesine geçmeli.
- ig_caption: Haberin tüm detaylarını, arka planını ve nedenlerini anlatan 3-5 cümlelik ferah, akıcı ve bilgilendirici bülten açıklaması. Paragrafları ferah tut, okuyucunun konuyu tam anlamasını sağla. Asla markdown yıldız (**) kullanma. Kaynak adı yazma.
- ig_hashtag: 5-8 adet konuyla ilgili Türkçe etiket, '#' işareti OLMADAN.
- gorsel_konu: Sadece tanınmış gerçek bir insanın adı ve soyadı (örn: "Hakan Fidan"). Yoksa boş bırak.
- gorsel_ikili: Zirve veya ikili diplomatik görüşme ise iki aktörün adı: ["Recep Tayyip Erdoğan", "İlham Aliyev"]. Yoksa boş liste [].
- gorsel_temsili: Pexels araması için 3-6 kelimelik somut İngilizce terim (örn: "stock market trading chart screen", "commercial passenger jet airplane"). Soyut ve yazılı tabela içeren terim isteme.

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

    # Markdown formatlama işaretlerini (**bold**, __italik__ vb.) temizle
    from src import filtre
    for k, v in list(sonuc.items()):
        if isinstance(v, str):
            sonuc[k] = filtre.markdown_temizle(v)
        elif isinstance(v, list):
            sonuc[k] = [filtre.markdown_temizle(x) if isinstance(x, str) else x for x in v]

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
    if not govde or len(govde) < 150:
        ek_baglam = olay_baglami_cek(haber["baslik_orj"])
        if ek_baglam:
            govde = f"{govde or ''}\n\n[GÜNCEL BASIN DETAYLARI & OLAY BAĞLAMI]:\n{ek_baglam}"

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
