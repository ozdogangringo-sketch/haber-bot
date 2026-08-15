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
