"""
son_dakika.py — Gün içinde önemli haber çıktıysa 2 slaytlık post hazırlar.

AKŞAM TURUNDAN FARKI:
    Akşam turu günün 10 haberini toplu veriyor. Bu script tek bir haberi,
    çıktığı anda veriyor. Format da farklı: 2 slayt — birincisi dikkat
    çeker (fotoğraf + başlık), ikincisi anlatır (sade zemin + detay).

KARARLAR (16 Ağu 2026, kullanıcıyla konuşuldu):
    * Eşik: onem_puani >= 8
    * Onay ŞART, ama 1 saat içinde onaylanmazsa kendiliğinden iptal.
      Bayat bir "son dakika" postu atmak, hiç atmamaktan kötü.
    * Günde en fazla 2 son dakika. Akşam turuyla birlikte günde 3 post —
      Instagram için sağlıklı aralık, takipçi yorulmuyor.

NEDEN ONAY KALDIRILMADI:
    Son dakika haberleri EN ÇOK düzeltilen haberlerdir; ilk dakikalarda
    sayılar ve isimler değişir. Doğrulama katmanımız "kaynakta ne yazıyorsa
    o" diyor ama kaynağın kendisi 20 dakika sonra güncelleniyor. Yani
    otomatik yayının en riskli olduğu yer tam burası.

ÇALIŞTIRMA:
    python scripts/son_dakika.py           (kontrol et, gerekiyorsa hazırla)
    python scripts/son_dakika.py --kuru    (Telegram'a GÖNDERME)
"""

import json
import logging
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import yaml                                       # noqa: E402

from src import (                                  # noqa: E402
    aday, ayar, caption, db, db_senkron, hata_bildir, dogrula, facebook, fetch_news, instagram,
    make_image, otomatik_onay, threads,
    secim, slaytlar, telegram_bot, upload_image, yonetim,
)
from src import generate_text                      # noqa: E402
from src.generate_text import metinleri_uret       # noqa: E402

log = logging.getLogger("sondakika")

# Onaylanmayan son dakika turu kaç dakika sonra kendiliğinden düşsün (24 saat).
OMUR_DAKIKA = 24 * 60

# Haber kaç saatten eskiyse artık "son dakika" sayılmaz.
# ⚠️ Config'den okunuyor — sabit 3 saat ölçüldüğünde çok dar çıktı:
# havuzdaki 228 hazır metnin 224'ü bu filtreye takılıyordu ve tekil
# post 5 saat boyunca hiç çıkmadı (19 Ağu 2026).
TAZELIK_SAAT_VARSAYILAN = 5


def _tazelik_saat(ayarlar: dict | None = None) -> int:
    if not ayarlar:
        return TAZELIK_SAAT_VARSAYILAN
    return ayarlar["genel"].get("son_dakika_tazelik_saat",
                                TAZELIK_SAAT_VARSAYILAN)

# TR saatiyle gece aralığı. UTC+3 sabit (yaz saati yok).
GECE_BASI_TR, GECE_SONU_TR = 23, 7


def _tr_saat() -> int:
    """Şu anki TR saati. Türkiye UTC+3, yaz saati uygulaması yok."""
    return (datetime.now(timezone.utc) + timedelta(hours=3)).hour


def gece_mi() -> bool:
    saat = _tr_saat()
    return saat >= GECE_BASI_TR or saat < GECE_SONU_TR


def gecerli_esik(ayarlar: dict, kategori: str | None = None) -> int:
    """
    Bu haberin tekil post olabilmesi için gereken önem puanı.

    İKİ ŞEY BELİRLİYOR:

    1. GECE Mİ — gece eşiği daha yüksek. Gece hazırlanan post sabaha
       kalıyor, yani onaylandığında 5-8 saatlik bir haber oluyor; bu
       gecikmeyi ancak gerçekten büyük bir olay hak ediyor.

    2. KATEGORİ — ⚠️ TEK EŞİK SPOR VE EKONOMİYİ TAMAMEN DIŞLIYORDU.
       Ölçüldü (19 Ağu 2026, son 3 gün): ekonomi 18 haberin 8+ alanı
       SIFIR (en yükseği 7), spor 15 haberin 8+ alanı SIFIR (en yükseği
       7). Eşik 8 iken o kategorilerden tekil post çıkması matematiksel
       olarak imkansızdı.

       Sebep, önem puanının kendisinin kategoriye göre farklı
       dağılması: "ülke gündemi" haberleri doğaları gereği daha yüksek
       puan alıyor. Aynı çatı altında yarıştırmak yerine her kategoriye
       kendi eşiği veriliyor — bu, ön elemedeki kategori katsayısı
       mantığının tekil postlara uygulanmış hali.
    """
    g = ayarlar["genel"]
    taban = (g.get("gece_puan_esigi", 9) if gece_mi()
             else g.get("son_dakika_puan_esigi", 8))

    esikler = g.get("son_dakika_kategori_esikleri", {}) or {}
    if kategori and kategori in esikler:
        # Gece kuralı kategori eşiğinde de geçerli: bir puan daha zor.
        return esikler[kategori] + (1 if gece_mi() else 0)
    return taban


def bugunku_kategori_sayisi(con, kategori: str) -> int:
    """Bugün bu kategoriden kaç tekil post yayınlandı?"""
    return con.execute(
        "SELECT COUNT(*) FROM haberler WHERE son_dakika = 1 "
        "AND durum = 'yayinlandi' AND kategori = ? "
        "AND date(gonderim_zamani) = date('now')",
        (kategori,),
    ).fetchone()[0]


def omru_bitti_mi(gonderim: str, ayarlar: dict) -> bool:
    """
    Bu tur düşürülmeli mi?

    Görselleri üretilmiş bir haber 24 saat boyunca Telegram'da onaya hazır bekler.
    Kullanıcı onay verdiği sürece 24 saat boyunca yayınlanabilir.
    """
    try:
        t = datetime.fromisoformat(gonderim).replace(tzinfo=timezone.utc)
    except ValueError:
        return False

    simdi = datetime.now(timezone.utc)
    return simdi - t > timedelta(hours=24)


def _bugun_anahtari() -> str:
    return "son_dakika_" + datetime.now(timezone.utc).strftime("%Y-%m-%d")


