# -*- coding: utf-8 -*-
# ==============================================================================
# 包内实现（唯一真源）· B13-L2（2026-09-14）—— 逐字搬自宿主
#   `qqbot/data/plugins/dragonfall/game/core/wild_king.py`
# 搬运改动面**只有「宿主取件」**一类：9 处 `from .. import db` → `db` 替身；`C`/`drop_engine`/`data.maps`/`core.drops` → 宿主句柄；12 个 `WILD_KING*` 常数 → ★ B16-W11b 包内门面 `catalog_rules`（原 `_WK` 宿主句柄已退场）；`WILD_KINGS` → 包内域读口
# ★ B14-2 L8（2026-09-14）切包内门面：`C.ITEMS` / `C.MATERIALS` → `catalog_items`；`data.maps.MAP_BY_ID` → `catalog_space`。
# 宿主同名文件 = 薄壳（指向本模块，见那边的头注）。
# ==============================================================================
"""奥兰迪亚·余烬纪年 核心层 - wild_king.py（v140 波2：野外 Boss 看守宝箱 · 野王体系）

链路：
  任意玩家指令（_maint_gate 惰性）→ wild_king_tick() 刷新全局野王状态
  → 探索命中当前图野王 → 普通战斗（build_monster 构造野王）
  → _handle_victory 检测 monster.id 以 b_guard_ 开头 → wild_king_on_kill() 解锁宝箱+广播
  → 『摸宝箱』/『摸战利箱』指令 → wild_king_open_chest() 原子认领开箱

设计（docs/方案 3.2 节，鱼鱼原创）：
- 全服同一时刻每图至多 1 只、全服 ≤3 只（WILD_KING_GLOBAL_LIMIT，见下门面取件）
- 每日 4 时段（02/08/14/20 点）刷新：日期+时段哈希全服一致从 8 图选 1 只野王
  （哈希命中图之前已被 3 只占满时顺延到下一图，保证"全服 ≤3 只"始终成立）
- 存活超时 90 分钟自动消失（懒计时：读时校验 expired 即清理）
- 击杀 → 解锁宝箱（战利箱 15 分钟专属 → 转公共箱）
- 保底：个人连续 3 时段参与未开箱 → 第 4 时段保底券（pity 计数）；
  全服连续 2 时段野王未击杀 → 下时段刷 2 只（no_kill_streak）
- 状态存 event_state：全局键 wild_king_global（JSON），个人键 wild_king_meta_{qq_id}（JSON）

⚠️ 宿主存储经 `db = _HostMod("db")` 替身（B13-L2 搬包 2026-09-14）：正文 `db.xxx(...)`
   一字未改，属性访问时解析宿主 `game.db`；取不到**大声抛**（不静默空跑）。
"""
import datetime
import json
import random

import importlib
import os
import sys

# ============================================================
# ① 宿主替身口（B13-L2 搬包 2026-09-14；正文 `db.xxx(...)` / `C.xxx` 一行未改）
#    写法照抄包内 `content/world_cmds.py`（B9 线2）：注入优先 → sys.modules → importlib，
#    取不到**大声抛**（绝不静默空跑）。
# ============================================================
_HOST_PKG = "data.plugins.dragonfall.game"      # 运行时（main.py 的模块路径）
_HOST_PKG_FALLBACK = "game"                     # 测试/工具按 `game.xxx` 直接 import 时
_INJECTED = {}


def bind_host(**objs):
    """宿主薄壳 import 期注入（幂等）——键 = `_HostMod` 的模块名（`db` / `content`）。"""
    for k, v in (objs or {}).items():
        if v is not None:
            _INJECTED[k] = v


def _host_module(name: str):
    """取宿主子模块（`name` 为空 = 宿主 `game` 包本身，真源 `from .. import X` 那一类）。"""
    if name in _INJECTED:
        return _INJECTED[name]
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        full = prefix if not name else "%s.%s" % (prefix, name)
        m = sys.modules.get(full)
        if m is not None:
            return m
    last = None
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        try:
            return importlib.import_module(prefix if not name else "%s.%s" % (prefix, name))
        except Exception as exc:                # noqa: BLE001
            last = exc
    raise RuntimeError("B13-L2：宿主模块 %s 取不到（%s）——拒绝静默空跑" % (name, last))


