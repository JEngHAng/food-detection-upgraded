# ตั้งค่าทั้งหมด (GPIO, server, cleanup)

"""
config.py
─────────────────────────────────────────────────────────
ไฟล์ตั้งค่าหลักของระบบ  ← แก้ไขที่นี่บ่อยที่สุด

สิ่งที่แก้ได้ที่นี่:
  - เพิ่ม / ลบ / เปลี่ยนราคาเมนูอาหาร
  - เปลี่ยน GPIO pin ของ HX711 / Load Cell
  - ปรับค่า confidence ของ YOLOv8
  - เปลี่ยน port หรือ host ของ server
─────────────────────────────────────────────────────────
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# โหลด .env (ถ้ามี)
load_dotenv()

# ── เส้นทางหลักของโปรเจค ──────────────────────────────────
BASE_DIR    = Path(__file__).parent
UPLOAD_DIR  = BASE_DIR / "uploads"
LOG_DIR     = BASE_DIR / "logs"
DATA_DIR    = BASE_DIR / "data"
MODEL_PATH  = BASE_DIR / "models" / "best.pt"
DB_PATH     = BASE_DIR / os.getenv("DB_PATH", "database/food_detection.db")
MENU_PATH             = DATA_DIR / "menu.json"
MENU_INGREDIENTS_PATH = DATA_DIR / "menu_ingredients.json"

# สร้างโฟลเดอร์อัตโนมัติถ้ายังไม่มี
UPLOAD_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)


# ── Flask Server ───────────────────────────────────────────
class ServerConfig:
    HOST      = os.getenv("HOST", "0.0.0.0")
    PORT      = int(os.getenv("PORT", 5000))
    DEBUG     = os.getenv("FLASK_DEBUG", "0") == "1"
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-in-production")
    MAX_UPLOAD_MB = 16               # ขนาดไฟล์สูงสุดที่รับได้ (MB)


# ── YOLOv8 Detection ───────────────────────────────────────
class DetectionConfig:
    CONFIDENCE    = float(os.getenv("CONFIDENCE", 0.4))  # ความมั่นใจขั้นต่ำ (0.0–1.0)
    IOU_THRESHOLD = 0.45              # Intersection over Union threshold
    IMG_SIZE      = 640               # ขนาดภาพที่ส่งให้ YOLO
    MAX_DETECTIONS = 10               # จำนวน detection สูงสุดต่อภาภ


# ── Hardware (Raspberry Pi) ────────────────────────────────
class HardwareConfig:
    # HX711 Load Cell GPIO Pins
    HX711_DOUT_PIN = int(os.getenv("HX711_DOUT", 5))   # GPIO5  (Pin 29)
    HX711_SCK_PIN  = int(os.getenv("HX711_SCK",  6))   # GPIO6  (Pin 31)
    HX711_SCALE    = float(os.getenv("HX711_SCALE", -227634.2))  # ค่า calibration
    HX711_READINGS = 5                # จำนวนครั้งที่อ่านเพื่อเฉลี่ย

    # Camera
    CAMERA_RESOLUTION = (1920, 1080)  # ความละเอียดภาพ
    CAMERA_FORMAT     = "JPEG"


# ── File Cleanup ───────────────────────────────────────────
class CleanupConfig:
    KEEP_DAYS = 7          # เก็บไฟล์ใน uploads/ กี่วัน
    LOG_MAX_BYTES  = 10 * 1024 * 1024   # 10 MB
    LOG_BACKUP_COUNT = 3               # เก็บ log backup กี่ไฟล์


# ── Allowed File Types ─────────────────────────────────────
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
