# -*- coding: utf-8 -*-
"""宿主运行时 · 战斗记账形状（`Scenario` / `BattleOutcome` / 替身袋子）。

**通用形状**：一场战斗的输入数据（调用方给）、一场战斗的账（数字全部来自引擎事件，
这里不自己算）、以及给包内策略半边用的「替身袋子」。

零游戏知识：本模块不知道任何职业/怪物/池名 —— 键名与包内域同名就现读该域，
读不到给中性值（`None`），**绝不编数字**。
"""
from __future__ import annotations

import random

from ..clock.wall import today as _wall_today      # 挂钟单一出口纪律：日期只许经 clock/


def _read_json(path, default=None):
    from ..package import read_json
    return read_json(path, default)


class Scenario:
    """一场战斗的**输入数据**（调用方给；内容侧以后可从流程里产）。

    为什么它是「数据」不是「逻辑」：宿主不挑怪、不算数值、不选池 —— 这三件事都是内容策略。
    """

    def __init__(self, player=None, enemies=None, rewards=None, event_state=None, btype="monster"):
        self.player = dict(player or {})
        self.enemies = list(enemies or [])
        self.rewards = list(rewards or [])           # [{"pool": 池key, "ctx": {...}}]
        self.event_state = dict(event_state or {})   # 包内桥的 event_state 替身（普通 dict）
        self.btype = str(btype or "monster")

    @classmethod
    def from_dict(cls, data) -> "Scenario":
        data = data or {}
        return cls(data.get("player"), data.get("enemies"), data.get("rewards"),
                   data.get("event_state"), data.get("btype") or "monster")

    @classmethod
    def from_file(cls, path) -> "Scenario":
        return cls.from_dict(_read_json(path, {}))


class BattleOutcome:
    """一场战斗的账：结果 / 伤害数字 / 事件序列 / 日志 / 掉落（若包已进包）。"""

    HIT_EVENTS = ("attack_hit", "skill_hit")

    def __init__(self, result="", damage=0, hits=None, events=None, log=None,
                 loot=None, stubs=None, settlement=None, elapsed=0.0):
        self.result = result
        self.damage = int(damage or 0)
        self.hits = list(hits or [])          # [{"event", "by", "to", "dmg", "crit"}]
        self.events = list(events or [])      # 引擎事件名序列（含 battle_start / act_done）
        self.log = list(log or [])            # 引擎已渲染的战场日志（宿主只投递）
        self.loot = list(loot or [])          # 掉落产出（池 key 由场景给；发放属宿主）
        self.settlement = dict(settlement or {})   # 结算计划（包内 settlement；经验/金币）
        self.stubs = list(stubs or [])        # 留桩说明（包内半边未进包时写清位置）
        self.elapsed = float(elapsed or 0.0)

    @property
    def actors(self) -> dict:
        return {"hits": len(self.hits), "events": len(self.events)}

    def summary(self) -> str:
        line = ("battle=%s damage=%d hits=%d events=%d loot=%d"
                % (self.result or "?", self.damage, len(self.hits), len(self.events), len(self.loot)))
        if self.settlement:
            line += " exp=%s gold=%s" % (self.settlement.get("exp"), self.settlement.get("gold"))
        if "battle_start" in self.events and "act_done" in self.events:
            line += " (battle_start→act_done ✅)"
        if self.stubs:
            line += " stubs=%d" % len(self.stubs)
        return line


class StandIns(dict):
    """宿主替身袋子：包内要什么读什么，**宿主没有的给中性值**（None）。

    * 键名与包内某个域同名 → 现读包内该域（`content/<data|rules>/<域>.json`）
    * `final_stats` → 引擎**已挂**的面板 hook（`config.get_hook("panel_fn")`）按引擎契约算好的面板
    * 其余键（宿主自己没有的东西）→ None
      —— 骨架**不抄**包模块那份键清单（那是包的事）；缺什么包自己会喊，
      喊不出来（异常）就由调用方记桩，**不编数字**。
    """

    def __init__(self, pkg, host, player: dict, uid: str = ""):
        super().__init__()
        for name in pkg.domains:
            self[name] = pkg.domain(name)
        self["party_members"] = [uid] if uid else []
        self["now"] = host.clock()
        self["today"] = _wall_today().isoformat()
        self["rng"] = random.Random(host.seed) if host.seed is not None else random.Random()
        from .. import config as engine_config
        panel = engine_config.get_hook("panel_fn")
        if callable(panel):
            try:
                self["final_stats"] = panel(player.get("class_name"), int(player.get("level", 1) or 1),
                                            player.get("equipment") or {},
                                            int(player.get("class_tier", 0) or 0),
                                            player.get("attributes"),
                                            int(player.get("evolve_path", 0) or 0), {}, player.get("race"))
            except Exception:                                    # noqa: BLE001
                self["final_stats"] = {}

    def __missing__(self, key):                                  # 未知键 → 中性值（不炸）
        return None
