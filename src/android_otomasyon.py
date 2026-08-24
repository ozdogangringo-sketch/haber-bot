"""
src/android_otomasyon.py — Samsung Galaxy A05 Tam Otomatik Instagram Paylaşım Motoru

Bu modül ADB ve UIAutomator2 üzerinden:
  1. Wi-Fi (Kablosuz) veya USB ile Samsung cihaza bağlanır.
  2. Yeni turun slaytlarını telefonun galerisine (/sdcard/Pictures/DailyBrief) aktarır.
  3. Instagram uygulamasını açar.
  4. Slaytları sırasıyla seçer.
  5. Trend/önerilen arka plan müziğini bağlar.
  6. Açıklama metnini (caption) yazar.
  7. 'Paylaş' butonuna basarak canlı yayını tamamlar.
"""

import logging
import os
import subprocess
import time
from pathlib import Path
try:
    import uiautomator2 as u2
except ImportError:
    u2 = None

log = logging.getLogger(__name__)

# Varsayılan ADB yolu
ADB_BIN = "/Users/macbook/Library/Android/sdk/platform-tools/adb"
DEFAULT_IP = "192.168.0.112:5555"
DEFAULT_SERIAL = "R96X200KERL"


def cihaza_baglan() -> Optional["u2.Device"]:
    """
    Samsung cihaza önce Wi-Fi (192.168.0.112:5555), olmazsa USB üzerinden bağlanır.
    """
    if u2 is None:
        log.warning("uiautomator2 kütüphanesi kurulu değil, Android otomasyonu atlanıyor.")
        return None

    # 1. Wi-Fi üzerinden ADB bağlantısını dene
    try:
        subprocess.run([ADB_BIN, "connect", DEFAULT_IP], capture_output=True, timeout=5)
    except Exception as e:
        log.warning("Wi-Fi ADB connect denemesi: %s", e)

    # 2. uiautomator2 ile bağlan
    for hedef in [DEFAULT_IP, DEFAULT_SERIAL, None]:
        try:
            if hedef:
                d = u2.connect(hedef)
            else:
                d = u2.connect()
            info = d.info
            if info and "productName" in info:
                log.info("✅ Samsung cihaza bağlanıldı: %s (hedef: %s)", info.get("productName"), hedef)
                return d
        except Exception as e:
            log.debug("Bağlantı denemesi (%s) başarısız: %s", hedef, e)

    log.error("❌ Samsung cihaza bağlanılamadı. Cihaz açık ve aynı Wi-Fi ağında mı?")
    return None


def slaytlari_telefona_aktar(d: u2.Device, slayt_yollari: list[Path]) -> list[str]:
    """
    Slayt dosyalarını telefonun /sdcard/Pictures/DailyBrief klasörüne aktarır ve galeriye işletir.
    """
    hedef_klasor = "/sdcard/Pictures/DailyBrief"
    
    # Klasörü temizle ve yeniden oluştur
    subprocess.run([ADB_BIN, "shell", f"mkdir -p {hedef_klasor}"], check=True)
    subprocess.run([ADB_BIN, "shell", f"rm -f {hedef_klasor}/*.jpg"], check=True)

    aktarilanlar = []
    for idx, dosya in enumerate(slayt_yollari, start=1):
        if not dosya.exists():
            continue
        hedef_dosya = f"{hedef_klasor}/{idx:02d}_slayt.jpg"
        subprocess.run([ADB_BIN, "push", str(dosya), hedef_dosya], check=True, capture_output=True)
        # MediaScanner'a bildir (Galeri hemen görsün)
        subprocess.run(
            [ADB_BIN, "shell", f'am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d "file://{hedef_dosya}"'],
            check=True,
            capture_output=True,
        )
        aktarilanlar.append(hedef_dosya)
        log.info("Slayt telefona yüklendi: %s -> %s", dosya.name, hedef_dosya)

    time.sleep(1)
    return aktarilanlar


