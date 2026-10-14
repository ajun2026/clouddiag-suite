#!/usr/bin/env bash
# ============================================================
# 摘掉一个对外域名入口（重渲染 Caddyfile；不改 DNS）
#
#   用法：
#     sudo bash remove_public_domain.sh <域名> [--dry-run]
#
#   保护措施：
#     · 不允许摘掉 primary（必须先 switch_public_domain.sh 换主域名）
#     · 摘之前自动备份注册表 + Caddyfile
#   摘完你还需做：DNSPod 里删除该域名的 A 记录（可选：腾讯云控制台吊销其证书）
# ============================================================
set -euo pipefail

PROJ=${PROJ:-/home/ubuntu/projects/clouddiag-suite}
REG=${REG:-/etc/caddy/clouddiag-domains.conf}
DOM="${1:-}"
DRY=0
for a in "$@"; do [ "$a" = "--dry-run" ] && DRY=1; done
[ -n "$DOM" ] || { echo "用法: sudo bash remove_public_domain.sh <域名> [--dry-run]"; exit 1; }

grep -qE "^primary[[:space:]]+$DOM([[:space:]]|$)" "$REG" \
    && { echo "❌ $DOM 当前是 primary（主入口），不能直接摘。请先用 switch_public_domain.sh 换主域名。"; exit 1; }
grep -qE "^(extra|primary)[[:space:]]+$DOM([[:space:]]|$)" "$REG" \
    || { echo "❌ 注册表里没有这个入口：$DOM"; sed 's/^/   /' "$REG"; exit 1; }

TS=$(date '+%Y%m%d-%H%M%S')
BK="$PROJ/backups/pre-domain-remove-$TS"
echo "备份 → $BK"
mkdir -p "$BK"
sudo cp "$REG" "$BK/clouddiag-domains.conf"
sudo cp /etc/caddy/Caddyfile "$BK/Caddyfile"
(cd "$BK" && sudo md5sum clouddiag-domains.conf Caddyfile > MD5SUMS)

NEW=$(mktemp)
while read -r role dom certdir; do
    case "${role:-}" in ''|\#*) continue ;; esac
    [ "$dom" = "$DOM" ] && continue
    echo "$role $dom $certdir" >> "$NEW"
done < "$REG"
echo "# clouddiag 对外域名注册表（仓库外，含环境信息，不入库）" | cat - "$NEW" > "$NEW.2"

if [ "$DRY" = "1" ]; then echo "（dry-run）将被移除：$DOM"; echo "———— 剩余注册表 ————"; cat "$NEW.2"; rm -f "$NEW" "$NEW.2"; exit 0; fi

sudo cp "$NEW.2" "$REG"; rm -f "$NEW" "$NEW.2"
sudo bash "$PROJ/deploy/render_caddyfile.sh"

cat <<EOF

✅ 已摘掉 $DOM 的 Caddy 站点。剩余入口：
$(awk '$1=="primary"||$1=="extra"{printf "   %-8s %s\n", $1, $2}' "$REG")
回退：sudo cp $BK/clouddiag-domains.conf $REG && sudo cp $BK/Caddyfile /etc/caddy/Caddyfile && sudo systemctl reload caddy

你还需做：
  ① DNSPod 删除 $DOM 的 A 记录
  ② （可选）腾讯云控制台吊销 $DOM 的证书
EOF
