# Adım 1 — RSS'ten haber çekme

Bu adımda **hiçbir API key gerekmiyor.** Sadece çalıştır ve sonucu bana gönder.

## Kurulum (bir kere)

Bilgisayarında bir klasör aç, zip'in içindekileri oraya çıkar. Sonra terminalde:

```bash
cd haber-bot

# sanal ortam (proje kütüphanelerini sistemden ayırır)
python3 -m venv .venv
source .venv/bin/activate        # Windows'ta:  .venv\Scripts\activate

pip install -r requirements.txt
```

## Çalıştır

```bash
python scripts/test_1_rss.py
```

## Ne göreceksin

Üç bölümlük bir çıktı:

1. **Kaynak tablosu** — 8 haber kaynağının hangisi çalıştı, hangisi hata verdi
2. **Veritabanı durumu** — kaç haber var, hangi kaynaktan
3. **Sıradaki 10 haber** — Adım 2'de Gemini'ye gidecek olanlar

Scripti **iki kez** çalıştır. İkinci seferde "YENİ" sütununun 0, "TEKRAR" sütununun dolu olması lazım — bu, aynı haberin iki kez paylaşılmayacağının kanıtı.

## Bana ne göndereceksin

Çıktının tamamını kopyala gönder. Özellikle şuna bakacağım:

- **Hata veren kaynak var mı?** Bazı Türk haber siteleri Cloudflare korumalı; senin ev IP'nden çalışsa bile GitHub Actions'ın veri merkezi IP'sinden 403 dönebilir. Hangileri sağlam, birlikte göreceğiz.
- **Haber sayısı makul mü?** Çok az geliyorsa `config.yaml` içindeki `haber_yasi_saat` değerini artırırız.

## Ayar yapmak istersen

`config.yaml` dosyası okunması kolay olsun diye Türkçe yazıldı:

- Bir kaynağı kapatmak → `aktif: false`
- Yeni kaynak eklemek → listeye aynı formatta ekle
- Daha eski haberleri de almak → `haber_yasi_saat: 48`
- Bir kaynağın önceliğini artırmak → `agirlik` değerini yükselt

## Veritabanına doğrudan bakmak istersen

SQL bildiğin için en rahat edeceğin yer burası:

```bash
sqlite3 data/haber.db
```

```sql
.headers on
.mode column

SELECT kaynak, COUNT(*) FROM haberler GROUP BY kaynak;

SELECT kaynak, baslik_orj, yayin_tarihi
FROM haberler
WHERE kategori = 'turkiye'
ORDER BY yayin_tarihi DESC
LIMIT 10;
```

## Bu adımda test edilmiş olanlar

Kodu sana göndermeden önce burada şunları doğruladım:

- RSS 2.0 **ve** Atom formatı ayrıştırma
- CDATA blokları ve özet içindeki HTML etiketlerinin temizlenmesi
- Türkçe karakterler (ğ ş ı İ ç ö ü Ğ Ş Ç Ö Ü) bozulmadan geliyor
- Farklı tarih formatlarının UTC'ye normalize edilmesi
- Yaş sınırından eski haberlerin elenmesi
- **Tekrar engeli**: aynı feed ikinci kez okunduğunda 0 yeni kayıt
- Bir kaynak çökerse (404/timeout) diğerlerinin etkilenmemesi