def _host_attr(mod: str, attr: str):
    """宿主模块属性 —— 真源「`from ..<mod> import <attr>`」的同义替身（调用时解析）。"""
    m = _host_module(mod)
    try:
        return getattr(m, attr)
    except AttributeError:
        for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
            try:
                return importlib.import_module("%s.%s" % (
                    prefix if not mod else "%s.%s" % (prefix, mod), attr))
            except Exception:                   # noqa: BLE001
                continue
        raise


class _HostMod:
    """宿主模块替身（`db` / `C`）——`db.xxx` / `C.xxx` 正文一字未改，属性访问时解析。"""

    def __init__(self, name):
        self._name = name

    def __getattr__(self, attr):
        return getattr(_host_module(self._name), attr)

db = _HostMod("db")                     # 真源 9 处函数内 `from .. import db`
C = _HostMod("content")                 # 真源 `from .. import content as C`（残 `roll_blueprint`，见缺口）

# ★ B14-2 L8（2026-09-14）：`C.ITEMS` / `C.MATERIALS` / `data.maps.MAP_BY_ID` 三处读点
#   → 包内门面直取（B14 第一段产物；门禁 `b14_catalog_gate.py` 逐值+键序 OK）。
from . import catalog_items as _ci      # noqa: E402  ITEMS / MATERIALS
from . import catalog_space as _cs      # noqa: E402  MAP_BY_ID
# ★ B16-W11b（2026-09-14）：`WILD_KING*` 常数 → 包内门面直取（原 `_WK` 宿主句柄已退场）
from .catalog_rules import (WILD_KING_CHEST_TIERS, WILD_KING_GLOBAL_LIMIT, WILD_KING_LIFETIME_SEC,
                            WILD_KING_LOOT_PRIORITY_SEC, WILD_KING_MAPS, WILD_KING_NO_KILL_EXTRA,
                            WILD_KING_PERIODS, WILD_KING_PER_DAY_LIMIT, WILD_KING_PER_PERIOD_LIMIT,
                            WILD_KING_PITY_PERIODS)


# ============================================================
# ② 包内域读口 —— 野王名册（域 `wild_king`，导出器
#    `scripts/export_domains/monster_combat.py` → `content/data/wild_king.json`）
#    真源 `game/data/wild_king_data.py:62 WILD_KINGS`（8 只）—— 逐键 deep-equal 已验
#    （`overnight/b13l2_probe*.py`）。**不改形状**：JSON 里的值原样用。
#    其余常数（时段/候选图/宝箱档位/上限）**域内没有** → 走 `_WK` 宿主句柄（缺口登记）。
# ============================================================
_HERE = os.path.dirname(os.path.abspath(__file__))


