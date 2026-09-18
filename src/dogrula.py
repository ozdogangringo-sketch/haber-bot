"""
dogrula.py — Üretilen metnin kaynakta karşılığı var mı diye bakar.

NEDEN VAR:
    Onay adımı tek başına uydurmayı yakalamıyor. Uydurulmuş bir cümle
    akıcı ve inandırıcı görünüyor; insan gözü "kulağa doğru geliyor"
    diye onaylıyor. Ölçüldü (Adım 2): RSS teaser'ıyla çalışan üç ayrı
    model de kaynakta OLMAYAN iddialar üretti — üstelik adı geçen gerçek
    bir milletvekili ve cinsel taciz suçlaması hakkında.

NEYE BAKIYOR:
    Uydurma genelde SOMUT ayrıntıda oluyor: bir sayı, bir isim, bir
    tarih. Genel cümleler ("açıklama yaptı") düşük riskli. Bu yüzden
    sayı ve özel isim doğrulaması yapıyoruz — ikisi de kaynakta
    aranabiliyor ve ikisi de yanlış olduğunda gerçekten zarar veriyor.

NE YAPMIYOR:
    Anlam denetimi yapmıyor. "X, Y'yi reddetti" ile "X, Y'yi kabul etti"
    aynı kelimeleri taşıyor; bunu ayırmak için ikinci bir LLM çağrısı
    gerekir. Bu katman ucuz ve deterministik bir ilk süzgeç — insan
    onayının yerine değil, önüne konuyor.

TÜRKÇE EK SORUNU:
    "Soruşturmasında" kaynakta "soruşturma" olarak geçiyor. Tam eşleşme
    ararsak her ek yanlış alarm üretir. Kaba kök alıp (kelimenin ilk
    %70'i) öyle karşılaştırıyoruz.
"""

from __future__ import annotations

import logging
import re
import unicodedata

log = logging.getLogger(__name__)

# Bu kelimeler cümle içinde büyük harfle başlayabiliyor ama özel isim
# değiller; doğrulamaya sokulursa gürültü yapıyorlar.
AYLAR_GUNLER = {
    "ocak", "şubat", "mart", "nisan", "mayıs", "haziran", "temmuz",
    "ağustos", "eylül", "ekim", "kasım", "aralık",
    "pazartesi", "salı", "çarşamba", "perşembe", "cuma", "cumartesi", "pazar",
}


def _sadelestir(metin: str) -> str:
    """Türkçe karakterleri ve noktalamayı indirger."""
    metin = metin.replace("İ", "i").replace("I", "i").replace("ı", "i")
    metin = unicodedata.normalize("NFKD", metin)
    metin = "".join(c for c in metin if not unicodedata.combining(c))
    return re.sub(r"[^0-9a-z]", " ", metin.lower())


def _kok(kelime: str) -> str:
    """
    Kaba kök: kesme işaretinden kes, kalanın ilk %70'ini al.
    "İstanbul'a" -> "istanbul",  "Soruşturmasında" -> "sorustur"
    """
    k = _sadelestir(kelime.split("'")[0]).strip()
    return k[: max(4, int(len(k) * 0.7))]


def _sayilar(metin: str) -> set[str]:
    """Ayraçları temizlenmiş sayılar. '2.500' ve '2500' aynı sayılıyor."""
    duz = metin.replace(".", "").replace(",", "")
    return {s for s in re.findall(r"\d+", duz) if len(s) >= 1}


# ----------------------------------------------------------------------
# TÜRKÇE SAYI EŞDEĞERLERİ — "kurt geliyor" uyarısını susturmak için
# ----------------------------------------------------------------------
#
# ⚠️ NEDEN GEREKTİ (18 Eyl 2026). ÖLÇÜLDÜ: yayınlanan 200 haberin
# **50'si** (%25) Telegram onay mesajında `⚠️ DENETİM UYARISI`
# alıyordu ve bunların 38'i "kaynakta olmayan sayı" idi. Tek tek
# bakıldı: **19'u (yarısı) TÜRKÇE YAZIM FARKI**, uydurma değil.
#
#     üretilen "435.683"     kaynak "435 bin 683"
#     üretilen "4,62 ₺"      kaynak "4 lira 62 kuruş"
#     üretilen "%29,61"      kaynak "yüzde 29,61"
#     üretilen "9.000"       kaynak "9 bin"
#
# `_sayilar` ayraçları siliyor: "4,62" -> "462". Kaynakta "462" diye
# bir sayı yok, dolayısıyla uyarı çıkıyor.
#
# ⚠️ BU BİR GÜRÜLTÜ SORUNU, DOĞRULUK SORUNU DEĞİL — ve tam olarak bu
# yüzden tehlikeli. Projenin kendi dersi: *"Yanlış alarm veren test,
# hiç olmayan testten kötüdür — insan onu görmezden gelmeye başlar."*
# Dörtte bir orana çıkmış bir uyarı okunmaz olur ve GERÇEK uyarı da
# onunla birlikte kaybolur.
#
# ⚠️ GENİŞLETME YALNIZCA KAYNAK TARAFINA UYGULANIR. Üretilen metin
# `_sayilar` ile okunmaya devam ediyor; kaynak ise "bu sayı şu
# biçimlerde de yazılmış olabilir" diye genişletiliyor. Ters yönde
# yapılsaydı uydurma bir sayı kaynaktaki başka bir sayıya benzeyip
# sessizce geçebilirdi.

