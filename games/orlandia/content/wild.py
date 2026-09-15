# -*- coding: utf-8 -*-
# ==============================================================================
# 包内实现（唯一真源）· B13-L2（2026-09-14）—— 逐字搬自宿主
#   `qqbot/data/plugins/dragonfall/game/core/wild.py`
# 搬运改动面**只有「宿主取件」**一类：5 处 `from .. import db` → `db` 替身；`ALL_WILD` → 惰性快照 `_ALL_WILD()`（PEP 562 兼容真源名）
# ★ B16-W8（2026-09-14）：「宿主取件」最后一处 `data.wild_npcs` 两张表**归包** ——
#   `_wild_tables()` 改读包内 `npcs` 域（经 `catalog_quests` 的保序门面，序表在那边显式声明），
#   宿主句柄清零；本模块此后 `import` 不碰 `game.data`（见 ② 与 `overnight/_w8_wild_daily_events.md`）。
# 宿主同名文件 = 薄壳（指向本模块，见那边的头注）。
# ==============================================================================
"""奥兰迪亚·余烬纪年 核心 - wild.py（18 章野外 NPC 判定引擎，2026-08-06）

出现链路：
  地图匹配（含 roam 游走定位）→ unlock 解锁（flag/道具/任务）→ 基础条件（时间/季节/天气/等级/任务/道具/星期）
  → 随机性（chance 概率 + cycle 周期 + 保底）→ 偶遇（记录见闻录）

随机性（18 章 1.5b）：
  chance：每 30 分钟独立判定（简化：每次判定独立）
  roam：日期哈希定当天位置，全服一致
  cycle：date.toordinal() % N == 0
  保底：连续 7 次条件满足未遇 → 下次必出

⚠️ 宿主存储经 `db = _HostMod("db")` 替身（B13-L2 搬包 2026-09-14）：正文 `db.xxx(...)`
   一字未改，属性访问时解析宿主 `game.db`；取不到**大声抛**（不静默空跑）。
"""
import datetime
import json
import os
import random

from .time_weather import current_period, current_season, today_weather   # 包内（本线同名模块）
from .timed_events import register_timed, set_timed                       # 包内（本线同名模块）
import importlib
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


from ._pkgref import DB as db


# ============================================================
# ② 野外/隐藏 NPC 三表 —— 包内域读口（★ B16-W8 · 2026-09-14 宿主句柄归包）
#    真源模块级 `from ..data.wild_npcs import WILD_NPCS, HIDDEN_NPCS` = 宿主两张数据表；
#    宿主 `game/data/` 要删，所以本模块必须自带。取值来源换成包内：
#
#        `npcs` 域 `content/data/npcs.json`（431 条 = town 362 / wild 47 / hidden 22）
#          ↓ 经包内门面 `content/catalog_quests.py` 的**保序还原**
#        `WILD_NPCS`（47）· `HIDDEN_NPCS`（22）
#
#    为什么不能直接读域 JSON：域外层键是**字典序**落盘（导出契约 `sort_table`，幂等优先），
#    真源是插入序，而本模块的 `roll_wild_encounter` / `nearby_hints` 是**按 ALL_WILD 顺序
#    取第一个命中** ⇒ 顺序 = 行为。序表（`_WILD_NPCS_ORDER` 47 / `_HIDDEN_NPCS_ORDER` 22）
#    在 `catalog_quests.py` 里显式声明 + 导入期集合守卫（`_ordered()`：域键集 ≠ 序表键集
#    → raise），实测与宿主 `C.WILD_NPCS` / `C.HIDDEN_NPCS` **键集 / 键序 / 逐条值全等**。
#    ⚠️ 本模块**不再本地派生这两张表** —— 同一张表两份定义必漂移（与 `content/talk_actions.py`
#       「ALL_WILD 切包内读口后本地派生随之删除」同纪律）。
# ============================================================
from .catalog_quests import (WILD_NPCS as _WILD_NPCS_47,          # 包内门面（npcs 域 + 序表）
                             HIDDEN_NPCS as _HIDDEN_NPCS_22)

_HERE = os.path.dirname(os.path.abspath(__file__))


