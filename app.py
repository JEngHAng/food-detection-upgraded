import logging
import time
import os
import sqlite3
from flask import Flask, jsonify, render_template, send_from_directory, Response, request
from flask_cors import CORS
from config import ServerConfig, DB_PATH, UPLOAD_DIR
from database import init_db
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
    
    return jsonify({
        "success": True,
        "total_price": result.get("total_price", 0),
        "annotated_image": f"/uploads/annotated_{filename}?t={int(time.time())}",
        "dishes": result.get("detections", []),
        "pending_file": filename
    })

# 🚩 เพิ่ม API สำหรับบันทึกข้อมูลลง SQLite พร้อมระบบ Print แจ้งเตือน
@app.route("/api/confirm", methods=["POST"])
def confirm_api():
    try:
        data = request.get_json()
        filename = data.get("filename")
        total_price = data.get("total_price", 0)
        weight = data.get("weight", 0)
        dishes = data.get("dishes", [])

        # รวมชื่อรายการอาหารเป็นข้อความเดียว (คั่นด้วยลูกน้ำ)
        dishes_str = ", ".join([d.get('name_th', d.get('name', '')) for d in dishes])

        # เชื่อมต่อและบันทึกลงฐานข้อมูล
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        
        # สร้าง Table หากยังไม่มี
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS detections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT,
                dishes TEXT,
                weight REAL,
                total_price REAL,
                timestamp TEXT DEFAULT (datetime('now', 'localtime'))
            )
        ''')
        
        cursor.execute('''
            INSERT INTO detections (filename, dishes, weight, total_price)
            VALUES (?, ?, ?, ?)
        ''', (filename, dishes_str, weight, total_price))
        
        conn.commit()
        conn.close()
        
        # 🚩 แสดงผลใน Terminal เพื่อให้เรารู้ว่าดาต้าเข้ามาถึง Python แล้ว
        print(f"\n=====================================")
        print(f"✅ บันทึกข้อมูลสำเร็จ! ไฟล์: {filename}")
        print(f"👉 เมนู: {dishes_str}")
        print(f"👉 ราคารวม: {total_price} บาท | น้ำหนัก: {weight} กรัม")
        print(f"=====================================\n")
        
        return jsonify({"success": True, "message": "บันทึกข้อมูลลง SQLite เรียบร้อย"})
    except Exception as e:
        # 🚩 ถ้าพัง จะโชว์สาเหตุออกมาที่หน้าจอ Terminal ทันที
        print(f"\n❌ ปัญหาฐานข้อมูล! สาเหตุ: {e}\n")
        return jsonify({"success": False, "error": str(e)}), 500

# Route เพื่อให้ Browser เข้ามาดึงรูปภาพพรีวิวไปโชว์ได้
@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
