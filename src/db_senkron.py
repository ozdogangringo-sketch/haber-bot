"""
db_senkron.py — Veritabanını Telegram mesajından hemen sonra kaydeder.

ÇÖZDÜĞÜ SORUN — YARIŞ DURUMU (17 Ağu 2026'da yaşandı):

    Onay butonu GitHub'daki veritabanına bakıyor. Turu hazırlayan job
    ise veritabanını iş bitiminde, workflow'un son adımında commit
    ediyor. Arada birkaç saniye ile birkaç dakika var.

    Kullanıcı o aralıkta onaylarsa yayın job'ı turu göremiyor:
        "⚠️ Bu onay mesajına bağlı haber bulunamadı"

    Gerçek olay: mesaj 16:53'te gitti, 16:54'te onaylandı, hazırlama
    job'ının commit'i henüz push edilmemişti.

ÇÖZÜM:
    Telegram'a mesaj gönderildiği anda veritabanını commit+push et.
    Workflow sonundaki adım yine duruyor (bu çağrı patlarsa yedek).

NEDEN PYTHON İÇİNDEN:
    Mesaj gönderme ile kaydetme arasındaki boşluğu kapatmanın tek yolu
    ikisini aynı yerde yapmak. Workflow adımı ne kadar erken olursa
    olsun script bitmeden çalışamıyor.
"""

from __future__ import annotations

import logging
from pathlib import Path
import sqlite3
import subprocess

log = logging.getLogger(__name__)

DAL = "main"

# Çakışmada BİZİM sürümümüzün kazanacağı dosyalar. İkili dosyalar
# birleştirilemiyor; birini seçmek zorundayız.
BIZIM_KAZANIR = ("data/haber.db",)


def veritabani_saglam_mi(db_yolu: str | Path = "data/haber.db") -> bool:
    """
    Veritabanı dosyasının fiziksel olarak var olduğunu, SQLite formatında olduğunu
    ve bozuk olmadığını doğrular. Bozuk (0 bayt, sıfırlanmış ilk sayfa vb.) bir veritabanının
    git'e commit edilip diğer tüm runner'ları zehirlemesini engeller.
    """
    try:
        yol = Path(db_yolu)
        if not yol.exists() or yol.stat().st_size < 100:
            log.critical("db_senkron: '%s' dosyası mevcut değil veya çok küçük (<100 bayt)!", yol)
            return False
        with open(yol, "rb") as f:
            baslik = f.read(16)
            if baslik != b"SQLite format 3\x00":
                log.critical("db_senkron: '%s' SQLite başlığı geçersiz (ilk 16 bayt bozuk)!", yol)
                return False
        with sqlite3.connect(yol, timeout=10) as con:
            res = con.execute("PRAGMA quick_check").fetchone()
            if not res or res[0] != "ok":
                log.critical("db_senkron: '%s' quick_check başarısız: %s", yol, res)
                return False
        return True
    except Exception as e:
        log.critical("db_senkron: veritabanı kontrol hatası: %s", e)
        return False


def _calistir(*komut: str, saniye: int = 60) -> tuple[bool, str]:
    try:
        s = subprocess.run(komut, capture_output=True, text=True, timeout=saniye)
        return s.returncode == 0, (s.stderr or s.stdout).strip()
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _push() -> tuple[bool, str]:
    """
    Açık refspec ile iter: `HEAD:main`.

    Neden düz `git push` değil: 17 Ağu 2026'da akşam turu `main`
    dalında başladı ama iş bitiminde detached HEAD'deydi ve push
    "You are not currently on a branch" ile düştü. Turun veritabanı
    GitHub'a hiç yazılamadı, onaya basılınca "haber bulunamadı"
    hatası geldi.

    `HEAD:main` detached HEAD'de de çalışıyor — hangi commit'te
    olduğumuzu değil, nereye iteceğimizi söylüyoruz.
    """
    return _calistir("git", "push", "origin", f"HEAD:{DAL}", saniye=120)


