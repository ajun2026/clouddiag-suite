#!/usr/bin/env bash
# Nexpert 探活 + 资源记录（纯 shell，无常驻进程，每分钟由 cron 调一次）
#
# 为什么这么做：
#   2026-10-20 上午整机内存吃紧假死（日志 237 次 "Under memory pressure"，
#   无 OOM kill），Caddy 转 8000 端口 42 秒 i/o timeout，Hermes 网关事件循环
#   也探活失败。事后无法定位是哪个进程涨内存 —— 没有历史数据。
#   本脚本每分钟记一行资源快照，并在服务真挂时自动重启（不用重启整机）。
#
# 开销：无常驻内存；每次运行约 5MB、0.1 秒；日志一天约 100KB。
#
# 退出码：始终 0（cron 里不产生邮件噪音）

set -u
LANG=C

LOG_DIR="${LOG_DIR:-$HOME/logs}"   # 可用环境变量覆盖，默认 ~/logs
LOG="$LOG_DIR/nexpert-watch.log"
STATE="$LOG_DIR/.nexpert-watch.fail"
LOCK="/tmp/nexpert-watch.lock"
PORT="${PORT:-8000}"
SERVICES="clouddiag-server clouddiag-loganalyzer clouddiag-logconsumer caddy"

mkdir -p "$LOG_DIR"

# 防重入（上一分钟还没跑完就跳过）
exec 9>"$LOCK"
flock -n 9 || exit 0

now=$(date '+%F %T')
rss_mb() {  # 服务内存（MB）
    local v
    v=$(systemctl show "$1" -p MemoryCurrent --value 2>/dev/null)
    if [ -z "$v" ] || [ "$v" = "[not set]" ] || [ "$v" = "18446744073709551615" ]; then
        echo "-"
    else
        echo $((v / 1048576))
    fi
}
state_of() { systemctl is-active "$1" 2>/dev/null | head -1; }

avail=$(awk '/^MemAvailable:/{printf "%d", $2/1024}' /proc/meminfo)
swapused=$(awk '/^SwapTotal:/{t=$2}/^SwapFree:/{f=$2}END{if(t>0)printf "%d",(t-f)/1024; else print 0}' /proc/meminfo)
load=$(awk '{print $1}' /proc/loadavg)
disk=$(df --output=pcent / 2>/dev/null | tail -1 | tr -dc '0-9')

# ① 应用健康（走本机回环，绕过 Caddy，能区分"应用挂了"与"网关挂了"）
app="fail"
curl -s -m 5 -o /dev/null "http://127.0.0.1:${PORT}/api/health" && app="ok"
# ② 对外 HTTPS（走 Caddy）
#    注意：不能用 https://127.0.0.1 + Host 头 —— TLS 握手按 SNI 匹配站点，
#    IP 访问会被 Caddy 拒绝（实测 000）。正确做法是 --resolve 把域名钉到本机，
#    SNI 正确、又不依赖 DNS。域名从 .env 的 PUBLIC_URL 取，不硬编码。
envf="/home/ubuntu/projects/clouddiag-suite/clouddiag-server/.env"
whost="${WATCH_HOST:-}"
if [ -z "$whost" ] && [ -r "$envf" ]; then
    whost=$(grep -m1 '^PUBLIC_URL=' "$envf" 2>/dev/null | sed -e 's|^PUBLIC_URL=||' -e 's|"||g' \
            -e 's|^https\?://||' -e 's|/.*$||' -e 's|:.*$||')
fi
edge="skip"
if [ -n "$whost" ]; then
    edge="fail"
    curl -sk -m 5 -o /dev/null --resolve "${whost}:443:127.0.0.1" "https://${whost}/api/health" && edge="ok"
fi

fails=$(cat "$STATE" 2>/dev/null || echo 0)
case "$fails" in ''|*[!0-9]*) fails=0 ;; esac

action="-"
if [ "$app" = "ok" ]; then
    fails=0
else
    fails=$((fails + 1))
    # 连续 2 分钟应用不可用 → 重启应用（不重启整机）
    if [ "$fails" -ge 2 ]; then
        action="RESTART-clouddiag-server"
        sudo -n systemctl restart clouddiag-server >/dev/null 2>&1
        sleep 3
        curl -s -m 5 -o /dev/null "http://127.0.0.1:${PORT}/api/health" && action="${action}+ok" || action="${action}+still-fail"
        fails=0
    fi
fi

# 应用正常但对外 HTTPS 不通 → 多半是 Caddy，重启 Caddy
if [ "$app" = "ok" ] && [ "$edge" = "fail" ]; then
    action="${action} RESTART-caddy"
    sudo -n systemctl restart caddy >/dev/null 2>&1
fi

echo "$fails" > "$STATE"

printf '%s avail=%sM swap=%sM disk=%s%% load=%s app=%s edge=%s srv=%s logan=%s consumer=%s caddy=%s state=%s/%s/%s/%s act=%s\n' \
    "$now" "$avail" "$swapused" "$disk" "$load" "$app" "$edge" \
    "$(rss_mb clouddiag-server)" "$(rss_mb clouddiag-loganalyzer)" "$(rss_mb clouddiag-logconsumer)" "$(rss_mb caddy)" \
    "$(state_of clouddiag-server)" "$(state_of clouddiag-loganalyzer)" "$(state_of clouddiag-logconsumer)" "$(state_of caddy)" \
    "$action" >> "$LOG"

# 日志瘦身：超过 4000 行只留最近 2000 行（约 7 天）
lines=$(wc -l < "$LOG" 2>/dev/null || echo 0)
if [ "$lines" -gt 4000 ]; then
    tail -n 2000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

# 内存吃紧时单独留痕，便于事后一眼看到压力起点
if [ "$avail" -lt 400 ] 2>/dev/null; then
    echo "$now [MEM-PRESSURE] avail=${avail}M swap=${swapused}M — $(ps aux --sort=-rss | head -4 | awk '{printf "%s:%dM ", substr($11,1,18), $6/1024}')" >> "$LOG"
fi

exit 0
