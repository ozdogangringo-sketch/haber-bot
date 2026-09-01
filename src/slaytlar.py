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

    # --- 0) Web HD Haber Fotoğrafı (Canlı Basın & Olay Fotoğrafı Arama) ---
    if not haber_gorseli_atla:
        try:
            web_sonuc = fetch_web_image.haber_icin_fotograf(haber, atlanacak=atlanacak)
            if web_sonuc:
                foto, web_kayit = web_sonuc
                return (
                    make_image.fotograftan_arkaplan(foto, genislik, yukseklik),
                    "web_haber",
                    "",
                )
        except Exception as e:
            log.warning("Web haber görseli katmanı patladı: %s", e)

    # --- 0.5) Haberin kendi görseli (og:image) ---
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

    # --- 1) Commons: İkili Aktör (Split-Screen) veya Tek Kişi ---
    ikili = _alan(haber, "gorsel_ikili")
    if ikili and atlanacak == 0:
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

    # --- 2.5) Gemini AI Görsel Üretimi (Fotoğraf bulunamazsa AI ile özel editoryal görsel üret) ---
    try:
        gorsel_ai = make_image.arkaplan_uret_ai(haber.get("kategori") or "turkiye", ayarlar)
        if gorsel_ai is not None:
            if gorsel_ai.size != (genislik, yukseklik):
                gorsel_ai = gorsel_ai.resize((genislik, yukseklik), Image.LANCZOS)
            log.info("arka plan: Gemini AI ile üretildi (#%s)", haber.get("id"))
            return gorsel_ai, "ai", ""
    except Exception as e:
        log.warning("AI arka plan üretimi hatası: %s", e)

    # --- 3) Gradyan: her zaman çalışır ---
    return (
        make_image.arkaplan_uret_yedek(haber["kategori"], genislik, yukseklik, g),
        "gradyan",
        "",
    )


def slayt_uret(haber, ayarlar: dict,
               zorla_ai: bool = False,
               atlanacak: int = 0,
               haber_gorseli_atla: bool = False,
               sira: int = 1,
               son_slayt: bool = False) -> tuple[Path, str, str]:
    """
    Tek bir haberin slaytını üretip diske yazar.
    """
    g = ayarlar["gorsel"]
    make_image.CIKTI_KLASORU.mkdir(parents=True, exist_ok=True)

    arkaplan, katman, atif = arkaplan_sec(
        haber, ayarlar, zorla_ai=zorla_ai, atlanacak=atlanacak,
        haber_gorseli_atla=haber_gorseli_atla)

    # Veri Kartı / Mini İnfografik Rozeti
    veri_karti = None
    v_etiket = _alan(haber, "veri_karti_etiket")
    v_yeni = _alan(haber, "veri_karti_yeni")
    if v_etiket and v_yeni:
        km = _alan(haber, "makale_metni") or _alan(haber, "ozet_orj")
        baslik = _alan(haber, "ig_baslik") or _alan(haber, "baslik_orj") or ""
        ozet = _alan(haber, "slayt_ozet") or ""
        if dogrula.veri_karti_dogrula(_alan(haber, "veri_karti_eski"), v_yeni, km):
            gecici_kart = {
                "etiket": v_etiket,
                "yeni": v_yeni,
                "eski": _alan(haber, "veri_karti_eski") or "",
                "yon": _alan(haber, "veri_karti_yon") or "artis",
            }
            if not dogrula.veri_karti_baslikta_var_mi(gecici_kart, baslik, ozet):
                veri_karti = gecici_kart
            else:
                log.info("Veri kartı başlıkta/özette zaten var, atlandı #%s", haber.get("id"))

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
            yol, katman, atif = slayt_uret(haber, ayarlar, sira=idx, son_slayt=is_son)
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
                    atlanacak: int = 0,
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
    ham_arkaplan, katman, atif = arkaplan_sec(
        haber, ayarlar, zorla_ai=zorla_ai, atlanacak=atlanacak,
        haber_gorseli_atla=haber_gorseli_atla)

    veri_karti = None
    v_etiket = _alan(haber, "veri_karti_etiket")
    v_yeni = _alan(haber, "veri_karti_yeni")
    if v_etiket and v_yeni:
        km = _alan(haber, "makale_metni") or _alan(haber, "ozet_orj")
        baslik = _alan(haber, "ig_baslik") or _alan(haber, "baslik_orj") or ""
        ozet = _alan(haber, "slayt_ozet") or ""
        if dogrula.veri_karti_dogrula(_alan(haber, "veri_karti_eski"), v_yeni, km):
            gecici_kart = {
                "etiket": v_etiket,
                "yeni": v_yeni,
                "eski": _alan(haber, "veri_karti_eski") or "",
                "yon": _alan(haber, "veri_karti_yon") or "artis",
            }
            if not dogrula.veri_karti_baslikta_var_mi(gecici_kart, baslik, ozet):
                veri_karti = gecici_kart
            else:
                log.info("Veri kartı başlıkta/özette zaten var, atlandı #%s", haber.get("id"))

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

    log.info("son dakika %100 native 9:16 slaytları üretildi #%s [%s + %d detay]",
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
