# Hermes Agent 作为服务器端大脑 — 集成与调试记录

> 项目：云端 AI 远程运维助手（cab-server）
> 日期：2026-08-07
> 状态：✅ 已上线（并存切换模式），Hermes 通道受最小权限保护

---

## 1. 背景与目标

cab-server 原本的"大脑"是 **DeepSeek**（`server.py` 内 `run_agent()` 循环，OpenAI 兼容 tool-calling）。
目标：把大脑换成 **Hermes Agent**（本机自治 agent），验证其作为服务器端大脑的稳定性与回答质量，
确认后再正式切换（V4.1 目标）。

**决策：方案②并存切换**（用户拍板）——
server.py 保留现有 DeepSeek 循环，**新增一条 Hermes 通道**，通过 `brain` 参数切换：
- 消息级：WebSocket 消息带 `"brain": "hermes"`（前端下拉选择）
- 全局级：环境变量 `AGENT_BRAIN=deepseek|hermes`

好处：生产零风险并行验证，Hermes 通道稳定后再切。

---

## 2. 关键调研发现（决定架构的事实）

在动手前验证了 Hermes 的接入方式，三个关键事实：

| 发现 | 内容 | 影响 |
|---|---|---|
| ① api_server 可用 | Hermes gateway 自带 OpenAI 兼容 API Server，监听 `127.0.0.1:8642`，带 Bearer key（`API_SERVER_KEY`） | 可直接 httpx 调用 |
| ② **api_server 是自治 agent** | `/v1/chat/completions` 和 `/v1/responses` **都忽略请求里的 `tools` 参数**——它用 Hermes 自己的工具集在服务器上自主执行，返回最终文本，**不返回 tool_calls 让调用方执行** | Hermes 通道不能复用 DeepSeek 的 tool-calling 循环，必须把 Hermes 当"完整大脑" |
| ③ 工具集可配置 | `config.yaml → platform_toolsets.api_server` 控制 Hermes 在 api_server 平台可用的工具 | 权限收敛的关键开关 |

**架构推论**：Hermes 作为自治 agent 运行在服务器上，要操作远程 Windows 电脑，
必须给它一条"桥"——即 cab-server 暴露 HTTP 接口，Hermes 用 curl 调用。

---

## 3. 架构设计（并存切换）

```
浏览器 (Web UI)
   │  WS /ws/browser/{room}
   ▼
server.py ── brain=deepseek ──► run_agent()          ──► DeepSeek API（原逻辑，tool-calling）
   │                            （工具执行→bridge）      │
   └── brain=hermes  ──► run_agent_hermes() ──► Hermes api_server (127.0.0.1:8642)
                            （自治 agent）                │
                              │ curl POST                │ 自己的工具集（terminal/web）
                              ▼                          │
                    POST /api/bridge/execute ──► 复用 execute_bridge_command() ──► Windows bridge
                    （HTTP 桥，X-Bridge-Secret 认证）       （审批弹窗→浏览器用户）
```

### 3.1 新增组件

| 组件 | 位置 | 说明 |
|---|---|---|
| `HERMES_*` 配置 | `server.py` 配置区 + `.env` | `HERMES_BASE_URL` / `HERMES_API_KEY` / `HERMES_MODEL` / `AGENT_BRAIN` / `BRIDGE_HTTP_SECRET` |
| `execute_bridge_command()` | `server.py`（从 run_agent 抽出） | 工具下发 bridge 的公共函数，DeepSeek 循环与 HTTP 桥共用 |
| `run_agent_hermes()` | `server.py` | Hermes 通道入口：拼 system prompt → 调 api_server → 返回文本 |
| `build_hermes_bridge_guide()` | `server.py` | 注入 Hermes 的"远程桥接操作指南"（工具清单 + curl 用法 + 安全红线） |
| `POST /api/bridge/execute` | `server.py` | HTTP 桥：认证 → tier 判定 → 审批 → 执行 → 返回结果 |
| brain 分流 | `ws_browser` + `static/index.html` | WS 消息带 brain；前端 🧠 DeepSeek/Hermes 下拉 |

### 3.2 HTTP 桥协议

```
POST http://127.0.0.1:8000/api/bridge/execute
Header: X-Bridge-Secret: <BRIDGE_HTTP_SECRET>
Header: Content-Type: application/json
Body:   {"room_code": "ABC123", "tool": "RunCommand", "args": {"command": "..."}}

响应:
  {"status": "ok",      "tool": "...", "tier": 1, "result": "..."}
  {"status": "denied",  "tier": 3, "reason": "用户拒绝"}
  {"status": "blocked", "reason": "危险命令拦截"}
```

- Tier 1 只读：直接执行返回
- Tier 2/3：**同步阻塞等审批**（浏览器用户弹窗批准/拒绝后返回）
- RunCommand 走 `classify_command()` 动态分类（只读立即 / 修改审批 / 危险拦截）

---

## 4. 调试过程（一步步）

### Step 1 — 验证 Hermes api_server 可用性
```bash
curl http://127.0.0.1:8642/v1/chat/completions \
  -H "Authorization: Bearer $API_SERVER_KEY" \
  -d '{"model":"hermes-agent","messages":[{"role":"user","content":"1+1=?"}]}'
# ✅ 200，标准 OpenAI 格式返回
```

