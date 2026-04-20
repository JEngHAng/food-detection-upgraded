"""
tests/conftest.py
─────────────────────────────────────────────────────────
Shared fixtures ที่ทุก test file ใช้ร่วมกัน

Fixtures:
  tmp_db    → database ชั่วคราวสำหรับแต่ละ test
  tmp_img   → ภาพ JPEG จำลองสำหรับ test
  client    → Flask test client
  mock_det  → FoodDetector ที่ force ใช้ mock mode
─────────────────────────────────────────────────────────
"""

import os
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np
import pytest

# เพิ่ม root ของโปรเจคใน Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import init_db
from detector import FoodDetector


# ── Database fixture ───────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path):
    """
    สร้าง SQLite database ชั่วคราวสำหรับแต่ละ test
    จะถูกลบอัตโนมัติหลัง test จบ
    """
    db = str(tmp_path / "test.db")
    init_db(db)
    return db


# ── Image fixture ──────────────────────────────────────────

@pytest.fixture
def tmp_img(tmp_path):
    """
    สร้างภาพ JPEG จำลอง 320×240 px สำหรับ test
    มีสีและข้อความเพื่อให้ OpenCV อ่านได้จริง
    """
    img  = np.zeros((240, 320, 3), dtype=np.uint8)
    img[:] = (30, 30, 30)  # พื้นหลังสีเทาเข้ม

    # วาดสี่เหลี่ยมจำลองอาหาร
    cv2.rectangle(img, (40, 40), (280, 200), (60, 180, 100), -1)
    cv2.putText(img, "MOCK FOOD", (70, 130),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)

    path = str(tmp_path / "test_food.jpg")
    cv2.imwrite(path, img)
    return path


# ── Flask test client fixture ──────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    """
    Flask test client พร้อม database ชั่วคราว
    mock hardware ทั้งหมดเพื่อ test บน PC ได้
    """
    # ต้อง import หลัง set env vars
    import app as app_module

    db_path    = str(tmp_path / "test.db")
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()

    # Override config ให้ชี้ไปที่ tmp folder
    monkeypatch.setattr(app_module, "DB_PATH", Path(db_path))
    monkeypatch.setattr(app_module, "UPLOAD_DIR", upload_dir)

    flask_app = app_module.create_app()
    flask_app.config["TESTING"]       = True
    flask_app.config["DB_PATH"]       = db_path
    flask_app.config["UPLOAD_FOLDER"] = str(upload_dir)

    init_db(db_path)

    # Force mock mode (ไม่ต้องมี Pi หรือ best.pt)
    flask_app.detector._is_pi = False
    flask_app.detector.model  = None

    return flask_app.test_client()


# ── Mock detector fixture ──────────────────────────────────

@pytest.fixture
def mock_det():
    """FoodDetector ใน mock mode เสมอ"""
    det       = FoodDetector()
    det.model = None       # force mock
    det._is_pi = False
    return det


# ── JPEG bytes helper ──────────────────────────────────────

@pytest.fixture
def jpeg_bytes():
    """สร้าง JPEG bytes สำหรับ upload test"""
    img = np.zeros((120, 160, 3), dtype=np.uint8)
    cv2.rectangle(img, (20, 20), (140, 100), (0, 200, 100), -1)
    _, buf = cv2.imencode(".jpg", img)
    return buf.tobytes()