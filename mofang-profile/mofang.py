#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
魔方服务（agent.cube.lenovo.com）适配层
────────────────────────────────────────────────────────────────
作用：用服务账号登录魔方服务，按 SN 取「保修 / 历史维修 / 出厂配置」，
      解析成二线控制台「整机档案」需要的 {summary, detail} 结构。

设计要点（为什么这么写）：
  1) 纯 HTTP，不依赖浏览器：/api/v2/chat/completions 走 SSE，
     真正的数据在两个 HTTP 节点（根据SN号获取设备维保 / 根据SN查找设备配置），
     我们消费工作流节点回填的 pluginOutput / httpResult，不解析大模型的自然语言尾巴。
  2) 保修 + 历史维修来自同一次查询（device_info 里带历史维修明细），
     所以按 SN 做一次缓存，两种视图都从缓存派生，省一次 50 秒调用。
  3) 会话（httpOnly cookie fastgpt_token）落盘 + 定期在线校验；
     失效才走「图形验证码 OCR + 密码登录」，验证码用多尺度投票，票不一致直接换一张再试。
  4) 任何异常都不抛给主服务：返回 ok=false + summary，二线台只是那几行显示「查询失败」。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from collections import Counter

import httpx

# ── 依赖（缺失时降级为「需人工更新 cookie」，不影响主服务）────────────────
try:
    import cairosvg
    import ddddocr
    _OCR_OK = True
except Exception:                                    # pragma: no cover
    _OCR_OK = False

APP_ID = os.getenv("MOFANG_APP_ID", "66cc1c31a90a341aafe8c758")
BASE = os.getenv("MOFANG_BASE_URL", "https://agent.cube.lenovo.com").rstrip("/")
USER = os.getenv("MOFANG_USERNAME", "")
PWD = os.getenv("MOFANG_PASSWORD", "")
STATE_PATH = os.getenv("MOFANG_STATE_PATH", "")
CACHE_TTL = int(os.getenv("MOFANG_CACHE_TTL", "86400"))        # 同一 SN 缓存 24h
CHAT_ID = os.getenv("MOFANG_CHAT_ID", "clouddiag-profile-console")
KEEPALIVE = int(os.getenv("MOFANG_KEEPALIVE_SECS", "1800"))    # 30 分钟校验一次在线
ASK_TIMEOUT = float(os.getenv("MOFANG_ASK_TIMEOUT", "150"))    # 配置查询实测约 50s

_lock = threading.RLock()
_state: dict = {"cookies": {}, "chat_id": CHAT_ID, "last_check": 0, "last_login": 0,
                "login_fail": 0, "note": ""}
_cache: dict[str, dict] = {}                                   # sn -> {at, device_info, config, raw}
_ocr = None


# ══════════════════════════════════════════════════════════════════════
# 状态落盘
# ══════════════════════════════════════════════════════════════════════
def _load_state():
    global _state
    if not STATE_PATH or not os.path.exists(STATE_PATH):
        return
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d.get("cookies"), dict):
            _state.update({k: d[k] for k in ("cookies", "chat_id", "last_check", "last_login") if k in d})
    except Exception:
        pass


def _save_state():
    if not STATE_PATH:
        return
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({k: _state[k] for k in ("cookies", "chat_id", "last_check", "last_login")},
                      f, ensure_ascii=False, indent=1)
        os.replace(tmp, STATE_PATH)
        os.chmod(STATE_PATH, 0o600)
    except Exception:
        pass


def _client(fresh: bool = False) -> httpx.Client:
    """fresh=True 用于登录流程：不带旧 cookie，否则服务端重复下发同名 captcha 会冲突。"""
    jar = {} if fresh else (_state.get("cookies") or {})
    return httpx.Client(base_url=BASE, timeout=httpx.Timeout(ASK_TIMEOUT, connect=15.0),
                        cookies=jar, follow_redirects=True,
                        headers={"User-Agent": "clouddiag-profile/1.0", "Accept-Language": "zh-CN"})


def _absorb_cookies(c: httpx.Client):
    jar = {k: v for k, v in c.cookies.items()}
    if jar:
        _state["cookies"] = jar
        _save_state()


