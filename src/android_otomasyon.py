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
DEFAULT_IP = "192.168.0.112:5555"
DEFAULT_SERIAL = "R96X200KERL"


def cihaza_baglan() -> Optional["u2.Device"]:
    """
    Samsung cihaza önce Wi-Fi (192.168.0.112:5555), olmazsa USB üzerinden bağlanır.
    """
    if u2 is None:
        log.warning("uiautomator2 kütüphanesi kurulu değil, Android otomasyonu atlanıyor.")
        return None

    try:
        subprocess.run([ADB_BIN, "connect", DEFAULT_IP], capture_output=True, timeout=5)
    except Exception as e:
        log.warning("Wi-Fi ADB connect denemesi: %s", e)

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


def slaytlari_telefona_aktar(target: str, slayt_yollari: list[Path]) -> list[str]:
    """
    Slayt dosyalarını telefonun /sdcard/Pictures/DailyBrief klasörüne aktarır ve galeriye işletir.
    """
    hedef_klasor = "/sdcard/Pictures/DailyBrief"
    
    cmd_prefix = [ADB_BIN]
    if target:
        cmd_prefix.extend(["-s", target])

    # Klasörü temizle ve yeniden oluştur
    subprocess.run(cmd_prefix + ["shell", f"rm -rf {hedef_klasor} && mkdir -p {hedef_klasor}"], check=True, capture_output=True)

    aktarilanlar = []
    for idx, dosya in enumerate(slayt_yollari, start=1):
        if not dosya.exists():
            continue
        hedef_dosya = f"{hedef_klasor}/{idx:02d}_slayt.jpg"
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

    # 4. Sol üstteki '+' (Oluştur) butonuna bas
    d.click(60, 110)
    time.sleep(2)

    # İzin pop-up'ı gelirse onayla
    if d(text="Tümüne izin ver").exists(timeout=2):
        d(text="Tümüne izin ver").click()
        time.sleep(1)

    # 5. REELS moduna geç
    if reel_olarak:
        if d(textContains="REELS").exists(timeout=2):
            d(textContains="REELS").click()
            time.sleep(1.5)

    # 6. 'Seç' (Çoklu seçim) butonuna bas
    if d(text="Seç").exists(timeout=2):
        d(text="Seç").click()
    elif d(descriptionContains="Seç").exists(timeout=2):
        d(descriptionContains="Seç").click()
    time.sleep(1)

    # 7. Slaytları sırasıyla seç (720x1600 Reels Grid Koordinatları)
    # Grid 3 sütunlu:
    # 1. Slayt (Kapak): x=500, y=550 (veya x=450, y=635)
    # 2. Slayt: x=500, y=300
    # 3. Slayt: x=650, y=300
    # 4. Slayt: x=290, y=450
    # 5. Slayt: x=90, y=815
    # 6. Slayt: x=270, y=815
    log.info("Slaytlar sırayla seçiliyor (toplam %s)...", slayt_sayisi)
    
    if slayt_sayisi == 1:
        d.click(500, 550)
    elif slayt_sayisi == 2:
        d.click(500, 550)
        time.sleep(0.3)
        d.click(500, 300)
    elif slayt_sayisi == 3:
        d.click(500, 550)
        time.sleep(0.3)
        d.click(500, 300)
        time.sleep(0.3)
        d.click(650, 300)
    elif slayt_sayisi >= 4:
        d.click(290, 450)  # Piyasa kartı
        time.sleep(0.3)
        d.click(500, 550)  # 1. Haber
        time.sleep(0.3)
        d.click(500, 300)  # 2. Haber
        time.sleep(0.3)
        d.click(650, 300)  # 3. Haber
        time.sleep(0.3)
        if slayt_sayisi >= 5:
            d.click(90, 815)
            time.sleep(0.3)
        if slayt_sayisi >= 6:
            d.click(270, 815)
            time.sleep(0.3)

    time.sleep(0.5)

    # 8. 'İleri >' butonuna bas (Sağ alt veya üst)
    if d(textContains="İleri").exists(timeout=2):
        d(textContains="İleri").click()
    else:
        d.click(600, 900)  # Sağ alt 'İleri >' butonu
    time.sleep(3)

    # 9. Müzik ekle: 'Ses' butonuna bas
    log.info("Trend müzik ekleniyor...")
    if d(text="Ses").exists(timeout=2):
        d(text="Ses").click()
    else:
        d.click(115, 780)  # Sol alt Ses butonu
    time.sleep(2)

    # Klavyeyi kapatıp şarkı listesini gör
    d.press("back")
    time.sleep(0.8)

    # Şarkılardan birine dokun ve 'Bitti' de
    d.click(300, 600)  # 2. Şarkı (En popüler/instrumental)
    time.sleep(1.5)
    if d(text="Bitti").exists(timeout=2):
        d(text="Bitti").click()
    else:
        d.click(650, 110)
    time.sleep(2)

    # 10. Editörden 'İleri ->' butonuna bas
    if d(textContains="İleri").exists(timeout=2):
        d(textContains="İleri").click()
    else:
        d.click(625, 915)  # Mavi İleri butonu
    time.sleep(2.5)

    # İlk defa paylaşım uyarısı (Tamam)
    if d(text="Tamam").exists(timeout=2):
        d(text="Tamam").click()
        time.sleep(1)

    # 11. Açıklama metnini yaz (Panodan güvenli yapıştır)
    try:
        d.set_clipboard(caption_metni[:800])
        time.sleep(0.3)
        if d(className="android.widget.EditText").exists(timeout=2):
            d(className="android.widget.EditText").click()
        elif d(textContains="açıklama").exists(timeout=2):
            d(textContains="açıklama").click()
        else:
            d.click(200, 225)
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

    # 12. 'Paylaş' butonuna bas
    if d(text="Paylaş").exists(timeout=2):
        d(text="Paylaş").click()
        log.info("🎉 Instagram'da 'Paylaş' butonuna başarıyla basıldı!")
    elif d(descriptionContains="Paylaş").exists(timeout=2):
        d(descriptionContains="Paylaş").click()
        log.info("🎉 Description ile 'Paylaş' butonuna basıldı!")
    else:
        d.click(360, 915)  # Mavi Paylaş butonu koordinatı
        log.info("🎉 Koordinat ile 'Paylaş' butonuna basıldı!")

    time.sleep(8)
    try:
        d.screen_off()  # İşlem bitince ekranı kapatıp uykuya al
        log.info("Ekran kapatıldı, cihaz uykuya alındı.")
    except Exception:
        pass

    log.info("✅ Samsung otomasyonu ile Reels paylaşımı tamamlandı.")
    return True
