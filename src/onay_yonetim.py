"""
onay_yonetim.py — Telegram onay/yönetim paneli, durum sorgulama, iptal ve tur yaşam döngüsü işlemleri.

`scripts/onay_isle.py` monolitini sadeleştirmek için yönetim, durum,
havuz güncelleme, inceleme ve yayından kaldırma fonksiyonları bu modüle ayrılmıştır.
"""

import html
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src import (
    ayar,
    db_senkron,
    facebook,
    fetch_news,
    instagram,
    secim,
    telegram_bot,
    threads,
    tur_icerigi,
    yonetim,
)

KOK = Path(__file__).resolve().parent.parent
log = logging.getLogger("onay")


def turu_getir(con, mesaj_id: int) -> list:
    """
    Bu onay mesajına bağlı haberleri slayt sırasıyla getirir.

    ⚠️ SIRALAMA: `slayt_sirasi` belirlenmişse (kullanıcı taşıdıysa) o sıra
    kullanılır; yoksa varsayılan puan ve tarih sırası geçerlidir.
    """
    satirlar = tur_icerigi.haberleri_getir(con, mesaj_id)
    if not satirlar and con is not None:
        try:
            bagli = con.execute(
                "SELECT deger FROM ayarlar WHERE anahtar = ?",
                (f"bagli_mesaj_{mesaj_id}",)
            ).fetchone()
            if bagli and bagli["deger"] and str(bagli["deger"]).isdigit():
                ana_mid = int(bagli["deger"])
                if ana_mid != mesaj_id:
                    return turu_getir(con, ana_mid)
        except Exception:
            pass
    return satirlar


def ayar_paneli(con, ayarlar) -> int:
    """`/ayar` — çalışma ayarlarını gösterir, düğmelerle değiştirilir."""
    telegram_bot.mesaj_gonder(
        ayar.panel_metni(con, ayarlar),
        butonlar=ayar.panel_butonlari(con, ayarlar),
    )
    return 0


def ayar_degistir(con, ayarlar, komut: str, mesaj_id: int, basan) -> int:
    """
    Alt menüden seçilen değeri yazar ve ANA PANELE döner.
    """
    try:
        yol, kod = komut.split(":", 1)
        yeni = ayar.deger_ata(con, ayarlar, yol, kod)
    except (ValueError, KeyError):
        telegram_bot.mesaj_gonder("⚠️ Tanınmayan ayar ya da değer.")
        return 1

    ayar.uygula(con, ayarlar)
    etiket = ayar.DEGISTIRILEBILIR[yol][0]
    gosterim = "AÇIK" if yeni is True else "KAPALI" if yeni is False else yeni
    try:
        if mesaj_id:
            telegram_bot.paneli_tazele(
                mesaj_id,
                ayar.panel_metni(con, ayarlar)
                + f"\n\nSon değişiklik: {etiket} → {gosterim}"
                f"  ({basan or 'bilinmiyor'})",
                ayar.panel_butonlari(con, ayarlar),
            )
        else:
            telegram_bot.mesaj_gonder(
                f"⚙️ Ayar değişti: {etiket} → {gosterim}  ({basan or 'bilinmiyor'})")
    except Exception as e:
        log.warning("panel tazelenemedi: %s", e)

    db_senkron.hemen_kaydet(f"Ayar: {yol} = {yeni}")
    return 0


def yonetim_paneli_goster(con, ayarlar: dict, mesaj_id: int | None = None) -> int:
    """`/yonetim` — Yönetim ve acil durum kontrol panelini gönderir veya günceller."""
    duraklatildi, kalan = yonetim.duraklatildi_mi(con)
    durum_str = f"⏸️ DURAKLATILDI (Kalan: {kalan})" if duraklatildi else "🟢 AKTİF (Cronlar çalışıyor)"

    metin = (
        "🎛️ <b>BOT YÖNETİM & ACİL DURUM PANELİ</b>\n\n"
        f"<b>Durum:</b> {durum_str}\n\n"
        "Aşağıdaki butonlarla botu geçici süreyle susturabilir, "
        "API bağlantılarını test edebilir, kotayı sorgulayabilir veya "
        "askıda kalan turları temizleyebilirsin."
    )
    klavye = telegram_bot.yonetim_menusu(duraklatildi, kalan)
    if mesaj_id:
        telegram_bot.mesaji_guncelle(mesaj_id, metin, klavye)
    else:
        telegram_bot.mesaj_gonder(metin, html=True, butonlar=klavye["inline_keyboard"])
    return 0


