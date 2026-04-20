import logging
import uuid
import os
import subprocess
import shutil
import threading
import time
from config import UPLOAD_DIR

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

    def get_frame(self) -> bytes | None:
        with self._lock:
            return self._frame

    def capture(self) -> str | None:
        try:
            filename = f"capture_{uuid.uuid4().hex}.jpg"
            path = str(UPLOAD_DIR / filename)
            with self._lock:
                if self._frame:
                    with open(path, "wb") as f:
                        f.write(self._frame)
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