_YAZIYLA_SAYI = {
    "bir": 1, "iki": 2, "üç": 3, "dört": 4, "beş": 5, "altı": 6,
    "yedi": 7, "sekiz": 8, "dokuz": 9, "on": 10, "yirmi": 20,
    "otuz": 30, "kırk": 40, "elli": 50, "altmış": 60, "yetmiş": 70,
    "seksen": 80, "doksan": 90, "yüz": 100,
}

_CARPANLAR = {"bin": 1000, "milyon": 10 ** 6, "milyar": 10 ** 9}


def sayi_esdegerleri(metin: str | None) -> set[str]:
    """
    Kaynak metindeki sayıların BÜTÜN makul Türkçe yazımları.

    `_sayilar`ın ürettiklerine ek olarak:
      * bileşik  "435 bin 683"      -> 435683
      * çarpan   "9 bin", "2 milyar" -> 9000, 2000000000
      * ondalık  "4,62"             -> 462, 4, 62
      * para     "4 lira 62 kuruş"  -> 462
      * yazıyla  "dört"             -> 4

    ⚠️ Yalnızca KAYNAK tarafında kullanılır (bkz. yukarıdaki not).
    """
    m = str(metin or "")
    sonuc = set(_sayilar(m))

    # Bileşik sayı öbekleri: "9 bin" · "435 bin 683" · "2 milyon 702 bin 500"
    #
    # ⚠️ İÇ İÇE ÇARPAN VAR. İlk yazımda desen "(sayı)(çarpan)( sayı)?"
    # idi ve "2 milyon 702 bin" için 2·10⁶ + 702 = 2.000.702 üretiyordu;
    # doğrusu 2·10⁶ + 702·10³ = 2.702.000. Öbeği bir bütün olarak
    # okumak gerekiyor: ardışık (sayı, çarpan) ikilileri çarpanları
    # KÜÇÜLDÜĞÜ sürece toplanıyor, büyüdüğü an yeni öbek başlıyor.
    obek = re.compile(
        r"(\d[\d.,]*)\s*(bin|milyon|milyar)?(?=\s|$|[^\w])", re.IGNORECASE)
    parcalar = list(obek.finditer(m))
    i = 0
    while i < len(parcalar):
        toplam = 0.0
        onceki_carpan = None
        j = i
        while j < len(parcalar):
            e = parcalar[j]
            try:
                taban = float(e.group(1).replace(".", "").replace(",", "."))
            except ValueError:
                break
            carpan = _CARPANLAR.get((e.group(2) or "").lower(), 1)
            # Çarpan büyüyorsa ya da araya başka metin girdiyse öbek bitti
            if onceki_carpan is not None and carpan >= onceki_carpan:
                break
            if j > i and m[parcalar[j - 1].end():e.start()].strip():
                break
            toplam += taban * carpan
            onceki_carpan = carpan
            j += 1
            if carpan == 1:
                break
        if j > i and toplam:
            try:
                sonuc.add(str(int(toplam)))
            except (ValueError, OverflowError):
                pass
        # ⚠️ KISMİ TOPLAMLAR DA EKLENİYOR. Kaynak "2 milyon 702 bin 482"
        # yazarken model "2 milyon 702.482" yazıyor — yani milyon
        # kısmını kelimeyle, kalanını rakamla. `_sayilar` bunu "702482"
        # olarak okuyor ve tam toplam (2702482) ile eşleşmiyordu.
        # Öbeğin her SONEKİ ayrı bir yazım olabilir: 2702482, 702482, 482.
        artan = 0.0
        for k in range(j - 1, i - 1, -1):
            e = parcalar[k]
            try:
                taban = float(e.group(1).replace(".", "").replace(",", "."))
            except ValueError:
                break
            artan += taban * _CARPANLAR.get((e.group(2) or "").lower(), 1)
            try:
                sonuc.add(str(int(artan)))
            except (ValueError, OverflowError):
                break
        i = max(j, i + 1)

    # Ondalık: "4,62" -> hem 462 hem 4 hem 62
    for e in re.finditer(r"(\d+)[,.](\d+)", m):
        sonuc.update((e.group(1), e.group(2), e.group(1) + e.group(2)))

    # "4 lira 62 kuruş" -> 462
    for e in re.finditer(r"(\d+)\s*(?:lira|tl|₺)\s*(\d+)\s*kuru",
                         m, re.IGNORECASE):
        sonuc.add(e.group(1) + e.group(2))

    # Yazıyla yazılmış küçük sayılar
    sade = _sadelestir(m)
    for kelime, deger in _YAZIYLA_SAYI.items():
        if re.search(r"\b" + _sadelestir(kelime).strip() + r"\b", sade):
            sonuc.add(str(deger))

    return sonuc


