# -*- coding: utf-8 -*-
"""
data_engine.py — 乡数智见 数据引擎 (纯 Python 标准库)

职责:
  1. 加载 data/ 目录下的全部 CSV 为内存数据表 (Table);
  2. 提供统一的元数据目录 (CATALOG): 维度/度量/量纲/中文同义词;
  3. 提供通用查询: 过滤 + 分组 + 聚合 + 排序 + Top-N。

设计为无第三方依赖, 便于离线运行与评审复核。
"""
from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from typing import Any, Callable

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
DATA_DIR = os.path.normpath(DATA_DIR)


# --------------------------------------------------------------------------
# 元数据目录: 描述每个数据集的维度(可分组/筛选)与度量(可聚合), 以及中文同义词,
# 供自然语言问数模块做字段匹配。unit 用于前端显示与叙事。
# --------------------------------------------------------------------------
@dataclass
class Measure:
    key: str              # CSV 列名
    name: str             # 展示名
    unit: str             # 量纲
    synonyms: list[str] = field(default_factory=list)
    better: str = "high"  # high=越高越好, low=越低越好 (用于叙事判断)


@dataclass
class Dimension:
    key: str
    name: str
    synonyms: list[str] = field(default_factory=list)


@dataclass
class DatasetMeta:
    name: str                       # 数据集标识
    title: str                      # 中文标题
    file: str                       # CSV 文件名
    time_key: str                   # 时间维度列名 (年份 / 月份)
    time_name: str
    category: str                   # 五大振兴归类
    dimensions: list[Dimension]
    measures: list[Measure]
    synonyms: list[str] = field(default_factory=list)


