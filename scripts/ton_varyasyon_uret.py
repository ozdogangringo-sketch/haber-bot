"""
scripts/ton_varyasyon_uret.py — Sektör başlığı şerit zeminini gittikçe koyulaşan 5 farklı tonda üretir ve Telegram'a gönderir.
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
from src.piyasa_kart import _font, _squarify, _fiyat_bicimlendir, _arka_plan_ciz, _renk_hesapla_canli

GENISLIK = 1080
YUKSEKLIK = 1350
LOGO_YOLU = KOK / "assets" / "logo_circular.png"
CIKTI_DIR = KOK / "data" / "output"
CIKTI_DIR.mkdir(parents=True, exist_ok=True)

# 5 Gittikçe Koyulaşan Şerit Tonu
TONLAR = [
    {
        "no": 1,
        "ad": "Ton 1 — Yumuşak Açık Krem (#EBE6DC)",
        "ribbon_bg": (235, 230, 220),
        "ribbon_fg": (6, 31, 36),
    },
    {
        "no": 2,
        "ad": "Ton 2 — Sıcak Kum & Fildişi (#DED6C8)",
        "ribbon_bg": (222, 214, 200),
        "ribbon_fg": (6, 31, 36),
    },
    {
        "no": 3,
        "ad": "Ton 3 — Koyu Bej & Karamel Tozu (#D0C4B2)",
        "ribbon_bg": (208, 196, 178),
        "ribbon_fg": (6, 31, 36),
    },
    {
        "no": 4,
        "ad": "Ton 4 — Sıcak Taş & Muted Slate (#BEB4A8)",
        "ribbon_bg": (190, 180, 168),
        "ribbon_fg": (6, 31, 36),
    },
    {
        "no": 5,
        "ad": "Ton 5 — Zengin Bronz Bej (#AAA096)",
        "ribbon_bg": (170, 160, 150),
        "ribbon_fg": (6, 31, 36),
    },
]

RENK_KART_CONTAINER = (12, 45, 52)
RENK_KART_BORDER = (25, 85, 96)
RENK_BASLIK_KOYU = (255, 255, 255)
RENK_GRI_METIN = (140, 185, 195)
RENK_BEYAZ = (255, 255, 255)
RENK_FIYAT_ACIK = (226, 232, 240)


def ton_karti_uret(ton: dict, sektor_verileri: dict) -> Path:
    img = _arka_plan_ciz()
    draw = ImageDraw.Draw(img)

    f_etiket = _font(20, 800.0)
    f_baslik = _font(44, 900.0)
    f_tarih_buyuk = _font(24, 800.0)
    f_tarih_kucuk = _font(19, 600.0)
    f_sektor = _font(18, 900.0)
    f_alt_kucuk = _font(17, 600.0)

    logo_boyut = 126
    logo_x = 45
    logo_y = 38

    if LOGO_YOLU.exists():
        try:
            golge = Image.new("RGBA", (GENISLIK, YUKSEKLIK), (0, 0, 0, 0))
            ImageDraw.Draw(golge).ellipse(
                [logo_x - 4, logo_y - 2, logo_x + logo_boyut + 6, logo_y + logo_boyut + 8],
                fill=(0, 0, 0, 120),
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
    rozet_txt = f"DAILYBRIEF · {ton['ad'].split(' — ')[0].upper()}"
    rw = draw.textlength(rozet_txt, font=f_etiket)
    draw.rounded_rectangle(
        [(header_x, 42), (header_x + rw + 22, 78)],
        radius=8,
        fill=(18, 62, 72),
        outline=(6, 182, 212),
        width=2,
    )
    draw.text((header_x + 11, 48), rozet_txt, font=f_etiket, fill=(6, 182, 212))

    draw.text((header_x, 92), "Güne Nasıl Başladı?", font=f_baslik, fill=RENK_BASLIK_KOYU)

    aylar = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
             "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
    gunler = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    simdi = datetime.now(timezone.utc)
    tarih_satir1 = f"{simdi.day} {aylar[simdi.month - 1]} {simdi.year}"
    tarih_satir2 = f"{gunler[simdi.weekday()]} · Açılış"

    w_t1 = draw.textlength(tarih_satir1, font=f_tarih_buyuk)
    w_t2 = draw.textlength(tarih_satir2, font=f_tarih_kucuk)

    sag_kenar = 1035
    draw.text((sag_kenar - w_t1, 86), tarih_satir1, font=f_tarih_buyuk, fill=RENK_BASLIK_KOYU)
    draw.text((sag_kenar - w_t2, 118), tarih_satir2, font=f_tarih_kucuk, fill=RENK_GRI_METIN)

    sektor_yerlesimi = [
        ("BİST & TÜRKİYE HİSSELERİ", (45, 180, 990, 490)),
        ("DÖVİZ & EMTİA (MAKRO)", (45, 688, 490, 545)),
        ("KÜRESEL DEVLER & KRİPTO", (545, 688, 490, 545)),
    ]

    ribbon_h = 36

    shadow_img = Image.new("RGBA", (GENISLIK, YUKSEKLIK), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow_img)
    for _, (sx, sy, sw, sh) in sektor_yerlesimi:
        sdraw.rounded_rectangle([(sx, sy + 3), (sx + sw, sy + sh + 5)], radius=14, fill=(0, 0, 0, 80))
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
            fill=RENK_KART_CONTAINER,
            outline=RENK_KART_BORDER,
            width=2,
        )
        
        # Sektör Şerit Zemini (Gittikçe koyulaşan ton)
        draw.rounded_rectangle(
            [(sx, sy), (sx + sw, sy + ribbon_h)],
            radius=10,
            fill=ton["ribbon_bg"],
        )
        # Sektör Başlık Yazısı
        draw.text((sx + 14, sy + 8), f"› {sektor_adi}", font=f_sektor, fill=ton["ribbon_fg"])

        icerik_rect = (sx + 2, sy + ribbon_h + 3, sw - 4, sh - ribbon_h - 5)
        hucreler = _squarify(ogeler, icerik_rect)

        for oge, (cx, cy, cw, ch) in hucreler:
            degisim = oge["degisim"]
            fiyat = oge.get("fiyat", 0.0)
            sym = oge.get("sym", "")
            fiyat_str = _fiyat_bicimlendir(sym, fiyat)

            c_bg, c_border = _renk_hesapla_canli(degisim)

            draw.rounded_rectangle(
                [(cx + 2, cy + 2), (cx + cw - 2, cy + ch - 2)],
                radius=10,
                fill=c_bg,
                outline=c_border,
                width=1,
            )

            sembol = oge["etiket"]
            chg_str = f"{'▲ +' if degisim >= 0 else '▼ -'}{abs(degisim):.2f}%"

            max_w = cw - 18
            max_p = 44 if (cw >= 200 and ch >= 125) else (34 if (cw >= 130 and ch >= 80) else (24 if (cw >= 80 and ch >= 55) else 18))

            p_sym = max_p
            f_sym = _font(p_sym, 900.0)
            while draw.textlength(sembol, font=f_sym) > max_w and p_sym > 14:
                p_sym -= 2
                f_sym = _font(p_sym, 900.0)

            p_fiyat = max(13, int(p_sym * 0.70))
            f_fiyat = _font(p_fiyat, 700.0)
            while draw.textlength(fiyat_str, font=f_fiyat) > max_w and p_fiyat > 11:
                p_fiyat -= 2
                f_fiyat = _font(p_fiyat, 700.0)

            p_chg = max(13, int(p_sym * 0.72))
            f_chg = _font(p_chg, 800.0)
            while draw.textlength(chg_str, font=f_chg) > max_w and p_chg > 10:
                p_chg -= 2
                f_chg = _font(p_chg, 800.0)

            sw_s = draw.textlength(sembol, font=f_sym)
            sw_f = draw.textlength(fiyat_str, font=f_fiyat)
            sw_c = draw.textlength(chg_str, font=f_chg)
            mid_x = cx + cw / 2

            if ch >= 130 and fiyat_str:
                y1 = cy + int(ch * 0.24) - int(p_sym * 0.5)
                y2 = cy + int(ch * 0.54) - int(p_fiyat * 0.5)
                y3 = cy + int(ch * 0.80) - int(p_chg * 0.5)
                draw.text((mid_x - sw_s / 2, y1), sembol, font=f_sym, fill=RENK_BEYAZ)
                draw.text((mid_x - sw_f / 2, y2), fiyat_str, font=f_fiyat, fill=RENK_FIYAT_ACIK)
                draw.text((mid_x - sw_c / 2, y3), chg_str, font=f_chg, fill=RENK_BEYAZ)
            elif ch >= 85 and fiyat_str:
                y1 = cy + int(ch * 0.28) - int(p_sym * 0.5)
                y2 = cy + int(ch * 0.58) - int(p_fiyat * 0.5)
                y3 = cy + int(ch * 0.82) - int(p_chg * 0.5)
                draw.text((mid_x - sw_s / 2, y1), sembol, font=f_sym, fill=RENK_BEYAZ)
                draw.text((mid_x - sw_f / 2, y2), fiyat_str, font=f_fiyat, fill=RENK_FIYAT_ACIK)
                draw.text((mid_x - sw_c / 2, y3), chg_str, font=f_chg, fill=RENK_BEYAZ)
            elif ch >= 55 and fiyat_str:
                alt_metin = f"{fiyat_str}  ·  {chg_str}" if cw >= 150 else f"{fiyat_str} {chg_str}"
                sw_alt = draw.textlength(alt_metin, font=f_chg)
                y1 = cy + int(ch * 0.32) - int(p_sym * 0.5)
                y2 = cy + int(ch * 0.72) - int(p_chg * 0.5)
                draw.text((mid_x - sw_s / 2, y1), sembol, font=f_sym, fill=RENK_BEYAZ)
                draw.text((mid_x - sw_alt / 2, y2), alt_metin, font=f_chg, fill=RENK_BEYAZ)
            else:
                y1 = cy + int(ch * 0.30) - int(p_sym * 0.5)
                y2 = cy + int(ch * 0.58) - int(p_fiyat * 0.5)
                y3 = cy + int(ch * 0.82) - int(p_chg * 0.5)
                draw.text((mid_x - sw_s / 2, y1), sembol, font=f_sym, fill=RENK_BEYAZ)
                if fiyat_str:
                    draw.text((mid_x - sw_f / 2, y2), fiyat_str, font=f_fiyat, fill=RENK_FIYAT_ACIK)
                draw.text((mid_x - sw_c / 2, y3), chg_str, font=f_chg, fill=RENK_BEYAZ)

    draw.line([(45, 1245), (1035, 1245)], fill=(24, 75, 85), width=1)

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

    draw.text((skala_x, skala_y + 2), "SKALA:", font=f_alt_kucuk, fill=RENK_GRI_METIN)
    skala_x += 70

    for txt, rnk in skala_ogeleri:
        draw.rounded_rectangle([(skala_x, skala_y), (skala_x + 40, skala_y + 20)], radius=4, fill=rnk)
        draw.text((skala_x + 4, skala_y + 24), txt, font=_font(12, 700.0), fill=RENK_GRI_METIN)
        skala_x += 46

    not_txt = f"{ton['ad']}"
    nw = draw.textlength(not_txt, font=f_alt_kucuk)
    draw.text((1035 - nw, 1264), not_txt, font=f_alt_kucuk, fill=RENK_BASLIK_KOYU)
    draw.text((1035 - 200, 1292), "Yatırım tavsiyesi değildir.", font=_font(14, 500.0), fill=RENK_GRI_METIN)

    cikti_yolu = CIKTI_DIR / f"ton_{ton['no']}.jpg"
    img.save(cikti_yolu, "JPEG", quality=95)
    return cikti_yolu


def main():
    print("Canlı borsa verileri alınıyor...")
    sektor_verileri = piyasa.isi_haritasi_verileri_getir()

    uretilenler = []
    for t in TONLAR:
        p = ton_karti_uret(t, sektor_verileri)
        uretilenler.append((t, p))
        print(f"[{t['no']}/5] {t['ad']} üretildi -> {p.name}")

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("Telegram ayarları eksik!")
        return

    print("Telegram'a 5 tonluk albüm gönderiliyor...")
    media = []
    files = {}
    for i, (t, p) in enumerate(uretilenler):
        key = f"photo_{i}"
        cap = f"🎨 <b>{t['ad']}</b>" if i == 0 else ""
        media.append({"type": "photo", "media": f"attach://{key}", "caption": cap, "parse_mode": "HTML"})
        files[key] = open(p, "rb")

    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMediaGroup",
        data={"chat_id": chat_id, "media": str(media).replace("'", '"')},
        files=files,
        timeout=30,
    )
    for f in files.values():
        f.close()
    print("Albüm Gönderim Durumu:", r.status_code)

    ozet = (
        "🎨 <b>SEKTÖR ŞERİT ZEMİNİ İÇİN GİTTİKÇE KOYULAŞAN 5 TON</b>\n\n"
        "1️⃣ <b>Ton 1:</b> Yumuşak Açık Krem (#EBE6DC)\n"
        "2️⃣ <b>Ton 2:</b> Sıcak Kum & Fildişi (#DED6C8)\n"
        "3️⃣ <b>Ton 3:</b> Koyu Bej & Karamel Tozu (#D0C4B2)\n"
        "4️⃣ <b>Ton 4:</b> Sıcak Taş & Muted Slate (#BEB4A8)\n"
        "5️⃣ <b>Ton 5:</b> Zengin Bronz Bej (#AAA096)\n\n"
        "👉 <i>1'den 5'e doğru koyulaşıyor kanka. Hangisinin tonu en iyi oturduysa numarasını söylemen yeterli!</i>"
    )
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": ozet, "parse_mode": "HTML"},
        timeout=15,
    )
    print("Özet mesajı iletildi!")


if __name__ == "__main__":
    main()
