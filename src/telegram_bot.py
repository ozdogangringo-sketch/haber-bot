"""
telegram_bot.py — ADIM 5
Onay mesajını "Daily Brief" grubuna gönderir ve butonları yönetir.

MESAJ NEDEN İKİ PARÇA:
    Telegram'ın `sendMediaGroup` metodu (albüm) inline buton KABUL ETMİYOR.
    10 slaytı albüm olarak göndermek istiyoruz ama butonlar da lazım, o
    yüzden akış şöyle:
        1. sendMediaGroup  -> 10 slayt, albüm halinde
        2. sendMessage     -> caption + onay butonları
    İkinci mesajın id'si `telegram_message_id` olarak saklanıyor; sonucu
    yazarken düzenlenecek olan o.

CAPTION NEDEN ALBÜMDE DEĞİL:
    Albüm başlığı en fazla 1024 karakter. Bizim caption ~1100 karakter
    (ölçüldü). Sınırı aştığı için ayrı mesaja alındı; sendMessage sınırı
    4096, rahat sığıyor.

SUPERGROUP TUZAĞI:
    Telegram bir grubu supergroup'a yükselttiğinde chat ID DEĞİŞİR ve bot
    sessizce mesaj atamaz olur. Hata cevabında `parameters.migrate_to_chat_id`
    ile yeni ID veriliyor; `_istek` bunu yakalayıp .env'i güncelliyor ve
    isteği yeni ID ile tekrarlıyor. Yoksa bir gün onay mesajları gelmez ve
    sebebi anlaşılmaz.

YETKİ:
    Gruptaki HERKES onaylayabilir. Kullanıcının açık tercihi; kimin
    bastığını denetleyen bir kısıt bilerek YOK.
"""

from __future__ import annotations

import json
import html
import logging
import os
import re
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

log = logging.getLogger(__name__)
load_dotenv()

KOK = Path(__file__).resolve().parent.parent
ENV_YOLU = KOK / ".env"
TABAN = "https://api.telegram.org/bot{jeton}/{metot}"
GECICI_HATALAR = {429, 500, 502, 503, 504}

# ⚠️ HTTP KODUNA BAKMAK YETMİYOR — medya hataları 400 ile geliyor.
#
# 19 Ağu 2026 akşam turu şu hatayla düştü ve tur tamamen kayboldu:
#     400: failed to send message #9 with the error message
#          "WEBPAGE_CURL_FAILED"
#
# Anlamı: Telegram, albümdeki 9. görseli imgbb'den KENDİSİ indirmeye
# çalıştı ve indiremedi. Görselde kusur yok — Instagram'daki 2207052
# hatasının birebir kardeşi. 400 "kalıcı hata" sayıldığı için hiç
# tekrar denenmedi; oysa aynı URL saniyeler sonra sorunsuz iniyor.
GECICI_MESAJLAR = (
    "WEBPAGE_CURL_FAILED",
    "failed to get http url content",
    "wrong file identifier",
    "failed to send message",
)

# Medya indirme hatasında bekleme. Instagram ve Threads'te ölçüldü:
# sorun karşı tarafın o anki durumu, 2 saniye sonra tekrar sormak
# aynı yükün üstüne binmek oluyor.
MEDYA_BEKLEME_SANIYE = 10
MEDYA_AZAMI_DENEME = 5
ZAMAN_ASIMI = 60


def _jeton() -> str:
    j = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not j:
        raise RuntimeError("TELEGRAM_BOT_TOKEN bulunamadı (.env)")
    return j


def _sohbet_id() -> str:
    s = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not s:
        raise RuntimeError("TELEGRAM_CHAT_ID bulunamadı (.env)")
    return s


