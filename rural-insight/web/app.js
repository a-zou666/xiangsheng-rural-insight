/* 乡数智见 前端逻辑 (原生 JS + ECharts, 无框架依赖) */
"use strict";

const GREEN = "#2e7d4f", GREEN2 = "#8bc1a0", GOLD = "#c8914b";
const PALETTE = ["#2e7d4f", "#c8914b", "#4a90d9", "#8bc1a0", "#e07b53", "#9b7cc8"];

let overviewChart = null, resultChart = null, mapChart = null, radarChart = null, worldBankChart = null;
let geoReady = false;

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = "请求失败: " + r.status;
    try { const j = await r.json(); if (j.error) msg = j.error; } catch (e) {}
    throw new Error(msg);
  }
  return r.json();
}

function el(tag, cls, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html != null) e.innerHTML = html;
  return e;
}

function fmtNum(v) {
  if (v == null) return "-";
  if (typeof v !== "number") return v;
  return v.toLocaleString("zh-CN", { maximumFractionDigits: 1 });
}

/* ---------- 概览 ---------- */
async function loadOverview() {
  const data = await api("/api/overview");
  const box = document.getElementById("cards");
  box.innerHTML = "";
  data.cards.forEach(c => {
    const card = el("div", "card");
    card.appendChild(el("div", "v", `${fmtNum(c.value)}<span class="u">${c.unit || ""}</span>`));
    card.appendChild(el("div", "l", c.label));
    box.appendChild(card);
  });
  overviewChart = echarts.init(document.getElementById("overviewChart"));
  overviewChart.setOption(lineOption(data.chart));
}

/* ---------- 目录 ---------- */
async function loadCatalog() {
  const data = await api("/api/catalog");
  const badge = document.getElementById("llmBadge");
  if (data.llm_available) { badge.textContent = "AI增强: 已配置"; badge.className = "badge badge-on"; }
  const box = document.getElementById("catalog");
  box.innerHTML = "";
  data.catalog.forEach(d => {
    const card = el("div", "cat-card");
    const head = el("div", "cat-head");
    head.appendChild(el("h4", null, d.title));
    head.appendChild(el("span", "cat-tag", d.category));
    card.appendChild(head);
    card.appendChild(el("div", "meta", `时间：${d.time} ｜ 维度：${d.dimensions.join("、")} ｜ ${d.rows} 行`));
    const ms = el("div", "ms");
    d.measures.forEach(m => ms.appendChild(el("span", null, `${m.name}(${m.unit})`)));
    card.appendChild(ms);
    box.appendChild(card);
  });
}

/* ---------- 县域地图 + 综合评价指数 ---------- */
async function loadMapAndIndex() {
  // GeoJSON 注册
  try {
    const geo = await api("/api/geojson");
    echarts.registerMap("counties", geo);
    geoReady = true;
  } catch (e) { console.warn("地图加载失败", e); }

  mapChart = echarts.init(document.getElementById("mapChart"));
  radarChart = echarts.init(document.getElementById("radarChart"));

  const sel = document.getElementById("mapMeasure");
  const yearSel = document.getElementById("mapYear");
  sel.onchange = refreshMap;
  yearSel.onchange = () => { refreshMap(); refreshIndex(); };

  await refreshMap(true);
  await refreshIndex();
}

async function refreshMap(initOptions) {
  const sel = document.getElementById("mapMeasure");
  const yearSel = document.getElementById("mapYear");
  const measure = sel.value || "index";
  const year = yearSel.value || "";
  const d = await api(`/api/map?measure=${encodeURIComponent(measure)}&year=${year}`);

  if (initOptions) {
    sel.innerHTML = "";
    d.options.forEach(o => {
      const op = el("option"); op.value = o.key; op.textContent = o.name; sel.appendChild(op);
    });
    sel.value = measure;
    yearSel.innerHTML = "";
    d.years.forEach(y => { const op = el("option"); op.value = y; op.textContent = y; yearSel.appendChild(op); });
    yearSel.value = d.year;
  }

  const opt = {
    title: { text: `${d.measure_name} · ${d.year}`, left: "center",
             textStyle: { fontSize: 14, color: "#223027" } },
    tooltip: { trigger: "item",
      formatter: p => `${p.name}<br/>${d.measure_name}: ${p.value == null ? "-" : fmtNum(p.value)}${d.unit}` },
    visualMap: {
      min: d.min, max: d.max, left: "left", bottom: 10,
      text: ["高", "低"], calculable: true,
      inRange: { color: ["#eaf4ec", "#8bc1a0", "#2e7d4f"] },
    },
    series: [{
      type: "map", map: "counties", roam: false,
      label: { show: true, fontSize: 11, color: "#223027" },
      itemStyle: { borderColor: "#fff", borderWidth: 1.4 },
      emphasis: { itemStyle: { areaColor: GOLD }, label: { color: "#fff" } },
      data: d.data,
    }],
  };
  if (geoReady) mapChart.setOption(opt, true);
  else mapChart.setOption({ title: { text: "（地图数据未就绪）", left: "center" } });
}

