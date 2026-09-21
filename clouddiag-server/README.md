# Cloud AI Remote Diagnostics

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tools](https://img.shields.io/badge/Tools-49-orange.svg)](#tool-tiers)
[![Go Bridge](https://img.shields.io/badge/Bridge-Go-blue.svg)](bridge/)

A cloud-based AI remote diagnostics system for Windows computers. Users describe PC problems in natural language through a browser, and the cloud AI remotely executes diagnostic and repair commands via a lightweight bridge program, then provides analysis reports.

> **Live Demo:** http://<公网入口IP>:8000  
> **Admin Dashboard:** http://<公网入口IP>:8000/admin （需登录）
> **Update Log:** 详见 [CHANGELOG.md](CHANGELOG.md)
> **Project Evolution:** 项目演进史（Python → Go 重写原因、架构变化）详见 [HISTORY.md](HISTORY.md)
> **Hermes 大脑集成记录:** [docs/Hermes大脑集成与调试记录.md](docs/Hermes大脑集成与调试记录.md)

---

## Architecture

```
Browser (Web UI)  <-->  Cloud Server (server.py)  <-->  Remote PC (Go bridge)
      |                        |                              |
  Login page               FastAPI + Agent Core           Executes systeminfo/dxdiag/
  Dashboard (工单)         Brain: Hermes（默认, 自治 agent） PowerShell/process mgmt/
  Chat interface           └─ DeepSeek（兜底, 前端入口隐藏）   49 diagnostic tools
  Approval dialog          <公网入口IP>:8000              Linux/macOS/Windows
```

## Features

### User Accounts & Dashboard (v0.8.0+)
- **Login Required** -- 工号 + 密码登录（users 表，PBKDF2 密码哈希），未登录无法创建房间/进入对话
- **Workbench Dashboard** -- 登录后进入工作台：创建房间 / 加入房间 / 下载桥接器三个功能卡片 + 我的工单台账
- **Room Binding** -- 创建房间必须填写电脑 **SN 序列号 + 报修工单号**（型号选填），按 房间码 + SN + 日期 归档
- **8-Digit Room Code** -- 大写字母+数字，去掉易混字符（O/0、I/1、L、Z/2、S/5），电话报读不易错
- **My Work Orders** -- 只显示当前工程师的房间（房间码/SN/型号/工单号/状态），状态 = 连接中 / 已断开
- **Change Password** -- 登录用户可修改自己的密码
- **Conversation Memory** -- 两大脑请求自动携带最近 20 条对话历史；断线重连/刷新后自动恢复聊天记录

### AI-Powered Diagnostics
- **Natural Language Interface** -- Describe your PC problem in plain language, AI plans and executes diagnostics
- **49 Windows Tools** -- System info, screenshots, process monitoring, network tests, registry access, event logs, OCR, desktop control, and more
- **Smart Analysis** -- AI collects data, analyzes results, and produces Chinese-language diagnostic reports with markdown formatting

### Dual AI Brain (v0.7.0+, Hermes 默认)
- **Hermes Brain (default)** -- Hermes Agent 作为服务器端大脑，通过 HTTP 桥（`POST /api/bridge/execute`）操作远程电脑；前端切换下拉已移除
- **DeepSeek Brain (fallback)** -- 原 tool-calling 通道，代码保留作为兜底（`AGENT_BRAIN=deepseek` 可切回）
- **Conversation memory** -- 两通道均携带该房间最近 20 条对话，上下文连续
- **Safety first** -- Hermes api_server toolsets are locked down to `web + terminal`; a "security red line" in its system prompt forbids touching server files/processes (see [集成记录](docs/Hermes大脑集成与调试记录.md))

### Safety and Approval System
- **3-Tier Tool Classification** -- Tier 1 (read-only, safe), Tier 2 (interactive, awareness needed), Tier 3 (destructive, approval required)
- **Visual Approval Popup** -- When AI wants to use Tier 2/3 tools, a red popup appears with countdown timer
- **Auto-Approve Toggle** -- Optionally skip Tier 2 approval for faster workflows
- **Tab Title Flash** -- Browser tab flashes when approval is pending (can't miss it!)

### Admin Dashboard
- **Real-time Room Monitoring** -- See all active rooms with browser/bridge connection status
- **Machine Identification** -- Auto-detects hostname, OS, IP address, username on bridge connect
- **Chat History** -- SQLite persistence with full conversation search and export
- **Live Log Viewer** -- View server.log, chat.log in real-time from the dashboard
- **Approval Audit Trail** -- Track every approval request (approved/denied/pending)

### Multi-Language UI
- Simplified Chinese (default)
- Traditional Chinese
- English
- Language preference saved across sessions

### Data Management
- **SQLite Chat Database** -- All conversations persisted with room-level query API
- **Export Conversations** -- One-click .txt download from the chat interface
- **Admin Export** -- Download full chat history per room from the dashboard

## Tool Tiers

| Tier | Count | Type | Examples |
|:---:|:---:|:---|:---|
| **Tier 1** | 26 | Read-Only Diagnostics | `GetSystemInfo`, `Snapshot`, `Ping`, `ListProcesses`, `EventLog`, `OCR`, `NetConnections`, `FileRead` |
| **Tier 2** | 10 | Interactive Control | `Click`, `Type`, `Shortcut`, `FocusWindow`, `Scroll`, `Scrape` |
| **Tier 3** | 13 | System Modification | `Shell`, `KillProcess`, `RegWrite`, `ServiceStart/Stop`, `FileWrite`, `LockScreen` |

### Full Tool List

<details>
<summary>Click to expand all 49 tools</summary>

| Tool | Tier | Description |
|:---|:---:|:---|
| `GetSystemInfo` | T1 | CPU, memory, disk, network, uptime summary |
| `run_systeminfo` | T1 | Raw Windows systeminfo command output |
| `run_dxdiag` | T1 | DirectX diagnostic report (GPU, audio, drivers) |
| `Snapshot` | T1 | Desktop screenshot + window list + UI elements |
| `AnnotatedSnapshot` | T1 | Screenshot with numbered red rectangles on clickable elements |
| `GetClipboard` | T1 | Read Windows clipboard text |
| `ListProcesses` | T1 | List running processes with CPU/memory usage |
| `ServiceList` | T1 | List Windows services and their status |
| `TaskList` | T1 | List Windows scheduled tasks |
| `FileList` | T1 | List directory contents with size and date |
| `FileSearch` | T1 | Search files by glob pattern |
| `FileRead` | T1 | Read file content (text or binary/base64) |
| `FileDownload` | T1 | Download file as base64-encoded content |
| `RegRead` | T1 | Read Windows registry values |
| `Ping` | T1 | Ping a host |
| `PortCheck` | T1 | Check if TCP port is open |
| `NetConnections` | T1 | List active network connections |
| `read_event_log` | T1 | Read Windows System event log |
| `EventLog` | T1 | Read any Windows Event Log with level filter |
| `OCR` | T1 | Extract text from screen via OCR |
| `ScreenRecord` | T1 | Record screen as animated GIF |
| `Notification` | T1 | Show Windows toast notification |
| `Wait` | T1 | Pause execution for N seconds |
| `GetTaskStatus` | T1 | Get status of a specific task |
| `GetRunningTasks` | T1 | List all running/pending tasks |
| `run_powershell` | T1 | Execute read-only PowerShell command |
| `Click` | T2 | Mouse click at screen coordinates |
| `Type` | T2 | Type text (optionally at coordinates) |
| `Move` | T2 | Move mouse or drag |
| `Scroll` | T2 | Scroll at position |
| `Shortcut` | T2 | Execute keyboard shortcut (e.g. ctrl+c) |
| `FocusWindow` | T2 | Bring window to foreground |
| `MinimizeAll` | T2 | Minimize all windows (Win+D) |
| `ReconnectSession` | T2 | Reconnect RDP session to console |
| `Scrape` | T2 | Fetch URL content as markdown |
| `CancelTask` | T2 | Cancel a running task |
| `Shell` | T3 | Execute arbitrary PowerShell command |
| `App` | T3 | Launch/switch/resize applications |
| `KillProcess` | T3 | Kill a process by PID or name |
| `FileWrite` | T3 | Write content to a file |
| `FileUpload` | T3 | Upload file from base64 data |
| `RegWrite` | T3 | Write Windows registry values |
| `ServiceStart` | T3 | Start a Windows service |
| `ServiceStop` | T3 | Stop a Windows service |
| `TaskCreate` | T3 | Create a scheduled task |
| `TaskDelete` | T3 | Delete a scheduled task |
| `SetClipboard` | T3 | Set clipboard text |
| `LockScreen` | T3 | Lock Windows workstation |
| `PlaySound` | T3 | Play audio file on the host |

</details>

## Quick Start

### Prerequisites

- Python 3.10+
- DeepSeek API key (or any OpenAI-compatible API)
- Windows PC (for the bridge)

### Server Setup

```bash
# Clone the repository
git clone https://github.com/ajun2026/cloud-ai-remote-diag.git
cd cloud-ai-remote-diag

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Configure API key
cp .env.example .env
# Edit .env with your DeepSeek API key

# Start the server
python server.py
# Server runs at http://localhost:8000
```

### Bridge Setup (Remote PC)

Bridge 分两种：**Go 版（推荐，单文件免依赖）** 和 **Python 版（源码参考）**。

**方式 A：Go 版 bridge（推荐）**

Go 源码在 `bridge/` 目录，编译产物不入库（避免仓库膨胀），需自行编译：

```bash
# Windows 版
cd bridge
GOOS=windows GOARCH=amd64 go build -ldflags "-s -w" -o clouddiag-bridge-win64.exe .
cp clouddiag-bridge-win64.exe ../static/   # 放回 static/ 供网页下载

# Linux 版（可选）
GOOS=linux GOARCH=amd64 go build -ldflags "-s -w" -o clouddiag-bridge-linux-amd64 .
```

编译后在需要诊断的电脑上运行：
- Windows：双击 `clouddiag-bridge-win64.exe`（单文件，无需安装 Python）
- Linux：`chmod +x clouddiag-bridge-linux-amd64 && ./clouddiag-bridge-linux-amd64`
- 然后输入网页上的 8 位房间码即可连接

> 注意：仓库不包含编译好的二进制（`.gitignore` 忽略 `static/*.exe` / `static/bridge-linux-*`）。部署新服务器后需按上面编译并放入 `static/`，否则网页"下载桥接器"会 404。

**方式 B：Python 版 bridge（源码参考）**

```bash
pip install psutil Pillow pyautogui pywin32 tabulate thefuzz
python bridge.py   # 输入 8 位房间码
```

### Build bridge.exe (legacy Python bridge)

```bash
# 旧版 Python bridge 已由 Go 版取代（v0.5.0 起），仅保留源码参考
pyinstaller --onefile --name bridge --console --clean bridge.py \
  --hidden-import psutil --hidden-import PIL --hidden-import PIL.ImageGrab \
  --hidden-import pyautogui --hidden-import win32api --hidden-import tabulate \
  --collect-all pyautogui
# Output: dist/bridge.exe (~22MB)
```

## Configuration

Create a `.env` file in the project root (template: `.env.example`):

```env
# API Configuration (DeepSeek or any OpenAI-compatible API)
OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_API_KEY=sk-your-api-key-here
OPENAI_MODEL=deepseek-chat

# Server Configuration
SERVER_HOST=0.0.0.0
SERVER_PORT=8000

# --- Hermes Brain (optional, default OFF) ---
# 不配置以下项 = 纯 DeepSeek 大脑，行为等同旧版。
# 启用后可在页面顶部 🧠 下拉按消息切换大脑。
# HERMES_BASE_URL=http://127.0.0.1:8642/v1   # 本机 Hermes gateway api_server
# HERMES_API_KEY=your-api-server-key
# HERMES_MODEL=hermes-agent
# AGENT_BRAIN=deepseek                        # 默认大脑: deepseek | hermes
# BRIDGE_HTTP_SECRET=change-me-to-a-long-random-string   # HTTP 桥密钥（必改）
```

> ⚠️ 启用 Hermes Brain 需要本机部署 Hermes Agent（gateway + api_server 端口 8642），
> 且必须把 `~/.hermes/config.yaml` 的 `platform_toolsets.api_server` 限制为 `[web, terminal]`，
> 否则 Hermes 作为自治 agent 可能越权操作服务器（事故详情见 [集成记录](docs/Hermes大脑集成与调试记录.md)）。

## Project Structure

```
cloud-ai-remote-diag/
  server.py              FastAPI + WebSocket + AI Agent core (Dual Brain)
  bridge.py              Legacy Python bridge (source reference)
  bridge/                Go bridge source (v0.5.0+, recommended)
  static/
    index.html           Web UI (zh-CN/zh-TW/EN) + brain switcher
  docs/
    Hermes大脑集成与调试记录.md   Hermes Brain integration & incident record
  .env.example           Environment template (DeepSeek + optional Hermes)
  requirements.txt       Python dependencies
  CLAUDE.md              Project documentation (Chinese)
  logs/                  Runtime logs + SQLite DB (gitignored)
    server.log
    chat.log
    chat.db
  dist/                  Built legacy bridge.exe (gitignored)
```

## API Endpoints

| Endpoint | Method | Description |
|:---|:---:|:---|
| `/` | GET | Web UI |
| `/admin` | GET | Admin dashboard |
| `/api/health` | GET | Server health check |
| `/api/rooms` | POST | Create a new room (returns 6-digit code) |
| `/api/history/{room}` | GET | Get chat history for a room |
| `/api/rooms/list` | GET | List all rooms with message counts |
| `/api/diag/{room}` | GET | Room health diagnostics (bridge status, heartbeat, cmd history) |
| `/api/bridge/execute` | POST | **HTTP bridge** for Hermes brain — execute a tool on the remote PC (auth: `X-Bridge-Secret`) |
| `/api/admin/stats` | GET | Server statistics (rooms, messages, approvals) |
| `/api/admin/logs/{name}` | GET | View server/chat/bridge logs |
| `/ws/browser/{room}` | WebSocket | Browser-side connection |
| `/ws/bridge/{room}` | WebSocket | Bridge-side connection |

### HTTP Bridge (`POST /api/bridge/execute`)

```json
// Header: X-Bridge-Secret: <BRIDGE_HTTP_SECRET>
{"room_code": "ABC123", "tool": "RunCommand", "args": {"command": "Get-Temperature"}}
```

```json
// Response
{"status": "ok", "tool": "RunCommand", "tier": 1, "result": "..."}
{"status": "denied", "tier": 3, "reason": "..."}
{"status": "blocked", "reason": "dangerous command"}
```

Tier 1 直接执行；Tier 2/3 会向浏览器用户弹审批窗，接口阻塞等待批准后返回结果。

## WebSocket Protocol

### Browser to Server
```json
{"type": "chat", "content": "My PC is running slow", "brain": "deepseek"}
{"type": "approval_response", "id": "approve_xxx", "approved": true}
{"type": "auto_approve_toggle", "enabled": true}
```
> `brain` 字段可选：`deepseek`（默认）或 `hermes`，按消息切换大脑；不传则用环境变量 `AGENT_BRAIN`。

### Server to Browser
```json
{"type": "tool_start", "tool": "ListProcesses", "args": {...}, "tier": 1}
{"type": "tool_result", "tool": "ListProcesses", "content": "..."}
{"type": "approval_required", "id": "approve_xxx", "tool": "KillProcess", "tier": 3}
{"type": "ai_message", "content": "# Diagnostic Report..."}
{"type": "status", "content": "Bridge connected [OK]"}
```

### Server to Bridge
```json
{"type": "command", "id": "cmd_1_xxx", "tool": "GetSystemInfo", "args": {}}
```

### Bridge to Server
```json
{"type": "command_result", "id": "cmd_1_xxx", "output": "System: Windows 11..."}
{"type": "identify", "info": {"hostname": "DESKTOP-PC", "os": "Windows 11"}}
```

## Tech Stack

| Component | Technology |
|:---|:---|
| **Server Framework** | FastAPI + Uvicorn |
| **Real-time Communication** | WebSockets |
| **AI Engine (default)** | DeepSeek (OpenAI-compatible API, tool-calling loop) |
| **AI Engine (optional)** | Hermes Agent (autonomous agent via HTTP bridge) |
| **Remote Bridge** | Go (single binary, v0.5.0+) / legacy Python asyncio |
| **Desktop Automation** | Go native (legacy: PyAutoGUI + PyWin32 + Pillow) |
| **System Monitoring** | psutil (legacy Python bridge) |
| **Database** | SQLite (chat history + approvals) |
| **Frontend** | Vanilla HTML/CSS/JS (zero dependencies) |
| **Packaging** | Go build (single binary, ~4.8MB) |

## License

MIT License

## Credits

- **WinRemote MCP** by [dddabtc](https://github.com/dddabtc) -- The 45 Windows tools integrated into the bridge
- **DeepSeek** -- AI model powering the diagnostic agent
- Built with FastAPI, PyAutoGUI, PyWin32, and many other open-source projects

---

**Status:** Production | **Version:** 0.4.0 (Hermes Brain) | **Last Updated:** 2026-08-07
