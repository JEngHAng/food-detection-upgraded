"""
routes/camera.py
────────────────────────────────────────────────────────
Blueprint สำหรับ camera endpoints

Routes:
  GET  /video_feed          — MJPEG live stream
  POST /api/capture         — ถ่ายภาพนิ่ง
────────────────────────────────────────────────────────
"""

import logging
import os
import time
from flask import Blueprint, Response, current_app, jsonify

logger = logging.getLogger(__name__)

camera_bp = Blueprint("camera", __name__)


@camera_bp.route("/video_feed")
def video_feed():
    """MJPEG stream จาก PiCamera.get_frame()"""

    def generate():
        while True:
            frame = current_app.camera.get_frame()
            if frame:
                yield (
                    b"--frame\r\n" b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                )
            time.sleep(0.1)

    return Response(
        generate(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@camera_bp.route("/api/capture", methods=["POST"])
def capture():
    """ถ่ายภาพนิ่ง — คืน filename + image_url"""
    path = current_app.camera.capture()
    if not path:
        return jsonify({"success": False, "error": "Camera busy"}), 500

    filename = os.path.basename(path)
    return jsonify(
        {
            "success": True,
            "filename": filename,
            "image_url": f"/uploads/{filename}?t={int(time.time())}",
        }
    )