async function refreshIndex() {
  const yearSel = document.getElementById("mapYear");
  const year = yearSel.value || "";
  const d = await api(`/api/index?year=${year}`);

  // 雷达图: 展示前三名县域的五维得分
  const top = d.ranking.slice(0, 3);
  radarChart.setOption({
    title: { text: `五大振兴维度得分 · ${d.year}`, left: "center",
             textStyle: { fontSize: 14, color: "#223027" } },
    tooltip: {},
    legend: { bottom: 0, data: top.map(r => r.county) },
    radar: { indicator: d.radar_indicator, radius: "62%",
             axisName: { color: "#4a5a50", fontSize: 11 } },
    series: [{
      type: "radar", data: top.map((r, i) => ({
        name: r.county,
        value: d.dimensions.map(dim => r.dimensions[dim]),
        lineStyle: { width: 2, color: PALETTE[i] },
        areaStyle: { opacity: 0.12, color: PALETTE[i] },
        itemStyle: { color: PALETTE[i] },
      })),
    }],
  }, true);

  // 排名列表
  const rl = document.getElementById("rankList");
  rl.innerHTML = "";
  const maxScore = d.ranking[0] ? d.ranking[0].score : 100;
  d.ranking.forEach(r => {
    const li = el("li", "rank-item");
    li.innerHTML = `<span class="rk">${r.rank}</span>` +
      `<span class="rc">${r.county}</span>` +
      `<span class="rbar"><i style="width:${(r.score / maxScore * 100).toFixed(0)}%"></i></span>` +
      `<span class="rv">${r.score}</span>`;
    rl.appendChild(li);
  });
  document.getElementById("idxNote").textContent = `（${d.method} · ${d.year}）`;
  document.getElementById("idxMethod").textContent = d.note;

  // 权重表
  const wt = document.getElementById("weightTable");
  wt.innerHTML = "";
  d.indicators.forEach(ind => {
    const row = el("div", "wrow");
    row.innerHTML = `<span class="wd">${ind.dimension}</span>` +
      `<span class="wn">${ind.name}</span>` +
      `<span class="wk ${ind.direction === "成本型" ? "cost" : "benefit"}">${ind.direction}</span>` +
      `<span class="wbar"><i style="width:${(ind.weight * 100 / 0.12).toFixed(0)}%"></i></span>` +
      `<span class="wv">${(ind.weight * 100).toFixed(1)}%</span>`;
    wt.appendChild(row);
  });
}

