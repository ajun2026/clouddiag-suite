# A7 · install.sh 覆盖已有 .env 导致生产配置丢失

**发生时间**：2026-09-26 20:23（发现即修复）
**类别**：部署 / 脚本安全
**严重度**：🟡 中（可恢复，但会在生产环境造成配置丢失与短时服务异常）

---

## 现象

在**已部署运行**的服务器上重复执行 `deploy/install.sh`（或做非隔离的脚本测试）时，
脚本会直接 `cat > "$SERVER_DIR/.env"` **覆盖**原 `.env`，导致：

- `PUBLIC_URL` 被改成脚本交互中临时输入的值（如 `https://diag.example.com`）
- AI 配置被改成临时输入的测试值（如 `openai.com` + `sk-test`）
- `ADMIN_PASSWORD` / `BRIDGE_HTTP_SECRET` 等被重置为新生成值
- 服务重启后：客户机连接命令指向错误域名、AI 调用全部失败

本次实际触发：开发端为验证「三种部署形态引导」在**生产机**上跑了脚本交互测试，
脚本执行到 [5/6] 生成配置文件时覆盖了生产 `.env`（20:23→20:26，约 3 分钟）。

---

## 根因

```bash
# install.sh [5/6] 原实现：无条件覆盖
cat > "$SERVER_DIR/.env" << EOF
...
EOF
```

**设计缺陷**：脚本被定位为"首次部署"，未考虑"目标机已有部署"的情况，
既没有备份、也没有提示，属于**破坏性写操作**。

---

## 修复（v1.0.7）

```bash
# ── 2026-09-26 安全加固：避免覆盖已有配置 ──
for _f in "$SERVER_DIR/.env" "$ANALYZER_DIR/.env"; do
    if [ -f "$_f" ]; then
        _bk="${_f}.bak.$(date '+%Y%m%d-%H%M%S')"
        cp "$_f" "$_bk"
        echo -e " ⚠️  已存在 $(basename $_f)，原文件已备份为：$_bk"
    fi
done
```

覆盖前自动备份为 `<name>.env.bak.<时间戳>`，并显式提示用户。

---

## 恢复步骤（本次实际执行）

```bash
# 1) 保存被覆盖的版本留证
mkdir -p backups/polluted-$(date +%Y%m%d-%H%M)
cp clouddiag-server/.env log-analyzer/.env backups/polluted-*/

# 2) 重建 .env（按本机实际部署形态）
#    关键项：PUBLIC_URL / PUBLIC_URL_FALLBACK / COOKIE_SECURE /
#            OPENAI_BASE_URL / OPENAI_API_KEY / OPENAI_MODEL /
#            ADMIN_* / BRIDGE_HTTP_SECRET / LOG_ANALYZER_*

# 3) 重启并验证
sudo systemctl restart clouddiag-server clouddiag-loganalyzer clouddiag-logconsumer
curl -s http://127.0.0.1:8000/api/health
curl -sk https://<域名>/api/health
```

---

## 教训

1. **破坏性写操作必须有备份 + 提示**——哪怕脚本定位是"首次部署"。
2. **脚本测试必须在隔离环境**：不要在生产机跑交互式安装脚本；
   若必须跑，先 `cp .env .env.bak` 并准备回退命令。
3. **已有部署的重跑场景要考虑**：用户重装/迁移/排障时会重跑脚本，
   脚本不能假设"目标机是干净的"。
4. **敏感配置与代码分离的作用**：本次 `.env` 不在版本控制中，
   因此恢复依赖人工重建（若有 `.env` 备份则更快）——日常应定期备份 `.env`。

---

## 相关

- 修复版本：v1.0.7
- 涉及文件：`deploy/install.sh`
- 备份留存：`backups/polluted-<时间戳>/`（被覆盖版本）
