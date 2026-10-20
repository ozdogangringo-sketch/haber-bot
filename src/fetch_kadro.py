"""
fetch_kadro.py — Canlı Futbol API'si (API-Football) üzerinden maç kadrolarını çeker
ve Daily Brief spor infografik şablonlarına (Split Clash Kapak + Monokrom Lüks Kadro) dönüştürür.

Özellikler:
  - API-Football (v3.football.api-sports.io) entegrasyonu
  - Günün Süper Lig, Türkiye Kupası ve Türk takımlarının Avrupa maçlarını otomatik listeleme
  - Resmi maç kadrosunu (İlk 11, diziliş, yedekler, TD, hakem, stadyum) ayrıştırma
  - Daily Brief 1080x1920 (4:5 güvenli alanlı) Carousel görsellerini doğrudan üretme
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

KOK = Path(__file__).resolve().parent.parent
BASE_URL = "https://v3.football.api-sports.io"

# Türk takımları arama anahtarları
TURK_TAKIMLARI = {
    "galatasaray", "fenerbahce", "fenerbahçe", "besiktas", "beşiktaş",
    "trabzonspor", "basaksehir", "başakşehir", "samsunspor", "eyupspor",
    "eyüpspor", "goztepe", "göztepe", "sivasspor", "antalyaspor", "konyaspor",
    "kasimpasa", "kasımpaşa", "alanyaspor", "rizespor", "çaykur rizespor",
    "gaziantep", "kayserispor", "bodrumspor", "adana demirspor", "hatayspor"
}


def _api_key() -> str:
    key = os.getenv("API_FOOTBALL_KEY", "").strip()
    if not key:
        log.warning("API_FOOTBALL_KEY tanımlı değil (.env dosyasını kontrol edin)")
    return key


def api_football_istek(endpoint: str, params: dict | None = None) -> dict:
    """API-Football REST API isteği yapar."""
    key = _api_key()
    if not key:
        return {"errors": ["API_FOOTBALL_KEY bulunamadı"], "response": []}

    headers = {
        "x-apisports-key": key,
        "Accept": "application/json",
    }
    url = f"{BASE_URL}/{endpoint.lstrip('/')}"
    try:
        r = requests.get(url, headers=headers, params=params or {}, timeout=12)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.error("API-Football istek hatası (%s): %s", endpoint, e)
        return {"errors": [str(e)], "response": []}


def bugun_tr() -> str:
    """Türkiye yerel saatine (UTC+3) göre bugünün tarihini YYYY-MM-DD olarak döner."""
    now_tr = datetime.now(timezone.utc) + timedelta(hours=3)
    return now_tr.strftime("%Y-%m-%d")


def gunun_maclarini_getir(tarih: str | None = None) -> list[dict]:
    """
    Belirtilen günün (varsayılan bugün) fikstürünü çeker ve Türk kulüplerinin
    veya büyük liglerin maçlarını önceliklendirerek döner.
    """
    hedef_tarih = tarih or bugun_tr()
    res = api_football_istek("fixtures", {"date": hedef_tarih})
    fixtures = res.get("response", [])
    if not fixtures:
        return []

    secilenler = []
    for f in fixtures:
        league = f.get("league", {})
        country = (league.get("country") or "").strip().lower()
        l_name = (league.get("name") or "").strip()
        h_name = (f.get("teams", {}).get("home", {}).get("name") or "").strip()
        a_name = (f.get("teams", {}).get("away", {}).get("name") or "").strip()

        h_lower = h_name.lower()
        a_lower = a_name.lower()

        turk_maci = (
            country == "turkey"
            or any(t in h_lower for t in TURK_TAKIMLARI)
            or any(t in a_lower for t in TURK_TAKIMLARI)
        )
        onemli_avrupa = (
            "champions league" in l_name.lower()
            or "europa league" in l_name.lower()
            or "conference league" in l_name.lower()
        )

        if turk_maci or onemli_avrupa:
            secilenler.append(f)

    return secilenler


def mac_kadrosunu_cek(fixture_id: int) -> dict | None:
    """
    Verilen fikstür ID'sinin detaylarını ve resmi kadrolarını çeker.
    Daily Brief 'spor_kadro' şablon verisi (JSON) formatına dönüştürür.
    """
    # 1. Fikstür temel bilgileri
    fix_res = api_football_istek("fixtures", {"id": fixture_id})
    f_list = fix_res.get("response", [])
    if not f_list:
        log.warning("Fikstür #%s bulunamadı", fixture_id)
        return None

    fix_data = f_list[0]
    fixture_info = fix_data.get("fixture", {})
    league_info = fix_data.get("league", {})
    teams_info = fix_data.get("teams", {})

    ev_ad = teams_info.get("home", {}).get("name", "")
    dep_ad = teams_info.get("away", {}).get("name", "")
    turnuva = (league_info.get("name") or "FUTBOL KARŞILAŞMASI").upper()

    # Maç saati (TR Saati UTC+3)
    mac_dt_str = fixture_info.get("date", "")
    saat_tr = "20:00"
    if mac_dt_str:
        try:
            dt = datetime.fromisoformat(mac_dt_str.replace("Z", "+00:00"))
            dt_tr = dt.astimezone(timezone(timedelta(hours=3)))
            saat_tr = dt_tr.strftime("%H:%M")
        except Exception:
            pass

    venue = (fixture_info.get("venue", {}).get("name") or "").strip()
    city = (fixture_info.get("venue", {}).get("city") or "").strip()
    stadyum = f"{venue}, {city}".strip(" ,") if city else venue or "Stadyum"

    referee = (fixture_info.get("referee") or "").strip()
    hakem = referee.split(",")[0].strip() if referee else "Açıklanmadı"
    mac_bilgisi = f"{stadyum} · Hakem: {hakem}" if hakem != "Açıklanmadı" else stadyum

    # 2. Lineup (Kadro) sorgusu
    lin_res = api_football_istek("fixtures/lineups", {"fixture": fixture_id})
    lineups = lin_res.get("response", [])

    if not lineups or len(lineups) < 2:
        log.info("Fikstür #%s için henüz resmi kadrolar girilmemiş", fixture_id)
        return {
            "turnuva": turnuva,
            "ev_sahibi": ev_ad,
            "deplasman": dep_ad,
            "skor_veya_saat": saat_tr,
            "mac_bilgisi": mac_bilgisi,
            "kadro_hazir": False,
        }

    ev_lineup = lineups[0]
    dep_lineup = lineups[1]

    def _oyunculari_derle(oyuncu_listesi: list[dict], kaleci_etiketle: bool = True) -> list[str]:
        sonuc = []
        for p in oyuncu_listesi:
            p_info = p.get("player", {})
            num = p_info.get("number") or ""
            name = (p_info.get("name") or "").strip()
            pos = (p_info.get("pos") or "").upper()
            kl = " (KL)" if (kaleci_etiketle and pos in ("G", "GK")) else ""
            if name:
                sonuc.append(f"{num} {name}{kl}".strip())
        return sonuc

    ev_kadro = _oyunculari_derle(ev_lineup.get("startXI", []))
    dep_kadro = _oyunculari_derle(dep_lineup.get("startXI", []))
    ev_subs = _oyunculari_derle(ev_lineup.get("substitutes", []), kaleci_etiketle=False)
    dep_subs = _oyunculari_derle(dep_lineup.get("substitutes", []), kaleci_etiketle=False)

    ev_td = (ev_lineup.get("coach", {}).get("name") or "").strip()
    dep_td = (dep_lineup.get("coach", {}).get("name") or "").strip()

    ev_dizilis = ev_lineup.get("formation") or "4-2-3-1"
    dep_dizilis = dep_lineup.get("formation") or "4-3-3"

    # Kadro şablonu bir "MAÇ ÖNÜ" duyurusudur; merkez rozette ve metinde HER ZAMAN
    # karşılaşmanın başlama saati (örn: 20:00) yer alır (asla maç skoru yazılmaz).
    alt_not = f"Karşılaşma saat {saat_tr}'de başlayacak. Resmi ilk 11'ler ve yedek kulübeleri açıklandı."
    skor_saat = saat_tr

    sablon_verisi = {
        "turnuva": turnuva,
        "ev_sahibi": ev_ad,
        "deplasman": dep_ad,
        "skor_veya_saat": skor_saat,
        "saat": saat_tr,
        "mac_bilgisi": mac_bilgisi,
        "ev_td": ev_td,
        "deplasman_td": dep_td,
        "ev_dizilis": ev_dizilis,
        "deplasman_dizilis": dep_dizilis,
        "ev_kadro": ev_kadro,
        "deplasman_kadro": dep_kadro,
        "ev_yedekler": ev_subs[:8],  # İdeal okunurluk için ilk 8 yedek
        "deplasman_yedekler": dep_subs[:8],
        "alt_not": alt_not,
        "kadro_hazir": True,
    }

    return sablon_verisi


def spor_haberi_olustur_ve_ciz(
    fixture_id: int,
    ayarlar: dict,
    cikti_dizini: Path | None = None,
) -> tuple[dict, Path, Path]:
    """
    Belirtilen fikstür için Daily Brief haber kaydını oluşturur,
    1. Kapak Slaytı (Split Clash) ve 2. Kadro Slaytını (Monokrom Lüks) render eder.
    """
    from src import sablonlar

    kadro_verisi = mac_kadrosunu_cek(fixture_id)
    if not kadro_verisi or not kadro_verisi.get("kadro_hazir"):
        raise ValueError(f"Fikstür #{fixture_id} için kadro verisi henüz hazır değil!")

    ev_ad = kadro_verisi["ev_sahibi"]
    dep_ad = kadro_verisi["deplasman"]
    turnuva = kadro_verisi["turnuva"]
    saat = kadro_verisi["skor_veya_saat"]

    baslik = f"{ev_ad} - {dep_ad} Maçının İlk 11'leri Belli Oldu"
    ozet = (
        f"{turnuva} heyecanında dev karşılaşmanın resmi kadroları açıklandı. "
        f"Saat {saat}'de başlayacak maç öncesinde takımların ilk 11'leri ve yedek kulübeleri sahada."
    )

    haber = {
        "id": fixture_id,
        "kategori": "spor",
        "kaynak": "Daily Brief Spor",
        "ig_baslik": baslik,
        "slayt_ozet": ozet,
        "detay_sablonu": "spor_kadro",
        "sablon_verisi": json.dumps(kadro_verisi, ensure_ascii=False),
        "paylas_reels": False,  # KATI KURAL: Sadece Carousel Gönderi!
        "paylas_video": False,
    }

    hedef_klasor = cikti_dizini or (KOK / "cikis")
    hedef_klasor.mkdir(parents=True, exist_ok=True)

    # 1. Kapak Slaytı
    img_kapak = sablonlar.ozel_kapak_slayti_uret(haber, ayarlar, sayfa=1, toplam_sayfa=2)
    yol_kapak = hedef_klasor / f"mac_slayt_1_kapak_{fixture_id}.jpg"
    img_kapak.save(yol_kapak, "JPEG", quality=95, optimize=True)

    # 2. Kadro Slaytı
    img_kadro = sablonlar.ozel_detay_slayti_uret(haber, ayarlar, sayfa=2, toplam_sayfa=2)
    yol_kadro = hedef_klasor / f"mac_slayt_2_kadro_{fixture_id}.jpg"
    img_kadro.save(yol_kadro, "JPEG", quality=95, optimize=True)

    return haber, yol_kapak, yol_kadro
