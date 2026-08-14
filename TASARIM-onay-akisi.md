# Onay ve Zamanlama Tasarımı

Verdiğin kararlara göre nihai akış. Kod yazmadan önce buna bakıp "evet böyle olsun" demeni istiyorum.

## Günlük takvim (Türkiye saati)

```
SABAH TURU
 09:00  ● HAZIRLA   Haber seç → Gemini → görsel → imgbb → Telegram'a butonlu mesaj
         │
         ├─ sen butona bastığın AN (09:02 de olur, 11:47 de) → saniyeler içinde yayınlanır
         │
 10:00  ○ HATIRLAT  Hâlâ cevap yoksa: "⏰ onay bekliyor — 2 şans kaldı"
 11:00  ○ HATIRLAT  "⏰ son hatırlatma — 1 şans kaldı"
 12:00  ○ ERTELE    Cevap yok → haber 'ertelendi' olur, akşam turuna kalır
                    Telegram: "Sabah turu geçildi, akşam tekrar soracağım"

AKŞAM TURU
 20:00  ● HAZIRLA   Ertelenen haber + yeni haberler birlikte yarışır, EN ÖNEMLİSİ seçilir
 21:00  ○ HATIRLAT
 22:00  ○ HATIRLAT
 23:00  ↩ HAVUZA DÖN  Cevap yok → haber elenmez, havuza geri döner
                      ve ertesi sabah yeniden yarışır
```

**Kural:** Bir turda sadece **1 post**. Günde en fazla 2.

---

## Cloudflare Worker ne değiştiriyor

Seçtiğin yol şu: Telegram'daki butona bastığında Telegram, Cloudflare'deki küçük bir programı çağırır; o da GitHub'a "hemen çalış" der. Yayın **saniyeler içinde** olur, saat başını beklemez.

```
[Sen butona basarsın]
        │
        v
[Telegram]  --webhook-->  [Cloudflare Worker]  (~20 satır kod, ücretsiz)
                                 │
                                 │ 1. Butona basanın sen olduğunu doğrular
                                 │ 2. GitHub'a repository_dispatch atar
                                 v
                          [GitHub Actions "yayinla" job'ı]
                                 │
                                 v
                          Instagram'a post + Telegram mesajını
                          "✅ Yayınlandı" olarak günceller
```

### Yan etkisi (bilmen gereken tek şey)

Telegram'da **webhook ile getUpdates aynı anda kullanılamaz.** Webhook kurunca bot artık "mesajları çekme" moduna giremez.

Bu bizim için **iyi** bir haber: saat başı çalışan job'lar artık Telegram'ı hiç okumuyor. Sadece veritabanına bakıp "bu haber hâlâ onay bekliyor mu?" diye kontrol ediyorlar, bekliyorsa hatırlatma atıyorlar. Yani o job'lar hem daha basit hem daha hızlı hem daha ucuz.

**Küçük bir yarış durumu:** 09:59'da onaylarsan ve 10:00 hatırlatma job'ı veritabanı güncellenmeden çalışırsa gereksiz bir hatırlatma gelebilir. Nadir ve zararsız — yayın mesajı zaten "✅ Yayınlandı" olarak güncellenmiş olacağı için karışıklık olmaz.

---

## "En önemlisi" nasıl seçiliyor

Sabahki haber akşama ertelendiğinde hepsini üst üste yığmak istemediğini söyledin. Çözüm: her haberin bir **önem puanı** olacak ve akşam turunda sadece en yükseği seçilecek.

