# GEMINI.md — Daily Brief Instagram & Sosyal Medya Haber Botu

Bu dosya projeyi devralan yapay zeka oturumu ve geliştiriciler içindir. Tüm mimari kararlar, yapılan geliştirmeler, çalışma kuralları ve sistemin güncel durumu bu rehberde toplanmıştır.

---

## 1. Kullanıcı Profili ve Çalışma İlkeleri

- **Kullanıcı:** Doğukan. Türkçe konuşur, kararlı ve net çıktılar bekler.
- **Teknik Yaklaşım:** SQL ve veritabanı mantığına hakimdir. Python kodlarını doğrudan asistanın yazıp test etmesini, sonuçları anlaşılır ve şeffaf biçimde sunmasını tercih eder.
- **Çalışma İlkeleri:**
  - **Küçük ve Doğrulanmış Adımlar:** Bir özellik veya düzeltme çalıştırılıp canlıda test edilmeden diğerine geçilmez.
  - **Dürüstlük ve Şeffaflık:** Gizli maliyet, API kotası veya platform kısıtları (Instagram/Threads API limitleri) açıkça belirtilir.
  - **Türkçe Standart:** Kod içi açıklamalar, değişken adları ve Telegram mesajları Türkçe terminolojiye uygundur.

---

## 2. Sistem Mimarisi & İşleyiş Akışı

Sistem günde 2 ana tur (Sabah/Akşam) ve gün içi tekil son dakika haberlerini Instagram, Facebook ve Threads'te otomatik/yarı-otomatik paylaşan bir yayın otomasyonudur:

```
[RSS & Finans Beslemeleri] 
       │ (AA, TRT, BloombergHT, Borsa Gündem, Investing TR, Webrazzi...)
       ▼
[fetch_news.py] ──> SQLite (data/haber.db) [durum='yeni']
       │
       ▼
[Seçim & Puanlama] (secim.py / ekonomi_turu.py / sondakika.py)
       │ (Gemini Flash ile başlık & özet üretimi)
       ▼
[Görsel & Slayt Üretimi] (slaytlar.py / piyasa_kart.py / upload_image.py)
       │ (4 Katmanlı Görsel + 144px 3D Kurumsal Logo + ImgBB / Catbox)
       ▼
[Telegram Onay Grubu] (telegram_bot.py ──> Daily Brief Grubu)
       │ (İnteraktif butonlar: ✅ Yayınla, ⏰ Ertele, 🎨 Slayt Düzenle...)
       ▼
[Cloudflare Worker ──> GitHub Actions] (onay_isle.py)
       │
       ├─► Instagram Graph API (1080x1350 Carousel & Story)
       ├─► Facebook Graph API (Sayfa Albümü & Story)
       └─► Threads API (6 Halkalı Bilgi Zinciri)
```

---

## 3. Yapılan Başlıca Geliştirmeler & Eklenen Sistemler

### A. Varyasyon 14 Canlı Piyasa Isı Haritası (`src/piyasa_kart.py`)
- **Tasarım:** *Derin Okyanus Petrolü* zemin (`#04181C` -> `#08262C`), *Siber Turkuaz* parıltılı rozet (`#06B6D4`) ve derin petrol dolgulu şeritler üzerinde *sıcak asil krem / kirli beyaz* (`#F6F3EC`) sektör başlıkları.
- **Ferah 3 Katmanlı Fiyat Düzeni:** Sıkışıklık giderildi; her kutucukta orantılı dikey yükseklikle Sembol (Üst), Canlı Fiyat (Orta Geniş Nefes Payı) ve Yön Oku + Yüzde Değişim (Alt) konumlandırıldı.
- **Altın & Gümüş Gram TL Canlı Çevrimi:** Ons Altın (`GC=F`) ve Gümüş (`SI=F`), anlık dolar kuru ve `31.1034768` ons gram formülüyle otomatik canlı Gram TL'ye çevrildi.
- **Vitrin Hiyerarşisi:** En üstte tam genişlikte BİST 100 ve dev Türk hisseleri (`TUPRS`, `KCHOL`, `THYAO`, `GARAN`, `AKBNK`, `ASELS`, `EREGL`, `BIMAS`); alt bloklarda Döviz/Emtia ve Kripto/Küresel devler.

### B. %100 Saf Finans & Borsa Ekonomi Turu (`scripts/ekonomi_turu.py`)
- **Yeni Özel Kaynaklar (`config.yaml`):** `BloombergHT`, `Borsa Gündem`, `Investing TR Hisse Senetleri`, `Investing TR Piyasalar`.
- **Kati Finans Filtresi:** Genel asayiş, kaza, siyaset, tarım destekleri, dış politika veya savaş haberleri ekonomi turu havuzundan tamamen filtrelendi. Yalnızca hisse, halka arz, TCMB, Fed, altın, kripto, fon ve şirket yatırımları seçilir.

