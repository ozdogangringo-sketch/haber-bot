"""
JETON UZATMA
Çalıştır:  python scripts/jeton_uzat.py

Graph API Explorer'dan aldığın jeton 1-2 saat yaşar. Bu script onu
60 günlük "uzun ömürlü" jetona çevirir ve .env dosyanı günceller.

NEDEN GEREKLİ:
    Kısa ömürlü jetonla bot bir sonraki gün çalışmaz. 60 günlük jeton
    da sonsuz değil — Adım 7'de haftalık otomatik yenileme kuracağız.
    Bu script o otomatiğin elle çalışan hali.

GÜVENLİK:
    Jetonu ekrana basmaz, doğrudan .env'e yazar. Eski .env dosyasının
    yedeğini .env.yedek olarak bırakır.
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import requests                                   # noqa: E402
from dotenv import load_dotenv                    # noqa: E402

from src.fetch_news import ayarlari_oku           # noqa: E402

ENV_YOLU = KOK / ".env"
load_dotenv(ENV_YOLU)

SURUM = ayarlari_oku()["instagram"]["api_surumu"]


def env_guncelle(anahtar: str, yeni_deger: str):
    """
    .env içindeki tek bir satırı değiştirir, gerisine dokunmaz.
    Dosyayı baştan yazmıyoruz ki yorumlar ve diğer anahtarlar korunsun.
    """
    satirlar = ENV_YOLU.read_text(encoding="utf-8").splitlines()
    bulundu = False
    for i, satir in enumerate(satirlar):
        if satir.strip().startswith(f"{anahtar}="):
            satirlar[i] = f"{anahtar}={yeni_deger}"
            bulundu = True
            break
    if not bulundu:
        satirlar.append(f"{anahtar}={yeni_deger}")

    # Önce yedek al — bu dosyada başka anahtarlar da var
    yedek = ENV_YOLU.parent / ".env.yedek"
    yedek.write_text(ENV_YOLU.read_text(encoding="utf-8"), encoding="utf-8")
    ENV_YOLU.write_text("\n".join(satirlar) + "\n", encoding="utf-8")
    return yedek


def main():
    jeton = os.getenv("IG_ACCESS_TOKEN", "").strip()
    app_id = os.getenv("META_APP_ID", "").strip()
    app_secret = os.getenv("META_APP_SECRET", "").strip()

    if not all((jeton, app_id, app_secret)):
        print("IG_ACCESS_TOKEN, META_APP_ID ve META_APP_SECRET .env'de olmalı.")
        return

    print("Jeton uzun ömürlüye çevriliyor...")
    try:
        c = requests.get(
            f"https://graph.facebook.com/{SURUM}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": app_id,
                "client_secret": app_secret,
                "fb_exchange_token": jeton,
            },
            timeout=60,
        )
        veri = c.json()
    except Exception as e:
        print(f"Bağlantı hatası: {type(e).__name__}: {e}")
        return

    if "error" in veri:
        h = veri["error"]
        print(f"HATA: {h.get('type')}: {h.get('message')}")
        print("\nSık görülen sebep: jeton zaten ölmüş olabilir.")
        print("Graph API Explorer'dan yenisini alıp tekrar dene.")
        return

    yeni = veri.get("access_token")
    if not yeni:
        print(f"Beklenmeyen cevap: {str(veri)[:200]}")
        return

    saniye = veri.get("expires_in")
    yedek = env_guncelle("IG_ACCESS_TOKEN", yeni)

    print("✓ Jeton uzatıldı ve .env güncellendi.")
    print(f"  (eski dosyanın yedeği: {yedek.name} — git'e girmez)")
    if saniye:
        biter = datetime.now(timezone.utc) + timedelta(seconds=int(saniye))
        print(f"  Yeni son kullanma: {biter:%d %b %Y} "
              f"(~{int(saniye) // 86400} gün)")
    print("\nDoğrulamak için: python scripts/test_5_instagram_baglanti.py")


if __name__ == "__main__":
    main()
