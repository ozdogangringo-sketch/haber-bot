"""
scripts/test_canli_yayinla.py — Samsung Galaxy A05 Canlı Paylaşım Doğrulama
"""
import time
import subprocess
from pathlib import Path
import uiautomator2 as u2

ADB_BIN = "/Users/macbook/Library/Android/sdk/platform-tools/adb"
TARGET = "192.168.0.112:5555"

print("1. Samsung cihaza bağlanılıyor...")
d = u2.connect(TARGET)
d.screen_on()
d.unlock()
time.sleep(1)

# 1. Slaytları telefona aktar
hedef_klasor = "/sdcard/Pictures/DailyBrief"
subprocess.run([ADB_BIN, "-s", TARGET, "shell", f"mkdir -p {hedef_klasor}"], check=True)
subprocess.run([ADB_BIN, "-s", TARGET, "shell", f"rm -f {hedef_klasor}/*.jpg"], check=True)

slaytlar = [
    Path("data/output/slayt-43088.jpg"),
    Path("data/output/slayt-43088-detay-1.jpg"),
    Path("data/output/slayt-43088-detay-2.jpg"),
]

for idx, s in enumerate(slaytlar, start=1):
    hedef = f"{hedef_klasor}/{idx:02d}_slayt.jpg"
    subprocess.run([ADB_BIN, "-s", TARGET, "push", str(s), hedef], check=True)
    subprocess.run([ADB_BIN, "-s", TARGET, "shell", f'am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d "file://{hedef}"'], check=True)
    print(f"Slayt {idx} aktarıldı: {s.name}")

time.sleep(1)

# 2. Instagram'ı sıfırdan aç
print("2. Instagram başlatılıyor...")
d.app_stop("com.instagram.android")
time.sleep(1)
d.app_start("com.instagram.android")
time.sleep(3)

# 3. Sol üstteki '+' veya alt bardaki '+' ikonuna tıkla
print("3. Oluştur (+) butonuna basılıyor...")
d.click(60, 110)
time.sleep(2)

# İzin penceresi varsa
if d(text="Tümüne izin ver").exists(timeout=2):
    d(text="Tümüne izin ver").click()
    time.sleep(1)

# 4. 'Seç' (Çoklu seçim) butonuna bas
print("4. Çoklu seçim açılıyor...")
if d(text="Seç").exists(timeout=3):
    d(text="Seç").click()
elif d(descriptionContains="Seç").exists(timeout=3):
    d(descriptionContains="Seç").click()
time.sleep(1)

# 5. Slaytları seç
print("5. Slaytlar seçiliyor...")
# Seçili ilk kutunun seçimini kaldır
d.click(270, 635)
time.sleep(0.3)

# 1. Slayt (x=450, y=635)
d.click(450, 635)
time.sleep(0.3)
# 2. Slayt (x=630, y=635)
d.click(630, 635)
time.sleep(0.3)
# 3. Slayt (x=90, y=815)
d.click(90, 815)
time.sleep(0.5)

d.screenshot("data/output/adim_test_secim.png")
print("Slaytlar seçildi, ekran kaydedildi.")

# 6. Sağ üstteki 'İleri' butonuna bas
print("6. İleri butonuna basılıyor...")
if d(text="İleri").exists(timeout=3):
    d(text="İleri").click()
time.sleep(3)

# 7. Müzik / Düzenleme ekranında 'İleri'
print("7. Müzik onaylanıyor (İleri)...")
if d(text="İleri").exists(timeout=3):
    d(text="İleri").click()
time.sleep(2)

if d(text="Tamam").exists(timeout=2):
    d(text="Tamam").click()
    time.sleep(1)

# 8. Açıklama yaz
print("8. Açıklama yazılıyor...")
caption = "🚨 İzmir'de çıkan orman yangınına karadan ve havadan yoğun müdahale ediliyor. Ekipler alevleri kontrol altına almak için çalışmalarını sürdürüyor.\n\nDetaylar Daily Brief'te. #izmir #yangın #sondakika #dailybrief"
d.set_clipboard(caption)
time.sleep(0.5)

d.click(200, 225)
time.sleep(0.5)
d.send_action("paste")
time.sleep(1)

# Klavyeyi kapat
d.press("back")
time.sleep(1)

d.screenshot("data/output/adim_test_paylas_oncesi.png")

# 9. Paylaş butonuna bas
print("9. Paylaş butonuna basılıyor...")
if d(text="Paylaş").exists(timeout=2):
    d(text="Paylaş").click()
    print("Mavi Paylaş butonuna tıklandı.")
else:
    d.click(360, 915)
    print("Koordinattan Paylaş tıklandı.")

print("10. Paylaşımın tamamlanması bekleniyor (10 sn)...")
time.sleep(10)

d.screenshot("data/output/adim_test_paylas_sonrasi.png")
print("🎉 Test tamamlandı! Ekran görüntüsü kaydedildi.")