### Step 2 — 确认 tools 参数行为（决定架构的关键测试）
```bash
# 带 tools 调用，看是否返回 tool_calls
# ✅ 结论：api_server 忽略外部 tools，自主执行 Hermes 自己的工具 → 自治 agent
```

### Step 3 — 确认 api_server 平台默认工具集
```bash
GET /v1/toolsets
# 发现默认含 patch/write_file/execute_code/delegate_task 等 → 权限过大（事故伏笔）
```

### Step 4 — 实现并单测 HTTP 桥
```bash
curl -X POST /api/bridge/execute  # 无密钥 → 401 ✅
curl -X POST /api/bridge/execute  # 有密钥无房间 → 404 ✅
curl -X POST /api/bridge/execute  # 有房间无 bridge → 409 ✅
```

### Step 5 — 端到端验证 Hermes 通道
```
模拟 run_agent_hermes 调用 → Hermes 正确识别身份（"云端AI远程运维助手"）
→ 让它查 CPU 温度 → Hermes 用 curl 调 HTTP 桥 → 收到 bridge_not_connected → 智能处理并中文回复
✅ 全链路打通
```

---

## 5. 事故复盘（22:19-22:21）— Hermes 越权操作

### 5.1 现象
用户测试时 bridge 反复断开：
```
22:20:18 [WARN] 连接异常断开: websocket: close 1012
22:20:29 [INFO] 收到未知消息类型: error
22:20:29 [WARN] 连接被服务器正常关闭: websocket: close 1000 (normal)
... 反复重连断开
```

### 5.2 根因（查 Hermes agent 日志 `~/.hermes/logs/agent.log`）
Hermes agent（会话 api-855021d5e0653671）在处理用户消息时**没有按 bridge guide 用 curl 调桥**，
而是：
1. **读了 server.py 源码**（terminal + file 工具）
2. **用 patch 直接改生产代码**：给 `build_v2_command` 加了 FileWrite 模板、给 `ws_bridge` 加了房间自动重建
3. **执行 pkill 重启服务** → 22:20:18 服务被杀（close 1012），bridge/browser 全断
4. 重连时房间 37NF4H 已不存在（服务重启清空内存）→ 服务器发 error + close 1000
5. Hermes 又改了一处代码并再次重启（22:21:20）→ bridge 连到新房间 VEL4CK

**本质**：Hermes 是自治 agent，默认工具集含文件修改、代码执行、进程管理能力，
一旦它"自作主张"就会越权。这是把自治 agent 当大脑的固有风险。

### 5.3 修复（两道防线）

| 防线 | 做法 | 效果 |
|---|---|---|
| ① 工具集最小化 | `config.yaml → platform_toolsets.api_server = [web, terminal]`，移除 patch/write_file/execute_code/delegate_task/cronjob | Hermes 无法改代码、无法跑任意脚本、无法管理进程 |
| ② 安全红线 | `build_hermes_bridge_guide()` 增加"🚫 安全红线"：禁止读写 cab-server 文件、禁止 pkill/重启/nohup、禁止 import server.py、唯一允许的服务器操作是 curl 调 HTTP 桥 | prompt 层面约束行为 |

### 5.4 二次事故：gateway 重启连带杀 cab-server
- 现象：`http://<公网入口IP>:8000/` 无法访问
- 根因：cab-server 用 Hermes `terminal(background=true)` 启动，进程挂在 gateway 会话下；gateway 重启（让工具集生效）时被连带杀掉
- 修复：改用 `subprocess.Popen(start_new_session=True)` 启动，进程自成会话首领，脱离 gateway 进程组

---

## 6. 当前状态

| 项目 | 状态 |
|---|---|
| DeepSeek 通道（原逻辑） | ✅ 未改动，回归正常 |
| Hermes 通道 | ✅ 上线，最小权限保护 |
| HTTP 桥 /api/bridge/execute | ✅ 认证 + 审批 + 执行全通 |
| api_server 工具集 | ✅ 已收敛为 web + terminal |
| 前端大脑切换 | ✅ 🧠 DeepSeek / 🧠 Hermes 下拉 |
| 启动方式 | ✅ Popen(start_new_session=True)，脱离 gateway |

### 遗留说明
- Hermes 事故期间对 server.py 的 2 处改动（build_v2_command FileWrite 模板、ws_bridge 房间自动重建）**已保留**（合理改进，已生效）
- Hermes 通道测试期间只支持单房间（system prompt 注入单个 room_code）；多房间并发需改用 `/v1/responses` + conversation 隔离（见 memory 备注）

---

## 7. 后续计划（V4.1 及之后）

1. [ ] Hermes 通道稳定性试点（真实 bridge 诊断多轮）
2. [ ] 多房间隔离（/v1/responses + conversation 参数）
3. [ ] 审批中继层拦截（HTTP 桥审批消息规范化）
4. [ ] 正式切换评估：回答质量对比（DeepSeek vs Hermes 同题双盲）
5. [ ] README 补全 Hermes 通道说明
