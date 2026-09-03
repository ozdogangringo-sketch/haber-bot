"""
SÖZLEŞME TESTLERİ — "bu koşulda şu olmalı" denetimleri.

NİYE VAR:
    `test_0_butunluk.py` kodun ÇAĞRILABİLİR olduğunu denetliyor:
    fonksiyon var mı, imza uyuyor mu. Ama kodun DOĞRU DAVRANDIĞINI
    denetlemiyor. Bu oturumda çıkan hataların çoğu tam o boşluktaydı:

      * mükerrer engeli üç yerde gerekiyordu, ikisine konmuştu
        (aynı olay bir saat arayla iki kez yayınlandı)
      * `instagram.deneme_sayisi` config'de vardı, kod okumuyordu
      * `TAZELIK_SAAT` sabit koda gömülüydü, config'deki değer ölüydü
      * prompt'un bir kopyası güncellendi, ikincisi unutuldu
      * buton listesi Python'da değişti, Worker'da değişmedi

    Hepsinin ortak deseni: AYNI KURAL BİRDEN FAZLA YERDE YAŞIYOR VE
    BİRİ UNUTULUYOR. Bu testler o unutmayı yakalamak için var.

NE YAPMIYOR:
    Ağa çıkmıyor, gerçek veritabanına DOKUNMUYOR (geçici kopya
    kullanıyor), para harcamıyor. Her değişiklikten sonra
    çalıştırılabilir.

ÇALIŞTIRMA:
    python scripts/test_7_sozlesme.py
"""

import ast
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
sys.path.insert(0, str(KOK / "scripts"))

import yaml                                          # noqa: E402

from src import secim                                # noqa: E402

SONUCLAR: list[tuple[bool, str, str]] = []


def denetle(kosul: bool, ad: str, ayrinti: str = "") -> None:
    SONUCLAR.append((bool(kosul), ad, ayrinti))


# ─────────────────────────────────────────────────────────────
#  1. MÜKERRER ENGELİ — HER AKIŞTA UYGULANMALI
# ─────────────────────────────────────────────────────────────
#
# ⚠️ 20 Ağu 2026: "Rusya'nın Kiev ve Jitomir'e füzeli saldırısı" sabah
# turunda yayınlandı, bir saat sonra "Rus ordusu Kiev'i füzelerle
# vurdu" TEKİL post olarak çıktı. Kural doğruydu ama `aday_bul`'da
# uygulanmıyordu. Bu test o boşluğu yakalar.