def yonetim_duraklat_uygula(con, ayarlar: dict, saat: int, mesaj_id: int | None, basan: str) -> int:
    """Botu belirtilen süre kadar duraklatır."""
    bitis = yonetim.duraklat(con, saat, basan)
    db_senkron.hemen_kaydet(f"Bot {saat}s duraklatıldı")
    tr_bitis = bitis.astimezone(timezone(timedelta(hours=3)))

    metin = (
        f"⏸️ <b>BOT {saat} SAAT DURAKLATILDI</b>\n\n"
        f"• <b>Bitiş:</b> TR {tr_bitis:%H:%M} ({basan or 'Bilinmiyor'})\n"
        f"• <b>Kapsam:</b> Akşam turu hazırlama, son dakika arama ve hatırlatma cron'ları bu süre boyunca çalışmayacaktır.\n"
        f"• İstediğin zaman aşağıdaki butonla duraklatmayı kaldırabilirsin."
    )
    klavye = telegram_bot.yonetim_menusu(True, f"{saat} saat")
    if mesaj_id:
        telegram_bot.mesaji_guncelle(mesaj_id, metin, klavye)
    else:
        telegram_bot.mesaj_gonder(metin, html=True, butonlar=klavye["inline_keyboard"])
    return 0


def yonetim_devam_et_uygula(con, ayarlar: dict, mesaj_id: int | None, basan: str) -> int:
    """Bot duraklatmasını kaldırır."""
    yonetim.devam_et(con, basan)
    db_senkron.hemen_kaydet("Bot duraklatması kaldırıldı")

    metin = (
        f"🟢 <b>BOT DURAKLATMASI KALDIRILDI</b>\n\n"
        f"• Tüm periyodik cron akışları normale döndü ({basan or 'Bilinmiyor'})."
    )
    klavye = telegram_bot.yonetim_menusu(False, "")
    if mesaj_id:
        telegram_bot.mesaji_guncelle(mesaj_id, metin, klavye)
    else:
        telegram_bot.mesaj_gonder(metin, html=True, butonlar=klavye["inline_keyboard"])
    return 0


def yonetim_saglik_testi_uygula(ayarlar: dict, mesaj_id: int | None) -> int:
    """API bağlantı sağlık testini çalıştırıp raporlar."""
    sonuclar = yonetim.api_saglik_testi(ayarlar)
    satirlar = ["🧪 <b>API BAĞLANTI SAĞLIK TESTİ</b>\n"]
    for s in sonuclar:
        simge = "✅" if s["durum"] else "❌"
        satirlar.append(f"{simge} <b>{s['ad']}:</b> {s['mesaj']}")

    metin = "\n".join(satirlar)
    klavye = {"inline_keyboard": [[{"text": "← Yönetim Paneline Dön", "callback_data": "yonetim_panel"}]]}
    if mesaj_id:
        telegram_bot.mesaji_guncelle(mesaj_id, metin, klavye)
    else:
        telegram_bot.mesaj_gonder(metin, html=True, butonlar=klavye["inline_keyboard"])
    return 0


def yonetim_kota_raporu_uygula(con, ayarlar: dict, mesaj_id: int | None, kategori: int | str = "menu") -> int:
    """Canlı kota ve durum raporunu Telegram'a gönderir."""
    from src import kota_uretici
    kota_uretici.kota_gonder(mesaj_id, kategori=kategori)
    return 0


def yonetim_tur_temizle_uygula(con, ayarlar: dict, mesaj_id: int | None) -> int:
    """Askıda kalan onay bekleyen turları sıfırlar."""
    adet = yonetim.askidaki_turlari_temizle(con)
    db_senkron.hemen_kaydet(f"{adet} askıda haber temizlendi")

    metin = (
        f"🧹 <b>ASKIDAKİ TURLAR TEMİZLENDİ</b>\n\n"
        f"• Yanıtsız kalan <b>{adet}</b> haber onay kuyruğundan çıkarılıp havuza iade edildi.\n"
        f"• Yayınlanmış olan haberlere dokunulmadı."
    )
    klavye = {"inline_keyboard": [[{"text": "← Yönetim Paneline Dön", "callback_data": "yonetim_panel"}]]}
    if mesaj_id:
        telegram_bot.mesaji_guncelle(mesaj_id, metin, klavye)
    else:
        telegram_bot.mesaj_gonder(metin, html=True, butonlar=klavye["inline_keyboard"])
    return 0


