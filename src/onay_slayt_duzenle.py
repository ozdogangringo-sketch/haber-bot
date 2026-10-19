"""
onay_slayt_duzenle.py — Telegram'dan slayt sıralama, metin düzenleme, havuzdan haber ekleme ve değiştirme işlemleri.

`scripts/onay_isle.py` monolitini sadeleştirmek için slayt/haber düzenleme
ve albüm yenileme fonksiyonları bu modüle ayrılmıştır.
"""

import html
import json
import logging
import re
from datetime import datetime, timedelta, timezone

from src import (
    aday,
    caption,
    db,
    db_senkron,
    dogrula,
    make_image,
    slaytlar,
    telegram_bot,
    tur_icerigi,
    upload_image,
)
from src.onay_yonetim import turu_getir

log = logging.getLogger("onay")

# Ayarlar main() içinde okunuyor ama menuyu_geri_koy() gibi yardımcılar da
# ihtiyaç duyuyor; parametre zincirini uzatmamak için burada tutuluyor.
_ayarlar_onbellek: dict = {}


def _detay_urlleri(ham) -> list[str]:
    """`detay_url` kolonunu listeye çevirir — kural `tur_icerigi.detay_urlleri`'de."""
    return tur_icerigi.detay_urlleri(ham)


def _sonuclari_kur(haberler: list) -> list[dict]:
    """Caption'ın atıf bloğu için katman bilgisi — kural `tur_icerigi.katman_bilgisi`'de."""
    return tur_icerigi.katman_bilgisi(haberler)


