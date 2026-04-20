"""
tests/test_database.py
─────────────────────────────────────────────────────────
Unit tests สำหรับ database.py เท่านั้น

รัน:
    pytest tests/test_database.py -v
─────────────────────────────────────────────────────────
"""

import pytest
from database import (
    get_db_connection,
    init_db,
    save_detection_record,
    get_all_detections,
    get_session_by_id,
)

# ── ข้อมูลตัวอย่าง ─────────────────────────────────────────

SAMPLE_DETECTIONS = [
    {
        "name": "pad_thai", "name_th": "ผัดไทย", "name_en": "Pad Thai",
        "confidence": 0.93, "price": 60.0, "weight": 180.0,
        "bbox": {"x1": 10, "y1": 10, "x2": 150, "y2": 200},
    },
    {
        "name": "som_tum", "name_th": "ส้มตำ", "name_en": "Som Tum",
        "confidence": 0.87, "price": 45.0, "weight": 120.0,
        "bbox": {"x1": 160, "y1": 10, "x2": 300, "y2": 200},
    },
]


# ═══ Schema Tests ══════════════════════════════════════════

class TestSchema:

    def test_tables_created(self, tmp_db):
        """ตารางทั้งสองต้องถูกสร้างหลัง init_db"""
        conn   = get_db_connection(tmp_db)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        conn.close()
        assert "detection_sessions" in tables
        assert "detection_items" in tables

    def test_init_idempotent(self, tmp_db):
        """เรียก init_db ซ้ำต้องไม่ throw exception"""
        init_db(tmp_db)
        init_db(tmp_db)   # ไม่ crash

    def test_foreign_key_enabled(self, tmp_db):
        """PRAGMA foreign_keys ต้องเปิดอยู่"""
        conn   = get_db_connection(tmp_db)
        result = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        conn.close()
        assert result == 1


# ═══ Save Tests ════════════════════════════════════════════

class TestSaveRecord:

    def test_returns_integer_id(self, tmp_db):
        """save ต้องคืน session id เป็น int > 0"""
        sid = save_detection_record(tmp_db, "img.jpg", SAMPLE_DETECTIONS, 105.0)
        assert isinstance(sid, int)
        assert sid > 0

    def test_saves_correct_item_count(self, tmp_db):
        """item_count ต้องตรงกับจำนวน detections"""
        sid     = save_detection_record(tmp_db, "img.jpg", SAMPLE_DETECTIONS, 105.0)
        session = get_session_by_id(tmp_db, sid)
        assert session["item_count"] == len(SAMPLE_DETECTIONS)

    def test_saves_items(self, tmp_db):
        """items ต้องถูกบันทึกลง detection_items"""
        sid     = save_detection_record(tmp_db, "img.jpg", SAMPLE_DETECTIONS, 105.0)
        session = get_session_by_id(tmp_db, sid)
        assert len(session["items"]) == 2
        names = {i["food_name"] for i in session["items"]}
        assert names == {"pad_thai", "som_tum"}

    def test_saves_total_price(self, tmp_db):
        """total_price ต้องบันทึกถูกต้อง"""
        sid     = save_detection_record(tmp_db, "img.jpg", SAMPLE_DETECTIONS, 105.0)
        session = get_session_by_id(tmp_db, sid)
        assert session["total_price"] == pytest.approx(105.0)

    def test_saves_weight(self, tmp_db):
        """weight_grams ต้องบันทึกถูกต้อง"""
        sid     = save_detection_record(tmp_db, "img.jpg", SAMPLE_DETECTIONS, 105.0, weight=300.0)
        session = get_session_by_id(tmp_db, sid)
        assert session["weight_grams"] == pytest.approx(300.0)

    def test_empty_detections(self, tmp_db):
        """ต้องรองรับการบันทึก session ที่ไม่มี items"""
        sid     = save_detection_record(tmp_db, "empty.jpg", [], 0.0)
        session = get_session_by_id(tmp_db, sid)
        assert session["item_count"] == 0
        assert session["items"] == []

    def test_session_uuid_unique(self, tmp_db):
        """แต่ละ session ต้องมี UUID ไม่ซ้ำกัน"""
        sid1 = save_detection_record(tmp_db, "a.jpg", [], 0.0)
        sid2 = save_detection_record(tmp_db, "b.jpg", [], 0.0)
        s1   = get_session_by_id(tmp_db, sid1)
        s2   = get_session_by_id(tmp_db, sid2)
        assert s1["session_uuid"] != s2["session_uuid"]


# ═══ Read Tests ════════════════════════════════════════════

class TestGetDetections:

    def test_empty_db_returns_zero_total(self, tmp_db):
        """database ใหม่ต้องมี total = 0"""
        result = get_all_detections(tmp_db)
        assert result["total"] == 0
        assert result["sessions"] == []

    def test_pagination_page1(self, tmp_db):
        """หน้า 1 ต้องคืน per_page รายการ"""
        for i in range(15):
            save_detection_record(tmp_db, f"img_{i}.jpg", [], 0.0)
        result = get_all_detections(tmp_db, page=1, per_page=10)
        assert len(result["sessions"]) == 10
        assert result["total"] == 15
        assert result["total_pages"] == 2

    def test_pagination_last_page(self, tmp_db):
        """หน้าสุดท้ายต้องมีรายการที่เหลือ"""
        for i in range(15):
            save_detection_record(tmp_db, f"img_{i}.jpg", [], 0.0)
        result = get_all_detections(tmp_db, page=2, per_page=10)
        assert len(result["sessions"]) == 5

    def test_ordered_by_newest_first(self, tmp_db):
        """ต้องเรียงจากใหม่ → เก่า"""
        sid1 = save_detection_record(tmp_db, "first.jpg",  [], 0.0)
        sid2 = save_detection_record(tmp_db, "second.jpg", [], 0.0)
        result = get_all_detections(tmp_db)
        ids = [s["id"] for s in result["sessions"]]
        assert ids[0] == sid2   # ใหม่กว่าอยู่หน้า

    def test_session_not_found_returns_none(self, tmp_db):
        """get_session_by_id ต้องคืน None ถ้าไม่พบ"""
        assert get_session_by_id(tmp_db, 9999) is None