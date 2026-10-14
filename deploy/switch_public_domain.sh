#!/usr/bin/env bash
# ============================================================
# 一键切换对外域名（云诊断项目）
#
#   用法：
#     sudo bash switch_public_domain.sh <新域名> [证书来源目录] [--dry-run]
#
#   做四件事（全部可回退）：
#     ① 前置校验：DNS 是否已解析到本机 / 证书是否匹配新域名且未过期
#     ② 安装证书到 /etc/caddy/certs/<新域名>/
#     ③ 注册表改为：新域名=primary，旧域名降级为 extra（过渡期两者都在线，零中断）
#     ④ 改 .env（PUBLIC_URL / PUBLIC_URL_FALLBACK）→ 重启应用 → 全链路验证
#
#   不做的事：不改 DNS（域名解析由主人在 DNSPod 操作）
# ============================================================
set -euo pipefail

PROJ=${PROJ:-/home/ubuntu/projects/clouddiag-suite}
ENV_FILE=${ENV_FILE:-$PROJ/clouddiag-server/.env}
REG=${REG:-/etc/caddy/clouddiag-domains.conf}
CADDY_OUT=${CADDY_OUT:-/etc/caddy/Caddyfile}   # 渲染目标（沙盒彩排时可指向 /tmp）
CERT_ROOT=${CERT_ROOT:-/etc/caddy/certs}
NO_SERVICE=${NO_SERVICE:-0}                     # =1 时不重启应用（沙盒彩排用）

SKIP_DNS_CHECK=${SKIP_DNS_CHECK:-0}   # =1 仅沙盒彩排用（跳过 DNS 解析校验）
NEW_DOMAIN="${1:-}"
CERT_SRC="${2:-/home/ubuntu/certs-incoming/$NEW_DOMAIN}"
ACME=0
DRY=0
for a in "$@"; do
    [ "$a" = "--dry-run" ] && DRY=1
    [ "$a" = "--acme" ] && ACME=1
done

[ -n "$NEW_DOMAIN" ] || { echo "用法: sudo bash switch_public_domain.sh <新域名> [证书来源目录] [--dry-run]"; exit 1; }
echo "$NEW_DOMAIN" | grep -qE '^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$' \
    || { echo "❌ 域名格式不合法：$NEW_DOMAIN"; exit 1; }

# 期望解析到的 IP：从 .env 的 PUBLIC_URL_FALLBACK 里取（零硬编码；取不到则跳过该检查）
EXPECT_IP=$(grep -aoE 'http://[0-9]{1,3}(\.[0-9]{1,3}){3}' "$ENV_FILE" 2>/dev/null | head -1 | cut -d/ -f3 || true)

echo "  证书方式: $([ "$ACME" = "1" ] && echo 'ACME 自动签发（Let'\''s Encrypt, DNS 无关, 自动续期）' || echo '手动证书文件')"
echo "═══ ① 前置校验 ═══"
echo "  新域名 : $NEW_DOMAIN"
echo "  证书源 : $CERT_SRC"
echo "  期望 IP: ${EXPECT_IP:-（未从 .env 推断出，跳过 IP 比对）}"

if [ "$SKIP_DNS_CHECK" = "1" ]; then
    echo "  （沙盒彩排：跳过 DNS 解析校验）"
elif [ -n "$EXPECT_IP" ]; then
    OK=0
    for NS in 223.5.5.5 119.29.29.29 8.8.8.8; do
        R=$( { command -v dig >/dev/null && dig +short "@$NS" "$NEW_DOMAIN" A 2>/dev/null; } | grep -E '^[0-9.]+$' | head -1 || true)
        echo "  DNS($NS) → ${R:-无记录}"
        [ "$R" = "$EXPECT_IP" ] && OK=1
    done
    if [ "$OK" != "1" ]; then
        echo "❌ 公共 DNS 尚未解析到 $EXPECT_IP（可能是缓存未过期，也可能是 A 记录未加）"
        echo "   建议先查权威 NS 确认：dig @<域名NS> $NEW_DOMAIN A"
        exit 1
    fi
fi

if [ "$ACME" = "1" ]; then
    echo "  ✅ ACME 模式：跳过证书文件校验与安装（由 Caddy 自动签发）"
