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

import html
import json
import logging
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import requests
import yaml                                       # noqa: E402

from src import (                                  # noqa: E402
    aday, android_bridge, android_otomasyon, ayar, caption, db, db_senkron, dogrula, facebook, fetch_news,
    filtre,
    instagram,
    make_image,
    secim,
    slaytlar, telegram_bot, threads, twitter, upload_image, yonetim,
)
from src import generate_text                      # noqa: E402
from src.generate_text import metinleri_uret       # noqa: E402

log = logging.getLogger("onay")

# Ayarlar main() içinde okunuyor ama menuyu_geri_koy() gibi yardımcılar da
# ihtiyaç duyuyor; parametre zincirini uzatmamak için burada tutuluyor.
_ayarlar_onbellek: dict = {}

# Açık bir onay mesajına bağlı OLMAYAN komutlar. Bunlar `mesaj_id`
# taşımıyor; buraya eklenmezse main() daha en başta hata verip çıkıyor.
# (`/tur` buraya girmiyor — workflow onu `hazirla.py`'ye yönlendiriyor,
#  bu script'e hiç uğramıyor.)
# ⚠️ `haber_sec`/`haber_vazgec` tur id'sini KOMUTTA taşıyor; Worker'ın
# gönderdiği mesaj_id alternatif mesajına ait ve işe yaramıyor.
MESAJSIZ_KOMUTLAR = {"durum", "ayar", "tamamla", "arsiv", "ara",
                     "havuz_guncelle", "sondakika", "son_dakika", "haftalik", "video", "reels",
                     "yonetim", "yonetim_panel", "duraklat", "devam_et",
                     "saglik_testi", "kota_raporu", "tur_temizle",
                     "haber_sec", "haber_vazgec", "kurtar",
                     "link", "arastir", "ozel", "faiz", "enflasyon", "fed", "makro",
                     "hisse", "kripto", "piyasa", "sonpostlar", "son_postlar",
                     # Tur id'sini KOMUTTA taşıyorlar (ayrı mesajın düğmesi)
                     "yayin_kontrol", "yeniden_yayinla", "retry_kanal",
                     "gorsel_kabul", "gorsel_yeni"}


def turu_getir(con, mesaj_id: int) -> list:
    """
    Bu onay mesajına bağlı haberleri slayt sırasıyla getirir.

    ⚠️ SIRALAMA: `slayt_sirasi` belirlenmişse (kullanıcı taşıdıysa) o sıra
    kullanılır; yoksa varsayılan puan ve tarih sırası geçerlidir.
    """
    return list(con.execute(
        "SELECT * FROM haberler WHERE telegram_message_id = ? "
        "ORDER BY CASE WHEN COALESCE(slayt_sirasi, 0) > 0 THEN slayt_sirasi ELSE 999 END ASC, "
        "COALESCE(daha_once_yayinlandi, 0) ASC, "
        "onem_puani DESC, yayin_tarihi DESC",
        (mesaj_id,),
    ))


def _detay_urlleri(ham) -> list[str]:
    """
    `detay_url` kolonunu listeye çevirir.

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


def _sonuclari_kur(haberler: list) -> list[dict]:
    """Caption'ın atıf bloğu için katman bilgisini toparlar."""
    return [
        {"id": h["id"], "katman": h["gorsel_kaynagi"], "atif": h["gorsel_atif"] or ""}
        for h in haberler
    ]


def _yayin_ozeti(haberler: list) -> str:
    """
    Yayın sonucu mesajına konan başlık özeti.

    ⚠️ NEDEN GEREKTİ (20 Ağu 2026): sonuç mesajı yalnızca "5 slayt
    yayınlandı" diyordu. Gün içinde birden çok tekil post çıkınca
    hangisinin yayınlandığı anlaşılmıyordu — özellikle çoklu seçimde
    art arda üç onay mesajı geliyor ve hepsi birbirinin aynısı
    görünüyor.

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


def _url_canli_ve_uygun_mu(url: str) -> bool:
    """URL'nin erişilebilir ve Meta/Instagram için uygun olup olmadığını denetler."""
    if not url or not isinstance(url, str) or not url.startswith("http"):
        return False
    # uguu.se bağlantıları Meta Graph API tarafından reddedilir veya süresi 3 saatte biter
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


def _slayti_tazele_ve_yukle(h: dict | sqlite3.Row, ayarlar: dict) -> str | None:
    """Haberin yerel slayt dosyasını bulup taze güvenli barındırıcıya yükler."""
    h_dict = dict(h)
    h_id = h_dict.get("id")
    cikis = make_image.CIKTI_KLASORU

    # 1. Haberin kayıtlı gorsel_yolu
    yol = h_dict.get("gorsel_yolu")
    if yol and Path(yol).exists():
        try:
            return upload_image.gorsel_yukle(Path(yol), ayarlar)["url"]
        except Exception as e:
            log.warning("Görsel yolu tazelenemedi (%s): %s", yol, e)

    # 2. Cikti klasorunde ara
    if h_id:
        for dosya_adi in (f"slayt-{h_id}.jpg", f"slayt-{h_id}-kapak.jpg", f"slayt-{h_id}-1.jpg"):
            p = cikis / dosya_adi
            if p.exists():
                try:
                    return upload_image.gorsel_yukle(p, ayarlar)["url"]
                except Exception as e:
                    log.warning("Çıktı slaytı %s yüklenemedi: %s", p, e)
    return None


def _urlleri_dogrula_ve_onar(con, ayarlar: dict, haberler: list[dict | sqlite3.Row], urller: list[str]) -> list[str]:
    """
    Tüm görsel URL'lerini denetler; süresi dolmuş veya uguu.se gibi riskli URL'leri
    yerel dosyalardan veya anında yeniden çizerek taze barındırıcıya (ImgBB / Litterbox) yükler.
    """
    if not urller or not haberler:
        return urller

    # 1. URL'lerin hepsi canlı ve güvenli mi?
    hepsi_canli = all(_url_canli_ve_uygun_mu(u) for u in urller)
    if hepsi_canli:
        return urller

    log.warning("Bazı görsel URL'leri süresi dolmuş veya geçersiz, otomatik onarma başlatılıyor...")

    ilk_h = dict(haberler[0])
    son_dakika_mi = bool(ilk_h.get("son_dakika"))

    # A) Son Dakika Tekil Haberi İse: Slaytları ve detayları baştan üretip yükle
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

            # Veritabanını güncelle
            con.execute(
                "UPDATE haberler SET gorsel_url = ?, detay_url = ?, story_url = ? WHERE id = ?",
                (taze_urller[0], json.dumps(taze_urller[1:]), story_url, ilk_h["id"])
            )
            con.commit()
            log.info("Son dakika haberi #%s için %d taze görsel URL'si başarıyla onarıldı.", ilk_h["id"], len(taze_urller))
            return taze_urller
        except Exception as e:
            log.exception("Son dakika görsel onarma hatası: %s", e)

    # B) Çoklu Tur İse: Her bir haberi tek tek tazele
    taze_urller = []
    for idx, h_raw in enumerate(haberler):
        h_d = dict(h_raw)
        mevcut_url = h_d.get("gorsel_url")
        if _url_canli_ve_uygun_mu(mevcut_url):
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


def yayinla(con, ayarlar, haberler, mesaj_id, basan, kanallar: str | None = None) -> int:
    if any(h["durum"] == "yayinlandi" for h in haberler):
        telegram_bot.mesaj_gonder("⚠️ Bu tur zaten yayınlanmış, tekrar gönderilmedi.")
        return 0

    # Kanal filtreleme: parametre > veritabanı kaydı > config varsayılanı
    secili = kanallar
    if not secili and haberler and "yayin_kanallari" in haberler[0].keys():
        secili = haberler[0]["yayin_kanallari"]

    if secili:
        k_set = {k.strip().lower() for k in secili.split(",") if k.strip()}
        paylas_reels = "reels" in k_set
        paylas_ig = "ig" in k_set and not paylas_reels
        paylas_story = "story" in k_set
        paylas_fb = "facebook" in k_set and bool((ayarlar.get("sosyal", {}) or {}).get("facebooka_da_at"))
        paylas_th = "threads" in k_set and bool((ayarlar.get("sosyal", {}) or {}).get("threadse_de_at")) and threads.kullanilabilir_mi()
        paylas_tw = ("twitter" in k_set or "x" in k_set) and bool((ayarlar.get("sosyal", {}) or {}).get("twittera_da_at")) and twitter.kullanilabilir_mi()
        paylas_yt = ("youtube" in k_set or "yt" in k_set) and bool((ayarlar.get("sosyal", {}) or {}).get("youtube_a_da_at"))
        paylas_tt = ("tiktok" in k_set or "tt" in k_set) and bool((ayarlar.get("sosyal", {}) or {}).get("tiktoka_da_at"))
    else:
        paylas_reels = False
        paylas_ig = True
        paylas_story = True
        paylas_fb = bool((ayarlar.get("sosyal", {}) or {}).get("facebooka_da_at"))
        paylas_th = bool((ayarlar.get("sosyal", {}) or {}).get("threadse_de_at")) and threads.kullanilabilir_mi()
        paylas_tw = bool((ayarlar.get("sosyal", {}) or {}).get("twittera_da_at")) and twitter.kullanilabilir_mi()
        paylas_yt = bool((ayarlar.get("sosyal", {}) or {}).get("youtube_a_da_at"))
        paylas_tt = bool((ayarlar.get("sosyal", {}) or {}).get("tiktoka_da_at"))

    urller = [h["gorsel_url"] for h in haberler if h["gorsel_url"]]

    # Ekonomi turu: 1. slayt Piyasa Isı Haritası, 2. slayt 30 Varlık Tablosudur
    ilk_h_dict = dict(haberler[0]) if haberler else {}
    if ilk_h_dict.get("tur") == "ekonomi":
        tablo_satir = con.execute(
            "SELECT deger FROM ayarlar WHERE anahtar = ?",
            (f"piyasa_tablosu_{mesaj_id}",)
        ).fetchone()
        kart_satir = con.execute(
            "SELECT deger FROM ayarlar WHERE anahtar = ?",
            (f"piyasa_karti_{mesaj_id}",)
        ).fetchone()

        if tablo_satir and tablo_satir["deger"]:
            urller.insert(0, tablo_satir["deger"])
        if kart_satir and kart_satir["deger"]:
            urller.insert(0, kart_satir["deger"])

    # Son dakika turu TEK haberden birden çok slayt üretiyor: 1 haber +
    # 1-4 ayrıntı sayfası (metin uzunsa sayfa ekleniyor). Bunlar ayrı
    # kolonda JSON listesi olarak duruyor; buraya eklenmezse elde tek
    # görsel kalıyor ve Instagram carousel'i reddediyor.
    for h in haberler:
        if h["son_dakika"]:
            urller.extend(_detay_urlleri(h["detay_url"]))

    # Görsellerin canlılığını ve Meta uyumluluğunu doğrula, süresi geçmiş/uguu olanları onar
    urller = _urlleri_dogrula_ve_onar(con, ayarlar, haberler, urller)

    if len(urller) < 2 and not paylas_reels:
        raise RuntimeError(
            f"yayın için en az 2 görsel gerekli, {len(urller)} var. "
            f"Tur bozuk görünüyor — /tur ile yenisini kurabilirsin."
        )

    # Caption belirleme
    if ilk_h_dict.get("tur") == "ekonomi" and ilk_h_dict.get("ig_caption"):
        metin = ilk_h_dict["ig_caption"]
    elif haberler[0]["son_dakika"]:
        metin = caption.son_dakika_caption(
            haberler[0], _sonuclari_kur(haberler), ayarlar)
    else:
        metin = caption.caption_kur(
            haberler, _sonuclari_kur(haberler), ayarlar=ayarlar)

    post_id = None
    baglanti = None
    ig_notu = ""
    if paylas_reels:
        # Reels Manuel Trend Müzik Modu: 1080x1920 MP4 üretilir + kopyalanabilir açıklama ile Telegram'a iletilir
        try:
            import html as html_lib
            from src import video
            log.info("Reels videosu için 9:16 dikey görseller hazırlanıyor...")
            dikey_gorseller = video.reels_dikey_gorselleri_uret(urller, haberler=haberler, ayarlar=ayarlar)
            if not dikey_gorseller:
                raise RuntimeError("Reels videosu için 9:16 görsel üretilemedi")

            # Müziksiz, yüksek kaliteli 1080x1920 MP4 videosu üret
            video_yolu = video.slaytlardan_reels_uret(dikey_gorseller, fps=30, slayt_suresi=3.5, gecis_suresi=0.5)

            # Üretilen MP4 videosunu ve kopyalanabilir caption'ı Telegram grubuna ilet
            temiz_metin = html_lib.escape(metin.strip())
            telegram_bot.video_gonder(
                video_yolu,
                aciklama="🎬 <b>Daily Brief Reels Videosu Hazır!</b>\n\n"
                         "📝 <b>Açıklama (Kopyalamak için Dokun):</b>\n"
                         f"<code>{temiz_metin}</code>\n\n"
                         "💡 <i>Videoyu kaydedip Instagram uygulamasından trend müzikle kolayca paylaşabilirsiniz.</i>",
            )
            ig_notu = "\n🎬 Reels videosu ve açıklama metni Telegram'a iletildi"

        except Exception as e:
            log.exception("Instagram Reels video hazırlama hatası")
            ig_notu = f"\n⚠️ Reels videosu hazırlanamadı: {type(e).__name__}: {e}"
    elif paylas_ig:
        post_id = instagram.carousel_yayinla(urller, metin, ayarlar)
        baglanti = instagram.post_baglantisi(post_id, ayarlar)
        ig_notu = "\n📸 Instagram gönderisi yayınlandı"
    else:
        ig_notu = "\n📸 Instagram atlandı"

    # Story postla birlikte gidiyor (kullanıcı kapatmadıysa).
    story_notu = ""
    story_id = None
    story_url = next((h["story_url"] for h in haberler if h["story_url"]), None)
    if paylas_story and story_url:
        try:
            story_id = instagram.story_yayinla(story_url, ayarlar)
            story_notu = "\n📱 Story de paylaşıldı"
        except Exception as e:
            log.warning("story yayınlanamadı: %s", e)
            story_notu = f"\n⚠️ Story paylaşılamadı: {type(e).__name__}"

    # Facebook: aynı içerik, aynı jeton, ayrı kanal.
    fb_notu = ""
    fb_id = None
    if paylas_fb:
        try:
            fb_id = facebook.albüm_yayinla(urller, metin, ayarlar)
            fb_notu = "\n📘 Facebook'a da paylaşıldı"
            log.info("Facebook: %s", fb_id)
            if paylas_story and story_url:
                try:
                    facebook.story_yayinla(story_url, ayarlar)
                    fb_notu += " (story dahil)"
                except Exception as e:
                    log.warning("Facebook story olmadı: %s", e)
        except Exception as e:
            log.warning("Facebook paylaşılamadı: %s", e)
            fb_notu = f"\n⚠️ Facebook'a gitmedi: {type(e).__name__}"

    # Threads: ayrı jeton istiyor.
    th_notu = ""
    th_gonderi_id = None
    th_yarim = False
    if paylas_th:
        try:
            son_dakika_mi = bool(haberler[0]["son_dakika"])
            halkalar = caption.threads_halkalari(
                haberler, urller, son_dakika=son_dakika_mi,
                ayarlar=ayarlar, tarihli=not son_dakika_mi,
            )
            th_id, th_adet = threads.zincir_yayinla(halkalar)
            th_gonderi_id = th_id

            if th_adet < len(halkalar):
                log.warning("zincir %s/%s kaldı, tamamlama deneniyor",
                            th_adet, len(halkalar))
                try:
                    th_adet, _ = threads.zinciri_tamamla(th_id, halkalar)
                except Exception as e:                # noqa: BLE001
                    log.warning("otomatik tamamlama olmadı: %s", str(e)[:120])

            if th_adet == len(halkalar):
                th_notu = f"\n🧵 Threads'e de paylaşıldı ({th_adet} halka)"
            else:
                th_yarim = True
                th_notu = (f"\n⚠️ Threads zinciri yarım kaldı: "
                           f"{th_adet}/{len(halkalar)} halka\n"
                           f"Aşağıdaki düğmeyle tamamlayabilirsin.")
            log.info("Threads: %s (%s/%s halka)", th_id, th_adet, len(halkalar))
        except Exception as e:
            log.warning("Threads paylaşılamadı: %s", e)
            th_notu = f"\n⚠️ Threads'e gitmedi: {type(e).__name__}"

    # X (Twitter) API v2 paylaşımı
    tw_notu = ""
    tw_gonderi_id = None
    if paylas_tw:
        try:
            son_dakika_mi = bool(haberler[0]["son_dakika"]) if haberler else False
            if len(haberler) > 1 or (son_dakika_mi and len(urller) > 1):
                tw_id, tw_adet = twitter.zincir_yayinla(haberler, urller, ayarlar, son_dakika=son_dakika_mi)
                tw_gonderi_id = tw_id
                if tw_id:
                    tw_notu = f"\n🐦 X'e (Twitter) de paylaşıldı ({tw_adet} tweet zinciri)"
            else:
                tw_gonderi_id = twitter.tekil_yayinla(haberler[0], urller, ayarlar)
                if tw_gonderi_id:
                    tw_notu = "\n🐦 X'e (Twitter) de paylaşıldı"
            log.info("Twitter: %s", tw_gonderi_id)
        except Exception as e:
            log.warning("Twitter paylaşılamadı: %s", e)
            tw_notu = f"\n⚠️ X'e (Twitter) gitmedi: {type(e).__name__}"

    # Ortak Video Üretimi (YouTube Shorts & TikTok için)
    paylasilan_video_yolu = None
    if (paylas_yt or paylas_tt) and urller:
        try:
            from src import video
            dikey_gorseller = video.reels_dikey_gorselleri_uret(urller, haberler=haberler, ayarlar=ayarlar)
            if dikey_gorseller:
                paylasilan_video_yolu = video.slaytlardan_reels_uret(dikey_gorseller, fps=30, slayt_suresi=3.5, gecis_suresi=0.5)
        except Exception as e:
            log.exception("YouTube/TikTok için ortak video üretilemedi: %s", e)

    # YouTube Shorts paylaşımı
    yt_notu = ""
    yt_url = None
    if paylas_yt:
        if not paylasilan_video_yolu:
            yt_notu = "\n⚠️ YouTube Shorts videosu oluşturulamadı"
        else:
            try:
                from src import youtube
                h0 = dict(haberler[0]) if haberler else {}
                baslik_yt = h0.get("ig_baslik") or h0.get("baslik_orj") or "Günün Gelişmeleri"
                yt_res = youtube.shorts_yukle(paylasilan_video_yolu, baslik=baslik_yt, aciklama=metin, ayarlar=ayarlar)
                if yt_res.get("durum"):
                    yt_url = yt_res.get("url")
                    yt_notu = "\n▶️ YouTube Shorts yayınlandı"
                else:
                    hata_yt = yt_res.get("hata", "")[:60]
                    yt_notu = f"\n⚠️ YouTube Shorts gitmedi: {hata_yt}"
            except Exception as e:
                log.warning("YouTube Shorts paylaşılamadı: %s", e)
                yt_notu = f"\n⚠️ YouTube Shorts hatası: {type(e).__name__}"

    # TikTok video paylaşımı
    tt_notu = ""
    tt_publish_id = None
    if paylas_tt:
        if not paylasilan_video_yolu:
            tt_notu = "\n⚠️ TikTok videosu oluşturulamadı"
        else:
            try:
                from src import tiktok
                h0 = dict(haberler[0]) if haberler else {}
                baslik_tt = h0.get("ig_baslik") or h0.get("baslik_orj") or "Günün Gelişmeleri"
                tt_res = tiktok.video_yukle(paylasilan_video_yolu, baslik=baslik_tt, ayarlar=ayarlar)
                if tt_res.get("durum"):
                    tt_publish_id = tt_res.get("publish_id")
                    tt_notu = "\n🎵 TikTok videosu yüklendi"
                else:
                    hata_tt = tt_res.get("hata", "")[:60]
                    tt_notu = f"\n⚠️ TikTok gitmedi: {hata_tt}"
            except Exception as e:
                log.warning("TikTok paylaşılamadı: %s", e)
                tt_notu = f"\n⚠️ TikTok hatası: {type(e).__name__}"

    # ⚠️ TÜM PLATFORM ID'LERİ SAKLANMALI.
    con.execute(
        "UPDATE haberler SET durum = 'yayinlandi', ig_post_id = ?, "
        "facebook_post_id = ?, threads_post_id = ?, story_post_id = ?, "
        "twitter_post_id = ?, youtube_post_id = ?, tiktok_post_id = ? "
        "WHERE telegram_message_id = ?",
        (post_id, fb_id, th_gonderi_id, story_id, tw_gonderi_id, yt_url, tt_publish_id, mesaj_id),
    )
    con.commit()

    # Doğrudan canlı gönderi link butonları
    canli_link_dugmeleri = []
    satir_1 = []
    if baglanti:
        satir_1.append({"text": "📸 Instagram'da Gör", "url": baglanti})
    if th_gonderi_id:
        th_url = threads.post_baglantisi(th_gonderi_id)
        if th_url:
            satir_1.append({"text": "🧵 Threads'te Gör", "url": th_url})
    if satir_1:
        canli_link_dugmeleri.append(satir_1)

    satir_2 = []
    if fb_id:
        fb_url = facebook.post_baglantisi(fb_id)
        if fb_url:
            satir_2.append({"text": "📘 Facebook'ta Gör", "url": fb_url})
    if tw_gonderi_id:
        tw_url = twitter.post_baglantisi(tw_gonderi_id)
        if tw_url:
            satir_2.append({"text": "🐦 X'te Gör", "url": tw_url})
    if yt_url:
        satir_2.append({"text": "▶️ Shorts'ta Gör", "url": yt_url})
    if satir_2:
        canli_link_dugmeleri.append(satir_2)

    # Başarısız olan veya eksik kalan kanallar için anında tek tıkla telafi butonları
    telafi_dugmeleri = []
    if paylas_story and (not story_url or "⚠️" in story_notu):
        telafi_dugmeleri.append([{"text": "🔄 📱 Story'i Tekrar Paylaş", "callback_data": f"retry_kanal:story:{mesaj_id}"}])
    if paylas_fb and (not fb_id or "⚠️" in fb_notu):
        telafi_dugmeleri.append([{"text": "🔄 📘 Facebook'a Tekrar Gönder", "callback_data": f"retry_kanal:facebook:{mesaj_id}"}])
    if paylas_th and (not th_gonderi_id or "⚠️" in th_notu or th_yarim):
        telafi_dugmeleri.append([{"text": "🔄 🧵 Threads'e Tekrar Gönder", "callback_data": f"retry_kanal:threads:{mesaj_id}"}])
    if paylas_tw and (not tw_gonderi_id or "⚠️" in tw_notu):
        telafi_dugmeleri.append([{"text": "🔄 🐦 X'e Tekrar Gönder", "callback_data": f"retry_kanal:twitter:{mesaj_id}"}])
    if paylas_yt and (not yt_url or "⚠️" in yt_notu):
        telafi_dugmeleri.append([{"text": "🔄 ▶️ Shorts'a Tekrar Yükle", "callback_data": f"retry_kanal:youtube:{mesaj_id}"}])
    if paylas_tt and "⚠️" in tt_notu:
        telafi_dugmeleri.append([{"text": "🔄 🎵 TikTok'a Tekrar Yükle", "callback_data": f"retry_kanal:tiktok:{mesaj_id}"}])
    if paylas_reels and (not post_id or "⚠️" in ig_notu):
        telafi_dugmeleri.append([{"text": "🔄 🎬 Reels'i Tekrar Gönder", "callback_data": f"retry_kanal:reels:{mesaj_id}"}])
    elif paylas_ig and not post_id:
        telafi_dugmeleri.append([{"text": "🔄 📸 Instagram'ı Tekrar Dene", "callback_data": f"retry_kanal:ig:{mesaj_id}"}])

    if len(telafi_dugmeleri) > 1:
        telafi_dugmeleri.insert(0, [{"text": "🔄 Başarısız Tüm Kanalları Tekrar Dene", "callback_data": f"retry_kanal:hepsi:{mesaj_id}"}])

    telegram_bot.sonucu_yaz(
        mesaj_id,
        f"✅ YAYINLANDI — {len(urller)} slayt{ig_notu}{story_notu}{fb_notu}{th_notu}{tw_notu}{yt_notu}{tt_notu}\n"
        f"\n{_yayin_ozeti(haberler)}\n"
        f"\nOnaylayan: {basan or 'bilinmiyor'}\n"
        f"{baglanti or post_id}",
        bildir=True,
        ek_dugmeler=(
            canli_link_dugmeleri
            + telafi_dugmeleri
            + ([[{"text": "🔗 Threads zincirini tamamla",
                  "callback_data": "tamamla"}]] if th_yarim else [])
            + [[{"text": "🔍 Yayın durumunu kontrol et",
                  "callback_data": f"yayin_kontrol:{mesaj_id}"}]]
        ),
    )
    return 0


