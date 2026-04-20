"""
tests/test_detector.py
─────────────────────────────────────────────────────────
Unit tests สำหรับ detector.py

ทดสอบ mock mode เท่านั้น (ไม่ต้องมี best.pt)
ใช้ fixture จาก conftest.py

รัน:
    pytest tests/test_detector.py -v
─────────────────────────────────────────────────────────
"""

import pytest
from pathlib import Path
from detector import FoodDetector


# ═══ Status Tests ══════════════════════════════════════════

class TestStatus:

    def test_get_status_has_required_keys(self, mock_det):
        status = mock_det.get_status()
        for key in ("model_loaded", "is_raspberry_pi", "platform", "mode"):
            assert key in status

    def test_mock_mode_model_not_loaded(self, mock_det):
        assert mock_det.get_status()["model_loaded"] is False

    def test_mock_mode_string(self, mock_det):
        assert mock_det.get_status()["mode"] == "mock"

    def test_not_raspberry_pi_on_pc(self, mock_det):
        assert mock_det.get_status()["is_raspberry_pi"] is False


# ═══ Detection Tests ═══════════════════════════════════════

class TestMockDetection:

    def test_detect_returns_success_true(self, mock_det, tmp_img):
        result = mock_det.detect(tmp_img)
        assert result["success"] is True

    def test_detect_has_required_keys(self, mock_det, tmp_img):
        result = mock_det.detect(tmp_img)
        for key in ("detections", "total_price", "annotated_path", "mock"):
            assert key in result

    def test_mock_flag_is_true(self, mock_det, tmp_img):
        result = mock_det.detect(tmp_img)
        assert result["mock"] is True

    def test_detections_is_list(self, mock_det, tmp_img):
        result = mock_det.detect(tmp_img)
        assert isinstance(result["detections"], list)

    def test_at_least_one_detection(self, mock_det, tmp_img):
        result = mock_det.detect(tmp_img)
        assert len(result["detections"]) >= 1

    def test_each_detection_has_required_fields(self, mock_det, tmp_img):
        result = mock_det.detect(tmp_img)
        for det in result["detections"]:
            assert "name"       in det
            assert "name_th"    in det
            assert "confidence" in det
            assert "price"      in det
            assert "bbox"       in det

    def test_confidence_in_valid_range(self, mock_det, tmp_img):
        result = mock_det.detect(tmp_img)
        for det in result["detections"]:
            assert 0.0 <= det["confidence"] <= 1.0

    def test_price_non_negative(self, mock_det, tmp_img):
        result = mock_det.detect(tmp_img)
        for det in result["detections"]:
            assert det["price"] >= 0

    def test_total_price_equals_sum(self, mock_det, tmp_img):
        """total_price ต้องเท่ากับ sum ของราคาแต่ละ item"""
        result   = mock_det.detect(tmp_img)
        expected = sum(d["price"] for d in result["detections"])
        assert result["total_price"] == pytest.approx(expected)

    def test_annotated_file_created(self, mock_det, tmp_img):
        """ต้องสร้างไฟล์ภาพที่วาด bounding box แล้ว"""
        result = mock_det.detect(tmp_img)
        assert Path(result["annotated_path"]).exists()

    def test_bbox_keys_present(self, mock_det, tmp_img):
        result = mock_det.detect(tmp_img)
        for det in result["detections"]:
            bbox = det["bbox"]
            for k in ("x1", "y1", "x2", "y2"):
                assert k in bbox

    def test_bbox_coordinates_valid(self, mock_det, tmp_img):
        """x2 ต้องมากกว่า x1, y2 ต้องมากกว่า y1"""
        result = mock_det.detect(tmp_img)
        for det in result["detections"]:
            b = det["bbox"]
            assert b["x2"] > b["x1"]
            assert b["y2"] > b["y1"]


# ═══ Edge Cases ════════════════════════════════════════════

class TestEdgeCases:

    def test_invalid_path_returns_failure(self, mock_det):
        result = mock_det.detect("/nonexistent/image.jpg")
        assert result["success"] is False
        assert "error" in result

    def test_invalid_path_error_message_meaningful(self, mock_det):
        result = mock_det.detect("/nonexistent/image.jpg")
        assert len(result["error"]) > 0