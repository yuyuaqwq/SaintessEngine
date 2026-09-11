# -*- coding: utf-8 -*-
"""《铆炉回声》——唯一装配入口。

两件事，都幂等：

    install_engine()          全局：把公式/面板/技能表/kind 词表/声明表挂进引擎 config
    apply_game_content(actor) 单个 actor：把资源渠道 / 机制 / 被动 proc 翻成 triggers

方向只有一个：**内容 → 引擎**。引擎不 import 本包，也不认识本包的表；
它只在需要时问 config 要 hook（要不到就按「零默认值」处理）。

⚠️ 本文件只 import `battle2`（引擎公开 API）与自己的 content；
不碰 game.data / game.services / game.content_rules / game.content（那是奥兰迪亚）。
"""
from __future__ import annotations

from battle2 import config

from .data import classes as C
from .data import monsters as M
from .data import rules as R
from .data import skills as S
from .mech import actions as _actions  # noqa: F401  import 即注册本游戏的动词

_MOUNTED = False

# 渠道名 → 引擎事件名（本平台的攒取时机表；引擎不读，这是内容侧约定）
_CHANNEL_EVENTS = {
    "attack_hit": "attack_hit",
    "skill_hit": "skill_hit",
    "taken": "on_taken",
    "tick": "time_advance",
}


def _lazy_mount():
    """引擎首次读未装配 hook 时的自举。

    ⚠️ 必须覆盖 game 包登记的那套装配器（它会把整份《奥兰迪亚》拉起来）——
    这正是「第三方自己接管注入面」的示范。
    """
    install_engine()


def install_engine() -> None:
    """把本游戏配置挂进引擎（幂等）。"""
    global _MOUNTED
    if _MOUNTED:
        return
    from battle2 import formulas as _formulas

    config.register_defaults_loader(install_engine)
    config.register_hook_provider(_lazy_mount)
    config.mount(
        formulas=_formulas,                                # 引擎自带纯公式模块
        kinds=R.KIND_NAMES,                                # 本游戏的 kind 词表
        panel_fn=C.class_panel,                            # 职业面板
        skill_lookup=S,                                    # .skill_info / .skill_by_key
        monster_skill_fn=S.monster_skill,
        basic_skill_fn=S.basic_skill,
        basic_fallback={"name": "应急撬棍", "kind": R.KIND_NAMES["phys"],
                        "exprs": ["atk*1.0"]},
        formula_skeleton_fn=lambda: R.FORMULA_SKELETON,     # formulas 的参数表
        skill_flat_fn=lambda: R.SKILL_FLAT,
        skill_up_fn=lambda info: {},                        # 本游戏不做技能等级成长
        skill_level_of_fn=lambda player, skill_name: 1,
    )
    config.load_game_rules(R)   # EFFECT_ACTIONS / EFFECT_RULES
    _MOUNTED = True


def apply_game_content(actor: dict) -> None:
    """内容入口：把本游戏内容挂到 actor 上（幂等，重复调用不叠加）。"""
    if not isinstance(actor, dict):
        return
    install_engine()
    _assemble_resources(actor)
    _assemble_mechanics(actor)
    _assemble_passives(actor)


# ------------------------------------------------------------
# 装配器：声明 → actor["triggers"]
# ------------------------------------------------------------

def _assemble_resources(actor: dict) -> None:
    """按 EFFECT_RULES[key]["start_classes"] 归属过滤，装 channels 为触发声明。"""
    cls = actor.get("class_name")
    if not cls:
        return
    trig = actor.setdefault("triggers", {})
    for key, rule in R.EFFECT_RULES.items():
        starts = rule.get("start_classes") or []
        if not starts or cls not in starts:
            continue        # 不声明归属 / 不归本职业 → 不装（防误加）
        for chan, decl in (rule.get("channels") or {}).items():
            event = _CHANNEL_EVENTS.get(chan)
            if not event:
                continue    # 未知渠道名 → 静默跳过（内容侧约定表里没有的）
            if isinstance(decl, (int, float)):
                gain, when, per_dt = decl, [], False
            else:
                gain = decl.get("gain") or 0
                when = decl.get("when") or []
                per_dt = bool(decl.get("per_dt"))
            _append_once(trig, event, {"action": "res_gain", "key": key, "gain": gain,
                                       "when": when, "per_dt": per_dt})


def _assemble_mechanics(actor: dict) -> None:
    """机制触发条件（本示例只在铆炉匠身上挂一条）。

    顺序契约：这条挂在资源渠道**之后**，所以它读到的是本次命中刚 +1 后的层数。
    """
    if actor.get("class_name") != "cls_kiln":
        return
    trig = actor.setdefault("triggers", {})
    _append_once(trig, "attack_hit",
                 {"action": "heat_vent", "key": "kiln",
                  "per_layer": 3, "min_layers": 3, "spend": 2})


def _assemble_passives(actor: dict) -> None:
    """PASSIVE_PROC → triggers（引擎不读这张表，是本包自己认的约定）。"""
    cls = actor.get("class_name")
    trig = actor.setdefault("triggers", {})
    for proc in R.PASSIVE_PROC.values():
        starts = proc.get("start_classes") or []
        if starts and cls not in starts:
            continue
        event = proc.get("event")
        action = proc.get("action")
        if not event or not action:
            continue
        entry = {"action": action}
        entry.update(proc.get("params") or {})
        _append_once(trig, event, entry)


def _append_once(trig: dict, event: str, entry: dict) -> None:
    """幂等追加：同事件下已有同内容的声明就不再挂（开战仪式可能被调多次）。"""
    lst = trig.setdefault(event, [])
    for exist in lst:
        if all(exist.get(k) == entry[k] for k in entry):
            return
    lst.append(entry)


__all__ = ["install_engine", "apply_game_content"]
