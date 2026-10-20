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
import itertools
import logging
import os
import random
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

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
    kategori: str, genislik: int, yukseklik: int, g: dict | None = None
) -> Image.Image:
    """
    API'siz, bedava gradyan arka plan.

    İki yerde kullanılıyor:
      1. Haber slaytlarında fotoğraf bulunamazsa (asıl kullanım —
         maliyeti burada kısıyoruz)
      2. AI kapak üretimi patlarsa yedek olarak
    """
    # ⚠️ RENK TEK KAYNAKTAN: `gorsel.serit_renkleri`.
    #
    # Gradyanın kendi renk sözlüğü vardı ve şerit paletiyle AYRI
    # tanımlıydı; aynı kategori iki yerde farklı tonda çıkıyor, yeni
    # kategori eklenince biri güncellenip diğeri unutuluyordu. Artık
    # gradyan da şerit renginden türüyor: üst ton renk, alt ton onun
    # açılmış hâli.
    #
    # `g` verilmezse (eski çağrılar) varsayılan palet kullanılıyor.
    palet = (g or {}).get("serit_renkleri") or {}
    taban = palet.get(kategori) or (g or {}).get("perde_rengi") or [22, 18, 46]
    ust = tuple(taban)
    # Alt ton: aynı rengin açılmışı. Sabit bir katsayı yerine toplama
    # kullanıyoruz — çarpım koyu tonlarda neredeyse hiç açmıyor.
    alt = tuple(min(255, k + 34) for k in ust)

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


_FONT_ONBELLEK: dict[tuple[int, tuple[float, ...]], ImageFont.FreeTypeFont] = {}


def _font(punto: int, eksenler: list[float] | tuple[float, ...] | float) -> ImageFont.FreeTypeFont:
    if isinstance(eksenler, (list, tuple)):
        eksen_tuple = tuple(float(x) for x in eksenler)
    else:
        eksen_tuple = (float(eksenler),)
    anahtar = (punto, eksen_tuple)
    f = _FONT_ONBELLEK.get(anahtar)
    if f is not None:
        return f

    f = ImageFont.truetype(str(FONT_YOLU), punto)
    try:
        f.set_variation_by_axes(list(eksen_tuple))
    except Exception:
        pass            # değişken font desteği yoksa varsayılan ağırlıkla devam
    _FONT_ONBELLEK[anahtar] = f
    return f


def _kelimeleri_satir_yap(kelimeler: list[tuple[str, bool]]) -> str:
    """
    Kelimeleri birleştirir; ardışık bold kelimeleri tek bir **word1 word2** içine alır.
    Kesme işareti ve noktalamaları önceki kelimeye boşluksuz bağlar.
    """
    parcalar = []
    bold_grup = []
    for w, is_b in kelimeler:
        if is_b:
            bold_grup.append(w)
        else:
            if bold_grup:
                joined = " ".join(bold_grup)
                parcalar.append(f"**{joined}**")
                bold_grup = []
            parcalar.append(w)
    if bold_grup:
        joined = " ".join(bold_grup)
        parcalar.append(f"**{joined}**")

    satir = ""
    for p in parcalar:
        if not satir:
            satir = p
        elif p.startswith(("'", "’", ",", ".", ":", ";", "!", "?", ")", "]", "”")):
            satir += p
        else:
            satir += f" {p}"
    return satir


UNVAN_VE_KISALTMALAR = {
    "dr.", "dr", "doç.", "doç", "prof.", "prof", "av.", "av", "yrd.", "yrd",
    "uzm.", "uzm", "müh.", "müh", "mim.", "mim", "sn.", "sn", "sayın",
    "gen.", "gen", "alb.", "alb", "bnb.", "bnb", "yzb.", "yzb",
    "tğm.", "tğm", "ütğm.", "ütğm", "astsb.", "astsb",
    "md.", "md", "mad.", "mad", "sf.", "sf", "no.", "no", "nr.", "nr"
}

BUYUKLUK_KELIMELERI = {"bin", "milyon", "milyar", "trilyon"}
PARA_BIRIMLERI = {"₺", "$", "€", "£", "tl", "try", "usd", "eur"}


def _is_para_birimi(w: str) -> bool:
    """Para sembolü, birim veya ekli halini (₺, ₺'ye, TL'de, $'a vb.) tespit eder."""
    if not w:
        return False
    if w.startswith(("₺", "$", "€", "£")):
        return True
    clean = re.sub(r"[^\w₺$€£]", "", w.lower())
    if clean in PARA_BIRIMLERI or any(clean.startswith(p) for p in ("₺", "tl", "try", "usd", "eur")):
        return True
    return bool(re.match(r"^(?:₺|\$|€|£|tl|try|usd|eur)(?:'[\wğüşıöç]+)?$", w, re.IGNORECASE))


def _is_sayi(w: str) -> bool:
    """Sayısal değer veya tutar (2.500, 45,50, 100 vb.) olup olmadığını denetler."""
    if not w:
        return False
    clean = re.sub(r"[\.,]", "", w.strip("*_"))
    return clean.isdigit()


def _is_unvan_veya_on_ek(w: str) -> bool:
    """Unvan, kısaltma veya sıra sayısı (Doç., Dr., Prof., 14. vb.) olup olmadığını denetler."""
    if not w:
        return False
    clean = w.lower().strip("*_()[]")
    if clean in UNVAN_VE_KISALTMALAR:
        return True
    if re.match(r"^\d+\.$", clean):
        return True
    return False


def _satirlara_bol(metin: str, font, azami_genislik: int, ciz) -> list[str]:
    """
    Kelime kelime ilerleyip satır genişliğini aşmadan böler.
    Satır bölünmelerinde **bold** etiketlerinin kopmasını önler.
    ₺ gibi para birimlerinin önceki rakamdan ve unvanların sonraki kelimeden
    kopmasını engelleyen akıllı yapışkanlık (glue) kurallarını uygular.
    """
    if not metin:
        return []

    from . import filtre
    metin = filtre.tipografi_temizle(metin)

    # 1. Regex ile metni (**bold** ve düz) parçala
    pattern = re.compile(r"(\*\*[^*]+\*\*)")
    parts = pattern.split(metin)
    tokens: list[tuple[str, bool]] = []

    for part in parts:
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) >= 4:
            clean_part = part[2:-2]
            for w in clean_part.split():
                if w:
                    tokens.append((w, True))
        else:
            kelimeler_p = part.split()
            if not kelimeler_p:
                continue
            # **dolar**, veya **TCMB**'nin gibi bold kapanışına bitişik noktalama/ek varsa
            # önceki kelimeye yapıştır ki virgül alt satırın başına tek başına düşmesin.
            baslangic_idx = 0
            if tokens and not part[0].isspace():
                tokens[-1] = (tokens[-1][0] + kelimeler_p[0], tokens[-1][1])
                baslangic_idx = 1
            for w in kelimeler_p[baslangic_idx:]:
                if w in {",", ".", ";", ":", "!", "?", ")", "]"} and tokens:
                    tokens[-1] = (tokens[-1][0] + w, tokens[-1][1])
                elif w:
                    tokens.append((w, False))

    if not tokens:
        return []

    # 2. Satırlara böl ve yapışkanlık kurallarını işlet
    satirlar = []
    gecerli_kelimeler = []
    gecerli_str = ""

    for word, bold in tokens:
        aday_str = f"{gecerli_str} {word}".strip()
        if ciz.textlength(aday_str, font=font) <= azami_genislik:
            gecerli_str = aday_str
            gecerli_kelimeler.append((word, bold))
        else:
            tasinanlar = []

            # Kural 1: Para / birim sembolü taşıyorsa önceki rakamı ve büyüklüğü beraberinde çeksin
            if _is_para_birimi(word) and gecerli_kelimeler:
                if (len(gecerli_kelimeler) >= 2
                        and gecerli_kelimeler[-1][0].lower().strip("*") in BUYUKLUK_KELIMELERI
                        and _is_sayi(gecerli_kelimeler[-2][0])):
                    if len(gecerli_kelimeler) > 2:
                        b = gecerli_kelimeler.pop()
                        s = gecerli_kelimeler.pop()
                        tasinanlar = [s, b]
                elif _is_sayi(gecerli_kelimeler[-1][0]):
                    if len(gecerli_kelimeler) > 1:
                        tasinanlar = [gecerli_kelimeler.pop()]

            # Kural 2: Büyüklük (bin, milyon) taşıyorsa önceki sayıyı çeksin
            elif word.lower().strip("*") in BUYUKLUK_KELIMELERI and gecerli_kelimeler:
                if _is_sayi(gecerli_kelimeler[-1][0]) and len(gecerli_kelimeler) > 1:
                    tasinanlar = [gecerli_kelimeler.pop()]

            # Kural 3: Satır sonunda unvan/ön ek kaldıysa (Doç., Dr., 14.), yeni satıra taşınsın
            elif gecerli_kelimeler:
                while len(gecerli_kelimeler) > 1 and _is_unvan_veya_on_ek(gecerli_kelimeler[-1][0]):
                    tasinanlar.insert(0, gecerli_kelimeler.pop())

            if gecerli_kelimeler:
                satirlar.append(_kelimeleri_satir_yap(gecerli_kelimeler))

            gecerli_kelimeler = tasinanlar + [(word, bold)]
            gecerli_str = " ".join(w for w, _ in gecerli_kelimeler)

    if gecerli_kelimeler:
        satirlar.append(_kelimeleri_satir_yap(gecerli_kelimeler))

    return satirlar


