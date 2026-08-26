import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

from PIL import Image
from src import video, upload_image

def test_reels_video_pipeline():
    print("1. Test slaytları hazırlanıyor...")
    klasor = Path("data/output/test_reels_env")
    klasor.mkdir(parents=True, exist_ok=True)
    
    p1 = klasor / "slayt1.jpg"
    p2 = klasor / "slayt2.jpg"
    Image.new("RGB", (1080, 1350), color=(15, 35, 55)).save(p1)
    Image.new("RGB", (1080, 1350), color=(30, 60, 40)).save(p2)

    print("2. 9:16 Dikey çerçeveleme test ediliyor...")
    dikey_yollar = video.reels_dikey_gorselleri_uret([p1, p2], cikti_dizini=klasor / "9_16")
    assert len(dikey_yollar) == 2, "2 dikey görsel üretilmeliydi"
    for dy in dikey_yollar:
        with Image.open(dy) as img:
            assert img.size == (1080, 1920), f"Boyut 1080x1920 olmalı, {img.size} geldi"

    print("3. MP4 video üretimi test ediliyor (30 FPS, H.264)...")
    mp4_yolu = video.slaytlardan_reels_uret(
        dikey_yollar,
        cikti_yolu=klasor / "reels_test.mp4",
        fps=30,
        slayt_suresi=2.0,
        gecis_suresi=0.3,
    )
    assert mp4_yolu.exists(), "MP4 dosyası oluşmalıydı"
    assert mp4_yolu.stat().st_size > 5000, "MP4 dosya boyutu geçerli olmalı"
    print(f"✓ Video başarıyla üretildi: {mp4_yolu} ({mp4_yolu.stat().st_size / 1024:.1f} KB)")

    print("4. Video CDN yükleme testi yapılıyor...")
    url = upload_image.video_yukle(mp4_yolu)
    assert url and url.startswith("http"), f"Geçerli video URL'si gelmeli, {url} geldi"
    print(f"✓ Video başarıyla yüklendi: {url}")
    print("\n🎉 TÜM REELS TESTLERİ BAŞARIYLA GEÇTİ!")

if __name__ == "__main__":
    test_reels_video_pipeline()
