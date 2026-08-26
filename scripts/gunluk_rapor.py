"""
gunluk_rapor.py — Sabah tek mesajda "dün ne oldu, bugün ne durumdayız".

NEDEN VAR:
    Bot sessiz çalışıyor. Saat başı son dakika kontrolü yapılıyor, çoğu
    zaman "aday yok" deyip geçiyor ve hiçbir iz kalmıyor. Cron atladı mı,
    jeton ölüyor mu, kota doluyor mu — hepsi ancak bir şey patlayınca
    fark ediliyordu.

    Bu rapor arızayı ÖNCEDEN görünür kılıyor: jetonun 5 günü kaldığında
    ya da dün üç job patladığında sabah haberin oluyor.

NE ANLATIYOR:
    * Dün ne yayınlandı (bağlantılarıyla)
    * Havuzda kaç haber var, kaçının metni hazır
    * Instagram yayın kotası, Threads jeton durumu
    * Son 24 saatte başarısız GitHub Actions job'ları
    * Dikkat gerektiren durumlar (bayat tur, kaldırılan post, yarım zincir)

ÇALIŞTIRMA:
    python scripts/gunluk_rapor.py           (Telegram'a gönderir)
    python scripts/gunluk_rapor.py --kuru    (ekrana basar, göndermez)
"""

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import requests                                   # noqa: E402
import yaml                                       # noqa: E402

from src import ayar, db, instagram, telegram_bot, threads   # noqa: E402

log = logging.getLogger("rapor")

VARSAYILAN_REPO = "ozdogangringo-sketch/haber-bot"

# Jeton bu günden aza inince rapor uyarı veriyor. Threads jetonu 60 gün
# ömürlü ve haftalık yenileniyor; 14 gün, üst üste iki yenileme kaçsa
# bile elle müdahaleye vakit bırakıyor.
JETON_UYARI_GUN = 14


def _tr_simdi() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=3)


def dunku_yayinlar(con) -> list[dict]:
    """Son 24 saatte yayınlanan turlar (tur başına tek satır)."""
    sinir = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    satirlar = con.execute("""
        SELECT telegram_message_id AS msg, MIN(gonderim_zamani) AS zaman,
               COUNT(*) AS adet, MIN(son_dakika) AS sd,
               MIN(ig_post_id) AS ig, MIN(threads_post_id) AS th,
               MIN(facebook_post_id) AS fb, MIN(ig_baslik) AS baslik
        FROM haberler
        WHERE durum = 'yayinlandi' AND gonderim_zamani >= ?
        GROUP BY telegram_message_id
        ORDER BY MIN(gonderim_zamani)
    """, (sinir,)).fetchall()
    return [dict(s) for s in satirlar]


def basarisiz_isler(repo: str) -> list[str]:
    """
    Son 24 saatte patlayan GitHub Actions job'ları.

    Jeton yoksa (yerelde çalıştırma) sessizce boş dönüyor — rapor
    bu bilgi olmadan da anlamlı.
    """
    jeton = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not jeton:
        return []
    sinir = (datetime.now(timezone.utc) - timedelta(hours=24))
    try:
        cevap = requests.get(
            f"https://api.github.com/repos/{repo}/actions/runs",
            headers={"Authorization": f"Bearer {jeton}",
                     "Accept": "application/vnd.github+json"},
            params={"status": "failure", "per_page": 20}, timeout=30,
        )
        if cevap.status_code != 200:
            return []
        cikti = []
        for run in cevap.json().get("workflow_runs", []):
            baslangic = datetime.fromisoformat(
                run["created_at"].replace("Z", "+00:00"))
            if baslangic >= sinir:
                cikti.append(f"{run['name']} ({baslangic.hour + 3:02d}:"
                             f"{baslangic.minute:02d})")
        return cikti
    except Exception as e:
        log.warning("Actions durumu okunamadı: %s", e)
        return []


