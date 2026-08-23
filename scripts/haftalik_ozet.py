"""
haftalik_ozet.py — Haftalık Pazar Bülteni & Özeti

Son 7 günün en önemli 6-8 haberini derler, özel 'HAFTANIN ÖZETİ' dergi kapağı ve
slaytlarını üretip Telegram'a onaya sunar.
"""

import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

from src import (  # noqa: E402
    caption, db, db_senkron, generate_text, make_image,
    slaytlar, telegram_bot, upload_image, yonetim,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("haftalik_ozet")


def haftalik_haberleri_sec(con, ayarlar: dict, adet: int = 7) -> list[dict]:
    """Son 7 günün en yüksek puanlı ve çeşitli kategorilerdeki haberlerini seçer."""
    yedi_gun_once = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    
    # 1. Öncelik: Son 7 günde yayınlanmış veya havuzda yüksek puan almış haberler
    satirlar = con.execute(
        "SELECT * FROM haberler WHERE yayin_tarihi >= ? "
        "AND (durum = 'yayinlandi' OR durum = 'metin_hazir' OR onem_puani >= 7) "
        "AND ig_baslik IS NOT NULL "
        "ORDER BY onem_puani DESC, yayin_tarihi DESC",
        (yedi_gun_once,),
    ).fetchall()

    if not satirlar:
        # Fallback: Havuzdaki en yüksek puanlı haberler
        satirlar = con.execute(
            "SELECT * FROM haberler WHERE ig_baslik IS NOT NULL "
            "ORDER BY onem_puani DESC LIMIT 15"
        ).fetchall()

    # Kategori çeşitliliği sağla (aynı kategoriden max 2 haber)
    kategori_sayaci: dict[str, int] = {}
    secilen = []
    
    for h in satirlar:
        kat = h["kategori"] or "genel"
        if kategori_sayaci.get(kat, 0) < 2:
            secilen.append(dict(h))
            kategori_sayaci[kat] = kategori_sayaci.get(kat, 0) + 1
        if len(secilen) >= adet:
            break

    return secilen


def main() -> int:
    ayarlar_yolu = KOK / "config.yaml"
    with open(ayarlar_yolu, encoding="utf-8") as f:
        ayarlar = yaml.safe_load(f)

    con = db.baglan()

    # Bot duraklatıldı mı kontrolü
    duraklatildi, kalan = yonetim.duraklatildi_mi(con)
    if duraklatildi:
        log.info("Bot duraklatılmış durumda (kalan: %s), haftalık özet atlandı.", kalan)
        con.close()
        return 0

    log.info("Haftalık bülten hazırlanıyor...")
    secilen_haberler = haftalik_haberleri_sec(con, ayarlar, adet=7)
    
    if len(secilen_haberler) < 3:
        log.warning("Haftalık bülten için yeterli haber bulunamadı (%s adet).", len(secilen_haberler))
        telegram_bot.mesaj_gonder("⚠️ Haftalık bülten için havuzda yeterli haber bulunamadı.")
        con.close()
        return 0

    # Eksik metin varsa üret
    eksik_metinliler = [h for h in secilen_haberler if not h["ig_baslik"]]
    if eksik_metinliler:
        try:
            generate_text.metinleri_uret(ayarlar=ayarlar, haberler=eksik_metinliler)
        except Exception as e:
            log.warning("Metin üretim hatası: %s", e)

    bugun = date.today()
    baslangic = bugun - timedelta(days=6)
    basliklar = [h["ig_baslik"] or h["baslik_orj"] for h in secilen_haberler]

    # 1. Özel Haftanın Özeti Kapak Slaytı Üret
    make_image.CIKTI_KLASORU.mkdir(parents=True, exist_ok=True)
    kapak_gorsel = make_image.haftalik_kapak_ciz(basliklar, ayarlar, baslangic, bugun)
    kapak_yolu = make_image.CIKTI_KLASORU / f"haftalik_kapak_{bugun.strftime('%Y%m%d')}.jpg"
    kapak_gorsel.save(kapak_yolu, "JPEG", quality=95, optimize=True)

    kapak_url = upload_image.gorsel_yukle(kapak_yolu, ayarlar)["url"]
    slayt_urlleri = [kapak_url]
    slayt_sonuclari = [{"katman": "ozel_kapak", "atif": "Daily Briefing", "yol": str(kapak_yolu)}]

    # 2. Seçilen haberlerin slaytlarını üret ve yükle
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

    # 3. Story kapak görseli üret
    story_url = None
    try:
        story_gorsel = make_image.story_kapak(basliklar, ayarlar)
        story_yol = make_image.CIKTI_KLASORU / "story-kapak-haftalik.jpg"
        story_gorsel.save(story_yol, "JPEG", quality=92, optimize=True)
        story_url = upload_image.gorsel_yukle(story_yol, ayarlar)["url"]
    except Exception as e:
        log.warning("Story görseli üretilemedi: %s", e)

    # 4. Caption oluştur
    metin = (
        f"🗓️ HAFTANIN ÖZETİ ({baslangic.day} – {bugun.day} {make_image.AYLAR[bugun.month - 1]} {bugun.year})\n\n"
        "Bu hafta Türkiye ve dünya gündeminde öne çıkan kritik gelişmeler:\n\n"
    )
    for i, h in enumerate(secilen_haberler, start=1):
        baslik = h["ig_baslik"] or h["baslik_orj"]
        metin += f"▪️ {baslik}\n"

    metin += (
        "\n📌 Tüm detaylar ve analizler için kaydırın.\n\n"
        "#haftalıközet #gündem #haberler #dailybrief #türkiye #dünya #ekonomi #teknoloji"
    )

    # 5. Telegram'a Albüm + Onay Mesajı Gönder
    etiketler = ["Kapak"] + [f"Haber {i}" for i in range(1, len(slayt_urlleri))]
    albom_idler = telegram_bot.slaytlari_gonder(slayt_urlleri, etiketler)

    ozet = (
        f"🗓️ <b>HAFTANIN ÖZETİ (PAZAR BÜLTENİ)</b>\n"
        f"1 Özel Kapak + {len(secilen_haberler)} Haber Slaytı ({len(slayt_urlleri)} slayt)\n"
        f"⌛️ 24 saat boyunca onaya hazır bekler"
    )

    mesaj_id = telegram_bot.onay_iste(
        metin,
        len(slayt_urlleri),
        ozet=ozet,
    )

    if mesaj_id:
        if albom_idler:
            con.execute(
                "INSERT OR REPLACE INTO ayarlar (anahtar, deger) VALUES (?, ?)",
                (f"albom_{mesaj_id}", json.dumps(albom_idler)),
            )

    # 6. Veritabanını güncelle
    for idx, h in enumerate(secilen_haberler, start=2):
        s_url = story_url if idx == 2 else None
        con.execute(
            "UPDATE haberler SET durum = 'onay_bekliyor', tur = 'haftalik', "
            "telegram_message_id = ?, slayt_sirasi = ?, ig_caption = ?, "
            "story_url = ?, gonderim_zamani = datetime('now') WHERE id = ?",
            (mesaj_id, idx, metin, s_url, h["id"]),
        )
    con.commit()

    db_senkron.hemen_kaydet(f"Haftalık bülten onaya sunuldu: {mesaj_id}")
    log.info("Haftalık özet başarıyla onaya sunuldu (mesaj_id=%s)", mesaj_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
