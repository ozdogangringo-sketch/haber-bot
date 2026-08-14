"""
TELEGRAM CHAT ID BULMA
Çalıştır:  python scripts/telegram_chat_id_bul.py

Ne yapar:
  1. Bot jetonunun geçerli olduğunu doğrular
  2. Bota gelen son mesajlardan chat ID'yi bulur
  3. .env dosyasına TELEGRAM_CHAT_ID olarak yazar
  4. Doğrulama için sana bir test mesajı gönderir

ÖNCE BOTA MESAJ AT: Telegram, bot ilk mesajı almadan sohbeti
göstermiyor. Botu bulup herhangi bir şey yaz ("selam" yeter).

ZAMANLAMA UYARISI:
  Bu script getUpdates kullanıyor. Adım 5'te webhook kurulunca
  getUpdates ÇALIŞMAZ (Telegram ikisine aynı anda izin vermiyor).
  Yani chat ID'yi webhook'tan ÖNCE almak gerekiyor.
"""

import os
import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import requests                                   # noqa: E402
from dotenv import load_dotenv                    # noqa: E402

ENV_YOLU = KOK / ".env"
load_dotenv(ENV_YOLU)


def env_guncelle(anahtar: str, deger: str):
    """`.env` içindeki tek satırı değiştirir, gerisine dokunmaz."""
    satirlar = ENV_YOLU.read_text(encoding="utf-8").splitlines()
    for i, s in enumerate(satirlar):
        if s.strip().startswith(f"{anahtar}="):
            satirlar[i] = f"{anahtar}={deger}"
            break
    else:
        satirlar.append(f"{anahtar}={deger}")
    ENV_YOLU.write_text("\n".join(satirlar) + "\n", encoding="utf-8")


def main():
    jeton = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not jeton:
        print("TELEGRAM_BOT_TOKEN .env'de yok.")
        print("@BotFather'ın verdiği jetonu ekle.")
        return

    taban = f"https://api.telegram.org/bot{jeton}"
    print(f"Jeton: {jeton[:8]}…{jeton[-4:]}  ({len(jeton)} karakter)\n")

    # --- 1) Jeton geçerli mi ---
    print("=" * 60)
    print("1) BOT KİMLİĞİ")
    print("=" * 60)
    try:
        d = requests.get(f"{taban}/getMe", timeout=30).json()
    except Exception as e:
        print(f"  Bağlantı hatası: {type(e).__name__}: {e}")
        return

    if not d.get("ok"):
        print(f"  ✗ Jeton geçersiz: {d.get('description')}")
        return

    bot = d["result"]
    print(f"  ✓ Bot adı      : {bot.get('first_name')}")
    print(f"    Kullanıcı adı: @{bot.get('username')}")

    # --- 2) Webhook kurulu mu (getUpdates'i engeller) ---
    try:
        w = requests.get(f"{taban}/getWebhookInfo", timeout=30).json()
        webhook_url = (w.get("result") or {}).get("url") or ""
        if webhook_url:
            print(f"\n  ⚠ Webhook kurulu: {webhook_url}")
            print("    Webhook varken getUpdates çalışmaz. Chat ID'yi")
            print("    bulmak için önce webhook'u kaldırman gerekir:")
            print(f"    {taban}/deleteWebhook")
            return
    except Exception:
        pass        # bilgi amaçlı, patlarsa devam

    # --- 3) Gelen mesajlar ---
    print("\n" + "=" * 60)
    print("2) GELEN MESAJLAR")
    print("=" * 60)
    try:
        d = requests.get(f"{taban}/getUpdates", timeout=30).json()
    except Exception as e:
        print(f"  Bağlantı hatası: {type(e).__name__}: {e}")
        return

    guncellemeler = d.get("result", [])
    if not guncellemeler:
        print("  ✗ Hiç mesaj yok.")
        print("\n  Yapılacak: Telegram'da botu bul "
              f"(@{bot.get('username')}), sohbeti aç ve")
        print("  herhangi bir mesaj yaz. Sonra bu scripti tekrar çalıştır.")
        print("\n  Not: Telegram mesajları ~24 saat tutuyor. Çok eskiyse")
        print("  yeni bir mesaj at.")
        return

    sohbetler = {}
    for g in guncellemeler:
        mesaj = g.get("message") or g.get("edited_message") or {}
        sohbet = mesaj.get("chat")
        if sohbet:
            sohbetler[sohbet["id"]] = sohbet

    for sid, s in sohbetler.items():
        ad = " ".join(filter(None, [s.get("first_name"), s.get("last_name")]))
        print(f"  Chat ID: {sid}")
        print(f"    Kim  : {ad or s.get('title', '?')}")
        print(f"    Tür  : {s.get('type')}")
        if s.get("username"):
            print(f"    Kul.a: @{s['username']}")

    if len(sohbetler) > 1:
        print("\n  ⚠ Birden fazla sohbet var. Kendi sohbetini seçip")
        print("    .env'e elle yaz — tahmin etmiyorum.")
        return

    chat_id = next(iter(sohbetler))
    env_guncelle("TELEGRAM_CHAT_ID", str(chat_id))
    print(f"\n  ✓ .env güncellendi: TELEGRAM_CHAT_ID={chat_id}")

    # --- 4) Test mesajı ---
    print("\n" + "=" * 60)
    print("3) TEST MESAJI")
    print("=" * 60)
    try:
        d = requests.post(
            f"{taban}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": (
                    "✅ Bağlantı çalışıyor.\n\n"
                    "Haber botu buradan onay soracak. "
                    "Henüz yapılandırma aşamasındayız."
                ),
            },
            timeout=30,
        ).json()
    except Exception as e:
        print(f"  Gönderilemedi: {type(e).__name__}: {e}")
        return

    if d.get("ok"):
        print("  ✓ Telegram'a mesaj gitti — telefonuna bak.")
    else:
        print(f"  ✗ {d.get('description')}")


if __name__ == "__main__":
    main()
