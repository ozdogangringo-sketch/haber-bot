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

import requests
from PIL import Image

from . import filtre, dogrula, fetch_article, fetch_photo, fetch_stock, make_image

log = logging.getLogger(__name__)

# Arka planında GERÇEK FOTOĞRAF olan katmanlar.
#
# ⚠️ YENİ FOTOĞRAF KATMANI EKLERKEN BURAYA DA EKLE. Katman adları koda
# birden çok yerde gömülüydü ve "haber" (og:image) katmanı eklenince
# story'nin listesi güncellenmedi: haber fotoğrafı kullanılan postlarda
# story fotoğrafsız çıktı. Tek liste tutmak bunu tekrarlanmaz kılıyor.
FOTOGRAFLI_KATMANLAR = ("haber", "commons", "pexels")


def _kalite(g: dict, katman: str) -> int:
    """
    JPEG kalitesi katmana göre seçiliyor.

    ⚠️ Fotoğraf arka planlı slaytlarda yüksek kalite gözle görülür fark
    yaratıyor; düz zeminli sayfalarda (detay slaytları) yaratmıyor —
    orada yalnızca dosyayı şişiriyor. Instagram sınırı 8 MB, bizim
    slaytlar ~200 KB, yani fotoğraflı tarafta bol alan var.
    """
    if katman in FOTOGRAFLI_KATMANLAR:
        return g.get("jpeg_kalite_foto", g["jpeg_kalite"])
    return g["jpeg_kalite"]

# Bunlardan hangilerinde "ARŞİV GÖRSELİ" ibaresi basılsın?
# `haber` katmanı HARİÇ: o görsel olayın kendi fotoğrafı, arşiv değil.
ARSIV_KATMANLARI = ("commons", "pexels")


def _alan(haber, ad: str) -> str:
    """
    Haber kaydından güvenli alan okuma.

    sqlite3.Row'da olmayan bir kolona erişmek IndexError atıyor; eski
    bir veritabanında yeni kolonlar henüz yokken çökmemek için sarmaladık.
    """
    try:
        return (haber[ad] or "").strip()
    except (IndexError, KeyError):
        return ""


def _gorseli_indir(url: str, g: dict):
    """
    Haber görselini indirir; CDN thumbnail'lerini otomatik 4K/2K ham basın görseline çözer.
    Eşiğin altındaki kalitesiz/küçük görseller elenir ve akış bir sonraki katmana (Pexels/Commons) aktarılır.
    """
    asgari = g.get("haber_gorseli_asgari_genislik", 800)
    asgari_y = g.get("haber_gorseli_asgari_yukseklik", 500)
    
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
            foto = Image.open(io.BytesIO(cevap.content))
            foto.load()
            alan = foto.width * foto.height
            if foto.width >= asgari and foto.height >= asgari_y:
                if alan > en_buyuk_alan:
                    en_iyi_foto = foto.convert("RGB")
                    en_buyuk_alan = alan
        except Exception as e:
            log.debug("görsel adayı indirilemedi %s: %s", u, e)
            continue
            
    if en_iyi_foto:
        return en_iyi_foto
        
    log.info("haber görseli küçük veya indirilemedi (%s, asgari %sx%s), atlanıyor",
             url, asgari, asgari_y)
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


