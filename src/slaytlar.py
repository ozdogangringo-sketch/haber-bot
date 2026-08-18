"""
slaytlar.py — ADIM 3'ün son parçası

Bir turluk carousel'in bütün slaytlarını üretir.

BURADAKİ ASIL İŞ: görsel katmanını seçmek. Her haberin arka planı üç
bedava kaynaktan gelebiliyor, sırayla deneyip ilk tutanı kullanıyoruz:

    1. Wikimedia Commons  — haberde tanınmış bir kişi/kurum varsa
    2. Pexels             — yoksa konuyu temsil eden stok fotoğraf
    3. Gradyan            — ikisi de bulamazsa

Neden sıra bu: Commons gerçek kişinin gerçek fotoğrafını veriyor, en
bilgilendirici olan o. Ama sadece tanınmış isimlerde tutuyor. Pexels her
konuda bir şey buluyor ama temsili — "bir otobüs", o otobüs değil.
Gradyan hiç yanıltmıyor ama hiçbir şey de anlatmıyor.

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

from . import dogrula, fetch_article, fetch_photo, fetch_stock, make_image

log = logging.getLogger(__name__)


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
    Haber görselini indirir; küçük ya da bozuksa None döner.

    ⚠️ BOYUT DENETİMİ ŞART. `og:image` bazen sitenin logosu ya da
    paylaşım rozeti oluyor; 1080x1350'ye büyütülünce bulanık bir leke
    çıkıyor. Asgari genişlik altındakiler eleniyor ve akış bir sonraki
    katmana (Commons/Pexels) düşüyor.
    """
    asgari = g.get("haber_gorseli_asgari_genislik", 600)
    try:
        cevap = requests.get(url, timeout=20,
                             headers={"User-Agent": "Mozilla/5.0"})
        cevap.raise_for_status()
        foto = Image.open(io.BytesIO(cevap.content))
        foto.load()
    except Exception as e:
        log.warning("haber görseli indirilemedi: %s", e)
        return None

    if foto.width < asgari:
        log.info("haber görseli küçük (%spx), atlanıyor", foto.width)
        return None
    return foto.convert("RGB")


def arkaplan_sec(haber, ayarlar: dict) -> tuple[Image.Image, str, str]:
    """
    Habere arka plan bulur. (görüntü, katman_adı, atıf_metni) döner.

    Katmanlar tek tek denenip ilk tutan alınıyor. Bir katman patlarsa
    (ağ hatası, kota, bozuk dosya) sonrakine geçiliyor — görsel
    bulunamadı diye postun kaçmaması gerekiyor.
    """
    g = ayarlar["gorsel"]
    genislik, yukseklik = g["genislik"], g["yukseklik"]

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
    if g.get("haber_gorseli_kullan") and haber["link"]:
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
            sonuc = fetch_photo.konu_icin_fotograf(konu)
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
    terim = _alan(haber, "gorsel_temsili")
    if terim:
        try:
            sonuc = fetch_stock.konu_icin_fotograf(terim)
            if sonuc:
                foto, kayit = sonuc
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
        make_image.arkaplan_uret_yedek(haber["kategori"], genislik, yukseklik),
        "gradyan",
        "",
    )


