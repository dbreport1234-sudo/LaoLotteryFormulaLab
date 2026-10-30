# Lao Lottery Formula Lab v2

ระบบวิเคราะห์ผลสลากลาว + เว็บ GitHub Pages ที่อัปเดตเอง แสดง **เลขเด่นงวดหน้า**, **ตารางแพ้ชนะ**, **สถิติย้อนหลังเทียบการสุ่ม** และ **คำทายจริงที่ล็อกไว้ก่อนผลออก**

> ผลสลากเป็นการสุ่ม ทุกเลขมีโอกาสเท่ากัน ระบบนี้ **ไม่รับประกันผล** และไม่ได้ทำให้ถูกบ่อยขึ้นเกินการสุ่ม
> สิ่งที่ระบบทำคือวัดอย่างตรงไปตรงมาว่าสูตรไหนชนะสุ่มจริงหรือไม่ (ผลทดสอบ 897 งวด: ยังไม่มีสูตรใดชนะ)

## เปิดเว็บบน GitHub (ทำครั้งเดียว)
1. สร้าง repo ใหม่บน GitHub แล้ว push โฟลเดอร์นี้ขึ้นไป (branch `main`)
2. **Settings → Pages → Build and deployment → Source: Deploy from a branch → Branch: `main` / folder: `/docs`**
3. **Settings → Actions → General → Workflow permissions → Read and write permissions**
4. แท็บ **Actions → Lao Lottery Formula Lab → Run workflow** เพื่อรันครั้งแรก
5. เว็บอยู่ที่ `https://<ชื่อผู้ใช้>.github.io/<ชื่อ repo>/`

หลังจากนั้น GitHub Actions รันเองทุกวัน 07:15 / 21:45 / 23:30 น. (เวลาไทย): ดึงผล → เทียบแพ้ชนะ → ล็อกคำทายงวดถัดไป → สร้างเว็บใหม่

## ไฟล์สำคัญ
| ไฟล์ | หน้าที่ |
|---|---|
| `formula_engine.py` | เอนจิน 12 สูตร + walk-forward + p-value (ไม่พึ่ง scipy) |
| `thaiorc_import.py` | ดึงผลจาก thaiorc (แก้วันที่ พ.ศ. → ค.ศ. แล้ว) |
| `make_prediction.py` | ล็อกคำทายงวดหน้า (timestamp + SHA-256 ไม่เขียนทับ) |
| `check_results.py` | เทียบคำทายที่ล็อกกับผลจริง → `data/prediction_results.csv` |
| `build_site.py` + `site/template.html` | สร้าง `docs/index.html` |
| `config.json` | จำนวนเลขที่เลือก, หน้าต่างทดสอบ, **อัตราจ่าย (ค่าสมมติ ต้องแก้ให้ตรงจริง)** |
| `tests/` | เทสต์ว่าไม่มีการแอบดูอนาคต (รันทุกครั้งใน Actions) |
| `app.py`, `lao_lottery_ui.py` | แดชบอร์ด Flask / UI เดสก์ท็อปเดิม (ใช้ต่อได้) |

## วิธีที่ทำให้ตัวเลขน่าเชื่อถือ
- **Walk-forward**: ทายแต่ละงวดด้วยข้อมูลก่อนงวดนั้นเท่านั้น
- **สูตรควบคุม `random`** + แถบ ±2σ ให้เห็นว่าผลที่ดูดีอยู่ในความผันผวนปกติของการสุ่มหรือไม่
- **Bonferroni**: ค่า p คูณจำนวนการทดสอบทั้งหมด (31) กันการเลือกสูตรที่บังเอิญสวย
- **สูตรหลักกำหนดล่วงหน้า** (`adaptive`) ไม่เปลี่ยนตามผลย้อนหลัง
- **Live record**: คำทายถูกล็อกในไฟล์ `data/predictions/YYYY-MM-DD.json` และถูก commit ลง Git ก่อนผลออก ประวัติ Git คือหลักฐานเวลาที่แก้ไม่ได้ ถ้า push หลังเวลาตัดรอบ (20:00 น.) ให้ลบไฟล์คำทายงวดนั้นทิ้ง ไม่เช่นนั้นจะนับเป็นคำทายก่อนผลออกทั้งที่ไม่ใช่

## รันในเครื่อง
```bash
pip install -r requirements.txt
python thaiorc_import.py --pages 100   # อัปเดตข้อมูล
python check_results.py && python make_prediction.py && python build_site.py
python -m unittest discover -s tests -v
python app.py                          # แดชบอร์ด Flask ที่ http://127.0.0.1:5000
```

## หมายเหตุ
- ข้อมูลตรวจเฉพาะรูปแบบและความสอดคล้อง ไม่ได้ยืนยันว่าตรงกับผลทางการทุกงวด
- ตัวดึงข้อมูลพึ่งโครงสร้างตารางของ thaiorc ถ้าเว็บเปลี่ยนต้องแก้ `parse_page`
- เพื่อความบันเทิงและการศึกษา ไม่ใช่คำแนะนำทางการเงิน