def _formatli_satir_ciz(
    ciz: ImageDraw.ImageDraw,
    x: int,
    y: int,
    satir: str,
    punto: int,
    spot: bool = False,
    varsayilan_renk: tuple[int, int, int] | None = None,
) -> None:
    """
    Satırdaki metni çizer; vurgu ve tırnak işaretlerini tipografik olarak işler:
      * Normal metinde **bold** vurgusu -> kalın ve parlak beyaz (veya altın rengi)
      * Spot (kalın) metinde **vurgu** -> normal/ince ağırlık (zıt ağırlık efekti)
      * Tırnak içindeki söylemler "..." veya “...” -> açık parlak beyaz
    """
    base_wght = 750.0 if spot else 450.0
    vurgu_wght = 400.0 if spot else 800.0

    f_norm = _font(punto, [20.0, base_wght])
    f_vurgu = _font(punto, [20.0, vurgu_wght])

    c_norm = varsayilan_renk or ((255, 255, 255) if spot else (206, 214, 230))
    c_vurgu = (226, 170, 88) if spot else (255, 255, 255)
    c_alinti = (245, 248, 255)

    desen = re.compile(r'(\*\*[^*]+\*\*|\"[^\"]+\"|“[^”]+”)')
    cur_x = x
    son = 0
    for m in desen.finditer(satir):
        if m.start() > son:
            t = satir[son:m.start()].replace("**", "")
            ciz.text((cur_x, y), t, font=f_norm, fill=c_norm)
            cur_x += int(ciz.textlength(t, font=f_norm))
        ham = m.group()
        if ham.startswith('**') and ham.endswith('**'):
            t = ham[2:-2].replace("**", "")
            ciz.text((cur_x, y), t, font=f_vurgu, fill=c_vurgu)
            cur_x += int(ciz.textlength(t, font=f_vurgu))
        elif (ham.startswith('"') and ham.endswith('"')) or (ham.startswith('“') and ham.endswith('”')):
            # ⚠️ TIRNAK DALI DA YILDIZI TEMİZLEMELİ (7 Eyl 2026).
            # Desen `**kalın**` ve `"alıntı"` kalıplarını AYNI alternasyonda
            # arıyor; metin `"**Yurt kazandı**"` gibi İÇ İÇE olduğunda tırnak
            # alternatifi kazanıyor ve bu dal `ham`i olduğu gibi çiziyordu.
            # Sonuç slaytta göründü: « " **Yurt kazandı** " ». Kalın dalında
            # `.replace("**","")` vardı, burada yoktu.
            t = ham.replace("**", "")
            ciz.text((cur_x, y), t, font=f_vurgu, fill=c_alinti)
            cur_x += int(ciz.textlength(t, font=f_vurgu))
        son = m.end()
    if son < len(satir):
        t = satir[son:].replace("**", "")
        ciz.text((cur_x, y), t, font=f_norm, fill=c_norm)
        cur_x += int(ciz.textlength(t, font=f_norm))


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


def _ozeti_yerlestir(metin: str, ciz, alan_genislik: int, azami_satir: int = 4, punto: int = 34):
    """
    Başlık altındaki özet satırını böler. Başlıktan farklı olarak punto
    sabit: özet her slaytta aynı boyda olmalı, yoksa carousel kayarken
    yazı boyu zıplıyor gibi görünür.
    """
    font = _font(punto, EKSEN_OZET)
    satirlar = _satirlara_bol(metin, font, alan_genislik, ciz)
    if len(satirlar) > azami_satir:
        satirlar = satirlar[:azami_satir]
        satirlar[-1] = satirlar[-1].rstrip(" ,;:") + "…"
    return font, satirlar, int(punto * 1.42)


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


# --- YATAY FOTOĞRAF YERLEŞİMİ (3 Eyl 2026, kullanıcı isteği) ---
#
# ⚠️ ESKİ HÂLİ: yatay fotoğraf 720px'de kesiliyordu ve başlık 1140'ta
# başlıyordu — arada ~420px "ne fotoğraf ne yazı" olan ölü bant kalıyordu.
# Kullanıcı: *"neden yazının çok üstünde yatay bir şekilde duruyor resim,
# ayrık duruyor çok fazla, burada açıklamaya kadar resim olurdu"*.
#
# Dört varyant üretilip yan yana gösterildi (720 / 1150 / 1450 / 1920) ve
# 1150 seçildi. Gerekçe: başlık fotoğrafın üstüne oturuyor (ayrıklık
# bitiyor) ama fotoğrafın ANLATTIĞI ŞEY bozulmuyor. 1450 ve 1920'de zoom
# arttıkça kadraj dağılıyor — Fed örneğinde madalyon iki yandan kesiliyordu.
FOTO_HEDEF_ALT = 1150

# ⚠️ BÜYÜTME TAVANI. Yatay fotoğrafı dikey tuvale yaymak onu BÜYÜTMEK
# demek ve büyütme bulanıklaştırır. Zoom oranı basitçe
# `hedef_yukseklik / kaynak_yukseklik`. 1200x709'luk tipik bir OG
# fotoğrafı 1150'ye çıkarken 1.62x büyüyor ve temiz kalıyor; küçük bir
# kaynakta aynı hedef yumuşama yaratır. O yüzden hedef sabit değil:
# fotoğraf yeterince büyük değilse daha AZ iniyor. Bulanık basmaktansa
# biraz daha kısa dursun.
FOTO_AZAMI_BUYUTME = 1.9

# Fotoğrafın en az ineceği yer — eski davranışın tabanı.
FOTO_ASGARI_ALT = 720


def _perde_maskesi(genislik: int, yukseklik: int,
                   bas: int, son: int) -> Image.Image:
    """
    Fotoğraftan düz zemine geçiş maskesi (0 = fotoğraf, 255 = düz zemin).

    ⚠️ EĞRİ SMOOTHSTEP: `t*t*(3-2t)`. Kullanıcı isteği (3 Eyl 2026):
    *"alt ve üst arasında renkleri bağlayıcı, biraz daha soft geçiş"*.
    Eski eğri `t**1.8` idi ve BAŞLANGICI KESKİNDİ — türevi 0 noktasında
    sıfır değil, yani perdenin nerede başladığı ince bir çizgi olarak
    görünüyordu. Smoothstep'in iki ucunda da türev sıfır, bu yüzden ne
    başladığı ne bittiği yer belli oluyor.

    ⚠️ PERFORMANS: eski kod her piksel için `putpixel` çağırıyordu —
    1080x1920 = 2 milyon Python çağrısı, slayt başına saniyeler.
    Degrade yalnızca Y'ye bağlı olduğu için 1 piksel genişliğinde
    üretilip yatayda geriliyor.
    """
    seritler = []
    for y in range(yukseklik):
        if y <= bas:
            v = 0
        elif y >= son:
            v = 255
        else:
            t = (y - bas) / (son - bas)
            v = int(255 * (t * t * (3 - 2 * t)))      # smoothstep
        seritler.append(v)
    serit = Image.new("L", (1, yukseklik))
    serit.putdata(seritler)
    return serit.resize((genislik, yukseklik), Image.BILINEAR)