def slayt_uret(haber, ayarlar: dict) -> tuple[Path, str, str]:
    """
    Tek bir haberin slaytını üretip diske yazar.

    (dosya_yolu, katman_adı, atıf_metni) döner. Atıf metni caption'ın
    sonuna eklenecek — Commons'taki CC BY görselleri için bu hukuken şart,
    Pexels'te zorunlu değil ama veriyoruz.
    """
    g = ayarlar["gorsel"]
    make_image.CIKTI_KLASORU.mkdir(parents=True, exist_ok=True)

    arkaplan, katman, atif = arkaplan_sec(haber, ayarlar)

    gorsel = make_image.yaziyi_bas(
        arkaplan,
        haber["ig_baslik"] or haber["baslik_orj"],
        haber["kaynak"],
        ayarlar,
        ozet=_alan(haber, "slayt_ozet") or None,
        # Fotoğraf katmanlarında görsel o olayın belgesi değil; gradyanda
        # ise ortada fotoğraf yok, ibare anlamsız olurdu.
        arsiv_ibaresi=katman in ("commons", "pexels"),
        ulke_kodu=_alan(haber, "ulke_kodu") or None,
        ulke_adi=_alan(haber, "ulke_adi") or None,
        # Şerit rengi kategoriden geliyor: spor yeşil, ekonomi bronz…
        kategori=haber["kategori"] or "",
    )

    yol = make_image.CIKTI_KLASORU / f"slayt-{haber['id']}.jpg"
    # Instagram PNG kabul etmiyor — JPEG şart
    gorsel.save(yol, "JPEG", quality=g["jpeg_kalite"], optimize=True)
    log.info("slayt üretildi [%s] #%s → %s", katman, haber["id"], yol.name)
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

        if con is not None:
            # Atıf da yazılıyor: caption yayın anında yeniden kuruluyor ve
            # hazırlık ile onay arasında saatler geçebiliyor. Bellekte
            # tutulsa Commons'ın CC BY atfı yayında kaybolurdu.
            con.execute(
                "UPDATE haberler SET gorsel_yolu = ?, gorsel_kaynagi = ?, "
                "gorsel_atif = ? WHERE id = ?",
                (str(yol), katman, atif, haber["id"]),
            )
            con.commit()

        sonuclar.append(
            {"id": haber["id"], "yol": yol, "katman": katman, "atif": atif}
        )

    return sonuclar


def son_dakika_uret(haber, ayarlar: dict, con=None) -> list[dict]:
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
    ham_arkaplan, katman, atif = arkaplan_sec(haber, ayarlar)

    gorsel1 = make_image.yaziyi_bas(
        ham_arkaplan.copy(),
        haber["ig_baslik"] or haber["baslik_orj"],
        haber["kaynak"],
        ayarlar,
        ozet=_alan(haber, "slayt_ozet") or None,
        arsiv_ibaresi=katman in ("commons", "pexels"),
        ulke_kodu=_alan(haber, "ulke_kodu") or None,
        ulke_adi=_alan(haber, "ulke_adi") or None,
        # Şerit rengi kategoriden geliyor: spor yeşil, ekonomi bronz…
        kategori=haber["kategori"] or "",
    )
    yol1 = make_image.CIKTI_KLASORU / f"slayt-{haber['id']}.jpg"
    gorsel1.save(yol1, "JPEG", quality=g["jpeg_kalite"], optimize=True)

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
            haber["ig_baslik"] or haber["baslik_orj"],
            detay,
            haber["kaynak"],
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
        gorsel2.save(yol2, "JPEG", quality=g["jpeg_kalite"], optimize=True)
        detay_yollari.append(yol2)

    # --- Story (9:16): HAM arka planla, slaytla değil ---
    yol3 = None
    try:
        story = make_image.story_haber(
            haber["ig_baslik"] or haber["baslik_orj"],
            _alan(haber, "slayt_ozet"),
            haber["kaynak"],
            ayarlar,
            # Gradyan katmanında ham arka planı geçmiyoruz: story kendi
            # ölçüsünde yeni bir gradyan üretsin, 4:5'liği esnetmesin.
            arkaplan=(ham_arkaplan.copy()
                      if katman in ("commons", "pexels") else None),
            kategori=haber["kategori"],
            son_dakika=son_dakika_mi,
            ulke_kodu=_alan(haber, "ulke_kodu") or None,
            ulke_adi=_alan(haber, "ulke_adi") or None,
        )
        yol3 = make_image.CIKTI_KLASORU / f"story-{haber['id']}.jpg"
        story.save(yol3, "JPEG", quality=g["jpeg_kalite"], optimize=True)
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
