# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— **存档层 quests 域**（B17，2026-09-14）。

真源：宿主 `game/store/quests.py`（逐字端口：正文一字未改，**只动「取件」**）。
宿主 `game/store/quests.py` 现在只剩一层**委托薄壳**（`from content.persistence.quests import *`）。

| 真源写法 | 包内替身 | 为什么 |
|---|---|---|
| `from .connection import _connect, _lock[, atomic]` | `from .handles import ...` | 连接/锁/事务三个句柄由**注入面**给（宿主工厂注入 db_path） |
| `from .. import content as C` | `from .handles import C`（`_HostMod("content")`） | 包内禁 import 宿主（I2）；宿主内容面走既有句柄约定 |
| 函数内 `from ..<宿主模块> import <名>` | `_host_attr("…", "…")` / `_host_attrs(...)` | 同位置、调用时解析（与真源「函数内惰性 import」同刻） |
| `time.time()` | `clock()` | 时钟是四个注入点之一（默认 = stdlib `time.time`，行为零变化） |

**注入面**：`content/persistence/handles.py`（`bind(db_path=…, clock=…, flush_log=…, lock=…)`）；
宿主装配点 = `game/store/store_factory.py`。纯包环境（编辑器）需注入自己的句柄 —— 见 B19/B20 接点。
"""
import json, datetime
from .handles import _connect, _lock

"""奥兰迪亚·余烬纪年存储层 - quests"""


def expire_daily(quest_data):
    """v94 每日任务跨天清理：daily 里 _date 不是今天 → 清空 daily 返回 True。

    调用方（daily 领取/战斗结算）在返回 True 后需 save_quests 落库。
    旧存档没有 _date 字段 → 视为跨天（清空重领），避免玩家被旧任务卡住。
    """
    daily = quest_data.get("daily") or {}
    if not daily:
        return False
    if daily.get("_date") == datetime.date.today().isoformat():
        return False
    quest_data["daily"] = {}
    return True


def get_quests(group_id, qq_id):
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT * FROM quests WHERE qq_id=?", (qq_id,)
            ).fetchone()
            if not row:
                # v104 M19：新档主线默认 q1_1（旧 "q1" 是已下线 id，quest_view 查不到会面板空白）
                return {"main_quest": "q1_1", "main_status": "pending", "main_progress": {}, "daily": {}, "completed_main": [], "side": {}}
            q = dict(row)
            q["main_progress"] = json.loads(q["main_progress"] or "{}")
            q["daily"] = json.loads(q["daily"] or "{}")
            q["completed_main"] = json.loads(q["completed_main"] or "[]")
            q["main_status"] = q.get("main_status") or "pending"
            q["side"] = json.loads(q["side"] or "{}")
            return q
        finally:
            conn.close()

def save_quests(group_id, qq_id, quest_data):
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "INSERT INTO quests (qq_id, main_quest, main_status, main_progress, daily, completed_main, side) VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(qq_id) DO UPDATE SET main_quest=excluded.main_quest, main_status=excluded.main_status, main_progress=excluded.main_progress, daily=excluded.daily, completed_main=excluded.completed_main, side=excluded.side",
                (
                    qq_id,
                    quest_data.get("main_quest"),
                    quest_data.get("main_status"),
                    json.dumps(quest_data.get("main_progress", {}), ensure_ascii=False),
                    json.dumps(quest_data.get("daily", {}), ensure_ascii=False),
                    json.dumps(quest_data.get("completed_main", []), ensure_ascii=False),
                    json.dumps(quest_data.get("side", {}), ensure_ascii=False),
                ),
            )
            conn.commit()
        finally:
            conn.close()



__all__ = [
    "json",
    "datetime",
    "_connect",
    "_lock",
    "expire_daily",
    "get_quests",
    "save_quests",
]
