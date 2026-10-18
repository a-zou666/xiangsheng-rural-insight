/* 乡声 · 青溪村文化导览 — 单一游览流程前端 (原生 JS, 无框架)
   流程：选择点位 → 收听/查看合适讲解版本 → 向导览提问（带引用或明确拒答）。
   语音用浏览器 Web Speech API 本地合成，默认不联网。 */
"use strict";

const TTS = window.speechSynthesis || null;

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
function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function svgEl(name, attrs) {
  const e = document.createElementNS("http://www.w3.org/2000/svg", name);
  Object.entries(attrs || {}).forEach(([k, v]) => e.setAttribute(k, v));
  return e;
}

let META = null, STYLES = {}, EXAMPLES = [];
let POIS = [], ROUTE = null;
let CUR_POI = null, CUR_ENTRY = null, CUR_STYLE = "normal";

/* ---------- 元信息 ---------- */
async function loadMeta() {
  META = await api("/api/guide/meta");
  STYLES = META.styles || { normal: "普通版" };
  EXAMPLES = META.examples || [];
  const badge = document.getElementById("llmBadge");
  if (META.llm_available) { badge.textContent = "AI 接地改写: 已配置"; badge.classList.add("on"); }
  else { badge.textContent = "检索式导览 · 离线"; }

  const tabs = document.getElementById("styleTabs");
  tabs.innerHTML = "";
  Object.entries(STYLES).forEach(([k, name]) => {
    const b = el("button", "style-tab" + (k === "normal" ? " active" : ""), esc(name));
    b.dataset.style = k;
    b.setAttribute("role", "tab");
    b.onclick = () => { CUR_STYLE = k; markTabs(); refreshGuide(); };
    tabs.appendChild(b);
  });
}
function markTabs() {
  document.querySelectorAll("#styleTabs .style-tab").forEach(b =>
    b.classList.toggle("active", b.dataset.style === CUR_STYLE));
}

/* ---------- 点位地图 + 列表 ---------- */
async function loadPois() {
  const d = await api("/api/guide/pois");
  POIS = (d.pois || []).slice().sort((a, b) => (a.order || 0) - (b.order || 0));
  ROUTE = d.route || null;
  renderMap();
  renderStopList();
  if (POIS.length) selectStop(POIS[0]);
}

function renderMap() {
  const svg = document.getElementById("guideMap");
  svg.innerHTML = "";
  // 溪流示意
  svg.appendChild(svgEl("path", {
    class: "map-stream",
    d: "M 6 94 Q 30 78 40 60 T 66 34 Q 78 22 96 10",
  }));
  // 导览路线（按 order 连线）
  if (POIS.length > 1) {
    const dd = POIS.map((p, i) => `${i ? "L" : "M"} ${p.x} ${p.y}`).join(" ");
    svg.appendChild(svgEl("path", { class: "map-route", d: dd }));
  }
  // 点位标记
  POIS.forEach(p => {
    const g = svgEl("g", { class: "map-pin", "data-id": p.id, tabindex: "0", role: "button" });
    g.setAttribute("aria-label", p.name);
    const dot = svgEl("circle", { class: "pin-dot", cx: p.x, cy: p.y, r: 3.6 });
    const num = svgEl("text", { class: "pin-num", x: p.x, y: p.y });
    num.textContent = p.order || "";
    const label = svgEl("text", { class: "pin-label", x: p.x, y: p.y - 5.3 });
    label.textContent = p.name;
    g.appendChild(dot); g.appendChild(num); g.appendChild(label);
    const pick = () => selectStop(p);
    g.addEventListener("click", pick);
    g.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
    svg.appendChild(g);
  });
}
function markMap() {
  document.querySelectorAll("#guideMap .map-pin").forEach(g =>
    g.classList.toggle("active", CUR_POI && g.getAttribute("data-id") === CUR_POI.id));
}

function renderStopList() {
  const ul = document.getElementById("stopList");
  ul.innerHTML = "";
  POIS.forEach(p => {
    const li = el("button", "stop-item");
    li.dataset.id = p.id;
    li.innerHTML = `<span class="ord">${p.order || "·"}</span>` +
      `<span><span class="nm">${esc(p.name)}</span>` +
      (p.intro ? ` <span class="ds">· ${esc(p.intro)}</span>` : "") + `</span>`;
    li.onclick = () => selectStop(p);
    ul.appendChild(li);
  });
}
function markList() {
  document.querySelectorAll("#stopList .stop-item").forEach(li =>
    li.classList.toggle("active", CUR_POI && li.dataset.id === CUR_POI.id));
}

