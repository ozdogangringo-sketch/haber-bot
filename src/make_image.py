"""
make_image.py — ADIM 3
Haber başlığından 1080x1080 Instagram görseli üretir.

TASARIM KARARLARI:

1) Arka plan AI ile üretiliyor ama SADECE SOYUT.
   Haberin kendisini resmeden fotogerçekçi görsel ÜRETMİYORUZ. Deprem
   haberine AI ile üretilmiş deprem fotoğrafı koyarsak takipçi onu o
   depremin gerçek fotoğrafı sanır — bu uydurma kanıt olur. Adı geçen
   kişilerin görselini üretmek ise doğrudan deepfake alanına girer.
   İstemlerde "no people, no text, no recognisable objects" ısrarla
   tekrarlanıyor. BU KURALI GEVŞETME.

2) Görsel üretimi PARALI (ücretsiz kotası sıfır), metin ücretsiz.
   Bu yüzden iki ayrı anahtar var:
       GEMINI_API_KEY        -> metin, faturasız proje
       GEMINI_IMAGE_API_KEY  -> görsel, faturalı proje
   Faturalandırma proje bazında olduğu için anahtarların FARKLI
   projelerden olması şart, yoksa metin de faturalanmaya başlar.

3) Günlük sayaç var. Gözetimsiz çalışan + kartı bağlı bir botta asıl
   risk faturanın büyüklüğü değil, bir döngü hatasının gece boyunca
   binlerce istek atması. Sayaç aşılırsa üretim durur.

4) API patlarsa bedava yedek: Pillow ile gradyan arka plan.
   Görsel üretilemedi diye post kaçmasın.
"""

from __future__ import annotations

import base64
import io
import logging
import os
import random
import re
import time
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import db, fetch_flag

log = logging.getLogger(__name__)
load_dotenv()

KOK = Path(__file__).resolve().parent.parent
FONT_YOLU = KOK / "assets" / "fonts" / "Inter-Variable.ttf"
CIKTI_KLASORU = KOK / "data" / "output"

UC_NOKTA = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

GECICI_HATALAR = {429, 500, 502, 503, 504}

# Inter değişken fontunun eksen sırası: [Optical size, Weight]
EKSEN_BASLIK = [32.0, 800.0]      # kalın, büyük punto için
EKSEN_OZET = [20.0, 450.0]        # başlık altı özet — ince, okunur
EKSEN_KUCUK = [14.0, 600.0]       # alt bilgi satırı

# Kategoriye göre renk paleti + arka plan istemi.
# Hepsi soyut; hiçbiri olay resmetmiyor.
PALETLER = {
    "turkiye": [
        ("koyu lacivert", "Deep navy blue and charcoal with a subtle diagonal "
                          "light sweep and soft grain, one muted amber accent line"),
        ("koyu bordo", "Dark burgundy and warm charcoal with soft concentric "
                       "curves and fine grain, one muted gold accent line"),
        ("koyu yesil", "Deep forest green and near-black with a faint diagonal "
                       "gradient and soft grain, one muted brass accent line"),
    ],
    "dunya": [
        ("koyu mor", "Deep indigo and near-black with a soft radial glow and "
                     "fine grain, one muted silver accent line"),
        ("koyu petrol", "Dark teal and charcoal with a faint grid and soft "
                        "gradient, one muted copper accent line"),
    ],
}

ISTEM_SABLONU = (
    "Abstract background for a news graphic, vertical format. "
    "{palet}. "
    "Strictly abstract: no people, no faces, no text, no letters, no numbers, "
    "no logos, no flags, no maps, no buildings, no recognisable objects. "
    "Flat editorial poster design, not photorealistic. "
    "The centre must stay calm, dark and uncluttered so that large white "
    "headline text placed on top remains fully readable."
)


# ----------------------------------------------------------------------
# Maliyet emniyeti
# ----------------------------------------------------------------------

def _gunluk_sayac_artir(con, azami: int) -> int:
    """
    Bugün kaç görsel ürettik? Sınırı aşarsak hata fırlatır.

    Sayaç `ayarlar` tablosunda duruyor ve tarih değişince sıfırlanıyor.
    GitHub Actions runner'ı her seferinde sıfırdan başladığı için sayacı
    bellekte tutmak işe yaramaz — veritabanında olmak zorunda.
    """
    bugun = date.today().isoformat()
    kayitli_gun = db.ayar_oku(con, "gorsel_sayac_gun")
    sayi = int(db.ayar_oku(con, "gorsel_sayac_adet", 0) or 0)

    if kayitli_gun != bugun:
        sayi = 0                                  # yeni gün, sayaç sıfırlanır

    if sayi >= azami:
        raise RuntimeError(
            f"Günlük görsel üretim sınırına ulaşıldı ({sayi}/{azami}). "
            "Bu bir maliyet emniyeti — config.yaml → gorsel.gunluk_azami"
        )

    db.ayar_yaz(con, "gorsel_sayac_gun", bugun)
    db.ayar_yaz(con, "gorsel_sayac_adet", sayi + 1)
    return sayi + 1


# ----------------------------------------------------------------------
# Arka plan
# ----------------------------------------------------------------------

def _gorsel_anahtari() -> str:
    anahtar = os.getenv("GEMINI_IMAGE_API_KEY", "").strip()
    if not anahtar:
        raise RuntimeError(
            "GEMINI_IMAGE_API_KEY bulunamadı. Görsel üretimi faturalı bir "
            "projeye ait ayrı anahtar istiyor (.env dosyasına ekle)."
        )
    return anahtar


def _en_boy_orani(g: dict) -> str:
    """
    Slayt boyutunu Gemini'nin beklediği "4:5" biçimine çevirir.

    Gemini yalnızca belirli oranları kabul ediyor; en yakınına yuvarlıyoruz.
    Böylece config'de boyut değişirse istem kendiliğinden uyum sağlar.
    """
    destekli = {"1:1": 1.0, "4:5": 0.8, "3:4": 0.75, "9:16": 0.5625,
                "5:4": 1.25, "4:3": 1.333, "16:9": 1.778}
    oran = g["genislik"] / g["yukseklik"]
    return min(destekli, key=lambda ad: abs(destekli[ad] - oran))


def arkaplan_uret_ai(kategori: str, ayarlar: dict) -> Image.Image:
    """Gemini'den soyut arka plan ister. Başaramazsa exception fırlatır."""
    g = ayarlar["gorsel"]
    paletler = PALETLER.get(kategori) or PALETLER["turkiye"]
    _, palet = random.choice(paletler)
    istem = ISTEM_SABLONU.format(palet=palet)

    son_hata = None
    for deneme in range(1, g["deneme_sayisi"] + 1):
        try:
            cevap = requests.post(
                UC_NOKTA.format(model=g["model"]),
                headers={"x-goog-api-key": _gorsel_anahtari()},
                json={
                    "contents": [{"parts": [{"text": istem}]}],
                    "generationConfig": {
                        "responseModalities": ["IMAGE"],
                        # Slayt oranı ne ise onu iste. Sabit "1:1" bırakılırsa
                        # kare görsel 4:5'e kırpılıyor ve kenarlardan kayıp
                        # oluyor — üstelik AI'ın kompozisyonu ortaya kurduğu
                        # için tam da vurgulu kısım kesiliyordu.
                        "imageConfig": {"aspectRatio": _en_boy_orani(g)},
                    },
                },
                timeout=g["zaman_asimi"],
            )
        except requests.RequestException as e:
            son_hata = f"{type(e).__name__}: {e}"
            time.sleep(2 * deneme)
            continue

        if cevap.status_code == 200:
            for parca in (
                cevap.json().get("candidates", [{}])[0]
                .get("content", {}).get("parts", [])
            ):
                veri = parca.get("inlineData") or parca.get("inline_data")
                if veri:
                    ham = base64.b64decode(veri["data"])
                    return Image.open(io.BytesIO(ham)).convert("RGB")
            son_hata = "cevapta görüntü yok"
            break

        son_hata = f"HTTP {cevap.status_code}: {cevap.text[:200]}"
        if cevap.status_code in GECICI_HATALAR:
            time.sleep(2 * deneme)
            continue
        break

    raise RuntimeError(f"arka plan üretilemedi: {son_hata}")


