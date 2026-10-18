# -*- coding: utf-8 -*-
"""
smoke_test.py — 乡数智见 端到端冒烟测试 (无需联网, 纯标准库)

直接调用后端核心函数, 覆盖: 数据加载、通用查询、时序预测(含回测MAPE)、
自然语言问数(规则引擎)、自动叙事、以及 server.build_answer 全链路。
运行:  python tests/smoke_test.py
全部通过时退出码为 0, 任一失败则非 0, 便于 CI/评审一键核验。
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))

import data_engine
import forecast as fc_mod
import nlquery
import narrative
import server
import rural_index
import insights as insights_mod
import world_bank
import server
import kb as kb_mod
import retrieval as retrieval_mod
import guide as guide_mod
import evaluation as evaluation_mod

PASS = 0
FAIL = 0


def check(name: str, cond: bool, extra: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {extra}")


def main():
    print("== 1. 数据引擎 ==")
    eng = data_engine.DataEngine()
    check("加载 8 个数据集", len(eng.tables) == 8, f"实际={len(eng.tables)}")
    check("economy 60 行", len(eng.tables["economy"]) == 60)
    check("ecommerce_monthly 288 行", len(eng.tables["ecommerce_monthly"]) == 288)
    check("governance 60 行", len(eng.tables["governance"]) == 60)
    check("6 个示例县", len(eng.distinct("economy", "县域")) == 6)

    print("\n== 2. 通用查询 ==")
    rows = eng.query("digital", "农村网络零售额_万元", "县域",
                     agg="sum", filters={"年份": 2024}, order="desc")
    check("2024 零售额查询返回 6 行", len(rows) == 6)
    check("降序: 首项 >= 末项", rows[0]["value"] >= rows[-1]["value"])
    top3 = eng.query("population", "返乡创业人数_人", "县域", order="desc", top_n=3)
    check("Top-N 截断为 3", len(top3) == 3)

    print("\n== 3. 时序预测 ==")
    labels, values = eng.series("digital", "农村网络零售额_万元", entity="青溪县")
    r = fc_mod.forecast(labels, values, horizon=3)
    check("年度预测产出 3 期", len(r["forecast"]) == 3)
    check("回测 MAPE 为数值", isinstance(r["mape"], (int, float)))
    check("年度自动择优(线性/指数)", "回归" in r["method"], r["method"])
    ml, mv = eng.series("ecommerce_monthly", "农村网络零售额_万元", entity="临江县")
    rm = fc_mod.forecast(ml, mv, horizon=6, season_length=12)
    check("月度季节预测产出 6 期", len(rm["forecast"]) == 6)
    check("月度命中季节模型", "季节" in rm["method"], rm["method"])
    check("月度 MAPE < 20%", rm["mape"] is not None and rm["mape"] < 20, f"mape={rm['mape']}")
    check("未来标签接续月份", rm["future_labels"][0] == "2025-01", rm["future_labels"][:1])

    print("\n== 4. 自然语言问数 (规则引擎) ==")
    cases = [
        ("2024年各县农村网络零售额排名", dict(dataset="digital", intent="compare", chart="bar")),
        ("青溪县旅游综合收入逐年变化并预测未来3年", dict(dataset="tourism", intent="forecast", chart="line")),
        ("各县返乡创业人数前3名", dict(dataset="population", top_n=3)),
        ("临江县电商月度销售额预测未来6个月", dict(dataset="ecommerce_monthly", intent="forecast", season_length=12)),
        ("各县农产品产量构成", dict(dataset="agriculture", intent="compose", chart="pie")),
    ]
    for q, exp in cases:
        spec = nlquery.parse(q, eng)
        ok = all(getattr(spec, k) == v for k, v in exp.items())
        check(f"解析: {q}", ok, f"got dataset={spec.dataset} intent={spec.intent} "
              f"chart={spec.chart} top_n={spec.top_n} season={spec.season_length}")

    print("\n== 5. 自动叙事 (事实可核验) ==")
    spec = nlquery.parse("2024年各县农村网络零售额排名", eng)
    rows = eng.query(spec.dataset, spec.measure, spec.group_by, agg=spec.agg,
                     filters=spec.filters, order=spec.order)
    nar = narrative.narrate_compare(spec, rows)
    check("对比叙事非空", len(nar["text"]) > 10)
    check("对比叙事含事实要点", len(nar["facts"]) >= 3)
    spec2 = nlquery.parse("青溪县旅游综合收入逐年变化并预测未来3年", eng)
    labels, values = eng.series(spec2.dataset, spec2.measure, entity=spec2.filters.get("县域"))
    fc = fc_mod.forecast(labels, values, horizon=3)
    nar2 = narrative.narrate_trend(spec2, labels, values, fc)
    check("趋势叙事含 MAPE", "MAPE" in nar2["text"])
    check("趋势叙事含复合增长", "复合增长" in nar2["text"])

    print("\n== 6. 全链路 build_answer ==")
    for q in ["2024年各县农村网络零售额排名",
              "青溪县旅游综合收入逐年变化并预测未来3年",
              "各县农产品产量构成"]:
        ans = server.build_answer(q)
        has_chart = bool(ans["chart"].get("series") or ans["chart"].get("pie"))
        check(f"build_answer: {q}", has_chart and bool(ans["narrative"]["text"]))

    print("\n== 7. 乡村治理数据集 (governance) ==")
    spec_g = nlquery.parse("各县村级集体经济收入排名", eng)
    check("治理问数命中 governance", spec_g.dataset == "governance", spec_g.dataset)
    gov_ans = server.build_answer("丰禾县平安乡村达标率变化趋势")
    check("治理趋势全链路出图", bool(gov_ans["chart"].get("series")))

    print("\n== 8. 熵权法-TOPSIS 综合评价指数 ==")
    idx = rural_index.compute_index(eng)
    check("综合指数覆盖 6 县", len(idx["ranking"]) == 6, f"实际={len(idx['ranking'])}")
    check("15 项指标", len(idx["indicators"]) == 15, f"实际={len(idx['indicators'])}")
    wsum = sum(i["weight"] for i in idx["indicators"])
    check("指标权重归一(Σ≈1)", abs(wsum - 1.0) < 1e-2, f"Σw={wsum}")
    r0 = idx["ranking"][0]
    check("排名降序: 第1名得分≥第2名", r0["score"] >= idx["ranking"][1]["score"])
    check("得分含五维分解", len(r0["dimensions"]) == 5, str(list(r0["dimensions"])))
    check("closeness 落在 [0,1]", all(0 <= r["closeness"] <= 1 for r in idx["ranking"]))

    print("\n== 9. 智能洞察引擎 ==")
    cards = insights_mod.compute_insights(eng)
    check("产出洞察卡片 >= 4", len(cards) >= 4, f"实际={len(cards)}")
    check("每卡含标题/正文/证据", all(c.get("title") and c.get("text") and c.get("evidence") for c in cards))
    check("按显著性降序", all(cards[i]["salience"] >= cards[i+1]["salience"] for i in range(len(cards)-1)))
    kinds = {c["kind"] for c in cards}
    check("涵盖多类洞察(>=3种)", len(kinds) >= 3, str(kinds))
    corr_cards = [c for c in cards if c["kind"] == "correlation"]
    check("相关洞察标注合成样本且不暗示因果",
          all("合成样本" in c["text"] and "不代表因果" in c["text"] for c in corr_cards))
    anomaly_cards = [c for c in cards if c["kind"] == "anomaly"]
    check("异常洞察不将模拟跌幅归因现实疫情",
          all("合成演示数据" in c["text"] and "不可据此归因现实事件" in c["text"]
              and "疫情冲击吻合" not in c["text"] for c in anomaly_cards))

    print("\n== 10. 地图/指数 API 构造 ==")
    mp = server.build_map("index", "", None)
    check("地图(index)返回 6 县着色值", len(mp["data"]) == 6)
    check("地图提供可选指标项", len(mp["options"]) >= 5)
    mp2 = server.build_map("农村网络零售额_万元", "digital", 2024)
    check("地图(指标)返回数值", len(mp2["data"]) == 6 and mp2["unit"] == "万元")
    bi = server.build_index(None)
    check("build_index 含雷达轴", len(bi["radar_indicator"]) == 5)

    print("\n== 11. 世界银行真实背景数据与情景 ==")
    wb_rows = world_bank.load_series()
    check("世界银行序列覆盖 2015-2025", len(wb_rows) == 11 and wb_rows[0]["year"] == 2015 and wb_rows[-1]["year"] == 2025)
    check("农村人口占比年度下降方向与源数据一致", wb_rows[-1]["rural_population_share_pct"] < wb_rows[0]["rural_population_share_pct"])
    baseline = world_bank.build_scenario(0)
    shifted = world_bank.build_scenario(0.2)
    check("情景端点差等于年度扰动累积", abs(shifted["scenario_end_difference_pp"] - 1.0) < 1e-6)
    check("基准情景差为零", abs(baseline["scenario_end_difference_pp"]) < 1e-6)
    check("情景明确标注非预测/非因果", "不是预测" in shifted["method_note"] and "因果" in shifted["method_note"])
    check("来源指标 API 可追溯", "SP.RUR.TOTL.ZS" in shifted["sources"]["rural_population_share_pct"])
    wb_context = server.build_world_bank_context()
    check("服务层全国数据路由与本地快照一致", len(wb_context["rows"]) == len(wb_rows)
          and wb_context["indicators"]["rural_population_share_pct"] == "SP.RUR.TOTL.ZS")
    api_scenario = server.build_scenario(0.2)
    check("服务层情景 API 返回夹紧后结果", api_scenario["delta_pp"] == 0.2
          and api_scenario["scenario_end_difference_pp"] == 1.0)

    print("\n== 12. 乡声 · 文化知识库加载 ==")
    gkb = kb_mod.get_kb()
    check("知识库条目 == 14", len(gkb) == 14, f"实际={len(gkb)}")
    check("点位 5 个", len(gkb.pois) == 5, f"实际={len(gkb.pois)}")
    check("路线 5 站", len(gkb.route_detail()["stops"]) == 5)
    check("版本记录 >= 2", len(gkb.versions) >= 2)
    rs = gkb.review_summary()
    check("每条资料均有来源标注",
          all((e.source or {}).get("name") for e in gkb.all_entries()))
    check("审核台覆盖全部条目", len(rs["rows"]) == len(gkb))
    check("来源类型 >= 2 类", len(gkb.source_types()) >= 2, str(gkb.source_types()))

    print("\n== 13. 确定性检索引擎 (BM25) ==")
    retr = retrieval_mod.get_retriever()
    hits = retr.search("青溪竹编的历史", top_k=3)
    check("检索命中 >= 1", len(hits) >= 1)
    check("命中结果带得分与引用",
          bool(hits) and hits[0].score > 0 and hits[0].entry.citation().get("source_name"))
    check("检索按得分降序",
          all(hits[i].score >= hits[i+1].score for i in range(len(hits)-1)))

    print("\n== 14. 检索增强问答: 带引用作答 + 拒答 ==")
    ans = guide_mod.answer("青溪竹编的历史是怎样的？")
    check("相关问题被作答", ans["answered"] and not ans["refused"])
    check("作答含编号引用 >= 1", len(ans["citations"]) >= 1)
    check("引用含来源名称",
          all(c.get("source_name") for c in ans["citations"]))
    check("引用编号连续从 1 开始",
          [c["index"] for c in ans["citations"]] == list(range(1, len(ans["citations"]) + 1)))
    ref = guide_mod.answer("量子计算的基本原理是什么？")
    check("域外问题被拒答", (not ref["answered"]) and ref["refused"], str(ref["answered"]))
    check("拒答无引用且给出理由",
          ref["citations"] == [] and bool(ref["refusal_reason"]))
    ref2 = guide_mod.answer("青溪村的常住人口有多少万？")
    check("资料缺失问题被拒答(不编造)", not ref2["answered"], str(ref2["answered"]))

    print("\n== 15. 讲解改写 (分龄/研学/双语) + 导览叙事 ==")
    for st in ("children", "study", "normal", "en"):
        ex = guide_mod.explain("qx-bamboo-origin", style=st)
        ok = bool(ex.get("rewritten")) and bool(ex.get("original")) and bool(ex.get("ai_notice"))
        check(f"讲解改写[{guide_mod.STYLES[st]}]保留原文对照", ok, str(list(ex)))
    nr = guide_mod.narration()
    check("导览叙事按路线产出 5 段", len(nr["segments"]) == 5, f"实际={len(nr['segments'])}")
    check("每段叙事附点位与引用",
          all(s.get("name") and s.get("text") and s.get("citation") for s in nr["segments"]))
    check("语音方案标注 Web Speech API", "Web Speech" in nr["tts"])

    print("\n== 16. 服务层导览 API 构造 ==")
    meta = server.build_guide_meta()
    check("导览元信息含村落/主题/声明",
          meta["meta"].get("village") and meta["meta"].get("theme") and meta["meta"].get("disclaimer"))
    check("元信息含风格与示例", bool(meta["styles"]) and len(meta["examples"]) >= 4)
    pois = server.build_guide_pois()
    check("点位 API 返回 5 点位 + 路线",
          len(pois["pois"]) == 5 and bool(pois["route"]["stops"]))
    gkb_api = server.build_guide_kb()
    check("知识库 API 返回全量条目", len(gkb_api["entries"]) == len(gkb))
    ans_api = guide_mod.answer("竹编器物应该怎么保养？")
    check("保养问题命中保养条目",
          any(c["entry_id"] == "qx-bamboo-care" for c in ans_api["citations"]),
          str([c["entry_id"] for c in ans_api["citations"]]))

    print("\n== 17. 可复现评估面板 ==")
    rep = server.build_guide_eval()
    es = rep["summary"]
    check("评估题目总数 >= 30", es["total_questions"] >= 30, f"实际={es['total_questions']}")
    check("作答准确率 100%", es["answer_accuracy_pct"] == 100.0, f"{es['answer_accuracy_pct']}%")
    check("拒答准确率 100%", es["refusal_accuracy_pct"] == 100.0, f"{es['refusal_accuracy_pct']}%")
    check("引用命中率 100%", es["citation_hit_rate_pct"] == 100.0, f"{es['citation_hit_rate_pct']}%")
    check("四种讲解风格均覆盖",
          len([r for r in es["style_coverage"] if r["ok"]]) >= 4)
    check("评估含响应时间指标", isinstance(es["avg_latency_ms"], (int, float)))

    print(f"\n==== 结果: {PASS} 通过 / {FAIL} 失败 ====")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
