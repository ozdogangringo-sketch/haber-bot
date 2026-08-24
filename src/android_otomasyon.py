"""
src/android_otomasyon.py — Samsung Galaxy A05 Tam Otomatik Instagram Reels & Carousel Paylaşım Motoru

Bu modül:
  1. Samsung cihaza Wi-Fi (192.168.0.112:5555) veya USB ile bağlanır.
  2. Slaytları telefonun /sdcard/Pictures/DailyBrief klasörüne doğru sıra ile aktarır.
  3. Instagram'da 'REELS' modunu açar ve 'Çoklu Seçim' ile tüm slaytları 1-2-3.. sırasıyla seçer.
  4. 'Ses' menüsünden trend müziği bağlar.
  5. Caption metnini güvenle yapıştırır.
  6. 'Paylaş' butonuna basarak canlıya alır ve işlem bitince ekranı kapatıp uykuya geçirir.
"""

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

try:
    import uiautomator2 as u2
except ImportError:
    u2 = None

log = logging.getLogger(__name__)

ADB_BIN = "/Users/macbook/Library/Android/sdk/platform-tools/adb"
DEFAULT_SERIAL = "R96X200KERL"
DEFAULT_IP = "192.168.0.112:5555"


def cihaza_baglan() -> Optional["u2.Device"]:
    """
    Samsung cihaza önce USB (R96X200KERL), olmazsa Wi-Fi (192.168.0.112:5555) üzerinden bağlanır.
    """
    if u2 is None:
        log.warning("uiautomator2 kütüphanesi kurulu değil, Android otomasyonu atlanıyor.")
        return None

    # Önce USB serial, sonra Wi-Fi, sonra varsayılan cihazı dene
    for hedef in [DEFAULT_SERIAL, DEFAULT_IP, None]:
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

    # Wi-Fi ADB connect dene ve tekrar dene
    try:
        subprocess.run([ADB_BIN, "connect", DEFAULT_IP], capture_output=True, timeout=5)
        d = u2.connect(DEFAULT_IP)
        if d.info:
            return d
    except Exception:
        pass

    log.error("❌ Samsung cihaza bağlanılamadı. Cihaz açık ve bağlı mı?")
    return None


def slaytlari_telefona_aktar(target: str, slayt_yollari: list[Path]) -> list[str]:
    """
    Slayt dosyalarını telefonun /sdcard/DCIM/Camera klasörüne aktarır ve galeriye işletir.
    """
    hedef_klasor = "/sdcard/DCIM/Camera"
    
    cmd_prefix = [ADB_BIN]
    if target:
        cmd_prefix.extend(["-s", target])

    # Eski geçici slaytları temizle
    subprocess.run(cmd_prefix + ["shell", f"rm -f {hedef_klasor}/DailyBrief_*.jpg"], check=True, capture_output=True)

    aktarilanlar = []
    for idx, dosya in enumerate(slayt_yollari, start=1):
        if not dosya.exists():
            continue
        hedef_dosya = f"{hedef_klasor}/DailyBrief_{idx:02d}.jpg"
        subprocess.run(cmd_prefix + ["push", str(dosya), hedef_dosya], check=True, capture_output=True)
        subprocess.run(
            cmd_prefix + ["shell", f'am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d "file://{hedef_dosya}"'],
            check=True,
            capture_output=True,
        )
        aktarilanlar.append(hedef_dosya)
        log.info("Slayt telefona yüklendi: %s -> %s", dosya.name, hedef_dosya)

    time.sleep(1.5)
    return aktarilanlar