CATALOG: dict[str, DatasetMeta] = {
    "economy": DatasetMeta(
        name="economy", title="县域经济与收入", file="county_economy.csv",
        time_key="年份", time_name="年份", category="产业振兴",
        synonyms=["经济", "gdp", "生产总值", "收入", "贫困", "脱贫", "产值"],
        dimensions=[Dimension("县域", "县域", ["县", "地区", "区域"])],
        measures=[
            Measure("地区生产总值_万元", "地区生产总值", "万元",
                    ["gdp", "生产总值", "经济总量", "产值"]),
            Measure("第一产业增加值_万元", "第一产业增加值", "万元",
                    ["第一产业", "农业产值", "一产"]),
            Measure("农村居民人均可支配收入_元", "农村居民人均可支配收入", "元",
                    ["收入", "人均收入", "可支配收入", "农民收入"]),
            Measure("贫困发生率_百分比", "贫困发生率", "%",
                    ["贫困", "贫困率", "脱贫"], better="low"),
        ],
    ),
    "agriculture": DatasetMeta(
        name="agriculture", title="主要农产品产量", file="agriculture_output.csv",
        time_key="年份", time_name="年份", category="产业振兴",
        synonyms=["农产品", "农业", "产量", "粮食", "蔬菜", "水果", "畜牧", "水产", "播种"],
        dimensions=[
            Dimension("县域", "县域", ["县", "地区", "区域"]),
            Dimension("农产品类别", "农产品类别", ["农产品", "品类", "作物", "类别"]),
        ],
        measures=[
            Measure("产量_吨", "产量", "吨", ["产量", "产出"]),
            Measure("播种面积_亩", "播种面积", "亩", ["面积", "播种面积", "耕种面积"]),
        ],
    ),
    "population": DatasetMeta(
        name="population", title="人口与人才", file="population.csv",
        time_key="年份", time_name="年份", category="人才振兴",
        synonyms=["人口", "人才", "劳动力", "外出务工", "返乡", "创业"],
        dimensions=[Dimension("县域", "县域", ["县", "地区", "区域"])],
        measures=[
            Measure("常住人口_人", "常住人口", "人", ["人口", "常住人口"]),
            Measure("乡村常住人口_人", "乡村常住人口", "人", ["乡村人口", "农村人口"]),
            Measure("外出务工劳动力_人", "外出务工劳动力", "人",
                    ["外出务工", "外流", "务工", "劳动力外流"], better="low"),
            Measure("返乡创业人数_人", "返乡创业人数", "人",
                    ["返乡", "返乡创业", "创业", "回流"]),
        ],
    ),
    "ecology": DatasetMeta(
        name="ecology", title="生态与人居环境", file="ecology.csv",
        time_key="年份", time_name="年份", category="生态振兴",
        synonyms=["生态", "环境", "森林", "耕地", "污水", "垃圾", "人居"],
        dimensions=[Dimension("县域", "县域", ["县", "地区", "区域"])],
        measures=[
            Measure("森林覆盖率_百分比", "森林覆盖率", "%", ["森林", "森林覆盖", "绿化"]),
            Measure("耕地面积_亩", "耕地面积", "亩", ["耕地", "农田"]),
            Measure("农村污水处理率_百分比", "农村污水处理率", "%", ["污水", "污水处理"]),
            Measure("生活垃圾处理率_百分比", "生活垃圾处理率", "%", ["垃圾", "垃圾处理"]),
        ],
    ),
    "digital": DatasetMeta(
        name="digital", title="数字乡村与电商", file="digital_economy.csv",
        time_key="年份", time_name="年份", category="产业振兴",
        synonyms=["电商", "网络零售", "数字乡村", "网店", "物流", "宽带", "数字"],
        dimensions=[Dimension("县域", "县域", ["县", "地区", "区域"])],
        measures=[
            Measure("农村网络零售额_万元", "农村网络零售额", "万元",
                    ["电商", "网络零售", "网店销售", "线上零售", "网络零售额"]),
            Measure("活跃网店数_家", "活跃网店数", "家", ["网店", "店铺", "网店数"]),
            Measure("物流到村覆盖率_百分比", "物流到村覆盖率", "%", ["物流", "物流覆盖"]),
            Measure("宽带入户率_百分比", "宽带入户率", "%", ["宽带", "网络入户", "宽带入户"]),
        ],
    ),
    "tourism": DatasetMeta(
        name="tourism", title="乡村文旅", file="tourism.csv",
        time_key="年份", time_name="年份", category="文化振兴",
        synonyms=["文旅", "旅游", "游客", "民宿", "旅游收入", "文化"],
        dimensions=[Dimension("县域", "县域", ["县", "地区", "区域"])],
        measures=[
            Measure("游客量_万人次", "游客量", "万人次", ["游客", "客流", "游客量"]),
            Measure("旅游综合收入_万元", "旅游综合收入", "万元",
                    ["旅游收入", "文旅收入", "旅游综合收入"]),
            Measure("民宿数量_家", "民宿数量", "家", ["民宿", "农家乐"]),
        ],
    ),
    "governance": DatasetMeta(
        name="governance", title="乡村治理与集体经济", file="governance.csv",
        time_key="年份", time_name="年份", category="组织振兴",
        synonyms=["治理", "组织", "集体经济", "党组织", "自治", "平安", "村级"],
        dimensions=[Dimension("县域", "县域", ["县", "地区", "区域"])],
        measures=[
            Measure("村级集体经济收入_万元", "村级集体经济收入", "万元",
                    ["集体经济", "村集体", "集体经济收入"]),
            Measure("村均集体经济收入_万元", "村均集体经济收入", "万元",
                    ["村均集体经济", "村均收入"]),
            Measure("行政村党组织覆盖率_百分比", "行政村党组织覆盖率", "%",
                    ["党组织", "党建", "组织覆盖"]),
            Measure("村民自治参与率_百分比", "村民自治参与率", "%",
                    ["自治", "村民自治", "村务公开", "议事参与"]),
            Measure("平安乡村达标率_百分比", "平安乡村达标率", "%",
                    ["平安乡村", "平安", "综治", "治安"]),
        ],
    ),
    "ecommerce_monthly": DatasetMeta(
        name="ecommerce_monthly", title="电商月度销售额", file="ecommerce_monthly.csv",
        time_key="月份", time_name="月份", category="产业振兴",
        synonyms=["月度", "每月", "电商月度", "销售额", "月销售"],
        dimensions=[Dimension("县域", "县域", ["县", "地区", "区域"])],
        measures=[
            Measure("农村网络零售额_万元", "农村网络零售额", "万元",
                    ["电商", "网络零售", "销售额", "网络零售额", "月销售额"]),
        ],
    ),
}


# --------------------------------------------------------------------------
# 数据表
# --------------------------------------------------------------------------
class Table:
    def __init__(self, meta: DatasetMeta, rows: list[dict[str, Any]]):
        self.meta = meta
        self.rows = rows

    def __len__(self):
        return len(self.rows)


def _coerce(value: str) -> Any:
    """尝试把字符串转为数值, 失败则原样返回。"""
    v = value.strip()
    if v == "":
        return None
    try:
        if "." in v:
            return float(v)
        return int(v)
    except ValueError:
        return v


