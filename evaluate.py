import sys
import sqlite3
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
    print("ติดตั้งด้วย: pip install matplotlib seaborn scikit-learn ultralytics")
    sys.exit(1)

# ── Paths ──────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent

# พยายามโหลดจาก config ถ้ามี ถ้าไม่มีใช้ค่าเริ่มต้น
try:
    from config import MODEL_PATH
except ImportError:
    MODEL_PATH = BASE_DIR / "models" / "best.pt"

# ชี้ไปที่ฐานข้อมูลของคุณตรงๆ
TARGET_DB_PATH = Path("/home/saranchai-6519410040/Desktop/food-detection-upgraded/database/food_detection.db")

RESULTS_DIR = BASE_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# raw YOLO class
CLASS_LABELS = [
    "boiled_chicken", "boiled_chicken_blood_jelly", "boiled_egg",
    "boiled_vegetables", "chainese_sausage", "chicken_drumstick",
    "chicken_rice", "chicken_shredded", "crispy_pork", "cucumber",
    "daikon_radish", "fried_chicken", "fried_tofo", "grilled_chicken",
    "grilled_chicken_with_rice", "minced_pork", "noodle", "pickled_ginger",
    "red_pork", "red_pork_and_crispy_pork", "rice", "roast_duck",
    "roaste_duck_rice", "stir_fried_basil",
]