def arkaplan_sec(haber, ayarlar: dict, zorla_ai: bool = False,
                 atlanacak: int = 0,
                 haber_gorseli_atla: bool = False) -> tuple[Image.Image, str, str]:
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

    # --- 0) Haberin kendi görseli (og:image) ---
    #
    # ⚠️ TELİF RİSKİ TAŞIYOR, BİLİNÇLİ TERCİH (18 Ağu 2026). Bu görseller
    # çoğu zaman ajans fotoğrafı ve telifi ajansa ait; "kaynak belirtmek"
    # izin yerine geçmiyor. Kullanıcı riski bilerek kullanmayı seçti.
    # Kapatmak için: `gorsel.haber_gorseli_kullan: false`.
    #
    # NEDEN İLK SIRADA: haberin KENDİ olayını gösteren tek görsel bu.
    # Commons kişi portresi, Pexels temsili fotoğraf veriyor; ikisi de
    # "o an" değil. Görsel gücü en yüksek katman burası.
    #
    # ⚠️ `haber_gorseli_atla`: "başka fotoğraf" düğmesinde bu katman
    # ATLANIYOR. og:image deterministik — her seferinde aynı URL'yi
    # döndürüyor. Kullanıcı "başka" deyince farklı bir sonuç bekliyor;
    # og:image'ı tekrar denemek aynı görseli getirir. Atlayınca
    # Commons/Pexels'e düşüyor ve gerçekten farklı bir görsel geliyor.
    if (not haber_gorseli_atla and atlanacak == 0
            and g.get("haber_gorseli_kullan") and haber["link"]):
        try:
            url = fetch_article.og_gorseli_cek(haber["link"])
            if url:
                foto = _gorseli_indir(url, g)
                if foto:
                    return (
                        make_image.fotograftan_arkaplan(
                            foto, genislik, yukseklik),
                        "haber",
                        f"Foto: {haber['kaynak']}",
                    )
        except Exception as e:
            log.warning("haber görseli alınamadı: %s", e)

    # --- 1) Commons: tanınmış kişi/kurum ---
    konu = _alan(haber, "gorsel_konu")
    if konu:
        try:
            sonuc = fetch_photo.konu_icin_fotograf(konu, atlanacak=atlanacak)
            if sonuc:
                foto, kayit = sonuc
                return (
                    make_image.fotograftan_arkaplan(foto, genislik, yukseklik),
                    "commons",
                    fetch_photo.atif_metni(kayit),
                )
            log.info("Commons'ta bulunamadı: %s", konu)
        except Exception as e:
            log.warning("Commons katmanı patladı (%s): %s", konu, e)

    # --- 2) Pexels: temsili fotoğraf ---
    # ⚠️ Liste her çağrıda temizleniyor: `tur_uret` bu değeri slayt
    # başına okuyor, eskisi kalırsa yanlış habere yazılır.
    _SON_STOK_ID.clear()
    terim = _alan(haber, "gorsel_temsili")
    if terim:
        try:
            sonuc = fetch_stock.konu_icin_fotograf(
                terim, atlanacak=atlanacak,
                kullanilmis=_kullanilmis_stok_idler())
            if sonuc:
                foto, kayit = sonuc
                # Bu fotoğrafı bir daha seçmeyelim diye işaretliyoruz.
                if kayit.get("id"):
                    _kullanilmis_stok_idler().add(str(kayit["id"]))
                    _SON_STOK_ID.append(str(kayit["id"]))
                return (
                    make_image.fotograftan_arkaplan(foto, genislik, yukseklik),
                    "pexels",
                    fetch_stock.atif_metni(kayit),
                )
            log.info("Pexels'te bulunamadı: %s", terim)
        except Exception as e:
            log.warning("Pexels katmanı patladı (%s): %s", terim, e)

    # --- 3) Gradyan: her zaman çalışır ---
    return (
        make_image.arkaplan_uret_yedek(haber["kategori"], genislik, yukseklik, g),
        "gradyan",
        "",
    )