def _yansima_ekle(canvas: Image.Image, foto: Image.Image,
                  foto_alt: int, yukseklik: int,
                  derinlik: int | None = None) -> None:
    """
    Fotoğrafın alt kenarına GÖL YANSIMASI ekler (yerinde değiştirir).

    ⚠️ NEDEN GEREKTİ (3 Eyl 2026, kullanıcı): *"bazı fotolarda fotoğrafın
    hemen altındaki alan çok keskin bir şekilde bitiyor"*. Fotoğraf
    `foto_alt`'ta bitiyor, altında bulanık ambiyans başlıyor ve ikisinin
    arasında NET BİR ÇİZGİ kalıyordu. Perde o çizgiyi ancak yeterince
    aşağıdaysa gizliyor; büyütme tavanı yüzünden fotoğraf erken bittiğinde
    (küçük kaynak) çizgi perdenin şeffaf bölgesine denk gelip görünüyordu.

    Çözüm: fotoğrafın alt şeridini dikey çevirip altına koymak. Su
    yüzeyindeki yansıma gibi — kenar artık "kesilmiş" değil, görüntünün
    kendi devamı oluyor. İçerik ilgili kaldığı için bulanık ambiyanstan
    da iyi duruyor.

    Aşağı indikçe hem SOLUYOR hem BULANIKLAŞIYOR: gerçek su yansıması da
    öyle davranır, sabit opaklıkta bir ayna görüntüsü yapay duruyor.
    """
    bosluk = yukseklik - foto_alt
    if bosluk <= 8:
        return                                     # yansımaya yer yok

    derinlik = derinlik or min(bosluk, int(foto_alt * 0.42))
    if derinlik < 24:
        return

    genislik = canvas.width
    # Fotoğrafın en alt `derinlik` kadarını al ve dikey çevir
    serit = canvas.crop((0, max(0, foto_alt - derinlik), genislik, foto_alt))
    yansima = serit.transpose(Image.FLIP_TOP_BOTTOM)

    # ⚠️ Bulanıklık YUKARIDAN AŞAĞI artmalı. Tek seferde blur uygulamak
    # yansımanın üst ucunu da bulanıklaştırır ve birleşme yeri yine
    # belli olur. Bantlara bölüp her banda kendi yarıçapını veriyoruz.
    bant = max(8, derinlik // 12)
    parcalar = []
    for ust in range(0, derinlik, bant):
        alt = min(ust + bant, derinlik)
        t = ust / derinlik
        parca = yansima.crop((0, ust, genislik, alt))
        yaricap = 2.0 + t * 5.0
        parcalar.append((ust, parca.filter(ImageFilter.GaussianBlur(yaricap))))
    for ust, parca in parcalar:
        yansima.paste(parca, (0, ust))

    # Solma maskesi: üstte yarı görünür, altta tamamen kayıp
    alfa = []
    for y in range(derinlik):
        t = y / derinlik
        alfa.append(int(150 * (1 - t) ** 1.6))
    m = Image.new("L", (1, derinlik))
    m.putdata(alfa)
    maske = m.resize((genislik, derinlik), Image.BILINEAR)

    canvas.paste(yansima, (0, foto_alt), maske)


def fotograftan_arkaplan(
    foto: Image.Image, genislik: int, yukseklik: int, odak_x_yuzde: int = 50
) -> Image.Image:
    """
    Ham haber veya basın fotoğrafını 1080x1920 dikey Story tuvaline akıllıca yerleştirir.

    - EXIF yön matrisini (ImageOps.exif_transpose) otomatik uygular; asla yan veya ters dönmez.
    - Dikey portreleri (ratio <= 0.8) üstten hizalı ve doğal derinlikle yerleştirir.
    - Yatay/16:9 basın fotoğraflarını (ratio > 0.8) aşırı dijital zoom ile kesip bulanıklaştırmak
      yerine, geniş kadrajıyla üst alana yerleştirir, arka plana yumuşak ambiyans ışıltısı verir
      ve alt metin alanına kesintisiz editoryal degrade ile eritir.
    - odak_x_yuzde: Yatay kırpmada odak merkezini yüzde (0=sol, 50=orta, 100=sağ) olarak kaydırır.
    """
    if getattr(foto, "_arkaplan_islendi", False) and foto.size == (genislik, yukseklik):
        return foto.copy()

    foto = ImageOps.exif_transpose(foto).convert("RGB")
    f_genislik, f_yukseklik = foto.size
    foto_oran = f_genislik / f_yukseklik

    canvas = Image.new("RGB", (genislik, yukseklik), (4, 24, 28))

    # Odak kaydırma katsayısı (0.0 - 1.0)
    odak_oran = max(0.0, min(1.0, odak_x_yuzde / 100.0))

    if foto_oran <= 0.78:
        # Doğal dikey portre (9:16 veya 4:5 portre)
        hedef_oran = genislik / yukseklik
        if foto_oran > hedef_oran:
            yeni_genislik = int(f_yukseklik * hedef_oran)
            kalan_w = f_genislik - yeni_genislik
            sol = int(kalan_w * odak_oran)
            foto_c = foto.crop((sol, 0, sol + yeni_genislik, f_yukseklik))
        else:
            yeni_yukseklik = int(f_genislik / hedef_oran)
            ust = int((f_yukseklik - yeni_yukseklik) * 0.12)
            foto_c = foto.crop((0, ust, f_genislik, ust + yeni_yukseklik))
        foto_res = foto_c.resize((genislik, yukseklik), Image.LANCZOS)
        canvas.paste(foto_res, (0, 0))
    else:
        # Yatay veya kare fotoğraf (16:9 HD, 4:3, 1:1)
        # 1. Arka plan ambiyans ışıltısı (keskin kenar/boşluk olmaması için)
        ambiyans = foto.resize((genislik, yukseklik), Image.BILINEAR)
        ambiyans = ambiyans.filter(ImageFilter.GaussianBlur(radius=40))
        # Koyu overlay
        amb_draw = ImageDraw.Draw(ambiyans, "RGBA")
        amb_draw.rectangle([0, 0, genislik, yukseklik], fill=(4, 24, 28, 150))
        canvas.paste(ambiyans, (0, 0))

        # 2. Fotoğrafı başlığın başladığı yere KADAR indir.
        #    Ölçekli tuvale oranla: 1920'lik tasarımda 1150.
        hedef_alt = int(FOTO_HEDEF_ALT * yukseklik / 1920)
        taban_alt = int(FOTO_ASGARI_ALT * yukseklik / 1920)

        # ⚠️ BÜYÜTME TAVANI — bulanık basmaktansa daha kısa dur.
        # Geniş fotoğrafta zoom = hedef_yukseklik / kaynak_yukseklik.
        tavan_alt = int(f_yukseklik * FOTO_AZAMI_BUYUTME)
        hedef_alt = max(taban_alt, min(hedef_alt, tavan_alt))

        # Tuvali (genislik x hedef_alt) KAPLAYACAK şekilde kırp
        hedef_oran = genislik / hedef_alt
        if foto_oran > hedef_oran:
            yeni_w = int(f_yukseklik * hedef_oran)
            kalan_w = f_genislik - yeni_w
            sol_k = int(kalan_w * odak_oran)
            foto_k = foto.crop((sol_k, 0, sol_k + yeni_w, f_yukseklik))
        else:
            yeni_h = int(f_genislik / hedef_oran)
            foto_k = foto.crop((0, 0, f_genislik, yeni_h))

        canvas.paste(foto_k.resize((genislik, hedef_alt), Image.LANCZOS), (0, 0))

        # Alt kenardaki keskin kesimi göl yansımasıyla yumuşat
        _yansima_ekle(canvas, foto, hedef_alt, yukseklik)

    # 3. Fotoğraftan düz zemine YUMUŞAK geçiş.
    #    Perde fotoğrafın bittiği yerin ÜSTÜNDE başlıyor ki fotoğrafın
    #    alt kenarı düz bir çizgi olarak görünmesin — başlık zaten oraya
    #    oturuyor ve okunması için karartma gerekiyor.
    perde_bas = int(700 * yukseklik / 1920)
    perde_son = int(1350 * yukseklik / 1920)
    mask = _perde_maskesi(genislik, yukseklik, perde_bas, perde_son)

    koyu_zemin = Image.new("RGB", (genislik, yukseklik), (4, 24, 28))
    canvas.paste(koyu_zemin, (0, 0), mask)

    # 4. Kristal netleştirme
    res = canvas.filter(ImageFilter.UnsharpMask(radius=1.2, percent=105, threshold=2))
    res._arkaplan_islendi = True
    return res


from .gorsel_arma import (
    IKONLAR,
    LOGO_KLASORU,
    LOGO_YOLU,
    _bayragi_bas,
    _ikon_facebook,
    _ikon_instagram,
    _ikon_threads,
    _ikon_tiktok,
    _ikon_x,
    _ikon_youtube,
    _kaynak_satiri_ciz,
    _logo_maskesi,
    _logo_onbellek,
    _logoyu_bas,
    _son_dakika_rozeti,
    _veri_rozeti_ciz,
    kanal_ikonlari_bas,
    serit_rengi,
    sirali_exif,
    split_portre_arkaplan,
)



def yaziyi_bas(
    arkaplan: Image.Image, baslik: str, kaynak: str, ayarlar: dict,
    ozet: str | None = None,
    arsiv_ibaresi: bool = False,
    ulke_kodu: str = "",
    ulke_adi: str = "",
    kategori: str = "",
    son_slayt: bool = False,
    veri_karti: dict | None = None,
    son_dakika: bool = False,
    haber: dict | None = None,
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

    # Uzun başlıklarda (>2 satır veya >85 karakter) alt özet puntosunu adaptif
    # olarak 34'ten 30'a çekerek üstteki kanca ve logoya ferah nefes alanı bırak.
    ozet_punto = 30 if len(baslik or "") > 85 else 34

    ozet_font, ozet_satirlari, ozet_satir_y = None, [], 0
    if ozet:
        ozet_font, ozet_satirlari, ozet_satir_y = _ozeti_yerlestir(
            ozet, ciz, alan_genislik, punto=ozet_punto
        )
    ozet_yuksekligi = ozet_satir_y * len(ozet_satirlari)

    # Özet varsa başlığa daha az yer kalıyor — sığdırma buna göre yapılmalı,
    # yoksa ikisi üst üste biner.
    baslik_alani = int(yukseklik * 0.42) - ozet_yuksekligi
    font, satirlar, satir_yuksekligi = _basligi_yerlestir(
        baslik, ciz, alan_genislik, baslik_alani
    )

    # Eğer başlık 2 satırı aşıyorsa ve özet henüz küçültülmediyse adaptif esnet
    if len(satirlar) > 2 and ozet_punto > 30 and ozet:
        ozet_punto = 30
        ozet_font, ozet_satirlari, ozet_satir_y = _ozeti_yerlestir(
            ozet, ciz, alan_genislik, punto=ozet_punto
        )
        ozet_yuksekligi = ozet_satir_y * len(ozet_satirlari)

    ozet_ust = alt_bilgi_y - (66 if (son_slayt or yukseklik >= 1800) else 44) - ozet_yuksekligi
    baslik_ust = ozet_ust - (26 if ozet else 0) - satir_yuksekligi * len(satirlar)

    # --- 2) Perde: Standart kurumsal kategori renk şeridi (özet ve alt bilgiyi tam opak korur) ---
    taban = _perde_taban_alfa(gorsel, (0, baslik_ust, genislik, yukseklik))
    renk = serit_rengi(kategori, g)
    serit_ust = ozet_ust - 30 if ozet else alt_bilgi_y - 30
    serit_basi = max(0, serit_ust - (150 + taban))

    perde = Image.new("RGBA", (genislik, yukseklik), (0, 0, 0, 0))
    perde_ciz = ImageDraw.Draw(perde)

    # Üst köşelere hafif netleştirici vignette (logo ve flama arkası)
    for y in range(0, min(320, yukseklik)):
        ust_alfa = int(115 * ((320 - y) / 320) ** 1.8)
        perde_ciz.line([(0, y), (genislik, y)], fill=(6, 10, 18, ust_alfa))

    gecis = max(1, serit_ust - serit_basi)
    for y in range(serit_basi, yukseklik):
        if y < serit_ust:
            alfa = int(255 * ((y - serit_basi) / gecis) ** 1.6)
        else:
            alfa = 255
        perde_ciz.line([(0, y), (genislik, y)], fill=renk + (alfa,))

    gorsel = Image.alpha_composite(gorsel.convert("RGBA"), perde).convert("RGB")

    # --- 3) Çok Katmanlı Difüzyon Gölgesi (Yazıyı arka plandan kristal gibi ayırır) ---
    golge = Image.new("RGBA", (genislik, yukseklik), (0, 0, 0, 0))
    golge_ciz = ImageDraw.Draw(golge)
    y = baslik_ust
    for satir in satirlar:
        golge_ciz.text((kenar, y + 4), satir.replace("**", ""), font=font, fill=(0, 0, 0, 230))
        y += satir_yuksekligi
    golge = golge.filter(ImageFilter.GaussianBlur(13))
    gorsel = Image.alpha_composite(gorsel.convert("RGBA"), golge).convert("RGB")
    ciz = ImageDraw.Draw(gorsel)

    y = baslik_ust
    for satir in satirlar:
        ciz.text((kenar, y), satir.replace("**", ""), font=font, fill=(255, 255, 255))
        y += satir_yuksekligi

    y = ozet_ust
    for satir in ozet_satirlari:
        _formatli_satir_ciz(ciz, kenar, y, satir, punto=ozet_punto, spot=True, varsayilan_renk=(226, 232, 240))
        y += ozet_satir_y

    # --- 3.5) Editoryal Hook (Kanca) Çizimi (Yalnızca 9:16 / 1080x1920 Kapak Slaytlarında) ---
    # ⚠️ `kanca_ciz` ayarı: projedeki her özellik kapatılabiliyor
    # (`web_gorsel_ara`, `threadse_de_at`…), kancanın anahtarı yoktu.
    if haber and yukseklik >= 1800 and g.get("kanca_ciz", True):
        try:
            from . import hook_motoru
            gorsel = hook_motoru.hook_uygula(gorsel, haber, baslik_ust, ayarlar)
            ciz = ImageDraw.Draw(gorsel)
        except Exception as e:
            log.warning("hook çiziminde hata: %s", e)

    # Son slayt Call-To-Action (CTA) etkileşim rozeti veya kapak kaydırma köprüsü
    # 4) Alt Bilgi ve Slayt Köprüsü Yerleşimi (Düşeyde Logolarla Ortalanmış & Tam Çakışma Korumalı)
    y_merkez = alt_bilgi_y + 13
    boy = g.get("kanal_ikon_boyu", 26)
    kanallar = (ayarlar.get("sosyal", {}) or {}).get("kanallar") or []
    toplam_genislik = len(kanallar) * boy + (len(kanallar) - 1) * 14 if kanallar else 0
    sag_x = genislik - kenar
    ikonlar_sol = sag_x - toplam_genislik if kanallar else sag_x

    EMNIYET_BOSLUK = 22

    # Son slayt Call-To-Action (CTA) etkileşim rozeti
    if son_slayt:
        cta_font = _font(24, EKSEN_KUCUK)
        kat_kucuk = (kategori or "").lower()
        if kat_kucuk == "ekonomi":
            cta_metin = "★ Piyasa ve ekonomi özetlerini kaçırmamak için kaydet & takip et"
        elif kat_kucuk in ("teknoloji", "bilim"):
            cta_metin = "★ Teknoloji ve bilim gündemini kaçırmamak için kaydet & takip et"
        elif kat_kucuk == "spor":
            cta_metin = "★ Spor gündemini ve analizleri kaçırmamak için kaydet & takip et"
        else:
            cta_metin = "★ Günün özetini kaçırmamak için kaydet & takip et"
        ciz.text((kenar, alt_bilgi_y - 36), cta_metin, font=cta_font, fill=(226, 170, 88))
        _kaynak_satiri_ciz(ciz, kenar, alt_bilgi_y, kaynak, arsiv_ibaresi=arsiv_ibaresi)
    elif yukseklik >= 1800:
        # Kapak Slaytı (1080x1920): Carousel akışında detay slaytlarına geçiş oku
        # Metin olmadan yalnızca şık bir "→" oku kullanılır; hem Carousel'de kaydırma yönünü
        # gösterir hem de Reels/TikTok/Shorts video formatında gereksiz metin karmaşası yaratmaz.
        # Düşeyde sağdaki sosyal medya logolarıyla (y_merkez) tam ortalanır.
        sw_metin = "→"
        sw_punto = 30
        sw_font = _font(sw_punto, EKSEN_KUCUK)
        sw_gen = ciz.textlength(sw_metin, font=sw_font)

        # İdeal tam yatay orta
        sw_x_orta = genislik // 2
        sw_sol = sw_x_orta - (sw_gen / 2)
        sw_sag = sw_x_orta + (sw_gen / 2)

        # Sağ güvenlik bariyeri: Sosyal medya ikonlarına ve dailybrief.co'ya taşmayı engelle
        if sw_sag + EMNIYET_BOSLUK > ikonlar_sol:
            sw_punto = 24
            sw_font = _font(sw_punto, EKSEN_KUCUK)
            sw_gen = ciz.textlength(sw_metin, font=sw_font)
            sw_sol = sw_x_orta - (sw_gen / 2)
            sw_sag = sw_x_orta + (sw_gen / 2)

        # Sol güvenlik bariyeri: Kaynak metninin orta oka taşmasını kesin olarak engelle
        azami_kaynak_sag = int(sw_sol - EMNIYET_BOSLUK)
        _kaynak_satiri_ciz(ciz, kenar, alt_bilgi_y, kaynak, arsiv_ibaresi=arsiv_ibaresi, azami_sag_x=azami_kaynak_sag)

        # Düşeyde o satırdaki logolarla (y_merkez) tam ortalanmış çizim (anchor="mm")
        ciz.text((sw_x_orta, y_merkez - 2), sw_metin, font=sw_font, fill=(226, 170, 88), anchor="mm")
    else:
        _kaynak_satiri_ciz(ciz, kenar, alt_bilgi_y, kaynak, arsiv_ibaresi=arsiv_ibaresi)

    # Sosyal kanal ikonları sağ altta: "bu içerik şu kanallarda da var".
    gorsel = kanal_ikonlari_bas(gorsel, ayarlar, y_merkez)
    ciz = ImageDraw.Draw(gorsel)

    # Sol üstte DailyBrief logosu (%50 büyütülmüş 144px)
    gorsel = _logoyu_bas(gorsel, kenar, dikey_kenar - 16, boy=144)
    ciz = ImageDraw.Draw(gorsel)
    ciz.rectangle(
        [kenar + 162, dikey_kenar + 50, kenar + 162 + 75, dikey_kenar + 58],
        fill=(226, 170, 88),
    )

    if ulke_kodu:
        gorsel = _bayragi_bas(gorsel, ulke_kodu, ulke_adi, dikey_kenar)

    # ⚠️ SON DAKİKA ETİKETİ ARTIK BURADA ÇİZİLİYOR. Eskiden çağıranlar
    # (`story_haber`) `yaziyi_bas`tan SONRA kendileri çiziyordu ve veri
    # rozetini yerleştiren kod etiketin varlığından habersizdi — ikisi
    # çakışıyordu (ölçüldü: 49 px örtüşme). Tek fonksiyon sahiplenince
    # yerleşim hesaplanabilir hale geliyor.
    ciz = ImageDraw.Draw(gorsel)
    sd_sag = sd_alt = 0
    if son_dakika:
        sd_sag, sd_alt = _son_dakika_rozeti(ciz, kenar + 162, dikey_kenar + 30)

    # ⚠️ VERİ KARTI ROZETİ KALDIRILDI (7 Eyl 2026):
    # Kullanıcı: *"ülke bayrağının solundaki özet rakamsal bilgi kartımızın
    # içeriği çok uzadığında soldaki logomuza taşıyor, tasarımı hoşuma gitmiyo
    # kaldıralım"*. Üst barda Logo (144px) + SON DAKİKA rozeti + Ülke Bayrağı
    # varken araya 4. bir kutu olarak giren cam rozet hem logoya biniyordu hem
    # görseli boğuyordu. Bu bilgi zaten başlıkta, spotta veya ayrıntı
    # sayfasındaki büyük odak kartında (vurgu_sayi) yer alıyor.
    return gorsel


# ----------------------------------------------------------------------
# Story (9:16) & Boyut Sabitleri
# ----------------------------------------------------------------------
GENISLIK = 1080
YUKSEKLIK = 1350
STORY_GENISLIK, STORY_YUKSEKLIK = 1080, 1920
STORY_GUVENLI_PAY = 330



def story_haber(
    baslik: str, ozet: str, kaynak: str, ayarlar: dict,
    arkaplan: Image.Image | None = None,
    kategori: str = "turkiye",
    son_dakika: bool = False,
    ulke_kodu: str | None = None,
    ulke_adi: str | None = None,
    son_slayt: bool = False,
    veri_karti: dict | None = None,
    arsiv_ibaresi: bool = False,
    haber: dict | None = None,
) -> Image.Image:
    """
    Tek haberin %100 Native 9:16 (1080x1920) Kapak Slaytı.
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
        odak_x = 50
        if isinstance(haber, dict) and haber.get("odak_x_yuzde") is not None:
            try:
                odak_x = int(haber["odak_x_yuzde"])
            except (ValueError, TypeError):
                odak_x = 50
        arkaplan = fotograftan_arkaplan(
            arkaplan, STORY_GENISLIK, STORY_YUKSEKLIK, odak_x_yuzde=odak_x
        )

    gorsel = yaziyi_bas(
        arkaplan, baslik, kaynak, story_ayarlar,
        ozet=ozet or None,
        arsiv_ibaresi=arsiv_ibaresi,
        ulke_kodu=ulke_kodu,
        ulke_adi=ulke_adi,
        son_slayt=son_slayt,
        kategori=kategori,
        veri_karti=veri_karti,
        son_dakika=son_dakika,
        haber=haber,
    )

    # ⚠️ SON DAKİKA ETİKETİ ARTIK BURADA ÇİZİLMİYOR — `yaziyi_bas`
    # çiziyor. Buradan çizilirken rozet yerleşimi ondan habersizdi ve
    # ikisi çakışıyordu (49 px, ölçüldü).

    return gorsel


def story_detay(
    baslik: str, detay: str, kaynak: str, ayarlar: dict,
    arkaplan: Image.Image | None = None,
    kategori: str = "turkiye",
    son_dakika: bool = True,
    ulke_kodu: str | None = None,
    ulke_adi: str | None = None,
    satirlar: list[dict] | None = None,
    sayfa: int = 1,
    toplam_sayfa: int = 1,
    arsiv_ibaresi: bool = False,
) -> Image.Image:
    """
    Haber detayının 9:16 (1080x1920) Story formatı.
    story_haber ile birebir aynı dikey güvenli pay (285px), logo, bayrak ve tipografi hizalamasını kullanır.
    """
    # ⚠️ Başlık DÜZ çiziliyor, kalın vurgusu yok — `**` gelirse ekranda
    # görünür. `ig_baslik` üretimde `markdown_temizle`den geçiyor ama
    # bu fonksiyon başka yollardan da çağrılabiliyor (özel haber,
    # elle kurulan tur); kapıyı burada da tutuyoruz.
    baslik = (baslik or "").replace("**", "")
    story_ayarlar = {
        **ayarlar,
        "gorsel": {
            **ayarlar["gorsel"],
            "genislik": STORY_GENISLIK,
            "yukseklik": STORY_YUKSEKLIK,
            "dikey_guvenli_pay": STORY_GUVENLI_PAY,
        },
    }
    return detay_slayti(
        baslik=baslik,
        detay=detay,
        kaynak=kaynak,
        ayarlar=story_ayarlar,
        kategori=kategori,
        son_dakika=son_dakika,
        ulke_kodu=ulke_kodu,
        ulke_adi=ulke_adi,
        satirlar=satirlar,
        sayfa=sayfa,
        toplam_sayfa=toplam_sayfa,
        arkaplan=arkaplan,
        arsiv_ibaresi=arsiv_ibaresi,
    )


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


TURKCE_KISALTMALAR = {
    "dr", "doc", "doç", "prof", "av", "yrd", "uzm", "muh", "müh", "mim",
    "sn", "gen", "alb", "bnb", "yzb", "tgm", "tğm", "utgm", "ütğm", "astsb",
    "emk", "bsk", "bşk", "mud", "müd", "vb", "vs", "sf", "s", "md", "mad",
    "no", "nr", "bkz", "or", "ör", "orn", "örn", "fiz", "kim", "biy",
    "ist", "ank", "izm", "cad", "sok", "apt", "al", "co", "inc", "ltd",
    "sti", "şti", "as", "aş", "tc", "t.c", "v"
}


def cumlelere_bol(metin: str) -> list[str]:
    """
    Türkçe unvan, kısaltma (Doç., Dr., vb.), sıra sayısı (14.) ve
    özel karakterleri bozmadan metni gerçek cümle sınırlarından ayırır.
    """
    if not metin or not metin.strip():
        return []

    cumleler = []
    baslangic = 0
    i = 0
    uzunluk = len(metin)

    while i < uzunluk:
        ch = metin[i]
        if ch in ".!?…":
            # Ardışık noktalamaları geç (...)
            j = i
            while j < uzunluk and metin[j] in ".!?…":
                j += 1

            # Noktalamadan sonraki boşluğu kontrol et
            k = j
            while k < uzunluk and metin[k].isspace():
                k += 1

            if k == uzunluk:
                # Metnin sonu
                cumle = metin[baslangic:].strip()
                if cumle:
                    cumleler.append(cumle)
                baslangic = uzunluk
                break

            if k > j:  # Noktalamadan sonra en az bir boşluk var
                sonraki_karakter = metin[k]

                # Tırnak veya parantez varsa bir sonraki karaktere bak
                if sonraki_karakter in "\"'“”‘’()[]" and k + 1 < uzunluk:
                    sonraki_karakter = metin[k + 1]

                # Cümle sonu olma koşulu: Sonraki karakter büyük harf olmalı
                buyuk_harf_mi = (sonraki_karakter.isupper()
                                 or sonraki_karakter in "ÇĞİÖŞÜ")

                # Noktadan önceki son kelimeyi bul
                onceki_metin = metin[baslangic:i].strip()
                kelimeler = re.findall(r"[a-zA-Z0-9çğıöşüÇĞİÖŞÜ]+", onceki_metin)
                son_kelime = kelimeler[-1] if kelimeler else ""
                son_kelime_kucuk = son_kelime.lower()

                # Kontroller:
                # a) Kısaltma mı? (Doç., Dr., vb.)
                kisaltma_mi = son_kelime_kucuk in TURKCE_KISALTMALAR
                # b) Sıra sayısı mı? (14., 2.)
                sira_sayisi_mi = son_kelime.isdigit()
                # c) Tek harfli baş harf mi? (M. Kemal)
                tek_harf_mi = len(son_kelime) == 1 and son_kelime.isupper()

                if buyuk_harf_mi and not kisaltma_mi and not sira_sayisi_mi and not tek_harf_mi:
                    # Gerçek cümle sonu!
                    cumle = metin[baslangic:j].strip()
                    if cumle:
                        cumleler.append(cumle)
                    baslangic = k
                    i = k
                    continue
            i = j
        else:
            i += 1

    kalan = metin[baslangic:].strip()
    if kalan:
        cumleler.append(kalan)

    return cumleler


def _metni_paragraflara_ayir(metin: str, azami_cumle: int = 3) -> list[str]:
    """
    Uzun veya tek parça detay metnini okunaklı, ferah paragraflara böler.
    Satır sonlarını korur; 3'ten fazla cümle içeren uzun blokları 2-3 cümlelik
    doğal paragraflara ayırarak okumayı kolaylaştırır.
    Türkçe kısaltma ve unvanları (Doç., Dr., vb.) korur.
    """
    if not metin or not metin.strip():
        return []

    ham_paragraflar = [p.strip() for p in re.split(r"\n+", metin.strip()) if p.strip()]
    sonuc = []

    for p in ham_paragraflar:
        cumleler = cumlelere_bol(p)
        if len(cumleler) <= azami_cumle:
            sonuc.append(p)
        elif len(cumleler) == 4:
            # 4 cümlede 3+1 yerine 2+2 daha dengeli ve ferah bir görünüm sunar
            sonuc.append(" ".join(cumleler[:2]).strip())
            sonuc.append(" ".join(cumleler[2:]).strip())
        else:
            for i in range(0, len(cumleler), azami_cumle):
                parca = " ".join(cumleler[i : i + azami_cumle]).strip()
                if parca:
                    sonuc.append(parca)

    return sonuc


def _sayfalari_dengeli_bol(
    bloklar: list[dict],
    kullanilabilir: int,
    azami_sayfa: int = AZAMI_DETAY_SAYFA,
    aralik: int = PARAGRAF_ARASI,
) -> list[list[dict]]:
    """
    Detay slaytı bloklarını (paragraflar, vurgu sayısı, alıntı, neden önemli vb.)
    sayfalar arasında estetik, nefes alan ve dengeli bir biçimde paylaştırır.

    Açgözlü (greedy) yaklaşımın bir önceki sayfayı alt bilgi çizgisine kadar doldurup
    son sayfayı tek satırlık bir alıntıyla %85 boş bırakmasını (yetim blok) engeller.
    """
    if not bloklar:
        return [[]]
    n = len(bloklar)
    if n == 1:
        return [bloklar]

    # 1. Açgözlü (greedy) simülasyonla asgari sayfa sayısını bul
    sayfalar_greedy: list[list[dict]] = []
    gecerli: list[dict] = []
    dolu = 0
    for b in bloklar:
        gerekli = b["yukseklik"] + (aralik if gecerli else 0)
        tek_vurgu = (len(gecerli) == 1 and gecerli[0].get("tip") == "sayi")
        if gecerli and dolu + gerekli > kullanilabilir and not tek_vurgu:
            sayfalar_greedy.append(gecerli)
            gecerli, dolu = [b], b["yukseklik"]
        else:
            gecerli.append(b)
            dolu += gerekli
    if gecerli:
        sayfalar_greedy.append(gecerli)

    k_min = len(sayfalar_greedy)
    if k_min <= 1:
        return [bloklar]
    k_min = min(k_min, azami_sayfa)

    ozel_kapanis_tipleri = {"alinti", "neden_onemli", "sirada_ne_var", "sana_etkisi"}
    en_iyi_bolum = None
    en_iyi_skor = float("inf")

    # Sayfa sayısı için k_min ve gerekirse k_min + 1'i dene
    for k in range(k_min, min(k_min + 2, azami_sayfa + 1)):
        for cuts in itertools.combinations(range(1, n), k - 1):
            idx = [0] + list(cuts) + [n]
            parts = [bloklar[idx[i]:idx[i + 1]] for i in range(k)]

            gecersiz = False
            heights = []
            orphan_ceza = 0

            for p in parts:
                h = sum(b.get("yukseklik", 0) for b in p) + aralik * (len(p) - 1)
                # Fiziksel sınır aşımı: bu bölümleme kesinlikle elenir
                if h > kullanilabilir:
                    gecersiz = True
                    break
                # Vurgu sayısı tek başına kalamaz (yanında mutlaka ilk metin olmalı)
                if p[0].get("tip") == "sayi" and len(p) == 1:
                    gecersiz = True
                    break
                # Yetim özel blok cezası (toplam blok >= 3 iken tek başına alıntı/neden önemli bırakma)
                if n >= 3 and len(p) == 1 and p[0].get("tip") in ozel_kapanis_tipleri:
                    orphan_ceza += 150000

                heights.append(h)

            if gecersiz:
                continue

            # Skorlama:
            # 1. Varyans: sayfaların birbirine yakın yükseklikte olmasını hedefler
            h_avg = sum(heights) / k
            var_cost = sum((h - h_avg) ** 2 for h in heights)

            # 2. Boy farkı (max - min)
            diff_cost = (max(heights) - min(heights)) * 50

            # 3. Boş sayfa oranı cezası (en küçük sayfa en büyük sayfanın %50'sinden az yer kaplarsa)
            min_oran = min(heights) / max(heights) if max(heights) > 0 else 1.0
            oran_ceza = 40000 * (0.50 - min_oran) if min_oran < 0.50 else 0

            # 4. Tek blok cezası (blok sayısı >= 4 iken sayfayı tek blokla kapatmayı cezalandır)
            tek_blok_ceza = sum(15000 for p in parts if len(p) == 1 and n >= 4)

            # 5. Gereksiz sayfa açma cezası (k > k_min ise)
            sayfa_ceza = (k - k_min) * 100000

            toplam_skor = var_cost + diff_cost + oran_ceza + tek_blok_ceza + sayfa_ceza + orphan_ceza
            if toplam_skor < en_iyi_skor:
                en_iyi_skor = toplam_skor
                en_iyi_bolum = parts

        # Eğer k_min sayfa sayısıyla yetim bloksuz geçerli bir bölüm bulunduysa dur
        if en_iyi_bolum is not None and en_iyi_skor < 100000:
            break

    return en_iyi_bolum if en_iyi_bolum is not None else sayfalar_greedy[:azami_sayfa]


def detay_sayfalara_bol(
    detay: str, ayarlar: dict,
    vurgu: tuple[str, str] | None = None,
    alinti: tuple[str, str] | None = None,
    neden_onemli: str | None = None,
    sirada_ne_var: str | None = None,
    trend_karti: Image.Image | None = None,
    sana_etkisi: str | None = None,
    etkilesim_sorusu: str | None = None,
) -> list[list[dict]]:
    """
    Detay metnini paragraflara ayırıp sayfalara dağıtır.
    Smart Brevity formatını (Ne oldu / Sana Etkisi / Neden Önemli / Sırada Ne Var) ve Finans Trend Kartlarını destekler.
    """
    g = ayarlar["gorsel"]
    genislik = g.get("genislik", STORY_GENISLIK)
    yukseklik = g.get("yukseklik", STORY_YUKSEKLIK)
    kenar = g.get("kenar_bosluk", 80)
    dikey_kenar = max(kenar, g.get("dikey_guvenli_pay", STORY_GUVENLI_PAY))

    olcu = ImageDraw.Draw(Image.new("RGB", (genislik, yukseklik)))
    alan = genislik - 2 * kenar - 32  # Sol çentik ve girinti payı (kenar + 24)

    ust_blok = dikey_kenar + 120
    alt_bilgi_y = yukseklik - dikey_kenar - 34
    kullanilabilir = alt_bilgi_y - 40 - ust_blok

    paragraflar = _metni_paragraflara_ayir(detay or "")
    if not paragraflar and not vurgu and not alinti and not neden_onemli and not trend_karti and not sana_etkisi:
        return [[]]

    bloklar = []

    # Vurgu rakamı en başta: sayfanın çapası, ilk göze çarpan şey.
    if vurgu and vurgu[0]:
        s_punto = VURGU_SAYI_PUNTO
        for aday in (VURGU_SAYI_PUNTO, 76, 64, 54, 46):
            if olcu.textlength(vurgu[0], font=_font(aday, EKSEN_BASLIK)) <= alan:
                s_punto = aday
                break
        else:
            s_punto = 46
        bloklar.append({
            # ⚠️ Vurgu etiketi KALIN basılmıyor, düz çiziliyor — yıldız
            # gelirse ekranda görünür. Model bu alanda `**` kullanmamalı
            # ama kullanırsa burada eleniyor.
            "tip": "sayi", "sayi": vurgu[0],
            "etiket": (vurgu[1] or "").replace("**", ""),
            "punto": s_punto, "satirlar": [],
            "yukseklik": int(s_punto * 1.15) + int(VURGU_ETIKET_PUNTO * 1.7),
        })

    # Her paragrafı satırlara böl. İlki spot: daha iri punto.
    for i, metin in enumerate(paragraflar):
        spot = (i == 0)
        # Giriş (spot) paragrafı çok uzunsa (>140 karakter) veya dikey alan sıkışıkken
        # nefes alanını korumak için puntoyu 46'dan 40'a esnet
        if spot:
            punto = 40 if len(metin) > 140 else DETAY_SPOT_PUNTO
        else:
            punto = DETAY_PUNTO
        font = _font(punto, EKSEN_OZET)
        satirlar = _satirlara_bol(metin, font, alan, olcu)
        yukseklik_px = int(punto * 1.5) * len(satirlar)

        # Eğer tek paragraf tek sayfaya sığmıyorsa cümle sınırlarından böl
        if yukseklik_px > kullanilabilir:
            c_parcalar = cumlelere_bol(metin)
            if len(c_parcalar) >= 2:
                yari_c = max(1, len(c_parcalar) // 2)
                metin_1 = " ".join(c_parcalar[:yari_c])
                metin_2 = " ".join(c_parcalar[yari_c:])
                sat_1 = _satirlara_bol(metin_1, font, alan, olcu)
                sat_2 = _satirlara_bol(metin_2, _font(DETAY_PUNTO, EKSEN_OZET), alan, olcu)
                bloklar.append({"tip": "metin", "satirlar": sat_1, "spot": spot,
                                "punto": punto,
                                "yukseklik": int(punto * 1.5) * len(sat_1)})
                bloklar.append({"tip": "metin", "satirlar": sat_2, "spot": False,
                                "punto": DETAY_PUNTO,
                                "yukseklik": int(DETAY_PUNTO * 1.5) * len(sat_2)})
            else:
                bloklar.append({"tip": "metin", "satirlar": satirlar, "spot": spot,
                                "punto": punto,
                                "yukseklik": yukseklik_px})
        else:
            bloklar.append({"tip": "metin", "satirlar": satirlar, "spot": spot,
                            "punto": punto,
                            "yukseklik": yukseklik_px})

    # Sana / Piyasaya Etkisi (Zümrüt Yeşil Vurgulu Doğal Editoryal Blok)
    if sana_etkisi and sana_etkisi.strip():
        se_punto = DETAY_PUNTO - 3
        se_font = _font(se_punto, EKSEN_OZET)
        se_satirlar = _satirlara_bol(sana_etkisi.strip(), se_font, alan, olcu)
        bloklar.append({
            "tip": "sana_etkisi",
            "metin": sana_etkisi.strip(),
            "satirlar": se_satirlar,
            "spot": False,
            "yukseklik": int(se_punto * 1.5) * len(se_satirlar),
        })

    # Smart Brevity: Neden Önemli (Doğal editoryal blok)
    if neden_onemli and neden_onemli.strip():
        n_punto = DETAY_PUNTO - 3
        n_font = _font(n_punto, EKSEN_OZET)
        n_satirlar = _satirlara_bol(neden_onemli.strip(), n_font, alan, olcu)
        bloklar.append({
            "tip": "neden_onemli",
            "metin": neden_onemli.strip(),
            "satirlar": n_satirlar,
            "spot": False,
            "yukseklik": int(n_punto * 1.5) * len(n_satirlar),
        })

    # Smart Brevity: Sırada Ne Var (Doğal editoryal blok)
    if sirada_ne_var and sirada_ne_var.strip():
        s_punto = DETAY_PUNTO - 3
        s_font = _font(s_punto, EKSEN_OZET)
        s_satirlar = _satirlara_bol(sirada_ne_var.strip(), s_font, alan, olcu)
        bloklar.append({
            "tip": "sirada_ne_var",
            "metin": sirada_ne_var.strip(),
            "satirlar": s_satirlar,
            "spot": False,
            "yukseklik": int(s_punto * 1.5) * len(s_satirlar),
        })

    # Finans & Borsa: Otomatik Mini Trend Kartı (Sparkline)
    if trend_karti:
        bloklar.append({
            "tip": "trend_karti",
            "gorsel": trend_karti,
            "satirlar": [],
            "spot": False,
            "yukseklik": trend_karti.height + 24,
        })

    # Alıntı en sonda: kapanış
    if alinti and alinti[0]:
        a_font = _font(ALINTI_PUNTO, EKSEN_OZET)
        a_satirlar = _satirlara_bol(f"“{alinti[0]}”", a_font, alan - 8, olcu)
        bloklar.append({
            "tip": "alinti", "satirlar": a_satirlar,
            "sahibi": alinti[1] or "", "spot": False,
            "yukseklik": int(ALINTI_PUNTO * 1.45) * len(a_satirlar) + 54,
        })

    # VURGU + İLK PARAGRAF BİRLİKTE SIĞMALI.
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

    # Sayfalara estetik ve dengeli dağıt (yetim blok korumalı)
    sayfalar = _sayfalari_dengeli_bol(bloklar, kullanilabilir, AZAMI_DETAY_SAYFA, PARAGRAF_ARASI)

    # Kapanış slaytında dikey alan müsaitse (yeni sayfa açtırmadan) etkileşim sorusunu ekle
    if etkilesim_sorusu and etkilesim_sorusu.strip() and sayfalar and sayfalar[-1]:
        soru_temiz = etkilesim_sorusu.replace("**", "").strip()
        if "?" in soru_temiz:
            eq_punto = DETAY_PUNTO - 3
            eq_font = _font(eq_punto, EKSEN_OZET)
            eq_metin = f"**SİZCE?** — {soru_temiz}"
            eq_satirlar = _satirlara_bol(eq_metin, eq_font, alan, olcu)
            eq_yuk = int(eq_punto * 1.5) * len(eq_satirlar)
            son_sayfa = sayfalar[-1]
            mevcut_yuk = (
                sum(b.get("yukseklik", 0) for b in son_sayfa)
                + PARAGRAF_ARASI * max(0, len(son_sayfa) - 1)
            )
            if mevcut_yuk + PARAGRAF_ARASI + eq_yuk <= kullanilabilir - 24:
                son_sayfa.append({
                    "tip": "etkilesim_sorusu",
                    "metin": eq_metin,
                    "satirlar": eq_satirlar,
                    "spot": False,
                    "yukseklik": eq_yuk,
                })

    return sayfalar


def detay_slayti(
    baslik: str, detay: str, kaynak: str, ayarlar: dict,
    kategori: str = "turkiye",
    son_dakika: bool = True,
    ulke_kodu: str | None = None,
    ulke_adi: str | None = None,
    satirlar: list[dict] | None = None,
    sayfa: int = 1,
    toplam_sayfa: int = 1,
    arkaplan: Image.Image | None = None,
    arsiv_ibaresi: bool = False,
) -> Image.Image:
    """
    Son dakika postunun 2. slaytı: haberin ayrıntısı.
    İkinci bir fotoğraf varsa hafif koyu perdeyle derinlikli zemin olarak kullanılır.
    """
    # ⚠️ Başlık DÜZ çiziliyor, kalın vurgusu yok — `**` gelirse ekranda
    # görünür. `ig_baslik` üretimde `markdown_temizle`den geçiyor ama
    # bu fonksiyon başka yollardan da çağrılabiliyor (özel haber,
    # elle kurulan tur); kapıyı burada da tutuyoruz.
    baslik = (baslik or "").replace("**", "")
    g = ayarlar["gorsel"]
    genislik, yukseklik = g["genislik"], g["yukseklik"]
    kenar = g["kenar_bosluk"]
    dikey_kenar = max(kenar, g.get("dikey_guvenli_pay", kenar))

    if arkaplan is not None:
        oran = max(genislik / arkaplan.width, yukseklik / arkaplan.height)
        yeni_w, yeni_h = int(arkaplan.width * oran), int(arkaplan.height * oran)
        foto_buyuk = arkaplan.resize((yeni_w, yeni_h), Image.LANCZOS)
        x_kirp = (yeni_w - genislik) // 2
        y_kirp = (yeni_h - yukseklik) // 2
        gorsel = foto_buyuk.crop((x_kirp, y_kirp, x_kirp + genislik, y_kirp + yukseklik))
        perde = Image.new("RGBA", (genislik, yukseklik), (4, 16, 26, 230))
        gorsel = Image.alpha_composite(gorsel.convert("RGBA"), perde).convert("RGB")
    else:
        gorsel = arkaplan_uret_yedek(kategori, genislik, yukseklik, g)
    ciz = ImageDraw.Draw(gorsel)
    alan_genislik = genislik - 2 * kenar

    # Bayrak sağ üstte duruyor; başlık oraya kadar uzarsa altında kalıyor.
    baslik_genislik = alan_genislik - (170 if ulke_kodu else 0)

    # Sol üst logo (%50 büyütülmüş 144px)
    gorsel = _logoyu_bas(gorsel, kenar, dikey_kenar - 16, boy=144)
    ciz = ImageDraw.Draw(gorsel)

    # --- Üst: SON DAKİKA etiketi (yalnızca olağanüstü olaylarda) ---
    if son_dakika:
        etiket_font = _font(24, EKSEN_KUCUK)
        etiket = "SON DAKİKA"
        metin_g = ciz.textlength(etiket, font=etiket_font)
        ciz.rounded_rectangle(
            [kenar + 162, dikey_kenar + 30, kenar + 162 + metin_g + 28, dikey_kenar + 76],
            radius=6,
            fill=(198, 60, 52),
        )
        ciz.text((kenar + 162 + 14, dikey_kenar + 39), etiket, font=etiket_font,
                 fill=(255, 255, 255))

    # Detay sayfalarında tekrarlayan devasa başlık kaldırıldı.
    # Metin ferah ve geniş bir dikey alanda akar.
    y = dikey_kenar + 120

    # --- Detay metni: asıl içerik ---
    alt_bilgi_y = yukseklik - dikey_kenar - 34
    kullanilabilir = alt_bilgi_y - 40 - y

    # `satirlar` paragraf blokları listesi: [{"satirlar", "spot"}, ...]
    bloklar = satirlar
    if bloklar is None:
        d_font = _font(DETAY_PUNTO, EKSEN_OZET)
        bloklar = [{"satirlar": _satirlara_bol(detay, d_font, alan_genislik - 32, ciz),
                    "spot": False}]

    toplam = (sum(b.get("yukseklik", 0) for b in bloklar)
              + PARAGRAF_ARASI * max(0, len(bloklar) - 1))

    # Blokları kalan alanda dikeyde ortalıyoruz.
    y += max(0, (kullanilabilir - toplam) // 2)

    for i, b in enumerate(bloklar):
        tip = b.get("tip", "metin")

        if tip == "sayi":
            # İri rakam + altında ne olduğu. Amber renk: sayfadaki tek
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

        elif tip in ("neden_onemli", "sirada_ne_var", "sana_etkisi", "etkilesim_sorusu"):
            if tip == "sana_etkisi":
                kenar_renk = (16, 185, 129)  # Parlak Zümrüt Yeşili (Emerald)
                varsayilan_renk = (220, 252, 231)
            elif tip in ("neden_onemli", "etkilesim_sorusu"):
                kenar_renk = (226, 170, 88)  # Sıcak Kehribar (Amber)
                varsayilan_renk = (226, 232, 240)
            else:
                kenar_renk = (6, 182, 212)   # Siber Turkuaz (Cyan)
                varsayilan_renk = (206, 214, 230)

            punto_kart = DETAY_PUNTO - 3
            satir_h = int(punto_kart * 1.5)
            blok_yuk = satir_h * len(b["satirlar"])
            # Zarif sol vurgu çizgisi (kutu yok, doğal ferah editoryal akış)
            ciz.rectangle([kenar, y, kenar + 4, y + blok_yuk], fill=kenar_renk)
            y_yazi = y
            for s in b["satirlar"]:
                _formatli_satir_ciz(ciz, kenar + 22, y_yazi, s, punto_kart, spot=False, varsayilan_renk=varsayilan_renk)
                y_yazi += satir_h
            y += blok_yuk

        elif tip == "trend_karti":
            img_tk = b["gorsel"]
            gorsel.paste(img_tk, (kenar, y), img_tk)
            y += b["yukseklik"]

        else:
            # Normal Detay Paragrafı (Spot veya Gelişme)
            punto = b.get("punto") or (DETAY_SPOT_PUNTO if b["spot"] else DETAY_PUNTO)
            satir_y = int(punto * 1.5)
            blok_yuk = satir_y * len(b["satirlar"])

            # Paragraf Başı Çentiği (Sleek Rounded Vertical Accent Notch):
            # 1. Paragraf (Spot): Canlı Amber (#E2AA58)
            # 2+ Paragraflar: Siber Turkuaz (#06B6D4)
            centik_renk = (226, 170, 88) if b["spot"] else (6, 182, 212)
            ciz.rounded_rectangle(
                [kenar, y + 4, kenar + 4, y + blok_yuk - 4],
                radius=2,
                fill=centik_renk
            )

            y_yazi = y
            for satir in b["satirlar"]:
                _formatli_satir_ciz(ciz, kenar + 24, y_yazi, satir, punto, spot=b["spot"])
                y_yazi += satir_y
            y += blok_yuk

        if i < len(bloklar) - 1:
            y += PARAGRAF_ARASI

    # --- Alt bilgi ---
    kucuk = _font(26, EKSEN_KUCUK)

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
        kanallar = (ayarlar.get("sosyal", {}) or {}).get("kanallar") or []
        boy = g.get("kanal_ikon_boyu", 26)
        toplam_g = len(kanallar) * boy + (len(kanallar) - 1) * 14 if kanallar else 0
        ikon_sol = genislik - (kenar + int(gen) + 24) - toplam_g
        _kaynak_satiri_ciz(ciz, kenar, alt_bilgi_y, kaynak, arsiv_ibaresi=arsiv_ibaresi, azami_sag_x=ikon_sol - 20)
        gorsel = kanal_ikonlari_bas(gorsel, gecici, alt_bilgi_y + 13)
    else:
        kanallar = (ayarlar.get("sosyal", {}) or {}).get("kanallar") or []
        boy = g.get("kanal_ikon_boyu", 26)
        toplam_g = len(kanallar) * boy + (len(kanallar) - 1) * 14 if kanallar else 0
        ikon_sol = genislik - kenar - toplam_g
        _kaynak_satiri_ciz(ciz, kenar, alt_bilgi_y, kaynak, arsiv_ibaresi=arsiv_ibaresi, azami_sag_x=ikon_sol - 20)
        gorsel = kanal_ikonlari_bas(gorsel, ayarlar, alt_bilgi_y + 13)

    if ulke_kodu:
        gorsel = _bayragi_bas(gorsel, ulke_kodu, ulke_adi, dikey_kenar)

    return gorsel


# ----------------------------------------------------------------------
# Kapak & Bülten Slaytları (kapak_bulten.py'den dışa aktarım)
# ----------------------------------------------------------------------
from .kapak_bulten import (
    AYLAR,
    gorsel_uret,
    haftalik_kapak_ciz,
    kapak_ciz,
    kapak_uret,
    kaynak_gosterim_adi,
    story_ekonomi_kapak,
    story_kapak,
    tarih_metni,
)

