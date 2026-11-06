#!/usr/bin/env python3
"""
scripts/tiktok_token_al.py — TikTok Production OAuth Token Değişim ve Kayıt Scripti.

Kullanım:
    .venv/bin/python scripts/tiktok_token_al.py --code "<TIKTOK_AUTH_CODE>" [--verifier "<PKCE_VERIFIER>"]
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("tiktok_token_al")

TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
REDIRECT_URI = "https://dailybrief.ozbornstudio.com/callback"


def token_al_ve_kaydet(code: str, verifier: str | None = None) -> bool:
    client_key = os.getenv("TIKTOK_CLIENT_KEY", "").strip() or "awkfxqrn4j2m603e"
    client_secret = os.getenv("TIKTOK_CLIENT_SECRET", "").strip()

    if not client_key or not client_secret:
        log.error("TIKTOK_CLIENT_KEY veya TIKTOK_CLIENT_SECRET eksik!")
        return False

    code = code.strip()
    if "code=" in code:
        import urllib.parse
        parsed = urllib.parse.urlparse(code)
        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [code])[0]

    log.info("TikTok token değişim isteği gönderiliyor (Client Key: %s)...", client_key)

    data = {
        "client_key": client_key,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    }
    if verifier:
        data["code_verifier"] = verifier

    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    try:
        res = requests.post(TOKEN_URL, headers=headers, data=data, timeout=15)
        veri = res.json()
    except Exception as e:
        log.error("TikTok token isteği başarısız: %s", e)
        return False

    access_token = veri.get("data", {}).get("access_token") or veri.get("access_token")
    refresh_token = veri.get("data", {}).get("refresh_token") or veri.get("refresh_token")
    open_id = veri.get("data", {}).get("open_id") or veri.get("open_id")
    scope = veri.get("data", {}).get("scope") or veri.get("scope")
    expires_in = veri.get("data", {}).get("expires_in") or veri.get("expires_in")

    if not access_token or not refresh_token:
        log.error("Token alınamadı! Yanıt: %s (Status: %s)", veri, res.status_code)
        return False

    log.info("🎉 Başarılı! TikTok Production jetonları alındı.")
    log.info("Open ID: %s", open_id)
    log.info("Kapsam (Scopes): %s", scope)
    log.info("Geçerlilik süresi: %s sn", expires_in)

    # 1. .env güncelle
    env_file = Path(".env")
    if env_file.exists():
        metin = env_file.read_text(encoding="utf-8")
        if "TIKTOK_ACCESS_TOKEN=" in metin:
            metin = re.sub(r"TIKTOK_ACCESS_TOKEN=.*", f"TIKTOK_ACCESS_TOKEN={access_token}", metin)
        else:
            metin += f"\nTIKTOK_ACCESS_TOKEN={access_token}\n"

        if "TIKTOK_REFRESH_TOKEN=" in metin:
            metin = re.sub(r"TIKTOK_REFRESH_TOKEN=.*", f"TIKTOK_REFRESH_TOKEN={refresh_token}", metin)
        else:
            metin += f"\nTIKTOK_REFRESH_TOKEN={refresh_token}\n"

        env_file.write_text(metin, encoding="utf-8")
        log.info("✅ .env dosyası güncellendi.")

    # 2. SQLite ayarlar güncelle
    try:
        import sqlite3
        con = sqlite3.connect("data/haber.db")
        con.execute(
            "INSERT INTO ayarlar (anahtar, deger) VALUES ('tiktok_access_token', ?) "
            "ON CONFLICT(anahtar) DO UPDATE SET deger = excluded.deger",
            (access_token,),
        )
        con.execute(
            "INSERT INTO ayarlar (anahtar, deger) VALUES ('tiktok_refresh_token', ?) "
            "ON CONFLICT(anahtar) DO UPDATE SET deger = excluded.deger",
            (refresh_token,),
        )
        con.commit()
        con.close()
        log.info("✅ data/haber.db güncellendi.")
    except Exception as e:
        log.warning("DB güncellenirken uyarı: %s", e)

    # 3. GitHub Secrets güncelle
    for secret_name, secret_val in [("TIKTOK_ACCESS_TOKEN", access_token), ("TIKTOK_REFRESH_TOKEN", refresh_token)]:
        try:
            res_gh = subprocess.run(
                ["gh", "secret", "set", secret_name, "-b", secret_val],
                capture_output=True,
                text=True,
                check=True,
            )
            log.info("✅ GitHub Secret güncellendi: %s", secret_name)
        except Exception as e:
            log.warning("GitHub secret %s güncellenemedi: %s", secret_name, e)

    # 4. TikTok API Canlı Testi (Creator Info)
    try:
        test_url = "https://open.tiktokapis.com/v2/post/publish/creator_info/query/"
        r_test = requests.post(
            test_url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json={},
            timeout=10,
        )
        test_res = r_test.json()
        log.info("TikTok Creator Info Testi Yanıtı: %s", test_res)
        if test_res.get("data", {}).get("creator_nickname"):
            nick = test_res["data"]["creator_nickname"]
            log.info("🚀 TikTok Hesabı Doğrulandı: @%s", nick)
    except Exception as e:
        log.warning("Creator info testinde hata: %s", e)

    return True


def main():
    parser = argparse.ArgumentParser(description="TikTok Production OAuth Token Alıcı")
    parser.add_argument("--code", required=True, help="TikTok'tan dönen yetkilendirme kodu")
    parser.add_argument("--verifier", required=False, default=None, help="PKCE Verifier (varsa)")
    args = parser.parse_args()

    basari = token_al_ve_kaydet(args.code, args.verifier)
    sys.exit(0 if basari else 1)


if __name__ == "__main__":
    main()