def gecici_db() -> sqlite3.Connection:
    """Bellekte test veritabanı — gerçek veriye dokunmaz."""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE haberler (
            id INTEGER PRIMARY KEY, kaynak TEXT, kategori TEXT,
            agirlik INTEGER, baslik_orj TEXT, link TEXT, ozet_orj TEXT,
            yayin_tarihi TEXT, cekilme_zamani TEXT, ig_baslik TEXT,
            onem_puani INTEGER, durum TEXT, son_dakika INTEGER,
            gonderim_zamani TEXT, oneri_gonderildi INTEGER DEFAULT 0,
            makale_metni TEXT, tur TEXT
        );
    """)
    return con


def test_mukerrer_engeli() -> None:
    con = gecici_db()
    simdi = datetime.now(timezone.utc)
    # Dün yayınlanmış haber
    con.execute(
        "INSERT INTO haberler (id, kaynak, kategori, agirlik, baslik_orj, "
        "ig_baslik, durum, gonderim_zamani, yayin_tarihi, onem_puani) "
        "VALUES (1,'TRT','turkiye',10,?,?,'yayinlandi',?,?,9)",
        ("Rusya'nın Kiev ve Jitomir'e füzeli saldırısında en az 10 kişi hayatını kaybetti",
         "Rusya'nın Kiev ve Jitomir'e füzeli saldırısında en az 10 kişi hayatını kaybetti",
         (simdi - timedelta(hours=3)).isoformat(),
         (simdi - timedelta(hours=4)).isoformat()))
    con.commit()

    ayarlar = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    gecmis = secim.yayinlanmis_konular(con, ayarlar)
    denetle(len(gecmis) == 1, "yayinlanmis_konular yayınlanmış haberi buluyor",
            f"bulunan: {len(gecmis)}")

    # Aynı olayın başka kaynaktan gelen hali elenmeli
    benzer = "Rus ordusu Kiev'i füzelerle vurdu: En az 8 kişi hayatını kaybetti"
    k, i = secim.konu_imzasi(benzer)
    esik = ayarlar["secim"]["gecmis_ortak_kelime_esigi"]
    carpisma = any(len(k & ok) >= esik and (i & oi) for ok, oi in gecmis)
    denetle(carpisma, "aynı olayın farklı kaynaktan hali TEKRAR sayılıyor",
            f"eşik={esik}")

    # Alakasız haber elenmemeli (yanlış pozitif denetimi)
    alakasiz = "İstanbul'da barajların doluluk oranı yüzde 50'nin altına düştü"
    k2, i2 = secim.konu_imzasi(alakasiz)
    yanlis = any(len(k2 & ok) >= esik and (i2 & oi) for ok, oi in gecmis)
    denetle(not yanlis, "alakasız haber YANLIŞLIKLA elenmiyor")
    con.close()


def test_mukerrer_her_akista_var() -> None:
    """
    ⚠️ ASIL DENETİM: kural üç akışta da uygulanıyor mu?

    Kod metnine bakıyoruz — `yayinlanmis_konular` çağrısı aday seçen
    her fonksiyonda geçmeli. 1p'de tam olarak bu eksikti.
    """
    kaynak = (KOK / "scripts" / "son_dakika.py").read_text(encoding="utf-8")
    agac = ast.parse(kaynak)
    beklenen = {"aday_bul", "onerileri_gonder"}
    for dugum in ast.walk(agac):
        if not isinstance(dugum, ast.FunctionDef) or dugum.name not in beklenen:
            continue
        govde = ast.get_source_segment(kaynak, dugum) or ""
        # ⚠️ İKİ KABUL EDİLEBİLİR YOL:
        #   1. `aday.Baglam` kullanmak — kural tek kapıdan geliyor
        #   2. doğrudan `yayinlanmis_konular` çağırmak (eski yol)
        # Aday kapısı tercih edilen; eski yol henüz bağlanmamış
        # akışlar için geçerli kalıyor.
        korumali = ("yayinlanmis_konular" in govde
                    or "aday.Baglam" in govde
                    or "Baglam.kur" in govde)
        denetle(korumali,
                f"{dugum.name}() geçmiş tekrar denetimi yapıyor",
                "aday seçen her akışta gerekli (aday.Baglam ya da "
                "yayinlanmis_konular)")
        beklenen.discard(dugum.name)
    for eksik in beklenen:
        denetle(False, f"{eksik}() bulunamadı", "fonksiyon silinmiş olabilir")

    secim_kaynak = (KOK / "src" / "secim.py").read_text(encoding="utf-8")
    # `tur_icin_sec` aday kapısına bağlandı; kural oradan geliyor.
    denetle("aday.Baglam.kur(aday.TUR" in secim_kaynak
            or "yayinlanmis_konular(con, ayarlar)" in secim_kaynak,
            "tur_icin_sec() geçmiş tekrar denetimi yapıyor",
            "aday.Baglam ya da yayinlanmis_konular")


# ─────────────────────────────────────────────────────────────
#  2. CONFIG ↔ KOD TUTARLILIĞI
# ─────────────────────────────────────────────────────────────
#
# ⚠️ `instagram.deneme_sayisi` config'de tanımlıydı ama kod onu HİÇ
# okumuyordu (`range(1,4)` sabitti). Ayar değiştirmek hiçbir şeyi
# değiştirmiyordu ve bu ancak elle okuyarak fark edildi.

def test_config_anahtarlari_okunuyor() -> None:
    cfg = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    tum_kod = "\n".join(
        p.read_text(encoding="utf-8")
        for klasor in ("src", "scripts")
        for p in (KOK / klasor).glob("*.py")
    )

    # Yalnızca ayar bloklarını denetliyoruz; `kaynaklar` liste ve
    # `sosyal.kanallar` gibi veri alanları koda ada göre girmiyor.
    atlanacak = {"kaynaklar", "icerik_filtresi"}
    olu = []
    for blok, icerik in cfg.items():
        if blok in atlanacak or not isinstance(icerik, dict):
            continue
        for anahtar in icerik:
            if not isinstance(anahtar, str):
                continue
            if f'"{anahtar}"' not in tum_kod and f"'{anahtar}'" not in tum_kod:
                olu.append(f"{blok}.{anahtar}")
    denetle(not olu, "config'deki her ayar kod tarafından okunuyor",
            f"ölü ayar: {', '.join(olu)}" if olu else "")


def test_sabit_kodlanmis_esik_yok() -> None:
    """
    ⚠️ `TAZELIK_SAAT = 3` sabit koda gömülüydü ve config'deki değer
    ölüydü; tekil post 5 saat boyunca hiç çıkmadı, sebebi ancak
    ölçerek bulundu.
    """
    kaynak = (KOK / "scripts" / "son_dakika.py").read_text(encoding="utf-8")
    # Eşik/tazelik sabitleri fonksiyon üzerinden okunmalı
    denetle("_tazelik_saat(" in kaynak,
            "tazelik değeri config'den okunuyor (sabit değil)")
    denetle(re.search(r"^TAZELIK_SAAT\s*=\s*\d+", kaynak, re.M) is None,
            "sabit TAZELIK_SAAT tanımı kaldırılmış")


# ─────────────────────────────────────────────────────────────
#  3. AYNI İŞİ YAPAN İKİNCİ KOD YOLU
# ─────────────────────────────────────────────────────────────
#
# ⚠️ En sık tekrarlayan desen. Örnekler: prompt'un iki kopyası,
# Worker ile Python'daki buton listeleri, YAML'daki ham git komutu.

def test_prompt_kopyalari_tutarli() -> None:
    kaynak = (KOK / "src" / "generate_text.py").read_text(encoding="utf-8")
    # Puan bandı hem tam metin hem toplu puanlama promptunda olmalı
    denetle(kaynak.count("9 VERMEKTEN ÇEKİNME") >= 2,
            "puan bandı İKİ prompta da uygulanmış",
            "tam metin + toplu puanlama")
    denetle(kaynak.count("AÇIKLAMA HABERİ İLE OLAY HABERİNİ AYIR") >= 2,
            "açıklama/olay ayrımı İKİ prompta da uygulanmış")


def test_worker_python_buton_uyumu() -> None:
    """
    ⚠️ Buton düzeni iki yerde tanımlı: `telegram_bot.py` ve
    `worker/index.js`. Birini değiştirip diğerini unutmak
    "tanınmayan komut" hatası veriyor.
    """
    worker = (KOK / "worker" / "index.js").read_text(encoding="utf-8")
    tg = (KOK / "src" / "telegram_bot.py").read_text(encoding="utf-8")

    # Python'un ürettiği callback_data'lar Worker tarafından tanınmalı
    uretilen = set(re.findall(r'"callback_data":\s*f?"([a-z_]+)', tg))
    for komut in sorted(uretilen):
        # Parametreli komutlar Worker'da regex ile karşılanıyor
        taniniyor = (f'"{komut}"' in worker
                     or f"{komut}:" in worker
                     or komut in worker)
        denetle(taniniyor, f"worker '{komut}' komutunu tanıyor")


def test_yaml_ham_git_komutu_yok() -> None:
    """
    ⚠️ 1d/1f: `git rebase` YAML'da çıplak kullanılınca `haber.db`
    ikili dosyasında çakışıp repoyu kilitliyordu. Python tarafı
    düzeltilmiş ama YAML'lar unutulmuştu.
    """
    for yol in (KOK / ".github" / "workflows").glob("*.yml"):
        # ⚠️ YORUM SATIRLARINI ATLA. Bu dosyalarda "çıplak git rebase
        # kullanma" UYARISI yorum olarak duruyor; onu ihlal sanmak
        # yanlış pozitif üretiyor (ilk sürümde tam olarak bu oldu).
        satirlar = [s for s in yol.read_text(encoding="utf-8").splitlines()
                    if not s.strip().startswith("#")]
        denetle("git rebase" not in "\n".join(satirlar),
                f"{yol.name}: çıplak 'git rebase' yok",
                "db_kaydet.py kullanılmalı")


# ─────────────────────────────────────────────────────────────
#  4. EŞİK MANTIĞI
# ─────────────────────────────────────────────────────────────

def test_oneri_esigi_yayin_esiginden_dusuk() -> None:
    """
    ⚠️ Toplu başlık puanlaması tam metin puanlamasından ~1.6 puan
    düşük veriyor (ölçüldü). Öneri eşiği yayın eşiğiyle aynı olursa
    hiçbir başlık geçemiyor ve öneri akışı sessizce kilitleniyor.
    """
    cfg = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    g = cfg["genel"]
    yayin = g.get("son_dakika_kategori_esikleri", {})
    oneri = g.get("oneri_kategori_esikleri", {})
    denetle(bool(oneri), "öneri eşikleri tanımlı")
    for kat, deger in oneri.items():
        y = yayin.get(kat)
        if y is None:
            continue
        denetle(deger < y, f"öneri eşiği ({kat}) yayın eşiğinden düşük",
                f"öneri={deger} yayın={y}")


def test_gece_esigi_gunduzden_yuksek() -> None:
    cfg = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    g = cfg["genel"]
    gece = g.get("gece_puan_esigi", 9)
    gunduz = g.get("son_dakika_puan_esigi", 8)
    denetle(gece > gunduz, "gece yayın eşiği gündüzden yüksek",
            f"gece={gece} gündüz={gunduz}")


# ─────────────────────────────────────────────────────────────
#  5. INSTAGRAM SINIRLARI
# ─────────────────────────────────────────────────────────────

def test_carousel_siniri() -> None:
    """Instagram carousel sınırı 10 — API dokümanından doğrulandı."""
    cfg = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    slayt = cfg["gorsel"]["slayt_sayisi"]
    denetle(2 <= slayt <= 10, "slayt sayısı Instagram sınırında (2-10)",
            f"slayt_sayisi={slayt}")



# ─────────────────────────────────────────────────────────────
#  6. ADAY KAPISI — kuralların tek yerde toplanmış hali
# ─────────────────────────────────────────────────────────────
#
# ⚠️ Bu kurallar önce üç ayrı fonksiyona dağılmıştı ve biri hep
# unutuluyordu (1j, 1p). `src/aday.py` hepsini tek kapıya topladı;
# bu testler o kapının her kuralı gerçekten uyguladığını doğruluyor.

def _sahte_haber(**degisiklik) -> dict:
    from datetime import datetime, timedelta, timezone
    temel = {
        "id": 1, "kaynak": "TRT", "kategori": "turkiye", "agirlik": 10,
        "baslik_orj": "Ankara'da metro seferleri yarın sabaha kadar uzatıldı",
        "ig_baslik": "Ankara'da metro seferleri yarın sabaha kadar uzatıldı",
        "onem_puani": 9, "durum": "metin_hazir", "son_dakika": 0,
        "yayin_tarihi": (datetime.now(timezone.utc)
                         - timedelta(hours=1)).isoformat(),
    }
    temel.update(degisiklik)
    return temel


class _SahteSatir(dict):
    """sqlite3.Row gibi davranan sözlük — aday.py `.keys()` kullanıyor."""


def test_aday_kapisi_kurallari() -> None:
    from src import aday

    con = gecici_db()
    ayarlar = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    b = aday.Baglam.kur("tekil", ayarlar, con)
    # Gece kuralı testi bozmasın: eşikleri sabitliyoruz
    b.esikler = {"turkiye": 8, "spor": 7}
    b.varsayilan_esik = 8
    b.tazelik_saat = 5
    b.kategori_azami = 3
    b.kategori_sayaci = {}
    b.gecmis_konular = []

    uygun, sebep = aday.uygun_mu(_SahteSatir(_sahte_haber()), b)
    denetle(uygun, "aday kapısı: uygun haber GEÇİYOR", sebep)

    from datetime import datetime, timedelta, timezone
    bayat = _sahte_haber(yayin_tarihi=(datetime.now(timezone.utc)
                                       - timedelta(hours=30)).isoformat())
    uygun, sebep = aday.uygun_mu(_SahteSatir(bayat), b)
    denetle(not uygun and "bayat" in sebep,
            "aday kapısı: BAYAT haber eleniyor", sebep)

    dusuk = _sahte_haber(onem_puani=5)
    uygun, sebep = aday.uygun_mu(_SahteSatir(dusuk), b)
    denetle(not uygun and "puan" in sebep,
            "aday kapısı: EŞİK ALTI eleniyor", sebep)

    b.kategori_sayaci = {"turkiye": 3}
    uygun, sebep = aday.uygun_mu(_SahteSatir(_sahte_haber()), b)
    denetle(not uygun and "kategori" in sebep,
            "aday kapısı: KATEGORİ SINIRI uygulanıyor", sebep)
    b.kategori_sayaci = {}

    # Geçmişte yayınlanmış konu
    gecmis_baslik = "Ankara'da metro seferleri gece boyunca uzatıldı"
    # ⚠️ `konu_imzasi` — üretim kodu da bunu kullanıyor. Test farklı
    # bir imza kullanırsa gerçek davranışı ölçmemiş olur.
    b.gecmis_konular = [secim.konu_imzasi(gecmis_baslik)]
    uygun, sebep = aday.uygun_mu(_SahteSatir(_sahte_haber(onem_puani=8)), b)
    denetle(not uygun and "yayınlandı" in sebep,
            "aday kapısı: GEÇMİŞ TEKRARI eleniyor", sebep)

    # ⚠️ Muafiyet: büyük olay günün özetinde de yer alabilmeli
    uygun, sebep = aday.uygun_mu(_SahteSatir(_sahte_haber(onem_puani=9)), b)
    denetle(uygun, "aday kapısı: 9+ puan geçmiş denetiminden MUAF", sebep)
    b.gecmis_konular = []

    # Liste içi tekrar
    b._secilenler = []
    aday.sec([_SahteSatir(_sahte_haber())], b)
    uygun, sebep = aday.uygun_mu(
        _SahteSatir(_sahte_haber(id=2, onem_puani=8)), b)
    denetle(not uygun and "bu seçimde" in sebep,
            "aday kapısı: AYNI SEÇİMDE tekrar eleniyor", sebep)
    con.close()


def test_aday_baglamlari_farkli_esik() -> None:
    """Üç bağlam farklı eşik kullanmalı; karışırsa akış kilitlenir."""
    from src import aday

    con = gecici_db()
    ayarlar = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    tekil = aday.Baglam.kur("tekil", ayarlar, con)
    oneri = aday.Baglam.kur("oneri", ayarlar, con)

    denetle(oneri.esik("turkiye") < tekil.esik("turkiye"),
            "öneri eşiği tekil post eşiğinden DÜŞÜK",
            f"öneri={oneri.esik('turkiye')} tekil={tekil.esik('turkiye')}")
    denetle(oneri.kategori_azami == tekil.kategori_azami,
            "öneri ve tekil aynı kategori sınırını kullanıyor")

    try:
        aday.Baglam.kur("olmayan_baglam", ayarlar, con)
        denetle(False, "bilinmeyen bağlam REDDEDİLİYOR")
    except ValueError:
        denetle(True, "bilinmeyen bağlam REDDEDİLİYOR")
    con.close()


def test_planlanmis_yayin_zaman_asimlarindan_muaf() -> None:
    """
    Planlanmış yayın (yayınla > "2 saat sonra") turu yayın anına kadar
    `onay_bekliyor` durumunda bekletiyor. Bu projede turu bekletmeyi
    zaman aşımına bağlayan İKİ ayrı mekanizma var ve ikisi de bu turu
    yayın anı gelmeden öldürebilir:

      * `son_dakika.suresi_gecmisi_iptal_et` — 60 dakikada iptal eder,
        yani "1 saat sonra" planı bile kendini iptal ederdi;
      * `hatirlat.py` — 6 saat sonra havuza döndürür ve o ana kadar
        her saat gereksiz hatırlatma atar.

    ⚠️ Bu denetim tam olarak bu projenin tekrar eden hata sınıfı için
    var: kural doğru yazılıyor ama AYNI İŞİ YAPAN diğer kod yolunda
    unutuluyor (bkz. CLAUDE.md 1j, 1p, 1f).
    """
    for dosya, fonksiyon in (("scripts/son_dakika.py", "60 dakikalık iptal"),
                             ("scripts/hatirlat.py", "6 saatlik kapatma")):
        kaynak = (KOK / dosya).read_text(encoding="utf-8")
        # Turu seçen SELECT'te muafiyet şartı olmalı
        denetle("planlanan_yayin IS NULL" in kaynak,
                f"planlı yayın {fonksiyon} kuralından muaf ({dosya})",
                "planlanan_yayin IS NULL şartı yok — planlanan tur "
                "yayın anı gelmeden havuza döner")

    # Kullanıcıya söylenen PENCERE, kontrolün gerçek aralığından kısa
    # olmamalı — kısa olursa düğme tutamayacağı bir söz verir.
    oi = (KOK / "scripts/onay_isle.py").read_text(encoding="utf-8")
    pencere = re.search(r'timedelta\(minutes=(\d+)\)\):%H:%M\} arasında', oi)
    denetle(bool(pencere), "yayın planı mesajı bir PENCERE söylüyor",
            "tek bir saat söyleniyor — cron atlanınca yalan olur")
    if pencere:
        # son-dakika.yml'deki en büyük gündüz aralığı
        yml = (KOK / ".github/workflows/son-dakika.yml").read_text(encoding="utf-8")
        gunduz = [c for c in re.findall(r'cron:\s*"([^"]+)"', yml)
                  if not re.match(r'^\S+\s+(20|23|2)[,\s]', c)]
        denetle(int(pencere.group(1)) >= 90,
                "söylenen pencere kontrol aralığından kısa değil",
                f"pencere {pencere.group(1)} dk ama cron 90 dakikada bir: {gunduz}")


def test_mukerrer_instagrama_da_bakiyor() -> None:
    """
    Mükerrer denetimi yalnızca veritabanına güvenemez.

    20 Ağu 2026'da ölçüldü: "Merkez Bankası rezervleri" TR 17:47'de,
    "TUFAN Kamikaze İDA" TR 17:19'da Instagram'da yayınlandı ama
    veritabanında ikisinin de hiçbir kaydı 'yayinlandi' değildi ve
    ikisi de akşam turuna yeniden girdi. Aynı turdaki Endonezya haberi
    DB'de doğru kayıtlıydı ve kural onu YAKALADI — yani kural sağlamdı,
    beslendiği veri eksikti.
    """
    kaynak = (KOK / "src/secim.py").read_text(encoding="utf-8")
    denetle("_instagram_gecmisi" in kaynak,
            "mükerrer denetimi Instagram geçmişini de okuyor",
            "yalnızca veritabanına bakıyor — DB bozulursa mükerrer geçer")

    ig = (KOK / "src/instagram.py").read_text(encoding="utf-8")
    denetle("def son_yayinlanan_basliklar" in ig,
            "instagram.son_yayinlanan_basliklar() var")

    # ⚠️ Her post KENDİ içinde değerlendirilmeli. İlk yazımda
    # "numarasız caption'ın ilk satırı manşettir" kuralı global listeye
    # bakıyordu ve ilk posttan sonra tekil postların manşetleri hiç
    # okunmadı — düzeltilen kusur tam olarak buydu.
    denetle("post_basliklari" in ig,
            "caption ayrıştırması post bazında yapılıyor",
            "global listeye bakılıyor: tekil post manşetleri okunmaz")


def test_ertelemede_menu_kaliyor() -> None:
    """
    "1 saat ertele" turu KAPATMIYOR, sadece bekletiyor. Menü kalkarsa
    tur kilitleniyor: ne yayınlanabiliyor ne atlanabiliyor.

    20 Ağu 2026: kullanıcı 20:58'de erteledi, menü silindi, 21:58'de
    gelen hatırlatma "yukarıdaki mesajdan yayınlayabilirsin" dedi ama
    o mesajda hiçbir düğme yoktu.
    """
    kaynak = (KOK / "scripts/onay_isle.py").read_text(encoding="utf-8")
    govde = kaynak.split("def ertele(")[1].split("\ndef ")[0]
    # ⚠️ Docstring'e değil GERÇEK ÇAĞRIYA bak: bu fonksiyonun
    # açıklamasında "sonucu_yaz KULLANMA" uyarısı yazılı ve düz metin
    # araması onu ihlal sanıyordu.
    denetle("telegram_bot.sonucu_yaz(" not in govde,
            "ertele() butonları kaldıran sonucu_yaz'ı ÇAĞIRMIYOR",
            "sonucu_yaz butonları siliyor — ertelenen tur kilitlenir")
    denetle("menuyu_geri_koy" in govde,
            "ertele() menüyü geri koyuyor")


def test_ayri_mesajdaki_dugme_tur_id_tasiyor() -> None:
    """
    Onay mesajından BAŞKA bir mesajda duran her düğme, hedef turun
    id'sini kendi içinde taşımalı.

    Worker düğmeye basıldığında `cb.message.message_id` gönderiyor —
    yani düğmenin BULUNDUĞU mesajın id'sini. Ayrı bir mesajdaki düğme
    için bu değer turu göstermez.

    ⚠️ İKİ KEZ YAŞANDI:
      * `kaldir` (yayın sonucu mesajı) — çözülmüş, id gömülü.
      * `haber_sec` (alternatif mesajı) — 20 Ağu 2026, düğmeye basıldı
        ve job "mesaj_id=487 için haber bulunamadı" ile düştü; tur
        474'tü. Aynı tuzak, yeni kod yolu.
    """
    # ⚠️ BU TUZAK DÖRT KEZ TEKRARLADI: kaldir, haber_sec, gorsel_kabul,
    # gorsel_yeni. Ayrı mesajda duran HER düğme tur id'sini taşımalı.
    tb = (KOK / "src/telegram_bot.py").read_text(encoding="utf-8")
    oi = (KOK / "scripts/onay_isle.py").read_text(encoding="utf-8")
    # (dosya, fonksiyon, komut, callback_data'da bulunması gereken değişken)
    for kaynak, menu, komut, degisken in (
            (tb, "alternatif_menusu", "haber_sec", "tur_mesaj_id"),
            (tb, "alternatif_menusu", "haber_vazgec", "tur_mesaj_id"),
            (tb, "sonucu_yaz", "kaldir", "message_id"),
            (oi, "slayt_islemi", "gorsel_kabul", "mesaj_id"),
            (oi, "slayt_islemi", "gorsel_yeni", "mesaj_id")):
        govde = kaynak.split(f"def {menu}(")[1].split("\ndef ")[0]
        satirlar = [s for s in govde.splitlines() if f"{komut}:" in s]
        denetle(bool(satirlar) and any(degisken in s for s in satirlar),
                f"{menu}(): '{komut}' düğmesi tur mesaj id'sini taşıyor",
                f"callback_data'da {degisken} yok — Worker'ın gönderdiği "
                "mesaj id'si o düğmenin bulunduğu mesaja ait, turu "
                "göstermez")


def test_havuza_donen_haber_metnini_koruyor() -> None:
    """
    Onaylanmayan tur havuza dönerken METNİ OLAN haber 'metin_hazir'
    olmalı, 'yeni' değil.

    'yeni' yapılırsa sonraki tur o haberi Gemini'ye TEKRAR gönderiyor
    ve zaten üretilmiş metin için ikinci kez kota harcanıyor. Ücretsiz
    kota model başına günde 20 istek — bu israf doğrudan turu düşürüyor.

    ⚠️ Kural İKİ YERDE yaşıyor ve biri unutulmuştu: `son_dakika`
    baştan doğru yapıyordu, `hatirlat.py` 20 Ağu 2026'da 10 haberlik
    bir turu 'yeni' yazarak havuza döndürdü.
    """
    for dosya in ("scripts/hatirlat.py", "scripts/son_dakika.py"):
        kaynak = (KOK / dosya).read_text(encoding="utf-8")
        denetle("ig_baslik IS NOT NULL THEN 'metin_hazir'" in kaynak,
                f"havuza dönen haber metnini koruyor ({dosya})",
                "durum düz 'yeni' yapılıyor — üretilmiş metin çöpe "
                "gidiyor ve Gemini kotası ikinci kez harcanıyor")


def test_turkce_ek_toleransi() -> None:
    """
    Mükerrer denetimi düz küme kesişimi kullanamaz — Türkçe sondan
    eklemeli bir dil.

    20 Ağu 2026: aynı PFDK kararının iki haberi tek tura girdi.
      "…çok sayıda kulübe para CEZASI verdi"
      "…Mahmut Uslu'ya 2 milyon 500 bin lira ve kulüplere CEZA"
    Düz kesişimde ortak kelime yalnızca "pfdk" (1) sayıldı, eşik 2.
    """
    from src import secim as _s
    for a, b in (("ceza", "cezası"), ("deprem", "depremde"),
                 ("endonezya", "endonezyada"), ("yangın", "yangını")):
        denetle(_s._ayni_kok(a, b), f"ek toleransı: {a} ~ {b}")
    # Yanlış eşleşme yapmamalı
    for a, b in (("ankara", "antalya"), ("istanbul", "izmir"),
                 ("kara", "deniz")):
        denetle(not _s._ayni_kok(a, b), f"ek toleransı: {a} ≠ {b}",
                "alakasız kelimeler eşleşiyor — tur boşalır")

    # Kural aday kapısında GERÇEKTEN kullanılıyor mu (düz kesişim kalmasın)
    kaynak = (KOK / "src/aday.py").read_text(encoding="utf-8")
    denetle("secim.ortak_kelime(" in kaynak,
            "aday kapısı ek-toleranslı karşılaştırma kullanıyor",
            "düz `&` kesişimi kalmış — Türkçe ekler kaçar")


def test_kategori_uc_yerde_tanimli() -> None:
    """
    Kategori listesi ÜÇ yerde yaşıyor ve üçü de aynı olmalı:
      * `generate_text.KATEGORILER` — modelin seçebileceği değerler,
      * `config → gorsel.serit_renkleri` — slaytın şerit/gradyan rengi,
      * `config → secim.kategori_katsayilari` — ön elemedeki ağırlık.

    ⚠️ Biri eksik kalırsa hata YOK, sessiz hasar var: renk bulunamayan
    kategori "turkiye" rengine düşüyor, katsayısı olmayan kategori
    varsayılan ağırlıkla yarışıyor.
    """
    from src.generate_text import KATEGORILER
    g = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    renkler = set((g.get("gorsel") or {}).get("serit_renkleri", {}))
    katsayilar = set((g.get("secim") or {}).get("kategori_katsayilari", {}))
    kats = set(KATEGORILER)

    denetle(kats <= renkler, "her kategorinin şerit rengi var",
            f"renksiz: {sorted(kats - renkler)} — slayt sessizce "
            "turkiye rengine düşer")
    denetle(kats <= katsayilar, "her kategorinin ön eleme katsayısı var",
            f"katsayısız: {sorted(kats - katsayilar)}")

    # Model şemayı ihlal ederse diye ikinci savunma
    dbk = (KOK / "src/db.py").read_text(encoding="utf-8")
    denetle("_gecerli_kategori" in dbk,
            "kaydetmeden önce kategori beyaz listeden geçiyor",
            "model listede olmayan bir değer üretirse doğrudan yazılır")

    gt = (KOK / "src/generate_text.py").read_text(encoding="utf-8")
    denetle('"kategori": {"type": "string", "enum": KATEGORILER}' in gt,
            "cevap şeması kategoriyi enum ile sınırlıyor")


def test_gecici_hatalar_400te_de_yakalaniyor() -> None:
    """
    Üç dış servis de geçici hatalarını HTTP 400 ile veriyor ve HTTP
    koduna bakmak yetmiyor:
      * Instagram  — 2207003 / 2207052 ("medya indirilemedi")
      * Telegram   — WEBPAGE_CURL_FAILED
      * imgbb      — code 111 "Internal upload error"
      * Threads    — 4279009 "Media Not Found"

    Hepsinde aynı kanıt var: saniyeler sonra aynı istek çalışıyor.
    400'ü kalıcı sayan kod bu isteği HİÇ tekrar denemiyor ve tur/post
    düşüyor. 21 Ağu 2026'da imgbb yüzünden iki tekil post üretilemedi.
    """
    for dosya, isaret in (
            ("src/upload_image.py", "GECICI_MESAJLAR"),
            ("src/telegram_bot.py", "GECICI_MESAJLAR"),
            ("src/instagram.py", "GECICI_ALT_KODLAR"),
            ("src/threads.py", "GECICI_ALT_KODLAR")):
        kaynak = (KOK / dosya).read_text(encoding="utf-8")
        denetle(isaret in kaynak,
                f"{dosya}: 400 ile gelen geçici hatalar tanınıyor",
                "yalnızca HTTP koduna bakılıyor — geçici hata kalıcı "
                "sayılıp hiç tekrar denenmiyor")

    # Threads publish'i yalnızca "Media Not Found"da tekrarlamalı;
    # diğer hatalarda mükerrer gönderi riski var.
    th = (KOK / "src/threads.py").read_text(encoding="utf-8")
    denetle("_medya_yok_mu" in th,
            "Threads publish 'Media Not Found'da taze container ile "
            "tekrar deniyor")


def test_git_degisiklik_yok_yanlis_alarm_vermiyor() -> None:
    """
    "Commit edilecek bir şey yok" durumu HATA DEĞİL.

    Git bunu birden çok cümleyle anlatıyor; koda tek kalıp yazmak
    yanlış alarm veriyordu. 21 Ağu 2026: veritabanı değişmemişti ama
    takip edilmeyen bir bayrak dosyası vardı, git "nothing ADDED to
    commit" dedi, kod "nothing to commit" arıyordu ve job kırmızı oldu.
    """
    from src.db_senkron import _degisiklik_yok
    for cikti in ("nothing to commit, working tree clean",
                  "nothing added to commit but untracked files present",
                  "no changes added to commit"):
        denetle(_degisiklik_yok(cikti), f"'değişiklik yok' tanınıyor: "
                                        f"{cikti[:34]}")
    denetle(not _degisiklik_yok("error: could not write index"),
            "gerçek git hatası 'değişiklik yok' sanılmıyor",
            "gerçek hata yutulursa veri kaybı sessizce geçer")


def test_kosullu_tanimlanan_bayraklar() -> None:
    """
    Bir bayrak koşullu blokta tanımlanıp bloğun DIŞINDA okunuyorsa,
    koşul çalışmadığında `NameError` verir.

    21 Ağu 2026: `th_yarim` (Threads zinciri yarım mı) yalnızca
    `if threadse_de_at and kullanilabilir_mi()` bloğunun içinde
    tanımlanmıştı ve yayın sonucunu yazan satırda okunuyordu. Threads
    kapalı olsaydı BAŞARILI bir yayın kırmızı job'a dönecekti.

    ⚠️ Bütünlük testi bunu göremiyor — kod sözdizimi açısından geçerli,
    hata ancak o dal çalışmadığında ortaya çıkıyor.
    """
    import ast
    kaynak = (KOK / "scripts/onay_isle.py").read_text(encoding="utf-8")
    agac = ast.parse(kaynak)

    for islev in ast.walk(agac):
        if not isinstance(islev, ast.FunctionDef) or islev.name != "yayinla":
            continue
        # Fonksiyon gövdesinin ÜST seviyesinde atanan isimler
        ust_seviye = set()
        for dugum in islev.body:
            if isinstance(dugum, ast.Assign):
                for h in dugum.targets:
                    if isinstance(h, ast.Name):
                        ust_seviye.add(h.id)
        for bayrak in ("th_notu", "th_yarim", "th_gonderi_id"):
            denetle(bayrak in ust_seviye,
                    f"yayinla(): '{bayrak}' koşulsuz tanımlı",
                    "yalnızca if/try içinde atanıyor — o dal "
                    "çalışmazsa NameError")
        return
    denetle(False, "yayinla() fonksiyonu bulundu")


def test_worker_calisiyor() -> None:
    """
    `worker/index.js` üst seviyesi HATASIZ yüklenmeli.

    ⚠️ `node --check` YETMİYOR — o yalnızca sözdizimine bakıyor.
    21 Ağu 2026: bir düzenlemede satır sonları gerçek newline yerine
    literal "\n" olarak yazıldı, `const HABER_SEC = ...` satırı bir
    `//` yorumunun İÇİNDE kaldı ve Worker canlıda
    `ReferenceError: HABER_SEC is not defined` ile 500 döndü.
    Telegram'daki HİÇBİR düğme çalışmadı; sözdizimi ise kusursuzdu.

    Bu test Worker'ı gerçekten yükleyip `eylemMi`'yi çağırıyor.
    """
    import shutil
    import subprocess
    if not shutil.which("node"):
        return                                  # node yoksa atla
    betik = (
        "const fs=require('fs');"
        "let k=fs.readFileSync(process.argv[1],'utf8');"
        "k=k.replace(/export default[\\s\\S]*$/,'');"
        "new Function(k+';return eylemMi(\"hazirla:1\");')();"
        "console.log('ok');"
    )
    sonuc = subprocess.run(
        ["node", "-e", betik, str(KOK / "worker/index.js")],
        capture_output=True, text=True, timeout=30)
    denetle(sonuc.returncode == 0 and "ok" in sonuc.stdout,
            "worker/index.js hatasız yükleniyor",
            (sonuc.stderr or "")[:200])

    # Kaçış hatasının doğrudan izi: yorum satırında literal \n
    kod = (KOK / "worker/index.js").read_text(encoding="utf-8")
    bozuk = [s for s in kod.splitlines()
             if s.strip().startswith("//") and "\\n" in s]
    denetle(not bozuk, "Worker'da kaçış hatası kalmamış",
            f"{len(bozuk)} yorum satırında literal \\n var — sonraki "
            "kod satırı yoruma gömülmüş olabilir")


def test_gorsel_cesitliligi() -> None:
    """
    Görsellerin tekdüzeleşmesine karşı iki koruma.

    21 Ağu 2026, kullanıcı: *"görseller çok genel gibi hissettirmeye
    başladı, hep aynı şeyleri kullanıyoruz gibi"*. Ölçüm iki sebep
    buldu:

      1. Haberin KENDİ fotoğrafı boyut eşiğinden tamamen eleniyordu
         (son 14 haberin 14'ü). Eşik 1080x800'dü; haber sitelerinin
         standart OG boyutları 1280x720 ve 1200x630, ikisi de altında.
         Sonuç: her şey Pexels'e düşüyordu.
      2. Aynı Pexels fotoğrafı tekrar tekrar seçiliyordu (aynı
         fotoğrafçı 6, 5 ve 4 kez) — aynı arama hep aynı sonucu
         veriyor ve biz en yüksek puanlıyı alıyorduk.
    """
    cfg = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    g = cfg.get("gorsel") or {}
    # 1280x720 ve 1200x630 GEÇEBİLMELİ
    for gen, yuk, ad in ((1280, 720, "16:9 (1280x720)"),
                         (1200, 630, "1.91:1 (1200x630)")):
        denetle(gen >= g.get("haber_gorseli_asgari_genislik", 0)
                and yuk >= g.get("haber_gorseli_asgari_yukseklik", 0),
                f"haber fotoğrafı eşiği {ad} boyutunu geçiriyor",
                f"eşik {g.get('haber_gorseli_asgari_genislik')}x"
                f"{g.get('haber_gorseli_asgari_yukseklik')} — haber "
                "sitelerinin standart boyutu eleniyor, her şey Pexels'e düşer")

    fs = (KOK / "src/fetch_stock.py").read_text(encoding="utf-8")
    denetle("kullanilmis" in fs,
            "Pexels aramasında tekrar engeli var",
            "aynı arama hep aynı fotoğrafı döndürür")
    sl = (KOK / "src/slaytlar.py").read_text(encoding="utf-8")
    denetle("_kullanilmis_stok_idler" in sl,
            "kullanılmış stok id'leri veritabanından okunuyor")


def test_icerik_filtresi() -> None:
    """
    Riskli kelimeler hem caption'da hem SLAYT GÖRSELİNDE yumuşatılmalı.

    21 Ağu 2026: filtre yalnızca caption'da çalışıyordu; slayt
    görselindeki başlık ham hâliyle basılıyordu. Kullanıcı benzer
    hesapların görselin üstünde sansürlediğini gösterip aynısını istedi.

    ⚠️ KISA KÖK YANLIŞ EŞLEŞME YAPAR — ölçüldü:
        "vur" -> v*rgu, v*rgun · "öl" -> ö*çüm · "kan" -> k*nser
    Bu yüzden listedeki her kök, masum bir cümlede hiçbir kelimeyi
    yıldızlamamalı.
    """
    from src import filtre as _f
    cfg = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    f = cfg.get("icerik_filtresi") or {}
    kokler = f.get("yumusatilacak", [])

    denetle(f.get("gorselde") is True,
            "içerik filtresi slayt görseline de uygulanıyor",
            "yalnızca caption'da çalışıyor")
    sl = (KOK / "src/slaytlar.py").read_text(encoding="utf-8")
    denetle(sl.count("_slayt_metni(haber") >= 4,
            "slayt/story/detay başlıkları filtreden geçiyor",
            "bazı görsel metinleri ham basılıyor")

    # Masum cümlede yanlış eşleşme OLMAMALI
    masum = ("Ölçüm sonucu kanser taraması kanunla kanıtlandı, vurgu "
             "yapıldı, ölçek büyük, kanal açıldı, kararname yayımlandı")
    denetle("*" not in _f.metni_yumusat(masum, kokler),
            "filtre kökleri masum kelimeleri yıldızlamıyor",
            f"yanlış eşleşme: {_f.metni_yumusat(masum, kokler)}")

    # Riskli cümlede eşleşme OLMALI
    riskli = "Eşini vurarak öldürdü, cinayet sonrası ceset bulundu"
    denetle("*" in _f.metni_yumusat(riskli, kokler),
            "filtre riskli kelimeleri yakalıyor")


def test_temizlik_yayinlanmisi_korur() -> None:
    """
    Eski kayıt temizliği YAYINLANMIŞ haberlere dokunmamalı.

    Mükerrer engeli geçmişe bakıyor (`secim.yayinlanmis_konular`);
    yayınlanmış kayıtları silmek 1j/1z'deki "aynı haber ikinci kez
    yayınlandı" sorununu geri getirir.

    21 Ağu 2026'da eklendi: hiç temizlik yoktu, 8 günde 3134 kayıt
    birikti ve `.git` 237 MB'a çıktı (veritabanı her job'da commit
    ediliyor, ikili dosya sıkışmıyor).
    """
    import sqlite3
    from src import db as _db
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE haberler (id INTEGER PRIMARY KEY,
                   durum TEXT, cekilme_zamani TEXT)""")
    con.executemany(
        "INSERT INTO haberler (durum, cekilme_zamani) VALUES (?, ?)",
        [("yayinlandi", "2020-01-01"),      # çok eski AMA yayınlanmış
         ("metin_hazir", "2020-01-01"),     # çok eski, silinmeli
         ("yeni", "2020-01-01"),            # çok eski, silinmeli
         ("metin_hazir", "2099-01-01")])    # taze, kalmalı
    con.commit()
    _db.eski_kayitlari_temizle(con, 7)
    kalan = {r["durum"] for r in con.execute("SELECT durum FROM haberler")}
    denetle("yayinlandi" in kalan,
            "temizlik yayınlanmış haberi KORUYOR",
            "mükerrer engeli geçmişe bakıyor, silmek tekrarı geri getirir")
    denetle(len(list(con.execute(
        "SELECT 1 FROM haberler WHERE cekilme_zamani = '2020-01-01' "
        "AND durum != 'yayinlandi'"))) == 0,
        "temizlik eski yayınlanmamış kayıtları siliyor")
    con.close()


