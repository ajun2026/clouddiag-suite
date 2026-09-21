# DEPLOY.md — 新服务器部署指南

> 面向**其他团队 / 其他服务器**：从 GitHub 拉取本仓库，部署到你们自己的服务器上。
> 本仓库是一个可移植项目，但代码里有 17 处写死了演示服务器地址（`<公网入口IP>:8000`），
> **部署到自己的服务器必须全部替换**，否则页面能打开、房间能建，但桥接器/下载命令
> 都会连到演示服务器上，完全不可用。本指南逐条列出"必须改成你自己的"的每一项。

---

## 0. 你需要准备的东西【必须自己准备】

| 项目 | 说明 |
|---|---|
| 一台公网 Linux 服务器 | 建议 Ubuntu 20.04+，有公网 IP（或域名） |
| Python 3.10+ | 运行 server.py |
| AI API Key | DeepSeek 或任意 OpenAI 兼容 API（base URL + key + 模型名） |
| Go 工具链（≥1.21） | **仅编译桥接器时需要**，不编译可跳过 |
| 域名 + HTTPS 证书 | 可选，推荐（解锁 wss/更安全） |

---

## 1. 快速部署

```bash
git clone https://github.com/ajun2026/cloud-ai-remote-diag.git
cd cloud-ai-remote-diag

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# ⚠️ 编辑 .env —— 第 2 节每一项都要改成你自己的！

python server.py
# 启动后访问 http://你的IP:8000/dashboard
```

---

## 2. 配置 .env【必须全部改成你自己的】

| 配置项 | 必须改 | 说明 |
|---|---|---|
| `OPENAI_BASE_URL` | ✅ | 你的 AI API 地址，如 `https://api.deepseek.com/v1` |
| `OPENAI_API_KEY` | ✅ | 你的 API Key（sk- 开头） |
| `OPENAI_MODEL` | ✅ | 你的模型名，如 `deepseek-chat` |
| `SERVER_HOST` | 一般不用 | `0.0.0.0`（监听所有网卡） |
| `SERVER_PORT` | 一般不用 | `8000` |
| `AGENT_BRAIN` | 默认即可 | `deepseek`＝纯 DeepSeek 大脑，无需 Hermes 即可用 |
| `BRIDGE_HTTP_SECRET` | ✅ **必改** | HTTP 桥接口共享密钥，改成你自己的长随机串（生成：`openssl rand -hex 24`） |
| `ADMIN_PASSWORD` | ✅ **必改** | 管理后台密码，默认 `admin` 必须换掉 |

> Hermes 大脑（可选）：只有你自己部署了 Hermes gateway 才配置 `HERMES_BASE_URL` 等项，
> 否则**保持注释状态**，系统用 DeepSeek 大脑正常工作。

---

## 3. 替换硬编码服务器地址【必须做！不换 = 不可用】

> 💡 **可选增强**：如果希望以后部署迁移不用再 sed 改代码，可先按
> [`../docs/archive/部署地址动态化改造指南.md`](../docs/archive/部署地址动态化改造指南.md)
> 把地址改成运行时动态化（`.env` 的 `PUBLIC_URL` 配置 + 自动推导），改完本项目
> 本节即可跳过。不想改则继续按本节 sed 替换（两条路任选其一，都可用）。

代码里写死了演示服务器 `<公网入口IP>:8000`，共 **4 个文件 17 处**：

| 文件 | 处数 | 影响 |
|---|---|---|
| `static/index.html` | 7 | 连接弹窗默认服务器、下载命令 |
| `static/dashboard.html` | 4 | 下载页命令版 / Linux 一键安装命令 |
| `static/bridge.ps1` | 3 | 命令版桥接器默认连接地址（ws://） |
| `static/install-linux.sh` | 3 | Linux 一键安装脚本的下载地址 |

### 批量替换（推荐）

把下面命令里的 `your-server.com:8000` 换成**你们的公网 IP 或域名**（http 方式）：

```bash
cd cloud-ai-remote-diag

sed -i 's|<公网入口IP>:8000|your-server.com:8000|g' \
  static/index.html static/dashboard.html static/bridge.ps1 static/install-linux.sh

# 若用 HTTPS，另外把 ws:// 改成 wss://（bridge.ps1 内默认连接地址）
sed -i 's|ws://your-server.com|wss://your-server.com|g' static/bridge.ps1
```

### 替换后必须检查

```bash
# 代码文件里不应再出现演示服务器地址（文档类文件除外）
grep -rn "<公网入口IP>" static/   # 应无输出

# 人工核对关键点
grep -n "your-server.com" static/index.html        # 连接弹窗默认服务器
grep -n "ServerUrl\|ws://" static/bridge.ps1       # 命令版默认地址
grep -n "^SERVER=" static/install-linux.sh         # Linux 安装下载地址
```

