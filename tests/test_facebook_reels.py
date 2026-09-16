"""
test_facebook_reels.py — Facebook Reels yükleme ve bağlantı birim testleri.
"""

import os
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch
import pytest

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

from src import facebook


def test_facebook_reels_baglantisi():
    """reels_baglantisi beklenen Facebook Reel URL formatını üretir."""
    url = facebook.reels_baglantisi("987654321")
    assert url == "https://www.facebook.com/reel/987654321"


def test_facebook_reels_video_yok():
    """Var olmayan video dosyası için FileNotFoundError fırlatılır."""
    with pytest.raises(FileNotFoundError):
        facebook.reels_yayinla("bu_dosya_kesinlikle_yok.mp4", "Açıklama", {})


@patch("src.facebook.requests.post")
@patch("src.facebook.sayfa_bilgisi")
@patch("src.facebook._jeton")
def test_facebook_reels_yayinla_basarili(mock_jeton, mock_sayfa, mock_post, tmp_path):
    """Facebook Reels 3 aşamalı yükleme akışını (start -> rupload -> finish) başarıyla tamamlar."""
    mock_jeton.return_value = "EAABtesttoken"
    mock_sayfa.return_value = {"id": "123456789", "name": "Daily Brief Test"}

    # Sahte video dosyası
    sahte_video = tmp_path / "test_reels.mp4"
    sahte_video.write_bytes(b"dummy mp4 video bytes" * 50)

    # 1. Start yanıtı
    mock_start_resp = MagicMock()
    mock_start_resp.status_code = 200
    mock_start_resp.json.return_value = {
        "video_id": "999888777",
        "upload_url": "https://rupload.facebook.com/video-upload/v21.0/999888777",
    }

    # 2. Rupload yanıtı
    mock_upload_resp = MagicMock()
    mock_upload_resp.status_code = 200
    mock_upload_resp.json.return_value = {"success": True}

    # 3. Finish yanıtı
    mock_finish_resp = MagicMock()
    mock_finish_resp.status_code = 200
    mock_finish_resp.json.return_value = {"success": True, "id": "999888777"}

    mock_post.side_effect = [mock_start_resp, mock_upload_resp, mock_finish_resp]

    ayarlar = {
        "instagram": {
            "api_surumu": "v21.0",
            "zaman_asimi": 30,
        }
    }

    # Fon müziği mikslemeyi mockla (mevcut videoyu döndürsün)
    with patch("src.youtube.youtube_icin_sesli_video_hazirla", return_value=sahte_video):
        video_id = facebook.reels_yayinla(
            sahte_video,
            "Bu bir **test** Reels videosudur #DailyBrief",
            ayarlar,
        )

    assert video_id == "999888777"
    assert mock_post.call_count == 3

    # 1. İstek kontrolü: start
    c1_args, c1_kwargs = mock_post.call_args_list[0]
    assert "video_reels" in c1_args[0]
    assert c1_kwargs["data"]["upload_phase"] == "start"
    assert c1_kwargs["data"]["access_token"] == "EAABtesttoken"

    # 2. İstek kontrolü: rupload
    c2_args, c2_kwargs = mock_post.call_args_list[1]
    assert c2_args[0] == "https://rupload.facebook.com/video-upload/v21.0/999888777"
    assert c2_kwargs["headers"]["offset"] == "0"
    assert c2_kwargs["headers"]["Authorization"] == "OAuth EAABtesttoken"
    assert c2_kwargs["headers"]["file_size"] == str(sahte_video.stat().st_size)

    # 3. İstek kontrolü: finish
    c3_args, c3_kwargs = mock_post.call_args_list[2]
    assert "video_reels" in c3_args[0]
    assert c3_kwargs["data"]["upload_phase"] == "finish"
    assert c3_kwargs["data"]["video_id"] == "999888777"
    assert c3_kwargs["data"]["video_state"] == "PUBLISHED"
    # Markdown yıldızları temizlenmiş olmalı
    assert "**" not in c3_kwargs["data"]["description"]
