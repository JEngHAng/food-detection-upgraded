import logging
import time
import os
import sqlite3
import json
import shutil
from flask import Flask, jsonify, render_template, send_from_directory, Response, request
from flask_cors import CORS
from config import ServerConfig, DB_PATH, UPLOAD_DIR
from pathlib import Path

CONFIRMED_DIR = UPLOAD_DIR.parent / "confirmed"
CONFIRMED_DIR.mkdir(exist_ok=True)

# ── นำเข้าฟังก์ชันจัดการฐานข้อมูลจาก database.py ──────────────────
from database import (
    init_db, 
    save_detection_record, 
    get_all_detections, 
    get_session_by_id, 
    get_db_connection
)
from detector import FoodDetector
from hardware.camera import PiCamera
from routes.weight import weight_bp          # ← Weight / SSE blueprint

app = Flask(__name__)
CORS(app)
app.config["UPLOAD_FOLDER"] = str(UPLOAD_DIR)

# ── Register Blueprints ────────────────────────────────
app.register_blueprint(weight_bp)

# ตรวจสอบว่ามีโฟลเดอร์สำหรับเซฟรูปหรือยัง
if not os.path.exists(app.config["UPLOAD_FOLDER"]):
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

init_db(str(DB_PATH))

app.detector = FoodDetector()
app.camera = PiCamera()

# Tare เครื่องชั่งอัตโนมัติตอนเริ่ม app
from hardware.loadcell import LoadCell
app.loadcell = LoadCell()
app.tare_status = "pending"  # pending, running, done, failed
import threading
def auto_tare():
    import time
    time.sleep(3)
    app.tare_status = "running"
    if app.loadcell.is_available:
        success = app.loadcell.tare()
        if success:
            app.tare_status = "done"
            print("✅ Auto tare สำเร็จ — น้ำหนักรีเซ็ตเป็น 0.0 กรัม")
        else:
            app.tare_status = "failed"
            print("⚠️ Auto tare ไม่สำเร็จ")
    else:
        app.tare_status = "done"
        print("⚠️ ไม่พบเครื่องชั่ง — ข้าม auto tare")

threading.Thread(target=auto_tare, daemon=True).start()

@app.route("/api/tare_status")
def tare_status():
    return jsonify({"status": app.tare_status})

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/video_feed")
def video_feed():
    def generate():
        while True:
            frame = app.camera.get_frame()
            if frame:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            time.sleep(0.1)
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route("/api/capture", methods=["POST"])
def capture_api():
    path = app.camera.capture()
    if path:
        filename = os.path.basename(path)
        # ส่ง image_url พร้อม Timestamp เพื่อป้องกัน Browser จำภาพเก่า (Cache)
        return jsonify({
            "success": True, 
            "filename": filename,
            "image_url": f"/uploads/{filename}?t={int(time.time())}"
        })
    return jsonify({"success": False, "error": "Camera Busy"}), 500

@app.route("/api/detect-captured", methods=["POST"])
def detect_api():
    data = request.get_json()
    filename = data.get("filename")
    if not filename:
        return jsonify({"success": False, "error": "No file"}), 400
    
    image_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    result = app.detector.detect(image_path)
    
    matched_menus = result.get("matched_menus", [])
    detections    = result.get("detections", [])
    total_price   = result.get("total_price", 0)

    return jsonify({
        "success": True,
        "total_price": total_price,
        "annotated_image": f"/uploads/annotated_{filename}?t={int(time.time())}",
        "dishes": matched_menus,
        "detections": detections,   # ← raw detections ทุกอย่างที่ YOLO เจอ
        "pending_file": filename
    })

