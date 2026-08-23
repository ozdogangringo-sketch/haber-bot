"""
ekonomi_turu.py — Hafta içi ve hafta sonu sabah piyasa açılışıyla (TR 10:05) Ekonomi Turu hazırlar.

Yapı:
  * 1. Slayt: Canlı BIST 100, Dolar, Euro, Gram Altın, Bitcoin, Brent Petrol İnfografiği (Yeşil Temalı)
  * 2..N. Slaytlar: Günün seçme borsa, hisse, altın, döviz, faiz, merkez bankası haberleri (1 ila 5 haber)
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

# Kök klasörü sys.path'e ekle
KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

from src import (  # noqa: E402
    caption, db, db_senkron, generate_text, make_image,
    piyasa, piyasa_kart, slaytlar, telegram_bot, upload_image, yonetim,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ekonomi_turu")


def main() -> int:
    ayarlar_yolu = KOK / "config.yaml"
    with open(ayarlar_yolu, encoding="utf-8") as f:
        ayarlar = yaml.safe_load(f)

    con = db.baglan()

    # 1. Bot duraklatılmış mı kontrol et
    duraklatildi, kalan = yonetim.duraklatildi_mi(con)
    if duraklatildi:
        log.info("Bot duraklatılmış durumda (kalan: %s), ekonomi turu atlanıyor", kalan)
        return 0

    log.info("--- EKONOMİ & PİYASA TURU HAZIRLANIYOR ---")

    # 2. Canlı piyasa göstergelerini çek
    piyasa_verileri = piyasa.piyasa_verileri_getir()

    # 3. 1. Slayt (Yeşil Temalı İnfografik Kartı) üret ve ImgBB'ye yükle
    kart_yolu = piyasa_kart.piyasa_karti_uret(piyasa_verileri)
    kart_yukleme = upload_image.gorsel_yukle(kart_yolu, ayarlar)
    kart_url = kart_yukleme["url"]

    # 4. Taze ekonomi haberlerini seç (Piyasa ve finans odaklı puanlama)
    sinir = datetime.now(timezone.utc) - timedelta(
        hours=ayarlar.get("genel", {}).get("yayin_yasi_siniri_saat", 48)
    )


    sorgu = """
    SELECT * FROM haberler
    WHERE (
        kaynak IN ('Borsa Gündem', 'Investing TR Hisse', 'BloombergHT', 'Investing TR Piyasa', 'AA Ekonomi', 'Dünya Gazetesi', 'Webrazzi')
        OR kategori = 'ekonomi'
    )
      AND COALESCE(daha_once_yayinlandi, 0) = 0
      AND (telegram_message_id IS NULL OR telegram_message_id = 0)
      AND yayin_tarihi >= ?
    """
    tum_adaylar = list(con.execute(sorgu, (sinir.isoformat(),)))

    ONEMLI_KELIMELER = [
        "borsa", "bist", "hisse", "halka arz", "gong", "altın", "dolar", "euro", "döviz",
        "merkez bankası", "tcmb", "faiz", "enflasyon", "kripto", "bitcoin", "ethereum",
        "petrol", "brent", "yatırım", "temettü", "fed", "bilanço", "ihracat", "ithalat", "şirket",
        "fon", "milyon dolar", "milyar dolar", "fitch", "moody", "jpmorgan", "banka",
        "kazandırdı", "kazandıranlar", "piyasa", "endeks", "tahvil", "bono", "mevduat",
        "nasdaq", "sp500", "dow jones", "gelir tablosu", "kar payı", "satın alma", "birleşme"
    ]
    YASAK_KELIMELER = [
        "saldırı", "füze", "gazze", "lübnan", "israil", "suriy", "kaza", "otobüs",
        "yangın", "anız", "cinayet", "tutukla", "yaralı", "ölü", "muayene", "depozito",
        "çocuk gizliliği", "evlilik", "hava durumu", "kölelik", "esir", "terör", "savaş",
        "japonya", "lgs", "tarımsal destekleme", "turist", "turizm", "havalimanı",
        "uçuş", "yolcu", "hangar", "kosgeb", "destekleme", "hibe", "fındık", "buğday",
        "hasat", "çiftçi", "gübre", "emlakçı", "zabıta", "kaçakçılık", "sahte",
        "operasyon", "gözaltı", "trafik cezası", "pasaport", "vize", "öğrenci", "okul"
    ]

    puanli_adaylar = []
    for h in tum_adaylar:
        baslik = ((h["ig_baslik"] or h["baslik_orj"]) or "").lower()
        
        # 1. Yasaklı genel/asayiş/turizm/tarım haberlerini doğrudan ele
        if any(y in baslik for y in YASAK_KELIMELER):
            continue

        # 2. KATİ FİNANS ŞARTI: Başlıkta en az 1 borsa/finans terimi geçmek ZORUNDADIR
        if not any(k in baslik for k in ONEMLI_KELIMELER):
            continue

        puan = h["onem_puani"] or 5
        for k in ONEMLI_KELIMELER:
            if k in baslik:
                puan += 3
                
        # Saf borsa/finans kaynaklarına öncelik ver
        if h["kaynak"] in ("Borsa Gündem", "Investing TR Hisse", "BloombergHT", "Investing TR Piyasa"):
            puan += 6

        # Metni hazır olanlara ufak öncelik
        if h["durum"] == "metin_hazir" and h["ig_baslik"]:
            puan += 2
            
        puanli_adaylar.append((puan, h))

    puanli_adaylar.sort(key=lambda x: (x[0], x[1]["id"]), reverse=True)
    secilen_adaylar = [item[1] for item in puanli_adaylar[:5]]

    # Seçilenlerden metni eksik olanlar için metin üret
    eksik_metinliler = [h for h in secilen_adaylar if not h["ig_baslik"]]
    if eksik_metinliler:
        try:
            generate_text.metinleri_uret(ayarlar=ayarlar, haberler=eksik_metinliler)
        except Exception as e:
            log.warning("Metin üretim hatası: %s", e)

    # Seçilenlerin güncel verilerini al
    secilen_haberler = []
    for h in secilen_adaylar:
        taze_h = con.execute("SELECT * FROM haberler WHERE id = ?", (h["id"],)).fetchone()
        if taze_h and (taze_h["ig_baslik"] or taze_h["baslik_orj"]):
            secilen_haberler.append(taze_h)

    log.info("Piyasa kartı + %s ekonomi haberi seçildi", len(secilen_haberler))

    # 5. Seçilen haberlerin slaytlarını üret ve ImgBB'ye yükle
    slayt_urlleri = [kart_url]
    slayt_sonuclari = [{"katman": "infografik", "atif": "Daily Briefing Finans", "yol": str(kart_yolu)}]

    for h in secilen_haberler:
        try:
            yol, katman, atif = slaytlar.slayt_uret(h, ayarlar)
            yukleme = upload_image.gorsel_yukle(yol, ayarlar)
            slayt_urlleri.append(yukleme["url"])
            slayt_sonuclari.append({"katman": katman, "atif": atif, "yol": str(yol)})
            con.execute(
                "UPDATE haberler SET gorsel_url = ?, gorsel_yolu = ?, "
                "gorsel_kaynagi = ?, gorsel_atif = ? WHERE id = ?",
                (yukleme["url"], str(yol), katman, atif, h["id"]),
            )
        except Exception as e:
            log.warning("Haber slaytı üretilemedi (id=%s): %s", h["id"], e)

    con.commit()

    # 5b. Story görseli üret ve yükle
    story_url = None
    try:
        story_basliklar = [h["ig_baslik"] or h["baslik_orj"] for h in secilen_haberler]
        story_gorsel = make_image.story_kapak(story_basliklar, ayarlar)
        story_yol = make_image.CIKTI_KLASORU / "story-kapak-ekonomi.jpg"
        story_gorsel.save(story_yol, "JPEG", quality=ayarlar["gorsel"].get("jpeg_kalite", 92), optimize=True)
        story_yukleme = upload_image.gorsel_yukle(story_yol, ayarlar)
        story_url = story_yukleme["url"]
        log.info("Ekonomi turu story görseli hazır: %s", story_url)
    except Exception as e:
        log.warning("Ekonomi turu story görseli üretilemedi: %s", e)

    # 6. Caption oluştur
    metin = caption.ekonomi_caption(
        piyasa_verileri=piyasa_verileri,
        haberler=secilen_haberler,
        sonuclar=slayt_sonuclari,
        ayarlar=ayarlar,
    )

    # 7. Telegram'a gönder (Albüm + Onay Mesajı)
    etiketler = ["Piyasa"] + [f"Haber {i}" for i in range(1, len(slayt_urlleri))]
    albom_idler = telegram_bot.slaytlari_gonder(slayt_urlleri, etiketler)

    ozet = (
        f"📊 <b>GÜNE BAŞLARKEN EKONOMİ & PİYASALAR</b>\n"
        f"1 Piyasa Kartı + {len(secilen_haberler)} Ekonomi Haberi ({len(slayt_urlleri)} slayt)\n"
        f"⌛️ 24 saat boyunca onaya hazır bekler"
    )

    mesaj_id = telegram_bot.onay_iste(
        metin,
        len(slayt_urlleri),
        ozet=ozet,
    )

    # Albüm ID'lerini ve Piyasa Kartı URL'sini ayarlar tablosuna kaydet
    if mesaj_id:
        con.execute(
            "INSERT OR REPLACE INTO ayarlar (anahtar, deger) VALUES (?, ?)",
            (f"piyasa_karti_{mesaj_id}", kart_url),
        )
        if albom_idler:
            con.execute(
                "INSERT OR REPLACE INTO ayarlar (anahtar, deger) VALUES (?, ?)",
                (f"albom_{mesaj_id}", json.dumps(albom_idler)),
            )

    # 8. Veritabanında haberleri 'onay_bekliyor' durumuna getir
    for idx, h in enumerate(secilen_haberler, start=2):
        s_url = story_url if idx == 2 else None
        con.execute(
            "UPDATE haberler SET durum = 'onay_bekliyor', tur = 'ekonomi', "
            "telegram_message_id = ?, slayt_sirasi = ?, ig_caption = ?, "
            "story_url = ?, gonderim_zamani = datetime('now') WHERE id = ?",
            (mesaj_id, idx, metin, s_url, h["id"]),
        )
    con.commit()

    db_senkron.hemen_kaydet(f"Ekonomi turu onaya sunuldu: {mesaj_id}")
    log.info("Ekonomi turu Telegram'a onaya sunuldu (mesaj_id=%s)", mesaj_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
