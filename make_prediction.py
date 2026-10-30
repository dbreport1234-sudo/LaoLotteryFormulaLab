# -*- coding: utf-8 -*-
"""สร้างและ "ล็อก" คำทายงวดหน้า ก่อนผลออก (ห้ามเขียนทับ)
- เก็บ timestamp + SHA-256 + ข้อมูลที่ใช้ถึงวันไหน เพื่อตรวจย้อนหลังได้
- ถ้าสร้างหลังเวลาตัดรอบ จะติดป้าย locked_before_draw=false และไม่นับในสถิติ live
"""
import argparse
import hashlib
import json
from datetime import datetime, timezone

import formula_engine as fe
import lotto_common as lc


def build_payload(rows, target, cfg, now):
    picks = cfg["picks"]
    kinds = {}
    for kind in fe.KINDS:
        use = fe.usable_rows(rows, kind)
        if len(use) < fe.MIN_HISTORY + 20:
            continue
        m = fe.Model([fe.target_value(r, kind) for r in use], kind)
        n = picks[kind]
        kinds[kind] = {
            "picks": n,
            "rankings": {s: m.top(s, n) for s in m.strategies()},
            "adaptive_weights": {k: round(v, 4) for k, v in m.adaptive_weights.items()},
        }
    return {
        "schema_version": 2,
        "target_date": target,
        "created_at_utc": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "data_through": rows[-1]["draw_date"],
        "rows_used": len(rows),
        "primary_strategy": cfg["primary_strategy"],
        "locked_before_draw": now < lc.cutoff_of(target, cfg),
        "method": "walk-forward heuristic rankings; ไม่ใช่การรับประกันผล",
        "kinds": kinds,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="วันงวด (ค.ศ./พ.ศ. ก็ได้) ถ้าไม่ระบุจะคำนวณงวดถัดไปให้เอง")
    ap.add_argument("--force", action="store_true", help="เขียนทับ (ไม่แนะนำ)")
    args = ap.parse_args()

    cfg, rows = lc.load_config(), fe.read_draws()
    if len(rows) < 60:
        raise SystemExit("ข้อมูลย้อนหลังน้อยเกินไป (ต้อง >= 60 งวด)")
    now = lc.now_ict()
    target = fe.iso_date(args.date) if args.date else lc.next_target(rows, cfg, now)
    if target <= rows[-1]["draw_date"]:
        raise SystemExit(f"งวด {target} มีผลในข้อมูลแล้ว (ล่าสุด {rows[-1]['draw_date']})")

    path = lc.PRED_DIR / f"{target}.json"
    if path.exists() and not args.force:
        print(f"มีคำทายล็อกไว้แล้ว ไม่เขียนทับ: {path.name}")
        return

    payload = build_payload(rows, target, cfg, now)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    payload["sha256"] = hashlib.sha256(raw).hexdigest()
    lc.PRED_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"บันทึกคำทาย {path.name}  locked_before_draw={payload['locked_before_draw']}")
    print(f"ข้อมูลถึง {payload['data_through']}  sha256={payload['sha256'][:16]}…")


if __name__ == "__main__":
    main()
