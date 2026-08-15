"""
onay_isle.py — Telegram'dan gelen buton komutunu uygular.

Cloudflare Worker `repository_dispatch` ile bu scripti tetikliyor.
Komut ortam değişkeninden geliyor:

    KOMUT      = "yayinla" | "iptal" | "metin_yenile" | "ertele"
                 | "slayt_ai:3" | "slayt_foto:3" | "slayt_metin:3"
                 | "slayt_kaynak:3" | "slayt_sil:3"
    MESAJ_ID   = onay mesajının Telegram id'si
    BASAN      = butona basan kişi (bilgi amaçlı, yetki kontrolü YOK)

YETKİ:
    Gruptaki herkes basabilir — kullanıcının açık tercihi. `BASAN`
    yalnızca sonuç mesajında "kim onayladı" yazmak için kullanılıyor.

TEKRAR BASMA KORUMASI:
    Yayınlanmış bir turu ikinci kez yayınlamak çift post demek. Butonlar
    yayından sonra kaldırılıyor ama Telegram'da eski mesaj önbellekten
    basılabiliyor; o yüzden durum da denetleniyor.
"""

import logging
import os
import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import yaml                                       # noqa: E402

from src import (                                  # noqa: E402
    caption, db, instagram, slaytlar, telegram_bot, upload_image,
)
from src.generate_text import metinleri_uret       # noqa: E402

log = logging.getLogger("onay")


def turu_getir(con, mesaj_id: int) -> list:
    """Bu onay mesajına bağlı haberleri slayt sırasıyla getirir."""
    return list(con.execute(
        "SELECT * FROM haberler WHERE telegram_message_id = ? "
        "ORDER BY onem_puani DESC, yayin_tarihi DESC",
        (mesaj_id,),
    ))


def _sonuclari_kur(haberler: list) -> list[dict]:
    """Caption'ın atıf bloğu için katman bilgisini toparlar."""
    return [
        {"id": h["id"], "katman": h["gorsel_kaynagi"], "atif": h["gorsel_atif"] or ""}
        for h in haberler
    ]


def yayinla(con, ayarlar, haberler, mesaj_id, basan) -> int:
    if any(h["durum"] == "yayinlandi" for h in haberler):
        telegram_bot.mesaj_gonder("⚠️ Bu tur zaten yayınlanmış, tekrar gönderilmedi.")
        return 0

    urller = [h["gorsel_url"] for h in haberler if h["gorsel_url"]]
    if len(urller) < 2:
        raise RuntimeError(f"yayın için en az 2 görsel gerekli, {len(urller)} var")

    metin = caption.caption_kur(haberler, _sonuclari_kur(haberler), ayarlar=ayarlar)
    post_id = instagram.carousel_yayinla(urller, metin, ayarlar)
    baglanti = instagram.post_baglantisi(post_id, ayarlar)

    con.execute(
        "UPDATE haberler SET durum = 'yayinlandi', ig_post_id = ? "
        "WHERE telegram_message_id = ?",
        (post_id, mesaj_id),
    )
    con.commit()

    telegram_bot.sonucu_yaz(
        mesaj_id,
        f"✅ YAYINLANDI — {len(urller)} slayt\n"
        f"Onaylayan: {basan or 'bilinmiyor'}\n"
        f"{baglanti or post_id}",
    )
    return 0


def iptal(con, haberler, mesaj_id, basan) -> int:
    # Haberler ELENMİYOR: havuza dönüp sonraki turda yeniden yarışıyorlar.
    con.execute(
        "UPDATE haberler SET durum = 'yeni', telegram_message_id = NULL "
        "WHERE telegram_message_id = ?",
        (mesaj_id,),
    )
    con.commit()
    telegram_bot.sonucu_yaz(
        mesaj_id,
        f"❌ Bu tur atlandı ({basan or 'bilinmiyor'}).\n"
        f"{len(haberler)} haber havuza döndü, sonraki turda yeniden yarışacak.",
    )
    return 0


def ertele(con, mesaj_id, basan) -> int:
    con.execute(
        "UPDATE haberler SET durum = 'ertelendi', "
        "ertelenme_sayisi = COALESCE(ertelenme_sayisi, 0) + 1 "
        "WHERE telegram_message_id = ?",
        (mesaj_id,),
    )
    con.commit()
    telegram_bot.sonucu_yaz(
        mesaj_id,
        f"⏰ 1 saat ertelendi ({basan or 'bilinmiyor'}).\n"
        "Bir sonraki hatırlatma turunda yeniden sorulacak.",
    )
    return 0


