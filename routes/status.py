# GET  /api/status

"""
routes/status.py
─────────────────────────────────────────────────────────
Blueprint: GET /api/status

คืนสถานะกล้อง, โมเดล, และ hardware

แก้ไขที่นี่เมื่อ:
  - เพิ่มข้อมูลสถานะใหม่ (เช่น disk space, temperature)
─────────────────────────────────────────────────────────
"""

import logging
from flask import Blueprint, jsonify, current_app
from hardware.camera import PiCamera

logger  = logging.getLogger(__name__)
status_bp = Blueprint("status", __name__, url_prefix="/api")

# Camera instance (สร้างครั้งเดียว)
_camera = PiCamera()


@status_bp.route("/status", methods=["GET"])
def camera_status():
    """
    GET /api/status
    คืนสถานะระบบทั้งหมด

    Response:
        {
          "success": true,
          "data": {
            "camera_active": bool,
            "model_loaded":  bool,
            "is_raspberry_pi": bool,
            "platform": str,
            "mode": "yolo" | "mock"
          }
        }
    """
    detector = current_app.detector
    status   = detector.get_status()
    status["camera_active"] = _camera.is_active

    return jsonify({"success": True, "data": status})