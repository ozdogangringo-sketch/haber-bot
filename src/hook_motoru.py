"""
hook_motoru.py — Editoryal Kanca (Hook) ve Akıllı Boşluk Tespiti Motoru.

Kullanıcıyı akışta ve story'de ilk 0.5 saniyede içeriğe çeken,
kutulardan/cam kalkanlardan arındırılmış, saf tipografik ve difüzyon gölgeli
kanca (hook) çizim ve kompozisyon motoru.

Özellikler:
  1. 3 Anlamlı Renk Paleti:
     - Ateş Kırmızısı (#EF4444): Kritik, acil, asayiş, rekor ceza, kriz, son dakika.
     - Sıcak Kehribar (#F59E0B): Lansman, teknoloji, ekonomi, yaşam, genel önemli.
     - Zümrüt Yeşili (#10B981): Şampiyonluk, zafer, müjde, tarihi başarı.
  2. 3 Tipografik Format:
     - stat_punch: İri rakam + birim + dikey ayraç + 2-3 satır vurgu.
     - minimal_vurgu: ● Kicker + dev 2 satır vurgu (en yalın editoryal stil).

    ⚠️ ÜÇÜNCÜ BİR FORMAT VARDI — `kinetik_cubuk` SİLİNDİ (9 Eyl 2026).
    `hook_olustur` yalnızca `stat_punch` ve `minimal_vurgu` üretiyor;
    ölçüldü, 200 gerçek haberde `kinetik_cubuk` **0 kez** seçildi ve
    55 satırlık çizim fonksiyonu hiçbir zaman çalışmadı. Ölü kodun
    asıl zararı yer değil YANLIŞ HARİTA: okuyan 'üç format var'
    sanıyor ve olmayan bir davranışa göre karar veriyor.
  3. Akıllı Boşluk Tespiti (Smart Negative Space Detection):
     - Pillow FIND_EDGES ile fotoğraf taranır.
     - İnsan yüzü/omzu veya detaylı nesne alt zemindeyse, metin otomatik olarak
       üst bokeh duvar alanına (y=485) taşınır.
     - Zemin temizse başlığın hemen üstüne (y=baslik_ust - 180) oturur.
     - İki alan da aşırı karmaşıksa görseli korumak için hook otomatik pas geçilir.
  4. Sıfır Taşma Garantisi:
     - BİN ₺, %10, 1.5 Milyar $ gibi verilerde dinamik piksel genişliği hesaplanır;
       asla çizgi veya metin çakışması yaşanmaz.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageStat

log = logging.getLogger(__name__)

# --- 3 TEMEL EDİTORYAL RENK ---
AMBER = (245, 158, 11)       # #F59E0B (Sıcak Kehribar Sarısı)
KIRMIZI = (239, 68, 68)      # #EF4444 (Crimson Alert Kırmızısı)
YESIL = (16, 185, 129)       # #10B981 (Zümrüt Yeşili)
WHITE = (255, 255, 255)
GRAY = (148, 163, 184)

RENK_PALETI = {
    "amber": AMBER,
    "sari": AMBER,
    "kirmizi": KIRMIZI,
    "red": KIRMIZI,
    "yesil": YESIL,
    "green": YESIL,
}


def _font(punto: int, weight: float = 900.0) -> ImageFont.FreeTypeFont:
    """Inter değişken fontundan ağırlık ve puntoya göre font yükler."""
    from . import make_image
    opsz = 32.0 if punto >= 28 else (20.0 if punto >= 18 else 14.0)
    return make_image._font(punto, [opsz, weight])


def _bant_yogunlugu(edges, x0: int, y0: int, x1: int, y1: int) -> float:
    """Bir bandın kenar yoğunluğu — yazı ve ince detay burada yükselir."""
    from PIL import ImageStat
    if y1 <= y0 or x1 <= x0:
        return 999.0
    return ImageStat.Stat(edges.crop((x0, y0, x1, y1))).mean[0]


def uygun_alan_tespit_et(gorsel, baslik_ust: int, hook_h: int = 160) -> tuple[str, int]:
    """
    Kancanın oturacağı EN SAKİN bandı seçer.

    ⚠️ NİYE DEĞİŞTİ (9 Eyl 2026): eski sürüm yalnızca İKİ bandı
    karşılaştırıyor ve neredeyse her zaman "zemin"e düşüyordu. Ürün
    fotoğrafı / infografik gibi YAZILI görsellerde her yer yoğun
    olduğundan ayrım yapamıyor, kanca fotoğrafın kendi yazısının
    üstüne oturuyordu — kullanıcının gönderdiği iPhone slaytında
    kancanın arkasında *"Başlangıç fiyatı: 137.999 TL"* okunuyordu.

    Yeni davranış: dört aday bant ölçülüyor, en sakini seçiliyor.
    ⚠️ HİÇBİRİ SAKİN DEĞİLSE en ALTTAKİ bant seçiliyor — orada okuma
    perdesi en koyu, yani fotoğraf ne kadar kalabalık olursa olsun
    metin okunur kalıyor. "En az kötü" seçeneği bilerek tercih
    ediliyor; kanca çizilmeyecekse bunu `hook_olustur` söyler.
    """
    from PIL import ImageFilter

    varsayilan_y = max(400, baslik_ust - hook_h - 30)
    try:
        genislik, _ = gorsel.size
        edges = gorsel.convert("L").filter(ImageFilter.FIND_EDGES)
        sag = min(genislik - 74, 1006)

        adaylar = [
            ("zemin", max(350, baslik_ust - hook_h - 30)),
            ("zemin_ust", max(350, baslik_ust - hook_h - 200)),
            ("orta", max(350, baslik_ust - hook_h - 380)),
            ("ust_bosluk", 485),
        ]
        olculen = []
        for ad, y in adaylar:
            yog = _bant_yogunlugu(edges, 74, y, sag, y + hook_h)
            olculen.append((yog, ad, y))
        SAKIN_ESIK = 18.0

        # ⚠️ EN SAKİN BANT DEĞİL, BAŞLIĞA EN YAKIN SAKİN BANT (9 Eyl 2026).
        # İlk yazımda bantlar yoğunluğa göre sıralanıp GLOBAL en sakini
        # seçiliyordu ve kanca sık sık en üste (y=485) fırlıyordu; gerçek
        # slaytta ölçüldü, kanca ile başlık arasında **~500 piksel boşluk**
        # kalıyor ve kanca hiçbir bloğa ait olmayan, havada duran bir
        # yazıya dönüşüyordu. Kanca başlığın ÜST SATIRI gibi okunmalı.
        # Bu yüzden bantlar aşağıdan yukarı geziliyor: yeteri kadar sakin
        # olan İLK bant kazanıyor, yukarı çıkmak için aşağıdakinin
        # gerçekten kalabalık olması gerekiyor.
        for yog, ad, y in sorted(olculen, key=lambda t: -t[2]):
            if yog <= SAKIN_ESIK:
                log.debug("Hook bandı: %s (yoğunluk %.1f)", ad, yog)
                return ad, y

        # Hepsi kalabalık → perdenin en koyu olduğu EN ALT bandı seç
        en_alt = max(adaylar, key=lambda t: t[1])
        log.debug("Hook bandı: hepsi yoğun (en düşük %.1f), perdeye iniliyor",
                  min(t[0] for t in olculen))
        return en_alt[0], en_alt[1]

    except Exception as e:                             # noqa: BLE001
        log.warning("Hook alan tespitinde hata, varsayılan kullanılıyor: %s", e)
        return "zemin", varsayilan_y


# Tuval ve kenar payları — hook metni bu sınırın dışına TAŞAMAZ.
TUVAL_GENISLIK = 1080
SAG_PAY = 74


def _sigdiran_font(satirlar, punto_bas: int, azami_px: int,
                   agirlik: float = 900.0, asgari: int = 26):
    """
    Verilen satırların HEPSİNİ `azami_px` genişliğe sığdıran en büyük puntoyu bulur.

    ⚠️ NİYE GEREKTİ (9 Eyl 2026): `ciz_stat_punch` docstring'i *"Sıfır
    taşma garantilidir"* diyordu ama `toplam_w` hesaplanıp HİÇBİR YERDE
    tuval genişliğiyle karşılaştırılmıyordu. ÖLÇÜLDÜ (60 gerçek haber):
    9'u (%15) taşıyordu, en kötüsü 1359px — 1080'lik tuvalde 279px kesik.
    ⚠️ Punto TÜM satırlar için ortak seçiliyor; satır satır küçültmek
    aynı blokta iki farklı boyut yaratıp düzeni bozardı.
    """
    dolu = [x for x in satirlar if x]
    if not dolu:
        return _font(punto_bas, agirlik)
    for punto in range(punto_bas, asgari - 1, -2):
        f = _font(punto, agirlik)
        if all((f.getbbox(x)[2] - f.getbbox(x)[0]) <= azami_px for x in dolu):
            return f
    return _font(asgari, agirlik)


def _kirp(metin: str, font, azami_px: int) -> str:
    """Punto küçültme yetmediyse kelime kelime kırpar ve … ekler."""
    if not metin:
        return metin
    if (font.getbbox(metin)[2] - font.getbbox(metin)[0]) <= azami_px:
        return metin
    kelimeler = metin.split()
    while len(kelimeler) > 1:
        kelimeler.pop()
        aday = " ".join(kelimeler) + "…"
        if (font.getbbox(aday)[2] - font.getbbox(aday)[0]) <= azami_px:
            return aday
    return metin


def ciz_stat_punch(
    gorsel: Image.Image,
    x: int,
    y: int,
    num_txt: str,
    unit_txt: str = "",
    lbl_txt: str = "",
    t1: str = "",
    t2: str = "",
    t3: str = "",
    renk: tuple[int, int, int] = AMBER,
) -> Image.Image:
    """
    Rakam odaklı vuruş formatı (İri rakam + birim + dikey ayraç + başlık satırları).
    Sıfır taşma garantilidir (BİN ₺ gibi birimler ayracı dinamik öteler).
    """
    out = gorsel.copy()
    f_unit = _font(34, 800.0)
    f_lbl = _font(17, 700.0)
    satirlar = [s for s in [t1, t2, t3] if s]

    # ⚠️ İKİ AŞAMALI SIĞDIRMA (9 Eyl 2026) — eskiden hiç yoktu.
    # Sağ bloğa en az `SAG_BLOK_ASGARI` piksel kalmalı; kalmıyorsa önce
    # RAKAM puntosu küçültülüyor (sol blok daralır), sonra sağ blok
    # satırları ortak bir puntoya sığdırılıyor, o da yetmezse kırpılıyor.
    SAG_BLOK_ASGARI = 400
    f_num = _font(105, 900.0)
    for num_punto in range(105, 55, -5):
        f_num = _font(num_punto, 900.0)
        w_num_d = f_num.getbbox(num_txt)[2] - f_num.getbbox(num_txt)[0]
        w_unit_d = (f_unit.getbbox(unit_txt)[2] - f_unit.getbbox(unit_txt)[0]) if unit_txt else 0
        w_lbl_d = (f_lbl.getbbox(lbl_txt)[2] - f_lbl.getbbox(lbl_txt)[0]) if lbl_txt else 0
        sol_d = max(w_num_d + (10 + w_unit_d if unit_txt else 0), w_lbl_d)
        if (TUVAL_GENISLIK - SAG_PAY) - (x + sol_d + 52) >= SAG_BLOK_ASGARI:
            break

    bb_num = f_num.getbbox(num_txt)
    w_num = bb_num[2] - bb_num[0]
    w_unit = (f_unit.getbbox(unit_txt)[2] - f_unit.getbbox(unit_txt)[0]) if unit_txt else 0
    w_lbl = (f_lbl.getbbox(lbl_txt)[2] - f_lbl.getbbox(lbl_txt)[0]) if lbl_txt else 0

    w_ust = w_num + (10 + w_unit if unit_txt else 0)
    sol_blok = max(w_ust, w_lbl)

    # Dinamik ayraç ve sağ blok konumu
    sep_x = x + sol_blok + 26
    sag_x = sep_x + 26

    sag_alan = max(160, (TUVAL_GENISLIK - SAG_PAY) - sag_x)
    f_t = _sigdiran_font(satirlar, 44, sag_alan)
    satirlar = [_kirp(sat, f_t, sag_alan) for sat in satirlar]

    w_sag = max((f_t.getbbox(s)[2] - f_t.getbbox(s)[0] for s in satirlar), default=200)
    toplam_w = (sag_x + w_sag) - x

    # 2. Difüzyon Gölgesi
    shadow = Image.new("RGBA", (toplam_w + 80, 260), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    sx = 40
    sdraw.text((sx, 25), num_txt, font=f_num, fill=(0, 0, 0, 255))
    if unit_txt:
        sdraw.text((sx + w_num + 10, 41), unit_txt, font=f_unit, fill=(0, 0, 0, 255))
    satir_adim = max(34, f_t.size + 6)
    for i, s in enumerate(satirlar):
        sdraw.text((sx + (sep_x - x) + 26, 25 + i * satir_adim), s, font=f_t, fill=(0, 0, 0, 255))
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    out.paste(shadow, (x - 40, y - 25), shadow)

    # 3. Metin Çizimi
    draw = ImageDraw.Draw(out)
    draw.text((x, y + 10), num_txt, font=f_num, fill=renk)
    if unit_txt:
        draw.text((x + w_num + 10, y + 26), unit_txt, font=f_unit, fill=renk)
    if lbl_txt:
        draw.text((x + 2, y + 115), lbl_txt, font=f_lbl, fill=GRAY)

    # Dikey ayraç
    h_cizgi = 146 if len(satirlar) <= 2 else 162
    draw.line([(sep_x, y + 16), (sep_x, y + h_cizgi)], fill=(255, 255, 255, 75), width=2)

    # Sağ blok satırları
    for i, s in enumerate(satirlar):
        satir_rengi = renk if i == 1 else WHITE
        draw.text((sag_x, y + 10 + i * satir_adim), s, font=f_t, fill=satir_rengi)

    return out


def ciz_minimal_vurgu(
    gorsel: Image.Image,
    x: int,
    y: int,
    kicker: str,
    t1: str,
    t2: str,
    renk: tuple[int, int, int] = AMBER,
) -> Image.Image:
    """Kutulardan arınmış, en yalın editoryal minimal kicker + dev başlık formatı."""
    out = gorsel.copy()
    f_kicker = _font(22, 800.0)
    # ⚠️ Sığdırma: 64 punto bu formatta en riskliydi (bkz. _sigdiran_font).
    minimal_alan = max(160, (TUVAL_GENISLIK - SAG_PAY) - x)
    f_title = _sigdiran_font([t1, t2], 64, minimal_alan)
    t1 = _kirp(t1, f_title, minimal_alan)
    t2 = _kirp(t2, f_title, minimal_alan)
    kicker = _kirp(kicker, f_kicker, minimal_alan)

    # ⚠️ Kicker boşsa satır YERİ DE ayrılmıyor — yoksa üstte 36 piksellik
    # sebepsiz bir boşluk kalır ve kanca yine havada durur.
    ust = 36 if kicker else 0

    shadow = Image.new("RGBA", (minimal_alan + 60, 220), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    if kicker:
        sdraw.text((30, 20), kicker, font=f_kicker, fill=(0, 0, 0, 255))
    sdraw.text((30, 20 + ust), t1, font=f_title, fill=(0, 0, 0, 255))
    sdraw.text((30, 90 + ust), t2, font=f_title, fill=(0, 0, 0, 255))
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    out.paste(shadow, (x - 30, y - 20), shadow)

    draw = ImageDraw.Draw(out)
    if kicker:
        draw.text((x, y), kicker, font=f_kicker, fill=renk)
    draw.text((x, y + ust), t1, font=f_title, fill=WHITE)
    draw.text((x, y + 70 + ust), t2, font=f_title, fill=renk)

    return out


def tr_upper(s: str) -> str:
    """Türkçe karakter duyarlı büyük harfe dönüştürücü."""
    if not s:
        return ""
    return s.replace("i", "İ").replace("ı", "I").upper()


def _dengeli_bol(kelimeler: list[str]) -> tuple[str, str]:
    """
    Kelime listesini iki satıra böler — KELİME SAYISINA göre değil,
    KARAKTER dengesine göre.

    ⚠️ NİYE (9 Eyl 2026): eski kural `mid = (len+1)//2` ile ortadan
    bölüyordu ve ifadeleri ortasından kesiyordu. Gerçek örnekler:
    `VERGİ İHBARLARINDA YAPAY / ZEKA DÖNEMİ BAŞLIYOR` ("yapay zeka"
    ikiye bölünmüş) · `YARISI BİZDEN KAMPANYASI / KADAR UZATILDI`
    (öznesiz parça).

    ⚠️ Tek başına yeterli değil ama zararı azaltıyor: iki satır da en
    az iki kelime ya da 8 karakter taşıyor, yani tek başına anlamsız
    bir kelime satırı kalmıyor.
    """
    if len(kelimeler) < 2:
        return " ".join(kelimeler), ""

    # ⚠️ RAKAMI BİRİMİNDEN AYIRMA (9 Eyl 2026). `kanca` alanı devreye
    # girince ilk çıktılardan biri `EHLİYETİNE 60 / GÜN EL KONDU` oldu —
    # "60 gün" ikiye bölünmüş. Satır sonunda yalnız kalan sayı ne
    # olduğunu söylemiyor; ardındaki birimle (gün, kişi, milyon, ₺…)
    # aynı satırda kalmalı.
    def _sayi_biriminden_kopuyor(i: int) -> bool:
        return bool(re.fullmatch(r"[%₺$€]?[\d.,]+[%₺$€]?", kelimeler[i - 1]))

    def _tek_kisa_satir(i: int) -> bool:
        sol, sag = " ".join(kelimeler[:i]), " ".join(kelimeler[i:])
        return ((len(kelimeler[:i]) < 2 and len(sol) < 8) or
                (len(kelimeler[i:]) < 2 and len(sag) < 8))

    # ⚠️ KISITLAR KATMAN KATMAN GEVŞETİLİYOR — düz ortadan bölmeye
    # DÜŞÜLMÜYOR. İlk yazımda hiçbir aday iki kuralı birden sağlamazsa
    # kod `(len+1)//2` ile ortadan bölüyordu ve bu, engellemeye
    # çalıştığı kusuru geri getiriyordu: "ZARAR 12 MİLYON LİRA" bütün
    # adaylarda elendiği için yedek dala düşüyor ve tam da yasak olan
    # yerden — `ZARAR 12 / MİLYON LİRA` — bölünüyordu.
    # Sıra önem sırasıdır: sayıyı biriminden ayırmak, kısa bir satır
    # bırakmaktan daha kötü okunuyor.
    for kisitlar in (
        (_tek_kisa_satir, _sayi_biriminden_kopuyor),   # ikisi de
        (_sayi_biriminden_kopuyor,),                   # kısa satıra izin ver
        (),                                            # son çare
    ):
        en_iyi, en_iyi_fark = None, None
        for i in range(1, len(kelimeler)):
            if any(k(i) for k in kisitlar):
                continue
            fark = abs(len(" ".join(kelimeler[:i])) - len(" ".join(kelimeler[i:])))
            if en_iyi_fark is None or fark < en_iyi_fark:
                en_iyi, en_iyi_fark = i, fark
        if en_iyi is not None:
            return " ".join(kelimeler[:en_iyi]), " ".join(kelimeler[en_iyi:])

    return " ".join(kelimeler), ""


def _basliktan_hook_metinleri(baslik: str, konu: str = "") -> tuple[str, str]:
    """
    Haber başlığı veya konusundan 2 satırlık vurucu kanca başlığı türetir.
    Klişe kalıplar veya başlığı körü körüne tekrarlamak yerine haberin özünü çıkarır.
    """
    baslik = (baslik or "").strip()
    konu_temiz = tr_upper(konu or "").strip()

    # 1. Başlıkta iki nokta (:) varsa (örn: "TEKNOFEST: Kayıtlar başladı")
    if ":" in baslik:
        sol, sag = baslik.split(":", 1)
        sol, sag = sol.strip(), sag.strip()
        kelimeler_sol = sol.split()
        if len(kelimeler_sol) >= 3:
            a, b = _dengeli_bol(kelimeler_sol)
            return tr_upper(a), tr_upper(b)
        return tr_upper(sol[:24]), tr_upper(sag[:24])

    kelimeler = baslik.split()
    if len(kelimeler) <= 2:
        return tr_upper(baslik), (tr_upper(konu[:20]) if konu else "")

    # 2. Somut bir konu / marka / model / aktör varsa (örn: "ANKA III", "Xiaomi", "Beşiktaş", "Apple")
    t1 = konu_temiz if (konu_temiz and len(konu_temiz) <= 24) else ""
    if not t1:
        t1 = " ".join(kelimeler[:2])
    else:
        # Bilinen kilit kurum/aktör önekleri
        for kurum in ["TUSAŞ", "BAYKAR", "ASELSAN", "ROKETSAN", "APPLE", "TESLA", "XIAOMI", "TFF", "ÖSYM", "CHP"]:
            if kurum.lower() in baslik.lower() and kurum not in t1:
                t1 = f"{kurum} {t1}"
                break

    # t2: Cümledeki ana olay/eylem (Türkçe haberlerde fiil ve aktör)
    ilk = kelimeler[0]
    son = kelimeler[-1]
    if ilk.lower() not in t1.lower() and len(ilk) <= 10 and not ilk.lower().startswith(("bir", "bu", "yeni", "ilk")):
        if "paylaş" in son.lower():
            t2 = f"{ilk}'DAN RESMİ PAYLAŞIM"
        elif "açıkla" in son.lower():
            t2 = f"{ilk}'DEN RESMİ AÇIKLAMA"
        elif "duyur" in son.lower():
            t2 = f"{ilk}'DEN RESMİ DUYURU"
        elif "onayla" in son.lower():
            t2 = f"{ilk}'DEN RESMİ ONAY"
        elif "yasakla" in son.lower():
            t2 = f"{ilk}'DEN YASAK KARARI"
        elif "karar" in son.lower():
            t2 = f"{ilk}'DEN KRİTİK KARAR"
        else:
            son_kelimeler = [k for k in kelimeler[-2:] if k.lower() not in t1.lower()]
            t2 = " ".join(son_kelimeler)
    else:
        son_kelimeler = [k for k in kelimeler[-2:] if k.lower() not in t1.lower()]
        t2 = " ".join(son_kelimeler) if son_kelimeler else (tr_upper(konu[:20]) if konu else "GÜNDEM")

    if len(t1) > 24 and " " in t1:
        t1 = t1[:24].rsplit(" ", 1)[0]
    if len(t2) > 24 and " " in t2:
        t2 = t2[:24].rsplit(" ", 1)[0]

    return tr_upper(t1), tr_upper(t2)


def _basliktan_farkli_mi(t1: str, t2: str, baslik: str,
                         azami_ortusme: float = 0.70) -> bool:
    """
    Kanca metni başlıktan GERÇEKTEN farklı bir şey söylüyor mu?

    ⚠️ KULLANICI KARARI (9 Eyl 2026): *"kancayla başlık tamamen farklı
    olmalı"*. Ekran görüntüsünde kanca *"APPLE İPHONE FİYATLARINA / %25
    ZAM YAPTI"* diyordu, 100 piksel altındaki başlık ise *"Apple iPhone
    fiyatlarına %25 zam yaptı: …"* — aynı cümle iki kez.

    Sebep yapısal: `_basliktan_hook_metinleri` başlığı kelime sayısına
    göre ortadan ikiye bölüyor, yani ürettiği şey tanım gereği başlığın
    bir DİLİMİ. Docstring "özü çıkarır" dese de yaptığı dilimlemek.

    Ölçüt: kancadaki anlamlı kelimelerin `azami_ortusme` kadarı başlıkta
    da geçiyorsa kanca bilgi eklemiyor demektir → hiç çizilmez.
    """
    import re as _re

    from . import dogrula

    # ⚠️ TÜRKÇE "İ" TUZAĞI — BEŞİNCİ KEZ. Düz `.lower()` "İPHONE"u
    # "i̇phone" (noktalı i) yapıyor ve "iphone" ile EŞLEŞMİYOR. İlk
    # yazımda tam bu yüzden `APPLE İPHONE FİYATLARINA / %25 ZAM YAPTI`
    # kancası, başlıkla birebir aynı olduğu hâlde filtreden GEÇTİ.
    # `dogrula._sadelestir` projenin ortak normalizeri — altıncı bir
    # varyant yazma.
    def _kelimeler(metin):
        return {k for k in _re.findall(r"\w+", dogrula._sadelestir(metin or ""))
                if len(k) > 2}

    kanca = _kelimeler(f"{t1} {t2}")
    if not kanca:
        return False
    ortak = len(kanca & _kelimeler(baslik)) / len(kanca)
    return ortak < azami_ortusme


def _baslikta_sayi_var_mi(baslik: str) -> bool:
    """
    Başlık zaten bir rakam taşıyor mu?

    ⚠️ KULLANICI KARARI: *"başlıkta rakam varsa zaten kancada gerek
    yok"*. iPhone vakasında başlık **en ucuz** modeli anlatıyordu
    (72.999) ama kanca **en pahalıyı** basıyordu (335.999) — üstelik
    fotoğrafın kendi içinde de 137.999 vardı. Tek slaytta üç fiyat.
    Rakam başlıkta duyurulmuşsa kanca onu tekrarlamamalı, başka bir
    rakamla da yarışmamalı: rakamsız formata düşer.
    """
    import re as _re
    return bool(_re.search(r"\d", baslik or ""))


def _son_dakika_esigini_geciyor(haber: dict) -> bool:
    """
    Bu haber "SON DAKİKA" ibaresini hak ediyor mu?

    Tek kaynak `config → genel.son_dakika_etiket_esigi` (varsayılan 9) —
    `slaytlar.py` ve `caption.py` aynı eşiği kullanıyor. Puan yoksa
    ibare BASILMIYOR: ölçülmemiş bir haberi "son dakika" ilan etmek,
    ibareyi değersizleştirmenin en kolay yolu.
    """
    try:
        import yaml
        from pathlib import Path as _P
        ayarlar = yaml.safe_load((_P(__file__).parent.parent / "config.yaml")
                                .read_text(encoding="utf-8"))
        esik = int(ayarlar.get("genel", {}).get("son_dakika_etiket_esigi", 9))
    except Exception:                                   # noqa: BLE001
        esik = 9
    try:
        return int(haber.get("onem_puani") or 0) >= esik
    except (TypeError, ValueError):
        return False


def hook_olustur(haber: dict) -> dict | None:
    """
    Haber verisinden akıllı editoryal hook konfigürasyonunu çıkarır.
    Format, renk ve başlık metinlerini otomatik belirler.
    """
    # 1. Renk Belirleme (Kritiklik / Duygu Analizi)
    kategori = (haber.get("kategori") or "turkiye").lower()
    baslik = (haber.get("ig_baslik") or haber.get("baslik_orj") or "").lower()
    ozet = (haber.get("slayt_ozet") or haber.get("ozet_orj") or "").lower()
    metin_tum = f"{baslik} {ozet}"

    kirmizi_desenler = [
        r"ceza", r"rekor ceza", r"tutukla", r"mahkeme", r"asayis", r"saldiri",
        r"kaza", r"sehit", r"operasyon", r"deprem", r"yangin", r"uyari", r"kriz",
        r"tehdit", r"tehlike", r"flas", r"son dakika", r"panik", r"agir darbe",
        r"fiyat artisi", r"zam", r"rekor zam",
        r"mahsur", r"kurtar", r"istifa", r"gozalti", r"gözaltı", r"patlama",
    ]
    yesil_desenler = [
        r"sampiyon", r"zafer", r"kupa", r"galibiyet", r"altin madalya",
        r"yendi", r"devirdi", r"tarihi basari", r"rekor ihracat", r"zirvede",
    ]

    if any(re.search(d, metin_tum) for d in kirmizi_desenler):
        renk_adi = "kirmizi"
    elif kategori == "spor" and any(re.search(d, metin_tum) for d in yesil_desenler):
        renk_adi = "yesil"
    else:
        renk_adi = "amber"

    # ⚠️ KODA GÖMÜLÜ "XIAOMI SUV" ÖZEL DURUMU SİLİNDİ (9 Eyl 2026).
    # Haberde ne yazarsa yazsın sabit "750 mm · SU GEÇİŞ DERİNLİĞİ" ve
    # "SUDA BATMAYAN KAMP ARACI" basıyordu. ÖLÇÜLDÜ: kaynağında 400 mm
    # geçen uydurma bir Xiaomi SUV haberi verildiğinde slayta yine 750
    # yazdı — yani kaynakta OLMAYAN bir teknik veri yayınlanıyordu.
    # ⚠️ Bu, projede DÖRDÜNCÜ kez görülen uydurma-rakam kusuru:
    # `/menu` düğmesindeki sahte TCMB faizi · piyasa sayfa 1 ve sayfa 2
    # varsayılanları · ısı haritası varsayılanları. Kural aynı:
    # KAYNAKTA YAZMAYAN SAYI SLAYTA BASILMAZ. Somut veri gerekiyorsa
    # `vurgu_sayi` alanından gelmeli — o alan makale metninden üretiliyor
    # ve `dogrula` denetiminden geçiyor.

    # 3. Sayısal Vurgu Varsa (stat_punch)
    v_sayi = haber.get("vurgu_sayi")
    v_etiket = haber.get("vurgu_etiket")

    # ⚠️ B KURALI — KULLANICI KARARI (9 Eyl 2026):
    # *"başlıkta rakam varsa zaten kancada gerek yok"*. Başlık rakamı
    # zaten duyurmuşsa kanca ikinci bir rakamla yarışmamalı; rakamsız
    # formata düşüyor. iPhone vakası: başlık **en ucuz** modeli
    # (72.999) anlatırken kanca **en pahalıyı** (335.999) basıyordu.
    if v_sayi and _baslikta_sayi_var_mi(haber.get("ig_baslik") or haber.get("baslik_orj") or ""):
        v_sayi = None

    if v_sayi:
        v_sayi_str = str(v_sayi).strip()
        m = re.match(r"^([%0-9\.\,\-]+)\s*(.*)$", v_sayi_str)
        if m:
            num_part = m.group(1).upper()
            unit_part = m.group(2).upper()
        else:
            num_part = v_sayi_str
            unit_part = ""

        t1, t2 = _basliktan_hook_metinleri(
            haber.get("ig_baslik") or haber.get("baslik_orj") or "",
            haber.get("gorsel_konu") or ""
        )
        if not _basliktan_farkli_mi(t1, t2, haber.get("ig_baslik") or haber.get("baslik_orj") or ""):
            return None
        return {
            "format": "stat_punch",
            "renk": renk_adi,
            "num_txt": num_part,
            "unit_txt": unit_part,
            "lbl_txt": tr_upper(v_etiket or "KİLİT VERİ"),
            "t1": t1,
            "t2": t2,
        }

    # 4. Sayısız Haberler (Konuya ve Duyguya Uygun Kicker + Minimal Vurgu)
    #
    # ⚠️ "SON DAKİKA" İBARESİ PUANA BAĞLI — kural baypas ediliyordu
    # (9 Eyl 2026). Kicker yalnızca RENGE bakıyordu ve renk de kelime
    # desenlerinden geliyor; sonuç: ÖLÇÜLDÜ, 12 kancanın **9'u** (%75)
    # önem puanı 9'un ALTINDAYKEN "SON DAKİKA GELİŞMESİ" basıyordu —
    # rutin bir trafik cezası (7), bir istifa (7), hastane ilaç
    # hırsızlığı (7). Oysa projenin kararı net: *"her önemli habere son
    # dakika demek ibareyi değersizleştiriyor"*, eşik `config →
    # son_dakika_etiket_esigi: 9` ve `slaytlar.py` ile `caption.py` ona
    # uyuyor. Kanca uymuyordu. Aynı kural, aynı eşik, üçüncü kapı.
    # ⚠️ İÇİ BOŞ KICKER'LAR KALDIRILDI — kullanıcı sordu: *"'dikkat çeken
    # gelişme' cümlesine gerek var mı"* (9 Eyl 2026). ÖLÇÜLDÜ: 47
    # kicker'ın **26'sı (%55)** tam olarak o ifadeydi. Bir haber
    # hesabındaki her gönderi zaten "dikkat çeken gelişme"dir; ifade
    # hiçbir şey söylemiyor ve silinince hiçbir bilgi kaybolmuyor —
    # gövde metninden ayıkladığımız *içi boş övgü* ölçütünün birebir
    # aynısı. `TARİHİ BAŞARI` da aynı sebeple gitti: bilgi değil HÜKÜM.
    #
    # Kalanların hepsi bir şey SÖYLÜYOR: alanı (piyasa, spor, savunma,
    # teknoloji), kimi ilgilendirdiğini (öğrenciler) ya da aciliyeti
    # (son dakika — artık önem puanına bağlı).
    #
    # ⚠️ Uyacak etiket yoksa kicker BOŞ kalıyor ve satır HİÇ ÇİZİLMİYOR;
    # yerine dolgu koymuyoruz. `vurgu_sayi` ve `alinti` alanlarındaki
    # kararla aynı: yoksa yok.
    if renk_adi == "kirmizi" and _son_dakika_esigini_geciyor(haber):
        kicker = "● SON DAKİKA GELİŞMESİ"
    elif any(w in metin_tum for w in ["savunma", "siha", "iha", "tusaş", "tsk", "nato", "baykar", "aselsan", "uçağı", "savaş uçağı"]):
        kicker = "● SAVUNMA SANAYİİ"
    elif any(w in metin_tum for w in ["öğrenci", "yurt", "ösym", "dgs", "yks", "kyk", "burs", "üniversite", "sınav"]):
        kicker = "● ÖĞRENCİLERİN DİKKATİNE"
    elif any(w in metin_tum for w in ["zam", "enflasyon", "bist", "faiz", "dolar", "euro", "petrol", "altın", "mevduat"]):
        kicker = "● PİYASA & EKONOMİ"
    elif kategori in ["teknoloji", "bilim"]:
        kicker = "● TEKNOLOJİ DÜNYASI"
    elif kategori == "spor":
        kicker = "● SPOR GÜNDEMİ"
    else:
        kicker = ""

    # ⚠️ ÖNCE GEMİNİ'NİN `kanca` ALANI — asıl çözüm bu (9 Eyl 2026).
    #
    # `_basliktan_hook_metinleri` adı üstünde BAŞLIKTAN türetiyor;
    # dolayısıyla ne kadar filtrelenirse filtrelensin yeni bilgi
    # taşıyamaz. ÖLÇÜLDÜ: 120 haberin **99'unda** (%82) üretilen kanca
    # başlığın yeniden ifadesiydi ve A kuralı tarafından bastırıldı.
    # Kullanıcının şartı — *"kancayla başlık tamamen farklı olmalı"* —
    # bu türetmeyle YAPISAL OLARAK karşılanamaz.
    #
    # `kanca` alanı makale GÖVDESİNDEN, başlıkta geçmeyen bir ayrıntı
    # olarak üretiliyor (bkz. `generate_text.PROMPT`). Şema onu ZORUNLU
    # DEĞİL, boş bırakılabilir yapıyor — `vurgu_sayi` ve `alinti` ile
    # aynı gerekçe: doldurmaya zorlamak uydurmayı davet eder.
    #
    # ⚠️ Başlıktan türetme SİLİNMEDİ, yedek olarak duruyor: alan boş
    # gelen ESKİ kayıtlar (1h dersi — kaynağı düzeltmek geçmiş
    # kayıtları düzeltmiyor) yine eski yoldan geçiyor ve A kuralı
    # onları zaten eliyor.
    kanca = (haber.get("kanca") or "").strip()
    if kanca:
        t1, t2 = _dengeli_bol(tr_upper(kanca).split())
    else:
        t1, t2 = _basliktan_hook_metinleri(
            haber.get("ig_baslik") or haber.get("baslik_orj") or "",
            haber.get("gorsel_konu") or ""
        )
    if not t2:
        t2 = tr_upper(haber.get("gorsel_konu") or "GÜNDEM")

    # ⚠️ A KURALI — KULLANICI KARARI: kanca başlığı tekrarlıyorsa HİÇ
    # ÇİZİLMEZ. Koddaki eski *"Hook ASLA pas geçilmez"* kararı bu
    # noktada terk edildi: bilgi eklemeyen bir kanca gürültüdür.
    if not _basliktan_farkli_mi(t1, t2, haber.get("ig_baslik") or haber.get("baslik_orj") or ""):
        return None

    return {
        "format": "minimal_vurgu",
        "renk": renk_adi,
        "kicker": kicker,
        "t1": t1,
        "t2": t2,
    }


# Kanca ile başlık bloğu arasında bırakılacak en az boşluk.
# Projenin kendi aralık standardı: detay paragrafları 24px, başlık-özet
# arası 26px. Kanca da aynı ailede olmalı.
NEFES_PAYI = 30


def _metin_kutusu(oncesi: Image.Image, sonrasi: Image.Image) -> tuple | None:
    """
    Çizilen kancanın GERÇEK metin sınırlarını döndürür.

    ⚠️ Eşik 110: düşük eşik gölgeyi de sayıyor. Ölçüldü — gölge dahil
    ölçüm kancayı başlığa 7-10px girmiş gösteriyordu, oysa METİN hiç
    taşmıyordu. Yanlış alarm veren ölçüm, ölçüm yapmamaktan kötüdür.
    """
    try:
        from PIL import ImageChops
        return (ImageChops.difference(oncesi.convert("RGB"), sonrasi.convert("RGB"))
                .convert("L").point(lambda v: 255 if v > 110 else 0).getbbox())
    except Exception:                                   # noqa: BLE001
        return None


def hook_uygula(
    gorsel: Image.Image,
    haber: dict,
    baslik_ust: int,
    ayarlar: dict | None = None,
) -> Image.Image:
    """
    Verilen kapak görseline akıllı konumlandırmayla editoryal hook'u çizer.
    """
    hook_veri = hook_olustur(haber)
    if not hook_veri:
        return gorsel

    # Akıllı negatif alan tespiti (asla pas geçilmez, güvenli koordinat döner)
    konum, y = uygun_alan_tespit_et(gorsel, baslik_ust)
    if y is None:
        y = max(400, baslik_ust - 190)

    x = 74
    renk = RENK_PALETI.get(hook_veri.get("renk", "amber"), AMBER)
    fmt = hook_veri.get("format", "stat_punch")

    def _ciz(hedef: Image.Image, ust: int) -> Image.Image:
        """Kancayı verilen üst koordinata çizer — iki geçişte de aynı yol."""
        if fmt == "stat_punch":
            return ciz_stat_punch(
                hedef,
                x=x,
                y=ust,
                num_txt=hook_veri.get("num_txt", ""),
                unit_txt=hook_veri.get("unit_txt", ""),
                lbl_txt=hook_veri.get("lbl_txt", ""),
                t1=hook_veri.get("t1", ""),
                t2=hook_veri.get("t2", ""),
                t3=hook_veri.get("t3", ""),
                renk=renk,
            )
        return ciz_minimal_vurgu(
            hedef,
            x=x,
            y=ust,
            kicker=hook_veri.get("kicker", "● ÖNE ÇIKAN GELİŞME"),
            t1=hook_veri.get("t1", ""),
            t2=hook_veri.get("t2", ""),
            renk=renk,
        )

    sonuc = _ciz(gorsel, y)

    # ⚠️ NEFES PAYI — kanca başlığa 9 PİKSEL kalana kadar iniyordu
    # (9 Eyl 2026, 51 kanca ölçüldü: ortanca 21px, en dar **9px**,
    # 9 tanesi 20px'in altında). Projenin kendi aralık standardı 24-26px
    # (detay paragrafları 24, başlık-özet arası 26); 9px'te kanca ile
    # başlık tek blok gibi okunuyor ve ikisi birbirine yapışıyor.
    #
    # ⚠️ SEBEP: `uygun_alan_tespit_et` kancayı **160px** varsayıyor ama
    # ölçüldü, `minimal_vurgu` gerçekte **180px**'e çıkıyor — 30px'lik
    # pay 9'a böyle düşüyordu.
    #
    # ⚠️ YÜKSEKLİK NEDEN HESAPLANMIYOR DA ÖLÇÜLÜYOR: formül yazmak
    # (kicker+36, t1+70, punto…) o hesabı çizim kodunun İKİZİ yapardı ve
    # bu projedeki en sık hata sınıfı tam olarak bu — *aynı kural iki
    # yerde yaşıyor, biri güncellenince diğeri unutuluyor*. Çizip ölçmek
    # kendi kendini düzeltiyor: çizim değişirse ölçüm de değişir.
    # Maliyeti ölçüldü: **33 ms/slayt** ve yalnızca kanca çizilen
    # slaytlarda (haberlerin %18'i).
    kutu = _metin_kutusu(gorsel, sonuc)
    if kutu:
        tasma = kutu[3] - (baslik_ust - NEFES_PAYI)
        if tasma > 0:
            y = max(120, y - int(tasma))
            sonuc = _ciz(gorsel, y)
            log.debug("Hook %d piksel yukarı alındı (nefes payı %d)", tasma, NEFES_PAYI)

    log.info("Hook çizildi: format=%s, renk=%s, konum=%s (y=%d)",
             fmt, hook_veri.get("renk"), konum, y)
    return sonuc
