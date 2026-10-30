# Data import script
# -*- coding: utf-8 -*-
import argparse
import csv
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

import formula_engine as fe

ROOT = Path(__file__).resolve().parent
URLS = [
    "https://lotto.thaiorc.com/lao/stats/lottery-years10.php",
    "https://lotto.thaiorc.com/lao/stats/lottery-years20.php",
]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; LaoLotteryFormulaLab/1.0)"
}


def parse_page(html, source):
    soup = BeautifulSoup(html, "html.parser")
    rows = []

    for tr in soup.select("tr"):
        cells = [
            c.get_text(" ", strip=True)
            for c in tr.find_all(["td", "th"], recursive=False)
        ]
        if len(cells) < 5:
            continue

        date = cells[0].strip()
        # ต้องเป็นวันที่รูปแบบที่ระบบรองรับ
        try:
            date_iso = fe.iso_date(date)
        except ValueError:
            continue

        values = [x.strip().replace(",", "") for x in cells[1:5]]
        if not (
            len(values[0]) == 6 and values[0].isdigit()
            and len(values[1]) == 3 and values[1].isdigit()
            and len(values[2]) == 2 and values[2].isdigit()
            and len(values[3]) == 2 and values[3].isdigit()
        ):
            continue

        rows.append({
            "draw_date": date_iso,
            "number6": values[0],
            "number3_top": values[1],
            "number2_top": values[2],
            "number2_bottom": values[3],
            "source": source,
        })

    return rows


def fetch_url(base, max_pages=100):
    session = requests.Session()
    session.headers.update(HEADERS)
    all_rows = []
    signatures = set()

    for page in range(1, max_pages + 1):
        url = f"{base}?pg={page}"
        try:
            response = session.get(url, timeout=25)
            response.raise_for_status()
            response.encoding = response.apparent_encoding or "utf-8"
            found = parse_page(response.text, url)
        except Exception as exc:
            print(f"[WARN] อ่านหน้า {url} ไม่สำเร็จ: {exc}")
            # ไม่ยืนยันว่าหมดข้อมูลเมื่อมีข้อผิดพลาด
            break

        if not found:
            print(f"[INFO] ไม่พบแถวผลรางวัลที่อ่านได้ในหน้า {page}")
            break

        signature = tuple(
            (r["draw_date"], r["number6"], r["number2_bottom"])
            for r in found
        )
        if signature in signatures:
            print(f"[INFO] หน้า {page} ซ้ำกับหน้าก่อนหน้า หยุดอ่าน")
            break

        signatures.add(signature)
        all_rows.extend(found)
        print(f"[OK] หน้า {page}: {len(found)} แถว")
        time.sleep(0.4)

    return all_rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=100)
    parser.add_argument("--years20", action="store_true",
                        help="ดึงจาก years20 เพิ่มด้วย")
    args = parser.parse_args()

    urls = [URLS[0]]
    if args.years20:
        urls.append(URLS[1])

    incoming = []
    for url in urls:
        print(f"\nดึงข้อมูล: {url}")
        incoming.extend(fetch_url(url, args.pages))

    if not incoming:
        raise SystemExit(
            "ไม่พบข้อมูลใหม่ โปรดตรวจว่าเว็บไซต์ยังเปิดใช้งาน "
            "และรูปแบบตารางไม่เปลี่ยน"
        )

    current = fe.read_draws()
    by_date = {r["draw_date"]: r for r in current}
    added, conflicts = 0, []

    for row in incoming:
        old = by_date.get(row["draw_date"])
        if old is None:
            by_date[row["draw_date"]] = row
            added += 1
            continue

        # ถ้าข้อมูลวันเดียวกันไม่ตรงกัน ให้เก็บเป็น conflict ไม่เขียนทับ
        fields = ("number6", "number3_top", "number2_top", "number2_bottom")
        differences = [f for f in fields if old.get(f) and row.get(f)
                       and old[f] != row[f]]
        if differences:
            conflicts.append({
                "date": row["draw_date"],
                "fields": ",".join(differences),
                "old": str(old),
                "incoming": str(row),
            })

    merged = sorted(by_date.values(), key=lambda r: r["draw_date"])
    fe.save_draws(merged)

    conflict_path = ROOT / "data" / "import_conflicts.csv"
    if conflicts:
        conflict_path.parent.mkdir(parents=True, exist_ok=True)
        exists = conflict_path.exists()
        with conflict_path.open("a", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["date", "fields", "old", "incoming"])
            if not exists:
                writer.writeheader()
            writer.writerows(conflicts)

    print(f"\nข้อมูลเดิม {len(current)} แถว")
    print(f"พบข้อมูลจากเว็บไซต์ {len(incoming)} แถว")
    print(f"เพิ่มวันที่ใหม่ {added} แถว")
    print(f"รายการขัดแย้ง {len(conflicts)} แถว")
    print(f"รวมหลังรวมข้อมูล {len(merged)} แถว")


if __name__ == "__main__":
    main()