def _yeni_sohbet_id_kaydet(yeni: str) -> None:
    """
    Supergroup'a yükseltilen grubun yeni ID'sini .env'e yazar.

    GitHub Actions'ta .env yok (secrets kullanılıyor); orada yazma
    başarısız olsa da tur devam etmeli, bu yüzden hata yutuluyor —
    ama loga BASILIYOR ki secret elle güncellenebilsin.
    """
    os.environ["TELEGRAM_CHAT_ID"] = yeni
    log.warning(
        "GRUP SUPERGROUP'A YÜKSELTİLDİ. Yeni TELEGRAM_CHAT_ID=%s — "
        "GitHub Secrets'taki değeri de elle güncelle.", yeni
    )
    try:
        if not ENV_YOLU.exists():
            return
        satirlar = ENV_YOLU.read_text(encoding="utf-8").splitlines()
        for i, satir in enumerate(satirlar):
            if satir.split("=", 1)[0].strip() == "TELEGRAM_CHAT_ID":
                satirlar[i] = f"TELEGRAM_CHAT_ID={yeni}"
                break
        ENV_YOLU.write_text("\n".join(satirlar) + "\n", encoding="utf-8")
    except Exception as e:
        log.warning(".env güncellenemedi (%s) — ortam değişkeni yine de ayarlandı", e)


def _istek(metot: str, **parametreler) -> dict:
    """
    Telegram API çağrısı. Geçici hatalarda tekrar dener, supergroup
    göçünü yakalar.
    """
    url = TABAN.format(jeton=_jeton(), metot=metot)

    son_hata = None
    for deneme in range(1, MEDYA_AZAMI_DENEME + 1):
        try:
            cevap = requests.post(url, json=parametreler, timeout=ZAMAN_ASIMI)
        except requests.RequestException as e:
            son_hata = f"{type(e).__name__}: {e}"
            time.sleep(2 * deneme)
            continue

        veri = cevap.json() if cevap.content else {}

        if veri.get("ok"):
            return veri["result"]

        # Supergroup göçü: yeni ID ile aynı isteği tekrarla
        yeni = (veri.get("parameters") or {}).get("migrate_to_chat_id")
        if yeni:
            _yeni_sohbet_id_kaydet(str(yeni))
            if "chat_id" in parametreler:
                parametreler["chat_id"] = str(yeni)
            continue

        # Hız sınırı: Telegram kaç saniye bekleyeceğimizi söylüyor
        bekle = (veri.get("parameters") or {}).get("retry_after")
        if bekle:
            time.sleep(min(int(bekle) + 1, 60))
            continue

        son_hata = f"{veri.get('error_code')}: {veri.get('description')}"
        if cevap.status_code in GECICI_HATALAR:
            time.sleep(2 * deneme)
            continue

        # Medya indirme hatası: 400 geliyor ama GEÇİCİ (bkz. GECICI_MESAJLAR)
        aciklama = (veri.get("description") or "").lower()
        if any(k in aciklama for k in GECICI_MESAJLAR):
            log.warning("Telegram medyayı indiremedi, %s sn sonra tekrar (%s/%s): %s",
                        MEDYA_BEKLEME_SANIYE, deneme, MEDYA_AZAMI_DENEME,
                        veri.get("description", "")[:80])
            time.sleep(MEDYA_BEKLEME_SANIYE)
            continue
        break

    raise RuntimeError(f"Telegram hatası ({metot}): {son_hata}")


# ----------------------------------------------------------------------
# Butonlar
# ----------------------------------------------------------------------
#
# callback_data 64 BAYT ile sınırlı — uzun metin koyulamaz, kısa kodlar
# kullanıyoruz. Worker bu kodları çözüp GitHub'a iletecek.

#
# DİKKAT: Bu üç menü `worker/index.js` içinde de birebir tanımlı. Menü
# gezinmesini Worker yapıyor (GitHub Actions'ı uyandırmak 30+ saniye
# sürüyor, menü açmak anında olmalı). Buradaki buton düzenini
# değiştirirsen Worker'daki karşılığını da değiştir.
#
# Slayt sayısı callback_data'ya gömülü ("slayt_menu:10"): Worker'ın turda
# kaç slayt olduğunu öğrenebileceği başka bir yol yok.

