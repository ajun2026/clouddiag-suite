#!/bin/bash
# CloudDiag Suite 部署自检脚本
# 2026-09-21
#
# 用法：bash doctor.sh [--url <对外地址>]
# 检查：系统依赖 / 服务状态 / 端口监听 / 服务互通 / 登录 / 桥接器下载

C_GREEN='\033[0;32m'; C_YELLOW='\033[1;33m'; C_RED='\033[0;31m'; C_BLUE='\033[0;34m'; C_NC='\033[0m'

SUITE_DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
SERVER_DIR="$SUITE_DIR/clouddiag-server"
ANALYZER_DIR="$SUITE_DIR/log-analyzer"

PASS=0; FAIL=0; WARN=0
ok()   { echo -e " ${C_GREEN}✓${C_NC} $1"; PASS=$((PASS+1)); }
bad()  { echo -e " ${C_RED}✗${C_NC} $1"; FAIL=$((FAIL+1)); }
warn() { echo -e " ${C_YELLOW}!${C_NC} $1"; WARN=$((WARN+1)); }
sec()  { echo ""; echo -e "${C_BLUE}$1${C_NC}"; }

# 参考地址（用于端到端检查）
BASE_URL="${CLOUDDIAG_URL:-http://127.0.0.1:8000}"

# 从 .env 读取配置
read_env() {
    local f="$1" k="$2"
    [ -f "$f" ] && grep -E "^$k=" "$f" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"' | tr -d "'"
}

