# 云端 AI 远程运维助手 — 产品需求与技术规格文档（PRD/SRS）

| 项目 | 内容 |
|:---|:---|
| **文档版本** | v1.0 |
| **文档性质** | 产品需求文档（PRD）+ 软件需求规格（SRS） |
| **适用对象** | 产品团队、开发团队、AI 辅助开发 Agent |
| **目标平台** | Windows 客户端 + Web 浏览器 + 云端服务器 |

---

## 1. 引言

### 1.1 项目概述

本项目构建一个"**云端 AI 远程运维助手**"：用户在浏览器中通过自然语言与云端 AI Agent 交互，AI Agent 通过安装在用户 Windows 电脑上的轻量级"桥接器"程序，远程执行系统诊断、软件问题排查与修复等操作。系统面向**不熟悉或不便自行操作电脑**的用户，将"找人帮忙修电脑"的场景产品化、自动化。

### 1.2 背景与参考

项目思路参考了开源项目 **Agent Room**（`github.com/ebin198351-akl/agent-room`，MIT 协议）：

- Agent Room 的核心是"多 Agent 协作房间"：通过 9 位房间码，让 Claude Code、Cursor、Codex 等本地 AI 客户端加入同一协作空间；云端仅承担房间、状态、消息路由职责（Vercel + Upstash Redis 实现），AI 推理能力位于用户本地客户端。
- 本项目**反向设计**：AI 推理能力统一收敛到云端（单一 Agent），用户本地仅保留一个轻量桥接器作为"手脚"（执行终端命令、读写文件），浏览器作为唯一人机交互界面。

### 1.3 核心差异（与 Agent Room 对比）

| 维度 | Agent Room | 本项目 |
|:---|:---|:---|
| AI 大脑位置 | 用户本地（Claude Code 等） | **云端单一 Agent** |
| 用户本地组件 | 全套 AI CLI 工具 | **单一轻量桥接器** |
| 云端职责 | 房间/状态/路由（薄） | 大脑 + 调度 + 记忆 + 技能（厚） |
| 浏览器角色 | 观察与发言 | **主操作界面** |
| 核心价值 | 多 Agent 协作开发 | 无需本地 AI 环境，一个云端 Agent 解决电脑问题 |

### 1.4 目标用户

- 非技术用户：不懂命令行、不会看系统日志，但需要解决电脑问题
- 不方便操作的用户：远程办公、出差在外，需要排查家中/公司电脑问题
- 小型团队：共享同一云端 Agent，统一为成员提供技术支持

---

## 2. 功能需求（按优先级）

### 2.1 P0 — 系统远程诊断（第一优先级）

用户通过浏览器发起诊断请求，云端 Agent 通过桥接器在用户 Windows 电脑上执行诊断操作并返回结果。

**支持的具体诊断能力：**

| 编号 | 功能 | 说明 |
|:---|:---|:---|
| F1 | 系统信息收集 | 执行 `systeminfo`，获取 OS 版本、硬件、内存等信息 |
| F2 | 显示诊断报告 | 执行 `dxdiag /t`，生成并解析 DirectX 诊断日志 |
| F3 | 事件日志分析 | 读取 Windows 事件日志（系统/应用程序），筛选错误与警告 |
| F4 | 硬盘健康检测 | 调用 SMART 检测工具（如 CrystalDiskInfo）读取硬盘健康状态、温度、坏道信息 |
| F5 | PowerShell 命令执行 | 在 Windows PowerShell 中执行用户指定的诊断命令 |
| F6 | 网络诊断 | ping、端口连通性检查、网络适配器状态 |
| F7 | 驱动信息查询 | 列出已安装驱动及其版本、状态 |
| F8 | 蓝屏分析（增强） | 读取 minidump 崩溃转储文件，分析蓝屏原因 |

**流程：**
1. 用户在浏览器输入自然语言需求（如"帮我查查为什么蓝屏"）
2. 云端 Agent 规划诊断步骤
3. 桥接器逐条执行命令，输出实时回传浏览器（流式）
4. Agent 综合分析，输出大白话诊断报告与修复建议

### 2.2 P1 — 软件问题处理

| 编号 | 场景 | 实现方式 |
|:---|:---|:---|
| F9 | 软件报错分析 | 抓取事件日志、错误弹窗内容、崩溃记录，定位原因并给方案 |
| F10 | 软件卡顿排查 | 查询 CPU/内存/磁盘占用，定位资源大户，给出优化建议 |
| F11 | 软件闪退分析 | 分析应用程序错误日志 + Windows 错误报告（WER），定位崩溃模块 |
| F12 | 软件安装 | 两种模式：① 静默安装（命令行参数，全自动）；② 引导式安装（AI 打开安装向导，用户在本地点击，或 AI 远程模拟点击） |
| F13 | 修复操作（P2 增强） | 更新驱动、修改设置、清理缓存等，均需用户审批 |

