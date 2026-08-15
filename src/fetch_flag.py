"""
fetch_flag.py — Slaytın sağ üstündeki ülke bayrağını sağlar.

NEDEN DOSYA, EMOJİ DEĞİL:
    Bayrak emojisi (🇹🇷) en kolay yol gibi görünüyor ama Pillow'un emojiyi
    RENKLİ basması için renkli emoji fontu gerekiyor. macOS'ta var
    (Apple Color Emoji), GitHub Actions runner'ında YOK — orada bayrak
    ya kutu ya da iki harf olarak çıkardı. Yayın ortamında çalışmayan
    bir çözüm, çözüm değil.

NEDEN ÖNBELLEK:
    flagcdn.com ücretsiz ve anahtarsız, ama her turda 10 slayt için 10
    istek atmanın anlamı yok. İndirilen bayrak `assets/flags/` altına
    yazılıyor ve repoya commit ediliyor; ikinci turdan sonra ağ hiç
    kullanılmıyor. Aynı zamanda flagcdn bir gün kapanırsa elimizde
    kalmış oluyor.

BAYRAK BULUNAMAZSA:
    None döner ve slayt bayraksız basılır. Bayrak süs; yokluğu postu
    engellememelidir.
"""

from __future__ import annotations

import io
import logging
import re
from pathlib import Path

import requests
from PIL import Image

log = logging.getLogger(__name__)

KOK = Path(__file__).resolve().parent.parent
KLASOR = KOK / "assets" / "flags"

# w160 = 160 piksel genişlik. Slaytta ~76 piksel basıyoruz; iki katı
# indirmek küçültünce kenarların temiz kalmasını sağlıyor.
CDN = "https://flagcdn.com/w160/{kod}.png"
ZAMAN_ASIMI = 20

# Ülke olmayan ama bayrağı olan kuruluşlar.
#
# Neden ayrı liste: flagcdn yalnızca ISO ülke kodlarını biliyor, NATO'nun
# ya da BM'nin bayrağı orada yok. Bunları Wikimedia Commons'ın FilePath
# uç noktasından çekiyoruz — SVG'yi istediğimiz boyutta PNG'ye çevirip
# veriyor. Hepsi kamu malı ya da serbest lisanslı kurumsal bayraklar.
#
# LİSTE BİLEREK KISA: buraya spor kulübü, şirket ya da parti logosu
# EKLEME. Onlar tescilli marka; bir haber görselinin köşesinde kullanmak
# telif/marka sorunu doğurur ve zaten haber sitesi fotoğrafını
# kullanmama kararımızla aynı gerekçeye takılır.
KURULUSLAR = {
    "nato": "Flag of NATO.svg",
    "un": "Flag of the United Nations.svg",
    "eu": "Flag of Europe.svg",
    "who": "Flag of WHO.svg",
    "unesco": "Flag of UNESCO.svg",
    "unicef": "Flag of UNICEF.svg",
    "opec": "Flag of OPEC.svg",
    "africanunion": "Flag of the African Union.svg",
    "arableague": "Flag of the Arab League.svg",
    "commonwealth": "Flag of the Commonwealth of Nations.svg",
    "oic": "Flag of the Organisation of Islamic Cooperation.svg",
    "redcross": "Flag of the Red Cross.svg",
}

COMMONS_DOSYA = (
    "https://commons.wikimedia.org/wiki/Special:FilePath/{dosya}?width=160"
)


def _kod_gecerli_mi(kod: str) -> bool:
    """
    İki harfli ISO ülke koduna veya tanıdığımız bir kuruluş adına izin ver.

    Bu bir güvenlik kontrolü: kod Gemini'den geliyor ve doğrudan hem URL'ye
    hem dosya yoluna giriyor. Doğrulamazsak "../../.env" gibi bir değer
    dosya yolundan çıkabilir. Kuruluşlar sabit listeden geldiği için
    onlarda böyle bir risk yok.
    """
    return bool(re.fullmatch(r"[a-z]{2}", kod)) or kod in KURULUSLAR


def bayrak_al(ulke_kodu: str) -> Image.Image | None:
    """
    Ülke bayrağını Pillow görüntüsü olarak döner. Bulamazsa None.

    Önce yerel önbelleğe bakar, yoksa flagcdn'den indirip kaydeder.
    """
    kod = (ulke_kodu or "").strip().lower()
    if not _kod_gecerli_mi(kod):
        if kod:
            log.warning("geçersiz ülke kodu, bayrak atlanıyor: %r", ulke_kodu)
        return None

    yerel = KLASOR / f"{kod}.png"
    if yerel.exists():
        try:
            return Image.open(yerel).convert("RGBA")
        except Exception as e:
            log.warning("önbellekteki bayrak okunamadı (%s): %s", kod, e)
            yerel.unlink(missing_ok=True)   # bozuk dosyayı at, yeniden indir

    if kod in KURULUSLAR:
        url = COMMONS_DOSYA.format(dosya=KURULUSLAR[kod].replace(" ", "_"))
        # Commons kim olduğumuzu bildiren bir User-Agent istiyor, yoksa 403
        baslik = {"User-Agent": "haber-bot/1.0 (ozdogangringo@gmail.com)"}
    else:
        url, baslik = CDN.format(kod=kod), {}

    try:
        cevap = requests.get(url, headers=baslik, timeout=ZAMAN_ASIMI)
        cevap.raise_for_status()
        gorsel = Image.open(io.BytesIO(cevap.content)).convert("RGBA")
    except Exception as e:
        log.warning("bayrak indirilemedi (%s): %s", kod, e)
        return None

    try:
        KLASOR.mkdir(parents=True, exist_ok=True)
        gorsel.save(yerel, "PNG")
    except Exception as e:
        # Kaydedemedik ama görsel elimizde — turu bunun için durdurmayalım
        log.warning("bayrak önbelleğe yazılamadı (%s): %s", kod, e)

    return gorsel
