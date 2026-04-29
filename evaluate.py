import sys
import sqlite3
import logging
from pathlib import Path
from datetime import datetime

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import seaborn as sns
    from sklearn.metrics import confusion_matrix, classification_report
    from ultralytics import YOLO
except ImportError as e:
    print(f"[ERROR] ขาด library: {e}")
    sys.exit(1)

DB_PATH    = Path('/home/saranchai-6519410040/automatic-food-detection-ai/food_detection.db')
MODEL_PATH = Path('/home/saranchai-6519410040/Desktop/food-detection-upgraded/models/best.pt')
RESULTS_DIR = Path('/home/saranchai-6519410040/Desktop/food-detection-upgraded/results')
RESULTS_DIR.mkdir(exist_ok=True)

CLASS_NAMES = [
    "boiled_chicken", "boiled_chicken_blood_jelly", "boiled_egg",
    "boiled_vegetables", "chainese_sausage", "chicken_drumstick",
    "chicken_rice", "chicken_shredded", "crispy_pork", "cucumber",
    "daikon_radish", "fried_chicken", "fried_tofu", "grilled_chicken",
    "minced_pork", "noodle", "pickled_ginger", "red_pork",
    "red_pork_and_crispy_pork", "rice", "roast_duck",
    "roaste_duck_rice", "stir_fried_basil",
]

EVAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS evaluation_results (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    image_path   TEXT    NOT NULL,
    actual       TEXT    NOT NULL,
    predicted    TEXT    NOT NULL,
    confidence   REAL    NOT NULL DEFAULT 0.0,
    is_correct   INTEGER NOT NULL DEFAULT 0,
    session_tag  TEXT,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""

def init_eval_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(EVAL_SCHEMA)
    conn.commit()
    conn.close()

def save_eval_result(image_path, actual, predicted, confidence, session_tag=""):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO evaluation_results (image_path, actual, predicted, confidence, is_correct, session_tag) VALUES (?, ?, ?, ?, ?, ?)",
        (str(image_path), actual, predicted, round(confidence, 4), int(actual == predicted), session_tag),
    )
    conn.commit()
    conn.close()

def load_eval_results(session_tag=None):
    conn = sqlite3.connect(DB_PATH)
    if session_tag:
        rows = conn.execute(
            "SELECT actual, predicted FROM evaluation_results WHERE session_tag = ?", (session_tag,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT actual, predicted FROM evaluation_results"
        ).fetchall()
    conn.close()
    return rows

def predict_top1(model, image_path):
    results = model.predict(str(image_path), conf=0.25, iou=0.45, imgsz=640, device="cpu", verbose=False)[0]
    if len(results.boxes) == 0:
        return "no_detection", 0.0
    best_idx = int(results.boxes.conf.argmax())
    cls_id   = int(results.boxes.cls[best_idx])
    conf     = float(results.boxes.conf[best_idx])
    return results.names[cls_id], conf

def plot_confusion_matrix(actuals, predicteds, session_tag=""):
    used_classes = sorted(set(actuals) | set(predicteds))
    cm = confusion_matrix(actuals, predicteds, labels=used_classes)
    total   = len(actuals)
    correct = sum(a == p for a, p in zip(actuals, predicteds))
    accuracy = correct / total * 100 if total > 0 else 0

    fig, ax = plt.subplots(figsize=(max(10, len(used_classes)), max(8, len(used_classes) - 2)))
    sns.heatmap(cm, annot=True, fmt="d", cmap="Blues",
                xticklabels=used_classes, yticklabels=used_classes, ax=ax, linewidths=0.5)
    tag_text = f" [{session_tag}]" if session_tag else ""
    ax.set_title(f"Confusion Matrix - Real Food Test{tag_text}\nAccuracy: {accuracy:.1f}%  ({correct}/{total})", fontsize=14, pad=15)
    ax.set_ylabel("Actual", fontsize=12)
    ax.set_xlabel("Predicted", fontsize=12)
    plt.xticks(rotation=45, ha="right", fontsize=9)
    plt.yticks(rotation=0, fontsize=9)
    plt.tight_layout()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = RESULTS_DIR / f"confusion_matrix_{ts}.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\nConfusion matrix saved -> {out_path}")

