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

from contextlib import closing
import logging
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile

log = logging.getLogger(__name__)

DAL = "main"

# Veritabanının depodaki yolu (git komutları ve SQLite aynı dosyaya bakıyor).
DB_GIT_YOLU = "data/haber.db"

# Push reddedilince (araya başka iş girince) birleştir-gönder kaç kez denensin.
AZAMI_BIRLESTIRME = 4


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


def _ortak_kolonlar(con: sqlite3.Connection, tablo: str) -> str:
    """
    Yerel ve uzak tablonun ORTAK kolonları, yereldeki sırayla.

    `SELECT *` iki tarafın kolon sırası/sayısı birebir aynıysa çalışıyor; bir
    job yeni kolonla (db.EK_KOLONLAR) çalışırken öbürü eski şemayla push etmişse
    birleştirme patlıyordu. Ortak kolonlarla kopyalamak iki durumda da çalışıyor.
    """
    yerel = [r[1] for r in con.execute(f"PRAGMA main.table_info({tablo})")]
    uzak = {r[1] for r in con.execute(f"PRAGMA remote_db.table_info({tablo})")}
    return ", ".join(f'"{k}"' for k in yerel if k in uzak)


def _sqlite_db_birlestir(yerel_db_yolu: str | Path, uzak_db_yolu: str | Path,
                         taban_db_yolu: str | Path | None = None) -> bool:
    """
    Uzaktaki veritabanını SQLite üzerinden YERELİN İÇİNE alır.

    Uzakta onaylanan/yayınlanan veya yeni eklenen haberler korunur,
    yerelde üretilen taze haber/slayt verileri ezilmez.

    ⚠️ Dosyayı yalnızca SQLite değiştiriyor — açık bağlantılar (çağıranın `con`'u)
    tutarlı kalıyor. Eskiden çakışmada git dosyayı diskte yeniden yaratıyordu.

    Ayarlar ÜÇ YÖNLÜ birleşiyor (`taban` = iki işin ortak başlangıcı): bizim
    değiştirmediğimiz anahtar uzaktakini alıyor, bizim değiştirdiğimiz bizde
    kalıyor. Eskiden uzak her zaman kazanıyordu ve bu işte yapılan bir ayar
    değişikliği (ör. uygulamadan/Telegram'dan /ayar) sessizce kayboluyordu.

    Başarısızsa False — o zaman PUSH EDİLMEMELİ: birleşmemiş yerel sürümü
    göndermek araya giren işin değişikliklerini (ör. "yayınlandı") silerdi.
    """
    try:
        with closing(sqlite3.connect(yerel_db_yolu, timeout=30)) as con:
            con.execute("PRAGMA busy_timeout = 30000")
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            con.execute("ATTACH DATABASE ? AS remote_db", (str(uzak_db_yolu),))
            kol = _ortak_kolonlar(con, "haberler")
            # 1. Uzakta olup yerelde hiç olmayan haberleri ekle
            con.execute(f'''
                INSERT OR IGNORE INTO haberler ({kol})
                SELECT {kol} FROM remote_db.haberler
                WHERE id NOT IN (SELECT id FROM haberler)
            ''')
            # 2. Uzakta onay bekleyen, yayınlanan veya işlem gören haberler yereldeki işlenmemiş ('yeni', 'metin_hazir') halini tamamen ezer
            con.execute('''
                DELETE FROM haberler
                WHERE id IN (
                    SELECT id FROM remote_db.haberler
                    WHERE durum IN ('onay_bekliyor', 'yayinlandi', 'ertelendi', 'reddedildi', 'cop')
                ) AND durum IN ('yeni', 'metin_hazir')
            ''')
            con.execute(f'''
                INSERT OR IGNORE INTO haberler ({kol})
                SELECT {kol} FROM remote_db.haberler
                WHERE id NOT IN (SELECT id FROM haberler)
            ''')
            # 3. Uzakta 'yayinlandi' durumuna geçmişse yerelde de yayınlandı yap ve post ID'lerini güncelle
            con.execute('''
                UPDATE haberler
                SET durum = r.durum,
                    ig_post_id = COALESCE(r.ig_post_id, haberler.ig_post_id),
                    threads_post_id = COALESCE(r.threads_post_id, haberler.threads_post_id),
                    facebook_post_id = COALESCE(r.facebook_post_id, haberler.facebook_post_id),
                    twitter_post_id = COALESCE(r.twitter_post_id, haberler.twitter_post_id),
                    youtube_post_id = COALESCE(r.youtube_post_id, haberler.youtube_post_id),
                    tiktok_post_id = COALESCE(r.tiktok_post_id, haberler.tiktok_post_id),
                    gonderim_zamani = COALESCE(r.gonderim_zamani, haberler.gonderim_zamani)
                FROM remote_db.haberler AS r
                WHERE haberler.id = r.id
                  AND r.durum = 'yayinlandi'
                  AND haberler.durum != 'yayinlandi'
            ''')
            # 4. Yerelde eksik kalan alanları (ig_caption, son_dakika vb.) uzaktan doldur
            con.execute('''
                UPDATE haberler
                SET ig_caption = COALESCE(haberler.ig_caption, r.ig_caption),
                    son_dakika = MAX(COALESCE(haberler.son_dakika, 0), COALESCE(r.son_dakika, 0)),
                    slayt_ozet = COALESCE(haberler.slayt_ozet, r.slayt_ozet),
                    ig_hashtag = COALESCE(haberler.ig_hashtag, r.ig_hashtag),
                    sana_etkisi = COALESCE(haberler.sana_etkisi, r.sana_etkisi),
                    neden_onemli = COALESCE(haberler.neden_onemli, r.neden_onemli),
                    gorsel_url = COALESCE(haberler.gorsel_url, r.gorsel_url),
                    story_url = COALESCE(haberler.story_url, r.story_url),
                    detay_url = COALESCE(haberler.detay_url, r.detay_url),
                    detay_metni = COALESCE(haberler.detay_metni, r.detay_metni)
                FROM remote_db.haberler AS r
                WHERE haberler.id = r.id
            ''')
            # 5. Ayarları birleştir
            if taban_db_yolu:
                con.execute("ATTACH DATABASE ? AS taban_db", (str(taban_db_yolu),))
                # Bizdeki değer tabandakiyle aynıysa (bu iş o anahtarı değiştirmediyse)
                # uzaktakini al; değiştirdiysek bizimki kalsın. İki tarafta da olmayan
                # yeni anahtar (NULL IS NULL) uzaktan gelir.
                con.execute('''
                    INSERT OR REPLACE INTO ayarlar (anahtar, deger)
                    SELECT r.anahtar, r.deger FROM remote_db.ayarlar r
                    LEFT JOIN main.ayarlar l ON l.anahtar = r.anahtar
                    LEFT JOIN taban_db.ayarlar t ON t.anahtar = r.anahtar
                    WHERE l.deger IS t.deger
                ''')
            else:
                # Ortak başlangıç bilinmiyorsa eski kural: uzak kazanır.
                con.execute('INSERT OR REPLACE INTO ayarlar (anahtar, deger) '
                            'SELECT anahtar, deger FROM remote_db.ayarlar')
            con.commit()
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        log.info("db_senkron: yerel ve uzak veritabanları birleştirildi (SQLite, dosyaya git dokunmadı)")
        return True
    except Exception as e:                                  # noqa: BLE001
        log.warning("db_senkron: SQLite birleştirme hatası: %s", e)
        return False


