"""
haftalik_bulten.py — Hafta sonu borsa ve piyasa kapanış bilançosu infografiği.

Haftalık (5 günlük) BİST 100 en çok kazandıran/kaybettiren hisseleri ve
makro göstergeleri (Altın, Dolar, Euro, Bitcoin, Brent) çekerek 1080x1350
infografik kartı üretir.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import db, make_image
from .piyasa import turkce_sayi

log = logging.getLogger(__name__)

KOK = Path(__file__).resolve().parent.parent
CIKTI_KLASORU = KOK / "data" / "output"
LOGO_YOLU = KOK / "assets" / "logo_circular.png"
FONT_YOLU = KOK / "assets" / "fonts" / "Inter-Variable.ttf"

# Takip edilen BİST devleri
BIST_HISSELERI = [
    "THYAO.IS", "GARAN.IS", "ASELS.IS", "EREGL.IS", "KCHOL.IS", "TUPRS.IS",
    "BIMAS.IS", "SISE.IS", "AKBNK.IS", "YKBNK.IS", "FROTO.IS", "SAHOL.IS",
    "PGSUS.IS", "TCELL.IS", "PETKM.IS", "KOZAL.IS", "ENKAI.IS", "ISCTR.IS",
    "ASTOR.IS", "KONTR.IS", "EKGYO.IS", "HEKTS.IS", "TOASO.IS", "MGROS.IS",
]

MAKRO_SEMBOL_HARITASI = {
    "bist100": {"sembol": "XU100.IS", "ad": "BIST 100", "para": ""},
    "dolar": {"sembol": "TRY=X", "ad": "Dolar / TL", "para": "₺"},
    "euro": {"sembol": "EURTRY=X", "ad": "Euro / TL", "para": "₺"},
    "ons_altin": {"sembol": "GC=F", "ad": "Ons Altın", "para": "$"},
    "btc": {"sembol": "BTC-USD", "ad": "Bitcoin", "para": "$"},
    "brent": {"sembol": "BZ=F", "ad": "Brent Petrol", "para": "$"},
}


def _font(punto: int, wght: float = 500.0) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT_YOLU), punto)
    try:
        f.set_variation_by_axes([20.0, float(wght)])
    except Exception:
        pass
    return f


def _haftalik_degisim_cek(sembol: str) -> dict | None:
    """Yahoo Finance üzerinden 5 günlük getiri ve son fiyatı hesaplar."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sembol}?interval=1d&range=5d"
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
    try:
        r = requests.get(url, headers=headers, timeout=6)
        if r.status_code == 200:
            res = r.json().get("chart", {}).get("result", [])[0]
            closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
            if len(closes) >= 2:
                ilk = closes[0]
                son = closes[-1]
                degisim = ((son - ilk) / ilk) * 100
                return {"fiyat": son, "degisim": degisim}
    except Exception as e:
        log.debug("haftalık veri çekilemedi %s: %s", sembol, e)
    return None


def haftalik_piyasa_verileri_getir() -> dict:
    """
    Haftalık kazanan/kaybeden hisseleri ve makro varlık değişimlerini derler.
    """
    hisse_sonuclari = []
    for s in BIST_HISSELERI:
        veri = _haftalik_degisim_cek(s)
        if veri:
            temiz_sembol = s.replace(".IS", "")
            hisse_sonuclari.append({
                "sembol": temiz_sembol,
                "fiyat": veri["fiyat"],
                "degisim": veri["degisim"],
            })

    hisse_sonuclari.sort(key=lambda x: x["degisim"], reverse=True)
    kazananlar = hisse_sonuclari[:3] if len(hisse_sonuclari) >= 3 else []
    kaybedenler = list(reversed(hisse_sonuclari[-3:])) if len(hisse_sonuclari) >= 3 else []

    # Makro varlıklar
    makro = {}
    for k, info in MAKRO_SEMBOL_HARITASI.items():
        v = _haftalik_degisim_cek(info["sembol"])
        if v:
            makro[k] = {
                "ad": info["ad"],
                "fiyat": v["fiyat"],
                "degisim": v["degisim"],
                "para": info["para"],
            }

    # Gram Altın Canlı Hesabı (Ons * Dolar / 31.1034768)
    if "ons_altin" in makro and "dolar" in makro:
        ons_f = makro["ons_altin"]["fiyat"]
        dolar_f = makro["dolar"]["fiyat"]
        gram_f = (ons_f * dolar_f) / 31.1034768
        gram_deg = ((1 + makro["ons_altin"]["degisim"] / 100) * (1 + makro["dolar"]["degisim"] / 100) - 1) * 100
        makro["gram_altin"] = {
            "ad": "Gram Altın",
            "fiyat": gram_f,
            "degisim": gram_deg,
            "para": "₺",
        }

    return {
        "kazananlar": kazananlar,
        "kaybedenler": kaybedenler,
        "makro": makro,
        "tarih": datetime.now(timezone.utc).strftime("%d.%m.%Y"),
    }


