"""
Görsel barındırıcı adaylarını ÇALIŞTIĞI ORTAMDAN test eder.

⚠️ YERELDE TEST ETMEK YANILTICI. 21 Ağu 2026: catbox.moe ev
bağlantısından sorunsuz çalıştı, GitHub runner'dan `HTTP 412 Invalid
uploader` verdi — veri merkezi IP'lerini engelliyor. Bir barındırıcıyı
yedek olarak eklemeden önce BU SCRIPT Actions'ta çalıştırılmalı.

Ölçtüğü şey: yükleme başarılı mı VE dönen URL Instagram'ın kullandığı
User-Agent ile indirilebiliyor mu (Instagram görseli kendisi çekiyor).
"""
import io
import sys
import time

import requests
from PIL import Image

# Instagram görseli bu User-Agent ile indiriyor; barındırıcı bunu
# engelliyorsa URL bizim için işe yaramaz.
IG_UA = "facebookexternalhit/1.1"
ZAMAN = 45


def _gorsel() -> bytes:
    im = Image.new("RGB", (1080, 1350), (24, 20, 52))
    t = io.BytesIO()
    im.save(t, "JPEG", quality=90)
    return t.getvalue()


def _erisilebilir(url: str) -> str:
    try:
        r = requests.get(url, headers={"User-Agent": IG_UA}, timeout=ZAMAN)
        tip = r.headers.get("content-type", "")
        if r.status_code == 200 and r.content[:3] == b"\xff\xd8\xff":
            return f"✓ indirilebiliyor ({len(r.content)//1024} KB, {tip})"
        return f"✗ HTTP {r.status_code} tip={tip}"
    except Exception as e:                            # noqa: BLE001
        return f"✗ {type(e).__name__}"


def catbox(ham):
    r = requests.post("https://catbox.moe/user/api.php",
                      data={"reqtype": "fileupload"},
                      files={"fileToUpload": ("s.jpg", ham, "image/jpeg")},
                      timeout=ZAMAN)
    if r.status_code != 200 or not r.text.startswith("http"):
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:80]}")
    return r.text.strip()


def tmpfiles(ham):
    r = requests.post("https://tmpfiles.org/api/v1/upload",
                      files={"file": ("s.jpg", ham, "image/jpeg")},
                      timeout=ZAMAN)
    u = r.json()["data"]["url"]
    # tmpfiles indirme için /dl/ yolu istiyor
    return u.replace("tmpfiles.org/", "tmpfiles.org/dl/")


def uguu(ham):
    r = requests.post("https://uguu.se/upload",
                      files={"files[]": ("s.jpg", ham, "image/jpeg")},
                      timeout=ZAMAN)
    return r.json()["files"][0]["url"]


def litterbox(ham):
    r = requests.post("https://litterbox.catbox.moe/resources/internals/api.php",
                      data={"reqtype": "fileupload", "time": "24h"},
                      files={"fileToUpload": ("s.jpg", ham, "image/jpeg")},
                      timeout=ZAMAN)
    if not r.text.startswith("http"):
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:80]}")
    return r.text.strip()


def main() -> int:
    ham = _gorsel()
    print(f"test görseli: {len(ham)//1024} KB\n")
    print(f"{'barındırıcı':<14}{'yükleme':<40}erişim (Instagram UA)")
    print("-" * 96)
    calisan = []
    for ad, islev in (("catbox", catbox), ("tmpfiles", tmpfiles),
                      ("uguu", uguu), ("litterbox", litterbox)):
        b = time.time()
        try:
            url = islev(ham)
            sure = time.time() - b
            erisim = _erisilebilir(url)
            print(f"{ad:<14}✓ {sure:4.1f}s {url[:32]:<33}{erisim}")
            if erisim.startswith("✓"):
                calisan.append(ad)
        except Exception as e:                        # noqa: BLE001
            print(f"{ad:<14}✗ {str(e)[:70]}")
    print("-" * 96)
    print(f"KULLANILABİLİR: {', '.join(calisan) if calisan else 'HİÇBİRİ'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
