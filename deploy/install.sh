#!/bin/bash
# CloudDiag Suite 交互式一键部署脚本
# 2026-09-21
#
# 用法：bash install.sh
# 作用：引导选择部署形态与端口 → 生成 .env → 装依赖 → 起服务 → 自检

set -e

C_GREEN='\033[0;32m'; C_YELLOW='\033[1;33m'; C_RED='\033[0;31m'; C_BLUE='\033[0;34m'; C_NC='\033[0m'

SUITE_DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
SERVER_DIR="$SUITE_DIR/clouddiag-server"
ANALYZER_DIR="$SUITE_DIR/log-analyzer"

echo "=================================================="
echo " CloudDiag Suite · 交互式部署"
echo "=================================================="
echo " 项目目录: $SUITE_DIR"
echo ""

# ── 0. 前置检查 ──────────────────────────────────
if [ ! -d "$SERVER_DIR" ] || [ ! -d "$ANALYZER_DIR" ]; then
    echo -e "${C_RED}错误: 未找到 clouddiag-server / log-analyzer 目录${C_NC}"
    echo "请确认脚本位于 <项目>/deploy/ 目录下"
    exit 1
fi
if [ "$(id -u)" = "0" ]; then
    echo -e "${C_YELLOW}提示: 建议以普通用户运行（需要 sudo 时会提示），当前为 root${C_NC}"
    echo ""
fi

# ── 1. 部署形态 ──────────────────────────────────
echo -e "${C_BLUE}[1/6] 部署形态${C_NC}"
echo ""
echo "  1) 纯 HTTP（只有服务器 IP，没有域名）—— 最简单"
echo "  2) 域名 + HTTPS（有域名，自动申请证书）"
echo ""
read -p " 请选择 [1/2] (默认 1): " FORM_CHOICE
FORM_CHOICE=${FORM_CHOICE:-1}

if [ "$FORM_CHOICE" = "2" ]; then
    FORM="https"
    read -p " 请输入你的域名 (例如 diag.example.com): " DOMAIN
    [ -z "$DOMAIN" ] && { echo -e "${C_RED}域名不能为空${C_NC}"; exit 1; }
    PUBLIC_URL="https://$DOMAIN"
    COOKIE_SECURE="true"
    echo -e " ${C_GREEN}✓ 形态: 域名 + HTTPS ($DOMAIN)${C_NC}"
else
    FORM="http"
    read -p " 请输入服务器公网 IP: " PUB_IP
    [ -z "$PUB_IP" ] && { echo -e "${C_RED}IP 不能为空${C_NC}"; exit 1; }
    PUBLIC_URL="http://$PUB_IP:8000"
    COOKIE_SECURE="false"
    echo -e " ${C_GREEN}✓ 形态: 纯 HTTP${C_NC}"
fi
echo ""

# ── 2. 端口 ──────────────────────────────────────
echo -e "${C_BLUE}[2/6] 端口配置${C_NC}"
echo ""
read -p " 诊断服务端口 (默认 8000): " SERVER_PORT
SERVER_PORT=${SERVER_PORT:-8000}
read -p " 日志分析服务端口 (默认 8082): " ANALYZER_PORT
ANALYZER_PORT=${ANALYZER_PORT:-8082}
# HTTP 形态下 PUBLIC_URL 要带上实际端口
if [ "$FORM" = "http" ]; then
    PUBLIC_URL="http://$PUB_IP:$SERVER_PORT"
fi
echo -e " ${C_GREEN}✓ 诊断服务: $SERVER_PORT | 日志分析: $ANALYZER_PORT${C_NC}"
echo ""

