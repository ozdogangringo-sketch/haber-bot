"""
scripts/test_kusursuz_reels.py — Kusursuz Reels Paylaşım Doğrulaması
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

# 1. Instagram'ı sıfırdan aç
d.app_stop("com.instagram.android")
time.sleep(0.5)
d.app_start("com.instagram.android")
time.sleep(2.5)

# 2. Sol üst '+' tıkla
d.click(60, 110)
time.sleep(2)

# Taslak uyarısı varsa temizle
if d(text="Yeni video başlat").exists(timeout=2):
    d(text="Yeni video başlat").click()
    time.sleep(1.5)

# Kamera ayarlarına girdiyse 'Bitti' de
if d(text="Bitti").exists(timeout=1):
    d(text="Bitti").click()
    time.sleep(1)

# Eğer kamera modundaysa sol alttaki Galeri Karesine tıkla (x=90, y=1450)
if d(text="REELS VİDEOSU").exists(timeout=1) and not d(text="Yakınlardakiler").exists(timeout=1):
    d.click(90, 1450)
    time.sleep(2)

# 3. 'Seç' (Çoklu seçim) butonuna bas
if d(text="Seç").exists(timeout=2):
    d(text="Seç").click()
elif d(descriptionContains="Seç").exists(timeout=2):
    d(descriptionContains="Seç").click()
time.sleep(1)

# 4. Slaytları seç (1: Kapak, 2: Detay 1, 3: Detay 2)
# Grid koordinatları:
d.click(500, 300) # 1. Slayt
time.sleep(0.3)
d.click(650, 300) # 2. Slayt
time.sleep(0.3)
d.click(100, 550) # 3. Slayt
time.sleep(0.5)

d.screenshot("data/output/adim_1_secildi.png")
print("1. Slaytlar seçildi.")

# 5. Sağ alttaki 'İleri >' beyaz butonuna bas (x=600, y=900 / d(textContains='İleri'))
if d(textContains="İleri").exists(timeout=2):
    d(textContains="İleri").click()
else:
    d.click(600, 900)
time.sleep(3)

d.screenshot("data/output/adim_2_editor.png")
print("2. Editör açıldı.")

# 6. 'Ses' butonuna basıp trend müzik ekle
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

d.screenshot("data/output/adim_3_muzik_hazir.png")
print("3. Müzik bağlandı.")

# 7. Editörden 'İleri ->' mavi butonuna bas (x=625, y=915)
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

d.screenshot("data/output/adim_4_paylas_ekrani.png")
print("4. Paylaşım ekranı açıldı.")

# 8. Açıklama metnini yapıştır
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

# Klavyeyi kapat
d.press("back")
time.sleep(1)

d.screenshot("data/output/adim_5_metin_hazir.png")
print("5. Metin yazıldı.")

# 9. 'Paylaş' butonuna bas (Alttaki mavi buton: x=360, y=915 veya d(text='Paylaş'))
print("6. Paylaş butonuna basılıyor...")
if d(text="Paylaş").exists(timeout=2):
    d(text="Paylaş").click()
    print("d(text='Paylaş') basıldı.")
elif d(descriptionContains="Paylaş").exists(timeout=2):
    d(descriptionContains="Paylaş").click()
    print("d(desc='Paylaş') basıldı.")
else:
    d.click(360, 915)
    print("Koordinat Paylaş basıldı.")

# 10. Yüklemenin tamamlanmasını bekle (12 saniye)
time.sleep(12)

d.screenshot("data/output/adim_6_tamamlandi.png")
print("🎉 PAYLAŞIM TAMAMLANDI!")