def yayindan_kaldir(con, ayarlar, haberler, mesaj_id, basan) -> int:
    """
    Yayınlanmış bir turu geri alır.
    Facebook, Threads, YouTube, X ve Instagram Story API'den silinir;
    Instagram Feed için bağlantı gösterilir.
    """
    if not any(h["durum"] == "yayinlandi" for h in haberler):
        telegram_bot.mesaj_gonder("⚠️ Bu tur yayınlanmamış, kaldırılacak bir şey yok.")
        return 0

    ilk = haberler[0]
    satirlar = []

    fb = ilk["facebook_post_id"]
    if fb:
        if facebook.postu_sil(fb, ayarlar):
            satirlar.append("📘 Facebook postu silindi")
        else:
            satirlar.append("⚠️ Facebook postu silinemedi")
    else:
        satirlar.append("· Facebook: kayıtlı post id yok")

    fb_reel = ilk["facebook_reel_id"] if "facebook_reel_id" in ilk.keys() else None
    if fb_reel:
        if facebook.postu_sil(fb_reel, ayarlar):
            satirlar.append("📘 Facebook Reel silindi")
        else:
            satirlar.append("⚠️ Facebook Reel silinemedi")

    th = ilk["threads_post_id"]
    if th:
        try:
            silinen, toplam = threads.zinciri_sil(th)
            satirlar.append(f"🧵 Threads zinciri silindi ({silinen}/{toplam} gönderi)")
        except Exception as e:
            satirlar.append(f"⚠️ Threads silinemedi: {type(e).__name__}")
    else:
        satirlar.append("· Threads: kayıtlı gönderi id yok")

    yt = ilk.get("youtube_post_id") if hasattr(ilk, "keys") and "youtube_post_id" in ilk.keys() else None
    if yt:
        try:
            from src import youtube
            if youtube.video_sil(yt):
                satirlar.append("▶️ YouTube Shorts silindi")
            else:
                satirlar.append("⚠️ YouTube Shorts silinemedi")
        except Exception as e:
            satirlar.append(f"⚠️ YouTube silinemedi: {type(e).__name__}")

    tw = ilk.get("twitter_post_id") if hasattr(ilk, "keys") and "twitter_post_id" in ilk.keys() else None
    if tw:
        try:
            from src import twitter
            if twitter.tweet_sil(tw):
                satirlar.append("🐦 Twitter tweeti silindi")
            else:
                satirlar.append("⚠️ Twitter tweeti silinemedi")
        except Exception as e:
            satirlar.append(f"⚠️ Twitter silinemedi: {type(e).__name__}")

    st_id = ilk.get("story_post_id") if hasattr(ilk, "keys") and "story_post_id" in ilk.keys() else None
    if st_id:
        try:
            if instagram.story_sil(st_id, ayarlar):
                satirlar.append("📷 Instagram Story silindi")
        except Exception as e:
            log.warning("Instagram story silinemedi: %s", e)

    ig = ilk["ig_post_id"]
    baglanti = instagram.post_baglantisi(ig, ayarlar) if ig else ""
    satirlar.append(
        "\n📷 Instagram Akış (Carousel) postunu ELLE silmen gerekiyor — Meta API "
        "yayınlanmış akış postunu silmeye izin vermiyor:\n" + (baglanti or f"post id: {ig}")
    )

    con.execute(
        "UPDATE haberler SET durum = 'kaldirildi' WHERE telegram_message_id = ?",
        (mesaj_id,),
    )
    con.commit()

    telegram_bot.mesaj_gonder(
        f"🗑 YAYINDAN KALDIRILDI ({len(haberler)} haber)\n"
        f"Kaldıran: {basan or 'bilinmiyor'}\n\n" + "\n".join(satirlar)
    )
    log.info("tur yayından kaldırıldı (mesaj_id=%s)", mesaj_id)
    return 0


