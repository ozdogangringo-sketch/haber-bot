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
import time
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import db

log = logging.getLogger(__name__)
load_dotenv()

KOK = Path(__file__).resolve().parent.parent
FONT_YOLU = KOK / "assets" / "fonts" / "Inter-Variable.ttf"
CIKTI_KLASORU = KOK / "data" / "output"

UC_NOKTA = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

GECICI_HATALAR = {429, 500, 502, 503, 504}

# Inter değişken fontunun eksen sırası: [Optical size, Weight]
EKSEN_BASLIK = [32.0, 800.0]      # kalın, büyük punto için
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
    "Abstract background for a news graphic, square format. "
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
                        "imageConfig": {"aspectRatio": "1:1"},
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


def _basligi_yerlestir(metin: str, ciz, alan_genislik: int, alan_yukseklik: int):
    """
    Başlığı alana sığdıran en büyük puntoyu bulur.
    Büyükten küçüğe deniyoruz: başlık kısaysa iri, uzunsa küçük olsun.
    """
    for punto in range(96, 39, -4):
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


def yaziyi_bas(
    arkaplan: Image.Image, baslik: str, kaynak: str, ayarlar: dict,
    perde_basi_orani: float = 0.30,
) -> Image.Image:
    """Arka planın üstüne başlığı ve kaynak adını yazar."""
    g = ayarlar["gorsel"]
    genislik, yukseklik = g["genislik"], g["yukseklik"]
    kenar = g["kenar_bosluk"]

    gorsel = arkaplan.resize((genislik, yukseklik), Image.LANCZOS)

    # Okunabilirlik garantisi: arka plan her seferinde farklı — AI görseli,
    # gerçek fotoğraf veya gradyan olabiliyor. Açık bir yer denk gelirse
    # beyaz yazı kaybolur. Alt kısma koyu perde çekiyoruz.
    # Fotoğraflarda perde daha güçlü olmalı: portrenin açık tonları
    # yazıyı yutuyor.
    perde = Image.new("RGBA", (genislik, yukseklik), (0, 0, 0, 0))
    perde_ciz = ImageDraw.Draw(perde)
    perde_basi = int(yukseklik * perde_basi_orani)
    for y in range(perde_basi, yukseklik):
        oran = (y - perde_basi) / (yukseklik - perde_basi)
        # Karesel artış: üstte yumuşak başlasın, altta tam kapatsın
        perde_ciz.line(
            [(0, y), (genislik, y)], fill=(0, 0, 0, int(238 * (oran ** 1.5)))
        )
    gorsel = Image.alpha_composite(gorsel.convert("RGBA"), perde).convert("RGB")

    ciz = ImageDraw.Draw(gorsel)
    alan_genislik = genislik - 2 * kenar
    alan_yukseklik = int(yukseklik * 0.42)

    font, satirlar, satir_yuksekligi = _basligi_yerlestir(
        baslik, ciz, alan_genislik, alan_yukseklik
    )

    # Alt bilgi satırının üstünde bitecek şekilde yukarıdan hizala
    alt_bilgi_y = yukseklik - kenar - 34
    y = alt_bilgi_y - 46 - satir_yuksekligi * len(satirlar)

    for satir in satirlar:
        # Hafif gölge: açık arka planda bile kenarları ayrışsın
        ciz.text((kenar + 2, y + 2), satir, font=font, fill=(0, 0, 0, 160))
        ciz.text((kenar, y), satir, font=font, fill=(255, 255, 255))
        y += satir_yuksekligi

    # Kaynak adı — telif değil, şeffaflık için: haber nereden geldi
    kucuk = _font(26, EKSEN_KUCUK)
    ciz.text(
        (kenar, alt_bilgi_y),
        kaynak.upper(),
        font=kucuk,
        fill=(198, 206, 222),
    )

    # Sol üstte ince vurgu çizgisi — hesaba tutarlı bir imza katsın
    ciz.rectangle(
        [kenar, kenar, kenar + 92, kenar + 7],
        fill=(226, 170, 88),
    )
    return gorsel


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
