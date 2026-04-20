# SQLite schema + CRUD

"""
database.py
─────────────────────────────────────────────────────────
จัดการฐานข้อมูล SQLite ทั้งหมด

มี 2 ตาราง:
  detection_sessions  → 1 session = 1 ครั้งที่กดตรวจจับ
  detection_items     → รายการอาหารแต่ละชิ้นใน session

แก้ไขที่นี่เมื่อ:
  - ต้องการเพิ่มคอลัมน์ใหม่ (เพิ่มใน SCHEMA_SQL + functions)
  - ต้องการ query ใหม่
─────────────────────────────────────────────────────────
"""

import uuid
import sqlite3
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── Schema ─────────────────────────────────────────────────
# แก้ตรงนี้เพื่อเพิ่มคอลัมน์ใหม่
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS detection_sessions (
    id            INTEGER  PRIMARY KEY AUTOINCREMENT,
    session_uuid  TEXT     NOT NULL UNIQUE,
    image_path    TEXT     NOT NULL,
    created_at    TEXT     NOT NULL DEFAULT (datetime('now', 'localtime')),  -- วันที่เวลาที่บันทึก (เมื่อกดยืนยัน)
    total_price   REAL     NOT NULL DEFAULT 0.0,
    weight_grams  REAL     NOT NULL DEFAULT 0.0,
    item_count    INTEGER  NOT NULL DEFAULT 0,
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS detection_items (
    id            INTEGER  PRIMARY KEY AUTOINCREMENT,
    session_id    INTEGER  NOT NULL
                           REFERENCES detection_sessions(id)
                           ON DELETE CASCADE,
    food_name     TEXT     NOT NULL,
    food_name_th  TEXT,
    food_name_en  TEXT,
    confidence    REAL     NOT NULL DEFAULT 0.0,
    price         REAL     NOT NULL DEFAULT 0.0,
    weight_grams  REAL     NOT NULL DEFAULT 0.0,
    bbox_x1       REAL,
    bbox_y1       REAL,
    bbox_x2       REAL,
    bbox_y2       REAL
);

CREATE INDEX IF NOT EXISTS idx_sessions_created ON detection_sessions(created_at);
CREATE INDEX IF NOT EXISTS idx_items_session    ON detection_items(session_id);
"""


# ── Connection ─────────────────────────────────────────────

def get_db_connection(db_path: str) -> sqlite3.Connection:
    """เปิด connection พร้อมตั้งค่า WAL mode และ foreign keys"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row          # ให้ผลลัพธ์เป็น dict-like
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")  # เร็วขึ้น ปลอดภัยขึ้น
    return conn


def init_db(db_path: str) -> None:
    """สร้างตารางถ้ายังไม่มี (เรียกครั้งเดียวตอน app เริ่มทำงาน)"""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = get_db_connection(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        logger.info("Database initialized: %s", db_path)
    finally:
        conn.close()


# ── Write ──────────────────────────────────────────────────

def save_detection_record(
    db_path: str,
    image_path: str,
    detections: list[dict[str, Any]],
    total_price: float,
    weight: float = 0.0,
    notes: str = "",
) -> int:
    """
    บันทึก 1 detection session พร้อม items ทั้งหมด

    Args:
        db_path     : path ของไฟล์ database
        image_path  : ชื่อไฟล์ภาพ (เก็บแค่ชื่อ ไม่ใช่ path เต็ม)
        detections  : list ของ dict แต่ละ detection
        total_price : ราคารวม
        weight      : น้ำหนักจาก load cell (กรัม)
        notes       : หมายเหตุเพิ่มเติม

    Returns:
        session_id (int) สำหรับอ้างอิงในภายหลัง
    """
    session_uuid = uuid.uuid4().hex
    conn = get_db_connection(db_path)
    try:
        # บันทึก session
        cur = conn.execute(
            """INSERT INTO detection_sessions
               (session_uuid, image_path, total_price, weight_grams, item_count, notes)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_uuid, image_path, total_price, weight, len(detections), notes),
        )
        session_id = cur.lastrowid

        # บันทึก items ทีละชิ้น
        for det in detections:
            bbox = det.get("bbox", {})
            conn.execute(
                """INSERT INTO detection_items
                   (session_id, food_name, food_name_th, food_name_en,
                    confidence, price, weight_grams,
                    bbox_x1, bbox_y1, bbox_x2, bbox_y2)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    det.get("name", "unknown"),
                    det.get("name_th", ""),
                    det.get("name_en", ""),
                    det.get("confidence", 0.0),
                    det.get("price", 0.0),
                    det.get("weight", 0.0),
                    bbox.get("x1"), bbox.get("y1"),
                    bbox.get("x2"), bbox.get("y2"),
                ),
            )

        conn.commit()
        logger.info("Saved session %d with %d items", session_id, len(detections))
        return session_id

    except Exception:
        conn.rollback()
        logger.exception("Failed to save detection record")
        raise
    finally:
        conn.close()


# ── Read ───────────────────────────────────────────────────

def get_all_detections(db_path: str, page: int = 1, per_page: int = 20) -> dict:
    """
    ดึงประวัติ detection แบบ pagination

    Returns:
        dict มี keys: sessions, total, page, per_page, total_pages
    """
    offset = (page - 1) * per_page
    conn = get_db_connection(db_path)
    try:
        total = conn.execute(
            "SELECT COUNT(*) FROM detection_sessions"
        ).fetchone()[0]

        rows = conn.execute(
            """SELECT * FROM detection_sessions
               ORDER BY created_at DESC
               LIMIT ? OFFSET ?""",
            (per_page, offset),
        ).fetchall()

        sessions = []
        for row in rows:
            s = dict(row)
            items = conn.execute(
                "SELECT * FROM detection_items WHERE session_id = ? ORDER BY id",
                (s["id"],),
            ).fetchall()
            s["items"] = [dict(i) for i in items]
            sessions.append(s)

        return {
            "sessions":    sessions,
            "total":       total,
            "page":        page,
            "per_page":    per_page,
            "total_pages": max(1, (total + per_page - 1) // per_page),
        }
    finally:
        conn.close()


def get_session_by_id(db_path: str, session_id: int) -> dict | None:
    """ดึง session เดี่ยวพร้อม items ทั้งหมด คืน None ถ้าไม่พบ"""
    conn = get_db_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM detection_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if not row:
            return None
        s = dict(row)
        items = conn.execute(
            "SELECT * FROM detection_items WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        s["items"] = [dict(i) for i in items]
        return s
    finally:
        conn.close()
