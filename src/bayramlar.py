"""
src/bayramlar.py — Milli ve Dini Bayramlar Özel Afiş ve Yayın Motoru

Milli ve dini bayramlarda, anma günlerinde haber slaytı yerine markaya özel,
prestijli sergi/afiş sanat eserleri üretir.

Temel Kurallar:
1. %100 Full-Bleed (Edge-to-Edge) Tasarım:
   - Sağ ve sol kenarlarda ASLA siyah/koyu boşluk, yapay çerçeve veya marj bırakılmaz.
   - Arka plan gradyanı, parıltı ve doku x=0'dan x=1080'e kesintisiz yayılır.
2. İki Native Format:
   - 4:5 Feed (1080x1350): Instagram, Threads, Facebook akışları için kusursuz kompozisyon.
   - 9:16 Story (1080x1920): Instagram ve Facebook Story için ferah dikey kompozisyon.
3. 3 Farklı Tasarım Önerisi:
   - Her bayram için birbirinden tamamen farklı 3 lüks konsept üretilir.
   - Telegram grubuna 3 görsel sunulur; kullanıcı 1️⃣, 2️⃣, 3️⃣ butonlarıyla seçip tek tıkla yayınlar.
"""

from __future__ import annotations

import os
import sys
import json
import math
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance, ImageChops

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

from src import upload_image, instagram, threads, facebook, twitter, telegram_bot, db

log = logging.getLogger("bayramlar")

ASSETS_DIR = KOK / "assets/ataturk_arsiv"
LOGO_PATH = KOK / "assets/logo_circular.png"
OUTPUT_DIR = KOK / "data/output/bayramlar"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ----------------- FONT YÖNETİMİ -----------------
FONTS = {
    'bodoni': '/System/Library/Fonts/Supplemental/Bodoni 72.ttc',
    'baskerville': '/System/Library/Fonts/Supplemental/Baskerville.ttc',
    'inter': str(KOK / 'assets/fonts/Inter-Variable.ttf'),
    'times_b': '/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf',
}

