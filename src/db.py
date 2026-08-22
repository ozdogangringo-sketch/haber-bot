"""
db.py — SQLite işlemleri.

Buradaki her fonksiyon tek bir SQL işi yapıyor.
SQL bildiğin için sorguları olduğu gibi görebilesin diye
ORM kullanmadım, düz SQL yazdım.
"""

import logging
import sqlite3
from pathlib import Path

# Proje kök klasörü (bu dosya src/ içinde, bir üstü kök)
KOK = Path(__file__).resolve().parent.parent
DB_YOLU = KOK / "data" / "haber.db"


SEMA = """
CREATE TABLE IF NOT EXISTS haberler (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,

    -- RSS'ten gelen ham veri
    kaynak         TEXT    NOT NULL,
    kategori       TEXT    NOT NULL,          -- 'turkiye' | 'dunya'
    agirlik        INTEGER NOT NULL DEFAULT 0,
    baslik_orj     TEXT    NOT NULL,
    link           TEXT    NOT NULL UNIQUE,   -- <<< tekrar engelinin anahtarı
    ozet_orj       TEXT,
    yayin_tarihi   TEXT,                      -- ISO 8601, UTC
    cekilme_zamani TEXT    NOT NULL DEFAULT (datetime('now')),

    -- LLM ve görsel adımlarında dolacak (şimdilik boş)
    ig_baslik      TEXT,
    ig_caption     TEXT,
    ig_hashtag     TEXT,
    onem_puani     INTEGER,                   -- Gemini'nin verdiği 1-10 önem puanı
    gorsel_yolu    TEXT,
    gorsel_url     TEXT,

    -- Onay akışı
    tur                 TEXT,                 -- 'sabah' | 'aksam'
    telegram_message_id INTEGER,              -- mesajı sonradan güncellemek için
    gonderim_zamani     TEXT,                 -- Telegram'a gittiği an
    hatirlatma_sayisi   INTEGER NOT NULL DEFAULT 0,
    ertelenme_sayisi    INTEGER NOT NULL DEFAULT 0,

    -- Akış durumu
    durum          TEXT    NOT NULL DEFAULT 'yeni',
    ig_post_id     TEXT,
    hata_mesaji    TEXT
);

CREATE INDEX IF NOT EXISTS idx_durum   ON haberler(durum);
CREATE INDEX IF NOT EXISTS idx_tarih   ON haberler(yayin_tarihi);

-- Basit anahtar/değer tablosu (Telegram offset, son tur bilgisi vs.)
CREATE TABLE IF NOT EXISTS ayarlar (
    anahtar TEXT PRIMARY KEY,
    deger   TEXT
);
"""

# durum akışı:
#   yeni -> metin_hazir -> gorsel_hazir -> onay_bekliyor -> yayinlandi
#                                                        -> atlandi
#                                                        -> ertelendi (akşama kalır)
#   herhangi bir yerde -> hata