# ----------------------------------------------------------------------
# VURGU RAKAMI KAPISI — "zorla eklenmiş rakam" ve "yazılmak için
# yazılmış etiket" elemesi
# ----------------------------------------------------------------------
#
# ⚠️ KULLANICI BİLDİRİMİ (18 Eyl 2026): *"özellikle vurgu rakamlarının
# altındaki metinler bazen çok yazılmak için yazılmış ya da o rakam
# oraya zorla eklenmiş gibi duruyor."*
#
# ÖLÇÜLDÜ (238 gerçek vurgu, mevcut kapılardan geçenler): 20'si
# (%8) iki kusurdan birini taşıyordu.
#
# ① RAKAM ZORLA EKLENMİŞ — çıplak tek haneli sayı. Sayfanın en
#    üstünde 92 puntoya kadar çıkan amber bir "4" okuyucuya hiçbir
#    büyüklük duygusu vermiyor:
#        "5"  / sezonluk garanti
#        "4"  / maçlık seri bitti
#        "2"  / eksik oyuncu
#        "3"  / desteklenen ilk model
#    ⚠️ İKİ HANE SINIRDA KALIYOR, bilerek: "12 / alıkonulan gemi" ve
#    "48 / gözaltı kararı" gerçek sayımlar ve çarpıcı.
#
# ② ETİKET CÜMLE PARÇASI — etiket yalnızca rakama yapışınca anlamlı
#    oluyor, tek başına bir şey ölçmüyor:
#        "38" / yaşındaki şehit polis   ("38 yaşındaki şehit polis")
#        "77" / maçlık seri sona erdi
#    Etiket bir AD ÖBEĞİ olmalı ("füze ağırlığı", "işlem hacmi"),
#    cümlenin kalanı değil.
#
# ⚠️ FİİL DENETİMİ DAR TUTULDU. İlk yazımda "-dı/-di/-tı/-ti ile
# biten etiket fiildir" kuralı denendi ve ÖLÇÜLDÜ: 16 eşleşmenin
# 13'ü YANLIŞ ALARMDI — Türkçe iyelik eki de aynı harflerle bitiyor
# ("fiyatı", "galibiyeti", "hacmi"). Bu yüzden açık fiil listesi
# kullanılıyor.
#
# ⚠️ İKİ YERDEN ÇAĞRILIYOR: `slaytlar.son_dakika_uret` (ayrıntı
# sayfasının dev rakamı) ve `hook_motoru.hook_olustur` (kapak
# kancası). Kanca tarafında ÖNCEDEN HİÇBİR KAPI YOKTU — yıl/tarih
# denetimi bile yalnızca slayt tarafındaydı.

_ETIKET_FIILLERI = {
    "bitti", "erdi", "edildi", "oldu", "başladı", "açıklandı",
    "yapıldı", "geldi", "gitti", "kaldı", "düştü", "çıktı",
    "verildi", "alındı", "yükseldi", "kesildi", "uzatıldı",
    "sona", "kalktı", "sürüyor", "ediyor", "gerekiyor",
}

_ETIKET_SAYI_EKLERI = re.compile(
    r"^(ya[sş][ıi]nda|ma[cç]l[ıi]k|sezonluk|ki[sş]ilik|katl[ıi]|"
    r"puanl[ıi]k|haneli|gunluk)", re.IGNORECASE)


def vurgu_zayif_mi(deger: str | None, etiket: str | None) -> str | None:
    """
    Vurgu rakamı slayta basılmaya değer mi?

    Zayıfsa sebebi döner (loglanabilsin diye), güçlüyse None.
    Bkz. yukarıdaki ölçüm notu.
    """
    d = (deger or "").strip()
    e = (etiket or "").strip()
    if not d:
        return None

    # ① Çıplak tek haneli sayı — büyüklük duygusu yok
    if re.fullmatch(r"\d", d):
        return "çıplak tek haneli sayı"

    # ② Etiket rakama yapışan ekle başlıyor ("38 yaşındaki …")
    if _ETIKET_SAYI_EKLERI.match(_sadelestir(e).strip()):
        return "etiket rakama yapışan ekle başlıyor"

    # ② Etiket cümle — açık fiille bitiyor
    son = (e.split() or [""])[-1].strip(".,;:").casefold()
    if son in _ETIKET_FIILLERI:
        return "etiket cümle parçası (fiille bitiyor)"

    return None


