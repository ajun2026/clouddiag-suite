#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clouddiag-profile —— 二线控制台「整机档案」数据源（魔方服务适配）

只监听 127.0.0.1，供同机的 clouddiag-server 调用；对外不可达。
鉴权：Authorization: Bearer <PROFILE_TOKEN>（主服务 .env 里的 PROFILE_*_TOKEN）

接口（返回给主服务的就是 {summary, detail} 契约，主服务负责补 configured/ok/fetched_at）：
  GET /warranty?sn=SN   保修信息
  GET /repair?sn=SN     历史维修记录
  GET /factory?sn=SN    出厂配置（IPS 装箱单）
  GET /health           会话在线状态（不含账号密码）
"""
from __future__ import annotations

import asyncio
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse


def _load_dotenv():
    """极简 .env 加载（不引入 python-dotenv 依赖）：KEY=VALUE，忽略 # 注释。"""
    here = os.path.dirname(os.path.abspath(__file__))
    fp = os.path.join(here, ".env")
    if not os.path.exists(fp):
        return
    with open(fp, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

import mofang  # noqa: E402
import asp  # noqa: E402  —— 必须在读 .env 之后导入（模块级读取环境变量）

TOKEN = os.getenv("PROFILE_TOKEN", "")
PORT = int(os.getenv("PROFILE_PORT", "8081"))

app = FastAPI(title="clouddiag-profile", docs_url=None, redoc_url=None)
_sn_locks: dict[str, threading.Lock] = {}
_sn_locks_guard = threading.Lock()


def _auth(authorization: str | None):
    if not TOKEN:
        raise HTTPException(status_code=500, detail="服务未配置 PROFILE_TOKEN")
    got = (authorization or "").replace("Bearer ", "").strip()
    if got != TOKEN:
        raise HTTPException(status_code=401, detail="unauthorized")


def _lock(sn: str) -> threading.Lock:
    with _sn_locks_guard:
        return _sn_locks.setdefault(sn, threading.Lock())


async def _run(fn, sn: str, key: str = "") -> dict:
    """同一 SN + 同一类别串行执行，避免并发把 50 秒的配置查询打两遍。
    保修/维修共用一次查询（同一把锁），出厂配置独立一把锁，两者可并行。"""
    sn = (sn or "").strip().upper()
    if not sn:
        return {"ok": False, "summary": "缺少 SN", "detail": {}}
    lk = _lock(sn + "|" + key)
    loop = asyncio.get_event_loop()
    def job():
        with lk:
            try:
                return fn(sn)
            except Exception as e:                     # 兜底：绝不 500
                return {"ok": False, "summary": f"查询异常：{type(e).__name__}", "detail": {}}
    return await loop.run_in_executor(None, job)


@app.get("/warranty")
async def warranty(sn: str = Query(""), authorization: str | None = Header(None)):
    _auth(authorization)
    return JSONResponse(await _run(mofang.warranty, sn))


@app.get("/repair")
async def repair(sn: str = Query(""), authorization: str | None = Header(None)):
    _auth(authorization)
    return JSONResponse(await _run(mofang.repair, sn))


@app.get("/factory")
async def factory(sn: str = Query(""), authorization: str | None = Header(None)):
    _auth(authorization)
    return JSONResponse(await _run(mofang.factory, sn, key="factory"))


@app.get("/asp_warranty")
async def asp_warranty(sn: str = Query(""), authorization: str | None = Header(None)):
    """联想官网 ASP：SN 有效性 + 保修状态 + 机型/MTM/生产日期。官网不可用返回 503。"""
    _auth(authorization)
    sn = (sn or "").strip().upper()
    loop = asyncio.get_event_loop()
    try:
        data = await loop.run_in_executor(None, asp.check, sn)
    except asp.ASPUnavailable as e:
        return JSONResponse({"ok": False, "valid": False, "unavailable": True,
                             "message": f"无法连接联想官网：{e}"}, status_code=503)
    except Exception as e:
        return JSONResponse({"ok": False, "valid": False, "unavailable": True,
                             "message": f"校验异常：{type(e).__name__}"}, status_code=503)
    return JSONResponse({"ok": True, **data})


@app.get("/asp_profile")
async def asp_profile(sn: str = Query(""), authorization: str | None = Header(None)):
    """官网档案（给二线台「整机档案」做补充源）：返回主服务契约 {ok, summary, detail}。
    只提供机型/MTM/生产日期/保修起止/出厂配置简称——工单与 BOM 仍由魔方提供。"""
    _auth(authorization)
    sn = (sn or "").strip().upper()
    loop = asyncio.get_event_loop()
    try:
        d = await loop.run_in_executor(None, asp.check, sn)
    except asp.ASPUnavailable as e:
        return JSONResponse({"ok": False, "summary": f"联想官网不可用：{e}", "detail": {}},
                            status_code=503)
    except Exception as e:
        return JSONResponse({"ok": False, "summary": f"官网档案异常：{type(e).__name__}", "detail": {}},
                            status_code=503)
    if not d.get("valid"):
        return JSONResponse({"ok": False, "summary": d.get("message") or "官网未查询到该主机编号",
                             "detail": {"SN": sn}})
    end = d.get("warranty_end") or "—"
    summary = (f"{d.get('machine') or ''} · 在保（至 {end}）" if d.get("in_warranty")
               else f"{d.get('machine') or ''} · 已过保（{end}）")
    detail = {
        "机型": d.get("machine"),
        "MTM": d.get("mtm"),
        "生产日期": d.get("product_date"),
        "保修起始": d.get("warranty_start"),
        "保修截止": end,
        "出厂配置简称": d.get("config_desc") or "",
        "服务产品": d.get("services") or [],
        "口径": ("在保" if d.get("in_warranty") else "已过保"),
        "来源": "联想官网 ASP",
    }
    return JSONResponse({"ok": True, "summary": summary.strip(), "detail": detail})


@app.get("/health")
async def health():
    st = mofang.status()
    return {"ok": bool(st.get("online")), **st, "asp": asp.status()}


@asynccontextmanager
async def _lifespan(_app):
    mofang._load_state()
    stop = threading.Event()
    threading.Thread(target=mofang.keepalive_loop, args=(stop,), daemon=True).start()
    yield
    stop.set()


app.router.lifespan_context = _lifespan


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
