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
import re
from PIL import Image, ImageDraw, ImageFilter

from src import make_image, fetch_kulup_logo
from src.sablonlar.ortak import ust_ve_alt_bar_bas, metin_kutuya_sar

log = logging.getLogger(__name__)


def _takim_adi_sigdir_kapak(ciz: ImageDraw.Draw, ham_ad: str, max_gen: int) -> tuple[str, any]:
    """Armanın altındaki takım adını adaptif olarak küçültür ve sığdırır; sıfır taşma garantisi."""
    ad = make_image._buyuk_harf(ham_ad.strip())
    for punto in (30, 26, 24, 22, 20, 18, 16):
        f = make_image._font(punto, [float(punto), 750.0])
        if ciz.textlength(ad, font=f) <= max_gen:
            return ad, f

    # Kısaltma denemesi ("FUTBOL KULÜBÜ" -> "FK", "SPOR KULÜBÜ" -> "SK", "A.Ş." kaldır)
    ad_kisa = re.sub(r"\bFUTBOL KULÜBÜ\b", "FK", ad)
    ad_kisa = re.sub(r"\bSPOR KULÜBÜ\b", "SK", ad_kisa)
    ad_kisa = re.sub(r"\bA\.?Ş\.?\b", "", ad_kisa).strip()
    for punto in (22, 20, 18, 16, 15):
        f = make_image._font(punto, [float(punto), 750.0])
        if ciz.textlength(ad_kisa, font=f) <= max_gen:
            return ad_kisa, f

    f = make_image._font(15, [15.0, 750.0])
    while ad_kisa and ciz.textlength(ad_kisa + "…", font=f) > max_gen:
        ad_kisa = ad_kisa[:-1].rstrip()
    return (ad_kisa + "…" if ad_kisa else ham_ad[:12]), f


