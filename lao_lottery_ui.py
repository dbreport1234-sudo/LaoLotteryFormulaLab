# -*- coding: utf-8 -*-
"""Lao Lottery Formula Lab - importer and database viewer.
Uses only the confirmed ThaiORC Laos history page as its source.
"""
import csv
import queue
import re
import sqlite3
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    requests = None
    BeautifulSoup = None

APP_TITLE = "Lao Lottery Formula Lab | Data Center"
BASE_URL = "https://lotto.thaiorc.com/lao/stats/lottery-years10.php"
ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "lao_lottery.db"
CSV_PATH = ROOT / "lao_lottery_full.csv"
PAGE_LIMIT = 100

FIELDS = ("draw_date", "number6", "number3_top", "number2_top", "number2_bottom", "source")
FIELD_LABELS = {
    "draw_date": "วันที่ (พ.ศ.)",
    "number6": "เลข 6 ตัว",
    "number3_top": "3 ตัวบน",
    "number2_top": "2 ตัวบน",
    "number2_bottom": "2 ตัวล่าง",
    "source": "แหล่งข้อมูล",
}

def db_connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS draws_full (
            draw_date TEXT PRIMARY KEY,
            number6 TEXT,
            number3_top TEXT,
            number2_top TEXT,
            number2_bottom TEXT,
            source TEXT
        )
    """)
    return conn

def parse_page(html):
    soup = BeautifulSoup(html, "html.parser")
    records = []
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"], recursive=False)
        if len(cells) < 5:
            continue
        date_text = cells[0].get_text(" ", strip=True)
        match = re.search(r"(?<!\d)(\d{1,2}/\d{1,2}/\d{4})(?!\d)", date_text)
        if not match:
            continue
        vals = [c.get_text(" ", strip=True) for c in cells[1:5]]
        # Validate expected source layout before accepting a row.
        if not (
            re.fullmatch(r"\d{6}", vals[0])
            and re.fullmatch(r"\d{3}", vals[1])
            and re.fullmatch(r"\d{2}", vals[2])
            and re.fullmatch(r"\d{2}", vals[3])
        ):
            continue
        records.append({
            "draw_date": match.group(1),
            "number6": vals[0],
            "number3_top": vals[1],
            "number2_top": vals[2],
            "number2_bottom": vals[3],
            "source": BASE_URL,
        })
    return records

def fetch_all(progress_cb, stop_event):
    if requests is None or BeautifulSoup is None:
        raise RuntimeError("ยังไม่ได้ติดตั้ง requests และ beautifulsoup4 กรุณารัน install.bat")
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 Chrome/130 Safari/537.36"
    })
    collected = {}
    previous_signature = None
    last_page = 0
    for page in range(1, PAGE_LIMIT + 1):
        if stop_event.is_set():
            break
        progress_cb("status", f"กำลังดาวน์โหลดหน้า {page} ...")
        response = session.get(BASE_URL, params={"pg": page}, timeout=35)
        response.raise_for_status()
        response.encoding = response.apparent_encoding
        rows = parse_page(response.text)
        if not rows:
            progress_cb("page", (page, 0, len(collected), "ไม่พบข้อมูล"))
            break
        signature = tuple((r["draw_date"], r["number6"], r["number3_top"],
                           r["number2_top"], r["number2_bottom"]) for r in rows)
        if signature == previous_signature:
            progress_cb("page", (page, len(rows), len(collected), "หน้าซ้ำ — หยุด"))
            break
        added = 0
        for row in rows:
            # Source data is keyed by draw date; this mirrors the current DB schema.
            if row["draw_date"] not in collected:
                collected[row["draw_date"]] = row
                added += 1
        last_page = page
        progress_cb("page", (page, len(rows), len(collected), f"เพิ่ม {added}"))
        previous_signature = signature
        time.sleep(0.45)
    session.close()
    if stop_event.is_set():
        return 0, len(collected), last_page, True
    if not collected:
        raise RuntimeError("ไม่พบแถวผลรางวัลที่ตรงกับโครงสร้างที่คาดไว้")
    with db_connect() as conn:
        before = conn.execute("SELECT COUNT(*) FROM draws_full").fetchone()[0]
        conn.executemany("""
            INSERT INTO draws_full
                (draw_date, number6, number3_top, number2_top, number2_bottom, source)
            VALUES
                (:draw_date, :number6, :number3_top, :number2_top, :number2_bottom, :source)
            ON CONFLICT(draw_date) DO UPDATE SET
                number6=excluded.number6,
                number3_top=excluded.number3_top,
                number2_top=excluded.number2_top,
                number2_bottom=excluded.number2_bottom,
                source=excluded.source
        """, list(collected.values()))
        after = conn.execute("SELECT COUNT(*) FROM draws_full").fetchone()[0]
    return after - before, len(collected), last_page, False

def thai_date_sort_key(date_text):
    try:
        d, m, y = date_text.split("/")
        return int(y), int(m), int(d)
    except Exception:
        return 0, 0, 0

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1180x760")
        self.minsize(950, 620)
        self.configure(bg="#101827")
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.worker = None
        self.auto_job = None
        self.auto_enabled = tk.BooleanVar(value=False)
        self.interval_minutes = tk.StringVar(value="60")
        self.search_var = tk.StringVar()
        self.status_var = tk.StringVar(value="พร้อมใช้งาน")
        self.progress_var = tk.DoubleVar(value=0)
        self._style()
        self._build()
        self.refresh_table()
        self.after(150, self.poll_events)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background="#101827")
        style.configure("Panel.TFrame", background="#182235")
        style.configure("TLabel", background="#101827", foreground="#e7edf7", font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI", 20, "bold"), foreground="#ffffff")
        style.configure("Muted.TLabel", foreground="#9aabc4")
        style.configure("Metric.TLabel", background="#182235", foreground="#65e6bd", font=("Segoe UI", 22, "bold"))
        style.configure("MetricCaption.TLabel", background="#182235", foreground="#aab8cc", font=("Segoe UI", 9))
        style.configure("TButton", font=("Segoe UI", 10), padding=(10, 7))
        style.configure("Treeview", background="#121d2e", foreground="#e7edf7",
                        fieldbackground="#121d2e", rowheight=29, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", background="#263650", foreground="#ffffff",
                        font=("Segoe UI", 10, "bold"), padding=8)
        style.map("Treeview", background=[("selected", "#255b76")], foreground=[("selected", "#ffffff")])
        style.configure("Horizontal.TProgressbar", troughcolor="#263650", background="#65e6bd")

    def _build(self):
        top = ttk.Frame(self, padding=(22, 18, 22, 10))
        top.pack(fill="x")
        ttk.Label(top, text="LAO LOTTERY FORMULA LAB", style="Title.TLabel").pack(anchor="w")
        ttk.Label(top, text="Data Center • ดึงผลย้อนหลังอัตโนมัติ • ฐานข้อมูล SQLite • ส่งออก CSV",
                  style="Muted.TLabel").pack(anchor="w", pady=(4, 0))

        metrics = ttk.Frame(self, padding=(22, 8, 22, 12))
        metrics.pack(fill="x")
        self.metric_total = self.metric_card(metrics, "จำนวนงวดในฐานข้อมูล", "0")
        self.metric_oldest = self.metric_card(metrics, "งวดเก่าสุด", "-")
        self.metric_latest = self.metric_card(metrics, "งวดล่าสุด", "-")
        self.metric_valid = self.metric_card(metrics, "รูปแบบเลขผ่านตรวจ", "0")

        controls = ttk.Frame(self, padding=(22, 0, 22, 10))
        controls.pack(fill="x")
        self.fetch_btn = ttk.Button(controls, text="⟳  ดึงข้อมูล / อัปเดต", command=self.start_fetch)
        self.fetch_btn.pack(side="left")
        ttk.Button(controls, text="เปิดเว็บไซต์ต้นทาง", command=lambda: webbrowser.open(BASE_URL)).pack(side="left", padx=8)
        ttk.Button(controls, text="ส่งออก CSV", command=self.export_csv).pack(side="left")
        ttk.Button(controls, text="ตรวจสอบข้อมูล", command=self.validate_data).pack(side="left", padx=8)
        ttk.Label(controls, text="ค้นหา:", style="Muted.TLabel").pack(side="left", padx=(18, 5))
        search = ttk.Entry(controls, textvariable=self.search_var, width=22)
        search.pack(side="left")
        search.bind("<KeyRelease>", lambda _e: self.refresh_table())

        auto = ttk.Frame(self, padding=(22, 0, 22, 10))
        auto.pack(fill="x")
        ttk.Checkbutton(auto, text="เปิดอัปเดตอัตโนมัติ", variable=self.auto_enabled,
                        command=self.toggle_auto).pack(side="left")
        ttk.Label(auto, text="ทุก", style="Muted.TLabel").pack(side="left", padx=(12, 5))
        ttk.Entry(auto, textvariable=self.interval_minutes, width=6).pack(side="left")
        ttk.Label(auto, text="นาที (ทำงานขณะเปิดโปรแกรม)", style="Muted.TLabel").pack(side="left", padx=(5, 12))
        ttk.Label(auto, text="แหล่งข้อมูล: lotto.thaiorc.com", style="Muted.TLabel").pack(side="right")

        prog = ttk.Frame(self, padding=(22, 0, 22, 8))
        prog.pack(fill="x")
        self.progress = ttk.Progressbar(prog, variable=self.progress_var, maximum=100, mode="indeterminate")
        self.progress.pack(fill="x")
        ttk.Label(self, textvariable=self.status_var, style="Muted.TLabel",
                  padding=(22, 0, 22, 10)).pack(fill="x")

        table_frame = ttk.Frame(self, padding=(22, 0, 22, 12))
        table_frame.pack(fill="both", expand=True)
        cols = ("draw_date", "number6", "number3_top", "number2_top", "number2_bottom")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings")
        widths = {"draw_date": 150, "number6": 160, "number3_top": 140, "number2_top": 140, "number2_bottom": 140}
        for col in cols:
            self.tree.heading(col, text=FIELD_LABELS[col], command=lambda c=col: self.sort_by(c, False))
            self.tree.column(col, width=widths[col], anchor="center")
        yscroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        bottom = ttk.Frame(self, padding=(22, 0, 22, 16))
        bottom.pack(fill="x")
        ttk.Label(bottom, text=f"DB: {DB_PATH}", style="Muted.TLabel").pack(side="left")
        ttk.Label(bottom, text="ข้อมูลใช้เพื่อการศึกษาและสถิติย้อนหลัง ไม่รับประกันผลในอนาคต",
                  style="Muted.TLabel").pack(side="right")

    def metric_card(self, parent, caption, value):
        card = ttk.Frame(parent, style="Panel.TFrame", padding=13)
        card.pack(side="left", fill="x", expand=True, padx=(0, 10))
        val = ttk.Label(card, text=value, style="Metric.TLabel")
        val.pack(anchor="w")
        ttk.Label(card, text=caption, style="MetricCaption.TLabel").pack(anchor="w", pady=(3, 0))
        return val

    def set_status(self, message):
        self.status_var.set(message)

    def start_fetch(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("กำลังทำงาน", "กำลังดึงข้อมูลอยู่ กรุณารอให้เสร็จก่อน")
            return
        self.stop_event.clear()
        self.fetch_btn.configure(state="disabled")
        self.progress.start(10)
        self.progress_var.set(0)
        self.set_status("เริ่มดึงข้อมูลจากเว็บไซต์ ...")
        def worker_fn():
            try:
                result = fetch_all(lambda kind, value: self.events.put((kind, value)), self.stop_event)
                self.events.put(("done", result))
            except Exception as exc:
                self.events.put(("error", str(exc)))
        self.worker = threading.Thread(target=worker_fn, daemon=True)
        self.worker.start()

    def poll_events(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "status":
                    self.set_status(value)
                elif kind == "page":
                    page, count, total, note = value
                    self.set_status(f"หน้า {page}: พบ {count} แถว • รวมชั่วคราว {total} งวด • {note}")
                elif kind == "done":
                    self.progress.stop()
                    self.fetch_btn.configure(state="normal")
                    added, fetched, last_page, stopped = value
                    if stopped:
                        self.set_status("หยุดการดึงข้อมูลแล้ว")
                    else:
                        self.set_status(f"เสร็จสิ้น • อ่านได้ {fetched} งวด • เพิ่มใหม่ {added} งวด • หน้าสุดท้ายที่อ่าน {last_page}")
                        self.refresh_table()
                elif kind == "error":
                    self.progress.stop()
                    self.fetch_btn.configure(state="normal")
                    self.set_status("เกิดข้อผิดพลาด")
                    messagebox.showerror("ดึงข้อมูลไม่สำเร็จ", value)
        except queue.Empty:
            pass
        self.after(150, self.poll_events)

    def refresh_table(self):
        query = self.search_var.get().strip()
        with db_connect() as conn:
            if query:
                like = f"%{query}%"
                rows = conn.execute("""
                    SELECT draw_date, number6, number3_top, number2_top, number2_bottom
                    FROM draws_full
                    WHERE draw_date LIKE ? OR number6 LIKE ? OR number3_top LIKE ?
                       OR number2_top LIKE ? OR number2_bottom LIKE ?
                    ORDER BY substr(draw_date,7,4) DESC, substr(draw_date,4,2) DESC,
                             substr(draw_date,1,2) DESC LIMIT 1000
                """, (like, like, like, like, like)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT draw_date, number6, number3_top, number2_top, number2_bottom
                    FROM draws_full
                    ORDER BY substr(draw_date,7,4) DESC, substr(draw_date,4,2) DESC,
                             substr(draw_date,1,2) DESC LIMIT 1000
                """).fetchall()
            total = conn.execute("SELECT COUNT(*) FROM draws_full").fetchone()[0]
            all_rows = conn.execute("SELECT draw_date, number6, number3_top, number2_top, number2_bottom FROM draws_full").fetchall()
        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in rows:
            self.tree.insert("", "end", values=tuple(row))
        valid = sum(
            bool(re.fullmatch(r"\d{6}", str(r["number6"] or "")) and
                 re.fullmatch(r"\d{3}", str(r["number3_top"] or "")) and
                 re.fullmatch(r"\d{2}", str(r["number2_top"] or "")) and
                 re.fullmatch(r"\d{2}", str(r["number2_bottom"] or "")))
            for r in all_rows
        )
        dates = [r["draw_date"] for r in all_rows if r["draw_date"]]
        self.metric_total.configure(text=str(total))
        self.metric_oldest.configure(text=min(dates, key=thai_date_sort_key) if dates else "-")
        self.metric_latest.configure(text=max(dates, key=thai_date_sort_key) if dates else "-")
        self.metric_valid.configure(text=f"{valid}/{total}")
        self.set_status(f"แสดง {len(rows)} รายการจากฐานข้อมูล {total} งวด")

    def validate_data(self):
        with db_connect() as conn:
            rows = conn.execute("SELECT * FROM draws_full").fetchall()
        invalid = []
        for row in rows:
            problems = []
            if not re.fullmatch(r"\d{1,2}/\d{1,2}/25\d{2}", str(row["draw_date"] or "")):
                problems.append("วันที่")
            for key, pattern in (("number6", r"\d{6}"), ("number3_top", r"\d{3}"),
                                 ("number2_top", r"\d{2}"), ("number2_bottom", r"\d{2}")):
                if not re.fullmatch(pattern, str(row[key] or "")):
                    problems.append(key)
            if problems:
                invalid.append((row["draw_date"], ", ".join(problems)))
        if invalid:
            preview = "\n".join(f"{d}: {p}" for d, p in invalid[:20])
            messagebox.showwarning("พบข้อมูลต้องตรวจสอบ",
                                   f"พบ {len(invalid)} แถวที่รูปแบบไม่ผ่าน\n\n{preview}")
        else:
            messagebox.showinfo("ตรวจสอบแล้ว", f"ผ่านการตรวจรูปแบบทั้งหมด {len(rows)} งวด\nหมายเหตุ: ตรวจรูปแบบเท่านั้น ไม่ได้ยืนยันกับต้นทางทีละรายการ")

    def export_csv(self):
        target = filedialog.asksaveasfilename(
            title="ส่งออกข้อมูล CSV", defaultextension=".csv",
            initialfile="lao_lottery_full.csv",
            filetypes=[("CSV UTF-8", "*.csv"), ("All files", "*.*")]
        )
        if not target:
            return
        with db_connect() as conn:
            rows = conn.execute("""
                SELECT draw_date, number6, number3_top, number2_top, number2_bottom, source
                FROM draws_full
                ORDER BY substr(draw_date,7,4), substr(draw_date,4,2), substr(draw_date,1,2)
            """).fetchall()
        with open(target, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow([FIELD_LABELS[k] for k in FIELDS])
            writer.writerows([tuple(row) for row in rows])
        self.set_status(f"ส่งออกแล้ว: {target}")
        messagebox.showinfo("ส่งออกสำเร็จ", f"ส่งออก {len(rows)} งวด\n{target}")

    def sort_by(self, column, reverse):
        items = [(self.tree.set(k, column), k) for k in self.tree.get_children("")]
        if column == "draw_date":
            items.sort(key=lambda x: thai_date_sort_key(x[0]), reverse=reverse)
        else:
            items.sort(key=lambda x: x[0], reverse=reverse)
        for index, (_, item) in enumerate(items):
            self.tree.move(item, "", index)
        self.tree.heading(column, command=lambda: self.sort_by(column, not reverse))

    def toggle_auto(self):
        if self.auto_job:
            self.after_cancel(self.auto_job)
            self.auto_job = None
        if self.auto_enabled.get():
            try:
                minutes = int(self.interval_minutes.get())
                if minutes < 1 or minutes > 10080:
                    raise ValueError
            except ValueError:
                self.auto_enabled.set(False)
                messagebox.showerror("ช่วงเวลาไม่ถูกต้อง", "กรอกช่วงเวลา 1 ถึง 10080 นาที")
                return
            self.set_status(f"เปิดอัปเดตอัตโนมัติทุก {minutes} นาที (ต้องเปิดโปรแกรมค้างไว้)")
            self.schedule_auto()
        else:
            self.set_status("ปิดอัปเดตอัตโนมัติ")

    def schedule_auto(self):
        try:
            minutes = int(self.interval_minutes.get())
            if minutes < 1 or minutes > 10080:
                raise ValueError
        except ValueError:
            self.auto_enabled.set(False)
            messagebox.showerror("ช่วงเวลาไม่ถูกต้อง", "กรอกช่วงเวลา 1 ถึง 10080 นาที")
            return
        self.auto_job = self.after(minutes * 60 * 1000, self.auto_tick)

    def auto_tick(self):
        self.auto_job = None
        if self.auto_enabled.get():
            if not (self.worker and self.worker.is_alive()):
                self.start_fetch()
            self.schedule_auto()

    def on_close(self):
        self.stop_event.set()
        if self.auto_job:
            try:
                self.after_cancel(self.auto_job)
            except tk.TclError:
                pass
        self.destroy()

if __name__ == "__main__":
    app = App()
    app.mainloop()
