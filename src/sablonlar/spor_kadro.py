"""
spor_kadro.py — Spor haberleri için "Maç Kadrosu / İlk 11 / Taktik Sahası & Yedekler" detay şablonu.

1080x1920 tuvalde (STORY_GUVENLI_PAY = 330 merkezi 4:5 güvenli alanında):
  - Üstte Maç Bilgi Bannerı (Lig/Turnuva, Ev Sahibi vs Deplasman, Saat/Skor Rozeti, Stat, Hakem & Yayın)
  - Ortada Çift Sütun İlk 11 Taktik Kartları (Ev & Deplasman yan yana veya tek takım 2 sütun)
  - Gerçek Forma Numaraları, Kaptan [K] ve Kaleci [KL] rozetleri (KATI KURAL: K ve KL rozetleri satırın EN SAĞINDA yer alır)
  - Teknik Direktör & Formasyon (4-2-3-1, 4-3-3 vb.) rozetleri
  - Altta İki Takımın Tam Yedek Kulübesi (Substitutes) Paneli
  - En Altta Sakat/Cezalı & Maç Önü Önemli Notlar şeridi
  - %100 Çakışma, Taşma ve Eksik Karakter (Missing Glyph) Korumalı Akıllı Tipografi
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
    Kaptan ve kaleci etiketleri isimden tamamen temizlenir ve satırın sonunda/en sağında çizilir.
    """
    if isinstance(ham, dict):
        ad = str(ham.get("ad") or ham.get("isim") or "").strip()
        no = str(ham.get("no") or ham.get("numara") or sira).strip()
        rol = str(ham.get("rol") or "").strip().upper()
        kaptan = "K" in rol or "C" in rol or bool(ham.get("kaptan"))
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

    # Kaptan ve kaleci etiketlerini isimden tamamen arındır
    txt = re.sub(r"[\(\[\{]\s*(?:K|C|KL|GK|KAPTAN|KALEC[İI])\s*[\)\]\}]", "", txt, flags=re.I)
    txt = txt.strip(" -:·•,")
    return {"no": no, "ad": txt, "kaptan": kaptan, "kaleci": kaleci}


def _yedekleri_coz(ham: list | str | None) -> list[dict]:
    """Yedek kulübesi verisini güvenle ayrıştırır (liste veya virgüllü metin)."""
    if not ham:
        return []
    if isinstance(ham, str):
        parcalar = [p.strip() for p in re.split(r"[,;\n•·]", ham) if p.strip()]
    else:
        parcalar = list(ham)
    sonuc = []
    for i, p in enumerate(parcalar, start=1):
        parsed = _oyuncu_coz(p, i)
        if parsed["ad"]:
            sonuc.append(parsed)
    return sonuc


