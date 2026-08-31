# GEMINI.md — Daily Brief Instagram & Sosyal Medya Haber Botu

Bu dosya projeyi devralan yapay zeka oturumu ve geliştiriciler içindir. Tüm mimari kararlar, yapılan geliştirmeler, çalışma kuralları ve sistemin güncel durumu bu rehberde toplanmıştır.

---

## 1. Kullanıcı Profili ve Değişmez Temel İlkeler

- **Kullanıcı:** Doğukan. Türkçe konuşur, kararlı, yüksek kaliteli ve net çıktılar bekler.
- **Teknik Yaklaşım:** SQL ve veritabanı mantığına hakimdir. Kodların doğrudan asistan tarafından profesyonelce yazılıp test edilmesini tercih eder.
- **KATI VE DEĞİŞMEZ KURAL (ZERO BLUR BORDER & 100% NATIVE 9:16):**
  * **ASLA VE ASLA** 4:5 gönderi kartları üstten/alttan blur arka plan veya yapay çerçeve eklenerek (`_cercevele_9_16`) 9:16 Story/Reels'e dönüştürülmeyecektir!
  * Tüm dikey formatlar (Instagram Story, Facebook Story, Reels, YouTube Shorts, TikTok, Piyasa Kartı Story, BİST Tablosu Story) **doğrudan 1080x1920 piksel tuvalde %100 SAF NATIVE FULL-BLEED infografik ve slayt olarak sıfırdan çizilir**.
- **KATI TİPOGRAFİ VE ÇİĞ YILDIZ ENGELİ:**
  * Slayt görsellerinde kilit veriler, oranlar ve aktörler Pillow render motoru tarafından **800.0 Extra Bold** kalın ve parlak çizilir.
  * Sosyal medya açıklamalarında (`ig_caption`, Threads, Twitter) ise **SIFIR MARKDOWN (`**`) KURALI** geçerlidir; tüm açıklamalar temiz düz metindir.
- **YAYIN MODELİ (SAATLİK TEKLİ HABERLER):**
  * Akşam çoklu haber turları kaldırılmıştır.
  * Gün boyu 1'er saat aralıklarla Telegram'a **en taze 5 haber önerisi** düşer; seçilen haber varsayılan olarak **3 ferah sayfa (1 Kapak + 2 Detay/Analiz Slaytı)** olarak üretilir.
  * Sabahları fiks **Canlı Borsa & Piyasa Bülteni** (4:5 Akış Carousel + 1080x1920 Native Story) otomatik paylaşılır.

---

## 2. Sistem Mimarisi & İşleyiş Akışı

```
[RSS & Finans Beslemeleri] 
       │ (AA, BloombergHT, Borsa Gündem, Investing TR, Webrazzi...)
       ▼
[fetch_news.py] ──> SQLite (data/haber.db) [durum='yeni']
       │
       ▼
[Saatlik Öneri & Seçim] (son_dakika.py)
       │ (Her saat başı en iyi 5 taze haber önerisi)
       ▼
[Tekil 3 Slayt Carousel + 1080x1920 Native Story Üretimi] (slaytlar.py / make_image.py)
       │ (1 Kapak + 2 Detay Slaytı + 144px 3D Logo + Zümrüt Yeşili "Sana Etkisi")
       ▼
[Telegram Onay Grubu] (telegram_bot.py ──> Daily Brief Grubu)
       │ (İnteraktif butonlar: 1️⃣..5️⃣ Seç, ✅ Yayınla, 🔄 Başka Fotoğraf...)
       ▼
[Cloudflare Worker ──> GitHub Actions] (onay_isle.py)
       │
       ├─► Instagram Graph API (1080x1350 Carousel & 1080x1920 Native Story)
       ├─► Facebook Graph API (Sayfa Albümü & 1080x1920 Story)
       ├─► Threads API (6 Halkalı Bilgi Zinciri)
       ├─► X (Twitter) API v2 (4 Fotoğraflı Tweet)
       ├─► YouTube Data API v3 (9:16 Shorts Video)
       └─► TikTok Content Posting API (9:16 Dikey Video)
```

