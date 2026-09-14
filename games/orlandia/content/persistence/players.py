# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— **存档层 players 域**（B17，2026-09-14）。

真源：宿主 `game/store/players.py`（逐字端口：正文一字未改，**只动「取件」**）。
宿主 `game/store/players.py` 现在只剩一层**委托薄壳**（`from content.persistence.players import *`）。

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
from .handles import _connect, _lock, clock, _host_attr, _host_attrs
from .handles import C

"""奥兰迪亚·余烬纪年存储层 - players"""

# B2 加固（2026-08-10）：players 表实际列白名单（PRAGMA 验证，qq_id 为 WHERE 专用不列入）。
# update_player 的字段名必须先过此白名单再拼 SQL，防动态列名注入/拼错列。
# 加新列（含 ALTER 补列）时必须同步加进这里。
PLAYER_FIELDS = {
    "name", "class_name", "level", "exp", "gold", "hp", "mp", "max_hp", "max_mp",
    "cur_map", "equipment", "skills", "class_tier", "attr_pts", "attributes",
    "skill_points", "learned_skills", "shortcuts", "evolve_path", "skill_levels",
    "created_at", "last_active", "portals", "skill_bar", "skill_spent", "mounts",
    "learned_blueprints", "lucky_until", "deed", "apprentices", "race",
    "equipped_title", "hidden_class_unlock", "deed_lv", "cur_subarea",
    "stamina", "stamina_ts", "explore_wandering", "gender",
    "faction", "battle_prefs",
    # v140 波2：副本通关后调查——每日次数/日期（跨日归零）
    "investigate_date", "investigate_count",
    # v141 大陆隔离：玩家所在大陆 id（mainland=主大陆 / inst:<uuid>=副本实例）
    "world_id",
}


def record_player_group(qq_id, group_id):
    """记录玩家在某个群注册/活跃过(广播目标筛选)"""
    if not group_id or group_id == "private":
        return
    with _lock:
        conn = _connect()
        try:
            now = int(clock())
            conn.execute(
                "INSERT INTO player_groups (qq_id, group_id, first_seen, last_active) VALUES (?,?,?,?) "
                "ON CONFLICT(qq_id, group_id) DO UPDATE SET last_active=excluded.last_active",
                (qq_id, group_id, now, now),
            )
            conn.commit()
        finally:
            conn.close()

def get_player_groups():
    """返回所有有玩家注册/活跃过的群号列表(广播目标)"""
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT DISTINCT group_id FROM player_groups WHERE group_id != 'private'"
            ).fetchall()
            return [r["group_id"] for r in rows]
        finally:
            conn.close()

def get_group_players(group_id):
    """返回在指定群注册/活跃过的玩家 {qq_id: player}(玩家数据全局，此处按群筛选)"""
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT p.* FROM players p JOIN player_groups g ON p.qq_id=g.qq_id "
                "WHERE g.group_id=? ORDER BY p.level DESC",
                (group_id,),
            ).fetchall()
            out = {}
            for r in rows:
                p = dict(r)
                p["equipment"] = json.loads(p["equipment"] or "{}")
                # v172 真等级化存量迁移：已穿戴装备 upgrade_lv → lv 补差（与 get_player 同源）
                try:
                    for _eq_slot, _eq_d in list((p["equipment"] or {}).items()):
                        if isinstance(_eq_d, dict) and _eq_d.get("upgrade_lv"):
                            _u = int(_eq_d.get("upgrade_lv") or 0)
                            if _u > 0:
                                _eq_d["lv"] = int(_eq_d.get("lv", 0) or 0) + _u
                            _eq_d.pop("upgrade_lv", None)
                            p["equipment"][_eq_slot] = _eq_d
                except Exception:
                    pass
                p["skills"] = json.loads(p["skills"] or "[]")
                p["attributes"] = json.loads(p.get("attributes") or '{"str":0,"agi":0,"int":0,"vit":0}')
                p["learned_skills"] = json.loads(p.get("learned_skills") or "[]")
                out[p["qq_id"]] = p
            return out
        finally:
            conn.close()


