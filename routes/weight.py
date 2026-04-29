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


@weight_bp.route("/api/weight/calibrate", methods=["POST"])
def calibrate_scale():
    """
    คาลิเบรตเครื่องชั่ง

    Step 1 — tare (ส่ง step=1): อ่าน zero_raw ขณะถาดว่าง
    Step 2 — calc (ส่ง step=2, known_grams=XXX): อ่าน raw ขณะวางของ แล้วคำนวณ scale_factor

    Body JSON:
        step         : 1 หรือ 2
        known_grams  : น้ำหนักของที่รู้จริง (กรัม) — ใช้เฉพาะ step 2
    """
    from flask import current_app
    import statistics, time

    lc = getattr(current_app, "loadcell", None)
    if lc is None or not lc.is_available:
        return jsonify({"success": False, "error": "ไม่พบเครื่องชั่ง"}), 400

    body = request.get_json(silent=True) or {}
    step = int(body.get("step", 1))

    hx = lc._hx

    def read_raw_samples(n=20):
        samples = []
        for _ in range(n):
            try:
                data = hx.get_raw_data()
                if data:
                    samples.extend(data)
            except Exception:
                pass
            time.sleep(0.05)
        return samples

    if step == 1:
        # Tare — บันทึก zero_raw
        samples = read_raw_samples(20)
        if not samples:
            return jsonify({"success": False, "error": "อ่านค่าไม่ได้"}), 500
        zero_raw = statistics.mean(samples)
        # เก็บ zero_raw ชั่วคราวใน app context
        current_app._calib_zero_raw = zero_raw
        return jsonify({
            "success": True,
            "step": 1,
            "zero_raw": round(zero_raw, 1),
            "message": "Tare สำเร็จ — วางของที่รู้น้ำหนักบนถาด แล้วส่ง step 2"
        })

    elif step == 2:
        known_grams = float(body.get("known_grams", 0))
        if known_grams <= 0:
            return jsonify({"success": False, "error": "กรุณาระบุ known_grams > 0"}), 400

        zero_raw = getattr(current_app, "_calib_zero_raw", None)
        if zero_raw is None:
            return jsonify({"success": False, "error": "ต้องทำ step 1 ก่อน"}), 400

        samples = read_raw_samples(20)
        if not samples:
            return jsonify({"success": False, "error": "อ่านค่าไม่ได้"}), 500

        loaded_raw = statistics.mean(samples)
        scale_factor = (loaded_raw - zero_raw) / known_grams

        if abs(scale_factor) < 1:
            return jsonify({"success": False, "error": f"scale_factor ผิดปกติ ({scale_factor:.2f}) — ลองใหม่"}), 400

        # ตั้งค่าใหม่ทันที
        lc.set_calibration(zero_raw=zero_raw, scale_factor=scale_factor)
        current_app._calib_zero_raw = None

        # บันทึกลง .env เพื่อให้คงอยู่หลัง restart
        _save_env("LOADCELL_ZERO_RAW", str(round(zero_raw, 1)))
        _save_env("LOADCELL_SCALE_FACTOR", str(round(scale_factor, 4)))

        return jsonify({
            "success": True,
            "step": 2,
            "zero_raw": round(zero_raw, 1),
            "scale_factor": round(scale_factor, 4),
            "loaded_raw": round(loaded_raw, 1),
            "known_grams": known_grams,
            "message": f"คาลิเบรตสำเร็จ! scale_factor = {scale_factor:.4f}"
        })

    return jsonify({"success": False, "error": "step ต้องเป็น 1 หรือ 2"}), 400


def _save_env(key: str, value: str):
    """เขียน/อัปเดต key=value ใน .env"""
    import os
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    lines = []
    found = False
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            lines = f.readlines()
    new_lines = []
    for line in lines:
        if line.startswith(f"{key}="):
            new_lines.append(f"{key}={value}\n")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{key}={value}\n")
    with open(env_path, "w") as f:
        f.writelines(new_lines)