def _inst_stage_ids():
    """域里带 `inst_stage` 的 6 条**层内 NPC**（`data/_assembly.py:163` 装配期并入 HIDDEN_NPCS）。

    真源 `ALL_WILD` 是 `core/wild.py` **import 期**求值的 `{**WILD_NPCS, **HIDDEN_NPCS}`，
    那一刻装配还没把 `INSTANCE_STAGE_NPCS` 并进去 ⇒ 真源 63 = wild 47 ∪ hidden **16**。
    宿主真源条目里**没有** `inst_stage` 这个键（它是导出器 `derive_npcs` 为折三张表注入的），
    所以**域是包内唯一能分辨这 6 条的地方** —— 用字段判定，不硬编码 id 名册。
    """
    try:
        with open(os.path.join(_HERE, "data", "npcs.json"), encoding="utf-8") as fh:
            dom = json.load(fh)
    except Exception:                                       # noqa: BLE001
        return frozenset()
    return frozenset(k for k, v in dom.items()
                     if isinstance(v, dict) and v.get("inst_stage"))


_INST_STAGE_IDS = _inst_stage_ids()

# 导入期守卫：形状漂移 → 大声抛（绝不静默少条目 / 静默换序 —— 两者都会改行为）
if (len(_WILD_NPCS_47), len(_HIDDEN_NPCS_22)) != (47, 22):
    raise ValueError(
        "content/wild：npcs 域两张表条数变了（wild=%d / hidden=%d，期望 47 / 22）—— "
        "域或 catalog_quests 序表变了，拒绝静默降级"
        % (len(_WILD_NPCS_47), len(_HIDDEN_NPCS_22)))
if set(_WILD_NPCS_47) & set(_HIDDEN_NPCS_22):
    raise ValueError(
        "content/wild：WILD_NPCS 与 HIDDEN_NPCS 键集有交集 %s —— 真源三表零交集"
        % sorted(set(_WILD_NPCS_47) & set(_HIDDEN_NPCS_22))[:5])
if len(_INST_STAGE_IDS) != 6 or not _INST_STAGE_IDS <= set(_HIDDEN_NPCS_22):
    raise ValueError(
        "content/wild：域里 `inst_stage` 标记不是 6 条、或不在 HIDDEN_NPCS 里（%d 条 %s）—— "
        "层内 NPC 并入路径（_assembly.py:163）变了，拒绝静默把 ALL_WILD 从 63 变 69"
        % (len(_INST_STAGE_IDS), sorted(_INST_STAGE_IDS)[:8]))

_ALL_WILD_CACHE = None


def _wild_tables():
    """包内两张 NPC 表（真源模块级 `from ..data.wild_npcs import WILD_NPCS, HIDDEN_NPCS`）。"""
    return _WILD_NPCS_47, _HIDDEN_NPCS_22


def _ALL_WILD() -> dict:
    """真源 `ALL_WILD = {**WILD_NPCS, **HIDDEN_NPCS}`（`core.wild` import 期求值一次）。

    真源快照发生在 `data/_assembly.py:163` 把 6 条层内 NPC 并进 `HIDDEN_NPCS` **之前**
    ⇒ 真源 ALL_WILD = wild 47 ∪ hidden 16 = **63** 条；这里用 `not inst_stage` 精确还原
    （与 `content/talk_actions.py` 同口径），首次调用后缓存 = 真源的「import 期求值一次」。

    ★ B16-W8：源在包内 ⇒ 取值与「谁先触发」解耦，恒为 63。改前两张表走宿主句柄，
    而宿主 `HIDDEN_NPCS` 是**会被装配期就地 update 的同一只字典**，`game.*` 回退路径下
    实测取到过 69（并入后）。
    """
    global _ALL_WILD_CACHE
    if _ALL_WILD_CACHE is None:
        _ALL_WILD_CACHE = {**_WILD_NPCS_47,
                           **{k: v for k, v in _HIDDEN_NPCS_22.items()
                              if k not in _INST_STAGE_IDS}}
    return _ALL_WILD_CACHE


def __getattr__(name):
    """PEP 562：真源顶层名兼容（`WILD_NPCS` / `HIDDEN_NPCS` / `ALL_WILD` 惰性解析）。"""
    if name == "WILD_NPCS":
        return _wild_tables()[0]
    if name == "HIDDEN_NPCS":
        return _wild_tables()[1]
    if name == "ALL_WILD":
        return _ALL_WILD()
    raise AttributeError(name)


# ==================== v127.5 限时NPC（通用懒计时引擎接入） ====================
# 偶遇触发 → set_timed 挂"在场限时"事件；倒计时内地图/对话可见可找，过期即同消。
# 过期回调：清除该 NPC 可能存在的进行中对话会话（显示与对话同时消失，铁律）。
def _wild_npc_expire(group_id, qq_id, data):
    try:
        db.clear_talk_state(group_id, qq_id)
    except Exception:
        pass  # 清除失败无副作用