def test_arama_yazim_toleransi() -> None:
    """
    `/haber` araması yazım hatalarını tolere etmeli ama alakasız
    haber getirmemeli.

    21 Ağu 2026: kullanıcı "netenhay" aradı, havuzda 24 Netanyahu
    haberi vardı ve arama "sonuç yok" dedi. Dizi benzerliği yalnızca
    0.59 çıkıyordu çünkü harf SIRASI karışmıştı (hay ↔ yah).
    Harf kümesi ölçütü eklendi (sıradan bağımsız, 0.86).

    ⚠️ Harf kümesi TEK BAŞINA fazla gevşek: ilk denemede "netenhay"
    42 sonuç getirdi ve ilki Netanyahu'yla ilgisizdi. İlk üç harfin
    tutması şartı eklendi.
    """
    import importlib, sys as _s
    _s.path.insert(0, str(KOK / "scripts"))
    oi = importlib.import_module("onay_isle")

    for yanlis, dogru in (("netenhay", "netanyahu"),
                          ("netenyahu", "netanyahu"),
                          ("netanhayu", "netanyahu"),
                          ("erdogann", "erdogan")):
        denetle(oi._yazim_yakin_mi(yanlis, dogru),
                f"yazım toleransı: '{yanlis}' → '{dogru}'",
                "kullanıcı yazım hatası yapınca sonuç bulunamıyor")

    for a, b in (("netenhay", "hayatini"), ("ankara", "antalya"),
                 ("gazze", "gaziantep"), ("israil", "irak")):
        denetle(not oi._yazim_yakin_mi(a, b),
                f"yazım toleransı '{a}' ≠ '{b}'",
                "alakasız haberler sonuçlara karışıyor")

    # ⚠️ SKOR FONKSİYONU BULMA YÖNTEMİYLE AYNI OLMALI.
    # 21 Ağu 2026: fuzzy 24 haber buluyordu ama bir sonraki satır
    # onları TAM EŞLEŞME skoruyla süzüyordu; hepsi 0 alıp eleniyordu
    # ve arama yine "bulunamadı" diyordu. Fuzzy çalışıyordu, sonucunu
    # bir alt satır siliyordu.
    kaynak = (KOK / "scripts/onay_isle.py").read_text(encoding="utf-8")
    govde = kaynak.split("def haber_ara(")[1].split("\ndef ")[0]
    denetle("skorla = _yazim_toleransli_skor if yazim_duzeltildi" in govde,
            "fuzzy sonuçları fuzzy skoruyla süzülüyor",
            "tam eşleşme skoruyla süzülürse fuzzy sonuçları elenir")


