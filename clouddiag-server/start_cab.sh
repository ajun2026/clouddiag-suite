#!/bin/bash
# 云端AI远程运维助手 启动脚本 — 脱离 Hermes 进程组（本机部署）
# 2026-09-20：改为脚本自身目录推导——项目放在任意路径都可运行（原为开发机绝对路径）
set -e
cd "$(dirname "$(readlink -f "$0")")"

# 确保日志目录存在
mkdir -p logs

exec ./venv/bin/python server.py >> logs/server.log 2>&1
