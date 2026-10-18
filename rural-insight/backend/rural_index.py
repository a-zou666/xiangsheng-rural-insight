# -*- coding: utf-8 -*-
"""
rural_index.py — 县域乡村振兴综合评价指数 (熵权法 + TOPSIS)

本模块将常见熵权法与 TOPSIS 用纯 Python 标准库实现于合成演示样本；不主张算法原创或现实评价效力。
  1. 熵权法 (Entropy Weight Method) 按当前样本指标分布计算权重 —— 不引入主观打分, 权重随样本范围变化;
     指标区分度越大(信息熵越小)权重越高;
  2. TOPSIS (逼近理想解排序法) 计算各县到"正/负理想解"的距离, 得到贴近度;
  3. 覆盖"五大振兴"(产业/人才/文化/生态/组织)各 3 个指标, 共 15 项,
     支持成本型指标(越低越好, 如外出务工劳动力)方向化处理;
  4. 输出全透明: 每个指标的权重、每个县的分维度得分与总得分、排名, 均可复核。

设计取向: 以"可解释、可复现、可审计"为第一原则, 适配政务/基层决策场景。
"""
from __future__ import annotations

import math
from typing import Any

# 指标体系: (数据集, CSV列名, 展示名, 单位, 五大振兴维度, 方向)
#   方向 "+" = 效益型(越高越好);  "-" = 成本型(越低越好)
INDICATORS: list[tuple[str, str, str, str, str, str]] = [
    # 产业振兴
    ("economy",    "地区生产总值_万元",           "地区生产总值",       "万元", "产业振兴", "+"),
    ("economy",    "农村居民人均可支配收入_元",   "农村居民人均可支配收入", "元", "产业振兴", "+"),
    ("digital",    "农村网络零售额_万元",         "农村网络零售额",     "万元", "产业振兴", "+"),
    # 人才振兴
    ("population", "返乡创业人数_人",             "返乡创业人数",       "人",   "人才振兴", "+"),
    ("population", "外出务工劳动力_人",           "外出务工劳动力",     "人",   "人才振兴", "-"),
    ("population", "乡村常住人口_人",             "乡村常住人口",       "人",   "人才振兴", "+"),
    # 文化振兴
    ("tourism",    "旅游综合收入_万元",           "旅游综合收入",       "万元", "文化振兴", "+"),
    ("tourism",    "游客量_万人次",               "游客量",             "万人次", "文化振兴", "+"),
    ("tourism",    "民宿数量_家",                 "民宿数量",           "家",   "文化振兴", "+"),
    # 生态振兴
    ("ecology",    "森林覆盖率_百分比",           "森林覆盖率",         "%",    "生态振兴", "+"),
    ("ecology",    "农村污水处理率_百分比",       "农村污水处理率",     "%",    "生态振兴", "+"),
    ("ecology",    "生活垃圾处理率_百分比",       "生活垃圾处理率",     "%",    "生态振兴", "+"),
    # 组织振兴
    ("governance", "村级集体经济收入_万元",       "村级集体经济收入",   "万元", "组织振兴", "+"),
    ("governance", "村民自治参与率_百分比",       "村民自治参与率",     "%",    "组织振兴", "+"),
    ("governance", "平安乡村达标率_百分比",       "平安乡村达标率",     "%",    "组织振兴", "+"),
]

DIMENSIONS = ["产业振兴", "人才振兴", "文化振兴", "生态振兴", "组织振兴"]


def _latest_year(engine) -> int:
    years = [y for y in engine.distinct("economy", "年份") if isinstance(y, int)]
    return max(years) if years else 2024


def _collect_matrix(engine, year: int):
    """返回 (counties, matrix) : matrix[i][j] = 第 i 县第 j 指标原始值。
    缺失值以该列均值回填, 保证算法稳健。"""
    counties = engine.distinct("economy", "县域")
    raw: list[list[float | None]] = []
    for c in counties:
        row: list[float | None] = []
        for (ds, key, *_rest) in INDICATORS:
            res = engine.query(ds, key, "县域", agg="sum", filters={"年份": year})
            val = next((r["value"] for r in res if r["key"] == c), None)
            row.append(float(val) if isinstance(val, (int, float)) else None)
        raw.append(row)
    # 列均值回填缺失
    m = len(INDICATORS)
    for j in range(m):
        col = [raw[i][j] for i in range(len(counties)) if raw[i][j] is not None]
        mean = sum(col) / len(col) if col else 0.0
        for i in range(len(counties)):
            if raw[i][j] is None:
                raw[i][j] = mean
    return counties, raw


def _normalize(matrix: list[list[float]]):
    """方向化 min-max 归一到 [0,1] (效益型越大越好, 成本型取反)。"""
    n, m = len(matrix), len(matrix[0])
    norm = [[0.0] * m for _ in range(n)]
    for j in range(m):
        direction = INDICATORS[j][5]
        col = [matrix[i][j] for i in range(n)]
        lo, hi = min(col), max(col)
        span = hi - lo
        for i in range(n):
            if span == 0:
                norm[i][j] = 1.0            # 无区分度 → 熵权自然趋近 0
            elif direction == "+":
                norm[i][j] = (matrix[i][j] - lo) / span
            else:                            # 成本型
                norm[i][j] = (hi - matrix[i][j]) / span
    return norm


