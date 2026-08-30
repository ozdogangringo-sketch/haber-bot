"""
ozel_haber.py — Telegram üzerinden havuz dışı özel haber üretimi.

3 Modu Destekler:
  1. /link <URL>     — Herhangi bir web sitesi veya haber linkinden tam post üretir.
  2. /arastir <KONU> — Verilen konuyu Gemini ile webde araştırıp doğrulanmış haber üretir.
  3. /ozel <METİN>   — Kullanıcının yazdığı duyuru/bülten metnini Daily Brief formatına dönüştürür.
"""

from __future__ import annotations

import html
import json
import logging
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from . import (
    caption, db, db_senkron, fetch_article,
    generate_text, make_image, slaytlar, telegram_bot, upload_image,
)

log = logging.getLogger("ozel_haber")


def _baslik_ve_metin_ayikla(url: str) -> tuple[str, str, str | None, str]:
    """URL'den başlık, tam gövde metni, og:image görseli ve kaynak adını çeker."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
    }
    r = requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()

    soup = BeautifulSoup(r.content, "html.parser")

    # 1. Başlık bul
    baslik = ""
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        baslik = og_title["content"].strip()
    elif soup.title and soup.title.string:
        baslik = soup.title.string.strip()

    # 2. Makale metni çek
    govde = fetch_article.makale_metni_cek(url) or ""
    if not govde:
        paragraflar = [p.get_text(" ", strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 40]
        govde = " ".join(paragraflar)[:3500]

    # 3. Görsel çek
    gorsel = fetch_article.og_gorseli_cek(url)

    # Kaynak adı alan adından tahmin edilir
    domain = urlparse(url).netloc.replace("www.", "").split(".")[0].capitalize()
    return baslik or "Özel Haber", govde, gorsel, domain


def _post_olustur_ve_onaya_sun(
    con,
    ayarlar: dict,
    haber_id: int,
    kaynak: str,
    ozet_not: str = "",
) -> int:
    """Oluşturulan haber kaydının slaytlarını üretir, yükler ve Telegram onayına sunar."""
    taze = con.execute("SELECT * FROM haberler WHERE id = ?", (haber_id,)).fetchone()
    if not taze:
        raise RuntimeError(f"Haber kaydı bulunamadı: {haber_id}")

    # 1. Slaytları ve Story'yi üret
    sonuclar = slaytlar.son_dakika_uret(taze, ayarlar, con=con)
    if not sonuclar:
        raise RuntimeError("Slayt görselleri üretilemedi.")

    # 2. Slaytları ImgBB'ye yükle
    urller = []
    katman_raporu = []
    story_url = None
    story_detay_url = None

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

        # Detay slaytı varsa 9:16 Story formatı üret
        if s.get("katman") == "detay":
            try:
                from src import video
                from PIL import Image
                detay_img = Image.open(s["yol"])
                detay_9_16 = video._cercevele_9_16(detay_img, baslik_rozet="HABERİN AYRINTILARI")
                detay_9_16_yol = make_image.CIKTI_KLASORU / f"story-{haber_id}-detay.jpg"
                detay_9_16.save(detay_9_16_yol, "JPEG", quality=92, optimize=True)
                story_detay_yukleme = upload_image.gorsel_yukle(detay_9_16_yol, ayarlar)
                story_detay_url = story_detay_yukleme["url"]
            except Exception as e:
                log.warning("detay story yüklenemedi: %s", e)
        else:
            simge = telegram_bot.KATMAN_SIMGE.get(s.get("katman", "gradyan"), "▫️")
            katman_raporu.append(f"{simge} Görsel: {s.get('katman', 'gradyan')}")

    if not urller:
        raise RuntimeError("Görseller ImgBB'ye yüklenemedi.")

    # 3. Caption hazırla
    metin = caption.son_dakika_caption(taze, sonuclar, ayarlar)

    # 4. Telegram'a albüm ve onay mesajı gönder (9:16 Story formatında, Haber + Ayrıntı)
    telegram_urller = [story_url] if story_url else [urller[0]]
    if story_detay_url:
        telegram_urller.append(story_detay_url)
    elif len(urller) > 1:
        telegram_urller.append(urller[1])

    etiketler = ["Haber", "Ayrıntı"][:len(telegram_urller)]
    telegram_bot.slaytlari_gonder(telegram_urller, etiketler)
    mesaj_id = telegram_bot.onay_iste(
        metin,
        len(telegram_urller),
        ozet=(
            f"{ozet_not or '✨ ÖZEL HABER'}\n"
            f"Kaynak: {kaynak}  ·  Puan: {taze['onem_puani'] or 9}/10\n"
            + ("\n".join(katman_raporu) if katman_raporu else "")
        ),
    )

    con.execute(
        "UPDATE haberler SET durum = 'onay_bekliyor', son_dakika = 1, "
        "telegram_message_id = ?, gorsel_url = ?, detay_url = ?, "
        "story_url = ?, gonderim_zamani = datetime('now') WHERE id = ?",
        (mesaj_id, urller[0], json.dumps(urller[1:]), story_url, haber_id),
    )
    con.commit()
    db_senkron.hemen_kaydet("Özel haber onaya sunuldu")
    log.info("Özel haber başarıyla onaya sunuldu (mid=%s, id=%s)", mesaj_id, haber_id)
    return 0


def linkten_haber_uret(url: str, con, ayarlar: dict, basan: str = "") -> int:
    """
    /link <URL> komutu: Verilen linkten tam haber ve slayt üretir.
    """
    url = url.strip()
    if not url.startswith("http"):
        telegram_bot.mesaj_gonder("⚠️ Geçerli bir link giriniz:\n<code>/link https://bloomberg.com/...</code>", html=True)
        return 1

    telegram_bot.mesaj_gonder(f"🌐 <b>Link taranıyor:</b>\n<code>{url}</code>\n\nMakale metni çekilip slaytlar üretiliyor…", html=True)

    try:
        baslik, govde, gorsel, kaynak = _baslik_ve_metin_ayikla(url)
        if len(govde) < 100:
            telegram_bot.mesaj_gonder("⚠️ Linkteki sayfa metni okunamadı veya erişim engellendi.")
            return 1

        # Veritabanında varsa getir veya yeni kayıt oluştur
        var_mi = con.execute("SELECT id FROM haberler WHERE link = ?", (url,)).fetchone()
        if var_mi:
            haber_id = var_mi["id"]
            con.execute(
                """UPDATE haberler SET
                    kaynak = ?, baslik_orj = ?, ozet_orj = ?, makale_metni = ?,
                    yayin_tarihi = datetime('now'), durum = 'yeni'
                WHERE id = ?""",
                (kaynak, baslik[:250], govde[:800], govde, haber_id),
            )
            con.commit()
        else:
            cursor = con.execute(
                """INSERT INTO haberler (
                    kaynak, kategori, agirlik, baslik_orj, link, ozet_orj, makale_metni,
                    yayin_tarihi, cekilme_zamani, durum
                ) VALUES (?, 'dunya', 10, ?, ?, ?, ?, datetime('now'), datetime('now'), 'yeni')""",
                (kaynak, baslik[:250], url, govde[:800], govde),
            )
            haber_id = cursor.lastrowid
            con.commit()

        if gorsel:
            con.execute("UPDATE haberler SET gorsel_kaynagi = 'haber_gorseli' WHERE id = ?", (haber_id,))
            con.commit()

        # Gemini ile metinleri üret
        kayit = con.execute("SELECT * FROM haberler WHERE id = ?", (haber_id,)).fetchone()
        generate_text.metinleri_uret(ayarlar=ayarlar, haberler=[kayit])

        return _post_olustur_ve_onaya_sun(
            con, ayarlar, haber_id, kaynak=kaynak, ozet_not=f"🔗 LİNKTEN ÜRETİLEN ÖZEL HABER"
        )

    except Exception as e:
        log.exception("Linkten haber üretilemedi: %s", e)
        telegram_bot.mesaj_gonder(f"⚠️ Linkten haber üretilirken bir hata oluştu:\n<code>{html.escape(str(e)[:300])}</code>", html=True)
        return 1


def arastir_haber_uret(konu: str, con, ayarlar: dict, basan: str = "") -> int:
    """
    /arastir <KONU> komutu: Gemini ile konuyu webde araştırıp doğrulanmış haber üretir.
    """
    konu = konu.strip()
    if len(konu) < 4:
        telegram_bot.mesaj_gonder("⚠️ Araştırmak istediğin konuyu daha detaylı yaz:\n<code>/arastir Nvidia yeni kuantum yapay zeka çipini duyurdu</code>", html=True)
        return 1

    telegram_bot.mesaj_gonder(f"🔍 <b>Konu araştırılıyor:</b>\n<i>\"{konu}\"</i>\n\nGüncel bilgiler toplanıyor ve slaytlar hazırlanıyor…", html=True)

    try:
        prompt = (
            f"Aşağıdaki konuyu derinlemesine ve en güncel bilgilerle araştırıp profesyonel bir haber haline getir:\n"
            f"KONU: {konu}\n\n"
            f"KURALLAR:\n"
            f"- Kesinlikle uydurma bilgi verme, güncel ve somut gerçekleri aktar.\n"
            f"- Varsa ilgili şirketleri, ülkeleri, kişileri, tarihleri ve sayısal rakamları belirt.\n"
            f"- Türkçe manşet (ig_baslik), 2-3 cümlelik Instagram caption (ig_caption), slayt özeti (slayt_ozet) ve detay metni (detay_metni) üret.\n"
            f"- Vurgu rakamı (vurgu_sayi) ve etiketi (vurgu_etiket) çıkar (örn: '500 Milyar $' / 'TOPLAM YATIRIM').\n"
            f"- Kategori (turkiye, dunya, ekonomi, teknoloji, bilim, spor) ve İngilizce Pexels stok arama kalıbı (gorsel_konu) belirle.\n"
        )

        yanit = generate_text.gemini_cagir(prompt, ayarlar)
        if not yanit or not isinstance(yanit, dict):
            raise RuntimeError("Gemini araştırma sonucunu üretemedi.")

        h_veri = yanit

        # Veritabanına başlangıç kaydı oluştur ve db.metin_kaydet ile tam kaydet
        cursor = con.execute(
            """INSERT INTO haberler (
                kaynak, kategori, agirlik, baslik_orj, link, ozet_orj,
                yayin_tarihi, cekilme_zamani, durum
            ) VALUES (
                'Web Araştırması', ?, 10, ?, ?, ?,
                datetime('now'), datetime('now'), 'yeni'
            )""",
            (
                h_veri.get("kategori", "teknoloji"),
                h_veri.get("ig_baslik", konu)[:250],
                f"https://dailybrief.co/arastirma/{int(time.time())}",
                h_veri.get("slayt_ozet", "")[:800],
            ),
        )
        haber_id = cursor.lastrowid
        db.metin_kaydet(con, haber_id, h_veri, makale_metni=konu)
        con.commit()

        return _post_olustur_ve_onaya_sun(
            con, ayarlar, haber_id, kaynak="Canlı Web Araştırması", ozet_not="🔎 CANLI ARAŞTIRMA İLE ÜRETİLEN ÖZEL HABER"
        )

    except Exception as e:
        log.exception("Araştırma haberi üretilemedi: %s", e)
        telegram_bot.mesaj_gonder(f"⚠️ Araştırma haberi üretilirken bir hata oluştu:\n<code>{html.escape(str(e)[:300])}</code>", html=True)
        return 1


def dosya_haber_uret(konu: str, con, ayarlar: dict, basan: str = "") -> int:
    """
    /dosya <KONU> veya /kronoloji <KONU> komutu:
    Verilen konunun başından sonuna kronolojisini, dava/resmi süreçlerini,
    gözden kaçan ara detaylarını ve en son durumunu derleyen
    A'dan Z'ye derinlemesine dosya haberi üretir.
    """
    konu = konu.strip()
    if len(konu) < 4:
        telegram_bot.mesaj_gonder(
            "⚠️ Dosya haberi yapmak istediğin konuyu detaylı yaz:\n"
            "<code>/dosya Haluk Levent ve Ahbap derneği davası son gelişmeler</code>\n"
            "<code>/kronoloji Dilan Polat davası ve ara kararlar</code>",
            html=True,
        )
        return 1

    telegram_bot.mesaj_gonder(
        f"📁 <b>A'dan Z'ye Dosya Haberi Hazırlanıyor:</b>\n"
        f"<i>\"{html.escape(konu)}\"</i>\n\n"
        f"Başından sonuna tüm kronoloji, dava/teftiş süreçleri ve perde arkası detaylar toplanıyor…",
        html=True,
    )

    try:
        prompt = (
            f"Aşağıdaki konuyu bir araştırmacı gazeteci titizliğiyle ele al. Olayın başından günümüze kadarki "
            f"tüm kronolojisini, gözden kaçan ara detaylarını, açılan davaları, teftiş/bilirkişi raporlarını ve "
            f"bugün gelinen en son durumu özetleyen A'dan Z'ye derinlemesine bir dosya haberi hazırla:\n\n"
            f"DOSYA KONUSU: {konu}\n\n"
            f"EDİTORYAL KURALLAR:\n"
            f"1. ASLA uydurma veya spekülatif bilgi verme. Doğrulanmış gerçekleri, resmi kurum raporlarını ve dava kararlarını aktar.\n"
            f"2. ig_baslik: Merak uyandıran, sonucu ve süreci net veren çarpıcı dosya manşeti (örn: 'Haluk Levent ve Ahbap Olayında Ne Oldu? Başından Sonuna Tüm Süreç').\n"
            f"3. slayt_ozet: TEK cümlelik (en fazla 20 kelime) dosya özeti.\n"
            f"4. detay_metni: Tam 3 FERAH PARAGRAF (Slaytta kalın vurgulanmasını istediğin 2-3 kilit veriyi **kalın** içine al):\n"
            f"   * 1. Paragraf (Olayın Çıkışı & İddialar): Olayın ne zaman, nasıl başladığı ve temel suçlama/iddia (30-40 kelime).\n"
            f"   * 2. Paragraf (Teftişler, Ara Kararlar & Perde Arkası): Medyada çok öne çıkmayan teftiş raporları, bilirkişi kararları, mali incelemeler ve ara süreçler (40-50 kelime).\n"
            f"   * 3. Paragraf (Bugün Gelinen Son Nokta): En güncel resmi karar, aklanma/ceza veya mevcut hukuki durum (30-40 kelime).\n"
            f"5. sana_etkisi: 1-2 cümlelik analiz (topluma, sivil topluma veya vatandaşa yansıması).\n"
            f"6. neden_onemli: 1-2 cümlelik kurumsal/hukuki önem boyutu.\n"
            f"7. sirada_ne_var: Varsa sonraki duruşma, rapor veya yürürlük tarihi (yoksa '').\n"
            f"8. vurgu_sayi / vurgu_etiket: Kilit bir rakam veya süre (örn: '850 Milyon ₺' / 'DENETLENEN YARDIM' veya '18 Ay' / 'SÜREN TEFTİŞ').\n"
            f"9. alinti / alinti_sahibi: Konunun ana aktörünün doğrulanmış net bir sözü ve sahibi.\n"
            f"10. ig_caption: 4-6 cümlelik, ferah paragraflı, etkileşim sorulu, tam kapsamlı mini dosya bülteni. Asla markdown yıldız (**) kullanma.\n"
            f"11. gorsel_konu: Konuyla doğrudan ilgili gerçek kişinin adı-soyadı (örn: 'Haluk Levent', 'Dilan Polat'). Varsa Wikimedia Commons'tan portresi çekilecek.\n"
            f"12. gorsel_temsili: Somut İngilizce stok arama terimi (örn: 'courtroom gavel justice trial', 'charity donation aid boxes').\n"
            f"13. kategori: 'turkiye', 'dunya', 'ekonomi', 'teknoloji', 'bilim', 'spor'.\n"
        )

        yanit = generate_text.gemini_cagir(prompt, ayarlar)
        if not yanit or not isinstance(yanit, dict):
            raise RuntimeError("Gemini dosya haberi analizini üretemedi.")

        h_veri = yanit

        cursor = con.execute(
            """INSERT INTO haberler (
                kaynak, kategori, agirlik, baslik_orj, link, ozet_orj,
                yayin_tarihi, cekilme_zamani, durum
            ) VALUES (
                'A\\'dan Z\\'ye Dosya', ?, 10, ?, ?, ?,
                datetime('now'), datetime('now'), 'yeni'
            )""",
            (
                h_veri.get("kategori", "turkiye"),
                h_veri.get("ig_baslik", konu)[:250],
                f"https://dailybrief.co/dosya/{int(time.time())}",
                h_veri.get("slayt_ozet", "")[:800],
            ),
        )
        haber_id = cursor.lastrowid
        db.metin_kaydet(con, haber_id, h_veri, makale_metni=konu)
        con.commit()

        return _post_olustur_ve_onaya_sun(
            con,
            ayarlar,
            haber_id,
            kaynak="A'dan Z'ye Dosya",
            ozet_not="📁 A'DAN Z'YE DOSYA HABERİ & KRONOLOJİ",
        )

    except Exception as e:
        log.exception("Dosya haberi üretilemedi: %s", e)
        telegram_bot.mesaj_gonder(
            f"⚠️ Dosya haberi hazırlanırken bir hata oluştu:\n<code>{html.escape(str(e)[:300])}</code>",
            html=True,
        )
        return 1


def ozel_metin_haber_uret(metin: str, con, ayarlar: dict, basan: str = "") -> int:
    """
    /ozel <METİN> komutu: Kullanıcının girdiği bülten/duyuru metninden Daily Brief postu üretir.
    """
    metin = metin.strip()
    if len(metin) < 15:
        telegram_bot.mesaj_gonder("⚠️ Post yapmak istediğin bülten veya duyuru metnini yaz:\n<code>/ozel Daily Brief mobil uygulamamız App Store ve Google Play'de yayına girdi...</code>", html=True)
        return 1

    telegram_bot.mesaj_gonder("✍️ <b>Özel bülten metni işleniyor…</b>\nDaily Brief şablonuna ve slaytlara dönüştürülüyor…", html=True)

    try:
        prompt = (
            f"Kullanıcı tarafından yazılan aşağıdaki bülten/duyuru/haber metnini profesyonel bir Daily Brief Instagram ve Threads postuna dönüştür:\n\n"
            f"KULLANICI METNİ:\n{metin}\n\n"
            f"KURALLAR:\n"
            f"- Türkçe çarpıcı ve net bir manşet (ig_baslik, en fazla 90 karakter).\n"
            f"- 2-3 cümlelik akıcı Instagram açıklaması (ig_caption).\n"
            f"- 1-2 cümlelik spot slayt özeti (slayt_ozet).\n"
            f"- Ayrıntılı 2. slayt detay metni (detay_metni).\n"
            f"- Varsa metinden vurucu bir rakam (vurgu_sayi) ve etiketi (vurgu_etiket).\n"
            f"- Kategori (turkiye, dunya, ekonomi, teknoloji, bilim, spor) ve İngilizce Pexels stok arama kalıbı (gorsel_konu) belirle.\n"
        )

        yanit = generate_text.gemini_cagir(prompt, ayarlar)
        if not yanit or not isinstance(yanit, dict):
            raise RuntimeError("Gemini bülten metnini işleyemedi.")

        h_veri = yanit

        cursor = con.execute(
            """INSERT INTO haberler (
                kaynak, kategori, agirlik, baslik_orj, link, ozet_orj,
                yayin_tarihi, cekilme_zamani, durum
            ) VALUES (
                'Özel Bülten', ?, 10, ?, ?, ?,
                datetime('now'), datetime('now'), 'yeni'
            )""",
            (
                h_veri.get("kategori", "turkiye"),
                h_veri.get("ig_baslik", metin[:60])[:250],
                f"https://dailybrief.co/ozel/{int(time.time())}",
                h_veri.get("slayt_ozet", metin[:200])[:800],
            ),
        )
        haber_id = cursor.lastrowid
        db.metin_kaydet(con, haber_id, h_veri, makale_metni=metin)
        con.commit()

        return _post_olustur_ve_onaya_sun(
            con, ayarlar, haber_id, kaynak="Özel Duyuru & Bülten", ozet_not="📢 ÖZEL DUYURU & BÜLTEN"
        )

    except Exception as e:
        log.exception("Özel metin postu üretilemedi: %s", e)
        telegram_bot.mesaj_gonder(f"⚠️ Özel metin işlenirken bir hata oluştu:\n<code>{html.escape(str(e)[:300])}</code>", html=True)
        return 1


def makro_haber_uret(komut_metni: str, con, ayarlar: dict, basan: str = "", veri_tipi: str = "makro") -> int:
    """
    /faiz, /enflasyon, /fed veya /makro komutu:
    Kritik makro ekonomik veriler için anında 1080x1350 ve 1080x1920 infografik postu üretir.
    """
    from . import makro_kart

    komut_metni = komut_metni.strip()
    telegram_bot.mesaj_gonder(f"⚡ <b>Kritik Makro İnfografik Kartı Hazırlanıyor…</b>\nVeriler analiz ediliyor ve canlı piyasa reaksiyonu işleniyor…", html=True)

    try:
        prompt = (
            f"Kullanıcının verdiği aşağıdaki makro ekonomik karar/veri girdisini yapılandırılmış JSON formatına dönüştür:\n\n"
            f"GİRDİ (Türü: {veri_tipi}):\n{komut_metni}\n\n"
            f"İSTENEN JSON FORMATI:\n"
            f"{{\n"
            f'  "rozet_metni": "TCMB POLİTİKA FAİZİ" veya "TÜİK TÜFE ENFLASYON" veya "FED FOMC KARARI" veya "MAKRO EKONOMİ",\n'
            f'  "ana_deger": "%45.00" (Örn: faiz veya enflasyon oranı, dev rakam),\n'
            f'  "durum_etiketi": "POLİTİKA FAİZİ SABİT TUTULDU" veya "+250 BAZ PUAN ARTIŞ" veya "YILLIK TÜFE: %61.78",\n'
            f'  "karsilastirma": {{"onceki": "%45.00", "beklenti": "%45.00", "aciklanan": "%45.00"}},\n'
            f'  "spot_metin": "1-2 cümlelik en vurucu karar ve piyasa analizi özeti",\n'
            f'  "ig_baslik": "Instagram ve sosyal medya için çarpıcı Türkçe manşet (max 90 karakter)",\n'
            f'  "ig_caption": "2-3 paragraflık detaylı, emojili ve hashtagli kurumsal Instagram açıklaması",\n'
            f'  "kaynak": "TCMB" veya "TÜİK" veya "Federal Reserve"\n'
            f"}}\n"
            f"Sadece saf JSON döndür."
        )

        yanit = generate_text.gemini_cagir(prompt, ayarlar)
        if not yanit or not isinstance(yanit, dict):
            raise RuntimeError("Gemini makro veriyi işleyemedi.")

        rozet_metni = yanit.get("rozet_metni", "MAKRO EKONOMİ")
        ana_deger = yanit.get("ana_deger", "%0.00")
        durum_etiketi = yanit.get("durum_etiketi", "AÇIKLANDI")
        karsilastirma = yanit.get("karsilastirma", {})
        spot_metin = yanit.get("spot_metin", komut_metni[:180])
        kaynak = yanit.get("kaynak", "TCMB")
        ig_baslik = yanit.get("ig_baslik", f"{rozet_metni}: {ana_deger}")
        ig_caption = yanit.get("ig_caption", spot_metin)

        # 1. 4:5 Post ve 9:16 Story Görsellerini Çiz
        post_yolu = makro_kart.makro_karti_ciz(
            rozet_metni=rozet_metni,
            ana_deger=ana_deger,
            durum_etiketi=durum_etiketi,
            karsilastirma=karsilastirma,
            spot_metin=spot_metin,
            kaynak=kaynak,
            dikey_story=False,
        )
        story_yolu = makro_kart.makro_karti_ciz(
            rozet_metni=rozet_metni,
            ana_deger=ana_deger,
            durum_etiketi=durum_etiketi,
            karsilastirma=karsilastirma,
            spot_metin=spot_metin,
            kaynak=kaynak,
            dikey_story=True,
        )

        # 2. ImgBB / Barındırıcıya Yükle
        yukleme_post = upload_image.gorsel_yukle(post_yolu, ayarlar)
        post_url = yukleme_post["url"]

        story_url = None
        try:
            yukleme_story = upload_image.gorsel_yukle(story_yolu, ayarlar)
            story_url = yukleme_story["url"]
        except Exception as e:
            log.warning("Story yüklenemedi: %s", e)

        # 3. Veritabanına Kaydet
        cursor = con.execute(
            """INSERT INTO haberler (
                kaynak, kategori, agirlik, baslik_orj, link, ozet_orj,
                ig_baslik, ig_caption, slayt_ozet, detay_metni, onem_puani,
                vurgu_sayi, vurgu_etiket, gorsel_url, story_url, gorsel_kaynagi,
                yayin_tarihi, cekilme_zamani, durum, son_dakika
            ) VALUES (
                ?, 'ekonomi', 10, ?, ?, ?,
                ?, ?, ?, ?, 10,
                ?, ?, ?, ?, 'makro_kart',
                datetime('now'), datetime('now'), 'onay_bekliyor', 1
            )""",
            (
                kaynak,
                ig_baslik[:250],
                f"https://dailybrief.co/makro/{int(time.time())}",
                spot_metin[:800],
                ig_baslik,
                ig_caption,
                spot_metin,
                spot_metin,
                ana_deger,
                durum_etiketi,
                post_url,
                story_url,
            ),
        )
        haber_id = cursor.lastrowid
        con.commit()

        # 4. Telegram Onay Kartına Sun
        taze = con.execute("SELECT * FROM haberler WHERE id = ?", (haber_id,)).fetchone()
        basliklar = [ig_baslik]
        foto_mesaj_idler = telegram_bot.slaytlari_gonder([post_url], basliklar=basliklar)

        ana_bilgi = f"⚡ <b>KRİTİK MAKRO VERİ ALARMI: {rozet_metni}</b>\n\n📌 <b>{ig_baslik}</b>\n\n{spot_metin}\n\n🏷️ Kaynak: {kaynak}"
        menu = telegram_bot.ana_menu(1)
        onay_mesaj_id = telegram_bot.mesaj_gonder(ana_bilgi, butonlar=menu["inline_keyboard"], html=True)

        con.execute(
            "UPDATE haberler SET telegram_message_id = ? WHERE id = ?",
            (onay_mesaj_id, haber_id),
        )
        con.commit()

        try:
            db_senkron.hemen_kaydet(f"makro haber olusturuldu: {haber_id}")
        except Exception as e:
            log.warning("db senkron hatası: %s", e)

        log.info("Makro haber kartı Telegram'a sunuldu (haber_id=%s, mesaj_id=%s)", haber_id, onay_mesaj_id)
        return 0

    except Exception as e:
        log.exception("Makro haber üretilemedi: %s", e)
        telegram_bot.mesaj_gonder(f"⚠️ Makro haber kartı üretilirken bir hata oluştu:\n<code>{html.escape(str(e)[:300])}</code>", html=True)
        return 1

