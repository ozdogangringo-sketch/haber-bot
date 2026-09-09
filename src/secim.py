"""
secim.py — Turda hangi haberlerin yayınlanacağına karar verir.

ÇÖZDÜĞÜ SORUN — tavuk-yumurta:
    Seçim skoru `onem_puani`ye dayanıyor, ama o puanı Gemini üretiyor.
    Yani "hangisi önemli" sorusunu cevaplamak için önce hepsine metin
    ürettirmek gerekiyor. Havuzda 200+ haber var; hepsine metin üretmek
    hem kotayı hem 200 makale indirmeyi göze almak demek — turun süresi
    dakikalardan saate çıkar.

    Çözüm iki aşamalı:
      1. ÖN ELEME (bedava, LLM yok): tazelik + kaynak ağırlığı + kategori
         ile havuzu ~2 kat adaya indir.
      2. ASIL SEÇİM: yalnızca o adaylara metin üretilir, sonra gerçek
         skorla en iyi N tanesi alınır.

    Ön eleme neden güvenli: elediğimiz haberler ya bayat ya düşük ağırlıklı
    kaynaktan. İkisi de zaten asıl skorda dibe düşecek şeyler.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# Aday havuzu, yayınlanacak sayının kaç katı olsun.
# 2.5 seçildi: elenen haber yerine yedek kalsın ama boşuna metin
# üretilmesin. 10 slayt için ~25 adaya metin üretiliyor.
ADAY_KATSAYISI = 2.5


def _yas_saat(haber) -> float:
    """Haberin yayınlanmasından bu yana geçen saat."""
    ham = haber["yayin_tarihi"]
    if not ham:
        return 999.0
    try:
        t = datetime.fromisoformat(ham)
    except ValueError:
        return 999.0
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 3600


# Başlıkta "bir şey OLDU" sinyali — ön elemede puanı yükseltir.
OLAY_SINYALLERI = [
    "tutukland", "gözaltına", "öldü", "hayatını kaybet", "yaraland",
    "keşfet", "rekor", "ilk kez", "kazandı", "şampiyon", "patlad",
    "yangın", "çöktü", "düştü", "kaza", "istifa", "görevden al", "zam",
    "operasyon", "baskın", "saldır", "yürürlüğe", "erteledi", "geriledi",
    "yükseldi",
    # ⚠️ FAYDA/FIRSAT SİNYALLERİ (20 Ağu 2026).
    #
    # Kullanıcı "Google öğrencilere Gemini üyeliği verdi" gibi haberleri
    # istedi: insanların tanıdıklarına GÖNDERDİĞİ, işe yarayan haberler.
    # Ölçüldü — o başlık bu listeden 0 puan alıyordu (rakam yok, olay
    # fiili yok), oysa "3 araç çarpıştı, 2 yaralı" 20 puan alıyordu.
    # Bu yüzden fırsat haberleri ön elemede metin bile üretilmeden
    # eleniyordu.
    "ücretsiz", "bedava", "indirim", "kampanya", "burs", "hibe",
    "destek paketi", "başvuru", "erişime açtı", "erişime açıldı",
    "hediye", "fırsat", "son gün", "uzatıldı", "yürürlükte",
]

# Başlıkta "biri bir şey DEDİ" sinyali — puanı düşürür.
ACIKLAMA_SINYALLERI = [
    "değerlendir", "kınad", "temenni", "vurgulad", "belirtti", "mesaj",
    "tebrik", "anma", "ziyaret", "katıldı",
]


def _icerik_puani(baslik: str) -> float:
    """
    Başlığa bakarak haberin "olay mı, açıklama mı" olduğunu tahmin eder.

    LLM YOK, bedava. Ön eleme aşamasında elimizde yalnızca başlık var;
    önem puanı henüz üretilmedi (tavuk-yumurta sorunu, bkz. modül
    açıklaması). Bu kaba sinyal o boşluğu dolduruyor.

    Ölçüldü (19 Ağu 2026): "Dışişleri Bakanlığından Dünya İnsani Günü
    mesajı" listeden geriledi, trafik kazaları ve operasyon haberleri
    öne çıktı.
    """
    b = (baslik or "").lower()
    puan = 0.0
    if re.search(r"\d", baslik or ""):
        puan += 8                                  # somut rakam taşıyor
    if any(k in b for k in OLAY_SINYALLERI):
        puan += 12
    if any(k in b for k in ACIKLAMA_SINYALLERI):
        puan -= 10
    return puan


def _kategori_katsayilari(ayarlar: dict) -> dict:
    return (ayarlar.get("secim", {}) or {}).get("kategori_katsayilari", {}) or {}


def on_skor(haber) -> float:
    """
    "Bu haber metin üretmeye değer mi?" sorusunun TEK cevabı.

        ağırlık × 10  −  yaş(saat)  +  içerik sinyali

    ⚠️ NEDEN ORTAK FONKSİYON (4 Eyl 2026): bu formül `on_eleme`de vardı
    ama günlük asıl akış olan `son_dakika.taze_adaylar` onu HİÇ
    kullanmıyordu — orada sıralama düpedüz `ORDER BY agirlik DESC,
    yayin_tarihi DESC` idi. ÖLÇÜLDÜ: tazelik penceresine giren 60
    haberin **54'ünün ağırlığı 10**, yani ağırlık neredeyse hep
    berabere bitiyor ve sıralamayı fiilen SAF TAZELİK belirliyordu.

    Sonuç somut: *"Yaz bitti, işbaşı sendromunu nasıl atlatabilirsiniz"*
    (içerik puanı 0) metin alırken *"Girne'deki gemide can kaybı 12'ye
    yükseldi"* (içerik puanı 20) **45. sırada** bekliyordu. `on_eleme`ye
    yıllar içinde eklenen bütün içerik sinyali mekanizması, günde ~20
    kez çalışan yolda hiç devrede değildi; `on_eleme` ise cron'u kapalı
    `hazirla.py`den günde ~1 kez çağrılıyor.

    ⚠️ Bu, projenin en sık tekrarlayan hatası: **kural doğru ama bir
    kod yolunda uygulanmamış** (1j · 1p · 1f · tazelik sabiti). Formül
    artık tek yerde; yeni bir akış eklerken burayı çağır.
    """
    return ((haber["agirlik"] or 1) * 10
            - _yas_saat(haber)
            + _icerik_puani(haber["baslik_orj"]))


def on_eleme(con, ayarlar: dict, kac: int | None = None) -> list:
    """
    Metin üretilecek adayları seçer. LLM ÇAĞIRMAZ, bedavadır.

    ⚠️ İKİ KATMANLI — HABERLER ÖNCE KENDİ KATEGORİSİNDE YARIŞIR.

    Eski yöntem tek havuzda düz sıralama yapıyordu ve ölçüldüğünde
    (19 Ağu 2026, 1497 haberlik havuz) 25 adayın tamamı 2 kategoriden,
    3 kaynaktan geliyordu: turkiye 17, ekonomi 8. Sebep aritmetik —
    ön skor `ağırlık × 10` ile başlıyor, TRT/AA gibi ağırlığı 10 olan
    ajanslar saatte onlarca haber basıyor ve liste onların taze
    haberleriyle doluyor. 25 saatlik bir spor transferi (ağırlık 7)
    skoru 44 alırken 2 saatlik bir TRT haberi 98 alıyordu; bu farkı
    hiçbir içerik sinyali kapatamıyordu. Ağırlık çarpanını 10'dan 3'e
    düşürmek bile işe yaramadı — asıl baskın etken haber AKIŞININ
    yoğunluğuydu, ağırlığın kendisi değil.

    Şimdi:
      KATMAN 1 — her haber yalnızca KENDİ kategorisindeki haberlerle
                 yarışır (kaynak ağırlığı + tazelik + içerik sinyali).
      KATMAN 2 — kategori içi sırası, kategorinin katsayısıyla
                 ağırlıklandırılır. Sıra cezası ÜSTEL ve kategori
                 büyüklüğünden BAĞIMSIZ.

    ⚠️ Sıra cezası neden kategori büyüklüğünden bağımsız olmalı: ilk
    denemede sıra, kategorideki haber sayısına bölünerek normalize
    edildi ve sonuç yine %100 turkiye çıktı — 592 haberlik kategoride
    25. sıra hâlâ 0.96 alıyor, 35 haberlik sporda 2. sıra 0.97'ye
    düşüyordu. Büyük kategori otomatik olarak avantajlı hale geliyordu.

    Ölçüldü: kategori çeşidi 2 -> 5, kaynak çeşidi 3 -> 9.
    """
    g = ayarlar["gorsel"]
    sinir_saat = ayarlar["genel"]["yayin_yasi_siniri_saat"]
    kac = kac or int(g["slayt_sayisi"] * ADAY_KATSAYISI)
    s = ayarlar.get("secim", {}) or {}
    katsayilar = _kategori_katsayilari(ayarlar)
    azalma = s.get("kategori_sira_azalmasi", 0.88)
    varsayilan_katsayi = s.get("kategori_varsayilan_katsayi", 0.6)

    havuz = list(con.execute(
        "SELECT * FROM haberler WHERE durum = 'yeni'"
        " AND COALESCE(daha_once_yayinlandi, 0) = 0"
    ))

    # --- KATMAN 1: kategori içi ham skor ---
    kategoriler: dict[str, list] = {}
    for haber in havuz:
        yas = _yas_saat(haber)
        if yas > sinir_saat:
            continue
        ham = on_skor(haber)
        kategoriler.setdefault(haber["kategori"] or "diger", []).append((ham, haber))

    # --- KATMAN 2: kategori katsayısı ile ağırlıklandır ---
    puanli = []
    for kat, liste in kategoriler.items():
        liste.sort(key=lambda x: x[0], reverse=True)
        katsayi = katsayilar.get(kat, varsayilan_katsayi)
        for sira, (_ham, haber) in enumerate(liste):
            puanli.append((katsayi * (azalma ** sira), haber))

    puanli.sort(key=lambda x: x[0], reverse=True)
    secilen = [haber for _, haber in puanli[:kac]]

    log.info("ön eleme: %d havuzdan %d aday (%d kategori, %d kaynak)",
             len(havuz), len(secilen),
             len({h["kategori"] for h in secilen}),
             len({h["kaynak"] for h in secilen}))
    return secilen


# Bir kez atlanan haberin skorundan düşülen puan. 15 = bir buçuk önem
# puanı; haberi eler değil, geriye atar.
ERTELEME_CEZASI = 15


def skor(haber, ayarlar: dict) -> float:
    """
    Asıl seçim skoru. Metin üretildikten SONRA çalışır.

    Formül CLAUDE.md'de kararlaştırıldı:
        onem_puani * 10 + agirlik - yaş_saat
        - 15  eğer kategori == 'dunya' ve onem_puani < 8
    """
    onem = haber["onem_puani"] or 0
    deger = onem * 10 + (haber["agirlik"] or 1) - _yas_saat(haber)
    if haber["kategori"] == "dunya" and onem < 8:
        deger -= 15

    # ⚠️ ATLANAN HABER BİR SONRAKİ TURDA ÖNE ÇIKMASIN.
    #
    # 20 Ağu 2026: kullanıcı bir turu "bu haberleri istemiyorum" diye
    # atladı, haberler havuza döndü ve skor değişmediği için AYNI
    # haberler yeni turda yine ilk sıralardaydı. "Atla" düğmesi
    # pratikte hiçbir şey değiştirmiyordu.
    #
    # Ceza kalıcı eleme DEĞİL: haber havuzda kalıyor, sadece bir tur
    # geri düşüyor. Önem puanı yüksek bir haber iki atlamadan sonra
    # bile yarışabiliyor (10 puanlık haber 100 - 30 = 70, ortalama
    # 7 puanlık haberin 70'iyle başa baş).
    deger -= (haber["ertelenme_sayisi"] or 0) * ERTELEME_CEZASI
    return deger


# Konu karşılaştırmasında sayılmayacak kelimeler. Bunlar her başlıkta
# geçiyor ve iki haberi yapay olarak "benzer" gösteriyor.
ETKISIZ_KELIMELER = {
    "için", "ile", "olarak", "sonra", "önce", "üzere", "kadar", "daha",
    "göre", "karşı", "yeni", "büyük", "sonrası", "ilgili", "hakkında",
    "arasında", "üzerine", "birlikte", "dedi", "açıkladı", "oldu",
    "edildi", "verdi", "aldı", "yaptı", "bulundu", "geldi", "başladı",
    # ⚠️ HABER KALIPLARI — büyük harfle yazıldıkları için özel isim
    # sanılıyorlardı. Ölçüldü (18 Ağu 2026): iki tamamen farklı mevzuat
    # haberi "Resmi Gazete'de yayımlandı" üzerinden aynı olay sayıldı.
    # Bunlar olayı ayırt etmiyor, yalnızca haberin biçimini anlatıyor.
    "resmi", "gazete", "yayımlandı", "yayimlandi", "açıklama",
    "bakanlığı", "başkanlığı", "cumhurbaşkanı", "bakan", "başkan",
    # Genel duyuru ve lansman kalıpları (farklı ürünleri aynı haber sanmamak için)
    "satışa", "satışta", "satışlar", "satış", "çıktı", "işte", "belli",
    "özellikleri", "özellikler", "tarihi", "fiyatı", "duyuruldu", "rekor", "kırdı",
}


def _ozel_isimler(baslik: str) -> set[str]:
    """
    Başlıktaki özel isimler (kişi, yer, kurum) — küçük harfe indirilmiş.

    ⚠️ NEDEN GEREKTİ: geçmiş-tekrar denetimi yalnızca ortak kelime
    sayarken YANLIŞ POZİTİF veriyordu. Ölçüldü (18 Ağu 2026):
    "Yeni çözüm sürecinin ... çerçeve yasa Resmi Gazete'de yayımlandı"
    ile bambaşka bir yasa haberi `resmi + gazete + yayımlandı` üzerinden
    eşleşiyordu — o kalıp neredeyse her mevzuat haberinde geçiyor.

    Aynı OLAY olduğunu gösteren şey ortak kalıp değil, ortak ÖZEL
    İSİMDİR: "Bozbey", "Mustafa". Bu yüzden geçmiş denetiminde
    eşleşmenin en az bir özel isim taşıması aranıyor.

    İlk kelime atlanıyor: başlık her zaman büyük harfle başlıyor, o
    yüzden büyük harf orada özel isim işareti değil.
    """
    isimler = set()
    for ham in (baslik or "").replace("'", " ").split()[1:]:
        temiz = "".join(k for k in ham if k.isalnum())
        # Karşılaştırma _anahtar_kelimeler ile AYNI biçimde yapılmalı:
        # o da düz .lower() kullanıyor ve Türkçe karakterleri koruyor.
        # İki taraf farklı sadeleştirme uygularsa ETKISIZ_KELIMELER
        # listesi bir tarafta hiç tutmaz ve eleme sessizce çalışmaz.
        kucuk = temiz.lower()
        if len(temiz) >= 4 and temiz[:1].isupper() \
                and kucuk not in ETKISIZ_KELIMELER:
            isimler.add(kucuk)
    return isimler


def konu_imzasi(baslik: str) -> tuple[set[str], set[str]]:
    """
    Tekrar denetimi için (anahtar kelimeler, özel isimler).

    ⚠️ `_ozel_isimler`'den farkı: BAŞLIĞIN İLK KELİMESİNİ DE sayıyor.
    O fonksiyon ilk kelimeyi bilerek atlıyor (her başlık büyük harfle
    başlar, orada büyük harf özel isim işareti değil) — ama haber
    başlıkları çok sık yer/kişi adıyla başlıyor: "Kolombiya'da 7,4
    büyüklüğündeki depremde…", "Gazzeli bebekler…". İlk kelime
    atlanınca iki kopya haberin ortak özel ismi kalmıyor ve tekrar
    yakalanamıyor.

    Kısa listelerde (öneri, arama sonucu) kullanılıyor; geçmişe karşı
    denetimde `_ozel_isimler` tercih ediliyor çünkü orada yanlış
    pozitif maliyeti daha yüksek.
    """
    kelimeler = _anahtar_kelimeler(baslik)
    isimler = set()
    for ham in (baslik or "").replace("'", " ").split():
        temiz = "".join(k for k in ham if k.isalnum())
        if len(temiz) >= 4 and temiz[:1].isupper():
            kucuk = temiz.lower()
            if kucuk not in ETKISIZ_KELIMELER:
                isimler.add(kucuk)
    return kelimeler, isimler


def _anahtar_kelimeler(baslik: str) -> set[str]:
    """
    Başlığın konusunu temsil eden kelimeler.

    Türkçe ek almış hâlleri ("İsrail'in", "Gazze'de") aynı köke indirmek
    için kesme işaretinden sonrası atılıyor; yoksa aynı olayın haberleri
    farklı kelime gibi görünüyor.
    """
    kelimeler = set()
    for ham in (baslik or "").lower().replace("'", " ").split():
        temiz = "".join(k for k in ham if k.isalnum())
        if len(temiz) >= 4 and temiz not in ETKISIZ_KELIMELER:
            kelimeler.add(temiz)
    return kelimeler


def yayinlanmis_konular(con, ayarlar: dict) -> list[tuple[set[str], set[str]]]:
    """
    Son günlerde YAYINLANMIŞ, ONAYDA BEKLEYEN veya İŞLENMİŞ haberlerin anahtar kelime kümeleri.

    ⚠️ NEDEN GEREKTİ: Kullanıcı gündüz tekil post yayınladığında veya bir haber
    onay beklerken, aynı olayın başka bir kaynaktan gelen kopyası gece otomatik
    yayına ya da yeni bir tekil posta ASLA girememelidir.
    """
    gun = (ayarlar.get("secim", {}) or {}).get("gecmis_konu_gun", 2)
    sutunlar = {col[1] for col in con.execute("PRAGMA table_info(haberler)").fetchall()}
    has_mid = "telegram_message_id" in sutunlar
    where_durum = ("(durum = 'yayinlandi' OR telegram_message_id IS NOT NULL OR durum IN ('onay_bekliyor', 'baslik_onayi', 'ertelendi'))"
                   if has_mid else
                   "(durum IN ('yayinlandi', 'onay_bekliyor', 'baslik_onayi', 'ertelendi'))")

    satirlar = con.execute(
        f"""SELECT ig_baslik, baslik_orj FROM haberler
           WHERE {where_durum}
             AND (
               (gonderim_zamani IS NOT NULL AND gonderim_zamani > datetime('now', ?))
               OR (yayin_tarihi IS NOT NULL AND yayin_tarihi > datetime('now', ?))
               OR (cekilme_zamani IS NOT NULL AND cekilme_zamani > datetime('now', ?))
             )""",
        (f"-{gun} day", f"-{gun} day", f"-{gun} day"),
    ).fetchall()
    # ⚠️ `konu_imzasi` — `_ozel_isimler` DEĞİL. İkincisi başlığın ilk
    # kelimesini atlıyor ve haber başlıkları çok sık yer adıyla
    # başlıyor ("Kolombiya'da...", "Ankara'da..."); ilk kelime
    # atlanınca ortak özel isim kalmıyor ve tekrar yakalanamıyor.
    basliklar = [b for b in ((r[0] or r[1]) for r in satirlar) if b]

    # ⚠️ VERİTABANI TEK KAYNAK DEĞİL — Instagram'a da soruyoruz.
    basliklar += _instagram_gecmisi(ayarlar)

    return [konu_imzasi(b) for b in basliklar if b]


# Aynı süreçte tekrar tekrar API'ye gitmemek için. Tur seçimi ve
# çeşitlendirme aynı çalıştırmada birden fazla kez soruyor.
_IG_GECMIS_ONBELLEK: list[str] | None = None


def _instagram_gecmisi(ayarlar: dict) -> list[str]:
    """Instagram'da gerçekten yayınlanmış manşetler (bir kez okunur)."""
    global _IG_GECMIS_ONBELLEK
    if _IG_GECMIS_ONBELLEK is not None:
        return _IG_GECMIS_ONBELLEK
    try:
        from src import instagram
        _IG_GECMIS_ONBELLEK = instagram.son_yayinlanan_basliklar(ayarlar)
        log.info("mükerrer denetimi: Instagram'dan %s manşet alındı",
                 len(_IG_GECMIS_ONBELLEK))
    except Exception as e:
        # Instagram'a ulaşılamıyorsa denetim veritabanıyla devam etsin;
        # mükerrer riski artar ama tur DURMAMALI.
        log.warning("Instagram geçmişi alınamadı: %s", e)
        _IG_GECMIS_ONBELLEK = []
    return _IG_GECMIS_ONBELLEK


