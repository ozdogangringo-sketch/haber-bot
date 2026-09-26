/**
 * Cloudflare Worker — Telegram butonu ile GitHub Actions arasındaki köprü.
 *
 * NEDEN VAR:
 *   Telegram bir butona basıldığında bunu bir adrese POST etmek istiyor
 *   (webhook). Sürekli açık sunucumuz yok. Worker sadece istek geldiğinde
 *   çalışıyor, boştayken hiçbir şey tüketmiyor. Bedava katman günde
 *   100.000 istek; bizim ihtiyacımız günde ~5.
 *
 * AKIŞ:
 *   Telegram butonu -> bu Worker -> GitHub repository_dispatch
 *                                -> .github/workflows/yayinla.yml
 *
 * GÜVENLİK:
 *   Worker'ın adresi herkese açık. Doğrulama yapmazsak adresi bilen
 *   herkes "yayınla" komutu gönderebilir. İki katman var:
 *     1. secret_token başlığı — Telegram her istekte gönderiyor,
 *        webhook kurulurken belirlediğimiz değerle karşılaştırıyoruz.
 *     2. Beklenen komut listesi — tanımadığımız callback_data reddediliyor,
 *        yani GitHub'a keyfi event_type geçirilemiyor.
 *
 *   GITHUB_PAT fine-grained olmalı ve YALNIZCA bu repoya, yalnızca
 *   "Contents: write" iznine sahip olmalı. Worker ele geçse bile
 *   yapılabilecek en kötü şey bu repoyu etkilemek.
 */

// GitHub'a iletilecek gerçek eylemler. İş yapan komutlar.
// "durum" ve "tur" butondan değil, yazılı komuttan geliyor.
// ⚠️ "sondakika" 4 Eyl 2026'ya kadar bu listede YOKTU ama Worker'ın
// kendi menüsünde "🚨 Son Dakika Tara" düğmesi onu gönderiyordu —
// yani Worker kendi bastığı düğmeyi reddediyordu.
const EYLEMLER = ["yayinla", "iptal", "metin_yenile", "foto_degistir", "ertele", "durum", "tur",
                  "sondakika",
                  "ayar", "tamamla", "arsiv", "oneri_gec", "tura_birak", "cope_at",
                  "plan_iptal", "havuz_guncelle", "havuzdan_ekle",
                  "manuel_paket", "yayinla_diger", "manuel_tamam",
                  // Fotoğraf ve metin alt menü eylemleri
                  "foto_gercek", "foto_stok", "foto_ai", "foto_orijinal",
                  "metin_ozetle", "metin_detaylandir", "metin_kaynak_arastir",
                  // Yönetim & Acil durum kontrolleri
                  "yonetim", "yonetim_panel", "devam_et", "saglik_testi",
                  "kota", "kota_raporu", "kota_tazele", "kota_goster", "kota_menu", "tur_temizle", "tur_hazirla", "ekonomi_hazirla", "ekonomi",
                  "piyasa", "piyasa_ozet", "piyasa_yayinla", "piyasa_onizle", "ekonomi_yayinla",
                  "bulten", "sonpostlar", "son_postlar",
                  // Tur başlık önizlemesi (iki aşamalı tur akışı)
                  "tur_onayla", "tur_yeniden"];
// Sayı parametresi alan eylemler: "slayt_ai:3", "slayt_sil:7", "slayt_elle:3", "slayt_yukari:3" ...
const PARAMETRELI_EYLEM =
  /^(slayt_carpici|slayt_ai|slayt_foto|slayt_metin|slayt_kaynak|slayt_elle|slayt_sil|slayt_yukari|slayt_asagi|slayt_basa|sansur_kaldir|sansur_uygula|metin_uzat|metin_kisalt|cope_at_tekil):([1-9]|10)$/;

// Kota kategori eylemleri: "kota_kat:1", "kota_kat:2", "kota_kat:menu"
const KOTA_KAT = /^kota_kat:(1|2|menu)$/;

// Botu duraklatma (1s, 6s, 12s, 24s)
const DURAKLAT = /^duraklat:(1|6|12|24)$/;

// Görsel önizleme düğmeleri: "gorsel_kabul:{slayt}:{turMesajId}".
// ⚠️ Tur id'si komutta — önizleme AYRI bir mesajda duruyor ve
// cb.message.message_id turu göstermiyor.
const GORSEL_ONAY = /^(gorsel_kabul|gorsel_yeni):([1-9]|10):\d{1,12}$/;

// Zamanlanmış yayın: "yayinla_sonra:60" -> 60 dakika sonra yayınla.
// ⚠️ DEĞERLER 30'UN KATLARI ve serbest sayı DEĞİL. Zamanı gelen turu
// son dakika kontrolü yayınlıyor, o cron 30 dakikada bir çalışıyor;
// "15 dk" kabul etseydik gerçekte 15-45 dakika arası yayınlanır ve
// düğme yalan söylerdi.
const YAYINLA_SONRA = /^yayinla_sonra:(30|60|120|180|240)$/;

// "🎙️ Sesli Yayınla" (2026-09-26, postedm'den): "yayinla_ses:muzikli" ve
// "yayinla_ses_sonra:muziksiz:60". GitHub'a YENİ komut gitmez: Worker bunları
// "yayinla" / "yayinla_sonra:N"e çevirip kanal listesine ses_muzikli /
// ses_muziksiz ekler. Planlı yayın ve çalar saati olduğu gibi çalışır; plan
// yayin_kanallari'na kanal listesiyle birlikte yazıldığı için kip de taşınır.
const SESLI_YAYIN = /^yayinla_ses:(muzikli|muziksiz)$|^yayinla_ses_sonra:(muzikli|muziksiz):(30|60|120|180|240)$/;
const VIDEO_KANALLARI = ["reels", "facebook", "youtube", "tiktok"];

// Turdaki bir haberi başkasıyla değiştirme.
//   "haber_degistir:3"      -> 3. slayt için 2 alternatif iste
//   "haber_sec:3:16380"     -> 3. slayta 16380 numaralı haberi koy
// id yalnızca rakam; slayt numarası 1-10 (Instagram carousel sınırı).
const HABER_DEGISTIR = /^haber_degistir:([1-9]|10)$/;
// ⚠️ Tur mesaj id'si komutun İÇİNDE ("haber_sec:5:16380:474"). Bu düğme
// ayrı bir mesajda duruyor; cb.message.message_id turu göstermiyor.
// haber_sec:{eskiHaberId}:{yeniHaberId}:{turMesajId}
// ⚠️ İlk alan SLAYT NUMARASI DEĞİL haber id'si — numara tur
// yeniden sıralanınca kayıyor ve yanlış slaydı hedefliyor.
const HABER_SEC = /^haber_sec:\d{1,8}:\d{1,8}:\d{1,12}$/;
const HABER_VAZGEC = /^haber_vazgec:\d{1,12}$/;

// Yayın doğrulama düğmeleri. Tur mesaj id'si komutun İÇİNDE — bu
// düğmeler yayın sonucu / hata mesajında duruyor ve o mesajların
// message_id'si turunkinden farklı.
//   yayin_kontrol:{turMesajId}   -> Instagram'a sorup durumu bildirir
//   yeniden_yayinla:{turMesajId} -> önce kontrol, yayınlanmamışsa yayınlar
const YAYIN_KONTROL = /^yayin_kontrol:\d{1,12}$/;
const YENIDEN_YAYINLA = /^yeniden_yayinla:\d{1,12}$/;
const RETRY_KANAL = /^retry_kanal:(story|facebook|threads|twitter|youtube|tiktok|ig|reels|hepsi):\d{1,12}$/;
const KURTAR = /^kurtar:\d{1,12}$/;

// Üç adaydan seçim: "gorsel_sec:2:3:656" = 2. aday, 3. slayt, tur 656.
// ⚠️ Tur id'si komuta GÖMÜLÜ — düğmeler ayrı bir mesajda duruyor.
const GORSEL_SEC = /^gorsel_sec:[1-9]:([1-9]|10):\d{1,12}$/;

// Durum panelindeki kurtarma düğmeleri: "yayinla:656" / "iptal:656".
// ⚠️ Bu düğmeler AYRI bir mesajda (durum paneli) duruyor, o yüzden tur
// id'sini KOMUTUN İÇİNDE taşıyorlar — Worker'ın gönderdiği mesaj_id
// paneli gösteriyor, turu değil.
// ⚠️ 4 Eyl 2026: panel dört düğme basıyordu ama yalnızca ikisi
// (kurtar, yayin_kontrol) beyaz listedeydi; diğer ikisi "Tanınmayan
// komut" alıyordu. Tur takıldığında açılan panelde, kurtaracak iki
// düğmenin ikisi de ölüydü.
const TUR_EYLEM = /^(yayinla|iptal):\d{1,12}$/;
const FOTO_EYLEM = /^(foto_degistir|foto_gercek|foto_stok|foto_ai):\d{1,12}$/;

// Tekil post ÖNERİSİ: "hazirla:1482" — haber id'si komuta gömülü.
// İki aşamalı akışın ikinci adımı: kontrol job'ı yalnızca başlıkları
// puanlayıp öneriyor, tam metin ve görsel ancak bu butona basılınca
// üretiliyor. id sınırlı biçimde doğrulanıyor (yalnızca rakam).
const HAZIRLA = /^hazirla:\d{1,8}(,\d{1,8}){0,7}$/;

// Tekil post önerisinde ÇOKLU SEÇİM.
// "sec:1482" bir başlığı işaretler/işareti kaldırır — bu GitHub'a
// GİTMİYOR, Worker mesajın butonlarını doğrudan düzenliyor. Actions'ı
// her seçim için uyandırmak 3 haber = 3 ayrı job (~5 dk) demekti.
// "hazirla_secilenler" işaretli olanların hepsini tek dispatch ile
// gönderiyor; id'ler buton metinlerinden okunuyor.
const SEC = /^sec:\d{1,8}$/;
const SECILENLERI_HAZIRLA = "hazirla_secilenler";

