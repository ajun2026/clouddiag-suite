# HISTORY — 项目演进史

本文档讲清楚这个项目**从哪里来、为什么变成现在这样、架构经历了哪些关键转折**，帮助后续接手的人快速建立全局认识。

> 版本时间线速览见文末「附录：版本时间线」。
> 每个版本的详细改动清单见 [CHANGELOG.md](./CHANGELOG.md)。

---

## 八、v0.8.1：bridge 管理员提权（工具模式的能力解锁）

**背景**：工具模式第三个工具「BIOS 信息读取」真机实测发现——联想 WMI 的 `Lenovo_BiosSetting` 全量设置项需要**管理员权限**，而 bridge 从设计上"不请求管理员权限"（v2 管道化原则 4）。普通权限返回 `PermissionDenied (0x80041003)`，只能读到基础信息。

**矛盾**：既想保持"行为面最小"的克制设计，又需要管理员能力。解法是**把提权做成显式动作**，而不是改变默认行为：

- **提权实现**：`ShellExecuteW + "runas"` → UAC 弹窗 → 管理员新进程（`--elevated` 防递归）→ 自动重连同房间
- **两种触发**：命令行 `--elevate` 显式请求；双击交互模式启动时询问 `[Y/n]`（回车默认提权）
- **权限感知**：bridge 上报 `is_admin`，服务器端 BIOS 工具预判——非管理员直接给提权指引，不空跑 60s 命令
- **平台差异**：Windows 用进程 Token Elevation 检测；Linux/macOS 不支持自动提权（手动 sudo）

**意义**：这是"工具模式 → 真正的远程运维"的最后一公里——读 BIOS 只是第一步，提权能力同时为未来的「远程改 BIOS 设置」（改启动顺序、开虚拟化、设密码）铺好了路。

---

## 一、起源（v0.3.x）：Python 版 Windows 桥接器

项目最初形态是一个**面向 Windows 电脑的云上 AI 远程诊断系统**：

```
浏览器 (Web UI)  ←→  云端服务器 (server.py)  ←→  Windows 桥接器 (bridge.py / bridge.exe)
      |                        |                          |
  聊天界面              FastAPI + AI Agent          执行 systeminfo/dxdiag/
  三语支持              DeepSeek                    PowerShell/进程管理/截图...
```

### 当时的桥接器

- **语言**：Python（`bridge.py`，约 1700 行）
- **打包**：PyInstaller → `bridge.exe`，**体积 22MB**
- **职责**：**内置 45~49 个诊断工具**（截图、进程监控、网络测试、事件日志、OCR 等），头部注释写明 *"Integrated with 45 tools from winremote-mcp"*
- **依赖**：`psutil` / `Pillow` / `pyautogui` / `pywin32` / `tabulate` / `thefuzz` 等
- **平台**：仅 Windows

### 当时的服务器端

- FastAPI + WebSocket（`/ws/browser/{room}` 浏览器端、`/ws/bridge/{room}` 桥接端）
- AI Agent 通过 `tool/args` 协议调用桥接器上的 45+ 内置工具
- SQLite 聊天历史、管理后台（admin 登录）、三语 UI、实时日志

---

## 二、v0.4.0：服务器端长出"通用命令层"

在重写桥接器之前，服务器先做了一个铺垫性改动：

- 新增 `RunCommand` 通用命令执行工具：AI 可直接下发任意 PowerShell/CMD 命令
- 新增 `classify_command()` 命令风险分级器：只读（Tier 1）/ 修改（Tier 2）/ 危险（Tier 3）

**意义**：这让"执行命令"成为服务器的一等能力，为下一步"桥接器管道化"铺路——既然 AI 已经能直接发命令，桥接器其实不需要再内置那么多工具了。

---

## 三、v0.5.0：管道化重写，Go 版桥接器诞生（关键转折）

### 为什么重写？

1. **体积与分发**：PyInstaller 打包 22MB，下载慢、每次更新都要重新打包分发
2. **依赖脆弱**：Python 版依赖 6+ 第三方库（psutil、PIL、pyautogui、pywin32…），客户机环境稍有差异就装不上、跑不起来
3. **杀软敏感**：内置大量桌面操控工具（截图、点击、剪贴板），行为面大，容易被 Windows Defender / 杀毒软件标记
4. **平台单一**：只有 Windows 版，无法覆盖 Linux/macOS 运维场景
5. **维护成本**：单文件 1700 行，工具逻辑与通信逻辑耦合，改一处动全身