def iptal(con, haberler, mesaj_id, basan) -> int:
    con.execute(
        "UPDATE haberler SET telegram_message_id = NULL, son_dakika = 0, "
        "ertelenme_sayisi = COALESCE(ertelenme_sayisi, 0) + 1, "
        "atlanma_zamani = datetime('now'), "
        "durum = CASE WHEN ig_baslik IS NOT NULL THEN 'metin_hazir' "
        "             ELSE 'yeni' END "
        "WHERE telegram_message_id = ?",
        (mesaj_id,),
    )

    ATLAMA_SINIRI = 2
    con.execute(
        "UPDATE haberler SET sadece_tur = 1 "
        "WHERE id IN ({}) AND COALESCE(ertelenme_sayisi, 0) >= ?".format(
            ",".join("?" * len(haberler))),
        [h["id"] for h in haberler] + [ATLAMA_SINIRI],
    )
    yeter = con.execute(
        "SELECT COUNT(*) FROM haberler WHERE id IN ({}) "
        "AND sadece_tur = 1".format(",".join("?" * len(haberler))),
        [h["id"] for h in haberler],
    ).fetchone()[0]
    con.commit()

    ek = ("\n\n📋 Bu haber ikinci kez atlandı; artık tekil post olarak "
          "sunulmayacak, yalnızca 10'lu turda yarışacak." if yeter else "")
    telegram_bot.sonucu_yaz(
        mesaj_id,
        f"❌ Bu tur atlandı ({basan or 'bilinmiyor'}).\n"
        f"{len(haberler)} haber havuza döndü, sonraki turda yeniden yarışacak."
        + ek,
    )
    return 0


def cope_at(con, haberler: list, mesaj_id: int, basan: str = "") -> int:
    """
    Turdaki/posttaki haberleri 'iptal' durumuna getirir.
    Haberler kesinlikle havuza DÖNMEZ, gelecekte hiçbir tura veya tekil posta aday olamaz.
    """
    con.execute(
        "UPDATE haberler SET durum = 'iptal', telegram_message_id = NULL, "
        "atlanma_zamani = datetime('now') WHERE telegram_message_id = ?",
        (mesaj_id,),
    )
    con.commit()
    telegram_bot.sonucu_yaz(
        mesaj_id,
        f"🗑️ <b>Gönderi tamamen çöpe atıldı</b> ({basan or 'kullanıcı'}).\n"
        f"Turdaki {len(haberler)} haber havuza dönmeyecek şekilde iptal edildi.",
    )
    return 0


def havuzu_guncelle(con, ayarlar) -> int:
    """RSS kaynaklarını hemen tarar — bir sonraki cron'u beklemeden."""
    telegram_bot.mesaj_gonder("🔄 Kaynaklar taranıyor…")
    try:
        rapor = fetch_news.haberleri_cek(ayarlar)
    except Exception as e:                            # noqa: BLE001
        log.exception("havuz güncellenemedi")
        telegram_bot.mesaj_gonder(
            f"⚠️ Havuz güncellenemedi: {type(e).__name__}: {str(e)[:120]}")
        return 1

    toplam = con.execute(
        "SELECT COUNT(*) FROM haberler "
        "WHERE cekilme_zamani > datetime('now', '-3 day')").fetchone()[0]
    hatali = rapor.get("hatali_kaynaklar") or []
    satirlar = [
        f"✅ <b>Havuz güncellendi</b>",
        f"   yeni haber : <b>{rapor.get('eklenen', 0)}</b>",
        f"   tekrar     : {rapor.get('tekrar', 0)}",
        f"   bayat      : {rapor.get('eski', 0)}",
        "",
        f"Havuzda son 3 günde <b>{toplam}</b> haber var.",
    ]
    if hatali:
        satirlar.append(f"\n⚠️ {len(hatali)} kaynak yanıt vermedi: "
                        + ", ".join(str(k)[:20] for k in hatali[:4]))
    if rapor.get("eklenen"):
        satirlar.append("\nAradığın haberi şimdi <code>/haber &lt;konu&gt;</code> "
                        "ile arayabilirsin.")
    telegram_bot.mesaj_gonder("\n".join(satirlar), html=True)
    db_senkron.hemen_kaydet("Havuz elle güncellendi")
    return 0


