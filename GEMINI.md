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

Sistem sabahları fiks Canlı Piyasa & Borsa Bülteni (Piyasa Turu) ve gün boyu 1'er saatlik aralıklarla tekli derinlemesine analiz carousel'lerini Instagram, Facebook, Threads ve X'te otomatik/yarı-otomatik paylaşan bir yayın otomasyonudur:

```
[RSS & Finans Beslemeleri] 
       │ (AA, TRT, BloombergHT, Borsa Gündem, Investing TR, Webrazzi...)
       ▼
[fetch_news.py] ──> SQLite (data/haber.db) [durum='yeni']
       │
       ▼
[Saatlik Öneri & Seçim] (son_dakika.py / ekonomi_turu.py)
       │ (Her saat başı en iyi 5 taze haber önerisi)
       ▼
[Tekil 3+ Slayt Carousel Üretimi] (slaytlar.py / make_image.py)
       │ (1 Kapak + 2-4 Detay/Analiz Slaytı + 144px 3D Logo)
       ▼
[Telegram Onay Grubu] (telegram_bot.py ──> Daily Brief Grubu)
       │ (İnteraktif butonlar: 1️⃣..5️⃣ Seç, ✅ Yayınla, 🔄 Başka Fotoğraf...)
       ▼
[Cloudflare Worker ──> GitHub Actions] (onay_isle.py)
       │
       ├─► Instagram Graph API (1080x1350 Carousel, Reels & Story)
       ├─► Facebook Graph API (Sayfa Albümü & Story)
       ├─► Threads API (6 Halkalı Bilgi Zinciri)
       └─► X (Twitter) API v2 (4 Fotoğraflı Tweet)
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

### F. Akıllı Hatırlatma & 3 Günlük Kati Havuz Temizliği
- **Eski Hatırlatmayı Silme (Temiz Sohbet):** `scripts/hatirlat.py` yeni bir hatırlatma atarken önceki hatırlatma mesajını Telegram'dan otomatik siler; böylece her saat başı yeni bildirim düşer ancak grupta mesaj yığını oluşmaz.
- **12 Saat Azami Tur Ömrü:** Cevap verilmeyen turlar 24 saat yerine 12 saat sonra otomatik kapanıp havuza döner.
- **3 Günlük Kati Havuz Temizliği (`config.yaml` & `src/db.py`):** `kayit_saklama_gun: 3` yapıldı; 3 günden eski hiçbir yayınlanmamış haber veritabanında ve havuzda tutulmaz, her gece otomatik purge edilir. (Tek seferde 2.622 eski kayıt temizlendi).

### G. Havuz Dışı Özel Haber Üretim Motoru (`src/ozel_haber.py`)
- **`1. /link <URL>` (Linkten Tam Post):** İstenen web sayfasının makale gövdesini ve orijinal basın fotoğraflarını çeker; Gemini ile Türkçe manşet, spot özet, vurgu rakamı ve Instagram caption'ını üretip onay kartı sunar.
- **`2. /arastir <KONU>` (Canlı Web Araştırması):** Verilen konuyu Gemini ile webde derinlemesine araştırıp doğrulanmış gerçek bilgileri 4:5 slaytlara dönüştürür.
- **`3. /ozel <METİN>` (Özel Bülten & Duyuru):** Kullanıcının doğrudan yazdığı duyuru/bülten metnini kurumsal Daily Brief şablonuna döker.

### H. 4. Yayın Kanalı: X (Twitter) API v2 Entegrasyonu (`src/twitter.py`)
- **OAuth 1.0a Saf Python Motoru:** Harici bağımlılığa gerek duymadan RFC 5849 standartlarında kalıcı yetkilendirme sağlar.
- **4 Fotoğraflı Medya Yükleme & 280 Karakter:** 1.1 Media Upload ile 4 adet 1080x1350 slayt yüklenir; 280 karaktere optimize edilmiş metin paylaşılır. URL link vergisine (\$0.20) takılmamak için kaynak metin olarak yazılır (\$0.015 birim maliyet).
- **Flood / Zincirleme Modu:** Çoklu haber turları birbirine yanıt veren Flood (Thread) olarak paylaşılır.
- **Telegram `[✅ X]` Toggle Butonu:** Onay menüsünde tek tıkla açılıp kapatılabilir.

### I. Telegram Tek Tıkla Alternatif Fotoğraf Motoru (`[🔄 Başka Fotoğraf Bul]`)
- **İşleyiş:** Onay mesajındaki butona basıldığında webden sıradaki en kaliteli HD basın fotoğrafını (DuckDuckGo HD) seçer, Carousel ve Native 9:16 Story slaytlarını baştan çizer ve Telegram albümünü anında günceller.

### J. Otomatik Mini Finans Grafikleri (Sparkline & Trend Kartı, `src/sparkline.py`)
- **30 Günlük Fiyat Serisi:** Borsa, hisse, döviz, emtia ve kripto haberlerinde Yahoo Finance üzerinden son 30 günün kapanış fiyatları çekilir.
- **Varyasyon 14 Siber Turkuaz / Mercan Kırmızı Çizgi:** Catmull-Rom/Bezier yumuşak eğrili, degrade yarı saydam dolgulu ve parlak bitiş noktalı 880x240px estetik infografik trend kartı üretilir ve detay slaytına gömülür.

### L. Editoryal İçerik ve AI Manşet Motoru Modernizasyonu (`src/generate_text.py` & `src/caption.py`)
- **3 Alternatifli Düşünce Modeli (Chain-of-Thought):** Gemini arka planda 3 farklı stilde başlık üretir (Dinamik Sonuç, Rakam & Veri Odaklı, Vurucu Karar / Söylem); akışta kaydırmayı en çok durduran ve sonucu en net veren kancayı `ig_baslik` olarak seçer. Pasif ajans dili kalıpları tamamen elendi.
- **"Sana / Piyasaya Etkisi" (Personal Impact):** Okuyucunun cebine, kredisini, mevduatını, borsadaki hissesini veya günlük hayatını doğrudan nasıl etkilediğini anlatan 1-2 cümlelik analiz boyutu eklendi. Detay slaytlarında Zümrüt Yeşili (`#10B981`) vurgu çizgisiyle çizilir.
- **Kategoriye Özel Editoryal Üslup:** Ekonomi ve borsada keskin Bloomberg/FT seviyesi finans dili; teknoloji ve bilimde vizyoner ve yalın dil; gündemde Smart Brevity analitik dili uygulandı.
- **Etkileşim ve Yorum CTA'sı:** Her haberin sonuna takipçilerin fikirlerini yorumlarda belirtmelerini sağlayan zekice 1 soru eklendi.
- **Zenginleştirilmiş İnfografik Veri Rozetleri:** Slaytlara şık cam (glassmorphism) kutu içinde karşılaştırma rozetleri (`[ 📈 HEDEF FİYAT: 380 ₺ ➔ 450 ₺ ]`) entegre edildi.
- **Taranabilir Mini Bülten Caption Formatı:** Instagram ve Threads için madde işaretli, emojili ve net taranabilir açıklama şablonu oluşturuldu.

