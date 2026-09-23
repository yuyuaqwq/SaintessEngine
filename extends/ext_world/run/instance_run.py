# -*- coding: utf-8 -*-
"""包内副本运行态适配层（`content/flow/instance_run.py`）—— 逐字搬自游戏仓
`game/core/instance_run.py`（308 行），只改「宿主耦合 → 调用方传参」一类东西。

真源（只读）：`qqbot/data/plugins/dragonfall/game/core/instance_run.py`

宿主耦合替身接口（调用方传什么）：
| 真源宿主耦合 | 包内替身 | 调用方传什么 |
|---|---|---|
| `from .. import db` + `db.party_members(group_id, leader)`（:93-94） | `current_members(st, party)` 的 `party` 参数 | 普通 id 序列（在队伍中的成员）；无队 = 空序列。组队/平台语义留在宿主 |
| 存档 `st`（宿主持久化） | 同左 | 普通 dict；键名/类型/缺失语义**一律不变**（老存档照旧可用） |
其余（引擎形状 `Progress`/`Roster`）不变 —— 引擎可直接依赖。
"""
from __future__ import annotations


from ext_world.run import Progress, Roster

# 池名（内容侧字符串；引擎不解释它们）
POOL_UNITS = "units"          # 分层：该层待清怪物队列
POOL_MONSTERS = "monsters"    # 房间：该房间剩余怪池
POOL_POIS = "pois"            # 房间：该房间剩余调查点
BUDGET_GOLD = "gold"
BUDGET_MATS = "mats"
BUDGET_EQUIP = "equip"

# 「回地图模式」要清的战斗视图字段（三处旧实现逐字相同的那一段）
BATTLE_VIEW_KEYS = ("boss", "enemy", "enemies")


# ======================================================================
# 一、名单（Roster）
# ======================================================================


def roster_of(st: dict) -> Roster:
    """从 st 构造名单视图（不改 st）。"""
    return Roster(st.get("members") or (), leader=st.get("leader"), alive=st.get("alive"))


def write_roster(st: dict, r: Roster) -> None:
    """把名单写回 st（只改这两个键的值；键名与形状不变）。"""
    st["members"] = [str(m) for m in r.members]
    st["alive"] = r.alive_map


def alive_of(st: dict, key) -> bool:
    """成员是否存活（**缺键 = 存活**，与旧 `st[\"alive\"].get(str(m), True)` 同口径）。"""
    return roster_of(st).alive(key)


def set_alive(st: dict, key, value: bool = True) -> None:
    st.setdefault("alive", {})[str(key)] = bool(value)


def living_members(st: dict) -> list:
    """存活的成员（保序）。"""
    return roster_of(st).living()


def living_players(st: dict) -> list:
    """「存活且血 > 0」的在场成员（旧 `_router_has_living_players` 口径，保序）。"""
    players = st.get("players") or {}
    out = []
    for k in roster_of(st).living():
        if int((players.get(str(k)) or {}).get("hp", 0) or 0) > 0:
            out.append(k)
    return out


def sort_members_by(st: dict, keyfunc, *, reverse: bool = True) -> None:
    """按内容侧给的键**原位**重排 `st[\"members\"]`（旧：按速度降序重排行动序）。"""
    r = roster_of(st)
    r.sort_by(keyfunc, reverse=reverse)
    st["members"] = r.members


def current_members(st: dict, party) -> list:
    """当前仍在队伍中的副本成员（旧 `_instance_current_members` 逐字等价）。

    宿主耦合替身：真源签名 `current_members(group_id, st)`，队伍来自
    `db.party_members(group_id, leader)` —— 包内不认组队/平台，`party` 由调用方
    取好传入（普通 id 序列；无队 = 空序列）。

    - 有队伍 → `members ∩ 队伍`（保序；退队成员不再白拿奖励/不被 Boss 攻击/不被全灭误杀）
    - 单人副本（成员只有队长本人）→ [队长]
    - 其余（队伍散了且不是单人本）→ []
    """
    party = [str(m) for m in (party or ())]
    r = roster_of(st)
    if party:
        return r.only(party)
    members = r.members
    if len(members) == 1 and str(members[0]) == str(st.get("leader")):
        return [str(members[0])]
    return []