def veri_karti_dogrula(eski_deger: str | None, yeni_deger: str | None, kaynak_metin: str | None) -> bool:
    """
    Veri kartındaki sayıların kaynak metinde gerçekten geçip geçmediğini doğrular.
    Uydurma sayıları engeller; kaynakta bulunamazsa False döner.
    """
    if not yeni_deger or not kaynak_metin:
        return False

    kaynak_sayilar = _sayilar(kaynak_metin)

    yeni_sayilar = _sayilar(yeni_deger)
    if not yeni_sayilar or not yeni_sayilar.issubset(kaynak_sayilar):
        return False

    if eski_deger:
        eski_sayilar = _sayilar(eski_deger)
        if eski_sayilar and not eski_sayilar.issubset(kaynak_sayilar):
            return False

    return True


def veri_karti_baslikta_var_mi(veri_karti: dict, baslik: str, ozet: str = "") -> bool:
    """
    Veri kartındaki sayılar veya değerler başlıkta ya da spotta zaten geçiyorsa True döner.
    Bu durumda veri kartı çizilmemeli (kopya / gereksiz rozet engellenir).
    """
    if not veri_karti:
        return False

    baslik_ozet = f"{baslik} {ozet}".lower()
    baslik_sayilar = _sayilar(baslik_ozet)

    yeni = str(veri_karti.get("yeni") or "")
    eski = str(veri_karti.get("eski") or "")

    # 1. Sayısal geçiş kontrolü
    yeni_sayilar = _sayilar(yeni)
    if yeni_sayilar and yeni_sayilar.issubset(baslik_sayilar):
        if not eski:
            return True
        eski_sayilar = _sayilar(eski)
        if eski_sayilar and eski_sayilar.issubset(baslik_sayilar):
            return True

    # 2. Metinsel doğrudan geçiş kontrolü (örn "6 - 2", "6-2", "4500", "600 bin")
    yeni_temiz = _sadelestir(yeni)
    baslik_temiz = _sadelestir(baslik_ozet)
    if yeni_temiz and len(yeni_temiz) >= 2 and yeni_temiz in baslik_temiz:
        if not eski or _sadelestir(eski) in baslik_temiz:
            return True

    return False


# ----------------------------------------------------------------------
# ÖZEL İSİM DENETİMİNİN DURAK LİSTESİ
# ----------------------------------------------------------------------
#
# ⚠️ NEDEN GEREKTİ (18 Eyl 2026). `_ozel_isimler` cümle ortasındaki her
# büyük harfli kelimeyi özel isim sayıyor. Türkçede kurum adlarının
# İÇİNDEKİ cins isimler de büyük yazılıyor ("Sermaye Piyasası Kurulu")
# ve milliyet sıfatları da öyle ("Türk sürücüler", "İtalyan kulübü").
#
# ÖLÇÜLDÜ (300 yayınlanmış haber): 580 isim işaretinin neredeyse
# tamamı bu sınıftandı — `Kurulu`, `Piyasası`, `Bakanlığı`, `Türk`,
# `İtalyan`, `Fransız`, `Filistinli`, `Foto`, `Gündem`.
#
# ⚠️ DAHA İLGİNÇ OLANI: model KISALTMAYI AÇIYOR. Kaynak "SPK" yazıyor,
# model "Sermaye Piyasası Kurulu" yazıyor — okuyucu için DOĞRU olan
# davranış — ve denetim bunu uydurma sayıp cezalandırıyordu.
#
# ⚠️ DENETİMİN AMACI BU DEĞİL. Bu kapı, modelin kaynakta OLMAYAN bir
# KİŞİYE ya da kuruma bir şey atfetmesini yakalamak için var. Cins
# isim ve milliyet sıfatı hiçbir zaman o tehlikeli durum değildir.
#
# ⚠️ LİSTE BİLEREK DAR — projenin ölçülmüş dersi ("içi boş övgü"
# vakası): geniş liste 5 eleme yaptı, 3'ü yanlış alarmdı; dar liste
# 2 eleme yaptı, ikisi de tam hedefti. Buraya kelime eklerken
# "bu kelime tek başına bir KİŞİYİ ya da KURUMU adlandırır mı?"
# diye sor; cevap evetse EKLEME.
_ISIM_DURAKLARI = {
    # Kurum/idare cins isimleri (kurum adının İÇİNDE büyük yazılıyor)
    "kurulu", "kurumu", "kurum", "bakanligi", "bakanlik", "baskanligi",
    "baskani", "mudurlugu", "mudurluk", "genel", "meclis", "meclisi",
    "piyasasi", "piyasalari", "kanunu", "kanunundan", "kanun",
    "yonetmeligi", "komisyonu", "komitesi", "birligi", "odasi",
    "dernegi", "vakfi", "enstitusu", "universitesi", "hastanesi",
    "belediyesi", "valiligi", "savciligi", "mahkemesi", "emniyet",
    "teskilati", "merkezi", "idaresi", "ajansi", "borsasi", "bankasi",
    "sirketi", "holding", "grubu", "federasyonu", "kulubu",
    # Unvan ekleri
    "ceosu", "ctosu", "cfosu", "sozcusu", "yardimcisi", "vekili",
    # Milliyet/aidiyet sıfatları (cümle ortasında büyük yazılıyor)
    "turk", "alman", "ingiliz", "fransiz", "italyan", "ispanyol",
    "rus", "amerikan", "cinli", "japon", "koreli", "hintli", "arap",
    "iranli", "israilli", "filistinli", "suriyeli", "yunan",
    "hollandali", "belcikali", "isvicreli", "avusturyali",
    "portekizli", "brezilyali", "arjantinli", "meksikali",
    "misirli", "ukraynali", "polonyali", "kanadali", "avustralyali",
    # Kendi şablon metnimiz (caption/slayt başlıkları)
    "foto", "gundem", "temsili", "daily", "brief", "briefing",
    "basliklari", "manset", "kaynak", "arsiv",
}


