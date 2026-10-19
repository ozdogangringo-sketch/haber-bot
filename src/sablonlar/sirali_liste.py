"""
sirali_liste.py — Top 5 / Puan Durumu / İhracat & Şehir Sıralaması yatay bar grafik şablonu.

1080x1920 tuvalde (STORY_GUVENLI_PAY = 330 merkezi 4:5 güvenli alanında):
  - Üstte Sıralama Başlık Kartı
  - Ortada #1 Altın, #2 Gümüş, #3 Bronz Rozetli ve Yatay İlerleme Çubuklu 4-7 Sıralama Kartı
  - Altta Özet / Kaynak Notu Şeridi
"""

from __future__ import annotations

import re
from PIL import Image, ImageDraw

from src import make_image
from src.sablonlar.ortak import (
    cam_kart_ciz,
    metin_kutuya_sar,
    temel_tuval_olustur,
    ust_ve_alt_bar_bas,
)


def _sayisal_deger_cikar(metin: str) -> float | None:
    if not metin:
        return None
    temiz = str(metin).replace(".", "").replace(",", ".")
    eslesme = re.search(r"[-+]?\d+(?:\.\d+)?", temiz)
    if not eslesme:
        return None
    try:
        return abs(float(eslesme.group(0)))
    except ValueError:
        return None