# ── 3. AI 配置 ───────────────────────────────────
echo -e "${C_BLUE}[3/6] AI 配置（两个服务共用同一 AI 通道）${C_NC}"
echo ""
read -p " AI API 地址 (默认 https://api.deepseek.com/v1): " AI_URL
AI_URL=${AI_URL:-https://api.deepseek.com/v1}
read -p " AI API Key: " AI_KEY
[ -z "$AI_KEY" ] && { echo -e "${C_RED}API Key 不能为空${C_NC}"; exit 1; }
read -p " 模型名 (默认 deepseek-chat): " AI_MODEL
AI_MODEL=${AI_MODEL:-deepseek-chat}
echo -e " ${C_GREEN}✓ AI 通道: $AI_URL ($AI_MODEL)${C_NC}"
echo ""

# ── 4. 管理员账号 ────────────────────────────────
echo -e "${C_BLUE}[4/6] 管理员账号${C_NC}"
echo ""
read -p " 管理员用户名 (默认 admin): " ADMIN_USER
ADMIN_USER=${ADMIN_USER:-admin}
read -p " 管理员密码: " ADMIN_PWD
[ -z "$ADMIN_PWD" ] && { echo -e "${C_RED}密码不能为空${C_NC}"; exit 1; }
RANDOM_SECRET=$(head -c 24 /dev/urandom | base64 | tr -d '/+=' | head -c 32)
echo -e " ${C_GREEN}✓ 管理员: $ADMIN_USER（桥接器密钥已随机生成）${C_NC}"
echo ""

# ── 5. 写入 .env ─────────────────────────────────
echo -e "${C_BLUE}[5/6] 生成配置文件${C_NC}"
echo ""

cat > "$SERVER_DIR/.env" << EOF
# CloudDiag Server 配置（由 install.sh 生成于 $(date '+%Y-%m-%d %H:%M:%S')）

# ── 监听 ──
SERVER_HOST=0.0.0.0
SERVER_PORT=$SERVER_PORT

# ── 对外地址 ──
PUBLIC_URL=$PUBLIC_URL

# ── 会话安全（HTTP 环境必须 false）──
COOKIE_SECURE=$COOKIE_SECURE

# ── AI 大脑 ──
AGENT_BRAIN=deepseek
OPENAI_BASE_URL=$AI_URL
OPENAI_API_KEY=$AI_KEY
OPENAI_MODEL=$AI_MODEL

# ── 桥接器上传校验密钥（随机生成，请妥善保存）──
BRIDGE_HTTP_SECRET=$RANDOM_SECRET

# ── 管理员 ──
ADMIN_USERNAME=$ADMIN_USER
ADMIN_PASSWORD=$ADMIN_PWD

# ── 日志分析服务对接 ──
LOG_ANALYZER_UPSTREAM=http://127.0.0.1:$ANALYZER_PORT
LOG_ANALYZER_DIR=$ANALYZER_DIR
EOF
echo -e " ${C_GREEN}✓ $SERVER_DIR/.env${C_NC}"

cat > "$ANALYZER_DIR/.env" << EOF
# CloudDiag Log Analyzer 配置（由 install.sh 生成于 $(date '+%Y-%m-%d %H:%M:%S')）

# ── 监听 ──
PORT=$ANALYZER_PORT
HOST=127.0.0.1

# ── AI 通道（与诊断服务共用）──
DEEPSEEK_BASE_URL=$AI_URL
DEEPSEEK_API_KEY=$AI_KEY
DEEPSEEK_MODEL=$AI_MODEL

# ── 可选：备用通道（主通道失败时自动切换）──
# DEEPSEEK_BASE_URL_2=
# DEEPSEEK_API_KEY_2=
# DEEPSEEK_MODEL_2=
EOF
echo -e " ${C_GREEN}✓ $ANALYZER_DIR/.env${C_NC}"
echo ""

# ── 6. 依赖 + 启动 ───────────────────────────────
echo -e "${C_BLUE}[6/6] 安装依赖并启动${C_NC}"
echo ""

echo " · 系统依赖检查..."
MISSING=""
for cmd in 7z lzop; do
    command -v $cmd >/dev/null 2>&1 || MISSING="$MISSING $cmd"
done
command -v unrar >/dev/null 2>&1 || echo -e "   ${C_YELLOW}⚠ 未检测到 unrar（.rar 将由 7z 处理，通常够用）${C_NC}"
if [ -n "$MISSING" ]; then
    echo -e "   ${C_YELLOW}⚠ 缺少:$MISSING${C_NC}"
    echo "   安装命令: sudo apt install -y p7zip-full lzop unrar"
    read -p "   是否现在安装? [y/N]: " INSTALL_SYS
    if [ "$INSTALL_SYS" = "y" ] || [ "$INSTALL_SYS" = "Y" ]; then
        sudo apt update && sudo apt install -y p7zip-full lzop unrar || sudo apt install -y p7zip-full lzop
    fi
fi

echo " · 创建 Python 虚拟环境（诊断服务）..."
if [ ! -d "$SERVER_DIR/venv" ]; then
    python3 -m venv "$SERVER_DIR/venv"
fi
"$SERVER_DIR/venv/bin/pip" install -q --upgrade pip
"$SERVER_DIR/venv/bin/pip" install -q -r "$SERVER_DIR/requirements.txt"
echo -e "   ${C_GREEN}✓ 依赖安装完成${C_NC}"

echo " · 创建 Python 虚拟环境（日志分析）..."
if [ ! -d "$ANALYZER_DIR/venv" ]; then
    python3 -m venv "$ANALYZER_DIR/venv"
fi
"$ANALYZER_DIR/venv/bin/pip" install -q --upgrade pip
"$ANALYZER_DIR/venv/bin/pip" install -q -r "$ANALYZER_DIR/requirements.txt"
echo -e "   ${C_GREEN}✓ 依赖安装完成${C_NC}"
echo ""

# 生成 systemd unit（需要 sudo）
echo " · 生成 systemd 服务（开机自启 + 崩溃自愈）..."
CURRENT_USER="$(id -un)"
sudo tee /etc/systemd/system/clouddiag-server.service > /dev/null << EOF
[Unit]
Description=CloudDiag Server (AI Remote Diagnostics)
After=network.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$SERVER_DIR
ExecStart=$SERVER_DIR/venv/bin/python server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/clouddiag-loganalyzer.service > /dev/null << EOF
[Unit]
Description=CloudDiag Log Analyzer (IDG)
After=network.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$ANALYZER_DIR
ExecStart=$ANALYZER_DIR/venv/bin/python main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/clouddiag-logconsumer.service > /dev/null << EOF
[Unit]
Description=CloudDiag Log Analyzer - Deep Analysis Consumer
After=network.target clouddiag-loganalyzer.service

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$ANALYZER_DIR
ExecStart=$ANALYZER_DIR/venv/bin/python deep_analyze_consumer.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable -q clouddiag-server clouddiag-loganalyzer clouddiag-logconsumer
sudo systemctl restart clouddiag-server clouddiag-loganalyzer clouddiag-logconsumer
sleep 6
echo -e " ${C_GREEN}✓ 服务已启动${C_NC}"
echo ""

# ── 完成 ─────────────────────────────────────────
echo "=================================================="
echo -e " ${C_GREEN}部署完成${C_NC}"
echo "=================================================="
echo ""
echo " 访问地址: $PUBLIC_URL"
echo " 管理员:   $ADMIN_USER / (你设置的密码)"
echo ""
echo " 服务管理:"
echo "   sudo systemctl status clouddiag-server"
echo "   sudo systemctl restart clouddiag-server clouddiag-loganalyzer clouddiag-logconsumer"
echo "   journalctl -u clouddiag-server -f"
echo ""
if [ "$FORM" = "https" ]; then
    echo -e " ${C_YELLOW}HTTPS 形态还需完成:${C_NC}"
    echo "   1) 配置反向代理（Caddy）：见 docs/01-部署指南.md 场景 B"
    echo "   2) 开放 80/443 端口"
    echo ""
fi
echo " 下一步: bash deploy/doctor.sh    # 部署自检"
echo ""