def save_classification_report(actuals, predicteds, session_tag=""):
    used_classes = sorted(set(actuals) | set(predicteds))
    report = classification_report(actuals, predicteds, labels=used_classes, zero_division=0)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = RESULTS_DIR / f"classification_report_{ts}.txt"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"=== Classification Report ===\n")
        if session_tag:
            f.write(f"Session: {session_tag}\n")
        f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(report)
    print(f"Classification report saved -> {out_path}")
    print(f"\n{report}")

def pick_actual_label():
    print("\n-- เลือก Actual Label --")
    for i, name in enumerate(CLASS_NAMES, 1):
        print(f"  {i:2d}. {name}")
    print("   0. ข้ามรูปนี้")
    print("   q. จบการ test")
    while True:
        choice = input("เลือก (หมายเลข): ").strip()
        if choice.lower() == "q":
            return "quit"
        if choice == "0":
            return "skip"
        if choice.isdigit() and 1 <= int(choice) <= len(CLASS_NAMES):
            return CLASS_NAMES[int(choice) - 1]
        print("  กรุณาใส่หมายเลข 0 -", len(CLASS_NAMES))

def run_test_session():
    print("=" * 50)
    print("  Evaluate - Real Food Test")
    print("=" * 50)

    if not MODEL_PATH.exists():
        print(f"[ERROR] ไม่พบ model: {MODEL_PATH}")
        sys.exit(1)

    print(f"\nโหลด model ...")
    model = YOLO(str(MODEL_PATH))
    print("Model พร้อมใช้งาน\n")

    session_tag = input("ชื่อ session (เช่น test_001 หรือ Enter เพื่อข้าม): ").strip()

    folder_input = input("path โฟลเดอร์รูป (Enter = uploads/): ").strip()
    folder = Path(folder_input) if folder_input else Path('/home/saranchai-6519410040/Desktop/food-detection-upgraded/uploads')

    images = sorted(folder.glob("*.jpg")) + sorted(folder.glob("*.png"))
    if not images:
        print(f"[ERROR] ไม่พบรูปใน {folder}")
        sys.exit(1)

    print(f"\nพบ {len(images)} รูป\n")
    actuals, predicteds, buffer = [], [], []

    for idx, img_path in enumerate(images, 1):
        print(f"\n[{idx}/{len(images)}] {img_path.name}")
        predicted, conf = predict_top1(model, img_path)
        print(f"  Model ทำนาย: {predicted}  ({conf:.0%})")
        actual = pick_actual_label()
        if actual == "quit":
            break
        if actual == "skip":
            continue
        mark = "CORRECT" if actual == predicted else "WRONG"
        print(f"  [{mark}] actual={actual}  predicted={predicted}")
        actuals.append(actual)
        predicteds.append(predicted)
        buffer.append((img_path, actual, predicted, conf))

    if not actuals:
        print("\nไม่มีข้อมูลเพียงพอ")
        return

    init_eval_db()
    for img_path, actual, predicted, conf in buffer:
        save_eval_result(img_path, actual, predicted, conf, session_tag)
    print(f"\nบันทึก {len(actuals)} ผลลัพธ์ลง database แล้ว")

    plot_confusion_matrix(actuals, predicteds, session_tag)
    save_classification_report(actuals, predicteds, session_tag)

def generate_from_db():
    init_eval_db()
    rows = load_eval_results()
    if not rows:
        print("[ERROR] ยังไม่มีข้อมูลใน evaluation_results")
        return
    actuals    = [r[0] for r in rows]
    predicteds = [r[1] for r in rows]
    print(f"พบข้อมูล {len(rows)} รายการ")
    plot_confusion_matrix(actuals, predicteds)
    save_classification_report(actuals, predicteds)

if __name__ == "__main__":
    print("\n Food Detection - Evaluate Tool")
    print("1. เริ่ม test session ใหม่")
    print("2. สร้าง confusion matrix จากผลที่บันทึกไว้แล้ว")
    mode = input("\nเลือก (1/2): ").strip()
    if mode == "2":
        generate_from_db()
    else:
        run_test_session()
