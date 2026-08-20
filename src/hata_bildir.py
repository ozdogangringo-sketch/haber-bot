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

import logging
import os
import re

from . import telegram_bot

log = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Hata kataloğu
# ----------------------------------------------------------------------
# Her kayıt: hangi metin görülürse (desen), kullanıcıya ne denir.
#
# `eylem` alanı Telegram'da hangi düğmenin çıkacağını belirliyor:
#   tur_tekrar    -> turu baştan hazırla
#   tur_metinsiz  -> Gemini'ye gitmeden, hazır metinlerle tur kur
#   yok           -> otomatik çözümü olmayan hata, yalnızca bilgi
KATALOG = [
    {
        "desen": r"database is locked|database table is locked",
        "ne_oldu": "Veritabanı kilitli olduğu için yazılamadı.",
        "neden": ("İki kod yolu aynı anda veritabanına yazmaya çalıştı. "
                  "20 Ağu 2026'da çoklu seçimde görüldü: onay işleyici "
                  "kendi bağlantısını açık tutarken tur kurucu ayrı bir "
                  "bağlantıdan yazmak istedi. WAL modu ve 30 sn bekleme "
                  "ile düzeltildi."),
        "ne_yapilir": ("Aynı haberi tekrar seçmek genelde yeterli. "
                       "Tekrarlıyorsa iki job aynı anda çalışıyor "
                       "olabilir — workflow'ların `veritabani` "
                       "concurrency grubunda olduğunu doğrula."),
        "eylem": "yok",
    },
    {
        "desen": r"story yayınlanamadı|STORIES",
        "ne_oldu": "Post yayınlandı ama Instagram story'si atılamadı.",
        "neden": ("Story görselini de Instagram imgbb'den kendisi "
                  "çekiyor ve o çekme başarısız oldu (2207052). Carousel "
                  "geçip story'nin geçmemesi olağan — aynı anda farklı "
                  "isteklerdeler."),
        "ne_yapilir": ("Post yayında, içerik kaybı YOK. Story ikincil "
                       "kanal; istersen uygulamadan elle paylaşabilirsin. "
                       "Sık tekrarlıyorsa imgbb yerine başka bir "
                       "barındırıcı denenebilir."),
        "eylem": "yok",
    },
    {
        "desen": r"metin üretilemedi|Gemini çağrısı başarısız",
        "ne_oldu": "Seçilen haberin metni üretilemedi.",
        "neden": ("Gemini isteği başarısız oldu — kota, güvenlik filtresi "
                  "ya da ağ hatası. Haber havuzda duruyor, kaybolmadı."),
        "ne_yapilir": ("Birkaç dakika sonra aynı haberi tekrar seçmek "
                       "genelde yeterli. Kota dolduysa metinsiz tur "
                       "seçeneği var."),
        "eylem": "tur_metinsiz",
    },
    {
        "desen": r"WEBPAGE_CURL_FAILED|failed to send message #\d+",
        "ne_oldu": "Telegram slayt görsellerini indiremedi.",
        "neden": ("Telegram görselleri imgbb'den KENDİSİ çekiyor ve o çekme "
                  "başarısız oldu. Slaytlarda kusur yok — aynı adresler "
                  "genelde saniyeler sonra sorunsuz iniyor. Instagram'daki "
                  "2207052 hatasının kardeşi."),
        "ne_yapilir": "Birkaç dakika sonra turu yeniden hazırlamak yeterli.",
        "eylem": "tur_tekrar",
    },
    {
        "desen": r"KOTASI DOLDU|RESOURCE_EXHAUSTED|429.*(quota|Quota)",
        "ne_oldu": "Gemini'nin günlük ücretsiz kotası doldu.",
        "neden": ("Ücretsiz katman model başına günde 20 istek veriyor "
                  "(iki modelle 40). Başarısız denemeler de kotadan "
                  "sayıldığı için kota göründüğünden erken bitiyor. "
                  "Kota Pasifik gece yarısında, TR ~10:00'da sıfırlanır."),
        "ne_yapilir": ("Havuzda metni HAZIR haberler var; onlarla tur "
                       "kurulabilir, Gemini'ye hiç gidilmez."),
        "eylem": "tur_metinsiz",
    },
    {
        "desen": r"2207052|2207003|Only photo or video can be accepted",
        "ne_oldu": "Instagram görselleri indiremedi.",
        "neden": ("Hata mesajı yanıltıcı: 'Only photo or video' diyor ama "
                  "gerçek sebep medya indirmenin başarısız olması. "
                  "Instagram görseli imgbb'den kendisi çekiyor."),
        "ne_yapilir": "Yayınla düğmesine tekrar basmak genelde yeterli.",
        "eylem": "yok",
    },
    {
        "desen": r"could not apply|rebase|CONFLICT|detached HEAD",
        "ne_oldu": "Veritabanı GitHub'a yazılamadı (git çakışması).",
        "neden": ("İki job aynı anda `data/haber.db` dosyasına yazmış. "
                  "İkili dosyada birleştirme mümkün olmadığı için çakışma "
                  "çözülemiyor."),
        "ne_yapilir": ("`scripts/db_kaydet.py` bunu kendisi çözmeli. "
                       "Tekrarlıyorsa workflow'lardan biri hâlâ ham git "
                       "komutu kullanıyor olabilir."),
        "eylem": "yok",
    },
    {
        "desen": r"carousel.*(2-10|10 görsel)|children.*(limit|invalid)",
        "ne_oldu": "Carousel'e 10'dan fazla görsel verildi.",
        "neden": ("Instagram carousel sınırı 10. Onaylanmayan bir son "
                  "dakika haberi havuza dönerken `detay_url` üstünde "
                  "kalmış olabilir."),
        "ne_yapilir": "Turu yeniden hazırlamak sorunu temizler.",
        "eylem": "tur_tekrar",
    },
    {
        "desen": r"(OAuthException|Error validating access token|Session has expired)",
        "ne_oldu": "Instagram/Facebook jetonu geçersiz.",
        "neden": ("Sayfa jetonu süresiz olmalı ama Facebook parolası "
                  "değiştiyse, uygulama izni geri çekildiyse veya sayfa "
                  "yöneticiliği kalktıysa ölür."),
        "ne_yapilir": ("Graph API Explorer'dan yeni jeton alıp "
                       "`IG_ACCESS_TOKEN` secret'ını güncellemek gerekiyor. "
                       "Bu elle yapılmalı."),
        "eylem": "yok",
    },
    {
        "desen": r"graph\.threads\.net|THREADS_ACCESS_TOKEN",
        "ne_oldu": "Threads paylaşımı başarısız.",
        "neden": ("Threads ikincil kanal. Jetonu 60 günlük ve haftalık "
                  "yenileniyor; yenileme kaçtıysa süresi dolmuş olabilir."),
        "ne_yapilir": ("Instagram postu etkilenmez. Jeton için "
                       "`jeton-yenile` workflow'u elle çalıştırılabilir."),
        "eylem": "yok",
    },
]