def create_player(group_id, qq_id, name, class_name, base_stats, max_hp, max_mp, race="human", gender=""):
    # v98.2 默认值收敛：gold/attr_pts/stamina/出生地图 由 core.constants 提供（原写死 SQL）
    from ..constants import START_MAP, DEFAULT_GOLD, DEFAULT_ATTR_PTS, DEFAULT_STAMINA
    with _lock:
        conn = _connect()
        try:
            now = int(clock())
            conn.execute(
                "INSERT INTO players (qq_id, name, class_name, level, exp, gold, hp, mp, max_hp, max_mp, cur_map, class_tier, attr_pts, attributes, created_at, last_active, race, gender, stamina, stamina_ts) "
                "VALUES (?,?,?,1,0,?,?,?,?,?,?,0,?,'{\"str\":0,\"agi\":0,\"int\":0,\"vit\":0}',?,?,?,?,?,?) "
                # v105 M24 P2-7：ON CONFLICT 分支不更新 name/class_name/race/gender——并发/异常路径
                # 重复 create 不得覆盖既有角色职业名（正常路径 player.py register 已拦截，冲突只可能来自并发）
                "ON CONFLICT(qq_id) DO UPDATE SET last_active=excluded.last_active",
                (qq_id, name, class_name, DEFAULT_GOLD, max_hp, max_mp, max_hp, max_mp,
                 START_MAP, DEFAULT_ATTR_PTS, now, now, race, gender, DEFAULT_STAMINA, now),
            )
            conn.commit()
        finally:
            conn.close()
    record_player_group(qq_id, group_id)

def _jload(raw, default):
    """JSON 字段安全解析（v105 M01#8）：空串/None/'null'/损坏内容/类型不符 → 默认值。
    旧代码 `json.loads(x or default)` 挡不住字符串 'null'（解析出 None 后下游 .items()/.values() 全崩）。"""
    if not raw:
        return default
    try:
        v = json.loads(raw)
    except Exception:
        return default
    return v if isinstance(v, type(default)) else default


