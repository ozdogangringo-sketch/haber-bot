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

    return {
        "temiz": not (eksik_sayilar or eksik_isimler) and bool(kaynak),
        "kaynak_var": bool(kaynak),
        "eksik_sayilar": eksik_sayilar,
        "eksik_isimler": eksik_isimler,
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
        satirlar.append(f"  {sira}. slayt — {'; '.join(ayrinti)}")

    if not satirlar:
        return "", 0

    return (
        "⚠️ KAYNAKTA DOĞRULANAMAYAN AYRINTILAR\n"
        + "\n".join(satirlar)
        + "\n(Yuvarlama da olabilir — ilgili slaytın kaynak metnine bak.)"
    ), len(satirlar)
