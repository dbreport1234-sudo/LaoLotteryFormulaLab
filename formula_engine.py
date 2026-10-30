# -*- coding: utf-8 -*-
"""
Formula Engine v2
-----------------
- ทุกสูตรคำนวณจาก "ข้อมูลก่อนงวดนั้น" เท่านั้น (walk-forward, ไม่แอบดูอนาคต)
- มีสูตรควบคุม `random` ไว้เทียบ เพื่อดูว่าสูตรอื่นชนะการสุ่มจริงหรือไม่
- มีค่า p-value (binomial) และ Bonferroni เพื่อกันการหลงเชื่อผลบังเอิญ
"""
import csv
import math
import re
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "lao_lottery_full.csv"
FIELDS = ["draw_date", "number6", "number3_top",
          "number2_top", "number2_bottom", "source"]

KINDS = ("top2", "top3", "bottom2")
KIND_LABELS = {"top2": "2 ตัวบน", "top3": "3 ตัวบน", "bottom2": "2 ตัวล่าง"}

MIN_HISTORY = 30          # ต้องมีอย่างน้อยกี่งวดก่อนเริ่มทายได้
ADAPT_WINDOW = 100        # หน้าต่างย้อนหลังที่ใช้ปรับน้ำหนักสูตร adaptive

STRATEGIES = {
    "frequency": "ความถี่ตลอดประวัติ",
    "decay": "ความถี่แบบถ่วงน้ำหนักงวดใหม่",
    "recent": "ความถี่ 30 งวดล่าสุด",
    "cold": "เลขที่ออกน้อย (กลับด้านความถี่)",
    "gap": "ระยะห่างจากการออก (เลขค้างนาน)",
    "digit": "รูปแบบจำนวนเลขคี่",
    "sum": "รูปแบบผลรวมเลข",
    "pair": "ความถี่คู่เลขติดกัน",
    "digitpos": "ความถี่เลขรายตำแหน่ง",
    "ensemble": "รวมคะแนนหลายสูตร (น้ำหนักคงที่)",
    "adaptive": "รวมสูตรแบบปรับน้ำหนักตามผลล่าสุด",
    "random": "สุ่ม (สูตรควบคุมไว้เทียบ)",
}
CONTROL = "random"
PRIMARY = "adaptive"


# ---------------------------------------------------------------- dates / IO
_DATE_RE = re.compile(r"^(\d{1,4})[-/](\d{1,2})[-/](\d{1,4})$")


def iso_date(value):
    """รับ YYYY-MM-DD หรือ DD/MM/YYYY ทั้ง ค.ศ. และ พ.ศ. -> คืน ISO แบบ ค.ศ."""
    s = str(value or "").strip()
    m = _DATE_RE.match(s)
    if not m:
        raise ValueError(f"วันที่ไม่ถูกต้อง: {s}")
    a, b, c = m.group(1), int(m.group(2)), m.group(3)
    if len(a) == 4:
        y, mo, d = int(a), b, int(c)
    else:
        d, mo, y = int(a), b, int(c)
    if y > 2400:                      # ปี พ.ศ.
        y -= 543
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        raise ValueError(f"วันที่ไม่ถูกต้อง: {s}")


def read_draws(path=DATA):
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return clean_draws(rows)[0]


def clean_draws(rows):
    clean, rejected, seen = [], [], set()
    for raw in rows:
        try:
            d = iso_date(raw.get("draw_date") or raw.get("date"))
            n6 = str(raw.get("number6") or "").strip()
            n3 = str(raw.get("number3_top") or raw.get("result3") or "").strip()
            n2 = str(raw.get("number2_top") or raw.get("result2") or "").strip()
            b2 = str(raw.get("number2_bottom") or raw.get("bottom2") or "").strip()
            for label, v, w in (("number6", n6, 6), ("number3_top", n3, 3),
                                ("number2_top", n2, 2), ("number2_bottom", b2, 2)):
                if v and (len(v) != w or not v.isdigit()):
                    raise ValueError(f"{label} ต้องเป็นเลข {w} หลัก")
            if not any((n6, n3, n2, b2)):
                raise ValueError("ไม่มีเลขผลรางวัล")
            if n6:
                n3 = n3 or n6[-3:]
                n2 = n2 or n6[-2:]
                if n3 != n6[-3:]:
                    raise ValueError("เลข 3 ตัวบนไม่ตรงกับเลข 6 ตัว")
                if n2 != n6[-2:]:
                    raise ValueError("เลข 2 ตัวบนไม่ตรงกับเลข 6 ตัว")
            if d in seen:
                rejected.append({"row": raw, "reason": "วันที่ซ้ำในชุดข้อมูล"})
                continue
            seen.add(d)
            clean.append({"draw_date": d, "number6": n6, "number3_top": n3,
                          "number2_top": n2, "number2_bottom": b2,
                          "source": str(raw.get("source") or "").strip()})
        except Exception as e:
            rejected.append({"row": raw, "reason": str(e)})
    clean.sort(key=lambda r: r["draw_date"])
    return clean, rejected