def get_player(group_id, qq_id):
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT * FROM players WHERE qq_id=?", (qq_id,)
            ).fetchone()
            if not row:
                return None
            p = dict(row)
            p["equipment"] = _jload(p["equipment"], {})
            # v172 真等级化存量迁移：已穿戴装备 upgrade_lv → lv 补差（读档即迁移，
            # 写回 equipment= 时落库；与 inventory._hydrate 的背包迁移同源）
            try:
                for _eq_slot, _eq_d in list((p["equipment"] or {}).items()):
                    if isinstance(_eq_d, dict) and _eq_d.get("upgrade_lv"):
                        _u = int(_eq_d.get("upgrade_lv") or 0)
                        if _u > 0:
                            _eq_d["lv"] = int(_eq_d.get("lv", 0) or 0) + _u
                        _eq_d.pop("upgrade_lv", None)
                        p["equipment"][_eq_slot] = _eq_d
            except Exception:
                pass
            p["skills"] = _jload(p["skills"], [])
            p["attributes"] = _jload(p.get("attributes"), {"str": 0, "agi": 0, "int": 0, "vit": 0})
            p["learned_skills"] = _jload(p.get("learned_skills"), [])
            # v46：learned_skills 存档为技能 ID，读入内存转回技能名（battle 层用名字查定义）
            p["learned_skills"] = [C.display("skills", s) if s else s for s in p["learned_skills"]]
            p["shortcuts"] = _jload(p.get("shortcuts"), {})
            p["skill_levels"] = _jload(p.get("skill_levels"), {})
            # v46：skill_levels 键名同样转回技能名
            p["skill_levels"] = {C.display("skills", k) if k else k: v for k, v in p["skill_levels"].items()}
            p["mounts"] = _jload(p.get("mounts"), {})
            # v139 战前指令偏好（形态预设/终结阈值/蓄力档位）——JSON dict，缺省空
            p["battle_prefs"] = _jload(p.get("battle_prefs"), {})
            p["learned_blueprints"] = _jload(p.get("learned_blueprints"), [])
            # v81 导师进修：apprentices 已拜师副业列表（JSON 数组）
            p["apprentices"] = _jload(p.get("apprentices"), [])
            p["hidden_class_unlock"] = _jload(p.get("hidden_class_unlock"), [])
            # v94 #41：读取时 clamp 存量档 hp/mp 超上限（升级漏传 race 导致 max 差 1 的遗留档）
            try:
                mx_hp = p.get("max_hp") or 0
                mx_mp = p.get("max_mp") or 0
                if mx_hp and (p.get("hp") or 0) > mx_hp:
                    p["hp"] = mx_hp
                if mx_mp and (p.get("mp") or 0) > mx_mp:
                    p["mp"] = mx_mp
            except Exception:
                pass
            # v94 体力系统：惰性自然恢复（vF3 起每 5 分钟 +1，封顶 100+等级×2；v166 改 1 分钟 +1）。
            # 仅在 stamina < 上限时触发——测试档 stamina=999999 不会被拉回上限。
            try:
                _max_st = 100 + (p.get("level") or 1) * 2
                _st = p.get("stamina")
                if _st is None or not isinstance(_st, (int, float)) or isinstance(_st, bool):
                    # v105 O60：脏数据防御——stamina 空串/非法类型（E1 列错位事件曾写入 ''）
                    # 只处理 None 挡不住 ''（'' < int 抛 TypeError 被吞，体力恢复静默失效）
                    _st = 100
                    p["stamina"] = 100
                _ts = p.get("stamina_ts") or 0
                if _st < _max_st and not _ts:
                    # v95.11：存量档 stamina_ts=0（v94 前建档，ALTER 补列默认 0）→ 补记时间戳，
                    # 最多折算 10 点恢复量，避免体力耗尽后永久卡死（铁拳 0/110 卡死根因）
                    _ts = int(clock()) - C.STAMINA_RECOVER_INTERVAL * max(0, min(10, _max_st - _st))
                if _st < _max_st and _ts:
                    _now = int(clock())
                    _gain = (_now - _ts) // C.STAMINA_RECOVER_INTERVAL  # 每 1 分钟 1 点（v166）
                    if _gain > 0:
                        _new = min(_max_st, _st + _gain)
                        p["stamina"] = _new
                        conn.execute(
                            "UPDATE players SET stamina=?, stamina_ts=? WHERE qq_id=?",
                            (_new, _now, qq_id),
                        )
                        conn.commit()
            except Exception:
                pass
            # v105 O60：读档 cur_subarea 兜底——脏数据（如 E1 事件的 '{}'）回退当前地图首个子区域，
            # 否则位置渲染"你身处【{}】"+ 移动/探索全链路异常（home_ 等无子区域图保持原值）
            try:
                _sa0 = p.get("cur_subarea")
                _cur0 = p.get("cur_map", "")
                _sas0 = C.SUBAREAS.get(_cur0) or []
                if _sas0 and (_sa0 not in [s["id"] for s in _sas0]):
                    p["cur_subarea"] = _sas0[0]["id"]
            except Exception:
                pass
            # v141 大陆隔离：读档 world_id 兜底——旧存档无该列/脏数据一律回退主大陆
            # （副本实例大陆 world_id 只在开本期间存在；读档看到 inst: 前缀但大陆已销毁 → 回主大陆）
            try:
                _wid = p.get("world_id")
                if not _wid or not isinstance(_wid, str):
                    p["world_id"] = "mainland"
            except Exception:
                p["world_id"] = "mainland"
            # v95.7 #26：读档惰性结算经验溢出（面板曾出现 100% 不升级，要打一场才结算）
            # 任务奖励等路径若漏查升级，读档时自动补算并写回（升级回满血/给属性点技能点）
            # v95.12 #143：惰性升级的 logs 不能丢——挂到 p["_lv_logs"]，由 check_player_level_up 消费
            # （否则战斗结算重读 player 后 check 拿不到升级提示，玩家看不到"恭喜升级/属性点+3"）
            try:
                _lv0 = p.get("level", 1)
                if p.get("exp", 0) >= C.exp_to_next(_lv0):
                    from ..gameplay_rules import check_player_level_up
                    # v105 P1(M01#11)：惰性升级前注入称号加成——升级重算 max_hp/max_mp 缺
                    # 称号加成会写低上限（存档 861 vs 面板 891，回血回不满永久复发）。
                    # 全 store 共用 connection._lock（已改 RLock），此处可安全调用 store 函数。
                    try:
                        from ..stat_bonus import stat_bonus
                        p["_title_bonus"] = stat_bonus(group_id, qq_id, p)
                    except Exception:
                        p["_title_bonus"] = {}
                    _logs, _p2 = check_player_level_up(group_id, qq_id, p)
                    if _p2.get("level", 1) > _lv0:
                        conn.execute(
                            "UPDATE players SET level=?, exp=?, hp=?, mp=?, max_hp=?, max_mp=?, "
                            "attr_pts=?, skill_points=? WHERE qq_id=?",
                            (_p2["level"], _p2["exp"], _p2["hp"], _p2["mp"],
                             _p2["max_hp"], _p2["max_mp"],
                             _p2.get("attr_pts", 0), _p2.get("skill_points", 0), qq_id),
                        )
                        conn.commit()
                        p["_lv_logs"] = _logs  # 升级提示暂存，供调用方展示
            except Exception:
                pass
            # v151 职业技能重构：一次性技能重置（鱼鱼拍板——旧技能全清返还技能点）
            # 纯 v151 新表替换后，旧技能 key 查不到定义 → 检测到即重置：
            #   清空 learned_skills/skill_levels，skill_spent 返还 skill_points，标记防重复。
            try:
                if not p.get("_v151_skill_reset"):
                    from ..skills import skill_info
                    _cls = p.get("class_name") or ""
                    _stale = [s for s in (p.get("learned_skills") or []) if s and not skill_info(_cls, s)]
                    if _stale:
                        _refund = int(p.get("skill_spent") or 0)
                        _new_sp = int(p.get("skill_points") or 0) + _refund
                        # 清空已学/等级/花费，返还技能点
                        conn.execute(
                            "UPDATE players SET learned_skills=?, skill_levels=?, skill_spent=0, "
                            "skill_points=?, shortcuts=?, skill_bar=? WHERE qq_id=?",
                            (json.dumps([]), json.dumps({}), _new_sp,
                             json.dumps({}), json.dumps([]), qq_id),
                        )
                        conn.commit()
                        p["learned_skills"] = []
                        p["skill_levels"] = {}
                        p["skill_spent"] = 0
                        p["skill_points"] = _new_sp
                        p["shortcuts"] = {}
                        p["skill_bar"] = []
                        p["_v151_skill_reset_log"] = (len(_stale), _refund)
                    p["_v151_skill_reset"] = True
            except Exception:
                pass
            return p
        finally:
            conn.close()

