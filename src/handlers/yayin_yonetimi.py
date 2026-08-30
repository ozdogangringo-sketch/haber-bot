"""
yayin_yonetimi.py — Çoklu Platform Sosyal Medya Yayınlama ve Telafi Motoru

Instagram, Facebook, Threads, Twitter, YouTube Shorts ve TikTok paylaşımlarını,
yayın durumu kontrollerini, telafi mekanizmalarını ve planlı yayınları yönetir.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from src import (
    caption,
    db,
    facebook,
    filtre,
    hata_bildir,
    instagram,
    make_image,
    telegram_bot,
    threads,
    tiktok,
    twitter,
    upload_image,
    video,
    youtube,
)

log = logging.getLogger("yayin_yonetimi")


def detay_urlleri(ham) -> list[str]:
    """
    JSON listesi bekliyoruz ama eski kayıtlarda tek düz URL var —
    ikisini de kabul ediyoruz ki geçmiş turlar bozulmasın.
    """
    if not ham:
        return []
    try:
        cozulen = json.loads(ham)
        return [u for u in cozulen if u] if isinstance(cozulen, list) else [ham]
    except (ValueError, TypeError):
        return [ham]


def sonuclari_kur(haberler: list) -> list[dict]:
    """Caption'ın atıf bloğu için katman bilgisini toparlar."""
    return [
        {"id": h["id"], "katman": h["gorsel_kaynagi"], "atif": h["gorsel_atif"] or ""}
        for h in haberler
    ]


def yayin_ozeti(haberler: list) -> str:
    """
    Yayın sonucu mesajına konan başlık özeti.
    Tek haberlik tekil postta başlık + kısa özet, çok haberli turda
    numaralı manşet listesi basılıyor.
    """
    if not haberler:
        return ""
    if len(haberler) == 1:
        h = haberler[0]
        baslik = (h["ig_baslik"] or h["baslik_orj"] or "").strip()
        ozet = (h["slayt_ozet"] or "").strip()
        return f"📌 {baslik}" + (f"\n{ozet}" if ozet else "")
    satirlar = []
    for sira, h in enumerate(haberler[:10], start=1):
        baslik = (h["ig_baslik"] or h["baslik_orj"] or "").strip()
        satirlar.append(f"{sira}. {baslik}")
    return "\n".join(satirlar)


def url_canli_ve_uygun_mu(url: str) -> bool:
    """URL'nin erişilebilir ve Meta/Instagram için uygun olup olmadığını denetler."""
    if not url or not isinstance(url, str) or not url.startswith("http"):
        return False
    if "uguu.se" in url:
        return False
    try:
        r = requests.head(
            url,
            headers={"User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)"},
            timeout=5,
            allow_redirects=True,
        )
        return r.status_code == 200
    except Exception:
        return False


def urlleri_dogrula_ve_onar(con, ayarlar: dict, haberler: list[dict | sqlite3.Row], urller: list[str]) -> list[str]:
    """
    Tüm görsel URL'lerini denetler; süresi dolmuş veya uguu.se gibi riskli URL'leri
    yerel dosyalardan veya anında yeniden çizerek taze barındırıcıya (ImgBB / Litterbox) yükler.
    """
    if not urller or not haberler:
        return urller

    hepsi_canli = all(url_canli_ve_uygun_mu(u) for u in urller)
    if hepsi_canli:
        return urller

    log.warning("Bazı görsel URL'leri süresi dolmuş veya geçersiz, otomatik onarma başlatılıyor...")

    ilk_h = dict(haberler[0])
    son_dakika_mi = bool(ilk_h.get("son_dakika"))

    if son_dakika_mi:
        try:
            from src import slaytlar
            sonuclar = slaytlar.son_dakika_uret(ilk_h, ayarlar, con)
            carousel = [s for s in sonuclar if not s["katman"].startswith("story")]
            story_slayt = next((s for s in sonuclar if s["katman"] == "story"), None)

            yuklemeler = upload_image.hepsini_yukle([s["yol"] for s in carousel], ayarlar)
            taze_urller = [y["url"] for y in yuklemeler]

            story_url = None
            if story_slayt:
                try:
                    story_url = upload_image.gorsel_yukle(story_slayt["yol"], ayarlar)["url"]
                except Exception:
                    pass

            con.execute(
                "UPDATE haberler SET gorsel_url = ?, detay_url = ?, story_url = ? WHERE id = ?",
                (taze_urller[0], json.dumps(taze_urller[1:]), story_url, ilk_h["id"])
            )
            con.commit()
            log.info("Son dakika haberi #%s için %d taze görsel URL'si başarıyla onarıldı.", ilk_h["id"], len(taze_urller))
            return taze_urller
        except Exception as e:
            log.exception("Son dakika görsel onarma hatası: %s", e)

    taze_urller = []
    for idx, h_raw in enumerate(haberler):
        h_d = dict(h_raw)
        mevcut_url = h_d.get("gorsel_url")
        if url_canli_ve_uygun_mu(mevcut_url):
            taze_urller.append(mevcut_url)
            continue

        try:
            from src import slaytlar
            slayt_sonuc = slaytlar.slayt_uret(h_d, ayarlar, sira=idx + 1)
            yol = slayt_sonuc.get("yol") if isinstance(slayt_sonuc, dict) else Path(h_d.get("gorsel_yolu", ""))
            if yol and Path(yol).exists():
                yeni_yukleme = upload_image.gorsel_yukle(Path(yol), ayarlar)
                yeni_url = yeni_yukleme["url"]
                con.execute("UPDATE haberler SET gorsel_url = ? WHERE id = ?", (yeni_url, h_d["id"]))
                con.commit()
                taze_urller.append(yeni_url)
            else:
                taze_urller.append(mevcut_url)
        except Exception as e:
            log.warning("Tur haber #%s görseli tazelenemedi: %s", h_d.get("id"), e)
            taze_urller.append(mevcut_url)

    return taze_urller if len(taze_urller) >= len(urller) else urller
