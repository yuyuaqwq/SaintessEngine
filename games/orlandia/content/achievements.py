# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— 成就系统（B13-L4，2026-09-14）。

真源：游戏仓 `game/core/achievements.py`（305 行 / 阶段九 14 章）。本模块 = 那份文件的
**实现本体**（逐字搬：`cond_met` / `check_achievements` / `achievement_titles` /
`achievement_points` / `claim_achievement_rewards` / `_bestiary_kills` / `_monster_total`
与 3 个 v140 条件注册）。宿主 `game/core/achievements.py` 现在只剩「加载包 + 同名单 re-export」。

★ 顺序不变式（逐字节等价的关键，与 `content/talk_actions.py` 的 ACTIONS 同款）
  · `from .achievement_conds import COND_CHECKS as _COND_CHECKS` + 3 个 `@_register_cond`
    （blueprints_learned / quests_done / chests_opened）在**本模块 import 期**执行 —— 与真源
    「import achievements 即注册」逐字等价（宿主薄壳 import 包内本模块，注册随之发生）；
  · `C.ACHIEVEMENTS` 的**源列表序**决定 `check_achievements` 的解锁顺序与
    `achievement_titles` 的称号序 → 见下缺口，未切包内域。

正文改动面（只有两类，替换表见 `overnight/w1213_b13l4_port.py`，每条断言出现次数）
--------------------------------------------------------------------------------------
1. 宿主取件 → 惰性替身：`from .. import content as C` / `from .. import db`（函数内，共 6+6 处）
   删除 → 模块级 `C = _HostMod("content")` / `db = _HostMod("db")`；
   `from ..content_rules.gameplay import check_player_level_up` →
   `_host_attr("content_rules.gameplay", …)`；`from .stat_bonus import stat_bonus` →
   `_host_attr("core.stat_bonus", …)`（stat_bonus 属 B13-L6 线，未落地 → 走句柄）；
   `from ..reward import grant_items_batch` → `_host_attr("reward", …)`；
   `from ..log_setup import LOG` → `_host_attr("log_setup", "LOG")`（**只改这一处**）。
2. 读点切包内域读口（I1）：`C.ITEMS.get(_ik)` → 包内 `items` 域读口 `ITEMS`（实测 900 键
   与 `name` 字段全等）。

⚠️ 缺口（报告已登记，B14 统一裁）
  · `C.ACHIEVEMENTS`（3 处）：包内 `achievements` 域是 **dict（外层键字典序）**，宿主
    `C.ACHIEVEMENTS` 是 **list（源列表序）** —— 实测 119 条**逐条深等、集合相等，但顺序不同**
    （域无 `seq`/顺序字段）⇒ 切过去会改「解锁顺序 / 称号顺序」→ 保留宿主句柄（`content/misc_cmds.py`
    的成就面板已登记同款缺口）；
  · `C.MAP_BY_ID`（`_monster_total`）：无同名域（maps 域的派生索引），且 maps 域是投影 → 保留；
  · `C.MATERIALS`（`check_achievements` 奖励文案）：无同名域 → 保留；
  · `C.display("monsters", …)`（`_bestiary_kills`）：宿主 `C.display` 走 `_INDEXES["monsters"]`
    （354 条，能把怪物 id 翻成中文名），包内 `content/tables.display` 对 monsters **原样返回**
    → 不同义，保留宿主句柄（实测见报告步骤 A·5）。

★ 真源遗留缺陷**逐字保留**：`claim_achievement_rewards` 的 `except` 分支里 `LOG` 是**未定义的全局名**
  （真源模块级没有 `LOG`，只有 `check_achievements` 里那处函数内 import）→ 该分支实际抛
  `NameError: name 'LOG' is not defined`。本模块**故意不在模块级定义 `LOG`**（快照 `失败分支 EXC:
  NameError name 'LOG' is not defined` 与改前逐字节相同）。修它 = 行为变更，留给后续单独一批。

