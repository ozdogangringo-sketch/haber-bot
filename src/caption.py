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
    Son dakika ve tekil post açıklaması — Taranabilir Mini Bülten Formatı.
    """
    h_dict = dict(haber)
    sonuclar = sonuclar or []
    f = (ayarlar or {}).get("icerik_filtresi", {})

    baslik = (h_dict.get("ig_baslik") or h_dict.get("baslik_orj") or "").strip()
    govde = (h_dict.get("ig_caption") or h_dict.get("slayt_ozet") or "").strip()
    sana_etkisi = (h_dict.get("sana_etkisi") or h_dict.get("neden_onemli") or "").strip()
    etkilesim = (h_dict.get("etkilesim_sorusu") or "").strip()
    vurgu_sayi = (h_dict.get("vurgu_sayi") or "").strip()
    vurgu_etiket = (h_dict.get("vurgu_etiket") or "").strip()

    if f.get("aktif") and f.get("captionda", True):
        kelimeler = f.get("yumusatilacak", [])
        baslik = filtre.metni_yumusat(baslik, kelimeler)
        govde = filtre.metni_yumusat(govde, kelimeler)
        sana_etkisi = filtre.metni_yumusat(sana_etkisi, kelimeler)

    etiketler = _hashtaglari_birlestir([h_dict])
    if f.get("aktif") and f.get("captionda", True):
        etiketler = filtre.hashtaglari_ele(
            etiketler, f.get("yasakli_hashtagler", [])
        )

    # "SON DAKİKA" ibaresi yalnızca gerçekten olağanüstü olaylarda (9+ puan)
    etiket_esigi = ((ayarlar or {}).get("genel", {})
                    .get("son_dakika_etiket_esigi", 9))
    son_dakika_mi = (h_dict.get("onem_puani") or 0) >= etiket_esigi

    parcalar = []
    if son_dakika_mi:
        parcalar.append("🔴 SON DAKİKA")

    parcalar.append(f"📌 {baslik}")

    if govde:
        parcalar.append(govde)

    if sana_etkisi:
        parcalar.append(f"💡 {sana_etkisi}")

    if etkilesim:
        parcalar.append(f"💬 SİZCE? {etkilesim}")

    kaynak_adi = kaynak_gosterim_adi(h_dict.get("kaynak", ""), ayarlar or {})
    if kaynak_adi:
        parcalar.append(f"Kaynak: {kaynak_adi}")

    atif = atif_bloku(sonuclar)
    if atif:
        parcalar.append(atif)
    if etiketler:
        parcalar.append(" ".join(f"#{e}" for e in etiketler))

    metin = "\n\n".join(p for p in parcalar if p).strip()
    return filtre.markdown_temizle(metin)[:AZAMI_KARAKTER]


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

    sonuc = bas + "\n".join(satirlar) + kuyruk
    return filtre.markdown_temizle(sonuc)


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
    Twitter (X) Flood yapısıyla %100 aynı zengin, numaralı ve kaynaklı metin şablonunu kullanır.
    """
    if not haberler:
        return []

    metinler = twitter_zincir_metinleri(
        haberler, ayarlar=ayarlar, son_dakika=son_dakika, urller=urller
    )

    halkalar = []
    for i, metin in enumerate(metinler):
        url = urller[i] if i < len(urller) else None
        halkalar.append({"metin": metin, "gorsel_url": url})

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

    return filtre.markdown_temizle(metin)


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

    metin = "\n\n".join(p for p in parcalar if p).strip()
    return filtre.markdown_temizle(metin)


def piyasa_bulteni_caption(piyasa_verileri: dict | None, ayarlar: dict | None = None, mod: str = "acilis") -> str:
    """
    Sabah (açılış) ve akşam (kapanış) canlı 2 slaytlık piyasa bülteni için Instagram & Threads caption'ı üretir.
    """
    tarih = tarih_metni()
    if mod == "acilis":
        bas = f"🔔 {tarih} — GÜNE BAŞLARKEN PİYASALAR & BORSA AÇILIŞI"
        alt_mesaj = "📊 Borsa İstanbul seans açılışı, döviz kurları, altın ve küresel piyasalarda günün ilk rakamları."
    else:
        bas = f"🔔 {tarih} — PİYASALARDA GÜN SONU & BORSA KAPANIŞI"
        alt_mesaj = "📊 Borsa İstanbul seans kapanışı, günün kazandıranları, döviz, altın ve küresel piyasalarda gün sonu karnesi."

    piyasa_satirlari = ["📈 Anlık Piyasa Göstergeleri:"]
    if piyasa_verileri:
        if "bist100" in piyasa_verileri:
            b = piyasa_verileri["bist100"]
            piyasa_satirlari.append(f"• BIST 100: {b['fiyat']:,.2f} (%{b['degisim']:+.2f})")
        if "dolar" in piyasa_verileri:
            d = piyasa_verileri["dolar"]
            piyasa_satirlari.append(f"• Dolar/TL: {d['fiyat']:.4f} (%{d['degisim']:+.2f})")
        if "euro" in piyasa_verileri:
            e = piyasa_verileri["euro"]
            piyasa_satirlari.append(f"• Euro/TL: {e['fiyat']:.4f} (%{e['degisim']:+.2f})")
        if "gram_altin" in piyasa_verileri:
            g = piyasa_verileri["gram_altin"]
            piyasa_satirlari.append(f"• Gram Altın: {g['fiyat']:,.2f} ₺ (%{g['degisim']:+.2f})")
        if "bitcoin" in piyasa_verileri:
            btc = piyasa_verileri["bitcoin"]
            piyasa_satirlari.append(f"• Bitcoin: ${btc['fiyat']:,.0f} (%{btc['degisim']:+.2f})")
        if "brent" in piyasa_verileri:
            br = piyasa_verileri["brent"]
            piyasa_satirlari.append(f"• Brent Petrol: ${br['fiyat']:.2f} (%{br['degisim']:+.2f})")

    piyasa_bloku = "\n".join(piyasa_satirlari)
    detay_bloku = "📌 Detaylı BİST 30 hisseleri, ABD teknoloji devleri ve kripto karnesi için kaydırın. 👉"
    etiketler = " ".join(f"#{e}" for e in EKONOMI_HASHTAGLER[:AZAMI_HASHTAG])

    sonuc = f"{bas}\n\n{alt_mesaj}\n\n{piyasa_bloku}\n\n{detay_bloku}\n\n{etiketler}".strip()
    return filtre.markdown_temizle(sonuc)


