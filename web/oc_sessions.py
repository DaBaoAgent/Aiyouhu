# -*- coding: utf-8 -*-
"""服务端会话列表：把 OpenClaw 自己的 transcript 库当作唯一真相源。

背景：Web 侧栏原先把会话列表**只**存在浏览器 localStorage（frontend/src/lib/store.ts
的 ``easel_sessions``），服务端既不落列表也不给列表接口 —— 浏览器站点数据被清、
换浏览器/换 profile，侧栏就整表清空，而服务端的对话原文其实一条没丢。

这里把 OpenClaw agent 库（``<state>/agents/main/agent/openclaw-agent.sqlite``）
读出来，转成前端 ``ChatSession`` 能吃的形状：

    会话 id  = OpenClaw session key 去掉 ``agent:main:`` 前缀
              （正是前端自己生成、并用于续接对话的那个 id）
    messages = 按时间分轮：user 原文 + 该轮最后一条 assistant 文本（其余短句合并进 activity）

**只读**：一律 ``mode=ro`` 打开，绝不写 OpenClaw 任何状态；出错返回空表，不阻断 Web。
"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import weakref
from pathlib import Path
from typing import Any

_AGENT_REL = Path("agents") / "main" / "agent" / "openclaw-agent.sqlite"
_KEY_PREFIX = "agent:main:"

# 非 Web 会话：CLI/TUI 的 main、OpenAI 兼容端点、定时自动化 —— 不进侧栏
_SKIP_SUFFIXES = frozenset({"main", ""})
_SKIP_PREFIXES = ("cron:", "openai:")

# 前端/后端注入的固定前缀，展示时剥掉（不是用户打的话）
_PERSONA_RE = re.compile(
    r"^我当前使用的画像是「[^」]+」。本会话的账号长期记忆仅使用 [^\n]*?memory\.md[，。]?\s*"
    r"不要使用工作区全局 [A-Z]*MEMORY\.md 作为账号记忆。[^\n]*\n*"
)
_INTERNAL_MARK = "〔内部提醒"

_CACHE_TTL = 5.0            # 秒：页面加载/切页连打时避免反复读库
_CACHE_MAX_SESSIONS = 60
_MSG_CHARS_CAP = 40_000     # 单条消息保护上限（防止异常巨型消息撑爆响应）

_cache_lock = threading.Lock()
_cache: dict[str, Any] = {"at": 0.0, "data": None}


def state_dir() -> Path:
    """OpenClaw state 目录（与 easel 其余部分同一解析：支持 EASEL_OPENCLAW_STATE_DIR 覆盖）。"""
    try:
        from easel.openclaw_workspace import state_dir as _sd  # type: ignore

        return Path(_sd())
    except Exception:
        env = os.environ.get("EASEL_OPENCLAW_STATE_DIR")
        return Path(env) if env else Path.home() / ".openclaw-easel"


def agent_db_path() -> Path:
    return state_dir() / _AGENT_REL


def _connect_ro(db: Path) -> sqlite3.Connection:
    """只读打开。库在 WAL 模式且被 gateway 占着，直连失败时退化为「复制三件套再读」。"""
    try:
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=3.0)
        con.row_factory = sqlite3.Row
        con.execute("select 1 from sqlite_master limit 1")
        return con
    except sqlite3.Error:
        # 直连失败（极少见）：把 库+WAL+SHM 三件套复制出来读，读完自动清掉临时目录
        tmp = Path(tempfile.mkdtemp(prefix="easel-oc-"))
        for suffix in ("", "-wal", "-shm"):
            src = Path(str(db) + suffix)
            if src.is_file():
                shutil.copy2(src, tmp / (db.name + suffix))
        con = sqlite3.connect(str(tmp / db.name), timeout=3.0)
        con.row_factory = sqlite3.Row
        weakref.finalize(con, lambda p=tmp: shutil.rmtree(p, ignore_errors=True))
        return con


def strip_user_text(text: str) -> str:
    """剥掉注入前缀（画像长期记忆声明 / 内部提醒块），只留用户真正打的内容。"""
    if not text:
        return ""
    cut = text.find(_INTERNAL_MARK)
    if cut >= 0:
        text = text[:cut]
    text = _PERSONA_RE.sub("", text)
    return text.strip()


def _session_key_suffix(key: str | None) -> str:
    key = (key or "").strip()
    if key.startswith(_KEY_PREFIX):
        key = key[len(_KEY_PREFIX):]
    if key in _SKIP_SUFFIXES or key.startswith(_SKIP_PREFIXES):
        return ""
    return key


def _build_turns(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    """把 (role, timestamp, text) 流切成前端形状的消息序列。"""
    turns: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for r in rows:
        role = r["role"]
        text = r["text"] or ""
        if role == "user":
            current = {"user": strip_user_text(text) or text, "ass": []}
            turns.append(current)
        elif current is not None:
            if text.strip():
                current["ass"].append(text)

    messages: list[dict[str, Any]] = []
    for t in turns:
        user = (t["user"] or "").strip()
        if user:
            messages.append({"role": "user", "content": user[:_MSG_CHARS_CAP]})
        ass = [a.strip() for a in t["ass"] if a.strip()]
        if ass:
            msg: dict[str, Any] = {"role": "assistant", "content": ass[-1][:_MSG_CHARS_CAP]}
            earlier = "\n".join(ass[:-1]).strip()
            if earlier:                      # 轮内的过程短句 → 前端「执行过程」区
                msg["activity"] = earlier[:_MSG_CHARS_CAP]
            messages.append(msg)
    return messages


def _load_sessions() -> list[dict[str, Any]]:
    """读库并组装会话（不含 limit / 缓存）。"""
    db = agent_db_path()
    if not db.is_file():
        return []
    con = _connect_ro(db)
    try:
        windows = list(con.execute(
            "select session_key, session_id, created_at, updated_at, started_at from session_windows"))
        events = list(con.execute(
            "select session_id, role, timestamp, text from session_transcript_fts order by timestamp"))
    finally:
        con.close()

    suffix_of: dict[str, str] = {}
    started: dict[str, int] = {}
    for w in windows:
        suffix = _session_key_suffix(w["session_key"])
        if not suffix or not w["session_id"]:
            continue
        suffix_of[w["session_id"]] = suffix
        ts = w["created_at"] or w["started_at"] or w["updated_at"]
        if ts:
            started[suffix] = min(started.get(suffix, ts), ts)

    bag: dict[str, dict[str, Any]] = {}
    for e in events:
        suffix = suffix_of.get(e["session_id"])
        if not suffix:
            continue
        s = bag.setdefault(suffix, {"rows": [], "updated": 0})
        s["rows"].append(e)
        if e["timestamp"]:
            s["updated"] = max(s["updated"], int(e["timestamp"]))

    out: list[dict[str, Any]] = []
    for suffix, s in bag.items():
        messages = _build_turns(s["rows"])
        if not messages:
            continue
        first_user = next((m["content"] for m in messages if m["role"] == "user"), "")
        out.append({
            "id": suffix,
            "created": int(started.get(suffix) or s["updated"] or 0),
            "updated": int(s["updated"] or 0),
            "first_user": first_user,
            "messages": messages,
        })
    out.sort(key=lambda x: x["updated"], reverse=True)
    return out


def list_sessions(limit: int = _CACHE_MAX_SESSIONS, use_cache: bool = True) -> list[dict[str, Any]]:
    """服务端会话列表（新→旧）。任何异常都退化为空表，不阻断 Web。"""
    now = time.time()
    if use_cache:
        with _cache_lock:
            if _cache["data"] is not None and now - _cache["at"] < _CACHE_TTL:
                return _cache["data"][:limit]
    try:
        data = _load_sessions()[:_CACHE_MAX_SESSIONS]
    except Exception as e:                      # 库损坏/被独占/结构变化 → 空表 + 打一行日志
        print(f"[oc-sessions] 读取失败：{e}", flush=True)
        data = []
    with _cache_lock:
        _cache["at"] = now
        _cache["data"] = data
    return data[:limit]


def get_session(session_id: str) -> dict[str, Any] | None:
    """单个会话（读缓存优先，未命中直接落库）。"""
    for s in list_sessions(limit=_CACHE_MAX_SESSIONS):
        if s["id"] == session_id:
            return s
    try:
        for s in _load_sessions():
            if s["id"] == session_id:
                return s
    except Exception as e:
        print(f"[oc-sessions] 单会话读取失败：{e}", flush=True)
    return None
