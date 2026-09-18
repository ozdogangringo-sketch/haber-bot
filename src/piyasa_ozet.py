"""
piyasa_ozet.py — Canlı Piyasa Bülteni "Günün Ekonomi Gündemi" Çoklu Özet Kartı Motoru.

Piyasa bülteninin 3. (ve gerekirse 4.) slaytı olarak günün öne çıkan
ekonomi gelişmelerini lüks Derin Petrol ve Siber Turkuaz temasıyla,
sayfa başına azami 3 haber içeren infografik kartlar halinde üretir.

Tasarım Standartları:
  * %100 Native 1080x1920 tuval, Y_OFFSET = 285px (4:5 güvenli alan).
  * 1-3 haber: 1 sayfa (Bültenin 3. slaytı).
  * 4-6 haber: 2 sayfa (Bültenin 3. ve 4. slaytları).
  * Sayfa başına 3 farklı tematik accent çentiği (Kehribar, Siber Turkuaz, Zümrüt Yeşili).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

log = logging.getLogger(__name__)

KOK = Path(__file__).resolve().parent.parent
FONT_YOLU = KOK / "assets" / "fonts" / "Inter-Variable.ttf"
LOGO_YOLU = KOK / "assets" / "logo_circular.png"
CIKTI_KLASORU = KOK / "data" / "output"

GENISLIK = 1080
YUKSEKLIK = 1920
Y_OFFSET = 285  # (1920 - 1350) // 2

# Renk Paleti (piyasa_kart ve piyasa_tablo ile %100 uyumlu)
RENK_ARKA_UST = (4, 24, 28)
RENK_ARKA_ORTA = (8, 38, 44)
RENK_ARKA_ALT = (3, 16, 20)
RENK_GLOW = (6, 182, 212, 45)

RENK_CYAN = (6, 182, 212)
RENK_AMBER = (245, 158, 11)
RENK_EMERALD = (16, 185, 129)
RENK_BASLIK_KOYU = (255, 255, 255)
RENK_GRI_METIN = (148, 163, 184)
RENK_GRI_ACIK = (203, 213, 225)

CENTIK_RENKLERI = [RENK_AMBER, RENK_CYAN, RENK_EMERALD]


def _font(punto: int, agirlik: float = 600.0) -> ImageFont.FreeTypeFont:
    """Inter Variable fontundan istenen punto ve ağırlıkta font üretir."""
    f = ImageFont.truetype(str(FONT_YOLU), punto)
    try:
        f.set_variation_by_axes([20.0, agirlik])
    except Exception:
        pass
    return f


def _arka_plan_ciz(w: int = GENISLIK, h: int = YUKSEKLIK) -> Image.Image:
    """Derin petrol ve turkuaz gradyan ile lüks ambiyans üretir."""
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)

    for y in range(h):
        oran = y / float(h)
        if oran < 0.5:
            t = oran * 2.0
            r = int(RENK_ARKA_UST[0] * (1 - t) + RENK_ARKA_ORTA[0] * t)
            g = int(RENK_ARKA_UST[1] * (1 - t) + RENK_ARKA_ORTA[1] * t)
            b = int(RENK_ARKA_UST[2] * (1 - t) + RENK_ARKA_ORTA[2] * t)
        else:
            t = (oran - 0.5) * 2.0
            r = int(RENK_ARKA_ORTA[0] * (1 - t) + RENK_ARKA_ALT[0] * t)
            g = int(RENK_ARKA_ORTA[1] * (1 - t) + RENK_ARKA_ALT[1] * t)
            b = int(RENK_ARKA_ORTA[2] * (1 - t) + RENK_ARKA_ALT[2] * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))

    y_off = Y_OFFSET
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.ellipse([(-120, y_off - 120), (600, y_off + 480)], fill=RENK_GLOW)
    gdraw.ellipse([(620, y_off + 680), (1250, y_off + 1450)], fill=(6, 182, 212, 30))
    glow = glow.filter(ImageFilter.GaussianBlur(140))

    return Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")


def _metin_sar(metin: str, font: ImageFont.FreeTypeFont, max_w: int, draw: ImageDraw.ImageDraw) -> list[str]:
    """Metni belirtilen piksel genişliğine göre kelime bölmeden satırlara ayırır."""
    kelimeler = (metin or "").replace("**", "").split()
    satirlar = []
    mevcut = ""
    for k in kelimeler:
        deneme = f"{mevcut} {k}".strip()
        if draw.textlength(deneme, font=font) <= max_w:
            mevcut = deneme
        else:
            if mevcut:
                satirlar.append(mevcut)
            mevcut = k
    if mevcut:
        satirlar.append(mevcut)
    return satirlar


def _etiket_belirle(h: dict) -> str:
    """Haberin başlığı ve konusuna göre kısa kategori etiketi üretir."""
    baslik = (h.get("ig_baslik") or h.get("baslik_orj") or "").lower()
    if any(k in baslik for k in ("spk", "fon", "hisse", "bist", "borsa", "temettü", "halka arz")):
        return "SERMAYE PİYASASI // BORSA & FON"
    elif any(k in baslik for k in ("tcmb", "fed", "ecb", "boj", "faiz", "merkez bankası", "enflasyon")):
        return "MERKEZ BANKALARI // FAİZ & ENFLASYON"
    elif any(k in baslik for k in ("dolar", "euro", "altın", "emtia", "petrol", "ons")):
        return "EMTİA & PİYASALAR // DÖVİZ"
    elif any(k in baslik for k in ("ihracat", "ithalat", "cari", "büyüme", "istihdam", "sanayi")):
        return "MAKRO EKONOMİ // TİCARET & BÜYÜME"
    elif any(k in baslik for k in ("abd", "avrupa", "çin", "küresel", "asya", "wall street")):
        return "KÜRESEL PİYASALAR // DIŞ TİCARET"
    return "EKONOMİ GÜNDEMİ // GELİŞME"


def _ciz_ozet_sayfasi(
    img: Image.Image,
    haberler: list[dict],
    sayfa_no: int = 1,
    toplam_sayfa: int = 1,
    mod: str | None = None,
    y_offset: int = Y_OFFSET,
) -> None:
    """
    1080x1350 güvenli bölgesine en fazla 3 haber içeren özet sayfasını çizer.
    """
    draw = ImageDraw.Draw(img)

    f_etiket = _font(19, 800.0)
    f_baslik = _font(44, 900.0)
    f_alt_baslik = _font(21, 500.0)
    f_kart_etiket = _font(18, 800.0)
    f_kart_kaynak = _font(17, 700.0)
    f_kart_baslik = _font(36, 850.0)
    f_kart_ozet = _font(22, 500.0)

    # --- 1. HEADER (ÜST ALAN) ---
    logo_boyut = 120
    logo_x = 45
    logo_y = y_offset + 35

    if LOGO_YOLU.exists():
        try:
            golge = Image.new("RGBA", (img.width, img.height), (0, 0, 0, 0))
            ImageDraw.Draw(golge).ellipse(
                [logo_x - 4, logo_y - 2, logo_x + logo_boyut + 6, logo_y + logo_boyut + 8],
                fill=(0, 0, 0, 140),
            )
            golge = golge.filter(ImageFilter.GaussianBlur(14))
            img.paste(Image.alpha_composite(img.convert("RGBA"), golge).convert("RGB"), (0, 0))

            logo = Image.open(LOGO_YOLU).convert("RGBA")
            logo = logo.resize((logo_boyut, logo_boyut), Image.Resampling.LANCZOS)
            img.paste(logo, (logo_x, logo_y), mask=logo)
        except Exception as e:
            log.warning("Özet kartı logo yüklenemedi: %s", e)

    draw = ImageDraw.Draw(img)

    header_x = 182
    rozet_txt = "DAILYBRIEF · EKONOMİ GÜNDEMİ"
    rw = draw.textlength(rozet_txt, font=f_etiket)
    draw.rounded_rectangle(
        [(header_x, y_offset + 38), (header_x + rw + 24, y_offset + 72)],
        radius=8,
        fill=(18, 62, 72),
        outline=RENK_CYAN,
        width=2,
    )
    draw.text((header_x + 12, y_offset + 43), rozet_txt, font=f_etiket, fill=RENK_CYAN)

    # Sağ üst tarih & sayfa rozeti
    if mod in ("acilis", "kapanis"):
        aksam_mi = (mod == "kapanis")
    else:
        aksam_mi = datetime.now(timezone.utc).hour >= 15

    oturum_adi = "Kapanış" if aksam_mi else "Açılış"
    simdi = datetime.now(timezone.utc)
    sayfa_ek = f" ({sayfa_no}/{toplam_sayfa})" if toplam_sayfa > 1 else ""
    tarih_txt = f"{simdi.strftime('%d.%m.%Y')}  ·  {oturum_adi} Özeti{sayfa_ek}"
    tw = draw.textlength(tarih_txt, font=_font(18, 700.0))
    sag_kenar = GENISLIK - 45
    draw.rounded_rectangle(
        [(sag_kenar - tw - 24, y_offset + 38), (sag_kenar, y_offset + 72)],
        radius=8,
        fill=(12, 36, 44),
        outline=(28, 85, 96),
        width=1,
    )
    draw.text((sag_kenar - tw - 12, y_offset + 44), tarih_txt, font=_font(18, 700.0), fill=RENK_GRI_METIN)

    baslik_ana = "Günü Kapatırken" if aksam_mi else "Günün Öne Çıkanları"
    baslik_alt = (
        "Piyasalara yön veren gün içi kritik gelişmeler ve kapanış başlıkları"
        if aksam_mi
        else "Güne başlarken piyasalara yön veren kritik gelişmeler ve ilk rakamlar"
    )
    draw.text((header_x, y_offset + 82), baslik_ana, font=f_baslik, fill=RENK_BASLIK_KOYU)
    draw.text((header_x, y_offset + 134), baslik_alt, font=f_alt_baslik, fill=RENK_GRI_METIN)

    # --- 2. GÖVDE: EN FAZLA 3 HABER KARTI ---
    kart_x = 45
    kart_w = GENISLIK - 90
    kart_y_baslangic = y_offset + 185
    kart_h = 320
    kart_bosluk = 28

    overlay = Image.new("RGBA", (GENISLIK, YUKSEKLIK), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)

    adet = min(len(haberler), 3)
    for i in range(adet):
        ky = kart_y_baslangic + i * (kart_h + kart_bosluk)
        c_renk = CENTIK_RENKLERI[i % len(CENTIK_RENKLERI)]

        # Kart arkaplan kutusu (Soft glassmorphism)
        odraw.rounded_rectangle(
            [(kart_x, ky), (kart_x + kart_w, ky + kart_h)],
            radius=18,
            fill=(8, 30, 38, 215),
            outline=(24, 78, 92, 230),
            width=2,
        )

        # Sol accent çentik
        notch_w = 6
        notch_margin = 18
        odraw.rounded_rectangle(
            [(kart_x + notch_margin, ky + 24), (kart_x + notch_margin + notch_w, ky + kart_h - 24)],
            radius=3,
            fill=c_renk,
        )

    img.paste(Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB"), (0, 0))
    draw = ImageDraw.Draw(img)

    for i in range(adet):
        h = haberler[i]
        ky = kart_y_baslangic + i * (kart_h + kart_bosluk)
        c_renk = CENTIK_RENKLERI[i % len(CENTIK_RENKLERI)]
        icerik_x = kart_x + 44
        max_metin_w = kart_w - 75

        # 1. Kategori etiketi & Kaynak/Saat
        kat_etiket = _etiket_belirle(h)
        draw.text((icerik_x, ky + 26), kat_etiket, font=f_kart_etiket, fill=c_renk)

        kaynak_adi = (h.get("kaynak") or "PİYASA GÜNDEMİ").upper()
        saat_str = ""
        yt = h.get("yayin_tarihi")
        if yt:
            try:
                dt = datetime.fromisoformat(str(yt).replace("Z", "+00:00"))
                saat_str = f"  ·  {dt.strftime('%H:%M')}"
            except Exception:
                pass
        kaynak_bilgi = f"{kaynak_adi}{saat_str}"
        kw = draw.textlength(kaynak_bilgi, font=f_kart_kaynak)
        draw.text((kart_x + kart_w - kw - 24, ky + 26), kaynak_bilgi, font=f_kart_kaynak, fill=RENK_GRI_METIN)

        # 2. Başlık
        baslik_ham = h.get("ig_baslik") or h.get("baslik_orj") or ""
        baslik_satirlari = _metin_sar(baslik_ham, f_kart_baslik, max_metin_w, draw)[:2]
        if len(baslik_satirlari) == 1:
            by = ky + 68
        else:
            by = ky + 58
        for b_satir in baslik_satirlari:
            draw.text((icerik_x, by), b_satir, font=f_kart_baslik, fill=RENK_BASLIK_KOYU)
            by += 45

        # 3. İnce ara ayırıcı çizgi
        ay = ky + 154
        draw.line([(icerik_x, ay), (kart_x + kart_w - 24, ay)], fill=(18, 56, 68), width=1)

        # 4. Özet
        ozet_ham = h.get("slayt_ozet") or h.get("ozet_orj") or ""
        if len(ozet_ham) < 30 and h.get("detay_metni"):
            ozet_ham = str(h["detay_metni"]).split("\n\n")[0]
        ozet_satirlari = _metin_sar(ozet_ham, f_kart_ozet, max_metin_w, draw)[:3]
        oy = ay + 14
        for o_satir in ozet_satirlari:
            draw.text((icerik_x, oy), o_satir, font=f_kart_ozet, fill=RENK_GRI_ACIK)
            oy += 32

    # --- 3. FOOTER (ALT BİLGİ ALANI) ---
    footer_y = y_offset + 1350 - 80
    draw.line([(45, footer_y), (GENISLIK - 45, footer_y)], fill=(18, 62, 72), width=1)

    tav_txt = "Yatırım tavsiyesi değildir. Veriler resmi haber ajansları ve kurumlardan derlenmiştir."
    draw.text((45, footer_y + 16), tav_txt, font=_font(16, 500.0), fill=RENK_GRI_METIN)

    marka_txt = "dailybrief.co"
    mw = draw.textlength(marka_txt, font=_font(18, 800.0))
    draw.text((GENISLIK - 45 - mw, footer_y + 14), marka_txt, font=_font(18, 800.0), fill=RENK_CYAN)


def ekonomi_ozet_sayfalari_uret(
    haberler: list[dict],
    mod: str | None = None,
    y_offset: int = Y_OFFSET,
) -> list[Path]:
    """
    Verilen ekonomi haberlerini 3'erli gruplayarak 1080x1920 (4:5 güvenli alanlı)
    özet slaytlarına dönüştürür.

    * 1 - 3 haber -> 1 sayfa
    * 4 - 6 haber -> 2 sayfa

    Döner: Üretilen JPEG dosyalarının Path listesi.
    """
    if not haberler:
        return []

    CIKTI_KLASORU.mkdir(parents=True, exist_ok=True)
    simdi = datetime.now(timezone.utc)
    tarih_str = simdi.strftime("%Y%m%d")

    # En fazla 6 haber (azami 2 sayfa)
    secilen = haberler[:6]
    sayfa_gruplari = [secilen[i:i + 3] for i in range(0, len(secilen), 3)]
    toplam_sayfa = len(sayfa_gruplari)

    uretilen_yollar: list[Path] = []

    for idx, grup in enumerate(sayfa_gruplari, start=1):
        img = _arka_plan_ciz(GENISLIK, YUKSEKLIK)
        _ciz_ozet_sayfasi(
            img,
            haberler=grup,
            sayfa_no=idx,
            toplam_sayfa=toplam_sayfa,
            mod=mod,
            y_offset=y_offset,
        )
        ek = f"_{idx}" if toplam_sayfa > 1 else ""
        mod_ek = f"_{mod}" if mod else ""
        dosya_adi = f"story_ekonomi_ozet_{tarih_str}{mod_ek}{ek}.jpg"
        cikti_yolu = CIKTI_KLASORU / dosya_adi
        img.save(cikti_yolu, "JPEG", quality=95, optimize=True)
        log.info("Günün Ekonomi Özeti sayfası %d/%d üretildi: %s", idx, toplam_sayfa, cikti_yolu)
        uretilen_yollar.append(cikti_yolu)

    return uretilen_yollar