# ======================================================================
# 二、进度（Progress）：两种形态共用一个形状
# ======================================================================


def _stage_index(st: dict) -> int:
    return int(st.get("stage_idx", 0) or 0)


def stages_progress(st: dict) -> Progress:
    """分层副本 → `Progress`：每层一个节点（key = 层下标的字符串），池 `units` = 该层待清队列。

    只有**当前层**有内容（旧实现里 `stage_pending` 就是当前层的队列；
    其它层的池空着 = 尚未进入），与旧语义一致。
    """
    stages = st.get("inst_stages") or []
    nodes = [{"key": str(i), "label": (s or {}).get("name", "")} for i, s in enumerate(stages)]
    p = Progress(nodes, index=_stage_index(st))
    cur = str(_stage_index(st))
    for mon in (st.get("stage_pending") or []):
        p.push(cur, POOL_UNITS, mon)
    return p


def write_stages_progress(st: dict, p: Progress) -> None:
    """写回：`stage_idx` + `stage_pending`（只改这两个键）。"""
    st["stage_idx"] = int(p.index)
    st["stage_pending"] = p.items(str(p.index), POOL_UNITS)


def stage_count(st: dict) -> int:
    return len(st.get("inst_stages") or [])


def is_last_stage(st: dict) -> bool:
    return stages_progress(st).is_last()


def stage_name(st: dict, idx=None) -> str:
    stages = st.get("inst_stages") or []
    i = _stage_index(st) if idx is None else int(idx)
    return (stages[i] or {}).get("name", "") if 0 <= i < len(stages) else ""


def pending_left(st: dict) -> int:
    """当前层还剩几只没遭遇（旧：`len(st[\"stage_pending\"])`）。"""
    return stages_progress(st).left(str(_stage_index(st)), POOL_UNITS)


def pending_take(st: dict):
    """从当前层待清队列弹一只（旧：`pending.pop(0)`），弹完写回。空 → None。"""
    p = stages_progress(st)
    item = p.take(str(p.index), POOL_UNITS)
    if item is not None:
        write_stages_progress(st, p)
    return item


def stage_advance(st: dict, pending=None) -> bool:
    """进入下一层（旧：`stage_idx += 1` + 组装新层 pending）。末层返回 False（不动）。

    `pending` 由调用方组装（机关 skip_elite/skip_wave 等属内容规则）。
    """
    p = stages_progress(st)
    if not p.advance():
        return False
    st["stage_idx"] = int(p.index)
    st["stage_pending"] = list(pending or [])
    return True


# ---------------------------------------------------------------- 房间形态


def rooms_progress(st: dict, cur: str = None) -> Progress:
    """房间副本 → `Progress`：每房间一个节点 + 池 `monsters` / `pois`；资源池进预算。

    当前节点（`cur`，不给则取 `st["cur_subarea"]`）只是「进度当前位置」这个视图；
    所有取用操作都要显式给房间 id（`take_monster(st, sa_id)` 等），不依赖当前位置。
    ★ 注意：队伍共享的房间里 `st` 本身没有 `cur_subarea`，旧实现是从**队长玩家行**读的
    —— 需要精确的当前位置时由调用方传进来（属展示层的事）。
    """
    rooms = st.get("rooms") or {}
    nodes = [{"key": str(k)} for k in rooms]
    pools = {}
    for k, rstate in rooms.items():
        pools[str(k)] = {
            POOL_MONSTERS: list((rstate or {}).get("monsters_left") or []),
            POOL_POIS: list((rstate or {}).get("pois_left") or []),
        }
    rp = st.get("resources_pool") or {}
    budgets = {
        BUDGET_GOLD: int(rp.get("gold_left", 0) or 0),
        BUDGET_MATS: dict(rp.get("mats_left") or {}),
        BUDGET_EQUIP: list(rp.get("equip_left") or []),
    }
    p = Progress(nodes, pools=pools, budgets=budgets)
    _cur = str(cur if cur is not None else (st.get("cur_subarea") or ""))
    if _cur and not p.goto(_cur):
        p.set_index(0)
    return p


