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


def _font(punto: int, eksenler: list[float]) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT_YOLU), punto)
    try:
        f.set_variation_by_axes(eksenler)
    except Exception:
        pass            # değişken font desteği yoksa varsayılan ağırlıkla devam
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
            for w in part.split():
                if w:
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
        yaricap = 0.6 + t * 5.0
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
    foto: Image.Image, genislik: int, yukseklik: int
) -> Image.Image:
    """
    Ham haber veya basın fotoğrafını 1080x1920 dikey Story tuvaline akıllıca yerleştirir.

    - EXIF yön matrisini (ImageOps.exif_transpose) otomatik uygular; asla yan veya ters dönmez.
    - Dikey portreleri (ratio <= 0.8) üstten hizalı ve doğal derinlikle yerleştirir.
    - Yatay/16:9 basın fotoğraflarını (ratio > 0.8) aşırı dijital zoom ile kesip bulanıklaştırmak
      yerine, geniş kadrajıyla üst alana yerleştirir, arka plana yumuşak ambiyans ışıltısı verir
      ve alt metin alanına kesintisiz editoryal degrade ile eritir.
    """
    foto = ImageOps.exif_transpose(foto).convert("RGB")
    f_genislik, f_yukseklik = foto.size
    foto_oran = f_genislik / f_yukseklik

    canvas = Image.new("RGB", (genislik, yukseklik), (4, 24, 28))

    if foto_oran <= 0.78:
        # Doğal dikey portre (9:16 veya 4:5 portre)
        hedef_oran = genislik / yukseklik
        if foto_oran > hedef_oran:
            yeni_genislik = int(f_yukseklik * hedef_oran)
            sol = (f_genislik - yeni_genislik) // 2
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
            sol_k = (f_genislik - yeni_w) // 2
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
    return res


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


def serit_rengi(kategori: str, g: dict) -> tuple:
    """
    Metin şeridinin rengi — kategoriye göre.

    Renk konuyu başlık okunmadan sezdiriyor (spor yeşil, ekonomi bronz)
    ve carousel kaydırılırken tekdüzeliği kırıyor.

    ⚠️ SEÇİLEN RENKLER KOYU OLMAK ZORUNDA: şerit tam opak ve üstüne
    BEYAZ yazı basılıyor. Açık bir ton başlığı okunmaz yapar. Bu yüzden
    renkler config'de sabit listede duruyor, haberden türetilmiyor.
    """
    varsayilan = g.get("perde_rengi", [22, 18, 46])
    renkler = g.get("serit_renkleri") or {}
    return tuple(renkler.get(kategori, varsayilan))


LOGO_YOLU = KOK / "assets" / "logo_circular.png"


def _logoyu_bas(gorsel: Image.Image, x: int, y: int, boy: int = 144) -> Image.Image:
    """
    Sol üst veya belirtilen konuma DailyBrief dairesel logosunu basar (%50 büyütülmüş 144px).
    Logo arkasına yumuşak gölge ekleyerek her tür arka planda net ve premium görünmesini sağlar.
    """
    if not LOGO_YOLU.exists():
        return gorsel
    try:
        # 1. Logo arkasına yumuşak koyu gölge (drop shadow)
        golge = Image.new("RGBA", gorsel.size, (0, 0, 0, 0))
        gdraw = ImageDraw.Draw(golge)
        gdraw.ellipse([x - 4, y - 2, x + boy + 6, y + boy + 8], fill=(0, 0, 0, 175))
        golge = golge.filter(ImageFilter.GaussianBlur(10))
        gorsel = Image.alpha_composite(gorsel.convert("RGBA"), golge).convert("RGB")

        # 2. Logoyu bas
        logo = Image.open(LOGO_YOLU).convert("RGBA")
        logo = logo.resize((boy, boy), Image.Resampling.LANCZOS)
        gorsel.paste(logo, (x, y), mask=logo)
    except Exception as e:
        log.warning("logo basılamadı: %s", e)
    return gorsel


