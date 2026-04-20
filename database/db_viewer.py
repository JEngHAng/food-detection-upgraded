#!/usr/bin/env python3
"""
db_viewer.py
─────────────────────────────────────────────────────────
CLI tool ดูข้อมูลใน SQLite database

วิธีใช้:
  python db_viewer.py                   → แสดง 20 รายการล่าสุด
  python db_viewer.py --all             → แสดงทั้งหมด
  python db_viewer.py --id 5            → ดู session #5 แบบละเอียด
  python db_viewer.py --stats           → สรุปสถิติ
  python db_viewer.py --search ไก่      → ค้นหาชื่อเมนู
  python db_viewer.py --export          → export เป็น CSV
  python db_viewer.py --delete 5        → ลบ session #5
─────────────────────────────────────────────────────────
"""

import argparse
import csv
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# ── ตำแหน่ง database ──────────────────────────────────────
DB_PATH = Path(__file__).parent / "food_detection.db"


# ── ANSI colors ────────────────────────────────────────────
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    GREEN = "\033[92m"
    BLUE = "\033[94m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    GRAY = "\033[90m"
    WHITE = "\033[97m"


def g(s):
    return f"{C.GREEN}{s}{C.RESET}"


def b(s):
    return f"{C.BLUE}{s}{C.RESET}"


def y(s):
    return f"{C.YELLOW}{s}{C.RESET}"


def r(s):
    return f"{C.RED}{s}{C.RESET}"


def cy(s):
    return f"{C.CYAN}{s}{C.RESET}"


def gr(s):
    return f"{C.GRAY}{s}{C.RESET}"


def bold(s):
    return f"{C.BOLD}{s}{C.RESET}"


# ── DB helpers ─────────────────────────────────────────────
def get_conn():
    if not DB_PATH.exists():
        print(r(f"❌ ไม่พบ database: {DB_PATH}"))
        print(gr("   รัน python app.py ก่อนอย่างน้อย 1 ครั้ง"))
        sys.exit(1)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── Commands ───────────────────────────────────────────────


def cmd_list(limit: int = 20, search: str = None):
    """แสดงรายการ sessions"""
    conn = get_conn()

    if search:
        rows = conn.execute(
            """
            SELECT DISTINCT s.* FROM detection_sessions s
            LEFT JOIN detection_items i ON i.session_id = s.id
            WHERE i.food_name_th LIKE ? OR i.food_name LIKE ?
            ORDER BY s.created_at DESC LIMIT ?
        """,
            (f"%{search}%", f"%{search}%", limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM detection_sessions
            ORDER BY created_at DESC LIMIT ?
        """,
            (limit,),
        ).fetchall()

    total = conn.execute("SELECT COUNT(*) FROM detection_sessions").fetchone()[0]
    conn.close()

    if not rows:
        print(gr("  ไม่มีข้อมูล"))
        return

    # ── Header ──
    print()
    print(
        bold(
            f"{'#':<6} {'วันเวลา':<22} {'เมนู':<30} {'จำนวน':>6} {'น้ำหนัก':>10} {'ราคา':>8}"
        )
    )
    print(gr("─" * 86))

    for row in rows:
        s = dict(row)
        sid = b(f"#{s['id']:<5}")
        dt = gr(s["created_at"][:16].replace("T", " "))

        # ดึงชื่อเมนูแรก
        conn2 = get_conn()
        items = conn2.execute(
            "SELECT food_name_th, food_name FROM detection_items WHERE session_id = ? LIMIT 3",
            (s["id"],),
        ).fetchall()
        conn2.close()

        names = ", ".join((i["food_name_th"] or i["food_name"]) for i in items)
        if s["item_count"] > 3:
            names += f" +{s['item_count']-3}"
        names = names[:28]

        wt = f"{s['weight_grams']:.0f}g" if s["weight_grams"] > 0 else "—"
        price = g(f"฿{s['total_price']:.0f}")

        print(f" {sid} {dt}  {names:<30} {s['item_count']:>5}  {wt:>9}  {price:>8}")

    print(gr("─" * 86))
    showing = len(rows)
    print(gr(f"  แสดง {showing} จาก {total} รายการ  |  db: {DB_PATH}"))
    print()


def cmd_detail(session_id: int):
    """แสดงรายละเอียด session เดี่ยว"""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM detection_sessions WHERE id = ?", (session_id,)
    ).fetchone()

    if not row:
        print(r(f"❌ ไม่พบ Session #{session_id}"))
        conn.close()
        return

    s = dict(row)
    items = conn.execute(
        "SELECT * FROM detection_items WHERE session_id = ? ORDER BY id", (session_id,)
    ).fetchall()
    conn.close()

    print()
    print(bold(f"  ═══ Session #{s['id']} ═══"))
    print(f"  UUID       : {gr(s['session_uuid'])}")
    print(f"  วันเวลา    : {cy(s['created_at'])}")
    print(f"  ภาพ        : {gr(s['image_path'])}")
    print(
        f"  น้ำหนักรวม : {y(str(s['weight_grams']) + ' กรัม') if s['weight_grams'] > 0 else gr('—')}"
    )
    print(f"  ราคารวม    : {g('฿' + str(int(s['total_price'])))}")
    if s.get("notes"):
        print(f"  หมายเหตุ   : {s['notes']}")

    print()
    print(bold(f"  รายการอาหาร ({s['item_count']} รายการ)"))
    print(gr("  " + "─" * 70))

    for it in items:
        conf = int((it["confidence"] or 0) * 100)
        name_th = it["food_name_th"] or it["food_name"]
        name_en = it["food_name_en"] or ""
        wt = f"{it['weight_grams']:.1f}g" if it["weight_grams"] > 0 else "—"
        bar = g("█" * (conf // 10)) + gr("░" * (10 - conf // 10))

        print(
            f"  {b(name_th):<20} {gr(name_en):<25} {bar} {conf:>3}%  {gr(wt):>8}  {g('฿'+str(int(it['price'])))}"
        )

    print()


def cmd_stats():
    """แสดงสถิติสรุป"""
    conn = get_conn()

    total = conn.execute("SELECT COUNT(*) FROM detection_sessions").fetchone()[0]
    revenue = (
        conn.execute("SELECT SUM(total_price) FROM detection_sessions").fetchone()[0]
        or 0
    )
    avg_price = (
        conn.execute("SELECT AVG(total_price) FROM detection_sessions").fetchone()[0]
        or 0
    )
    total_items = conn.execute("SELECT COUNT(*) FROM detection_items").fetchone()[0]

    # เมนูยอดนิยม 5 อันดับ
    top_menus = conn.execute(
        """
        SELECT COALESCE(food_name_th, food_name) as name, COUNT(*) as cnt
        FROM detection_items
        GROUP BY name ORDER BY cnt DESC LIMIT 5
    """
    ).fetchall()

    # รายได้รายวัน 7 วันล่าสุด
    daily = conn.execute(
        """
        SELECT DATE(created_at) as day, COUNT(*) as cnt, SUM(total_price) as rev
        FROM detection_sessions
        WHERE created_at >= DATE('now', '-7 days')
        GROUP BY day ORDER BY day DESC
    """
    ).fetchall()

    conn.close()

    print()
    print(bold("  ════ สถิติสรุป ════"))
    print()
    print(f"  Sessions ทั้งหมด  : {b(str(total))}")
    print(f"  รายการอาหารรวม    : {b(str(total_items))}")
    print(f"  รายได้รวม         : {g('฿' + f'{revenue:.0f}')}")
    print(f"  เฉลี่ยต่อครั้ง    : {y('฿' + f'{avg_price:.0f}')}")

    if top_menus:
        print()
        print(bold("  เมนูยอดนิยม:"))
        for i, m in enumerate(top_menus, 1):
            bar = g("█" * min(m["cnt"], 20))
            print(f"   {i}. {m['name']:<25} {bar} {cy(str(m['cnt']))} ครั้ง")

    if daily:
        print()
        print(bold("  รายได้ 7 วันล่าสุด:"))
        for d in daily:
            rev = f"{d['rev']:.0f}"
    print(f"   {gr(d['day'])}   {d['cnt']:>3} ครั้ง   {g('฿' + rev)}")

    print()


def cmd_export():
    """Export ทุก session เป็น CSV"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM detection_sessions ORDER BY created_at DESC"
    ).fetchall()
    conn.close()

    if not rows:
        print(gr("  ไม่มีข้อมูล"))
        return

    filename = f"food_ai_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "id",
                "session_uuid",
                "created_at",
                "image_path",
                "total_price",
                "weight_grams",
                "item_count",
                "notes",
            ]
        )
        for row in rows:
            writer.writerow(list(row))

    print(g(f"  ✅ Export {len(rows)} รายการ → {filename}"))


