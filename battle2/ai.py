# -*- coding: utf-8 -*-
"""battle2 通用怪 AI 决策器（条件优先级表 / 极简 utility）。

设计 docs/REFACTOR_v181P4_N5B_monster_ai_design.md：
- actor.ai 纯数据（select/fallback/moves[{when, then, weight}]），引擎零名词——
  谓词只做数字比较 + 冷却表查 key，then 动作只出引擎 ActCtx 词汇。
- 选择器：priority（条件表第一个命中）/ weighted（命中 moves 按权重随机 +
  skill_chance 概率回落 fallback）。
- 决策顺序（actor_auto）：导演演出刻 → actor.auto_act 显式 → 本决策器 → 普攻。
- 可执行性过滤（2026-09-11）：命中的 move 若技能此刻放不出（冷却/资源/索引不到）
  跳过 → 全部不可用则回落普攻；决策器语义 = 「选一个现在真能执行的动作」。
- 旧格式翻译：MONSTER_MODS ai {skill_chance, weights} → 新格式（幂等，写回
  actor["ai"]），bridge 原样透传后在此归一。

守卫谓词集 v1（扩展位：加谓词 = 所有怪多一个能力维度，需全局评估）：
  self_hp_lt / self_hp_gt     自身血量比例
  hostile_lowest_hp_lt        敌对侧存活最低血量比例（残血追击）
  round_mod [N, R]            actor.act_count % N == R（个体行动节奏）
  cd_ok                       技能不在冷却（actor.cooldown 表，key=技能 name）
  缺省 when={}                恒真
"""
from __future__ import annotations


# ============================================================
# 旧格式归一（幂等）：{skill_chance, weights} → 新格式
# ============================================================

def normalize_ai(actor: dict) -> dict:
    """actor.ai 旧格式（MONSTER_MODS ai 透传）→ 新格式，写回 actor["ai"]。

    新格式（select/fallback/moves）不动；旧格式（weights/skill_chance）转换：
      weights {技能id: 权重} → weighted moves（when={} 恒真）
      skill_chance 保留为 ai["skill_chance"]（weighted 概率回落用）
    无 ai → 返回 None（actor_auto 回落普攻）。
    """
    ai = actor.get("ai")
    if not isinstance(ai, dict):
        return None
    if ai.get("moves") is not None or ai.get("select"):
        return ai  # 已是新格式
    weights = ai.get("weights")
    chance = ai.get("skill_chance")
    moves = []
    if isinstance(weights, dict):
        for sk, w in weights.items():
            if not sk:
                continue
            try:
                wv = float(w)
            except Exception:
                wv = 1.0
            moves.append({"when": {}, "then": {"type": "skill", "skill": sk},
                          "weight": max(0.0, wv)})
    if not moves:
        # 只有 skill_chance 无 weights：单技能 fallback？无可选 → 丢给普攻
        return None
    new_ai = {"select": "weighted", "fallback": {"type": "attack"}, "moves": moves}
    if chance is not None:
        try:
            new_ai["skill_chance"] = float(chance)
        except Exception:
            pass
    actor["ai"] = new_ai
    return new_ai


# ============================================================
# 谓词评估
# ============================================================

def _ratio(actor: dict) -> float:
    mh = int(actor.get("max_hp", 0) or 0)
    if mh <= 0:
        return 1.0
    return int(actor.get("hp", 0) or 0) / mh


def _hostile_lowest(battle, actor: dict):
    """敌对侧存活 actor 最低血量比例（无存活 → None）。"""
    side = actor.get("side") or ""
    low = None
    for _a in battle.sides.values():
        for x in _a:
            if x is actor:
                continue
            if x.get("side") == side:
                continue
            if int(x.get("hp", 0) or 0) <= 0:
                continue
            r = _ratio(x)
            if low is None or r < low:
                low = r
    return low


def _cd_remaining(battle, actor: dict, skill: str) -> float:
    """技能剩余冷却（秒）：actor.cooldown 表 key=技能 name；skill 给 id 时经
    battle._skill_index 解析 name（引擎零名词——技能名只是字符串 key）。"""
    now = float(getattr(battle, "_now", 0) or 0)
    cd = actor.get("cooldown") or {}
    if not isinstance(cd, dict):
        return 0.0
    # 直接命中（name 或 id 同键）
    if skill in cd:
        return max(0.0, float(cd[skill]) - now)
    # id → name 解析（actor._skill_index 构造时挂，key=技能 id/name 双索引）
    idx = actor.get("_skill_index")
    if idx and isinstance(idx, dict):
        info = idx.get(skill)
        if info and isinstance(info, dict):
            nm = info.get("name")
            if nm and nm in cd:
                return max(0.0, float(cd[nm]) - now)
    return 0.0