/* ---------- 选中点位 ---------- */
function selectStop(poi) {
  CUR_POI = poi;
  CUR_ENTRY = poi.entry_id;
  markMap(); markList();
  document.getElementById("stopName").textContent = poi.name || "";
  document.getElementById("stopTag").textContent = "第 " + (poi.order || "?") + " 站";
  document.getElementById("stopIntro").textContent = poi.intro || "";
  // 情境化示例问题
  const chips = document.getElementById("askChips");
  chips.innerHTML = "";
  EXAMPLES.forEach(q => {
    const c = el("button", "chip", esc(q));
    c.onclick = () => { document.getElementById("q").value = q; ask(); };
    chips.appendChild(c);
  });
  // 收起上一次回答
  const ab = document.getElementById("answerBox");
  ab.style.display = "none"; ab.innerHTML = "";
  if (TTS) TTS.cancel();
  refreshGuide();
}

/* ---------- 讲解版本 (分龄/研学/双语) ---------- */
async function refreshGuide() {
  if (!CUR_ENTRY) return;
  const gt = document.getElementById("guideText");
  gt.textContent = "讲解生成中…";
  try {
    const d = await api(`/api/guide/explain?entry_id=${encodeURIComponent(CUR_ENTRY)}&style=${encodeURIComponent(CUR_STYLE)}`);
    gt.textContent = d.rewritten || "";
    document.getElementById("origText").textContent = d.original || "";
    document.getElementById("aiNote").textContent = d.ai_notice || "";
    const c = d.citation || {};
    document.getElementById("guideCite").innerHTML = c.source_name
      ? `来源：${esc(c.source_name)}` +
        (c.source_type ? `　<span class="cite-type">${esc(c.source_type)}</span>` : "") +
        (c.review_status ? `　审核：${esc(c.review_status)}` : "")
      : "";
  } catch (e) { gt.textContent = "讲解加载失败：" + e.message; }
}

/* ---------- 语音 ---------- */
function speak(text) {
  if (!TTS || !text) return;
  TTS.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "zh-CN"; u.rate = 1.0;
  TTS.speak(u);
}

/* ---------- 提问 (接地问答) ---------- */
async function ask() {
  const q = document.getElementById("q").value.trim();
  if (!q) return;
  const btn = document.getElementById("askBtn");
  btn.disabled = true; btn.textContent = "检索中…";
  try {
    const d = await api("/api/guide/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q, style: CUR_STYLE, use_llm: document.getElementById("useLlm").checked }),
    });
    renderAnswer(d);
  } catch (e) { alert("提问失败：" + e.message); }
  finally { btn.disabled = false; btn.textContent = "提问"; }
}

function renderAnswer(d) {
  const box = document.getElementById("answerBox");
  box.style.display = "block";
  box.className = "answer " + (d.refused ? "refuse" : "ok");
  const a = d.assessment || {};
  const src = d.source === "llm" ? "外部模型接地改写" : "确定性检索组装";

  let html = "";
  if (d.refused) {
    html += `<div class="status">⛔ 资料不足 · 不作答　<small>${esc(d.refusal_reason || "")}</small></div>`;
  } else {
    html += `<div class="status">✅ 基于带来源资料作答　<small>${esc(src)} · ${esc(STYLES[d.style] || d.style || "")}</small></div>`;
  }
  html += `<p class="atext">${esc(d.answer || "")}</p>`;
  const topScore = (a.top_score != null && a.top_score.toFixed) ? a.top_score.toFixed(2) : (a.top_score != null ? a.top_score : "-");
  html += `<div class="conf">` +
    `<span>置信度 <b>${d.confidence != null ? d.confidence : 0}</b></span>` +
    `<span>检索最高分 <b>${topScore}</b></span>` +
    `<span>主题覆盖率 <b>${a.answerability != null ? a.answerability : "-"}</b></span>` +
    `<span>用时 <b>${d.elapsed_ms != null ? d.elapsed_ms : "-"}ms</b></span></div>`;

  if ((d.citations || []).length) {
    html += `<ol class="cites">`;
    d.citations.forEach(c => {
      html += `<li><span class="t">${esc(c.title)}</span>` +
        `<div class="m">来源：${esc(c.source_name)}` +
        (c.source_type ? `　<span class="cite-type">${esc(c.source_type)}</span>` : "") +
        (c.review_status ? `　审核：${esc(c.review_status)}` : "") + `</div></li>`;
    });
    html += `</ol>`;
  }

  if ((d.retrieval || []).length || a.thresholds) {
    const th = a.thresholds || {};
    html += `<details class="retr"><summary>检索过程与充分性判定（可复核）</summary>`;
    html += `<p style="margin:8px 0;color:var(--muted);">判定阈值：最高分 ≥ ${th.min_top_score != null ? th.min_top_score : "?"}，覆盖率 ≥ ${th.min_answerability != null ? th.min_answerability : "?"}；命中主题词 [${esc((a.covered_terms || []).join(" "))}]，缺失 [${esc((a.missing_terms || []).join(" "))}]。</p>`;
    (d.retrieval || []).forEach(h => {
      html += `<div class="retr-row"><span class="s">${h.score}</span>` +
        `<span><b>${esc(h.title)}</b> <span style="color:var(--muted);">命中：${esc((h.matched_terms || []).slice(0, 6).join(" "))}</span></span></div>`;
    });
    html += `</details>`;
  }
  if (d.disclaimer) html += `<p class="adisc">${esc(d.disclaimer)}</p>`;
  box.innerHTML = html;
}

