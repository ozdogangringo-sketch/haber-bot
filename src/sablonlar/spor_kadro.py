"""
spor_kadro.py — Spor haberleri için "Maç Kadrosu / İlk 11 / Taktik Sahası" detay şablonu.

1080x1920 tuvalde (STORY_GUVENLI_PAY = 330 merkezi 4:5 güvenli alanında):
  - Üstte Maç Bilgi Barı (Ev Sahibi vs Deplasman, Saat/Skor Rozeti, Stat & Hakem)
  - Ortada Çim Çizgili Taktik Tahtası Kartları (Ev & Deplasman yan yana veya tek takım 2 sütun)
  - Gerçek Forma Numaraları, Kaptan [K] ve Kaleci [KL] rozetleri
  - Teknik Direktör & Formasyon (4-2-3-1, 4-3-3 vb.) şık rozetleri
  - Altta Sakat/Cezalı & Maç Önü Önemli Notlar şeridi
  - %100 Çakışma ve Taşma Korumalı Akıllı Tipografi
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


def _oyuncu_coz(ham: str | dict, sira: int) -> dict:
    """
    Ham oyuncu verisini ayrıştırır: forma numarası, isim, kaptan ve kaleci rozetleri.
    Örnekler:
      "1 Fernando Muslera (K)" -> no="1", ad="Fernando Muslera", kaptan=True, kaleci=False
      "Livakovic (KL)"         -> no=sira, ad="Livakovic", kaptan=False, kaleci=True
      {"no": 45, "ad": "Osimhen", "kaptan": False} -> doğrudan dict
    """
    if isinstance(ham, dict):
        ad = str(ham.get("ad") or ham.get("isim") or "").strip()
        no = str(ham.get("no") or ham.get("numara") or sira).strip()
        rol = str(ham.get("rol") or "").strip().upper()
        kaptan = "K" in rol or bool(ham.get("kaptan"))
        kaleci = "KL" in rol or "GK" in rol or bool(ham.get("kaleci"))
        return {"no": no, "ad": ad, "kaptan": kaptan, "kaleci": kaleci}

    txt = str(ham).strip()
    kaptan = bool(re.search(r"[\(\[\{]\s*[KC]\s*[\)\]\}]|\bKAPTAN\b", txt, re.I))
    kaleci = bool(re.search(r"[\(\[\{]\s*(?:KL|GK)\s*[\)\]\}]|\bKALEC[İI]\b", txt, re.I))

    # Başta forma numarası var mı? (örn. "1 -", "1.", "#1", "23")
    no = str(sira)
    m_no = re.match(r"^#?(\d{1,2})[\s\.\-\:)]+(.*)", txt)
    if m_no:
        no = m_no.group(1)
        txt = m_no.group(2).strip()

    # Kaptan ve kaleci etiketlerini isimden arındır
    txt = re.sub(r"[\(\[\{]\s*(?:K|C|KL|GK|KAPTAN|KALEC[İI])\s*[\)\]\}]", "", txt, flags=re.I)
    txt = txt.strip(" -:·•,")
    return {"no": no, "ad": txt, "kaptan": kaptan, "kaleci": kaleci}


def _ad_akilli_sigdir(ciz: ImageDraw.Draw, tam_ad: str, font, max_gen: int) -> str:
    """
    Uzun oyuncu isimlerini estetik broadcast standardında sütuna sığdırır:
      "Trent Alexander-Arnold" -> "T. Alexander-Arnold"
      "Dominik Szoboszlai" -> sığıyorsa tam kalır
      Sığmazsa son çare taşmayan kelimeden sonra "…" ekler.
    """
    if ciz.textlength(tam_ad, font=font) <= max_gen:
        return tam_ad

    parcalar = tam_ad.split()
    if len(parcalar) >= 2:
        kalan = " ".join(parcalar[1:])
        kisaltma = f"{parcalar[0][0]}. {kalan}"
        if ciz.textlength(kisaltma, font=font) <= max_gen:
            return kisaltma
        if len(parcalar) >= 3:
            kalan2 = " ".join(parcalar[2:])
            kisaltma2 = f"{parcalar[0][0]}. {parcalar[1][0]}. {kalan2}"
            if ciz.textlength(kisaltma2, font=font) <= max_gen:
                return kisaltma2

    ad = tam_ad
    while ad and ciz.textlength(ad + "…", font=font) > max_gen:
        ad = ad[:-1].rstrip()
    return ad + "…" if ad else tam_ad[:16]


def _takim_adi_sigdir(ciz: ImageDraw.Draw, ham_ad: str, max_gen: int) -> tuple[str, any]:
    """
    Takım adını font puntosunu adaptif küçülterek (34 -> 30 -> 26 -> 22) ortadaki
    VS/Skor rozetine çarpmayacak şekilde sığdırır.
    """
    ad = make_image._buyuk_harf(ham_ad.strip())
    for punto in (34, 30, 26, 22):
        f = make_image._font(punto, make_image.EKSEN_BASLIK)
        if ciz.textlength(ad, font=f) <= max_gen:
            return ad, f
    f = make_image._font(20, make_image.EKSEN_BASLIK)
    while ad and ciz.textlength(ad + "…", font=f) > max_gen:
        ad = ad[:-1].rstrip()
    return (ad + "…" if ad else ham_ad[:16]), f


def spor_kadro_slayti_ciz(
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
    `veri` sözlüğünden İlk 11 / Maç Kadrosu infografik slaytı üretir.
    Yeterli oyuncu verisi yoksa `None` döner (standart detay slaytına düşer).
    """
    ev_ad = (veri.get("ev_sahibi") or veri.get("takim_1") or "").strip()
    dep_ad = (veri.get("deplasman") or veri.get("takim_2") or "").strip()
    ev_kadro = [
        str(x).strip()
        for x in (veri.get("ev_kadro") or veri.get("ev_11") or veri.get("kadro_1") or [])
        if str(x).strip()
    ]
    dep_kadro = [
        str(x).strip()
        for x in (veri.get("deplasman_kadro") or veri.get("dep_11") or veri.get("kadro_2") or [])
        if str(x).strip()
    ]

    if len(ev_kadro) < 5 and len(dep_kadro) < 5:
        return None

    gorsel, kenar, dikey_kenar, y_ust, y_alt = temel_tuval_olustur(
        ayarlar,
        kategori=haber.get("kategori") or "spor",
        arkaplan=arkaplan,
        tema_alt_renk=(4, 22, 18),
    )
    genislik = make_image.STORY_GENISLIK
    alan_g = genislik - 2 * kenar
    y = y_ust + 8

    # --- 1. ÜST MAÇ SKOR / KARŞILAŞMA KARTI ---
    mac_bilgi = (
        veri.get("mac_bilgisi")
        or veri.get("stat_hakem")
        or veri.get("stadyum_saat")
        or veri.get("turnuva")
        or ""
    ).strip()
    skor_saat = (veri.get("skor_veya_saat") or veri.get("saat") or "VS").strip()

    kart_ust_h = 146 if mac_bilgi else 114
    gorsel = cam_kart_ciz(
        gorsel,
        (kenar, y, genislik - kenar, y + kart_ust_h),
        dolgu=(7, 34, 29, 235),
        kenarlik=(16, 185, 129, 100),
        yaricap=22,
    )
    ciz = ImageDraw.Draw(gorsel, "RGBA")

    f_vs = make_image._font(26, make_image.EKSEN_BASLIK)
    f_meta = make_image._font(21, make_image.EKSEN_KUCUK)

    # Ortada saat / skor rozeti
    vs_metin_w = int(ciz.textlength(skor_saat, font=f_vs))
    vs_g = max(96, vs_metin_w + 36)
    vs_x1 = (genislik - vs_g) // 2
    vs_x2 = vs_x1 + vs_g
    vs_y1 = y + 20
    vs_y2 = vs_y1 + 52

    # Rozet arka planı ve iç parıltısı
    ciz.rounded_rectangle([vs_x1, vs_y1, vs_x2, vs_y2], radius=14, fill=(16, 185, 129))
    ciz.rounded_rectangle([vs_x1, vs_y1, vs_x2, vs_y1 + 22], radius=14, fill=(255, 255, 255, 40))
    ciz.text(((genislik - vs_metin_w) / 2, vs_y1 + 12), skor_saat, font=f_vs, fill=(4, 20, 16))

    # Takım isimleri için azami genişlik (VS rozetine çarpmayı kesin önler)
    azami_takim_g = (vs_x1 - (kenar + 28)) - 16

    if ev_ad and dep_ad:
        ev_ad_ciz, f_ev = _takim_adi_sigdir(ciz, ev_ad, azami_takim_g)
        dep_ad_ciz, f_dep = _takim_adi_sigdir(ciz, dep_ad, azami_takim_g)

        # Ev Sahibi (sol tarafta, kehribar vurgulu nokta ile)
        ciz.ellipse([kenar + 26, y + 38, kenar + 34, y + 46], fill=(226, 170, 88))
        ciz.text((kenar + 42, y + 27), ev_ad_ciz, font=f_ev, fill=(255, 255, 255))

        # Deplasman (sağ tarafta, turkuaz vurgulu nokta ile)
        dep_w = ciz.textlength(dep_ad_ciz, font=f_dep)
        ciz.ellipse([genislik - kenar - 34, y + 38, genislik - kenar - 26, y + 46], fill=(6, 182, 212))
        ciz.text((genislik - kenar - 42 - dep_w, y + 27), dep_ad_ciz, font=f_dep, fill=(255, 255, 255))
    else:
        tek_ad = make_image._buyuk_harf((ev_ad or dep_ad or "İLK 11 KADROSU"))
        tek_ciz, f_tek = _takim_adi_sigdir(ciz, tek_ad, alan_g - 56)
        ciz.text((kenar + 28, y + 27), tek_ciz, font=f_tek, fill=(255, 255, 255))

    # Maç Meta Bilgisi (Stat, Hakem, Yayın vb.)
    if mac_bilgi:
        ciz.line([kenar + 24, y + 90, genislik - kenar - 24, y + 90], fill=(255, 255, 255, 28), width=1)
        mb_satir = metin_kutuya_sar(ciz, mac_bilgi, f_meta, alan_g - 48, maks_satir=1)
        if mb_satir:
            mb_w = ciz.textlength(mb_satir[0], font=f_meta)
            ciz.text(((genislik - mb_w) / 2, y + 104), mb_satir[0], font=f_meta, fill=(167, 243, 208))

    y += kart_ust_h + 18

    # --- 2. SAHA İÇİ İLK 11 LİSTESİ (İKİ SÜTUN VEYA TEK TAKIM İKİ SÜTUN) ---
    alt_not = (veri.get("alt_not") or veri.get("eksikler") or "").strip()
    alt_not_pay = 104 if alt_not else 0
    saha_yuk = y_alt - y - alt_not_pay

    iki_takim = len(ev_kadro) >= 5 and len(dep_kadro) >= 5
    sutun_arasi = 18
    sutun_g = (alan_g - sutun_arasi) // 2

    if iki_takim:
        sol_baslik = make_image._buyuk_harf(ev_ad or "EV SAHİBİ")
        sag_baslik = make_image._buyuk_harf(dep_ad or "DEPLASMAN")
        sol_td = (veri.get("ev_td") or "").strip()
        sag_td = (veri.get("deplasman_td") or veri.get("dep_td") or "").strip()
        sol_diz = (veri.get("ev_dizilis") or "").strip()
        sag_diz = (veri.get("deplasman_dizilis") or veri.get("dep_dizilis") or "").strip()
        sol_liste = ev_kadro[:11]
        sag_liste = dep_kadro[:11]
        sol_renk = (226, 170, 88)   # Kehribar
        sag_renk = (6, 182, 212)    # Siber Turkuaz
    else:
        aktif_kadro = ev_kadro if len(ev_kadro) >= 5 else dep_kadro
        yari = (len(aktif_kadro) + 1) // 2
        sol_baslik = "İLK 11 — SAVUNMA & ORTA SAHA"
        sag_baslik = "ORTA SAHA & HÜCUM HATTI"
        sol_td = (veri.get("ev_td") or veri.get("deplasman_td") or "").strip()
        sag_td = ""
        sol_diz = (veri.get("ev_dizilis") or veri.get("deplasman_dizilis") or "").strip()
        sag_diz = ""
        sol_liste = aktif_kadro[:yari]
        sag_liste = aktif_kadro[yari:11]
        sol_renk = (16, 185, 129)
        sag_renk = (16, 185, 129)

    for idx, (s_baslik, s_td, s_diz, oyuncular, vurgu_renk, bas_no) in enumerate([
        (sol_baslik, sol_td, sol_diz, sol_liste, sol_renk, 1),
        (sag_baslik, sag_td, sag_diz, sag_liste, sag_renk, 1 if iki_takim else len(sol_liste) + 1),
    ]):
        sx1 = kenar if idx == 0 else kenar + sutun_g + sutun_arasi
        sx2 = sx1 + sutun_g
        gorsel = cam_kart_ciz(
            gorsel,
            (sx1, y, sx2, y + saha_yuk),
            dolgu=(8, 28, 24, 228),
            kenarlik=(*vurgu_renk, 90),
            yaricap=20,
            sol_centik=vurgu_renk,
        )
        ciz = ImageDraw.Draw(gorsel, "RGBA")

        # Çim Taktik Tahtası Dokusu (Hafif dikey saha şeritleri)
        for serit_x in range(sx1 + 30, sx2 - 30, 48):
            ciz.rectangle([serit_x, y + 8, serit_x + 24, y + saha_yuk - 8], fill=(255, 255, 255, 4))

        # Sütun Başlığı + Diziliş Rozeti
        f_sbas = make_image._font(23, make_image.EKSEN_BASLIK)
        f_sdiz = make_image._font(19, make_image.EKSEN_BASLIK)

        diz_w = (int(ciz.textlength(s_diz, font=f_sdiz)) + 22) if s_diz else 0
        max_baslik_g = sutun_g - (diz_w + 38)
        bas_kisalt = metin_kutuya_sar(ciz, s_baslik, f_sbas, max_baslik_g, maks_satir=1)
        ciz.text((sx1 + 20, y + 16), bas_kisalt[0] if bas_kisalt else s_baslik[:16], font=f_sbas, fill=vurgu_renk)

        if s_diz:
            ciz.rounded_rectangle(
                [sx2 - diz_w - 14, y + 14, sx2 - 14, y + 44],
                radius=8,
                fill=(*vurgu_renk, 35),
                outline=(*vurgu_renk, 110),
                width=1,
            )
            ciz.text((sx2 - diz_w - 3, y + 18), s_diz, font=f_sdiz, fill=(241, 245, 249))

        oy_y = y + 54
        if s_td:
            f_td = make_image._font(19, make_image.EKSEN_KUCUK)
            td_metin = f"👔 TD: {s_td}"
            td_kisalt = metin_kutuya_sar(ciz, td_metin, f_td, sutun_g - 40, maks_satir=1)
            ciz.text((sx1 + 20, oy_y), td_kisalt[0] if td_kisalt else td_metin[:26], font=f_td, fill=(160, 175, 195))
            oy_y += 30

        # İnce ayırıcı çizgi
        ciz.line([sx1 + 16, oy_y, sx2 - 16, oy_y], fill=(255, 255, 255, 25), width=1)
        oy_y += 10

        # Oyuncu satırları
        kalan_h = (y + saha_yuk - 12) - oy_y
        adet = max(1, len(oyuncular))
        satir_h = min(56, max(38, kalan_h // adet))
        f_oy = make_image._font(23 if adet <= 11 else 21, make_image.EKSEN_OZET)
        f_no = make_image._font(19, make_image.EKSEN_BASLIK)
        f_rol = make_image._font(15, make_image.EKSEN_BASLIK)

        for o_i, ham_oyuncu in enumerate(oyuncular):
            p = _oyuncu_coz(ham_oyuncu, bas_no + o_i)

            # Çift satırlarda hafif cam aydınlatması (zebra satır)
            if o_i % 2 == 1:
                ciz.rounded_rectangle(
                    [sx1 + 10, oy_y, sx2 - 10, oy_y + satir_h - 4],
                    radius=8,
                    fill=(255, 255, 255, 6),
                )

            # Forma numarası rozeti (36x30 px)
            ciz.rounded_rectangle(
                [sx1 + 16, oy_y + 4, sx1 + 52, oy_y + 34],
                radius=8,
                fill=(*vurgu_renk, 45),
                outline=(*vurgu_renk, 130),
                width=1,
            )
            nw = ciz.textlength(p["no"], font=f_no)
            ciz.text((sx1 + 34 - nw / 2, oy_y + 7), p["no"], font=f_no, fill=(255, 255, 255))

            # Kaleci veya Kaptan rozeti
            isim_x = sx1 + 62
            if p["kaleci"]:
                kl_w = int(ciz.textlength("KL", font=f_rol)) + 12
                ciz.rounded_rectangle([isim_x, oy_y + 7, isim_x + kl_w, oy_y + 31], radius=6, fill=(16, 185, 129))
                ciz.text((isim_x + 6, oy_y + 9), "KL", font=f_rol, fill=(4, 20, 16))
                isim_x += kl_w + 8
            elif p["kaptan"]:
                kp_w = int(ciz.textlength("K", font=f_rol)) + 12
                ciz.rounded_rectangle([isim_x, oy_y + 7, isim_x + kp_w, oy_y + 31], radius=6, fill=(226, 170, 88))
                ciz.text((isim_x + 6, oy_y + 9), "K", font=f_rol, fill=(4, 20, 16))
                isim_x += kp_w + 8

            # Oyuncu Adı (Akıllı Kısaltma ve Sütun Koruma)
            max_ad_g = sx2 - isim_x - 14
            ad_formatli = _ad_akilli_sigdir(ciz, p["ad"], f_oy, max_ad_g)
            ciz.text((isim_x, oy_y + 6), ad_formatli, font=f_oy, fill=(248, 250, 252))

            oy_y += satir_h

    y += saha_yuk + 16

    # --- 3. ALT BİLGİ / EKSİKLER NOTU ---
    if alt_not:
        gorsel = cam_kart_ciz(
            gorsel,
            (kenar, y, genislik - kenar, y_alt),
            dolgu=(13, 34, 30, 230),
            kenarlik=(226, 170, 88, 85),
            yaricap=16,
            sol_centik=(226, 170, 88),
        )
        ciz = ImageDraw.Draw(gorsel, "RGBA")
        f_not = make_image._font(22, make_image.EKSEN_OZET)
        not_satirlar = metin_kutuya_sar(ciz, alt_not, f_not, alan_g - 44, maks_satir=2)
        ny = y + (90 - len(not_satirlar) * 28) // 2
        for ns in not_satirlar:
            ciz.text((kenar + 22, ny), ns, font=f_not, fill=(241, 245, 249))
            ny += 28

    return ust_ve_alt_bar_bas(
        gorsel,
        ayarlar=ayarlar,
        kaynak=kaynak,
        rozet_metni="MAÇ KADROLARI & İLK 11",
        rozet_renk=(16, 185, 129),
        ulke_kodu=haber.get("ulke_kodu") or None,
        ulke_adi=haber.get("ulke_adi") or None,
        sayfa=sayfa,
        toplam_sayfa=toplam_sayfa,
        arsiv_ibaresi=arsiv_ibaresi,
    )
