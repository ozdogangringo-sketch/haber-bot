# Android Müzikli Carousel Otomasyon İstasyonu — Kurulum Rehberi (3 Dakika)

Bu rehber, Android telefonunuzu 7/24 kesintisiz çalışan bir **Daily Brief Müzikli Carousel Paylaşım İstasyonuna** dönüştürür.

---

## 1. Gereksinimler & Hazırlık

1. **Android Telefon** (Instagram uygulaması yüklü ve `@dailybrief.co` hesabı açık olmalı).
2. **Termux Uygulaması:** Google Play yerine [F-Droid üzerinden Termux](https://f-droid.org/en/packages/com.termux/) veya [Termux GitHub APK](https://github.com/termux/termux-app/releases) indirip kurun.
3. **Termux:API (Opsiyonel):** Pano (kopyala/yapıştır) desteği için [Termux:API APK](https://f-droid.org/en/packages/com.termux.api/) kurun.

---

## 2. Telefon Ayarları (Kapanmaması İçin)

1. **Pil Optimizasyonunu Kapat:**
   * Telefon Ayarları $\to$ Uygulamalar $\to$ **Termux** $\to$ Pil $\to$ **"Kısıtlanmamış" (Don't optimize)** seçin.
   * Aynı şekilde **Instagram** için de pil tasarrufunu kapatın.
2. **Depolama İzni Ver:**
   * Termux'u açıp şu komutu yazın ve gelen ekranda izne **"İzin Ver"** deyin:
     ```bash
     termux-setup-storage
     ```

---

## 3. Kurulumu Başlatma (Tek Komut)

Termux ekranına şu komutları yapıştırın:

```bash
pkg update -y && pkg install -y git python termux-api
git clone https://github.com/ozdogangringo-sketch/haber-bot.git
cd haber-bot
bash android/kurulum.sh
```

---

## 4. İstasyonu Çalıştırma

Kurulum bittikten sonra istasyonu başlatmak için:

```bash
python android/otomasyon.py
```

* Ekran açık veya kapalıyken istasyon arka planda uyanık kalır (`termux-wake-lock`).
* Sen Telegram'dan **`[🎵 Android'den Müzikli Yayınla]`** butonuna bastığın anda:
  1. Slaytlar otomatik galeriye indirilir.
  2. Instagram uygulaması Carousel ekranında açılır.
  3. Müzik seçilip caption yapıştırılarak post canlıya alınır! 🎉
