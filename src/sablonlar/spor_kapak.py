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
    yeşil çim üzerine devasa 380px 3D kulüp armalı, volumetrik projektörlü kapak slaytı (1080x1920) üretir.
    Metin katmanı doğrudan make_image.yaziyi_bas motoruyla (Tümce düzeni, 13px blur gölge) çizilir.
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

    # Volumetrik Nova & Projektör Işıkları
    isik = Image.new("RGBA", (genislik, yukseklik), (0, 0, 0, 0))
    i_draw = ImageDraw.Draw(isik)
    # Sol GS Kehribar Flare
    i_draw.ellipse([0, 480, 560, 1060], fill=(245, 158, 11, 75))
    i_draw.polygon([(0, 0), (340, 0), (500, 950), (0, 800)], fill=(245, 158, 11, 30))
    # Sağ FB Safir Flare
    i_draw.ellipse([520, 480, 1080, 1060], fill=(56, 189, 248, 75))
    i_draw.polygon([(740, 0), (1080, 0), (1080, 800), (580, 950)], fill=(6, 182, 212, 30))
    gorsel = Image.alpha_composite(gorsel.convert("RGBA"), isik.filter(ImageFilter.GaussianBlur(70))).convert("RGB")

    # =========================================================================
    # GÖRSEL ALANI: 380px DEVASA RESMİ 3D KULÜP ARMALARI & MAÇ MERKEZİ
    # =========================================================================
    y_arma = dikey_kenar + 175  # 505 px (DB logosu altına nefes payı)
    arma_boyutu = 380
    sol_x = 18
    sag_x = genislik - 18 - arma_boyutu

    logo_ev = fetch_kulup_logo.kulup_logosu_al(ev_ad, boyut=arma_boyutu)
    logo_dep = fetch_kulup_logo.kulup_logosu_al(dep_ad, boyut=arma_boyutu)

    # 3D Derinlik Gölgeleri
    golge = Image.new("RGBA", (genislik, yukseklik), (0, 0, 0, 0))
    g_draw = ImageDraw.Draw(golge)
    g_draw.ellipse([sol_x - 12, y_arma + arma_boyutu - 45, sol_x + arma_boyutu + 12, y_arma + arma_boyutu + 50], fill=(0, 0, 0, 235))
    g_draw.ellipse([sag_x - 12, y_arma + arma_boyutu - 45, sag_x + arma_boyutu + 12, y_arma + arma_boyutu + 50], fill=(0, 0, 0, 235))
    gorsel = Image.alpha_composite(gorsel.convert("RGBA"), golge.filter(ImageFilter.GaussianBlur(26))).convert("RGB")

    if logo_ev:
        gorsel.paste(logo_ev, (sol_x, y_arma), mask=logo_ev)
    else:
        ciz_tmp = ImageDraw.Draw(gorsel, "RGBA")
        ciz_tmp.ellipse([sol_x, y_arma, sol_x + arma_boyutu, y_arma + arma_boyutu], fill=(245, 158, 11, 40), outline=(245, 158, 11), width=2)
        f_mono = make_image._font(56, make_image.EKSEN_BASLIK)
        ciz_tmp.text((sol_x + 100, y_arma + 140), ev_ad[:3].upper(), font=f_mono, fill=(255, 255, 255))

    if logo_dep:
        gorsel.paste(logo_dep, (sag_x, y_arma), mask=logo_dep)
    else:
        ciz_tmp = ImageDraw.Draw(gorsel, "RGBA")
        ciz_tmp.ellipse([sag_x, y_arma, sag_x + arma_boyutu, y_arma + arma_boyutu], fill=(14, 165, 233, 40), outline=(14, 165, 233), width=2)
        f_mono = make_image._font(56, make_image.EKSEN_BASLIK)
        ciz_tmp.text((sag_x + 100, y_arma + 140), dep_ad[:3].upper(), font=f_mono, fill=(255, 255, 255))

    ciz = ImageDraw.Draw(gorsel, "RGBA")

    # Merkez 3D Cam Faset Kapsülü (VS + Saat)
    mx = genislik // 2
    my = y_arma + arma_boyutu // 2
    cw = 176
    ch = 146
    ciz.rounded_rectangle([mx - cw // 2, my - ch // 2, mx + cw // 2, my + ch // 2], radius=26, fill=(6, 18, 22, 245), outline=(255, 255, 255, 70), width=2)
    ciz.rounded_rectangle([mx - cw // 2 + 6, my - ch // 2 + 6, mx + cw // 2 - 6, my + ch // 2 - 6], radius=20, outline=(16, 185, 129, 140), width=1)

    f_lig = make_image._font(14, make_image.EKSEN_BASLIK)
    lig_txt = turnuva if len(turnuva) <= 18 else "SÜPER LİG"
    ciz.text(((genislik - ciz.textlength(lig_txt, font=f_lig)) / 2, my - ch // 2 + 16), lig_txt, font=f_lig, fill=(245, 158, 11))

    f_vs = make_image._font(44, make_image.EKSEN_BASLIK)
    ciz.text(((genislik - ciz.textlength("VS", font=f_vs)) / 2, my - 26), "VS", font=f_vs, fill=(255, 255, 255))

    f_saat = make_image._font(23, make_image.EKSEN_BASLIK)
    ciz.text(((genislik - ciz.textlength(skor_saat, font=f_saat)) / 2, my + 34), skor_saat, font=f_saat, fill=(52, 211, 153))

    # Armaların Altındaki Takım İsimleri
    f_isim = make_image._font(32, make_image.EKSEN_BASLIK)
    ev_ad_b = make_image._buyuk_harf(ev_ad)
    dep_ad_b = make_image._buyuk_harf(dep_ad)
    ev_w = ciz.textlength(ev_ad_b, font=f_isim)
    dep_w = ciz.textlength(dep_ad_b, font=f_isim)
    isim_y = y_arma + arma_boyutu + 14
    ciz.text((sol_x + (arma_boyutu - ev_w) / 2, isim_y), ev_ad_b, font=f_isim, fill=(245, 158, 11))
    ciz.text((sag_x + (arma_boyutu - dep_w) / 2, isim_y), dep_ad_b, font=f_isim, fill=(56, 189, 248))

    # Alt Stadyum & Hakem Telemetri Kapsülü
    if mac_bilgi:
        f_info = make_image._font(18, make_image.EKSEN_BASLIK)
        iw = ciz.textlength(mac_bilgi, font=f_info)
        ciz.rounded_rectangle([(genislik - iw) / 2 - 22, isim_y + 48, (genislik + iw) / 2 + 22, isim_y + 88], radius=20, fill=(6, 22, 26, 235), outline=(255, 255, 255, 30), width=1)
        ciz.text(((genislik - iw) / 2, isim_y + 57), mac_bilgi, font=f_info, fill=(167, 243, 208))

    # =========================================================================
    # DAILY BRIEF RESMİ METİN & TİPOGRAFİ MOTORU (make_image.yaziyi_bas)
    # =========================================================================
    # Başlık: Doğal Tümce Düzeni (Sentence Case), bağıran ALL-CAPS yok!
    baslik = (haber.get("ig_baslik") or haber.get("baslik_orj") or "Dev derbide ilk 11'ler belli oldu").strip()
    spot = (haber.get("spot") or haber.get("slayt_ozet") or haber.get("ozet") or "").strip()

    story_ayarlar = {
        **ayarlar,
        "gorsel": {
            "kenar_bosluk": 64,
            "dikey_guvenli_pay": dikey_kenar,
            "genislik": genislik,
            "yukseklik": yukseklik,
            "serit_rengi": [4, 18, 16],
            **ayarlar.get("gorsel", {}),
        },
    }

    return make_image.yaziyi_bas(
        gorsel,
        baslik,
        make_image.kaynak_gosterim_adi(kaynak, ayarlar),
        story_ayarlar,
        ozet=spot or None,
        arsiv_ibaresi=arsiv_ibaresi,
        ulke_kodu=haber.get("ulke_kodu") or None,
        ulke_adi=haber.get("ulke_adi") or None,
        kategori="spor",
        son_slayt=False,
        haber=haber,
    )
