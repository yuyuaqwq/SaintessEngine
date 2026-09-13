# -*- coding: utf-8 -*-
"""《奥兰迪亚》战斗流水**采集半边** —— 战斗事件/人类行动 → 流水（P4-D3 搬运物，逐字保真）。

真源：游戏仓 `C:/Users/yuyu/qqbot/data/plugins/dragonfall/game/services/battle_tlog.py`
      **全文件 321 行**；本文件 = 真源 `:12-242` 的**逐字节拷贝**，正文一字未改
      （对拍见 `overnight/d3_tlog_verify.py` A1：真源正文 ↔ 本文件正文 逐行 diff 为空）。

切片口径（一条分界线：真源 :245 `# ==== 回放`）
  · **采集半边 = 本文件**：`BattleTLog`（链 `battle.on_event` / 包 `human_act` / 包 `act`
    → 把战斗事件与人类行动成流水）+ `EVENT_KINDS`（引擎事件 → 流水 kind 的映射表，
    框架不认，映射表在内容侧）+ `REPRO_KEYS` + `_uid` / `_num` / `_rounds_of` / `_player_input`。
    **可拔插（红线）**：`tlog=None` 时**全部方法零行为** —— 不链观察者、不包 human_act、不写一个字段。
    **采集不改行为**：观察者与包装都是只读 + 前后串联（既有观察者先跑、异常各自隔离）。
  · **未搬**（清单见 `overnight/d3-tlog-port.md` §3）：
    :245-321 回放半边（`find_battle`/`replay`）—— 依赖宿主重建链
    （`game/services/battle_bridge.py` 的 `prepare_player_for_battle`/`build_sides`/`apply_battle_loadout`）；
    `game/services/tlog_db_sink.py`（155 行）+ `game/tlog_setup.py`（116 行）= **落库半边**
    ——模块归属裁定为**宿主**（`overnight/module-ownership.md:82/102`：采集器 → 包，DB sink → 宿主）。
    ⇒ 包内**不含**任何落库/开关代码：出口（引擎 `JSONLSink`/`MemorySink`，宿主可换 `SQLiteSink`）
    与 `TLog` 实例由**调用方**构造后传进构造函数；本模块只认 `tlog.emit` / `tlog.flush`。

包内依赖（只有引擎，方向单向：内容 → 引擎）
  · `saintess_engine.tlog`（Record / TLog / KindTable 都在引擎侧）
  · **无包内数据依赖**：字段契约表 `content/data/tlogs.json` 由调用方读成 `KindTable` 交给 `TLog`
    （零声明表 = 不校验，与引擎同口径）；本模块不读盘、不写盘。

真源模块 docstring（逐字保留）
------------------------------
'''战斗流水采集与回放（内容侧）—— 框架 `saintess_engine.tlog` 的落地。

设计见 `docs/REFACTOR_tlog_landing.md`。三条纪律：

1. **零引擎改动**：事件走引擎既有观察者通道 `battle.on_event`（fire 尾部通知，只读）；
   行动走包 `human_act`；生命周期由驱动层显式调。不碰引擎、不加专用机制。
2. **可拔插**：`tlog=None` 时**全部方法零行为**（不链观察者、不包 human_act、不写一个字段）。
3. **采集不改行为**：观察者与包装都是**只读 + 前后串联**（既有观察者先跑，异常各自隔离）；
   同 seed 下"开采集 / 不开采集"结果必须一致。
'''
"""
from __future__ import annotations

import random
from typing import Callable, Iterable, Optional

from saintess_engine.tlog import Record

# 引擎事件 → 流水 kind（框架不认，映射表在内容侧）
EVENT_KINDS = {
    "skill_hit": "battle.hit",
    "attack_hit": "battle.hit",
    "crit": "battle.crit",
    "on_taken": "battle.taken",
    "on_heal": "battle.heal",
    "dot_tick": "battle.dot",
    "on_death": "battle.down",
}
REPRO_KEYS = ("class_name", "level", "class_tier", "evolve_path", "attributes",
              "equipment", "learned_skills", "race", "title_bonus", "hp", "mp",
              "max_hp", "max_mp")


def _uid(a) -> str:
    if not isinstance(a, dict):
        return ""
    return str(a.get("uid") or a.get("name") or "")


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _rounds_of(b) -> int:
    """回合数口径 = 行动轮次（`int(_now / ACT_TICK) + 1`，与数值门禁同式）。"""
    return int(_num(getattr(b, "_now", 0)) / 1) + 1