# Şema büyüdükçe buraya ekleyeceğimiz kolonlar.
# kur() bunları eksikse ALTER TABLE ile ekler; veritabanını silmene gerek kalmaz.
EK_KOLONLAR = {
    # Kullanılan stok fotoğrafın kaynaktaki id'si (Pexels).
    # Aynı fotoğrafın tekrar tekrar seçilmesini engellemek için
    # saklanıyor — bkz. fetch_stock.fotograf_ara(kullanilmis=...).
    "gorsel_kaynak_id": "TEXT",
    # Bu haber en son ne zaman turdan atlandı? (ISO, UTC)
    #
    # ⚠️ SKOR CEZASI TEK BAŞINA YETMİYOR. 20 Ağu 2026'da ölçüldü:
    # atlanan 10 haberin 5'i bir sonraki turda geri geldi. Sebep havuzun
    # dar olması — 8 puanlık bir haber 15 puan ceza yese bile 6 puanlık
    # taze haberin önünde kalıyor. Kullanıcının "atla" demesi
    # "sıralamada geri at" değil, "şimdi bunu istemiyorum" demek.
    "atlanma_zamani": "TEXT",
    # Bu haber daha önce (tekil post olarak) yayınlandı mı?
    #
    # Muafiyetle tura giren 9+ puanlı haberler için: haber turda KALIYOR
    # ama EN SON sıraya iniyor. Kullanıcı kararı (20 Ağu 2026):
    # "kalsın havuzda ama gündüz yayınlandıysa en son sırada olsun".
    # Gerekçe: takipçi o haberi gün içinde zaten gördü; başa koymak
    # turun ilk izlenimini tekrarla harcıyor.
    "daha_once_yayinlandi": "INTEGER DEFAULT 0",
    # Zamanlanmış yayın: bu tur ne zaman yayınlanacak (ISO 8601, UTC).
    #
    # ⚠️ HASSASİYET ±30 DAKİKA. Zamanı gelen turu son dakika kontrolü
    # yayınlıyor ve o cron 30 dakikada bir çalışıyor. Daha hassas olması
    # için cron sıklaştırılmalı; ölçüldü (20 Ağu 2026): 15 dakikaya
    # çıkarmak Actions kullanımını 594'ten 1122 dk/ay'a taşıyor.
    "planlanan_yayin": "TEXT",
    # "🔀 Başka fotoğraf" düğmesine kaç kez basıldı — Commons/Pexels
    # aday listesinde kaçıncı sıradayız.
    #
    # ⚠️ Bu sayaç olmadan düğme HİÇ İŞE YARAMIYORDU: katmanlar her
    # zaman `adaylar[0]` döndürüyordu, yani kaç kez basılırsa basılsın
    # aynı fotoğraf geliyordu (20 Ağu 2026).
    "gorsel_deneme": "INTEGER DEFAULT 0",
    # Değiştirilen görselin ADAY URL'si — kullanıcı onaylayana kadar
    # `gorsel_url` üzerine yazılmıyor.
    "gorsel_url_aday": "TEXT",
    "gorsel_yolu_aday": "TEXT",
    "gorsel_kaynagi_aday": "TEXT",
    "gorsel_atif_aday": "TEXT",
    # Bu haber TEKİL post olarak bir daha sunulmasın — yalnızca
    # carousel turunda yayınlansın.
    #
    # ⚠️ NEDEN GEREKTİ (20 Ağu 2026): "Türkiye'de yağışlar son 66 yılın
    # zirvesinde" haberi 23 dakika arayla İKİ KEZ tekil post olarak
    # onaya sunuldu. Kullanıcı "atla" dediğinde haber havuza dönüyor
    # (`durum='metin_hazir'`, `son_dakika=0`) ve bir sonraki kontrolde
    # yeniden aday oluyor — kısır döngü. "Onay verilmezse haber
    # ELENMEZ" kararı doğru, ama tekil post olarak ısrar etmek yanlış.
    # Bu işaret haberi turda bırakıyor, tekil adaylıktan çıkarıyor.
    "sadece_tur": "INTEGER DEFAULT 0",
    # Tekil post için BAŞLIK ÖNERİSİ olarak Telegram'a gönderildi mi?
    #
    # ⚠️ Aynı haberi her kontrolde tekrar önermeyi engelliyor. Kontrol
    # 20 dakikada bir çalışıyor; işaret olmadan aynı üç başlık gün boyu
    # tekrar tekrar gelir ve öneri mesajı gürültüye dönerdi.
    "oneri_gonderildi": "INTEGER DEFAULT 0",
    # Threads'e paylaşıldıysa zincirin ana gönderi id'si.
    #
    # ⚠️ MÜKERRER PAYLAŞIMI ÖNLÜYOR. `gecmisi_paylas.py` önce bu kolona
    # bakıyor; doluysa turu atlıyor. Olmadığında script her çalıştırmada
    # baştan başlıyordu ve 18 Ağu 2026'da aynı tur üç kez yayınlandı
    # (biri `--adet 1` denemesinden, ikisi sonraki çalıştırmadan).
    "threads_post_id": "TEXT",
    # Facebook albüm postunun id'si.
    #
    # ⚠️ SİLEBİLMEK İÇİN ŞART. Önce yalnızca loga yazılıyordu; yayınlanan
    # bir postu geri almak gerektiğinde id elde olmadığı için Facebook'a
    # elle girmek gerekiyordu. Instagram'da silme API'den mümkün DEĞİL
    # (Graph API izin vermiyor), ama Facebook ve Threads silinebiliyor.
    "facebook_post_id": "TEXT",
    # Story id'leri: story 24 saatte kendiliğinden düşüyor, yine de
    # yayından kaldırırken birlikte silinebilsin diye tutuluyor.
    "story_post_id": "TEXT",
    "onem_puani": "INTEGER",
    "tur": "TEXT",
    "telegram_message_id": "INTEGER",
    "gonderim_zamani": "TEXT",
    "hatirlatma_sayisi": "INTEGER NOT NULL DEFAULT 0",
    "ertelenme_sayisi": "INTEGER NOT NULL DEFAULT 0",
    # Haberin sitesinden çekilen tam gövde metni (Adım 2).
    # İki işe yarıyor:
    #   1) Gemini'ye RSS teaser'ı yerine bunu veriyoruz — ölçtük, teaser'la
    #      model bilgi boşluğunu uyduruyor.
    #   2) Onay aşamasında kaynak metni görebilesin diye saklıyoruz:
    #      "modelin yazdığı bu cümle haberde gerçekten var mı?"
    "makale_metni": "TEXT",
    # --- Adım 3: slayt görselini besleyen alanlar ---
    # Başlığın altına basılan tek cümlelik özet
    "slayt_ozet": "TEXT",
    # Commons araması için kişi/kurum adı (tanınmış biri yoksa boş)
    "gorsel_konu": "TEXT",
    # Pexels araması için İngilizce temsili terim
    "gorsel_temsili": "TEXT",
    # Sağ üstteki bayrak: ISO 3166-1 alpha-2 kodu + Türkçe ülke adı
    "ulke_kodu": "TEXT",
    "ulke_adi": "TEXT",
    # Görselin hangi katmandan geldiği: commons / pexels / gradyan / ai.
    # Onay mesajında göstermek ve sonradan "hangi katman ne sıklıkta
    # tutuyor" diye ölçebilmek için tutuluyor.
    "gorsel_kaynagi": "TEXT",
    # Fotoğrafın atıf metni ("Foto: X / Y / CC BY 4.0").
    # DB'de duruyor çünkü caption yayın ANINDA yeniden kuruluyor: hazırlık
    # ile onay arasında saatler geçebiliyor ve o sırada süreç ölüyor.
    # Bellekte tutulsaydı Commons'ın CC BY atfı yayında kaybolurdu — bu
    # lisans ihlali olurdu.
    "gorsel_atif": "TEXT",
    # Bu haber "son dakika" olarak mı sunuldu? Akşam turundan ayırmak
    # için: son dakika turunun 1 saatlik ömrü var, akşam turunun yok.
    "son_dakika": "INTEGER DEFAULT 0",
    # Bu tur/post hangi kanallarda yayınlanacak? ("ig,story,threads,facebook")
    # Kullanıcı onay aşamasında butonlarla seçiyor; zamanlanmış yayınlar
    # ve yeniden yayınlama bu tercihi hatırlasın diye saklanıyor.
    "yayin_kanallari": "TEXT",
    # Turun story görselinin imgbb adresi. Turun İLK haberine yazılıyor;
    # story tur başına tek olduğu için her satıra kopyalamaya gerek yok.
    "story_url": "TEXT",
    # Son dakika postunun İKİNCİ slaytı (detay sayfası).
    # Ayrı kolon şart: `gorsel_url` tek adres tutuyor ve son dakika
    # turu 2 slayt üretiyor. Bu kolon olmadan ikinci slayt yayın
    # anında kayboluyor ve Instagram "carousel en az 2 görsel ister"
    # diye reddediyor — 17 Ağu 2026 sabahı tam olarak bu oldu.
    "detay_url": "TEXT",
    # Son dakika slaytlarındaki uzun anlatım (ig_caption'dan AYRI).
    # ig_caption Instagram açıklaması için 2-3 cümle; bu ise slaytlara
    # yayılan 120-220 kelimelik metin. Sayfa başına ~75 kelime sığıyor,
    # yani 2-3 slayt ediyor.
    "detay_metni": "TEXT",
    # --- Vurgu öğeleri (opsiyonel, yoksa NULL) ---
    # Detay sayfalarında iri rakam ve alıntı bloğu olarak basılıyor.
    # Alıntı kaynakta birebir doğrulanıyor (dogrula.alintiyi_denetle);
    # doğrulanamazsa kullanılmıyor — uydurma alıntı en ağır hata.
    "vurgu_sayi": "TEXT",
    "vurgu_etiket": "TEXT",
    "alinti": "TEXT",
    "alinti_sahibi": "TEXT",
}