def instagram_otomatik_paylas(
    slayt_yollari: list[Path],
    caption_metni: str,
    reel_olarak: bool = True,
) -> bool:
    """
    Slaytları telefona yükler ve Instagram'da Reels / Çoklu seçim / Müzikli olarak paylaşır.
    """
    d = cihaza_baglan()
    if not d:
        return False

    target = DEFAULT_IP

    # 1. Ekranı uyandır ve kilidi aç
    d.screen_on()
    d.unlock()
    time.sleep(0.5)

    # 2. Slaytları telefona aktar
    aktarilan = slaytlari_telefona_aktar(target, slayt_yollari)
    if not aktarilan:
        log.error("Aktarılacak geçerli slayt bulunamadı.")
        return False

    slayt_sayisi = len(aktarilan)
    log.info("%s adet slayt Instagram için hazırlandı.", slayt_sayisi)

    # 3. Instagram uygulamasını sıfırdan aç
    d.app_stop("com.instagram.android")
    time.sleep(0.5)
    d.app_start("com.instagram.android")
    time.sleep(2.5)

    # Kamera ayarı açıksa 'Bitti' de
    if d(text="Bitti").exists(timeout=1):
        d(text="Bitti").click()

    # 4. Sol üstteki '+' (Oluştur) butonuna bas
    d.click(60, 100)
    time.sleep(2)

    # Pop-up 1: Taslak uyarısı
    if d(textContains="Yeni video").exists(timeout=2):
        d(textContains="Yeni video").click()
        time.sleep(1.5)

    # Pop-up 2: İzinler
    if d(text="Tümüne izin ver").exists(timeout=2):
        d(text="Tümüne izin ver").click()
        time.sleep(1)

    # Kamera açıldıysa sol alttaki Galeri Karesine tıkla (x=90, y=1450)
    if d(textContains="REELS").exists(timeout=1) and not d(text="Seç").exists(timeout=1) and not d(text="Yakınlardakiler").exists(timeout=1):
        d.click(90, 1450)
        time.sleep(2)

    # 5. 'Seç' (Çoklu seçim) butonuna bas
    if d(text="Seç").exists(timeout=2):
        d(text="Seç").click()
    elif d(descriptionContains="Seç").exists(timeout=2):
        d(descriptionContains="Seç").click()
    time.sleep(1)

    # 6. Slaytları sırasıyla seç (DCIM/Camera en başı)
    log.info("Slaytlar sırayla seçiliyor (toplam %s)...", slayt_sayisi)
    # 1. Sütun Kamera, 2. Sütun Slayt 1, 3. Sütun Slayt 2, 2. Satır 1. Sütun Slayt 3
    if slayt_sayisi == 1:
        d.click(480, 280)
    elif slayt_sayisi == 2:
        d.click(480, 280)
        time.sleep(0.3)
        d.click(640, 280)
    elif slayt_sayisi == 3:
        d.click(480, 280)
        time.sleep(0.3)
        d.click(640, 280)
        time.sleep(0.3)
        d.click(100, 520)
    elif slayt_sayisi >= 4:
        d.click(480, 280)
        time.sleep(0.3)
        d.click(640, 280)
        time.sleep(0.3)
        d.click(100, 520)
        time.sleep(0.3)
        d.click(320, 520)
        if slayt_sayisi >= 5:
            time.sleep(0.3)
            d.click(540, 520)
        if slayt_sayisi >= 6:
            time.sleep(0.3)
            d.click(100, 760)

    time.sleep(0.5)

    # 7. 'İleri >' butonuna bas
    if d(textContains="İleri").exists(timeout=2):
        d(textContains="İleri").click()
    elif d(descriptionContains="İleri").exists(timeout=2):
        d(descriptionContains="İleri").click()
    else:
        d.click(600, 900)
    time.sleep(3)

    # 8. 'Ses' butonuna basıp müzik ekle
    log.info("Trend müzik ekleniyor...")
    if d(text="Ses").exists(timeout=2):
        d(text="Ses").click()
    else:
        d.click(115, 780)
    time.sleep(2)

    # Klavyeyi kapat
    d.press("back")
    time.sleep(0.8)

    # Şarkıyı seç (x=300, y=600) ve Bitti de
    d.click(300, 600)
    time.sleep(1.5)
    if d(text="Bitti").exists(timeout=2):
        d(text="Bitti").click()
    else:
        d.click(650, 110)
    time.sleep(2)

    # 9. Editörden 'İleri ->' bas
    if d(text="İleri").exists(timeout=2):
        d(text="İleri").click()
    elif d(descriptionContains="İleri").exists(timeout=2):
        d(descriptionContains="İleri").click()
    else:
        d.click(625, 1450)
    time.sleep(3)

    # İlk defa paylaşım pop-up'ı (Tamam)
    if d(text="Tamam").exists(timeout=2):
        d(text="Tamam").click()
        time.sleep(1)

    # 10. Açıklama metnini yapıştır
    try:
        d.set_clipboard(caption_metni[:800])
        time.sleep(0.3)
        if d(textContains="açıklama").exists(timeout=2):
            d(textContains="açıklama").click()
        elif d(className="android.widget.EditText").exists(timeout=2):
            d(className="android.widget.EditText").click()
        else:
            d.click(200, 475)
        time.sleep(0.5)

        d.send_action("paste")
        time.sleep(0.5)
    except Exception as e:
        log.warning("Pano yapıştırma hatası: %s", e)

    # Klavyeyi kapat
    try:
        d.press("back")
    except Exception:
        pass
    time.sleep(1)

    # 11. 'İleri' veya 'Paylaş' butonuna bas
    if d(text="İleri").exists(timeout=2):
        d(text="İleri").click()
        time.sleep(2)

    # Pop-up: Reels Hakkında modalı çıkarsa Paylaş'a bas
    if d(text="Paylaş").exists(timeout=3):
        d(text="Paylaş").click()
        log.info("🎉 Instagram'da 'Paylaş' butonuna başarıyla basıldı!")
    elif d(descriptionContains="Paylaş").exists(timeout=3):
        d(descriptionContains="Paylaş").click()
        log.info("🎉 Description ile 'Paylaş' butonuna basıldı!")
    else:
        d.click(520, 1450)
        log.info("🎉 Koordinat ile 'Paylaş' butonuna basıldı!")

    time.sleep(8)
    try:
        d.screen_off()  # İşlem bitince ekranı kapatıp uykuya al
        log.info("Ekran kapatıldı, cihaz uykuya alındı.")
    except Exception:
        pass

    log.info("✅ Samsung otomasyonu ile Reels paylaşımı tamamlandı.")
    return True
