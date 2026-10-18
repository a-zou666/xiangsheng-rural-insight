# -*- coding: utf-8 -*-
"""
evaluation.py — 乡声导览 可验证评估面板 (纯 Python 标准库)

读取 data/eval_questions.json, 对检索增强问答做可复现评估:
  - 事实正确性(近似): 应作答题是否作答, 且命中预期来源 / 关键词;
  - 引用命中率: 作答题中引用到预期来源条目的比例;
  - 拒答正确率: 应拒答题被正确拒答的比例;
  - 响应时间: 单题平均 / 最大耗时 (本地确定性, 不含外部模型)。

所有指标基于离线确定性问答, 无需外部模型或网络, 可被评审一键复算。
注意: 评估问题集为团队设计的示例测试集, 不代表真实用户测试。
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

from guide import answer, explain, STYLES
from kb import get_kb

DATA_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
)
EVAL_FILE = os.path.join(DATA_DIR, "eval_questions.json")


def _load() -> dict[str, Any]:
    with open(EVAL_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def run_eval() -> dict[str, Any]:
    data = _load()
    questions = data.get("questions", [])
    style_cases = data.get("style_cases", [])
    kb = get_kb()

    rows: list[dict[str, Any]] = []
    answer_total = refuse_total = 0
    answer_ok = refuse_ok = 0
    citation_hit = citation_total = 0
    keyword_hit = keyword_total = 0
    latencies: list[float] = []

    for item in questions:
        q = item["q"]
        expect = item.get("expect", "answer")
        exp_sources = set(item.get("expect_sources", []))
        exp_keywords = item.get("keywords", [])

        t0 = time.perf_counter()
        res = answer(q)
        dt = (time.perf_counter() - t0) * 1000
        latencies.append(dt)

        answered = res["answered"]
        cited_ids = {c["entry_id"] for c in res.get("citations", [])}
        row: dict[str, Any] = {
            "q": q, "expect": expect, "answered": answered,
            "cited": sorted(cited_ids),
            "top_score": res["assessment"]["top_score"],
            "answerability": res["assessment"]["answerability"],
            "elapsed_ms": round(dt, 2),
        }

        if expect == "answer":
            answer_total += 1
            correct = answered
            # 引用命中: 若指定了预期来源, 命中其一即算
            if exp_sources:
                citation_total += 1
                if answered and (cited_ids & exp_sources):
                    citation_hit += 1
                else:
                    correct = correct and False if exp_sources else correct
            # 关键词命中(近似事实正确性)
            if exp_keywords and answered:
                keyword_total += 1
                atext = res["answer"]
                if any(k in atext for k in exp_keywords):
                    keyword_hit += 1
            if answered and (not exp_sources or (cited_ids & exp_sources)):
                answer_ok += 1
                row["result"] = "ok"
            else:
                row["result"] = "miss"
        else:  # refuse
            refuse_total += 1
            if not answered:
                refuse_ok += 1
                row["result"] = "ok"
            else:
                row["result"] = "miss"
        rows.append(row)

    # 风格覆盖检查: 每种讲解风格都能对示例条目产出非空、含声明的改写
    style_report = []
    for sc in style_cases:
        entry_id = kb.all_entries()[1].id if len(kb) > 1 else kb.all_entries()[0].id
        for st in sc.get("styles", list(STYLES.keys())):
            r = explain(entry_id, style=st)
            style_report.append({
                "style": st,
                "style_name": STYLES.get(st, st),
                "ok": bool(r.get("rewritten")) and "original" in r,
                "has_citation": bool(r.get("citation")),
            })

    def pct(n: int, d: int) -> float:
        return round(100.0 * n / d, 1) if d else 0.0

    summary = {
        "total_questions": len(questions),
        "answer_cases": answer_total,
        "refuse_cases": refuse_total,
        "answer_accuracy_pct": pct(answer_ok, answer_total),
        "refusal_accuracy_pct": pct(refuse_ok, refuse_total),
        "citation_hit_rate_pct": pct(citation_hit, citation_total),
        "keyword_fact_match_pct": pct(keyword_hit, keyword_total),
        "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
        "max_latency_ms": round(max(latencies), 2) if latencies else 0.0,
        "style_coverage": style_report,
        "note": "示例评估集，离线确定性问答，无外部模型/网络；不代表真实用户测试。",
    }
    return {"summary": summary, "rows": rows}


if __name__ == "__main__":
    report = run_eval()
    s = report["summary"]
    print("=== 乡声导览 评估面板 (示例) ===")
    print(f"题目总数: {s['total_questions']}  "
          f"(应作答 {s['answer_cases']} / 应拒答 {s['refuse_cases']})")
    print(f"作答准确率: {s['answer_accuracy_pct']}%   拒答准确率: {s['refusal_accuracy_pct']}%")
    print(f"引用命中率: {s['citation_hit_rate_pct']}%   关键词事实匹配: {s['keyword_fact_match_pct']}%")
    print(f"平均响应: {s['avg_latency_ms']} ms   最大响应: {s['max_latency_ms']} ms")
    print("风格覆盖:", [(r["style_name"], r["ok"]) for r in s["style_coverage"]])
    print("\n-- 逐题 --")
    for r in report["rows"]:
        print(f"[{r['result']:4}] {r['expect']:6} ans={r['answered']!s:5} "
              f"score={r['top_score']:.2f} cov={r['answerability']:.2f}  {r['q']}")
