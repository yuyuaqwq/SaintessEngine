# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— 身份映射（openid ↔ QQ 号）**真搬进包**（B2-C4，2026-09-14）。

真源 = 游戏仓 `game/commands/_identity.py`（120 行，**逐字搬**：函数体 / 正则 / SQL / 错误行为
一字未改，只换「取件口」一行）。宿主同名文件在波2 改薄壳（B2 波1 宿主侧零改，见 `B2_COMMON.md` §0②）。

为什么必须新建（而不是复用既有模块）
------------------------------------
| 候选 | 现状（实测） | 结论 |
|---|---|---|
| `content/_pkgref.py`（B1） | 只提供**惰性包内模块句柄**（`DB` / `HANDLES` / `WORLD` / `INVENTORY` / `SOCIAL`）+ 宿主工厂一次性预热 | **职责 = 句柄层**，不含任何身份取值逻辑 ⇒ 不重叠 |
| `content/persistence/handles.py`（B17） | 存档层**注入面**：`db_path()` / `clock()` / `get_db()` / `lock()` / `connect()` / `_lock` / `_connect` | **职责 = 连接与锁**；`identity_map` 只有 DDL（`content/persistence/schema.py:258`），**没有** `openid_to_qq` / `qq_to_openid` / `bind` / `is_openid` 等取值函数 ⇒ 不重叠 |
| 宿主 `game/commands/_identity.py` | 8 个真函数只在宿主；包内**零口子**（`content/` 全树 grep `identity_map` 只有 `cmds_gm.py:264` 的一行 GM 展示查询） | ⇒ 依接口表第 1 行新建 `content/_identity.py` |

**与 `_pkgref` 的分工**：`_pkgref` 是「包内模块的惰性句柄」（解决 EAGER 装配窗口的取件时机），
本模块是「身份映射的**实现**」；本模块**不新增第二套句柄**，直接复用存档层的注入面
`content/persistence/handles`（= 宿主 `game/store/connection.py` 转发的那**同一批对象**：
`_lock` / `_connect`，见 `game/store/connection.py:17-26`）。所以包内句柄仍然只有一套。

取件对照（真源 → 包内）
----------------------
| 真源写法 | 包内写法 | 说明 |
|---|---|---|
| `from ..store import connection as _conn` | `from .persistence import handles as _conn` | 同一批对象：宿主 `connection._lock` = `handles.lock()`（真 RLock）、`connection._connect` = `handles.connect`；本模块正文里 `_conn._lock` / `_conn._connect()` **一字未改** |

行为等价证据（B2-C4）：`out/evidence/identity_parity.txt` —— 同一 `qq_id` / openid 集合，
改前（宿主 `game.commands._identity`）与改后（本模块）取到的玩家 / DB 行**逐值相同**。
"""
from __future__ import annotations

import re
import time

from .persistence import handles as _conn

# 腾讯 openid 形如：xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx（32 位十六进制，部分带 -）
# QQ 号：5-11 位纯数字
_OPENID_RE = re.compile(r"^[0-9a-fA-F]{24,40}$|^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_QQ_RE = re.compile(r"^\d{5,11}$")


def is_openid(s: str) -> bool:
    """判断字符串是不是腾讯 openid（区别于 QQ 号）。"""
    if not s:
        return False
    s = str(s).strip()
    return bool(_OPENID_RE.match(s))


def is_qq_id(s: str) -> bool:
    return bool(_QQ_RE.match(str(s).strip()))


def bind(openid: str, qq_id: str, platform: str = "qq_official") -> None:
    """绑定 openid ↔ qq_id。已存在则覆盖。"""
    openid = str(openid).strip()
    qq_id = str(qq_id).strip()
    with _conn._lock:
        conn = _conn._connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO identity_map(openid, qq_id, platform, bind_time) "
                "VALUES(?,?,?,?)",
                (openid, qq_id, platform, int(time.time())),
            )
            conn.commit()
        finally:
            conn.close()


def unbind_openid(openid: str) -> None:
    with _conn._lock:
        conn = _conn._connect()
        try:
            conn.execute("DELETE FROM identity_map WHERE openid=?", (str(openid).strip(),))
            conn.commit()
        finally:
            conn.close()


def openid_to_qq(openid: str) -> str | None:
    """openid → QQ 号；未绑定返回 None。"""
    if not is_openid(openid):
        return None
    with _conn._lock:
        conn = _conn._connect()
        try:
            row = conn.execute(
                "SELECT qq_id FROM identity_map WHERE openid=?", (openid.strip(),)
            ).fetchone()
            return str(row[0]) if row else None
        finally:
            conn.close()


def qq_to_openid(qq_id: str, platform: str = "qq_official") -> str | None:
    """QQ 号 → openid（出向投递用）；未绑定返回 None。"""
    qq_id = str(qq_id).strip()
    with _conn._lock:
        conn = _conn._connect()
        try:
            row = conn.execute(
                "SELECT openid FROM identity_map WHERE qq_id=? AND platform=? "
                "ORDER BY bind_time DESC LIMIT 1",
                (qq_id, platform),
            ).fetchone()
            return str(row[0]) if row else None
        finally:
            conn.close()


def resolve_uid(raw: str) -> str:
    """命令层统一入口：raw 若是已绑定 openid → 返回对应 QQ 号，否则原样返回。"""
    if not raw:
        return raw
    mapped = openid_to_qq(raw)
    return mapped if mapped else raw


def query_all(limit: int = 100) -> list[dict]:
    """列出全部映射（GM 查看用）。返回 [dict(openid, qq_id, platform)]。"""
    with _conn._lock:
        conn = _conn._connect()
        try:
            rows = conn.execute(
                "SELECT openid, qq_id, platform FROM identity_map "
                "ORDER BY bind_time DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