def find_player_by_name(name: str):
    """按名字查找玩家(玩家跨群共用，只按名字查)。返回 {qq_id, name} 或 None"""
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT qq_id, name FROM players WHERE name=?", (name,)
            ).fetchone()
            if not row:
                return None
            return {"qq_id": row["qq_id"], "name": row["name"]}
        finally:
            conn.close()

def update_player(group_id, qq_id, **fields):
    """通用更新。fields: hp/mp/exp/gold/level/cur_map/equipment/skills/name/max_hp/max_mp"""
    if not fields:
        return
    # v87.6 内容下沉子区域：cur_map 变更且未显式指定子区域时，自动补目标图首个子区域
    # （保证玩家总有 cur_subarea 落点；home_ 等无子区域图保持原值）
    if "cur_map" in fields and "cur_subarea" not in fields:
        _sas = C.SUBAREAS.get(fields["cur_map"]) or []
        if _sas:
            fields["cur_subarea"] = _sas[0]["id"]
    with _lock:
        conn = _connect()
        try:
            sets = []
            vals = []
            for k, v in fields.items():
                if k not in PLAYER_FIELDS:
                    raise ValueError(f"update_player 非法字段: {k}（不在 players 表列白名单）")
                if k in ("equipment", "skills", "learned_skills", "shortcuts", "skill_levels", "mounts", "learned_blueprints", "apprentices", "hidden_class_unlock", "battle_prefs"):
                    # v46：技能名列表/技能等级表 写入时转 ID（存档只存 ID）
                    if k in ("learned_skills", "skills") and isinstance(v, list):
                        v = [C.resolve("skills", s) if s else s for s in v]
                    elif k == "skill_levels" and isinstance(v, dict):
                        v = {C.resolve("skills", kk) if kk else kk: vv for kk, vv in v.items()}
                    # 注意（v110 审计）：attributes/portals 也在 PLAYER_FIELDS 白名单但不在本
                    # 自动序列化分支——调用方必须先 json.dumps 预序列化，传原始 dict/list 会
                    # 撞 SQLite 绑定报错（现全部调用方均预序列化，此处仅为陷阱提示）
                    v = json.dumps(v, ensure_ascii=False)
                sets.append(f"{k}=?")
                vals.append(v)
            vals += [int(clock()), qq_id]
            conn.execute(
                f"UPDATE players SET {', '.join(sets)}, last_active=? WHERE qq_id=?",
                vals,
            )
            conn.commit()
        finally:
            conn.close()
    record_player_group(qq_id, group_id)

