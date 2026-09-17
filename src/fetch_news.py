"""
fetch_news.py — ADIM 1
RSS feed'lerinden haberleri çeker, temizler, SQLite'a yazar.

Dışarıdan kullanımı:
    from src.fetch_news import haberleri_cek
    sonuc = haberleri_cek()
"""

from __future__ import annotations

import logging
import re
import warnings
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import yaml
from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning
from dateutil import parser as tarih_ayristirici

from . import db, filtre

KOK = Path(__file__).resolve().parent.parent
CONFIG_YOLU = KOK / "config.yaml"

log = logging.getLogger(__name__)

# Haber siteleri "python-requests" görünce çoğu zaman kapıyı kapatıyor.
# Normal bir tarayıcı gibi görünüyoruz.
BASLIKLAR = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}

ATOM = "{http://www.w3.org/2005/Atom}"

# Bazı RSS özetleri düz bir URL'den ibaret oluyor. BeautifulSoup böyle bir
# metin görünce "bu dosya adına benziyor" diye uyarı basıyor. Zararsız ama
# log'u kirletiyor, özellikle GitHub Actions çıktısında. Susturuyoruz.
warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)


# ----------------------------------------------------------------------
# Yardımcılar
# ----------------------------------------------------------------------

def ayarlari_oku() -> dict:
    with open(CONFIG_YOLU, encoding="utf-8") as f:
        return yaml.safe_load(f)


def html_temizle(metin: str | None) -> str:
    """RSS özetleri çoğu zaman HTML etiketi içerir. Düz metne çeviriyoruz."""
    if not metin:
        return ""
    duz = BeautifulSoup(metin, "html.parser").get_text(separator=" ")
    return " ".join(duz.split())        # fazla boşlukları tekle


def tarihi_cevir(ham: str | None) -> str | None:
    """
    RSS tarihleri çok farklı formatlarda gelir.
    Hepsini UTC'ye çevirip ISO 8601 olarak saklıyoruz ki
    SQL'de karşılaştırabilelim.
    """
    if not ham:
        return None
    try:
        t = tarih_ayristirici.parse(ham)
    except (ValueError, OverflowError, TypeError):
        return None
    if t.tzinfo is None:
        # Saat dilimi yazmamışsa Türkiye saati varsayıyoruz (UTC+3)
        t = t.replace(tzinfo=timezone(timedelta(hours=3)))
    return t.astimezone(timezone.utc).isoformat()


def _metin(ogeler, *etiketler) -> str | None:
    """Bir XML düğümünde verilen etiketlerden ilk bulunanın metnini döner."""
    for etiket in etiketler:
        bulunan = ogeler.find(etiket)
        if bulunan is not None:
            if bulunan.text and bulunan.text.strip():
                return bulunan.text.strip()
            # Atom'da <link href="..."/> şeklinde olabiliyor
            href = bulunan.get("href")
            if href:
                return href.strip()
    return None


# ----------------------------------------------------------------------
# Tek bir feed'i indir + ayrıştır
# ----------------------------------------------------------------------

def _bozuk_baytlari_onar(xml_bytes: bytes) -> bytes:
    """
    Bazı siteler feed'ini "UTF-8" diye ilan edip içine UTF-8 olmayan bozuk
    bayt karıştırıyor (TRT Haber bunu yapıyor). XML ayrıştırıcı tek bir
    bozuk karaktere takılıp feed'in TAMAMINI reddediyor.

    Burada bozuk baytları '�' ile değiştirip geri kalan haberleri kurtarıyoruz.
    Kaybedilen tek şey o bozuk harf; haberin geri kalanı ve diğer tüm
    haberler sağlam geliyor.

    ÖNEMLİ: Bu fonksiyon sadece normal ayrıştırma zaten patladığında
    çağrılıyor. Yani hâlihazırda sorunsuz çalışan feed'lere hiç dokunmuyor.
    """
    # Feed hangi kodlamayı iddia ediyor? (ilk satırdaki <?xml ... ?> bildirimi)
    kodlama = "utf-8"
    eslesme = re.search(rb"""encoding=["']([\w-]+)["']""", xml_bytes[:200])
    if eslesme:
        kodlama = eslesme.group(1).decode("ascii", errors="replace")

    try:
        metin = xml_bytes.decode(kodlama, errors="replace")
    except LookupError:                 # tanımadığımız bir kodlama adı yazmışlar
        metin = xml_bytes.decode("utf-8", errors="replace")

    # Metin artık gerçekten UTF-8; bildirimin de bunu söylemesi lazım,
    # yoksa ayrıştırıcı yine yanlış kodlamayla okumaya çalışır.
    metin = re.sub(
        r"""encoding=["'][\w-]+["']""", 'encoding="utf-8"', metin, count=1
    )
    return metin.encode("utf-8")


TRT_TABAN = "https://www.trthaber.com/"


