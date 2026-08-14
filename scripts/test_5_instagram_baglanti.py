"""
INSTAGRAM BAĞLANTI DOĞRULAMASI
Çalıştır:  python scripts/test_5_instagram_baglanti.py

Ne yapar:
  .env'deki Meta bilgilerini kullanıp bağlantının doğru kurulup
  kurulmadığını uçtan uca kontrol eder. Hiçbir şey YAYINLAMAZ.

  1. .env'de hangi değerler var (değerleri EKRANA BASMADAN)
  2. Jeton geçerli mi, ne zaman ölüyor, hangi izinler verilmiş
  3. Hangi Facebook sayfası bağlı
  4. Sayfaya bağlı Instagram hesabı var mı, IG_USER_ID kaç
  5. Hesap gerçekten İşletme (Business) mi
  6. Yayınlama kotası ne durumda

Bu script hiçbir anahtarı tam olarak yazdırmaz — sadece ilk/son
birkaç karakterini gösterir.
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import requests                                   # noqa: E402
from dotenv import load_dotenv                    # noqa: E402

from src.fetch_news import ayarlari_oku           # noqa: E402

load_dotenv(KOK / ".env")

ayarlar = ayarlari_oku()
SURUM = ayarlar["instagram"]["api_surumu"]
TABAN = f"https://graph.facebook.com/{SURUM}"
ZAMAN_ASIMI = ayarlar["instagram"]["zaman_asimi"]


def maskele(deger: str) -> str:
    if not deger:
        return "(YOK)"
    if len(deger) <= 12:
        return deger[:2] + "…" + deger[-2:]
    return f"{deger[:6]}…{deger[-4:]} ({len(deger)} karakter)"


def cizgi(baslik):
    print("\n" + "=" * 70)
    print(baslik)
    print("=" * 70)


def iste(yol: str, parametreler: dict):
    """Graph API çağrısı. Hata olursa sözlük olarak döner, patlamaz."""
    try:
        c = requests.get(f"{TABAN}{yol}", params=parametreler, timeout=ZAMAN_ASIMI)
        veri = c.json()
    except Exception as e:
        return {"_hata": f"{type(e).__name__}: {e}"}
    if "error" in veri:
        h = veri["error"]
        return {"_hata": f"{h.get('type')}: {h.get('message')}"}
    return veri


def main():
    jeton = os.getenv("IG_ACCESS_TOKEN", "").strip()
    app_id = os.getenv("META_APP_ID", "").strip()
    app_secret = os.getenv("META_APP_SECRET", "").strip()
    ig_user_id = os.getenv("IG_USER_ID", "").strip()

    cizgi("1) .env DURUMU")
    print(f"  META_APP_ID      : {maskele(app_id)}")
    print(f"  META_APP_SECRET  : {maskele(app_secret)}")
    print(f"  IG_ACCESS_TOKEN  : {maskele(jeton)}")
    print(f"  IG_USER_ID       : {ig_user_id or '(YOK — bu scriptin bulacağı değer)'}")

    eksik = [ad for ad, d in (("META_APP_ID", app_id),
                              ("META_APP_SECRET", app_secret),
                              ("IG_ACCESS_TOKEN", jeton)) if not d]
    if eksik:
        print(f"\n  EKSİK: {', '.join(eksik)}")
        print("  Bunlar olmadan devam edemem. .env dosyasına ekle.")
        return

    # ---------------------------------------------------------------
    cizgi("2) JETON GEÇERLİ Mİ")
    d = iste("/debug_token", {
        "input_token": jeton,
        "access_token": f"{app_id}|{app_secret}",
    })
    if "_hata" in d:
        print(f"  ✗ {d['_hata']}")
        print("\n  Muhtemel sebep: App ID/Secret yanlış ya da jeton bu")
        print("  uygulamaya ait değil. Graph API Explorer'da doğru")
        print("  uygulamayı seçtiğinden emin ol.")
        return

    bilgi = d.get("data", {})
    gecerli = bilgi.get("is_valid")
    print(f"  Geçerli mi   : {'✓ evet' if gecerli else '✗ HAYIR'}")
    if not gecerli:
        print(f"  Sebep        : {bilgi.get('error', {}).get('message', '?')}")
        return

    bitis = bilgi.get("expires_at", 0)
    if bitis == 0:
        print("  Son kullanma : süresiz (kalıcı jeton)")
    else:
        bt = datetime.fromtimestamp(bitis, tz=timezone.utc)
        kalan = bt - datetime.now(timezone.utc)
        gun = kalan.days
        saat = kalan.seconds // 3600
        print(f"  Son kullanma : {bt:%d %b %Y %H:%M} UTC  → {gun} gün {saat} saat kaldı")
        if gun < 7:
            print("  ⚠ KISA ÖMÜRLÜ JETON. Aşağıdaki adımı mutlaka yap.")

    izinler = set(bilgi.get("scopes", []))
    print(f"\n  Verilen izinler ({len(izinler)}):")
    gerekli = [
        "instagram_basic",
        "instagram_content_publish",
        "pages_show_list",
        "pages_read_engagement",
        "business_management",
    ]
    for izin in gerekli:
        print(f"    {'✓' if izin in izinler else '✗ EKSİK'}  {izin}")
    fazlalik = izinler - set(gerekli)
    if fazlalik:
        print(f"    (ayrıca: {', '.join(sorted(fazlalik))})")

    # ---------------------------------------------------------------
    cizgi("3) BAĞLI FACEBOOK SAYFALARI")
    d = iste("/me/accounts", {
        "fields": "id,name,instagram_business_account{id,username,name}",
        "access_token": jeton,
    })
    if "_hata" in d:
        print(f"  ✗ {d['_hata']}")
        return

    sayfalar = d.get("data", [])
    if not sayfalar:
        print("  ✗ Hiç sayfa bulunamadı.")
        print("  Jeton alırken sayfayı seçmemiş olabilirsin — Graph API")
        print("  Explorer'da izin ekranında sayfayı işaretlemen gerekiyor.")
        return

    bulunan_ig = None
    for s in sayfalar:
        ig = s.get("instagram_business_account")
        print(f"\n  Sayfa: {s['name']}  (id: {s['id']})")
        if ig:
            print(f"    ✓ Instagram bağlı: @{ig.get('username')}  (id: {ig['id']})")
            bulunan_ig = ig
        else:
            print("    ✗ Bu sayfaya bağlı Instagram İŞLETME hesabı yok")

    if not bulunan_ig:
        print("\n  ✗ Hiçbir sayfada Instagram işletme hesabı görünmüyor.")
        print("  Sebebi genelde şu ikisinden biri:")
        print("    - Instagram hesabı 'Yaratıcı' türünde (İşletme olmalı)")
        print("    - Hesap sayfaya bağlı değil")
        return

    # ---------------------------------------------------------------
    cizgi("4) INSTAGRAM HESABI")
    d = iste(f"/{bulunan_ig['id']}", {
        "fields": "id,username,name,account_type,followers_count,media_count",
        "access_token": jeton,
    })
    if "_hata" in d:
        print(f"  ✗ {d['_hata']}")
    else:
        print(f"  Kullanıcı adı : @{d.get('username')}")
        print(f"  Ad            : {d.get('name')}")
        print(f"  Hesap türü    : {d.get('account_type', '?')}")
        print(f"  Takipçi       : {d.get('followers_count', '?')}")
        print(f"  Gönderi       : {d.get('media_count', '?')}")

    # ---------------------------------------------------------------
    cizgi("5) YAYINLAMA KOTASI")
    d = iste(f"/{bulunan_ig['id']}/content_publishing_limit", {
        "access_token": jeton,
    })
    if "_hata" in d:
        print(f"  (okunamadı: {d['_hata']})")
    else:
        for satir in d.get("data", []):
            print(f"  Son 24 saatte kullanılan: {satir.get('quota_usage')} / 100")

    # ---------------------------------------------------------------
    cizgi("SONUÇ")
    print(f"  .env dosyana şu satırı ekle (veya güncelle):\n")
    print(f"      IG_USER_ID={bulunan_ig['id']}\n")
    if bitis != 0 and (datetime.fromtimestamp(bitis, tz=timezone.utc)
                       - datetime.now(timezone.utc)).days < 7:
        print("  Jetonun kısa ömürlü. 60 günlüğe çevirmek için:")
        print("      python scripts/jeton_uzat.py")


if __name__ == "__main__":
    main()