class DataEngine:
    def __init__(self, data_dir: str = DATA_DIR):
        self.data_dir = data_dir
        self.tables: dict[str, Table] = {}
        self._load_all()

    def _load_all(self):
        for key, meta in CATALOG.items():
            path = os.path.join(self.data_dir, meta.file)
            if not os.path.exists(path):
                continue
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                rows = []
                for raw in reader:
                    row = {k: _coerce(v) for k, v in raw.items()}
                    rows.append(row)
            self.tables[key] = Table(meta, rows)

    # ---- 元数据接口 ----
    def catalog_summary(self) -> list[dict[str, Any]]:
        out = []
        for key, meta in CATALOG.items():
            if key not in self.tables:
                continue
            out.append({
                "name": key,
                "title": meta.title,
                "category": meta.category,
                "time": meta.time_name,
                "rows": len(self.tables[key]),
                "dimensions": [d.name for d in meta.dimensions],
                "measures": [{"name": m.name, "unit": m.unit} for m in meta.measures],
            })
        return out

    def distinct(self, dataset: str, dim: str) -> list[Any]:
        t = self.tables[dataset]
        seen = []
        for r in t.rows:
            v = r.get(dim)
            if v is not None and v not in seen:
                seen.append(v)
        return seen

    # ---- 通用查询 ----
    def query(
        self,
        dataset: str,
        measure: str,
        group_by: str,
        agg: str = "sum",
        filters: dict[str, Any] | None = None,
        order: str | None = None,       # "asc" | "desc" | None(按分组键自然序)
        top_n: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        返回 [{"key": 分组值, "value": 聚合值}, ...]。
        agg: sum | avg | max | min | count | last (last=按时间取最新值)
        """
        if dataset not in self.tables:
            raise ValueError(f"未知数据集: {dataset}")
        t = self.tables[dataset]
        meta = t.meta
        rows = t.rows
        if filters:
            rows = [r for r in rows if all(r.get(k) == v for k, v in filters.items())]

        buckets: dict[Any, list[Any]] = {}
        time_vals: dict[Any, list[tuple[Any, Any]]] = {}
        for r in rows:
            gkey = r.get(group_by)
            if gkey is None:
                continue
            val = r.get(measure)
            if val is None and agg != "count":
                continue
            buckets.setdefault(gkey, []).append(val)
            time_vals.setdefault(gkey, []).append((r.get(meta.time_key), val))

        result = []
        for gkey, vals in buckets.items():
            nums = [v for v in vals if isinstance(v, (int, float))]
            if agg == "sum":
                value = sum(nums)
            elif agg == "avg":
                value = sum(nums) / len(nums) if nums else 0
            elif agg == "max":
                value = max(nums) if nums else 0
            elif agg == "min":
                value = min(nums) if nums else 0
            elif agg == "count":
                value = len(vals)
            elif agg == "last":
                pairs = sorted(time_vals[gkey], key=lambda p: str(p[0]))
                value = pairs[-1][1] if pairs else 0
            else:
                raise ValueError(f"未知聚合: {agg}")
            result.append({"key": gkey, "value": round(value, 2)
                           if isinstance(value, float) else value})

        # 排序
        if order == "desc":
            result.sort(key=lambda x: (x["value"] is None, x["value"]), reverse=True)
        elif order == "asc":
            result.sort(key=lambda x: (x["value"] is None, x["value"]))
        else:
            result.sort(key=lambda x: str(x["key"]))

        if top_n:
            result = result[:top_n]
        return result

    def series(
        self,
        dataset: str,
        measure: str,
        entity: str | None = None,
        entity_dim: str = "县域",
    ) -> tuple[list[Any], list[float]]:
        """返回按时间排序的 (时间标签, 数值) 时间序列; entity=None 时按时间汇总所有实体。"""
        t = self.tables[dataset]
        meta = t.meta
        rows = t.rows
        if entity is not None:
            rows = [r for r in rows if r.get(entity_dim) == entity]
        agg_by_time: dict[Any, float] = {}
        for r in rows:
            tk = r.get(meta.time_key)
            v = r.get(measure)
            if tk is None or not isinstance(v, (int, float)):
                continue
            agg_by_time[tk] = agg_by_time.get(tk, 0.0) + v
        labels = sorted(agg_by_time.keys(), key=lambda x: str(x))
        values = [round(agg_by_time[k], 2) for k in labels]
        return labels, values


if __name__ == "__main__":
    eng = DataEngine()
    print("已加载数据集:")
    for item in eng.catalog_summary():
        print(f"  [{item['category']}] {item['title']} ({item['name']}): "
              f"{item['rows']} 行, 维度={item['dimensions']}, "
              f"度量={[m['name'] for m in item['measures']]}")
    print("\n示例查询: 2024 年各县农村网络零售额 (降序)")
    for row in eng.query("digital", "农村网络零售额_万元", "县域",
                         agg="sum", filters={"年份": 2024}, order="desc"):
        print(f"  {row['key']}: {row['value']} 万元")
