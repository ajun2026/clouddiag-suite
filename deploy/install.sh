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
echo "  1) 纯 HTTP（只有服务器 IP，没有域名）—— 最简单，无需证书/反代"
echo "  2) 域名 + HTTPS（有域名，自动申请证书）"
echo "  3) FRP 内网穿透（服务器在内网/无公网 IP，数据不出内网）"
echo ""
echo -e "  ${C_YELLOW}提示：三种形态的项目代码完全一致，只是部署方式与 .env 配置不同。${C_NC}"
echo -e "  ${C_YELLOW}      选 3 时本脚本只负责把服务跑起来，FRP 隧道需另按文档配置。${C_NC}"
echo ""
read -p " 请选择 [1/2/3] (默认 1): " FORM_CHOICE
FORM_CHOICE=${FORM_CHOICE:-1}

FALLBACK_URL=""   # 备用访问地址（仅 HTTPS 形态可选填）
AI_URL_2=""; AI_KEY_2=""; AI_MODEL_2=""   # 备用 AI 通道（可选）

if [ "$FORM_CHOICE" = "3" ]; then
    # ── 形态 C：FRP 内网穿透 ──
    FORM="frp"
    echo ""
    echo -e "  ${C_BLUE}FRP 形态说明：${C_NC}"
    echo "    · 本机（内网服务器）跑 clouddiag 服务，监听 HTTP 端口"
    echo "    · 另需一台【有公网 IP 的机器】跑 frps（服务端）"
    echo "    · 工程师通过穿透域名访问，流量经 frps 转发到内网"
    echo ""
    echo "    完整配置步骤（含 frps/frpc 配置模板、7 条实测踩坑）："
    echo "      deploy/frp-internal/README.md"
    echo ""
    read -p " 穿透后对外访问的地址（如 https://diag.example.com，可留空稍后填）: " FRP_URL
    if [ -n "$FRP_URL" ]; then
        PUBLIC_URL="$FRP_URL"
        case "$FRP_URL" in
            https://*) COOKIE_SECURE="true" ;;
            *)         COOKIE_SECURE="false" ;;
        esac
    else
        PUBLIC_URL="http://127.0.0.1:8000"
        COOKIE_SECURE="false"
        echo -e " ${C_YELLOW}⚠️  PUBLIC_URL 已留空，部署后请修改 .env 填入穿透地址（否则一键连接命令会指向本机）${C_NC}"
    fi
    echo -e " ${C_GREEN}✓ 形态: FRP 内网穿透${C_NC}"