### 2.3 P2 — 协作与记忆

| 编号 | 功能 | 说明 |
|:---|:---|:---|
| F14 | 多用户共用 Agent | 团队共享同一云端 Agent，会话按用户/项目隔离 |
| F15 | 项目记忆 | 按机器/项目持久化历史诊断结论，后续任务自动注入上下文 |
| F16 | 报告导出 | 诊断完成自动生成可导出的报告（PDF/Word） |
| F17 | 审计日志 | 所有操作留痕（操作人、命令、时间、审批状态） |

---

## 3. 非功能需求

| 编号 | 类别 | 要求 |
|:---|:---|:---|
| N1 | 安全 | 诊断命令默认只读；所有"修改类"操作必须经用户浏览器确认 |
| N2 | 安全 | 桥接器支持"一键断开"，断开后云端无法再下发指令 |
| N3 | 安全 | 目录/命令白名单机制，可配置允许访问的路径 |
| N4 | 权限 | 三级权限模型：只读 → 终端执行 → 高危操作（需审批） |
| N5 | 可用性 | 诊断场景下浏览器操作延迟 < 2s（网络正常时） |
| N6 | 可靠性 | 桥接器断线自动重连，长任务可断点续跑 |
| N7 | 兼容性 | Windows 10 / 11（64 位）；浏览器 Chrome / Edge / Firefox 最新版 |
| N8 | 合规 | 数据传输加密（HTTPS/WSS）；敏感信息（API Key 等）加密存储 |

---

## 4. 系统架构

### 4.1 总体架构

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

### 4.2 组件职责

| 组件 | 技术选型 | 职责 |
|:---|:---|:---|
| Web UI | React / Next.js + WebSocket | 聊天界面、任务看板、日志/Diff 展示、审批弹窗 |
| 云端 Agent 核心 | Python FastAPI + LangGraph | 规划→执行→验证闭环、工具调用、记忆与技能 |
| 本地桥接器 | Go 单二进制（或复用 WinRemote MCP 改造） | 文件读写、终端执行、git、端口代理、心跳上报 |
| 存储 | PostgreSQL + Redis | 关系数据 + 实时状态/任务队列 |

### 4.3 通信协议（v1）

- 消息模型（JSON over WebSocket）：

```json
{
  "id": "msg_xxx",
  "type": "task|command|command_result|trace|presence|approval",
  "room_id": "ABC-DEF-GHJ",
  "sender": "agent|user|bridge",
  "target": "agent|bridge",
  "payload": {},
  "metadata": { "phase": "plan|exec|verify", "command_id": "cmd_1" }
}
```

- 核心接口：
  - `POST /v1/rooms` — 创建房间（返回 9 位房间码）
  - `WSS /v1/rooms/{id}/ws` — 实时消息流（浏览器与桥接器共用）
  - `POST /v1/bridge/task` — 云端向桥接器下发任务
  - `POST /v1/bridge/result` — 桥接器回传执行结果/输出流
  - `POST /v1/approvals` — 高危操作审批（浏览器弹窗确认）

### 4.4 任务闭环

```
用户需求 → [规划] 拆解子任务 → [执行] 桥接器操作本地
   → [验证] 检查结果 → [汇报] 输出诊断报告与建议
        ↕ 修改类操作每次调用前走人工审批
```

### 4.5 配对与安全流程

1. 用户在浏览器生成 6 位配对码
2. 本地桥接器输入配对码，绑定到用户账户/房间
3. 桥接器每 10 秒心跳上报在线状态
4. 高危操作由云端生成审批请求 → 浏览器弹窗 → 用户允许/拒绝 → 记录审计

---

## 5. 数据模型（核心表）

```sql
rooms        (id, code, owner_id, title, gated, created_at, ended_at)
agents       (id, label, model, system_prompt, api_base, api_key_enc)
bridges      (id, agent_id, user_id, status, os, last_seen, allow_dirs)
messages     (id, room_id, sender, type, payload_json, created_at)
tasks        (id, room_id, title, status, phase, evidence, assignee)
tool_calls   (id, task_id, tool, args_json, result_hash, approval_state)
memories     (id, scope_kind, scope_key, content, state)
skills       (id, name, source, version, enabled)
audit_log    (id, actor, action, detail_json, created_at)
```

---

## 6. 技术选型