### M. 6 Platformlu Kurumsal Sosyal Footer İkonları (`src/make_image.py` & `config.yaml`)
- Slaytların sağ alt köşesindeki `dailybrief.co` alt bilgi bloğuna **YouTube** ve **TikTok** resmi marka ikonları entegre edildi.
- 6 kanal (`Instagram`, `Threads`, `Facebook`, `X`, `YouTube`, `TikTok`) kusursuz yatay hizalama ve eşit aralıklarla çizilir.

### N. %100 Saf Native 9:16 Full-Bleed Video Motoru (`src/video.py`)
- **4:5 Kırpma / Bulanık Kenar Kaldırıldı:** YouTube Shorts ve TikTok videoları artık 4:5 postların yapay bulanıklaştırılmış kopyası değil; her biri doğrudan **1080x1920 native Story şablonu** (`story_haber` ve `story_detay`), tam ekran fotoğraf yerleşimi, 144px 3D logo, Zümrüt Yeşili vurgu blokları ve editoryal tipografiyle baştan çizilir.
- **Kullanıcının Seçtiği Taze Görsel Garantisi:** Videolar artık varsayılan RSS aramasından değil, kullanıcının Telegram'da seçtiği/onayladığı en güncel `story_url` ve görsel linklerinden derlenir.