def _telemetri_sigdir(ciz: ImageDraw.Draw, txt: str, max_gen: int, baslangic_punto: int = 16) -> tuple[str, any]:
    """Turnuva ve maç bilgisi gibi telemetri satırlarını taşmayacak şekilde sığdırır."""
    for punto in (baslangic_punto, baslangic_punto - 2, baslangic_punto - 4):
        if punto < 12:
            break
        f = make_image._font(punto, make_image.EKSEN_BASLIK)
        if ciz.textlength(txt, font=f) <= max_gen:
            return txt, f
    f = make_image._font(12, make_image.EKSEN_BASLIK)
    kirp = txt
    while kirp and ciz.textlength(kirp + "…", font=f) > max_gen:
        kirp = kirp[:-1].rstrip()
    return (kirp + "…" if kirp else txt[:20]), f


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
    yeşil çim üzerine devasa 360px 3D kulüp armalı, volumetrik projektörlü kapak slaytı (1080x1920) üretir.
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

    # =========================================================================
    # GÖRSEL ALANI: 360px DEVASA RESMİ 3D KULÜP ARMALARI & MAÇ MERKEZİ
    # =========================================================================
    y_arma = dikey_kenar + 175  # 505 px (DB logosu altına nefes payı)
    arma_boyutu = 360
    sol_x = 24
    sag_x = genislik - 24 - arma_boyutu

    logo_ev = fetch_kulup_logo.kulup_logosu_al(ev_ad, boyut=arma_boyutu)
    logo_dep = fetch_kulup_logo.kulup_logosu_al(dep_ad, boyut=arma_boyutu)

    # Doğukan İsteği: Kapaktaki iki renk stadyum atmosferi takımların kendi renklerinden oluşur.
    ev_renkler, dep_renkler = fetch_kulup_logo.mac_renklerini_ayarla(ev_ad, dep_ad, logo_ev, logo_dep)

    ev_atmo = ev_renkler.get("atmosphere", (119, 13, 44))
    dep_atmo = dep_renkler.get("atmosphere", (20, 20, 28))

    # 1. TEMEL TUVAL — ZENGİN STADYUM VE PROJEKTÖR ZEMİNİ + SPLIT KULÜP ATMOSFERİ
    gorsel = stadyum_zemini_olustur(genislik, yukseklik)

    # Split Arena Diyagonal Atmosfer (Sol: Ev Sahibi Kulüp Rengi / Sağ: Deplasman Kulüp Rengi)
    split = Image.new("RGBA", (genislik, yukseklik), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(split)
    s_draw.polygon([(0, 0), (genislik // 2 + 100, 0), (genislik // 2 - 100, 1150), (0, 1150)], fill=(ev_atmo[0], ev_atmo[1], ev_atmo[2], 115))
    s_draw.polygon([(genislik // 2 + 100, 0), (genislik, 0), (genislik, 1150), (genislik // 2 - 100, 1150)], fill=(dep_atmo[0], dep_atmo[1], dep_atmo[2], 115))
    gorsel = Image.alpha_composite(gorsel.convert("RGBA"), split.filter(ImageFilter.GaussianBlur(80))).convert("RGB")

    # Armaların Arkasındaki Volümetrik Kulüp Parıltısı (Hale)
    hale = Image.new("RGBA", (genislik, yukseklik), (0, 0, 0, 0))
    h_draw = ImageDraw.Draw(hale)
    h_draw.ellipse([sol_x - 30, y_arma - 30, sol_x + arma_boyutu + 30, y_arma + arma_boyutu + 30], fill=(ev_atmo[0], ev_atmo[1], ev_atmo[2], 75))
    h_draw.ellipse([sag_x - 30, y_arma - 30, sag_x + arma_boyutu + 30, y_arma + arma_boyutu + 30], fill=(dep_atmo[0], dep_atmo[1], dep_atmo[2], 75))
    gorsel = Image.alpha_composite(gorsel.convert("RGBA"), hale.filter(ImageFilter.GaussianBlur(55))).convert("RGB")

    ciz_split = ImageDraw.Draw(gorsel, "RGBA")
    ciz_split.line([(genislik // 2 + 80, dikey_kenar + 120), (genislik // 2 - 80, dikey_kenar + 680)], fill=(255, 255, 255, 55), width=2)

    # 3D Derinlik Gölgeleri
    golge = Image.new("RGBA", (genislik, yukseklik), (0, 0, 0, 0))
    g_draw = ImageDraw.Draw(golge)
    g_draw.ellipse([sol_x - 12, y_arma + 25, sol_x + arma_boyutu + 12, y_arma + arma_boyutu + 45], fill=(0, 0, 0, 230))
    g_draw.ellipse([sag_x - 12, y_arma + 25, sag_x + arma_boyutu + 12, y_arma + arma_boyutu + 45], fill=(0, 0, 0, 230))
    gorsel = Image.alpha_composite(gorsel.convert("RGBA"), golge.filter(ImageFilter.GaussianBlur(24))).convert("RGB")

    if logo_ev:
        gorsel.paste(logo_ev, (sol_x, y_arma), mask=logo_ev)
    else:
        ciz_tmp = ImageDraw.Draw(gorsel, "RGBA")
        ciz_tmp.ellipse([sol_x, y_arma, sol_x + arma_boyutu, y_arma + arma_boyutu], fill=(245, 158, 11, 40), outline=(245, 158, 11), width=2)
        f_mono = make_image._font(56, make_image.EKSEN_BASLIK)
        ciz_tmp.text((sol_x + 90, y_arma + 140), ev_ad[:3].upper(), font=f_mono, fill=(255, 255, 255))

    if logo_dep:
        gorsel.paste(logo_dep, (sag_x, y_arma), mask=logo_dep)
    else:
        ciz_tmp = ImageDraw.Draw(gorsel, "RGBA")
        ciz_tmp.ellipse([sag_x, y_arma, sag_x + arma_boyutu, y_arma + arma_boyutu], fill=(14, 165, 233, 40), outline=(14, 165, 233), width=2)
        f_mono = make_image._font(56, make_image.EKSEN_BASLIK)
        ciz_tmp.text((sag_x + 90, y_arma + 140), dep_ad[:3].upper(), font=f_mono, fill=(255, 255, 255))

    ciz = ImageDraw.Draw(gorsel, "RGBA")

    # Üst Turnuva / Lig Kapsülü (Center, Top of Match Area)
    turnuva_ciz, f_tur = _telemetri_sigdir(ciz, turnuva, max_gen=320, baslangic_punto=16)
    tw = ciz.textlength(turnuva_ciz, font=f_tur)
    ciz.rounded_rectangle([(genislik - tw) // 2 - 16, y_arma + 12, (genislik + tw) // 2 + 16, y_arma + 36], radius=8, fill=(10, 14, 20, 200), outline=(255, 255, 255, 60), width=1)
    ciz.text(((genislik - tw) // 2, y_arma + 15), turnuva_ciz, font=f_tur, fill=(255, 255, 255))

    # Merkez Daire 'VS / MS' Madalyon Rozeti
    mx = genislik // 2
    my = y_arma + arma_boyutu // 2 + 10
    rc = 64
    ciz.ellipse([mx - rc, my - rc, mx + rc, my + rc], fill=(8, 18, 26, 250), outline=(255, 255, 255, 80), width=2)
    mac_sonu = bool(veri.get("mac_sonu")) or ("-" in skor_saat and ":" not in skor_saat)
    if mac_sonu:
        f_ust = make_image._font(22, [22.0, 750.0])
        f_alt = make_image._font(32, [32.0, 800.0])
        ust_txt = "MS"
        alt_txt = skor_saat
        ciz.ellipse([mx - rc + 6, my - rc + 6, mx + rc - 6, my + rc - 6], outline=(16, 185, 129, 180), width=1)
        ciz.text(((genislik - ciz.textlength(ust_txt, font=f_ust)) / 2, my - 34), ust_txt, font=f_ust, fill=(16, 185, 129))
        ciz.text(((genislik - ciz.textlength(alt_txt, font=f_alt)) / 2, my - 2), alt_txt, font=f_alt, fill=(255, 255, 255))
    else:
        ciz.ellipse([mx - rc + 6, my - rc + 6, mx + rc - 6, my + rc - 6], outline=(245, 158, 11, 140), width=1)
        f_vs = make_image._font(38, make_image.EKSEN_BASLIK)
        f_saat = make_image._font(20, make_image.EKSEN_BASLIK)
        ciz.text(((genislik - ciz.textlength("VS", font=f_vs)) / 2, my - 36), "VS", font=f_vs, fill=(255, 255, 255))
        ciz.text(((genislik - ciz.textlength(skor_saat, font=f_saat)) / 2, my + 8), skor_saat, font=f_saat, fill=(245, 158, 11))

    # Armaların Altındaki Takım İsimleri (SIFIR TAŞMA GARANTİSİ: max_gen = 380px)
    isim_y = y_arma + arma_boyutu + 14
    max_isim_w = arma_boyutu + 20

    ev_ad_ciz, f_ev = _takim_adi_sigdir_kapak(ciz, ev_ad, max_isim_w)
    dep_ad_ciz, f_dep = _takim_adi_sigdir_kapak(ciz, dep_ad, max_isim_w)

    ev_w = ciz.textlength(ev_ad_ciz, font=f_ev)
    dep_w = ciz.textlength(dep_ad_ciz, font=f_dep)

    ev_vurgu = ev_renkler.get("number") or ev_renkler.get("primary") or (255, 255, 255)
    dep_vurgu = dep_renkler.get("number") or dep_renkler.get("primary") or (255, 255, 255)

    ev_pos_x = max(18, sol_x + (arma_boyutu - int(ev_w)) // 2)
    dep_pos_x = min(genislik - 18 - int(dep_w), sag_x + (arma_boyutu - int(dep_w)) // 2)

    ciz.text((ev_pos_x, isim_y), ev_ad_ciz, font=f_ev, fill=ev_vurgu)
    ciz.text((dep_pos_x, isim_y), dep_ad_ciz, font=f_dep, fill=dep_vurgu)

    # Alt Stadyum & Hakem Telemetri Kapsülü (SIFIR TAŞMA GARANTİSİ: max_gen = 900px)
    if mac_bilgi:
        txt_bilgi, f_info = _telemetri_sigdir(ciz, mac_bilgi, max_gen=900, baslangic_punto=17)
        iw = ciz.textlength(txt_bilgi, font=f_info)
        ciz.rounded_rectangle([(genislik - iw) // 2 - 20, isim_y + 44, (genislik + iw) // 2 + 20, isim_y + 80], radius=18, fill=(6, 20, 28, 230), outline=(255, 255, 255, 35), width=1)
        ciz.text(((genislik - iw) // 2, isim_y + 51), txt_bilgi, font=f_info, fill=(226, 232, 240))

    # =========================================================================
    # DAILY BRIEF RESMİ METİN & TİPOGRAFİ MOTORU (make_image.yaziyi_bas)
    # =========================================================================
    baslik = (haber.get("ig_baslik") or haber.get("baslik_orj") or "Dev derbide ilk 11'ler belli oldu").strip()
    spot = (haber.get("spot") or haber.get("slayt_ozet") or haber.get("ozet") or "").strip()

    gorsel_ayarlar = dict(ayarlar.get("gorsel", {}))
    gorsel_ayarlar.update({
        "kenar_bosluk": 64,
        "dikey_guvenli_pay": dikey_kenar,
        "genislik": genislik,
        "yukseklik": yukseklik,
        "serit_rengi": [4, 18, 16],
        "kanca_ciz": False,
    })

    story_ayarlar = {
        **ayarlar,
        "gorsel": gorsel_ayarlar,
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
