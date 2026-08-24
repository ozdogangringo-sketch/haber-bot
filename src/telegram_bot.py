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

def kanal_butonlari(kanallar: dict | None = None) -> list[dict]:
    """
    Yayın kanallarını açıp kapamak için toggle buton satırı üretir.

    Örnek: [✅ IG] [⬜ Reels] [✅ Story] [✅ Threads] [✅ FB] [✅ X]
    """
    if kanallar is None:
        kanallar = {"ig": True, "reels": False, "story": True, "threads": True, "facebook": True, "twitter": True}

    def _simge(k):
        return "✅" if kanallar.get(k, False if k == "reels" else True) else "⬜"

    return [
        {"text": f"{_simge('ig')} IG", "callback_data": "kanal:ig"},
        {"text": f"{_simge('reels')} Reels", "callback_data": "kanal:reels"},
        {"text": f"{_simge('story')} Story", "callback_data": "kanal:story"},
        {"text": f"{_simge('threads')} Threads", "callback_data": "kanal:threads"},
        {"text": f"{_simge('facebook')} FB", "callback_data": "kanal:facebook"},
        {"text": f"{_simge('twitter')} X", "callback_data": "kanal:twitter"},
    ]


def ana_menu(adet: int, kanallar: dict | None = None) -> dict:
    """Onay mesajının ilk buton seti."""
    return {"inline_keyboard": [
        kanal_butonlari(kanallar),
        [{"text": "✅ Yayınla", "callback_data": f"yayin_menu:{adet}"},
         {"text": "📲 Manuel Paylaşım Paketi", "callback_data": "manuel_paket"}],
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
        [{"text": "❌ Bu turu atla (Havuza döner)", "callback_data": "iptal"},
         {"text": "🗑️ Çöpe At (Havuza dönmesin)", "callback_data": "cope_at"}],
    ]}


def yonetim_menusu(duraklatildi: bool = False, kalan_sure: str = "") -> dict:
    """Yönetim ve acil durum kontrol paneli menüsü."""
    duraklat_butonu = (
        {"text": f"▶️ Devam Ettir ({kalan_sure})", "callback_data": "devam_et"}
        if duraklatildi
        else {"text": "⏸️ Botu Duraklat", "callback_data": "duraklat_menu"}
    )
    return {"inline_keyboard": [
        [{"text": "🔄 Gündem Turu Hazırla", "callback_data": "tur_hazirla"},
         {"text": "📈 Ekonomi Turu Hazırla", "callback_data": "ekonomi_hazirla"}],
        [duraklat_butonu, {"text": "📊 Kota & Durum", "callback_data": "kota_raporu"}],
        [{"text": "🧪 API Sağlık Testi", "callback_data": "saglik_testi"},
         {"text": "🧹 Askıdaki Turları Temizle", "callback_data": "tur_temizle"}],
        [{"text": "⚙️ Bot Ayarları", "callback_data": "ayar"},
         {"text": "🔄 Havuzu Güncelle", "callback_data": "havuz_guncelle"}],
    ]}


def duraklatma_secenekleri_menusu() -> dict:
    """Duraklatma süresi seçim menüsü."""
    return {"inline_keyboard": [
        [{"text": "⏸️ 1 Saat Duraklat", "callback_data": "duraklat:1"},
         {"text": "⏸️ 6 Saat Duraklat", "callback_data": "duraklat:6"}],
        [{"text": "⏸️ 12 Saat Duraklat", "callback_data": "duraklat:12"},
         {"text": "⏸️ 24 Saat Duraklat", "callback_data": "duraklat:24"}],
        [{"text": "← Yönetim Paneline Dön", "callback_data": "yonetim_panel"}],
    ]}


def baslik_onay_menusu() -> dict:
    """
    Tur başlıkları sunulduğunda gösterilen menü.

    Bu aşamada slayt YOK — sadece hangi haberlerin seçildiği. Onay
    gelince görseller üretilip normal onay mesajı gönderiliyor.
    """
    return {"inline_keyboard": [
        [{"text": "✅ Bu haberlerle devam et", "callback_data": "tur_onayla"}],
        [{"text": "🔄 Başka haberler seç", "callback_data": "tur_yeniden"}],
        [{"text": "❌ Bu turu atla", "callback_data": "iptal"}],
    ]}