def ana_menu(adet: int) -> dict:
    """Onay mesajının ilk buton seti."""
    return {"inline_keyboard": [
        [{"text": "✅ Yayınla", "callback_data": f"yayin_menu:{adet}"}],
        [{"text": "🔄 Tüm metinleri yeniden üret", "callback_data": "metin_yenile"}],
        [{"text": f"🎨 Slayt düzenle ({adet} slayt)",
          "callback_data": f"slayt_menu:{adet}"}],
        [{"text": "⏰ 1 saat ertele", "callback_data": "ertele"}],
        # ⚠️ "Atla" ile farkı: atla haberi havuza döndürüyor ve haber
        # bir sonraki kontrolde YİNE tekil post adayı oluyordu — 20 Ağu
        # 2026'da "Türkiye'de yağışlar son 66 yılın zirvesinde" haberi
        # 23 dakika arayla iki kez sunuldu. Bu düğme haberi tekil
        # adaylıktan çıkarıyor ama turda bırakıyor.
        [{"text": "📋 Tekil atma, 10'lu tura bırak",
          "callback_data": "tura_birak"}],
        [{"text": "❌ Bu turu atla", "callback_data": "iptal"}],
    ]}


def alternatif_menusu(sira: int, adaylar: list, adet: int) -> dict:
    """
    Bir slaytın yerine gelebilecek haberleri sunar.

    Başlık DÜĞMENİN ÜSTÜNDE yazıyor çünkü `callback_data` 64 baytla
    sınırlı — oraya yalnızca haber id'si sığıyor. Düğme metni de
    Telegram'da tek satıra kırpıldığı için 60 karakterde kesiliyor.
    """
    tuslar = []
    for a in adaylar:
        baslik = (a["ig_baslik"] or a["baslik_orj"] or "")[:58]
        tuslar.append([{"text": f"✅ {baslik}",
                        "callback_data": f"haber_sec:{sira}:{a['id']}"}])
    tuslar.append([{"text": "← Vazgeç", "callback_data": f"geri:{adet}"}])
    return {"inline_keyboard": tuslar}


def yayin_zamani_menusu(adet: int) -> dict:
    """
    "Yayınla" düğmesinin alt menüsü: şimdi mi, sonra mı?

    ⚠️ SEÇENEKLER 30 DAKİKANIN KATLARI. Zamanı gelen turu son dakika
    kontrolü yayınlıyor ve o cron 30 dakikada bir çalışıyor; "15 dk"
    seçeneği koysaydık gerçekte 15-45 dakika arası yayınlanırdı ve
    düğme yalan söylemiş olurdu.

    İki sütun: dar ekranda okunur kalsın.
    """
    return {"inline_keyboard": [
        [{"text": "▶️ Şimdi", "callback_data": "yayinla"},
         {"text": "30 dk", "callback_data": "yayinla_sonra:30"}],
        [{"text": "1 saat", "callback_data": "yayinla_sonra:60"},
         {"text": "2 saat", "callback_data": "yayinla_sonra:120"}],
        [{"text": "3 saat", "callback_data": "yayinla_sonra:180"},
         {"text": "4 saat", "callback_data": "yayinla_sonra:240"}],
        [{"text": "← Geri", "callback_data": f"yayin_geri:{adet}"}],
    ]}


def slayt_secim_menusu(adet: int) -> dict:
    """
    Hangi slayta müdahale edileceğini seçtiren menü.

    Beşerli iki satır: Telegram butonları yan yana sıkıştırıyor, 10 tanesi
    tek satırda okunmuyor.
    """
    satir1 = [{"text": str(i), "callback_data": f"slayt:{i}:{adet}"}
              for i in range(1, min(adet, 5) + 1)]
    satir2 = [{"text": str(i), "callback_data": f"slayt:{i}:{adet}"}
              for i in range(6, adet + 1)]
    tuslar = [satir1]
    if satir2:
        tuslar.append(satir2)
    tuslar.append([{"text": "← Geri", "callback_data": f"geri:{adet}"}])
    return {"inline_keyboard": tuslar}


