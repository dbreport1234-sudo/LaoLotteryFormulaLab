# -*- coding: utf-8 -*-
"""ตัวช่วยร่วม: config, เวลาไทย, ตารางงวด"""
import json
from datetime import datetime, timedelta, timezone, date
from pathlib import Path

import formula_engine as fe

ROOT = Path(__file__).resolve().parent
PRED_DIR = ROOT / "data" / "predictions"
ICT = timezone(timedelta(hours=7))


def load_config():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    return cfg


def now_ict():
    return datetime.now(ICT)


def cutoff_of(target_iso, cfg):
    d = date.fromisoformat(target_iso)
    return datetime(d.year, d.month, d.day, cfg.get("draw_cutoff_hour_ict", 20),
                    0, tzinfo=ICT)


def draw_weekdays(rows, last_n=40):
    """วันในสัปดาห์ที่มีการออกรางวัลจริง (ดูจาก last_n งวดล่าสุด)"""
    tail = rows[-last_n:]
    counts = {}
    for r in tail:
        wd = date.fromisoformat(r["draw_date"]).weekday()
        counts[wd] = counts.get(wd, 0) + 1
    return {wd for wd, c in counts.items() if c >= max(2, last_n // 20)}


def next_target(rows, cfg, now=None):
    """งวดถัดไปที่ยังไม่ถึงเวลาตัดรอบ (ก่อนออกผล) ตามตารางที่ตรวจจากข้อมูล"""
    now = now or now_ict()
    wds = draw_weekdays(rows) or {0, 2, 4}
    d = now.date()
    for _ in range(21):
        if d.weekday() in wds and cutoff_of(d.isoformat(), cfg) > now:
            return d.isoformat()
        d += timedelta(days=1)
    raise RuntimeError("หางวดถัดไปไม่พบ")