# ══════════════════════════════════════════════════════════════════════
# 验证码 OCR：SVG → PNG（补边避免末位字被裁）→ 多尺度识别投票
# ══════════════════════════════════════════════════════════════════════
def _ocr_svg(svg: str) -> str:
    global _ocr
    if not _OCR_OK:
        return ""
    inner = re.sub(r"^<svg[^>]*>", "", svg or "").replace("</svg>", "")
    if not inner:
        return ""
    wrap = ('<svg xmlns="http://www.w3.org/2000/svg" width="150" height="60" '
            'viewBox="-10 -7 150 60">' + inner + "</svg>").encode()
    if _ocr is None:
        _ocr = ddddocr.DdddOcr(show_ad=False)
    votes = []
    for w, h in ((600, 240), (900, 360), (1200, 480), (1500, 600)):
        try:
            png = cairosvg.svg2png(bytestring=wrap, output_width=w, output_height=h,
                                   background_color="white")
            t = (_ocr.classification(png) or "").strip()
            if t:
                votes.append(t)
        except Exception:
            continue
    if not votes:
        return ""
    best, n = Counter(votes).most_common(1)[0]
    return best if n >= 2 or len(votes) == 1 else ""


def login() -> dict:
    """登录：取图形验证码 → OCR → 密码登录。返回 {ok, error}。"""
    if not USER or not PWD:
        return {"ok": False, "error": "未配置 MOFANG_USERNAME / MOFANG_PASSWORD"}
    if not _OCR_OK:
        return {"ok": False, "error": "未安装 cairosvg / ddddocr，无法自动过验证码，请人工更新 cookie"}
    last = ""
    for attempt in range(1, 7):
        try:
            with _client(fresh=True) as c:
                r = c.get("/api/lenovo/support/user/account/getCaptcha")
                if r.status_code != 200:
                    last = f"取验证码 HTTP {r.status_code}"
                    continue
                svg = r.text
                try:                                    # 可能是裸 svg 或 {data:svg}
                    js = json.loads(svg)
                    svg = js.get("data") or svg
                except Exception:
                    pass
                code = _ocr_svg(svg)
                if not code or len(code) < 4:
                    last = f"验证码识别失败（{attempt}）"
                    continue
                r2 = c.post("/api/lenovo/support/user/account/loginByPassword",
                            json={"username": USER, "password": PWD, "captcha": code})
                _absorb_cookies(c)
                body = {}
                try:
                    body = r2.json()
                except Exception:
                    pass
                if r2.status_code == 200 and body.get("code") in (200, 0, None):
                    tok = (c.cookies.get("fastgpt_token") or _state["cookies"].get("fastgpt_token") or "")
                    if tok:
                        _state["last_login"] = int(time.time())
                        _state["login_fail"] = 0
                        _state["note"] = ""
                        _save_state()
                        return {"ok": True, "attempts": attempt}
                    last = "登录返回 200 但没有 token cookie"
                else:
                    last = f"登录失败：{body.get('message') or body.get('statusText') or r2.status_code}"
        except Exception as e:
            last = f"登录异常：{e}"
        time.sleep(1.0)
    _state["login_fail"] += 1
    _state["note"] = last
    return {"ok": False, "error": last}


def validate() -> bool:
    """用一个轻量接口确认 cookie 还在线（tokenLogin 不消耗额度、不建会话）。"""
    if not _state.get("cookies", {}).get("fastgpt_token"):
        return False
    try:
        with _client() as c:
            r = c.get("/api/lenovo/support/user/account/tokenLogin")
            _absorb_cookies(c)
            ok = r.status_code == 200 and (r.json() or {}).get("code") in (200, 0)
            if ok:
                _state["last_check"] = int(time.time())
                _save_state()
            return bool(ok)
    except Exception:
        return False


def ensure_session(force: bool = False) -> bool:
    """保证会话可用：先校验，失效再登录。"""
    with _lock:
        if not force and validate():
            return True
        res = login()
        if res.get("ok"):
            return True
        _state["note"] = res.get("error", "")
        # 兜底：老 cookie 有时只是 tokenLogin 临时抖动，查询仍可用
        return bool(_state.get("cookies", {}).get("fastgpt_token")) and not force


