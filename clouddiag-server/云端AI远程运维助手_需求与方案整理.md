# 云端 AI 远程运维助手 — 需求沟通与方案整理

> 文档性质：需求讨论记录 + 技术方案
> 沟通时间：2026-07-30
> 参与方：主人（需求方） / 旺财（方案整理）
> 关联文档：`cloudagent_bridge_方案.md`（完整技术方案）

---

## 一、沟通背景

### 1.1 起点：用户提供的参考项目

主人提供了一个参考链接：**https://agent-room.daboluo.cc/**（页面标题为 **Relayer**）

**旺财调研结论：**

| 项目 | 说明 |
|:---|:---|
| **Relayer（daboluo.cc）** | 智慧芽（PatSnap）公司内部工具的前端部署，JS 中暴露内部仓库地址 `git.patsnap.com/devops/tool/Relayer` |
| **Agent Room（开源版）** | GitHub: `ebin198351-akl/agent-room`（MIT），核心是 MCP Server + 9 位房间码 + 浏览器协作 |

**Agent Room 核心机制（官方 README）：**
- 9 位房间码，浏览器免登录加入
- 云端只做"房间/状态/路由"（Vercel + Upstash Redis）
- AI 能力在客户端本地（Claude Code、Cursor、Codex 等通过 MCP 接入）
- 结构化产物 `[DECISION]` `[TODO]` `[STATUS]` `[RESULT]`
- 证据门控任务板、Webhook 唤醒、项目记忆、报告导出

**Relayer 比开源版多的能力：**
- Agent 管理（授权 grants、Token、钉钉通道）
- channel-computer（远程电脑通道）、workspace（工作区）
- collector / distill（信息收集与提炼）
- 平台级记忆、SkillHub 技能中心、管理后台

### 1.2 主人的项目设想（原话要点）

> "我想做一个项目，借鉴一下刚才那个链接。要求如下：主要解决软件问题……我的理解是通过浏览器连接到用户的本地客户端，将 AI 能力集成在云端。我们可以在云端建立一个单一的 Agent，专门解决这一类问题。"

**核心差异：** 原项目是"薄云端 + 客户端自带 AI"；主人的设想是反过来的——**浏览器 → 本地客户端（执行器）→ 云端单一 Agent（大脑）**，AI 能力统一收在云端。

---

## 二、目标场景（主人明确的具体需求）

### 2.1 首个落地场景：Windows 系统远程诊断

> "我的电脑是 Windows 系统，目前可能出现一些系统问题，或者某个软件运行有什么报错，或者某个驱动有问题，或者说想要让人远程帮忙看看系统日志、dxdiag 日志、运行一个 smartmoon tool 检测工具，或者在 Windows PowerShell 中跑一个命令等这些测试需求。但是我不会操作或者不方便操作，就是想找人帮忙搞定。这个时候我想登录一个 web 网页，让远程的一个 AI Agent 来帮我解决这些问题。"

**使用流程（主人视角）：**
1. Windows 电脑安装轻量"小机器人"（桥接器）
2. 浏览器打开网页，输入 6 位配对码完成绑定
3. 用自然语言提出需求（如"帮我查查为什么蓝屏"）
4. 云端 AI 逐步操作本地电脑（systeminfo、dxdiag、事件日志、SMART 检测、PowerShell）
5. 全程可视化 + 高危操作审批
6. AI 输出大白话诊断报告

### 2.2 扩展场景：软件问题处理

| 场景 | 可实现性 | AI 做法 |
|:---|:---:|:---|
| 软件报错 | ✅ | 抓事件日志/错误弹窗/崩溃记录，分析原因给方案 |
| 软件卡顿 | ✅ | 查 CPU/内存/磁盘占用，找资源大户，给优化建议 |
| 软件闪退 | ✅ | 查应用程序错误日志 + Windows 错误报告（WER），定位崩溃模块 |
| 安装软件 | ✅（两种方式） | ① 静默安装（全自动，需网页确认）② 引导式安装（AI 打开安装向导，用户点下一步，或 AI 远程模拟点击） |

**边界说明：**
- 管理员权限操作需用户本地 UAC 确认（系统安全设计，无法绕过）
- 杀毒软件拦截需用户配合
- 需重启的安装会在重启后要求重新确认连接

### 2.3 价值主张

- 用户本地**无需安装任何 AI 工具**（不需要 Claude/Cursor 等）
- AI 大脑统一在云端，升级换模型用户无感知
- 团队可共用同一"云端工程师"
- 诊断命令几乎全只读，风险低、价值直接可见

---

## 三、架构方案（CAB：CloudAgent Bridge）

### 3.1 三层架构

```
┌────────────┐     HTTPS/WSS      ┌─────────────────────────────┐
│  浏览器      │◄─────────────────►│        云端 CAB Server        │
│  (Web UI)   │   /v1/rooms       │  ┌─────────────────────────┐ │
└────────────┘   /v1/agents       │  │  单一 Agent 核心         │ │
                                  │  │  · 任务规划器 (planner)  │ │
┌────────────┐     HTTPS/WSS      │  │  · 工具调度器 (tools)    │ │
│ 本地桥接器   │◄─────────────────►│  │  · 记忆系统 (memory)     │ │
│ (Windows)  │   /v1/bridge       │  │  · 技能库 (skills)      │ │
│ 文件/终端/  │   /v1/tasks       │  │  · 会话/审计 (audit)    │ │
│ 端口代理    │                   │  └─────────────────────────┘ │
└────────────┘                   │  存储: Postgres + Redis     │
                                 └─────────────────────────────┘
```

### 3.2 三大组件职责