def _sadelestir(metin: str) -> str:
    return re.sub(r"\s+", " ", (metin or "")).strip()


def tani(hata) -> dict:
    """
    Ham hatayı katalogla eşleştirir.

    Eşleşme yoksa `tanindi=False` dönüyor ve ham metin olduğu gibi
    aktarılıyor — uydurma bir açıklama vermek, açıklama vermemekten
    daha zararlı.
    """
    ham = _sadelestir(str(hata))
    for kayit in KATALOG:
        if re.search(kayit["desen"], ham, re.IGNORECASE):
            return {**kayit, "tanindi": True, "ham": ham}
    return {
        "ne_oldu": "Beklenmeyen bir hata oluştu.",
        "neden": "Bu hata kataloğa kayıtlı değil.",
        "ne_yapilir": ("Ham hata metni aşağıda. Tekrarlıyorsa "
                       "`src/hata_bildir.py` içindeki katalog genişletilmeli."),
        # ⚠️ Bilinmeyen hatada da eylem sunuluyor. Önce "yok"tu ve
        # kullanıcı yalnızca "ham hata metni" düğmesini görüyordu —
        # yani hiçbir şey yapamıyordu. Turu yeniden denemek çoğu geçici
        # arızayı zaten çözüyor.
        "eylem": "tur_tekrar",
        "tanindi": False,
        "ham": ham,
    }


def _butonlar(eylem: str) -> list | None:
    """Hataya uygun eylem düğmeleri."""
    satir = []
    if eylem == "tur_tekrar":
        satir.append({"text": "🔄 Turu yeniden hazırla",
                      "callback_data": "hata:tur_tekrar"})
    elif eylem == "tur_metinsiz":
        satir.append({"text": "🧯 Metinsiz tur kur",
                      "callback_data": "hata:tur_metinsiz"})
        satir.append({"text": "🔄 Normal dene",
                      "callback_data": "hata:tur_tekrar"})
    # Ayrıntı düğmesi her hatada var: ham metni görmek isteyebilir.
    ikinci = [{"text": "🔍 Ham hata metni", "callback_data": "hata:ayrinti"}]
    # mesaj_gonder inline_keyboard'ın İÇERİĞİNİ bekliyor (satır listesi),
    # sarmalanmış sözlüğü değil.
    return [s for s in (satir, ikinci) if s] or None


def mesaji_kur(baslik: str, teshis: dict, nerede: str = "") -> str:
    """Telegram mesaj metni. Markdown YOK — hata metinleri onu bozuyor."""
    p = [f"⚠️ {baslik}"]
    if nerede:
        p.append(f"Nerede: {nerede}")
    p.append("")
    p.append(f"NE OLDU\n{teshis['ne_oldu']}")
    p.append("")
    p.append(f"NEDEN\n{teshis['neden']}")
    p.append("")
    p.append(f"NE YAPILIR\n{teshis['ne_yapilir']}")
    if not teshis["tanindi"]:
        p.append("")
        p.append(f"HAM HATA\n{teshis['ham'][:600]}")
    return "\n".join(p)


def bildir(baslik: str, hata, nerede: str = "") -> bool:
    """
    Hatayı teşhis edip Telegram'a yazar. ASLA kendisi patlamaz —
    hata bildirimi patlarsa asıl hatanın üstünü örter.
    """
    try:
        teshis = tani(hata)
        metin = mesaji_kur(baslik, teshis, nerede)
        telegram_bot.mesaj_gonder(
            metin, butonlar=_butonlar(teshis["eylem"]))
        log.info("hata Telegram'a bildirildi: %s", teshis["ne_oldu"])
        return True
    except Exception as e:                       # noqa: BLE001
        log.warning("hata bildirimi gönderilemedi: %s", e)
        return False


def son_ham_hata_kaydet(metin: str) -> None:
    """
    Ham hata metnini dosyaya yazar; "🔍 Ham hata metni" düğmesi bunu
    okuyor. Telegram mesajında hep göstermek gürültü yaratıyordu.
    """
    try:
        yol = os.path.join("data", "son_hata.txt")
        os.makedirs("data", exist_ok=True)
        with open(yol, "w", encoding="utf-8") as f:
            f.write(_sadelestir(metin)[:3000])
    except Exception as e:                       # noqa: BLE001
        log.warning("ham hata kaydedilemedi: %s", e)
