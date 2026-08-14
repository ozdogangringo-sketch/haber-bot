# Instagram Haber Botu — Yol Haritası

**Hedef:** Günde 1-3 kez, RSS'ten haber çek → Gemini ile Türkçe başlık/caption/hashtag üret → 1080x1080 görsel bas → Telegram'dan sana onay sor → onaylarsan Instagram'a yayınla.

**Çalışma ortamı:** Sürekli açık bırakacağın Android telefon, Termux üzerinde Python + zamanlayıcı.

---

## 0. Önce bir uyarı: telefon şart değil

Sunucu ücreti ödemek istememen çok mantıklı. Ama **GitHub Actions** bu iş için tamamen ücretsiz ve hiçbir cihazın açık kalmasına gerek yok — cron ile günde istediğin saatte tetiklenir, API key'leri "Secrets" kısmında güvenle saklar.

Karşılaştırma:

| | Telefon + Termux | GitHub Actions |
|---|---|---|
| Ücret | 0 TL | 0 TL |
| Cihaz açık kalmalı mı | Evet (şarj + wifi) | Hayır |
| Kurulum zorluğu | Orta (Termux tuhaflıkları var) | Kolay |
| Telegram onayı çalışır mı | Evet | Evet (2 aşamalı workflow ile) |
| Elektrik/wifi kesintisi | Post kaçar | Etkilenmez |

**Önemli:** Yazacağımız Python kodu **her iki ortamda da aynı**. Sadece "zamanlayıcı katmanı" değişiyor. Yani telefonla başlayıp sonra GitHub Actions'a taşımak 10 dakikalık iş. Sen telefonla devam etmek istiyorsan aynen planladığımız gibi gidiyoruz — bunu sadece bilmen için yazdım.

---

## 1. Mimari (veri nasıl akıyor)

```
[RSS feed'ler]
      |
      v
 fetch_news.py  --> SQLite'a yaz (daha önce paylaşıldı mı? kontrolü)
      |
      v
 generate_text.py  --> Gemini API --> {başlık, caption, hashtagler}
      |
      v
 make_image.py  --> Pillow --> assets/template.jpg üstüne başlık --> output/post_123.jpg
      |
      v
 upload_image.py --> imgbb --> https://i.ibb.co/.../post_123.jpg   (public URL)
      |                          ^ Instagram bunu ZORUNLU istiyor
      v
 telegram_bot.py --> sana görsel + caption gönderir
      |                [Yayınla] [Atla] [Yeniden üret]
      v (sen "Yayınla" dersen)
 instagram.py --> POST /media (container) --> POST /media_publish
      |
      v
 SQLite'a "yayınlandı" olarak işaretle
```

### Neden imgbb / public URL adımı var?

Instagram Graph API görseli **senden dosya olarak kabul etmiyor**. Sadece internetten erişilebilir bir JPEG URL'i istiyor. Telefonun evdeki wifi'da olduğu için dışarıdan erişilemez → o yüzden görseli önce ücretsiz bir yere yükleyip URL'ini alıyoruz. imgbb bunun en basit yolu (tek API key, 5 satır kod). İleride Cloudflare R2'ye geçmek istersen sadece bu dosyayı değiştiririz.

**Not:** Instagram sadece **JPEG** kabul ediyor, PNG değil. Ve 24 saatte en fazla 100 post sınırı var — bizim için sorun değil.

---

## 2. Klasör yapısı

Telefonda Termux açıldığında ana klasörün `/data/data/com.termux/files/home` oluyor, kısaca `~`. Projeyi oraya kuruyoruz:

```
~/haber-bot/
│
├── .env                    # TÜM API key'ler burada. Asla git'e girmez.
├── .env.example            # Boş şablon (hangi key'ler lazım görürsün)
├── .gitignore              # .env, data/, logs/ ignore edilir
├── requirements.txt        # Python kütüphaneleri
├── config.yaml             # RSS listesi, post saatleri, ayarlar (key YOK)
│
├── run.py                  # ANA DOSYA — her şeyi sırayla çalıştırır
│
├── src/
│   ├── __init__.py
│   ├── db.py               # SQLite işlemleri (senin alanın :)
│   ├── fetch_news.py       # ADIM 1 — RSS çekme + tekrar filtresi
│   ├── generate_text.py    # ADIM 2 — Gemini ile metin
│   ├── make_image.py       # ADIM 3 — Pillow ile görsel
│   ├── upload_image.py     # ADIM 4a — imgbb'ye yükle, URL al
│   ├── instagram.py        # ADIM 4b — Graph API ile yayınla
│   ├── telegram_bot.py     # ADIM 5 — onay akışı
│   └── refresh_token.py    # Instagram token'ı 60 günde bir yeniler
│
├── assets/
│   ├── template.jpg        # 1080x1080 sabit şablon (senin tasarımın)
│   └── fonts/
│       └── Inter-Bold.ttf  # Türkçe karakter (ğ ş ı İ ç ö ü) destekli font
│
├── data/
│   ├── haber.db            # SQLite: haberler, durumlar, geçmiş
│   └── output/             # üretilen görseller (post_20260814_1.jpg)
│
├── logs/
│   └── bot.log             # ne oldu ne bitti — hata ayıklarken bakacağız
│
└── scripts/
    ├── test_1_rss.py       # her adımı tek başına test eden scriptler
    ├── test_2_gemini.py
    ├── test_3_image.py
    ├── test_4_instagram.py
    └── test_5_telegram.py
```

