"""
routes/weight.py
─────────────────────────────────────────────────────────
Blueprint: /api/weight

GET  /api/weight         → อ่านน้ำหนักครั้งเดียว (JSON)
GET  /api/weight/stream  → SSE stream realtime ทุก 500 ms
POST /api/weight/tare    → Tare (归零)
POST /api/weight/calibrate → ตั้งค่า zero_raw + scale_factor
─────────────────────────────────────────────────────────
"""

import json
import logging
import time

from flask import Blueprint, Response, jsonify, request
from hardware.loadcell import LoadCell

logger = logging.getLogger(__name__)
weight_bp = Blueprint("weight", __name__, url_prefix="/api")

# Singleton LoadCell — สร้างครั้งเดียวตอน import
_loadcell = LoadCell()


# ── GET /api/weight ────────────────────────────────────
@weight_bp.route("/weight", methods=["GET"])
def get_weight():
    """อ่านน้ำหนักครั้งเดียว"""
    detail = _loadcell.read_detail()
    return jsonify({
        "success": True,
        "weight":  detail["weight_g"],
        "unit":    "grams",
        "stable":  detail["stable"],
        "mock":    detail["mock"],
    })


# ── GET /api/weight/stream ─────────────────────────────
@weight_bp.route("/weight/stream")
def stream_weight():
    """
    Server-Sent Events — ส่งน้ำหนักทุก 500 ms
    Client: EventSource('/api/weight/stream')
    """
    def generate():
        while True:
            try:
                detail = _loadcell.read_detail()
                payload = json.dumps({
                    "weight":   detail["weight_g"],
                    "stable":   detail["stable"],
                    "mock":     detail["mock"],
                    "boundary": detail["boundary_count"],
                })
                yield f"data: {payload}\n\n"
            except GeneratorExit:
                break
            except Exception as exc:
                logger.error("SSE weight error: %s", exc)
                yield f"data: {json.dumps({'error': str(exc)})}\n\n"
            time.sleep(0.5)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # ปิด nginx buffering
        },
    )


# ── POST /api/weight/tare ──────────────────────────────
@weight_bp.route("/weight/tare", methods=["POST"])
def tare_scale():
    """Tare — รีเซ็ตน้ำหนักเป็น 0"""
    ok = _loadcell.tare()
    if ok:
        return jsonify({"success": True, "message": "Tared successfully"})
    return jsonify({
        "success": False,
        "message": "Tare not available (mock mode or hardware error)",
    }), 200


# ── POST /api/weight/calibrate ─────────────────────────
@weight_bp.route("/weight/calibrate", methods=["POST"])
def calibrate():
    """
    ตั้งค่า calibration ด้วยมือ
    Body: { "zero_raw": 12345.6, "scale_factor": 420.0 }
    (copy ค่าจาก test_loadcell.py แล้วส่งมา)
    """
    data = request.get_json(force=True, silent=True) or {}
    try:
        zero_raw     = float(data["zero_raw"])
        scale_factor = float(data["scale_factor"])
    except (KeyError, ValueError, TypeError):
        return jsonify({"success": False, "message": "ต้องส่ง zero_raw และ scale_factor"}), 400

    _loadcell.set_calibration(zero_raw, scale_factor)
    return jsonify({
        "success":      True,
        "zero_raw":     zero_raw,
        "scale_factor": scale_factor,
        "message":      "Calibration updated",
    })
