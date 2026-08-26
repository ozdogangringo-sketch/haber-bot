"""
video.py — Slaytlardan 9:16 MP4 Reels & Video Üretim Motoru

Slayt görsellerini (1080x1350 veya 1080x1920) alır, sinematik yakınlaştırma
(Ken Burns zoom) ve yumuşak geçiş efekti (crossfade) uygulayarak
Instagram Reels, Stories ve Shorts için optimize edilmiş MP4 videosu üretir.
"""

from __future__ import annotations

import logging
from pathlib import Path
import numpy as np
import io
import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
import imageio

log = logging.getLogger(__name__)

KOK = Path(__file__).resolve().parent.parent
FONT_YOLU = KOK / "assets" / "fonts" / "Inter-Variable.ttf"
LOGO_YOLU = KOK / "assets" / "logo_circular.png"
CIKTI_KLASORU = KOK / "data" / "output"
HEDEF_GENISLIK = 1080
HEDEF_YUKSEKLIK = 1920


def _font(punto: int, agirlik: float = 600.0) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT_YOLU), punto)
    try:
        f.set_variation_by_axes([20.0, agirlik])
    except Exception:
        pass
    return f


def _cercevele_9_16(img: Image.Image, baslik_rozet: str = "") -> Image.Image:
    """
    1080x1350 formatındaki slayt, detay veya piyasa kartını,
    hiçbir yapay kutu, çerçeve veya renk ayrımı OLMADAN,
    üstünü görselin/gradyanın doğal devamı, altını ise taban renginin devamı
    olarak dikişsiz 1080x1920 (9:16) Reels/Story zeminine uzatır.
    """
    genislik, yukseklik = HEDEF_GENISLIK, HEDEF_YUKSEKLIK
    w, h = img.size
    if (w, h) == (genislik, yukseklik):
        return img.convert("RGB")

    card_y = (yukseklik - h) // 2  # 285
    tuval = Image.new("RGB", (genislik, yukseklik))

    # 1. Üst Bölgeyi Dikişsiz Uzat (y = 0..285)
    # Görselin en üst satırını yukarı doğru pürüzsüzce uzat
    ust_cizgi = img.crop((0, 0, w, 2)).resize((w, card_y), Image.LANCZOS)
    tuval.paste(ust_cizgi, (0, 0))

    # 2. Alt Bölgeyi Dikişsiz Uzat (y = 1635..1920)
    # Görselin en alt satırını aşağı doğru pürüzsüzce uzat
    alt_cizgi = img.crop((0, h - 2, w, h)).resize((w, yukseklik - (card_y + h)), Image.LANCZOS)
    tuval.paste(alt_cizgi, (0, card_y + h))

    # 3. 4:5 Görseli merkez dikişsiz alana yerleştir
    tuval.paste(img, (0, card_y))

    return tuval


def reels_dikey_gorselleri_uret(
    gorsel_kaynaklari: list[Path | str],
    cikti_dizini: Path | str | None = None,
    haberler: list | None = None,
    ayarlar: dict | None = None,
) -> list[Path]:
    """
    Tüm slaytları kusursuz 1080x1920 (9:16) Story/Reels görsellerine dönüştürür.
    Haberler için doğrudan yerel story_haber() çağrılır, kartlar için ise
    derin petrol çerçeve kullanılır.
    """
    from . import make_image

    if cikti_dizini is None:
        cikti_dizini = CIKTI_KLASORU / "reels_9_16"
    else:
        cikti_dizini = Path(cikti_dizini)
    cikti_dizini.mkdir(parents=True, exist_ok=True)

    uretilen_yollar: list[Path] = []
    
    for idx, kaynak in enumerate(gorsel_kaynaklari):
        hedef_yol = cikti_dizini / f"slayt_9_16_{idx + 1:02d}.jpg"
        
        # Eğer bu sıradaki haber verisi ve ayarlar mevcutsa
        haber = dict(haberler[idx]) if haberler and idx < len(haberler) else None
        
        # 1. Öncelik: Eğer haberin story_url'i varsa doğrudan indirip kullan
        if haber and haber.get("story_url"):
            try:
                r = requests.get(haber["story_url"], timeout=20)
                if r.status_code == 200:
                    with open(hedef_yol, "wb") as f:
                        f.write(r.content)
                    uretilen_yollar.append(hedef_yol)
                    continue
            except Exception as e:
                log.warning("story_url indirilemedi: %s", e)

        # 2. Öncelik: Haberin kendi metinleriyle yerel story_haber() çiz
        if haber and ayarlar and haber.get("ig_baslik"):
            try:
                baslik = haber.get("ig_baslik") or haber.get("baslik_orj") or ""
                ozet = haber.get("slayt_ozet") or ""
                kaynak_adi = make_image.kaynak_gosterim_adi(haber.get("kaynak", ""), ayarlar)
                kategori = haber.get("kategori", "turkiye")
                
                # Varsa orijinal arka plan görseli
                arkaplan_img = None
                if haber.get("gorsel_yolu") and Path(haber["gorsel_yolu"]).exists():
                    try:
                        arkaplan_img = Image.open(haber["gorsel_yolu"])
                    except Exception:
                        pass

                story_img = make_image.story_haber(
                    baslik=baslik,
                    ozet=ozet,
                    kaynak=kaynak_adi,
                    ayarlar=ayarlar,
                    arkaplan=arkaplan_img,
                    kategori=kategori,
                    ulke_kodu=haber.get("ulke_kodu"),
                    ulke_adi=haber.get("ulke_adi"),
                )
                story_img.save(hedef_yol, "JPEG", quality=95)
                uretilen_yollar.append(hedef_yol)
                continue
            except Exception as e:
                log.warning("Yerel story_haber çizilemedi: %s", e)

        # 3. Öncelik (Piyasa Isı Haritası / Tablosu / Fallback): 4:5 kartı zarif petrol 9:16 çerçeveye al
        try:
            if str(kaynak).startswith("http://") or str(kaynak).startswith("https://"):
                r = requests.get(str(kaynak), timeout=20)
                img = Image.open(io.BytesIO(r.content))
            else:
                p = Path(kaynak)
                if not p.exists():
                    continue
                img = Image.open(p)

            dikey_img = _cercevele_9_16(img)
            dikey_img.save(hedef_yol, "JPEG", quality=95, subsampling=0, optimize=True)
            uretilen_yollar.append(hedef_yol)
        except Exception as e:
            log.warning("9:16 çerçeveleme hatası (%s): %s", kaynak, e)

    return uretilen_yollar