def _git(*komut: str, ortam: dict | None = None, saniye: int = 60) -> tuple[bool, str]:
    """git komutu; başarı + STDOUT (tak/ağaç kimliği okumak için). Ortam: geçici index."""
    try:
        s = subprocess.run(["git", *komut], capture_output=True, text=True, timeout=saniye,
                           env={**os.environ, **ortam} if ortam else None)
        return s.returncode == 0, s.stdout.strip() if s.returncode == 0 else s.stderr.strip()
    except Exception as e:                                  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def _surumu_yaz(kaynak: str, hedef: Path) -> bool:
    """Depodaki bir sürümün veritabanını (ör. origin/main) GEÇİCİ dosyaya yazar."""
    try:
        s = subprocess.run(["git", "show", f"{kaynak}:{DB_GIT_YOLU}"], capture_output=True, timeout=90)
    except Exception:                                       # noqa: BLE001
        return False
    if s.returncode != 0 or not s.stdout.startswith(b"SQLite format 3\x00"):
        return False
    hedef.write_bytes(s.stdout)
    return True


def _commit_kur(mesaj: str, yollar: list[str], uzak_tak: str, index_yolu: Path) -> str | None:
    """
    Uzak dalın üstüne, ÇALIŞMA KLASÖRÜNE DOKUNMADAN commit kurar (geçici index).

    `git add --ignore-removal`: başka bir işin eklediği dosya bizde yoksa (ör. yeni
    indirilmiş bayrak) commit onu SİLMESİN; yalnızca bizim eklediğimiz/değiştirdiğimiz
    dosyalar uzak ağacın üstüne yazılıyor.
    """
    ortam = {"GIT_INDEX_FILE": str(index_yolu)}
    mevcut = [y for y in yollar if Path(y).exists()]
    ok, cikti = _git("read-tree", uzak_tak, ortam=ortam)
    if ok:
        ok, cikti = _git("add", "--ignore-removal", "--", *mevcut, ortam=ortam)
    if ok:
        ok, agac = _git("write-tree", ortam=ortam)
        cikti = agac
    if ok:
        ok, cikti = _git("commit-tree", agac, "-p", uzak_tak, "-m", mesaj)
    if not ok:
        log.warning("db_senkron: commit kurulamadı: %s", cikti[:200])
        return None
    return cikti