def menuyu_geri_koy(con, mesaj_id: int, en_alta_tasi: bool = False) -> int:
    """
    Onay mesajını günceller. en_alta_tasi=True ise eski onay mesajını silip
    sohbetin EN ALTINA yeni bir onay mesajı gönderir ve veritabanını günceller.
    Böylece yeni görsel/albüm geldiğinde butonlar yukarıda kalmaz.
    """
    haberler = turu_getir(con, mesaj_id)
    if not haberler:
        return mesaj_id
    try:
        uyari, isaretli = dogrula.turu_dogrula(haberler)
        ilk_h = dict(haberler[0]) if haberler else {}
        if len(haberler) == 1 and ilk_h.get("tur") != "ekonomi":
            adet = 1 + len(_detay_urlleri(ilk_h.get("detay_url")))
            baslik_goster = html.escape(ilk_h.get("ig_baslik") or ilk_h.get("baslik_orj") or "")
            onem = ilk_h.get('onem_puani', 8)
            tur_etiket = "🔴 <b>SON DAKİKA ÖNERİSİ</b>" if (ilk_h.get("son_dakika") or onem >= 9) else "📰 <b>HABER ÖNERİSİ</b>"
            ozet = (f"{tur_etiket}  ·  puan {onem}/10\n"
                    f"📰 <b>{baslik_goster}</b>\n"
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
        govde = "\n\n".join(parcalar)

        if en_alta_tasi:
            try:
                telegram_bot.mesaj_sil(mesaj_id)
            except Exception as e:
                log.debug("Eski onay mesajı silinemedi: %s", e)

            yeni_mid = telegram_bot.mesaj_gonder(
                govde,
                html=True,
                butonlar=telegram_bot.ana_menu(adet)["inline_keyboard"],
            )

            con.execute(
                "UPDATE haberler SET telegram_message_id = ? WHERE telegram_message_id = ?",
                (yeni_mid, mesaj_id),
            )
            con.commit()
            log.info("Onay mesajı en alta taşındı: #%s -> #%s", mesaj_id, yeni_mid)
            return yeni_mid
        else:
            telegram_bot.mesaji_guncelle(
                mesaj_id, govde,
                telegram_bot.ana_menu(adet),
            )
            return mesaj_id
    except Exception as e:
        log.warning("menü geri konamadı: %s", e)
        return mesaj_id


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
        if yeni_idler:
            db.ayar_yaz(con, f"albom_{mesaj_id}", json.dumps(yeni_idler))
        yeni_mid = menuyu_geri_koy(con, mesaj_id, en_alta_tasi=True)
        if yeni_idler and yeni_mid != mesaj_id:
            db.ayar_yaz(con, f"albom_{yeni_mid}", json.dumps(yeni_idler))
    except Exception as e:                            # noqa: BLE001
        log.warning("albüm yenilenemedi: %s", e)


def metin_duzenle(con, ayarlar: dict, haberler: list, mesaj_id: int, gelen_metin: str, basan: str) -> int:
    """
    Kullanıcının Telegram'dan Reply yaparak veya komutla girdiği yeni başlık/metni işler.
    """
    if not gelen_metin or not gelen_metin.strip():
        telegram_bot.mesaj_gonder("⚠️ Boş metin girilemez.")
        return 0

    metin = gelen_metin.strip()
    sira = None
    yeni_baslik = ""
    yeni_metin = None

    eslesme = re.match(r"^([1-9]|10)\s*[:\.\-]\s*(.+)$", metin, re.DOTALL)
    if eslesme:
        sira = int(eslesme.group(1))
        kalan = eslesme.group(2).strip()
    else:
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

    if haber["durum"] == "baslik_onayi":
        guncel_haberler = turu_getir(con, mesaj_id)
        telegram_bot.basliklari_tazele(mesaj_id, guncel_haberler)
        telegram_bot.mesaj_gonder(
            f"✅ <b>{sira}. slaytın başlığı güncellendi:</b>\n<i>{html.escape(yeni_baslik)}</i>",
            html=True,
        )
        db_senkron.hemen_kaydet(f"Başlık düzenlendi (başlık onayı): slayt {sira}")
        return 0

    taze = con.execute("SELECT * FROM haberler WHERE id = ?", (haber["id"],)).fetchone()
    son_dakika_tekil = len(haberler) == 1 and (bool(haber.get("son_dakika")) or haber.get("tur") != "ekonomi")
    if son_dakika_tekil:
        sonuclar = slaytlar.son_dakika_uret(taze, ayarlar, con=con)
        yuklemeler = upload_image.hepsini_yukle([s["yol"] for s in sonuclar], ayarlar)
        urller = [y["url"] for y in yuklemeler]
        con.execute(
            "UPDATE haberler SET gorsel_url = ?, story_url = ?, detay_url = ?, "
            "gorsel_yolu = ?, gorsel_kaynagi = ?, gorsel_atif = ? WHERE id = ?",
            (urller[0], urller[0], json.dumps(urller[1:]),
             str(sonuclar[0]["yol"]), sonuclar[0].get("katman"), sonuclar[0].get("atif"), haber["id"]),
        )
        con.commit()
    else:
        yol, katman, atif = slaytlar.slayt_uret(taze, ayarlar, con=con)
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
    """Slaytların sırasını yukarı, aşağı taşır veya en başa (manşet) alır."""
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

    for idx, h in enumerate(sirali, 1):
        con.execute("UPDATE haberler SET slayt_sirasi = ? WHERE id = ?", (idx, h["id"]))
    con.commit()

    guncel = turu_getir(con, mesaj_id)

    if haberler[0]["durum"] == "baslik_onayi":
        telegram_bot.basliklari_tazele(mesaj_id, guncel)
        telegram_bot.mesaj_gonder(mesaj, html=True)
        db_senkron.hemen_kaydet(f"Slayt sırası değiştirildi: {eylem}:{sira}")
        return 0

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
    """Havuzdan en iyi taze haberi seçip mevcut tura yeni slayt olarak ekler."""
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

    yol, katman, atif = slaytlar.slayt_uret(aday_haber, ayarlar, con=con)
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
    """Turdaki bir haberin yerine geçebilecek 2 alternatifi sunar."""
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
    """Seçilen alternatifi tura koyar, eskisini havuza döndürür."""
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
            yol, katman, atif = slaytlar.slayt_uret(dict(yeni), ayarlar, con=con)
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