def cesitlendir(adaylar: list, adet: int, ayarlar: dict,
                gecmis_konular: list | None = None) -> list:
    """
    Skora göre sıralı adaylardan turu kurar; AYNI OLAYI bir kez alır.

    ⚠️ KATEGORİ VE KAYNAK KOTASI YOK (18 Ağu 2026'da kaldırıldı).
    Önce "kategori başına 3, kaynak başına 4" kuralı vardı. Amaç
    tekdüzeliği kırmaktı ama yan etkisi şuydu: gündem gerçekten tek
    konuya kilitlendiğinde (büyük bir deprem, seçim gecesi) kota o
    haberleri dışarıda bırakıp yerlerine daha önemsizlerini alıyordu.
    Gündemi biz değil olaylar belirlemeli.

    KALAN TEK KURAL — AYNI OLAY TEKRARI: başlıkları birbirine çok
    benzeyen haberlerden yalnızca en yüksek puanlısı alınıyor. Bu bir
    "çeşitlilik" tercihi değil, MÜKERRER İÇERİK engeli: aynı olayı iki
    kaynaktan üst üste koymak takipçiye yeni bir şey söylemiyor.
    """
    s = ayarlar.get("secim", {}) or {}
    ortak_esik = s.get("konu_ortak_kelime_esigi", 2)

    # ⚠️ GEÇMİŞ İÇİN EŞİK DAHA YÜKSEK.
    # Tur içinde iki haber benzer başlıklıysa aynı olaydır. Ama günler
    # arasında gerçek bir gelişme olabilir: "İsrail Gazze" her gün
    # haber üretiyor ve dünkü habere benziyor diye bugünkü gelişmeyi
    # atmak yanlış olur. Bu yüzden geçmişte daha çok kelime tutuşması
    # aranıyor — engellenen şey tekrar, devam eden olay değil.
    gecmis_esik = s.get("gecmis_ortak_kelime_esigi", ortak_esik + 1)

    # ⚠️ BÜYÜK OLAY GÜNÜN ÖZETİNDE DE YER ALIR.
    # Gündüz son dakika olarak paylaşılan bir haber, gerçekten büyük
    # bir olaysa akşam özetinde tekrar görünmeli — özet o günü anlatıyor
    # ve günün en önemli olayını atlarsa özet olmaktan çıkar. Tekrar
    # engeli sıradan haberler için var: aynı istifayı üç kez göstermek
    # takipçiye yeni bir şey söylemiyor, ama bir depremi hem anında hem
    # akşam özetinde vermek doğru davranış.
    muafiyet = s.get("gecmis_muafiyet_puani", 9)

    secilen = []
    konular = []                      # tur içi — eşik: ortak_esik
    onceki_konular = list(gecmis_konular or [])   # yayınlanmış — eşik: gecmis_esik
    for haber in adaylar:
        if len(secilen) >= adet:
            break
        kelimeler = _anahtar_kelimeler(haber["ig_baslik"] or haber["baslik_orj"])
        if any(len(kelimeler & onceki) >= ortak_esik for onceki in konular):
            continue
        # Bu olayı son günlerde zaten yayınladık mı?
        # İki şart BİRLİKTE aranıyor: yeterince ortak kelime VE en az
        # bir ortak özel isim. Tek başına kelime sayısı "Resmi Gazete'de
        # yayımlandı" gibi kalıplarda yanlış eşleşme veriyordu.
        # ⚠️ `konu_imzasi` — geçmiş denetiminde kullanılan imzayla AYNI
        # olmalı. `yayinlanmis_konular` konu_imzasi ile kuruluyor;
        # burada farklı bir fonksiyon kullanmak iki tarafı kıyaslanamaz
        # hale getirir ve tekrar sessizce yakalanamaz.
        _, isimler = konu_imzasi(haber["ig_baslik"] or haber["baslik_orj"])
        yeterince_buyuk = (haber["onem_puani"] or 0) >= muafiyet
        if not yeterince_buyuk and any(
                len(kelimeler & ok) >= gecmis_esik and (isimler & oi)
                for ok, oi in onceki_konular):
            log.info("konu son %s günde zaten yayınlandı, atlanıyor: %s",
                     (s.get("gecmis_konu_gun", 2)),
                     (haber["ig_baslik"] or haber["baslik_orj"])[:60])
            continue
        secilen.append(haber)
        konular.append(kelimeler)

    return secilen