def slayt_islem_menusu(sira: int, adet: int) -> dict:
    """
    Seçilen slayt için yapılabilecekler.

    `slayt_kaynak` neden var: Gemini az bilgiyle çalıştığında kaynakta
    OLMAYAN iddia uydurabiliyor (Adım 2'de ölçüldü — bir milletvekili ve
    taciz suçlaması hakkında). Üretilen metin akıcı ve inandırıcı
    göründüğü için onay adımı tek başına bu riski çözmüyor. Bu buton
    haberin ham metnini gösteriyor ki "modelin yazdığı bu cümle haberde
    gerçekten var mı?" diye bakabilesin.

    `slayt_sil` carousel'i 2'nin altına düşürmemeli — Instagram tek
    görselli carousel kabul etmiyor. Kontrol job tarafında.
    """
    return {"inline_keyboard": [
        [{"text": f"🔀 {sira}. slayt: başka fotoğraf (bedava)",
          "callback_data": f"slayt_foto:{sira}"}],
        [{"text": f"🎨 {sira}. slayt: AI ile üret (~$0.04)",
          "callback_data": f"slayt_ai:{sira}"}],
        [{"text": f"✏️ {sira}. slaytın metnini yenile",
          "callback_data": f"slayt_metin:{sira}"}],
        [{"text": f"📄 {sira}. slaytın kaynak metnini göster",
          "callback_data": f"slayt_kaynak:{sira}"}],
        [{"text": f"🔄 {sira}. slaytın HABERİNİ değiştir",
          "callback_data": f"haber_degistir:{sira}"}],
        [{"text": f"🗑 {sira}. slaytı çıkar",
          "callback_data": f"slayt_sil:{sira}"}],
        [{"text": "← Geri", "callback_data": f"slayt_menu:{adet}"}],
    ]}


# ----------------------------------------------------------------------
# Gönderim
# ----------------------------------------------------------------------

# Görselin hangi katmandan geldiğini tek bakışta gösteren simgeler.
# Onay verirken en çok merak edilen şey bu: "bu fotoğraf gerçek mi,
# temsili mi?" Commons gerçek kişinin fotoğrafı, Pexels temsili.
KATMAN_SIMGE = {
    "commons": "📷",
    "pexels": "🖼",
    "gradyan": "▪️",
    "ai": "🎨",
}


def slaytlari_gonder(
    gorsel_urlleri: list[str], basliklar: list[str] | None = None
) -> list[int]:
    """
    Slaytları albüm olarak gönderir. Mesaj id'lerini döner.

    URL veriyoruz, dosya değil: görseller zaten imgbb'de duruyor ve
    Telegram'ın kendisi indiriyor — 10 dosyayı ikinci kez yüklemenin
    anlamı yok.

    Her fotoğrafa kendi sıra numarası yazılıyor. Bunsuz "3. slaytı
    değiştir" demek için albümdeki fotoğrafları tek tek saymak
    gerekiyordu.
    """
    medya = []
    for sira, url in enumerate(gorsel_urlleri, start=1):
        oge = {"type": "photo", "media": url}
        if basliklar and sira <= len(basliklar):
            # Telegram albümde her öğenin kendi başlığını taşıyabiliyor;
            # fotoğrafa dokununca görünüyor. 1024 karakter sınırı var.
            oge["caption"] = f"{sira}. {basliklar[sira - 1]}"[:1024]
        else:
            oge["caption"] = f"{sira}."
        medya.append(oge)

    sonuc = _istek("sendMediaGroup", chat_id=_sohbet_id(), media=medya)
    return [m["message_id"] for m in sonuc]


