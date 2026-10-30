# -*- coding: utf-8 -*-
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import formula_engine as fe  # noqa: E402


def sample_series(n=140, kind="top2", seed=7):
    rng = np.random.default_rng(seed)
    w = fe.width_of(kind)
    return [f"{int(x):0{w}d}" for x in rng.integers(0, 10 ** w, n)]


class DateTests(unittest.TestCase):
    def test_buddhist_year(self):
        self.assertEqual(fe.iso_date("21/01/2564"), "2021-01-21")
        self.assertEqual(fe.iso_date("29/02/2567"), "2024-02-29")   # ปีอธิกสุรทิน พ.ศ.

    def test_iso_and_bad(self):
        self.assertEqual(fe.iso_date("2026-10-28"), "2026-10-28")
        with self.assertRaises(ValueError):
            fe.iso_date("31/02/2569")


class NoLookaheadTests(unittest.TestCase):
    """คะแนนของงวด i ต้องไม่เปลี่ยน แม้จะตัดข้อมูลหลังงวด i ทิ้ง"""

    def test_scores_independent_of_future(self):
        for kind in ("top2", "top3"):
            full = sample_series(120, kind)
            k = 90
            m_full = fe.Model(full, kind)
            m_cut = fe.Model(full[:k], kind)
            for name in m_cut.strategies():
                self.assertTrue(
                    np.array_equal(m_full.ranks[name][k], m_cut.ranks[name][k]),
                    f"{kind}/{name} มีการใช้ข้อมูลอนาคต")

    def test_random_control_is_near_baseline(self):
        s = sample_series(600, "top2", seed=3)
        rows = [{"draw_date": f"2020-01-{1 + i % 28:02d}", "number2_top": x,
                 "number6": "", "number3_top": "", "number2_bottom": ""}
                for i, x in enumerate(s)]
        for i, r in enumerate(rows):           # ทำให้วันที่ไม่ซ้ำ
            r["draw_date"] = f"{2000 + i // 365}-{(i % 365) // 31 + 1:02d}-{(i % 31) % 28 + 1:02d}"
        ev = fe.evaluate(rows, "top2", 400, 10)
        for name, st in ev["strategies"].items():
            self.assertLess(abs(st["hit_pct"] - 10), 7, name)  # ข้อมูลสุ่มต้องไม่ให้ผลเบี่ยงเบนมากผิดปกติ


class StatsTests(unittest.TestCase):
    def test_binom_sf(self):
        self.assertAlmostEqual(fe.binom_sf(0, 10, .5), 1.0)
        self.assertAlmostEqual(fe.binom_sf(10, 10, .5), 0.5 ** 10)
        self.assertAlmostEqual(fe.binom_sf(5, 10, .5), 0.623046875, places=6)

    def test_wilson_bounds(self):
        lo, hi = fe.wilson(30, 300)
        self.assertTrue(0 < lo < .1 < hi < 1)


if __name__ == "__main__":
    unittest.main()


class ImporterTests(unittest.TestCase):
    def test_parse_page_buddhist_date(self):
        try:
            import thaiorc_import as ti
        except ImportError:
            self.skipTest("bs4/requests ไม่ได้ติดตั้ง")
        html = ("<table><tr><td>28/10/2569</td><td>740618</td><td>618</td>"
                "<td>18</td><td>06</td></tr></table>")
        rows = ti.parse_page(html, "test")
        self.assertEqual(rows[0]["draw_date"], "2026-10-28")
        self.assertEqual(rows[0]["number2_bottom"], "06")
