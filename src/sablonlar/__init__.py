"""
sablonlar — Haberin türüne göre dinamik değişen özel detay slaytı şablon paketi.

Desteklenen şablonlar (`detay_sablonu`):
  - `standart`      : Klasik editoryal paragraf + Smart Brevity detay slaytı
  - `spor_kadro`    : Maç kadroları, ilk 11, teknik direktör ve diziliş sahası kartı
  - `hava_durumu`   : Meteoroloji uyarı kodu (Sarı/Turuncu/Kırmızı), etkilenen iller ve metrikler
  - `karsilastirma` : Eski vs Yeni fiyat, maaş, vergi, tarife veya zam karşılaştırma tablosu
  - `rehber_adim`   : Başvuru şartları, adım adım rehber ve yasal düzenleme maddeleri
  - `sirali_liste`  : Top 5-6 sıralama, puan durumu, ihracat/şehir liderleri yatay bar grafiği
  - `medya_video`   : Haberde gerçek video varsa 2. slaytta çerçeveli 1080x1920 MP4 video
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from PIL import Image

from src.sablonlar.hava_durumu import hava_durumu_slayti_ciz
from src.sablonlar.karsilastirma import karsilastirma_slayti_ciz
from src.sablonlar.medya_video import (
    makaleden_video_url_cikar,
    video_cercevesi_ciz,
    video_detay_slayti_uret,
)
from src.sablonlar.rehber_adim import rehber_adim_slayti_ciz
from src.sablonlar.sirali_liste import sirali_liste_slayti_ciz
from src.sablonlar.spor_kadro import spor_kadro_slayti_ciz
from src.sablonlar.spor_kapak import spor_kapak_slayti_ciz

log = logging.getLogger(__name__)

GECERLI_SABLONLAR = (
    "standart",
    "spor_kadro",
    "hava_durumu",
    "karsilastirma",
    "rehber_adim",
    "sirali_liste",
    "medya_video",
)

_GORSEL_CIZICILER = {
    "spor_kadro": spor_kadro_slayti_ciz,
    "hava_durumu": hava_durumu_slayti_ciz,
    "karsilastirma": karsilastirma_slayti_ciz,
    "rehber_adim": rehber_adim_slayti_ciz,
    "sirali_liste": sirali_liste_slayti_ciz,
}


def sablon_adini_dogrula(deger: str | None) -> str:
    """Modelden veya DB'den gelen şablon adını beyaz listeden geçirir."""
    ad = (deger or "").strip().lower()
    return ad if ad in GECERLI_SABLONLAR else "standart"


def sablon_verisini_coz(ham_veri: Any) -> dict:
    """DB'deki JSON string veya dict olan `sablon_verisi` alanını güvenle sözlüğe çevirir."""
    if isinstance(ham_veri, dict):
        return ham_veri
    if isinstance(ham_veri, str) and ham_veri.strip():
        try:
            cozulen = json.loads(ham_veri)
            if isinstance(cozulen, dict):
                return cozulen
        except Exception as e:
            log.warning("sablon_verisi JSON çözülemedi: %s", e)
    return {}


def ozel_detay_slayti_uret(
    haber: dict,
    ayarlar: dict,
    kaynak: str | None = None,
    arkaplan: Image.Image | None = None,
    sayfa: int = 1,
    toplam_sayfa: int = 2,
    arsiv_ibaresi: bool = False,
) -> Image.Image | None:
    """
    Haberin `detay_sablonu` ve `sablon_verisi` alanlarına göre özel infografik
    detay slaytını (1080x1920) üretir.
    Şablon `standart` ise veya veri eksikse `None` döner (standart metin slaytı devreye girer).
    """
    h = dict(haber) if not isinstance(haber, dict) else haber
    sablon = sablon_adini_dogrula(h.get("detay_sablonu"))
    if sablon == "standart" or sablon not in _GORSEL_CIZICILER:
        return None

    veri = sablon_verisini_coz(h.get("sablon_verisi"))
    if not veri:
        return None

    etkin_kaynak = kaynak if kaynak is not None else str(h.get("kaynak") or "")
    cizici = _GORSEL_CIZICILER[sablon]
    try:
        return cizici(
            haber=h,
            veri=veri,
            ayarlar=ayarlar,
            kaynak=etkin_kaynak,
            arkaplan=arkaplan,
            sayfa=sayfa,
            toplam_sayfa=toplam_sayfa,
            arsiv_ibaresi=arsiv_ibaresi,
        )
    except Exception as e:
        log.warning("Özel detay şablonu (%s) çizilemedi, standart slayta düşülüyor: %s", sablon, e)
        return None


def ozel_kapak_slayti_uret(
    haber: dict,
    ayarlar: dict,
    kaynak: str | None = None,
    arkaplan: Image.Image | None = None,
    arsiv_ibaresi: bool = False,
    sayfa: int = 1,
    toplam_sayfa: int = 2,
) -> Image.Image | None:
    """
    Haberin türüne göre (örn: `spor_kadro` -> kulüp armalı Maç Günü Kapağı)
    özel 1. kapak slaytı üretir. Uygun özel kapak yoksa `None` döner.
    """
    h = dict(haber) if not isinstance(haber, dict) else haber
    sablon = sablon_adini_dogrula(h.get("detay_sablonu"))
    if sablon != "spor_kadro":
        return None

    veri = sablon_verisini_coz(h.get("sablon_verisi"))
    if not veri:
        return None

    etkin_kaynak = kaynak if kaynak is not None else str(h.get("kaynak") or "")
    try:
        return spor_kapak_slayti_ciz(
            haber=h,
            veri=veri,
            ayarlar=ayarlar,
            kaynak=etkin_kaynak,
            arkaplan=arkaplan,
            arsiv_ibaresi=arsiv_ibaresi,
            sayfa=sayfa,
            toplam_sayfa=toplam_sayfa,
        )
    except Exception as e:
        log.warning("Özel kapak şablonu (%s) çizilemedi: %s", sablon, e)
        return None


__all__ = [
    "GECERLI_SABLONLAR",
    "makaleden_video_url_cikar",
    "ozel_detay_slayti_uret",
    "ozel_kapak_slayti_uret",
    "sablon_adini_dogrula",
    "sablon_verisini_coz",
    "spor_kadro_slayti_ciz",
    "spor_kapak_slayti_ciz",
    "video_cercevesi_ciz",
    "video_detay_slayti_uret",
]
