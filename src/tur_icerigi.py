"""
tur_icerigi.py — Bir onay turunun İÇERİĞİ: hangi haberler, hangi sırayla,
hangi görsellerle ve hangi metinle yayınlanacak.

NEDEN AYRI MODÜL (7 Eki 2026):
    OzBorn Studio mobil uygulaması onay ekranında yayınlanacak metni ve
    slaytları gösteriyor. Bu bilgi yayın anında `onay_isle.yayinla` içinde
    kuruluyordu. Uygulama özeti kendi kopyasını kursaydı ikisi bir gün
    ayrışırdı — 18 Ağu 2026'daki "onaylanan metin ≠ yayınlanan metin"
    hatasının uygulamadaki tekrarı olurdu. Artık YAYIN YOLU ve UYGULAMA
    ÖZETİ ikisi de buradan besleniyor.

⚠️ `onay_isle.py` içinde aynı kuruluşun eski kopyaları hâlâ duruyor
   (metin yenileme, başlık düzeltme, kurtarma akışları — ~6 yer). Onlar
   onay mesajını yeniden kurarken kullanılıyor; bilerek dokunulmadı.
   Yayınlanan metni belirleyen tek yer `yayin_metni`.
"""

from __future__ import annotations

import json
from datetime import timedelta

from . import caption, filtre

# Son dakika onayı bu kadar süre Telegram'da (ve uygulamada) yayınlanabilir
# bekler; sonra düşer ve haber havuza döner. `son_dakika.omru_bitti_mi`
# kararı buradan veriyor, uygulama "… içinde düşer" yazısını buradan
# hesaplıyor — iki yerde ayrı sayı yaşamasın.
SON_DAKIKA_ONAY_OMRU = timedelta(hours=24)


def haberleri_getir(con, mesaj_id: int) -> list:
    """
    Bu onay mesajına bağlı haberler, SLAYT SIRASIYLA.

    ⚠️ SIRALAMA: kullanıcı slaytı taşıdıysa `slayt_sirasi` geçerli;
    yoksa gündüz tekil yayınlanmış haber EN SONA (`daha_once_yayinlandi`),
    sonra önem ve tarih. Slayt numarası bu sıraya göre verildiği için
    başka bir sıralama "3. slayt" dediğinde başka haberi hedefler.
    """
    return list(con.execute(
        "SELECT * FROM haberler WHERE telegram_message_id = ? "
        "ORDER BY CASE WHEN COALESCE(slayt_sirasi, 0) > 0 THEN slayt_sirasi ELSE 999 END ASC, "
        "COALESCE(daha_once_yayinlandi, 0) ASC, "
        "onem_puani DESC, yayin_tarihi DESC",
        (mesaj_id,),
    ))


def detay_urlleri(ham) -> list[str]:
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


def katman_bilgisi(haberler: list) -> list[dict]:
    """Caption'ın atıf bloğu için her haberin görsel katmanı ve atfı."""
    return [
        {"id": h["id"], "katman": h["gorsel_kaynagi"], "atif": h["gorsel_atif"] or ""}
        for h in haberler
    ]


def slaytlar(con, haberler: list, mesaj_id) -> list[tuple[str, str]]:
    """
    Yayına gidecek slaytlar SIRASIYLA: (görsel adresi, kısa etiket).

    * Ekonomi turu: önce piyasa ısı haritası, sonra 30 varlık tablosu
      (ikisi `ayarlar` tablosunda mesaj kimliğiyle saklı), sonra haberler.
    * Son dakika: tek haberden 1 kapak + 1-4 ayrıntı sayfası; ayrıntılar
      `detay_url` kolonunda JSON listesi. Eklenmezse elde tek görsel
      kalıyor ve Instagram carousel'i reddediyor.

    Etiket yalnızca gösterim için (uygulamadaki slayt altyazısı); adres ve
    sıra `yayin_gorselleri` ile birebir aynı — ikisi bu fonksiyondan.
    """
    liste: list[tuple[str, str]] = []
    for h in haberler:
        if h["gorsel_url"]:
            liste.append((h["gorsel_url"], (h["ig_baslik"] or h["baslik_orj"] or "").strip()))

    ilk = dict(haberler[0]) if haberler else {}
    if ilk.get("tur") == "ekonomi":
        tablo = con.execute(
            "SELECT deger FROM ayarlar WHERE anahtar = ?",
            (f"piyasa_tablosu_{mesaj_id}",),
        ).fetchone()
        kart = con.execute(
            "SELECT deger FROM ayarlar WHERE anahtar = ?",
            (f"piyasa_karti_{mesaj_id}",),
        ).fetchone()
        if tablo and tablo["deger"]:
            liste.insert(0, (tablo["deger"], "30 varlık tablosu"))
        if kart and kart["deger"]:
            liste.insert(0, (kart["deger"], "Piyasa ısı haritası"))

    for h in haberler:
        if h["son_dakika"]:
            ayrintilar = detay_urlleri(h["detay_url"])
            for sira, url in enumerate(ayrintilar, start=1):
                etiket = "Ayrıntı" if len(ayrintilar) == 1 else f"Ayrıntı {sira}/{len(ayrintilar)}"
                liste.append((url, etiket))
    return liste


def yayin_gorselleri(con, haberler: list, mesaj_id) -> list[str]:
    """Yayına gidecek slayt görsellerinin adresleri, sırasıyla (bkz. `slaytlar`)."""
    return [url for url, _ in slaytlar(con, haberler, mesaj_id)]


def yayin_metni(haberler: list, ayarlar: dict) -> str:
    """
    Instagram'a gidecek açıklama metni — onay ekranında gösterilen metin de bu.

    Ekonomi turunun metni üretimde hazırlanıp `ig_caption`'a yazılıyor;
    tek haberli ve son dakika postu kendi biçimini kullanıyor; çok haberli
    tur numaralı manşet listesi.
    """
    ilk = dict(haberler[0]) if haberler else {}
    if ilk.get("tur") == "ekonomi" and ilk.get("ig_caption"):
        metin = ilk["ig_caption"]
    elif haberler[0]["son_dakika"] or len(haberler) == 1:
        metin = caption.son_dakika_caption(haberler[0], katman_bilgisi(haberler), ayarlar)
    else:
        metin = caption.caption_kur(haberler, katman_bilgisi(haberler), ayarlar=ayarlar)
    return filtre.markdown_temizle(metin)
