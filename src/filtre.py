"""
filtre.py — Instagram'ın erişim kısıtlamasına takılan kelimeleri yumuşatır.

NEDEN VAR:
    Instagram belirli kelime ve etiketleri içeren postların erişimini
    sessizce düşürüyor ("shadowban"). Uyarı gelmiyor, sadece kimse
    görmüyor. İçerik üreticileri bunu kelimenin ortasına yıldız koyarak
    aşıyor: "intihar" -> "int*har".

NEDEN LİSTE KISA TUTULDU:
    Aşırı sansürün iki maliyeti var. Birincisi görüntü: bir haber
    hesabında "c*nayet" yazmak amatör duruyor. İkincisi okunabilirlik:
    yıldızlı metin göz yorar ve ciddiyeti düşürür. Instagram haber değeri
    taşıyan içeriğe zaten istisna tanıyor — ölüm, kaza, saldırı gibi
    gündelik haber kelimeleri listede YOK, bilerek.

    Listeye kelime eklemek serbest ama her ekleme bir bedel: config'deki
    yorumları okumadan büyütme.

NEREDE UYGULANIR:
    Varsayılan olarak yalnızca caption ve hashtag'lerde. Slayt
    görsellerindeki başlığa dokunulmuyor: Instagram görsel içindeki
    metni caption kadar agresif taramıyor, ama yıldızlı başlık slaytta
    çok daha göze batıyor. `gorselde: true` yaparsan orada da uygulanır.
"""

from __future__ import annotations

import re

# Yıldız kelimenin İÇİNE konuyor, başına değil: "*intihar" işe yaramıyor,
# "int*har" yarıyor. İkinci sesli harfi yıldızlamak okunabilirliği en az
# bozan yer.
def _yildizla(kelime: str) -> str:
    """Kelimenin ortasına doğru ilk sesliyi yıldızla değiştirir."""
    sesliler = "aeıioöuüAEIİOÖUÜ"
    # Baştan ikinci karakterden itibaren bak: ilk harf kalsın ki kelime
    # tanınabilir olsun ("i*tihar" değil "int*har")
    for i in range(2, len(kelime)):
        if kelime[i] in sesliler:
            return kelime[:i] + "*" + kelime[i + 1:]
    # Sesli bulunamazsa ortadaki harfi yıldızla
    orta = len(kelime) // 2
    return kelime[:orta] + "*" + kelime[orta + 1:]


def metni_yumusat(metin: str, kelimeler: list[str]) -> str:
    """
    Verilen kelimeleri metinde yıldızlı hâle getirir.

    Kelime kökü olarak eşleşiyor: "intihar" kuralı "intiharı",
    "intihara" hâllerini de yakalıyor. Büyük/küçük harf farkı gözetmiyor
    ama kelimenin özgün yazımını koruyor — başlıktaki "İNTİHAR"
    "İNT*HAR" oluyor, "int*har" değil.
    """
    if not metin or not kelimeler:
        return metin

    for kok in kelimeler:
        kok = kok.strip()
        if not kok:
            continue

        def degistir(eslesme: re.Match) -> str:
            bulunan = eslesme.group(0)
            # Yıldızı kökün içine koy, ekleri olduğu gibi bırak
            govde = bulunan[: len(kok)]
            ek = bulunan[len(kok):]
            return _yildizla(govde) + ek

        metin = re.sub(
            rf"\b{re.escape(kok)}\w*",
            degistir,
            metin,
            flags=re.IGNORECASE,
        )

    return metin


def hashtaglari_ele(etiketler: list[str], yasakli: list[str]) -> list[str]:
    """
    Kısıtlı etiketleri listeden tamamen çıkarır.

    Etiketlerde yıldızlama işe yaramıyor: "#int*har" diye bir etiket yok,
    kimse aramıyor, sadece yer kaplıyor. Riskli etiketi yumuşatmak yerine
    atmak doğru — tek bir kısıtlı etiket postun tamamının erişimini
    düşürebiliyor.
    """
    yasakli_kume = {y.strip().casefold().lstrip("#") for y in yasakli if y.strip()}
    return [
        e for e in etiketler
        if e.casefold().lstrip("#") not in yasakli_kume
    ]


def kacislari_coz(metin: str) -> str:
    """
    Modelin ÜRETTİĞİ kaçış dizilerini gerçek karaktere çevirir.

    ⚠️ GERÇEK OLAY (6 Eyl 2026): Gemini `detay_metni` alanında paragraf
    ayracını gerçek satır sonu yerine DÜZ METİN olarak yazıyor —
    "...bulundu.\\n\\nYapılan bilgilendirmede...". JSON çözümlemesi bunu
    DÜZELTMEZ, çünkü ortada bozuk JSON yok: model gerçekten ters bölü
    ve "n" karakterlerini yazmış, `json.loads` da onları sadakatle
    aktarıyor.

    İki zararı birden var: (1) "\\n\\n" slayta HARF HARF basılıyor,
    kullanıcı ekranda görüyor; (2) paragraf bölünmediği için iki
    paragraf tek blok hâline geliyor ve sayfa düzeni bozuluyor.

    ⚠️ Ölçüldü (307 kayıt, 11 metin alanı taranarak): bu sınıfta
    BAŞKA bir şey yok — HTML varlığı (&nbsp;), HTML etiketi, kod bloğu
    işareti, çözülmemiş \\uXXXX, markdown bağlantısı hiç görülmedi.
    Yalnızca `detay_metni` alanında 6 kayıt (%2).
    """
    if not metin or not isinstance(metin, str):
        return metin
    if "\\" not in metin:
        return metin                      # hızlı çıkış: kayıtların %98'i
    return (metin.replace("\\r\\n", "\n")
                 .replace("\\n", "\n")
                 .replace("\\r", "\n")
                 .replace("\\t", " "))