def tur_ozeti(haberler: list, uyari_sayisi: int = 0) -> str:
    """
    Onay mesajının başına konan özet tablo.

    Neden gerekli: caption Instagram'a gidecek metin, onay vermek için
    yetmiyor. Karar verirken bakılan şeyler ayrı — kaç slayt var, görsel
    nereden geldi, denetim ne dedi. Bunlar caption'da yok.
    """
    satirlar = []
    for sira, haber in enumerate(haberler, start=1):
        katman = (haber["gorsel_kaynagi"] or "gradyan").strip()
        simge = KATMAN_SIMGE.get(katman, "▫️")
        baslik = (haber["ig_baslik"] or haber["baslik_orj"] or "").strip()
        satirlar.append(f"{sira:>2} {simge} {baslik[:58]}")

    durum = ("✅ denetim temiz" if not uyari_sayisi
             else f"⚠️ {uyari_sayisi} slaytta uyarı — aşağıya bak")

    return (
        f"📋 {len(haberler)} slayt  ·  {durum}\n"
        f"📷 gerçek foto · 🖼 temsili · ▪️ gradyan · 🎨 AI\n\n"
        + "\n".join(satirlar)
    )


def foto_gonder(url: str, aciklama: str = "",
                butonlar: list | None = None) -> int:
    """
    Tek fotoğraf gönderir.

    Slayt görseli değiştirildiğinde kullanılıyor: yeni görseli link
    olarak vermek yerine göstermek gerekiyor, yoksa beğenip beğenmediğini
    anlamak için tarayıcı açman lazım.

    `butonlar` verilirse fotoğrafın altına inline klavye eklenir —
    "bu görseli kullan / başka dene" onayı için.
    """
    ek = {"reply_markup": {"inline_keyboard": butonlar}} if butonlar else {}
    sonuc = _istek("sendPhoto", chat_id=_sohbet_id(), photo=url,
                   caption=aciklama[:1024], **ek)
    return sonuc["message_id"]


def mesajlari_sil(mesaj_idleri: list[int]) -> int:
    """
    Verilen mesajları siler. Kaç tanesinin silindiğini döner.

    ⚠️ ALBÜM YENİLEMEK İÇİN GEREKLİ. Telegram'da media group ATOMİK bir
    birim: `editMessageMedia` albümdeki tek bir fotoğrafı değiştiremiyor.
    Slayt görseli değişince üstteki albümü güncel göstermenin tek yolu
    eskisini silip yeniden göndermek.

    Bot yalnızca KENDİ mesajlarını silebiliyor (grupta yönetici değil),
    yani kullanıcının yazdıkları risk altında değil. Silinemeyen mesaj
    sessizce atlanıyor: 48 saatten eski mesajlar silinemiyor ve bu
    beklenen bir durum, turu düşürmemeli.
    """
    silinen = 0
    for mid in mesaj_idleri or []:
        try:
            _istek("deleteMessage", chat_id=_sohbet_id(), message_id=mid)
            silinen += 1
        except Exception as e:                        # noqa: BLE001
            log.debug("mesaj silinemedi (%s): %s", mid, e)
    return silinen


def onay_iste(caption: str, slayt_adedi: int, uyari: str = "",
              ozet: str = "") -> int:
    """
    Özeti, caption'ı ve onay butonlarını gönderir. message_id döner.

    Bu id `telegram_message_id` olarak saklanmalı — sonuç yazılırken
    düzenlenecek mesaj bu.

    Sıralama bilinçli: önce denetim uyarısı (varsa hemen görülmeli),
    sonra özet tablo (karar burada veriliyor), en sonda caption
    (Instagram'a gidecek metin, doğrulaması en az acil olan).
    """
    parcalar = [p for p in (uyari, ozet) if p]
    parcalar.append("— Instagram açıklaması —\n" + caption)
    metin = "\n\n".join(parcalar)
    # sendMessage sınırı 4096; caption ~1100 olduğu için pay bol.
    sonuc = _istek(
        "sendMessage",
        chat_id=_sohbet_id(),
        text=metin[:4096],
        reply_markup=ana_menu(slayt_adedi),
        disable_web_page_preview=True,
    )
    return sonuc["message_id"]