def basliklari_sun(haberler: list) -> int:
    """
    Seçilen haberlerin başlıklarını numaralı liste olarak gönderir.

    Kategori ve kaynak da yazılıyor: kullanıcı listeye bakıp "bu tur
    fazla spor olmuş" ya da "hepsi aynı kaynaktan" diyebilsin.
    """
    satirlar = [f"📋 <b>TUR ÖNİZLEME — {len(haberler)} haber</b>",
                "<i>Görseller henüz üretilmedi.</i>", ""]
    for i, h in enumerate(haberler, 1):
        baslik = html.escape(h["ig_baslik"] or h["baslik_orj"] or "")
        etiket = html.escape((h["kategori"] or "?").upper())
        puan = h["onem_puani"] or "?"
        satirlar.append(f"<b>{i}.</b> {baslik}")
        satirlar.append(f"    <i>{etiket} · {puan} puan</i>")
    satirlar += ["", "Onaylarsan slaytlar hazırlanıp tam onaya sunulacak."]
    return mesaj_gonder("\n".join(satirlar), html=True,
                        butonlar=baslik_onay_menusu()["inline_keyboard"])


def basliklari_tazele(mesaj_id: int, haberler: list) -> None:
    """Mevcut başlık önizleme mesajını güncel liste ile yeniler."""
    satirlar = [f"📋 <b>TUR ÖNİZLEME — {len(haberler)} haber</b>",
                "<i>Görseller henüz üretilmedi.</i>", ""]
    for i, h in enumerate(haberler, 1):
        baslik = html.escape(h["ig_baslik"] or h["baslik_orj"] or "")
        etiket = html.escape((h["kategori"] or "?").upper())
        puan = h["onem_puani"] or "?"
        satirlar.append(f"<b>{i}.</b> {baslik}")
        satirlar.append(f"    <i>{etiket} · {puan} puan</i>")
    satirlar += ["", "Onaylarsan slaytlar hazırlanıp tam onaya sunulacak."]
    mesaji_guncelle(mesaj_id, "\n".join(satirlar), baslik_onay_menusu())


def alternatif_menusu(eski_id: int, adaylar: list, tur_mesaj_id: int) -> dict:
    """
    Bir slaytın yerine gelebilecek haberleri sunar.

    ⚠️ TUR MESAJ ID'Sİ DÜĞMEYE GÖMÜLÜ. Bu menü AYRI bir mesajda
    duruyor ve o mesajın kendi `message_id`'si turunkinden farklı;
    Worker `cb.message.message_id` gönderdiği için tur bulunamıyor.
    20 Ağu 2026'da tam bu oldu: düğmeye basıldı, job
    "mesaj_id=487 için haber bulunamadı" ile düştü, tur 474'tü.

    Aynı tuzak `kaldir:{tur_id}` düğmesinde zaten çözülmüştü —
    CLAUDE.md'de kayıtlı. Yeni bir ayrı-mesaj düğmesi eklerken bu
    deseni kullan.

    ⚠️ SLAYT NUMARASI DEĞİL HABER ID'Sİ TAŞINIYOR. Numara kırılgan:
    tur yeniden sıralanınca (ör. gündüz yayınlanmış haberler sona
    alınınca) "5. slayt" başka bir haberi işaret ediyor ve açık duran
    bir alternatif mesajı YANLIŞ slaydı değiştiriyor. 20 Ağu 2026'da
    tam bu oldu. Haber id'si hiç değişmiyor.

    Başlık düğme METNİNDE, `callback_data`'da değil: 64 bayt sınırı.
    """
    tuslar = []
    for a in adaylar:
        baslik = (a["ig_baslik"] or a["baslik_orj"] or "")[:58]
        tuslar.append([{
            "text": f"✅ {baslik}",
            "callback_data": f"haber_sec:{eski_id}:{a['id']}:{tur_mesaj_id}"}])
    tuslar.append([{"text": "← Vazgeç",
                    "callback_data": f"haber_vazgec:{tur_mesaj_id}"}])
    return {"inline_keyboard": tuslar}