/* ---------- World Bank real-data scenario ---------- */
async function loadWorldBankScenario() {
  const slider = document.getElementById("scenarioDelta");
  const label = document.getElementById("scenarioDeltaLabel");
  const refresh = async () => {
    const delta = Number(slider.value);
    label.textContent = `${delta > 0 ? "+" : ""}${delta.toFixed(2)} 个百分点/年`;
    const d = await api(`/api/world-bank/scenario?delta_pp=${encodeURIComponent(delta)}`);
    const series = [
      { name: "历史观测（农村人口占比）", type: "line", data: d.actual.map(x => [x.year, x.value]), symbolSize: 5, lineStyle: { width: 2.5 } },
      { name: "基准机械延伸", type: "line", data: d.baseline.map(x => [x.year, x.value]), symbol: "none", lineStyle: { type: "dashed", width: 2 } },
      { name: "交互情景", type: "line", data: d.scenario.map(x => [x.year, x.value]), symbol: "none", lineStyle: { width: 3, color: GOLD }, areaStyle: { opacity: 0.08, color: GOLD } },
    ];
    worldBankChart.setOption({
      color: [GREEN, "#6484a3", GOLD],
      tooltip: { trigger: "axis", valueFormatter: v => `${Number(v).toFixed(2)}%` },
      legend: { bottom: 0 }, grid: { left: 64, right: 28, top: 28, bottom: 64 },
      xAxis: { type: "value", min: 2015, max: 2030, interval: 1, axisLabel: { formatter: v => String(v) } },
      yAxis: { type: "value", name: "%", min: 25, max: 45 },
      series,
    }, true);
    document.getElementById("scenarioResult").textContent = `至 ${d.scenario.at(-1).year} 年，情景线较基准线相差 ${d.scenario_end_difference_pp > 0 ? "+" : ""}${d.scenario_end_difference_pp.toFixed(2)} 个百分点。`;
    document.getElementById("worldBankMethod").textContent = `${d.method_note} 观测指标：${d.indicator}（${d.indicator_code}），单位 ${d.unit}。`;
    const sourceBox = document.getElementById("worldBankSources");
    sourceBox.innerHTML = "";
    Object.entries(d.sources).forEach(([key, url]) => {
      const link = el("a", null, key);
      link.href = url; link.target = "_blank"; link.rel = "noreferrer";
      sourceBox.appendChild(link);
    });
  };
  worldBankChart = echarts.init(document.getElementById("worldBankChart"));
  slider.addEventListener("input", refresh);
  await refresh();
}

/* ---------- 智能洞察 ---------- */
async function loadInsights() {
  const d = await api("/api/insights");
  const box = document.getElementById("insights");
  box.innerHTML = "";
  d.insights.forEach(c => {
    const card = el("div", "insight-card insight-" + c.kind);
    const head = el("div", "insight-head");
    head.innerHTML = `<span class="ic">${c.icon}</span><h4>${c.title}</h4>`;
    card.appendChild(head);
    card.appendChild(el("p", "insight-text", c.text));
    const ev = el("div", "insight-evidence");
    (c.evidence || []).forEach(e => {
      ev.appendChild(el("span", "ev-chip", `${e.label}: <b>${fmtNum(e.value)}</b>`));
    });
    card.appendChild(ev);
    box.appendChild(card);
  });
}

/* ---------- 示例问题 ---------- */
async function loadExamples() {
  const data = await api("/api/examples");
  const box = document.getElementById("examples");
  box.innerHTML = "";
  data.examples.forEach(q => {
    const chip = el("span", "chip", q);
    chip.onclick = () => { document.getElementById("q").value = q; ask(); };
    box.appendChild(chip);
  });
}

/* ---------- 问数 ---------- */
async function ask() {
  const q = document.getElementById("q").value.trim();
  if (!q) return;
  const btn = document.getElementById("askBtn");
  const useLlm = document.getElementById("useLlm").checked;
  btn.disabled = true; btn.textContent = "分析中…";
  try {
    const data = await api("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q, use_llm: useLlm }),
    });
    renderResult(data);
  } catch (e) {
    alert("分析失败：" + e.message);
  } finally {
    btn.disabled = false; btn.textContent = "问数";
  }
}

