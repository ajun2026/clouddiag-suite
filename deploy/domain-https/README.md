# 域名 + HTTPS 部署

**适用**：对外服务、需要 HTTPS 加密、有域名的环境。

**特点**：在纯 HTTP 部署的基础上，前面加一层 Caddy 反向代理（自动申请并续期证书）。

## 与前者的唯一差异

| 项 | 纯 HTTP | 域名 + HTTPS |
|---|---|---|
| `PUBLIC_URL` | `http://IP:8000` | `https://your-domain.com` |
| `COOKIE_SECURE` | `false` | `true` |
| 桥接器协议 | `ws://` | `wss://` |
| 反向代理 | 不需要 | Caddy（本目录 Caddyfile） |

## 前置条件

1. 域名已解析到服务器公网 IP（A 记录）
2. 服务器 80 / 443 端口对外开放（Let's Encrypt 验证需要 80）

## 快速配置

```bash
sudo cp Caddyfile /etc/caddy/Caddyfile
sudo nano /etc/caddy/Caddyfile      # 改 your-domain.com 为你的域名
sudo systemctl reload caddy
```

然后修改 `clouddiag-server/.env`：

```ini
PUBLIC_URL=https://your-domain.com
COOKIE_SECURE=true
```

重启服务：`sudo systemctl restart clouddiag-server`

## 完整步骤

见 [docs/01-部署指南.md · 场景 B](../../docs/01-部署指南.md#场景-b域名--https-部署)
