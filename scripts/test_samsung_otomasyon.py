"""
scripts/test_samsung_otomasyon.py — Samsung Cihazı ile Reels Fotoğraf Carouseli Otomasyon Testi
"""

import time
import uiautomator2 as u2
from pathlib import Path

d = u2.connect("R96X200KERL")
print("1. Samsung Galaxy A05'e bağlandı:", d.info.get("productName"))

# 1. Instagram'ı ön plana getir
d.app_start("com.instagram.android")
time.sleep(1)

# Ekran resmi al
d.screenshot("data/output/adim_1_ana_ekran.png")
print("Adım 1 tamam: Ana ekran yakalandı.")

# 2. Sol üstteki '+' (Oluştur) veya alt bardaki butonlara bak
if d(descriptionContains="Oluştur").exists(timeout=3):
    d(descriptionContains="Oluştur").click()
    print("Oluştur butonuna tıklandı.")
elif d(descriptionContains="Yeni gönderi").exists(timeout=3):
    d(descriptionContains="Yeni gönderi").click()
    print("Yeni gönderi butonuna tıklandı.")
elif d(descriptionContains="Create").exists(timeout=3):
    d(descriptionContains="Create").click()
    print("Create butonuna tıklandı.")
else:
    # Sol üstteki '+' ikon koordinatına dokun (x=60, y=110)
    d.click(60, 110)
    print("Sol üst '+' koordinatına tıklandı.")

time.sleep(2)
d.screenshot("data/output/adim_2_olustur_ekrani.png")
print("Adım 2 tamam: Oluşturma ekranı yakalandı.")