def bugunku_sayi(con) -> int:
    """
    Bugün YAYINLANMIŞ tekil post sayısı.

    ⚠️ ESKİDEN AYRI BİR SAYAÇ OKUNUYORDU ve o sayaç haber ONAYA
    SUNULDUĞUNDA artıyordu, yayınlandığında değil. 21 Ağu 2026'da
    ölçüldü: sayaç 10 (sınır dolu) ama gerçekte yalnızca 6 post
    yayınlanmıştı — onaylamadığın 4 haber günlük kotayı yemişti ve
    yeni seçimler sessizce reddediliyordu.

    Artık veritabanına soruyoruz: tek doğru kaynak yayının kendisi.
    """
    return con.execute(
        "SELECT COUNT(*) FROM haberler "
        "WHERE son_dakika = 1 AND durum = 'yayinlandi' "
        "AND date(gonderim_zamani, '+3 hours') = date('now', '+3 hours')"
    ).fetchone()[0]


def sayaci_artir(con) -> None:
    db.ayar_yaz(con, _bugun_anahtari(), bugunku_sayi(con) + 1)


# Planlanan saatin ne kadar üstüne çıkılırsa yayın vazgeçilir.
# Sebep: cron atlanabiliyor (GitHub cron gecikmesi 5-30 dk, nadiren
# tamamen kaçıyor). 4 saat geciken bir "şimdi yayınla" kararı artık
# kullanıcının verdiği karar değil — haber bayatlamış olur.
PLAN_AZAMI_GECIKME_SAAT = 4


def planli_yayinlari_isle(con, ayarlar: dict) -> int:
    """
    Zamanı gelen planlanmış turları yayınlar.

    Bu, "yayınla" düğmesinin alt menüsünden seçilen gecikmeli yayının
    ikinci yarısı. Neden burada: GitHub Actions'ta "N dakika sonra
    çalıştır" diye bir şey YOK. İki seçenek vardı —
      * job içinde `sleep` beklemek: 2 saatlik plan 120 dakika Actions
        kotası yakardı, kota zaten sınırda (bkz. CLAUDE.md);
      * zamanı veritabanına yazıp mevcut bir cron'a baktırmak.
    İkincisi seçildi ve EK MALİYETİ SIFIR — bu kontrol zaten 30
    dakikada bir çalışıyor, tek eklenen bir SELECT.

    Bedeli hassasiyet: yayın planlanan saatle onu izleyen 30 dakika
    arasında çıkar. Menüdeki seçeneklerin 30'un katı olması bu yüzden.
    """
    simdi = datetime.now(timezone.utc)
    bekleyen = list(con.execute(
        "SELECT DISTINCT telegram_message_id AS mid, planlanan_yayin "
        "FROM haberler WHERE planlanan_yayin IS NOT NULL "
        "AND durum = 'onay_bekliyor' AND telegram_message_id IS NOT NULL"))
    if not bekleyen:
        return 0

    # onay_isle bu modülü import ediyor (çoklu seçimde tekil post
    # üretmek için); tepede import edersek döngü oluşur.
    sys.path.insert(0, str(KOK / "scripts"))
    import onay_isle                                   # noqa: E402

    yayinlanan = 0
    for satir in bekleyen:
        mesaj_id = satir["mid"]
        try:
            an = datetime.fromisoformat(satir["planlanan_yayin"])
        except (TypeError, ValueError):
            log.warning("planlanan_yayin okunamadı (%s), plan siliniyor", mesaj_id)
            con.execute("UPDATE haberler SET planlanan_yayin = NULL "
                        "WHERE telegram_message_id = ?", (mesaj_id,))
            con.commit()
            continue

        if simdi < an:
            kalan = (an - simdi).total_seconds() / 60
            log.info("planlı yayın %s: %.0f dakika var", mesaj_id, kalan)
            continue

        gecikme = (simdi - an).total_seconds() / 3600
        if gecikme > PLAN_AZAMI_GECIKME_SAAT:
            log.warning("planlı yayın %s %.1f saat gecikmiş, iptal", mesaj_id, gecikme)
            con.execute("UPDATE haberler SET planlanan_yayin = NULL "
                        "WHERE telegram_message_id = ?", (mesaj_id,))
            con.commit()
            try:
                telegram_bot.sonucu_yaz(
                    mesaj_id,
                    f"⌛️ Planlanan yayın {gecikme:.0f} saat gecikti, "
                    "yapılmadı.\nHaber elenmedi — tur onay bekliyor.")
            except Exception as e:
                log.warning("gecikme mesajı yazılamadı: %s", e)
            continue

        haberler = onay_isle.turu_getir(con, mesaj_id)
        if not haberler:
            log.warning("planlı yayın %s: tur bulunamadı", mesaj_id)
            con.execute("UPDATE haberler SET planlanan_yayin = NULL "
                        "WHERE telegram_message_id = ?", (mesaj_id,))
            con.commit()
            continue

        log.info("planlı yayın zamanı geldi: %s", mesaj_id)
        # Planı ÖNCE temizliyoruz: yayın yarıda patlarsa bir sonraki
        # kontrol aynı turu tekrar yayınlamaya kalkmasın (çift post).
        con.execute("UPDATE haberler SET planlanan_yayin = NULL "
                    "WHERE telegram_message_id = ?", (mesaj_id,))
        con.commit()
        try:
            onay_isle.yayinla(con, ayarlar, haberler, mesaj_id, "zamanlanmış")
            yayinlanan += 1
        except Exception as e:
            log.exception("planlı yayın patladı (%s)", mesaj_id)
            try:
                # `nerede` önemli: hata mesajındaki eylem düğmesi buna
                # bakıyor. "son_dakika" yazmazsak "yeniden hazırla"
                # düğmesi akşam turunu tetikler (20 Ağu 2026'da oldu).
                hata_bildir.bildir("Zamanlanmış yayın yapılamadı", e,
                                   nerede="son_dakika.py")
            except Exception:
                pass
    return yayinlanan


