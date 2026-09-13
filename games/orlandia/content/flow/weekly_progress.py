# -*- coding: utf-8 -*-
"""包内周常进度域（`content/flow/weekly_progress.py`）—— 真源 `game/services/weekly_progress.py`（93 行）逐字端口。

真源（游戏仓 `qqbot/data/plugins/dragonfall`，**只读**）
--------------------------------------------------------
| 真源 | 行数 | 本文件搬什么 |
|---|---:|---|
| `game/services/weekly_progress.py` | 93 | **全文件**：周状态族 `_week_key/_week_state/_save_week_state` + `_grant_rewards` + `weekly_bump_kill` |
| `game/commands/weekly.py:49 _assign_week` | — | 一并搬入（发布面板的任务构造，读悬赏池 = 内容逻辑；命令层只留拼文案） |
| `game/data/weekly_quests.py:152/155` | — | 两个常量：`WEEKLY_PICK`（每周发布条数）/ `WEEKLY_MIN_LV`（解锁等级） |

宿主耦合替身（**只改两类东西**：① 存储层 import 口 ② 读表口）
--------------------------------------------------------------
| 真源写法 | 包内写法 | 说明 |
|---|---|---|
| `from .. import db` + `db.get_event_state(k)` / `db.set_event_state(k, v)` | 模块级 `db` = **惰性宿主代理** `_HostDB`（属性访问时才解析宿主模块） | 正文里 `db.xxx(...)` **一行未改**；宿主由 `bind_host(db)` 注入，或按 `sys.modules` 找**已加载**的宿主模块（绝不 import，防在包侧另起一份宿主模块树） |
| `from ..reward import grant_reward`（函数内 import） | `grant_reward = _host_grant_reward()` | 同一分发：注入优先，否则取宿主 `game.reward` 模块 |
| `from .. import content as C` + `C.WEEKLY_QUESTS`（`game/commands/weekly.py:56/135`） | `weekly_pool()` —— 读包内 `content/data/weekly_quests.json` | **域文件单源**；按条目 `seq`（= 源列表插入序，导出期注入）还原顺序 |
| 模块常量 `_WEEKLY_PICK = 3` / `_WEEKLY_MIN_LV = 50`（命令层硬编码） | `WEEKLY_PICK` / `WEEKLY_MIN_LV` = `_CFG.const("weekly_quests", …)` | ★ B9-L7：常量不再是包内字面量，改读 `game_config` 域（真源 `game/data/weekly_quests.py:152/155`，导出器 `b9_l7_domains.py:derive_game_config`） |

顺序不变式（**渲染逐字等价的关键**）
------------------------------------
`WEEKLY_QUESTS` 真源是 **list**：`_assign_week` 取「按等级过滤后的**前 3 条**」、
`weekly_list` 按**插入序**分页。包域是 dict 且外层键按字典序落盘 →
导出期给每条注入了 `seq`（1 基下标），本文件 `weekly_pool()` 按 `seq` 还原源序。
少了这一步，玩家看到的悬赏发布顺序 / 分页顺序会变（文案逐字变）。

返回结构（与真源逐字段一致）
----------------------------
`_week_key(qq_id)` → `weekly_{qq_id}_{ISO年}-W{周:02d}`；`_week_state(qq_id)` → dict|None
（缺 records → None；坏 JSON → None；`tasks`/`done_n` 补默认）——与真源一字不差。

用法::

    from content.flow import weekly_progress as WP
    WP.bind_host(db, grant_reward)          # 宿主薄壳注入（游戏仓 game/services/weekly_progress.py）
    st = WP._week_state(qq_id)
    lines = WP.weekly_bump_kill(group_id, qq_id, monster)
"""
from __future__ import annotations

import datetime
import json
import os

# 包内常量读口（B9-L7：WEEKLY_PICK / WEEKLY_MIN_LV 改读 `game_config` 常量域，不再自带副本）
from .. import config as _CFG

# ============================================================
# 宿主替身口（① 存储层 / 发放函数）
# ============================================================
_HOST_DB = None            # 宿主存储层（真源 `from .. import db`）
_HOST_GRANT = None         # 宿主发放函数（真源 `from ..reward import grant_reward`）

# 宿主模块名（运行时 `main.py` 的模块路径 = `data.plugins.dragonfall`；测试同样）
_HOST_PKG = "data.plugins.dragonfall.game"
_HOST_PKG_FALLBACK = "game"


