"""
tiktok_auth.py — TikTok Sandbox PKCE Yetkilendirme Sihirbazı.

TikTok Sandbox kuralı gereği Redirect URI:
    http://127.0.0.1:8990/callback  veya  https://127.0.0.1:8990/callback
olmalıdır.
"""

import base64
import hashlib
import http.server
import json
import os
import secrets
import socket
import socketserver
import threading
import urllib.parse
import webbrowser
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

REDIRECT_URI = "https://haber-bot-onay.ezanplus.workers.dev/tiktok-callback"
SCOPES = ["user.info.basic", "video.upload", "video.publish"]


def generate_pkce_pair():
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
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
                    b"<p>Bu sekmeyi kapatabilirsiniz.</p>"
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


class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True

    def server_bind(self):
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except Exception:
            pass
        super().server_bind()


def main():
    print("=" * 65)
    print("🎵 TIKTOK SANDBOX PKCE YETKİLENDİRME SİHİRBAZI")
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

    print(f"\n📌 TikTok Portalındaki Redirect URI: {REDIRECT_URI}")
    print("\n🌐 Tarayıcıda yetkilendirme sayfası açılıyor...")
    print(f"🔗 Link:\n{auth_url}\n")

    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    print("=" * 65)
    print("📋 Onay verdikten sonra açılan ekranda mavi kutuda görünen KODU yapıştırın:")
    code_raw = input("👉 Kod veya Yönlenen URL: ").strip()

    code = code_raw
    if "code=" in code_raw:
        parsed = urllib.parse.urlparse(code_raw)
        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [code_raw])[0]

    if not code:
        print("❌ Kod girilmedi.")
        return

    print("✅ Kod işleniyor, Access Token talep ediliyor...")

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

    print("\n🎉 TEBRİKLER! TikTok Sandbox bağlantısı başarıyla sağlandı.")
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
