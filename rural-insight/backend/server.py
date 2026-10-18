# -*- coding: utf-8 -*-
"""
server.py — 乡声 · 乡村文化 AI 导览 HTTP 服务 (Python 标准库 http.server, 无第三方依赖)

启动:  python backend/server.py  [--port 8000]
访问:  http://127.0.0.1:8000/

路由:
  GET  /                      → 乡声 AI 导览产品页 (web/index.html + app.css + guide.js, 唯一前端入口)
  GET  /dashboard.html        → 遗留县域数据看板 (非产品入口, 保留供直连参考)
  GET  /<静态资源>            → web/ 下的静态文件
  GET  /api/catalog           → 数据目录 (维度/度量/量纲)
  GET  /api/overview          → 首页概览 (若干预置指标卡 + 图)
  GET  /api/examples          → 推荐示例问题
  POST /api/ask {question}    → 自然语言问数: 返回图表数据 + 叙事 + 解析依据
  GET  /api/ask?q=...         → 同上 (便于浏览器/命令行测试)
  --- 乡声 · 乡村文化 AI 导览 ---
  GET  /api/guide/meta        → 导览产品元信息 (村落/主题/声明/风格/审核汇总)
  GET/POST /api/guide/ask     → 检索增强问答 (带引用, 资料不足则拒答)
  GET  /api/guide/explain     → 分龄/研学/双语讲解改写 (保留原文对照)
  GET  /api/guide/pois        → 点位列表 + 有序导览路线
  GET  /api/guide/narration   → 导览叙事脚本 (供浏览器 Web Speech API 播报)
  GET  /api/guide/kb          → 知识库全量条目 + 人工审核台 + 版本记录
  GET  /api/guide/eval        → 可复现评估面板 (引用命中/拒答正确率/响应时间)

安全说明: 本服务默认仅监听 127.0.0.1 (本机回环), 不对外暴露, 无需鉴权;
若需部署到公网, 应另加反向代理与访问控制 (见 docs/README)。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_engine import DataEngine, CATALOG
from nlquery import parse, parse_with_llm, llm_available
from forecast import forecast
from narrative import narrate_compare, narrate_trend, llm_polish
from rural_index import compute_index
from insights import compute_insights
from world_bank import build_scenario, load_series as load_world_bank_series
from guide import (answer as guide_answer, explain as guide_explain,
                   narration as guide_narration, STYLES as GUIDE_STYLES,
                   llm_available as guide_llm_available)
from kb import get_kb
from evaluation import run_eval

WEB_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "web"))
DATA_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data"))
ENGINE = DataEngine()

# 可在县域地图上着色的指标 (friendly 下拉项); key=index 表示综合评价指数
MAP_MEASURES = [
    {"key": "index", "dataset": "", "name": "乡村振兴综合指数", "unit": "分"},
    {"key": "农村居民人均可支配收入_元", "dataset": "economy", "name": "农村居民人均可支配收入", "unit": "元"},
    {"key": "农村网络零售额_万元", "dataset": "digital", "name": "农村网络零售额", "unit": "万元"},
    {"key": "旅游综合收入_万元", "dataset": "tourism", "name": "旅游综合收入", "unit": "万元"},
    {"key": "返乡创业人数_人", "dataset": "population", "name": "返乡创业人数", "unit": "人"},
    {"key": "森林覆盖率_百分比", "dataset": "ecology", "name": "森林覆盖率", "unit": "%"},
    {"key": "村级集体经济收入_万元", "dataset": "governance", "name": "村级集体经济收入", "unit": "万元"},
]

MIME = {
    ".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
    ".geojson": "application/json; charset=utf-8",
}

EXAMPLES = [
    "2024年各县农村网络零售额排名",
    "青溪县旅游综合收入逐年变化并预测未来3年",
    "各县返乡创业人数前3名",
    "临江县电商月度销售额预测未来6个月",
    "各县农产品产量构成",
    "各县森林覆盖率现状对比",
    "各县村级集体经济收入排名",
    "丰禾县平安乡村达标率变化趋势",
]

# 乡声 · AI 文化导览 示例问题 (覆盖可作答与应拒答两类, 便于演示拒答机制)
GUIDE_EXAMPLES = [
    "青溪竹编的历史是怎样的？",
    "竹编是怎么做出来的？有哪些工序？",
    "青溪古廊桥是什么结构？",
    "竹编器物应该怎么保养？",
    "导览路线应该怎么走？大概要多久？",
    "青溪村的常住人口有多少万？",   # 资料不足 → 应拒答
]


def build_answer(question: str, use_llm: bool = False) -> dict:
    """核心: 问题 → 规格 → 查询/预测 → 叙事 → 组装前端 payload。"""
    spec = (parse_with_llm if use_llm else parse)(question, ENGINE)
    chart: dict = {"type": spec.chart, "title": spec.title, "unit": spec.unit}
    narrative: dict = {}

    if spec.intent in ("trend", "forecast"):
        entity = spec.filters.get("县域")
        labels, values = ENGINE.series(spec.dataset, spec.measure, entity=entity)
        series = [{"name": f"{spec.measure_name}(历史)", "data": values}]
        x = list(labels)
        fc = None
        if spec.intent == "forecast" and spec.forecast_horizon > 0:
            fc = forecast(labels, values, horizon=spec.forecast_horizon,
                          season_length=spec.season_length)
            # 预测段: 前面用 None 占位, 使折线从历史末端接续
            pad = [None] * (len(values) - 1)
            series.append({
                "name": f"{spec.measure_name}(预测)",
                "data": pad + [values[-1]] + fc["forecast"],
                "dashed": True,
            })
            x = list(labels) + list(fc["future_labels"])
        chart.update(x=x, series=series)
        narrative = narrate_trend(spec, labels, values, fc)
    else:
        rows = ENGINE.query(spec.dataset, spec.measure, spec.group_by, agg=spec.agg,
                            filters=spec.filters, order=spec.order, top_n=spec.top_n)
        chart.update(
            x=[r["key"] for r in rows],
            series=[{"name": spec.measure_name, "data": [r["value"] for r in rows]}],
            pie=[{"name": r["key"], "value": r["value"]} for r in rows],
        )
        narrative = narrate_compare(spec, rows)

    if use_llm and narrative.get("text"):
        narrative["text"] = llm_polish(narrative["text"], narrative.get("facts", []))

    return {
        "question": question,
        "spec": spec.to_dict(),
        "chart": chart,
        "narrative": narrative,
        "llm_used": bool(use_llm and llm_available()),
    }


def build_overview() -> dict:
    """首页概览: 关键指标卡 (2024) + 一张趋势图。"""
    cards = []
    # 2024 汇总指标
    def total(ds, measure, year=2024):
        rows = ENGINE.query(ds, measure, "县域", agg="sum", filters={"年份": year})
        return round(sum(r["value"] for r in rows), 1)

    def avg(ds, measure, year=2024):
        rows = ENGINE.query(ds, measure, "县域", agg="sum", filters={"年份": year})
        return round(sum(r["value"] for r in rows) / len(rows), 1) if rows else 0

    cards.append({"label": "示例县数量", "value": len(ENGINE.distinct("economy", "县域")), "unit": "个"})
    cards.append({"label": "2024 农村网络零售额(合计)", "value": total("digital", "农村网络零售额_万元"), "unit": "万元"})
    cards.append({"label": "2024 返乡创业(合计)", "value": total("population", "返乡创业人数_人"), "unit": "人"})
    cards.append({"label": "2024 农村居民人均可支配收入(均值)", "value": avg("economy", "农村居民人均可支配收入_元"), "unit": "元"})
    cards.append({"label": "2024 森林覆盖率(均值)", "value": avg("ecology", "森林覆盖率_百分比"), "unit": "%"})
    cards.append({"label": "2024 游客量(合计)", "value": total("tourism", "游客量_万人次"), "unit": "万人次"})

    labels, values = ENGINE.series("digital", "农村网络零售额_万元", entity=None)
    overview_chart = {
        "type": "line", "title": "全部示例县 农村网络零售额合计 (年度)",
        "unit": "万元", "x": list(labels),
        "series": [{"name": "网络零售额合计", "data": values}],
    }
    return {"cards": cards, "chart": overview_chart,
            "categories": sorted(set(m.category for m in CATALOG.values()))
            if hasattr(next(iter(CATALOG.values())), "category") else []}


def build_map(measure_key: str, dataset: str, year: int | None) -> dict:
    """返回县域地图 choropleth 所需的 {县: 值} 及值域、单位。
    measure_key == 'index' 时用综合评价指数着色。"""
    years = [y for y in ENGINE.distinct("economy", "年份") if isinstance(y, int)]
    year = year or (max(years) if years else 2024)
    meta = next((m for m in MAP_MEASURES if m["key"] == measure_key), MAP_MEASURES[0])

    if measure_key == "index":
        idx = compute_index(ENGINE, year=year)
        data = [{"name": r["county"], "value": r["score"]} for r in idx["ranking"]]
        name, unit = meta["name"], meta["unit"]
    else:
        ds = dataset or meta["dataset"]
        rows = ENGINE.query(ds, measure_key, "县域", agg="sum", filters={"年份": year})
        data = [{"name": r["key"], "value": r["value"]} for r in rows]
        name, unit = meta["name"], meta["unit"]

    vals = [d["value"] for d in data if isinstance(d["value"], (int, float))]
    return {
        "measure": measure_key, "measure_name": name, "unit": unit, "year": year,
        "min": round(min(vals), 2) if vals else 0,
        "max": round(max(vals), 2) if vals else 0,
        "data": data,
        "options": MAP_MEASURES,
        "years": years,
    }


def build_index(year: int | None) -> dict:
    """综合评价指数: 为前端补充 radar 维度轴信息。"""
    res = compute_index(ENGINE, year=year)
    res["radar_indicator"] = [{"name": d, "max": 100} for d in res["dimensions"]]
    res["years"] = [y for y in ENGINE.distinct("economy", "年份") if isinstance(y, int)]
    return res


def build_insights() -> dict:
    return {"insights": compute_insights(ENGINE)}


def build_world_bank_context() -> dict:
    rows = load_world_bank_series()
    return {"source": "World Bank, World Development Indicators (WDI)",
            "country": "China", "rows": rows,
            "indicators": {"rural_population": "SP.RUR.TOTL",
                           "rural_population_share_pct": "SP.RUR.TOTL.ZS",
                           "gdp_per_capita_current_usd": "NY.GDP.PCAP.CD"}}


# --------------------------------------------------------------------------
# 乡声 · 乡村文化 AI 导览 (检索增强问答 / 讲解改写 / 点位导览 / 评估)
# --------------------------------------------------------------------------
def build_guide_meta() -> dict:
    """导览产品的元信息: 村落/主题/声明 + 风格 + 来源分布 + 审核汇总。"""
    kb = get_kb()
    review = kb.review_summary()
    return {
        "meta": kb.meta,
        "styles": GUIDE_STYLES,
        "source_types": kb.source_types(),
        "review_by_status": review["by_status"],
        "entry_count": len(kb),
        "poi_count": len(kb.pois),
        "examples": GUIDE_EXAMPLES,
        "llm_available": guide_llm_available(),
    }


def build_guide_pois() -> dict:
    """点位列表 (含关联资料标题与引用) + 有序路线详情。"""
    kb = get_kb()
    return {"pois": kb.pois_with_entries(), "route": kb.route_detail()}


def build_guide_kb() -> dict:
    """知识库全量条目 + 人工审核台 + 来源类型分布 + 版本记录。"""
    kb = get_kb()
    return {
        "entries": [e.to_dict() for e in kb.all_entries()],
        "review": kb.review_summary(),
        "source_types": kb.source_types(),
        "meta": kb.meta,
    }


_EVAL_CACHE: dict | None = None


def build_guide_eval(force: bool = False) -> dict:
    """可复现评估面板 (离线确定性, 结果缓存以免重复计算)。"""
    global _EVAL_CACHE
    if _EVAL_CACHE is None or force:
        _EVAL_CACHE = run_eval()
    return _EVAL_CACHE


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # 精简日志
        sys.stderr.write("  [%s] %s\n" % (self.address_string(), fmt % args))

    def _send_json(self, obj, status=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, relpath):
        safe = os.path.normpath(relpath).lstrip("/\\")
        path = os.path.join(WEB_DIR, safe)
        if not path.startswith(WEB_DIR) or not os.path.isfile(path):
            self.send_error(404, "Not Found")
            return
        ext = os.path.splitext(path)[1].lower()
        with open(path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_data_file(self, name):
        """从 data/ 目录安全地提供指定文件 (如 counties.geojson)。"""
        safe = os.path.basename(name)
        path = os.path.join(DATA_DIR, safe)
        if not os.path.isfile(path):
            self.send_error(404, "Not Found")
            return
        ext = os.path.splitext(path)[1].lower()
        with open(path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(ext, "application/json; charset=utf-8"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        path, qs = u.path, parse_qs(u.query)
        try:
            if path == "/" or path == "/index.html":
                self._send_file("index.html")
            elif path == "/api/catalog":
                self._send_json({"catalog": ENGINE.catalog_summary(),
                                 "llm_available": llm_available()})
            elif path == "/api/overview":
                self._send_json(build_overview())
            elif path == "/api/examples":
                self._send_json({"examples": EXAMPLES})
            elif path == "/api/index":
                yr = (qs.get("year") or [None])[0]
                self._send_json(build_index(int(yr) if yr else None))
            elif path == "/api/insights":
                self._send_json(build_insights())
            elif path == "/api/world-bank/context":
                self._send_json(build_world_bank_context())
            elif path == "/api/world-bank/scenario":
                raw_delta = (qs.get("delta_pp") or ["0"])[0]
                self._send_json(build_scenario(float(raw_delta)))
            elif path == "/api/map":
                mk = (qs.get("measure") or ["index"])[0]
                ds = (qs.get("dataset") or [""])[0]
                yr = (qs.get("year") or [None])[0]
                self._send_json(build_map(mk, ds, int(yr) if yr else None))
            elif path == "/api/geojson":
                self._send_data_file("counties.geojson")
            elif path == "/api/ask":
                q = (qs.get("q") or [""])[0]
                use_llm = (qs.get("llm") or ["0"])[0] in ("1", "true")
                if not q:
                    self._send_json({"error": "缺少参数 q"}, 400)
                else:
                    self._send_json(build_answer(q, use_llm))
            elif path == "/api/guide/meta":
                self._send_json(build_guide_meta())
            elif path == "/api/guide/pois":
                self._send_json(build_guide_pois())
            elif path == "/api/guide/narration":
                self._send_json(guide_narration())
            elif path == "/api/guide/kb":
                self._send_json(build_guide_kb())
            elif path == "/api/guide/eval":
                self._send_json(build_guide_eval())
            elif path == "/api/guide/explain":
                entry_id = (qs.get("entry_id") or [""])[0]
                style = (qs.get("style") or ["normal"])[0]
                use_llm = (qs.get("llm") or ["0"])[0] in ("1", "true")
                if not entry_id:
                    self._send_json({"error": "缺少参数 entry_id"}, 400)
                else:
                    self._send_json(guide_explain(entry_id, style=style, use_llm=use_llm))
            elif path == "/api/guide/ask":
                q = (qs.get("q") or [""])[0]
                style = (qs.get("style") or ["normal"])[0]
                use_llm = (qs.get("llm") or ["0"])[0] in ("1", "true")
                if not q:
                    self._send_json({"error": "缺少参数 q"}, 400)
                else:
                    self._send_json(guide_answer(q, style=style, use_llm=use_llm))
            else:
                self._send_file(path)
        except Exception as e:
            self._send_json({"error": f"{type(e).__name__}: {e}"}, 500)

    def do_POST(self):
        u = urlparse(self.path)
        if u.path not in ("/api/ask", "/api/guide/ask"):
            self.send_error(404, "Not Found")
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            q = (body.get("question") or "").strip()
            use_llm = bool(body.get("use_llm"))
            if not q:
                self._send_json({"error": "缺少字段 question"}, 400)
                return
            if u.path == "/api/guide/ask":
                style = body.get("style") or "normal"
                self._send_json(guide_answer(q, style=style, use_llm=use_llm))
            else:
                self._send_json(build_answer(q, use_llm))
        except Exception as e:
            self._send_json({"error": f"{type(e).__name__}: {e}"}, 500)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    kb = get_kb()
    print(f"乡声 · 乡村文化 AI 导览 服务已启动: http://{args.host}:{args.port}/")
    print(f"  知识库: {kb.meta.get('village','')} · {kb.meta.get('theme','')}; "
          f"条目 {len(kb)} 条, 点位 {len(kb.pois)} 个")
    print(f"  产品入口（唯一）: http://{args.host}:{args.port}/")
    print(f"  LLM 增强: {'已配置' if guide_llm_available() else '未配置(走自研检索/规则引擎)'}；遗留数据看板(非产品) /dashboard.html 仍可直连")
    print("  按 Ctrl+C 停止。")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
        srv.server_close()


if __name__ == "__main__":
    main()
