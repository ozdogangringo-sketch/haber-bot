"""
karsilastirma.py — Eski vs Yeni / Zam / Tarife / Vergi / Maaş Karşılaştırma Tablosu şablonu.

1080x1920 tuvalde (STORY_GUVENLI_PAY = 330 merkezi 4:5 güvenli alanında):
  - Üstte Tablo Başlığı ve Sütun Etiketleri (Kalem | Eski | Yeni | Değişim)
  - Ortada 2-6 Satırlık Lüks Karşılaştırma Kartları (Hero Row altın çerçeve, parantezli alt kalem,
    üstü çizili eski değer, parlayan geçiş oku ve yön ikonlu akıllı değişim rozetleri)
  - Altta Kompakt ve Mikro Rozetli Yürürlük / Editör Notu Şeridi (💡 EDİTÖR NOTU)
  - Arka planda %5 opaklıkta siber nokta ızgarası (dot matrix)
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


def _nokta_matrisi_ciz(gorsel: Image.Image, x1: int, y1: int, x2: int, y2: int, adim: int = 44) -> Image.Image:
    """Merkezi 4:5 alanına ince, şık bir siber veri nokta ızgarası çizer."""
    katman = Image.new("RGBA", gorsel.size, (0, 0, 0, 0))
    kc = ImageDraw.Draw(katman)
    for x in range(x1, x2, adim):
        for y in range(y1, y2, adim):
            kc.ellipse([x - 1, y - 1, x + 1, y + 1], fill=(255, 255, 255, 12))
    return Image.alpha_composite(gorsel.convert("RGBA"), katman).convert("RGB")


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
    degisim_etiket = make_image._buyuk_harf((veri.get("degisim_etiket") or "DEĞİŞİM").strip())
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

    # Lüks veri terminali dokusu: Arka plana hafif nokta ızgarası ekle
    gorsel = _nokta_matrisi_ciz(gorsel, kenar, y_ust, genislik - kenar, y_alt, adim=44)

    # --- ALT NOT ÖLÇÜSÜ (Kompakt, Mikro Rozetli & Metinle Orantılı) ---
    ciz_olcum = ImageDraw.Draw(gorsel, "RGBA")
    f_not = make_image._font(23, make_image.EKSEN_OZET)
    not_satirlar = metin_kutuya_sar(ciz_olcum, alt_not, f_not, alan_g - 52, maks_satir=3) if alt_not else []
    alt_not_h = max(96, min(148, 58 + len(not_satirlar) * 30)) if not_satirlar else 0

    ust_h = 114
    sutun_h = 32
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
        dolgu=(10, 26, 44, 238),
        kenarlik=(226, 170, 88, 120),
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

    # --- 2. SÜTUN BAŞLIKLARI BARI (DEĞİŞİM sütunu dahil) ---
    f_sutun = make_image._font(20, make_image.EKSEN_BASLIK)
    ciz.text((kenar + 24, y), sol_etiket[:24], font=f_sutun, fill=(148, 163, 184))
    eski_x = kenar + int(alan_g * 0.43)
    yeni_x = kenar + int(alan_g * 0.65)
    ciz.text((eski_x, y), eski_etiket[:14], font=f_sutun, fill=(148, 163, 184))
    ciz.text((yeni_x, y), yeni_etiket[:14], font=f_sutun, fill=(226, 170, 88))
    deg_w = int(ciz.textlength(degisim_etiket[:12], font=f_sutun))
    ciz.text((genislik - kenar - deg_w - 24, y), degisim_etiket[:12], font=f_sutun, fill=(148, 163, 184))
    y += sutun_h + 10

    # --- 3. KARŞILAŞTIRMA SATIRLARI ---
    f_kalem = make_image._font(28 if adet <= 3 else 25, make_image.EKSEN_BASLIK)
    f_kalem_alt = make_image._font(21, make_image.EKSEN_OZET)
    f_eski = make_image._font(25 if adet <= 3 else 23, make_image.EKSEN_OZET)
    f_yeni = make_image._font(33 if adet <= 3 else 29, make_image.EKSEN_BASLIK)
    f_deg = make_image._font(21 if adet <= 3 else 19, make_image.EKSEN_BASLIK)
    f_ok = make_image._font(24, make_image.EKSEN_BASLIK)

    # Bağlamsal Renk ve Anlam Analizi (Zam vs İndirim vs Faiz)
    metin_tum = (haber.get("baslik") or "") + " " + (haber.get("metin") or "") + " " + tablo_basligi
    metin_tum_low = metin_tum.casefold()
    faiz_veya_indirim = any(w in metin_tum_low for w in ["faiz", "tcmb", "enflasyon", "indirim", "düşüş"])
    zam_veya_vergi = any(w in metin_tum_low for w in ["zam", "vergi", "fiyat", "harç", "tarife", "akaryakıt", "benzin", "motorin", "lpg"])

    for idx, s in enumerate(satirlar):
        sy1 = y + idx * (satir_h + gap)
        sy2 = sy1 + satir_h
        hero = (idx == 0)

        # 1. Satır: Hero Row (Lüks kehribar ışıltısı ve zenginleştirilmiş cam dolgu)
        dolgu = (18, 38, 64, 242) if hero else ((12, 26, 44, 226) if idx % 2 == 1 else (15, 32, 54, 226))
        kenarlik = (226, 170, 88, 130) if hero else (255, 255, 255, 38)
        sol_centik = (226, 170, 88) if hero else (6, 182, 212)

        gorsel = cam_kart_ciz(
            gorsel,
            (kenar, sy1, genislik - kenar, sy2),
            dolgu=dolgu,
            kenarlik=kenarlik,
            yaricap=16,
            sol_centik=sol_centik,
        )
        ciz = ImageDraw.Draw(gorsel, "RGBA")

        kalem_metni = str(s.get("kalem") or s.get("ad") or "").replace("**", "").strip()
        eski_deger = str(s.get("eski") or "—").replace("**", "").strip()
        yeni_deger = str(s.get("yeni") or "").replace("**", "").strip()
        degisim = str(s.get("degisim") or "").replace("**", "").strip()

        # Sol: Kalem adı ve alt etiket (parantez ayrımı)
        m_par = re.match(r"^(.*?)\s*\((.*?)\)$", kalem_metni)
        if m_par:
            ana_ad = m_par.group(1).strip()
            alt_ad = m_par.group(2).strip()
            orta_kalem = sy1 + (satir_h - 52) // 2
            ciz.text((kenar + 24, orta_kalem), ana_ad, font=f_kalem, fill=(255, 255, 255) if hero else (241, 245, 249))
            ciz.text((kenar + 24, orta_kalem + 32), f"({alt_ad})", font=f_kalem_alt, fill=(148, 163, 184))
        else:
            k_satir = metin_kutuya_sar(ciz, kalem_metni, f_kalem, int(alan_g * 0.38), maks_satir=2)
            ky = sy1 + (satir_h - len(k_satir) * 34) // 2
            for ks in k_satir:
                ciz.text((kenar + 24, ky), ks, font=f_kalem, fill=(255, 255, 255) if hero else (241, 245, 249))
                ky += 34

        orta_y = sy1 + (satir_h - 34) // 2

        # Orta: Eski değer + strikethrough efekti
        eski_w = int(ciz.textlength(eski_deger[:14], font=f_eski))
        ciz.text((eski_x, orta_y + 3), eski_deger[:14], font=f_eski, fill=(148, 163, 184))
        if eski_deger != "—":
            ciz.line([(eski_x, orta_y + 17), (eski_x + eski_w, orta_y + 17)], fill=(148, 163, 184, 160), width=2)

        # Parlayan geçiş oku
        ok_x = yeni_x - 34
        ciz.text((ok_x, orta_y + 2), "➔", font=f_ok, fill=(226, 170, 88) if hero else (6, 182, 212))

        # Sağ: Yeni değer
        ciz.text((yeni_x, orta_y - 2), yeni_deger[:14], font=f_yeni, fill=(255, 255, 255))

        # En sağ: Değişim rozeti (Yön İkonlu & Akıllı Renkli)
        if degisim:
            is_neg = degisim.startswith("-") or "düşüş" in degisim.casefold() or "indirim" in degisim.casefold()
            is_pos = degisim.startswith("+") or "artış" in degisim.casefold() or "zam" in degisim.casefold()

            if is_neg and not degisim.startswith("▼"):
                degisim_gosterim = f"▼ {degisim}"
            elif is_pos and not degisim.startswith("▲"):
                degisim_gosterim = f"▲ {degisim}"
            else:
                degisim_gosterim = degisim

            if faiz_veya_indirim and is_neg:
                d_renk = (6, 182, 212)    # Siber Turkuaz (Faiz indirimi / gevşeme)
            elif zam_veya_vergi and is_neg:
                d_renk = (16, 185, 129)   # Zümrüt Yeşili (İndirim tüketiciye iyi)
            elif zam_veya_vergi and is_pos:
                d_renk = (239, 68, 68)    # Mercan Kırmızı (Zam / Fiyat artışı)
            elif is_neg:
                d_renk = (6, 182, 212)
            else:
                d_renk = (16, 185, 129)

            dw = int(ciz.textlength(degisim_gosterim[:15], font=f_deg)) + 26
            dh = 44 if adet <= 3 else 38
            dx1 = genislik - kenar - dw - 20
            dy1 = sy1 + (satir_h - dh) // 2
            ciz.rounded_rectangle(
                [dx1, dy1, dx1 + dw, dy1 + dh],
                radius=12,
                fill=(*d_renk, 42),
                outline=(*d_renk, 130),
                width=1,
            )
            ciz.text((dx1 + 13, dy1 + 7), degisim_gosterim[:15], font=f_deg, fill=d_renk)

    y += adet * satir_h + max(0, adet - 1) * gap + 20

    # --- 4. ALT BİLGİ / YÜRÜRLÜK NOTU (Kompakt ve 💡 EDİTÖR NOTU Çipli) ---
    if not_satirlar and alt_not_h > 0 and y + alt_not_h <= y_alt + 30:
        gorsel = cam_kart_ciz(
            gorsel,
            (kenar, y, genislik - kenar, y + alt_not_h),
            dolgu=(10, 28, 36, 232),
            kenarlik=(16, 185, 129, 95),
            yaricap=16,
            sol_centik=(16, 185, 129),
        )
        ciz = ImageDraw.Draw(gorsel, "RGBA")
        f_cip = make_image._font(17, make_image.EKSEN_BASLIK)
        cip_metin = "💡 EDİTÖR NOTU"
        cip_w = int(ciz.textlength(cip_metin, font=f_cip)) + 18
        cip_h = 24
        ciz.rounded_rectangle(
            [kenar + 24, y + 12, kenar + 24 + cip_w, y + 12 + cip_h],
            radius=6,
            fill=(16, 185, 129, 45),
            outline=(16, 185, 129, 120),
            width=1,
        )
        ciz.text((kenar + 33, y + 15), cip_metin, font=f_cip, fill=(16, 185, 129))

        ny = y + 12 + cip_h + 8
        for ns in not_satirlar:
            ciz.text((kenar + 24, ny), ns, font=f_not, fill=(220, 252, 231))
            ny += 30

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
