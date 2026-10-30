# Flask or FastAPI application
# -*- coding: utf-8 -*-
import csv
import io
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template, request, Response

import formula_engine as fe

ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "lottery.db"
app = Flask(__name__)


def db():
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT
        )
    """)
    conn.commit()
    return conn


def log(action, details=""):
    with db() as conn:
        conn.execute(
            "INSERT INTO activity(created_at,action,details) VALUES(?,?,?)",
            (datetime.now(timezone.utc).isoformat(), action, details)
        )


def rows():
    return fe.read_draws()


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/summary")
def summary():
    data = rows()
    return jsonify({
        "count": len(data),
        "first_date": data[0]["draw_date"] if data else None,
        "last_date": data[-1]["draw_date"] if data else None,
        "strategies": fe.STRATEGIES,
    })


@app.get("/api/draws")
def draws():
    limit = max(1, min(request.args.get("limit", 100, type=int), 5000))
    return jsonify(list(reversed(rows()))[:limit])


@app.post("/api/draw")
def add_draw():
    payload = request.get_json(silent=True) or request.form.to_dict()
    current = rows()
    date = fe.iso_date(payload.get("draw_date") or payload.get("date"))

    # แทนที่เฉพาะวันที่เดียวกัน เมื่อผู้ใช้ส่งข้อมูลแก้ไขมาอย่างชัดเจน
    current = [r for r in current if r["draw_date"] != date]
    current.append({
        "draw_date": date,
        "number6": payload.get("number6", ""),
        "number3_top": payload.get("number3_top", ""),
        "number2_top": payload.get("number2_top", ""),
        "number2_bottom": payload.get("number2_bottom", ""),
        "source": payload.get("source", "manual"),
    })
    count, rejected = fe.save_draws(current)
    if rejected:
        return jsonify({"error": "ข้อมูลไม่ผ่านการตรวจสอบ", "rejected": rejected}), 400
    log("add_or_update_draw", date)
    return jsonify({"ok": True, "count": count})


@app.post("/api/import")
def import_csv():
    if "file" not in request.files:
        return jsonify({"error": "กรุณาเลือกไฟล์ CSV"}), 400
    file = request.files["file"]
    try:
        content = file.stream.read().decode("utf-8-sig")
        incoming = list(csv.DictReader(io.StringIO(content)))
        existing = rows()
        by_date = {r["draw_date"]: r for r in existing}
        added = 0
        for row in incoming:
            date = fe.iso_date(row.get("draw_date") or row.get("date"))
            mapped = {
                "draw_date": date,
                "number6": row.get("number6", ""),
                "number3_top": row.get("number3_top") or row.get("result3", ""),
                "number2_top": row.get("number2_top") or row.get("result2", ""),
                "number2_bottom": row.get("number2_bottom") or row.get("bottom2", ""),
                "source": row.get("source", "csv"),
            }
            if date not in by_date:
                by_date[date] = mapped
                added += 1
            else:
                # ไม่เขียนทับข้อมูลเดิมโดยอัตโนมัติ
                pass

        count, rejected = fe.save_draws(list(by_date.values()))
        log("import_csv", f"added={added}, total={count}")
        return jsonify({
            "ok": True, "added": added, "total": count,
            "rejected": rejected
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/api/backtest")
def backtest():
    kind = request.args.get("kind", "top2")
    if kind not in ("top2", "top3", "bottom2"):
        return jsonify({"error": "ชนิดผลไม่ถูกต้อง"}), 400
    test_count = max(10, min(request.args.get("tests", 100, type=int), 500))
    picks = max(1, min(request.args.get("picks", 10, type=int), 100))
    result = fe.backtest(rows(), kind, test_count, picks)
    log("backtest", f"{kind}, tests={test_count}, picks={picks}")
    return jsonify(result)


@app.get("/api/predict")
def predict():
    kind = request.args.get("kind", "top2")
    strategy = request.args.get("strategy", "ensemble")
    limit = max(1, min(request.args.get("picks", 10, type=int), 100))
    if kind not in ("top2", "top3", "bottom2"):
        return jsonify({"error": "ชนิดผลไม่ถูกต้อง"}), 400
    data = rows()
    history = [r for r in data if fe.target_value(r, kind)]
    if len(history) < 20:
        return jsonify({"error": "ข้อมูลย้อนหลังไม่พอ ต้องมีอย่างน้อย 20 งวด"}), 400
    ranked = fe.rank_numbers(history, kind, strategy, limit)
    return jsonify({
        "kind": kind, "strategy": strategy, "picks": ranked,
        "data_through": history[-1]["draw_date"],
        "note": "คะแนนเป็นการจัดอันดับเชิงสถิติ ไม่ใช่ความน่าจะเป็นที่รับประกันผล",
    })


@app.get("/api/activity")
def activity():
    with db() as conn:
        result = conn.execute(
            "SELECT * FROM activity ORDER BY id DESC LIMIT 100"
        ).fetchall()
    return jsonify([dict(r) for r in result])


@app.get("/api/export.csv")
def export_csv():
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fe.FIELDS)
    writer.writeheader()
    writer.writerows(rows())
    return Response(
        "\ufeff" + output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=lao_lottery_full.csv"}
    )


@app.get("/health")
def health():
    return jsonify({"ok": True, "draws": len(rows())})


if __name__ == "__main__":
    DB.parent.mkdir(parents=True, exist_ok=True)
    app.run(host="127.0.0.1", port=5000, debug=False)