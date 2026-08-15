"""
refresh_token.py — ADIM 7
Instagram jetonunu süresi dolmadan yeniler.

NEDEN KRİTİK:
    Uzun ömürlü jeton 60 gün yaşıyor. Yenilenmezse bot bir sabah sessizce
    durur ve sebebi "her şey çalışıyordu" diye aranır. Bu, gözetimsiz
    çalışan bir sistemde en sinsi arıza türü.

NASIL YENİLENİYOR:
    Facebook'un `fb_exchange_token` akışı: elindeki geçerli uzun ömürlü
    jetonu verip yenisini alıyorsun, saat sıfırlanıyor. Jeton ÖLDÜKTEN
    sonra bu çalışmıyor — o yüzden erken davranıyoruz (varsayılan 10 gün
    kala). Ölmüş jetonu yenilemenin yolu yok, Graph API Explorer'dan
    elle almak gerekir.

YENİ JETON NEREYE YAZILIYOR:
    İki yere: `.env` (yerel çalıştırma) ve GitHub Actions Secrets (uzak).
    İkincisi olmadan bot yine durur — runner .env'i görmüyor.
"""

from __future__ import annotations

import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

log = logging.getLogger(__name__)
load_dotenv()

KOK = Path(__file__).resolve().parent.parent
ENV_YOLU = KOK / ".env"
TABAN = "https://graph.facebook.com"

# Kaç gün kala yenileyelim. 10 gün pay bırakıyoruz: haftalık cron
# kaçarsa bile bir sonraki denemede hâlâ vakit olsun.
ESIK_GUN = 10


def _gerekli(ad: str) -> str:
    d = os.getenv(ad, "").strip()
    if not d:
        raise RuntimeError(f"{ad} bulunamadı (.env veya GitHub Secrets)")
    return d


def jeton_durumu(ayarlar: dict) -> dict:
    """
    Jetonun geçerliliğini ve kalan gününü sorar.

    Döner: {'gecerli', 'kalan_gun', 'bitis', 'tur'}
    `kalan_gun` None ise jeton süresizdir (expires_at = 0).
    """
    surum = ayarlar["instagram"]["api_surumu"]
    jeton = _gerekli("IG_ACCESS_TOKEN")
    uygulama = f'{_gerekli("META_APP_ID")}|{_gerekli("META_APP_SECRET")}'

    cevap = requests.get(
        f"{TABAN}/{surum}/debug_token",
        params={"input_token": jeton, "access_token": uygulama},
        timeout=60,
    )
    cevap.raise_for_status()
    d = cevap.json().get("data", {})

    son = d.get("expires_at") or 0
    if son:
        bitis = datetime.fromtimestamp(son, timezone.utc)
        kalan = (bitis - datetime.now(timezone.utc)).days
    else:
        bitis, kalan = None, None

    return {
        "gecerli": bool(d.get("is_valid")),
        "kalan_gun": kalan,
        "bitis": bitis,
        "tur": d.get("type"),
    }


def jetonu_yenile(ayarlar: dict) -> str:
    """Yeni uzun ömürlü jetonu döner. Başaramazsa exception fırlatır."""
    surum = ayarlar["instagram"]["api_surumu"]
    cevap = requests.get(
        f"{TABAN}/{surum}/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": _gerekli("META_APP_ID"),
            "client_secret": _gerekli("META_APP_SECRET"),
            "fb_exchange_token": _gerekli("IG_ACCESS_TOKEN"),
        },
        timeout=60,
    )
    if cevap.status_code != 200:
        raise RuntimeError(f"jeton yenilenemedi: {cevap.text[:300]}")

    yeni = cevap.json().get("access_token", "").strip()
    if not yeni:
        raise RuntimeError(f"cevapta jeton yok: {str(cevap.json())[:200]}")
    return yeni


def env_guncelle(yeni: str) -> bool:
    """Yerel .env dosyasını günceller. Actions'ta .env yok, False döner."""
    if not ENV_YOLU.exists():
        return False
    satirlar = ENV_YOLU.read_text(encoding="utf-8").splitlines()
    for i, satir in enumerate(satirlar):
        if satir.split("=", 1)[0].strip() == "IG_ACCESS_TOKEN":
            satirlar[i] = f"IG_ACCESS_TOKEN={yeni}"
            ENV_YOLU.write_text("\n".join(satirlar) + "\n", encoding="utf-8")
            return True
    return False


def github_secret_guncelle(yeni: str, repo: str) -> bool:
    """
    Yeni jetonu GitHub Actions Secrets'a yazar.

    `gh` CLI kullanıyoruz: şifrelemeyi (libsodium) kendisi hallediyor,
    elle uğraşmaya gerek yok. Jeton stdin'den veriliyor — komut satırı
    argümanı olarak geçirilse süreç listesinde görünürdü.

    Bunun çalışması için PAT'in "Secrets: write" izni olmalı. Yoksa
    False dönüyor ve çağıran taraf uyarı gönderiyor — sessizce
    başarısız olmak, jetonun ölmesi demek.
    """
    try:
        sonuc = subprocess.run(
            ["gh", "secret", "set", "IG_ACCESS_TOKEN", "--repo", repo],
            input=yeni, text=True, capture_output=True, timeout=120,
        )
        if sonuc.returncode == 0:
            return True
        log.error("gh secret set başarısız: %s", sonuc.stderr.strip()[:300])
    except FileNotFoundError:
        log.error("gh CLI bulunamadı")
    except Exception as e:
        log.error("secret güncellenemedi: %s", e)
    return False