def _yereli_tasi(tak: str) -> None:
    """
    Yerel dalı gönderilen commit'e taşır — veritabanı dosyasına DOKUNMADAN.

    `reset --mixed` yalnızca HEAD'i ve index'i değiştirir. Başka işlerin değiştirdiği
    küçük dosyalar (bayraklar, rapor dosyaları) çalışma klasöründe güncellenir; bu işin
    henüz commit etmediği değişiklikler (sonraki adımlar `--ek` ile ekleyecek) korunur.
    """
    ok, eski = _git("rev-parse", "HEAD")
    yerel_degisen: set[str] = set()
    if ok:
        ok2, cikti = _git("diff", "--name-only", "-z", eski)
        if ok2:
            yerel_degisen = {p for p in cikti.split("\0") if p}
    _git("reset", "-q", "--mixed", tak)
    ok, cikti = _git("diff", "--name-only", "-z")
    if not ok:
        return
    yenile = [p for p in cikti.split("\0")
              if p and not p.startswith(DB_GIT_YOLU) and p not in yerel_degisen]
    for i in range(0, len(yenile), 100):
        _git("checkout", tak, "--", *yenile[i:i + 100])


def _birlestir_ve_gonder(mesaj: str, yollar: list[str]) -> bool:
    """
    Push reddedildi (araya başka iş girdi): uzaktakini İÇERİ AL, uzak dalın üstüne gönder.

    ⚠️ ESKİ YOL `git stash` + `git rebase` + `git checkout --ours/--theirs` idi ve
    veritabanı dosyasını diskte YENİDEN YARATIYORDU — `son_dakika.main`'in bağlantısı
    açıkken. Açık bağlantı silinmiş dosyaya bakıyor, yazdıkları yeni dosyanın `-wal`'ına
    düşüyordu (yol aynı, .gitignore'da, stash'e girmiyor); iki veritabanının sayfaları
    karışıyordu. 4-7 Eki 2026: 14 "Hazırla" işi `file is not a database` ile düştü,
    çoklu seçimde kalan haberler hazırlanmadı; denemede araya giren işin "yayınlandı"
    işareti yerelde geri alındı. (Daha önce de 1d/1f: yarım kalan rebase repoyu kilitliyordu.)

    YENİ YOL: dosyayı yalnızca SQLite değiştiriyor (uzak sürüm geçici dosyadan ATTACH ile
    içeri alınıyor), commit geçici index'le uzak dalın üstüne kuruluyor, çalışma
    klasörüne ve veritabanına git hiç yazmıyor. Yarım rebase, detached HEAD, stash yok.
    `test_7_sozlesme.test_db_kaydi_canli_dosyaya_dokunmaz` dosyanın inode'unu ölçüyor.
    """
    with tempfile.TemporaryDirectory(prefix="db-birlestir-") as klasor:
        k = Path(klasor)
        taban: Path | None = k / "taban.db"
        ok, _ = _git("fetch", "origin", DAL, saniye=90)
        ok, ortak = _git("merge-base", "HEAD", f"origin/{DAL}")
        if not (ok and _surumu_yaz(ortak, taban)):
            taban = None        # sığ klonda ortak başlangıç bulunamazsa: ayarlarda uzak kazanır
        for deneme in range(1, AZAMI_BIRLESTIRME + 1):
            if deneme > 1:
                _git("fetch", "origin", DAL, saniye=90)
            ok, uzak_tak = _git("rev-parse", f"origin/{DAL}")
            uzak = k / f"uzak-{deneme}.db"
            if not (ok and _surumu_yaz(uzak_tak, uzak)):
                log.warning("db_senkron: uzaktaki veritabanı okunamadı, push yapılmadı")
                return False
            if not _sqlite_db_birlestir(DB_GIT_YOLU, uzak, taban):
                log.warning("db_senkron: birleştirilemedi — uzaktakini ezmemek için push YAPILMADI")
                return False
            _wal_bosalt()
            if not veritabani_saglam_mi(DB_GIT_YOLU):
                log.critical("db_senkron: birleştirme sonrası veritabanı sağlam değil, push engellendi")
                return False
            tak = _commit_kur(mesaj, yollar, uzak_tak, k / f"index-{deneme}")
            if not tak:
                return False
            ok, cikti = _git("push", "origin", f"{tak}:refs/heads/{DAL}", saniye=120)
            if ok:
                _yereli_tasi(tak)
                return True
            log.warning("db_senkron: push yine reddedildi (%s/%s): %s", deneme, AZAMI_BIRLESTIRME, cikti[:160])
            # Bir sonraki turda "ortak başlangıç" az önce içeri aldığımız uzak sürüm.
            taban = uzak
    return False


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

    Kayıttan sonra OzBorn Studio uygulamasına güncel özet bırakılıyor
    (`uygulama_koprusu`). Veritabanını değiştiren her akış buradan geçtiği
    için uygulama tek kancayla hepsini görüyor.
    """
    tamam = _kaydet(mesaj, ek_yollar)
    _uygulamaya_bildir()
    return tamam


def _uygulamaya_bildir() -> None:
    """
    Uygulama köprüsü İKİNCİL kanal: patlarsa yalnızca loglanır.

    ⚠️ İçe aktarma da korumanın İÇİNDE. Modülde bir sözdizimi hatası
    olsa bile veritabanı kaydı (yukarıda, ondan ÖNCE) çoktan yapılmış
    olur ve job düşmez.
    """
    try:
        from . import uygulama_koprusu
        uygulama_koprusu.ozet_gonder()
    except Exception:                                       # noqa: BLE001
        log.warning("db_senkron: uygulama köprüsü çağrılamadı", exc_info=True)


def _kaydet(mesaj: str, ek_yollar: list[str] | None = None) -> bool:
    """`hemen_kaydet`'in asıl işi: sağlamlık denetimi, commit, push, çakışma çözümü."""
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
        # Başka bir job araya girmiş olabilir — uzaktakini içeri alıp tekrar itiyoruz.
        log.info("db_senkron: push reddedildi, uzaktaki sürümle birleştiriliyor: %s", cikti[:120])
        tamam = _birlestir_ve_gonder(mesaj, yollar)

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
    olabilir.

    ⚠️ Eskiden `git stash` + `git checkout origin/main -- data/haber.db` yapıyordu:
    çağıranın bağlantısı AÇIKKEN dosya diskte yeniden yaratılıyor, açık bağlantı eski
    veriyi görmeye devam ediyordu (bkz. `_birlestir_ve_gonder`). Artık uzak sürüm
    SQLite'ın yedekleme API'siyle dosyanın İÇİNE kopyalanıyor: dosya aynı, açık
    bağlantı dahil herkes yeni veriyi görüyor. Davranış aynı: yerel sürüm uzaktakiyle
    DEĞİŞTİRİLİYOR (job yeni başlamış, korunacak yerel değişiklik yok).
    """
    tamam, cikti = _git("fetch", "origin", DAL, saniye=90)
    if not tamam:
        log.warning("db_senkron: fetch başarısız: %s", cikti[:200])
        return False
    with tempfile.TemporaryDirectory(prefix="db-tazele-") as klasor:
        uzak = Path(klasor) / "uzak.db"
        if not _surumu_yaz(f"origin/{DAL}", uzak):
            log.warning("db_senkron: uzaktaki veritabanı okunamadı")
            return False
        try:
            with closing(sqlite3.connect(uzak)) as kaynak, \
                    closing(sqlite3.connect(DB_GIT_YOLU, timeout=30)) as hedef:
                hedef.execute("PRAGMA busy_timeout = 30000")
                kaynak.backup(hedef)
        except Exception as e:                              # noqa: BLE001
            log.warning("db_senkron: uzaktaki veritabanı kopyalanamadı: %s", e)
            return False
    _wal_bosalt()
    return veritabani_saglam_mi(DB_GIT_YOLU)