def suresi_gecmisi_iptal_et(con, ayarlar: dict) -> None:
    """
    1 saati dolmuş, onaylanmamış son dakika turunu düşürür.

    Haber ELENMİYOR — havuza dönüyor ve akşam turunda yeniden yarışıyor.
    Sadece "son dakika" olarak yayınlanma hakkını kaybediyor.
    """
    bekleyen = list(con.execute(
        "SELECT DISTINCT telegram_message_id, gonderim_zamani FROM haberler "
        "WHERE son_dakika = 1 AND durum = 'onay_bekliyor' "
        "AND gonderim_zamani IS NOT NULL "
        # ⚠️ Planlanmış tur bu kuraldan MUAF. Ömür 60 dakika olduğu
        # için "1 saat sonra yayınla" planı yayın anı gelmeden kendi
        # kendini iptal ederdi.
        "AND planlanan_yayin IS NULL"
    ))

    for satir in bekleyen:
        if not omru_bitti_mi(satir["gonderim_zamani"], ayarlar):
            continue
        mesaj_id = satir["telegram_message_id"]
        # Metni olan haber 'metin_hazir'e dönüyor: 'yeni' yapılırsa
        # sonraki tur onu Gemini'ye tekrar gönderiyor, kota boşa gidiyor
        # ve hata alınırsa haber havuzdan düşüyor.
        con.execute(
            "UPDATE haberler SET son_dakika = 0, telegram_message_id = NULL, "
            "durum = CASE WHEN ig_baslik IS NOT NULL THEN 'metin_hazir' "
            "             ELSE 'yeni' END "
            "WHERE telegram_message_id = ?",
            (mesaj_id,),
        )
        con.commit()
        try:
            telegram_bot.sonucu_yaz(
                mesaj_id,
                "⌛️ Son dakika postu onaylanmadı, iptal edildi.\n"
                "Haber elenmedi — akşam turunda yeniden değerlendirilecek.",
            )
        except Exception as e:
            log.warning("iptal mesajı yazılamadı: %s", e)
        log.info("süresi geçen son dakika turu iptal edildi (%s)", mesaj_id)


def taze_adaylar(con, ayarlar: dict, kac: int) -> list:
    """
    Metin üretilecek TAZE haberler.

    ⚠️ NEDEN `secim.on_eleme` KULLANMIYORUZ. Ölçüldü (19 Ağu 2026):
    tekil post 5 saat boyunca hiç çıkmadı. Sebep aday bulunamaması
    değildi — havuzda 228 hazır metin vardı ama **224'ü 3 saatten
    eskiydi** ve `TAZELIK_SAAT` filtresine takılıyordu. Aynı anda son
    3 saatte gelen 44 haberin metni HİÇ üretilmemişti.

    Kök sebep: `on_eleme` "en iyi haberi" seçiyor — kaynak ağırlığı,
    kategori katsayısı ve içerik sinyaliyle. Son dakika için gereken
    ise "en TAZE haber". İkisi farklı sorular ve on_eleme ikincisini
    cevaplamıyor; havuzdaki eski ama yüksek skorlu haberleri seçip
    duruyordu, onlar da zaten bayat oldukları için aday olamıyordu.

    Burada doğrudan tazelik sorgulanıyor: son `TAZELIK_SAAT` içinde
    yayınlanmış, metni henüz üretilmemiş haberler, kaynak ağırlığına
    göre sıralı.
    """
    sinir = (datetime.now(timezone.utc)
             - timedelta(hours=_tazelik_saat(ayarlar))).isoformat()
    return list(con.execute(
        """SELECT * FROM haberler
           WHERE durum = 'yeni' AND yayin_tarihi >= ?
           ORDER BY agirlik DESC, yayin_tarihi DESC LIMIT ?""",
        (sinir, kac),
    ))



# `onerileri_gonder` bu değeri döndürdüğünde: öneri GÖNDERİLMEDİ,
# bunun yerine yüksek puanlı bir habere metin üretildi. Çağıran taraf
# yeniden aday aramalı — o haber artık otomatik yayın akışına girebilir.
METIN_URETILDI = -1


def oneri_esigi(ayarlar: dict, kategori: str | None) -> int:
    """
    ÖNERİ aşamasının eşiği — tam metin eşiğinden ayrı.

    ⚠️ Toplu başlık puanlaması aynı habere tam metin puanlamasından
    ortalama 1.5-1.8 puan DÜŞÜK veriyor (ölçüldü). Aynı eşiği
    kullanmak öneri akışını tamamen kilitliyordu: hiçbir başlık 8'e
    ulaşamadığı için öneri hiç gönderilmiyordu.

    ⚠️ GECE KURALI BURADA UYGULANMIYOR — bilerek. Yayın eşiğinde gece
    +1 var, çünkü gece çıkan post kimsenin onayından geçmeden yayında
    kalıyor. Ama ÖNERİ yayın değil, yalnızca insana sunma: mesaj gece
    gelir, kullanıcı sabah bakıp seçer.
    """
    g = ayarlar["genel"]
    esikler = g.get("oneri_kategori_esikleri", {}) or {}
    return esikler.get(kategori, 6)