def _sqlite_db_birlestir(yerel_db_yolu: str, uzak_db_yolu: str) -> None:
    """
    İki SQLite veritabanındaki haberler ve ayarlar tablolarını birleştirir.
    Uzakta onaylanan/yayınlanan veya yeni eklenen haberler korunur,
    yerelde üretilen taze haber/slayt verileri ezilmez.
    """
    import sqlite3
    try:
        with sqlite3.connect(yerel_db_yolu, timeout=30) as con:
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            con.execute(f'ATTACH "{uzak_db_yolu}" AS remote_db')
            # 1. Uzakta olup yerelde hiç olmayan haberleri ekle
            con.execute('''
                INSERT OR IGNORE INTO haberler 
                SELECT * FROM remote_db.haberler 
                WHERE id NOT IN (SELECT id FROM haberler)
            ''')
            # 2. Uzakta onay bekleyen veya yayınlanan haberleri güncelle (yerel henüz yeni ise)
            con.execute('''
                UPDATE haberler
                SET durum = r.durum,
                    telegram_message_id = r.telegram_message_id,
                    ig_baslik = r.ig_baslik,
                    gonderim_zamani = r.gonderim_zamani,
                    gorsel_url = r.gorsel_url,
                    story_url = r.story_url,
                    detay_url = r.detay_url,
                    detay_metni = r.detay_metni,
                    ig_post_id = r.ig_post_id,
                    threads_post_id = r.threads_post_id,
                    facebook_post_id = r.facebook_post_id,
                    twitter_post_id = r.twitter_post_id,
                    youtube_post_id = r.youtube_post_id,
                    tiktok_post_id = r.tiktok_post_id
                FROM remote_db.haberler AS r
                WHERE haberler.id = r.id
                  AND r.durum != 'yeni'
                  AND haberler.durum = 'yeni'
            ''')
            # 3. Uzakta 'yayinlandi' durumuna geçmişse yerelde de yayınlandı yap
            con.execute('''
                UPDATE haberler
                SET durum = r.durum,
                    ig_post_id = COALESCE(r.ig_post_id, haberler.ig_post_id),
                    threads_post_id = COALESCE(r.threads_post_id, haberler.threads_post_id),
                    facebook_post_id = COALESCE(r.facebook_post_id, haberler.facebook_post_id),
                    twitter_post_id = COALESCE(r.twitter_post_id, haberler.twitter_post_id),
                    youtube_post_id = COALESCE(r.youtube_post_id, haberler.youtube_post_id),
                    tiktok_post_id = COALESCE(r.tiktok_post_id, haberler.tiktok_post_id)
                FROM remote_db.haberler AS r
                WHERE haberler.id = r.id
                  AND r.durum = 'yayinlandi'
            ''')
            # 4. Ayarları birleştir
            try:
                con.execute('INSERT OR REPLACE INTO ayarlar SELECT * FROM remote_db.ayarlar')
            except Exception:
                pass
            con.commit()
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            log.info("db_senkron: yerel ve uzak veritabanları başarıyla birleştirildi")
    except Exception as e:
        log.warning("db_senkron: SQLite birleştirme hatası: %s", e)


def _birlestir() -> None:
    """
    Uzaktaki değişikliği üstümüze alır, çakışmayı kendisi çözer.

    ⚠️ `git pull --rebase` TEK BAŞINA KULLANILMAMALI. `data/haber.db`
    ikili bir dosya; iki job aynı anda yazdığında rebase çakışıyor ve
    YARIM KALIYOR — repo detached HEAD'de kilitleniyor, sonraki her
    git komutu patlıyor. Akşam turunu bu düşürdü.

    Burada çakışma akıllı SQLite birleştirme ile çözülür: uzakta onaylanan/
    yayınlanan haberler ile yerelde üretilen taze haberler tek veritabanında
    harmanlanır.
    """
    _calistir("git", "fetch", "origin", DAL, saniye=90)
    _calistir("git", "stash", "--include-untracked")

    tamam, _ = _calistir("git", "rebase", f"origin/{DAL}")
    if tamam:
        _calistir("git", "stash", "pop")
        return

    # Rebase sırasında çakışma oldu:
    # 1. Uzaktaki (origin/main) haber.db dosyasını geçici konuma alalım
    import os
    import shutil
    uzak_gecici = "data/haber_uzak_temp.db"
    _calistir("git", "checkout", "--ours", "--", "data/haber.db")
    try:
        shutil.copyfile("data/haber.db", uzak_gecici)
    except Exception:
        uzak_gecici = ""

    # 2. Yereldeki commit edilmiş haber.db dosyasını geri yükle
    _calistir("git", "checkout", "--theirs", "--", "data/haber.db")

    # 3. Akıllı SQLite merge çalıştır
    if uzak_gecici and os.path.exists(uzak_gecici):
        _sqlite_db_birlestir("data/haber.db", uzak_gecici)
        try:
            os.remove(uzak_gecici)
        except Exception:
            pass

    # Merge sonrası sağlamlık kontrolü
    if not veritabani_saglam_mi("data/haber.db"):
        log.critical("db_senkron: Merge sonrası 'data/haber.db' bozuldu! Rebase iptal ediliyor.")
        _calistir("git", "rebase", "--abort")
        _calistir("git", "stash", "pop")
        return

    for dosya in BIZIM_KAZANIR:
        if dosya != "data/haber.db":
            _calistir("git", "checkout", "--theirs", "--", dosya)
        _calistir("git", "add", dosya)

    tamam, cikti = _calistir("git", "-c", "core.editor=true", "rebase", "--continue")
    if not tamam:
        # Çözemediysek yarım rebase'i temizle. Detached HEAD'de kalmak
        # push'u da, sonraki job'ları da bozuyor.
        log.warning("db_senkron: rebase çözülemedi, iptal ediliyor: %s", cikti[:200])
        _calistir("git", "rebase", "--abort")
    _calistir("git", "stash", "pop")


