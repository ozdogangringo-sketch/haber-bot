"""
tiktok_auth.py — TikTok Content Posting API v2 OAuth2 + PKCE Yetkilendirme Aracı.

TikTok API v2'nin zorunlu tuttuğu PKCE standardını kullanarak
TikTok hesabınızı tek tıkla bağlar ve TIKTOK_ACCESS_TOKEN üretir.

Kullanım:
    python3 scripts/tiktok_auth.py
"""

import base64
import hashlib
import json
import os
import secrets
import urllib.parse
import webbrowser
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

REDIRECT_URI = "https://haber-bot-onay.ezanplus.workers.dev/tiktok-callback"
SCOPES = ["user.info.basic", "video.upload", "video.publish"]


def generate_pkce_pair():
    """PKCE için code_verifier ve code_challenge (S256) üretir."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def main():
    print("=" * 65)
    print("🎵 TIKTOK CONTENT POSTING API PKCE YETKİLENDİRME SİHİRBAZI")
    print("=" * 65)

    client_key = os.getenv("TIKTOK_CLIENT_KEY", "").strip() or "sbawe0cyh06uct6wt7"
    client_secret = os.getenv("TIKTOK_CLIENT_SECRET", "").strip() or "md29enTkZzSgGZtFN5ICOaKR28OJsp1F"

    code_verifier, code_challenge = generate_pkce_pair()

    auth_params = {
        "client_key": client_key,
        "scope": ",".join(SCOPES),
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "state": "dailybrief_bot",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }

    auth_url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode(auth_params)

    print("\n🌐 Tarayıcıda TikTok yetkilendirme sayfası açılıyor...")
    print(f"🔗 Eğer otomatik açılmazsa bu linke tıklayın:\n{auth_url}\n")

    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    print("=" * 65)
    print("📋 Onay verdikten sonra açılan sayfadaki KODU buraya yapıştırın:")
    code = input("👉 Kod: ").strip()

    if not code:
        print("❌ Kod girilmedi.")
        return

    print("✅ Kod alındı, kalıcı Access Token talep ediliyor...")

    token_url = "https://open.tiktokapis.com/v2/oauth/token/"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "client_key": client_key,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
        "code_verifier": code_verifier,
    }

    res = requests.post(token_url, headers=headers, data=data, timeout=15)
    veri = res.json()

    access_token = veri.get("data", {}).get("access_token") or veri.get("access_token")
    refresh_token = veri.get("data", {}).get("refresh_token") or veri.get("refresh_token")
    open_id = veri.get("data", {}).get("open_id") or veri.get("open_id")

    if not access_token:
        print(f"\n❌ Token alınamadı: {veri}")
        return

    print("\n🎉 TEBRİKLER! TikTok bağlantısı başarıyla sağlandı.")
    print(f"🔑 Access Token: {access_token[:15]}...")

    # .env'ye kaydet
    env_path = Path(".env")
    satirlar = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []

    yeni_anahtarlar = {
        "TIKTOK_CLIENT_KEY": client_key,
        "TIKTOK_CLIENT_SECRET": client_secret,
        "TIKTOK_ACCESS_TOKEN": access_token,
        "TIKTOK_REFRESH_TOKEN": refresh_token or "",
        "TIKTOK_OPEN_ID": open_id or "",
    }

    seen = set()
    yeni_satirlar = []
    for s in satirlar:
        if "=" in s:
            k = s.split("=", 1)[0].strip()
            if k in yeni_anahtarlar:
                yeni_satirlar.append(f"{k}={yeni_anahtarlar[k]}")
                seen.add(k)
                continue
        yeni_satirlar.append(s)

    for k, v in yeni_anahtarlar.items():
        if k not in seen and v:
            yeni_satirlar.append(f"{k}={v}")

    env_path.write_text("\n".join(yeni_satirlar) + "\n", encoding="utf-8")
    print("💾 .env dosyası güncellendi!")

    print("\n📌 GİTHUB ACTIONS SECRET EKLEME:")
    print(f"  • TIKTOK_ACCESS_TOKEN = {access_token}")
    print("=" * 65)


if __name__ == "__main__":
    main()
