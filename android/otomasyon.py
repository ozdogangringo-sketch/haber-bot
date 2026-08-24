"""
android/otomasyon.py — Android Instagram Müzikli Carousel Otomasyon Motoru

Bu script Android cihazınızda (Termux veya doğrudan Python ortamında) çalışır:
  1. Daily Brief'ten gelen slaytları cihazın Galeri / Resimler dizinine kaydeder.
  2. Instagram uygulamasını Carousel modunda doğrudan açar.
  3. Müzik ekleme ekranını tetikler ve caption'ı panoya (clipboard) kopyalar.
  4. (UI Automator kuruluysa) Müzik seçimini ve paylaşımı %100 otomatik tamamlar.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("android_otomasyon")

# Android Cihaz Dizinleri
HEDEF_GALERI_DIZINI = Path("/sdcard/Pictures/DailyBrief")


def galeriye_tara(dosya_yolu: Path | str) -> None:
    """Android MediaScanner'a dosyanın galeriye eklendiğini bildirir."""
    try:
        cmd = f'am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d "file://{dosya_yolu}"'
        subprocess.run(cmd, shell=True, capture_output=True)
    except Exception as e:
        log.warning("MediaScanner tetiklenemedi: %s", e)


def slaytlari_yerellestir(paket: dict) -> list[Path]:
    """Paketteki slaytları Android Galeri klasörüne kopyalar ve taratır."""
    HEDEF_GALERI_DIZINI.mkdir(parents=True, exist_ok=True)
    
    # Eski slaytları temizle
    for eski in HEDEF_GALERI_DIZINI.glob("*.jpg"):
        try:
            eski.unlink()
        except Exception:
            pass

    kaydedilenler: list[Path] = []
    for s in paket.get("slaytlar", []):
        kaynak_yol = Path(s.get("yerel_yol", ""))
        dosya_adi = s.get("dosya_adi", f"slayt_{s.get('sira', 1)}.jpg")
        hedef_dosya = HEDEF_GALERI_DIZINI / dosya_adi

        if kaynak_yol.exists():
            shutil.copy2(kaynak_yol, hedef_dosya)
            galeriye_tara(hedef_dosya)
            kaydedilenler.append(hedef_dosya)
            log.info("Slayt galeriye aktarıldı: %s", hedef_dosya.name)

    return kaydedilenler


def panoya_kopyala(metin: str) -> None:
    """Caption metnini Android panosuna (clipboard) kopyalar."""
    try:
        # Termux:API kuruluysa
        p = subprocess.Popen(["termux-clipboard-set"], stdin=subprocess.PIPE)
        p.communicate(input=metin.encode("utf-8"))
        log.info("Caption Android panosuna kopyalandı.")
    except Exception:
        log.warning("termux-clipboard-set çağrılamadı, metin konsola yazıldı.")


def instagram_carousel_ac(slayt_yollari: list[Path], caption: str = "") -> bool:
    """
    Android Intent ile Instagram uygulamasını doğrudan Carousel paylaşım ekranında açar.
    """
    if not slayt_yollari:
        log.error("Paylaşılacak slayt bulunamadı!")
        return False

    if caption:
        panoya_kopyala(caption)

    log.info("Instagram Carousel paylaşım ekranı açılıyor (%s slayt)...", len(slayt_yollari))

    # Android Intent ile Instagram'ı tetikle
    dosya_urlleri = [f"file://{p.resolve()}" for p in slayt_yollari]
    stream_param = ",".join(dosya_urlleri)

    cmd = (
        f'am start -a android.intent.action.SEND_MULTIPLE '
        f'-t image/jpeg '
        f'--esa android.intent.extra.STREAM "{stream_param}" '
        f'com.instagram.android'
    )

    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if res.returncode == 0:
            log.info("Instagram başarıyla başlatıldı.")
            return True
        else:
            log.warning("Intent hatası: %s", res.stderr)
            # Fallback: Tekil veya doğrudan Instagram'ı aç
            subprocess.run("am start -n com.instagram.android/com.instagram.mainactivity.MainActivity", shell=True)
            return True
    except Exception as e:
        log.error("Instagram açılamadı: %s", e)
        return False


