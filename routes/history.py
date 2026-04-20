# GET/DELETE /api/history

"""
routes/history.py
─────────────────────────────────────────────────────────
Blueprint: ประวัติการตรวจจับ

Endpoints:
  GET  /api/history          → รายการทั้งหมด (paginated)
  GET  /api/history/<id>     → session เดี่ยว
  DELETE /api/history/<id>   → ลบ session

แก้ไขที่นี่เมื่อ:
  - เพิ่ม filter (วันที่, ชื่อเมนู)
  - เพิ่ม export CSV
─────────────────────────────────────────────────────────
"""

import logging
from flask import Blueprint, current_app, jsonify, request
from database import get_all_detections, get_session_by_id, get_db_connection

logger     = logging.getLogger(__name__)
history_bp = Blueprint("history", __name__, url_prefix="/api")


@history_bp.route("/history", methods=["GET"])
def list_history():
    """
    GET /api/history?page=1&per_page=20

    Query params:
        page     (int) ← หน้าที่ต้องการ (default 1)
        per_page (int) ← จำนวนต่อหน้า (default 20, max 100)

    Response:
        {
          "success": true,
          "data": {
            "sessions": [...],
            "total": 42,
            "page": 1,
            "per_page": 20,
            "total_pages": 3
          }
        }
    """
    page     = max(1, request.args.get("page", 1, type=int))
    per_page = min(100, max(1, request.args.get("per_page", 20, type=int)))

    db_path = current_app.config["DB_PATH"]
    data    = get_all_detections(db_path, page=page, per_page=per_page)
    return jsonify({"success": True, "data": data})


@history_bp.route("/history/<int:session_id>", methods=["GET"])
def get_history(session_id: int):
    """
    GET /api/history/<session_id>
    ดึงรายละเอียด session เดี่ยวพร้อม items

    Response:
        { "success": true, "data": { session + items } }
    """
    db_path = current_app.config["DB_PATH"]
    session = get_session_by_id(db_path, session_id)
    if not session:
        return jsonify({"success": False, "error": "Session not found"}), 404
    return jsonify({"success": True, "data": session})


@history_bp.route("/history/<int:session_id>", methods=["DELETE"])
def delete_history(session_id: int):
    """
    DELETE /api/history/<session_id>
    ลบ session (และ items ที่เชื่อมอยู่ ผ่าน CASCADE)

    Response:
        { "success": true, "deleted_id": 5 }
    """
    db_path = current_app.config["DB_PATH"]
    conn    = get_db_connection(db_path)
    try:
        row = conn.execute(
            "SELECT id FROM detection_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if not row:
            return jsonify({"success": False, "error": "Session not found"}), 404

        conn.execute(
            "DELETE FROM detection_sessions WHERE id = ?", (session_id,)
        )
        conn.commit()
        logger.info("Deleted session %d", session_id)
        return jsonify({"success": True, "deleted_id": session_id})
    finally:
        conn.close()