def onerileri_gonder(con, ayarlar: dict, kuru: bool = False) -> int:
    """
    Taze başlıkları ucuz yoldan puanlayıp Telegram'a ÖNERİ gönderir.

    ⚠️ İKİ AŞAMALI AKIŞIN BİRİNCİ AŞAMASI (19 Ağu 2026).
    Eskiden kontrol job'ı taze haberlere TAM metin üretiyor (~4400
    token/haber), sonra puanına bakıp eşiği geçmiyorsa atıyordu —
    üretilen metnin çoğu çöpe gidiyordu. Şimdi yalnızca başlıklar
    toplu ve ucuz biçimde puanlanıyor (10 başlık tek istekte,
    ~1500 token); tam metin YALNIZCA kullanıcının seçtiği haber için
    üretiliyor.

    Döner: gönderilen öneri sayısı (0 = önerilecek haber yok).
    """
    tazelik = _tazelik_saat(ayarlar)
    sinir = (datetime.now(timezone.utc) - timedelta(hours=tazelik)).isoformat()
    azami = ayarlar["genel"].get("oneri_aday_adedi", 10)

    # Henüz ÖNERİLMEMİŞ taze haberler — puanı olsun ya da olmasın.
    #
    # ⚠️ Önce burada `onem_puani IS NULL` şartı da vardı ve haberi bir
    # kez puanlamak onu havuzdan DÜŞÜRÜYORDU: puanlanmış ama önerilmemiş
    # 78 haber bu şekilde görünmez oldu (kuru test çalıştırmaları
    # puanları yazdığı için). Puanın varlığı haberin değerlendirilmiş
    # olduğunu göstermez — `oneri_gonderildi` işareti onu gösterir.
    # ⚠️ SIRALAMA AĞIRLIĞA GÖRE YAPILMIYOR — KATEGORİ BAZLI.
    #
    # Önce `ORDER BY agirlik DESC LIMIT 10` vardı ve öneri akışını
    # pratikte tek kaynağa kilitliyordu. Ölçüldü (20 Ağu 2026): taze
    # havuzda ağırlığı 9-10 olan **85 haber** var, yani 10'luk dilim
    # HER ZAMAN TRT/BBC/AA'dan doluyordu. Ağırlığı 8 olan NTV Teknoloji
    # bu dilime matematiksel olarak hiç giremiyordu — kullanıcının
    # istediği "Google öğrencilere Gemini verdi" tipi haberler tam da
    # o kaynaklardan geliyor.
    #
    # Kanıt: tarih boyunca `oneri_gonderildi=1` olan yalnızca 11 haber
    # vardı ve 7'si TRT'ydi.
    #
    # Çözüm, `secim.on_eleme`'de zaten ölçülmüş olan kalıp: haberler
    # önce KENDİ kategorisinde sıralanıyor, sonra kategori katsayısıyla
    # ağırlıklandırılıyor. O değişiklik ön elemede kategori çeşidini
    # 2'den 5'e çıkarmıştı.
    havuz = list(con.execute(
        """SELECT * FROM haberler
           WHERE durum = 'yeni' AND yayin_tarihi >= ?
             AND (oneri_gonderildi IS NULL OR oneri_gonderildi = 0)
             AND (sadece_tur IS NULL OR sadece_tur = 0)""",
        (sinir,),
    ))
    if not havuz:
        log.info("önerilecek taze haber yok")
        return 0

    s_ayar = ayarlar.get("secim", {}) or {}
    katsayilar = s_ayar.get("kategori_katsayilari", {}) or {}
    varsayilan = s_ayar.get("kategori_varsayilan_katsayi", 0.6)
    azalma = s_ayar.get("kategori_sira_azalmasi", 0.88)

    kategoriler: dict[str, list] = {}
    for h in havuz:
        kategoriler.setdefault(h["kategori"] or "diger", []).append(h)

    puanli = []
    for kat, liste in kategoriler.items():
        # Kategori içinde: taze + içerik sinyali (LLM yok, bedava)
        liste.sort(key=lambda h: (secim._icerik_puani(h["baslik_orj"])
                                  - secim._yas_saat(h)), reverse=True)
        katsayi = katsayilar.get(kat, varsayilan)
        for sira, h in enumerate(liste):
            puanli.append((katsayi * (azalma ** sira), h))
    puanli.sort(key=lambda x: x[0], reverse=True)
    ham = [h for _, h in puanli[:azami]]

    log.info("öneri havuzu: %d haberden %d aday (%d kategori, %d kaynak)",
             len(havuz), len(ham),
             len({h["kategori"] for h in ham}),
             len({h["kaynak"] for h in ham}))

    # Yalnızca PUANSIZ olanlara Gemini çağrısı — puanı olan haberin
    # puanını yeniden üretmek kotayı boşa harcar.
    puansiz = [h for h in ham if h["onem_puani"] is None]
    puanlar = {h["id"]: h["onem_puani"]
               for h in ham if h["onem_puani"] is not None}
    if puansiz:
        yeni_puanlar = generate_text.basliklari_puanla(puansiz, ayarlar)
        if not yeni_puanlar and not puanlar:
            log.warning("başlıklar puanlanamadı, öneri gönderilmedi")
            return 0
        puanlar.update(yeni_puanlar)
    if not puanlar:
        log.info("puanlanabilen başlık yok")
        return 0

    # Puanları sakla — bir daha puanlamaya gerek kalmasın.
    #
    # ⚠️ KURU ÇALIŞMADA YAZMIYORUZ. `--kuru`nun sözleşmesi net: üretir,
    # Telegram'a göndermez, VERİTABANINA YAZMAZ. Bu blok kuru modda da
    # yazınca test çalıştırmaları öneri havuzunu tüketiyordu: puanlanan
    # haber `onem_puani IS NULL` filtresine artık takılmadığı için bir
    # daha öneriye giremiyordu. 20 Ağu 2026'da yapılan yapısal
    # çalışmanın kuru testleri 82 haberi bu şekilde havuzdan düşürdü.
    #
    # Kuru modda puanlar yalnızca bellekte kalıyor; gerçek çalıştırma
    # onları yeniden üretir (tek toplu istek, ~1500 token).
    if not kuru:
        for haber_id, puan in puanlar.items():
            con.execute("UPDATE haberler SET onem_puani = ? WHERE id = ?",
                        (puan, haber_id))
        con.commit()

    # ⚠️ GECE OTOMATİK YAYIN ADAYINI ÖNERİYE DÜŞÜRME.
    #
    # Öneri akışı haberi `durum='yeni'` ve metinsiz bırakıyor; oysa
    # `aday_bul` yalnızca `metin_hazir` olanlara bakıyor. Yani gece
    # gelen büyük bir haber öneriye düşerse otomatik yayınlanmaz,
    # sabaha kadar bekler — tam da otomatik yayının önlemek istediği
    # şey. Bu yüzden yüksek puanlı bir başlık varsa öneri yerine
    # doğrudan metni üretiliyor ve normal akışa bırakılıyor.
    #
    # Eşik toplu puanlamaya göre: toplu puan tam metin puanından
    # ~1.6 düşük geldiği için, yayın eşiği 9 olan bir haber burada
    # 7-8 civarında görünüyor.
    if (not kuru and gece_mi()
            and ayarlar["genel"].get("gece_otomatik_yayin", False)):
        uretim_esigi = ayarlar["genel"].get("oneri_otomatik_uretim_esigi", 8)
        yuksek = [h for h in ham
                  if puanlar.get(h["id"], 0) >= uretim_esigi]
        if yuksek:
            log.info("gece otomatik yayın adayı olabilir [%s], metin üretiliyor: %s",
                     puanlar.get(yuksek[0]["id"]), yuksek[0]["baslik_orj"][:50])
            metinleri_uret(ayarlar=ayarlar, haberler=yuksek[:1])
            return METIN_URETILDI

    # ⚠️ ELEME KURALLARI ARTIK `src/aday.py`'DE — burada tekrar YOK.
    #
    # Tazelik, eşik, kategori sınırı, geçmiş tekrarı ve liste içi
    # mükerrer denetimi tek kapıdan geçiyor. Önce bu kurallar üç ayrı
    # fonksiyona kopyalanmıştı ve biri hep unutuluyordu (1j, 1p).
    #
    # `aday.uygun_mu` puanı haberin üstünden okuyor, o yüzden puanların
    # kayıtlara işlenmiş olması gerekiyor.
    #
    # ⚠️ Gerçek çalıştırmada puanlar DB'ye yazıldı, yeniden çekiyoruz.
    # KURU çalışmada DB'ye yazmıyoruz (havuzu tüketmesin), o yüzden
    # puanı bellekte kayıtlara işliyoruz — eleme yine gerçek puanlarla
    # yapılıyor, yalnızca kalıcı iz bırakmıyor.
    idler = [h["id"] for h in ham]
    if kuru:
        puanli_ham = [dict(h, onem_puani=puanlar.get(h["id"])) for h in ham]
    else:
        isaret = ",".join("?" * len(idler))
        puanli_ham = list(con.execute(
            f"SELECT * FROM haberler WHERE id IN ({isaret})", idler))
    # Orijinal sırayı koru (ağırlık + tazelik sırası)
    sira = {hid: i for i, hid in enumerate(idler)}
    puanli_ham.sort(key=lambda h: sira.get(h["id"], 999))

    baglam = aday.Baglam.kur(aday.ONERI, ayarlar, con)
    uygunlar = aday.sec(puanli_ham, baglam)

    adaylar = [{"id": h["id"], "puan": h["onem_puani"],
                "baslik": h["baslik_orj"],
                "kaynak": h["kaynak"],
                "kategori": h["kategori"] or "-"}
               for h in uygunlar]
    adaylar.sort(key=lambda a: a["puan"], reverse=True)

    if not adaylar:
        log.info("puanlanan %d başlığın hiçbiri eşiği geçmedi", len(puanlar))
        return 0

    if kuru:
        print("\n--- ÖNERİ (kuru çalışma, Telegram'a gönderilmedi) ---")
        for a in adaylar[:5]:
            print(f"  [{a['puan']}] {a['kategori']:9} {a['baslik'][:60]}")
        return len(adaylar[:5])

    telegram_bot.oneri_gonder(adaylar)
    # Gönderilenleri işaretle: aynı başlık her kontrolde tekrar gelmesin
    for a in adaylar[:5]:
        con.execute("UPDATE haberler SET oneri_gonderildi = 1 WHERE id = ?",
                    (a["id"],))
    con.commit()
    db_senkron.hemen_kaydet("Tekil post önerisi")
    log.info("%d başlık öneri olarak gönderildi", len(adaylar[:5]))
    return len(adaylar[:5])


