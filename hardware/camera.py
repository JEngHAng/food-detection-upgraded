import logging
import uuid
import os
import subprocess
import shutil
import threading
import time
import io
from PIL import Image
from config import UPLOAD_DIR

ROTATE_ANGLE = 90  # ← แก้ตรงนี้เพื่อเปลี่ยนองศา (90, 180, 270)

logger = logging.getLogger(__name__)

FRAME_PATH = "/dev/shm/live.jpg"

class PiCamera:
    def __init__(self):
        os.system("sudo pkill -9 rpicam-vid 2>/dev/null")
        os.system("sudo pkill -9 rpicam-still 2>/dev/null")
        time.sleep(0.5)

        UPLOAD_DIR.mkdir(exist_ok=True)

        self._lock = threading.Lock()
        self._frame = None
        self._running = True

        self._proc = subprocess.Popen([
            "rpicam-vid",
            "-t", "0",
            "--width", "1280",
            "--height", "720",
            "--framerate", "30",
            "--codec", "mjpeg",
            "--quality", "95",
            "--sharpness", "2.0",
            "--flush",
            "--output", "-",       # output ออก stdout
            "--nopreview",
        ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

        # รอเฟรมแรก
        for _ in range(20):
            if self._frame:
                break
            time.sleep(0.3)

        logger.info("✅ PiCamera MJPEG stream ready")

    def _read_loop(self):
        """อ่าน MJPEG stream จาก stdout แยก frame ด้วย JPEG marker"""
        buf = b""
        SOI = b"\xff\xd8"  # JPEG start
        EOI = b"\xff\xd9"  # JPEG end

        while self._running:
            try:
                chunk = self._proc.stdout.read(4096)
                if not chunk:
                    break
                buf += chunk

                while True:
                    start = buf.find(SOI)
                    end = buf.find(EOI, start + 2)
                    if start == -1 or end == -1:
                        break
                    frame = buf[start:end + 2]
                    buf = buf[end + 2:]
                    with self._lock:
                        self._frame = frame

            except Exception as e:
                logger.debug(f"Read loop error: {e}")
                break

    def _rotate(self, jpeg_bytes: bytes) -> bytes:
        """หมุน JPEG bytes ตาม ROTATE_ANGLE แล้วคืน bytes ใหม่"""
        if not ROTATE_ANGLE:
            return jpeg_bytes
        try:
            img = Image.open(io.BytesIO(jpeg_bytes))
            img = img.rotate(-ROTATE_ANGLE, expand=True)  # ลบ = หมุนตามเข็ม
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=95)
            return buf.getvalue()
        except Exception:
            return jpeg_bytes  # ถ้าพัง ส่ง frame เดิม

    def get_frame(self) -> bytes | None:
        with self._lock:
            frame = self._frame
        if frame is None:
            return None
        return self._rotate(frame)

    def capture(self) -> str | None:
        try:
            filename = f"capture_{uuid.uuid4().hex}.jpg"
            path = str(UPLOAD_DIR / filename)
            with self._lock:
                if self._frame:
                    rotated = self._rotate(self._frame)
                    with open(path, "wb") as f:
                        f.write(rotated)
                    logger.info(f"📸 บันทึกภาพสำเร็จ: {filename}")
                    return path
            return None
        except Exception as exc:
            logger.error(f"Capture failed: {exc}")
            return None

    def __del__(self):
        self._running = False
        if hasattr(self, "_proc"):
            self._proc.terminate()