def menuyu_degistir(message_id: int, menu: dict) -> None:
    """Mesajın butonlarını değiştirir (metne dokunmaz)."""
    _istek("editMessageReplyMarkup", chat_id=_sohbet_id(),
           message_id=message_id, reply_markup=menu)


def mesaji_guncelle(message_id: int, metin: str, menu: dict) -> None:
    """
    Mesajın hem metnini hem butonlarını değiştirir.

    Worker butona basıldığı anda butonları kaldırıp "⏳ İşleniyor"
    yazıyor. İş bitip tur devam ediyorsa (slayt değişimi gibi) menü geri
    konmalı, yoksa tur kilitlenir.
    """
    try:
        _istek("editMessageText", chat_id=_sohbet_id(), message_id=message_id,
               text=metin[:4096], reply_markup=menu,
               disable_web_page_preview=True)
    except RuntimeError as e:
        # "message is not modified" hatası zararsız: metin zaten aynıysa
        # Telegram düzenlemeyi reddediyor.
        if "not modified" not in str(e):
            raise


def sonucu_yaz(message_id: int, metin: str, bildir: bool = False,
               butonlar: dict | None = None) -> None:
    """
    Onay mesajını sonuçla günceller ve butonları kaldırır.

    Butonların kaldırılması önemli: kalırsa biri yayından sonra tekrar
    basar ve ikinci kez yayınlamaya çalışırız.

    `bildir=True` sonucu AYRICA yeni bir mesaj olarak gönderir.

    `butonlar` verilirse klavye BOŞALTILMAZ, verilen düzen konur —
    zamanlanmış yayında "planı iptal et" düğmesinin kalması gerekiyor.

    ⚠️ NEDEN GEREKİYOR: `editMessageText` var olan mesajı değiştiriyor ve
    Telegram düzenlemede BİLDİRİM ÜRETMİYOR. Onay mesajı sohbette
    yukarıda, uzun caption'ın içinde kalıyor; yayın 2 dakika sürdüğü için
    kullanıcı o sırada başka yere bakıyor ve sonucu hiç görmüyor.
    17 Ağu 2026: post, story ve Facebook paylaşımının üçü de başarıyla
    çıktı, kullanıcı "telegramda bir dönüt alamadım" dedi.

    Düzenleme yine de yapılıyor — butonları kaldırmanın başka yolu yok.
    """
    _istek("editMessageText", chat_id=_sohbet_id(), message_id=message_id,
           text=metin[:4096],
           reply_markup=butonlar or {"inline_keyboard": []},
           disable_web_page_preview=True)

    if bildir:
        # Bildirim gönderilemese bile yayın başarılı; sonucu düşürmeyelim.
        try:
            # Yayın sonucuna "kaldır" düğmesi: gece otomatik yayın açıkken
            # sabah uyanıp postu tek tuşla geri alabilmek gerekiyor.
            # Tur id'si düğmeye gömülü, çünkü bu YENİ bir mesaj ve kendi
            # message_id'si turunkinden farklı.
            butonlar = [[{"text": "🗑 Bu yayını kaldır",
                          "callback_data": f"kaldir:{message_id}"}]]
            mesaj_gonder(metin, butonlar=butonlar)
        except Exception as e:
            log.warning("sonuç bildirimi gönderilemedi: %s", e)


