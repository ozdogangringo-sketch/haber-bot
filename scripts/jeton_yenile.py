"""
jeton_yenile.py — ADIM 7
Instagram jetonunun ömrünü kontrol eder, gerekiyorsa yeniler.

ÇALIŞTIRMA:
    python scripts/jeton_yenile.py           (gerekiyorsa yeniler)
    python scripts/jeton_yenile.py --zorla   (süre dolmasa da yeniler)
    python scripts/jeton_yenile.py --sadece-bak  (hiçbir şeyi değiştirmez)

Haftalık cron ile GitHub Actions'ta çalışıyor. Yerelde de çalıştırılabilir.

NEDEN ERKEN YENİLİYORUZ:
    Jeton ÖLDÜKTEN sonra yenilenemiyor — Graph API Explorer'dan elle
    almak gerekiyor. 10 gün pay bırakmak, haftalık cron bir kez kaçsa
    bile ikinci şansı garantiliyor.

BAŞARISIZLIK SESSİZ KALMAMALI:
    Yenileme patlarsa Telegram'a uyarı gidiyor. Bir botun jetonu sessizce
    ölürse arıza haftalar sonra "neden post gelmiyor?" diye fark ediliyor.
"""

import logging
import os
import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import yaml                                       # noqa: E402

from src import refresh_token, telegram_bot       # noqa: E402

log = logging.getLogger("jeton")

VARSAYILAN_REPO = "ozdogangringo-sketch/haber-bot"


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")

    zorla = "--zorla" in sys.argv
    sadece_bak = "--sadece-bak" in sys.argv
    repo = os.getenv("GITHUB_REPOSITORY", VARSAYILAN_REPO)

    ayarlar = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))

    try:
        durum = refresh_token.jeton_durumu(ayarlar)
    except Exception as e:
        log.exception("jeton durumu okunamadı")
        telegram_bot.hata_bildir("Jeton durumu okunamadı", str(e))
        return 1

    kalan = durum["kalan_gun"]
    print(f"  geçerli   : {durum['gecerli']}")
    print(f"  tür       : {durum['tur']}")
    print(f"  bitiş     : {durum['bitis'].strftime('%d.%m.%Y') if durum['bitis'] else 'süresiz'}")
    print(f"  kalan gün : {kalan if kalan is not None else '—'}")

    if not durum["gecerli"]:
        mesaj = (
            "Instagram jetonu GEÇERSİZ. Otomatik yenileme çalışmaz — "
            "Graph API Explorer'dan elle yeni jeton alıp "
            "`python scripts/jeton_uzat.py` ile 60 güne çevirmen gerekiyor."
        )
        log.error(mesaj)
        telegram_bot.hata_bildir("Instagram jetonu geçersiz", mesaj)
        return 1

    if sadece_bak:
        print("\n(--sadece-bak: hiçbir şey değiştirilmedi)")
        return 0

    if kalan is None:
        print("\nJeton süresiz görünüyor, yenilemeye gerek yok.")
        return 0

    if kalan > refresh_token.ESIK_GUN and not zorla:
        print(f"\nYenilemeye gerek yok ({refresh_token.ESIK_GUN} günden fazla var).")
        return 0

    print(f"\nYenileniyor (eşik: {refresh_token.ESIK_GUN} gün)...")
    try:
        yeni = refresh_token.jetonu_yenile(ayarlar)
    except Exception as e:
        log.exception("jeton yenilenemedi")
        telegram_bot.hata_bildir(
            "Instagram jetonu yenilenemedi",
            f"{e}\n\nKalan süre: {kalan} gün. Süre dolmadan elle müdahale gerekebilir."
        )
        return 1

    # Yeni jeton elimizde ama ortam değişkeni hâlâ eskisini gösteriyor;
    # doğrulama çağrısı yenisini kullansın diye güncelliyoruz.
    os.environ["IG_ACCESS_TOKEN"] = yeni

    env_oldu = refresh_token.env_guncelle(yeni)
    secret_oldu = refresh_token.github_secret_guncelle(yeni, repo)

    yeni_durum = refresh_token.jeton_durumu(ayarlar)
    print(f"  yeni bitiş: {yeni_durum['bitis'].strftime('%d.%m.%Y') if yeni_durum['bitis'] else 'süresiz'}")
    print(f"  .env      : {'güncellendi' if env_oldu else 'yok/atlandı'}")
    print(f"  GitHub    : {'güncellendi' if secret_oldu else 'GÜNCELLENEMEDİ'}")

    if not secret_oldu:
        # Bu sessiz kalamaz: .env güncellense bile runner onu görmüyor,
        # yani bot yine ölür.
        telegram_bot.hata_bildir(
            "Jeton yenilendi ama GitHub Secret güncellenemedi",
            "PAT'in 'Secrets: write' izni olmayabilir. GitHub Actions "
            "eski jetonu kullanmaya devam eder ve süresi dolunca bot durur.\n\n"
            "Çözüm: PAT'e Secrets:write izni ver, sonra "
            "`python scripts/jeton_yenile.py --zorla` çalıştır."
        )
        return 1

    telegram_bot.mesaj_gonder(
        f"🔑 Instagram jetonu yenilendi.\n"
        f"Yeni bitiş: {yeni_durum['bitis'].strftime('%d.%m.%Y') if yeni_durum['bitis'] else 'süresiz'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
