"""
detector.py
─────────────────────────────────────────────────────────
Logic การตรวจจับอาหารด้วย YOLOv8

โหมดการทำงาน:
  YOLO mode เท่านั้น — ต้องติดตั้ง ultralytics และมี models/best.pt

หมายเหตุ:
  ใช้ Pillow วาดข้อความภาษาไทยบน bounding box
  เพราะ cv2.putText() ไม่รองรับ Unicode / ภาษาไทย

แก้ไขที่นี่เมื่อ:
  - ปรับ threshold หรือ post-processing
  - เปลี่ยนขนาด / สี label
  - เพิ่ม preprocessing ภาพ
─────────────────────────────────────────────────────────
"""

import logging
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from ultralytics import YOLO

from config import MODEL_PATH, UPLOAD_DIR, DetectionConfig, MENU_PATH, MENU_INGREDIENTS_PATH
from utils import load_menu

logger = logging.getLogger(__name__)

# ── สีของ bounding box (RGB สำหรับ Pillow) ────────────────
BOX_COLORS_RGB = [
    (0, 229, 160),  # เขียว
    (0, 153, 255),  # น้ำเงิน
    (255, 107, 53),  # ส้ม
    (176, 106, 255),  # ม่วง
    (255, 210, 63),  # เหลือง
    (53, 211, 255),  # ฟ้า
]

# ── ฟอนต์ภาษาไทย ──────────────────────────────────────────
_FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/tlwg/Loma.otf",
    "/usr/share/fonts/truetype/tlwg/Loma.ttf",
    "/usr/share/fonts/opentype/tlwg/Garuda.otf",
    "/usr/share/fonts/truetype/thai/Garuda.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/Library/Fonts/Thonburi.ttf",
    "/System/Library/Fonts/Supplemental/Ayuthaya.ttf",
    "C:/Windows/Fonts/tahoma.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


def _find_thai_font(size: int = 18) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            try:
                logger.debug("Using font: %s", path)
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    logger.warning("No Thai font found — using PIL default (Thai may not display)")
    return ImageFont.load_default()