def haftalik_kart_uret(ayarlar: dict, veri: dict | None = None) -> Path:
    """
    1080x1350 boyutunda ultra-lüks Hafta Sonu Kapanış Bilançosu infografik kartı çizer.
    """
    veri = veri or haftalik_piyasa_verileri_getir()
    genislik, yukseklik = 1080, 1350
    kenar = 50

    img = Image.new("RGB", (genislik, yukseklik), (4, 18, 26))
    ciz = ImageDraw.Draw(img)

    # Derin Petrol Arka Plan
    for y in range(yukseklik):
        r = int(4 + (10 - 4) * (y / yukseklik))
        g = int(24 + (16 - 24) * (y / yukseklik))
        b = int(36 + (28 - 36) * (y / yukseklik))
        ciz.line([(0, y), (genislik, y)], fill=(r, g, b))

    # 1. Header & Logo
    if LOGO_YOLU.exists():
        try:
            logo = Image.open(LOGO_YOLU).convert("RGBA").resize((120, 120), Image.LANCZOS)
            img.paste(logo, (kenar, 45), mask=logo)
        except Exception:
            pass

    ciz.text((kenar + 140, 52), "HAFTANIN BİLANÇOSU", font=_font(38, 800.0), fill=(255, 255, 255))
    ciz.text((kenar + 140, 102), "BORSA & PİYASA KAZANANLARI • 5 GÜNLÜK GETİRİ", font=_font(20, 600.0), fill=(6, 182, 212))

    # Altın Ayırıcı Çizgi
    ciz.line([(kenar, 180), (genislik - kenar, 180)], fill=(226, 170, 88), width=3)

    # 2. HAFTANIN KAZANANLARI (BİST 100)
    y_kazan = 210
    ciz.rounded_rectangle([kenar, y_kazan, genislik - kenar, y_kazan + 42], radius=8, fill=(16, 185, 129, 40), outline=(16, 185, 129), width=1)
    ciz.text((kenar + 16, y_kazan + 9), "🟢  HAFTANIN EN ÇOK YÜKSELENLERİ (BİST 100)", font=_font(21, 700.0), fill=(16, 185, 129))

    y_row = y_kazan + 54
    for h in veri.get("kazananlar", []):
        ciz.rounded_rectangle([kenar, y_row, genislik - kenar, y_row + 70], radius=10, fill=(8, 28, 38), outline=(16, 185, 129, 100), width=1)
        ciz.text((kenar + 24, y_row + 18), h["sembol"], font=_font(30, 800.0), fill=(255, 255, 255))
        ciz.text((kenar + 220, y_row + 22), f"{turkce_sayi(h['fiyat'])} ₺", font=_font(26, 600.0), fill=(206, 214, 230))
        rozet_metin = f"▲ +%{abs(h['degisim']):.2f}"
        f_r = _font(25, 800.0)
        rw = ciz.textlength(rozet_metin, font=f_r) + 28
        rx = genislik - kenar - rw - 16
        ciz.rounded_rectangle([rx, y_row + 12, rx + rw, y_row + 58], radius=8, fill=(16, 185, 129))
        ciz.text((rx + 14, y_row + 18), rozet_metin, font=f_r, fill=(255, 255, 255))
        y_row += 82

    # 3. HAFTANIN KAYBEDENLERİ (BİST 100)
    y_kaybet = y_row + 10
    ciz.rounded_rectangle([kenar, y_kaybet, genislik - kenar, y_kaybet + 42], radius=8, fill=(244, 63, 94, 40), outline=(244, 63, 94), width=1)
    ciz.text((kenar + 16, y_kaybet + 9), "🔴  HAFTANIN EN ÇOK DÜŞENLERİ (BİST 100)", font=_font(21, 700.0), fill=(244, 63, 94))

    y_row2 = y_kaybet + 54
    for h in veri.get("kaybedenler", []):
        ciz.rounded_rectangle([kenar, y_row2, genislik - kenar, y_row2 + 70], radius=10, fill=(8, 28, 38), outline=(244, 63, 94, 100), width=1)
        ciz.text((kenar + 24, y_row2 + 18), h["sembol"], font=_font(30, 800.0), fill=(255, 255, 255))
        ciz.text((kenar + 220, y_row2 + 22), f"{turkce_sayi(h['fiyat'])} ₺", font=_font(26, 600.0), fill=(206, 214, 230))
        rozet_metin = f"▼ -%{abs(h['degisim']):.2f}"
        f_r = _font(25, 800.0)
        rw = ciz.textlength(rozet_metin, font=f_r) + 28
        rx = genislik - kenar - rw - 16
        ciz.rounded_rectangle([rx, y_row2 + 12, rx + rw, y_row2 + 58], radius=8, fill=(244, 63, 94))
        ciz.text((rx + 14, y_row2 + 18), rozet_metin, font=f_r, fill=(255, 255, 255))
        y_row2 += 82

    # 4. MAKRO VARLIKLAR BÖLÜMÜ
    y_makro = y_row2 + 10
    ciz.rounded_rectangle([kenar, y_makro, genislik - kenar, y_makro + 42], radius=8, fill=(226, 170, 88, 40), outline=(226, 170, 88), width=1)
    ciz.text((kenar + 16, y_makro + 9), "📊  MAKRO VARLIKLAR (5 GÜNLÜK GETİRİ)", font=_font(21, 700.0), fill=(226, 170, 88))

    makro_items = [
        veri.get("makro", {}).get("bist100"),
        veri.get("makro", {}).get("gram_altin"),
        veri.get("makro", {}).get("dolar"),
        veri.get("makro", {}).get("euro"),
        veri.get("makro", {}).get("btc"),
        veri.get("makro", {}).get("brent"),
    ]
    makro_items = [m for m in makro_items if m is not None]

    kart_w = (genislik - 2 * kenar - 24) // 3
    for idx, m in enumerate(makro_items[:6]):
        col = idx % 3
        row = idx // 3
        kx = kenar + col * (kart_w + 12)
        ky = y_makro + 54 + row * 92

        is_pos = m["degisim"] >= 0
        renk = (16, 185, 129) if is_pos else (244, 63, 94)
        ciz.rounded_rectangle([kx, ky, kx + kart_w, ky + 82], radius=10, fill=(8, 24, 34), outline=(*renk[:3], 100), width=1)

        ciz.text((kx + 14, ky + 10), m["ad"], font=_font(20, 700.0), fill=(255, 255, 255))
        ciz.text((kx + 14, ky + 34), f"{turkce_sayi(m['fiyat'], 2 if m['fiyat'] < 1000 else 0)} {m['para']}", font=_font(22, 600.0), fill=(206, 214, 230))

        simge = "▲" if is_pos else "▼"
        yuzde_metin = f"{simge} %{abs(m['degisim']):.2f}"
        ciz.text((kx + 14, ky + 58), yuzde_metin, font=_font(18, 700.0), fill=renk)

    # 5. Alt Bilgi
    alt_y = yukseklik - 60
    ciz.text((kenar, alt_y), "Yatırım tavsiyesi değildir • Kaynak: Borsa İstanbul & Yahoo Finance", font=_font(20, 500.0), fill=(148, 163, 184))
    img = make_image.kanal_ikonlari_bas(img, ayarlar, alt_y + 10)

    CIKTI_KLASORU.mkdir(parents=True, exist_ok=True)
    cikti_yolu = CIKTI_KLASORU / "haftalik_bilanco.jpg"
    img.save(cikti_yolu, "JPEG", quality=95, subsampling=0, optimize=True)
    log.info("Haftalık bilanço kartı üretildi: %s", cikti_yolu)
    return cikti_yolu


def haftanin_onemli_haberleri(con, limit: int = 3) -> list[dict]:
    """Son 7 gün içinde yayınlanmış en yüksek puanlı haberleri getirir."""
    return con.execute(
        """
        SELECT *
        FROM haberler
        WHERE durum = 'yayinlandi'
          AND yayin_tarihi >= datetime('now', '-7 day')
        ORDER BY onem_puani DESC, yayin_tarihi DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