def _wal_bosalt() -> None:
    """
    WAL dosyasındaki değişiklikleri ana veritabanına yazar.

    ⚠️ ŞART. 20 Ağu 2026'da `journal_mode=WAL` açıldı ("database is
    locked" hatası için). WAL modunda yazılanlar önce `haber.db-wal`
    dosyasına gidiyor; git'e yalnızca `haber.db` commit ediliyor.
    Checkpoint alınmazsa o turda yazılan HER ŞEY (haberler, üretilen
    metinler, tur kaydı) commit'e girmez ve runner kapanınca kaybolur.
    """
    try:
        from .db import DB_YOLU
        with sqlite3.connect(DB_YOLU, timeout=30) as con:
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception as e:                              # noqa: BLE001
        log.error("WAL boşaltılamadı: %s", e)


# Git'in "commit edilecek bir şey yok" demesinin bütün biçimleri.
# Hepsi normal durum — hata değil.
_DEGISIKLIK_YOK_KALIPLARI = (
    "nothing to commit",
    "nothing added to commit",
    "no changes added to commit",
    "working tree clean",
)


def _degisiklik_yok(cikti: str) -> bool:
    """Commit başarısızlığı 'zaten değişiklik yoktu' anlamına mı geliyor?"""
    metin = (cikti or "").lower()
    return any(k in metin for k in _DEGISIKLIK_YOK_KALIPLARI)


def hemen_kaydet(mesaj: str, ek_yollar: list[str] | None = None) -> bool:
    """
    data/haber.db'yi commit edip push eder.

    Yerelde de çalışır ama asıl yeri GitHub Actions. Başarısız olursa
    False dönüyor ve LOGA yazıyor — turu düşürmüyoruz, workflow'un
    sonundaki commit adımı yedek olarak duruyor.
    """
    # ⚠️ BOZUK VERİTABANINI ASLA COMMIT ETME VE PUSH'LAMA!
    if not veritabani_saglam_mi("data/haber.db"):
        log.critical("db_senkron: 'data/haber.db' sağlamlık denetimini geçemedi! Commit ve push İPTAL EDİLDİ.")
        return False

    # Actions'ta kimlik ayarlı olmayabilir; her seferinde yazmak zararsız.
    _calistir("git", "config", "user.name", "haber-bot")
    _calistir("git", "config", "user.email", "bot@users.noreply.github.com")

    _wal_bosalt()

    if not veritabani_saglam_mi("data/haber.db"):
        log.critical("db_senkron: WAL boşaltma sonrası 'data/haber.db' bozuldu! Commit ve push İPTAL EDİLDİ.")
        return False

    yollar = ["data/haber.db"] + list(ek_yollar or [])
    tamam, _ = _calistir("git", "add", *yollar)
    if not tamam:
        log.warning("db_senkron: git add başarısız")
        return False

    # Değişiklik yoksa commit hata veriyor; bu bir sorun DEĞİL.
    tamam, cikti = _calistir("git", "commit", "-m", mesaj)
    if not tamam:
        if _degisiklik_yok(cikti):
            log.info("db_senkron: değişiklik yok, commit ve push atlandı")
            return True
        log.warning("db_senkron: commit başarısız: %s", cikti[:200])
        return False

    tamam, cikti = _push()
    if not tamam:
        # Başka bir job araya girmiş olabilir — üstüne alıp tekrar itiyoruz.
        _birlestir()
        if not veritabani_saglam_mi("data/haber.db"):
            log.critical("db_senkron: Rebase sonrası veritabanı bozuk! Push engellendi.")
            return False
        tamam, cikti = _push()

    if tamam:
        log.info("db_senkron: veritabanı push edildi")
    else:
        log.warning("db_senkron: push başarısız: %s", cikti[:200])
    return tamam


def uzaktan_tazele() -> bool:
    """
    Uzaktaki en güncel veritabanını çeker.

    Yayın job'ı turu bulamadığında çağrılıyor: turu hazırlayan job
    henüz push etmemiş olabilir ve bu job checkout'u ondan önce yapmış
    olabilir. Yerel değişiklik varsa ezmemek için önce stash'liyoruz.
    """
    _calistir("git", "stash", "push", "--", "data/haber.db")
    tamam, cikti = _calistir("git", "fetch", "origin", "main", saniye=90)
    if not tamam:
        log.warning("db_senkron: fetch başarısız: %s", cikti[:200])
        return False
    tamam, cikti = _calistir("git", "checkout", "origin/main", "--", "data/haber.db")
    if not tamam:
        log.warning("db_senkron: checkout başarısız: %s", cikti[:200])
    return tamam
