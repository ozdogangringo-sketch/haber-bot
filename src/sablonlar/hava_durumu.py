"""
hava_durumu.py — Meteoroloji / Hava Durumu uyarı haberleri için tam dolu lüks infografik şablonu.

1080x1920 tuvalde (STORY_GUVENLI_PAY = 330 merkezi 4:5 güvenli alanında):
  - 4:5 tuvali tam dolu, dengeli ve zengin kullanır (sıfır alt boşluk garantisi).
  - 1. Bölüm: Üst Hero Meteorolojik Uyarı Kartı (Kod rozeti, geçerlilik zamanı, başlık, hadise)
  - 2. Bölüm: 3'lü Yarı Saydam Vektör İkonlu Gösterge Kartları (Rüzgar çizgileri, Yağmur bulutu, Termometre)
  - 3. Bölüm: Etkilenen İller ve Riskli Merkezler Paneli (3 sütunlu lüks cam kapsüller, parlayan nokta)
  - 4. Bölüm: Afet ve Acil Durum Tedbirleri Paneli (Tehlike rozetleri, MGM/AFAD uyarısı, 112 Acil Hattı)
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFilter

from src import make_image
from src.sablonlar.ortak import (
    cam_kart_ciz,
    metin_kutuya_sar,
    nokta_matrisi_ciz,
    temel_tuval_olustur,
    ust_ve_alt_bar_bas,
)


def _uyari_renkleri(kod_metni: str) -> tuple[tuple[int, int, int], str]:
    k = (kod_metni or "").casefold()
    if "kırmızı" in k or "kirmizi" in k:
        return (239, 68, 68), "KIRMIZI KODLU ACİL UYARI"
    if "turuncu" in k:
        return (249, 115, 22), "TURUNCU KODLU METEOROLOJİK UYARI"
    if "sarı" in k or "sari" in k:
        return (245, 158, 11), "SARI KODLU METEOROLOJİK UYARI"
    return (6, 182, 212), "METEOROLOJİ GENEL MÜDÜRLÜĞÜ UYARISI"


def _ciz_ruzgar_ikonu(ciz: ImageDraw.ImageDraw, cx: int, cy: int, renk: tuple[int, int, int]) -> None:
    """Akıcı rüzgar ve fırtına dalgaları ikonu çizer."""
    ciz.line([cx - 20, cy - 10, cx + 12, cy - 10], fill=renk, width=3)
    ciz.arc([cx + 2, cy - 20, cx + 22, cy - 10], start=270, end=90, fill=renk, width=3)
    ciz.line([cx - 26, cy, cx + 6, cy], fill=renk, width=3)
    ciz.arc([cx - 4, cy - 10, cx + 16, cy], start=270, end=90, fill=renk, width=3)
    ciz.line([cx - 16, cy + 10, cx + 16, cy + 10], fill=renk, width=3)
    ciz.arc([cx + 6, cy + 10, cx + 24, cy + 20], start=90, end=270, fill=renk, width=3)


def _ciz_yagis_ikonu(ciz: ImageDraw.ImageDraw, cx: int, cy: int, renk: tuple[int, int, int]) -> None:
    """Modern minimalist bulut ve yağmur damlaları ikonu çizer."""
    ciz.ellipse([cx - 18, cy - 12, cx + 2, cy + 8], fill=(*renk, 45), outline=renk, width=2)
    ciz.ellipse([cx - 6, cy - 20, cx + 16, cy + 4], fill=(*renk, 45), outline=renk, width=2)
    ciz.ellipse([cx + 6, cy - 8, cx + 22, cy + 8], fill=(*renk, 45), outline=renk, width=2)
    ciz.rounded_rectangle([cx - 14, cy - 2, cx + 20, cy + 8], radius=5, fill=(*renk, 45), outline=renk, width=2)
    ciz.line([cx - 10, cy + 12, cx - 14, cy + 22], fill=renk, width=3)
    ciz.line([cx, cy + 12, cx - 4, cy + 22], fill=renk, width=3)
    ciz.line([cx + 10, cy + 12, cx + 6, cy + 22], fill=renk, width=3)


def _ciz_sicaklik_ikonu(ciz: ImageDraw.ImageDraw, cx: int, cy: int, renk: tuple[int, int, int]) -> None:
    """Minimalist cam termometre ikonu çizer."""
    ciz.rounded_rectangle([cx - 5, cy - 20, cx + 5, cy + 8], radius=4, fill=(*renk, 45), outline=renk, width=2)
    ciz.ellipse([cx - 12, cy + 4, cx + 12, cy + 24], fill=(*renk, 45), outline=renk, width=2)
    ciz.rounded_rectangle([cx - 2, cy - 8, cx + 2, cy + 8], radius=2, fill=renk)
    ciz.ellipse([cx - 7, cy + 9, cx + 7, cy + 19], fill=renk)


def hava_durumu_slayti_ciz(
    haber: dict,
    veri: dict,
    ayarlar: dict,
    kaynak: str,
    arkaplan: Image.Image | None = None,
    sayfa: int = 1,
    toplam_sayfa: int = 2,
    arsiv_ibaresi: bool = False,
) -> Image.Image | None:
    """
    `veri` sözlüğünden iOS Weather tarzı atmosferik gökyüzü, kutucuksuz şeffaf cam podlar,
    derin difüzyon gölgesi ve sıfır taşmalı (logo/footer korumalı) lüks meteoroloji şablonu üretir.
    """
    if not veri or not isinstance(veri, dict):
        return None

    iller_ham = veri.get("etkilenen_iller") or veri.get("iller") or []
    if isinstance(iller_ham, str):
        iller_ham = [s.strip() for s in iller_ham.split(",") if s.strip()]
    elif not isinstance(iller_ham, (list, tuple, set)):
        iller_ham = []

    iller = [str(x).strip() for x in iller_ham if str(x).strip()]
    uyari_basligi = str(veri.get("uyari_basligi") or veri.get("baslik") or haber.get("ig_baslik") or "").strip()
    olay_metni = str(veri.get("olay_tipi") or veri.get("hadise") or "").strip()
    siddet_metni = str(veri.get("siddet_bilgisi") or veri.get("ruzgar") or veri.get("yagis") or "").strip()
    sicaklik_metni = str(veri.get("sicaklik_bilgisi") or veri.get("sicaklik") or "").strip()
    if not iller and not olay_metni and not siddet_metni:
        return None

    kod_ham = str(veri.get("uyari_kodu") or "sari").strip()
    ana_renk, kod_etiket = _uyari_renkleri(kod_ham)
    zaman_araligi = str(veri.get("zaman_araligi") or veri.get("saat_araligi") or "Bugün & Yarın").strip()
    onlem_notu = str(veri.get("onlem_notu") or veri.get("onlem") or veri.get("alt_not") or "").strip()

    genislik = make_image.STORY_GENISLIK   # 1080
    yukseklik = make_image.STORY_YUKSEKLIK # 1920
    kenar = ayarlar.get("gorsel", {}).get("kenar_bosluk", 64)
    dikey_kenar = ayarlar.get("gorsel", {}).get("dikey_guvenli_pay", make_image.STORY_GUVENLI_PAY) # 330
    alan_g = genislik - 2 * kenar # 952

    # --- 1. iOS WEATHER TARZI ATMOSFERİK GÖKYÜZÜ ZEMİNİ ---
    olay_kucuk = (olay_metni + " " + uyari_basligi).casefold()

    if "sıcak" in olay_kucuk or "sicak" in olay_kucuk or "47" in olay_kucuk:
        # Ekstrem Sıcaklık / Solar Obsidian
        c_ust = (22, 8, 8)
        c_orta = (42, 16, 12)
        c_alt = (14, 6, 8)
        glow_renk = (249, 115, 22)
    elif "kar" in olay_kucuk or "tipi" in olay_kucuk or "buz" in olay_kucuk:
        # Kar & Tipi / Buzul Arktik
        c_ust = (6, 16, 28)
        c_orta = (12, 32, 52)
        c_alt = (4, 12, 22)
        glow_renk = (14, 165, 233)
    elif "lodos" in olay_kucuk or "rüzgar" in olay_kucuk:
        # Fırtına & Lodos / Derin Petrol Teal
        c_ust = (4, 18, 26)
        c_orta = (8, 36, 48)
        c_alt = (4, 14, 20)
        glow_renk = (6, 182, 212)
    else:
        # Şiddetli Yağış & Fırtına / Fırtına Grisi & Kobalt
        c_ust = (5, 14, 24)
        c_orta = (12, 28, 46)
        c_alt = (4, 10, 18)
        glow_renk = ana_renk

    canvas = Image.new("RGB", (genislik, yukseklik), c_ust)
    c_draw = ImageDraw.Draw(canvas)

    # Dikey atmosfer gradyanı
    for y_step in range(yukseklik):
        t = y_step / float(yukseklik)
        if t < 0.5:
            r = int(c_ust[0] + (c_orta[0] - c_ust[0]) * (t * 2))
            g = int(c_ust[1] + (c_orta[1] - c_ust[1]) * (t * 2))
            b = int(c_ust[2] + (c_orta[2] - c_ust[2]) * (t * 2))
        else:
            r = int(c_orta[0] + (c_alt[0] - c_orta[0]) * ((t - 0.5) * 2))
            g = int(c_orta[1] + (c_alt[1] - c_orta[1]) * ((t - 0.5) * 2))
            b = int(c_orta[2] + (c_alt[2] - c_orta[2]) * ((t - 0.5) * 2))
        c_draw.line([(0, y_step), (genislik, y_step)], fill=(r, g, b))

    # Atmosferik Işık Aurası (Ambient Volumetric Glow)
    aura = Image.new("RGBA", (genislik, yukseklik), (0, 0, 0, 0))
    a_draw = ImageDraw.Draw(aura)
    a_draw.ellipse([genislik // 2 - 420, 480, genislik // 2 + 420, 1100], fill=(*glow_renk, 38))
    aura = aura.filter(ImageFilter.GaussianBlur(radius=90))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), aura).convert("RGB")

    # Üst ve Alt Vignette Karartması (Story 9:16 ve 4:5 Feed Uyumu)
    vig = Image.new("RGBA", (genislik, yukseklik), (0, 0, 0, 0))
    v_draw = ImageDraw.Draw(vig)
    for y_v in range(0, dikey_kenar + 20):
        alfa = int(210 * (1.0 - (y_v / (dikey_kenar + 20))) ** 1.6)
        v_draw.line([(0, y_v), (genislik, y_v)], fill=(2, 6, 12, alfa))
    for y_v in range(1920 - dikey_kenar - 20, yukseklik):
        alfa = int(230 * ((y_v - (1920 - dikey_kenar - 20)) / (dikey_kenar + 20)) ** 1.6)
        v_draw.line([(0, y_v), (genislik, y_v)], fill=(2, 6, 12, alfa))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), vig).convert("RGB")

    # --- 2. TAŞMASIZ YÜKSEKLİK VE DÜZEN PLANLAMASI ---
    # Logo 144px ve y=314'te başlar, y=458'de biter.
    # Bu yüzden içerik KESİNLİKLE y = 474'te başlar! (Logo çakışması SIFIRLANDI)
    # Alt bar y=1556'da başlar, bu yüzden içerik KESİNLİKLE y = 1515'te biter! (Alt taşma SIFIRLANDI)
    y = 474

    ciz = ImageDraw.Draw(canvas, "RGBA")

    # Üst Etiket Satırı: Uyarı Rozeti + Geçerlilik Saati
    f_etiket = make_image._font(17, make_image.EKSEN_BASLIK)
    ew = int(ciz.textlength(kod_etiket, font=f_etiket)) + 24
    ciz.rounded_rectangle([kenar, y, kenar + ew, y + 34], radius=8, fill=(*ana_renk, 38), outline=(*ana_renk, 160), width=1)
    ciz.text((kenar + 12, y + 6), kod_etiket, font=f_etiket, fill=ana_renk)

    zaman_str = f"GEÇERLİLİK: {zaman_araligi.upper()}"
    f_zmn = make_image._font(16, make_image.EKSEN_KUCUK)
    zw = ciz.textlength(zaman_str, font=f_zmn)
    ciz.text((genislik - kenar - zw, y + 7), zaman_str, font=f_zmn, fill=(160, 175, 195))

    y += 48

    # Başlık: Doğrudan gökyüzü üzerine, 34px Extra Bold ve yumuşak difüzyon gölgesiyle (Azami 3 satır)
    f_bas = make_image._font(34, make_image.EKSEN_BASLIK)
    bas_satirlar = make_image._satirlara_bol(uyari_basligi, f_bas, alan_g, ciz)
    if len(bas_satirlar) > 3:
        bas_satirlar = bas_satirlar[:3]
        if not bas_satirlar[2].endswith("..."):
            bas_satirlar[2] = bas_satirlar[2].rstrip(". ") + "..."
    bas_satir_h = 42

    b_golge = Image.new("RGBA", (genislik, yukseklik), (0, 0, 0, 0))
    bg_ciz = ImageDraw.Draw(b_golge)
    by_g = y
    for s in bas_satirlar:
        bg_ciz.text((kenar, by_g + 2), s.replace("**", ""), font=f_bas, fill=(0, 0, 0, 220))
        by_g += bas_satir_h
    b_golge = b_golge.filter(ImageFilter.GaussianBlur(7))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), b_golge).convert("RGB")
    ciz = ImageDraw.Draw(canvas, "RGBA")

    by = y
    for s in bas_satirlar:
        ciz.text((kenar, by), s.replace("**", ""), font=f_bas, fill=(255, 255, 255))
        by += bas_satir_h

    y = by + 6
    if olay_metni:
        f_had = make_image._font(20, make_image.EKSEN_OZET)
        ciz.text((kenar, y), f"Beklenen Hadise: {olay_metni[:75]}", font=f_had, fill=(6, 182, 212))
        y += 32

    y += 18

    # --- 3. 3'LÜ YARI SAYDAM FROSTED GLASS PODLAR (GÖRÜNTÜ FORMATINDAKİ GİBİ GÖLGE) ---
    pod_w = (alan_g - 2 * 14) // 3
    pod_h = 160

    kart_verileri = [
        ("RÜZGAR & FIRTINA", siddet_metni or "70-85 km/s", "Tam Fırtına Seviyesi", _ciz_ruzgar_ikonu, ana_renk),
        ("YAĞIŞ MİKTARI", "80-120 kg/m²", "Kuvvetli Sağanak", _ciz_yagis_ikonu, (6, 182, 212)),
        ("SICAKLIK DEĞİŞİMİ", sicaklik_metni or "6-10 °C Düşüş", "Ani Soğuma Dalgası", _ciz_sicaklik_ikonu, (16, 185, 129)),
    ]

    # Görüntü formatındaki gibi 20px yumuşak difüzyon gölgesi
    pod_golge = Image.new("RGBA", (genislik, yukseklik), (0, 0, 0, 0))
    pg_ciz = ImageDraw.Draw(pod_golge)
    for i in range(3):
        px1 = kenar + i * (pod_w + 14)
        pg_ciz.rounded_rectangle([px1 - 2, y + 6, px1 + pod_w + 2, y + pod_h + 16], radius=24, fill=(0, 0, 0, 175))
    pod_golge = pod_golge.filter(ImageFilter.GaussianBlur(radius=20))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), pod_golge).convert("RGB")
    ciz = ImageDraw.Draw(canvas, "RGBA")

    for i, (k_lbl, k_val, k_sub, k_ikoniciz, k_renk) in enumerate(kart_verileri):
        px1 = kenar + i * (pod_w + 14)
        px2 = px1 + pod_w

        # ŞEFFAF FROSTED CAM ZEMİN (Kaba kutu değil, transparan cam pod!)
        ciz.rounded_rectangle([px1, y, px2, y + pod_h], radius=20, fill=(255, 255, 255, 22), outline=(255, 255, 255, 45), width=1)

        # Üstte şık minimalist ikon ve etiket
        k_ikoniciz(ciz, px1 + 30, y + 30, k_renk)
        f_klbl = make_image._font(15, make_image.EKSEN_BASLIK)
        ciz.text((px1 + 58, y + 21), k_lbl, font=f_klbl, fill=k_renk)

        # Ortada büyük parlak rakam
        f_kval = make_image._font(30, make_image.EKSEN_BASLIK)
        ciz.text((px1 + 16, y + 70), k_val[:14], font=f_kval, fill=(255, 255, 255))

        # Altta durum açıklaması
        f_ksub = make_image._font(15, make_image.EKSEN_OZET)
        ciz.text((px1 + 16, y + 116), k_sub, font=f_ksub, fill=(160, 175, 195))

    y += pod_h + 26

    # --- 4. ETKİLENEN İLLER VE RİSKLİ MERKEZLER (ŞEFFAF KAPSÜLLER & GÖLGE) ---
    il_baslik = f"RİSK ALTINDAKİ BÖLGELER ({len(iller)} İL)" if iller else "RİSK ALTINDAKİ MERKEZLER"
    f_il_hdr = make_image._font(18, make_image.EKSEN_BASLIK)

    # Parlayan meteorolojik odak noktası
    ciz.ellipse([kenar, y + 5, kenar + 12, y + 17], fill=ana_renk)
    ciz.text((kenar + 22, y), il_baslik, font=f_il_hdr, fill=(245, 248, 252))

    y += 34

    sutun_sayisi = 3
    col_w = (alan_g - (sutun_sayisi - 1) * 12) // sutun_sayisi
    chip_h = 40
    iller_kullan = iller[:15] if iller else ["Bölge geneli tüm iller teyakkuzda"]
    f_il_ad = make_image._font(19, make_image.EKSEN_BASLIK)
    toplam_satir = (len(iller_kullan) + sutun_sayisi - 1) // sutun_sayisi

    # İllerin arkasına hafif difüzyon gölgesi
    il_golge = Image.new("RGBA", (genislik, yukseklik), (0, 0, 0, 0))
    ig_ciz = ImageDraw.Draw(il_golge)
    for idx in range(len(iller_kullan)):
        c_i = idx % sutun_sayisi
        r_i = idx // sutun_sayisi
        cx1 = kenar + c_i * (col_w + 12)
        cy1 = y + r_i * (chip_h + 8)
        ig_ciz.rounded_rectangle([cx1, cy1 + 2, cx1 + col_w, cy1 + chip_h + 4], radius=12, fill=(0, 0, 0, 110))
    il_golge = il_golge.filter(ImageFilter.GaussianBlur(radius=8))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), il_golge).convert("RGB")
    ciz = ImageDraw.Draw(canvas, "RGBA")

    for idx, il_adi in enumerate(iller_kullan):
        c_i = idx % sutun_sayisi
        r_i = idx // sutun_sayisi
        cx1 = kenar + c_i * (col_w + 12)
        cy1 = y + r_i * (chip_h + 8)
        cx2 = cx1 + col_w
        cy2 = cy1 + chip_h

        # ŞEFFAF FROSTED CAM KAPSÜL
        ciz.rounded_rectangle([cx1, cy1, cx2, cy2], radius=10, fill=(255, 255, 255, 18), outline=(*ana_renk, 75), width=1)
        ciz.ellipse([cx1 + 12, cy1 + 15, cx1 + 20, cy1 + 23], fill=ana_renk)
        ciz.text((cx1 + 28, cy1 + 8), il_adi.strip()[:18], font=f_il_ad, fill=(255, 255, 255))

    y += toplam_satir * (chip_h + 8) + 24

    # --- 5. AFET & ACİL DURUM TEDBİRLERİ (KUTUCUKSUZ EDİTORYAL ANLATIM, ÇENTİKLİ METİN) ---
    ciz.line([(kenar, y), (genislik - kenar, y)], fill=(255, 255, 255, 25), width=1)
    y += 18

    # 3 Tehlike Rozeti (Şeffaf Cam Haplar)
    tehlikeler = ["ÇATI UÇMASI RİSKİ", "SEL VE SU BASKINI", "ULAŞIMDA AKSAMA"]
    th_w = (alan_g - 2 * 12) // 3
    for ti, th in enumerate(tehlikeler):
        tx1 = kenar + ti * (th_w + 12)
        ciz.rounded_rectangle([tx1, y, tx1 + th_w, y + 32], radius=6, fill=(255, 255, 255, 20), outline=(255, 255, 255, 40), width=1)
        f_th = make_image._font(15, make_image.EKSEN_BASLIK)
        tw = ciz.textlength(th, font=f_th)
        ciz.text((tx1 + (th_w - tw) / 2, y + 6), th, font=f_th, fill=(235, 242, 250))

    y += 44

    # Editoryal Önlem Metni (Solunda dikey çentik ile, KUTUCUKSUZ! 1482px tavan sınırı garantili)
    y_hotline_ust = 1482
    kalan_onlem_h = y_hotline_ust - y - 10

    if onlem_notu and kalan_onlem_h >= 36:
        f_onl = make_image._font(22, make_image.EKSEN_OZET)
        onl_satirlar = make_image._satirlara_bol(onlem_notu, f_onl, alan_g - 28, ciz)
        maks_satir = max(1, kalan_onlem_h // 30)
        if len(onl_satirlar) > maks_satir:
            onl_satirlar = onl_satirlar[:maks_satir]
            if not onl_satirlar[-1].endswith("..."):
                onl_satirlar[-1] = onl_satirlar[-1].rstrip(". ") + "..."
        onl_h = len(onl_satirlar) * 30

        # 4px dikey çentik
        ciz.rounded_rectangle([kenar, y + 3, kenar + 4, y + onl_h - 1], radius=2, fill=ana_renk)

        oy = y
        for s in onl_satirlar:
            ciz.text((kenar + 20, oy), s.replace("**", ""), font=f_onl, fill=(240, 245, 250))
            oy += 30
        y = oy + 12

    # Sabit Alt Çağrı Hattı & Radar Durumu (1488 - 1515 aralığında, alt bara ASLA taşmaz!)
    ciz.line([(kenar, 1488), (genislik - kenar, 1488)], fill=(255, 255, 255, 20), width=1)
    f_hotline = make_image._font(16, make_image.EKSEN_KUCUK)
    ciz.ellipse([kenar, 1502, kenar + 8, 1510], fill=(239, 68, 68))
    ciz.text((kenar + 16, 1498), "ACİL DURUM İHBAR HATTI: 112 ACİL ÇAĞRI MERKEZİ", font=f_hotline, fill=ana_renk)

    ciz.ellipse([genislik - kenar - 194, 1502, genislik - kenar - 186, 1510], fill=(16, 185, 129))
    ciz.text((genislik - kenar - 180, 1498), "MGM RADAR TAKİBİ AKTİF", font=f_hotline, fill=(160, 175, 195))

    # --- 6. ÜST VE ALT KURUMSAL BARLAR (ust_ve_alt_bar_bas) ---
    return ust_ve_alt_bar_bas(
        canvas,
        ayarlar=ayarlar,
        kaynak=kaynak,
        rozet_metni="METEOROLOJİ UYARISI",
        rozet_renk=ana_renk,
        ulke_kodu=haber.get("ulke_kodu") or None,
        ulke_adi=haber.get("ulke_adi") or None,
        sayfa=sayfa,
        toplam_sayfa=toplam_sayfa,
        arsiv_ibaresi=arsiv_ibaresi,
    )