| 层 | 选型 | 理由 |
|:---|:---|:---|
| 后端 | Python FastAPI + Uvicorn | 与 AI 生态无缝集成，异步 WebSocket 支持好 |
| Agent 编排 | LangGraph（或自研状态机） | Agent 循环、工具调用、条件分支成熟 |
| 前端 | Next.js + React + Tailwind | 快速迭代，SSR 支持好 |
| 实时通信 | WebSocket（房间维度广播） | 消息/输出流/审批全走 WSS |
| 存储 | PostgreSQL + Redis | 关系数据 + 实时状态/任务队列 |
| 桥接器 | Go 单二进制（首选） | 跨平台免依赖，交叉编译容易 |
| 部署 | Docker Compose → K8s | 先单机后集群 |
| 模型 | DeepSeek V4 / 多厂商切换 | 成本低，兼容 OpenAI API |

---

## 7. 开源参考与复用

| 项目 | 地址 | 复用点 |
|:---|:---|:---|
| **WinRemote MCP** | `github.com/dddabtc/winremote-mcp` | 40+ Windows 自动化工具（进程管理、文件操作、网络诊断 ping/端口检查），可作为桥接器"手脚"的现成实现；MIT 协议，Python |
| **Windows-Use** | `github.com/CursorTouch/Windows-Use` | GUI 层面操作 Windows（模拟点击输入） |
| **mcp-windows** | `github.com/sbroenne/mcp-windows` | Windows UI Automation API，按元素名称操作（不受分辨率/DPI 影响） |
| **windows-computer-use-mcp** | `github.com/sandraschi/windows-computer-use-mcp` | 22 个 MCP 工具：点击/输入/截图/OCR/UI 检查 |
| **AgentDesk** | `github.com/agentsea/agentdesk` | 云端虚拟桌面 + REST API 控制（云端思路参考） |
| **Pane** | `github.com/dcouple/Pane` | 浏览器/手机远程管理多个 agent（AGPL） |

**组合策略：** 桥接器优先复用 WinRemote MCP / mcp-windows 能力；云端 Agent 基于 Hermes / OpenClaw 框架构建；Web UI 为自研核心。

---

## 8. 风险与对策

| 风险 | 等级 | 对策 |
|:---|:---|:---|
| 本地终端安全（恶意命令） | 高 | 目录白名单 + 命令黑名单 + 高危审批 + 全程审计 |
| 长任务断线 | 中 | 任务队列持久化，桥接器重连续跑（幂等 token） |
| 文件读写并发冲突 | 中 | 单房间写操作串行化加锁 |
| 云端→本地延迟 | 中 | 操作类走 REST 短连接，输出流走 WSS |
| 多用户共用 Agent 串扰 | 中 | 会话隔离 + 记忆按项目/机器分隔 |
| 管理员权限（UAC） | 低 | 需用户本地确认（系统安全设计，不可避免） |
| 杀毒软件拦截 | 低 | 检测并提示用户处理 |

---

## 9. 开发路线图

### Phase 1 — MVP 演示版（1~2 周）
- [ ] 云端 FastAPI：房间/消息 API + WebSocket
- [ ] 本地桥接器（Go 或复用 WinRemote MCP）：文件读写 + 终端执行 + 心跳 + 配对
- [ ] 浏览器聊天 UI（消息流 + 流式输出）
- [ ] 最小闭环：用户指令 → 规划 → 桥接器执行 → 结果回显
- [ ] 支持命令：`systeminfo`、`dxdiag`、事件日志、PowerShell 任意命令

### Phase 2 — 增强版（+1~2 周）
- [ ] SMART 硬盘检测（CrystalDiskInfo 集成）
- [ ] 蓝屏分析（minidump 解析）
- [ ] 驱动信息收集
- [ ] 任务看板 + 证据门控
- [ ] 审批流（高危操作浏览器确认）

### Phase 3 — 产品化（1~2 月）
- [ ] 软件安装（静默/引导两种模式）
- [ ] 修复操作执行 + 审批
- [ ] 多用户协作 + 角色权限
- [ ] 项目记忆 + 报告导出
- [ ] 审计后台 + 用量统计
- [ ] 私有化部署包（Docker Compose 一键部署）

---

## 10. 验收标准（MVP）

1. 用户在 Windows 10/11 电脑安装桥接器，输入配对码后浏览器可看到"已连接"状态
2. 用户在浏览器输入"帮我查一下系统信息"，Agent 能返回 `systeminfo` 的解析结果
3. 用户在浏览器输入"导出 dxdiag 报告"，Agent 能生成并展示诊断报告内容
4. 用户在浏览器输入"看看最近有什么系统错误"，Agent 能列出事件日志中的错误条目
5. 用户在浏览器输入一条 PowerShell 命令，命令在本地执行且输出实时回传
6. 所有诊断命令在"只读模式"下执行，未授权不得修改系统
7. 点击"断开连接"，桥接器立即失效，云端无法继续下发指令

---

*文档结束 · 本规格文档自包含，可直接作为开发与评审依据*
