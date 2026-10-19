"""
kapak_bulten.py — Bülten, Tur ve Haftalık Özet kapak slaytı üreticileri.

`make_image.py` şişkinliğini önlemek için Günün Gündemi / Ekonomi Turu / Haftalık Özet
kapak çizim fonksiyonları ve tarih/kaynak yardımcıları bu modülde toplanmıştır.
Geriye dönük uyumluluk için `make_image.py` tarafından da dışa aktarılır.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

log = logging.getLogger(__name__)

AYLAR = ["OCAK", "ŞUBAT", "MART", "NİSAN", "MAYIS", "HAZİRAN",
         "TEMMUZ", "AĞUSTOS", "EYLÜL", "EKİM", "KASIM", "ARALIK"]


def kaynak_gosterim_adi(kaynak: str, ayarlar: dict) -> str:
    """Slaytta ve caption'da görünecek kaynak adı."""
    if not kaynak:
        return ""
    for k in (ayarlar or {}).get("kaynaklar", []):
        if k.get("ad") == kaynak:
            return k.get("gosterim_adi") or kaynak
    return kaynak


def tarih_metni(gun: date | None = None) -> str:
    """'15 AĞUSTOS 2026' üretir."""
    gun = gun or date.today()
    return f"{gun.day} {AYLAR[gun.month - 1]} {gun.year}"


