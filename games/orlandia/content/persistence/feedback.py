# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— **存档层 feedback 域**（B17，2026-09-14）。

真源：宿主 `game/store/feedback.py`（逐字端口：正文一字未改，**只动「取件」**）。
宿主 `game/store/feedback.py` 现在只剩一层**委托薄壳**（`from content.persistence.feedback import *`）。

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

"""奥兰迪亚·余烬纪年存储层 - feedback"""


def add_feedback(qq_id, group_id, content):
    """记录一条玩家意见，返回意见编号"""
    from datetime import datetime
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute(
                "INSERT INTO feedback (qq_id, group_id, content, created_at, status) VALUES (?,?,?,?, 'new')",
                (qq_id, group_id, content, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

def get_feedback(status=None, limit=50):
    """查询意见；status=None 查全部，'new' 只查未处理"""
    with _lock:
        conn = _connect()
        try:
            if status:
                rows = conn.execute(
                    "SELECT id, qq_id, group_id, content, reply, created_at, status FROM feedback WHERE status=? ORDER BY id DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, qq_id, group_id, content, reply, created_at, status FROM feedback ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return rows
        finally:
            conn.close()


__all__ = [
    "_connect",
    "_lock",
    "add_feedback",
    "get_feedback",
]
