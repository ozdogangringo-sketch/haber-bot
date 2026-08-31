"""
hata_bildir.py — Bir job patladığında Telegram'a NE OLDUĞUNU anlatır.

NEDEN VAR:
    Bot gözetimsiz çalışıyor. Bir job patladığında ortaya çıkan şey
    Python traceback'iydi:

        RuntimeError: Telegram hatası (sendMediaGroup): 400: Bad Request:
        failed to send message #9 with the error message "WEBPAGE_CURL_FAILED"

    Bu metin, kodu yazan için bile ilk bakışta anlaşılmıyor; kullanıcı
    için hiç anlaşılmıyor. Üstelik yanıltıcı: "Bad Request" bizim
    isteğimizde kusur varmış gibi duruyor, oysa sorun Telegram'ın
    görseli imgbb'den indirememesi.

    Burada her tanıdık hata için üç şey üretiliyor:
      NE OLDU    — tek cümle, teknik terim yok
      NEDEN      — kök sebep, "bizim hatamız mı, karşı taraf mı"
      NE YAPILIR — somut eylem, mümkünse tek düğme

ÖNEMLİ: tanınmayan hata GİZLENMİYOR. Ham metin "ayrıntı" olarak
    aynen gösteriliyor — yanlış teşhis, teşhis koymamaktan kötü.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from . import telegram_bot

log = logging.getLogger(__name__)

HATA_LOG_YOLU = Path("data") / "hata_kayitlari.jsonl"
SON_HATA_YOLU = Path("data") / "son_hata.txt"

# ----------------------------------------------------------------------
# Genişletilmiş Hata Kataloğu
# ----------------------------------------------------------------------
KATALOG = [
    {
        "desen": r"sqlite3\.Row.*has no attribute 'get'|'sqlite3\.Row' object has no attribute 'get'",
        "ne_oldu": "Veritabanı satır nesnesinde sözlük fonksiyonu (.get) çağrıldı.",
        "neden": "Veritabanından dönen satır doğrudan sözlük gibi kullanılmak istendi. Bu kod içi tip uyuşmazlığı giderildi.",
        "ne_yapilir": "Yayınla butonuna tekrar basarak yayını sorunsuz tamamlayabilirsin.",
        "eylem": "yeniden_yayinla",
    },
    {
        "desen": r"database is locked|database table is locked",
        "ne_oldu": "Veritabanı kilitli olduğu için işlem yapılamadı.",
        "neden": "İki işlem aynı anda SQLite veritabanına yazmaya çalıştı.",
        "ne_yapilir": "1-2 saniye bekleyip butona tekrar basmak genelde işlemi tamamlar.",
        "eylem": "yeniden_yayinla",
    },
    {
        "desen": r"2207052|2207003|Only photo or video can be accepted",
        "ne_oldu": "Instagram görselleri indirirken geçici zaman aşımına uğradı.",
        "neden": "Instagram sunucuları görsel barındırma adresinden (ImgBB) görseli çekerken geçici bir gecikme yaşadı.",
        "ne_yapilir": "Görseller sağlam. '🔄 Tekrar Yayınla' butonuna basarak doğrudan tekrar deneyebilirsin.",
        "eylem": "yeniden_yayinla",
    },
    {
        "desen": r"WEBPAGE_CURL_FAILED|failed to send message #\d+",
        "ne_oldu": "Telegram slayt görsellerini indiremedi.",
        "neden": "Telegram API ImgBB üzerindeki görsellere anlık erişemedi.",
        "ne_yapilir": "'🔄 Turu Yeniden Hazırla' butonuna basarak albümü sıfırdan gönderebilirsin.",
        "eylem": "tur_tekrar",
    },
    {
        "desen": r"KOTASI DOLDU|RESOURCE_EXHAUSTED|429.*(quota|Quota)",
        "ne_oldu": "Gemini'nin günlük ücretsiz kotası doldu.",
        "neden": "Günlük ücretsiz API limiti aşıldı. Kota her gün TR saatiyle ~10:00'da sıfırlanır.",
        "ne_yapilir": "Havuzda metni hazır haberlerle hemen metinsiz tur kurabilirsin.",
        "eylem": "tur_metinsiz",
    },
    {
        "desen": r"story yayınlanamadı|STORIES",
        "ne_oldu": "Post yayınlandı ama Instagram story'si atılamadı.",
        "neden": "Story görseli Instagram tarafından çekilemedi. Ana gönderi yayında.",
        "ne_yapilir": "Ana gönderi yayında olduğu için ek bir işlem gerekmez.",
        "eylem": "yok",
    },
    {
        "desen": r"carousel.*(2-10|10 görsel)|children.*(limit|invalid)",
        "ne_oldu": "Carousel'e izin verilen sınırların dışında görsel verildi.",
        "neden": "Tura 10'dan fazla veya 2'den az görsel eklenmeye çalışıldı.",
        "ne_yapilir": "Turu yeniden hazırlamak sorunu temizler.",
        "eylem": "tur_tekrar",
    },
    {
        "desen": r"(OAuthException|Error validating access token|Session has expired)",
        "ne_oldu": "Instagram/Facebook jetonu geçersiz.",
        "neden": "Facebook parolası değişmiş veya sayfa yönetici izni kalkmış olabilir.",
        "ne_yapilir": "Meta Graph API Explorer üzerinden yeni jeton alınıp secret güncellenmeli.",
        "eylem": "yok",
    },
    {
        "desen": r"graph\.threads\.net|THREADS_ACCESS_TOKEN",
        "ne_oldu": "Threads paylaşımı başarısız.",
        "neden": "Threads API jetonunun süresi dolmuş veya geçici ağ hatası oluşmuş.",
        "ne_yapilir": "Instagram postu etkilenmez. Jeton için `jeton-yenile` çalıştırılabilir.",
        "eylem": "yok",
    },
    {
        "desen": r"cannot unpack non-iterable|unpack.*bool",
        "ne_oldu": "Bir fonksiyon beklenenden farklı türde değer döndürdü.",
        "neden": "Kod düzenlemesinde bir fonksiyonun dönüş değeri bozulmuş.",
        "ne_yapilir": "Turu yeniden çalıştırmayı dene.",
        "eylem": "tur_tekrar",
    },
    {
        "desen": r"en az 2 görsel gerekli|görsel.*None|gorsel_url.*None",
        "ne_oldu": "Turun görsel URL'leri eksik, slaytlar yüklenememiş.",
        "neden": "Görseller ImgBB'ye yüklenirken hata olmuş ya da URL'ler veritabanına yazılamamış.",
        "ne_yapilir": "Turu yeniden hazırlamak görselleri sıfırdan üretir.",
        "eylem": "tur_tekrar",
    },
    {
        "desen": r"Application request limit|throttl|instagram.*429",
        "ne_oldu": "Instagram API geçici istek sınırı koydu.",
        "neden": "Kısa sürede çok fazla istek yapıldı. Sınır genelde 15-30 dakika içinde kalkar.",
        "ne_yapilir": "15-30 dakika bekleyip '🔄 Tekrar Yayınla' düğmesine bas.",
        "eylem": "yeniden_yayinla",
    },
    {
        "desen": r"AttributeError|KeyError|IndexError|TypeError|ValueError",
        "ne_oldu": "Kod yürütülürken beklenmeyen bir veri tipi veya alan uyuşmazlığı oluştu.",
        "neden": "Veri yapısı beklenenden farklıydı. Hata kalıcı loga kaydedildi.",
        "ne_yapilir": "'🔄 Tekrar Yayınla' veya '🔄 Turu Yeniden Hazırla' butonuna basabilirsin.",
        "eylem": "yeniden_yayinla",
    },
]


def _sadelestir(metin: str) -> str:
    return re.sub(r"\s+", " ", (metin or "")).strip()


def hata_kaydet(nerede: str, baslik: str, ham_hata: str, teshis: dict) -> None:
    """Her hatayı kalıcı jsonl ve son_hata.txt dosyalarına yazar."""
    try:
        from .zaman import su_an_tr, tr_format
        HATA_LOG_YOLU.parent.mkdir(parents=True, exist_ok=True)
        simdi = su_an_tr()
        kayit = {
            "tarih": simdi.isoformat(),
            "tarih_tr": tr_format(simdi, "tarih_saat"),
            "nerede": nerede,
            "baslik": baslik,
            "ne_oldu": teshis.get("ne_oldu", ""),
            "neden": teshis.get("neden", ""),
            "ne_yapilir": teshis.get("ne_yapilir", ""),
            "eylem": teshis.get("eylem", ""),
            "tanindi": teshis.get("tanindi", False),
            "ham_hata": ham_hata,
        }
        with open(HATA_LOG_YOLU, "a", encoding="utf-8") as f:
            f.write(json.dumps(kayit, ensure_ascii=False) + "\n")

        with open(SON_HATA_YOLU, "w", encoding="utf-8") as f:
            f.write(f"[{kayit['tarih_tr']}] {nerede} -> {baslik}\n\n{ham_hata[:3000]}")
    except Exception as e:
        log.warning("hata loguna yazılamadı: %s", e)


def tani(hata) -> dict:
    """Ham hatayı katalogla eşleştirir."""
    ham = _sadelestir(str(hata))
    for kayit in KATALOG:
        if re.search(kayit["desen"], ham, re.IGNORECASE):
            return {**kayit, "tanindi": True, "ham": ham}
    return {
        "ne_oldu": "Beklenmeyen bir hata oluştu.",
        "neden": "Bu hata kataloğa henüz kayıtlı değil.",
        "ne_yapilir": "Aşağıdaki butonları kullanarak turu yeniden deneyebilir veya sıfırlayabilirsin.",
        "eylem": "yeniden_yayinla",
        "tanindi": False,
        "ham": ham,
    }


def _butonlar(eylem: str, nerede: str = "", mesaj_id: int | str = "") -> list | None:
    """Hataya uygun zengin ve tek tıkla çözümlü eylem düğmeleri üretir."""
    butonlar = []

    m_str = str(mesaj_id or "")

    # 1. Öncelikli Çözüm Düğmesi
    if m_str.startswith("hazirla:"):
        butonlar.append([{"text": "🔄 Haberi Tekrar Hazırla", "callback_data": m_str}])
    elif eylem == "yeniden_yayinla" or str(eylem).startswith("yeniden_yayinla:"):
        cb = eylem if str(eylem).startswith("yeniden_yayinla:") else (f"yeniden_yayinla:{mesaj_id}" if mesaj_id else "yayinla")
        butonlar.append([{"text": "🔄 Tekrar Yayınla", "callback_data": cb}])
    elif eylem == "tur_metinsiz":
        butonlar.append([
            {"text": "🧯 Metinsiz Tur Kur", "callback_data": "hata:tur_metinsiz"},
            {"text": "🔄 Normal Tur Kur", "callback_data": "hata:tur_tekrar"},
        ])
    elif "son_dakika" in (nerede or "") or "oneri" in (nerede or "").lower() or "öneri" in (nerede or "").lower():
        butonlar.append([{"text": "🔄 Son Dakika Kontrolünü Tekrar Çalıştır", "callback_data": "hata:sondakika_tekrar"}])
    else:
        butonlar.append([{"text": "🔄 İşlemi Tekrar Dene", "callback_data": "hata:tur_tekrar"}])

    # 2. Genel Kontrol ve Temizlik Düğmeleri
    butonlar.append([
        {"text": "🔍 Yayın Durumunu Kontrol Et", "callback_data": "durum"},
        {"text": "🧹 Askıdaki Turu Sıfırla", "callback_data": "tur_temizle"},
    ])
    butonlar.append([{"text": "📄 Detaylı Hata Kaydı", "callback_data": "hata:ayrinti"}])
    return butonlar


def mesaji_kur(baslik: str, teshis: dict, nerede: str = "") -> str:
    """Telegram mesaj metni (HTML güvenli ve zengin açıklamalı)."""
    import html as html_lib

    b_esc = html_lib.escape(baslik or "")
    n_esc = html_lib.escape(nerede or "")
    ne_oldu = html_lib.escape(teshis.get("ne_oldu", "") or "")
    neden = html_lib.escape(teshis.get("neden", "") or "")
    ne_yapilir = html_lib.escape(teshis.get("ne_yapilir", "") or "")
    ham = html_lib.escape(str(teshis.get("ham", ""))[:450] or "")

    p = [f"⚠️ <b>BİR SORUN OLUŞTU:</b> {b_esc}"]
    if nerede:
        p.append(f"📍 <b>İşlem / Konum:</b> <code>{n_esc}</code>")
    p.append("")
    p.append(f"🔍 <b>NE OLDU?</b>\n{ne_oldu}")
    p.append("")
    p.append(f"💡 <b>NEDEN?</b>\n{neden}")
    p.append("")
    p.append(f"🛠️ <b>ÇÖZÜM / NE YAPILMALI?</b>\n{ne_yapilir}")
    if ham:
        p.append("")
        p.append(f"📄 <b>HATA DETAYI:</b>\n<code>{ham}</code>")
    return "\n".join(p)


def bildir(baslik: str, hata, nerede: str = "", mesaj_id: int | str = "") -> bool:
    """Hatayı teşhis edip kalıcı kaydeder ve Telegram'a butonlarla yazar."""
    try:
        teshis = tani(hata)
        ham_hata = _sadelestir(str(hata))
        hata_kaydet(nerede, baslik, ham_hata, teshis)

        metin = mesaji_kur(baslik, teshis, nerede)
        telegram_bot.mesaj_gonder(
            metin, butonlar=_butonlar(teshis["eylem"], nerede, mesaj_id=mesaj_id), html=True
        )
        log.info("hata Telegram'a bildirildi ve kaydedildi: %s", teshis["ne_oldu"])
        return True
    except Exception as e:
        log.warning("hata bildirimi gönderilemedi: %s", e)
        return False


def son_ham_hata_kaydet(metin: str) -> None:
    try:
        SON_HATA_YOLU.parent.mkdir(parents=True, exist_ok=True)
        with open(SON_HATA_YOLU, "w", encoding="utf-8") as f:
            f.write(_sadelestir(metin)[:3000])
    except Exception as e:
        log.warning("ham hata kaydedilemedi: %s", e)
