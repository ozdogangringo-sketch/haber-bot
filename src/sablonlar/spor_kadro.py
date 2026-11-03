"""
spor_kadro.py — Spor haberleri için "Maç Kadrosu / İlk 11 / Taktik Sahası & Yedekler" detay şablonu.

Claude Design & Anti-Slop İlkeleri:
  - Canlı stadyum projektörleri ve derin zümrüt çim zemin dokusu (stadyum_zemini_olustur)
  - Skorboard bannerında kulüplerin 38x38 şeffaf logoları (fetch_kulup_logo)
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

    # Başta forma numarası var mı? (örn. "1 -", "1.", "#1", "23", "#100")
    no = str(sira)
    m_no = re.match(r"^#?(\d{1,3})[\s\.\-\:)]+(.*)", txt)
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
      "Bernardo Mota Veiga de Carvalho e Silva" -> "B. Silva"
      Sığmazsa son çare taşmayan kelimeden sonra "…" ekler.
    """
    if ciz.textlength(tam_ad, font=font) <= max_gen:
        return tam_ad

    parcalar = tam_ad.split()
    if len(parcalar) >= 2:
        kalan = " ".join(parcalar[1:])
        k1 = f"{parcalar[0][0]}. {kalan}"
        if ciz.textlength(k1, font=font) <= max_gen:
            return k1

        if len(parcalar) >= 3:
            k2 = f"{parcalar[0][0]}. {parcalar[-1]}"
            if ciz.textlength(k2, font=font) <= max_gen:
                return k2
            k3 = f"{parcalar[0][0]}. {parcalar[-2]} {parcalar[-1]}"
            if ciz.textlength(k3, font=font) <= max_gen:
                return k3

    ad = tam_ad
    while ad and ciz.textlength(ad + "…", font=font) > max_gen:
        ad = ad[:-1].rstrip()
    return ad + "…" if ad else tam_ad[:14]


def _takim_adi_sigdir(ciz: ImageDraw.Draw, ham_ad: str, max_gen: int) -> tuple[str, any]:
    """Takım adını puntoları adaptif küçülterek skor rozetine çarpmayacak şekilde sığdırır."""
    ad = make_image._buyuk_harf(ham_ad.strip())
    for punto in (26, 24, 22, 20, 18, 16):
        f = make_image._font(punto, [float(punto), 750.0])
        if ciz.textlength(ad, font=f) <= max_gen:
            return ad, f

    ad_kisa = re.sub(r"\bFUTBOL KULÜBÜ\b", "FK", ad)
    ad_kisa = re.sub(r"\bSPOR KULÜBÜ\b", "SK", ad_kisa)
    ad_kisa = re.sub(r"\bA\.?Ş\.?\b", "", ad_kisa).strip()
    for punto in (20, 18, 16, 15):
        f = make_image._font(punto, [float(punto), 750.0])
        if ciz.textlength(ad_kisa, font=f) <= max_gen:
            return ad_kisa, f

    f = make_image._font(15, [15.0, 750.0])
    while ad_kisa and ciz.textlength(ad_kisa + "…", font=f) > max_gen:
        ad_kisa = ad_kisa[:-1].rstrip()
    return (ad_kisa + "…" if ad_kisa else ham_ad[:12]), f


