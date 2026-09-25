#!/bin/bash
# ============================================================
# CloudDiag Bridge — 交叉编译脚本
#
# 用法: bash build.sh          # 编译全部平台
#       bash build.sh linux    # 只编译 Linux 平台
#
# 说明:
#   · 桥接器是 Go 实现（单一源码交叉编译多平台），无需 wine / PyInstaller
#   · 需要 Go 1.22+（未安装时见 README 的环境要求）
#   · 产物输出到本目录，并自动同步到 ../clouddiag-server/static/
# ============================================================
set -e

cd "$(dirname "$(readlink -f "$0")")"

# Go 工具链（未在 PATH 时尝试常见位置）
if ! command -v go >/dev/null 2>&1; then
    for p in /usr/local/go/bin /usr/lib/go/bin "$HOME/go/bin"; do
        [ -x "$p/go" ] && export PATH="$PATH:$p" && break
    done
fi
if ! command -v go >/dev/null 2>&1; then
    echo "错误: 未找到 go 命令。请先安装 Go 1.22+（https://go.dev/dl/）"
    exit 1
fi
echo "使用 $(go version)"

# 国内网络建议设置模块代理（如可直连可省略）
export GOPROXY="${GOPROXY:-https://goproxy.cn,direct}"

TARGET="${1:-all}"
LDFLAGS="-s -w"
STATIC_DIR="../clouddiag-server/static"

build() {
    local goos="$1" goarch="$2" out="$3"
    echo "  编译 $goos/$goarch → $out"
    CGO_ENABLED=0 GOOS="$goos" GOARCH="$goarch" \
        go build -trimpath -ldflags="$LDFLAGS" -o "$out" .
}

echo "----------------------------------------------"
if [ "$TARGET" = "all" ] || [ "$TARGET" = "windows" ]; then
    build windows amd64 clouddiag-bridge-win64.exe
fi
if [ "$TARGET" = "all" ] || [ "$TARGET" = "linux" ]; then
    build linux amd64   clouddiag-bridge-linux-amd64
    build linux arm64   clouddiag-bridge-linux-arm64
    build linux loong64 clouddiag-bridge-linux-loong64
fi
echo "----------------------------------------------"

# 同步到服务端静态目录（供客户机下载）
if [ -d "$STATIC_DIR" ]; then
    echo "同步到 $STATIC_DIR ..."
    for f in clouddiag-bridge-win64.exe clouddiag-bridge-linux-amd64 \
             clouddiag-bridge-linux-arm64 clouddiag-bridge-linux-loong64; do
        [ -f "$f" ] && cp -f "$f" "$STATIC_DIR/" && echo "  → $f"
    done
fi

echo ""
echo "编译完成。产物列表:"
ls -lh clouddiag-bridge-* 2>/dev/null | awk '{printf "  %-36s %s\n", $9, $5}'
echo ""
echo "提示: 服务端重启后客户机即可下载新版本（无需重启桥接器进程的旧版本仍可连接）"