### 重写后的 Go 版（bridge/ 目录）

- **语言**：Go，单文件静态编译，Windows 版 **4.8MB**（-78%），免安装、免依赖
- **架构**：从「内置工具」改为「**透明管道化**」——单一职责，只做两件事：
  - **命令管道**：把服务器的命令送进本地 shell，把结果送回来
  - **文件通道**：拉取客户机文件 / 推送工具脚本（256KB 分块）
- **平台无关**：同一份代码交叉编译 Windows / Linux / macOS
- **可审计**：每条执行过的命令写入 `~/.clouddiag/bridge.log`（时间/shell/exit code/命令/结果摘要）
- **行为面最小**：无桌面操控、不请求管理员权限、不自启动、无静默后台

### 服务器端同步适配

- **平台感知**：bridge 上报 `platform`，服务器自动识别 v1 旧版 / v2 go-pipe 与目标平台（windows/linux/darwin）
- **工具收缩**：25 个桌面操控工具默认隐藏，TOOLS 46 → 26
- **命令模板库**：双平台 18 个工具模板（systeminfo/事件日志/进程/服务/网络等），Linux 走 bash、Windows 走 PowerShell
- **平台提示词**：三套 SYSTEM_PROMPT（Windows/Linux/macOS），按目标平台动态注入
- **命令分级跨平台**：classify_command 补充 Linux 规则（uname/lscpu=只读，apt install=修改，高危命令=硬拦截）
- **v1 兼容**：旧 Python bridge 仍可连接（tool/args 协议），平滑过渡

---

## 四、v0.6.x：稳定性修复

### v0.6.0

1. **修复：双击运行闪退**
   - 问题：bridge 强制要求 `-room` 参数，缺少时直接退出；用户双击 exe 时窗口一闪而过
   - 修改：无参数时进入**交互模式**——欢迎界面 → 引导输入服务器地址（回车默认）→ 输入房间码 → 自动连接；房间码为空时等按键后再退出

2. **修复：Bridge disconnected/connected 状态反复切换**
   - 问题：客户端每 25s 发 heartbeat，服务器收到后不回复；而客户端设了 75s 读超时，收不到消息就断开重连 → 每 ~75s 循环一次
   - 修改：服务器收到 heartbeat 回复 `pong`，客户端新增 `pong` 静默处理（仅重置读超时）

### v0.6.1

- 收尾：同步文档、index.html 下载链接改为 clouddiag-bridge-win64.exe（4.8MB）、三语说明更新

---

## 五、v0.7.0：Hermes 大脑并存切换（双大脑）

在 Go 管道化稳定之后，服务器端大脑从「唯一 DeepSeek」升级为「二选一可插拔」：

- **双大脑并存**：`AGENT_BRAIN` 环境变量 / WebSocket 消息 `brain` 字段选择：
  - `deepseek`（默认）：原 `run_agent()` tool-calling 循环，零改动
  - `hermes`：`run_agent_hermes()` 调本机 Hermes api_server（`127.0.0.1:8642`，自治 agent），经 **HTTP 桥** 操作远程电脑
- **新增 HTTP 桥** `POST /api/bridge/execute`（`X-Bridge-Secret` 认证）：tier 判定 →（Tier 2/3）审批弹窗 → 执行 → 返回结果；RunCommand 走动态分类
- **安全加固（事故驱动）**：Hermes 测试期间发生越权事故（agent 未走桥而是直接读源码、patch 生产代码、pkill 重启服务）。修复为两道防线——api_server 工具集最小化（仅 web+terminal）+ bridge 指南安全红线（禁读写 cab-server 文件、禁 pkill/重启）
- **进程隔离**：server 启动改 `Popen(start_new_session=True)` 脱离 Hermes 进程组，gateway 重启不再连带杀掉 cab-server

**意义**：服务器大脑从「单引擎」变为「可插拔」，并把自治 agent 的破坏性行为隔离在 HTTP 桥之外。

---

## 六、两个桥接器现状对比