log = logging.getLogger(__name__)

def baglan():
    """
    Veritabanına bağlan. Dosya yoksa oluşturur.

    ⚠️ "database is locked" HATASININ ÇÖZÜMÜ BURADA (20 Ağu 2026).
    Öneri listesinden iki haber seçildiğinde ilki üretiliyor, ikincisi
    bu hatayla düşüyordu. Sebep: `onay_isle` kendi bağlantısını açık
    tutarken `son_dakika`yı çağırıyor, o da AYRI bir bağlantı açıp
    yazmaya çalışıyor.

    Varsayılan `journal_mode=delete`'te tek yazar bütün veritabanını
    kilitliyor. WAL modunda okuyucular yazarı engellemiyor ve iki
    bağlantı yan yana çalışabiliyor. `busy_timeout` da 5 sn'den 30
    sn'ye çıkarıldı: görsel üretimi ve imgbb yüklemesi sırasında
    yazma birkaç saniye bekleyebiliyor, 5 saniye dar kalıyordu.
    """
    DB_YOLU.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_YOLU, timeout=30)
    con.row_factory = sqlite3.Row       # sonuçlara sütun adıyla erişebilmek için
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA busy_timeout = 30000")
    return con


def kur():
    """
    Tabloları yoksa yaratır, varsa eksik kolonları ekler.
    Her çalıştırmada güvenle çağrılabilir — mevcut veriye dokunmaz.
    """
    with baglan() as con:
        con.executescript(SEMA)

        # --- otomatik migration ---
        mevcut = {s["name"] for s in con.execute("PRAGMA table_info(haberler)")}
        for kolon, tanim in EK_KOLONLAR.items():
            if kolon not in mevcut:
                con.execute(f"ALTER TABLE haberler ADD COLUMN {kolon} {tanim}")
        con.commit()