def mesaj_gonder(metin: str, butonlar: list | None = None,
                 html: bool = False) -> int:
    """
    Düz bilgi/hata mesajı.

    `butonlar` verilirse inline klavye eklenir — yayın sonucuna
    "kaldır" düğmesi koyabilmek için.

    ⚠️ `html` VARSAYILAN OLARAK KAPALI. Telegram'a `parse_mode`
    göndermezsek etiketler metin olarak görünüyor; gönderirsek de
    metindeki her `<` ve `&` kaçırılmak zorunda, yoksa Telegram
    mesajı "can't parse entities" ile REDDEDİYOR ve mesaj sessizce
    hiç ulaşmıyor. Bu modüldeki eski çağrıların metinleri
    kaçırılmamış olduğu için varsayılan kapalı; HTML isteyen çağıran
    `_kacir()` kullanmak zorunda.
    """
    ek = {}
    if butonlar:
        ek["reply_markup"] = {"inline_keyboard": butonlar}
    if html:
        ek["parse_mode"] = "HTML"
    sonuc = _istek("sendMessage", chat_id=_sohbet_id(), text=metin[:4096],
                   disable_web_page_preview=True, **ek)
    return sonuc["message_id"]


def paylasim_bildir(kanal: str, basarili: bool, ayrinti: str = "",
                    baglanti: str = "") -> None:
    """
    Bir kanala paylaşım yapıldığında (ya da yapılamadığında) haber verir.

    NEDEN AYRI BİR BİLDİRİM: yayın sonucu şimdiye kadar yalnızca onay
    mesajının içinde özetleniyordu. Ama artık paylaşım Telegram'dan
    tetiklenmeyen yerlerden de olabiliyor — gece otomatik yayını, elle
    çalıştırılan geçmiş paylaşımı — ve o durumlarda hiçbir bildirim
    gitmiyordu. 18 Ağu 2026'da bir Threads zinciri yarım kaldı ve bu
    ancak elle bakılınca fark edildi.

    Bildirim gönderilemezse yutuluyor: haber verememek, işi durdurmayı
    gerektirmez.
    """
    try:
        simge = "✅" if basarili else "⚠️"
        satirlar = [f"{simge} {kanal}"]
        if ayrinti:
            satirlar.append(ayrinti)
        if baglanti:
            satirlar.append(baglanti)
        mesaj_gonder("\n".join(satirlar))
    except Exception as e:
        log.warning("paylaşım bildirimi gönderilemedi: %s", e)


def paneli_tazele(message_id: int, metin: str, butonlar: list) -> None:
    """
    Var olan bir paneli metniyle ve düğmeleriyle birlikte günceller.

    Ayar paneli için: değer değiştirmek üst üste yapılan bir iş ve her
    basışta yeni mesaj göndermek sohbeti dolduruyor.
    """
    _istek("editMessageText", chat_id=_sohbet_id(), message_id=message_id,
           text=metin[:4096], disable_web_page_preview=True,
           reply_markup={"inline_keyboard": butonlar})


def butonlari_ayarla(message_id: int, butonlar: list) -> None:
    """
    Var olan bir mesajın düğmelerini değiştirir.

    Gece otomatik yayını için gerekti: "kaldır" düğmesi turun id'sini
    taşımak zorunda, ama o id mesaj GÖNDERİLDİKTEN sonra belli oluyor
    (mesajın kendi id'si tur kimliği olarak kullanılıyor). Bu yüzden
    mesaj önce düğmesiz gidiyor, id öğrenilince düğme ekleniyor.
    """
    try:
        _istek("editMessageReplyMarkup", chat_id=_sohbet_id(),
               message_id=message_id,
               reply_markup={"inline_keyboard": butonlar})
    except Exception as e:
        log.warning("düğmeler ayarlanamadı: %s", e)