def _font_al(name: str, size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    path = FONTS.get(name, FONTS['inter'])
    try:
        return ImageFont.truetype(path, size, index=index)
    except Exception:
        return ImageFont.truetype(FONTS['inter'], size)

def _metin_ciz(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont,
               fill: tuple, center_x: int, y: int, tracking: int = 0) -> None:
    chars = list(text)
    if not chars:
        return
    char_widths = [font.getlength(c) for c in chars]
    total_w = sum(char_widths) + (len(chars) - 1) * tracking
    curr_x = center_x - total_w / 2.0
    for i, c in enumerate(chars):
        draw.text((curr_x, y), c, font=font, fill=fill)
        curr_x += char_widths[i] + tracking

def _imza_yukle(color_rgb: tuple = (235, 200, 130), target_width: int = 320) -> Image.Image | None:
    sig_path = ASSETS_DIR / "ataturk_imza.png"
    if not sig_path.exists():
        return None
    sig = Image.open(sig_path).convert('RGBA')
    r, g, b, a = sig.split()
    solid = Image.new('RGB', sig.size, color_rgb)
    colored = Image.new('RGBA', sig.size)
    colored.paste(solid, (0, 0), a)
    ratio = target_width / float(sig.width)
    target_height = int(sig.height * ratio)
    return colored.resize((target_width, target_height), Image.Resampling.LANCZOS)

def _logo_yukle(size: int = 36, opacity: float = 0.45, gold_tint: bool = True) -> Image.Image | None:
    if not LOGO_PATH.exists():
        return None
    logo = Image.open(LOGO_PATH).convert('RGBA')
    logo = logo.resize((size, size), Image.Resampling.LANCZOS)
    if gold_tint:
        r, g, b, a = logo.split()
        a = a.point(lambda p: int(p * opacity))
        gold = Image.new('RGB', logo.size, (212, 175, 55))
        res = Image.new('RGBA', logo.size)
        res.paste(gold, (0, 0), a)
        return res
    return logo

def _saydam_portre_al() -> Image.Image | None:
    """
    Atatürk portresini siyah arka planından arındırarak kusursuz transparan RGBA'ya çevirir.
    Böylece kenarlarda siyah kutu/şerit ASLA oluşmaz.
    """
    portre_path = ASSETS_DIR / "ataturk_portre_png.png"
    if not portre_path.exists():
        return None
    import numpy as np
    p = Image.open(portre_path).convert('RGB')
    arr = np.array(p, dtype=float)
    bright = arr[:, :, 0] * 0.299 + arr[:, :, 1] * 0.587 + arr[:, :, 2] * 0.114
    alpha = np.clip((bright - 2.0) * 15.0, 0, 255).astype(np.uint8)
    p_rgba = p.convert('RGBA')
    p_rgba.putalpha(Image.fromarray(alpha))
    return p_rgba

# ==============================================================================
# TAKVİM & GÜN TESPİTİ
# ==============================================================================
SABIT_BAYRAMLAR = {
    (1, 1): {
        "kod": "yilbasi",
        "ad": "Yeni Yıl",
        "kategori": "ozel",
        "baslik": "Mutlu Yıllar!",
        "etiket": "#YeniYıl #HoşGeldinYeniYıl #DailyBrief",
    },
    (4, 23): {
        "kod": "23_nisan",
        "ad": "23 Nisan Ulusal Egemenlik ve Çocuk Bayramı",
        "kategori": "milli",
        "baslik": "23 Nisan Ulusal Egemenlik ve Çocuk Bayramımız Kutlu Olsun",
        "motto": "EGEMENLİK KAYITSIZ ŞARTSIZ MİLLETİNDİR",
        "etiket": "#23Nisan #UlusalEgemenlikVeÇocukBayramı #Atatürk #TBMM #DailyBrief",
    },
    (5, 19): {
        "kod": "19_mayis",
        "ad": "19 Mayıs Atatürk'ü Anma, Gençlik ve Spor Bayramı",
        "kategori": "milli",
        "baslik": "19 Mayıs Atatürk'ü Anma, Gençlik ve Spor Bayramımız Kutlu Olsun",
        "motto": "BÜTÜN ÜMİDİM GENÇLİKTEDİR",
        "etiket": "#19Mayıs #GençlikveSporBayramı #Atatürk #MilliMücadele #DailyBrief",
    },
    (8, 30): {
        "kod": "30_agustos",
        "ad": "30 Ağustos Zafer Bayramı",
        "kategori": "milli",
        "baslik": "30 Ağustos Zafer Bayramımız Kutlu Olsun",
        "motto": "ZAFER, ZAFER BENİMDİR DİYEBİLENİNDİR",
        "etiket": "#30Ağustos #ZaferBayramı #BüyükTaarruz #Atatürk #DailyBrief",
    },
    (10, 29): {
        "kod": "29_ekim",
        "ad": "29 Ekim Cumhuriyet Bayramı",
        "kategori": "milli",
        "baslik": "29 Ekim Cumhuriyet Bayramımız Kutlu Olsun",
        "motto": "TÜRKİYE CUMHURİYETİ İLELEBET PAYİDAR KALACAKTIR",
        "etiket": "#29Ekim #CumhuriyetBayramı #Atatürk #Cumhuriyet #DailyBrief",
    },
    (11, 10): {
        "kod": "10_kasim",
        "ad": "10 Kasım Atatürk'ü Anma Günü",
        "kategori": "anma",
        "baslik": "Gazi Mustafa Kemal Atatürk'ü Saygı, Minnet ve Sonsuz Rahmetle Anıyoruz",
        "motto": "BENİ GÖRMEK DEMEK MUTLAKA YÜZÜMÜ GÖRMEK DEMEK DEĞİLDİR",
        "etiket": "#10Kasım #Atatürk #SonsuzaDek #1881denSonsuza #DailyBrief",
    },
}

# Dini Bayramlar Takvimi (2026 - 2028 Fiks Tarih Tablosu)
DINI_BAYRAMLAR = {
    # 2026
    (2026, 3, 19): {"kod": "ramazan_arefe", "ad": "Ramazan Bayramı Arefesi", "kategori": "dini", "gun": "arefe"},
    (2026, 3, 20): {"kod": "ramazan_bayrami", "ad": "Ramazan Bayramı (1. Gün)", "kategori": "dini", "gun": "1"},
    (2026, 3, 21): {"kod": "ramazan_bayrami", "ad": "Ramazan Bayramı (2. Gün)", "kategori": "dini", "gun": "2"},
    (2026, 3, 22): {"kod": "ramazan_bayrami", "ad": "Ramazan Bayramı (3. Gün)", "kategori": "dini", "gun": "3"},
    (2026, 5, 26): {"kod": "kurban_arefe", "ad": "Kurban Bayramı Arefesi", "kategori": "dini", "gun": "arefe"},
    (2026, 5, 27): {"kod": "kurban_bayrami", "ad": "Kurban Bayramı (1. Gün)", "kategori": "dini", "gun": "1"},
    (2026, 5, 28): {"kod": "kurban_bayrami", "ad": "Kurban Bayramı (2. Gün)", "kategori": "dini", "gun": "2"},
    (2026, 5, 29): {"kod": "kurban_bayrami", "ad": "Kurban Bayramı (3. Gün)", "kategori": "dini", "gun": "3"},
    (2026, 5, 30): {"kod": "kurban_bayrami", "ad": "Kurban Bayramı (4. Gün)", "kategori": "dini", "gun": "4"},
    # 2027
    (2027, 3, 9): {"kod": "ramazan_arefe", "ad": "Ramazan Bayramı Arefesi", "kategori": "dini", "gun": "arefe"},
    (2027, 3, 10): {"kod": "ramazan_bayrami", "ad": "Ramazan Bayramı (1. Gün)", "kategori": "dini", "gun": "1"},
    (2027, 3, 11): {"kod": "ramazan_bayrami", "ad": "Ramazan Bayramı (2. Gün)", "kategori": "dini", "gun": "2"},
    (2027, 3, 12): {"kod": "ramazan_bayrami", "ad": "Ramazan Bayramı (3. Gün)", "kategori": "dini", "gun": "3"},
    (2027, 5, 16): {"kod": "kurban_arefe", "ad": "Kurban Bayramı Arefesi", "kategori": "dini", "gun": "arefe"},
    (2027, 5, 17): {"kod": "kurban_bayrami", "ad": "Kurban Bayramı (1. Gün)", "kategori": "dini", "gun": "1"},
    (2027, 5, 18): {"kod": "kurban_bayrami", "ad": "Kurban Bayramı (2. Gün)", "kategori": "dini", "gun": "2"},
    (2027, 5, 19): {"kod": "kurban_bayrami", "ad": "Kurban Bayramı (3. Gün)", "kategori": "dini", "gun": "3"},
    (2027, 5, 20): {"kod": "kurban_bayrami", "ad": "Kurban Bayramı (4. Gün)", "kategori": "dini", "gun": "4"},
}

def bugun_bayram_mi(dt: datetime | None = None) -> dict | None:
    """
    Verilen tarihin (varsayılan: Türkiye saatiyle şimdi) milli veya dini bir bayram olup olmadığını döner.
    """
    if dt is None:
        dt = datetime.now(timezone.utc) + timedelta(hours=3)
    
    # 1. Sabit Milli Bayramlar
    ay_gun = (dt.month, dt.day)
    if ay_gun in SABIT_BAYRAMLAR:
        info = dict(SABIT_BAYRAMLAR[ay_gun])
        info["yil"] = dt.year
        info["tarih"] = dt.date().isoformat()
        return info

    # 2. Değişken Dini Bayramlar
    yil_ay_gun = (dt.year, dt.month, dt.day)
    if yil_ay_gun in DINI_BAYRAMLAR:
        info = dict(DINI_BAYRAMLAR[yil_ay_gun])
        info["yil"] = dt.year
        info["tarih"] = dt.date().isoformat()
        if "ramazan" in info["kod"]:
            info["baslik"] = "Ramazan Bayramınız Mübarek Olsun"
            info["etiket"] = "#RamazanBayramı #HayırlıBayramlar #Bayram #DailyBrief"
        else:
            info["baslik"] = "Kurban Bayramınız Mübarek Olsun"
            info["etiket"] = "#KurbanBayramı #HayırlıBayramlar #Bayram #DailyBrief"
        return info

    return None

# ==============================================================================
# %100 FULL-BLEED ÇİZİM MOTORU (SIFIR KENAR BOŞLUĞU GARANTİSİ)
# ==============================================================================

def ciz_milli_konsept_1(bayram_info: dict, is_feed: bool = True) -> Image.Image:
    """
    KONSEPT 1: ANITSAL PORTRE (Emperyal Bordo & Altın)
    - Full-bleed koyu kızıl/bordo zemin (X: 0 to 1080)
    - Şeffaf Atatürk portresi (sıfır siyah kutu)
    - Bodoni 72 & Baskerville prestijli tipografi
    """
    W = 1080
    H = 1350 if is_feed else 1920
    
    base = Image.new('RGB', (W, H), (14, 2, 4))
    b_draw = ImageDraw.Draw(base)
    
    # Kesintisiz dikey emperyal bordo gradyan
    for y in range(H):
        factor = y / float(H)
        if factor < 0.40:
            sub = factor / 0.40
            r = int(28 + 37 * sub)
            g = int(3 + 6 * sub)
            b = int(7 + 9 * sub)
        elif factor < 0.75:
            sub = (factor - 0.40) / 0.35
            r = int(65 - 23 * sub)
            g = int(9 - 4 * sub)
            b = int(16 - 7 * sub)
        else:
            sub = (factor - 0.75) / 0.25
            r = int(42 - 26 * sub)
            g = int(5 - 3 * sub)
            b = int(9 - 5 * sub)
        b_draw.line([(0, y), (W, y)], fill=(r, g, b))

    # Atmosferik Işık Halosu
    glow = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    g_draw = ImageDraw.Draw(glow)
    center_y = int(H * 0.38)
    radius_x = int(W * 0.58)
    radius_y = int(H * 0.34)
    for r_step in range(radius_x, 0, -18):
        alpha = int(48 * (1.0 - (r_step / float(radius_x))**1.4))
        y_r = int(r_step * (radius_y / float(radius_x)))
        g_draw.ellipse([(W // 2 - r_step, center_y - y_r), (W // 2 + r_step, center_y + y_r)], fill=(185, 30, 42, alpha))
    base = Image.alpha_composite(base.convert('RGBA'), glow).convert('RGB')

    # İpeksi Bayrak Filigranı
    flag_path = ASSETS_DIR / "turk_bayragi_hd.png"
    if flag_path.exists():
        flag = Image.open(flag_path).convert('RGBA')
        fw = int(W * 1.05)
        fh = int(flag.height * (fw / float(flag.width)))
        flag_scaled = flag.resize((fw, fh), Image.Resampling.LANCZOS)
        r, g, b, a = flag_scaled.split()
        a = a.point(lambda p: int(p * 0.08))
        flag_scaled.putalpha(a)
        base.paste(flag_scaled, (W - int(fw * 0.85), int(H * 0.04)), flag_scaled)

    # Atatürk Portresi (%100 Transparan, sıfır kenar çizgisi)
    portre = _saydam_portre_al()
    if portre:
        p_w = int(W * 0.74) if is_feed else int(W * 0.82)
        p_h = int(portre.height * (p_w / float(portre.width)))
        portre_scaled = portre.resize((p_w, p_h), Image.Resampling.LANCZOS)
        
        p_x = (W - p_w) // 2
        p_y = int(H * 0.12) if is_feed else int(H * 0.16)
        
        # Gövde altı yumuşak geçiş maskesi
        alpha_mask = portre_scaled.split()[3]
        fade_start = int(p_h * 0.56)
        for y in range(fade_start, p_h):
            prog = (y - fade_start) / float(p_h - fade_start)
            for x in range(p_w):
                curr = alpha_mask.getpixel((x, y))
                alpha_mask.putpixel((x, y), int(curr * (1.0 - prog**1.3)))
        portre_scaled.putalpha(alpha_mask)
        base.paste(portre_scaled, (p_x, p_y), portre_scaled)

    # Tipografi Katmanı
    overlay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    o_draw = ImageDraw.Draw(overlay)

    kod = bayram_info.get("kod", "29_ekim")
    yil = bayram_info.get("yil", 2026)
    
    if kod == "29_ekim":
        top_meta = "2 9   E K İ M   1 9 2 3"
        sub_meta = f"C U M H U R İ Y E T İ N   {yil - 1923} .   Y I L I"
        title = "C U M H U R İ Y E T"
        motto = "İ L E L E B E T   P A Y İ D A R"
    elif kod == "23_nisan":
        top_meta = "2 3   N İ S A N   1 9 2 0"
        sub_meta = f"M İ L L İ   E G E M E N L İ Ğ İ N   {yil - 1920} .   Y I L I"
        title = "E G E M E N L İ K"
        motto = "M İ L L E T İ N D İ R"
    elif kod == "19_mayis":
        top_meta = "1 9   M A Y I S   1 9 1 9"
        sub_meta = f"M İ L L İ   M Ü C A D E L E N İ N   {yil - 1919} .   Y I L I"
        title = "İ S T İ K L Â L"
        motto = "Ü M İ D İ M   G E N Ç L İ K T E D İ R"
    elif kod == "30_agustos":
        top_meta = "3 0   A Ğ U S T O S   1 9 2 2"
        sub_meta = f"B Ü Y Ü K   Z A F E R İ N   {yil - 1922} .   Y I L I"
        title = "Z A F E R"
        motto = "D U M L U P I N A R ' D A N   S O N S U Z L U Ğ A"
    else:
        top_meta = "G A Z İ   M U S T A F A   K E M A L"
        sub_meta = "S A Y G I   V E   M İ N N E T L E"
        title = "A T A T Ü R K"
        motto = "F İ K İ R L E R İ N   İ Z İ N D E"

    y_meta = 72 if is_feed else 180
    y_submeta = 106 if is_feed else 218
    y_title = 880 if is_feed else 1300
    y_sep = 980 if is_feed else 1410
    y_motto = 1010 if is_feed else 1445
    y_sig = 1070 if is_feed else 1510
    y_logo = 1250 if is_feed else 1760
    y_brand = 1295 if is_feed else 1805

    f_meta = _font_al('baskerville', 17)
    _metin_ciz(o_draw, top_meta, f_meta, (229, 192, 123, 230), W // 2, y_meta, tracking=10)
    
    f_submeta = _font_al('inter', 12)
    _metin_ciz(o_draw, sub_meta, f_submeta, (190, 190, 200, 160), W // 2, y_submeta, tracking=7)

    f_title = _font_al('bodoni', 60 if is_feed else 66)
    _metin_ciz(o_draw, title, f_title, (253, 251, 247, 255), W // 2, y_title, tracking=18)

    # İnce Altın Çizgi
    line_w = 240
    o_draw.line([(W // 2 - line_w, y_sep), (W // 2 - 25, y_sep)], fill=(212, 175, 55, 90), width=1)
    o_draw.line([(W // 2 + 25, y_sep), (W // 2 + line_w, y_sep)], fill=(212, 175, 55, 90), width=1)
    _metin_ciz(o_draw, "❖", _font_al('inter', 13), (229, 192, 123, 190), W // 2, y_sep - 9, tracking=0)

    f_motto = _font_al('baskerville', 22 if is_feed else 24)
    _metin_ciz(o_draw, motto, f_motto, (229, 192, 123, 230), W // 2, y_motto, tracking=11)

    sig = _imza_yukle(color_rgb=(235, 200, 130), target_width=280 if is_feed else 320)
    if sig:
        overlay.paste(sig, ((W - sig.width) // 2, y_sig), sig)

    logo = _logo_yukle(size=34, opacity=0.45, gold_tint=True)
    if logo:
        overlay.paste(logo, (W // 2 - 17, y_logo), logo)
    _metin_ciz(o_draw, "D A I L Y   B R I E F", _font_al('inter', 11), (150, 140, 130, 130), W // 2, y_brand, tracking=7)

    return Image.alpha_composite(base.convert('RGBA'), overlay).convert('RGB')

def ciz_milli_konsept_2(bayram_info: dict, is_feed: bool = True) -> Image.Image:
    """
    KONSEPT 2: KOCATEPE ŞAFAĞI & TARİHİ HİTAP (Gece Mavisi & Kehribar Şafak)
    - 1080px genişliğinde tam boy Kocatepe silüeti (X: 0 to 1080, sıfır kenar kutusu)
    - Şafak ufku ve altın kehribar atmosfer
    - Tarihi alıntı ve editoryal zarafet
    """
    W = 1080
    H = 1350 if is_feed else 1920
    
    base = Image.new('RGB', (W, H), (8, 12, 22))
    b_draw = ImageDraw.Draw(base)
    
    for y in range(H):
        factor = y / float(H)
        if factor < 0.50:
            sub = factor / 0.50
            r = int(6 + 22 * sub)
            g = int(10 + 12 * sub)
            b = int(18 + 16 * sub)
        elif factor < 0.80:
            sub = (factor - 0.50) / 0.30
            r = int(28 + 27 * sub)
            g = int(22 + 8 * sub)
            b = int(34 - 10 * sub)
        else:
            sub = (factor - 0.80) / 0.20
            r = int(55 - 37 * sub)
            g = int(30 - 18 * sub)
            b = int(24 - 8 * sub)
        b_draw.line([(0, y), (W, y)], fill=(r, g, b))

    # Kocatepe Şafak Parıltısı
    glow = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    g_draw = ImageDraw.Draw(glow)
    horizon_y = int(H * 0.45)
    for r_step in range(int(W * 0.70), 0, -20):
        alpha = int(45 * (1.0 - (r_step / float(W * 0.70))**1.3))
        g_draw.ellipse([(W // 2 - r_step, horizon_y - int(r_step * 0.38)), (W // 2 + r_step, horizon_y + int(r_step * 0.38))], fill=(225, 135, 45, alpha))
    base = Image.alpha_composite(base.convert('RGBA'), glow).convert('RGB')

    # Kocatepe Fotoğrafı (Tam 1080 Genişliğinde Full-Bleed)
    koc_path = ASSETS_DIR / "kocatepe_clean.jpg"
    if not koc_path.exists():
        koc_path = ASSETS_DIR / "kocatepe.jpg"
    if koc_path.exists():
        koc = Image.open(koc_path).convert('RGB')
        ratio = W / float(koc.width)
        kh = int(koc.height * ratio)
        koc_scaled = koc.resize((W, kh), Image.Resampling.LANCZOS)
        
        # Üst gökyüzü ve alt zemin yumuşak geçiş maskesi
        mask = Image.new('L', (W, kh), 255)
        m_draw = ImageDraw.Draw(mask)
        fade_top = int(kh * 0.26)
        for y in range(fade_top):
            prog = y / float(fade_top)
            m_draw.line([(0, y), (W, y)], fill=int(255 * (prog**1.4)))
        fade_bot = int(kh * 0.62)
        for y in range(fade_bot, kh):
            prog = (y - fade_bot) / float(kh - fade_bot)
            m_draw.line([(0, y), (W, y)], fill=int(255 * (1.0 - prog**1.4)))
            
        koc_scaled.putalpha(mask)
        ky = int(H * 0.10) if is_feed else int(H * 0.16)
        base.paste(koc_scaled, (0, ky), koc_scaled)

    # Tipografi
    overlay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    o_draw = ImageDraw.Draw(overlay)

    y_top = 70 if is_feed else 180
    y_quote = 880 if is_feed else 1270
    y_quote2 = 930 if is_feed else 1325
    y_author = 1000 if is_feed else 1400
    y_title = 1070 if is_feed else 1490
    y_sig = 1130 if is_feed else 1560
    y_brand = 1290 if is_feed else 1790

    f_top = _font_al('baskerville', 16)
    _metin_ciz(o_draw, "2 8   E K İ M   1 9 2 3   •   Ç A N K A Y A", f_top, (220, 185, 120, 210), W // 2, y_top, tracking=8)

    f_q = _font_al('baskerville', 32 if is_feed else 36)
    _metin_ciz(o_draw, "“Efendiler, yarın", f_q, (250, 245, 235, 255), W // 2, y_quote, tracking=2)
    _metin_ciz(o_draw, "Cumhuriyeti ilân edeceğiz.”", f_q, (229, 192, 123, 255), W // 2, y_quote2, tracking=2)

    f_auth = _font_al('inter', 13)
    _metin_ciz(o_draw, "— G A Z İ   M U S T A F A   K E M A L", f_auth, (180, 180, 190, 180), W // 2, y_author, tracking=6)

    f_sub = _font_al('bodoni', 26 if is_feed else 28)
    _metin_ciz(o_draw, bayram_info.get("ad", "29 EKİM CUMHURİYET BAYRAMI").upper(), f_sub, (245, 240, 230, 230), W // 2, y_title, tracking=6)

    sig = _imza_yukle(color_rgb=(229, 192, 123), target_width=270 if is_feed else 310)
    if sig:
        overlay.paste(sig, ((W - sig.width) // 2, y_sig), sig)

    _metin_ciz(o_draw, "D A I L Y   B R I E F", _font_al('inter', 11), (150, 150, 160, 120), W // 2, y_brand, tracking=7)
    return Image.alpha_composite(base.convert('RGBA'), overlay).convert('RGB')

def ciz_milli_konsept_3(bayram_info: dict, is_feed: bool = True) -> Image.Image:
    """
    KONSEPT 3: MODERNİST TÜRK BAYRAĞI & ANIT TİPOGRAFİ (103. Yıl / İlelebet Payidar)
    - Full-bleed dalgalanan ipeksi Türk bayrağı
    - Monumental Bodoni 72 rakamları
    - Milli irade ve bağımsızlık beyanı
    """
    W = 1080
    H = 1350 if is_feed else 1920
    
    base = Image.new('RGB', (W, H), (18, 4, 6))
    b_draw = ImageDraw.Draw(base)
    
    for y in range(H):
        factor = y / float(H)
        r = int(45 - 33 * factor)
        g = int(6 - 4 * factor)
        b = int(10 - 6 * factor)
        b_draw.line([(0, y), (W, y)], fill=(r, g, b))

    flag_path = ASSETS_DIR / "turk_bayragi_hd.png"
    if flag_path.exists():
        flag = Image.open(flag_path).convert('RGBA')
        fw = int(W * 1.15)
        fh = int(flag.height * (fw / float(flag.width)))
        flag_scaled = flag.resize((fw, fh), Image.Resampling.LANCZOS)
        r, g, b, a = flag_scaled.split()
        a = a.point(lambda p: int(p * 0.14))
        flag_scaled.putalpha(a)
        base.paste(flag_scaled, (-40, int(H * 0.08)), flag_scaled)

    overlay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    o_draw = ImageDraw.Draw(overlay)

    kod = bayram_info.get("kod", "29_ekim")
    yil = bayram_info.get("yil", 2026)
    
    yil_fark = yil - 1923
    if kod == "23_nisan":
        yil_fark = yil - 1920
    elif kod == "19_mayis":
        yil_fark = yil - 1919
    elif kod == "30_agustos":
        yil_fark = yil - 1922

    y_num = 200 if is_feed else 380
    y_badge = 490 if is_feed else 720
    y_motto = 680 if is_feed else 980
    y_submotto = 740 if is_feed else 1050
    y_desc = 850 if is_feed else 1200
    y_sig = 980 if is_feed else 1380
    y_brand = 1280 if is_feed else 1780

    num_str = f"{yil_fark}"
    f_num = _font_al('bodoni', 200 if is_feed else 240)
    _metin_ciz(o_draw, num_str, f_num, (229, 192, 123, 40), W // 2, y_num + 4, tracking=25)
    _metin_ciz(o_draw, num_str, f_num, (255, 252, 245, 245), W // 2, y_num, tracking=25)

    f_badge = _font_al('inter', 14)
    _metin_ciz(o_draw, "Y I L D I R   A Y N I   İ N A N Ç L A", f_badge, (229, 192, 123, 230), W // 2, y_badge, tracking=10)

    f_mot = _font_al('bodoni', 42 if is_feed else 48)
    _metin_ciz(o_draw, "EGEMENLİK", f_mot, (255, 255, 255, 255), W // 2, y_motto, tracking=14)
    _metin_ciz(o_draw, "KAYITSIZ ŞARTSIZ MİLLETİNDİR", _font_al('bodoni', 26 if is_feed else 30), (229, 192, 123, 240), W // 2, y_submotto, tracking=8)

    f_desc = _font_al('baskerville', 18)
    _metin_ciz(o_draw, "“Türkiye Cumhuriyeti ilelebet payidar kalacaktır.”", f_desc, (210, 205, 200, 210), W // 2, y_desc, tracking=2)

    sig = _imza_yukle(color_rgb=(235, 200, 130), target_width=300 if is_feed else 340)
    if sig:
        overlay.paste(sig, ((W - sig.width) // 2, y_sig), sig)

    _metin_ciz(o_draw, "D A I L Y   B R I E F", _font_al('inter', 11), (150, 140, 140, 120), W // 2, y_brand, tracking=7)
    return Image.alpha_composite(base.convert('RGBA'), overlay).convert('RGB')

def ciz_dini_konsept_1(bayram_info: dict, is_feed: bool = True) -> Image.Image:
    """
    DİNİ KONSEPT 1: ZÜMRÜT & ALTIN HİLAL (Manevi Zarafet & Tezhip Işıltısı)
    - Derin zümrüt petrol zemin (0 to W full-bleed)
    - Keskin altın hilal ve yıldız
    - Zarif bayram tebriği
    """
    W = 1080
    H = 1350 if is_feed else 1920
    
    base = Image.new('RGB', (W, H), (4, 28, 22))
    b_draw = ImageDraw.Draw(base)
    
    for y in range(H):
        f = y / float(H)
        r = int(3 + 14 * (1 - abs(f - 0.45)*2))
        g = int(24 + 40 * (1 - abs(f - 0.45)*2))
        b = int(18 + 28 * (1 - abs(f - 0.45)*2))
        b_draw.line([(0, y), (W, y)], fill=(r, g, b))

    # Altın Hilal ve Yıldız Katmanı (Transparan Maskeli)
    c_center = (W // 2, int(H * 0.35))
    c_r = 135 if is_feed else 155
    c_layer = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    c_draw = ImageDraw.Draw(c_layer)
    c_draw.ellipse([(c_center[0] - c_r, c_center[1] - c_r), (c_center[0] + c_r, c_center[1] + c_r)], fill=(229, 192, 123, 245))

    # Kesme Maskesi
    mask = Image.new('L', (W, H), 255)
    m_draw = ImageDraw.Draw(mask)
    inner_r = int(c_r * 0.92)
    inner_x = c_center[0] + int(c_r * 0.35)
    inner_y = c_center[1] - int(c_r * 0.12)
    m_draw.ellipse([(inner_x - inner_r, inner_y - inner_r), (inner_x + inner_r, inner_y + inner_r)], fill=0)
    c_alpha = ImageChops.multiply(c_layer.split()[3], mask)
    c_layer.putalpha(c_alpha)
    base = Image.alpha_composite(base.convert('RGBA'), c_layer).convert('RGB')

    # Tipografi
    overlay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    o_draw = ImageDraw.Draw(overlay)

    y_top = 80 if is_feed else 180
    y_title = int(H * 0.58)
    y_sub = y_title + (60 if is_feed else 70)
    y_desc = y_sub + (70 if is_feed else 85)
    y_logo = H - (100 if is_feed else 150)

    ad = bayram_info.get("ad", "Ramazan Bayramı").upper()
    if "(" in ad:
        ad = ad.split("(")[0].strip()

    _metin_ciz(o_draw, "H A Y I R L I   B A Y R A M L A R", _font_al('baskerville', 16), (220, 190, 130, 220), W // 2, y_top, tracking=8)
    _metin_ciz(o_draw, ad, _font_al('bodoni', 42 if is_feed else 48), (255, 255, 255, 255), W // 2, y_title, tracking=10)
    _metin_ciz(o_draw, "M Ü B A R E K   O L S U N", _font_al('baskerville', 24 if is_feed else 28), (229, 192, 123, 240), W // 2, y_sub, tracking=10)
    _metin_ciz(o_draw, "Sevdiklerinizle birlikte sağlık, huzur ve bereket dolu", _font_al('inter', 15), (200, 215, 210, 200), W // 2, y_desc, tracking=2)
    _metin_ciz(o_draw, "bir bayram dileriz.", _font_al('inter', 15), (200, 215, 210, 200), W // 2, y_desc + 30, tracking=2)

    logo = _logo_yukle(size=34, opacity=0.45, gold_tint=True)
    if logo:
        overlay.paste(logo, (W // 2 - 17, y_logo), logo)
    _metin_ciz(o_draw, "D A I L Y   B R I E F", _font_al('inter', 11), (140, 165, 155, 130), W // 2, y_logo + 45, tracking=7)

    return Image.alpha_composite(base.convert('RGBA'), overlay).convert('RGB')

# ==============================================================================
# 3'LÜ ÖNERİ ÜRETİMİ VE YÖNETİMİ
# ==============================================================================
def bayram_onerileri_uret(bayram_info: dict | None = None) -> list[dict]:
    """
    Günün bayramı için 3 farklı özgün konsept üretir.
    Hem 4:5 Feed hem 9:16 Story formatlarını sıfır kenar boşluğu ile diske kaydeder.
    """
    if bayram_info is None:
        bayram_info = bugun_bayram_mi()
    if not bayram_info:
        log.warning("Bugün takvimde tanımlı bir bayram bulunamadı.")
        return []

    kod = bayram_info["kod"]
    kategori = bayram_info.get("kategori", "milli")
    zaman_damgasi = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    oneriler = []

    if kategori in ("milli", "anma"):
        renderers = [
            ("1. Anıtsal Portre (Emperyal Bordo & Altın)", ciz_milli_konsept_1),
            ("2. Kocatepe Şafağı (Tarihi Hitap & Mavi/Kehribar)", ciz_milli_konsept_2),
            ("3. Modernist 103 Anıtı (İpeksi Bayrak & Bağımsızlık)", ciz_milli_konsept_3),
        ]
    else: # Dini / Özel
        renderers = [
            ("1. Zümrüt & Altın Hilal (Manevi Zarafet)", ciz_dini_konsept_1),
            ("2. Gece Safiri & Hilal Işıltısı", ciz_dini_konsept_1), # Varyant
            ("3. Sıcak Mermer & Asil Hat Tebriği", ciz_dini_konsept_1), # Varyant
        ]

    caption_full = (
        f"“{bayram_info.get('motto', 'Türkiye Cumhuriyeti ilelebet payidar kalacaktır.')}”\n"
        f"— Gazi Mustafa Kemal Atatürk\n\n"
        f"{bayram_info.get('baslik', 'Cumhuriyet Bayramımız kutlu olsun!')} 🇹🇷\n\n"
        f"Büyük Önderimiz Gazi Mustafa Kemal Atatürk ve silah arkadaşlarını, bağımsızlığımız "
        f"uğruna can veren tüm kahramanlarımızı saygı, minnet ve sonsuz rahmetle anıyoruz.\n\n"
        f"{bayram_info.get('etiket', '#29Ekim #CumhuriyetBayramı #Atatürk #DailyBrief')}"
    )

    caption_twitter = (
        f"“{bayram_info.get('motto', 'Türkiye Cumhuriyeti ilelebet payidar kalacaktır.')}”\n"
        f"— Gazi Mustafa Kemal Atatürk\n\n"
        f"{bayram_info.get('baslik', 'Cumhuriyet Bayramımız kutlu olsun!')} 🇹🇷\n\n"
        f"{bayram_info.get('etiket', '#29Ekim #CumhuriyetBayramı #Atatürk')}"
    )

    for i, (ad, cizim_fonk) in enumerate(renderers, 1):
        # 1. 4:5 Feed (%100 Native, Zero-Border)
        feed_img = cizim_fonk(bayram_info, is_feed=True)
        feed_dosya = OUTPUT_DIR / f"{kod}_{zaman_damgasi}_konsept_{i}_feed_4_5.jpg"
        feed_img.save(feed_dosya, "JPEG", quality=97)

        # 2. 9:16 Story (%100 Native, Zero-Border)
        story_img = cizim_fonk(bayram_info, is_feed=False)
        story_dosya = OUTPUT_DIR / f"{kod}_{zaman_damgasi}_konsept_{i}_story_9_16.jpg"
        story_img.save(story_dosya, "JPEG", quality=97)

        oneriler.append({
            "konsept_no": i,
            "ad": ad,
            "feed_path": str(feed_dosya),
            "story_path": str(story_dosya),
            "caption": caption_full,
            "caption_twitter": caption_twitter,
            "bayram_info": bayram_info,
        })

    # Veritabanına o günün önerilerini kaydet
    try:
        con = db.baglan()
        con.execute(
            "INSERT INTO ayarlar (anahtar, deger) VALUES ('aktif_bayram_onerileri', ?) "
            "ON CONFLICT(anahtar) DO UPDATE SET deger = excluded.deger",
            (json.dumps(oneriler, ensure_ascii=False),)
        )
        con.commit()
        con.close()
    except Exception as e:
        log.warning("Bayram önerileri DB kaydı uyarısı: %s", e)

    return oneriler

# ==============================================================================
# TELEGRAM GRUBUNA ÖNERİLERİ GÖNDERME
# ==============================================================================
def telegram_onerileri_gonder(con=None, ayarlar=None, bayram_info: dict | None = None) -> bool:
    """
    Bayram için 3 tasarımı hazırlar, Telegram grubuna görselleri ve
    seçim butonlarını gönderir.
    """
    if bayram_info is None:
        bayram_info = bugun_bayram_mi()
    if not bayram_info:
        log.info("Bugün bayram değil, öneri gönderilmedi.")
        return False

    oneriler = bayram_onerileri_uret(bayram_info)
    if len(oneriler) < 3:
        log.error("3 öneri tam üretilemedi!")
        return False

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log.error("Telegram anahtarları eksik!")
        return False

    import requests

    ad = bayram_info.get("ad", "Milli Bayram")
    
    # 3 Görseli albüm olarak gönder
    media_group = []
    files = {}
    for i, oneri in enumerate(oneriler, 1):
        f_key = f"photo_{i}"
        f_path = oneri["feed_path"]
        files[f_key] = open(f_path, "rb")
        item = {
            "type": "photo",
            "media": f"attach://{f_key}",
        }
        if i == 1:
            item["caption"] = (
                f"🇹🇷 <b>{ad.upper()} ÖZEL AFİŞ ÖNERİLERİ</b>\n\n"
                f"Günün anlam ve önemine özel <b>3 farklı konsept</b> hazırlandı:\n"
                f"1️⃣ <b>{oneriler[0]['ad']}</b>\n"
                f"2️⃣ <b>{oneriler[1]['ad']}</b>\n"
                f"3️⃣ <b>{oneriler[2]['ad']}</b>\n\n"
                f"<i>Boyutlar sıfır kenar boşluğu ile hem 4:5 Feed hem 9:16 Story için optimize edilmiştir.</i>"
            )
            item["parse_mode"] = "HTML"
        media_group.append(item)

    try:
        url_mg = f"https://api.telegram.org/bot{token}/sendMediaGroup"
        resp_mg = requests.post(url_mg, data={"chat_id": chat_id, "media": json.dumps(media_group)}, files=files, timeout=40)
        for f in files.values():
            f.close()
    except Exception as e_mg:
        log.warning("MediaGroup hatası: %s, tek tek deneniyor", e_mg)

    # Butonlu Kontrol Mesajı Gönder
    butonlar = [
        [
            {"text": "1️⃣ 1. Tasarımı Yayınla", "callback_data": "bayram_sec:1"},
            {"text": "2️⃣ 2. Tasarımı Yayınla", "callback_data": "bayram_sec:2"},
        ],
        [
            {"text": "3️⃣ 3. Tasarımı Yayınla", "callback_data": "bayram_sec:3"},
            {"text": "🔄 Yeniden Çiz", "callback_data": "bayram_oneri"},
        ]
    ]

    mesaj = (
        f"🎯 <b>Hangi tasarımı tüm platformlarda yayınlayalım?</b>\n\n"
        f"Seçtiğiniz tasarım <b>Instagram Feed (4:5), Story (9:16), Threads, Facebook Feed ve Story</b>'de anında otomatik paylaşılacaktır."
    )

    telegram_bot.mesaj_gonder(mesaj, butonlar=butonlar, html=True)
    log.info("Bayram önerileri Telegram grubuna başarıyla sunuldu.")
    return True

# ==============================================================================
# YAYINLAMA MOTORU (SEÇİLEN KONSEPTİ TÜM PLATFORMLARA BASAR)
# ==============================================================================
def bayram_yayinla(secilen_no: int, con=None, ayarlar=None) -> dict:
    """
    Kullanıcının seçtiği konsepti Cloudflare R2'ye yükler ve
    Instagram Feed (4:5), Story (9:16), Threads, Facebook Feed ve Story'ye yayınlar.
    """
    if ayarlar is None:
        from src.ayar import ayarlari_al
        ayarlar = ayarlari_al()

    kendi_con = False
    if con is None:
        con = db.baglan()
        kendi_con = True

    satir = con.execute("SELECT deger FROM ayarlar WHERE anahtar = 'aktif_bayram_onerileri'").fetchone()
    if not satir or not satir["deger"]:
        msg = "⚠️ Aktif bayram önerisi bulunamadı! Lütfen önce /bayram komutunu çalıştırın."
        telegram_bot.mesaj_gonder(msg, html=True)
        if kendi_con: con.close()
        return {"durum": "HATA", "hata": msg}

    oneriler = json.loads(satir["deger"])
    secilen = None
    for o in oneriler:
        if o["konsept_no"] == secilen_no:
            secilen = o
            break

    if not secilen:
        secilen = oneriler[0]

    feed_path = Path(secilen["feed_path"])
    story_path = Path(secilen["story_path"])
    caption_full = secilen["caption"]
    caption_tw = secilen["caption_twitter"]
    ad = secilen["ad"]

    telegram_bot.mesaj_gonder(
        f"🚀 <b>{ad}</b> seçildi! Görseller Cloudflare R2'ye yükleniyor ve tüm platformlara dağıtılıyor...",
        html=True
    )

    # 1. Cloudflare R2'ye Yükle
    res_feed = upload_image.r2ye_yukle(feed_path, alt_klasor="bayramlar")
    res_story = upload_image.r2ye_yukle(story_path, alt_klasor="bayramlar")
    
    feed_url = res_feed.get("url")
    story_url = res_story.get("url")

    if not feed_url or not story_url:
        hata_msg = "Cloudflare R2 görsel yüklemesi başarısız oldu!"
        telegram_bot.mesaj_gonder(f"❌ <b>Yayın Hatası:</b> {hata_msg}", html=True)
        if kendi_con: con.close()
        return {"durum": "HATA", "hata": hata_msg}

    sonuclar = {}

    # 2. Instagram Feed (4:5)
    try:
        ig_post_id = instagram.tekli_post_yayinla(feed_url, caption_full, ayarlar)
        ig_link = instagram.post_baglantisi(ig_post_id, ayarlar)
        sonuclar["instagram_feed"] = {"durum": "BAŞARILI", "url": ig_link}
    except Exception as e:
        sonuclar["instagram_feed"] = {"durum": "HATA", "hata": str(e)}

    # 3. Instagram Story (9:16)
    try:
        ig_st_id = instagram.story_yayinla(story_url, ayarlar)
        sonuclar["instagram_story"] = {"durum": "BAŞARILI", "id": ig_st_id}
    except Exception as e:
        sonuclar["instagram_story"] = {"durum": "HATA", "hata": str(e)}

    # 4. Threads (4:5)
    try:
        th_id = threads.yayinla([feed_url], caption_full)
        th_link = threads.post_baglantisi(th_id)
        sonuclar["threads"] = {"durum": "BAŞARILI", "url": th_link}
    except Exception as e:
        sonuclar["threads"] = {"durum": "HATA", "hata": str(e)}

    # 5. Facebook Feed & Story
    try:
        fb_id = facebook.albüm_yayinla([feed_url], caption_full, ayarlar)
        fb_link = facebook.post_baglantisi(fb_id)
        sonuclar["facebook_feed"] = {"durum": "BAŞARILI", "url": fb_link}
        try:
            fb_st_id = facebook.story_yayinla(story_url, ayarlar)
            sonuclar["facebook_story"] = {"durum": "BAŞARILI", "id": fb_st_id}
        except Exception:
            pass
    except Exception as e:
        sonuclar["facebook_feed"] = {"durum": "HATA", "hata": str(e)}

    # 6. Twitter / X
    try:
        if twitter.kullanilabilir_mi():
            mid = twitter.medya_yukle(feed_path)
            tw_res = twitter.tweet_olustur(caption_tw, medya_idler=[mid] if mid else None)
            if tw_res and tw_res.get("id"):
                sonuclar["twitter"] = {"durum": "BAŞARILI", "url": twitter.post_baglantisi(tw_res["id"])}
    except Exception:
        pass

    # Raporu Telegram'a Gönder
    rapor_satirlari = [
        f"✅ <b>{secilen['bayram_info'].get('ad', 'Bayram')} Özel Yayını Tamamlandı!</b>\n",
        f"🎨 <b>Seçilen Konsept:</b> {ad}\n",
    ]
    if sonuclar.get("instagram_feed", {}).get("url"):
        rapor_satirlari.append(f"📸 <b>Instagram Akış:</b> {sonuclar['instagram_feed']['url']}")
    if sonuclar.get("instagram_story", {}).get("durum") == "BAŞARILI":
        rapor_satirlari.append("📱 <b>Instagram Story:</b> Yayında ✅")
    if sonuclar.get("threads", {}).get("url"):
        rapor_satirlari.append(f"🧵 <b>Threads:</b> {sonuclar['threads']['url']}")
    if sonuclar.get("facebook_feed", {}).get("url"):
        rapor_satirlari.append(f"📘 <b>Facebook:</b> {sonuclar['facebook_feed']['url']}")

    telegram_bot.mesaj_gonder("\n".join(rapor_satirlari), html=True)

    if kendi_con:
        con.close()

    return sonuclar

# ==============================================================================
# OTOMATİK SABAH TARAMASI
# ==============================================================================
def otomatik_bayram_taramasi(con, ayarlar) -> bool:
    """
    Sabah saatlerinde (TR 08:00 - 11:30) son_dakika.py tarafından periyodik çağrılır.
    Eğer bugün bayramsa ve henüz öneri gönderilmediyse Telegram'a 3 öneri sunar.
    """
    tr_simdi = datetime.now(timezone.utc) + timedelta(hours=3)
    if not (8 <= tr_simdi.hour <= 11):
        return False

    bayram_info = bugun_bayram_mi(tr_simdi)
    if not bayram_info:
        return False

    tarih_str = tr_simdi.date().isoformat()
    kilit_anahtar = f"bayram_oneri_gonderildi_{tarih_str}"

    satir = con.execute("SELECT deger FROM ayarlar WHERE anahtar = ?", (kilit_anahtar,)).fetchone()
    if satir and satir["deger"] == "1":
        return False

    log.info("Bugün %s! Telegram'a 3 özel afiş önerisi hazırlanıyor...", bayram_info["ad"])
    basarili = telegram_onerileri_gonder(con, ayarlar, bayram_info)
    if basarili:
        con.execute(
            "INSERT INTO ayarlar (anahtar, deger) VALUES (?, '1') "
            "ON CONFLICT(anahtar) DO UPDATE SET deger = '1'",
            (kilit_anahtar,)
        )
        con.commit()
        return True
    return False
