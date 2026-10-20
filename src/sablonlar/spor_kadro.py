"""
spor_kadro.py — Spor haberleri için "Maç Kadrosu / İlk 11 / Taktik Sahası & Yedekler" detay şablonu.

Claude Design & Anti-Slop İlkeleri:
  - Canlı stadyum projektörleri ve derin zümrüt çim zemin dokusu (stadyum_zemini_olustur)
  - Skorboard bannerında kulüplerin 42x42 şeffaf logoları (fetch_kulup_logo)
  - Parçalanmış küçük kutu tarlası yerine TEK BİRLEŞİK MİMARİ TAKTİK SAHNE (Frosted Glass)
  - Tabular (sağa hizalı) forma numarası sütunu — tüm oyuncu isimleri milimetrik aynı eksende başlar
  - Kaptan [K] ve Kaleci [KL] rozetleri satırın EN SAĞINDA yer alır; isme asla çarpmaz
  - Zarif santra dairesi ve saha ayrım dokusu
  - Kulübe (Yedekler) rafı: Temiz 2 sütunlu (toplam 4 sütun) editoryal akış
  - 1080x1920 tuvalde merkezi 4:5 (STORY_GUVENLI_PAY = 330) güvenli alanında sıfır taşma garantisi
"""

from __future__ import annotations

import re
from PIL import Image, ImageDraw, ImageFilter

from src import make_image, fetch_kulup_logo
from src.sablonlar.ortak import ust_ve_alt_bar_bas, metin_kutuya_sar
from src.sablonlar.spor_kapak import stadyum_zemini_olustur