def instagram_otomatik_paylas(
    slayt_yollari: list[Path],
    caption_metni: str,
    reel_olarak: bool = True,
) -> bool:
    """
    Slaytları telefona yükler ve Instagram'da müzikli olarak tam otomatik paylaşır.
    """
    d = cihaza_baglan()
    if not d:
        return False

    # 1. Ekranı uyandır ve kilidi aç (varsa)
    d.screen_on()
    d.unlock()
    time.sleep(0.5)

    # 2. Slaytları telefona aktar
    aktarilan = slaytlari_telefona_aktar(d, slayt_yollari)
    if not aktarilan:
        log.error("Aktarılacak geçerli slayt bulunamadı.")
        return False

    slayt_sayisi = len(aktarilan)
    log.info("%s adet slayt Instagram için hazırlandı.", slayt_sayisi)

    # 3. Instagram uygulamasını sıfırdan aç
    d.app_stop("com.instagram.android")
    time.sleep(0.5)
    d.app_start("com.instagram.android")
    time.sleep(2)

    # 4. Sol üstteki '+' (Oluştur) butonuna bas
    if d(descriptionContains="Oluştur").exists(timeout=3):
        d(descriptionContains="Oluştur").click()
    elif d(descriptionContains="Yeni gönderi").exists(timeout=3):
        d(descriptionContains="Yeni gönderi").click()
    elif d(descriptionContains="Create").exists(timeout=3):
        d(descriptionContains="Create").click()
    else:
        # Standart sol üst '+' koordinatı (720x1600 için x=60, y=110)
        d.click(60, 110)

    time.sleep(2)

    # İzin pop-up'ı gelirse onayla
    if d(text="Tümüne izin ver").exists(timeout=2):
        d(text="Tümüne izin ver").click()
        time.sleep(1)

    # 5. REELS modunu seç (eğer isteniyorsa)
    if reel_olarak and d(text="REELS").exists(timeout=2):
        d(text="REELS").click()
        time.sleep(1.5)

    # 6. 'Seç' (Çoklu seçim) butonuna bas
    if d(text="Seç").exists(timeout=2):
        d(text="Seç").click()
    elif d(descriptionContains="Seç").exists(timeout=2):
        d(descriptionContains="Seç").click()
    time.sleep(1)

    # 7. Slaytları sırasıyla seç (İlk satırdaki kutucuklar)
    d.click(270, 635)  # Seçimi sıfırla
    time.sleep(0.3)
    d.click(450, 635)  # 1. Slayt
    time.sleep(0.3)
    d.click(630, 635)  # 2. Slayt
    time.sleep(0.3)

    if slayt_sayisi > 2:
        d.click(90, 815)   # 3. Slayt
        time.sleep(0.3)
    if slayt_sayisi > 3:
        d.click(270, 815)  # 4. Slayt
        time.sleep(0.3)
    if slayt_sayisi > 4:
        d.click(450, 815)  # 5. Slayt
        time.sleep(0.3)
    if slayt_sayisi > 5:
        d.click(630, 815)  # 6. Slayt
        time.sleep(0.3)

    # 8. Sağ üstteki 'İleri' butonuna bas
    if d(text="İleri").exists(timeout=2):
        d(text="İleri").click()
    time.sleep(2.5)

    # 9. Müzik / Düzenleme ekranındaki 'İleri' butonuna bas (Önerilen trend ses otomatik seçilir)
    if d(text="İleri").exists(timeout=3):
        d(text="İleri").click()
    time.sleep(2)

    # İlk defa paylaşım uyarısı pop-up'ı (Tamam)
    if d(text="Tamam").exists(timeout=2):
        d(text="Tamam").click()
        time.sleep(1)

    # 10. Açıklama metnini yaz
    d.click(200, 225)  # Açıklama kutusu
    time.sleep(0.5)
    d.send_keys(caption_metni[:800])
    time.sleep(1)

    # Klavyeyi kapat (Done / Tamam)
    if d(text="Done").exists(timeout=1):
        d(text="Done").click()
    elif d(text="Tamam").exists(timeout=1):
        d(text="Tamam").click()
    d.press("back")
    time.sleep(1)

    # 11. 'Paylaş' butonuna bas
    if d(text="Paylaş").exists(timeout=2):
        d(text="Paylaş").click()
        log.info("🎉 Instagram'da 'Paylaş' butonuna başarıyla basıldı!")
    else:
        d.click(360, 915)  # Mavi Paylaş butonu koordinatı
        log.info("🎉 Koordinat ile 'Paylaş' butonuna basıldı!")

    time.sleep(6)
    try:
        d.screen_off()  # İşlem bitince ekranı kapatıp uykuya al
        log.info("Ekran kapatıldı, cihaz uykuya alındı.")
    except Exception:
        pass

    log.info("✅ Samsung otomasyonu ile paylaşım tamamlandı.")
    return True
