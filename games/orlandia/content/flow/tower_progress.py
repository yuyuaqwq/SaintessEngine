# -*- coding: utf-8 -*-
"""包内修炼塔进度域（`content/flow/tower_progress.py`）—— 真源 `game/services/tower_progress.py`（110 行）逐字端口。

真源（游戏仓 `qqbot/data/plugins/dragonfall`，**只读**）
--------------------------------------------------------
| 真源 | 行数 | 本文件搬什么 |
|---|---:|---|
| `game/services/tower_progress.py` | 110 | **全文件**：状态族 `_tower_key/_tower_state/_save_tower_state` + `_floor_def` + `tower_guard_on_kill` |
| `game/commands/tower.py:39 build_tower_guard` | 27 | 一并搬入（塔卫构造 = 内容逻辑：读塔表 + 放大系数；命令层只留拼文案） |

宿主耦合替身（**只改两类东西**：① 存储层 import 口 ② 读表口）
--------------------------------------------------------------
| 真源写法 | 包内写法 | 说明 |
|---|---|---|
| `from .. import db` + `db.get_event_state` / `db.set_event_state` / `db.get_player` / `db.update_player` | 模块级 `db` = **惰性宿主代理** `_HostDB`（属性访问时才解析宿主模块） | 正文里 `db.xxx(...)` **一行未改**；宿主由 `bind_host(db)` 注入，或按 `sys.modules` 找**已加载**的宿主模块（绝不 import） |
| `from .. import content as C` + 宿主聚合层 `TRIAL_FLOORS` / `TRIAL_DAILY_LIMIT` / `TRIAL_MAX_FLOOR` | `from . import tower_data as _TD` + `getattr(_TD, …)` | 塔表**逐字**落在包内 `content/flow/tower_data.py`（真源 `game/data/trial_tower.py` 整文件）；三处 `getattr` 的默认值原样保留 |
| `C.build_monster(...)`（`game/core/drops.py:389`，**未进包**） | 调用方传参 `build_monster=` | 与 `content/flow/__init__.py` 的 boss_script 同款替身；**必传**（不给默认 → 不许静默落到兜底分支） |

不变式
------
* `_floor_def(floor)` 语义不变：1 基、找不到返回 `None`（真源同款线性查找）。
* `tower_guard_on_kill` 的段序 / 幂等 / 文案一字不改（金币入账在幂等判断**之前**——真源如此，照搬）。
* `build_tower_guard` 的兜底分支（`build_monster` 抛错时手搓最小敌人）原样保留；
  只有宿主真传了 `build_monster` 才可能走到。

用法::

    from content.flow import tower_progress as TP
    TP.bind_host(db)                                     # 宿主薄壳注入（game/services/tower_progress.py）
    guard = TP.build_tower_guard(3, C.build_monster)     # 开战前构造塔卫
    lines = TP.tower_guard_on_kill(group_id, qq_id, monster)
"""
from __future__ import annotations

import datetime
import json

# 塔表（真源整文件逐字搬入：`game/data/trial_tower.py`）—— 常量按真源名 re-export 给宿主命令薄壳
from . import tower_data as _TD
from .tower_data import (  # noqa: F401  (re-export：宿主命令读门槛/上限)
    TRIAL_FLOORS, TRIAL_MIN_LV, TRIAL_MAX_FLOOR, TRIAL_DAILY_LIMIT,
)

# ============================================================
# 宿主替身口（① 存储层）
# ============================================================
_HOST_DB = None            # 宿主存储层（真源 `from .. import db`）

# 宿主模块名（运行时 `main.py` 的模块路径 = `data.plugins.dragonfall`；测试同样）
_HOST_PKG = "data.plugins.dragonfall.game"
_HOST_PKG_FALLBACK = "game"


def bind_host(db=None):
    """宿主替身注入（幂等；宿主薄壳在 import 期调用）。`db` = 存储层模块。"""
    global _HOST_DB
    if db is not None:
        _HOST_DB = db


def _resolve_host(mod: str):
    """取宿主子模块：注入优先 → 已加载的宿主模块（`sys.modules`，**不 import**）。"""
    import sys
    for name in (f"{_HOST_PKG}.{mod}", f"{_HOST_PKG_FALLBACK}.{mod}"):
        m = sys.modules.get(name)
        if m is not None:
            return m
    raise RuntimeError(f"tower_progress：宿主模块 {mod} 不可用（未 bind_host 且未加载）—— 拒绝静默空跑")


class _HostDB:
    """惰性宿主存储层代理（真源 `from .. import db`）——`db.xxx` 正文不动，属性访问时解析。"""

    def __getattr__(self, name):
        return getattr(_HOST_DB if _HOST_DB is not None else _resolve_host("db"), name)


db = _HostDB()


# ============================================================
# 状态族（真源逐字；只把 `db.` 的解析交给上面的代理）
# ============================================================

def _tower_key(qq_id) -> str:
    return f"tower_{qq_id}"


def _tower_state(qq_id):
    d = None
    raw = db.get_event_state(_tower_key(qq_id))
    if raw:
        try:
            d = json.loads(raw)
        except Exception:
            d = None
    st = {"cur": 0, "cleared_today": [], "count_today": 0, "date": ""}
    if isinstance(d, dict):
        st.update(d)
    today = datetime.date.today().isoformat()
    if st.get("date") != today:
        st["cleared_today"] = []
        st["count_today"] = 0
    st["date"] = today
    # 类型兜底（旧档脏数据防御）
    st["cleared_today"] = [int(x) for x in (st.get("cleared_today") or [])]
    try:
        st["count_today"] = int(st.get("count_today") or 0)
    except Exception:
        st["count_today"] = 0
    try:
        st["cur"] = int(st.get("cur") or 0)
    except Exception:
        st["cur"] = 0
    return st