def arkaplan_uret_yedek(
    kategori: str, genislik: int, yukseklik: int
) -> Image.Image:
    """
    API'siz, bedava gradyan arka plan.

    İki yerde kullanılıyor:
      1. Haber slaytlarında fotoğraf bulunamazsa (asıl kullanım —
         maliyeti burada kısıyoruz)
      2. AI kapak üretimi patlarsa yedek olarak
    """
    renkler = {
        "turkiye": ((16, 24, 46), (38, 50, 82)),
        "dunya": ((26, 18, 40), (58, 42, 74)),
    }
    ust, alt = renkler.get(kategori, renkler["turkiye"])

    gorsel = Image.new("RGB", (genislik, yukseklik), ust)
    ciz = ImageDraw.Draw(gorsel)
    for y in range(yukseklik):
        oran = y / yukseklik
        ciz.line(
            [(0, y), (genislik, y)],
            fill=(
                int(ust[0] + (alt[0] - ust[0]) * oran),
                int(ust[1] + (alt[1] - ust[1]) * oran),
                int(ust[2] + (alt[2] - ust[2]) * oran),
            ),
        )
    return gorsel.filter(ImageFilter.GaussianBlur(1))


# ----------------------------------------------------------------------
# Yazı katmanı
# ----------------------------------------------------------------------

def _buyuk_harf(metin: str) -> str:
    """
    Türkçeye uygun büyük harf çevirimi.

    Python'un `.upper()` metodu 'i' harfini 'I' yapıyor, oysa Türkçede
    doğrusu 'İ'. İlk denemede ülke adı "TÜRKIYE" çıktı — bir haber
    hesabında bu hatayı yapmak kötü görünür. Aynı şekilde 'ı' da 'I'
    olmalı, Python bunu zaten doğru yapıyor ama açıkça yazmak
    davranışı ileride tahmin edilebilir kılıyor.
    """
    return metin.replace("i", "İ").replace("ı", "I").upper()


def _font(punto: int, eksenler: list[float]) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT_YOLU), punto)
    try:
        f.set_variation_by_axes(eksenler)
    except Exception:
        pass            # değişken font desteği yoksa varsayılan ağırlıkla devam
    return f


def _satirlara_bol(metin: str, font, azami_genislik: int, ciz) -> list[str]:
    """Kelime kelime ilerleyip satır genişliğini aşmadan böler."""
    satirlar, gecerli = [], ""
    for kelime in metin.split():
        aday = f"{gecerli} {kelime}".strip()
        if ciz.textlength(aday, font=font) <= azami_genislik:
            gecerli = aday
        else:
            if gecerli:
                satirlar.append(gecerli)
            gecerli = kelime
    if gecerli:
        satirlar.append(gecerli)
    return satirlar


# ⚠️ BAŞLIK PUNTO TAVANI — 96'dan 80'e indirildi (18 Ağu 2026).
#
# 96 tavanla ölçüldü: bir turdaki 10 başlığın 8'i altı satırı doldurup
# 640-700 px kaplıyordu, yani slaytın yarısını. Yazı alanı büyüdükçe
# okuma perdesi de büyüyor ve arka plandaki fotoğraf neredeyse tamamen
# örtülüyordu — kullanıcının şikâyeti buydu.
#
# Ölçüm (aynı 10 başlık, ortalama kapladığı yükseklik):
#     96 -> 643 px  (8/10 başlık altı satır)
#     88 -> 556 px  (5/10)
#     80 -> 446 px  (1/10)
#     72 -> 374 px  (0/10)   <- seçilen
#
# 72'ye inildi (18 Ağu, kullanıcı isteği): başlık artık düz renk şeridin
# değil fotoğrafın üstünde duruyor, yer kapladıkça fotoğrafı örtüyor.
# Daha aşağı inilmedi — manşetin uzaktan okunabilmesi bu tasarımın temel
# şartı, slayt kaydırılırken haber ÖĞRENİLMİŞ olmalı.
BASLIK_PUNTO_TAVAN = 72


def _basligi_yerlestir(metin: str, ciz, alan_genislik: int, alan_yukseklik: int):
    """
    Başlığı alana sığdıran en büyük puntoyu bulur.
    Büyükten küçüğe deniyoruz: başlık kısaysa iri, uzunsa küçük olsun.
    """
    for punto in range(BASLIK_PUNTO_TAVAN, 39, -4):
        font = _font(punto, EKSEN_BASLIK)
        satirlar = _satirlara_bol(metin, font, alan_genislik, ciz)
        satir_yuksekligi = int(punto * 1.22)
        toplam = satir_yuksekligi * len(satirlar)
        if toplam <= alan_yukseklik and len(satirlar) <= 6:
            return font, satirlar, satir_yuksekligi

    # Buraya düşerse başlık aşırı uzun — en küçük puntoyla kırpıyoruz
    font = _font(40, EKSEN_BASLIK)
    satirlar = _satirlara_bol(metin, font, alan_genislik, ciz)[:6]
    return font, satirlar, int(40 * 1.22)


def _ozeti_yerlestir(metin: str, ciz, alan_genislik: int, azami_satir: int = 4):
    """
    Başlık altındaki özet satırını böler. Başlıktan farklı olarak punto
    sabit: özet her slaytta aynı boyda olmalı, yoksa carousel kayarken
    yazı boyu zıplıyor gibi görünür.
    """
    font = _font(34, EKSEN_OZET)
    satirlar = _satirlara_bol(metin, font, alan_genislik, ciz)
    if len(satirlar) > azami_satir:
        satirlar = satirlar[:azami_satir]
        satirlar[-1] = satirlar[-1].rstrip(" ,;:") + "…"
    return font, satirlar, int(34 * 1.42)


def _perde_taban_alfa(arkaplan: Image.Image, kutu: tuple) -> int:
    """
    Yazının oturacağı kutudaki ortalama parlaklığa bakıp perdenin ne kadar
    koyu olması gerektiğini söyler.

    Neden gerekli: sabit perde her arka planda aynı işi görmüyor. Koyu
    gradyanda gereğinden fazlaydı, açık gri bir duvar fotoğrafında ise
    yetersiz kaldı — ilk denemede başlığın üst satırı fotoğrafın içinde
    eridi. Perdeyi arka plana göre ayarlamak bunu kökten çözüyor.
    """
    parca = arkaplan.convert("L").crop(kutu)
    ortalama = sum(parca.get_flattened_data()) / max(1, parca.width * parca.height)
    # Ölçüldü: gradyan arka planın yazı bölgesi ~43, açık bir portre ~123.
    # 55'in altı zaten yeterince koyu, orada perde çizmek gradyanın üstünde
    # görünür bir bant bırakıyordu — o yüzden 0'a düşüyor.
    #   43  -> 0    (gradyan: perde yok, temiz kalır)
    #   123 -> 130  (portre: başlık ayrışır)
    #   200 -> 232  (parlak arka plan: güçlü perde)
    return max(0, min(245, int((ortalama - 55) * 1.63)))


def fotograftan_arkaplan(
    foto: Image.Image, genislik: int, yukseklik: int
) -> Image.Image:
    """
    Commons'tan gelen fotoğrafı slayt oranına kırpar.

    Kırpma ÜSTTEN hizalı: portrelerde yüz genelde üst yarıda oluyor,
    ortadan kırpınca çene kesiliyor. Üstten hizalayınca yüz korunuyor
    ve alt kısım zaten yazı perdesinin altında kalıyor.
    """
    hedef_oran = genislik / yukseklik
    f_genislik, f_yukseklik = foto.size
    foto_oran = f_genislik / f_yukseklik

    if foto_oran > hedef_oran:
        # Fotoğraf çok geniş: yanlardan kırp, ortayı koru
        yeni_genislik = int(f_yukseklik * hedef_oran)
        sol = (f_genislik - yeni_genislik) // 2
        foto = foto.crop((sol, 0, sol + yeni_genislik, f_yukseklik))
    else:
        # Fotoğraf çok uzun: alttan kırp, üstü (yüzü) koru
        yeni_yukseklik = int(f_genislik / hedef_oran)
        ust = int((f_yukseklik - yeni_yukseklik) * 0.12)   # birazcık nefes payı
        foto = foto.crop((0, ust, f_genislik, ust + yeni_yukseklik))

    return foto.resize((genislik, yukseklik), Image.LANCZOS)


