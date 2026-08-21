"""
aday.py — "Bu haber şu bağlamda yayınlanabilir mi?" sorusunun TEK cevabı.

NİYE VAR — ÖLÇÜLMÜŞ BİR SORUN:

    Bu projede kusurların çoğu tek bir desende toplanıyordu: AYNI KURAL
    BİRDEN FAZLA YERDE YAŞIYOR VE BİRİ UNUTULUYOR.

      * 1j — mükerrer engeli tur seçimine kondu, tekil posta konmadı;
             aynı olay üç kez tura girdi
      * 1p — aynı engel `onerileri_gonder`e ve `tur_icin_sec`e kondu,
             `aday_bul`a KONMADI; sabah turunda yayınlanan haber bir
             saat sonra tekil post olarak çıktı
      * `TAZELIK_SAAT` sabit koda gömülüydü, config'deki değer ölüydü;
             tekil post 5 saat boyunca hiç çıkmadı

    Üçü de "kural yanlıştı" değil, "kural doğru ama bir yerde
    uygulanmamıştı" hatasıydı. Kuralları buraya toplayınca o hata
    sınıfı yapısal olarak imkânsız hale geliyor: yeni bir akış eklemek
    istediğinde `uygun_mu()` çağırıyorsun ve bütün kurallar otomatik
    geliyor.

NASIL KULLANILIR:

    from src import aday

    baglam = aday.Baglam.kur("tekil", ayarlar, con)
    for haber in havuz:
        uygun, sebep = aday.uygun_mu(haber, baglam)
        if not uygun:
            log.debug("elendi (%s): %s", sebep, haber["baslik_orj"][:50])
            continue

BAĞLAMLAR:
    "tur"    — sabah/akşam carousel turu (10 slayt)
    "tekil"  — gün içi tekil post, metni HAZIR haberlerden
    "oneri"  — Telegram'a başlık önerisi, metni HENÜZ ÜRETİLMEMİŞ

    Üçü farklı eşik ve farklı durum filtresi kullanıyor ama tazelik,
    geçmiş tekrarı ve mükerrer denetimi ORTAK. Farkların hepsi
    `Baglam` içinde veri olarak duruyor; `uygun_mu` içinde
    `if baglam == "tur"` gibi dallanma YOK.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import secim

log = logging.getLogger(__name__)

# Bağlam adları — yazım hatası sessizce yanlış davranışa yol açmasın.
TUR = "tur"
TEKIL = "tekil"
ONERI = "oneri"
GECERLI_BAGLAMLAR = (TUR, TEKIL, ONERI)


def gece_mi(simdi: datetime | None = None) -> bool:
    """TR saatiyle gece aralığı (23:00-07:00). UTC+3 sabit, yaz saati yok."""
    an = (simdi or datetime.now(timezone.utc)) + timedelta(hours=3)
    return an.hour >= 23 or an.hour < 7


@dataclass
class Baglam:
    """
    Bir seçim turunun değişmeyen verileri.

    Her haber için yeniden hesaplanmasın diye bir kez kurulup
    `uygun_mu`ya geçiriliyor: geçmiş konular veritabanı sorgusu,
    kategori sayaçları, eşik tablosu.
    """
    ad: str
    esikler: dict                      # kategori -> asgari puan
    varsayilan_esik: int
    tazelik_saat: float                # bundan eski haber aday olamaz
    kategori_azami: int | None         # None = sınır yok
    kategori_sayaci: dict              # kategori -> bugün yayınlanan adet
    gecmis_konular: list               # [(kelimeler, özel_isimler)]
    gecmis_esik: int
    liste_esigi: int                   # aynı listede tekrar denetimi
    muafiyet_puani: int                # bu puanın üstü geçmiş denetiminden muaf
    atlanan_bekleme: float = 12.0       # atlanan haber kaç saat beklesin
    gece: bool = False
    # Aynı çağrı içinde seçilenler — liste içi mükerrer denetimi için
    _secilenler: list = field(default_factory=list)

    @classmethod
    def kur(cls, ad: str, ayarlar: dict, con) -> "Baglam":
        if ad not in GECERLI_BAGLAMLAR:
            raise ValueError(f"bilinmeyen bağlam: {ad!r} "
                             f"(geçerli: {GECERLI_BAGLAMLAR})")
        g = ayarlar["genel"]
        s = ayarlar.get("secim", {}) or {}
        gece = gece_mi()

        if ad == ONERI:
            # ⚠️ Öneri eşikleri yayın eşiklerinden DÜŞÜK. Toplu başlık
            # puanlaması tam metin puanlamasından ~1.6 puan düşük
            # veriyor (ölçüldü); aynı eşik öneri akışını kilitliyordu.
            # ⚠️ Gece +1 YOK: öneri yayın değil, insana sunma.
            esikler = g.get("oneri_kategori_esikleri", {}) or {}
            varsayilan = 6
            ek = 0
        elif ad == TEKIL:
            esikler = g.get("son_dakika_kategori_esikleri", {}) or {}
            varsayilan = (g.get("gece_puan_esigi", 9) if gece
                          else g.get("son_dakika_puan_esigi", 8))
            # Gece yayın eşiği bir puan daha zor: kimsenin onayından
            # geçmeden yayında kalıyor.
            ek = 1 if gece else 0
        else:                                          # TUR
            esikler = {}
            varsayilan = s.get("asgari_onem_puani", 0)
            ek = 0

        if ek:
            esikler = {k: v + ek for k, v in esikler.items()}
            varsayilan += ek

        # Tazelik: tur bayatlama sınırını, tekil/öneri kendi penceresini
        # kullanıyor.
        if ad == TUR:
            tazelik = g.get("yayin_yasi_siniri_saat", 48)
        else:
            tazelik = g.get("son_dakika_tazelik_saat", 5)

        return cls(
            ad=ad,
            esikler=esikler,
            varsayilan_esik=varsayilan,
            tazelik_saat=tazelik,
            kategori_azami=(g.get("son_dakika_kategori_azami", 3)
                            if ad in (TEKIL, ONERI) else None),
            kategori_sayaci=_bugunku_kategoriler(con),
            gecmis_konular=secim.yayinlanmis_konular(con, ayarlar),
            gecmis_esik=s.get("gecmis_ortak_kelime_esigi",
                              s.get("konu_ortak_kelime_esigi", 2) + 1),
            liste_esigi=s.get("konu_ortak_kelime_esigi", 2),
            muafiyet_puani=s.get("gecmis_muafiyet_puani", 9),
            atlanan_bekleme=g.get("atlanan_bekleme_saat", 12),
            gece=gece,
        )

    def esik(self, kategori: str | None) -> int:
        return self.esikler.get(kategori, self.varsayilan_esik)


def _bugunku_kategoriler(con) -> dict:
    """Bugün her kategoriden kaç tekil post yayınlandı?"""
    return {
        r[0]: r[1] for r in con.execute(
            "SELECT kategori, COUNT(*) FROM haberler "
            "WHERE son_dakika = 1 AND durum = 'yayinlandi' "
            "AND date(gonderim_zamani) = date('now') GROUP BY kategori"
        )
    }


def _yas_saat(haber) -> float:
    ham = haber["yayin_tarihi"] if "yayin_tarihi" in haber.keys() else None
    if not ham:
        return 999.0
    try:
        t = datetime.fromisoformat(ham)
    except (ValueError, TypeError):
        return 999.0
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 3600


def _baslik(haber) -> str:
    anahtarlar = haber.keys()
    if "ig_baslik" in anahtarlar and haber["ig_baslik"]:
        return haber["ig_baslik"]
    return haber["baslik_orj"] or ""


def uygun_mu(haber, baglam: Baglam) -> tuple[bool, str]:
    """
    Bu haber bu bağlamda seçilebilir mi?

    Döner: `(uygun, sebep)`. Sebep her zaman dolu — elenme nedenini
    loglamak teşhisin yarısı. "Tekil post 5 saat çıkmadı" olayında
    havuzun %98'inin tazelik filtresine takıldığı ancak elle ölçerek
    anlaşılmıştı; artık log doğrudan söylüyor.
    """
    puan = haber["onem_puani"] or 0
    kategori = haber["kategori"] or ""
    baslik = _baslik(haber)

    # 1) Tazelik — bayat haber hiçbir bağlamda aday olmaz
    yas = _yas_saat(haber)
    if yas > baglam.tazelik_saat:
        return False, f"bayat ({yas:.1f} sa > {baglam.tazelik_saat} sa)"

    # 2) Önem eşiği
    esik = baglam.esik(kategori)
    if puan < esik:
        return False, f"puan yetersiz ({puan} < {esik}, kategori={kategori})"

    # 3) Kategori günlük sınırı — tek kategori günü domine etmesin
    if baglam.kategori_azami is not None:
        bugun = baglam.kategori_sayaci.get(kategori, 0)
        if bugun >= baglam.kategori_azami:
            return False, f"kategori sınırı dolu ({kategori}: {bugun})"

    # ⚠️ `konu_imzasi` kullanılıyor, `_ozel_isimler` DEĞİL: ikincisi
    # başlığın ilk kelimesini atlıyor ve haber başlıkları çok sık yer
    # adıyla başladığı için tekrarlar yakalanamıyor (sözleşme testi
    # bu kusuru yakaladı).
    kelimeler, isimler = secim.konu_imzasi(baslik)

    # 3b) Yakın zamanda turdan ATLANDI mı?
    #
    # "Atla" düğmesi haberi elemiyor (proje kuralı: onaylanmayan haber
    # kaybolmaz) ama kullanıcı o haberi ŞİMDİ istemediğini söylemiş
    # oluyor. Skor cezası dar havuzda yetmiyor — ölçüldü, atlanan 10
    # haberin 5'i bir sonraki turda geri geldi.
    atlandi = haber["atlanma_zamani"] if "atlanma_zamani" in haber.keys() else None
    if atlandi:
        try:
            gecen = (datetime.now(timezone.utc)
                     - datetime.fromisoformat(atlandi)).total_seconds() / 3600
            if gecen < baglam.atlanan_bekleme:
                return False, "yakın zamanda atlandı"
        except (TypeError, ValueError):
            pass

    # 4) Aynı çağrıda daha önce seçilen bir haberin tekrarı mı?
    # ⚠️ DÜZ KESİŞİM DEĞİL — Türkçe ekleri tolere eden karşılaştırma.
    # "ceza"/"cezası", "kulübe"/"kulüplere" düz kesişimde farklı
    # kelime sayılıyordu ve aynı PFDK kararının iki haberi tek tura
    # girdi (20 Ağu 2026).
    for onceki_k, onceki_i in baglam._secilenler:
        if (len(secim.ortak_kelime(kelimeler, onceki_k)) >= baglam.liste_esigi
                and secim.ortak_kelime(isimler, onceki_i)):
            return False, "bu seçimde aynı olay zaten var"

    # 5) Son günlerde YAYINLANMIŞ bir olayın tekrarı mı?
    #
    # ⚠️ Muafiyet: gerçekten büyük bir olay günün özetinde de yer
    # almalı. Gündüz son dakika olarak paylaşılan bir deprem, akşam
    # özetinde de görünmeli — özet o günü anlatıyor.
    if puan < baglam.muafiyet_puani:
        for onceki_k, onceki_i in baglam.gecmis_konular:
            if (len(secim.ortak_kelime(kelimeler, onceki_k)) >= baglam.gecmis_esik
                    and secim.ortak_kelime(isimler, onceki_i)):
                return False, "bu konu son günlerde yayınlandı"

    return True, "uygun"


def sec(haberler, baglam: Baglam, adet: int | None = None) -> list:
    """
    Havuzdan uygun haberleri seçer; seçtiklerini bağlama işler.

    `adet` verilirse o sayıda haber seçilince durur. Elenen her haber
    DEBUG seviyesinde sebebiyle loglanıyor.
    """
    secilen = []
    sebepler: dict[str, int] = {}
    for haber in haberler:
        if adet is not None and len(secilen) >= adet:
            break
        uygun, sebep = uygun_mu(haber, baglam)
        if not uygun:
            anahtar = sebep.split(" (")[0]
            sebepler[anahtar] = sebepler.get(anahtar, 0) + 1
            continue
        secilen.append(haber)
        baslik = _baslik(haber)
        baglam._secilenler.append(secim.konu_imzasi(baslik))
    if sebepler:
        log.info("[%s] eleme: %s", baglam.ad,
                 ", ".join(f"{k}={v}" for k, v in sorted(sebepler.items())))
    return secilen


def alternatifler(con, ayarlar: dict, mevcut, turdaki_idler,
                  adet: int = 2) -> list:
    """
    Turdaki bir haberin YERİNE konabilecek adaylar.

    Kullanıcı onay mesajında bir slaydı beğenmezse ("bu haberi
    değiştir") buradan gelen alternatifler sunuluyor.

    ⚠️ KURALLAR YENİDEN YAZILMIYOR — `uygun_mu` çağrılıyor. Bu
    dosyanın var olma sebebi tam da bu: bu projedeki kusurların çoğu
    "kural yanlıştı" değil, "kural doğru ama BİR YERDE uygulanmamıştı"
    hatasıydı (CLAUDE.md 1j, 1p, 1z). Yeni bir akış açarken kuralları
    kopyalamak o hatayı yeniden üretmek olurdu.

    Sıralama: önce AYNI KATEGORİDEN olanlar. Sebep sadece konu
    yakınlığı değil — turun kategori dengesi zaten `cesitlendir` ile
    kurulmuş durumda; ekonomi haberini sporla değiştirmek o dengeyi
    bozar.
    """
    havuz = list(con.execute(
        "SELECT * FROM haberler WHERE durum = 'metin_hazir' "
        "AND ig_baslik IS NOT NULL AND gorsel_url IS NOT NULL"
    ))
    if not havuz:
        # Görseli hazır aday yoksa metni hazır olanlarla devam: slayt
        # değiştirme anında üretiliyor, görsel şart değil.
        havuz = list(con.execute(
            "SELECT * FROM haberler WHERE durum = 'metin_hazir' "
            "AND ig_baslik IS NOT NULL"
        ))

    baglam = Baglam.kur(TUR, ayarlar, con)
    # Turdaki DİĞER haberler de "aynı listede" sayılmalı, yoksa
    # değiştirilen haberin yerine turdaki BAŞKA bir haberin benzeri
    # gelebilir ve tur yine mükerrer olur.
    # ⚠️ `_secilenler` haber satırı değil, (kelimeler, özel_isimler)
    # imzası tutuyor — `uygun_mu` onu öyle açıyor.
    baglam._secilenler = [
        secim.konu_imzasi(_baslik(h))
        for h in _turdakiler(con, turdaki_idler) if h["id"] != mevcut["id"]
    ]

    uygunlar = []
    for h in havuz:
        if h["id"] in turdaki_idler:
            continue
        tamam, _ = uygun_mu(h, baglam)
        if tamam:
            uygunlar.append(h)

    kategori = mevcut["kategori"]
    uygunlar.sort(key=lambda h: (h["kategori"] != kategori,
                                 -(h["onem_puani"] or 0),
                                 _yas_saat(h)))
    log.info("[degistir] %s haberden %s alternatif bulundu (kategori=%s)",
             len(havuz), len(uygunlar), kategori)
    return uygunlar[:adet]


def _turdakiler(con, idler) -> list:
    if not idler:
        return []
    isaret = ",".join("?" * len(idler))
    return list(con.execute(
        f"SELECT * FROM haberler WHERE id IN ({isaret})", tuple(idler)))
