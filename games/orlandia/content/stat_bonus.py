# -*- coding: utf-8 -*-
"""《奥兰迪亚·余烬纪年》包内**外部面板增幅聚合器 + bonus 容器助手**（逐字搬自游戏仓
`game/core/stat_bonus.py`，226 行；v181.M-bonus 统一容器）。

真源职责：① `stat_bonus()` 聚合称号/成就称号/收藏册满套的**纯 flat 数值**增幅；
② `_collection_completed_bonus()` 收藏册满套判定；③ `bonus_seed`/`bonus_domain` 容器读写助手。
宿主 `game/core/stat_bonus.py` 现在是薄壳（全名单再导出），消费者 9 处
（`commands/base.py:523` · `core/achievements.py:234` · `reward.py:166` · `services/battle_settlement.py:37` ·
`services/player_event_subscribers.py:21` · `services/quests.py:66` · `services/quests_flow.py:35` ·
`store/players.py:231` · 测试 `tests/test_m_bonus.py` / `test_numeric_reward_unify.py`）零改动。

正文改动面（**只有宿主取件**，聚合逻辑一字未改）：
  ① `from .. import content as C` → `C = _HostMod("content")`（TITLES/ACHIEVEMENTS/
     COLLECTION_BOOKS/ITEMS/MATERIALS/`display` 全在宿主聚合层）
  ② `from ..log_setup import LOG` → `LOG = _host_attr("log_setup", "LOG")`
  ③ 函数内 3 处 `from .. import db` → 删（改用模块级 `db = _HostMod("db")`，同一模块对象）
  ④ `_collection_completed_bonus` 内 `from .. import content as _C` → `_C = C`
  ⑤ `stat_bonus()` 内 `from .title_conds import TitleCtx, CONDITIONS, check_pro_title`
     → 三个 `_host_attr("core.title_conds", …)`（**跨线**：title_conds 归 B13-L4，别线并行中
       → 按 BRIEF §3 B-5 用宿主句柄；L4 落地后切包内直取）

缺口（报告登记）：TITLES / ACHIEVEMENTS / ITEMS / MATERIALS / COLLECTION_BOOKS / `display`
全走宿主聚合层句柄。本线实测（`overnight/w1213_l6_probe.py` 输出）：包内 `titles.json`（68 条）
**条目无 `bonus` 键**、`achievements.json` 只有 `reward` 无 `bonus` → 直接切会**静默丢加成**，
故不切（形状不等价，I3）。`db`/`log_setup` 属存档/平台面（留宿主，I2 注入）。
"""

# ============================================================
# ① 宿主替身口（注入优先 → sys.modules → importlib；**绝不静默空跑**）
#    形状逐字抄 `content/world_cmds.py`（B9 线2 定稿）
# ============================================================
import importlib as _importlib
import sys as _sys

_HOST_PKG = "data.plugins.dragonfall.game"      # 运行时（main.py 的模块路径）
_HOST_PKG_FALLBACK = "game"                     # 测试/工具按 `game.xxx` 直接 import 时
_INJECTED = {}


def bind_host(**objs):
    """宿主薄壳 import 期注入（幂等）——键 = `_HostMod` 的模块名（`content` / `db` / `data`）。"""
    for k, v in (objs or {}).items():
        if v is not None:
            _INJECTED[k] = v


def _host_module(name: str):
    """取宿主子模块（`name` 为空 = 宿主 `game` 包本身）。"""
    if name in _INJECTED:
        return _INJECTED[name]
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        m = _sys.modules.get(prefix if not name else "%s.%s" % (prefix, name))
        if m is not None:
            return m
    last = None
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        try:
            return _importlib.import_module(prefix if not name else "%s.%s" % (prefix, name))
        except Exception as exc:                # noqa: BLE001
            last = exc
    raise RuntimeError("%s：宿主模块 %s 取不到（%s）——拒绝静默空跑" % (__name__, name, last))


def _host_attr(mod: str, attr: str):
    """宿主模块属性 —— 真源「函数内 `from ..<mod> import <attr>`」的同义替身（调用时解析）。"""
    m = _host_module(mod)
    try:
        return getattr(m, attr)
    except AttributeError:
        for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
            try:
                return _importlib.import_module("%s.%s" % (
                    prefix if not mod else "%s.%s" % (prefix, mod), attr))
            except Exception:                   # noqa: BLE001
                continue
        raise


class _HostMod:
    """宿主模块替身（`C` / `db` / `data`）——`C.xxx` 正文一字未改，属性访问时解析。"""

    def __init__(self, name):
        self._name = name

    def __getattr__(self, attr):
        return getattr(_host_module(self._name), attr)

# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年核心层 - stat_bonus.py（v105 M01#11，N5b4-4 泛化正名；v181.M-bonus 统一 bonus 容器）

