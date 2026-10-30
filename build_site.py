# -*- coding: utf-8 -*-
"""สร้างเว็บ static (docs/index.html + docs/data.json) สำหรับ GitHub Pages"""
import csv
import json
from datetime import datetime, timezone

import formula_engine as fe
import lotto_common as lc

DOCS = lc.ROOT / "docs"
TEMPLATE = lc.ROOT / "site" / "template.html"


def cumulative(hits, p0):
    out, c = [], 0.0
    for h in hits:
        c += h - p0
        out.append(round(c, 3))
    return out


def band(n, p0):
    import math
    return [round(2 * math.sqrt(i * p0 * (1 - p0)), 3) for i in range(1, n + 1)]


def main():
    cfg = lc.load_config()
    rows = fe.read_draws()
    primary = cfg["primary_strategy"]
    window = cfg["backtest_window"]
    payout = cfg["payout_multiplier_ASSUMPTION"]

    # ---------- backtest (จำลอง walk-forward) ----------
    evals, models = {}, {}
    for kind in fe.KINDS:
        ev = fe.evaluate(rows, kind, window, cfg["picks"][kind])
        evals[kind] = ev
        models[kind] = ev["model"]
    m_tests = sum(len([s for s in ev["strategies"] if s != fe.CONTROL])
                  for ev in evals.values())            # จำนวนการทดสอบทั้งหมด (Bonferroni)

    backtest = {}
    for kind, ev in evals.items():
        p0, picks = ev["baseline"], ev["picks"]
        strat_rows = []
        for key, s in ev["strategies"].items():
            p_adj = min(1.0, s["p_value"] * m_tests)
            strat_rows.append({
                "key": key, "name": s["name"], "is_control": key == fe.CONTROL,
                "is_primary": key == primary,
                **{k: s[k] for k in ("tests", "hits", "misses", "hit_pct", "baseline_pct",
                                     "expected_hits", "z", "ci_low_pct", "ci_high_pct")},
                "p_value": round(s["p_value"], 4), "p_adj": round(p_adj, 4),
                "verdict": "control" if key == fe.CONTROL
                else fe.verdict(s["p_value"], p_adj),
            })
        strat_rows.sort(key=lambda r: (-r["hit_pct"], r["key"]))
        pr, ct = ev["strategies"][primary], ev["strategies"][fe.CONTROL]
        n = len(ev["dates"])
        records = [{"date": d, "actual": a, "rank": int(r) + 1, "hit": int(h)}
                   for d, a, r, h in zip(ev["dates"], ev["actual"], pr["ranks"], pr["hit_flags"])]
        pnl = lambda hits: [round(sum(h * payout[kind] - picks for h in hits[:i + 1]), 1)
                            for i in range(len(hits))]
        backtest[kind] = {
            "label": fe.KIND_LABELS[kind], "picks": picks, "tests": n,
            "baseline_pct": round(100 * p0, 2),
            "from": ev["dates"][0] if n else None, "to": ev["dates"][-1] if n else None,
            "strategies": strat_rows,
            "records": records[-80:][::-1],
            "chart": {"dates": ev["dates"],
                      "primary": cumulative(pr["hit_flags"], p0),
                      "control": cumulative(ct["hit_flags"], p0),
                      "band": band(n, p0),
                      "pnl_primary": pnl(pr["hit_flags"]),
                      "pnl_control": pnl(ct["hit_flags"])},
        }

    # ---------- งวดหน้า (ใช้คำทายที่ล็อกไว้ ถ้ามี) ----------
    target = lc.next_target(rows, cfg)
    locked = None
    p_file = lc.PRED_DIR / f"{target}.json"
    if p_file.exists():
        locked = json.loads(p_file.read_text(encoding="utf-8"))
    nxt = {"target_date": target, "cutoff_hour_ict": cfg["draw_cutoff_hour_ict"],
           "locked": bool(locked and locked.get("locked_before_draw")),
           "created_at_utc": locked.get("created_at_utc") if locked else None,
           "sha256": locked.get("sha256") if locked else None,
           "data_through": (locked or {}).get("data_through", rows[-1]["draw_date"]),
           "kinds": {}}
    for kind in fe.KINDS:
        st = {r["key"]: r for r in backtest[kind]["strategies"]}[primary]
        if locked and kind in locked["kinds"]:
            picks_list = locked["kinds"][kind]["rankings"][primary]
            weights = locked["kinds"][kind]["adaptive_weights"]
        else:
            picks_list = models[kind].top(primary, cfg["picks"][kind])
            weights = {k: round(v, 4) for k, v in models[kind].adaptive_weights.items()}
        p_single = 1 / 10 ** fe.width_of(kind)      # โอกาสถูกของ "เลขหนึ่งตัว" (ลง 1 หน่วยต่อเลข)
        mult = payout[kind]
        nxt["kinds"][kind] = {
            "label": fe.KIND_LABELS[kind], "picks": picks_list,
            "hit_pct": st["hit_pct"], "baseline_pct": st["baseline_pct"],
            "p_adj": st["p_adj"], "verdict": st["verdict"],
            "verdict_text": fe.VERDICT_TEXT[st["verdict"]],
            "weights": dict(sorted(weights.items(), key=lambda x: -x[1])[:5]),
            "ev": {"payout_assumed": mult,
                   "return_per_unit_pct": round(100 * p_single * mult, 1),
                   "breakeven_payout": round(1 / p_single)},
        }

    # ---------- ผลคำทายจริงที่ล็อกก่อนออกผล ----------
    live_rows = []
    rp = lc.ROOT / "data" / "prediction_results.csv"
    if rp.exists():
        with rp.open(encoding="utf-8-sig", newline="") as f:
            live_rows = [r for r in csv.DictReader(f) if r["strategy"] == primary]
    live_summary = {}
    sp = lc.ROOT / "data" / "live_summary.json"
    if sp.exists():
        live_summary = json.loads(sp.read_text(encoding="utf-8"))
    live = {
        "draws": len({r["target_date"] for r in live_rows}),
        "records": [{"date": r["target_date"], "kind": r["kind"], "actual": r["actual"],
                     "picks": r["picks"].split(), "hit": int(r["hit"])}
                    for r in sorted(live_rows, key=lambda r: r["target_date"], reverse=True)][:90],
        "summary": {k: v.get(primary) for k, v in live_summary.items() if v.get(primary)},
    }

    data = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total_draws": len(rows), "first_date": rows[0]["draw_date"],
        "data_through": rows[-1]["draw_date"],
        "primary": {"key": primary, "name": fe.STRATEGIES[primary]},
        "window": window, "bonferroni_m": m_tests,
        "next": nxt, "backtest": backtest, "live": live,
        "recent_draws": [{k: r[k] for k in ("draw_date", "number6", "number3_top",
                                            "number2_top", "number2_bottom")}
                         for r in rows[-30:][::-1]],
    }

    DOCS.mkdir(exist_ok=True)
    (DOCS / "data.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", blob)
    (DOCS / "index.html").write_text(html, encoding="utf-8")
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")
    print(f"สร้างเว็บแล้ว: docs/index.html  (งวดหน้า {target}, ข้อมูลถึง {data['data_through']})")


if __name__ == "__main__":
    main()
