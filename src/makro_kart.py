"""
makro_kart.py — 1080x1350 (4:5) ve 1080x1920 (9:16) Makro Ekonomik Kritik Veri İnfografik Kartı Motoru.

TCMB Faiz Kararları, TÜİK Enflasyon Verileri, Fed FOMC Kararları ve Kritik Makro Veriler için
dev vitrin rakamı, 3'lü karşılaştırma matrisi, anlık piyasa reaksiyonu ve kurumsal analizi
tek bir görselde çizer.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import piyasa

log = logging.getLogger(__name__)

KOK = Path(__file__).resolve().parent.parent
FONT_YOLU = KOK / "assets" / "fonts" / "Inter-Variable.ttf"
LOGO_YOLU = KOK / "assets" / "logo_circular.png"
CIKTI_KLASORU = KOK / "data" / "output"

# Renk Paleti (Derin Petrol & Siber Turkuaz / Altın Rozet)
RENK_ARKA_UST = (4, 24, 28)              # #04181C
RENK_ARKA_ORTA = (8, 38, 44)             # #08262C
RENK_ARKA_ALT = (3, 16, 20)              # #031014

RENK_KART_CONTAINER = (8, 32, 38)        # #082026
RENK_KART_BORDER = (20, 68, 78)          # #14444E
RENK_KART_IC_BG = (12, 45, 54)           # #0C2D36
RENK_KART_IC_BORDER = (28, 85, 96)       # #1C5560

RENK_BEYAZ = (255, 255, 255)
RENK_GRI_METIN = (140, 185, 195)         # #8CB9C3
RENK_CYAN = (6, 182, 212)                # #06B6D4
RENK_ALTIN = (245, 158, 11)              # #F59E0B
RENK_YESIL = (16, 185, 129)              # #10B981
RENK_KIRMIZI = (239, 68, 68)             # #EF4444
RENK_MAVI = (59, 130, 246)               # #3B82F6


def _font(punto: int, agirlik: float = 600.0) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT_YOLU), punto)
    try:
        f.set_variation_by_axes([20.0, agirlik])
    except Exception:
        pass
    return f


def _arkaplan_olustur(genislik: int, yukseklik: int) -> Image.Image:
    """Derin Okyanus Petrolü dikey gradyan zemin üretir."""
    img = Image.new("RGB", (genislik, yukseklik), RENK_ARKA_UST)
    draw = ImageDraw.Draw(img)

    for y in range(yukseklik):
        t = y / float(yukseklik)
        if t < 0.5:
            t2 = t * 2.0
            r = int(RENK_ARKA_UST[0] + (RENK_ARKA_ORTA[0] - RENK_ARKA_UST[0]) * t2)
            g = int(RENK_ARKA_UST[1] + (RENK_ARKA_ORTA[1] - RENK_ARKA_UST[1]) * t2)
            b = int(RENK_ARKA_UST[2] + (RENK_ARKA_ORTA[2] - RENK_ARKA_UST[2]) * t2)
        else:
            t2 = (t - 0.5) * 2.0
            r = int(RENK_ARKA_ORTA[0] + (RENK_ARKA_ALT[0] - RENK_ARKA_ORTA[0]) * t2)
            g = int(RENK_ARKA_ORTA[1] + (RENK_ARKA_ALT[1] - RENK_ARKA_ORTA[1]) * t2)
            b = int(RENK_ARKA_ORTA[2] + (RENK_ARKA_ALT[2] - RENK_ARKA_ORTA[2]) * t2)
        draw.line([(0, y), (genislik, y)], fill=(r, g, b))

    # Atmosfer Parıltısı (Radial Glow)
    parilti = Image.new("RGBA", (genislik, yukseklik), (0, 0, 0, 0))
    pdraw = ImageDraw.Draw(parilti)
    merkez_x, merkez_y = genislik // 2, int(yukseklik * 0.38)
    for r in range(320, 0, -8):
        alfa = int(22 * (1.0 - (r / 320.0)))
        pdraw.ellipse(
            [merkez_x - r, merkez_y - r, merkez_x + r, merkez_y + r],
            fill=(6, 182, 212, alfa),
        )
    parilti = parilti.filter(ImageFilter.GaussianBlur(radius=25))
    img.paste(parilti, (0, 0), parilti)

    return img


def makro_karti_ciz(
    rozet_metni: str,
    ana_deger: str,
    durum_etiketi: str,
    karsilastirma: dict | None = None,
    spot_metin: str = "",
    kaynak: str = "TCMB",
    piyasa_ozeti: dict | None = None,
    dikey_story: bool = False,
    cikti_yolu: Path | str | None = None,
) -> Path:
    """
    1080x1350 veya 1080x1920 çözünürlükte Makro İnfografik Kartı üretir.

    * `rozet_metni`: "TCMB POLİTİKA FAİZİ" / "TÜİK TÜFE ENFLASYON" / "FED FOMC FAİZİ"
    * `ana_deger`: "%45.00" / "%61.78" / "%5.25"
    * `durum_etiketi`: "POLİTİKA FAİZİ SABİT BIRAKILDI" / "+250 BAZ PUAN ARTIŞ" / "YILLIK TÜFE ARTIŞI"
    * `karsilastirma`: {"onceki": "%45.00", "beklenti": "%45.00", "aciklanan": "%45.00"}
    * `spot_metin`: Karar metni veya Gemini analizi özeti.
    * `kaynak`: "TCMB" / "TÜİK" / "Federal Reserve"
    """
    genislik = 1080
    yukseklik = 1920 if dikey_story else 1350
    CIKTI_KLASORU.mkdir(parents=True, exist_ok=True)

    if cikti_yolu is None:
        prefix = "story" if dikey_story else "post"
        cikti_yolu = CIKTI_KLASORU / f"makro_{prefix}_{int(datetime.now().timestamp())}.jpg"
    else:
        cikti_yolu = Path(cikti_yolu)

    img = _arkaplan_olustur(genislik, yukseklik)
    draw = ImageDraw.Draw(img)

    # 1. Üst Hiyerarşi: Logo & Başlıklar (4:5 safe area y=285..1635 uyumlu)
    y_imlec = 310 if dikey_story else 75

    # 3D 144px Kurumsal Logo (Sol Üst)
    if LOGO_YOLU.exists():
        try:
            with Image.open(LOGO_YOLU) as logo:
                logo_rgb = logo.convert("RGBA").resize((110, 110), Image.Resampling.LANCZOS)
                # Gölge
                golge = Image.new("RGBA", (140, 140), (0, 0, 0, 0))
                gdraw = ImageDraw.Draw(golge)
                gdraw.ellipse([15, 15, 125, 125], fill=(0, 0, 0, 140))
                golge = golge.filter(ImageFilter.GaussianBlur(radius=8))
                img.paste(golge, (65, y_imlec - 5), golge)
                img.paste(logo_rgb, (80, y_imlec + 10), logo_rgb)
        except Exception as e:
            log.warning("Logo yüklenemedi: %s", e)

    # Rozet & Kategori (Sağ Bölüm)
    rozet_x = 210
    draw.rounded_rectangle(
        [rozet_x, y_imlec + 12, rozet_x + 360, y_imlec + 48],
        radius=8,
        fill=RENK_KART_CONTAINER,
        outline=RENK_CYAN,
        width=2,
    )
    draw.text(
        (rozet_x + 16, y_imlec + 18),
        f"›  {rozet_metni.upper()}",
        font=_font(17, 800.0),
        fill=RENK_BEYAZ,
    )

    tarih_str = datetime.now(timezone.utc).strftime("%d.%m.%Y · %H:%M")
    draw.text(
        (rozet_x, y_imlec + 62),
        f"KRİTİK MAKRO RAPORU  ·  {tarih_str}",
        font=_font(16, 600.0),
        fill=RENK_GRI_METIN,
    )

    y_imlec += 145

    # 2. Hero Vitrin Kartı (Dev Rakam & Durum Rozeti)
    hero_kutu_h = 320
    draw.rounded_rectangle(
        [60, y_imlec, genislik - 60, y_imlec + hero_kutu_h],
        radius=24,
        fill=RENK_KART_CONTAINER,
        outline=RENK_KART_BORDER,
        width=2,
    )

    # İnce Üst Işık Çizgisi
    draw.line([(84, y_imlec + 2), (genislik - 84, y_imlec + 2)], fill=RENK_CYAN, width=2)

    # Dev Rakam
    hero_font = _font(100, 900.0)
    bbox_val = hero_font.getbbox(ana_deger)
    val_w = bbox_val[2] - bbox_val[0]
    val_x = (genislik - val_w) // 2
    draw.text((val_x, y_imlec + 35), ana_deger, font=hero_font, fill=RENK_BEYAZ)

    # Durum Rozeti (Örn: "POLİTİKA FAİZİ SABİT TUTULDU")
    durum_font = _font(22, 800.0)
    bbox_durum = durum_font.getbbox(durum_etiketi)
    durum_w = bbox_durum[2] - bbox_durum[0]
    durum_pill_w = durum_w + 50
    durum_x = (genislik - durum_pill_w) // 2
    durum_y = y_imlec + 195

    # Renk tonu belirle
    pill_renk = RENK_CYAN
    if "ARTIŞ" in durum_etiketi.upper() or "YÜKSEL" in durum_etiketi.upper():
        pill_renk = RENK_KIRMIZI if "ENFLASYON" in rozet_metni.upper() else RENK_YESIL
    elif "İNDİRİM" in durum_etiketi.upper() or "DÜŞÜŞ" in durum_etiketi.upper():
        pill_renk = RENK_YESIL if "ENFLASYON" in rozet_metni.upper() else RENK_MAVI
    elif "SABİT" in durum_etiketi.upper():
        pill_renk = RENK_ALTIN

    draw.rounded_rectangle(
        [durum_x, durum_y, durum_x + durum_pill_w, durum_y + 54],
        radius=27,
        fill=pill_renk,
        outline=pill_renk,
        width=2,
    )
    # Koyu arkaplan üzerinde beyaz veya siyah kontrast metin
    yazi_rengi = (10, 20, 25) if pill_renk in (RENK_ALTIN, RENK_CYAN, RENK_YESIL) else RENK_BEYAZ
    draw.text(
        (durum_x + 25, durum_y + 14),
        durum_etiketi,
        font=durum_font,
        fill=yazi_rengi,
    )

    y_imlec += hero_kutu_h + 30

    # 3. 3'lü Karşılaştırma Matrisi (Önceki vs Beklenti vs Açıklanan)
    if karsilastirma:
        matris_h = 130
        draw.rounded_rectangle(
            [60, y_imlec, genislik - 60, y_imlec + matris_h],
            radius=18,
            fill=RENK_KART_IC_BG,
            outline=RENK_KART_IC_BORDER,
            width=1,
        )

        sutun_w = (genislik - 120) / 3.0
        ogeler = [
            ("ÖNCEKİ", karsilastirma.get("onceki", "-"), RENK_GRI_METIN),
            ("BEKLENTİ", karsilastirma.get("beklenti", "-"), RENK_GRI_METIN),
            ("AÇIKLANAN", karsilastirma.get("aciklanan", ana_deger), pill_renk),
        ]

        for i, (etiket, deger, renk) in enumerate(ogeler):
            cx = 60 + i * sutun_w + (sutun_w / 2.0)
            # Etiket
            f_lbl = _font(15, 700.0)
            bb_lbl = f_lbl.getbbox(etiket)
            draw.text((cx - (bb_lbl[2] - bb_lbl[0]) / 2.0, y_imlec + 22), etiket, font=f_lbl, fill=RENK_GRI_METIN)
            # Değer
            f_val = _font(28, 850.0)
            bb_v = f_val.getbbox(str(deger))
            draw.text((cx - (bb_v[2] - bb_v[0]) / 2.0, y_imlec + 58), str(deger), font=f_val, fill=renk)

            # Ayırıcı Dikey Çizgiler
            if i < 2:
                cizgi_x = int(60 + (i + 1) * sutun_w)
                draw.line([(cizgi_x, y_imlec + 20), (cizgi_x, y_imlec + matris_h - 20)], fill=RENK_KART_BORDER, width=1)

        y_imlec += matris_h + 30

    # 4. Anlık Piyasa İlk Reaksiyonu (Dolar, BİST 100, Gram Altın)
    if piyasa_ozeti is None:
        try:
            canli = piyasa.piyasa_verileri_getir()
            dolar = canli.get("dolar", {})
            bist = canli.get("bist100", {})
            gram_altin = canli.get("gram_altin", {})

            dolar_fiyat = f"{dolar.get('fiyat', 0.0):.2f} ₺" if dolar.get("fiyat") else "34.10 ₺"
            dolar_deg = dolar.get("degisim", 0.0)
            bist_fiyat = f"{int(bist.get('fiyat', 0.0)):,}".replace(",", ".") if bist.get("fiyat") else "10.150"
            bist_deg = bist.get("degisim", 0.0)
            altin_fiyat = f"{int(gram_altin.get('fiyat', 0.0)):,} ₺".replace(",", ".") if gram_altin.get("fiyat") else "2.850 ₺"
            altin_deg = gram_altin.get("degisim", 0.0)

            piyasa_ozeti = {
                "Dolar/TL": (dolar_fiyat, dolar_deg),
                "BİST 100": (bist_fiyat, bist_deg),
                "Gram Altın": (altin_fiyat, altin_deg),
            }
        except Exception as e:
            log.warning("Piyasa reaksiyonu çekilemedi: %s", e)
            piyasa_ozeti = {}

    if piyasa_ozeti:
        draw.text((70, y_imlec), "› ANLIK PİYASA REAKSİYONU", font=_font(15, 800.0), fill=RENK_CYAN)
        y_imlec += 28

        kart_w = (genislik - 120 - 30) / 3.0
        for idx, (ad, (fiyat, deg)) in enumerate(piyasa_ozeti.items()):
            kx = 60 + idx * (kart_w + 15)
            draw.rounded_rectangle(
                [kx, y_imlec, kx + kart_w, y_imlec + 90],
                radius=14,
                fill=RENK_KART_CONTAINER,
                outline=RENK_KART_BORDER,
                width=1,
            )
            # İsim
            draw.text((kx + 14, y_imlec + 14), ad, font=_font(15, 700.0), fill=RENK_GRI_METIN)
            # Fiyat
            draw.text((kx + 14, y_imlec + 46), str(fiyat), font=_font(21, 800.0), fill=RENK_BEYAZ)
            # Değişim Yüzdesi Rozeti
            ok = "▲" if deg >= 0 else "▼"
            deg_renk = RENK_YESIL if deg >= 0 else RENK_KIRMIZI
            deg_str = f"{ok} %{abs(deg):.2f}"
            draw.text((kx + kart_w - 90, y_imlec + 49), deg_str, font=_font(14, 800.0), fill=deg_renk)

        y_imlec += 115

    # 5. Spot Açıklama Kutusu
    if spot_metin:
        spot_box_h = 160 if not dikey_story else 220
        draw.rounded_rectangle(
            [60, y_imlec, genislik - 60, y_imlec + spot_box_h],
            radius=16,
            fill=RENK_KART_CONTAINER,
            outline=RENK_KART_BORDER,
            width=1,
        )
        # Sol İnce Turkuaz Vurgu Çizgisi
        draw.rounded_rectangle([60, y_imlec, 66, y_imlec + spot_box_h], radius=3, fill=RENK_CYAN)

        draw.text((85, y_imlec + 18), "› KARAR METNİ & ANALİZ", font=_font(15, 800.0), fill=RENK_CYAN)

        # Metni satırlara böl
        f_spot = _font(18, 500.0)
        kelimeler = spot_metin.split()
        satirlar = []
        mevcut = ""
        for w in kelimeler:
            test = (mevcut + " " + w).strip()
            if f_spot.getbbox(test)[2] < (genislik - 190):
                mevcut = test
            else:
                satirlar.append(mevcut)
                mevcut = w
        if mevcut:
            satirlar.append(mevcut)

        spot_y = y_imlec + 50
        for s in satirlar[:4]:
            draw.text((85, spot_y), s, font=f_spot, fill=RENK_BEYAZ)
            spot_y += 28

    # 6. Alt Bilgi (Footer)
    footer_y = yukseklik - 60 if not dikey_story else yukseklik - 90
    draw.text(
        (70, footer_y),
        f"dailybrief.co  ·  Kaynak: {kaynak}",
        font=_font(16, 600.0),
        fill=RENK_GRI_METIN,
    )
    draw.text(
        (genislik - 240, footer_y),
        "Daily Brief Finans",
        font=_font(16, 700.0),
        fill=RENK_CYAN,
    )

    img.save(cikti_yolu, "JPEG", quality=95)
    log.info("Makro infografik kartı başarıyla üretildi: %s", cikti_yolu)
    return cikti_yolu
