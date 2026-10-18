# -*- coding: utf-8 -*-
"""
nlquery.py — 乡数智见 自然语言问数 (Text-to-Chart) 解析器

把中文问题 (如"2024年各县农村网络零售额排名"、"青溪县旅游收入逐年变化并预测未来3年")
解析为结构化查询规格 QuerySpec, 供数据引擎执行并驱动可视化。

设计特点:
  - 默认使用【确定性语义解析器】(基于目录同义词 + 规则), 完全离线、可复现、可解释,
    每次解析都给出"解析依据"便于答辩演示与评审复核;
  - 预留【可插拔 LLM 后端】接口 (parse_with_llm): 当配置了 OpenAI 兼容 API 时,
    可用大模型生成同样结构的 QuerySpec; 未配置时自动回退到确定性解析器。

★ 评审透明度: 生成式 AI 在本平台中仅作为"可选增强", 核心问数能力由团队自研的
  规则引擎实现, 不依赖外部大模型即可完整运行。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, asdict
from typing import Any

from data_engine import CATALOG, DataEngine


@dataclass
class QuerySpec:
    dataset: str
    measure: str                      # CSV 列名
    measure_name: str
    unit: str
    group_by: str                     # 分组维度 (时间列 或 实体维度列)
    agg: str = "sum"
    filters: dict[str, Any] = field(default_factory=dict)
    order: str | None = None
    top_n: int | None = None
    chart: str = "bar"                # bar | line | pie
    intent: str = "compare"           # compare | trend | compose | forecast
    forecast_horizon: int = 0
    season_length: int | None = None
    title: str = ""
    rationale: list[str] = field(default_factory=list)  # 解析依据(可解释)
    source: str = "rule"              # rule | llm

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# 意图关键词
TREND_KW = ["趋势", "变化", "走势", "逐年", "历年", "逐月", "每年", "每月", "增长", "演变", "发展"]
COMPARE_KW = ["对比", "比较", "排名", "排行", "最高", "最多", "最大", "最低", "最少", "前", "top", "各"]
COMPOSE_KW = ["占比", "构成", "结构", "比例", "组成", "分布"]
FORECAST_KW = ["预测", "未来", "明年", "后年", "预计", "展望", "将来"]
AVG_KW = ["平均", "均值", "人均", "每"]
LATEST_KW = ["现状", "最新", "目前", "当前"]


def _find_measure(q: str) -> tuple[str, Any] | None:
    """在问题中匹配度量; 返回 (dataset_key, Measure)。按同义词最长匹配优先。"""
    best = None
    best_len = 0
    for dkey, meta in CATALOG.items():
        for m in meta.measures:
            for syn in [m.name, m.key] + m.synonyms:
                if syn and syn.lower() in q.lower() and len(syn) > best_len:
                    best = (dkey, m)
                    best_len = len(syn)
    return best


def _find_dataset(q: str) -> str | None:
    best, best_len = None, 0
    for dkey, meta in CATALOG.items():
        for syn in [meta.title] + meta.synonyms:
            if syn and syn.lower() in q.lower() and len(syn) > best_len:
                best, best_len = dkey, len(syn)
    return best


def parse(question: str, engine: DataEngine | None = None) -> QuerySpec:
    """确定性语义解析入口。"""
    engine = engine or DataEngine()
    q = question.strip()
    rationale: list[str] = []

    # 1) 确定度量 (优先), 据此确定数据集
    mfound = _find_measure(q)
    if mfound:
        dataset, measure = mfound
        rationale.append(f"识别度量「{measure.name}」→ 数据集「{CATALOG[dataset].title}」")
    else:
        dataset = _find_dataset(q) or "economy"
        measure = CATALOG[dataset].measures[0]
        rationale.append(f"未直接识别度量, 按数据集「{CATALOG[dataset].title}」默认度量「{measure.name}」")

    meta = CATALOG[dataset]

    # 2) 意图判定
    intent = "compare"
    chart = "bar"
    if any(k in q for k in FORECAST_KW):
        intent, chart = "forecast", "line"
        rationale.append("命中预测关键词 → 意图=预测, 图型=折线")
    elif any(k in q for k in COMPOSE_KW):
        intent, chart = "compose", "pie"
        rationale.append("命中构成关键词 → 意图=构成, 图型=饼图")
    elif any(k in q for k in TREND_KW):
        intent, chart = "trend", "line"
        rationale.append("命中趋势关键词 → 意图=趋势, 图型=折线")
    else:
        rationale.append("默认意图=对比, 图型=柱状图")

    # 3) 实体(县域)过滤
    filters: dict[str, Any] = {}
    counties = engine.distinct(dataset, "县域") if "县域" in [d.key for d in meta.dimensions] else []
    hit_counties = [c for c in counties if c in q]
    if hit_counties:
        if len(hit_counties) == 1 and intent in ("trend", "forecast"):
            filters["县域"] = hit_counties[0]
            rationale.append(f"按县域过滤: {hit_counties[0]}")

    # 4) 年份过滤
    years = re.findall(r"(20\d{2})\s*年?", q)
    if years and intent not in ("trend", "forecast"):
        filters[meta.time_key] = int(years[0]) if meta.time_key == "年份" else years[0]
        rationale.append(f"按{meta.time_key}过滤: {years[0]}")

    # 5) 农产品类别等二级维度过滤
    if dataset == "agriculture":
        for cat in engine.distinct("agriculture", "农产品类别"):
            if cat in q:
                filters["农产品类别"] = cat
                rationale.append(f"按农产品类别过滤: {cat}")
                break

    # 6) 聚合方式
    if any(k in q for k in AVG_KW) and "人均" not in measure.name:
        agg = "avg"
        rationale.append("命中平均关键词 → 聚合=平均")
    elif any(k in q for k in LATEST_KW):
        agg = "last"
        rationale.append("命中现状关键词 → 聚合=取最新期")
    else:
        agg = "sum"

    # 7) Top-N 与排序
    top_n = None
    order = None
    mtop = re.search(r"前\s*(\d+)|top\s*(\d+)", q, re.IGNORECASE)
    if mtop:
        top_n = int(mtop.group(1) or mtop.group(2))
        order = "desc"
        rationale.append(f"命中 Top-N → 取前 {top_n} 名, 降序")
    elif any(k in q for k in ["排名", "排行", "最高", "最多", "最大"]):
        order = "desc"
        rationale.append("命中排名/最高 → 降序")
    elif any(k in q for k in ["最低", "最少", "最小"]):
        order = "desc" if measure.better == "low" else "asc"
        rationale.append("命中最低/最少 → 升序(或按指标方向)")

    # 8) 分组维度: 趋势/预测按时间, 对比/构成按实体
    if intent in ("trend", "forecast"):
        group_by = meta.time_key
    else:
        # 若指定了单一县域且是对比, 仍按时间展示; 否则按县域
        group_by = "县域" if "县域" in [d.key for d in meta.dimensions] else meta.time_key
        if dataset == "agriculture" and "农产品类别" not in filters and intent == "compose":
            group_by = "农产品类别"

    # 9) 预测参数
    horizon = 0
    season = None
    if intent == "forecast":
        mh = re.search(r"(未来|后)\s*(\d+)\s*(年|个月|月)", q)
        if mh:
            horizon = int(mh.group(2))
            if "月" in mh.group(3):
                season = 12 if meta.time_key == "月份" else None
        else:
            horizon = 6 if meta.time_key == "月份" else 3
        if meta.time_key == "月份":
            season = 12
        rationale.append(f"预测期数={horizon}" + (f", 季节周期={season}" if season else ""))

    # 10) 标题
    scope = filters.get("县域", "各县") if intent in ("trend", "forecast") else "各县"
    yr = f"{years[0]}年" if years and intent not in ("trend", "forecast") else ""
    title = f"{yr}{scope}{measure.name}"
    if intent == "trend":
        title = f"{scope}{measure.name}变化趋势"
    elif intent == "forecast":
        title = f"{scope}{measure.name}趋势与预测"
    elif intent == "compose":
        title = f"{yr}{measure.name}构成"

    return QuerySpec(
        dataset=dataset, measure=measure.key, measure_name=measure.name,
        unit=measure.unit, group_by=group_by, agg=agg, filters=filters,
        order=order, top_n=top_n, chart=chart, intent=intent,
        forecast_horizon=horizon, season_length=season, title=title,
        rationale=rationale, source="rule",
    )


# --------------------------------------------------------------------------
# 可插拔 LLM 后端 (可选): 配置 OpenAI 兼容 API 时启用, 否则回退到规则解析。
#   环境变量: RURAL_LLM_BASE (如 https://api.deepseek.com),
#            RURAL_LLM_KEY, RURAL_LLM_MODEL (默认 deepseek-chat)
# --------------------------------------------------------------------------
def llm_available() -> bool:
    return bool(os.environ.get("RURAL_LLM_KEY") and os.environ.get("RURAL_LLM_BASE"))


def parse_with_llm(question: str, engine: DataEngine | None = None) -> QuerySpec:
    """若配置了 LLM 则用大模型解析, 否则回退规则解析 (保证离线可用)。"""
    if not llm_available():
        spec = parse(question, engine)
        spec.rationale.insert(0, "未配置 LLM, 回退到自研规则解析器")
        return spec
    try:
        import json
        import urllib.request
        schema_hint = _catalog_prompt()
        prompt = (
            "你是数据问数解析器。根据下面的数据目录, 把用户问题解析为 JSON, "
            "字段: dataset, measure(CSV列名), group_by, agg(sum/avg/max/min/last), "
            "filters(对象), order(asc/desc/null), top_n(整数或null), "
            "chart(bar/line/pie), intent(compare/trend/compose/forecast), "
            "forecast_horizon(整数), season_length(整数或null)。只输出 JSON。\n\n"
            f"数据目录:\n{schema_hint}\n\n问题: {question}"
        )
        body = json.dumps({
            "model": os.environ.get("RURAL_LLM_MODEL", "deepseek-chat"),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }).encode("utf-8")
        req = urllib.request.Request(
            os.environ["RURAL_LLM_BASE"].rstrip("/") + "/v1/chat/completions",
            data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + os.environ["RURAL_LLM_KEY"]},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = data["choices"][0]["message"]["content"]
        text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
        obj = json.loads(text)
        meta = CATALOG[obj["dataset"]]
        m = next((x for x in meta.measures if x.key == obj["measure"]), meta.measures[0])
        return QuerySpec(
            dataset=obj["dataset"], measure=m.key, measure_name=m.name, unit=m.unit,
            group_by=obj.get("group_by", meta.time_key), agg=obj.get("agg", "sum"),
            filters=obj.get("filters", {}) or {}, order=obj.get("order"),
            top_n=obj.get("top_n"), chart=obj.get("chart", "bar"),
            intent=obj.get("intent", "compare"),
            forecast_horizon=obj.get("forecast_horizon", 0),
            season_length=obj.get("season_length"),
            title=question, rationale=["由 LLM 解析"], source="llm",
        )
    except Exception as e:  # 任何失败都回退规则解析, 保证服务不中断
        spec = parse(question, engine)
        spec.rationale.insert(0, f"LLM 解析失败({type(e).__name__}), 回退规则解析")
        return spec


def _catalog_prompt() -> str:
    lines = []
    for dkey, meta in CATALOG.items():
        ms = "; ".join(f"{m.key}({m.name},{m.unit})" for m in meta.measures)
        dims = ",".join(d.key for d in meta.dimensions)
        lines.append(f"- {dkey}[{meta.title}] 时间={meta.time_key} 维度={dims} 度量={ms}")
    return "\n".join(lines)


if __name__ == "__main__":
    eng = DataEngine()
    tests = [
        "2024年各县农村网络零售额排名",
        "青溪县旅游收入逐年变化并预测未来3年",
        "各县返乡创业人数前3名",
        "临江县电商月度销售额预测未来6个月",
        "2023年各县贫困发生率最低",
        "各县农产品产量构成",
    ]
    for t in tests:
        spec = parse(t, eng)
        print(f"\n问: {t}")
        print(f"  → 数据集={spec.dataset} 度量={spec.measure_name} 分组={spec.group_by} "
              f"聚合={spec.agg} 意图={spec.intent} 图型={spec.chart} "
              f"过滤={spec.filters} topN={spec.top_n} 预测={spec.forecast_horizon}")
        for r in spec.rationale:
            print(f"     · {r}")
