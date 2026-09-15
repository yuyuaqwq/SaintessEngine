# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— 对话条件注册表（B13 线3，2026-09-14）。

真源：游戏仓 `game/core/dialogue_conds.py`（210 行）。本模块 = 那个模块的**实现本体**
（`CONDITIONS` + `register` + `_quest_state` + 18 个条件函数逐字搬）；
宿主 `game/core/dialogue_conds.py` 只剩再导出（`content/dialogue.py` 与
`tests/test_v98_03_registry.py:34` 的 import 点零改动）。

消灭 core/dialogue.py check_need() 里的 if-elif 硬编码：
对话数据只声明 need dict（key → 值），判定统一走本模块注册表。

扩展方式：
- 加条件类型：register 一个函数（~5 行），之后所有对话数据直接可用
- 函数签名：fn(ctx: dict, v) -> bool，ctx 由 check_need 原样传入
  （player/quests/flags/apprentices/npc_id/side_quests/item_counts）
v113 新增条件键：race_is/hidden_unlocked/hidden_current/not_hidden_current/side_available。

正文改动面（**只有两类**，都是「宿主取件 → 包内读口/直取」）
----------------------------------------------------------
| 真源写法 | 包内替身 | 说明 |
|---|---|---|
| `from ..data import MAIN_QUESTS`（`_quest_state` 内） | `_main_quests()`：包内 `quests` 域 `source=="main"` 子集 | 真源消费是「按 id 扫表」⇒ 顺序无语义；与 `content/quests_flow.py:264` 同口径（实测 70 条 id 全等 + 逐条逐值相等） |
| `from .. import content as C` → `C.CLASS_NOVICE`（`_c_is_novice` / `_c_not_novice` 内） | 模块级 `from .tables import CLASS_NOVICE`（`content/tables.py:45`，包内读口） | 逐值相等实测：`host cls_novice == pkg cls_novice` ✅ |

