"""
karsilastirma.py — Eski vs Yeni / Zam / Tarife / Vergi / Maaş Karşılaştırma Tablosu şablonu.

1080x1920 tuvalde (STORY_GUVENLI_PAY = 330 merkezi 4:5 güvenli alanında):
  - Üstte Tablo Başlığı ve Sütun Etiketleri (Kalem | Eski | Yeni | Değişim)
  - Ortada 3-6 Satırlık Lüks Karşılaştırma Kartları (Eski -> Yeni okları ve renkli değişim rozetleri)
  - Altta Yürürlük Tarihi / Önemli Not Şeridi
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


def karsilastirma_slayti_ciz(
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
    `veri` sözlüğünden Eski vs Yeni karşılaştırma tablosu slaytı üretir.
    En az 2 satır veri yoksa `None` döner.
    """
    ham_satirlar = veri.get("satirlar") or []
    satirlar = [s for s in ham_satirlar if isinstance(s, dict) and (s.get("kalem") or s.get("ad")) and s.get("yeni")]
    if len(satirlar) < 2:
        return None

    satirlar = satirlar[:6]
    tablo_basligi = (veri.get("tablo_basligi") or veri.get("baslik") or haber.get("ig_baslik") or "ESKİ VE YENİ TABLO KARŞILAŞTIRMASI").strip()
    sol_etiket = make_image._buyuk_harf((veri.get("kalem_etiket") or "KALEM / KATEGORİ").strip())
    eski_etiket = make_image._buyuk_harf((veri.get("eski_etiket") or veri.get("sol_etiket") or "ESKİ").strip())
    yeni_etiket = make_image._buyuk_harf((veri.get("yeni_etiket") or veri.get("sag_etiket") or "YENİ").strip())
    alt_not = (veri.get("alt_not") or haber.get("sana_etkisi") or "").strip()

    gorsel, kenar, dikey_kenar, y_ust, y_alt = temel_tuval_olustur(
        ayarlar,
        kategori=haber.get("kategori") or "ekonomi",
        arkaplan=arkaplan,
        tema_alt_renk=(5, 16, 28),
    )
    genislik = make_image.STORY_GENISLIK
    alan_g = genislik - 2 * kenar
    y = y_ust + 8

    # --- 1. TABLO ÜST BAŞLIK KARTI ---
    ust_h = 118
    gorsel = cam_kart_ciz(
        gorsel,
        (kenar, y, genislik - kenar, y + ust_h),
        dolgu=(10, 26, 44, 232),
        kenarlik=(226, 170, 88, 95),
        yaricap=20,
        sol_centik=(226, 170, 88),
    )
    ciz = ImageDraw.Draw(gorsel, "RGBA")
    f_tbas = make_image._font(30, make_image.EKSEN_BASLIK)
    tb_satir = metin_kutuya_sar(ciz, tablo_basligi, f_tbas, alan_g - 52, maks_satir=2)
    ty = y + (ust_h - len(tb_satir) * 38) // 2
    for s in tb_satir:
        ciz.text((kenar + 28, ty), s, font=f_tbas, fill=(255, 255, 255))
        ty += 38

    y += ust_h + 18

    # --- 2. SÜTUN BAŞLIKLARI BARI ---
    f_sutun = make_image._font(20, make_image.EKSEN_BASLIK)
    ciz.text((kenar + 24, y), sol_etiket[:24], font=f_sutun, fill=(148, 163, 184))
    eski_x = kenar + int(alan_g * 0.48)
    yeni_x = kenar + int(alan_g * 0.69)
    ciz.text((eski_x, y), eski_etiket[:14], font=f_sutun, fill=(148, 163, 184))
    ciz.text((yeni_x, y), yeni_etiket[:14], font=f_sutun, fill=(226, 170, 88))
    y += 36

    # --- 3. KARŞILAŞTIRMA SATIRLARI ---
    alt_not_pay = 116 if alt_not else 0
    kalan_h = y_alt - y - alt_not_pay
    adet = len(satirlar)
    gap = 14
    satir_h = min(132, max(86, (kalan_h - (adet - 1) * gap) // adet))

    f_kalem = make_image._font(26, make_image.EKSEN_BASLIK)
    f_eski = make_image._font(25, make_image.EKSEN_OZET)
    f_yeni = make_image._font(28, make_image.EKSEN_BASLIK)
    f_deg = make_image._font(21, make_image.EKSEN_BASLIK)

    for idx, s in enumerate(satirlar):
        sy1 = y + idx * (satir_h + gap)
        sy2 = sy1 + satir_h
        dolgu = (12, 28, 48, 224) if idx % 2 == 0 else (16, 36, 60, 224)
        gorsel = cam_kart_ciz(
            gorsel,
            (kenar, sy1, genislik - kenar, sy2),
            dolgu=dolgu,
            kenarlik=(255, 255, 255, 34),
            yaricap=16,
            sol_centik=(6, 182, 212) if idx % 2 == 0 else (226, 170, 88),
        )
        ciz = ImageDraw.Draw(gorsel, "RGBA")

        kalem_metni = str(s.get("kalem") or s.get("ad") or "").replace("**", "").strip()
        eski_deger = str(s.get("eski") or "—").replace("**", "").strip()
        yeni_deger = str(s.get("yeni") or "").replace("**", "").strip()
        degisim = str(s.get("degisim") or "").replace("**", "").strip()

        # Sol: Kalem adı
        k_satir = metin_kutuya_sar(ciz, kalem_metni, f_kalem, int(alan_g * 0.42), maks_satir=2)
        ky = sy1 + (satir_h - len(k_satir) * 32) // 2
        for ks in k_satir:
            ciz.text((kenar + 24, ky), ks, font=f_kalem, fill=(241, 245, 249))
            ky += 32

        orta_y = sy1 + (satir_h - 32) // 2

        # Orta: Eski değer + ok
        ciz.text((eski_x, orta_y + 2), eski_deger[:16], font=f_eski, fill=(148, 163, 184))
        ok_x = yeni_x - 34
        ciz.text((ok_x, orta_y), "→", font=f_kalem, fill=(226, 170, 88))

        # Sağ: Yeni değer
        ciz.text((yeni_x, orta_y - 2), yeni_deger[:16], font=f_yeni, fill=(255, 255, 255))

        # En sağ: Değişim rozeti (varsa)
        if degisim:
            negatif = degisim.startswith("-") or "indirim" in degisim.casefold() or "düşüş" in degisim.casefold()
            d_renk = (16, 185, 129) if not negatif else (239, 68, 68)
            dw = int(ciz.textlength(degisim[:12], font=f_deg)) + 24
            dx1 = genislik - kenar - dw - 18
            dy1 = sy1 + (satir_h - 42) // 2
            ciz.rounded_rectangle(
                [dx1, dy1, dx1 + dw, dy1 + 42],
                radius=10,
                fill=(*d_renk, 38),
                outline=(*d_renk, 110),
                width=1,
            )
            ciz.text((dx1 + 12, dy1 + 8), degisim[:12], font=f_deg, fill=d_renk)

    y += adet * satir_h + max(0, adet - 1) * gap + 18

    # --- 4. ALT BİLGİ / YÜRÜRLÜK NOTU ---
    if alt_not and y + 70 <= y_alt:
        gorsel = cam_kart_ciz(
            gorsel,
            (kenar, y, genislik - kenar, y_alt),
            dolgu=(10, 28, 36, 228),
            kenarlik=(16, 185, 129, 80),
            yaricap=16,
            sol_centik=(16, 185, 129),
        )
        ciz = ImageDraw.Draw(gorsel, "RGBA")
        f_not = make_image._font(24, make_image.EKSEN_OZET)
        not_satir = metin_kutuya_sar(ciz, alt_not, f_not, alan_g - 48, maks_satir=2)
        ny = y + ((y_alt - y) - len(not_satir) * 32) // 2
        for ns in not_satir:
            ciz.text((kenar + 24, ny), ns, font=f_not, fill=(220, 252, 231))
            ny += 32

    return ust_ve_alt_bar_bas(
        gorsel,
        ayarlar=ayarlar,
        kaynak=kaynak,
        rozet_metni="ESKİ & YENİ KARŞILAŞTIRMA",
        rozet_renk=(226, 170, 88),
        ulke_kodu=haber.get("ulke_kodu") or None,
        ulke_adi=haber.get("ulke_adi") or None,
        sayfa=sayfa,
        toplam_sayfa=toplam_sayfa,
        arsiv_ibaresi=arsiv_ibaresi,
    )