def hata_bildir(baslik: str, ayrinti: str = "") -> None:
    """
    Bir job patladığında haber verir (Adım 7).

    Bildirim gönderirken hata çıkarsa yutuyoruz: hata bildiriminin
    kendisi turu düşürmemeli.
    """
    try:
        metin = f"⚠️ {baslik}"
        if ayrinti:
            metin += f"\n\n{ayrinti[:1500]}"
        mesaj_gonder(metin)
    except Exception as e:
        log.error("hata bildirimi gönderilemedi: %s", e)


def _kacir(metin: str) -> str:
    """
    Telegram HTML modunda güvenli hale getirir.

    ⚠️ Haber başlıkları dışarıdan geliyor ve `&`, `<`, `>` içerebilir;
    kaçırılmazsa Telegram mesajı "can't parse entities" ile reddediyor
    ve o tur sessizce Telegram'a HİÇ ulaşmıyor.
    """
    return html.escape(metin or "", quote=False)


def oneri_gonder(adaylar: list) -> int:
    """
    Tekil post için BAŞLIK ÖNERİSİ — çoklu seçim.

    ⚠️ NEDEN İKİ AŞAMALI ONAY (19 Ağu 2026):
        Eskiden kontrol job'ı taze haberlere TAM metin üretiyor
        (~4400 token), sonra puanına bakıp eşiği geçmiyorsa
        ATIYORDU. Üretilen metnin çoğu çöpe gidiyordu. Şimdi önce
        yalnızca başlıklar puanlanıp buraya geliyor; tam metin ve
        görsel yalnızca seçilenler için üretiliyor.

    ⚠️ ÇOKLU SEÇİM WORKER'DA, GITHUB'DA DEĞİL. Numaralara basmak
        yalnızca butonun metnine ✓ ekleyip çıkarıyor — Worker mesajı
        anında düzenliyor, Actions hiç uyanmıyor. Tek bir "Hazırla"
        basışında seçili olanların hepsi tek dispatch ile gidiyor.
        Her seçimde Actions çalıştırmak 3 haber için 3 ayrı job
        (~5 dk) demek olurdu.

    `adaylar`: [{id, puan, baslik, kaynak, kategori}] — puana göre sıralı.
    """
    if not adaylar:
        return 0

    # ⚠️ 3 İLE SINIRLI. Kontrol yarım saatte bir çalışıyor; 8 öneri
    # gün boyunca okunamayacak kadar mesaj üretiyordu. Kullanıcı
    # tercihi (20 Ağu 2026): "yarım saatte bir çalışacağı için 3
    # öneriyle sınırlayalım".
    rakam = ["1️⃣", "2️⃣", "3️⃣"]
    satirlar = ["📰 <b>Tekil post adayları</b>", ""]
    secim_butonlari = []
    for i, a in enumerate(adaylar[:len(rakam)]):
        satirlar.append(
            f"{rakam[i]} <b>[{a['puan']}]</b> {_kacir(a['baslik'])}"
        )
        satirlar.append(
            f"     <i>{_kacir(a['kaynak'])} · {_kacir(a['kategori'])}</i>"
        )
        satirlar.append("")
        secim_butonlari.append({"text": rakam[i],
                                "callback_data": f"sec:{a['id']}"})

    satirlar.append("<i>Numaralara basarak istediğin kadar haber seç, "
                    "sonra Hazırla'ya bas. Seçilenler sırayla üretilip "
                    "onayına sunulur.</i>")

    # Butonlar dörderli satırlara bölünüyor — Telegram dar ekranda
    # yan yana en fazla bu kadarını okunur gösteriyor.
    satir_butonlar = [secim_butonlari[i:i + 4]
                      for i in range(0, len(secim_butonlari), 4)]
    menu = satir_butonlar + [
        [{"text": "▶️ Hazırla (0)", "callback_data": "hazirla_secilenler"}],
        [{"text": "❌ Hiçbiri", "callback_data": "oneri_gec"}],
    ]
    # Başlıklar `_kacir` ile kaçırıldığı için HTML güvenli.
    return mesaj_gonder("\n".join(satirlar), menu, html=True)