def _bayragi_bas(
    gorsel: Image.Image, ulke_kodu: str, ulke_adi: str, kenar: int
) -> Image.Image:
    """
    Sağ üst köşeye ülke flaması basar: sağ kenara yapışık, sol ucu
    kırlangıç kuyruğu (içe doğru V çentik).

    NEDEN FLAMA, DÜZ BAYRAK DEĞİL:
        Önce bayrağı düz bir dikdörtgen olarak basıp altına ülke adı
        yazmıştık; sade kaldı ve açık fotoğraflarda yazı zeminden zor
        ayrıldı. Flamanın kendi koyu zemini olduğu için hem her arka
        planda aynı netlikte okunuyor hem de üst şeride karakter katıyor.

    Yükseklik SABİT, genişlik değişken:
        Bayrak oranları ülkeye göre farklı (İsviçre kare, Nepal üçgen).
        Genişliği sabitleseydik bazı bayraklar ezilirdi. Bunun yerine
        bayrak yüksekliğini sabitleyip genişliği orana göre hesaplıyoruz;
        flama da içeriğe göre uzuyor.

    Görüntüyü DEĞİŞTİRİP döner (alpha_composite yeni nesne üretiyor).
    """
    bayrak = fetch_flag.bayrak_al(ulke_kodu)
    if bayrak is None:
        return gorsel

    b_yuk = 54
    b_gen = max(1, int(bayrak.width * b_yuk / bayrak.height))
    bayrak = bayrak.resize((b_gen, b_yuk), Image.LANCZOS)
    kose_maske = Image.new("L", (b_gen, b_yuk), 0)
    ImageDraw.Draw(kose_maske).rounded_rectangle(
        [0, 0, b_gen - 1, b_yuk - 1], radius=5, fill=255
    )
    bayrak.putalpha(kose_maske)

    font = _font(19, EKSEN_KUCUK)
    metin = _buyuk_harf(ulke_adi or "")
    olcum = ImageDraw.Draw(gorsel)
    metin_genislik = olcum.textlength(metin, font=font) if metin else 0

    # Dikey istif: bayrak üstte, ülke adı altında. Flamanın genişliğini
    # ikisinden hangisi genişse o belirliyor — "Çin" ile "Birleşik Krallık"
    # aynı şablonda düzgün otursun diye.
    ust_pay, ara, alt_pay = 9, 6, 9
    yazi_yuk = 19 if metin else 0
    icerik_gen = int(max(b_gen, metin_genislik))
    yukseklik = ust_pay + b_yuk + (ara + yazi_yuk if metin else 0) + alt_pay

    uc_payi = 38                      # sol uçtaki V çentik için ayrılan yer
    ic_sol, ic_sag = 22, 28
    genislik = uc_payi + ic_sol + icerik_gen + ic_sag

    x1 = gorsel.width                 # sağ kenara yapışık
    x0 = x1 - genislik
    y0 = kenar - 10
    y1 = y0 + yukseklik
    orta_y = (y0 + y1) / 2

    # Kırlangıç kuyruğu: sol kenarın bir noktası içeri giriyor.
    # Kırılım flamanın geometrik ortasında DEĞİL — bayrakla ülke adı
    # arasındaki boşluğun hizasında. Böylece çentik içerikteki ayrımı
    # takip ediyor; ortada olunca bayrağın üstüne denk gelip keyfi
    # duruyordu. Ülke adı yoksa ortaya düşüyor.
    kirilim_y = (y0 + ust_pay + b_yuk + ara / 2) if metin else orta_y
    nokta = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0 + uc_payi, kirilim_y)]

    golge = Image.new("RGBA", gorsel.size, (0, 0, 0, 0))
    ImageDraw.Draw(golge).polygon(
        [(px, py + 4) for px, py in nokta], fill=(0, 0, 0, 120)
    )
    gorsel = Image.alpha_composite(
        gorsel.convert("RGBA"), golge.filter(ImageFilter.GaussianBlur(9))
    )

    katman = Image.new("RGBA", gorsel.size, (0, 0, 0, 0))
    ImageDraw.Draw(katman).polygon(nokta, fill=(13, 18, 32, 214))
    gorsel = Image.alpha_composite(gorsel, katman).convert("RGB")

    # Bayrak ve yazı, içerik alanında yatayda ortalanıyor
    icerik_x = x0 + uc_payi + ic_sol
    gorsel.paste(
        bayrak,
        (int(icerik_x + (icerik_gen - b_gen) / 2), int(y0 + ust_pay)),
        bayrak,
    )

    if metin:
        ImageDraw.Draw(gorsel).text(
            (
                icerik_x + (icerik_gen - metin_genislik) / 2,
                y0 + ust_pay + b_yuk + ara,
            ),
            metin, font=font, fill=(240, 244, 252),
        )
    return gorsel