---

## 3. Yapılan Başlıca Geliştirmeler & Modüller

### A. %100 Saf Native 1080x1920 Canlı Piyasa Bülteni (`src/piyasa_kart.py` & `src/piyasa_tablo.py`)
- **4:5 Carousel Akış:** 1080x1350 formatında 1. Slayt (Piyasa Isı Haritası) + 2. Slayt (30 Varlık BİST/Küresel/Kripto Tablosu).
- **%100 Native 9:16 Story:** `piyasa_karti_uret_9_16()` ve `piyasa_tablosu_uret_9_16()` ile hiçbir blur/çerçeve olmadan doğrudan 1920px dikey ekranda tam ekran infografik olarak çizilir.
- **Tasarım:** *Derin Okyanus Petrolü* zemin (`#04181C`), *Siber Turkuaz* parıltılı rozet (`#06B6D4`), canlı Gram Altın/Gümüş TL çevrimi ve 30 günlük Yahoo Finance sparkline trend çizgileri.

### B. Tek Merkezli Komut Sözlüğü (`src/komutlar.py`) & Modüler Handler Katmanı (`src/handlers/`)
- **Single Source of Truth (`src/komutlar.py`):** `MESAJSIZ_KOMUTLAR`, `KOMUT_MENUSU` ve yetki yönetimi tek merkezde toplandı.
- **Modüler Handler Katmanı (`src/handlers/`):**
  * `yayin_yonetimi.py`: Çoklu platform yayını, telafi, URL doğrulama ve zamanlanmış yayınlar.
  * `slayt_yonetimi.py`: Fotoğraf değiştirme, AI ile görsel üretme, metin düzenleme ve slayt silme.
  * `tur_yonetimi.py`: Tur yaşam döngüsü, aday seçimi, başlık onayı, arama ve erteleme/iptal.
- **Telegram Slash Menüsü:** `/dosya`, `/kronoloji`, `/link`, `/arastir`, `/sondakika`, `/piyasa`, `/yonetim`, `/temizle` resmi olarak `setMyCommands` ile kaydedildi.

### C. A'dan Z'ye Perde Arkası Dosya Haberi Motoru (`/dosya <KONU>`, `src/ozel_haber.py`)
- Verilen konunun (örn. davalar, teftişler, şirket krizleri) başından günümüze kadarki tüm kronolojisini, ara bilirkişi raporlarını ve gelinen son hukuki durumu 3 ferah paragraflı, kilit verili derinlemesine bir bültene dönüştürür.

### D. Kurumsal Marka Kimliği & 144px 3D Logo (`src/slaytlar.py` & `src/make_image.py`)
- Slaytlardaki marka logosu 144x144 px boyutundadır. Arka planında çok katmanlı 14px Gaussian Blur gölge ile 3D kabartma derinliği bulunur.
- Slaytların sağ alt köşesinde 6 platformun (`Instagram`, `Threads`, `Facebook`, `X`, `YouTube`, `TikTok`) resmi kurumsal vektör ikonları yer alır.

### F. Kristal Netlik ve Piksel Yoğunluğu Motoru (`src/gorsel_kalite.py`)
- **Dikey Kırpma Piksel Yoğunluğu Denetimi:** 16:9 yatay görsellerin 4:5 veya 9:16'ya kırpılırken piksellenmesi engellenir. Dikey kırpma ölçeği $< 0.88x$ olan veya büyütme (upscale) gerektiren fotoğraflar elenir.
- **Laplacian Netlik Varyansı:** Yapay büyütülmüş, düşük bitrate'li TV ekran yakalamaları ve bulanık fotoğraflar elenir (Asgari netlik varyansı $\ge 90.0$).
- **Kristal Keskinleştirme (`kristal_netlestir`):** Seçilen kaliteli fotoğraflar UnsharpMask ile pürüzsüz ve kristal netlikte editoryal stile kavuşturulur.

---

## 4. Görsel Seçim Standartları ve İyileştirme Yol Haritası