def _trt_ayristir(girdiler) -> list[dict]:
    """
    TRT'nin `xml_mobile` beslemesini standart haber sözlüğüne çevirir.

    ⚠️ LİNKLER GÖRELİ geliyor ("haber/dunya/...html"); başına alan adı
    eklenmezse makale gövdesi çekilemiyor ve `og:image` bulunamıyor,
    yani hem metin hem görsel katmanı sessizce düşüyor.
    """
    sonuc = []
    for g in girdiler:
        baslik = (g.findtext("haber_manset") or "").strip()
        link = (g.findtext("haber_link") or "").strip()
        if not baslik or not link:
            continue
        if not link.startswith("http"):
            link = TRT_TABAN + link.lstrip("/")
        sonuc.append({
            "baslik_orj": " ".join(baslik.split()),
            "link": link,
            "ozet_orj": html_temizle(g.findtext("haber_aciklama")),
            "yayin_tarihi": tarihi_cevir(g.findtext("haber_tarihi")),
        })
    return sonuc


def feed_ayristir(xml_bytes: bytes) -> list[dict]:
    """Ham XML'i haber listesine çevirir. RSS 2.0 ve Atom destekli."""
    try:
        kok = ET.fromstring(xml_bytes)
    except ET.ParseError:
        # Feed bozuk olabilir: baytları onarıp bir kez daha deniyoruz.
        # Hâlâ patlarsa hata yukarı gider, kaynak "bozuk" diye raporlanır.
        kok = ET.fromstring(_bozuk_baytlari_onar(xml_bytes))

    # ⚠️ TRT ÖZEL FORMAT — RSS de Atom da değil.
    #
    # TRT'nin kategori beslemeleri (`xml_mobile.php?kategori=spor`)
    # `<haberler><haber><haber_manset>` yapısında geliyor. Standart
    # okuyucu bunu boş sanıp kaynağı düşürüyordu; TRT ağırlığı 10 olan
    # en güvendiğimiz kaynak olduğu ve kategori beslemeleri yalnızca
    # burada bulunduğu için ayrı bir dal açıldı (18 Ağu 2026).
    #
    # Doğrulandı: spor / ekonomi / bilim-teknoloji arasında 0 ortak
    # haber var, yani kategori parametresi gerçekten çalışıyor.
    trt = kok.findall(".//haber")
    if trt and kok.tag == "haberler":
        return _trt_ayristir(trt)

    girdiler = kok.findall(".//item")            # RSS 2.0
    atom = False
    if not girdiler:
        girdiler = kok.findall(f".//{ATOM}entry")  # Atom
        atom = bool(girdiler)

    sonuc = []
    for g in girdiler:
        if atom:
            baslik = _metin(g, f"{ATOM}title")
            link = _metin(g, f"{ATOM}link", f"{ATOM}id")
            ozet = _metin(g, f"{ATOM}summary", f"{ATOM}content")
            tarih = _metin(g, f"{ATOM}published", f"{ATOM}updated")
        else:
            baslik = _metin(g, "title")
            link = _metin(g, "link", "guid")
            ozet = _metin(g, "description", "summary")
            tarih = _metin(g, "pubDate", "date")

        if not baslik or not link:
            continue    # başlığı veya linki olmayan girdi işimize yaramaz

        sonuc.append(
            {
                "baslik_orj": " ".join(baslik.split()),
                "link": link,
                "ozet_orj": html_temizle(ozet),
                "yayin_tarihi": tarihi_cevir(tarih),
            }
        )
    return sonuc


def feed_indir(url: str, zaman_asimi: int) -> bytes:
    cevap = requests.get(url, headers=BASLIKLAR, timeout=zaman_asimi)
    cevap.raise_for_status()
    return cevap.content


# ----------------------------------------------------------------------
# Ana iş
# ----------------------------------------------------------------------

# Kategori beslemeleri için son dakika çekimindeki alt sınır.
# Gündem akışlarınınkinden düşük: kategori çeşitliliği buna bağlı.
KATEGORI_ASGARI_AGIRLIK = 7