class FoodDetector:
    """ตรวจจับอาหารจากภาพด้วย YOLOv8"""

    def __init__(self):
        self.menu = load_menu(MENU_PATH)
        self.menu_ingredients = load_menu(MENU_INGREDIENTS_PATH)
        self.model = self._load_model()
        self._is_pi = self._detect_raspberry_pi()
        self._font_label = _find_thai_font(size=22)
        self._font_small = _find_thai_font(size=14)
        logger.info(
            "FoodDetector ready | pi=%s | model=%s",
            self._is_pi,
            "loaded" if self.model else "NOT FOUND",
        )

    # ── Initialisation ─────────────────────────────────────

    def _load_model(self) -> YOLO | None:
        try:
            if not MODEL_PATH.exists():
                logger.error("Model file NOT FOUND at %s", MODEL_PATH)
                return None
            model = YOLO(str(MODEL_PATH))
            logger.info("YOLOv8 loaded: %s", MODEL_PATH)
            return model
        except Exception as e:
            logger.error("Failed to load YOLO model: %s", e)
            return None

    def _detect_raspberry_pi(self) -> bool:
        try:
            return "raspberry" in Path("/proc/device-tree/model").read_text().lower()
        except Exception:
            return False

    # ── Public API ─────────────────────────────────────────

    def get_status(self) -> dict:
        return {
            "model_loaded": self.model is not None,
            "is_raspberry_pi": self._is_pi,
            "platform": "Raspberry Pi 5" if self._is_pi else "Development PC",
            "mode": "yolo",
        }

    def detect(self, image_path: str) -> dict:
        if not Path(image_path).exists():
            return {"success": False, "error": f"Image not found: {image_path}"}
        if self.model is None:
            return {"success": False, "error": "Model not initialized"}
        return self._detect_yolo(image_path)

    def _match_menu(self, detected_classes: list[str]) -> dict:
        detected_set = set(detected_classes)
        best_match = None
        best_score = -1

        for class_name, item in self.menu.items():
            if not isinstance(item, dict) or not item.get("is_main"):
                continue
            if class_name not in detected_set:
                continue

            if "menus" in item:
                for sub in item["menus"]:
                    ingredients = set(sub.get("ingredients", []))
                    score = len(ingredients & detected_set)
                    if score > best_score:
                        best_score = score
                        best_match = {
                            "class_name": class_name,
                            "name_th": sub["name_th"],
                            "name_en": sub["name_en"],
                            "price": sub["price"],
                            "ingredients": sub.get("ingredients", []),
                            "score": score,
                        }
            else:
                ingredients = set(item.get("ingredients", []))
                score = len(ingredients & detected_set) if ingredients else 1
                if score > best_score:
                    best_score = score
                    best_match = {
                        "class_name": class_name,
                        "name_th": item["name_th"],
                        "name_en": item["name_en"],
                        "price": item["price"],
                        "ingredients": item.get("ingredients", []),
                        "score": score,
                    }

        return best_match

    def _build_menu_result(self, detections: list[dict]) -> list[dict]:
        """
        จับคู่เมนูโดยใช้ menu_ingredients.json
        รองรับ min_match, required_ingredients, bonus_ingredients
        """
        detected_set = set(d["name"] for d in detections)
        results = []
        used_main = set()

        candidates = []
        for menu in self.menu_ingredients.get("menus", []):
            main = set(menu.get("main_ingredients", []))
            required = set(menu.get("required_ingredients", []))
            bonus = set(menu.get("bonus_ingredients", []))
            min_match = menu.get("min_match", 1)

            main_matched = main & detected_set
            if len(main_matched) < min_match:
                continue

            if required and not required.issubset(detected_set):
                continue

            score = len(main_matched) + len(bonus & detected_set)
            candidates.append((score, menu))

        candidates.sort(key=lambda x: x[0], reverse=True)

        for score, menu in candidates:
            main_matched = set(menu.get("main_ingredients", [])) & detected_set

            if main_matched & used_main:
                continue

            # ── ดึงราคาจาก menu.json โดยหา key ตรงๆ ก่อน ──
            price = 0
            direct = self.menu.get(menu["key"])
            if isinstance(direct, dict):
                price = direct.get("price", 0)
            if not price:
                for m in self.menu.values():
                    if not isinstance(m, dict):
                        continue
                    if "menus" in m:
                        for sub in m["menus"]:
                            if sub.get("name_en") == menu.get("name_en"):
                                price = sub.get("price", 0)
                                break
                    elif m.get("name_en") == menu.get("name_en"):
                        price = m.get("price", 0)
                    if price:
                        break

            results.append({
                "name": menu["key"],
                "name_th": menu["name_th"],
                "name_en": menu["name_en"],
                "price": price,
                "confidence": max(
                    (d["confidence"] for d in detections if d["name"] in main_matched),
                    default=0,
                ),
                "ingredients": [
                    {
                        "name": d["name"],
                        "name_th": self.menu.get(d["name"], {}).get("name_th", d["name"]),
                        "confidence": d["confidence"],
                        "bbox": d["bbox"],
                    }
                    for d in detections
                    if d["name"] in set(menu.get("ingredients", []))
                ],
            })
            used_main.update(main_matched)

        return results

    # ── YOLO Detection ─────────────────────────────────────

    def _detect_yolo(self, image_path: str) -> dict:
        try:
            results = self.model.predict(
                image_path,
                conf=DetectionConfig.CONFIDENCE,
                iou=DetectionConfig.IOU_THRESHOLD,
                imgsz=DetectionConfig.IMG_SIZE,
                max_det=DetectionConfig.MAX_DETECTIONS,
                device="cpu",
            )[0]

            pil_img = Image.open(image_path).convert("RGB")
            detections = []

            for i, box in enumerate(results.boxes):
                cls_id = int(box.cls[0])
                conf = float(box.conf[0])
                label_en = results.names[cls_id]
                b = box.xyxy[0].cpu().numpy()

                item = self.menu.get(label_en, self.menu.get("unknown", {}))
                det = {
                    "name": label_en,
                    "name_th": item.get("name_th", label_en),
                    "name_en": item.get("name_en", label_en),
                    "confidence": round(conf, 2),
                    "price": item.get("price", 0),
                    "weight": 0.0,
                    "bbox": {
                        "x1": int(b[0]),
                        "y1": int(b[1]),
                        "x2": int(b[2]),
                        "y2": int(b[3]),
                    },
                }
                detections.append(det)
                self._draw_box_pil(pil_img, det, i)

            annotated_path = self._save_annotated_pil(pil_img, image_path)

            menu_results = self._build_menu_result(detections)
            total_price = sum(m["price"] for m in menu_results) if menu_results else sum(d["price"] for d in detections)

            out = {
                "success": True,
                "detections": detections,
                "total_price": total_price,
                "annotated_path": annotated_path,
                "count": len(detections),
                "mock": False,
                "matched_menus": menu_results,
                "menus": menu_results,
            }
            return out

        except Exception as exc:
            logger.exception("YOLO detection error")
            return {"success": False, "error": str(exc)}

    # ── Menu hierarchy (ไม่ใช้แล้ว — เก็บไว้ reference) ────

    @staticmethod
    def _bbox_area(b: dict) -> float:
        w = max(0, b.get("x2", 0) - b.get("x1", 0))
        h = max(0, b.get("y2", 0) - b.get("y1", 0))
        return w * h

    @staticmethod
    def _bbox_center(b: dict) -> tuple[float, float]:
        return (
            (b.get("x1", 0) + b.get("x2", 0)) / 2,
            (b.get("y1", 0) + b.get("y2", 0)) / 2,
        )

    @classmethod
    def _build_menus_hierarchy(cls, detections: list[dict]) -> list[dict]:
        if not detections:
            return []

        def contains(outer: dict, inner: dict) -> bool:
            ob = outer.get("bbox") or {}
            ib = inner.get("bbox") or {}
            cx, cy = cls._bbox_center(ib)
            x1, y1 = ob.get("x1", 0), ob.get("y1", 0)
            x2, y2 = ob.get("x2", 0), ob.get("y2", 0)
            if x1 >= x2 or y1 >= y2:
                return False
            return x1 <= cx <= x2 and y1 <= cy <= y2

        areas = [cls._bbox_area(d.get("bbox") or {}) for d in detections]
        parent_idx = [None] * len(detections)

        for i, det in enumerate(detections):
            candidates = [
                j
                for j in range(len(detections))
                if j != i and areas[j] > areas[i] and contains(detections[j], det)
            ]
            if candidates:
                parent_idx[i] = min(candidates, key=lambda j: areas[j])

        root_indices = [i for i in range(len(detections)) if parent_idx[i] is None]
        root_indices.sort(
            key=lambda i: (
                (detections[i].get("bbox") or {}).get("y1", 0),
                (detections[i].get("bbox") or {}).get("x1", 0),
            )
        )

        menus = []
        for ri in root_indices:
            det = detections[ri]
            children = [j for j in range(len(detections)) if parent_idx[j] == ri]
            confs = [det.get("confidence", 0)] + [
                detections[j].get("confidence", 0) for j in children
            ]
            menus.append(
                {
                    "name": det.get("name", ""),
                    "name_th": det.get("name_th", det.get("name", "")),
                    "name_en": det.get("name_en", ""),
                    "confidence": det.get("confidence", 0),
                    "accuracy_avg": round(sum(confs) / len(confs), 3),
                    "price": det.get("price", 0),
                    "weight": det.get("weight", 0.0),
                    "ingredients": [
                        {
                            "name": detections[j].get("name", ""),
                            "name_th": detections[j].get("name_th", ""),
                            "name_en": detections[j].get("name_en", ""),
                            "confidence": detections[j].get("confidence", 0),
                            "price": 0,
                        }
                        for j in children
                    ],
                }
            )
        return menus

    # ── Drawing ─────────────────────────────────────────────

    def _draw_box_pil(self, img: Image.Image, det: dict, idx: int) -> None:
        color = BOX_COLORS_RGB[idx % len(BOX_COLORS_RGB)]
        b = det["bbox"]
        draw = ImageDraw.Draw(img)

        draw.rectangle(
            [b["x1"], b["y1"], b["x2"], b["y2"]],
            outline=color,
            width=5,
        )

        label_text = (
            f"{det['name_th']} {int(det['confidence'] * 100)}%  ฿{det['price']}"
        )
        text_bbox = draw.textbbox((b["x1"], b["y1"]), label_text, font=self._font_label)
        tw = text_bbox[2] - text_bbox[0]
        th = text_bbox[3] - text_bbox[1]

        draw.rectangle(
            [b["x1"], b["y1"] - th - 10, b["x1"] + tw + 10, b["y1"]],
            fill=color,
        )
        draw.text(
            (b["x1"] + 5, b["y1"] - th - 5),
            label_text,
            font=self._font_label,
            fill=(255, 255, 255),
        )

    @staticmethod
    def _save_annotated_pil(img: Image.Image, original_path: str) -> str:
        p = Path(original_path)
        out = p.parent / f"annotated_{p.stem}.jpg"
        img.save(str(out), "JPEG", quality=95)
        return str(out)