def sirali_liste_slayti_ciz(
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
    `veri` sözlüğünden Top 5-7 Sıralama / Puan Durumu infografik slaytı üretir.
    En az 3 öğe yoksa `None` döner.
    """
    ham_ogeler = veri.get("ogeler") or veri.get("liste") or []
    ogeler = [
        o for o in ham_ogeler
        if isinstance(o, dict) and (o.get("ad") or o.get("isim")) and o.get("deger")
    ]
    if len(ogeler) < 3:
        return None

    ogeler = ogeler[:6]
    liste_basligi = (veri.get("liste_basligi") or veri.get("baslik") or haber.get("ig_baslik") or "SIRALAMA VE VERİ TABLOSU").strip()
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

    # --- 1. ÜST BAŞLIK KARTI ---
    ust_h = 112
    gorsel = cam_kart_ciz(
        gorsel,
        (kenar, y, genislik - kenar, y + ust_h),
        dolgu=(10, 26, 44, 232),
        kenarlik=(245, 158, 11, 95),
        yaricap=20,
        sol_centik=(245, 158, 11),
    )
    ciz = ImageDraw.Draw(gorsel, "RGBA")
    f_lbas = make_image._font(29, make_image.EKSEN_BASLIK)
    lb_satir = metin_kutuya_sar(ciz, liste_basligi, f_lbas, alan_g - 52, maks_satir=2)
    ly = y + (ust_h - len(lb_satir) * 36) // 2
    for s in lb_satir:
        ciz.text((kenar + 28, ly), s, font=f_lbas, fill=(255, 255, 255))
        ly += 36

    y += ust_h + 20

    # --- 2. SIRALI LİSTE VE YATAY BAR KARTLARI ---
    not_pay = 112 if alt_not else 0
    kalan_h = y_alt - y - not_pay
    adet = len(ogeler)
    gap = 14
    kart_h = min(140, max(92, (kalan_h - (adet - 1) * gap) // adet))

    sayilar = [_sayisal_deger_cikar(str(o.get("deger") or "")) for o in ogeler]
    maks_sayi = max([s for s in sayilar if s is not None] or [100.0]) or 100.0

    f_sira = make_image._font(24, make_image.EKSEN_BASLIK)
    f_ad = make_image._font(27, make_image.EKSEN_BASLIK)
    f_alt = make_image._font(21, make_image.EKSEN_OZET)
    f_deger = make_image._font(29, make_image.EKSEN_BASLIK)

    for idx, oge in enumerate(ogeler):
        ky1 = y + idx * (kart_h + gap)
        ky2 = ky1 + kart_h

        if idx == 0:
            r_renk = (245, 158, 11)   # Altın (#1)
        elif idx == 1:
            r_renk = (203, 213, 225)  # Gümüş (#2)
        elif idx == 2:
            r_renk = (217, 119, 6)    # Bronz (#3)
        else:
            r_renk = (6, 182, 212)    # Siber Turkuaz

        gorsel = cam_kart_ciz(
            gorsel,
            (kenar, ky1, genislik - kenar, ky2),
            dolgu=(12, 28, 48, 226),
            kenarlik=(*r_renk, 80 if idx < 3 else 45),
            yaricap=16,
            sol_centik=r_renk,
        )
        ciz = ImageDraw.Draw(gorsel, "RGBA")

        # Sol sıra rozeti
        rx1 = kenar + 22
        ry1 = ky1 + 18
        ciz.rounded_rectangle(
            [rx1, ry1, rx1 + 56, ry1 + 44],
            radius=12,
            fill=(*r_renk, 38),
            outline=r_renk,
            width=2 if idx < 3 else 1,
        )
        sira_str = f"#{idx + 1}"
        sw = ciz.textlength(sira_str, font=f_sira)
        ciz.text((rx1 + (56 - sw) / 2, ry1 + 8), sira_str, font=f_sira, fill=r_renk)

        ad_metin = str(oge.get("ad") or oge.get("isim") or "").replace("**", "").strip()
        alt_bilgi = str(oge.get("alt_bilgi") or "").replace("**", "").strip()
        deger_metin = str(oge.get("deger") or "").replace("**", "").strip()

        # Sağda değer
        dw = ciz.textlength(deger_metin[:18], font=f_deger)
        ciz.text((genislik - kenar - 24 - dw, ky1 + 20), deger_metin[:18], font=f_deger, fill=(255, 255, 255))

        # Solda isim ve varsa alt bilgi
        isim_x = rx1 + 74
        isim_w = int(alan_g - 130 - dw)
        ad_satir = metin_kutuya_sar(ciz, ad_metin, f_ad, max(180, isim_w), maks_satir=1)
        if ad_satir:
            ciz.text((isim_x, ky1 + 20), ad_satir[0], font=f_ad, fill=(248, 250, 252))
        if alt_bilgi and kart_h >= 106:
            ciz.text((isim_x, ky1 + 52), alt_bilgi[:42], font=f_alt, fill=(148, 163, 184))

        # Alt kısımda yatay oran çubuğu (progress bar)
        bar_x1 = isim_x
        bar_x2 = genislik - kenar - 24
        bar_y1 = ky2 - 22
        bar_y2 = ky2 - 12
        bar_gen = bar_x2 - bar_x1

        oran = oge.get("oran_yuzde") or oge.get("oran")
        if isinstance(oran, (int, float)) and 5 <= oran <= 100:
            oran_f = float(oran) / 100.0
        elif sayilar[idx] is not None and maks_sayi > 0:
            oran_f = max(0.18, min(1.0, sayilar[idx] / maks_sayi))
        else:
            oran_f = max(0.25, 1.0 - idx * 0.14)

        ciz.rounded_rectangle([bar_x1, bar_y1, bar_x2, bar_y2], radius=5, fill=(30, 41, 59))
        dolu_x2 = bar_x1 + int(bar_gen * oran_f)
        ciz.rounded_rectangle([bar_x1, bar_y1, dolu_x2, bar_y2], radius=5, fill=r_renk)

    y += adet * kart_h + max(0, adet - 1) * gap + 18

    # --- 3. ALT BİLGİ ŞERİDİ ---
    if alt_not and y + 65 <= y_alt:
        gorsel = cam_kart_ciz(
            gorsel,
            (kenar, y, genislik - kenar, y_alt),
            dolgu=(10, 28, 38, 228),
            kenarlik=(6, 182, 212, 80),
            yaricap=16,
            sol_centik=(6, 182, 212),
        )
        ciz = ImageDraw.Draw(gorsel, "RGBA")
        f_not = make_image._font(24, make_image.EKSEN_OZET)
        not_satir = metin_kutuya_sar(ciz, alt_not, f_not, alan_g - 48, maks_satir=2)
        ny = y + ((y_alt - y) - len(not_satir) * 32) // 2
        for ns in not_satir:
            ciz.text((kenar + 24, ny), ns, font=f_not, fill=(226, 232, 240))
            ny += 32

    return ust_ve_alt_bar_bas(
        gorsel,
        ayarlar=ayarlar,
        kaynak=kaynak,
        rozet_metni="SIRALAMA & VERİ TABLOSU",
        rozet_renk=(245, 158, 11),
        ulke_kodu=haber.get("ulke_kodu") or None,
        ulke_adi=haber.get("ulke_adi") or None,
        sayfa=sayfa,
        toplam_sayfa=toplam_sayfa,
        arsiv_ibaresi=arsiv_ibaresi,
    )
