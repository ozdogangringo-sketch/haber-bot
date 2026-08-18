"""
secim.py — Turda hangi haberlerin yayınlanacağına karar verir.

ÇÖZDÜĞÜ SORUN — tavuk-yumurta:
    Seçim skoru `onem_puani`ye dayanıyor, ama o puanı Gemini üretiyor.
    Yani "hangisi önemli" sorusunu cevaplamak için önce hepsine metin
    ürettirmek gerekiyor. Havuzda 200+ haber var; hepsine metin üretmek
    hem kotayı hem 200 makale indirmeyi göze almak demek — turun süresi
    dakikalardan saate çıkar.

    Çözüm iki aşamalı:
      1. ÖN ELEME (bedava, LLM yok): tazelik + kaynak ağırlığı + kategori
         ile havuzu ~2 kat adaya indir.
      2. ASIL SEÇİM: yalnızca o adaylara metin üretilir, sonra gerçek
         skorla en iyi N tanesi alınır.

    Ön eleme neden güvenli: elediğimiz haberler ya bayat ya düşük ağırlıklı
    kaynaktan. İkisi de zaten asıl skorda dibe düşecek şeyler.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# Aday havuzu, yayınlanacak sayının kaç katı olsun.
# 2.5 seçildi: elenen haber yerine yedek kalsın ama boşuna metin
# üretilmesin. 10 slayt için ~25 adaya metin üretiliyor.
ADAY_KATSAYISI = 2.5


def _yas_saat(haber) -> float:
    """Haberin yayınlanmasından bu yana geçen saat."""
    ham = haber["yayin_tarihi"]
    if not ham:
        return 999.0
    try:
        t = datetime.fromisoformat(ham)
    except ValueError:
        return 999.0
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 3600


def on_eleme(con, ayarlar: dict, kac: int | None = None) -> list:
    """
    Metin üretilecek adayları seçer. LLM ÇAĞIRMAZ, bedavadır.

    Yalnızca elimizde zaten olan bilgiyi kullanıyor: yaş, kaynak ağırlığı,
    kategori. Bayatlama sınırını geçenler hiç aday olmuyor.
    """
    g = ayarlar["gorsel"]
    sinir_saat = ayarlar["genel"]["yayin_yasi_siniri_saat"]
    kac = kac or int(g["slayt_sayisi"] * ADAY_KATSAYISI)

    havuz = list(con.execute("SELECT * FROM haberler WHERE durum = 'yeni'"))

    puanli = []
    for haber in havuz:
        yas = _yas_saat(haber)
        if yas > sinir_saat:
            continue
        # Ön skor: taze ve ağırlıklı kaynak öne çıksın. onem_puani burada
        # YOK — henüz üretilmedi, asıl seçimde devreye girecek.
        puan = (haber["agirlik"] or 1) * 10 - yas
        if haber["kategori"] == "dunya":
            # Türkiye gündemi öncelikli; dünya haberi asıl skorda
            # onem_puani >= 8 ile geri dönebilir.
            puan -= 15
        puanli.append((puan, haber))

    puanli.sort(key=lambda p: p[0], reverse=True)
    secilen = [h for _, h in puanli[:kac]]
    log.info("ön eleme: %d havuzdan %d aday", len(havuz), len(secilen))
    return secilen


def skor(haber, ayarlar: dict) -> float:
    """
    Asıl seçim skoru. Metin üretildikten SONRA çalışır.

    Formül CLAUDE.md'de kararlaştırıldı:
        onem_puani * 10 + agirlik - yaş_saat
        - 15  eğer kategori == 'dunya' ve onem_puani < 8
    """
    onem = haber["onem_puani"] or 0
    deger = onem * 10 + (haber["agirlik"] or 1) - _yas_saat(haber)
    if haber["kategori"] == "dunya" and onem < 8:
        deger -= 15
    return deger


# Konu karşılaştırmasında sayılmayacak kelimeler. Bunlar her başlıkta
# geçiyor ve iki haberi yapay olarak "benzer" gösteriyor.
ETKISIZ_KELIMELER = {
    "için", "ile", "olarak", "sonra", "önce", "üzere", "kadar", "daha",
    "göre", "karşı", "yeni", "büyük", "sonrası", "ilgili", "hakkında",
    "arasında", "üzerine", "birlikte", "dedi", "açıkladı", "oldu",
    "edildi", "verdi", "aldı", "yaptı", "bulundu", "geldi", "başladı",
}


def _anahtar_kelimeler(baslik: str) -> set[str]:
    """
    Başlığın konusunu temsil eden kelimeler.

    Türkçe ek almış hâlleri ("İsrail'in", "Gazze'de") aynı köke indirmek
    için kesme işaretinden sonrası atılıyor; yoksa aynı olayın haberleri
    farklı kelime gibi görünüyor.
    """
    kelimeler = set()
    for ham in (baslik or "").lower().replace("'", " ").split():
        temiz = "".join(k for k in ham if k.isalnum())
        if len(temiz) >= 4 and temiz not in ETKISIZ_KELIMELER:
            kelimeler.add(temiz)
    return kelimeler


def cesitlendir(adaylar: list, adet: int, ayarlar: dict) -> list:
    """
    Skora göre sıralı adaylardan ÇEŞİTLİ bir tur kurar.

    NEDEN GEREKTİ: seçim düz skor sıralamasıydı ve aynı olayın haberleri
    birbirine yakın puan aldığı için üst üste diziliyordu. 16 Ağu 2026
    turunda 10 haberin 6'sı İsrail/Gazze, 8'i tek kaynaktandı — takipçi
    için bu "haber özeti" değil, tek konunun tekrarı.

    Üç kural: aynı olaydan bir haber, kategori başına sınır, kaynak
    başına sınır.

    ⚠️ KURALLAR TURU EKSİK BIRAKMAZ. Havuz darsa (gecenin ilerleyen
    saatleri, kota hatası) kısıtlar gevşetilip kalan en yüksek puanlılar
    ekleniyor: 7 haberlik bir carousel, 10 haberlik tekdüze bir turdan
    kötü değil ama boş slayt hiç kabul edilemez.
    """
    s = ayarlar.get("secim", {}) or {}
    azami_kategori = s.get("azami_ayni_kategori", 3)
    azami_kaynak = s.get("azami_ayni_kaynak", 4)
    ortak_esik = s.get("konu_ortak_kelime_esigi", 2)

    secilen, kategori_sayaci, kaynak_sayaci, konular = [], {}, {}, []

    for haber in adaylar:
        if len(secilen) >= adet:
            break
        kategori = haber["kategori"] or "?"
        kaynak = haber["kaynak"] or "?"
        kelimeler = _anahtar_kelimeler(haber["ig_baslik"] or haber["baslik_orj"])

        if any(len(kelimeler & onceki) >= ortak_esik for onceki in konular):
            continue
        if kategori_sayaci.get(kategori, 0) >= azami_kategori:
            continue
        if kaynak_sayaci.get(kaynak, 0) >= azami_kaynak:
            continue

        secilen.append(haber)
        konular.append(kelimeler)
        kategori_sayaci[kategori] = kategori_sayaci.get(kategori, 0) + 1
        kaynak_sayaci[kaynak] = kaynak_sayaci.get(kaynak, 0) + 1

    if len(secilen) < adet:
        eksik = adet - len(secilen)
        secili_idler = {h["id"] for h in secilen}
        yedek = [h for h in adaylar if h["id"] not in secili_idler][:eksik]
        if yedek:
            log.info("çeşitlilik kuralları %d haber için gevşetildi", len(yedek))
        secilen += yedek

    return secilen


def tur_icin_sec(con, ayarlar: dict) -> list:
    """
    Yayınlanacak haberleri seçer.

    Metni hazır olan havuzdan skora göre sıralayıp en iyi N tanesini
    döner. Onaylanmayıp havuza dönen haberler burada yeniden yarışıyor —
    "onay verilmezse haber elenmez" kararı böyle işliyor.
    """
    g = ayarlar["gorsel"]
    sinir_saat = ayarlar["genel"]["yayin_yasi_siniri_saat"]

    adaylar = [
        h for h in con.execute(
            "SELECT * FROM haberler WHERE durum = 'metin_hazir' "
            "AND ig_baslik IS NOT NULL"
        )
        if _yas_saat(h) <= sinir_saat
    ]

    adaylar.sort(key=lambda h: skor(h, ayarlar), reverse=True)
    # Düz sıralamadan almak yerine çeşitlendiriyoruz: aynı olayın
    # haberleri birbirine yakın puan aldığı için üst üste diziliyordu.
    secilen = cesitlendir(adaylar, g["slayt_sayisi"], ayarlar)

    log.info("tur seçimi: %d adaydan %d haber", len(adaylar), len(secilen))
    return secilen