---

## 4. 编译桥接器【必须做，否则下载页 404】

仓库**不包含编译好的二进制**（`.gitignore` 排除，避免仓库膨胀），部署后需自行编译放入 `static/`：

```bash
cd bridge

# Windows x86_64
GOOS=windows GOARCH=amd64 go build -ldflags "-s -w" -o clouddiag-bridge-win64.exe .

# Linux x86_64
GOOS=linux GOARCH=amd64 go build -ldflags "-s -w" -o clouddiag-bridge-linux-amd64 .

# Linux ARM64
GOOS=linux GOARCH=arm64 go build -ldflags "-s -w" -o clouddiag-bridge-linux-arm64 .

# Linux 龙芯
GOOS=linux GOARCH=loong64 go build -ldflags "-s -w" -o clouddiag-bridge-linux-loong64 .

# 全部放入 static/ 供网页下载
cp clouddiag-bridge-win64.exe bridge-linux-* ../static/
```

验证：

```bash
curl -sI http://你的IP:8000/static/clouddiag-bridge-win64.exe   # 期望 200
```

> ⚠️ `-ldflags "-s -w"` 必须带（去符号表，否则体积 4.8MB→7MB）。

---

## 5. 种子账号

首次启动自动创建：

- **admin**：管理后台账号（`/admin`），初始密码 `admin` —— **部署后立刻改**
- **test1 ~ test10**：测试工程师账号，密码 = 工号（如 test1 / test1）

改密码：登录后在「🔒 修改密码」页面，或管理后台重置。

---

## 6. 公网访问

- **云服务器安全组**：放行 `8000` 端口（或你的反代端口）
- **本机防火墙**（如有）：`sudo ufw allow 8000`
- 浏览器访问：`http://你的IP:8000/dashboard`

---

## 7. Nginx 反代（推荐：域名 + HTTPS）

WebSocket 必须带 `Upgrade` 头，否则桥接器连不上。

```nginx
server {
    listen 80;
    server_name your-domain.com;
    # 可选：HTTP 跳 HTTPS（certbot 自动配）

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;      # WebSocket 必需
        proxy_set_header Connection "upgrade";       # WebSocket 必需
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 3600s;                    # 长连接（诊断命令可能跑几分钟）
    }
}
```

HTTPS 部署（certbot 一键）：`sudo certbot --nginx -d your-domain.com`

> ⚠️ 用 HTTPS 后：
> - 页面地址变 `https://your-domain.com`
> - 客户端连接地址必须是 `wss://your-domain.com`（把 bridge.ps1 / 下载页命令里的 `ws://` 改 `wss://`）
> - 前端复制功能/WebSocket 在 HTTPS 下更稳定

---

## 8. 部署后自检清单

```bash
# 1. 服务健康
curl -s http://127.0.0.1:8000/api/health          # {"status":"ok",...}

# 2. 页面可访问
curl -sI http://你的IP:8000/dashboard              # 302 到 /login 属正常

# 3. 桥接器文件可下载
curl -sI http://你的IP:8000/static/clouddiag-bridge-win64.exe # 200
curl -sI http://你的IP:8000/static/bridge.ps1       # 200 + content-type: text/plain

# 4. 硬编码地址已替换干净
grep -rn "<公网入口IP>" static/                     # 无输出

# 5. 端到端：创建房间 → 客户机跑桥接器输入房间码 → 对话页显示在线 → 发"看看系统信息"能回
```

---

## 9. 常见问题

| 症状 | 原因 / 处理 |
|---|---|
| 下载桥接器 404 | 没编译二进制（见第 4 节） |
| 页面能开，但 bridge 连不上 | 硬编码地址没替换干净 / 反代缺 Upgrade 头 / 安全组没放行 |
| 命令版报 `Byte[]` 错误 | 服务器未返回 text/plain（检查是否用了旧版 server.py） |
| 对话无响应 | .env 的 API key / base URL / 模型名不对 |
| 管理后台进不去 | 用 admin/admin 登录（部署后立即改密码） |
| 桥接器被杀毒拦截 | 用命令版（bridge.ps1）替代 .exe |

---

## 10. 与演示服务器的差异说明

| 项 | 演示服务器（<公网入口IP>） | 你们部署的服务器 |
|---|---|---|
| 页面地址 | `http://<公网入口IP>:8000` | `http://你们的IP:8000`（或域名） |
| AI 大脑 | DeepSeek（默认）+ Hermes（可选） | DeepSeek 即可，Hermes 可选 |
| 数据 | 演示数据，可随意清空 | 你们自己的工单/房间数据（SQLite：`logs/chat.db`） |
| 桥接器 | 已编译好的二进制在 static/ | **需自行编译**（第 4 节） |
