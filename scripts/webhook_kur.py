"""
Telegram webhook'unu kurar veya kaldırır.

KULLANIM:
    python scripts/webhook_kur.py https://haber-bot-onay.XXX.workers.dev
    python scripts/webhook_kur.py --durum      (mevcut ayarı gösterir)
    python scripts/webhook_kur.py --kaldir     (webhook'u siler)

WEBHOOK NE YAPAR:
    Telegram'a "birisi butona basarsa şu adrese haber ver" diyoruz.
    Kurulmadan önce butonlar görünür ama basınca hiçbir şey olmaz.

⚠️ KURULDUKTAN SONRA getUpdates ÇALIŞMAZ:
    Telegram webhook ve getUpdates'e aynı anda izin vermiyor. Yani
    `scripts/telegram_chat_id_bul.py` boş dönmeye başlar. Bu arıza değil,
    beklenen davranış — chat ID zaten .env'de kayıtlı.

GÜVENLİK:
    secret_token, Telegram'ın her istekte göndereceği paroladır. Worker
    bunu doğruluyor; olmadan Worker'ın adresini bilen herkes sahte
    "yayınla" isteği gönderebilirdi.
"""

import sys
from getpass import getpass
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import os                                    # noqa: E402

import requests                              # noqa: E402
from dotenv import load_dotenv               # noqa: E402

load_dotenv(KOK / ".env")

TABAN = "https://api.telegram.org/bot{jeton}/{metot}"


def cagir(metot: str, **parametreler) -> dict:
    jeton = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not jeton:
        print("✗ TELEGRAM_BOT_TOKEN bulunamadı (.env)")
        raise SystemExit(1)
    cevap = requests.post(
        TABAN.format(jeton=jeton, metot=metot), json=parametreler, timeout=60
    )
    return cevap.json()


def durum() -> int:
    d = cagir("getWebhookInfo")
    if not d.get("ok"):
        print("✗", d.get("description"))
        return 1
    r = d["result"]
    print("Webhook adresi   :", r.get("url") or "(kurulu değil)")
    print("Bekleyen güncelleme:", r.get("pending_update_count", 0))
    if r.get("last_error_message"):
        print("Son hata         :", r["last_error_message"])
        print("  (Worker'ın çalıştığından ve secret'ın eşleştiğinden emin ol)")
    return 0


def kaldir() -> int:
    d = cagir("deleteWebhook", drop_pending_updates=True)
    print("✓ webhook kaldırıldı" if d.get("ok") else f"✗ {d.get('description')}")
    print("  getUpdates artık yeniden çalışır.")
    return 0 if d.get("ok") else 1


def kur(url: str) -> int:
    if not url.startswith("https://"):
        print("✗ Adres https:// ile başlamalı. Telegram http kabul etmiyor.")
        return 1

    # .env'de varsa oradan al: aynı değer Worker'a da verildiği için iki
    # yere elle yapıştırmak hem zahmetli hem hataya açık. Bir harf farkla
    # webhook sessizce çalışmaz ve sebebi anlaşılmaz.
    gizli = os.getenv("WEBHOOK_SECRET", "").strip()
    if gizli:
        print(f"\n✓ WEBHOOK_SECRET .env'den okundu ({len(gizli)} karakter).")
    else:
        print("\nWEBHOOK_SECRET değerini gir (Worker'a verdiğin parolanın AYNISI).")
        print("(Yazdığın ekranda görünmez.)\n")
        gizli = getpass("WEBHOOK_SECRET = ").strip()

    if not gizli:
        print("✗ Boş parola kabul edilmiyor — Worker doğrulama yapamaz.")
        return 1

    d = cagir(
        "setWebhook",
        url=url,
        secret_token=gizli,
        # Buton basımları + yazılı komutlar (/durum, /tur, /yardim).
        # `message` de dinleniyor çünkü buton menüsü yalnızca açık bir
        # onay mesajı varken işe yarıyor; tur kapandığında elde tutamak
        # kalmıyordu. Worker komut olmayan mesajları hemen eleyip
        # GitHub'a taşımıyor, o yüzden grup sohbeti maliyet doğurmuyor.
        allowed_updates=["callback_query", "message"],
        drop_pending_updates=True,
    )
    if not d.get("ok"):
        print("✗", d.get("description"))
        return 1

    print(f"\n✓ webhook kuruldu: {url}")
    print("  İletilecek: buton basımları (callback_query) + mesajlar (message).")
    print("  Mesajlar /durum, /tur, /yardim komutları için gerekli;")
    print("  Worker komut olmayanları hemen eleyip GitHub'a taşımıyor.")
    print("\n⚠️ getUpdates artık ÇALIŞMAZ — telegram_chat_id_bul.py boş döner.")
    print("   Bu beklenen davranış, arıza değil.\n")
    return durum()


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    arg = sys.argv[1]
    if arg == "--durum":
        return durum()
    if arg == "--kaldir":
        return kaldir()
    return kur(arg)


if __name__ == "__main__":
    raise SystemExit(main())