def top_players(group_id, limit=10):
    """全服强者榜(跨群)：玩家数据全局，排行不按群过滤。group_id 仅作兼容参数"""
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT p.name, p.class_name, p.level, p.exp FROM players p "
                "ORDER BY p.level DESC, p.exp DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

def all_players(group_id):
    """返回全部玩家(全局)——group_id 仅作兼容参数"""
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute("SELECT * FROM players ORDER BY level DESC").fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def get_portals(qq_id) -> list:
    """已激活的祭坛地图 id 列表"""
    with _lock:
        conn = _connect()
        try:
            row = conn.execute("SELECT portals FROM players WHERE qq_id=?", (qq_id,)).fetchone()
            if not row or not row["portals"]:
                return []
            try:
                return json.loads(row["portals"])
            except (ValueError, TypeError):
                return []
        finally:
            conn.close()

def add_portal(qq_id, map_id):
    """激活一座祭坛(幂等)"""
    with _lock:
        conn = _connect()
        try:
            row = conn.execute("SELECT portals FROM players WHERE qq_id=?", (qq_id,)).fetchone()
            lst = []
            if row and row["portals"]:
                try:
                    lst = json.loads(row["portals"])
                except (ValueError, TypeError):
                    lst = []
            if map_id not in lst:
                lst.append(map_id)
                conn.execute("UPDATE players SET portals=? WHERE qq_id=?", (json.dumps(lst), qq_id))
                conn.commit()
                return True
            return False
        finally:
            conn.close()


def get_skill_bar(qq_id) -> list:
    """技能栏 6 槽(技能 ID 列表，空槽为 None)；旧档技能名自动转 ID"""
    with _lock:
        conn = _connect()
        try:
            row = conn.execute("SELECT skill_bar FROM players WHERE qq_id=?", (qq_id,)).fetchone()
            if not row or not row["skill_bar"]:
                return []
            try:
                bar = json.loads(row["skill_bar"])
                if not isinstance(bar, list):
                    return []
                # v46：旧档技能名 → 技能 ID，再统一转回名字（内存层用名字）
                return [C.display("skills", C.resolve("skills", s)) if s else None for s in bar]
            except (ValueError, TypeError):
                return []
        finally:
            conn.close()

def set_skill_bar(qq_id, bar: list):
    """保存技能栏(自动补齐 6 槽)；v46 统一存技能 ID"""
    padded = list(bar) + [None] * max(0, 6 - len(bar))
    padded = padded[:6]
    # v46：技能名 → ID
    padded = [C.resolve("skills", s) if s else None for s in padded]
    with _lock:
        conn = _connect()
        try:
            conn.execute("UPDATE players SET skill_bar=? WHERE qq_id=?", (json.dumps(padded), qq_id))
            conn.commit()
        finally:
            conn.close()


# B2 加固（2026-08-10）：注销角色时按 qq_id 清理的关联表白名单。
# 新增表（且该表有 qq_id 列）时必须同步加进这里，否则注销会残留数据。
# event_state 无 qq_id 列，按键后缀 {prefix}_{qq} / {prefix}:{qq} 存储，在 delete_player 内单独清理。
# 注（v110 审计）：guild_members/feedback 亦有 qq_id 列但不在常量——guild_members 由
# delete_player 内手动处理（退会/解散），feedback 有意保留历史（含原 qq 绑定，不清理）。
DELETE_TABLES = (
    "inventory", "quests", "battle_state", "achievements", "stats",
    "reputation", "signin", "fishing", "bestiary", "visited",
    "player_groups", "professions", "pets", "props_use", "pet_dex",
)