def _veri_rozeti_ciz(
    ciz: ImageDraw.ImageDraw,
    x: int,
    y: int,
    etiket: str,
    yeni: str,
    eski: str = "",
    yon: str = "artis",
) -> tuple[int, int]:
    """
    Slaytın üstüne mini infografik veri rozeti çizer.
    Döner: `(kart_genislik, kart_yukseklik)`
    """
    renk_map = {
        "artis": ((16, 185, 129), "▲"),
        "azalis": ((244, 63, 94), "▼"),
        "hedef": ((226, 170, 88), "◆"),
        "notr": ((148, 163, 184), "●"),
    }
    tema_renk, sembol = renk_map.get(yon or "artis", ((226, 170, 88), "●"))

    f_etiket = _font(21, [14.0, 600.0])
    f_deger = _font(30, [20.0, 800.0])
    f_eski = _font(21, [14.0, 500.0])

    metin_deger = f"{sembol} {yeni}"
    gen_deger = ciz.textlength(metin_deger, font=f_deger)
    gen_etiket = ciz.textlength(etiket.upper(), font=f_etiket)
    gen_eski = ciz.textlength(f"Önceki: {eski}", font=f_eski) if eski else 0

    kart_g = int(max(gen_deger, gen_etiket, gen_eski) + 36)
    kart_y = 92 if eski else 74

    # Cam petrol arkaplan ve renkli ince çerçeve
    ciz.rounded_rectangle(
        [x, y, x + kart_g, y + kart_y],
        radius=10,
        fill=(6, 18, 28),
        outline=(*tema_renk[:3],),
        width=2,
    )

    ciz.text((x + 16, y + 8), etiket.upper(), font=f_etiket, fill=(160, 174, 192))
    ciz.text((x + 16, y + 32), metin_deger, font=f_deger, fill=tema_renk)
    if eski:
        ciz.text((x + 16, y + 64), f"Önceki: {eski}", font=f_eski, fill=(130, 145, 165))

    return kart_g, kart_y


def split_portre_arkaplan(
    img1: Image.Image,
    img2: Image.Image,
    genislik: int = 1080,
    yukseklik: int = 1350,
) -> Image.Image:
    """
    İki resmi portreyi dikeyde altın ayırıcı çizgi ile birleştiren çift portre arka planı üretir.
    """
    canvas = Image.new("RGB", (genislik, yukseklik), (10, 15, 25))
    yarim = genislik // 2

    # 1. Sol yarı (Aktör 1)
    w1, h1 = img1.size
    oran1 = max(yarim / w1, yukseklik / h1)
    nw1, nh1 = int(w1 * oran1), int(h1 * oran1)
    r1 = img1.resize((nw1, nh1), Image.LANCZOS)
    x1 = (nw1 - yarim) // 2
    y1 = int(nh1 * 0.1)
    if y1 + yukseklik > nh1:
        y1 = max(0, nh1 - yukseklik)
    crop1 = r1.crop((x1, y1, x1 + yarim, y1 + yukseklik))
    canvas.paste(crop1, (0, 0))

    # 2. Sağ yarı (Aktör 2)
    w2, h2 = img2.size
    oran2 = max(yarim / w2, yukseklik / h2)
    nw2, nh2 = int(w2 * oran2), int(h2 * oran2)
    r2 = img2.resize((nw2, nh2), Image.LANCZOS)
    x2 = (nw2 - yarim) // 2
    y2 = int(nh2 * 0.1)
    if y2 + yukseklik > nh2:
        y2 = max(0, nh2 - yukseklik)
    crop2 = r2.crop((x2, y2, x2 + yarim, y2 + yukseklik))
    canvas.paste(crop2, (yarim, 0))

    # 3. Altın ayırıcı çizgi (Daily Brief kurumsal #E2AA58)
    ciz = ImageDraw.Draw(canvas)
    ciz.line([(yarim, 0), (yarim, yukseklik)], fill=(226, 170, 88), width=3)

def _kaynak_satiri_ciz(
    ciz: ImageDraw.Draw, kenar: int, alt_bilgi_y: int, kaynak: str, arsiv_ibaresi: bool = False
) -> None:
    """Slaytın sol altına şık bir altın nokta ve kaynak adını yazar."""
    kucuk = _font(26, EKSEN_KUCUK)
    # Zarif altın nokta
    ciz.ellipse([kenar, alt_bilgi_y + 8, kenar + 8, alt_bilgi_y + 16], fill=(226, 170, 88))
    metin = _buyuk_harf(kaynak)
    if arsiv_ibaresi:
        metin += "   ·   ARŞİV GÖRSELİ"
    ciz.text((kenar + 18, alt_bilgi_y), metin, font=kucuk, fill=(198, 206, 222))