def test_gunluk_sinir_gercek_yayini_sayiyor() -> None:
    """
    Günlük tekil post sınırı YAYINLANMIŞ postları saymalı.

    21 Ağu 2026: sayaç haber ONAYA SUNULDUĞUNDA artıyordu. Sayaç 10
    (sınır dolu) görünürken gerçekte 6 post yayınlanmıştı —
    onaylanmayan 4 haber kotayı yemişti. Kullanıcı iki haber seçti,
    job "başarılı" döndü, hiçbir şey üretilmedi ve kimse bir şey
    söylemedi.

    ⚠️ Ayrıca sınır dolduğunda ELLE SEÇİLEN haber muaf olmalı: insan
    bakıp seçtiyse makinenin sessizce reddetmesi yanlış.
    """
    kaynak = (KOK / "scripts/son_dakika.py").read_text(encoding="utf-8")
    govde = kaynak.split("def bugunku_sayi(")[1].split("\ndef ")[0]
    denetle("durum = 'yayinlandi'" in govde,
            "günlük sınır gerçek yayınları sayıyor",
            "ayrı bir sayaç okunuyor — onaylanmayan haber kotayı yer")

    ana = kaynak.split("def main(")[1]
    denetle("if zorla_haber_id:" in ana.split("son_dakika_gunluk_azami")[1][:600],
            "elle seçilen haber günlük sınırdan muaf",
            "kullanıcının açık seçimi sessizce reddediliyor")


