# dailybrief.ozbornstudio.com

Daily Brief'in tanıtım + yasal belge sayfaları. **Bot çalışması için gerekli:**
Google OAuth ekranı ("Publish app") bu üç URL'yi zorunlu tutuyor.

## Neden bu klasör burada

Bu sayfalar bir web sitesi projesi değil, **botun bir bağımlılığı**.
YouTube'a yükleme yapabilmek için Google'ın consent screen'i şunları istiyor:

| Google alanı | URL |
|---|---|
| Application home page | `https://dailybrief.ozbornstudio.com` |
| Application privacy policy link | `https://dailybrief.ozbornstudio.com/privacy` |
| Application terms of service link | `https://dailybrief.ozbornstudio.com/terms` |
| Authorized domain | `ozbornstudio.com` (alt alan adlarını da kapsar) |

## Dosyalar

**Yayına yüklenecekler (5 dosya):**

- `index.html` — tanıtım sayfası, 6 kanal bağlantısı
- `privacy.html` — gizlilik politikası (TR/EN)
- `terms.html` — kullanım koşulları (TR/EN)
- `logo.webp` — 256x256, **16 KB**
- `favicon.png` — 64x64, sekme simgesi

**Yüklenmeyecekler:** `_ortak.css` (HTML'lere gömülü) ve bu README.

### ⚠️ Logo neden iki boyda

Marka logosu ayrıntılı bir rozet (küre, RSS dalgaları, kabartma DB
harfleri). **40px'te koyu zeminde lekeye dönüşüyor** — denendi ve
görüldü. Bu yüzden:

| yer | boy | sınıf |
|---|---|---|
| ana sayfa, ortalanmış | 104px | `.kahraman img` |
| yasal sayfaların üst şeridi | 46px | `img.rozet` |

### ⚠️ Neden WebP

Aynı 256px logo: **PNG 106 KB → WebP 16 KB** (6,6 kat). Ölçüldü.
Favicon PNG kaldı; sekme simgesinde WebP desteği daha dar.

`_ortak.css` değiştirirsen üç HTML'in `<style>` bloğunu yeniden
üretmeyi unutma — stil gömülü, ayrı dosya olarak sunulmuyor.

## Cloudflare Pages'e yayınlama

1. Cloudflare → **Workers & Pages** → **Create** → **Pages** →
   **Upload assets** (git bağlamaya gerek yok, üç dosya)
2. Proje adı: `dailybrief`
3. `index.html`, `privacy.html`, `terms.html` dosyalarını yükle
4. **Custom domains** → **Set up a custom domain** →
   `dailybrief.ozbornstudio.com` → Cloudflare DNS kaydını kendisi ekler
5. Doğrula:
   ```
   curl -o /dev/null -w "%{http_code}\n" https://dailybrief.ozbornstudio.com/privacy
   ```

`/privacy` ve `/terms` uzantısız çalışır — Pages `.html` uzantısını
kendiliğinden çözüyor.

## İçerik doğruluğu

⚠️ Metinler botun **gerçekte ne yaptığına** göre yazıldı, şablon değil:
veri toplamıyor, çerez kullanmıyor, yalnızca kamuya açık RSS işliyor,
kayıtları 3 günde siliyor (`genel.kayit_saklama_gun`). Botun davranışı
değişirse bu sayfalar da güncellenmeli.

⚠️ Kanal bağlantılarının hepsi canlı doğrulandı (HTTP 200). Facebook
sayfasının kısa adı yok; Graph API'nin verdiği sayısal adres kanonik.
