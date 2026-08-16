"""
db.py — SQLite işlemleri.

Buradaki her fonksiyon tek bir SQL işi yapıyor.
SQL bildiğin için sorguları olduğu gibi görebilesin diye
ORM kullanmadım, düz SQL yazdım.
"""

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
}


def baglan():
    """Veritabanına bağlan. Dosya yoksa oluşturur."""
    DB_YOLU.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_YOLU)
    con.row_factory = sqlite3.Row       # sonuçlara sütun adıyla erişebilmek için
    con.execute("PRAGMA foreign_keys = ON")
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
               gorsel_konu    = ?,
               gorsel_temsili = ?,
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
            # Gemini boş bırakabiliyor (tanınmış kişi yoksa / ülkesiz haber).
            # Boş string yerine NULL saklamak SQL'de ayırt etmeyi kolaylaştırır.
            (uretilen.get("gorsel_konu") or "").strip() or None,
            (uretilen.get("gorsel_temsili") or "").strip() or None,
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
