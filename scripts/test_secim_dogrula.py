"""
scripts/test_secim_dogrula.py — Galeri Çoklu Seçim ve Numaralandırma Doğrulama
"""
import time
import subprocess
from pathlib import Path
import uiautomator2 as u2

ADB_BIN = "/Users/macbook/Library/Android/sdk/platform-tools/adb"
TARGET = "R96X200KERL"

d = u2.connect(TARGET)
d.screen_on()
d.unlock()

# 1. Instagram'ı sıfırdan aç
d.app_stop("com.instagram.android")
time.sleep(1)
d.app_start("com.instagram.android")
time.sleep(2.5)

# 2. Sol üstteki '+' (Oluştur) butonuna bas
d.click(60, 100)
time.sleep(2)

# Taslak uyarısı varsa temizle
if d(textContains="Yeni video").exists(timeout=2):
    d(textContains="Yeni video").click()
    time.sleep(1.5)

# Kamera açıldıysa Galeri'ye geç
if d(textContains="REELS").exists(timeout=1) and not d(text="Seç").exists(timeout=1) and not d(text="Yakınlardakiler").exists(timeout=1):
    d.click(90, 1450)
    time.sleep(2)

# 3. 'Seç' (Çoklu seçim) butonuna tıkla
print("Çoklu seçim butonuna basılıyor...")
if d(text="Seç").exists(timeout=2):
    d(text="Seç").click()
elif d(descriptionContains="Seç").exists(timeout=2):
    d(descriptionContains="Seç").click()
time.sleep(1.5)

d.screenshot("data/output/test_secim_1_buton_sonrasi.png")

# 4. Şimdi 1, 2 ve 3 numaralı slaytlara sırayla tıkla
# Slayt 1 (Kapak): x=480, y=280
print("1. Slayta tıklanıyor...")
d.click(480, 280)
time.sleep(0.8)
d.screenshot("data/output/test_secim_2_slayt1.png")

# Slayt 2 (Detay 1): x=640, y=280
print("2. Slayta tıklanıyor...")
d.click(640, 280)
time.sleep(0.8)
d.screenshot("data/output/test_secim_3_slayt2.png")

# Slayt 3 (Detay 2): x=100, y=520
print("3. Slayta tıklanıyor...")
d.click(100, 520)
time.sleep(0.8)
d.screenshot("data/output/test_secim_4_slayt3.png")

print("Seçim adımları tamamlandı, ekranlar kaydedildi.")
