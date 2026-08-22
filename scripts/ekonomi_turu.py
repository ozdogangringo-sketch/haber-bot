"""
ekonomi_turu.py — Hafta içi sabah borsa açılışıyla (TR 10:05) Ekonomi Turu hazırlar.

Yapı:
  * 1. Slayt: Canlı BIST 100, Dolar, Euro, Gram Altın, Bitcoin, Brent Petrol İnfografiği
  * 2..N. Slaytlar: Günün taze ekonomi haberleri (1 ila 5 haber)
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

from src import caption, db, db_senkron, piyasa, piyasa_kart, slaytlar, telegram_bot, upload_image, yonetim  # noqa: E402

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

    # 3. 1. Slayt (İnfografik Kartı) üret ve ImgBB'ye yükle
    kart_yolu = piyasa_kart.piyasa_karti_uret(piyasa_verileri)
    kart_yukleme = upload_image.gorsel_yukle(kart_yolu, ayarlar)
    kart_url = kart_yukleme["url"]

    # 4. Taze ekonomi haberlerini seç (1 ila 5 haber)
    sinir = datetime.now(timezone.utc) - timedelta(
        hours=ayarlar.get("genel", {}).get("yayin_yasi_siniri_saat", 36)
    )

    sorgu = """
    SELECT * FROM haberler
    WHERE (kategori = 'ekonomi' OR kaynak LIKE '%Ekonomi%' OR kaynak LIKE '%Bloomberg%' OR kaynak LIKE '%Dünya%')
      AND durum = 'metin_hazir'
      AND ig_baslik IS NOT NULL
      AND COALESCE(daha_once_yayinlandi, 0) = 0
      AND (telegram_message_id IS NULL OR telegram_message_id = 0)
      AND yayin_tarihi >= ?
    ORDER BY onem_puani DESC, yayin_tarihi DESC
    LIMIT 5
    """
    secilen_haberler = list(con.execute(sorgu, (sinir.isoformat(),)))

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
        con.execute(
            "UPDATE haberler SET durum = 'onay_bekliyor', tur = 'ekonomi', "
            "telegram_message_id = ?, slayt_sirasi = ?, ig_caption = ?, "
            "gonderim_zamani = datetime('now') WHERE id = ?",
            (mesaj_id, idx, metin, h["id"]),
        )
    con.commit()

    db_senkron.hemen_kaydet(f"Ekonomi turu onaya sunuldu: {mesaj_id}")
    log.info("Ekonomi turu Telegram'a onaya sunuldu (mesaj_id=%s)", mesaj_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
