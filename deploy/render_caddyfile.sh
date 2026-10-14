#!/usr/bin/env bash
# ============================================================
# 由「域名注册表」渲染 /etc/caddy/Caddyfile（clouddiag 项目通用）
#
#   注册表：/etc/caddy/clouddiag-domains.conf（放在仓库外——含环境信息，不入库）
#     格式：<角色> <域名> <证书目录>
#       primary = 主入口：同时开 443 + 8443 两条加密入口
#       extra   = 过渡期保留的旧入口：只开 443
#
#   用法：
#     sudo bash render_caddyfile.sh              # 渲染 + 校验 + reload
#     sudo bash render_caddyfile.sh --dry-run    # 只渲染到临时文件并打印，不动线上
# ============================================================
set -euo pipefail

REG=${REG:-/etc/caddy/clouddiag-domains.conf}
OUT=${OUT:-/etc/caddy/Caddyfile}
APP_PORT=${APP_PORT:-8000}          # 应用端口（云诊断主服务）
LOG_PORT=${LOG_PORT:-8082}          # 日志分析服务端口
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

[ -r "$REG" ] || { echo "❌ 读不到域名注册表：$REG"; exit 1; }

DOMAINS=(); CERTS=(); ROLES=()
while read -r role dom certdir; do
    case "${role:-}" in ''|\#*) continue ;; esac
    [ -n "${dom:-}" ] && [ -n "${certdir:-}" ] || { echo "❌ 注册表格式错误：$role $dom ${certdir:-}"; exit 1; }
    ROLES+=("$role"); DOMAINS+=("$dom"); CERTS+=("$certdir")
done < "$REG"

[ ${#DOMAINS[@]} -gt 0 ] || { echo "❌ 注册表为空"; exit 1; }
PRIMARY_COUNT=0
for r in "${ROLES[@]}"; do [ "$r" = "primary" ] && PRIMARY_COUNT=$((PRIMARY_COUNT+1)); done
[ "$PRIMARY_COUNT" -eq 1 ] || { echo "❌ 注册表必须且只能有一个 primary（当前 $PRIMARY_COUNT 个）"; exit 1; }

TMP=$(mktemp /tmp/Caddyfile.render.XXXXXX)
EXP_PRIMARY=""
{
    echo "# ⚠️ 本文件由 deploy/render_caddyfile.sh 自动生成，请勿手工编辑"
    echo "#   域名清单来源：$REG   生成时间：$(date '+%F %T %Z')"
    echo "#   证书：注册表第三字段填证书目录=手动证书文件；填 acme=Let's Encrypt 自动签发 + 自动续期（推荐）"
    for i in "${!DOMAINS[@]}"; do
        if [ "${CERTS[$i]}" = "acme" ]; then
            echo "#   ${DOMAINS[$i]} 证书：Let's Encrypt 自动签发 + 自动续期（ACME HTTP-01）"
        elif [ -f "${CERTS[$i]}/fullchain.crt" ]; then
            END=$(openssl x509 -in "${CERTS[$i]}/fullchain.crt" -noout -enddate 2>/dev/null | cut -d= -f2 || true)
            [ -n "${END:-}" ] && echo "#   ${DOMAINS[$i]} 证书到期：$END"
        fi
    done
    echo

    render_site() {   # $1=地址(可带端口)  $2=证书目录 或 "acme"  $3=角色
        if [ "$2" = "acme" ]; then
            TLS_LINES='tls {
        issuer acme {
            disable_tlsalpn_challenge
        }
    }'
        else
            TLS_LINES="tls $2/fullchain.crt $2/privkey.key"
        fi
        cat <<EOF
$1 {
    $TLS_LINES
    header Cache-Control "no-cache"
    handle_path /log-analyzer/* {
        reverse_proxy 127.0.0.1:$LOG_PORT
    }
    reverse_proxy 127.0.0.1:$APP_PORT
}
EOF
    }

    for i in "${!DOMAINS[@]}"; do
        if [ "${ROLES[$i]}" = "primary" ]; then
            echo "# ── 主入口：443 标准端口 + 8443 备用加密端口（同一张证书）"
            echo "#    8443 用途：部分网络对 443 做深度检测/RST，同证书同 SNI 换端口即可绕过"
            render_site "${DOMAINS[$i]}" "${CERTS[$i]}" primary
            echo
            render_site "https://${DOMAINS[$i]}:8443" "${CERTS[$i]}" primary
            echo
        else
            echo "# ── 过渡期保留入口（仅 443）：${DOMAINS[$i]}"
            render_site "${DOMAINS[$i]}" "${CERTS[$i]}" extra
            echo
        fi
    done
} > "$TMP"

if ! caddy validate --config "$TMP" --adapter caddyfile >/dev/null 2>&1; then
    echo "❌ Caddyfile 校验失败，未生效。错误详情：" >&2
    caddy validate --config "$TMP" --adapter caddyfile 2>&1 | tail -12 >&2
    echo "   渲染结果保留在：$TMP" >&2
    exit 1
fi
echo "✅ 渲染并通过校验：$TMP" >&2

if [ "$DRY" = "1" ]; then
    echo "———— 渲染结果（dry-run，未改动线上）————" >&2
    cat "$TMP"
    rm -f "$TMP"
    exit 0
fi

sudo cp "$TMP" "$OUT"
sudo chown root:root "$OUT"; sudo chmod 644 "$OUT"
rm -f "$TMP"
if [ "${NO_RELOAD:-0}" = "1" ]; then
    echo "✅ 已渲染（NO_RELOAD=1，跳过 reload）" >&2
elif sudo systemctl reload caddy; then
    echo "✅ 已 reload Caddy（$OUT）" >&2
else
    echo "❌ reload 失败：新配置语法已校验通过但 Caddy 拒绝加载（通常是证书文件权限/路径问题）" >&2
    sudo journalctl -u caddy --since '1 min ago' --no-pager | tail -15 >&2
    exit 1
fi
