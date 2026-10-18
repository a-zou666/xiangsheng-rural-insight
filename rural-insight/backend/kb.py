# -*- coding: utf-8 -*-
"""
kb.py — 乡声·乡村文化 AI 导览 知识库加载层 (纯 Python 标准库)

职责:
  1. 从 data/culture_kb.json 加载【有来源标注的乡村文化示例资料库】;
  2. 提供资料条目 (entry)、点位 (POI)、路线 (route)、版本记录 (versions) 的访问;
  3. 汇总人工审核状态与版本信息, 供文档/前端/评估核验。

设计约束:
  - 无第三方依赖, 便于离线运行与评审复核;
  - 资料均为【示例/待实地核验】内容, 来源字段必须随条目一起返回,
    供带引用的检索增强问答与原创性/合规披露使用。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

DATA_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
)
KB_FILE = os.path.join(DATA_DIR, "culture_kb.json")


@dataclass
class Entry:
    id: str
    title: str
    village: str
    theme: str
    category: str
    body: str
    tags: list[str] = field(default_factory=list)
    source: dict[str, Any] = field(default_factory=dict)
    review: dict[str, Any] = field(default_factory=dict)
    version: str = ""
    updated: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "title": self.title, "village": self.village,
            "theme": self.theme, "category": self.category, "body": self.body,
            "tags": list(self.tags), "source": dict(self.source),
            "review": dict(self.review), "version": self.version,
            "updated": self.updated,
        }

    def citation(self) -> dict[str, Any]:
        """供带引用回答使用的精简来源信息。"""
        src = self.source or {}
        return {
            "entry_id": self.id,
            "title": self.title,
            "source_name": src.get("name", "未标注来源"),
            "source_type": src.get("type", ""),
            "ref": src.get("ref", ""),
            "license": src.get("license", ""),
            "collected": src.get("collected", ""),
            "review_status": (self.review or {}).get("status", ""),
        }


class KnowledgeBase:
    """加载并封装乡村文化示例资料库。"""

    def __init__(self, path: str | None = None):
        self.path = path or KB_FILE
        with open(self.path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        self.meta: dict[str, Any] = raw.get("meta", {})
        self.entries: list[Entry] = [
            Entry(
                id=e["id"], title=e["title"], village=e.get("village", ""),
                theme=e.get("theme", ""), category=e.get("category", ""),
                body=e.get("body", ""), tags=e.get("tags", []),
                source=e.get("source", {}), review=e.get("review", {}),
                version=e.get("version", ""), updated=e.get("updated", ""),
            )
            for e in raw.get("entries", [])
        ]
        self._by_id: dict[str, Entry] = {e.id: e for e in self.entries}
        self.pois: list[dict[str, Any]] = raw.get("pois", [])
        self.route: dict[str, Any] = raw.get("route", {})
        self.versions: list[dict[str, Any]] = raw.get("versions", [])

    # -- 基础访问 ---------------------------------------------------------
    def get(self, entry_id: str) -> Entry | None:
        return self._by_id.get(entry_id)

    def all_entries(self) -> list[Entry]:
        return list(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    # -- 点位 / 路线 ------------------------------------------------------
    def pois_with_entries(self) -> list[dict[str, Any]]:
        """点位附带其关联资料条目的标题与引用, 便于前端点位卡片。"""
        out = []
        for p in sorted(self.pois, key=lambda x: x.get("order", 0)):
            e = self.get(p.get("entry_id", ""))
            item = dict(p)
            if e:
                item["entry_title"] = e.title
                item["citation"] = e.citation()
            out.append(item)
        return out

    def route_detail(self) -> dict[str, Any]:
        """路线及其有序点位详情。"""
        stops = []
        poi_map = {p["id"]: p for p in self.pois}
        for sid in self.route.get("stops", []):
            p = poi_map.get(sid)
            if not p:
                continue
            e = self.get(p.get("entry_id", ""))
            stops.append({
                "poi_id": sid,
                "name": p.get("name", ""),
                "intro": p.get("intro", ""),
                "entry_id": p.get("entry_id", ""),
                "entry_title": e.title if e else "",
            })
        return {
            "name": self.route.get("name", ""),
            "walk_minutes": self.route.get("walk_minutes"),
            "note": self.route.get("note", ""),
            "stops": stops,
        }

    # -- 审核 / 版本 ------------------------------------------------------
    def review_summary(self) -> dict[str, Any]:
        """汇总人工审核状态, 供合规披露与前端审核台展示。"""
        by_status: dict[str, int] = {}
        rows = []
        for e in self.entries:
            status = (e.review or {}).get("status", "unreviewed")
            by_status[status] = by_status.get(status, 0) + 1
            rows.append({
                "entry_id": e.id,
                "title": e.title,
                "reviewer": (e.review or {}).get("reviewer", ""),
                "status": status,
                "note": (e.review or {}).get("note", ""),
                "version": e.version,
                "updated": e.updated,
                "source_type": (e.source or {}).get("type", ""),
            })
        return {
            "total": len(self.entries),
            "by_status": by_status,
            "rows": rows,
            "kb_version": self.meta.get("version", ""),
            "versions": self.versions,
        }

    def source_types(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self.entries:
            t = (e.source or {}).get("type", "未标注")
            counts[t] = counts.get(t, 0) + 1
        return counts


# 单例, 供 server / 测试复用
_DEFAULT_KB: KnowledgeBase | None = None


def get_kb() -> KnowledgeBase:
    global _DEFAULT_KB
    if _DEFAULT_KB is None:
        _DEFAULT_KB = KnowledgeBase()
    return _DEFAULT_KB


if __name__ == "__main__":
    kb = get_kb()
    print(f"知识库: {kb.meta.get('product')} / 村落={kb.meta.get('village')} "
          f"主题={kb.meta.get('theme')}")
    print(f"条目 {len(kb)} 条, 点位 {len(kb.pois)} 个, 版本记录 {len(kb.versions)} 条")
    print("来源类型分布:", kb.source_types())
    print("审核汇总:", kb.review_summary()["by_status"])
