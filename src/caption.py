"""
caption.py — Carousel'in tek açıklama metnini kurar.

NEDEN AYRI MODÜL:
    `ig_caption` her haber için ayrı üretiliyor ama post TEK. 10 haberlik
    bir carousel'in altına 10 ayrı caption koyamayız; hepsini tek metinde
    birleştirmek gerekiyor ve bunun kendi kuralları var.

INSTAGRAM SINIRLARI (ölçüldü, uyulması zorunlu):
    * Caption en fazla 2200 karakter. Aşarsa API hata döndürüyor.
    * En fazla 30 hashtag. Her haberin 5-8 hashtag'i var, 10 haberde
      50-80 eder — birleştirip seçmek şart.
    * İlk ~125 karakterden sonrası "... daha fazla" arkasına gizleniyor.
      O yüzden tarih ve ilk manşet en başta duruyor.

ATIF POLİTİKASI:
    Commons görselleri çoğu zaman CC BY / CC BY-SA lisanslı; atıf vermek
    hukuken ZORUNLU, kısaltılamaz. Pexels lisansı atıf gerektirmiyor, o
    yüzden Pexels satırlarını tek satırda topluyoruz — 9 ayrı "Temsili
    foto: X (Pexels)" satırı 700 karakter yiyordu ve karşılığında hiçbir
    hukuki gereklilik karşılamıyordu.
"""

from __future__ import annotations

import re
from datetime import date

from . import filtre
from .make_image import tarih_metni

AZAMI_KARAKTER = 2200
AZAMI_HASHTAG = 30

# Her postta duran, hesabın kimliğini taşıyan etiketler.
SABIT_HASHTAGLER = ["gündem", "haber", "türkiye", "sondakika", "gününhaberleri"]


def _hashtaglari_birlestir(haberler: list, azami: int = AZAMI_HASHTAG) -> list[str]:
    """
    10 haberin hashtag'lerini tek listede toplar.

    Sıra önemli: önce sabit etiketler, sonra haberler önem sırasında.
    Böylece sınıra dayanınca kırpılan hep en az önemli haberin etiketi
    oluyor. Tekrarlar ayıklanıyor — aynı etiket iki kez yazılırsa
    Instagram ikincisini saymıyor ama yer işgal ediyor.
    """
    goruldu, sonuc = set(), []

    for etiket in SABIT_HASHTAGLER:
        if etiket.casefold() not in goruldu:
            goruldu.add(etiket.casefold())
            sonuc.append(etiket)

    for haber in haberler:
        ham = haber["ig_hashtag"] or ""
        for etiket in re.split(r"[,\s]+", ham):
            etiket = etiket.strip().lstrip("#")
            # Instagram etiketlerde boşluk kabul etmiyor; Gemini ara sıra
            # "trafik cezası" gibi iki kelimelik etiket üretiyor.
            etiket = re.sub(r"[^0-9A-Za-zÇĞİÖŞÜçğıöşü]", "", etiket)
            if not etiket or etiket.casefold() in goruldu:
                continue
            goruldu.add(etiket.casefold())
            sonuc.append(etiket)
            if len(sonuc) >= azami:
                return sonuc

    return sonuc


def atif_bloku(sonuclar: list[dict]) -> str:
    """
    Fotoğraf atıflarını hazırlar.

    Commons atıfları tek tek yazılıyor (CC BY şartı). Pexels'ler tek
    satırda toplanıyor: lisansı atıf istemiyor, ayrı ayrı yazmak sadece
    karakter yiyor.
    """
    commons, pexels_var = [], False

    for s in sonuclar:
        atif = (s.get("atif") or "").strip()
        if not atif:
            continue
        if s.get("katman") == "pexels":
            pexels_var = True
        elif atif not in commons:
            commons.append(atif)

    satirlar = list(commons)
    if pexels_var:
        satirlar.append("Temsili görseller: Pexels")

    return "\n".join(satirlar)


