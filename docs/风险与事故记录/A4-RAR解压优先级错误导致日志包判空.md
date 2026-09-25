# A4 · RAR 解压优先级错误导致"日志包为空"

**发生时间**：2026-09-24
**类别**：部署 / 依赖
**严重度**：🔴 高（客户日志完全无法分析，且给出了错误的诊断结论）

---

## 现象

客户上传一个 22.6 MB 的 `.rar` 日志包（内含 2 个 268 MB 的 `.evtx`、1 个 3.9 MB 的 `.dmp`、1 个 `systeminfo.log`），
IDG 日志分析页面显示：

```
osdump/110325-4843-01.dmp     0.0 KB
oslog/Application.evtx        0.0 KB
oslog/system.evtx             0.0 KB
systeminfo.log                0.0 KB
```

AI 对话随之给出错误结论：**"这批日志仍然是 0 字节，没有任何可分析的数据"**，
并建议客户"重新采集日志""确认文件大小不为 0 再发"。

**实际是服务端解压失败**，客户包完全正常。

---

## 根因

`log-analyzer/detectors.py` 的 `.rar` 解压逻辑被改成了 **7z 优先、unrar 兜底**：

```python
elif ext == '.rar':
    # 2026-09-17：优先用 7z（服务器必有，且支持 rar/rar5），unrar 作兜底
    r = subprocess.run(['7z', 'x', '-y', str(filepath), f'-o{extract_dir}'], ...)
    if r.returncode != 0:
        subprocess.run(['unrar', 'x', '-y', str(filepath), str(extract_dir)], ...)
```

**7z 对部分 RAR5 压缩方法不支持**：它会报 `ERROR: Unsupported Method`，
并生成 **0 字节的空文件**（实测 7-Zip 23.01 退出码为 **2**，不是 0）。

> ⚠️ **口径修正（2026-09-25，现网部署端核对指出）**：
> 本文早期版本写"退出码仍为 0"，与本机实测不符。
> 实测环境：7-Zip 23.01（`/usr/bin/7z`）+ UNRAR 7.00，现网真实包 20.7 MB / 394 文件。
> 旧代码是 `rc != 0` 才走 unrar 兜底，因此在**有 unrar 的机器上此类文件本会兜底成功**。
> 更可能的现场根因是：**7z 失败后兜底没生效（现场缺 unrar）** →
> `extract_` 目录已留下 0 字节文件 → 页面列出 0.0 KB → AI 判"空包"。
> 即：**`.rar` 场景下 unrar 是必需依赖，不能只靠 7z**。

### 实锤对比

同一个 `.rar` 文件：

| 解压器 | 结果 |
|---|---|
| `7z x` | ❌ 全部 0 字节（`ERROR: Unsupported Method`，退出码 0） |
| `unrar x` | ✅ 268 MB + 268 MB + 3.9 MB + 1.9 KB 全部正常 |

---

## 修复

`.rar` 改为 **unrar 优先、7z 兜底**，并**新增解压结果校验**（v1.0.4）。
后续 v1.0.5 又修掉了本方案自身的两个缺陷——判定只看返回码 + 7z 兜底写同一目录会覆盖已解出的文件
（详见 [A6](A6-RAR兜底解压覆盖已解文件.md)）：

```python
# 1) unrar 优先，失败再 7z
ok = False
for cmd in ([unrar...], [7z...]):
    r = subprocess.run(cmd, ...)
    if r.returncode == 0 and _extract_has_content(extract_dir):
        ok = True
        break

# 2) 两种解压器都失败 → 抛明确错误（不再静默产出空文件）
if not ok:
    raise RuntimeError("RAR 解压失败（unrar 与 7z 均无法解出内容）——"
                       "该压缩包可能使用了新版 RAR 压缩算法，请重新打包为 zip 或 7z 后上传")
```

新增 `_extract_has_content()`：检查解压目录里是否存在**非空文件**，
避免把"7z 报错但退出码 0 + 全 0 字节"当成解压成功。

---

## 教训

1. **退出码 0 不等于成功**——外部工具（尤其 7z 处理不支持的压缩算法时）会"成功退出但产出空结果"，
   关键路径必须**校验产物**，不能只看返回码。
2. **解压器选择要按格式定**：`.rar` 用 unrar（官方算法覆盖最全），`.7z` 用 7z，不要"一个工具通吃"。
3. **错误要显式化**：解压失败必须抛出可读错误，而不是把空文件交给下游，
   否则 AI 会基于空数据给出**看似合理但完全错误**的结论（比直接报错更危险）。
4. 排查时**先用真实失败样本对比验证**（本次即用客户原包对比 7z / unrar 输出），再下结论。

---

## 复现与验证

```bash
# 复现（旧代码行为）
7z x customer.rar -o/tmp/a && find /tmp/a -type f -size 0 | wc -l   # 全部 0 字节

# 验证（修复后）
cd log-analyzer && ./venv/bin/python -c "
import sys; sys.path.insert(0,'.')
from pathlib import Path
from detectors import extract_archive, _extract_has_content
d = extract_archive(Path('/tmp/customer.rar'))
print('有内容:', _extract_has_content(d))
"
```