# ══════════════════════════════════════════════════════════════════════
# 调工作流 + 收节点数据
# ══════════════════════════════════════════════════════════════════════
def _collect(evs) -> dict:
    """把所有工作流节点里的结构化结果汇总出来。"""
    out = {"device_info": "", "answer": "", "json": {}, "nodes": []}
    def walk(n):
        if not isinstance(n, dict):
            return
        if n.get("moduleName"):
            out["nodes"].append(str(n.get("moduleName"))[:60])
        for k, v in list(n.items()):
            if k == "pluginOutput" and isinstance(v, dict):
                if isinstance(v.get("device_info"), str) and v["device_info"].strip():
                    out["device_info"] = out["device_info"] or v["device_info"]
                if isinstance(v.get("answer"), str) and v["answer"].strip():
                    out["answer"] = out["answer"] or v["answer"]
            if k == "httpResult" and isinstance(v, dict):
                if isinstance(v.get("device_info"), str) and v["device_info"].strip():
                    out["device_info"] = out["device_info"] or v["device_info"]
                out["json"][n.get("moduleName") or "http"] = v
        walk(n.get("pluginDetail"))
    for _, d in evs:
        walk(d)
    return out


_chat_locks: dict = {}
_chat_locks_guard = threading.Lock()


def _chat_lock(cid: str):
    with _chat_locks_guard:
        return _chat_locks.setdefault(cid, threading.Lock())


def ask(question: str, chat_key: str = "") -> dict:
    """问一句，返回 {ok, device_info, answer, error, nodes}

    chat_key：会话隔离键。魔方工作流按「会话变量」传递 device_info，
      同一个 chatId 并发两轮会串台（实测会把另一轮的上下文带进来，甚至拿回空结果），
      所以按 SN + 用途分会话，并且同一会话内的请求串行。
    """
    cid = (_state.get("chat_id") or CHAT_ID) + ("-" + re.sub(r"[^A-Za-z0-9_.-]", "", chat_key) if chat_key else "")
    lk = _chat_lock(cid)
    body = {
        "messages": [{"dataId": "", "hideInUI": False, "role": "user", "content": question}],
        "variables": {"sn": "", "useDS": False, "modelName": "Qwen3.5-397B-FP8",
                      "weakForcePush": 2, "forcePush": 2, "externalKB": False},
        "responseChatItemId": "", "appId": APP_ID,
        "chatId": cid,
        "retainDatasetCite": True, "chatPlatform": "online", "detail": True, "stream": True,
    }
    try:
        lk.acquire()
        with _client() as c:
            r = c.post("/api/v2/chat/completions", json=body,
                       headers={"Content-Type": "application/json", "Accept": "text/event-stream"})
            _absorb_cookies(c)
            if r.status_code in (401, 403) or '"code":403' in (r.text or "")[:400]:
                return {"ok": False, "need_login": True, "error": f"HTTP {r.status_code}"}
            if r.status_code >= 400:
                return {"ok": False, "error": f"HTTP {r.status_code}"}
            evs, cur = [], None
            for line in (r.text or "").splitlines():
                if line.startswith("event: "):
                    cur = line[7:].strip()
                elif line.startswith("data: "):
                    try:
                        evs.append((cur, json.loads(line[6:])))
                    except Exception:
                        pass
            got = _collect(evs)
            streamed = "".join(d.get("text", "") for e, d in evs
                               if e == "answer" and isinstance(d.get("text"), str))
            got["answer"] = got["answer"] or streamed
            got["ok"] = bool(got["device_info"] or got["answer"])
            got["chat"] = cid
            return got
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        try:
            lk.release()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════
# 解析：把 markdown 事实文本拆成字段
#   规则：标签匹配要宽容（全角/半角冒号、加粗星号、空格）；
#        解析不出来不抛异常，原文全量留在 detail.原始文本 里供人工核对。
# ══════════════════════════════════════════════════════════════════════
_LABELS = {
    "model": r"产品型号",
    "prod_date": r"生产日期",
    "warranty_end": r"保修截止日期|保修到期日期",
    "warranty_status": r"保修状态",
    "channel": r"销售通路|销售渠道",
    "mot_count": r"(?:\d{4}\s*年度)?该?设备历史\s*MOT|MOT\s*数量|MOT\s*_?count",
    "mot_owner": r"MOT\s*Owner",
    "open_orders": r"进行中工单数",
    "repair_count": r"历史维修次数|维修次数",
    "upgrade_count": r"升级单数",
}