SERVER_PORT=$(read_env "$SERVER_DIR/.env" SERVER_PORT); SERVER_PORT=${SERVER_PORT:-8000}
ANALYZER_PORT=$(read_env "$ANALYZER_DIR/.env" PORT); ANALYZER_PORT=${ANALYZER_PORT:-8082}
PUBLIC_URL=$(read_env "$SERVER_DIR/.env" PUBLIC_URL)
COOKIE_SECURE=$(read_env "$SERVER_DIR/.env" COOKIE_SECURE)
UPSTREAM=$(read_env "$SERVER_DIR/.env" LOG_ANALYZER_UPSTREAM); UPSTREAM=${UPSTREAM:-http://127.0.0.1:$ANALYZER_PORT}
ANALYZER_DIR_CFG=$(read_env "$SERVER_DIR/.env" LOG_ANALYZER_DIR)

echo "=================================================="
echo " CloudDiag Suite · 部署自检"
echo "=================================================="
echo " 项目目录: $SUITE_DIR"
echo " 检查地址: $BASE_URL"

# ── 1. 系统依赖 ──────────────────────────────────
sec "[1/6] 系统依赖"
for cmd in 7z lzop; do
    if command -v $cmd >/dev/null 2>&1; then ok "$cmd 已安装"; else bad "$cmd 缺失（上传 .7z/.tzz 会失败）→ apt install p7zip-full lzop"; fi
done
if command -v unrar >/dev/null 2>&1; then ok "unrar 已安装"
else warn "unrar 未安装（.rar 将由 7z 处理，通常够用）"; fi
command -v python3 >/dev/null 2>&1 && ok "python3: $(python3 --version 2>&1 | cut -d' ' -f2)" || bad "python3 缺失"

# ── 2. 配置文件 ──────────────────────────────────
sec "[2/6] 配置文件"
for f in "$SERVER_DIR/.env" "$ANALYZER_DIR/.env"; do
    if [ -f "$f" ]; then ok "$(basename $(dirname $f))/.env 存在"; else bad "$f 缺失（从 .env.example 复制并填写）"; fi
done

# 关键项检查
if [ -n "$PUBLIC_URL" ]; then ok "PUBLIC_URL = $PUBLIC_URL"; else bad "PUBLIC_URL 未配置（桥接器连接命令会生成错误地址）"; fi

if [ "$COOKIE_SECURE" = "false" ] && echo "$PUBLIC_URL" | grep -q "^http://"; then
    ok "COOKIE_SECURE=false 与 HTTP 部署匹配"
elif [ "$COOKIE_SECURE" = "true" ] && echo "$PUBLIC_URL" | grep -q "^https://"; then
    ok "COOKIE_SECURE=true 与 HTTPS 部署匹配"
elif [ -z "$COOKIE_SECURE" ]; then
    warn "COOKIE_SECURE 未设置（HTTP 环境请设 false，否则登录后掉线）"
else
    bad "COOKIE_SECURE=$COOKIE_SECURE 与 PUBLIC_URL 协议不匹配（HTTP→false，HTTPS→true）"
fi

AI_KEY=$(read_env "$SERVER_DIR/.env" OPENAI_API_KEY)
[ -n "$AI_KEY" ] && [ "$AI_KEY" != "sk-your-key-here" ] && ok "AI API Key 已配置" || bad "AI API Key 未配置（AI 功能不可用）"

# ── 3. 服务进程 ──────────────────────────────────
sec "[3/6] 服务进程"
for svc in clouddiag-server clouddiag-loganalyzer clouddiag-logconsumer; do
    if systemctl is-active --quiet $svc 2>/dev/null; then
        ok "$svc 运行中"
    else
        # 兼容非 systemd 部署
        if pgrep -f "$(echo $svc | sed 's/clouddiag-//')" >/dev/null 2>&1; then
            warn "$svc 未由 systemd 托管（进程存在）"
        else
            bad "$svc 未运行 → systemctl status $svc"
        fi
    fi
done

# ── 4. 端口监听 ──────────────────────────────────
sec "[4/6] 端口监听"
if ss -tlnp 2>/dev/null | grep -q ":$SERVER_PORT "; then ok "端口 $SERVER_PORT 监听中（诊断服务）"; else bad "端口 $SERVER_PORT 未监听"; fi
if ss -tlnp 2>/dev/null | grep -q ":$ANALYZER_PORT "; then ok "端口 $ANALYZER_PORT 监听中（日志分析）"; else bad "端口 $ANALYZER_PORT 未监听"; fi

# ── 5. 健康检查 ──────────────────────────────────
sec "[5/6] 服务健康"
H=$(curl -s --max-time 8 "http://127.0.0.1:$SERVER_PORT/api/health" 2>/dev/null)
if echo "$H" | grep -q '"status":"ok"'; then
    ok "诊断服务健康: $(echo $H | head -c 100)"
else
    bad "诊断服务健康检查失败 → journalctl -u clouddiag-server -n 30"
fi

A=$(curl -s -o /dev/null -w "%{http_code}" --max-time 8 "http://127.0.0.1:$ANALYZER_PORT/" 2>/dev/null)
if [ "$A" = "200" ]; then ok "日志分析服务响应 200"; else bad "日志分析服务响应 $A"; fi

# 服务互通（诊断服务 → 日志分析）
I=$(curl -s -o /dev/null -w "%{http_code}" --max-time 8 "$UPSTREAM/" 2>/dev/null)
if [ "$I" = "200" ] || [ "$I" = "307" ] || [ "$I" = "302" ]; then ok "服务互通正常（$UPSTREAM → $I）"
else bad "诊断服务无法访问日志分析（$UPSTREAM → $I）→ 检查 LOG_ANALYZER_UPSTREAM 与端口"; fi

# ── 6. 功能抽查 ──────────────────────────────────
sec "[6/6] 功能抽查"

# 登录页
L=$(curl -s -o /dev/null -w "%{http_code}" --max-time 8 "$BASE_URL/login" 2>/dev/null)
[ "$L" = "200" ] && ok "登录页可访问" || bad "登录页返回 $L"

# 桥接器文件
BIN="$SERVER_DIR/static/clouddiag-bridge-win64.exe"
if [ -f "$BIN" ]; then
    ok "桥接器文件存在（Windows: $(du -h "$BIN" | cut -f1)）"
else
    bad "桥接器文件缺失（$BIN）→ 客户机将无法下载"
fi
for b in clouddiag-bridge-linux-amd64 clouddiag-bridge-linux-arm64 clouddiag-bridge-linux-loong64; do
    [ -f "$SERVER_DIR/static/$b" ] && ok "桥接器存在: $b" || warn "桥接器缺失: $b（对应平台客户机无法下载）"
done

# 数据目录
if [ -n "$ANALYZER_DIR_CFG" ]; then
    [ -d "$ANALYZER_DIR_CFG" ] && ok "日志分析目录存在: $ANALYZER_DIR_CFG" || bad "日志分析目录不存在: $ANALYZER_DIR_CFG"
fi

# ── 汇总 ─────────────────────────────────────────
echo ""
echo "=================================================="
echo -e " 通过 ${C_GREEN}$PASS${C_NC} | 警告 ${C_YELLOW}$WARN${C_NC} | 失败 ${C_RED}$FAIL${C_NC}"
echo "=================================================="
if [ $FAIL -eq 0 ]; then
    echo -e " ${C_GREEN}自检通过${C_NC}"
    [ $WARN -gt 0 ] && echo " （有 $WARN 项警告，建议查看上方提示）"
    exit 0
else
    echo -e " ${C_RED}存在 $FAIL 项失败，请按提示修复${C_NC}"
    echo " 常见问题参考: docs/04-常见问题.md"
    exit 1
fi
