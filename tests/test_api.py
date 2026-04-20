"""
tests/test_api.py
─────────────────────────────────────────────────────────
Integration tests สำหรับ Flask API endpoints ทั้งหมด

ทดสอบ HTTP request/response จริง ผ่าน test client
ใช้ fixture จาก conftest.py

รัน:
    pytest tests/test_api.py -v
─────────────────────────────────────────────────────────
"""

import io
import json
import base64
import pytest


# ═══ GET /api/status ═══════════════════════════════════════

class TestStatusEndpoint:

    def test_returns_200(self, client):
        r = client.get("/api/status")
        assert r.status_code == 200

    def test_success_true(self, client):
        data = r_json(client.get("/api/status"))
        assert data["success"] is True

    def test_has_data_key(self, client):
        data = r_json(client.get("/api/status"))
        assert "data" in data

    def test_data_has_camera_active(self, client):
        data = r_json(client.get("/api/status"))
        assert "camera_active" in data["data"]


# ═══ GET /api/weight ═══════════════════════════════════════

class TestWeightEndpoint:

    def test_returns_200(self, client):
        r = client.get("/api/weight")
        assert r.status_code == 200

    def test_has_weight_field(self, client):
        data = r_json(client.get("/api/weight"))
        assert "weight" in data

    def test_weight_is_float(self, client):
        data = r_json(client.get("/api/weight"))
        assert isinstance(data["weight"], (int, float))

    def test_weight_non_negative(self, client):
        data = r_json(client.get("/api/weight"))
        assert data["weight"] >= 0


# ═══ POST /api/detect ══════════════════════════════════════

class TestDetectEndpoint:

    def test_upload_file_returns_200(self, client, jpeg_bytes):
        r = client.post(
            "/api/detect",
            data={"image": (io.BytesIO(jpeg_bytes), "food.jpg")},
            content_type="multipart/form-data",
        )
        assert r.status_code == 200

    def test_upload_file_success_true(self, client, jpeg_bytes):
        data = _detect_with_file(client, jpeg_bytes)
        assert data["success"] is True

    def test_upload_file_has_detections(self, client, jpeg_bytes):
        data = _detect_with_file(client, jpeg_bytes)
        assert "detections" in data
        assert isinstance(data["detections"], list)

    def test_upload_file_has_total_price(self, client, jpeg_bytes):
        data = _detect_with_file(client, jpeg_bytes)
        assert "total_price" in data
        assert data["total_price"] >= 0

    def test_upload_file_has_session_id(self, client, jpeg_bytes):
        data = _detect_with_file(client, jpeg_bytes)
        assert "session_id" in data
        assert isinstance(data["session_id"], int)

    def test_upload_file_has_annotated_image(self, client, jpeg_bytes):
        data = _detect_with_file(client, jpeg_bytes)
        assert "annotated_image" in data
        assert data["annotated_image"].startswith("data:image/jpeg;base64,")

    def test_base64_json_upload(self, client, jpeg_bytes):
        """ทดสอบ upload แบบ base64 JSON"""
        b64  = base64.b64encode(jpeg_bytes).decode()
        data = r_json(client.post("/api/detect", json={"image": b64}))
        assert data["success"] is True

    def test_base64_with_data_uri_prefix(self, client, jpeg_bytes):
        """ต้องตัด data:image/... prefix ออกได้"""
        b64  = "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode()
        data = r_json(client.post("/api/detect", json={"image": b64}))
        assert data["success"] is True

    def test_no_image_returns_400(self, client):
        r = client.post("/api/detect", json={})
        assert r.status_code == 400

    def test_empty_form_returns_400(self, client):
        r = client.post("/api/detect", data={}, content_type="multipart/form-data")
        assert r.status_code == 400

    def test_invalid_file_type_returns_400(self, client):
        r = client.post(
            "/api/detect",
            data={"image": (io.BytesIO(b"fake"), "virus.exe")},
            content_type="multipart/form-data",
        )
        assert r.status_code == 400

    def test_total_price_equals_sum_of_items(self, client, jpeg_bytes):
        """total_price ต้องเท่ากับ sum ของ price แต่ละ item"""
        data     = _detect_with_file(client, jpeg_bytes)
        expected = sum(d["price"] for d in data["detections"])
        assert data["total_price"] == pytest.approx(expected)

    def test_session_saved_to_history(self, client, jpeg_bytes):
        """หลัง detect ต้องมีใน /api/history"""
        _detect_with_file(client, jpeg_bytes)
        history = r_json(client.get("/api/history"))
        assert history["data"]["total"] >= 1


# ═══ GET /api/history ══════════════════════════════════════

class TestHistoryEndpoint:

    def test_empty_history(self, client):
        data = r_json(client.get("/api/history"))
        assert data["success"] is True
        assert data["data"]["total"] == 0

    def test_pagination_default(self, client, jpeg_bytes):
        for _ in range(3):
            _detect_with_file(client, jpeg_bytes)
        data = r_json(client.get("/api/history"))
        assert data["data"]["total"] == 3

    def test_pagination_per_page(self, client, jpeg_bytes):
        for _ in range(5):
            _detect_with_file(client, jpeg_bytes)
        data = r_json(client.get("/api/history?per_page=2"))
        assert len(data["data"]["sessions"]) == 2
        assert data["data"]["total_pages"] == 3

    def test_session_detail_found(self, client, jpeg_bytes):
        det_data = _detect_with_file(client, jpeg_bytes)
        sid      = det_data["session_id"]
        r = client.get(f"/api/history/{sid}")
        assert r.status_code == 200
        data = r_json(r)
        assert data["data"]["id"] == sid

    def test_session_detail_not_found(self, client):
        r = client.get("/api/history/99999")
        assert r.status_code == 404

    def test_delete_session(self, client, jpeg_bytes):
        det_data = _detect_with_file(client, jpeg_bytes)
        sid      = det_data["session_id"]
        r = client.delete(f"/api/history/{sid}")
        assert r.status_code == 200
        # ต้องหายไปจาก history
        r2 = client.get(f"/api/history/{sid}")
        assert r2.status_code == 404


# ═══ Helpers ═══════════════════════════════════════════════

def r_json(response) -> dict:
    """แปลง response เป็น dict"""
    return json.loads(response.data)


def _detect_with_file(client, jpeg_bytes: bytes) -> dict:
    """ส่งภาพและรับผลลัพธ์"""
    r = client.post(
        "/api/detect",
        data={"image": (io.BytesIO(jpeg_bytes), "food.jpg")},
        content_type="multipart/form-data",
    )
    return r_json(r)