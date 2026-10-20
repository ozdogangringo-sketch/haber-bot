"""
spor_kapak.py — Spor maçları ve kadro duyuruları için "Armalı Maç Günü Kapağı (Matchday Cover)" şablonu.

1080x1920 dikey tuvalde (merkezi 4:5 güvenli alanında, STORY_GUVENLI_PAY = 330):
  - Canlı ve enerjik stadyum projektörleri ve zümrüt çim gradyanı
  - Merkezde iki kulübün 3D gölgeli resmi şeffaf armaları (215x215 px)
  - Ortada parıltılı "VS" ve maç saati kapsülü
  - Armaların altında otoriter takım isimleri ve teknik direktörler
  - Stadyum, hakem ve yayıncı meta kapsülü
  - Altta dinamik buzlu cam manşet kartı (Başlık + Spot + 3 Kilit Maç Hikayesi + Kaydırma Çağrısı)
  - En altta Daily Brief 3D logosu, sağa kaydırma oku (→) ve kaynak/sosyal ikonlar
"""

from __future__ import annotations

import logging
import re
from PIL import Image, ImageDraw, ImageFilter

from src import make_image, fetch_kulup_logo
from src.sablonlar.ortak import ust_ve_alt_bar_bas, metin_kutuya_sar

log = logging.getLogger(__name__)