def _val(text: str, pat: str) -> str:
    """宽容取值：标签与冒号之间可能有「为」/星号/空格；值可能被 ** 包住。"""
    m = re.search(r"(?:" + pat + r")\s*(?:为)?\s*[*：:]\s*[*\s]*([^\n|*]{0,120})", text, re.I)
    if not m:
        return ""
    return m.group(1).replace("*", "").strip(" :：\t")


def parse_device_info(text: str) -> dict:
    t = text or ""
    d = {k: _val(t, p) for k, p in _LABELS.items()}
    for k in ("mot_count", "open_orders", "repair_count", "upgrade_count"):
        m = re.search(re.escape(d.get(k) or "") or r"(?!)", "")  # 占位，避免空值报错
        d[k] = re.sub(r"[^\d]", "", d.get(k) or "")
    # 其他服务保修（TS333 这类附加服务）
    other = []
    m = re.search(r"其他服务保修信息[:：]\s*\n?([\s\S]{0,600}?)(?:\n\s*\n|上门服务信息|$)", t)
    if m:
        for line in m.group(1).splitlines():
            line = line.strip("-* ").strip()
            if not line:
                continue
            line = _unescape(line)
            # 服务名里可能带空格/下划线（如「TS P5/6/7/9 1+1+1 to 3+3+3_EB」），按「保修时间」切分
            mm = re.match(r"(.+?)\**\s*保修时间\s*[:：]\s*(.+)", line)
            if mm:
                other.append({"服务": mm.group(1).strip("* "), "保修时间": mm.group(2).strip("* ")})
            else:
                other.append({"原文": line})
    onsite = []
    m = re.search(r"上门服务信息[:：]\s*\n?([\s\S]{0,600}?)(?:\n\s*\n|##|$)", t)
    if m:
        for line in m.group(1).splitlines():
            line = _unescape(line).replace("**", " ").strip("-* ").strip()
            if line:
                onsite.append(re.sub(r"\s+", " ", line))
    # 历史维修明细：按「工单N字段：值」分组
    repairs, cur = [], None
    for m in re.finditer(r"工单\s*(\d+)\s*([^：:\n]{2,20})[：:]\s*([^\n]*)", t):
        idx, key, val = m.group(1), m.group(2).strip().replace("*", ""), m.group(3).replace("*", "").strip()
        if cur is None or cur.get("_i") != idx:
            cur = {"_i": idx}
            repairs.append(cur)
        cur[key] = val
    for r in repairs:
        r.pop("_i", None)
    # 非返还/意外保
    def _section(name):
        m = re.search(r"##?\s*" + name + r"[\s\S]{0,200}", t)
        if not m:
            return ""
        seg = m.group(0).splitlines()
        return (seg[1].strip() if len(seg) > 1 else "")[:80]
    d["其他服务保修"] = other
    d["上门服务"] = onsite
    d["历史维修明细"] = repairs
    d["意外保服务"] = _section("意外保服务信息")
    d["备件不返还服务"] = _section("备件不返还服务信息")
    d["原始文本"] = t.strip()[:6000]
    return d


