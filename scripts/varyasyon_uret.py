"""
scripts/varyasyon_uret.py — 10 Farklı Renk ve Zemin Temasında Piyasa Kartı Üretir ve Telegram'a Gönderir.
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

# 10 FARKLI TEMA TANIMI
TEMALAR = [
    {
        "id": 1,
        "ad": "Varyasyon 1 — Buzul Slate & Lacivert",
        "tur": "light",
        "bg_ust": (236, 241, 248),
        "bg_orta": (220, 229, 240),
        "bg_alt": (202, 216, 232),
        "glow": (30, 58, 138, 30),
        "container_bg": (252, 254, 255),
        "container_border": (195, 208, 226),
        "ribbon_bg": (15, 23, 42),
        "ribbon_fg": (255, 255, 255),
        "baslik_fg": (15, 23, 42),
        "metin_gri": (90, 105, 128),
        "rozet_bg": (15, 23, 42),
        "rozet_border": (245, 158, 11),
        "rozet_fg": (245, 158, 11),
        "footer_line": (185, 198, 216),
        "koyu_tema": False,
    },
    {
        "id": 2,
        "ad": "Varyasyon 2 — Lüks Fildişi & Sıcak Krem",
        "tur": "light",
        "bg_ust": (247, 245, 239),
        "bg_orta": (236, 231, 220),
        "bg_alt": (222, 214, 198),
        "glow": (180, 83, 9, 25),
        "container_bg": (255, 254, 250),
        "container_border": (216, 203, 182),
        "ribbon_bg": (45, 34, 24),
        "ribbon_fg": (255, 255, 255),
        "baslik_fg": (38, 28, 18),
        "metin_gri": (115, 100, 85),
        "rozet_bg": (45, 34, 24),
        "rozet_border": (217, 119, 6),
        "rozet_fg": (245, 158, 11),
        "footer_line": (205, 190, 170),
        "koyu_tema": False,
    },
    {
        "id": 3,
        "ad": "Varyasyon 3 — Gece Yarısı Derin Lacivert",
        "tur": "dark",
        "bg_ust": (10, 16, 36),
        "bg_orta": (14, 23, 52),
        "bg_alt": (8, 12, 28),
        "glow": (37, 99, 235, 45),
        "container_bg": (17, 27, 58),
        "container_border": (45, 68, 115),
        "ribbon_bg": (24, 38, 80),
        "ribbon_fg": (255, 255, 255),
        "baslik_fg": (255, 255, 255),
        "metin_gri": (148, 163, 184),
        "rozet_bg": (24, 38, 80),
        "rozet_border": (56, 189, 248),
        "rozet_fg": (56, 189, 248),
        "footer_line": (38, 55, 95),
        "koyu_tema": True,
    },
    {
        "id": 4,
        "ad": "Varyasyon 4 — Titanyum & Obsidyen Siyahı",
        "tur": "dark",
        "bg_ust": (13, 17, 24),
        "bg_orta": (19, 25, 36),
        "bg_alt": (10, 14, 20),
        "glow": (56, 189, 248, 25),
        "container_bg": (24, 32, 46),
        "container_border": (50, 65, 90),
        "ribbon_bg": (34, 46, 68),
        "ribbon_fg": (255, 255, 255),
        "baslik_fg": (255, 255, 255),
        "metin_gri": (156, 163, 175),
        "rozet_bg": (34, 46, 68),
        "rozet_border": (96, 165, 250),
        "rozet_fg": (96, 165, 250),
        "footer_line": (40, 52, 72),
        "koyu_tema": True,
    },
    {
        "id": 5,
        "ad": "Varyasyon 5 — Mat Grafit & Karbon",
        "tur": "dark",
        "bg_ust": (24, 25, 29),
        "bg_orta": (32, 33, 39),
        "bg_alt": (18, 19, 22),
        "glow": (239, 68, 68, 25),
        "container_bg": (38, 40, 48),
        "container_border": (68, 72, 85),
        "ribbon_bg": (48, 50, 60),
        "ribbon_fg": (255, 255, 255),
        "baslik_fg": (255, 255, 255),
        "metin_gri": (160, 165, 175),
        "rozet_bg": (48, 50, 60),
        "rozet_border": (239, 68, 68),
        "rozet_fg": (248, 113, 113),
        "footer_line": (55, 58, 68),
        "koyu_tema": True,
    },
    {
        "id": 6,
        "ad": "Varyasyon 6 — İskandinav Zümrüt & Derin Orman",
        "tur": "dark",
        "bg_ust": (8, 24, 20),
        "bg_orta": (13, 38, 30),
        "bg_alt": (6, 18, 14),
        "glow": (52, 211, 153, 35),
        "container_bg": (18, 48, 38),
        "container_border": (38, 85, 70),
        "ribbon_bg": (24, 65, 52),
        "ribbon_fg": (255, 255, 255),
        "baslik_fg": (255, 255, 255),
        "metin_gri": (150, 185, 170),
        "rozet_bg": (24, 65, 52),
        "rozet_border": (52, 211, 153),
        "rozet_fg": (52, 211, 153),
        "footer_line": (30, 70, 58),
        "koyu_tema": True,
    },
    {
        "id": 7,
        "ad": "Varyasyon 7 — Sis Grisi & Stüdyo Minimal",
        "tur": "light",
        "bg_ust": (242, 244, 247),
        "bg_orta": (230, 234, 240),
        "bg_alt": (212, 218, 228),
        "glow": (100, 116, 139, 30),
        "container_bg": (255, 255, 255),
        "container_border": (195, 204, 216),
        "ribbon_bg": (30, 41, 59),
        "ribbon_fg": (255, 255, 255),
        "baslik_fg": (30, 41, 59),
        "metin_gri": (100, 116, 139),
        "rozet_bg": (30, 41, 59),
        "rozet_border": (148, 163, 184),
        "rozet_fg": (241, 245, 249),
        "footer_line": (188, 198, 212),
        "koyu_tema": False,
    },
    {
        "id": 8,
        "ad": "Varyasyon 8 — Siber Gece Moru & Neon",
        "tur": "dark",
        "bg_ust": (18, 10, 34),
        "bg_orta": (28, 14, 52),
        "bg_alt": (12, 6, 24),
        "glow": (168, 85, 247, 45),
        "container_bg": (34, 18, 62),
        "container_border": (75, 45, 125),
        "ribbon_bg": (48, 26, 88),
        "ribbon_fg": (255, 255, 255),
        "baslik_fg": (255, 255, 255),
        "metin_gri": (192, 175, 220),
        "rozet_bg": (48, 26, 88),
        "rozet_border": (217, 70, 239),
        "rozet_fg": (217, 70, 239),
        "footer_line": (65, 38, 105),
        "koyu_tema": True,
    },
    {
        "id": 9,
        "ad": "Varyasyon 9 — Bloomberg Finans Terminali (Lacivert & Altın)",
        "tur": "dark",
        "bg_ust": (14, 20, 36),
        "bg_orta": (19, 29, 50),
        "bg_alt": (11, 15, 28),
        "glow": (245, 158, 11, 35),
        "container_bg": (22, 34, 58),
        "container_border": (180, 120, 20),
        "ribbon_bg": (30, 46, 78),
        "ribbon_fg": (255, 255, 255),
        "baslik_fg": (255, 255, 255),
        "metin_gri": (165, 180, 205),
        "rozet_bg": (30, 46, 78),
        "rozet_border": (245, 158, 11),
        "rozet_fg": (245, 158, 11),
        "footer_line": (50, 70, 105),
        "koyu_tema": True,
    },
    {
        "id": 10,
        "ad": "Varyasyon 10 — Platin Beyaz & Kraliyet Kobaltı",
        "tur": "light",
        "bg_ust": (245, 247, 251),
        "bg_orta": (234, 238, 246),
        "bg_alt": (218, 225, 238),
        "glow": (37, 99, 235, 35),
        "container_bg": (255, 255, 255),
        "container_border": (175, 195, 230),
        "ribbon_bg": (30, 64, 175),
        "ribbon_fg": (255, 255, 255),
        "baslik_fg": (30, 58, 138),
        "metin_gri": (90, 110, 140),
        "rozet_bg": (30, 64, 175),
        "rozet_border": (96, 165, 250),
        "rozet_fg": (255, 255, 255),
        "footer_line": (185, 205, 235),
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

    # Konteyner gölgeleri
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
    for tema in TEMALAR:
        p = kart_uret_tema(tema, sektor_verileri)
        uretilen_yollar.append((tema, p))
        print(f"[{tema['id']}/10] {tema['ad']} üretildi -> {p.name}")

    # Telegram'a 2'li Albüm halinde (5 + 5) gönder
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("Telegram ayarları eksik!")
        return

    print("Telegram'a 10 varyasyon gönderiliyor...")

    # 1. Grup (1-5)
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
    print("Grup 1 (1-5) Gönderim:", r1.status_code)

    # 2. Grup (6-10)
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
    print("Grup 2 (6-10) Gönderim:", r2.status_code)

    # Özet Açıklama Mesajı
    ozet = (
        "🎨 <b>10 FARKLI PİYASA KARTI VARYASYONU HAZIRLANDI</b>\n\n"
        "1️⃣ <b>Varyasyon 1:</b> Buzul Slate & Lacivert (Modern Açık Slate)\n"
        "2️⃣ <b>Varyasyon 2:</b> Lüks Fildişi & Sıcak Krem (Lüks Sıcak Tonlar)\n"
        "3️⃣ <b>Varyasyon 3:</b> Gece Yarısı Derin Lacivert (Karanlık Lüks Lacivert)\n"
        "4️⃣ <b>Varyasyon 4:</b> Titanyum & Obsidyen Siyahı (Ultra Modern Dark)\n"
        "5️⃣ <b>Varyasyon 5:</b> Mat Grafit & Karbon (Mat Minimalist Koyu)\n"
        "6️⃣ <b>Varyasyon 6:</b> İskandinav Zümrüt & Derin Orman (Yeşil/Zümrüt Derinlik)\n"
        "7️⃣ <b>Varyasyon 7:</b> Sis Grisi & Stüdyo Minimal (Minimalist Açık Gri)\n"
        "8️⃣ <b>Varyasyon 8:</b> Siber Gece Moru & Neon (Siberpunk Gece Teması)\n"
        "9️⃣ <b>Varyasyon 9:</b> Bloomberg Terminal (Koyu Lacivert & Altın Amber)\n"
        "🔟 <b>Varyasyon 10:</b> Platin Beyaz & Kraliyet Kobaltı (Kraliyet Mavisi Açık Zıtlık)\n\n"
        "👉 <i>Hangi numara hoşuna gittiyse numarasını söylemen yeterli kanka!</i>"
    )
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": ozet, "parse_mode": "HTML"},
        timeout=15,
    )
    print("Özet mesajı iletildi!")


if __name__ == "__main__":
    main()