**统一数值修正容器（v181.M-bonus，鱼鱼 2026-09-09 拍板方案 2）**：
actor 上全部数值修正收敛为单容器 actor["bonus"] = {分域 dict}：
    actor["bonus"] = {
        "panel": {"atk": 15, "spd": 10},   # 面板 flat 增幅（现 stat_bonus 并入；stats.actor_stats 面板合成读）
        "cap":   {"rage": 2},               # 资源上限 flat int 增量（现 cap_bonus 并入；effects._cap_of 读）
        "cost":  {"mp_pct": 0.10, "res": {"energy": 0.05}, "mp_flat": 5,
                  "when": [{"mp_pct": ..., "judge": {...}}]},  # 技能消耗修正（actions._skill_pay_of 读）
    }
约定：
- 引擎零语义：装配层（开战仪式/词条装配）写入，引擎只读分域（读源一律 get 兜底 {}）。
- 旧 actor 键 stat_bonus/cap_bonus 已全清（v181.M-bonus 迁移），无回落兼容。
- 新增修正类型 = bonus 加域 + 引擎一个读点，不再散 actor 字段。
- 本模块职责不变 = 外部面板增幅聚合器（返回 panel 分域 dict），外加容器播种/读取助手。

**外部面板数值增幅聚合器**（鱼鱼 2026-09-08 拍板：新增纯数值增幅系统不改战斗引擎）。

来源（全部是"纯 flat 数值"，加进面板）：
- 副业大师称号/成就称号（TITLES/ACHIEVEMENTS bonus）
- 收藏册满套 bonus（v174）
- 【未来新增来源：挂件/时装/符文等——只在这个函数加一路，引擎/saintess_engine/命令层零改动】

⚠️ 边界：机制型效果（触发/条件/事件）不走这里——走 saintess_engine 装配层
（actor.triggers + 事件总线，N9/N9A 通用通道）。本聚合器只产 flat 数值 dict
（如 {"atk": 15, "spd": 10}），由命令层开战时经 bonus_seed 塞进 actor["bonus"]["panel"]。

命名迁移：v105 原名 title_bonus（只聚合称号）；v174 并入收藏册后语义已是
"外部增幅"，N5b4-4 正名 stat_bonus（仅指聚合函数/模块名）；v181.M-bonus 起
actor 键统称 bonus 容器（panel/cap/cost 分域）。命令层 _title_bonus 方法名与
engine.player_final_stats 的 title_bonus 位置参数保留（旧引擎冻结区，N10 删旧收敛）。

