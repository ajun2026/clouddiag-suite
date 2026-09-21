# 纯 HTTP 部署（IP 直连）

**适用**：只有服务器 IP、没有域名；内网环境；快速验证。

**特点**：无需域名、无需证书、无需反向代理——FastAPI 直接监听端口。

## 关键配置

`.env`（clouddiag-server）：

```ini
SERVER_HOST=0.0.0.0
SERVER_PORT=8000
PUBLIC_URL=http://<你的公网IP>:8000
COOKIE_SECURE=false          # ★ HTTP 环境必须 false
```

## 端口开放

云服务器在控制台安全组放行 `8000`（如需外部访问日志分析页，再放行 `8082`）。

## 桥接器连接

客户机桥接器使用 `ws://` 协议（一键连接命令会自动生成正确协议）。

## 完整步骤

见 [docs/01-部署指南.md · 场景 A](../../docs/01-部署指南.md#场景-a纯-http-部署无域名)