# ── Database ───────────────────────────────────────────────
EVAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS evaluation_results (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    image_path        TEXT    NOT NULL,
    actual_class      TEXT    NOT NULL,
    predicted_class   TEXT    NOT NULL DEFAULT '',
    actual_menu       TEXT    NOT NULL DEFAULT '',
    predicted_menu    TEXT    NOT NULL DEFAULT '',
    confidence        REAL    NOT NULL DEFAULT 0.0,
    is_correct_class  INTEGER NOT NULL DEFAULT 0,
    is_correct_menu   INTEGER NOT NULL DEFAULT 0,
    session_tag       TEXT,
    created_at        TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""

def init_eval_db():
    conn = sqlite3.connect(TARGET_DB_PATH)
    conn.executescript(EVAL_SCHEMA)
    conn.commit()
    conn.close()

def save_eval_result(image_path, actual_class, predicted_class,
                     actual_menu, predicted_menu, confidence, session_tag=""):
    conn = sqlite3.connect(TARGET_DB_PATH)
    conn.execute(
        """INSERT INTO evaluation_results
           (image_path, actual_class, predicted_class,
            actual_menu, predicted_menu, confidence,
            is_correct_class, is_correct_menu, session_tag)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            str(image_path), actual_class, predicted_class,
            actual_menu, predicted_menu, round(confidence, 4),
            int(actual_class == predicted_class), int(actual_menu == predicted_menu),
            session_tag,
        )
    )
    conn.commit()
    conn.close()

def load_eval_results(session_tag=None):
    conn = sqlite3.connect(TARGET_DB_PATH)
    q = """SELECT actual_class, predicted_class, actual_menu, predicted_menu
           FROM evaluation_results"""
    rows = conn.execute(
        q + (" WHERE session_tag=?" if session_tag else ""),
        (session_tag,) if session_tag else ()
    ).fetchall()
    conn.close()
    return rows

# ── Model ──────────────────────────────────────────────────
def predict_all(model, image_path: Path):
    results = model.predict(
        str(image_path), conf=0.25, iou=0.45,
        imgsz=640, device="cpu", verbose=False,
    )[0]

    if len(results.boxes) == 0:
        return [], "no_detection", "", 0.0

    detections = sorted(
        [(results.names[int(b.cls[0])], round(float(b.conf[0]), 2))
         for b in results.boxes],
        key=lambda x: x[1], reverse=True,
    )
    detected_classes = [d[0] for d in detections]
    predicted_top    = detected_classes[0]
    top_conf         = detections[0][1]
    return detections, predicted_top, "", top_conf

# ── Plotting ───────────────────────────────────────────────
def plot_cm(actuals, predicteds, title: str, filename: str):
    used = sorted(set(actuals) | set(predicteds))
    cm = confusion_matrix(actuals, predicteds, labels=used)
    total = len(actuals)
    correct = sum(a == p for a, p in zip(actuals, predicteds))
    acc = correct / total * 100 if total else 0

    size = max(10, len(used))
    fig, ax = plt.subplots(figsize=(size, max(8, size - 2)))
    sns.heatmap(cm, annot=True, fmt="d", cmap="Blues",
                xticklabels=used, yticklabels=used,
                ax=ax, linewidths=0.5)
    ax.set_title(f"{title}\nAccuracy: {acc:.1f}%  ({correct}/{total})", fontsize=13, pad=15)
    ax.set_ylabel("Actual", fontsize=11)
    ax.set_xlabel("Predicted", fontsize=11)
    plt.xticks(rotation=45, ha="right", fontsize=8)
    plt.yticks(rotation=0, fontsize=8)
    plt.tight_layout()

    out = RESULTS_DIR / filename
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"✅ Saved → {out}")

def save_report(actuals, predicteds, title: str, filename: str):
    used = sorted(set(actuals) | set(predicteds))
    report = classification_report(actuals, predicteds, labels=used, zero_division=0)
    out = RESULTS_DIR / filename
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"=== {title} ===\n")
        f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(report)
    print(f"✅ Saved → {out}")

def generate_outputs(ac, pc, am, pm, session_tag=""):
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    tag = f" [{session_tag}]" if session_tag else ""

    print("\n" + "═"*50)
    print("📊  Confusion Matrix — ระดับ Class (Raw YOLO)")
    print("═"*50)
    plot_cm(ac, pc, f"Confusion Matrix — Class Level{tag}", f"confusion_matrix_class_{ts}.png")
    save_report(ac, pc, f"Classification Report — Class Level{tag}", f"classification_report_class_{ts}.txt")

def print_summary(ac, pc, am, pm):
    tc = len(ac); cc = sum(a == p for a, p in zip(ac, pc))
    print(f"\n{'═'*50}")
    print(f"  Class level : {cc}/{tc} ถูก ({cc/tc*100:.1f}%)" if tc else "  Class level : -")
    wrong_c = [(a, p) for a, p in zip(ac, pc) if a != p]
    if wrong_c:
        print("\n  ❌ Class ผิด:")
        for a, p in wrong_c:
            print(f"     actual={a}  →  predicted={p}")
    print("═"*50)

# ── Mode 1: DB Auto ────────────────────────────────────────
def run_db_groundtruth_session():
    print("\n" + "═"*50)
    print("  Evaluate — 🚀 Auto from Application Database")
    print("═"*50)

    if not Path(MODEL_PATH).exists():
        print(f"[ERROR] ไม่พบ model: {MODEL_PATH}")
        sys.exit(1)

    print("\nโหลด model ...")
    model = YOLO(str(MODEL_PATH))
    print("Model พร้อมใช้งาน\n")

    if not TARGET_DB_PATH.exists():
        print(f"[ERROR] ไม่พบไฟล์ Database ที่: {TARGET_DB_PATH}")
        return

    print(f"เชื่อมต่อฐานข้อมูล: {TARGET_DB_PATH.name}...")
    conn = sqlite3.connect(TARGET_DB_PATH)
    
    query = """
        SELECT s.image_path, i.food_name 
        FROM detection_sessions s
        JOIN detection_items i ON s.id = i.session_id
        WHERE s.image_path IS NOT NULL
    """
    try:
        records = conn.execute(query).fetchall()
    except sqlite3.OperationalError as e:
        print(f"[ERROR] โครงสร้างตารางอาจไม่ถูกต้อง: {e}")
        conn.close()
        return
    conn.close()

    if not records:
        print("[ERROR] ไม่พบข้อมูลประวัติในฐานข้อมูลระบบ (ตาราง detection_sessions/items)")
        return

    print(f"✅ พบข้อมูลใน DB ทั้งหมด {len(records)} รายการ\n")
    session_tag = input("ชื่อ session สำหรับบันทึกผล (Enter เพื่อข้าม): ").strip()
    
    # โปรเจกต์ Root อ้างอิงจาก Path เครื่องคุณ
    project_root = Path("/home/saranchai-6519410040/Desktop/food-detection-upgraded")
    
    ac, pc, am, pm = [], [], [], []
    buffer = []

    for idx, (img_filename, actual_class) in enumerate(records, 1):
        # ลบ Path เดิมทิ้งในกรณีที่ใน DB บันทึกไว้เต็มรูปแบบ เพื่อค้นหาเฉพาะชื่อไฟล์
        just_filename = Path(img_filename).name 

        possible_paths = [
            project_root / just_filename,
            project_root / "uploads" / just_filename,
            project_root / "confirmed" / just_filename,
            project_root / "database" / just_filename,
        ]
        
        img_path = None
        for p in possible_paths:
            if p.exists():
                img_path = p
                break
                
        if not img_path:
            print(f"[{idx}/{len(records)}] ⚠️ ข้าม: หาไฟล์รูปไม่พบ -> {just_filename}")
            continue

        print(f"\n{'─'*40}")
        print(f"[{idx}/{len(records)}]  {img_path.name}")

        detections, pred_class, pred_menu, top_conf = predict_all(model, img_path)

        if detections:
            print("  Model เจอ:")
            for cls, conf in detections:
                print(f"    • {cls}  ({conf:.0%})")
        else:
            print("  Model ไม่เจออะไรเลย")

        if actual_class not in CLASS_LABELS:
            print(f"  ⚠️ ข้าม: คลาส '{actual_class}' ไม่มีในระบบโมเดลปัจจุบัน")
            continue

        class_ok = "✅" if actual_class == pred_class else "❌"
        print(f"  Class: {class_ok}  actual={actual_class}  predicted={pred_class}")

        ac.append(actual_class); pc.append(pred_class)
        am.append(""); pm.append("")
        buffer.append((img_path, actual_class, pred_class, "", "", top_conf))

    if not ac:
        print("\nไม่มีข้อมูลที่สมบูรณ์พอให้ประเมินผล (อาจจะหาไฟล์รูปไม่เจอเลย)")
        return

    print_summary(ac, pc, am, pm)
    
    init_eval_db()
    for row in buffer:
        save_eval_result(*row, session_tag)
    print(f"\n✅ บันทึก {len(buffer)} ผลลัพธ์ลงตาราง evaluation_results แล้ว")
    
    generate_outputs(ac, pc, am, pm, session_tag)

# ── Mode 2: from DB ────────────────────────────────────────
def generate_from_db():
    init_eval_db()
    session_tag = input("session tag (Enter = ทั้งหมด): ").strip() or None
    rows = load_eval_results(session_tag)
    if not rows:
        print("[ERROR] ไม่มีข้อมูลใน database")
        return

    ac = [r[0] for r in rows]
    pc = [r[1] for r in rows]
    am = [r[2] for r in rows]
    pm = [r[3] for r in rows]
    print(f"พบข้อมูล {len(rows)} รายการ")
    print_summary(ac, pc, am, pm)
    generate_outputs(ac, pc, am, pm, session_tag or "")

# ── Entry point ────────────────────────────────────────────
if __name__ == "__main__":
    print("\n🍽️  Food Detection — Evaluate Tool")
    print("─"*50)
    print("1. ดึงเฉลยจาก Database (food_detection.db) มาเทสต์ออโต้ 🚀")
    print("2. สร้าง matrix จากผลที่บันทึกไว้ใน DB (evaluation_results)")
    mode = input("\nเลือก (1/2): ").strip()
    
    if mode == "1":
        run_db_groundtruth_session()
    elif mode == "2":
        generate_from_db()
    else:
        print("ออกโปรแกรม")
