"""
spor_yonetimi.py — 4 Büyükler Futbol Otomasyon & Yayın Motoru.

Kullanıcı Kuralları (21 Ekim 2026):
  1. 4 Büyüklerin (Galatasaray, Fenerbahçe, Beşiktaş, Trabzonspor) her maçından önce
     kadro Carousel gönderisi (Split Arena Kapak + Monokrom Lüks Kadro).
     - Kesinlikle Carousel (Reels/Video YOK).
  2. Her maçından sonra maç skoru & analiz haberi:
     - En az 15 dakika bekleme penceresi (basın toplantısı, kesin istatistik ve fotoğrafların netleşmesi için).
     - Seslendirmeli (ElevenLabs Alex bariton spiker + fon müziği) Reels video formatında.
     - Aynı zamanda Instagram Akışına 4:5 Carousel.
  3. Mükerrer yayın koruması: Her maçın kadrosu ve maç sonu bülteni SQLite 'ayarlar'
     üzerinden izlenir ve yalnızca bir kez üretilir.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import requests
from dotenv import load_dotenv

from . import (
    caption,
    db,
    fetch_kadro,
    fetch_kulup_logo,
    generate_text,
    make_image,
    okunus,
    sablonlar,
    telegram_bot,
    upload_image,
)

load_dotenv()
log = logging.getLogger(__name__)

KOK = Path(__file__).resolve().parent.parent

# 4 Büyükler standart slug ve arama anahtarları
DORT_BUYUKLER = {
    "galatasaray",
    "fenerbahce",
    "fenerbahçe",
    "besiktas",
    "beşiktaş",
    "trabzonspor",
}


def dort_buyuk_mu(takim_adi: str) -> bool:
    """Verilen takımın 4 Büyükler A Takımı olup olmadığını doğrular."""
    if not takim_adi:
        return False
    t_lower = takim_adi.lower()
    # Altyapı, gençlik, rezerv ve kadın takımlarını hariç tut (Yalnızca A Takımı resmi maçları)
    if any(k in t_lower for k in ("u19", "u21", "u18", "u17", "u23", "women", "kadin", "kadın", "youth", "b takimi")):
        return False
    slug = fetch_kulup_logo.takim_slug_yap(takim_adi)
    return any(b in slug or slug in b for b in ("galatasaray", "fenerbahce", "besiktas", "trabzonspor"))


def dort_buyukler_maci_mi(ev_ad: str, dep_ad: str) -> bool:
    """Karşılaşmada ev sahibi veya deplasman takımından en az birinin 4 Büyükler olduğunu denetler."""
    return dort_buyuk_mu(ev_ad) or dort_buyuk_mu(dep_ad)


def gunun_dort_buyuk_maclari(tarih: str | None = None) -> list[dict]:
    """
    Günün (veya belirtilen tarihin) fikstürünü çeker ve yalnızca 4 Büyüklerin
    maçlarını (Süper Lig, Türkiye Kupası, Şampiyonlar Ligi, Avrupa Ligi, Konferans Ligi) döner.
    """
    tum_maclar = fetch_kadro.gunun_maclarini_getir(tarih)
    secilenler = []
    for f in tum_maclar:
        league_name = (f.get("league", {}).get("name") or "").lower()
        if any(k in league_name for k in ("youth", "u19", "u21", "women", "kadin", "kadın")):
            continue
        h_name = f.get("teams", {}).get("home", {}).get("name", "")
        a_name = f.get("teams", {}).get("away", {}).get("name", "")
        if dort_buyukler_maci_mi(h_name, a_name):
            secilenler.append(f)
    return secilenler


def bekleme_suresi_doldu_mu(fixture_id: int, con: sqlite3.Connection, asgari_dakika: int = 15) -> tuple[bool, float]:
    """
    Maç bitimi üzerinden en az `asgari_dakika` (varsayılan 15 dk) geçip geçmediğini denetler.
    İlk kez FT görüldüğünde zaman damgası SQLite ayarlar tablosuna kaydedilir.

    Döner: `(sure_doldu_mu, gecen_dakika)`
    """
    anahtar = f"spor_mac_bitti_zamani_{fixture_id}"
    satir = con.execute("SELECT deger FROM ayarlar WHERE anahtar = ?", (anahtar,)).fetchone()
    simdi = datetime.now(timezone.utc)

    if not satir or not satir["deger"]:
        con.execute(
            "INSERT INTO ayarlar (anahtar, deger) VALUES (?, ?) "
            "ON CONFLICT(anahtar) DO UPDATE SET deger = excluded.deger",
            (anahtar, simdi.isoformat()),
        )
        con.commit()
        log.info("Fikstür #%s maç sonu (FT) ilk kez tespit edildi. 15 dk bekleme penceresi başlatıldı.", fixture_id)
        return False, 0.0

    try:
        bitis_dt = datetime.fromisoformat(satir["deger"])
        if bitis_dt.tzinfo is None:
            bitis_dt = bitis_dt.replace(tzinfo=timezone.utc)
        fark_dakika = (simdi - bitis_dt).total_seconds() / 60.0
        return (fark_dakika >= asgari_dakika), fark_dakika
    except Exception as e:
        log.warning("Fikstür #%s bitiş zamanı okunamadı (%s), sıfırlanıyor", fixture_id, e)
        con.execute("DELETE FROM ayarlar WHERE anahtar = ?", (anahtar,))
        con.commit()
        return False, 0.0


# =============================================================================
# 1. MAÇ ÖNÜ KADRO CAROUSEL AKIŞI
# =============================================================================

def kadro_haberi_hazirla_ve_sun(
    fixture_id: int,
    con: sqlite3.Connection,
    ayarlar: dict,
    telegrama_gonder: bool = True,
) -> dict | None:
    """
    4 Büyüklerin maçından önce resmi ilk 11'ler açıklandığında 2 slaytlık
    Carousel gönderisini hazırlar ve Telegram onay grubuna sunar.
    """
    anahtar_yayin = f"spor_kadro_{fixture_id}"
    zaten = con.execute("SELECT deger FROM ayarlar WHERE anahtar = ?", (anahtar_yayin,)).fetchone()
    if zaten:
        log.info("Fikstür #%s kadro gönderisi zaten hazırlanmış/yayınlanmış, atlanıyor.", fixture_id)
        return None

    # Kadro verisini çek ve doğrula
    kadro_verisi = fetch_kadro.mac_kadrosunu_cek(fixture_id)
    if not kadro_verisi or not kadro_verisi.get("kadro_hazir"):
        log.info("Fikstür #%s için henüz resmi kadrolar yayınlanmamış.", fixture_id)
        return None

    ev_ad = kadro_verisi["ev_sahibi"]
    dep_ad = kadro_verisi["deplasman"]
    turnuva = kadro_verisi["turnuva"]
    saat = kadro_verisi.get("skor_veya_saat", "20:00")

    baslik = f"{ev_ad} - {dep_ad} Maçının İlk 11'leri Belli Oldu"
    spot = (
        f"{turnuva} heyecanında dev karşılaşmanın resmi kadroları açıklandı. "
        f"Saat {saat}'de başlayacak maç öncesinde takımların ilk 11'leri ve yedek kulübeleri sahada."
    )

    cikti_klasor = KOK / "data" / "output"
    cikti_klasor.mkdir(parents=True, exist_ok=True)

    haber = {
        "id": fixture_id,
        "kategori": "spor",
        "kaynak": "Daily Brief Spor",
        "ig_baslik": baslik,
        "slayt_ozet": spot,
        "detay_sablonu": "spor_kadro",
        "sablon_verisi": json.dumps(kadro_verisi, ensure_ascii=False),
        "paylas_reels": False,  # KATI KURAL: Sadece Carousel Gönderi!
        "paylas_video": False,
    }

    # 1. Kapak ve Kadro Slaytlarını Çiz
    img_kapak = sablonlar.ozel_kapak_slayti_uret(haber, ayarlar, sayfa=1, toplam_sayfa=2)
    img_kadro = sablonlar.ozel_detay_slayti_uret(haber, ayarlar, sayfa=2, toplam_sayfa=2)

    yol_kapak = cikti_klasor / f"mac_kadro_{fixture_id}_1_kapak.jpg"
    yol_kadro = cikti_klasor / f"mac_kadro_{fixture_id}_2_kadro.jpg"
    img_kapak.save(yol_kapak, "JPEG", quality=95, optimize=True)
    img_kadro.save(yol_kadro, "JPEG", quality=95, optimize=True)

    # 2. R2 / ImgBB Görsel Yüklemesi
    yukleme_sonuclari = upload_image.hepsini_yukle([yol_kapak, yol_kadro], ayarlar)
    if len(yukleme_sonuclari) < 2:
        raise RuntimeError(f"Fikstür #{fixture_id} kadro görselleri CDN'e yüklenemedi!")

    url_kapak = yukleme_sonuclari[0]["url"]
    url_kadro = yukleme_sonuclari[1]["url"]

    # 3. Instagram & Sosyal Medya Açıklama Metni (SIFIR MARKDOWN KURALI)
    ev_11_str = ", ".join(kadro_verisi.get("ev_kadro", [])[:11])
    dep_11_str = ", ".join(kadro_verisi.get("deplasman_kadro", [])[:11])
    caption_metni = (
        f"{baslik}\n\n"
        f"{spot}\n\n"
        f"{ev_ad} İlk 11: {ev_11_str}\n\n"
        f"{dep_ad} İlk 11: {dep_11_str}\n\n"
        f"Stat: {kadro_verisi.get('mac_bilgisi', '')}\n\n"
        f"#DailyBrief #{fetch_kulup_logo.takim_slug_yap(ev_ad)} #{fetch_kulup_logo.takim_slug_yap(dep_ad)} #SüperLig #Kadro"
    )

    # 4. Veritabanına Kaydet
    cursor = con.execute(
        """INSERT OR REPLACE INTO haberler (
            kaynak, kategori, agirlik, baslik_orj, link, ozet_orj,
            ig_baslik, slayt_ozet, ig_caption, detay_sablonu, sablon_verisi,
            gorsel_yolu, gorsel_url, story_url, detay_url, son_dakika,
            durum, yayin_tarihi, cekilme_zamani
        ) VALUES (
            'Daily Brief Spor', 'spor', 10, ?, ?, ?,
            ?, ?, ?, 'spor_kadro', ?,
            ?, ?, ?, ?, 1,
            'onay_bekliyor', datetime('now'), datetime('now')
        )""",
        (
            baslik,
            f"https://dailybrief.co/kadro/{fixture_id}",
            spot,
            baslik,
            spot,
            caption_metni,
            json.dumps(kadro_verisi, ensure_ascii=False),
            str(yol_kapak),
            url_kapak,
            url_kapak,
            json.dumps([url_kadro]),
        ),
    )
    haber_id = cursor.lastrowid

    # Slayt URL'lerini ayarlar tablosuna eşle (onay_isle.py bu anahtarları okur)
    con.execute(
        "INSERT INTO ayarlar (anahtar, deger) VALUES (?, ?) "
        "ON CONFLICT(anahtar) DO UPDATE SET deger = excluded.deger",
        (f"tur_gorselleri_{haber_id}", json.dumps([url_kapak, url_kadro])),
    )
    con.commit()

    # 5. Telegram Onay Grubuna Sun
    if telegrama_gonder:
        telegram_bot.slaytlari_gonder([url_kapak, url_kadro], basliklar=[baslik, "İlk 11 Kadrosu"])
        ana_bilgi = (
            f"📋 <b>RESMİ MAÇ KADROSU ONAYI</b>\n\n"
            f"⚽ <b>{baslik}</b>\n\n"
            f"⏱️ Başlama Saati: {saat}\n"
            f"🏟️ {kadro_verisi.get('mac_bilgisi', '')}\n\n"
            f"📌 <i>Bu gönderi Carousel olarak (IG, Threads, FB, X) paylaşılacaktır.</i>"
        )
        menu = telegram_bot.yayin_zamani_menusu(2)
        onay_mesaj_id = telegram_bot.mesaj_gonder(ana_bilgi, butonlar=menu["inline_keyboard"], html=True)
        con.execute(
            "UPDATE haberler SET telegram_message_id = ? WHERE id = ?",
            (onay_mesaj_id, haber_id),
        )

    # İşlendi olarak işaretle
    con.execute(
        "INSERT INTO ayarlar (anahtar, deger) VALUES (?, ?) "
        "ON CONFLICT(anahtar) DO UPDATE SET deger = excluded.deger",
        (anahtar_yayin, datetime.now(timezone.utc).isoformat()),
    )
    con.commit()
    log.info("Fikstür #%s kadro carousel postu başarıyla hazırlandı (haber_id=%s).", fixture_id, haber_id)
    return haber


# =============================================================================
# 2. MAÇ SONU SESLENDİRMELİ REELS & CAROUSEL AKIŞI
# =============================================================================

def mac_sonu_haberi_hazirla_ve_sun(
    fixture_id: int,
    con: sqlite3.Connection,
    ayarlar: dict,
    telegrama_gonder: bool = True,
) -> dict | None:
    """
    Maç bittikten en az 15 dakika sonra çalışan maç sonu bülten motoru:
      - API-Football'dan skor, goller, kartlar ve istatistikleri çeker.
      - Gemini ile editoryal maç hikayesi, analiz ve puan tablosu metnini yazar.
      - 3 Slaytlık infografik seti ve ElevenLabs Alex seslendirmeli dikey video üretir.
      - Telegram'a videolu onay kartı sunar.
    """
    anahtar_yayin = f"spor_mac_sonu_{fixture_id}"
    zaten = con.execute("SELECT deger FROM ayarlar WHERE anahtar = ?", (anahtar_yayin,)).fetchone()
    if zaten:
        log.info("Fikstür #%s maç sonu bülteni zaten yayınlanmış, atlanıyor.", fixture_id)
        return None

    # 15 Dakika bekleme şartı kontrolü
    doldu, gecen = bekleme_suresi_doldu_mu(fixture_id, con, asgari_dakika=15)
    if not doldu:
        log.info("Fikstür #%s maç sonu için 15 dakika bekleme penceresinde (geçen: %.1f dk).", fixture_id, gecen)
        return None

    # Fikstür maç sonu detaylarını çek
    fix_res = fetch_kadro.api_football_istek("fixtures", {"id": fixture_id})
    f_list = fix_res.get("response", [])
    if not f_list:
        log.warning("Fikstür #%s bulunamadı", fixture_id)
        return None

    fix_data = f_list[0]
    fixture_info = fix_data.get("fixture", {})
    status_short = fixture_info.get("status", {}).get("short", "")
    if status_short not in ("FT", "AET", "PEN"):
        log.info("Fikstür #%s henüz tamamlanmamış (durum: %s).", fixture_id, status_short)
        return None

    teams = fix_data.get("teams", {})
    goals = fix_data.get("goals", {})
    league = fix_data.get("league", {})
    events = fix_data.get("events", [])

    ev_ad = teams.get("home", {}).get("name", "")
    dep_ad = teams.get("away", {}).get("name", "")
    g_ev = goals.get("home", 0)
    g_dep = goals.get("away", 0)
    turnuva = (league.get("name") or "FUTBOL KARŞILAŞMASI").upper()
    skor_str = f"{g_ev} - {g_dep}"

    # Gol atanları ve kritik olayları özetle
    goller = []
    for ev in events:
        if ev.get("type") == "Goal":
            dakika = ev.get("time", {}).get("elapsed", "")
            oyuncu = ev.get("player", {}).get("name", "")
            takim = ev.get("team", {}).get("name", "")
            detail = ev.get("detail", "")
            ek = " (P)" if "Penalty" in detail else (" (KK)" if "Own Goal" in detail else "")
            goller.append(f"{dakika}' {oyuncu}{ek} ({takim})")

    gol_ozeti = ", ".join(goller) if goller else "Gol sesi çıkmadı"

    # İstatistik sorgusu
    stats_res = fetch_kadro.api_football_istek("fixtures/statistics", {"fixture": fixture_id})
    stats_list = stats_res.get("response", [])
    stats_text = ""
    for st in stats_list:
        tname = st.get("team", {}).get("name", "")
        s_dict = {s.get("type"): s.get("value") for s in st.get("statistics", [])}
        stats_text += f"{tname}: Şut: {s_dict.get('Total Shots', 0)} (İsabet: {s_dict.get('Shots on Goal', 0)}), Topla Oynama: {s_dict.get('Ball Possession', '50%')}\n"

    # Gemini ile editoryal maç sonu analizi yaz
    prompt = f"""Aşağıdaki resmi futbol karşılaşması verilerini kullanarak Daily Brief için yüksek kaliteli, tarafsız ve profesyonel bir MAÇ SONU HABERİ hazırla.