def son_dakika_caption(
    haber, sonuclar: list[dict] | None = None,
    ayarlar: dict | None = None,
) -> str:
    """
    Son dakika postunun açıklaması — tek haber, akşam turundan farklı.

    Akşam turunda 10 manşet listeleniyor; burada tek haber var, o yüzden
    liste yerine haberin kendisi anlatılıyor. Yapı: SON DAKİKA etiketi +
    başlık + açıklama + kaynak + atıf + hashtag.
    """
    sonuclar = sonuclar or []
    f = (ayarlar or {}).get("icerik_filtresi", {})

    baslik = (haber["ig_baslik"] or haber["baslik_orj"] or "").strip()
    govde = (haber["ig_caption"] or haber["slayt_ozet"] or "").strip()

    if f.get("aktif") and f.get("captionda", True):
        kelimeler = f.get("yumusatilacak", [])
        baslik = filtre.metni_yumusat(baslik, kelimeler)
        govde = filtre.metni_yumusat(govde, kelimeler)

    etiketler = _hashtaglari_birlestir([haber])
    if f.get("aktif") and f.get("captionda", True):
        etiketler = filtre.hashtaglari_ele(
            etiketler, f.get("yasakli_hashtagler", [])
        )

    # "SON DAKİKA" ibaresi yalnızca gerçekten olağanüstü olaylarda.
    # Tetikleme eşiği 8 ama etiket eşiği 9: her önemli habere "son
    # dakika" demek ibareyi değersizleştiriyor.
    etiket_esigi = ((ayarlar or {}).get("genel", {})
                    .get("son_dakika_etiket_esigi", 9))
    son_dakika_mi = (haber["onem_puani"] or 0) >= etiket_esigi

    parcalar = [
        (f"🔴 SON DAKİKA · {tarih_metni()}" if son_dakika_mi
         else tarih_metni()),
        baslik,
        govde,
        f"Kaynak: {haber['kaynak']}",
    ]
    atif = atif_bloku(sonuclar)
    if atif:
        parcalar.append(atif)
    if etiketler:
        parcalar.append(" ".join(f"#{e}" for e in etiketler))

    metin = "\n\n".join(p for p in parcalar if p).strip()
    return metin[:AZAMI_KARAKTER]


# Threads'in gönderi sınırı. Instagram'ın 2200'ü buraya SIĞMIYOR.
THREADS_AZAMI = 500


def kisa_metin_kur(
    haberler: list,
    sinir: int,
    gun: date | None = None,
    ayarlar: dict | None = None,
) -> str:
    """
    Dar karakter sınırı olan kanallar için gündemi yeniden kurar.

    ⚠️ KIRPMA DEĞİL, YENİDEN KURMA. Threads'e önce tam caption gönderilip
    `metin[:500]` ile kesiliyordu — 2200 karakterlik bir metni 500'de
    kesmek onu bir haberin ORTASINDA bitiriyor, üstelik caption'ın sonunda
    kaynak ve atıf satırları var, onlar da hiç görünmüyordu.

    Burada sığan kadar manşet alınıyor, sığmayanlar "+N haber daha" diye
    özetleniyor. Öncelik sırası: tarih ve ilk manşetler korunur, hashtag
    en önce feda edilir.

    (Threads için `sinir=THREADS_AZAMI`. X kapatıldı ama `x_paylas` de
     aynı işi 280 ile yapıyor — mantık tek yerde dursun diye burada.)
    """
    bas = f"{tarih_metni(gun)}  ·  Günün gündemi\n\n"

    ham_etiketler = _hashtaglari_birlestir(haberler, azami=3)
    f = (ayarlar or {}).get("icerik_filtresi", {})
    if f.get("aktif") and f.get("captionda", True):
        ham_etiketler = filtre.hashtaglari_ele(
            ham_etiketler, f.get("yasakli_hashtagler", [])
        )
    kuyruk = ("\n\n" + " ".join(f"#{e}" for e in ham_etiketler)
              if ham_etiketler else "")

    basliklar = [(h["ig_baslik"] or h["baslik_orj"]).strip() for h in haberler]
    if f.get("aktif") and f.get("captionda", True):
        kelimeler = f.get("yumusatilacak", [])
        basliklar = [filtre.metni_yumusat(b, kelimeler) for b in basliklar]

    satirlar: list[str] = []
    for i, baslik in enumerate(basliklar, 1):
        aday = satirlar + [f"{i}. {baslik}"]
        if len(bas + "\n".join(aday) + kuyruk) > sinir:
            break
        satirlar = aday

    if not satirlar:
        # Tek manşet bile sığmadı: hashtag'i at, manşeti kısalt.
        tek = basliklar[0] if basliklar else ""
        yer = max(0, sinir - len(bas) - 1)
        return (bas + tek[:yer] + "…")[:sinir]

    kalan = len(basliklar) - len(satirlar)
    if kalan > 0:
        ek = f"\n+{kalan} haber daha"
        if len(bas + "\n".join(satirlar) + ek + kuyruk) <= sinir:
            satirlar.append(ek.strip())

    return bas + "\n".join(satirlar) + kuyruk


