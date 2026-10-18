#!/usr/bin/env bash
# 乡数智见 一键启动脚本 (Linux / macOS)
set -e
cd "$(dirname "$0")"
export PYTHONUTF8=1

PY=python3
command -v "$PY" >/dev/null 2>&1 || PY=python
command -v "$PY" >/dev/null 2>&1 || { echo "[错误] 未找到 python3，请先安装 Python 3.9+"; exit 1; }

echo "=== 乡数智见 启动中 ==="
echo "1) 若数据缺失，重新生成示例数据..."
[ -f data/county_economy.csv ] || "$PY" data/gen_data.py
[ -f data/counties.geojson ] || "$PY" data/gen_map.py

echo "2) 运行冒烟测试..."
"$PY" tests/smoke_test.py || echo "[警告] 冒烟测试未全部通过，仍将尝试启动服务。"

echo "3) 启动服务 http://127.0.0.1:8000/"
exec "$PY" backend/server.py --port 8000
