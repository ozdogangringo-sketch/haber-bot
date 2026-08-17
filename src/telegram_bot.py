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
    for deneme in range(1, 4):
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
        [{"text": "✅ Yayınla", "callback_data": "yayinla"}],
        [{"text": "🔄 Tüm metinleri yeniden üret", "callback_data": "metin_yenile"}],
        [{"text": f"🎨 Slayt düzenle ({adet} slayt)",
          "callback_data": f"slayt_menu:{adet}"}],
        [{"text": "⏰ 1 saat ertele", "callback_data": "ertele"}],
        [{"text": "❌ Bu turu atla", "callback_data": "iptal"}],
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


def foto_gonder(url: str, aciklama: str = "") -> int:
    """
    Tek fotoğraf gönderir.

    Slayt görseli değiştirildiğinde kullanılıyor: yeni görseli link
    olarak vermek yerine göstermek gerekiyor, yoksa beğenip beğenmediğini
    anlamak için tarayıcı açman lazım.
    """
    sonuc = _istek("sendPhoto", chat_id=_sohbet_id(), photo=url,
                   caption=aciklama[:1024])
    return sonuc["message_id"]


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


def sonucu_yaz(message_id: int, metin: str, bildir: bool = False) -> None:
    """
    Onay mesajını sonuçla günceller ve butonları kaldırır.

    Butonların kaldırılması önemli: kalırsa biri yayından sonra tekrar
    basar ve ikinci kez yayınlamaya çalışırız.

    `bildir=True` sonucu AYRICA yeni bir mesaj olarak gönderir.

    ⚠️ NEDEN GEREKİYOR: `editMessageText` var olan mesajı değiştiriyor ve
    Telegram düzenlemede BİLDİRİM ÜRETMİYOR. Onay mesajı sohbette
    yukarıda, uzun caption'ın içinde kalıyor; yayın 2 dakika sürdüğü için
    kullanıcı o sırada başka yere bakıyor ve sonucu hiç görmüyor.
    17 Ağu 2026: post, story ve Facebook paylaşımının üçü de başarıyla
    çıktı, kullanıcı "telegramda bir dönüt alamadım" dedi.

    Düzenleme yine de yapılıyor — butonları kaldırmanın başka yolu yok.
    """
    _istek("editMessageText", chat_id=_sohbet_id(), message_id=message_id,
           text=metin[:4096], reply_markup={"inline_keyboard": []},
           disable_web_page_preview=True)

    if bildir:
        # Bildirim gönderilemese bile yayın başarılı; sonucu düşürmeyelim.
        try:
            mesaj_gonder(metin)
        except Exception as e:
            log.warning("sonuç bildirimi gönderilemedi: %s", e)


def mesaj_gonder(metin: str) -> int:
    """Düz bilgi/hata mesajı — buton yok."""
    sonuc = _istek("sendMessage", chat_id=_sohbet_id(), text=metin[:4096],
                   disable_web_page_preview=True)
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