def test_etki_dogrulamasi() -> None:
    """
    Kullanıcı komutları DÖNÜŞ DEĞERİNE değil GERÇEK ETKİYE bakmalı.

    21 Ağu 2026'da bugünkü hataların hepsi aynı desendi: kod
    "başarılı" dedi ama iş yapılmadı ve kullanıcıya hiçbir şey
    söylenmedi.
      * `son_dakika.main` günlük sayaç yanlış olduğu için 15 saniyede
        `0` döndü, hiçbir post üretmedi;
      * fuzzy arama 24 sonuç buldu, alt satır hepsini eledi;
      * yayın komutu kuyrukta iptal edildi.

    `oneriyi_hazirla` artık veritabanına bakıyor: haber gerçekten
    `onay_bekliyor` oldu mu ve bir mesaja bağlandı mı?
    """
    kaynak = (KOK / "scripts/onay_isle.py").read_text(encoding="utf-8")
    govde = kaynak.split("def oneriyi_hazirla(")[1].split("\ndef ")[0]
    denetle("gercekten_oldu" in govde,
            "oneriyi_hazirla gerçek etkiyi doğruluyor",
            "yalnızca dönüş değerine bakıyor — sessiz başarısızlık "
            "kullanıcıya 'hazırlanıyor' olarak görünür")
    denetle("durum'] in (\"onay_bekliyor\", \"yayinlandi\")" in govde
            or 'onay_bekliyor' in govde,
            "etki kontrolü haberin durumuna bakıyor")


def test_hatirlatma_tum_turlari_isliyor() -> None:
    """
    Aynı anda birden fazla açık tur olabilir ve HEPSİ işlenmeli.

    21 Ağu 2026: sabah 09:23'te kurulan tur hiç kapanmadı çünkü
    `hatirlat.main` yalnızca `haberler[0]`ın turunu işliyordu. Akşam
    yeni tur kurulunca hatırlatma hep onu görüyor, sabahki tur
    sonsuza kadar açık kalıyordu. Kullanıcı "sırada 20 küsür
    bekliyor" uyarısını böyle aldı (10 + 10 + 1 = 21 haber).
    """
    kaynak = (KOK / "scripts/hatirlat.py").read_text(encoding="utf-8")
    denetle("_turu_isle" in kaynak,
            "hatırlatma her turu ayrı ayrı işliyor",
            "yalnızca ilk tur işleniyor, diğerleri sonsuza kadar açık kalır")
    ana = kaynak.split("def main(")[1]
    denetle("turlar.setdefault" in ana or "for mesaj_id, tur_haberleri" in ana,
            "açık turlar mesaj id'sine göre gruplanıyor")


def test_commons_tukenince_katman_degisiyor() -> None:
    """
    "Başka fotoğraf" düğmesi GERÇEKTEN farklı bir görsel vermeli.

    21 Ağu 2026: kullanıcı "resmi değiştir" dedi ve hep aynı şeyi
    gördü. Ölçüldü — "Melissa Vargas" aramasının Commons'taki bütün
    adayları aynı maçtan geliyordu (Fenerbahçe forması, dosya 1-2-3-4)
    ve modulo ile dönüldüğü için düğme aynı serinin bir sonraki
    karesini veriyordu. Üstelik haber MİLLİ TAKIM haberiydi; kulüp
    forması tutarsız duruyordu.

    Artık birkaç denemeden sonra Commons atlanıyor ve Pexels
    katmanına düşülüyor.
    """
    kaynak = (KOK / "src/fetch_photo.py").read_text(encoding="utf-8")
    denetle("AZAMI_AYNI_KISI" in kaynak,
            "Commons'ta aynı kişi için deneme sınırı var",
            "modulo ile dönülüyor — 'başka dene' aynı seriyi veriyor")
    denetle("atlanacak % len(adaylar)" not in kaynak,
            "Commons adayları modulo ile döngüye sokulmuyor",
            "liste başa dönüyor, katman hiç değişmiyor")