def zinciri_tamamla(con, ayarlar) -> int:
    """
    `/tamamla` — son yayınlanan turun Threads zinciri eksikse tamamlar.

    Threads'in medya tarafı kararsız ve zincir ortada kesilebiliyor.
    Kesildiğinde bildirim düşüyor ama düzeltmenin Telegram'dan yolu
    yoktu; terminale inmek gerekiyordu.
    """
    if not threads.kullanilabilir_mi():
        telegram_bot.mesaj_gonder("⚠️ Threads anahtarları tanımlı değil.")
        return 0

    satir = con.execute(
        "SELECT telegram_message_id AS msg, MIN(threads_post_id) AS th "
        "FROM haberler WHERE durum = 'yayinlandi' "
        "AND threads_post_id IS NOT NULL "
        "GROUP BY telegram_message_id ORDER BY MIN(gonderim_zamani) DESC "
        "LIMIT 1"
    ).fetchone()

    if not satir:
        telegram_bot.mesaj_gonder(
            "ℹ️ Threads'e paylaşılmış bir tur bulunamadı.")
        return 0

    haberler = turu_getir(con, satir["msg"])
    urller = [h["gorsel_url"] for h in haberler if h["gorsel_url"]]
    ilk_h_dict = dict(haberler[0]) if haberler else {}
    if ilk_h_dict.get("tur") == "ekonomi":
        tablo_satir = con.execute(
            "SELECT deger FROM ayarlar WHERE anahtar = ?",
            (f"piyasa_tablosu_{satir['msg']}",)
        ).fetchone()
        kart_satir = con.execute(
            "SELECT deger FROM ayarlar WHERE anahtar = ?",
            (f"piyasa_karti_{satir['msg']}",)
        ).fetchone()
        if tablo_satir and tablo_satir["deger"]:
            urller.insert(0, tablo_satir["deger"])
        if kart_satir and kart_satir["deger"]:
            urller.insert(0, kart_satir["deger"])

    son_dakika_mi = bool(haberler[0]["son_dakika"])
    if son_dakika_mi:
        for h in haberler:
            urller.extend(_detay_urlleri(h["detay_url"]))

    halkalar = caption.threads_halkalari(
        haberler, urller, son_dakika=son_dakika_mi,
        ayarlar=ayarlar, tarihli=not son_dakika_mi,
    )

    try:
        yayinlanan, hedef = threads.zinciri_tamamla(satir["th"], halkalar)
    except Exception as e:
        telegram_bot.mesaj_gonder(f"⚠️ Tamamlanamadı: {type(e).__name__}: {e}")
        return 1

    baglanti = threads.post_baglantisi(satir["th"])
    if yayinlanan >= hedef:
        telegram_bot.mesaj_gonder(
            f"✅ Zincir tam ({hedef} halka).\n{baglanti}")
    else:
        telegram_bot.mesaj_gonder(
            f"⚠️ Zincir hâlâ eksik: {yayinlanan}/{hedef} halka.\n"
            f"Threads medya hatası sürüyor olabilir, sonra tekrar dene.\n"
            f"{baglanti}")
    return 0


def kanal_telafi_et(con, ayarlar: dict, haberler: list, mesaj_id: int, kanal: str, basan: str) -> int:
    """
    Yayın sırasında herhangi bir platformda başarısız olan veya eksik kalan
    gönderiyi Telegram'dan tek tıkla telafi eder ve yayınlar.
    """
    if not haberler:
        haberler = turu_getir(con, mesaj_id)
    if not haberler:
        telegram_bot.mesaj_gonder(f"⚠️ #{mesaj_id} numaralı tura ait haber kaydı bulunamadı.")
        return 0

    ilk_h_dict = dict(haberler[0])
    son_dakika_mi = bool(ilk_h_dict.get("son_dakika"))
    tur_mu = len(haberler) > 1

    # Görselleri ve varsa detay/piyasa slaytlarını topla
    urller = [h["gorsel_url"] for h in haberler if h["gorsel_url"]]
    if ilk_h_dict.get("tur") == "ekonomi":
        tablo_satir = con.execute(
            "SELECT deger FROM ayarlar WHERE anahtar = ?",
            (f"piyasa_tablosu_{mesaj_id}",)
        ).fetchone()
        kart_satir = con.execute(
            "SELECT deger FROM ayarlar WHERE anahtar = ?",
            (f"piyasa_karti_{mesaj_id}",)
        ).fetchone()
        if tablo_satir and tablo_satir["deger"]:
            urller.insert(0, tablo_satir["deger"])
        if kart_satir and kart_satir["deger"]:
            urller.insert(0, kart_satir["deger"])

    for h in haberler:
        if h["son_dakika"]:
            urller.extend(_detay_urlleri(h["detay_url"]))

    # Görsellerin canlılığını ve Meta uyumluluğunu doğrula, süresi geçmiş/uguu olanları onar
    urller = _urlleri_dogrula_ve_onar(con, ayarlar, haberler, urller)

    # Caption metni
    if ilk_h_dict.get("tur") == "ekonomi" and ilk_h_dict.get("ig_caption"):
        metin = ilk_h_dict["ig_caption"]
    elif son_dakika_mi:
        metin = caption.son_dakika_caption(haberler[0], _sonuclari_kur(haberler), ayarlar)
    else:
        metin = caption.caption_kur(haberler, _sonuclari_kur(haberler), ayarlar=ayarlar)

    sonuclar = []
    canli_linkler = []

    # 1. STORY TELAFİSİ
    if kanal in ("story", "hepsi"):
        story_url = next((h["story_url"] for h in haberler if h["story_url"]), None)
        # Eğer story_url erişilemezse veya catbox bağlantısı kopuyorsa yeniden üret & yükle
        story_yenilendi = False
        try:
            r_test = requests.head(story_url, timeout=5) if story_url else None
            if not r_test or r_test.status_code != 200:
                story_yenilendi = True
        except Exception:
            story_yenilendi = True

        if story_yenilendi or not story_url:
            try:
                story_yol = make_image.CIKTI_KLASORU / f"story-{ilk_h_dict['id']}.jpg"
                if not story_yol.exists():
                    story_img = make_image.story_haber(
                        ilk_h_dict["ig_baslik"] or ilk_h_dict["baslik_orj"],
                        ilk_h_dict["slayt_ozet"],
                        ilk_h_dict["kaynak"],
                        ayarlar,
                        kategori=ilk_h_dict.get("kategori", "gundem")
                    )
                    story_yol.parent.mkdir(exist_ok=True, parents=True)
                    story_img.save(story_yol, "JPEG", quality=96)

                yukleme = upload_image.gorsel_yukle(story_yol, ayarlar)
                story_url = yukleme.get("url")
                con.execute("UPDATE haberler SET story_url = ? WHERE telegram_message_id = ?", (story_url, mesaj_id))
                con.commit()
            except Exception as e:
                log.warning("Story görseli yerelden taze üretilemedi: %s", e)

        if story_url:
            try:
                st_id = instagram.story_yayinla(story_url, ayarlar)
                sonuclar.append(f"📱 <b>Instagram Story:</b> Başarıyla yayınlandı!")
                con.execute("UPDATE haberler SET story_post_id = ? WHERE telegram_message_id = ?", (st_id, mesaj_id))
                con.commit()
            except Exception as e:
                log.exception("Instagram Story telafi hatası: %s", e)
                sonuclar.append(f"⚠️ <b>Instagram Story:</b> Başarısız ({type(e).__name__}: {str(e)[:80]})")

            if bool((ayarlar.get("sosyal", {}) or {}).get("facebooka_da_at")):
                try:
                    fb_st_id = facebook.story_yayinla(story_url, ayarlar)
                    sonuclar.append(f"📘 <b>Facebook Story:</b> Başarıyla yayınlandı!")
                except Exception as e:
                    log.warning("Facebook Story telafi hatası: %s", e)
                    sonuclar.append(f"⚠️ <b>Facebook Story:</b> Başarısız ({type(e).__name__})")
        else:
            sonuclar.append("⚠️ <b>Story:</b> Story görseli üretilemedi/yüklenemedi.")

    # 2. FACEBOOK POST TELAFİSİ
    if kanal in ("facebook", "hepsi"):
        try:
            fb_id = facebook.albüm_yayinla(urller, metin, ayarlar)
            con.execute("UPDATE haberler SET facebook_post_id = ? WHERE telegram_message_id = ?", (fb_id, mesaj_id))
            con.commit()
            fb_url = facebook.post_baglantisi(fb_id)
            sonuclar.append(f"📘 <b>Facebook Albümü:</b> Başarıyla paylaşıldı!")
            if fb_url:
                canli_linkler.append([{"text": "📘 Facebook'ta Gör", "url": fb_url}])
        except Exception as e:
            log.exception("Facebook telafi hatası: %s", e)
            sonuclar.append(f"⚠️ <b>Facebook:</b> Başarısız ({type(e).__name__}: {str(e)[:80]})")

    # 3. THREADS TELAFİSİ
    if kanal in ("threads", "hepsi"):
        try:
            halkalar = caption.threads_halkalari(
                haberler, urller, son_dakika=son_dakika_mi,
                ayarlar=ayarlar, tarihli=not son_dakika_mi
            )
            th_id, th_adet = threads.zincir_yayinla(halkalar)
            if th_adet < len(halkalar):
                try:
                    th_adet, _ = threads.zinciri_tamamla(th_id, halkalar)
                except Exception:
                    pass
            con.execute("UPDATE haberler SET threads_post_id = ? WHERE telegram_message_id = ?", (th_id, mesaj_id))
            con.commit()
            th_url = threads.post_baglantisi(th_id)
            sonuclar.append(f"🧵 <b>Threads Zinciri:</b> Başarıyla paylaşıldı ({th_adet} halka)!")
            if th_url:
                canli_linkler.append([{"text": "🧵 Threads'te Gör", "url": th_url}])
        except Exception as e:
            log.exception("Threads telafi hatası: %s", e)
            sonuclar.append(f"⚠️ <b>Threads:</b> Başarısız ({type(e).__name__}: {str(e)[:80]})")

    # 4. TWITTER / X TELAFİSİ
    if kanal in ("twitter", "hepsi"):
        try:
            if len(haberler) > 1 or (son_dakika_mi and len(urller) > 1):
                tw_id, tw_adet = twitter.zincir_yayinla(haberler, urller, ayarlar, son_dakika=son_dakika_mi)
            else:
                tw_id = twitter.tekil_yayinla(haberler[0], urller, ayarlar)
            if tw_id:
                con.execute("UPDATE haberler SET twitter_post_id = ? WHERE telegram_message_id = ?", (tw_id, mesaj_id))
                con.commit()
                tw_url = twitter.post_baglantisi(tw_id)
                sonuclar.append(f"🐦 <b>X (Twitter):</b> Başarıyla paylaşıldı!")
                if tw_url:
                    canli_linkler.append([{"text": "🐦 X'te Gör", "url": tw_url}])
            else:
                sonuclar.append("⚠️ <b>X (Twitter):</b> Yayınlanamadı (API hatası).")
        except Exception as e:
            log.exception("Twitter telafi hatası: %s", e)
            sonuclar.append(f"⚠️ <b>X (Twitter):</b> Başarısız ({type(e).__name__}: {str(e)[:80]})")

    # 5. INSTAGRAM POST TELAFİSİ
    if kanal in ("ig", "hepsi"):
        try:
            post_id = instagram.carousel_yayinla(urller, metin, ayarlar)
            con.execute("UPDATE haberler SET ig_post_id = ? WHERE telegram_message_id = ?", (post_id, mesaj_id))
            con.commit()
            ig_url = instagram.post_baglantisi(post_id, ayarlar)
            sonuclar.append(f"📸 <b>Instagram Gönderisi:</b> Başarıyla yayınlandı!")
            if ig_url:
                canli_linkler.append([{"text": "📸 Instagram'da Gör", "url": ig_url}])
        except Exception as e:
            log.exception("Instagram telafi hatası: %s", e)
            sonuclar.append(f"⚠️ <b>Instagram:</b> Başarısız ({type(e).__name__}: {str(e)[:80]})")

    # 6. INSTAGRAM REELS TELAFİSİ
    if kanal in ("reels",):
        try:
            from src import video
            dikey_gorseller = video.reels_dikey_gorselleri_uret(urller, haberler=haberler, ayarlar=ayarlar)
            if not dikey_gorseller:
                raise RuntimeError("Reels videosu için 9:16 görsel üretilemedi")

            video_yolu = video.slaytlardan_reels_uret(dikey_gorseller, fps=30, slayt_suresi=3.5, gecis_suresi=0.5)
            video_url = upload_image.video_yukle(video_yolu, ayarlar)
            kapak_url = urller[0] if urller else None
            post_id = instagram.reels_yayinla(video_url, metin, ayarlar, kapak_url=kapak_url)
            con.execute("UPDATE haberler SET ig_post_id = ? WHERE telegram_message_id = ?", (post_id, mesaj_id))
            con.commit()
            ig_url = instagram.post_baglantisi(post_id, ayarlar)
            sonuclar.append("🎬 <b>Instagram Reels:</b> Başarıyla yayınlandı!")
            if ig_url:
                canli_linkler.append([{"text": "🎬 Reels'i Gör", "url": ig_url}])
            try:
                telegram_bot.video_gonder(
                    video_yolu,
                    aciklama=f"🎬 <b>Daily Brief Reels Videosu Yayında!</b>\n\n🔗 {ig_url or 'Instagram Reels'}",
                )
            except Exception:
                pass
        except Exception as e:
            log.exception("Reels telafi hatası: %s", e)
            sonuclar.append(f"⚠️ <b>Instagram Reels:</b> Başarısız ({type(e).__name__}: {str(e)[:80]})")

    # 7. YOUTUBE SHORTS TELAFİSİ
    if kanal in ("youtube", "hepsi"):
        try:
            from src import youtube, video
            dikey_gorseller = video.reels_dikey_gorselleri_uret(urller, haberler=haberler, ayarlar=ayarlar)
            video_yolu = video.slaytlardan_reels_uret(dikey_gorseller, fps=30, slayt_suresi=3.5, gecis_suresi=0.5)
            h0 = dict(haberler[0]) if haberler else {}
            baslik_yt = h0.get("ig_baslik") or h0.get("baslik_orj") or "Günün Gelişmeleri"
            yt_res = youtube.shorts_yukle(video_yolu, baslik=baslik_yt, aciklama=metin, ayarlar=ayarlar)
            if yt_res.get("durum"):
                con.execute("UPDATE haberler SET youtube_post_id = ? WHERE telegram_message_id = ?", (yt_res.get("url"), mesaj_id))
                con.commit()
                sonuclar.append(f"▶️ <b>YouTube Shorts:</b> Başarıyla yüklendi! ({yt_res.get('url')})")
                if yt_res.get("url"):
                    canli_linkler.append([{"text": "▶️ Shorts'ta Gör", "url": yt_res.get("url")}])
            else:
                sonuclar.append(f"⚠️ <b>YouTube Shorts:</b> Başarısız ({yt_res.get('hata', '')[:80]})")
        except Exception as e:
            log.exception("YouTube Shorts telafi hatası: %s", e)
            sonuclar.append(f"⚠️ <b>YouTube Shorts:</b> Başarısız ({type(e).__name__}: {str(e)[:80]})")

    # 8. TIKTOK TELAFİSİ
    if kanal in ("tiktok", "hepsi"):
        try:
            from src import tiktok, video
            dikey_gorseller = video.reels_dikey_gorselleri_uret(urller, haberler=haberler, ayarlar=ayarlar)
            video_yolu = video.slaytlardan_reels_uret(dikey_gorseller, fps=30, slayt_suresi=3.5, gecis_suresi=0.5)
            h0 = dict(haberler[0]) if haberler else {}
            baslik_tt = h0.get("ig_baslik") or h0.get("baslik_orj") or "Günün Gelişmeleri"
            tt_res = tiktok.video_yukle(video_yolu, baslik=baslik_tt, ayarlar=ayarlar)
            if tt_res.get("durum"):
                con.execute("UPDATE haberler SET tiktok_post_id = ? WHERE telegram_message_id = ?", (tt_res.get("publish_id"), mesaj_id))
                con.commit()
                sonuclar.append("🎵 <b>TikTok Videosu:</b> Başarıyla yüklendi!")
            else:
                sonuclar.append(f"⚠️ <b>TikTok:</b> Başarısız ({tt_res.get('hata', '')[:80]})")
        except Exception as e:
            log.exception("TikTok telafi hatası: %s", e)
            sonuclar.append(f"⚠️ <b>TikTok:</b> Başarısız ({type(e).__name__}: {str(e)[:80]})")

    # Kalan eksik platformlar için telafi butonlarını topla — böylece diğer seçenekler ASLA kaybolmaz
    kalan_haberler = turu_getir(con, mesaj_id) or haberler
    k_story = next((h["story_post_id"] for h in kalan_haberler if h["story_post_id"]), None)
    k_fb = next((h["facebook_post_id"] for h in kalan_haberler if h["facebook_post_id"]), None)
    k_th = next((h["threads_post_id"] for h in kalan_haberler if h["threads_post_id"]), None)
    k_tw = next((h["twitter_post_id"] for h in kalan_haberler if "twitter_post_id" in h.keys() and h["twitter_post_id"]), None)
    k_yt = next((h["youtube_post_id"] for h in kalan_haberler if "youtube_post_id" in h.keys() and h["youtube_post_id"]), None)
    k_tt = next((h["tiktok_post_id"] for h in kalan_haberler if "tiktok_post_id" in h.keys() and h["tiktok_post_id"]), None)

    kalan_telafi_butonlari = []
    if not k_story:
        kalan_telafi_butonlari.append([{"text": "🔄 📱 Story'i Yayınla", "callback_data": f"retry_kanal:story:{mesaj_id}"}])
    if not k_fb and bool((ayarlar.get("sosyal", {}) or {}).get("facebooka_da_at")):
        kalan_telafi_butonlari.append([{"text": "🔄 📘 Facebook'a Gönder", "callback_data": f"retry_kanal:facebook:{mesaj_id}"}])
    if not k_th and bool((ayarlar.get("sosyal", {}) or {}).get("threadse_de_at")):
        kalan_telafi_butonlari.append([{"text": "🔄 🧵 Threads'e Gönder", "callback_data": f"retry_kanal:threads:{mesaj_id}"}])
    if not k_tw and bool((ayarlar.get("sosyal", {}) or {}).get("twittera_da_at")):
        kalan_telafi_butonlari.append([{"text": "🔄 🐦 X'e Gönder", "callback_data": f"retry_kanal:twitter:{mesaj_id}"}])
    if not k_yt and bool((ayarlar.get("sosyal", {}) or {}).get("youtubea_da_at")):
        kalan_telafi_butonlari.append([{"text": "🔄 ▶️ Shorts'a Yükle", "callback_data": f"retry_kanal:youtube:{mesaj_id}"}])
    if not k_tt and bool((ayarlar.get("sosyal", {}) or {}).get("tiktoka_da_at")):
        kalan_telafi_butonlari.append([{"text": "🔄 🎵 TikTok'a Yükle", "callback_data": f"retry_kanal:tiktok:{mesaj_id}"}])

    if len(kalan_telafi_butonlari) > 1:
        kalan_telafi_butonlari.insert(0, [{"text": "🔄 Kalan Tüm Kanalları Yayınla", "callback_data": f"retry_kanal:hepsi:{mesaj_id}"}])

    kontrol_butonu = [[{"text": "🔍 Yayın Durumunu Kontrol Et", "callback_data": f"yayin_kontrol:{mesaj_id}"}]]
    tum_butonlar = (canli_linkler or []) + kalan_telafi_butonlari + kontrol_butonu

    rapor = "\n".join(sonuclar)
    telegram_bot.mesaj_gonder(
        f"🛠️ <b>PLATFORM TELAFİ İŞLEMİ RAPORU</b>\n\n"
        f"İşlemi Yapan: {basan or 'Bilinmiyor'}\n"
        f"Hedef Tur: #{mesaj_id}\n\n"
        f"{rapor}",
        html=True,
        butonlar=tum_butonlar if tum_butonlar else None
    )
    return 0


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

    Ana panele dönmek bilinçli: değer değiştikten sonra alt menüde
    kalmak, kullanıcıyı bir tık daha "geri" basmaya zorluyor. Panelde
    yeni değer zaten görünüyor.
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
        telegram_bot.paneli_tazele(
            mesaj_id,
            ayar.panel_metni(con, ayarlar)
            + f"\n\nSon değişiklik: {etiket} → {gosterim}"
            f"  ({basan or 'bilinmiyor'})",
            ayar.panel_butonlari(con, ayarlar),
        )
    except Exception as e:
        log.warning("panel tazelenemedi: %s", e)

    # Ayar değişikliği veritabanında; runner'lar arasında taşınması için
    # hemen push ediliyor, yoksa sonraki job eski değeri okur.
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


