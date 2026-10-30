// App JavaScript
const $ = (id) => document.getElementById(id);

async function api(url, options = {}) {
  const res = await fetch(url, options);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function message(id, text, bad = false) {
  const el = $(id);
  el.textContent = text;
  el.className = "message " + (bad ? "error" : "success");
}

async function loadSummary() {
  const s = await api("/api/summary");
  $("count").textContent = s.count;
  $("first").textContent = s.first_date || "—";
  $("last").textContent = s.last_date || "—";

  const strategy = $("strategy");
  strategy.replaceChildren();
  Object.entries(s.strategies).forEach(([key, label]) => {
    const opt = document.createElement("option");
    opt.value = key;
    opt.textContent = `${label} (${key})`;
    strategy.appendChild(opt);
  });
}

async function loadDraws() {
  const data = await api("/api/draws?limit=100");
  const body = $("drawsBody");
  body.replaceChildren();

  data.forEach((r) => {
    const tr = document.createElement("tr");
    [r.draw_date, r.number6, r.number3_top, r.number2_top,
      r.number2_bottom, r.source].forEach((value) => {
      const td = document.createElement("td");
      td.textContent = value || "—";
      tr.appendChild(td);
    });
    body.appendChild(tr);
  });
}

$("drawForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const data = Object.fromEntries(new FormData(event.currentTarget));
    await api("/api/draw", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(data),
    });
    message("drawMessage", "บันทึกข้อมูลแล้ว");
    await loadSummary();
    await loadDraws();
  } catch (e) {
    message("drawMessage", e.message, true);
  }
});

$("importForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const data = await api("/api/import", {
      method: "POST",
      body: new FormData(event.currentTarget),
    });
    message("importMessage",
      `นำเข้าสำเร็จ เพิ่ม ${data.added} แถว รวม ${data.total} แถว`
      + (data.rejected?.length ? ` | ไม่ผ่านตรวจสอบ ${data.rejected.length} แถว` : ""));
    await loadSummary();
    await loadDraws();
  } catch (e) {
    message("importMessage", e.message, true);
  }
});

$("predictBtn").addEventListener("click", async () => {
  $("prediction").replaceChildren();
  try {
    const params = new URLSearchParams({
      kind: $("kind").value,
      strategy: $("strategy").value,
      picks: $("picks").value,
    });
    const data = await api("/api/predict?" + params);
    $("predictionInfo").textContent =
      `ข้อมูลถึง ${data.data_through} · ${data.note}`;
    data.picks.forEach((item, i) => {
      const box = document.createElement("div");
      box.className = "number-card";
      const number = document.createElement("strong");
      number.textContent = item.number;
      const rank = document.createElement("span");
      rank.textContent = `อันดับ ${i + 1}`;
      const score = document.createElement("small");
      score.textContent = `คะแนน ${item.score}`;
      box.append(number, rank, score);
      $("prediction").appendChild(box);
    });
  } catch (e) {
    $("predictionInfo").textContent = e.message;
  }
});

$("backtestBtn").addEventListener("click", async () => {
  $("backtestBody").replaceChildren();
  message("backtestMessage", "กำลังทดสอบ อาจใช้เวลาสักครู่...");
  try {
    const params = new URLSearchParams({
      kind: $("kind").value,
      tests: $("tests").value,
      picks: $("testPicks").value,
    });
    const data = await api("/api/backtest?" + params);
    data.forEach((r, i) => {
      const tr = document.createElement("tr");
      const values = [
        i + 1, `${r.name} (${r.strategy})`, r.hits, r.misses,
        r.tests, `${r.hit_pct}%`, `${r.random_pct}%`
      ];
      values.forEach((v) => {
        const td = document.createElement("td");
        td.textContent = v;
        tr.appendChild(td);
      });
      $("backtestBody").appendChild(tr);
    });
    message("backtestMessage", `เสร็จแล้ว ${data.length} สูตร`);
  } catch (e) {
    message("backtestMessage", e.message, true);
  }
});

(async function init() {
  try {
    await loadSummary();
    await loadDraws();
  } catch (e) {
    console.error(e);
    message("drawMessage", "โหลดข้อมูลไม่สำเร็จ: " + e.message, true);
  }
})();