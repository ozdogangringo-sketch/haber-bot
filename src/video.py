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
from PIL import Image, ImageFilter, ImageOps
import imageio

log = logging.getLogger(__name__)

CIKTI_KLASORU = Path("data") / "output"
HEDEF_GENISLIK = 1080
HEDEF_YUKSEKLIK = 1920


def reels_dikey_gorselleri_uret(
    gorsel_kaynaklari: list[Path | str],
    cikti_dizini: Path | str | None = None,
) -> list[Path]:
    """
    4:5 formatındaki slayt görsellerini veya URL'leri alır,
    arka planı sinematik derin okyanus petrolü blur efektiyle doldurarak
    1080x1920 (9:16) tam dikey Reels / Story görselleri üretir.
    """
    if cikti_dizini is None:
        cikti_dizini = CIKTI_KLASORU / "reels_9_16"
    else:
        cikti_dizini = Path(cikti_dizini)
    cikti_dizini.mkdir(parents=True, exist_ok=True)

    uretilen_yollar: list[Path] = []
    for idx, kaynak in enumerate(gorsel_kaynaklari):
        try:
            if str(kaynak).startswith("http://") or str(kaynak).startswith("https://"):
                r = requests.get(str(kaynak), timeout=20)
                img = Image.open(io.BytesIO(r.content))
            else:
                p = Path(kaynak)
                if not p.exists():
                    continue
                img = Image.open(p)

            dikey_img = _reels_kare_hazirla(img)
            hedef_yol = cikti_dizini / f"slayt_9_16_{idx + 1:02d}.jpg"
            dikey_img.save(hedef_yol, "JPEG", quality=95)
            uretilen_yollar.append(hedef_yol)
        except Exception as e:
            log.warning("9:16 görsel üretilemedi (%s): %s", kaynak, e)

    return uretilen_yollar


def _reels_kare_hazirla(img: Image.Image, genislik: int = HEDEF_GENISLIK, yukseklik: int = HEDEF_YUKSEKLIK) -> Image.Image:
    """
    1080x1350 veya farklı boyutlardaki slaytı 1080x1920 dikey Reels zeminine oturtur.
    Arka plana hafif bulanıklaştırılmış ve karartılmış atmosfer görseli koyar.
    """
    if img.size == (genislik, yukseklik):
        return img.convert("RGB")

    # 1. Arka Plan: Orijinal görseli büyüt ve bulanıklaştır
    arkaplan = ImageOps.fit(img, (genislik, yukseklik), method=Image.Resampling.LANCZOS)
    arkaplan = arkaplan.filter(ImageFilter.GaussianBlur(radius=25))
    
    # Karartma katmanı (%40 siyah)
    karartma = Image.new("RGB", (genislik, yukseklik), (10, 15, 25))
    arkaplan = Image.blend(arkaplan, karartma, alpha=0.55)

    # 2. Ön Plan: Slaytı orantılı boyutlandırıp merkeze yerleştir
    oran = min(genislik / img.width, (yukseklik - 120) / img.height)
    yeni_w = int(img.width * oran)
    yeni_h = int(img.height * oran)
    on_plan = img.resize((yeni_w, yeni_h), Image.Resampling.LANCZOS)

    # Merkeze yapıştır
    pos_x = (genislik - yeni_w) // 2
    pos_y = (yukseklik - yeni_h) // 2
    arkaplan.paste(on_plan, (pos_x, pos_y))

    return arkaplan


def slaytlardan_reels_uret(
    gorsel_yollari: list[Path | str],
    cikti_yolu: Path | str | None = None,
    fps: int = 24,
    slayt_suresi: float = 3.0,
    gecis_suresi: float = 0.4,
) -> Path:
    """
    Verilen slayt görsellerinden 1080x1920 MP4 Reels videosu üretir.

    * `slayt_suresi`: Her slaytın ekranda kalma süresi (saniye).
    * `gecis_suresi`: İki slayt arasındaki yumuşak kararma geçişi (saniye).
    * `fps`: Saniyedeki kare sayısı (24 veya 30).
    """
    if not gorsel_yollari:
        raise ValueError("Video üretimi için en az 1 görsel gerekli")

    CIKTI_KLASORU.mkdir(parents=True, exist_ok=True)
    if cikti_yolu is None:
        cikti_yolu = CIKTI_KLASORU / f"reels_{Path(gorsel_yollari[0]).stem}.mp4"
    else:
        cikti_yolu = Path(cikti_yolu)

    log.info("Reels videosu üretiliyor: %s slayt -> %s", len(gorsel_yollari), cikti_yolu)

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
        quality=8,
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