def bind_host(db=None, grant_reward=None):
    """宿主替身注入（幂等；宿主薄壳在 import 期调用）。`db` = 存储层模块（四动词），`grant_reward` = 可调用。"""
    global _HOST_DB, _HOST_GRANT
    if db is not None:
        _HOST_DB = db
    if grant_reward is not None:
        _HOST_GRANT = grant_reward


def _resolve_host(mod: str):
    """取宿主子模块：注入优先 → 已加载的宿主模块（`sys.modules`，**不 import**）。"""
    import sys
    for name in (f"{_HOST_PKG}.{mod}", f"{_HOST_PKG_FALLBACK}.{mod}"):
        m = sys.modules.get(name)
        if m is not None:
            return m
    raise RuntimeError(f"weekly_progress：宿主模块 {mod} 不可用（未 bind_host 且未加载）—— 拒绝静默空跑")


class _HostDB:
    """惰性宿主存储层代理（真源 `from .. import db`）——`db.xxx` 正文不动，属性访问时解析。"""

    def __getattr__(self, name):
        return getattr(_HOST_DB if _HOST_DB is not None else _resolve_host("db"), name)


db = _HostDB()


def _host_grant_reward():
    """宿主发放函数（真源 `from ..reward import grant_reward`）。"""
    if _HOST_GRANT is not None:
        return _HOST_GRANT
    return getattr(_resolve_host("reward"), "grant_reward")


# ============================================================
# ② 读表口：包内 `weekly_quests` 域（真源 `game/data/weekly_quests.py`）
# ============================================================
_QUEST_SRC = "game/data/weekly_quests.py:22 WEEKLY_QUESTS"
WEEKLY_PICK_SRC = "game/data/weekly_quests.py:152 WEEKLY_PICK"
WEEKLY_MIN_LV_SRC = "game/data/weekly_quests.py:155 WEEKLY_MIN_LV"

# 每周自动发布条数 / 悬赏板解锁等级 —— ★ B9-L7 起**读域**（`game_config` 域的 `weekly_quests` 组，
# 由 `scripts/export_domains/b9_l7_domains.py:derive_game_config` 从真源单向导出）：
# 包内不再有第二份数值副本；名字保持原样（宿主 `game/commands/weekly.py:60-61` re-export 这两个名字）。
WEEKLY_PICK: int = _CFG.const("weekly_quests", "WEEKLY_PICK")
WEEKLY_MIN_LV: int = _CFG.const("weekly_quests", "WEEKLY_MIN_LV")

_DOMAIN_JSON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "data", "weekly_quests.json")
_POOL = None               # 悬赏池缓存（包内域文件是静态数据；`_reload_pool` 供测试/工具换盘）


def _read_domain():
    """读包内 `content/data/weekly_quests.json` → `{悬赏名: 条目}`（缺文件/坏 JSON → 抛，不静默空池）。"""
    with open(_DOMAIN_JSON, encoding="utf-8") as f:
        tbl = json.load(f)
    if not isinstance(tbl, dict) or not tbl:
        raise RuntimeError(f"weekly_quests 域文件不可用（{_DOMAIN_JSON}）—— 空表 = 静默无悬赏")
    return tbl


def weekly_pool() -> list:
    """悬赏池 —— **源列表顺序**（按条目 `seq`，= 真源 `WEEKLY_QUESTS` 插入序）的条目 list。

    与真源 `list(C.WEEKLY_QUESTS)` 逐条等价（条目字段原样 + 导出期注入的 `seq`）。
    """
    global _POOL
    if _POOL is None:
        tbl = _read_domain()
        rows = []
        for name, ent in tbl.items():
            if not isinstance(ent, dict):
                raise RuntimeError(f"weekly_quests 域条目 {name!r} 不是 dict（{type(ent).__name__}）")
            rows.append(ent)
        seqs = [r.get("seq") for r in rows]
        if any(isinstance(s, bool) or not isinstance(s, int) for s in seqs):
            raise RuntimeError("weekly_quests 域条目缺 seq（源列表序）—— 拒绝按字典序发赏")
        rows.sort(key=lambda r: r["seq"])
        _POOL = rows
    return list(_POOL)


def _reload_pool():
    """清空悬赏池缓存（换盘/测试用）。"""
    global _POOL
    _POOL = None


# ============================================================
# 周状态族（真源逐字；只把 `db.` 的解析交给上面的代理）
# ============================================================

def _week_key(qq_id) -> str:
    """周状态 event_state key：weekly_{qq_id}_{ISO年}-W{周}（跨年自动换 key）。"""
    y, w, _wd = datetime.date.today().isocalendar()
    return f"weekly_{qq_id}_{y}-W{w:02d}"