def _ozel_isimler(metin: str) -> list[str]:
    """
    Cümle ortasında büyük harfle başlayan kelimeler.

    Cümle başındakiler atlanıyor (orada büyük harf zorunlu, bilgi
    taşımıyor). Başlık bu fonksiyona VERİLMEMELİ: başlıklar Title Case
    olabiliyor ve o zaman her kelime özel isim sanılıyor.
    """
    bulunan = []
    kelimeler = metin.split()
    for i, kelime in enumerate(kelimeler):
        temiz = kelime.strip(".,;:!?'\"()[]")
        if len(temiz) < 4 or not temiz[0].isupper() or temiz.isupper():
            continue
        if i == 0 or kelimeler[i - 1].endswith((".", ":", "?", "!")):
            continue
        # ⚠️ KESME İŞARETİNDEN KES. "Meclis'e" -> "meclis": Türkçede
        # ekler kesmeyle ayrılıyor ve `_sadelestir` kesmeyi BOŞLUĞA
        # çeviriyor, yani durak listesi "meclis e" ile eşleşmiyordu.
        # `_kok` de aynı bölmeyi yapıyor; iki taraf tutarlı olmalı.
        sade = _sadelestir(temiz.split("'")[0]).strip()
        if sade in AYLAR_GUNLER:
            continue
        # Kurum cins ismi, milliyet sıfatı, kendi şablonumuz — bkz.
        # `_ISIM_DURAKLARI`. Bunlar hiçbir zaman "modelin uydurduğu
        # kişi/kurum" olmuyor, yalnızca uyarıyı gürültüye boğuyorlar.
        if sade in _ISIM_DURAKLARI:
            continue
        bulunan.append(temiz)
    return bulunan


# Konuyu duyurup SONUCU saklayan kalıplar.
#
# Neden denetliyoruz: takipçiye link vermiyoruz, okuyacağı başka yer yok.
# "Bakan X'ten Y'ye ilişkin açıklama" diyen bir slayt kaydırılıp geçildiğinde
# kişi hiçbir şey öğrenmemiş oluyor — tam da clickbait sayfalarının yaptığı
# şey. Prompt bunu yasaklıyor ama model ara sıra yine düşüyor; bu süzgeç
# yakalayıp onay mesajında uyarıyor.
ICI_BOS_KALIPLAR = (
    "ilişkin açıklama", "dair açıklama", "ilişkin konuştu", "hakkında konuştu",
    "değerlendirdi", "anlattı", "ele aldı", "mesaj verdi", "görüş bildirdi",
    "gündeme getirdi", "dikkat çekti", "açıklama yaptı", "açıklamalarda bulundu",
    "değerlendirmede bulundu", "konuşma yaptı",
)

# Abartı/tıklama tuzağı işaretleri.
# ⚠️ TÜRKÇE ÇEKİMLER AYRI AYRI YAZILMALI.
# Kalıplar kelime sınırıyla aranıyor (bkz. `basligi_denetle`), yani
# "şaşırttı" yazmak "şaşırtan"ı yakalamıyor. Kök araması yapmak da
# çözüm değil: "şok" kökü sadeleştirme sonrası "sok" oluyor ve sonek
# serbest bırakılırsa "sokak" yeniden eşleşiyor.
ABARTI_KALIPLAR = (
    "şok", "bomba", "işte o an", "olay oldu", "inanılmaz",
    "herkesi şaşırttı", "herkesi şaşırtan", "şaşırtan",
    "gündemi salladı", "gündemi sallayan",
    "şaşkına çevirdi", "şaşkına çeviren",
    "ağzı açık kaldı", "dumur etti", "çılgın",
)


