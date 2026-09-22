## v1.0.2 — 2026-09-22（现网修复回灌 + 卸载能力）

> 来源：现网部署端逐文件比对清单——整合包中部分文件仍为旧逻辑，
> 现网已修复的问题在此回灌。（换算：1 个新增文件 + 5 个文件小改，不涉架构）

### 修复

- **P0 · 日志分析 app_state 修复**（新增 `log-analyzer/app_state.py` +
  改 `chat/function_call.py` / `analyzers/windows.py` / `analyzers/linux.py`）

  *现象*：服务重启后新上传的日志包，AI 对话一律报「日志目录不存在，请重新上传」；
  整体总结匹配不到新任务的缓存报告。（重启前上传的老任务正常）

  *根因*：主程序以 `python main.py` 启动，模块名是 `__main__`；
  `analyzers/` 与 `chat/` 里用 `from main import jobs` 懒加载，会让 Python
  **把 main.py 再执行一遍**（模块名 `main`），第二遍执行到 `_fc.jobs = jobs`
  时，把 chat 用的 `jobs` 重新指向「第二个 main」自己的旧快照 —— 从此与真正
  在服务的那份脱钩，只有「重启之后新上传」的任务会报错。

  *修复*：子模块不再 `import main`，改为经 `app_state.py`（`sys.modules` 查询）
  向正在运行的主进程要状态。

- **P0 · Function Calling「空回复」误判**（`chat/function_call.py`）

  *现象*：多轮工具链第一步（模型只返回 `tool_calls`、`content` 为空）被判空回复，
  重试 3 次后报 500。

  *修复*：成功出口增加 `tool_calls` 判断；取值改防御式（缺字段不再 KeyError）。

- **BMC/other 对话 500**（`chat/context_inject.py`，本次实测发现）

  *现象*：BMC/other 类型日志包的 AI 对话必然 `NameError` 500。

  *根因*：该模块调用了 `_clean_name()` 与 `DEEPSEEK_MODEL`，但未定义/未导入。

  *修复*：本地定义 `_clean_name()`（与 main.py 一致）；补导入 `DEEPSEEK_MODEL`。

- **Linux 一键安装脚本**（`static/install-linux.sh.tmpl`）

  - 443 探测限定为 https 部署——HTTP/IP 部署不再拼出 `IP:8000:8443` 坏地址
  - 新增：安装后清理历史误装名 `/usr/local/bin/bridge`
    （早期版本会顶掉系统 bridge-utils 的网络桥接命令；只删确认是本程序的文件）

### 新增

- **桥接器卸载能力**（现场交付「能装也能干净卸载」）
  - `static/uninstall-linux.sh`（模板 + 路由）——停进程、删程序（含历史误装名）、
    删审计日志 `~/.clouddiag`、报告系统 bridge 命令状态；只动本程序自己的文件
  - `static/uninstall-windows.bat`——Windows 对应版本（自动提权）
  - `static/dashboard.html`——Linux 下载卡片新增「第 4 步：用完清理（可选）」

- **`clouddiag-bridge/build.sh`**——交叉编译脚本（Windows + Linux×3），
  自动同步产物到 `clouddiag-server/static/`（README 此前引用了该文件但缺失）

### 变更

- 日志分析分析提示词去掉公司名（统一口径称「售后」）

## v1.0.1 — 2026-09-21（新增第三种部署形态：内网穿透）

### 新增

- **场景 C：内网部署 + FRP 内网穿透**（`deploy/frp-internal/`）
  适用：服务部署在内网/无公网 IP 的服务器，但需外部工程师访问；
  或客户要求"数据不出内网"。
  - `README.md`：完整部署步骤（frps 公网侧 + frpc 内网侧）+ 7 条踩坑清单
  - `frps.toml.example` / `frpc.toml.example`：两侧配置模板（含 token 认证、端口范围、systemd）
  - 覆盖 HTTPS 叠加方案（前置 Nginx + Let's Encrypt / FRP 原生 https）
  - 三种部署形态对比表（纯 HTTP / 域名 HTTPS / 内网穿透）

  收录的真实踩坑经验：
  - 443 端口被企业防火墙 SNI 检测拦截 → 改用 8443 等非标端口（桥接器已内置降级）
  - `PUBLIC_URL` 误填内网地址 → 一键连接命令指向错误地址，桥接器连不上
  - 企业 VPN 劫持 DNS → 改 hosts 或直接用 IP 访问
  - 内网/隧道 MTU < 1500 → 连接超时（调小 MTU 至 1400）
  - frps 被扫描滥用 → token 认证 + 安全组限制来源 IP + 管理面板不裸暴露
  - 大日志包上传失败 → 前置 Nginx `client_max_body_size 500M`

- **LICENSE** 文件（原项目缺失）

### 修复

- 修复文档内部链接失效（7 处：迁移后路径变更、归档文档引用）

### 更新

- README 与部署指南补充场景 C 入口
- FAQ 新增 Q13（内网穿透后桥接器连不上）

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
