# -*- coding: utf-8 -*-
"""Curated World Bank national rural-context series and transparent scenarios."""
from __future__ import annotations

import csv
import os
from typing import Any

DATA_PATH = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "world_bank_china_rural_context.csv"))
SOURCE_URLS = {
    "rural_population": "https://api.worldbank.org/v2/country/CHN/indicator/SP.RUR.TOTL?format=json&per_page=100",
    "rural_population_share_pct": "https://api.worldbank.org/v2/country/CHN/indicator/SP.RUR.TOTL.ZS?format=json&per_page=100",
    "gdp_per_capita_current_usd": "https://api.worldbank.org/v2/country/CHN/indicator/NY.GDP.PCAP.CD?format=json&per_page=100",
}


def load_series(path: str = DATA_PATH) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [{k: (int(v) if k == "year" else float(v)) for k, v in row.items()}
                for row in csv.DictReader(f)]


def build_scenario(delta_pp: float = 0.0) -> dict[str, Any]:
    """Mechanical linear scenario: alter recent annual percentage-point slope; not a forecast."""
    rows = load_series()
    base = rows[-1]
    recent = [r for r in rows if r["year"] >= base["year"] - 5]
    slope = (recent[-1]["rural_population_share_pct"] - recent[0]["rural_population_share_pct"]) / (recent[-1]["year"] - recent[0]["year"])
    delta_pp = max(-0.5, min(0.5, float(delta_pp)))
    actual = [{"year": r["year"], "value": r["rural_population_share_pct"]} for r in rows]
    horizon = 5
    baseline, scenario = [], []
    for step in range(1, horizon + 1):
        baseline.append({"year": base["year"] + step, "value": max(0.0, min(100.0, base["rural_population_share_pct"] + slope * step))})
        scenario.append({"year": base["year"] + step, "value": max(0.0, min(100.0, base["rural_population_share_pct"] + (slope + delta_pp) * step))})
    return {
        "source": "World Bank WDI, China",
        "indicator": "Rural population (% of total population)",
        "indicator_code": "SP.RUR.TOTL.ZS",
        "unit": "%",
        "actual": actual,
        "baseline": baseline,
        "scenario": scenario,
        "recent_annual_change_pp": round(slope, 3),
        "delta_pp": delta_pp,
        "scenario_end_difference_pp": round(scenario[-1]["value"] - baseline[-1]["value"], 3),
        "method_note": "基准线性延伸近5年平均年度变化；情景线在此基础上叠加用户设定的年度百分点变化。纯算术假设，不是预测、政策效果估计或因果结论。",
        "sources": SOURCE_URLS,
    }
