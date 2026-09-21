# 更新日志

本项目采用语义化版本。**v1.0.0 起为整合版**（合并原两个独立项目）。

---

## v1.0.0 — 2026-09-21（整合首发）

### 整合

将原两个独立项目合并为单一仓库 `clouddiag-suite`：

| 原项目 | 现目录 | 整合时版本 |
|---|---|---|
| `cloud-ai-remote-diag`（云端 AI 远程诊断） | `clouddiag-server/` | v0.15.2 |
| `file-analyzer-web`（IDG 日志分析） | `log-analyzer/` | v3.11 |
| （原内嵌 `bridge/`） | `clouddiag-bridge/` | 0.6.4 → 1.0.0 |

> 整合前版本历史见各自仓库（已归档）：
> [cloud-ai-remote-diag](https://github.com/ajun2026/cloud-ai-remote-diag)、
> [file-analyzer-web](https://github.com/ajun2026/file-analyzer-web)

### 新增

- **部署形态解耦（HTTP / HTTPS）**：TLS/域名/反向代理从项目代码中剥离，
  作为部署选项。项目只监听 HTTP 端口；是否套 TLS 由部署方决定。
  两种形态的完整步骤见 `docs/01-部署指南.md`。

- **部署脚本**
  - `deploy/install.sh`：交互式一键部署（选形态 → 问端口 → 填 AI key → 生成 .env → 装依赖 → 起服务 → systemd 托管）
  - `deploy/doctor.sh`：部署自检（系统依赖 / 配置校验 / 进程 / 端口 / 服务健康 / 服务互通 / 功能抽查）
  - `deploy/plain-http/` 与 `deploy/domain-https/`：两种形态的说明与 Caddyfile 示例

- **风险与事故记录体系**（`docs/风险与事故记录/`）：收录 8 类真实踩坑记录
  （部署类 A1-A3 / 开发类 B1-B3 / 安全类 C1 / 运维类 D1），含现象、根因、处置、预防。

- **文档体系**：部署指南 / 架构说明 / 环境变量说明 / 常见问题（FAQ 12 问）

- **桥接器改名**：`bridge` → `clouddiag-bridge`
  - **修复**：Linux 上与系统网络工具 `bridge-utils` 同名冲突，
    客户误执行 `bridge` 时会被本程序劫持终端（见 [事故记录 A1](docs/风险与事故记录/A1-Linux桥接器与系统命令同名.md)）
  - Windows 同步改名：`bridge.exe` → `clouddiag-bridge.exe`

- **桥接器交互模式改进**：无参数运行不再阻塞等待输入
  - 非交互环境（无 TTY）：打印用法后退出
  - 有 TTY 但未指定 `-interactive`：打印用法后退出
  - 显式 `-interactive` 才进入交互式输入房间码

- **配置化**
  - 桥接器默认服务器地址不再硬编码具体部署地址（`-server` 参数 > 环境变量 `CLOUDDIAG_SERVER` > 占位默认）
  - 日志分析端口可配（`PORT` / `HOST` 环境变量）
  - 启动脚本改为脚本自身目录推导（不再硬编码开发机路径）

### 清理

移除历史遗留与误导性文件：

- `CLAUDE.md`（内容严重过时：描述的是 v0.8.0 / Python 桥接器 / 49 工具，与实际严重不符）
- `bridge.py`（旧 Python v1 桥接器，已被 Go 实现取代）
- PyInstaller 旧产物、待集成压缩包、各类 `.bak` 文件
- 历史文档移至 `docs/archive/`（标注仅供参考，可能已过时）

### 安全

- 移除误提交的 `.env`（详见 [事故记录 C1](docs/风险与事故记录/C1-环境文件误提交公开仓库.md)）
- 新增 `.env.example` 模板（两服务各一份），真实 `.env` 不入库
- 排除清单硬编码拦截 `.env` / `.env.*`

### ⚠️ 部署方必读

1. **凭据轮换**：若曾使用过整合前的版本，请轮换 AI API Key、桥接器校验密钥、管理员密码
   （原因见 [事故记录 C1](docs/风险与事故记录/C1-环境文件误提交公开仓库.md)）
2. **桥接器改名**：客户机需重新下载新的桥接器（`clouddiag-bridge-*`）
3. **HTTP 环境务必设 `COOKIE_SECURE=false`**（最常见的部署失败原因）