def piyasa_twitter_metni(piyasa_verileri: dict | None, ayarlar: dict | None = None, mod: str = "acilis") -> str:
    """
    X (Twitter) için 280 karakterlik açılış/kapanış piyasa bülteni metni üretir.
    """
    tarih = tarih_metni()
    baslik = "🔔 Borsa Açılış Raporu" if mod == "acilis" else "🔔 Borsa Kapanış Raporu"
    
    satirlar = [f"{baslik} ({tarih})"]
    if piyasa_verileri:
        if "bist100" in piyasa_verileri:
            b = piyasa_verileri["bist100"]
            satirlar.append(f"📈 BIST 100: {b['fiyat']:,.0f} (%{b['degisim']:+.2f})")
        if "dolar" in piyasa_verileri:
            d = piyasa_verileri["dolar"]
            satirlar.append(f"💵 Dolar: {d['fiyat']:.2f} ₺")
        if "gram_altin" in piyasa_verileri:
            g = piyasa_verileri["gram_altin"]
            satirlar.append(f"🟡 Gram Altın: {g['fiyat']:,.0f} ₺")
        if "bitcoin" in piyasa_verileri:
            btc = piyasa_verileri["bitcoin"]
            satirlar.append(f"₿ BTC: ${btc['fiyat']:,.0f}")

    satirlar.append("#BIST100 #Borsa #Dolar #Altın #DailyBrief")
    metin = "\n".join(satirlar)
    if len(metin) > 280:
        metin = metin[:277] + "…"
    return filtre.markdown_temizle(metin)


def twitter_metni_kur(haber: dict, ayarlar: dict | None = None) -> str:
    """
    X (Twitter) için 280 karakter sınırına tam uyumlu tekil post metni üretir.
    URL link vergisine takılmamak için kaynak metin olarak belirtilir.
    """
    h_dict = dict(haber)
    baslik = (h_dict.get("ig_baslik") or h_dict.get("baslik_orj") or "").strip()
    ozet = (h_dict.get("slayt_ozet") or h_dict.get("ig_caption") or "").strip()
    kaynak = kaynak_gosterim_adi(h_dict.get("kaynak", ""), ayarlar or {})

    simge = "🚨 SON DAKİKA" if h_dict.get("son_dakika") else "📰"
    vurgu_sayi = h_dict.get("vurgu_sayi")
    vurgu_etiket = h_dict.get("vurgu_etiket")

    metin_parcalari = [f"{simge} {baslik}"]

    if ozet and len(ozet) > 10:
        # Özetin ilk 1-2 cümlesi
        ilk_cumle = ozet.split(". ")[0] + "."
        if len(ilk_cumle) > 140:
            ilk_cumle = ilk_cumle[:135] + "…"
        metin_parcalari.append(ilk_cumle)

    if kaynak:
        metin_parcalari.append(f"Kaynak: {kaynak}")

    # Temel etiketler
    kat = h_dict.get("kategori") or "gundem"
    etiket = f"#{kat} #DailyBrief"
    metin_parcalari.append(etiket)

    sonuc = "\n\n".join(metin_parcalari).strip()
    if len(sonuc) > 280:
        sonuc = sonuc[:277] + "…"
    return filtre.markdown_temizle(sonuc)


