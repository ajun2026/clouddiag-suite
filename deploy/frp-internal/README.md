# 场景 C：内网部署 + FRP 内网穿透

**适用**：服务部署在**内网/无公网 IP** 的服务器上，但需要外部工程师访问。

**典型场景**：
- 客户数据敏感，要求**数据不出内网**，只暴露 Web 端口
- 公司内网机房有服务器，但没有公网 IP
- 临时演示/测试环境，不想开公网机器

**与场景 A/B 的差别**：服务本身还是 HTTP（同场景 A），**在它前面加一层 FRP 隧道** 把端口映射到公网。

```
工程师浏览器
     ↓ https://diag.example.com（公网域名）
  ┌──────────────────────────────┐
  │ 云服务器（公网 IP，跑 frps）  │  ← 只做流量转发，不存数据
  └──────────────────────────────┘
     ↓ FRP 隧道（frpc 主动连出，无需内网开端口）
  ┌──────────────────────────────┐
  │ 内网服务器（跑 clouddiag）    │  ← 数据都在这里
  │  · clouddiag-server :8000    │
  │  · log-analyzer :8082        │
  └──────────────────────────────┘
     ↑ 桥接器（ws/wss）连接
  客户机（内网 Windows）
```

---

## 前置条件

| 项 | 要求 |
|---|---|
| 公网服务器 | 一台有公网 IP 的机器（跑 frps）——**仅作转发用**，配置可很低 |
| 内网服务器 | 跑 clouddiag-suite（已完成场景 A 部署） |
| 域名（可选） | 有域名可套 HTTPS；无域名则用 `公网IP:端口` 访问 |
| 网络 | 内网服务器能**主动出网**（能连公网 frps 的端口） |

> 🔑 FRP 原理：**内网侧主动连接公网侧**（不需要内网开端口/不需要公网 IP）。
> 这点很重要——内网服务器只要能访问外网即可，无需任何入站权限。

---

## 一、公网侧：部署 frps（服务端）

### 1. 下载 frp

```bash
# 公网服务器上执行
cd /opt
FRP_VER=0.58.0   # 按需替换为最新版本
wget https://github.com/fatedier/frp/releases/download/v${FRP_VER}/frp_${FRP_VER}_linux_amd64.tar.gz
tar -xzf frp_${FRP_VER}_linux_amd64.tar.gz
mv frp_${FRP_VER}_linux_amd64 frp
cd frp
```

### 2. 配置 frps.toml

```bash
sudo mkdir -p /etc/frp
sudo tee /etc/frp/frps.toml > /dev/null << 'EOF'
# frps 监听端口（frpc 连这个）
bindPort = 7000

# ⚠️ 必填：认证令牌（防止被他人白嫖/滥用）
auth.method = "token"
auth.token = "请替换为随机长字符串"

# 管理面板（可选，建议绑定内网或加认证）
webServer.addr = "127.0.0.1"
webServer.port = 7500
webServer.user = "admin"
webServer.password = "请替换为强密码"

# 允许的端口范围（穿透时用）
allowPorts = [
  { start = 8000, end = 8010 },
  { start = 8080, end = 8090 },
  { start = 8443, end = 8450 }
]

# 日志
log.to = "/var/log/frps.log"
log.level = "info"
log.maxDays = 7
EOF
```

### 3. 配置 systemd 自启

```bash
sudo tee /etc/systemd/system/frps.service > /dev/null << 'EOF'
[Unit]
Description=FRP Server
After=network.target

[Service]
Type=simple
User=root
ExecStart=/opt/frp/frps -c /etc/frp/frps.toml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now frps
sudo systemctl status frps --no-pager
```

### 4. 放行端口（安全组 + 防火墙）

```bash
# 云服务器控制台安全组放行：
#   7000  —— frpc 连接端口（⚠️ 建议限制来源 IP 为内网服务器出口 IP）
#   8000  —— 诊断服务（对外访问）
#   8443  —— 备用 HTTPS 端口（可选）
#   7500  —— 管理面板（⚠️ 不要对外，或加认证）

# 本机防火墙（如启用 ufw）
sudo ufw allow 7000/tcp
sudo ufw allow 8000/tcp
# sudo ufw allow 7500/tcp   # 管理面板：确认必要再开
```

> 🔴 **安全提醒**：`7000`（frpc 连接端口）建议在安全组里**限制来源 IP**（只允许内网服务器的出口 IP），
> 否则任何人都能尝试连接。`auth.token` 必须设置且足够随机。

---

## 二、内网侧：部署 frpc（客户端）

### 1. 下载 frp（同上，内网服务器上执行）

```bash
cd /opt
FRP_VER=0.58.0
wget https://github.com/fatedier/frp/releases/download/v${FRP_VER}/frp_${FRP_VER}_linux_amd64.tar.gz
tar -xzf frp_${FRP_VER}_linux_amd64.tar.gz
mv frp_${FRP_VER}_linux_amd64 frp
```

