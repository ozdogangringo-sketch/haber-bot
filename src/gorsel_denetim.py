"""
gorsel_denetim.py — Yayına çıkacak fotoğrafın İÇİNE bakar.

⚠️ NEDEN GEREKTİ (3 Eyl 2026)

Bu projede görselin haberi anlatıp anlatmadığını denetleyen hiçbir katman
yoktu. Var olan bütün denetimler METNE bakıyordu (`dogrula.py`: sayı, isim,
alıntı, suçlama dili). Görsel tarafında ölçülen ne varsa TEKNİKTİ: piksel
sayısı, netlik, dosya boyutu.

Sonuç ölçüldü:
  * İnternet araması "ABD İran'a saldırdı" haberine Fox News'ten Trump
    portresi getirdi — 1200x675, keskin, temiz. Teknik testin sorduğu
    her soruya "evet" dedi. Kimse "bu fotoğraf bu haberi mi anlatıyor"
    diye sormadı.
  * Metin tabanlı alaka kapısı DENENDİ VE ELENDİ: 6 haberin 6'sı da
    geçti. Sebep döngüsel — `gorsel_konu` "Donald Trump" olduğu için
    arama Trump'ı arıyor, her sonuçta "Trump" geçiyor, kapı kendi
    kendini onaylıyor.

⚠️ İKİNCİ SORUN — GÜNCELLİK. Kullanıcı bildirdi: Vlahovic bu sezon
Beşiktaş'ta ama Commons'taki tek fotoğrafı Juventus formalı. Yani DOĞRU
kişinin YANLIŞ fotoğrafı. `gorsel_baglam` alanı bu bağlamı makaleden
çıkarıyor ("Beşiktaş forması") ama Commons'ta alternatif olmadığı için
sıralama tek başına çözmüyor — ölçüldü, etkisiz kaldı.

İkisini de ancak GÖRSELİN İÇİNE bakan bir denetim çözebilir.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import time

import requests
from PIL import Image

log = logging.getLogger(__name__)

UC_NOKTA = ("https://generativelanguage.googleapis.com/v1beta/"
            "models/{model}:generateContent")

# ⚠️ GÖRSEL KÜÇÜLTÜLEREK GÖNDERİLİYOR. "Bu fotoğrafta ne var" sorusu
# için 512px fazlasıyla yeterli; tam boyut göndermek hem token hem süre
# yakıyor. Kardeş havuzu artık 5877x3306 gibi fotoğraflar getirebiliyor.
AZAMI_KENAR = 512

CEVAP_SEMASI = {
    "type": "object",
    "properties": {
        # Modeli ÖNCE tarif ettirmek, sonra karar verdirmek daha isabetli
        # sonuç veriyor: kararı gerekçesiyle bağlamak zorunda kalıyor.
        "fotografta_ne_var": {"type": "string"},
        "konuyu_gosteriyor_mu": {"type": "boolean"},
        "baglam_uyuyor_mu": {"type": "boolean"},
        "sebep": {"type": "string"},
    },
    "required": ["fotografta_ne_var", "konuyu_gosteriyor_mu",
                 "baglam_uyuyor_mu", "sebep"],
}

ISTEM = """Sen bir haber ajansının FOTO EDİTÖRÜSÜN. Bu fotoğrafın bu haberde \
kullanılıp kullanılamayacağına karar vereceksin.

HABER BAŞLIĞI: {baslik}
FOTOĞRAFTA GÖRÜNMESİ BEKLENEN: {konu}
GEREKLİ GÜNCEL BAĞLAM: {baglam}

Sırayla cevapla:

1) fotografta_ne_var: Fotoğrafta gerçekten NE gördüğünü tarif et. Kişi
   varsa kim olabileceğini, ne giydiğini (forma, üniforma, takım elbise),
   mekânı ve varsa yazı/logo/amblemleri yaz. Tahmin etme, GÖRDÜĞÜNÜ yaz.

2) konuyu_gosteriyor_mu: Fotoğraf "görünmesi beklenen" şeyi gösteriyor mu?
   ⚠️ Temsili fotoğraf da GEÇERLİDİR: haber orman yangınıysa herhangi bir
   orman yangını fotoğrafı "true"dur. Aranan şey olayın BELGESİ değil,
   konuyla İLGİ. Yalnızca fotoğraf tamamen başka bir şeyi gösteriyorsa
   "false" ver.