| 组件 | 技术选型 | 职责 |
|:---|:---|:---|
| **Web UI** | React/Next.js + WebSocket | 聊天界面、任务看板、代码/日志 Diff 视图、审批弹窗 |
| **云端 Agent 核心** | Python FastAPI + LangGraph | 规划→执行→验证闭环、工具调用、记忆与技能 |
| **本地桥接器** | Go 单二进制（或复用 WinRemote MCP） | 文件读写、终端执行、git、端口代理、心跳 |

### 3.3 通信协议（v1 核心）

- `POST /v1/rooms` — 创建房间（9 位码）
- `WSS /v1/rooms/{id}/ws` — 实时消息流
- `POST /v1/bridge/task` — 云端向桥接器下发任务
- `POST /v1/bridge/result` — 桥接器回传结果
- `POST /v1/approvals` — 高危操作审批

消息类型：`task | command | command_result | trace | presence | approval`

### 3.4 单一 Agent 任务闭环

```
用户需求 → 规划拆解 → 通过桥接器执行 → 验证结果 → 输出报告
              ↕ 每次工具调用前可走人工审批（浏览器一键允许/拒绝）
```

---

## 四、可行性结论

### ✅ 结论：完全可实现
- 所有技术点均有成熟方案（WSS、MCP 工具协议、PTY 流式终端、配对认证）
- Agent Room 已验证"房间+桥接+审批"协议可行
- 本方案把大脑搬到云端，不依赖本地 AI 环境，风险更低

### ⚠️ 需重点设计的难点

| 难点 | 对策 |
|:---|:---|
| 本地终端安全 | 白名单目录 + 命令黑名单 + 审批 + 全程审计 |
| 长任务断线 | 任务队列持久化，桥接器重连续跑（幂等 token） |
| 文件读写并发 | 单房间串行化写操作 |
| 云端→本地延迟 | 操作走 REST 短连接，输出流走 WSS |
| 多用户共用 Agent | 会话隔离 + 记忆按项目分隔 |

### 💰 MVP 成本估算
- 云服务器 ¥200~500/月 + 模型 API ¥50~200/月 + 域名 ¥100/年 ≈ **¥400~800/月**

### 📅 路线图
- **演示版（1~2 周）**：网页聊天 + 云端 AI + Windows 小机器人（systeminfo / dxdiag / 事件日志 / PowerShell）
- **增强版（+1 周）**：SMART 硬盘检测、蓝屏 minidump 分析、驱动信息收集
- **正式版（1~2 月）**：修复操作 + 审批流、多用户、计费、审计后台

---

## 五、开源项目调研结果

### 5.1 最相关项目

| 项目 | 地址 | 特点 |
|:---|:---|:---|
| **WinRemote MCP** ⭐ | `github.com/dddabtc/winremote-mcp` | 40+ 工具：桌面自动化、进程管理、文件操作、网络诊断（ping/端口检查）；MIT；Python；163⭐；有中文文档，支持 OpenClaw |
| **Windows-Use** | `github.com/CursorTouch/Windows-Use` | GUI 层面操作 Windows，模拟点击输入 |
| **mcp-windows** | `github.com/sbroenne/mcp-windows` | Windows UI Automation API，按元素名称操作按钮 |
| **windows-computer-use-mcp** | `github.com/sandraschi/windows-computer-use-mcp` | 22 个 MCP 工具：点击/输入/截图/OCR/UI 检查 |
| **Windows-MCP** | `github.com/CursorTouch/Windows-MCP` | 轻量，Windows 7~11 |
| **AgentDesk** | `github.com/agentsea/agentdesk` | 云端虚拟桌面 + REST API 控制（云端思路参考） |
| **Pane** | `github.com/dcouple/Pane` | 手机/浏览器远程管理多个 coding agent（AGPL） |

### 5.2 组合策略（不重复造轮子）

```
浏览器网页 ←→ 云端 Agent ←→ 本地桥接器 ←→ Windows
                                ↑
            复用 WinRemote MCP / mcp-windows 作为桥接器的"手脚"
```

| 需求 | 现成方案 | 需自研 |
|:---|:---|:---|
| PowerShell / dxdiag / systeminfo | ✅ WinRemote MCP | — |
| 网络诊断 | ✅ WinRemote MCP | — |
| GUI 点击/装软件 | ✅ mcp-windows / windows-computer-use | — |
| 浏览器网页 | ❌ | ✅ 自研（核心） |
| 云端 Agent 编排 | ⚠️ 部分 | ✅ 自研（可基于 Hermes/OpenClaw 框架） |

### 5.3 WinRemote MCP 地址确认（GitHub API 已验证）

```
https://github.com/dddabtc/winremote-mcp
```
- 名称：`dddabtc/winremote-mcp`
- 描述：Windows Remote MCP Server — 40+ tools for desktop automation, process management, file operations via FastMCP
- 语言：Python / 协议：MIT / Stars：163
- 注意：PyPI 包名不是 `win-remote-mcp`，以仓库 README 为准

---

## 六、下一步建议

1. **拉取 WinRemote MCP** 源码，评估工具清单与改造成本
2. **确定 MVP 范围**：以"Windows 诊断 + 浏览器聊天 + 云端 Agent"为第一版
3. **搭建骨架**：云端 FastAPI（房间+WSS）→ 桥接器（复用 WinRemote MCP）→ 最简网页
4. **验证闭环**：浏览器说一句"帮我查蓝屏原因" → 云端调 DeepSeek → 桥接器在本地跑诊断 → 浏览器看到报告
5. **迭代增强**：审批流 → 记忆 → 技能库 → 多用户

---

*文档由旺财整理 · 2026-07-31*