真源原文头注（逐字保留）
------------------------
    奥兰迪亚·余烬纪年核心层 - achievements.py（阶段九：成就系统，14 章）
    
    - cond_met(player, stats, profs, extra, cond)：单条条件判定
    - check_achievements(group_id, qq_id)：遍历 97 成就，满足且未解锁 → 解锁 + 发奖励
    - achievement_titles(qq_id)：已解锁成就的称号名列表（与 titles.py TITLES 合并成称号总表）
    - achievement_points(qq_id)：成就点计算（普通 1 / 隐藏 2）
    
    ⚠️ 本模块在 core 聚合链内，禁止顶层 import content/engine（循环导入），一律函数内延迟导入。
    数据源：players（level/evolve_path/learned_skills/apprentices/gold/learned_blueprints）、
    stats 表（kills/elite/boss/visited_areas/inst_clears/party_count/副业次数/world_events/chests_opened）、
    professions 表（副业等级）、quests（completed_main/side）、bestiary（击杀/图鉴）、
    achievements 表（已解锁 + inst_clear_* 记录）。
    
    v140 波2（成就/称号/收藏资源化 3.9）：
    - reward.items 物品奖励发放（claim_achievement_rewards）
    - 3 个新条件类型注册（blueprints_learned/quests_done/chests_opened）——直接 extend
      COND_CHECKS 注册表（achievement_conds.py 的 dict 是模块级单例，注册后 cond_met 立即可用）"""

from __future__ import annotations

import importlib
import sys

import json as _json
import os as _os


# ============================================================
# 包内域读口（I1）：`items` 域（真源 `C.ITEMS`）
# 实测（探针 `overnight/w1213_b13l4_probe.py`）：900 键 / 键集合与 `name` 字段**全等** →
# 正文里 `C.ITEMS.get(_ik)` 一处改读本读口；`C.MATERIALS`（无同名域）仍走宿主句柄（缺口登记）。
# ============================================================
_HERE = _os.path.dirname(_os.path.abspath(__file__))


def _read_domain(name: str) -> dict:
    """读包内 `content/data/<域>.json`（缺文件 / 坏 JSON → `{}`，与 `content/tables.py` 同款）。"""
    try:
        with open(_os.path.join(_HERE, "data", "%s.json" % name), encoding="utf-8") as f:
            return _json.load(f)
    except Exception:                            # noqa: BLE001
        return {}


ITEMS = _read_domain("items")                   # ← 真源 `C.ITEMS`


# ============================================================
# 宿主替身口（**惰性**：属性访问时才解析宿主模块；绝不 import 宿主模块树、绝不静默空跑）
# 真源写法 → 包内替身：`from .. import content as C` → `C = _HostMod("content")`；
# `from .. import db` → `db = _HostMod("db")`。函数内那几行 import 已按原位置删除，
# 所有调用点 `C.xxx` / `db.xxx` **一行未改**（与 `content/world_cmds.py` / `talk_actions.py` 同款）。
# ============================================================
_HOST_PKG = "data.plugins.dragonfall.game"      # 运行时（main.py 的模块路径）
_HOST_PKG_FALLBACK = "game"                     # 测试/工具按 `game.xxx` 直接 import 时
_INJECTED = {}


def bind_host(**objs):
    """宿主薄壳 import 期注入（幂等）——键 = `_HostMod` 的模块名（`content` / `db`）。"""
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
    raise RuntimeError("%s：宿主模块 %s 取不到（%s）——拒绝静默空跑" % (__name__, name, last))


def _host_attr(mod: str, attr: str):
    """宿主模块属性 —— 真源「函数内 `from ..<mod> import <attr>`」的同义替身（调用时解析）。"""
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
    """宿主模块替身（`C` / `db`）——`C.xxx` / `db.xxx` 正文一字未改，属性访问时解析。"""

    def __init__(self, name):
        self._name = name

    def __getattr__(self, attr):
        return getattr(_host_module(self._name), attr)


C = _HostMod("content")     # 真源 `from .. import content as C`
db = _HostMod("db")         # 真源 `from .. import db`


# v140 波2：3 个新条件类型注册（数据已有零消费点或最小接线）
# 与 achievement_conds.py 共用 COND_CHECKS 单例：本模块 import 它再注册，cond_met 同 dict 生效。
try:
    from .achievement_conds import COND_CHECKS as _COND_CHECKS
except Exception:
    _COND_CHECKS = None


def _register_cond(key):
    """向 COND_CHECKS 注册条件判定（v140 波2 新增类型）。"""
    def deco(fn):
        if _COND_CHECKS is not None:
            _COND_CHECKS[key] = fn
        return fn
    return deco


@_register_cond("blueprints_learned")
def _c_blueprints_learned(player, stats, profs, extra, cond):
    """已学习图纸数（v140 波2：读 players.learned_blueprints 长度，数据已有零消费点）"""
    return len(player.get("learned_blueprints") or []) >= cond.get("value", 0)


@_register_cond("quests_done")
def _c_quests_done(player, stats, profs, extra, cond):
    """累计完成任务数（v140 波2：读 quests.completed_main + side done 计数，数据已有零消费点）"""
    gid = extra.get("_group_id")
    if not gid:
        return False
    try:
        q = db.get_quests(gid, player["qq_id"])
    except Exception:
        return False
    if not q:
        return False
    done = len(q.get("completed_main") or [])
    for _s in (q.get("side") or {}).values():
        if isinstance(_s, dict) and _s.get("status") == "done":
            done += 1
    return done >= cond.get("value", 0)


@_register_cond("chests_opened")
def _c_chests_opened(player, stats, profs, extra, cond):
    """累计开启宝箱数（v140 波2：读 stats.chests_opened——stats 新列 +
    item_templates.py tpl_open_chest 一行 bump 接线；无列时 get 兜底 0 不报错）"""
    return int(stats.get("chests_opened", 0) or 0) >= cond.get("value", 0)


def _bestiary_kills(qq_id, keyword) -> int:
    """bestiary 按怪物名关键词统计击杀数"""
    try:
        rows = db.get_bestiary("", qq_id)
    except Exception:
        return 0
    total = 0
    for r in rows:
        name = C.display("monsters", r["monster"])
        if keyword in (name or ""):
            total += int(r.get("kills", 0) or 0)
    return total


def _monster_total() -> int:
    """地图怪物去重总数(图鉴全解锁判定)"""
    try:
        ids = set()
        for mid, m in C.MAP_BY_ID.items():
            for mon in (m.get("monsters") or []):
                if isinstance(mon, dict):
                    ids.add(mon.get("id") or mon.get("name"))
                else:
                    ids.add(mon)
        return max(len(ids), 100)
    except Exception:
        return 150


def cond_met(player: dict, stats: dict, profs: dict, extra: dict, cond: dict, group_id: str = None) -> bool:
    """成就条件判定。extra 携带事件上下文(inst_id/flawless/worldboss/flags 等)
    v99.5：判定逻辑数据化 → core/achievement_conds.py COND_CHECKS 注册表
    （41 种条件类型；未知 type / 异常 → False，与旧 if 链兜底一致）
    v100.3b：新增可选 group_id —— 非 None 时注入 extra['_group_id'] 副本，
    供 quest_done/item_has 查询任务/背包（原代码引用未定义 group_id → 恒 False 的历史 bug）"""
    try:
        from .achievement_conds import COND_CHECKS
        fn = COND_CHECKS.get(cond.get("type"))
        if fn is None:
            return False
        if group_id is not None and extra.get("_group_id") is None:
            extra = dict(extra)
            extra["_group_id"] = group_id
        return fn(player, stats, profs, extra, cond)
    except Exception:
        return False


def achievement_titles(qq_id) -> list:
    """已解锁成就的称号名列表(14 章：达成成就自动获得称号)"""
    try:
        rows = db.get_achievements("", qq_id)
        unlocked = {r["ach_key"] for r in rows}
    except Exception:
        return []
    return [a["title"] for a in C.ACHIEVEMENTS if a["id"] in unlocked and a.get("title")]


def achievement_points(qq_id) -> int:
    """成就点(普通 1 / 隐藏 2)。

    ⚠️ 14 章四「成就等级体系（青铜→传奇）」待后续版本，未实装：当前只算点数，
    无等级划分/等级称号/等级加成。（v105 M18 P2 标注）
    """
    try:
        rows = db.get_achievements("", qq_id)
        unlocked = {r["ach_key"] for r in rows}
    except Exception:
        return 0
    return sum(2 if a.get("cat") == "隐藏" else 1 for a in C.ACHIEVEMENTS if a["id"] in unlocked)


def check_achievements(group_id, qq_id, player=None, extra=None) -> list:
    """通用成就判定：事件后调用。返回本次新解锁的成就(dict)列表。

    v101.22（鱼鱼拍板）：解锁不再自动发奖励——改为待领取(claimed=0)，
    玩家用『成就 领取』手动领。奖励数值同步下调(新手期 500→100)。
    返回的成就 dict 带 _reward_txt 供调用方提示。
    """
    try:
        if player is None:
            player = db.get_player(group_id, qq_id)
        if not player:
            return []
        player["qq_id"] = player.get("qq_id") or qq_id
        stats = db.get_stats(group_id, qq_id) or {}
        profs = db.get_professions(group_id, qq_id) or {}
        extra = extra or {}
        unlocked = set()
        try:
            rows = db.get_achievements("", qq_id)
            unlocked = {r["ach_key"] for r in rows}
        except Exception:
            pass
        # 已通关副本集合（inst_clear_* 记录）
        inst_ids = set()
        for aid in unlocked:
            if str(aid).startswith("inst_clear_"):
                inst_ids.add(str(aid)[len("inst_clear_"):])
        if extra.get("inst_id"):
            inst_ids.add(extra["inst_id"])
        extra["inst_ids"] = inst_ids
        new_ones = []
        for a in C.ACHIEVEMENTS:
            if a["id"] in unlocked:
                continue
            if cond_met(player, stats, profs, extra, a["cond"], group_id):
                try:
                    db.set_achievement(group_id, qq_id, a["id"], 1, 0)  # claimed=0 待领取
                except Exception:
                    continue
                unlocked.add(a["id"])
                rw = a.get("reward") or {}
                if rw.get("exp") or rw.get("gold") or rw.get("items"):
                    parts = []
                    if rw.get("exp"):
                        parts.append(f"经验+{rw['exp']}")
                    if rw.get("gold"):
                        parts.append(f"金币+{rw['gold']}")
                    # v140 波2：物品奖励进解锁提示（《物品名》×N）
                    if rw.get("items"):
                        for _ik, _ic in rw["items"].items():
                            _nm = _ik
                            try:
                                _nm = (ITEMS.get(_ik) or C.MATERIALS.get(_ik) or {}).get("name", _ik)
                            except Exception:
                                pass
                            parts.append(f"{_nm}×{_ic}")
                    a = dict(a)
                    a["_reward_txt"] = "、".join(parts) + "（『成就 领取』领取）"
                else:
                    a = dict(a)
                    a["_reward_txt"] = ""
                new_ones.append(a)
        return new_ones
    except Exception:
        LOG = _host_attr("log_setup", "LOG")
        LOG.warning("[dragonfall] check_achievements 异常，成就列表降级为空", exc_info=True)
        return []


def claim_achievement_rewards(group_id, qq_id) -> tuple:
    """领取全部待领取的成就奖励(经验/金币/物品)。返回 (lines, err) 供命令输出。

    v101.22：成就解锁后奖励待领取，玩家手动『成就 领取』时统一发放，
    发放走 check_player_level_up 正常结算升级。未解锁/无奖励成就忽略。
    v140 波2（成就/称号/收藏资源化 3.9）：reward 新增 items 物品奖励
    （{item_key: count}），与经验/金币一同发放——db.add_item 入包，
    物品 key 走 _key_to_id 兼容中文名；发放失败静默跳过（物品缺失不影响其他奖励）。
    """
    check_player_level_up = _host_attr("content_rules.gameplay", "check_player_level_up")
    stat_bonus = _host_attr("core.stat_bonus", "stat_bonus")   # ← B13-L6 线落地后切包内直取
    try:
        rows = db.get_achievements(group_id, qq_id) or []
        pending = [r for r in rows if not r.get("claimed")]
        if not pending:
            return [], "没有待领取的成就奖励～"
        # 过滤出真正带奖励的待领成就
        claimable = []
        for r in pending:
            a = next((x for x in C.ACHIEVEMENTS if x["id"] == r["ach_key"]), None)
            # v105.xx P0 修复：原 `if a and X or Y` 优先级错误——a=None（如 inst_clear_* 记录
            # 不在 C.ACHIEVEMENTS 中）时 `or` 右侧仍求值 a.get() → AttributeError 崩溃。
            # 显式括号：a 为 None 时短路，不进入。
            if a and (((a.get("reward") or {}).get("exp", 0)) or ((a.get("reward") or {}).get("gold", 0))
                      or ((a.get("reward") or {}).get("items"))):
                claimable.append(a)
        if not claimable:
            # 没有奖励的成就直接标记已领取，避免永久挂起
            for r in pending:
                try:
                    db.set_achievement(group_id, qq_id, r["ach_key"], r.get("progress", 1), 1)
                except Exception:
                    pass
            return [], "没有待领取的成就奖励～"
        player = db.get_player(group_id, qq_id)
        if not player:
            return [], "请先注册角色～"
        player = dict(player)
        # K0-A1：复用统一单点 stat_bonus()（含 M18 同名去重 + TITLES 侧 bonus），
        # 不再用轻量 _title_bonus_plain——避免 Lv.10 副业大师称号被当作第二份双算。
        player["_title_bonus"] = stat_bonus(group_id, qq_id, player)
        exp_gain = sum((a.get("reward") or {}).get("exp", 0) for a in claimable)
        gold_gain = sum((a.get("reward") or {}).get("gold", 0) for a in claimable)
        # v140 波2：物品奖励统一收集 → 发放（失败静默跳过，不阻塞经验/金币/升级）
        # v174 统一抽象：物品发放走 game.reward.grant_items_batch（与任务/对话/收藏同一实现）
        item_lines = []
        _reward_ok = True
        _all_items = {}
        for a in claimable:
            for ik, ic in ((a.get("reward") or {}).get("items") or {}).items():
                _all_items[ik] = int(_all_items.get(ik, 0)) + int(ic)
        if _all_items:
            try:
                grant_items_batch = _host_attr("reward", "grant_items_batch")
                item_lines, _reward_ok = grant_items_batch(group_id, qq_id, _all_items, lines=item_lines)
            except Exception:
                _reward_ok = False
        player["exp"] = player.get("exp", 0) + exp_gain
        player["gold"] = player.get("gold", 0) + gold_gain
        lv_logs, player = check_player_level_up(group_id, qq_id, player)
        db.update_player(group_id, qq_id,
                         exp=player["exp"], gold=player["gold"], level=player["level"],
                         hp=player["hp"], mp=player["mp"], max_hp=player["max_hp"], max_mp=player["max_mp"],
                         skills=player["skills"], attr_pts=player.get("attr_pts", 0),
                         skill_points=player.get("skill_points", 0),
                         learned_skills=player.get("learned_skills", []))
        for a in claimable:
            db.set_achievement(group_id, qq_id, a["id"], 1, 1)
        lines = [f"🎁 成就奖励领取！经验 +{exp_gain}" + (f" 金币 +{gold_gain}" if gold_gain else "")]
        if item_lines:
            lines.append("🎒 获得物品：")
            lines += item_lines
            if not _reward_ok:
                lines.append("(部分物品发放失败，可联系管理)")
        for a in claimable:
            lines.append(f"🏅 {a['name']}")
        lines.append("")
        lines += lv_logs
        return lines, ""
    except Exception as e:
        LOG.warning(f"[dragonfall] 成就领取失败: {e}")
        return [], "领取失败，稍后再试试～"