def parse_bom(text: str) -> dict:
    """出厂配置：markdown 表 → 结构化行 + 关键件摘要。"""
    rows, cur = [], {}
    for line in (text or "").splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip().strip("*") for c in line.strip().strip("|").split("|")]
        if not cells or set("".join(cells)) <= set("-: "):
            continue
        if any(k in cells[0] for k in ("类别", "ECC")):
            continue
        cur = {"类别": cells[0], "信息": cells[1] if len(cells) > 1 else "",
               "客户化": cells[2] if len(cells) > 2 else "",
               "物料编码": cells[3] if len(cells) > 3 else ""}
        rows.append(cur)
    # 关键件摘要：命中词按优先级取，另带排除词
    #   · 排除标签/贴纸/包装行（BOM 里「LABEL Intel Xeon w3 Size3」「L1 LBL Xeon W3 CPU Label」会抢位）
    #   · 排除散热片/线材（CPU HS clip、电源线）
    _NOISE = ("label", "lbl", "mark", "carton", "sticker", "贴纸", "标识", "铭牌")
    def pick(include, exclude=()):
        for r in rows:
            blob = (r["类别"] + " " + r["信息"]).lower()
            if any(x in blob for x in _NOISE):
                continue
            if any(x.lower() in blob for x in exclude):
                continue
            if any(k.lower() in blob for k in include):
                return r["信息"], r["物料编码"]
        return "", ""
    # CPU 单独打分：Xeon/处理器 +主频 +核数，排除 Package Carrier / Socket / 标签行
    _BADCPU = ("carrier", "socket", "clip", "cooler", "heatsink", "hsk", "散热", "风扇",
               "dummy", "connector", "cable", "线")
    cpu, cpu_pn, _best = "", "", -1
    for _r in rows:
        _b = (_r["类别"] + " " + _r["信息"]).lower()
        if any(x in _b for x in _NOISE) or any(x in _b for x in _BADCPU):
            continue
        _sc = 0
        if re.search(r"xeon|epyc|ryzen|core\s+i\d|处理器|pentium|athlon", _b):
            _sc += 4
        if re.search(r"\d\.\d\s*g\b", _b):
            _sc += 2
        if re.search(r"\b\d+c\b|\d+c\s*\d+t", _b):
            _sc += 1
        if _sc > _best and _sc > 0:
            _best, cpu, cpu_pn = _sc, _r["信息"], _r["物料编码"]
    mem, mem_pn = pick(("memory", "内存"))
    gpu, gpu_pn = pick(("video_card", "显示卡", "quadro"))
    hdd, hdd_pn = pick(("hdd", "硬盘"), exclude=("cable", "线", "power"))
    ssd, ssd_pn = pick(("ssd", "固态"), exclude=("cable", "heatsink", "heasink", "板卡"))
    # 电源常有 900W/280W 两条（替代料），取瓦数最大的那条
    cands = []
    for r in rows:
        blob = (r["类别"] + " " + r["信息"]).lower()
        if any(x in blob for x in ("电源线", "line cord", "cable", "cbl")):
            continue
        if any(k in blob for k in ("pwr_supply", "pwr supply", "psu", "电源", "power supply")):
            w = re.search(r"(\d{3,4})\s*W", r["信息"], re.I)
            cands.append((int(w.group(1)) if w else 0, r["信息"], r["物料编码"]))
    cands.sort(reverse=True)
    psu, psu_pn = (cands[0][1], cands[0][2]) if cands else ("", "")
    if not any((cpu, mem, gpu, hdd, ssd)):
        return {"rows": [], "原始文本": (text or "")[:20000]}
    return {"rows": rows, "count": len(rows),
            "cpu": cpu, "cpu_pn": cpu_pn, "mem": mem, "mem_pn": mem_pn,
            "gpu": gpu, "gpu_pn": gpu_pn, "hdd": hdd, "hdd_pn": hdd_pn,
            "ssd": ssd, "ssd_pn": ssd_pn, "psu": psu, "psu_pn": psu_pn,
            "原始文本": (text or "")[:20000]}


def _unescape(s: str) -> str:
    return (s or "").replace("\\_", "_").replace("\\*", "*").replace("\\-", "-")


def _short(s: str, n: int = 42) -> str:
    s = re.sub(r"\s+", " ", (s or "").strip())
    return s if len(s) <= n else s[:n - 1] + "…"


# ══════════════════════════════════════════════════════════════════════
# 对外：按 SN 取数据（带缓存）
# ══════════════════════════════════════════════════════════════════════
def _fetch_device(sn: str) -> dict:
    hit = _cache.get(sn)
    if hit and hit.get("ok") and time.time() - hit["at"] < CACHE_TTL:
        return hit
    res = ask(f"查询SN：{sn} 保修", chat_key=f"warranty-{sn}")
    if res.get("need_login"):
        ensure_session(force=True)
        res = ask(f"查询SN：{sn} 保修", chat_key=f"warranty-{sn}")
    info = res.get("device_info") or ""
    answer = res.get("answer") or ""
    if not info and answer and "没有查询到" not in answer:
        info = answer
    if not info or "没有查询到" in info[:200]:
        print(f"[mofang] {sn} 保修查询无数据 error={res.get('error')} "
              f"info={info[:120]!r} answer={answer[:120]!r}", flush=True)
        return {"ok": False, "error": res.get("error") or "魔方服务未返回该 SN 的保修数据"}
    parsed = parse_device_info(info + "\n" + answer)
    # 关键校验：解析不出型号/保修截止 就当作失败，绝不把空结果缓存下来
    if not (parsed.get("model") or parsed.get("warranty_end")):
        print(f"[mofang] {sn} 保修结果无法解析（可能串台） info={info[:200]!r} answer={answer[:200]!r}",
              flush=True)
        return {"ok": False, "error": "魔方返回内容无法解析（已丢弃，未缓存）"}
    item = {"ok": True, "at": time.time(), "device_info": info, "answer": answer,
            "parsed": parsed, "config": (hit or {}).get("config")}
    _cache[sn] = {**(hit or {}), **item}
    return _cache[sn]