// Menü gezinme komutları. Bunlar GitHub'a GİTMİYOR — Actions'ı uyandırmak
// 30+ saniye sürüyor ve menü açmak anında olmalı. Worker mesajın
// butonlarını doğrudan düzenliyor.
const MENU_GEZINME =
  /^(slayt_menu:(\d{1,2})(?::([a-z0-9_,]+))?|geri:(\d{1,2})(?::([a-z0-9_,]+))?|slayt:([1-9]|10):(\d{1,2})(?::([a-z0-9_,]+))?|yayin_menu:(\d{1,2})(?::([a-z0-9_,]+))?|yayin_geri:(\d{1,2})(?::([a-z0-9_,]+))?|foto_menu:(\d{1,2})(?::([a-z0-9_,]+))?|foto_geri:(\d{1,2})(?::([a-z0-9_,]+))?|metin_menu:(\d{1,2})(?::([a-z0-9_,]+))?|metin_geri:(\d{1,2})(?::([a-z0-9_,]+))?|ses_menu:(\d{1,2})(?::([a-z0-9_,]+))?|ses_zaman:(muzikli|muziksiz):(\d{1,2})(?::([a-z0-9_,]+))?)$/;

// Yayından kaldırma. Tur id'si komuta GÖMÜLÜ ("kaldir:144") çünkü bu
// düğme yayın sonucu mesajında duruyor ve o mesajın kendi message_id'si
// turunkinden farklı — cb.message.message_id kullanılırsa yanlış turu
// hedefler.
const KALDIR = /^kaldir:(\d{1,12})$/;

// Ayar düğmeleri: "ayar:genel.gece_otomatik_yayin". Yol beyaz listeye
// karşı GitHub tarafında da doğrulanıyor; buradaki desen yalnızca
// biçim kontrolü.
// Ayar alt menüsü Worker'da açılıyor (anında). Seçenekler düğmenin
// içinde taşınıyor ("ayarmenu:genel.gece_otomatik_yayin:true-false"),
// böylece seçenek listesi yalnızca src/ayar.py'de duruyor — menüyü
// üçüncü bir yerde tekrarlamıyoruz.
const AYAR_MENU = /^ayarmenu:[a-z0-9_.]+:([a-z0-9_-]+)$/;
const AYAR_SEC  = /^ayarsec:[a-z0-9_.]+:([a-z0-9_]+)$/;

// Hata bildirimindeki eylem düğmeleri (src/hata_bildir.py üretiyor).
// "tur_tekrar" ve "tur_metinsiz" GitHub'da tur kurdurur; "ayrinti"
// GitHub'a HİÇ gitmez — Worker ham hata metnini repodan okuyup anında
// cevaplıyor, Actions dakikası harcamıyoruz.
const HATA_EYLEM = /^hata:(tur_tekrar|tur_metinsiz|sondakika_tekrar)$/;
// Son dakika kontrolü kendi workflow'unda çalışıyor; tur eylemlerinden
// AYRI bir event'e gitmeli, yoksa "son dakika hatası" düğmesi akşam
// turunu tetikliyor (20 Ağu 2026'da tam olarak bu oldu).
const SONDAKIKA_EYLEM = "hata:sondakika_tekrar";
const HATA_AYRINTI = "hata:ayrinti";

const MAKRO_EYLEM = /^(makro|faiz|enflasyon|fed):.+$/;
const LINK_EYLEM = /^link:.+$/;
const VARLIK_EYLEM = /^(hisse|kripto):.+$/;
const DOSYA_EYLEM = /^(dosya|kronoloji):.+$/;
const INCELE = /^incele:\d{1,8}$/;

function eylemMi(veri) {
  if (typeof veri !== "string" || veri.length > 500) return false;
  return EYLEMLER.includes(veri) || PARAMETRELI_EYLEM.test(veri)
    || YAYINLA_SONRA.test(veri)
    || HABER_DEGISTIR.test(veri) || HABER_SEC.test(veri)
    || HABER_VAZGEC.test(veri)
    || YAYIN_KONTROL.test(veri) || YENIDEN_YAYINLA.test(veri)
    || RETRY_KANAL.test(veri) || KURTAR.test(veri)
    || GORSEL_ONAY.test(veri)
    || KALDIR.test(veri) || AYAR_SEC.test(veri) || HATA_EYLEM.test(veri)
    || TUR_EYLEM.test(veri) || FOTO_EYLEM.test(veri) || GORSEL_SEC.test(veri)
    || HAZIRLA.test(veri) || veri === SECILENLERI_HAZIRLA
    || DURAKLAT.test(veri) || MAKRO_EYLEM.test(veri) || LINK_EYLEM.test(veri)
    || VARLIK_EYLEM.test(veri) || DOSYA_EYLEM.test(veri) || INCELE.test(veri)
    || KOTA_KAT.test(veri);
}

// Ayar alt menüsü: seçenekler düğmeden okunuyor, geçerli değer
// bilinmediği için işaret KONULMUYOR — onu GitHub tarafı, paneli
// tazelerken gösteriyor.
function ayarAltMenu(yol, kodlar) {
  const goster = (k) => (k === "true" ? "AÇIK" : k === "false" ? "KAPALI" : k);
  const satir = kodlar.split("-").map((k) => ({
    text: goster(k),
    callback_data: `ayarsec:${yol}:${k}`,
  }));
  return { inline_keyboard: [satir, [{ text: "← Ayarlara dön", callback_data: "ayar" }]] };
}

// Kanal seçimi toggle komutu ("kanal:ig", "kanal:reels", "kanal:story", "kanal:threads", "kanal:facebook", "kanal:twitter", "kanal:youtube", "kanal:tiktok")
const KANAL_TOGGLE = /^kanal:(ig|reels|story|threads|facebook|twitter|youtube|tiktok)$/;

function seciliKanallariCikar(klavye) {
  if (!klavye || !klavye.length) return null;
  const kanalButonlari = klavye.flat().filter((b) => String(b.callback_data || "").startsWith("kanal:"));
  if (kanalButonlari.length === 0) return null;
  return kanalButonlari
    .filter((b) => String(b.text || "").startsWith("✅"))
    .map((b) => b.callback_data.slice(6)); // "kanal:ig" -> "ig"
}

const KANAL_KODLARI = {
  ig: "i",
  reels: "r",
  story: "s",
  threads: "t",
  facebook: "f",
  twitter: "x",
  youtube: "y",
  tiktok: "k",
};
const KOD_TO_KANAL = {
  i: "ig",
  r: "reels",
  s: "story",
  t: "threads",
  f: "facebook",
  x: "twitter",
  y: "youtube",
  k: "tiktok",
};

function kanallariKodla(kanallar) {
  if (!kanallar) return "";
  const arr = Array.isArray(kanallar) ? kanallar : (typeof kanallar === "string" ? kanallar.split(",") : []);
  return arr.map((k) => KANAL_KODLARI[k.trim().toLowerCase()] || k.trim()).join(",");
}

function kanallariCoz(str) {
  if (!str) return [];
  return str.split(",").map((s) => KOD_TO_KANAL[s.trim().toLowerCase()] || s.trim().toLowerCase()).filter(Boolean);
}

function kanalButonlariSatirlari(kanallar) {
  const varMi = (k) => {
    if (Array.isArray(kanallar)) return kanallar.includes(k) || kanallar.includes(KANAL_KODLARI[k]);
    if (kanallar && typeof kanallar === "object") return Boolean(kanallar[k]);
    if (k === "reels") return false; // Varsayılan kapalı (Reels, IG post ile çakışmasın)
    return true; // IG, Story, Threads, FB, X, YT, TT varsayılan AKTİF
  };
  return [
    [
      { text: `${varMi('ig') ? '✅' : '⬜'} IG`, callback_data: "kanal:ig" },
      { text: `${varMi('reels') ? '✅' : '⬜'} Reels`, callback_data: "kanal:reels" },
      { text: `${varMi('story') ? '✅' : '⬜'} Story`, callback_data: "kanal:story" },
      { text: `${varMi('threads') ? '✅' : '⬜'} Threads`, callback_data: "kanal:threads" },
    ],
    [
      { text: `${varMi('facebook') ? '✅' : '⬜'} FB`, callback_data: "kanal:facebook" },
      { text: `${varMi('twitter') ? '✅' : '⬜'} X`, callback_data: "kanal:twitter" },
      { text: `${varMi('youtube') ? '✅' : '⬜'} YT`, callback_data: "kanal:youtube" },
      { text: `${varMi('tiktok') ? '✅' : '⬜'} TT`, callback_data: "kanal:tiktok" },
    ],
  ];
}

// ---------------------------------------------------------------------
// Menüler
//
// Bu fonksiyonlar telegram_bot.py'deki karşılıklarının AYNISI olmalı.
// Menü gezinmesi Worker'da yapıldığı için buton düzeni iki yerde
// tanımlı — birini değiştirirsen diğerini de değiştir.
// Slayt sayısı callback_data'ya gömülü ("slayt_menu:10"): Worker'ın
// turda kaç slayt olduğunu başka türlü bilme yolu yok.
// ---------------------------------------------------------------------

function anaMenu(adet, kanallar) {
  const kStr = kanallariKodla(kanallar);
  const yayinCb = kStr ? `yayin_menu:${adet}:${kStr}` : `yayin_menu:${adet}`;
  const sesCb = kStr ? `ses_menu:${adet}:${kStr}` : `ses_menu:${adet}`;
  const slaytCb = kStr ? `slayt_menu:${adet}:${kStr}` : `slayt_menu:${adet}`;
  const fotoCb  = kStr ? `foto_menu:${adet}:${kStr}`  : `foto_menu:${adet}`;
  const metinCb = kStr ? `metin_menu:${adet}:${kStr}` : `metin_menu:${adet}`;
  return {
    inline_keyboard: [
      ...kanalButonlariSatirlari(kanallariCoz(kStr)),
      [{ text: "✅ Yayınla", callback_data: yayinCb },
       { text: "🎙️ Sesli Yayınla", callback_data: sesCb }],
      [{ text: "📲 Manuel Paylaşım Paketi", callback_data: "manuel_paket" }],
      [{ text: "🔄 Başka Fotoğraf Bul", callback_data: fotoCb },
       { text: "✍️ Metinleri Yenile", callback_data: metinCb }],
      [{ text: `🎨 Slayt düzenle (${adet} slayt)`, callback_data: slaytCb }],
      [{ text: "⏰ 1 saat ertele", callback_data: "ertele" }],
      [{ text: "📋 Tekil atma, 10'lu tura bırak", callback_data: "tura_birak" }],
      [{ text: "❌ Bu turu atla (Havuza döner)", callback_data: "iptal" },
       { text: "🗑️ Çöpe At (Havuza dönmesin)", callback_data: "cope_at" }],
    ],
  };
}

