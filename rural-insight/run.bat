@echo off
chcp 65001 >nul
REM 乡数智见 一键启动脚本 (Windows)
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1

where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 未找到 python, 请先安装 Python 3.9+ 并加入 PATH。
  pause
  exit /b 1
)

echo === 乡数智见 启动中 ===
echo 1) 若数据缺失, 重新生成示例数据...
if not exist "data\county_economy.csv" (
  python data\gen_data.py
)
if not exist "data\counties.geojson" (
  python data\gen_map.py
)

echo 2) 运行冒烟测试...
python tests\smoke_test.py
if errorlevel 1 (
  echo [警告] 冒烟测试未全部通过, 仍将尝试启动服务。
)

echo 3) 启动服务 http://127.0.0.1:8000/
start "" "http://127.0.0.1:8000/"
python backend\server.py --port 8000
endlocal