def yayin_zamani_menusu(adet: int, kanallar: dict | None = None) -> dict:
    """
    "Yayınla" düğmesinin alt menüsü: şimdi mi, sonra mı?

    ⚠️ SEÇENEKLER 30 DAKİKANIN KATLARI. Zamanı gelen turu son dakika
    kontrolü yayınlıyor ve o cron 30 dakikada bir çalışıyor; "15 dk"
    seçeneği koysaydık gerçekte 15-45 dakika arası yayınlanırdı ve
    düğme yalan söylemiş olurdu.

    İki sütun: dar ekranda okunur kalsın.
    """
    return {"inline_keyboard": [
        kanal_butonlari(kanallar),
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
    if adet < 10:
        tuslar.append([{"text": f"➕ Havuzdan Haber Ekle ({adet}/10)",
                        "callback_data": "havuzdan_ekle"}])
    tuslar.append([{"text": "← Geri", "callback_data": f"geri:{adet}"}])
    return {"inline_keyboard": tuslar}


def slayt_islem_menusu(sira: int, adet: int) -> dict:
    """
    Seçilen slayt için yapılabilecekler (düzenleme + sıralama).
    """
    tuslar = []
    # Sıralama butonları (Carousel turlarında)
    if adet > 1:
        if sira > 1:
            tuslar.append([{"text": f"🔝 {sira}. slaytı EN BAŞA al (Manşet)",
                            "callback_data": f"slayt_basa:{sira}"}])
        sira_satiri = []
        if sira > 1:
            sira_satiri.append({"text": "⬆️ 1 Yukarı Taşı",
                                "callback_data": f"slayt_yukari:{sira}"})
        if sira < adet:
            sira_satiri.append({"text": "⬇️ 1 Aşağı Taşı",
                                "callback_data": f"slayt_asagi:{sira}"})
        if sira_satiri:
            tuslar.append(sira_satiri)

    tuslar += [
        [{"text": f"🔀 {sira}. slayt: başka fotoğraf (bedava)",
          "callback_data": f"slayt_foto:{sira}"}],
        [{"text": f"🎨 {sira}. slayt: AI ile üret (~$0.04)",
          "callback_data": f"slayt_ai:{sira}"}],
        [{"text": f"✏️ {sira}. slaytın metnini yenile",
          "callback_data": f"slayt_metin:{sira}"}],
        [{"text": f"✍️ {sira}. slaytın başlığını elle yaz",
          "callback_data": f"slayt_elle:{sira}"}],
        [{"text": f"🧹 {sira}. slayt: Sansürü Kaldır (* sil)",
          "callback_data": f"sansur_kaldir:{sira}"},
         {"text": f"🛡️ {sira}. slayt: Sansürle",
          "callback_data": f"sansur_uygula:{sira}"}],
        [{"text": f"➕ {sira}. slayt: Metni Uzat",
          "callback_data": f"metin_uzat:{sira}"},
         {"text": f"➖ {sira}. slayt: Metni Kısalt",
          "callback_data": f"metin_kisalt:{sira}"}],
        [{"text": f"📄 {sira}. slaytın kaynak metnini göster",
          "callback_data": f"slayt_kaynak:{sira}"}],
        [{"text": f"🔄 {sira}. slaytın HABERİNİ değiştir",
          "callback_data": f"haber_degistir:{sira}"}],
        [{"text": f"🗑 {sira}. slaytı çıkar",
          "callback_data": f"slayt_sil:{sira}"},
         {"text": f"🗑️ Haberi Çöpe At",
          "callback_data": f"cope_at_tekil:{sira}"}],
        [{"text": "← Geri", "callback_data": f"slayt_menu:{adet}"}],
    ]
    return {"inline_keyboard": tuslar}


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

    Önce URL ile dener; eğer Telegram WEBPAGE_CURL_FAILED verirse
    görselleri indirip doğrudan multipart/form-data ile yükler.
    """
    import io
    medya = []
    for sira, url in enumerate(gorsel_urlleri, start=1):
        oge = {"type": "photo", "media": url}
        if basliklar and sira <= len(basliklar):
            oge["caption"] = f"{sira}. {basliklar[sira - 1]}"[:1024]
        else:
            oge["caption"] = f"{sira}."
        medya.append(oge)

    try:
        sonuc = _istek("sendMediaGroup", chat_id=_sohbet_id(), media=medya)
        return [m["message_id"] for m in sonuc]
    except Exception as e:
        if "WEBPAGE_CURL_FAILED" in str(e) or "failed to send message" in str(e):
            log.warning("Telegram URL'den indiremedi, doğrudan dosya yüklemesine geçiliyor: %s", e)
            files = {}
            multipart_medya = []
            for sira, url in enumerate(gorsel_urlleri, start=1):
                attach_name = f"foto_{sira}"
                try:
                    r = requests.get(url, timeout=15)
                    files[attach_name] = (f"foto_{sira}.jpg", io.BytesIO(r.content), "image/jpeg")
                    oge = {"type": "photo", "media": f"attach://{attach_name}"}
                    if basliklar and sira <= len(basliklar):
                        oge["caption"] = f"{sira}. {basliklar[sira - 1]}"[:1024]
                    else:
                        oge["caption"] = f"{sira}."
                    multipart_medya.append(oge)
                except Exception as dl_err:
                    log.warning("görsel indirilemedi: %s", dl_err)

            if files and len(multipart_medya) == len(gorsel_urlleri):
                url_api = TABAN.format(jeton=_jeton(), metot="sendMediaGroup")
                data = {"chat_id": _sohbet_id(), "media": json.dumps(multipart_medya)}
                res = requests.post(url_api, data=data, files=files, timeout=60)
                res_json = res.json() if res.content else {}
                if res_json.get("ok"):
                    log.info("Telegram albümü doğrudan multipart ile başarıyla gönderildi.")
                    return [m["message_id"] for m in res_json["result"]]
        raise


def yerel_albom_gonder(
    dosya_yollari: list[Path | str],
    basliklar: list[str] | None = None,
) -> list[int]:
    """
    Yerel dosya yollarını (örneğin 9:16 Reels görsellerini) doğrudan albüm olarak Telegram'a gönderir.
    """
    if not dosya_yollari:
        return []

    files = {}
    media = []
    file_handles = []

    try:
        for idx, yol in enumerate(dosya_yollari):
            p = Path(yol)
            if not p.exists():
                continue
            attach_name = f"photo_{idx}"
            fh = open(p, "rb")
            file_handles.append(fh)
            files[attach_name] = (p.name, fh, "image/jpeg")

            cap = ""
            if basliklar and idx < len(basliklar):
                cap = f"{idx + 1}. {basliklar[idx]}"[:1024]
            elif idx == 0:
                cap = "📱 9:16 Dikey Format (Reels / Story)"

            media.append({
                "type": "photo",
                "media": f"attach://{attach_name}",
                "caption": cap,
            })

        if not media:
            return []

        url_api = TABAN.format(jeton=_jeton(), metot="sendMediaGroup")
        data = {"chat_id": _sohbet_id(), "media": json.dumps(media)}
        res = requests.post(url_api, data=data, files=files, timeout=90)
        veri = res.json() if res.content else {}
        if veri.get("ok"):
            log.info("Yerel 9:16 albüm Telegram'a başarıyla iletildi.")
            return [m["message_id"] for m in veri["result"]]
        else:
            log.warning("Yerel albüm gönderilemedi: %s", veri)
            return []
    finally:
        for fh in file_handles:
            try:
                fh.close()
            except Exception:
                pass


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
               butonlar: dict | None = None,
               ek_dugmeler: list | None = None) -> None:
    """
    Onay mesajını sonuçla günceller ve butonları kaldırır.

    Butonların kaldırılması önemli: kalırsa biri yayından sonra tekrar
    basar ve ikinci kez yayınlamaya çalışırız.

    `bildir=True` sonucu AYRICA yeni bir mesaj olarak gönderir.

    `butonlar` verilirse klavye BOŞALTILMAZ, verilen düzen konur —
    zamanlanmış yayında "planı iptal et" düğmesinin kalması gerekiyor.

    `ek_dugmeler` yalnızca `bildir=True` ile gönderilen YENİ mesaja
    ekleniyor. Yarım kalan Threads zinciri için: kullanıcı `/tamamla`
    komutunu ezberlemek zorunda kalmasın.

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
            tuslar = [[{"text": "🗑 Bu yayını kaldır",
                        "callback_data": f"kaldir:{message_id}"}]]
            if ek_dugmeler:
                tuslar = list(ek_dugmeler) + tuslar
            mesaj_gonder(metin, butonlar=tuslar)
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


def hata_bildir(baslik: str, ayrinti: str = "", nerede: str = "", mesaj_id: int | str = "") -> None:
    """
    Bir hata veya problem oluştuğunda akıllı hata teşhis motoruna iletir,
    hatayı kalıcı kaydeder ve Telegram'a çözüm butonlarıyla bildirir.
    """
    try:
        from . import hata_bildir as hb
        hb.bildir(baslik, ayrinti, nerede=nerede or "Sistem", mesaj_id=mesaj_id)
    except Exception as e:
        log.error("hata bildirimi gönderilemedi: %s", e)
        try:
            mesaj_gonder(f"⚠️ {baslik}\n\n{ayrinti[:1000]}")
        except Exception:
            pass


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


def video_gonder(
    video_yolu: Path | str,
    aciklama: str = "",
    butonlar: list | None = None,
) -> int:
    """
    Üretilen MP4 Reels/video dosyasını Telegram grubuna gönderir.
    """
    p = Path(video_yolu)
    if not p.exists():
        raise FileNotFoundError(f"Video dosyası bulunamadı: {video_yolu}")

    url = TABAN.format(jeton=_jeton(), metot="sendVideo")
    data = {"chat_id": _sohbet_id()}
    if aciklama:
        data["caption"] = aciklama[:1024]
    if butonlar:
        data["reply_markup"] = json.dumps({"inline_keyboard": butonlar})

    with open(p, "rb") as f:
        files = {"video": f}
        cevap = requests.post(url, data=data, files=files, timeout=180)

    veri = cevap.json() if cevap.content else {}
    if not veri.get("ok"):
        raise RuntimeError(f"Telegram video gönderme hatası: {veri.get('description', cevap.text[:200])}")
    return veri["result"]["message_id"]