def yayin_durumu_kontrol(con, ayarlar, mesaj_id: int) -> int:
    """
    Bu turun her platformdaki (Instagram, Story, Facebook, Threads, X) yayın durumunu denetler.
    Eksik veya yayınlanmamış olan platformları tespit edip tek tıkla telafi butonları sunar.
    """
    haberler = turu_getir(con, mesaj_id)
    if not haberler:
        telegram_bot.mesaj_gonder(
            "⚠️ Bu mesaja bağlı tur bulunamadı — kapanmış olabilir.")
        return 0

    ilk = dict(haberler[0])
    db_durum = ilk.get("durum")
    post_id = next((h["ig_post_id"] for h in haberler if h["ig_post_id"]), None)
    story_id = next((h["story_post_id"] for h in haberler if h["story_post_id"]), None)
    fb_id = next((h["facebook_post_id"] for h in haberler if h["facebook_post_id"]), None)
    th_id = next((h["threads_post_id"] for h in haberler if h["threads_post_id"]), None)
    tw_id = next((h["twitter_post_id"] for h in haberler if "twitter_post_id" in h.keys() and h["twitter_post_id"]), None)
    yt_id = next((h["youtube_post_id"] for h in haberler if "youtube_post_id" in h.keys() and h["youtube_post_id"]), None)
    tt_id = next((h["tiktok_post_id"] for h in haberler if "tiktok_post_id" in h.keys() and h["tiktok_post_id"]), None)
    basliklar = [(h["ig_baslik"] or h["baslik_orj"] or "") for h in haberler]

    satirlar = [f"🔍 <b>TÜM PLATFORMLAR YAYIN DURUMU</b> (#{mesaj_id} - {len(haberler)} haber)", ""]
    satirlar.append(f"<b>Veritabanı Durumu:</b> <code>{html.escape(str(db_durum))}</code>")

    ig_var = False
    try:
        gecmis = instagram.son_yayinlanan_basliklar(ayarlar)
        bulunan = []
        for b in basliklar:
            kel, ozel = secim.konu_imzasi(b)
            for g in gecmis:
                gk, go = secim.konu_imzasi(g)
                if (len(secim.ortak_kelime(kel, gk)) >= 3
                        and secim.ortak_kelime(ozel, go)):
                    bulunan.append(b)
                    break
        if bulunan:
            ig_var = True
            satirlar.append(f"📸 <b>Instagram Post:</b> ✅ Yayında ({len(bulunan)}/{len(basliklar)} haber)")
        elif post_id:
            ig_var = True
            satirlar.append(f"📸 <b>Instagram Post:</b> ✅ Yayında (ID: {post_id})")
        else:
            satirlar.append("📸 <b>Instagram Post:</b> ❌ Yayında YOK")
    except Exception as e:
        satirlar.append(f"📸 <b>Instagram Post:</b> ⚠️ Kontrol edilemedi ({type(e).__name__})")

    if story_id:
        satirlar.append(f"📱 <b>Story:</b> ✅ Yayında (ID: {story_id})")
    else:
        satirlar.append("📱 <b>Story:</b> ⚠️ Yayınlanmadı / Bilgi Yok")

    if fb_id:
        satirlar.append(f"📘 <b>Facebook:</b> ✅ Yayında (ID: {fb_id})")
    else:
        satirlar.append("📘 <b>Facebook:</b> ⚠️ Yayınlanmadı / Kayıt Yok")

    if th_id:
        satirlar.append(f"🧵 <b>Threads:</b> ✅ Yayında (ID: {th_id})")
    else:
        satirlar.append("🧵 <b>Threads:</b> ⚠️ Yayınlanmadı / Kayıt Yok")

    if tw_id:
        satirlar.append(f"🐦 <b>X (Twitter):</b> ✅ Yayında (ID: {tw_id})")
    else:
        satirlar.append("🐦 <b>X (Twitter):</b> ⚠️ Yayınlanmadı / Kayıt Yok")

    if yt_id:
        satirlar.append(f"▶️ <b>YouTube Shorts:</b> ✅ Yayında ({yt_id})")
    else:
        satirlar.append("▶️ <b>YouTube Shorts:</b> ⚠️ Yayınlanmadı / Kayıt Yok")

    if tt_id:
        satirlar.append(f"🎵 <b>TikTok:</b> ✅ Yüklendi (ID: {tt_id})")
    else:
        satirlar.append("🎵 <b>TikTok:</b> ⚠️ Yayınlanmadı / Kayıt Yok")

    tuslar = []
    if not story_id:
        tuslar.append([{"text": "🔄 📱 Story'i Yayınla / Telafi Et", "callback_data": f"retry_kanal:story:{mesaj_id}"}])
    if not fb_id and bool((ayarlar.get("sosyal", {}) or {}).get("facebooka_da_at")):
        tuslar.append([{"text": "🔄 📘 Facebook'a Gönder", "callback_data": f"retry_kanal:facebook:{mesaj_id}"}])
    if not th_id and bool((ayarlar.get("sosyal", {}) or {}).get("threadse_de_at")):
        tuslar.append([{"text": "🔄 🧵 Threads'e Gönder", "callback_data": f"retry_kanal:threads:{mesaj_id}"}])
    if not tw_id and bool((ayarlar.get("sosyal", {}) or {}).get("twittera_da_at")):
        tuslar.append([{"text": "🔄 🐦 X'e Gönder", "callback_data": f"retry_kanal:twitter:{mesaj_id}"}])
    if not yt_id and bool((ayarlar.get("sosyal", {}) or {}).get("youtube_a_da_at") or (ayarlar.get("sosyal", {}) or {}).get("youtubea_da_at")):
        tuslar.append([{"text": "🔄 ▶️ Shorts'a Yükle", "callback_data": f"retry_kanal:youtube:{mesaj_id}"}])
    if not tt_id and bool((ayarlar.get("sosyal", {}) or {}).get("tiktoka_da_at")):
        tuslar.append([{"text": "🔄 🎵 TikTok'a Yükle", "callback_data": f"retry_kanal:tiktok:{mesaj_id}"}])
    if not ig_var:
        tuslar.append([{"text": "🔄 📸 Instagram Postunu Yayınla", "callback_data": f"retry_kanal:ig:{mesaj_id}"}])

    if len(tuslar) > 1:
        tuslar.insert(0, [{"text": "🔄 Eksik Tüm Kanalları Yayınla", "callback_data": f"retry_kanal:hepsi:{mesaj_id}"}])

    telegram_bot.mesaj_gonder("\n".join(satirlar), html=True, butonlar=tuslar if tuslar else None)
    return 0