register_timed("wild_npc", duration_sec=60 * 60, on_expire=_wild_npc_expire)

WILD_META_KEY = "wildmeta_{gid}_{qid}"
MISS_GUARANTEE = 7  # 连续 7 次条件满足未遇 → 必出


def _day_hash(seed: int, salt: str = "") -> int:
    h = seed * 2654435761 + (sum(ord(c) for c in salt) if salt else 0)
    return h & 0x7FFFFFFF


def npc_map_id(npc_id: str, npc: dict, now: datetime.date | None = None) -> str | None:
    """NPC 当天所在地图：roam 用日期哈希定位，否则返回固定 map"""
    roam = npc.get("roam")
    if roam:
        now = now or datetime.date.today()
        return roam[_day_hash(now.toordinal(), npc_id) % len(roam)]
    return npc.get("map")


def _quest_known(q: dict, qid: str) -> bool:
    """任务已知(主线完成 / 支线已接或进行中)。支线完成即从 side 删除，无完成记录。"""
    return qid in q.get("completed_main", []) or qid in q.get("side", {})


def unlock_met(npc_id: str, npc: dict, group_id: str, qq_id: str) -> bool:
    """解锁条件(unlock)：flag:xxx / item:mat_xxx / quest:qid。无 unlock=天然解锁。"""
    unlock = npc.get("unlock")
    if not unlock:
        return True
    if unlock.startswith("flag:"):
        flag = unlock[5:]
        # v104 P1（M21）：扫全量 flag 桶——flag 可能由其他 NPC 对话设置（如 说书人·巴尔 →
        # heard_owl_song），只查本 NPC 自己的桶会永久锁死。base_conditions_met 已有全桶扫描先例。
        return any(flag in db.get_talk_flags(group_id, qq_id, nid) for nid in _ALL_WILD())
    if unlock.startswith("item:"):
        item = unlock[5:]
        return db.count_item(group_id, qq_id, item) > 0
    if unlock.startswith("quest:"):
        qid = unlock[6:]
        return _quest_known(db.get_quests(group_id, qq_id), qid)
    if unlock.startswith("quest_done:"):
        # v87：已完成任务解锁（如 图书管理员·贝拉 需通关圣堂地窖/主线第11章）
        qid = unlock[11:]
        q = db.get_quests(group_id, qq_id)
        if _quest_known(q, qid):
            return True
        # v104 P1（M21）：quest_done 兼容副本 id——battle_state 中该副本已通关(cleared)
        # 也算达成（副本通关不写 quests 完成记录，battle_state 是唯一临时标记；
        # 持久路径为 unlock 指向主线任务 id，如 q11_3）
        try:
            _row = db.get_battle(group_id, qq_id)
            if _row:
                _st = _row.get("state") or {}
                if _st.get("cleared") and _st.get("inst_id") == qid:
                    return True
        except Exception:
            pass
        return False
    if unlock.startswith("stats:"):
        # v124 隐藏线触发：stats 计数门槛（如 候鸟·翎信 需垂钓 10 次）——stats:key:min
        try:
            _key, _min = unlock[6:].split(":", 1)
            _st = db.get_stats(group_id, qq_id) or {}
            return int(_st.get(_key, 0) or 0) >= int(_min)
        except Exception:
            return False
    return True