def slayt_uret(haber, ayarlar: dict, zorla_ai: bool = False,
               atlanacak: int = 0,
               haber_gorseli_atla: bool = False) -> tuple[Path, str, str]:
    """
    Tek bir haberin slaytını üretip diske yazar.

    (dosya_yolu, katman_adı, atıf_metni) döner. Atıf metni caption'ın
    sonuna eklenecek — Commons'taki CC BY görselleri için bu hukuken şart,
    Pexels'te zorunlu değil ama veriyoruz.

    `zorla_ai` / `atlanacak` / `haber_gorseli_atla`: Telegram'daki
    görsel değiştirme düğmeleri için — bkz. `arkaplan_sec`.
    """
    g = ayarlar["gorsel"]
    make_image.CIKTI_KLASORU.mkdir(parents=True, exist_ok=True)

    arkaplan, katman, atif = arkaplan_sec(
        haber, ayarlar, zorla_ai=zorla_ai, atlanacak=atlanacak,
        haber_gorseli_atla=haber_gorseli_atla)

    gorsel = make_image.yaziyi_bas(
        arkaplan,
        _slayt_metni(haber, "ig_baslik", ayarlar),
        make_image.kaynak_gosterim_adi(haber["kaynak"], ayarlar),
        ayarlar,
        ozet=_slayt_metni(haber, "slayt_ozet", ayarlar) or None,
        # Fotoğraf katmanlarında görsel o olayın belgesi değil; gradyanda
        # ise ortada fotoğraf yok, ibare anlamsız olurdu.
        arsiv_ibaresi=katman in ARSIV_KATMANLARI,
        ulke_kodu=_alan(haber, "ulke_kodu") or None,
        ulke_adi=_alan(haber, "ulke_adi") or None,
        # Şerit rengi kategoriden geliyor: spor yeşil, ekonomi bronz…
        kategori=haber["kategori"] or "",
    )

    yol = make_image.CIKTI_KLASORU / f"slayt-{haber['id']}.jpg"
    # Instagram PNG kabul etmiyor — JPEG şart (subsampling=0 ile kristal netlik)
    gorsel.save(yol, "JPEG", quality=_kalite(g, katman), subsampling=0, optimize=True)

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
        )
        story_gorsel.save(story_yol, "JPEG", quality=_kalite(g, katman), subsampling=0, optimize=True)
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

    for haber in haberler[: g["slayt_sayisi"]]:
        try:
            yol, katman, atif = slayt_uret(haber, ayarlar)
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