function fotoMenusu(adet, kanallar) {
  const kStr = kanallariKodla(kanallar);
  const geriCb = kStr ? `foto_geri:${adet}:${kStr}` : `foto_geri:${adet}`;
  return {
    inline_keyboard: [
      ...kanalButonlariSatirlari(kanallariCoz(kStr)),
      [{ text: "📸 Gerçek Fotoğraf Ara", callback_data: "foto_gercek" },
       { text: "🖼️ Stok Fotoğraf (Pexels)", callback_data: "foto_stok" }],
      [{ text: "🎨 Yapay Zeka ile Üret", callback_data: "foto_ai" },
       { text: "↩️ İlk Görsele Dön", callback_data: "foto_orijinal" }],
      [{ text: "← Ana Menü", callback_data: geriCb }],
    ],
  };
}

function metinMenusu(adet, kanallar) {
  const kStr = kanallariKodla(kanallar);
  const geriCb = kStr ? `metin_geri:${adet}:${kStr}` : `metin_geri:${adet}`;
  return {
    inline_keyboard: [
      ...kanalButonlariSatirlari(kanallariCoz(kStr)),
      [{ text: "✂️ Haberi Daha da Özetle", callback_data: "metin_ozetle" },
       { text: "📖 Haberi Detaylandır", callback_data: "metin_detaylandir" }],
      [{ text: "🔍 Başka Kaynaktan Araştır", callback_data: "metin_kaynak_arastir" }],
      [{ text: "🔄 Standart Yeniden Yaz", callback_data: "metin_yenile" }],
      [{ text: "← Ana Menü", callback_data: geriCb }],
    ],
  };
}

// ⚠️ src/telegram_bot.py -> yayin_zamani_menusu() ile BİREBİR AYNI olmalı.
function yayinZamaniMenusu(adet, kanallar) {
  const kStr = kanallariKodla(kanallar);
  const geriCb = kStr ? `yayin_geri:${adet}:${kStr}` : `yayin_geri:${adet}`;
  return {
    inline_keyboard: [
      ...kanalButonlariSatirlari(kanallariCoz(kStr)),
      [{ text: "▶️ Şimdi", callback_data: "yayinla" },
       { text: "30 dk", callback_data: "yayinla_sonra:30" }],
      [{ text: "1 saat", callback_data: "yayinla_sonra:60" },
       { text: "2 saat", callback_data: "yayinla_sonra:120" }],
      [{ text: "3 saat", callback_data: "yayinla_sonra:180" },
       { text: "4 saat", callback_data: "yayinla_sonra:240" }],
      [{ text: "← Geri", callback_data: geriCb }],
    ],
  };
}

// ⚠️ src/telegram_bot.py -> ses_menusu() ile BİREBİR AYNI olmalı.
function sesMenusu(adet, kanallar) {
  const kStr = kanallariKodla(kanallar);
  const ek = kStr ? `:${kStr}` : "";
  return {
    inline_keyboard: [
      ...kanalButonlariSatirlari(kanallariCoz(kStr)),
      [{ text: "🎵 Fon müzikli", callback_data: `ses_zaman:muzikli:${adet}${ek}` },
       { text: "🔇 Fon müziksiz", callback_data: `ses_zaman:muziksiz:${adet}${ek}` }],
      [{ text: "← Geri", callback_data: `yayin_geri:${adet}${ek}` }],
    ],
  };
}

// ⚠️ src/telegram_bot.py -> sesli_yayin_zamani_menusu() ile BİREBİR AYNI olmalı.
function sesliYayinZamaniMenusu(mod, adet, kanallar) {
  const kStr = kanallariKodla(kanallar);
  const simge = mod === "muziksiz" ? "🔇" : "🎵";
  return {
    inline_keyboard: [
      ...kanalButonlariSatirlari(kanallariCoz(kStr)),
      [{ text: `▶️ Şimdi ${simge}`, callback_data: `yayinla_ses:${mod}` },
       { text: "30 dk", callback_data: `yayinla_ses_sonra:${mod}:30` }],
      [{ text: "1 saat", callback_data: `yayinla_ses_sonra:${mod}:60` },
       { text: "2 saat", callback_data: `yayinla_ses_sonra:${mod}:120` }],
      [{ text: "3 saat", callback_data: `yayinla_ses_sonra:${mod}:180` },
       { text: "4 saat", callback_data: `yayinla_ses_sonra:${mod}:240` }],
      [{ text: "← Geri", callback_data: kStr ? `ses_menu:${adet}:${kStr}` : `ses_menu:${adet}` }],
    ],
  };
}

function slaytSecimMenusu(adet, kanallarStr) {
  const kStr = kanallariKodla(kanallarStr);
  const satir1 = [];
  const satir2 = [];
  for (let i = 1; i <= Math.min(adet, 5); i++) {
    satir1.push({ text: String(i), callback_data: kStr ? `slayt:${i}:${adet}:${kStr}` : `slayt:${i}:${adet}` });
  }
  for (let i = 6; i <= adet; i++) {
    satir2.push({ text: String(i), callback_data: kStr ? `slayt:${i}:${adet}:${kStr}` : `slayt:${i}:${adet}` });
  }
  const tuslar = [satir1];
  if (satir2.length) tuslar.push(satir2);
  if (adet < 10) {
    tuslar.push([{ text: `➕ Havuzdan Haber Ekle (${adet}/10)`, callback_data: "havuzdan_ekle" }]);
  }
  const geriCb = kStr ? `geri:${adet}:${kStr}` : `geri:${adet}`;
  tuslar.push([{ text: "← Geri", callback_data: geriCb }]);
  return { inline_keyboard: tuslar };
}

function slaytIslemMenusu(sira, adet, kanallarStr) {
  const kStr = kanallariKodla(kanallarStr);
  const tuslar = [];
  if (adet > 1) {
    if (sira > 1) {
      tuslar.push([{ text: `🔝 ${sira}. slaytı EN BAŞA al (Manşet)`, callback_data: `slayt_basa:${sira}` }]);
    }
    const siraSatiri = [];
    if (sira > 1) {
      siraSatiri.push({ text: "⬆️ 1 Yukarı Taşı", callback_data: `slayt_yukari:${sira}` });
    }
    if (sira < adet) {
      siraSatiri.push({ text: "⬇️ 1 Aşağı Taşı", callback_data: `slayt_asagi:${sira}` });
    }
    if (siraSatiri.length) {
      tuslar.push(siraSatiri);
    }
  }

  const geriCb = kStr ? `slayt_menu:${adet}:${kStr}` : `slayt_menu:${adet}`;
  tuslar.push(
    [{ text: `🔥 ${sira}. slayt: Başlığı Daha Dikkat Çekici Yap`, callback_data: `slayt_carpici:${sira}` }],
    [{ text: `✏️ ${sira}. slayt: Metni & Başlığı Yeniden Yaz`, callback_data: `slayt_metin:${sira}` }],
    [{ text: `✍️ ${sira}. slayt: Başlığı Elle Düzenle (Reply)`, callback_data: `slayt_elle:${sira}` }],
    [{ text: `🔀 ${sira}. slayt: Başka Fotoğraf Seç (Bedava)`, callback_data: `slayt_foto:${sira}` }],
    [{ text: `🎨 ${sira}. slayt: AI ile Görsel Çiz (~$0.04)`, callback_data: `slayt_ai:${sira}` }],
    [{ text: `➕ ${sira}. slayt: Metni Uzat`, callback_data: `metin_uzat:${sira}` },
     { text: `➖ ${sira}. slayt: Metni Kısalt`, callback_data: `metin_kisalt:${sira}` }],
    [{ text: `🧹 ${sira}. slayt: Sansürü Kaldır (* sil)`, callback_data: `sansur_kaldir:${sira}` },
     { text: `🛡️ ${sira}. slayt: Sansürle`, callback_data: `sansur_uygula:${sira}` }],
    [{ text: `📄 ${sira}. slaytın kaynak metnini göster`, callback_data: `slayt_kaynak:${sira}` }],
    [{ text: `🔄 Havuzdan Farklı Bir Habere Geç`, callback_data: `haber_degistir:${sira}` }],
    [{ text: `🗑 ${sira}. slaytı çıkar`, callback_data: `slayt_sil:${sira}` },
     { text: `🗑️ Haberi Çöpe At`, callback_data: `cope_at_tekil:${sira}` }],
    [{ text: "← Geri", callback_data: geriCb }],
  );
  return { inline_keyboard: tuslar };
}

function duraklatmaSecenekleriMenusu() {
  return {
    inline_keyboard: [
      [{ text: "⏸️ 1 Saat Duraklat", callback_data: "duraklat:1" },
       { text: "⏸️ 6 Saat Duraklat", callback_data: "duraklat:6" }],
      [{ text: "⏸️ 12 Saat Duraklat", callback_data: "duraklat:12" },
       { text: "⏸️ 24 Saat Duraklat", callback_data: "duraklat:24" }],
      [{ text: "← Yönetim Paneline Dön", callback_data: "yonetim_panel" }],
    ],
  };
}