**Prensip:** Her `src/` dosyası tek işi yapıyor ve tek başına test edilebiliyor. Bir adım çalışmadan diğerine geçmeyeceğiz — `scripts/test_*.py` dosyaları tam olarak bunun için.

### SQLite tablosu (senin bildiğin dil)

```sql
CREATE TABLE haberler (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    kaynak        TEXT NOT NULL,        -- 'AA', 'NTV', 'BBC World'
    baslik_orj    TEXT NOT NULL,        -- RSS'ten gelen orijinal başlık
    link          TEXT NOT NULL UNIQUE, -- tekrar engelinin anahtarı
    ozet_orj      TEXT,
    yayin_tarihi  TEXT,                 -- RSS'teki tarih
    cekilme_zamani TEXT DEFAULT CURRENT_TIMESTAMP,

    ig_baslik     TEXT,                 -- Gemini'nin ürettiği
    ig_caption    TEXT,
    ig_hashtag    TEXT,
    gorsel_yolu   TEXT,
    gorsel_url    TEXT,                 -- imgbb linki

    durum         TEXT DEFAULT 'yeni',  -- yeni | metin_hazir | gorsel_hazir
                                        -- | onay_bekliyor | yayinlandi | atlandi | hata
    ig_post_id    TEXT,                 -- Instagram'ın döndürdüğü ID
    hata_mesaji   TEXT
);
```

`link` UNIQUE olduğu için aynı haber iki kez asla paylaşılmıyor — veritabanı bunu kendisi engelliyor.

---

## 3. Adım adım yol haritası

Her adım bittiğinde çalıştığını **gözünle göreceksin**, sonra diğerine geçeceğiz.

| Adım | Ne yapacağız | Bitince ne göreceksin | Tahmini süre |
|---|---|---|---|
| **0** | Termux kurulumu, Python, klasör, `.env` iskeleti | `python --version` çalışıyor | 20 dk |
| **1** | RSS çekme + SQLite'a yazma | Terminalde 10 haber başlığı listelenir | 30 dk |
| **2** | Gemini ile Türkçe başlık/caption/hashtag | Her haber için üretilmiş metni görürsün | 30 dk |
| **3** | Pillow ile 1080x1080 görsel | Telefonun galerisinde hazır görsel | 45 dk |
| **4a** | imgbb'ye yükleme | Tarayıcıda açılan bir görsel linki | 15 dk |
| **4b** | Instagram'a yayınlama | Hesabına gerçekten post düşer | 45 dk |
| **5** | Telegram onay akışı | Telefonuna butonlu mesaj gelir | 45 dk |
| **6** | Zamanlama (günde X kez otomatik) | Sen hiçbir şey yapmadan mesaj gelir | 30 dk |
| **7** | Token yenileme + hata bildirimi | 60 günde bir kendini yeniler | 20 dk |

Toplam ~5 saat, ama tek oturumda yapmak zorunda değiliz.

---

## 4. Sen ne hazırlayacaksın (ADIM 1'e başlamadan önce)

Bu listeyi bitirmen lazım. Sırayla git, takıldığın yerde sor.

### A) Instagram + Meta tarafı (en zahmetli kısım, ~30 dk)

1. **Instagram hesabını Professional yap**
   Instagram → Ayarlar → Hesap türü → *Profesyonel hesaba geç* → **Business** seç (Creator DEĞİL, Creator'da yayın API'si kısıtlı).

2. **Bir Facebook Sayfası (Page) aç**
   Boş bir sayfa yeter, kimse görmeyecek. facebook.com → Sayfalar → Yeni sayfa.

3. **Instagram'ı bu sayfaya bağla**
   Instagram uygulaması → Ayarlar → *Hesap merkezi* → Facebook hesabını/sayfasını bağla.
   Kontrol: Facebook Sayfa ayarlarında "Bağlı Instagram hesabı" görünmeli.

