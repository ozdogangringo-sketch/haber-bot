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
KOMUT_MENUSU: list[dict[str, str]] = [
    {"command": "dosya", "description": "📁 A'dan Z'ye Kronolojik Dosya Haberi Üret"},
    {"command": "kronoloji", "description": "⏳ Olay, Dava veya Teftiş Sürecini Özetle"},
    {"command": "link", "description": "🌐 Web Sitesi / Haber Linkinden Tam Post Üret"},
    {"command": "arastir", "description": "🔍 Konuyu Webde Araştırıp Posta Dönüştür"},
    {"command": "ozel", "description": "📢 Kendi Duyuru veya Bülten Metninden Post Üret"},
    {"command": "sondakika", "description": "⚡ Saatlik Taze Haber Önerileri & Son Dakika Tara"},
    {"command": "piyasa", "description": "📈 Canlı Borsa, Isı Haritası, Döviz & Altın Tablosu"},
    {"command": "ekonomi", "description": "📊 Sabah Ekonomi & Finans Bülteni Başlat"},
    {"command": "faiz", "description": "🏦 Faiz Kararı İnfografik Kartı Üret"},
    {"command": "enflasyon", "description": "📉 TÜİK / Küresel Enflasyon İnfografiği"},
    {"command": "hisse", "description": "🏢 Canlı BİST Hisse Senedi Sorgula (/hisse THYAO)"},
    {"command": "kripto", "description": "🪙 Canlı Kripto Para Sorgula (/kripto BTC)"},
    {"command": "bulten", "description": "☕ Taze Haberlerle Anlık Kahve Bülteni Derle"},
    {"command": "yonetim", "description": "🎛️ Ana Yönetim Paneli ve API Sağlık Testleri"},
    {"command": "durum", "description": "📊 Canlı Havuz, Kota ve Sistem Raporu"},
    {"command": "temizle", "description": "🧹 Askıda Kalan Onay Turlarını Sıfırla"},
    {"command": "guncelle", "description": "🔄 20+ RSS ve Finans Kaynağını Şimdi Tara"},
    {"command": "sonpostlar", "description": "📰 Son Yayınlanan Postlar ve Sosyal Linkler"},
    {"command": "durdur", "description": "⏸️ Botu Geçici Süreyle Duraklat"},
    {"command": "devam", "description": "▶️ Duraklatılmış Botu Tekrar Başlat"},
    {"command": "yardim", "description": "❓ Tüm Komutlar ve Kullanım Rehberi"},
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