def _save_tower_state(qq_id, st):
    db.set_event_state(_tower_key(qq_id), json.dumps(st, ensure_ascii=False))


def _floor_def(floor: int) -> dict:
    """TRIAL_FLOORS 表查找（1 基；找不到返回 None）。"""
    floors = list(getattr(_TD, "TRIAL_FLOORS", None) or [])
    for f in floors:
        if int(f.get("floor") or 0) == int(floor):
            return f
    return None


def tower_guard_on_kill(group_id, qq_id, monster) -> list:
    """塔卫被击杀 → 爬塔状态推进 + 金币结算 + 文案（L3 订阅方/combat 击杀后调用）。

    v181 L3-P2a 下沉版：原 commands/tower.py 同逻辑，签名去掉 inst（原 inst._player 读
    等价换 db.get_player——存档玩家必存在）。

    经验已由标准战斗结算按 monster.exp 发放；金币（v93 怪物 gold 不直接入账）在此
    显式 +reward_gold。返回通知行由调用方拼入结算输出。
    """
    lines = []
    try:
        mid = str(monster.get("id") or "")
        if not mid.startswith("tower_"):
            return lines
        floor = int(mid[len("tower_"):])
        fd = _floor_def(floor) or {}
        gold = int(fd.get("reward_gold") or 0)
        # 金币显式入账（v93：怪物 gold 折算材料不入账，塔的金币走这里）
        if gold > 0:
            player = db.get_player(group_id, qq_id) or {}
            db.update_player(group_id, qq_id, gold=int(player.get("gold", 0) or 0) + gold)
            lines.append(f"💰 塔层赏金：金币 +{gold}")
        st = _tower_state(qq_id)
        today_cleared = [int(x) for x in (st.get("cleared_today") or [])]
        # 幂等：同一天同层已结算过不再重复计数
        if floor in today_cleared:
            return lines
        today_cleared.append(floor)
        st["cleared_today"] = sorted(today_cleared)
        st["count_today"] = len(today_cleared)
        st["cur"] = max(int(st.get("cur") or 0), floor)
        _save_tower_state(qq_id, st)
        lines.append(f"🏯 第 {floor} 层【{fd.get('name') or ''}】突破！")
        left = max(0, int(getattr(_TD, "TRIAL_DAILY_LIMIT", 3) or 3) - st["count_today"])
        if floor >= int(getattr(_TD, "TRIAL_MAX_FLOOR", 30) or 30):
            lines.append("👑 你已登顶修炼塔之巅——奥兰迪亚的强者之名，当之无愧！")
        elif left > 0:
            nxt = floor + 1
            nfd = _floor_def(nxt)
            lines.append(f"💡 今日还可突破 {left} 层——回复『爬塔』挑战第 {nxt} 层"
                         + (f"【{nfd.get('name') or ''}】(建议 Lv.{nfd.get('lv')})" if nfd else ""))
        else:
            lines.append("🌙 今日修炼已满 3 层，好好消化感悟，明日再来！(失败/逃跑不占次数)")
    except Exception:
        pass
    return lines


# ============================================================
# 塔卫构造（真源 `game/commands/tower.py:39 build_tower_guard` 搬入）
# ============================================================

def build_tower_guard(floor: int, build_monster) -> dict:
    """构造第 floor 层塔卫（普通战斗敌人 dict；exp/gold = 层奖励）。

    真源 `game/commands/tower.py:39`，包内改动只有两处：
      · `_floor_def(floor)` 读包内塔表（`content/flow/tower_data.py`）
      · `C.build_monster(...)` → 调用方传入的 `build_monster`（真源 `game/core/drops.py:389`，未进包）
    """
    fd = _floor_def(floor) or {}
    name = fd.get("guard") or f"第{floor}层守卫"
    lv = int(fd.get("lv") or min(100, 70 + floor))
    role = fd.get("role") or "dps"
    skills = list(fd.get("skills") or [])
    fake_map = {"id": "trial_tower", "name": "修炼塔", "lv": lv, "area": "tower"}
    try:
        guard = build_monster((f"tower_{floor}", name, role, lv, skills, []), fake_map)
    except Exception:
        # build_monster 失败兜底：手搓最小敌人（防数据漂移导致爬塔不可玩）
        guard = {
            "id": f"tower_{floor}", "uid": f"e_tower_{floor}", "name": name, "lv": lv,
            "role": role, "rank": 1, "reach": 1,
            "defending": False, "charging": None,
            "hp": 600, "max_hp": 600, "atk": 60, "def": 30, "matk": 30, "mdef": 30,
            "spd": 12, "exp": 0, "gold": 0, "skills": [], "drops": [],
            "map": "修炼塔", "map_area": "tower", "is_boss": False, "is_elite": False,
            "mech": "", "mod": "",
        }
    # 层挑战系数（hp/atk 放大；exp/gold 覆盖为层奖励）
    guard["hp"] = max(1, int(guard.get("hp", 100) * float(fd.get("hp_mult") or 1.0)))
    guard["max_hp"] = guard["hp"]
    guard["atk"] = max(1, int(guard.get("atk", 10) * float(fd.get("atk_mult") or 1.0)))
    guard["matk"] = max(1, int(guard.get("matk", 10) * float(fd.get("atk_mult") or 1.0)))
    # v93 经济：怪物 gold 字段不直接入账（折算材料），塔的金币奖励改由
    # tower_guard_on_kill 结算时显式发放 → 怪物 gold 置 0 防白嫖材料掉落
    guard["exp"] = int(fd.get("reward_exp") or 0)
    guard["gold"] = 0
    return guard