4. **Meta Developer hesabı aç ve uygulama oluştur**
   [developers.facebook.com](https://developers.facebook.com) → Giriş yap → *My Apps* → *Create App* → tür olarak **Business** seç.

5. **Uygulamaya Instagram ürününü ekle**
   App Dashboard → *Add Product* → **Instagram** → *Set up*.

6. **Access Token üret**
   [Graph API Explorer](https://developers.facebook.com/tools/explorer/) → uygulamanı seç → şu izinleri işaretle:
   - `instagram_basic`
   - `instagram_content_publish`
   - `pages_show_list`
   - `pages_read_engagement`
   - `business_management`

   → *Generate Access Token* → Facebook izin ekranını onayla.

   > Kendi hesabına post attığın ve uygulamanın admin'i sen olduğun için **App Review gerekmiyor**. Doğru anlamışsın.

7. **Uzun ömürlü token'a çevir** — Explorer'ın verdiği token 1 saatte ölüyor. 60 günlük olanı Adım 4b'de birlikte alacağız.

8. **Instagram User ID'ni bul** — bunu da Adım 4b'de kod ile bulacağız, şimdilik dert etme.

**Bana lazım olacak:** App ID, App Secret, kısa ömürlü token (Adım 4b'de).

---

### B) Google Gemini (5 dk, ücretsiz, kredi kartı istemiyor)

1. [aistudio.google.com/apikey](https://aistudio.google.com/apikey) → Google hesabınla gir
2. *Create API key* → kopyala, bir yere kaydet

Ücretsiz katman günde birkaç post için fazlasıyla yeterli. Kesin limitleri AI Studio panelinde görebilirsin.

---

### C) Telegram bot (5 dk)

1. Telegram'da **@BotFather**'a yaz → `/newbot` → isim ve kullanıcı adı ver → sana bir **token** verir
2. **@userinfobot**'a yaz → sana **chat ID**'ni (bir sayı) verir
3. Kendi botuna bir kez `/start` yaz (yoksa bot sana mesaj atamaz)

---

### D) imgbb (2 dk, ücretsiz)

1. [api.imgbb.com](https://api.imgbb.com/) → *Get API key* → hesap aç → key'i kopyala

---

### E) Telefon tarafı (~20 dk)

1. **Termux'u F-Droid'den kur** — [f-droid.org/packages/com.termux](https://f-droid.org/packages/com.termux/)
   ⚠️ **Play Store'daki Termux'u KURMA**, çok eski ve bozuk. F-Droid veya GitHub Releases.
2. **Termux:API** uygulamasını da aynı yerden kur (zamanlama için lazım).
3. Telefon ayarları → Pil → Termux için **pil optimizasyonunu kapat** (yoksa Android uygulamayı öldürür).
4. Telefonu şarjda ve wifi'da tut.

Termux komutlarını Adım 0'da ben yazacağım, şimdilik sadece uygulamayı kur.

---

### F) Görsel şablon (senin tasarım kararın)

Bana bir **1080x1080 JPEG** şablon lazım. İçinde:
- Üstte veya altta logo/hesap adı alanı
- Ortada başlığın basılacağı boş/koyu bir alan (metin okunabilsin)
- İstersen alt köşede kaynak yazısı için yer

Canva'da 5 dakikada yapılır. Hazır değilse Adım 3'te sana geçici bir tane üretirim, sonra değiştiririz.

---

## 5. `.env` dosyasında ne olacak

```bash
# --- Instagram / Meta ---
IG_USER_ID=
IG_ACCESS_TOKEN=
META_APP_ID=
META_APP_SECRET=

# --- Gemini ---
GEMINI_API_KEY=

# --- Telegram ---
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# --- imgbb ---
IMGBB_API_KEY=
```

Kodda hiçbir key yazmayacak; hepsi buradan `os.getenv()` ile okunacak. `.gitignore`'a ilk satır olarak `.env` yazacağız.

---

## 6. Bilmen gereken riskler

| Risk | Ne olur | Çözümümüz |
|---|---|---|
| Instagram token 60 günde ölür | Bot sessizce durur | Adım 7'de otomatik yenileme + Telegram uyarısı |
| Telefon kapanır/wifi gider | Post kaçar | Telegram'a "çalışamadım" mesajı; ya da GitHub Actions'a taşımak |
| Gemini yanlış/taraflı metin üretir | Yanlış haber paylaşırsın | Telegram onayı tam olarak bunun için var |
| RSS kaynağı çöker | Haber gelmez | Birden fazla kaynak + hata yakalama |
| Aynı haber tekrar paylaşılır | Spam görünür | SQLite `link UNIQUE` |
| Telif / haber görseli kullanımı | Şikâyet | Haber görseli kullanmıyoruz, kendi şablonumuz + kaynak adı yazıyoruz |

**Bir de dürüst not:** Haber içeriğini otomatik üretip yayınlamak, LLM'in başlığı yanlış çerçevelemesi riskini taşıyor. Onay adımını asla kaldırmamanı öneririm — hız kazancı, yanlış bir haberin hesabına düşmesine değmez.

---

## 7. Şimdi ne olacak

Sen yukarıdaki **A–F** listesini hazırla. Bitirdiğinde bana "hazırım" de, **Adım 0 + Adım 1** ile başlayalım:
Termux kurulumu, klasör yapısı ve RSS'ten haberleri çekip SQLite'a yazan ilk çalışan kod.

Bu arada kafana takılan bir şey olursa listenin ortasında da sorabilirsin.