/* ---------- 次级：来源审核 / 评估 ---------- */
async function loadKb() {
  const kb = await api("/api/guide/kb");
  document.getElementById("kbDisclosure").textContent =
    (kb.meta && kb.meta.disclaimer) ? kb.meta.disclaimer : "";
  const review = kb.review || {};
  const stats = document.getElementById("kbStats");
  stats.innerHTML = "";
  const chip = (l, v) => el("span", "stat-chip", `${esc(l)}<b>${v}</b>`);
  stats.appendChild(chip("条目 ", review.total || 0));
  Object.entries(review.by_status || {}).forEach(([k, v]) => stats.appendChild(chip("审核·" + k + " ", v)));
  Object.entries(kb.source_types || {}).forEach(([k, v]) => stats.appendChild(chip(k + " ", v)));

  const tb = document.getElementById("kbTableBody");
  tb.innerHTML = "";
  (review.rows || []).forEach(r => {
    const tr = el("tr");
    tr.innerHTML = `<td>${esc(r.title)}</td><td>${esc(r.source_type || "")}</td>` +
      `<td><span class="st-badge ${esc(r.status)}">${esc(r.status)}</span></td>` +
      `<td>${esc(r.reviewer || "")}${r.note ? "：" + esc(r.note) : ""}</td><td>${esc(r.version || "")}</td>`;
    tb.appendChild(tr);
  });
  const vl = document.getElementById("versions");
  vl.innerHTML = "";
  (review.versions || []).forEach(v =>
    vl.appendChild(el("li", null, `<b>v${esc(v.version)}</b>（${esc(v.date)}，${esc(v.author)}）：${esc(v.change)}`)));
}

async function loadEval() {
  const d = await api("/api/guide/eval");
  const s = d.summary || {};
  document.getElementById("evalNote").textContent =
    `${s.note || ""}（应作答 ${s.answer_cases} 题 / 应拒答 ${s.refuse_cases} 题；平均响应 ${s.avg_latency_ms}ms，最大 ${s.max_latency_ms}ms）`;
  const cards = [
    ["作答准确率", s.answer_accuracy_pct, "%"], ["拒答准确率", s.refusal_accuracy_pct, "%"],
    ["引用命中率", s.citation_hit_rate_pct, "%"], ["关键词事实匹配", s.keyword_fact_match_pct, "%"],
    ["题目总数", s.total_questions, "题"],
  ];
  const box = document.getElementById("evalCards");
  box.innerHTML = "";
  cards.forEach(([l, v, u]) => {
    const c = el("div", "eval-card");
    c.innerHTML = `<div class="v">${v == null ? "-" : v}<span class="u">${u}</span></div><div class="l">${l}</div>`;
    box.appendChild(c);
  });
  const tb = document.getElementById("evalRows");
  tb.innerHTML = "";
  (d.rows || []).forEach(r => {
    const tr = el("tr");
    tr.innerHTML = `<td><span class="st-badge ${r.result === "ok" ? "ok" : "miss"}">${esc(r.result)}</span></td>` +
      `<td>${r.expect === "answer" ? "作答" : "拒答"}</td><td>${r.answered ? "是" : "否"}</td>` +
      `<td>${r.top_score}</td><td>${r.answerability}</td><td>${esc(r.q)}</td>`;
    tb.appendChild(tr);
  });
}

/* ---------- 启动 ---------- */
document.getElementById("askBtn").onclick = ask;
document.getElementById("q").addEventListener("keydown", e => { if (e.key === "Enter") ask(); });
document.getElementById("playBtn").onclick = () => speak(document.getElementById("guideText").textContent);
document.getElementById("stopBtn").onclick = () => { if (TTS) TTS.cancel(); };
window.addEventListener("beforeunload", () => { if (TTS) TTS.cancel(); });

(async function init() {
  try {
    await loadMeta();
    await loadPois();
    await Promise.allSettled([loadKb(), loadEval()]);
  } catch (e) {
    console.error(e);
    document.getElementById("stopName").textContent = "初始化失败";
    document.getElementById("stopIntro").textContent = "请确认后端服务已启动：" + e.message;
  }
})();
