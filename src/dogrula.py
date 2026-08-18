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

import re
import unicodedata

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
    return {s for s in re.findall(r"\d+", duz) if len(s) >= 2}


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
        if _sadelestir(temiz).strip() in AYLAR_GUNLER:
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
    kaynak_sayi = _sayilar(kaynak)

    # Başlık yalnızca sayı kontrolüne giriyor; özel isim kontrolüne
    # girmiyor çünkü Title Case olabiliyor.
    govde = " ".join(filter(None, [haber["slayt_ozet"], haber["ig_caption"]]))
    tumu = " ".join(filter(None, [haber["ig_baslik"], govde]))

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
