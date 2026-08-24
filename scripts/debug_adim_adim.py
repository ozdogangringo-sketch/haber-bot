import time
import subprocess
from pathlib import Path
import uiautomator2 as u2

ADB_BIN = "/Users/macbook/Library/Android/sdk/platform-tools/adb"
TARGET = "192.168.0.112:5555"

d = u2.connect(TARGET)
d.screen_on()
d.unlock()

# 1. Instagram'ı aç
d.app_stop("com.instagram.android")
time.sleep(1)
d.app_start("com.instagram.android")
time.sleep(2)

# 2. Sol üst '+' tıkla
d.click(60, 110)
time.sleep(2)

# 3. REELS seç
if d(textContains="REELS").exists(timeout=2):
    d(textContains="REELS").click()
    time.sleep(1.5)

# 4. Seç (Çoklu seçim) tıkla
if d(text="Seç").exists(timeout=2):
    d(text="Seç").click()
time.sleep(1)

# 5. Slaytları seç
d.click(500, 550) # 1
time.sleep(0.3)
d.click(500, 300) # 2
time.sleep(0.3)
d.click(650, 300) # 3
time.sleep(0.5)

d.screenshot("data/output/dbg_1_secim.png")

# 6. İleri bas
if d(textContains="İleri").exists(timeout=2):
    d(textContains="İleri").click()
else:
    d.click(600, 900)
time.sleep(3)

d.screenshot("data/output/dbg_2_editor.png")

# 7. Editörden İleri bas
if d(textContains="İleri").exists(timeout=2):
    d(textContains="İleri").click()
else:
    d.click(625, 915)
time.sleep(3)

d.screenshot("data/output/dbg_3_paylas_ekrani.png")

# 8. Açıklama yaz
d.set_clipboard("Apple'ın ilk katlanabilir telefonu Daily Brief ile yayında. #apple #teknoloji")
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

d.screenshot("data/output/dbg_4_hazir.png")

# 9. Paylaş tıkla
print("Paylaş butonuna basılıyor...")
if d(text="Paylaş").exists(timeout=2):
    d(text="Paylaş").click()
    print("d(text='Paylaş') tıklandı.")
elif d(descriptionContains="Paylaş").exists(timeout=2):
    d(descriptionContains="Paylaş").click()
    print("d(desc='Paylaş') tıklandı.")
else:
    d.click(360, 915)
    print("Koordinat tıklandı.")

time.sleep(3)
d.screenshot("data/output/dbg_5_basildiktan_sonra.png")

time.sleep(10)
d.screenshot("data/output/dbg_6_10sn_sonra.png")
print("Bitti.")