def save_draws(rows, path=DATA):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned, rejected = clean_draws(rows)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(cleaned)
    return len(cleaned), rejected


def target_value(row, kind):
    key = {"top2": "number2_top", "top3": "number3_top",
           "bottom2": "number2_bottom"}.get(kind)
    return str(row.get(key) or "") if key else ""


def width_of(kind):
    return 3 if kind == "top3" else 2


def number_space(kind):
    w = width_of(kind)
    return [f"{n:0{w}d}" for n in range(10 ** w)]


def baseline(kind, picks):
    """ความน่าจะเป็นที่ถูกด้วยการสุ่มล้วน เมื่อเลือก `picks` เลข"""
    return min(picks, 10 ** width_of(kind)) / 10 ** width_of(kind)


def usable_rows(rows, kind):
    w = width_of(kind)
    out = [r for r in rows if len(target_value(r, kind)) == w
           and target_value(r, kind).isdigit()]
    out.sort(key=lambda r: r["draw_date"])
    return out


# ---------------------------------------------------------------- statistics
def binom_sf(k, n, p):
    """P(X >= k) แบบแม่นยำ (ไม่พึ่ง scipy)"""
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    if p <= 0:
        return 0.0
    if p >= 1:
        return 1.0
    lp, lq = math.log(p), math.log(1 - p)
    logs = [math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)
            + i * lp + (n - i) * lq for i in range(k, n + 1)]
    m = max(logs)
    return min(1.0, math.exp(m) * sum(math.exp(x - m) for x in logs))


def wilson(h, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = h / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - r), min(1.0, c + r))


def summarize(hits, p0):
    n, h = len(hits), int(sum(hits))
    lo, hi = wilson(h, n)
    sd = math.sqrt(n * p0 * (1 - p0)) if n else 0
    return {
        "tests": n, "hits": h, "misses": n - h,
        "hit_pct": round(100 * h / n, 2) if n else 0.0,
        "baseline_pct": round(100 * p0, 2),
        "expected_hits": round(n * p0, 1),
        "z": round((h - n * p0) / sd, 2) if sd else 0.0,
        "p_value": binom_sf(h, n, p0) if n else 1.0,
        "ci_low_pct": round(100 * lo, 2), "ci_high_pct": round(100 * hi, 2),
    }


# ---------------------------------------------------------------- scoring
def _digits_matrix(kind):
    sp = number_space(kind)
    return np.array([[int(c) for c in n] for n in sp])


def _cum(X):
    out = np.zeros((X.shape[0] + 1, X.shape[1]))
    np.cumsum(X, axis=0, out=out[1:])
    return out


def _class_score(X, cls, n_classes):
    """คะแนนต่อ 'เลขหนึ่งตัว' ของคลาส (ความถี่คลาส / จำนวนเลขในคลาส)"""
    T, M = X.shape
    C = np.zeros((T, n_classes))
    C[np.arange(T), cls[X.argmax(axis=1)]] = 1
    cumC = _cum(C)
    size = np.bincount(cls, minlength=n_classes).astype(float)
    size[size == 0] = 1
    return cumC[:, cls] / size[cls][None, :]