function renderResult(data) {
  document.getElementById("resultPanel").style.display = "block";
  document.getElementById("resultTitle").textContent = "分析结果 · " + (data.chart.title || data.question);

  if (!resultChart) resultChart = echarts.init(document.getElementById("resultChart"));
  const c = data.chart;
  let opt;
  if (c.type === "line") opt = lineOption(c);
  else if (c.type === "pie") opt = pieOption(c);
  else opt = barOption(c);
  resultChart.setOption(opt, true);

  document.getElementById("narrativeText").textContent = data.narrative.text || "";
  const fl = document.getElementById("factsList");
  fl.innerHTML = "";
  (data.narrative.facts || []).forEach(f => fl.appendChild(el("li", null, f)));

  const rl = document.getElementById("rationaleList");
  rl.innerHTML = "";
  (data.spec.rationale || []).forEach(r => rl.appendChild(el("li", null, r)));
  document.getElementById("srcTag").textContent =
    data.llm_used ? "（AI增强解析）" : "（规则解析）";

  document.getElementById("resultPanel").scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ---------- ECharts 配置 ---------- */
function baseGrid() { return { left: 60, right: 24, top: 50, bottom: 60 }; }

function barOption(c) {
  const s = c.series[0];
  return {
    color: PALETTE,
    title: { text: c.title, left: "center", textStyle: { fontSize: 15, color: "#223027" } },
    tooltip: { trigger: "axis", valueFormatter: v => fmtNum(v) + (c.unit || "") },
    grid: baseGrid(),
    xAxis: { type: "category", data: c.x, axisLabel: { interval: 0, rotate: c.x.length > 6 ? 25 : 0 } },
    yAxis: { type: "value", name: c.unit || "" },
    series: [{
      name: s.name, type: "bar", data: s.data, barMaxWidth: 46,
      itemStyle: { borderRadius: [6, 6, 0, 0], color: new echarts.graphic.LinearGradient(0, 0, 0, 1,
        [{ offset: 0, color: GREEN2 }, { offset: 1, color: GREEN }]) },
      label: { show: c.x.length <= 8, position: "top", formatter: p => fmtNum(p.value), fontSize: 11 },
    }],
  };
}

function lineOption(c) {
  const series = c.series.map((s, i) => ({
    name: s.name, type: "line", data: s.data, smooth: true, connectNulls: false,
    symbol: "circle", symbolSize: 6,
    lineStyle: s.dashed ? { type: "dashed", width: 2.5, color: GOLD } : { width: 2.5 },
    itemStyle: s.dashed ? { color: GOLD } : { color: PALETTE[i % PALETTE.length] },
    areaStyle: (!s.dashed && c.series.length === 1) ? {
      color: new echarts.graphic.LinearGradient(0, 0, 0, 1,
        [{ offset: 0, color: "rgba(46,125,79,0.25)" }, { offset: 1, color: "rgba(46,125,79,0.02)" }]) } : null,
  }));
  return {
    color: PALETTE,
    title: { text: c.title, left: "center", textStyle: { fontSize: 15, color: "#223027" } },
    tooltip: { trigger: "axis", valueFormatter: v => v == null ? "-" : fmtNum(v) + (c.unit || "") },
    legend: { bottom: 0, data: c.series.map(s => s.name) },
    grid: baseGrid(),
    xAxis: { type: "category", boundaryGap: false, data: c.x,
      axisLabel: { interval: c.x.length > 14 ? "auto" : 0, rotate: c.x.length > 10 ? 30 : 0 } },
    yAxis: { type: "value", name: c.unit || "" },
    series,
  };
}

function pieOption(c) {
  return {
    color: PALETTE,
    title: { text: c.title, left: "center", textStyle: { fontSize: 15, color: "#223027" } },
    tooltip: { trigger: "item", formatter: p => `${p.name}<br/>${fmtNum(p.value)}${c.unit || ""} (${p.percent}%)` },
    legend: { bottom: 0 },
    series: [{
      type: "pie", radius: ["38%", "66%"], center: ["50%", "48%"],
      data: c.pie, avoidLabelOverlap: true,
      itemStyle: { borderRadius: 6, borderColor: "#fff", borderWidth: 2 },
      label: { formatter: "{b}\n{d}%", fontSize: 12 },
    }],
  };
}

/* ---------- 启动 ---------- */
window.addEventListener("resize", () => {
  if (overviewChart) overviewChart.resize();
  if (resultChart) resultChart.resize();
  if (mapChart) mapChart.resize();
  if (radarChart) radarChart.resize();
  if (worldBankChart) worldBankChart.resize();
});
document.getElementById("askBtn").onclick = ask;
document.getElementById("q").addEventListener("keydown", e => { if (e.key === "Enter") ask(); });

(async function init() {
  try {
    const results = await Promise.allSettled([loadOverview(), loadCatalog(), loadExamples(),
      loadMapAndIndex(), loadInsights(), loadWorldBankScenario()]);
    const failure = results.find(r => r.status === "rejected");
    if (failure) {
      console.error(failure.reason);
      if (!worldBankChart) document.getElementById("worldBankChart").textContent = "真实数据情景暂不可用，请检查数据文件与服务日志。";
      if (results.some((r, i) => i < 5 && r.status === "rejected")) throw failure.reason;
    }
  } catch (e) {
    console.error(e);
    alert("初始化失败：" + e.message + "\n请确认后端服务已启动。");
  }
})();
