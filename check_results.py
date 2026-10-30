# -*- coding: utf-8 -*-
"""เทียบคำทายที่ล็อกไว้กับผลจริง -> data/prediction_results.csv + data/live_summary.json"""
import csv
import json

import formula_engine as fe
import lotto_common as lc

REPORT = lc.ROOT / "data" / "prediction_results.csv"
SUMMARY = lc.ROOT / "data" / "live_summary.json"
FIELDS = ["target_date", "kind", "strategy", "actual", "picks", "hit",
          "data_through", "created_at_utc"]


def collect():
    by_date = {r["draw_date"]: r for r in fe.read_draws()}
    out = []
    for path in sorted(lc.PRED_DIR.glob("*.json")):
        try:
            pred = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[WARN] อ่าน {path.name} ไม่ได้: {exc}")
            continue
        # นับเฉพาะคำทายที่ล็อกก่อนออกผลจริง และใช้ข้อมูลก่อนงวดนั้นเท่านั้น
        if not pred.get("locked_before_draw") or pred.get("data_through", "") >= pred["target_date"]:
            continue
        row = by_date.get(pred["target_date"])
        if not row:
            continue
        for kind, block in pred.get("kinds", {}).items():
            actual = fe.target_value(row, kind)
            if not actual:
                continue
            for strategy, picks in block["rankings"].items():
                out.append({"target_date": pred["target_date"], "kind": kind,
                            "strategy": strategy, "actual": actual,
                            "picks": " ".join(picks), "hit": int(actual in picks),
                            "data_through": pred["data_through"],
                            "created_at_utc": pred["created_at_utc"]})
    return out


def main():
    cfg = lc.load_config()
    res = collect()
    with REPORT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(res)

    summary = {}
    for kind in fe.KINDS:
        p0 = fe.baseline(kind, cfg["picks"][kind])
        for s in {r["strategy"] for r in res if r["kind"] == kind}:
            hits = [r["hit"] for r in res if r["kind"] == kind and r["strategy"] == s]
            summary.setdefault(kind, {})[s] = fe.summarize(hits, p0)
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    dates = sorted({r["target_date"] for r in res})
    print(f"ตรวจแล้ว {len(dates)} งวด / {len(res)} รายการ -> {REPORT.name}")


if __name__ == "__main__":
    main()