elif [ "$FORM_CHOICE" = "2" ]; then
    FORM="https"
    read -p " 请输入你的域名 (例如 diag.example.com): " DOMAIN
    [ -z "$DOMAIN" ] && { echo -e "${C_RED}域名不能为空${C_NC}"; exit 1; }
    PUBLIC_URL="https://$DOMAIN"
    COOKIE_SECURE="true"
    echo -e " ${C_GREEN}✓ 形态: 域名 + HTTPS ($DOMAIN)${C_NC}"
    # 备用访问地址（可选）：443 被中间设备拦截时降级用；不需要可直接回车跳过
    echo ""
    echo -e "  ${C_BLUE}备用访问地址（可选，按回车跳过）：${C_NC}"
    echo "    如果你的网络环境存在「443 被防火墙/中间设备拦截」的情况，"
    echo "    可提供一个备用地址（如 https://$DOMAIN:8443）用于自动降级。"
    echo "    纯 HTTP / 内网 IP / FRP 单端口部署【无需】配置此项。"
    read -p "    备用地址 (默认留空=不降级): " FALLBACK_URL
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
echo -e "  ${C_BLUE}说明：本项目使用【任意 OpenAI 兼容接口】作为 AI 大脑。${C_NC}"
echo "    常见的 API 地址示例："
echo "      · DeepSeek 官方   https://api.deepseek.com/v1"
echo "      · OpenAI 官方     https://api.openai.com/v1"
echo "      · 阿里通义千问    https://dashscope.aliyuncs.com/compatible-mode/v1"
echo "      · 智谱 GLM        https://open.bigmodel.cn/api/paas/v4"
echo "      · 第三方中转站    https://你的中转地址/v1"
echo "      · 本地部署(Ollama) http://127.0.0.1:11434/v1"
echo ""
echo -e "  ${C_YELLOW}🔴 关键要求：所选模型【必须支持 Function Calling（工具调用）】，${C_NC}"
echo -e "  ${C_YELLOW}   否则诊断功能无法下发命令、无法工作。${C_NC}"
echo ""
read -p " AI API 地址 (默认 https://api.deepseek.com/v1): " AI_URL
AI_URL=${AI_URL:-https://api.deepseek.com/v1}
read -p " AI API Key: " AI_KEY
[ -z "$AI_KEY" ] && { echo -e "${C_RED}API Key 不能为空${C_NC}"; exit 1; }
echo ""
echo "  模型名（须支持 Function Calling）示例："
echo "      · DeepSeek: deepseek-chat / deepseek-reasoner"
echo "      · OpenAI:   gpt-4o / gpt-4o-mini"
echo "      · 通义:     qwen-plus / qwen-max"
echo "      · 智谱:     glm-4-plus"
read -p " 模型名 (默认 deepseek-chat): " AI_MODEL
AI_MODEL=${AI_MODEL:-deepseek-chat}
echo -e " ${C_GREEN}✓ AI 通道: $AI_URL ($AI_MODEL)${C_NC}"
echo ""
echo -e "  ${C_BLUE}备用 AI 通道（可选，按回车跳过）${C_NC}"
echo "    主通道调用失败（如额度不足、限流）时自动切换，提升可用性。"
read -p "    备用 API 地址: " AI_URL_2
if [ -n "$AI_URL_2" ]; then
    read -p "    备用 API Key: " AI_KEY_2
    read -p "    备用模型名: " AI_MODEL_2
    echo -e " ${C_GREEN}✓ 备用通道: $AI_URL_2 ($AI_MODEL_2)${C_NC}"
fi
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

# ── 2026-09-26 安全加固：避免覆盖已有配置 ──
# 若目标机已有 .env（例如重装、或误在已有环境运行），先备份再覆盖，防止配置丢失。
for _f in "$SERVER_DIR/.env" "$ANALYZER_DIR/.env"; do
    if [ -f "$_f" ]; then
        _bk="${_f}.bak.$(date '+%Y%m%d-%H%M%S')"
        cp "$_f" "$_bk"
        echo -e " ${C_YELLOW}⚠️  已存在 $(basename $_f)，原文件已备份为：$_bk${C_NC}"
    fi
done
echo ""

cat > "$SERVER_DIR/.env" << EOF
# CloudDiag Server 配置（由 install.sh 生成于 $(date '+%Y-%m-%d %H:%M:%S')）

# ── 监听 ──
SERVER_HOST=0.0.0.0
SERVER_PORT=$SERVER_PORT

# ── 对外地址 ──
PUBLIC_URL=$PUBLIC_URL

# ── 备用访问地址（可选）──
# 主地址不可达时自动降级（如生产环境 443 被中间设备拦截）
# 纯 HTTP / 内网 IP / FRP 单端口部署【无需配置】——留空即不做降级
PUBLIC_URL_FALLBACK=$FALLBACK_URL

# ── 会话安全（HTTP 环境必须 false）──
COOKIE_SECURE=$COOKIE_SECURE

# ── AI 大脑 ──
# 任何 OpenAI 兼容接口均可；模型必须支持 Function Calling（否则诊断无法下发命令）
AGENT_BRAIN=deepseek
OPENAI_BASE_URL=$AI_URL
OPENAI_API_KEY=$AI_KEY
OPENAI_MODEL=$AI_MODEL

# ── 可选：备用 AI 通道（主通道失败时自动切换）──
# OPENAI_BASE_URL_2=$AI_URL_2
# OPENAI_API_KEY_2=$AI_KEY_2
# OPENAI_MODEL_2=$AI_MODEL_2

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
# 任何 OpenAI 兼容接口均可；模型必须支持 Function Calling
DEEPSEEK_BASE_URL=$AI_URL
DEEPSEEK_API_KEY=$AI_KEY
DEEPSEEK_MODEL=$AI_MODEL

# ── 可选：备用通道（主通道失败时自动切换）──
DEEPSEEK_BASE_URL_2=$AI_URL_2
DEEPSEEK_API_KEY_2=$AI_KEY_2
DEEPSEEK_MODEL_2=$AI_MODEL_2
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
