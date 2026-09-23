# -*- coding: utf-8 -*-
"""《铆炉回声》——**战斗构造半边**（包内对宿主契约的实现）。

宿主只认一个可选半边：`<entry 同级模块>/bridge.py`（本包 entry = `content/apply.py`
⇒ 引擎找 `content/bridge.py`）。缺了它，`Host.run_battle` 无路可走、只能 fail-closed：

    包 X 既无 content/bridge.py 也无 entry.build_sides —— 无法开战

本文件补的就是这一半 —— 一个函数：

    build_sides(player, enemies) -> {"player": [actor, ...], "enemy": [actor, ...]}

契约顺序（引擎 `saintess_engine/host/runtime.py::Host.run_battle`）：
  ① 宿主调 `build_sides` 拿**两侧 actor**；
  ② 宿主逐个调 `content.apply.apply_game_content(actor)` 装内容（**不是**本文件的事 ——
     本文件只搬数据，不挂 hook，也不调 install_engine）；
  ③ 宿主构造 `Battle(sides=...)` 跑完；回写半边（actor → 存档）也在宿主。

零宿主知识、零其他游戏词汇：只 import 引擎公开 API（`make_actor`）与本包自己的
模板/工厂（`data/classes.py` / `data/monsters.py`）。要换成另一个游戏，换的是这个文件，
引擎与宿主一行不改 —— 这就是「宿主不认任何具体包」的证明。
"""
from __future__ import annotations

from ext_combat import make_actor

from .data.classes import CLASSES, build_player
from .data.monsters import MONSTERS, build_monster

#: 直接透传成 actor 面板的字段（场景直给数值的「无模板」路径用）
_STAT_KEYS = ("hp", "max_hp", "mp", "max_mp", "atk", "matk", "def", "mdef", "spd",
              "crit", "dodge", "crit_dmg", "luck", "tenacity", "block", "pene")

#: 调用方（存档 / 场景）显式给了就覆盖模板值的键；`None` = 「没给」。
_OVERRIDE_KEYS = (
    # 身份 / 面板配置
    "name", "level", "class_name", "skills", "learned_skills", "equipment",
    "attributes", "class_tier", "evolve_path", "race",
    # 战斗可变状态（存档续战：接着上次的血量与效果打）
    "hp", "max_hp", "mp", "max_mp", "effects", "shields", "cooldown",
    "charging", "defending", "ct", "poi_buff",
    # 怪的数据标签 / 行为
    "ai", "auto_act", "rank", "role", "reach", "is_boss", "is_elite",
    "exp", "gold", "drops", "resource_def", "triggers",
) + _STAT_KEYS


def _given(src: dict, keys) -> dict:
    """从 `src` 里挑出**显式给了值**的键（`None` / 缺省都算没给）。"""
    return {k: src[k] for k in keys if src.get(k) is not None}


def _overlay(actor: dict, src: dict) -> dict:
    """把调用方显式给的字段盖到 actor 上（幂等；不删 actor 已有的播种键）。"""
    for key, value in _given(src, _OVERRIDE_KEYS).items():
        actor[key] = value
    return actor


def player_to_actor(player: dict) -> dict:
    """玩家**存档 dict** → 引擎 actor。

    * 有本包认识的 `class_name` → 走包内面板工厂 `classes.build_player`（面板/技能随之定）；
    * 没有（宿主侧最小档 / 纯字段档）→ 通用透传，面板字段由调用方给。
    两种路径之后都 `_overlay`：存档里的血量/状态优先（「接着上次的档打」）。
    """
    src = dict(player or {})
    uid = str(src.get("uid") or src.get("id") or "p1")
    name = str(src.get("name") or uid)
    level = int(src.get("level", 1) or 1)
    cls = src.get("class_name")
    if cls in CLASSES:
        actor = build_player(cls, uid, name, level=level)
    else:
        actor = make_actor(uid, name, "player", kind="player", human_controlled=True,
                           class_name=cls, level=level, **_given(src, _STAT_KEYS))
    return _overlay(actor, src)


def monster_to_actor(mon: dict, idx: int = 0) -> dict:
    """怪 dict → 引擎 actor。

    * 带本包模板 key（`key` / `id`，如场景只写「打哪只」）→ 包内模板工厂
      `monsters.build_monster`（数值 / 技能 / AI 随之带上）；
    * 否则（调用方直给完整数值）→ 通用透传。
    场景显式给的字段（血量 / 技能 / AI …）覆盖模板值。
    """
    src = dict(mon or {})
    uid = str(src.get("uid") or ("e%d" % (idx + 1)))
    key = src.get("key") or src.get("id")
    if key in MONSTERS:
        actor = build_monster(str(key), uid)
    else:
        actor = make_actor(uid, str(src.get("name") or uid), "enemy", kind="monster",
                           level=int(src.get("level", 1) or 1),
                           skills=list(src.get("skills") or []),
                           ai=src.get("ai"), **_given(src, _STAT_KEYS))
    return _overlay(actor, src)


def build_sides(player=None, enemies=None) -> dict:
    """★ 宿主契约入口：把「玩家档 + 敌组数据」翻成引擎 `sides`（唯一容器的唯一形状）。"""
    sides: dict = {"player": [], "enemy": []}
    if isinstance(player, dict) and player:
        sides["player"].append(player_to_actor(player))
    sides["enemy"] = [monster_to_actor(mon, i) for i, mon in enumerate(enemies or [])]
    return sides


__all__ = ["build_sides", "player_to_actor", "monster_to_actor"]