def _read_domain(name: str) -> dict:
    """读包内 `content/data/<域>.json`（缺文件/坏 JSON → {}，与 `content/tables.py` 同款）。"""
    try:
        with open(os.path.join(_HERE, "data", "%s.json" % name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:                            # noqa: BLE001
        return {}


WILD_KINGS = _read_domain("wild_king")


def __getattr__(name):
    """PEP 562：真源顶层名兼容（`WILD_KING*` 常数 → 包内门面 `catalog_rules`，含另 2 个未直取名）。"""
    if name.startswith("WILD_KING"):
        from . import catalog_rules as _cr
        return getattr(_cr, name)
    raise AttributeError(name)

# event_state 键
GLOBAL_KEY = "wild_king_global"
META_PREFIX = "wild_king_meta_"


# ================= 日期+时段哈希（全服一致，与 wild.py _day_hash 同模式） =================
def _day_hash(seed: int, salt: str = "") -> int:
    h = seed * 2654435761 + (sum(ord(c) for c in salt) if salt else 0)
    return h & 0x7FFFFFFF


def period_hour(now: datetime.datetime | None = None) -> int:
    """当前野王时段开始小时（02/08/14/20）。"""
    now = now or datetime.datetime.now()
    h = now.hour
    if 2 <= h < 8:
        return 2
    if 8 <= h < 14:
        return 8
    if 14 <= h < 20:
        return 14
    return 20


def period_label(now: datetime.datetime | None = None) -> str:
    """当前时段中文名。"""
    now = now or datetime.datetime.now()
    ph = period_hour(now)
    for p in WILD_KING_PERIODS:
        if p["hour"] == ph:
            return p["label"]
    return "夜晚"


def period_key(now: datetime.datetime | None = None) -> str:
    """时段唯一键：YYYY-MM-DD:P（当日 02 时段归入当天凌晨，即当日第一个时段）。"""
    now = now or datetime.datetime.now()
    return f"{now.strftime('%Y-%m-%d')}:{period_hour(now)}"


# ================= 全局状态读写 =================
def _default_global() -> dict:
    return {
        "period": "",          # 当前时段键
        "spawned": False,      # 本时段是否已刷
        "kings": {},           # {map_id: king_state}
        "no_kill_streak": 0,   # 全服连续未击杀时段数（保底：2 → 下时段刷 2 只）
        "extra_count": 0,      # 下时段额外刷的只数（no_kill 保底累加）
    }


def _load_global() -> dict:
    raw = db.get_event_state(GLOBAL_KEY)
    if not raw:
        return _default_global()
    try:
        d = json.loads(raw)
        return d if isinstance(d, dict) else _default_global()
    except (ValueError, TypeError):
        return _default_global()


def _save_global(st: dict):
    db.set_event_state(GLOBAL_KEY, json.dumps(st, ensure_ascii=False))


def wild_king_state(map_id: str) -> dict | None:
    """当前地图的野王状态（未在场返回 None）。"""
    st = _load_global()
    k = st.get("kings", {}).get(map_id)
    if not k:
        return None
    # 懒计时：存活超时/跨时段 → 惰性清理（不额外定时器）
    now_ts = int(datetime.datetime.now().timestamp())
    if now_ts >= k.get("expire", 0):
        st["kings"].pop(map_id, None)
        _save_global(st)
        return None
    if k.get("period") != st.get("period"):
        st["kings"].pop(map_id, None)
        _save_global(st)
        return None
    return k


# ================= 刷新（惰性：任意指令触发 tick） =================
def _build_king(kid: str, map_id: str, period: str, extra: bool = False) -> dict:
    """构造一只野王的在场状态。"""
    kdef = WILD_KINGS[kid]
    now_ts = int(datetime.datetime.now().timestamp())
    return {
        "kid": kid,
        "name": kdef["name"],
        "icon": kdef.get("icon", "👑"),
        "map": map_id,
        "lv": kdef["lv"],
        "hp_base": kdef["hp_base"],
        "atk_mult": kdef.get("atk_mult", 1.3),
        "skills": list(kdef.get("skills", [])),
        "drops": list(kdef.get("drops", [])),
        "chest_tier": kdef.get("chest_tier", "low"),
        "desc": kdef.get("desc", ""),
        "period": period,
        "spawn_ts": now_ts,
        "expire": now_ts + WILD_KING_LIFETIME_SEC,
        "extra": bool(extra),
        "hp": None,          # 当前血量（多人共享：首次参战 build_monster 后回写）
        "max_hp": None,
        "contrib": {},       # qq -> 累计伤害
        "last_hit": None,    # 最后一击 qq
        "killed": False,
        "chest": None,       # 宝箱状态（击杀后生成）
    }


def _spawn_pick(period: str, count: int, occupied: set) -> list:
    """时段哈希从 8 图选 count 只野王（避开已被占满的图；全服 ≤3 只）。

    用『日期+时段+盐』哈希全服一致；count 只按哈希偏移递增取模，
    命中 occupied（已刷满的图）或已在 kings 的图则顺延下一张。
    """
    today = datetime.date.today()
    seed = today.toordinal() * 100 + period_hour()
    picks = []
    idx = 0
    while len(picks) < count and idx < len(WILD_KING_MAPS) * 3:
        h = _day_hash(seed, f"{period}#{idx}")
        cand = WILD_KING_MAPS[h % len(WILD_KING_MAPS)]
        idx += 1
        if cand in occupied or cand in picks:
            continue
        picks.append(cand)
    return picks


def wild_king_tick() -> dict:
    """野王全局惰性刷新。任意玩家指令触发（_maint_gate 内接入）。

    逻辑：
    1. 读全局状态；跨时段 → 重置（旧 kings 全清，02 时段强制全清）
    2. 本时段已刷 → 只做存活超时惰性清理，返回当前状态
    3. 未刷 → 按哈希选图刷 1 只（全服 ≤3 只）；no_kill_streak ≥2 → 额外刷 1 只
       （全服连续 2 时段未击杀 → 下时段 2 只，方案 3.2 保底 ②）
    返回全局状态 dict。
    """
    st = _load_global()
    pk = period_key()
    # 跨时段：重置（02 时段为每日强制重置点，任何旧 kings 一律清）
    if st.get("period") != pk:
        old = st
        st = _default_global()
        st["period"] = pk
        # no_kill 保底：上一时段有野王在场但全服未击杀（killed 全 False 且 kings 非空）
        if old.get("kings") and not any(k.get("killed") for k in old.get("kings", {}).values()):
            st["no_kill_streak"] = int(old.get("no_kill_streak", 0) or 0) + 1
        else:
            st["no_kill_streak"] = 0
        if st["no_kill_streak"] >= WILD_KING_NO_KILL_EXTRA:
            st["extra_count"] = 1  # 下时段多刷 1 只（共 2 只）
            st["no_kill_streak"] = 0
        _save_global(st)
    if st.get("spawned"):
        # 惰性清理过期/跨时段残留
        now_ts = int(datetime.datetime.now().timestamp())
        changed = False
        for mid in list(st.get("kings", {}).keys()):
            k = st["kings"][mid]
            if now_ts >= k.get("expire", 0) or k.get("period") != pk:
                st["kings"].pop(mid, None)
                changed = True
        if changed:
            _save_global(st)
        return st
    # 本时段首次：刷新
    occupied = set(st.get("kings", {}).keys())
    active = len([k for k in st.get("kings", {}).values() if k.get("killed") is not True])
    budget = WILD_KING_GLOBAL_LIMIT - active
    count = 1 + int(st.get("extra_count", 0) or 0)
    count = max(1, min(count, budget))
    if count <= 0:
        st["spawned"] = True
        _save_global(st)
        return st
    for map_id in _spawn_pick(pk, count, occupied):
        # 每图一只：已刷过本时段的图不再刷
        if map_id in st["kings"]:
            continue
        # 从该图的野王池抽一只（哈希全服一致）
        pool = [kid for kid, kdef in WILD_KINGS.items() if kdef["map"] == map_id]
        if not pool:
            continue
        h = _day_hash(datetime.date.today().toordinal(), f"{pk}#{map_id}")
        kid = pool[h % len(pool)]
        st["kings"][map_id] = _build_king(kid, map_id, pk)
    st["extra_count"] = 0
    st["spawned"] = True
    _save_global(st)
    return st


# ================= 探索检测 =================
def explore_king(group_id: str, qq_id: str, map_id: str) -> dict | None:
    """探索时检测当前图是否有野王在场。返回 king_state（未在场 None）。

    只做展示/入口提示，不消耗探索（与野外 NPC 偶遇同级）。
    """
    wild_king_tick()
    return wild_king_state(map_id)


# ================= 击杀结算（combat._handle_victory 接入） =================
def build_king_monster(king: dict, map_obj: dict, player: dict) -> dict:
    """把野王状态构造为战斗怪物 dict（build_monster 同款结构，供普通战斗链路）。

    血量 = hp_base × (1 + 0.5×(参战人数-1))：首人参战 hp_base 基准，
    后续参战玩家累计参战人数（存 king['participants']），保持多人弹性。
    """
    build_monster = _host_attr("core.drops", "build_monster")  # noqa: E402（宿主真源，drops 未进包）
    # 参战人数：首人参战记 1；已有参战记录则 +1
    participants = int(king.get("participants", 0) or 0)
    king["participants"] = participants + 1
    lv = int(king.get("lv", 30))
    kdef = WILD_KINGS.get(king.get("kid"), {})
    # 构造 6 元组怪物定义（boss role → 血量按 boss 模板再乘 hp_mult）
    mon_def = (king.get("kid"), king.get("name"), "boss", lv,
               king.get("skills") or kdef.get("skills", []),
               king.get("drops") or kdef.get("drops", []))
    monster = build_monster(mon_def, map_obj)
    # 野王专属数值：血量 = hp_base × 弹性；攻击 = 同级精英 ×1.3（方案 3.2 安全标定）
    mult = 1.0 + 0.5 * max(0, int(king.get("participants", 0) or 0) - 1)
    hp = max(1000, int(king.get("hp_base", 0) * mult))
    monster["hp"] = hp
    monster["max_hp"] = hp
    atk_mult = float(king.get("atk_mult", 1.3) or 1.3)
    for ak in ("atk", "matk"):
        if isinstance(monster.get(ak), (int, float)):
            monster[ak] = int(monster[ak] * atk_mult)
    # 回写全局当前血量（多人共享；后续玩家 build 时按现血恢复）
    king["hp"] = hp
    king["max_hp"] = hp
    monster["_wild_king"] = True
    monster["_wk_map"] = king.get("map", "")
    return monster


def _resolve_map_name(map_id: str) -> str:
    MAP_BY_ID = _cs.MAP_BY_ID            # B14-2 L8：包内门面（真源 `data.maps.MAP_BY_ID`，逐值+键序 OK）
    m = MAP_BY_ID.get(map_id, {})
    return m.get("name", map_id)


def wild_king_on_kill(group_id: str, qq_id: str, monster: dict, damage: int = 0,
                      last_hit: bool = True) -> list:
    """野王死亡结算（combat._handle_victory 接入）：解锁宝箱 + 记录贡献 + 广播。

    返回广播文本列表（命令层负责 _broadcast）。重复调用幂等（killed 标记）。
    """
    kid = monster.get("id", "")
    map_id = monster.get("_wk_map", "") or ""
    st = _load_global()
    if not st.get("kings") or map_id not in st["kings"]:
        return []
    king = st["kings"].get(map_id)
    if not king or king.get("killed"):
        return []
    # 贡献记录（击杀者最后一击 + 此前贡献）
    king.setdefault("contrib", {})
    king["contrib"][str(qq_id)] = int(king["contrib"].get(str(qq_id), 0) or 0) + max(0, int(damage))
    if last_hit:
        king["last_hit"] = str(qq_id)
    king["hp"] = 0
    king["killed"] = True
    king["killed_ts"] = int(datetime.datetime.now().timestamp())
    # 解锁宝箱：击杀者（队伍）优先 15 分钟 → 公共
    now_ts = king["killed_ts"]
    king["chest"] = {
        "unlocked": True,
        "killers": [str(qq_id)],          # 击杀者（含队伍）
        "priority_until": now_ts + WILD_KING_LOOT_PRIORITY_SEC,
        "public_until": now_ts + WILD_KING_LIFETIME_SEC,  # 宝箱与野王同寿命（约 90 分钟）
        "opened": {},                     # qq -> 开箱时间戳
        "public": False,
    }
    # 全服击杀 → no_kill_streak 清零
    st["no_kill_streak"] = 0
    _save_global(st)
    # 广播文本
    name = king.get("name", "野王")
    icon = king.get("icon", "👑")
    map_name = _resolve_map_name(map_id)
    killer_name = ""
    try:
        p = db.get_player(group_id, qq_id)
        killer_name = p.get("name", "") if p else ""
    except Exception:
        pass
    lines = [
        f"{icon}【{name}】被击败了！",
        f"📍 它看守的宝箱在【{map_name}】原地解锁——",
        f"🎁 击杀者{f' {killer_name} ' if killer_name else ' '}可优先『摸战利箱』15 分钟，"
        f"之后转为公共宝箱（同图每人 1 次）！",
        f"💡 打不过也不用等：15 分钟后『摸宝箱』人人可摸！",
    ]
    return lines


# ================= 宝箱开箱（原子认领） =================
def _personal_meta(qq_id: str) -> dict:
    raw = db.get_event_state(f"{META_PREFIX}{qq_id}")
    if not raw:
        return {"pity": 0, "pity_period": "", "opened": {}, "day": "", "day_count": 0}
    try:
        d = json.loads(raw)
        return d if isinstance(d, dict) else {"pity": 0, "pity_period": "", "opened": {}, "day": "", "day_count": 0}
    except (ValueError, TypeError):
        return {"pity": 0, "pity_period": "", "opened": {}, "day": "", "day_count": 0}


def _save_personal(qq_id: str, meta: dict):
    db.set_event_state(f"{META_PREFIX}{qq_id}", json.dumps(meta, ensure_ascii=False))


def _touch_pity(qq_id: str) -> dict:
    """参与野王时段（探索到野王/进入战斗/击杀）→ 保底计数滚动。

    方案 3.2 保底 ①：个人连续 3 时段参与未开箱 → 第 4 时段保底券
    （保底券 = 下一次开箱资格，不占时段/每日次数）。
    """
    pk = period_key()
    meta = _personal_meta(qq_id)
    if meta.get("pity_period") != pk:
        # 跨时段：上一时段开了箱 → 计数清零；未开 → +1；达 3 → 发保底券
        if meta.get("opened_period") == meta.get("pity_period"):
            meta["pity"] = 0
        else:
            meta["pity"] = int(meta.get("pity", 0) or 0) + 1
        meta["pity_period"] = pk
        meta.setdefault("opened_period", "")
        if meta["pity"] >= WILD_KING_PITY_PERIODS:
            meta["pity"] = 0
            meta["voucher"] = int(meta.get("voucher", 0) or 0) + 1  # 保底券 +1
    _save_personal(qq_id, meta)
    return meta


def _chest_access(king: dict, qq_id: str, meta: dict) -> tuple:
    """开箱资格判定：返回 (ok, reason)。

    - 战利箱：击杀者（含队伍）15 分钟内可摸，每人每时段 1 次
    - 公共箱：同图任意玩家每人 1 次
    - 每人每时段最多 1 次、每日最多 2 次
    - 保底券：voucher>0 → 本次开箱不占次数（消耗 1 张）
    """
    chest = king.get("chest") or {}
    if not chest.get("unlocked"):
        return False, "🔒 宝箱还锁着——野王还活着，先去击败它吧！"
    now_ts = int(datetime.datetime.now().timestamp())
    # 时段限制
    pk = period_key()
    opened = meta.get("opened", {}) or {}
    if opened.get(pk, 0) >= WILD_KING_PER_PERIOD_LIMIT:
        return False, "⏳ 本时段你已经摸过宝箱了（每时段限 1 次）！"
    # 每日限制
    today = datetime.date.today().isoformat()
    if meta.get("day") == today and int(meta.get("day_count", 0) or 0) >= WILD_KING_PER_DAY_LIMIT:
        return False, "⏳ 今天已经摸过 2 次宝箱了（每日限 2 次）！"
    # 战利箱（击杀者专属期）
    if not chest.get("public") and now_ts < chest.get("priority_until", 0):
        killers = chest.get("killers") or []
        if str(qq_id) in killers:
            return True, "loot"
        # 击杀者队伍成员同样可摸
        try:
            members = _party_members_of(qq_id)
            if members and any(str(m) in killers for m in members):
                return True, "loot"
        except Exception:
            pass
        return False, "🔒 野王刚倒下，战利箱归击杀者（队伍）所有——等 15 分钟后公共化，或一起组队击杀！"
    # 公共箱
    if now_ts >= chest.get("priority_until", 0) or chest.get("public"):
        return True, "public"
    return False, "🔒 宝箱暂时无法打开……"


def _party_members_of(qq_id: str) -> list:
    """玩家所在队伍成员（含自己）。"""
    try:
        for gid in ("", ):
            members = db.party_members(gid, qq_id)
            if members:
                return members
    except Exception:
        pass
    return [qq_id]


def open_chest(group_id: str, qq_id: str, map_id: str) -> tuple:
    """『摸宝箱』/『摸战利箱』指令入口。

    返回 (text, need_broadcast)：text 为回复文本；need_broadcast 表示是否触发全服公告
    （公共箱开出传说物品时）。
    """
    wild_king_tick()
    king = wild_king_state(map_id)
    if not king:
        return "这里没有野王看守的宝箱……（野王在 08/14/20/02 时段随机现身，去『探索』碰碰运气）", False
    if not king.get("killed"):
        return (f"{king.get('icon', '👑')}【{king.get('name')}】还活着，宝箱锁得死死的！\n"
                f"⚔️ 击败它才能解锁宝箱（打不过就等 15 分钟公共化——不过那要先有人击败它）", False)
    meta = _personal_meta(qq_id)
    ok, kind = _chest_access(king, qq_id, meta)
    if not ok:
        return kind, False
    # 原子认领：先标记已开（防并发双开）
    pk = period_key()
    today = datetime.date.today().isoformat()
    opened = meta.get("opened", {}) or {}
    opened[pk] = int(opened.get(pk, 0) or 0) + 1
    meta["opened"] = opened
    meta["opened_period"] = pk
    if meta.get("day") != today:
        meta["day"] = today
        meta["day_count"] = 0
    meta["day_count"] = int(meta.get("day_count", 0) or 0) + 1
    # 保底券：优先消耗（本次不占次数）
    voucher = int(meta.get("voucher", 0) or 0)
    if voucher > 0:
        meta["voucher"] = voucher - 1
        meta["day_count"] = max(0, int(meta["day_count"]) - 1)
        opened[pk] = max(0, int(opened.get(pk, 0)) - 1)
        meta["opened"] = opened
        meta["opened_period"] = ""
    _save_personal(qq_id, meta)
    # 开箱奖励
    kdef = WILD_KINGS.get(king.get("kid"), {})
    tier = WILD_KING_CHEST_TIERS.get(king.get("chest_tier") or kdef.get("chest_tier", "low"),
                                     WILD_KING_CHEST_TIERS["low"])
    is_loot = kind == "loot"
    lines, need_bc = _roll_chest_rewards(group_id, qq_id, king, tier, is_loot)
    # 记录开箱者
    chest = king["chest"]
    chest.setdefault("opened", {})[str(qq_id)] = int(datetime.datetime.now().timestamp())
    chest["public"] = True  # 有人开箱后即公共化（击杀者已摸完 → 转公共）
    king["chest"] = chest
    _save_global(wild_king_tick())
    header = "🎁 你打开了【野王战利箱】！" if is_loot else "🎁 你打开了【野王宝箱】！"
    return header + "\n" + "\n".join(lines), need_bc


def _roll_chest_rewards(group_id: str, qq_id: str, king: dict, tier: dict,
                        is_loot: bool) -> tuple:
    """宝箱奖励 roll：图纸保底（战利箱 100% / 公共箱 50%）+ 原石 + 装备 + 符文 + 材料 + 金币。

    返回 (展示行列表, 是否需广播)。

    v174 统一抽象：核心 8 档概率走 drop_engine roll('chest:{tier}')——数据源
    DROP_POOLS（gold/bp/gem/equip_drop/rune/stone/mats/collect 统一配置可审计），
    本层只做入包 + 文案 + 广播。战利箱(is_loot) bp 必出 与 图纸残页 20% 是动态特例保留。
    """
    _drop_roll = _host_attr("drop_engine", "roll")  # noqa: E402（宿主真源：池/内容 API 由宿主装配）
    _DropCtx = _host_attr("drop_engine", "_SimpleCtx")  # noqa: E402
    import uuid
    player = db.get_player(group_id, qq_id) or {}
    lv = int(king.get("lv", 30) or 30)
    lines = []
    need_bc = False

    # 引擎核心档：chest:{tier}（tier key 由 king.chest_tier 指定，数据源 WILD_KING_CHEST_TIERS）
    _tier_key = king.get("chest_tier") or "low"
    if _tier_key not in ("low", "mid", "high"):
        _tier_key = "low"
    _dctx = _DropCtx(player_level=lv, monster_lv=lv, qty=1)
    _results = _drop_roll(f"chest:{_tier_key}", _dctx)

    got_bp = False
    for r in _results:
        t = r.get("type")
        if t == "gold":
            gold = int(r.get("count", 0))
            db.update_player(group_id, qq_id, gold=player.get("gold", 0) + gold)
            lines.append(f"💰 金币 +{gold}")
        elif t == "bp" and r.get("data"):
            got_bp = True
            bp = r["data"]
            learned = player.get("learned_blueprints") or []
            if bp.get("blueprint_for") in learned:
                pages = {"white": 1, "green": 1, "blue": 2, "purple": 4, "orange": 6}.get(
                    bp.get("quality", "white"), 1)
                db.add_item(group_id, qq_id, "mat_tu_zhi_can_ye",
                            {"name": "图纸残页", "type": "材料", "stackable": True, "price": 10},
                            count=pages)
                lines.append(f"📜 图纸已学会，化作 {pages} 张图纸残页")
            else:
                db.add_item(group_id, qq_id, f"bp_{uuid.uuid4().hex[:8]}", bp)
                lines.append(f"📜 掉出图纸：{bp['name']}！")
        elif t == "gem" and r.get("data"):
            gem = r["data"]
            db.add_item(group_id, qq_id, f"gem_{uuid.uuid4().hex[:8]}", gem)
            lines.append(f"💎 获得幸运宝石：{gem['name']}！")
        elif t == "equip" and r.get("data"):
            eq = r["data"]
            db.add_item(group_id, qq_id, f"eq_{uuid.uuid4().hex[:8]}", eq)
            qn = {"green": "🟢", "blue": "🔵", "purple": "✨🟣", "orange": "🌟🟠"}.get(
                eq.get("quality", ""), "")
            lines.append(f"{qn} 装备：【{eq['name']}】！")
            if eq.get("quality") in ("purple", "orange"):
                need_bc = True
        elif t == "rune" and r.get("data"):
            rune_data = r["data"]
            db.add_item(group_id, qq_id,
                        f"rune_{rune_data.get('effect', '')}_{rune_data.get('lvl', 1)}", rune_data)
            lines.append(f"✨ 符文【{rune_data['name']}】！")
        elif t == "item" and r.get("item_id") == "mat_gao_ji_qiang_hua_shi":
            stone_n = int(r.get("count", 1))
            db.add_item(group_id, qq_id, "mat_gao_ji_qiang_hua_shi",
                        {"name": "高级强化石", "type": "材料", "stackable": True, "price": 80},
                        count=stone_n)
            lines.append(f"🪨 高级强化石 ×{stone_n}")
        elif t == "item" and r.get("item_id") == "mat_tu_zhi_can_ye":
            pages = int(r.get("count", 1))
            db.add_item(group_id, qq_id, "mat_tu_zhi_can_ye",
                        {"name": "图纸残页", "type": "材料", "stackable": True, "price": 10},
                        count=pages)
            lines.append(f"📄 图纸残页 ×{pages}")
        elif t == "item" and r.get("item_id"):
            # 材料档 / 收藏品档（collect：铁牌徽章等曾配置但旧代码不消费的死数据）
            mid = r["item_id"]
            _idata = _ci.ITEMS.get(mid) or _ci.MATERIALS.get(mid)
            if _idata:
                db.add_item(group_id, qq_id, mid, dict(_idata))
                lines.append(f"🎒 {_idata.get('name', mid)} ×1")
    # 战利箱 bp 必出（引擎公共箱概率可能没 roll 到 → 补一次必出）
    if is_loot and not got_bp:
        bp = C.roll_blueprint(max(1, lv))
        if bp:
            learned = player.get("learned_blueprints") or []
            if bp.get("blueprint_for") in learned:
                pages = {"white": 1, "green": 1, "blue": 2, "purple": 4, "orange": 6}.get(
                    bp.get("quality", "white"), 1)
                db.add_item(group_id, qq_id, "mat_tu_zhi_can_ye",
                            {"name": "图纸残页", "type": "材料", "stackable": True, "price": 10},
                            count=pages)
                lines.append(f"📜 图纸已学会，化作 {pages} 张图纸残页")
            else:
                db.add_item(group_id, qq_id, f"bp_{uuid.uuid4().hex[:8]}", bp)
                lines.append(f"📜 掉出图纸：{bp['name']}！")
    # 图纸残页 20% 额外（动态特例保留）
    if random.random() < 0.20:
        pages = random.randint(*tier["pages_range"])
        db.add_item(group_id, qq_id, "mat_tu_zhi_can_ye",
                    {"name": "图纸残页", "type": "材料", "stackable": True, "price": 10},
                    count=pages)
        lines.append(f"📄 图纸残页 ×{pages}")
    return lines, need_bc


# ================= 查询/展示 =================
def wild_king_summary(map_id: str) -> str:
    """『时间』/探索入口展示：当前图野王状态（在场/已击杀/无）。"""
    king = wild_king_state(map_id)
    if not king:
        return ""
    if king.get("killed"):
        return (f"{king.get('icon', '👑')}【{king.get('name')}】已被击败，"
                f"宝箱在原地（『摸宝箱』）")
    left = max(0, int(king.get("expire", 0)) - int(datetime.datetime.now().timestamp()))
    mins = left // 60
    return (f"{king.get('icon', '👑')}【{king.get('name')}】Lv.{king.get('lv')} 在此图看守宝箱"
            f"（约 {mins} 分钟后离开）——击败它解锁宝箱！")


def personal_meta(qq_id: str) -> dict:
    """个人野王元数据（保底券/时段计数展示）。"""
    return _personal_meta(qq_id)


def list_active_kings() -> list:
    """全服当前在场野王列表（GM/状态展示用）。"""
    st = _load_global()
    return [k for k in st.get("kings", {}).values() if not k.get("killed")]