class BattleTLog:
    """一场战斗的流水采集器（`tlog=None` → 全程零行为）。"""

    def __init__(self, tlog=None, *, tags: Iterable[str] = (), name: str = "") -> None:
        self.tlog = tlog
        self.tags = tuple(tags or ())
        self.name = name
        self.enabled = tlog is not None
        self.acts = 0
        self.events = 0
        self._end_sent = False

    # ============================================================ 挂载
    def attach(self, b, *, btype: str = "monster", seed=None, player=None,
               enemies=None, extra: Optional[dict] = None):
        """给一场战斗挂采集：链观察者 + 包 human_act + 写 `battle.start`。

        `player`/`enemies` 记**完整构造输入**（不是指纹）——回放时直接拿来重建，
        这是"能复现同一场"的前提。`seed` 给定时（测试/演练）回放可逐场复现；
        生产战斗不强制改随机流 → `seed=None` 记 `reproducible=False`（诚实记账）。

        ⚠️ **`seed` 的语义 = 「重演起点」**：调用方应在**战斗对象构造完成之后、
        第一次行动之前**取种子并调 `random.seed(seed)`，再 `attach(..., seed=seed)`
        —— 重建会消耗随机（装备生成/洗牌），所以重演端也在同一位置设种子（见 `replay`）。
        """
        if not self.enabled:
            return b
        try:
            b._battle_tlog = self
        except Exception:                                        # noqa: BLE001
            pass
        self._chain_observer(b)
        self._wrap_human_act(b)
        self._wrap_act(b)
        self.on_start(b, btype=btype, seed=seed, player=player, enemies=enemies, extra=extra)
        return b

    def _wrap_act(self, b) -> None:
        """包 `b.act()`（引擎的统一行动入口：人类/AI/随从都走它）—— 行动**跑完后**再看一眼结果。

        为什么必须在这里看：胜负是在 `act()` 内部最后一步 `_check_side_end()` 里才置上的，
        而事件观察者只在该行动产生的**事件**上被叫到 —— 胜负一旦由「不产生事件的那一步」
        决定（例如最后一个怪被打死后的结算），事件侧就再也不会响了。
        （2026-09-13：实测整场打完 0 条 `battle.end`，就是漏在这。）
        """
        orig = getattr(b, "act", None)
        if not callable(orig) or getattr(orig, "_battle_tlog_wrapped", False):
            return

        def wrapped(ctx):
            out = orig(ctx)
            try:
                self._maybe_end(b)
            except Exception:                                    # noqa: BLE001
                pass
            return out

        wrapped._battle_tlog_wrapped = True
        try:
            b.act = wrapped
        except Exception:                                        # noqa: BLE001
            pass

    def _chain_observer(self, b) -> None:
        """把采集挂到既有 `on_event` **之后**（既有观察者先跑；两边异常各自隔离）。"""
        prev = getattr(b, "on_event", None)

        def combined(battle, evt_name, ctx, logs):
            if prev is not None:
                try:
                    prev(battle, evt_name, ctx, logs)
                except Exception:                                # noqa: BLE001
                    pass
            self.on_event(battle, evt_name, ctx, logs)

        b.on_event = combined

    def _wrap_human_act(self, b) -> None:
        orig = b.human_act
        if getattr(orig, "_battle_tlog_wrapped", False):
            return

        def wrapped(action, skill_name, actor=None, target=None, target_side=None):
            try:
                who = actor if actor is not None else b.focus()
                self.on_act(b, action, skill_name, who, target)
            except Exception:                                    # noqa: BLE001
                pass
            return orig(action, skill_name, actor, target, target_side)

        wrapped._battle_tlog_wrapped = True
        b.human_act = wrapped

    # ============================================================ 采集点
    def on_start(self, b, *, btype="monster", seed=None, player=None,
                 enemies=None, extra: Optional[dict] = None) -> None:
        if not self.enabled:
            return
        fields = {"btype": str(btype), "seed": (int(seed) if seed is not None else None),
                  "reproducible": seed is not None,
                  "player": _player_input(player),
                  "enemies": [dict(e) for e in (enemies or [])]}
        for k, v in (extra or {}).items():
            fields.setdefault(str(k), v)
        self.tlog.emit("battle.start", actor=_uid(player), tags=self.tags, **fields)

    def on_act(self, b, action, skill_name=None, actor=None, target=None) -> None:
        if not self.enabled:
            return
        self.acts += 1
        self.tlog.emit("battle.act", actor=_uid(actor), tags=self.tags,
                       action=str(action or ""), skill=str(skill_name or ""),
                       target_uid=_uid(target), p_acts=int(getattr(b, "_p_acts", 0) or 0))
        # ⚠️ 这里**不**查收尾：`on_act` 是 action **之前**叫的（`human_act` 包装器的前半段），
        # 此刻 `b.result` 还没被引擎置上。收尾检查放在 `b.act()` 包装器的**后半段**（`_wrap_act`）。

    def on_event(self, b, evt_name, ctx, logs=None) -> None:
        """引擎观察者形态：`on_event(battle, evt_name, ctx, logs)`。只读 ctx。"""
        if not self.enabled:
            return
        kind = EVENT_KINDS.get(str(evt_name or ""))
        if not kind:
            return
        ctx = ctx if isinstance(ctx, dict) else {}
        self.events += 1
        caster, subject, body = ctx.get("caster"), ctx.get("target"), ctx.get("actor")
        info = ctx.get("info") if isinstance(ctx.get("info"), dict) else {}
        fields = {"caster": _uid(caster), "subject": _uid(subject)}
        if kind in ("battle.taken", "battle.heal", "battle.dot", "battle.down"):
            fields["caster"] = _uid(caster) or _uid(subject)
            fields["subject"] = _uid(body) or _uid(subject)
        if ctx.get("dmg") is not None:
            fields["dmg"] = _num(ctx.get("dmg"))
        if ctx.get("amount") is not None:
            fields["amount"] = _num(ctx.get("amount"))
        if ctx.get("real") is not None:
            fields["real"] = _num(ctx.get("real"))
        if ctx.get("is_crit") is not None:
            fields["crit"] = bool(ctx.get("is_crit"))
        if info.get("name"):
            fields["skill"] = str(info.get("name"))
        self.tlog.emit(kind, actor=_uid(body) or fields.get("caster") or fields.get("subject"),
                       tags=self.tags, **fields)
        self._maybe_end(b)

    def _maybe_end(self, b) -> None:
        """战斗一结束就自动收尾（**零侵入**：不用改命令层的结算点）。

        触发点是引擎事件/行动的尾部（`on_death` 是战斗结束前必发的事件），
        且只发一次；逃跑等无事件路径由行动尾部兜住。

        ⚠️ 2026-09-13 修：这里原来是「先置 `_end_sent=True` 再调 `on_end()`」——
        而 `on_end()` 开头就是幂等守卫 `if self._end_sent and not force: return`，
        于是**自动收尾这条路一条 `battle.end` 都发不出来**（生产路径上唯一的
        `on_end` 调用点就是这里，测试里都是 `force=True` 手动补发 → 一直没被发现）。
        现在「置位」这件事交给 `on_end()` 自己（它才知道到底发没发）。
        """
        if self._end_sent or not self.enabled:
            return
        if getattr(b, "result", None):
            self.on_end(b)

    def on_end(self, b, *, result: Optional[str] = None,
               extra: Optional[dict] = None, force: bool = False) -> None:
        """记 `battle.end`。**幂等**：自动收尾（`_maybe_end`）已发过则跳过，
        除非 `force=True`（显式补发/带自定义 extra 时用）。"""
        if not self.enabled:
            return
        if self._end_sent and not force:
            return
        # ⚠️ `p_acts` = **引擎口径的全量行动数**（`act()` 是统一入口，人类/AI/随从都 +1，
        # 所以它是"双方出手总数"而不是"玩家出手数"——名字有误导，值照实录）。
        # 玩家侧的出手数见 `acts_recorded`（本采集器的计数）。
        fields = {"result": str(result if result is not None else getattr(b, "result", "") or ""),
                  "rounds": _rounds_of(b), "p_acts": int(getattr(b, "_p_acts", 0) or 0),
                  "acts_recorded": self.acts, "events_recorded": self.events}
        for k, v in (extra or {}).items():
            fields.setdefault(str(k), v)
        self.tlog.emit("battle.end", tags=self.tags, **fields)
        self._end_sent = True        # 「发过了」这件事由**发出方**记（_maybe_end 只看这个标志）

    def flush(self) -> None:
        if self.enabled:
            self.tlog.flush()


def _player_input(player) -> dict:
    """玩家构造输入（回放重建用）——只留重建必需键，去掉运行期产物。"""
    if not isinstance(player, dict):
        return {}
    return {k: player.get(k) for k in REPRO_KEYS if k in player}