def test_gorsel_kunyesi_zorunlu() -> None:
    """
    Yayınlanan her GERÇEK FOTOĞRAF künyeli olmak zorunda.

    ⚠️ NEDEN GEREKTİ (3 Eyl 2026): 28 Ağustos'ta `fetch_web_image`
    katmanı eklendi ve `arkaplan_sec` içinde atıf yerine boş string
    dönüyordu. Yayınlanan 10 web_haber postunun 10'u da ATIFSIZ ve
    "ARŞİV GÖRSELİ" ibaresi olmadan çıktı — yani fotoğrafın nereden
    geldiği hiçbir yerde kayıtlı değildi ve görsel, olayın belgesiymiş
    gibi duruyordu. Telif şikayeti gelse kaynağı bulmanın yolu yoktu.

    ⚠️ Katman aynı zamanda zincirin BİRİNCİ sırasındaydı — haberin
    kendi og:image'inin bile önünde. og:image konuya garantili bağlı
    (yayıncı o haber için koymuş), internet araması değil. Ölçüldü:
    3 gerçek haberin 3'ünde de yanlış fotoğraf geldi (İran saldırısı
    haberine Fox News'ten Trump portresi).

    Denetim AST ile yapılıyor: düz metin araması `return ... ""`
    kalıbını kaçırıyor, çünkü atıf bir değişkende de gelebilir.
    """
    kaynak = (KOK / "src/slaytlar.py").read_text(encoding="utf-8")
    agac = ast.parse(kaynak)

    fn = next((d for d in ast.walk(agac)
               if isinstance(d, ast.FunctionDef) and d.name == "arkaplan_sec"), None)
    denetle(fn is not None, "arkaplan_sec bulundu")
    if fn is None:
        return

    # `return (gorsel, "katman", atif)` biçimindeki dönüşleri sırayla topla
    donusler = []            # [(katman_adi, atif_bos_mu)]
    for dugum in ast.walk(fn):
        if not isinstance(dugum, ast.Return) or not isinstance(dugum.value, ast.Tuple):
            continue
        ogeler = dugum.value.elts
        if len(ogeler) != 3:
            continue
        katman = ogeler[1]
        if not (isinstance(katman, ast.Constant) and isinstance(katman.value, str)):
            continue
        atif = ogeler[2]
        bos = isinstance(atif, ast.Constant) and atif.value == ""
        donusler.append((katman.value, bos))

    denetle(len(donusler) >= 5,
            "arkaplan_sec katman dönüşleri okunabildi",
            f"yalnızca {len(donusler)} dönüş bulundu")

    # --- 1) Gerçek fotoğraf basan katman ATIFSIZ dönemez ---
    # `ai` ve `gradyan` üretilen görseller — atıf verecek kimse yok.
    kunyesiz_muaf = {"ai", "gradyan"}
    for katman, atif_bos in donusler:
        if katman in kunyesiz_muaf:
            continue
        denetle(not atif_bos,
                f"'{katman}' katmanı atıf döndürüyor",
                "gerçek fotoğraf basan katman boş atıf dönemez — "
                "görselin kaynağı kayıt altına alınmadan yayınlanır")

    # --- 2) İnternet araması og:image'den SONRA gelmeli ---
    sira = [k for k, _ in donusler]
    if "web_haber" in sira and "haber" in sira:
        denetle(sira.index("web_haber") > sira.index("haber"),
                "internet araması og:image katmanından SONRA çalışıyor",
                "internet araması haberin kendi fotoğrafını eziyor — "
                "og:image konuya garantili bağlı, arama değil")

    # --- 3) Doğrulanmamış fotoğraf ARŞİV ibaresi taşımalı ---
    denetle('"web_haber"' in kaynak.split("ARSIV_KATMANLARI")[1][:200]
            if "ARSIV_KATMANLARI" in kaynak else False,
            "web_haber ARSIV_KATMANLARI içinde",
            "internetten aranan fotoğrafın olayın belgesi olduğuna dair "
            "güvencemiz yok; 'ARŞİV GÖRSELİ' ibaresi basılmalı")

    # --- 4) Katman config'den kapatılabilir olmalı ---
    cfg = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    g = cfg.get("gorsel") or {}
    denetle("web_gorsel_ara" in g,
            "gorsel.web_gorsel_ara config'de tanımlı")
    # ⚠️ DÜZ METİN ARAMASI BURADA YETMİYOR — kasten bozularak ölçüldü:
    # `if g.get("web_gorsel_ara")` şartı silindiğinde test TEMİZ geçti,
    # çünkü aynı dosyadaki `#` yorumunda o kelime hâlâ yazılıydı.
    # AST'de yorumlar HİÇ bulunmuyor, o yüzden gerçek okumayı yalnızca
    # AST görüyor. (Aynı tuzak `test_ertelemede_menu_kaliyor`da da
    # yaşanmıştı: docstring'deki uyarı yanlış alarm veriyordu.)
    okunuyor = any(
        isinstance(d, ast.Constant) and d.value == "web_gorsel_ara"
        for d in ast.walk(agac)
    )
    denetle(okunuyor,
            "slaytlar.py web_gorsel_ara ayarını GERÇEKTEN okuyor",
            "config'de duran ama okunmayan ayar ÖLÜ AYARDIR — "
            "kullanıcı false yapar, katman yine çalışır")


def test_gorsel_brief_dort_yerde_tanimli() -> None:
    """
    Görsel brief alanları DÖRT ayrı yerde yaşıyor; dördü de olmalı.

    ⚠️ BU PROJENİN EN SIK TEKRARLAYAN HATA SINIFI: bir alan şemaya
    eklenir, `metin_kaydet`in SQL'ine eklenmeyi unutulur ve alan
    SESSİZCE HİÇ KAYDEDİLMEZ. Hata vermez — model değeri üretir, kod
    onu atar, veritabanında NULL kalır ve kimse fark etmez.
    (`kategori` alanı üç yerde yaşıyordu ve aynı denetim yazılmıştı.)

    Dört yer:
      1. CEVAP_SEMASI.properties  — model üretsin diye
      2. CEVAP_SEMASI.required    — model ATLAMASIN diye
      3. PROMPT                   — model NE yazacağını bilsin diye
      4. db.EK_KOLONLAR + metin_kaydet SQL — değer SAKLANSIN diye

    3 Eyl 2026'da eklendi (İş 2 — görsel brief).
    """
    sys.path.insert(0, str(KOK))
    from src import generate_text as gt, db as _db

    alanlar = ("gorsel_ozne_tipi", "gorsel_baglam")
    kaydet_kaynak = (KOK / "src/db.py").read_text(encoding="utf-8")

    for alan in alanlar:
        denetle(alan in gt.CEVAP_SEMASI["properties"],
                f"{alan} CEVAP_SEMASI.properties içinde")
        denetle(alan in gt.CEVAP_SEMASI["required"],
                f"{alan} CEVAP_SEMASI.required içinde",
                "required değilse model alanı atlayabilir")
        denetle(alan in gt.PROMPT,
                f"{alan} PROMPT'ta anlatılıyor",
                "şemada olup promptta olmayan alan rastgele dolar")
        denetle(alan in _db.EK_KOLONLAR,
                f"{alan} db.EK_KOLONLAR içinde",
                "kolon yoksa migration çalışmaz")
        # ⚠️ ASIL DENETİM BU: SQL'de gerçekten yazılıyor mu?
        denetle(f"{alan}" in kaydet_kaynak.split("def metin_kaydet")[1][:4000],
                f"{alan} metin_kaydet SQL'inde yazılıyor",
                "şemada var ama kaydedilmiyorsa alan SESSİZCE kaybolur")

    # --- Beyaz liste: şemadaki enum tek başına yetmiyor ---
    denetle(hasattr(_db, "_gecerli_ozne_tipi"),
            "db._gecerli_ozne_tipi beyaz listesi var",
            "model şemayı ihlal edebiliyor; `kategori` alanında da iki "
            "katman gerekmişti")
    if hasattr(_db, "_gecerli_ozne_tipi"):
        denetle(_db._gecerli_ozne_tipi("yok") is None
                and _db._gecerli_ozne_tipi("kisi") == "kisi",
                "beyaz liste tanınmayan değeri eliyor")
        sema_enum = set(gt.CEVAP_SEMASI["properties"]["gorsel_ozne_tipi"]["enum"])
        denetle(sema_enum == set(_db.OZNE_TIPLERI),
                "şema enum'u ile beyaz liste AYNI",
                f"şema={sorted(sema_enum)} beyaz liste={sorted(_db.OZNE_TIPLERI)} "
                "— ayrışırsa geçerli bir değer sessizce elenir")

    # --- Yönlendirme yalnızca Commons'ı atlamalı ---
    sl = (KOK / "src/slaytlar.py").read_text(encoding="utf-8")
    denetle("commons_atla" in sl,
            "slaytlar.py brief'e göre yönlendirme yapıyor")
    agac = ast.parse(sl)
    fn = next((d for d in ast.walk(agac)
               if isinstance(d, ast.FunctionDef) and d.name == "arkaplan_sec"), None)
    if fn is not None:
        govde = ast.get_source_segment(sl, fn) or ""
        # og:image bloğu `commons_atla` ile KOŞULLANMAMALI — yangının
        # haberinde yayıncının koyduğu fotoğraf gerçekten o yangındır.
        og_blok = govde.split("0.5)")[1].split("--- YÖNLENDİRME")[0] if "0.5)" in govde else ""
        denetle("commons_atla" not in og_blok,
                "yönlendirme og:image katmanını ATLAMIYOR",
                "'olay' haberinde bile yayıncının kendi fotoğrafı doğrudur")


