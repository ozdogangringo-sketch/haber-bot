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

import json
import logging
import os
import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import yaml                                       # noqa: E402

from src import (                                  # noqa: E402
    ayar, caption, db, db_senkron, dogrula, facebook, instagram, slaytlar,
    telegram_bot, threads, upload_image,
)
from src.generate_text import metinleri_uret       # noqa: E402

log = logging.getLogger("onay")

# Ayarlar main() içinde okunuyor ama menuyu_geri_koy() gibi yardımcılar da
# ihtiyaç duyuyor; parametre zincirini uzatmamak için burada tutuluyor.
_ayarlar_onbellek: dict = {}

# Açık bir onay mesajına bağlı OLMAYAN komutlar. Bunlar `mesaj_id`
# taşımıyor; buraya eklenmezse main() daha en başta hata verip çıkıyor.
# (`/tur` buraya girmiyor — workflow onu `hazirla.py`'ye yönlendiriyor,
#  bu script'e hiç uğramıyor.)
MESAJSIZ_KOMUTLAR = {"durum", "ayar"}


def turu_getir(con, mesaj_id: int) -> list:
    """Bu onay mesajına bağlı haberleri slayt sırasıyla getirir."""
    return list(con.execute(
        "SELECT * FROM haberler WHERE telegram_message_id = ? "
        "ORDER BY onem_puani DESC, yayin_tarihi DESC",
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
            if th_adet == len(halkalar):
                th_notu = f"\n🧵 Threads'e de paylaşıldı ({th_adet} halka)"
            else:
                # Yarım zinciri "paylaşıldı" diye yazmak hatayı gizler.
                th_notu = (f"\n⚠️ Threads zinciri yarım kaldı: "
                           f"{th_adet}/{len(halkalar)} halka")
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
        f"Onaylayan: {basan or 'bilinmiyor'}\n"
        f"{baglanti or post_id}",
        bildir=True,
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
        "durum = CASE WHEN ig_baslik IS NOT NULL THEN 'metin_hazir' "
        "             ELSE 'yeni' END "
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
    if komut == "slayt_ai":
        ayarlar = {**ayarlar, "gorsel": {**ayarlar["gorsel"], "haberde_ai": True}}
    yol, katman, atif = slaytlar.slayt_uret(taze, ayarlar)

    yukleme = upload_image.gorsel_yukle(yol, ayarlar)
    # Atıf da güncelleniyor: katman değişince (Pexels → AI gibi) eski
    # atıf yanlış kalır ve caption'a yanlış lisans bilgisi girer.
    con.execute(
        "UPDATE haberler SET gorsel_url = ?, gorsel_kaynagi = ?, "
        "gorsel_atif = ?, gorsel_yolu = ? WHERE id = ?",
        (yukleme["url"], katman, atif, str(yol), haber["id"]),
    )
    con.commit()

    # Yeni görseli GÖSTERİYORUZ, link vermiyoruz: beğenip beğenmediğine
    # karar vermek için tarayıcı açmak gerekmemeli.
    simge = telegram_bot.KATMAN_SIMGE.get(katman, "▫️")
    telegram_bot.foto_gonder(
        yukleme["url"],
        f"{simge} {sira}. slayt yenilendi — {katman}\n"
        f"{taze['ig_baslik'] or ''}",
    )
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
    if komut not in MESAJSIZ_KOMUTLAR and not mesaj_id:
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
    if komut == "ayar":
        return ayar_paneli(con, ayarlar)
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
        log.error("mesaj_id=%s için haber bulunamadı", mesaj_id)
        telegram_bot.mesaj_gonder(
            "⚠️ Bu onay mesajına bağlı haber bulunamadı.\n"
            "Tur kapanmış ya da veritabanı bu turu görmüyor olabilir. "
            "/durum yazarak güncel duruma bakabilirsin."
        )
        return 1

    try:
        if komut == "yayinla":
            return yayinla(con, ayarlar, haberler, mesaj_id, basan)
        if komut == "iptal":
            return iptal(con, haberler, mesaj_id, basan)
        if komut == "kaldir":
            return yayindan_kaldir(con, ayarlar, haberler, mesaj_id, basan)
        if komut == "ertele":
            return ertele(con, mesaj_id, basan)
        if komut == "metin_yenile":
            return metin_yenile(con, ayarlar, haberler, mesaj_id)
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