/** Mesajın butonlarını değiştirir (metne dokunmaz). */
async function menuyuDegistir(env, sohbetId, mesajId, menu) {
  const url = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/editMessageReplyMarkup`;
  await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      chat_id: sohbetId,
      message_id: mesajId,
      reply_markup: menu,
    }),
  });
}

// Komut adlarının insan diline çevrisi — "işleniyor" satırında görünüyor.
const KOMUT_ADI = {
  yayinla: "Yayınlanıyor",
  iptal: "Tur atlanıyor",
  metin_yenile: "Metinler yeniden üretiliyor",
  foto_degistir: "Alternatif fotoğraf aranıyor",
  foto_gercek: "Gerçek basın fotoğrafı aranıyor",
  foto_stok: "Pexels stok fotoğrafı aranıyor",
  foto_ai: "AI görseli üretiliyor",
  foto_orijinal: "Orijinal görsel geri yükleniyor",
  ertele: "Erteleniyor",
  slayt_carpici: "Başlık daha dikkat çekici yapılıyor",
  slayt_ai: "AI görsel üretiliyor",
  slayt_foto: "Başka fotoğraf aranıyor",
  slayt_metin: "Metin yeniden üretiliyor",
  slayt_elle: "Başlık düzenleniyor",
  slayt_yukari: "Slayt yukarı taşınıyor",
  slayt_asagi: "Slayt aşağı taşınıyor",
  slayt_basa: "Slayt başa alınıyor",
  havuzdan_ekle: "Havuzdan haber ekleniyor",
  slayt_kaynak: "Kaynak metni getiriliyor",
  slayt_sil: "Slayt çıkarılıyor",
  metin_duzenle: "Yeni metin uygulanıyor",
  hata: "Tur yeniden kuruluyor",
  kurtar: "Tur menüsü kurtarılıyor",
  retry_kanal: "Kanal yayını telafi ediliyor",
  incele: "Haber inceleniyor",
};

/**
 * Yayın/iptal işlemlerinde butonları kaldırır; fotoğraf/metin düzenleme işlemlerinde
 * butonları tamamen yok etmek yerine "İşleniyor" ve "Menüyü Geri Getir" güvenliği sunar.
 */
async function islemeAlindiGoster(env, sohbetId, mesajId, mesajMetni, komut) {
  const kokKomut = komut.split(":")[0];
  const ad = KOMUT_ADI[kokKomut] || "İşleniyor";
  const url = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/editMessageText`;

  const sonlandirici = ["yayinla", "iptal", "cope_at", "manuel_paket"].includes(kokKomut)
    || kokKomut.startsWith("yayinla_sonra");

  const klavye = sonlandirici
    ? { inline_keyboard: [] }
    : {
        inline_keyboard: [
          [{ text: `⏳ ${ad}…`, callback_data: "isleniyor" }],
          [{ text: "↩️ Menüyü Geri Getir", callback_data: `kurtar:${mesajId}` }],
        ],
      };

  await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      chat_id: sohbetId,
      message_id: mesajId,
      text: `⏳ ${ad}…\n\n${mesajMetni || ""}`.slice(0, 4096),
      reply_markup: klavye,
      disable_web_page_preview: true,
    }),
  });
}

