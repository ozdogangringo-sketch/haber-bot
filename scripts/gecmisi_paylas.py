"""
gecmisi_paylas.py — Daha önce Instagram'a yayınlanmış turları Threads'e taşır.

NEDEN VAR:
    Threads sonradan eklendi ve hesap bomboş kaldı. Instagram'da yayında
    olan turlar orada da olsun diye, geçmiş turlar kronolojik sırayla
    yeniden paylaşılıyor.

⚠️ TARİH: her tur KENDİ tarihiyle paylaşılıyor, bugünün tarihiyle değil.
    `caption.kisa_metin_kur` tarih verilmezse bugünü yazıyor; geriye dönük
    paylaşımda bu 15 Ağustos turuna "18 Ağustos" yazdırırdı.

⚠️ GÖRSELLER 2 GÜNDE SİLİNİYOR (`imgbb.omur_saniye`). Instagram yayında
    kendi kopyasını aldığı için postlar etkilenmiyor, ama geriye dönük
    paylaşımda 2 günden eski turların görselleri artık yok. Script bunu
    önceden kontrol ediyor ve o turu ATLIYOR — yarım carousel atmaktansa
    atlamak doğru. Slaytlar `hazirla.py` ile yeniden üretilebilir.

ÇALIŞTIRMA:
    python scripts/gecmisi_paylas.py --kuru    # PAYLAŞMAZ, ne gideceğini gösterir
    python scripts/gecmisi_paylas.py           # gerçekten paylaşır

    --bekleme N   turlar arası saniye (varsayılan 60)
"""

import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import requests                                   # noqa: E402
import yaml                                       # noqa: E402

from src import caption, db, threads              # noqa: E402

log = logging.getLogger("gecmis")

# Turlar arası varsayılan bekleme. Art arda 8 carousel atmak hem hesabı
# spam gibi gösteriyor hem de Threads'in medya işleme tarafını yoruyor
# (2207052 hatasını kurulumda bizzat gördük).
VARSAYILAN_BEKLEME = 60


def turlari_getir(con) -> list[dict]:
    """Yayınlanmış turları kronolojik sırayla döner."""
    satirlar = con.execute("""
        SELECT telegram_message_id AS msg, MIN(gonderim_zamani) AS zaman
        FROM haberler
        WHERE durum = 'yayinlandi' AND ig_post_id IS NOT NULL
          AND telegram_message_id IS NOT NULL
        GROUP BY telegram_message_id
        ORDER BY MIN(gonderim_zamani)
    """).fetchall()

    turlar = []
    for satir in satirlar:
        haberler = list(con.execute(
            "SELECT * FROM haberler WHERE telegram_message_id = ? ORDER BY id",
            (satir["msg"],),
        ))
        if not haberler:
            continue

        urller = []
        for haber in haberler:
            if haber["gorsel_url"]:
                urller.append(haber["gorsel_url"])
            # Son dakika turlarında ayrıntı sayfaları ayrı kolonda.
            if haber["son_dakika"] and haber["detay_url"]:
                try:
                    urller += json.loads(haber["detay_url"])
                except (json.JSONDecodeError, TypeError):
                    urller.append(haber["detay_url"])

        turlar.append({
            "msg": satir["msg"],
            "zaman": satir["zaman"],
            "haberler": haberler,
            "urller": urller,
            "son_dakika": bool(haberler[0]["son_dakika"]),
        })
    return turlar


def gorseller_saglam_mi(urller: list[str]) -> tuple[bool, int]:
    """Kaç görsel hâlâ erişilebilir? Hepsi değilse tur atlanmalı."""
    saglam = 0
    for url in urller:
        try:
            if requests.head(url, timeout=15).status_code == 200:
                saglam += 1
        except requests.RequestException:
            pass
    return saglam == len(urller) and saglam > 0, saglam


def _tur_gunu(zaman: str):
    """Turun kendi tarihi — paylaşım metninde bugünün tarihi yazmasın."""
    try:
        return datetime.fromisoformat(zaman).date()
    except (ValueError, TypeError):
        return None


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")

    kuru = "--kuru" in sys.argv
    bekleme = VARSAYILAN_BEKLEME
    if "--bekleme" in sys.argv:
        bekleme = int(sys.argv[sys.argv.index("--bekleme") + 1])

    ayarlar = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    con = db.baglan()

    if not kuru and not threads.kullanilabilir_mi():
        log.error("Threads anahtarları yok (.env)")
        return 1

    turlar = turlari_getir(con)
    print(f"\n{len(turlar)} yayınlanmış tur bulundu.\n")

    paylasilacak, atlanan = [], []
    for tur in turlar:
        tam, saglam = gorseller_saglam_mi(tur["urller"])
        etiket = "son dakika" if tur["son_dakika"] else "akşam turu"
        durum = f"{saglam}/{len(tur['urller'])} görsel"

        # Threads carousel 2-20 görsel istiyor; tek görselde carousel'e
        # gerek yok, threads.yayinla onu tek gönderi olarak atıyor.
        if tam:
            paylasilacak.append(tur)
            print(f"  ✓ {tur['zaman'][:16]}  {etiket:11} {durum}")
        else:
            atlanan.append(tur)
            print(f"  ✗ {tur['zaman'][:16]}  {etiket:11} {durum}  → ATLANIYOR")

    if atlanan:
        print(f"\n⚠️  {len(atlanan)} tur atlanıyor: görselleri imgbb'den "
              f"silinmiş (2 günlük ömür).")
        print("    Slaytları yeniden üretilirse paylaşılabilirler.")

    if not paylasilacak:
        print("\nPaylaşılacak tur yok.")
        return 0

    print(f"\n{len(paylasilacak)} tur paylaşılacak"
          f"{' (KURU ÇALIŞMA)' if kuru else ''}:\n")
    print("=" * 68)

    for sira, tur in enumerate(paylasilacak, 1):
        metin = caption.kisa_metin_kur(
            tur["haberler"], caption.THREADS_AZAMI,
            gun=_tur_gunu(tur["zaman"]), ayarlar=ayarlar,
            baslik="Son dakika" if tur["son_dakika"] else "Günün gündemi",
        )
        print(f"\n[{sira}/{len(paylasilacak)}] {tur['zaman'][:16]}  "
              f"{len(tur['urller'])} görsel  {len(metin)} karakter")
        print("-" * 68)
        print(metin)
        print("-" * 68)

        if kuru:
            continue

        try:
            post_id = threads.yayinla(tur["urller"], metin)
            print(f"✓ Threads'e paylaşıldı: {post_id}")
        except Exception as e:
            # Bir tur patlasa da diğerleri denensin.
            print(f"✗ paylaşılamadı: {type(e).__name__}: {e}")

        if sira < len(paylasilacak):
            print(f"  ({bekleme} sn bekleniyor…)")
            time.sleep(bekleme)

    if kuru:
        print("\n\nKURU ÇALIŞMA — hiçbir şey paylaşılmadı.")
        print("Gerçekten paylaşmak için --kuru olmadan çalıştır.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
