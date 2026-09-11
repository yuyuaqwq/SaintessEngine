# -*- coding: utf-8 -*-
"""v2 多对多站位战斗引擎 —— 阵型纯函数工具（game/core/formation.py）

§3.1：不依赖 Battle 实例的纯函数，便于单测。单位用 dict 表示，站位字段：
  - rank : 当前站位层（1 前 → 3 后），压缩后可能变化
  - reach: 攻击范围（1=近战只打第 1 层 / 2=远程第 1-2 层 / 3=全域）

MAX_RANKS：层数上限（§2.1）。
"""
import random

MAX_RANKS = 3


def alive_units(units: list) -> list:
    """存活单位（hp>0）。返回新列表，不改输入。"""
    return [u for u in (units or []) if u.get("hp", 0) > 0]


def front_rank(units) -> int:
    """存活单位最小 rank；无存活返回 MAX_RANKS+1。"""
    alive = [u.get("rank", 1) for u in alive_units(units)]
    if not alive:
        return MAX_RANKS + 1
    return min(alive)


def reachable_units(attacker, units) -> list:
    """射程内存活单位（u.rank <= attacker.reach）。返回新列表。"""
    reach = int(attacker.get("reach", 1) or 1)
    return [u for u in units if u.get("hp", 0) > 0 and int(u.get("rank", 1) or 1) <= reach]


def select_target(attacker, units, threat=None, exclude_uid=None, threat_mode="front"):
    """选择攻击目标。

    规则（§4.1）：射程内 → 最前排(最小 rank) → 同层随机（有 threat 表时同层按
    threat 最高，平局随机）。射程内无目标 → 兜底取最前排存活单位。exclude_uid
    排除指定单位（如已死的源单位）。

    threat_mode（v173.5 全层仇恨，鱼鱼拍板 2026-09-04）：
      "front"（默认）：先射程/前排过滤，同层才比仇恨——旧行为，野外/普通怪
      "all"：全层直接按仇恨最高选（跨层 OT 模型）——副本 Boss 用，
        后排输出/治疗高仇恨会被点名；坦克靠嘲讽/防御挑衅/仇恨技能维持。

    返回 Unit|None。threat: {uid: 仇恨值}。
    """
    reach = int(attacker.get("reach", 1) or 1)
    alive = alive_units(units)
    if not alive:
        return None
    if exclude_uid:
        alive = [u for u in alive if u.get("uid") != exclude_uid]
    if not alive:
        return None
    # 全层仇恨模式：忽略站位，直接全场按仇恨最高选（OT 模型）
    if threat_mode == "all" and threat:
        max_th = max(float(threat.get(u.get("uid"), 0) or 0) for u in alive)
        contenders = [u for u in alive if float(threat.get(u.get("uid"), 0) or 0) >= max_th]
        if len(contenders) == 1:
            return contenders[0]
        return random.choice(contenders)
    # 射程内目标
    in_range = [u for u in alive if int(u.get("rank", 1) or 1) <= reach]
    pool = in_range if in_range else alive  # 兜底：最前排
    if not pool:
        return None
    # 最前排（最小 rank）
    min_rank = min(int(u.get("rank", 1) or 1) for u in pool)
    front = [u for u in pool if int(u.get("rank", 1) or 1) == min_rank]
    if not threat:
        if len(front) == 1:
            return front[0]
        return random.choice(front)
    # 同层按仇恨最高，平局随机
    max_th = max(float(threat.get(u.get("uid"), 0) or 0) for u in front)
    contenders = [u for u in front if float(threat.get(u.get("uid"), 0) or 0) >= max_th]
    if len(contenders) == 1:
        return contenders[0]
    return random.choice(contenders)


def select_aoe_targets(attacker, units, scope) -> list:
    """AOE 目标选择。

    scope ∈ "front"（当前最前排全部）/ "all"（全部存活）/ "rankN"（第 N 层全部，
    N 越界取最前排）。AOE 同样先按射程过滤（技能自带 reach 覆盖职业 reach 时按
    技能——attacker 的 reach 已被调用方设置为覆盖后的值）。

    返回目标列表（存活）。
    """
    reach = int(attacker.get("reach", 1) or 1)
    alive = alive_units(units)
    if not alive:
        return []
    in_range = [u for u in alive if int(u.get("rank", 1) or 1) <= reach]
    if not in_range:
        # 射程内无目标（兜底：最前排）
        mr = min(int(u.get("rank", 1) or 1) for u in alive)
        in_range = [u for u in alive if int(u.get("rank", 1) or 1) == mr]
    if scope in ("front", "rank"):
        mr = min(int(u.get("rank", 1) or 1) for u in in_range)
        return [u for u in in_range if int(u.get("rank", 1) or 1) == mr]
    if scope == "all":
        return list(in_range)
    if scope.startswith("rank"):
        try:
            n = int(scope[4:])
        except (ValueError, TypeError):
            n = 1
        layer = [u for u in in_range if int(u.get("rank", 1) or 1) == n]
        if layer:
            return layer
        # N 越界 → 取最前排
        mr = min(int(u.get("rank", 1) or 1) for u in in_range)
        return [u for u in in_range if int(u.get("rank", 1) or 1) == mr]
    # 未知 scope：默认最前排
    mr = min(int(u.get("rank", 1) or 1) for u in in_range)
    return [u for u in in_range if int(u.get("rank", 1) or 1) == mr]


