"""
tiktok_auth.py — TikTok Content Posting API v2 OAuth2 + PKCE Yetkilendirme Aracı.

TikTok API v2'nin zorunlu tuttuğu PKCE (code_challenge & code_verifier) standardını
kullanarak TikTok hesabınızı tek tıkla bağlar ve TIKTOK_ACCESS_TOKEN üretir.

Kullanım:
    python3 scripts/tiktok_auth.py
"""

import base64
import hashlib
import http.server
import json
import os
import secrets
import socketserver
import urllib.parse
import webbrowser
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

REDIRECT_PORT = 8990
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"
SCOPES = ["user.info.basic", "video.upload", "video.publish"]


def generate_pkce_pair():
    """PKCE için code_verifier ve code_challenge (S256) üretir."""
    verifier = secrets.token_urlsafe(64)
    # SHA-256 hash
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    # URL-safe Base64 without padding
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


class TikTokCallbackHandler(http.server.SimpleHTTPRequestHandler):
    auth_code = None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/callback":
            params = urllib.parse.parse_qs(parsed.query)
            if "code" in params:
                TikTokCallbackHandler.auth_code = params["code"][0]
                self.send_response(200)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    b"<html><body style='font-family:sans-serif;text-align:center;padding:40px;background:#061A1E;color:#fff;'>"
                    b"<h1 style='color:#06B6D4;'>&#10004; TikTok Yetkilendirmesi Ba&#351;ar&#305;l&#305;!</h1>"
                    b"<p>Bu sekmeyi kapatabilir ve terminale d&#246;nebilirsiniz.</p>"
                    b"</body></html>"
                )
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Hata: Kod alinamadi.")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def main():
    print("=" * 65)
    print("🎵 TIKTOK CONTENT POSTING API PKCE YETKİLENDİRME SİHİRBAZI")
    print("=" * 65)

    client_key = os.getenv("TIKTOK_CLIENT_KEY", "").strip() or "awkfxqrn4j2m603e"
    client_secret = os.getenv("TIKTOK_CLIENT_SECRET", "").strip()

    if not client_key:
        client_key = input("\n🔑 TikTok Client Key: ").strip()
    else:
        print(f"\n🔑 Client Key: {client_key}")

    if not client_secret:
        client_secret = input("🔑 TikTok Client Secret: ").strip()
    else:
        print(f"🔑 Client Secret: {client_secret[:6]}...")

    if not client_key or not client_secret:
        print("\n❌ Client Key ve Client Secret boş bırakılamaz.")
        return

    # PKCE oluştur
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

    print(f"⏳ Port {REDIRECT_PORT} üzerinde onay bekleniyor...")
    with socketserver.TCPServer(("localhost", REDIRECT_PORT), TikTokCallbackHandler) as httpd:
        while not TikTokCallbackHandler.auth_code:
            httpd.handle_request()

    code = TikTokCallbackHandler.auth_code
    print("✅ Yetki kodu alındı, Access Token talep ediliyor...")

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