else
CRT=$(ls "$CERT_SRC"/*fullchain*.crt "$CERT_SRC"/*.crt 2>/dev/null | head -1 || true)
KEY=$(ls "$CERT_SRC"/*privkey*.key "$CERT_SRC"/*.key 2>/dev/null | head -1 || true)
[ -n "$CRT" ] && [ -n "$KEY" ] || { echo "❌ 证书目录里找不到 fullchain.crt / privkey.key：$CERT_SRC"; exit 1; }

openssl x509 -in "$CRT" -noout -text 2>/dev/null | grep -q "DNS:$NEW_DOMAIN" \
    || { echo "❌ 证书与 $NEW_DOMAIN 不匹配（SAN 里没有该域名）"; openssl x509 -in "$CRT" -noout -text | grep -A1 'Subject Alternative Name'; exit 1; }
openssl x509 -in "$CRT" -noout -checkend 86400 >/dev/null \
    || { echo "❌ 证书 24 小时内过期或已过期，请重新申请"; exit 1; }
M1=$(openssl x509 -in "$CRT" -noout -modulus | md5sum | cut -d' ' -f1)
M2=$(openssl rsa -in "$KEY" -noout -modulus 2>/dev/null | md5sum | cut -d' ' -f1)
[ "$M1" = "$M2" ] || { echo "❌ 证书与私钥不配对"; exit 1; }
CHAIN=$(grep -c 'BEGIN CERTIFICATE' "$CRT")
echo "  ✅ 证书匹配（链 ${CHAIN} 张；到期 $(openssl x509 -in "$CRT" -noout -enddate | cut -d= -f2)）"
[ "$CHAIN" -ge 2 ] || echo "  ⚠️ 证书链只有 1 张，客户端可能报链不完整（建议用 fullchain）"

fi

TS=$(date '+%Y%m%d-%H%M%S')
BK="$PROJ/backups/pre-domain-switch-$TS"
if [ "$DRY" = "1" ]; then echo "（dry-run：校验全部通过，未做任何改动）"; exit 0; fi

echo "═══ ② 备份 ═══"
mkdir -p "$BK"
cp "$ENV_FILE" "$BK/clouddiag-server.env"
sudo cp /etc/caddy/Caddyfile "$BK/Caddyfile"
sudo cp "$REG" "$BK/clouddiag-domains.conf"
(cd "$BK" && md5sum clouddiag-server.env Caddyfile clouddiag-domains.conf > MD5SUMS)
cat > "$BK/restore.sh" <<EOF
#!/usr/bin/env bash
set -e
cp "$BK/clouddiag-server.env" "$PROJ/clouddiag-server/.env"
sudo cp "$BK/clouddiag-domains.conf" "$REG"
sudo cp "$BK/Caddyfile" /etc/caddy/Caddyfile
sudo systemctl reload caddy
if [ "$NO_SERVICE" = "1" ]; then
    echo "  （沙盒彩排：跳过应用重启）"
else
    sudo systemctl restart clouddiag-server
    sleep 6
fi
curl -s -o /dev/null -w '回退后 health → %{http_code}\n' --max-time 8 http://127.0.0.1:8000/api/health
EOF
chmod +x "$BK/restore.sh"
echo "  ✅ $BK"

echo "═══ ③ 安装证书 ═══"
if [ "$ACME" = "1" ]; then
    echo "  （ACME 模式：无需安装证书文件）"
else
sudo install -d -m 700 "$CERT_ROOT/$NEW_DOMAIN"
sudo install -m 644 "$CRT" "$CERT_ROOT/$NEW_DOMAIN/fullchain.crt"
sudo install -m 600 "$KEY" "$CERT_ROOT/$NEW_DOMAIN/privkey.key"
sudo chown -R caddy:caddy "$CERT_ROOT/$NEW_DOMAIN" 2>/dev/null || true
echo "  ✅ $CERT_ROOT/$NEW_DOMAIN（私钥 600）"
fi

echo "═══ ④ 更新域名注册表（旧域名降级为过渡入口，先换再删）═══"
NEW_REG=$(mktemp)
echo "# clouddiag 对外域名注册表（仓库外，含环境信息，不入库）" > "$NEW_REG"
echo "# 格式：<角色 primary|extra> <域名> <证书目录>" >> "$NEW_REG"
while read -r role dom certdir; do
    case "${role:-}" in ''|\#*) continue ;; esac
    [ "$dom" = "$NEW_DOMAIN" ] && continue
    echo "extra $dom $certdir" >> "$NEW_REG"        # 旧入口保留，仅 443
done < "$REG"
if [ "$ACME" = "1" ]; then
    echo "primary $NEW_DOMAIN acme" >> "$NEW_REG"
else
    echo "primary $NEW_DOMAIN $CERT_ROOT/$NEW_DOMAIN" >> "$NEW_REG"
fi
sudo cp "$NEW_REG" "$REG"; rm -f "$NEW_REG"
sudo env REG="$REG" OUT="$CADDY_OUT" bash "$PROJ/deploy/render_caddyfile.sh"

echo "═══ ⑤ 切换应用配置 ═══"
IP_FALLBACK=""
[ -n "$EXPECT_IP" ] && IP_FALLBACK="http://$EXPECT_IP:8000"
NEW_FALLBACK="https://$NEW_DOMAIN:8443"
[ -n "$IP_FALLBACK" ] && NEW_FALLBACK="$NEW_FALLBACK,$IP_FALLBACK"
python3 - "$ENV_FILE" "$NEW_DOMAIN" "$NEW_FALLBACK" <<'PY'
import sys, re
path, dom, fb = sys.argv[1], sys.argv[2], sys.argv[3]
s = open(path, encoding='utf-8').read()
s = re.sub(r'(?m)^PUBLIC_URL=.*$', f'PUBLIC_URL=https://{dom}', s)
s = re.sub(r'(?m)^PUBLIC_URL_FALLBACK=.*$', f'PUBLIC_URL_FALLBACK={fb}', s)
if not re.search(r'(?m)^COOKIE_SECURE=', s):
    s += '\nCOOKIE_SECURE=true\n'
else:
    s = re.sub(r'(?m)^COOKIE_SECURE=.*$', 'COOKIE_SECURE=true', s)
open(path, 'w', encoding='utf-8').write(s)
ip = re.search(r'http://([0-9.]+):', fb)
if ip:
    m = re.search(r'(?m)^ALLOWED_HOSTS=(.*)$', s)
    hosts = [h.strip() for h in (m.group(1).split(',') if m else []) if h.strip()]
    if ip.group(1) not in hosts:
        hosts.append(ip.group(1))
    if m:
        s = re.sub(r'(?m)^ALLOWED_HOSTS=.*$', 'ALLOWED_HOSTS=' + ','.join(hosts), s)
    else:
        s += '\nALLOWED_HOSTS=' + ','.join(hosts) + '\n'
    open(path, 'w', encoding='utf-8').write(s)
print('   .env 已更新：PUBLIC_URL / PUBLIC_URL_FALLBACK / COOKIE_SECURE / ALLOWED_HOSTS(含明文 IP)')
PY
grep -aE '^(PUBLIC_URL|PUBLIC_URL_FALLBACK|ALLOWED_HOSTS|COOKIE_SECURE)=' "$ENV_FILE" | sed 's/^/   /'
if [ "$NO_SERVICE" = "1" ]; then
    echo "  （沙盒彩排：跳过应用重启）"
else
    sudo systemctl restart clouddiag-server
    sleep 6
fi

echo "═══ ⑥ 全链路验证 ═══"
fail=0
chk() { # $1=说明 $2=url $3=期望码 $4=resolve(host:port:ip)
    local code
    if [ -n "${4:-}" ]; then
        code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 --resolve "$4" "$2" || echo 000)
    else
        code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$2" || echo 000)
    fi
    if [ "$code" = "$3" ]; then echo "  ✅ $1 → $code"; else echo "  ❌ $1 → $code（期望 $3）"; fail=1; fi
}
chk "新域名 443"      "https://$NEW_DOMAIN/api/health"        "200" "$NEW_DOMAIN:443:127.0.0.1"
chk "新域名 8443"     "https://$NEW_DOMAIN:8443/api/health"   "200" "$NEW_DOMAIN:8443:127.0.0.1"
[ -n "$IP_FALLBACK" ] && chk "明文 IP 兜底" "$IP_FALLBACK/api/health" "200" ""
RENDERED=$(curl -s --max-time 10 --resolve "$NEW_DOMAIN:443:127.0.0.1" "https://$NEW_DOMAIN/static/install-linux.sh" || true)
if printf '%s' "$RENDERED" | grep -q "$NEW_DOMAIN"; then echo "  ✅ 下发脚本已指向新域名"; else echo "  ❌ 下发脚本未指向新域名"; fail=1; fi
echo "  —— 证书实况 ——"
echo | openssl s_client -connect 127.0.0.1:443 -servername "$NEW_DOMAIN" 2>/dev/null \
  | openssl x509 -noout -subject -enddate 2>/dev/null | sed 's/^/   /' || echo "   （证书读取失败）"
BRIDGE=""; [ "$NO_SERVICE" = "1" ] || BRIDGE=$(ls "$PROJ"/clouddiag-bridge/clouddiag-bridge-linux-amd64 2>/dev/null | head -1 || true)
if [ -n "$BRIDGE" ]; then
    OUT=$(cd "$PROJ/clouddiag-bridge" && timeout 15 "$BRIDGE" -server "wss://$NEW_DOMAIN:8443" -room SWITCHTEST -token dummy 2>&1 || true)
    if printf '%s' "$OUT" | grep -q "已连接房间\|连接令牌无效"; then echo "  ✅ 真桥接器 wss://$NEW_DOMAIN:8443 已握手"; else echo "  ❌ 桥接器握手失败：$(printf '%s' "$OUT" | tail -2)"; fail=1; fi
fi
echo "  —— 过渡期：旧入口是否仍在服务 ——"
OLDP=$(awk '$1=="extra"{print $2}' "$REG" | head -1 || true)
[ -n "${OLDP:-}" ] && chk "旧入口 $OLDP（仅 443）" "https://$OLDP/api/health" "200" "$OLDP:443:127.0.0.1"

echo
echo "═══ 结果 ═══"
if [ "$fail" = "0" ]; then echo "🎉 切换完成，全部验证通过。"; else echo "⚠️ 有验证项未通过，请先不要删旧域名；回退：bash $BK/restore.sh"; fi
echo "回退命令 : bash $BK/restore.sh"
echo "摘掉旧域名（确认稳定后）: sudo bash $PROJ/deploy/remove_public_domain.sh <旧域名>"
echo "你还需做 : ① DNSPod 里删除旧域名 A 记录  ②（可选）腾讯云控制台吊销旧证书"