def _skill_castable(battle, actor: dict, skill_ref: str) -> bool:
    """某技能引用此刻是否可执行（与 do_skill 前置校验同源，不产生文案）。

    三段判据（任一不满足 → 不可执行）：
    1. **索引得到** —— _skill_index 无该键 → 不可执行。do_skill 拿 info={} 会
       `if not info: return []`（静默空放、白耗一回合）；N10 后引擎唯一技能解析源
       就是 _skill_index（ActCtx.__post_init__ 同源）。
    2. **不在冷却** —— 与 actions._cd_left_of 同一判据。
    3. **资源足额** —— 与 actions._skill_usable 同一函数（logs=None 静默）。
    """
    idx = actor.get("_skill_index")
    info = idx.get(skill_ref) if isinstance(idx, dict) else None
    if not isinstance(info, dict) or not info:
        return False
    try:
        from .actions import _skill_usable
        return bool(_skill_usable(battle, actor, info, None))
    except Exception:
        return False


def _move_castable(battle, actor: dict, move: dict) -> bool:
    """move 的 then 动作此刻是否可执行（非技能动作恒可执行）。"""
    then = (move or {}).get("then")
    if not isinstance(then, dict):
        return False
    if str(then.get("type") or "attack") != "skill":
        return True          # 普攻/防御/道具… → act() 各自兜底，不在此过滤
    sk = then.get("skill")
    if not sk:
        return False         # action=skill 无技能名 → do_skill 空转
    return _skill_castable(battle, actor, str(sk))


def eval_when(battle, actor: dict, when: dict) -> bool:
    """守卫评估：when 全部键满足（AND）；空 dict = 恒真。"""
    try:
        for k, v in (when or {}).items():
            if k == "self_hp_lt":
                if not (_ratio(actor) < float(v)):
                    return False
            elif k == "self_hp_gt":
                if not (_ratio(actor) > float(v)):
                    return False
            elif k == "hostile_lowest_hp_lt":
                low = _hostile_lowest(battle, actor)
                if low is None or not (low < float(v)):
                    return False
            elif k == "round_mod":
                try:
                    n, r = int(v[0]), int(v[1])
                except Exception:
                    return False
                if not (int(actor.get("act_count", 0) or 0) % n == r):
                    return False
            elif k == "cd_ok":
                if _cd_remaining(battle, actor, str(v)) > 0.0:
                    return False
            else:
                return False  # 未知谓词 → 不命中（宁缺毋滥，防拼写漂移）
        return True
    except Exception:
        return False


# ============================================================
# 选择器
# ============================================================

def resolve_ai_move(battle, actor: dict):
    """按 actor.ai 选动作。返回 then 动作 dict（engine ActCtx 词汇）或 None（回落）。

    priority：moves 从上到下第一个 when 全满足。
    weighted：when 命中的 moves 按 weight 随机；ai.skill_chance<1 时先 roll
    （rand > chance → None 回落 fallback——旧 skill_chance 语义）。

    2026-09-11 ★可执行性过滤（修「AI 活锁」）：when 命中但技能此刻放不出的 move
    直接跳过（冷却中 / 资源不足 / 技能索引不到，判据见 _move_castable）——
    否则 do_skill 前置校验返回空动作 → 白耗一回合，且冷却不被写入 → cd_ok 恒真 →
    每回合重试同一个永远放不出的技能（0 输出直到被打死；第三方接入实测出过 defeat）。
    过滤后无 move 可用 → None → 调用方回落普攻（与「when 不命中」同一出口）。
    """
    ai = normalize_ai(actor)
    if not ai:
        return None
    moves = ai.get("moves") or []
    if not moves:
        return None
    select = str(ai.get("select") or "priority")
    if select == "weighted":
        import random as _rnd
        chance = float(ai.get("skill_chance", 1.0) if ai.get("skill_chance") is not None else 1.0)
        if chance < 1.0 and _rnd.random() > chance:
            return None
        pool = [(m.get("weight", 1.0), m) for m in moves
                if isinstance(m, dict) and eval_when(battle, actor, m.get("when") or {})
                and _move_castable(battle, actor, m)]
        if not pool:
            return None
        try:
            weights = [max(0.0, float(w)) for w, _ in pool]
        except Exception:
            weights = None
        if weights is not None and sum(weights) > 0:
            chosen = _rnd.choices([m for _, m in pool], weights=weights, k=1)[0]
        else:
            chosen = pool[0][1]
        return chosen.get("then")
    # priority
    for m in moves:
        if not isinstance(m, dict):
            continue
        if eval_when(battle, actor, m.get("when") or {}) and _move_castable(battle, actor, m):
            return m.get("then")
    return None
