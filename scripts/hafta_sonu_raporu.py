"""
hafta_sonu_raporu.py — Cuma akşamı veya hafta sonu borsa kapanış bilançosu ve haftalık özet bülteni.

1. Slayt: BİST 100 En Çok Kazandıranlar / Kaybettirenler ve Makro Getiri İnfografiği
2..N. Slaytlar: Son 7 günün en önemli 3-4 manşet slaytı
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

from src import (  # noqa: E402
    caption, db, db_senkron, haftalik_bulten, make_image,
    slaytlar, telegram_bot, upload_image, yonetim,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("hafta_sonu_raporu")


def main() -> int:
    ayarlar_yolu = KOK / "config.yaml"
    with open(ayarlar_yolu, encoding="utf-8") as f:
        ayarlar = yaml.safe_load(f)

    con = db.baglan()

    # 1. Bot duraklatılmış mı?
    duraklatildi, kalan = yonetim.duraklatildi_mi(con)
    if duraklatildi:
        log.info("Bot duraklatılmış (kalan: %s), hafta sonu bülteni atlanıyor.", kalan)
        con.close()
        return 0

    log.info("--- HAFTA SONU BİLANÇO BÜLTENİ HAZIRLANIYOR ---")

    # 2. Haftalık Piyasa Verileri ve İnfografik Kartı
    piyasa_verileri = haftalik_bulten.haftalik_piyasa_verileri_getir()
    kart_yolu = haftalik_bulten.haftalik_kart_uret(ayarlar, piyasa_verileri)
    kart_yukleme = upload_image.gorsel_yukle(kart_yolu, ayarlar)
    kart_url = kart_yukleme["url"]

    # 3. Haftanın En Önemli Haberleri
    onemli_haberler = list(haftalik_bulten.haftanin_onemli_haberleri(con, limit=3))
    slayt_sonuclari = []
    toplam_slayt = 1 + len(onemli_haberler)

    for idx, haber in enumerate(onemli_haberler, start=2):
        try:
            is_son = (idx == toplam_slayt)
            yol, katman, atif = slaytlar.slayt_uret(dict(haber), ayarlar, sira=idx, son_slayt=is_son)
            yukleme = upload_image.gorsel_yukle(yol, ayarlar)
            slayt_sonuclari.append({
                "id": haber["id"],
                "yol": yol,
                "url": yukleme["url"],
                "katman": katman,
                "atif": atif,
            })
        except Exception as e:
            log.warning("Haftalık haber slaytı üretilemedi #%s: %s", haber["id"], e)

    # 4. Caption Metni Hazırla
    kazanan_metin = ", ".join([f"{k['sembol']} (+%{k['degisim']:.1f})" for k in piyasa_verileri.get("kazananlar", [])])
    kaybeden_metin = ", ".join([f"{k['sembol']} (-%{abs(k['degisim']):.1f})" for k in piyasa_verileri.get("kaybedenler", [])])

    ig_caption = (
        "📊 HAFTALIK BİLANÇO: Borsa ve piyasalarda bu hafta kim kazandı, kim kaybetti?\n\n"
        f"🟢 Haftanın En Çok Yükselenleri: {kazanan_metin or 'Veri alınıyor'}\n"
        f"🔴 Haftanın En Çok Düşenleri: {kaybeden_metin or 'Veri alınıyor'}\n\n"
        "Haftanın en kritik 3 gelişmesi ve detaylar kaydırmalı slaytlarda. 👆\n\n"
        "#borsa #bist100 #hisse #altın #dolar #ekonomi #haftalıközet #dailybrief"
    )

    tum_slayt_urlleri = [kart_url] + [s["url"] for s in slayt_sonuclari]
    tum_slayt_yollari = [kart_yolu] + [s["yol"] for s in slayt_sonuclari]

    # 5. Telegram Onay Kartı Gönder
    log.info("Hafta sonu onay kartı Telegram'a iletiliyor (%d görsel)...", len(tum_slayt_urlleri))
    
    # Sanal tur ID'si ve kaydı
    tur_bilgi = {
        "tur": "hafta_sonu",
        "tarih": datetime.now(timezone.utc).isoformat(),
        "kart_url": kart_url,
        "slayt_urlleri": tum_slayt_urlleri,
        "slayt_yollari": [str(p) for p in tum_slayt_yollari],
        "caption": ig_caption,
    }

    try:
        # Telegram'a albüm ve onay butonlarını gönder
        mesaj_id = telegram_bot.haftalik_bulten_onay_iste(
            tur_bilgi,
            piyasa_verileri,
            onemli_haberler,
            ayarlar,
        )
        log.info("Telegram onay mesajı gönderildi: mesaj_id=%s", mesaj_id)
    except Exception as e:
        log.error("Telegram mesajı gönderilemedi: %s", e)

    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