def ayar_oku(con, anahtar: str, varsayilan=None):
    satir = con.execute(
        "SELECT deger FROM ayarlar WHERE anahtar = ?", (anahtar,)
    ).fetchone()
    return satir["deger"] if satir else varsayilan


def ayar_yaz(con, anahtar: str, deger):
    con.execute(
        "INSERT INTO ayarlar (anahtar, deger) VALUES (?, ?) "
        "ON CONFLICT(anahtar) DO UPDATE SET deger = excluded.deger",
        (anahtar, str(deger)),
    )


def haber_ekle(con, haber: dict) -> bool:
    """
    Tek bir haberi ekler.
    Aynı link daha önce eklendiyse SQLite sessizce yok sayar (INSERT OR IGNORE).
    Gerçekten eklendiyse True, tekrar olduğu için atlandıysa False döner.
    """
    imlec = con.execute(
        """
        INSERT OR IGNORE INTO haberler
            (kaynak, kategori, agirlik, baslik_orj, link, ozet_orj, yayin_tarihi)
        VALUES
            (:kaynak, :kategori, :agirlik, :baslik_orj, :link, :ozet_orj, :yayin_tarihi)
        """,
        haber,
    )
    return imlec.rowcount > 0


def durum_guncelle(con, haber_id: int, durum: str, hata: str | None = None):
    """Bir haberin akıştaki durumunu değiştirir."""
    con.execute(
        "UPDATE haberler SET durum = ?, hata_mesaji = ? WHERE id = ?",
        (durum, hata, haber_id),
    )