# 🚩 API สำหรับบันทึกข้อมูล (แก้ให้รับค่าน้ำหนักและรูปภาพได้ถูกต้อง 100%)
@app.route("/api/confirm", methods=["POST"])
def confirm_api():
    try:
        data = request.get_json()
        
        # 1. บังคับชนิดตัวแปรป้องกันบั๊ก
        filename = str(data.get("filename", ""))
        total_price = float(data.get("total_price", 0.0))
        weight = float(data.get("weight", 0.0))
        dishes = data.get("dishes", [])
        raw_detections = data.get("detections", [])

        # แจ้งเตือนใน Terminal เพื่อตรวจสอบความถูกต้อง
        print(f"\n📥 [DEBUG] กำลังเตรียมบันทึกข้อมูล:")
        print(f"   - ไฟล์รูปภาพ: {filename}")
        print(f"   - น้ำหนักรวม: {weight} กรัม")
        print(f"   - ราคารวม: {total_price} บาท")

        if not filename:
             return jsonify({"success": False, "error": "ไม่ได้ระบุชื่อไฟล์รูปภาพ"}), 400

        used_names = set()
        items_to_save = []

        # 2. รวบรวมข้อมูลจากจานหลักและส่วนผสม
        for d in dishes:
            used_names.add(d.get("name", ""))
            items_to_save.append({
                "name": d.get("name", "unknown"),
                "name_th": d.get("name_th", ""),
                "name_en": d.get("name_en", ""),
                "confidence": float(d.get("confidence", 0.0)),
                "price": float(d.get("price", 0.0)),
                "weight": float(d.get("weight", 0.0)),
                "bbox": d.get("bbox", {})
            })
            for ing in d.get("ingredients", []):
                used_names.add(ing.get("name", ""))
                items_to_save.append({
                    "name": ing.get("name", "unknown"),
                    "name_th": ing.get("name_th", ""),
                    "name_en": ing.get("name_en", ""),
                    "confidence": float(ing.get("confidence", 0.0)),
                    "price": 0.0,
                    "weight": float(ing.get("weight", 0.0)),
                    "bbox": d.get("bbox", {})
                })

        # 3. รวบรวมสิ่งที่เจอแต่ไม่อยู่ในเมนู (Extra)
        extra = [d for d in raw_detections if d.get("name", "") not in used_names]
        for d in extra:
            items_to_save.append({
                "name": d.get("name", "unknown"),
                "name_th": d.get("name_th", ""),
                "name_en": d.get("name_en", ""),
                "confidence": float(d.get("confidence", 0.0)),
                "price": float(d.get("price", 0.0)),
                "weight": float(d.get("weight", 0.0)),
                "bbox": d.get("bbox", {})
            })

        # 4. บันทึกผ่าน database.py 
        session_id = save_detection_record(
            db_path=str(DB_PATH),
            image_path=filename,       # รูปภาพจะถูกบันทึกตรงนี้
            detections=items_to_save,
            total_price=total_price,
            weight=weight,             # น้ำหนักจะถูกบันทึกตรงนี้
            notes=""
        )
        
        # 5. ย้าย/ลบ ไฟล์รูปภาพ
        annotated = os.path.join(app.config["UPLOAD_FOLDER"], f"annotated_{filename}")
        if os.path.exists(annotated):
            shutil.move(annotated, str(CONFIRMED_DIR / f"annotated_{filename}"))
        
        orig = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        if os.path.exists(orig):
            os.remove(orig)
            
        print(f"✅ บันทึกข้อมูลลงฐานข้อมูลสำเร็จ! (Session ID: {session_id})\n")
        return jsonify({"success": True, "message": "บันทึกข้อมูลเรียบร้อย", "session_id": session_id})

    except Exception as e:
        print(f"\n❌ ปัญหาฐานข้อมูล! สาเหตุ: {e}\n")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/cleanup", methods=["POST"])
def cleanup_api():
    """ลบรูปที่ยังไม่ได้ยืนยัน"""
    try:
        data = request.get_json() or {}
        filename = data.get("filename")
        deleted = []
        if filename:
            for name in [filename, f"annotated_{filename}"]:
                p = os.path.join(app.config["UPLOAD_FOLDER"], name)
                if os.path.exists(p):
                    os.remove(p)
                    deleted.append(name)
        return jsonify({"success": True, "deleted": deleted})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.route("/history")
