"""
logo_indir.py — Kanal logolarını Wikimedia Commons'tan indirir.

NEDEN İNDİRİYORUZ, ÇİZMİYORUZ:
    Logolar önce Pillow ile elle çiziliyordu. Instagram/X/Facebook makul
    çıkıyordu ama Threads'inki hiçbir denemede tanınmadı — beş varyantın
    hepsi başka bir harfe benzedi ("3", "6", "B", "T"). Gerçek logolar
    hem doğru hem daha temiz duruyor.

LİSANS:
    Yalnızca KAMU MALI / CC0 sürümler seçildi. Bu logolar tescilli marka
    ama telif eşiğinin altında sayıldıkları için Commons'ta kamu malı
    etiketli. Kullanım biçimimiz de nominatif: "bizi bu kanallarda da
    bulabilirsiniz" diyoruz, markayı haberin öznesi yapmıyoruz.

    ⚠️ Bu, CLAUDE.md'deki "haberdeki kuruluşun logosu basılmaz" kuralına
    aykırı DEĞİL. O kural haber içeriği için; bunlar bizim kendi
    hesaplarımızın işaretleri.

ÇIKTI:
    assets/icons/<kanal>.png — tek renk siluet, alfa kanallı. Slaytta
    alfa maskesi olarak kullanılıp istenen renge boyanıyor.
    Repoya giriyor (bayrak önbelleği gibi), runner her seferinde
    indirmesin.

ÇALIŞTIRMA:
    python scripts/logo_indir.py
"""

import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import requests                                   # noqa: E402
from PIL import Image                             # noqa: E402

HEDEF = KOK / "assets" / "icons"
BOYUT = 256

# Commons dosya adları. Hepsi kamu malı sürüm — değiştirirsen lisansı
# tekrar doğrula, Commons'ta aynı logonun telifli sürümleri de var.
LOGOLAR = {
    "instagram": "File:Instagram simple icon.svg",
    "x":         "File:X logo 2023.svg",
    "threads":   "File:Threads (app) logo.svg",
    # ⚠️ "green" adı yanıltıcı ama doğru dosya bu: yalnızca "f" harfini
    # içeriyor, arka planı ŞEFFAF. Mavi daireli sürümlerde ("f logo
    # (2019)", "2021 Facebook icon") alfa kanalı dairenin tamamını
    # kaplıyor ve maske olarak kullanınca ekrana DOLU DAİRE basılıyor —
    # denendi, "f" hiç görünmedi. Rengi zaten biz veriyoruz.
    "facebook":  "File:Facebook f logo green.svg",
}

OTURUM = requests.Session()
# Wikimedia iletişim bilgisi içeren User-Agent istiyor, yoksa 429.
OTURUM.headers["User-Agent"] = "haber-bot/1.0 (ozdogandogukan@gmail.com)"


def _thumb_url(baslik: str) -> tuple[str, str]:
    """Commons dosyasının PNG önizleme adresini ve lisansını döner."""
    cevap = OTURUM.get(
        "https://commons.wikimedia.org/w/api.php",
        params={"action": "query", "format": "json", "titles": baslik,
                "prop": "imageinfo", "iiprop": "url|extmetadata",
                "iiurlwidth": BOYUT},
        timeout=30,
    )
    sayfalar = cevap.json().get("query", {}).get("pages", {})
    sayfa = list(sayfalar.values())[0]
    if "imageinfo" not in sayfa:
        raise RuntimeError(f"Commons'ta bulunamadı: {baslik}")
    bilgi = sayfa["imageinfo"][0]
    lisans = (bilgi.get("extmetadata", {})
                   .get("LicenseShortName", {}).get("value", "?"))
    return bilgi["thumburl"], lisans


def indir(ad: str, baslik: str) -> Path:
    url, lisans = _thumb_url(baslik)
    if "ublic domain" not in lisans and "CC0" not in lisans:
        raise RuntimeError(f"{ad}: lisans uygun değil ({lisans})")

    HEDEF.mkdir(parents=True, exist_ok=True)
    yol = HEDEF / f"{ad}.png"
    yol.write_bytes(OTURUM.get(url, timeout=30).content)

    # ⚠️ ASIL TEHLİKE ALFANIN YOKLUĞU DEĞİL, DOLU OLMASI.
    # Logoyu alfa maskesi olarak basıyoruz. Mavi daire + beyaz "f" gibi
    # bir logoda alfa dairenin TAMAMINI kaplıyor ve ekrana içi boş bir
    # daire değil, DOLU DAİRE basılıyor — harf hiç görünmüyor. Facebook'ta
    # tam olarak bu oldu. Doluluk oranına bakmak bunu yakalıyor.
    #
    # (Dosya `P` modunda gelebiliyor; alfa ancak RGBA'ya çevirince
    #  ortaya çıkıyor, ham moda bakmak yanıltıcı.)
    gorsel = Image.open(yol).convert("RGBA")
    alfa = gorsel.split()[-1]
    dolu = sum(1 for p in alfa.tobytes() if p > 200) / (gorsel.width * gorsel.height)
    if dolu > 0.90:
        raise RuntimeError(
            f"{ad}: alfa %{dolu * 100:.0f} dolu — maske olarak basılınca "
            f"logo değil dolu blok çıkar, şeffaf arka planlı sürüm gerekiyor"
        )

    print(f"  ✓ {ad:10} {gorsel.size[0]}x{gorsel.size[1]}  "
          f"doluluk %{dolu * 100:.0f}  {lisans}")
    return yol


def main() -> int:
    print("Kanal logoları indiriliyor (Wikimedia Commons):")
    hata = 0
    for ad, baslik in LOGOLAR.items():
        try:
            indir(ad, baslik)
        except Exception as e:
            print(f"  ✗ {ad:10} {e}")
            hata = 1
    return hata


if __name__ == "__main__":
    raise SystemExit(main())
