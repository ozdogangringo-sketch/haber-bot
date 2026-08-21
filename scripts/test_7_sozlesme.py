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
    tb = (KOK / "src/telegram_bot.py").read_text(encoding="utf-8")
    # (fonksiyon, komut, callback_data'da bulunması gereken değişken)
    for menu, komut, degisken in (
            ("alternatif_menusu", "haber_sec", "tur_mesaj_id"),
            ("alternatif_menusu", "haber_vazgec", "tur_mesaj_id"),
            ("sonucu_yaz", "kaldir", "message_id")):
        govde = tb.split(f"def {menu}(")[1].split("\ndef ")[0]
        satirlar = [s for s in govde.splitlines() if f"{komut}:" in s]
        denetle(bool(satirlar) and any(degisken in s for s in satirlar),
                f"{menu}: '{komut}' düğmesi tur mesaj id'sini taşıyor",
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
