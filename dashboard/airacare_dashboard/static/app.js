"use strict";

// AiraCare dashboard front-end. One fetch to /api/dashboard drives the whole page; Chart.js
// (CDN) renders the four pitch visuals. All data is privacy-scrubbed and off the safety path.

const COLORS = {
  trend: "#4cc9f0",
  fit: "#f4a261",
  routine: "#3a6ea5",
  wander: "#e63946",
  med: "#f4a261",
  meal: "#62b6cb",
  fall: "#b5179e",
  cloud: "#4cc9f0",
  edge: "#7b8aa5",
  night: "#e63946",
};
const LEVEL_COLORS = { L0: "#3a6ea5", L1: "#62b6cb", L2: "#f4a261", L3: "#e63946" };

const charts = {};

function el(id) {
  return document.getElementById(id);
}

function showError(msg) {
  const box = el("error");
  box.textContent = msg;
  box.classList.remove("hidden");
}

function fmtDate(iso) {
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function kpiCard(label, value, sub, cls) {
  return `<div class="kpi ${cls || ""}"><div class="label">${label}</div>` +
    `<div class="value">${value}</div><div class="sub">${sub || ""}</div></div>`;
}

function renderKpis(s) {
  const trendCls = "trend-" + s.trend_direction;
  const slope = s.trend_slope_per_week;
  const slopeTxt = (slope > 0 ? "+" : "") + slope.toFixed(3) + " / wk";
  const trendCardCls = s.trend_direction === "declining" ? "alert"
    : s.trend_direction === "improving" ? "good" : "";
  el("kpis").innerHTML = [
    kpiCard("Events filed", s.event_count, `${s.window.start || "—"} → ${s.window.end || "—"}`),
    kpiCard("Cognitive trend",
      `<span class="trend-pill ${trendCls}">${s.trend_direction}</span>`,
      `${slopeTxt} · latest ${s.latest_score ?? "—"}`, trendCardCls),
    kpiCard("Nighttime risk", s.nighttime_risk, "wander · night · door open", s.nighttime_risk ? "warn" : "good"),
    kpiCard("L3 escalations", s.escalations, "reached emergency ladder", s.escalations ? "alert" : "good"),
    kpiCard("Cloud refinements", s.refined_count, "grade differed from edge"),
  ].join("");
}

function renderPatient(s) {
  el("patient-name").textContent = s.patient_name;
  el("disease-stage").textContent = s.disease_stage + " stage";
  el("backend-label").textContent = s.backend + " store";
  el("backend-dot").className = "dot" + (s.backend === "cosmos" ? " cosmos" : "");
}

function destroy(name) {
  if (charts[name]) { charts[name].destroy(); delete charts[name]; }
}

function baseOpts(extra) {
  return Object.assign({
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { labels: { color: "#93a1b8", boxWidth: 12, font: { size: 11 } } },
    },
    scales: {
      x: { ticks: { color: "#93a1b8", font: { size: 11 } }, grid: { color: "#263248" } },
      y: { ticks: { color: "#93a1b8", font: { size: 11 } }, grid: { color: "#263248" }, beginAtZero: true },
    },
  }, extra || {});
}

function renderTrend(t) {
  el("trend-summary").textContent = t.summary || "";
  const labels = t.points.map((p) => fmtDate(p.t));
  const n = t.points.length;
  const fit = new Array(n).fill(null);
  if (t.fit.length === 2 && n >= 2) { fit[0] = t.fit[0].y; fit[n - 1] = t.fit[1].y; }
  destroy("trend");
  charts.trend = new Chart(el("trend-chart"), {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: "Voice-biomarker index", data: t.points.map((p) => p.y), borderColor: COLORS.trend,
          backgroundColor: "rgba(76,201,240,0.12)", tension: 0.25, pointRadius: 2, fill: true },
        { label: "Trend line", data: fit, borderColor: COLORS.fit, borderDash: [6, 5],
          pointRadius: 0, spanGaps: true, fill: false },
      ],
    },
    options: baseOpts({ scales: { x: { ticks: { color: "#93a1b8", maxTicksLimit: 8, font: { size: 10 } },
      grid: { color: "#263248" } }, y: { min: 0, max: 1, ticks: { color: "#93a1b8" }, grid: { color: "#263248" } } } }),
  });
}