### 2. 配置 frpc.toml

```bash
sudo mkdir -p /etc/frp
sudo tee /etc/frp/frpc.toml > /dev/null << 'EOF'
# 公网 frps 地址与端口
serverAddr = "公网服务器IP"
serverPort = 7000

# 与 frps 一致的认证令牌
auth.method = "token"
auth.token = "与 frps.toml 中完全一致"

# 日志
log.to = "/var/log/frpc.log"
log.level = "info"
log.maxDays = 7

# ══════ 穿透规则 ══════

# ① 诊断服务（必须有）
[[proxies]]
name = "clouddiag-server"
type = "tcp"
localIP = "127.0.0.1"
localPort = 8000
remotePort = 8000          # 公网侧暴露的端口

# ② 日志分析服务（可选——如需外部直接访问）
# ⚠️ 建议不穿透：日志分析页通过诊断服务反代访问即可（/log-analyzer/ 路径）
#[[proxies]]
#name = "clouddiag-loganalyzer"
#type = "tcp"
#localIP = "127.0.0.1"
#localPort = 8082
#remotePort = 8082
EOF
```

### 3. 配置 systemd 自启

```bash
sudo tee /etc/systemd/system/frpc.service > /dev/null << 'EOF'
[Unit]
Description=FRP Client
After=network.target

[Service]
Type=simple
User=root
ExecStart=/opt/frp/frpc -c /etc/frp/frpc.toml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now frpc
sudo systemctl status frpc --no-pager
```

### 4. 验证隧道

```bash
# 内网服务器上：确认 frpc 已连上
sudo journalctl -u frpc -n 20 --no-pager | grep -i "start proxy success"

# 公网服务器（或任意外网机器）上：测试穿透
curl -I http://公网IP:8000/login
# 应返回 200
```

---

## 三、修改 clouddiag 配置（关键）

内网服务器上的 `clouddiag-server/.env`：

```ini
# ★ 改为【对外访问地址】（穿透后的公网入口），不是内网 IP
PUBLIC_URL=http://公网IP:8000

# 判断依据：
#   对外是 HTTP  → COOKIE_SECURE=false
#   对外有 HTTPS → COOKIE_SECURE=true
COOKIE_SECURE=false

# 其余保持不变（监听 0.0.0.0，不要改成 127.0.0.1）
SERVER_HOST=0.0.0.0
SERVER_PORT=8000
```

重启服务：

```bash
sudo systemctl restart clouddiag-server
```

> 🔴 **最常见的错误**：`PUBLIC_URL` 填了内网地址（如 `192.168.x.x`）。
> 这会导致**一键连接命令里的服务器地址错误**，客户机桥接器连不上。
> 必须填**外部能访问到的地址**（穿透后的入口）。

> ⚠️ `SERVER_HOST` 保持 `0.0.0.0`——虽然 frpc 连的是 `127.0.0.1`，
> 但保持监听全地址可避免后续调整麻烦。

---

## 四、（可选）叠加 HTTPS

如果公网侧已有域名，可以在 frps 或前置 Nginx/Caddy 上套 TLS。

### 方式 1：前置 Nginx + Let's Encrypt（推荐）

```nginx
# 公网服务器 /etc/nginx/sites-available/clouddiag
server {
    listen 443 ssl http2;
    server_name diag.example.com;

    ssl_certificate     /etc/letsencrypt/live/diag.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/diag.example.com/privkey.pem;

    client_max_body_size 500M;   # 日志包上传

    location / {
        proxy_pass http://127.0.0.1:8000;    # 指向 frps 暴露的端口
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;      # WebSocket 支持
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 600s;                     # 长连接（诊断任务）
    }
}
```

配置后，内网侧的 `PUBLIC_URL` 改为 `https://diag.example.com`，`COOKIE_SECURE=true`。

### 方式 2：FRP 原生 HTTPS（frps 直接处理 TLS）

frpc.toml 中：

```toml
[[proxies]]
name = "clouddiag-https"
type = "https"
localPort = 8000
customDomains = ["diag.example.com"]
```

frps.toml 中：

```toml
vhostHTTPSPort = 443
```

并把域名解析到公网服务器 IP。（需自行准备证书或使用 frps 的证书配置）

---

## 五、常见问题（内网穿透踩坑清单）

### Q1：访问显示"连接被重置"（443 打不开，但换个端口能开）

**现象**：`https://域名` 打不开，浏览器报 `ERR_CONNECTION_RESET` / `PR_CONNECT_RESET_ERROR`。

**原因**：部分企业网络/运营商防火墙对 **443 端口的 TLS 握手做深度检测（SNI 检查）**，
检测到特定特征就重置连接。

**解决**：**换非标端口**——用 8443 或其它端口对外提供服务：

```toml
# frpc.toml
[[proxies]]
name = "clouddiag-8443"
type = "tcp"
localPort = 8000
remotePort = 8443
```

