#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
乡数智见 - 示例数据生成器 (gen_data.py)

生成「县域乡村振兴」主题的多维合成数据集 (CSV, UTF-8-SIG)。
数据为【合成示例数据】: 使用固定随机种子按真实统计规律(趋势+季节+噪声)生成,
用于平台功能演示与评审复核, 不代表任何真实县域的真实统计数字。

设计口径参考国家乡村振兴"五大振兴"框架:
  产业振兴 / 人才振兴 / 文化振兴 / 生态振兴 / 组织振兴

运行:  python gen_data.py
输出:  与本脚本同目录下的若干 .csv 文件 + 数据来源说明.txt
"""
import csv
import math
import os
import random

SEED = 20261011
random.seed(SEED)

HERE = os.path.dirname(os.path.abspath(__file__))

# 6 个虚构示例县 (名称虚构, 避免与真实行政区混淆)
COUNTIES = ["青溪县", "云岭县", "丰禾县", "石门县", "临江县", "和顺县"]
# 每个县一个"发展基线系数", 使县与县之间有差异
BASE = {
    "青溪县": 1.00,  # 产业强县
    "云岭县": 0.72,  # 生态/旅游型
    "丰禾县": 0.88,  # 农业大县
    "石门县": 0.60,  # 后发县
    "临江县": 0.95,  # 电商活跃
    "和顺县": 0.78,  # 文旅融合
}
YEARS = list(range(2015, 2025))  # 2015-2024, 10 年


def jitter(scale=0.03):
    """返回一个 1±scale 范围内的乘性噪声。"""
    return 1.0 + random.uniform(-scale, scale)


def grow(base, year, rate, start=2015):
    """按复合增长率从 start 年推进到 year 年。"""
    return base * ((1.0 + rate) ** (year - start))


def write_csv(name, header, rows):
    path = os.path.join(HERE, name)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"  已生成 {name}: {len(rows)} 行")


def gen_economy():
    """县域经济与收入 (产业振兴核心指标)。"""
    rows = []
    for c in COUNTIES:
        b = BASE[c]
        gdp0 = 320000 * b          # 2015 GDP (万元)
        inc0 = 11800 * b           # 2015 农村居民人均可支配收入 (元)
        pov0 = 8.5 * (1.4 - b)     # 2015 贫困发生率 (%), 后发县更高
        for y in YEARS:
            gdp = grow(gdp0, y, 0.075) * jitter()
            primary = gdp * (0.18 - 0.004 * (y - 2015)) * jitter()  # 第一产业占比缓降
            inc = grow(inc0, y, 0.085) * jitter()
            # 贫困发生率: 2020 年后基本清零(脱贫攻坚), 之后记为 0
            if y <= 2020:
                pov = max(0.0, pov0 * (1 - 0.22 * (y - 2015)) * jitter())
            else:
                pov = 0.0
            rows.append([y, c, round(gdp, 1), round(primary, 1),
                         round(inc, 0), round(pov, 2)])
    write_csv("county_economy.csv",
              ["年份", "县域", "地区生产总值_万元", "第一产业增加值_万元",
               "农村居民人均可支配收入_元", "贫困发生率_百分比"], rows)


def gen_agriculture():
    """主要农产品产量 (产业振兴 - 农业生产)。"""
    products = {
        "粮食": (185000, 0.025),
        "蔬菜": (92000, 0.06),
        "水果": (48000, 0.08),
        "畜牧": (36000, 0.05),
        "水产": (12000, 0.07),
    }
    rows = []
    for c in COUNTIES:
        b = BASE[c]
        for prod, (base0, rate) in products.items():
            out0 = base0 * b
            area0 = out0 / (random.uniform(1.6, 2.4))  # 粗略单产换算播种面积(亩)
            for y in YEARS:
                out = grow(out0, y, rate) * jitter(0.05)
                area = grow(area0, y, rate * 0.4) * jitter(0.04)
                rows.append([y, c, prod, round(out, 1), round(area, 0)])
    write_csv("agriculture_output.csv",
              ["年份", "县域", "农产品类别", "产量_吨", "播种面积_亩"], rows)


def gen_population():
    """人口与人才 (人才振兴 - 劳动力外流/返乡创业)。"""
    rows = []
    for c in COUNTIES:
        b = BASE[c]
        tot0 = 420000 * (0.7 + 0.6 * b)
        for y in YEARS:
            tot = tot0 * (1 - 0.004 * (y - 2015)) * jitter(0.01)
            rural_ratio = max(0.42, 0.68 - 0.012 * (y - 2015))  # 城镇化推进
            rural = tot * rural_ratio
            outflow = rural * (0.26 - 0.006 * (y - 2015)) * jitter(0.04)  # 外出务工
            # 返乡创业: 近年政策推动, 2018 后快速上升
            returnees = max(0, (y - 2017)) * 820 * b * jitter(0.08)
            rows.append([y, c, round(tot, 0), round(rural, 0),
                         round(outflow, 0), round(returnees, 0)])
    write_csv("population.csv",
              ["年份", "县域", "常住人口_人", "乡村常住人口_人",
               "外出务工劳动力_人", "返乡创业人数_人"], rows)


def gen_ecology():
    """生态与人居环境 (生态振兴)。"""
    rows = []
    for c in COUNTIES:
        b = BASE[c]
        forest0 = 38 + 18 * (1.4 - b)   # 后发/山区县森林覆盖更高
        land0 = 540000 * b
        for y in YEARS:
            forest = min(72.0, forest0 + 0.5 * (y - 2015)) * jitter(0.01)
            land = land0 * (1 - 0.002 * (y - 2015)) * jitter(0.01)
            sewage = min(96.0, 32 + 6.2 * (y - 2015)) * jitter(0.02)      # 污水处理率
            waste = min(99.0, 45 + 5.4 * (y - 2015)) * jitter(0.02)       # 生活垃圾处理率
            rows.append([y, c, round(forest, 2), round(land, 0),
                         round(sewage, 1), round(waste, 1)])
    write_csv("ecology.csv",
              ["年份", "县域", "森林覆盖率_百分比", "耕地面积_亩",
               "农村污水处理率_百分比", "生活垃圾处理率_百分比"], rows)


def gen_digital():
    """数字乡村与电商 (产业振兴 - 新业态)。"""
    rows = []
    for c in COUNTIES:
        b = BASE[c]
        online0 = 6800 * b
        stores0 = 180 * b
        for y in YEARS:
            online = grow(online0, y, 0.26) * jitter(0.06)      # 农村网络零售额(万元)
            stores = grow(stores0, y, 0.20) * jitter(0.05)      # 活跃网店数
            logistics = min(100.0, 46 + 5.6 * (y - 2015)) * jitter(0.02)  # 物流到村覆盖率
            broadband = min(100.0, 58 + 4.4 * (y - 2015)) * jitter(0.015) # 宽带入户率
            rows.append([y, c, round(online, 1), round(stores, 0),
                         round(logistics, 1), round(broadband, 1)])
    write_csv("digital_economy.csv",
              ["年份", "县域", "农村网络零售额_万元", "活跃网店数_家",
               "物流到村覆盖率_百分比", "宽带入户率_百分比"], rows)


def gen_tourism():
    """乡村文旅 (文化振兴 + 产业融合)。"""
    rows = []
    for c in COUNTIES:
        b = BASE[c]
        # 文旅型县(云岭/和顺)基数更高
        tb = b * (1.6 if c in ("云岭县", "和顺县") else 1.0)
        vis0 = 85 * tb
        for y in YEARS:
            # 2020 年受疫情影响大幅下滑, 2021 起恢复
            shock = 0.45 if y == 2020 else (0.72 if y == 2021 else 1.0)
            vis = grow(vis0, y, 0.14) * shock * jitter(0.05)       # 游客(万人次)
            income = vis * random.uniform(85, 120) * jitter(0.04)  # 旅游收入(万元)
            homestay = grow(28 * tb, y, 0.22) * jitter(0.06)       # 民宿数量
            rows.append([y, c, round(vis, 1), round(income, 1), round(homestay, 0)])
    write_csv("tourism.csv",
              ["年份", "县域", "游客量_万人次", "旅游综合收入_万元", "民宿数量_家"], rows)


def gen_ecommerce_monthly():
    """电商月度销售额 (用于时序预测演示: 明显趋势 + 年度季节性 + 节假日峰值)。"""
    rows = []
    months = []
    for y in range(2021, 2025):          # 2021-01 .. 2024-12, 48 个月
        for m in range(1, 13):
            months.append((y, m))
    for c in COUNTIES:
        b = BASE[c]
        base_level = 520 * b             # 月销售额基准(万元)
        for i, (y, m) in enumerate(months):
            trend = base_level * (1.0 + 0.013) ** i          # 月复合增长 ~1.3%
            # 季节性: 1月(年货)、6月(618)、11月(双11)、12月 高峰; 2月春节后低谷
            seasonal = {
                1: 1.35, 2: 0.78, 3: 0.92, 4: 0.95, 5: 1.02, 6: 1.28,
                7: 0.98, 8: 0.97, 9: 1.05, 10: 1.08, 11: 1.52, 12: 1.30,
            }[m]
            val = trend * seasonal * jitter(0.04)
            rows.append([f"{y}-{m:02d}", c, round(val, 1)])
    write_csv("ecommerce_monthly.csv",
              ["月份", "县域", "农村网络零售额_万元"], rows)


def gen_governance():
    """乡村治理与集体经济 (组织振兴)。

    指标口径参考: 村级集体经济、基层党组织覆盖、村民自治(村务公开/议事参与)、
    平安乡村(矛盾调处/综治达标)。均为合成示例数据。
    """
    rows = []
    for c in COUNTIES:
        b = BASE[c]
        collect0 = 2600 * b          # 2015 村级集体经济总收入 (万元)
        villages = int(round(72 * (0.7 + 0.6 * b)))  # 行政村数量(用于村均)
        for y in YEARS:
            # 集体经济: 近年"消薄"行动推动, 增速较快
            collect = grow(collect0, y, 0.16) * jitter(0.05)
            per_village = collect / villages
            # 党组织覆盖率: 高基线并逐步接近 100%
            party = min(100.0, 94.0 + 0.7 * (y - 2015)) * jitter(0.004)
            party = min(100.0, party)
            # 村民自治参与率: 村务公开 + 村民议事参与, 稳步提升
            autonomy = min(98.0, 61 + 3.4 * (y - 2015) * (0.8 + 0.4 * b)) * jitter(0.02)
            # 平安乡村达标率: 综治/矛盾调处达标
            safety = min(99.5, 70 + 2.9 * (y - 2015)) * jitter(0.015)
            rows.append([y, c, round(collect, 1), round(per_village, 1),
                         round(party, 2), round(autonomy, 1), round(safety, 1)])
    write_csv("governance.csv",
              ["年份", "县域", "村级集体经济收入_万元", "村均集体经济收入_万元",
               "行政村党组织覆盖率_百分比", "村民自治参与率_百分比",
               "平安乡村达标率_百分比"], rows)


def write_source_note():
    note = """乡数智见 — 数据来源与合规说明
