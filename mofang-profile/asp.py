#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
联想官网 ASP 保修查询适配（api.asp.atlenovo.com）
────────────────────────────────────────────────────────────────
用途：创建诊断房间前，按 SN 快速校验「主机编号是否有效 + 是否还在保修」，并取回
      机型 / MTM / 生产日期。这是联想商用服务官网「保修配置驱动」页背后用的接口，
      无需登录、无需验证码，纯 GET。

设计要点：
  · 只做校验，不做历史工单/配置——那部分仍走魔方（IPS/SF）
  · 10 分钟缓存 + 同 SN 并发合并，避免用户连打输入把官网打爆
  · 官网不可用与「SN 无效」严格区分：前者抛 ASPUnavailable，让上层决定拦不拦
"""
from __future__ import annotations

import datetime as _dt
import os
import re
import threading
import time
from zoneinfo import ZoneInfo

import httpx

ASP_BASE = os.getenv("ASP_BASE_URL", "https://api.asp.atlenovo.com").rstrip("/")
ASP_PATH = os.getenv("ASP_DEVICE_PATH", "/asp/infomartion/v3/getDeviceInfo")  # 官网原路径（infomartion 拼写就是如此）
ASP_TIMEOUT = float(os.getenv("ASP_TIMEOUT", "5"))
ASP_RETRY = int(os.getenv("ASP_RETRY", "1"))
ASP_CACHE_TTL = int(os.getenv("ASP_CACHE_TTL", "600"))

_CACHE: dict[str, dict] = {}
_LOCK = threading.Lock()
_INFLIGHT: dict[str, threading.Lock] = {}
_TZ = ZoneInfo("Asia/Shanghai")


class ASPUnavailable(Exception):
    """官网连不上（超时/5xx/网络）——与「SN 无效」是两回事。"""


def _today() -> _dt.date:
    return _dt.datetime.now(_TZ).date()


def _norm(sn: str) -> str:
    return (sn or "").strip().upper()


def check_format(sn: str) -> tuple[bool, str]:
    """前置格式校验：6~25 位字母数字。不做"必须含字母"（服务器 SN 可能全数字，有效性交官网判）。"""
    sn = _norm(sn)
    if not sn:
        return False, "请输入主机编号"
    if len(sn) < 6 or len(sn) > 25:
        return False, "主机编号长度应为 6~25 位"
    if not sn.isalnum():
        return False, "主机编号只能包含字母和数字"
    return True, ""


def _sn_lock(sn: str) -> threading.Lock:
    with _LOCK:
        return _INFLIGHT.setdefault(sn, threading.Lock())


def _fetch(sn: str) -> dict:
    last = ""
    for attempt in range(ASP_RETRY + 1):
        try:
            with httpx.Client(base_url=ASP_BASE, timeout=httpx.Timeout(ASP_TIMEOUT, connect=ASP_TIMEOUT),
                              headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}) as c:
                r = c.get(ASP_PATH, params={"sn": sn, "_t": int(time.time())})
            if r.status_code >= 500:
                last = f"官网返回 HTTP {r.status_code}"
                continue
            if r.status_code >= 400:
                raise ASPUnavailable(f"官网返回 HTTP {r.status_code}")
            try:
                return r.json()
            except Exception:
                raise ASPUnavailable("官网返回非 JSON")
        except ASPUnavailable:
            raise
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            if attempt < ASP_RETRY:
                time.sleep(0.6)
                continue
            raise ASPUnavailable(last)
    raise ASPUnavailable(last or "官网无响应")


def check(sn: str, use_cache: bool = True) -> dict:
    """返回 {valid, in_warranty, machine, mtm, product_date, warranty_end, ...}
    官网不可用时抛 ASPUnavailable；SN 无效时返回 valid=False（不抛）。"""
    sn = _norm(sn)
    ok, why = check_format(sn)
    if not ok:
        return {"valid": False, "reason": "format", "message": why, "sn": sn}

    if use_cache:
        hit = _CACHE.get(sn)
        if hit and time.time() - hit["at"] < ASP_CACHE_TTL:
            return {**hit["data"], "cached": True}

    with _sn_lock(sn):
        hit = _CACHE.get(sn)                      # 拿到锁后再看一次：并发合并
        if use_cache and hit and time.time() - hit["at"] < ASP_CACHE_TTL:
            return {**hit["data"], "cached": True}

        js = _fetch(sn)
        status = js.get("status")
        data = js.get("data") or {}
        if status != 200 or not data:
            out = {"valid": False, "reason": "not_found", "sn": sn,
                   "message": js.get("msg") or "联想官网未查询到该主机编号",
                   "asp_status": status}
            _CACHE[sn] = {"at": time.time(), "data": out}
            return {**out, "cached": False}

        wd = data.get("warrantyDate") or {}
        ends = [wd.get(k) for k in ("warrantyEndDate", "laborEndDate", "onSiteEndDate")]
        ends = [e for e in ends if isinstance(e, str) and e.strip()]
        end = max(ends) if ends else ""
        in_warranty = False
        if end:
            try:
                in_warranty = _dt.date.fromisoformat(end) >= _today()
            except Exception:
                in_warranty = False

        services = []
        for w in (data.get("warrantyInfos") or []):
            services.append({
                "name": (w.get("serviceProductName") or "").strip(),
                "desc": (w.get("remark") or "").replace("\r\n", " ").strip(),
                "start": w.get("startDate") or "",
                "end": w.get("endDate") or "",
                "part_end": w.get("partEndDate") or "",
                "labor_end": w.get("laborEndDate") or "",
                "onsite_end": w.get("onsiteEndDate") or "",
            })

        # 出厂配置简称（官网拿法：warrantyDate.name，如 "ThinkStation P360 TWR I912900K 32G x2"）
        #   注意：2018 年前的老机型这里只返回"售后"，前端据此判断是否展示
        cfg_desc = (wd.get("name") or "").strip()
        cfg_ok = bool(cfg_desc) and cfg_desc not in ("售后", "售后保修") and bool(re.search(r"[0-9]", cfg_desc))

        out = {
            "valid": True,
            "in_warranty": in_warranty,
            "config_desc": cfg_desc if cfg_ok else "",
            "config_desc_raw": cfg_desc,
            "sn": data.get("sn") or sn,
            "machine": (data.get("machineName") or "").strip(),
            "mtm": (wd.get("mTM") or "").strip(),
            "product_date": wd.get("productDate") or "",
            "warranty_start": wd.get("warrantyStartDate") or "",
            "warranty_end": end,
            "labor_end": wd.get("laborEndDate") or "",
            "onsite_end": wd.get("onSiteEndDate") or "",
            "services": services,
            "is_server": bool(data.get("IsServerOrStorageDevice")),
            "checked_at": _dt.datetime.now(_TZ).strftime("%Y-%m-%d %H:%M:%S"),
            "source": "联想官网 ASP",
        }
        _CACHE[sn] = {"at": time.time(), "data": out}
        return {**out, "cached": False}


def status() -> dict:
    return {"asp_base": ASP_BASE, "cache_ttl": ASP_CACHE_TTL, "cached_sn": len(_CACHE),
            "timeout": ASP_TIMEOUT, "retry": ASP_RETRY}
