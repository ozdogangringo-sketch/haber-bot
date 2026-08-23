"""
yonetim.py — Bot yönetim ve acil durum kontrol merkezi.

Bu modül Telegram'dan tetiklenen yönetim ve acil durum operasyonlarını yönetir:
  * Botu geçici süreyle duraklatma (1s, 6s, 12s, 24s) / devam ettirme
  * Cron job'ların duraklatma durumunu denetlemesi
  * Instagram, Facebook, Threads, Gemini API bağlantı sağlık testleri
  * Canlı kota, havuz ve veritabanı istatistik raporu
  * Askıda / cevapsız kalan açık turları temizleme
"""

import logging
import os
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

log = logging.getLogger(__name__)

# Ayarlar tablosunda duraklatma anahtarları
ANAHTAR_DURAKLATMA_BITIS = "bot_duraklatma_bitis"
ANAHTAR_DURAKLATAN_KISI = "bot_duraklatan_kisi"


def duraklatildi_mi(con) -> tuple[bool, str]:
    """
    Botun şu an duraklatılmış olup olmadığını denetler.

    Döner: `(duraklatildi, kalan_sure_aciklamasi)`
    """
    satir = con.execute(
        "SELECT deger FROM ayarlar WHERE anahtar = ?",
        (ANAHTAR_DURAKLATMA_BITIS,),
    ).fetchone()

    if not satir or not satir["deger"]:
        return False, ""

    try:
        bitis = datetime.fromisoformat(satir["deger"])
        if bitis.tzinfo is None:
            bitis = bitis.replace(tzinfo=timezone.utc)

        simdi = datetime.now(timezone.utc)
        if simdi < bitis:
            fark = bitis - simdi
            toplam_dakika = int(fark.total_seconds() // 60)
            saat = toplam_dakika // 60
            dakika = toplam_dakika % 60
            kalan = f"{saat}s {dakika}dk" if saat > 0 else f"{dakika} dakika"
            return True, kalan
        else:
            devam_et(con)
            return False, ""
    except Exception as e:
        log.warning("duraklatma denetiminde hata: %s", e)
        return False, ""


def duraklat(con, saat: int, basan: str = "") -> datetime:
    """
    Botu belirtilen saat kadar duraklatır.
    Cron'lar (hazırla, son dakika, hatırlat) bu süre boyunca çalışmaz.
    """
    bitis = datetime.now(timezone.utc) + timedelta(hours=saat)
    con.execute(
        "INSERT INTO ayarlar (anahtar, deger) VALUES (?, ?) "
        "ON CONFLICT(anahtar) DO UPDATE SET deger = excluded.deger",
        (ANAHTAR_DURAKLATMA_BITIS, bitis.isoformat()),
    )
    if basan:
        con.execute(
            "INSERT INTO ayarlar (anahtar, deger) VALUES (?, ?) "
            "ON CONFLICT(anahtar) DO UPDATE SET deger = excluded.deger",
            (ANAHTAR_DURAKLATAN_KISI, basan),
        )
    con.commit()
    log.info("bot %s saat duraklatıldı (bitiş: %s, basan: %s)", saat, bitis.isoformat(), basan)
    return bitis


def devam_et(con, basan: str = "") -> None:
    """Botun duraklatmasını kaldırır, cron'lar normal çalışmaya döner."""
    con.execute(
        "DELETE FROM ayarlar WHERE anahtar IN (?, ?)",
        (ANAHTAR_DURAKLATMA_BITIS, ANAHTAR_DURAKLATAN_KISI),
    )
    con.commit()
    log.info("bot duraklatması kaldırıldı (basan: %s)", basan)


def api_saglik_testi(ayarlar: dict) -> list[dict]:
    """
    Instagram, Facebook, Threads, Gemini ve ImgBB API bağlantılarını test eder.
    Her servis için durum ve açıklama döner.
    """
    sonuclar = []

    # 1. Instagram Graph API Testi
    ig_user_id = os.getenv("IG_USER_ID", "").strip()
    ig_token = os.getenv("IG_ACCESS_TOKEN", "").strip()
    if not ig_token or not ig_user_id:
        sonuclar.append({
            "ad": "Instagram Graph API",
            "durum": False,
            "mesaj": "IG_USER_ID veya IG_ACCESS_TOKEN eksik.",
        })
    else:
        try:
            r = requests.get(
                f"https://graph.facebook.com/v21.0/{ig_user_id}",
                params={"fields": "id,username", "access_token": ig_token},
                timeout=10,
            )
            veri = r.json()
            if r.status_code == 200 and "id" in veri:
                username = veri.get("username", ig_user_id)
                sonuclar.append({
                    "ad": "Instagram Graph API",
                    "durum": True,
                    "mesaj": f"Bağlantı başarılı (@{username})",
                })
            else:
                hata = veri.get("error", {}).get("message", r.text[:80])
                sonuclar.append({
                    "ad": "Instagram Graph API",
                    "durum": False,
                    "mesaj": f"Hata: {hata}",
                })
        except Exception as e:
            sonuclar.append({
                "ad": "Instagram Graph API",
                "durum": False,
                "mesaj": f"İstek hatası: {type(e).__name__}",
            })

    # 2. Facebook Sayfa API Testi
    fb_aktif = bool((ayarlar.get("sosyal", {}) or {}).get("facebooka_da_at"))
    if not fb_aktif:
        sonuclar.append({
            "ad": "Facebook Sayfa API",
            "durum": True,
            "mesaj": "Devre dışı (config'de kapalı)",
        })
    elif not ig_token:
        sonuclar.append({
            "ad": "Facebook Sayfa API",
            "durum": False,
            "mesaj": "IG_ACCESS_TOKEN (Sayfa jetonu) eksik.",
        })
    else:
        try:
            r = requests.get(
                "https://graph.facebook.com/v21.0/me",
                params={"fields": "id,name", "access_token": ig_token},
                timeout=10,
            )
            veri = r.json()
            if r.status_code == 200 and "id" in veri:
                name = veri.get("name", "Sayfa")
                sonuclar.append({
                    "ad": "Facebook Sayfa API",
                    "durum": True,
                    "mesaj": f"Bağlantı başarılı ({name})",
                })
            else:
                hata = veri.get("error", {}).get("message", r.text[:80])
                sonuclar.append({
                    "ad": "Facebook Sayfa API",
                    "durum": False,
                    "mesaj": f"Hata: {hata}",
                })
        except Exception as e:
            sonuclar.append({
                "ad": "Facebook Sayfa API",
                "durum": False,
                "mesaj": f"İstek hatası: {type(e).__name__}",
            })

    # 3. Threads API Testi
    th_aktif = bool((ayarlar.get("sosyal", {}) or {}).get("threadse_de_at"))
    th_token = os.getenv("THREADS_ACCESS_TOKEN", "").strip()
    if not th_aktif:
        sonuclar.append({
            "ad": "Threads API",
            "durum": True,
            "mesaj": "Devre dışı (config'de kapalı)",
        })
    elif not th_token:
        sonuclar.append({
            "ad": "Threads API",
            "durum": False,
            "mesaj": "THREADS_ACCESS_TOKEN eksik.",
        })
    else:
        try:
            r = requests.get(
                "https://graph.threads.net/v1.0/me",
                params={"fields": "id,username", "access_token": th_token},
                timeout=10,
            )
            veri = r.json()
            if r.status_code == 200 and "id" in veri:
                username = veri.get("username", "Threads")
                sonuclar.append({
                    "ad": "Threads API",
                    "durum": True,
                    "mesaj": f"Bağlantı başarılı (@{username})",
                })
            else:
                hata = veri.get("error", {}).get("message", r.text[:80])
                sonuclar.append({
                    "ad": "Threads API",
                    "durum": False,
                    "mesaj": f"Hata: {hata}",
                })
        except Exception as e:
            sonuclar.append({
                "ad": "Threads API",
                "durum": False,
                "mesaj": f"İstek hatası: {type(e).__name__}",
            })

    # 4. Gemini API Testi
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not gemini_key:
        sonuclar.append({
            "ad": "Gemini AI API",
            "durum": False,
            "mesaj": "GEMINI_API_KEY eksik.",
        })
    else:
        try:
            r = requests.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                params={"key": gemini_key, "pageSize": 1},
                timeout=10,
            )
            if r.status_code == 200:
                sonuclar.append({
                    "ad": "Gemini AI API",
                    "durum": True,
                    "mesaj": "Bağlantı ve API anahtarı aktif",
                })
            else:
                veri = r.json()
                hata = veri.get("error", {}).get("message", r.text[:80])
                sonuclar.append({
                    "ad": "Gemini AI API",
                    "durum": False,
                    "mesaj": f"Kota/Anahtar hatası: {hata}",
                })
        except Exception as e:
            sonuclar.append({
                "ad": "Gemini AI API",
                "durum": False,
                "mesaj": f"İstek hatası: {type(e).__name__}",
            })

    # 5. ImgBB Görsel Barındırma
    imgbb_key = os.getenv("IMGBB_API_KEY", "").strip()
    if not imgbb_key:
        sonuclar.append({
            "ad": "ImgBB Görsel API",
            "durum": False,
            "mesaj": "IMGBB_API_KEY eksik.",
        })
    else:
        sonuclar.append({
            "ad": "ImgBB Görsel API",
            "durum": True,
            "mesaj": "Anahtar tanımlı",
        })

    # 6. X (Twitter) API v2 Testi
    tw_aktif = bool((ayarlar.get("sosyal", {}) or {}).get("twittera_da_at"))
    if not tw_aktif:
        sonuclar.append({
            "ad": "X (Twitter) API v2",
            "durum": True,
            "mesaj": "Devre dışı (config'de kapalı)",
        })
    else:
        from src import twitter
        sonuclar.append(twitter.api_saglik_testi())

    return sonuclar


