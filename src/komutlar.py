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
    {"command": "haber", "description": "✍️ <kelime> ile havuzda haber ara"},
    {"command": "link", "description": "✍️ <url> ile linkten post üret"},
    {"command": "dosya", "description": "✍️ <konu> kronolojik dosya haberi"},
    {"command": "kronoloji", "description": "✍️ <konu> olay/dava süreci özeti"},
    {"command": "arastir", "description": "✍️ <konu> webde araştır, post yap"},
    {"command": "ozel", "description": "✍️ <metin> kendi duyurundan post"},

    # ── 📰 GÜNDEM & AKIŞ ──────────────────────────────────────────
    {"command": "sondakika", "description": "📰 Taze haberleri tara, öneri getir"},
    {"command": "guncelle", "description": "📰 RSS'i şimdi tara (metin üretmez)"},
    {"command": "tur", "description": "📰 10 haberlik gündem turu hazırla"},
    {"command": "bulten", "description": "📰 Kahve bülteni derle"},
    {"command": "haftalik", "description": "📰 Haftalık pazar özeti"},
    {"command": "sonpostlar", "description": "📰 Son yayınlanan postlar"},

    # ── 📈 PİYASA & MAKRO ─────────────────────────────────────────
    {"command": "piyasa", "description": "📈 Canlı borsa, döviz, altın tablosu"},
    {"command": "ekonomi", "description": "📈 Piyasa özeti + yayın düğmeleri"},
    {"command": "hisse", "description": "📈 <sembol> BİST hissesi sorgula"},
    {"command": "kripto", "description": "📈 <sembol> kripto para sorgula"},
    {"command": "faiz", "description": "📈 <oran> <açıklama> faiz kartı"},
    {"command": "enflasyon", "description": "📈 <oran> <açıklama> enflasyon kartı"},
    {"command": "fed", "description": "📈 <oran> <açıklama> Fed kartı"},
    {"command": "makro", "description": "📈 <veri> makro veri kartı"},

    # ── 🎛 YÖNETİM & BAKIM ────────────────────────────────────────
    {"command": "durum", "description": "🎛 Havuz, kota, askıdaki turlar"},
    {"command": "menu", "description": "🎛 Düğmeli kontrol merkezi"},
    {"command": "yonetim", "description": "🎛 Yönetim paneli, sağlık testi"},
    {"command": "ayar", "description": "🎛 Çalışma ayarlarını değiştir"},
    {"command": "temizle", "description": "🎛 Askıdaki turları sıfırla"},
    {"command": "tamamla", "description": "🎛 Yarım Threads zincirini tamamla"},
    {"command": "arsiv", "description": "🎛 Eski turları Threads'e taşı"},
    {"command": "video", "description": "🎛 Son turdan Reels videosu üret"},
    {"command": "durdur", "description": "🎛 Botu geçici duraklat"},
    {"command": "devam", "description": "🎛 Duraklatılmış botu başlat"},

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