等价证据：`overnight/w1213_b13l3_snap.py`（E1–E3：CONDITIONS 键集 + `_quest_state` 11 态
+ 未知键）与 D3/D3b（`check_need` 25 组真值矩阵，含测试模式 raise）· `overnight/W-B13-L3-events-dialogue.md`。
"""
from __future__ import annotations

import json
import os

from .tables import CLASS_NOVICE      # 包内读口（真源 `C.CLASS_NOVICE`）

_HERE = os.path.dirname(os.path.abspath(__file__))          # <pkg>/content


def _read_domain(domain: str, sub: str = "data", default=None):
    """读包内 `content/<sub>/<domain>.json`（缺文件 / 坏 JSON → default，不抛）。"""
    try:
        with open(os.path.join(_HERE, sub, "%s.json" % domain), encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                       # noqa: BLE001
        return {} if default is None else default


_MAIN_QUESTS = None


def _main_quests() -> list:
    """包内 `quests` 域主线子集（真源 `from ..data import MAIN_QUESTS`，按 id 扫表 ⇒ 顺序无关）。"""
    global _MAIN_QUESTS
    if _MAIN_QUESTS is None:
        raw = _read_domain("quests")
        _MAIN_QUESTS = [v for v in raw.values() if v.get("source") == "main"]
    return _MAIN_QUESTS


CONDITIONS = {}


def register(key):
    """条件注册装饰器。"""
    def deco(fn):
        CONDITIONS[key] = fn
        return fn
    return deco


def _quest_state(quests, qid: str, status, ctx=None) -> bool:
    """主线状态判断：quests dict + qid + 期望状态
    qid 为空字符串 → 按"当前主线"动态判断（对话树通用接取/交付选项用）
    v101.23：动态判断时校验"当前主线发布者 == 对话中的 NPC"——
    否则镇长会在主线已推进到其他 NPC 发布的任务时，仍显示接取/交付选项，
    念的还是写死的旧任务台词（史莱姆）。"""
    if not quests:
        return False
    if status == "done":
        return qid in (quests.get("completed_main") or [])
    target = quests.get("main_quest") if not qid else qid
    if not target:
        return False  # 主线全完成/未设置时，无"当前主线"可言
    if quests.get("main_quest") != target:
        return False
    # v101.23：动态"当前主线"场景 → 校验 giver == 当前 NPC
    if not qid:
        MAIN_QUESTS = _main_quests()        # 真源 `from ..data import MAIN_QUESTS`
        mq = next((q for q in MAIN_QUESTS if q["id"] == target), None)
        npc_id = (ctx or {}).get("npc_id")
        if mq and npc_id and mq.get("giver") != npc_id:
            return False
    cur = quests.get("main_status", "pending")
    if status == "active":
        return cur in ("active", "ready")
    if status == "pending":
        return cur == "pending"
    if status == "ready":
        return cur == "ready"
    return False


# ================= 条件实现 =================

@register("quest_done")
def _c_quest_done(ctx, v):
    return _quest_state(ctx.get("quests") or {}, v, "done", ctx)


@register("not_quest_done")
def _c_not_quest_done(ctx, v):
    """该主线未完成（反向条件，用于隐藏已完成任务相关的旧话题/旧选项）"""
    done = (ctx.get("quests") or {}).get("completed_main") or []
    return v not in done


@register("quest_active")
def _c_quest_active(ctx, v):
    return _quest_state(ctx.get("quests") or {}, v, "active", ctx)


@register("quest_pending")
def _c_quest_pending(ctx, v):
    return _quest_state(ctx.get("quests") or {}, v, "pending", ctx)


@register("quest_ready")
def _c_quest_ready(ctx, v):
    return _quest_state(ctx.get("quests") or {}, v, "ready", ctx)


@register("side_ready")
def _c_side_ready(ctx, v):
    """该 NPC 名下有待交付的支线（击杀/探索型 ready，收集型材料齐）"""
    if not v:
        return True
    quests = ctx.get("quests") or {}
    side = quests.get("side") or {}
    if not side:
        return False
    npc_id = ctx.get("npc_id") or ""
    for sid, sq in side.items():
        sqd = next((q for q in (ctx.get("side_quests") or []) if q["id"] == sid), None)
        if not sqd or sqd.get("giver") != npc_id:
            continue
        if sq.get("status") == "done":  # v95.12：已交付支线不重复提示
            continue
        obj = sqd.get("objective", {})
        if obj.get("collect"):
            have = ctx.get("item_counts") or {}
            # v104 M20 P2：收集门槛统一 collect_count 优先（与 world.py 面板/交付一致；
            # 复合目标如魔剑士试炼 collect_count=2/count=3，旧口径 count 会要求 3 份才显示可交）
            if have.get(obj["collect"], 0) >= obj.get("collect_count", obj.get("count", 1)):
                return True
        elif sq.get("status") == "ready":
            return True
    return False


@register("side_available")
def _c_side_available(ctx, v):
    """该 NPC 名下存在未接取的支线（告示板委托除外——告示委托只能在告示板接取）

    v95r65 #288：对话树『有活儿要交给我吗』类选项用它替代 quest_pending——
    此前玛莎（非主线 giver）选项显示条件用 quest_pending(任意主线待接)，
    点选后 quest_take 只处理主线 → 报"我现在没有任务交给你"误导文案。
    """
    if not v:
        return True
    quests = ctx.get("quests") or {}
    side = quests.get("side") or {}
    npc_id = ctx.get("npc_id") or ""
    for sq in (ctx.get("side_quests") or []):
        if sq.get("giver") != npc_id or sq.get("board"):
            continue
        if sq["id"] in side:
            continue
        return True
    return False

@register("quest_any_active")
def _c_quest_any_active(ctx, v):
    """当前存在任意进行中主线（对话树指引用）"""
    quests = ctx.get("quests") or {}
    return bool(quests.get("main_quest"))


@register("apprentice")
def _c_apprentice(ctx, v):
    """已拜师该副业"""
    return v in (ctx.get("apprentices") or [])


@register("not_apprentice")
def _c_not_apprentice(ctx, v):
    """未拜师该副业（拜师选项只在未拜师时显示）"""
    return v not in (ctx.get("apprentices") or [])


@register("is_novice")
def _c_is_novice(ctx, v):
    """仅见习冒险者可见（行会就职选项）"""
    player = ctx.get("player") or {}
    return player.get("class_name") == CLASS_NOVICE    # 真源 `C.CLASS_NOVICE`（包内读口）


@register("not_novice")
def _c_not_novice(ctx, v):
    """已就职（非见习）才可见"""
    player = ctx.get("player") or {}
    return player.get("class_name") != CLASS_NOVICE    # 真源 `C.CLASS_NOVICE`（包内读口）


@register("class_any")
def _c_class_any(ctx, v):
    """玩家职业在列表中才可见（导师对话按职业过滤）"""
    player = ctx.get("player") or {}
    return player.get("class_name") in v


@register("race_is")
def _c_race_is(ctx, v):
    """v113 种族限制：玩家种族 == 指定种族（隐藏线导师·血脉传承对话）"""
    player = ctx.get("player") or {}
    return (player.get("race") or "human") == v


@register("hidden_unlocked")
def _c_hidden_unlocked(ctx, v):
    """v113：已解锁指定隐藏线（hidden_class_unlock 含 cls_id）——导师对话『接受传承』门槛"""
    player = ctx.get("player") or {}
    return v in (player.get("hidden_class_unlock") or [])


@register("hidden_current")
def _c_hidden_current(ctx, v):
    """v113：当前职业已是该隐藏线（传承完成后的闲聊分支/提示满阶）"""
    player = ctx.get("player") or {}
    return player.get("class_name") == v


@register("not_hidden_current")
def _c_not_hidden_current(ctx, v):
    """v113：当前职业尚未是该隐藏线（『接受传承』选项只在未传承时显示；
    已传承玩家再点会走 _evolve_hidden_generic 的"你已是X"分支，双保险）"""
    player = ctx.get("player") or {}
    return player.get("class_name") != v

@register("evolve_ready")
def _c_evolve_ready(ctx, v):
    """到达转职等级门槛（{tier: 目标阶, level: 需要等级}）"""
    player = ctx.get("player") or {}
    if player.get("class_tier", 0) != int(v.get("tier", 0)):
        return False
    return int(player.get("level", 0) or 0) >= int(v.get("level", 0))
