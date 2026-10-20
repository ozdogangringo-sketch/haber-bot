import json
import re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter
import yaml

from src import make_image, fetch_kulup_logo
from src.sablonlar import spor_kapak

art_dir = Path("/Users/macbook/.gemini/antigravity/brain/4b51c693-ddbf-4a88-aba5-083b33bb6dd2")

with open("config.yaml", "r", encoding="utf-8") as f:
    ayarlar = yaml.safe_load(f)

def _oyuncu_coz(ham: str | dict, idx: int = 1) -> dict:
    if isinstance(ham, dict):
        return {
            "no": ham.get("no") or ham.get("numara") or idx,
            "ad": ham.get("ad") or ham.get("isim") or "",
            "kaptan": bool(ham.get("kaptan")),
            "kaleci": bool(ham.get("kaleci")),
        }
    txt = str(ham).strip()
    kaptan = "(K)" in txt or txt.endswith(" K")
    kaleci = "(KL)" in txt or txt.endswith(" KL")
    txt = re.sub(r"\s*\((?:KL|K)\)", "", txt, flags=re.I).strip()
    m = re.match(r"^(\d+)\s+(.+)$", txt)
    if m:
        return {"no": int(m.group(1)), "ad": m.group(2).strip(), "kaptan": kaptan, "kaleci": kaleci}
    return {"no": idx, "ad": txt, "kaptan": kaptan, "kaleci": kaleci}

def _yedekleri_coz(ham_liste: list | None) -> list[dict]:
    if not ham_liste:
        return []
    res = []
    for i, x in enumerate(ham_liste):
        p = _oyuncu_coz(x, i + 1)
        if p["ad"]:
            res.append(p)
    return res

def _ad_akilli_sigdir(ciz: ImageDraw.Draw, ham_ad: str, font, max_gen: int) -> str:
    if ciz.textlength(ham_ad, font=font) <= max_gen:
        return ham_ad
    parcalar = ham_ad.split()
    if len(parcalar) >= 2:
        kisaltilmis = f"{parcalar[0][0]}. {' '.join(parcalar[1:])}"
        if ciz.textlength(kisaltilmis, font=font) <= max_gen:
            return kisaltilmis
        kisaltilmis_2 = f"{parcalar[0][0]}. {parcalar[1]}"
        if ciz.textlength(kisaltilmis_2, font=font) <= max_gen:
            return kisaltilmis_2
    ad = ham_ad
    while ad and ciz.textlength(ad + "…", font=font) > max_gen:
        ad = ad[:-1].strip()
    return ad + "…" if ad else ham_ad[:12]

