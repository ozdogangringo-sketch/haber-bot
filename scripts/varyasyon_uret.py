"""
scripts/varyasyon_uret.py — 10 Yeni Farklı Renk ve Zemin Temasında (11-20) Piyasa Kartı Üretir ve Telegram'a Gönderir.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from datetime import datetime, timezone
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import requests
from dotenv import load_dotenv

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
load_dotenv(KOK / ".env")

from src import piyasa
from src.piyasa_kart import _font, _squarify, _fiyat_bicimlendir

GENISLIK = 1080
YUKSEKLIK = 1350
LOGO_YOLU = KOK / "assets" / "logo_circular.png"
CIKTI_DIR = KOK / "data" / "output"
CIKTI_DIR.mkdir(parents=True, exist_ok=True)

# 10 YENİ FARKLI TEMA TANIMI (11 - 20)
TEMALAR_2 = [
    {
        "id": 11,
        "ad": "Varyasyon 11 — Espresso & Sıcak Moka",
        "tur": "dark",
        "bg_ust": (24, 16, 12),
        "bg_orta": (36, 24, 18),
        "bg_alt": (18, 12, 8),
        "glow": (217, 119, 6, 35),
        "container_bg": (38, 26, 19),
        "container_border": (85, 58, 42),
        "ribbon_bg": (52, 35, 25),
        "ribbon_fg": (255, 255, 255),
        "baslik_fg": (255, 255, 255),
        "metin_gri": (185, 165, 150),
        "rozet_bg": (52, 35, 25),
        "rozet_border": (245, 158, 11),
        "rozet_fg": (245, 158, 11),
        "footer_line": (65, 45, 32),
        "koyu_tema": True,
    },
    {
        "id": 12,
        "ad": "Varyasyon 12 — Buzul Nane & Kutup Ferahlığı",
        "tur": "light",
        "bg_ust": (234, 245, 242),
        "bg_orta": (218, 236, 232),
        "bg_alt": (198, 224, 218),
        "glow": (13, 148, 136, 30),
        "container_bg": (250, 254, 253),
        "container_border": (160, 204, 195),
        "ribbon_bg": (19, 78, 74),
        "ribbon_fg": (255, 255, 255),
        "baslik_fg": (19, 78, 74),
        "metin_gri": (75, 115, 110),
        "rozet_bg": (19, 78, 74),
        "rozet_border": (45, 212, 191),
        "rozet_fg": (45, 212, 191),
        "footer_line": (170, 210, 200),
        "koyu_tema": False,
    },
    {
        "id": 13,
        "ad": "Varyasyon 13 — Gün Batımı Mercan & Sıcak Şeftali",
        "tur": "light",
        "bg_ust": (252, 243, 238),
        "bg_orta": (245, 226, 216),
        "bg_alt": (235, 208, 194),
        "glow": (249, 115, 22, 30),
        "container_bg": (255, 253, 250),
        "container_border": (225, 190, 172),
        "ribbon_bg": (67, 30, 20),
        "ribbon_fg": (255, 255, 255),
        "baslik_fg": (58, 24, 14),
        "metin_gri": (130, 95, 80),
        "rozet_bg": (67, 30, 20),
        "rozet_border": (249, 115, 22),
        "rozet_fg": (251, 146, 60),
        "footer_line": (215, 180, 160),
        "koyu_tema": False,
    },
    {
        "id": 14,
        "ad": "Varyasyon 14 — Derin Petrol & Siber Turkuaz",
        "tur": "dark",
        "bg_ust": (4, 24, 28),
        "bg_orta": (8, 38, 44),
        "bg_alt": (3, 16, 20),
        "glow": (6, 182, 212, 40),
        "container_bg": (12, 45, 52),
        "container_border": (25, 85, 96),
        "ribbon_bg": (18, 62, 72),
        "ribbon_fg": (255, 255, 255),
        "baslik_fg": (255, 255, 255),
        "metin_gri": (140, 185, 195),
        "rozet_bg": (18, 62, 72),
        "rozet_border": (6, 182, 212),
        "rozet_fg": (6, 182, 212),
        "footer_line": (24, 75, 85),
        "koyu_tema": True,
    },
    {
        "id": 15,
        "ad": "Varyasyon 15 — İngiliz Yarış Yeşili & Antik Altın",
        "tur": "dark",
        "bg_ust": (11, 26, 18),
        "bg_orta": (16, 38, 26),
        "bg_alt": (8, 18, 12),
        "glow": (202, 138, 4, 35),
        "container_bg": (22, 48, 34),
        "container_border": (180, 140, 45),
        "ribbon_bg": (30, 65, 46),
        "ribbon_fg": (255, 255, 255),
        "baslik_fg": (255, 255, 255),
        "metin_gri": (160, 190, 170),
        "rozet_bg": (30, 65, 46),
        "rozet_border": (234, 179, 8),
        "rozet_fg": (250, 204, 21),
        "footer_line": (40, 75, 55),
        "koyu_tema": True,
    },
    {
        "id": 16,
        "ad": "Varyasyon 16 — Gül Kurusu & Kuvars Zarafeti",
        "tur": "light",
        "bg_ust": (253, 244, 246),
        "bg_orta": (246, 228, 232),
        "bg_alt": (236, 210, 218),
        "glow": (225, 29, 72, 25),
        "container_bg": (255, 254, 254),
        "container_border": (228, 185, 196),
        "ribbon_bg": (136, 19, 55),
        "ribbon_fg": (255, 255, 255),
        "baslik_fg": (136, 19, 55),
        "metin_gri": (140, 90, 105),
        "rozet_bg": (136, 19, 55),
        "rozet_border": (251, 113, 133),
        "rozet_fg": (255, 255, 255),
        "footer_line": (220, 175, 188),
        "koyu_tema": False,
    },
    {
        "id": 17,
        "ad": "Varyasyon 17 — Kadife Böğürtlen & Gece Mürdümü",
        "tur": "dark",
        "bg_ust": (26, 10, 24),
        "bg_orta": (38, 14, 35),
        "bg_alt": (18, 6, 16),
        "glow": (217, 70, 239, 35),
        "container_bg": (46, 18, 42),
        "container_border": (98, 42, 92),
        "ribbon_bg": (62, 24, 58),
        "ribbon_fg": (255, 255, 255),
        "baslik_fg": (255, 255, 255),
        "metin_gri": (195, 165, 190),
        "rozet_bg": (62, 24, 58),
        "rozet_border": (232, 121, 249),
        "rozet_fg": (232, 121, 249),
        "footer_line": (75, 32, 70),
        "koyu_tema": True,
    },
    {
        "id": 18,
        "ad": "Varyasyon 18 — Endüstriyel Beton & Sarı İkaz",
        "tur": "light",
        "bg_ust": (235, 237, 240),
        "bg_orta": (220, 224, 230),
        "bg_alt": (200, 206, 215),
        "glow": (234, 179, 8, 30),
        "container_bg": (252, 252, 253),
        "container_border": (180, 186, 196),
        "ribbon_bg": (28, 32, 40),
        "ribbon_fg": (250, 204, 21),
        "baslik_fg": (28, 32, 40),
        "metin_gri": (85, 95, 110),
        "rozet_bg": (28, 32, 40),
        "rozet_border": (234, 179, 8),
        "rozet_fg": (250, 204, 21),
        "footer_line": (175, 182, 192),
        "koyu_tema": False,
    },
    {
        "id": 19,
        "ad": "Varyasyon 19 — Derin Uzay & Parlak Neon Camgöbeği",
        "tur": "dark",
        "bg_ust": (6, 12, 24),
        "bg_orta": (10, 22, 44),
        "bg_alt": (4, 8, 16),
        "glow": (0, 229, 255, 45),
        "container_bg": (14, 28, 56),
        "container_border": (0, 180, 216),
        "ribbon_bg": (18, 38, 76),
        "ribbon_fg": (255, 255, 255),
        "baslik_fg": (255, 255, 255),
        "metin_gri": (150, 185, 220),
        "rozet_bg": (18, 38, 76),
        "rozet_border": (0, 229, 255),
        "rozet_fg": (0, 229, 255),
        "footer_line": (30, 55, 100),
        "koyu_tema": True,
    },
    {
        "id": 20,
        "ad": "Varyasyon 20 — Çöl Kumulu & Sıcak Terracotta",
        "tur": "light",
        "bg_ust": (252, 247, 234),
        "bg_orta": (244, 234, 212),
        "bg_alt": (230, 215, 185),
        "glow": (180, 83, 9, 30),
        "container_bg": (255, 254, 250),
        "container_border": (215, 195, 160),
        "ribbon_bg": (69, 26, 3),
        "ribbon_fg": (255, 255, 255),
        "baslik_fg": (69, 26, 3),
        "metin_gri": (130, 95, 60),
        "rozet_bg": (69, 26, 3),
        "rozet_border": (217, 119, 6),
        "rozet_fg": (245, 158, 11),
        "footer_line": (210, 185, 150),
        "koyu_tema": False,
    },
]


def _renk_hesapla(degisim: float) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    if degisim >= 2.5:
        return (16, 185, 129), (5, 150, 105)
    elif degisim >= 0.5:
        return (22, 163, 74), (21, 128, 61)
    elif degisim > 0.05:
        return (21, 128, 61), (20, 83, 45)
    elif degisim >= -0.05:
        return (71, 85, 105), (51, 65, 85)
    elif degisim > -0.5:
        return (185, 28, 28), (153, 27, 27)
    elif degisim > -2.5:
        return (220, 38, 38), (185, 28, 28)
    else:
        return (239, 68, 68), (220, 38, 38)


def kart_uret_tema(tema: dict, sektor_verileri: dict) -> Path:
    img = Image.new("RGB", (GENISLIK, YUKSEKLIK))
    draw = ImageDraw.Draw(img)

    # 1. Gradyan Zemin
    for y in range(YUKSEKLIK):
        if y < 650:
            oran = y / 650.0
            r = int(tema["bg_ust"][0] * (1 - oran) + tema["bg_orta"][0] * oran)
            g = int(tema["bg_ust"][1] * (1 - oran) + tema["bg_orta"][1] * oran)
            b = int(tema["bg_ust"][2] * (1 - oran) + tema["bg_orta"][2] * oran)
        else:
            oran = (y - 650) / (YUKSEKLIK - 650.0)
            r = int(tema["bg_orta"][0] * (1 - oran) + tema["bg_alt"][0] * oran)
            g = int(tema["bg_orta"][1] * (1 - oran) + tema["bg_alt"][1] * oran)
            b = int(tema["bg_orta"][2] * (1 - oran) + tema["bg_alt"][2] * oran)
        draw.line([(0, y), (GENISLIK, y)], fill=(r, g, b))

    # Glow ambiyansı
    glow = Image.new("RGBA", (GENISLIK, YUKSEKLIK), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.ellipse([(-120, -120), (600, 480)], fill=tema["glow"])
    gdraw.ellipse([(620, 680), (1250, 1450)], fill=(tema["glow"][0], tema["glow"][1], tema["glow"][2], int(tema["glow"][3] * 0.8)))
    glow = glow.filter(ImageFilter.GaussianBlur(140))
    img.paste(Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB"), (0, 0))
    draw = ImageDraw.Draw(img)

    f_etiket = _font(20, 800.0)
    f_baslik = _font(44, 900.0)
    f_tarih_buyuk = _font(24, 800.0)
    f_tarih_kucuk = _font(19, 600.0)
    f_sektor = _font(18, 800.0)
    f_alt_kucuk = _font(17, 600.0)

    # 2. Header
    logo_boyut = 126
    logo_x = 45
    logo_y = 38

    if LOGO_YOLU.exists():
        try:
            golge = Image.new("RGBA", (GENISLIK, YUKSEKLIK), (0, 0, 0, 0))
            ImageDraw.Draw(golge).ellipse(
                [logo_x - 4, logo_y - 2, logo_x + logo_boyut + 6, logo_y + logo_boyut + 8],
                fill=(0, 0, 0, 100 if tema["koyu_tema"] else 40),
            )
            golge = golge.filter(ImageFilter.GaussianBlur(14))
            img.paste(Image.alpha_composite(img.convert("RGBA"), golge).convert("RGB"), (0, 0))

            logo = Image.open(LOGO_YOLU).convert("RGBA")
            logo = logo.resize((logo_boyut, logo_boyut), Image.Resampling.LANCZOS)
            img.paste(logo, (logo_x, logo_y), mask=logo)
        except Exception:
            pass

    draw = ImageDraw.Draw(img)

    header_x = 192
    rozet_txt = f"DAILYBRIEF · VARYASYON #{tema['id']}"
    rw = draw.textlength(rozet_txt, font=f_etiket)
    draw.rounded_rectangle(
        [(header_x, 42), (header_x + rw + 22, 78)],
        radius=8,
        fill=tema["rozet_bg"],
        outline=tema["rozet_border"],
        width=2,
    )
    draw.text((header_x + 11, 48), rozet_txt, font=f_etiket, fill=tema["rozet_fg"])
    draw.text((header_x, 92), "Güne Nasıl Başladı?", font=f_baslik, fill=tema["baslik_fg"])

    aylar = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
             "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
    gunler = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    simdi = datetime.now(timezone.utc)
    tarih_satir1 = f"{simdi.day} {aylar[simdi.month - 1]} {simdi.year}"
    tarih_satir2 = f"{gunler[simdi.weekday()]} · Açılış"

    w_t1 = draw.textlength(tarih_satir1, font=f_tarih_buyuk)
    w_t2 = draw.textlength(tarih_satir2, font=f_tarih_kucuk)

    sag_kenar = 1035
    draw.text((sag_kenar - w_t1, 86), tarih_satir1, font=f_tarih_buyuk, fill=tema["baslik_fg"])
    draw.text((sag_kenar - w_t2, 118), tarih_satir2, font=f_tarih_kucuk, fill=tema["metin_gri"])

    # 3. Sektör Konteynerleri
    sektor_yerlesimi = [
        ("BİST & TÜRKİYE HİSSELERİ", (45, 180, 990, 490)),
        ("DÖVİZ & EMTİA (MAKRO)", (45, 688, 490, 545)),
        ("KÜRESEL DEVLER & KRİPTO", (545, 688, 490, 545)),
    ]

    ribbon_h = 36

    shadow_img = Image.new("RGBA", (GENISLIK, YUKSEKLIK), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow_img)
    for _, (sx, sy, sw, sh) in sektor_yerlesimi:
        sdraw.rounded_rectangle([(sx, sy + 3), (sx + sw, sy + sh + 5)], radius=14, fill=(0, 0, 0, 70 if tema["koyu_tema"] else 35))
    shadow_img = shadow_img.filter(ImageFilter.GaussianBlur(12))
    img.paste(Image.alpha_composite(img.convert("RGBA"), shadow_img).convert("RGB"), (0, 0))
    draw = ImageDraw.Draw(img)

    for sektor_adi, (sx, sy, sw, sh) in sektor_yerlesimi:
        ogeler = sektor_verileri.get(sektor_adi, [])
        if not ogeler:
            continue

        draw.rounded_rectangle(
            [(sx, sy), (sx + sw, sy + sh)],
            radius=12,
            fill=tema["container_bg"],
            outline=tema["container_border"],
            width=2,
        )
        draw.rounded_rectangle(
            [(sx, sy), (sx + sw, sy + ribbon_h)],
            radius=10,
            fill=tema["ribbon_bg"],
        )
        draw.text((sx + 14, sy + 8), f"› {sektor_adi}", font=f_sektor, fill=tema["ribbon_fg"])

        icerik_rect = (sx + 2, sy + ribbon_h + 3, sw - 4, sh - ribbon_h - 5)
        hucreler = _squarify(ogeler, icerik_rect)

        for oge, (cx, cy, cw, ch) in hucreler:
            degisim = oge["degisim"]
            fiyat = oge.get("fiyat", 0.0)
            sym = oge.get("sym", "")
            fiyat_str = _fiyat_bicimlendir(sym, fiyat)

            c_bg, c_border = _renk_hesapla(degisim)

            draw.rounded_rectangle(
                [(cx + 2, cy + 2), (cx + cw - 2, cy + ch - 2)],
                radius=10,
                fill=c_bg,
                outline=c_border,
                width=1,
            )

            sembol = oge["etiket"]
            chg_str = f"{'▲ +' if degisim >= 0 else '▼ -'}{abs(degisim):.2f}%"

            max_w = cw - 20
            max_p = 42 if (cw >= 200 and ch >= 120) else (32 if (cw >= 130 and ch >= 80) else (22 if (cw >= 80 and ch >= 55) else 17))

            p_sym = max_p
            f_sym = _font(p_sym, 900.0)
            while draw.textlength(sembol, font=f_sym) > max_w and p_sym > 13:
                p_sym -= 2
                f_sym = _font(p_sym, 900.0)

            p_fiyat = max(11, int(p_sym * 0.65))
            f_fiyat = _font(p_fiyat, 700.0)
            while draw.textlength(fiyat_str, font=f_fiyat) > max_w and p_fiyat > 10:
                p_fiyat -= 2
                f_fiyat = _font(p_fiyat, 700.0)

            p_chg = max(12, int(p_sym * 0.70))
            f_chg = _font(p_chg, 800.0)
            while draw.textlength(chg_str, font=f_chg) > max_w and p_chg > 10:
                p_chg -= 2
                f_chg = _font(p_chg, 800.0)

            sw_s = draw.textlength(sembol, font=f_sym)
            sw_f = draw.textlength(fiyat_str, font=f_fiyat)
            sw_c = draw.textlength(chg_str, font=f_chg)
            mid_x = cx + cw / 2
            mid_y = cy + ch / 2

            if ch >= 90 and fiyat_str:
                draw.text((mid_x - sw_s / 2, mid_y - int(p_sym * 0.95)), sembol, font=f_sym, fill=(255, 255, 255))
                draw.text((mid_x - sw_f / 2, mid_y - int(p_fiyat * 0.05)), fiyat_str, font=f_fiyat, fill=(241, 245, 249))
                draw.text((mid_x - sw_c / 2, mid_y + int(p_chg * 0.70)), chg_str, font=f_chg, fill=(255, 255, 255))
            elif ch >= 55 and fiyat_str:
                alt_metin = f"{fiyat_str} {chg_str}" if cw >= 130 else chg_str
                sw_alt = draw.textlength(alt_metin, font=f_chg)
                draw.text((mid_x - sw_s / 2, mid_y - int(p_sym * 0.8)), sembol, font=f_sym, fill=(255, 255, 255))
                draw.text((mid_x - sw_alt / 2, mid_y + int(p_chg * 0.2)), alt_metin, font=f_chg, fill=(255, 255, 255))
            else:
                draw.text((mid_x - sw_s / 2, mid_y - int(p_sym * 0.7)), sembol, font=f_sym, fill=(255, 255, 255))
                draw.text((mid_x - sw_c / 2, mid_y + int(p_chg * 0.2)), chg_str, font=f_chg, fill=(255, 255, 255))

    # 4. Footer
    draw.line([(45, 1245), (1035, 1245)], fill=tema["footer_line"], width=1)

    skala_x = 45
    skala_y = 1262
    skala_ogeleri = [
        ("<-2.5%", (239, 68, 68)),
        ("-1.5%", (220, 38, 38)),
        ("-0.5%", (185, 28, 28)),
        ("0%", (71, 85, 105)),
        ("+0.5%", (21, 128, 61)),
        ("+1.5%", (22, 163, 74)),
        (">+2.5%", (16, 185, 129)),
    ]

    draw.text((skala_x, skala_y + 2), "SKALA:", font=f_alt_kucuk, fill=tema["metin_gri"])
    skala_x += 70

    for txt, rnk in skala_ogeleri:
        draw.rounded_rectangle([(skala_x, skala_y), (skala_x + 40, skala_y + 20)], radius=4, fill=rnk)
        draw.text((skala_x + 4, skala_y + 24), txt, font=_font(12, 700.0), fill=tema["metin_gri"])
        skala_x += 46

    not_txt = f"{tema['ad']}"
    nw = draw.textlength(not_txt, font=f_alt_kucuk)
    draw.text((1035 - nw, 1264), not_txt, font=f_alt_kucuk, fill=tema["baslik_fg"])
    draw.text((1035 - 200, 1292), "Yatırım tavsiyesi değildir.", font=_font(14, 500.0), fill=tema["metin_gri"])

    cikti_yolu = CIKTI_DIR / f"varyasyon_{tema['id']}.jpg"
    img.save(cikti_yolu, "JPEG", quality=95)
    return cikti_yolu


def main():
    print("Canlı borsa verileri alınıyor...")
    sektor_verileri = piyasa.isi_haritasi_verileri_getir()

    uretilen_yollar = []
    for tema in TEMALAR_2:
        p = kart_uret_tema(tema, sektor_verileri)
        uretilen_yollar.append((tema, p))
        print(f"[{tema['id']}/20] {tema['ad']} üretildi -> {p.name}")

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("Telegram ayarları eksik!")
        return

    print("Telegram'a yeni 10 varyasyon (11-20) gönderiliyor...")

    # 1. Grup (11-15)
    media1 = []
    files1 = {}
    for i, (tema, p) in enumerate(uretilen_yollar[:5]):
        key = f"photo_{i}"
        cap = f"🎨 <b>{tema['ad']}</b>" if i == 0 else ""
        media1.append({"type": "photo", "media": f"attach://{key}", "caption": cap, "parse_mode": "HTML"})
        files1[key] = open(p, "rb")

    r1 = requests.post(
        f"https://api.telegram.org/bot{token}/sendMediaGroup",
        data={"chat_id": chat_id, "media": str(media1).replace("'", '"')},
        files=files1,
        timeout=30,
    )
    for f in files1.values():
        f.close()
    print("Grup 1 (11-15) Gönderim:", r1.status_code)

    # 2. Grup (16-20)
    media2 = []
    files2 = {}
    for i, (tema, p) in enumerate(uretilen_yollar[5:]):
        key = f"photo_{i}"
        cap = f"🎨 <b>{tema['ad']}</b>" if i == 0 else ""
        media2.append({"type": "photo", "media": f"attach://{key}", "caption": cap, "parse_mode": "HTML"})
        files2[key] = open(p, "rb")

    r2 = requests.post(
        f"https://api.telegram.org/bot{token}/sendMediaGroup",
        data={"chat_id": chat_id, "media": str(media2).replace("'", '"')},
        files=files2,
        timeout=30,
    )
    for f in files2.values():
        f.close()
    print("Grup 2 (16-20) Gönderim:", r2.status_code)

    # Özet Açıklama Mesajı
    ozet = (
        "🎨 <b>10 YENİ FARKLI RENK VARYASYONU DAHA HAZIRLANDI (11-20)</b>\n\n"
        "1️⃣1️⃣ <b>Varyasyon 11:</b> Espresso & Sıcak Moka (Kahve/Moka Koyu Tema)\n"
        "1️⃣2️⃣ <b>Varyasyon 12:</b> Buzul Nane & Kutup Ferahlığı (Pastel Nane Açık Tema)\n"
        "1️⃣3️⃣ <b>Varyasyon 13:</b> Gün Batımı Mercan & Sıcak Şeftali (Sıcak Mercan Açık Tema)\n"
        "1️⃣4️⃣ <b>Varyasyon 14:</b> Derin Petrol & Siber Turkuaz (Petrol Yeşili Koyu Tema)\n"
        "1️⃣5️⃣ <b>Varyasyon 15:</b> İngiliz Yarış Yeşili & Antik Altın (Klasik Asil Yeşil Koyu Tema)\n"
        "1️⃣6️⃣ <b>Varyasyon 16:</b> Gül Kurusu & Kuvars Zarafeti (Pastel Gül/Kuvars Açık Tema)\n"
        "1️⃣7️⃣ <b>Varyasyon 17:</b> Kadife Böğürtlen & Gece Mürdümü (Lüks Mürdüm Koyu Tema)\n"
        "1️⃣8️⃣ <b>Varyasyon 18:</b> Endüstriyel Beton & Sarı İkaz (Minimal Beton Gri Açık Tema)\n"
        "1️⃣9️⃣ <b>Varyasyon 19:</b> Derin Uzay & Parlak Camgöbeği (Kozmik Mavi/Camgöbeği Koyu Tema)\n"
        "2️⃣0️⃣ <b>Varyasyon 20:</b> Çöl Kumulu & Sıcak Terracotta (Doğal Kum/Toprak Açık Tema)\n\n"
        "👉 <i>Toplam 20 varyasyon oldu! Hangisi en çok içine sindiyse numarasını söylemen yeterli kanka!</i>"
    )
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": ozet, "parse_mode": "HTML"},
        timeout=15,
    )
    print("Özet mesajı iletildi!")


if __name__ == "__main__":
    main()
