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

# Gemini'den JSON istiyoruz. Şema vermek, "bazen düz metin döndürme"
# sorununu tamamen ortadan kaldırıyor.
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
        # Slaytın sağ üstündeki bayrak için ISO 3166-1 alpha-2 kodu
        "ulke_kodu": {"type": "string"},
        # Bayrağın altına yazılan Türkçe ülke adı
        "ulke_adi": {"type": "string"},
    },
    "required": [
        "ig_baslik", "ig_caption", "ig_hashtag", "onem_puani",
        "slayt_ozet", "detay_metni", "vurgu_sayi", "vurgu_etiket",
        "alinti", "alinti_sahibi", "gorsel_konu", "gorsel_temsili",
        "ulke_kodu", "ulke_adi",
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
- ig_baslik: en fazla 12 kelime.

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
- ig_caption: 2-3 cümle, haberin özü. Kaynak adını yazma.
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

- gorsel_konu: SADECE GERÇEK BİR İNSANIN ADI VE SOYADI. Başka hiçbir şey.
  (örn: "Hakan Fidan", "Ekrem İmamoğlu")

  KURUM, ÖRGÜT, ŞEHİR, KISALTMA YAZMA — burası en kritik kural.
  Ölçüldü (15 Ağu 2026): kurum adları fotoğraf arşivinde yanlış eşleşiyor
  ve haberle ilgisiz görsel geliyor. Gerçek örnekler:
      "İSKİ"    -> Macar bir sanatçının portresi ("Iski Kocsis Tibor")
      "Taliban" -> 2021 askeri harekat haritası
      "Ankara Büyükşehir Belediyesi" -> Ankara Kalesi manzarası
  Bunlar bir haber hesabında yayınlanamaz. Kurumu tarif etmek istiyorsan
  gorsel_temsili alanını kullan; orası bu iş için zaten var ve iyi çalışıyor.

  Kişi Wikipedia'da sayfası olacak kadar tanınmış değilse BOŞ BIRAK.
  Sıradan vatandaş veya yerel yetkili adı yazma — arşivde fotoğrafı yok.
  Haberin merkezinde tanınmış bir insan yoksa BOŞ BIRAKMAK DOĞRU CEVAPTIR.

- gorsel_temsili: Konuyu temsil eden İNGİLİZCE stok fotoğraf arama terimi.
  Ölçüldü (15 Ağu 2026), şu kurallara uy:
    * YAKIN PLAN NESNE iste, geniş mekân isteme. Geniş mekân fotoğrafları
      hep bir ülkeye ait oluyor ve tabelaları yabancı dilde çıkıyor —
      Türkiye haberinde İspanyolca hastane tabelası özensiz görünüyor.
        KÖTÜ: "hospital corridor"   ->  İYİ: "stethoscope close up"
        KÖTÜ: "city bus stop"       ->  İYİ: "turkish lira coins close up"
    * 3-6 kelime yeter. Sonuna "close up" eklemek işe yarıyor.
    * İnsan yüzü içeren sahne isteme — tanımadığımız biri haberle
      ilişkilendirilmiş görünür.
    * Doğa ve doku sahneleri de nötr olduğu için iyi çalışıyor
      (kuraklık haberinde "dry cracked earth" gibi).

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

onem_puani (1-10) — Türkiye'deki ortalama bir takipçi için önem:
  * Ulusal etki: kaç kişiyi doğrudan etkiliyor?
  * Aciliyet: bugün bilinmesi gerekiyor mu?
  * İlgi çekicilik: insanlar bunu konuşur mu?
  9-10 = ülke gündemini belirleyen olay
  7-8  = önemli, çoğu insan bilmek ister
  4-6  = orta, ilgi alanına göre değişir
  1-3  = niş veya önemsiz

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
    anahtar = _anahtar_al()
    modeller = [g["model"], g.get("yedek_model")]
    son_hata = None

    for model in [m for m in modeller if m]:
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
                return _cevabi_coz(cevap.json())

            son_hata = f"HTTP {cevap.status_code}: {cevap.text[:200]}"

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

    raise RuntimeError(f"Gemini çağrısı başarısız: {son_hata}")


def _cevabi_coz(veri: dict) -> dict:
    """Gemini cevabının içinden JSON'u çıkarır ve doğrular."""
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