def history_page():
    return render_template("history.html")

# 🚩 ดึงประวัติทั้งหมด (ทำ Data Mapping เพื่อให้รูปและน้ำหนักแสดงบนหน้าเว็บเก่าได้)
@app.route("/api/history")
def api_history():
    try:
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 50))
        
        # ดึงข้อมูลจาก 2 ตาราง
        result = get_all_detections(str(DB_PATH), page=page, per_page=per_page)
        
        # --- ทำ Data Mapping แปลงกลับให้หน้าเว็บหาตัวแปรเจอ ---
        for session in result.get("sessions", []):
            session["session_uuid"] = session.get("image_path", "")
            session["filename"] = session.get("image_path", "")
            session["weight"] = session.get("weight_grams", 0.0)
            session["timestamp"] = session.get("created_at", "")
            
            for item in session.get("items", []):
                item["weight"] = item.get("weight_grams", 0.0)
        
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "data": {"sessions": [], "total": 0}, "error": str(e)})

# 🚩 ดึงประวัติเฉพาะบิล (ทำ Data Mapping เหมือนกัน)
@app.route("/api/history/<int:session_id>")
def api_history_detail(session_id):
    try:
        session_data = get_session_by_id(str(DB_PATH), session_id)
        if not session_data:
            return jsonify({"success": False, "error": "Not found"}), 404
            
        # --- ทำ Data Mapping ---
        session_data["session_uuid"] = session_data.get("image_path", "")
        session_data["filename"] = session_data.get("image_path", "")
        session_data["weight"] = session_data.get("weight_grams", 0.0)
        session_data["timestamp"] = session_data.get("created_at", "")
        for item in session_data.get("items", []):
            item["weight"] = item.get("weight_grams", 0.0)
            
        return jsonify({"success": True, "data": session_data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

# 🚩 ลบประวัติ
@app.route("/api/history/<int:session_id>", methods=["DELETE"])
def api_history_delete(session_id):
    try:
        conn = get_db_connection(str(DB_PATH))
        # ด้วย ON DELETE CASCADE มันจะลบรายการใน detection_items ให้ด้วยอัตโนมัติ
        conn.execute("DELETE FROM detection_sessions WHERE id=?", (session_id,))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

# 🚩 ดึงสถิติ
@app.route("/api/stats")
def api_stats():
    try:
        conn = get_db_connection(str(DB_PATH))
        
        # สรุปภาพรวมจากตาราง sessions
        total_count   = conn.execute("SELECT COUNT(*) FROM detection_sessions").fetchone()[0]
        total_revenue = conn.execute("SELECT COALESCE(SUM(total_price),0) FROM detection_sessions").fetchone()[0]
        avg_price     = conn.execute("SELECT COALESCE(AVG(total_price),0) FROM detection_sessions").fetchone()[0]
        avg_weight    = conn.execute("SELECT COALESCE(AVG(weight_grams),0) FROM detection_sessions").fetchone()[0]
        
        # หายอดนิยมจากตาราง items จัดกลุ่มด้วยชื่อเมนู
        rows = conn.execute("""
            SELECT COALESCE(NULLIF(food_name_th, ''), food_name) as name, COUNT(*) as count
            FROM detection_items
            WHERE name != 'unknown' AND name != ''
            GROUP BY name
            ORDER BY count DESC
            LIMIT 5
        """).fetchall()
        
        conn.close()

        top_menus = [{"name": r["name"], "count": r["count"]} for r in rows]

        return jsonify({
            "total_count":   total_count,
            "total_revenue": total_revenue,
            "avg_price":     avg_price,
            "avg_weight":    avg_weight,
            "top_menus":     top_menus,
        })
    except Exception as e:
        return jsonify({"total_count":0,"total_revenue":0,"avg_price":0,"avg_weight":0,"top_menus":[],"error":str(e)})


@app.route("/confirmed/<path:filename>")
def confirmed_file(filename):
    return send_from_directory(str(CONFIRMED_DIR), filename)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