def son_dakika_uret(haber, ayarlar: dict, con=None,
                    zorla_ai: bool = False,
                    atlanacak: int = 0) -> list[dict]:
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
    ham_arkaplan, katman, atif = arkaplan_sec(
        haber, ayarlar, zorla_ai=zorla_ai, atlanacak=atlanacak)

    gorsel1 = make_image.yaziyi_bas(
        ham_arkaplan.copy(),
        _slayt_metni(haber, "ig_baslik", ayarlar),
        make_image.kaynak_gosterim_adi(haber["kaynak"], ayarlar),
        ayarlar,
        ozet=_slayt_metni(haber, "slayt_ozet", ayarlar) or None,
        arsiv_ibaresi=katman in ARSIV_KATMANLARI,
        ulke_kodu=_alan(haber, "ulke_kodu") or None,
        ulke_adi=_alan(haber, "ulke_adi") or None,
        # Şerit rengi kategoriden geliyor: spor yeşil, ekonomi bronz…
        kategori=haber["kategori"] or "",
    )
    yol1 = make_image.CIKTI_KLASORU / f"slayt-{haber['id']}.jpg"
    gorsel1.save(yol1, "JPEG", quality=_kalite(g, katman), subsampling=0, optimize=True)

    # --- Slayt 2: detay ---
    # ig_caption zaten haberin 2-3 cümlelik özü; ayrı bir alan üretmek
    # yerine onu kullanıyoruz (ek Gemini çağrısı = ek kota).
    # Uzun anlatım varsa onu kullan; yoksa caption'a düş.
    detay = (_alan(haber, "detay_metni")
             or _alan(haber, "ig_caption")
             or _alan(haber, "slayt_ozet")
             or _alan(haber, "ozet_orj"))

    # Kırmızı "SON DAKİKA" ibaresi yalnızca olağanüstü olaylarda.
    etiket_esigi = ayarlar["genel"].get("son_dakika_etiket_esigi", 9)
    son_dakika_mi = (haber["onem_puani"] or 0) >= etiket_esigi

    # Vurgu rakamı — varsa iri puntoyla basılıyor.
    #
    # TEKRAR ENGELİ: rakam başlıkta zaten geçiyorsa vurgu bloğu aynı
    # bilgiyi ikinci kez veriyor ve sayfayı boş yere işgal ediyor.
    # Gerçek örnek: başlık "…32 kişi tutuklandı" + altında
    # "32 / TUTUKLANAN ŞÜPHELİ SAYISI".
    vurgu = None
    ham_vurgu = _alan(haber, "vurgu_sayi")
    if ham_vurgu:
        baslik_metni = haber["ig_baslik"] or haber["baslik_orj"] or ""
        if dogrula._sayilar(ham_vurgu) & dogrula._sayilar(baslik_metni):
            log.info("vurgu rakamı başlıkta zaten var, atlandı #%s", haber["id"])
        else:
            vurgu = (ham_vurgu, _alan(haber, "vurgu_etiket"))

    # ALINTI KAYNAKTA DOĞRULANMADAN KULLANILMIYOR.
    # Birinin ağzına söylemediği sözü koymak, yanlış sayı yazmaktan çok
    # daha ağır bir hata. Doğrulanamayan alıntı sessizce atılıyor.
    alinti = None
    ham_alinti = _alan(haber, "alinti")
    if ham_alinti:
        kaynak = _alan(haber, "makale_metni") or _alan(haber, "ozet_orj")
        if dogrula.alintiyi_denetle(ham_alinti, kaynak):
            alinti = (ham_alinti, _alan(haber, "alinti_sahibi"))
        else:
            log.warning("alıntı kaynakta doğrulanamadı, atlandı #%s",
                        haber["id"])

    # Metin uzunsa birden fazla sayfaya yayılıyor — punto küçültmek
    # yerine sayfa ekliyoruz, yoksa uzun anlatım okunmaz hâle geliyor.
    sayfalar = make_image.detay_sayfalara_bol(
        detay, ayarlar, vurgu=vurgu, alinti=alinti
    )
    detay_yollari = []
    for i, satirlar in enumerate(sayfalar, start=1):
        gorsel2 = make_image.detay_slayti(
            _slayt_metni(haber, "ig_baslik", ayarlar),
            detay,
            make_image.kaynak_gosterim_adi(haber["kaynak"], ayarlar),
            ayarlar,
            kategori=haber["kategori"],
            son_dakika=son_dakika_mi and i == 1,
            ulke_kodu=_alan(haber, "ulke_kodu") or None,
            ulke_adi=_alan(haber, "ulke_adi") or None,
            satirlar=satirlar,
            sayfa=i,
            toplam_sayfa=len(sayfalar),
        )
        ek = "" if len(sayfalar) == 1 else f"-{i}"
        yol2 = make_image.CIKTI_KLASORU / f"slayt-{haber['id']}-detay{ek}.jpg"
        gorsel2.save(yol2, "JPEG", quality=g["jpeg_kalite"], subsampling=0, optimize=True)
        detay_yollari.append(yol2)

    # --- Story (9:16): HAM arka planla, slaytla değil ---
    yol3 = None
    try:
        story = make_image.story_haber(
            _slayt_metni(haber, "ig_baslik", ayarlar),
            _slayt_metni(haber, "slayt_ozet", ayarlar),
            make_image.kaynak_gosterim_adi(haber["kaynak"], ayarlar),
            ayarlar,
            arkaplan=(ham_arkaplan.copy()
                      if katman in FOTOGRAFLI_KATMANLAR else None),
            kategori=haber["kategori"],
            son_dakika=son_dakika_mi,
            ulke_kodu=_alan(haber, "ulke_kodu") or None,
            ulke_adi=_alan(haber, "ulke_adi") or None,
        )
        yol3 = make_image.CIKTI_KLASORU / f"story-{haber['id']}.jpg"
        story.save(yol3, "JPEG", quality=_kalite(g, katman), subsampling=0, optimize=True)
    except Exception as e:
        # Story ikincil; patlarsa post yine çıkmalı.
        log.warning("story görseli üretilemedi: %s", e)

    log.info("son dakika slaytları üretildi #%s [%s + %d detay + story]",
             haber["id"], katman, len(detay_yollari))

    if con is not None:
        con.execute(
            "UPDATE haberler SET gorsel_yolu = ?, gorsel_kaynagi = ?, "
            "gorsel_atif = ? WHERE id = ?",
            (str(yol1), katman, atif, haber["id"]),
        )
        con.commit()

    sonuc = [{"id": haber["id"], "yol": yol1, "katman": katman, "atif": atif}]
    sonuc += [{"id": haber["id"], "yol": y, "katman": "detay", "atif": ""}
              for y in detay_yollari]
    if yol3:
        # Story carousel'e GİRMİYOR; ayrı işaretli, çağıran taraf ayırıyor.
        sonuc.append(
            {"id": haber["id"], "yol": yol3, "katman": "story", "atif": ""}
        )
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