def warranty(sn: str) -> dict:
    r = _fetch_device(sn)
    if not r.get("ok"):
        return {"ok": False, "summary": r.get("error", "查询失败"), "detail": {}}
    p = r["parsed"]
    end, st = p.get("warranty_end", ""), p.get("warranty_status", "")
    summary = " · ".join(x for x in (p.get("model"), st + (f"（截止 {end}）" if end else "")) if x)
    return {"ok": True, "summary": summary or "已获取", "detail": {
        "产品型号": p.get("model"), "生产日期": p.get("prod_date"),
        "保修截止": end, "保修状态": st, "销售通路": p.get("channel"),
        "进行中工单": p.get("open_orders"), "历史维修次数": p.get("repair_count"),
        "升级单数": p.get("upgrade_count"),
        "MOT 次数": p.get("mot_count"), "MOT Owner": p.get("mot_owner"),
        "其他服务保修": p.get("其他服务保修"), "上门服务": p.get("上门服务"),
        "意外保": p.get("意外保服务"), "备件不返还": p.get("备件不返还服务"),
    }}


def repair(sn: str) -> dict:
    r = _fetch_device(sn)
    if not r.get("ok"):
        return {"ok": False, "summary": r.get("error", "查询失败"), "detail": {}}
    p = r["parsed"]
    items = p.get("历史维修明细") or []
    n = p.get("repair_count") or (str(len(items)) if items else "0")
    summary = f"共 {n} 次维修" + (f" · 最近 {items[0].get('开单时间', '')}" if items else "")
    return {"ok": True, "summary": summary.strip(), "detail": {
        "历史维修次数": n, "工单明细": items or "无历史维修记录",
        "原文": ("\n".join("- " + " | ".join(f"{k}：{v}" for k, v in it.items()) for it in items)
                 if items else ""),
    }}


_fail_cache: dict = {}      # sn → (ts, 结果)；失败结果只留 60 秒，便于重试但不重复等 50 秒