# ⚠️ İÇİ BOŞ ÖVGÜ — "neden_onemli" / "sana_etkisi" alanlarının hastalığı.
# Kullanıcı (6 Eyl 2026): *"bu paragraf çok fazla AI gibi duruyor, yapay bir
# cümle ve sırıtıyor"*. Örnek: *"Milli takımın bu tarihi başarısı tüm
# Türkiye'de büyük bir gurur, coşku ve motivasyon kaynağı yaratıyor."*
#
# ⚠️ Cümleler YANLIŞ DEĞİL — sorun bu. Yanlış olsalar sayı/isim denetimi
# yakalardı. Bunlar DOĞRULANAMAZ: içlerinde kontrol edilebilecek hiçbir şey
# yok, silinince hiçbir bilgi kaybolmuyor. Kaynak zayıf olduğunda model
# boşluğu övgüyle dolduruyor (ölçüldü: gövde zenginken boş cümle %8, gövde
# zayıfken %44).
#
# ⚠️ İKİ ÖLÇÜT AYRI ÇALIŞIYOR — bu ayrım ölçümle bulundu:
#   DUYGU ATFI koşulsuz elenir: bir topluluğun duygusu kaynakta ASLA yazmaz.
#   TÖREN DİLİ yalnızca yanında somut sayı YOKSA elenir — "45 milyon Euro
#   bedelle tarihin en yüksek transferi" bilgi taşıyor, elenmemeli.
_DUYGU_ATFI = re.compile(
    r"gurur|coşku|moral kaynağı|motivasyon kaynağı|sevinç kaynağı|"
    r"tüm (Türkiye|ülke|dünya)'?d[ae]", re.IGNORECASE)

# ⚠️ DAR TUTULDU. Düz "en büyük" / "en önemli" DENENDİ ve ELENDİ: olgusal
# tanımları da yakalıyordu ("Türkiye'nin en büyük yerel yönetimi olan İBB").
# Ölçüm: geniş liste 202 cümlenin 5'ini eledi ve 3'ü yanlış alarmdı; dar
# liste 2'sini eliyor ve ikisi de kullanıcının gösterdiği cümleler.
_TOREN_DILI = re.compile(
    r"tarihin?in en (önemli|büyük|prestijli|unutulmaz)|prestijli başarı|"
    r"kayda geçiyor|altın harflerle|başarılarından biri olarak|"
    r"zaferle birlikte", re.IGNORECASE)

_SOMUT_SAYI = re.compile(r"\d")


def bos_ovgu_mu(cumle: str) -> bool:
    """
    Bu cümle bilgi taşımayan bir övgü mü?

    Ölçüldü (202 gerçek cümle): %1'i eleniyor ve elenenler tam olarak
    kullanıcının *"yapay duruyor"* dediği cümleler. Bilgi veren cümleler
    (`45 milyon Euro`, `35 il`, `9 yıllık kariyer`) korunuyor.
    """
    metin = (cumle or "").strip()
    if not metin:
        return False
    if _DUYGU_ATFI.search(metin):
        return True
    return bool(_TOREN_DILI.search(metin)) and not _SOMUT_SAYI.search(metin)


def ovguyu_ele(cumle: str) -> str:
    """İçi boş övgüyse boş dize döner — çağıran taraf o bloğu basmaz."""
    if bos_ovgu_mu(cumle):
        log.info("içi boş övgü elendi: %s", (cumle or "")[:80])
        return ""
    return cumle


def basligi_denetle(baslik: str) -> list[str]:
    """
    Başlık haberin sonucunu söylüyor mu diye bakar.

    Türkçe `İ` tuzağı: "İlişkin".lower() Python'da "i̇lişkin" üretiyor
    (noktalı i) ve düz karşılaştırma tutmuyor. _sadelestir() bunu
    çözdüğü için karşılaştırmayı onun üzerinden yapıyoruz.
    """
    if not baslik:
        return []
    sade = _sadelestir(baslik)
    sorunlar = []

    for kalip in ICI_BOS_KALIPLAR:
        if _sadelestir(kalip).strip() in sade:
            sorunlar.append(f"içi boş kalıp: '{kalip}'")
            break

    # ⚠️ ABARTI KALIPLARI KELİME SINIRIYLA ARANIYOR, ALT DİZE OLARAK DEĞİL.
    #
    # `_sadelestir` "ş" harfini "s"ye çeviriyor, yani "şok" → "sok".
    # Alt dize araması yapılınca "sokak", "Söke", "sokuldu" gibi masum
    # kelimeler eşleşiyordu: "İstanbul'da ... sokak ulaşıma kapatıldı" ve
    # "Söke-Milas kara yolunda..." başlıkları "abartılı" damgası yiyordu
    # (18 Ağu 2026'da ölçüldü).
    #
    # Yanlış uyarı, uyarı vermemekten kötü: onay mesajında sürekli
    # gereksiz işaret gören kullanıcı gerçek uyarıyı da ciddiye almıyor.
    for kalip in ABARTI_KALIPLAR:
        kalip_sade = _sadelestir(kalip).strip()
        if re.search(rf"(?<!\w){re.escape(kalip_sade)}(?!\w)", sade):
            sorunlar.append(f"abartı: '{kalip}'")
            break

    return sorunlar