def _week_state(qq_id):
    """读取本周状态（无记录返回 None）。"""
    raw = db.get_event_state(_week_key(qq_id))
    if not raw:
        return None
    try:
        st = json.loads(raw)
        if not isinstance(st, dict):
            return None
        st.setdefault("tasks", {})
        st.setdefault("done_n", 0)
        return st
    except Exception:
        return None


def _save_week_state(qq_id, st):
    db.set_event_state(_week_key(qq_id), json.dumps(st, ensure_ascii=False))


def _grant_rewards(group_id, qq_id, exp, gold):
    """周常达标发奖单点（与 world._settle_daily_quest 同款结算：exp/gold + 升级）。

    v174 统一抽象：走 game.reward.grant_reward（含升级结算，返回更新后 player）。
    L3-P2a：原 inst._player 刷新读无消费方，去掉 inst 参数。
    """
    grant_reward = _host_grant_reward()        # 真源：from ..reward import grant_reward
    grant_reward({"exp": int(exp), "gold": int(gold)}, group_id, qq_id)


def weekly_bump_kill(group_id, qq_id, monster) -> list:
    """击杀推进周常（L3 订阅方/击杀结算处调用；v169.2 起命令层 combat 接线已切订阅）。

    周常无『接取/交付』环节：本周已发布的任务按击杀自动 +1，达标即自动结算发奖。
    与每日任务击杀分支同构——kill_any 任意击杀 / kill_elite 精英 /
    kill_boss 区域 Boss。返回通知行列表（调用方拼入战斗结算输出）。
    """
    out = []
    try:
        st = _week_state(qq_id)
        if not st or not st.get("tasks"):
            return out
        is_elite = bool(monster.get("is_elite"))
        is_boss = bool(monster.get("is_boss"))
        changed = False
        for tname, task in list(st["tasks"].items()):
            if task.get("done"):
                continue
            need = int(task.get("need") or 0)
            obj = task.get("objective") or {}
            hit = bool(obj.get("kill_any")) or (bool(obj.get("kill_elite")) and is_elite) \
                or (bool(obj.get("kill_boss")) and is_boss)
            if not hit:
                continue
            task["prog"] = int(task.get("prog", 0) or 0) + 1
            changed = True
            if task["prog"] >= need:
                task["done"] = True
                st["done_n"] = int(st.get("done_n", 0) or 0) + 1
                _grant_rewards(group_id, qq_id, task["reward_exp"], task["reward_gold"])
                out.append(f"📜 周常『{tname}』完成！奖励：经验 +{task['reward_exp']} 金币 +{task['reward_gold']}")
                if st["done_n"] >= len(st["tasks"]):
                    out.append("🏆 本周悬赏全部完成！下周刷新后再来领新赏金～")
        if changed:
            _save_week_state(qq_id, st)
    except Exception:
        # 周常推进失败不影响战斗主流程（与成就/野王 hook 同款宽容）
        pass
    return out


# ============================================================
# 任务发布（真源 `game/commands/weekly.py:49 _assign_week` 搬入）
# ============================================================

def _assign_week(player) -> dict:
    """按玩家等级发布本周 3 条悬赏（Lv50-69 中坚池 / Lv70+ 终局池），返回任务 dict。

    池内顺序取前 3（同周全员一致更公平——避免『同一周不同人任务不同』的攀比，
    也比每日 random.sample 少一个随机调用点，不扰动战斗回归随机序列）。

    包内改动：`C.WEEKLY_QUESTS` → `weekly_pool()`（包内域文件，按源插入序）；
    `_WEEKLY_PICK` → `WEEKLY_PICK`（同值 3）。其余逐字。
    """
    lv = int(player.get("level") or 1)
    pool = [q for q in weekly_pool() if lv >= int(q.get("min_lv") or 0)]
    if len(pool) > WEEKLY_PICK:
        pool = pool[: WEEKLY_PICK]
    tasks = {}
    for q in pool:
        obj = dict(q.get("objective") or {})
        need = next((v for v in obj.values() if isinstance(v, int) and v > 0), 1)
        tasks[q["name"]] = {
            "need": need,
            "prog": 0,
            "done": False,
            "objective": obj,
            "reward_exp": int(q.get("reward_exp") or 0),
            "reward_gold": int(q.get("reward_gold") or 0),
            "desc": q.get("desc", ""),
        }
    return tasks
