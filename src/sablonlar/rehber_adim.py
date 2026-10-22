"""
rehber_adim.py — Başvuru Şartları / Adım Adım Rehber / Yeni Düzenleme Maddeleri şablonu.

1080x1920 tuvalde (STORY_GUVENLI_PAY = 330 merkezi 4:5 güvenli alanında):
  - Üstte Rehber Başlık Kartı
  - Ortada Dikey Zaman Çizgisiyle Bağlı 3-5 Numaralı Adım / Şart Kartı (01, 02, 03, 04...)
  - Altta Kritik Tarih / Başvuru Kanalı Uyarı Kutusu
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from src import make_image
from src.sablonlar.ortak import (
    cam_kart_ciz,
    metin_kutuya_sar,
    temel_tuval_olustur,
    ust_ve_alt_bar_bas,
)


def rehber_adim_slayti_ciz(
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
    `veri` sözlüğünden Adım Adım Rehber / Başvuru Şartları infografik slaytı üretir.
    En az 2 adım yoksa `None` döner.
    """
    ham_adimlar = veri.get("adimlar") or []
    adimlar = [
        a for a in ham_adimlar
        if isinstance(a, dict) and (a.get("baslik") or a.get("aciklama"))
    ]
    if len(adimlar) < 2:
        return None

    adimlar = adimlar[:5]
    rehber_basligi = (veri.get("rehber_basligi") or veri.get("baslik") or haber.get("ig_baslik") or "ADIM ADIM BAŞVURU VE UYGULAMA REHBERİ").strip()
    onemli_not = (veri.get("onemli_not") or veri.get("son_tarih") or veri.get("alt_not") or haber.get("sana_etkisi") or "").strip()

    gorsel, kenar, dikey_kenar, y_ust, y_alt = temel_tuval_olustur(
        ayarlar,
        kategori=haber.get("kategori") or "turkiye",
        arkaplan=arkaplan,
        tema_alt_renk=(5, 18, 28),
    )
    genislik = make_image.STORY_GENISLIK
    alan_g = genislik - 2 * kenar
    alan_h = y_alt - y_ust

    # --- ALT NOT ÖLÇÜSÜ (Kompakt & Metinle Orantılı) ---
    ciz_olcum = ImageDraw.Draw(gorsel, "RGBA")
    f_not = make_image._font(24, make_image.EKSEN_OZET)
    not_satir = metin_kutuya_sar(ciz_olcum, onemli_not, f_not, alan_g - 48, maks_satir=3) if onemli_not else []
    alt_not_h = max(74, min(120, 36 + len(not_satir) * 32)) if not_satir else 0

    ust_h = 114
    adet = len(adimlar)
    gap = 18 if adet <= 3 else (16 if adet <= 4 else 14)

    if adet == 2:
        kart_h = 190
    elif adet == 3:
        kart_h = 160
    elif adet == 4:
        kart_h = 135
    else:
        kart_h = 112

    # 4:5 Güvenli Alanında Dikey Ortalama / Dengeleme
    toplam_icerik = ust_h + 22 + (adet * kart_h + (adet - 1) * gap) + (18 + alt_not_h if alt_not_h else 0)
    y_offset_extra = max(8, (alan_h - toplam_icerik) // 2)
    y = y_ust + y_offset_extra

    # --- 1. ÜST REHBER BAŞLIK KARTI ---
    gorsel = cam_kart_ciz(
        gorsel,
        (kenar, y, genislik - kenar, y + ust_h),
        dolgu=(9, 28, 42, 232),
        kenarlik=(6, 182, 212, 95),
        yaricap=20,
        sol_centik=(6, 182, 212),
    )
    ciz = ImageDraw.Draw(gorsel, "RGBA")
    f_rbas = make_image._font(29, make_image.EKSEN_BASLIK)
    rb_satir = metin_kutuya_sar(ciz, rehber_basligi, f_rbas, alan_g - 52, maks_satir=2)
    ry = y + (ust_h - len(rb_satir) * 36) // 2
    for s in rb_satir:
        ciz.text((kenar + 28, ry), s, font=f_rbas, fill=(255, 255, 255))
        ry += 36

    y += ust_h + 22

    # --- 2. ADIM KARTLARI + SOL ZAMAN ÇİZGİSİ ---
    # Sol dikey bağlantı çizgisi
    ciz = ImageDraw.Draw(gorsel, "RGBA")
    cizgi_x = kenar + 42
    ciz.line(
        [cizgi_x, y + 36, cizgi_x, y + (adet - 1) * (kart_h + gap) + kart_h - 36],
        fill=(6, 182, 212),
        width=4,
    )

    f_no = make_image._font(26, make_image.EKSEN_BASLIK)
    f_abas = make_image._font(26, make_image.EKSEN_BASLIK)
    f_aacik = make_image._font(24, make_image.EKSEN_OZET)

    renk_paleti = [
        (226, 170, 88),
        (6, 182, 212),
        (16, 185, 129),
        (56, 189, 248),
        (168, 85, 247),
    ]

    for idx, adim in enumerate(adimlar):
        ay1 = y + idx * (kart_h + gap)
        ay2 = ay1 + kart_h
        vurgu = renk_paleti[idx % len(renk_paleti)]

        # Sağdaki adım kartı
        kx1 = kenar + 98
        kx2 = genislik - kenar
        gorsel = cam_kart_ciz(
            gorsel,
            (kx1, ay1, kx2, ay2),
            dolgu=(12, 28, 46, 226),
            kenarlik=(*vurgu, 85),
            yaricap=18,
            sol_centik=vurgu,
        )
        ciz = ImageDraw.Draw(gorsel, "RGBA")

        # Soldaki numara dairesi
        cy = (ay1 + ay2) // 2
        ciz.ellipse(
            [cizgi_x - 32, cy - 32, cizgi_x + 32, cy + 32],
            fill=(10, 24, 40),
            outline=vurgu,
            width=3,
        )
        no_str = f"0{idx + 1}"
        nw = ciz.textlength(no_str, font=f_no)
        ciz.text((cizgi_x - nw / 2, cy - 16), no_str, font=f_no, fill=vurgu)

        # Kart içi başlık ve açıklama
        a_bas = str(adim.get("baslik") or f"{idx + 1}. Adım").replace("**", "").strip()
        a_acik = str(adim.get("aciklama") or "").replace("**", "").strip()
        ic_w = (kx2 - kx1) - 44

        bas_satir = metin_kutuya_sar(ciz, a_bas, f_abas, ic_w, maks_satir=1)
        acik_satir = metin_kutuya_sar(ciz, a_acik, f_aacik, ic_w, maks_satir=2)

        toplam_metin_h = (34 if bas_satir else 0) + len(acik_satir) * 31 + (6 if bas_satir and acik_satir else 0)
        my = ay1 + max(14, (kart_h - toplam_metin_h) // 2)

        if bas_satir:
            ciz.text((kx1 + 24, my), bas_satir[0], font=f_abas, fill=vurgu)
            my += 38
        for s in acik_satir:
            ciz.text((kx1 + 24, my), s, font=f_aacik, fill=(241, 245, 249))
            my += 31

    y += adet * kart_h + max(0, adet - 1) * gap + 18

    # --- 3. ALT ÖNEMLİ NOT KUTUSU (Kompakt ve Orantılı Boyut) ---
    if not_satir and alt_not_h > 0 and y + alt_not_h <= y_alt + 30:
        gorsel = cam_kart_ciz(
            gorsel,
            (kenar, y, genislik - kenar, y + alt_not_h),
            dolgu=(10, 30, 34, 228),
            kenarlik=(16, 185, 129, 85),
            yaricap=16,
            sol_centik=(16, 185, 129),
        )
        ciz = ImageDraw.Draw(gorsel, "RGBA")
        ny = y + (alt_not_h - len(not_satir) * 32) // 2
        for ns in not_satir:
            ciz.text((kenar + 24, ny), ns, font=f_not, fill=(220, 252, 231))
            ny += 32

    return ust_ve_alt_bar_bas(
        gorsel,
        ayarlar=ayarlar,
        kaynak=kaynak,
        rozet_metni="ADIM ADIM REHBER & ŞARTLAR",
        rozet_renk=(6, 182, 212),
        ulke_kodu=haber.get("ulke_kodu") or None,
        ulke_adi=haber.get("ulke_adi") or None,
        sayfa=sayfa,
        toplam_sayfa=toplam_sayfa,
        arsiv_ibaresi=arsiv_ibaresi,
    )