| 维度 | v1 Python 版（bridge.py） | v2 Go 版（bridge/） |
|---|---|---|
| 语言 | Python（~1700 行） | Go（~815 行，8 文件） |
| 产物 | PyInstaller exe，22MB | 静态编译，4.8MB（-78%） |
| 工具形态 | 内置 45+ 诊断工具 | 零内置，纯命令管道 + 文件通道 |
| 平台 | 仅 Windows | Windows / Linux / macOS |
| 协议 | tool/args 映射 | command 直接下发命令字符串 |
| 依赖 | psutil/PIL/pyautogui/pywin32 等 | 无（仅 gorilla/websocket） |
| 审计 | 无 | `~/.clouddiag/bridge.log` 全量记录 |
| 安全 | 桌面操控工具多 | 行为面收敛，杀软友好 |
| 状态 | 保留（v1 兼容，服务器可识别） | 当前主力 |

---

## 七、架构演进总结

```
v0.3.x                 v0.4.0                 v0.5.0+                    v0.6.x
Python 桥接器           服务器长出              Go 管道化重写              稳定性修复
(内置45+工具)          通用命令层              (零内置工具)               (交互模式/心跳)
仅 Windows             + 命令分级             多平台                     连接稳定
22MB                  铺垫下一步              4.8MB / 可审计 / 杀软友好
```

**一句话演进逻辑**：从「一个内置 45 个工具的胖客户端」演进到「一个只做命令管道和文件通道的瘦管道」，把"懂业务"的部分全部上收到服务器 AI，把"执行"的部分精简到最小、最快、最安全。

**v0.7.0 之后**：桥接器形态不再演进（Go 管道已定型），重心转向服务器端大脑——从单一 DeepSeek 变为 DeepSeek/Hermes 双大脑并存、可插拔（详见第五章）。

---

## 附录：版本时间线

| 版本 | 时间 | 核心内容 |
|---|---|---|
| v0.9.4 | 2026-08-10 | **role bug 修复**：AI 回复存库 role `ai` 原样透传 API → Hermes 通道静默丢弃（AI 记不住自己说过的话）、DeepSeek 通道 400（第二次对话必挂）；API 边界映射 `ai→assistant` 一行修复；附部署地址动态化改造指南（可选） |
| v0.9.3 | 2026-08-10 | **对话安全与权限边界（四层纵深防御）**：意图门控（违禁/无关/越权硬拦截，0 token）、三平台统一安全提示词（Scope/隐私红线/防注入）、文件路径策略（个人目录弹窗审批+敏感路径硬拦）、run_powershell 过命令分级、危险命令名单扩充 |
| v0.3.0 | 2026-08-02 15:13 | 初始提交：Python bridge + FastAPI 服务器 |
| v0.3.1 | 2026-08-02 18:33 | admin 登录认证、历史删除、日志显示修复、前端错误上报 |
| v0.3.2 | 2026-08-02 22:14 | Agent 轮次 15→30、兜底消息中文化 |
| v0.4.0 | 2026-08-03 17:19 | RunCommand 通用命令层 + 命令风险分级 |
| v0.5.0 | 2026-08-03 20:38 | **Go 管道化重写**、平台感知、工具收缩、多平台 |
| v0.6.0 | 2026-08-03 | 交互模式（修复闪退）、心跳修复（修复反复断连） |
| v0.6.1 | 2026-08-03 | 收尾同步：文档、下载链接、三语说明 |
| v0.7.0 | 2026-08-07 | **Hermes 大脑并存切换**：双大脑、HTTP 桥、越权事故修复 |
| v0.8.0 | 2026-08-08 | **登录体系 + 工作台**：账号认证、房间业务绑定、对话上下文 |
| v0.8.1 | 2026-08-09 | **bridge 管理员提权**：UAC 提权、is_admin 上报、BIOS 工具预判 |
| v0.8.2 | 2026-08-09 | **体验优化**：bridge 双击自动提权（v0.6.3）、BIOS 弹窗展示 |
| v0.9.3 | 2026-08-10 | **对话安全与权限边界（四层纵深防御）**：意图门控（违禁/无关/越权硬拦截，0 token）、三平台统一安全提示词（Scope/隐私红线/防注入）、文件路径策略（个人目录弹窗审批+敏感路径硬拦）、run_powershell 过命令分级、危险命令名单扩充 |
| v0.9.1 | 2026-08-09 | **命令版桥接器**：免安装 PowerShell 脚本（`iex (iwr ...)` 一行连接，无文件运行规避杀软拦截），v2 协议全兼容（identify/heartbeat/command/文件通道），下载页新增三步操作说明 + 三语 i18n |
| v0.9.0 | 2026-08-09 | **工具模式大扩展**：睡眠/能源/驱动 3 新工具、报告文件拉回、Windows/Linux 分区、Linux 日志打包、网格卡片布局 |
