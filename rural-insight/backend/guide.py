# -*- coding: utf-8 -*-
"""
guide.py — 乡声导览 检索增强问答 / 讲解改写 / 导览叙事 核心 (纯 Python 标准库)

本模块是作品的 AI 核心, 组织成【可观测、可测试、确定性可复现】的流水线:

  问题 → 检索(retrieval) → 充分性判定(拒答) → 带引用答案组装
                                        ↘ 可选 LLM 接地生成(需显式配置, 失败回退规则)
  资料 → 分龄/研学/双语【讲解改写】(保留事实, 展示原文对照)
  点位/条目 → 【导览叙事脚本】(供浏览器 Web Speech API 语音播报, 无需外部模型)

核心可信约束 (对应竞赛评审与合规要求):
  - 每条可作答结果都给出带编号的引用 (来源名称/类型/审核状态);
  - 检索不足时明确拒答"资料不足", 不编造历史事实;
  - 讲解改写只做风格/语言转换, 事实以引用原文为准, 并标注 AI 改写;
  - 外部大模型仅在显式配置后用于"接地改写", 且被要求只依据给定资料。
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from typing import Any

from kb import KnowledgeBase, get_kb
from retrieval import Retriever, get_retriever, tokenize

_CJK = r"\u4e00-\u9fff"

# --- 拒答 / 充分性阈值 (确定性, 可复核) --------------------------------
# 绝对相关度下限: 过滤与资料库几乎无关的问题 (纯噪声问题 BM25 极低)
MIN_TOP_SCORE = 5.0
# 内容名词覆盖率下限 (按 IDF 加权): 问题的"实义主题词"须被检索命中
MIN_ANSWERABILITY = 0.43

# 组装答案时采用的证据条数与片段长度
MAX_EVIDENCE = 3
SNIPPET_LEN = 140

# 讲解风格
STYLES = {
    "children": "儿童版",
    "study": "研学版",
    "normal": "普通版",
    "en": "English",
}

# 作为问句常见的"虚词/疑问/程度/数量"二元词, 不计入内容名词覆盖率分母,
# 因为这些词天然不会出现在资料正文里, 不应据此判定资料是否充分。
VAGUE_BIGRAMS = {
    "怎么", "怎样", "如何", "多少", "多久", "多长", "大概", "大约", "左右", "具体",
    "一下", "一般", "介绍", "可以", "是否", "有没", "没有", "什么", "哪些",
    "哪里", "为什么", "请问", "知道", "告诉", "想问", "问一", "一个", "几个",
    "这个", "那个", "一些", "出来", "起来", "下来", "应该", "需要", "能不",
    "说法", "时间", "长时", "时候",
}
# 单字虚词/功能字, 不参与内容词切分
STOP_CHARS = set("的了是有在和与吗呢吧啊呀哦嗯这那你我他她它们到从为会能可以要想看把被给对还也都就很太请问之或而且并即将也呀么")


def _content_bigrams(text: str, retriever: Retriever) -> list[str]:
    """从问题中抽取"实义名词性"中文二元词 + 英文词, 用于充分性判定。

    关键去噪: 纯字符二元切分会在两个真实词的边界处产生"跨词垃圾二元"
    (如 竹编|工序 之间的 编怎 / 些工), 它们在资料库里 df=0, 会错误地拉低
    主题覆盖率。规则: 对 df=0 的二元, 若其任一字已被某个 df>=1 的二元"锚定"
    (即属于一个真实命中词), 则判定为边界垃圾并丢弃; 只保留真正成片的、
    与资料库无关的"域外提问"二元 (如 手机 / 号码 / 人口 / 高铁)。
    """
    toks = tokenize(text)
    raw: list[str] = []
    for t in toks:
        if re.fullmatch(rf"[{_CJK}]{{2}}", t):           # 中文二元
            if t in VAGUE_BIGRAMS:
                continue
            if t[0] in STOP_CHARS or t[1] in STOP_CHARS:
                continue
            raw.append(t)
        elif re.fullmatch(r"[a-z0-9]{2,}", t):           # 英文/数字词
            raw.append(t)
    raw = list(dict.fromkeys(raw))                       # 去重保序

    # 用 df>=1 的中文二元"锚定"字符
    anchored: set[str] = set()
    for b in raw:
        if re.fullmatch(rf"[{_CJK}]{{2}}", b) and retriever.doc_freq(b) >= 1:
            anchored.add(b[0])
            anchored.add(b[1])

    kept: list[str] = []
    for b in raw:
        if re.fullmatch(rf"[{_CJK}]{{2}}", b):
            if retriever.doc_freq(b) >= 1:
                kept.append(b)                            # 资料库已知词
            elif b[0] not in anchored and b[1] not in anchored:
                kept.append(b)                            # 真·域外提问词
            # 否则: 跨词边界垃圾二元, 丢弃
        else:
            kept.append(b)                                # 英文/数字词
    return kept


def assess(question: str, retriever: Retriever | None = None) -> dict[str, Any]:
    """检索 + 充分性判定, 返回可观测的中间结果 (供拒答与答疑组装)。"""
    retriever = retriever or get_retriever()
    hits = retriever.search(question, top_k=MAX_EVIDENCE)
    top_score = hits[0].score if hits else 0.0

    cbigrams = _content_bigrams(question, retriever)
    answerability = 1.0
    covered: list[str] = []
    missing: list[str] = []
    if cbigrams and hits:
        top_tokens = retriever.entry_tokens(hits[0].entry.id)
        # 合并前若干命中文档的 token, 允许跨条目覆盖
        for h in hits:
            top_tokens |= retriever.entry_tokens(h.entry.id)
        num = 0.0
        den = 0.0
        for b in cbigrams:
            w = retriever.term_idf(b)
            den += w
            if b in top_tokens:
                num += w
                covered.append(b)
            else:
                missing.append(b)
        answerability = (num / den) if den > 0 else 0.0
    elif cbigrams and not hits:
        answerability = 0.0
        missing = cbigrams

    sufficient = bool(hits) and top_score >= MIN_TOP_SCORE \
        and answerability >= MIN_ANSWERABILITY
    return {
        "hits": hits,
        "top_score": top_score,
        "answerability": round(answerability, 4),
        "covered_terms": covered,
        "missing_terms": missing,
        "sufficient": sufficient,
        "thresholds": {
            "min_top_score": MIN_TOP_SCORE,
            "min_answerability": MIN_ANSWERABILITY,
        },
    }


REFUSAL_TEXT = (
    "抱歉，现有资料库中没有足够依据回答这个问题，因此不作回答，"
    "以免编造不准确的信息。建议向当地村镇或场馆核实，或改问与"
    "“{theme}”相关的问题。"
)


def _refusal(question: str, kb: KnowledgeBase, assessment: dict[str, Any]) -> dict[str, Any]:
    theme = kb.meta.get("theme", "本村文化")
    return {
        "answered": False,
        "question": question,
        "answer": REFUSAL_TEXT.format(theme=theme),
        "refused": True,
        "refusal_reason": "资料不足：检索结果相关度或主题覆盖率低于阈值。",
        "citations": [],
        "confidence": round(assessment["answerability"], 3),
        "retrieval": [h.to_dict() for h in assessment["hits"]],
        "assessment": {k: assessment[k] for k in
                       ("top_score", "answerability", "covered_terms",
                        "missing_terms", "sufficient", "thresholds")},
        "source": "rule",
        "style": "normal",
        "disclaimer": "本助手仅依据带来源标注的示例资料作答，资料不足时拒答。",
    }


def _compose_rule_answer(question: str, assessment: dict[str, Any]) -> tuple[str, list[dict]]:
    """确定性地从检索片段组装带编号引用的答案。"""
    hits = assessment["hits"][:MAX_EVIDENCE]
    citations: list[dict[str, Any]] = []
    parts: list[str] = []
    for idx, h in enumerate(hits, start=1):
        body = h.entry.body.strip()
        snippet = body if len(body) <= SNIPPET_LEN else body[:SNIPPET_LEN] + "……"
        parts.append(f"{snippet}[{idx}]")
        c = h.entry.citation()
        c["index"] = idx
        citations.append(c)
    answer = "".join(parts)
    return answer, citations


# --------------------------------------------------------------------------
# 可选 LLM 接地改写 (显式配置后启用; 失败自动回退规则组装)
# --------------------------------------------------------------------------
def llm_available() -> bool:
    return bool(os.environ.get("RURAL_LLM_BASE") and os.environ.get("RURAL_LLM_KEY"))


def _llm_ground_answer(question: str, citations: list[dict], evidence_text: str,
                       style: str) -> str | None:
    """要求模型只依据给定资料改写; 不提供新事实。失败返回 None。"""
    if not llm_available():
        return None
    base = os.environ["RURAL_LLM_BASE"].rstrip("/")
    key = os.environ["RURAL_LLM_KEY"]
    model = os.environ.get("RURAL_LLM_MODEL", "gpt-3.5-turbo")
    style_name = STYLES.get(style, "普通版")
    sys_prompt = (
        "你是乡村文化导览助手。只能依据【资料】回答，不得补充资料之外的事实；"
        "若资料不足以回答，请直接说明资料不足。保留引用标注[n]。"
        f"请用“{style_name}”风格组织答案。"
    )
    user_prompt = f"问题：{question}\n\n【资料】\n{evidence_text}\n\n请作答并保留[n]引用。"
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    try:
        req = urllib.request.Request(
            f"{base}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {key}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def answer(question: str, style: str = "normal", use_llm: bool = False,
           kb: KnowledgeBase | None = None,
           retriever: Retriever | None = None) -> dict[str, Any]:
    """核心问答入口: 检索 → 拒答判定 → 带引用答案 (可选 LLM 接地改写)。"""
    kb = kb or get_kb()
    retriever = retriever or get_retriever()
    t0 = time.perf_counter()
    assessment = assess(question, retriever)

    if not assessment["sufficient"]:
        out = _refusal(question, kb, assessment)
        out["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        return out

    rule_answer, citations = _compose_rule_answer(question, assessment)
    source = "rule"
    final_answer = rule_answer

    if use_llm and llm_available():
        evidence_text = "\n".join(
            f"[{c['index']}] {kb.get(c['entry_id']).title}: {kb.get(c['entry_id']).body}"
            for c in citations
        )
        llm_text = _llm_ground_answer(question, citations, evidence_text, style)
        if llm_text:
            final_answer = llm_text
            source = "llm"

    out = {
        "answered": True,
        "question": question,
        "answer": final_answer,
        "refused": False,
        "citations": citations,
        "confidence": round(assessment["answerability"], 3),
        "retrieval": [h.to_dict() for h in assessment["hits"]],
        "assessment": {k: assessment[k] for k in
                       ("top_score", "answerability", "covered_terms",
                        "missing_terms", "sufficient", "thresholds")},
        "source": source,
        "style": style,
        "disclaimer": ("答案由系统基于带来源标注的示例资料检索组装"
                       + ("并经外部模型接地改写" if source == "llm" else "")
                       + "；内容为示例/待实地核验，引用见下方来源。"),
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
    }
    return out


# --------------------------------------------------------------------------
# 讲解改写: 分龄 / 研学 / 双语 (确定性模板, 保留事实, 标注 AI 改写)
# --------------------------------------------------------------------------
def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？；])", text)
    return [p.strip() for p in parts if p.strip()]


def _rewrite_children(entry) -> str:
    sents = _split_sentences(entry.body)
    lead = f"小朋友，我们来认识一下{entry.title}！"
    body = "".join(sents[:3])
    body = body.replace("示例", "").replace("（", "(").replace("）", ")")
    tail = "是不是很有意思呀？下次来可以亲眼看看哦。"
    return f"{lead}{body}{tail}"


def _rewrite_study(entry) -> str:
    sents = _split_sentences(entry.body)
    head = f"【研学主题】{entry.title}（{entry.theme}）"
    points = "".join(f"\n· 要点{i+1}：{s}" for i, s in enumerate(sents[:4]))
    task = ("\n【探究任务】结合现场观察，记录你看到的细节，并对照资料来源"
            "判断哪些是已核实信息、哪些仍待核验。")
    return head + points + task


def _rewrite_normal(entry) -> str:
    return entry.body


def _rewrite_en(entry) -> str:
    """确定性双语改写: 给出要点式英文导览 (非逐字机翻, 保留事实骨架)。"""
    title_map = {
        "青溪村概况": "Overview of Qingxi Village",
        "青溪竹编的历史源流": "History of Qingxi Bamboo Weaving",
        "竹编工序：从选竹到成器": "Bamboo Weaving: From Culm to Craft",
        "常见竹编纹样及寓意": "Common Bamboo Weaving Patterns",
        "竹编传承与研学体验": "Inheritance & Hands-on Experience",
        "青溪古廊桥": "The Qingxi Covered Bridge",
        "青溪老戏台与地方戏": "The Old Opera Stage & Local Opera",
        "村口古樟与风水林": "The Old Camphor Tree & Fengshui Grove",
        "青溪贡茶园": "Qingxi Tribute-Tea Garden",
        "青溪特色美食": "Local Delicacies of Qingxi",
        "青溪竹编节与年俗": "Bamboo Weaving Festival & Customs",
        "导览路线与慢行建议": "Walking Route & Tips",
        "竹编器物的保养": "Caring for Bamboo Wares",
        "毛竹与水竹的区别": "Moso Bamboo vs. Water Bamboo",
    }
    en_title = title_map.get(entry.title, entry.title)
    return (f"[{en_title}] This is an example guide note about "
            f"\"{entry.title}\" ({entry.theme}) in Qingxi Village. "
            f"The Chinese source text below is the authoritative content; "
            f"this English version is an AI-assisted summary for bilingual "
            f"visitors. All facts are illustrative and pending field "
            f"verification.\nSource (zh): {entry.body}")


_REWRITERS = {
    "children": _rewrite_children,
    "study": _rewrite_study,
    "normal": _rewrite_normal,
    "en": _rewrite_en,
}


def explain(entry_id: str, style: str = "normal",
            use_llm: bool = False, kb: KnowledgeBase | None = None) -> dict[str, Any]:
    """对指定资料条目做讲解改写, 返回改写文本 + 原始资料对照 + 引用。"""
    kb = kb or get_kb()
    entry = kb.get(entry_id)
    if entry is None:
        return {"error": f"未找到资料条目: {entry_id}"}
    style = style if style in _REWRITERS else "normal"
    rewritten = _REWRITERS[style](entry)
    source = "rule"

    if use_llm and llm_available():
        evidence_text = f"[1] {entry.title}: {entry.body}"
        llm_text = _llm_ground_answer(
            f"请把以下资料改写为{STYLES.get(style)}讲解，保留事实不变",
            [{"index": 1, "entry_id": entry.id}], evidence_text, style)
        if llm_text:
            rewritten = llm_text
            source = "llm"

    return {
        "entry_id": entry.id,
        "title": entry.title,
        "style": style,
        "style_name": STYLES.get(style, style),
        "rewritten": rewritten,
        "original": entry.body,              # 原文对照
        "citation": entry.citation(),
        "source": source,
        "ai_notice": "本讲解为 AI 按风格改写，事实以原始资料为准，内容为示例/待核验。",
    }


# --------------------------------------------------------------------------
# 导览叙事脚本: 供浏览器 Web Speech API 语音播报 (离线可运行的"音频导览"替代)
# --------------------------------------------------------------------------
def narration(kb: KnowledgeBase | None = None) -> dict[str, Any]:
    """按路线顺序生成分段讲解词, 前端用 SpeechSynthesis 逐段播报。"""
    kb = kb or get_kb()
    route = kb.route_detail()
    segments = []
    for i, stop in enumerate(route["stops"], start=1):
        entry = kb.get(stop["entry_id"])
        if not entry:
            continue
        text = (f"第{i}站，{stop['name']}。"
                + "".join(_split_sentences(entry.body)[:2]))
        segments.append({
            "order": i,
            "poi_id": stop["poi_id"],
            "name": stop["name"],
            "text": text,
            "entry_id": entry.id,
            "citation": entry.citation(),
        })
    return {
        "route_name": route["name"],
        "walk_minutes": route["walk_minutes"],
        "note": route["note"],
        "tts": "浏览器 Web Speech API (SpeechSynthesisUtterance, lang=zh-CN)，无需联网或外部模型",
        "segments": segments,
    }


if __name__ == "__main__":
    for q in ["青溪竹编的历史", "竹编怎么保养", "青溪村的人口有多少万", "量子计算原理"]:
        r = answer(q)
        tag = "作答" if r["answered"] else "拒答"
        print(f"\n[{tag}] {q}  (score={r['assessment']['top_score']:.2f} "
              f"ans={r['assessment']['answerability']:.2f})")
        print("  →", r["answer"][:80])
