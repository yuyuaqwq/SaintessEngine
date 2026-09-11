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
from . import config as _cfg

# 旧 battle 常量（对外兼容读）
DEFAULT_CT_WAIT = 2.0  # CTB 基础行动间隔（N4 schedule 细化）


def _now_of(battle) -> float:
    """battle 当前绝对时刻（schedule 未接入时 = 0；CD 以此刻为基准）。"""
    return float(getattr(battle, "_now", 0) or 0)


# S2 公开 API 面（§5）：私有 → 公开；旧下划线名保留为别名（不得删）。
now_of = _now_of


class Battle:
    def __init__(self, btype: str = "monster", sides: Optional[dict] = None,
                 title_bonus: Optional[dict] = None, dmg_mult: float = 1.0,
                 pet: Optional[dict] = None, st: Optional[dict] = None,
                 hostile_map: Optional[dict] = None,
                 target_picker=None, on_event=None, action_override=None,
                 script_hook=None, seed_ct: bool = True, **kwargs):
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
        script_hook: （N5B5c P1 剧本导演钩子）callable(battle, actor, logs) -> bool。
          自动 actor（actor_auto）行动前调用——命令层 Boss 剧本导演在此检查血量阈值/
          刻计数 → 触发剧本动作（转阶段演出/换招/召唤等）。返回 True = 拦截本刻行动
          （阶段演出刻，照推 ct 行动浪费）。引擎零游戏知识，只提供前置决策注入点。
        """
        self.btype = btype
        self.title_bonus = title_bonus or {}
        self.dmg_mult = dmg_mult
        self.pet = pet or {}
        self.target_picker = target_picker
        self.on_event = on_event
        self.action_override = action_override
        self.script_hook = script_hook
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
        # 初始 ct 播种（N10-B6b 对齐旧引擎 _ct_initial_wait：开局第一动也按速度排，
        # 快者先手；旧 battle.py:733/770/1090 同款。此前全 0 = 玩家/命令层首轮抢跑、
        # 快怪在首轮被跳过——真人对拍暴露的节奏 bug）
        # seed_ct=False（from_state 恢复路径）：actor ct 已随存档反序列化，不重播。
        if seed_ct:
            for _acts in self.sides.values():
                for _a in _acts:
                    self._seed_ct_one(_a)

    # ============================================================
    # 构造辅助
    # ============================================================

    def _seed_ct_one(self, actor: dict) -> None:
        """单 actor 初始 ct 播种（构造期与运行期 add_actor 共用）。

        已有正 ct 不重播；裸 spd 可能 0（真实玩家 actor 面板聚合）——
        用聚合面板速度口径（stats.actor_spd）。ct 为空会让 CTB 排序异常。
        """
        if actor.get("ct") is not None and float(actor.get("ct") or 0) > 0:
            return
        from .schedule import initial_ct as _ict
        _spd = actor.get("spd", 0) or 0
        try:
            from . import stats as S
            _spd = S.actor_spd(self, actor)
        except Exception:
            pass
        actor["ct"] = _ict(_spd)

    def _index_one_actor(self, actor: dict) -> None:
        """单 actor 技能索引（构造期与运行期 add_actor 共用）。

        S1 断链（docs/ENGINE_CONTENT_SPLIT_PLAN.md §3.2 R9/R10）：原先 import
        game.engine / game.content 直读技能表——现走 config 注入面
        （skill_lookup / monster_skill_fn，内容侧装配）。技能 key 可能是
        中文名或 sk_xxx——内容侧查询函数负责解析。索引失败不阻断（N1 政策：
        普攻走 resolve_basic_skill 兜底），故 try 包在本函数内、两个调用方同语义。
        """
        try:
            idx = actor.setdefault("_skill_index", {})
            for sk in (actor.get("skills") or []):
                if sk in idx:
                    continue
                info = None
                # 尝试 skill_info（中文名/内部 key 双路）
                if actor.get("class_name"):
                    info = _cfg.skill_info_of(actor["class_name"], sk)
                if not info:
                    # sk_xxx key → 查 skill_by_key
                    info = _cfg.skill_by_key(sk)
                if not info:
                    # N5B 怪技能源（ms_* 表——旧引擎 7666 同款：先怪表后玩家表；
                    # battle2 此前只查玩家源 → 怪技能索引空 → 技能静默空放）
                    try:
                        info = _cfg.monster_skill_of(sk)
                    except Exception:
                        info = None
                if info:
                    idx[info.get("name", sk)] = info
                    idx[sk] = info
        except Exception:
            pass  # 索引失败不阻断（N1 普攻直接 resolve_basic_skill）

    def refresh_skill_index(self, actor: dict) -> None:
        """保证 actor 的技能索引覆盖当前 actor["skills"]（幂等，快路径零开销）。

        2026-09-11 ★运行期换招索引失效修复：`_skill_index` 原先只在 Battle 构造期
        与 add_actor 建一次，而运行期会往 actor["skills"] 追加技能（Boss 剧本转阶段
        add_skills、变身/获得技能）。追加后索引不含新键 → ActCtx.__post_init__ 取
        info={} → do_skill 直接 return []：**转阶段后 Boss 的 auto_act 主技能静默空放**
        （tools/probe_phase_skill_index.py 实跑：4/4 阶段新招均不在索引、ActCtx.info={}）。

        索引一致性归引擎（内容侧换招不必记得调索引）：本方法在每次行动决策前调用，
        skills 全在索引 → 只做 len(skills) 次 dict 成员判断即返回。
        """
        idx = actor.get("_skill_index")
        if not isinstance(idx, dict):
            idx = actor["_skill_index"] = {}
        try:
            for sk in (actor.get("skills") or []):
                if sk not in idx:
                    self._index_one_actor(actor)
                    return
        except Exception:
            pass  # 索引失败不阻断（_index_one_actor 内部同语义容错）

    def _index_skills(self):
        """构造期技能索引：遍历 sides 逐 actor 建（单个 actor 走 _index_one_actor）。"""
        for _acts in self.sides.values():
            for _a in _acts:
                self._index_one_actor(_a)

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
    # 运行期 actor 注册（召唤 / 援军 / 变身）
    # ============================================================

    def add_actor(self, actor: dict, side: str, front: bool = False) -> dict:
        """向战斗注册一个新 actor（召唤 / 援军 / 变身）。

        - 入 self.sides[side]；front=True 插队首（前排挡刀——存活序列第一名即
          新单位，AI 默认目标先打它；对齐 boss_script M-W2s 口径），默认 append 尾部。
        - 建 actor["_skill_index"]（复用 _index_one_actor——不建则 auto_act 技能
          查不到技能 dict 而静默空放）。
        - 播种 ct（复用 _seed_ct_one——不播种则 CTB 排序异常）。
        - 返回 actor（调用方拿引用做日志 / 上限记账 / uid 登记）。

        引擎零游戏知识：不认识"随从 / 召唤 / 亡灵 / 援军"，只做注册 + 索引 + 排程。
        sides 是普通 dict，调度（schedule.py）与序列化（serialize.py）均动态遍历
        sides，故新 actor 自动参与行动与存档，无需额外同步。
        """
        acts = self.sides.setdefault(side, [])
        if front:
            acts.insert(0, actor)
        else:
            acts.append(actor)
        self._index_one_actor(actor)
        self._seed_ct_one(actor)
        return actor

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
        # 决策前刷新技能索引（运行期换招/获得技能后索引可能落后于 actor.skills；
        # 必须在 ActCtx 构造前——ActCtx.__post_init__ 是技能 dict 的唯一解析时机）
        self.refresh_skill_index(caster)
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
        # 5c P1：剧本导演钩子（自动 actor 行动帧前置——Boss 剧本导演检查血量阈值/
        # 刻计数 → 转阶段演出/换招；返回 True = 演出刻拦截本刻行动，照推 ct）
        _hook_logs = []
        if self.script_hook is not None:
            try:
                if self.script_hook(self, caster, _hook_logs):
                    from .schedule import _after_act
                    _after_act(self, caster, "attack")
                    return _hook_logs, False
            except Exception:
                pass  # 导演异常不阻断怪行动（回落默认行动）
        # 决策前刷新技能索引（导演帧刚可能 add_skills 换招 → 索引落后于 actor.skills；
        # 必须在下面读 auto_act / resolve_ai_move 之前——ActCtx.__post_init__ 只解析一次）
        self.refresh_skill_index(caster)
        action = "attack"
        skill_name = None
        aa = caster.get("auto_act") or {}
        if aa.get("act"):
            _a = aa["act"]
            action = _a.get("type", "attack")
            skill_name = _a.get("skill")
        else:
            # N5B 怪 AI 决策器（无 auto_act 显式招时——导演换招/装配指定优先，
            # AI 只兜底自选；再回落普攻）。resolve 返回 None = 普攻。
            try:
                from .ai import resolve_ai_move
                _mv = resolve_ai_move(self, caster)
                if _mv and isinstance(_mv, dict):
                    action = str(_mv.get("type") or "attack")
                    skill_name = _mv.get("skill")
                    # N5B target_hint：AI 战术目标提示（如残血收割 lowest_hp）——
                    # 挂瞬态字段，target_picker（命令层）消费后即弃；
                    # 无 picker/未知 hint → 回落默认仇恨目标，尾部清理防残留
                    if _mv.get("target_hint"):
                        caster["_target_hint"] = _mv["target_hint"]
            except Exception:
                pass
        # 2026-09-11 ★可执行性兜底：显式 auto_act 指定了此刻放不出的技能（冷却中/
        # 资源不足/索引不到）→ 回落普攻，避免白耗一回合（与 ai 决策器过滤同一判据；
        # 人控路径不适用——玩家显式选择仍由 do_skill 回拦截文案展示，行为不变）。
        if action == "skill":
            try:
                from .ai import _skill_castable
                if not _skill_castable(self, caster, str(skill_name or "")):
                    action = "attack"
                    skill_name = None
            except Exception:
                pass
        if ctx_target is None and self.target_picker is not None:
            try:
                ctx_target = self.target_picker(self, caster) or None
            except Exception:
                ctx_target = None
        # hint 一次性消费（picker 未识别也清，防残留到下一帧）
        caster.pop("_target_hint", None)
        ctx = ActCtx(caster=caster, action=action, skill_name=skill_name,
                     target=ctx_target)
        logs, ended = self.act(ctx)
        if _hook_logs:
            logs = _hook_logs + logs
        # 个体行动计数（AI round_mod 谓词；随 actor 序列化持久化）
        caster["act_count"] = int(caster.get("act_count", 0) or 0) + 1
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
        # V 系列：控制条目在 effects 容器（effects[tag] = {expire, mode}）
        ef = actor.get("effects") or {}
        now = float(self._now or 0)
        for tag, entry in list(ef.items()):
            if not isinstance(entry, dict):
                continue
            mode = entry.get("mode")
            if not mode:
                continue
            # 过期控制（时间兜底）：到点自然消失
            exp = entry.get("expire")
            if exp is not None and now >= float(exp):
                ef.pop(tag, None)
                continue
            if mode == "no_skill" and ctx.action == "skill":
                logs.append(f"🤐 {actor.get('name', '目标')} 被沉默，无法使用技能！(只能普攻/防御)")
                ctx.action = "attack"
                ctx.skill_name = None
                continue
            if mode == "skip":
                logs.append(f"💫 {actor.get('name', '目标')} 被【{tag}】控制，无法行动！")
                ef.pop(tag, None)
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