def tur_icin_sec(con, ayarlar: dict) -> list:
    """
    Yayınlanacak haberleri seçer.

    Metni hazır olan havuzdan skora göre sıralayıp en iyi N tanesini
    döner. Onaylanmayıp havuza dönen haberler burada yeniden yarışıyor —
    "onay verilmezse haber elenmez" kararı böyle işliyor.
    """
    g = ayarlar["gorsel"]
    sinir_saat = ayarlar["genel"]["yayin_yasi_siniri_saat"]

    # ⚠️ ASGARİ ÖNEM PUANI — TUR ARTIK SABİT 10 SLAYT DEĞİL.
    #
    # Önce havuzdan en iyi 10 alınıyordu; havuz doluysa 10'uncu haber
    # bazen "belediye şu toplantıyı yaptı" seviyesine düşüyordu. Artık
    # eşiği geçen kaç haber varsa o kadar slayt üretiliyor: az gün 6-7,
    # yoğun gün 10. Zayıf haberle slayt doldurmak turun tamamını
    # sıradanlaştırıyor.
    asgari = (ayarlar.get("secim", {}) or {}).get("asgari_onem_puani", 0)

    adaylar = list(con.execute(
        "SELECT * FROM haberler WHERE durum = 'metin_hazir' "
        "AND ig_baslik IS NOT NULL"
        " AND COALESCE(daha_once_yayinlandi, 0) = 0"
    ))

    # Skor sıralaması ÖNCE: aday kapısı verilen sırayı koruyor, yani
    # en iyi haberler önce denenmiş oluyor.
    adaylar.sort(key=lambda h: skor(h, ayarlar), reverse=True)

    # ⚠️ ELEME KURALLARI `src/aday.py`'DE — burada tekrar YOK.
    #
    # Tazelik (bayatlama sınırı), asgari önem puanı, aynı olayın
    # tekrarı ve son günlerde yayınlanmış konu denetimi tek kapıdan
    # geçiyor. Bu kurallar önce üç ayrı yere kopyalanmıştı ve biri
    # hep unutuluyordu (1j, 1p).
    # ⚠️ GEÇ İMPORT — KARŞILIKLI BAĞIMLILIK VAR.
    # `aday.py` bu modülün `konu_imzasi` ve `yayinlanmis_konular`
    # fonksiyonlarını kullanıyor; modül başında import edersek
    # döngüsel import oluşur ve ikisi de yüklenemez.
    from . import aday

    baglam = aday.Baglam.kur(aday.TUR, ayarlar, con)
    secilen = aday.sec(adaylar, baglam, adet=g["slayt_sayisi"])

    # ⚠️ DAHA ÖNCE YAYINLANMIŞ HABER TURDA EN SONA.
    #
    # 9+ puanlı haberler geçmiş denetiminden muaf (bkz. aday.uygun_mu):
    # büyük bir olay günün özetinde de yer almalı. Ama takipçi o postu
    # gün içinde zaten gördü; başa koymak turun ilk izlenimini tekrarla
    # harcıyor. Kullanıcı kararı (20 Ağu 2026): "kalsın havuzda ama
    # gündüz yayınlandıysa en son sırada olsun".
    esik = (ayarlar.get("secim", {}) or {}).get("gecmis_ortak_kelime", 3)
    for h in secilen:
        kel, ozel = konu_imzasi(h["ig_baslik"] or h["baslik_orj"])
        gorulmus = any(
            len(ortak_kelime(kel, gk)) >= esik and ortak_kelime(ozel, go)
            for gk, go in baglam.gecmis_konular)
        con.execute("UPDATE haberler SET daha_once_yayinlandi = ? WHERE id = ?",
                    (1 if gorulmus else 0, h["id"]))
    con.commit()

    # Listeyi yeniden oku: sıralama artık işareti de hesaba katıyor.
    # (Satırlar salt-okunur olduğu için yerinde güncellenemiyor.)
    idler = [h["id"] for h in secilen]
    if idler:
        isaret = ",".join("?" * len(idler))
        taze = {r["id"]: r for r in con.execute(
            f"SELECT * FROM haberler WHERE id IN ({isaret})", tuple(idler))}
        secilen = [taze.get(h["id"], h) for h in secilen]
        secilen.sort(key=lambda h: ((h["daha_once_yayinlandi"] or 0),
                                    -skor(h, ayarlar)))

    gorulen = sum(1 for h in secilen if h["daha_once_yayinlandi"])
    log.info("tur seçimi: %d adaydan %d haber (%d tanesi daha önce "
             "yayınlanmış, sona alındı)", len(adaylar), len(secilen), gorulen)
    return secilen