def raw_scores(series, kind):
    """คืน dict ชื่อสูตร -> เมทริกซ์ (T+1, M) แถว i = คะแนนที่ทายงวด i
    โดยใช้เฉพาะ series[:i] เท่านั้น"""
    sp = number_space(kind)
    M, T, w = len(sp), len(series), width_of(kind)
    idx = {n: i for i, n in enumerate(sp)}
    act = np.array([idx[s] for s in series], dtype=int)
    X = np.zeros((T, M))
    X[np.arange(T), act] = 1
    cum = _cum(X)
    Dg = _digits_matrix(kind)
    S = {}

    S["frequency"] = cum
    S["cold"] = -cum

    lam = 0.5 ** (1 / 60)
    D = np.zeros((T + 1, M))
    for i in range(T):
        D[i + 1] = D[i] * lam + X[i]
    S["decay"] = D

    rec = np.zeros((T + 1, M))
    for i in range(T + 1):
        rec[i] = cum[i] - cum[max(0, i - 30)]
    S["recent"] = rec

    gap = np.zeros((T + 1, M))
    last = np.full(M, -1.0)
    for i in range(T + 1):
        gap[i] = i - last
        if i < T:
            last[act[i]] = i
    S["gap"] = gap

    S["digit"] = _class_score(X, (Dg % 2).sum(axis=1), w + 1)
    S["sum"] = _class_score(X, Dg.sum(axis=1), 9 * w + 1)

    if w == 3:       # สำหรับ 2 หลัก pair เท่ากับ frequency จึงไม่ใส่ซ้ำ
        P = np.zeros((T + 1, M))
        for pi in (Dg[:, :2] @ [10, 1], Dg[:, 1:] @ [10, 1]):
            Pc = np.zeros((T, 100))
            Pc[np.arange(T), pi[act]] = 1
            P += _cum(Pc)[:, pi] / 100.0
        S["pair"] = P / 2

    L = np.zeros((T + 1, M))      # ความถี่รายตำแหน่ง (log-likelihood, Laplace)
    for pos in range(w):
        Pc = np.zeros((T, 10))
        Pc[np.arange(T), Dg[act, pos]] = 1
        cp = _cum(Pc)
        logp = np.log((cp + 1) / (np.arange(T + 1)[:, None] + 10))
        L += logp[:, Dg[:, pos]]
    S["digitpos"] = L

    rnd = np.empty((T + 1, M))
    for i in range(T + 1):
        rnd[i] = np.random.default_rng(10_000 + i).random(M)
    S[CONTROL] = rnd
    return S, act


_ENSEMBLE_W = {"frequency": .20, "recent": .25, "gap": .10,
               "digit": .10, "sum": .10, "pair": .25}


def _rank_rows(S):
    """อันดับ 0 = ดีที่สุด ตัดสินเสมอด้วยค่า jitter คงที่ (ไม่เอนเอียงไปเลขต่ำ)"""
    M = S.shape[1]
    jit = np.random.default_rng(12345).random(M) * 1e-7
    order = np.argsort(-(S + jit), axis=1, kind="stable")
    rank = np.empty_like(order)
    np.put_along_axis(rank, order, np.arange(M)[None, :], axis=1)
    return rank.astype(np.int32)


class Model:
    """ผลคำนวณทั้งหมดของ series หนึ่งชุด (อันดับของทุกเลขทุกงวด)"""

    def __init__(self, series, kind, window=ADAPT_WINDOW):
        self.kind, self.series = kind, list(series)
        self.T = len(series)
        self.M = len(number_space(kind))
        S, self.act = raw_scores(series, kind)
        self.ranks = {name: _rank_rows(m) for name, m in S.items()}
        del S
        T, M = self.T, self.M
        den = max(1, M - 1)
        pct = {k: 1.0 - r / den for k, r in self.ranks.items()}

        # ensemble น้ำหนักคงที่
        wts = {k: v for k, v in _ENSEMBLE_W.items() if k in pct}
        tot = sum(wts.values())
        E = sum(pct[k] * (v / tot) for k, v in wts.items())
        self.ranks["ensemble"] = _rank_rows(E)

        # adaptive: น้ำหนัก = ความได้เปรียบเหนือ 0.5 ของผลย้อนหลังในหน้าต่าง
        # (ใช้เฉพาะงวดก่อนหน้า i เท่านั้น)
        comp = [k for k in pct if k != CONTROL]
        got = {k: pct[k][np.arange(T), self.act] for k in comp}
        cs = {k: np.concatenate([[0.0], np.cumsum(v)]) for k, v in got.items()}
        A = np.zeros((T + 1, M))
        self.adaptive_weights = {}
        for i in range(T + 1):
            lo = max(0, i - window)
            n = i - lo
            ws = {}
            if n >= MIN_HISTORY:
                for k in comp:
                    ws[k] = max(0.0, (cs[k][i] - cs[k][lo]) / n - 0.5)
            s = sum(ws.values())
            if s <= 0:                       # ไม่มีสูตรไหนเด่น -> เฉลี่ยเท่ากัน
                ws = {k: 1.0 / len(comp) for k in comp}
            else:
                ws = {k: v / s for k, v in ws.items()}
            for k, v in ws.items():
                if v:
                    A[i] += v * pct[k][i]
            if i == T:
                self.adaptive_weights = ws
        self.ranks["adaptive"] = _rank_rows(A)

    def strategies(self):
        return [k for k in STRATEGIES if k in self.ranks]

    def top(self, strategy, limit=10, row=None):
        row = self.T if row is None else row
        order = np.argsort(self.ranks[strategy][row], kind="stable")[:limit]
        sp = number_space(self.kind)
        return [sp[i] for i in order]

    def actual_ranks(self, strategy):
        return self.ranks[strategy][np.arange(self.T), self.act]