def story_kapak(
    basliklar: list[str], ayarlar: dict, gun: date | None = None
) -> Image.Image:
    """Akşam turunun story'si: günün manşet listesi (9:16)."""
    from .make_image import (
        EKSEN_BASLIK,
        EKSEN_KUCUK,
        EKSEN_OZET,
        STORY_GENISLIK,
        STORY_GUVENLI_PAY,
        STORY_YUKSEKLIK,
        _font,
        _satirlara_bol,
    )

    genislik, yukseklik = STORY_GENISLIK, STORY_YUKSEKLIK
    kenar = ayarlar["gorsel"]["kenar_bosluk"]

    img = Image.new("RGB", (genislik, yukseklik))
    draw = ImageDraw.Draw(img)

    for y in range(yukseklik):
        oran = y / float(yukseklik)
        r = int(6 * (1 - oran) + 2 * oran)
        g = int(11 * (1 - oran) + 5 * oran)
        b = int(20 * (1 - oran) + 10 * oran)
        draw.line([(0, y), (genislik, y)], fill=(r, g, b))

    glow = Image.new("RGBA", (genislik, yukseklik), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.ellipse([(-150, 100), (650, 700)], fill=(37, 99, 235, 45))
    gdraw.ellipse([(550, 1200), (1200, 1850)], fill=(245, 158, 11, 35))
    glow = glow.filter(ImageFilter.GaussianBlur(160))
    img.paste(Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB"), (0, 0))

    ciz = ImageDraw.Draw(img)
    alan_genislik = genislik - 2 * kenar

    y = STORY_GUVENLI_PAY + 20

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

    b_font = _font(72, EKSEN_BASLIK)
    ciz.text((kenar, y), "GÜNÜN GÜNDEMİ", font=b_font, fill=(255, 255, 255))
    y += 90

    simdi = datetime.now(timezone.utc)
    aksam_mi = simdi.hour >= 15
    oturum = "Akşam Özeti" if aksam_mi else "Sabah Özeti"
    tarih_str = f"{tarih_metni(gun)} · {oturum}"
    ciz.text((kenar, y), tarih_str, font=_font(28, EKSEN_KUCUK), fill=(226, 170, 88))
    y += 60

    ciz.line([(kenar, y), (genislik - kenar, y)], fill=(30, 41, 59), width=2)
    y += 40
    ust_alt = y

    alt_bilgi_y = yukseklik - STORY_GUVENLI_PAY - 20
    hesap = ayarlar.get("instagram", {}).get("hesap_kullanici_adi", "dailybrief.co")

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

    ciz.line([(kenar, alt_bilgi_y - 20), (genislik - kenar, alt_bilgi_y - 20)], fill=(30, 41, 59), width=1)
    ciz.text((kenar, alt_bilgi_y), f"@{hesap}", font=_font(30, EKSEN_KUCUK), fill=(148, 163, 184))

    kaydir_txt = "Detaylar gönderide →"
    kw = ciz.textlength(kaydir_txt, font=_font(28, 700.0))
    ciz.text((genislik - kenar - kw, alt_bilgi_y), kaydir_txt, font=_font(28, 700.0), fill=(245, 158, 11))

    return img


def story_ekonomi_kapak(
    basliklar: list[str], ayarlar: dict, gun: date | None = None
) -> Image.Image:
    """Ekonomi ve Finans turunun 9:16 formatında lüks Derin Petrol & Siber Turkuaz temalı Story'si."""
    from .make_image import (
        EKSEN_BASLIK,
        EKSEN_KUCUK,
        EKSEN_OZET,
        STORY_GENISLIK,
        STORY_GUVENLI_PAY,
        STORY_YUKSEKLIK,
        _font,
        _satirlara_bol,
    )

    genislik, yukseklik = STORY_GENISLIK, STORY_YUKSEKLIK
    kenar = ayarlar["gorsel"]["kenar_bosluk"]

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

    y = STORY_GUVENLI_PAY + 20

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

    b_font = _font(72, EKSEN_BASLIK)
    ciz.text((kenar, y), "EKONOMİ & PİYASA TURU", font=b_font, fill=(255, 255, 255))
    y += 90

    simdi = datetime.now(timezone.utc)
    aksam_mi = simdi.hour >= 15
    oturum = "Akşam Kapanış Özeti" if aksam_mi else "Sabah Açılış Özeti"
    tarih_str = f"{tarih_metni(gun)} · {oturum}"
    ciz.text((kenar, y), tarih_str, font=_font(28, EKSEN_KUCUK), fill=(245, 158, 11))
    y += 60

    ciz.line([(kenar, y), (genislik - kenar, y)], fill=(24, 75, 85), width=2)
    y += 40
    ust_alt = y

    alt_bilgi_y = yukseklik - STORY_GUVENLI_PAY - 20
    hesap = ayarlar.get("instagram", {}).get("hesap_kullanici_adi", "dailybrief.co")

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
        ciz.rounded_rectangle([(kenar, y + 4), (kenar + 38, y + 42)], radius=8, fill=(18, 62, 74), outline=(6, 182, 212), width=1)
        ciz.text((kenar + 12, y + 8), str(i), font=_font(22, 800.0), fill=(6, 182, 212))

        cur_y = y
        for satir in satirlar:
            ciz.text((kenar + 52, cur_y), satir.replace("**", ""), font=madde_font, fill=(246, 243, 236))
            cur_y += satir_y
        y += max(cur_y - y, 42) + 32

    ciz.line([(kenar, alt_bilgi_y - 20), (genislik - kenar, alt_bilgi_y - 20)], fill=(24, 75, 85), width=1)
    ciz.text((kenar, alt_bilgi_y), f"@{hesap}", font=_font(30, EKSEN_KUCUK), fill=(140, 185, 195))

    kaydir_txt = "Detaylar gönderide →"
    kw = ciz.textlength(kaydir_txt, font=_font(28, 700.0))
    ciz.text((genislik - kenar - kw, alt_bilgi_y), kaydir_txt, font=_font(28, 700.0), fill=(6, 182, 212))

    return img


def kapak_ciz(
    arkaplan: Image.Image,
    ayarlar: dict,
    basliklar: list[str] | None = None,
    ust_yazi: str = "GÜNÜN GÜNDEMİ",
    gun: date | None = None,
) -> Image.Image:
    """Carousel'in ilk slaytı."""
    from .make_image import (
        EKSEN_KUCUK,
        EKSEN_OZET,
        _basligi_yerlestir,
        _font,
        _perde_taban_alfa,
        _satirlara_bol,
    )

    g = ayarlar["gorsel"]
    genislik, yukseklik = g["genislik"], g["yukseklik"]
    kenar = g["kenar_bosluk"]

    gorsel = arkaplan.resize((genislik, yukseklik), Image.LANCZOS)
    alan_genislik = genislik - 2 * kenar

    story_renk = tuple(g.get("perde_rengi", [22, 18, 46]))
    taban = _perde_taban_alfa(gorsel, (0, 0, genislik, yukseklik))
    if taban > 0:
        perde = Image.new("RGBA", (genislik, yukseklik),
                          story_renk + (int(taban * 0.85),))
        gorsel = Image.alpha_composite(gorsel.convert("RGBA"), perde).convert("RGB")

    ciz = ImageDraw.Draw(gorsel)

    ciz.rectangle([kenar, kenar, kenar + 92, kenar + 7], fill=(226, 170, 88))
    ciz.text(
        (kenar, kenar + 34),
        tarih_metni(gun),
        font=_font(30, EKSEN_KUCUK),
        fill=(226, 170, 88),
    )

    font, satirlar, satir_yuksekligi = _basligi_yerlestir(
        ust_yazi, ciz, alan_genislik, int(yukseklik * 0.26)
    )
    y = kenar + 104
    for satir in satirlar:
        ciz.text((kenar + 2, y + 2), satir.replace("**", ""), font=font, fill=(0, 0, 0))
        ciz.text((kenar, y), satir.replace("**", ""), font=font, fill=(255, 255, 255))
        y += satir_yuksekligi
    baslik_alti = y

    alt_bilgi_y = yukseklik - kenar - 34

    if basliklar:
        madde_font = _font(31, EKSEN_OZET)
        satir_y = int(31 * 1.34)
        bloklar = [
            _satirlara_bol(b, madde_font, alan_genislik - 34, ciz)[:2]
            for b in basliklar
        ]

        while bloklar:
            toplam = sum(len(b) * satir_y + 18 for b in bloklar)
            if alt_bilgi_y - 30 - toplam > baslik_alti + 30:
                break
            bloklar.pop()

        y = alt_bilgi_y - 30 - sum(len(b) * satir_y + 18 for b in bloklar)
        for satirlar in bloklar:
            ciz.ellipse(
                [kenar, y + 13, kenar + 9, y + 22], fill=(226, 170, 88)
            )
            for satir in satirlar:
                ciz.text((kenar + 26, y), satir, font=madde_font,
                         fill=(226, 231, 242))
                y += satir_y
            y += 18

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
    """Kapak slaytını üretip diske yazar."""
    from .make_image import (
        CIKTI_KLASORU,
        _gunluk_sayac_artir,
        arkaplan_uret_ai,
        arkaplan_uret_yedek,
    )

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


def gorsel_uret(haber, ayarlar: dict, con=None) -> Path:
    """Bir haber için görsel üretip diske yazar, dosya yolunu döner."""
    from .make_image import (
        CIKTI_KLASORU,
        _gunluk_sayac_artir,
        arkaplan_uret_ai,
        arkaplan_uret_yedek,
        yaziyi_bas,
    )

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
    gorsel.save(yol, "JPEG", quality=g["jpeg_kalite"], subsampling=0, optimize=True)
    log.info("görsel üretildi (%s): %s", kaynak_tipi, yol)
    return yol


def haftalik_kapak_ciz(
    basliklar: list[str],
    ayarlar: dict,
    baslangic: date | None = None,
    bitis: date | None = None,
) -> Image.Image:
    """Haftalık Pazar bülteni için özel 'HAFTANIN ÖZETİ' kapak slaytı üretir."""
    from .gorsel_arma import _logoyu_bas, kanal_ikonlari_bas
    from .make_image import (
        EKSEN_BASLIK,
        EKSEN_KUCUK,
        EKSEN_OZET,
        _font,
        _satirlara_bol,
        arkaplan_uret_yedek,
    )

    g = ayarlar["gorsel"]
    genislik, yukseklik = g["genislik"], g["yukseklik"]
    kenar = g["kenar_bosluk"]
    dikey_kenar = g.get("dikey_kenar_bosluk", g.get("kenar_bosluk", 60))
    alan_genislik = genislik - 2 * kenar

    gorsel = arkaplan_uret_yedek("turkiye", genislik, yukseklik, g)
    ciz = ImageDraw.Draw(gorsel)

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

    y = dikey_kenar + 140
    ana_baslik = "Haftanın Öne Çıkan Gelişmeleri"
    baslik_font = _font(58, EKSEN_BASLIK)
    baslik_satirlari = _satirlara_bol(ana_baslik, baslik_font, alan_genislik, ciz)
    for s in baslik_satirlari:
        ciz.text((kenar, y), s, font=baslik_font, fill=(255, 255, 255))
        y += int(58 * 1.18)

    y += 15
    ciz.rectangle([(kenar, y), (kenar + 100, y + 4)], fill=(226, 170, 88))
    y += 30

    alt_bilgi_y = yukseklik - dikey_kenar - 10
    madde_font = _font(27, EKSEN_OZET)
    satir_y = int(27 * 1.32)

    for _i, b in enumerate(basliklar[:5], start=1):
        blok = _satirlara_bol(b, madde_font, alan_genislik - 45, ciz)[:2]
        ciz.ellipse([kenar, y + 10, kenar + 10, y + 20], fill=(226, 170, 88))
        for satir in blok:
            ciz.text((kenar + 26, y), satir.replace("**", ""), font=madde_font, fill=(226, 231, 242))
            y += satir_y
        y += 18
        if y > alt_bilgi_y - 60:
            break

    kucuk = _font(24, EKSEN_KUCUK)
    hesap = ayarlar.get("instagram", {}).get("hesap_kullanici_adi", "")
    if hesap:
        ciz.text((kenar, alt_bilgi_y), f"@{hesap}  ·  Haftalık Bülten", font=kucuk, fill=(198, 206, 222))

    gorsel = kanal_ikonlari_bas(gorsel, ayarlar, alt_bilgi_y + 12)
    return gorsel