def ciz_kadro_premium(haber: dict, veri: dict, stil: str = "A") -> Image.Image:
    genislik = make_image.STORY_GENISLIK
    yukseklik = make_image.STORY_YUKSEKLIK
    kenar = 64
    dikey_kenar = make_image.STORY_GUVENLI_PAY  # 330
    alt_bilgi_y = yukseklik - dikey_kenar - 34
    y_alt = alt_bilgi_y - 68
    y_ust = dikey_kenar + 175  # 505 px

    ev_ad = (veri.get("ev_sahibi") or veri.get("takim_1") or "").strip()
    dep_ad = (veri.get("deplasman") or veri.get("takim_2") or "").strip()
    turnuva = (veri.get("turnuva") or veri.get("lig") or "KARŞILAŞMA").strip().upper()
    skor_saat = (veri.get("skor_veya_saat") or veri.get("saat") or "20:00").strip()

    ev_kadro = [_oyuncu_coz(x, i+1) for i, x in enumerate(veri.get("ev_kadro") or [])]
    dep_kadro = [_oyuncu_coz(x, i+1) for i, x in enumerate(veri.get("deplasman_kadro") or [])]
    ev_yedekler = _yedekleri_coz(veri.get("ev_yedekler"))
    dep_yedekler = _yedekleri_coz(veri.get("deplasman_yedekler"))

    mini_ev_logo = fetch_kulup_logo.kulup_logosu_al(ev_ad, boyut=38) if ev_ad else None
    mini_dep_logo = fetch_kulup_logo.kulup_logosu_al(dep_ad, boyut=38) if dep_ad else None
    ev_renkler = fetch_kulup_logo.kulup_renkleri_al(ev_ad, mini_ev_logo)
    dep_renkler = fetch_kulup_logo.kulup_renkleri_al(dep_ad, mini_dep_logo)

    ev_atmo = ev_renkler.get("atmosphere", (119, 13, 44))
    dep_atmo = dep_renkler.get("atmosphere", (20, 20, 28))
    ev_p = ev_renkler.get("primary", (119, 13, 44))
    ev_s = ev_renkler.get("secondary", (88, 184, 237))
    ev_num = ev_renkler.get("number", (255, 255, 255))
    dep_p = dep_renkler.get("primary", (22, 22, 28))
    dep_s = dep_renkler.get("secondary", (240, 240, 248))
    dep_num = dep_renkler.get("number", (255, 255, 255))

    # 1. TEMEL TUVAL — DOĞUKAN'IN DEDİĞİ GİBİ: KOMPLE ARKAPLAN STADYUM ATMOSFERİNE DAHİL!
    gorsel = Image.new("RGB", (genislik, yukseklik), (6, 8, 12))

    # Split Arena Diyagonal Atmosfer Işıltısı (Sol: Ev Sahibi / Sağ: Deplasman)
    split = Image.new("RGBA", (genislik, yukseklik), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(split)
    # Sol ev sahibi ışığı
    s_draw.polygon([(0, 0), (genislik // 2 + 80, 0), (genislik // 2 - 80, yukseklik), (0, yukseklik)], fill=(ev_atmo[0], ev_atmo[1], ev_atmo[2], 95))
    # Sağ deplasman ışığı
    s_draw.polygon([(genislik // 2 + 80, 0), (genislik, 0), (genislik, yukseklik), (genislik // 2 - 80, yukseklik)], fill=(dep_atmo[0], dep_atmo[1], dep_atmo[2], 95))
    gorsel = Image.alpha_composite(gorsel.convert("RGBA"), split.filter(ImageFilter.GaussianBlur(95))).convert("RGB")

    # Merkezde hafif koyu vinjet (kartların arkasında maksimum kontrast için)
    vinjet = Image.new("RGBA", (genislik, yukseklik), (0, 0, 0, 0))
    v_draw = ImageDraw.Draw(vinjet)
    v_draw.ellipse([kenar - 40, y_ust - 40, genislik - kenar + 40, y_alt + 40], fill=(0, 0, 0, 110))
    gorsel = Image.alpha_composite(gorsel.convert("RGBA"), vinjet.filter(ImageFilter.GaussianBlur(50))).convert("RGB")

    ciz = ImageDraw.Draw(gorsel, "RGBA")
    alan_w = genislik - 2 * kenar
    y = y_ust

    # =========================================================================
    # BÖLÜM 1: MAÇ SKORBOARD BANNERI (LÜKS FÜME CAM + METALİK BORDER)
    # =========================================================================
    banner_h = 120
    # Koyu obsidian cam kutu
    ciz.rounded_rectangle([kenar, y, genislik - kenar, y + banner_h], radius=16, fill=(10, 12, 16, 235), outline=(255, 255, 255, 45), width=1)
    ciz.rounded_rectangle([kenar + 16, y + 1, genislik - kenar - 16, y + 2], radius=1, fill=(255, 255, 255, 80))

    # Turnuva / Lig Rozeti
    f_lig = make_image._font(16, make_image.EKSEN_BASLIK)
    lig_w = ciz.textlength(turnuva, font=f_lig)
    ciz.rounded_rectangle([(genislik - lig_w) / 2 - 16, y + 8, (genislik + lig_w) / 2 + 16, y + 30], radius=6, fill=(255, 255, 255, 20), outline=(255, 255, 255, 60), width=1)
    ciz.text(((genislik - lig_w) / 2, y + 10), turnuva, font=f_lig, fill=(255, 255, 255))

    # Saat Rozeti
    f_saat = make_image._font(24, make_image.EKSEN_BASLIK)
    saat_w = ciz.textlength(skor_saat, font=f_saat)
    rw = max(96, int(saat_w + 28))
    rx1 = (genislik - rw) // 2
    rx2 = rx1 + rw
    ry1 = y + 38
    ry2 = ry1 + 38
    ciz.rounded_rectangle([rx1, ry1, rx2, ry2], radius=10, fill=(255, 255, 255, 25), outline=(255, 255, 255, 100), width=1)
    ciz.text(((genislik - saat_w) / 2, ry1 + 7), skor_saat, font=f_saat, fill=(255, 255, 255))

    # Ev Sahibi Kapsülü (Lüks Füme Cam + Sol Kulüp Neon Çizgisi)
    ciz.rounded_rectangle([kenar + 8, ry1 - 3, rx1 - 10, ry2 + 3], radius=10, fill=(18, 22, 30, 220), outline=(ev_p[0], ev_p[1], ev_p[2], 120), width=1)
    ciz.rounded_rectangle([kenar + 8, ry1 - 3, kenar + 12, ry2 + 3], radius=2, fill=(ev_p[0], ev_p[1], ev_p[2], 240))

    ev_sol_x = kenar + 20
    if mini_ev_logo:
        ciz.ellipse([ev_sol_x - 3, ry1 - 3, ev_sol_x + 38 + 3, ry1 + 38 + 3], fill=(10, 12, 18, 235), outline=(255, 255, 255, 70), width=1)
        gorsel.paste(mini_ev_logo, (ev_sol_x, ry1), mask=mini_ev_logo)
        ev_ad_x = ev_sol_x + 46
    else:
        ev_ad_x = ev_sol_x + 12
    f_ev = make_image._font(22, make_image.EKSEN_BASLIK)
    ciz.text((ev_ad_x, ry1 + 7), ev_ad.upper(), font=f_ev, fill=(255, 255, 255))

    # Deplasman Kapsülü (Lüks Füme Cam + Sağ Kulüp Neon Çizgisi)
    ciz.rounded_rectangle([rx2 + 10, ry1 - 3, genislik - kenar - 8, ry2 + 3], radius=10, fill=(18, 22, 30, 220), outline=(dep_p[0], dep_p[1], dep_p[2], 120), width=1)
    ciz.rounded_rectangle([genislik - kenar - 12, ry1 - 3, genislik - kenar - 8, ry2 + 3], radius=2, fill=(dep_p[0], dep_p[1], dep_p[2], 240))

    dep_sag_x = genislik - kenar - 20
    if mini_dep_logo:
        ciz.ellipse([dep_sag_x - 38 - 3, ry1 - 3, dep_sag_x + 3, ry1 + 38 + 3], fill=(10, 12, 18, 235), outline=(255, 255, 255, 70), width=1)
        gorsel.paste(mini_dep_logo, (dep_sag_x - 38, ry1), mask=mini_dep_logo)
        dep_ad_sag_sinir = dep_sag_x - 46
    else:
        dep_ad_sag_sinir = dep_sag_x - 12
    f_dep = make_image._font(22, make_image.EKSEN_BASLIK)
    dep_tw = ciz.textlength(dep_ad.upper(), font=f_dep)
    ciz.text((dep_ad_sag_sinir - dep_tw, ry1 + 7), dep_ad.upper(), font=f_dep, fill=(255, 255, 255))

    # Alt Stadyum & Hakem Bilgisi
    mac_bilgi = (veri.get("mac_bilgisi") or veri.get("stat_hakem") or veri.get("stadyum_saat") or "").strip()
    if mac_bilgi:
        ciz.line([kenar + 20, y + 84, genislik - kenar - 20, y + 84], fill=(255, 255, 255, 20), width=1)
        f_info = make_image._font(16, make_image.EKSEN_BASLIK)
        iw = ciz.textlength(mac_bilgi, font=f_info)
        ciz.text(((genislik - iw) / 2, y + 93), mac_bilgi, font=f_info, fill=(226, 232, 240))

    y += banner_h + 12

    # =========================================================================
    # BÖLÜM 2: SAHA ALANI (FROSTED OBSIDIAN GLASS + CRISTAL CLEAR ROWS)
    # =========================================================================
    has_yedek = bool(ev_yedekler or dep_yedekler)
    alt_not = (veri.get("alt_not") or veri.get("eksikler") or "").strip()
    kalan_alan = y_alt - y
    alt_not_h = 68 if alt_not else 0
    kulube_h = 138 if has_yedek else 0
    saha_h = kalan_alan - alt_not_h - (kulube_h + (10 if kulube_h else 0)) - (10 if alt_not_h else 0)

    # Saha Kutusu (Koyu Cam + Titanyum Bevel)
    ciz.rounded_rectangle([kenar, y, genislik - kenar, y + saha_h], radius=18, fill=(10, 12, 16, 235), outline=(255, 255, 255, 45), width=1)
    ciz.rounded_rectangle([kenar + 16, y + 1, genislik - kenar - 16, y + 2], radius=1, fill=(255, 255, 255, 80))

    orta_x = genislik // 2
    ciz.line([orta_x, y + 16, orta_x, y + saha_h - 16], fill=(255, 255, 255, 25), width=1)
    santra_y = y + saha_h // 2
    ciz.ellipse([orta_x - 36, santra_y - 36, orta_x + 36, santra_y + 36], outline=(255, 255, 255, 25), width=1)

    sutun_verileri = [
        (ev_ad, veri.get("ev_dizilis", "4-2-3-1"), veri.get("ev_td", ""), ev_kadro[:11], ev_renkler, kenar + 16, orta_x - 12),
        (dep_ad, veri.get("dep_dizilis", "4-3-3"), veri.get("dep_td", ""), dep_kadro[:11], dep_renkler, orta_x + 12, genislik - kenar - 16),
    ]

    for c_i, (t_ad, t_diz, t_td, oyuncular, t_renk, c_x1, c_x2) in enumerate(sutun_verileri):
        p_col = t_renk.get("primary", (14, 165, 233))
        s_col = t_renk.get("secondary", (245, 245, 250))
        num_col = t_renk.get("number", (255, 255, 255))

        f_diz = make_image._font(16, make_image.EKSEN_BASLIK)
        f_td = make_image._font(15, make_image.EKSEN_BASLIK)

        # Diziliş Rozeti
        if t_diz:
            diz_w = ciz.textlength(t_diz, font=f_diz)
            ciz.rounded_rectangle([c_x1, y + 12, c_x1 + diz_w + 16, y + 34], radius=6, fill=(p_col[0], p_col[1], p_col[2], 50), outline=(p_col[0], p_col[1], p_col[2], 140), width=1)
            ciz.text((c_x1 + 8, y + 14), t_diz, font=f_diz, fill=(255, 255, 255))
            td_x = c_x1 + diz_w + 24
        else:
            td_x = c_x1 + 4

        # TD
        if t_td:
            ciz.text((td_x, y + 15), f"TD: {t_td}", font=f_td, fill=(203, 213, 225))

        # İnce yatay ayırıcı
        ciz.line([c_x1, y + 42, c_x2, y + 42], fill=(255, 255, 255, 20), width=1)

        # 11 OYUNCU SATIRI (DOĞUKAN STANDARDI: ZARİF, FERAH, SAF BEYAZ VE NEON VURGULU)
        oy_y = y + 48
        adet = max(1, len(oyuncular))
        satir_h = (saha_h - 56) // adet
        f_no = make_image._font(19, make_image.EKSEN_BASLIK)
        f_ad_bold = make_image._font(20, make_image.EKSEN_BASLIK)
        f_badge = make_image._font(13, make_image.EKSEN_BASLIK)

        for o_idx, p in enumerate(oyuncular):
            # Zemin: ASLA KALIN SARI/MAVİ BLOK YOK! Koyu füme cam zemin + zarif zebra
            if stil == "A":
                # Stil A: VIP Minimalist Glass — Her 2. satırda çok hafif %4 füme cam
                if o_idx % 2 == 1:
                    ciz.rounded_rectangle([c_x1, oy_y - 2, c_x2, oy_y + satir_h - 4], radius=4, fill=(255, 255, 255, 12))
            elif stil == "B":
                # Stil B: Metallic Gradient Glow — Soldan sağa çok hafif renk süzülmesi
                grad_alpha = 30 if o_idx % 2 == 1 else 15
                ciz.rounded_rectangle([c_x1, oy_y - 2, c_x2, oy_y + satir_h - 4], radius=4, fill=(p_col[0], p_col[1], p_col[2], grad_alpha))
            elif stil == "C":
                # Stil C: Titanyum Graphite Strip — Koyu grafit satır şeritleri
                bg_a = 24 if o_idx % 2 == 1 else 10
                ciz.rounded_rectangle([c_x1, oy_y - 2, c_x2, oy_y + satir_h - 4], radius=4, fill=(30, 36, 48, bg_a), outline=(255, 255, 255, 15), width=1)

            # Sol Çentik: 3px yuvarlatılmış neon kulüp rengi çizgisi (HER SATIRDA ASİLCE IŞILDAR)
            ciz.rounded_rectangle([c_x1 + 3, oy_y + 3, c_x1 + 6, oy_y + satir_h - 7], radius=2, fill=(p_col[0], p_col[1], p_col[2], 240))

            # Forma Numarası: Kulübün parlak metalik renginde
            no_txt = str(p["no"])
            no_w = ciz.textlength(no_txt, font=f_no)
            no_x_sag = c_x1 + 40
            ciz.text((no_x_sag - no_w, oy_y + 4), no_txt, font=f_no, fill=num_col)

            # Sağdaki Rozetler (K / KL)
            sag_x = c_x2 - 6
            if p["kaptan"]:
                ciz.rounded_rectangle([sag_x - 22, oy_y + 4, sag_x, oy_y + 24], radius=4, fill=(p_col[0], p_col[1], p_col[2], 75), outline=(255, 255, 255, 140), width=1)
                ciz.text((sag_x - 16, oy_y + 6), "K", font=f_badge, fill=(255, 255, 255))
                sag_x -= 28

            if p["kaleci"]:
                ciz.rounded_rectangle([sag_x - 30, oy_y + 4, sag_x, oy_y + 24], radius=4, fill=(16, 185, 129, 60), outline=(52, 211, 153, 160), width=1)
                ciz.text((sag_x - 24, oy_y + 6), "KL", font=f_badge, fill=(255, 255, 255))
                sag_x -= 36

            # Futbolcu Adı: %100 SAF KRİSTAL BEYAZ BOLD (Sıfır kontrast sorunu, maksimum lüks)
            ad_x = c_x1 + 50
            max_ad_w = sag_x - ad_x - 6
            ad_sig = _ad_akilli_sigdir(ciz, p["ad"], f_ad_bold, max_ad_w)
            ciz.text((ad_x, oy_y + 3), ad_sig, font=f_ad_bold, fill=(255, 255, 255))

            oy_y += satir_h

    y += saha_h + 10

    # =========================================================================
    # BÖLÜM 3: YEDEK KULÜBESİ
    # =========================================================================
    if kulube_h:
        ciz.rounded_rectangle([kenar, y, genislik - kenar, y + kulube_h], radius=14, fill=(10, 12, 16, 235), outline=(255, 255, 255, 45), width=1)
        f_kb = make_image._font(15, make_image.EKSEN_BASLIK)
        ciz.text((kenar + 18, y + 10), "YEDEK KULÜBESİ", font=f_kb, fill=(255, 255, 255))
        ciz.line([orta_x, y + 30, orta_x, y + kulube_h - 10], fill=(255, 255, 255, 20), width=1)

        f_ydk_bold = make_image._font(15, make_image.EKSEN_BASLIK)
        f_yno = make_image._font(13, make_image.EKSEN_BASLIK)

        for t_idx, (ydk_list, k_x1, k_x2, y_renk) in enumerate([
            (ev_yedekler, kenar + 16, orta_x - 12, ev_renkler),
            (dep_yedekler, orta_x + 12, genislik - kenar - 16, dep_renkler),
        ]):
            yp_col = y_renk.get("primary", (14, 165, 233))
            ys_col = y_renk.get("number", (255, 255, 255))
            sub_w = (k_x2 - k_x1 - 10) // 2
            for i, yp in enumerate(ydk_list[:8]):
                scol = i % 2
                srow = i // 2
                px = k_x1 + scol * (sub_w + 10)
                py = y + 32 + srow * 24

                # İnce füme kart
                ciz.rounded_rectangle([px, py, px + sub_w, py + 22], radius=4, fill=(255, 255, 255, 10))
                # Forma no (metalik kulüp rengi)
                ciz.text((px + 6, py + 3), str(yp["no"]), font=f_yno, fill=ys_col)
                # İsim (saf beyaz)
                ad_txt = yp["ad"] + (" (KL)" if yp["kaleci"] else "")
                ad_sig = _ad_akilli_sigdir(ciz, ad_txt, f_ydk_bold, sub_w - 32)
                ciz.text((px + 28, py + 2), ad_sig, font=f_ydk_bold, fill=(245, 245, 250))

        y += kulube_h + 10

    # =========================================================================
    # BÖLÜM 4: EKSİKLER & MAÇ NOTU
    # =========================================================================
    if alt_not:
        ciz.rounded_rectangle([kenar, y, genislik - kenar, y_alt], radius=12, fill=(10, 12, 16, 235), outline=(255, 255, 255, 45), width=1)
        ciz.rounded_rectangle([kenar, y, kenar + 5, y_alt], radius=2, fill=(255, 255, 255))
        f_not = make_image._font(17, make_image.EKSEN_BASLIK)
        alt_not_temiz = re.sub(r"[\u2600-\u27bf\U0001f300-\U0001f9ff⚠️📌🔴🚨★⭐⚽]", "", alt_not).strip()
        from src.sablonlar.ortak import metin_kutuya_sar
        not_satirlar = metin_kutuya_sar(ciz, alt_not_temiz, f_not, alan_w - 36, maks_satir=2)
        ny = y + (y_alt - y - len(not_satirlar) * 20) // 2
        for ns in not_satirlar:
            ciz.text((kenar + 18, ny), ns, font=f_not, fill=(255, 255, 255))
            ny += 20

    from src.sablonlar.ortak import ust_ve_alt_bar_bas
    return ust_ve_alt_bar_bas(
        gorsel,
        ayarlar=ayarlar,
        kaynak="Daily Brief Spor",
        rozet_metni="",
        rozet_renk=(255, 255, 255),
        sayfa=2,
        toplam_sayfa=2,
    )

print('Test module ready.')