# Kaynakta suçlama/soruşturma olduğunu gösteren ifadeler.
SUCLAMA_ISARETI = (
    "iddia", "öne sürül", "şüpheli", "gözaltına", "soruşturma",
    "savcılık", "hakkında dava", "suçlam", "tutuklama talebi",
)

# Üretilen metinde ihtiyat korunduğunu gösteren ifadeler.
IHTIYAT_ISARETI = (
    "iddia", "öne sürül", "şüpheli", "soruşturma", "gözaltı",
    "savcılık", "hakkında dava", "suçlam", "tutukland", "yargılan",
    "belirtil", "bildiril", "açıklad", "duyur",
)


def _atifli_mi(baslik: str) -> bool:
    """
    Başlık bir kaynağa atıfla mı başlıyor? ("BM:", "Erdoğan:", "Bakan X:")

    Atıflı başlıkta iddia zaten birine dayandırılmış oluyor; ihtiyat
    denetimi orada yanlış alarm veriyor. Ölçüldü: 3 uyarının 2'si bu
    yüzden çıkmıştı.
    """
    return bool(re.match(r"^[^:]{2,40}:", baslik or ""))


def suclama_dili_denetle(haber) -> list[str]:
    """
    Kaynakta suçlama/soruşturma varsa, üretilen metinde ihtiyat dili
    korunmuş mu?

    NEDEN AYRI BİR DENETİM: sayı ve isim denetimi bunu yakalayamıyor.
    Kaynakta "hakkında soruşturma başlatıldı" yazarken üretilen metin
    "suç örgütü elebaşı" diyebiliyor — bütün sayılar ve isimler kaynakla
    birebir uyuyor, ama dil kesinleşmiş oluyor. Mahkeme kararı olmadan
    kesin dille yazmak iftira riski.

    Ölçüldü (16 Ağu 2026): suçlama içeren 10 haberin 3'ünde ihtiyat
    düşmüştü; ikisi atıflı başlıktı (yanlış alarm), biri gerçek riskti.
    """
    kaynak = _sadelestir(haber["makale_metni"] or "")
    if not kaynak or not any(_sadelestir(k) in kaynak for k in SUCLAMA_ISARETI):
        return []

    baslik = haber["ig_baslik"] or ""
    if _atifli_mi(baslik):
        return []

    uretilen = _sadelestir(
        f"{baslik} {haber['slayt_ozet'] or ''} {haber['ig_caption'] or ''}"
    )
    if any(_sadelestir(k) in uretilen for k in IHTIYAT_ISARETI):
        return []

    return ["suçlama kesin dille yazılmış — kaynakta ihtiyat var, metinde yok"]


def alintiyi_denetle(alinti: str, kaynak: str) -> bool:
    """
    Alıntı kaynak metinde gerçekten geçiyor mu?

    NEDEN EN SIKI DENETİM BU: birinin ağzına söylemediği sözü koymak,
    yanlış sayı yazmaktan çok daha ağır. Sayı düzeltilebilir, uydurma
    alıntı itibar meselesi.

    Kelime kelime karşılaştırıyoruz: alıntının kelimelerinin %85'i
    kaynakta ARDIŞIK olarak geçmeli. Tam eşleşme aramıyoruz çünkü
    modelin araya bir bağlaç sıkıştırması ya da çekim ekini değiştirmesi
    normal; ama cümlenin iskeleti kaynakta durmalı.
    """
    if not alinti or not kaynak:
        return False

    a_kelime = [_kok(k) for k in alinti.split() if len(k) > 2]
    if len(a_kelime) < 3:
        return False

    k_sade = _sadelestir(kaynak)
    k_kelime = [_kok(k) for k in kaynak.split() if len(k) > 2]

    # Alıntının kelimeleri kaynakta ardışık bir pencerede toplanıyor mu?
    pencere = len(a_kelime) + 6
    hedef = int(len(a_kelime) * 0.85)
    for i in range(max(1, len(k_kelime) - pencere + 1)):
        parca = set(k_kelime[i:i + pencere])
        if sum(1 for k in a_kelime if k in parca) >= hedef:
            return True

    # Yedek: düz alt dize araması (model birebir kopyalamışsa)
    return _sadelestir(alinti).strip() in k_sade


