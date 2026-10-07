"""
uygulama_koprusu.py — OzBorn Studio mobil uygulamasına botun durum özetini bırakır.

NEDEN VAR (7 Eki 2026):
    Uygulama Telegram'ın yerini alacak bir arayüz. Telegram KAPANMIYOR: bot
    onayları ikisine paralel sunuyor, biri onaylayınca öbürü de kapanıyor.
    Uygulamanın gördüğü her şey bu özetten geliyor — açık onaylar, öneriler,
    son yayınlar, olaylar, Telegram'dan değiştirilebilen ayarlar.
    Sözleşme: ozborn-studio/docs/KOPRU-PROTOKOLU.md

TEK KANCA:
    `db_senkron.hemen_kaydet()` veritabanını her kaydettiğinde özet yeniden
    kuruluyor ve Worker'a gönderiliyor. Onaya sunma, yayın, iptal, metin
    yenileme… hepsi o fonksiyondan geçiyor. Her akışa ayrı kanca yazmak bir
    yolu unutmak demekti — bu projedeki en sık hata sınıfı tam olarak bu.

ÖZET VERİTABANININ SAF FONKSİYONU:
    "Üretildiği an" gibi değişen alan YOK; aynı veritabanı aynı özeti veriyor.
    Worker aynı özeti ikinci kez yazmıyor, göreli zamanı ("12 dk önce")
    uygulama hesaplıyor.

İKİNCİL KANAL — BOTU ASLA DURDURMAZ:
    Worker'a ulaşılamazsa, ayar kapalıysa, bir alan bozuksa: log'a yazılır,
    bot çalışmaya devam eder. Asıl kanal Telegram.

KİMLİK — YENİ SIR YOK:
    Worker ile bot zaten aynı TELEGRAM_BOT_TOKEN'ı biliyor. Anahtar ondan
    türetiliyor: HMAC-SHA256(jeton, "ozborn-kopru-v1"). Jetonun kendisi ağa
    çıkmıyor, yeni bir GitHub secret'ı gerekmiyor.

YALNIZCA GITHUB ACTIONS'TA GÖNDERİR:
    Veritabanının sahibi GitHub. Yerelde çalışan bir script geride kalmış
    yerel veritabanının özetini gönderip uygulamayı yanıltmasın diye yerelde
    sessiz kalıyor (deneme için: UYGULAMA_KOPRUSU_ZORLA=1).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

KOK = Path(__file__).resolve().parent.parent

PROTOKOL = 1
ANAHTAR_ETIKETI = b"ozborn-kopru-v1"
ZAMAN_ASIMI_SN = 6

# Özette kaç kayıt taşınıyor. Uygulama yaşa göre ayrıca süzüyor; burada
# sınır yalnızca özetin boyunu tutmak için (bir onay ~5-30 KB).
AZAMI_ONAY = 20
AZAMI_ONERI = 15
AZAMI_YAYIN = 20
AZAMI_OLAY = 10
KAYNAK_METNI_AZAMI = 3000

# Kanal kodu → `config.yaml → sosyal` bayrağı. None: her zaman açık.
# Kodlar Telegram düğmeleriyle aynı (`kanal:ig`, `kanal:tiktok_video`…).
KANAL_BAYRAKLARI: dict[str, str | None] = {
    "ig": None,
    "reels": None,
    "story": None,
    "threads": "threadse_de_at",
    "facebook": "facebooka_da_at",
    "twitter": "twittera_da_at",
    "youtube": "youtube_a_da_at",
    "tiktok": "tiktoka_da_at",
    "tiktok_video": "tiktoka_da_at",
}

# Yayınlanmış bir turda hangi kanala gerçekten çıktığını gösteren kolonlar.
YAYIN_KOLONLARI = {
    "ig": "ig_post_id",
    "story": "story_post_id",
    "facebook": "facebook_post_id",
    "facebook_reels": "facebook_reel_id",
    "threads": "threads_post_id",
    "twitter": "twitter_post_id",
    "youtube": "youtube_post_id",
    "tiktok": "tiktok_post_id",
}


# ----------------------------------------------------------------------
# Yardımcılar
# ----------------------------------------------------------------------

def _iso(deger) -> str | None:
    """
    Veritabanı zamanını ISO 8601 UTC'ye çevirir ("…Z").

    ⚠️ SQLite `datetime('now')` SAAT DİLİMSİZ yazıyor ("2026-10-07 06:52:39")
    ve o değer UTC. Saat dilimi taşıyanlar ("…+00:00", "…+03:00") olduğu gibi
    çevriliyor.
    """
    if not deger:
        return None
    try:
        t = datetime.fromisoformat(str(deger).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _kanallari_coz(ham: str | None) -> tuple[list[str] | None, str | None]:
    """`yayin_kanallari` ("ig,story,ses_muzikli") → (kanallar, ses kipi)."""
    if not ham:
        return None, None
    parcalar = [p.strip().lower() for p in str(ham).split(",") if p.strip()]
    ses = "muzikli" if "ses_muzikli" in parcalar else ("muziksiz" if "ses_muziksiz" in parcalar else None)
    return [p for p in parcalar if not p.startswith("ses_")], ses


def _tur_turu(haberler: list) -> str:
    ilk = haberler[0]
    tur = (ilk["tur"] or "").strip()
    if tur == "ekonomi":
        return "piyasa"
    if tur == "haftalik":
        return "haftalik"
    if any(h["son_dakika"] for h in haberler) or len(haberler) == 1:
        return "sondakika"
    return "tur"


def _haber_ozeti(h) -> dict:
    return {
        "id": h["id"],
        "baslik": (h["ig_baslik"] or h["baslik_orj"] or "").strip(),
        "ozet": (h["slayt_ozet"] or "").strip(),
        "kaynak": h["kaynak"],
        "kategori": h["kategori"],
        "onem": h["onem_puani"],
        "link": h["link"],
        "kaynak_metni": (h["makale_metni"] or h["ozet_orj"] or "")[:KAYNAK_METNI_AZAMI],
        "gorsel_kaynagi": h["gorsel_kaynagi"],
        "gorsel_atif": h["gorsel_atif"] or "",
    }


# ----------------------------------------------------------------------
# Özet
# ----------------------------------------------------------------------

def _onaylar(con, ayarlar: dict) -> list[dict]:
    from . import dogrula, tur_icerigi

    mesajlar = [r[0] for r in con.execute(
        "SELECT DISTINCT telegram_message_id FROM haberler "
        "WHERE telegram_message_id IS NOT NULL "
        "AND durum IN ('onay_bekliyor', 'baslik_onayi') "
        "ORDER BY telegram_message_id DESC LIMIT ?",
        (AZAMI_ONAY,),
    )]

    sonuc = []
    for mesaj_id in mesajlar:
        haberler = tur_icerigi.haberleri_getir(con, mesaj_id)
        if not haberler:
            continue
        tur = _tur_turu(haberler)
        baslik_asamasi = any(h["durum"] == "baslik_onayi" for h in haberler)
        planlanan = next((h["planlanan_yayin"] for h in haberler if h["planlanan_yayin"]), None)
        gonderim = max((h["gonderim_zamani"] or "" for h in haberler), default="") or None
        kanallar, ses = _kanallari_coz(haberler[0]["yayin_kanallari"])

        son_gecerlilik = None
        if tur == "sondakika" and not planlanan and gonderim:
            t = datetime.fromisoformat(_iso(gonderim).replace("Z", "+00:00"))
            son_gecerlilik = _iso((t + tur_icerigi.SON_DAKIKA_ONAY_OMRU).isoformat())

        # Metin, görsel ve uyarı ayrı ayrı korunuyor: biri patlarsa onay yine
        # görünsün, yalnızca o alan boş kalsın.
        try:
            metin = None if baslik_asamasi else tur_icerigi.yayin_metni(haberler, ayarlar)
        except Exception:                                   # noqa: BLE001
            log.warning("uygulama köprüsü: %s metni kurulamadı", mesaj_id, exc_info=True)
            metin = None
        try:
            slaytlar = [{"url": u, "etiket": e}
                        for u, e in tur_icerigi.slaytlar(con, haberler, mesaj_id)]
        except Exception:                                   # noqa: BLE001
            log.warning("uygulama köprüsü: %s slaytları kurulamadı", mesaj_id, exc_info=True)
            slaytlar = []
        try:
            uyari = dogrula.turu_dogrula(haberler)[0]
        except Exception:                                   # noqa: BLE001
            log.warning("uygulama köprüsü: %s denetlenemedi", mesaj_id, exc_info=True)
            uyari = ""

        sonuc.append({
            "mesaj_id": mesaj_id,
            "tur": tur,
            "durum": "baslik_onayi" if baslik_asamasi else ("planli" if planlanan else "bekliyor"),
            "olusma": _iso(gonderim),
            "son_gecerlilik": son_gecerlilik,
            "planlanan": _iso(planlanan),
            "kanallar": kanallar,
            "ses": ses,
            "metin": metin,
            "uyari": uyari,
            "slaytlar": slaytlar,
            "haberler": [_haber_ozeti(h) for h in haberler],
        })
    return sonuc


def _oneriler(con) -> list[dict]:
    """
    Telegram'a öneri olarak gönderilmiş, henüz hazırlanmamış başlıklar.

    ⚠️ Yaşa göre süzme BURADA YAPILMIYOR — "şu an" özeti zamana bağlar ve
    özet veritabanının saf fonksiyonu olmaktan çıkar. Uygulama `yayin_tarihi`ne
    bakıp eskileri gizliyor.
    """
    return [{
        "id": r["id"],
        "baslik": (r["ig_baslik"] or r["baslik_orj"] or "").strip(),
        "kaynak": r["kaynak"],
        "kategori": r["kategori"],
        "puan": r["onem_puani"],
        "yayin_tarihi": _iso(r["yayin_tarihi"]),
    } for r in con.execute(
        "SELECT id, ig_baslik, baslik_orj, kaynak, kategori, onem_puani, yayin_tarihi "
        "FROM haberler WHERE oneri_gonderildi = 1 AND durum = 'yeni' "
        "AND COALESCE(sadece_tur, 0) = 0 "
        "ORDER BY yayin_tarihi DESC, id DESC LIMIT ?",
        (AZAMI_ONERI,),
    )]


def _yayinlananlar(con) -> list[dict]:
    """
    Son yayınlanan turlar ve gerçekten çıktıkları kanallar.

    ⚠️ Yayın anı kolonda YOK; `zaman` onaya sunulma anı (gonderim_zamani).
    Uygulama bunu "onaya sunuldu" diye gösteriyor, "yayınlandı" diye değil.
    """
    gruplar = list(con.execute(
        "SELECT COALESCE(telegram_message_id, -id) AS grup, MAX(gonderim_zamani) AS zaman "
        "FROM haberler WHERE durum = 'yayinlandi' "
        "GROUP BY grup ORDER BY zaman DESC, grup DESC LIMIT ?",
        (AZAMI_YAYIN,),
    ))
    sonuc = []
    for g in gruplar:
        grup = g["grup"]
        if grup >= 0:
            haberler = list(con.execute(
                "SELECT * FROM haberler WHERE telegram_message_id = ? AND durum = 'yayinlandi' "
                "ORDER BY onem_puani DESC, id", (grup,)))
        else:
            haberler = list(con.execute("SELECT * FROM haberler WHERE id = ?", (-grup,)))
        if not haberler:
            continue
        kanallar = {ad: any(h[kolon] for h in haberler) for ad, kolon in YAYIN_KOLONLARI.items()}
        ilk = haberler[0]
        sonuc.append({
            "mesaj_id": grup if grup >= 0 else None,
            "tur": _tur_turu(haberler),
            "baslik": (ilk["ig_baslik"] or ilk["baslik_orj"] or "").strip(),
            "haber_sayisi": len(haberler),
            "zaman": _iso(g["zaman"]),
            "kapak": ilk["gorsel_url"],
            "kanallar": {k: v for k, v in kanallar.items() if v},
        })
    return sonuc


def _olaylar() -> list[dict]:
    """
    `hata_bildir`'in kaydettiği son arızalar.

    ⚠️ Ham hata metni (`ham_hata`) BİLEREK taşınmıyor: istisna metinleri
    istek adreslerini, bazen de sorgu dizgisindeki jetonu içerebiliyor.
    Yalnızca katalogdaki insan dilindeki açıklamalar gidiyor.
    """
    from . import hata_bildir

    yol = Path(hata_bildir.HATA_LOG_YOLU)
    if not yol.exists():
        return []
    satirlar = yol.read_text(encoding="utf-8").splitlines()[-AZAMI_OLAY:]
    sonuc = []
    for satir in reversed(satirlar):
        try:
            k = json.loads(satir)
        except ValueError:
            continue
        sonuc.append({
            "zaman": _iso(k.get("tarih")),
            "baslik": k.get("baslik") or "",
            "ne_oldu": k.get("ne_oldu") or "",
            "neden": k.get("neden") or "",
            "ne_yapilir": k.get("ne_yapilir") or "",
            "nerede": k.get("nerede") or "",
            "eylem": k.get("eylem") or "",
        })
    return sonuc


def _ayarlar(con, ayarlar: dict) -> list[dict]:
    """Telegram'dan (ve artık uygulamadan) değiştirilebilen ayarlar — beyaz liste `ayar.py`'de."""
    from . import ayar

    return [{
        "yol": yol,
        "ad": ad,
        "deger": ayar.gecerli_deger(con, ayarlar, yol),
        "secenekler": list(secenekler),
    } for yol, (ad, secenekler) in ayar.DEGISTIRILEBILIR.items()]


def _kanallar(ayarlar: dict) -> list[dict]:
    from . import telegram_bot

    sosyal = ayarlar.get("sosyal") or {}
    return [{
        "kod": kod,
        "acik": True if bayrak is None else bool(sosyal.get(bayrak)),
        "varsayilan": bool(telegram_bot.VARSAYILAN_KANAL_SECIMI.get(kod)),
    } for kod, bayrak in KANAL_BAYRAKLARI.items()]


def ozet_kur(con, ayarlar: dict) -> dict:
    """
    Uygulamanın göreceği bütün durum. Veritabanının SAF fonksiyonu.

    `con` satırları isimle okunabilen bir bağlantı olmalı (sqlite3.Row).
    `ayarlar`, `ayar.uygula` işlenmiş config sözlüğü.
    """
    k = ayarlar.get("uygulama_koprusu") or {}
    ig = ayarlar.get("instagram") or {}
    hesap = (ig.get("hesap_kullanici_adi") or "").strip()
    return {
        "protokol": PROTOKOL,
        "proje": {
            "id": k.get("proje_id") or "proje",
            "ad": k.get("proje_adi") or "Bot",
            "hesap": f"@{hesap}" if hesap else "",
        },
        "kanallar": _kanallar(ayarlar),
        "onaylar": _onaylar(con, ayarlar),
        "oneriler": _oneriler(con),
        "yayinlananlar": _yayinlananlar(con),
        "olaylar": _olaylar(),
        "ayarlar": _ayarlar(con, ayarlar),
        "havuz": con.execute("SELECT COUNT(*) FROM haberler WHERE durum = 'yeni'").fetchone()[0],
        # Worker'ın iç alanı: eşleştirme isteğini ve "uygulamadan işlendi"
        # işaretini Telegram'da hangi gruba yazacağı. Uygulamaya verilmiyor.
        "_ic": {"telegram_sohbet": os.getenv("TELEGRAM_CHAT_ID", "").strip()},
    }


# ----------------------------------------------------------------------
# Gönderim
# ----------------------------------------------------------------------

def imza(jeton: str) -> str:
    """Bot ↔ Worker ortak anahtarı. Worker aynı hesabı kendi jetonuyla yapıyor."""
    return hmac.new(jeton.encode("utf-8"), ANAHTAR_ETIKETI, hashlib.sha256).hexdigest()


def _config() -> dict:
    import yaml

    return yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8")) or {}


def ozet_gonder(db_yolu: str | Path | None = None) -> bool:
    """
    Özeti kurup Worker'a gönderir. Ne olursa olsun İSTİSNA FIRLATMAZ.

    True: Worker özeti aldı. False: kapalı, yerel, ayarsız ya da başarısız
    (sebep log'da). Çağıran (db_senkron) sonuca bakmıyor — bilerek.
    """
    try:
        ayarlar = _config()
        k = ayarlar.get("uygulama_koprusu") or {}
        if not k.get("acik"):
            return False
        if os.getenv("GITHUB_ACTIONS") != "true" and os.getenv("UYGULAMA_KOPRUSU_ZORLA") != "1":
            log.debug("uygulama köprüsü: GitHub Actions dışında, özet gönderilmedi")
            return False
        adres = (k.get("adres") or "").strip().rstrip("/")
        jeton = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        if not adres or not jeton:
            log.info("uygulama köprüsü: adres ya da Telegram jetonu yok, özet gönderilmedi")
            return False

        from . import ayar, db

        yol = Path(db_yolu) if db_yolu else Path(db.DB_YOLU)
        con = sqlite3.connect(yol, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            ayar.uygula(con, ayarlar)
            ozet = ozet_kur(con, ayarlar)
        finally:
            con.close()

        import requests

        govde = json.dumps(ozet, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        cevap = requests.post(
            f"{adres}/api/kopru/ozet",
            data=govde.encode("utf-8"),
            headers={"content-type": "application/json; charset=utf-8",
                     "authorization": f"Bearer {imza(jeton)}"},
            timeout=ZAMAN_ASIMI_SN,
        )
        if cevap.status_code != 200:
            log.warning("uygulama köprüsü: Worker %s döndü: %s",
                        cevap.status_code, cevap.text[:200])
            return False
        log.info("uygulama köprüsü: özet gönderildi (%d onay, %d KB, %s)",
                 len(ozet["onaylar"]), len(govde) // 1024,
                 "yeni" if (cevap.json() or {}).get("degisti") else "aynı")
        return True
    except Exception:                                       # noqa: BLE001
        # İkincil kanal: arıza log'a, bot yoluna devam ediyor. exc_info ile
        # yazılıyor ki bir KOD hatası "ağ hatası" gibi sessizce kaybolmasın.
        log.warning("uygulama köprüsü: özet gönderilemedi", exc_info=True)
        return False
