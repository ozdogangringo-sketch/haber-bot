"""
scripts/otomasyon_saglam.py — Eleman Tabanlı, Pop-Up Korumalı Sağlam Instagram Reels Paylaşıcısı
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

print("1. Slaytlar /sdcard/DCIM/Camera klasörüne taşınıyor...")
subprocess.run([ADB_BIN, "-s", TARGET, "shell", "rm -f /sdcard/DCIM/Camera/DailyBrief_*.jpg"], check=True)

slaytlar = [
    Path("data/output/slayt-42233.jpg"),
    Path("data/output/slayt-42233-detay-1.jpg"),
    Path("data/output/slayt-42233-detay-2.jpg"),
]

for idx, s in enumerate(slaytlar, start=1):
    hedef = f"/sdcard/DCIM/Camera/DailyBrief_{idx:02d}.jpg"
    subprocess.run([ADB_BIN, "-s", TARGET, "push", str(s), hedef], check=True, capture_output=True)
    subprocess.run([ADB_BIN, "-s", TARGET, "shell", f'am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d "file://{hedef}"'], check=True, capture_output=True)
    print(f"  -> Slayt {idx} yüklendi: {hedef}")

time.sleep(1)

print("2. Instagram sıfırdan açılıyor...")
d.app_stop("com.instagram.android")
time.sleep(1)
d.app_start("com.instagram.android")
time.sleep(2.5)

# Pop-up / Kamera ayarı temizliği
if d(text="Bitti").exists(timeout=1):
    d(text="Bitti").click()

# 3. Sol üst '+' Oluştur butonuna tıkla
print("3. Oluştur (+) butonuna tıklanıyor...")
d.click(60, 100)
time.sleep(2)

# Taslak uyarısı çıkarsa 'Yeni video başlat'
if d(textContains="Yeni video").exists(timeout=2):
    d(textContains="Yeni video").click()
    print("  -> Eski taslak uyarısı temizlendi.")
    time.sleep(1.5)

# Kamera açıldıysa sol alttaki Galeri Karesine tıkla
if d(textContains="REELS").exists(timeout=1) and not d(text="Seç").exists(timeout=1) and not d(text="Yakınlardakiler").exists(timeout=1):
    d.click(90, 1450)
    time.sleep(2)

# 4. 'Seç' (Çoklu seçim) butonuna tıkla
print("4. Çoklu seçim açılıyor...")
if d(text="Seç").exists(timeout=2):
    d(text="Seç").click()
elif d(descriptionContains="Seç").exists(timeout=2):
    d(descriptionContains="Seç").click()
time.sleep(1)

# 5. Slaytları seç (1, 2, 3)
# /sdcard/DCIM/Camera içine attığımız için en üst 3 görsel bizim slaytlarımızdır
# 1. Sütun (Kamera), 2. Sütun (Slayt 1: x=480, y=280), 3. Sütun (Slayt 2: x=640, y=280)
# 2. Satır 1. Sütun (Slayt 3: x=100, y=520)
print("5. Slaytlar seçiliyor...")
d.click(480, 280) # 1. Slayt (Kapak)
time.sleep(0.3)
d.click(640, 280) # 2. Slayt (Detay 1)
time.sleep(0.3)
d.click(100, 520) # 3. Slayt (Detay 2)
time.sleep(0.5)

d.screenshot("data/output/saglam_1_secildi.png")

# 6. 'İleri >' butonuna bas
print("6. İleri butonuna basılıyor...")
if d(textContains="İleri").exists(timeout=2):
    d(textContains="İleri").click()
elif d(descriptionContains="İleri").exists(timeout=2):
    d(descriptionContains="İleri").click()
else:
    d.click(600, 900)
time.sleep(3)

d.screenshot("data/output/saglam_2_editor.png")

# 7. 'Ses' butonuna basıp müzik ekle
print("7. Müzik ekleniyor...")
if d(text="Ses").exists(timeout=2):
    d(text="Ses").click()
else:
    d.click(115, 780)
time.sleep(2)

# Klavyeyi kapat
d.press("back")
time.sleep(0.8)

# Şarkıyı seç (x=300, y=600)
d.click(300, 600)
time.sleep(1.5)

# Bitti de
if d(text="Bitti").exists(timeout=2):
    d(text="Bitti").click()
else:
    d.click(650, 110)
time.sleep(2)

# 8. Editörden 'İleri ->' bas
print("8. Paylaşım ekranına geçiliyor...")
if d(text="İleri").exists(timeout=2):
    d(text="İleri").click()
elif d(descriptionContains="İleri").exists(timeout=2):
    d(descriptionContains="İleri").click()
else:
    d.click(625, 915)
time.sleep(3)

# İlk defa paylaşım pop-up'ı (Tamam)
if d(text="Tamam").exists(timeout=2):
    d(text="Tamam").click()
    time.sleep(1)

# 9. Açıklama metnini yapıştır
print("9. Açıklama metni yazılıyor...")
caption = "🍎 Apple'ın ilk katlanabilir telefonu Daily Brief ile yayında!\n\nDetaylar için kaydırın. #apple #iphone #teknoloji #dailybrief"
d.set_clipboard(caption)
time.sleep(0.5)

if d(className="android.widget.EditText").exists(timeout=2):
    d(className="android.widget.EditText").click()
else:
    d.click(200, 225)
time.sleep(0.5)
d.send_action("paste")
time.sleep(1)
d.press("back")
time.sleep(1)

d.screenshot("data/output/saglam_3_hazir.png")

# 10. 'Paylaş' butonuna bas
print("10. 'Paylaş' butonuna basılıyor...")
if d(text="Paylaş").exists(timeout=2):
    d(text="Paylaş").click()
    print("  -> d(text='Paylaş') ile basıldı!")
elif d(descriptionContains="Paylaş").exists(timeout=2):
    d(descriptionContains="Paylaş").click()
    print("  -> d(desc='Paylaş') ile basıldı!")
else:
    d.click(360, 915)
    print("  -> Koordinat ile basıldı!")

time.sleep(10)
d.screenshot("data/output/saglam_4_paylasildi.png")
print("✅ PAYLAŞIM ADIMI TAMAMLANDI!")