def rapor_kur(con, ayarlar: dict, repo: str) -> str:
    simdi = _tr_simdi()
    satirlar = [f"📊 GÜNLÜK RAPOR — {simdi.strftime('%d.%m.%Y %H:%M')}", ""]

    # --- Ücretli Gemini anahtar kullanımı ---
    try:
        yedek_yolu = os.path.join("data", "yedek_anahtar_kullanimi.txt")
        if os.path.exists(yedek_yolu):
            with open(yedek_yolu, encoding="utf-8") as f:
                yedek_satirlar = f.read().strip().splitlines()
            if yedek_satirlar:
                from collections import Counter
                from datetime import date
                sayac = Counter(yedek_satirlar)
                bugun = date.today().isoformat()
                bugunki = sayac.get(bugun, 0)
                toplam = len(yedek_satirlar)
                satirlar.append(
                    f"💰 ÜCRETLİ ANAHTAR: bugün {bugunki}, toplam {toplam} kez"
                )
                satirlar.append("")
    except Exception:
        pass

    # --- Dünkü yayınlar ---
    from src.zaman import tr_format
    yayinlar = dunku_yayinlar(con)
    if yayinlar:
        satirlar.append(f"📤 SON 24 SAAT — {len(yayinlar)} yayın")
        for y in yayinlar:
            tur = "Son dakika" if y["sd"] else "Akşam turu"
            saat = tr_format(y["zaman"], "saat") if y["zaman"] else ""
            kanal = "".join([
                "📷" if y["ig"] else "",
                "📘" if y["fb"] else "",
                "🧵" if y["th"] else "",
            ])
            satirlar.append(f"· {saat} {tur} ({y['adet']} haber) {kanal}")
            satirlar.append(f"  {(y['baslik'] or '')[:58]}")
    else:
        satirlar.append("📤 SON 24 SAAT — yayın yok")
    satirlar.append("")

    # --- Havuz ---
    sayim = dict(con.execute(
        "SELECT durum, COUNT(*) FROM haberler GROUP BY durum").fetchall())
    satirlar.append(
        f"🗂 HAVUZ — {sayim.get('yeni', 0)} yeni, "
        f"{sayim.get('metin_hazir', 0)} metni hazır, "
        f"{sayim.get('yayinlandi', 0)} yayınlanmış"
    )
    bekleyen = con.execute(
        "SELECT COUNT(DISTINCT telegram_message_id) FROM haberler "
        "WHERE durum IN ('onay_bekliyor','ertelendi')").fetchone()[0]
    if bekleyen:
        satirlar.append(f"⏳ Onay bekleyen tur: {bekleyen}")
    satirlar.append("")

    # --- Sistem ---
    satirlar.append("🔧 SİSTEM")
    try:
        kota = instagram.yayin_kotasi(ayarlar)
        satirlar.append(
            f"· Instagram kota: {kota['kullanilan']}/{kota['azami']}")
    except Exception as e:
        satirlar.append(f"· ⚠️ Instagram kotası okunamadı ({type(e).__name__})")

    if threads.kullanilabilir_mi():
        try:
            satirlar.append(
                f"· Threads: @{threads.hesap_bilgisi().get('username')}")
        except Exception as e:
            satirlar.append(f"· ⚠️ Threads erişilemedi ({type(e).__name__})")
    else:
        satirlar.append("· Threads: anahtar yok")

    hatalar = basarisiz_isler(repo)
    if hatalar:
        satirlar.append(f"· ⚠️ Başarısız iş ({len(hatalar)}): "
                        + ", ".join(hatalar[:4]))
    else:
        satirlar.append("· Başarısız iş yok")
    satirlar.append("")

    # --- Ayarlar varsayılandan farklıysa ---
    # Sessizce kapalı kalmış bir kanal en sinsi arıza türü: bot çalışıyor
    # görünür ama içerik bir yere gitmez.
    degisik = [
        f"{ayar.DEGISTIRILEBILIR[y][0]}: "
        f"{ayar.gecerli_deger(con, ayarlar, y)}"
        for y in ayar.DEGISTIRILEBILIR
        if db.ayar_oku(con, y) is not None
    ]
    if degisik:
        satirlar.append("⚙️ ELLE DEĞİŞTİRİLMİŞ AYARLAR")
        satirlar += [f"· {d}" for d in degisik]
        satirlar.append("")

    satirlar.append("/durum · /ayar · /tur")
    return "\n".join(satirlar)


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    kuru = "--kuru" in sys.argv
    repo = os.getenv("GITHUB_REPOSITORY", VARSAYILAN_REPO)

    ayarlar = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    db.kur()
    con = db.baglan()
    ayar.uygula(con, ayarlar)

    metin = rapor_kur(con, ayarlar, repo)

    # ⚠️ TEMİZLİK RAPORDAN SONRA: rapor dünün sayılarını okuyor, önce
    # silersek eksik rapor çıkar.
    # `--kuru` hiçbir şey SİLMEZ — kuru çalışmanın sözleşmesi bu.
    if not kuru:
        gun = ayarlar["genel"].get("kayit_saklama_gun", 7)
        try:
            silinen = db.eski_kayitlari_temizle(con, gun)
            if silinen:
                metin += (f"\n\n🧹 {silinen} eski kayıt silindi "
                          f"({gun} günden eski, yayınlanmamış).")
        except Exception as e:                        # noqa: BLE001
            # Temizlik raporu DÜŞÜRMEMELİ; rapor asıl iş.
            log.warning("temizlik yapılamadı: %s", e)

    if kuru:
        print(metin)
        return 0

    telegram_bot.mesaj_gonder(metin)
    log.info("günlük rapor gönderildi")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