def _gecerli_kategori(deger) -> str | None:
    """
    Modelin verdiği kategoriyi doğrular.

    ⚠️ BEYAZ LİSTE ZORUNLU. Listede olmayan bir kategori sessiz hasar
    veriyor: `gorsel.serit_renkleri` onu tanımadığı için slayt
    "turkiye" rengine düşüyor, `secim.kategori_katsayilari` de
    tanımadığı için ön elemede varsayılan katsayı uygulanıyor —
    ikisi de hata vermeden yanlış çalışıyor.

    Şemada `enum` var ama tek savunma o olmamalı: model şemayı
    ihlal edebiliyor ve eski kayıtlar başka yollardan da geliyor.
    """
    from .generate_text import KATEGORILER
    ad = (deger or "").strip().lower()
    return ad if ad in KATEGORILER else None


def metin_kaydet(con, haber_id: int, uretilen: dict, makale_metni: str | None = None):
    """
    Gemini'nin ürettiği Instagram metnini kaydeder ve haberi
    'metin_hazir' durumuna geçirir.

    `uretilen` sözlüğü şunları içermeli:
        ig_baslik, ig_caption, ig_hashtag (liste), onem_puani (int),
        slayt_ozet, gorsel_konu, gorsel_temsili, ulke_kodu, ulke_adi

    Hashtag'i veritabanında boşlukla ayrılmış tek metin olarak tutuyoruz
    ('#' işareti olmadan). Böyle saklamak SQL'de aramayı kolaylaştırıyor;
    '#' işaretini gösterirken ekliyoruz.
    """
    etiketler = uretilen.get("ig_hashtag") or []
    if isinstance(etiketler, str):
        etiketler = etiketler.split()

    con.execute(
        """
        UPDATE haberler
           SET ig_baslik      = ?,
               ig_caption     = ?,
               ig_hashtag     = ?,
               onem_puani     = ?,
               slayt_ozet     = ?,
               detay_metni    = ?,
               vurgu_sayi     = ?,
               vurgu_etiket   = ?,
               alinti         = ?,
               alinti_sahibi  = ?,
               gorsel_konu    = ?,
               gorsel_temsili = ?,
               -- ⚠️ KATEGORİ MODELDEN GELİYORSA ÜZERİNE YAZILIYOR.
               -- `fetch_news` kategoriyi RSS beslemesinden atıyor ve o
               -- çoğu zaman yanlış (CLAUDE.md 1i): AA'nın ekonomi
               -- beslemesinden gelen silah satışı haberi "ekonomi"
               -- görünüyordu. Model haberin tam metnini okuyor.
               -- Model boş/geçersiz döndürürse eski değer korunuyor.
               kategori       = COALESCE(?, kategori),
               ulke_kodu      = ?,
               ulke_adi       = ?,
               makale_metni   = COALESCE(?, makale_metni),
               durum          = 'metin_hazir',
               hata_mesaji    = NULL
         WHERE id = ?
        """,
        (
            uretilen.get("ig_baslik"),
            uretilen.get("ig_caption"),
            " ".join(e.lstrip("#") for e in etiketler),
            uretilen.get("onem_puani"),
            uretilen.get("slayt_ozet"),
            uretilen.get("detay_metni"),
            (uretilen.get("vurgu_sayi") or "").strip() or None,
            (uretilen.get("vurgu_etiket") or "").strip() or None,
            (uretilen.get("alinti") or "").strip() or None,
            (uretilen.get("alinti_sahibi") or "").strip() or None,
            # Gemini boş bırakabiliyor (tanınmış kişi yoksa / ülkesiz haber).
            # Boş string yerine NULL saklamak SQL'de ayırt etmeyi kolaylaştırır.
            (uretilen.get("gorsel_konu") or "").strip() or None,
            (uretilen.get("gorsel_temsili") or "").strip() or None,
            _gecerli_kategori(uretilen.get("kategori")),
            (uretilen.get("ulke_kodu") or "").strip().lower() or None,
            (uretilen.get("ulke_adi") or "").strip() or None,
            makale_metni,
            haber_id,
        ),
    )


