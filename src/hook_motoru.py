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
     - kinetik_cubuk: Sol degrade dikey çentik + kicker + 2 satır başlık.
     - minimal_vurgu: ● Kicker + dev 2 satır vurgu (en yalın editoryal stil).
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


def uygun_alan_tespit_et(gorsel: Image.Image, baslik_ust: int, hook_h: int = 160) -> tuple[str, int | None]:
    """
    Fotoğrafın kenar yoğunluğunu (edge density) analiz ederek en uygun
    negatif alanı belirler.

    Döner: (konum_adi, y_koordinati)
      - ("zemin", y): Başlık üstü zemin temiz.
      - ("ust_bosluk", y): Zemin dolu/insan yüzü var, üst alan pürüzsüz bokeh.
      - ("pas_gec", None): İki alan da aşırı kalabalık, görseli kirletmemek için çizme.
    """
    try:
        genislik, yukseklik = gorsel.size
        gray = gorsel.convert("L")
        edges = gray.filter(ImageFilter.FIND_EDGES)

        # 1. Alan: Zemin (Başlık Üstü)
        zemin_ust = max(350, baslik_ust - hook_h - 40)
        box_zemin = (74, zemin_ust, min(genislik - 74, 650), baslik_ust)
        crop_z = edges.crop(box_zemin)
        zemin_edge = ImageStat.Stat(crop_z).mean[0]

        # 2. Alan: Üst Boşluk (DB Logo Altı, Heykel/Duvar/Gökyüzü Bokeh Alanı)
        box_ust = (74, 460, min(genislik - 74, 650), 660)
        crop_u = edges.crop(box_ust)
        ust_edge = ImageStat.Stat(crop_u).mean[0]

        log.debug("Hook alan analizi: Zemin Edge=%.2f, Üst Edge=%.2f (baslik_ust=%d)",
                  zemin_edge, ust_edge, baslik_ust)

        # Karar matrisi:
        # Zemin eşiği: 3.6 altı pürüzsüz düz yol/asfalt/karanlık zemin
        if zemin_edge <= 3.6:
            return "zemin", zemin_ust

        # Zemin dolu ama üst alan pürüzsüz bokeh ise (Öğrenci/Portre gibi)
        if ust_edge <= 3.8:
            return "ust_bosluk", 485

        # Zemin hafif toleranslıysa ve üstten daha az karmaşıksa
        if zemin_edge <= 4.8 and zemin_edge <= ust_edge:
            return "zemin", zemin_ust

        # Eğer iki alan da aşırı gürültülü/detaylıysa (kalabalık miting vb.)
        if zemin_edge > 5.2 and ust_edge > 5.0:
            log.info("Hook pas geçildi: görselin hem üstü hem altı aşırı kalabalık")
            return "pas_gec", None

        # Varsayılan emniyet: daha sakin olan alan
        if ust_edge < zemin_edge:
            return "ust_bosluk", 485
        return "zemin", zemin_ust

    except Exception as e:
        log.warning("Hook alan tespitinde hata, varsayılan zemin kullanılıyor: %s", e)
        return "zemin", max(400, baslik_ust - hook_h - 40)


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
    f_num = _font(105, 900.0)
    f_unit = _font(34, 800.0)
    f_lbl = _font(17, 700.0)
    f_t = _font(44, 900.0)

    # 1. Genişlik ölçümü
    bb_num = f_num.getbbox(num_txt)
    w_num = bb_num[2] - bb_num[0]
    w_unit = (f_unit.getbbox(unit_txt)[2] - f_unit.getbbox(unit_txt)[0]) if unit_txt else 0
    w_lbl = (f_lbl.getbbox(lbl_txt)[2] - f_lbl.getbbox(lbl_txt)[0]) if lbl_txt else 0

    w_ust = w_num + (10 + w_unit if unit_txt else 0)
    sol_blok = max(w_ust, w_lbl)

    # Dinamik ayraç ve sağ blok konumu
    sep_x = x + sol_blok + 26
    sag_x = sep_x + 26

    satirlar = [s for s in [t1, t2, t3] if s]
    w_sag = max((f_t.getbbox(s)[2] - f_t.getbbox(s)[0] for s in satirlar), default=200)
    toplam_w = (sag_x + w_sag) - x

    # 2. Difüzyon Gölgesi
    shadow = Image.new("RGBA", (toplam_w + 80, 260), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    sx = 40
    sdraw.text((sx, 25), num_txt, font=f_num, fill=(0, 0, 0, 255))
    if unit_txt:
        sdraw.text((sx + w_num + 10, 41), unit_txt, font=f_unit, fill=(0, 0, 0, 255))
    for i, s in enumerate(satirlar):
        sdraw.text((sx + (sep_x - x) + 26, 25 + i * 50), s, font=f_t, fill=(0, 0, 0, 255))
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
        draw.text((sag_x, y + 10 + i * 50), s, font=f_t, fill=satir_rengi)

    return out


def ciz_kinetik_cubuk(
    gorsel: Image.Image,
    x: int,
    y: int,
    kicker: str,
    t1: str,
    t2: str,
    renk: tuple[int, int, int] = AMBER,
) -> Image.Image:
    """Sol degrade çentikli kinetik format (Rakamsız haberler için)."""
    out = gorsel.copy()
    f_kicker = _font(22, 800.0)
    f_title = _font(56, 900.0)

    tx = x + 26
    y_kicker = y
    y_t1 = y + 32
    y_t2 = y + 96

    bb_k = f_kicker.getbbox(kicker)
    bb_t2 = f_title.getbbox(t2)
    bar_top = y_kicker + bb_k[1]
    bar_bottom = y_t2 + bb_t2[3]
    bar_h = max(30, bar_bottom - bar_top)

    notch = Image.new("RGBA", (8, bar_h), (0, 0, 0, 0))
    ndraw = ImageDraw.Draw(notch)
    for ny in range(bar_h):
        t = ny / bar_h
        r = int(renk[0] * (1 - t) + (renk[0] * 0.8) * t)
        g = int(renk[1] * (1 - t) + (renk[1] * 0.8) * t)
        b = int(renk[2] * (1 - t) + (renk[2] * 0.8) * t)
        ndraw.line([(0, ny), (7, ny)], fill=(r, g, b, 255))
    out.paste(notch, (x, bar_top), notch)

    shadow = Image.new("RGBA", (850, 220), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    sdraw.text((30, 20), kicker, font=f_kicker, fill=(0, 0, 0, 255))
    sdraw.text((30, 52), t1, font=f_title, fill=(0, 0, 0, 255))
    sdraw.text((30, 116), t2, font=f_title, fill=(0, 0, 0, 255))
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    out.paste(shadow, (tx - 30, y - 20), shadow)

    draw = ImageDraw.Draw(out)
    draw.text((tx, y_kicker), kicker, font=f_kicker, fill=renk)
    draw.text((tx, y_t1), t1, font=f_title, fill=WHITE)
    draw.text((tx, y_t2), t2, font=f_title, fill=renk)

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
    f_title = _font(64, 900.0)

    shadow = Image.new("RGBA", (850, 220), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    sdraw.text((30, 20), kicker, font=f_kicker, fill=(0, 0, 0, 255))
    sdraw.text((30, 56), t1, font=f_title, fill=(0, 0, 0, 255))
    sdraw.text((30, 126), t2, font=f_title, fill=(0, 0, 0, 255))
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    out.paste(shadow, (x - 30, y - 20), shadow)

    draw = ImageDraw.Draw(out)
    draw.text((x, y), kicker, font=f_kicker, fill=renk)
    draw.text((x, y + 36), t1, font=f_title, fill=WHITE)
    draw.text((x, y + 106), t2, font=f_title, fill=renk)

    return out


def tr_upper(s: str) -> str:
    """Türkçe karakter duyarlı büyük harfe dönüştürücü."""
    if not s:
        return ""
    return s.replace("i", "İ").replace("ı", "I").upper()


def _basliktan_hook_metinleri(baslik: str, konu: str = "") -> tuple[str, str]:
    """
    Haber başlığı veya konusundan 2 satırlık vurucu kanca başlığı türetir.
    Klişe kalıplar yerine haberin özünü 2 dengeli satıra böler.
    """
    baslik = (baslik or "").strip()
    if ":" in baslik:
        sol, sag = baslik.split(":", 1)
        sol, sag = sol.strip(), sag.strip()
        kelimeler_sol = sol.split()
        if len(kelimeler_sol) >= 3:
            mid = (len(kelimeler_sol) + 1) // 2
            return tr_upper(" ".join(kelimeler_sol[:mid])), tr_upper(" ".join(kelimeler_sol[mid:]))
        return tr_upper(sol[:22]), tr_upper(sag[:22])

    kelimeler = baslik.split()
    if len(kelimeler) <= 2:
        return tr_upper(baslik), (tr_upper(konu[:20]) if konu else "")

    mid = (len(kelimeler) + 1) // 2
    s1 = " ".join(kelimeler[:mid])
    s2 = " ".join(kelimeler[mid:])
    if len(s1) > 22 and " " in s1:
        s1 = s1[:22].rsplit(" ", 1)[0]
    if len(s2) > 22 and " " in s2:
        s2 = s2[:22].rsplit(" ", 1)[0]
    return tr_upper(s1), tr_upper(s2)


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

    # 2. Özel Durum Kontrolü (Xiaomi SUV gibi somut haberler için)
    if "xiaomi" in metin_tum and ("suv" in metin_tum or "skynomad" in metin_tum):
        return {
            "format": "stat_punch",
            "renk": "amber",
            "num_txt": "750",
            "unit_txt": "mm",
            "lbl_txt": "SU GEÇİŞ DERİNLİĞİ",
            "t1": "SUDA BATMAYAN",
            "t2": "KAMP ARACI",
        }

    # 3. Sayısal Vurgu Varsa (stat_punch)
    v_sayi = haber.get("vurgu_sayi")
    v_etiket = haber.get("vurgu_etiket")

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
        return {
            "format": "stat_punch",
            "renk": renk_adi,
            "num_txt": num_part,
            "unit_txt": unit_part,
            "lbl_txt": tr_upper(v_etiket or "KİLİT VERİ"),
            "t1": t1,
            "t2": t2,
        }

    # 4. Sayısız Haberler (minimal_vurgu veya kinetik_cubuk)
    kicker = "● SON DAKİKA GELİŞMESİ" if renk_adi == "kirmizi" else "● DİKKAT ÇEKEN GELİŞME"
    t1, t2 = _basliktan_hook_metinleri(
        haber.get("ig_baslik") or haber.get("baslik_orj") or "",
        haber.get("gorsel_konu") or ""
    )
    if not t2:
        t2 = tr_upper(haber.get("gorsel_konu") or "GÜNDEM")

    return {
        "format": "minimal_vurgu",
        "renk": renk_adi,
        "kicker": kicker,
        "t1": t1,
        "t2": t2,
    }


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

    # Akıllı negatif alan tespiti
    konum, y = uygun_alan_tespit_et(gorsel, baslik_ust)
    if konum == "pas_gec" or y is None:
        return gorsel

    x = 74
    renk = RENK_PALETI.get(hook_veri.get("renk", "amber"), AMBER)
    fmt = hook_veri.get("format", "stat_punch")

    log.info("Hook çiziliyor: format=%s, renk=%s, konum=%s (y=%d)",
             fmt, hook_veri.get("renk"), konum, y)

    if fmt == "stat_punch":
        return ciz_stat_punch(
            gorsel,
            x=x,
            y=y,
            num_txt=hook_veri.get("num_txt", ""),
            unit_txt=hook_veri.get("unit_txt", ""),
            lbl_txt=hook_veri.get("lbl_txt", ""),
            t1=hook_veri.get("t1", ""),
            t2=hook_veri.get("t2", ""),
            t3=hook_veri.get("t3", ""),
            renk=renk,
        )
    elif fmt == "kinetik_cubuk":
        return ciz_kinetik_cubuk(
            gorsel,
            x=x,
            y=y,
            kicker=hook_veri.get("kicker", "● ÖNE ÇIKAN GELİŞME"),
            t1=hook_veri.get("t1", ""),
            t2=hook_veri.get("t2", ""),
            renk=renk,
        )
    else:  # minimal_vurgu
        return ciz_minimal_vurgu(
            gorsel,
            x=x,
            y=y,
            kicker=hook_veri.get("kicker", "● ÖNE ÇIKAN GELİŞME"),
            t1=hook_veri.get("t1", ""),
            t2=hook_veri.get("t2", ""),
            renk=renk,
        )