def caption_kur(
    haberler: list,
    sonuclar: list[dict] | None = None,
    gun: date | None = None,
    hesap: str = "",
    ayarlar: dict | None = None,
) -> str:
    """
    Carousel'in tam açıklama metnini üretir.

    `haberler` slayt sırasıyla gelmeli — listedeki numaralar slaytlarla
    birebir eşleşiyor, takipçi "3. slayttaki haber" diye bakabilsin.

    2200 karakteri aşarsa sondan kırpıyoruz: önce hashtag'ler, sonra
    atıf bloğu, en son haber listesi. Manşetler en değerli kısım olduğu
    için en son onlara dokunuyoruz.
    """
    sonuclar = sonuclar or []

    bas = f"{tarih_metni(gun)}  ·  Günün gündemi"

    maddeler = [
        f"{sira}. {(haber['ig_baslik'] or haber['baslik_orj']).strip()}"
        for sira, haber in enumerate(haberler, start=1)
    ]

    kaynaklar = []
    for haber in haberler:
        if haber["kaynak"] not in kaynaklar:
            kaynaklar.append(haber["kaynak"])
    kaynak_satiri = "Kaynaklar: " + ", ".join(kaynaklar)

    ham_etiketler = _hashtaglari_birlestir(haberler)

    # İçerik filtresi: kısıtlı etiketleri at, riskli kelimeleri yumuşat.
    # Atıf bloğuna DOKUNULMUYOR — orada fotoğrafçı adı ve lisans var,
    # yıldızlanırsa atıf geçersiz hâle gelir.
    f = (ayarlar or {}).get("icerik_filtresi", {})
    if f.get("aktif") and f.get("captionda", True):
        ham_etiketler = filtre.hashtaglari_ele(
            ham_etiketler, f.get("yasakli_hashtagler", [])
        )
        kelimeler = f.get("yumusatilacak", [])
        maddeler = [filtre.metni_yumusat(m, kelimeler) for m in maddeler]

    etiketler = " ".join(f"#{e}" for e in ham_etiketler)
    atif = atif_bloku(sonuclar)

    def birlestir(maddeler, etiketler, atif) -> str:
        parcalar = [bas, "\n".join(maddeler), kaynak_satiri]
        if atif:
            parcalar.append(atif)
        if etiketler:
            parcalar.append(etiketler)
        return "\n\n".join(p for p in parcalar if p).strip()

    metin = birlestir(maddeler, etiketler, atif)

    # Sınırı aşarsak en az değerli parçadan başlayarak kısıyoruz
    if len(metin) > AZAMI_KARAKTER:
        metin = birlestir(maddeler, "", atif)
    if len(metin) > AZAMI_KARAKTER:
        metin = birlestir(maddeler, "", "")
    while len(metin) > AZAMI_KARAKTER and len(maddeler) > 1:
        maddeler.pop()
        metin = birlestir(maddeler, "", "")

    return metin
