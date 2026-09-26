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

        aciklama = (veri.get("description") or "").lower()

        # HTML etiket parse hatası: 400 gelir ama parse_mode kaldırılarak düz metinle anında kurtarılır
        if cevap.status_code == 400 and ("can't parse entities" in aciklama or "entity" in aciklama):
            if parametreler.get("parse_mode"):
                log.warning(
                    "Telegram HTML ayrıştırma hatası (%s), parse_mode kaldırılarak düz metinle deneniyor: %s",
                    metot, veri.get("description", "")
                )
                parametreler.pop("parse_mode", None)
                if "text" in parametreler and isinstance(parametreler["text"], str):
                    parametreler["text"] = html.unescape(re.sub(r"<[^>]+>", "", parametreler["text"]))
                if "caption" in parametreler and isinstance(parametreler["caption"], str):
                    parametreler["caption"] = html.unescape(re.sub(r"<[^>]+>", "", parametreler["caption"]))
                continue

            if "media" in parametreler and isinstance(parametreler["media"], list):
                degisti = False
                for m in parametreler["media"]:
                    if isinstance(m, dict) and m.pop("parse_mode", None):
                        if "caption" in m and isinstance(m["caption"], str):
                            m["caption"] = html.unescape(re.sub(r"<[^>]+>", "", m["caption"]))
                        degisti = True
                if degisti:
                    log.warning(
                        "Telegram sendMediaGroup HTML ayrıştırma hatası, parse_mode kaldırılarak deneniyor"
                    )
                    continue

        # Medya indirme hatası: 400 geliyor ama GEÇİCİ (bkz. GECICI_MESAJLAR)
        if any(k in aciklama for k in GECICI_MESAJLAR):
            if metot == "sendMediaGroup" and deneme >= 1:
                # sendMediaGroup için WEBPAGE_CURL_FAILED durumunda slaytlari_gonder
                # zaten doğrudan multipart dosya yükleme yedeğine sahip. 50 saniye boşuna
                # beklemek yerine derhal yerel dosya/multipart fallback'ine geçiyoruz.
                break
            bekleme = 3 if metot == "sendMediaGroup" else MEDYA_BEKLEME_SANIYE
            log.warning("Telegram medyayı indiremedi, %s sn sonra tekrar (%s/%s): %s",
                        bekleme, deneme, MEDYA_AZAMI_DENEME,
                        veri.get("description", "")[:80])
            time.sleep(bekleme)
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

def kanal_butonlari(kanallar: dict | None = None) -> list[list[dict]]:
    """
    Yayın kanallarını açıp kapamak için 2 satırlı kompakt toggle butonları üretir.
    Satır 1: [✅ IG] [⬜ Reels] [✅ Story] [✅ Threads]
    Satır 2: [✅ FB] [✅ X] [✅ YT] [✅ TT] [⬜ TT Video]
    """
    if kanallar is None:
        kanallar = {
            "ig": True, "reels": False, "story": True, "threads": True,
            "facebook": True, "twitter": True, "youtube": True, "tiktok": True,
            "tiktok_video": False,
        }

    def _simge(k):
        varsayilan_kapali = k in ("reels", "tiktok_video")
        return "✅" if kanallar.get(k, False if varsayilan_kapali else True) else "⬜"

    return [
        [
            {"text": f"{_simge('ig')} IG", "callback_data": "kanal:ig"},
            {"text": f"{_simge('reels')} Reels", "callback_data": "kanal:reels"},
            {"text": f"{_simge('story')} Story", "callback_data": "kanal:story"},
            {"text": f"{_simge('threads')} Threads", "callback_data": "kanal:threads"},
        ],
        [
            {"text": f"{_simge('facebook')} FB", "callback_data": "kanal:facebook"},
            {"text": f"{_simge('twitter')} X", "callback_data": "kanal:twitter"},
            {"text": f"{_simge('youtube')} YT", "callback_data": "kanal:youtube"},
            {"text": f"{_simge('tiktok')} TT", "callback_data": "kanal:tiktok"},
            {"text": f"{_simge('tiktok_video')} TT Video", "callback_data": "kanal:tiktok_video"},
        ],
    ]


