"""
test_tiktok_carousel.py — TikTok Content Posting API v2 Photo Carousel birim testleri.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

from src import tiktok


def test_foto_carousel_bos_url_listesi():
    """Boş URL listesi verildiğinde hata dönmelidir."""
    sonuc = tiktok.foto_carousel_yukle([], "Test Başlık")
    assert sonuc["durum"] is False
    assert "boş" in sonuc["hata"]


def test_foto_carousel_gecersiz_urller():
    """Geçersiz URL'ler (http ile başlamayan) ayıklanmalı, hiç kalmazsa hata dönmelidir."""
    with patch("src.tiktok.access_token_al", return_value="mock_token"):
        sonuc = tiktok.foto_carousel_yukle(["file://tmp/img1.jpg", "invalid"], "Test")
        assert sonuc["durum"] is False
        assert "Geçerli HTTPS" in sonuc["hata"]


def test_foto_carousel_token_yok():
    """TikTok erişim jetonu yoksa uygun hata dönmelidir."""
    with patch("src.tiktok.access_token_al", return_value=None):
        sonuc = tiktok.foto_carousel_yukle(
            ["https://example.com/1.jpg", "https://example.com/2.jpg"],
            "Test Başlık",
        )
        assert sonuc["durum"] is False
        assert "TIKTOK_ACCESS_TOKEN eksik" in sonuc["hata"]


def test_foto_carousel_direct_post_basarili():
    """Doğrudan yayın (DIRECT_POST) başarılı olduğunda publish_id dönmelidir."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": {"publish_id": "p_direct_photo_123"},
        "error": {"code": "ok", "message": ""},
    }

    with patch("src.tiktok.access_token_al", return_value="mock_token"), \
         patch("requests.post", return_value=mock_resp) as mock_post:
        sonuc = tiktok.foto_carousel_yukle(
            [
                "https://media.dailybrief.ozbornstudio.com/sosyal/1.jpg",
                "https://media.dailybrief.ozbornstudio.com/sosyal/2.jpg",
            ],
            baslik="Yeni Nesil AI Modeli",
            etiketler=["teknoloji", "yapayzeka"],
        )
        assert sonuc["durum"] is True
        assert sonuc["mod"] == "direct_publish"
        assert sonuc["publish_id"] == "p_direct_photo_123"

        # İstek parametrelerini doğrula
        cagrilar = mock_post.call_args_list
        assert len(cagrilar) == 1
        gonderilen_json = cagrilar[0][1]["json"]
        assert gonderilen_json["media_type"] == "PHOTO"
        assert gonderilen_json["post_mode"] == "DIRECT_POST"
        assert len(gonderilen_json["source_info"]["photo_images"]) == 2


def test_foto_carousel_direct_post_403_inbox_fallback():
    """DIRECT_POST 403 unaudited_client aldığında otomatik MEDIA_UPLOAD (Inbox) moduna düşmelidir."""
    mock_direct_fail = MagicMock()
    mock_direct_fail.status_code = 403
    mock_direct_fail.json.return_value = {
        "error": {"code": "unaudited_client_can_only_post_to_private_accounts", "message": "App audit required"}
    }

    mock_inbox_ok = MagicMock()
    mock_inbox_ok.status_code = 200
    mock_inbox_ok.json.return_value = {
        "data": {"publish_id": "p_inbox_draft_456"},
        "error": {"code": "ok", "message": ""},
    }

    with patch("src.tiktok.access_token_al", return_value="mock_token"), \
         patch("requests.post", side_effect=[mock_direct_fail, mock_inbox_ok]) as mock_post:
        sonuc = tiktok.foto_carousel_yukle(
            [
                "https://media.dailybrief.ozbornstudio.com/sosyal/1.jpg",
                "https://media.dailybrief.ozbornstudio.com/sosyal/2.jpg",
            ],
            baslik="Borsa Kapanış Raporu",
        )
        assert sonuc["durum"] is True
        assert sonuc["mod"] == "inbox_draft"
        assert sonuc["publish_id"] == "p_inbox_draft_456"
        assert mock_post.call_count == 2


def test_foto_carousel_url_unverified_tespiti():
    """Alan adı doğrulanmadığında url_ownership_unverified hatası yakalanmalıdır."""
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.json.return_value = {
        "error": {"code": "url_ownership_unverified", "message": "Domain not verified in TikTok dev portal"}
    }

    with patch("src.tiktok.access_token_al", return_value="mock_token"), \
         patch("requests.post", return_value=mock_resp):
        sonuc = tiktok.foto_carousel_yukle(
            [
                "https://media.dailybrief.ozbornstudio.com/sosyal/1.jpg",
                "https://media.dailybrief.ozbornstudio.com/sosyal/2.jpg",
            ],
            baslik="Test",
        )
        assert sonuc["durum"] is False
        assert sonuc.get("url_unverified") is True
        assert "alan adı doğrulanmamış" in sonuc["hata"]