def test_foto_ile_yazi_arasinda_olu_bant_yok() -> None:
    """
    Yatay fotoğraf, başlığın başladığı yere KADAR inmeli.

    ⚠️ NEDEN GEREKTİ (3 Eyl 2026, kullanıcı): *"neden yazının çok
    üstünde yatay bir şekilde duruyor resim, ayrık duruyor çok fazla,
    burada açıklamaya kadar resim olurdu"*. Eski kod yatay fotoğrafı
    720px'de kesiyordu, başlık 1140'ta başlıyordu — arada ~420px "ne
    fotoğraf ne yazı" olan ölü bant kalıyordu.

    Dört varyant üretilip yan yana gösterildi (720/1150/1450/1920);
    1150 seçildi. Daha aşağısında zoom kadrajı bozuyor (Fed örneğinde
    madalyon iki yandan kesiliyordu).
    """
    sys.path.insert(0, str(KOK))
    from src import make_image as mi

    # --- 1) Fotoğraf başlık alanına kadar inmeli ---
    denetle(mi.FOTO_HEDEF_ALT >= 1000,
            "yatay fotoğraf başlık alanına kadar iniyor",
            f"FOTO_HEDEF_ALT={mi.FOTO_HEDEF_ALT} — 720'deki eski davranışta "
            "fotoğraf ile yazı arasında ölü bant oluşuyordu")

    # --- 2) Büyütme tavanı olmalı ---
    denetle(hasattr(mi, "FOTO_AZAMI_BUYUTME") and mi.FOTO_AZAMI_BUYUTME <= 2.5,
            "büyütme tavanı var ve makul",
            "tavansız büyütme küçük kaynak fotoğrafı bulanıklaştırır; "
            "bulanık basmaktansa fotoğraf daha kısa dursun")

    # --- 3) Geçiş YUMUŞAK olmalı (smoothstep) ---
    # Kullanıcı isteği: "alt ve üst arasında renkleri bağlayıcı, biraz
    # daha soft geçiş". Smoothstep'in iki ucunda da türev sıfırdır, yani
    # perdenin nerede başlayıp bittiği görünmez. Eski `t**1.8` eğrisinin
    # başlangıcı keskindi.
    maske = mi._perde_maskesi(100, 1000, 200, 800)
    d = [maske.getpixel((50, y)) for y in range(1000)]
    denetle(d[0] == 0 and d[-1] == 255, "perde 0'dan 255'e gidiyor")
    # Uçlarda değişim yavaş, ortada hızlı olmalı
    bas_egim = d[230] - d[210]
    orta_egim = d[510] - d[490]
    denetle(orta_egim > bas_egim * 2,
            "geçiş eğrisi yumuşak (uçlarda yavaş, ortada hızlı)",
            f"başlangıç eğimi={bas_egim} orta eğim={orta_egim} — "
            "keskin başlayan perde fotoğrafın altında çizgi bırakır")
    denetle(abs(d[500] - 127) <= 4,
            "geçiş tam ortada yarı yolda (simetrik)",
            f"orta nokta {d[500]}/255")

    # --- 4) Piksel piksel döngü OLMAMALI ---
    # Eski kod slayt başına 1080x1920 = 2 milyon putpixel çağırıyordu
    # (ölçüldü: 0.78 sn/slayt). Degrade yalnızca Y'ye bağlı.
    #
    # ⚠️ DÜZ METİN ARAMASI OLMAZ — bu oturumda ÜÇÜNCÜ kez yakalandı:
    # fonksiyonun docstring'i "eski kod putpixel çağırıyordu" diye
    # AÇIKLADIĞI için düz arama yanlış alarm verdi. AST'de docstring
    # bir Constant düğümü, çağrı ise Attribute — ikisi karışmaz.
    kaynak = (KOK / "src/make_image.py").read_text(encoding="utf-8")
    fn = next((d for d in ast.walk(ast.parse(kaynak))
               if isinstance(d, ast.FunctionDef) and d.name == "_perde_maskesi"), None)
    denetle(fn is not None, "_perde_maskesi fonksiyonu var")
    if fn is not None:
        cagrilar = {d.attr for d in ast.walk(fn) if isinstance(d, ast.Attribute)}
        denetle("putpixel" not in cagrilar,
                "perde maskesi putpixel döngüsü kullanmıyor",
                "2 milyon Python çağrısı slayt başına ~0.8 sn yiyor")