def kota_ve_durum_raporu(con, ayarlar: dict) -> str:
    """
    Veritabanı durumunu, haber sayılarını ve Gemini ücretli kullanım istatistiklerini raporlar.
    """
    satirlar = ["📊 <b>CANLI DURUM & KOTA RAPORU</b>\n"]

    # 1. Duraklatma Durumu
    duraklatildi, kalan = duraklatildi_mi(con)
    if duraklatildi:
        satirlar.append(f"⏸️ <b>Bot Durumu:</b> DURAKLATILDI (Kalan: {kalan})")
    else:
        satirlar.append("🟢 <b>Bot Durumu:</b> AKTİF (Tüm cronlar devrede)")

    # 2. Havuz ve Haber Sayıları
    sinir = datetime.now(timezone.utc) - timedelta(
        hours=ayarlar.get("genel", {}).get("yayin_yasi_siniri_saat", 36)
    )
    taze_havuz = con.execute(
        "SELECT COUNT(*) FROM haberler WHERE durum = 'metin_hazir' "
        "AND yayin_tarihi >= ?",
        (sinir.isoformat(),),
    ).fetchone()[0]

    yayinlanan = con.execute(
        "SELECT COUNT(*) FROM haberler WHERE durum = 'yayinlandi'"
    ).fetchone()[0]

    toplam_haber = con.execute("SELECT COUNT(*) FROM haberler").fetchone()[0]

    satirlar.append(f"📰 <b>Taze Haber Havuzu:</b> {taze_havuz} hazır haber")
    satirlar.append(f"✅ <b>Yayınlanan Toplam:</b> {yayinlanan} haber")
    satirlar.append(f"💾 <b>Veritabanı Toplam:</b> {toplam_haber} kayıt")

    # 3. Gemini Ücretli Anahtar Kullanımı
    try:
        yedek_yolu = Path("data") / "yedek_anahtar_kullanimi.txt"
        if yedek_yolu.exists():
            icerik = yedek_yolu.read_text(encoding="utf-8").strip().splitlines()
            if icerik:
                sayac = Counter(icerik)
                bugun = date.today().isoformat()
                bugunki = sayac.get(bugun, 0)
                toplam = len(icerik)
                satirlar.append(
                    f"\n💰 <b>Ücretli Gemini Kullanımı:</b>\n"
                    f"  • Bugün: {bugunki} çağrı\n"
                    f"  • Toplam: {toplam} çağrı"
                )
            else:
                satirlar.append("\n💰 <b>Ücretli Gemini Kullanımı:</b> 0 çağrı (Hepsi ücretsiz)")
        else:
            satirlar.append("\n💰 <b>Ücretli Gemini Kullanımı:</b> 0 çağrı (Hepsi ücretsiz)")
    except Exception as e:
        log.warning("kota raporunda yedek dosya okuma hatası: %s", e)

    return "\n".join(satirlar)


def askidaki_turlari_temizle(con) -> int:
    """
    Cevap verilmemiş, askıda kalan açık onay turlarını sıfırlar ve havuza iade eder.
    YAYINLANMIŞ haberlere asla dokunmaz.
    """
    cursor = con.execute(
        "UPDATE haberler SET durum = 'metin_hazir', telegram_message_id = NULL, "
        "planlanan_yayin = NULL WHERE durum IN ('onay_bekliyor', 'baslik_onayi', 'ertelendi') "
        "AND durum != 'yayinlandi'"
    )
    con.commit()
    adet = cursor.rowcount
    log.info("askıdaki %s haber temizlendi ve havuza iade edildi", adet)
    return adet