def factory(sn: str) -> dict:
    """出厂配置：不依赖保修查询，独立会话独立缓存——两者可并行，省一轮等待。"""
    _f = _fail_cache.get(sn)
    if _f and time.time() - _f[0] < 60:
        return _f[1]
    r = _cache.get(sn) or {}
    cfg = (r.get("config") or {})
    if not cfg or time.time() - cfg.get("at", 0) > CACHE_TTL:
        res = ask(f"查询配置信息：SN {sn}", chat_key=f"config-{sn}")
        if res.get("need_login"):
            ensure_session(force=True)
            res = ask(f"查询配置信息：SN {sn}", chat_key=f"config-{sn}")
        txt = res.get("answer") or ""
        # 2026-11-10：失败分档，别把三种情况说成一句"未返回可解析的装箱单"
        #   ① 完全没响应/超时 ② 响应了但说没查到 ③ 有内容但解析不出物料行（附原文摘要）
        if not txt:
            _fail_cache[sn] = (time.time(), {"ok": False,
                                             "summary": "魔方未响应（超时或未登录）：" + (res.get("error") or "无返回"),
                                             "detail": {}})
            return _fail_cache[sn][1]
        if "没有查询到" in txt[:300] or "未查询到" in txt[:300]:
            _fail_cache[sn] = (time.time(), {"ok": False, "summary": "魔方查无此 SN 的装箱单（IPS 无记录）",
                                             "detail": {"原始回答": txt[:800]}})
            return _fail_cache[sn][1]
        _p = parse_bom(txt)
        if not _p.get("rows"):
            print(f"[mofang] {sn} 配置信息无法解析 txt={txt[:200]!r}", flush=True)
            _rows_hint = ""
            _cells = []
            for _a, _b in re.findall(r"\|\s*([^|\n]{1,24})\s*\|\s*([^|\n]{1,60})\s*\|", txt):
                _a, _b = _a.strip("* ").strip(), _b.strip("* ").strip()
                if not _a or not _b or set(_a) <= set("-: ") or set(_b) <= set("-: "):
                    continue
                if _a in ("类别", "配置"):
                    continue
                _cells.append(f"{_a}：{_b}")
            if _cells:
                _rows_hint = "；返回里只有 " + "；".join(_cells[:2])
            _fail_cache[sn] = (time.time(), {"ok": False,
                                             "summary": "魔方有返回，但没有物料明细" + _rows_hint,
                                             "detail": {"原始回答": txt[:1200], "解析到行数": len(_p.get("rows") or [])}})
            return _fail_cache[sn][1]
        cfg = {"at": time.time(), "parsed": _p}
        _fail_cache.pop(sn, None)
        _cache.setdefault(sn, {"at": time.time()})
        _cache[sn]["config"] = cfg
    p = cfg["parsed"]
    if not p.get("rows"):
        return {"ok": False, "summary": "未解析到装箱单行", "detail": {"原文": p.get("原始文本", "")[:2000]}}
    head = " · ".join(_short(x, 30) for x in (p.get("cpu"), p.get("mem"), p.get("gpu")) if x)
    return {"ok": True, "summary": f"{p.get('count')} 项物料" + (f" · {head}" if head else ""),
            "detail": {"物料行数": p.get("count"), "CPU": p.get("cpu"), "CPU 物料": p.get("cpu_pn"),
                       "内存": p.get("mem"), "内存物料": p.get("mem_pn"),
                       "显卡": p.get("gpu"), "显卡物料": p.get("gpu_pn"),
                       "硬盘": p.get("hdd"), "硬盘物料": p.get("hdd_pn"),
                       "固态": p.get("ssd"), "固态物料": p.get("ssd_pn"),
                       "电源": p.get("psu"), "电源物料": p.get("psu_pn"),
                       "装箱单": p.get("rows")}}



# ══════════════════════════════════════════════════════════════════════
# 当前工单（2026-11-08）
#   关键发现：魔方工作流「按问句决定返回哪一块」。
#     · 「查询SN：x 保修」→ 不含进行中工单段（旧逻辑据此判"工单不可信"，是问错了句子）
#     · 「查询SN：x 工单」→ 明确返回「该设备当前进行中工单数为 N」+「进行中工单i工单号/开单时间/故障描述/解决方案/企业名称」
#   真值验证：GM0DLHEH 内部系统有活动工单 → 魔方 1 单；PC0WZMAB 无 → 魔方 0 单（2/2 一致）。
#   注意多单时字段带序号：进行中工单1工单号…、进行中工单2工单号…，正则必须带 (\d*)
# ══════════════════════════════════════════════════════════════════════
TICKET_CACHE_TTL = int(os.getenv("MOFANG_TICKET_TTL", "600"))   # 工单状态变化快，缓存 10 分钟
_ticket_cache: dict = {}
_ticket_lock = threading.Lock()


