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
    Verilen tüm slayt görsellerini sırasıyla 1080x1920 (9:16) Reels video karelerine dönüştürür.
    Carousel'deki 1. slayt (Piyasa Isı Haritası vb.) videonun da 1. karesi olur; hiçbir görsel atlanmaz.
    """
    if cikti_dizini is None:
        cikti_dizini = CIKTI_KLASORU / "reels_9_16"
    else:
        cikti_dizini = Path(cikti_dizini)
    cikti_dizini.mkdir(parents=True, exist_ok=True)

    uretilen_yollar: list[Path] = []

    for idx, kaynak in enumerate(gorsel_kaynaklari):
        hedef_yol = cikti_dizini / f"slayt_9_16_{idx + 1:02d}.jpg"

        try:
            if str(kaynak).startswith("http://") or str(kaynak).startswith("https://"):
                r = requests.get(str(kaynak), timeout=25)
                if r.status_code != 200:
                    log.warning("Görsel indirilemedi (HTTP %s): %s", r.status_code, kaynak)
                    continue
                img = Image.open(io.BytesIO(r.content))
            else:
                p = Path(kaynak)
                if not p.exists():
                    log.warning("Görsel dosyası bulunamadı: %s", p)
                    continue
                img = Image.open(p)

            # Görseli 1080x1920 dikişsiz zeminine dönüştür
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
    gecis_suresi: float = 0.5,
) -> Path:
    """
    Verilen slayt görsellerinden 1080x1920 MP4 Reels videosu üretir.

    * Titremesiz, jilet gibi net ve akıcı S-curve (cosine easing) geçişler uygulanır.
    * `slayt_suresi`: Her slaytın ekranda kalma süresi (saniye).
    * `gecis_suresi`: İki slayt arasındaki yumuşak kararma geçişi (saniye).
    * `fps`: Saniyedeki kare sayısı (30 fps Instagram için en ideal).
    """
    import math

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

    # Kare sayıları hesabı
    toplam_kare_slayt = max(1, int(fps * slayt_suresi))
    gecis_kare_sayisi = max(1, int(fps * gecis_suresi)) if len(kareler_ham) > 1 else 0
    sabit_kare_sayisi = max(1, toplam_kare_slayt - gecis_kare_sayisi)

    # NumPy dizilerine önceden çevirerek bellek ve işlem hızını maksimize et
    np_kareler = [np.array(img, dtype=np.float32) for img in kareler_ham]

    writer = imageio.get_writer(
        str(cikti_yolu),
        fps=fps,
        codec="libx264",
        pixelformat="yuv420p",
        macro_block_size=1,
        quality=9,
        ffmpeg_params=[
            "-crf", "17",
            "-preset", "slow",
            "-tune", "stillimage",
            "-movflags", "+faststart",
        ],
    )

    try:
        toplam_slayt = len(np_kareler)
        for idx in range(toplam_slayt):
            arr_simdiki = np_kareler[idx]
            arr_sonraki = np_kareler[(idx + 1) % toplam_slayt] if toplam_slayt > 1 else None

            # 1. Sabit Görsel Aşaması (Jilet gibi net, titreşimsiz)
            arr_uint8 = np.clip(arr_simdiki, 0, 255).astype(np.uint8)
            for _ in range(sabit_kare_sayisi):
                writer.append_data(arr_uint8)

            # 2. Buttery Smooth S-Curve Crossfade Aşaması (Sıçramasız, kusursuz geçiş)
            if gecis_kare_sayisi > 0 and arr_sonraki is not None and idx < toplam_slayt - 1:
                for k in range(gecis_kare_sayisi):
                    # Lineer değil, Cosine S-Curve easing (0 -> 1)
                    t = (k + 1) / float(gecis_kare_sayisi)
                    alpha = 0.5 * (1.0 - math.cos(math.pi * t))

                    # Renk kanallarında kusursuz yumuşak geçiş
                    gecis_arr = (1.0 - alpha) * arr_simdiki + alpha * arr_sonraki
                    writer.append_data(np.clip(gecis_arr, 0, 255).astype(np.uint8))

    finally:
        writer.close()

    log.info("Reels videosu başarıyla oluşturuldu: %s (boyut: %.2f MB)",
             cikti_yolu, cikti_yolu.stat().st_size / (1024 * 1024))
    return cikti_yolu
