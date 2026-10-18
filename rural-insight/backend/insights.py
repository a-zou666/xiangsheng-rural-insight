# -*- coding: utf-8 -*-
"""
insights.py — 自动洞察发现引擎 (纯 Python 标准库)

《乡数智见》原创分析能力之一: 无需用户提问, 自动扫描全部数据集, 用确定性统计
方法挖掘"值得关注的事实", 生成可核验的洞察卡片。覆盖四类发现:

  1. 相关洞察 (correlation): 皮尔逊相关系数, 揭示指标间联动(如宽带入户↔网络零售);
  2. 增长之星 (growth):   复合增长率(CAGR)扫描, 找出增长最快的县域指标;
  3. 区域差距 (disparity): 最新年份极值倍差, 量化县域不均衡;
  4. 异常拐点 (anomaly):   同比最大跌幅/突变, 定位冲击事件(如疫情对文旅)。

每张卡片都附"证据"(真实数值), 排序依据显著性(salience), 杜绝主观臆断。
"""
from __future__ import annotations

import math
from typing import Any


# ---- 基础统计 (手写, 不依赖 numpy) ----
def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    vy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if vx == 0 or vy == 0:
        return 0.0
    return cov / (vx * vy)


def _panel(engine, dataset: str, key: str) -> dict[tuple, float]:
    """返回 {(县域, 时间): 值} 面板, 便于跨数据集按(县,年)对齐。"""
    t = engine.tables[dataset]
    tk = t.meta.time_key
    out: dict[tuple, float] = {}
    for r in t.rows:
        c, y, v = r.get("县域"), r.get(tk), r.get(key)
        if c is not None and y is not None and isinstance(v, (int, float)):
            out[(c, y)] = v
    return out


def _cagr(values: list[float], periods: int) -> float | None:
    """复合年均增长率。首值<=0 或期数<=0 时返回 None。"""
    if periods <= 0 or not values or values[0] <= 0 or values[-1] <= 0:
        return None
    return (values[-1] / values[0]) ** (1.0 / periods) - 1.0


def _r_desc(r: float) -> str:
    a = abs(r)
    strength = "强" if a >= 0.8 else ("较强" if a >= 0.6 else "中等")
    return f"{'正' if r >= 0 else '负'}{strength}相关"


# ---- 四类检测器 ----
CORRELATION_PAIRS = [
    ("digital", "宽带入户率_百分比", "数字乡村", "digital", "农村网络零售额_万元", "电商零售"),
    ("digital", "物流到村覆盖率_百分比", "物流到村", "digital", "农村网络零售额_万元", "电商零售"),
    ("population", "返乡创业人数_人", "返乡创业", "governance", "村级集体经济收入_万元", "集体经济"),
    ("ecology", "森林覆盖率_百分比", "森林覆盖", "tourism", "旅游综合收入_万元", "旅游收入"),
    ("economy", "农村居民人均可支配收入_元", "农民收入", "population", "外出务工劳动力_人", "外出务工"),
]

GROWTH_MEASURES = [
    ("digital", "农村网络零售额_万元", "农村网络零售额"),
    ("tourism", "旅游综合收入_万元", "旅游综合收入"),
    ("population", "返乡创业人数_人", "返乡创业人数"),
    ("governance", "村级集体经济收入_万元", "村级集体经济收入"),
    ("economy", "农村居民人均可支配收入_元", "农村居民人均可支配收入"),
]

DISPARITY_MEASURES = [
    ("economy", "农村居民人均可支配收入_元", "农村居民人均可支配收入", "元"),
    ("digital", "农村网络零售额_万元", "农村网络零售额", "万元"),
    ("tourism", "旅游综合收入_万元", "旅游综合收入", "万元"),
]


def _detect_correlations(engine) -> list[dict]:
    cards = []
    for ds1, k1, n1, ds2, k2, n2 in CORRELATION_PAIRS:
        try:
            p1, p2 = _panel(engine, ds1, k1), _panel(engine, ds2, k2)
        except KeyError:
            continue
        keys = sorted(set(p1) & set(p2), key=str)
        if len(keys) < 3:
            continue
        xs = [p1[k] for k in keys]
        ys = [p2[k] for k in keys]
        r = _pearson(xs, ys)
        if abs(r) < 0.5:
            continue
        cards.append({
            "kind": "correlation", "icon": "🔗",
            "title": f"{n1} 与 {n2} 呈{_r_desc(r)}",
            "text": (f"基于 {len(keys)} 个「县域×年份」合成样本, {n1}与{n2}的皮尔逊相关系数 r={r:.2f}, "
                     f"呈{_r_desc(r)}。该统计关系不代表因果关系, 且仅反映本演示数据。"),
            "evidence": [{"label": "相关系数 r", "value": round(r, 3)},
                         {"label": "样本数", "value": len(keys)}],
            "salience": abs(r),
        })
    return cards


def _detect_growth(engine) -> list[dict]:
    best = None
    for ds, key, name in GROWTH_MEASURES:
        for c in engine.distinct(ds, "县域"):
            labels, values = engine.series(ds, key, entity=c)
            if len(values) < 3:
                continue
            g = _cagr(values, len(values) - 1)
            if g is None:
                continue
            if best is None or g > best["g"]:
                best = {"g": g, "ds": ds, "key": key, "name": name, "county": c,
                        "v0": values[0], "v1": values[-1],
                        "y0": labels[0], "y1": labels[-1]}
    if not best:
        return []
    return [{
        "kind": "growth", "icon": "🚀",
        "title": f"{best['county']}{best['name']} 增长领跑全域",
        "text": (f"{best['y0']}—{best['y1']}年, {best['county']}的{best['name']}由 {best['v0']:.0f} "
                 f"增长至 {best['v1']:.0f}, 年均复合增长率(CAGR)达 {best['g']*100:.1f}%, "
                 f"为全部县域各增长型指标中最高。"),
        "evidence": [{"label": "CAGR", "value": f"{best['g']*100:.1f}%"},
                     {"label": f"{best['y0']}", "value": round(best['v0'], 1)},
                     {"label": f"{best['y1']}", "value": round(best['v1'], 1)}],
        "salience": min(1.0, best["g"]),
    }]