def _delete_player_event_state(conn, qq_id):
    """删除该玩家的全部 event_state 键（v104 修复：注销后模式/状态残留导致重注册串状态）。

    键格式：{prefix}_{qq_id}（daily_fortune_{群}_{qq}/talk_{群}_{qq}/boss_dmg_{qq}/
    del_confirm_{qq} 等）或 {prefix}:{qq_id}（move_mode:/item_view_mode:）。
    全量取出后在 Python 侧精确后缀匹配（避免 SQL LIKE 的 _ 通配符误伤相邻 qq 键），
    全局键（server_maintenance/gm_whitelist/last_event_end 等）不含该后缀，天然不受影响。
    """
    qid = str(qq_id)
    suf_under, suf_colon = "_" + qid, ":" + qid
    keys = [r["key"] for r in conn.execute("SELECT key FROM event_state").fetchall()]
    matched = [k for k in keys if k.endswith(suf_under) or k.endswith(suf_colon)]
    # v110 修复：收拢匹配键后单次 executemany，消除逐条 DELETE 的 N 次往返。
    if matched:
        conn.executemany("DELETE FROM event_state WHERE key=?", [(k,) for k in matched])

def delete_player(qq_id):
    """注销角色：删除玩家主记录 + 全部关联数据（v62 群友想切职业）。

    清理表：inventory / quests / battle_state / achievements / stats /
    reputation / signin / fishing / bestiary / visited / player_groups /
    professions / pets / props_use / pet_dex / market(卖出) / party(队长或队员)
    / guild_members(退会；会长则解散公会) / feedback(历史意见保留、不清理)
    / event_state(按键后缀精确匹配，v104 补)。
    返回是否删除成功（False = 该 qq 无角色）。
    """
    with _lock:
        conn = _connect()
        try:
            row = conn.execute("SELECT qq_id FROM players WHERE qq_id=?", (qq_id,)).fetchone()
            if not row:
                return False
            for tbl in DELETE_TABLES:  # 白名单本身即约束：表名只能来自此常量
                conn.execute(f"DELETE FROM {tbl} WHERE qq_id=?", (qq_id,))
            # 事件状态：键后缀匹配清理（move_mode:/item_view_mode:/daily_fortune_/talk_ 等）
            _delete_player_event_state(conn, qq_id)
            # 市场：下架该玩家挂的单
            conn.execute("DELETE FROM market WHERE seller=?", (qq_id,))
            # 队伍：删掉该玩家所在行（队长行也删，队自动散）
            conn.execute("DELETE FROM party WHERE member=?", (qq_id,))
            conn.execute("DELETE FROM party WHERE leader=?", (qq_id,))
            # 公会：退出公会；若为会长则解散公会
            g = conn.execute("SELECT gid FROM guild_members WHERE qq_id=?", (qq_id,)).fetchone()
            if g:
                gid = g["gid"]
                conn.execute("DELETE FROM guild_members WHERE qq_id=?", (qq_id,))
                remain = conn.execute("SELECT COUNT(*) AS c FROM guild_members WHERE gid=?", (gid,)).fetchone()["c"]
                if remain == 0:
                    conn.execute("DELETE FROM guilds WHERE gid=?", (gid,))
            # 玩家主记录最后删（外键约束兜底顺序无关，SQLite 默认无外键）
            conn.execute("DELETE FROM players WHERE qq_id=?", (qq_id,))
            conn.commit()
            return True
        finally:
            conn.close()



__all__ = [
    "json",
    "time",
    "_connect",
    "_lock",
    "C",
    "PLAYER_FIELDS",
    "record_player_group",
    "get_player_groups",
    "get_group_players",
    "create_player",
    "_jload",
    "get_player",
    "find_player_by_name",
    "update_player",
    "top_players",
    "all_players",
    "get_portals",
    "add_portal",
    "get_skill_bar",
    "set_skill_bar",
    "DELETE_TABLES",
    "_delete_player_event_state",
    "delete_player",
]
