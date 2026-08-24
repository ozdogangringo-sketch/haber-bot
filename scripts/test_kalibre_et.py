"""
scripts/test_kalibre_et.py — Instagram UI Kalibrasyon ve Hassas Adım Testi
"""
import time
import subprocess
from pathlib import Path
import uiautomator2 as u2

ADB_BIN = "/Users/macbook/Library/Android/sdk/platform-tools/adb"
TARGET = "192.168.0.112:5555"

d = u2.connect(TARGET)
d.screen_on()
d.unlock()

# 1. Klasörü temizle ve 4 adet slayt yükle
hedef_klasor = "/sdcard/Pictures/DailyBrief"
subprocess.run([ADB_BIN, "-s", TARGET, "shell", f"rm -rf {hedef_klasor} && mkdir -p {hedef_klasor}"], check=True)

# Son oluşturulan slaytları al
slaytlar = [
    Path("data/output/piyasa_karti_20260823.jpg"),
    Path("data/output/slayt-43088.jpg"),
    Path("data/output/slayt-43088-detay-1.jpg"),
    Path("data/output/slayt-43088-detay-2.jpg"),
]

# Galeri en yeni dosyayı en başta gösterir. Doğru sırada çıkması için zaman damgalarını ayarla
for idx, s in enumerate(slaytlar, start=1):
    hedef = f"{hedef_klasor}/{idx:02d}_slayt.jpg"
    subprocess.run([ADB_BIN, "-s", TARGET, "push", str(s), hedef], check=True)
    subprocess.run([ADB_BIN, "-s", TARGET, "shell", f'am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d "file://{hedef}"'], check=True)

time.sleep(1)

# 2. Instagram'ı aç
d.app_stop("com.instagram.android")
time.sleep(0.5)
d.app_start("com.instagram.android")
time.sleep(2.5)

# 3. Sol üst '+' tıkla
d.click(60, 110)
time.sleep(2)

# Ekranı kaydet
d.screenshot("data/output/kalibre_1_olustur.png")
print("1. Oluşturma ekranı açıldı.")
