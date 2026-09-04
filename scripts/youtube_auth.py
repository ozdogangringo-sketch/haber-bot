"""
youtube_auth.py — YouTube API OAuth2 Yetkilendirme ve Refresh Token Alma Aracı.

Bu script, Google Cloud Console'dan aldığınız Client ID ve Client Secret ile
YouTube Shorts yükleme iznini (OAuth2) tek tıkla onaylayıp kalıcı
YOUTUBE_REFRESH_TOKEN üretir ve .env dosyanıza otomatik kaydeder.

Kullanım:
    python3 scripts/youtube_auth.py
"""

import http.server
import json
import os
import socketserver
import urllib.parse
import webbrowser
import sys
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
                    b"<h1 style='color:#06B6D4;'>&#10004; Yetkilendirme Ba&#351;ar&#305;l&#305;!</h1>"
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
        pass  # Konsolu temiz tut


def main():
    print("=" * 65)
    print("🎬 YOUTUBE SHORTS OAUTH2 JETON SİHİRBAZI")
    print("=" * 65)

    client_id = os.getenv("YOUTUBE_CLIENT_ID", "").strip()
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()

    if not client_id:
        client_id = input("\n🔑 Google Client ID'nizi yapıştırın: ").strip()
    else:
        print(f"\n🔑 Mevcut Client ID: {client_id[:15]}...")

    if not client_secret:
        client_secret = input("🔑 Google Client Secret'ınızı yapıştırın: ").strip()
    else:
        print(f"🔑 Mevcut Client Secret: {client_secret[:8]}...")

    if not client_id or not client_secret:
        print("\n❌ Client ID ve Client Secret boş bırakılamaz.")
        return

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

    print("\n🌐 Tarayıcıda yetkilendirme sayfası açılıyor...")
    print(f"🔗 Eğer otomatik açılmazsa bu linke tıklayın:\n{auth_url}\n")

    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    # Yerel dinleyici başlat
    print(f"⏳ Port {REDIRECT_PORT} üzerinde yanıt bekleniyor (Onay verildikten sonra otomatik kapanır)...")
    with socketserver.TCPServer(("localhost", REDIRECT_PORT), OAuthCallbackHandler) as httpd:
        while not OAuthCallbackHandler.auth_code:
            httpd.handle_request()

    code = OAuthCallbackHandler.auth_code
    print("✅ Yetki kodu alındı, kalıcı Refresh Token alınıyor...")

    # Token Takası
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    }

    res = requests.post(token_url, data=data, timeout=15)
    veri = res.json()

    refresh_token = veri.get("refresh_token")
    if not refresh_token:
        print(f"\n❌ Refresh Token alınamadı: {veri}")
        return

    print("\n🎉 TEBRİKLER! YouTube bağlantısı başarıyla sağlandı.")
    print(f"🔑 Refresh Token: {refresh_token[:15]}... (Gizli)")

    # .env Dosyasına Kaydet
    env_path = Path(".env")
    satirlar = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []

    yeni_anahtarlar = {
        "YOUTUBE_CLIENT_ID": client_id,
        "YOUTUBE_CLIENT_SECRET": client_secret,
        "YOUTUBE_REFRESH_TOKEN": refresh_token,
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

    print("\n📌 GİTHUB ACTIONS SECRET EKLEME (Canlı Sunucu İçin):")
    # ⚠️ GITHUB SECRET'I DA YAZ — YOKSA BOT CANLIDA ÖLÜ JETONLA KALIR.
    #
    # 4 Eyl 2026: YouTube jetonu öldü ve post gitmedi. Script jetonu
    # yalnızca `.env`'e yazıp kullanıcıya "şunları elle ekleyin" diyordu.
    # O adım atlanırsa yerelde her şey çalışır, ama Actions eski jetonu
    # kullanmaya devam eder ve arıza aynen sürer — üstelik "jetonu
    # yeniledim" diye yanlış güvenle.
    #
    # `gh` CLI şifrelemeyi kendisi hallediyor; PAT'in "Secrets: write"
    # izni zaten var (bkz. Adım 7).
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    yazildi = []
    try:
        from src.refresh_token import github_secret_guncelle
        repo = os.getenv("GITHUB_REPOSITORY", "ozdogangringo-sketch/haber-bot")
        for ad, deger in yeni_anahtarlar.items():
            if github_secret_guncelle(deger, repo, ad):
                yazildi.append(ad)
    except Exception as e:                            # noqa: BLE001
        print(f"⚠️  GitHub Secret yazılamadı: {type(e).__name__}: {e}")

    if len(yazildi) == len(yeni_anahtarlar):
        print("✅ GitHub Secrets OTOMATİK güncellendi:")
        for ad in yazildi:
            print(f"  • {ad}")
    else:
        eksik = [a for a in yeni_anahtarlar if a not in yazildi]
        print("⚠️  GitHub Secrets ELLE eklenmeli (gh CLI çalışmadı):")
        print("GitHub Deponuz -> Settings -> Secrets and variables -> Actions")
        for ad in eksik:
            print(f"  • {ad} = {yeni_anahtarlar[ad]}")

    print()
    print("⚠️  KALICI ÇÖZÜM İÇİN: Google Cloud Console -> OAuth consent")
    print("    screen -> PUBLISH APP. 'Testing' modunda kalan uygulamaların")
    print("    refresh jetonunu Google 7 GÜNDE iptal ediyor (4 Eyl 2026'da")
    print("    tam olarak bu yaşandı). Yayınlanmazsa jeton her hafta ölür.")
    print("=" * 65)


if __name__ == "__main__":
    main()
