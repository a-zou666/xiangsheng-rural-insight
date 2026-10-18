# -*- coding: utf-8 -*-
"""
forecast.py — 乡数智见 时序预测模块 (纯 Python 标准库, 无 numpy)

提供两种可解释的预测方法:
  1. 线性趋势 (最小二乘回归): 适用于年度等无明显季节性的序列;
  2. 季节性分解 + 趋势 (乘性, 类 Holt-Winters 思路): 适用于月度等有年内季节性的序列。

自动根据序列长度与 season_length 选择方法, 并用"留出最后若干期回测"的方式
计算 MAPE (平均绝对百分比误差) 作为可核验的精度指标。
"""
from __future__ import annotations

from typing import Any


def _linreg(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """最小二乘拟合 y = a + b*x, 返回 (a, b)。"""
    n = len(xs)
    if n == 0:
        return 0.0, 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return my, 0.0
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom
    a = my - b * mx
    return a, b


def _mape(actual: list[float], pred: list[float]) -> float | None:
    pairs = [(a, p) for a, p in zip(actual, pred) if a not in (0, 0.0)]
    if not pairs:
        return None
    return round(100.0 * sum(abs(a - p) / abs(a) for a, p in pairs) / len(pairs), 2)


def _linear_core(values: list[float], horizon: int) -> list[float]:
    xs = list(range(len(values)))
    a, b = _linreg([float(x) for x in xs], values)
    return [round(a + b * (len(values) + h), 2) for h in range(horizon)]


def _exp_core(values: list[float], horizon: int) -> list[float] | None:
    """对数线性(指数)外推: 适合持续复合增长的序列。要求全部为正数。"""
    import math
    if any(v <= 0 for v in values):
        return None
    xs = [float(x) for x in range(len(values))]
    logs = [math.log(v) for v in values]
    a, b = _linreg(xs, logs)
    return [round(math.exp(a + b * (len(values) + h)), 2) for h in range(horizon)]


def _nonseasonal_core(values: list[float], horizon: int) -> tuple[list[float], str]:
    """非季节序列: 在"线性"与"指数"间按回测 MAPE 自动择优。"""
    n = len(values)
    hold = max(1, min(horizon, n // 4))
    train, test = values[:-hold], values[-hold:]
    candidates: list[tuple[str, list[float]]] = [
        ("线性趋势 (最小二乘回归)", _linear_core(values, horizon)),
    ]
    exp_fc = _exp_core(values, horizon)
    if exp_fc is not None:
        candidates.append(("指数趋势 (对数线性回归)", exp_fc))
    # 用回测误差择优
    best, best_err = candidates[0], float("inf")
    for name, _ in candidates:
        if name.startswith("线性"):
            bt = _linear_core(train, hold)
        else:
            bt = _exp_core(train, hold) or []
        err = _mape(test, bt)
        if err is not None and err < best_err:
            best_err, best = err, (name, dict(candidates)[name])
    return best[1], best[0]


def _seasonal_core(values: list[float], horizon: int, period: int) -> list[float]:
    """乘性季节模型: 去季节 -> 线性趋势 -> 再乘回季节指数。"""
    n = len(values)
    # 1) 季节指数 (按位置取均值, 再归一化到均值为 1)
    sums = [0.0] * period
    cnts = [0] * period
    for i, v in enumerate(values):
        sums[i % period] += v
        cnts[i % period] += 1
    season = [(sums[k] / cnts[k]) if cnts[k] else 1.0 for k in range(period)]
    avg = sum(season) / period if period else 1.0
    if avg == 0:
        avg = 1.0
    season = [s / avg for s in season]
    # 2) 去季节化后拟合线性趋势
    deseason = [values[i] / (season[i % period] or 1.0) for i in range(n)]
    a, b = _linreg([float(i) for i in range(n)], deseason)
    # 3) 外推并乘回季节
    out = []
    for h in range(horizon):
        idx = n + h
        trend = a + b * idx
        out.append(round(trend * season[idx % period], 2))
    return out


def forecast(
    labels: list[Any],
    values: list[float],
    horizon: int = 4,
    season_length: int | None = None,
) -> dict[str, Any]:
    """
    labels/values: 历史时间序列。
    horizon: 预测期数。
    season_length: 季节周期 (如月度=12); None 时自动判断 (>=24 个点且疑似月度→12)。
    返回包含 method / history / forecast / future_labels / mape 的字典。
    """
    values = [float(v) for v in values]
    n = len(values)
    result: dict[str, Any] = {
        "history_labels": labels, "history": values, "horizon": horizon,
    }
    if n < 3:
        result.update(method="insufficient_data", forecast=[], future_labels=[],
                      mape=None, note="数据点不足, 无法预测")
        return result

    # 自动决定是否使用季节模型
    use_season = False
    period = season_length or 0
    if season_length and n >= 2 * season_length:
        use_season = True
    elif season_length is None and n >= 24 and _looks_monthly(labels):
        period = 12
        use_season = n >= 24
        use_season = True

    # 回测: 留出最后 min(horizon, n//4) 期
    hold = max(1, min(horizon, n // 4))
    train = values[:-hold]
    if use_season and len(train) >= 2 * period:
        bt_pred = _seasonal_core(train, hold, period)
        mape = _mape(values[-hold:], bt_pred)
    else:
        bt_pred, _ = _nonseasonal_core(train, hold)
        mape = _mape(values[-hold:], bt_pred)

    # 正式预测 (用全部历史)
    if use_season and n >= 2 * period:
        fc = _seasonal_core(values, horizon, period)
        method = f"季节性分解+线性趋势 (周期={period})"
    else:
        fc, method = _nonseasonal_core(values, horizon)

    result.update(
        method=method,
        forecast=fc,
        future_labels=_future_labels(labels, horizon),
        mape=mape,
    )
    return result


def _looks_monthly(labels: list[Any]) -> bool:
    return bool(labels) and isinstance(labels[0], str) and "-" in str(labels[0])


def _future_labels(labels: list[Any], horizon: int) -> list[str]:
    if not labels:
        return [str(i + 1) for i in range(horizon)]
    last = labels[-1]
    s = str(last)
    if "-" in s:  # 月度 YYYY-MM
        y, m = s.split("-")
        y, m = int(y), int(m)
        out = []
        for _ in range(horizon):
            m += 1
            if m > 12:
                m = 1
                y += 1
            out.append(f"{y}-{m:02d}")
        return out
    try:  # 年度
        base = int(float(s))
        return [str(base + i + 1) for i in range(horizon)]
    except ValueError:
        return [f"{s}+{i+1}" for i in range(horizon)]


if __name__ == "__main__":
    from data_engine import DataEngine
    eng = DataEngine()
    print("== 年度预测: 青溪县 农村网络零售额 ==")
    labels, values = eng.series("digital", "农村网络零售额_万元", entity="青溪县")
    r = forecast(labels, values, horizon=3)
    print("方法:", r["method"], "| 回测MAPE:", r["mape"], "%")
    print("历史:", list(zip(labels, values))[-3:])
    print("预测:", list(zip(r["future_labels"], r["forecast"])))

    print("\n== 月度季节预测: 临江县 电商月度销售额 ==")
    labels, values = eng.series("ecommerce_monthly", "农村网络零售额_万元", entity="临江县")
    r = forecast(labels, values, horizon=6, season_length=12)
    print("方法:", r["method"], "| 回测MAPE:", r["mape"], "%")
    print("预测:", list(zip(r["future_labels"], r["forecast"])))
