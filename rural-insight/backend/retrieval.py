# -*- coding: utf-8 -*-
"""
retrieval.py — 乡声导览 确定性检索引擎 (纯 Python 标准库)

对中文资料库做【确定性、可复现、可解释】的检索排序, 不依赖外部模型:
  - 分词: 对中文按【单字 + 相邻二元(bigram)】切分, 兼顾召回与短语匹配;
    英文/数字按单词切分并小写化;
  - 排序: 采用轻量 BM25 (Okapi) 打分, 叠加标题与标签命中加权;
  - 输出: 每条结果给出得分、命中词与来源引用, 便于答辩演示与评审复核。

检索分数同时用于【拒答判定】: 当最高分低于阈值或归一化置信度不足时,
问答层据此回答"资料不足", 不编造事实。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from kb import Entry, KnowledgeBase, get_kb

# BM25 参数 (经验值, 对短文档库稳健)
_K1 = 1.5
_B = 0.75
# 标题 / 标签命中的额外加权
_TITLE_BOOST = 2.2
_TAG_BOOST = 1.6

_CJK = r"\u4e00-\u9fff"
_WORD_RE = re.compile(rf"[{_CJK}]|[a-zA-Z0-9]+")


def tokenize(text: str) -> list[str]:
    """中文单字 + 相邻二元 + 英文单词。全部小写。"""
    if not text:
        return []
    toks: list[str] = []
    atoms = _WORD_RE.findall(text.lower())
    cjk_run: list[str] = []

    def flush_run():
        # 为连续中文串追加相邻二元, 提升短语区分度
        for i in range(len(cjk_run) - 1):
            toks.append(cjk_run[i] + cjk_run[i + 1])
        cjk_run.clear()

    for a in atoms:
        if len(a) == 1 and re.match(rf"[{_CJK}]", a):
            toks.append(a)
            cjk_run.append(a)
        else:
            flush_run()
            toks.append(a)
    flush_run()
    return toks


@dataclass
class Hit:
    entry: Entry
    score: float
    norm_score: float          # 相对最高分归一化 (0~1)
    matched_terms: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry.id,
            "title": self.entry.title,
            "score": round(self.score, 4),
            "norm_score": round(self.norm_score, 4),
            "matched_terms": self.matched_terms,
            "snippet": self.entry.body[:120],
            "citation": self.entry.citation(),
        }


class Retriever:
    """基于 BM25 的确定性检索器。"""

    def __init__(self, kb: KnowledgeBase | None = None):
        self.kb = kb or get_kb()
        self._docs: list[Entry] = self.kb.all_entries()
        self._doc_tokens: list[list[str]] = []
        self._doc_tf: list[dict[str, int]] = []
        self._title_tokens: list[set[str]] = []
        self._tag_tokens: list[set[str]] = []
        self._df: dict[str, int] = {}
        self._avgdl = 1.0
        self._build()

    def _build(self) -> None:
        total_len = 0
        for e in self._docs:
            body_toks = tokenize(e.body) + tokenize(e.title) * 2 \
                + tokenize(" ".join(e.tags))
            self._doc_tokens.append(body_toks)
            tf: dict[str, int] = {}
            for t in body_toks:
                tf[t] = tf.get(t, 0) + 1
            self._doc_tf.append(tf)
            total_len += len(body_toks)
            self._title_tokens.append(set(tokenize(e.title)))
            self._tag_tokens.append(set(tokenize(" ".join(e.tags))))
            for t in set(body_toks):
                self._df[t] = self._df.get(t, 0) + 1
        n = max(1, len(self._docs))
        self._avgdl = total_len / n

    def _idf(self, term: str) -> float:
        n = len(self._docs)
        df = self._df.get(term, 0)
        # BM25 idf, 保证非负
        return max(0.0, math.log(1 + (n - df + 0.5) / (df + 0.5)))

    # 公开给问答层使用: 词的 IDF 与某条目的 token 集合
    def term_idf(self, term: str) -> float:
        return self._idf(term)

    def doc_freq(self, term: str) -> int:
        return self._df.get(term, 0)

    def entry_tokens(self, entry_id: str) -> set[str]:
        for i, e in enumerate(self._docs):
            if e.id == entry_id:
                return set(self._doc_tokens[i])
        return set()

    def search(self, query: str, top_k: int = 5) -> list[Hit]:
        q_terms = [t for t in dict.fromkeys(tokenize(query))]  # 去重保序
        if not q_terms:
            return []
        scored: list[Hit] = []
        for i, e in enumerate(self._docs):
            tf = self._doc_tf[i]
            dl = max(1, len(self._doc_tokens[i]))
            score = 0.0
            matched: list[str] = []
            for term in q_terms:
                f = tf.get(term, 0)
                if f == 0:
                    continue
                idf = self._idf(term)
                denom = f + _K1 * (1 - _B + _B * dl / self._avgdl)
                term_score = idf * (f * (_K1 + 1)) / denom
                if term in self._title_tokens[i]:
                    term_score *= _TITLE_BOOST
                elif term in self._tag_tokens[i]:
                    term_score *= _TAG_BOOST
                score += term_score
                if len(term) > 1 or re.match(rf"[{_CJK}]", term):
                    matched.append(term)
            if score > 0:
                scored.append(Hit(entry=e, score=score, norm_score=0.0,
                                   matched_terms=matched))
        scored.sort(key=lambda h: h.score, reverse=True)
        top = scored[:top_k]
        if top:
            best = top[0].score
            for h in top:
                h.norm_score = h.score / best if best > 0 else 0.0
        return top


# 单例
_DEFAULT_RETRIEVER: Retriever | None = None


def get_retriever() -> Retriever:
    global _DEFAULT_RETRIEVER
    if _DEFAULT_RETRIEVER is None:
        _DEFAULT_RETRIEVER = Retriever()
    return _DEFAULT_RETRIEVER


if __name__ == "__main__":
    r = get_retriever()
    for q in ["竹编怎么做", "廊桥", "青溪村的人口有多少"]:
        print(f"\n问: {q}")
        for h in r.search(q, top_k=3):
            print(f"  [{h.score:.3f} / norm={h.norm_score:.2f}] {h.entry.title} "
                  f"命中={h.matched_terms[:6]}")
