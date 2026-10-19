"""
hava_durumu.py — Meteoroloji / Hava Durumu uyarı haberleri için özel infografik detay şablonu.

1080x1920 tuvalde (STORY_GUVENLI_PAY = 330 merkezi 4:5 güvenli alanında):
  - Üstte Uyarı Kodu (Sarı / Turuncu / Kırmızı / Mavi) Hero Kartı + Vektör Hava İkonu + Zaman Aralığı
  - Ortada 3'lü Metrik Kartı (Hadise, Şiddet/Hız, Sıcaklık/Bölge)
  - Etkilenen İller / Bölgeler Izgarası (Okunaklı Şehir Pill Rozetleri)
  - Altta Tedbir & Risk Uyarısı Şeridi
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


def _uyari_renkleri(kod_metni: str) -> tuple[tuple[int, int, int], str]:
    k = (kod_metni or "").casefold()
    if "kırmızı" in k or "kirmizi" in k:
        return (239, 68, 68), "KIRMIZI KODLU UYARI"
    if "turuncu" in k:
        return (249, 115, 22), "TURUNCU KODLU UYARI"
    if "sarı" in k or "sari" in k:
        return (234, 179, 8), "SARI KODLU UYARI"
    return (6, 182, 212), "METEOROLOJİ UYARISI"


def _vektor_hava_ikonu_ciz(ciz: ImageDraw.ImageDraw, cx: int, cy: int, olay: str, renk: tuple[int, int, int]) -> None:
    """Bulut ve yağış/şimşek/kar vektör ikonu çizer."""
    # Bulut gövdesi
    bulut_renk = (226, 232, 240)
    ciz.ellipse([cx - 38, cy - 22, cx + 2, cy + 16], fill=bulut_renk)
    ciz.ellipse([cx - 16, cy - 34, cx + 28, cy + 10], fill=bulut_renk)
    ciz.ellipse([cx + 8, cy - 18, cx + 42, cy + 16], fill=bulut_renk)
    ciz.rounded_rectangle([cx - 32, cy - 4, cx + 38, cy + 16], radius=8, fill=bulut_renk)

    o = (olay or "").casefold()
    if "fırtına" in o or "gök gürültü" in o or "kuvvetli" in o:
        # Şimşek
        ciz.polygon(
            [(cx - 4, cy + 18), (cx - 16, cy + 36), (cx - 4, cy + 36), (cx - 10, cy + 54), (cx + 12, cy + 30), (cx, cy + 30)],
            fill=renk,
        )
    else:
        # Yağmur damlaları / kar
        for dx in (-18, 0, 18):
            ciz.line([cx + dx, cy + 22, cx + dx - 6, cy + 38], fill=renk, width=4)


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
    `veri` sözlüğünden Hava Durumu & Meteoroloji Uyarısı infografik slaytı üretir.
    """
    iller = [str(x).strip() for x in (veri.get("etkilenen_iller") or veri.get("iller") or []) if str(x).strip()]
    uyari_basligi = (veri.get("uyari_basligi") or veri.get("baslik") or haber.get("ig_baslik") or "").strip()
    olay_metni = (veri.get("olay_tipi") or veri.get("hadise") or "").strip()
    siddet_metni = (veri.get("siddet_bilgisi") or veri.get("ruzgar") or veri.get("yagis") or "").strip()
    sicaklik_metni = (veri.get("sicaklik_bilgisi") or veri.get("sicaklik") or "").strip()
    if not iller and not olay_metni and not siddet_metni:
        return None

    kod_ham = (veri.get("uyari_kodu") or "sari").strip()
    ana_renk, kod_etiket = _uyari_renkleri(kod_ham)

    gorsel, kenar, dikey_kenar, y_ust, y_alt = temel_tuval_olustur(
        ayarlar,
        kategori=haber.get("kategori") or "turkiye",
        arkaplan=arkaplan,
        tema_alt_renk=(6, 18, 32),
    )
    genislik = make_image.STORY_GENISLIK
    alan_g = genislik - 2 * kenar
    y = y_ust + 8

    # --- 1. ÜST UYARI HERO KARTI ---
    hero_h = 168
    gorsel = cam_kart_ciz(
        gorsel,
        (kenar, y, genislik - kenar, y + hero_h),
        dolgu=(10, 24, 42, 232),
        kenarlik=(*ana_renk, 115),
        yaricap=22,
        sol_centik=ana_renk,
    )
    ciz = ImageDraw.Draw(gorsel, "RGBA")

    # Sol ikon dairesi
    ikon_cx = kenar + 74
    ikon_cy = y + hero_h // 2 - 6
    ciz.ellipse(
        [ikon_cx - 48, ikon_cy - 44, ikon_cx + 48, ikon_cy + 52],
        fill=(*ana_renk, 32),
        outline=(*ana_renk, 90),
        width=2,
    )
    _vektor_hava_ikonu_ciz(ciz, ikon_cx, ikon_cy - 4, olay_metni or uyari_basligi, ana_renk)

    # Sağ metin alanı
    mx = kenar + 144
    mw = alan_g - 168
    zaman_araligi = (veri.get("zaman_araligi") or veri.get("saat_araligi") or "Bugün & Yarın Etkili").strip()

    f_kod = make_image._font(22, make_image.EKSEN_BASLIK)
    ciz.text((mx, y + 22), kod_etiket, font=f_kod, fill=ana_renk)

    # Zaman aralığı rozeti (sağ üst)
    f_zaman = make_image._font(20, make_image.EKSEN_KUCUK)
    zw = int(ciz.textlength(zaman_araligi[:34], font=f_zaman)) + 24
    ciz.rounded_rectangle(
        [genislik - kenar - zw - 20, y + 18, genislik - kenar - 20, y + 50],
        radius=10,
        fill=(255, 255, 255, 24),
    )
    ciz.text((genislik - kenar - zw - 8, y + 23), zaman_araligi[:34], font=f_zaman, fill=(226, 232, 240))

    f_hero = make_image._font(30, make_image.EKSEN_BASLIK)
    bas_satirlar = metin_kutuya_sar(ciz, uyari_basligi, f_hero, mw, maks_satir=2)
    hy = y + 60
    for s in bas_satirlar:
        ciz.text((mx, hy), s, font=f_hero, fill=(255, 255, 255))
        hy += 38

    y += hero_h + 20

    # --- 2. 3'LÜ METRİK KARTLARI ---
    metrikler = [
        ("BEKLENEN HADİSE", olay_metni or "Kuvvetli Yağış & Fırtına", ana_renk),
        ("ŞİDDET / RÜZGAR", siddet_metni or "50-80 km/saat", (6, 182, 212)),
        ("SICAKLIK & ETKİ", sicaklik_metni or "4-8 °C Düşüş", (16, 185, 129)),
    ]
    m_arasi = 16
    m_gen = (alan_g - 2 * m_arasi) // 3
    m_yuk = 132

    for i, (m_etiket, m_deger, m_renk) in enumerate(metrikler):
        mx1 = kenar + i * (m_gen + m_arasi)
        mx2 = mx1 + m_gen
        gorsel = cam_kart_ciz(
            gorsel,
            (mx1, y, mx2, y + m_yuk),
            dolgu=(12, 28, 48, 220),
            kenarlik=(*m_renk, 75),
            yaricap=18,
        )
        ciz = ImageDraw.Draw(gorsel, "RGBA")
        f_me = make_image._font(19, make_image.EKSEN_KUCUK)
        f_md = make_image._font(25, make_image.EKSEN_BASLIK)
        ciz.text((mx1 + 18, y + 18), m_etiket, font=f_me, fill=m_renk)
        d_satir = metin_kutuya_sar(ciz, m_deger, f_md, m_gen - 32, maks_satir=2)
        dy = y + 52
        for ds in d_satir:
            ciz.text((mx1 + 18, dy), ds, font=f_md, fill=(248, 250, 252))
            dy += 31

    y += m_yuk + 20

    # --- 3. ETKİLENEN İLLER / BÖLGELER IZGARASI ---
    onlem_notu = (veri.get("onlem_notu") or veri.get("onlem") or veri.get("alt_not") or "").strip()
    onlem_pay = 122 if onlem_notu else 0
    il_kart_h = y_alt - y - onlem_pay

    gorsel = cam_kart_ciz(
        gorsel,
        (kenar, y, genislik - kenar, y + il_kart_h),
        dolgu=(9, 22, 38, 222),
        kenarlik=(255, 255, 255, 38),
        yaricap=20,
    )
    ciz = ImageDraw.Draw(gorsel, "RGBA")
    f_ib = make_image._font(23, make_image.EKSEN_BASLIK)
    il_baslik = f"ETKİLENEN İLLER VE BÖLGELER ({len(iller)} NOKTA)" if iller else "ETKİLENEN BÖLGELER"
    ciz.text((kenar + 24, y + 20), il_baslik, font=f_ib, fill=(226, 170, 88))

    if iller:
        gosterilecek = iller[:20]
        sutun_sayisi = 4 if len(gosterilecek) > 12 else (3 if len(gosterilecek) > 6 else 2)
        ic_x = kenar + 24
        ic_w = alan_g - 48
        chip_gap_x = 14
        chip_gap_y = 14
        chip_w = (ic_w - (sutun_sayisi - 1) * chip_gap_x) // sutun_sayisi
        satir_sayisi = (len(gosterilecek) + sutun_sayisi - 1) // sutun_sayisi
        kalan_il_h = il_kart_h - 76
        chip_h = min(64, max(44, (kalan_il_h - (satir_sayisi - 1) * chip_gap_y) // max(1, satir_sayisi)))

        f_il = make_image._font(24 if sutun_sayisi <= 3 else 22, make_image.EKSEN_BASLIK)
        bas_y = y + 64
        for idx, il_adi in enumerate(gosterilecek):
            r_i = idx // sutun_sayisi
            c_i = idx % sutun_sayisi
            cx1 = ic_x + c_i * (chip_w + chip_gap_x)
            cy1 = bas_y + r_i * (chip_h + chip_gap_y)
            cx2 = cx1 + chip_w
            cy2 = cy1 + chip_h

            ciz.rounded_rectangle(
                [cx1, cy1, cx2, cy2],
                radius=12,
                fill=(18, 38, 64),
                outline=(*ana_renk, 85),
                width=1,
            )
            il_kisa = il_adi.replace("**", "").strip()[:18]
            iw = ciz.textlength(il_kisa, font=f_il)
            ciz.text(
                (cx1 + (chip_w - iw) / 2, cy1 + (chip_h - 28) / 2),
                il_kisa,
                font=f_il,
                fill=(248, 250, 252),
            )

    y += il_kart_h + 16

    # --- 4. TEDBİR & RİSK UYARISI ŞERİDİ ---
    if onlem_notu:
        gorsel = cam_kart_ciz(
            gorsel,
            (kenar, y, genislik - kenar, y_alt),
            dolgu=(20, 26, 38, 230),
            kenarlik=(*ana_renk, 85),
            yaricap=18,
            sol_centik=ana_renk,
        )
        ciz = ImageDraw.Draw(gorsel)
        f_onlem = make_image._font(24, make_image.EKSEN_OZET)
        onlem_satirlar = metin_kutuya_sar(ciz, onlem_notu, f_onlem, alan_g - 48, maks_satir=2)
        oy = y + (106 - len(onlem_satirlar) * 32) // 2
        for os_ in onlem_satirlar:
            ciz.text((kenar + 24, oy), os_, font=f_onlem, fill=(241, 245, 249))
            oy += 32

    return ust_ve_alt_bar_bas(
        gorsel,
        ayarlar=ayarlar,
        kaynak=kaynak,
        rozet_metni=kod_etiket,
        rozet_renk=ana_renk,
        ulke_kodu=haber.get("ulke_kodu") or None,
        ulke_adi=haber.get("ulke_adi") or None,
        sayfa=sayfa,
        toplam_sayfa=toplam_sayfa,
        arsiv_ibaresi=arsiv_ibaresi,
    )