def base_conditions_met(npc_id: str, npc: dict, player: dict, group_id: str, qq_id: str) -> bool:
    """基础出现条件(AND)：time/season/weather/min_level/max_level/quest_done/quest_active/flag/item/day_of_week"""
    cond = npc.get("condition", {})
    # 时间段
    t = cond.get("time")
    if t and current_period() not in t:
        return False
    # 季节
    s = cond.get("season")
    if s and current_season() not in s:
        return False
    # 天气
    w = cond.get("weather")
    if w:
        cur_w = today_weather(npc_map_id(npc_id, npc))
        if w == "sunny":
            if cur_w not in ("sunny", "cloudy"):
                return False
        elif cur_w != w:
            return False
    # 等级区间
    if cond.get("min_level") and player.get("level", 1) < cond["min_level"]:
        return False
    if cond.get("max_level") and player.get("level", 1) > cond["max_level"]:
        return False
    q = db.get_quests(group_id, qq_id)
    # 已完成任务
    qd = cond.get("quest_done")
    if qd and not all(_quest_known(q, x) for x in qd):
        return False
    # 任务进行中
    # v105 M23 P2-7：原只查 side（支线），主线进行中（main_status=active 且 main_quest 命中）
    # 也会被误判不满足——补主线查询。当前数据层无 quest_active 使用者（潜伏），语义对齐无行为变化
    qa = cond.get("quest_active")
    if qa:
        _side = q.get("side", {})
        _main_hit = q.get("main_status") == "active" and q.get("main_quest") in qa
        if not _main_hit and not any(x in _side for x in qa):
            return False
    # 对话 flag（任意 NPC 的 flag 都算——talkflags 按 NPC 分组，这里扫全部）
    if cond.get("flag"):
        if not any(cond["flag"] in db.get_talk_flags(group_id, qq_id, nid) for nid in _ALL_WILD()):
            return False
    # 持有道具
    if cond.get("item") and db.count_item(group_id, qq_id, cond["item"]) <= 0:
        return False
    # 星期（周一=0）
    dw = cond.get("day_of_week")
    if dw and datetime.date.today().weekday() not in dw:
        return False
    return True


def _get_meta(group_id: str, qq_id: str) -> dict:
    raw = db.get_event_state(WILD_META_KEY.format(gid=group_id, qid=qq_id))
    if not raw:
        return {"met": [], "miss": {}, "last": {}}
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {"met": [], "miss": {}, "last": {}}


def _save_meta(group_id: str, qq_id: str, meta: dict):
    db.set_event_state(WILD_META_KEY.format(gid=group_id, qid=qq_id),
                       json.dumps(meta, ensure_ascii=False))


def met_wild(group_id: str, qq_id: str) -> list:
    """见闻录：已遇见的野外 NPC id 列表"""
    return _get_meta(group_id, qq_id).get("met", [])


def _roll_random(npc_id: str, npc: dict, group_id: str, qq_id: str) -> bool:
    """随机性判定：cycle 硬条件 + chance 概率(含保底)。返回是否出现。"""
    cycle = npc.get("cycle")
    if cycle and datetime.date.today().toordinal() % cycle != 0:
        return False
    chance = npc.get("chance")
    if not chance:
        return True
    meta = _get_meta(group_id, qq_id)
    miss = meta.get("miss", {}).get(npc_id, 0)
    if miss >= MISS_GUARANTEE:
        meta.setdefault("miss", {}).pop(npc_id, None)  # 保底必出 = 本次遇到，清计数
        _save_meta(group_id, qq_id, meta)
        return True  # 保底：连续 7 次未遇必出
    if random.random() < chance:
        return True
    meta.setdefault("miss", {})[npc_id] = miss + 1
    _save_meta(group_id, qq_id, meta)
    return False


def wild_npc_findable(npc_id: str, npc: dict, player: dict, group_id: str, qq_id: str) -> bool:
    """『找 <名字>』直接寻找的判定：解锁 + 基础条件 + cycle 硬条件（跳过 chance——
    主动寻找不受概率限制，条件满足就能找到；cycle 是硬规律必须满足）。"""
    if npc.get("cycle") and datetime.date.today().toordinal() % npc["cycle"] != 0:
        return False
    return unlock_met(npc_id, npc, group_id, qq_id) and base_conditions_met(npc_id, npc, player, group_id, qq_id)


def roll_wild_encounter(group_id: str, qq_id: str, player: dict, map_id: str):
    """探索/进入地图时调用：当前地图满足条件的野外 NPC → 返回 (npc_id, npc)，否则 None。

    记录见闻录 + 清保底计数 + 30 分钟冷却（同一 NPC 30 分钟内不重复偶遇，防蹲守刷屏）。
    只返回第一个命中的 NPC（偶遇一次）。
    """
    today = datetime.date.today()
    now = int(datetime.datetime.now().timestamp())
    meta = _get_meta(group_id, qq_id)
    for nid, npc in _ALL_WILD().items():
        if npc_map_id(nid, npc, today) != map_id:
            continue
        if not unlock_met(nid, npc, group_id, qq_id):
            continue
        if not base_conditions_met(nid, npc, player, group_id, qq_id):
            continue
        # 30 分钟冷却（偶遇过的不立刻重复出现）
        last = meta.get("last", {}).get(nid, 0)
        if last and now - last < 1800:
            continue
        if not _roll_random(nid, npc, group_id, qq_id):
            continue
        # 偶遇！见闻录记录 + 清保底 + 冷却
        if nid not in meta["met"]:
            meta["met"].append(nid)
        meta.setdefault("miss", {}).pop(nid, None)
        meta.setdefault("last", {})[nid] = now
        _save_meta(group_id, qq_id, meta)
        # v127.5 限时NPC：偶遇命中 → 挂"在场限时"事件（通用懒计时引擎）。
        # 时长按 NPC 的 duration 分钟（缺省 60）；map 用 npc_map_id 支持 roam 当日定位。
        _dur_min = npc.get("duration", 60) or 60
        set_timed(group_id, qq_id, f"wild:{nid}", "wild_npc",
                  data={"npc_id": nid, "map": npc_map_id(nid, npc, today)},
                  duration_sec=int(_dur_min) * 60)
        return nid, npc
    return None