Karşılaşma: {ev_ad} {skor_str} {dep_ad}
Turnuva: {turnuva}
Goller: {gol_ozeti}
İstatistikler:
{stats_text}

Format Kuralları:
- SIFIR MARKDOWN KURALI: Metinlerde ASLA ** (yıldız) veya kalıp etiketler kullanma!
- Doğal Tümce Düzeni (Sentence Case).
- ig_baslik: Çarpıcı, prestijli Türkçe başlık (max 80 karakter).
- slayt_ozet: 1-2 cümlelik vurucu özet (maçın galibi, golleri ve genel atmosfer).
- detay_metni: 2 ferah paragraflık editoryal analiz. 1. paragrafta goller ve maçın hikayesi, 2. paragrafta puan durumu ve takımlara etkisi.
- ig_caption: 2-3 paragraflık akıcı Instagram ve sosyal medya metni.
- onem_puani: 1 ile 10 arasında bir tam sayı (örn: 9).
- vurgu_sayi: "{skor_str}"
- vurgu_etiket: "Maç Sonucu"
- neden_onemli: Puan tablosu ve derbi/lig dengesi açısından önemi.
- sana_etkisi: Şampiyonluk yarışı ve taraftara yansıması.

Şu JSON formatında döndür:
{{
  "ig_baslik": "...",
  "slayt_ozet": "...",
  "detay_metni": "...",
  "ig_caption": "...",
  "onem_puani": 9,
  "vurgu_sayi": "{skor_str}",
  "vurgu_etiket": "Maç Sonucu",
  "neden_onemli": "...",
  "sana_etkisi": "..."
}}
Sadece saf JSON döndür."""

    try:
        metinler = generate_text.gemini_cagir(prompt, ayarlar)
    except Exception as e:
        log.error("Gemini maç sonu metin üretiminde hata: %s", e)
        # Güvenli fallback metni
        metinler = {
            "ig_baslik": f"{ev_ad} {skor_str} {dep_ad} Maç Sonucu",
            "slayt_ozet": f"{turnuva} mücadelesinde {ev_ad} ile {dep_ad} arasındaki karşılaşma {skor_str} sona erdi. Goller: {gol_ozeti}.",
            "detay_metni": f"{ev_ad} ve {dep_ad} sahadan {skor_str} skorla ayrıldı. Karşılaşmada atılan goller: {gol_ozeti}.",
            "ig_caption": f"{turnuva} mücadelesinde {ev_ad} ile {dep_ad} karşı karşıya geldi. Maç {skor_str} bitti.",
            "onem_puani": 8,
            "vurgu_sayi": skor_str,
            "vurgu_etiket": "Maç Sonucu",
            "neden_onemli": "Zirve yarışında kritik puanlar dağıtıldı.",
            "sana_etkisi": "Süper Lig puan durumunda sıralama güncellendi.",
        }

    baslik = metinler.get("ig_baslik") or f"{ev_ad} {skor_str} {dep_ad}"
    spot = metinler.get("slayt_ozet") or ""

    cikti_klasor = KOK / "data" / "output"
    cikti_klasor.mkdir(parents=True, exist_ok=True)

    # Maç Sonu 3D Skor Tahtası Kapak Slaytı
    kapak_veri = {
        "ev_sahibi": ev_ad,
        "deplasman": dep_ad,
        "skor_veya_saat": skor_str,
        "turnuva": turnuva,
        "mac_bilgisi": f"Maç Sonucu · Goller: {gol_ozeti[:50]}",
        "mac_sonu": True,
    }
    haber_kapak = {
        "id": fixture_id,
        "kategori": "spor",
        "kaynak": "Daily Brief Spor",
        "ig_baslik": baslik,
        "slayt_ozet": spot,
        "sablon_verisi": json.dumps(kapak_veri, ensure_ascii=False),
    }

    img_kapak = sablonlar.spor_kapak.spor_kapak_slayti_ciz(haber_kapak, kapak_veri, ayarlar, kaynak="Daily Brief Spor")
    yol_kapak = cikti_klasor / f"mac_sonu_{fixture_id}_1_kapak.jpg"
    img_kapak.save(yol_kapak, "JPEG", quality=95, optimize=True)

    # Detay Slaytları (Pillow Tipografi Motoru: 1080x1920 4:5 Safe Area)
    detay_sayfalar = make_image.detay_sayfalara_bol(
        metinler.get("detay_metni", ""),
        ayarlar,
        vurgu=(skor_str, "Maç Sonucu"),
        neden_onemli=metinler.get("neden_onemli"),
        sana_etkisi=metinler.get("sana_etkisi"),
    )

    detay_yollari = [yol_kapak]
    toplam_sayfa = 1 + max(1, len(detay_sayfalar))

    for i, satirlar in enumerate(detay_sayfalar[:2], start=2):
        story_d = make_image.story_detay(
            baslik,
            metinler.get("detay_metni", ""),
            "Daily Brief Spor",
            ayarlar,
            kategori="spor",
            satirlar=satirlar,
            sayfa=i,
            toplam_sayfa=toplam_sayfa,
        )
        yol_d = cikti_klasor / f"mac_sonu_{fixture_id}_detay_{i}.jpg"
        story_d.save(yol_d, "JPEG", quality=95, optimize=True)
        detay_yollari.append(yol_d)

    # Görselleri CDN'e yükle
    yuklenenler = upload_image.hepsini_yukle(detay_yollari, ayarlar)
    urller = [y["url"] for y in yuklenenler]

    # ElevenLabs Seslendirmeli Dikey Video Üretimi
    video_yolu = None
    try:
        from src import video, ses
        dikey_gorseller = video.reels_dikey_gorselleri_uret(urller, haberler=[haber_kapak], ayarlar=ayarlar)
        if dikey_gorseller:
            ses_sonucu = {}
            video_yolu = ses.anlatimli_video_uret(
                dikey_gorseller,
                [haber_kapak],
                ayarlar,
                muzik=True,
                sonuc=ses_sonucu,
            )
            log.info("Fikstür #%s maç sonu seslendirmeli video üretildi: %s", fixture_id, video_yolu)
    except Exception as e_v:
        log.warning("Maç sonu sesli video üretilemedi: %s", e_v)

    # Veritabanı kaydı
    caption_metni = (
        f"{baslik}\n\n"
        f"{metinler.get('ig_caption', spot)}\n\n"
        f"⚽ Skor: {ev_ad} {skor_str} {dep_ad}\n"
        f"🥅 Goller: {gol_ozeti}\n\n"
        f"#DailyBrief #MaçSonucu #SüperLig #{fetch_kulup_logo.takim_slug_yap(ev_ad)} #{fetch_kulup_logo.takim_slug_yap(dep_ad)}"
    )

    cursor = con.execute(
        """INSERT OR REPLACE INTO haberler (
            kaynak, kategori, agirlik, baslik_orj, link, ozet_orj,
            ig_baslik, slayt_ozet, ig_caption, detay_sablonu, sablon_verisi,
            gorsel_yolu, gorsel_url, story_url, detay_url, son_dakika,
            durum, yayin_tarihi, cekilme_zamani
        ) VALUES (
            'Daily Brief Spor', 'spor', 10, ?, ?, ?,
            ?, ?, ?, 'spor_mac_sonu', ?,
            ?, ?, ?, ?, 1,
            'onay_bekliyor', datetime('now'), datetime('now')
        )""",
        (
            baslik,
            f"https://dailybrief.co/mac-sonu/{fixture_id}",
            spot,
            baslik,
            spot,
            caption_metni,
            json.dumps(kapak_veri, ensure_ascii=False),
            str(yol_kapak),
            urller[0],
            urller[0],
            json.dumps(urller[1:]),
        ),
    )
    haber_id = cursor.lastrowid

    con.execute(
        "INSERT INTO ayarlar (anahtar, deger) VALUES (?, ?) "
        "ON CONFLICT(anahtar) DO UPDATE SET deger = excluded.deger",
        (f"tur_gorselleri_{haber_id}", json.dumps(urller)),
    )
    con.commit()

    # Telegram Onay Grubuna Sun (Video + Slaytlar + Yayın Butonları)
    if telegrama_gonder:
        if video_yolu and Path(video_yolu).exists():
            try:
                telegram_bot.video_gonder(
                    video_yolu,
                    aciklama=f"🎙️ <b>SESLENDİRMELİ REELS VİDEOSU</b>\n\n<b>{baslik}</b>\n\n{caption_metni[:400]}...",
                )
            except Exception as e_tgv:
                log.warning("Telegram'a video iletilemedi: %s", e_tgv)

        telegram_bot.slaytlari_gonder(urller, basliklar=[baslik, "Maçın Özeti & Goller", "Puan Durumu"])
        ana_bilgi = (
            f"🎙️ <b>SESLENDİRMELİ MAÇ SONU REELS & CAROUSEL ONAYI</b>\n\n"
            f"⚽ <b>{baslik}</b>\n\n"
            f"⏱️ Skor: {skor_str}\n"
            f"🥅 Goller: {gol_ozeti}\n\n"
            f"📌 <i>Bu bülten Instagram Reels, YouTube Shorts, TikTok ve 4:5 Carousel Akışına eşzamanlı gidecektir.</i>"
        )
        menu = telegram_bot.sesli_yayin_zamani_menusu(muzikli=True, adet=len(urller))
        onay_mesaj_id = telegram_bot.mesaj_gonder(ana_bilgi, butonlar=menu["inline_keyboard"], html=True)
        con.execute(
            "UPDATE haberler SET telegram_message_id = ? WHERE id = ?",
            (onay_mesaj_id, haber_id),
        )

    # İşlendi olarak kaydet
    con.execute(
        "INSERT INTO ayarlar (anahtar, deger) VALUES (?, ?) "
        "ON CONFLICT(anahtar) DO UPDATE SET deger = excluded.deger",
        (anahtar_yayin, datetime.now(timezone.utc).isoformat()),
    )
    con.commit()
    log.info("Fikstür #%s maç sonu seslendirmeli bülteni hazırlandı (haber_id=%s).", fixture_id, haber_id)
    return haber_kapak


# =============================================================================
# 3. ANA OTOMATİK TARAMA & ZAMANLAYICI MOTORU
# =============================================================================

def otomatik_spor_taramasi(con: sqlite3.Connection, ayarlar: dict, telegrama_gonder: bool = True) -> dict:
    """
    Her periyodik döngüde (saatlik veya cron ile) çalışan ana spor tarama motoru:
      1. Günün 4 Büyükler maçlarını bulur.
      2. Maçtan önce resmi ilk 11'ler geldiyse Kadro Carousel postunu hazırlar.
      3. Maç bittikten (FT) en az 15 dakika geçtiyse Maç Sonu Sesli Reels bültenini hazırlar.
    """
    maclar = gunun_dort_buyuk_maclari()
    rapor = {
        "taranan_mac_sayisi": len(maclar),
        "kadro_hazirlanan": [],
        "mac_sonu_hazirlanan": [],
        "beklemede": [],
    }

    if not maclar:
        log.info("Bugün 4 Büyüklerin planlanmış bir karşılaşması bulunamadı.")
        return rapor

    for f in maclar:
        f_id = f.get("fixture", {}).get("id")
        h_name = f.get("teams", {}).get("home", {}).get("name", "")
        a_name = f.get("teams", {}).get("away", {}).get("name", "")
        status = f.get("fixture", {}).get("status", {}).get("short", "NS")

        mac_tanim = f"#{f_id} {h_name} vs {a_name} ({status})"

        # A) MAÇ SONU KONTROLÜ (FT / AET / PEN)
        if status in ("FT", "AET", "PEN"):
            anahtar_son = f"spor_mac_sonu_{f_id}"
            zaten_son = con.execute("SELECT deger FROM ayarlar WHERE anahtar = ?", (anahtar_son,)).fetchone()
            if not zaten_son:
                doldu, gecen = bekleme_suresi_doldu_mu(f_id, con, asgari_dakika=15)
                if doldu:
                    log.info("Maç bitti ve 15 dk doldu (geçen: %.1f dk): %s", gecen, mac_tanim)
                    try:
                        res = mac_sonu_haberi_hazirla_ve_sun(f_id, con, ayarlar, telegrama_gonder=telegrama_gonder)
                        if res:
                            rapor["mac_sonu_hazirlanan"].append(mac_tanim)
                    except Exception as e_ms:
                        log.error("Maç sonu bülteni hazırlama hatası (%s): %s", mac_tanim, e_ms)
                else:
                    log.info("Maç sonu 15 dk bekleme penceresinde (geçen: %.1f dk): %s", gecen, mac_tanim)
                    rapor["beklemede"].append(f"{mac_tanim} - {gecen:.1f}/15 dk")
            continue

        # B) MAÇ ÖNÜ KADRO KONTROLÜ (NS / TBD)
        if status in ("NS", "TBD"):
            anahtar_kadro = f"spor_kadro_{f_id}"
            zaten_kadro = con.execute("SELECT deger FROM ayarlar WHERE anahtar = ?", (anahtar_kadro,)).fetchone()
            if not zaten_kadro:
                # Başlama saatine bak (75 dakika içindeyse kadro sorgula)
                mac_dt_str = f.get("fixture", {}).get("date", "")
                zaman_uygun = True
                if mac_dt_str:
                    try:
                        dt = datetime.fromisoformat(mac_dt_str.replace("Z", "+00:00"))
                        fark_dk = (dt - datetime.now(timezone.utc)).total_seconds() / 60.0
                        # Maça 80 dakikadan fazla varsa henüz kadrolar açıklanmamıştır
                        if fark_dk > 80:
                            zaman_uygun = False
                    except Exception:
                        pass

                if zaman_uygun:
                    try:
                        res = kadro_haberi_hazirla_ve_sun(f_id, con, ayarlar, telegrama_gonder=telegrama_gonder)
                        if res:
                            rapor["kadro_hazirlanan"].append(mac_tanim)
                    except Exception as e_kd:
                        log.warning("Kadro hazırlama denemesi (%s): %s", mac_tanim, e_kd)

    return rapor


def spor_durumu_raporu(con: sqlite3.Connection, ayarlar: dict) -> str:
    """Telegram /spor komutu için canlı 4 Büyükler maç durum özeti metnini üretir."""
    maclar = gunun_dort_buyuk_maclari()
    if not maclar:
        return "⚽ <b>BUGÜN 4 BÜYÜKLERİN MAÇI YOK</b>\n\nBugün Galatasaray, Fenerbahçe, Beşiktaş veya Trabzonspor'un planlanmış resmi bir karşılaşması bulunmuyor."

    satirlar = [f"⚽ <b>GÜNÜN 4 BÜYÜKLER KARŞILAŞMALARI ({len(maclar)} Maç)</b>\n"]
    for idx, f in enumerate(maclar, 1):
        f_id = f.get("fixture", {}).get("id")
        h_name = f.get("teams", {}).get("home", {}).get("name", "")
        a_name = f.get("teams", {}).get("away", {}).get("name", "")
        status = f.get("fixture", {}).get("status", {}).get("short", "NS")
        league = f.get("league", {}).get("name", "Lig")

        # Saat
        dt_str = f.get("fixture", {}).get("date", "")
        saat_tr = "20:00"
        if dt_str:
            try:
                dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                saat_tr = dt.astimezone(timezone(timedelta(hours=3))).strftime("%H:%M")
            except Exception:
                pass

        kadro_var = bool(con.execute("SELECT 1 FROM ayarlar WHERE anahtar = ?", (f"spor_kadro_{f_id}",)).fetchone())
        mac_sonu_var = bool(con.execute("SELECT 1 FROM ayarlar WHERE anahtar = ?", (f"spor_mac_sonu_{f_id}",)).fetchone())

        if status in ("FT", "AET", "PEN"):
            gh = f.get("goals", {}).get("home", 0)
            ga = f.get("goals", {}).get("away", 0)
            durum_str = f"✅ Bitti ({gh}-{ga})"
            bulten_str = "🎙️ Sesli Reels Yayınlandı" if mac_sonu_var else "⏳ 15 Dk Bekleme / Hazırlıkta"
        elif status in ("1H", "HT", "2H", "ET", "P"):
            gh = f.get("goals", {}).get("home", 0)
            ga = f.get("goals", {}).get("away", 0)
            durum_str = f"🟢 Canlı Oynanıyor ({gh}-{ga})"
            bulten_str = "Maç Devam Ediyor"
        else:
            durum_str = f"⏳ Saat {saat_tr}"
            bulten_str = "📋 Kadro Carousel Yayında" if kadro_var else "⏳ Kadro Bekleniyor"

        satirlar.append(
            f"<b>{idx}. {h_name} vs {a_name}</b>\n"
            f"   🏆 {league}  ·  {durum_str}\n"
            f"   📊 Durum: {bulten_str} (ID: <code>{f_id}</code>)\n"
        )

    satirlar.append("<i>Kadro maçtan 1 saat önce Carousel; maç sonu haberi ise bitimden 15 dk sonra sesli Reels olarak otomatik hazırlanır.</i>")
    return "\n".join(satirlar)