def tur_onayla(con, ayarlar, haberler, mesaj_id) -> int:
    """Başlıkları onaylanan tur için slaytları üretir ve tam onaya sunar."""
    if not haberler:
        telegram_bot.mesaj_gonder("⚠️ Onaylanacak tur bulunamadı.")
        return 1
    if haberler[0]["durum"] != "baslik_onayi":
        telegram_bot.mesaj_gonder(
            "⚠️ Bu tur başlık onayı aşamasında değil.")
        return 0

    telegram_bot.mesaj_gonder(
        f"🎨 {len(haberler)} slayt hazırlanıyor… (yaklaşık 1 dakika)")
    telegram_bot.sonucu_yaz(
        mesaj_id, f"✅ Başlıklar onaylandı ({len(haberler)} haber).\n"
                  "Slaytlar hazırlandı, aşağıdaki mesajdan yayınlayabilirsin.")

    con.execute(
        "UPDATE haberler SET telegram_message_id = NULL, durum = 'metin_hazir' "
        "WHERE telegram_message_id = ?", (mesaj_id,))
    con.commit()

    sys.path.insert(0, str(KOK / "scripts"))
    import hazirla                                    # noqa: E402
    return hazirla.turu_tamamla(con, ayarlar, list(haberler))


def tur_yeniden_sec(con, ayarlar, haberler, mesaj_id) -> int:
    """Başlık listesini beğenmeyip başka haberler ister."""
    con.execute(
        "UPDATE haberler SET telegram_message_id = NULL, "
        "durum = 'metin_hazir', "
        "ertelenme_sayisi = COALESCE(ertelenme_sayisi, 0) + 1, "
        "atlanma_zamani = datetime('now') "
        "WHERE telegram_message_id = ?", (mesaj_id,))
    con.commit()
    db_senkron.hemen_kaydet("Tur başlıkları reddedildi")
    telegram_bot.sonucu_yaz(
        mesaj_id, f"🔄 {len(haberler)} haber havuza döndü.\n"
                  "Yeni tur hazırlanıyor…")

    sys.path.insert(0, str(KOK / "scripts"))
    import hazirla                                    # noqa: E402
    secilen = secim.tur_icin_sec(con, ayarlar)
    if len(secilen) < 2:
        telegram_bot.mesaj_gonder(
            "⚠️ Havuzda yeterli yeni haber kalmadı, tur kurulamadı.")
        return 0
    return hazirla.basliklari_sun_ve_bekle(con, ayarlar, secilen)


