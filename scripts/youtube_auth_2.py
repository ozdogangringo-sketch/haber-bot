"""
youtube_auth_2.py — 2. Google Cloud Projesi için YouTube OAuth Yetkilendirme Scripti.

Downloads klasöründeki client_secret JSON dosyasını okur, OAuth flow başlatır,
alınan Refresh Token'ı hem .env hem de GitHub Secrets'a YOUTUBE_*_2 olarak kaydeder.
"""

import http.server
import json
import logging
import os
import socketserver
import subprocess
import sys
import urllib.parse
import webbrowser
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

REDIRECT_PORT = 8989
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]


class OAuthCallbackHandler(http.server.SimpleHTTPRequestHandler):
    auth_code = None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/callback":
            params = urllib.parse.parse_qs(parsed.query)
            if "code" in params:
                OAuthCallbackHandler.auth_code = params["code"][0]
                self.send_response(200)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    b"<html><body style='font-family:sans-serif;text-align:center;padding:40px;background:#061A1E;color:#fff;'>"
                    b"<h1 style='color:#06B6D4;'>&#10004; 2. Proje Yetkilendirmesi Ba&#351;ar&#305;l&#305;!</h1>"
                    b"<p>Bu sekmeyi kapatabilir ve terminale d&#246;nebilirsiniz.</p>"
                    b"</body></html>"
                )
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Hata: Yetki kodu alinamadi.")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def main():
    print("=" * 65)
    print("🎬 YOUTUBE 2. PROJE OAUTH2 JETON SİHİRBAZI")
    print("=" * 65)

    # Downloads klasöründen en yeni client_secret json dosyasını bul
    downloads_dir = Path.home() / "Downloads"
    json_dosyalari = sorted(downloads_dir.glob("client_secret_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not json_dosyalari:
        print("❌ Downloads klasöründe client_secret_*.json dosyası bulunamadı.")
        return 1

    secilen_json = json_dosyalari[0]
    print(f"📄 Bulunan JSON dosyası: {secilen_json.name}")

    try:
        veri = json.loads(secilen_json.read_text(encoding="utf-8"))
        web_config = veri.get("web", {})
        client_id = web_config.get("client_id", "").strip()
        client_secret = web_config.get("client_secret", "").strip()
    except Exception as e:
        print(f"❌ JSON okuma hatası: {e}")
        return 1

    if not client_id or not client_secret:
        print("❌ JSON içerisinde client_id veya client_secret bulunamadı.")
        return 1

    print(f"🔑 Client ID: {client_id[:20]}...")
    print(f"🔑 Client Secret: {client_secret[:8]}...")

    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        + urllib.parse.urlencode({
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
        })
    )

    print("\n🌐 Tarayıcınızda Google Onay Sayfası açılıyor...")
    print(f"🔗 Eğer otomatik açılmazsa lütfen bu linke tıklayın:\n{auth_url}\n")

    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    print(f"⏳ Port {REDIRECT_PORT} üzerinde yanıt bekleniyor (Onay verildikten sonra otomatik kapanır)...")
    with socketserver.TCPServer(("localhost", REDIRECT_PORT), OAuthCallbackHandler) as httpd:
        while not OAuthCallbackHandler.auth_code:
            httpd.handle_request()

    code = OAuthCallbackHandler.auth_code
    print("✅ Yetki kodu alındı, kalıcı Refresh Token alınıyor...")

    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    }

    res = requests.post(token_url, data=data, timeout=15)
    token_veri = res.json()

    refresh_token = token_veri.get("refresh_token")
    access_token = token_veri.get("access_token")

    if not refresh_token:
        print(f"\n❌ Refresh Token alınamadı: {token_veri}")
        return 1

    # Kanal Doğrulaması
    try:
        r_ch = requests.get(
            "https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        ch_veri = r_ch.json()
        if ch_veri.get("items"):
            ch_ad = ch_veri["items"][0]["snippet"]["title"]
            ch_id = ch_veri["items"][0]["id"]
            print(f"📺 Bağlanan YouTube Kanalı: {ch_ad} (ID: {ch_id})")
    except Exception as e_ch:
        print(f"⚠️ Kanal bilgisi sorgulanamadı: {e_ch}")

    print(f"\n🔑 2. Refresh Token Başarıyla Alındı: {refresh_token[:15]}... (Gizli)")

    # .env Dosyasına Kaydet
    env_path = Path(".env")
    satirlar = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []

    yeni_anahtarlar = {
        "YOUTUBE_CLIENT_ID_2": client_id,
        "YOUTUBE_CLIENT_SECRET_2": client_secret,
        "YOUTUBE_REFRESH_TOKEN_2": refresh_token,
    }

    mevcut_anahtarlar = set()
    yeni_satirlar = []
    for s in satirlar:
        esit = s.find("=")
        if esit != -1:
            k = s[:esit].strip()
            if k in yeni_anahtarlar:
                yeni_satirlar.append(f"{k}={yeni_anahtarlar[k]}")
                mevcut_anahtarlar.add(k)
                continue
        yeni_satirlar.append(s)

    for k, v in yeni_anahtarlar.items():
        if k not in mevcut_anahtarlar:
            yeni_satirlar.append(f"{k}={v}")

    env_path.write_text("\n".join(yeni_satirlar) + "\n", encoding="utf-8")
    print("💾 .env dosyası güncellendi!")

    # GitHub Actions Secrets'a kaydet
    print("\n📌 GitHub Actions Secrets güncelleniyor...")
    repo = os.getenv("GITHUB_REPOSITORY", "ozdogangringo-sketch/haber-bot")
    for ad, deger in yeni_anahtarlar.items():
        try:
            cmd = ["gh", "secret", "set", ad, "--repo", repo]
            sub = subprocess.run(cmd, input=deger, text=True, capture_output=True, timeout=60)
            if sub.returncode == 0:
                print(f"  • {ad}: ✅ GitHub Secret'a kaydedildi")
            else:
                print(f"  • {ad}: ⚠️ gh hatası: {sub.stderr.strip()[:100]}")
        except Exception as e_gh:
            print(f"  • {ad}: ⚠️ {e_gh}")

    print("\n🎉 TEBRİKLER! 2. YouTube projesi tamamen kuruldu ve kaydedildi!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
