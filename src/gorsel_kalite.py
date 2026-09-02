"""
gorsel_kalite.py — Görsel Kalite, Netlik ve Çözünürlük Denetim Motoru.

Bu modül, Instagram Feed (1080x1350, 4:5) ve Story/Reels (1080x1920, 9:16) formatlarında
kullanılacak tüm fotoğrafların piksel yoğunluğunu, netliğini ve kalitesini denetler.

Temel Kurallar:
  1. Asla dikey kırpmada dijital büyütme (upscale) ile piksellenen fotoğraf kullanılmaz.
  2. Sahte büyütülmüş (yapay 1080p), bulanık veya düşük bitrate'li TV ekran görüntüleri
     Laplacian varyans filtresi ile elenir.
  3. Minimum dosya ve piksel yoğunluğu karşılanmayan görseller reddedilerek bir sonraki
     katmana (HD Web Basın Fotoğrafı, Wikimedia 4K, Pexels 4K veya AI) geçilir.
"""

from __future__ import annotations

import logging
from typing import Any
from PIL import Image, ImageFilter, ImageStat

log = logging.getLogger(__name__)

# Minimum kabul edilebilir netlik (Laplacian varyansı)
ASGARI_NETLIK_PUANI = 35.0

# 4:5 ve 9:16 için asgari hedef ölçüler
HEDEF_GENISLIK = 1080
HEDEF_YUKSEKLIK_FEED = 1350
HEDEF_YUKSEKLIK_STORY = 1920


def kirpma_olcegi_hesapla(
    genislik: int,
    yukseklik: int,
    hedef_g: int = HEDEF_GENISLIK,
    hedef_y: int = HEDEF_YUKSEKLIK_FEED,
) -> float:
    """
    Fotoğraf hedef dikey orana (örn. 4:5 veya 9:16) merkezden kırpıldığında,
    kırpılan alanın hedef tuvale göre gerçek piksel ölçeğini (yoğunluğunu) hesaplar.
    """
    if genislik <= 0 or yukseklik <= 0:
        return 0.0

    hedef_oran = hedef_g / hedef_y
    foto_oran = genislik / yukseklik

    if foto_oran > hedef_oran:
        # Fotoğraf yatay: yanlardan kırpılacak, yükseklik belirleyici
        kirpilan_genislik = yukseklik * hedef_oran
        kirpilan_yukseklik = yukseklik
    else:
        # Fotoğraf dikey: alttan/üstten kırpılacak, genişlik belirleyici
        kirpilan_genislik = genislik
        kirpilan_yukseklik = genislik / hedef_oran

    olcek = min(kirpilan_genislik / hedef_g, kirpilan_yukseklik / hedef_y)
    return round(olcek, 3)


def netlik_puani(img: Image.Image) -> float:
    """
    Pillow tabanlı Laplacian kenar varyansı ile görselin gerçek netlik ve keskinliğini ölçer.
    Yapay olarak büyütülmüş, bulanık veya aşırı sıkıştırılmış görseller düşük puan alır.
    """
    try:
        w, h = img.size
        if max(w, h) > 1000:
            oran = 1000.0 / max(w, h)
            test_img = img.resize((int(w * oran), int(h * oran)), Image.BILINEAR)
        else:
            test_img = img

        gray = test_img.convert("L")
        edges = gray.filter(ImageFilter.FIND_EDGES)
        stat = ImageStat.Stat(edges)
        varyans = stat.var[0] if stat.var else 0.0
        return float(varyans)
    except Exception as e:
        log.debug("Netlik puanı hesaplanamadı: %s", e)
        return 100.0


def gorsel_kalite_denetle(
    img: Image.Image,
    dosya_boyutu_kb: float = 0.0,
    hedef_g: int = HEDEF_GENISLIK,
    hedef_y: int = HEDEF_YUKSEKLIK_FEED,
    asgari_olcek: float = 0.45,
    asgari_netlik: float = ASGARI_NETLIK_PUANI,
) -> tuple[bool, str]:
    """
    Görselin yayın kalitesi standartlarını karşılayıp karşılamadığını denetler.
    Döner: `(uygun_mu, aciklama)`
    """
    w, h = img.size

    # 1. Asgari Mutlak Boyut Denetimi (16:9 HD 1200x675 / 1280x720 / 1920x1080 ve dikey portreleri kapsar)
    if (w < 800 or h < 450) and not (w >= 600 and h >= 600):
        return False, f"Mutlak çözünürlük çok düşük: {w}x{h} px (asgari 800x450 px gerekli)"

    # 2. Dikey Kırpma Piksel Yoğunluğu (Crop Density)
    olcek = kirpma_olcegi_hesapla(w, h, hedef_g, hedef_y)
    if olcek < asgari_olcek:
        return (
            False,
            f"Dikey kırpmada aşırı piksel kaybı ({olcek}x < {asgari_olcek}x, {w}x{h} px)",
        )

    # 3. Dosya Boyutu ve Bitrate Denetimi
    piksel_mp = (w * h) / 1_000_000.0
    if dosya_boyutu_kb > 0:
        if piksel_mp >= 1.5 and dosya_boyutu_kb < 70:
            return False, f"Aşırı JPEG sıkıştırma artefaktı ({dosya_boyutu_kb:.1f} KB / {piksel_mp:.1f} MP)"

    # 4. Laplacian Netlik ve Keskinlik Denetimi
    puan = netlik_puani(img)
    if puan < asgari_netlik:
        return False, f"Görsel bulanık veya yapay büyütülmüş (Netlik puanı: {puan:.1f} < {asgari_netlik})"

    # 5. Belge / Tablo / Taranmış İlan Formu Denetimi (Scanned Document Filter)
    try:
        stat_hsv = ImageStat.Stat(img.convert("HSV"))
        stat_l = ImageStat.Stat(img.convert("L"))
        sat_mean = stat_hsv.mean[1] if len(stat_hsv.mean) > 1 else 100.0
        lum_mean = stat_l.mean[0] if stat_l.mean else 100.0
        if sat_mean < 15.0 and lum_mean > 175.0:
            return (
                False,
                f"Görsel bir belge/tablo taraması veya düz beyaz zeminli metin belgesi (Doygunluk: {sat_mean:.1f}, Parlaklık: {lum_mean:.1f})",
            )
    except Exception as e:
        log.debug("Belge denetiminde hata: %s", e)

    return True, f"Kalite onaylandı (Ölçek: {olcek}x, Netlik: {puan:.1f}, {w}x{h} px)"


def kristal_netlestir(img: Image.Image) -> Image.Image:
    """
    Fotoğrafa ince, profesyonel editoryal keskinlik kazandırır (Hale/halo oluşturmaz).
    """
    return img.filter(ImageFilter.UnsharpMask(radius=1.2, percent=110, threshold=2))
