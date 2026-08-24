import time
import uiautomator2 as u2

d = u2.connect("R96X200KERL")

# 1. 'Ses' butonuna bas
print("Ses butonuna basılıyor...")
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

# 2. Editörden 'İleri ->' bas (x=625, y=1450)
print("İleri butonuna basılıyor...")
if d(text="İleri").exists(timeout=2):
    d(text="İleri").click()
elif d(descriptionContains="İleri").exists(timeout=2):
    d(descriptionContains="İleri").click()
else:
    d.click(625, 1450)
time.sleep(3)

# 3. Açıklama yaz
print("Açıklama yazılıyor...")
caption = "🍎 Apple'ın ilk katlanabilir telefonu Daily Brief ile yayında!\n\nDetaylar için kaydırın. #apple #iphone #teknoloji #dailybrief"
d.set_clipboard(caption)
time.sleep(0.5)

if d(textContains="açıklama").exists(timeout=2):
    d(textContains="açıklama").click()
elif d(className="android.widget.EditText").exists(timeout=2):
    d(className="android.widget.EditText").click()
else:
    d.click(200, 475)
time.sleep(0.5)
d.send_action("paste")
time.sleep(1)
d.press("back")
time.sleep(1)

# 4. 'İleri' veya 'Paylaş' butonuna bas
print("Paylaş basılıyor...")
if d(text="İleri").exists(timeout=2):
    d(text="İleri").click()
    time.sleep(2)

if d(text="Paylaş").exists(timeout=3):
    d(text="Paylaş").click()
elif d(descriptionContains="Paylaş").exists(timeout=3):
    d(descriptionContains="Paylaş").click()
else:
    d.click(520, 1450)

time.sleep(10)
d.screenshot("data/output/tamamlandi_3_slayt_sonuc.png")
print("🎉 3 Slayt Paylaşımı Tamamlandı!")