def bekleyenler(con, durum: str = "yeni", limit: int = 10):
    """
    Belirli durumdaki haberleri, önce ağırlığı yüksek ve yeni olanlar
    gelecek şekilde getirir. Bir sonraki adım (Gemini) bunu kullanacak.
    """
    return con.execute(
        """
        SELECT *
        FROM haberler
        WHERE durum = ?
        ORDER BY agirlik DESC, yayin_tarihi DESC
        LIMIT ?
        """,
        (durum, limit),
    ).fetchall()


def ozet_istatistik(con):
    """Hangi durumda kaç haber var — ekrana basmak için."""
    return con.execute(
        "SELECT durum, COUNT(*) AS adet FROM haberler GROUP BY durum ORDER BY adet DESC"
    ).fetchall()


def kaynak_dagilimi(con):
    """Hangi kaynaktan kaç haber geldi."""
    return con.execute(
        "SELECT kaynak, COUNT(*) AS adet FROM haberler GROUP BY kaynak ORDER BY adet DESC"
    ).fetchall()


# VACUUM eşiği: bu kadar kayıt silinmediyse dosyayı yeniden yazmıyoruz.
#
# ⚠️ VACUUM'U HER GÜN ÇALIŞTIRMA. Dosyanın tamamını yeniden düzenliyor;
# `haber.db` her job'da git'e commit edildiği için bu, git'in delta
# sıkıştırmasını işe yaramaz hale getiriyor ve geçmişi tam boyutta bir
# kopya daha büyütüyor. Ancak kayda değer bir küçülme varsa değer.
VACUUM_ESIGI = 100


def eski_kayitlari_temizle(con, gun: int = 7) -> int:
    """
    Yayınlanmamış eski haberleri siler. Silinen kayıt sayısını döner.

    ⚠️ YAYINLANMIŞ HABER ASLA SİLİNMEZ. Mükerrer engeli geçmişe
    bakıyor (`secim.yayinlanmis_konular`) ve o kayıtlar aynı haberin
    tekrar yayınlanmasını önlüyor; silmek 1j/1z'deki mükerrer
    sorununu geri getirir.

    ⚠️ NEDEN GEREKTİ (21 Ağu 2026): hiç temizlik yoktu. 8 günde 3134
    kayıt birikti ve `.git` klasörü **237 MB**'a çıktı — veritabanı her
    job'da commit ediliyor ve ikili dosya olduğu için git onu
    sıkıştıramıyor. Ölçüldü: 30 MB/gün büyüme, 6 ay sonra ~5 GB
    (GitHub'ın yumuşak limiti).

    Silinen haberler zaten kullanılamaz durumda: tazelik sınırı 36
    saat, yani 7 günlük bir kayıt hiçbir akışta aday olamıyor.
    """
    silinen = con.execute(
        "DELETE FROM haberler "
        "WHERE durum != 'yayinlandi' "
        "  AND cekilme_zamani < datetime('now', ?)",
        (f"-{gun} day",),
    ).rowcount
    con.commit()

    if silinen >= VACUUM_ESIGI:
        # ⚠️ VACUUM işlem dışında çalışmalı; açık işlem varsa hata verir.
        con.isolation_level = None
        try:
            con.execute("VACUUM")
        finally:
            con.isolation_level = ""
        log.info("veritabanı sıkıştırıldı (VACUUM)")

    if silinen:
        log.info("%s eski kayıt silindi (%s günden eski, yayınlanmamış)",
                 silinen, gun)
    return silinen
