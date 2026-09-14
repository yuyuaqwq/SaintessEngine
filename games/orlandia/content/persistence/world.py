# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— **存档层 world 域**（B17，2026-09-14）。

真源：宿主 `game/store/world.py`（逐字端口：正文一字未改，**只动「取件」**）。
宿主 `game/store/world.py` 现在只剩一层**委托薄壳**（`from content.persistence.world import *`）。

| 真源写法 | 包内替身 | 为什么 |
|---|---|---|
| `from .connection import _connect, _lock[, atomic]` | `from .handles import ...` | 连接/锁/事务三个句柄由**注入面**给（宿主工厂注入 db_path） |
| `from .. import content as C` | `from .handles import C`（`_HostMod("content")`） | 包内禁 import 宿主（I2）；宿主内容面走既有句柄约定 |
| 函数内 `from ..<宿主模块> import <名>` | `_host_attr("…", "…")` / `_host_attrs(...)` | 同位置、调用时解析（与真源「函数内惰性 import」同刻） |
| `time.time()` | `clock()` | 时钟是四个注入点之一（默认 = stdlib `time.time`，行为零变化） |

**注入面**：`content/persistence/handles.py`（`bind(db_path=…, clock=…, flush_log=…, lock=…)`）；
宿主装配点 = `game/store/store_factory.py`。纯包环境（编辑器）需注入自己的句柄 —— 见 B19/B20 接点。
"""
import json
import time

from saintess_engine.container import Slots

from .handles import _connect, _lock, atomic, clock
from .inventory import _slim, _trim_individuals, FISH_TAGS_MAX, _snapshot_one
from .handles import C

"""奥兰迪亚·余烬纪年存储层 - world"""


def bump_fishing(group_id, qq_id, n=1):
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "INSERT INTO fishing (qq_id, total) VALUES (?,?) "
                "ON CONFLICT(qq_id) DO UPDATE SET total=total+?",
                (qq_id, n, n),
            )
            conn.commit()
        finally:
            conn.close()

def get_fishing_total(group_id, qq_id):
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT total FROM fishing WHERE qq_id=?", (qq_id,)
            ).fetchone()
            return row["total"] if row else 0
        finally:
            conn.close()


def bump_bestiary(group_id, qq_id, monster, n=1):
    """v46：怪物名/ID 统一存怪物 ID(monster 参数兼容名字或 m_xxx id)"""
    mon_id = C.resolve("monsters", monster)
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "INSERT INTO bestiary (qq_id, monster, kills) VALUES (?,?,?) "
                "ON CONFLICT(qq_id, monster) DO UPDATE SET kills=kills+?",
                (qq_id, mon_id, n, n),
            )
            conn.commit()
        finally:
            conn.close()

def get_bestiary(group_id, qq_id):
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT monster, kills FROM bestiary WHERE qq_id=? ORDER BY kills DESC",
                (qq_id,),
            ).fetchall()
            out = []
            for r in rows:
                out.append({"monster": r["monster"],
                            "name": C.display("monsters", r["monster"]),
                            "kills": r["kills"]})
            return out
        finally:
            conn.close()


def add_visited(group_id, qq_id, map_id):
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO visited (qq_id, map_id) VALUES (?,?)",
                (qq_id, map_id),
            )
            conn.commit()
        finally:
            conn.close()

def get_visited_count(group_id, qq_id):
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM visited WHERE qq_id=?",
                (qq_id,),
            ).fetchone()
            return row["c"] if row else 0
        finally:
            conn.close()


# ==================== v115 探索见闻：子区域级到访 visited_subareas ====================
# 与 visited 表（地图级）同构但按"地图:子区域"粒度记录；group_id 仅作兼容保留（同 add_visited）。

def add_visited_subarea(group_id, qq_id, map_id, sa_id):
    """记录子区域到访（INSERT OR IGNORE：幂等，不重复计数）。"""
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO visited_subareas (qq_id, map_id, sa_id, first_at) VALUES (?,?,?,?)",
                (qq_id, map_id, sa_id, int(clock())),
            )
            conn.commit()
        finally:
            conn.close()

def get_visited_subareas(qq_id) -> set:
    """返回该玩家已到访问的子区域集合 {"map_id:sa_id", ...}。"""
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT map_id, sa_id FROM visited_subareas WHERE qq_id=?",
                (qq_id,),
            ).fetchall()
            return {f"{r['map_id']}:{r['sa_id']}" for r in rows}
        finally:
            conn.close()

def get_visited_subareas_rows(qq_id) -> list:
    """v168 冒险手册：子区域到访明细行 [{map_id, sa_id, first_at}, ...]（按 first_at 升序）。"""
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT map_id, sa_id, first_at FROM visited_subareas WHERE qq_id=? ORDER BY first_at",
                (qq_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

def count_visited_subareas(qq_id) -> int:
    """子区域到访总数（全大陆 visited_subareas 记录条数）。"""
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM visited_subareas WHERE qq_id=?",
                (qq_id,),
            ).fetchone()
            return row["c"] if row else 0
        finally:
            conn.close()


def get_world_event(include_expired: bool = False):
    """返回当前活动事件(未过期)，无则 None；include_expired=True 时返回最近一条(含过期)"""
    with _lock:
        conn = _connect()
        try:
            now = int(clock())
            if include_expired:
                row = conn.execute(
                    "SELECT * FROM world_event ORDER BY id DESC LIMIT 1"
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM world_event WHERE ends_at > ? ORDER BY id DESC LIMIT 1", (now,)
                ).fetchone()
            if not row:
                return None
            e = dict(row)
            e["data"] = json.loads(e.get("data") or "{}")
            return e
        finally:
            conn.close()

def save_world_event(etype, ends_at, data: dict):
    with _lock:
        conn = _connect()
        try:
            conn.execute("DELETE FROM world_event")
            conn.execute(
                "INSERT INTO world_event (etype, starts_at, ends_at, data) VALUES (?,?,?,?)",
                (etype, int(clock()), int(ends_at), json.dumps(data, ensure_ascii=False)),
            )
            conn.commit()
        finally:
            conn.close()

def clear_world_event():
    with _lock:
        conn = _connect()
        try:
            conn.execute("DELETE FROM world_event")
            conn.commit()
        finally:
            conn.close()

def get_event_state(key: str):
    with _lock:
        conn = _connect()
        try:
            row = conn.execute("SELECT value FROM event_state WHERE key=?", (key,)).fetchone()
            return row["value"] if row else None
        finally:
            conn.close()

def set_event_state(key: str, value):
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO event_state (key, value) VALUES (?,?)",
                (key, str(value)),
            )
            conn.commit()
        finally:
            conn.close()

def delete_event_state(key: str):
    """删除事件状态(v62 注销确认用)"""
    with _lock:
        conn = _connect()
        try:
            conn.execute("DELETE FROM event_state WHERE key=?", (key,))
            conn.commit()
        finally:
            conn.close()


# ---------- v65 NPC 多轮对话状态 ----------
# 会话状态（当前正在跟谁聊、聊到哪个节点）：event_state key = talk_{gid}_{qid}
# 对话 flag（聊过什么/彩蛋解锁，跨会话持久）：event_state key = talkflags_{gid}_{qid}

def talk_state_key(group_id, qq_id):
    return f"talk_{group_id}_{qq_id}"

def talk_flags_key(group_id, qq_id):
    return f"talkflags_{group_id}_{qq_id}"

def get_talk_state(group_id, qq_id):
    """返回当前对话会话 {"npc": id, "node": id} 或 None"""
    raw = get_event_state(talk_state_key(group_id, qq_id))
    if not raw:
        return None
    try:
        import json
        return json.loads(raw)
    except (ValueError, TypeError):
        return None

def set_talk_state(group_id, qq_id, npc_id, node_id):
    """保存对话会话"""
    import json
    set_event_state(talk_state_key(group_id, qq_id),
                    json.dumps({"npc": npc_id, "node": node_id}, ensure_ascii=False))

def clear_talk_state(group_id, qq_id):
    """结束对话(删除会话，flag 保留)"""
    delete_event_state(talk_state_key(group_id, qq_id))

def get_talk_flags(group_id, qq_id, npc_id):
    """该 NPC 已设置的对话 flag 列表"""
    raw = get_event_state(talk_flags_key(group_id, qq_id))
    if not raw:
        return []
    try:
        import json
        data = json.loads(raw)
        return list(data.get(npc_id, []))
    except (ValueError, TypeError):
        return []

def set_talk_flag(group_id, qq_id, npc_id, flag):
    """给该 NPC 设置对话 flag(幂等)"""
    import json
    key = talk_flags_key(group_id, qq_id)
    raw = get_event_state(key)
    data = {}
    if raw:
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            data = {}
    lst = list(data.get(npc_id, []))
    if flag not in lst:
        lst.append(flag)
    data[npc_id] = lst
    set_event_state(key, json.dumps(data, ensure_ascii=False))

def get_boss_dmg_mult(qq_id) -> float:
    """世界 Boss 伤害倍率（gm_伤害 设置，默认 1.0）。"""
    try:
        return float(get_event_state(f"boss_dmg_{qq_id}") or 1)
    except (ValueError, TypeError):
        return 1.0


# v104 M24 P2-5：流失玩家残留 event_state 键的全局过期清理。
# 键内嵌 qq_id 的后缀键（每日运势/对话会话/移动模式/物品查看模式/Boss 伤害倍率）
# 只随注销路径清理，流失玩家（>N 天未活跃）的键永久残留 → 启动时统一清扫。
# 注意：talkflags_（跨会话彩蛋解锁，持久保留）、prof_daily_（按天键，短生命周期）等
# 不在清理名单内；无玩家关联的键（deed_owner_ 等）也不动。
_EVENT_STATE_PLAYER_PREFIXES = (
    "daily_fortune_",  # daily_fortune_{gid}_{qid}
    "talk_",           # talk_{gid}_{qid}（talkflags_ 不以 "talk_" 开头，天然豁免）
    "boss_dmg_",       # boss_dmg_{qid}
    "move_mode:",      # move_mode:{qid}
    "item_view_mode:", # item_view_mode:{qid}
)

def _event_state_key_qq(key: str):
    """从上述五类后缀键中提取内嵌 qq_id；无法识别返回 None。"""
    if key.startswith("move_mode:") or key.startswith("item_view_mode:"):
        return key.split(":", 1)[1]
    if key.startswith("boss_dmg_"):
        return key.split("_", 2)[2]
    if key.startswith("daily_fortune_"):
        return key.split("_", 3)[3]
    if key.startswith("talk_"):
        return key.split("_", 2)[2]
    return None

def cleanup_stale_event_state(max_age_days: int = 30) -> int:
    """清理 >max_age_days 天未活跃玩家的五类残留 event_state 键。
    幂等；返回删除的键数（0 = 无可清理/无表）。"""
    cutoff = int(clock()) - max_age_days * 86400
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT qq_id FROM players WHERE last_active < ?", (cutoff,)
            ).fetchall()
            if not rows:
                return 0
            inactive = {r["qq_id"] for r in rows}
            keys = [
                r["key"] for r in conn.execute("SELECT key FROM event_state").fetchall()
                if r["key"].startswith(_EVENT_STATE_PLAYER_PREFIXES)
            ]
            doomed = [k for k in keys if _event_state_key_qq(k) in inactive]
            if doomed:
                conn.executemany("DELETE FROM event_state WHERE key=?", [(k,) for k in doomed])
                conn.commit()
            return len(doomed)
        finally:
            conn.close()


# ==================== F1 P0-2 家具仓库原子存取 ====================
# 仓库状态存 event_state JSON（命令层 _home_storage_load/save），原命令层写成
# 读改写 + db.remove_item/add_item 分两次提交——并发双请求会互踩（各读到旧 list
# 都 append/pop，后者覆盖前者）。改为 store 层单事务：同一事务内 读当前 storage
# JSON → 校验/改列表 → 写回 event_state → 扣/加背包。item_key 已由命令层归一化。

def _storage_upsert(conn, qq_id, item_key, item_data, count):
    """事务连接上的背包加/累计一格（语义对齐 inventory.add_item 退化累加）。

    v126.3 瘦身：入包前 _slim（水合快照 → 只留个体 tags，类属性不落库）；
    背包已有同 key 且新旧都带 tags 时合并（旧 tags + 新 tags，
    FISH_TAGS_MAX 截断丢最旧）；无新 tags 时保留旧数据（旧 tags 不丢），
    不变量 len(tags) <= count 恒成立。
    """
    slim = _slim(item_key, item_data or {})
    row = conn.execute(
        "SELECT count, item_data FROM inventory WHERE qq_id=? AND item_key=?",
        (qq_id, item_key),
    ).fetchone()
    if row:
        _old = json.loads(row["item_data"]) if row["item_data"] else {}
        if not isinstance(_old, (dict, list)):
            _old = {}
        if isinstance(slim, dict) and slim.get("tags") is not None:
            _old_tags = _old.get("tags", []) if isinstance(_old, dict) else (
                _old if isinstance(_old, list) else [])
            _new_tags = (_old_tags + slim["tags"])[-FISH_TAGS_MAX:]
            # v126.4 审计 P2：保留 slim 非 tags 字段（配置未命中动态物的类属性兜底）
            _new_data = {k: v for k, v in slim.items() if k != "tags"}
            _new_data["tags"] = _new_tags
        else:
            _new_data = _old
        conn.execute(
            "UPDATE inventory SET item_data=?, count=count+? WHERE qq_id=? AND item_key=?",
            (json.dumps(_new_data, ensure_ascii=False), count, qq_id, item_key),
        )
    else:
        conn.execute(
            "INSERT INTO inventory (qq_id, item_key, item_data, count) VALUES (?,?,?,?)",
            (qq_id, item_key, json.dumps(slim, ensure_ascii=False), count),
        )


def _storage_remove(conn, qq_id, item_key, count=1):
    """事务连接上的背包扣减；不足/不存在返回 False（计入回滚条件）。

    v126.3 部分扣减时同步 _trim_individuals 截断 tags（FIFO：先扣的先删个体
    标记），不变量 len(tags) <= count 恒成立。
    """
    row = conn.execute(
        "SELECT count, item_data FROM inventory WHERE qq_id=? AND item_key=?",
        (qq_id, item_key),
    ).fetchone()
    if not row:
        return False
    if row["count"] <= count:
        conn.execute("DELETE FROM inventory WHERE qq_id=? AND item_key=?", (qq_id, item_key))
    else:
        _new = _trim_individuals(
            json.loads(row["item_data"]) if row["item_data"] else {}, count)
        if not isinstance(_new, (dict, list)):
            _new = {}
        conn.execute(
            "UPDATE inventory SET count=count-?, item_data=? WHERE qq_id=? AND item_key=?",
            (count, json.dumps(_new, ensure_ascii=False), qq_id, item_key),
        )
    return True


def home_storage_deposit_atomic(group_id, qq_id, storage_key, item_key, item_data, max_slots):
    """原子存仓：单事务内 读当前 storage→容量校验→append→写回→扣背包。
    返回 (ok, storage_len)。超容量返回 (False, -1)。

    容器形状（有序格子 + 容量 + 容错载入 + JSON 往返）在框架
    `saintess_engine.container.Slots`；事务边界与「扣背包」仍是本游戏的事。
    """
    with atomic() as conn:
        raw = conn.execute("SELECT value FROM event_state WHERE key=?", (storage_key,)).fetchone()
        lst = Slots.load(raw["value"] if raw else None, max_slots=max_slots)
        if lst.is_full():
            return False, -1
        # v126.4 审计 P1：存仓按 1 件流转，快照只带 1 条个体 tags（防整堆快照回流
        # 破坏 len(tags)<=count；取回 _storage_upsert 合并 1 条与 count=1 对称）
        lst.add(item_key, _snapshot_one(item_data) or {}, 1)
        conn.execute(
            "INSERT INTO event_state (key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (storage_key, lst.dump()),
        )
        if not _storage_remove(conn, qq_id, item_key, 1):
            # 背包货不存在：回滚（不污染 storage），命令层按原语义提示
            raise ValueError("deposit item missing")
    return True, len(lst)


def home_storage_take_atomic(group_id, qq_id, storage_key, idx):
    """原子取出：单事务内 读 storage→pop 第 idx 格→写回→加背包。
    返回 (ok, item_dict) 或 (False, None)。"""
    with atomic() as conn:
        raw = conn.execute("SELECT value FROM event_state WHERE key=?", (storage_key,)).fetchone()
        lst = Slots.load(raw["value"] if raw else None)
        it = lst.take_at(idx)          # 1-based；越界 → None（框架容器保证安全）
        if it is None:
            return False, None
        conn.execute(
            "INSERT INTO event_state (key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (storage_key, lst.dump()),
        )
        _storage_upsert(conn, qq_id, it.get("key"), it.get("data"), int(it.get("count", 1)))
    return True, it



__all__ = [
    "json",
    "time",
    "Slots",
    "_connect",
    "_lock",
    "atomic",
    "_slim",
    "_trim_individuals",
    "FISH_TAGS_MAX",
    "_snapshot_one",
    "C",
    "bump_fishing",
    "get_fishing_total",
    "bump_bestiary",
    "get_bestiary",
    "add_visited",
    "get_visited_count",
    "add_visited_subarea",
    "get_visited_subareas",
    "get_visited_subareas_rows",
    "count_visited_subareas",
    "get_world_event",
    "save_world_event",
    "clear_world_event",
    "get_event_state",
    "set_event_state",
    "delete_event_state",
    "talk_state_key",
    "talk_flags_key",
    "get_talk_state",
    "set_talk_state",
    "clear_talk_state",
    "get_talk_flags",
    "set_talk_flag",
    "get_boss_dmg_mult",
    "_EVENT_STATE_PLAYER_PREFIXES",
    "_event_state_key_qq",
    "cleanup_stale_event_state",
    "_storage_upsert",
    "_storage_remove",
    "home_storage_deposit_atomic",
    "home_storage_take_atomic",
]