def aday_bul(con, ayarlar: dict):
    """
    Son dakika adayı: yüksek puanlı, taze ve henüz yayınlanmamış haber.

    Yalnızca metni ZATEN hazır olanlara bakıyoruz — kontrol job'ı artık
    metin üretmiyor, yalnızca başlık öneriyor (bkz. `onerileri_gonder`).
    Buradaki iş, daha önce üretilmiş metinlerin arasından fırlayanı
    seçmek.

    ⚠️ ELEME KURALLARI `src/aday.py`'DE. Tazelik, kategori eşiği,
    kategori günlük sınırı ve geçmiş tekrarı denetimi orada tek yerde
    duruyor. Bu fonksiyon önce kuralları kendi içinde tekrar ediyordu
    ve geçmiş tekrar denetimi buraya KONMAMIŞTI — 20 Ağu 2026'da sabah
    turunda yayınlanan Kiev saldırısı bir saat sonra tekil post olarak
    yeniden çıktı (1p). Kapıya bağlanınca o hata sınıfı kapandı.
    """
    baglam = aday.Baglam.kur(aday.TEKIL, ayarlar, con)

    # SQL ön filtresi yalnızca PERFORMANS için: kategori eşikleri
    # farklı olduğundan en düşüğüyle çekip asıl elemeyi aday kapısına
    # bırakıyoruz. Havuz zaten 'metin_hazir' ile sınırlı.
    esikler = list(
        (ayarlar["genel"].get("son_dakika_kategori_esikleri") or {}).values())
    taban = min([baglam.varsayilan_esik] + esikler) if esikler \
        else baglam.varsayilan_esik

    havuz = list(con.execute(
        "SELECT * FROM haberler WHERE durum = 'metin_hazir' "
        "AND ig_baslik IS NOT NULL AND onem_puani >= ? "
        "AND (son_dakika IS NULL OR son_dakika = 0) "
        # ⚠️ Kullanıcı "tura bırak" dediyse bir daha tekil aday olmasın.
        # Bu işaret olmadan haber her kontrolde yeniden sunuluyordu.
        "AND (sadece_tur IS NULL OR sadece_tur = 0) "
        "ORDER BY onem_puani DESC, yayin_tarihi DESC",
        (taban,),
    ))

    secilen = aday.sec(havuz, baglam, adet=1)
    return secilen[0] if secilen else None


