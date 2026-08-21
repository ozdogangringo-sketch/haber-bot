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
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import yaml                                       # noqa: E402

from src import (                                  # noqa: E402
    aday, ayar, caption, db, db_senkron, dogrula, facebook, instagram,
    secim,
    slaytlar, telegram_bot, threads, upload_image,
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
                     "haber_sec", "haber_vazgec",
                     # Tur id'sini KOMUTTA taşıyorlar (ayrı mesajın düğmesi)
                     "yayin_kontrol", "yeniden_yayinla"}


def turu_getir(con, mesaj_id: int) -> list:
    """
    Bu onay mesajına bağlı haberleri slayt sırasıyla getirir.

    ⚠️ SIRALAMA `secim.tur_icin_sec` İLE AYNI OLMALI, yoksa slaytların
    sırası ile caption'daki manşet sırası birbirini tutmaz.
    `daha_once_yayinlandi` en başta: gün içinde tekil olarak yayınlanmış
    haber turda kalıyor ama EN SONA iniyor.
    """
    return list(con.execute(
        "SELECT * FROM haberler WHERE telegram_message_id = ? "
        "ORDER BY COALESCE(daha_once_yayinlandi, 0) ASC, "
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


def yayinla(con, ayarlar, haberler, mesaj_id, basan) -> int:
    if any(h["durum"] == "yayinlandi" for h in haberler):
        telegram_bot.mesaj_gonder("⚠️ Bu tur zaten yayınlanmış, tekrar gönderilmedi.")
        return 0

    urller = [h["gorsel_url"] for h in haberler if h["gorsel_url"]]

    # Son dakika turu TEK haberden birden çok slayt üretiyor: 1 haber +
    # 1-4 ayrıntı sayfası (metin uzunsa sayfa ekleniyor). Bunlar ayrı
    # kolonda JSON listesi olarak duruyor; buraya eklenmezse elde tek
    # görsel kalıyor ve Instagram carousel'i reddediyor.
    #
    # ⚠️ SADECE SON DAKİKA TURUNDA. Onaylanmayan son dakika haberi havuza
    # dönerken `detay_url` üstünde kalıyor; aynı haber akşam turunda
    # yeniden seçilince o eski ayrıntı sayfaları carousel'e sızıyordu.
    # 17 Ağu 2026'da oldu: 10 haberlik tur 13 görselle yayınlanmaya
    # çalıştı ve Instagram reddetti (sınır 10).
    for h in haberler:
        if h["son_dakika"]:
            urller.extend(_detay_urlleri(h["detay_url"]))

    if len(urller) < 2:
        raise RuntimeError(
            f"yayın için en az 2 görsel gerekli, {len(urller)} var. "
            f"Tur bozuk görünüyor — /tur ile yenisini kurabilirsin."
        )

    # ⚠️ SON DAKİKA AYRI CAPTION KULLANIYOR.
    #
    # `son_dakika.py` turu hazırlarken `son_dakika_caption()` kuruyor ve
    # Telegram'da ONU gösteriyor; burada `caption_kur()` çağrılınca
    # yayınlanan metin onaylanandan FARKLI oluyordu. 18 Ağu 2026'da
    # yayınlanan son dakika postunun açıklaması "Günün gündemi" diye
    # başlayıp tek haberi numaralı liste gibi veriyordu.
    #
    # Onaylanan metinle yayınlanan metnin ayrışması, içerik hatasından
    # daha sinsi: gözden geçirdiğin şey yayına çıkan şey değil.
    if haberler[0]["son_dakika"]:
        metin = caption.son_dakika_caption(
            haberler[0], _sonuclari_kur(haberler), ayarlar)
    else:
        metin = caption.caption_kur(
            haberler, _sonuclari_kur(haberler), ayarlar=ayarlar)
    post_id = instagram.carousel_yayinla(urller, metin, ayarlar)
    baglanti = instagram.post_baglantisi(post_id, ayarlar)

    # Story postla birlikte gidiyor. Ayrı bir onay istemiyoruz: içeriği
    # zaten onayladığın haberlerin listesi, yeni bir karar noktası değil.
    # Story patlarsa post yine yayında kalmalı — o yüzden hata yutuluyor.
    story_notu = ""
    story_url = next((h["story_url"] for h in haberler if h["story_url"]), None)
    if story_url:
        try:
            instagram.story_yayinla(story_url, ayarlar)
            story_notu = "\n📱 Story de paylaşıldı"
        except Exception as e:
            log.warning("story yayınlanamadı: %s", e)
            story_notu = f"\n⚠️ Story paylaşılamadı: {type(e).__name__}"

    # Facebook: aynı içerik, aynı jeton, ayrı kanal.
    # Instagram postu yayında kaldığı sürece buradaki hata turu
    # düşürmemeli — o yüzden yutuluyor, sonuca not düşülüyor.
    fb_notu = ""
    fb_id = None
    if (ayarlar.get("sosyal", {}) or {}).get("facebooka_da_at"):
        try:
            fb_id = facebook.albüm_yayinla(urller, metin, ayarlar)
            fb_notu = "\n📘 Facebook'a da paylaşıldı"
            log.info("Facebook: %s", fb_id)
            # Aynı story görseli Facebook'a da gidiyor; ayrı üretim yok,
            # ikisi de 9:16.
            if story_url:
                try:
                    facebook.story_yayinla(story_url, ayarlar)
                    fb_notu += " (story dahil)"
                except Exception as e:
                    log.warning("Facebook story olmadı: %s", e)
        except Exception as e:
            log.warning("Facebook paylaşılamadı: %s", e)
            fb_notu = f"\n⚠️ Facebook'a gitmedi: {type(e).__name__}"

    # Threads: ayrı jeton istiyor. Anahtar yoksa sessizce atlanıyor —
    # jeton alınmadan önce de kod güvenle çalışsın diye.
    th_notu = ""
    th_gonderi_id = None
    # ⚠️ KOŞULUN DIŞINDA TANIMLI OLMALI. Aşağıdaki `if` bloğu Threads
    # kapalıyken (`threadse_de_at: false`) veya jeton geçersizken hiç
    # çalışmıyor; bayrak orada tanımlanırsa yayın sonucunu yazan satır
    # NameError veriyor ve BAŞARILI bir yayın kırmızı job'a dönüyor.
    th_yarim = False
    if ((ayarlar.get("sosyal", {}) or {}).get("threadse_de_at")
            and threads.kullanilabilir_mi()):
        try:
            # ZİNCİR olarak gidiyor, carousel olarak değil: Threads metin
            # platformu, sınırı 500 karakter ve uzun anlatım zincirle
            # yapılıyor. Tam caption'ı tek gönderiye sıkıştırmak onu bir
            # haberin ortasında kesiyordu.
            # ⚠️ SON DAKİKADA TARİH YAZILMIYOR (`tarihli=False`).
            # Bu düzeltme önce yalnızca gece otomatik yayınına
            # uygulanmıştı; onaydan geçen son dakika postları buradan
            # çıktığı için tarih yazmaya devam etti ve canlı zincirde
            # "18 AĞUSTOS 2026 · Son dakika" göründü (18 Ağu 2026).
            # Akşam turunda tarih KALIYOR: orada vaat günlük derleme.
            son_dakika_mi = bool(haberler[0]["son_dakika"])
            halkalar = caption.threads_halkalari(
                haberler, urller, son_dakika=son_dakika_mi,
                ayarlar=ayarlar, tarihli=not son_dakika_mi,
            )
            th_id, th_adet = threads.zincir_yayinla(halkalar)
            th_gonderi_id = th_id

            # ⚠️ YARIM KALDIYSA HEMEN BİR KEZ TAMAMLAMAYI DENE.
            #
            # 21 Ağu 2026: zincir 2. halkada "Media Not Found" ile
            # kesildi ve kullanıcı eksik halkaları ELLE yazmak zorunda
            # kaldı. `/tamamla` komutu vardı ama mesajda ne komut ne
            # düğme geçiyordu — kullanıcı varlığını bilmiyordu.
            #
            # Kesilme sebebi geçici olduğu için (container yarışı)
            # saniyeler sonra ikinci deneme büyük olasılıkla tutuyor.
            # Maliyeti düşük: yalnızca eksik halkalar gönderiliyor.
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
                # Yarım zinciri "paylaşıldı" diye yazmak hatayı gizler.
                # Düğme de veriliyor (aşağıda): kullanıcı komutu
                # ezberlemek zorunda kalmasın.
                th_yarim = True
                th_notu = (f"\n⚠️ Threads zinciri yarım kaldı: "
                           f"{th_adet}/{len(halkalar)} halka\n"
                           f"Aşağıdaki düğmeyle tamamlayabilirsin.")
            log.info("Threads: %s (%s/%s halka)", th_id, th_adet, len(halkalar))
        except Exception as e:
            log.warning("Threads paylaşılamadı: %s", e)
            th_notu = f"\n⚠️ Threads'e gitmedi: {type(e).__name__}"

    # ⚠️ ID'LER SAKLANMALI. Yayından kaldırmak gerektiğinde Facebook ve
    # Threads bunlarla siliniyor; saklanmazsa elle girip aramak gerekiyor.
    # (Instagram'da silme API'den mümkün değil, orada yalnızca bağlantı
    #  gösteriliyor.)
    con.execute(
        "UPDATE haberler SET durum = 'yayinlandi', ig_post_id = ?, "
        "facebook_post_id = ?, threads_post_id = ? "
        "WHERE telegram_message_id = ?",
        (post_id, fb_id, th_gonderi_id, mesaj_id),
    )
    con.commit()

    # `bildir=True`: sonuç ayrıca yeni mesaj olarak da gidiyor. Yalnızca
    # onay mesajını düzenlemek yetmiyordu — düzenleme bildirim üretmiyor
    # ve kullanıcı 2 dakika süren yayının sonucunu göremiyordu.
    telegram_bot.sonucu_yaz(
        mesaj_id,
        f"✅ YAYINLANDI — {len(urller)} slayt{story_notu}{fb_notu}{th_notu}\n"
        f"\n{_yayin_ozeti(haberler)}\n"
        f"\nOnaylayan: {basan or 'bilinmiyor'}\n"
        f"{baglanti or post_id}",
        bildir=True,
        # Zincir yarım kaldıysa tek tuşla tamamlanabilsin. Komutu
        # ("/tamamla") bilmek zorunda bırakmak, kullanıcının eksik
        # halkaları ELLE yazmasına yol açtı (21 Ağu 2026).
        # Her yayın sonucunda "durumu kontrol et": veritabanı ile
        # Instagram ayrışabiliyor (20 Ağu 2026'da bir `ertele` komutu
        # yayınlanmış turun kaydını bozdu) ve kuyrukta iptal edilen bir
        # komut kullanıcıyı yayınlandı mı bilemez halde bırakıyordu.
        ek_dugmeler=(
            ([[{"text": "🔗 Threads zincirini tamamla",
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


def yayin_durumu_kontrol(con, ayarlar, mesaj_id: int) -> int:
    """
    Bu turun GERÇEKTEN yayınlanıp yayınlanmadığını Instagram'a sorar.

    ⚠️ VERİTABANI GERÇEĞİN TEK KAYNAĞI DEĞİL. 20 Ağu 2026'da bir tur
    yayınlandı, bir dakika sonra gelen `ertele` komutu kaydı bozdu ve
    sistem postu "yayınlanmamış" sandı; aynı haber iki kez daha onaya
    sunuldu. 21 Ağu'da da bir yayın komutu kuyrukta sessizce iptal
    edildi ve kullanıcı yayınlandı mı bilemedi.

    Bu düğme iki kaynağı da gösteriyor: veritabanı ne diyor, Instagram
    ne diyor. Uyuşmuyorlarsa Instagram doğrudur.
    """
    haberler = turu_getir(con, mesaj_id)
    if not haberler:
        telegram_bot.mesaj_gonder(
            "⚠️ Bu mesaja bağlı tur bulunamadı — kapanmış olabilir.")
        return 0

    db_durum = haberler[0]["durum"]
    post_id = next((h["ig_post_id"] for h in haberler if h["ig_post_id"]), None)
    basliklar = [(h["ig_baslik"] or h["baslik_orj"] or "") for h in haberler]

    satirlar = [f"🔍 <b>YAYIN DURUMU</b> ({len(haberler)} haber)", ""]
    satirlar.append(f"Veritabanı : <code>{html.escape(db_durum)}</code>")

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
            satirlar.append(f"Instagram  : ✅ <b>{len(bulunan)}/{len(basliklar)} "
                            "haber yayında görünüyor</b>")
            for b in bulunan[:3]:
                satirlar.append(f"   • {html.escape(b[:56])}")
        else:
            satirlar.append("Instagram  : ❌ <b>bu haberler yayında YOK</b>")
    except Exception as e:                            # noqa: BLE001
        satirlar.append(f"Instagram  : ⚠️ sorulamadı ({type(e).__name__})")
        bulunan = []

    if post_id:
        satirlar += ["", instagram.post_baglantisi(post_id, ayarlar) or post_id]

    if not bulunan and db_durum != "yayinlandi":
        satirlar += ["", "Yayınlanmamış görünüyor — aşağıdaki düğmeyle "
                         "tekrar deneyebilirsin."]
        tuslar = [[{"text": "🔄 Tekrar yayınla",
                    "callback_data": f"yeniden_yayinla:{mesaj_id}"}]]
    else:
        tuslar = None

    telegram_bot.mesaj_gonder("\n".join(satirlar), html=True, butonlar=tuslar)
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


def yayin_planla(con, ayarlar, haberler, dakika: int, mesaj_id, basan) -> int:
    """
    Turu ileri bir saate planlar. Yayın o ana kadar YAPILMIYOR.

    ⚠️ HASSASİYET ±90 DAKİKA — düğmedeki süre EN ERKEN yayın anıdır.
    Zamanı gelen turu son dakika kontrolü yayınlıyor ve o cron 20 Ağu
    2026'da Actions kotası için 30 dakikadan 90 dakikaya çekildi.
    Üstüne GitHub zamanlanmış çalıştırmaların bir kısmını atlıyor
    (ölçüldü: 30 dakikalık cron gerçekte ortalama 56 dakika aralıkla
    çalışıyordu, 9-98 arası).

    Bu yüzden mesajda kullanıcıya TEK BİR SAAT değil, 90 dakikalık bir
    PENCERE söyleniyor — cron'un vaat ettiğini değil, ölçüleni.

    ⚠️ PLANLANMIŞ TUR İKİ ZAMAN AŞIMINDAN KORUNMALI, yoksa yayın anı
    gelmeden tur havuza döner:
      * `son_dakika.suresi_gecmisi_iptal_et` — 60 dakikada iptal eder,
        yani "1 saat sonra" planı bile kendi kendini öldürürdü.
      * `hatirlat.py` — 6 saat onaysız turu kapatır ve bu arada
        gereksiz hatırlatma mesajları atardı.
    İkisi de `planlanan_yayin IS NULL` şartıyla bu turu atlıyor.
    """
    an = datetime.now(timezone.utc) + timedelta(minutes=dakika)
    con.execute(
        "UPDATE haberler SET planlanan_yayin = ? WHERE telegram_message_id = ?",
        (an.isoformat(), mesaj_id),
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
        return 0

    if komut == "slayt_metin":
        con.execute("UPDATE haberler SET durum = 'yeni' WHERE id = ?", (haber["id"],))
        con.commit()
        metinleri_uret(ayarlar=ayarlar, haberler=[haber])
        con.execute("UPDATE haberler SET durum = 'onay_bekliyor' WHERE id = ?",
                    (haber["id"],))
        con.commit()

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
    yol, katman, atif = slaytlar.slayt_uret(
        taze, ayarlar, zorla_ai=zorla_ai, atlanacak=deneme)

    yukleme = upload_image.gorsel_yukle(yol, ayarlar)

    # ⚠️ ADAY ALANLARA YAZILIYOR, ASIL ALANLARA DEĞİL.
    # Önce `gorsel_url` doğrudan güncelleniyordu: kullanıcı yeni görseli
    # beğenmese bile geri dönüş yoktu ve eski dosya da üzerine
    # yazıldığı için diskte kalmıyordu. Artık onay bekliyor.
    con.execute(
        "UPDATE haberler SET gorsel_url_aday = ?, gorsel_kaynagi_aday = ?, "
        "gorsel_atif_aday = ?, gorsel_yolu_aday = ?, gorsel_deneme = ? "
        "WHERE id = ?",
        (yukleme["url"], katman, atif, str(yol), deneme, haber["id"]),
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
        butonlar=[[
            {"text": "✅ Bunu kullan", "callback_data": f"gorsel_kabul:{sira}"},
            {"text": "🔄 Başka dene", "callback_data": f"gorsel_yeni:{sira}"},
        ]],
    )
    return 0


def _albumu_yenile(con, mesaj_id: int) -> None:
    """
    Üstteki slayt albümünü siler ve güncel hâlini yeniden gönderir.

    ⚠️ TELEGRAM ALBÜMÜNDE TEK FOTOĞRAF DEĞİŞTİRİLEMİYOR. Media group
    atomik bir birim; `editMessageMedia` albüm öğelerinde çalışmıyor.
    Albümü güncel göstermenin tek yolu eskisini silip yeniden göndermek.

    ⚠️ İKİ YERDEN çağrılıyor (görsel değiştirme ve haber değiştirme).
    Kopyalamak yerine tek fonksiyon: bu projedeki kusurların çoğu aynı
    işi yapan iki kod yolundan birinin unutulmasıydı.
    """
    yeniler = turu_getir(con, mesaj_id)
    urller = [h["gorsel_url"] for h in yeniler if h["gorsel_url"]]
    eski_albom = db.ayar_oku(con, f"albom_{mesaj_id}", "")
    if eski_albom:
        try:
            telegram_bot.mesajlari_sil(json.loads(eski_albom))
        except Exception as e:                        # noqa: BLE001
            log.warning("eski albüm silinemedi: %s", e)
    try:
        yeni_idler = telegram_bot.slaytlari_gonder(urller, ["Haber", "Ayrıntı"])
        db.ayar_yaz(con, f"albom_{mesaj_id}", json.dumps(yeni_idler or []))
    except Exception as e:                            # noqa: BLE001
        log.warning("albüm yenilenemedi: %s", e)


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
    try:
        yol, katman, atif = slaytlar.slayt_uret(dict(yeni), ayarlar)
        url = upload_image.gorsel_yukle(yol, ayarlar)["url"]
    except Exception as e:                            # noqa: BLE001
        log.exception("alternatif slaytı üretilemedi")
        telegram_bot.mesaj_gonder(
            f"⚠️ Yeni haberin slaytı üretilemedi: {type(e).__name__}: {e}\n"
            "Tur değişmedi.")
        menuyu_geri_koy(con, mesaj_id)
        return 1

    # Eski haber havuza, yeni haber tura. `tur` alanı korunuyor ki
    # sıralama bozulmasın.
    con.execute(
        "UPDATE haberler SET durum = 'metin_hazir', telegram_message_id = NULL, "
        "tur = NULL WHERE id = ?", (eski["id"],))
    con.execute(
        "UPDATE haberler SET durum = 'onay_bekliyor', telegram_message_id = ?, "
        "tur = ?, gorsel_yolu = ?, gorsel_url = ?, gorsel_kaynagi = ?, "
        "gorsel_atif = ?, gonderim_zamani = ? WHERE id = ?",
        (mesaj_id, eski["tur"], str(yol), url, katman, atif,
         eski["gonderim_zamani"], yeni_id))
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

    ⚠️ TELEGRAM ALBÜMÜNDE TEK FOTOĞRAF DEĞİŞTİRİLEMİYOR. Media group
    atomik bir birim; `editMessageMedia` albüm öğelerinde çalışmıyor.
    Üstteki albümü güncel göstermenin tek yolu eskisini silip yeniden
    göndermek — kullanıcı "önceki gönderi mesajımızda o resim
    güncellenmeli ki yayınla dediğimde güncel hali yayınlansın" dedi.
    """
    if sira < 1 or sira > len(haberler):
        telegram_bot.mesaj_gonder(f"⚠️ {sira}. slayt bulunamadı.")
        return 1
    haber = haberler[sira - 1]
    if not haber["gorsel_url_aday"]:
        telegram_bot.mesaj_gonder(
            "⚠️ Onay bekleyen bir görsel yok — muhtemelen zaten uygulandı.")
        return 0

    con.execute(
        "UPDATE haberler SET gorsel_url = gorsel_url_aday, "
        "gorsel_kaynagi = gorsel_kaynagi_aday, gorsel_atif = gorsel_atif_aday, "
        "gorsel_yolu = gorsel_yolu_aday, "
        "gorsel_url_aday = NULL, gorsel_yolu_aday = NULL, "
        "gorsel_kaynagi_aday = NULL, gorsel_atif_aday = NULL "
        "WHERE id = ?", (haber["id"],))
    con.commit()
    db_senkron.hemen_kaydet("Slayt görseli değiştirildi")

    _albumu_yenile(con, mesaj_id)
    telegram_bot.mesaj_gonder(f"✅ {sira}. slaytın görseli güncellendi.")
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
        ozet = telegram_bot.tur_ozeti(haberler, isaretli)
        metin = caption.caption_kur(
            haberler, _sonuclari_kur(haberler), ayarlar=_ayarlar_onbellek
        )
        parcalar = [p for p in (uyari, ozet) if p]
        parcalar.append("— Instagram açıklaması —\n" + metin)
        telegram_bot.mesaji_guncelle(
            mesaj_id, "\n\n".join(parcalar),
            telegram_bot.ana_menu(len(haberler)),
        )
    except Exception as e:
        log.warning("menü geri konamadı: %s", e)


def durum_bildir(con, ayarlar) -> int:
    """
    /durum komutunun cevabı: bot şu an ne durumda?

    Telegram'dan sorulabilmesi önemli — aksi halde "acaba tur hazırlandı
    mı, onay bekleyen var mı" sorusunun cevabı yalnızca GitHub Actions
    kayıtlarında oluyor ve telefondan bakmak zor.
    """
    sayim = dict(con.execute(
        "SELECT durum, COUNT(*) FROM haberler GROUP BY durum"
    ).fetchall())

    bekleyen = list(con.execute(
        "SELECT * FROM haberler WHERE durum IN ('onay_bekliyor','ertelendi') "
        "ORDER BY onem_puani DESC"
    ))

    son = con.execute(
        "SELECT ig_post_id, MAX(gonderim_zamani) z, COUNT(*) n FROM haberler "
        "WHERE durum = 'yayinlandi' AND ig_post_id IS NOT NULL"
    ).fetchone()

    satirlar = [
        "📊 BOT DURUMU",
        "",
        f"Havuzda bekleyen haber : {sayim.get('yeni', 0)}",
        f"Metni hazır            : {sayim.get('metin_hazir', 0)}",
        f"Yayınlanmış            : {sayim.get('yayinlandi', 0)}",
    ]

    if bekleyen:
        satirlar += [
            "",
            f"⏳ ONAY BEKLEYEN TUR VAR — {len(bekleyen)} slayt",
            "Onay mesajı yukarıda; görmüyorsan /tur ile yenisini kurabilirsin.",
        ]
    else:
        satirlar += ["", "✅ Onay bekleyen tur yok."]

    if son and son["z"]:
        satirlar += ["", f"Son yayın: {son['z']} (UTC)"]

    telegram_bot.mesaj_gonder("\n".join(satirlar))
    return 0



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

    # ⚠️ Hiçbir kelimesi BAŞLIKTA geçmeyenler (skor < 10) eleniyor.
    # Ölçüldü: "/haber asgari ücret" bu eşik olmadan üç alakasız haber
    # döndürüyordu — kelimeler özet metninde ayrı bağlamlarda geçiyordu.
    # Alakasız sonuç göstermek, "bulunamadı" demekten kötü: kullanıcı
    # yanlış haberi seçip yayınlayabilir.
    guclu = [h for h in ham if _arama_skoru(h, kelimeler) >= 10]

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
            f"çekilmemiş olabilir — kontrol yarım saatte bir çalışıyor.")
        return 0

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
                "kategori": h["kategori"] or "-"}
               for h in bulunan]
    adaylar.sort(key=lambda a: a["puan"], reverse=True)

    telegram_bot.mesaj_gonder(
        f"🔎 '{konu}' için {len(adaylar)} haber bulundu:")
    telegram_bot.oneri_gonder(adaylar)
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
    if komut.startswith("yayin_kontrol:"):
        return yayin_durumu_kontrol(con, ayarlar, int(komut.split(":")[1]))
    if komut.startswith("yeniden_yayinla:"):
        return yeniden_yayinla(con, ayarlar, int(komut.split(":")[1]), basan)
    if komut.startswith("haber_vazgec:"):
        menuyu_geri_koy(con, int(komut.split(":")[1]))
        telegram_bot.mesaj_gonder("Haber değiştirilmedi.")
        return 0

    if komut == "ayar":
        return ayar_paneli(con, ayarlar)
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
        telegram_bot.mesaj_gonder(
            "ℹ️ Bu mesaj artık geçerli değil.\n"
            "Tur kapanmış, atlanmış ya da yayınlanmış olabilir." + ek)
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
            return yayinla(con, ayarlar, haberler, mesaj_id, basan)
        if komut == "tura_birak":
            return tura_birak(con, haberler, mesaj_id, basan)
        if komut == "iptal":
            return iptal(con, haberler, mesaj_id, basan)
        if komut == "kaldir":
            return yayindan_kaldir(con, ayarlar, haberler, mesaj_id, basan)
        if komut == "ertele":
            return ertele(con, mesaj_id, basan)
        if komut == "plan_iptal":
            return plani_iptal_et(con, mesaj_id, basan)
        if komut.startswith("yayinla_sonra:"):
            return yayin_planla(con, ayarlar, haberler,
                                int(komut.split(":")[1]), mesaj_id, basan)
        if komut == "metin_yenile":
            return metin_yenile(con, ayarlar, haberler, mesaj_id)
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
        if ":" in komut:
            ad, sira = komut.split(":", 1)
            sonuc = slayt_islemi(con, ayarlar, haberler, ad, int(sira), mesaj_id)
            # Slayt işlemleri turu bitirmiyor; Worker butonları kaldırdığı
            # için menüyü geri koymazsak onay verilemez hale gelir.
            menuyu_geri_koy(con, mesaj_id)
            return sonuc

        log.error("bilinmeyen komut: %s", komut)
        return 1

    except Exception as e:
        log.exception("komut işlenemedi")
        telegram_bot.hata_bildir(f"Komut işlenemedi: {komut}",
                                 f"{type(e).__name__}: {e}")
        # Worker butonları kaldırmıştı; hata sonrası geri koymazsak tur
        # kilitlenir ve elle müdahale gerekir.
        menuyu_geri_koy(con, mesaj_id)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