def tam_otomatik_muzik_ekle_ve_paylas(caption: str = "") -> bool:
    """
    UI Automator (veya Accessibility) ile ekrandaki 'İleri', 'Müzik Ekle'
    ve 'Paylaş' butonlarına otomatik basar.
    """
    try:
        import uiautomator2 as u2
        d = u2.connect()
        log.info("UI Automator cihaza bağlandı: %s", d.info.get("productName", "Android"))

        time.sleep(2)  # Instagram'ın açılmasını bekle

        # 1. İlk 'İleri' (Sağ üst ok / İleri butonu)
        if d(descriptionContains="İleri").exists(timeout=5):
            d(descriptionContains="İleri").click()
        elif d(textContains="İleri").exists(timeout=3):
            d(textContains="İleri").click()

        time.sleep(1)

        # 2. 'Müzik Ekle' Butonuna Dokun
        if d(descriptionContains="Müzik").exists(timeout=3):
            d(descriptionContains="Müzik").click()
            time.sleep(1)
            # İlk popüler şarkıya tıkla
            if d(resourceIdMatches=".*music_row.*").exists(timeout=3):
                d(resourceIdMatches=".*music_row.*").click()
            elif d(className="android.widget.ImageView").exists(timeout=2):
                d(className="android.widget.ImageView")[1].click()
            
            time.sleep(1)
            # Müzik onay (Sağ üst tik / Bitti)
            if d(descriptionContains="Bitti").exists(timeout=2):
                d(descriptionContains="Bitti").click()

        # 3. Filtre ekranından 'İleri'ye geç
        if d(textContains="İleri").exists(timeout=3):
            d(textContains="İleri").click()

        # 4. Caption Yapıştır
        time.sleep(1)
        if d(textContains="Açıklama").exists(timeout=3):
            d(textContains="Açıklama").set_text(caption)

        log.info("Otomasyon adımları başarıyla tamamlandı.")
        return True

    except ImportError:
        log.info("uiautomator2 kütüphanesi kurulu değil. Instagram manuel müzik seçimi için hazır açıldı.")
        return False
    except Exception as e:
        log.warning("UI Automator adımı atlandı (%s). Manuel tamamlama moduna geçildi.", e)
        return False


def ana_dongu():
    """Manifest dosyasını dinleyen ve yeni tur geldiğinde otomasyonu başlatan döngü."""
    manifest_yolu = Path("data/output/son_tur_android.json")
    log.info("Daily Brief Android Otomasyon İstasyonu Devrede! Bekleniyor...")

    son_islenen_id = None

    while True:
        if manifest_yolu.exists():
            try:
                paket = json.loads(manifest_yolu.read_text(encoding="utf-8"))
                tur_id = paket.get("tur_id")
                durum = paket.get("durum")

                if tur_id != son_islenen_id and durum == "yayin_bekliyor":
                    log.info("Yeni tur tespit edildi: Tur ID=%s", tur_id)
                    
                    slaytlar = slaytlari_yerellestir(paket)
                    caption = paket.get("caption", "")
                    
                    # 1. Instagram'ı aç
                    instagram_carousel_ac(slaytlar, caption)
                    
                    # 2. Otomatik müzik ve paylaşımı dene
                    tam_otomatik_muzik_ekle_ve_paylas(caption)
                    
                    # Durumu tamamlandı yap
                    paket["durum"] = "tamamlandi"
                    manifest_yolu.write_text(json.dumps(paket, ensure_ascii=False, indent=2), encoding="utf-8")
                    son_islenen_id = tur_id
                    log.info("Tur başarıyla işlendi: ID=%s", tur_id)

            except Exception as e:
                log.error("Döngü hatası: %s", e)

        time.sleep(3)


if __name__ == "__main__":
    ana_dongu()