def parse_ticket(text: str) -> dict:
    """从「工单」问句的回答里抠进行中工单。返回 {count, tickets[], warranty{}}"""
    flat = text or ""
    out = {"count": None, "tickets": [], "warranty": {}}
    m = re.search(r"进行中工单数为?[：:\s]*([0-9]+)", flat)
    if not m:
        m = re.search(r"当前进行中工单[^0-9]{0,6}([0-9]+)", flat)
    if m:
        out["count"] = int(m.group(1))
    # 每条工单：优先带序号的完整字段块
    # 多单时字段带序号；单张时常见无序号写法（进行中工单工单号：…）
    idxs = sorted({int(x) for x in re.findall(r"进行中工单(\d+)工单号", flat)})
    if not idxs and out["count"]:
        idxs = [1]
    for i in idxs:
        def g(label: str) -> str:
            pats = [rf"进行中工单{i}{label}[：:\s]*(.*)"]
            if i == 1:
                pats.append(rf"进行中工单{label}[：:\s]*(.*)")
            for p in pats:
                mm = re.search(p, flat)
                if mm:
                    return mm.group(1).strip().strip("*｜| ").strip()
            return ""
        no = g("工单号")
        if not re.match(r"^[0-9]{6,}$", no or ""):
            continue
        out["tickets"].append({
            "工单号": no,
            "开单时间": g("开单时间"),
            "故障描述": g("故障描述"),
            "解决方案": g("解决方案"),
            "企业名称": g("企业名称"),
            "SDM": g("SDM"),
        })
    # 附带信息（同一回答里就有，省一次保修问句）
    # 注意：_val 自己会补「为/*/：」分隔符，这里只能传标签本身，不能再塞冒号
    out["warranty"] = {
        "产品型号": _val(flat, r"产品型号"),
        "生产日期": _val(flat, r"生产日期"),
        "保修截止": _val(flat, r"保修截止日期") or _val(flat, r"保修到期日期"),
        "保修状态": _val(flat, r"保修状态"),
        "销售通路": _val(flat, r"销售通路"),
        "历史维修次数": _val(flat, r"历史维修次数"),
        "升级单数": _val(flat, r"升级单数"),
    }
    return out


def ticket(sn: str) -> dict:
    """查询当前进行中工单（走「查询SN：{sn} 工单」问句）。"""
    sn = (sn or "").strip().upper()
    if not sn:
        return {"ok": False, "summary": "SN 为空", "detail": {}}
    hit = _ticket_cache.get(sn)
    if hit and hit.get("ok") and time.time() - hit["at"] < TICKET_CACHE_TTL:
        d = dict(hit["data"])
        d["cache"] = True
        return d
    with _ticket_lock:                                  # 同 SN 串行，避免并发打同一问句
        hit = _ticket_cache.get(sn)
        if hit and hit.get("ok") and time.time() - hit["at"] < TICKET_CACHE_TTL:
            d = dict(hit["data"])
            d["cache"] = True
            return d
        res = ask(f"查询SN：{sn} 工单", chat_key=f"ticket-{sn}")
        if res.get("need_login"):
            ensure_session(force=True)
            res = ask(f"查询SN：{sn} 工单", chat_key=f"ticket-{sn}")
        blob = (res.get("device_info") or "") + "\n" + (res.get("answer") or "")
        if not blob.strip():
            return {"ok": False, "summary": res.get("error") or "魔方未返回工单信息", "detail": {}}
        p = parse_ticket(blob)
        items = p["tickets"]
        if p["count"] is None and not items:
            # 既没数量也没明细：不判成功、不缓存（与保修同一纪律）
            return {"ok": False, "summary": "魔方返回内容无法解析工单信息（已丢弃，未缓存）",
                    "detail": {"原文": blob[:1200]}}
        cnt = p["count"] if p["count"] is not None else len(items)
        if items:
            summary = f"{cnt} 个进行中 · {items[0]['工单号']}"
            if items[0].get("开单时间"):
                summary += f"（{items[0]['开单时间']} 开单）"
        else:
            summary = "无进行中工单"
        data = {"ok": True, "cache": False,
                "summary": summary,
                "detail": {"进行中工单数": cnt, "工单明细": items or "无进行中工单",
                           "附带保修": p["warranty"], "原文": blob[:2000]},
                "count": cnt, "tickets": items, "warranty": p["warranty"]}
        _ticket_cache[sn] = {"at": time.time(), "ok": True, "data": data}
        return data

def status() -> dict:
    tok = bool((_state.get("cookies") or {}).get("fastgpt_token"))
    return {"online": tok, "user": USER, "base": BASE, "last_check": _state.get("last_check"),
            "last_login": _state.get("last_login"), "login_fail": _state.get("login_fail"),
            "note": _state.get("note"), "ocr_ready": _OCR_OK,
            "cached_sn": len(_cache), "now": int(time.time())}


def keepalive_loop(stop: threading.Event, interval: int = KEEPALIVE):
    """后台守在线上：定期 tokenLogin 校验；失效自动重新登录。"""
    while not stop.wait(5):
        try:
            ok = validate()
            if not ok:
                ensure_session(force=True)
        except Exception:
            pass
        if stop.wait(max(60, interval)):
            return


_load_state()