# Türkçe ek toleransı için: iki kelime aynı kökten mi geliyor?
# Ortak önek, kısa olanın bu oranı kadarsa aynı sayılıyor.
KOK_ORANI = 0.8
KOK_ASGARI_HARF = 4


def _ayni_kok(a: str, b: str) -> bool:
    """
    "ceza" ile "cezası" aynı kelime mi? Türkçe için evet.

    ⚠️ NEDEN GEREKTİ (20 Ağu 2026): aynı PFDK kararının iki haberi tek
    tura girdi ve tur içi mükerrer denetimi yakalayamadı —
      "PFDK Fenerbahçe ve Galatasaray dahil çok sayıda kulübe para CEZASI"
      "PFDK Mahmut Uslu'ya 2 milyon 500 bin lira ve KULÜPLERE CEZA"
    Ortak kelime yalnızca "pfdk" sayıldı (eşik 2), çünkü "ceza"≠"cezası"
    ve "kulübe"≠"kulüplere". Türkçe sondan eklemeli bir dil; düz küme
    kesişimi bu yüzden zayıf kalıyor.

    Tam kök bulma (stemming) yapmıyoruz — bir kütüphane bağımlılığı
    daha demek ve bu iş için gereğinden ağır. Ortak önek oranı yeterli.
    """
    if a == b:
        return True
    kisa, uzun = (a, b) if len(a) <= len(b) else (b, a)
    if len(kisa) < KOK_ASGARI_HARF:
        return False
    ortak = 0
    for x, y in zip(kisa, uzun):
        if x != y:
            break
        ortak += 1
    return ortak >= max(KOK_ASGARI_HARF, len(kisa) * KOK_ORANI)


def ortak_kelime(kume1: set, kume2: set) -> set:
    """
    İki başlığın ortak kelimeleri — Türkçe eklerini tolere ederek.

    Kesişim yerine bunu kullan: `kume1 & kume2` "ceza"/"cezası"
    çiftini kaçırıyor.
    """
    ortak = set()
    for a in kume1:
        for b in kume2:
            if _ayni_kok(a, b):
                ortak.add(a)
                break
    return ortak
