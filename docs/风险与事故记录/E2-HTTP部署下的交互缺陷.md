# E2 · HTTP 部署下的三处交互缺陷（复制按钮 / 游客退出 / 模型提示）

**发生时间**：2026-09-29（外部反馈）
**类别**：产品 / 交互
**严重度**：🟠 中（功能可绕过，但用户以为"坏了"）
**影响版本**：≤ v1.0.8

---

## 现象

在**纯 HTTP + IP 部署**（局域网、非安全上下文）下：

1. **「复制命令」按钮点了没反应**——没有任何提示，用户以为复制失败或按钮坏了；
2. **游客无法退出登录**：点「游客进入」→ 自动跳 `/log-analyzer/` → 页面只有「← 返回主界面」，
   点回去又被自动跳回 IDG → **死循环**，没有任何注销入口；
3. AI 分析失败时只显示「AI 分析所有通道均失败」，看不出是**模型不支持工具调用**
   （本地 Ollama 推理模型常见），用户会去查网络与额度。

## 根因

**① 复制按钮 —— 比"没提示"更早一步就崩了**

```js
navigator.clipboard.writeText(t).then(...).catch(() => { 选中文字 });
```

`navigator.clipboard` **只在安全上下文**（HTTPS 或 localhost）存在。
HTTP + IP 部署时它是 `undefined` → 取 `.writeText` **同步抛 TypeError** →
连 `.catch()` 都进不去 → 降级分支（选中文字）从未执行 → 表现为"完全没反应"。

浏览器实测（Chrome 149，`http://<局域网IP>:8000`）：

```
isSecureContext: false, typeof navigator.clipboard: "undefined"
旧写法结果: THROW_SYNC: TypeError
```

**② 游客退出 —— 角色与页面归属错配**

游客被强制分流到 IDG（独立页面），但 IDG 页面只有「返回主界面」；
`/dashboard` 对游客又是"加载即跳 IDG"，于是没有任何出口。
「退出登录」按钮只存在于工作台——而游客恰恰到不了工作台。

**③ 模型提示 —— 文案把根因说反了**

全通道都拿到"空回复"时（模型只输出推理、不返回 `content`/`tool_calls`），
错误里只有 `空回复(第N次)`，对外却统一说"所有通道均失败"。

## 处置过程

```js
// ① 新增 copyTextSafe()：能用 Clipboard API 才用，否则 execCommand('copy')，
//    两条路径都回调成功/失败 → 明确提示（diag.html + dashboard.html 共 4 处）
// ② IDG 两个页面各加「🚪 退出登录」→ 同源调 /api/auth/logout → 清 localStorage → /login
// ③ 文案改为：全"空回复"时追加"常见于本地推理模型不支持 Function Calling，请换支持工具调用的模型"
//    并兼容 Ollama 的 message.reasoning 字段名（原来只认 reasoning_content）
```

浏览器实测：

| 项 | 修复前 | 修复后 |
|---|---|---|
| 非安全上下文复制 | 同步 TypeError，无任何反应 | `execCommand` 降级 → 成功/失败均有提示 |
| 游客退出 | 死循环，无出口 | 点击 → 回到 `/login`，`user_token` 已清除 |

## 预防措施

- 涉及浏览器 API 的代码，**必须在目标部署形态下实测**（HTTPS 与 HTTP+IP 是两种环境）：
  `navigator.clipboard`、`:has()`、Web Crypto、Service Worker 等在非安全上下文行为不同。
- 凡是"自动跳转 + 强制分流"的角色，**必须在被分流后的页面上提供回退出口**
  （单向导航即缺陷）。
- 错误文案要区分**模型/配置问题**与**网络/资源问题**，否则会把人带到错误的排查方向。

## 相关提交

- 修复：v1.0.9（`clouddiag-server/static/diag.html`、`dashboard.html`、
  `log-analyzer/templates/analyze.html`、`upload.html`、`chat/function_call.py` 等）