def nearby_hints(group_id: str, qq_id: str, player: dict, map_id: str) -> list:
    """『时间』指令：当前地图满足条件(含随机性)的野外 NPC 提示列表(供"附近可遇"显示)"""
    hints = []
    today = datetime.date.today()
    for nid, npc in _ALL_WILD().items():
        if npc_map_id(nid, npc, today) != map_id:
            continue
        if not unlock_met(nid, npc, group_id, qq_id):
            continue
        if not base_conditions_met(nid, npc, player, group_id, qq_id):
            continue
        hints.append((nid, npc))
    return hints


# ==================== v95.30 城镇 NPC 随机性引擎 ====================
# 城镇酱油 NPC（funcs=[]）的活人随机：roam 游走 / appear 随机出现 / period 时段 / lines 随机台词
# 铁律：功能 NPC（funcs 非空）永不参与随机——镇长/铁匠随机消失会毁任务链
# 全服一致：一律日期哈希（同一天所有玩家看到同一世界），不用 random

def town_npc_day_sa(npc_id: str, npc: dict, home_sa: str, now: datetime.date | None = None) -> str | None:
    """城镇 NPC 今日所在子区域（B 游走）。

    - 无 roam → 返回 home_sa（静态）
    - 有 roam（同图子区域 id 列表）→ 日期哈希定位当天位置
    返回 None 仅表示数据异常（roam 列表空），正常恒返回一个 sa id。
    """
    roam = npc.get("roam")
    if not roam:
        return home_sa
    now = now or datetime.date.today()
    return roam[_day_hash(now.toordinal(), npc_id) % len(roam)]


def town_npc_visible(npc_id: str, npc: dict, sa_id: str, now: datetime.date | None = None) -> bool:
    """城镇 NPC 当前是否在指定子区域可见（B 游走 + C 随机出现 + D 时段）。

    - 功能 NPC（funcs 非空）恒可见（铁律）
    - period 时段不符 → 不可见（『找』提示时段）
    - appear 概率（日期哈希，如 0.7 = 7 成天数出现）→ 不可见（『找』提示没来）
    - roam 当天位置 ≠ sa_id → 不可见（『找』提示去向）
    """
    if npc.get("funcs"):
        return True
    # D 时段（v95.30b 修复：period 判定必须确定性——now 未传（生产）用真实时钟，
    # 传 date 对象（测试固定日期）→ 固定白天映射；传 datetime → 按该时间）
    per = npc.get("period")
    if per:
        if now is None:
            _cur = current_period()
        elif isinstance(now, datetime.datetime):
            _cur = current_period(now)
        else:
            _cur = "day"
        if _cur not in per:
            return False
    now = now or datetime.date.today()
    # C 随机出现（appear ∈ (0,1]，日期哈希全服一致）
    app = npc.get("appear")
    if app is not None and app < 1.0:
        if _day_hash(now.toordinal(), npc_id + ":appear") % 100 >= int(app * 100):
            return False
    # B 游走：今天在这才可见
    if town_npc_day_sa(npc_id, npc, sa_id, now) != sa_id:
        return False
    return True


def town_npc_dialogue(npc_id: str, npc: dict, base: str, now: datetime.date | None = None) -> str:
    """A 随机台词：funcs=[] 且配置了 lines（多条）→ 按日期哈希选一条（每天换台词，全服一致）。

    功能 NPC / 未配置 lines / 配置了对话树（多轮）→ 返回原台词。
    """
    if npc.get("funcs"):
        return base
    lines = npc.get("lines")
    if not lines or len(lines) < 2:
        return base
    now = now or datetime.date.today()
    return lines[_day_hash(now.toordinal(), npc_id + ":line") % len(lines)]