def cmd_delete(session_id: int):
    """ลบ session"""
    conn = get_conn()
    row = conn.execute(
        "SELECT id, created_at, total_price FROM detection_sessions WHERE id = ?",
        (session_id,),
    ).fetchone()

    if not row:
        print(r(f"  ❌ ไม่พบ Session #{session_id}"))
        conn.close()
        return

    confirm = input(
        y(
            f"  ⚠️  ลบ Session #{session_id} ({row['created_at'][:16]}, ฿{row['total_price']:.0f})? [y/N] "
        )
    )
    if confirm.lower() != "y":
        print(gr("  ยกเลิก"))
        conn.close()
        return

    conn.execute("DELETE FROM detection_sessions WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()
    print(g(f"  ✅ ลบ Session #{session_id} แล้ว"))


# ── Main ───────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="🍽️  Food AI — Database Viewer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""ตัวอย่าง:
  python db_viewer.py                 แสดง 20 รายการล่าสุด
  python db_viewer.py --all           แสดงทั้งหมด
  python db_viewer.py --id 5          ดู session #5 แบบละเอียด
  python db_viewer.py --stats         สถิติสรุป
  python db_viewer.py --search ไก่    ค้นหาเมนู
  python db_viewer.py --export        export CSV
  python db_viewer.py --delete 5      ลบ session #5""",
    )
    parser.add_argument("--id", type=int, help="ดูรายละเอียด session ID")
    parser.add_argument("--all", action="store_true", help="แสดงทุก session")
    parser.add_argument("--stats", action="store_true", help="สถิติสรุป")
    parser.add_argument("--search", type=str, help="ค้นหาชื่อเมนู")
    parser.add_argument("--export", action="store_true", help="export CSV")
    parser.add_argument("--delete", type=int, help="ลบ session ID")
    parser.add_argument(
        "--db", type=str, help="path ของ database (default: food_detection.db)"
    )

    args = parser.parse_args()

    # override db path ถ้าระบุ
    if args.db:
        global DB_PATH
        DB_PATH = Path(args.db)

    if args.id:
        cmd_detail(args.id)
    elif args.stats:
        cmd_stats()
    elif args.export:
        cmd_export()
    elif args.delete:
        cmd_delete(args.delete)
    elif args.search:
        cmd_list(limit=100, search=args.search)
    elif args.all:
        cmd_list(limit=9999)
    else:
        cmd_list(limit=20)


if __name__ == "__main__":
    main()
