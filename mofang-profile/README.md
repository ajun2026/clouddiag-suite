# mofang-profile · 整机档案数据源旁挂服务

给二线控制台 `/expert` 左栏「整机档案」（保修 / 出厂配置 / 历史维修记录）提供数据的旁挂服务。

| 数据 | 来源 |
|---|---|
| 保修、历史维修记录、出厂配置（BOM 装箱单） | 魔方服务（IPS / SF），服务账号登录 + 工作流接口 |
| 机型 / MTM / 生产日期 / 保修起止 / 出厂配置简称 | 联想官网 ASP `getDeviceInfo`（无需登录） |

## 为什么是旁挂而不是塞进主服务

- 主服务不引入第三方账号与会话逻辑，也不需装 `ddddocr`/`cairosvg` 这类重依赖
- 旁挂挂了只影响左栏三行（显示「查询失败」），不影响诊断主链路
- 主服务只按既有契约 `{summary, detail}` 消费，`.env` 配 URL 即可接入

## 部署

```bash
# 依赖（建议直接复用 clouddiag-server 的 venv）
pip install -r requirements.txt

cp .env.example .env        # 填账号密码与共享令牌，权限 600
python app.py               # 默认监听 127.0.0.1:8081
```

systemd 示例（`/etc/systemd/system/clouddiag-profile.service`）：

```ini
[Unit]
Description=CloudDiag Profile Sidecar
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/path/to/mofang-profile
ExecStart=/path/to/venv/bin/python app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## 接口

| 路径 | 用途 |
|---|---|
| `GET /warranty?sn=` | 保修（魔方） |
| `GET /repair?sn=` | 历史维修记录（魔方） |
| `GET /factory?sn=` | 出厂配置装箱单（魔方 IPS） |
| `GET /asp_profile?sn=` | 官网档案补充源（机型/MTM/生产日期/保修起止/配置简称） |
| `GET /asp_warranty?sn=` | 官网原始校验结果（有效性/在保判定/服务产品） |
| `GET /health` | 魔方会话在线状态 + 官网配置 |

除 `/health` 外都需要 `Authorization: Bearer <PROFILE_TOKEN>`。

## 几条硬规则（踩过坑，别改回去）

1. **按 SN + 用途分会话**：魔方工作流靠「会话变量」传数据，同一 `chatId` 并发两轮会串台，必须 `warranty-<SN>` / `config-<SN>` 分开并加锁串行。
2. **空结果不缓存、不判成功**：解析不出型号/保修截止就返回失败，否则会缓存一天的空壳。
3. **登录用干净 client**：旧 cookie 里带 `captcha` 时，服务端重复下发同名 cookie 会让 httpx 抛 `Multiple cookies exist`。
4. **历史工单不是进行中工单**：`device_info` 里「工单1工单号」是历史维修记录，绝不能写进房间的工单字段。
5. **官网百分比不要做成单一数字**：每条服务产品各自一个剩余比例（未开始的展期常是 100%），硬取最大值会误导。

## 会话保活

`fastgpt_token` 落盘在 `state/session.json`（600 权限，不入库），后台每 30 分钟 `tokenLogin` 探活；失效才走「验证码 OCR + 密码登录」（cairosvg 渲染 + ddddocr 多尺度投票，票数不一致就换一张重试）。