def haberleri_cek(ayarlar: dict | None = None,
                  asgari_agirlik: int | None = None) -> dict:
    """
    Tüm aktif kaynakları gezer, yeni haberleri veritabanına yazar.
    Bir kaynak patlarsa diğerleri etkilenmez.

    `asgari_agirlik` verilirse yalnızca o ağırlıktaki ve üstündeki
    kaynaklar taranır.

    ⚠️ NEDEN VAR — GITHUB ACTIONS KOTASI. Son dakika kontrolü saat başı
    çalışıyor ve her seferinde 22 kaynağı tarıyordu; job süresinin
    171 saniyesinin neredeyse tamamı RSS indirmekle geçiyordu. Ölçüldü
    (18 Ağu 2026): bu tempoyla aylık kullanım 2040 dakikaya çıkıyor ve
    2000 dakikalık ücretsiz limit AŞILIYOR — bot ay sonunda dururdu.

    Son dakika haberi doğası gereği yüksek ağırlıklı gündem
    kaynaklarından geliyor; kültür, yaşam, motor sporları beslemelerini
    saat başı taramanın karşılığı yok. Akşam turu hepsini zaten tarıyor.

    ⚠️ AMA KATEGORİ BESLEMELERİ BU FİLTREDEN MUAF OLMAK ZORUNDA.
    19 Ağu 2026'da ölçüldü: AA Kültür ve AA Spor beslemeleri
    veritabanına 3 GÜNDE SIFIR haber yazmıştı, oysa ikisi de sağlıklı
    çalışıyor ve 30'ar haber veriyor.

    Sebep: ağırlıkları 8, yani bu filtreye takılıyorlardı. Ama AA'nın
    GENEL akışının ağırlığı 9 ve o geçiyordu — aynı haberleri "turkiye"
    etiketiyle önce kaydediyor, `haberler.link` UNIQUE olduğu için
    kategori beslemesi sonradan geldiğinde "tekrar" sayılıp eleniyordu.
    Kontrol günde 20 kez, tur günde 2 kez çalıştığı için genel akış
    her zaman önce davranıyordu.

    Sonuç: spor ve kültür kategorileri veritabanında hiç oluşmuyor,
    kategori bazlı ön eleme onlara yer ayırsa bile ortada haber yok.
    Bu yüzden filtre yalnızca GÜNDEM akışlarına uygulanıyor.

    Döner: {'eklenen': int, 'tekrar': int, 'eski': int, 'kaynaklar': [...]}
    """
    ayarlar = ayarlar or ayarlari_oku()
    genel = ayarlar["genel"]
    yas_siniri = datetime.now(timezone.utc) - timedelta(hours=genel["haber_yasi_saat"])

    db.kur()
    rapor = {"eklenen": 0, "tekrar": 0, "eski": 0, "elenen": 0,
             "kaynaklar": []}

    # SEO çöpü desenleri (config → icerik_filtresi.baslik_elemeleri).
    # Bkz. filtre.baslik_elenmeli — neden girişte elendiği orada yazılı.
    eleme_desenleri = (ayarlar.get("icerik_filtresi", {}) or {}).get(
        "baslik_elemeleri", []) or []

    with db.baglan() as con:
        for kaynak in ayarlar["kaynaklar"]:
            if not kaynak.get("aktif", True):
                continue
            # Filtre yalnızca gündem akışlarına tam uygulanır; kategori
            # beslemeleri daha düşük bir eşikle taranır (yoksa spor ve
            # kültür veritabanında hiç oluşmuyor — yukarıdaki nota bak).
            # Kategori beslemelerine de bir alt sınır var: dünya
            # kategorisi zaten TRT/AA ile temsil ediliyor, ağırlığı 4-5
            # olan akışları saat başı taramanın karşılığı yok.
            agirlik = kaynak.get("agirlik") or 0
            genel_akis = (kaynak.get("kategori") or "") == "turkiye"
            if asgari_agirlik is not None:
                esik = asgari_agirlik if genel_akis else min(asgari_agirlik, KATEGORI_ASGARI_AGIRLIK)
                if agirlik < esik:
                    continue

            k_rapor = {"ad": kaynak["ad"], "durum": "ok", "eklenen": 0,
                       "tekrar": 0, "eski": 0, "elenen": 0, "hata": None}

            try:
                ham = feed_indir(kaynak["url"], genel["istek_zaman_asimi"])
                girdiler = feed_ayristir(ham)
            except requests.HTTPError as e:
                k_rapor.update(durum="hata", hata=f"HTTP {e.response.status_code}")
                log.warning("%s: %s", kaynak["ad"], k_rapor["hata"])
                rapor["kaynaklar"].append(k_rapor)
                continue
            except Exception as e:                      # ağ hatası, bozuk XML vs.
                k_rapor.update(durum="hata", hata=f"{type(e).__name__}: {e}")
                log.warning("%s: %s", kaynak["ad"], k_rapor["hata"])
                rapor["kaynaklar"].append(k_rapor)
                continue

            for girdi in girdiler[: genel["kaynak_basina_limit"]]:
                # Çok eski haberleri alma
                if girdi["yayin_tarihi"]:
                    t = datetime.fromisoformat(girdi["yayin_tarihi"])
                    if t < yas_siniri:
                        k_rapor["eski"] += 1
                        continue

                # SEO çöpü mü? (rüya tabiri, loto sonucu, aktüel ürün
                # kataloğu). Havuza HİÇ girmiyor — seçim aşamasında
                # elemek geç kalıyor, 24 puanlama slotu zaten dolmuş
                # oluyor. Bkz. filtre.baslik_elenmeli.
                elendi = filtre.baslik_elenmeli(girdi["baslik_orj"],
                                                eleme_desenleri)
                if elendi:
                    k_rapor["elenen"] += 1
                    log.debug("başlık elendi [%s]: %s",
                              elendi, girdi["baslik_orj"][:70])
                    continue

                girdi.update(
                    kaynak=kaynak["ad"],
                    kategori=kaynak["kategori"],
                    agirlik=kaynak.get("agirlik", 0),
                )

                if db.haber_ekle(con, girdi):
                    k_rapor["eklenen"] += 1
                else:
                    k_rapor["tekrar"] += 1

            for anahtar in ("eklenen", "tekrar", "eski", "elenen"):
                rapor[anahtar] += k_rapor[anahtar]
            rapor["kaynaklar"].append(k_rapor)

        con.commit()

    return rapor
