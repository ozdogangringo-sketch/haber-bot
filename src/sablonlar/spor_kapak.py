"""
spor_kapak.py — Spor maçları ve kadro duyuruları için "Armalı Maç Günü Kapağı (Matchday Cover)" şablonu.

Daily Brief Standart Haber Formatı:
  - 1080x1920 dikey tuvalde (merkezi 4:5 güvenli alanında, STORY_GUVENLI_PAY = 330)
  - Arka planda derinlikli stadyum projektörleri ve canlı yeşil çim dokusu
  - Görsel alanında: İki kulübün resmi 3D gölgeli şeffaf armaları (210x210 px), "VS" ve maç saati kapsülü
  - Alt bölgede: Standart Daily Brief haber formatı (yumuşak dip karartma gradyanı, büyük otoriter manşet başlık ve editoryal spot)
  - Yapay kutucuk veya buton yok; %100 saf editoryal dergi/haber kapağı standardı.
"""

from __future__ import annotations

import logging
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
    Kadro ve maç duyuruları için Daily Brief standart haber formatında,
    yeşil çim üzerine 3D kulüp armalı kapak slaytı (1080x1920) üretir.
    """
    genislik = make_image.STORY_GENISLIK
    yukseklik = make_image.STORY_YUKSEKLIK
    kenar = 64
    dikey_kenar = make_image.STORY_GUVENLI_PAY  # 330
    alt_bilgi_y = yukseklik - dikey_kenar - 34

    ev_ad = (veri.get("ev_sahibi") or veri.get("takim_1") or "EV SAHİBİ").strip()
    dep_ad = (veri.get("deplasman") or veri.get("takim_2") or "DEPLASMAN").strip()
    turnuva = (veri.get("turnuva") or veri.get("lig") or "KARŞILAŞMA").strip().upper()
    skor_saat = (veri.get("skor_veya_saat") or veri.get("saat") or "20:00").strip()
    mac_bilgi = (veri.get("mac_bilgisi") or veri.get("stat_hakem") or veri.get("stadyum_saat") or "").strip()

    # 1. TEMEL TUVAL — Canlı Çim ve Projektör Zemin
    gorsel = stadyum_zemini_olustur(genislik, yukseklik)
    ciz = ImageDraw.Draw(gorsel, "RGBA")

    # =========================================================================
    # GÖRSEL ALANI: YEŞİL ÇİM ÜZERİNDE RESMİ 3D KULÜP ARMALARI & MAÇ MERKEZİ
    # =========================================================================
    # Safe area üst başlangıcı (Daily Brief logosu altına 20px nefes payı)
    y_logo_alani = dikey_kenar + 175  # = 505 px

    # 1. Turnuva / Lig Kapsülü
    f_lig = make_image._font(18, make_image.EKSEN_BASLIK)
    lig_w = ciz.textlength(turnuva, font=f_lig)
    ciz.rounded_rectangle(
        [(genislik - lig_w) / 2 - 22, y_logo_alani, (genislik + lig_w) / 2 + 22, y_logo_alani + 38],
        radius=19,
        fill=(10, 32, 28, 220),
        outline=(52, 211, 153, 90),
        width=1,
    )
    ciz.text(((genislik - lig_w) / 2, y_logo_alani + 9), turnuva, font=f_lig, fill=(167, 243, 208))

    # 2. Kulüp Armaları (210x210) & 3D Gölgeleri
    arma_boyutu = 210
    sol_arma_x = kenar + 60
    sag_arma_x = genislik - kenar - 60 - arma_boyutu
    arma_y = y_logo_alani + 56

    logo_ev = fetch_kulup_logo.kulup_logosu_al(ev_ad, boyut=arma_boyutu)
    logo_dep = fetch_kulup_logo.kulup_logosu_al(dep_ad, boyut=arma_boyutu)

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
    ciz.rounded_rectangle([vs_x1, vs_y1, vs_x1 + vs_w, vs_y1 + vs_h], radius=22, fill=(8, 30, 26, 240), outline=(52, 211, 153, 140), width=2)
    ciz.text(((genislik - ciz.textlength("VS", font=f_vs_buyuk)) / 2, vs_y1 + 15), "VS", font=f_vs_buyuk, fill=(255, 255, 255))
    saat_metin_w = ciz.textlength(skor_saat, font=f_vs_saat)
    ciz.text(((genislik - saat_metin_w) / 2, vs_y1 + 61), skor_saat, font=f_vs_saat, fill=(52, 211, 153))

    # Armaların Altındaki Takım İsimleri
    f_takim_kapak = make_image._font(30, make_image.EKSEN_BASLIK)
    isim_y = arma_y + arma_boyutu + 18

    ev_ad_b = make_image._buyuk_harf(ev_ad)
    ev_w = ciz.textlength(ev_ad_b, font=f_takim_kapak)
    ciz.text((sol_arma_x + (arma_boyutu - ev_w) / 2, isim_y), ev_ad_b, font=f_takim_kapak, fill=(245, 158, 11))

    dep_ad_b = make_image._buyuk_harf(dep_ad)
    dep_w = ciz.textlength(dep_ad_b, font=f_takim_kapak)
    ciz.text((sag_arma_x + (arma_boyutu - dep_w) / 2, isim_y), dep_ad_b, font=f_takim_kapak, fill=(56, 189, 248))

    # Stadyum & Hakem Kapsülü
    if mac_bilgi:
        f_meta = make_image._font(17, make_image.EKSEN_BASLIK)
        meta_w = ciz.textlength(mac_bilgi, font=f_meta)
        ciz.rounded_rectangle(
            [(genislik - meta_w) / 2 - 20, isim_y + 46, (genislik + meta_w) / 2 + 20, isim_y + 84],
            radius=18,
            fill=(10, 32, 28, 220),
            outline=(255, 255, 255, 24),
            width=1,
        )
        ciz.text(((genislik - meta_w) / 2, isim_y + 55), mac_bilgi, font=f_meta, fill=(167, 243, 208))

    # =========================================================================
    # DAILY BRIEF STANDART HABER FORMATI: DİP KARARTMA (VIGNETTE) + MANŞET & SPOT
    # =========================================================================
    perde = Image.new("RGBA", (genislik, yukseklik), (0, 0, 0, 0))
    perde_ciz = ImageDraw.Draw(perde)
    perde_baslangic = 980
    for py in range(perde_baslangic, yukseklik):
        oran = (py - perde_baslangic) / (yukseklik - perde_baslangic)
        alfa = int(255 * min(1.0, oran ** 1.3))
        perde_ciz.line([(0, py), (genislik, py)], fill=(4, 18, 16, alfa))

    gorsel = Image.alpha_composite(gorsel.convert("RGBA"), perde).convert("RGB")
    ciz = ImageDraw.Draw(gorsel, "RGBA")

    # Metin Yerleşimi (Daily Brief Standardı)
    baslik = (haber.get("ig_baslik") or haber.get("baslik_orj") or "İLK 11'LER BELLİ OLDU").strip()
    spot = (haber.get("spot") or haber.get("slayt_ozet") or haber.get("ozet") or "").strip()

    alan_w = genislik - 2 * kenar

    # Özet / Spot
    f_spot = make_image._font(24, make_image.EKSEN_OZET)
    spot_satirlari = metin_kutuya_sar(ciz, spot, f_spot, alan_w, maks_satir=3) if spot else []
    spot_satir_h = 34
    spot_h = len(spot_satirlari) * spot_satir_h

    # Başlık (44px Extra Bold — Daily Brief Standart Kapak Fontu)
    f_baslik = make_image._font(44, make_image.EKSEN_BASLIK)
    baslik_b = make_image._buyuk_harf(baslik)
    baslik_satirlari = metin_kutuya_sar(ciz, baslik_b, f_baslik, alan_w, maks_satir=3)
    baslik_satir_h = 54
    baslik_h = len(baslik_satirlari) * baslik_satir_h

    # Konumlandırma: Alt bilgi çizgisine çarpmayacak şekilde
    spot_y = alt_bilgi_y - 48 - spot_h
    baslik_y = spot_y - (24 if spot_h else 0) - baslik_h

    # Başlığı Çiz
    by = baslik_y
    for bs in baslik_satirlari:
        ciz.text((kenar, by), bs, font=f_baslik, fill=(255, 255, 255))
        by += baslik_satir_h

    # Spotu Çiz
    sy = spot_y
    for ss in spot_satirlari:
        ciz.text((kenar, sy), ss, font=f_spot, fill=(226, 232, 240))
        sy += spot_satir_h

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