def pick_by_policy(policy: str | None, units, threat=None, fallback=None):
    """v173.6 目标策略共享解析（玩家/怪物同一套语义，数据驱动）。
    从存活 units 按 policy 选 1 个目标；policy 缺省/未知 → fallback 结果。

    policy ∈:
      "hate_top"  → 全层仇恨最高（点名 OT 者，无视站位/射程）
      "random"    → 随机存活（无视仇恨/站位）
      "weakest"   → 血量百分比最低（压血线/处决）
      "backline"  → rank 最大（后排）存活；同 rank 随机
      "front"     → 最前排（默认，等同 select_target front 语义）
    返回 Unit | None。threat: {uid: 仇恨值}（hate_top 用）。
    """
    alive = alive_units(units)
    if not alive:
        return None
    policy = (policy or "").lower()
    if policy == "hate_top":
        if threat:
            _mx = max(float(threat.get(u.get("uid"), 0) or 0) for u in alive)
            _c = [u for u in alive if float(threat.get(u.get("uid"), 0) or 0) >= _mx]
            return random.choice(_c)
        # 无仇恨表 → 随机
        return random.choice(alive)
    if policy == "random":
        return random.choice(alive)
    if policy == "weakest":
        return min(alive, key=lambda u: (u.get("hp", 0) or 0) / max(1, u.get("max_hp", 1) or 1))
    if policy == "backline":
        _mxr = max(int(u.get("rank", 1) or 1) for u in alive)
        _c = [u for u in alive if int(u.get("rank", 1) or 1) == _mxr]
        return random.choice(_c)
    if policy == "front":
        _mnr = min(int(u.get("rank", 1) or 1) for u in alive)
        _c = [u for u in alive if int(u.get("rank", 1) or 1) == _mnr]
        return random.choice(_c)
    # 缺省/未知 → fallback（调用方传入的默认选择函数结果）
    return fallback


def compact(units) -> list:
    """原地阵型压缩（§2.1）：存活单位按当前 rank 升序重排、rank 重编号为 1..K
    （同层内保持原有顺序）；死亡单位移除。

    返回被移除（死亡）的单位列表，供结算层发"倒下"文案。直接修改传入列表。
    """
    removed = []
    kept = []
    for u in (units or []):
        if u.get("hp", 0) > 0:
            kept.append(u)
        else:
            removed.append(u)
    # 原 rank 升序稳定排序（同层保持原顺序）
    kept.sort(key=lambda u: int(u.get("rank", 1) or 1))
    ranks = {}
    for u in kept:
        r = int(u.get("rank", 1) or 1)
        ranks.setdefault(r, []).append(u)
    new_rank = 1
    ordered = []
    for r in sorted(ranks):
        for u in ranks[r]:
            u["rank"] = new_rank
            ordered.append(u)
        new_rank += 1
    units[:] = ordered
    return removed


def numbered_units(units) -> list:
    """存活单位按站位顺序编号（rank 升序 + 层内原序），返回 [(序号, unit), ...]。

    v127.3 战斗选敌：显示与解析共用同一编号（a1/a2… 敌方，b1/b2… 我方）。
    """
    alive = alive_units(units)
    alive.sort(key=lambda u: (int(u.get("rank", 1) or 1), _orig_idx(units, u)))
    return [(i + 1, u) for i, u in enumerate(alive)]


def _orig_idx(units, u) -> int:
    """单位在原列表中的位置（稳定编号用；找不到返回大值排最后）。"""
    for i, x in enumerate(units):
        if x is u:
            return i
    return 10 ** 6


def formation_view(units, side: str = "enemy") -> list:
    """生成站位图文案行（每层一行）。仅含存活单位；蓄力单位带"⏳蓄力中(剩N)"。

    v127.3：side 决定阵营代号——enemy: 层=A{n}层、目标=a{序号}；ally: 层=B{n}层、目标=b{序号}。
    示例：`A1层: a1 🐺野狼 ❤️100 | a2 🐻黑熊 ❤️150`
    """
    rows = []
    alive = alive_units(units)
    rows_map = {}
    for u in alive:
        r = int(u.get("rank", 1) or 1)
        rows_map.setdefault(r, []).append(u)
    numed = {id(u): n for n, u in numbered_units(units)}
    side_mark = "A" if side == "enemy" else "B"
    for r in sorted(rows_map):
        parts = []
        for u in rows_map[r]:
            icon = u.get("icon", "") or ""
            nm = u.get("name", "单位")
            hp = u.get("hp", 0)
            mx = u.get("max_hp", 0)
            tag = f"{side_mark.lower()}{numed.get(id(u), '?')}"
            # v164.1：血量带最大值（❤️当前/最大）——站位图即完整血量，消除下方重复汇总
            hp_txt = f"❤️{hp}" + (f"/{mx}" if mx else "")
            seg = f"{tag} {icon} {nm} {hp_txt}".strip()
            ch = u.get("charging")
            if ch:
                left = ch.get("left", 1)
                seg += f" ⏳蓄力中(剩{left})"
            parts.append(seg)
        rows.append(f"{side_mark}{r}层: " + " | ".join(parts))
    return rows
