"""
medya_video.py — Video içeren haberler için Hibrit Carousel (2. Slayt Çerçeveli MP4 Video) motoru.

Kaynak haberde gerçek bir `.mp4` video bulunduğunda veya yerel video yolu verildiğinde:
  1. 1080x1920 Daily Brief şablon çerçevesi (144px 3D Logo, VİDEO HABER rozeti, Başlık, Kaynak ve 6 Sosyal İkon) üretilir.
  2. Haberin videosu merkezi 4:5 güvenli alanındaki ekran penceresine FFmpeg ile yerleştirilir.
  3. Instagram Graph API (`media_type=VIDEO`) ve Telegram (`sendMediaGroup` video öğesi) ile
     1. Slayt Kapak Fotoğrafı + 2. Slayt Video + 3. Slayt Detay Metni olarak hibrit carousel yayınlanır.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urljoin

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from src import make_image
from src.sablonlar.ortak import (
    cam_kart_ciz,
    metin_kutuya_sar,
    nokta_matrisi_ciz,
    temel_tuval_olustur,
    ust_ve_alt_bar_bas,
)

log = logging.getLogger(__name__)

_REKLAM_KELIMELERI = ("doubleclick", "googlesyndication", "adservice", "taboola", "outbrain", "preroll", " pixel")


def video_boyutunu_al(video_yolu: str | Path) -> tuple[int, int] | None:
    """ffprobe ile video dosyasının gerçek (genişlik, yükseklik) piksel boyutunu döndürür."""
    if not shutil.which("ffprobe"):
        return None
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0:s=x",
            str(video_yolu),
        ]
        sonuc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if sonuc.returncode == 0 and "x" in sonuc.stdout:
            parcalar = sonuc.stdout.strip().split("x")
            if len(parcalar) >= 2:
                w, h = int(parcalar[0]), int(parcalar[1])
                if w > 0 and h > 0:
                    return (w, h)
    except Exception as e:
        log.warning("video boyutu ffprobe ile okunamadı: %s", e)
    return None


def makaleden_video_url_cikar(html_metni: str, sayfa_url: str = "") -> str | None:
    """
    Haber sayfasının HTML kaynağından doğrudan oynatılabilir `.mp4` video adresini ayıklar.
    Reklam ve izleyici videolarını eler.
    """
    if not html_metni:
        return None

    kaliplar = [
        r'<meta[^>]+property=["\']og:video:secure_url["\'][^>]+content=["\']([^"\']+\.mp4[^"\']*)["\']',
        r'<meta[^>]+property=["\']og:video["\'][^>]+content=["\']([^"\']+\.mp4[^"\']*)["\']',
        r'<meta[^>]+name=["\']twitter:player:stream["\'][^>]+content=["\']([^"\']+\.mp4[^"\']*)["\']',
        r'"contentUrl"\s*:\s*"([^"]+\.mp4[^"]*)"',
        r'<source[^>]+src=["\']([^"\']+\.mp4[^"\']*)["\']',
        r'<video[^>]+src=["\']([^"\']+\.mp4[^"\']*)["\']',
    ]

    for kalip in kaliplar:
        for eslesme in re.finditer(kalip, html_metni, flags=re.IGNORECASE):
            aday = (eslesme.group(1) or "").strip().replace("\\/", "/")
            if not aday:
                continue
            if sayfa_url and aday.startswith("/"):
                aday = urljoin(sayfa_url, aday)
            if not aday.startswith(("http://", "https://")):
                continue
            kucuk = aday.casefold()
            if any(rk in kucuk for rk in _REKLAM_KELIMELERI):
                continue
            return aday
    return None


def video_cercevesi_ciz(
    haber: dict,
    ayarlar: dict,
    kaynak: str,
    arkaplan: Image.Image | None = None,
    sayfa: int = 1,
    toplam_sayfa: int = 2,
    arsiv_ibaresi: bool = False,
    video_boyut: tuple[int, int] | None = None,
    medya_turu: str = "video",
) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """
    1080x1920 tuval üzerinde kutucuksuz, geçişli ve şık tipografili video/fotoğraf çerçevesi üretir.
    Kaba kart kutuları yerine akıcı ambiyans ışıltısı, 3D difüzyon gölgesi ve zarif dikey çentik kullanır.
    Döner: `(cerceve_gorseli, (vx1, vy1, vx2, vy2))`
    """
    genislik = make_image.STORY_GENISLIK
    yukseklik = make_image.STORY_YUKSEKLIK
    kenar = ayarlar.get("gorsel", {}).get("kenar_bosluk", 64)
    dikey_kenar = ayarlar.get("gorsel", {}).get("dikey_guvenli_pay", make_image.STORY_GUVENLI_PAY)
    y_ust = dikey_kenar
    y_alt = yukseklik - dikey_kenar
    alan_g = genislik - 2 * kenar

    is_gorsel = (medya_turu == "gorsel")

    # 1. TEMEL ZEMİN & AMBİYANS IŞILTISI (GEÇİŞLİ)
    tema_koyu = (4, 16, 26)
    canvas = Image.new("RGB", (genislik, yukseklik), tema_koyu)

    if arkaplan is not None:
        try:
            bg_rgb = arkaplan.convert("RGB")
            ambiyans = bg_rgb.resize((genislik, yukseklik), Image.BILINEAR)
            ambiyans = ambiyans.filter(ImageFilter.GaussianBlur(radius=75))
            amb_perde = Image.new("RGBA", (genislik, yukseklik), (4, 14, 22, 218))
            ambiyans = Image.alpha_composite(ambiyans.convert("RGBA"), amb_perde).convert("RGB")
            canvas.paste(ambiyans, (0, 0))
        except Exception as e:
            log.warning("Ambiyans zemin üretilemedi: %s", e)

    # Üst ve alt güvenli pay degrade karartması (Story & 4:5 Feed uyumu)
    vignette = Image.new("RGBA", (genislik, yukseklik), (0, 0, 0, 0))
    v_ciz = ImageDraw.Draw(vignette)
    for y in range(0, y_ust + 30):
        a = int(220 * (1.0 - (y / (y_ust + 30))) ** 1.5)
        v_ciz.line([(0, y), (genislik, y)], fill=(2, 8, 14, a))
    for y in range(y_alt - 30, yukseklik):
        a = int(240 * ((y - (y_alt - 30)) / (yukseklik - (y_alt - 30))) ** 1.5)
        v_ciz.line([(0, y), (genislik, y)], fill=(2, 8, 14, a))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), vignette).convert("RGB")

    # 2. METİN VE GÖRSEL YÜKSEKLİĞİ ÖLÇÜMÜ (4:5 GÜVENLİ ALAN VE SIFIR TAŞMA GARANTİSİ)
    # Üst sınır: 144px logo (y=314..458). İçerik KESİNLİKLE y >= 474 başlar.
    # Alt sınır: Alt bilgi çubuğu (y=1556). İçerik KESİNLİKLE y <= 1515 biter.
    y_icerik_min = 474
    y_icerik_max = 1515
    kullanilabilir_toplam_h = y_icerik_max - y_icerik_min  # 1041 px

    baslik = (haber.get("ig_baslik") or haber.get("baslik_orj") or "").strip()
    alt_not = (haber.get("slayt_ozet") or haber.get("detay_metni") or haber.get("sana_etkisi") or "").strip()

    ciz_olcum = ImageDraw.Draw(canvas)
    f_bas = make_image._font(34, make_image.EKSEN_BASLIK)
    bas_satirlar = make_image._satirlara_bol(baslik, f_bas, alan_g, ciz_olcum) if baslik else []
    if len(bas_satirlar) > 3:
        bas_satirlar = bas_satirlar[:3]
        if not bas_satirlar[2].endswith("..."):
            bas_satirlar[2] = bas_satirlar[2].rstrip(". ") + "..."
    bas_satir_h = 42
    bas_toplam_h = len(bas_satirlar) * bas_satir_h

    # Video / Fotoğraf en-boy oranı (Sıfır ve negatif bölme korumalı)
    vb = video_boyut or haber.get("video_boyut")
    if vb and isinstance(vb, (list, tuple)) and len(vb) >= 2 and vb[0] > 0 and vb[1] > 0:
        ar = float(vb[0]) / float(vb[1])
    else:
        ar = 16.0 / 9.0

    # Metne yer bırakmak için görsel tavan yüksekliği
    metin_min_h = bas_toplam_h + 32  # Başlık ve görsel arası boşluk
    maks_foto_h = max(200, kullanilabilir_toplam_h - metin_min_h - 40)

    # En-boy oranına göre orantılı boyut hesapla
    if ar >= 1.2:
        kutu_w = alan_g
        kutu_h = int(kutu_w / ar)
        if kutu_h > maks_foto_h:
            kutu_h = maks_foto_h
            kutu_w = int(kutu_h * ar)
    elif ar <= 0.8:
        kutu_h = min(maks_foto_h, 620)
        kutu_w = int(kutu_h * ar)
    else:
        kutu_w = min(alan_g, 700)
        kutu_h = int(kutu_w / ar)
        if kutu_h > maks_foto_h:
            kutu_h = maks_foto_h
            kutu_w = int(kutu_h * ar)

    kutu_w = max(240, min(alan_g, (kutu_w // 2) * 2))
    kutu_h = max(180, min(maks_foto_h, (kutu_h // 2) * 2))

    # Kalan alana göre açıklama metnini bütçele (Alt bara taşma SIFIRLANDI)
    f_ozet = make_image._font(24, make_image.EKSEN_OZET)
    ozet_satir_h = 34
    kalan_metin_h = y_icerik_max - (y_icerik_min + kutu_h + 32 + bas_toplam_h + 20)

    if alt_not and kalan_metin_h >= 34:
        ozet_satirlar = make_image._satirlara_bol(alt_not, f_ozet, alan_g - 28, ciz_olcum)
        maks_ozet_satir = max(1, kalan_metin_h // ozet_satir_h)
        if len(ozet_satirlar) > maks_ozet_satir:
            ozet_satirlar = ozet_satirlar[:maks_ozet_satir]
            if ozet_satirlar and not ozet_satirlar[-1].endswith("..."):
                ozet_satirlar[-1] = ozet_satirlar[-1].rstrip(". ") + "..."
        ozet_toplam_h = len(ozet_satirlar) * ozet_satir_h
    else:
        ozet_satirlar = []
        ozet_toplam_h = 0

    metin_toplam_h = bas_toplam_h + (20 if ozet_toplam_h else 0) + ozet_toplam_h
    toplam_icerik_h = kutu_h + 32 + metin_toplam_h
    kalan_dikey_bosluk = max(0, kullanilabilir_toplam_h - toplam_icerik_h)

    # Dikeyde 4:5 merkezi güvenli alanda kusursuz hizalama
    baslangic_y = y_icerik_min + (kalan_dikey_bosluk // 2)

    vx1 = kenar + (alan_g - kutu_w) // 2
    fy1 = baslangic_y
    vx2 = vx1 + kutu_w
    vy2 = fy1 + kutu_h

    # 3. YUMUŞAK DİFÜZYON GÖLGESİ (KUTU DEĞİL, 3D DERİNLİK)
    golge_katmani = Image.new("RGBA", (genislik, yukseklik), (0, 0, 0, 0))
    g_ciz = ImageDraw.Draw(golge_katmani)
    g_ciz.rounded_rectangle([vx1 - 4, fy1 + 8, vx2 + 4, vy2 + 20], radius=24, fill=(0, 0, 0, 180))
    golge_katmani = golge_katmani.filter(ImageFilter.GaussianBlur(radius=24))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), golge_katmani).convert("RGB")

    # İnce lüks 1px kenarlık
    rim = Image.new("RGBA", (genislik, yukseklik), (0, 0, 0, 0))
    r_ciz = ImageDraw.Draw(rim)
    r_ciz.rounded_rectangle([vx1, fy1, vx2, vy2], radius=20, outline=(255, 255, 255, 38), width=1)
    canvas = Image.alpha_composite(canvas.convert("RGBA"), rim).convert("RGB")

    # 4. KUTUCUKSUZ ŞIK EDİTORYAL TİPOGRAFİ (BAŞLIK & AÇIKLAMA)
    metin_y = vy2 + 32

    # Başlık: Doğrudan tuval üzerine difüzyon gölgesiyle
    b_golge = Image.new("RGBA", (genislik, yukseklik), (0, 0, 0, 0))
    bg_ciz = ImageDraw.Draw(b_golge)
    by_g = metin_y
    for s in bas_satirlar:
        bg_ciz.text((kenar, by_g + 2), s.replace("**", ""), font=f_bas, fill=(0, 0, 0, 220))
        by_g += bas_satir_h
    b_golge = b_golge.filter(ImageFilter.GaussianBlur(8))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), b_golge).convert("RGB")
    ciz = ImageDraw.Draw(canvas, "RGBA")

    by = metin_y
    for s in bas_satirlar:
        ciz.text((kenar, by), s.replace("**", ""), font=f_bas, fill=(255, 255, 255))
        by += bas_satir_h

    # Detay / Arka plan açıklaması (Zarif dikey çentikli, kutucuksuz editoryal paragraf)
    if ozet_satirlar:
        metin_y = by + 20
        centik_h = len(ozet_satirlar) * ozet_satir_h
        centik_renk = (226, 170, 88) if is_gorsel else (6, 182, 212)
        ciz.rounded_rectangle([kenar, metin_y + 4, kenar + 4, metin_y + centik_h - 2], radius=2, fill=centik_renk)

        oy = metin_y
        for s in ozet_satirlar:
            ciz.text((kenar + 20, oy), s.replace("**", ""), font=f_ozet, fill=(226, 232, 240))
            oy += ozet_satir_h

    # 5. ÜST VE ALT KURUMSAL BARLAR (ust_ve_alt_bar_bas)
    rozet_txt = (haber.get("rozet_metni") or "HABERİN GÖRÜNTÜSÜ").strip() if is_gorsel else "VİDEO HABER DETAYI"
    rozet_renk = (226, 170, 88) if is_gorsel else (239, 68, 68)

    canvas = ust_ve_alt_bar_bas(
        canvas,
        ayarlar=ayarlar,
        kaynak=kaynak,
        rozet_metni=rozet_txt,
        rozet_renk=rozet_renk,
        ulke_kodu=haber.get("ulke_kodu") or None,
        ulke_adi=haber.get("ulke_adi") or None,
        sayfa=sayfa,
        toplam_sayfa=toplam_sayfa,
        arsiv_ibaresi=arsiv_ibaresi,
    )

    return canvas, (vx1, fy1, vx2, vy2)


def gorsel_detay_slayti_uret(
    haber: dict,
    gorsel_kaynak: Image.Image | str | Path,
    ayarlar: dict,
    kaynak: str,
    arkaplan: Image.Image | None = None,
    sayfa: int = 1,
    toplam_sayfa: int = 2,
    arsiv_ibaresi: bool = False,
) -> Image.Image | None:
    """
    Haberin sıcak görüntüsünü (olay yeri fotoğrafı, belge, uydu görüntüsü, basın fotoğrafı vb.)
    gerçek en/boy oranına göre kutucuksuz, geçişli ve şık tipografili Daily Brief formatında üretir.
    """
    from src.gorsel_kalite import kristal_netlestir

    if isinstance(gorsel_kaynak, (str, Path)):
        p = Path(gorsel_kaynak)
        if not p.exists() or p.stat().st_size == 0:
            return None
        try:
            foto = Image.open(p).convert("RGB")
        except Exception as e:
            log.warning("Görsel açılamadı (%s): %s", p, e)
            return None
    elif isinstance(gorsel_kaynak, Image.Image):
        try:
            foto = gorsel_kaynak.convert("RGB")
        except Exception as e:
            log.warning("Görsel dönüştürülemedi: %s", e)
            return None
    else:
        return None

    if foto.width <= 0 or foto.height <= 0:
        return None

    # Arka plan belirtilmemişse fotoğrafın kendisinden ambiyans zemin üret
    zemin_foto = arkaplan if arkaplan is not None else foto

    cerceve, (vx1, vy1, vx2, vy2) = video_cercevesi_ciz(
        haber=haber,
        ayarlar=ayarlar,
        kaynak=kaynak,
        arkaplan=zemin_foto,
        sayfa=sayfa,
        toplam_sayfa=toplam_sayfa,
        arsiv_ibaresi=arsiv_ibaresi,
        video_boyut=foto.size,
        medya_turu="gorsel",
    )
    vw = vx2 - vx1
    vh = vy2 - vy1

    # Fotoğrafı pencereye tam oturt ve kristal keskinleştir
    foto_fit = foto.resize((vw, vh), Image.LANCZOS)
    try:
        foto_fit = kristal_netlestir(foto_fit)
    except Exception:
        pass

    # Yuvarlak köşeli maske ile yapıştır (kutucuksuz, organik geçiş)
    maske = Image.new("L", (vw, vh), 0)
    m_ciz = ImageDraw.Draw(maske)
    m_ciz.rounded_rectangle([0, 0, vw, vh], radius=20, fill=255)
    cerceve.paste(foto_fit, (vx1, vy1), maske)

    return cerceve


def video_detay_slayti_uret(
    haber: dict,
    video_kaynak: str | Path,
    ayarlar: dict,
    kaynak: str,
    arkaplan: Image.Image | None = None,
    sayfa: int = 1,
    toplam_sayfa: int = 2,
    maks_sure_sn: int = 25,
) -> Path | None:
    """
    Verilen `.mp4` URL'sini veya yerel video dosyasını 1080x1920 Daily Brief
    detay çerçevesine yerleştirip `story-{id}-detay-video.mp4` olarak kaydeder.
    """
    if not shutil.which("ffmpeg"):
        log.warning("ffmpeg bulunamadı, video detay slaytı üretilemedi")
        return None

    make_image.CIKTI_KLASORU.mkdir(parents=True, exist_ok=True)
    haber_id = haber.get("id") or "ozel"
    cikti_yolu = make_image.CIKTI_KLASORU / f"story-{haber_id}-detay-video.mp4"

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        girdi_video = Path(str(video_kaynak))
        if str(video_kaynak).startswith(("http://", "https://")):
            indirilen = tmp_path / "kaynak.mp4"
            try:
                with requests.get(str(video_kaynak), stream=True, timeout=20, headers={"User-Agent": "Mozilla/5.0"}) as r:
                    r.raise_for_status()
                    toplam_bayt = 0
                    with open(indirilen, "wb") as f:
                        for parca in r.iter_content(chunk_size=65536):
                            if parca:
                                f.write(parca)
                                toplam_bayt += len(parca)
                                if toplam_bayt > 35 * 1024 * 1024:
                                    break
                girdi_video = indirilen
            except Exception as e:
                log.warning("Haber videosu indirilemedi (%s): %s", video_kaynak, e)
                return None

        if not girdi_video.exists() or girdi_video.stat().st_size < 1024:
            return None

        # Gerçek video en/boy oranına göre orantılı dinamik çerçeve üret
        vb = video_boyutunu_al(girdi_video)
        cerceve, (vx1, vy1, vx2, vy2) = video_cercevesi_ciz(
            haber, ayarlar, kaynak, arkaplan=arkaplan, sayfa=sayfa, toplam_sayfa=toplam_sayfa, video_boyut=vb
        )
        vw = ((vx2 - vx1) // 2) * 2
        vh = ((vy2 - vy1) // 2) * 2

        bg_yolu = tmp_path / "cerceve.jpg"
        cerceve.save(bg_yolu, "JPEG", quality=95)

        filtre_kompleks = (
            f"[1:v]scale={vw}:{vh}:force_original_aspect_ratio=decrease,"
            f"pad={vw}:{vh}:(ow-iw)/2:(oh-ih)/2:color=#040A12[vid];"
            f"[0:v][vid]overlay={vx1}:{vy1}:shortest=1[outv]"
        )
        komut = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", str(bg_yolu),
            "-i", str(girdi_video),
            "-t", str(maks_sure_sn),
            "-filter_complex", filtre_kompleks,
            "-map", "[outv]",
            "-map", "1:a?",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "21",
            "-pix_fmt", "yuv420p",
            "-g", "60",
            "-c:a", "aac",
            "-b:a", "128k",
            "-ar", "44100",
            "-ac", "2",
            "-movflags", "+faststart",
            str(cikti_yolu),
        ]
        try:
            sonuc = subprocess.run(komut, capture_output=True, text=True, timeout=90)
            if sonuc.returncode != 0 or not cikti_yolu.exists():
                log.warning("FFmpeg video detay slaytı hatası: %s", (sonuc.stderr or "")[-250:])
                return None
            return cikti_yolu
        except Exception as e:
            log.warning("Video detay slaytı oluşturulurken hata: %s", e)
            return None