def _detect_disparity(engine) -> list[dict]:
    years = [y for y in engine.distinct("economy", "年份") if isinstance(y, int)]
    year = max(years) if years else 2024
    best = None
    for ds, key, name, unit in DISPARITY_MEASURES:
        res = engine.query(ds, key, "县域", agg="sum", filters={"年份": year}, order="desc")
        vals = [r for r in res if isinstance(r["value"], (int, float)) and r["value"] > 0]
        if len(vals) < 2:
            continue
        hi, lo = vals[0], vals[-1]
        ratio = hi["value"] / lo["value"]
        if best is None or ratio > best["ratio"]:
            best = {"ratio": ratio, "name": name, "unit": unit, "year": year,
                    "hi": hi, "lo": lo}
    if not best:
        return []
    return [{
        "kind": "disparity", "icon": "⚖️",
        "title": f"{best['year']}年 {best['name']} 县域差距达 {best['ratio']:.1f} 倍",
        "text": (f"{best['year']}年, {best['name']}最高的{best['hi']['key']}({best['hi']['value']:.0f}"
                 f"{best['unit']})是最低的{best['lo']['key']}({best['lo']['value']:.0f}"
                 f"{best['unit']})的 {best['ratio']:.1f} 倍, 区域不均衡值得关注。"),
        "evidence": [{"label": f"最高·{best['hi']['key']}", "value": round(best['hi']['value'], 1)},
                     {"label": f"最低·{best['lo']['key']}", "value": round(best['lo']['value'], 1)},
                     {"label": "倍差", "value": f"{best['ratio']:.1f}×"}],
        "salience": min(1.0, (best["ratio"] - 1) / 5.0),
    }]


def _detect_anomaly(engine) -> list[dict]:
    worst = None
    for c in engine.distinct("tourism", "县域"):
        labels, values = engine.series("tourism", "旅游综合收入_万元", entity=c)
        for i in range(1, len(values)):
            if values[i - 1] <= 0:
                continue
            chg = (values[i] - values[i - 1]) / values[i - 1]
            if worst is None or chg < worst["chg"]:
                worst = {"chg": chg, "county": c, "year": labels[i],
                         "prev": values[i - 1], "cur": values[i]}
    if not worst or worst["chg"] >= -0.15:
        return []
    return [{
        "kind": "anomaly", "icon": "⚠️",
        "title": f"{worst['county']} {worst['year']}年旅游收入骤降 {abs(worst['chg'])*100:.0f}%",
        "text": (f"{worst['county']}旅游综合收入由上一年的 {worst['prev']:.0f} 万元降至 "
                 f"{worst['year']}年的 {worst['cur']:.0f} 万元, 同比下降 {abs(worst['chg'])*100:.0f}%, "
                 f"为合成演示数据中的最大单年跌幅; 生成规则包含预设扰动, 不可据此归因现实事件。"),
        "evidence": [{"label": "同比", "value": f"{worst['chg']*100:.0f}%"},
                     {"label": "上一年", "value": round(worst['prev'], 1)},
                     {"label": worst['year'], "value": round(worst['cur'], 1)}],
        "salience": min(1.0, abs(worst["chg"])),
    }]


def _detect_structure(engine) -> list[dict]:
    years = [y for y in engine.distinct("agriculture", "年份") if isinstance(y, int)]
    year = max(years) if years else 2024
    res = engine.query("agriculture", "产量_吨", "农产品类别", agg="sum",
                       filters={"年份": year}, order="desc")
    vals = [r for r in res if isinstance(r["value"], (int, float))]
    total = sum(r["value"] for r in vals)
    if not vals or total <= 0:
        return []
    top = vals[0]
    share = top["value"] / total
    return [{
        "kind": "structure", "icon": "🌾",
        "title": f"{year}年 农产品以{top['key']}为主 (占 {share*100:.0f}%)",
        "text": (f"{year}年全域农产品总产量中, {top['key']}以 {top['value']:.0f} 吨居首, "
                 f"占比 {share*100:.0f}%, 是县域农业的压舱石。"),
        "evidence": [{"label": top["key"], "value": round(top["value"], 1)},
                     {"label": "占比", "value": f"{share*100:.0f}%"}],
        "salience": share,
    }]


def compute_insights(engine, max_cards: int = 8) -> list[dict[str, Any]]:
    """运行全部检测器, 按显著性排序返回洞察卡片。"""
    cards: list[dict] = []
    cards += _detect_correlations(engine)
    cards += _detect_growth(engine)
    cards += _detect_disparity(engine)
    cards += _detect_anomaly(engine)
    cards += _detect_structure(engine)
    cards.sort(key=lambda c: c.get("salience", 0), reverse=True)
    for i, c in enumerate(cards[:max_cards], 1):
        c["id"] = i
    return cards[:max_cards]


if __name__ == "__main__":
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from data_engine import DataEngine

    eng = DataEngine()
    for c in compute_insights(eng):
        print(f"{c['icon']} [{c['kind']}] {c['title']}")
        print(f"    {c['text']}")
        print(f"    证据: {c['evidence']}")