/** Düz mesaj gönderir (yazılı komutlara anında cevap için). */
/** Düz mesaj gönderir (yazılı komutlara anında cevap için). */
async function mesajGonder(env, sohbetId, metin, parseMode = null) {
  if (!sohbetId) return;
  const url = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`;
  const body = {
    chat_id: sohbetId,
    text: metin.slice(0, 4096),
    disable_web_page_preview: true,
  };
  if (parseMode) body.parse_mode = parseMode;
  await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Butonlu mesaj gönderir (İnteraktif kontrol merkezi vb. için). */
async function butonluMesajGonder(env, sohbetId, metin, butonlar, parseMode = "HTML") {
  if (!sohbetId) return;
  const url = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`;
  const body = {
    chat_id: sohbetId,
    text: metin.slice(0, 4096),
    disable_web_page_preview: true,
    reply_markup: { inline_keyboard: butonlar },
  };
  if (parseMode) body.parse_mode = parseMode;
  await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Butonun üstündeki "yükleniyor" halkasını durdurur. */
async function butonuDurdur(env, callbackId, metin) {
  const url = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/answerCallbackQuery`;
  await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      callback_query_id: callbackId,
      text: metin || "",
      show_alert: false,
    }),
  });
}

// Ham hata metnini repodan okur. GitHub'a dispatch ATMIYOR — yalnızca
// dosya okuyor, yani Actions dakikası harcanmıyor ve cevap anında geliyor.
async function hamHataOku(env) {
  const url = `https://api.github.com/repos/${env.GITHUB_REPO}/contents/data/son_hata.txt`;
  const cevap = await fetch(url, {
    headers: {
      authorization: `Bearer ${env.GITHUB_PAT}`,
      accept: "application/vnd.github+json",
      "user-agent": "haber-bot-worker",
    },
  });
  if (!cevap.ok) return null;
  const veri = await cevap.json();
  try {
    return decodeURIComponent(escape(atob((veri.content || "").replace(/\n/g, ""))));
  } catch (e) {
    return null;
  }
}

async function githubaIlet(env, komut, mesajId, basanKisi, kanallar, metin) {
  const url = `https://api.github.com/repos/${env.GITHUB_REPO}/dispatches`;
  const cevap = await fetch(url, {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.GITHUB_PAT}`,
      accept: "application/vnd.github+json",
      "content-type": "application/json",
      // GitHub API User-Agent zorunlu kılıyor, yoksa 403 dönüyor
      "user-agent": "haber-bot-worker",
    },
    body: JSON.stringify({
      // Tur kurma ayrı bir workflow (hazirla.yml); onay akışıyla aynı
      // event'i paylaşırsa yayinla.yml onu da işlemeye kalkıyor.
      event_type: (komut === SONDAKIKA_EYLEM || komut === "sondakika" || komut === "son_dakika")
        ? "son_dakika_calistir"
        : (HATA_EYLEM.test(komut) || komut === "tur_hazirla" || komut === "tur" ? "tur_hazirla" : "telegram_onay"),
      client_payload: {
        komut,
        mesaj_id: mesajId,
        basan: basanKisi,
        metinsiz: komut === "hata:tur_metinsiz",
        kanallar: kanallar || "",
        metin: metin || "",
      },
    }),
  });
  // 204 = kabul edildi. GitHub dispatch'te gövde döndürmüyor.
  return cevap.status === 204;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/tiktok-callback" || url.pathname === "/callback") {
      const code = url.searchParams.get("code") || "";
      const error = url.searchParams.get("error") || "";
      const errorDesc = url.searchParams.get("error_description") || "";
      if (error) {
        return new Response(
          `<html><body style="font-family:sans-serif;text-align:center;padding:40px;background:#061A1E;color:#fff;">` +
          `<h1 style="color:#EF4444;">&#10060; Yetkilendirme Ba&#351;ar&#305;s&#305;z</h1>` +
          `<p>${error}: ${errorDesc}</p></body></html>`,
          { headers: { "Content-Type": "text/html; charset=utf-8" } }
        );
      }
      return new Response(
        `<html><body style="font-family:sans-serif;text-align:center;padding:40px;background:#061A1E;color:#fff;">` +
        `<h1 style="color:#06B6D4;">&#127881; TikTok Yetkilendirmesi Ba&#351;ar&#305;l&#305;!</h1>` +
        `<p style="font-size:18px;margin-top:20px;">A&#351;a&#287;&#305;daki kodu kopyalay&#305;p terminale yap&#305;&#351;t&#305;r&#305;n:</p>` +
        `<div style="background:#0D333A;padding:15px;border-radius:8px;font-family:monospace;font-size:20px;color:#38BDF8;word-break:break-all;margin:20px auto;max-width:600px;border:1px solid #06B6D4;">` +
        `${code}` +
        `</div></body></html>`,
        { headers: { "Content-Type": "text/html; charset=utf-8" } }
      );
    }

    if (request.method !== "POST") {
      return new Response("yalnızca POST", { status: 405 });
    }

    // 1) Telegram'dan geldiğini doğrula
    const gelenGizli = request.headers.get("x-telegram-bot-api-secret-token");
    if (!env.WEBHOOK_SECRET || gelenGizli !== env.WEBHOOK_SECRET) {
      return new Response("yetkisiz", { status: 401 });
    }

    let guncelleme;
    try {
      guncelleme = await request.json();
    } catch {
      return new Response("bozuk gövde", { status: 400 });
    }

    // --- Yazılı komutlar: /durum, /tur, /yardim ---
    //
    // Buton menüsü yalnızca AÇIK bir onay mesajı varken işe yarıyor.
    // Tur kapandıysa ya da hiç kurulmadıysa elde hiçbir tutamak
    // kalmıyordu; bu komutlar o boşluğu dolduruyor.
    const msj = guncelleme.message;
    if (msj && typeof msj.text === "string") {
        const sohbet = msj.chat ? msj.chat.id : null;

        // --- Yanıtlanan Mesajlar (Reply): Doğrudan başlık/metin düzenleme ---
        if (msj.reply_to_message) {
            const replyId = msj.reply_to_message.message_id;
            const replyMetin = msj.text.trim();
            const basan = msj.from ? msj.from.first_name || "" : "";

            if (!replyMetin.startsWith("/")) {
                const iletildi = await githubaIlet(env, "metin_duzenle", replyId, basan, "", replyMetin);
                await mesajGonder(env, sohbet,
                    iletildi
                        ? "✍️ Yeni metin işleniyor, başlık ve slayt güncelleniyor…"
                        : "⚠️ İstek GitHub'a iletilemedi.");
                return new Response("ok");
            }
        }

        const komutMetni = msj.text.trim().split(/[\s@]/)[0].toLowerCase();

        // /guncelle — RSS'i hemen tarar. Kullanıcı duyduğu bir haberi
        // arayıp bulamadığında kontrolün çalışmasını beklemek zorunda
        // kalıyordu (21 Ağu 2026, "Netanyahu tutuklama emri").
        if (komutMetni === "/guncelle" || komutMetni === "/havuz") {
            const iletildi = await githubaIlet(
                env, "havuz_guncelle", null,
                msj.from ? msj.from.first_name || "" : "");
            await mesajGonder(env, sohbet,
                iletildi
                    ? "🔄 Kaynaklar taranıyor, sonucu birazdan yazacağım…"
                    : "⚠️ İstek GitHub'a iletilemedi.");
            return new Response("ok");
        }

        if (komutMetni === "/yardim" || komutMetni === "/start") {
            // Yardım metni Worker'da duruyor: GitHub'ı uyandırmak 40+
            // saniye sürüyor, sabit bir metin için buna değmez.
            await mesajGonder(env, sohbet,
                "🤖 <b>Daily Brief Bot — Komut Rehberi</b>\n\n" +

                "<b>✍️ İÇERİK ÜRET</b>\n" +
                "• /haber &lt;kelime&gt; — Havuzdaki haberlerde ara\n" +
                "• /link &lt;url&gt; — Haber linkinden post üret\n" +
                "• /dosya &lt;konu&gt; — Konunun A'dan Z'ye kronolojik dosyası\n" +
                "• /kronoloji &lt;konu&gt; — Olay veya dava sürecini özetle\n" +
                "• /arastir &lt;konu&gt; — Konuyu webde araştırıp posta dönüştür\n" +
                "• /ozel &lt;metin&gt; — Kendi duyuru metninden post üret\n" +
                "• /incele &lt;id&gt; — Haber detayını ve puan gerekçesini incele\n\n" +

                "<b>📰 GÜNDEM &amp; AKIŞ</b>\n" +
                "• /sondakika — Taze haberleri tara, öneri getir\n" +
                "• /populer — Merak edilen, popüler haberler\n" +
                "• /guncelle — RSS kaynaklarını ŞİMDİ tara (metin üretmez)\n" +
                "• /tur — 10 haberlik gündem turu hazırla\n" +
                "• /bulten — Taze haberlerden kahve bülteni derle\n" +
                "• /haftalik — Haftalık pazar özeti\n" +
                "• /sonpostlar — Son yayınlanan postlar ve linkleri\n\n" +

                "<b>📈 PİYASA &amp; MAKRO</b>\n" +
                "• /piyasa — Canlı borsa, döviz, altın, kripto tablosu\n" +
                "• /ekonomi — Canlı piyasa özeti + yayın düğmeleri\n" +
                "• /hisse &lt;sembol&gt; — BİST hissesi sorgula\n" +
                "• /kripto &lt;sembol&gt; — Kripto para sorgula\n" +
                "• /faiz &lt;oran&gt; &lt;açıklama&gt; — Faiz kararı kartı\n" +
                "• /enflasyon &lt;oran&gt; &lt;açıklama&gt; — Enflasyon kartı\n" +
                "• /fed &lt;oran&gt; &lt;açıklama&gt; — Fed kararı kartı\n" +
                "• /makro &lt;veri&gt; — Serbest makro veri kartı\n\n" +

                "<b>🎛 YÖNETİM &amp; BAKIM</b>\n" +
                "• /kota — Detaylı GitHub ve AI kota raporu\n" +
                "• /durum — Havuz, kota ve askıda kalan turlar\n" +
                "• /menu — Düğmeli kontrol merkezi\n" +
                "• /yonetim — Yönetim paneli ve API sağlık testleri\n" +
                "• /ayar — Çalışma ayarlarını değiştir\n" +
                "• /temizle — Askıda kalan onay turlarını sıfırla\n" +
                "• /tamamla — Yarım kalan Threads zincirini tamamla\n" +
                "• /arsiv — Eski turları Threads'e taşı\n" +
                "• /video — Son turdan 9:16 Reels videosu üret\n" +
                "• /durdur — Botu geçici duraklat · /devam — Yeniden başlat\n\n" +

                "❓ /yardim — Bu rehber\n\n" +
                "<i>⚠️ Makro kartlarında oranı SEN yazıyorsun; bot rakam " +
                "uydurmaz. Örn: /faiz 47.5 TCMB politika faizini sabit tuttu</i>",
                "HTML");
            return new Response("ok");
        }

        // /link <URL> — Verilen web linkinden özel haber üretir
        if (komutMetni === "/link") {
            const url = msj.text.trim().slice(komutMetni.length).trim();
            if (!url.startsWith("http")) {
                await mesajGonder(env, sohbet,
                    "⚠️ Lütfen geçerli bir haber linki yaz:\n/link https://bloomberg.com/...");
                return new Response("ok");
            }
            const iletildi = await githubaIlet(env, `link:${url}`,
                null, msj.from ? msj.from.first_name || "" : "");
            await mesajGonder(env, sohbet,
                iletildi
                    ? `🌐 Link taranıyor ve özel haber hazırlanıyor…\n${url.slice(0, 70)}`
                    : "⚠️ Komut iletilemedi, tekrar dene.");
            return new Response("ok");
        }

        // /incele <ID> veya /incele_<ID> — Haberin detayını ve Gemini puanını inceler
        if (komutMetni === "/incele" || komutMetni.startsWith("/incele_")) {
            let id = "";
            if (komutMetni.startsWith("/incele_")) {
                id = komutMetni.slice("/incele_".length).trim();
            } else {
                id = msj.text.trim().slice(komutMetni.length).trim();
            }
            if (!id || !/^\d+$/.test(id)) {
                await mesajGonder(env, sohbet,
                    "⚠️ İncelemek istediğin haber numarasını yaz:\nÖrnek: /incele 1482");
                return new Response("ok");
            }
            const iletildi = await githubaIlet(env, `incele:${id}`,
                null, msj.from ? msj.from.first_name || "" : "");
            await mesajGonder(env, sohbet,
                iletildi
                    ? `🔍 #${id} numaralı haber inceleniyor ve detayları getiriliyor…`
                    : "⚠️ Komut iletilemedi, tekrar dene.");
            return new Response("ok");
        }

        // /dosya <KONU> veya /kronoloji <KONU> — Bir konunun başından sonuna kronolojik perde arkası dosya haberini üretir
        if (komutMetni === "/dosya" || komutMetni === "/kronoloji" || komutMetni === "/perdearkasi") {
            const konu = msj.text.trim().slice(komutMetni.length).trim();
            if (konu.length < 4) {
                await mesajGonder(env, sohbet,
                    "⚠️ Dosya haberi yapmak istediğin konuyu yaz:\n/dosya Haluk Levent ve Ahbap derneği davası son gelişmeler\n/kronoloji Dilan Polat davası");
                return new Response("ok");
            }
            const iletildi = await githubaIlet(env, `dosya:${konu.slice(0, 400)}`,
                null, msj.from ? msj.from.first_name || "" : "");
            await mesajGonder(env, sohbet,
                iletildi
                    ? `📁 "${konu.slice(0, 70)}" dosya haberi hazırlanıyor:\nBaşından sonuna tüm kronoloji, dava/teftiş süreçleri ve perde arkası detaylar toplanıyor…`
                    : "⚠️ Komut iletilemedi, tekrar dene.");
            return new Response("ok");
        }

        // /arastir <KONU> — Konuyu webde araştırıp doğrulanmış haber üretir
        if (komutMetni === "/arastir" || komutMetni === "/ara") {
            const konu = msj.text.trim().slice(komutMetni.length).trim();
            if (konu.length < 4) {
                await mesajGonder(env, sohbet,
                    "⚠️ Araştırmak istediğin konuyu yaz:\n/arastir Nvidia yeni kuantum yapay zeka çipini duyurdu");
                return new Response("ok");
            }
            const iletildi = await githubaIlet(env, `arastir:${konu.slice(0, 300)}`,
                null, msj.from ? msj.from.first_name || "" : "");
            await mesajGonder(env, sohbet,
                iletildi
                    ? `🔍 "${konu.slice(0, 70)}" konusu canlı araştırılıyor ve haberleştiriliyor…`
                    : "⚠️ Komut iletilemedi, tekrar dene.");
            return new Response("ok");
        }

        // /ozel <METİN> — Kullanıcının bülten/duyuru metninden post üretir
        if (komutMetni === "/ozel" || komutMetni === "/bulten" || komutMetni === "/duyuru") {
            const metin = msj.text.trim().slice(komutMetni.length).trim();
            if (metin.length < 15) {
                await mesajGonder(env, sohbet,
                    "⚠️ Post yapmak istediğin bülten veya duyuru metnini yaz:\n/ozel Daily Brief mobil uygulamamız App Store ve Google Play'de yayına girdi...");
                return new Response("ok");
            }
            const iletildi = await githubaIlet(env, `ozel:${metin.slice(0, 1500)}`,
                null, msj.from ? msj.from.first_name || "" : "");
            await mesajGonder(env, sohbet,
                iletildi
                    ? "✍️ Özel bülten metni işleniyor, slaytlar hazırlanıyor…"
                    : "⚠️ Komut iletilemedi, tekrar dene.");
            return new Response("ok");
        }

        // /faiz, /enflasyon, /fed, /makro — Kritik Makro Veri İnfografik Kartı Üretir
        if (["/faiz", "/enflasyon", "/fed", "/makro"].includes(komutMetni)) {
            const metin = msj.text.trim().slice(komutMetni.length).trim();
            const turu = komutMetni.slice(1);
            if (metin.length < 2) {
                await mesajGonder(env, sohbet,
                    `⚠️ Lütfen veri veya açıklama gir:\n${komutMetni} 45 TCMB politika faizini yüzde 45'te sabit bıraktı.`);
                return new Response("ok");
            }
            const iletildi = await githubaIlet(env, `${turu}:${metin.slice(0, 800)}`,
                null, msj.from ? msj.from.first_name || "" : "");
            await mesajGonder(env, sohbet,
                iletildi
                    ? `⚡ <b>${turu.toUpperCase()} İnfografik Kartı Hazırlanıyor…</b>\nPiyasa reaksiyonu ve dev vitrin kartı çiziliyor…`
                    : "⚠️ Komut iletilemedi, tekrar dene.");
            return new Response("ok");
        }

        // /haber <konu> — havuzda arama yapıp öneri sunar.
        if (komutMetni === "/haber") {
            const konu = msj.text.trim().slice(komutMetni.length).trim();
            if (konu.length < 3) {
                await mesajGonder(env, sohbet,
                    "Aramak istediğin konuyu yaz:\n/haber galatasaray transfer");
                return new Response("ok");
            }
            const iletildi = await githubaIlet(env, `ara:${konu.slice(0, 120)}`,
                null, msj.from ? msj.from.first_name || "" : "");
            await mesajGonder(env, sohbet,
                iletildi
                    ? `🔎 "${konu.slice(0, 60)}" havuzda aranıyor…`
                    : "⚠️ Komut iletilemedi, tekrar dene.");
            return new Response("ok");
        }

        // /menu & /kontrol — İnteraktif Kontrol Merkezi
        if (komutMetni === "/menu" || komutMetni === "/kontrol") {
            const menuButonlar = [
                [
                    { text: "📊 Ekonomi Turu Başlat", callback_data: "ekonomi_hazirla" },
                    { text: "🌅 Gündem Turu Başlat", callback_data: "tur_hazirla" },
                ],
                [
                    { text: "🚨 Son Dakika Tara", callback_data: "sondakika" },
                    { text: "📈 Canlı Piyasa & Borsa", callback_data: "piyasa_ozet" },
                ],
                [
                    { text: "🏦 Faiz Kartı (TCMB)", callback_data: "makro_yardim:faiz" },
                    { text: "📉 Enflasyon Kartı", callback_data: "makro_yardim:enflasyon" },
                ],
                [
                    { text: "☕ Kahve Bülteni", callback_data: "bulten" },
                    { text: "📰 Son Postlar", callback_data: "sonpostlar" },
                ],
                [
                    { text: "🩺 API Sağlık Testi", callback_data: "saglik_testi" },
                    { text: "🧹 Askıdakileri Sıfırla", callback_data: "tur_temizle" },
                ],
                [
                    { text: "📊 Durum & Kota Raporu", callback_data: "kota_raporu" },
                    { text: "🔄 RSS Tara (Havuz)", callback_data: "havuz_guncelle" },
                ],
                [
                    { text: "⏸️ Botu Duraklat", callback_data: "yonetim" },
                    { text: "⚙️ Ayarlar", callback_data: "ayar" },
                ],
            ];
            await butonluMesajGonder(env, sohbet,
                "🎛️ <b>DAILY BRIEF KONTROL MERKEZİ</b>\n\n" +
                "Aşağıdaki interaktif panelden turları başlatabilir, son dakika taraması yapabilir veya sistemi yönetebilirsin:",
                menuButonlar, "HTML"
            );
            return new Response("ok");
        }

        // /hisse <SEMBOL> — Canlı Hisse Senedi Fiyatı Sorgula
        if (komutMetni === "/hisse") {
            const sembol = msj.text.trim().slice(komutMetni.length).trim();
            if (!sembol) {
                await mesajGonder(env, sohbet, "⚠️ Lütfen hisse sembolü girin:\n/hisse THYAO veya /hisse ASELS");
                return new Response("ok");
            }
            const iletildi = await githubaIlet(env, `hisse:${sembol.slice(0, 30)}`, null, msj.from ? msj.from.first_name || "" : "");
            await mesajGonder(env, sohbet, iletildi ? `📊 <b>${sembol.toUpperCase()}</b> canlı piyasa verisi sorgulanıyor…` : "⚠️ İstek iletilemedi.", "HTML");
            return new Response("ok");
        }

        // /kripto <SEMBOL> — Canlı Kripto Para Fiyatı Sorgula
        if (komutMetni === "/kripto") {
            const sembol = msj.text.trim().slice(komutMetni.length).trim();
            if (!sembol) {
                await mesajGonder(env, sohbet, "⚠️ Lütfen kripto sembolü girin:\n/kripto BTC veya /kripto ETH");
                return new Response("ok");
            }
            const iletildi = await githubaIlet(env, `kripto:${sembol.slice(0, 30)}`, null, msj.from ? msj.from.first_name || "" : "");
            await mesajGonder(env, sohbet, iletildi ? `🪙 <b>${sembol.toUpperCase()}</b> canlı kripto verisi sorgulanıyor…` : "⚠️ İstek iletilemedi.", "HTML");
            return new Response("ok");
        }

        if (["/durum", "/kota", "/rapor", "/kullanim", "/tur", "/hazirla", "/ekonomi", "/temizle", "/guncelle", "/sondakika", "/populer", "/popüler", "/haftalik", "/pazar", "/video", "/reels", "/ayar", "/tamamla", "/arsiv", "/yonetim", "/panel", "/piyasa", "/saglik", "/durdur", "/devam", "/bulten", "/kahve", "/sonpostlar"].includes(komutMetni)) {
            let komut = komutMetni.slice(1);
            if (komut === "rapor" || komut === "kullanim" || komut === "kota") {
                const parcalar = msj.text.trim().split(/\s+/);
                if (parcalar.length > 1) {
                    const p = parcalar[1].toLowerCase();
                    if (p === "1" || p === "bulut" || p === "api") komut = "kota_kat:1";
                    else if (p === "2" || p === "sosyal" || p === "yayin") komut = "kota_kat:2";
                    else komut = "kota";
                } else {
                    komut = "kota";
                }
            }
            if (komut === "panel") komut = "yonetim";
            if (komut === "hazirla") komut = "tur";
            if (komut === "temizle") komut = "tur_temizle";
            if (komut === "guncelle") komut = "havuz_guncelle";
            if (komut === "pazar") komut = "haftalik";
            if (komut === "reels") komut = "video";
            if (komut === "saglik") komut = "saglik_testi";
            if (komut === "durdur") komut = "durdur";
            if (komut === "devam") komut = "devam_et";
            if (komut === "kahve") komut = "bulten";
            if (komut === "popüler") komut = "populer";
            const iletildi = await githubaIlet(env, komut, null,
                msj.from ? msj.from.first_name || "" : "");
            await mesajGonder(env, sohbet,
                iletildi
                    ? (komut === "kota"
                        ? "📊 Canlı GitHub ve AI kota raporu hazırlanıyor…"
                        : komut === "tur"
                        ? "⏳ Yeni gündem turu hazırlanıyor, birkaç dakika sürebilir…"
                        : komut === "ekonomi"
                          ? "📊 Yeni Ekonomi & Piyasa turu hazırlanıyor…"
                          : komut === "tur_temizle"
                            ? "🧹 Askıdaki cevapsız turlar temizleniyor…"
                            : komut === "sondakika"
                              ? "⚡️ Son dakika sıcak haber taraması başlatılıyor…"
                              : komut === "populer"
                                ? "🔥 Popüler & merak edilen haber önerileri taranıyor…"
                                : komut === "piyasa"
                                  ? "📈 Canlı piyasa ve borsa verileri çekiliyor…"
                                : komut === "saglik_testi"
                                  ? "🩺 Sosyal medya API bağlantıları test ediliyor…"
                                  : komut === "bulten"
                                    ? "☕ Taze haberlerden kahve bülteni derleniyor…"
                                    : komut === "sonpostlar"
                                      ? "📰 Son yayınlanan post kayıtları getiriliyor…"
                                      : komut === "haftalik"
                                        ? "🗓️ Haftalık Pazar özeti hazırlanıyor, son 7 günün manşetleri taranıyor…"
                                        : komut === "video"
                                          ? "🎬 Son turun 9:16 MP4 Reels videosu render ediliyor…"
                                          : komut === "ayar"
                                            ? "⏳ Ayarlar getiriliyor…"
                                            : komut === "yonetim"
                                              ? "⏳ Yönetim paneli getiriliyor…"
                                              : komut === "tamamla"
                                                ? "⏳ Threads zinciri kontrol ediliyor…"
                                                : komut === "arsiv"
                                                  ? "⏳ Arşiv paylaşımı başlatılıyor, uzun sürebilir…"
                                                  : "⏳ Durum sorgulanıyor…")
                    : "⚠️ Komut iletilemedi, tekrar dene.");
            return new Response("ok");
        }

        // Akıllı Link Yakalayıcı: Kullanıcı /link yazmadan düz haber linki atarsa otomatik buton sun
        if (!msj.text.startsWith("/")) {
            const urlMatch = msj.text.match(/https?:\/\/[^\s]+/i);
            if (urlMatch) {
                const url = urlMatch[0];
                const linkButonlar = [
                    [{ text: "🚀 Bu Linkten Post Üret", callback_data: `link:${url.slice(0, 300)}` }],
                    [{ text: "❌ İptal", callback_data: "iptal" }]
                ];
                await butonluMesajGonder(env, sohbet,
                    `🌐 <b>Haber Linki Algılandı!</b>\n\n` +
                    `Bu haber linkinden Daily Brief formatında 9:16 infografik post üretmek ister misin?\n\n` +
                    `🔗 <code>${url.slice(0, 80)}</code>`,
                    linkButonlar, "HTML"
                );
                return new Response("ok");
            }
        }

        // Akıllı Fotoğraf & Başlık Yakalayıcı
        if (msj.photo && typeof msj.caption === "string" && msj.caption.trim().length > 5) {
            const cap = msj.caption.trim();
            const photoButtons = [
                [{ text: "🚀 Bu Açıklamayla Post Üret", callback_data: `ozel:${cap.slice(0, 300)}` }],
                [{ text: "❌ İptal", callback_data: "iptal" }]
            ];
            await butonluMesajGonder(env, sohbet,
                `📸 <b>Fotoğraflı İçerik Algılandı!</b>\n\n` +
                `Bu açıklama metninden Daily Brief 9:16 postu hazırlamak ister misin?\n\n` +
                `📝 <i>${cap.slice(0, 100)}</i>`,
                photoButtons, "HTML"
            );
            return new Response("ok");
        }

        return new Response("ok");
    }

    const cb = guncelleme.callback_query;
    // Butona basılmayan güncellemeler (grup mesajları vb.) bizi ilgilendirmiyor.
    // 200 dönüyoruz ki Telegram tekrar tekrar denemesin.
    if (!cb) return new Response("ok");

    let komut = cb.data;  // let: "yayinla_ses…" aşağıda "yayinla…"ya çevriliyor
    const sohbetId = cb.message ? cb.message.chat.id : null;
    const mesajId = cb.message ? cb.message.message_id : null;

    // --- Slayt başlığını elle yazma kılavuzu ---
    if (komut.startsWith("slayt_elle:")) {
      const sira = komut.split(":")[1];
      await mesajGonder(env, sohbetId,
          `✍️ <b>${sira}. slayt</b> için yeni başlığı bu mesaja <b>YANITLAYARAK (Reply)</b> yazabilirsin.\n\n` +
          `<b>Örnek formatlar:</b>\n` +
          `• <code>${sira}: Yeni Başlık Metni</code>\n` +
          `• <code>${sira}: Yeni Başlık | Yeni Alt Açıklama</code>\n\n` +
          `<i>(Başlık onayı aşamasındaysa liste, görsel onayı aşamasındaysa slayt görseli yenilenir.)</i>`,
          "HTML"
      );
      await butonuDurdur(env, cb.id, "Yanıtını bekliyorum...");
      return new Response("ok");
    }

    // --- "İşleniyor" butonuna basılırsa kullanıcıyı bilgilendir ---
    if (komut === "isleniyor") {
      await butonuDurdur(env, cb.id, "⏳ İşlem devam ediyor, lütfen bekle…");
      return new Response("ok");
    }

    // --- Kurtar: Worker menüyü ve butonları anında geri yükler ---
    if (KURTAR.test(komut)) {
      const mid = Number(komut.split(":")[1]);
      let temizMetin = (cb.message ? cb.message.text : "") || "";
      if (temizMetin.startsWith("⏳")) {
        temizMetin = temizMetin.replace(/^⏳[^\n]*\n\n/, "");
      }
      const editUrl = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/editMessageText`;
      await fetch(editUrl, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          chat_id: sohbetId,
          message_id: mid,
          text: (temizMetin || "Daily Brief Onay Menüsü").slice(0, 4096),
          reply_markup: anaMenu(3),
          disable_web_page_preview: true,
        }),
      });
      await butonuDurdur(env, cb.id, "✅ Menü geri yüklendi");
      return new Response("ok");
    }

    // --- Duraklatma alt menüsü: Worker anında açıyor ---
    if (komut === "duraklat_menu") {
      await menuyuDegistir(env, sohbetId, mesajId, duraklatmaSecenekleriMenusu());
      await butonuDurdur(env, cb.id, "");
      return new Response("ok");
    }

    // --- Ayar alt menüsü: Worker anında açıyor ---
    const ayarMenu = AYAR_MENU.exec(komut);
    if (ayarMenu) {
      await menuyuDegistir(env, sohbetId, mesajId,
                           ayarAltMenu(ayarMenu[1], ayarMenu[2]));
      await butonuDurdur(env, cb.id, "");
      return new Response("ok");
    }

    // --- Öneri çoklu seçimi: Worker anında hallediyor ---
    if (SEC.test(komut)) {
      const klavye = cb.message?.reply_markup?.inline_keyboard || [];
      let secili = 0;
      const yeni = klavye.map((satir) =>
        satir.map((btn) => {
          const kopya = { ...btn };
          if (kopya.callback_data === komut) {
            // İşareti aç/kapat
            kopya.text = kopya.text.startsWith("✅")
              ? kopya.text.slice(1)
              : "✅" + kopya.text;
          }
          if (String(kopya.callback_data || "").startsWith("sec:")
              && kopya.text.startsWith("✅")) {
            secili += 1;
          }
          return kopya;
        })
      );
      // "Hazırla (N)" sayacını güncelle
      for (const satir of yeni) {
        for (const btn of satir) {
          if (btn.callback_data === SECILENLERI_HAZIRLA) {
            btn.text = `▶️ Hazırla (${secili})`;
          }
        }
      }
      await menuyuDegistir(env, sohbetId, mesajId, { inline_keyboard: yeni });
      await butonuDurdur(env, cb.id, "");
      return new Response("ok");
    }

    // Seçilenleri topla ve TEK dispatch ile gönder
    if (komut === SECILENLERI_HAZIRLA) {
      const klavye = cb.message?.reply_markup?.inline_keyboard || [];
      const idler = klavye
        .flat()
        .filter((b) => String(b.callback_data || "").startsWith("sec:")
                       && String(b.text || "").startsWith("✅"))
        .map((b) => b.callback_data.slice(4));
      if (idler.length === 0) {
        await butonuDurdur(env, cb.id, "Önce en az bir haber seç");
        return new Response("ok");
      }
      // Komut GitHub'a "hazirla:12,34,56" biçiminde gidiyor.
      // callback_data 64 bayt sınırına takılmıyor çünkü id'ler
      // butonun kendisinde değil, buton METİNLERİNDEN okunuyor.
      // `basan` aşağıda tanımlanıyor ama bu blok ondan önce
      // çalışıyor; burada kendimiz hesaplıyoruz.
      const secen = cb.from
        ? `${cb.from.first_name || ""} ${cb.from.username ? "@" + cb.from.username : ""}`.trim()
        : "";
      const kararlar = `hazirla:${idler.join(",")}`;
      await islemeAlindiGoster(env, sohbetId, mesajId,
        `${idler.length} haber seçildi, sırayla üretiliyor.`, kararlar);
      await githubaIlet(env, kararlar, mesajId, secen);
      await butonuDurdur(env, cb.id, "");
      return new Response("ok");
    }

    // --- Kanal seçimi toggle: Worker anında hallediyor ---
    if (KANAL_TOGGLE.test(komut)) {
      const hedefKanal = komut.slice(6); // "ig", "reels", "story", "threads", "facebook", "twitter"
      const klavye = cb.message?.reply_markup?.inline_keyboard || [];
      
      // 1. Tıklanan hedefin şu anki durumunu bulalım
      let hedefSuAnSecili = false;
      for (const satir of klavye) {
        for (const btn of satir) {
          if (btn.callback_data === `kanal:${hedefKanal}`) {
            hedefSuAnSecili = String(btn.text || "").startsWith("✅");
          }
        }
      }
      const hedefYeniSecili = !hedefSuAnSecili;

      // 2. Butonları güncelle
      const yeni = klavye.map((satir) =>
        satir.map((btn) => {
          const kopya = { ...btn };
          if (!String(kopya.callback_data || "").startsWith("kanal:")) return kopya;

          const buKanal = kopya.callback_data.slice(6);

          if (buKanal === hedefKanal) {
            kopya.text = (hedefYeniSecili ? "✅ " : "⬜ ") + kopya.text.slice(1).trim();
          } else if (hedefKanal === "reels" && hedefYeniSecili && buKanal === "ig") {
            // Reels AÇILDIYSA -> IG MUTLAKA KAPANIR
            kopya.text = "⬜ IG";
          } else if (hedefKanal === "ig" && hedefYeniSecili && buKanal === "reels") {
            // IG AÇILDIYSA -> Reels MUTLAKA KAPANIR
            kopya.text = "⬜ Reels";
          }
          return kopya;
        })
      );
      await menuyuDegistir(env, sohbetId, mesajId, { inline_keyboard: yeni });
      await butonuDurdur(env, cb.id, "");
      return new Response("ok");
    }

    // --- Menü gezinme: Worker anında hallediyor, GitHub'a gitmiyor ---
    if (MENU_GEZINME.test(komut)) {
      let menu;
      const klavyedenKanallar = seciliKanallariCikar(cb.message?.reply_markup?.inline_keyboard);
      const parcalar = komut.split(":");
      const kok = parcalar[0];

      if (kok === "slayt_menu") {
        const adet = Number(parcalar[1]);
        const kanallarStr = parcalar[2] || (klavyedenKanallar ? klavyedenKanallar.join(",") : "");
        menu = slaytSecimMenusu(adet, kanallarStr);
      } else if (kok === "geri" || kok === "yayin_geri" || kok === "foto_geri" || kok === "metin_geri") {
        const adet = Number(parcalar[1]);
        const kanallarStr = parcalar[2];
        const kanallar = kanallarStr ? kanallarStr.split(",") : klavyedenKanallar;
        menu = anaMenu(adet, kanallar);
      } else if (kok === "yayin_menu") {
        const adet = Number(parcalar[1]);
        const kanallarStr = parcalar[2] || (klavyedenKanallar ? klavyedenKanallar.join(",") : "");
        const kanallar = kanallarStr ? kanallarStr.split(",") : klavyedenKanallar;
        menu = yayinZamaniMenusu(adet, kanallar);
      } else if (kok === "ses_menu") {
        const adet = Number(parcalar[1]);
        const kanallarStr = parcalar[2] || (klavyedenKanallar ? klavyedenKanallar.join(",") : "");
        menu = sesMenusu(adet, kanallarStr ? kanallarStr.split(",") : klavyedenKanallar);
      } else if (kok === "ses_zaman") {
        const adet = Number(parcalar[2]);
        const kanallarStr = parcalar[3] || (klavyedenKanallar ? klavyedenKanallar.join(",") : "");
        menu = sesliYayinZamaniMenusu(parcalar[1], adet, kanallarStr ? kanallarStr.split(",") : klavyedenKanallar);
      } else if (kok === "foto_menu") {
        const adet = Number(parcalar[1]);
        const kanallarStr = parcalar[2] || (klavyedenKanallar ? klavyedenKanallar.join(",") : "");
        const kanallar = kanallarStr ? kanallarStr.split(",") : klavyedenKanallar;
        menu = fotoMenusu(adet, kanallar);
      } else if (kok === "metin_menu") {
        const adet = Number(parcalar[1]);
        const kanallarStr = parcalar[2] || (klavyedenKanallar ? klavyedenKanallar.join(",") : "");
        const kanallar = kanallarStr ? kanallarStr.split(",") : klavyedenKanallar;
        menu = metinMenusu(adet, kanallar);
      } else if (kok === "slayt") {
        const sira = Number(parcalar[1]);
        const adet = Number(parcalar[2]);
        const kanallarStr = parcalar[3] || "";
        menu = slaytIslemMenusu(sira, adet, kanallarStr);
      }
      await menuyuDegistir(env, sohbetId, mesajId, menu);
      await butonuDurdur(env, cb.id, "");
      return new Response("ok");
    }

    // --- Ham hata metni: Worker repodan okuyup anında gösteriyor ---
    if (komut === HATA_AYRINTI) {
      const ham = await hamHataOku(env);
      await mesajGonder(env, sohbetId,
        ham ? `🔍 HAM HATA METNİ\n\n${ham.slice(0, 3500)}`
            : "Kayıtlı ham hata metni bulunamadı.");
      await butonuDurdur(env, cb.id, "");
      return new Response("ok");
    }

    // --- Makro kartı: ORANI KULLANICI YAZAR ---
    //
    // ⚠️ 4 Eyl 2026'ya kadar bu iki düğme callback_data'sında UYDURMA
    // RAKAM taşıyordu: "faiz:45 TCMB politika faizini yüzde 45
    // seviyesinde sabit bıraktı." O metin doğrudan Gemini prompt'una
    // GİRDİ olarak giriyor ve yayınlanabilir bir infografiğe dönüşüyordu
    // — yani düğmeye basan kişi, hiçbir kaynaktan gelmeyen bir merkez
    // bankası faizi yayınlıyordu. Projenin en temel kuralına aykırı:
    // "yalnızca kaynak metinde yazanı kullan".
    //
    // Düğme artık post ÜRETMİYOR, komutun nasıl yazılacağını gösteriyor.
    if (komut.startsWith("makro_yardim:")) {
      const tip = komut.split(":")[1];
      const ornek = {
        faiz: "/faiz 47.5 TCMB politika faizini yüzde 47,5'te sabit tuttu",
        enflasyon: "/enflasyon 33.2 TÜİK yıllık TÜFE'yi yüzde 33,2 açıkladı",
        fed: "/fed 4.25 Fed politika faizini 25 baz puan indirdi",
      }[tip] || "/makro <veri ve açıklama>";
      await mesajGonder(env, sohbetId,
        `📊 <b>Makro kartı için oranı SEN yazmalısın.</b>\n\n` +
        `Bot rakam uydurmaz — açıklanan veriyi komutla ver:\n\n` +
        `<code>${ornek}</code>\n\n` +
        `<i>Kart bu girdiden üretilir.</i>`, "HTML");
      await butonuDurdur(env, cb.id, "");
      return new Response("ok");
    }

    // --- Gerçek eylem: GitHub Actions'a iletiliyor ---
    // Sesli yayın komutu mevcut yayın komutuna çevrilir; kip kanal listesinde taşınır.
    let sesKipi = null;
    const sesEslesme = SESLI_YAYIN.exec(komut);
    if (sesEslesme) {
      sesKipi = sesEslesme[1] || sesEslesme[2];
      komut = sesEslesme[3] ? `yayinla_sonra:${sesEslesme[3]}` : "yayinla";
    }
    if (!eylemMi(komut)) {
      await butonuDurdur(env, cb.id, "Tanınmayan komut");
      return new Response("ok");
    }

    const seciliKanallar = seciliKanallariCikar(cb.message?.reply_markup?.inline_keyboard);
    // Sıfır kanal seçimi koruması (Senaryo A)
    if (seciliKanallar !== null && seciliKanallar.length === 0 && (komut === "yayinla" || komut.startsWith("yayinla_sonra:"))) {
      await butonuDurdur(env, cb.id, "⚠️ En az bir yayın kanalı seçmelisin!");
      return new Response("ok");
    }
    // Seslendirme yalnızca videoya uygulanır: video kanalı yoksa sesli yayın anlamsız
    if (sesKipi && !(seciliKanallar || []).some((k) => VIDEO_KANALLARI.includes(k))) {
      await butonuDurdur(env, cb.id, "🎙️ Sesli yayın için en az bir video kanalı seç (Reels, FB, YT, TT)");
      return new Response("ok");
    }

    const basan = cb.from
      ? `${cb.from.first_name || ""} ${cb.from.username ? "@" + cb.from.username : ""}`.trim()
      : "";

    // "kaldir:144" -> komut "kaldir", hedef tur 144. Mesajın kendi
    // id'si burada işe yaramıyor (bkz. KALDIR açıklaması).
    let gonderilecek = komut;
    let hedefMesajId = mesajId;
    const kaldirEslesme = KALDIR.exec(komut);
    if (kaldirEslesme) {
      gonderilecek = "kaldir";
      hedefMesajId = Number(kaldirEslesme[1]);
    }

    const kanallarStr = (seciliKanallar ? seciliKanallar.join(",") : "") + (sesKipi ? `,ses_${sesKipi}` : "");
    const iletildi = await githubaIlet(env, gonderilecek, hedefMesajId, basan, kanallarStr);

    // ⚠️ ÇALAR SAATİ KUR. "2 saat sonra yayınla" seçildiğinde GitHub
    // veritabanına `planlanan_yayin` yazıyor; ama o zamanın GELDİĞİNİ
    // fark edecek olan taraf burası. KV'ye bir uyandırma kaydı
    // bırakılıyor ve 10 dakikalık cron ona bakıyor.
    //
    // ⚠️ SIRA ÖNEMLİ: yalnızca dispatch BAŞARILIYSA alarm kuruluyor.
    // Aksi hâlde veritabanında plan olmayan bir alarm kalır ve
    // GitHub boş yere uyanır.
    //
    // ⚠️ TTL: plan süresi + 6 saat. Anahtar kendiliğinden temizleniyor,
    // yani iptal edilen bir plan sonsuza kadar KV'de kalmıyor. Zaten
    // bayat alarm zararsız — `planli_yayinlari_isle` DB'den doğruluyor
    // ve 4 saatten geç planı iptal ediyor.
    const sonraEslesme = YAYINLA_SONRA.exec(komut);
    if (iletildi && sonraEslesme && env.PLANLAR) {
      const dakika = Number(sonraEslesme[1]);
      const an = new Date(Date.now() + dakika * 60000).toISOString();
      try {
        await env.PLANLAR.put(`plan:${hedefMesajId}`, an,
          { expirationTtl: dakika * 60 + 21600 });
      } catch (e) {
        // KV yazılamazsa saatlik `son_dakika` yedek yol olarak planı
        // yine de işler — yalnızca daha geç. Sessiz kalmak doğru:
        // kullanıcıya "yayın planlandı" denmesi gereken an burası değil.
      }
    }

    // Plan iptal edilirse alarmı da kaldır — yoksa GitHub boş uyanır.
    if (iletildi && komut === "plan_iptal" && env.PLANLAR) {
      try {
        await env.PLANLAR.delete(`plan:${hedefMesajId}`);
      } catch (e) { /* bayat alarm zararsız */ }
    }

    if (iletildi) {
      // Önce görsel geri bildirim, sonra buton halkasını durdur.
      // Sıra önemli: kullanıcı butona bastıktan sonra ilk gördüğü şey
      // mesajın değişmesi olmalı.
      await islemeAlindiGoster(
        env, sohbetId, mesajId,
        cb.message ? cb.message.text : "", komut
      );
    }

    await butonuDurdur(
      env,
      cb.id,
      iletildi ? "Alındı, işleniyor…" : "İletilemedi, tekrar dene"
    );

    return new Response("ok");
  },

  async scheduled(event, env, ctx) {
    // Cloudflare Edge üzerinden sıfır gecikmeli cron tetikleyici
    if (!env.GITHUB_PAT || !env.GITHUB_REPO) return;
    const url = `https://api.github.com/repos/${env.GITHUB_REPO}/dispatches`;

    // 0. ZAMANLANMIŞ YAYIN ÇALAR SAATİ (her 10 dakikada bir)
    //
    // ⚠️ GITHUB'I HER SEFERİNDE UYANDIRMIYOR. KV'de zamanı gelmiş bir
    // plan yoksa hiçbir şey yapmadan çıkıyor — Cloudflare tarafı
    // ücretsiz, GitHub Actions yalnızca gerçek iş varken çalışıyor.
    // Sıklığı `son_dakika` cron'uyla artırmak +1620 dk/ay getirirdi
    // ve 3000'lik kotayı patlatırdı (ölçüm CLAUDE.md'de).
    //
    // ⚠️ KV GERÇEĞİN KAYNAĞI DEĞİL, yalnızca çalar saat. Veritabanı
    // asıl kayıt; `planli_yayinlari_isle` zaten oradan doğruluyor.
    // Bayat bir anahtar en fazla boş bir çalışma üretir — bu yüzden
    // KV ile DB'nin ayrışması TEHLİKESİZ (projede "aynı veri iki
    // yerde" tuzağının zararsız olduğu nadir yerlerden biri).
    if (event.cron === "*/10 * * * *") {
      if (!env.PLANLAR) return;
      const simdi = Date.now();
      let zamaniGelen = 0;
      try {
        const liste = await env.PLANLAR.list({ prefix: "plan:" });
        for (const anahtar of liste.keys) {
          const deger = await env.PLANLAR.get(anahtar.name);
          if (!deger) continue;
          if (Date.parse(deger) <= simdi) {
            zamaniGelen++;
            await env.PLANLAR.delete(anahtar.name);
          }
        }
      } catch (e) {
        // KV okunamazsa sessiz kal: saatlik `son_dakika` yedek yol
        // olarak planlı yayınları zaten işliyor, yalnızca daha geç.
        return;
      }
      if (!zamaniGelen) return;
      await fetch(url, {
        method: "POST",
        headers: {
          Accept: "application/vnd.github+json",
          Authorization: `Bearer ${env.GITHUB_PAT}`,
          "User-Agent": "HaberBot-CloudflareWorker",
        },
        body: JSON.stringify({
          event_type: "planli_yayin",
          client_payload: { adet: zamaniGelen, tetikleyen: "cloudflare_cron" },
        }),
      });
      return;
    }

    // 1. Hafta içi Borsa Bülteni — AÇILIŞ ve KAPANIŞ AYNI CRON'DA
    //    (TR 10:20 açılış / TR 18:20 kapanış — UTC 07:20 ve 15:20)
    //
    // ⚠️ İKİ AYRI CRON SATIRIYDI, BİRLEŞTİRİLDİ. Cloudflare ücretsiz
    // planda cron sınırı HESAP başına 5 ve aynı hesapta ezan botunun
    // tetikleyicisi de duruyor; ortak dakikada (20) toplanınca bir
    // slot boşaldı ve davranış korundu.
    //
    // ⚠️ CRON DİZGİSİ ARTIK HANGİ BÜLTEN OLDUĞUNU SÖYLEMİYOR — ayrım
    // SAATTEN yapılıyor. `scheduledTime` tercih ediliyor: tetiklemenin
    // PLANLANAN anı, worker'ın uyandığı an değil. Yan faydası, testin
    // saati enjekte edip iki modu da ağa çıkmadan sınayabilmesi.
    //
    // ⚠️ Yanlış mod gönderilse bile `piyasa_otomatik.py` saat
    // penceresini ayrıca denetliyor (açılış 09:55-11:30, kapanış
    // 18:15-20:00 TR) — yani bu ayrım tek savunma katmanı değil.
    if (event.cron === "20 7,15 * * 1-5") {
      const saatUTC = new Date(event.scheduledTime ?? Date.now()).getUTCHours();
      const mod = saatUTC < 12 ? "acilis" : "kapanis";
      await fetch(url, {
        method: "POST",
        headers: {
          Accept: "application/vnd.github+json",
          Authorization: `Bearer ${env.GITHUB_PAT}`,
          "User-Agent": "HaberBot-CloudflareWorker",
        },
        body: JSON.stringify({
          event_type: "piyasa_bulteni",
          client_payload: { mod: mod, tetikleyen: "cloudflare_cron" },
        }),
      });
      return;
    }

    // 3. Saatlik son dakika ve taze haber taraması
    await fetch(url, {
      method: "POST",
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${env.GITHUB_PAT}`,
        "User-Agent": "HaberBot-CloudflareWorker",
      },
      body: JSON.stringify({
        event_type: "son_dakika_calistir",
        client_payload: { tetikleyen: "cloudflare_cron" },
      }),
    });
  },
};
