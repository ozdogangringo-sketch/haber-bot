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
import subprocess

log = logging.getLogger(__name__)

DAL = "main"

# Çakışmada BİZİM sürümümüzün kazanacağı dosyalar. İkili dosyalar
# birleştirilemiyor; birini seçmek zorundayız.
BIZIM_KAZANIR = ("data/haber.db",)


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


def _birlestir() -> None:
    """
    Uzaktaki değişikliği üstümüze alır, çakışmayı kendisi çözer.

    ⚠️ `git pull --rebase` TEK BAŞINA KULLANILMAMALI. `data/haber.db`
    ikili bir dosya; iki job aynı anda yazdığında rebase çakışıyor ve
    YARIM KALIYOR — repo detached HEAD'de kilitleniyor, sonraki her
    git komutu patlıyor. Akşam turunu bu düşürdü.

    Burada çakışma sessizce çözülüyor: ikili dosyada birleştirme diye
    bir şey yok, birini seçmek zorundayız ve elimizdeki taze tur daha
    değerli. Kaybedilen, o arada başka bir job'ın yazdığı satırlar —
    çakışmayı asıl önleyen şey workflow'lardaki ortak `concurrency`
    grubu, burası son emniyet supabı.
    """
    _calistir("git", "fetch", "origin", DAL, saniye=90)

    tamam, _ = _calistir("git", "rebase", f"origin/{DAL}")
    if tamam:
        return

    # Rebase sırasında "theirs" = yeniden uygulanan commit, yani BİZİM
    # değişikliğimiz. Sezgiye ters ama doğrusu bu.
    for dosya in BIZIM_KAZANIR:
        _calistir("git", "checkout", "--theirs", "--", dosya)
        _calistir("git", "add", dosya)

    tamam, cikti = _calistir("git", "-c", "core.editor=true", "rebase", "--continue")
    if not tamam:
        # Çözemediysek yarım rebase'i temizle. Detached HEAD'de kalmak
        # push'u da, sonraki job'ları da bozuyor.
        log.warning("db_senkron: rebase çözülemedi, iptal ediliyor: %s", cikti[:200])
        _calistir("git", "rebase", "--abort")


def hemen_kaydet(mesaj: str, ek_yollar: list[str] | None = None) -> bool:
    """
    data/haber.db'yi commit edip push eder.

    Yerelde de çalışır ama asıl yeri GitHub Actions. Başarısız olursa
    False dönüyor ve LOGA yazıyor — turu düşürmüyoruz, workflow'un
    sonundaki commit adımı yedek olarak duruyor.
    """
    # Actions'ta kimlik ayarlı olmayabilir; her seferinde yazmak zararsız.
    _calistir("git", "config", "user.name", "haber-bot")
    _calistir("git", "config", "user.email", "bot@users.noreply.github.com")

    yollar = ["data/haber.db"] + list(ek_yollar or [])
    tamam, _ = _calistir("git", "add", *yollar)
    if not tamam:
        log.warning("db_senkron: git add başarısız")
        return False

    # Değişiklik yoksa commit hata veriyor; bu bir sorun değil.
    tamam, cikti = _calistir("git", "commit", "-m", mesaj)
    if not tamam and "nothing to commit" not in cikti:
        log.warning("db_senkron: commit başarısız: %s", cikti[:200])
        return False

    tamam, cikti = _push()
    if not tamam:
        # Başka bir job araya girmiş olabilir — üstüne alıp tekrar itiyoruz.
        _birlestir()
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