def _entropy_weights(norm: list[list[float]]) -> list[float]:
    """熵权法: 返回每个指标的权重 (和为 1)。
    为避免 ln(0), 对列归一概率做平移处理。"""
    n, m = len(norm), len(norm[0])
    weights = [0.0] * m
    divergence = [0.0] * m
    k = 1.0 / math.log(n) if n > 1 else 1.0
    for j in range(m):
        col = [norm[i][j] for i in range(n)]
        total = sum(col)
        if total <= 0:
            divergence[j] = 0.0
            continue
        e = 0.0
        for i in range(n):
            p = col[i] / total
            if p > 0:
                e += p * math.log(p)
        e = -k * e                      # 信息熵, 介于 [0,1]
        divergence[j] = 1.0 - e         # 差异系数(区分度)
    dsum = sum(divergence)
    if dsum <= 0:
        return [1.0 / m] * m            # 退化: 等权
    for j in range(m):
        weights[j] = divergence[j] / dsum
    return weights


def _topsis(norm: list[list[float]], weights: list[float]):
    """TOPSIS: 返回 (closeness[], dplus[], dminus[])。
    norm 已为效益化 [0,1] 矩阵, 加权后求与正/负理想解的欧氏距离。"""
    n, m = len(norm), len(norm[0])
    weighted = [[norm[i][j] * weights[j] for j in range(m)] for i in range(n)]
    best = [max(weighted[i][j] for i in range(n)) for j in range(m)]   # 正理想解
    worst = [min(weighted[i][j] for i in range(n)) for j in range(m)]  # 负理想解
    dplus, dminus, closeness = [], [], []
    for i in range(n):
        dp = math.sqrt(sum((weighted[i][j] - best[j]) ** 2 for j in range(m)))
        dm = math.sqrt(sum((weighted[i][j] - worst[j]) ** 2 for j in range(m)))
        dplus.append(dp)
        dminus.append(dm)
        closeness.append(dm / (dp + dm) if (dp + dm) > 0 else 0.0)
    return closeness, dplus, dminus, weighted


def _dimension_scores(norm, weights, i) -> dict[str, float]:
    """某县各"振兴维度"的 0-100 得分 = 维度内指标的加权平均归一值。"""
    out: dict[str, float] = {}
    for dim in DIMENSIONS:
        num = den = 0.0
        for j, ind in enumerate(INDICATORS):
            if ind[4] == dim:
                num += norm[i][j] * weights[j]
                den += weights[j]
        out[dim] = round(100.0 * (num / den if den > 0 else 0.0), 1)
    return out


def compute_index(engine, year: int | None = None) -> dict[str, Any]:
    """计算县域乡村振兴综合评价指数。返回全透明结果字典。"""
    if year is None:
        year = _latest_year(engine)
    counties, matrix = _collect_matrix(engine, year)
    norm = _normalize(matrix)
    weights = _entropy_weights(norm)
    closeness, dplus, dminus, _weighted = _topsis(norm, weights)

    # 维度权重 = 维度内指标权重之和
    dim_weights = {dim: 0.0 for dim in DIMENSIONS}
    for j, ind in enumerate(INDICATORS):
        dim_weights[ind[4]] += weights[j]
    dim_weights = {d: round(w, 4) for d, w in dim_weights.items()}

    rows = []
    for i, c in enumerate(counties):
        rows.append({
            "county": c,
            "score": round(closeness[i] * 100, 2),
            "closeness": round(closeness[i], 4),
            "dplus": round(dplus[i], 4),
            "dminus": round(dminus[i], 4),
            "dimensions": _dimension_scores(norm, weights, i),
            "values": {INDICATORS[j][1]: round(matrix[i][j], 2) for j in range(len(INDICATORS))},
        })
    rows.sort(key=lambda r: r["score"], reverse=True)
    for rank, r in enumerate(rows, 1):
        r["rank"] = rank

    indicators_meta = [{
        "dataset": ind[0], "key": ind[1], "name": ind[2], "unit": ind[3],
        "dimension": ind[4], "direction": ("效益型" if ind[5] == "+" else "成本型"),
        "weight": round(weights[j], 4),
    } for j, ind in enumerate(INDICATORS)]

    return {
        "year": year,
        "method": "熵权法-TOPSIS",
        "note": ("权重由熵权法按当前样本的指标区分度计算; 综合得分为 TOPSIS 贴近度×100, "
                 "越接近正理想解得分越高。成本型指标(如外出务工劳动力)已做反向处理。"
                 "本结果仅为虚构县域合成演示数据内的相对排序, 不代表真实县域评价或政策结论; "
                 "权重、得分与排名会随样本范围和指标口径变化。"),
        "dimensions": DIMENSIONS,
        "dimension_weights": dim_weights,
        "indicators": indicators_meta,
        "ranking": rows,
    }


if __name__ == "__main__":
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from data_engine import DataEngine

    eng = DataEngine()
    res = compute_index(eng)
    print(f"== {res['year']}年 县域乡村振兴综合评价指数 ({res['method']}) ==")
    print("维度权重:", res["dimension_weights"])
    print("指标权重:")
    for ind in res["indicators"]:
        print(f"  [{ind['dimension']}] {ind['name']}({ind['direction']}): {ind['weight']}")
    print("\n综合排名:")
    for r in res["ranking"]:
        print(f"  第{r['rank']}名 {r['county']}: {r['score']}  维度={r['dimensions']}")