def durum_bildir(con, ayarlar) -> int:
    """/durum komutunun cevabı: Botun ve bekleyen tüm turların detaylı, şeffaf ve interaktif durum raporu."""
    from src.zaman import tr_format, goreceli_zaman, su_an_tr

    sayim = dict(con.execute(
        "SELECT durum, COUNT(*) FROM haberler GROUP BY durum"
    ).fetchall())

    bekleyen_mesajlar = con.execute("""
        SELECT telegram_message_id, tur, son_dakika, durum,
               MIN(gonderim_zamani) as ilk_zaman,
               COUNT(*) as slayt_sayisi,
               GROUP_CONCAT(COALESCE(ig_baslik, baslik_orj), ' || ') as basliklar
        FROM haberler 
        WHERE durum IN ('onay_bekliyor', 'baslik_onayi', 'ertelendi')
           OR (telegram_message_id IS NOT NULL AND durum != 'yayinlandi')
        GROUP BY telegram_message_id
        ORDER BY ilk_zaman DESC
    """).fetchall()

    son = con.execute("""
        SELECT ig_post_id, MAX(gonderim_zamani) z, COUNT(*) n,
               COALESCE(ig_baslik, baslik_orj) baslik
        FROM haberler 
        WHERE durum = 'yayinlandi' AND ig_post_id IS NOT NULL
        GROUP BY telegram_message_id ORDER BY z DESC LIMIT 1
    """).fetchone()

    satirlar = [
        "📊 <b>DAILY BRIEF — SİSTEM & YAYIN DURUMU</b>\n",
        f"🕒 <b>Canlı Saat:</b> {tr_format(su_an_tr(), 'tarih_saat')}",
        f"📰 <b>Taze Haber Havuzu:</b> {sayim.get('metin_hazir', 0)} hazır haber ({sayim.get('yeni', 0)} işlenmemiş)",
        f"✅ <b>Yayınlanan Toplam:</b> {sayim.get('yayinlandi', 0)} haber\n",
    ]

    butonlar = []

    if bekleyen_mesajlar:
        satirlar.append(f"⏳ <b>AÇIKTA / ONAY BEKLEYEN {len(bekleyen_mesajlar)} İŞLEM:</b>\n")
        for b in bekleyen_mesajlar:
            mid = b["telegram_message_id"] or 0
            tur_adi = "📊 Ekonomi Turu" if b["tur"] == "ekonomi" else ("⚡ Son Dakika" if b["son_dakika"] else "📋 Gündem Turu")
            zaman_str = tr_format(b["ilk_zaman"], "tam") if b["ilk_zaman"] else "Bilinmiyor"
            goreceli = goreceli_zaman(b["ilk_zaman"]) if b["ilk_zaman"] else ""
            goreceli_ek = f" ({goreceli})" if goreceli else ""

            ilk_baslik = (b["basliklar"] or "").split(" || ")[0]
            if len(ilk_baslik) > 65:
                ilk_baslik = ilk_baslik[:65] + "…"

            satirlar.append(
                f"🔹 <b>#{mid}</b> {tur_adi} ({b['slayt_sayisi']} slayt)\n"
                f"   • <b>Manşet:</b> {html.escape(ilk_baslik)}\n"
                f"   • <b>Durum:</b> <code>{b['durum']}</code>\n"
                f"   • <b>Gönderim:</b> {zaman_str}{goreceli_ek}"
            )

            if goreceli and ("dakika" in goreceli or "saat" in goreceli or "gün" in goreceli):
                satirlar.append("   ⚠️ <i>(Uzun süredir işlem bekliyor / kilitlenmiş olabilir)</i>")
            satirlar.append("")

            if mid > 0:
                butonlar.append([
                    {"text": f"🔄 #{mid} Menüyü Kurtar / Aç", "callback_data": f"kurtar:{mid}"},
                    {"text": f"🚀 #{mid} Şimdi Yayınla", "callback_data": f"yayinla:{mid}"},
                ])
                butonlar.append([
                    {"text": f"🔍 #{mid} Durum Sorgula", "callback_data": f"yayin_kontrol:{mid}"},
                    {"text": f"🗑 #{mid} İptal / Havuza At", "callback_data": f"iptal:{mid}"},
                ])
    else:
        satirlar.append("✅ <b>Onay bekleyen veya askıda kalan tur yok.</b> Her şey güncel.\n")

    if son and son["z"]:
        son_zaman = tr_format(son["z"], "tam")
        son_goreceli = goreceli_zaman(son["z"])
        satirlar.append(f"📸 <b>Son Yayın:</b> {son_zaman} ({son_goreceli})\n«{html.escape(son['baslik'] or '')}»")

    butonlar.append([
        {"text": "🔄 Durumu Yenile", "callback_data": "durum"},
        {"text": "🧹 Askıdakileri Temizle", "callback_data": "tur_temizle"},
    ])
    butonlar.append([
        {"text": "⚙️ Yönetim Paneli", "callback_data": "yonetim_panel"},
    ])

    telegram_bot.mesaj_gonder("\n".join(satirlar), html=True, butonlar=butonlar)
    return 0