def stadyum_zemini_olustur(genislik: int, yukseklik: int) -> Image.Image:
    """
    Canlı, derinlikli ve ışık huzmeli stadyum çim zeminini oluşturur.
    Kasvetli/iç karartıcı siyah yerine zengin zümrüt petrol ve projektör ışıkları kullanır.
    """
    zemin = Image.new("RGB", (genislik, yukseklik), (5, 24, 20))
    z_draw = ImageDraw.Draw(zemin)

    for y_idx in range(yukseklik):
        oran = y_idx / yukseklik
        if oran < 0.5:
            r = int(6 + (14 - 6) * (oran / 0.5))
            g = int(26 + (52 - 26) * (oran / 0.5))
            b = int(22 + (42 - 22) * (oran / 0.5))
        else:
            local_oran = (oran - 0.5) / 0.5
            r = int(14 - (14 - 8) * local_oran)
            g = int(52 - (52 - 28) * local_oran)
            b = int(42 - (42 - 24) * local_oran)
        z_draw.line([(0, y_idx), (genislik, y_idx)], fill=(r, g, b))

    # Projektör huzmeleri (Sol: Ev sahibi kehribar, Sağ: Deplasman siber mavi)
    isik = Image.new("RGBA", (genislik, yukseklik), (0, 0, 0, 0))
    i_draw = ImageDraw.Draw(isik)
    i_draw.polygon([(0, 0), (genislik // 2, 0), (genislik // 3, 900), (0, 600)], fill=(245, 158, 11, 28))
    i_draw.polygon([(genislik, 0), (genislik // 2, 0), (2 * genislik // 3, 900), (genislik, 600)], fill=(6, 182, 212, 28))
    i_draw.ellipse([genislik // 2 - 380, 500, genislik // 2 + 380, 1400], fill=(16, 185, 129, 45))

    isik_blurlu = isik.filter(ImageFilter.GaussianBlur(80))
    zemin = Image.alpha_composite(zemin.convert("RGBA"), isik_blurlu).convert("RGB")

    # İnce Tebeşir Saha Çizgileri
    cizgiler = Image.new("RGBA", (genislik, yukseklik), (0, 0, 0, 0))
    c_draw = ImageDraw.Draw(cizgiler)
    orta_y = 1000
    c_draw.line([(64, orta_y), (genislik - 64, orta_y)], fill=(255, 255, 255, 18), width=2)
    c_draw.ellipse([genislik // 2 - 130, orta_y - 130, genislik // 2 + 130, orta_y + 130], outline=(255, 255, 255, 18), width=2)
    c_draw.ellipse([genislik // 2 - 8, orta_y - 8, genislik // 2 + 8, orta_y + 8], fill=(255, 255, 255, 25))

    return Image.alpha_composite(zemin.convert("RGBA"), cizgiler).convert("RGB")


def spor_kapak_slayti_ciz(
    haber: dict,
    veri: dict,
    ayarlar: dict,
    kaynak: str,
    arkaplan: Image.Image | None = None,
    arsiv_ibaresi: bool = False,
    sayfa: int = 1,
    toplam_sayfa: int = 2,
) -> Image.Image:
    """
    Kadro ve maç haberleri için kulüp armalı 1. kapak slaytını (1080x1920) üretir.
    """
    genislik = make_image.STORY_GENISLIK
    yukseklik = make_image.STORY_YUKSEKLIK
    kenar = 64
    dikey_kenar = make_image.STORY_GUVENLI_PAY  # 330
    y_ust = dikey_kenar + 120
    alt_bilgi_y = yukseklik - dikey_kenar - 34
    y_alt = alt_bilgi_y - 20

    ev_ad = (veri.get("ev_sahibi") or veri.get("takim_1") or "EV SAHİBİ").strip()
    dep_ad = (veri.get("deplasman") or veri.get("takim_2") or "DEPLASMAN").strip()
    turnuva = (veri.get("turnuva") or veri.get("lig") or "KARŞILAŞMA").strip().upper()
    skor_saat = (veri.get("skor_veya_saat") or veri.get("saat") or "20:00").strip()
    mac_bilgi = (veri.get("mac_bilgisi") or veri.get("stat_hakem") or veri.get("stadyum_saat") or "").strip()
    ev_td = veri.get("ev_td", "").strip()
    dep_td = veri.get("dep_td", "").strip()

    # 1. TEMEL TUVAL — Elektrikli Stadyum Gece Atmosferi
    gorsel = stadyum_zemini_olustur(genislik, yukseklik)
    ciz = ImageDraw.Draw(gorsel, "RGBA")

    y = y_ust + 10

    # =========================================================================
    # 1. ÜST TURNUVA / LİG ROZETİ
    # =========================================================================
    f_lig = make_image._font(18, make_image.EKSEN_BASLIK)
    lig_w = ciz.textlength(turnuva, font=f_lig)
    ciz.rounded_rectangle(
        [(genislik - lig_w) / 2 - 22, y, (genislik + lig_w) / 2 + 22, y + 38],
        radius=9,
        fill=(16, 185, 129, 40),
        outline=(16, 185, 129, 140),
        width=1,
    )
    ciz.text(((genislik - lig_w) / 2, y + 9), turnuva, font=f_lig, fill=(167, 243, 208))

    y += 62

    # =========================================================================
    # 2. MERKEZ SAHNE: KULÜP ARMALARI VE "VS" KAPSÜLÜ
    # =========================================================================
    arma_boyutu = 215
    sol_arma_x = kenar + 55
    sag_arma_x = genislik - kenar - 55 - arma_boyutu
    arma_y = y + 14

    # Armaları çek
    logo_ev = fetch_kulup_logo.kulup_logosu_al(ev_ad, boyut=arma_boyutu)
    logo_dep = fetch_kulup_logo.kulup_logosu_al(dep_ad, boyut=arma_boyutu)

    # Ev Sahibi Arması ve 3D Gölgesi
    if logo_ev:
        golge_ev = Image.new("RGBA", gorsel.size, (0, 0, 0, 0))
        g_draw = ImageDraw.Draw(golge_ev)
        g_draw.ellipse([sol_arma_x - 14, arma_y + 14, sol_arma_x + arma_boyutu + 14, arma_y + arma_boyutu + 38], fill=(0, 0, 0, 180))
        gorsel = Image.alpha_composite(gorsel.convert("RGBA"), golge_ev.filter(ImageFilter.GaussianBlur(18))).convert("RGB")
        gorsel.paste(logo_ev, (sol_arma_x, arma_y), mask=logo_ev)
    else:
        ciz.ellipse([sol_arma_x, arma_y, sol_arma_x + arma_boyutu, arma_y + arma_boyutu], fill=(245, 158, 11, 40), outline=(245, 158, 11), width=2)
        f_mono = make_image._font(42, make_image.EKSEN_BASLIK)
        ciz.text((sol_arma_x + 60, arma_y + 75), ev_ad[:3].upper(), font=f_mono, fill=(255, 255, 255))

    # Deplasman Arması ve 3D Gölgesi
    if logo_dep:
        golge_dep = Image.new("RGBA", gorsel.size, (0, 0, 0, 0))
        g_draw = ImageDraw.Draw(golge_dep)
        g_draw.ellipse([sag_arma_x - 14, arma_y + 14, sag_arma_x + arma_boyutu + 14, arma_y + arma_boyutu + 38], fill=(0, 0, 0, 180))
        gorsel = Image.alpha_composite(gorsel.convert("RGBA"), golge_dep.filter(ImageFilter.GaussianBlur(18))).convert("RGB")
        gorsel.paste(logo_dep, (sag_arma_x, arma_y), mask=logo_dep)
    else:
        ciz.ellipse([sag_arma_x, arma_y, sag_arma_x + arma_boyutu, arma_y + arma_boyutu], fill=(14, 165, 233, 40), outline=(14, 165, 233), width=2)
        f_mono = make_image._font(42, make_image.EKSEN_BASLIK)
        ciz.text((sag_arma_x + 60, arma_y + 75), dep_ad[:3].upper(), font=f_mono, fill=(255, 255, 255))

    ciz = ImageDraw.Draw(gorsel, "RGBA")

    # Ortadaki "VS" ve Maç Saati Kapsülü
    vs_y_merkez = arma_y + arma_boyutu // 2
    f_vs_buyuk = make_image._font(34, make_image.EKSEN_BASLIK)
    f_vs_saat = make_image._font(20, make_image.EKSEN_BASLIK)

    vs_w = 126
    vs_h = 106
    vs_x1 = (genislik - vs_w) // 2
    vs_y1 = vs_y_merkez - vs_h // 2
    ciz.rounded_rectangle([vs_x1, vs_y1, vs_x1 + vs_w, vs_y1 + vs_h], radius=22, fill=(8, 30, 26, 240), outline=(16, 185, 129, 150), width=2)
    ciz.text(((genislik - ciz.textlength("VS", font=f_vs_buyuk)) / 2, vs_y1 + 15), "VS", font=f_vs_buyuk, fill=(255, 255, 255))
    saat_metin_w = ciz.textlength(skor_saat, font=f_vs_saat)
    ciz.text(((genislik - saat_metin_w) / 2, vs_y1 + 61), skor_saat, font=f_vs_saat, fill=(52, 211, 153))

    # Armaların Altındaki Takım İsimleri & Teknik Direktörler
    f_takim_kapak = make_image._font(30, make_image.EKSEN_BASLIK)
    f_td_kapak = make_image._font(18, make_image.EKSEN_KUCUK)
    isim_y = arma_y + arma_boyutu + 18

    # Ev Sahibi Adı & TD
    ev_ad_b = make_image._buyuk_harf(ev_ad)
    ev_w = ciz.textlength(ev_ad_b, font=f_takim_kapak)
    ev_x_merkez = sol_arma_x + arma_boyutu // 2
    ciz.text((ev_x_merkez - ev_w / 2, isim_y), ev_ad_b, font=f_takim_kapak, fill=(245, 158, 11))
    if ev_td:
        ev_td_txt = f"TD: {ev_td}"
        ev_td_w = ciz.textlength(ev_td_txt, font=f_td_kapak)
        ciz.text((ev_x_merkez - ev_td_w / 2, isim_y + 36), ev_td_txt, font=f_td_kapak, fill=(203, 213, 225))

    # Deplasman Adı & TD
    dep_ad_b = make_image._buyuk_harf(dep_ad)
    dep_w = ciz.textlength(dep_ad_b, font=f_takim_kapak)
    dep_x_merkez = sag_arma_x + arma_boyutu // 2
    ciz.text((dep_x_merkez - dep_w / 2, isim_y), dep_ad_b, font=f_takim_kapak, fill=(56, 189, 248))
    if dep_td:
        dep_td_txt = f"TD: {dep_td}"
        dep_td_w = ciz.textlength(dep_td_txt, font=f_td_kapak)
        ciz.text((dep_x_merkez - dep_td_w / 2, isim_y + 36), dep_td_txt, font=f_td_kapak, fill=(203, 213, 225))

    y = isim_y + (64 if (ev_td or dep_td) else 44)

    # =========================================================================
    # 3. MAÇ META KAPSÜLÜ (STADYUM • HAKEM • YAYINCI)
    # =========================================================================
    if mac_bilgi:
        f_meta = make_image._font(17, make_image.EKSEN_BASLIK)
        meta_w = ciz.textlength(mac_bilgi, font=f_meta)
        ciz.rounded_rectangle(
            [(genislik - meta_w) / 2 - 20, y, (genislik + meta_w) / 2 + 20, y + 36],
            radius=18,
            fill=(10, 32, 28, 220),
            outline=(255, 255, 255, 24),
            width=1,
        )
        ciz.text(((genislik - meta_w) / 2, y + 8), mac_bilgi, font=f_meta, fill=(167, 243, 208))
        y += 48

    y += 10

    # =========================================================================
    # 4. ALT MANŞET & KİLİT MAÇ HİKAYELERİ KARTI (DİNAMİK BUZLU CAM)
    # =========================================================================
    kart_w = genislik - 2 * kenar
    kart_baslangic_y = y

    # Başlık
    baslik = (haber.get("ig_baslik") or haber.get("baslik_orj") or "İLK 11'LER BELLİ OLDU").strip()
    f_bas = make_image._font(32, make_image.EKSEN_BASLIK)
    baslik_satirlari = metin_kutuya_sar(ciz, make_image._buyuk_harf(baslik), f_bas, kart_w - 48, maks_satir=2)

    # Spot
    spot = (haber.get("spot") or haber.get("ozet") or f"{ev_ad} ve {dep_ad} maçında ilk 11'ler ve kulübeler resmi esame listesiyle netleşti.").strip()
    f_spot = make_image._font(21, make_image.EKSEN_OZET)
    spot_satirlari = metin_kutuya_sar(ciz, spot, f_spot, kart_w - 48, maks_satir=2)

    # Kilit Maddeler
    maddeler = veri.get("maddeler") or []
    if not maddeler:
        maddeler = [
            ("ZİRVE YARIŞI", f"İki ezeli rakip namağlup serilerini korumak ve zirveye oturmak için sahada."),
            ("GOLCÜLERİN DÜELLOSU", f"Hücum hatlarının yıldızları derbide gol arayacak; tarihi randevu başladı."),
            ("KULÜBE KOZLARI", f"Geniş yedek kulübeleriyle iki teknik adamdan kritik taktik hamleler bekleniyor."),
        ]

    m_kutu_h = 86
    # Dinamik kart yüksekliği (Boşluk bırakmayan oturum)
    kart_h = (
        26 + len(baslik_satirlari) * 40
        + 8 + len(spot_satirlari) * 30
        + 14 + 18
        + len(maddeler[:3]) * (m_kutu_h + 12)
        + 14 + 46 + 20
    )

    if kart_baslangic_y + kart_h > y_alt:
        kart_h = y_alt - kart_baslangic_y

    ciz.rounded_rectangle([kenar, kart_baslangic_y, genislik - kenar, kart_baslangic_y + kart_h], radius=20, fill=(9, 28, 25, 235), outline=(52, 211, 153, 60), width=1)
    ciz.rounded_rectangle([kenar + 20, kart_baslangic_y + 1, genislik - kenar - 20, kart_baslangic_y + 3], radius=2, fill=(16, 185, 129, 140))

    by = kart_baslangic_y + 26
    for bs in baslik_satirlari:
        ciz.text((kenar + 24, by), bs, font=f_bas, fill=(255, 255, 255))
        by += 40

    by += 8
    for ss in spot_satirlari:
        ciz.text((kenar + 24, by), ss, font=f_spot, fill=(203, 213, 225))
        by += 30

    by += 12
    ciz.line([kenar + 24, by, genislik - kenar - 24, by], fill=(255, 255, 255, 20), width=1)
    by += 16

    f_m_bas = make_image._font(18, make_image.EKSEN_BASLIK)
    f_m_txt = make_image._font(19, make_image.EKSEN_OZET)

    for i, m_item in enumerate(maddeler[:3]):
        if isinstance(m_item, (tuple, list)):
            m_etiket, m_aciklama = m_item[0], m_item[1]
        else:
            m_etiket, m_aciklama = f"MADDE {i+1}", str(m_item)

        ciz.rounded_rectangle([kenar + 20, by, genislik - kenar - 20, by + m_kutu_h], radius=10, fill=(12, 38, 34, 180), outline=(255, 255, 255, 14), width=1)
        accent_col = (245, 158, 11) if i == 0 else ((6, 182, 212) if i == 1 else (16, 185, 129))
        ciz.rounded_rectangle([kenar + 20, by, kenar + 25, by + m_kutu_h], radius=2, fill=accent_col)

        ciz.text((kenar + 38, by + 10), m_etiket.upper(), font=f_m_bas, fill=accent_col)

        m_temiz = re.sub(r"[\u2600-\u27bf\U0001f300-\U0001f9ff⚠️📌🔴🚨★⭐⚽🔥⚡🎯📋]", "", m_aciklama).strip()
        acik_satirlar = metin_kutuya_sar(ciz, m_temiz, f_m_txt, kart_w - 76, maks_satir=2)
        ty = by + 34
        for asat in acik_satirlar:
            ciz.text((kenar + 38, ty), asat, font=f_m_txt, fill=(241, 245, 249))
            ty += 24

        by += m_kutu_h + 12

    # CTA Aksiyon Şeridi (Call-to-Action)
    by += 4
    cta_h = 44
    ciz.rounded_rectangle([kenar + 20, by, genislik - kenar - 20, by + cta_h], radius=10, fill=(16, 185, 129, 35), outline=(16, 185, 129, 130), width=1)
    f_cta = make_image._font(17, make_image.EKSEN_BASLIK)
    cta_txt = "KADROLAR VE SAHA İÇİ DİZİLİŞ İÇİN KAYDIRIN  →"
    cta_w = ciz.textlength(cta_txt, font=f_cta)
    ciz.text(((genislik - cta_w) / 2, by + 12), cta_txt, font=f_cta, fill=(110, 231, 183))

    return ust_ve_alt_bar_bas(
        gorsel,
        ayarlar=ayarlar,
        kaynak=kaynak,
        rozet_metni="MAÇ GÜNÜ",
        rozet_renk=(16, 185, 129),
        sayfa=sayfa,
        toplam_sayfa=toplam_sayfa,
        arsiv_ibaresi=arsiv_ibaresi,
    )