def _oyuncu_coz(ham: str | dict, sira: int) -> dict:
    """
    Ham oyuncu verisini ayrıştırır: forma numarası, isim, kaptan ve kaleci rozetleri.
    Kaptan ve kaleci etiketleri isimden tamamen temizlenir ve satırın en sağında çizilir.
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
    """Takım adını puntoları adaptif küçülterek skor rozetine çarpmayacak şekilde sığdırır."""
    ad = make_image._buyuk_harf(ham_ad.strip())
    for punto in (28, 25, 22, 19):
        f = make_image._font(punto, make_image.EKSEN_BASLIK)
        if ciz.textlength(ad, font=f) <= max_gen:
            return ad, f
    f = make_image._font(18, make_image.EKSEN_BASLIK)
    while ad and ciz.textlength(ad + "…", font=f) > max_gen:
        ad = ad[:-1].rstrip()
    return (ad + "…" if ad else ham_ad[:14]), f


def spor_kadro_slayti_ciz(
    haber: dict,
    veri: dict,
    ayarlar: dict,
    kaynak: str,
    arkaplan: Image.Image | None = None,
    sayfa: int = 2,
    toplam_sayfa: int = 2,
    arsiv_ibaresi: bool = False,
) -> Image.Image | None:
    """
    Canlı stadyum aydınlatmalı, kulüp armalı skorboardlu, İlk 11, Taktik Sahne
    ve Yedek Kulübesi infografik detay slaytını (1080x1920) üretir.
    Dark Slate Glass paleti ve 4:5 Safe Area (y_ust >= 505) standartlarına tam uyar.
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

    genislik = make_image.STORY_GENISLIK
    yukseklik = make_image.STORY_YUKSEKLIK
    kenar = 64
    dikey_kenar = make_image.STORY_GUVENLI_PAY  # 330
    alt_bilgi_y = yukseklik - dikey_kenar - 34
    y_alt = alt_bilgi_y - 20

    # ⚠️ KATI GÜVENLİ ALAN KURALI:
    # Daily Brief 3D logosu Y=330'da başlar, 144px boyutuyla Y=484'te biter.
    # Content ASLA 505'ten önce başlayamaz (sıfır çakışma garantisi).
    y_ust = dikey_kenar + 175  # = 505 px

    # 1. TEMEL TUVAL — Monokrom Lüks Siyah & Krom
    gorsel = Image.new("RGB", (genislik, yukseklik), (8, 8, 10))
    z_draw_k = ImageDraw.Draw(gorsel)
    for y_idx in range(yukseklik):
        oran = y_idx / yukseklik
        r = int(14 + (6 - 14) * oran)
        g = int(14 + (6 - 14) * oran)
        b = int(18 + (8 - 18) * oran)
        z_draw_k.line([(0, y_idx), (genislik, y_idx)], fill=(r, g, b))

    # Platin ışıltı
    isik_k = Image.new("RGBA", (genislik, yukseklik), (0, 0, 0, 0))
    ik_draw = ImageDraw.Draw(isik_k)
    ik_draw.ellipse([genislik // 2 - 380, 400, genislik // 2 + 380, 1100], fill=(255, 255, 255, 18))
    gorsel = Image.alpha_composite(gorsel.convert("RGBA"), isik_k.filter(ImageFilter.GaussianBlur(90))).convert("RGB")

    ciz = ImageDraw.Draw(gorsel, "RGBA")

    alan_w = genislik - 2 * kenar
    y = y_ust

    alt_not = (veri.get("alt_not") or veri.get("eksikler") or "").strip()

    # =========================================================================
    # BÖLÜM 1: MAÇ SKORBOARD BANNERI (NET OKUNAN KRİSTAL BAŞLIK VE LOGOLAR)
    # =========================================================================
    banner_h = 120
    ciz.rounded_rectangle([kenar, y, genislik - kenar, y + banner_h], radius=16, fill=(14, 14, 18, 245), outline=(255, 255, 255, 45), width=1)
    ciz.rounded_rectangle([kenar + 16, y + 1, genislik - kenar - 16, y + 2], radius=1, fill=(255, 255, 255, 90))

    # Turnuva / Lig Kapsülü (Net, parlak ve yüksek kontrastlı)
    turnuva = (veri.get("turnuva") or veri.get("lig") or "KARŞILAŞMA").strip().upper()
    f_lig = make_image._font(16, make_image.EKSEN_BASLIK)
    lig_w = ciz.textlength(turnuva, font=f_lig)
    ciz.rounded_rectangle([(genislik - lig_w) / 2 - 16, y + 10, (genislik + lig_w) / 2 + 16, y + 32], radius=11, fill=(255, 255, 255, 25), outline=(255, 255, 255, 70), width=1)
    ciz.text(((genislik - lig_w) / 2, y + 12), turnuva, font=f_lig, fill=(255, 255, 255))

    # Ortada Karşılaşma Saati / Skor Rozeti
    skor_saat = (veri.get("skor_veya_saat") or veri.get("saat") or "20:00").strip()
    f_saat = make_image._font(24, make_image.EKSEN_BASLIK)
    saat_w = ciz.textlength(skor_saat, font=f_saat)
    rw = max(96, int(saat_w + 28))
    rx1 = (genislik - rw) // 2
    rx2 = rx1 + rw
    ry1 = y + 38
    ry2 = ry1 + 38

    ciz.rounded_rectangle([rx1, ry1, rx2, ry2], radius=10, fill=(255, 255, 255, 30), outline=(255, 255, 255, 120), width=1)
    ciz.text(((genislik - saat_w) / 2, ry1 + 7), skor_saat, font=f_saat, fill=(255, 255, 255))

    # Kulüp Mini Armaları (38x38 px)
    mini_ev_logo = fetch_kulup_logo.kulup_logosu_al(ev_ad, boyut=38) if ev_ad else None
    mini_dep_logo = fetch_kulup_logo.kulup_logosu_al(dep_ad, boyut=38) if dep_ad else None

    if ev_ad and dep_ad:
        # Ev Sahibi (Sol)
        ev_sol_x = kenar + 18
        if mini_ev_logo:
            gorsel.paste(mini_ev_logo, (ev_sol_x, ry1), mask=mini_ev_logo)
            ev_ad_x = ev_sol_x + 46
        else:
            ciz.rounded_rectangle([ev_sol_x, ry1 + 6, ev_sol_x + 4, ry1 + 32], radius=2, fill=(255, 255, 255))
            ev_ad_x = ev_sol_x + 14

        azami_takim_g = (rx1 - ev_ad_x) - 14
        ev_ad_ciz, f_ev = _takim_adi_sigdir(ciz, ev_ad, azami_takim_g)
        ciz.text((ev_ad_x, ry1 + 5), ev_ad_ciz, font=f_ev, fill=(255, 255, 255))

        # Deplasman (Sağ)
        dep_sag_x = genislik - kenar - 18
        if mini_dep_logo:
            gorsel.paste(mini_dep_logo, (dep_sag_x - 38, ry1), mask=mini_dep_logo)
            dep_ad_sag_sinir = dep_sag_x - 46
        else:
            ciz.rounded_rectangle([dep_sag_x - 4, ry1 + 6, dep_sag_x, ry1 + 32], radius=2, fill=(203, 213, 225))
            dep_ad_sag_sinir = dep_sag_x - 14

        azami_dep_g = (dep_ad_sag_sinir - rx2) - 14
        dep_ad_ciz, f_dep = _takim_adi_sigdir(ciz, dep_ad, azami_dep_g)
        dep_tw = ciz.textlength(dep_ad_ciz, font=f_dep)
        ciz.text((dep_ad_sag_sinir - dep_tw, ry1 + 5), dep_ad_ciz, font=f_dep, fill=(241, 245, 249))
    else:
        tek_ad = make_image._buyuk_harf((ev_ad or dep_ad or "İLK 11 KADROSU"))
        tek_ciz, f_tek = _takim_adi_sigdir(ciz, tek_ad, alan_w - 48)
        ciz.text((kenar + 24, ry1 + 5), tek_ciz, font=f_tek, fill=(255, 255, 255))

    # Alt satır: Stadyum & Hakem & Yayın
    mac_bilgi = (veri.get("mac_bilgisi") or veri.get("stat_hakem") or veri.get("stadyum_saat") or "").strip()
    if mac_bilgi:
        ciz.line([kenar + 20, y + 84, genislik - kenar - 20, y + 84], fill=(255, 255, 255, 25), width=1)
        f_info = make_image._font(16, make_image.EKSEN_BASLIK)
        info_w = ciz.textlength(mac_bilgi, font=f_info)
        ciz.text(((genislik - info_w) / 2, y + 93), mac_bilgi, font=f_info, fill=(226, 232, 240))

    y += banner_h + 12

    # =========================================================================
    # BÖLÜM 2: TEK PARÇA BİRLEŞİK TAKTİK SAHA KARTI & BOLD FUTBOLCU İSİMLERİ
    # =========================================================================
    iki_takim = len(ev_kadro) >= 5 and len(dep_kadro) >= 5
    has_yedek = bool(ev_yedekler or dep_yedekler)

    kalan_alan = y_alt - y
    alt_not_h = 80 if alt_not else 0
    kulube_h = 150 if has_yedek else 0
    saha_h = kalan_alan - alt_not_h - (kulube_h + (12 if kulube_h else 0)) - (12 if alt_not_h else 0)

    # Ana Birleşik Saha Kutusu (Koyu Monokrom Lüks + İnce Krom Bevel)
    ciz.rounded_rectangle([kenar, y, genislik - kenar, y + saha_h], radius=18, fill=(14, 14, 18, 245), outline=(255, 255, 255, 45), width=1)
    ciz.rounded_rectangle([kenar + 16, y + 1, genislik - kenar - 16, y + 2], radius=1, fill=(255, 255, 255, 80))

    orta_x = genislik // 2

    if iki_takim:
        # Ortadaki Zarif Saha Ayrım Çizgisi ve Santra Dairesi
        ciz.line([orta_x, y + 16, orta_x, y + saha_h - 16], fill=(255, 255, 255, 25), width=1)
        santra_y = y + saha_h // 2
        ciz.ellipse([orta_x - 36, santra_y - 36, orta_x + 36, santra_y + 36], outline=(255, 255, 255, 25), width=1)

        sutun_verileri = [
            (ev_ad, veri.get("ev_dizilis", "4-2-3-1"), veri.get("ev_td", ""), [_oyuncu_coz(x, i + 1) for i, x in enumerate(ev_kadro[:11])], (255, 255, 255), kenar + 16, orta_x - 12),
            (dep_ad, veri.get("dep_dizilis", "4-3-3"), veri.get("dep_td", ""), [_oyuncu_coz(x, i + 1) for i, x in enumerate(dep_kadro[:11])], (241, 245, 249), orta_x + 12, genislik - kenar - 16),
        ]
    else:
        aktif = ev_kadro if len(ev_kadro) >= 5 else dep_kadro
        yari = (len(aktif) + 1) // 2
        ciz.line([orta_x, y + 16, orta_x, y + saha_h - 16], fill=(255, 255, 255, 25), width=1)
        sutun_verileri = [
            ("SAVUNMA & ORTA SAHA", veri.get("ev_dizilis", ""), veri.get("ev_td", ""), [_oyuncu_coz(x, i + 1) for i, x in enumerate(aktif[:yari])], (255, 255, 255), kenar + 16, orta_x - 12),
            ("HÜCUM HATTI", "", "", [_oyuncu_coz(x, yari + i + 1) for i, x in enumerate(aktif[yari:11])], (241, 245, 249), orta_x + 12, genislik - kenar - 16),
        ]

    for c_i, (t_ad, t_diz, t_td, oyuncular, col_renk, c_x1, c_x2) in enumerate(sutun_verileri):
        f_diz = make_image._font(16, make_image.EKSEN_BASLIK)
        f_td = make_image._font(15, make_image.EKSEN_BASLIK)

        # Formasyon Rozeti
        if t_diz:
            diz_w = ciz.textlength(t_diz, font=f_diz)
            ciz.rounded_rectangle([c_x1, y + 12, c_x1 + diz_w + 16, y + 34], radius=6, fill=(255, 255, 255, 25), outline=(255, 255, 255, 90), width=1)
            ciz.text((c_x1 + 8, y + 14), t_diz, font=f_diz, fill=(255, 255, 255))
            td_x = c_x1 + diz_w + 24
        else:
            td_x = c_x1 + 4

        # TD
        if t_td:
            td_txt = f"TD: {t_td}"
            ciz.text((td_x, y + 15), td_txt, font=f_td, fill=(226, 232, 240))

        # İnce yatay ayırıcı
        ciz.line([c_x1, y + 42, c_x2, y + 42], fill=(255, 255, 255, 20), width=1)

        # 11 Oyuncu Satırı (DOĞUKAN İSTEĞİ: FUTBOLCU İSİMLERİ BOLD!)
        oy_y = y + 48
        adet = max(1, len(oyuncular))
        satir_h = (saha_h - 56) // adet
        f_no = make_image._font(19, make_image.EKSEN_BASLIK)
        # ⚠️ İSİMLER ARTIK EXTRA BOLD!
        f_ad_bold = make_image._font(20, make_image.EKSEN_BASLIK)
        f_badge = make_image._font(13, make_image.EKSEN_BASLIK)

        for o_idx, p in enumerate(oyuncular):
            # İnce zebra satır
            if o_idx % 2 == 1:
                ciz.rounded_rectangle([c_x1, oy_y - 2, c_x2, oy_y + satir_h - 4], radius=4, fill=(255, 255, 255, 12))

            # Forma Numarası: Tabular (sağa hizalı blok)
            no_txt = str(p["no"])
            no_w = ciz.textlength(no_txt, font=f_no)
            no_x_sag = c_x1 + 28
            ciz.text((no_x_sag - no_w, oy_y + 4), no_txt, font=f_no, fill=(255, 255, 255))

            # Sağdaki Rozetler (KATI KURAL: Satırın en sağında yer alır)
            sag_x = c_x2 - 6
            if p["kaptan"]:
                ciz.rounded_rectangle([sag_x - 22, oy_y + 4, sag_x, oy_y + 24], radius=4, fill=(255, 255, 255, 35), outline=(255, 255, 255, 140), width=1)
                ciz.text((sag_x - 16, oy_y + 6), "K", font=f_badge, fill=(255, 255, 255))
                sag_x -= 28

            if p["kaleci"]:
                ciz.rounded_rectangle([sag_x - 30, oy_y + 4, sag_x, oy_y + 24], radius=4, fill=(255, 255, 255, 35), outline=(255, 255, 255, 140), width=1)
                ciz.text((sag_x - 24, oy_y + 6), "KL", font=f_badge, fill=(255, 255, 255))
                sag_x -= 36

            # Oyuncu Adı (BOLD VE KRİSTAL BEYAZ)
            ad_x = c_x1 + 38
            max_ad_w = sag_x - ad_x - 6
            ad_sig = _ad_akilli_sigdir(ciz, p["ad"], f_ad_bold, max_ad_w)
            ciz.text((ad_x, oy_y + 3), ad_sig, font=f_ad_bold, fill=(255, 255, 255))

            oy_y += satir_h

    y += saha_h + 12

    # =========================================================================
    # BÖLÜM 3: YEDEK KULÜBESİ (BOLD İSİMLER)
    # =========================================================================
    if kulube_h:
        ciz.rounded_rectangle([kenar, y, genislik - kenar, y + kulube_h], radius=14, fill=(14, 14, 18, 245), outline=(255, 255, 255, 45), width=1)

        f_kb = make_image._font(15, make_image.EKSEN_BASLIK)
        ciz.text((kenar + 18, y + 10), "YEDEK KULÜBESİ", font=f_kb, fill=(255, 255, 255))

        # İki takım yedek akışı
        ciz.line([orta_x, y + 30, orta_x, y + kulube_h - 10], fill=(255, 255, 255, 20), width=1)

        f_ydk_bold = make_image._font(16, make_image.EKSEN_BASLIK)
        f_yno = make_image._font(14, make_image.EKSEN_BASLIK)

        for t_idx, (ydk_list, k_x1, k_x2) in enumerate([
            (ev_yedekler, kenar + 16, orta_x - 12),
            (dep_yedekler, orta_x + 12, genislik - kenar - 16),
        ]):
            sub_w = (k_x2 - k_x1 - 10) // 2
            for i, yp in enumerate(ydk_list[:8]):
                scol = i % 2
                srow = i // 2
                px = k_x1 + scol * (sub_w + 10)
                py = y + 34 + srow * 26

                # Forma no (tabular)
                ciz.text((px, py + 1), str(yp["no"]), font=f_yno, fill=(255, 255, 255))

                # İsim + (KL) sonda
                ad_txt = yp["ad"]
                if yp["kaleci"]:
                    ad_txt += " (KL)"
                ad_sig = _ad_akilli_sigdir(ciz, ad_txt, f_ydk_bold, sub_w - 28)
                ciz.text((px + 24, py), ad_sig, font=f_ydk_bold, fill=(241, 245, 249))

        y += kulube_h + 12

    # =========================================================================
    # BÖLÜM 4: EKSİKLER & MAÇ NOTU (DISCIPLINED STATUS LINE)
    # =========================================================================
    if alt_not:
        ciz.rounded_rectangle([kenar, y, genislik - kenar, y_alt], radius=12, fill=(14, 14, 18, 245), outline=(255, 255, 255, 50), width=1)
        ciz.rounded_rectangle([kenar, y, kenar + 5, y_alt], radius=2, fill=(255, 255, 255))

        f_not = make_image._font(18, make_image.EKSEN_BASLIK)
        alt_not_temiz = re.sub(r"[\u2600-\u27bf\U0001f300-\U0001f9ff⚠️📌🔴🚨★⭐⚽]", "", alt_not).strip()
        not_satirlar = metin_kutuya_sar(ciz, alt_not_temiz, f_not, alan_w - 36, maks_satir=2)
        ny = y + (y_alt - y - len(not_satirlar) * 22) // 2
        for ns in not_satirlar:
            ciz.text((kenar + 18, ny), ns, font=f_not, fill=(255, 255, 255))
            ny += 22

    return ust_ve_alt_bar_bas(
        gorsel,
        ayarlar=ayarlar,
        kaynak=kaynak,
        rozet_metni="MAÇ KADROLARI & İLK 11",
        rozet_renk=(255, 255, 255),
        ulke_kodu=haber.get("ulke_kodu") or None,
        ulke_adi=haber.get("ulke_adi") or None,
        sayfa=sayfa,
        toplam_sayfa=toplam_sayfa,
        arsiv_ibaresi=arsiv_ibaresi,
    )
