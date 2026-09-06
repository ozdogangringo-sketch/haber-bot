"""
slaytlar.py — ADIM 3'ün son parçası

Bir turluk carousel'in bütün slaytlarını üretir.

BURADAKİ ASIL İŞ: görsel katmanını seçmek. Her haberin arka planı dört
kaynaktan gelebiliyor, sırayla deneyip ilk tutanı kullanıyoruz:

    0. Haberin kendi görseli (og:image) — olayın FOTOĞRAFI
    1. Wikimedia Commons  — haberde tanınmış bir kişi varsa
    2. Pexels             — yoksa konuyu temsil eden stok fotoğraf
    3. Gradyan            — hiçbiri bulamazsa

Neden sıra bu: haberin kendi görseli olayın kendisini gösteriyor, en
güçlü olan o (⚠️ telif riski taşıyor, bkz. `arkaplan_sec`). Commons
gerçek kişinin gerçek fotoğrafını veriyor ama sadece tanınmış isimlerde
tutuyor. Pexels her konuda bir şey buluyor ama temsili — "bir otobüs",
o otobüs değil. Gradyan hiç yanıltmıyor ama hiçbir şey de anlatmıyor.

AI bu zincirde YOK. Normal turda hiç çağrılmıyor, dolayısıyla bir turun
görsel maliyeti sıfır. AI yalnızca Telegram'dan elle tetiklenince
devreye giriyor (Adım 5).
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

import re
import requests
from PIL import Image, ImageOps

from . import filtre, dogrula, fetch_article, fetch_photo, fetch_stock, fetch_web_image, gorsel_kalite, make_image

log = logging.getLogger(__name__)

# Arka planında GERÇEK FOTOĞRAF olan katmanlar.
FOTOGRAFLI_KATMANLAR = ("haber", "web_haber", "commons", "commons_split", "pexels", "ai")


def _kalite(g: dict, katman: str) -> int:
    """
    JPEG kalitesi katmana göre seçiliyor.

    Fotoğraflı arka planlarda 88 JPEG kalitesi yetersiz; yapay
    artefaktlar ve banding (renk basamaklanması) yaratıyor. Bu yüzden
    fotoğraflı olanlara 95 veriyoruz (ölçüldü: dosya boyutu ~240 KB -> ~360 KB,
    ama görsel farkı çok belirgin).

    Fotoğrafsız (gradyan/soyut) arka planlarda 88 yeterli.
    """
    if katman in FOTOGRAFLI_KATMANLAR:
        return g.get("jpeg_kalite_foto", 95)
    return g.get("jpeg_kalite", 88)

# Bunlardan hangilerinde "ARŞİV GÖRSELİ" ibaresi basılsın?
# `haber` katmanı HARİÇ: o görsel olayın kendi fotoğrafı, arşiv değil.
# ⚠️ `web_haber` BURADA OLMAK ZORUNDA: internetten aranan fotoğrafın
# olayın kendi belgesi olduğuna dair hiçbir güvencemiz yok. 28 Ağu -
# 3 Eyl 2026 arasında bu ibare basılmadan 10 post çıktı.
ARSIV_KATMANLARI = ("commons", "pexels", "web_haber")


def _alan(haber, ad: str) -> str:
    """
    Haber kaydından güvenli alan okuma.

    sqlite3.Row'da olmayan bir kolona erişmek IndexError/KeyError atıyor;
    sayısal değerlerde (id, onem_puani vb.) strip çökmemesi için str'ye çevrilir.

    ⚠️ KAÇIŞ DİZİLERİ BURADA DA ÇÖZÜLÜYOR. Üretim girişinde de
    çözülüyor ama bu kapı ESKİ KAYITLARI ve diğer üretim yollarını
    (`onay_isle` içindeki başlık düzeltme, aday üretimi gibi ayrı
    `json.loads` noktaları) da kapsıyor — kaynağı düzeltmek geçmiş
    kayıtları düzeltmiyor, bu projede defalarca yaşandı.
    """
    try:
        val = haber[ad]
        if val is None:
            return ""
        return filtre.kacislari_coz(str(val)).strip()
    except (IndexError, KeyError, TypeError):
        return ""


def _gorseli_indir(url: str, g: dict):
    """
    Haber görselini indirir; CDN thumbnail'lerini otomatik 4K/2K ham basın görseline çözer.
    Eşiğin altındaki kalitesiz/küçük/bulanık görseller elenir ve akış sonraki katmana aktarılır.
    """
    adaylar = fetch_article.hd_gorsel_url_coz(url)
    
    en_iyi_foto = None
    en_buyuk_alan = 0
    
    for u in adaylar:
        try:
            cevap = requests.get(
                u,
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
            )
            if cevap.status_code != 200:
                continue
            ham_boyut_kb = len(cevap.content) / 1024
            foto = Image.open(io.BytesIO(cevap.content))
            foto = ImageOps.exif_transpose(foto)
            foto.load()

            # gorsel_kalite denetimi: piksel yoğunluğu, dikey kırpma ölçeği ve netlik
            kaliteli, sebep = gorsel_kalite.gorsel_kalite_denetle(foto, dosya_boyutu_kb=ham_boyut_kb)
            if not kaliteli:
                log.info("Haber görseli adayı elendi (%s): %s", u, sebep)
                continue

            alan = foto.width * foto.height
            if alan > en_buyuk_alan:
                en_iyi_foto = gorsel_kalite.kristal_netlestir(foto.convert("RGB"))
                en_buyuk_alan = alan
        except Exception as e:
            log.debug("görsel adayı indirilemedi %s: %s", u, e)
            continue
            
    if en_iyi_foto:
        return en_iyi_foto
        
    log.info("haber görseli kalite kriterlerini karşılamadı (%s), 4K basın/stok katmanına geçiliyor", url)
    return None


# Son kullanılan stok fotoğraf id'leri. Modül seviyesinde tutuluyor:
# aynı çalıştırma içinde 10 slayt üretiliyor ve her biri için
# veritabanına gitmek gereksiz.
_KULLANILMIS_ONBELLEK: set | None = None
# Bu çağrıda seçilen id — çağıran taraf veritabanına yazsın diye.
_SON_STOK_ID: list = []


def _kullanilmis_stok_idler() -> set:
    """
    Son günlerde kullanılmış Pexels fotoğraf id'leri.

    ⚠️ NEDEN GEREKTİ (21 Ağu 2026): kullanıcı "görseller hep aynı
    şeyler" dedi ve ölçüm doğruladı — aynı fotoğrafçının fotoğrafı 6,
    5 ve 4 kez tekrar etmişti. Aynı arama terimi hep aynı sonucu
    veriyor, biz de hep en yüksek puanlıyı alıyorduk.

    Bu küme fotoğrafı ELEMİYOR, listenin sonuna atıyor: havuz darsa
    hiç fotoğraf bulamamaktansa tekrar iyidir.
    """
    global _KULLANILMIS_ONBELLEK
    if _KULLANILMIS_ONBELLEK is not None:
        return _KULLANILMIS_ONBELLEK
    _KULLANILMIS_ONBELLEK = set()
    try:
        from . import db
        con = db.baglan()
        try:
            _KULLANILMIS_ONBELLEK = {
                str(r[0]) for r in con.execute(
                    "SELECT gorsel_kaynak_id FROM haberler "
                    "WHERE gorsel_kaynak_id IS NOT NULL "
                    "AND cekilme_zamani > datetime('now', '-7 day')")
            }
        finally:
            con.close()
        log.info("stok tekrar engeli: %s fotoğraf daha önce kullanılmış",
                 len(_KULLANILMIS_ONBELLEK))
    except Exception as e:                            # noqa: BLE001
        # Tekrar engeli olmadan da slayt üretilebilir; tur DURMAMALI.
        log.warning("kullanılmış stok id'leri okunamadı: %s", e)
    return _KULLANILMIS_ONBELLEK


def _slayt_metni(haber, alan: str, ayarlar: dict) -> str:
    """
    Slayta basılacak metni içerik filtresinden geçirir.

    ⚠️ 21 Ağu 2026'ya kadar filtre YALNIZCA caption'da çalışıyordu;
    slayt görselindeki başlık ham hâliyle basılıyordu. Kullanıcı benzer
    hesapların görselin ÜSTÜNDE sansürlediğini gösterip aynısını istedi
    (Instagram erişimi için yaygın uygulama).

    `icerik_filtresi.gorselde: false` ile kapatılabilir.
    """
    ham = (haber[alan] if alan in haber.keys() else None) or ""
    if alan == "ig_baslik" and not ham:
        ham = haber["baslik_orj"] or ""
    f = (ayarlar or {}).get("icerik_filtresi", {}) or {}
    if not (f.get("aktif") and f.get("gorselde")):
        return ham
    return filtre.metni_yumusat(ham, f.get("yumusatilacak", []))


# ⚠️ AYNI OLAYIN BAŞKA KAYNAKLARDAKİ FOTOĞRAFLARI (3 Eyl 2026).
#
# Ölçüldü: yayınladığımız haber başına ortalama 3.9 ek kayıt aynı olayı
# işliyor ve her birinin KENDİ fotoğrafı var — hepsi gerçekten o olaydan.
# Dağılım çok anlamlı: rutin haberde 0 ek kaynak, ama BÜYÜK OLAYDA 6-12.
# Yani tam da en çok erişim alan postlarda en çok aday boşta duruyordu.
#
# Ek adayların gerçekten daha iyi olduğu ölçüldü:
#   Silivri gemi çarpışması : seçilen 1200x708, havuzda 1920x1080 vardı
#   Voleybol milli takım    : seçilen 1200x675, havuzda 6000x3375 vardı
KARDES_AZAMI = 3

# Bu genişliğin üstündeki bir og:image zaten yeterince iyi — kardeşleri
# taramaya gerek yok. Fetch başına 0.7-3.8 sn ödüyoruz, bedavaya değil.
MUKEMMEL_GENISLIK = 1600


def kardes_linkler(con, haber, azami: int = KARDES_AZAMI) -> list[str]:
    """
    Aynı olayı işleyen DİĞER kayıtların linkleri, kaynak ağırlığına göre.

    Mükerrer denetiminde kullanılan imza karşılaştırmasının aynısı
    (`secim.konu_imzasi` + ortak özel isim şartı). Orada amaç aynı olayı
    İKİ KEZ YAYINLAMAMAK; burada amaç aynı olayın FOTOĞRAFLARINI
    toplamak. Aynı ölçüt iki işi de görüyor.

    ⚠️ Ortak özel isim ŞART — yalnızca kelime saymak yanlış pozitif
    veriyor ("Resmi Gazete'de yayımlandı" iki alakasız mevzuat haberini
    eşleştiriyordu, bkz. 1j).
    """
    if con is None:
        return []
    try:
        from . import secim
        baslik = haber["baslik_orj"] if "baslik_orj" in haber.keys() else ""
    except Exception:
        return []
    if not baslik:
        return []

    k1, i1 = secim.konu_imzasi(baslik)
    if not i1:
        return []
    # ⚠️ ÖNCE EŞLEŞTİR, SONRA SIRALA — tersi çalışmıyor.
    # İlk yazımda sorgu `ORDER BY agirlik DESC LIMIT 400` idi: en yüksek
    # ağırlıklı 400 satır alınıp içinde eşleşme aranıyordu. Aynı olayın
    # haberleri o dilimin DIŞINDA kalabiliyor. Ölçüldü — Silivri gemi
    # çarpışmasında havuzda 1920x1080 fotoğraf vardı ama bulunamadı,
    # yalnızca 1280x720'ye ulaşılabildi.
    try:
        satirlar = con.execute(
            """SELECT baslik_orj, link, agirlik FROM haberler
               WHERE id != ? AND COALESCE(link,'') != ''
                 AND cekilme_zamani > datetime('now', '-2 day')""",
            (haber["id"],),
        ).fetchall()
    except Exception as e:                            # noqa: BLE001
        log.warning("kardeş haber sorgusu patladı: %s", e)
        return []

    esler = []
    for r in satirlar:
        k2, i2 = secim.konu_imzasi(r["baslik_orj"] or "")
        if len(secim.ortak_kelime(k1, k2)) >= 3 and (i1 & i2):
            esler.append((r["agirlik"] or 0, r["link"]))

    # Ağırlık sıralaması EŞLEŞENLER arasında yapılır. Yüksek ağırlıklı
    # kaynak (AA, TRT, Habertürk) daha büyük fotoğraf koyuyor.
    esler.sort(key=lambda x: -x[0])
    linkler = [link for _, link in esler[:azami]]
    if linkler:
        log.info("aynı olayın %d ek kaynağı bulundu (#%s)", len(linkler), haber["id"])
    return linkler


def _haber_gorseli_alternatifi(haber, g, con, sira: int):
    """
    "Başka fotoğraf" için SIRADAKİ haber görseli.

    ⚠️ NEDEN GEREKTİ (4 Eyl 2026): kullanıcı Galatasaray-Başakşehir
    maçında düşük çözünürlüklü ama DOĞRU fotoğrafı görüp "başka
    fotoğraf"a bastı; 2. denemede 2008 tarihli bir stadyum tifosu,
    3. denemede **bambaşka bir kulübün** (Arjantin) fotoğrafı geldi.

    Kök sebep: `atlanacak > 0` olduğunda og:image katmanı ATLANIYORDU
    ve onunla birlikte **kardeş görsel havuzu** da atlanıyordu. Oysa
    havuz tam bu iş için kurulmuştu: aynı olayı işleyen diğer
    kaynakların fotoğrafları. Kullanıcı "bu yanlış" demiyor, "bu
    kalitesiz" diyor — en iyi kaynağı terk etmek yanlış cevap.

    Sıra: og:image → kardeş 1 → kardeş 2 → … tükenince Commons/Pexels.

    ⚠️ Burada ÇÖZÜNÜRLÜĞE göre değil SIRAYA göre seçiliyor. `atlanacak=0`
    yolundaki "en büyüğü al" davranışı değişmedi; alternatif isteyen
    kullanıcıya her basışta FARKLI bir fotoğraf lazım, en büyüğü değil.
    """
    adaylar = [haber["link"]] + list(kardes_linkler(con, haber))
    if sira >= len(adaylar):
        log.info("haber görseli alternatifi tükendi (%d aday, %d. isteniyor)",
                 len(adaylar), sira)
        return None, None
    link = adaylar[sira]
    try:
        url = fetch_article.og_gorseli_cek(link)
        if not url:
            return None, None
        foto = _gorseli_indir(url, g)
        if foto is None:
            return None, None
        kaynak = _kaynak_adi(con, link)
        log.info("haber görseli alternatifi #%d: %dx%d (%s)",
                 sira, foto.width, foto.height, kaynak)
        return foto, kaynak
    except Exception as e:                            # noqa: BLE001
        log.warning("alternatif haber görseli alınamadı: %s", e)
        return None, None


def _kaynak_adi(con, link: str) -> str:
    """Kardeş görselin geldiği yayın kuruluşu — atıf için."""
    try:
        r = con.execute("SELECT kaynak FROM haberler WHERE link = ?",
                        (link,)).fetchone()
        if r:
            return make_image.kaynak_gosterim_adi(r[0], None)
    except Exception:                                 # noqa: BLE001
        pass
    return "haber kaynağı"


def _en_iyi_haber_gorseli(haber, g: dict, con=None):
    """
    og:image adayları arasından EN İYİSİNİ seçer (ilkini değil).

    ⚠️ ESKİ DAVRANIŞ: yalnızca haberin KENDİ og:image'i deneniyordu; o
    kalite testini geçemezse doğrudan Commons/Pexels'e düşülüyordu.
    Oysa aynı olayın başka kaynaklardaki haberleri havuzda duruyor ve
    fotoğrafları çoğu zaman daha iyi (ölçüldü: 1200x675 yerine
    6000x3375 mevcuttu).

    ⚠️ HIZLI YOL KORUNUYOR: birincil fotoğraf zaten yeterince büyükse
    (MUKEMMEL_GENISLIK) kardeşler hiç taranmıyor. Her kardeş 0.7-3.8 sn
    maliyetli; rutin haberlerde zaten kardeş de yok, yani ek maliyet 0.

    Döner: (foto, atif_kaynak) ya da (None, None).
    """
    if not (g.get("haber_gorseli_kullan") and haber["link"]):
        return None, None

    en_iyi = en_iyi_alan = None
    en_iyi_kaynak = haber["kaynak"]

    try:
        url = fetch_article.og_gorseli_cek(haber["link"])
        if url:
            foto = _gorseli_indir(url, g)
            if foto is not None:
                en_iyi, en_iyi_alan = foto, foto.width * foto.height
                if foto.width >= MUKEMMEL_GENISLIK:
                    log.info("og:image zaten yüksek çözünürlüklü (%dx%d), "
                             "kardeşler taranmıyor", foto.width, foto.height)
                    return en_iyi, en_iyi_kaynak
    except Exception as e:                            # noqa: BLE001
        log.warning("haber görseli alınamadı: %s", e)

    for link in kardes_linkler(con, haber):
        try:
            url = fetch_article.og_gorseli_cek(link)
            if not url:
                continue
            foto = _gorseli_indir(url, g)
            if foto is None:
                continue
            alan = foto.width * foto.height
            if en_iyi is None or alan > en_iyi_alan:
                en_iyi, en_iyi_alan = foto, alan
                log.info("daha iyi kardeş görseli: %dx%d", foto.width, foto.height)
                # Yeterince iyi bulunduysa kalanları tarama — her aday
                # 0.7-3.8 sn maliyetli ve 1600px üstü zaten fazlasıyla
                # yeterli (slayt 1080 basılıyor).
                if foto.width >= MUKEMMEL_GENISLIK:
                    break
        except Exception as e:                        # noqa: BLE001
            log.debug("kardeş görseli alınamadı: %s", e)

    return en_iyi, (en_iyi_kaynak if en_iyi is not None else None)


# ⚠️ VISION DENETİMİ HANGİ KATMANLARDA ÇALIŞIR (3 Eyl 2026)
#
# Yalnızca BELİRLİ BİR KİŞİ/KURUM İDDİASI TAŞIYAN katmanlar denetleniyor.
#   commons / commons_split : "bu fotoğraf X kişisidir" diyor
#   web_haber               : internetten aranmış, hiçbir güvencesi yok
#
# `haber` (og:image) MUAF: yayıncı o fotoğrafı o haber için koymuş,
# konuya bağlılığı yapı gereği garanti. `pexels` de MUAF: temsili
# olduğunu zaten söylüyor (ARŞİV GÖRSELİ ibaresi basılıyor) ve belirli
# bir kişi iddiası taşımıyor — denetlemek 5 sn'yi boşa harcamak olur.
VISION_DENETLENEN = ("commons", "commons_split", "web_haber")

# Reddedilen adaydan sonra kaç alternatif denensin.
#
# ⚠️ 3 DEĞİL 2 — yani yalnızca BİR yeniden deneme. Ölçüldü: Commons'ta
# aynı kişinin adayları çoğu zaman AYNI ÇEKİMDEN geliyor (Melissa
# Vargas'ın dört fotoğrafı da aynı Fenerbahçe maçından), yani bağlam
# uymuyorsa sıradaki de uymuyor. Her deneme ~2 sn Commons + ~5 sn
# Vision; üçüncü deneme nadiren kazandırıp her seferinde 7 sn yiyor.
VISION_AZAMI_DENEME = 2


def _vision_onayi(foto, haber, ayarlar: dict) -> tuple[bool, str]:
    """
    Fotoğrafın içine bakıp habere uygun olup olmadığını sorar.

    Döner: (kullanılabilir_mi, sebep).

    ⚠️ DENETİM YAPILAMAZSA KABUL EDİLİR. Kota dolmuş, ağ patlamış ya da
    anahtar yoksa fotoğraf kullanılır. Gerekçe: denetim bir EK güvence,
    ön şart değil; soramadık diye postu görselsiz bırakmak, denetimden
    geçmemiş bir fotoğraf basmaktan kötü. (`otomatik_onay`daki "şüphede
    reddet" kuralının tersi — orada insan onayı olmadan YAYIN yapılıyor,
    burada yalnızca fotoğraf seçiliyor ve zaten insan onayına gidiyor.)
    """
    g = ayarlar.get("gorsel", {}) or {}
    if not g.get("vision_denetim"):
        return True, ""
    try:
        from . import gorsel_denetim
        sonuc = gorsel_denetim.gorseli_denetle(
            foto,
            _alan(haber, "ig_baslik") or _alan(haber, "baslik_orj"),
            konu=_alan(haber, "gorsel_konu"),
            baglam=_alan(haber, "gorsel_baglam"),
            ayarlar=ayarlar,
        )
    except Exception as e:                            # noqa: BLE001
        log.warning("görsel denetimi patladı, fotoğraf kabul ediliyor: %s", e)
        return True, ""

    if sonuc is None:
        return True, ""                               # soramadık -> kabul

    if not sonuc.get("konuyu_gosteriyor_mu", True):
        return False, "konuyu göstermiyor: " + (sonuc.get("sebep") or "")[:90]
    if not sonuc.get("baglam_uyuyor_mu", True):
        return False, "güncel bağlama uymuyor: " + (sonuc.get("sebep") or "")[:90]
    return True, ""


def arkaplan_sec(haber, ayarlar: dict, zorla_ai: bool = False,
                 atlanacak: int = 0,
                 haber_gorseli_atla: bool = False,
                 con=None) -> tuple[Image.Image, str, str]:
    """
    Habere arka plan bulur. (görüntü, katman_adı, atıf_metni) döner.

    Katmanlar tek tek denenip ilk tutan alınıyor. Bir katman patlarsa
    (ağ hatası, kota, bozuk dosya) sonrakine geçiliyor — görsel
    bulunamadı diye postun kaçmaması gerekiyor.

    ⚠️ `zorla_ai` ve `atlanacak` — TELEGRAM DÜĞMELERİ İÇİN (20 Ağu 2026).

    Bu iki parametre eklenene kadar "🎨 AI ile üret" ve "🔀 Başka
    fotoğraf" düğmeleri HİÇBİR İŞE YARAMIYORDU. `onay_isle` bir
    `gorsel.haberde_ai` bayrağı set ediyordu ama bu fonksiyon o bayrağı
    hiç okumuyordu; her iki düğme de aşağıdaki sabit zinciri baştan
    çalıştırıyordu. Zincirin her adımı deterministik (`adaylar[0]`,
    rastgelelik yok), dolayısıyla sonuç her seferinde tıpatıp aynıydı.

    `zorla_ai=True`  → zinciri atla, doğrudan Gemini'den görsel üret
    `atlanacak=N`    → Commons/Pexels'te N'inci adayı al (0 = en iyisi)
    `haber_gorseli_atla=True` → og:image katmanını atla, "başka fotoğraf"
                                 düğmesinde haber görseli yerine farklı
                                 kaynak denemek için
    """
    g = ayarlar["gorsel"]
    genislik, yukseklik = g["genislik"], g["yukseklik"]

    # --- AI: kullanıcı açıkça istediyse zinciri atla ---
    if zorla_ai:
        try:
            gorsel = make_image.arkaplan_uret_ai(
                haber["kategori"] or "turkiye", ayarlar)
            if gorsel is not None and gorsel.size != (genislik, yukseklik):
                gorsel = gorsel.resize((genislik, yukseklik), Image.LANCZOS)
            if gorsel is not None:
                log.info("arka plan: AI ile üretildi (#%s)", haber["id"])
                return gorsel, "ai", ""
            log.warning("AI görsel üretemedi, normal zincire düşülüyor")
        except Exception as e:                        # noqa: BLE001
            log.warning("AI görsel hatası (%s), normal zincire düşülüyor", e)

    # --- 0.5) Haberin kendi görseli (og:image) ---
    #
    # ⚠️ "BAŞKA FOTOĞRAF" ARTIK ÖNCE KARDEŞLERİ GEZİYOR. Eskiden
    # `atlanacak > 0` bu katmanı komple atlıyordu ve kullanıcı ikinci
    # basışta doğrudan Commons/Pexels'e düşüyordu — ölçüldü (4 Eyl):
    # doğru ama düşük çözünürlüklü fotoğraf → 2008 tarihli tifo →
    # başka kulübün fotoğrafı. Kullanıcı "bu yanlış" demiyor, "bu
    # kalitesiz" diyor; en iyi kaynağı terk etmek yanlış cevap.
    if not haber_gorseli_atla and atlanacak == 0:
        foto, foto_kaynak = _en_iyi_haber_gorseli(haber, g, con)
        if foto is not None:
            return (
                make_image.fotograftan_arkaplan(foto, genislik, yukseklik),
                "haber",
                f"Foto: {foto_kaynak}",
            )
    elif atlanacak > 0 and con is not None:
        foto, foto_kaynak = _haber_gorseli_alternatifi(haber, g, con, atlanacak)
        if foto is not None:
            return (
                make_image.fotograftan_arkaplan(foto, genislik, yukseklik),
                "haber",
                f"Foto: {foto_kaynak}",
            )

    # --- YÖNLENDİRME: brief hangi kaynağı işaret ediyor? (3 Eyl 2026) ---
    #
    # ⚠️ NEDEN GEREKTİ: ölçüldü, bugünkü prompt `gorsel_konu`yu DOĞRU
    # üretiyor (6 haberin 6'sı), ama 6 briefin 5'i yine genel Pexels
    # stoğunda bitiyordu. Sebep brief değil, brief'in KULLANILMAMASIydı:
    # her haber aynı sabit zincire sokuluyor, "bu tarifi hangi kaynak
    # karşılayabilir" diye hiç sorulmuyordu.
    #
    # `olay` tipinde (yangın, sel, kaza, zam, sınav, mevzuat) ortada
    # aranacak bir kişi ya da kurum YOKTUR. Commons'a sormak iki
    # zarar veriyor: ~5-10 saniye boşa gidiyor VE gevşek eşleşme yanlış
    # fotoğraf getirebiliyor ("İSKİ" -> Macar sanatçı portresi vakası).
    # Doğrusu doğrudan temsili fotoğrafa gitmek.
    #
    # ⚠️ og:image bundan MUAF — yangının haberinde yayıncının koyduğu
    # fotoğraf gerçekten o yangının fotoğrafı. Yönlendirme yalnızca
    # Commons katmanını atlıyor.
    #
    # Tip bilinmiyorsa (eski kayıtlar, model şemayı ihlal etti) eski
    # davranış sürüyor: her katman sırayla denenir. Sessizce yanlış
    # kaynağa gitmektense fazladan denemek yeğdir.
    ozne_tipi = _alan(haber, "gorsel_ozne_tipi")
    commons_atla = ozne_tipi == "olay"
    if commons_atla:
        log.info("brief 'olay' diyor -> Commons atlanıyor, temsili fotoğrafa gidiliyor (#%s)",
                 _alan(haber, "id"))

    # --- 1) Commons: İkili Aktör (Split-Screen) veya Tek Kişi ---
    ikili = _alan(haber, "gorsel_ikili")
    if ikili and atlanacak == 0 and not commons_atla:
        try:
            import json
            if isinstance(ikili, str):
                ikili = json.loads(ikili)
            if isinstance(ikili, list) and len(ikili) >= 2:
                sonuc_ikili = fetch_photo.iki_portre_ara(ikili[0], ikili[1])
                if sonuc_ikili:
                    img1, img2, atif_ikili = sonuc_ikili
                    return (
                        make_image.split_portre_arkaplan(img1, img2, genislik, yukseklik),
                        "commons_split",
                        atif_ikili,
                    )
        except Exception as e:
            log.warning("ikili portre katmanı patladı: %s", e)

    konu = _alan(haber, "gorsel_konu")
    if konu and not commons_atla:
        try:
            # ⚠️ Reddedilen aday varsa SIRADAKİNİ dene, doğrudan alt
            # katmana düşme: Commons'ta aynı kişinin başka bağlamda
            # fotoğrafı olabiliyor (Hakan Fidan'da 2024 yerine 2026
            # karesi bulunmuştu).
            for ek in range(VISION_AZAMI_DENEME):
                sonuc = fetch_photo.konu_icin_fotograf(
                    konu, atlanacak=atlanacak + ek,
                    baglam=_alan(haber, "gorsel_baglam"))
                if not sonuc:
                    if ek == 0:
                        log.info("Commons'ta bulunamadı: %s", konu)
                    break
                foto, kayit = sonuc
                uygun, sebep = _vision_onayi(foto, haber, ayarlar)
                if uygun:
                    return (
                        make_image.fotograftan_arkaplan(foto, genislik, yukseklik),
                        "commons",
                        fetch_photo.atif_metni(kayit),
                    )
                log.info("Commons adayı #%d Vision denetiminden geçemedi (%s)",
                         atlanacak + ek, sebep)
        except Exception as e:
            log.warning("Commons katmanı patladı (%s): %s", konu, e)

    # --- 2) Pexels: temsili fotoğraf ---
    _SON_STOK_ID.clear()
    terim = _alan(haber, "gorsel_temsili")
    if terim:
        try:
            sonuc = fetch_stock.konu_icin_fotograf(
                terim, atlanacak=atlanacak,
                kullanilmis=_kullanilmis_stok_idler()
            )
            if sonuc:
                foto, kayit = sonuc
                _SON_STOK_ID.append(kayit.get("id"))
                return (
                    make_image.fotograftan_arkaplan(foto, genislik, yukseklik),
                    "pexels",
                    fetch_stock.atif_metni(kayit),
                )
            log.info("Pexels'te bulunamadı: %s", terim)
        except Exception as e:
            log.warning("Pexels katmanı patladı (%s): %s", terim, e)

    # --- 2.5) SON ÇARE: internette görsel arama ---
    #
    # ⚠️ VARSAYILAN OLARAK KAPALI (`gorsel.web_gorsel_ara`). Gerekçe ve
    # ölçümler config.yaml'de. Kısaca: bu katmanın döndürdüğü fotoğrafın
    # haberi anlattığına dair hiçbir güvencemiz yok ve metin tabanlı
    # alaka kapısı bu kusuru ÇÖZMÜYOR (ölçüldü: 6/6 yanlış aday geçti).
    #
    # ⚠️ ESKİDEN ZİNCİRİN BİRİNCİ SIRASINDAYDI — yani haberin kendi
    # og:image'inin bile önünde. 3 Eyl 2026'da sona alındı: og:image
    # konuya garantili bağlı, bu değil.
    #
    # Açılırsa iki şey ZORUNLU: atıf (kaynak alan adı) ve slaytta
    # "ARŞİV GÖRSELİ" ibaresi (bkz. ARSIV_KATMANLARI).
    if g.get("web_gorsel_ara") and not haber_gorseli_atla:
        try:
            web_sonuc = fetch_web_image.haber_icin_fotograf(
                haber, atlanacak=atlanacak)
            if web_sonuc:
                foto, web_kayit = web_sonuc
                atif = fetch_web_image.atif_metni(web_kayit)
                # Atıf üretilemiyorsa BASMIYORUZ. Kaynağı bilinmeyen bir
                # fotoğrafı yayınlamak, hiç fotoğraf koymamaktan kötü.
                uygun, sebep = _vision_onayi(foto, haber, ayarlar)
                if not uygun:
                    log.info("internet görseli Vision denetiminden geçemedi (%s)",
                             sebep)
                elif atif:
                    log.info("arka plan: internet aramasi (son çare) — %s", atif)
                    return (
                        make_image.fotograftan_arkaplan(
                            foto, genislik, yukseklik),
                        "web_haber",
                        atif,
                    )
                log.warning("web görseli atıfsız geldi, basılmıyor")
        except Exception as e:                        # noqa: BLE001
            log.warning("internet görsel araması patladı: %s", e)

    # --- 2.6) Gemini AI: hiçbir gerçek fotoğraf bulunamadıysa üret ---
    try:
        gorsel_ai = make_image.arkaplan_uret_ai(_alan(haber, "kategori") or "turkiye", ayarlar)
        if gorsel_ai is not None:
            if gorsel_ai.size != (genislik, yukseklik):
                gorsel_ai = gorsel_ai.resize((genislik, yukseklik), Image.LANCZOS)
            log.info("arka plan: Gemini AI ile üretildi (#%s)", _alan(haber, "id"))
            return gorsel_ai, "ai", ""
    except Exception as e:
        log.warning("AI arka plan üretimi hatası: %s", e)

    # --- 3) Gradyan: her zaman çalışır ---
    return (
        make_image.arkaplan_uret_yedek(haber["kategori"], genislik, yukseklik, g),
        "gradyan",
        "",
    )


def _secimi_uygula(haber, atlanacak, haber_gorseli_atla):
    """
    Kullanıcının "başka fotoğraf" seçimini kayıttan okur.

    ⚠️ NEDEN GEREKTİ (3 Eyl 2026): seçim `gorsel_deneme` kolonunda
    saklanıyor ama slaytı yeniden üreten **20'den fazla çağrı yeri**
    vardı ve çoğu bu kolonu okumuyordu. Sonuç: kullanıcı "başka
    fotoğraf" diyor, sonra yayın anında (URL onarımı, video karesi
    üretimi vb.) slayt yeniden üretiliyor ve ORİJİNAL fotoğraf geri
    geliyor. Kullanıcı bildirdi: *"başka fotolarla yeniden üret dedim
    ve onu paylaştığımda oluşturduğu videoları eski görüntülerle
    oluşturdu"*.

    Tek tek çağrı yerlerini yamalamak yerine seçim BURADA, tek kapıda
    uygulanıyor — `aday.uygun_mu` ile aynı gerekçe: bu projedeki
    kusurların çoğu "kural doğru ama bir yerde uygulanmamış" hatası.

    `atlanacak=None` (varsayılan) = kayıttan oku.
    `atlanacak=<sayı>`            = çağıran açıkça belirtti, o kazanır.
    """
    if atlanacak is None:
        atlanacak = 0
        try:
            atlanacak = int(_alan(haber, "gorsel_deneme") or 0)
        except (TypeError, ValueError):
            atlanacak = 0
        if atlanacak:
            log.info("kayıtlı fotoğraf seçimi uygulanıyor (gorsel_deneme=%s)",
                     atlanacak)
    # Kullanıcı "başka fotoğraf" dediyse haberin kendi görseli de atlanır
    # (yoksa düğme aynı og:image'i geri getirir).
    return atlanacak, (haber_gorseli_atla or atlanacak > 0)


def slayt_uret(haber, ayarlar: dict,
               zorla_ai: bool = False,
               atlanacak: int | None = None,
               haber_gorseli_atla: bool = False,
               sira: int = 1,
               son_slayt: bool = False,
               con=None) -> tuple[Path, str, str]:
    """
    Tek bir haberin slaytını üretip diske yazar.
    """
    g = ayarlar["gorsel"]
    make_image.CIKTI_KLASORU.mkdir(parents=True, exist_ok=True)

    atlanacak, haber_gorseli_atla = _secimi_uygula(
        haber, atlanacak, haber_gorseli_atla)
    arkaplan, katman, atif = arkaplan_sec(
        haber, ayarlar, zorla_ai=zorla_ai, atlanacak=atlanacak,
        haber_gorseli_atla=haber_gorseli_atla, con=con)

    # Veri Kartı / Mini İnfografik Rozeti
    veri_karti = None
    v_etiket = _alan(haber, "veri_karti_etiket")
    v_yeni = _alan(haber, "veri_karti_yeni")
    if v_etiket and v_yeni:
        km = _alan(haber, "makale_metni") or _alan(haber, "ozet_orj")
        baslik = _alan(haber, "ig_baslik") or _alan(haber, "baslik_orj") or ""
        ozet = _alan(haber, "slayt_ozet") or ""
        if dogrula.veri_karti_dogrula(_alan(haber, "veri_karti_eski"), v_yeni, km):
            v_eski = _alan(haber, "veri_karti_eski") or ""
            v_yon = _alan(haber, "veri_karti_yon") or "artis"
            # ⚠️ ÖNCESİ YOKSA YÖN OLMAZ (5 Eyl 2026). "artis"/"azalis"
            # üçgen (▲/▼) bastırıyor ve bu bir DEĞİŞİM iddiasıdır; ama
            # `eski` boşken kıyaslanacak bir şey yok. Ölçüldü: *"ChatGPT
            # çöktü — Etkilenen Bileşen: → 19 (artış)"*. 19 bileşen
            # neye göre artmış? Hiçbir şeye. Model yönü varsayılan
            # olarak dolduruyor, kod düzeltiyor.
            if not v_eski and v_yon in ("artis", "azalis"):
                log.info("veri kartında öncesi yok, yön '%s' -> 'notr' (#%s)",
                         v_yon, _alan(haber, "id"))
                v_yon = "notr"
            gecici_kart = {
                "etiket": v_etiket,
                "yeni": v_yeni,
                "eski": v_eski,
                "yon": v_yon,
            }
            if not dogrula.veri_karti_baslikta_var_mi(gecici_kart, baslik, ozet):
                veri_karti = gecici_kart
            else:
                log.info("Veri kartı başlıkta/özette zaten var, atlandı #%s", _alan(haber, "id"))

    gorsel = make_image.yaziyi_bas(
        arkaplan,
        _slayt_metni(haber, "ig_baslik", ayarlar),
        make_image.kaynak_gosterim_adi(haber["kaynak"], ayarlar),
        ayarlar,
        ozet=_slayt_metni(haber, "slayt_ozet", ayarlar) or None,
        arsiv_ibaresi=katman in ARSIV_KATMANLARI,
        ulke_kodu=_alan(haber, "ulke_kodu") or None,
        ulke_adi=_alan(haber, "ulke_adi") or None,
        kategori=haber["kategori"] or "",
        son_slayt=son_slayt,
        veri_karti=veri_karti,
    )

    yol = make_image.CIKTI_KLASORU / f"slayt-{haber['id']}.jpg"
    exif_meta = make_image.sirali_exif(sira=sira)
    # Instagram PNG kabul etmiyor — JPEG şart (subsampling=0 ile kristal netlik)
    gorsel.save(yol, "JPEG", quality=_kalite(g, katman), subsampling=0, optimize=True, exif=exif_meta)

    # 9:16 Dikey Story / Reels slaytı (Telegram albümlerinde ve Story'de kullanılır)
    story_yol = make_image.CIKTI_KLASORU / f"story-{haber['id']}.jpg"
    try:
        story_gorsel = make_image.story_haber(
            _slayt_metni(haber, "ig_baslik", ayarlar),
            _slayt_metni(haber, "slayt_ozet", ayarlar),
            make_image.kaynak_gosterim_adi(haber["kaynak"], ayarlar),
            ayarlar,
            arkaplan=(arkaplan.copy() if katman in FOTOGRAFLI_KATMANLAR else None),
            kategori=haber["kategori"] or "turkiye",
            ulke_kodu=_alan(haber, "ulke_kodu") or None,
            ulke_adi=_alan(haber, "ulke_adi") or None,
            son_slayt=son_slayt,
        )
        story_gorsel.save(story_yol, "JPEG", quality=_kalite(g, katman), subsampling=0, optimize=True, exif=exif_meta)
    except Exception as e:
        log.warning("Haber story slaytı üretilemedi #%s: %s", haber["id"], e)
        story_yol = None

    log.info("slayt üretildi [%s] #%s → %s (story: %s)", katman, haber["id"], yol.name, bool(story_yol))
    return yol, katman, atif


def tur_uret(haberler: list, ayarlar: dict, con=None) -> list[dict]:
    """
    Bir turun bütün slaytlarını üretir.

    Bir haberin slaytı patlarsa o haber atlanıyor, tur devam ediyor —
    9 haberlik bir carousel tek bir bozuk fotoğraf yüzünden iptal olmasın.
    `con` verilirse seçilen katman `gorsel_kaynagi` kolonuna yazılıyor;
    hangi katmanın ne sıklıkta tuttuğunu sonradan ölçebilmek için.
    """
    g = ayarlar["gorsel"]
    sonuclar = []
    toplam_slayt = min(len(haberler), g["slayt_sayisi"])

    for idx, haber in enumerate(haberler[: g["slayt_sayisi"]], start=1):
        try:
            is_son = (idx == toplam_slayt)
            yol, katman, atif = slayt_uret(
                haber, ayarlar, sira=idx, son_slayt=is_son, con=con)
        except Exception as e:
            log.error("slayt üretilemedi #%s: %s", haber["id"], e)
            continue

        story_yol = make_image.CIKTI_KLASORU / f"story-{haber['id']}.jpg"

        if con is not None:
            # Atıf da yazılıyor: caption yayın anında yeniden kuruluyor ve
            # hazırlık ile onay arasında saatler geçebiliyor. Bellekte
            # tutulsa Commons'ın CC BY atfı yayında kaybolurdu.
            # Stok fotoğraf id'si: aynı fotoğrafın bir daha
            # seçilmemesi için saklanıyor. Pexels dışı katmanlarda
            # boş kalıyor, COALESCE eski değeri korumasın diye
            # doğrudan yazılıyor.
            stok_id = _SON_STOK_ID.pop() if _SON_STOK_ID else None
            con.execute(
                "UPDATE haberler SET gorsel_kaynak_id = ?, "
                "gorsel_yolu = ?, gorsel_kaynagi = ?, "
                "gorsel_atif = ? WHERE id = ?",
                (stok_id, str(yol), katman, atif, haber["id"]),
            )
            con.commit()

        sonuclar.append(
            {
                "id": haber["id"],
                "yol": yol,
                "story_yol": story_yol if story_yol.exists() else yol,
                "katman": katman,
                "atif": atif,
            }
        )

    return sonuclar


_AYLAR = ("ocak", "şubat", "mart", "nisan", "mayıs", "haziran", "temmuz",
          "ağustos", "eylül", "ekim", "kasım", "aralık")


def _yil_ya_da_tarih_mi(deger: str) -> bool:
    """
    Vurgu rakamı çıplak bir YIL ya da TARİH mi?

    ⚠️ Ölçü/miktar taşıyan değerler ("2023 kişi", "%45") vurgu olabilir;
    çıplak yıl ("2023") ve tarih ("5 Eylül") olamaz — büyük puntoda
    basılınca okuyucuya bir büyüklük duygusu vermiyorlar.
    """
    s = (deger or "").strip()
    if not s:
        return False
    if re.fullmatch(r"(19|20)\d{2}\.?", s):          # 2023, 1999.
        return True
    kucuk = s.casefold()
    if any(ay in kucuk for ay in _AYLAR):             # "5 Eylül"
        return True
    return False


def son_dakika_uret(haber, ayarlar: dict, con=None,
                    zorla_ai: bool = False,
                    atlanacak: int | None = None,
                    haber_gorseli_atla: bool = False) -> list[dict]:
    """
    Son dakika postunun iki slaytını üretir.

    Slayt 1: normal haber slaytı (fotoğraf + başlık + özet) — dikkat çeker
    Slayt 2: detay slaytı (sade zemin + uzun açıklama) — bilgi verir

    Instagram carousel en az 2 görsel istediği için 2 zaten alt sınır.
    İşbölümü bilinçli: birincisi akışta durdurur, ikincisi haberi anlatır.
    """
    g = ayarlar["gorsel"]
    make_image.CIKTI_KLASORU.mkdir(parents=True, exist_ok=True)

    # --- Slayt 1: normal haber slaytı ---
    # Arka planı BURADA seçiyoruz çünkü story'de de aynı HAM fotoğraf
    # lazım. `slayt_uret` yalnızca yazılmış slaytı döndürüyor; story'yi
    # ondan üretmeye kalkmak yazının üstüne yazı basmak oluyor —
    # 17 Ağu 2026'da yayınlanan story'de tam olarak bu oldu.
    atlanacak, haber_gorseli_atla = _secimi_uygula(
        haber, atlanacak, haber_gorseli_atla)
    ham_arkaplan, katman, atif = arkaplan_sec(
        haber, ayarlar, zorla_ai=zorla_ai, atlanacak=atlanacak,
        haber_gorseli_atla=haber_gorseli_atla, con=con)

    veri_karti = None
    v_etiket = _alan(haber, "veri_karti_etiket")
    v_yeni = _alan(haber, "veri_karti_yeni")
    if v_etiket and v_yeni:
        km = _alan(haber, "makale_metni") or _alan(haber, "ozet_orj")
        baslik = _alan(haber, "ig_baslik") or _alan(haber, "baslik_orj") or ""
        ozet = _alan(haber, "slayt_ozet") or ""
        if dogrula.veri_karti_dogrula(_alan(haber, "veri_karti_eski"), v_yeni, km):
            v_eski = _alan(haber, "veri_karti_eski") or ""
            v_yon = _alan(haber, "veri_karti_yon") or "artis"
            # ⚠️ ÖNCESİ YOKSA YÖN OLMAZ (5 Eyl 2026). "artis"/"azalis"
            # üçgen (▲/▼) bastırıyor ve bu bir DEĞİŞİM iddiasıdır; ama
            # `eski` boşken kıyaslanacak bir şey yok. Ölçüldü: *"ChatGPT
            # çöktü — Etkilenen Bileşen: → 19 (artış)"*. 19 bileşen
            # neye göre artmış? Hiçbir şeye. Model yönü varsayılan
            # olarak dolduruyor, kod düzeltiyor.
            if not v_eski and v_yon in ("artis", "azalis"):
                log.info("veri kartında öncesi yok, yön '%s' -> 'notr' (#%s)",
                         v_yon, _alan(haber, "id"))
                v_yon = "notr"
            gecici_kart = {
                "etiket": v_etiket,
                "yeni": v_yeni,
                "eski": v_eski,
                "yon": v_yon,
            }
            if not dogrula.veri_karti_baslikta_var_mi(gecici_kart, baslik, ozet):
                veri_karti = gecici_kart
            else:
                log.info("Veri kartı başlıkta/özette zaten var, atlandı #%s", _alan(haber, "id"))

    # ig_caption ve detay metinleri
    detay = (_alan(haber, "detay_metni")
             or _alan(haber, "ig_caption")
             or _alan(haber, "slayt_ozet")
             or _alan(haber, "ozet_orj"))

    etiket_esigi = ayarlar["genel"].get("son_dakika_etiket_esigi", 9)
    son_dakika_mi = (haber["onem_puani"] or 0) >= etiket_esigi

    vurgu = None
    ham_vurgu = _alan(haber, "vurgu_sayi")
    if ham_vurgu:
        baslik_metni = haber["ig_baslik"] or haber["baslik_orj"] or ""
        if dogrula._sayilar(ham_vurgu) & dogrula._sayilar(baslik_metni):
            log.info("vurgu rakamı başlıkta zaten var, atlandı #%s", haber["id"])
        elif _yil_ya_da_tarih_mi(ham_vurgu):
            # ⚠️ YIL VE TARİH ÇARPICI SAYI DEĞİLDİR (5 Eyl 2026).
            # Vurgu, sayfanın en üstünde 92 puntoya kadar çıkan görsel
            # çapa; oraya "2023" ya da "5 Eylül" basmak okuyucuya
            # hiçbir şey söylemiyor. Ölçüldü: 12 vurgunun 2'si böyleydi
            # (Satürn haberinde "2023 / oluşum başlangıcı", voleybolda
            # "5 Eylül / Sırbistan maçı"). Sayının kendisi doğru ama
            # ÇARPICI değil — o alan ölçü/miktar için.
            log.info("vurgu rakamı yıl/tarih (%s), atlandı #%s",
                     ham_vurgu, haber["id"])
        else:
            vurgu = (ham_vurgu, _alan(haber, "vurgu_etiket"))

    alinti = None
    ham_alinti = _alan(haber, "alinti")
    if ham_alinti:
        kaynak = _alan(haber, "makale_metni") or _alan(haber, "ozet_orj")
        if dogrula.alintiyi_denetle(ham_alinti, kaynak):
            alinti = (ham_alinti, _alan(haber, "alinti_sahibi"))
        else:
            log.warning("alıntı kaynakta doğrulanamadı, atlandı #%s", haber["id"])

    trend_karti = None
    try:
        from src import sparkline
        trend_karti = sparkline.haber_icin_trend_karti(haber)
    except Exception as e:
        log.warning("trend kartı üretilemedi: %s", e)

    sayfalar = make_image.detay_sayfalara_bol(
        detay, ayarlar,
        vurgu=vurgu,
        alinti=alinti,
        neden_onemli=_alan(haber, "neden_onemli"),
        sirada_ne_var=_alan(haber, "sirada_ne_var"),
        trend_karti=trend_karti,
        sana_etkisi=_alan(haber, "sana_etkisi"),
    )

    # --- %100 SAF NATIVE 9:16 (1080x1920) ÜRETİM (4:5 tamamen kaldırıldı) ---
    # Slayt 1: 1080x1920 Native Kapak Slaytı
    gorsel_kapak = make_image.story_haber(
        _slayt_metni(haber, "ig_baslik", ayarlar),
        _slayt_metni(haber, "slayt_ozet", ayarlar),
        make_image.kaynak_gosterim_adi(haber["kaynak"], ayarlar),
        ayarlar,
        arkaplan=(ham_arkaplan.copy() if katman in FOTOGRAFLI_KATMANLAR else None),
        kategori=haber["kategori"] or "turkiye",
        son_dakika=son_dakika_mi,
        ulke_kodu=_alan(haber, "ulke_kodu") or None,
        ulke_adi=_alan(haber, "ulke_adi") or None,
        veri_karti=veri_karti,
        arsiv_ibaresi=(katman in ARSIV_KATMANLARI),
    )
    yol_kapak = make_image.CIKTI_KLASORU / f"story-{haber['id']}.jpg"
    gorsel_kapak.save(yol_kapak, "JPEG", quality=_kalite(g, katman), subsampling=0, optimize=True)

    # Slayt 2 & 3: 1080x1920 Native Detay & Analiz Slaytları
    story_detay_yollari = []
    for i, satirlar in enumerate(sayfalar, start=1):
        story_d = make_image.story_detay(
            _slayt_metni(haber, "ig_baslik", ayarlar),
            detay,
            make_image.kaynak_gosterim_adi(haber["kaynak"], ayarlar),
            ayarlar,
            arkaplan=(ham_arkaplan.copy() if katman in FOTOGRAFLI_KATMANLAR else None),
            kategori=haber["kategori"] or "turkiye",
            son_dakika=son_dakika_mi and i == 1,
            ulke_kodu=_alan(haber, "ulke_kodu") or None,
            ulke_adi=_alan(haber, "ulke_adi") or None,
            satirlar=satirlar,
            sayfa=i,
            toplam_sayfa=len(sayfalar),
            arsiv_ibaresi=(katman in ARSIV_KATMANLARI),
        )
        ek = "" if len(sayfalar) == 1 else f"-{i}"
        s_detay_yol = make_image.CIKTI_KLASORU / f"story-{haber['id']}-detay{ek}.jpg"
        story_d.save(s_detay_yol, "JPEG", quality=_kalite(g, katman), subsampling=0, optimize=True)
        story_detay_yollari.append(s_detay_yol)

    log.info("son dakika %%100 native 9:16 slaytları üretildi #%s [%s + %d detay]",
             haber["id"], katman, len(story_detay_yollari))

    if con is not None:
        con.execute(
            "UPDATE haberler SET gorsel_yolu = ?, gorsel_kaynagi = ?, "
            "gorsel_atif = ? WHERE id = ?",
            (str(yol_kapak), katman, atif, haber["id"]),
        )
        con.commit()

    sonuc = [{"id": haber["id"], "yol": yol_kapak, "katman": katman, "atif": atif}]
    sonuc += [{"id": haber["id"], "yol": y, "katman": "detay", "atif": ""}
              for y in story_detay_yollari]
    return sonuc


def atif_bloku(sonuclar: list[dict]) -> str:
    """
    Caption'ın sonuna eklenecek fotoğraf atıflarını hazırlar.

    Aynı atıf birden fazla slaytta çıkabiliyor; tekrarı ayıklıyoruz.
    Hiç fotoğraf kullanılmadıysa (hepsi gradyan) boş dönüyor ki
    caption'da sebepsiz bir başlık durmasın.
    """
    goruldu, satirlar = set(), []
    for s in sonuclar:
        atif = (s.get("atif") or "").strip()
        if atif and atif not in goruldu:
            goruldu.add(atif)
            satirlar.append(atif)

    if not satirlar:
        return ""
    return "\n\nGörseller:\n" + "\n".join(satirlar)
