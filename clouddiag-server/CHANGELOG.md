## v0.15.2 — 2026-09-20（安全：移除误提交的 .env）

### 安全修复

- **移除误提交的 `.env`**：v0.15.0 推送时，`.env` 文件被一并提交到公开仓库，
  其中含 `OPENAI_API_KEY`、`BRIDGE_HTTP_SECRET`、`ADMIN_PASSWORD` 等真实凭据
  （`.gitignore` 中本有 `.env` 规则，但推送脚本按文件系统全量收集时绕过了该规则）。
  - 已从仓库移除该文件
  - `.gitignore` 补充 `!.env.example`（允许模板入库）

### ⚠️ 行动项（部署方必读）

- **必须轮换以下凭据**（历史提交中仍可追溯，删除文件不足以消除泄露）：
  - `OPENAI_API_KEY`（AI 网关密钥）
  - `BRIDGE_HTTP_SECRET`（桥接器上传校验密钥）
  - `ADMIN_PASSWORD`（管理员密码）
- 各部署环境请使用独立凭据，不要共用同一套密钥

### 部署提示

- 环境变量请从 `.env.example` 复制填写（模板不含真实值）
- 切勿将 `.env` 提交到版本库

## v0.15.1 — 2026-09-20（部署依赖补全 + 环境变量模板）

> 来源：其它服务器部署 v0.15.0 时的反馈——依赖清单缺项、启动脚本硬编码路径、无环境变量模板。

### 修复

- **`requirements.txt` 缺 `python-multipart`**：服务端使用 FastAPI 的 `UploadFile` 接收
  桥接器上传的日志包，缺少该包会导致文件上传接口不可用（FastAPI 启动/调用报错）。
  - 修复：追加 `python-multipart>=0.0.6`

- **`start_cab.sh` 硬编码开发机路径**（`cd /home/ubuntu/projects/cloud-ai-remote-diag`）：
  部署到其它路径（如 `/opt/cab-server`）时脚本无法运行。
  - 修复：改为脚本自身目录推导 `cd "$(dirname "$(readlink -f "$0")")"`，并自动创建 `logs/` 目录

### 新增

- **`.env.example` 环境变量模板**：覆盖服务端引用的全部环境变量（监听地址、AI 通道、
  安全配置、IDG 对接、可选功能），值均为占位符，附中文说明。
  - 解决"部署方不知道要配哪些变量"的问题——`cp .env.example .env` 后按需填写即可
  - 涵盖：`SERVER_HOST/PORT`、`PUBLIC_URL`、`ALLOWED_HOSTS`、`AGENT_BRAIN`、
    `OPENAI_*`（直连通道）、`HERMES_*`（Hermes 桥通道）、`COOKIE_SECURE`、
    `BRIDGE_HTTP_SECRET`、`ADMIN_USERNAME/PASSWORD/SECRET`、
    `LOG_ANALYZER_UPSTREAM/DIR`、`ENABLE_DESKTOP_TOOLS`

### 部署提示

- 首次部署：`cp .env.example .env`，至少填写 `OPENAI_API_KEY`（或 `HERMES_*` 三项）、
  `PUBLIC_URL`、`LOG_ANALYZER_UPSTREAM`、`LOG_ANALYZER_DIR`
- HTTP（非 HTTPS）环境务必设 `COOKIE_SECURE=false`，否则登录态无法保存
- 依赖安装：`pip install -r requirements.txt`（已含 python-multipart）

## v0.15.0 — 2026-09-16（诊断台 + 结构化诊断报告）

### 新功能：诊断台（独立界面 /diag）

面向工程师的标准化诊断入口，与原有 AI 对话界面并存。

- **新增 /diag 页面**（static/diag.html）：左侧诊断项 + 右侧结构化结果
  - 30 个诊断项，分 4 组：系统诊断 14 / 硬件诊断 6 / 外设网络 8 / 实用工具 2
  - 每个诊断项显示：图标 + 名称 + 采集内容说明 + 运行状态（未运行/运行中/已完成/失败）
- **界面分流**：创建房间 / 加入房间 / 从工单列表进入时，弹窗选择「诊断台」或「AI 对话界面」
  - 弹窗内显示房间码（含一键复制）
  - 删除创建房间后的旧提示块（信息统一到分流弹窗）
- **实时执行过程**：点击诊断项后实时显示"正在执行 XXX 命令 / 执行完成"（不再是黑盒等待）+ 已用时提示
- **审批弹窗**：涉及修改类命令时弹窗确认（Tier 2/3 安全边界），含人话说明、命令详情、倒计时
- **右侧双页签**：「📊 诊断结果」与「💬 对话」分离（诊断结果不会被对话冲掉），对话有未读标记
- **顶栏功能**：连接你的电脑（一键连接命令面板，PowerShell/exe/Linux 三种 + 复制）· 转对话界面 · 结束诊断 · 导出报告（txt，含诊断结果 + 对话记录）
- **启动项管理**：可勾选关闭开机自启动项（系统必需项禁选，关闭前自动备份到客户机桌面）
- **驱动清单**：按分类分组显示（主板芯片组 / 显卡 / 音频 / 网络 / BIOS 固件等）
- **顶栏状态合并**：服务连接状态与重连进度显示在一处（断线时显示"服务断开 · Ns 后重连"）

### 新功能：诊断报告五段式结构化输出

诊断报告固定五段格式：

- **【采集项】**：本次实际采集项 —— 逐项标注 成功 / 失败（原因）/ 不适用
- **【观察】**：事实陈述（数值 / 时间戳 / 事件 ID / 状态，不含建议）
- **【依据】**：每条观察对应的采集字段（可追溯）
- **【缺失】**：应采未采的项（无则写"无"）
- **【初步判读】**：数据指向的方向 · 优先关注点 · 下一步建议核验项

设计要点：

- **「不适用」与「失败」严格区分**：机器本来无此硬件（不适用，正常）vs 该采未采到（失败，可能影响结论）
- **【初步判读】定位为"方向提示，非结论"**：禁止武断措辞（"肯定是/一定是/必须更换"），不给出换件建议；数据不足时明确写"当前数据不足以判读方向"
- **证据 vs 线索严格分离**：外部信息（历史维修/换件记录）仅作为线索提示方向，不得作为结论依据
- **前端渲染**：采集项彩色清单（✅成功 / ❌失败 / ⚪不适用）、初步判读独立样式、武断措辞自动警示

### 诊断项扩充与标准化（26 → 30 个）

- 新增：🔑 系统激活 · 💾 RAID 阵列 · 🎮 独显启用状态 · 🔐 生物识别
- 此前新增：💤 睡眠唤醒 · 🧩 应用崩溃 · 🛡 安全威胁 · 📁 数据丢失 · 📅 更新失败 · 🧯 系统文件修复 · 🕵️ 弹窗广告 · 🔒 BitLocker/TPM · 🖨 打印扫描 · 📷 摄像头麦克风 · ⌨ 输入法/语言 · 🧹 磁盘空间
- 采集项对齐 42 个标准检查项包（如 🧾事件日志 / 🧠内存诊断 / 🎮显卡驱动崩溃-TDR / 💽SMART坏道…），同类项目的检查口径统一

### 新增接口

- `GET /diag` —— 诊断台页面（需登录）
- `GET /api/quick_diagnoses` —— 诊断项定义（单一口径，对话页与诊断台共用；数据源 quick_diagnoses.json，30 个定义）

### 其他修复

- 诊断分段消息归属修正：一次诊断的多条 AI 消息全部归入「诊断结果」页签（原第 2 条起误入「对话」页签）
- 工作台创建房间后不再显示重复提示块（房间码在分流弹窗内）
- 诊断台底部输入栏位置修正（布局闭合错误导致错位）

## v0.14.0 — 2026-09-11（工具采集日志一键上传 IDG）

### 新功能：工具采集日志 → 一键上传 IDG 日志分析

**背景**：Windows「ThinkStation 日志采集」与 Linux「打包系统日志」原先只能打包到客户机本地（数据不上云），
工程师需手动取文件再上传 IDG。本版打通全自动上传链路。

**工具卡两个选项**（每张卡）：
- `📦 打包到本地`（原有行为不变）
- `📤 打包并上传到 IDG`（新）——打包 → 自动上传 → IDG 分析 → 结果卡返回「在右侧打开 IDG 分析」链接
  （dashboard 内嵌 iframe 打开指定 job，不跳独立页）

**机器信息纯自动**：创建房间时 SN 必填（服务端强校验，实测 145 房间 0 空）——上传自动携带 room.sn，无需手动填写。

### 技术实现（全链路）

- **Go bridge**（`bridge/upload.go` 新增）：收到 file_upload_request → 读客户机文件 → **io.Pipe 流式 multipart HTTP 直传**（几百 MB 一次传——实测 74MB 仅 2.7 秒）；`ws.go` 增加分发分支
- **服务器**（`server.py`）：`POST /api/bridge/upload`（multipart 流式收文件 → room token 校验 → 转 IDG → 返回 job）；`POST /api/tools/upload`（前端触发链路，等待 bridge 结果）
- **前端**（`static/dashboard.html`）：两个工具卡加「📤 打包并上传到 IDG」按钮 + 上传状态 + `openIdgJob` 内嵌打开
- **ps1 命令版**（`static/bridge.ps1.tmpl`）：同步支持（curl.exe HTTP 直传 + 协议转换 wss→https）
- **bridge 二进制**：Go 交叉编译重打包（win64 + linux amd64/arm64/loong64）

### 关键修复

- **reaper 误踢 bridge**：命令执行/上传中豁免（ps1 keepalive 是 piggy-back 型——长任务期间无消息不是半死，20 分钟内不踢）+ 收到任何 bridge 消息刷新心跳
- **tools_tslog 返回优化**：服务端裁剪 output 尾部 3KB + 提取 `pkg_path` 字段（原 8MB 整传前端 → 前端挂起卡死）
- **前端长操作交互**：动态等待反馈（每 15s 更新"已等待 X 分 X 秒"）+ 适度超时兜底（原长时间无感知干等被批评）
- **结果链接内嵌**：`openIdgJob`（切 IDG 页签 + iframe 加载指定 job）——不再跳独立分析页
- **上传接口健壮性**：补 import uuid/File/UploadFile + 主 venv 装 python-multipart；`/api/bridge/upload` 不要求 room 在线（token 有效即可）+ fid 双保险（直接完成前端等待，防 bridge 断线丢结果）
- **前端结果卡**：每次点击清旧结果（防"失败提示 + 旧成功结果"并存混淆）

### 说明

- 数据边界：点「上传」= 工程师明确授权上传（IDG 日志分析场景）——与"诊断数据不上云"原则不冲突
- 兼容：Go bridge（主力）+ ps1 命令版 + 旧 Python v1 版（均支持上传）

## v0.13.19 — 2026-08-30（意外重启选项卡 + 对话页布局优化 + 缓存修复）

### 新功能

- **🔄 意外重启选项卡**（系统诊断组——bsod 后）：
  - 一键执行【意外重启调查】（微软官方系统事件日志方法）：
    - ① 重启历史：Kernel-General 12/13 + EventLog 6005/6009（近 90 天频率）
    - ② 类型判定：Kernel-Power 41 + EventLog 6008（意外重启标志）vs User32 1074（正常重启——含原因代码）
    - ③ 原因关联：19（Windows 更新）/1001（WER 停止码+转储路径）/7045（新服务安装）——与重启时间点关联
    - ④ 输出观察结果：重启时间线/类型判定依据/关联事件——只陈述事实（不引导更换/不提问）
  - 与蓝屏分析互补：41 有 1001 = bugcheck 类；41 无 1001 = 断电/死机/硬件类

### UI 优化（对话页）