def haberi_dogrula(haber) -> dict:
    """
    Tek bir haberin üretilen metnini kaynağıyla karşılaştırır.

    Kaynak olarak makale gövdesi VE RSS özeti birlikte kullanılıyor:
    gövde çekilemediğinde model RSS özetinden üretiyor ve o özet çoğu
    zaman sayıları içeriyor. Yalnızca gövdeye bakmak, gövdesi olmayan
    haberlerin tamamını haksız yere işaretliyordu.

    Döner: {'temiz', 'kaynak_var', 'eksik_sayilar', 'eksik_isimler'}
    """
    parcalar = [haber["makale_metni"] or "", haber["ozet_orj"] or ""]
    kaynak = " ".join(parcalar).strip()
    kaynak_sade = _sadelestir(kaynak)
    # ⚠️ KAYNAK TARAFI GENİŞLETİLİYOR — bkz. `sayi_esdegerleri`.
    # Düz `_sayilar` Türkçe yazım farkını uydurma sanıyordu
    # ("435 bin 683" kaynakta, "435.683" üretilende). ÖLÇÜLDÜ:
    # 83 güncel haberde 18 sayı uyarısının 13'ü bu yüzden çıkıyordu,
    # yani %72'si gürültüydü.
    kaynak_sayi = sayi_esdegerleri(kaynak)

    # Başlık yalnızca sayı kontrolüne giriyor; özel isim kontrolüne
    # girmiyor çünkü Title Case olabiliyor.
    #
    # ⚠️ `detay_metni` VE `vurgu_sayi` 18 EYL 2026'DA EKLENDİ.
    # Öncesinde denetim yalnızca `ig_baslik` + `slayt_ozet` +
    # `ig_caption`e bakıyordu. Denetim dışı kalanlar:
    #   `detay_metni`  %100 dolu, AYRINTI SAYFALARININ TAMAMI
    #   `vurgu_sayi`   %92 dolu, SAYFANIN EN ÜSTÜNDEKİ DEV AMBER RAKAM
    # Yani en uzun metin ve ekrandaki en büyük öğe hiç denetlenmiyordu.
    # Ölçülen uydurma oranı düşüktü (%1-5) ama KAPI YOKTU — gerçek bir
    # uydurma olursa hiçbir şey yakalamıyordu.
    def _al(ad):
        return haber[ad] if ad in haber.keys() else None

    detay = _al("detay_metni") or ""
    vurgu = _al("vurgu_sayi") or ""

    govde = " ".join(filter(None, [haber["slayt_ozet"], haber["ig_caption"],
                                   detay]))
    tumu = " ".join(filter(None, [haber["ig_baslik"], govde, str(vurgu)]))

    eksik_sayilar = sorted(s for s in _sayilar(tumu) if s not in kaynak_sayi)

    eksik_isimler = sorted({
        isim for isim in _ozel_isimler(govde)
        if _kok(isim) and _kok(isim) not in kaynak_sade
    })

    baslik_sorunlari = basligi_denetle(haber["ig_baslik"] or "")
    suclama_sorunlari = suclama_dili_denetle(haber)

    return {
        "temiz": not (eksik_sayilar or eksik_isimler or baslik_sorunlari
                      or suclama_sorunlari) and bool(kaynak),
        "kaynak_var": bool(kaynak),
        "eksik_sayilar": eksik_sayilar,
        "eksik_isimler": eksik_isimler,
        "baslik_sorunlari": baslik_sorunlari,
        "suclama_sorunlari": suclama_sorunlari,
    }


def turu_dogrula(haberler: list) -> tuple[str, int]:
    """
    Bütün turu denetler. (uyarı_metni, işaretli_haber_sayısı) döner.

    Uyarı metni boşsa her şey temiz demektir. Metin Telegram onay
    mesajının başına konuyor — kullanıcı neye dikkat edeceğini
    onaylamadan ÖNCE görsün.
    """
    satirlar = []
    for sira, haber in enumerate(haberler, start=1):
        sonuc = haberi_dogrula(haber)
        if sonuc["temiz"]:
            continue

        ayrinti = []
        if not sonuc["kaynak_var"]:
            ayrinti.append("kaynak metni yok")
        if sonuc["eksik_sayilar"]:
            ayrinti.append("sayı: " + ", ".join(sonuc["eksik_sayilar"][:4]))
        if sonuc["eksik_isimler"]:
            ayrinti.append("isim: " + ", ".join(sonuc["eksik_isimler"][:3]))
        ayrinti.extend(sonuc["baslik_sorunlari"])
        ayrinti.extend(sonuc["suclama_sorunlari"])
        satirlar.append(f"  {sira}. slayt — {'; '.join(ayrinti)}")

    if not satirlar:
        return "", 0

    return (
        "⚠️ DENETİM UYARISI\n"
        + "\n".join(satirlar)
        + "\n(Sayı uyarısı yuvarlama olabilir; içi boş kalıp uyarısında "
          "başlık haberin sonucunu söylemiyor demektir.)"
    ), len(satirlar)
