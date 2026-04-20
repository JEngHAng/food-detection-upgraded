"""
hardware/loadcell.py
─────────────────────────────────────────────────────────
HX711 Load Cell wrapper สำหรับ Raspberry Pi
ใช้ logic จาก test_loadcell.py:
  - IQR outlier filter
  - Boundary / overflow detection
  - Persistent zero_raw + scale_factor (calibrated)
  - Singleton HX711 instance (ไม่สร้างใหม่ทุกครั้ง)

โหมดการทำงาน:
  - บน Pi ที่มี RPi.GPIO + hx711 → อ่านน้ำหนักจริง
  - บน PC / ไม่มี library        → จำลองค่าด้วย mock mode

วงจร HX711 → RPi GPIO:
  DT   → GPIO5 (Pin 29)  ← เปลี่ยนได้ใน config.py / .env
  SCK  → GPIO6 (Pin 31)
─────────────────────────────────────────────────────────
"""

import logging
import statistics
import time
import os

from config import HardwareConfig

logger = logging.getLogger(__name__)

try:
    from hx711 import HX711
    _HAS_HX711 = True
except ImportError:
    _HAS_HX711 = False
    logger.info("HX711 not available — running in mock mode")

# ค่า ADC boundary ของ HX711 24-bit (overflow/underflow)
_BOUNDARIES = {32767, 524287, 262143, -32768, -524288, -262144}
_READ_DELAY = float(os.getenv("HX711_READ_DELAY", "0.05"))


def _is_boundary(val: float) -> bool:
    return round(val) in _BOUNDARIES


def _read_raw_mean(hx, n: int = 10) -> tuple:
    """
    อ่าน n รอบ กรอง boundary + IQR outlier คืน (mean|None, valid_count, boundary_count)
    """
    raw_all = []
    boundary_count = 0

    for _ in range(n):
        try:
            data = hx.get_raw_data()
            if data is not False and data:
                for v in data:
                    if _is_boundary(v):
                        boundary_count += 1
                    else:
                        raw_all.append(v)
        except Exception as exc:
            logger.debug("HX711 read error: %s", exc)
        time.sleep(_READ_DELAY)

    if not raw_all:
        return None, 0, boundary_count

    if len(raw_all) >= 6:
        s = sorted(raw_all)
        q1, q3 = s[len(s) // 4], s[3 * len(s) // 4]
        iqr = q3 - q1
        filtered = [x for x in raw_all if q1 - 1.5 * iqr <= x <= q3 + 1.5 * iqr]
        if filtered:
            raw_all = filtered

    return statistics.mean(raw_all), len(raw_all), boundary_count


class LoadCell:
    """
    Singleton-style HX711 wrapper พร้อม IQR filter และ tare/calibrate
    """

    def __init__(self):
        self._hx = None
        self._zero_raw = float(os.getenv("LOADCELL_ZERO_RAW", "0"))
        self._scale = float(os.getenv("LOADCELL_SCALE_FACTOR", str(HardwareConfig.HX711_SCALE)))
        self._readings = HardwareConfig.HX711_READINGS
        self._ready = False
        self._init_hardware()

    def _init_hardware(self) -> None:
        if not _HAS_HX711:
            return
        try:
            self._hx = HX711(
                dout_pin=HardwareConfig.HX711_DOUT_PIN,
                pd_sck_pin=HardwareConfig.HX711_SCK_PIN,
            )
            self._hx.reset()
            time.sleep(0.5)
            self._ready = True
            logger.info(
                "HX711 ready DT=%d SCK=%d scale=%.4f zero=%.1f",
                HardwareConfig.HX711_DOUT_PIN, HardwareConfig.HX711_SCK_PIN,
                self._scale, self._zero_raw,
            )
        except Exception as exc:
            logger.error("HX711 init failed: %s", exc)
            self._ready = False

    def _raw_to_grams(self, raw: float) -> float:
        if self._scale == 0:
            return 0.0
        return (raw - self._zero_raw) / self._scale

    @property
    def is_available(self) -> bool:
        return self._ready

    def read_grams(self) -> float:
        """อ่านน้ำหนัก (กรัม) คืน 0.0 ถ้าไม่มี hardware"""
        if not self._ready or self._hx is None:
            return 0.0
        mean_raw, _, b_count = _read_raw_mean(self._hx, n=self._readings)
        if b_count:
            logger.debug("Boundary skipped: %d", b_count)
        if mean_raw is None:
            return 0.0
        return round(max(self._raw_to_grams(mean_raw), 0.0), 1)

    def read_detail(self) -> dict:
        """อ่านน้ำหนักพร้อม metadata สำหรับ SSE stream"""
        if not self._ready or self._hx is None:
            return {"weight_g": 0.0, "raw": 0, "valid_count": 0,
                    "boundary_count": 0, "stable": True, "mock": True}

        mean_raw, valid, b_count = _read_raw_mean(self._hx, n=self._readings)
        if mean_raw is None:
            return {"weight_g": 0.0, "raw": 0, "valid_count": valid,
                    "boundary_count": b_count, "stable": False, "mock": False}

        grams = round(max(self._raw_to_grams(mean_raw), 0.0), 1)
        return {"weight_g": grams, "raw": int(mean_raw),
                "valid_count": valid, "boundary_count": b_count,
                "stable": b_count == 0, "mock": False}

    def tare(self) -> bool:
        """Tare: อ่าน 30 ครั้งแล้วบันทึกเป็น zero_raw"""
        if not self._ready or self._hx is None:
            return False
        try:
            samples = []
            for _ in range(30):
                mean_raw, _, _ = _read_raw_mean(self._hx, n=3)
                if mean_raw is not None:
                    samples.append(mean_raw)
                time.sleep(0.05)
            if not samples:
                return False
            self._zero_raw = statistics.mean(samples)
            logger.info("Tared — zero_raw=%.1f", self._zero_raw)
            return True
        except Exception as exc:
            logger.error("Tare error: %s", exc)
            return False

    def set_calibration(self, zero_raw: float, scale_factor: float) -> None:
        """ตั้งค่า calibration (ค่าจาก test_loadcell.py)"""
        self._zero_raw = zero_raw
        self._scale = scale_factor
        logger.info("Calibration set: zero_raw=%.1f scale=%.4f", zero_raw, scale_factor)
