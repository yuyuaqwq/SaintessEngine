# -*- coding: utf-8 -*-
"""v181.P4 battle2 引擎——Battle 主类（battle.py）。

按 docs/REFACTOR_v181P4_FULL_PLAN.md Part 2：
- 构造：sides = {side名: [actor, ...]}（唯一入口，无 player/enemy 参数）
- 行动入口：act(ctx) / human_act(...) / actor_auto(...)
- 玩家只是 sides["player"] 里 human_controlled=True 的 actor
- 胜负判定：某阵营全员阵亡 → 敌对获胜

N1：构造 + human_act/act 普攻闭环 + 胜负/死亡标记。
CTB 调度（schedule.py）N4；序列化（serialize.py）N5。
"""
from __future__ import annotations

from typing import Optional

from .actors import ActCtx, actor_alive, actor_dead
from . import actions

# 旧 battle 常量（对外兼容读）
DEFAULT_CT_WAIT = 2.0  # CTB 基础行动间隔（N4 schedule 细化）


def _now_of(battle) -> float:
    """battle 当前绝对时刻（schedule 未接入时 = 0；CD 以此刻为基准）。"""
    return float(getattr(battle, "_now", 0) or 0)


class Battle:
    def __init__(self, btype: str = "monster", sides: Optional[dict] = None,
                 title_bonus: Optional[dict] = None, dmg_mult: float = 1.0,
                 pet: Optional[dict] = None, st: Optional[dict] = None,
                 hostile_map: Optional[dict] = None,
                 target_picker=None, on_event=None, action_override=None, **kwargs):
        """构造战斗。

        sides: dict[str, list[actor]] —— 唯一入口。sides["player"] 第一个
          human_controlled actor 是命令层焦点（命令层用它展示/等输入）。
        hostile_map: 阵营敌对关系（缺省 = 除自己外的全部阵营）
        target_picker: （N5b4-5E 战斗级注入钩子）callable(battle, actor) -> Optional[actor]。
          自动 actor（actor_auto/advance 内）行动前若未指定 target，先问外部"打谁"——
          引擎零游戏知识（不认识仇恨/嘲讽/策略），只提供决策注入点；返回 None 回落
          默认目标（hostile 首个存活）。副本命令层用它注入仇恨/嘲讽选择。
        on_event: （N5b4-5E 战斗级注入钩子）callable(battle, evt_name, ctx, logs) -> None。
          事件总线 fire() 尾部通知外部观察者（命令层记账/团队技能广播/存活同步）；
          只读 ctx 或调引擎动词改状态，不返回影响结算。与 actor.triggers 声明效果正交。
        """
        self.btype = btype
        self.title_bonus = title_bonus or {}
        self.dmg_mult = dmg_mult
        self.pet = pet or {}
        self.target_picker = target_picker
        self.on_event = on_event
        self.action_override = action_override
        # 阵营容器（唯一）
        self.sides: dict = {}
        for sn, acts in (sides or {}).items():
            self.sides[sn] = list(acts or [])
        # 敌对关系（可覆盖）
        self.hostile_map = hostile_map or {}
        # 行动上下文（N2 起用）
        self._cast_ctx: Optional[dict] = None
        self._target_ctx: Optional[dict] = None
        # 结果
        self.result: Optional[str] = None      # None | victory | defeat | fled
        self.winner_side: Optional[str] = None
        self.killed_actors: list = []
        # CTB 绝对时刻（N4 schedule）
        self._now: float = 0.0
        self._p_acts: int = 0
        self._events: list = []
        # 开战事件已触发标记（N8：battle_start 整场一次；from_state 恢复 = True）
        self._started: bool = False
        # 技能索引：actor.skills key 列表 → 技能 dict（从 data 桥读取）
        self._index_skills()
        # 初始 ct（N4 前：所有 actor ct=0，命令层轮流驱动）
        for _acts in self.sides.values():
            for _a in _acts:
                if "ct" not in _a or _a.get("ct") is None:
                    _a["ct"] = 0.0

    # ============================================================
    # 构造辅助
    # ============================================================

    def _index_skills(self):
        """把 skills key 列表解析成技能 dict 挂到 actor["_skill_index"]。

        N1：从 data_bridge 读技能表（旧 engine.skill_info）。技能 key 可能是
        中文名或 sk_xxx——data_bridge 负责解析。
        """
        try:
            from .. import engine as E
            from .. import content as C
            for _acts in self.sides.values():
                for _a in _acts:
                    idx = _a.setdefault("_skill_index", {})
                    for sk in (_a.get("skills") or []):
                        if sk in idx:
                            continue
                        info = None
                        # 尝试 skill_info（中文名/内部 key 双路）
                        if _a.get("class_name"):
                            info = E.skill_info(_a["class_name"], sk)
                        if not info:
                            # sk_xxx key → 查 engine.skill_by_key
                            info = E.skill_by_key(sk)
                        if info:
                            idx[info.get("name", sk)] = info
                            idx[sk] = info
        except Exception:
            pass  # 索引失败不阻断构造（N1 普攻直接 resolve_basic_skill）

    # ============================================================
    # 查询
    # ============================================================

    def sides_of(self, side: str) -> list:
        return list(self.sides.get(side) or [])

    def hostile_of(self, side: str) -> list:
        from .actors import hostile_actors
        return hostile_actors(self, side)

    def focus(self) -> Optional[dict]:
        """命令层焦点：sides["player"] 第一个 human_controlled 存活 actor。"""
        for _a in self.sides_of("player"):
            if _a.get("human_controlled") and actor_alive(_a):
                return _a
        # 兜底：无 human_controlled 标记时取第一个存活玩家 kind
        for _a in self.sides_of("player"):
            if _a.get("kind") == "player" and actor_alive(_a):
                return _a
        return None

    def alive_actors(self) -> list:
        out = []
        for _acts in self.sides.values():
            out.extend(_a for _a in _acts if actor_alive(_a))
        return out

    def alive_sides(self) -> list:
        """有存活 actor 的阵营名列表。"""
        return [sn for sn, acts in self.sides.items()
                if any(actor_alive(_a) for _a in acts)]

    # ============================================================
    # 行动入口
    # ============================================================

    def human_act(self, action: str, skill_name: Optional[str],
                  actor: Optional[dict] = None, target=None,
                  target_side=None) -> tuple:
        """命令层唯一入口。构造 ActCtx 后调 self.act()。

        返回 (logs, ended, who)：
        - logs：出手日志 + 推进期间事件日志
        - ended：战斗是否结束
        - who：下一个该决策的 actor（多人调度；单人 = 自己/None）
        """
        caster = actor or self.focus()
        if caster is None:
            return ["没有可行动的玩家！"], False, None
        if self.result:
            return ["战斗已结束！"], True, None
        ctx = ActCtx(caster=caster, action=action, skill_name=skill_name,
                     target=target, target_side=target_side)
        logs, ended = self.act(ctx)
        # 玩家出手后：行动耗时推 ct + 推进自动 actor 到下一个决策点
        # （v181.N7.2：被沉默转普攻后 action 已变 attack → 耗时按普攻打）
        # （v181.N5b4-5a R3：action_override 自定义动作也推 ct——use_item 等同样占刻）
        _is_override = bool(getattr(ctx, "_override_consumed", False))
        if not ended and (ctx.action in ("attack", "skill", "defend") or _is_override):
            from .schedule import _after_act
            if _is_override:
                _cast = getattr(ctx, "_override_cast", None) or "attack"
                # 回调返回的 cast：str=内置动作基准（defend/skill/attack，按 spd 缩放）
                # 或数字=绝对耗时秒（命令层已算好时长，直接落 ct）
                if isinstance(_cast, str):
                    _after_act(self, caster, _cast)
                else:
                    try:
                        caster["ct"] = float(self._now) + max(0.0, float(_cast))
                    except Exception:
                        _after_act(self, caster, "attack")
            else:
                _after_act(self, caster, ctx.action)
            logs2 = []
            who = self.advance(logs2)
            logs.extend(logs2)
            if who is None:
                ended = True
            return logs, ended, who
        who = None if ended else (self.focus() if self.focus() else None)
        return logs, ended, who

    def advance(self, logs: list) -> Optional[dict]:
        """推进战斗到下一个决策点（自动 actor 行动 + DOT 结算）。

        返回下一个该决策的人控 actor；战斗结束返回 None。
        """
        from .schedule import advance as _adv
        _kind, who = _adv(self, logs)
        return who

    def auto_run(self, logs: list, max_steps: int = 500):
        """全自动跑战斗（测试/AI 模式）：所有 actor 自动行动直到结束。"""
        from .schedule import advance as _adv
        guard = 0
        while self.result is None and guard < max_steps:
            guard += 1
            _kind, who = _adv(self, logs)
            if who is None:
                break
            # 人控 actor 在 auto_run 里也自动行动（普攻）
            if actor_alive(who):
                sub, ended = self.actor_auto(who)
                logs.extend(sub)
                if ended or self.result:
                    break

    def actor_auto(self, actor: dict, ctx_target=None) -> tuple:
        """actor 自动行动（怪/随从按 auto_act 配置；N4 schedule 用）。

        读 auto_act，缺省普攻；行动后推 ct。
        N5b4-5E：未指定 target 且战斗配了 target_picker → 先问外部"打谁"
        （仇恨/嘲讽等上层策略注入；None 回落默认敌对目标）。
        """
        caster = actor
        if caster is None or actor_dead(caster):
            return [], False
        if self.result:
            return [], True
        action = "attack"
        skill_name = None
        aa = caster.get("auto_act") or {}
        if aa.get("act"):
            _a = aa["act"]
            action = _a.get("type", "attack")
            skill_name = _a.get("skill")
        if ctx_target is None and self.target_picker is not None:
            try:
                ctx_target = self.target_picker(self, caster) or None
            except Exception:
                ctx_target = None
        ctx = ActCtx(caster=caster, action=action, skill_name=skill_name,
                     target=ctx_target)
        logs, ended = self.act(ctx)
        # 行动后推 ct（自动 actor）
        if not ended:
            from .schedule import _after_act
            _after_act(self, caster, action)
        return logs, ended

    def act(self, ctx: ActCtx) -> tuple:
        """统一行动执行（人类/AI/随从都走这里）。返回 (logs, ended)。

        事件总线插桩（N8）：turn_start（回合开始，先于控制检查）→ 控制消费
        （skip 时 on_act_consume）→ act_begin（行动执行前）。
        行动前检查控制状态（v181.N7.2）：
        - mode=skip（stun/freeze/sleep）：行动被跳过 + 清除（ct 由调用方照推 = 行动浪费）
        - mode=no_skill（silence）+ action=skill：技能转普攻（不禁普攻）
        """
        if self.result:
            return [], True
        actor = ctx.caster
        if actor is None or actor_dead(actor):
            return [], False
        logs = []
        # ---- 开战事件（整场一次，首个 actor 行动前）----
        self._ensure_battle_started(logs)
        # ---- N8 事件：回合开始（先于控制检查——"回合开始回蓝"被晕也触发；
        #      主体=行动者，只处理其自身声明，旁观者不误触发）----
        from .effect_triggers import fire as _fire
        _fire(self, "turn_start", {"actor": actor}, logs)
        # ---- 控制消费（统一入口，人类/自动/随从全走这里）----
        bf = actor.get("buffs") or {}
        now = float(self._now or 0)
        for tag, entry in list(bf.items()):
            if not isinstance(entry, dict):
                continue
            mode = entry.get("mode")
            if not mode:
                continue
            # 过期控制（时间兜底）：到点自然消失
            exp = entry.get("expire")
            if exp is not None and now >= float(exp):
                bf.pop(tag, None)
                continue
            if mode == "no_skill" and ctx.action == "skill":
                logs.append(f"🤐 {actor.get('name', '目标')} 被沉默，无法使用技能！(只能普攻/防御)")
                ctx.action = "attack"
                ctx.skill_name = None
                continue
            if mode == "skip":
                logs.append(f"💫 {actor.get('name', '目标')} 被【{tag}】控制，无法行动！")
                bf.pop(tag, None)
                # N8 事件：行动级消费点（控制跳过）
                _fire(self, "on_act_consume", {"actor": actor, "tag": tag}, logs)
                # 被控跳过：登记行动点但不结算（调用方推 ct = 行动浪费）
                self._p_acts += 1
                return logs, False
        # N8 事件：行动开始（控制通过，执行行动前；主体=行动者）
        _fire(self, "act_begin", {"actor": actor, "target": ctx.target}, logs)
        # 登记行动点（展示用）
        self._p_acts += 1
        action = ctx.action
        if action == "attack":
            logs = actions.do_attack(self, ctx)
        elif action == "skill":
            logs = actions.do_skill(self, ctx)
        elif action == "defend":
            logs = self._do_defend(ctx)
        elif action == "flee":
            logs = self._do_flee(ctx)
        else:
            # N5b4-5a R3：非引擎内置动作（use_item/命令层自定义）→ 先问外部
            # action_override 注入点（引擎零游戏知识——不认识道具/吃药/特殊动作，
            # 只提供"这次行动做什么 + 耗时多少"的执行注入；效果由回调用引擎动词写）。
            # 回调返回 (logs, cast_base_or_None)；None = 未消费 → 回落默认未知提示。
            if self.action_override is not None:
                try:
                    _ov_logs, _ov_cast = self.action_override(
                        self, ctx.action, actor, ctx.skill_name, ctx.target)
                    if _ov_logs is not None:
                        logs = _ov_logs
                        ctx._override_cast = _ov_cast  # str("defend"/"skill"/"attack") 或数字秒或 None
                        ctx._override_consumed = True
                except Exception:
                    logs = [f"未知行动类型：{action}"]
            if not getattr(ctx, "_override_consumed", False):
                logs = [f"未知行动类型：{action}"]
        # N9A-2 事件：行动完成（全员广播——不带 actor 键避免主体过滤拦截旁观者；
        # 刚行动的 actor 放 ctx["acted"]，效果侧自己 if 敌我判断，如 randuin/ice_vein
        # 监听敌对 actor 行动叠减速）。被控跳过（skip）早退 return 不触发。
        try:
            from .effect_triggers import fire as _fire
            _fire(self, "act_done", {"acted": actor}, logs)
        except Exception:
            pass  # 事件源异常不阻断行动结算
        # 胜负判定（死亡可能已触发）
        self._check_side_end()
        return logs, bool(self.result)

    # ============================================================
    # 简单行动
    # ============================================================

    def _do_defend(self, ctx: ActCtx) -> list:
        actor = ctx.caster
        actor["defending"] = True
        return [f"🛡 {actor.get('name', '')} 摆出防御姿态，受到的伤害减半！"]

    def _do_flee(self, ctx: ActCtx) -> list:
        self.result = "fled"
        return [f"💨 {ctx.caster.get('name', '')} 逃跑了！"]

    # ============================================================
    # 死亡/胜负
    # ============================================================

    def _ensure_battle_started(self, logs: list):
        """开战事件（N8）：整场一次，首个 actor 行动前 fire("battle_start")。

        序列化续战（from_state）置 _started=True → 不重复触发（起手效果已
        随 actor 状态落盘）。
        """
        if self._started:
            return
        self._started = True
        try:
            from .effect_triggers import fire as _fire
            _fire(self, "battle_start", {}, logs)
        except Exception:
            pass  # 事件源异常不阻断开战

    def _on_actor_dead(self, actor: dict, logs: Optional[list] = None):
        """actor 死亡：记录（击杀奖励/任务进度由命令层处理）。

        N8：死亡事件 fire("on_death")——所有死亡路径统一在此触发
        （主动伤害/DOT/环境），ctx.actor = 死者。
        """
        if actor not in self.killed_actors:
            self.killed_actors.append(actor)
        # 死亡 actor 清 defending/charging 状态
        actor["defending"] = False
        actor["charging"] = None
        if logs is not None:
            try:
                from .effect_triggers import fire as _fire
                _fire(self, "on_death", {"actor": actor, "target": actor}, logs)
            except Exception:
                pass

    def _check_side_end(self) -> bool:
        """胜负判定：存活阵营数 ≤1 → 置 result。

        返回是否已结束。命令层外部（掉落/经验）看 self.result。
        """
        if self.result:
            return True
        alive = [sn for sn, acts in self.sides.items()
                 if any(actor_alive(_a) for _a in acts)]
        if len(alive) <= 1:
            if not alive:
                # 全灭（罕见）→ 无胜者
                self.result = "defeat"
                return True
            # 恰好剩一个阵营 → 该阵营胜
            self.winner_side = alive[0]
            if alive[0] == "player":
                self.result = "victory"
            else:
                self.result = "defeat"
            return True
        return False

    # ============================================================
    # 序列化（N5：sides-only）
    # ============================================================

    def to_state(self) -> dict:
        """Battle → JSON 化 dict（battle_state.state 存）。"""
        from .serialize import to_state as _ts
        return _ts(self)

    @classmethod
    def from_state(cls, st: dict) -> "Battle":
        """dict → Battle（断线恢复/续战用）。"""
        from .serialize import from_state as _fs
        return _fs(st)