def _son_dakika_rozeti(ciz, x: int, y: int) -> tuple[int, int]:
    """
    "SON DAKİKA" etiketini çizer, SAĞ ve ALT kenarını döner.

    ⚠️ NEDEN ORTAK FONKSİYON (5 Eyl 2026): etiket İKİ yerde ayrı ayrı
    çiziliyordu (`story_haber` ve `detay_slayti`) ve veri rozetini
    çizen `yaziyi_bas` ikisinden de habersizdi. Rozet sağa yaslı,
    etiket soldan başlıyor; ikisi genişleyince ÇAKIŞIYORLARDI.
    ÖLÇÜLDÜ (gerçek slayt, piksel taraması): etiket x 186→421, rozet
    x 372→890 — **49 piksel örtüşme**. Kullanıcı ekran görüntüsüyle
    bildirdi.

    Artık kutuyu tek fonksiyon üretiyor ve sınırlarını döndürüyor;
    yerleşimi yapan taraf nereye kadar dolu olduğunu biliyor.
    """
    f = _font(24, EKSEN_KUCUK)
    etiket = "SON DAKİKA"
    metin_g = ciz.textlength(etiket, font=f)
    sag = int(x + metin_g + 28)
    alt = int(y + 46)
    ciz.rounded_rectangle([x, y, sag, alt], radius=6, fill=(198, 60, 52))
    ciz.text((x + 14, y + 10), etiket, font=f, fill=(255, 255, 255))
    return sag, alt


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

    ozet_ust = alt_bilgi_y - (66 if son_slayt else 44) - ozet_yuksekligi
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
        _formatli_satir_ciz(ciz, kenar, y, satir, punto=34, spot=True, varsayilan_renk=(226, 232, 240))
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

    # Son slayt Call-To-Action (CTA) etkileşim rozeti
    if son_slayt:
        cta_font = _font(24, EKSEN_KUCUK)
        cta_metin = "★ Günün özetini kaçırmamak için kaydet & takip et"
        ciz.text((kenar, alt_bilgi_y - 36), cta_metin, font=cta_font, fill=(226, 170, 88))

    # Kaynak adı — şeffaflık ve gazetecilik atfı
    _kaynak_satiri_ciz(ciz, kenar, alt_bilgi_y, kaynak, arsiv_ibaresi=arsiv_ibaresi)

    # Sosyal kanal ikonları sağ altta: "bu içerik şu kanallarda da var".
    gorsel = kanal_ikonlari_bas(gorsel, ayarlar, alt_bilgi_y + 13)
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