独立于命令层：commands/base.py:_title_bonus 与 store/players.py 惰性升级共用
同一实现，避免 get_player 读档升级重算 max_hp 时缺称号加成（存档上限 < 面板
计算值，升级回满血只回到旧上限，面板长期"生命 861/891"不满）。
- player 参数：已加载玩家 dict 时传入，避免重复读档（get_player 持锁调用必须传）。
"""
C = _HostMod("content")                     # 真源 `from .. import content as C`
LOG = _host_attr("log_setup", "LOG")        # 真源 `from ..log_setup import LOG`
db = _HostMod("db")                         # 真源函数内 `from .. import db`（3 处）


def _visited_maps(group_id, qq_id):
    """已探索地图 id 列表（独立直连，不占用 store 锁）。"""
    import sqlite3
    try:
        conn = sqlite3.connect(db.DB_PATH)
        rows = conn.execute("SELECT map_id FROM visited WHERE qq_id=?", (qq_id,)).fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception:
        return []


def _has_enhanced(group_id, qq_id, level):
    """背包中是否有强化 ≥level 的装备（独立直连，不占用 store 锁）。"""
    import json
    import sqlite3
    try:
        conn = sqlite3.connect(db.DB_PATH)
        rows = conn.execute(
            "SELECT item_data FROM inventory WHERE qq_id=?", (qq_id,)).fetchall()
        conn.close()
        for r in rows:
            try:
                d = json.loads(r[0] or "{}")
                if d.get("enhance", 0) >= level:
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def stat_bonus(group_id, qq_id, player=None) -> dict:
    """外部面板数值增幅聚合（称号加成 + 成就称号 + 收藏册满套；未来纯数值来源加这里）。

    与 commands/base.py 旧 _title_bonus 同逻辑（TITLES 加成 + 成就加成 +
    M18 同名去重 + v174 收藏册）；失败静默返回 {}（与旧实现一致）。
    """
    bonus = {}
    try:
        TitleCtx = _host_attr("core.title_conds", "TitleCtx")
        CONDITIONS = _host_attr("core.title_conds", "CONDITIONS")
        check_pro_title = _host_attr("core.title_conds", "check_pro_title")
        if player is None:
            player = db.get_player(group_id, qq_id) or {}
        stats = db.get_stats(group_id, qq_id) or {}
        rep = db.get_reputation(group_id, qq_id)
        quests = db.get_quests(group_id, qq_id)
        ctx = TitleCtx(group_id, qq_id, player, stats, rep, quests, hooks={
            "has_enhanced": _has_enhanced,
            "visited_maps": _visited_maps,
        })
        earned = []
        for t in C.TITLES:
            tid = t["id"]
            fn = CONDITIONS.get(tid)
            if fn is not None:
                ok = fn(ctx)
            elif tid.startswith("pro_"):
                ok = check_pro_title(tid, ctx)
            else:
                ok = False  # 未知称号 id：不获得（数据错误时安全降级）
            earned.append(ok)
        for i, t in enumerate(C.TITLES):
            if earned[i] and t.get("bonus"):
                for k, v in t["bonus"].items():
                    bonus[k] = bonus.get(k, 0) + v
        # 阶段九：成就称号 bonus（14 章 3.3，达成即生效）
        # M18 修复：跳过与 TITLES 同名且带 bonus 的成就（副业 Lv.10 大师称号已由上方
        # TITLES 段累加，成就侧 ach_pro_*10 为同一称号的重复数据 → 跳过避免双倍发放）
        title_bonus_names = {t["name"] for t in C.TITLES if t.get("bonus")}
        try:
            unlocked_achs = {r["ach_key"] for r in db.get_achievements("", qq_id)}
        except Exception:
            unlocked_achs = set()
        for a in C.ACHIEVEMENTS:
            if a.get("bonus") and a["id"] in unlocked_achs and a.get("name") not in title_bonus_names:
                for k, v in a["bonus"].items():
                    if k == "prof_exp_mult":
                        continue  # v104.2 M13：全知全能副业经验倍率由 add_prof_exp 结算，非面板属性
                    if k != "atk" or v != 0:  # 占位字段跳过
                        bonus[k] = bonus.get(k, 0) + v
        # v174 收藏册满套 bonus 实装（此前数据登记但从不生效，死数据）：
        # 集齐 = 册条目 key/name 命中「曾拥有 possessed」或「图鉴击杀怪名」（与 collection.py
        # _book_progress 同口径，但读 possessed 而非当前背包——卖掉/用掉仍算收集过）
        _book_bonus = _collection_completed_bonus(qq_id, player)
        for k, v in _book_bonus.items():
            bonus[k] = bonus.get(k, 0) + v
    except Exception:
        LOG.warning("[dragonfall] title_bonus 计算异常，称号加成降级为空", exc_info=True)
        pass
    return bonus


def _collection_completed_bonus(qq_id: str, player: dict) -> dict:
    """收藏册已集齐册的永久属性汇总（v174 实装）。

    读 possessed（曾拥有 key）+ ITEMS/MATERIALS 名映射 + bestiary（击杀图鉴怪 key/名）
    判断条目收集；集齐册的 reward.bonus 累加。失败安全返回 {}（不影响其他加成）。
    """
    bonus = {}
    try:
        _C = C
        books = list(getattr(_C, "COLLECTION_BOOKS", None) or [])
        if not books:
            return bonus
        poss = set()
        # 曾拥有物品 key（possessed 表）
        try:
            poss |= set(db.get_possessed(qq_id) or set())
        except Exception:
            pass
        # key → 显示名映射（收藏册条目常用中文名，把曾拥有 key 的中文名也纳入）
        try:
            for _ik in list(poss):
                if _ik in _C.ITEMS:
                    poss.add(str(_C.ITEMS[_ik].get("name", "")))
                elif _ik in _C.MATERIALS:
                    poss.add(str(_C.MATERIALS[_ik].get("name", "")))
        except Exception:
            pass
        # 图鉴击杀怪名（key + display 名）
        try:
            for r in db.get_bestiary("", qq_id) or []:
                _mk = str(r.get("monster") or "")
                poss.add(_mk)
                try:
                    poss.add(str(_C.display("monsters", _mk)))
                except Exception:
                    pass
        except Exception:
            pass
        for b in books:
            entries = b.get("entries") or []
            if not entries:
                continue
            got = sum(1 for e in entries
                      if (e.get("key") and str(e["key"]) in poss)
                      or (e.get("name") and str(e["name"]) in poss))
            if got == len(entries) and b.get("reward", {}).get("bonus"):
                for k, v in b["reward"]["bonus"].items():
                    bonus[k] = bonus.get(k, 0) + float(v)
    except Exception:
        pass
    return bonus


# ============================================================
# 统一 bonus 容器助手（v181.M-bonus：panel/cap/cost 分域读写约定）
# ============================================================

BONUS_DOMAINS = ("panel", "cap", "cost")


def bonus_seed(actor: dict, panel: dict = None) -> dict:
    """开战仪式播种/覆盖 actor["bonus"] 全容器（写约定唯一入口）。

    panel = 外部面板增幅 flat dict（本模块 stat_bonus() 聚合产物）。
    覆盖写：开战装配点每场重算外部增幅 → 整容器重建（cap/cost 由装备装配
    apply_to_actor 随后覆盖写各自分域，先后无冲突）。
    """
    actor["bonus"] = {
        "panel": dict(panel or {}),
        "cap": {},
        "cost": {},
    }
    return actor["bonus"]


def bonus_domain(actor: dict, domain: str) -> dict:
    """读 bonus 分域 dict（无容器/无域 → {}；引擎读源兜底铁律）。"""
    if domain not in BONUS_DOMAINS:
        return {}
    try:
        b = (actor or {}).get("bonus")
        if not isinstance(b, dict):
            return {}
        d = b.get(domain)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}