def write_rooms_progress(st: dict, p: Progress) -> None:
    """写回：`rooms[*].monsters_left` / `pois_left` + `resources_pool`（只改值）。"""
    rooms = st.setdefault("rooms", {})
    for k in p.keys:
        rstate = rooms.setdefault(k, {})
        rstate["monsters_left"] = p.items(k, POOL_MONSTERS)
        rstate["pois_left"] = p.items(k, POOL_POIS)
    rp = st.setdefault("resources_pool", {})
    rp["gold_left"] = int(p.budget(BUDGET_GOLD, 0) or 0)
    rp["mats_left"] = dict(p.budget(BUDGET_MATS, {}) or {})
    rp["equip_left"] = list(p.budget(BUDGET_EQUIP, []) or [])


def monsters_left(st: dict, sa_id: str) -> int:
    return rooms_progress(st).left(str(sa_id), POOL_MONSTERS)


def take_monster(st: dict, sa_id: str):
    """从房间怪池弹 1 只（旧 `consume_monster`：`monsters_left.pop(0)`）。空/无房间 → None。"""
    p = rooms_progress(st)
    if not p.has(str(sa_id)):
        return None
    item = p.take(str(sa_id), POOL_MONSTERS)
    if item is not None:
        write_rooms_progress(st, p)
    return item


def poi_left(st: dict, sa_id: str, poi_id: str) -> bool:
    return poi_id in rooms_progress(st).items(str(sa_id), POOL_POIS)


def take_poi(st: dict, sa_id: str, poi_id: str) -> bool:
    """把调查点移出该房间剩余表（旧：`_pois_left.remove(poi_id)`）。不在 → False。"""
    p = rooms_progress(st)
    if not p.drop(str(sa_id), POOL_POIS, poi_id):
        return False
    write_rooms_progress(st, p)
    return True


def mark_boss_room_done(st: dict, sa_id: str) -> None:
    """标记房间 Boss 已清（旧：`boss_alive=False` + `_boss_room=True`）。"""
    rstate = (st.get("rooms") or {}).get(str(sa_id))
    if rstate is None:
        return
    rstate["boss_alive"] = False
    rstate["_boss_room"] = True


def spend_gold(st: dict, want: int) -> int:
    """资源池扣金币 → **实得量（不足只给剩余）**。"""
    p = rooms_progress(st)
    got = p.spend(BUDGET_GOLD, want)
    if got:
        write_rooms_progress(st, p)
    return got


def spend_mat(st: dict, name: str) -> bool:
    """资源池扣 1 件材料（同名计数）；不够 → False。"""
    p = rooms_progress(st)
    if not p.spend_one(BUDGET_MATS, name):
        return False
    write_rooms_progress(st, p)
    return True


def spend_equip(st: dict, item_id: str) -> bool:
    """资源池移出 1 件装备；不在池中 → False。"""
    p = rooms_progress(st)
    if not p.spend_one(BUDGET_EQUIP, item_id):
        return False
    write_rooms_progress(st, p)
    return True


# ======================================================================
# 三、战斗视图收尾（router 三处逐字重复的那一段）
# ======================================================================


def clear_battle_view(st: dict, **flags) -> None:
    """清掉「战斗视图」字段并写回地图模式标志（旧三处逐字相同的那一段）。

    `flags` 里给的键原样写入（例：`stage_cleared=True, over=False`），
    未给的键不动 —— 三处旧实现在**标志上**本就不同（暗格守卫给 secret_chest、
    房间/分层给 stage_cleared），差异留给调用方显式写。
    """
    st["mode"] = "map"
    for k in BATTLE_VIEW_KEYS:
        st[k] = None if k != "enemies" else []
    st.update(flags)


def clear_pet_hits(st: dict) -> None:
    """清宠物「最近被击中」时间戳（旧三处逐字相同的那段循环）。"""
    for _m0 in list((st.get("pets") or {}).keys()):
        try:
            (st["pets"][_m0]).pop("_last_hit_at", None)
        except Exception:
            pass