def gece_otomatik_yayinla(con, ayarlar, aday, taze, urller,
                          story_url, metin) -> tuple[bool, list]:
    """
    Gece: dört katmanlı denetimden geçen haberi insan onayı olmadan yayınlar.

    Döner: `(yayinlandi, katman_raporu)`.

    ⚠️ RAPOR DA DÖNÜYOR — yalnızca bool yetmiyor. Gece otomatik yayın
    reddedildiğinde haber onaya sunuluyor ve o onay mesajında HANGİ
    katmanın reddettiği yazılı olmalı; insan kararını ona bakarak
    veriyor. İlk bölme denemesinde yalnızca bool dönüyordu ve rapor
    sessizce kayboluyordu.

    ⚠️ Bu blok `main()` içinde 104 satır olarak duruyordu ve fonksiyonu
    334 satıra çıkaran en büyük parçaydı. Davranış AYNEN korundu —
    yalnızca yeri değişti.

    Gece kimse uyanık değil; büyük bir olayda hesabın sabaha kadar
    sessiz kalması kötü. Ama insan onayını kaldırmak doğruluk
    güvencesini de kaldırıyor, o yüzden yerine dört katman kondu.
    ŞÜPHEDE REDDET: biri bile tereddüt ederse sabaha bırakılıyor.
    """
    # --- 6a) GECE: dört katmanlı denetimden geçerse otomatik yayınla ---
    #
    # Gece kimse uyanık değil; büyük bir olayda hesabın sabaha kadar
    # sessiz kalması kötü. Ama insan onayını kaldırmak doğruluk
    # güvencesini kaldırıyor, o yüzden yerine dört katman kondu.
    # ŞÜPHEDE REDDET: biri bile tereddüt ederse sabaha bırakılıyor.
    if not (gece_mi() and ayarlar["genel"].get("gece_otomatik_yayin", False)):
        return False, []

    uygun, katman_raporu = otomatik_onay.otomatik_yayinlanabilir(
        con, taze, ayarlar
    )
    for satir in katman_raporu:
        log.info("  %s", satir)

    if uygun:
        post_id = instagram.carousel_yayinla(urller, metin, ayarlar)
        baglanti = instagram.post_baglantisi(post_id, ayarlar)
        # ⚠️ ID'LER SAKLANIYOR. Gece yayını insan onayı olmadan
        # çıkıyor; sabah geri alınabilmesi için Facebook ve
        # Threads kimlikleri şart. Önce yalnızca Instagram id'si
        # yazılıyordu ve o postlar geri alınamıyordu.
        fb_id = None
        story_id = None
        if story_url:
            try:
                story_id = instagram.story_yayinla(story_url, ayarlar)
            except Exception as e:
                log.warning("story yayınlanamadı: %s", e)
        if (ayarlar.get("sosyal", {}) or {}).get("facebooka_da_at"):
            try:
                fb_id = facebook.albüm_yayinla(urller, metin, ayarlar)
                if story_url:
                    facebook.story_yayinla(story_url, ayarlar)
            except Exception as e:
                log.warning("Facebook paylaşılamadı: %s", e)
        th_gonderi_id = None
        if ((ayarlar.get("sosyal", {}) or {}).get("threadse_de_at")
                and threads.kullanilabilir_mi()):
            try:
                # Zincir: ana halka haberin kendisi, sonraki
                # halkalar ayrıntı sayfaları. Threads'in 500
                # karakter sınırı tek gönderiye sığdırmaya izin
                # vermiyor.
                # tarihli=False: haber ŞU AN oluyor, Threads
                # gönderinin yaşını zaten gösteriyor.
                halkalar = caption.threads_halkalari(
                    [taze], urller, son_dakika=True,
                    ayarlar=ayarlar, tarihli=False,
                )
                th_id, th_adet = threads.zincir_yayinla(halkalar)
                th_gonderi_id = th_id
                if th_adet < len(halkalar):
                    log.warning("Threads zinciri yarım: %s/%s halka",
                                th_adet, len(halkalar))
            except Exception as e:
                log.warning("Threads paylaşılamadı: %s", e)

        con.execute(
            "UPDATE haberler SET durum = 'yayinlandi', son_dakika = 1, "
            "ig_post_id = ?, gorsel_url = ?, detay_url = ?, story_url = ?, "
            "facebook_post_id = ?, threads_post_id = ?, story_post_id = ?, "
            "gonderim_zamani = datetime('now') WHERE id = ?",
            (post_id, urller[0], json.dumps(urller[1:]),
             story_url, fb_id, th_gonderi_id, story_id, aday["id"]),
        )
        con.commit()
        sayaci_artir(con)

        # Sabah görmek için: ne yayınlandı, hangi denetimlerden
        # geçti. Beğenilmezse Instagram'dan silinebilir.
        telegram_bot.slaytlari_gonder(urller, ["Haber", "Ayrıntı"])
        bildirim_id = telegram_bot.mesaj_gonder(
            "🌙 GECE OTOMATİK YAYINLANDI\n"
            f"{taze['ig_baslik']}\n\n"
            + "\n".join(katman_raporu)
            + f"\n\n{baglanti or post_id}\n\n"
            "Uygun bulmazsan aşağıdaki düğmeyle geri alabilirsin: "
            "Facebook ve Threads otomatik silinir, Instagram'ı "
            "elle silmen gerekir."
        )

        # ⚠️ TUR KİMLİĞİ OLARAK BİLDİRİM MESAJININ ID'Sİ.
        # Gece yayını onay mesajı üretmiyor, yani ortada bir
        # `telegram_message_id` yok; kaldırma komutu turu bununla
        # buluyor. Yazılmazsa "kaldır" düğmesi turu bulamıyor —
        # üstelik geri almanın en çok gerektiği senaryo bu, çünkü
        # post insan onayı olmadan çıkıyor.
        con.execute(
            "UPDATE haberler SET telegram_message_id = ? WHERE id = ?",
            (bildirim_id, aday["id"]),
        )
        con.commit()
        telegram_bot.butonlari_ayarla(
            bildirim_id,
            [[{"text": "🗑 Bu yayını kaldır",
               "callback_data": f"kaldir:{bildirim_id}"}]],
        )
        # Onay dallarında olduğu gibi burada da hemen push:
        # "kaldır" düğmesi GitHub'daki veritabanına bakıyor ve
        # workflow'un son adımını beklemek gereksiz risk.
        db_senkron.hemen_kaydet("Gece otomatik yayın")
        log.info("gece otomatik yayınlandı: %s", post_id)
        return True, katman_raporu

    log.info("otomatik yayın reddedildi, sabaha bırakılıyor")
    return False, katman_raporu


def onaya_sun(con, ayarlar, aday, taze, urller, story_url, metin,
              uyari, katman_raporu) -> int:
    """
    Hazırlanan tekil postu Telegram'da onaya sunar.

    ⚠️ `main()` içinde 30 satırlık bir blok olarak duruyordu. Davranış
    AYNEN korundu — yalnızca yeri değişti.

    Onay mesajı gider gitmez veritabanı push ediliyor: onay düğmesi
    GitHub'daki kopyaya bakıyor ve workflow'un son adımını beklersek
    kullanıcı o aralıkta onayladığında yayın job'ı turu göremiyor
    (17 Ağu 2026'da tam olarak bu oldu).
    """
    # --- 6b) Onaya sun ---
    # ⚠️ ALBÜM ID'LERİ SAKLANIYOR. Slayt görseli değiştirilip
    # onaylandığında albümün yenilenmesi gerekiyor (Telegram'da media
    # group atomik, tek fotoğraf düzenlenemiyor) ve bunun için eski
    # albümü silmek şart. Önce bu id'ler dönüyor ama atılıyordu.
    albom_idler = telegram_bot.slaytlari_gonder(urller, ["Haber", "Ayrıntı"])
    mesaj_id = telegram_bot.onay_iste(
        metin, len(urller),
        uyari=(uyari or ""),
        ozet=(f"🔴 SON DAKİKA ÖNERİSİ  ·  puan {taze['onem_puani']}/10\n"
              "⌛️ 24 saat boyunca onaya hazır bekler\n"
              + ("\n".join(katman_raporu) if katman_raporu else "")),
    )

    con.execute(
        "UPDATE haberler SET durum = 'onay_bekliyor', son_dakika = 1, "
        "telegram_message_id = ?, gorsel_url = ?, detay_url = ?, "
        "story_url = ?, gonderim_zamani = datetime('now') WHERE id = ?",
        (mesaj_id, urller[0], json.dumps(urller[1:]),
         story_url, aday["id"]),
    )
    con.commit()
    sayaci_artir(con)

    # Onay butonu GitHub'daki veritabanına bakıyor. Workflow'un
    # sonundaki commit adımını beklersek kullanıcı o aralıkta
    # onayladığında yayın job'ı turu göremiyor — 17 Ağu 2026'da
    # tam olarak bu oldu. O yüzden hemen kaydediyoruz.
    db_senkron.hemen_kaydet("Son dakika onaya sunuldu")

    log.info("son dakika onaya sunuldu (message_id=%s)", mesaj_id)
    return 0