def ana_menu(adet: int, kanallar: dict | None = None) -> dict:
    """Onay mesajının ilk buton seti."""
    return {"inline_keyboard": [
        *kanal_butonlari(kanallar),
        [{"text": "✅ Yayınla", "callback_data": f"yayin_menu:{adet}"},
         {"text": "🎙️ Sesli Yayınla", "callback_data": f"ses_menu:{adet}"}],
        [{"text": "📲 Manuel Paylaşım Paketi", "callback_data": "manuel_paket"}],
        [{"text": "🔄 Başka Fotoğraf Bul", "callback_data": f"foto_menu:{adet}"},
         {"text": "✍️ Metinleri Yenile", "callback_data": f"metin_menu:{adet}"}],
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


def foto_menusu(adet: int, kanallar: dict | None = None) -> dict:
    """Fotoğraf değiştirme alt menüsü."""
    return {"inline_keyboard": [
        *kanal_butonlari(kanallar),
        [{"text": "📸 Gerçek Fotoğraf Ara", "callback_data": "foto_gercek"},
         {"text": "🖼️ Stok Fotoğraf (Pexels)", "callback_data": "foto_stok"}],
        [{"text": "🎨 Yapay Zeka ile Üret", "callback_data": "foto_ai"}],
        [{"text": "← Ana Menü", "callback_data": f"foto_geri:{adet}"}],
    ]}


def metin_menusu(adet: int, kanallar: dict | None = None) -> dict:
    """Metin yenileme alt menüsü."""
    return {"inline_keyboard": [
        *kanal_butonlari(kanallar),
        [{"text": "✂️ Haberi Daha da Özetle", "callback_data": "metin_ozetle"},
         {"text": "📖 Haberi Detaylandır", "callback_data": "metin_detaylandir"}],
        [{"text": "🔍 Başka Kaynaktan Araştır", "callback_data": "metin_kaynak_arastir"}],
        [{"text": "🔄 Standart Yeniden Yaz", "callback_data": "metin_yenile"}],
        [{"text": "← Ana Menü", "callback_data": f"metin_geri:{adet}"}],
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
        satirlar.append(f"<b>{i}. {baslik}</b>")
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
        satirlar.append(f"<b>{i}. {baslik}</b>")
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
        *kanal_butonlari(kanallar),
        [{"text": "▶️ Şimdi", "callback_data": "yayinla"},
         {"text": "30 dk", "callback_data": "yayinla_sonra:30"}],
        [{"text": "1 saat", "callback_data": "yayinla_sonra:60"},
         {"text": "2 saat", "callback_data": "yayinla_sonra:120"}],
        [{"text": "3 saat", "callback_data": "yayinla_sonra:180"},
         {"text": "4 saat", "callback_data": "yayinla_sonra:240"}],
        [{"text": "← Geri", "callback_data": f"yayin_geri:{adet}"}],
    ]}


def ses_menusu(adet: int, kanallar: dict | None = None) -> dict:
    """
    "🎙️ Sesli Yayınla" alt menüsü: fon müzikli mi, müziksiz mi (2026-09-26, postedm'den).

    Düz "✅ Yayınla" eskisi gibi seslendirmesiz. Seçilen kip Worker'da kanal listesine
    ses_muzikli / ses_muziksiz olarak eklenir, komut yine "yayinla" / "yayinla_sonra:N".
    ⚠️ worker/index.js › sesMenusu ile BİREBİR AYNI olmalı.
    """
    return {"inline_keyboard": [
        *kanal_butonlari(kanallar),
        [{"text": "🎵 Fon müzikli", "callback_data": f"ses_zaman:muzikli:{adet}"},
         {"text": "🔇 Fon müziksiz", "callback_data": f"ses_zaman:muziksiz:{adet}"}],
        [{"text": "← Geri", "callback_data": f"yayin_geri:{adet}"}],
    ]}


def sesli_yayin_zamani_menusu(muzikli: bool, adet: int, kanallar: dict | None = None) -> dict:
    """
    Sesli yayının zaman menüsü: yayin_zamani_menusu ile aynı yapı.

    ⚠️ Kip ve süre yer tutucuyla DEĞİL, açıkça yazılı: sözleşme testi
    callback_data'daki yer tutucuları "1" ile doldurup Worker'a soruyor;
    "yayinla_ses_sonra:muzikli:1" gibi bir örnek "ölü düğme" sayılırdı.
    """
    if muzikli:
        simdi = {"text": "▶️ Şimdi 🎵", "callback_data": "yayinla_ses:muzikli"}
        sonra = [{"text": "30 dk", "callback_data": "yayinla_ses_sonra:muzikli:30"},
                 {"text": "1 saat", "callback_data": "yayinla_ses_sonra:muzikli:60"},
                 {"text": "2 saat", "callback_data": "yayinla_ses_sonra:muzikli:120"},
                 {"text": "3 saat", "callback_data": "yayinla_ses_sonra:muzikli:180"},
                 {"text": "4 saat", "callback_data": "yayinla_ses_sonra:muzikli:240"}]
    else:
        simdi = {"text": "▶️ Şimdi 🔇", "callback_data": "yayinla_ses:muziksiz"}
        sonra = [{"text": "30 dk", "callback_data": "yayinla_ses_sonra:muziksiz:30"},
                 {"text": "1 saat", "callback_data": "yayinla_ses_sonra:muziksiz:60"},
                 {"text": "2 saat", "callback_data": "yayinla_ses_sonra:muziksiz:120"},
                 {"text": "3 saat", "callback_data": "yayinla_ses_sonra:muziksiz:180"},
                 {"text": "4 saat", "callback_data": "yayinla_ses_sonra:muziksiz:240"}]
    return {"inline_keyboard": [
        *kanal_butonlari(kanallar),
        [simdi, sonra[0]],
        [sonra[1], sonra[2]],
        [sonra[3], sonra[4]],
        [{"text": "← Geri", "callback_data": f"ses_menu:{adet}"}],
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
        [{"text": f"🔥 {sira}. slayt: Başlığı Daha Dikkat Çekici Yap",
          "callback_data": f"slayt_carpici:{sira}"}],
        [{"text": f"✏️ {sira}. slayt: Metni & Başlığı Yeniden Yaz",
          "callback_data": f"slayt_metin:{sira}"}],
        [{"text": f"✍️ {sira}. slayt: Başlığı Elle Düzenle (Reply)",
          "callback_data": f"slayt_elle:{sira}"}],
        [{"text": f"🔀 {sira}. slayt: Başka Fotoğraf Seç (Bedava)",
          "callback_data": f"slayt_foto:{sira}"}],
        [{"text": f"🎨 {sira}. slayt: AI ile Görsel Çiz (~$0.04)",
          "callback_data": f"slayt_ai:{sira}"}],
        [{"text": f"➕ {sira}. slayt: Metni Uzat",
          "callback_data": f"metin_uzat:{sira}"},
         {"text": f"➖ {sira}. slayt: Metni Kısalt",
          "callback_data": f"metin_kisalt:{sira}"}],
        [{"text": f"🧹 {sira}. slayt: Sansürü Kaldır (* sil)",
          "callback_data": f"sansur_kaldir:{sira}"},
         {"text": f"🛡️ {sira}. slayt: Sansürle",
          "callback_data": f"sansur_uygula:{sira}"}],
        [{"text": f"📄 {sira}. slaytın kaynak metnini göster",
          "callback_data": f"slayt_kaynak:{sira}"}],
        [{"text": f"🔄 Havuzdan Farklı Bir Habere Geç",
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
    gorsel_urlleri: list[str],
    basliklar: list[str] | None = None,
    yerel_yollar: list[Path | str] | None = None,
) -> list[int]:
    """
    Slaytları albüm olarak gönderir. Mesaj id'lerini döner.

    Önce URL ile dener; eğer Telegram WEBPAGE_CURL_FAILED verirse
    görselleri yerel diskten veya gerekirse indirerek doğrudan
    multipart/form-data ile yükler.
    """
    if not gorsel_urlleri:
        return []
    import io
    from . import upload_image

    medya = []
    for sira, url in enumerate(gorsel_urlleri, start=1):
        oge = {"type": "photo", "media": url}
        if basliklar and sira <= len(basliklar):
            temiz_b = html.escape(str(basliklar[sira - 1]).strip())
            oge["caption"] = f"<b>{sira}. {temiz_b}</b>"[:1024]
        else:
            oge["caption"] = f"<b>{sira}.</b>"
        oge["parse_mode"] = "HTML"
        medya.append(oge)

    try:
        sonuc = _istek("sendMediaGroup", chat_id=_sohbet_id(), media=medya)
        return [m["message_id"] for m in sonuc]
    except Exception as e:
        if "WEBPAGE_CURL_FAILED" in str(e) or "failed to send message" in str(e):
            log.warning("Telegram URL'den indiremedi, doğrudan dosya yüklemesine geçiliyor: %s", e)
            files = {}
            file_handles = []
            multipart_medya = []
            try:
                for sira, url in enumerate(gorsel_urlleri, start=1):
                    attach_name = f"foto_{sira}"
                    icerik_stream = None
                    dosya_adi = f"foto_{sira}.jpg"

                    # 1. Öncelik: Varsa yerel dosyayı doğrudan kullan (sıfır ağ gecikmesi, sıfır indirme hatası)
                    yerel = None
                    if yerel_yollar and (sira - 1) < len(yerel_yollar):
                        p_cand = Path(yerel_yollar[sira - 1])
                        if p_cand.exists():
                            yerel = p_cand
                    if not yerel:
                        try:
                            yerel = upload_image.yerel_karsiligi(url)
                        except Exception:
                            yerel = None
                    if not yerel:
                        temiz_ad = Path(str(url).split("?")[0]).name
                        if temiz_ad and (Path("output") / temiz_ad).exists():
                            yerel = Path("output") / temiz_ad

                    if yerel and Path(yerel).exists():
                        dosya_adi = Path(yerel).name
                        fh = open(yerel, "rb")
                        file_handles.append(fh)
                        icerik_stream = fh
                        log.info("Telegram albümü için yerel dosya kullanılıyor: %s", yerel)
                    else:
                        # 2. Öncelik: Yerel dosya bulunamazsa URL'den indir (User-Agent + 25s timeout + 2 deneme)
                        tarayici_headers = {
                            "User-Agent": (
                                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                            )
                        }
                        for deneme_dl in range(2):
                            try:
                                r = requests.get(url, headers=tarayici_headers, timeout=25)
                                if r.status_code == 200 and r.content:
                                    icerik_stream = io.BytesIO(r.content)
                                    break
                            except Exception as dl_err:
                                log.warning("görsel indirme denemesi %d başarısız (%s): %s", deneme_dl + 1, url, dl_err)
                                time.sleep(2)

                    if icerik_stream:
                        files[attach_name] = (dosya_adi, icerik_stream, "image/jpeg")
                        oge = {"type": "photo", "media": f"attach://{attach_name}"}
                        if basliklar and sira <= len(basliklar):
                            temiz_b = html.escape(str(basliklar[sira - 1]).strip())
                            oge["caption"] = f"<b>{sira}. {temiz_b}</b>"[:1024]
                        else:
                            oge["caption"] = f"<b>{sira}.</b>"
                        oge["parse_mode"] = "HTML"
                        multipart_medya.append(oge)
                    else:
                        log.warning("görsel temin edilemedi: %s", url)

                if files and len(multipart_medya) == len(gorsel_urlleri):
                    url_api = TABAN.format(jeton=_jeton(), metot="sendMediaGroup")
                    data = {"chat_id": _sohbet_id(), "media": json.dumps(multipart_medya)}
                    res = requests.post(url_api, data=data, files=files, timeout=90)
                    res_json = res.json() if res.content else {}
                    if res_json.get("ok"):
                        log.info("Telegram albümü doğrudan multipart ile başarıyla gönderildi.")
                        return [m["message_id"] for m in res_json["result"]]
                    else:
                        log.warning("Telegram multipart yükleme başarısız: %s", res_json)
            finally:
                for fh in file_handles:
                    try:
                        fh.close()
                    except Exception:
                        pass
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


# Türkçe yazım uyumluluğu için alias
yerel_album_gonder = yerel_albom_gonder


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
        satirlar.append(f"{sira:>2} {simge} <b>{html.escape(baslik[:58])}</b>")

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


def mesaj_sil(mid: int) -> bool:
    """Tek bir mesajı siler."""
    return bool(mesajlari_sil([mid]))


def onay_iste(caption: str, slayt_adedi: int, uyari: str = "",
              ozet: str = "") -> int:
    """
    Özeti, kopyalanabilir caption'ı ve onay butonlarını gönderir. message_id döner.

    Bu id `telegram_message_id` olarak saklanmalı — sonuç yazılırken
    düzenlenecek mesaj bu.

    Sıralama bilinçli: önce denetim uyarısı (varsa hemen görülmeli),
    sonra özet tablo (karar burada veriliyor), en sonda kopyalanabilir caption
    (Instagram'a gidecek metin, tek dokunuşla kopyalanır).
    """
    import html as html_lib

    parcalar = []
    if uyari:
        parcalar.append(f"⚠️ <b>UYARI:</b>\n{html_lib.escape(uyari.strip())}")
    if ozet:
        parcalar.append(ozet.strip())

    temiz_caption = html_lib.escape(caption.strip())
    parcalar.append(
        "📝 <b>Açıklama Metni (Kopyalamak için dokunun):</b>\n"
        f"<pre>{temiz_caption}</pre>"
    )

    metin = "\n\n".join(parcalar)
    # sendMessage sınırı 4096; caption ~1100 olduğu için pay bol.
    sonuc = _istek(
        "sendMessage",
        chat_id=_sohbet_id(),
        text=metin[:4096],
        parse_mode="HTML",
        reply_markup=ana_menu(slayt_adedi),
        disable_web_page_preview=True,
    )
    return sonuc["message_id"]


def haftalik_bulten_onay_iste(
    tur_bilgi: dict,
    piyasa_verileri: dict,
    onemli_haberler: list,
    ayarlar: dict,
) -> int:
    """
    Hafta sonu kapanış bilançosu için Telegram albümünü ve onay kartını gönderir.
    """
    slayt_urlleri = tur_bilgi.get("slayt_urlleri", [])
    slayt_yollari = tur_bilgi.get("slayt_yollari", [])

    if slayt_urlleri:
        try:
            slaytlari_gonder(slayt_urlleri)
        except Exception:
            if slayt_yollari:
                yerel_albom_gonder(slayt_yollari)

    caption_metin = tur_bilgi.get("caption", "")
    metin = (
        "📊 <b>HAFTANIN BİLANÇOSU & KAPANIŞ BÜLTENİ HAZIR!</b>\n\n"
        f"📅 <b>Tarih:</b> {piyasa_verileri.get('tarih', '')}\n"
        f"🗞️ <b>Haftalık Manşet Sayısı:</b> {len(onemli_haberler)} seçme haber\n\n"
        f"📝 <b>Açıklama Metni (Kopyalamak için dokunun):</b>\n<pre>{caption_metin}</pre>"
    )

    mesaj = _istek(
        "sendMessage",
        chat_id=_sohbet_id(),
        text=metin,
        parse_mode="HTML",
        reply_markup=ana_menu(len(slayt_urlleri)),
    )
    return mesaj["message_id"]


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
               ek_dugmeler: list | None = None,
               html: bool = False) -> None:
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
    ek = {"parse_mode": "HTML"} if html else {}
    _istek("editMessageText", chat_id=_sohbet_id(), message_id=message_id,
           text=metin[:4096],
           reply_markup=butonlar or {"inline_keyboard": []},
           disable_web_page_preview=True,
           **ek)

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
            mesaj_gonder(metin, butonlar=tuslar, html=html)
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


def durum_guncelle(message_id: int, baslik: str, adim: int, toplam_adim: int = 4, detay: str = "") -> None:
    """
    Uzun süren işlemlerde (özel haber, dosya, araştırma, görsel arama)
    kullanıcıya Telegram grubunu kirletmeden canlı ilerleme çubuğu (progress bar) sunar.
    """
    if not message_id:
        return
    if toplam_adim < 1:
        toplam_adim = 1
    adim = max(1, min(adim, toplam_adim))
    dolu = "▰" * adim
    bos = "▱" * max(0, toplam_adim - adim)
    yuzde = int((adim / toplam_adim) * 100)

    satirlar = [
        f"⏳ <b>{html.escape(baslik)}</b>",
        f"<code>[{dolu}{bos}] %{yuzde} ({adim}/{toplam_adim})</code>",
    ]
    if detay:
        satirlar.append(f"<i>{html.escape(detay)}</i>")

    try:
        _istek(
            "editMessageText",
            chat_id=_sohbet_id(),
            message_id=message_id,
            text="\n\n".join(satirlar),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception as e:
        if "not modified" not in str(e).lower():
            log.debug("durum_guncelle hatası (%s): %s", message_id, e)


KANAL_ETIKETLERI = {
    "tiktok": "TikTok (@dailybrief.co)",
    "youtube": "YouTube Shorts",
    "facebook_reels": "Facebook Reels",
    "instagram": "Instagram Akış (4:5)",
    "instagram_story": "Instagram Story",
    "facebook": "Facebook Sayfası",
    "threads": "Threads (@dailybrief.co)",
    "twitter": "X (Twitter)",
}


def yayin_durum_metni_olustur(
    baslik: str,
    adim: int,
    toplam_adim: int,
    durum_haritasi: dict[str, str],
    baslangic_ts: float = 0.0,
    is_telafi: bool = False,
) -> str:
    """
    Canlı paralel yayın ilerleme metnini ve platform durum listesini oluşturur.
    EzanPlusBot ve Daily Brief ortak parite standardında:
    Her kanalın durumunu (⏳ Yükleniyor... / ✅ Yayında / ❌ Hata / ⏱️ Sırada) ve
    canlı ilerleme çubuğunu ([▰▰▱▱] %50) gösterir.
    """
    toplam = max(1, toplam_adim)
    ad = max(0, min(adim, toplam))
    dolu = "▰" * ad
    bos = "▱" * (toplam - ad)
    yuzde = int((ad / toplam) * 100)
    bar = f"<code>[{dolu}{bos}] %{yuzde} ({ad}/{toplam})</code>"

    tamamlandi = (ad == toplam and all(v not in ("⏱️ Sırada", "⏳ Yükleniyor...") for v in durum_haritasi.values()))

    if is_telafi:
        baslik_satiri = "⏳ <b>TELAFİ DAĞITIMI SÜRÜYOR...</b>"
    elif tamamlandi:
        baslik_satiri = "✅ <b>TÜM PLATFORMLARA AKTARIM TAMAMLANDI!</b>"
    else:
        baslik_satiri = "⏳ <b>YAYIN DAĞITIMI SÜRÜYOR (Paralel Motor)...</b>"

    satirlar = [baslik_satiri]
    if baslik:
        satirlar.append(f"📌 <b>{html.escape(baslik[:100])}</b>")
    satirlar.append("")
    satirlar.append(bar)
    satirlar.append("")
    satirlar.append("📱 <b>Platform Durumları:</b>")

    for k, durum in durum_haritasi.items():
        isim = KANAL_ETIKETLERI.get(k, k.capitalize())
        satirlar.append(f"• <b>{isim}:</b> {durum}")

    if baslangic_ts > 0:
        gecen = time.time() - baslangic_ts
        if tamamlandi:
            satirlar.append(f"\n⏱️ <i>Toplam Dağıtım Süresi: {gecen:.1f} sn • Rapor hazırlanıyor...</i>")
        else:
            satirlar.append(f"\n⏱️ <i>Geçen Süre: {gecen:.1f} sn</i>")

    return "\n".join(satirlar)


def canli_yayin_durumu_guncelle(
    message_id: int,
    baslik: str,
    adim: int,
    toplam_adim: int,
    durum_haritasi: dict[str, str],
    baslangic_ts: float = 0.0,
    is_telafi: bool = False,
) -> None:
    """
    Paralel dağıtım sırasında onay mesajını anlık platform durumları ve
    ilerleme çubuğu ile canlı olarak günceller.
    """
    if not message_id:
        return
    metin = yayin_durum_metni_olustur(
        baslik=baslik,
        adim=adim,
        toplam_adim=toplam_adim,
        durum_haritasi=durum_haritasi,
        baslangic_ts=baslangic_ts,
        is_telafi=is_telafi,
    )
    try:
        _istek(
            "editMessageText",
            chat_id=_sohbet_id(),
            message_id=message_id,
            text=metin,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception as e:
        if "not modified" not in str(e).lower():
            log.debug("canli_yayin_durumu_guncelle hatası (%s): %s", message_id, e)



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


def _kacir_url(url: str) -> str:
    """URL'yi HTML href niteliği için güvenli hale getirir."""
    return html.escape(url or "", quote=True)


def _spot_temizle(metin: str, azami: int = 120) -> str:
    """
    Haber özetini/spotunu 1-2 cümlelik ferah bir Telegram satırına dönüştürür.
    HTML etiketlerini temizler ve fazla uzamadan cümle/kelime sınırından keser.
    """
    if not metin:
        return ""
    temiz = re.sub(r"<[^>]+>", " ", metin)
    temiz = " ".join(temiz.split()).strip()
    if not temiz:
        return ""
    m = re.search(r"^(.*?[.!?])(?:\s+[A-ZÇĞİÖŞÜ0-9]|$)", temiz)
    if m and 25 <= len(m.group(1)) <= azami:
        return m.group(1)
    if len(temiz) > azami:
        kesilmis = temiz[:azami].rsplit(" ", 1)[0]
        return f"{kesilmis}…"
    return temiz


def oneri_gonder(adaylar: list[dict], azami: int = 5,
                 baslik_metni: str = "📰 <b>Günün Öne Çıkan Haber Adayları</b>") -> int:
    """
    Kullanıcıya saatlik tekil post için seçebileceği 5 taze başlığı önerir.
    Başlıklar tıklanabilir orijinal haber linkiyle sunulur; altına 1 cümlelik
    spot açıklama eklenerek tek bakışta anlaşılması sağlanır.
    `[1️⃣] [2️⃣] [3️⃣] [4️⃣] [5️⃣]` butonları ile çoklu seçim yapılır.
    """
    if not adaylar:
        return 0

    rakamlar = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣"]
    gosterilecek = adaylar[:min(len(adaylar), len(rakamlar), azami)]

    satirlar = [baslik_metni, ""]
    secim_butonlari = []
    for i, a in enumerate(gosterilecek):
        r_simge = rakamlar[i]
        puan_str = f"[{a['puan']}] " if a.get("puan") is not None else ""
        baslik = _kacir(a["baslik"])
        link = (a.get("link") or "").strip()
        if link and link.startswith("http"):
            baslik_satiri = f"{r_simge} <a href=\"{_kacir_url(link)}\"><b>{puan_str}{baslik}</b></a>"
        else:
            baslik_satiri = f"{r_simge} <b>{puan_str}{baslik}</b>"
        satirlar.append(baslik_satiri)

        spot = _spot_temizle(a.get("ozet") or "")
        baslik_ham = a.get("baslik") or ""
        if spot and spot.lower() not in baslik_ham.lower() and baslik_ham.lower() not in spot.lower():
            satirlar.append(f"     💬 <i>{_kacir(spot)}</i>")

        # ⚠️ SİNYAL ROZETLERİ (18 Eyl 2026). Kullanıcı sordu: "Tera
        # Holding ve Katılımevim haberleri neden hiç önerilmedi, yoksa
        # önerildi de ben mi başlıklardan anlamadım?" — Tera GERÇEKTEN
        # önerilmişti (`oneri_gonderildi=1`) ama listede yalnızca önem
        # puanı `[5]` görünüyordu ve başlık ("Tera Portföy'ün iki fonu
        # temerrüde düştü, 6 fonunda ise para 10'uncu iş günü
        # ödenecek") yoğun bir finans cümlesiydi.
        #
        # Yani kusur SEÇİMDE değil SUNUMDAYDI: mesaj "buna neden
        # bakmalıyım" sorusunu cevaplamıyordu. İki sinyal zaten
        # hesaplanıyor ama gösterilmiyordu.
        rozetler = []
        mut = a.get("mutabakat") or 0
        if mut >= 3:
            rozetler.append(f"🔥 {mut} kaynak")
        pay = a.get("paylasim") or 0
        if pay >= 8:
            rozetler.append("💾 paylaşımlık")
        rozet_str = ("  " + " · ".join(rozetler)) if rozetler else ""
        satirlar.append(
            f"     <i>{_kacir(a.get('kaynak', ''))} · {_kacir(a.get('kategori', ''))}</i>"
            f"{rozet_str} · <code>/incele_{a['id']}</code>"
        )
        satirlar.append("")
        secim_butonlari.append({"text": r_simge,
                                "callback_data": f"sec:{a['id']}"})

    satirlar.append("<i>Numaralara basarak haber seçebilir, 🔍 butonlarıyla veya /incele &lt;id&gt; ile detaylarını önizleyebilirsin.</i>")

    incele_butonlari = [
        {"text": f"🔍 {i + 1}", "callback_data": f"incele:{a['id']}"}
        for i, a in enumerate(gosterilecek)
    ]

    menu = [
        secim_butonlari,
        incele_butonlari,
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
        if "<" in aciklama and ">" in aciklama:
            data["parse_mode"] = "HTML"
    if butonlar:
        data["reply_markup"] = json.dumps({"inline_keyboard": butonlar})

    with open(p, "rb") as f:
        files = {"video": f}
        cevap = requests.post(url, data=data, files=files, timeout=180)

    try:
        veri = cevap.json() if cevap.content else {}
    except Exception:
        veri = {}
    if not veri.get("ok"):
        # Eğer HTML etiket parse hatası verirse parse_mode'suz güvenli dene
        if "can't parse entities" in (veri.get("description") or "").lower():
            data.pop("parse_mode", None)
            with open(p, "rb") as f2:
                cevap2 = requests.post(url, data=data, files={"video": f2}, timeout=180)
            try:
                veri2 = cevap2.json() if cevap2.content else {}
            except Exception:
                veri2 = {}
            if veri2.get("ok"):
                return veri2["result"]["message_id"]
        raise RuntimeError(f"Telegram video gönderme hatası: {veri.get('description', cevap.text[:200])}")
    return veri["result"]["message_id"]


def kontrol_merkezi_menusu() -> list[list[dict]]:
    """
    /menu ve /kontrol için interaktif buton paneli döner.
    """
    return [
        [
            {"text": "📊 Ekonomi Turu", "callback_data": "ekonomi_hazirla"},
            {"text": "🌅 Gündem Turu", "callback_data": "tur_hazirla"},
        ],
        [
            {"text": "🚨 Son Dakika Tara", "callback_data": "sondakika"},
            {"text": "📈 Canlı Piyasa", "callback_data": "piyasa_ozet"},
        ],
        [
            {"text": "🏦 Faiz Kartı", "callback_data": "makro:faiz"},
            {"text": "📉 Enflasyon Kartı", "callback_data": "makro:enflasyon"},
        ],
        [
            {"text": "☕ Kahve Bülteni", "callback_data": "bulten"},
            {"text": "📰 Son Postlar", "callback_data": "sonpostlar"},
        ],
        [
            {"text": "🩺 API Sağlık Testi", "callback_data": "saglik_testi"},
            {"text": "🧹 Askıdakileri Sıfırla", "callback_data": "tur_temizle"},
        ],
        [
            {"text": "📊 Durum & Kota", "callback_data": "kota_raporu"},
            {"text": "🔄 RSS Tara (Havuz)", "callback_data": "havuz_guncelle"},
        ],
        [
            {"text": "⏸️ Botu Duraklat", "callback_data": "yonetim"},
            {"text": "⚙️ Ayarlar", "callback_data": "ayar"},
        ],
    ]


def komut_menusu_kaydet() -> bool:
    """
    Telegram komut açılır menüsünü (`setMyCommands`) kaydeder.

    ⚠️ ÜÇ KAPSAMA BİRDEN YAZILIYOR. Telegram komut listesini "scope"lara
    göre çözüyor. `default` teorik olarak hepsini kapsıyor ama
    istemciler grup sohbetinde `all_group_chats` kapsamını ayrıca
    sorguluyor; orası boşken menü geç tazeleniyor. 4 Eyl 2026:
    `default`ta 31 komut yazılıydı, `getMyCommands` doğruluyordu, ama
    kullanıcı grupta "/" yazınca ESKİ menüyü görüyordu.

    ⚠️ TEK KAYNAK YİNE `KOMUT_MENUSU` — üç kapsam da AYNI listeyi
    alıyor. Kapsam eklemek listeyi çoğaltmak değil, aynı listeyi birden
    fazla rafa koymak; "aynı kural iki yerde" tuzağı doğmuyor.
    """
    import json as _json
    from src.komutlar import KOMUT_MENUSU

    kapsamlar = [
        None,                                  # varsayılan
        {"type": "all_private_chats"},
        {"type": "all_group_chats"},
    ]
    basarili = 0
    for kapsam in kapsamlar:
        govde: dict = {"commands": KOMUT_MENUSU}
        if kapsam:
            govde["scope"] = _json.dumps(kapsam)
        try:
            url = TABAN.format(jeton=_jeton(), metot="setMyCommands")
            r = requests.post(url, json=govde, timeout=15)
            res = r.json() if r.content else {}
            if res.get("ok"):
                basarili += 1
            else:
                log.warning("komut menüsü kaydedilemedi (%s): %s",
                            kapsam or "varsayılan", res)
        except Exception as e:                        # noqa: BLE001
            log.warning("setMyCommands isteği başarısız (%s): %s",
                        kapsam or "varsayılan", e)

    log.info("Telegram komut menüsü %d/%d kapsama yazıldı.",
             basarili, len(kapsamlar))
    return basarili == len(kapsamlar)