def _reels_kare_hazirla(img: Image.Image, genislik: int = HEDEF_GENISLIK, yukseklik: int = HEDEF_YUKSEKLIK) -> Image.Image:
    """Video üretiminde her kareyi 1080x1920 zeminine yerleştirir."""
    return _cercevele_9_16(img)


def slaytlardan_reels_uret(
    gorsel_yollari: list[Path | str],
    cikti_yolu: Path | str | None = None,
    fps: int = 30,
    slayt_suresi: float = 3.5,
    gecis_suresi: float = 0.4,
) -> Path:
    """
    Verilen slayt görsellerinden 1080x1920 MP4 Reels videosu üretir.

    * `slayt_suresi`: Her slaytın ekranda kalma süresi (saniye).
    * `gecis_suresi`: İki slayt arasındaki yumuşak kararma geçişi (saniye).
    * `fps`: Saniyedeki kare sayısı (30 fps Instagram için en ideal).
    """
    if not gorsel_yollari:
        raise ValueError("Video üretimi için en az 1 görsel gerekli")

    CIKTI_KLASORU.mkdir(parents=True, exist_ok=True)
    if cikti_yolu is None:
        cikti_yolu = CIKTI_KLASORU / f"reels_{Path(gorsel_yollari[0]).stem}.mp4"
    else:
        cikti_yolu = Path(cikti_yolu)

    log.info("Reels videosu üretiliyor: %s slayt -> %s (fps=%s)", len(gorsel_yollari), cikti_yolu, fps)

    # 1. Tüm görselleri 1080x1920 RGB formatına dönüştür
    kareler_ham: list[Image.Image] = []
    for yol in gorsel_yollari:
        p = Path(yol)
        if not p.exists():
            log.warning("Görsel bulunamadı, atlanıyor: %s", p)
            continue
        with Image.open(p) as img:
            kareler_ham.append(_reels_kare_hazirla(img))

    if not kareler_ham:
        raise RuntimeError("Hiçbir görsel işlenemedi")

    toplam_kare_slayt = int(fps * slayt_suresi)
    gecis_kare_sayisi = int(fps * gecis_suresi)
    sabit_kare_sayisi = max(1, toplam_kare_slayt - gecis_kare_sayisi)

    writer = imageio.get_writer(
        str(cikti_yolu),
        fps=fps,
        codec="libx264",
        pixelformat="yuv420p",
        macro_block_size=1,
        quality=9,
    )

    try:
        for idx, img_simdiki in enumerate(kareler_ham):
            img_sonraki = kareler_ham[(idx + 1) % len(kareler_ham)] if len(kareler_ham) > 1 else None

            # Ken Burns / Hafif Yakınlaştırma (1.00 -> 1.03)
            for k in range(sabit_kare_sayisi):
                t = k / float(toplam_kare_slayt)
                olcek = 1.0 + (0.03 * t)
                
                w = int(HEDEF_GENISLIK * olcek)
                h = int(HEDEF_YUKSEKLIK * olcek)
                crop_x = (w - HEDEF_GENISLIK) // 2
                crop_y = (h - HEDEF_YUKSEKLIK) // 2

                zoom_img = img_simdiki.resize((w, h), Image.Resampling.BILINEAR)
                zoom_crop = zoom_img.crop((crop_x, crop_y, crop_x + HEDEF_GENISLIK, crop_y + HEDEF_YUKSEKLIK))
                
                writer.append_data(np.array(zoom_crop))

            # Yumuşak Geçiş (Crossfade)
            if idx < len(kareler_ham) - 1 and img_sonraki:
                for k in range(gecis_kare_sayisi):
                    alpha = (k + 1) / float(gecis_kare_sayisi)
                    gecis_img = Image.blend(img_simdiki, img_sonraki, alpha)
                    writer.append_data(np.array(gecis_img))

    finally:
        writer.close()

    log.info("Reels videosu başarıyla oluşturuldu: %s (boyut: %.2f MB)",
             cikti_yolu, cikti_yolu.stat().st_size / (1024 * 1024))
    return cikti_yolu