def yaziyi_bas(
    arkaplan: Image.Image, baslik: str, kaynak: str, ayarlar: dict,
    ozet: str | None = None,
    arsiv_ibaresi: bool = False,
    ulke_kodu: str = "",
    ulke_adi: str = "",
) -> Image.Image:
    """
    Arka planın üstüne başlığı, varsa özeti ve alt bilgiyi yazar.

    SIRA ÖNEMLİ: önce yazının nereye oturacağını ölçüyoruz, perdeyi
    ondan sonra çiziyoruz. Eski hâlinde perde sabit bir orandan (%30)
    başlıyordu ve karesel arttığı için başlığın üst satırları perdenin
    daha şeffaf bölgesine denk geliyordu — açık bir fotoğrafta yazı
    okunmuyordu. Perdeyi yazıya göre konumlandırınca sorun kalmıyor.
    """
    g = ayarlar["gorsel"]
    genislik, yukseklik = g["genislik"], g["yukseklik"]
    kenar = g["kenar_bosluk"]

    # Dikeyde kenara en yakın öğeler (bayrak, kaynak satırı) kırpma
    # riskine karşı içeri alınıyor; yatayda böyle bir kırpma yok.
    dikey_kenar = max(kenar, g.get("dikey_guvenli_pay", kenar))

    gorsel = arkaplan.resize((genislik, yukseklik), Image.LANCZOS)
    ciz = ImageDraw.Draw(gorsel)
    alan_genislik = genislik - 2 * kenar

    # --- 1) Ölçüm: bloklar nereye oturacak? (alttan yukarı doğru) ---
    alt_bilgi_y = yukseklik - dikey_kenar - 34

    ozet_font, ozet_satirlari, ozet_satir_y = None, [], 0
    if ozet:
        ozet_font, ozet_satirlari, ozet_satir_y = _ozeti_yerlestir(
            ozet, ciz, alan_genislik
        )
    ozet_yuksekligi = ozet_satir_y * len(ozet_satirlari)

    # Özet varsa başlığa daha az yer kalıyor — sığdırma buna göre yapılmalı,
    # yoksa ikisi üst üste biner.
    baslik_alani = int(yukseklik * 0.42) - ozet_yuksekligi
    font, satirlar, satir_yuksekligi = _basligi_yerlestir(
        baslik, ciz, alan_genislik, baslik_alani
    )

    ozet_ust = alt_bilgi_y - 44 - ozet_yuksekligi
    baslik_ust = ozet_ust - (26 if ozet else 0) - satir_yuksekligi * len(satirlar)

    # --- 2) Perde: tam olarak yazı bloğunu koruyacak şekilde ---
    taban = _perde_taban_alfa(gorsel, (0, baslik_ust, genislik, yukseklik))

    # Geçiş payı sabit olamaz: perde ne kadar koyuysa yumuşamak için o kadar
    # uzun mesafe gerekiyor. 190 piksel sabitken açık pembe bir arka planda
    # perde düz siyah bir blok gibi başlıyordu.
    perde_basi = max(0, baslik_ust - (190 + taban))

    # ⚠️ RENK ŞERİDİ BAŞLIĞIN ALTINDAN BAŞLIYOR.
    #
    # Şerit önce başlığı da kaplıyordu; okunaklıydı ama fotoğrafın yarıdan
    # fazlasını yutuyordu. Artık yalnızca AÇIKLAMA ve alt bilgi düz renk
    # üstünde; başlık fotoğrafın üstünde duruyor ve okunmayı gölgeden
    # alıyor. Böylece fotoğraf çok daha fazla görünüyor.
    #
    # `taban` yine ölçülüyor ama artık yalnızca geçişin nerede
    # başlayacağını belirliyor: koyu fotoğrafta geçiş erken başlayıp
    # yumuşuyor.
    renk = tuple(g.get("perde_rengi", [22, 18, 46]))
    serit_ust = ozet_ust - 30 if ozet else alt_bilgi_y - 30
    serit_basi = max(0, serit_ust - (150 + taban))

    perde = Image.new("RGBA", (genislik, yukseklik), renk + (0,))
    perde_ciz = ImageDraw.Draw(perde)
    gecis = max(1, serit_ust - serit_basi)
    for y in range(serit_basi, yukseklik):
        if y < serit_ust:
            alfa = int(255 * ((y - serit_basi) / gecis) ** 1.6)
        else:
            alfa = 255
        perde_ciz.line([(0, y), (genislik, y)], fill=renk + (min(255, alfa),))

    gorsel = Image.alpha_composite(gorsel.convert("RGBA"), perde).convert("RGB")
    ciz = ImageDraw.Draw(gorsel)

    # --- 3) Yazı ---
    #
    # ⚠️ BAŞLIK GÖLGESİ GERÇEK BULANIK GÖLGE, tek piksel kaydırma değil.
    # Başlık artık düz renk şeridin değil FOTOĞRAFIN üstünde duruyor;
    # okunması tamamen gölgeye bağlı. Eski 2px kaydırma açık ve kalabalık
    # fotoğraflarda yetmiyordu — harflerin kenarı zemine karışıyordu.
    # Yumuşak gölge, arka plan rengi ne olursa olsun harfi ayırıyor.
    golge = Image.new("RGBA", (genislik, yukseklik), (0, 0, 0, 0))
    golge_ciz = ImageDraw.Draw(golge)
    y = baslik_ust
    for satir in satirlar:
        golge_ciz.text((kenar, y + 3), satir, font=font, fill=(0, 0, 0, 200))
        y += satir_yuksekligi
    golge = golge.filter(ImageFilter.GaussianBlur(9))
    gorsel = Image.alpha_composite(gorsel.convert("RGBA"), golge).convert("RGB")
    ciz = ImageDraw.Draw(gorsel)

    y = baslik_ust
    for satir in satirlar:
        ciz.text((kenar, y), satir, font=font, fill=(255, 255, 255))
        y += satir_yuksekligi

    y = ozet_ust
    for satir in ozet_satirlari:
        ciz.text((kenar, y), satir, font=ozet_font, fill=(220, 226, 238))
        y += ozet_satir_y

    # Kaynak adı — telif değil, şeffaflık için: haber nereden geldi
    kucuk = _font(26, EKSEN_KUCUK)
    alt_metin = _buyuk_harf(kaynak)
    if arsiv_ibaresi:
        # Fotoğraf konuyla ilgili ama o olayın kendisi olmayabiliyor
        # (Commons'ta "Hakan Fidan" araması Brüksel'deki bir toplantıyı
        # getirdi, haber ise Mısır ziyaretiydi). Bunu yazmak hem dürüst
        # hem de "yanlış görsel kullandı" eleştirisine karşı koruma.
        alt_metin += "   ·   ARŞİV GÖRSELİ"
    ciz.text((kenar, alt_bilgi_y), alt_metin, font=kucuk, fill=(198, 206, 222))

    # Sosyal kanal ikonları sağ altta: "bu içerik şu kanallarda da var".
    gorsel = kanal_ikonlari_bas(gorsel, ayarlar, alt_bilgi_y + 13)
    ciz = ImageDraw.Draw(gorsel)

    # Sol üstte ince vurgu çizgisi — hesaba tutarlı bir imza katsın
    ciz.rectangle(
        [kenar, dikey_kenar, kenar + 92, dikey_kenar + 7],
        fill=(226, 170, 88),
    )

    if ulke_kodu:
        gorsel = _bayragi_bas(gorsel, ulke_kodu, ulke_adi, dikey_kenar)

    return gorsel


# ----------------------------------------------------------------------
# Sosyal kanal ikonları
# ----------------------------------------------------------------------
#
# NEDEN ELLE ÇİZİLİYOR:
#   Resmi logolar SVG; Pillow SVG okumuyor ve dönüştürmek sistem
#   bağımlılığı istiyor (GitHub runner'da riskli). Unicode sembolleri
#   de denendi — Inter fontunda yoklar, "NO GLYPH" kutusu çıkıyor.
#
# MARKA NOTU: bunlar resmi logoların birebir kopyası DEĞİL, tanınabilir
# sadeleştirmeler. "Bizi şurada da bulun" amaçlı kullanım nominatif
# kullanım sayılıyor; logoyu değiştirmemek ve kendi markanmış gibi
# göstermemek şartı burada zaten sağlanıyor.