def main(zorla_haber_id: int | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    kuru = "--kuru" in sys.argv
    if zorla_haber_id is None and "--haber-id" in sys.argv:
        zorla_haber_id = int(sys.argv[sys.argv.index("--haber-id") + 1])
    ayarlar = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    db.kur()
    con = db.baglan()
    ayar.uygula(con, ayarlar)

    # ⚠️ BOT DURAKLATILDI MI KONTROLÜ (Acil durum / Mute)
    # Kullanıcı elle bir haber seçtiyse (zorla_haber_id) engellenmez;
    # yalnızca otomatik periyodik tarama duraklatılır.
    if not zorla_haber_id:
        duraklatildi, kalan = yonetim.duraklatildi_mi(con)
        if duraklatildi:
            log.info("Bot duraklatılmış durumda (kalan: %s), son dakika kontrolü atlandı.", kalan)
            con.close()
            return 0

    try:
        # --- 0) Kota/ağ hatası almış haberleri havuza geri al ---
        # Gemini 429 verdiğinde haber 'hata' durumunda kalıyor ve bir
        # daha aday olamıyor. Bu haberin kusuru değil; metni varsa
        # 'metin_hazir', yoksa 'yeni' olarak havuza dönüyor.
        # son_dakika işareti de temizleniyor: yayınlanmamış bir turdan
        # kalan işaret haberi `aday_bul`un gözünden düşürüyor ("bu haber
        # zaten son dakika yapıldı" sanılıyor) ve haber bir daha
        # seçilemiyor.
        onarilan = con.execute(
            "UPDATE haberler SET hata_mesaji = NULL, son_dakika = 0, "
            "telegram_message_id = NULL, "
            "durum = CASE WHEN ig_baslik IS NOT NULL THEN 'metin_hazir' "
            "             ELSE 'yeni' END "
            "WHERE durum = 'hata'"
        ).rowcount

        # Yayınlanmamış ama son_dakika işareti takılı kalmış haberler
        # (iptal edilmiş turlardan artakalan) da temizleniyor.
        onarilan += con.execute(
            "UPDATE haberler SET son_dakika = 0 "
            "WHERE son_dakika = 1 AND durum NOT IN ('yayinlandi', 'onay_bekliyor')"
        ).rowcount
        con.commit()
        if onarilan:
            log.info("%s haber 'hata' durumundan havuza döndürüldü", onarilan)

        # --- 1) Süresi geçmiş turu düşür ---
        planli_yayinlari_isle(con, ayarlar)
        suresi_gecmisi_iptal_et(con, ayarlar)

        # --- 2) Zaten onay bekleyen son dakika varsa yenisini kurma ---
        #
        # ⚠️ KULLANICI SEÇİMİNDE BU KURAL UYGULANMIYOR. Öneri
        # listesinden birden fazla haber seçilebiliyor ve hepsi sırayla
        # hazırlanıyor; ilk tur onay beklerken durursa ikinci ve üçüncü
        # seçim hiç üretilmez, kullanıcı da neden gelmediğini anlamaz.
        # Kendiliğinden kurulan turlarda kural geçerli: aynı anda iki
        # otomatik tekil post onayda bekleyip karışmasın.
        # ⚠️ BU KAPI ARTIK ÖNERİYİ DURDURMUYOR — yalnızca TUR KURMAYI.
        #
        # Ölçüldü (20 Ağu 2026): onay ömrü 60 dakika, kontrol 30 dakikada
        # bir çalışıyor. Yani onayda bekleyen HER tur, iki kontrolü
        # öneri göstermeden yakıyordu. Son dört günde 25 tekil post
        # yayınlandı; her biri +1 saatlik öneri sessizliği demek.
        # Kullanıcı "yarım saatte bir gelen öneriler gelmiyor" derken
        # bunu görüyordu.
        #
        # Öneri göndermek YAYIN DEĞİL, yalnızca başlık listesi sunmak.
        # Mükerrer gönderimi `oneri_gonderildi` ve `sadece_tur`
        # işaretleri zaten engelliyor.
        acik_tur_var = False
        if not zorla_haber_id:
            acik_tur_var = con.execute(
                "SELECT COUNT(*) FROM haberler WHERE son_dakika = 1 "
                "AND durum = 'onay_bekliyor'"
            ).fetchone()[0] > 0
            if acik_tur_var:
                log.info("onay bekleyen tur var — tur kurulmayacak, "
                         "öneri akışı yine de çalışacak")

        # --- 3) Günlük sınır ---
        azami = ayarlar["genel"].get("son_dakika_gunluk_azami", 2)
        bugun = bugunku_sayi(con)
        if bugun >= azami:
            # ⚠️ İNSAN SEÇİMİ SINIRDAN MUAF. Kullanıcı Telegram'da bir
            # haberi açıkça seçtiyse makinenin onu sessizce reddetmesi
            # yanlış — 21 Ağu 2026'da tam bu oldu: iki haber seçildi,
            # job "başarılı" döndü, hiçbir şey üretilmedi ve kullanıcı
            # "hazırlanıyor" yazısında kaldı.
            if zorla_haber_id:
                log.info("günlük sınır dolu (%s/%s) ama haber elle "
                         "seçilmiş, devam ediliyor", bugun, azami)
                telegram_bot.mesaj_gonder(
                    f"ℹ️ Bugünkü tekil post sınırı dolu ({bugun}/{azami}) "
                    "ama sen seçtiğin için hazırlanıyor.")
            else:
                log.info("günlük son dakika sınırı dolu (%s/%s)",
                         bugun, azami)
                return 0

        # --- 4) Taze haber çek, sonra aday ara ---
        # Yalnızca yüksek ağırlıklı gündem kaynakları — Actions kotası
        # için (bkz. fetch_news.haberleri_cek). Akşam turu hepsini tarıyor.
        rapor = fetch_news.haberleri_cek(
            ayarlar,
            asgari_agirlik=ayarlar["genel"].get("son_dakika_asgari_agirlik", 9),
        )
        log.info("RSS: %s yeni haber", rapor["eklenen"])

        if acik_tur_var:
            # Tur kurulamaz ama öneri gönderilebilir.
            onerileri_gonder(con, ayarlar, kuru=kuru)
            return 0

        if zorla_haber_id:
            # Kullanıcı Telegram'da bir ÖNERİYİ seçti. Eşik/tazelik
            # denetimleri burada uygulanmıyor — insan zaten bakıp
            # seçti, makinenin ikinci kez elemesi anlamsız olurdu.
            aday = con.execute("SELECT * FROM haberler WHERE id = ?",
                               (zorla_haber_id,)).fetchone()
            if aday is None:
                log.error("haber bulunamadı: %s", zorla_haber_id)
                return 1
            if not aday["ig_baslik"]:
                log.info("seçilen haberin metni üretiliyor: %s",
                         aday["baslik_orj"][:60])
                metinleri_uret(ayarlar=ayarlar, haberler=[aday])
                aday = con.execute("SELECT * FROM haberler WHERE id = ?",
                                   (zorla_haber_id,)).fetchone()
            if not aday or not aday["ig_baslik"]:
                log.error("metin üretilemedi, tur kurulamadı")
                telegram_bot.hata_bildir(
                    "Seçilen haber hazırlanamadı",
                    "Gemini metni üretemedi (kota ya da güvenlik filtresi "
                    "olabilir). Haber havuzda duruyor, tekrar denenebilir.")
                return 1
        else:
            # Metni ZATEN hazır bir aday var mı? (daha önce seçilmiş
            # ama tur kurulamamış olabilir)
            aday = aday_bul(con, ayarlar)

        if not zorla_haber_id and not aday:
            # ⚠️ BURADA ARTIK TAM METİN ÜRETİLMİYOR.
            # Eskiden taze haberlere tam metin üretilir (~4400 token),
            # sonra puanına bakılıp eşiği geçmiyorsa ATILIRDI — üretilen
            # metnin çoğu çöpe gidiyordu ve kontrol job'ı 2.81 dk
            # sürüyordu (Actions kotasının en büyük kalemi).
            #
            # Şimdi başlıklar toplu ve ucuz biçimde puanlanıp kullanıcıya
            # öneriliyor; tam metin yalnızca seçilen haber için üretiliyor.
            sonuc = onerileri_gonder(con, ayarlar, kuru=kuru)
            if sonuc == METIN_URETILDI:
                # Yüksek puanlı bir habere metin üretildi; artık
                # otomatik yayın akışına girebilir.
                aday = aday_bul(con, ayarlar)
            if not aday:
                log.info("metni hazır aday yok — öneri aşamasında kalındı")
                return 0

        log.info("aday: [%s] %s", aday["onem_puani"], aday["ig_baslik"])

        katman_raporu: list[str] = []

        # --- 5) İki slaytı üret ---
        sonuclar = slaytlar.son_dakika_uret(aday, ayarlar, con)
        taze = con.execute("SELECT * FROM haberler WHERE id = ?",
                           (aday["id"],)).fetchone()

        # Story carousel'e girmiyor, ayrı yükleniyor.
        carousel = [s for s in sonuclar if s["katman"] != "story"]
        story_slayt = next((s for s in sonuclar if s["katman"] == "story"), None)

        yuklemeler = upload_image.hepsini_yukle(
            [s["yol"] for s in carousel], ayarlar
        )
        urller = [y["url"] for y in yuklemeler]

        story_url = None
        if story_slayt:
            try:
                story_url = upload_image.gorsel_yukle(
                    story_slayt["yol"], ayarlar
                )["url"]
            except Exception as e:
                log.warning("story yüklenemedi: %s", e)

        metin = caption.son_dakika_caption(taze, sonuclar, ayarlar)
        uyari, isaretli = dogrula.turu_dogrula([taze])

        if kuru:
            print("\n" + "=" * 70)
            print("KURU ÇALIŞMA — Telegram'a gönderilmedi")
            print("=" * 70)
            print(metin)
            print("=" * 70)
            for s in sonuclar:
                print(f"  [{s['katman']:<8}] {s['yol']}")
            return 0

        # --- 6a) GECE: dört katmanlı denetimden geçerse otomatik yayınla ---
        yayinlandi, katman_raporu = gece_otomatik_yayinla(
            con, ayarlar, aday, taze, urller, story_url, metin)
        if yayinlandi:
            return 0


        return onaya_sun(con, ayarlar, aday, taze, urller,
                        story_url, metin, uyari, katman_raporu)

    except Exception as e:
        log.exception("son dakika turu hazırlanamadı")
        # Ham metni her durumda sakla — "🔍 Ham hata metni" düğmesi
        # bunu okuyor.
        hata_bildir.son_ham_hata_kaydet(traceback.format_exc())
        # ⚠️ KULLANICI SEÇİMİNDE BURADAN BİLDİRİM GÖNDERİLMİYOR.
        # `onay_isle.oneriyi_hazirla` zaten hangi haberlerin
        # hazırlanamadığını ve DOĞRU tekrar düğmesini ("bu haberleri
        # yeniden dene") gönderiyor. Buradan da bildirirsek kullanıcı
        # iki mesaj alıyor ve buradaki düğme yanlış oluyor: "Turu
        # yeniden hazırla" AKŞAM turunu tetikliyor, seçilen haberi
        # değil.
        if not kuru and not zorla_haber_id:
            hata_bildir.bildir("Son dakika turu hazırlanamadı", e, nerede="son_dakika.py")
        return 1

    finally:
        # ⚠️ BAĞLANTIYI KAPAT — "database is locked" hatasının ASIL
        # sebebi buydu (20 Ağu 2026).
        #
        # `main()` bir bağlantı açıyor ama hiç kapatmıyordu. Tek
        # çalıştırmada zararsızdı (süreç bitince kapanıyor), ama çoklu
        # seçimde `onay_isle` bu fonksiyonu ARKA ARKAYA çağırıyor:
        # birinci çağrının bağlantısı hâlâ açıkken ikincisi yeni bir
        # bağlantı açıp yazmaya çalışıyor ve kilide takılıyordu.
        # Kullanıcı "2 tanesini seçtim birini oluşturdu" derken tam
        # olarak bunu görüyordu.
        #
        # WAL modu tek başına yetmiyor: WAL okuyucu-yazar
        # eşzamanlılığını çözüyor, İKİ YAZARI değil.
        try:
            con.commit()
        except Exception:                             # noqa: BLE001
            pass
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
