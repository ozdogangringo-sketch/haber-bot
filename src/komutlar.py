"""
komutlar.py — Tek Merkezli Komut ve Yetki Yönetim Sözlüğü (Single Source of Truth)

Tüm Telegram komutları, serbest/mesajsız komutlar, slash açılır menüsü
ve komut eşanlamlıları tek bir merkezden yönetilir.
"""

from __future__ import annotations

# Açık bir onay mesajına (mesaj_id) bağlı OLMADAN, doğrudan chat'ten
# veya serbestçe çağrılabilen komutların listesi.
MESAJSIZ_KOMUTLAR: set[str] = {
    # Sistem, Havuz ve Durum
    "durum",
    "ayar",
    "tamamla",
    "arsiv",
    "ara",
    "havuz_guncelle",
    "guncelle",
    "sondakika",
    "son_dakika",
    "haftalik",
    "pazar",
    "bulten",
    "kahve",
    "video",
    "reels",
    "sonpostlar",
    "son_postlar",

    # Yönetim ve Kontrol Paneli
    "yonetim",
    "yonetim_panel",
    "panel",
    "duraklat",
    "durdur",
    "devam",
    "devam_et",
    "saglik",
    "saglik_testi",
    "kota",
    "kota_raporu",
    "temizle",
    "tur_temizle",

    # Tur ve Haber Seçimleri (Tur ID'sini komut içinde taşır)
    "haber_sec",
    "haber_vazgec",
    "kurtar",
    "yayin_kontrol",
    "yeniden_yayinla",
    "retry_kanal",
    "gorsel_kabul",
    "gorsel_yeni",

    # Özel Haber & Dosya Motoru
    "dosya",
    "kronoloji",
    "perdearkasi",
    "link",
    "arastir",
    "ozel",

    # Makro & Piyasa Veri Kartları
    "faiz",
    "enflasyon",
    "fed",
    "makro",
    "hisse",
    "kripto",
    "piyasa",
    "piyasa_ozet",
    "ekonomi",
    "piyasa_yayinla",
    "ekonomi_yayinla",
    "piyasa_onizle",
}