def twitter_zincir_metinleri(
    haberler: list[dict],
    ayarlar: dict | None = None,
    son_dakika: bool = False,
    urller: list[str] | None = None,
) -> list[str]:
    """
    X (Twitter) için haber turunu veya son dakika detaylarını birbirine bağlı Flood (Thread) metinlerine böler.
    Her halkanın metni ile urller[i] görseli 1-e-1 birebir örtüşür; görsel kayması yaşanmaz.
    """
    if not haberler:
        return []

    halkalar = []
    ilk_h = dict(haberler[0])
    tur_turu = ilk_h.get("tur", "")

    # 1. Durum: Son Dakika çoklu slayt Flood'u
    if son_dakika or bool(ilk_h.get("son_dakika")):
        baslik = (ilk_h.get("ig_baslik") or ilk_h.get("baslik_orj") or "").strip()
        ozet = (ilk_h.get("slayt_ozet") or "").strip()
        kaynak = kaynak_gosterim_adi(ilk_h.get("kaynak", ""), ayarlar or {})

        # 1. Tweet: Manşet & Ana Özet (1. Slayt Görseli ile eşleşir)
        tweet1 = f"🚨 SON DAKİKA | {baslik}\n\n📌 {ozet}"
        if kaynak:
            tweet1 += f"\n\nKaynak: {kaynak}"
        tweet1 += "\n\n🧵 Ayrıntılar zincirimizde 👇"
        if len(tweet1) > 280:
            tweet1 = tweet1[:277] + "…"
        halkalar.append(tweet1)

        # 2..N Tweet: Varsa geniş ayrıntı sayfaları (2..N slayt görselleriyle eşleşir)
        detay = (ilk_h.get("ig_caption") or "").strip()
        if detay and len(detay) > 80:
            paragraflar = [p.strip() for p in detay.split("\n\n") if len(p.strip()) > 30]
            for p in paragraflar[:2]:
                tw_detay = f"🔍 Detay:\n\n{p}"
                if len(tw_detay) > 280:
                    tw_detay = tw_detay[:277] + "…"
                halkalar.append(tw_detay)

        return [filtre.markdown_temizle(h) for h in halkalar]

    # 2. Durum: Ekonomi Turu Flood'u (1. Isı Haritası, 2. Piyasa Tablosu, 3..7 Finans Haberleri)
    if tur_turu == "ekonomi":
        toplam_haber = len(haberler)
        # 1. Halka: Piyasa Isı Haritası Slaytı ile eşleşir
        halkalar.append(
            "📊 Daily Brief | Piyasa & Ekonomi Turu 🧵\n\n"
            "Borsa İstanbul, döviz, emtia ve küresel piyasalarda anlık görünüm:\n\n"
            "Detaylı borsa karnesi ve günün kritik finans gelişmeleri zincirimizde 👇"
        )
        # 2. Halka: 3 Sütunlu Piyasa Tablosu Slaytı ile eşleşir (eğer 2. slayt varsa)
        if urller and len(urller) >= toplam_haber + 2:
            halkalar.append(
                "📋 Global & Yerel Piyasa Karnesi\n\n"
                "Borsa İstanbul, Wall Street ve Kripto Piyasaları güncel fiyat ve sektör değişim listesi 📈👇"
            )

        # 3..N Halkalar: Finans Haberlerinin kendi slayt görselleriyle eşleşir
        for i, h in enumerate(haberler, start=1):
            h_dict = dict(h)
            baslik = (h_dict.get("ig_baslik") or h_dict.get("baslik_orj") or "").strip()
            ozet = (h_dict.get("slayt_ozet") or h_dict.get("ig_caption") or "").strip()
            kaynak = kaynak_gosterim_adi(h_dict.get("kaynak", ""), ayarlar or {})

            if len(ozet) > 140:
                ozet = ozet[:135] + "…"

            parcalar = [f"{i}/{toplam_haber} 📌 {baslik}"]
            if ozet:
                parcalar.append(ozet)
            if kaynak:
                parcalar.append(f"Kaynak: {kaynak}")

            metin = "\n\n".join(parcalar)
            if len(metin) > 280:
                metin = metin[:277] + "…"
            halkalar.append(metin)

        return [filtre.markdown_temizle(h) for h in halkalar]

    # 3. Durum: Genel Gündem Turu (10 Haber)
    # Her tweet tam 1 habere ve onun slayt görseline (1..10) 1-e-1 karşılık gelir.
    toplam = len(haberler)
    for i, h in enumerate(haberler, start=1):
        h_dict = dict(h)
        baslik = (h_dict.get("ig_baslik") or h_dict.get("baslik_orj") or "").strip()
        ozet = (h_dict.get("slayt_ozet") or h_dict.get("ig_caption") or "").strip()
        kaynak = kaynak_gosterim_adi(h_dict.get("kaynak", ""), ayarlar or {})

        if len(ozet) > 135:
            ozet = ozet[:130] + "…"

        if i == 1:
            parcalar = [f"🗞️ Daily Brief | 1/{toplam} 📌 {baslik}"]
        else:
            parcalar = [f"{i}/{toplam} 📌 {baslik}"]

        if ozet:
            parcalar.append(ozet)
        if kaynak:
            parcalar.append(f"Kaynak: {kaynak}")

        if i == 1:
            parcalar.append(f"🧵 Günün {toplam} kritik gelişmesi zincirimizde 👇")

        metin = "\n\n".join(parcalar)
        if len(metin) > 280:
            metin = metin[:277] + "…"
        halkalar.append(metin)

    return [filtre.markdown_temizle(h) for h in halkalar]