def tipografi_temizle(metin: str) -> str:
    """
    Türkçe tipografi ve sayı standartlarını otomatik temizler:
      * 'bin 410' -> '1.410', '2 bin 410' -> '2.410', 'bin 257' -> '1.257'
      * 'yüzde 25' / 'Yüzde 2,5' -> '%25' / '%2,5'
      * '7,76 TL' -> '7,76 ₺', '90 TL' -> '90 ₺'
      * Bozuk/eksik markdown yıldızlarını ('**95-96 *') düzeltir veya öksüz tek yıldızları temizler.
    """
    if not metin or not isinstance(metin, str):
        return ""

    # 1. 4 basamaklı sayıları rakama dönüştür: '2 bin 410' -> '2.410', 'bin 410' -> '1.410'
    metin = re.sub(r"\b(\d+)\s+bin\s+(\d{3})\b", r"\1.\2", metin)
    metin = re.sub(r"\bbin\s+(\d{3})\b", r"1.\1", metin)

    # 2. Yüzde ifadeleri: 'yüzde 25' -> '%25', 'Yüzde 2,5' -> '%2,5'
    metin = re.sub(r"\b[yY]üzde\s+(\d+(?:,\d+)?)\b", r"%\1", metin)

    # 3. Türk Lirası simgesi: '7,76 TL' -> '7,76 ₺', '90 TL'yi' -> '90 ₺'yi'
    metin = re.sub(r"(\d+(?:,\d+)?)\s*TL\b", r"\1 ₺", metin)

    # 4. Kapanmamış markdown kalıpları: '**95-96 *' -> '**95-96**'
    # ⚠️ `(?<!\w)` SANSÜR YILDIZI İÇİN — aşağıdaki uzun nota bak.
    # Onsuz "**2.544** askeri öl*m" ifadesinde kapanış `**`i ile sansür
    # yıldızı eşleşip "**2.544** askeri öl**m" üretiliyordu: yıldız
    # ikizleniyor ve satırın TÜM kalın/ince yapısı kayıyordu.
    metin = re.sub(r"\*\*([^*]+)\s*(?<!\w)\*(?!\*)", r"**\1**", metin)

    # 5. Öksüz tek yıldızları temizle
    #
    # ⚠️ SANSÜR YILDIZINA DOKUNMA — bu satır aynı dosyadaki
    # `metni_yumusat`ı sessizce iptal ediyordu. O fonksiyon riskli
    # kelimenin ortasındaki sesliyi yıldızla değiştiriyor
    # (öldürdü → öld*rdü); buradaki düz silme yıldızı da götürünce
    # geriye EKSİK HARFLİ bir kelime kalıyordu ve okuyucu sansür değil
    # YAZIM HATASI görüyordu: "ölmünü", "öldrdü", "öl m".
    # ⚠️ Bozulma ÇİZİM anında olduğu için "metinleri yeniden üret"
    # düğmesi bunu ASLA düzeltemiyordu — veritabanındaki metin zaten
    # doğruydu, her yeni çizimde aynı bozulma tekrar oluşuyordu.
    #
    # ⚠️ ÖLÇÜT "İKİ YANINDA HARF" DEĞİL, "SOLUNDA HARF": `_yildizla`
    # ilk iki karakteri koruduğu için sansür yıldızının solunda HER
    # ZAMAN harf var; ama kök sesliyle bitiyorsa yıldız sona düşüyor
    # ("ölü" → "öl*"). İki yanı arayan ölçüt o kelimeyi "öl" yapardı.
    # Öksüz markdown yıldızı ise boşluk ya da satır başı komşusu.
    metin = re.sub(r"(?<!\*)(?<!\w)\*(?!\*)", "", metin)

    return metin


def markdown_temizle(metin: str) -> str:
    """
    Metindeki markdown kalın (**metin**) veya italik (*metin* / _metin_) işaretlerini temizler.
    Instagram, Threads, Twitter gibi düz metin platformları markdown desteklemediği için
    ** işaretlerinin çıplak görünmesini engeller.
    """
    if not metin or not isinstance(metin, str):
        return ""
    # Önce genel tipografiyi düzelt
    metin = tipografi_temizle(metin)
    # **kalın** -> kalın
    metin = re.sub(r"\*\*(.*?)\*\*", r"\1", metin)
    # __kalın__ -> kalın
    metin = re.sub(r"__(.*?)__", r"\1", metin)
    # Markdown başlık işaretleri (örn: '### Başlık' -> 'Başlık', hashtag'leri bozmaz)
    metin = re.sub(r"^#{1,6}\s+", "", metin, flags=re.MULTILINE)
    # `kod` -> kod
    metin = re.sub(r"`(.*?)`", r"\1", metin)
    # Kalan tekil çift yıldızları temizle
    metin = metin.replace("**", "")
    return metin.strip()