================================================

一、数据性质
本平台所用全部数据为【合成示例数据 (synthetic sample data)】。
由 data/gen_data.py 使用固定随机种子 (SEED=20261011) 按统计规律程序化生成,
确保任何人重新运行脚本都能得到完全一致的数据集 (可复现、可核验)。

二、生成口径
数据字段与量纲参照以下公开统计口径设计 (仅为口径参考, 数值非真实抽取):
  - 《中国农村统计年鉴》《中国县域统计年鉴》常见指标口径;
  - 国家乡村振兴"五大振兴"框架 (产业/人才/文化/生态/组织);
  - 国家统计局农村居民人均可支配收入、森林覆盖率等指标定义。
趋势假设 (如脱贫攻坚后 2021 年贫困发生率归零、2020 年文旅受疫情冲击、
电商年度季节性峰值在 6/11 月) 用于演示分析与预测能力。

三、县域名称
青溪/云岭/丰禾/石门/临江/和顺 均为【虚构县名】, 不指向任何真实行政区划,
以避免与真实县域真实数据产生混淆。

四、合规承诺
  - 未爬取、未使用任何真实个人信息或受限数据;
  - 若后续接入真实公开数据, 将严格标注来源 (如国家统计局、各省统计年鉴),
    并遵守其开放数据使用许可。

生成方式: python data/gen_data.py
"""
    path = os.path.join(HERE, "数据来源说明.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(note)
    print("  已生成 数据来源说明.txt")


def main():
    print("乡数智见 示例数据生成中 ...")
    gen_economy()
    gen_agriculture()
    gen_population()
    gen_ecology()
    gen_digital()
    gen_tourism()
    gen_governance()
    gen_ecommerce_monthly()
    write_source_note()
    print("全部数据生成完成。")


if __name__ == "__main__":
    main()
