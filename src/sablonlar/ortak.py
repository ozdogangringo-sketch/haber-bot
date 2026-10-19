"""
ortak.py — Özel detay slaytı şablonları (spor_kadro, hava_durumu, karsilastirma,
rehber_adim, sirali_liste) için ortak 1080x1920 (4:5 güvenli alanlı) tuval,
üst bar (144px 3D logo + şablon rozeti + ülke bayrağı) ve alt bilgi çubuğu.
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFilter

from src import make_image


def temel_tuval_olustur(
    ayarlar: dict,
    kategori: str = "turkiye",
    arkaplan: Image.Image | None = None,
    tema_alt_renk: tuple[int, int, int] | None = None,
) -> tuple[Image.Image, int, int, int, int]:
    """
    1080x1920 dikey tuval ve merkezi 4:5 (STORY_GUVENLI_PAY = 330) güvenli alan sınırlarını hazırlar.
    Döner: `(gorsel, kenar, dikey_kenar, y_icerik_ust, y_icerik_alt)`
    """
    g = ayarlar.get("gorsel", {})
    genislik = make_image.STORY_GENISLIK
    yukseklik = make_image.STORY_YUKSEKLIK
    kenar = int(g.get("kenar_bosluk", 68))
    dikey_kenar = make_image.STORY_GUVENLI_PAY

    if arkaplan is not None:
        oran = max(genislik / arkaplan.width, yukseklik / arkaplan.height)
        yeni_w, yeni_h = int(arkaplan.width * oran), int(arkaplan.height * oran)
        foto_buyuk = arkaplan.resize((yeni_w, yeni_h), Image.LANCZOS)
        x_kirp = (yeni_w - genislik) // 2
        y_kirp = (yeni_h - yukseklik) // 2
        gorsel = foto_buyuk.crop((x_kirp, y_kirp, x_kirp + genislik, y_kirp + yukseklik))
        gorsel = gorsel.filter(ImageFilter.GaussianBlur(radius=14))
        p_r, p_g, p_b = tema_alt_renk if tema_alt_renk else (4, 16, 26)
        perde = Image.new("RGBA", (genislik, yukseklik), (p_r, p_g, p_b, 232))
        gorsel = Image.alpha_composite(gorsel.convert("RGBA"), perde).convert("RGB")
    else:
        gorsel = make_image.arkaplan_uret_yedek(kategori, genislik, yukseklik, g)

    y_icerik_ust = dikey_kenar + 122
    alt_bilgi_y = yukseklik - dikey_kenar - 34
    y_icerik_alt = alt_bilgi_y - 28
    return gorsel, kenar, dikey_kenar, y_icerik_ust, y_icerik_alt


def ust_ve_alt_bar_bas(
    gorsel: Image.Image,
    ayarlar: dict,
    kaynak: str,
    rozet_metni: str,
    rozet_renk: tuple[int, int, int] = (6, 182, 212),
    ulke_kodu: str | None = None,
    ulke_adi: str | None = None,
    sayfa: int = 1,
    toplam_sayfa: int = 2,
    arsiv_ibaresi: bool = False,
) -> Image.Image:
    """
    144px 3D Daily Brief logosunu, şablon rozetini, ülke bayrağını, kaynak satırını,
    sayfa numarasını ve 6 sosyal medya ikonunu standart koordinatlara basar.
    """
    g = ayarlar.get("gorsel", {})
    genislik = make_image.STORY_GENISLIK
    yukseklik = make_image.STORY_YUKSEKLIK
    kenar = int(g.get("kenar_bosluk", 68))
    dikey_kenar = make_image.STORY_GUVENLI_PAY
    alt_bilgi_y = yukseklik - dikey_kenar - 34

    # 1. Sol üst 144px 3D logo
    gorsel = make_image._logoyu_bas(gorsel, kenar, dikey_kenar - 16, boy=144)
    ciz = ImageDraw.Draw(gorsel)

    # 2. Şablon kategori rozeti
    if rozet_metni:
        etiket_font = make_image._font(23, make_image.EKSEN_KUCUK)
        etiket_temiz = make_image._buyuk_harf(rozet_metni.strip())
        metin_g = ciz.textlength(etiket_temiz, font=etiket_font)
        rx1 = kenar + 162
        ry1 = dikey_kenar + 32
        rx2 = int(rx1 + metin_g + 32)
        ry2 = dikey_kenar + 78
        ciz.rounded_rectangle([rx1, ry1, rx2, ry2], radius=8, fill=rozet_renk)
        ciz.text((rx1 + 16, ry1 + 10), etiket_temiz, font=etiket_font, fill=(255, 255, 255))

    # 3. Alt bilgi satırı (Kaynak + Sayfa Göstergesi + 6 Sosyal İkon)
    kucuk = make_image._font(26, make_image.EKSEN_KUCUK)

    story_ayarlar = {
        **ayarlar,
        "gorsel": {
            **g,
            "genislik": genislik,
            "yukseklik": yukseklik,
            "dikey_guvenli_pay": dikey_kenar,
        },
    }

    kanallar = (ayarlar.get("sosyal", {}) or {}).get("kanallar") or []
    boy = g.get("kanal_ikon_boyu", 26)
    toplam_g = len(kanallar) * boy + (len(kanallar) - 1) * 14 if kanallar else 0

    if toplam_sayfa > 1:
        gosterge = f"{sayfa}/{toplam_sayfa}"
        gen = ciz.textlength(gosterge, font=kucuk)
        ciz.text((genislik - kenar - gen, alt_bilgi_y), gosterge,
                 font=kucuk, fill=(198, 206, 222))
        gecici = {
            **story_ayarlar,
            "gorsel": {
                **story_ayarlar["gorsel"],
                "kenar_bosluk": kenar + int(gen) + 24,
            },
        }
        ikon_sol = genislik - (kenar + int(gen) + 24) - toplam_g
        make_image._kaynak_satiri_ciz(ciz, kenar, alt_bilgi_y, kaynak, arsiv_ibaresi=arsiv_ibaresi, azami_sag_x=ikon_sol - 20)
        gorsel = make_image.kanal_ikonlari_bas(gorsel, gecici, alt_bilgi_y + 13)
    else:
        ikon_sol = genislik - kenar - toplam_g
        make_image._kaynak_satiri_ciz(ciz, kenar, alt_bilgi_y, kaynak, arsiv_ibaresi=arsiv_ibaresi, azami_sag_x=ikon_sol - 20)
        gorsel = make_image.kanal_ikonlari_bas(gorsel, story_ayarlar, alt_bilgi_y + 13)

    if ulke_kodu:
        gorsel = make_image._bayragi_bas(gorsel, ulke_kodu, ulke_adi, dikey_kenar)

    return gorsel


def cam_kart_ciz(
    gorsel: Image.Image,
    kutu: list[int] | tuple[int, int, int, int],
    dolgu: tuple[int, int, int, int] = (13, 25, 42, 215),
    kenarlik: tuple[int, int, int, int] | None = (255, 255, 255, 34),
    yaricap: int = 18,
    sol_centik: tuple[int, int, int] | None = None,
) -> Image.Image:
    """
    Yarı saydam lüks glassmorphism kartı ve opsiyonel sol renk çentiği çizer.
    """
    katman = Image.new("RGBA", gorsel.size, (0, 0, 0, 0))
    kc = ImageDraw.Draw(katman)
    x1, y1, x2, y2 = [int(v) for v in kutu]
    kc.rounded_rectangle(
        [x1, y1, x2, y2],
        radius=yaricap,
        fill=dolgu,
        outline=kenarlik,
        width=1 if kenarlik else 0,
    )
    if sol_centik:
        kc.rounded_rectangle(
            [x1, y1 + 10, x1 + 6, y2 - 10],
            radius=3,
            fill=(*sol_centik, 255),
        )
    return Image.alpha_composite(gorsel.convert("RGBA"), katman).convert("RGB")


def metin_kutuya_sar(
    ciz: ImageDraw.ImageDraw,
    metin: str,
    font,
    maks_genislik: int,
    maks_satir: int = 2,
) -> list[str]:
    """Metni verilen piksel genişliğine ve azami satır sayısına göre böler."""
    temiz = (metin or "").replace("**", "").strip()
    if not temiz:
        return []
    satirlar = make_image._satirlara_bol(temiz, font, maks_genislik, ciz)
    if len(satirlar) > maks_satir:
        satirlar = satirlar[:maks_satir]
        son = satirlar[-1].rstrip(" .,;:")
        if not son.endswith("…"):
            satirlar[-1] = son + "…"
    return satirlar
