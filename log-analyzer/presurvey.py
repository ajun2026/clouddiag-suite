"""预调查（Pre-survey）——日志包上传后的确定性初步调查。

设计原则（主人 2026-11-04 定）：
1. **纯规则、不调 AI**：确定性、可复现、不花额度；大模型只负责在它之上做推理。
2. **结论只给方向，必带依据**：每条判定都附支撑数据；无数据一律写「数据不足」，不猜。
3. **复用已有分析器**（analyzers/windows.py 的 overview / diagnostics / dump），
   不重写解析逻辑；结果缓存到 reports/{job}_presurvey.json，第二次打开秒出。
4. 客户版脱敏：SN / 主机名 / 注册用户 / 路径在导出给客户的文本时替换。
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent
REPORT_DIR = BASE_DIR / "reports"
REPORT_DIR.mkdir(exist_ok=True)

run_logger = logging.getLogger("presurvey")

# job_id -> "building" | "done" | "error"
_build_state: dict = {}
_locks: dict = {}
_VER = 1          # 结构版本：改动输出结构时 +1，旧缓存自动失效


def cache_path(job_id: str) -> Path:
    return REPORT_DIR / f"{job_id}_presurvey.json"


def _is_win(tslog: Path) -> bool:
    return (tslog / "oslog").exists() or (tslog / "dxdiag.txt").exists()


def _num(v) -> str:
    """把 '24,403' 这类千分位字符串规整成 '24,403 MB' 形式可直接显示。"""
    return str(v or "").strip()


def _build_windows(tslog: Path) -> dict:
    from analyzers.windows import analyze_overview, analyze_system_diagnostics, analyze_dump

    t_start = time.time()
    out = {"os_type": "windows", "sections": {}, "errors": []}

    # ── ① 机器 / 系统（读文本文件，秒级）──
    try:
        ov = analyze_overview(tslog)
        sysd = ov.get("system") or {}
        gpu = ov.get("gpu") or {}
        disks = ov.get("disks") or []
        out["sections"]["machine"] = {
            "manufacturer": sysd.get("manufacturer") or "",
            "model": sysd.get("model") or "",
            "bios": sysd.get("bios_version") or "",
            "cpu": sysd.get("cpu") or "",
            "memory_total": _num(sysd.get("total_memory")),
            "memory_available": _num(sysd.get("available_memory")),
            "chassis": sysd.get("system_type") or "",
        }
        out["sections"]["system"] = {
            "hostname": sysd.get("hostname") or "",
            "os_name": sysd.get("os_name") or "",
            "os_version": sysd.get("os_version") or "",
            "install_date": sysd.get("install_date") or "",
            "boot_time": sysd.get("boot_time") or "",
            "owner": sysd.get("registered_owner") or "",
            "domain": sysd.get("domain") or "",
            "timezone": sysd.get("timezone") or "",
        }
        out["sections"]["gpu"] = {
            "name": gpu.get("name") or "",
            "driver_version": gpu.get("driver_version") or "",
            "display_memory": gpu.get("display_memory") or "",
            "current_mode": gpu.get("current_mode") or "",
        }
        out["sections"]["disks"] = [
            {"model": d.get("model", ""), "serial": d.get("serial", ""), "firmware": d.get("firmware", "")}
            for d in disks[:6]
        ]
    except Exception as e:
        out["errors"].append(f"overview: {e}")

    # ── ② 系统诊断（扫 evtx，慢：可能 60-90s，靠缓存）──
    try:
        dg = analyze_system_diagnostics(tslog)
        hw = dg.get("hardware_errors") or []
        by_type: dict = {}
        for h in hw:
            key = f"{h.get('description') or '未知'}(事件{h.get('id')})"
            by_type[key] = by_type.get(key, 0) + 1
        out["sections"]["events"] = {
            "severity": dg.get("severity") or "",
            "findings": (dg.get("findings") or [])[:6],
            "hardware_error_count": dg.get("hardware_error_count") or 0,
            "hardware_errors": [
                {"id": h.get("id"), "time": h.get("time"), "provider": h.get("provider"),
                 "description": h.get("description")}
                for h in hw[:8]
            ],
            "hardware_by_type": by_type,
            "bugcheck_count": dg.get("bugcheck_count") or 0,
            "unexpected_shutdowns": dg.get("unexpected_shutdowns_count") or 0,
            "normal_restarts": dg.get("normal_restart_count") or 0,
            "lke_count": dg.get("lke_count") or 0,
            "system_top_ids": dict(sorted((dg.get("syst_dist") or {}).items(),
                                          key=lambda kv: -kv[1])[:8]),
            "app_top_ids": dict(sorted((dg.get("app_dist") or {}).items(),
                                       key=lambda kv: -kv[1])[:8]),
            "summary": dg.get("summary") or "",
        }
        bcs = dg.get("bugchecks") or []
        if bcs:
            out["sections"]["bugcheck"] = {
                "count": len(bcs),
                "items": [{"time": b.get("time"), "code": b.get("bugcheck_code") or b.get("code", ""),
                           "desc": (b.get("bugcheck") or {}).get("description", "") if isinstance(b.get("bugcheck"), dict) else ""}
                          for b in bcs[:5]],
            }
    except Exception as e:
        out["errors"].append(f"diagnostics: {e}")

    # ── ③ Dump（解析头部取 bugcheck）──
    try:
        dp = analyze_dump(tslog)
        dumps = dp.get("dumps") or []
        out["sections"]["dump"] = {
            "count": dp.get("dump_count") or len(dumps),
            "items": [{"file": d.get("filename") or d.get("file", ""),
                       "time": d.get("time") or d.get("modified", ""),
                       "code": (d.get("bugcheck") or {}).get("code", "") if isinstance(d.get("bugcheck"), dict) else d.get("bugcheck_raw", ""),
                       "desc": (d.get("bugcheck") or {}).get("description", "") if isinstance(d.get("bugcheck"), dict) else "",
                       "drivers": (d.get("drivers") or [])[:5]}
                      for d in dumps[:5]],
        }
    except Exception as e:
        out["errors"].append(f"dump: {e}")

    out["build_seconds"] = round(time.time() - t_start, 1)
    return out


def _build_linux(tslog: Path) -> dict:
    from analyzers.linux import analyze_linux_overview
    out = {"os_type": "linux", "sections": {}, "errors": []}
    try:
        ov = analyze_linux_overview(tslog)
        out["sections"]["system"] = {k: v for k, v in (ov or {}).items()
                                     if isinstance(v, (str, int, float))}
    except Exception as e:
        out["errors"].append(f"linux_overview: {e}")
    return out


def build(job_id: str, tslog: Path) -> dict:
    """同步构建预调查（慢，调用方应在后台线程里跑）。"""
    out = _build_windows(tslog) if _is_win(tslog) else _build_linux(tslog)
    out["job_id"] = job_id
    out["version"] = _VER
    out["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    out["verdict"] = _verdict(out)
    try:
        cache_path(job_id).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:
        run_logger.warning(f"[presurvey] 缓存写入失败 {job_id}: {e}")
    return out


def _verdict(d: dict) -> dict:
    """一句话结论 + 依据。只给方向，不武断；没数据就说数据不足。"""
    s = d.get("sections") or {}
    ev = s.get("events") or {}
    bc = s.get("bugcheck") or {}
    dp = s.get("dump") or {}
    reasons = []

    n_hw = ev.get("hardware_error_count") or 0
    n_bc = ev.get("bugcheck_count") or 0
    n_un = ev.get("unexpected_shutdowns") or 0
    n_dump = dp.get("count") or 0

    if n_bc:
        reasons.append(f"蓝屏事件 {n_bc} 次")
    if n_dump:
        first = (dp.get("items") or [{}])[0]
        code = first.get("code") or ""
        desc = first.get("desc") or ""
        reasons.append(f"dump {n_dump} 个" + (f"（{code} {desc}）" if code else ""))
    if n_un:
        reasons.append(f"非正常关机 {n_un} 次")
    if n_hw:
        types = "、".join(list((ev.get("hardware_by_type") or {}).keys())[:3])
        reasons.append(f"硬件告警 {n_hw} 条（{types}）")

    if n_bc or n_dump:
        level, head = "bad", "检出蓝屏/崩溃记录，优先看 dump 指向的驱动或硬件"
    elif n_hw or n_un:
        level, head = "warn", "检出硬件告警或非正常关机，方向指向硬件/供电/驱动"
    elif not s:
        level, head = "nodata", "预调查数据不足（该包可能缺 oslog/系统信息文件）"
    else:
        level, head = "ok", "未检出蓝屏与硬件告警；若无症状可不深挖"
    return {"level": level, "headline": head, "reasons": reasons}


def get_cached(job_id: str) -> Optional[dict]:
    p = cache_path(job_id)
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("version") != _VER:
            return None
        return d
    except Exception:
        return None


def ensure_async(job_id: str, tslog: Path) -> str:
    """确保存在预调查：有缓存→done；正在建→building；否则起后台线程→building。"""
    if get_cached(job_id):
        return "done"
    if _build_state.get(job_id) == "building":
        return "building"
    lock = _locks.setdefault(job_id, threading.Lock())
    if not lock.acquire(blocking=False):
        return "building"

    def _run():
        try:
            _build_state[job_id] = "building"
            build(job_id, tslog)
            _build_state[job_id] = "done"
        except Exception as e:
            run_logger.warning(f"[presurvey] 构建失败 {job_id}: {e}")
            _build_state[job_id] = "error"
        finally:
            try:
                lock.release()
            except Exception:
                pass

    threading.Thread(target=_run, daemon=True).start()
    return "building"


def as_prompt_text(d: dict, mask: bool = False) -> str:
    """把预调查压成注入 AI 首轮的上下文块（≤1600 字）。"""
    if not d:
        return ""
    s = d.get("sections") or {}
    m = s.get("machine") or {}
    sy = s.get("system") or {}
    g = s.get("gpu") or {}
    ev = s.get("events") or {}
    bc = s.get("bugcheck") or {}
    dp = s.get("dump") or {}
    v = d.get("verdict") or {}

    def host(x: str) -> str:
        if not x:
            return "—"
        return "客户机" if mask else x

    lines = ["【预调查摘要】（本地规则解析，非 AI 推断；引用时请说明来自日志包）"]
    lines.append(f"机器：{m.get('manufacturer','')} {m.get('model','')} · BIOS {m.get('bios','—')} · "
                 f"CPU {m.get('cpu','—')} · 内存 {m.get('memory_total','—')} MB")
    lines.append(f"系统：{sy.get('os_name','')} {sy.get('os_version','')} · 装机 {sy.get('install_date','—')} · "
                 f"最近启动 {sy.get('boot_time','—')} · 主机 {host(sy.get('hostname',''))}")
    if g:
        lines.append(f"显卡：{g.get('name','—')} · 驱动 {g.get('driver_version','—')} · {g.get('current_mode','')}")
    dk = s.get("disks") or []
    if dk:
        lines.append("磁盘：" + "；".join(
            f"{x.get('model','')}({x.get('serial','')}, 固件 {x.get('firmware','')})" for x in dk[:3]))
    if ev:
        lines.append(f"事件：蓝屏 {ev.get('bugcheck_count',0)} 次 · 非正常关机 {ev.get('unexpected_shutdowns',0)} 次 · "
                     f"硬件告警 {ev.get('hardware_error_count',0)} 条 · LiveKernelEvent {ev.get('lke_count',0)} 个")
        hw = ev.get("hardware_errors") or []
        if hw:
            lines.append("硬件告警明细：" + "；".join(
                f"{h.get('description','')}(事件{h.get('id')}, {h.get('provider','')}, {str(h.get('time'))[:19]})"
                for h in hw[:5]))
        top = ev.get("system_top_ids") or {}
        if top:
            lines.append("System 日志高频事件ID：" + "、".join(f"{k}×{n}" for k, n in list(top.items())[:6]))
    if bc.get("count"):
        lines.append("蓝屏事件：" + "；".join(
            f"{str(i.get('time'))[:19]} {i.get('code','')} {i.get('desc','')}" for i in (bc.get("items") or [])[:3]))
    if dp.get("count"):
        lines.append("Dump 文件：" + "；".join(
            f"{i.get('file','')} {i.get('code','')} {i.get('desc','')} 驱动:{','.join(i.get('drivers') or []) or '—'}"
            for i in (dp.get("items") or [])[:3]))
    lines.append(f"预调查初判（{v.get('level','')}）：{v.get('headline','')}"
                 + (("（依据：" + "、".join(v.get("reasons") or []) + "）") if v.get("reasons") else ""))
    lines.append("提示：以上为规则解析结果，若与工具查询到的细节冲突，以工具查询结果为准，并说明差异。")
    txt = "\n".join(lines)
    return txt[:1600]
