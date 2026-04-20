# load_menu, cleanup, logging

"""
utils.py
─────────────────────────────────────────────────────────
ฟังก์ชันช่วยเหลือที่ใช้ร่วมกันทั่วโปรเจค

- load_menu()        : โหลด menu.json
- allowed_file()     : ตรวจสอบนามสกุลไฟล์
- cleanup_old_files(): ลบไฟล์เก่าใน uploads/
- setup_logging()    : ตั้งค่า logger พร้อม rotation
─────────────────────────────────────────────────────────
"""

import json
import logging
import logging.handlers
import os
import time
from pathlib import Path

from config import ALLOWED_EXTENSIONS, CleanupConfig, LOG_DIR


# ── Menu Loader ────────────────────────────────────────────

def load_menu(menu_path: Path) -> dict:
    """
    โหลด menu.json คืน dict ของเมนูทั้งหมด
    ถ้าไฟล์ไม่มีหรืออ่านไม่ได้ คืน dict เปล่า
    """
    try:
        with open(menu_path, encoding="utf-8") as f:
            data = json.load(f)
        # กรอง key ที่ขึ้นต้นด้วย _ (comment keys)
        return {k: v for k, v in data.items() if not k.startswith("_")}
    except FileNotFoundError:
        logging.warning("menu.json not found at %s", menu_path)
        return {}
    except json.JSONDecodeError as exc:
        logging.error("menu.json parse error: %s", exc)
        return {}


# ── File Validation ────────────────────────────────────────

def allowed_file(filename: str) -> bool:
    """
    ตรวจสอบว่านามสกุลไฟล์อยู่ใน whitelist หรือไม่

    Example:
        allowed_file("food.jpg")  → True
        allowed_file("virus.exe") → False
    """
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


# ── File Cleanup ───────────────────────────────────────────

def cleanup_old_files(directory: Path, keep_days: int = None) -> int:
    """
    ลบไฟล์ที่เก่ากว่า keep_days วัน ในโฟลเดอร์ที่กำหนด

    Args:
        directory : โฟลเดอร์ที่ต้องการล้าง (เช่น uploads/)
        keep_days : จำนวนวันที่เก็บไว้ (default จาก CleanupConfig)

    Returns:
        จำนวนไฟล์ที่ถูกลบ
    """
    if keep_days is None:
        keep_days = CleanupConfig.KEEP_DAYS

    cutoff  = time.time() - (keep_days * 86400)  # แปลงเป็น epoch seconds
    deleted = 0

    if not directory.exists():
        return 0

    for file_path in directory.iterdir():
        if not file_path.is_file():
            continue
        try:
            if file_path.stat().st_mtime < cutoff:
                file_path.unlink()
                deleted += 1
        except Exception as exc:
            logging.warning("Cannot delete %s: %s", file_path, exc)

    if deleted:
        logging.info("Cleanup: deleted %d old files from %s", deleted, directory)
    return deleted


# ── Logging Setup ──────────────────────────────────────────

def setup_logging(app_name: str = "food_ai") -> None:
    """
    ตั้งค่า logging ให้บันทึกลง console และไฟล์
    พร้อม RotatingFileHandler ป้องกัน log ใหญ่เกินไป
    """
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(log_format, date_format))

    # File handler พร้อม rotation
    log_file = LOG_DIR / f"{app_name}.log"
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=CleanupConfig.LOG_MAX_BYTES,
        backupCount=CleanupConfig.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(log_format, date_format))

    # ใช้กับ root logger
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(console)
    root.addHandler(file_handler)