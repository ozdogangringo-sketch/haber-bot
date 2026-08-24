import time
import uiautomator2 as u2

d = u2.connect("192.168.0.112:5555")

# 1. 'Yeni video başlat' tıkla
if d(text="Yeni video başlat").exists(timeout=2):
    d(text="Yeni video başlat").click()
    print("Yeni video başlat tıklandı.")

time.sleep(2)

# 2. 'Seç' (Çoklu seçim) tıkla
if d(text="Seç").exists(timeout=2):
    d(text="Seç").click()
    print("Seç tıklandı.")

time.sleep(1)

# 3. Slaytları seç (1: Apple kapak, 2: detay 1, 3: detay 2, 4: detay 3)
# Galeri ilk satır 3 sütun:
# Kamera (Sol), Slayt 1 (Orta: x=500, y=300), Slayt 2 (Sağ: x=650, y=300)
# İkinci satır: Slayt 3 (Sol: x=100, y=550), Slayt 4 (Orta: x=500, y=550)
d.click(500, 300) # 1
time.sleep(0.3)
d.click(650, 300) # 2
time.sleep(0.3)
d.click(100, 550) # 3
time.sleep(0.3)
d.click(500, 550) # 4
time.sleep(0.5)

d.screenshot("data/output/dbg_step_1_secildi.png")

# 4. 'İleri >' butonuna bas (Sağ alt: x=600, y=900 veya d(textContains='İleri'))
if d(textContains="İleri").exists(timeout=2):
    d(textContains="İleri").click()
else:
    d.click(600, 900)
time.sleep(3)

d.screenshot("data/output/dbg_step_2_editor.png")

# 5. Müzik ekle: 'Ses' butonuna bas
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

d.screenshot("data/output/dbg_step_3_muzik_eklendi.png")

# 6. Editörden 'İleri ->' bas (Sağ alttaki mavi buton)
if d(textContains="İleri").exists(timeout=2):
    d(textContains="İleri").click()
else:
    d.click(625, 915)
time.sleep(3)

d.screenshot("data/output/dbg_step_4_aciklama.png")

# 7. Açıklama yaz
d.set_clipboard("🍎 Apple'ın ilk katlanabilir telefonu Daily Brief ile yayında!\n\n#apple #teknoloji #sondakika #dailybrief")
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

d.screenshot("data/output/dbg_step_5_hazir.png")

# 8. Paylaş butonuna bas
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

time.sleep(8)
d.screenshot("data/output/dbg_step_6_paylasildi.png")
print("Bitti!")