function renderMix(m) {
  destroy("mix");
  charts.mix = new Chart(el("mix-chart"), {
    type: "bar",
    data: {
      labels: m.weeks,
      datasets: m.types.map((t) => ({ label: t, data: m.counts[t], backgroundColor: COLORS[t] || "#888" })),
    },
    options: baseOpts({ scales: {
      x: { stacked: true, ticks: { color: "#93a1b8" }, grid: { color: "#263248" } },
      y: { stacked: true, beginAtZero: true, ticks: { color: "#93a1b8", precision: 0 }, grid: { color: "#263248" } },
    } }),
  });
}

function renderFunnel(f) {
  destroy("funnel");
  charts.funnel = new Chart(el("funnel-chart"), {
    type: "bar",
    data: {
      labels: f.levels,
      datasets: [
        { label: "Cloud considered", data: f.cloud, backgroundColor: f.levels.map((l) => LEVEL_COLORS[l]) },
        { label: "Edge assessed", data: f.edge, backgroundColor: "rgba(123,138,165,0.55)" },
      ],
    },
    options: baseOpts({ scales: {
      x: { ticks: { color: "#93a1b8" }, grid: { color: "#263248" } },
      y: { beginAtZero: true, ticks: { color: "#93a1b8", precision: 0 }, grid: { color: "#263248" } },
    } }),
  });
}

function renderNight(nt) {
  destroy("night");
  charts.night = new Chart(el("night-chart"), {
    type: "bar",
    data: { labels: nt.weeks, datasets: [{ label: "Nighttime wanders", data: nt.counts, backgroundColor: COLORS.night }] },
    options: baseOpts({ scales: {
      x: { ticks: { color: "#93a1b8" }, grid: { color: "#263248" } },
      y: { beginAtZero: true, ticks: { color: "#93a1b8", precision: 0 }, grid: { color: "#263248" } },
    } }),
  });
}

function briefingBlock(title, b) {
  const highlights = (b.highlights || []).map((h) => `<li>${h}</li>`).join("");
  return `<h3>${title} — ${b.period}</h3><p>${b.summary}</p>` +
    (highlights ? `<ul>${highlights}</ul>` : "");
}

function renderBriefings(b) {
  el("briefing-family").innerHTML = briefingBlock("Family daily", b.family);
  el("briefing-clinician").innerHTML = briefingBlock("Clinician monthly", b.clinician);
}

function renderEvents(rows) {
  const cols = [
    ["timestamp", "When"], ["type", "Type"], ["considered_level", "Cloud"],
    ["edge_assessed_level", "Edge"], ["baseline_deviation", "Deviation"],
    ["biomarker", "Biomarker"], ["time_of_day", "Time"], ["door_open", "Door"], ["response", "Response"],
  ];
  const head = "<tr>" + cols.map((c) => `<th>${c[1]}</th>`).join("") + "</tr>";
  const body = rows.map((r) => "<tr>" + cols.map(([k]) => {
    let v = r[k];
    if (k === "timestamp") v = fmtDate(v);
    if (k === "considered_level" || k === "edge_assessed_level") return `<td><span class="badge ${v}">${v}</span></td>`;
    return `<td>${v}</td>`;
  }).join("") + "</tr>").join("");
  el("events-table").innerHTML = head + body;
}

async function load() {
  let data;
  try {
    const res = await fetch("/api/dashboard");
    if (!res.ok) throw new Error("HTTP " + res.status);
    data = await res.json();
  } catch (e) {
    showError("Failed to load dashboard data: " + e.message);
    return;
  }
  renderPatient(data.summary);
  renderKpis(data.summary);
  renderBriefings(data.briefings);
  renderEvents(data.events);
  if (typeof Chart === "undefined") {
    showError("Charts unavailable (Chart.js CDN blocked). Tables and KPIs still work offline.");
    return;
  }
  renderTrend(data.trend);
  renderMix(data.event_mix);
  renderFunnel(data.funnel);
  renderNight(data.nighttime);
}

load();
