# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— **存档层 stats 域**（B17，2026-09-14）。

真源：宿主 `game/store/stats.py`（逐字端口：正文一字未改，**只动「取件」**）。
宿主 `game/store/stats.py` 现在只剩一层**委托薄壳**（`from content.persistence.stats import *`）。

| 真源写法 | 包内替身 | 为什么 |
|---|---|---|
| `from .connection import _connect, _lock[, atomic]` | `from .handles import ...` | 连接/锁/事务三个句柄由**注入面**给（宿主工厂注入 db_path） |
| `from .. import content as C` | `from .handles import C`（`_HostMod("content")`） | 包内禁 import 宿主（I2）；宿主内容面走既有句柄约定 |
| 函数内 `from ..<宿主模块> import <名>` | `_host_attr("…", "…")` / `_host_attrs(...)` | 同位置、调用时解析（与真源「函数内惰性 import」同刻） |
| `time.time()` | `clock()` | 时钟是四个注入点之一（默认 = stdlib `time.time`，行为零变化） |

**注入面**：`content/persistence/handles.py`（`bind(db_path=…, clock=…, flush_log=…, lock=…)`）；
宿主装配点 = `game/store/store_factory.py`。纯包环境（编辑器）需注入自己的句柄 —— 见 B19/B20 接点。
"""
from .handles import _connect, _lock

"""奥兰迪亚·余烬纪年存储层 - stats"""

# B2 加固（2026-08-10）：stats 表可 bump 列白名单（qq_id/day_date 为 TEXT 不参与 +1 不列入）。
STAT_FIELDS = {
    "kills", "elite_kills", "boss_kills", "deaths", "day_kills", "visited_areas",
    "inst_clears", "party_count", "fish_count", "gather_count", "mine_count",
    "cook_count", "alchemy_count", "craft_count", "enhance_count",
    "enchant_count", "world_events", "catch_collect", "chests_opened",
}


def init_stats(group_id, qq_id):
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO stats (qq_id) VALUES (?)", (qq_id,)
            )
            conn.commit()
        finally:
            conn.close()

def bump_stats(group_id, qq_id, **fields):
    bad = [k for k in fields if k not in STAT_FIELDS]
    if bad:  # B2 加固（2026-08-10）：动态列名前白名单校验
        raise ValueError(f"bump_stats 非法字段: {bad}（不在 stats 表白名单）")
    with _lock:
        conn = _connect()
        try:
            sets = ", ".join(f"{k}={k}+?" for k in fields)
            conn.execute(
                f"UPDATE stats SET {sets} WHERE qq_id=?",
                (*fields.values(), qq_id),
            )
            conn.commit()
        finally:
            conn.close()

def get_stats(group_id, qq_id):
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT * FROM stats WHERE qq_id=?", (qq_id,)
            ).fetchone()
            return dict(row) if row else {}
        finally:
            conn.close()

def set_achievement(group_id, qq_id, ach_key, progress, claimed=0):
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "INSERT INTO achievements (qq_id, ach_key, progress, claimed) VALUES (?,?,?,?) "
                "ON CONFLICT(qq_id, ach_key) DO UPDATE SET progress=excluded.progress, claimed=excluded.claimed",
                (qq_id, ach_key, progress, claimed),
            )
            conn.commit()
        finally:
            conn.close()

def get_achievements(group_id, qq_id):
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT * FROM achievements WHERE qq_id=?", (qq_id,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()



__all__ = [
    "_connect",
    "_lock",
    "STAT_FIELDS",
    "init_stats",
    "bump_stats",
    "get_stats",
    "set_achievement",
    "get_achievements",
]
