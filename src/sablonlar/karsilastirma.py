"""
karsilastirma.py — Eski vs Yeni / Zam / Tarife / Vergi / Maaş Karşılaştırma Tablosu şablonu.

1080x1920 tuvalde (STORY_GUVENLI_PAY = 330 merkezi 4:5 güvenli alanında):
  - Üstte Tablo Başlığı ve Sütun Etiketleri (Kalem | Eski | Yeni | Değişim)
  - Ortada 2-6 Satırlık Lüks Karşılaştırma Kartları (Eski -> Yeni okları ve renkli değişim rozetleri)
  - Altta Kompakt Yürürlük Tarihi / Önemli Not Şeridi (Asla dikey esnetilmez, metinle orantılı boyutta kalır)
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
    sol_etiket = make_image._buyuk_harf((veri.get("kalem_etiket") or veri.get("sol_etiket") or "KALEM / KATEGORİ").strip())
    eski_etiket = make_image._buyuk_harf((veri.get("eski_etiket") or "ESKİ").strip())
    yeni_etiket = make_image._buyuk_harf((veri.get("yeni_etiket") or "YENİ").strip())
    alt_not = (veri.get("alt_not") or haber.get("sana_etkisi") or "").strip()

    gorsel, kenar, dikey_kenar, y_ust, y_alt = temel_tuval_olustur(
        ayarlar,
        kategori=haber.get("kategori") or "ekonomi",
        arkaplan=arkaplan,
        tema_alt_renk=(5, 16, 28),
    )
    genislik = make_image.STORY_GENISLIK
    alan_g = genislik - 2 * kenar
    alan_h = y_alt - y_ust

    # --- ALT NOT ÖLÇÜSÜ (Kompakt & Metinle Orantılı) ---
    ciz_olcum = ImageDraw.Draw(gorsel, "RGBA")
    f_not = make_image._font(24, make_image.EKSEN_OZET)
    not_satirlar = metin_kutuya_sar(ciz_olcum, alt_not, f_not, alan_g - 52, maks_satir=3) if alt_not else []
    alt_not_h = max(74, min(126, 38 + len(not_satirlar) * 32)) if not_satirlar else 0

    ust_h = 114
    sutun_h = 34
    adet = len(satirlar)
    gap = 18 if adet <= 3 else (16 if adet <= 4 else 12)

    # Satır sayısına göre optimize edilmiş kart yükseklikleri
    if adet == 2:
        satir_h = 185
    elif adet == 3:
        satir_h = 160
    elif adet == 4:
        satir_h = 138
    elif adet == 5:
        satir_h = 118
    else:
        satir_h = 100

    # 4:5 Güvenli Alanında Dikey Ortalama / Dengeleme
    toplam_icerik = ust_h + 16 + sutun_h + 12 + (adet * satir_h + (adet - 1) * gap) + (20 + alt_not_h if alt_not_h else 0)
    y_offset_extra = max(8, (alan_h - toplam_icerik) // 2)
    y = y_ust + y_offset_extra

    # --- 1. TABLO ÜST BAŞLIK KARTI ---
    gorsel = cam_kart_ciz(
        gorsel,
        (kenar, y, genislik - kenar, y + ust_h),
        dolgu=(10, 26, 44, 235),
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

    y += ust_h + 16

    # --- 2. SÜTUN BAŞLIKLARI BARI ---
    f_sutun = make_image._font(20, make_image.EKSEN_BASLIK)
    ciz.text((kenar + 24, y), sol_etiket[:24], font=f_sutun, fill=(148, 163, 184))
    eski_x = kenar + int(alan_g * 0.44)
    yeni_x = kenar + int(alan_g * 0.66)
    ciz.text((eski_x, y), eski_etiket[:14], font=f_sutun, fill=(148, 163, 184))
    ciz.text((yeni_x, y), yeni_etiket[:14], font=f_sutun, fill=(226, 170, 88))
    y += sutun_h + 10

    # --- 3. KARŞILAŞTIRMA SATIRLARI ---
    f_kalem = make_image._font(28 if adet <= 3 else 25, make_image.EKSEN_BASLIK)
    f_eski = make_image._font(26 if adet <= 3 else 24, make_image.EKSEN_OZET)
    f_yeni = make_image._font(32 if adet <= 3 else 28, make_image.EKSEN_BASLIK)
    f_deg = make_image._font(22 if adet <= 3 else 20, make_image.EKSEN_BASLIK)

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
        k_satir = metin_kutuya_sar(ciz, kalem_metni, f_kalem, int(alan_g * 0.40), maks_satir=2)
        ky = sy1 + (satir_h - len(k_satir) * 34) // 2
        for ks in k_satir:
            ciz.text((kenar + 24, ky), ks, font=f_kalem, fill=(241, 245, 249))
            ky += 34

        orta_y = sy1 + (satir_h - 34) // 2

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
            dw = int(ciz.textlength(degisim[:12], font=f_deg)) + 26
            dh = 44 if adet <= 3 else 38
            dx1 = genislik - kenar - dw - 20
            dy1 = sy1 + (satir_h - dh) // 2
            ciz.rounded_rectangle(
                [dx1, dy1, dx1 + dw, dy1 + dh],
                radius=10,
                fill=(*d_renk, 38),
                outline=(*d_renk, 110),
                width=1,
            )
            ciz.text((dx1 + 13, dy1 + 7), degisim[:12], font=f_deg, fill=d_renk)

    y += adet * satir_h + max(0, adet - 1) * gap + 20

    # --- 4. ALT BİLGİ / YÜRÜRLÜK NOTU (Kompakt ve Orantılı Boyut) ---
    if not_satirlar and alt_not_h > 0 and y + alt_not_h <= y_alt + 30:
        gorsel = cam_kart_ciz(
            gorsel,
            (kenar, y, genislik - kenar, y + alt_not_h),
            dolgu=(10, 28, 36, 228),
            kenarlik=(16, 185, 129, 85),
            yaricap=16,
            sol_centik=(16, 185, 129),
        )
        ciz = ImageDraw.Draw(gorsel, "RGBA")
        ny = y + (alt_not_h - len(not_satirlar) * 32) // 2
        for ns in not_satirlar:
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