### 4 Katmanlı Akıllı Görsel Hiyerarşisi:
1. **1. Katman — Web HD / 4K Basın Fotoğrafları Motoru (`src/fetch_web_image.py`):** Doğrudan haber ajanslarının (AA, Reuters, AP, AFP) webde yayınlanan yüksek çözünürlüklü editoryal basın fotoğrafları çekilir.
2. **2. Katman — Akıllı Makale Basın & Ürün Görseli Çekici (`src/fetch_article.py`):** `og:image`, `twitter:image`, JSON-LD `NewsArticle` ve makale gövdesindeki orijinal lansman fotoğrafları taranır ve `gorsel_kalite` denetiminden geçirilir.
3. **3. Katman — Wikimedia Commons & Pexels HD Stok (`src/fetch_photo.py`, `src/fetch_stock.py`):** Kişi portreleri ($\ge 1200\text{px}$) ve 4K dikey temsili stoklar.
4. **4. Katman — Kategoriye Özel Gemini Görsel Motoru (`src/make_image.py`):** Hiçbir katmandan yüksek çözünürlüklü kaliteli fotoğraf bulunamazsa Gemini AI ile özel görsel üretimi.

---

## 5. Dosya ve Dizin Yapısı

| Dizin / Dosya | Görevi |
|---|---|
| `config.yaml` | Tüm bot ayarları, RSS kaynakları, ağırlıklar, eşikler ve sosyal medya anahtarları. |
| `src/gorsel_kalite.py` | Çözünürlük, dikey kırpma piksel yoğunluğu, Laplacian netlik varyansı ve keskinleştirme motoru. |
| `src/fetch_web_image.py` | DuckDuckGo üzerinden HD/4K editoryal basın ve olay fotoğrafları arama motoru. |
| `src/komutlar.py` | Tek merkezli komut listesi, alias'lar, mesajsız serbest komutlar ve slash menü sözlüğü. |
| `src/handlers/` | Modüler Telegram onay ve yayın işleme handler modülleri (`yayin`, `slayt`, `tur`). |
| `src/piyasa.py` | Yahoo Finance canlı veri çekimi, BİST, döviz, emtia, kripto ve Gram TL hesabı. |
| `src/piyasa_kart.py` | 1080x1350 Akış ve 1080x1920 Native Story Canlı Piyasa Isı Haritası motoru. |
| `src/piyasa_tablo.py` | 1080x1350 Akış ve 1080x1920 Native Story 30 Varlık Piyasa Karnesi motoru. |
| `src/sparkline.py` | Borsa ve emtia için 30 günlük geçmiş fiyat çekimi ve estetik trend grafiği çizimi. |
| `src/slaytlar.py` | 4:5 haber slaytlarının ve 9:16 Story slaytlarının çizimi, tipografi, 144px 3D logo. |
| `src/make_image.py` | Pillow tabanlı infografik ve tipografi çizim motoru (`_satirlara_bol`, `_formatli_satir_ciz`). |
| `src/video.py` | 1080x1920 Story slaytlarından dikey video (Reels/Shorts/TikTok) derleme motoru. |
| `src/ozel_haber.py` | Telegram üzerinden `/dosya`, `/kronoloji`, `/link`, `/arastir` ve `/ozel` ile özel haber üretimi. |
| `src/twitter.py` | X (Twitter) API v2 üzerinden 4 fotoğraflı tweet paylaşımı. |
| `src/youtube.py` | YouTube Data API v3 üzerinden 9:16 Shorts video yükleme. |
| `src/tiktok.py` | TikTok Content Posting API v2 üzerinden dikey video yükleme. |
| `src/fetch_news.py` | 20+ RSS kaynağından haberleri çekme, parse etme ve SQLite veritabanına aktarma. |
| `src/generate_text.py` | Gemini Flash modelleri ile başlık, özet, detay metni ve önem puanı üretimi. |
| `scripts/piyasa_otomatik.py`| Hafta içi 10:08 ve 18:20 otomatik Piyasa Bülteni yayınlama scripti. |
| `scripts/son_dakika.py` | Saatlik 5'li haber önerisi akışını yöneten ana script. |
| `scripts/onay_isle.py` | Telegram onay ve komut işleme facade router'ı. |
