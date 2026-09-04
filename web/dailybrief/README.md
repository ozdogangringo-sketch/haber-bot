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

- `index.html` — tanıtım sayfası, kanal bağlantıları
- `privacy.html` — gizlilik politikası (TR/EN)
- `terms.html` — kullanım koşulları (TR/EN)
- `_ortak.css` — kaynak stil; **HTML'lere gömülü** olduğu için yayına
  kopyalanması gerekmez. Değiştirirsen sayfaları yeniden üret.

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