Puanı Gemini üretecek (Adım 2'de), 1–10 arası. Seçim skoru:

```
skor = onem_puani × 10          -- Gemini'nin değerlendirmesi (ana faktör)
     + agirlik                   -- config.yaml'deki kaynak önceliği
     - tazelik_cezasi            -- haber başına saat başı -1 puan
     - 15  (eğer kategori='dunya' ve onem_puani < 8)   -- dünya haberi sadece kritikse
```

Ertelenen haber bu skorla yeni haberlere karşı yarışır:

- Gerçekten önemliyse (deprem, seçim, büyük ekonomik gelişme) → yüksek puan, yaşlanma cezasını yener, bir sonraki turda yayınlanır
- Sıradan bir haberse → taze haberler onu geçer, sessizce havuzda kalır

## Hiçbir haber elenmiyor

"Akşam haberi elenmesin" dedin — ve aslında bu bedava, çünkü zaten öyle çalışıyor.

Veritabanında her an yüzlerce haber var (8 kaynak × 15 haber × günde birkaç çekim). Bunların ezici çoğunluğu hiç yayınlanmıyor — sadece havuzda duruyorlar. Onay vermediğin haberin "elenmesi" ile "havuzda kalması" arasındaki tek fark, bir sonraki turda tekrar aday olup olmaması.

Yeni davranış: **hiçbir haber elenmiyor.** Onay vermediğin haber havuza dönüyor ve ertesi tur yeniden yarışıyor. Kuyruk şişmesi diye bir sorun yok, çünkü her turda yalnızca **en yüksek skorlu tek haber** seçiliyor — havuzda 3 tane mi 300 tane mi beklediği hiçbir şeyi değiştirmiyor.

Ertelenen haberin ürettiğimiz başlığı, caption'ı ve görseli saklanıyor. Tekrar seçilirse Gemini'yi ve görsel üretimini baştan çalıştırmıyoruz — bedava geliyor.

**Tek sınır — bayatlama:** Bir haber yayın tarihinden 48 saat sonra aday olmayı bırakıyor (`config.yaml` → `yayin_yasi_siniri_saat`). Bu bir ceza değil, gerçeklik: 2 gün önceki haberi "günün haberi" diye paylaşmak hesabın itibarına zarar verir. Süreyi uzatmak istersen tek satır.

---

## "Atla" butonuna basınca

Seçtiğin davranış: sıradaki haberi öner.

```
09:00  1. haber gönderildi
09:04  sen [Atla] dedin
       → o haber 'atlandi', ANINDA 2. haber hazırlanıp gönderilir
09:06  sen [Atla] dedin
       → 3. haber gönderilir
09:08  sen [Yayınla] dedin
       → yayınlanır, tur kapanır
```

Worker sayesinde bu da anında oluyor — her "Atla"da bir sonraki haber saniyeler içinde geliyor.

**Sınır:** Bir turda en fazla 5 "Atla" hakkı. Sonrasında "bugün sabah için uygun haber bulamadım" mesajı gelir ve tur kapanır. (Yoksa 40 haberi tek tek eleme riski var.)

---

## Telegram mesajı neye benzeyecek

```
┌──────────────────────────────────┐
│  [1080x1080 görsel önizlemesi]   │
└──────────────────────────────────┘
📰 TRT Haber · Türkiye · önem 7/10
🕐 2 saat önce

BAŞLIK:
Türkiye ile Mısır arasında 5 anlaşma imzalandı

CAPTION:
Ankara'da düzenlenen törende iki ülke arasında
ticaret ve enerji alanında beş mutabakat zaptı
imzalandı. Anlaşmaların yıllık ticaret hacmini
%30 artırması bekleniyor.

#gündem #türkiye #mısır #ekonomi #haber

[ ✅ Yayınla ]  [ ⏭ Atla ]  [ 🔄 Metni yeniden üret ]
```

Üçüncü butonu ekledim: başlık/caption beğenmediysen aynı haber için Gemini'ye tekrar ürettirir. Aynı haberi atlamak zorunda kalmazsın.

---

## Bu tasarımın maliyeti

| İş | Günde | Süre | Aylık |
|---|---|---|---|
| Hazırla job (sabah + akşam) | 2 | ~2 dk | 120 dk |
| Hatırlatma job'ları | 6 | ~1 dk | 180 dk |
| Yayınla job (buton tetikli) | ~2 | ~2 dk | 120 dk |
| **Toplam** | | | **~420 dk** |

2000 dk ücretsiz kotanın **%21'i**. Rahat rahat sığıyor, "Atla"ya çok bassan bile sorun yok.

Cloudflare Worker: günde 100.000 istek ücretsiz. Biz günde ~10 istek atacağız.

---

## Veritabanına eklenenler

```sql
ALTER TABLE haberler ADD COLUMN tur                 TEXT;     -- 'sabah' | 'aksam'
ALTER TABLE haberler ADD COLUMN onem_puani          INTEGER;  -- Gemini: 1-10
ALTER TABLE haberler ADD COLUMN telegram_message_id INTEGER;  -- mesajı güncellemek için
ALTER TABLE haberler ADD COLUMN hatirlatma_sayisi   INTEGER DEFAULT 0;
ALTER TABLE haberler ADD COLUMN ertelenme_sayisi    INTEGER DEFAULT 0;
ALTER TABLE haberler ADD COLUMN gonderim_zamani     TEXT;     -- Telegram'a gittiği an
```

Yeni `durum` değerleri: `ertelendi` (sabahtan akşama kalan), `yeniden_uretilecek`.

Bu kolonlar `src/db.py` içine eklendi ve **otomatik migration** yazdım — elindeki veritabanını silmene gerek yok, kod eksik kolonları kendisi ekliyor.

---

## Ön hazırlık listene eklenenler

Cloudflare Worker seçimi iki yeni madde getirdi. **Şimdi yapma**, Adım 5'e geldiğimizde birlikte yapacağız — sadece haberin olsun:

**G) Cloudflare hesabı** — [dash.cloudflare.com](https://dash.cloudflare.com) → ücretsiz kayıt. Kredi kartı istemiyor. Worker'ı ben yazacağım, sen kopyala-yapıştır yapacaksın.

**H) GitHub Personal Access Token** — Worker'ın senin repo'nu tetikleyebilmesi için. GitHub → Settings → Developer settings → Fine-grained tokens → sadece bu repo'ya, sadece `Contents: write` izniyle. Token'ı Cloudflare'e secret olarak koyacağız, kimse göremez.

---

## Kararlar (kapandı)

- ✅ Hiçbir haber elenmiyor — onay verilmeyen haber havuza dönüp yeniden yarışıyor
- ✅ Bayatlama sınırı: 48 saat (`config.yaml`'den değiştirilebilir)
- ✅ Tur başına 5 "Atla" hakkı
- ✅ "🔄 Metni yeniden üret" butonu var