def yonetim_kota_raporu_uygula(con, ayarlar: dict, mesaj_id: int | None) -> int:
    """Canlı kota ve durum raporunu Telegram'a gönderir."""
    metin = yonetim.kota_ve_durum_raporu(con, ayarlar)
    klavye = {"inline_keyboard": [[{"text": "← Yönetim Paneline Dön", "callback_data": "yonetim_panel"}]]}
    if mesaj_id:
        telegram_bot.mesaji_guncelle(mesaj_id, metin, klavye)
    else:
        telegram_bot.mesaj_gonder(metin, html=True, butonlar=klavye["inline_keyboard"])
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

    ⚠️ INSTAGRAM API'DEN SİLİNEMİYOR. Graph API yayınlanmış postu silmeye
    izin vermiyor (denendi: `(#10) Insufficient permissions`); orada silme
    yalnızca uygulamadan yapılabiliyor. Bu yüzden Instagram için yalnızca
    bağlantı gösteriliyor ve elle silinmesi isteniyor.

    Facebook ve Threads API'den siliniyor.

    HABER ELENİYOR: kaldırılan tur `durum='kaldirildi'` oluyor, havuza
    DÖNMÜYOR. Bir postu geri alıyorsak o haberi bir daha yayınlamak
    istemiyoruz demektir; havuza dönerse ertesi gün yeniden çıkardı.
    """
    if not any(h["durum"] == "yayinlandi" for h in haberler):
        telegram_bot.mesaj_gonder("⚠️ Bu tur yayınlanmamış, kaldırılacak bir şey yok.")
        return 0

    ilk = haberler[0]
    satirlar = []

    # --- Facebook ---
    fb = ilk["facebook_post_id"]
    if fb:
        if facebook.postu_sil(fb, ayarlar):
            satirlar.append("📘 Facebook postu silindi")
        else:
            satirlar.append("⚠️ Facebook postu silinemedi")
    else:
        satirlar.append("· Facebook: kayıtlı post id yok")

    # --- Threads ---
    th = ilk["threads_post_id"]
    if th:
        try:
            silinen, toplam = threads.zinciri_sil(th)
            satirlar.append(f"🧵 Threads zinciri silindi ({silinen}/{toplam} gönderi)")
        except Exception as e:
            satirlar.append(f"⚠️ Threads silinemedi: {type(e).__name__}")
    else:
        satirlar.append("· Threads: kayıtlı gönderi id yok")

    # --- Instagram: elle ---
    ig = ilk["ig_post_id"]
    baglanti = instagram.post_baglantisi(ig, ayarlar) if ig else ""
    satirlar.append(
        "\n📷 Instagram'dan ELLE silmen gerekiyor — Graph API yayınlanmış "
        "postu silmeye izin vermiyor:\n" + (baglanti or f"post id: {ig}")
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
    # Haberler ELENMİYOR: havuza dönüp sonraki turda yeniden yarışıyorlar.
    #
    # METNİ OLAN HABER 'metin_hazir'E DÖNÜYOR, 'yeni'YE DEĞİL.
    # 'yeni' yapılırsa sonraki tur onu metni yokmuş gibi görüp Gemini'ye
    # tekrar gönderiyor: kota boşa gidiyor ve çağrı hata alırsa haber
    # 'hata' durumunda kalıp havuzdan düşüyor. 17 Ağu 2026'da tam olarak
    # bu oldu — iptal edilen haber bir daha aday olamadı.
    con.execute(
        "UPDATE haberler SET telegram_message_id = NULL, son_dakika = 0, "
        "ertelenme_sayisi = COALESCE(ertelenme_sayisi, 0) + 1, "
        # ⚠️ Haber 12 saat yeniden aday olmuyor (`atlanan_bekleme_saat`).
        # Skor cezası dar havuzda yetmiyordu: atlanan 10 haberin 5'i bir
        # sonraki turda geri geliyordu. `ertele` bunu YAZMIYOR — orada
        # kullanıcı yayınlamak istiyor, sadece bekletiyor.
        "atlanma_zamani = datetime('now'), "
        "durum = CASE WHEN ig_baslik IS NOT NULL THEN 'metin_hazir' "
        "             ELSE 'yeni' END "
        "WHERE telegram_message_id = ?",
        (mesaj_id,),
    )

    # ⚠️ İKİ KEZ ATLANAN HABER BİR DAHA TEKİL SUNULMUYOR.
    #
    # 20 Ağu 2026: "Türkiye'de yağışlar son 66 yılın zirvesinde" haberi
    # üç kez tekil post olarak onaya düştü. Kullanıcı her seferinde
    # "atla" dedi, haber havuza döndü ve bir sonraki kontrolde YİNE
    # aday oldu — kısır döngü. "Onay verilmezse haber ELENMEZ" kararı
    # doğru ama ısrar etmek yanlış: ikinci atlamadan sonra haber
    # yalnızca 10'lu turda yarışıyor.
    #
    # Turda hâlâ görünüyor, yani haber kaybolmuyor; sadece tekil post
    # olarak dayatılmıyor.
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


def ertele(con, mesaj_id, basan) -> int:
    """
    Turu 1 saat erteler. Tur KAPANMIYOR — sadece bekliyor.

    ⚠️ BURADA `sonucu_yaz` KULLANMA. O fonksiyon butonları kaldırıyor
    (çift yayını engellemek için, doğru davranış) ama ertelemede tur
    devam ediyor. 20 Ağu 2026'da tam bu oldu: kullanıcı 20:58'de
    "1 saat ertele" dedi, menü silindi, 21:58'de gelen hatırlatma
    "yukarıdaki mesajdan yayınlayabilirsin" dedi ama o mesajda artık
    hiçbir düğme yoktu. Tur kilitlendi — ne yayınlanabiliyor ne
    atlanabiliyordu.

    Doğrusu: menü yerinde kalsın, erteleme AYRI bir mesajla bildirilsin.
    """
    con.execute(
        "UPDATE haberler SET durum = 'ertelendi', "
        "ertelenme_sayisi = COALESCE(ertelenme_sayisi, 0) + 1 "
        "WHERE telegram_message_id = ?",
        (mesaj_id,),
    )
    con.commit()
    # Worker butona basıldığında menüyü kaldırmıştı; geri koyuyoruz.
    menuyu_geri_koy(con, mesaj_id)
    telegram_bot.mesaj_gonder(
        f"⏰ 1 saat ertelendi ({basan or 'bilinmiyor'}).\n"
        "Tur açık kalıyor — yukarıdaki mesajdan istediğin an "
        "yayınlayabilirsin."
    )
    return 0


def havuzu_guncelle(con, ayarlar) -> int:
    """
    RSS kaynaklarını hemen tarar — bir sonraki cron'u beklemeden.

    Kullanıcı isteği (21 Ağu 2026): *"yardım sekmesine veritabanı
    güncelle / haber havuzunu güncelle gibisinden komut ekleyelim"*.
    Sebep somuttu: sabah duyduğu bir haberi aradı, havuzda yoktu ve
    kontrolün çalışmasını beklemek zorunda kaldı.

    ⚠️ METİN ÜRETMİYOR, yalnızca RSS çekiyor. Gemini kotası günde 20
    ücretsiz istekle sınırlı; elle tetiklenen her güncellemenin metin
    üretmesi kotayı hızla bitirir. Çekilen haberler `durum='yeni'`
    olarak havuza giriyor ve `/haber` aramasında ZATEN görünüyorlar —
    metin, kullanıcı bir haberi seçtiğinde üretiliyor.
    """
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

    # 1. Instagram Feed
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

    # 2. Story
    if story_id:
        satirlar.append(f"📱 <b>Story:</b> ✅ Yayında (ID: {story_id})")
    else:
        satirlar.append("📱 <b>Story:</b> ⚠️ Yayınlanmadı / Bilgi Yok")

    # 3. Facebook
    if fb_id:
        satirlar.append(f"📘 <b>Facebook:</b> ✅ Yayında (ID: {fb_id})")
    else:
        satirlar.append("📘 <b>Facebook:</b> ⚠️ Yayınlanmadı / Kayıt Yok")

    # 4. Threads
    if th_id:
        satirlar.append(f"🧵 <b>Threads:</b> ✅ Yayında (ID: {th_id})")
    else:
        satirlar.append("🧵 <b>Threads:</b> ⚠️ Yayınlanmadı / Kayıt Yok")

    # 5. X (Twitter)
    if tw_id:
        satirlar.append(f"🐦 <b>X (Twitter):</b> ✅ Yayında (ID: {tw_id})")
    else:
        satirlar.append("🐦 <b>X (Twitter):</b> ⚠️ Yayınlanmadı / Kayıt Yok")

    # 6. YouTube Shorts
    if yt_id:
        satirlar.append(f"▶️ <b>YouTube Shorts:</b> ✅ Yayında ({yt_id})")
    else:
        satirlar.append("▶️ <b>YouTube Shorts:</b> ⚠️ Yayınlanmadı / Kayıt Yok")

    # 7. TikTok
    if tt_id:
        satirlar.append(f"🎵 <b>TikTok:</b> ✅ Yüklendi (ID: {tt_id})")
    else:
        satirlar.append("🎵 <b>TikTok:</b> ⚠️ Yayınlanmadı / Kayıt Yok")

    # Telafi Butonları — Yalnızca yukarıda eksik (⚠️) görünen kanallar için eklenir
    tuslar = []
    if not story_id:
        tuslar.append([{"text": "🔄 📱 Story'i Yayınla / Telafi Et", "callback_data": f"retry_kanal:story:{mesaj_id}"}])
    if not fb_id and bool((ayarlar.get("sosyal", {}) or {}).get("facebooka_da_at")):
        tuslar.append([{"text": "🔄 📘 Facebook'a Gönder", "callback_data": f"retry_kanal:facebook:{mesaj_id}"}])
    if not th_id and bool((ayarlar.get("sosyal", {}) or {}).get("threadse_de_at")):
        tuslar.append([{"text": "🔄 🧵 Threads'e Gönder", "callback_data": f"retry_kanal:threads:{mesaj_id}"}])
    if not tw_id and bool((ayarlar.get("sosyal", {}) or {}).get("twittera_da_at")):
        tuslar.append([{"text": "🔄 🐦 X'e Gönder", "callback_data": f"retry_kanal:twitter:{mesaj_id}"}])
    if not yt_id and bool((ayarlar.get("sosyal", {}) or {}).get("youtubea_da_at")):
        tuslar.append([{"text": "🔄 ▶️ Shorts'a Yükle", "callback_data": f"retry_kanal:youtube:{mesaj_id}"}])
    if not tt_id and bool((ayarlar.get("sosyal", {}) or {}).get("tiktoka_da_at")):
        tuslar.append([{"text": "🔄 🎵 TikTok'a Yükle", "callback_data": f"retry_kanal:tiktok:{mesaj_id}"}])
    if not ig_var:
        tuslar.append([{"text": "🔄 📸 Instagram Postunu Yayınla", "callback_data": f"retry_kanal:ig:{mesaj_id}"}])

    if len(tuslar) > 1:
        tuslar.insert(0, [{"text": "🔄 Eksik Tüm Kanalları Yayınla", "callback_data": f"retry_kanal:hepsi:{mesaj_id}"}])

    telegram_bot.mesaj_gonder("\n".join(satirlar), html=True, butonlar=tuslar if tuslar else None)
    return 0


def yeniden_yayinla(con, ayarlar, mesaj_id: int, basan) -> int:
    """
    Yayınlanamamış bir turu yeniden yayınlar.

    ⚠️ ÖNCE INSTAGRAM'A SORUYOR. Çift yayın, yayınlanamamaktan çok daha
    kötü: takipçi aynı postu iki kez görüyor ve Instagram'dan API ile
    silinemiyor (Graph API izin vermiyor, yalnızca uygulamadan).
    Veritabanı "yayınlanmadı" dese bile Instagram'da post varsa
    yayınlamıyoruz.
    """
    haberler = turu_getir(con, mesaj_id)
    if not haberler:
        telegram_bot.mesaj_gonder("⚠️ Tur bulunamadı.")
        return 0
    if haberler[0]["durum"] == "yayinlandi":
        post = next((h["ig_post_id"] for h in haberler if h["ig_post_id"]), None)
        telegram_bot.mesaj_gonder(
            "✅ Bu tur zaten yayınlanmış, tekrar yayınlanmadı.\n"
            f"{instagram.post_baglantisi(post, ayarlar) if post else ''}")
        return 0

    try:
        gecmis = instagram.son_yayinlanan_basliklar(ayarlar)
        for h in haberler:
            kel, ozel = secim.konu_imzasi(h["ig_baslik"] or h["baslik_orj"] or "")
            for g in gecmis:
                gk, go = secim.konu_imzasi(g)
                if (len(secim.ortak_kelime(kel, gk)) >= 3
                        and secim.ortak_kelime(ozel, go)):
                    telegram_bot.mesaj_gonder(
                        "⚠️ Bu haber Instagram'da ZATEN VAR, tekrar "
                        f"yayınlanmadı:\n«{g[:70]}»\n\n"
                        "Veritabanı kaydı bozulmuş olabilir.")
                    return 0
    except Exception as e:                            # noqa: BLE001
        # Instagram'a ulaşılamıyorsa yayınlamıyoruz: çift yayın riski
        # belirsizlikten daha pahalı.
        telegram_bot.mesaj_gonder(
            f"⚠️ Instagram'a sorulamadı ({type(e).__name__}), çift yayın "
            "riskine karşı yayınlanmadı. Biraz sonra tekrar dene.")
        return 0

    telegram_bot.mesaj_gonder("🔄 Yeniden yayınlanıyor…")
    return yayinla(con, ayarlar, haberler, mesaj_id, basan or "tekrar")


def tur_onayla(con, ayarlar, haberler, mesaj_id) -> int:
    """
    Başlıkları onaylanan tur için slaytları üretir ve tam onaya sunar.

    Bu, iki aşamalı tur akışının ikinci yarısı: `hazirla.py` önce
    yalnızca başlıkları gönderiyor (görsel üretmeden), kullanıcı
    onaylayınca slaytlar burada üretiliyor.

    ⚠️ ~60 SANİYE SÜRÜYOR. Worker düğmeye basıldığı an "⏳" yazıyor;
    o yüzden burada ayrıca bilgi mesajı gönderiliyor, kullanıcı
    sessizlikte ikinci kez basmasın.
    """
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

    # Haberleri onay mesajından ÇÖZ: `turu_tamamla` kendi mesajını
    # oluşturup yeni id'yi yazacak. Bağlı bırakırsak iki mesaj aynı
    # turu işaret eder ve `turu_getir` ikisini karıştırır.
    con.execute(
        "UPDATE haberler SET telegram_message_id = NULL, durum = 'metin_hazir' "
        "WHERE telegram_message_id = ?", (mesaj_id,))
    con.commit()

    sys.path.insert(0, str(KOK / "scripts"))
    import hazirla                                    # noqa: E402
    return hazirla.turu_tamamla(con, ayarlar, list(haberler))


def tur_yeniden_sec(con, ayarlar, haberler, mesaj_id) -> int:
    """
    Başlık listesini beğenmeyip başka haberler ister.

    Mevcut seçim havuza dönüyor ve `sadece_tur` işareti KONMUYOR —
    haberler elenmedi, sadece bu listede istenmedi. Ama aynı haberlerin
    hemen tekrar seçilmemesi için `ertelenme_sayisi` artırılıyor.
    """
    con.execute(
        "UPDATE haberler SET telegram_message_id = NULL, "
        "durum = 'metin_hazir', "
        "ertelenme_sayisi = COALESCE(ertelenme_sayisi, 0) + 1, "
        # Bu liste istenmedi: haberler 12 saat yeniden aday olmuyor,
        # yoksa "başka haberler" düğmesi aynı listeyi geri getirir.
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


def yayin_planla(con, ayarlar, haberler, dakika: int, mesaj_id, basan,
                 kanallar: str | None = None) -> int:
    """
    Turu ileri bir saate planlar. Yayın o ana kadar YAPILMIYOR.
    """
    an = datetime.now(timezone.utc) + timedelta(minutes=dakika)
    con.execute(
        "UPDATE haberler SET planlanan_yayin = ?, yayin_kanallari = ? "
        "WHERE telegram_message_id = ?",
        (an.isoformat(), kanallar or "", mesaj_id),
    )
    con.commit()
    db_senkron.hemen_kaydet(f"yayın planlandı ({dakika} dk)")

    tr = an.astimezone(timezone(timedelta(hours=3)))
    sure = f"{dakika} dakika" if dakika < 60 else f"{dakika // 60} saat"
    telegram_bot.sonucu_yaz(
        mesaj_id,
        f"🕒 Yayın {sure} sonraya planlandı — "
        f"TR {tr:%H:%M} ({basan or 'bilinmiyor'}).\n"
        f"Kontrol 90 dakikada bir çalıştığı için yayın "
        f"TR {tr:%H:%M}–{(tr + timedelta(minutes=90)):%H:%M} arasında çıkar.\n"
        "Vazgeçersen aşağıdaki düğmeyle planı iptal edebilirsin.",
        butonlar={"inline_keyboard": [
            [{"text": "⏹ Planı iptal et", "callback_data": "plan_iptal"}]]},
    )
    log.info("yayın planlandı: %s (%s dk)", an.isoformat(), dakika)
    return 0


def plani_iptal_et(con, mesaj_id, basan) -> int:
    """Planlanan yayını geri alır; tur normal onay bekler hale döner."""
    con.execute(
        "UPDATE haberler SET planlanan_yayin = NULL "
        "WHERE telegram_message_id = ?", (mesaj_id,))
    con.commit()
    db_senkron.hemen_kaydet("yayın planı iptal edildi")
    telegram_bot.sonucu_yaz(
        mesaj_id,
        f"⏹ Yayın planı iptal edildi ({basan or 'bilinmiyor'}).\n"
        "Tur onay bekliyor.")
    menuyu_geri_koy(con, mesaj_id)
    return 0


def metin_yenile(con, ayarlar, haberler, mesaj_id) -> int:
    """Tüm haberlerin metnini yeniden ürettirir ve slaytları yeniler."""
    con.execute(
        "UPDATE haberler SET durum = 'yeni' WHERE telegram_message_id = ?",
        (mesaj_id,),
    )
    con.commit()
    metinleri_uret(ayarlar=ayarlar, haberler=haberler)

    taze = turu_getir(con, mesaj_id)
    sonuclar = slaytlar.tur_uret(taze, ayarlar, con)
    yuklemeler = upload_image.hepsini_yukle([s["yol"] for s in sonuclar], ayarlar)
    for haber, yukleme in zip(taze, yuklemeler):
        con.execute("UPDATE haberler SET gorsel_url = ?, durum = 'onay_bekliyor' "
                    "WHERE id = ?", (yukleme["url"], haber["id"]))
    con.commit()

    telegram_bot.slaytlari_gonder(
        [y["url"] for y in yuklemeler],
        [h["ig_baslik"] or h["baslik_orj"] for h in taze],
    )
    metin = caption.caption_kur(taze, sonuclar, ayarlar=ayarlar)
    uyari, isaretli = dogrula.turu_dogrula(taze)
    yeni_id = telegram_bot.onay_iste(
        metin, len(yuklemeler),
        uyari=(uyari or "🔄 Metinler yeniden üretildi"),
        ozet=telegram_bot.tur_ozeti(taze, isaretli),
    )
    con.execute("UPDATE haberler SET telegram_message_id = ? "
                "WHERE telegram_message_id = ?", (yeni_id, mesaj_id))
    con.commit()
    telegram_bot.sonucu_yaz(mesaj_id, "🔄 Metinler yeniden üretildi — yeni öneri yukarıda.")
    return 0


def foto_degistir_islemi(con, ayarlar: dict, haberler: list, mesaj_id: int, basan: str = "") -> int:
    """
    Onay bekleyen haberin fotoğrafını sıradaki alternatif HD görselle yeniler ve slaytları baştan çizer.
    """
    if not haberler:
        telegram_bot.mesaj_gonder("⚠️ Fotoğrafı değiştirilecek haber bulunamadı.")
        return 1

    # Tekil / Son dakika haberi
    if len(haberler) == 1 or haberler[0]["son_dakika"]:
        h = haberler[0]
        deneme = (h["gorsel_deneme"] or 0) + 1
        telegram_bot.mesaj_gonder(
            f"🔄 <b>Fotoğraf Yenileniyor...</b>\n\n{h['ig_baslik'] or h['baslik_orj']}\n"
            f"(Alternatif #{deneme + 1} taranıyor ve slaytlar baştan çiziliyor)",
            html=True,
        )

        sonuclar = slaytlar.son_dakika_uret(h, ayarlar, con=con, atlanacak=deneme)
        carousel = [s for s in sonuclar if s["katman"] not in ("story", "story_detay")]
        story_slayt = next((s for s in sonuclar if s["katman"] == "story"), None)
        story_detay_slaytlar = [s for s in sonuclar if s["katman"] == "story_detay"]

        yuklemeler = upload_image.hepsini_yukle([s["yol"] for s in carousel], ayarlar)
        urller = [y["url"] for y in yuklemeler]

        story_url = None
        story_detay_urller = []
        if story_slayt:
            try:
                story_url = upload_image.gorsel_yukle(story_slayt["yol"], ayarlar)["url"]
            except Exception as e:
                log.warning("story yüklenemedi: %s", e)

        for sds in story_detay_slaytlar:
            try:
                sdu = upload_image.gorsel_yukle(sds["yol"], ayarlar)["url"]
                story_detay_urller.append(sdu)
            except Exception as e:
                log.warning("detay story yüklenemedi: %s", e)

        con.execute(
            "UPDATE haberler SET gorsel_url = ?, detay_url = ?, story_url = ?, "
            "gorsel_deneme = ? WHERE id = ?",
            (urller[0], json.dumps(urller[1:]), story_url, deneme, h["id"]),
        )
        con.commit()

        # Telegram albümünü güncelle
        telegram_urller = [story_url] if story_url else [urller[0]]
        if story_detay_urller:
            telegram_urller.extend(story_detay_urller)
        elif len(urller) > 1:
            telegram_urller.extend(urller[1:])

        etiketler = []
        for idx in range(len(telegram_urller)):
            if idx == 0:
                etiketler.append("Haber (Yeni Görsel)")
            elif len(telegram_urller) == 2:
                etiketler.append("Ayrıntı")
            else:
                etiketler.append(f"Ayrıntı {idx}/{len(telegram_urller)-1}")

        telegram_bot.slaytlari_gonder(telegram_urller, etiketler)
        telegram_bot.sonucu_yaz(mesaj_id, f"✅ <b>Fotoğraf Güncellendi</b> (Alternatif #{deneme + 1} uygulandı)")
        menuyu_geri_koy(con, mesaj_id)
        return 0
    else:
        # Çoklu tur: Kullanıcıya hangi slaytı değiştirmek istediğini sor
        telegram_bot.menuyu_degistir(mesaj_id, telegram_bot.slayt_secim_menusu(len(haberler)))
        return 0


def slayt_islemi(con, ayarlar, haberler, komut, sira, mesaj_id) -> int:
    """
    Tek bir slayta müdahale eder.

    SON DAKİKA TURUNDA SLAYT ≠ HABER: tek haberden 2-5 slayt üretiliyor
    (1 haber + 1-4 ayrıntı sayfası). Menü slayt sayısına göre kuruluyor
    ama burada haber listesine bakılıyordu; "3. slaytı değiştir" deyince
    "bu slayt yok" hatası veriyordu.

    Son dakika turunda bütün slaytlar aynı haberden geldiği için hangi
    numaraya basılırsa basılsın o haber üzerinde işlem yapıyoruz.
    """
    son_dakika_turu = len(haberler) == 1 and haberler[0]["son_dakika"]

    if son_dakika_turu:
        haber = haberler[0]
        if komut in ("slayt_foto", "slayt_ai") and sira > 1:
            # Ayrıntı sayfalarında fotoğraf yok, sade zemin var.
            telegram_bot.mesaj_gonder(
                f"ℹ️ {sira}. slayt ayrıntı sayfası — orada fotoğraf yok, "
                f"sade zemin kullanılıyor. Fotoğrafı 1. slaytta değiştirebilirsin."
            )
            return 0
    elif not 1 <= sira <= len(haberler):
        telegram_bot.mesaj_gonder(
            f"⚠️ {sira}. slayt yok (turda {len(haberler)} slayt var)."
        )
        return 0
    else:
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

    if komut == "slayt_elle":
        telegram_bot.mesaj_gonder(
            f"✍️ <b>{sira}. Slaytın Başlık ve Metnini Elle Düzenleme</b>\n\n"
            f"Mevcut Başlık: <i>{html.escape(haber['ig_baslik'] or haber['baslik_orj'] or '')}</i>\n"
            f"Mevcut Özet: <i>{html.escape(haber['slayt_ozet'] or haber['ozet_orj'] or '')}</i>\n\n"
            f"Bu mesaja <b>Yanıtla (Reply)</b> yaparak yeni metni yazabilirsin:\n"
            f"• <b>Sadece Yeni Başlık:</b> <code>{sira}: Yeni Başlık Metni</code>\n"
            f"• <b>Başlık + Açıklama:</b> <code>{sira}: Yeni Başlık | Yeni Açıklama Metni</code>\n\n"
            f"<i>(Yazıp gönderdiğinde slayt otomatik güncellenecektir.)</i>",
            html=True,
        )
        menuyu_geri_koy(con, mesaj_id)
        return 0

    if komut == "slayt_sil":
        if son_dakika_turu:
            telegram_bot.mesaj_gonder(
                "ℹ️ Son dakika turu tek haberden oluşuyor; slayt çıkarılamaz. "
                "Beğenmediysen '❌ Bu turu atla' diyebilirsin."
            )
            return 0
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
        _albumu_yenile(con, mesaj_id)
        menuyu_geri_koy(con, mesaj_id)
        return 0

    if komut == "cope_at_tekil":
        con.execute(
            "UPDATE haberler SET durum = 'iptal', telegram_message_id = NULL, "
            "atlanma_zamani = datetime('now') WHERE id = ?",
            (haber["id"],),
        )
        con.commit()
        kalan = len(haberler) - 1
        if kalan == 0:
            telegram_bot.sonucu_yaz(
                mesaj_id,
                f"🗑️ <b>Haber tamamen çöpe atıldı</b> (iptal edildi, havuza dönmeyecek).",
            )
            return 0
        telegram_bot.mesaj_gonder(
            f"🗑️ <b>{sira}. slayttaki haber tamamen çöpe atıldı</b> (iptal edildi, havuza dönmeyecek).\n"
            f"Kalan slayt sayısı: {kalan}",
            html=True,
        )
        _albumu_yenile(con, mesaj_id)
        menuyu_geri_koy(con, mesaj_id)
        return 0

    if komut == "sansur_kaldir":
        yeni_baslik = (haber["ig_baslik"] or "").replace("*", "")
        yeni_ozet = (haber["slayt_ozet"] or "").replace("*", "")
        con.execute(
            "UPDATE haberler SET ig_baslik = ?, slayt_ozet = ? WHERE id = ?",
            (yeni_baslik, yeni_ozet, haber["id"]),
        )
        con.commit()
        taze = con.execute("SELECT * FROM haberler WHERE id = ?", (haber["id"],)).fetchone()
        yol, katman, atif = slaytlar.slayt_uret(taze, ayarlar)
        yukleme = upload_image.gorsel_yukle(yol, ayarlar)
        story_yol = make_image.CIKTI_KLASORU / f"story-{haber['id']}.jpg"
        story_url = yukleme["url"]
        if story_yol.exists():
            try:
                story_yukleme = upload_image.gorsel_yukle(story_yol, ayarlar)
                story_url = story_yukleme.get("url") or story_url
            except Exception as e:
                log.warning("Story görseli yüklenemedi: %s", e)
        con.execute(
            "UPDATE haberler SET gorsel_url = ?, story_url = ?, gorsel_yolu = ? WHERE id = ?",
            (yukleme["url"], story_url, str(yol), haber["id"]),
        )
        con.commit()
        telegram_bot.mesaj_gonder(f"🧹 <b>{sira}. slayttaki sansürler (* işaretleri) kaldırıldı.</b>", html=True)
        _albumu_yenile(con, mesaj_id)
        return 0

    if komut == "sansur_uygula":
        f = (ayarlar or {}).get("icerik_filtresi", {})
        kelimeler = f.get("yumusatilacak", [])
        yeni_baslik = filtre.metni_yumusat(haber["ig_baslik"] or "", kelimeler)
        yeni_ozet = filtre.metni_yumusat(haber["slayt_ozet"] or "", kelimeler)
        con.execute(
            "UPDATE haberler SET ig_baslik = ?, slayt_ozet = ? WHERE id = ?",
            (yeni_baslik, yeni_ozet, haber["id"]),
        )
        con.commit()
        taze = con.execute("SELECT * FROM haberler WHERE id = ?", (haber["id"],)).fetchone()
        yol, katman, atif = slaytlar.slayt_uret(taze, ayarlar)
        yukleme = upload_image.gorsel_yukle(yol, ayarlar)
        story_yol = make_image.CIKTI_KLASORU / f"story-{haber['id']}.jpg"
        story_url = yukleme["url"]
        if story_yol.exists():
            try:
                story_yukleme = upload_image.gorsel_yukle(story_yol, ayarlar)
                story_url = story_yukleme.get("url") or story_url
            except Exception as e:
                log.warning("Story görseli yüklenemedi: %s", e)
        con.execute(
            "UPDATE haberler SET gorsel_url = ?, story_url = ?, gorsel_yolu = ? WHERE id = ?",
            (yukleme["url"], story_url, str(yol), haber["id"]),
        )
        con.commit()
        telegram_bot.mesaj_gonder(f"🛡️ <b>{sira}. slayta hassas kelime filtresi uygulandı.</b>", html=True)
        _albumu_yenile(con, mesaj_id)
        return 0

    if komut in ("metin_uzat", "metin_kisalt"):
        try:
            from src.generate_text import _model_ve_anahtar_dene
            mevcut = haber["slayt_ozet"] or haber["ig_metin"] or haber["baslik_orj"]
            if komut == "metin_uzat":
                istek = f"Bu haber özetini daha detaylı ve açıklayıcı şekilde 2-3 cümleyle genişlet (en fazla 40 kelime):\n{mevcut}"
            else:
                istek = f"Bu haber özetini çok daha vurucu ve kısa tek bir cümleye indirge (en fazla 15 kelime):\n{mevcut}"
            yeni_metin, _, _ = _model_ve_anahtar_dene(istek)
            if yeni_metin:
                yeni_metin = yeni_metin.strip().replace("\n", " ")
                con.execute(
                    "UPDATE haberler SET slayt_ozet = ?, ig_metin = ? WHERE id = ?",
                    (yeni_metin, yeni_metin, haber["id"]),
                )
                con.commit()
                taze = con.execute("SELECT * FROM haberler WHERE id = ?", (haber["id"],)).fetchone()
                yol, katman, atif = slaytlar.slayt_uret(taze, ayarlar)
                yukleme = upload_image.gorsel_yukle(yol, ayarlar)
                story_yol = make_image.CIKTI_KLASORU / f"story-{haber['id']}.jpg"
                story_url = yukleme["url"]
                if story_yol.exists():
                    try:
                        story_yukleme = upload_image.gorsel_yukle(story_yol, ayarlar)
                        story_url = story_yukleme.get("url") or story_url
                    except Exception as e:
                        log.warning("Story görseli yüklenemedi: %s", e)
                con.execute(
                    "UPDATE haberler SET gorsel_url = ?, story_url = ?, gorsel_yolu = ? WHERE id = ?",
                    (yukleme["url"], story_url, str(yol), haber["id"]),
                )
                con.commit()
                telegram_bot.mesaj_gonder(
                    f"✍️ <b>{sira}. slaytın metni {'genişletildi' if komut == 'metin_uzat' else 'kısaltıldı'}:</b>\n"
                    f"<i>{html.escape(yeni_metin)}</i>",
                    html=True,
                )
                _albumu_yenile(con, mesaj_id)
                return 0
        except Exception as e:
            log.warning("Metin uzat/kısalt hatası: %s", e)

    if komut == "slayt_carpici":
        eski_baslik = haber["ig_baslik"] or haber["baslik_orj"] or ""
        eski_ozet = haber["slayt_ozet"] or haber["ozet_orj"] or ""
        govde = (haber["makale_metni"] or haber["ozet_orj"] or eski_baslik).strip()

        prompt = (
            "Sen Türkiye'nin en popüler sosyal medya haber yayınının (Daily Brief) "
            "kıdemli genel yayın yönetmenisin. Aşağıdaki haberin başlığını ve spotunu, "
            "Instagram ve sosyal medyada kullanıcıların dikkatini ilk saniyede çekecek, "
            "merak uyandıran, son derece güçlü, vurucu ve profesyonel bir manşet olarak YENİDEN YAZ.\n\n"
            "KURALLAR:\n"
            "1. Haberdeki gerçek bilgileri asla çarpıtma veya uydurma.\n"
            "2. Başlık (ig_baslik): En fazla 8-10 kelime, vurucu, aktif fiilli, büyük etki ve merak yaratan manşet.\n"
            "3. Slayt Özeti (slayt_ozet): 15-25 kelime, olayın can alıcı noktasını net ve akıcı anlatan 1-2 cümle.\n\n"
            f"KAYNAK: {haber['kaynak']}\n"
            f"MEVCUT BAŞLIK: {eski_baslik}\n"
            f"HABER DETAYI: {govde[:2500]}\n\n"
            "Yalnızca şu JSON formatında yanıt ver:\n"
            "{\n"
            '  "ig_baslik": "...",\n'
            '  "slayt_ozet": "..."\n'
            "}"
        )

        try:
            from src.generate_text import _model_ve_anahtar_dene
            yanit, _, _ = _model_ve_anahtar_dene(prompt)
            if yanit:
                temiz = yanit.strip()
                if "```json" in temiz:
                    temiz = temiz.split("```json", 1)[1].split("```", 1)[0].strip()
                elif "```" in temiz:
                    temiz = temiz.split("```", 1)[1].split("```", 1)[0].strip()

                veri = json.loads(temiz)
                yeni_baslik = veri.get("ig_baslik", "").strip()
                yeni_ozet = veri.get("slayt_ozet", "").strip()

                if yeni_baslik:
                    con.execute(
                        "UPDATE haberler SET ig_baslik = ?, slayt_ozet = ? WHERE id = ?",
                        (yeni_baslik, yeni_ozet or eski_ozet, haber["id"]),
                    )
                    con.commit()

                    taze = con.execute("SELECT * FROM haberler WHERE id = ?", (haber["id"],)).fetchone()
                    son_dakika_mi = len(haberler) == 1 and bool(haberler[0]["son_dakika"])
                    if son_dakika_mi:
                        sonuclar = slaytlar.son_dakika_uret(taze, ayarlar, con=con)
                        urller = []
                        story_url = None
                        for s in sonuclar:
                            if s.get("katman") == "story":
                                if s.get("yol"):
                                    try:
                                        yukleme = upload_image.gorsel_yukle(s["yol"], ayarlar)
                                        story_url = yukleme["url"]
                                    except Exception as e:
                                        log.warning("story yüklenemedi: %s", e)
                                continue
                            yukleme = upload_image.gorsel_yukle(s["yol"], ayarlar)
                            urller.append(yukleme["url"])

                        con.execute(
                            "UPDATE haberler SET gorsel_url = ?, story_url = ?, detay_url = ? WHERE id = ?",
                            (urller[0], story_url or urller[0], json.dumps(urller[1:]), haber["id"]),
                        )
                        con.commit()
                        yeni_cap = caption.son_dakika_caption(taze, sonuclar, ayarlar)
                        con.execute("UPDATE haberler SET ig_caption = ? WHERE id = ?", (yeni_cap, haber["id"]))
                        con.commit()
                    else:
                        yol, katman, atif = slaytlar.slayt_uret(taze, ayarlar)
                        yukleme = upload_image.gorsel_yukle(yol, ayarlar)
                        story_yol = make_image.CIKTI_KLASORU / f"story-{haber['id']}.jpg"
                        story_url = yukleme["url"]
                        if story_yol.exists():
                            try:
                                story_yukleme = upload_image.gorsel_yukle(story_yol, ayarlar)
                                story_url = story_yukleme.get("url") or story_url
                            except Exception as e:
                                log.warning("Story görseli yüklenemedi: %s", e)

                        con.execute(
                            "UPDATE haberler SET gorsel_url = ?, story_url = ?, gorsel_yolu = ?, "
                            "gorsel_kaynagi = ?, gorsel_atif = ? WHERE id = ?",
                            (yukleme["url"], story_url, str(yol), katman, atif, haber["id"]),
                        )
                        con.commit()
                        guncel = turu_getir(con, mesaj_id)
                        yeni_cap = caption.caption_kur(guncel, _sonuclari_kur(guncel), ayarlar=ayarlar)
                        for h in guncel:
                            con.execute("UPDATE haberler SET ig_caption = ? WHERE id = ?", (yeni_cap, h["id"]))
                        con.commit()

                    _albumu_yenile(con, mesaj_id)
                    menuyu_geri_koy(con, mesaj_id)
                    telegram_bot.mesaj_gonder(
                        f"🔥 <b>{sira}. slaytın başlığı daha dikkat çekici olarak yenilendi:</b>\n\n"
                        f"<b>Eski Başlık:</b> <s>{html.escape(eski_baslik)}</s>\n"
                        f"<b>Yeni Manşet:</b> <b>{html.escape(yeni_baslik)}</b>\n"
                        f"<b>Yeni Özet:</b> <i>{html.escape(yeni_ozet or '')}</i>",
                        html=True,
                    )
                    db_senkron.hemen_kaydet(f"Başlık çarpıcı yapıldı: slayt {sira}")
                    return 0
        except Exception as e:
            log.warning("Çarpıcı başlık üretme hatası: %s", e)

    if komut == "slayt_metin":
        con.execute("UPDATE haberler SET durum = 'yeni' WHERE id = ?", (haber["id"],))
        con.commit()
        metinleri_uret(ayarlar=ayarlar, con=con, haberler=[haber])
        con.execute("UPDATE haberler SET durum = 'onay_bekliyor' WHERE id = ?",
                    (haber["id"],))
        con.commit()
        taze = con.execute("SELECT * FROM haberler WHERE id = ?", (haber["id"],)).fetchone()
        yol, katman, atif = slaytlar.slayt_uret(taze, ayarlar)
        yukleme = upload_image.gorsel_yukle(yol, ayarlar)
        story_yol = make_image.CIKTI_KLASORU / f"story-{haber['id']}.jpg"
        story_url = yukleme["url"]
        if story_yol.exists():
            try:
                story_yukleme = upload_image.gorsel_yukle(story_yol, ayarlar)
                story_url = story_yukleme.get("url") or story_url
            except Exception as e:
                log.warning("Story görseli yüklenemedi: %s", e)

        con.execute(
            "UPDATE haberler SET gorsel_url = ?, story_url = ?, gorsel_yolu = ?, "
            "gorsel_kaynagi = ?, gorsel_atif = ? WHERE id = ?",
            (yukleme["url"], story_url, str(yol), katman, atif, haber["id"]),
        )
        con.commit()

        guncel = turu_getir(con, mesaj_id)
        if len(guncel) == 1 and guncel[0]["son_dakika"]:
            yeni_cap = caption.son_dakika_caption(taze, _sonuclari_kur(guncel), ayarlar)
        else:
            yeni_cap = caption.caption_kur(guncel, _sonuclari_kur(guncel), ayarlar=ayarlar)
        for h in guncel:
            con.execute("UPDATE haberler SET ig_caption = ? WHERE id = ?", (yeni_cap, h["id"]))
        con.commit()

        _albumu_yenile(con, mesaj_id)
        menuyu_geri_koy(con, mesaj_id)
        telegram_bot.mesaj_gonder(
            f"✍️ <b>{sira}. slaytın metni yapay zeka ile yeniden yazıldı:</b>\n\n"
            f"<b>Başlık:</b> {html.escape(taze['ig_baslik'] or '')}\n"
            f"<b>Özet:</b> {html.escape(taze['slayt_ozet'] or '')}",
            html=True,
        )
        db_senkron.hemen_kaydet(f"Slayt {sira} metni yeniden üretildi")
        return 0

    # slayt_ai / slayt_foto / metin sonrası: slaytı yeniden üret
    taze = con.execute("SELECT * FROM haberler WHERE id = ?", (haber["id"],)).fetchone()

    # ⚠️ İKİ DÜĞME DE ARTIK GERÇEKTEN FARKLI SONUÇ ÜRETİYOR (20 Ağu 2026).
    #
    # Önce burada yalnızca `gorsel.haberde_ai` bayrağı set ediliyordu ve
    # `slaytlar.arkaplan_sec` o bayrağı HİÇ OKUMUYORDU. Sonuç: her iki
    # düğme de sabit katman zincirini (og:image → Commons → Pexels)
    # baştan çalıştırıyor, zincirin her adımı deterministik olduğu için
    # tıpatıp aynı görseli üretiyordu. Kullanıcı "AI ile üret desem de
    # diğerini seçsem de aynı görüntü geliyor" diye bildirdi; kanıt
    # `gorsel_sayac_adet`in 14 Ağustos'tan beri 1'de kalmasıydı — AI
    # bir kez bile çağrılmamıştı.
    zorla_ai = (komut == "slayt_ai")
    deneme = (taze["gorsel_deneme"] or 0) + 1 if komut == "slayt_foto" else 0
    # ⚠️ "Başka fotoğraf" düğmesinde haber görseli (og:image) her zaman ATLANIYOR.
    # og:image deterministik: her seferinde aynı URL → aynı sonuç.
    # Kullanıcı "başka" deyince Commons/Pexels'e geçiyoruz.
    foto_atla = (komut == "slayt_foto" or deneme > 0)
    yol, katman, atif = slaytlar.slayt_uret(
        taze, ayarlar, zorla_ai=zorla_ai, atlanacak=deneme,
        haber_gorseli_atla=foto_atla)

    yukleme = upload_image.gorsel_yukle(yol, ayarlar)
    story_yol = make_image.CIKTI_KLASORU / f"story-{haber['id']}.jpg"
    story_url_aday = None
    if story_yol.exists():
        try:
            story_yukleme = upload_image.gorsel_yukle(story_yol, ayarlar)
            story_url_aday = story_yukleme.get("url")
        except Exception as e:
            log.warning("Story görseli yüklenemedi: %s", e)

    # ⚠️ ADAY ALANLARA YAZILIYOR, ASIL ALANLARA DEĞİL.
    # Önce `gorsel_url` doğrudan güncelleniyordu: kullanıcı yeni görseli
    # beğenmese bile geri dönüş yoktu ve eski dosya da üzerine
    # yazıldığı için diskte kalmıyordu. Artık onay bekliyor.
    con.execute(
        "UPDATE haberler SET gorsel_url_aday = ?, story_url_aday = ?, "
        "gorsel_kaynagi_aday = ?, gorsel_atif_aday = ?, gorsel_yolu_aday = ?, "
        "gorsel_deneme = ? WHERE id = ?",
        (yukleme["url"], story_url_aday or yukleme["url"], katman, atif, str(yol), deneme, haber["id"]),
    )
    con.commit()

    # Yeni görseli GÖSTERİYORUZ, link vermiyoruz: beğenip beğenmediğine
    # karar vermek için tarayıcı açmak gerekmemeli.
    simge = telegram_bot.KATMAN_SIMGE.get(katman, "▫️")
    telegram_bot.foto_gonder(
        yukleme["url"],
        f"{simge} {sira}. slayt için yeni görsel — {katman}\n"
        f"{taze['ig_baslik'] or ''}\n\n"
        f"Beğendiysen onayla; onaylamazsan slayt eski görselle kalır.",
        # ⚠️ TUR MESAJ ID'Sİ DÜĞMEYE GÖMÜLÜ. Bu önizleme AYRI bir
        # mesajda duruyor ve Worker basılan düğmenin BULUNDUĞU mesajın
        # id'sini gönderiyor. 21 Ağu 2026: kullanıcı "🔄 Başka dene"ye
        # bastı, job "mesaj_id=657 artık geçerli değil" dedi — tur 656,
        # önizleme mesajı 657'ydi.
        # Aynı tuzak `kaldir` ve `haber_sec` düğmelerinde de yaşandı.
        butonlar=[[
            {"text": "✅ Bunu kullan",
             "callback_data": f"gorsel_kabul:{sira}:{mesaj_id}"},
            {"text": "🔄 Başka dene",
             "callback_data": f"gorsel_yeni:{sira}:{mesaj_id}"},
        ]],
    )
    return 0


def _albumu_yenile(con, mesaj_id: int) -> None:
    """
    Üstteki slayt albümünü siler ve güncel hâlini (9:16 Story formatında) yeniden gönderir.
    """
    yeniler = turu_getir(con, mesaj_id)
    if not yeniler:
        return
    urller = []
    ilk_h = dict(yeniler[0]) if yeniler else {}
    if ilk_h.get("tur") == "ekonomi":
        kart_satir = con.execute(
            "SELECT deger FROM ayarlar WHERE anahtar = ?",
            (f"piyasa_karti_{mesaj_id}",)
        ).fetchone()
        tablo_satir = con.execute(
            "SELECT deger FROM ayarlar WHERE anahtar = ?",
            (f"piyasa_tablosu_{mesaj_id}",)
        ).fetchone()
        if kart_satir and kart_satir["deger"]:
            urller.append(kart_satir["deger"])
        if tablo_satir and tablo_satir["deger"]:
            urller.append(tablo_satir["deger"])

    for h in yeniler:
        h_dict = dict(h)
        u = h_dict.get("story_url") or h_dict.get("gorsel_url")
        if u:
            urller.append(u)
        if h_dict.get("detay_url"):
            urller.extend(_detay_urlleri(h_dict["detay_url"]))

    eski_albom = db.ayar_oku(con, f"albom_{mesaj_id}", "")
    if eski_albom:
        try:
            telegram_bot.mesajlari_sil(json.loads(eski_albom))
        except Exception as e:                        # noqa: BLE001
            log.warning("eski albüm silinemedi: %s", e)
    try:
        basliklar = [f"Slayt {i}" for i in range(1, len(urller) + 1)]
        yeni_idler = telegram_bot.slaytlari_gonder(urller, basliklar)
        db.ayar_yaz(con, f"albom_{mesaj_id}", json.dumps(yeni_idler or []))
    except Exception as e:                            # noqa: BLE001
        log.warning("albüm yenilenemedi: %s", e)


def metin_duzenle(con, ayarlar: dict, haberler: list, mesaj_id: int, gelen_metin: str, basan: str) -> int:
    """
    Kullanıcının Telegram'dan Reply yaparak veya komutla girdiği yeni başlık/metni işler.

    Formatlar:
      - "3: Yeni Başlık"
      - "3: Yeni Başlık | Yeni Açıklama"
      - "Yeni Başlık" (Tekil haberler için doğrudan, 10'lu turda belirsizse yönlendirme yapılır)
    """
    if not gelen_metin or not gelen_metin.strip():
        telegram_bot.mesaj_gonder("⚠️ Boş metin girilemez.")
        return 0

    metin = gelen_metin.strip()
    sira = None
    yeni_baslik = ""
    yeni_metin = None

    # Format 1: "3: ..." veya "3. ..." veya "3 - ..."
    eslesme = re.match(r"^([1-9]|10)\s*[:\.\-]\s*(.+)$", metin, re.DOTALL)
    if eslesme:
        sira = int(eslesme.group(1))
        kalan = eslesme.group(2).strip()
    else:
        # Numara yoksa:
        if len(haberler) == 1:
            sira = 1
            kalan = metin
        else:
            telegram_bot.mesaj_gonder(
                "⚠️ Bu turda birden fazla slayt var. Lütfen hangi slaytı "
                "düzenlemek istediğini belirt.\n\n"
                "<b>Örnek format:</b>\n"
                "• <code>3: Yeni Başlık Metni</code>\n"
                "• <code>3: Yeni Başlık | Yeni Açıklama</code>",
                html=True,
            )
            return 0

    if sira > len(haberler) or sira < 1:
        telegram_bot.mesaj_gonder(f"⚠️ Bu turda {len(haberler)} slayt var; {sira}. slayt bulunamadı.")
        return 0

    # Başlık ve Açıklama ayrıştırma: "Başlık | Açıklama" veya satır sonu
    if "|" in kalan:
        parcalar = kalan.split("|", 1)
        yeni_baslik = parcalar[0].strip()
        yeni_metin = parcalar[1].strip()
    elif "\n" in kalan:
        parcalar = kalan.split("\n", 1)
        yeni_baslik = parcalar[0].strip()
        yeni_metin = parcalar[1].strip()
    else:
        yeni_baslik = kalan

    if not yeni_baslik:
        telegram_bot.mesaj_gonder("⚠️ Başlık boş olamaz.")
        return 0

    haber = haberler[sira - 1]

    # DB Güncelleme
    if yeni_metin:
        con.execute(
            "UPDATE haberler SET ig_baslik = ?, ig_metin = ? WHERE id = ?",
            (yeni_baslik, yeni_metin, haber["id"]),
        )
    else:
        con.execute(
            "UPDATE haberler SET ig_baslik = ? WHERE id = ?",
            (yeni_baslik, haber["id"]),
        )
    con.commit()

    # Durum 1: Başlık Onayı Aşaması (Slaytlar henüz üretilmedi)
    if haber["durum"] == "baslik_onayi":
        guncel_haberler = turu_getir(con, mesaj_id)
        telegram_bot.basliklari_tazele(mesaj_id, guncel_haberler)
        telegram_bot.mesaj_gonder(
            f"✅ <b>{sira}. slaytın başlığı güncellendi:</b>\n<i>{html.escape(yeni_baslik)}</i>",
            html=True,
        )
        db_senkron.hemen_kaydet(f"Başlık düzenlendi (başlık onayı): slayt {sira}")
        return 0

    # Durum 2: Görsel Onayı Aşaması (Slayt üretilmiş durumda)
    # Slaytı yeni başlıkla yeniden çiziyoruz
    taze = con.execute("SELECT * FROM haberler WHERE id = ?", (haber["id"],)).fetchone()
    yol, katman, atif = slaytlar.slayt_uret(taze, ayarlar)
    yukleme = upload_image.gorsel_yukle(yol, ayarlar)
    story_yol = make_image.CIKTI_KLASORU / f"story-{haber['id']}.jpg"
    story_url = yukleme["url"]
    if story_yol.exists():
        try:
            story_yukleme = upload_image.gorsel_yukle(story_yol, ayarlar)
            story_url = story_yukleme.get("url") or story_url
        except Exception as e:
            log.warning("Story görseli yüklenemedi: %s", e)

    con.execute(
        "UPDATE haberler SET gorsel_url = ?, story_url = ?, gorsel_yolu = ?, "
        "gorsel_kaynagi = ?, gorsel_atif = ? WHERE id = ?",
        (yukleme["url"], story_url, str(yol), katman, atif, haber["id"]),
    )
    con.commit()

    # Caption'ı güncelle
    guncel_haberler = turu_getir(con, mesaj_id)
    if len(guncel_haberler) == 1:
        yeni_cap = caption.son_dakika_caption(taze, _sonuclari_kur(guncel_haberler), ayarlar)
    else:
        yeni_cap = caption.caption_kur(guncel_haberler, _sonuclari_kur(guncel_haberler), ayarlar=ayarlar)

    con.execute(
        "UPDATE haberler SET ig_caption = ? WHERE id = ?",
        (yeni_cap, haber["id"]),
    )
    con.commit()

    # Albümü / önizlemeyi yenile
    try:
        _albumu_yenile(con, mesaj_id)
    except Exception as e:
        log.warning("albüm yenilenirken hata: %s", e)

    telegram_bot.mesaj_gonder(
        f"✅ <b>{sira}. slaytın başlığı güncellendi ve yeni slayt üretildi:</b>\n<i>{html.escape(yeni_baslik)}</i>\n"
        f"<i>(Yazan: {basan or 'Bilinmiyor'})</i>",
        html=True,
    )
    db_senkron.hemen_kaydet(f"Başlık elle düzenlendi: slayt {sira}")
    return 0


def slayt_tasi(con, ayarlar: dict, haberler: list, eylem: str, sira: int, mesaj_id: int) -> int:
    """
    Slaytların sırasını yukarı, aşağı taşır veya en başa (manşet) alır.
    """
    if sira < 1 or sira > len(haberler):
        telegram_bot.mesaj_gonder(f"⚠️ {sira}. slayt bulunamadı.")
        return 0

    if len(haberler) < 2:
        telegram_bot.mesaj_gonder("⚠️ Tek slaytlı turda sıralama yapılamaz.")
        return 0

    sirali = list(haberler)
    if eylem == "slayt_basa":
        if sira == 1:
            telegram_bot.mesaj_gonder("⚠️ Bu slayt zaten 1. sırada (Manşet).")
            return 0
        hedef = sirali.pop(sira - 1)
        sirali.insert(0, hedef)
        mesaj = f"🔝 <b>{sira}. slayt en başa (Manşet) alındı:</b>\n<i>{html.escape(hedef['ig_baslik'] or hedef['baslik_orj'] or '')}</i>"

    elif eylem == "slayt_yukari":
        if sira == 1:
            telegram_bot.mesaj_gonder("⚠️ Bu slayt zaten 1. sırada.")
            return 0
        sirali[sira - 2], sirali[sira - 1] = sirali[sira - 1], sirali[sira - 2]
        mesaj = f"⬆️ <b>{sira}. slayt {sira - 1}. sıraya taşındı.</b>"

    elif eylem == "slayt_asagi":
        if sira == len(haberler):
            telegram_bot.mesaj_gonder("⚠️ Bu slayt zaten son sırada.")
            return 0
        sirali[sira - 1], sirali[sira] = sirali[sira], sirali[sira - 1]
        mesaj = f"⬇️ <b>{sira}. slayt {sira + 1}. sıraya taşındı.</b>"
    else:
        telegram_bot.mesaj_gonder("⚠️ Bilinmeyen taşıma eylemi.")
        return 0

    # DB'de tüm tur için slayt_sirasi değerlerini normalize et
    for idx, h in enumerate(sirali, 1):
        con.execute("UPDATE haberler SET slayt_sirasi = ? WHERE id = ?", (idx, h["id"]))
    con.commit()

    guncel = turu_getir(con, mesaj_id)

    # Durum 1: Başlık onayı aşaması
    if haberler[0]["durum"] == "baslik_onayi":
        telegram_bot.basliklari_tazele(mesaj_id, guncel)
        telegram_bot.mesaj_gonder(mesaj, html=True)
        db_senkron.hemen_kaydet(f"Slayt sırası değiştirildi: {eylem}:{sira}")
        return 0

    # Durum 2: Görsel onayı aşaması
    yeni_cap = caption.caption_kur(guncel, _sonuclari_kur(guncel), ayarlar=ayarlar)
    for h in guncel:
        con.execute("UPDATE haberler SET ig_caption = ? WHERE id = ?", (yeni_cap, h["id"]))
    con.commit()

    try:
        _albumu_yenile(con, mesaj_id)
    except Exception as e:
        log.warning("albüm yenilenirken hata: %s", e)

    telegram_bot.mesaj_gonder(mesaj, html=True)
    db_senkron.hemen_kaydet(f"Slayt sırası değiştirildi: {eylem}:{sira}")
    return 0


def havuzdan_haber_ekle(con, ayarlar: dict, haberler: list, mesaj_id: int) -> int:
    """
    Havuzdan en iyi taze haberi seçip mevcut tura yeni slayt olarak ekler.
    """
    if len(haberler) >= 10:
        telegram_bot.mesaj_gonder("⚠️ Instagram carousel en fazla 10 slayt destekler. Önce bir slaytı çıkarmalısın.")
        return 0

    sinir = datetime.now(timezone.utc) - timedelta(
        hours=ayarlar.get("genel", {}).get("yayin_yasi_siniri_saat", 36)
    )
    mevcut_idler = [h["id"] for h in haberler]
    soru_isaretleri = ",".join("?" for _ in mevcut_idler)
    sorgu = (
        "SELECT * FROM haberler WHERE durum = 'metin_hazir' "
        "AND COALESCE(daha_once_yayinlandi, 0) = 0 "
        "AND (telegram_message_id IS NULL OR telegram_message_id = 0) "
        f"AND id NOT IN ({soru_isaretleri}) "
        "AND yayin_tarihi >= ? "
        "ORDER BY onem_puani DESC, yayin_tarihi DESC LIMIT 1"
    )
    parametreler = list(mevcut_idler) + [sinir.isoformat()]
    aday_haber = con.execute(sorgu, parametreler).fetchone()

    if not aday_haber:
        telegram_bot.mesaj_gonder(
            "⚠️ Havuzda taze ve uygun haber bulunamadı. "
            "/guncelle komutuyla kaynakları tarayabilirsin."
        )
        return 0

    yeni_sira = len(haberler) + 1

    # Durum 1: Başlık onayı aşaması
    if haberler[0]["durum"] == "baslik_onayi":
        con.execute(
            "UPDATE haberler SET durum = 'baslik_onayi', telegram_message_id = ?, "
            "slayt_sirasi = ?, gonderim_zamani = datetime('now') WHERE id = ?",
            (mesaj_id, yeni_sira, aday_haber["id"]),
        )
        con.commit()
        guncel = turu_getir(con, mesaj_id)
        telegram_bot.basliklari_tazele(mesaj_id, guncel)
        telegram_bot.mesaj_gonder(
            f"✅ <b>Havuzdan yeni haber eklendi ({yeni_sira}. slayt):</b>\n"
            f"<i>{html.escape(aday_haber['ig_baslik'] or aday_haber['baslik_orj'] or '')}</i>",
            html=True,
        )
        db_senkron.hemen_kaydet(f"Havuzdan haber eklendi (başlık onayı): id={aday_haber['id']}")
        return 0

    # Durum 2: Görsel onayı aşaması (Slayt üretilmeli)
    yol, katman, atif = slaytlar.slayt_uret(aday_haber, ayarlar)
    yukleme = upload_image.gorsel_yukle(yol, ayarlar)
    story_yol = make_image.CIKTI_KLASORU / f"story-{aday_haber['id']}.jpg"
    story_url = yukleme["url"]
    if story_yol.exists():
        try:
            story_yukleme = upload_image.gorsel_yukle(story_yol, ayarlar)
            story_url = story_yukleme.get("url") or story_url
        except Exception as e:
            log.warning("Story görseli yüklenemedi: %s", e)

    con.execute(
        "UPDATE haberler SET durum = 'onay_bekliyor', telegram_message_id = ?, "
        "slayt_sirasi = ?, gorsel_url = ?, story_url = ?, gorsel_yolu = ?, gorsel_kaynagi = ?, "
        "gorsel_atif = ?, gonderim_zamani = datetime('now') WHERE id = ?",
        (mesaj_id, yeni_sira, yukleme["url"], story_url, str(yol), katman, atif, aday_haber["id"]),
    )
    con.commit()

    guncel = turu_getir(con, mesaj_id)
    yeni_cap = caption.caption_kur(guncel, _sonuclari_kur(guncel), ayarlar=ayarlar)
    for h in guncel:
        con.execute("UPDATE haberler SET ig_caption = ? WHERE id = ?", (yeni_cap, h["id"]))
    con.commit()

    try:
        _albumu_yenile(con, mesaj_id)
    except Exception as e:
        log.warning("albüm yenilenirken hata: %s", e)

    telegram_bot.mesaj_gonder(
        f"✅ <b>Havuzdan yeni haber eklendi ve {yeni_sira}. slayt üretildi:</b>\n"
        f"<i>{html.escape(aday_haber['ig_baslik'] or aday_haber['baslik_orj'] or '')}</i>\n"
        f"<i>({len(guncel)} slayt oldu)</i>",
        html=True,
    )
    db_senkron.hemen_kaydet(f"Havuzdan haber eklendi: id={aday_haber['id']}")
    return 0


def haber_degistir(con, ayarlar, haberler, sira: int, mesaj_id: int) -> int:
    """
    Turdaki bir haberin yerine geçebilecek 2 alternatifi sunar.

    Kullanıcı isteği (20 Ağu 2026): "10'lu tur geldi, akşam
    haberlerden bir ya da birkaçını değiştirebilmeliyim; değiştir
    dediğim her haber için haber başı 2 öneri gelsin".

    Bu adım YALNIZCA öneriyor — değiştirme, kullanıcı alternatiflerden
    birini seçince yapılıyor. Sebep: değiştirme slayt üretimi ve albüm
    yenilemesi demek, geri alması pahalı.
    """
    if sira < 1 or sira > len(haberler):
        telegram_bot.mesaj_gonder(f"⚠️ {sira}. slayt bulunamadı.")
        return 1
    mevcut = haberler[sira - 1]
    idler = [h["id"] for h in haberler]

    adaylar = aday.alternatifler(con, ayarlar, mevcut, idler, adet=2)
    if not adaylar:
        telegram_bot.mesaj_gonder(
            f"⚠️ {sira}. slayt için uygun alternatif bulunamadı.\n"
            "Havuzda metni hazır, bayatlamamış ve daha önce "
            "yayınlanmamış haber kalmamış olabilir.")
        menuyu_geri_koy(con, mesaj_id)
        return 0

    telegram_bot.mesaj_gonder(
        f"🔄 {sira}. slayt şu an:\n"
        f"«{mevcut['ig_baslik'] or mevcut['baslik_orj']}»\n\n"
        "Yerine hangisi gelsin? (Seçmezsen tur olduğu gibi kalır.)",
        butonlar=telegram_bot.alternatif_menusu(
            mevcut["id"], adaylar, mesaj_id)["inline_keyboard"])
    log.info("slayt %s (haber %s) için %s alternatif sunuldu",
             sira, mevcut["id"], len(adaylar))
    return 0


def haberi_degistir_uygula(con, ayarlar, haberler, eski_id: int, yeni_id: int,
                           mesaj_id: int) -> int:
    """
    Seçilen alternatifi tura koyar, eskisini havuza döndürür.

    ⚠️ HEDEF HABER ID İLE BULUNUYOR, slayt numarasıyla değil. Numara
    tur yeniden sıralanınca kayıyor ve açık duran bir alternatif
    mesajı yanlış slaydı değiştiriyordu.

    ⚠️ ESKİ HABER ELENMİYOR — `metin_hazir` olarak havuza dönüyor ve
    sonraki turlarda yeniden yarışıyor. Projedeki genel kural bu:
    onaylanmayan haber kaybolmaz.
    """
    eski = next((h for h in haberler if h["id"] == eski_id), None)
    if not eski:
        telegram_bot.mesaj_gonder(
            "⚠️ Değiştirilecek haber bu turda değil — tur bu arada "
            "değişmiş olabilir. Menüden yeniden dene.")
        menuyu_geri_koy(con, mesaj_id)
        return 0
    sira = haberler.index(eski) + 1
    yeni = con.execute("SELECT * FROM haberler WHERE id = ?",
                       (yeni_id,)).fetchone()
    if not yeni:
        telegram_bot.mesaj_gonder("⚠️ Seçilen haber bulunamadı.")
        menuyu_geri_koy(con, mesaj_id)
        return 1
    if yeni["telegram_message_id"]:
        telegram_bot.mesaj_gonder(
            "⚠️ Bu haber bu arada başka bir tura girmiş, kullanılamaz.")
        menuyu_geri_koy(con, mesaj_id)
        return 0

    # Slaytı ÜRET — hata olursa tura hiç dokunmuyoruz.
    son_dakika_mi = bool(eski["son_dakika"]) or len(haberler) == 1
    try:
        if son_dakika_mi:
            sonuclar = slaytlar.son_dakika_uret(dict(yeni), ayarlar, con=con)
            urller = []
            story_url = None
            for s in sonuclar:
                if s.get("katman") == "story":
                    if s.get("yol"):
                        try:
                            yukleme = upload_image.gorsel_yukle(s["yol"], ayarlar)
                            story_url = yukleme["url"]
                        except Exception as e:
                            log.warning("story yüklenemedi: %s", e)
                    continue
                yukleme = upload_image.gorsel_yukle(s["yol"], ayarlar)
                urller.append(yukleme["url"])
            url = urller[0]
            detay_json = json.dumps(urller[1:])
            katman = sonuclar[0].get("katman", "og")
            atif = sonuclar[0].get("atif", "")
            yol = sonuclar[0].get("yol", "")
        else:
            yol, katman, atif = slaytlar.slayt_uret(dict(yeni), ayarlar)
            url = upload_image.gorsel_yukle(yol, ayarlar)["url"]
            story_yol = make_image.CIKTI_KLASORU / f"story-{yeni_id}.jpg"
            story_url = url
            detay_json = None
            if story_yol.exists():
                try:
                    story_yukleme = upload_image.gorsel_yukle(story_yol, ayarlar)
                    story_url = story_yukleme.get("url") or story_url
                except Exception as e:
                    log.warning("Story görseli yüklenemedi: %s", e)
    except Exception as e:                            # noqa: BLE001
        log.exception("alternatif slaytı üretilemedi")
        telegram_bot.mesaj_gonder(
            f"⚠️ Yeni haberin slaytı üretilemedi: {type(e).__name__}: {e}\n"
            "Tur değişmedi.")
        menuyu_geri_koy(con, mesaj_id)
        return 1

    # Eski haber havuza, yeni haber tura. `tur` ve `slayt_sirasi` korunuyor ki
    # sıralama bozulmasın.
    con.execute(
        "UPDATE haberler SET durum = 'metin_hazir', telegram_message_id = NULL, "
        "tur = NULL, slayt_sirasi = NULL WHERE id = ?", (eski["id"],))
    con.execute(
        "UPDATE haberler SET durum = 'onay_bekliyor', telegram_message_id = ?, "
        "tur = ?, gorsel_yolu = ?, gorsel_url = ?, story_url = ?, detay_url = ?, gorsel_kaynagi = ?, "
        "gorsel_atif = ?, gonderim_zamani = ?, slayt_sirasi = ? WHERE id = ?",
        (mesaj_id, eski["tur"], str(yol), url, story_url, detay_json, katman, atif,
         eski["gonderim_zamani"], eski["slayt_sirasi"], yeni_id))
    con.commit()
    db_senkron.hemen_kaydet(f"Turda {sira}. haber değiştirildi")

    _albumu_yenile(con, mesaj_id)
    menuyu_geri_koy(con, mesaj_id)
    telegram_bot.mesaj_gonder(
        f"✅ {sira}. slayt değiştirildi:\n"
        f"«{yeni['ig_baslik'] or yeni['baslik_orj']}»\n\n"
        "Eski haber elenmedi, havuza döndü.")
    log.info("slayt %s: %s -> %s", sira, eski["id"], yeni_id)
    return 0


def gorseli_kabul_et(con, ayarlar, haberler, sira: int, mesaj_id: int) -> int:
    """
    Değiştirilen görseli kalıcı yapar ve albümü yeniler.
    """
    if sira < 1 or sira > len(haberler):
        telegram_bot.mesaj_gonder(f"⚠️ {sira}. slayt bulunamadı.")
        return 1
    haber = haberler[sira - 1]
    if not haber["gorsel_url_aday"]:
        telegram_bot.mesaj_gonder(
            "⚠️ Onay bekleyen bir görsel yok — muhtemelen zaten uygulandı.")
        menuyu_geri_koy(con, mesaj_id)
        return 0

    con.execute(
        "UPDATE haberler SET gorsel_url = gorsel_url_aday, "
        "story_url = COALESCE(story_url_aday, gorsel_url_aday), "
        "gorsel_kaynagi = gorsel_kaynagi_aday, gorsel_atif = gorsel_atif_aday, "
        "gorsel_yolu = gorsel_yolu_aday, "
        "gorsel_url_aday = NULL, story_url_aday = NULL, gorsel_yolu_aday = NULL, "
        "gorsel_kaynagi_aday = NULL, gorsel_atif_aday = NULL "
        "WHERE id = ?", (haber["id"],))
    con.commit()
    db_senkron.hemen_kaydet("Slayt görseli değiştirildi")

    _albumu_yenile(con, mesaj_id)
    menuyu_geri_koy(con, mesaj_id)
    telegram_bot.mesaj_gonder(f"✅ {sira}. slaytın görseli güncellendi. Yayına hazır!")
    log.info("slayt %s görseli kabul edildi (haber=%s)", sira, haber["id"])
    return 0


def menuyu_geri_koy(con, mesaj_id: int) -> None:
    """
    Onay mesajını yeniden düzenleyip butonları geri koyar.

    Worker, butona basıldığı anda butonları kaldırıp "⏳ İşleniyor"
    yazıyor (çift basmayı engellemek için). İş bitince menüyü geri
    koymazsak tur kilitleniyor — ne yayınlanabiliyor ne atlanabiliyor.

    Metin de tazeleniyor: slayt görseli değişmiş olabilir, özet
    tablodaki katman simgesi güncel olmalı.
    """
    haberler = turu_getir(con, mesaj_id)
    if not haberler:
        return
    try:
        uyari, isaretli = dogrula.turu_dogrula(haberler)
        ilk_h = dict(haberler[0]) if haberler else {}
        if len(haberler) == 1 and ilk_h.get("son_dakika"):
            adet = 1 + len(_detay_urlleri(ilk_h.get("detay_url")))
            ozet = (f"🔴 SON DAKİKA ÖNERİSİ  ·  puan {ilk_h.get('onem_puani', 8)}/10\n"
                    f"⌛️ 24 saat boyunca onaya hazır bekler")
            metin = caption.son_dakika_caption(haberler[0], _sonuclari_kur(haberler), ayarlar=_ayarlar_onbellek)
        elif ilk_h.get("tur") == "ekonomi":
            adet = len(haberler) + 2
            ozet = (
                f"📊 <b>GÜNE BAŞLARKEN EKONOMİ & PİYASALAR</b>\n"
                f"1 Piyasa Kartı + 1 Piyasa Tablosu + {len(haberler)} Ekonomi Haberi ({adet} slayt)\n"
                f"⌛️ 24 saat boyunca onaya hazır bekler"
            )
            metin = ilk_h.get("ig_caption") or caption.caption_kur(
                haberler, _sonuclari_kur(haberler), ayarlar=_ayarlar_onbellek
            )
        else:
            adet = len(haberler)
            ozet = telegram_bot.tur_ozeti(haberler, isaretli)
            metin = caption.caption_kur(
                haberler, _sonuclari_kur(haberler), ayarlar=_ayarlar_onbellek
            )

        parcalar = [p for p in (uyari, ozet) if p]
        parcalar.append("— Instagram açıklaması —\n" + metin)
        telegram_bot.mesaji_guncelle(
            mesaj_id, "\n\n".join(parcalar),
            telegram_bot.ana_menu(adet),
        )
    except Exception as e:
        log.warning("menü geri konamadı: %s", e)


def durum_bildir(con, ayarlar) -> int:
    """
    /durum komutunun cevabı: Botun ve bekleyen tüm turların detaylı, şeffaf ve interaktif durum raporu.
    """
    from src.zaman import tr_format, goreceli_zaman, su_an_tr

    # 1. Genel Sayımlar
    sayim = dict(con.execute(
        "SELECT durum, COUNT(*) FROM haberler GROUP BY durum"
    ).fetchall())

    # 2. Onay Bekleyen veya Açık Turlar (telegram_message_id'ye göre grupla)
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

    # 3. Son Yayınlanan Post
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

            # Eğer 10 dakikadan eski ve hala onay bekliyorsa uyarı ekle
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



# Yazım hatası toleransı: iki kelime bu orandan benzerse aynı sayılıyor.
#
# ⚠️ YALNIZCA HİÇ SONUÇ ÇIKMAYINCA devreye giriyor. Ölçüldü (21 Ağu
# 2026): doğru eşleşmeler 0.80-0.95, yanlış eşleşmeler 0.60-0.88
# aralığında ve ARALIKLAR ÇAKIŞIYOR — "kayseri"/"kayseride" 0.88
# (yanlış) ama "trump"/"trumb" 0.80 (doğru). Tek eşikle ayrılmıyorlar.
# Çözüm sıralama: "kayseride" zaten normal aramada bulunuyor, fuzzy'ye
# hiç gerek kalmıyor; fuzzy sadece gerçek yazım hatalarında çalışıyor.
YAZIM_BENZERLIGI = 0.85
# Harf kümesi benzerliği — sıradan bağımsız ölçüt. "netenhay" burada
# 0.86 alıyor, dizi benzerliğinde yalnızca 0.59 alıyordu.
HARF_BENZERLIGI = 0.80


def _yazim_yakin_mi(a: str, b: str) -> bool:
    """
    İki kelime yazım hatası payıyla aynı mı?

    İKİ ÖLÇÜT, biri yetiyor:

    1. **Dizi benzerliği** (`SequenceMatcher`) — harf sırasına duyarlı.
       "netenyahu"/"netanyahu" burada 0.89 alıyor.

    2. **Harf kümesi benzerliği** — sıradan BAĞIMSIZ.
       ⚠️ Bu ikincisi olmadan harf sırası karışan yazımlar kaçıyordu.
       21 Ağu 2026 ölçümü: kullanıcı "netenhay" yazdı, dizi benzerliği
       yalnızca **0.59** çıktı (hay ↔ yah yer değiştirmiş) ve arama
       "sonuç yok" dedi — oysa havuzda 24 Netanyahu haberi vardı.
       Harf kümesinde aynı çift **0.86** alıyor.

    Uzunluk farkı 3'ten fazlaysa hiç denenmiyor: "gazze"/"gaziantep"
    gibi çiftler harf kümesinde yanlışlıkla yakınlaşabiliyor.
    """
    from difflib import SequenceMatcher
    if len(a) < 5 or len(b) < 5:
        return False                       # kısa kelimede çok riskli
    if abs(len(a) - len(b)) > 3:
        return False
    if SequenceMatcher(None, a, b).ratio() >= YAZIM_BENZERLIGI:
        return True
    # ⚠️ HARF KÜMESİ TEK BAŞINA FAZLA GEVŞEK. Ölçüldü: "netenhay"
    # araması 42 sonuç getirdi ve ilki Netanyahu'yla ilgisizdi.
    # Yazım hataları kelimenin BAŞINI genelde doğru yazıyor; ilk üç
    # harfin tutması şartı alakasızları eliyor
    # ("net…"/"net…" geçer, "net…"/"hay…" geçmez).
    if a[:3] != b[:3]:
        return False
    A, B = set(a), set(b)
    return len(A & B) / len(A | B) >= HARF_BENZERLIGI


def _yazim_toleransli_skor(haber, kelimeler: list[str]) -> int:
    """`_arama_skoru`nun yazım hatasına toleranslı hâli."""
    baslik = dogrula._sadelestir(haber["baslik_orj"] or "")
    ozet = dogrula._sadelestir(haber["ozet_orj"] or "")
    skor = 0
    for k in kelimeler:
        k = dogrula._sadelestir(k).strip()
        if not k:
            continue
        if any(_yazim_yakin_mi(k, s) for s in baslik.split()):
            skor += 10
        elif any(_yazim_yakin_mi(k, s) for s in ozet.split()):
            skor += 2
    return skor


def _arama_skoru(haber, kelimeler: list[str]) -> int:
    """
    Arama isabetini artıran basit skor.

    ⚠️ NEDEN GEREKTİ: yalnızca "kelime geçiyor mu" bakmak alakasız
    sonuç veriyordu. Ölçüldü (20 Ağu 2026): "/haber asgari ücret"
    aramasında dönen 3 haberin hiçbiri asgari ücretle ilgili değildi
    — kelimeler özet metninde ayrı bağlamlarda geçiyordu.

    Başlıkta geçmek özette geçmekten çok daha güçlü bir sinyal.

    ⚠️ TÜRKÇE "İ" TUZAĞI — ARAMA BU YÜZDEN ÇALIŞMIYORDU (20 Ağu 2026).
    Python'da `"İsrail".lower()` → `"i̇srail"` üretiyor: küçük i'nin
    ARDINDAN ayrı bir birleştirme noktası (U+0307) geliyor. Kullanıcının
    yazdığı düz "israil" bu diziyle EŞLEŞMİYOR.

    Sonuç: havuzda 71 İsrail haberi varken `/haber israil` "bulunamadı"
    diyordu. Aynı tuzak "İstanbul", "İzmir", "İngiltere" için de
    geçerli — yani en çok aranacak kelimelerin bir kısmı tamamen
    görünmezdi.

    Çözüm `dogrula._sadelestir`: Türkçe harfleri indirgiyor ve
    birleştirme işaretlerini atıyor, böylece "israil" ↔ "İsrail"
    eşleşiyor. Aynı fonksiyon başlık denetiminde de kullanılıyor.
    """
    baslik = dogrula._sadelestir(haber["baslik_orj"] or "")
    ozet = dogrula._sadelestir(haber["ozet_orj"] or "")
    skor = 0
    for k in kelimeler:
        k = dogrula._sadelestir(k).strip()
        if not k:
            continue
        if k in baslik:
            skor += 10
        elif k in ozet:
            skor += 2
    return skor


def haber_ara(con, ayarlar, komut: str) -> int:
    """
    `/haber <konu>` — havuzda arama yapıp bulunanları öneri olarak sunar.

    ⚠️ KULLANICININ YAZDIĞI METİNDEN POST ÜRETİLMİYOR. Projenin en
    temel kuralı "yalnızca kaynak metinde yazanı kullan, uydurma"
    (bkz. CLAUDE.md Adım 2). Tek cümlelik bir istekten haber metni
    üretmek tam da o kuralın yasakladığı şey olurdu — üstelik en
    tehlikeli biçimde, çünkü çıktı gerçek bir haber gibi görünür.

    Bunun yerine havuzdaki GERÇEK haberlerde arama yapılıyor. Seçilen
    haberin metni her zaman kendi kaynağından üretiliyor.
    """
    konu = komut.split(":", 1)[1].strip() if ":" in komut else ""
    if len(konu) < 3:
        telegram_bot.mesaj_gonder("Aramak istediğin konuyu yaz:\n"
                                  "/haber galatasaray transfer")
        return 1

    kelimeler = [k for k in konu.lower().split() if len(k) >= 3][:5]
    if not kelimeler:
        telegram_bot.mesaj_gonder(f"'{konu}' araması çok kısa.")
        return 1

    # ⚠️ ELEME SQL'DE DEĞİL PYTHON'DA — SQLite Türkçe bilmiyor.
    #
    # Önce `lower(baslik_orj) LIKE '%israil%'` kullanılıyordu ve arama
    # ÇALIŞMIYORDU: SQLite'ın `lower()` fonksiyonu ASCII-only, "İ"yi
    # dönüştürmüyor. Üstelik Python'un `.lower()`'ı da "İsrail"i
    # "i̇srail" yapıyor (i + birleştirme noktası U+0307), yani iki
    # taraftan birden eşleşme kaçıyordu.
    #
    # Ölçüldü (20 Ağu 2026): havuzda 71 İsrail haberi varken
    # `/haber israil` "bulunamadı" diyordu. Aynı tuzak İstanbul, İzmir,
    # İngiltere için de geçerliydi.
    #
    # Havuz son 3 günle sınırlı (~1600 kayıt); Python'da elemek ucuz ve
    # `dogrula._sadelestir` Türkçe'yi doğru indirgiyor.
    havuz = list(con.execute(
        """SELECT * FROM haberler
           WHERE durum NOT IN ('yayinlandi', 'onay_bekliyor')
             AND cekilme_zamani > datetime('now', '-3 day')
           ORDER BY yayin_tarihi DESC""",
    ))
    ham = [h for h in havuz if _arama_skoru(h, kelimeler) > 0][:30]
    ham.sort(key=lambda h: _arama_skoru(h, kelimeler), reverse=True)

    # ⚠️ HİÇ SONUÇ YOKSA YAZIM HATASI OLABİLİR. 21 Ağu 2026: kullanıcı
    # "netenyahu" yazdı, havuzda 22 Netanyahu haberi vardı ama tam
    # eşleşme tutmadı ve "havuzda yok" cevabı geldi.
    yazim_duzeltildi = False
    if not ham:
        ham = [h for h in havuz
               if _yazim_toleransli_skor(h, kelimeler) > 0][:30]
        ham.sort(key=lambda h: _yazim_toleransli_skor(h, kelimeler),
                 reverse=True)
        yazim_duzeltildi = bool(ham)
        if yazim_duzeltildi:
            log.info("'%s' tam eşleşmedi, yazım toleransıyla %s sonuç",
                     konu, len(ham))

    # ⚠️ Hiçbir kelimesi BAŞLIKTA geçmeyenler (skor < 10) eleniyor.
    # Ölçüldü: "/haber asgari ücret" bu eşik olmadan üç alakasız haber
    # döndürüyordu — kelimeler özet metninde ayrı bağlamlarda geçiyordu.
    # Alakasız sonuç göstermek, "bulunamadı" demekten kötü: kullanıcı
    # yanlış haberi seçip yayınlayabilir.
    # ⚠️ SKOR FONKSİYONU, HABERİN NASIL BULUNDUĞUYLA AYNI OLMALI.
    # 21 Ağu 2026: yazım toleransı eklendi, fuzzy 24 haber buluyordu
    # ama bu satır onları TAM EŞLEŞME skoruyla süzüyordu — hepsi 0
    # alıp eleniyordu ve arama yine "bulunamadı" diyordu. Fuzzy
    # çalışıyordu, sonucunu bir alt satır siliyordu.
    skorla = _yazim_toleransli_skor if yazim_duzeltildi else _arama_skoru
    guclu = [h for h in ham if skorla(h, kelimeler) >= 10]

    # Aynı olayın farklı kaynaklardan gelen kopyalarını ele.
    #
    # ⚠️ ARANAN KELİMELER KARŞILAŞTIRMAYA GİRMİYOR. Kullanıcı "mavi
    # vatan" arayınca çıkan HER sonuç doğal olarak "mavi" ve "vatan"
    # kelimelerini taşıyor; bunlar sayılınca alakasız iki haber bile
    # "aynı olay" görünüyordu ve 29 sonuçtan geriye 1 tane kalıyordu
    # (20 Ağu 2026, kullanıcı bildirdi).
    #
    # Aranan kelimeler çıkarılınca geriye haberi AYIRT EDEN kelimeler
    # kalıyor: "Gölcük'te başladı" ile "insansız deniz aracı" artık
    # farklı sayılıyor.
    aranan = {k.lower() for k in kelimeler}
    onceki, bulunan = [], []
    for h in guclu:
        kelime_kumesi, isimler = secim.konu_imzasi(h["baslik_orj"])
        kelime_kumesi = kelime_kumesi - aranan
        isimler = isimler - aranan
        if any(len(kelime_kumesi & ok) >= 2 and (isimler & oi)
               for ok, oi in onceki):
            continue
        onceki.append((kelime_kumesi, isimler))
        bulunan.append(h)
        if len(bulunan) >= 8:
            break

    if not bulunan:
        telegram_bot.mesaj_gonder(
            f"🔎 '{konu}' için havuzda haber bulunamadı.\n\n"
            f"Havuz son 3 günü kapsıyor. Haber çok yeniyse henüz "
            f"çekilmemiş olabilir — kontrol 90 dakikada bir çalışıyor.\n"
            f"Aşağıdaki düğmeyle havuzu hemen tazeleyebilirsin.",
            butonlar=[[{"text": "🔄 Haber havuzunu güncelle",
                        "callback_data": "havuz_guncelle"}]])
        return 0

    if yazim_duzeltildi:
        telegram_bot.mesaj_gonder(
            f"ℹ️ '{konu}' tam olarak bulunamadı, yazıma en yakın "
            "haberler gösteriliyor.")

    # Puanı olmayanları toplu puanla (ucuz: tek istek)
    puansiz = [h for h in bulunan if h["onem_puani"] is None]
    if puansiz:
        yeni = generate_text.basliklari_puanla(puansiz, ayarlar)
        for haber_id, puan in yeni.items():
            con.execute("UPDATE haberler SET onem_puani = ? WHERE id = ?",
                        (puan, haber_id))
        con.commit()
        bulunan = list(con.execute(
            "SELECT * FROM haberler WHERE id IN (%s)"
            % ",".join("?" * len(bulunan)),
            [h["id"] for h in bulunan],
        ))

    adaylar = [{"id": h["id"], "puan": h["onem_puani"] or 0,
                "baslik": h["baslik_orj"], "kaynak": h["kaynak"],
                "kategori": h["kategori"] or "-",
                "yayin_tarihi": h["yayin_tarihi"] or ""}
               for h in bulunan]
    # En güncel haberler en üstte, ardından puan sırasıyla
    adaylar.sort(key=lambda a: (a.get("yayin_tarihi") or "", a["puan"]), reverse=True)

    gosterilen_sayisi = min(len(adaylar), 6)
    telegram_bot.mesaj_gonder(
        f"🔎 '{konu}' için {len(adaylar)} haber bulundu (en güncel {gosterilen_sayisi} tanesi listeleniyor):")
    telegram_bot.oneri_gonder(adaylar, azami=6)
    db_senkron.hemen_kaydet(f"Haber araması: {konu[:40]}")
    log.info("'%s' araması: %d sonuç", konu, len(adaylar))
    return 0


def oneriyi_hazirla(con, ayarlar, komut: str, mesaj_id: int) -> int:
    """
    Telegram'da SEÇİLEN başlık önerilerini sırayla tam posta dönüştürür.

    Komut biçimi: "hazirla:1482" ya da "hazirla:1482,1490,1503".
    Çoklu seçim Worker'da yapılıyor (butonlara ✓ konuyor), buraya
    yalnızca sonuç geliyor.

    İKİ AŞAMALI AKIŞIN İKİNCİ ADIMI. Kontrol job'ı yalnızca başlıkları
    puanlayıp öneriyor; tam metin, görsel ve imgbb yüklemesi ancak
    burada — kullanıcı seçtikten sonra — yapılıyor.
    """
    try:
        ham = komut.split(":", 1)[1]
        haber_idler = [int(x) for x in ham.split(",") if x.strip()]
    except (IndexError, ValueError):
        log.error("geçersiz hazırla komutu: %s", komut)
        return 1
    if not haber_idler:
        return 1

    basliklar = {}
    for hid in haber_idler:
        r = con.execute("SELECT baslik_orj FROM haberler WHERE id = ?",
                        (hid,)).fetchone()
        if r:
            basliklar[hid] = (r["baslik_orj"] or "")[:60]

    if not basliklar:
        telegram_bot.sonucu_yaz(
            mesaj_id, "⚠️ Seçilen haberler bulunamadı "
                      "(veritabanı güncellenmiş olabilir).")
        return 1

    telegram_bot.sonucu_yaz(
        mesaj_id,
        f"⏳ {len(basliklar)} haber hazırlanıyor:\n"
        + "\n".join(f"  • {b}" for b in basliklar.values())
        + "\n\nHer biri ayrı onay mesajı olarak gelecek.")

    # son_dakika akışını yeniden kullanıyoruz — görsel üretimi, imgbb
    # yüklemesi, doğrulama ve onay mesajı zaten orada.
    import son_dakika

    basarili, basarisiz = [], []
    for hid in haber_idler:
        if hid not in basliklar:
            continue
        # ⚠️ KİLİDİ BIRAK. `son_dakika.main` kendi bağlantısını açıp
        # yazıyor; bizim açık işlemimiz dururken "database is locked"
        # alıyordu. Commit hem kilidi bırakıyor hem o ana kadarki
        # değişiklikleri kalıcı kılıyor.
        con.commit()
        try:
            sonuc = son_dakika.main(zorla_haber_id=hid)
        except Exception as e:                        # noqa: BLE001
            log.exception("haber %s hazırlanamadı", hid)
            sonuc = 1

        # ⚠️ DÖNÜŞ DEĞERİNE DEĞİL, GERÇEK ETKİYE BAK.
        #
        # 21 Ağu 2026: kullanıcı iki haber seçti, `main` 15 saniyede
        # `0` (başarı) döndü ve hiçbir şey üretmedi — günlük sayaç
        # yanlış hesaplandığı için sessizce çıkmıştı. Kullanıcı
        # "hazırlanıyor" yazısında kaldı, kimse bir şey söylemedi.
        #
        # "Başarılı" demek yetmiyor: haber gerçekten onaya sunuldu mu?
        # Bunun tek kanıtı veritabanındaki durum.
        taze = con.execute(
            "SELECT durum, telegram_message_id FROM haberler WHERE id = ?",
            (hid,)).fetchone()
        gercekten_oldu = bool(
            taze and taze["durum"] in ("onay_bekliyor", "yayinlandi")
            and taze["telegram_message_id"])

        if sonuc == 0 and not gercekten_oldu:
            log.error("haber %s: 'başarılı' dönüldü ama post üretilmedi "
                      "(durum=%s)", hid, taze["durum"] if taze else "?")
            sonuc = 1

        if sonuc == 0:
            basarili.append(basliklar[hid])
        else:
            basarisiz.append((hid, basliklar[hid]))

    if basarisiz:
        # ⚠️ TEKRAR DENEME DÜĞMESİ ŞART. Önce yalnızca düz metin
        # gönderiliyordu ve kullanıcı hazırlanamayan haberi bir daha
        # deneyemiyordu — öneri mesajının butonları da silinmiş
        # oluyordu, yani haber tamamen erişilemez hale geliyordu.
        # Hataların çoğu geçici (Gemini kotası, Instagram medya
        # indirme), yani tekrar denemek gerçekten çözüyor.
        idler = ",".join(str(hid) for hid, _ in basarisiz)
        telegram_bot.mesaj_gonder(
            f"⚠️ {len(basarisiz)} haber hazırlanamadı:\n"
            + "\n".join(f"  • {b}" for _, b in basarisiz)
            + ("\n\nDiğerleri onayına sunuldu." if basarili else "")
            + "\n\nHataların çoğu geçicidir (kota, medya indirme).",
            [[{"text": f"🔄 {len(basarisiz)} haberi tekrar dene",
               "callback_data": f"hazirla:{idler}"}]])
    return 0 if basarili else 1



def tura_birak(con, haberler, mesaj_id, basan) -> int:
    """
    Haberi TEKİL post adaylığından çıkarır, carousel turunda bırakır.

    ⚠️ "Bu turu atla"dan farkı: atla haberi havuza döndürüyor
    (`durum='metin_hazir'`, `son_dakika=0`) ve haber bir sonraki
    kontrolde YİNE tekil aday oluyordu. 20 Ağu 2026'da "Türkiye'de
    yağışlar son 66 yılın zirvesinde" haberi 23 dakika arayla iki kez
    onaya sunuldu; kullanıcı aynı haberi tekrar tekrar görüyordu.

    Bu komut `sadece_tur = 1` işareti koyuyor: haber havuzda kalıyor ve
    10'lu turda yarışmaya devam ediyor, ama bir daha tekil post olarak
    sunulmuyor.
    """
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


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")

    komut = os.getenv("KOMUT", "").strip()
    mesaj_id = int(os.getenv("MESAJ_ID", "0") or 0)
    basan = os.getenv("BASAN", "").strip()
    kanallar = os.getenv("KANALLAR", "").strip()
    metin = os.getenv("METIN", "").strip()

    if not komut:
        log.error("KOMUT eksik")
        return 1

    # ⚠️ `/durum` bir onay mesajına BAĞLI DEĞİL, dolayısıyla `mesaj_id`
    # taşımıyor. Eskiden kontrol ikisini birden şart koşuyordu ve komut
    # aşağıdaki kendi dalına HİÇ ULAŞAMIYORDU — `/durum` yazınca Worker
    # "Durum sorgulanıyor…" diyor, job ise sessizce hata verip ölüyordu.
    # ⚠️ PARAMETRELİ KOMUTLARDA ÖN EKE BAK. `/haber istanbulda hava`
    # buraya `ara:istanbulda hava` olarak geliyor; düz üyelik testi
    # ("ara" listede mi) tutmuyordu ve komut "MESAJ_ID eksik" ile
    # ölüyordu. 20 Ağu 2026'da `/haber` denendiğinde tam olarak bu oldu.
    if (komut.split(":", 1)[0] not in MESAJSIZ_KOMUTLAR
            and komut not in MESAJSIZ_KOMUTLAR and not mesaj_id):
        log.error("MESAJ_ID eksik (komut=%s)", komut)
        return 1

    global _ayarlar_onbellek
    ayarlar = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    _ayarlar_onbellek = ayarlar
    db.kur()
    con = db.baglan()
    ayar.uygula(con, ayarlar)

    # /durum haberlerden bağımsız çalışıyor — onay bekleyen tur olmasa da
    # cevap vermeli, zaten "bir şey var mı?" diye sorulan komut bu.
    if komut == "durum":
        return durum_bildir(con, ayarlar)

    # ⚠️ AYAR KOMUTLARI TURDAN BAĞIMSIZ ve `turu_getir`DEN ÖNCE olmalı.
    # İkinci sebep daha ince: "ayar:genel.gece_otomatik_yayin" içinde ":"
    # var; aşağıdaki `":" in komut` dalına düşerse slayt işlemi sanılıp
    # `int(sira)` çağrısında patlar.
    # ⚠️ BU KOMUTLAR TUR MESAJ ID'SİNİ KENDİ İÇİNDE TAŞIYOR ve ayrı bir
    # mesajın düğmesinden geliyor. `mesaj_id` (Worker'ın gönderdiği)
    # alternatif mesajını işaret ediyor, turu DEĞİL — bu yüzden
    # `turu_getir` kontrolünden önce ele alınmalılar.
    if komut.startswith("haber_sec:"):
        _, eski_id, yeni_id, tur_mid = komut.split(":")
        tur = turu_getir(con, int(tur_mid))
        if not tur:
            telegram_bot.mesaj_gonder("⚠️ Değiştirilecek tur bulunamadı.")
            return 1
        return haberi_degistir_uygula(con, ayarlar, tur, int(eski_id),
                                      int(yeni_id), int(tur_mid))
    # ⚠️ Görsel önizleme düğmeleri tur id'sini KOMUTTA taşıyor
    # ("gorsel_kabul:3:656"); Worker'ın gönderdiği mesaj_id önizleme
    # mesajına ait ve turu göstermiyor.
    if (komut.startswith("gorsel_kabul:")
            or komut.startswith("gorsel_yeni:")) and komut.count(":") == 2:
        ad, sira, tur_mid = komut.split(":")
        tur = turu_getir(con, int(tur_mid))
        if not tur:
            telegram_bot.mesaj_gonder(
                "⚠️ Görseli değiştirilecek tur bulunamadı.")
            return 0
        if ad == "gorsel_kabul":
            return gorseli_kabul_et(con, ayarlar, tur, int(sira), int(tur_mid))
        return slayt_islemi(con, ayarlar, tur, "slayt_foto",
                            int(sira), int(tur_mid))

    if komut.startswith("retry_kanal:"):
        parcalar = komut.split(":")
        hedef_kanal = parcalar[1]
        hedef_mid = int(parcalar[2]) if len(parcalar) > 2 else mesaj_id
        tur = turu_getir(con, hedef_mid)
        return kanal_telafi_et(con, ayarlar, tur, hedef_mid, hedef_kanal, basan)

    if komut.startswith("yayin_kontrol:"):
        return yayin_durumu_kontrol(con, ayarlar, int(komut.split(":")[1]))
    if komut.startswith("yeniden_yayinla:"):
        return yeniden_yayinla(con, ayarlar, int(komut.split(":")[1]), basan)
    if komut.startswith("kurtar:"):
        hedef_mid = int(komut.split(":")[1])
        menuyu_geri_koy(con, hedef_mid)
        _albumu_yenile(con, hedef_mid)
        telegram_bot.mesaj_gonder(
            f"🔄 <b>#{hedef_mid} Numaralı Tur Başarıyla Kurtarıldı!</b>\n\n"
            f"Onay butonları yeniden mesaja bağlandı ve slayt albümü tazelendi. "
            f"Yukarıdaki mesajdan yayını başlatabilir veya düzenleyebilirsiniz.",
            html=True,
        )
        return 0

    if komut.startswith("haber_vazgec:"):
        menuyu_geri_koy(con, int(komut.split(":")[1]))
        telegram_bot.mesaj_gonder("Haber değiştirilmedi.")
        return 0

    if komut in ("yonetim", "yonetim_panel"):
        return yonetim_paneli_goster(con, ayarlar, mesaj_id)
    if komut.startswith("duraklat:"):
        saat = int(komut.split(":")[1])
        return yonetim_duraklat_uygula(con, ayarlar, saat, mesaj_id, basan)
    if komut == "devam_et":
        return yonetim_devam_et_uygula(con, ayarlar, mesaj_id, basan)
    if komut == "saglik_testi":
        return yonetim_saglik_testi_uygula(ayarlar, mesaj_id)
    if komut == "kota_raporu":
        return yonetim_kota_raporu_uygula(con, ayarlar, mesaj_id)
    if komut == "tur_temizle":
        return yonetim_tur_temizle_uygula(con, ayarlar, mesaj_id)
    if komut == "duraklat_menu":
        menu = telegram_bot.duraklatma_secenekleri_menusu()
        telegram_bot.paneli_tazele(
            mesaj_id,
            "⏸️ <b>BOTU DURAKLATMA SEÇENEKLERİ</b>\n\n"
            "Botu ne kadar süreyle duraklatmak istersiniz?\n"
            "Duraklatma süresince otomatik turlar, hatırlatmalar ve son dakika kontrolleri askıya alınır.",
            menu["inline_keyboard"],
        )
        return 0
    if komut == "tur_hazirla":
        from scripts import hazirla
        telegram_bot.mesaj_gonder("🔄 Gündem turu sıfırdan hazırlanıyor...")
        return hazirla.main()
    if komut == "ekonomi_hazirla":
        from scripts import ekonomi_turu
        telegram_bot.mesaj_gonder("📈 Ekonomi & Finans turu sıfırdan hazırlanıyor...")
        return ekonomi_turu.main()

    if komut == "ayar":
        return ayar_paneli(con, ayarlar)
    if komut == "havuz_guncelle":
        return havuzu_guncelle(con, ayarlar)
    if komut == "tamamla":
        return zinciri_tamamla(con, ayarlar)
    # ── Tekil post ÖNERİSİ ──────────────────────────────────────
    # Bu komutlar bir TURA bağlı değil: öneri mesajı henüz tur değil,
    # yalnızca başlık listesi. Haber id'si komutun içinde geliyor.
    if komut.startswith("ara:"):
        return haber_ara(con, ayarlar, komut)
    if komut.startswith("hazirla:"):
        return oneriyi_hazirla(con, ayarlar, komut, mesaj_id)
    if komut == "oneri_gec":
        telegram_bot.sonucu_yaz(mesaj_id, "⏭ Öneri geçildi.")
        log.info("öneri geçildi")
    # ── Özel Haber Komutları (/link, /arastir, /ozel) ──────────
    if komut.startswith("link:"):
        from src import ozel_haber
        return ozel_haber.linkten_haber_uret(komut.split(":", 1)[1], con, ayarlar, basan)

    if komut.startswith("arastir:"):
        from src import ozel_haber
        return ozel_haber.arastir_haber_uret(komut.split(":", 1)[1], con, ayarlar, basan)

    if komut.startswith("ozel:"):
        from src import ozel_haber
        return ozel_haber.ozel_metin_haber_uret(komut.split(":", 1)[1], con, ayarlar, basan)

    if komut.startswith("faiz:"):
        from src import ozel_haber
        return ozel_haber.makro_haber_uret(komut.split(":", 1)[1], con, ayarlar, basan, veri_tipi="faiz")

    if komut.startswith("enflasyon:"):
        from src import ozel_haber
        return ozel_haber.makro_haber_uret(komut.split(":", 1)[1], con, ayarlar, basan, veri_tipi="enflasyon")

    if komut.startswith("fed:"):
        from src import ozel_haber
        return ozel_haber.makro_haber_uret(komut.split(":", 1)[1], con, ayarlar, basan, veri_tipi="fed")

    if komut.startswith("makro:"):
        from src import ozel_haber
        return ozel_haber.makro_haber_uret(komut.split(":", 1)[1], con, ayarlar, basan, veri_tipi="makro")

    if komut == "durum":
        return durum_bildir(con, ayarlar)

    if komut in ("hata:sondakika_tekrar", "sondakika", "son_dakika"):
        from scripts import son_dakika
        telegram_bot.mesaj_gonder("🔍 Son dakika kontrolü yapılıyor, havuz ve kaynaklar taranıyor…")
        sonuc = son_dakika.main()
        acik_sayisi = con.execute("SELECT COUNT(*) FROM haberler WHERE durum = 'onay_bekliyor' AND son_dakika = 1").fetchone()[0]
        if acik_sayisi == 0:
            telegram_bot.mesaj_gonder(
                "ℹ️ <b>Son dakika taraması tamamlandı.</b>\n\n"
                "Havuzdaki ve RSS beslemelerindeki en sıcak haberler incelendi ancak şu an "
                "son dakika eşiğini (8+/10) aşan yeni bir acil haber bulunamadı.\n"
                "Sıcak bir gelişme olduğunda sistem otomatik olarak bildirecektir.",
                html=True,
            )
        return sonuc

    if komut == "haftalik":
        from scripts import haftalik_ozet
        telegram_bot.mesaj_gonder("🗓️ Haftalık Pazar özeti hazırlanıyor, son 7 günün manşetleri derleniyor…")
        return haftalik_ozet.main()

    if komut in ("video", "reels"):
        from src import video
        telegram_bot.mesaj_gonder("🎬 Son turun 9:16 MP4 Reels videosu hazırlanıyor…")
        
        # Son açık veya yayınlanan turun slaytlarını bul
        satirlar = con.execute(
            "SELECT gorsel_yolu FROM haberler WHERE gorsel_yolu IS NOT NULL "
            "ORDER BY gonderim_zamani DESC, slayt_sirasi ASC LIMIT 10"
        ).fetchall()
        
        yollar = [s["gorsel_yolu"] for s in satirlar if s["gorsel_yolu"] and Path(s["gorsel_yolu"]).exists()]
        if not yollar:
            # Fallback: data/output klasöründeki en son slaytları al
            yollar = [str(p) for p in sorted(Path("data/output").glob("slayt-*.jpg"))[:6]]
        
        if not yollar:
            telegram_bot.mesaj_gonder("⚠️ Video üretilecek slayt görseli bulunamadı.")
            return 0
            
    if komut in ("piyasa", "piyasa_ozet"):
        from src import piyasa
        pv = piyasa.piyasa_verileri_getir()
        satirlar = ["📈 <b>CANLI PİYASA & BORSA ÖZETİ</b>\n"]
        if "bist100" in pv:
            b = pv["bist100"]
            yon = "🟢 +" if b['degisim'] >= 0 else "🔴 "
            satirlar.append(f"• <b>BİST 100:</b> {b['fiyat']:,.2f} ({yon}%{b['degisim']:.2f})")
        if "dolar" in pv:
            d = pv["dolar"]
            yon = "🟢 +" if d['degisim'] >= 0 else "🔴 "
            satirlar.append(f"• <b>Dolar/TL:</b> {d['fiyat']:.2f} ₺ ({yon}%{d['degisim']:.2f})")
        if "euro" in pv:
            e = pv["euro"]
            yon = "🟢 +" if e['degisim'] >= 0 else "🔴 "
            satirlar.append(f"• <b>Euro/TL:</b> {e['fiyat']:.2f} ₺ ({yon}%{e['degisim']:.2f})")
        if "gram_altin" in pv:
            g = pv["gram_altin"]
            yon = "🟢 +" if g['degisim'] >= 0 else "🔴 "
            satirlar.append(f"• <b>Gram Altın:</b> {g['fiyat']:,.2f} ₺ ({yon}%{g['degisim']:.2f})")
        if "btc" in pv:
            btc = pv["btc"]
            yon = "🟢 +" if btc['degisim'] >= 0 else "🔴 "
            satirlar.append(f"• <b>Bitcoin:</b> ${btc['fiyat']:,.0f} ({yon}%{btc['degisim']:.2f})")
        if "brent" in pv:
            br = pv["brent"]
            yon = "🟢 +" if br['degisim'] >= 0 else "🔴 "
            satirlar.append(f"• <b>Brent Petrol:</b> ${br['fiyat']:.2f} ({yon}%{br['degisim']:.2f})")

        from src.zaman import tr_format, su_an_tr
        satirlar.append(f"\n⏰ <i>Canlı Piyasa: {tr_format(su_an_tr(), 'canli')}</i>")
        telegram_bot.mesaj_gonder("\n".join(satirlar), html=True)
        return 0

    if komut.startswith("hisse:") or komut.startswith("kripto:"):
        from src import piyasa
        from src.zaman import tr_format, su_an_tr
        sembol = komut.split(":", 1)[1].strip()
        veri = piyasa.varlik_sorgula(sembol)
        if not veri:
            telegram_bot.mesaj_gonder(
                f"⚠️ <b>{sembol.upper()}</b> sembolü bulunamadı veya veri alınamadı.\n"
                f"Örnek: <code>/hisse THYAO</code>, <code>/hisse ASELS</code>, <code>/kripto BTC</code>, <code>/hisse NVDA</code>",
                html=True,
            )
            return 0

        yon = "🟢 +" if veri["degisim"] >= 0 else "🔴 "
        para = "₺" if veri["currency"] == "TRY" else ("$" if veri["currency"] == "USD" else veri["currency"])
        fiyat_str = piyasa.turkce_sayi(veri["fiyat"], 2)
        yuksek_str = piyasa.turkce_sayi(veri["gun_yuksek"], 2)
        dusuk_str = piyasa.turkce_sayi(veri["gun_dusuk"], 2)

        satirlar = [
            f"📊 <b>CANLI FİNANS SORGUSU: {veri['ad']}</b>\n",
            f"💰 <b>Anlık Fiyat:</b> {fiyat_str} {para} ({yon}%{veri['degisim']:.2f})",
            f"📈 <b>Gün İçi En Yüksek:</b> {yuksek_str} {para}",
            f"📉 <b>Gün İçi En Düşük:</b> {dusuk_str} {para}",
            f"🏷️ <b>Sembol / Borsa:</b> <code>{veri['sembol']}</code>",
            f"\n⏰ <i>Canlı Veri: {tr_format(su_an_tr(), 'canli')}</i>",
        ]
        telegram_bot.mesaj_gonder("\n".join(satirlar), html=True)
        return 0

    if komut in ("sonpostlar", "son_postlar"):
        from src.zaman import tr_format, goreceli_zaman
        satirlar_db = con.execute(
            "SELECT ig_baslik, durum, yayin_tarihi, telegram_message_id "
            "FROM haberler WHERE durum = 'yayinlandi' "
            "GROUP BY telegram_message_id ORDER BY yayin_tarihi DESC LIMIT 5"
        ).fetchall()
        if not satirlar_db:
            telegram_bot.mesaj_gonder("ℹ️ Henüz yayınlanmış bir tur kaydı bulunamadı.")
            return 0

        rapor = ["📰 <b>SON YAYINLANAN POSTLAR & KANALLAR</b>\n"]
        for idx, s in enumerate(satirlar_db, start=1):
            baslik = s["ig_baslik"] or "Daily Brief Haber Turu"
            tarih_str = tr_format(s["yayin_tarihi"], "tam") if s["yayin_tarihi"] else "Yeni"
            goreceli = goreceli_zaman(s["yayin_tarihi"])
            goreceli_ek = f" ({goreceli})" if goreceli else ""
            rapor.append(
                f"{idx}. <b>{html.escape(baslik[:65])}</b>\n"
                f"   ⏰ <i>{tarih_str}{goreceli_ek}</i> · ✅ Instagram, Threads, FB, X\n"
            )
        rapor.append("🔗 <i>Sosyal medya hesaplarından canlı görüntüleyebilirsiniz.</i>")
        telegram_bot.mesaj_gonder("\n".join(rapor), html=True)
        return 0

    if komut in ("bulten", "kahve"):
        sinir = datetime.now(timezone.utc) - timedelta(hours=36)
        taze = con.execute(
            "SELECT ig_baslik, ig_ozet, onem_puani, kategori FROM haberler "
            "WHERE durum = 'metin_hazir' AND yayin_tarihi >= ? "
            "ORDER BY onem_puani DESC LIMIT 5",
            (sinir.isoformat(),),
        ).fetchall()
        if not taze:
            telegram_bot.mesaj_gonder("ℹ️ Havuzda şu an taze özetlenecek haber yok. <code>/guncelle</code> yazarak tarayabilirsin.", html=True)
            return 0

        satirlar = ["☕ <b>DAILY BRIEF ANLIK HABER BÜLTENİ</b>\n"]
        for idx, h in enumerate(taze, start=1):
            kat = f"[{h['kategori'].upper()}] " if h.get("kategori") else ""
            satirlar.append(f"<b>{idx}. {kat}{h['ig_baslik']}</b>\n{h['ig_ozet']}\n")
        satirlar.append("<i>Bu haberler onay bekleyen tur havuzundan canlı derlenmiştir.</i>")
        telegram_bot.mesaj_gonder("\n".join(satirlar), html=True)
        return 0

    if komut in ("hata:tur_tekrar", "tur_tekrar"):
        from scripts import ekonomi_turu
        telegram_bot.mesaj_gonder("🔄 Ekonomi & Piyasa turu sıfırdan hazırlanıyor...")
        return ekonomi_turu.main()

    if komut == "hata:tur_metinsiz":
        from scripts import hazirla
        telegram_bot.mesaj_gonder("🧯 Havuzdaki hazır metinlerle tur kuruluyor...")
        return hazirla.main()

    if komut in ("hata:ayrinti", "ayrinti"):
        son_hata_dosya = Path("data") / "son_hata.txt"
        icerik = ""
        if son_hata_dosya.exists():
            icerik = son_hata_dosya.read_text(encoding="utf-8").strip()
        if not icerik:
            icerik = "Kayıtlı detaylı hata izi bulunamadı veya temizlendi."
        telegram_bot.mesaj_gonder(
            f"📄 <b>DETAYLI HATA RAPORU / TRACEBACK</b>\n\n<code>{html.escape(icerik[:3500])}</code>",
            html=True,
        )
        return 0

    if komut.startswith("ayarsec:"):
        return ayar_degistir(con, ayarlar, komut.split(":", 1)[1],
                             mesaj_id, basan)

    haberler = turu_getir(con, mesaj_id)

    # YARIŞ DURUMU KORUMASI: turu hazırlayan job veritabanını henüz
    # push etmemiş olabilir. Bu job checkout'u ondan önce yapmışsa turu
    # göremiyor. Bir kez en güncel hâli çekip tekrar bakıyoruz.
    if not haberler:
        log.warning("tur bulunamadı, güncel veritabanı çekiliyor…")
        if db_senkron.uzaktan_tazele():
            con.close()
            con = db.baglan()
            haberler = turu_getir(con, mesaj_id)
            if haberler:
                log.info("tur güncel veritabanında bulundu")

    if not haberler:
        # ⚠️ BU BİR SİSTEM HATASI DEĞİL — çoğu zaman kullanıcı ESKİ bir
        # mesajın düğmesine basıyor. Tur o arada kapanmış, atlanmış veya
        # yayınlanmış oluyor ve `telegram_message_id` temizlenmiş
        # oluyor. Eskiden `return 1` veriliyordu: job kırmızı görünüyor,
        # hata bildirimi düşüyor ve gerçek arızalar arasında kayboluyordu.
        #
        # Kullanıcıya yararlı olan şey ne olduğunu ve şu an neyin açık
        # olduğunu söylemek.
        acik = list(con.execute(
            "SELECT telegram_message_id mid, COUNT(*) n, MIN(durum) d "
            "FROM haberler WHERE telegram_message_id IS NOT NULL "
            "AND durum IN ('onay_bekliyor', 'baslik_onayi', 'ertelendi') "
            "GROUP BY telegram_message_id ORDER BY mid DESC LIMIT 1"))
        if acik:
            a = acik[0]
            asama = ("başlık onayı" if a["d"] == "baslik_onayi"
                     else "yayın onayı")
            ek = (f"\n\n✅ Şu an açık tur var: {a['n']} haber, {asama} "
                  "aşamasında. Sohbetin altındaki mesajı kullan.")
        else:
            ek = "\n\nŞu an açık tur yok. Yeni tur için /tur yazabilirsin."

        log.warning("mesaj_id=%s artık geçerli değil (eski mesaj)", mesaj_id)
        try:
            telegram_bot.sonucu_yaz(
                mesaj_id,
                "ℹ️ <b>Bu mesaj artık geçerli değil.</b>\n"
                "Gönderi kapanmış, atlanmış ya da yayınlanmış olabilir." + ek,
            )
        except Exception:
            telegram_bot.mesaj_gonder(
                "ℹ️ Bu mesaj artık geçerli değil.\n"
                "Gönderi kapanmış, atlanmış ya da yayınlanmış olabilir." + ek
            )
        # Sistem hatası olmadığı için job BAŞARILI sayılıyor.
        return 0

    try:
        # ⚠️ YAYINLANMIŞ TUR ÜZERİNDE DEĞİŞTİRİCİ İŞLEM YAPILAMAZ.
        #
        # 20 Ağu 2026: "Türkiye'de yağışlar son 66 yılın zirvesinde"
        # haberi 09:59'da başarıyla yayınlandı (Instagram + Facebook +
        # story + Threads 4/4, veritabanı push edildi). Bir dakika
        # sonra aynı onay mesajından `ertele` komutu geldi ve
        # YAYINLANMIŞ haberin durumunu `ertelendi` yaptı. Haber havuza
        # döndü, sistem onu "yayınlanmamış" sandı ve aynı gün iki kez
        # daha tekil post olarak onaya sundu.
        #
        # Kullanıcı postu Instagram'da görüyor ama bot bilmiyordu.
        # `turu_getir` durum filtresi yapmıyor, bu yüzden koruma burada.
        #
        # "kaldir" hariç: o komut zaten yayınlanmış turu hedefliyor.
        DEGISTIRICI = {"yayinla", "iptal", "ertele", "tura_birak",
                       "metin_yenile", "plan_iptal"}
        if (komut in DEGISTIRICI or komut.startswith("slayt_")
                or komut.startswith("yayinla_sonra:")
                or komut.startswith("haber_degistir:")
                or komut.startswith("haber_sec:")) and any(
                h["durum"] == "yayinlandi" for h in haberler):
            post = next((h["ig_post_id"] for h in haberler
                         if h["ig_post_id"]), None)
            baglanti = instagram.post_baglantisi(post, ayarlar) if post else ""
            log.warning("yayınlanmış tur üzerinde '%s' reddedildi", komut)
            telegram_bot.sonucu_yaz(
                mesaj_id,
                "⚠️ Bu tur ZATEN YAYINLANDI, işlem yapılmadı.\n\n"
                f"{baglanti or post or ''}\n\n"
                "Yayını geri almak için sonuç mesajındaki "
                "🗑 düğmesini kullan.")
            return 0

        # Başlık önizlemesinin düğmeleri
        if komut == "tur_onayla":
            return tur_onayla(con, ayarlar, haberler, mesaj_id)
        if komut == "tur_yeniden":
            return tur_yeniden_sec(con, ayarlar, haberler, mesaj_id)

        if komut == "yayinla":
            # ⚠️ Başlık onayı aşamasındaki turun SLAYTI YOK. Bu düğme
            # o mesajda görünmüyor ama komut başka yoldan gelebilir
            # (eski mesaj, zamanlanmış yayın); slaytsız yayın denemesi
            # Instagram'da anlamsız bir hataya dönüşür.
            if haberler and haberler[0]["durum"] == "baslik_onayi":
                telegram_bot.mesaj_gonder(
                    "⚠️ Bu turun slaytları henüz üretilmedi. "
                    "Önce başlıkları onayla.")
                return 0
            return yayinla(con, ayarlar, haberler, mesaj_id, basan, kanallar=kanallar)
        if komut == "manuel_paket":
            ilk_h_dict = dict(haberler[0]) if haberler else {}
            if ilk_h_dict.get("tur") == "ekonomi" and ilk_h_dict.get("ig_caption"):
                metin = ilk_h_dict["ig_caption"]
            elif haberler[0]["son_dakika"]:
                metin = caption.son_dakika_caption(haberler[0], _sonuclari_kur(haberler), ayarlar)
            else:
                metin = caption.caption_kur(haberler, _sonuclari_kur(haberler), ayarlar=ayarlar)

            butonlar = {
                "inline_keyboard": [
                    [{"text": "📸 Instagram'ı Aç", "url": "https://instagram.com"}],
                    [{"text": "🚀 Diğer Kanallarda Yayınla (FB, Threads, X)", "callback_data": "yayinla_diger"}],
                    [{"text": "✅ Paylaştım (Tamamlandı Olarak İşaretle)", "callback_data": "manuel_tamam"}],
                    [{"text": "← Geri", "callback_data": f"yayin_geri:{len(haberler)}"}],
                ]
            }
            mesaj = (
                f"📲 <b>MANUEL INSTAGRAM PAYLAŞIM PAKETİ</b>\n\n"
                f"Aşağıdaki açıklama metnini kopyalayıp Instagram'da gönderi veya Reels olarak paylaşabilirsin:\n\n"
                f"<code>{metin}</code>\n\n"
                f"💡 <i>Görseller yukarıdaki Telegram albümünde hazır. Tek tıkla telefonunun galerisine kaydedebilirsin.</i>\n"
                f"Diğer sosyal ağlarda (Threads, FB, X) paylaşım hakkını kaybetmemek için aşağıdaki butonu kullanabilirsin."
            )
            telegram_bot.mesaj_gonder(mesaj, butonlar=butonlar["inline_keyboard"])
            return 0

        if komut == "yayinla_diger":
            # Instagram'ı atlayıp FB, Threads, X'e yayınla
            return yayinla(con, ayarlar, haberler, mesaj_id, basan, kanallar="story,threads,facebook,twitter")

        if komut == "manuel_tamam":
            simdi = datetime.now(timezone.utc).isoformat()
            for h in haberler:
                con.execute(
                    "UPDATE haberler SET durum = 'yayinlandi', yayin_tarihi = ?, daha_once_yayinlandi = 1 WHERE id = ?",
                    (simdi, h["id"]),
                )
            con.commit()
            telegram_bot.sonucu_yaz(
                mesaj_id,
                f"✅ <b>MANUEL PAYLAŞIM TAMAMLANDI</b>\n\n"
                f"Haberler veritabanında yayınlandı olarak işaretlendi.\n\n"
                f"Onaylayan: {basan or 'bilinmiyor'}",
                bildir=True,
            )
            return 0
        if komut == "tura_birak":
            return tura_birak(con, haberler, mesaj_id, basan)
        if komut == "iptal":
            return iptal(con, haberler, mesaj_id, basan)
        if komut == "cope_at":
            return cope_at(con, haberler, mesaj_id, basan)
        if komut == "kaldir":
            return yayindan_kaldir(con, ayarlar, haberler, mesaj_id, basan)
        if komut == "ertele":
            return ertele(con, mesaj_id, basan)
        if komut == "plan_iptal":
            return plani_iptal_et(con, mesaj_id, basan)
        if komut.startswith("yayinla_sonra:"):
            return yayin_planla(con, ayarlar, haberler,
                                int(komut.split(":")[1]), mesaj_id, basan,
                                kanallar=kanallar)
        if komut == "foto_degistir":
            return foto_degistir_islemi(con, ayarlar, haberler, mesaj_id, basan)
        if komut == "metin_yenile":
            return metin_yenile(con, ayarlar, haberler, mesaj_id)
        if komut == "metin_duzenle":
            sonuc = metin_duzenle(con, ayarlar, haberler, mesaj_id, metin, basan)
            menuyu_geri_koy(con, mesaj_id)
            return sonuc
        if komut == "havuzdan_ekle":
            sonuc = havuzdan_haber_ekle(con, ayarlar, haberler, mesaj_id)
            menuyu_geri_koy(con, mesaj_id)
            return sonuc
        if komut.startswith(("slayt_yukari:", "slayt_asagi:", "slayt_basa:")):
            eylem, sira = komut.split(":", 1)
            sonuc = slayt_tasi(con, ayarlar, haberler, eylem, int(sira), mesaj_id)
            menuyu_geri_koy(con, mesaj_id)
            return sonuc
        # Görsel onay düğmeleri
        # Haber değiştirme: önce alternatif sun, sonra uygula
        if komut.startswith("haber_degistir:"):
            return haber_degistir(con, ayarlar, haberler,
                                  int(komut.split(":")[1]), mesaj_id)

        if komut.startswith("gorsel_kabul:"):
            return gorseli_kabul_et(
                con, ayarlar, haberler, int(komut.split(":")[1]), mesaj_id)
        if komut.startswith("gorsel_yeni:"):
            # "Başka dene" = aynı slaytın fotoğrafını bir sonraki adayla
            # yeniden üret. `slayt_islemi` sayacı kendisi artırıyor.
            return slayt_islemi(con, ayarlar, haberler, "slayt_foto",
                                int(komut.split(":")[1]), mesaj_id)
        # Menü Gezinme Düğmeleri (Worker yapamazsa veya doğrudan gelirse)
        if komut.startswith("slayt_menu:"):
            adet = int(komut.split(":")[1])
            telegram_bot.menuyu_degistir(mesaj_id, telegram_bot.slayt_secim_menusu(adet))
            return 0
        if komut.startswith("slayt:") and komut.count(":") >= 2:
            parcalar = komut.split(":")
            sira, adet = int(parcalar[1]), int(parcalar[2])
            telegram_bot.menuyu_degistir(mesaj_id, telegram_bot.slayt_islem_menusu(sira, adet))
            return 0
        if komut.startswith("yayin_menu:"):
            adet = int(komut.split(":")[1])
            telegram_bot.menuyu_degistir(mesaj_id, telegram_bot.yayin_zamani_menusu(adet))
            return 0
        if komut.startswith(("geri:", "yayin_geri:")):
            adet = int(komut.split(":")[1])
            telegram_bot.menuyu_degistir(mesaj_id, telegram_bot.ana_menu(adet))
            return 0

        if ":" in komut:
            ad, sira = komut.split(":", 1)
            sonuc = slayt_islemi(con, ayarlar, haberler, ad, int(sira), mesaj_id)
            # Slayt işlemleri turu bitirmiyor; Worker butonları kaldırdığı
            # için menüyü geri koymazsak onay verilemez hale gelir.
            menuyu_geri_koy(con, mesaj_id)
            return sonuc

    except Exception as e:
        log.exception("komut işlenemedi")
        telegram_bot.hata_bildir(
            f"Komut işlenemedi: {komut}",
            f"{type(e).__name__}: {e}",
            nerede=f"Onay İşlemi ({komut})",
            mesaj_id=mesaj_id,
        )
        # Worker butonları kaldırmıştı; hata sonrası geri koymazsak tur
        # kilitlenir ve elle müdahale gerekir.
        menuyu_geri_koy(con, mesaj_id)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