访问 `https://域名:8443`。项目的一键连接命令**已内置 443 → 8443 自动降级**，
桥接器连接不受影响。

---

### Q2：内网服务器连不上 frps

**排查顺序**：

```bash
# 1) 内网能否出网到 frps 端口
telnet 公网服务器IP 7000     # 或用 nc -zv
# 不通 → 内网防火墙/出网策略限制，需放行

# 2) frps 是否在跑
sudo systemctl status frps

# 3) token 是否一致
diff <(grep token /etc/frp/frps.toml) <(grep token /etc/frp/frpc.toml)

# 4) frpc 日志
sudo journalctl -u frpc -n 50 --no-pager
```

---

### Q3：桥接器连不上（客户机 → 服务器）

**检查 `PUBLIC_URL`**：

```bash
# 内网服务器上
grep PUBLIC_URL clouddiag-server/.env
```

必须是**外部可访问的地址**（穿透入口），不能是内网 IP。

**协议要匹配**：对外是 HTTP → 桥接器用 `ws://`；对外是 HTTPS → `wss://`。
一键连接命令会自动生成正确协议（前提是 `PUBLIC_URL` 配置正确）。

---

### Q4：公司 VPN 导致域名解析异常

**现象**：公司网络下域名解析到错误地址，或连接超时。

**原因**：企业 VPN 常劫持 DNS 或修改路由表。

**解决**：

```bash
# 临时验证：改 hosts 直连
# Windows: C:\Windows\System32\drivers\etc\hosts
# Linux:   /etc/hosts
公网服务器IP  diag.example.com

# 或直接用 IP:端口 访问（跳过 DNS）
http://公网服务器IP:8000
```

---

### Q5：连接超时但 ping 通（MTU 问题）

**现象**：能 ping 通，但 HTTP/WebSocket 连接卡住或超时。

**原因**：部分企业内网/隧道 MTU < 1500，大包被丢弃。

**解决**：

```bash
# Windows（管理员 PowerShell）：把 MTU 调小
netsh interface ipv4 set subinterface "以太网" mtu=1400 store=persistent

# Linux
sudo ip link set dev eth0 mtu 1400
```

或在使用方（工程师端）调整。

---

### Q6：frps 被扫描/滥用

**现象**：管理面板出现陌生客户端连接，或带宽异常。

**解决**：

| 措施 | 说明 |
|---|---|
| `auth.token` 用长随机串 | 最基本防护 |
| 安全组限制 7000 端口来源 IP | 只允许内网服务器出口 IP |
| 管理面板绑 `127.0.0.1` 或加认证 | 不对公网开放 |
| 定期看 frps 日志 | 发现异常连接 |
| 只穿透必要端口 | 不要穿透 22/3306 等管理端口 |

---

### Q7：日志包上传失败（大文件）

**原因**：FRP 或前置 Nginx 的请求体大小限制。

**解决**：

```nginx
# Nginx
client_max_body_size 500M;
```

```bash
# frps.toml 无需特殊配置（TCP 类型无大小限制），
# 但如用了 http/https 类型代理，注意 maxPorts / transport 配置
```

---

## 六、对比三种部署形态

| | A 纯 HTTP（IP） | B 域名 + HTTPS | **C 内网穿透** |
|---|---|---|---|
| 服务器位置 | 公网 | 公网 | **内网** |
| 需要公网 IP | ✅ | ✅ | ❌（只需能出网） |
| 需要域名 | ❌ | ✅ | 可选 |
| 数据存放 | 服务器 | 服务器 | **内网（不出网）** |
| 额外组件 | 无 | Caddy/Nginx | **frps + frpc** |
| `COOKIE_SECURE` | false | true | 视对外协议 |
| 适用 | 快速验证 | 正式对外 | **数据敏感/无公网 IP** |

---

## 七、检查清单

部署完成后逐项确认：

- [ ] frps 已启动且开机自启（`systemctl is-enabled frps`）
- [ ] frpc 已连接成功（`journalctl -u frpc | grep "start proxy success"`）
- [ ] `auth.token` 两侧一致且足够随机
- [ ] 安全组已放行：7000 / 8000（+/8443）
- [ ] 公网入口可访问（`curl -I http://公网IP:8000/login` 返回 200）
- [ ] `PUBLIC_URL` 填的是**外部可访问地址**（不是内网 IP）
- [ ] `COOKIE_SECURE` 与对外协议匹配
- [ ] 桥接器可连接（一键命令生成后实测）
- [ ] frps 管理端口未暴露公网（或已加认证）
- [ ] 已跑 `bash deploy/doctor.sh` 自检

---

## 相关文档

- [部署指南（总）](../../docs/01-部署指南.md)
- [场景 A：纯 HTTP../plain-http/README.md
- [场景 B：域名 + HTTPS../domain-https/README.md
- [常见问题](../../docs/04-常见问题.md)
- [风险与事故记录](../../docs/风险与事故记录/README.md)