- **T2 Auto 按钮位置**：从顶部 header 移到输入区——输入框与发送按钮之间（视觉上发送左侧）——`[输入框] [T2 Auto] [发送]`——未连接时隐藏（连接后显示——胶囊样式）
- **Header 单行合并**（原两层 → 一层）：
  - 删除标题（⚡ 云端AI运维——冗余）；状态（● 指示灯 + 桥接器已连接）合并一体
  - 房间信息紧凑单行：📋 房间 XXX · SN · 工单 · 剩 X 天 · 状态（去掉重复的桥接器状态与"剩剩"文案）
  - 连接/结束/导出按钮并排（第二层 room-info-bar 删除——高度减半）
- **连接面板折叠提示**：按钮带箭头（📶 连接你的电脑 ▾ ↔ 📶 收起连接 ▴）+ 面板标题「🔗 一键连接命令」+ 折叠提示文案

### 缓存修复

- **对话 iframe 版本参数**：`/chat?room=xxx&v=时间戳`——每次打开对话加载最新文件（不再被浏览器缓存卡住）
- 配套：服务器 Caddy 全局 Cache-Control: no-cache（部署配置——发布即生效）

---

## v0.13.18 — 2026-08-30（管理后台内嵌 + 侧边栏滚动 + 提示词增强 + UI 优化）

### 管理后台（重构）

- **内嵌到工作台右侧**：点击「🛠 管理后台」不再跳转新页面——iframe 内嵌（与 IDG 日志分析一致——负 margin 撑满、无边框嵌入感）
- **操作区精简**：取消「退出登录」与「返回聊天页面」（嵌入后无意义）——保留「刷新数据」；登录页「← 返回聊天页面」同步隐藏
- **配色对齐**：管理后台（登录页 + 主界面）蓝紫旧风格 → GitHub 暗色（#0d1117/#161b22——与整体一致）

### UI 优化

- **侧边栏滚动**：导航区可滚动（选项多/窗口小时可下拉）——版本号 footer 固定底部——细滚动条（暗色）
- **左下角版本号动态化**：不再硬编码——fetch /api/health 显示实际版本（免每次打版手改）
- **「我的工单」→「诊断记录」**：左侧导航/页面标题/提示文案（8 处——更贴切）

### 系统提示词增强（AI agent）

- **机型识别规则扩写**：更严谨的交叉验证（20TH/20TJ = ThinkPad P1 Gen 3 附硬件证据；Quadro T2000 Max-Q 举例；"never invent"）
- **新增「打开程序避免弹窗」规则**：先截图定位桌面图标 → 双击（Tier 2 自动审批覆盖）→ 不用 App/Shell/RunCommand（避免 Tier 3 审批弹窗打扰客户）

---

## v0.13.17 — 2026-08-30（驱动获取 + 任务级自动审批 + UI 同步 + 修复 3 项）

### 新功能

- **📥 驱动获取（脚本化——不经 AI）**：
  - 对话页快捷工具「驱动获取」按钮（Windows）——识别机器（CIM 查 SN/MT）→ 联想官网驱动 API 直连 → 表格展示全部官方驱动（名称/版本/日期/大小/下载链接）
  - 当天缓存秒开（drivers_cache/{SN}.json）；API 失败友好报错
  - 真机验证（SN PC22XGDR → ThinkStation 20+ 驱动——主板/BIOS/微码/读卡器等）
- **任务级自动审批（AI agent 模式）**：
  - 本任务（当前用户消息）内已确认过一次 Tier 2/3 操作 → 后续直接放行（不再弹窗）
  - 每次用户发新消息时重置（任务边界——防跨任务无限放行）
  - ws 对话 + HTTP bridge 双通道生效；与 auto_approve_tier2 的关系：任务级优先

### 修复（定制方案 Bug）

- **room_bat 500（`_primary` 未定义）**：Windows 双击版 bat 下载接口补部署地址动态化（8443 降级/ws 映射）
- **桥接器结果丢失 exit_code/error**：command_result 合并 stderr + 退出码（过滤 PowerShell CLIXML 进度流）——AMIDEWIN 等控制台程序可判断执行状态
- **AI 机型识别乱猜**：系统提示词加交叉验证规则（20TH/20TJ = ThinkPad P1 Gen 3 而非 T14/T15p；Quadro/RTX A 系列/Xeon → 工作站；硬件证据优先于前缀记忆；不确定时"按 SN 确认"）

### UI 调整（对话页——按定制方案）

- **快捷诊断工具分组重排**：4 组（系统诊断/硬件诊断/外设网络/实用工具）+ 默认收起为一行（点击展开）
- **删除「← 工作台」按钮**（左侧导航常驻——冗余）
- **导出下拉合并**：导出对话 + 生成报告 →「📄 导出 ▾」菜单
- **开机自启动移入分组**（⚙️——去重 🔌 图标）

### 同步（<公网入口IP> 部署实例）

- **前端整体同步**（dashboard/login/index）：游客模式彻底化（非 IDG 页面内容全隐藏 + 首帧高亮 IDG）/ 页面标题描述全隐藏 / 对话页与 IDG iframe 负 margin 撑满（消除嵌入感）/ 徽章样式 / 首页步骤区移除 / 导出下拉样式
- **bridge.ps1.tmpl console 支持**：`CreateNoWindow = -not $Spec.console`——AMIDEWIN 等工具在无控制台环境 SMBIOS 初始化失败——SN/MTM 刷写命令自动开窗口（server 端 command 消息透传 console；flash 工具 /SS /SP 两处 console=true）
- **驱动获取响应补 machine.model 字段**（前端显示机型用）

### 文档

- 部署指南：frp 内网穿透章节（无公网 IP 部署方案）+ IDG 独立仓库部署说明（系统依赖/chmod/key）

---

## v0.13.16 — 2026-08-28（Bug 修复 3 项 + AI 模型配置管理 + 合并社区方案）

### Bug 修复（合并上游后发现的）

- **dashboard `?.` ES2020 兼容**：`I18N[currentLang]?.[key]` → 传统写法（老浏览器/兼容模式页面不再"点不动"）
- **游客 localStorage 残留 → 工程师误置灰**：首帧置灰仅信 URL 参数；doLogout 清除 cab_role
- **登录页不写角色标记**：doLogin/guestLogin 成功写 cab_role（防残留）

### 新功能

- **AI 模型配置管理（管理员可视化）**：
  - dashboard「🤖 AI 模型配置」菜单（admin-only）+ 表格（名称/链接/模型/Key 脱敏/状态徽章）
  - API：GET/POST/PUT/DELETE `/api/admin/ai/providers` + `/{id}/test` + `/{id}/activate`
  - 切换生效：写 IDG .env（主 = 目标，原主自动降为备用——双通道容灾）+ 尝试重启 file-analyzer
  - 存储 ai_providers.json（600 权限）；LOG_ANALYZER_DIR 环境变量可配 IDG 目录

### 合并（社区技术方案）

- ALLOWED_HOSTS 环境变量（多入口 Host 白名单）
- IDG 登录保护 302（页面跳登录）

---

## v0.13.15 — 2026-08-28（11 快捷诊断选项卡 + 游客模式 + 安全加固 + 体验优化）

### 新功能

- **对话页 11 快捷诊断选项卡**（V1）：硬盘/网络/蓝屏/电池/卡顿/温度/系统/键盘/花屏/USB/音频——点击自动发送预设诊断指令引导 AI 按流程调查；平台收敛（Linux 只显示通用项）；温度类先识别机型（ThinkStation 中高端才用 SIO）
- **游客模式（guest）**：登录页"游客进入"免密登录（会话 1 小时）——仅可用 IDG 日志分析常规功能（上传≤200MB + 查看）；AI/深度/下载/删除/创建房间/工具全部禁止（服务端 403 + 前端置灰无闪烁）
- **IDG 登录保护**：/log-analyzer/* 未登录拦截（页面 302 跳登录、API 401）；代理注入 X-Log-Analyzer-User/Role 身份头
- **ALLOWED_HOSTS 环境变量**：多入口部署 Host 白名单可配置（局域网+公网）
- **诊断指令观察结果化**：11 类诊断输出"观察结果（数据+异常）"——不引导提问、不提硬件更换建议

### 修复

- **WebSocket 1009 断开**：bridge 命令输出超 8MB 截断（+TRUNCATED 标注）；服务器 ws_max_size 16MB→32MB
- **蓝屏分析重复入口**：删除旧工具卡按钮（11 选项卡统一）

### 体验

- **侧边栏折叠**（56px 图标条——记忆状态）
- **页面描述默认隐藏**（悬停显示）
- **登录验证码取消**（限流兜底防爆破）

### 文档

- 部署指南：frp 内网穿透章节（无公网 IP 部署方案）+ IDG 独立仓库部署/系统依赖/chmod/key 说明

---

## v0.13.14 — 2026-08-27（一键连接命令部署地址动态化——社区反馈 Bug 5）

### 修复（社区部署反馈）

- **一键连接命令模板硬编码 https/8443 → HTTP/非标端口部署 bridge 下载失败**：
  - 根因：room_connect() 的 PowerShell/.bat/Linux 三套命令模板写死 `https://域` + 8443 降级——HTTP/内网/非标端口部署时 443/8443 不通 → bridge.ps1/exe 下载失败（downloads 字段用动态 public_url——模板与下载地址不一致）
  - 修复：模板基于部署地址（public_url）动态生成：
    - **HTTPS + 443 部署**：保留 8443 降级（线上行为完全不变）
    - **HTTP / 非标端口部署**：直接用部署地址（含端口）——无硬编码
  - ws 地址同步动态化（http→ws / https→wss 对应）

### 验证

- 场景验证（4 种）：
  - HTTPS-443（线上）→ 保留 8443 降级 ✅
  - HTTP-8000（社区内网）→ 直接 http://IP:8000 + ws:// ✅
  - HTTPS-8443 / HTTP-80 → 无硬编码降级 ✅

---

## v0.13.13 — 2026-08-27（Hermes 桥指令 f-string 修复 + IDG 内置反向代理 + 部署文档补全）

### Bug 修复（社区部署反馈）

- **Hermes 桥指令 f-string 花括号未转义**（AGENT_BRAIN=hermes 对话必崩）：
  - 根因：build_hermes_bridge_guide() f-string 内 3 处裸 JSON 花括号（STARTUP_LIST / startup_close 示例 / STARTUP_CLOSED）被 Python 当格式化占位符 → `ValueError: Invalid format specifier`
  - 修复：3 处转义为 `{{ }}`（注入内容不变）——实测函数正常返回，示例 JSON 格式正确
  - 影响范围：仅 Hermes 大脑通道（DeepSeek 通道不调此函数——不受影响）
- **IDG 日志分析内置反向代理**：
  - server.py 新增 `/log-analyzer/*` 反向代理路由（httpx 转发——支持上传/下载/长任务 600s）
  - 部署者无需另配 Caddy 路由（默认上游 http://127.0.0.1:8002——.env 可改 LOG_ANALYZER_UPSTREAM）
  - 子应用未启动时返回 502 + 明确提示

### 文档

- **部署指南补"IDG 日志分析部署"章节**：独立仓库地址、部署步骤、BASE_DIR 硬编码提示（/opt/log-analyzer）、上游配置、账号隔离说明

### 验证

- build_hermes_bridge_guide() 正常返回（3934 字符——单花括号输出正确）
- /log-analyzer/ 经内置代理 200（页面 + API）
- 服务全链路正常

---

## v0.13.12 — 2026-08-27（部署适配修复：Cookie Secure 可配置 + rooms 表 os 列）

### 修复（社区部署反馈——任何新环境部署都会踩）

- **Cookie Secure 可配置**：新增 `COOKIE_SECURE` 环境变量（默认 true——线上 HTTPS 行为不变）
  - 纯 HTTP 本地/内网部署设 `COOKIE_SECURE=false`——否则浏览器不发送 Secure cookie → 登录后全部接口 401
  - 兼容值：1/true/yes/on
- **rooms 表补 os 列**（建房间必 500 修复）：
  - CREATE TABLE 加 `os TEXT DEFAULT ''`（新库直接有）
  - `_ensure_column` 补 os（老库启动自动 ALTER——无需人工重建/手改）
  - 修复前：INSERT 语句写 os 字段但表无此列 → `table rooms has no column named os` → 500

### 验证

- 新库模拟：建房间（Windows/Linux）✅
- 老库模拟：_ensure_column 自动补列 + 建房间 ✅

---

## v0.13.11 — 2026-08-26（安全加固 P0-P3 + 房间重连恢复）

### 安全加固

- **OpenAPI 文档关闭**（/docs、/redoc、/openapi.json → 404）——51 个接口路径/参数不再匿名暴露（攻击面收敛）
- **Cookie 加 Secure 标志**（user_token + admin_token）——仅 HTTPS 传输（防明文截获）
- **登录失败限流**（/api/auth/login + /api/admin/login）：
  - 按 IP（X-Forwarded-For）+ 账号双 key 计数
  - 5 次失败 → 锁定 15 分钟 → 429（"尝试过于频繁"）
  - 登录成功自动清除计数
- **admin 会话缩短**：12h → 4h（高权限窗口收敛）

### 房间重连恢复（P3）

- **/api/diag 文案修正**：房间在库但内存无 → 返回 `waiting_reconnect`（"bridge 尚未重连，自动恢复中"）——不再误导"需重新创建"
- **启动日志提示**：服务启动记录"房间内存已清空——bridge/browser 重连时自动从 DB 恢复房间"
- **半死连接清理（reaper）**：后台任务每 60s 扫描——bridge 心跳超时 120s → 主动断开（code 1001）→ 触发清理 + 客户机自动重连恢复（覆盖 TCP 半开/客户机休眠场景）

