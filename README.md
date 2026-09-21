# CloudDiag Suite · 云端 AI 远程运维助手

给售后/运维工程师使用的「AI 远程诊断 + 日志分析」一体化平台。

```
浏览器  →  云端服务  →  客户机桥接器  →  执行诊断命令
日志包  →  上传分析  →  解析 + AI 分析  →  结构化报告
```

---

## 这是什么（30 秒版）

| 部件 | 作用 | 用户看到 |
|---|---|---|
| **clouddiag-server** | 云端诊断服务：房间管理、诊断台、AI 分析、工具下发 | 网页：登录 → 创建房间 → 诊断台 / 对话 |
| **clouddiag-bridge** | 客户机上的桥接器：接收命令并在本机执行 | 一行命令跑起来，弹窗/终端显示连接状态 |
| **log-analyzer** | 日志分析服务：接收日志包，解析并做 AI 分析 | 网页：上传日志包 → 自动分析 → 报告 |

三个部件的关系：**server 是入口**，通过 **bridge** 操作客户机；采集到的日志可一键上传到 **log-analyzer** 做深度分析。

---

## 快速开始

### 第一步：确定你的部署形态

| 场景 | 你需要 | 部署方式 | 文档 |
|---|---|---|---|
| **只有服务器 IP，没有域名** | 一台 Linux 服务器 | 纯 HTTP（最简单） | [部署指南 → 场景 A](docs/01-部署指南.md#场景-a纯-http-部署无域名) |
| **有域名，要 HTTPS** | 域名 + 服务器 | 域名 + 自动 TLS | [部署指南 → 场景 B](docs/01-部署指南.md#场景-b域名--https-部署) |
| **服务器在内网/无公网 IP** | 内网服务器 + 一台公网机器 | FRP 内网穿透（数据不出内网） | [FRP 内网穿透](deploy/frp-internal/README.md) |

> ⚠️ **HTTPS 相关配置（Caddy、证书、443 端口）属于「部署形态」，不是项目代码的必需依赖**。
> 项目本身只监听 HTTP 端口；要不要套 TLS 由你决定。两种形态的环境变量差异见下。

### 第二步：一键部署（交互式脚本）

```bash
git clone https://github.com/ajun2026/clouddiag-suite.git
cd clouddiag-suite/deploy
bash install.sh          # 交互式引导：选形态 → 问端口 → 填 AI key → 起服务
bash doctor.sh           # 部署后自检：依赖/端口/服务互通/登录/桥接器下载
```

### 第三步：验证

```bash
bash deploy/doctor.sh    # 全绿即部署成功
```

---

## 两种部署形态的差异（重要）

项目代码**不依赖任何特定域名或证书**，差异只在环境变量与是否套反向代理：

| 配置项 | 纯 HTTP（IP 部署） | HTTPS（域名部署） |
|---|---|---|
| `PUBLIC_URL` | `http://1.2.3.4:8000` | `https://your-domain.com` |
| `COOKIE_SECURE` | **`false`** ← 必须 | `true` |
| 桥接器协议 | `ws://` | `wss://` |
| 反向代理 | 不需要（FastAPI 直连） | Caddy / Nginx（自动申请证书） |
| 额外要求 | 无 | 域名解析 + 80/443 端口开放 |

> 🔴 **最常见的部署失败原因**：HTTP 环境下忘记设 `COOKIE_SECURE=false`，导致登录后立刻掉线。

---

## 目录结构

```
clouddiag-suite/
├── clouddiag-server/          # 云端诊断服务（FastAPI）
│   ├── server.py              # 主服务
│   ├── static/                # 前端页面 + 桥接器下载文件
│   ├── quick_diagnoses.json   # 诊断项定义（30 项）
│   ├── .env.example           # 环境变量模板
│   └── requirements.txt
│
├── clouddiag-bridge/          # 桥接器（Go，跨平台）
│   ├── *.go                   # 源码
│   ├── build.sh               # 交叉编译脚本
│   └── clouddiag-bridge-*     # 已编译产物（win/linux×3）
│
├── log-analyzer/              # 日志分析服务（FastAPI）
│   ├── main.py
│   ├── detectors.py           # 日志格式识别与解压
│   ├── analyzers/             # Windows/Linux/BMC 分析模块
│   ├── .env.example
│   └── requirements.txt
│
├── deploy/                    # 部署脚本（按形态分目录）
│   ├── install.sh             # 交互式一键部署
│   ├── doctor.sh              # 部署自检
│   ├── plain-http/            # 纯 HTTP 形态（IP 部署）
│   └── domain-https/          # 域名 + TLS 形态
│
└── docs/
    ├── 01-部署指南.md          # ★ 部署主文档
    ├── 02-架构说明.md
    ├── 03-环境变量说明.md
    ├── 04-常见问题.md
    ├── archive/               # 历史文档（仅供参考，可能已过时）
    └── 风险与事故记录/         # ★ 踩坑与事故（部署前建议先看）
        ├── README.md          # 索引
        └── ...
```

---

## 环境要求

### 系统依赖（两个服务都需要）

| 组件 | 用途 | 缺失后果 |
|---|---|---|
| Python 3.10+ | 运行服务 | — |
| **7-Zip** (`p7zip-full`) | `.7z` 解压；`.rar` 首选解压器 | 7z/rar 上传失败 |
| **unrar** | `.rar` 解压兜底 | rar 兜底不可用 |
| **lzop** | `.tzz` 解压（IBM XCC FFDC） | tzz 上传失败 |

```bash
# Ubuntu / Debian
sudo apt install -y python3 python3-pip python3-venv p7zip-full unrar lzop

# 若 apt 找不到 unrar（部分源未收录），用 unrar-free：
# sudo apt install -y unrar-free
```

### 反向代理（仅 HTTPS 形态需要）

```bash
# 推荐 Caddy（自动申请 Let's Encrypt 证书，配置最简）
sudo apt install -y caddy
```

---

## 常见问题（Top 5）

| 问题 | 原因 | 解决 |
|---|---|---|
| 登录后立刻掉线 | HTTP 环境 `COOKIE_SECURE` 仍为 true | 改为 `false`，重启服务 |
| 上传 .rar 报「服务器错误」 | 缺 7z / unrar | 装 `p7zip-full`（+ optional `unrar`），见[事故记录](docs/风险与事故记录/) |
| AI 分析报「空回复」 | 网关抖动 / 推理模型 content 为空 | 已内置 3 次重试 + reasoning 兜底；持续失败需查网关 |
| 桥接器连不上 | 地址协议不对 / 端口不通 | HTTP 部署用 `ws://`，HTTPS 用 `wss://`；检查端口 |
| Linux 上敲 `bridge` 弹出诊断程序 | 历史版本命名冲突（现已改名） | 升级到 `clouddiag-bridge`（见[事故记录 A1](docs/风险与事故记录/)） |

更多见 [docs/04-常见问题.md](docs/04-常见问题.md)。

---

## ⚠️ 风险与事故记录

**部署前建议先浏览**——这些都是真实踩过的坑：

| 编号 | 问题 | 类别 |
|---|---|---|
| A1 | Linux 桥接器与系统命令同名（`bridge` 撞车） | 部署 |
| A2 | 依赖缺失导致启动/功能失败（multipart / dotenv） | 部署 |
| A3 | 端口硬编码导致部署不一致 | 部署 |
| B1 | 桥接器语言误判（以为 Python，实为 Go） | 开发 |
| B2 | 提示词多处消费路径未同步 | 开发 |
| C1 | `.env` 误提交公开仓库（凭据泄露） | 安全 |
| D1 | 包内混入旧文件，覆盖现网修复 | 运维 |

完整索引：[docs/风险与事故记录/README.md](docs/风险与事故记录/README.md)

---

## 版本

| 版本 | 说明 |
|---|---|
| **v1.0.0** | 整合版首发（继承 `cloud-ai-remote-diag` v0.15.2 + `file-analyzer-web` v3.11） |

历史版本（整合前）见各自仓库：
- [cloud-ai-remote-diag](https://github.com/ajun2026/cloud-ai-remote-diag)（已归档）
- [file-analyzer-web](https://github.com/ajun2026/file-analyzer-web)（已归档）

---

## 许可

内部项目，详见 [LICENSE](LICENSE)。