3) baglam_uyuyor_mu: "Gerekli güncel bağlam" boşsa her zaman true ver.
   Doluysa fotoğraf o bağlama uyuyor mu?
   ⚠️ Örnek: bağlam "Beşiktaş forması" ise ve fotoğraftaki oyuncu
   Juventus forması giyiyorsa false. Bağlam "milli takım forması" ise ve
   sporcu kulüp forması giyiyorsa false. Bağlamla ÇELİŞEN bir şey
   görmüyorsan true ver — emin olamamak çelişki değildir.
   ⚠️ SPORDA BRANŞ VE KATEGORİ UYUMU ZORUNLUDUR: Haber A Milli Takım
   hakkındaysa ve fotoğrafta Ampute takımı (koltuk değnekleri, protez/ampute
   sporcular) ya da Kadın/Genç takımı görünüyorsa (veya tersi) baglam_uyuyor_mu
   ve konuyu_gosteriyor_mu KESİNLİKLE false verilmelidir.

4) sebep: Kararını tek kısa cümleyle açıkla."""


def _anahtarlar() -> list[str]:
    """Denenecek Gemini anahtarları. `generate_text` ile aynı sıra."""
    anahtarlar = []
    for ad in ("GEMINI_API_KEY", "GEMINI_IMAGE_API_KEY"):
        deger = (os.getenv(ad) or "").strip()
        if deger and deger not in anahtarlar:
            anahtarlar.append(deger)
    return anahtarlar


def _kucult(foto: Image.Image) -> bytes:
    """Fotoğrafı JPEG bayta çevirir, uzun kenarı AZAMI_KENAR'a indirir."""
    kopya = foto.convert("RGB")
    if max(kopya.size) > AZAMI_KENAR:
        oran = AZAMI_KENAR / max(kopya.size)
        kopya = kopya.resize(
            (max(1, int(kopya.width * oran)), max(1, int(kopya.height * oran))),
            Image.LANCZOS,
        )
    tampon = io.BytesIO()
    kopya.save(tampon, "JPEG", quality=80)
    return tampon.getvalue()


def gorseli_denetle(foto: Image.Image, baslik: str, konu: str = "",
                    baglam: str = "", ayarlar: dict | None = None) -> dict | None:
    """
    Fotoğrafın habere uygunluğunu Gemini Vision'a sorar.

    Döner: şema sözlüğü, ya da denetim YAPILAMADIYSA None.

    ⚠️ None ile `konuyu_gosteriyor_mu=False` AYNI ŞEY DEĞİL. None
    "soramadık" demek (kota, ağ, anahtar yok) ve çağıran taraf o durumda
    fotoğrafı KULLANMALI — denetim yapılamadı diye postu görselsiz
    bırakmak, denetimden geçmemiş bir fotoğraf basmaktan kötü.
    """
    anahtarlar = _anahtarlar()
    if not anahtarlar:
        log.warning("Gemini anahtarı yok, görsel denetimi atlanıyor")
        return None

    g = (ayarlar or {}).get("gemini", {}) or {}
    model = g.get("model", "gemini-3.6-flash")
    zaman_asimi = g.get("zaman_asimi", 90)

    try:
        veri = base64.b64encode(_kucult(foto)).decode("ascii")
    except Exception as e:                            # noqa: BLE001
        log.warning("görsel denetim için küçültülemedi: %s", e)
        return None

    govde = {
        "contents": [{"parts": [
            {"inline_data": {"mime_type": "image/jpeg", "data": veri}},
            {"text": ISTEM.format(baslik=baslik or "(yok)",
                                  konu=konu or "(belirtilmemiş)",
                                  baglam=baglam or "")},
        ]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": CEVAP_SEMASI,
            # Denetim kararı KARARLI olmalı; aynı fotoğrafa her seferinde
            # farklı cevap veren bir kapı, kapı değildir.
            "temperature": 0.1,
        },
    }

    for anahtar in anahtarlar:
        try:
            cevap = requests.post(
                UC_NOKTA.format(model=model),
                headers={"x-goog-api-key": anahtar},
                json=govde, timeout=zaman_asimi,
            )
        except requests.RequestException as e:
            log.warning("görsel denetimi ağ hatası: %s", e)
            continue
        if cevap.status_code == 200:
            try:
                ham = cevap.json()["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(ham)
            except Exception as e:                    # noqa: BLE001
                log.warning("görsel denetim cevabı çözülemedi: %s", e)
                return None
        if cevap.status_code == 429:
            log.info("görsel denetimi kota doldu, sonraki anahtar deneniyor")
            continue
        if cevap.status_code in (500, 502, 503, 504):
            log.warning("görsel denetimi geçici sunucu hatası (HTTP %s), sonraki anahtar deneniyor", cevap.status_code)
            time.sleep(1)
            continue
        log.warning("görsel denetimi HTTP %s: %s",
                    cevap.status_code, cevap.text[:160])
        return None
    return None
