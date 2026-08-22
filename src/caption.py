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
from .make_image import kaynak_gosterim_adi, tarih_metni

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

    # ⚠️ SON DAKİKA AÇIKLAMASINDA TARİH YOK.
    # Instagram gönderinin yaşını zaten gösteriyor ve haber o an oluyor;
    # üstüne tarih yazmak hem tekrar hem de aciliyeti zayıflatıyor.
    # Tarih yalnızca AKŞAM TURU açıklamasında var (`caption_kur`), çünkü
    # orada vaat "şu günün gündemi" — tarih bilginin parçası.
    parcalar = [
        "🔴 SON DAKİKA" if son_dakika_mi else "",
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
    baslik: str = "Günün gündemi",
    tarihli: bool = True,
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
    # ⚠️ CANLI SON DAKİKADA TARİH YAZILMIYOR (`tarihli=False`).
    # Threads gönderinin kendi zaman damgasını zaten gösteriyor ("2sa"),
    # üstüne tarih koymak hem tekrar hem de "son dakika" hissini
    # zayıflatıyor. Akşam turunda tarih KALIYOR: orada vaat günlük bir
    # derleme. Arşiv paylaşımında da kalıyor — eski haberi tarihsiz
    # paylaşmak okuyucuya güncel sanıp yanlış bilgi vermek olur.
    bas = (f"{tarih_metni(gun)}  ·  {baslik}\n\n" if tarihli
           else f"{baslik}\n\n")

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

    # Tek haberlik turda (son dakika) numara yazmak tuhaf duruyor:
    # "1." diye başlayan bir liste ama ikinci maddesi yok.
    numarali = len(basliklar) > 1

    satirlar: list[str] = []
    for i, metin in enumerate(basliklar, 1):
        aday = satirlar + [f"{i}. {metin}" if numarali else metin]
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


def threads_halkalari(
    haberler: list,
    urller: list[str],
    son_dakika: bool = False,
    gun: date | None = None,
    ayarlar: dict | None = None,
    tarihli: bool = True,
) -> list[dict]:
    """
    Turu Threads zincirine çevirir: her görsel bir halka.

    `[{"metin": str, "gorsel_url": str}, ...]` döner; ilk eleman ana
    gönderi, kalanlar sırayla ona zincirlenecek yanıtlar.

    ANA HALKA akışta görünen tek gönderi: tarih + ilk manşet + hashtag.
    Hashtag'i sonraki halkalara koymanın anlamı yok, onları yalnızca
    zinciri açan görüyor.

    AKŞAM TURU : her haber kendi slaytıyla bir halka.
    SON DAKİKA : ilk halka haberin kendisi, sonrakiler ayrıntı sayfaları;
                 metinleri `detay_metni` paragraflarından geliyor.

    NEDEN CAROUSEL DEĞİL: Threads metin platformu, 500 karakter sınırı
    var ve uzun anlatım zincirle yapılıyor. 10 slaytlık carousel oranın
    dili değil, üstelik metin de kırpılıyordu.
    """
    ilk_haber = dict(haberler[0]) if haberler else {}
    if ilk_haber.get("tur") == "ekonomi":
        halkalar = [{"metin": "📊 Günün Piyasa Açılışı ve Öne Çıkan Ekonomi Başlıkları", "gorsel_url": urller[0]}]
        for sira, (haber, url) in enumerate(zip(haberler, urller[1:]), start=2):
            manset = (haber["ig_baslik"] or haber["baslik_orj"]).strip()
            halkalar.append({"metin": f"{sira}. {manset}", "gorsel_url": url})
        return halkalar

    if son_dakika:
        # Tarihsiz hâlde başlık tek başına duruyor; kırmızı nokta ve
        # büyük harf onu akışta ayırt edilir kılıyor.
        baslik = "🔴 SON DAKİKA" if not tarihli else "Son dakika"
    else:
        baslik = "Günün gündemi"

    ana_metin = kisa_metin_kur(haberler[:1], THREADS_AZAMI, gun=gun,
                               ayarlar=ayarlar, baslik=baslik,
                               tarihli=tarihli)
    halkalar = [{"metin": ana_metin, "gorsel_url": urller[0]}]

    if son_dakika:
        paragraflar = [p.strip() for p in
                       (haberler[0]["detay_metni"] or "").split("\n\n")
                       if p.strip()]
        # `detay_metni` sonradan eklendi; eski kayıtlarda yok. Metinsiz
        # bir gönderi Threads'te yavan duruyor — orada okunan şey metin.
        if not paragraflar and haberler[0]["ig_caption"]:
            paragraflar = [haberler[0]["ig_caption"].strip()]

        for i, url in enumerate(urller[1:]):
            metin = paragraflar[i] if i < len(paragraflar) else ""
            if not metin:
                continue          # söyleyecek sözü yoksa halka eklemiyoruz
            halkalar.append({"metin": metin, "gorsel_url": url})
    else:
        for sira, (haber, url) in enumerate(zip(haberler[1:], urller[1:]),
                                            start=2):
            manset = (haber["ig_baslik"] or haber["baslik_orj"]).strip()
            halkalar.append({"metin": f"{sira}. {manset}", "gorsel_url": url})

    return halkalar


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
        # Besleme adı değil yayın kuruluşu: "AA Ekonomi" -> "AA".
        # Slayttaki alt bilgiyle tutarlı olmalı.
        ad = kaynak_gosterim_adi(haber["kaynak"], ayarlar)
        if ad not in kaynaklar:
            kaynaklar.append(ad)
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


EKONOMI_HASHTAGLER = [
    "ekonomi", "borsa", "bist100", "altın", "dolar",
    "finans", "piyasalar", "gündem", "haber", "türkiye"
]


def ekonomi_caption(
    piyasa_verileri: dict,
    haberler: list,
    sonuclar: list[dict] | None = None,
    ayarlar: dict | None = None,
    gun: date | None = None,
) -> str:
    """
    Ekonomi ve Piyasa Açılış Turunun Instagram caption metnini üretir.
    """
    gun = gun or date.today()
    bas = f"📊 GÜNE BAŞLARKEN PİYASALAR · {tarih_metni(gun)}"

    piyasa_satirlari = []
    if "bist100" in piyasa_verileri:
        b = piyasa_verileri["bist100"]
        f_str = f"{b['fiyat']:,.0f}".replace(",", ".")
        piyasa_satirlari.append(f"• BIST 100: {f_str} (%{b['degisim']:+.2f})")
    if "dolar" in piyasa_verileri:
        d = piyasa_verileri["dolar"]
        piyasa_satirlari.append(f"• Dolar/TL: {d['fiyat']:.2f} ₺ (%{d['degisim']:+.2f})")
    if "euro" in piyasa_verileri:
        e = piyasa_verileri["euro"]
        piyasa_satirlari.append(f"• Euro/TL: {e['fiyat']:.2f} ₺ (%{e['degisim']:+.2f})")
    if "gram_altin" in piyasa_verileri:
        g = piyasa_verileri["gram_altin"]
        f_str = f"{g['fiyat']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        piyasa_satirlari.append(f"• Gram Altın: {f_str} ₺ (%{g['degisim']:+.2f})")
    if "btc" in piyasa_verileri:
        btc = piyasa_verileri["btc"]
        f_str = f"{btc['fiyat']:,.0f}".replace(",", ".")
        piyasa_satirlari.append(f"• Bitcoin: ${f_str} (%{btc['degisim']:+.2f})")
    if "brent" in piyasa_verileri:
        br = piyasa_verileri["brent"]
        piyasa_satirlari.append(f"• Brent Petrol: ${br['fiyat']:.2f} (%{br['degisim']:+.2f})")

    piyasa_bloku = "\n".join(piyasa_satirlari)

    haber_maddeleri = []
    if haberler:
        haber_maddeleri.append("📌 Öne Çıkan Ekonomi Başlıkları:")
        for sira, haber in enumerate(haberler, start=1):
            baslik = (haber["ig_baslik"] or haber["baslik_orj"]).strip()
            haber_maddeleri.append(f"{sira + 1}. {baslik}")

    etiket_listesi = list(EKONOMI_HASHTAGLER)
    for h in haberler:
        ham = h["ig_hashtag"] or "" if "ig_hashtag" in h.keys() else ""
        for et in re.split(r"[,\s]+", ham):
            et = et.strip().lstrip("#")
            if et and et.casefold() not in [x.casefold() for x in etiket_listesi]:
                etiket_listesi.append(et)

    etiketler = " ".join(f"#{e}" for e in etiket_listesi[:AZAMI_HASHTAG])
    atif = atif_bloku(sonuclar or [])

    parcalar = [bas, piyasa_bloku]
    if haber_maddeleri:
        parcalar.append("\n".join(haber_maddeleri))
    if atif:
        parcalar.append(atif)
    if etiketler:
        parcalar.append(etiketler)

    return "\n\n".join(p for p in parcalar if p).strip()