def _ikon_instagram(ciz, x, y, boy, renk):
    """Yuvarlak köşeli kare + mercek + vizör noktası."""
    r = boy // 4
    ciz.rounded_rectangle([x, y, x + boy, y + boy], radius=r,
                          outline=renk, width=max(2, boy // 11))
    m = boy // 4
    ciz.ellipse([x + m, y + m, x + boy - m, y + boy - m],
                outline=renk, width=max(2, boy // 12))
    n = max(2, boy // 10)
    ciz.ellipse([x + boy - m + 1, y + m // 2, x + boy - m + 1 + n,
                 y + m // 2 + n], fill=renk)


def _ikon_x(ciz, x, y, boy, renk):
    """X: iki çapraz kalın çizgi."""
    k = max(2, boy // 8)
    p = boy // 8
    ciz.line([(x + p, y + p), (x + boy - p, y + boy - p)], fill=renk, width=k)
    ciz.line([(x + boy - p, y + p), (x + p, y + boy - p)], fill=renk, width=k)


def _ikon_facebook(ciz, x, y, boy, renk):
    """Daire içinde 'f' — harf fontta var, çizmeye gerek yok."""
    ciz.ellipse([x, y, x + boy, y + boy], outline=renk,
                width=max(2, boy // 11))
    f = _font(int(boy * 0.72), [14.0, 700.0])
    g = ciz.textlength("f", font=f)
    ciz.text((x + (boy - g) / 2, y + boy * 0.12), "f", font=f, fill=renk)


def _ikon_threads(ciz, x, y, boy, renk):
    """
    Threads: üstte sağa, altta sola dolanan iki kavis ve dikey gövde.

    Resmî logo SVG ve Pillow SVG okumuyor; Unicode'da da karşılığı yok
    (ölçüldü, fontta "NO GLYPH" çıkıyor). Diğer ikonlarda olduğu gibi
    tanınabilir bir sadeleştirme çiziliyor. Ayırt edici yanı ilmeğin
    KAPALI OLMAMASI — kapatılırsa "@" işaretine benziyor.
    """
    k = max(2, boy // 10)
    # Alt ilmek: sağ alttan başlayıp sola dolanıyor, sağ tarafı açık.
    ciz.arc([x + boy * 0.16, y + boy * 0.36, x + boy * 0.84, y + boy * 0.96],
            start=300, end=200, fill=renk, width=k)
    # Üst kavis: sola açılıp sağa kıvrılan kanca.
    ciz.arc([x + boy * 0.16, y + boy * 0.04, x + boy * 0.84, y + boy * 0.64],
            start=170, end=40, fill=renk, width=k)
    # Dikey gövde: iki kavsi birleştiriyor, harfi ayakta tutan çizgi.
    ciz.line([(x + boy * 0.5, y + boy * 0.18), (x + boy * 0.5, y + boy * 0.66)],
             fill=renk, width=k)


IKONLAR = {"instagram": _ikon_instagram, "x": _ikon_x,
           "facebook": _ikon_facebook, "threads": _ikon_threads}

# İndirilmiş gerçek logolar (scripts/logo_indir.py). Elle çizim yalnızca
# dosya yoksa devreye giriyor.
LOGO_KLASORU = Path(__file__).resolve().parent.parent / "assets" / "icons"
_logo_onbellek: dict[tuple[str, int], Image.Image] = {}


def _logo_maskesi(ad: str, boy: int):
    """
    Logonun alfa kanalını maske olarak döner, yoksa None.

    NEDEN MASKE: logolar kendi renklerinde (Instagram gradyanı, Facebook
    mavisi) geliyor ama alt bilgideki her şey tek renk. Alfayı maske alıp
    istediğimiz rengi basınca logo alt bilgiye uyuyor.

    Önbellek: bir turda 10 slayt çiziliyor ve her slayt aynı 4 logoyu
    istiyor; diskten 40 kez okumanın anlamı yok.
    """
    anahtar = (ad, boy)
    if anahtar in _logo_onbellek:
        return _logo_onbellek[anahtar]

    yol = LOGO_KLASORU / f"{ad}.png"
    if not yol.exists():
        return None
    try:
        logo = Image.open(yol).convert("RGBA")
        # En-boy oranı korunuyor: X logosu kare değil (330x299) ve
        # zorla kareye oturtulursa eziliyor.
        oran = min(boy / logo.width, boy / logo.height)
        yeni = (max(1, int(logo.width * oran)), max(1, int(logo.height * oran)))
        maske = logo.resize(yeni, Image.LANCZOS).split()[-1]
    except Exception as e:
        log.warning("logo okunamadı (%s): %s", ad, e)
        return None

    _logo_onbellek[anahtar] = maske
    return maske


def kanal_ikonlari_bas(gorsel, ayarlar, y_merkez: int, renk=(150, 160, 180)):
    """
    Slaytın alt bilgisine sosyal kanal ikonlarını basar.

    Sağ kenardan başlayıp sola doğru diziliyor; sol tarafta kaynak adı
    duruyor ve ona çarpmaması gerekiyor.

    Önce indirilmiş gerçek logo aranıyor, bulunamazsa elle çizime
    düşülüyor — logo dosyaları silinse bile slayt üretimi durmuyor.
    """
    kanallar = (ayarlar.get("sosyal", {}) or {}).get("kanallar") or []
    if not kanallar:
        return gorsel

    ciz = ImageDraw.Draw(gorsel)
    g = ayarlar["gorsel"]
    boy = g.get("kanal_ikon_boyu", 26)
    ara = boy + 14
    x = g["genislik"] - g["kenar_bosluk"] - boy

    for ad in reversed(kanallar):
        maske = _logo_maskesi(ad, boy)
        if maske is not None:
            # Dikeyde ortala: X logosu kare olmadığı için gerekiyor.
            ust = y_merkez - maske.height // 2
            sol = x + (boy - maske.width) // 2
            gorsel.paste(renk, (sol, ust), maske)
        elif ad in IKONLAR:
            IKONLAR[ad](ciz, x, y_merkez - boy // 2, boy, renk)
        else:
            continue
        x -= ara
    return gorsel


# ----------------------------------------------------------------------
# Story (9:16)
# ----------------------------------------------------------------------

# Story ölçüleri Instagram'ın standardı, config'den gelmiyor: post 4:5,
# story 9:16 ve ikisi aynı anda üretiliyor.
STORY_GENISLIK, STORY_YUKSEKLIK = 1080, 1920

# Story'de üstte profil bilgisi, altta yanıt kutusu var; oralara denk
# gelen içerik ya görünmüyor ya da parmakla kapanıyor.
STORY_GUVENLI_PAY = 260


def story_kapak(
    basliklar: list[str], ayarlar: dict, gun: date | None = None
) -> Image.Image:
    """
    Akşam turunun story'si: günün manşet listesi.

    NEDEN LİSTE: Instagram Graph API story'ye link/sticker eklemeye izin
    vermiyor — "postu gör" diyemiyoruz. O yüzden story tek başına anlamlı
    olmalı: gören kişi postu açmasa bile gündemi öğrenmiş oluyor.

    `kapak_ciz` yerine ayrı fonksiyon çünkü 9:16'nın ihtiyacı farklı:
    dikey alan çok daha uzun (liste ortalanmalı, yoksa arada boşluk
    kalıyor) ve "KAYDIR →" daveti story'de anlamsız.
    """
    genislik, yukseklik = STORY_GENISLIK, STORY_YUKSEKLIK
    kenar = ayarlar["gorsel"]["kenar_bosluk"]

    gorsel = arkaplan_uret_yedek("turkiye", genislik, yukseklik)
    ciz = ImageDraw.Draw(gorsel)
    alan_genislik = genislik - 2 * kenar

    # --- Üst blok ---
    y = STORY_GUVENLI_PAY
    ciz.rectangle([kenar, y, kenar + 92, y + 7], fill=(226, 170, 88))
    ciz.text((kenar, y + 30), tarih_metni(gun),
             font=_font(30, EKSEN_KUCUK), fill=(226, 170, 88))

    b_font = _font(76, EKSEN_BASLIK)
    ciz.text((kenar + 2, y + 76 + 2), "GÜNÜN GÜNDEMİ", font=b_font,
             fill=(0, 0, 0))
    ciz.text((kenar, y + 76), "GÜNÜN GÜNDEMİ", font=b_font,
             fill=(255, 255, 255))
    ust_alt = y + 76 + 96

    # --- Alt bilgi ---
    alt_bilgi_y = yukseklik - STORY_GUVENLI_PAY
    hesap = ayarlar.get("instagram", {}).get("hesap_kullanici_adi", "")

    # --- Manşet listesi: kalan alanda dikeyde ortalı ---
    madde_font = _font(34, EKSEN_OZET)
    satir_y = int(34 * 1.34)
    bloklar = [
        _satirlara_bol(b, madde_font, alan_genislik - 36, ciz)[:2]
        for b in basliklar
    ]

    kullanilabilir = alt_bilgi_y - 40 - ust_alt
    while bloklar:
        toplam = sum(len(x) * satir_y + 20 for x in bloklar)
        if toplam <= kullanilabilir:
            break
        bloklar.pop()          # sığmayan en az önemli maddeden atıyoruz

    toplam = sum(len(x) * satir_y + 20 for x in bloklar)
    y = ust_alt + max(0, (kullanilabilir - toplam) // 2)

    for satirlar in bloklar:
        ciz.ellipse([kenar, y + 14, kenar + 10, y + 24], fill=(226, 170, 88))
        for satir in satirlar:
            ciz.text((kenar + 28, y), satir, font=madde_font,
                     fill=(226, 231, 242))
            y += satir_y
        y += 20

    if hesap:
        ciz.text((kenar, alt_bilgi_y), f"@{hesap}",
                 font=_font(28, EKSEN_KUCUK), fill=(198, 206, 222))

    gecici = {**ayarlar, "gorsel": {**ayarlar["gorsel"],
              "genislik": genislik, "kenar_bosluk": kenar}}
    gorsel = kanal_ikonlari_bas(gorsel, gecici, alt_bilgi_y + 14)

    return gorsel


def story_haber(
    baslik: str, ozet: str, kaynak: str, ayarlar: dict,
    arkaplan: Image.Image | None = None,
    kategori: str = "turkiye",
    son_dakika: bool = False,
    ulke_kodu: str | None = None,
    ulke_adi: str | None = None,
) -> Image.Image:
    """
    Tek haberin story hâli — son dakika için.

    Fotoğraf verilirse kullanılıyor (son dakika slaytının arka planı),
    yoksa gradyan. Yerleşim `yaziyi_bas` ile aynı mantıkta ama story
    ölçüsünde ve daha geniş güvenli payla.
    """
    story_ayarlar = {
        **ayarlar,
        "gorsel": {
            **ayarlar["gorsel"],
            "genislik": STORY_GENISLIK,
            "yukseklik": STORY_YUKSEKLIK,
            "dikey_guvenli_pay": STORY_GUVENLI_PAY,
        },
    }

    if arkaplan is None:
        arkaplan = arkaplan_uret_yedek(kategori, STORY_GENISLIK, STORY_YUKSEKLIK)
    else:
        arkaplan = fotograftan_arkaplan(
            arkaplan, STORY_GENISLIK, STORY_YUKSEKLIK
        )

    gorsel = yaziyi_bas(
        arkaplan, baslik, kaynak, story_ayarlar,
        ozet=ozet or None,
        arsiv_ibaresi=False,
        ulke_kodu=ulke_kodu,
        ulke_adi=ulke_adi,
    )

    if son_dakika:
        ciz = ImageDraw.Draw(gorsel)
        kenar = ayarlar["gorsel"]["kenar_bosluk"]
        f = _font(26, EKSEN_KUCUK)
        etiket = "SON DAKİKA"
        g = ciz.textlength(etiket, font=f)
        y = STORY_GUVENLI_PAY
        ciz.rectangle([kenar, y, kenar + g + 30, y + 46], fill=(198, 60, 52))
        ciz.text((kenar + 15, y + 10), etiket, font=f, fill=(255, 255, 255))

    return gorsel


# ----------------------------------------------------------------------
# Son dakika: detay slaytı
# ----------------------------------------------------------------------

# Detay sayfasında sabit punto: 40 puntoda sayfa başına ~75 kelime
# sığıyor (ölçüldü). Puntoyu metne göre küçültmek yerine SAYFA EKLİYORUZ
# — 28 puntoya inen bir slayt telefonda okunmuyor ve carousel'de zaten
# 10 slayt hakkımız var.
DETAY_PUNTO = 37

# Giriş ("spot") paragrafı daha iri: slaytta ilk göze çarpan şey o olmalı.
# Gazete düzeninden alınma — düz tek blok metin telefonda duvar gibi
# görünüyor ve kaydırılıp geçiliyor.
DETAY_SPOT_PUNTO = 46

# Paragraflar arası nefes payı (piksel)
PARAGRAF_ARASI = 24

# Vurgu bloklarının puntoları
VURGU_SAYI_PUNTO = 92      # iri rakam — sayfanın çapası
VURGU_ETIKET_PUNTO = 30    # rakamın altındaki açıklama
ALINTI_PUNTO = 40

# Son dakika postu en fazla kaç detay sayfası taşısın.
# 1 haber + 4 detay = 5 slayt. Daha uzunu kaydırılmıyor.
AZAMI_DETAY_SAYFA = 4


def detay_sayfalara_bol(
    detay: str, ayarlar: dict,
    vurgu: tuple[str, str] | None = None,
    alinti: tuple[str, str] | None = None,
) -> list[list[dict]]:
    """
    Detay metnini paragraflara ayırıp sayfalara dağıtır.

    Dönen yapı: sayfa listesi; her sayfa paragraf bloklarından oluşuyor:
        [{"satirlar": [...], "spot": bool}, ...]

    NEDEN PARAGRAF: tek blok düz metin slaytta duvar gibi görünüyor ve
    kaydırılıp geçiliyor. Paragraf araları nefes veriyor, ilk paragraf
    iri puntoyla basılınca göz oraya takılıyor (gazetedeki "spot").

    Punto sabit; metin uzunsa SAYFA ekleniyor. Tersi (puntoyu küçültmek)
    denenip bırakıldı — uzun metinde 28 puntoya inip okunmaz oluyordu.

    Paragraf ortasından bölmemeye çalışıyoruz: sığmayan paragraf bir
    sonraki sayfaya iniyor. Tek başına bir sayfayı aşan paragraf
    kaçınılmaz olarak bölünüyor.
    """
    g = ayarlar["gorsel"]
    genislik, yukseklik = g["genislik"], g["yukseklik"]
    kenar = g["kenar_bosluk"]
    dikey_kenar = max(kenar, g.get("dikey_guvenli_pay", kenar))

    olcu = ImageDraw.Draw(Image.new("RGB", (genislik, yukseklik)))
    alan = genislik - 2 * kenar

    ust_blok = dikey_kenar + 76 + 3 * int(46 * 1.2) + 62
    kullanilabilir = (yukseklik - dikey_kenar - 34 - 40) - ust_blok

    paragraflar = [p.strip() for p in re.split(r"\n\s*\n", detay or "")
                   if p.strip()]
    if not paragraflar and not vurgu and not alinti:
        return [[]]

    bloklar = []

    # Vurgu rakamı en başta: sayfanın çapası, ilk göze çarpan şey.
    if vurgu and vurgu[0]:
        # Rakam uzunsa puntoyu düşür: "828 yıldan 2.352 yıla" gibi uzun
        # ifadeler 92 puntoda sağa taşıyordu.
        s_punto = VURGU_SAYI_PUNTO
        for aday in (VURGU_SAYI_PUNTO, 76, 64, 54, 46):
            if olcu.textlength(vurgu[0], font=_font(aday, EKSEN_BASLIK)) <= alan:
                s_punto = aday
                break
        else:
            s_punto = 46
        bloklar.append({
            "tip": "sayi", "sayi": vurgu[0], "etiket": vurgu[1] or "",
            "punto": s_punto, "satirlar": [],
            "yukseklik": int(s_punto * 1.15) + int(VURGU_ETIKET_PUNTO * 1.7),
        })

    # Her paragrafı satırlara böl. İlki spot: daha iri punto.
    for i, metin in enumerate(paragraflar):
        spot = (i == 0)
        punto = DETAY_SPOT_PUNTO if spot else DETAY_PUNTO
        font = _font(punto, EKSEN_OZET)
        satirlar = _satirlara_bol(metin, font, alan, olcu)
        yukseklik_px = int(punto * 1.5) * len(satirlar)
        bloklar.append({"tip": "metin", "satirlar": satirlar, "spot": spot,
                        "yukseklik": yukseklik_px})

    # Alıntı en sonda: paragrafları okuduktan sonra gelen kapanış.
    if alinti and alinti[0]:
        a_font = _font(ALINTI_PUNTO, EKSEN_OZET)
        a_satirlar = _satirlara_bol(f"“{alinti[0]}”", a_font, alan - 40, olcu)
        bloklar.append({
            "tip": "alinti", "satirlar": a_satirlar,
            "sahibi": alinti[1] or "", "spot": False,
            "yukseklik": int(ALINTI_PUNTO * 1.45) * len(a_satirlar) + 54,
        })

    # VURGU + İLK PARAGRAF BİRLİKTE SIĞMALI.
    # Ayrılırlarsa vurgu tek başına sayfayı işgal ediyor ve altta koca
    # bir boşluk kalıyor (17 Ağu 2026'da yayınlanan slaytta görüldü).
    # Sığmıyorsa spot paragrafın puntosunu düşürüp birleştiriyoruz.
    if len(bloklar) >= 2 and bloklar[0].get("tip") == "sayi":
        ikisi = bloklar[0]["yukseklik"] + PARAGRAF_ARASI + bloklar[1]["yukseklik"]
        for kucuk in (DETAY_PUNTO, 34, 31):
            if ikisi <= kullanilabilir:
                break
            f = _font(kucuk, EKSEN_OZET)
            yeni = _satirlara_bol(paragraflar[0], f, alan, olcu)
            bloklar[1] = {"tip": "metin", "satirlar": yeni, "spot": False,
                          "punto": kucuk,
                          "yukseklik": int(kucuk * 1.5) * len(yeni)}
            ikisi = bloklar[0]["yukseklik"] + PARAGRAF_ARASI + bloklar[1]["yukseklik"]

    # Sayfalara dağıt
    sayfalar, gecerli, dolu = [], [], 0
    for blok in bloklar:
        gerekli = blok["yukseklik"] + (PARAGRAF_ARASI if gecerli else 0)
        # Vurgu bloğu asla tek başına sayfada kalmasın: yanındaki
        # paragrafla birlikte taşınıyor.
        tek_basina_vurgu = (len(gecerli) == 1
                            and gecerli[0].get("tip") == "sayi")
        if gecerli and dolu + gerekli > kullanilabilir and not tek_basina_vurgu:
            sayfalar.append(gecerli)
            gecerli, dolu = [blok], blok["yukseklik"]
        else:
            gecerli.append(blok)
            dolu += gerekli
    if gecerli:
        sayfalar.append(gecerli)

    return sayfalar[:AZAMI_DETAY_SAYFA]


def detay_slayti(
    baslik: str, detay: str, kaynak: str, ayarlar: dict,
    kategori: str = "turkiye",
    son_dakika: bool = True,
    ulke_kodu: str | None = None,
    ulke_adi: str | None = None,
    satirlar: list[dict] | None = None,
    sayfa: int = 1,
    toplam_sayfa: int = 1,
) -> Image.Image:
    """
    Son dakika postunun 2. slaytı: haberin ayrıntısı.

    NEDEN FOTOĞRAF YOK: bu slayt metin ağırlıklı, 60-80 kelime taşıyor.
    Fotoğraf üstüne bu kadar yazı okunmuyor — perde koyulaştıkça fotoğraf
    zaten görünmez oluyor, yani fotoğrafın bir faydası kalmıyor ama
    okunabilirlikten götürüyor. Sade gradyan hem okunaklı hem tutarlı.

    1. slayt dikkat çekiyor, bu slayt bilgi veriyor. İşbölümü bilinçli.
    """
    g = ayarlar["gorsel"]
    genislik, yukseklik = g["genislik"], g["yukseklik"]
    kenar = g["kenar_bosluk"]
    dikey_kenar = max(kenar, g.get("dikey_guvenli_pay", kenar))

    gorsel = arkaplan_uret_yedek(kategori, genislik, yukseklik)
    ciz = ImageDraw.Draw(gorsel)
    alan_genislik = genislik - 2 * kenar

    # Bayrak sağ üstte duruyor; başlık oraya kadar uzarsa altında kalıyor.
    # Etiket olmadığında başlık daha yukarıdan başladığı için çakışma
    # görünür hâle geliyordu — başlık alanını bayrak kadar daraltıyoruz.
    baslik_genislik = alan_genislik - (170 if ulke_kodu else 0)

    # --- Üst: SON DAKİKA etiketi (yalnızca olağanüstü olaylarda) ---
    # Etiket eşiği çağıran tarafta karar veriliyor: tetikleme eşiği 8 ama
    # etiket 9+, yoksa her gün "son dakika" görüp ibare değersizleşiyor.
    if son_dakika:
        etiket_font = _font(24, EKSEN_KUCUK)
        etiket = "SON DAKİKA"
        metin_g = ciz.textlength(etiket, font=etiket_font)
        ciz.rectangle(
            [kenar, dikey_kenar, kenar + metin_g + 28, dikey_kenar + 42],
            fill=(198, 60, 52),
        )
        ciz.text((kenar + 14, dikey_kenar + 9), etiket, font=etiket_font,
                 fill=(255, 255, 255))
        y = dikey_kenar + 76
    else:
        y = dikey_kenar + 10

    # --- Başlık: küçük punto, bu slaytın yıldızı değil ---
    b_font = _font(46, EKSEN_BASLIK)
    b_satirlar = _satirlara_bol(baslik, b_font, baslik_genislik, ciz)[:3]
    for satir in b_satirlar:
        ciz.text((kenar, y), satir, font=b_font, fill=(255, 255, 255))
        y += int(46 * 1.2)

    # --- Ayırıcı çizgi ---
    y += 22
    ciz.rectangle([kenar, y, kenar + 92, y + 5], fill=(226, 170, 88))
    y += 40

    # --- Detay metni: asıl içerik ---
    # Punto SABİT; metin uzunsa sayfa ekleniyor (bkz. detay_sayfalara_bol).
    alt_bilgi_y = yukseklik - dikey_kenar - 34
    kullanilabilir = alt_bilgi_y - 40 - y

    # `satirlar` paragraf blokları listesi: [{"satirlar", "spot"}, ...]
    bloklar = satirlar
    if bloklar is None:
        d_font = _font(DETAY_PUNTO, EKSEN_OZET)
        bloklar = [{"satirlar": _satirlara_bol(detay, d_font, alan_genislik, ciz),
                    "spot": False}]

    toplam = (sum(b.get("yukseklik", 0) for b in bloklar)
              + PARAGRAF_ARASI * max(0, len(bloklar) - 1))

    # Blokları kalan alanda dikeyde ortalıyoruz.
    y += max(0, (kullanilabilir - toplam) // 2)

    for i, b in enumerate(bloklar):
        tip = b.get("tip", "metin")

        if tip == "sayi":
            # İri rakam + altında ne olduğu. Amber renk: sayfadaki tek
            # renkli öğe, göz doğrudan oraya gidiyor.
            punto = b.get("punto", VURGU_SAYI_PUNTO)
            f = _font(punto, EKSEN_BASLIK)
            ciz.text((kenar, y), b["sayi"], font=f, fill=(226, 170, 88))
            y += int(punto * 1.15)
            if b["etiket"]:
                ciz.text((kenar + 4, y), _buyuk_harf(b["etiket"]),
                         font=_font(VURGU_ETIKET_PUNTO, EKSEN_KUCUK),
                         fill=(198, 206, 222))
            y += int(VURGU_ETIKET_PUNTO * 1.7)

        elif tip == "alinti":
            # Sol kenarda dikey çizgi: alıntı olduğu bir bakışta belli.
            f = _font(ALINTI_PUNTO, EKSEN_OZET)
            satir_y = int(ALINTI_PUNTO * 1.45)
            blok_yuk = satir_y * len(b["satirlar"])
            ciz.rectangle([kenar, y, kenar + 5, y + blok_yuk],
                          fill=(226, 170, 88))
            for satir in b["satirlar"]:
                ciz.text((kenar + 26, y), satir, font=f, fill=(240, 244, 252))
                y += satir_y
            if b["sahibi"]:
                ciz.text((kenar + 26, y + 8), f"— {b['sahibi']}",
                         font=_font(28, EKSEN_KUCUK), fill=(198, 206, 222))
            y += 54

        else:
            punto = b.get("punto") or (DETAY_SPOT_PUNTO if b["spot"]
                                       else DETAY_PUNTO)
            f = _font(punto, EKSEN_OZET)
            satir_y = int(punto * 1.5)
            renk = (255, 255, 255) if b["spot"] else (206, 214, 230)
            for satir in b["satirlar"]:
                ciz.text((kenar, y), satir, font=f, fill=renk)
                y += satir_y

        if i < len(bloklar) - 1:
            y += PARAGRAF_ARASI

    # --- Alt bilgi ---
    kucuk = _font(26, EKSEN_KUCUK)
    ciz.text((kenar, alt_bilgi_y), _buyuk_harf(kaynak),
             font=kucuk, fill=(198, 206, 222))

    # Sayfa göstergesi: "2/3". Birden fazla detay sayfası varken
    # takipçinin nerede olduğunu bilmesi gerekiyor.
    if toplam_sayfa > 1:
        gosterge = f"{sayfa}/{toplam_sayfa}"
        gen = ciz.textlength(gosterge, font=kucuk)
        ciz.text((genislik - kenar - gen, alt_bilgi_y), gosterge,
                 font=kucuk, fill=(198, 206, 222))
        # İkonlar sayfa göstergesinin soluna kayıyor, üstüne binmesin.
        gecici = {**ayarlar, "gorsel": {**g,
                  "kenar_bosluk": kenar + int(gen) + 24}}
        gorsel = kanal_ikonlari_bas(gorsel, gecici, alt_bilgi_y + 13)
    else:
        gorsel = kanal_ikonlari_bas(gorsel, ayarlar, alt_bilgi_y + 13)

    if ulke_kodu:
        gorsel = _bayragi_bas(gorsel, ulke_kodu, ulke_adi, dikey_kenar)

    return gorsel


# ----------------------------------------------------------------------
# Kapak slaytı
# ----------------------------------------------------------------------

AYLAR = ["OCAK", "ŞUBAT", "MART", "NİSAN", "MAYIS", "HAZİRAN",
         "TEMMUZ", "AĞUSTOS", "EYLÜL", "EKİM", "KASIM", "ARALIK"]


def tarih_metni(gun: date | None = None) -> str:
    """
    '15 AĞUSTOS 2026' üretir.

    Python'un locale'ine güvenmiyoruz: GitHub runner'da Türkçe locale
    kurulu değil, `strftime('%B')` orada 'August' döner.
    """
    gun = gun or date.today()
    return f"{gun.day} {AYLAR[gun.month - 1]} {gun.year}"


def kapak_ciz(
    arkaplan: Image.Image,
    ayarlar: dict,
    basliklar: list[str] | None = None,
    ust_yazi: str = "GÜNÜN GÜNDEMİ",
    gun: date | None = None,
) -> Image.Image:
    """
    Carousel'in ilk slaytı.

    `basliklar` verilirse manşetler madde madde listelenir — takipçi
    kaydırmadan önce içeride ne olduğunu görür. Verilmezse sade kapak
    çıkar (sadece tarih + başlık).
    """
    g = ayarlar["gorsel"]
    genislik, yukseklik = g["genislik"], g["yukseklik"]
    kenar = g["kenar_bosluk"]

    gorsel = arkaplan.resize((genislik, yukseklik), Image.LANCZOS)
    alan_genislik = genislik - 2 * kenar

    # Kapakta yazı her yere yayıldığı için perde tüm görsele uygulanıyor,
    # haber slaytlarındaki gibi sadece alta değil.
    taban = _perde_taban_alfa(gorsel, (0, 0, genislik, yukseklik))
    if taban > 0:
        perde = Image.new("RGBA", (genislik, yukseklik), (0, 0, 0, int(taban * 0.85)))
        gorsel = Image.alpha_composite(gorsel.convert("RGBA"), perde).convert("RGB")

    ciz = ImageDraw.Draw(gorsel)

    # --- Üst blok: tarih ---
    ciz.rectangle([kenar, kenar, kenar + 92, kenar + 7], fill=(226, 170, 88))
    ciz.text(
        (kenar, kenar + 34),
        tarih_metni(gun),
        font=_font(30, EKSEN_KUCUK),
        fill=(226, 170, 88),
    )

    # --- Ana yazı: tarihin hemen altında, üst blokta ---
    # Haber slaytlarında yazı altta toplanıyor (fotoğrafın yüzünü açıkta
    # bırakmak için), ama kapakta fotoğraf yok. Başlığı da alta koyunca
    # üst yarı tamamen boş kalıyordu; yukarı alınca sayfa dengeleniyor.
    font, satirlar, satir_yuksekligi = _basligi_yerlestir(
        ust_yazi, ciz, alan_genislik, int(yukseklik * 0.26)
    )
    y = kenar + 104
    for satir in satirlar:
        ciz.text((kenar + 2, y + 2), satir, font=font, fill=(0, 0, 0))
        ciz.text((kenar, y), satir, font=font, fill=(255, 255, 255))
        y += satir_yuksekligi
    baslik_alti = y

    # --- Manşet listesi (varsa) — alttan yukarı doğru yerleşiyor ---
    alt_bilgi_y = yukseklik - kenar - 34

    if basliklar:
        madde_font = _font(31, EKSEN_OZET)
        satir_y = int(31 * 1.34)
        bloklar = [
            _satirlara_bol(b, madde_font, alan_genislik - 34, ciz)[:2]
            for b in basliklar
        ]

        # Liste başlığa dayanırsa alttan madde atıyoruz. Manşetler önem
        # sırasında geldiği için kırpılması gereken hep en az önemlisi.
        while bloklar:
            toplam = sum(len(b) * satir_y + 18 for b in bloklar)
            if alt_bilgi_y - 30 - toplam > baslik_alti + 30:
                break
            bloklar.pop()

        y = alt_bilgi_y - 30 - sum(len(b) * satir_y + 18 for b in bloklar)
        for satirlar in bloklar:
            # Küçük amber nokta: madde işareti yerine, listeyi hizalar
            ciz.ellipse(
                [kenar, y + 13, kenar + 9, y + 22], fill=(226, 170, 88)
            )
            for satir in satirlar:
                ciz.text((kenar + 26, y), satir, font=madde_font,
                         fill=(226, 231, 242))
                y += satir_y
            y += 18

    # --- Alt bilgi: hesap adı + kaydırma daveti ---
    kucuk = _font(26, EKSEN_KUCUK)
    hesap = ayarlar.get("instagram", {}).get("hesap_kullanici_adi", "")
    if hesap:
        ciz.text((kenar, alt_bilgi_y), f"@{hesap}", font=kucuk,
                 fill=(198, 206, 222))

    davet = "KAYDIR  →"
    ciz.text(
        (genislik - kenar - ciz.textlength(davet, font=kucuk), alt_bilgi_y),
        davet, font=kucuk, fill=(226, 170, 88),
    )
    return gorsel


def kapak_uret(
    basliklar: list[str],
    ayarlar: dict,
    con=None,
    ai_kullan: bool | None = None,
) -> Path:
    """
    Kapak slaytını üretip diske yazar.

    `ai_kullan` verilmezse config'deki `kapakta_ai` geçerli. AI patlarsa
    ya da günlük sayaç dolmuşsa gradyana düşer — post kaçmasın.
    """
    g = ayarlar["gorsel"]
    CIKTI_KLASORU.mkdir(parents=True, exist_ok=True)
    if ai_kullan is None:
        ai_kullan = g.get("kapakta_ai", True)

    try:
        if not ai_kullan:
            raise RuntimeError("kapakta_ai kapalı")
        if con is not None:
            _gunluk_sayac_artir(con, g["gunluk_azami"])
        arkaplan = arkaplan_uret_ai("turkiye", ayarlar)
        kaynak_tipi = "ai"
    except Exception as e:
        log.info("kapak AI'sız üretiliyor (%s)", e)
        arkaplan = arkaplan_uret_yedek("turkiye", g["genislik"], g["yukseklik"])
        kaynak_tipi = "gradyan"

    gorsel = kapak_ciz(arkaplan, ayarlar, basliklar)
    yol = CIKTI_KLASORU / "kapak.jpg"
    gorsel.save(yol, "JPEG", quality=g["jpeg_kalite"], optimize=True)
    log.info("kapak üretildi (%s): %s", kaynak_tipi, yol)
    return yol


# ----------------------------------------------------------------------
# Ana iş
# ----------------------------------------------------------------------

def gorsel_uret(haber, ayarlar: dict, con=None) -> Path:
    """
    Bir haber için görsel üretip diske yazar, dosya yolunu döner.

    `con` verilirse günlük maliyet sayacı işletilir. Test amaçlı
    çağrılarda None geçilebilir ama üretimde HER ZAMAN verilmeli.
    """
    g = ayarlar["gorsel"]
    CIKTI_KLASORU.mkdir(parents=True, exist_ok=True)

    baslik = haber["ig_baslik"] or haber["baslik_orj"]
    kategori = haber["kategori"]

    try:
        if con is not None:
            _gunluk_sayac_artir(con, g["gunluk_azami"])
        arkaplan = arkaplan_uret_ai(kategori, ayarlar)
        kaynak_tipi = "ai"
    except Exception as e:
        log.warning("AI arka plan olmadı (%s), yedek gradyana düşülüyor", e)
        arkaplan = arkaplan_uret_yedek(kategori, g["genislik"], g["yukseklik"])
        kaynak_tipi = "yedek"

    gorsel = yaziyi_bas(arkaplan, baslik, haber["kaynak"], ayarlar)

    yol = CIKTI_KLASORU / f"haber-{haber['id']}.jpg"
    # Instagram PNG kabul etmiyor — JPEG şart
    gorsel.save(yol, "JPEG", quality=g["jpeg_kalite"], optimize=True)
    log.info("görsel üretildi (%s): %s", kaynak_tipi, yol)
    return yol