def test_fotograf_alt_kenari_keskin_degil() -> None:
    """
    Fotoğrafın bittiği yerde KESKİN ÇİZGİ olmamalı.

    ⚠️ NEDEN GEREKTİ (3 Eyl 2026, kullanıcı): *"bazı fotolarda fotoğrafın
    hemen altındaki alan çok keskin bir şekilde bitiyor"*. Büyütme tavanı
    yüzünden küçük kaynaklı fotoğraf erken bitiyor (ör. 450px'lik kaynak
    855'te durur), altında bulanık ambiyans başlıyor ve arada net bir
    çizgi kalıyordu. Perde o noktada henüz şeffaf olduğu için gizlemiyordu.

    Çözüm: göl yansıması — fotoğrafın alt şeridi dikey çevrilip altına
    konuyor, aşağı indikçe soluyor ve bulanıklaşıyor.

    ⚠️ BU TEST KOD METNİNE DEĞİL DAVRANIŞA BAKIYOR. Fonksiyon adı
    değişse, yansıma başka bir yolla yapılsa bile geçerli kalır —
    denetlenen şey "alt kenarda ani sıçrama var mı".
    """
    sys.path.insert(0, str(KOK))
    from PIL import Image
    from src import make_image as mi

    # Büyütme tavanına takılacak KÜÇÜK kaynak: 450 * 1.9 = 855'te biter.
    # Desenli olsun ki yansıma ile düz zemin ayırt edilebilsin.
    kaynak = Image.new("RGB", (760, 450))
    px = kaynak.load()
    for y in range(450):
        for x in range(0, 760, 2):
            px[x, y] = (40 + (x * 7) % 200, 90, 150 - (y // 3) % 120)
    ark = mi.fotograftan_arkaplan(kaynak, 1080, 1920)

    foto_alt = int(450 * mi.FOTO_AZAMI_BUYUTME)         # 855
    def satir_ort(y):
        return sum(sum(ark.getpixel((x, y))) for x in range(0, 1080, 20)) / 54

    # Fotoğrafın son satırı ile hemen altındaki satır arasında
    # ani parlaklık sıçraması olmamalı.
    ust = satir_ort(foto_alt - 3)
    alt = satir_ort(foto_alt + 3)
    sicrama = abs(ust - alt)
    denetle(sicrama < 60,
            "fotoğrafın alt kenarında ani sıçrama yok",
            f"kenarın iki yanı arasında {sicrama:.0f} birimlik fark — "
            "fotoğraf düz bir çizgiyle kesiliyor demektir")

    # Altındaki alan DÜZ RENK olmamalı — yansıma içerik taşımalı.
    bant = [satir_ort(y) for y in range(foto_alt + 10, foto_alt + 160, 10)]
    denetle(max(bant) - min(bant) > 3,
            "fotoğrafın altındaki alan düz renk değil (yansıma var)",
            "yansıma yoksa kenar çizgi gibi durur")

    # Yansıma SONSUZA kadar gitmemeli — metin alanı temiz kalmalı.
    denetle(satir_ort(1700) < satir_ort(foto_alt + 20),
            "yansıma aşağı doğru soluyor",
            "sabit opaklıkta ayna görüntüsü yapay durur ve metni bozar")


def test_kardes_gorsel_havuzu() -> None:
    """
    Aynı olayın DİĞER kaynaklarındaki fotoğraflar da aday olmalı.

    ⚠️ NEDEN GEREKTİ (3 Eyl 2026): her kaynaktan yalnızca TEK aday
    alınıyordu. Ölçüldü — yayınladığımız haber başına ortalama 3.9 ek
    kayıt aynı olayı işliyor ve dağılım şöyle: rutin haberde 0 ek
    kaynak, BÜYÜK OLAYDA 6-12. Yani en çok erişim alan postlarda en çok
    aday boşta duruyordu.

    Ek adayların gerçekten daha iyi olduğu ölçüldü:
      Voleybol : seçilen 1200x675  -> havuzda 5877x3306 vardı (24x piksel)
      Silivri  : seçilen 1200x708  -> havuzda 1280x720

    ⚠️ ÖNCE EŞLEŞTİR, SONRA SIRALA. İlk yazımda sorgu
    `ORDER BY agirlik DESC LIMIT 400` idi — yani önce en yüksek
    ağırlıklı 400 satır alınıp içinde eşleşme aranıyordu ve aynı olayın
    haberleri o dilimin DIŞINDA kalabiliyordu. Bu test tam olarak o
    hatayı yakalar: eşleşen kardeş DÜŞÜK AĞIRLIKLI.
    """
    sys.path.insert(0, str(KOK))
    from src import slaytlar as slayt_mod

    con = gecici_db()
    con.executescript("""
        INSERT INTO haberler (id, kaynak, agirlik, baslik_orj, link, cekilme_zamani)
        VALUES
          -- hedef haber
          (1, 'Borsa Gündem', 5, 'Silivri açıklarında iki Türk gemisi çarpıştı',
           'http://a/1', datetime('now')),
          -- AYNI OLAY, DÜŞÜK ağırlıklı kaynak (ön-limitleme hatasını yakalar)
          (2, 'Küçük Ajans', 1, 'Silivri açıklarında Türk bayraklı 2 gemi çarpıştı',
           'http://b/2', datetime('now')),
          -- AYNI OLAY, yüksek ağırlıklı
          (3, 'Anadolu Ajansı', 10, 'Silivri açıklarında iki gemi çarpıştı, arama sürüyor',
           'http://c/3', datetime('now')),
          -- ⚠️ BAŞKA BİR OLAY ama 3 ORTAK KELİME taşıyor
          -- (açıklarında + gemisi + çarpıştı). Ortak ÖZEL İSİM yok:
          -- hedefte {silivri, türk}, burada {marmara}. Yalnızca kelime
          -- sayan bir denetim bunu kardeş sanar — 1j'deki yanlış pozitif.
          (4, 'TRT Haber', 10, 'Marmara açıklarında yolcu gemisi kayalıklara çarpıştı',
           'http://d/4', datetime('now')),
          -- AYNI OLAY ama ÇOK ESKİ (2 günlük pencere dışında)
          (5, 'AA Dünya', 10, 'Silivri açıklarında iki Türk gemisi çarpıştı',
           'http://e/5', datetime('now', '-5 day'));
    """)
    hedef = con.execute("SELECT * FROM haberler WHERE id = 1").fetchone()
    linkler = slayt_mod.kardes_linkler(con, hedef, azami=5)

    denetle("http://b/2" in linkler,
            "düşük ağırlıklı kardeş de bulunuyor",
            "sorgu ağırlığa göre ÖN-LİMİTLEME yapıyorsa eşleşen kardeşler "
            "o dilimin dışında kalır — Silivri'de 1920x1080 bu yüzden "
            "bulunamamıştı")
    denetle("http://c/3" in linkler, "yüksek ağırlıklı kardeş bulunuyor")
    denetle("http://d/4" not in linkler,
            "alakasız haber kardeş sayılmıyor",
            "ortak özel isim şartı olmadan yanlış pozitif verir (bkz. 1j)")
    denetle("http://e/5" not in linkler,
            "2 günden eski kayıt kardeş sayılmıyor",
            "eski haberin fotoğrafı o olayın güncel karesi değil")
    denetle("http://a/1" not in linkler, "haberin kendisi listeye girmiyor")

    # Sıralama: yüksek ağırlıklı kaynak önce denenmeli (daha büyük foto koyuyor)
    if "http://c/3" in linkler and "http://b/2" in linkler:
        denetle(linkler.index("http://c/3") < linkler.index("http://b/2"),
                "kardeşler ağırlığa göre sıralı deneniyor")

    # Üst sınır olmalı — her aday 0.7-3.8 sn maliyetli
    denetle(slayt_mod.KARDES_AZAMI <= 5,
            "kardeş taraması sınırlı",
            f"KARDES_AZAMI={slayt_mod.KARDES_AZAMI} — sınırsız tarama turu yavaşlatır")
    denetle(len(slayt_mod.kardes_linkler(con, hedef)) <= slayt_mod.KARDES_AZAMI,
            "varsayılan çağrı sınıra uyuyor")

    # `con` zinciri: DB olmadan eski davranış sürmeli, patlamamalı
    denetle(slayt_mod.kardes_linkler(None, hedef) == [],
            "con verilmezse kardeş taraması yapılmıyor (eski davranış)")

    # con dört fonksiyonda da taşınmalı
    import inspect
    for ad in ("arkaplan_sec", "slayt_uret", "tur_uret", "son_dakika_uret"):
        fn = getattr(slayt_mod, ad, None)
        denetle(fn is not None and "con" in inspect.signature(fn).parameters,
                f"{ad} con parametresi taşıyor",
                "zincirin bir halkası con'u düşürürse kardeş havuzu "
                "sessizce devre dışı kalır")


def test_onaylanan_gorsel_videoya_giriyor() -> None:
    """
    Videoda ONAYLANAN görseller kullanılmalı, eski/yeniden üretilen değil.

    ⚠️ NEDEN GEREKTİ (3 Eyl 2026, kullanıcı): *"başka fotolarla yeniden
    üret dedim ve onu paylaştığımda oluşturduğu videoları eski
    görüntülerle oluşturdu"*.

    Kök sebep: `reels_dikey_gorselleri_uret` önce YEREL DOSYAYA bakıyor,
    yoksa slaytı SIFIRDAN üretiyordu — üstelik `gorsel_deneme` okumadan,
    yani "başka fotoğraf" seçimi yok sayılarak. Yayın job'ı ayrı runner'da
    çalışıyor ve `data/output` .gitignore'da olduğu için yerel dosya
    HİÇBİR ZAMAN yoktu; bu yol her seferinde devreye giriyordu.

    Onaylanan imgbb URL'leri ise parametre olarak GELİYOR ama 2. sıradaydı
    ve hiç ulaşılmıyordu.

    ⚠️ Bu, CLAUDE.md'deki "Onaylanan metin ≠ yayınlanan metin" hatasının
    görsel kardeşi: gözden geçirdiğin şey yayına çıkan şey değil.

    Test DAVRANIŞA bakıyor: onaylanan görsel KIRMIZI, yereldeki eski
    dosya MAVİ. Çıkan karenin rengi hangisi?
    """
    sys.path.insert(0, str(KOK))
    import pathlib as _pathlib
    import tempfile
    from PIL import Image
    from src import video

    with tempfile.TemporaryDirectory() as gecici:
        gecici = _pathlib.Path(gecici)
        # Onaylanan görsel — KIRMIZI
        onaylanan = gecici / "onaylanan.jpg"
        Image.new("RGB", (1080, 1920), (220, 30, 30)).save(onaylanan)

        # Yereldeki ESKİ dosya — MAVİ (eski fotoğrafı temsil ediyor)
        h_id = 999777
        video.CIKTI_KLASORU.mkdir(parents=True, exist_ok=True)
        eski_yerel = video.CIKTI_KLASORU / f"story-{h_id}.jpg"
        eski_detay = video.CIKTI_KLASORU / f"story-{h_id}-detay-1.jpg"
        Image.new("RGB", (1080, 1920), (30, 30, 220)).save(eski_yerel)
        Image.new("RGB", (1080, 1920), (30, 30, 220)).save(eski_detay)

        try:
            kareler = video.reels_dikey_gorselleri_uret(
                [str(onaylanan)],
                cikti_dizini=gecici / "kareler",
                haberler=[{"id": h_id, "gorsel_deneme": 2}],
                ayarlar={},
            )
            denetle(len(kareler) >= 1, "video karesi üretildi")
            if kareler:
                r, g_, b = Image.open(kareler[0]).convert("RGB").getpixel((540, 960))
                denetle(r > 150 and b < 100,
                        "video ONAYLANAN görseli kullanıyor",
                        f"kare rengi ({r},{g_},{b}) — mavi ise yereldeki ESKİ "
                        "dosya kullanılmış demektir; kullanıcının onayladığı "
                        "görsel yayına çıkmıyor")
        finally:
            for f in (eski_yerel, eski_detay):
                f.unlink(missing_ok=True)

    # --- SEÇİM TEK KAPIDAN UYGULANMALI ---
    #
    # ⚠️ Slaytı yeniden üreten 20'den fazla çağrı yeri var (URL onarımı,
    # video karesi, metin yenileme, arşiv paylaşımı...). Her birine
    # `atlanacak=` eklemek bir gün unutulur — bu projedeki kusurların
    # çoğu zaten "kural doğru ama bir yerde uygulanmamış" hatası.
    # Bu yüzden seçim `_secimi_uygula` içinde, üretim fonksiyonunun
    # KENDİSİNDE okunuyor.
    from src import slaytlar as slayt_mod2
    denetle(hasattr(slayt_mod2, "_secimi_uygula"),
            "fotoğraf seçimi tek kapıdan uygulanıyor")
    if hasattr(slayt_mod2, "_secimi_uygula"):
        h_secim = {"id": 1, "gorsel_deneme": 2}
        denetle(slayt_mod2._secimi_uygula(h_secim, None, False) == (2, True),
                "çağrı belirtmezse seçim KAYITTAN okunuyor",
                "okunmazsa yeniden üretim orijinal fotoğrafa döner")
        denetle(slayt_mod2._secimi_uygula(h_secim, 5, False) == (5, True),
                "çağıran açıkça belirtirse o kazanır",
                "'başka fotoğraf' düğmesi sayacı artırıp geçiriyor")
        denetle(slayt_mod2._secimi_uygula({"id": 1}, None, False) == (0, False),
                "kolon yoksa/bozuksa güvenli varsayılan",
                "eski kayıtlar bu kolonu taşımıyor")
        import inspect
        for ad in ("slayt_uret", "son_dakika_uret"):
            par = inspect.signature(getattr(slayt_mod2, ad)).parameters["atlanacak"]
            denetle(par.default is None,
                    f"{ad}.atlanacak varsayılanı None (= kayıttan oku)",
                    "varsayılan 0 olursa 'belirtilmedi' ile 'orijinali istiyorum' "
                    "ayırt edilemez ve seçim sessizce yok sayılır")

    # Yeniden üretim yoluna düşülürse `gorsel_deneme` OKUNMALI —
    # yoksa "başka fotoğraf" seçimi yok sayılıp orijinal fotoğraf gelir.
    kaynak = (KOK / "src/video.py").read_text(encoding="utf-8")
    fn = next((d for d in ast.walk(ast.parse(kaynak))
               if isinstance(d, ast.FunctionDef)
               and d.name == "reels_dikey_gorselleri_uret"), None)
    denetle(fn is not None, "reels_dikey_gorselleri_uret bulundu")
    if fn is not None:
        sabitler = {d.value for d in ast.walk(fn)
                    if isinstance(d, ast.Constant) and isinstance(d.value, str)}
        denetle("gorsel_deneme" in sabitler,
                "yeniden üretim gorsel_deneme'yi okuyor",
                "okunmazsa kullanıcının 'başka fotoğraf' seçimi yok sayılır")


def main() -> int:
    # ⚠️ SÖZLEŞME TESTİ AĞA ÇIKMAZ. `secim.yayinlanmis_konular` artık
    # Instagram geçmişini de okuyor (mükerrer denetimi için); testte o
    # çağrı yapılırsa test ağa bağımlı hale gelir, yavaşlar ve jeton
    # yoksa patlar. Önbelleği boş doldurup API yolunu kapatıyoruz.
    sys.path.insert(0, str(KOK))
    from src import secim as _secim
    _secim._IG_GECMIS_ONBELLEK = []

    for test in (
        test_mukerrer_engeli,
        test_mukerrer_her_akista_var,
        test_config_anahtarlari_okunuyor,
        test_sabit_kodlanmis_esik_yok,
        test_prompt_kopyalari_tutarli,
        test_worker_python_buton_uyumu,
        test_yaml_ham_git_komutu_yok,
        test_oneri_esigi_yayin_esiginden_dusuk,
        test_gece_esigi_gunduzden_yuksek,
        test_carousel_siniri,
        test_aday_kapisi_kurallari,
        test_aday_baglamlari_farkli_esik,
        test_planlanmis_yayin_zaman_asimlarindan_muaf,
        test_mukerrer_instagrama_da_bakiyor,
        test_ertelemede_menu_kaliyor,
        test_ayri_mesajdaki_dugme_tur_id_tasiyor,
        test_havuza_donen_haber_metnini_koruyor,
        test_turkce_ek_toleransi,
        test_kategori_uc_yerde_tanimli,
        test_gecici_hatalar_400te_de_yakalaniyor,
        test_git_degisiklik_yok_yanlis_alarm_vermiyor,
        test_kosullu_tanimlanan_bayraklar,
        test_worker_calisiyor,
        test_gorsel_cesitliligi,
        test_icerik_filtresi,
        test_temizlik_yayinlanmisi_korur,
        test_arama_yazim_toleransi,
        test_gunluk_sinir_gercek_yayini_sayiyor,
        test_etki_dogrulamasi,
        test_hatirlatma_tum_turlari_isliyor,
        test_commons_tukenince_katman_degisiyor,
        test_gorsel_kunyesi_zorunlu,
        test_gorsel_brief_dort_yerde_tanimli,
        test_foto_ile_yazi_arasinda_olu_bant_yok,
        test_fotograf_alt_kenari_keskin_degil,
        test_kardes_gorsel_havuzu,
        test_onaylanan_gorsel_videoya_giriyor,
    ):
        try:
            test()
        except Exception as e:                        # noqa: BLE001
            denetle(False, f"{test.__name__} PATLADI", f"{type(e).__name__}: {e}")

    print("=" * 70)
    print("SÖZLEŞME TESTLERİ")
    print("=" * 70)
    gecen = [s for s in SONUCLAR if s[0]]
    kalan = [s for s in SONUCLAR if not s[0]]
    for ok, ad, ayrinti in SONUCLAR:
        if not ok:
            print(f"  ✗ {ad}")
            if ayrinti:
                print(f"      {ayrinti}")
    print()
    print(f"  {len(gecen)}/{len(SONUCLAR)} denetim geçti")
    if kalan:
        print(f"  ✗ {len(kalan)} SORUN — yukarıda listelendi")
        return 1
    print("  ✓ Bütün sözleşmeler sağlanıyor.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