### O. Global Markdown Sanitasyonu ve Temiz Sosyal Metinler (`src/filtre.py` & `src/caption.py`)
- **Sıfır `**` (Markdown Bold) Kuralı:** Instagram, Threads ve Twitter düz metin platformları markdown bold (`**`) desteklemediği için çiğ yıldızların görünmesi engellendi.
- `filtre.markdown_temizle()` filtresi sayesinde Gemini çıktısı, Telegram onay kartı ve tüm sosyal medya açıklamaları otomatik olarak temiz ve akıcı düz metne dönüştürülür.

### P. Telegram Yüzen Onay Menüsü (Her Düzenlemede En Alta Taşıma, `scripts/onay_isle.py`)
- Slayt fotoğrafı değiştirildiğinde (`[🔄 Başka Fotoğraf Bul]`), metin düzenlendiğinde veya slayt silindiğinde eski buton mesajı otomatik silinir; yeni önizleme albümü gönderildikten sonra **onay kartı ve butonlar sohbetin EN ALTINA** yeni bir mesaj olarak bırakılır. Kullanıcının yukarı kaydırmasına gerek kalmaz.

---

## 4. Dosya ve Dizin Yapısı

| Dizin / Dosya | Görevi |
|---|---|
| `config.yaml` | Tüm bot ayarları, RSS kaynakları, ağırlıklar, eşikler ve sosyal medya anahtarları. |
| `src/sparkline.py` | Borsa/finans haberleri için 30 günlük geçmiş fiyat çekimi ve estetik trend grafiği çizimi. |
| `src/youtube.py` | YouTube Data API v3 üzerinden 9:16 Shorts video yükleme ve OAuth yetkilendirmesi. |
| `src/tiktok.py` | TikTok Content Posting API v2 üzerinden dikey video yükleme ve durum sorgulama. |
| `src/ozel_haber.py` | Telegram üzerinden `/link`, `/arastir` ve `/ozel` komutlarıyla havuz dışı özel haber üretimi. |
| `src/twitter.py` | X (Twitter) API v2 üzerinden 4 fotoğraflı tekil post, Flood (zincir) paylaşımı ve sağlık testi. |
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

## 5. Görsel Seçim Mantığı ve Ürün Görselleri Standartları

### 4 Katmanlı Akıllı Görsel Hiyerarşisi:
1. **1. Katman — Akıllı Makale Basın & Ürün Görseli Çekici (`src/fetch_article.py`):**
   - Yalnızca `og:image` ile yetinmez; `twitter:image`, JSON-LD `NewsArticle` yüksek çözünürlüklü `"image"` verisi ve makale gövdesindeki (`featured-image`, `article figure img`) orijinal lansman/ürün fotoğraflarını çeker.
   - İkon, avatar, yazar resmi, reklam ve banner'lar otomatik filtrelenir.
2. **2. Katman — Wikimedia Commons (Yalnızca Kişi Portreleri, `src/fetch_photo.py`):**
   - Haberde tanınmış bir kişi/yönetici geçiyorsa (`gorsel_konu`) yüksek kaliteli resmi portresi çekilir.
3. **3. Katman — Yüksek Çözünürlüklü Nokta Atışı Stok Motoru (`src/fetch_stock.py`):**
   - Pexels üzerinde yapay zekanın ürettiği somut İngilizce arama kalıpları (`"silicon wafer AI microchip"`, `"commercial passenger jet"`, `"gold bullion bars vault"`) kullanılır.
   - Dikey ve 4K/2K yatay yüksek çözünürlüklü havuz taranır; genel ofis veya soyut bulanık manzaralar elenir.
4. **4. Katman — Derin Kategori Gradyanı (`src/make_image.py`):**
   - Fotoğraf bulunamazsa kategoriye özel koyu gradyan zemin kullanılır.
   - Kullanıcı dilerse Telegram'dan **`🎨 AI ile üret`** butonuna basarak anında stüdyo render'ı çizdirebilir.

---

## 6. Git ve Canlı Ortam Kontrol Listesi

- `git status`: Çalışma dizini temiz, `main` dalı `origin/main` ile tamamen senkronize.
- Veritabanı: `data/haber.db` SQLite WAL modunda çalışır.
- Hata Günlüğü: `data/hata_kayitlari.jsonl` ve `data/son_hata.txt` aktif.