def _ikon_youtube(ciz, x, y, boy, renk):
    """YouTube: Yuvarlak köşeli dikdörtgen + sağa bakan üçgen play ikonu."""
    r = boy // 4
    ciz.rounded_rectangle([x, y + boy * 0.12, x + boy, y + boy * 0.88], radius=r,
                          outline=renk, width=max(2, boy // 11))
    p1 = (x + boy * 0.40, y + boy * 0.32)
    p2 = (x + boy * 0.40, y + boy * 0.68)
    p3 = (x + boy * 0.70, y + boy * 0.50)
    ciz.polygon([p1, p2, p3], fill=renk)


def _ikon_tiktok(ciz, x, y, boy, renk):
    """TikTok: Müzik notası (nota başı, gövde ve üst bayrak)."""
    k = max(2, boy // 10)
    ciz.ellipse([x + boy * 0.18, y + boy * 0.55, x + boy * 0.58, y + boy * 0.90], fill=renk)
    ciz.line([(x + boy * 0.52, y + boy * 0.15), (x + boy * 0.52, y + boy * 0.72)], fill=renk, width=k)
    ciz.arc([x + boy * 0.52, y + boy * 0.12, x + boy * 0.90, y + boy * 0.50],
            start=270, end=90, fill=renk, width=k)


IKONLAR = {
    "instagram": _ikon_instagram,
    "threads": _ikon_threads,
    "facebook": _ikon_facebook,
    "x": _ikon_x,
    "youtube": _ikon_youtube,
    "tiktok": _ikon_tiktok,
}

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
    sag_x = g["genislik"] - g["kenar_bosluk"]
    toplam_genislik = len(kanallar) * boy + (len(kanallar) - 1) * 14
    sol_x = sag_x - toplam_genislik

    # 1. Sosyal Medya İkonlarının hemen üstüne tam ikon genişliğinde "dailybrief.co"
    web_txt = "dailybrief.co"
    f_web = _font(16, [14.0, 700.0])
    raw_w = ciz.textlength(web_txt, font=f_web)
    extra_space = (toplam_genislik - raw_w) / max(1, (len(web_txt) - 1))
    cur_x = sol_x
    web_y = y_merkez - boy - 10
    for ch in web_txt:
        ciz.text((cur_x, web_y), ch, font=f_web, fill=(160, 175, 195))
        cur_x += ciz.textlength(ch, font=f_web) + extra_space

    # 2. İkonları bas
    x = sag_x - boy
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
# story 9:16 ve ikisi aynı # Standart 4:5 dikey boyut (1080x1350)
GENISLIK = 1080
YUKSEKLIK = 1350


def sirali_exif(sira: int = 1) -> Image.Exif:
    """
    Telefon galerilerinin (iOS Photos / Android Gallery) fotoğrafları toplu kaydettiğinde
    1, 2, 3... sırasında dizmesi için artımlı EXIF zaman damgası ekler.
    """
    from PIL.ExifTags import Base
    exif = Image.Exif()
    # 2026-08-28 10:00:01, 10:00:02, 10:00:03...
    zaman_str = (datetime(2026, 8, 28, 10, 0, 0) + timedelta(seconds=max(1, int(sira)))).strftime("%Y:%m:%d %H:%M:%S")
    exif[Base.DateTime] = zaman_str
    exif[Base.DateTimeOriginal] = zaman_str
    exif[Base.DateTimeDigitized] = zaman_str
    return exif
STORY_GENISLIK, STORY_YUKSEKLIK = 1080, 1920

# 4:5 Güvenli Alan Payı: 9:16 (1080x1920) görselin içindeki tüm içerik
# (logo, başlık, özet, kaynak) 4:5 (1080x1350) merkez kutusunun (y=285..1635)
# içine güvenle sığar.
STORY_GUVENLI_PAY = 330


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

    # Derin Gece Mavisi / Antrasit gradyan zemin (#060B14 -> #02050A)
    img = Image.new("RGB", (genislik, yukseklik))
    draw = ImageDraw.Draw(img)

    for y in range(yukseklik):
        oran = y / float(yukseklik)
        r = int(6 * (1 - oran) + 2 * oran)
        g = int(11 * (1 - oran) + 5 * oran)
        b = int(20 * (1 - oran) + 10 * oran)
        draw.line([(0, y), (genislik, y)], fill=(r, g, b))

    # Atmosferik Çift Parıltı (Sol üst Kobalt Mavi, Sağ alt Sıcak Kehribar)
    glow = Image.new("RGBA", (genislik, yukseklik), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.ellipse([(-150, 100), (650, 700)], fill=(37, 99, 235, 45))
    gdraw.ellipse([(550, 1200), (1200, 1850)], fill=(245, 158, 11, 35))
    glow = glow.filter(ImageFilter.GaussianBlur(160))
    img.paste(Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB"), (0, 0))

    ciz = ImageDraw.Draw(img)
    alan_genislik = genislik - 2 * kenar

    # --- Üst Blok ---
    y = STORY_GUVENLI_PAY + 20

    # Rozet: DAILYBRIEF · GÜNÜN GÜNDEMİ
    rozet_txt = "DAILYBRIEF · GÜNÜN GÜNDEMİ"
    f_rozet = _font(22, 800.0)
    rw = ciz.textlength(rozet_txt, font=f_rozet)
    ciz.rounded_rectangle(
        [(kenar, y), (kenar + rw + 28, y + 42)],
        radius=8,
        fill=(28, 25, 23),
        outline=(245, 158, 11),
        width=2,
    )
    ciz.text((kenar + 14, y + 8), rozet_txt, font=f_rozet, fill=(245, 158, 11))
    y += 65

    # Başlık: GÜNÜN GÜNDEMİ
    b_font = _font(72, EKSEN_BASLIK)
    ciz.text((kenar, y), "GÜNÜN GÜNDEMİ", font=b_font, fill=(255, 255, 255))
    y += 90

    # Tarih ve Oturum
    simdi = datetime.now(timezone.utc)
    aksam_mi = simdi.hour >= 15
    oturum = "Akşam Özeti" if aksam_mi else "Sabah Özeti"
    tarih_str = f"{tarih_metni(gun)} · {oturum}"
    ciz.text((kenar, y), tarih_str, font=_font(28, EKSEN_KUCUK), fill=(226, 170, 88))
    y += 60

    ciz.line([(kenar, y), (genislik - kenar, y)], fill=(30, 41, 59), width=2)
    y += 40
    ust_alt = y

    # --- Alt Bilgi ---
    alt_bilgi_y = yukseklik - STORY_GUVENLI_PAY - 20
    hesap = ayarlar.get("instagram", {}).get("hesap_kullanici_adi", "dailybrief.co")

    # --- Manşet Listesi: Numaralı ve Ferah Kartlar ---
    madde_font = _font(36, EKSEN_OZET)
    satir_y = int(36 * 1.36)
    bloklar = [
        _satirlara_bol(b, madde_font, alan_genislik - 60, ciz)[:2]
        for b in basliklar[:5]
    ]

    kullanilabilir = alt_bilgi_y - 60 - ust_alt
    toplam = sum(len(x) * satir_y + 36 for x in bloklar)
    y = ust_alt + max(0, (kullanilabilir - toplam) // 2)

    for i, satirlar in enumerate(bloklar, start=1):
        ciz.rounded_rectangle([(kenar, y + 4), (kenar + 38, y + 42)], radius=8, fill=(28, 25, 23), outline=(245, 158, 11), width=1)
        ciz.text((kenar + 12, y + 8), str(i), font=_font(22, 800.0), fill=(245, 158, 11))

        cur_y = y
        for satir in satirlar:
            ciz.text((kenar + 52, cur_y), satir.replace("**", ""), font=madde_font, fill=(246, 243, 236))
            cur_y += satir_y
        y += max(cur_y - y, 42) + 32

    # --- Alt Bilgi & Çağrı ---
    ciz.line([(kenar, alt_bilgi_y - 20), (genislik - kenar, alt_bilgi_y - 20)], fill=(30, 41, 59), width=1)
    ciz.text((kenar, alt_bilgi_y), f"@{hesap}", font=_font(30, EKSEN_KUCUK), fill=(148, 163, 184))

    kaydir_txt = "Detaylar gönderide →"
    kw = ciz.textlength(kaydir_txt, font=_font(28, 700.0))
    ciz.text((genislik - kenar - kw, alt_bilgi_y), kaydir_txt, font=_font(28, 700.0), fill=(245, 158, 11))

    return img


def story_ekonomi_kapak(
    basliklar: list[str], ayarlar: dict, gun: date | None = None
) -> Image.Image:
    """
    Ekonomi ve Finans turunun 9:16 formatında lüks Derin Petrol & Siber Turkuaz temalı Story'si.
    """
    genislik, yukseklik = STORY_GENISLIK, STORY_YUKSEKLIK
    kenar = ayarlar["gorsel"]["kenar_bosluk"]

    # Derin petrol gradyan zemin
    img = Image.new("RGB", (genislik, yukseklik))
    draw = ImageDraw.Draw(img)

    for y in range(yukseklik):
        oran = y / float(yukseklik)
        r = int(4 * (1 - oran) + 3 * oran)
        g = int(24 * (1 - oran) + 16 * oran)
        b = int(28 * (1 - oran) + 20 * oran)
        draw.line([(0, y), (genislik, y)], fill=(r, g, b))

    glow = Image.new("RGBA", (genislik, yukseklik), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.ellipse([(-150, 100), (650, 700)], fill=(6, 182, 212, 45))
    gdraw.ellipse([(550, 1200), (1200, 1850)], fill=(6, 182, 212, 35))
    glow = glow.filter(ImageFilter.GaussianBlur(160))
    img.paste(Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB"), (0, 0))

    ciz = ImageDraw.Draw(img)
    alan_genislik = genislik - 2 * kenar

    # --- Üst Blok (Güvenli Payın Altı) ---
    y = STORY_GUVENLI_PAY + 20

    # Rozet: DAILYBRIEF · EKONOMİ & PİYASALAR
    rozet_txt = "DAILYBRIEF · EKONOMİ & PİYASALAR"
    f_rozet = _font(22, 800.0)
    rw = ciz.textlength(rozet_txt, font=f_rozet)
    ciz.rounded_rectangle(
        [(kenar, y), (kenar + rw + 28, y + 42)],
        radius=8,
        fill=(18, 62, 72),
        outline=(6, 182, 212),
        width=2,
    )
    ciz.text((kenar + 14, y + 8), rozet_txt, font=f_rozet, fill=(6, 182, 212))
    y += 65

    # Başlık: EKONOMİ & PİYASA TURU
    b_font = _font(72, EKSEN_BASLIK)
    ciz.text((kenar, y), "EKONOMİ & PİYASA TURU", font=b_font, fill=(255, 255, 255))
    y += 90

    # Tarih ve Alt Başlık
    simdi = datetime.now(timezone.utc)
    aksam_mi = simdi.hour >= 15
    oturum = "Akşam Kapanış Özeti" if aksam_mi else "Sabah Açılış Özeti"
    tarih_str = f"{tarih_metni(gun)} · {oturum}"
    ciz.text((kenar, y), tarih_str, font=_font(28, EKSEN_KUCUK), fill=(245, 158, 11))
    y += 60

    ciz.line([(kenar, y), (genislik - kenar, y)], fill=(24, 75, 85), width=2)
    y += 40
    ust_alt = y

    # --- Alt Bilgi ---
    alt_bilgi_y = yukseklik - STORY_GUVENLI_PAY - 20
    hesap = ayarlar.get("instagram", {}).get("hesap_kullanici_adi", "dailybrief.co")

    # --- Manşet Listesi: Ferah ve Numaralandırılmış Kartlar ---
    madde_font = _font(36, EKSEN_OZET)
    satir_y = int(36 * 1.36)
    bloklar = [
        _satirlara_bol(b, madde_font, alan_genislik - 60, ciz)[:2]
        for b in basliklar[:5]
    ]

    kullanilabilir = alt_bilgi_y - 60 - ust_alt
    toplam = sum(len(x) * satir_y + 36 for x in bloklar)
    y = ust_alt + max(0, (kullanilabilir - toplam) // 2)

    for i, satirlar in enumerate(bloklar, start=1):
        # Sol Numaralı Rozet
        ciz.rounded_rectangle([(kenar, y + 4), (kenar + 38, y + 42)], radius=8, fill=(18, 62, 74), outline=(6, 182, 212), width=1)
        ciz.text((kenar + 12, y + 8), str(i), font=_font(22, 800.0), fill=(6, 182, 212))

        # Metin Satırları
        cur_y = y
        for satir in satirlar:
            ciz.text((kenar + 52, cur_y), satir.replace("**", ""), font=madde_font, fill=(246, 243, 236))
            cur_y += satir_y
        y += max(cur_y - y, 42) + 32

    # --- Alt Bilgi & Çağrı ---
    ciz.line([(kenar, alt_bilgi_y - 20), (genislik - kenar, alt_bilgi_y - 20)], fill=(24, 75, 85), width=1)
    ciz.text((kenar, alt_bilgi_y), f"@{hesap}", font=_font(30, EKSEN_KUCUK), fill=(140, 185, 195))

    kaydir_txt = "Detaylar gönderide →"
    kw = ciz.textlength(kaydir_txt, font=_font(28, 700.0))
    ciz.text((genislik - kenar - kw, alt_bilgi_y), kaydir_txt, font=_font(28, 700.0), fill=(6, 182, 212))

    return img


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
        arkaplan = fotograftan_arkaplan(
            arkaplan, STORY_GENISLIK, STORY_YUKSEKLIK
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


def detay_sayfalara_bol(
    detay: str, ayarlar: dict,
    vurgu: tuple[str, str] | None = None,
    alinti: tuple[str, str] | None = None,
    neden_onemli: str | None = None,
    sirada_ne_var: str | None = None,
    trend_karti: Image.Image | None = None,
    sana_etkisi: str | None = None,
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
        punto = DETAY_SPOT_PUNTO if spot else DETAY_PUNTO
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
                                "yukseklik": int(punto * 1.5) * len(sat_1)})
                bloklar.append({"tip": "metin", "satirlar": sat_2, "spot": False,
                                "yukseklik": int(DETAY_PUNTO * 1.5) * len(sat_2)})
            else:
                bloklar.append({"tip": "metin", "satirlar": satirlar, "spot": spot,
                                "yukseklik": yukseklik_px})
        else:
            bloklar.append({"tip": "metin", "satirlar": satirlar, "spot": spot,
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

    # Sayfalara dağıt
    sayfalar, gecerli, dolu = [], [], 0
    for blok in bloklar:
        gerekli = blok["yukseklik"] + (PARAGRAF_ARASI if gecerli else 0)
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

        elif tip in ("neden_onemli", "sirada_ne_var", "sana_etkisi"):
            if tip == "sana_etkisi":
                kenar_renk = (16, 185, 129)  # Parlak Zümrüt Yeşili (Emerald)
                varsayilan_renk = (220, 252, 231)
            elif tip == "neden_onemli":
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
    _kaynak_satiri_ciz(ciz, kenar, alt_bilgi_y, kaynak, arsiv_ibaresi=arsiv_ibaresi)

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


def kaynak_gosterim_adi(kaynak: str, ayarlar: dict) -> str:
    """
    Slaytta ve caption'da görünecek kaynak adı.

    ⚠️ NEDEN GEREKTİ (20 Ağu 2026): slayta RSS BESLEMESİNİN adı
    basılıyordu. "ABD, Katar'a yakıt ikmal uçağı satışını onayladı"
    haberi AA'nın ekonomi beslemesinden geldiği için slaytta
    **AA EKONOMİ** yazdı ve kullanıcı haklı olarak "bu haber neden
    ekonomi kategorisinde" diye sordu — haber ekonomi değil, savunma.

    Besleme adı bizim İÇ kaydımız (tekrar engeli ve ölçüm ona bakıyor);
    okuyucuya gösterilmesi gereken YAYIN KURULUŞU. Eşleme
    `config.yaml → kaynaklar[].gosterim_adi` alanında; tanımlı değilse
    besleme adı olduğu gibi kullanılıyor.

    ⚠️ Bu kategori kusurunun YALNIZCA GÖRÜNEN yüzü. `kategori` kolonu
    hâlâ beslemeden geliyor (CLAUDE.md 1i) ve şerit rengini o
    belirliyor — ayrı bir iş.
    """
    if not kaynak:
        return ""
    for k in (ayarlar or {}).get("kaynaklar", []):
        if k.get("ad") == kaynak:
            return k.get("gosterim_adi") or kaynak
    return kaynak


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
    # Perde rengi haber slaytlarıyla AYNI olmalı: story ve post aynı
    # turdan çıkıyor, farklı renk kullanmak iki ayrı hesabın işi gibi
    # duruyor. Siyahtan marka rengine çevrildi (18 Ağu 2026).
    story_renk = tuple(g.get("perde_rengi", [22, 18, 46]))
    taban = _perde_taban_alfa(gorsel, (0, 0, genislik, yukseklik))
    if taban > 0:
        perde = Image.new("RGBA", (genislik, yukseklik),
                          story_renk + (int(taban * 0.85),))
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
        ciz.text((kenar + 2, y + 2), satir.replace("**", ""), font=font, fill=(0, 0, 0))
        ciz.text((kenar, y), satir.replace("**", ""), font=font, fill=(255, 255, 255))
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
        arkaplan = arkaplan_uret_yedek(kategori, g["genislik"], g["yukseklik"], g)
        kaynak_tipi = "yedek"

    gorsel = yaziyi_bas(arkaplan, baslik,
                        kaynak_gosterim_adi(haber["kaynak"], ayarlar),
                        ayarlar)

    yol = CIKTI_KLASORU / f"haber-{haber['id']}.jpg"
    # Instagram PNG kabul etmiyor — JPEG şart (subsampling=0 ile kristal netlik)
    gorsel.save(yol, "JPEG", quality=g["jpeg_kalite"], subsampling=0, optimize=True)
    log.info("görsel üretildi (%s): %s", kaynak_tipi, yol)
    return yol


def haftalik_kapak_ciz(
    basliklar: list[str],
    ayarlar: dict,
    baslangic: date | None = None,
    bitis: date | None = None,
) -> Image.Image:
    """
    Haftalık Pazar bülteni için özel 'HAFTANIN ÖZETİ' kapak slaytı üretir.
    4:5 dikey format (1080x1350).
    """
    g = ayarlar["gorsel"]
    genislik, yukseklik = g["genislik"], g["yukseklik"]
    kenar = g["kenar_bosluk"]
    dikey_kenar = g.get("dikey_kenar_bosluk", g.get("kenar_bosluk", 60))
    alan_genislik = genislik - 2 * kenar

    gorsel = arkaplan_uret_yedek("turkiye", genislik, yukseklik, g)
    ciz = ImageDraw.Draw(gorsel)

    # --- Üst blok (144px Logo + Amber Rozet) ---
    gorsel = _logoyu_bas(gorsel, kenar, dikey_kenar - 16, boy=144)
    ciz = ImageDraw.Draw(gorsel)

    rozet_x = kenar + 162
    rozet_y = dikey_kenar + 15
    rozet_w = 260
    rozet_h = 36
    ciz.rounded_rectangle(
        [(rozet_x, rozet_y), (rozet_x + rozet_w, rozet_y + rozet_h)],
        radius=6,
        fill=(226, 170, 88),
    )
    ciz.text(
        (rozet_x + 16, rozet_y + 7),
        "HAFTANIN ÖZETİ",
        font=_font(20, [14.0, 800.0]),
        fill=(10, 20, 30),
    )

    # Tarih Aralığı (Örn: 17 – 23 AĞUSTOS 2026)
    if bitis is None:
        bitis = date.today()
    if baslangic is None:
        baslangic = bitis - timedelta(days=6)

    ay_adi = AYLAR[bitis.month - 1]
    tarih_str = f"{baslangic.day} – {bitis.day} {ay_adi} {bitis.year}"
    ciz.text(
        (rozet_x, rozet_y + 44),
        tarih_str,
        font=_font(24, EKSEN_KUCUK),
        fill=(226, 170, 88),
    )

    # Ana Başlık
    y = dikey_kenar + 140
    ana_baslik = "Haftanın Öne Çıkan Gelişmeleri"
    baslik_font = _font(58, EKSEN_BASLIK)
    baslik_satirlari = _satirlara_bol(ana_baslik, baslik_font, alan_genislik, ciz)
    for s in baslik_satirlari:
        ciz.text((kenar, y), s, font=baslik_font, fill=(255, 255, 255))
        y += int(58 * 1.18)

    # Ayırıcı İnce Şerit
    y += 15
    ciz.rectangle([(kenar, y), (kenar + 100, y + 4)], fill=(226, 170, 88))
    y += 30

    # --- Manşet Listesi (Maddeler) ---
    alt_bilgi_y = yukseklik - dikey_kenar - 10
    madde_font = _font(27, EKSEN_OZET)
    satir_y = int(27 * 1.32)

    for i, b in enumerate(basliklar[:5], start=1):
        blok = _satirlara_bol(b, madde_font, alan_genislik - 45, ciz)[:2]
        # Küçük altın nokta
        ciz.ellipse([kenar, y + 10, kenar + 10, y + 20], fill=(226, 170, 88))
        for satir in blok:
            ciz.text((kenar + 26, y), satir.replace("**", ""), font=madde_font, fill=(226, 231, 242))
            y += satir_y
        y += 18
        if y > alt_bilgi_y - 60:
            break

    # --- Alt Bilgi & 4 Kanal İkonu ---
    kucuk = _font(24, EKSEN_KUCUK)
    hesap = ayarlar.get("instagram", {}).get("hesap_kullanici_adi", "")
    if hesap:
        ciz.text((kenar, alt_bilgi_y), f"@{hesap}  ·  Haftalık Bülten", font=kucuk, fill=(198, 206, 222))

    gorsel = kanal_ikonlari_bas(gorsel, ayarlar, alt_bilgi_y + 12)
    return gorsel

