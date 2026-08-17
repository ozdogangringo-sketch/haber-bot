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


def _calistir(*komut: str, saniye: int = 60) -> tuple[bool, str]:
    try:
        s = subprocess.run(komut, capture_output=True, text=True, timeout=saniye)
        return s.returncode == 0, (s.stderr or s.stdout).strip()
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def hemen_kaydet(mesaj: str) -> bool:
    """
    data/haber.db'yi commit edip push eder.

    Yerelde de çalışır ama asıl yeri GitHub Actions. Başarısız olursa
    False dönüyor ve LOGA yazıyor — turu düşürmüyoruz, workflow'un
    sonundaki commit adımı yedek olarak duruyor.
    """
    # Actions'ta kimlik ayarlı olmayabilir; her seferinde yazmak zararsız.
    _calistir("git", "config", "user.name", "haber-bot")
    _calistir("git", "config", "user.email", "bot@users.noreply.github.com")

    tamam, _ = _calistir("git", "add", "data/haber.db")
    if not tamam:
        log.warning("db_senkron: git add başarısız")
        return False

    # Değişiklik yoksa commit hata veriyor; bu bir sorun değil.
    tamam, cikti = _calistir("git", "commit", "-m", mesaj)
    if not tamam and "nothing to commit" not in cikti:
        log.warning("db_senkron: commit başarısız: %s", cikti[:200])
        return False

    tamam, cikti = _calistir("git", "push", saniye=120)
    if not tamam:
        # Başka bir job araya girmiş olabilir — bir kez rebase deneyip
        # tekrar itiyoruz.
        _calistir("git", "pull", "--rebase", saniye=120)
        tamam, cikti = _calistir("git", "push", saniye=120)

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