### C. Kalıcı Hata Motoru & İnsan Okur Teşhis Sistemi (`src/hata_bildir.py`)
- **Kalıcı JSONL Kaydı (`data/hata_kayitlari.jsonl`):** Oluşan tüm sistem ve yayın hataları tarih, konum, ham traceback, insan diliyle teşhis ve önerilen aksiyonlarla kalıcı olarak dosyalanır.
- **İnsan Okur Şablon:**
  - ⚠️ **BİR SORUN OLUŞTU:** `...`
  - 📍 **Konum / İşlem:** `...`
  - 🔍 **NE OLDU?** (Net, terim içermeyen sade özet)
  - 💡 **NEDEN?** (Kök sebep analizi)
  - 🛠️ **EYLEM PLANI / ÇÖZÜM:** (Somut çözüm adımları)
- **Tek Tıkla Çözen Aksiyon Butonları:** `[🔄 Tekrar Yayınla]`, `[🔍 Yayın Durumunu Kontrol Et]`, `[🔄 Turu Yeniden Hazırla]`, `[🧹 Askıdaki Turu Sıfırla]`, `[📄 Detaylı Hata Kaydı]`.

### D. Kurumsal Marka Kimliği & 144px 3D Logo (`src/slaytlar.py`)
- Slaytlardaki marka logosu %50 büyütülerek **144x144 px** boyutuna çıkarıldı.
- Arka planına çok katmanlı 14px Gaussian Blur gölge eklenerek fotoğraflar üzerinde 3D kabartma derinliği kazandırıldı.

### E. Çoklu Platform Yayıncılığı & Güvenli Tip Yönetimi
- **Instagram + Facebook + Threads Eşzamanlı Yayını:** Carousel, sayfa albümü ve 6 halkalı Threads zinciri aynı işlemde güvenle yayınlanır.
- **Tip Güvenliği (`scripts/onay_isle.py` & `src/caption.py`):** `sqlite3.Row` nesnelerinden kaynaklanan `.get()` hataları `dict()` dönüşümüyle kökünden çözüldü.

---

## 4. Dosya ve Dizin Yapısı

| Dizin / Dosya | Görevi |
|---|---|
| `config.yaml` | Tüm bot ayarları, RSS kaynakları, ağırlıklar, eşikler ve sosyal medya anahtarları. |
| `src/piyasa.py` | Yahoo Finance üzerinden BİST, döviz, emtia, kripto ve ABD hisselerinin canlı çekimi & Gram TL hesabı. |
| `src/piyasa_kart.py` | 1080x1350 dikey formatta Varyasyon 14 piyasa ısı haritası ve infografik kartı üretim motoru. |
| `src/slaytlar.py` | 4:5 haber slaytlarının çizimi, tipografi, 144px 3D gölgeli logo, güvenli paylar ve fotoğraf yerleşimi. |
| `src/hata_bildir.py` | Kalıcı hata loglama (`data/hata_kayitlari.jsonl`), insan diliyle teşhis ve interaktif çözüm butonları. |
| `src/fetch_news.py` | 20+ RSS kaynağından haberleri çekme, parse etme ve SQLite veritabanına aktarma. |
| `src/generate_text.py` | Gemini Flash modelleri ile başlık, özet, detay metni ve önem puanı üretimi (yedek faturalı anahtar destekli). |
| `src/instagram.py` | Instagram Graph API carousel container oluşturma, durum sorgulama ve yayınlama. |
| `src/facebook.py` | Facebook Sayfa API üzerinden çoklu görsel albüm ve story paylaşımı. |
| `src/threads.py` | Threads API üzerinden 6 halkalı birbirine bağlı bilgi zinciri paylaşımı. |
| `scripts/ekonomi_turu.py` | Canlı piyasa kartı + 5 saf finans haberinden oluşan sabah/akşam ekonomi turunu oluşturan ana script. |
| `scripts/onay_isle.py` | Telegram butonlarına basıldığında Cloudflare Worker / GitHub Actions üzerinden yayını başlatan işleyici. |
| `scripts/varyasyon_uret.py` | Farklı renk, zemin ve gradyan temalarını toplu üreten yardımcı script. |

---

## 5. Görsel Seçim Mantığı ve Ürün Görselleri Analizi

### Mevcut 4 Katmanlı Görsel Hiyerarşisi (`src/slaytlar.py`):
1. **1. Katman — Haberin Orijinal Görseli (`og:image`):** Haberin kendi sitesindeki sosyal medya görseli çekilir (Asgari 1000x560 px boyutu aranır).
2. **2. Katman — Wikimedia Commons (Yalnızca Kişi Portreleri):** Haberde tanınmış bir kişi geçiyorsa (`gorsel_konu`) yüksek kaliteli resmi portresi çekilir.
3. **3. Katman — Pexels API (Temsili Stok Fotoğraf):** Kişi yoksa haber konusuna uygun stok fotoğraf aranır (Mükerrer fotoğraf engeli aktiftir).
4. **4. Katman — Kategori Gradyanı:** Fotoğraf bulunamazsa kategoriye özel koyu gradyan zemin kullanılır.

---

## 6. Git ve Canlı Ortam Kontrol Listesi

- `git status`: Çalışma dizini temiz, `main` dalı `origin/main` ile tamamen senkronize.
- Veritabanı: `data/haber.db` SQLite WAL modunda çalışır.
- Hata Günlüğü: `data/hata_kayitlari.jsonl` ve `data/son_hata.txt` aktif.