def _telemetri_sigdir(ciz: ImageDraw.Draw, txt: str, max_gen: int, baslangic_punto: int = 16) -> tuple[str, any]:
    """Turnuva ve maç bilgisi telemetri satırlarını taşmayacak şekilde sığdırır."""
    for punto in (baslangic_punto, baslangic_punto - 2, baslangic_punto - 4):
        if punto < 12:
            break
        f = make_image._font(punto, make_image.EKSEN_BASLIK)
        if ciz.textlength(txt, font=f) <= max_gen:
            return txt, f
    f = make_image._font(12, make_image.EKSEN_BASLIK)
    kirp = txt
    while kirp and ciz.textlength(kirp + "…", font=f) > max_gen:
        kirp = kirp[:-1].rstrip()
    return (kirp + "…" if kirp else txt[:20]), f


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
    VIP Spor Kadro Detay Slaytı (1080x1920 dikey tuval, 4:5 merkezi güvenli alan).
    Kapakla %100 uyumlu Split Arena stadyum atmosferi, tek parça lüks obsidian cam sahne,
    neon kulüp çentikleri ve saf kristal beyaz bold tipografi.
    """
    ev_ad = (veri.get("ev_sahibi") or veri.get("takim_1") or "").strip()
    dep_ad = (veri.get("deplasman") or veri.get("takim_2") or "").strip()
    ev_kadro = [
        _oyuncu_coz(x, i + 1)
        for i, x in enumerate(
            veri.get("ev_kadro")
            or veri.get("ev_sahibi_kadro")
            or veri.get("ev_11")
            or veri.get("kadro_1")
            or []
        )
        if str(x).strip()
    ]
    dep_kadro = [
        _oyuncu_coz(x, i + 1)
        for i, x in enumerate(
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
    y_alt = alt_bilgi_y - 68  # 1488 px (Sosyal medya ikonlarıyla sıfır çakışma)
    y_ust = dikey_kenar + 175  # 505 px (DB logosu altına nefes payı)

    mini_ev_logo = fetch_kulup_logo.kulup_logosu_al(ev_ad, boyut=38) if ev_ad else None
    mini_dep_logo = fetch_kulup_logo.kulup_logosu_al(dep_ad, boyut=38) if dep_ad else None

    ev_renkler, dep_renkler = fetch_kulup_logo.mac_renklerini_ayarla(ev_ad, dep_ad, mini_ev_logo, mini_dep_logo)

    ev_atmo = ev_renkler.get("atmosphere", (119, 13, 44))
    dep_atmo = dep_renkler.get("atmosphere", (20, 20, 28))
    ev_p = ev_renkler.get("primary", (119, 13, 44))
    dep_p = dep_renkler.get("primary", (22, 22, 28))

    # =========================================================================
    # 1. TEMEL TUVAL — ZENGİN STADYUM VE PROJEKTÖR ZEMİNİ + SPLIT KULÜP ATMOSFERİ
    # =========================================================================
    gorsel = stadyum_zemini_olustur(genislik, yukseklik)

    split = Image.new("RGBA", (genislik, yukseklik), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(split)
    s_draw.polygon([(0, 0), (genislik // 2 + 80, 0), (genislik // 2 - 80, yukseklik), (0, yukseklik)], fill=(ev_atmo[0], ev_atmo[1], ev_atmo[2], 95))
    s_draw.polygon([(genislik // 2 + 80, 0), (genislik, 0), (genislik, yukseklik), (genislik // 2 - 80, yukseklik)], fill=(dep_atmo[0], dep_atmo[1], dep_atmo[2], 95))
    gorsel = Image.alpha_composite(gorsel.convert("RGBA"), split.filter(ImageFilter.GaussianBlur(95))).convert("RGB")

    # =========================================================================
    # 2. TEK PARÇA BİRLEŞİK LÜKS TACTICAL STAGE (FROSTED OBSIDIAN GLASS)
    # =========================================================================
    stage_w = genislik - 2 * kenar
    stage_h = y_alt - y_ust

    golge = Image.new("RGBA", (genislik, yukseklik), (0, 0, 0, 0))
    g_draw = ImageDraw.Draw(golge)
    g_draw.rounded_rectangle([kenar - 8, y_ust - 4, genislik - kenar + 8, y_alt + 12], radius=24, fill=(0, 0, 0, 160))
    gorsel = Image.alpha_composite(gorsel.convert("RGBA"), golge.filter(ImageFilter.GaussianBlur(24))).convert("RGB")

    ciz = ImageDraw.Draw(gorsel, "RGBA")

    # Ana Birleşik Gövde (Tek Parça Lüks Mimari)
    ciz.rounded_rectangle([kenar, y_ust, genislik - kenar, y_alt], radius=20, fill=(10, 14, 20, 238), outline=(255, 255, 255, 45), width=1)
    # Üst Krom Yansıma Işıltısı
    ciz.rounded_rectangle([kenar + 20, y_ust + 1, genislik - kenar - 20, y_ust + 2], radius=1, fill=(255, 255, 255, 80))

    # =========================================================================
    # BÖLÜM A: ENTEGRE SKORBOARD BAŞLIĞI
    # =========================================================================
    header_h = 116
    orta_x = genislik // 2

    turnuva = (veri.get("turnuva") or veri.get("lig") or "KARŞILAŞMA").strip().upper()
    turnuva_ciz, f_lig = _telemetri_sigdir(ciz, turnuva, max_gen=320, baslangic_punto=16)
    lig_w = ciz.textlength(turnuva_ciz, font=f_lig)
    ciz.rounded_rectangle([(genislik - lig_w) // 2 - 14, y_ust + 8, (genislik + lig_w) // 2 + 14, y_ust + 30], radius=6, fill=(255, 255, 255, 20), outline=(255, 255, 255, 60), width=1)
    ciz.text(((genislik - lig_w) // 2, y_ust + 10), turnuva_ciz, font=f_lig, fill=(255, 255, 255))

    # Ortada Karşılaşma Saati / Skor Rozeti
    skor_saat = (veri.get("skor_veya_saat") or veri.get("saat") or "20:00").strip()
    f_saat = make_image._font(24, make_image.EKSEN_BASLIK)
    saat_w = ciz.textlength(skor_saat, font=f_saat)
    rw = max(96, int(saat_w + 28))
    rx1 = (genislik - rw) // 2
    rx2 = rx1 + rw
    ry1 = y_ust + 36
    ry2 = ry1 + 38

    mac_sonu = bool(veri.get("mac_sonu")) or ("-" in skor_saat and ":" not in skor_saat)
    rozet_border = (16, 185, 129, 200) if mac_sonu else (255, 255, 255, 100)
    ciz.rounded_rectangle([rx1, ry1, rx2, ry2], radius=10, fill=(255, 255, 255, 25), outline=rozet_border, width=1)
    ciz.text(((genislik - saat_w) // 2, ry1 + 7), skor_saat, font=f_saat, fill=(255, 255, 255))

    if ev_ad and dep_ad:
        # Ev Sahibi Kapsülü
        ciz.rounded_rectangle([kenar + 12, ry1 - 2, rx1 - 10, ry2 + 2], radius=10, fill=(18, 22, 30, 220), outline=(ev_p[0], ev_p[1], ev_p[2], 120), width=1)
        ciz.rounded_rectangle([kenar + 12, ry1 - 2, kenar + 16, ry2 + 2], radius=2, fill=(ev_p[0], ev_p[1], ev_p[2], 240))

        ev_sol_x = kenar + 22
        if mini_ev_logo:
            ciz.ellipse([ev_sol_x - 3, ry1 - 2, ev_sol_x + 38 + 3, ry1 + 38 + 2], fill=(10, 12, 18, 235), outline=(255, 255, 255, 70), width=1)
            gorsel.paste(mini_ev_logo, (ev_sol_x, ry1), mask=mini_ev_logo)
            ev_ad_x = ev_sol_x + 46
        else:
            ev_ad_x = ev_sol_x + 10

        azami_takim_g = (rx1 - ev_ad_x) - 16
        ev_ad_ciz, f_ev = _takim_adi_sigdir(ciz, ev_ad, azami_takim_g)
        bbox_ev = ciz.textbbox((0, 0), ev_ad_ciz, font=f_ev)
        th_ev = bbox_ev[3] - bbox_ev[1]
        ty_ev = (ry1 - 2 + ry2 + 2 - th_ev) // 2 - bbox_ev[1]
        ciz.text((ev_ad_x, ty_ev), ev_ad_ciz, font=f_ev, fill=(255, 255, 255))

        # Deplasman Kapsülü
        ciz.rounded_rectangle([rx2 + 10, ry1 - 2, genislik - kenar - 12, ry2 + 2], radius=10, fill=(18, 22, 30, 220), outline=(dep_p[0], dep_p[1], dep_p[2], 120), width=1)
        ciz.rounded_rectangle([genislik - kenar - 16, ry1 - 2, genislik - kenar - 12, ry2 + 2], radius=2, fill=(dep_p[0], dep_p[1], dep_p[2], 240))

        dep_sag_x = genislik - kenar - 22
        if mini_dep_logo:
            ciz.ellipse([dep_sag_x - 38 - 3, ry1 - 2, dep_sag_x + 3, ry1 + 38 + 2], fill=(10, 12, 18, 235), outline=(255, 255, 255, 70), width=1)
            gorsel.paste(mini_dep_logo, (dep_sag_x - 38, ry1), mask=mini_dep_logo)
            dep_ad_sag_sinir = dep_sag_x - 46
        else:
            dep_ad_sag_sinir = dep_sag_x - 10

        azami_dep_g = (dep_ad_sag_sinir - rx2) - 16
        dep_ad_ciz, f_dep = _takim_adi_sigdir(ciz, dep_ad, azami_dep_g)
        dep_tw = ciz.textlength(dep_ad_ciz, font=f_dep)
        bbox_dep = ciz.textbbox((0, 0), dep_ad_ciz, font=f_dep)
        th_dep = bbox_dep[3] - bbox_dep[1]
        ty_dep = (ry1 - 2 + ry2 + 2 - th_dep) // 2 - bbox_dep[1]
        ciz.text((dep_ad_sag_sinir - dep_tw, ty_dep), dep_ad_ciz, font=f_dep, fill=(255, 255, 255))
    else:
        tek_ad = make_image._buyuk_harf((ev_ad or dep_ad or "İLK 11 KADROSU"))
        tek_ciz, f_tek = _takim_adi_sigdir(ciz, tek_ad, stage_w - 48)
        bbox_tek = ciz.textbbox((0, 0), tek_ciz, font=f_tek)
        th_tek = bbox_tek[3] - bbox_tek[1]
        ty_tek = (ry1 - 2 + ry2 + 2 - th_tek) // 2 - bbox_tek[1]
        ciz.text((kenar + 24, ty_tek), tek_ciz, font=f_tek, fill=(255, 255, 255))

    # Alt satır: Stadyum & Hakem & Yayın
    mac_bilgi = (veri.get("mac_bilgisi") or veri.get("stat_hakem") or veri.get("stadyum_saat") or "").strip()
    if mac_bilgi:
        ciz.line([kenar + 20, y_ust + 82, genislik - kenar - 20, y_ust + 82], fill=(255, 255, 255, 20), width=1)
        mac_bilgi_ciz, f_info = _telemetri_sigdir(ciz, mac_bilgi, max_gen=stage_w - 40, baslangic_punto=16)
        iw = ciz.textlength(mac_bilgi_ciz, font=f_info)
        ciz.text(((genislik - iw) // 2, y_ust + 91), mac_bilgi_ciz, font=f_info, fill=(226, 232, 240))

    # Başlık ile Saha arasındaki Zarif Ayrım Çizgisi
    ciz.line([kenar + 16, y_ust + header_h, genislik - kenar - 16, y_ust + header_h], fill=(255, 255, 255, 25), width=1)

    # =========================================================================
    # BÖLÜM B: TAKTİK SAHA, YEDEK KULÜBESİ VE EKSİKLER NOTU
    # =========================================================================
    y_icerik = y_ust + header_h + 8
    kalan_yukseklik = y_alt - y_icerik

    alt_not = (veri.get("alt_not") or veri.get("eksikler") or "").strip()
    alt_not_h = 66 if alt_not else 0

    has_yedek = bool(ev_yedekler or dep_yedekler)
    kulube_h = 132 if has_yedek else 0

    saha_h = kalan_yukseklik - alt_not_h - (kulube_h + (10 if kulube_h else 0)) - (10 if alt_not_h else 0)

    iki_takim = len(ev_kadro) >= 5 and len(dep_kadro) >= 5

    # Santra Dairesi ve Orta Çizgi
    ciz.line([orta_x, y_icerik + 12, orta_x, y_icerik + saha_h - 12], fill=(255, 255, 255, 25), width=1)
    santra_y = y_icerik + saha_h // 2
    ciz.ellipse([orta_x - 36, santra_y - 36, orta_x + 36, santra_y + 36], outline=(255, 255, 255, 25), width=1)

    if iki_takim:
        sutun_verileri = [
            (ev_ad, veri.get("ev_dizilis", "4-2-3-1"), veri.get("ev_td", ""), ev_kadro[:11], ev_renkler, kenar + 16, orta_x - 12),
            (dep_ad, veri.get("dep_dizilis", "4-3-3"), veri.get("dep_td", ""), dep_kadro[:11], dep_renkler, orta_x + 12, genislik - kenar - 16),
        ]
    else:
        aktif = ev_kadro if len(ev_kadro) >= 5 else dep_kadro
        aktif_renk = ev_renkler if len(ev_kadro) >= 5 else dep_renkler
        yari = (len(aktif) + 1) // 2
        sutun_verileri = [
            ("SAVUNMA & ORTA SAHA", veri.get("ev_dizilis", ""), veri.get("ev_td", ""), aktif[:yari], aktif_renk, kenar + 16, orta_x - 12),
            ("HÜCUM HATTI", "", "", aktif[yari:11], aktif_renk, orta_x + 12, genislik - kenar - 16),
        ]

    for c_i, (t_ad, t_diz, t_td, oyuncular, t_renk, c_x1, c_x2) in enumerate(sutun_verileri):
        p_col = t_renk.get("primary", (14, 165, 233))
        num_col = t_renk.get("number", (255, 255, 255))

        f_diz = make_image._font(16, make_image.EKSEN_BASLIK)
        f_td = make_image._font(15, make_image.EKSEN_BASLIK)

        # Formasyon Rozeti
        if t_diz:
            diz_w = ciz.textlength(t_diz, font=f_diz)
            ciz.rounded_rectangle([c_x1, y_icerik + 8, c_x1 + diz_w + 16, y_icerik + 30], radius=6, fill=(p_col[0], p_col[1], p_col[2], 50), outline=(p_col[0], p_col[1], p_col[2], 140), width=1)
            ciz.text((c_x1 + 8, y_icerik + 10), t_diz, font=f_diz, fill=(255, 255, 255))
            td_x = c_x1 + diz_w + 24
        else:
            td_x = c_x1 + 4

        # TD
        if t_td:
            td_txt = f"TD: {t_td}"
            td_sig, f_td_sig = _telemetri_sigdir(ciz, td_txt, max_gen=(c_x2 - td_x - 8), baslangic_punto=15)
            ciz.text((td_x, y_icerik + 11), td_sig, font=f_td_sig, fill=(203, 213, 225))

        ciz.line([c_x1, y_icerik + 38, c_x2, y_icerik + 38], fill=(255, 255, 255, 20), width=1)

        # 11 Futbolcu Satırları
        oy_y = y_icerik + 44
        adet = max(1, len(oyuncular))
        satir_h = (saha_h - 50) // adet
        f_no = make_image._font(19, make_image.EKSEN_BASLIK)
        f_ad_bold = make_image._font(20, make_image.EKSEN_BASLIK)
        f_badge = make_image._font(13, make_image.EKSEN_BASLIK)

        for o_idx, p in enumerate(oyuncular):
            if o_idx % 2 == 1:
                ciz.rounded_rectangle([c_x1, oy_y - 2, c_x2, oy_y + satir_h - 4], radius=4, fill=(255, 255, 255, 12))

            # Sol Çentik (Kulüp Neon Çizgisi)
            ciz.rounded_rectangle([c_x1 + 3, oy_y + 3, c_x1 + 6, oy_y + satir_h - 7], radius=2, fill=(p_col[0], p_col[1], p_col[2], 240))

            # Forma Numarası
            no_txt = str(p["no"])
            no_w = ciz.textlength(no_txt, font=f_no)
            no_x_sag = c_x1 + 40
            ciz.text((no_x_sag - no_w, oy_y + 4), no_txt, font=f_no, fill=num_col)

            # Rozetler
            sag_x = c_x2 - 6
            if p["kaptan"]:
                ciz.rounded_rectangle([sag_x - 22, oy_y + 4, sag_x, oy_y + 24], radius=4, fill=(p_col[0], p_col[1], p_col[2], 75), outline=(255, 255, 255, 140), width=1)
                ciz.text((sag_x - 16, oy_y + 6), "K", font=f_badge, fill=(255, 255, 255))
                sag_x -= 28

            if p["kaleci"]:
                ciz.rounded_rectangle([sag_x - 30, oy_y + 4, sag_x, oy_y + 24], radius=4, fill=(16, 185, 129, 60), outline=(52, 211, 153, 160), width=1)
                ciz.text((sag_x - 24, oy_y + 6), "KL", font=f_badge, fill=(255, 255, 255))
                sag_x -= 36

            # Futbolcu Adı (%100 BOLD SAF KRİSTAL BEYAZ + GELİŞMİŞ SOYAD KORUMA)
            ad_x = c_x1 + 50
            max_ad_w = sag_x - ad_x - 6
            ad_sig = _ad_akilli_sigdir(ciz, p["ad"], f_ad_bold, max_ad_w)
            ciz.text((ad_x, oy_y + 3), ad_sig, font=f_ad_bold, fill=(255, 255, 255))

            oy_y += satir_h

    cur_y = y_icerik + saha_h + 8

    # =========================================================================
    # BÖLÜM C: YEDEK KULÜBESİ
    # =========================================================================
    if kulube_h:
        ciz.line([kenar + 16, cur_y - 4, genislik - kenar - 16, cur_y - 4], fill=(255, 255, 255, 25), width=1)

        f_kb = make_image._font(15, make_image.EKSEN_BASLIK)
        ciz.text((kenar + 18, cur_y + 4), "YEDEK KULÜBESİ", font=f_kb, fill=(255, 255, 255))

        ciz.line([orta_x, cur_y + 24, orta_x, cur_y + kulube_h - 6], fill=(255, 255, 255, 20), width=1)

        f_ydk_bold = make_image._font(15, make_image.EKSEN_BASLIK)
        f_yno = make_image._font(13, make_image.EKSEN_BASLIK)

        for t_idx, (ydk_list, k_x1, k_x2, y_renk) in enumerate([
            (ev_yedekler, kenar + 16, orta_x - 12, ev_renkler),
            (dep_yedekler, orta_x + 12, genislik - kenar - 16, dep_renkler),
        ]):
            ynum_col = y_renk.get("number", (255, 255, 255))
            sub_w = (k_x2 - k_x1 - 10) // 2
            for i, yp in enumerate(ydk_list[:8]):
                scol = i % 2
                srow = i // 2
                px = k_x1 + scol * (sub_w + 10)
                py = cur_y + 26 + srow * 24

                ciz.rounded_rectangle([px, py, px + sub_w, py + 22], radius=4, fill=(255, 255, 255, 10))
                ciz.text((px + 6, py + 3), str(yp["no"]), font=f_yno, fill=ynum_col)

                ad_txt = yp["ad"]
                if yp["kaleci"]:
                    ad_txt += " (KL)"
                ad_sig = _ad_akilli_sigdir(ciz, ad_txt, f_ydk_bold, sub_w - 32)
                ciz.text((px + 28, py + 2), ad_sig, font=f_ydk_bold, fill=(245, 245, 250))

        cur_y += kulube_h + 8

    # =========================================================================
    # BÖLÜM D: EKSİKLER & MAÇ NOTU
    # =========================================================================
    if alt_not:
        ciz.line([kenar + 16, cur_y - 4, genislik - kenar - 16, cur_y - 4], fill=(255, 255, 255, 25), width=1)
        ciz.rounded_rectangle([kenar + 12, cur_y + 4, kenar + 16, y_alt - 10], radius=2, fill=(226, 170, 88))  # Sıcak kehribar çentik

        f_not = make_image._font(17, make_image.EKSEN_BASLIK)
        alt_not_temiz = re.sub(r"[\u2600-\u27bf\U0001f300-\U0001f9ff⚠️📌🔴🚨★⭐⚽]", "", alt_not).strip()
        not_satirlar = metin_kutuya_sar(ciz, alt_not_temiz, f_not, stage_w - 44, maks_satir=2)
        ny = cur_y + (y_alt - cur_y - len(not_satirlar) * 20) // 2
        for ns in not_satirlar:
            ciz.text((kenar + 28, ny), ns, font=f_not, fill=(255, 255, 255))
            ny += 20

    return ust_ve_alt_bar_bas(
        gorsel,
        ayarlar=ayarlar,
        kaynak=kaynak,
        rozet_metni="",  # 144px 3D logo tek başına tertemiz kalsın
        rozet_renk=(255, 255, 255),
        ulke_kodu=haber.get("ulke_kodu") or None,
        ulke_adi=haber.get("ulke_adi") or None,
        sayfa=sayfa,
        toplam_sayfa=toplam_sayfa,
        arsiv_ibaresi=arsiv_ibaresi,
    )
