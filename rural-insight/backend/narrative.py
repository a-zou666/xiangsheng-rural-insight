# -*- coding: utf-8 -*-
"""
narrative.py — 乡数智见 自动数据叙事

把查询/预测结果转写为中文结论段落 (可供人工校核后采用)。
默认使用【确定性模板叙事】: 根据数据自动计算极值、极差、增长率、复合增长率(CAGR)、
预测方向、季节峰谷等事实, 以结构化模板生成结论, 保证不编造、可核验。
可选【LLM 润色】: 配置 API 时对事实要点做自然语言润色 (仅润色不新增事实)。

★ 评审透明度: 叙事中的每一个数字都来自真实计算 (见 facts 字段), 生成式润色不改变事实。
"""
from __future__ import annotations

import os
from typing import Any

from nlquery import QuerySpec


def _fmt(v: float, unit: str) -> str:
    if abs(v) >= 10000 and unit in ("万元", "元", "人", "吨", "亩"):
        return f"{v:,.0f}{unit}"
    if isinstance(v, float) and not v.is_integer():
        return f"{v:,.1f}{unit}"
    return f"{v:,.0f}{unit}"


def narrate_compare(spec: QuerySpec, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """对比/构成类叙事。rows=[{key,value}]。"""
    facts: list[str] = []
    if not rows:
        return {"text": "无符合条件的数据。", "facts": facts}
    vals = [r["value"] for r in rows]
    total = sum(vals)
    top = max(rows, key=lambda r: r["value"])
    bot = min(rows, key=lambda r: r["value"])
    unit = spec.unit
    facts.append(f"参与对比的分组数: {len(rows)}")
    facts.append(f"最高: {top['key']}={_fmt(top['value'], unit)}")
    facts.append(f"最低: {bot['key']}={_fmt(bot['value'], unit)}")
    facts.append(f"合计: {_fmt(total, unit)}")

    parts = [f"在「{spec.title}」中, 共纳入 {len(rows)} 个分组。"]
    parts.append(
        f"{top['key']}以 {_fmt(top['value'], unit)} 居首, "
        f"{bot['key']}最低, 为 {_fmt(bot['value'], unit)}。"
    )
    if bot["value"] not in (0, 0.0):
        ratio = top["value"] / bot["value"]
        facts.append(f"首尾倍差: {ratio:.2f}×")
        parts.append(f"二者相差约 {ratio:.1f} 倍, 区域间差异{'较为明显' if ratio >= 1.5 else '相对均衡'}。")
    if spec.intent == "compose" and total:
        share = top["value"] / total * 100
        facts.append(f"最大占比: {top['key']} {share:.1f}%")
        parts.append(f"其中 {top['key']} 占比最高, 约 {share:.1f}%。")
    return {"text": "".join(parts), "facts": facts}


def narrate_trend(spec: QuerySpec, labels: list[Any], values: list[float],
                  fc: dict[str, Any] | None = None) -> dict[str, Any]:
    """趋势/预测类叙事。"""
    facts: list[str] = []
    if len(values) < 2:
        return {"text": "数据点不足, 无法分析趋势。", "facts": facts}
    unit = spec.unit
    start, end = values[0], values[-1]
    span = len(values) - 1
    change = end - start
    pct = (change / start * 100) if start else 0.0
    cagr = ((end / start) ** (1 / span) - 1) * 100 if start > 0 and span > 0 else 0.0
    peak = max(values)
    trough = min(values)
    peak_label = labels[values.index(peak)]
    trough_label = labels[values.index(trough)]
    facts.append(f"区间: {labels[0]} → {labels[-1]}")
    facts.append(f"起始={_fmt(start, unit)}, 期末={_fmt(end, unit)}")
    facts.append(f"累计变化={pct:+.1f}%, 年均复合增长(CAGR)={cagr:+.1f}%")
    facts.append(f"峰值={_fmt(peak, unit)}@{peak_label}; 谷值={_fmt(trough, unit)}@{trough_label}")

    direction = "上升" if change > 0 else ("下降" if change < 0 else "基本持平")
    scope = spec.filters.get("县域", "全部县域")
    parts = [
        f"{scope}的{spec.measure_name}在 {labels[0]} 至 {labels[-1]} 间整体呈{direction}态势, "
        f"由 {_fmt(start, unit)} 变为 {_fmt(end, unit)}, 累计{pct:+.1f}%, "
        f"年均复合增长约 {cagr:+.1f}%。"
    ]
    if peak_label != labels[-1]:
        parts.append(f"期间峰值出现在 {peak_label} ({_fmt(peak, unit)})。")

    if fc and fc.get("forecast"):
        fv = fc["forecast"]
        last_hist = values[-1]
        f_end = fv[-1]
        f_dir = "继续增长" if f_end > last_hist else ("有所回落" if f_end < last_hist else "趋于平稳")
        facts.append(f"预测方法={fc['method']}, 回测MAPE={fc.get('mape')}%")
        facts.append(f"预测期末({fc['future_labels'][-1]})={_fmt(f_end, unit)}")
        parts.append(
            f"采用「{fc['method']}」外推, 预计到 {fc['future_labels'][-1]} 将{f_dir}至 "
            f"{_fmt(f_end, unit)}; 模型在历史留出期上的平均绝对百分比误差(MAPE)约 "
            f"{fc.get('mape')}%, 预测结果仅供参考。"
        )
    return {"text": "".join(parts), "facts": facts}


def llm_polish(text: str, facts: list[str]) -> str:
    """可选 LLM 润色: 仅在配置 API 时启用, 失败则原样返回。只润色、不新增事实。"""
    base = os.environ.get("RURAL_LLM_BASE")
    key = os.environ.get("RURAL_LLM_KEY")
    if not (base and key):
        return text
    try:
        import json
        import urllib.request
        prompt = (
            "下面是一段数据分析结论和其对应的事实要点。请在不改变、不新增任何数字与事实的前提下, "
            "把结论润色得更通顺专业, 控制在 3 句以内, 直接输出润色后的文字:\n\n"
            f"结论: {text}\n事实要点: {'; '.join(facts)}"
        )
        body = json.dumps({
            "model": os.environ.get("RURAL_LLM_MODEL", "deepseek-chat"),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
        }).encode("utf-8")
        req = urllib.request.Request(
            base.rstrip("/") + "/v1/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + key})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"].strip() or text
    except Exception:
        return text


if __name__ == "__main__":
    from data_engine import DataEngine
    from nlquery import parse
    from forecast import forecast
    eng = DataEngine()

    spec = parse("2024年各县农村网络零售额排名", eng)
    rows = eng.query(spec.dataset, spec.measure, spec.group_by, agg=spec.agg,
                     filters=spec.filters, order=spec.order, top_n=spec.top_n)
    print(narrate_compare(spec, rows)["text"])

    spec = parse("青溪县旅游收入逐年变化并预测未来3年", eng)
    labels, values = eng.series(spec.dataset, spec.measure, entity=spec.filters.get("县域"))
    fc = forecast(labels, values, horizon=spec.forecast_horizon, season_length=spec.season_length)
    print("\n" + narrate_trend(spec, labels, values, fc)["text"])