def incele_islemi(con, ayarlar: dict, komut: str, mesaj_id: int = 0, basan: str = "") -> int:
    """
    Kullanıcıya seçtiği haberin detaylı özetini, Gemini puan gerekçesini,
    kaynak ve kategori bilgilerini ve makale özetini Telegram kartı olarak sunar.
    """
    try:
        if ":" in komut:
            ham = komut.split(":", 1)[1].strip()
        else:
            ham = komut.split(" ", 1)[1].strip()
        haber_id = int(ham)
    except (IndexError, ValueError):
        telegram_bot.mesaj_gonder("⚠️ Geçersiz haber numarası. Örnek kullanım: <code>/incele 1482</code>", html=True)
        return 1

    h = con.execute("SELECT * FROM haberler WHERE id = ?", (haber_id,)).fetchone()
    if not h:
        telegram_bot.mesaj_gonder(f"⚠️ #{haber_id} numaralı haber veritabanında bulunamadı.", html=True)
        return 1

    h = dict(h)
    baslik = html.escape(h.get("baslik_orj") or "Başlıksız")
    kaynak = html.escape(h.get("kaynak") or "Bilinmiyor")
    kategori = html.escape((h.get("kategori") or "genel").upper())
    puan = h.get("onem_puani") or 0.0
    gerekce = html.escape(h.get("onem_gerekcesi") or "")
    link = (h.get("link") or "").strip()
    ozet = h.get("ozet_orj") or ""
    makale = h.get("makale_metni") or ""

    icerik = (makale.strip()[:400] if len(makale.strip()) > 50 else ozet.strip()[:400])
    icerik_temiz = html.escape(icerik).strip()
    if len(makale or ozet) > 400:
        icerik_temiz += "…"

    tarih_str = ""
    if h.get("yayin_tarihi"):
        try:
            dt = datetime.fromisoformat(h["yayin_tarihi"].replace("Z", "+00:00"))
            tarih_str = dt.strftime("%d.%m.%Y %H:%M")
        except Exception:
            tarih_str = str(h["yayin_tarihi"])[:16]

    satirlar = [
        f"🔍 <b>Haber İncelemesi #{haber_id}</b>",
        "",
        f"📰 <b>{baslik}</b>",
        f"🏷️ <i>{kaynak} · {kategori}</i>" + (f" · 🕒 <i>{tarih_str}</i>" if tarih_str else ""),
        f"⭐ <b>Önem Puanı:</b> {puan}/10",
    ]
    if gerekce:
        satirlar.append(f"💡 <b>Puanlama Gerekçesi:</b> <i>{gerekce}</i>")

    if icerik_temiz:
        satirlar.extend(["", "📝 <b>Haber İçeriği / Giriş:</b>", f"<blockquote expandable>{icerik_temiz}</blockquote>"])

    if link and link.startswith("http"):
        satirlar.extend(["", f"🔗 <a href=\"{link}\">Orijinal Haberi Kaynağında Oku</a>"])

    menu = [
        [{"text": f"⚡ #{haber_id} Numaralı Haberi Hazırla", "callback_data": f"hazirla:{haber_id}"}],
        [{"text": "← Öneri Listesine Dön", "callback_data": "sondakika"}],
    ]
    telegram_bot.mesaj_gonder("\n".join(satirlar), butonlar=menu, html=True)
    return 0


def tura_birak(con, haberler, mesaj_id, basan) -> int:
    """Haberi TEKİL post adaylığından çıkarır, carousel turunda bırakır."""
    idler = [h["id"] for h in haberler]
    isaret = ",".join("?" * len(idler))
    con.execute(
        f"UPDATE haberler SET sadece_tur = 1, son_dakika = 0, "
        f"telegram_message_id = NULL, "
        f"durum = CASE WHEN ig_baslik IS NOT NULL THEN 'metin_hazir' "
        f"             ELSE 'yeni' END "
        f"WHERE id IN ({isaret})", idler)
    con.commit()
    db_senkron.hemen_kaydet("Tekil adaylıktan çıkarıldı")

    baslik = (haberler[0]["ig_baslik"] or haberler[0]["baslik_orj"] or "")[:60]
    telegram_bot.sonucu_yaz(
        mesaj_id,
        f"📋 Tekil post olarak sunulmayacak: {baslik}\n\n"
        "Haber havuzda duruyor ve 10'lu turda yarışmaya devam edecek.",
        bildir=False)
    log.info("tekil adaylıktan çıkarıldı: %s (basan=%s)", idler, basan)
    return 0