def metin_yenile(con, ayarlar, haberler, mesaj_id) -> int:
    """Tüm haberlerin metnini yeniden ürettirir ve slaytları yeniler."""
    con.execute(
        "UPDATE haberler SET durum = 'yeni' WHERE telegram_message_id = ?",
        (mesaj_id,),
    )
    con.commit()
    metinleri_uret(con, haberler, ayarlar)

    taze = turu_getir(con, mesaj_id)
    sonuclar = slaytlar.tur_uret(taze, ayarlar, con)
    yuklemeler = upload_image.hepsini_yukle([s["yol"] for s in sonuclar], ayarlar)
    for haber, yukleme in zip(taze, yuklemeler):
        con.execute("UPDATE haberler SET gorsel_url = ?, durum = 'onay_bekliyor' "
                    "WHERE id = ?", (yukleme["url"], haber["id"]))
    con.commit()

    telegram_bot.slaytlari_gonder([y["url"] for y in yuklemeler])
    metin = caption.caption_kur(taze, sonuclar, ayarlar=ayarlar)
    yeni_id = telegram_bot.onay_iste(metin, len(yuklemeler),
                                     uyari="🔄 Metinler yeniden üretildi")
    con.execute("UPDATE haberler SET telegram_message_id = ? "
                "WHERE telegram_message_id = ?", (yeni_id, mesaj_id))
    con.commit()
    telegram_bot.sonucu_yaz(mesaj_id, "🔄 Metinler yeniden üretildi — yeni öneri yukarıda.")
    return 0


def slayt_islemi(con, ayarlar, haberler, komut, sira, mesaj_id) -> int:
    """Tek bir slayta müdahale eder."""
    if not 1 <= sira <= len(haberler):
        telegram_bot.mesaj_gonder(f"⚠️ {sira}. slayt yok (turda {len(haberler)} slayt var).")
        return 0
    haber = haberler[sira - 1]

    if komut == "slayt_kaynak":
        # Uydurma denetimi: modelin yazdığı cümle kaynakta var mı?
        ham = (haber["makale_metni"] or "").strip() or "(kaynak metni saklanmamış)"
        telegram_bot.mesaj_gonder(
            f"📄 {sira}. slaytın kaynak metni\n\n"
            f"ÜRETİLEN BAŞLIK:\n{haber['ig_baslik']}\n\n"
            f"ÜRETİLEN ÖZET:\n{haber['slayt_ozet']}\n\n"
            f"— KAYNAK —\n{ham[:2500]}"
        )
        return 0

    if komut == "slayt_sil":
        kalan = len(haberler) - 1
        if kalan < 2:
            telegram_bot.mesaj_gonder(
                "⚠️ Çıkarılamaz: Instagram carousel en az 2 slayt istiyor."
            )
            return 0
        con.execute("UPDATE haberler SET durum = 'yeni', telegram_message_id = NULL "
                    "WHERE id = ?", (haber["id"],))
        con.commit()
        telegram_bot.mesaj_gonder(
            f"🗑 {sira}. slayt çıkarıldı ({kalan} slayt kaldı).\n"
            f"Haber elenmedi, havuza döndü."
        )
        return 0

    if komut == "slayt_metin":
        con.execute("UPDATE haberler SET durum = 'yeni' WHERE id = ?", (haber["id"],))
        con.commit()
        metinleri_uret(con, [haber], ayarlar)
        con.execute("UPDATE haberler SET durum = 'onay_bekliyor' WHERE id = ?",
                    (haber["id"],))
        con.commit()

    # slayt_ai / slayt_foto / metin sonrası: slaytı yeniden üret
    taze = con.execute("SELECT * FROM haberler WHERE id = ?", (haber["id"],)).fetchone()
    if komut == "slayt_ai":
        ayarlar = {**ayarlar, "gorsel": {**ayarlar["gorsel"], "haberde_ai": True}}
    yol, katman, atif = slaytlar.slayt_uret(taze, ayarlar, con=con)

    yukleme = upload_image.gorsel_yukle(yol, ayarlar)
    con.execute("UPDATE haberler SET gorsel_url = ?, gorsel_kaynagi = ? WHERE id = ?",
                (yukleme["url"], katman, haber["id"]))
    con.commit()

    telegram_bot.mesaj_gonder(
        f"🖼 {sira}. slayt yenilendi (katman: {katman}).\n{yukleme['url']}"
    )
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")

    komut = os.getenv("KOMUT", "").strip()
    mesaj_id = int(os.getenv("MESAJ_ID", "0") or 0)
    basan = os.getenv("BASAN", "").strip()

    if not komut or not mesaj_id:
        log.error("KOMUT veya MESAJ_ID eksik")
        return 1

    ayarlar = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    db.kur()
    con = db.baglan()

    haberler = turu_getir(con, mesaj_id)
    if not haberler:
        log.error("mesaj_id=%s için haber bulunamadı", mesaj_id)
        telegram_bot.mesaj_gonder("⚠️ Bu onay mesajına bağlı haber bulunamadı.")
        return 1

    try:
        if komut == "yayinla":
            return yayinla(con, ayarlar, haberler, mesaj_id, basan)
        if komut == "iptal":
            return iptal(con, haberler, mesaj_id, basan)
        if komut == "ertele":
            return ertele(con, mesaj_id, basan)
        if komut == "metin_yenile":
            return metin_yenile(con, ayarlar, haberler, mesaj_id)
        if ":" in komut:
            ad, sira = komut.split(":", 1)
            return slayt_islemi(con, ayarlar, haberler, ad, int(sira), mesaj_id)

        log.error("bilinmeyen komut: %s", komut)
        return 1

    except Exception as e:
        log.exception("komut işlenemedi")
        telegram_bot.hata_bildir(f"Komut işlenemedi: {komut}",
                                 f"{type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
