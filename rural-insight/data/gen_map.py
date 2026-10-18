#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_map.py — 生成 6 个示例县的【示意地图】GeoJSON (counties.geojson)

说明: 为保证作品完全离线且不涉及任何真实行政区划边界, 本脚本以固定随机种子
程序化生成 6 个相互独立的"示意区块"多边形(非真实地理边界), 供 ECharts
registerMap 渲染县域 choropleth 使用。区块排布为 2 行 × 3 列, 并带有机抖动边缘,
使其在视觉上形成一张可着色的县域分布图。

运行:  python gen_map.py   →   与本脚本同目录下 counties.geojson
"""
import json
import math
import os
import random

SEED = 20261011
random.seed(SEED)

HERE = os.path.dirname(os.path.abspath(__file__))

# 与 gen_data.py 保持一致的县名与排布
LAYOUT = [
    ["青溪县", "云岭县", "丰禾县"],
    ["石门县", "临江县", "和顺县"],
]

CELL_W = 11.0
CELL_H = 11.0
RADIUS = 4.6
N_POINTS = 28       # 边界采样点数


def blob(cx, cy, r, phase):
    """以 (cx,cy) 为中心生成一个带有机抖动的闭合多边形环。"""
    ring = []
    for i in range(N_POINTS):
        theta = 2 * math.pi * i / N_POINTS
        # 低频起伏 + 轻微随机, 形成自然的区块轮廓
        wobble = (1.0
                  + 0.16 * math.sin(3 * theta + phase)
                  + 0.08 * math.cos(5 * theta + phase * 0.7)
                  + random.uniform(-0.04, 0.04))
        x = cx + r * wobble * math.cos(theta)
        y = cy + r * wobble * math.sin(theta)
        ring.append([round(x, 3), round(y, 3)])
    ring.append(ring[0])  # 闭合
    return ring


def main():
    features = []
    for row, names in enumerate(LAYOUT):
        for col, name in enumerate(names):
            cx = col * CELL_W + CELL_W / 2
            # 行序翻转: 让第一行在上方(较大 y)
            cy = (len(LAYOUT) - 1 - row) * CELL_H + CELL_H / 2
            phase = random.uniform(0, 2 * math.pi)
            ring = blob(cx, cy, RADIUS, phase)
            features.append({
                "type": "Feature",
                "properties": {"name": name, "cp": [round(cx, 3), round(cy, 3)]},
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            })
    fc = {"type": "FeatureCollection", "features": features}
    path = os.path.join(HERE, "counties.geojson")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False)
    print(f"  已生成 counties.geojson: {len(features)} 个县区块")


if __name__ == "__main__":
    main()