# Telegram resmi açılır menüsünde (setMyCommands) listelenen komutlar
# ⚠️ TELEGRAM MENÜSÜ DÜZ BİR LİSTE — gerçek "grup" desteği YOK.
# Gruplama iki şeyle yapılıyor: (1) SIRA (Telegram verdiğimiz sırayı
# koruyor), (2) açıklamanın başındaki grup simgesi. Kullanıcı "/" yazınca
# komutlar bu blokta göründüğü sırayla, simgeleriyle listeleniyor.
#
# ⚠️ 4 Eyl 2026'da ölçüldü: Worker 33 asıl slash komutu tanıyordu ama bu
# liste yalnızca 21'ini gösteriyordu — `/haber`, `/tamamla`, `/arsiv`,
# `/video`, `/fed`, `/makro`, `/menu`, `/haftalik`, `/ayar`, `/tur`
# çalışıyor ama hiçbir yerde YAZMIYORDU. Ayrıca Worker'daki `/yardim`
# metni bu listeyle TUTMUYORDU (yardımda `/haber` vardı menüde yoktu;
# menüde `hisse`/`kripto`/`faiz`/`bulten` vardı yardımda yoktu).
# `test_komut_menusu_tutarli` üçünü birden denetliyor.
#
# ⚠️ YENİ KOMUT EKLERKEN ÜÇ YERİ birden güncelle: bu liste · Worker'ın
# tanıdığı slash listesi · Worker'daki `/yardim` metni.
KOMUT_MENUSU: list[dict[str, str]] = [
    # ── ✍️ İÇERİK ÜRET ────────────────────────────────────────────
    {"command": "haber", "description": "✍️ Havuzdaki haberlerde ara (/haber asgari ücret)"},
    {"command": "link", "description": "✍️ Haber linkinden post üret (/link <url>)"},
    {"command": "dosya", "description": "✍️ Konunun A'dan Z'ye kronolojik dosyası (/dosya <konu>)"},
    {"command": "kronoloji", "description": "✍️ Olay veya dava sürecini özetle (/kronoloji <konu>)"},
    {"command": "arastir", "description": "✍️ Konuyu webde araştırıp posta dönüştür (/arastir <konu>)"},
    {"command": "ozel", "description": "✍️ Kendi duyuru metninden post üret (/ozel <metin>)"},

    # ── 📰 GÜNDEM & AKIŞ ──────────────────────────────────────────
    {"command": "sondakika", "description": "📰 Taze haberleri tara, öneri getir"},
    {"command": "guncelle", "description": "📰 RSS kaynaklarını ŞİMDİ tara (metin üretmez)"},
    {"command": "tur", "description": "📰 10 haberlik gündem turu hazırla"},
    {"command": "bulten", "description": "📰 Taze haberlerden kahve bülteni derle"},
    {"command": "haftalik", "description": "📰 Haftalık pazar özeti hazırla"},
    {"command": "sonpostlar", "description": "📰 Son yayınlanan postlar ve linkleri"},

    # ── 📈 PİYASA & MAKRO ─────────────────────────────────────────
    {"command": "piyasa", "description": "📈 Canlı borsa, döviz, altın, kripto tablosu"},
    {"command": "ekonomi", "description": "📈 Canlı piyasa özeti + yayın düğmeleri"},
    {"command": "hisse", "description": "📈 BİST hissesi sorgula (/hisse THYAO)"},
    {"command": "kripto", "description": "📈 Kripto para sorgula (/kripto BTC)"},
    {"command": "faiz", "description": "📈 Faiz kararı kartı (/faiz 47.5 TCMB faizi sabit)"},
    {"command": "enflasyon", "description": "📈 Enflasyon kartı (/enflasyon 33.2 TÜİK açıkladı)"},
    {"command": "fed", "description": "📈 Fed kararı kartı (/fed 4.25 FOMC 25 bp indirdi)"},
    {"command": "makro", "description": "📈 Serbest makro veri kartı (/makro <veri>)"},

    # ── 🎛 YÖNETİM & BAKIM ────────────────────────────────────────
    {"command": "durum", "description": "🎛 Havuz, kota ve askıda kalan turlar"},
    {"command": "menu", "description": "🎛 Düğmeli kontrol merkezi"},
    {"command": "yonetim", "description": "🎛 Yönetim paneli ve API sağlık testleri"},
    {"command": "ayar", "description": "🎛 Çalışma ayarlarını değiştir"},
    {"command": "temizle", "description": "🎛 Askıda kalan onay turlarını sıfırla"},
    {"command": "tamamla", "description": "🎛 Yarım kalan Threads zincirini tamamla"},
    {"command": "arsiv", "description": "🎛 Eski turları Threads'e taşı (3'er 3'er)"},
    {"command": "video", "description": "🎛 Son turdan 9:16 Reels videosu üret"},
    {"command": "durdur", "description": "🎛 Botu geçici süreyle duraklat"},
    {"command": "devam", "description": "🎛 Duraklatılmış botu yeniden başlat"},

    # ── ❓ ────────────────────────────────────────────────────────
    {"command": "yardim", "description": "❓ Tüm komutlar ve kullanım rehberi"},
]


def mesajsiz_komut_mu(komut: str) -> bool:
    """
    Verilen komutun bir `mesaj_id` olmadan da çalışabilen serbest bir komut
    olup olmadığını denetler. Parametreli komutlarda (örn: `dosya:ahbap`)
    komutun ön ekini kontrol eder.
    """
    if not komut:
        return False
    kok_komut = komut.split(":", 1)[0].strip()
    return kok_komut in MESAJSIZ_KOMUTLAR or komut.strip() in MESAJSIZ_KOMUTLAR
