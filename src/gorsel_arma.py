"""
gorsel_arma.py — Kurumsal marka öğeleri, logo, ülke flaması, rozetler ve sosyal kanal ikonları.

`make_image.py` şişkinliğini önlemek için kurumsal kimlik, ikon ve rozet çizim fonksiyonları
bu modülde toplanmıştır. Geriye dönük uyumluluk için `make_image.py` tarafından da dışa aktarılır.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from . import fetch_flag

log = logging.getLogger(__name__)

KOK = Path(__file__).resolve().parent.parent
LOGO_YOLU = KOK / "assets" / "logo_circular.png"
LOGO_KLASORU = KOK / "assets" / "icons"
_logo_onbellek: dict[tuple[str, int], Image.Image] = {}


def _bayragi_bas(
    gorsel: Image.Image, ulke_kodu: str, ulke_adi: str, kenar: int
) -> Image.Image:
    """
    Sağ üst köşeye ülke flaması basar: sağ kenara yapışık, sol ucu
    kırlangıç kuyruğu (içe doğru V çentik).
    """
    from .make_image import EKSEN_KUCUK, _buyuk_harf, _font

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

    ust_pay, ara, alt_pay = 9, 6, 9
    yazi_yuk = 19 if metin else 0
    icerik_gen = int(max(b_gen, metin_genislik))
    yukseklik = ust_pay + b_yuk + (ara + yazi_yuk if metin else 0) + alt_pay

    uc_payi = 38
    ic_sol, ic_sag = 22, 28
    genislik = uc_payi + ic_sol + icerik_gen + ic_sag

    x1 = gorsel.width
    x0 = x1 - genislik
    y0 = kenar - 10
    y1 = y0 + yukseklik
    orta_y = (y0 + y1) / 2

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
    """Metin şeridinin rengi — kategoriye göre."""
    varsayilan = g.get("perde_rengi", [22, 18, 46])
    renkler = g.get("serit_renkleri") or {}
    return tuple(renkler.get(kategori, varsayilan))


def _logoyu_bas(gorsel: Image.Image, x: int, y: int, boy: int = 144) -> Image.Image:
    """
    Sol üst veya belirtilen konuma DailyBrief dairesel logosunu basar (%50 büyütülmüş 144px).
    Logo arkasına yumuşak gölge ekleyerek her tür arka planda net ve premium görünmesini sağlar.
    """
    if not LOGO_YOLU.exists():
        return gorsel
    try:
        golge = Image.new("RGBA", gorsel.size, (0, 0, 0, 0))
        gdraw = ImageDraw.Draw(golge)
        gdraw.ellipse([x - 4, y - 2, x + boy + 6, y + boy + 8], fill=(0, 0, 0, 175))
        golge = golge.filter(ImageFilter.GaussianBlur(10))
        gorsel = Image.alpha_composite(gorsel.convert("RGBA"), golge).convert("RGB")

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
    from .make_image import _font

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

    ciz = ImageDraw.Draw(canvas)
    ciz.line([(yarim, 0), (yarim, yukseklik)], fill=(226, 170, 88), width=3)
    return canvas


def _kaynak_satiri_ciz(
    ciz: ImageDraw.Draw, kenar: int, alt_bilgi_y: int, kaynak: str, arsiv_ibaresi: bool = False
) -> None:
    """Slaytın sol altına şık bir altın nokta ve kaynak adını yazar."""
    from .make_image import EKSEN_KUCUK, _buyuk_harf, _font

    kucuk = _font(26, EKSEN_KUCUK)
    ciz.ellipse([kenar, alt_bilgi_y + 8, kenar + 8, alt_bilgi_y + 16], fill=(226, 170, 88))
    metin = _buyuk_harf(kaynak)
    if arsiv_ibaresi:
        metin += "   ·   ARŞİV GÖRSELİ"
    ciz.text((kenar + 18, alt_bilgi_y), metin, font=kucuk, fill=(198, 206, 222))


def _son_dakika_rozeti(ciz, x: int, y: int) -> tuple[int, int]:
    """
    "SON DAKİKA" etiketini çizer, SAĞ ve ALT kenarını döner.
    """
    from .make_image import EKSEN_KUCUK, _font

    f = _font(24, EKSEN_KUCUK)
    etiket = "SON DAKİKA"
    metin_g = ciz.textlength(etiket, font=f)
    sag = int(x + metin_g + 28)
    alt = int(y + 46)
    ciz.rounded_rectangle([x, y, sag, alt], radius=6, fill=(198, 60, 52))
    ciz.text((x + 14, y + 10), etiket, font=f, fill=(255, 255, 255))
    return sag, alt


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
    from .make_image import _font

    ciz.ellipse([x, y, x + boy, y + boy], outline=renk,
                width=max(2, boy // 11))
    f = _font(int(boy * 0.72), [14.0, 700.0])
    g = ciz.textlength("f", font=f)
    ciz.text((x + (boy - g) / 2, y + boy * 0.12), "f", font=f, fill=renk)


def _ikon_threads(ciz, x, y, boy, renk):
    """Threads: üstte sağa, altta sola dolanan iki kavis ve dikey gövde."""
    k = max(2, boy // 10)
    ciz.arc([x + boy * 0.16, y + boy * 0.36, x + boy * 0.84, y + boy * 0.96],
            start=300, end=200, fill=renk, width=k)
    ciz.arc([x + boy * 0.16, y + boy * 0.04, x + boy * 0.84, y + boy * 0.64],
            start=170, end=40, fill=renk, width=k)
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


def _logo_maskesi(ad: str, boy: int):
    """Logonun alfa kanalını maske olarak döner, yoksa None."""
    anahtar = (ad, boy)
    if anahtar in _logo_onbellek:
        return _logo_onbellek[anahtar]

    yol = LOGO_KLASORU / f"{ad}.png"
    if not yol.exists():
        return None
    try:
        logo = Image.open(yol).convert("RGBA")
        oran = min(boy / logo.width, boy / logo.height)
        yeni = (max(1, int(logo.width * oran)), max(1, int(logo.height * oran)))
        maske = logo.resize(yeni, Image.LANCZOS).split()[-1]
    except Exception as e:
        log.warning("logo okunamadı (%s): %s", ad, e)
        return None

    _logo_onbellek[anahtar] = maske
    return maske


def kanal_ikonlari_bas(gorsel, ayarlar, y_merkez: int, renk=(150, 160, 180)):
    """Slaytın alt bilgisine sosyal kanal ikonlarını basar."""
    from .make_image import _font

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

    web_txt = "dailybrief.co"
    f_web = _font(16, [14.0, 700.0])
    raw_w = ciz.textlength(web_txt, font=f_web)
    extra_space = (toplam_genislik - raw_w) / max(1, (len(web_txt) - 1))
    cur_x = sol_x
    web_y = y_merkez - boy - 10
    for ch in web_txt:
        ciz.text((cur_x, web_y), ch, font=f_web, fill=(160, 175, 195))
        cur_x += ciz.textlength(ch, font=f_web) + extra_space

    x = sag_x - boy
    for ad in reversed(kanallar):
        maske = _logo_maskesi(ad, boy)
        if maske is not None:
            ust = y_merkez - maske.height // 2
            sol = x + (boy - maske.width) // 2
            gorsel.paste(renk, (sol, ust), maske)
        elif ad in IKONLAR:
            IKONLAR[ad](ciz, x, y_merkez - boy // 2, boy, renk)
        else:
            continue
        x -= ara
    return gorsel


def sirali_exif(sira: int = 1) -> Image.Exif:
    """
    Telefon galerilerinin (iOS Photos / Android Gallery) fotoğrafları toplu kaydettiğinde
    1, 2, 3... sırasında dizmesi için artımlı EXIF zaman damgası ekler.
    """
    from PIL.ExifTags import Base
    exif = Image.Exif()
    zaman_str = (datetime(2026, 8, 28, 10, 0, 0) + timedelta(seconds=max(1, int(sira)))).strftime("%Y:%m:%d %H:%M:%S")
    exif[Base.DateTime] = zaman_str
    exif[Base.DateTimeOriginal] = zaman_str
    exif[Base.DateTimeDigitized] = zaman_str
    return exif