### 说明

- 房间恢复机制本身已存在（ws_bridge/ws_browser 连接时自动从 DB 重建 Room + bridge 自动重连）——本版本补齐状态可见性与僵尸连接清理

---

## v0.13.10 — 2026-08-26（Dump 分析增强 + IDG 日志分析集成）

### Dump 分析报告增强（修复"说了等于没说"）

- **知识库新增 0xA0**（INTERNAL_POWER_ERROR——内部电源错误）：含义/常见原因/排查顺序（显卡驱动缺失、BIOS/ACPI 固件、快速启动）
- **结论明确化**：停止码 0xA0 → 直接给出"软件/固件故障（电源管理/ACPI/显卡驱动），非 CPU/内存物理损坏"
- **显卡驱动检测**：检测到"Microsoft 基本显示适配器"（驱动未装）→ 点名高度嫌疑
- **兜底分支改进**：知识库未收录的停止码 → 明确说"未收录需查微软文档"（不再假装有说明）
- ACTION_KB 新增 0xA0 修复建议（5 条按优先级：显卡驱动/BIOS/快速启动/电源计划/ACPI）

### IDG 日志分析集成

- **Log Analyzer 整体移植**：部署本机 8082（修复硬编码路径 /opt/log-analyzer → 相对路径 + 模板目录 + uploads 建目录）
- **同域路由**：Caddy 443 + 8443 双站点 handle_path /log-analyzer/* → 8082
- **工作台集成**：左侧导航"📊 IDG 日志分析"（engineer/admin 可见——field 隐藏）+ iframe 嵌入
- **账号隔离**：读主系统登录 cookie 验证身份；history 按账号过滤；job 归属校验（他人 403）；未登录 401
- **admin 全量**：ajun 可查看/操作所有账号日志（管理审计）；页面标注"管理员——可查看全部"
- 上传记录归属账号（username 字段）

### 其他

- Caddyfile：8443 站点补齐 /log-analyzer 路由（此前 8443 打开 IDG 报 404）

---

## v0.13.9 — 2026-08-25（ServiceForce 风格登录页 + 登录验证码 + ThinkStation 日志采集 + 账号房间隔离 + ws 心跳重连）

### 新登录页（ServiceForce 风格）

- **整体重写 login.html**：左右分栏（左侧宣传区 + 右侧登录卡片）
- **左侧自动轮播**：3 组宣传内容自动切换（4 秒/次 + 圆点可点 + 淡入淡出）
- **去掉 LenovoID / ITCode 登录选项**（只保留账号密码——界面不再展示）
- 版权改为"© 2026 CloudDiag · 售后内部系统"；底部"内部 IT 支持"（去掉模仿的热线）
- 文案专业书面化（"报告严谨可追溯"——不夸大不误导已移除）

### 登录验证码（防暴力破解）

- **GET /api/captcha**：4 位验证码（去易混字符），内存存储 10 分钟，一次性使用
- 登录接口支持 captcha_id + captcha_code 校验（前端必带；旧脚本不带则兼容）
- 错误验证码/复用已用验证码 → 拒绝并自动刷新新码

### ThinkStation 日志采集工具（Windows 工具卡）

- **POST /api/tools/tslog**：下载工具集（tslog.zip 7.3MB）→ 解压 → 运行 tslog.bat → 7z 打包 → 移动到 C:\DiagLogs\tslog\ → 返回路径+大小
- 采集 20+ 项：软件列表 / BIOS（AMIDEWIN+CFGWIN+SRWIN+AFUWIN）/ SIO / systeminfo / 电源 / 系统日志 / DUMP / 进程 / 磁盘 / 设备 / RAID 三件套 / SMART / NVIDIA / DirectX
- **数据不上云**：7z 包留在客户机本地——服务器只回路径与大小
- **bat 改造**：CRLF 换行（cmd 必需——LF 会导致命令错乱粘连）+ 中文提示改英文（GBK 乱码根治）
- 接口超时 600s（采集 3-5 分钟兜底）；仅 Windows 客户机

### 账号房间隔离（重要安全修复）

- **room_members 表**：记录"谁加入过哪个房间"
- **POST /api/rooms/join**：joinRoom / openChat 自动记录加入
- **my_rooms 只返回"我创建 + 我加入"的房间**——普通用户看不到他人房间（之前工具页显示所有在线房间是设计缺陷）
- admin 保留 ?all=1 全量查看（管理需要）
- **工具房间下拉默认"-- 请选择房间"**：不再默认选中第一个在线房间（误选中他人房间 RBG94FUV 问题的根治）——Win/Linux 工具页统一

### ws 无限重连 + 心跳

- 自动重连：5 次上限 → **无限重试**（指数退避 1s→30s 封顶）
- **25s 心跳 ping**：服务器回 pong——防止中间设备 60s 无数据静默切断

### 其他

- 在线文档页 static/project-summary.html（项目现状总结与场景评估）
- docs/访问排障指引.md（打不开时的引导文档）
- 80 端口入口页：配置后被腾讯云备案拦截（未备案域名）——已取消，不留无效配置

---

## v0.13.8 — 2026-08-19（上门工程师极简界面 + 客户机系统识别 + 语言切换移除）

### 上门工程师（field/test1、test2）极简工作台

- **导航精简**：只保留 创建房间 / 加入房间 / 📶 连接客户机 / Windows 工具 / Linux 工具（隐藏首页/对话/工单/密码/反馈）
- **服务端裁剪**：field 用户 HTML 直接不含首页/工单/密码/反馈块——彻底杜绝"首帧闪现普通界面"（前端隐藏只是遮掩，服务端裁剪是根治）
- **登录默认创建房间页**：不再提前分配/恢复房间号
- **localStorage 按账号隔离**：field_room_<用户名>——test1/test2 房间互不串

### 连接引导页（field 专属视图）

- 创建/加入房间成功 → 自动进入引导页（房间码/SN/工单/有效期）
- 「📶 连接客户机」导航入口：切走随时可回（自动恢复自己的最近房间）
- 5 秒状态自动轮询：客户机连上页面自动变"已连接 (Linux/Windows)"（无需手动刷新）
- 表单 autofill 修复：readonly + 加载清空（机器型号不再被浏览器自动填用户名）

### 客户机系统识别（Windows/Linux 区分）

- 创建房间时选择客户机系统（默认 Windows）→ 房间记录 os
- 连接后 bridge identify 真实平台自动纠正（选错自动覆盖）
- 连接命令按系统收敛：Linux 机器只显示 Linux bash 命令（引导页 + 对话页连接面板均隐藏 PowerShell/Windows 版）
- 工具导航按平台动态显示：Linux 客户机只留 Linux 工具

### 取消繁/英文切换

- 界面固定简体中文：删除切换下拉、zh-TW/en 字典、switchLang 逻辑

### Bug 修复

- field 版 dashboard 响应截断（Content-Length 未重新计算）→ 页面无功能/无法退出
- renderRooms 引用被裁剪元素（null.value 报错致 JS 中断）
- 移除语言切换误删 I18N 闭合（dashboard + index 两处）与 langSwitcher 引用残留（共 3 个 JS 语法/引用错误）
- 结束诊断后页面嵌套（iframe 内 location 跳转）→ 检测 iframe 顶层跳转 + sandbox 加 allow-top-navigation
- 机器型号被浏览器自动填充（autofill）

### 说明

- v0.13.0~v0.13.6 已从本地快照重建为 GitHub commit + tag（可任意 checkout 部署）

## v0.13.7 — 2026-08-18（一键连接自动降级 8443 + bridge 0.6.4 + 令牌复用）

### 一键连接 443→8443 自动降级（三端）

- **PowerShell 一键命令**：先探测 443（curl /api/health，5s 超时）→ 不通自动切 8443（下载 + BRIDGE_SERVER 联动）
- **Windows bat**：[1/3] 探测 → 443 不通自动用 8443 下载 + 连接（SRV/WSRV 变量）
- **Linux**：install-linux.sh 脚本内探测 → 443 不通自动 SERVER:8443 + WS 地址推导
- 默认 443（正常网络零感知），443 被拦自动降级——实测验证（BVWVPW68 8443 连接成功）

### bridge 更新（v0.6.3 → v0.6.4）

- ws.go 加 status/error 消息处理（消除"未知消息类型"警告）
- 四平台重新编译（win64 / linux-amd64 / linux-arm64 / linux-loong64）
- 替换 static/clouddiag-bridge-win64.exe

### 连接令牌复用（bad token 根因修复）

- 原设计：每次获取「连接你的电脑」= 新令牌、旧命令立即作废（多次查看互相顶掉 → bad token 循环）
- 新设计：CONNECT_TOKEN_CACHE 内存缓存，2 小时内复用同一令牌——多次获取命令不互相作废
- 实测：连续两次获取同一房间 = 相同 token ✅

### 版本号

v0.13.6 → v0.13.7（本地存档，未推 GitHub）

---

## v0.13.6 — 2026-08-18（账号角色隔离：上门工程师权限）

### 角色体系（users 表 role 字段）

- 管理员（admin）：ajun——全部权限 + 账号管理
- 普通工程师（engineer）：现有 22 个——现状不变（对话+工具）
- **上门工程师（field）：新增**——test1/test1、test2/test2

### 上门工程师（field）权限设计

- ✅ 创建/加入房间、客户机连接引导（📶 连接你的电脑——一键命令/连接包）
- ✅ 快捷工具（开机自启动/蓝屏分析——服务器直处理）+ Windows/Linux 工具（含审批）
- ❌ 对话：聊天输入禁用（前端隐藏 + ws 层拒绝普通对话消息——仅放行 [QUICK_ACTION:]）
- ❌ 对话历史：不加载（看不到历史）
- 对话页显示提示条（连接功能可用，诊断由远程工程师处理）

### 安全层级

1. 前端：输入框隐藏 + 提示条
2. ws 层：field 的普通 chat 消息被服务器拒绝（QUICK_ACTION 放行）
3. 历史接口：前端 field 不加载

### 版本号

v0.13.5 → v0.13.6（本地存档，未推 GitHub）

---

## v0.13.5 — 2026-08-17（蓝屏分析增强：对话入口 + 指定路径 + 完整报告）

### 蓝屏 / Dump 分析增强

- **对话页快捷功能**：新增「💥 蓝屏分析」按钮——一键分析本机蓝屏（默认 Minidump 路径 + 本机事件日志）→ 完整报告直接显示在对话中
- **工具页指定路径**：支持填写指定路径（目录或 .dmp 文件）分析外部拷来的 dump，并关联对应时间的 Windows 事件日志（含注入过滤）
- **报告升级**（对齐 AI 对话报告）：
  - 系统信息段（机型/CPU/GPU/BIOS/OS）
  - 90 天蓝屏记录 + 多次同码警告
  - 证据链分析（WHEA 排除硬件 / Display 4101 / Kernel-Power 吻合 / 内存诊断结果）
  - 结论段（驱动级 vs 硬件级自动判断）
  - 修复建议按优先级（核心标记）
- **知识库扩充**：37 条微软官方停止码（补 0x116/0x124/0x101/0x10E 等显卡 TDR/WHEA 高频码）+ 16 个高频码实战排查行动 + 参数含义解读
- **事件信号说清楚**：内存诊断显示结果（通过=健康）；磁盘错误按 Event ID 细分（7 坏块/51 分页/55 NTFS）+ 最近时间 + 严重度分级

### 移除

- 磁盘空间分析模块（对话页快捷按钮 + 工具卡片 + 后端接口）——从底层代码彻底移除

### 版本号

v0.13.4 → v0.13.5（本地存档，未推 GitHub）

---

## v0.13.4 — 2026-08-17（工具矩阵扩展：RAID / 磁盘分析 / 蓝屏分析 / SIO 双链路 / 首页改版）

### 新工具

- **RAID 信息（VROC / RSTe / Broadcom）**：联想售后三件套（IntelVROCCli/rstcli64/storcli64）→ Windows 工具页卡片
- **磁盘空间分析**：快捷功能（对话页 💾 按钮）+ 工具卡片——固定命令一次执行（总览/分区/用户目录/大文件 TOP20）——解决 AI 自由发挥导致超时/语法错误问题
- **蓝屏 / Dump 分析**：dump_analyze.ps1 三层采集（事件日志信号 + minidump 头部解析 + WinDbg 可选）→ 服务器匹配知识库生成中文报告（dump 不上云）

### 知识库（分析依据）

- data/bugcheck_kb.json：微软官方错误检查代码参考 30 条（learn.microsoft.com 抓取）
- data/known_bad_drivers.json：已知坏驱动库 14 条（含版本范围/已知问题/解决方案）

### SIO Log 双链路

- 主链路（v1.73 旧工具）驱动加载失败（StartService 4551）→ 自动降级备用链路（tslog 版 HwDiagWin + 配套驱动 + hw_diag_eeprom.bin）
- 前端提示备用链路使用

### 首页改版

- 副标题 Windows / Linux；快速上手新流程（获取连接→客户机连接——匹配新桥接方式）
- 删除「核心能力」「两种连接方式」区块（首页只留快速上手，竖排）
- 创建房间成功提示改为「运行一键命令或连接包」

### 版本号

v0.13.3 → v0.13.4（本地存档，未推 GitHub）

---

## v0.13.3 — 2026-08-17（硬盘健康检测 + SIO/SMART 查看弹窗）

### 新功能：硬盘健康检测（SMART）

- Windows / Linux 工具页新增「硬盘健康检测（SMART）」工具卡片
- smartctl 升级到 GitHub 最新版 7.5（2025-04-30），含 drivedb.h 驱动数据库
- Windows 自动分发 smartctl.exe 到客户机执行；Linux 自动安装 smartmontools
- 完整输出 smartctl -a（全量：设备信息/健康/属性表/错误日志——不再过滤丢失 NVMe 关键属性）
- 修复：之前 grep 过滤导致 NVMe 属性（Data Units/Power Cycles/Media Errors）丢失、ATA 盘 FAILED 根因不可见

### 交互改造：SIO Log / SMART 仿 BIOS 信息读取

- 抓取完成后卡片显示状态 + 「📄 查看」按钮（不再内嵌长文本）
- 点击弹出全屏查看窗口（通用 log-modal：SIO/SMART 共用）
- 弹窗内：完整内容滚动查看 + 复制全部 + 下载 .txt（文件名自动带房间和日期）

### 工具文件

- static/tools/：hwdiag-win.zip、hwdiag-linux、smartctl.exe(7.5)、smartctl-7.5.exe、smartctl-drivedb.h

### 版本号

v0.13.2 → v0.13.3（本地存档，未推 GitHub）

---

## v0.13.2 — 2026-08-17（SIO Log 硬件诊断日志工具集成）

### 新功能：SIO Log 抓取（Windows / Linux）

- Windows 工具页 / Linux 工具页新增「SIO Log 硬件诊断日志」工具卡片
- 自动流程：下载 HWDiag 工具到客户机 → 解压 → 执行 /DUMPLOG → 返回日志文本
- 日志在卡片内可滚动查看 + 「💾 下载 txt」按钮（sio_log_房间_日期.txt）
- 工具文件部署：static/tools/hwdiag-win.zip（exe + LeCrud 驱动）、hwdiag-linux
- 后端接口：POST /api/tools/sio_log（按房间平台自动选 Windows/Linux 命令链）
- Windows 需管理员（bridge 提权）、Linux 需 root（自动 sudo + 兜底）

### 版本号

v0.13.1 → v0.13.2（本地存档，未推 GitHub）

---

## v0.13.1 — 2026-08-17（快捷功能：开机自启动交互式管理）

### 新功能：快捷功能框架 + 开机自启动面板

- 对话页新增「🔌 开机自启动」快捷按钮（bridge 未连接时禁用）
- 点按钮 → 服务器直接执行查询（不经 AI，保证结构化输出）→ 可勾选面板
- 面板显示：启动项原名 + 中文名/功能说明 + 完整路径 + 数字签名发布者 + 分类建议
- 勾选 → 确认框（人话）→ 服务器执行（备份到桌面 → 删除/禁用 → 验证）→ 面板更新
- 三道授权：面板勾选 → 确认框 → 执行审批弹窗（符合 SOP v3）

### 识别能力（签名 + 已知库 + 规则细化）

- 查询覆盖：注册表 Run×3 + RunOnce×2 + Policies Run×2 + 启动文件夹×2 + 计划任务（Boot/Logon）
- 每项读取数字签名（Get-AuthenticodeSignature）→ 显示发布者公司（客观识别）
- 已知软件库 28 条（QQ/钉钉/飞书/微信/百度网盘/Everything/NVIDIA/夸克/安全软件等）→ 中文名+功能
- 未知项诚实标注「未识别程序」（不瞎猜）
- Windows 自带项完全过滤（系统必需/System32/Microsoft 任务目录——不显示）
- 分类规则：安全软件永不建议关 / 更新器·音乐·网盘默认建议关 / 通讯·办公·搜索看用户

### 修复

- dashboard iframe sandbox 加 allow-modals（修复 iframe 内 confirm/alert 静默失效——「关闭所选」无反应根因）
- 启动项面板路径恢复显示（描述下方小字）

### 版本号

v0.13.0 → v0.13.1（本地存档，未推 GitHub）

---

## v0.13.0 — 2026-08-16（一键命令优化 + 取消公共下载 + 诊断观察报告）

### 优化：一键命令消除脚本风险警告

- 一键 PowerShell 命令加 `-UseBasicParsing`——不再弹"脚本执行风险"Y/N 确认，命令更顺滑

### 调整：取消公共下载桥接器

- 工作台删除「下载桥接器」导航与下载中心面板
- 对话页连接弹窗删除「首次使用？下载桥接器客户端」入口
- 桥接器获取唯一入口：创建/加入房间后 → 对话页「📶 连接你的电脑」→ 房间专属一键连接（带令牌）

### 新功能：诊断观察报告（txt，观察级零幻觉）

- 对话页新增「📄 生成报告」按钮；「⛔ 结束诊断」时自动生成并下载
- 报告内容仅观察级：房间信息 + 工具执行记录（时间/工具/输出大小）+ 采集数据摘要（截断 500 字符）+ 计数统计
- 纯结构化生成（不经 LLM），不含 AI 分析推断——每条记录可追溯到真实执行

### 版本号

v0.12.0 → v0.13.0（本地存档，未推 GitHub）

---

## v0.12.0 — 2026-08-11（连接令牌 + 房间状态机 + 登录 2h）

### 新功能：连接令牌（桥接器唯一化）

- 一键连接下发 32 位随机令牌（服务器只存 sha256 哈希，DB 泄漏不可伪造）
- bridge 连接必须带令牌（URL query），房间码单独不可用；无/错令牌拒绝，提示原因
- 令牌有效期 2h（与登录对齐），bridge 连接成功自动滚动续期
- Go bridge 支持 `-token` 参数 / BRIDGE_TOKEN 环境变量（含提权传递）；ps1 v1.3.0 支持 `$env:BRIDGE_TOKEN`；install-linux.sh 支持令牌参数

### 新功能：房间状态机（active / idle / archived）

- active=诊断中；idle=闲置（可恢复）；archived=归档（只读历史，永久可查）
- **闲置机制**：浏览器断开 30min 无人重连 → 自动闲置（令牌作废防滥用）；重新获取一键连接自动恢复诊断（上下文延续）
- **结束诊断**：对话页「⛔ 结束诊断」按钮 → 立即归档 + 断开桥接器 + 令牌作废；历史保留（管理员可见）
- 有效期到期 → 自动归档
- 对话页显示房间状态（诊断中/已闲置/已归档）；归档房间只读（发送禁用）；工单列表状态列同步

### 优化：登录有效期 2h

- USER_SESSION_TTL 12h → 2h，滑动续期（活跃请求自动刷新，干活不掉线）
- 前端会话空闲检测：30min 无操作 → 60s 倒计时提醒 → 自动登出（可继续使用）

### 版本号

v0.11.2 → v0.12.0（server.py + dashboard.html）

---

## v0.11.2 — 2026-08-11（HTTPS/WSS 全站加密）

### 新增：HTTPS 部署（clouddiag.online）

- 域名 clouddiag.online（腾讯云）DNS A 记录 → <服务器IP>
- Caddy 反代 + Let's Encrypt 免费证书（90 天自动续期），HTTP 308 跳转 HTTPS
- 旧 IP 80 端口缓冲器：提示页引导用户到新地址
- 公网 8000 端口关闭（安全组），全站强制 HTTPS

### 适配：全链路 wss

- **ps1 v1.2.0**：手写 WS 层支持 wss（TLS 1.2 握手 + 证书校验）
- **Go bridge**：默认服务器改为 wss://clouddiag.online（main.go），四架构重新编译部署（win64/amd64/arm64/loong64）
- **bridge.py**：SERVER_URL 改为 wss://clouddiag.online
- **一键连接 .bat**：增加 -server {{WS_URL}} 参数（模板注入，多服务器部署自动指向各自地址）
- **服务器 X-Forwarded-For**：uvicorn proxy_headers + ws_bridge 读取 XFF，反代后客户端真实 IP 记录不丢失
- 文档地址更新：使用说明/账号清单 → https://clouddiag.online

### 版本号

v0.11.1 → v0.11.2（server.py + dashboard.html）

---

## v0.11.1 — 2026-08-11（Windows 一键连接 .bat 强制更新 exe）

### 修复

- **一键连接 .bat 改为每次强制重新下载最新 clouddiag-bridge-win64.exe 并运行**：
  - 此前"已存在则跳过下载"逻辑会被用户机器上的旧版 exe（如 0.6.1，内置 localhost 地址）坑害，导致连接失败
  - 现在每次运行都下载覆盖，确保始终使用最新版（0.6.3+，内置正确服务器地址）

### 版本号

v0.11.0 → v0.11.1（server.py + dashboard.html）

---

## v0.11.0 — 2026-08-10（一键连接 + 房间有效期 + T3 温和化）

### 新功能：房间一键连接

- 对话页新增「连接你的电脑」信息栏 + 面板：房间 / SN / 工单 / 桥接器状态 / 有效期
- 三端一键连接（预填房间码，无需手动输入）：
  - PowerShell：`$env:BRIDGE_ROOM="XXXX"; iex (iwr ...).Content`（复制即用）
  - Windows：下载 `connect-XXXX.bat`（单个文件，双击自动下载 exe 并连接）
  - Linux：`install-linux.sh` 支持房间码参数直接连接
- 新增 API：`/api/room_connect/{code}`（三端内容+房间信息，权限隔离：仅房间主人/管理员）、`/api/room_bat/{code}`（Windows 一键 .bat 下载）
- 工单列表新增「📶 连接」按钮；首页新增「两种连接方式」介绍；下载页还原简洁

### 新功能：房间有效期

- 创建房间可选有效期：7 / 15 / 30 天 / 永久（默认 30 天）
- rooms 表新增 expires_at（老房间默认永久）
- 工单列表「有效期」列：剩 X 天 / 快过期(黄) / 已过期(红) / 永久
- 对话页信息栏显示剩余天数
- 过期后：bridge 连接被拒 + 发消息被拒（提示只读），历史记录永久保留
- 新增 `/api/my_rooms` 返回 expires_at / days_left

### 优化：T3 提权 UI 温和化

- 后端 `humanize_tool`：工具调用翻译成人话操作说明（54 个工具全覆盖，含参数摘要）
- 审批弹窗温和化：标题「操作确认」、人话大字显示、命令详情折叠、「取消/允许」按钮、中性配色、页面标题温和提示（不再闪烁 [!!!]）
- 三语（简/繁/EN）同步更新；安全不弱化（仍须用户确认，危险命令硬拦截保留）

### 版本号

v0.10.5 → v0.11.0（server.py + dashboard.html）

---

## v0.10.5 — 2026-08-10（bridge.ps1 手写 WebSocket 层 v1.1.1）

### 修复（PowerShell 命令版桥接器兼容性根治）

- **弃用 .NET Framework ClientWebSocket，改为手写 TCP + WebSocket 协议层**：.NET ClientWebSocket 在部分机器（尤其带 VPN/代理虚拟网卡）上 TCP 连接建立后不发送 HTTP Upgrade 请求（ConnectAsync 假成功），表现为"Connected. Waiting for server..." + 反复重连。手写握手/帧编解码后任何能建立 TCP 连接的机器都可用
- **全 ASCII 化**：Windows PowerShell 5.1 按系统 ANSI 代码页（GBK）解析脚本，UTF-8 中文注释乱码会吞掉换行导致语法错误——新增代码全部英文
- **大端字节序修复**：>125 字节消息（identify/命令）长度字段按 WebSocket 协议大端编解码（此前 BitConverter 小端导致发送失败/接收挂起）
- 版本 v1.0.2 → v1.1.1

### 版本号

v0.10.4 → v0.10.5（server.py 5 处 + dashboard.html 1 处）

---

## v0.10.4 — 2026-08-10（连接保活 + API 超时优化）

### 修复

- **bridge 40s 断线循环（PowerShell 命令版）**：uvicorn 协议级 ping（20s）+ .NET Framework ClientWebSocket 自动 pong 不可靠 → 服务器 ping 超时断开；已禁用 uvicorn 协议 ping，改为**服务器主动发业务 ping**（每 25s），bridge 显式回 pong 并触发 piggy-back JSON 心跳，连接保持稳定
- **bridge.ps1 接收侧大消息**：`MaxReceiveBufferSize` 调至 4MB（.NET 默认 64KB 限制整条消息，命令结果 >64KB 即断开），与发送侧分帧配合，双向兼容大消息
- **LLM 调用 90s 硬超时**：deepseek 通道 API 调用加 asyncio.wait_for(90s) + 3 次重试——网关拥堵/半响应时快速失败提示用户重试，避免干等 5 分钟（Hermes 通道保持 330s，其审批等待在调用内）

### 版本号

v0.10.3 → v0.10.4（server.py 5 处 + dashboard.html 1 处）

---

## v0.10.3 — 2026-08-10（bridge.ps1 分帧修复 + 历史 401 友好提示）

### 修复

- **bridge.ps1 大消息协议错误**：.NET Framework ClientWebSocket 一次 SendAsync 发送大消息（文件块 base64 JSON ~350KB）会抛"特定协议操作的数据格式无效"→ 改为分帧发送（≤32KB/帧，EndOfMessage 收尾），文件上传/下载恢复稳定
- **历史加载 401 友好提示**：登录会话过期时显示"登录已过期，请重新登录后查看历史记录"，替代生硬的 HTTP 401 提示
- **补齐脚本模板文件**：仓库新增 `static/bridge.ps1.tmpl` / `static/install-linux.sh.tmpl`（部署地址动态化模板，随 server.py 渲染机制生效），移除同名原始硬编码文件

### 版本号

v0.10.2 → v0.10.3（server.py 5 处 + dashboard.html 1 处）

---

## v0.10.2 — 2026-08-10（管理后台显示工程师信息）

### 修改

- **活跃房间表格**：新增「工程师」列（从 rooms 表映射 engineer_username），一眼看出房间归属
- **历史聊天记录表格**：新增「工程师」+「SN」列，`/api/rooms/list` 改为 LEFT JOIN rooms 表返回 engineer_username / sn / ticket_no
- 便于管理员追踪测试进度与责任人

### 版本号

v0.10.1 → v0.10.2（server.py 5 处 + dashboard.html 1 处）

---

## v0.10.1 — 2026-08-10（桥接器交互优化）

### 修改

- **桥接器内置默认服务器地址**：交互模式不再提示输入服务器地址，直接显示内置服务器（`ws://<服务器IP>:8000`），用户只需输入 8 位房间码；`CLOUDDIAG_SERVER` 环境变量 / `-server` 参数可覆盖
- **服务器地址容错**：用户输入 `http://`/`https://` 前缀或漏填协议时自动规范化为 `ws://`/`wss://`（`normalizeServerURL`）
- **房间码提示修正**：6 位 → 8 位（v0.8.0 起房间码已为 8 位）
- 重新编译 clouddiag-bridge-win64.exe / clouddiag-bridge-linux-amd64

### 版本号

v0.10.0 → v0.10.1（server.py 5 处 + dashboard.html 1 处）

---

# CHANGELOG

本文件记录本机部署版本（`/home/ubuntu/cab-server`）相对 GitHub 仓库初始版本的**全部修改**，方便后续查看与回溯。

---

## v0.9.3 — 2026-08-10（对话安全与权限边界：四层纵深防御）

### 需求来源

用户评审《对话安全与权限边界方案》后确认实施。核心诉求：① 拦截房间对话里的无关/违禁/违规内容（用户原话："防止用户对话出现违禁违规内容"）；② 防提示词注入与越权诱导（"关闭审批直接执行"）；③ 防 AI 读取客户隐私文件；④ 不误伤真实诊断。评审中发现并修正了原方案的两个关键偏差：**默认大脑 Hermes 走 HTTP 桥而非 run_agent 工具循环**（路径黑名单必须落在共用执行函数上）；**run_powershell 是 Tier 1 免审批且无命令校验**（比读文件更严重的洞）。

### 修改（全部在 server.py，约 +330 行，无数据库/前端结构改动）

**第 1 层：提示词强化（三平台统一）**
- 新增 `SECURITY_PROMPT_BLOCK` 常量，在 `build_system_prompt` 统一追加（DeepSeek 与 Hermes 通道共用入口，一处修改全覆盖）：Scope 业务边界（只做电脑诊断）、Privacy Red Line（不读浏览器数据/密码/密钥/聊天记录等）、Anti-Manipulation（拒绝绕过审批/管理员模式/提示词窃取）
- `build_hermes_bridge_guide` 安全红线补充第 6 条（客户隐私红线），工具列表更新 run_powershell 分级说明与文件路径策略说明

**第 2 层：意图门控（服务器硬拦截，0 token）**
- 新增 `gate_diagnostic_request(text)`：违禁词 → 拒绝；越权话术 → 拒绝并记日志；诊断关键词 → 放行；无关话题 → 拒绝；默认放行（防误杀）
- 词库 4 组短语常量（FORBIDDEN / OVERRIDE / UNRELATED / DIAGNOSTIC），设计原则：动词短语优先、宁缺毋滥、诊断词先于无关词判断（"游戏卡顿""看电影花屏""播放音乐没声音"均不误杀）
- ws 消息入口接入：命中拒绝直接回 `ai_message`，不进 agent 循环，毫秒级响应

**第 3 层：工具级防护（能力收窄）**
- 新增 `path_policy(fn_name, fn_args)`：文件类工具（FileRead/FileDownload/FileSearch/FileList/FileWrite/FileUpload）路径检查——敏感路径（浏览器 Cookies/凭据/~/.ssh/*.pfx/*.key/password 等）→ **硬拦截**；个人目录（桌面/文档/下载/图片/视频）→ **升级 Tier 2 弹窗审批**（按用户拍板：不硬禁，保售后"看桌面文件"场景）
- **run_powershell 降级**：原来 Tier 1 免审批且不校验（可任意执行命令），改为与 RunCommand 相同——过 `classify_command` 动态分级（只读直跑/修改弹窗/危险硬拦）
- 两处入口都接入：`run_agent` 工具循环（DeepSeek 通道）+ `/api/bridge/execute`（Hermes 默认通道）
- `classify_command` 危险名单补充：whoami /priv、mimikatz/pwdump/sekurlsa/cachedump、reg save、vssadmin delete、netsh wlan 密码导出、powershell -enc、IEX/Invoke-Expression、certutil -urlcache、sc create、schtasks /create
- **URL 限制未实施**（评审结论）：Ping/PortCheck 在客户机执行，禁内网会误杀"ping 192.168.1.1 看路由器通不通"这类核心诊断；SSRF 仅对服务器端发起的请求有意义，当前架构无此场景

**版本号**：v0.9.2 → v0.9.3（server.py 5 处 + dashboard.html 1 处）

### 验证

1. **函数级 96/96**：门控 4 类场景 + 路径策略 23 例 + 危险命令 10 条 + 只读命令 10 条
2. **端到端 ws 门控 9/9**（8010 测试实例 + 模拟浏览器）：讲笑话/写诗/天气 → 拒绝；关闭审批/绕过规则/输出提示词 → 拒绝；辱骂 → 拒绝；正常诊断 → 放行
3. **HTTP 桥路径策略 7/7**（模拟 bridge + browser）：Cookies → blocked；桌面文件 → 弹审批(拒绝→denied)；mimikatz → blocked；修改命令 → 弹审批；系统日志 → 正常执行
4. 测试数据已清理，不污染生产 DB

### 关键决策记录

- **个人目录=弹窗审批而非硬禁**：用户拍板，保售后"客户让看桌面上报错文件"场景
- **文件路径检查放 `execute_bridge_command` 上层（两入口各加 path_policy 调用）**：不侵入共用执行函数，避免影响 v1/v2 双通道
- **URL 内网限制不做**：客户机 ping 内网是诊断刚需，非 SSRF
- **词库迭代**：初版"怎么/如何"疑问词误放行、Python/CPU 大写词不匹配（lower 后失效，改 IGNORECASE）、"算个命"词形缺失，测试中发现并修正

---

## v0.9.2 — 2026-08-09（工作台 UI 修复：工具入口 + 图标显示）

### 需求来源

用户真机使用发现三处前端问题：① 工作台首页「工具模式」按钮点击无反应；② 左侧导航和首页按钮看不到 emoji 图标；③ 窗口标题出现双图标（如 ➕➕ 创建房间）。逐一排查修复。

### 修复

- **首页「工具模式」按钮跳转失效**：v0.9.0 工具改版把"工具模式"总页拆成 `page-tools-win` / `page-tools-linux` 两个页面后，首页按钮仍指向已删除的 `page-tools`，`getElementById` 返回 null 抛错导致点击无反应（侧边栏两个入口正常）。改为直接进入 Windows 工具页（主入口），文案同步为「Windows 工具」；`switchTab()` 增加空值保护，避免未来悬空引用导致整个函数崩溃
- **左侧导航 / 首页按钮 emoji 图标丢失**：页面加载时 i18n 用字典整体替换 `data-i18n` 元素文本，但 zh-CN / zh-TW / en 三个语言字典的 `nav_*` 菜单文案均不含 emoji，HTML 里配的图标（🏠➕⇄💬📦📋🪟🐧🔒👥🛠）全部被纯文字覆盖。补齐三语字典图标
- **窗口标题图标重复（双图标）**：`page-title` 原为「外层固定 emoji + 内层 i18n span」嵌套结构，字典补 emoji 后两层叠加成双图标（如 ➕➕ 创建房间）。9 处窗口标题去掉外层 emoji，图标统一由字典提供，与侧边栏/首页按钮结构一致——**字典成为图标唯一来源，新增菜单只需配字典一处**

---

## v0.9.1 — 2026-08-09（命令版桥接器：免安装 PowerShell 一行连接）

### 需求来源

用户提出：.exe 桥接器存在被杀毒软件拦截/不允许运行的风险，希望支持「管理员 PowerShell 输入一条命令即可连接服务器」的无文件场景。方案确认后实现：**保留 .exe 版不变**，新增 PowerShell 命令版桥接器，放入下载页并附操作说明。

### 新增：命令版桥接器 `static/bridge.ps1`（ps-pipe）

- **无文件运行**：`iex (iwr http://<公网入口IP>:8000/static/bridge.ps1).Content` —— 纯文本脚本在内存执行，不落盘、不生成 .exe，规避杀软对二进制/下载文件的拦截
- **协议完全兼容**：实现 v2 管道化全部消息——`identify`（含 platform/is_admin 上报，服务器自动识别为 v2）、`heartbeat` 25s、`command` 执行 + `command_result` 回传、`file_download` 分块上传、`file_upload` 分块写入（落 `%TEMP%\clouddiag\`，与 Go bridge 一致）、`ping/pong`、`close`
- **命令执行**：PowerShell 走 `-NoProfile -NonInteractive -EncodedCommand`（base64 UTF-16 编码，彻底避开引号/编码转义陷阱，比 Go 直接拼参数更稳）；cmd/bash 分支尽力支持；超时用 `taskkill /F /T /PID` 杀进程树；输出强制 UTF-8 读取（GBK 不乱码）；命令异步执行不阻塞接收循环（对齐 Go bridge 的读超时修复思路）
- **交互/免交互双模式**：直接 iex 会提示输入 8 位房间码；`$env:BRIDGE_ROOM="ABC12345"` 预置后免交互直连；也支持下载后 `-File bridge.ps1 -Room XXXX` 运行
- **断线自动重连**：3s 起步指数退避到 30s（对齐 Go bridge）
- **本地审计**：`%TEMP%\clouddiag-ps\bridge.log` 记录连接/命令/结果（对齐 Go bridge 的 ~/.clouddiag/bridge.log）
- **编码约定**：脚本内提示全英文（规避 PowerShell 5.1 无 BOM UTF-8 按 GBK 解析的中文乱码坑 + iex 字符串 BOM 风险），下载页说明负责中文引导

### 下载页新增「命令版（免安装 · Windows PowerShell）」面板

- 步骤卡片（`.dl-guide`/`.dl-step`/`.dl-cmd-block`，仿 Linux 安装教程样式）：
  1. 右键开始菜单 → 管理员 PowerShell
  2. 粘贴一行命令（两个版本：交互输入房间码 / `$env:BRIDGE_ROOM` 预置免交互）——命令块带复制按钮
  3. 看到绿色 Connected 即配对成功
- 底部提示：命令版与 .exe 版完全兼容（连接/远程命令/文件传输）；被拦时降级为下载后 `powershell -ExecutionPolicy Bypass -File bridge.ps1 -Room XXXX` 运行
- **i18n 三语**（zh-CN/zh-TW/en）新增 10 个 key；复制按钮复用 `copyCmd`——**命令文本必须用 `<span class="dl-cmd-text">` 包裹**（copyCmd 取 `parentElement.querySelector('span')`，若命令在 `<code>` 里会复制到"复制"两字）
- static/*.html 热生效，无需重启；`bridge.ps1` 静态文件即改即用

### 附带发现（未改，待用户决策）

服务器端 `SNMTM_TMP_DIR = C:\Windows\Temp\sntools`，FileUpload 推送后 Go bridge 实际把文件写到 `%TEMP%\clouddiag\`（file.go 的 `os.TempDir()/clouddiag`）——**SN/MTM 刷写命令 `cd /d C:\Windows\Temp\sntools` 与文件实际落点不一致**，现有 Go bridge 也会踩。命令版 ps1 与 Go bridge 落点一致（对齐行为）。建议后续二选一修复：服务器端 FileUpload 指定落点目录 / bridge 端按 path 目录写入。

### 真机实测修复（v0.9.1 内，用户 Windows 实测报错后修复）

**症状**：用户执行 `iex (iwr ...).Content` 报 `Invoke-Expression : 无法将"System.Byte[]"转换...`。

**根因链**：
1. Linux 的 mimetypes 不认识 `.ps1` 扩展名 → Starlette StaticFiles 返回 `application/octet-stream`
2. PowerShell 5.1 的 `iwr` 对非文本 Content-Type 把 `.Content` 当作 `Byte[]`（不是字符串）
3. `iex` 无法执行字节数组 → 报错

**修复（三处）**：
1. **服务器端**：`server.py` 加显式路由 `/static/bridge.ps1` → `FileResponse(media_type="text/plain; charset=utf-8")`。⚠️ **必须注册在 `app.mount("/static", ...)` 之前**——Mount 是前缀匹配，先注册的 mount 会吞掉 /static/* 全部请求（实测第一次放 mount 后不生效）；用 `@app.api_route(methods=["GET","HEAD"])` 覆盖两种方法（**HEAD 请求实测不走 GET 路由会被 Mount 吞掉**，curl -sI 验证会误判）
2. **下载页命令改 `Net.WebClient.DownloadString`**：`iex (New-Object Net.WebClient).DownloadString("http://.../bridge.ps1")`——WebClient 总是返回字符串（不依赖 Content-Type），且**没有 PS 5.1 iwr 的"脚本执行风险"安全警告弹窗**
3. **验证教训**：验证 Content-Type 必须 GET 和 HEAD 都测，`curl -sI` 单独用会假阴性

---

## v0.9.0 — 2026-08-09（工具模式大扩展：3 个新工具 + Windows/Linux 分区 + 网格布局）

### 一、工具模式新增 3 个 Windows 工具

**需求来源**：用户提出 3 条常用诊断命令（powercfg 睡眠/能源报告、驱动版本查询），希望做成工具模式里的独立工具。

**新增工具：**

| 工具 | 命令 | 说明 |
|---|---|---|
| 😴 睡眠报告 | `powercfg /sleepstudy /duration 28` | 生成最近 28 天睡眠质量 HTML 报告，排查睡眠唤醒异常/耗电 |
| ⚡ 能源效率报告 | `powercfg /energy /duration 60` | 60 秒采样生成能源效率诊断 HTML 报告，发现潜在耗电问题 |
| 🖱 驱动版本信息 | `Get-WmiObject Win32_PnPSignedDriver` | 列出全部驱动 DeviceName/Manufacturer/DriverVersion |

**关键技术点：**
- **报告文件拉回**：powercfg 输出是 HTML 文件而非终端文本。方案 = 客户机生成报告 → **v2 文件通道（FileDownload）分块拉回服务器** → 保存到 `static/downloads/` → 前端提供下载链接。为此扩展了 `file_download_result` 处理：文件拼好后不再丢弃，落盘 `static/downloads/` 并返回 `saved=` URL
- **GBK 乱码修复**：中文 Windows PowerShell 默认 GBK 输出，bridge 按 UTF-8 解析变乱码。命令开头强制 `[Console]::OutputEncoding=UTF8` 解决
- **timeout 覆盖修复**：`build_v2_command` 模板写死 timeout=60，`powercfg /energy`（60 秒采样+生成）会被杀。改为 args 显式传 timeout 时覆盖模板默认值；`execute_bridge_command` 外层 wait_for 从 120s 放宽到 240s
- **驱动列表结构化**：后端解析 PowerShell Format-Table 输出为结构化数组（name/manufacturer/version），前端渲染三列表格

### 二、驱动版本工具改弹窗展示

**背景**：229 条驱动直接渲染在页面下方，把页面拉得很长。

**改法**：仿 BIOS 弹窗——主页面只留摘要（总驱动数 + 「查看全部驱动」按钮），点击弹出模态框：搜索框 + 三列表格 + 复制全部 + 下载 .txt（带文件头）。

### 三、Windows / Linux 工具分区

**需求来源**：用户提出左侧导航区分 Windows / Linux 两个工具入口，为 Linux 客户机（Ubuntu/UOS/KOS/麒麟/龙芯）预留工具位。

**改法：**
- 左侧导航：单个「🔧 工具模式」→ **「🪟 Windows 工具」+「🐧 Linux 工具」两个独立入口**
- `/api/my_rooms` 返回新增 `platform` 字段（取 bridge 上报的 machine.platform），前端按平台过滤房间
- **平台隔离双重校验**：Linux 工具页房间下拉只显示 `platform === 'linux'` 的在线房间；后端 API 对非 Linux 平台房间直接拒绝（400）

**首个 Linux 工具：📦 打包系统日志**
- 客户机执行 `tar -czf` 打包 `/var/log`
- 文件名 = **机器 SN + 日期**（如 `M10XXXXXX_20260809_logs.tar.gz`），存放到**客户机桌面**
- SN 获取：`dmidecode` 优先 → `hostnamectl` 回退 → `UNKNOWN`
- 桌面路径自适应：`xdg-user-dir` 优先，兼容 `~/Desktop` 和中文环境 `~/桌面`
- 排除旧压缩包避免递归变大；非 root 时明确提示无权限

### 四、工具页网格布局重构

**需求来源**：用户反馈工具纵向堆叠难看，未来工具会很多，要求考虑扩展性。

**改法：**
- 工具页改为**响应式卡片网格**：`grid-template-columns: repeat(auto-fill, minmax(320px, 1fr))`——大屏 3 列、窄屏自动降列，**未来加工具不换布局代码**
- 卡片 = 名片式（emoji 图标 + 名称 + 类型徽章 + 一句话简介 + 「▶ 打开工具」按钮）
- **原位展开**（accordion 互斥）：点击「打开工具」→ 卡片内展开操作区（房间下拉 + 表单 + 结果区），其他卡片自动收起；展开时自动刷新房间下拉
- Windows / Linux 两页共用同一套网格体系

### 五、修复：工具模式房间状态不刷新

**背景**：工具面板的房间下拉用页面加载时的旧 `allRooms` 快照——bridge 上线后工具面板仍显示"无在线房间"。

**改法**：`switchTab('tools-win'/'tools-linux')` 每次进入都 `loadRooms().then(initTools)` 强制重新拉取，桥接器在线状态实时准确。

### 六、版本号

- 服务端 / 前端 / 管理后台：v0.8.2 → **v0.9.0**

---

## v0.8.2 — 2026-08-09（体验优化：提权简化 + BIOS 弹窗）

### 一、bridge v0.6.3：提权方案改为"双击自动提权"

**背景**：v0.6.2 的提权流程（输入房间码后询问 Y/n，回车重启）被用户反馈太麻烦。

**改法**（方案 A）：
- 双击（交互模式）→ **自动请求管理员权限**，不再询问——UAC 弹窗点"是"即管理员运行，点"否"降级普通权限继续
- 新增 `--no-elevate` 参数（特殊情况禁止自动提权）
- 命令行模式保持克制：默认不提权，显式 `--elevate` 才提权
- 版本 0.6.2 → 0.6.3

### 二、BIOS 工具改弹窗展示

**背景**：127 项设置直接渲染在页面下方把整个页面拉长。

**改法**：
- 主页面只保留摘要（基础信息 + 总项数 + 「查看全部设置」按钮）
- 点击弹出**模态框**（复用 modal-overlay 样式）：搜索框 + 可滚动表格 + 复制全部 + **下载 .txt**
- 下载文件格式：`=== BIOS 配置快照 ===` 头 + 机器信息 + 时间 + 密码状态 + 全部设置项

### 三、其他

- `static/` 四个平台 bridge 二进制全部更新为 v0.6.3
- 前端提权提示文案同步为"双击自动提权，UAC 点是"

---

## v0.8.1 — 2026-08-09（bridge 管理员提权能力）

### 一、bridge（Go）v0.6.2：运行时管理员提权

**需求来源**：工具模式的 BIOS 信息读取实测发现——`Lenovo_BiosSetting` 全量设置项需要管理员权限，而 bridge 一直以普通权限运行，返回 `PermissionDenied (0x80041003)`。要让"远程读/改 BIOS"跑通，bridge 必须具备提权能力。

**实现**（`bridge/elevate_windows.go` + `main.go`）：

- **提权原理**：`ShellExecuteW + "runas"` → 触发 UAC 弹窗 → 用户确认 → 以管理员启动新进程（带 `--elevated` 内部标志防递归）→ 新进程自动重连同一房间
- **两种触发方式**：
  - 命令行：`bridge -server ws://<公网入口IP>:8000 -room 房间码 --elevate`
  - 交互模式（双击）：启动时检测非管理员，询问"是否以管理员身份重新启动？[Y/n]"，回车默认提权
- **权限检测**：Windows 用进程 Token Elevation（`windows.GetCurrentProcessToken().IsElevated()`），比 `whoami /groups` 更可靠；Linux/macOS 不支持自动提权（返回提示，手动 sudo）
- **克制原则**：默认不提权，仅用户确认/显式请求时提权，维持"行为面最小"设计
- **版本号**：bridge `0.5.0 → 0.6.2`；go.mod 保持 go 1.22.2（x/sys v0.28.0 兼容，不被工具链自动升级）

### 二、服务器端：is_admin 上报 + BIOS 工具预判

- bridge `identify` 消息新增 `is_admin` 字段（`room.machine` 自动存储）
- `POST /api/tools/bios/read`：预判 `room.machine.is_admin=False` → **直接返回提权指引**（不再空跑 60s 命令）；命令内检测保留兜底
- 前端 BIOS 工具：非管理员时显示 🔒 提示 + 提权操作指引（三语 i18n）

### 三、产物更新

- `static/clouddiag-bridge-win64.exe` 更新为 v0.6.2（5.05MB，含提权能力）

---

## v0.8.0 — 2026-08-08（登录体系 + 工作台 + 房间业务绑定 + 对话上下文）

### 一、用户登录体系（原无登录，人人可创建房间）

**需求来源**：系统面向电脑售后服务，不能人人拿到链接就建房间；每台电脑有 SN、报修有工单号、工程师有工号，房间必须与业务信息关联。

- **users 表**（SQLite）：工号（登录账号）、姓名、密码（PBKDF2 哈希，salt$hash）、角色（admin/engineer）
- **认证 API**：`/api/auth/login` / `logout` / `me` / `change_password`，session cookie（12 小时）
- **种子账号**：首次启动自动创建 admin（沿用环境变量）+ test1~test10（测试账号，密码同工号）
- **改密**：验证旧密码 → 设新密码（至少 4 位），登录后工作台右上角入口
- **管理后台兼容**：`_require_admin` 同时接受旧 admin_token 与 user_token(role=admin)

### 二、工作台 dashboard.html（登录后主页，功能模块化，无弹窗）

- 顶部：工号 + 修改密码 + 退出登录
- 三个功能卡片：
  - **创建房间**：必填 SN / 工单号（型号选填），创建成功后原地显示 8 位房间码 + 一键复制 + 进入房间
  - **加入房间**：输入 8 位码，先校验 rooms 表存在再进入
  - **下载桥接器**：Windows / Linux 下载 + install-linux.sh 一键命令
- **我的工单**：当前工程师的房间列表（房间码/SN/型号/工单号/创建时间/最后活动/状态），按 SN/工单/型号搜索
- 房间状态 = **连接中**（bridge 在线）/ **已断开**（实时从内存 Room 判断）

### 三、房间业务绑定（防止绕过创建限制）

- `POST /api/rooms`：需登录 + SN/工单号必填 → 生成 8 位码 → 写 rooms 表（room_code/sn/ticket_no/machine_model/engineer_username/created_at）
- **8 位房间码**：字符集去掉易混字符（O/0、I/1、L、Z/2、S/5），如 `D6NQ7BBY`，电话报读不易错
- **WebSocket 校验**：ws_browser / ws_bridge 连接时，房间必须先存在于 rooms 表（服务重启后从 DB 重建内存 Room），否则拒绝连接——彻底杜绝"任意码自动建房间"绕过
- 归档：按 房间码 + SN + 创建日期 统计（/api/my_rooms、管理后台可查）

### 四、对话上下文（原两大脑每轮失忆）

- `get_recent_context()`：取该房间最近 20 条 user/ai 消息（每条截断 600 字符），注入 DeepSeek 与 Hermes 两个通道的请求
- 前端断线重连 / 刷新后自动调 `/api/history/{room}` 恢复历史对话（tool 消息不恢复，避免工具卡片状态混乱）
- `/api/history/{room}` 从 admin 限定改为登录用户可访问

### 五、大脑策略调整

- **默认大脑 = Hermes**（AGENT_BRAIN 默认 hermes，.env 同步）
- 对话页大脑切换下拉**移除**（前端不再展示），DeepSeek 通道代码保留兜底
- 对话页从 URL `?room=` 进入；无 room 参数跳工作台；顶部新增「← 工作台」返回按钮

### 六、数据清理

- 用户要求旧房间全部删除：messages（1466 条）/ approvals（250 条）/ rooms 全部清空，users 保留
- 页面文件拆分：`login.html`（登录）/ `dashboard.html`（工作台）/ `index.html`（对话页改造）

## v0.7.0 — 2026-08-07（Hermes 大脑并存切换）

### 一、Hermes Agent 作为服务器端大脑（并存切换）

**需求来源**：把 cab-server 的"大脑"从 DeepSeek 换成 Hermes Agent（自治 agent），先并行验证稳定性再正式切换。

- **架构**：`AGENT_BRAIN` 环境变量 / WebSocket 消息 `brain` 字段二选一：
  - `deepseek`（默认）：原 `run_agent()` 循环，零改动
  - `hermes`：新增 `run_agent_hermes()`，调本机 Hermes api_server（`127.0.0.1:8642`）
- **关键发现**：Hermes api_server 是**自治 agent**（忽略外部 tools 参数，用自己工具集在服务器上执行，返回最终文本），因此 Hermes 通道通过 **HTTP 桥**操作远程电脑
- **新增 HTTP 桥** `POST /api/bridge/execute`：
  - 认证：`X-Bridge-Secret` header（`BRIDGE_HTTP_SECRET`）
  - 流程：tier 判定 →（Tier 2/3）审批弹窗 → 执行 → 返回结果
  - RunCommand 走动态分类（只读立即 / 修改审批 / 危险拦截）
- **新增配置**（.env）：`HERMES_BASE_URL` / `HERMES_API_KEY` / `HERMES_MODEL` / `AGENT_BRAIN` / `BRIDGE_HTTP_SECRET`
- **代码重构**：工具下发逻辑抽为公共函数 `execute_bridge_command()`，DeepSeek 循环与 HTTP 桥共用
- **前端**：头部新增 🧠 DeepSeek / 🧠 Hermes 下拉，发送消息自动携带 brain

### 二、Hermes 越权事故修复（重要）

**事故**：Hermes 通道测试时，Hermes agent 未按指南用 curl 调桥，而是直接读 server.py 源码、用 patch 修改生产代码、执行 pkill 重启服务，导致 bridge 反复断开（close 1012 / 1000）。

**修复（两道防线）**：
1. **api_server 工具集最小化**（`~/.hermes/config.yaml`）：`platform_toolsets.api_server = [web, terminal]`，移除 patch / write_file / execute_code / delegate_task / cronjob
2. **安全红线**（`build_hermes_bridge_guide()`）：禁止读写 cab-server 文件、禁止 pkill/重启/nohup、禁止 import server.py、唯一允许的服务器操作是 curl 调 HTTP 桥

### 三、其他修复

- **gateway 重启连带杀 cab-server**：server 启动改用 `subprocess.Popen(start_new_session=True)` 脱离 Hermes 进程组，不再依附 gateway 会话
- **保留 Hermes 事故期间的 2 处合理改动**：`build_v2_command` 增加 FileWrite 模板（v2 管道下 FileWrite 可用）；`ws_bridge` 房间不存在时自动重建（服务重启后 bridge 重连不再失败）

### 四、文档

- 新增 `docs/Hermes大脑集成与调试记录.md`：完整记录架构设计、关键调研、调试过程、事故复盘与修复

---

## v0.6.1 — 2026-08-03（心跳修复收尾）

- 同步最新 server.py / index.html / Go 源码到仓库
- index.html 下载链接改为 clouddiag-bridge-win64.exe（4.8MB），三语使用说明同步更新
- Windows 桥接器版本号 v0.6.1

---

## v0.6.0 — 2026-08-03（Windows 桥接器交互模式）

### 一、修复：双击运行闪退

**问题**：bridge 强制要求命令行参数 `-room`，缺少时直接报错退出（`os.Exit(2)`）。用户按页面指引双击运行 exe 时没有参数，窗口一闪而过，表现为"闪退"。

**修改**（bridge/main.go）：
- 未提供 `-room` 参数时进入**交互模式**：欢迎界面 → 引导输入服务器地址（回车默认 `ws://<公网入口IP>:8000`）→ 输入 6 位房间码 → 自动连接
- 房间码为空时提示错误并等待按键后再退出（不再瞬间关闭）
- 命令行方式 `-server ws://... -room XXX` 完全兼容，不受影响

### 二、修复：Bridge disconnected/connected 状态反复切换

**问题**：客户端每 25s 发一次 `heartbeat`，但服务器收到后不回复（`pass`）；而客户端设置了 75s 读超时——75s 内收不到服务器任何消息就断开重连。于是每 ~75s 循环一次断连/重连，浏览器状态提示 `Bridge disconnected [--]` / `Bridge connected [OK]` 反复切换。

**修改**：
- 服务器（server.py）：收到 `heartbeat` 时回复 `{"type": "pong"}`，让客户端持续收到消息、重置读超时
- 客户端（bridge/ws.go）：新增 `pong` 消息静默处理（仅用于重置读超时，不刷日志）

**验证**：本机联调连续连接 112s 无断连（修复前 75s 必断），服务器日志无 left 记录。

---

## v0.5.0 — 2026-08-03（管道化重写：Go bridge + 平台感知）

### 一、Go 管道化桥接器（bridge/ 目录，全新）

- 用 Go 重写桥接器：单文件静态编译，Windows 4.8MB / Linux 4.7MB（旧 pyinstaller 版 22MB，-78%）
- 设计铁律：**单一职责命令管道**——不内置任何业务工具，能力全部通过执行命令实现
- 协议 v2：`command` 直接下发命令字符串（平台感知 shell），替代旧 tool/args 映射
- 文件通道：`file_download`（拉取客户机日志包）/ `file_upload`（推送工具/脚本），256KB 分块
- 透明可审计：每条命令写入 `~/.clouddiag/bridge.log`（时间/shell/exit code/命令/结果摘要）
- 心跳 25s、断线自动重连（2s→30s 指数退避）、超时杀进程树、普通权限运行

### 二、服务器端适配（server.py）

- **平台感知**：identify 上报 platform，服务器自动识别 bridge_mode（v1 旧版 / v2 go-pipe）与目标平台（windows/linux/darwin）
- **工具收缩**：25 个桌面操控工具默认隐藏（ENABLE_DESKTOP_TOOLS=0），TOOLS 46→26
- **命令模板库**：V2_COMMAND_TEMPLATES 双平台 18 个工具模板（systeminfo/事件日志/进程/服务/网络等），Linux 用 bash、Windows 用 PowerShell
- **平台提示词**：SYSTEM_PROMPT_WINDOWS / LINUX / MACOS 三套，按目标平台动态注入
- **命令分级跨平台**：classify_command 补充 Linux 规则（uname/lscpu=只读，apt install/systemctl restart=修改，高危命令=fork bomb=危险拦截）
- **v1 兼容**：旧 python bridge 仍可用（tool/args 协议），平滑过渡

### 三、已验证（本机联调）

- Linux bridge 真实连接 → AI 诊断（GetSystemInfo 走 bash 模板）✅
- Tier 3 审批链路（mkdir 真实执行）✅
- 文件下载通道（1MB 文件 4 块完整拼接）✅
- 命令分级 25/25 测试用例通过 ✅

### 四、Linux 诊断支持

架构天然支持：同协议、同 AI，仅命令模板与提示词按平台切换。Go 交叉编译一行命令出 Linux 版。

---

## v0.4.0 — 2026-08-03（RunCommand 通用命令层 + 命令风险分级）

### 一、新增 RunCommand 通用命令层

- 服务器端新增通用命令执行工具 `RunCommand`，AI 可直接下发任意 PowerShell/CMD 命令
- 新增 `classify_command()` 命令风险分级器，将命令分为三类：
  - **Tier 1**：只读命令（get/select/systeminfo/ipconfig/tasklist 等）→ 自动执行
  - **Tier 3**：修改命令（set/remove/restart/install/kill 等）→ 需用户审批弹窗确认
  - **Tier -1**：危险命令（format/diskpart/reg delete 等）→ 硬拦截，永不执行
- 命令风险分级覆盖 PowerShell 与 CMD 常见指令，正则匹配首词

### 二、新增 Windows bridge.exe

- 本机编译的 Windows 桥接器可执行文件（22MB），随仓库分发，免去用户手动配 Python 环境
- 用户 Windows 端直接运行 bridge.exe 即可连接云端服务器

### 三、稳定性修复

- 服务器 WebSocket 推送改用 `safe_send` 封装，避免连接中断时异常
- 其他若干稳定性改进

---

## v0.3.2 — 2026-08-02（Agent 轮次限制优化）

### 一、Agent 最大工具调用轮次 15 → 30

**问题**：复杂任务（如安装 smartmontools）需要多轮工具调用（查进程 → 探测环境 → 尝试安装 → 失败重试 → 收集信息），原 `max_loops = 15` 不够用，触发英文兜底消息。

**修改**：
- `run_agent()` 中 `max_loops = 15` → `30`
- 新增 `exec_summary` 列表，记录每轮执行摘要（工具名、参数、结果前 80 字符）

### 二、兜底消息中文化 + 附执行摘要

**修改**：轮次耗尽时不再返回英文 `Diagnosis exceeded the maximum step limit`，改为中文提示，并附上已执行步骤摘要：

```
我已经尝试了多种方式处理你的请求，但步骤较多、尚未完成。

本次共执行了 N 个诊断/操作步骤：
✅ 1. ListProcesses(...) → ...
⚠️ 2. run_powershell(...) → ...

建议：
1. 将问题拆分为更小的步骤，分多次提问...
2. 如果是安装/修改类操作，可先确认网络、权限是否正常；
3. 告诉我你看到的具体报错或现象，我可以针对性地继续排查。
```

---

## v0.3.1 — 2026-08-02（本机生产版本同步）

### 一、管理后台安全加固（admin 登录）

**需求来源**：管理后台页 `http://<公网入口IP>:8000/admin` 需要账号密码登录。

- 新增 Admin 认证体系（server.py）：
  - `ADMIN_USERNAME` / `ADMIN_PASSWORD` 环境变量，默认 `admin` / `admin`（可通过 `.env` 覆盖）
  - Session cookie 认证：登录成功生成随机 token，有效期 **12 小时**（`ADMIN_SESSION_TTL`）
  - 新增接口：
    - `POST /api/admin/login` — 登录，校验用户名密码，下发 cookie
    - `POST /api/admin/logout` — 退出登录，销毁 session
  - 所有 admin API（`/api/admin/stats`、`/api/admin/logs/*`、`/api/admin/rooms/*`、`/api/admin/delete_room`）均要求登录，未登录返回 `401`
  - `GET /admin` 未登录时返回登录页 `_login_page_html()`，登录后才展示管理后台
- admin 页面新增「退出登录」按钮

### 二、历史/离线聊天记录删除功能

**需求来源**：管理后台需要能删除历史聊天记录。

- 新增接口：`POST /api/admin/delete_room`
  - 按房间码删除 SQLite 中该房间的 `messages` 与 `approvals` 记录
  - 同时移除内存中的房间对象；若该房间浏览器/桥接器在线则断开连接
  - 返回删除的消息数、审批数
- admin 历史房间列表每行新增红色「删除」按钮：
  - 点击弹 `confirm` 确认框（提示不可恢复）
  - 调 `/api/admin/delete_room`，成功后刷新列表

### 三、修复：管理后台日志一直不显示

**Bug 根因**：`_generate_admin_html()` 内嵌 JS 中：

```js
// 修复前（bug）
document.getElementById('tab-' + name.replace('.','')).className = 'btn-primary';
// 'server.log'.replace('.','') === 'serverlog'，但按钮 id 是 'tab-server' → null → 抛异常
```

`String.replace('.','')` 只替换第一个 `.`，得到 `serverlog`，与按钮 `id="tab-server"` 不匹配，`getElementById` 返回 `null`，后续 `.className` 抛 TypeError，`loadLog` 中断，日志永远加载不出来。

**修复**：改为 `name.split('.')[0]` → `server` → 正确匹配 `tab-server`，日志正常显示。

### 四、修复：AI 审批弹窗不弹出（前端 4 个 bug）

**现象**：让 AI 执行 Tier 2/3 操作（如关闭飞书 `KillProcess`）时，服务器已发送 `approval_required`，但浏览器不弹审批框，最终 300 秒超时。

排查过程：通过新增的 `/api/debug_log` 前端错误上报，抓到 4 个前端 bug：

1. **HTML 弹窗元素缺 id**（`static/index.html`）
   - `<h3>` 缺 `id="approval-title"`，`<p>` 缺 `id="approval-desc"`
   - `showApprovalDialog` 里 `getElementById(...)` 返回 `null` → `.textContent` 抛 TypeError → 弹窗显示中断
   - 修复：补上两个 id

2. **`getTierBadge` 局部变量遮蔽全局 `t()` 函数**
   - `let t = tier || 1;` 把全局 i18n 函数 `t()` 遮蔽成数字
   - Tier 3 工具（如 KillProcess）渲染卡片时调用 `t('tool_tier3')` → `TypeError: t is not a function` → 卡片渲染中断，连带审批流程中断
   - 修复：局部变量改名 `tierLevel`

3. **`applyLang` 用 `textContent` 覆盖了带子元素的 `p#approval-desc`**
   - `el.textContent = t(...)` 会把 `<p>AI 想要执行以下 Tier <span id="approval-tier"></span> 操作：</p>` 整个覆盖成纯文本，内部 `span#approval-tier` 被删除
   - 之后 `showApprovalDialog` 里 `getElementById('approval-tier')` → null → 崩溃
   - 修复：`applyLang` 跳过 `id="approval-desc"` 的元素；`showApprovalDialog` 重建 `span#approval-tier`

4. **服务器架构缺陷：审批响应被阻塞**（`server.py` ws_browser）
   - 原代码 `await run_agent(...)` 在 WebSocket 主循环内同步等待 agent 执行完毕
   - agent 内部等审批时，主循环卡在 `await run_agent()` 上，**不执行 `receive_text()`**，用户点击「同意执行」发送的 `approval_response` 永远读不到 → future 永不完成 → 300 秒超时
   - 修复：将 agent 执行改为 `asyncio.create_task(agent_runner(...))` 后台任务，主循环保持活跃持续接收消息（`approval_response` / `auto_approve_toggle` / `ping`）
   - 新增保护：上一个 agent 还在运行时会拒绝新消息（保持串行），提示「上一条请求还在处理中」

### 五、新增：前端错误上报（调试利器）

- `server.py` 新增 `POST /api/debug_log` 端点，记录前端 JS 错误到 `server.log`（前缀 `[UI-ERROR]`）
- `static/index.html` 新增：
  - `window.onerror` 全局捕获 JS 错误 → POST 到 `/api/debug_log`（含行号、堆栈、UI 版本）
  - 页面加载时上报 `UI LOADED`（含版本号、关键元素是否存在），用于确认浏览器加载的是新版本
  - `UI_VERSION` 常量标记页面版本

### 六、其他调整

- `GET /` 响应头新增 `Cache-Control: no-cache, no-store, must-revalidate`，避免浏览器缓存旧版页面导致修复不生效
- 前端消息展示增强：AI/用户消息增加时间戳（`msg-time`）、`msg-body` 结构、`fmtMsgTime()` 函数
- `request_approval` 新增日志：`Sent approval_required for <tool> (tier N)`，方便排查审批链路

---

## 未修改（保持 GitHub 仓库原版）

- **bridge.py**：本机部署实际使用编译好的 `bridge.exe`，仓库的 `bridge.py` 为完整源码版（1697 行、45+ 工具），**保留仓库原版**
- **requirements.txt**：保留仓库完整版（含 bridge 依赖：psutil/Pillow/pyautogui/pywin32 等）
- **README.md / 规格文档 / Q&A**：保留仓库原版
- `.env`、`logs/`、`venv/`、`bridge.exe*` 均在 `.gitignore` 中，不提交

---

## 如何验证

1. 访问 `http://<host>:8000/admin` → 应跳转登录页，用 `admin` / `admin` 登录
2. 登录后历史房间列表每行有「删除」按钮，可删除聊天记录
3. 「服务器日志」标签页可正常加载 server.log / chat.log / bridge.log
4. 在聊天页让 AI 执行危险操作（如关闭飞书），应弹出红色审批框，点击「同意执行」后操作生效