def _ad_akilli_sigdir(ciz: ImageDraw.Draw, tam_ad: str, font, max_gen: int) -> str:
    """
    Uzun oyuncu isimlerini estetik broadcast standardında sütuna sığdırır:
      "Trent Alexander-Arnold" -> "T. Alexander-Arnold"
      "Pierre-Emerick Aubameyang" -> "P. Aubameyang"
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
    return ad + "…" if ad else tam_ad[:14]


def _takim_adi_sigdir(ciz: ImageDraw.Draw, ham_ad: str, max_gen: int) -> tuple[str, any]:
    """
    Takım adını font puntosunu adaptif küçülterek (32 -> 28 -> 24 -> 20) ortadaki
    VS/Skor rozetine çarpmayacak şekilde sığdırır.
    """
    ad = make_image._buyuk_harf(ham_ad.strip())
    for punto in (32, 28, 24, 21):
        f = make_image._font(punto, make_image.EKSEN_BASLIK)
        if ciz.textlength(ad, font=f) <= max_gen:
            return ad, f
    f = make_image._font(19, make_image.EKSEN_BASLIK)
    while ad and ciz.textlength(ad + "…", font=f) > max_gen:
        ad = ad[:-1].rstrip()
    return (ad + "…" if ad else ham_ad[:14]), f


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
    `veri` sözlüğünden İlk 11, Yedek Kulübesi ve Maç Detayları infografik slaytını (1080x1920) üretir.
    Yeterli oyuncu verisi yoksa `None` döner (standart editoryal metin slaytına düşer).
    """
    ev_ad = (veri.get("ev_sahibi") or veri.get("takim_1") or "").strip()
    dep_ad = (veri.get("deplasman") or veri.get("takim_2") or "").strip()
    ev_kadro = [
        str(x).strip()
        for x in (
            veri.get("ev_kadro")
            or veri.get("ev_sahibi_kadro")
            or veri.get("ev_11")
            or veri.get("kadro_1")
            or []
        )
        if str(x).strip()
    ]
    dep_kadro = [
        str(x).strip()
        for x in (
            veri.get("deplasman_kadro")
            or veri.get("dep_kadro")
            or veri.get("dep_11")
            or veri.get("kadro_2")
            or []
        )
        if str(x).strip()
    ]

    if len(ev_kadro) < 5 and len(dep_kadro) < 5:
        return None

    ev_yedekler = _yedekleri_coz(veri.get("ev_yedekler") or veri.get("ev_kulube"))
    dep_yedekler = _yedekleri_coz(veri.get("deplasman_yedekler") or veri.get("dep_yedekler") or veri.get("dep_kulube"))

    gorsel, kenar, dikey_kenar, y_ust, y_alt = temel_tuval_olustur(
        ayarlar,
        kategori=haber.get("kategori") or "spor",
        arkaplan=arkaplan,
        tema_alt_renk=(3, 18, 16),
    )
    genislik = make_image.STORY_GENISLIK
    alan_g = genislik - 2 * kenar
    y = y_ust + 6

    # =========================================================================
    # 1. ÜST MAÇ SKOR / KARŞILAŞMA KARTI (MATCH HEADER)
    # =========================================================================
    turnuva = (veri.get("turnuva") or veri.get("lig") or "KARŞILAŞMA").strip().upper()
    mac_bilgi = (
        veri.get("mac_bilgisi")
        or veri.get("stat_hakem")
        or veri.get("stadyum_saat")
        or ""
    ).strip()
    skor_saat = (veri.get("skor_veya_saat") or veri.get("saat") or "VS").strip()

    kart_ust_h = 138 if mac_bilgi else 108
    gorsel = cam_kart_ciz(
        gorsel,
        (kenar, y, genislik - kenar, y + kart_ust_h),
        dolgu=(6, 26, 22, 238),
        kenarlik=(16, 185, 129, 90),
        yaricap=20,
    )
    ciz = ImageDraw.Draw(gorsel, "RGBA")

    # Turnuva / Lig rozeti (üst merkez)
    f_tur = make_image._font(17, make_image.EKSEN_BASLIK)
    tur_w = ciz.textlength(turnuva, font=f_tur)
    ciz.rounded_rectangle(
        [(genislik - tur_w) / 2 - 14, y + 10, (genislik + tur_w) / 2 + 14, y + 32],
        radius=6,
        fill=(16, 185, 129, 35),
        outline=(16, 185, 129, 90),
        width=1,
    )
    ciz.text(((genislik - tur_w) / 2, y + 12), turnuva, font=f_tur, fill=(167, 243, 208))

    # Ortada Skor / Saat Rozeti
    f_vs = make_image._font(26, make_image.EKSEN_BASLIK)
    vs_metin_w = int(ciz.textlength(skor_saat, font=f_vs))
    vs_g = max(90, vs_metin_w + 32)
    vs_x1 = (genislik - vs_g) // 2
    vs_x2 = vs_x1 + vs_g
    vs_y1 = y + 42
    vs_y2 = vs_y1 + 44

    ciz.rounded_rectangle([vs_x1, vs_y1, vs_x2, vs_y2], radius=12, fill=(16, 185, 129))
    ciz.text(((genislik - vs_metin_w) / 2, vs_y1 + 9), skor_saat, font=f_vs, fill=(3, 18, 14))

    # Takım isimleri (VS rozetine çarpmayı kesin önler)
    azami_takim_g = (vs_x1 - (kenar + 24)) - 14

    if ev_ad and dep_ad:
        ev_ad_ciz, f_ev = _takim_adi_sigdir(ciz, ev_ad, azami_takim_g)
        dep_ad_ciz, f_dep = _takim_adi_sigdir(ciz, dep_ad, azami_takim_g)

        # Ev Sahibi (Kehribar vurgulu nokta)
        ciz.ellipse([kenar + 22, vs_y1 + 16, kenar + 32, vs_y1 + 26], fill=(226, 170, 88))
        ciz.text((kenar + 40, vs_y1 + 6), ev_ad_ciz, font=f_ev, fill=(255, 255, 255))

        # Deplasman (Turkuaz vurgulu nokta)
        dep_w = ciz.textlength(dep_ad_ciz, font=f_dep)
        ciz.ellipse([genislik - kenar - 32, vs_y1 + 16, genislik - kenar - 22, vs_y1 + 26], fill=(6, 182, 212))
        ciz.text((genislik - kenar - 40 - dep_w, vs_y1 + 6), dep_ad_ciz, font=f_dep, fill=(255, 255, 255))
    else:
        tek_ad = make_image._buyuk_harf((ev_ad or dep_ad or "İLK 11 KADROSU"))
        tek_ciz, f_tek = _takim_adi_sigdir(ciz, tek_ad, alan_g - 48)
        ciz.text((kenar + 24, vs_y1 + 6), tek_ciz, font=f_tek, fill=(255, 255, 255))

    # Maç Meta Bilgisi (Stat, Hakem, Yayın vb.)
    if mac_bilgi:
        ciz.line([kenar + 20, y + 96, genislik - kenar - 20, y + 96], fill=(255, 255, 255, 20), width=1)
        f_meta = make_image._font(19, make_image.EKSEN_KUCUK)
        mb_satir = metin_kutuya_sar(ciz, mac_bilgi, f_meta, alan_g - 40, maks_satir=1)
        if mb_satir:
            mb_w = ciz.textlength(mb_satir[0], font=f_meta)
            ciz.text(((genislik - mb_w) / 2, y + 106), mb_satir[0], font=f_meta, fill=(167, 243, 208))

    y += kart_ust_h + 14

    # =========================================================================
    # 2. SAHA İÇİ İLK 11 LİSTESİ (İKİ SÜTUN VEYA TEK TAKIM İKİ SÜTUN)
    # =========================================================================
    iki_takim = len(ev_kadro) >= 5 and len(dep_kadro) >= 5
    has_yedek = bool(ev_yedekler or dep_yedekler)
    alt_not = (veri.get("alt_not") or veri.get("eksikler") or "").strip()

    toplam_kalan = y_alt - y
    alt_not_h = 96 if alt_not else 0
    yedek_h = 220 if has_yedek else 0
    saha_yuk = toplam_kalan - alt_not_h - (yedek_h + (12 if has_yedek else 0)) - (12 if alt_not else 0)
    saha_yuk = max(460, min(560, saha_yuk))

    sutun_arasi = 16
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
        sol_renk = (226, 170, 88)   # Kehribar (Ev Sahibi)
        sag_renk = (6, 182, 212)    # Siber Turkuaz (Deplasman)
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
            dolgu=(7, 24, 21, 232),
            kenarlik=(*vurgu_renk, 85),
            yaricap=18,
            sol_centik=vurgu_renk,
        )
        ciz = ImageDraw.Draw(gorsel, "RGBA")

        # Sütun Başlığı + Diziliş Rozeti
        f_sbas = make_image._font(22, make_image.EKSEN_BASLIK)
        f_sdiz = make_image._font(18, make_image.EKSEN_BASLIK)

        diz_w = (int(ciz.textlength(s_diz, font=f_sdiz)) + 18) if s_diz else 0
        max_baslik_g = sutun_g - (diz_w + 34)
        bas_kisalt = metin_kutuya_sar(ciz, s_baslik, f_sbas, max_baslik_g, maks_satir=1)
        ciz.text((sx1 + 18, y + 14), bas_kisalt[0] if bas_kisalt else s_baslik[:14], font=f_sbas, fill=vurgu_renk)

        if s_diz:
            ciz.rounded_rectangle(
                [sx2 - diz_w - 12, y + 12, sx2 - 12, y + 38],
                radius=6,
                fill=(*vurgu_renk, 30),
                outline=(*vurgu_renk, 110),
                width=1,
            )
            ciz.text((sx2 - diz_w - 3, y + 15), s_diz, font=f_sdiz, fill=(241, 245, 249))

        # Teknik Direktör (Eksik glif / emoji kutusu olmadan temiz metin)
        oy_y = y + 46
        if s_td:
            f_td = make_image._font(17, make_image.EKSEN_KUCUK)
            td_metin = f"TD: {s_td}"
            td_kisalt = metin_kutuya_sar(ciz, td_metin, f_td, sutun_g - 36, maks_satir=1)
            ciz.text((sx1 + 18, oy_y), td_kisalt[0] if td_kisalt else td_metin[:24], font=f_td, fill=(160, 180, 195))
            oy_y += 26

        # İnce ayırıcı çizgi
        ciz.line([sx1 + 14, oy_y, sx2 - 14, oy_y], fill=(255, 255, 255, 20), width=1)
        oy_y += 8

        # Oyuncu satırları
        kalan_h = (y + saha_yuk - 8) - oy_y
        adet = max(1, len(oyuncular))
        satir_h = min(46, max(36, kalan_h // adet))
        f_oy = make_image._font(21 if adet <= 11 else 19, make_image.EKSEN_OZET)
        f_no = make_image._font(17, make_image.EKSEN_BASLIK)
        f_badge = make_image._font(14, make_image.EKSEN_BASLIK)

        for o_i, ham_oyuncu in enumerate(oyuncular):
            p = _oyuncu_coz(ham_oyuncu, bas_no + o_i)

            # Zebra satır
            if o_i % 2 == 1:
                ciz.rounded_rectangle(
                    [sx1 + 8, oy_y, sx2 - 8, oy_y + satir_h - 4],
                    radius=6,
                    fill=(255, 255, 255, 5),
                )

            # Forma numarası rozeti (solda)
            ciz.rounded_rectangle(
                [sx1 + 14, oy_y + 3, sx1 + 46, oy_y + 29],
                radius=6,
                fill=(*vurgu_renk, 35),
                outline=(*vurgu_renk, 120),
                width=1,
            )
            nw = ciz.textlength(p["no"], font=f_no)
            ciz.text((sx1 + 30 - nw / 2, oy_y + 6), p["no"], font=f_no, fill=(255, 255, 255))

            # -------------------------------------------------------------
            # KATI KURAL: KL ve K rozetleri SATIRIN EN SAĞINDA YER ALIR
            # İsmin başında ASLA bulunmaz!
            # -------------------------------------------------------------
            sag_sinir = sx2 - 14

            # Kaptan Rozeti (en sağda)
            if p["kaptan"]:
                kp_w = 26
                kp_x = sag_sinir - kp_w
                ciz.rounded_rectangle([kp_x, oy_y + 5, sag_sinir, oy_y + 27], radius=5, fill=(226, 170, 88))
                ciz.text((kp_x + 7, oy_y + 7), "K", font=f_badge, fill=(4, 20, 16))
                sag_sinir = kp_x - 6

            # Kaleci Rozeti (kaptanın solunda veya en sağda)
            if p["kaleci"]:
                kl_w = 34
                kl_x = sag_sinir - kl_w
                ciz.rounded_rectangle([kl_x, oy_y + 5, sag_sinir, oy_y + 27], radius=5, fill=(16, 185, 129))
                ciz.text((kl_x + 6, oy_y + 7), "KL", font=f_badge, fill=(4, 20, 16))
                sag_sinir = kl_x - 6

            # Oyuncu Adı (Forma no ile sağ rozetler arasındaki alanda güvenle sığdırılır)
            isim_x = sx1 + 54
            max_ad_g = sag_sinir - isim_x - 6
            ad_formatli = _ad_akilli_sigdir(ciz, p["ad"], f_oy, max_ad_g)
            ciz.text((isim_x, oy_y + 5), ad_formatli, font=f_oy, fill=(248, 250, 252))

            oy_y += satir_h

    y += saha_yuk + 12

    # =========================================================================
    # 3. YEDEK KULÜBESİ (SUBSTITUTES / BENCH)
    # =========================================================================
    if has_yedek:
        gorsel = cam_kart_ciz(
            gorsel,
            (kenar, y, genislik - kenar, y + yedek_h),
            dolgu=(7, 24, 21, 235),
            kenarlik=(255, 255, 255, 30),
            yaricap=18,
            sol_centik=(16, 185, 129),
        )
        ciz = ImageDraw.Draw(gorsel, "RGBA")

        # Başlık ve Takım Etiketleri
        f_yb = make_image._font(18, make_image.EKSEN_BASLIK)
        f_sub = make_image._font(16, make_image.EKSEN_BASLIK)

        yb_metin = "YEDEK KULÜBESİ"
        yb_w = ciz.textlength(yb_metin, font=f_yb)
        ciz.text(((genislik - yb_w) / 2, y + 10), yb_metin, font=f_yb, fill=(16, 185, 129))

        # Sol takım yedek etiketi
        ciz.text((kenar + 18, y + 11), f"● {sol_baslik[:12]}", font=f_sub, fill=sol_renk)
        # Sağ takım yedek etiketi
        sag_etiket = f"{sag_baslik[:12]} ●"
        sag_e_w = ciz.textlength(sag_etiket, font=f_sub)
        ciz.text((genislik - kenar - 18 - sag_e_w, y + 11), sag_etiket, font=f_sub, fill=sag_renk)

        # İki takım yedek sütunları
        y_icerik_y = y + 36
        ciz.line([genislik // 2, y_icerik_y - 2, genislik // 2, y + yedek_h - 10], fill=(255, 255, 255, 22), width=1)

        f_yedek = make_image._font(16, make_image.EKSEN_OZET)
        f_yno = make_image._font(14, make_image.EKSEN_BASLIK)

        for col_idx, (yedekler, col_x1, col_x2, col_renk) in enumerate([
            (ev_yedekler, kenar + 14, genislik // 2 - 10, sol_renk),
            (dep_yedekler, genislik // 2 + 10, genislik - kenar - 14, sag_renk),
        ]):
            # 2 mini alt-sütuna bölerek 8 yedeği ferah sığdır
            sub_w = (col_x2 - col_x1 - 8) // 2
            for y_i, yp in enumerate(yedekler[:8]):
                sub_col = y_i % 2
                sub_row = y_i // 2
                yx = col_x1 + sub_col * (sub_w + 8)
                yy = y_icerik_y + sub_row * 38

                # Mini numara rozeti
                ciz.rounded_rectangle([yx, yy + 2, yx + 28, yy + 24], radius=4, fill=(*col_renk, 30), outline=(*col_renk, 90), width=1)
                ynw = ciz.textlength(yp["no"], font=f_yno)
                ciz.text((yx + 14 - ynw / 2, yy + 5), yp["no"], font=f_yno, fill=(255, 255, 255))

                # Yedek Oyuncu Adı + (KL) sonda
                ad_txt = yp["ad"]
                if yp["kaleci"]:
                    ad_txt += " (KL)"
                ad_sig = _ad_akilli_sigdir(ciz, ad_txt, f_yedek, sub_w - 34)
                ciz.text((yx + 34, yy + 4), ad_sig, font=f_yedek, fill=(225, 235, 245))

        y += yedek_h + 12

    # =========================================================================
    # 4. ALT BİLGİ / SAKAT-CEZALI & MAÇ NOTU
    # =========================================================================
    if alt_not:
        gorsel = cam_kart_ciz(
            gorsel,
            (kenar, y, genislik - kenar, y_alt),
            dolgu=(10, 30, 26, 230),
            kenarlik=(226, 170, 88, 80),
            yaricap=16,
            sol_centik=(226, 170, 88),
        )
        ciz = ImageDraw.Draw(gorsel, "RGBA")
        f_not = make_image._font(20, make_image.EKSEN_OZET)
        alt_not_temiz = re.sub(r"[\u2600-\u27bf\U0001f300-\U0001f9ff⚠️📌🔴🚨★⭐⚽]", "", alt_not).strip()
        not_satirlar = metin_kutuya_sar(ciz, alt_not_temiz, f_not, alan_g - 40, maks_satir=2)
        ny = y + (y_alt - y - len(not_satirlar) * 26) // 2
        for ns in not_satirlar:
            ciz.text((kenar + 20, ny), ns, font=f_not, fill=(241, 245, 249))
            ny += 26

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
