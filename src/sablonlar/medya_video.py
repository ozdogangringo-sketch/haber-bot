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
from PIL import Image, ImageDraw

from src import make_image
from src.sablonlar.ortak import (
    cam_kart_ciz,
    metin_kutuya_sar,
    temel_tuval_olustur,
    ust_ve_alt_bar_bas,
)

log = logging.getLogger(__name__)

_REKLAM_KELIMELERI = ("doubleclick", "googlesyndication", "adservice", "taboola", "outbrain", "preroll", " pixel")


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
) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """
    1080x1920 tuval üzerinde video oynatma penceresi olan Daily Brief çerçevesini çizer.
    Döner: `(cerceve_gorseli, (vx1, vy1, vx2, vy2))`
    """
    gorsel, kenar, dikey_kenar, y_ust, y_alt = temel_tuval_olustur(
        ayarlar,
        kategori=haber.get("kategori") or "turkiye",
        arkaplan=arkaplan,
        tema_alt_renk=(4, 14, 24),
    )
    genislik = make_image.STORY_GENISLIK
    alan_g = genislik - 2 * kenar
    y = y_ust + 8

    # Üstte haber başlığı kartı
    baslik = (haber.get("ig_baslik") or haber.get("baslik_orj") or "Görüntülü Haber Detayı").strip()
    ust_h = 116
    gorsel = cam_kart_ciz(
        gorsel,
        (kenar, y, genislik - kenar, y + ust_h),
        dolgu=(10, 24, 42, 232),
        kenarlik=(239, 68, 68, 95),
        yaricap=20,
        sol_centik=(239, 68, 68),
    )
    ciz = ImageDraw.Draw(gorsel)
    f_bas = make_image._font(28, make_image.EKSEN_BASLIK)
    b_satirlar = metin_kutuya_sar(ciz, baslik, f_bas, alan_g - 52, maks_satir=2)
    by = y + (ust_h - len(b_satirlar) * 36) // 2
    for s in b_satirlar:
        ciz.text((kenar + 28, by), s, font=f_bas, fill=(255, 255, 255))
        by += 36

    y += ust_h + 22

    # Ortada video penceresi alanı (944 x 680 px)
    alt_not = (haber.get("slayt_ozet") or haber.get("sana_etkisi") or "").strip()
    not_pay = 112 if alt_not else 0
    v_yuk = y_alt - y - not_pay
    vx1, vy1, vx2, vy2 = kenar, y, genislik - kenar, y + v_yuk

    gorsel = cam_kart_ciz(
        gorsel,
        (vx1 - 6, vy1 - 6, vx2 + 6, vy2 + 6),
        dolgu=(4, 10, 18, 255),
        kenarlik=(6, 182, 212, 110),
        yaricap=20,
    )

    if alt_not:
        ny1 = vy2 + 18
        gorsel = cam_kart_ciz(
            gorsel,
            (kenar, ny1, genislik - kenar, y_alt),
            dolgu=(10, 26, 40, 228),
            kenarlik=(6, 182, 212, 75),
            yaricap=16,
            sol_centik=(6, 182, 212),
        )
        ciz = ImageDraw.Draw(gorsel)
        f_not = make_image._font(24, make_image.EKSEN_OZET)
        not_satir = metin_kutuya_sar(ciz, alt_not, f_not, alan_g - 48, maks_satir=2)
        nty = ny1 + ((y_alt - ny1) - len(not_satir) * 32) // 2
        for ns in not_satir:
            ciz.text((kenar + 24, nty), ns, font=f_not, fill=(226, 232, 240))
            nty += 32

    gorsel = ust_ve_alt_bar_bas(
        gorsel,
        ayarlar=ayarlar,
        kaynak=kaynak,
        rozet_metni="GÖRÜNTÜLÜ HABER DETAYI",
        rozet_renk=(239, 68, 68),
        ulke_kodu=haber.get("ulke_kodu") or None,
        ulke_adi=haber.get("ulke_adi") or None,
        sayfa=sayfa,
        toplam_sayfa=toplam_sayfa,
        arsiv_ibaresi=arsiv_ibaresi,
    )
    return gorsel, (vx1, vy1, vx2, vy2)


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

    cerceve, (vx1, vy1, vx2, vy2) = video_cercevesi_ciz(
        haber, ayarlar, kaynak, arkaplan=arkaplan, sayfa=sayfa, toplam_sayfa=toplam_sayfa
    )
    vw = ((vx2 - vx1) // 2) * 2
    vh = ((vy2 - vy1) // 2) * 2

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        bg_yolu = tmp_path / "cerceve.jpg"
        cerceve.save(bg_yolu, "JPEG", quality=95)

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