def evaluate(rows, kind, test_count=300, picks=10, window=ADAPT_WINDOW,
             model=None):
    """Walk-forward ย้อนหลัง test_count งวดล่าสุด"""
    use = usable_rows(rows, kind)
    series = [target_value(r, kind) for r in use]
    m = model or Model(series, kind, window)
    start = max(MIN_HISTORY, m.T - int(test_count))
    p0 = baseline(kind, picks)
    out = {"kind": kind, "picks": picks, "baseline": p0,
           "dates": [r["draw_date"] for r in use[start:]],
           "actual": series[start:], "model": m, "strategies": {}}
    for name in m.strategies():
        ranks = m.actual_ranks(name)[start:]
        hits = ranks < picks
        out["strategies"][name] = {
            "name": STRATEGIES[name], "ranks": ranks.tolist(),
            "hit_flags": hits.astype(int).tolist(), **summarize(hits, p0)}
    return out


def verdict(p_raw, p_adj):
    if p_adj < 0.05:
        return "signal"        # ผ่านการแก้ multiple testing
    if p_raw < 0.05:
        return "luck"          # ดูดีแต่น่าจะบังเอิญ
    return "none"              # ไม่ต่างจากการสุ่ม


VERDICT_TEXT = {
    "signal": "พบสัญญาณ (ควรตรวจซ้ำกับงวดใหม่)",
    "luck": "ดูดีกว่าสุ่ม แต่น่าจะบังเอิญ",
    "none": "ไม่ต่างจากการสุ่ม",
}


# ------------------------------------------- backward-compatible wrappers
def rank_numbers(history, kind, strategy="ensemble", limit=10):
    use = usable_rows(history, kind)
    if strategy not in STRATEGIES:
        raise ValueError("ไม่รู้จักสูตร: " + strategy)
    m = Model([target_value(r, kind) for r in use], kind)
    if strategy not in m.ranks:
        raise ValueError(f"สูตร {strategy} ใช้กับ {kind} ไม่ได้")
    limit = max(1, min(int(limit), m.M))
    row = m.ranks[strategy][m.T]
    order = np.argsort(row, kind="stable")[:limit]
    sp = number_space(kind)
    return [{"number": sp[i], "score": round(1 - row[i] / max(1, m.M - 1), 6)}
            for i in order]


def backtest(rows, kind="top2", test_count=100, picks=10):
    ev = evaluate(rows, kind, test_count, picks)
    out = []
    for name, s in ev["strategies"].items():
        out.append({"strategy": name, "name": s["name"], "tests": s["tests"],
                    "hits": s["hits"], "misses": s["misses"],
                    "hit_pct": s["hit_pct"], "random_pct": s["baseline_pct"],
                    "p_value": round(s["p_value"], 4),
                    "hit_dates": [d for d, h in zip(ev["dates"], s["hit_flags"]) if h]})
    out.sort(key=lambda x: (-x["hit_pct"], -x["hits"], x["strategy"]))
    return out
