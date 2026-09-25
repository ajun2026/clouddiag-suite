# A6 · RAR 兜底解压覆盖已解文件（修复自身引入的新缺陷）

**发生时间**：2026-09-25（v1.0.4 引入，v1.0.5 修复）
**类别**：部署 / 依赖
**严重度**：🔴 高（比 v1.0.3 更容易把好包整包拒收）
**发现者**：现网部署端逐项核对（v1.0.4 核对报告 P0-1 / P1-2）

---

## 背景

A4 修复（v1.0.4）把 `.rar` 从「7z 优先」改成「unrar 优先」，方向正确，
但实现上引入**两个新缺陷**，导致在某些场景下比修复前更差。

---

## 缺陷 1（P0-1）：判定只看返回码 + 7z 兜底写同一目录 → 覆盖已解出的文件

### v1.0.4 的问题代码

```python
ok = False
for cmd in (['unrar', 'x', '-y', ...], ['7z', 'x', '-y', ...]):
    r = subprocess.run(cmd, ...)
    if r.returncode == 0 and _extract_has_content(extract_dir):
        ok = True
        break
if not ok:
    raise RuntimeError("...请重新打包为 zip 或 7z 后上传")
```

两个问题叠加：

1. **判定只看 `returncode`**——包轻微损坏时 `unrar` 会返回非 0（如 rc=3 checksum error），
   但它**已经解出了大部分可用文件**；代码却认为失败，继续往下走。
2. **7z 兜底解到同一个 `extract_dir`**——7z 对不支持的 RAR5 方法会写出 0 字节文件，
   **把 unrar 刚解好的文件全部覆盖成 0 字节**。

### 实测复现（现网部署端）

```
a) 完整包：unrar → 394 个文件全部非空（rc=0）
          接着 7z x 到同目录 → 394 个文件全部变 0 字节（rc=2）

b) 截断包（head -c 3000000 customer.rar > trunc.rar）：
   unrar → rc=3（checksum error），但已解出 198 个非空可用文件
   代码因 rc!=0 继续走 7z → 198 个文件全部被覆盖成 0 字节
   → _extract_has_content=False → 抛 RuntimeError → 上传被拒
   → 客户收到误导性提示"请重新打包为 zip 或 7z"
```

**对比 v1.0.3**：同一损坏包 = 7z(rc=2) → unrar 兜底 → 拿到 198 个文件可分析。
即 v1.0.4 在"包轻微损坏但能解出大部分"场景属于**功能回退**。

### 修复（v1.0.5）

```python
# 1) 判定改为"有内容即成功"：unrar 即使 rc≠0，只要解出非空文件就采用
r = subprocess.run(['unrar', 'x', '-y', str(filepath), str(extract_dir)], ...)
if _extract_has_content(extract_dir):
    ok = True
    if r.returncode != 0:
        partial = _count_nonempty(extract_dir)
        run_logger.warning(f"unrar 返回码 {r.returncode}，但已解出 {partial} 个非空文件——按可用数据处理")

# 2) 7z 兜底解到独立临时目录，校验有内容后再合并（绝不写进 unrar 的产物目录）
if not ok:
    tmp_dir = extract_dir.parent / (extract_dir.name + ".7z_tmp")
    subprocess.run(['7z', 'x', '-y', str(filepath), f'-o{tmp_dir}'], ...)
    if _extract_has_content(tmp_dir):
        ...合并进 extract_dir...
        ok = True

# 3) 错误文案区分"完全解不出"与"部分损坏"
```

---

## 缺陷 2（P1-2）：`extract_` 目录"存在即早退" → 中毒目录永久判空包

### 问题代码（v1.0.4 仍在）

```python
def extract_archive(filepath: Path) -> Path:
    extract_dir = filepath.parent / f"extract_{filepath.stem}"
    if extract_dir.exists():
        return extract_dir      # already extracted
```

A4 事故里 7z 失败正好留下"**全 0 字节的 extract_ 目录**"。
升级后被污染的目录仍在磁盘上，客户**重传同一个包**时直接返回该目录 →
依旧判"日志包为空"，**A4 的修复在"已经脏过的目录"上完全失效**。

### 修复（v1.0.5）

```python
if extract_dir.exists() and _extract_has_content(extract_dir):
    return extract_dir                      # 有内容才复用
if extract_dir.exists():
    run_logger.warning(f"解压目录存在但无有效内容，清理后重新解压: {extract_dir.name}")
    shutil.rmtree(extract_dir, ignore_errors=True)
extract_dir.mkdir(parents=True, exist_ok=True)
```

---

## 验证（v1.0.5 实测）

| 场景 | v1.0.4 行为 | v1.0.5 行为 |
|---|---|---|
| 完整包 | ✅ 正常解出 | ✅ 正常（4 个非空文件） |
| 截断包（可解出部分） | ❌ 7z 覆盖 → 抛错拒收 | ✅ 保留 2 个非空文件，日志记警告 |
| 中毒目录 + 重传 | ❌ 直接返回空目录 → 判"空包" | ✅ 清理后重解 → 4 个非空文件 |
| 已有有效内容 | ✅ 复用 | ✅ 复用（< 0.5s 返回） |
| HTTP 上传回归 | — | ✅ `evtx_count=4` 正常识别 |

---

## 教训

1. **修复要连"失败路径的副作用"一起考虑**：兜底解压器的输出目录必须隔离，
   否则"兜底"会变成"覆盖式破坏"。
2. **返回码不是唯一判据**：外部工具部分成功（rc≠0 但产出可用数据）时，
   应以**产物是否可用**为准，不能一刀切丢弃。
3. **缓存目录要有自愈能力**："存在即复用"是危险的——必须校验内容有效性，
   否则一次失败会永久污染该路径。
4. **修复后要主动核对**：本次由现网部署端逐项复现才发现，说明
   "改完只做正向验证"不够，还要**构造损坏/异常输入**验证降级行为。

---

## 相关

- [A4](A4-RAR解压优先级错误导致日志包判空.md)——同类问题的上一轮修复
- 现网核对报告：`clouddiag-v1.0.4-核对与待修问题.txt`（P0-1 / P1-2）
