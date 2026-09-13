# -*- coding: utf-8 -*-
"""《奥兰迪亚》战斗内动词 —— P4/D2 切片：「团队/面幅」机制族 20 个动作（**搬运物**，逐字保真）。

真源 = 游戏仓 `C:/Users/yuyu/qqbot/data/plugins/dragonfall/game/services/battle_team_procs.py`
（788 行，动作区 :172-788）。本文件正文 = 真源 :44-788 **逐字节**搬运（含分节注释与空行）；
真源 :2-41 的模块散文不搬（换成下面这段头注）。

搬运物（20 个 `@register_action` 动词，动作区 :172-788）
--------------------------------------------------------------------------
通用面幅 1 个：`team_apply`
护盾 2 个：`team_shield` / `self_shield`（助手 `_stat_of:202` / `_shield_value:217`）
减伤 2 个：`team_taken_reduce` / `team_ss_reduce_apply`（助手 `_alt_reduce:302` / `_reduce_of:319`）
易伤 2 个：`timed_vuln` / `timed_vuln_apply`
伤害乘区 3 个：`team_dmg_aura` / `team_dmg_aura_apply` / `target_lock_mark`
免疫控制 2 个：`team_cc_immune` / `self_cc_immune`
挡刀 3 个：`team_guard` / `guard_expire` / `guard_reflect`
格挡 3 个：`block_once` / `block_once_apply` / `block_reflect_hit`
奥术力场 2 个：`arcane_field` / `arcane_edge_apply`
模块级助手（原文件即模块级，逐字搬）：`_now:54` / `_alive:62` / `_info:71` / `_side_of:77` /
`team_of:93` / `_turns:104` / `_num:118` / `_res_stacks:133` / `_mount:146` / `_norm_pct:157` +
常量 `PREFIX:47`。

结构改写清单（每处一行；除下列外，数值 / `logs.append` 文案 / 注释 / 空行零改动）
--------------------------------------------------------------------------
1. 模块头：真源 :2-41 的模块散文不搬 → 换成上面这段头注（含真源行号与本清单）。
2. 无「闭包 → 模块级」提取：核实真源**没有** `install()` / `_registered`（grep 零命中），
   20 个动作与全部助手**本就在模块顶层** —— 故无需提层，纯搬运。
3. 装饰器注册：真源已在模块顶层用 `@register_action("…")` 注册 → 逐字保留
   （引擎 `saintess_engine.battle.effects.register_action` 是 import 即注册，无装配器）。
4. import 路径：真源 :44 的 `from saintess_engine.battle.effects import apply_effects, register_action`
   本身已是绝对导入 → 原样保留；函数体内的惰性 import（`act_shield` / `deal_damage` /
   `state_def` / `stats`）逐字未动。
5. 其它：零改写。

⚠️ 过渡期铁律（设计稿 §五-3）：**包版是搬运物**，游戏仓 `battle_team_procs.py` 的同名实现继续
存在；两者语义必须逐字一致（否则同一 actor 走不同装配路径会得到不同数值）。
"""
from saintess_engine.battle.effects import apply_effects, register_action

# 团队态统一前缀（effects 容器命名空间；避免与引擎/其它模块 key 撞名）
PREFIX = "team:"


# ============================================================
# 工具
# ============================================================

def _now(battle) -> float:
    try:
        from saintess_engine.battle import now_of
        return float(now_of(battle) or 0.0)
    except Exception:
        return float(getattr(battle, "_now", 0) or 0)


def _alive(a) -> bool:
    if not isinstance(a, dict):
        return False
    try:
        return int(a.get("hp", 0) or 0) > 0
    except Exception:
        return False


def _info(params) -> dict:
    """技能数据（`_do_buff` 经 params["info"] 注入）——本模块数值唯一来源。"""
    i = params.get("info") if isinstance(params, dict) else None
    return i if isinstance(i, dict) else {}


def _side_of(battle, actor) -> str:
    """取 actor 所在阵营名（先读字段，缺失时反查 sides）。"""
    if not isinstance(actor, dict):
        return ""
    s = actor.get("side") or ""
    if s:
        return s
    try:
        for name, acts in (battle.sides or {}).items():
            if any(a is actor for a in acts):
                return name
    except Exception:
        pass
    return ""


def team_of(battle, actor) -> list:
    """施法者同侧全部存活 actor（含施法者自己）。"""
    side = _side_of(battle, actor)
    if not side:
        return []
    try:
        return [a for a in battle.sides_of(side) if _alive(a)]
    except Exception:
        return []


def _turns(params, info=None) -> int:
    """生效刻数：params.turns（`_do_buff` 由 buff_turns 折算注入）优先。"""
    for src in (params, info or {}):
        if not isinstance(src, dict):
            continue
        try:
            t = int(src.get("turns", 0) or 0)
        except Exception:
            t = 0
        if t > 0:
            return t
    return 0


def _num(src, *keys, default=0.0) -> float:
    """从 src 里按 keys 顺序取第一个有效数值（字符串数字也算）。"""
    if not isinstance(src, dict):
        return default
    for k in keys:
        v = src.get(k)
        if v is None or v == "":
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return default


def _res_stacks(owner, key) -> float:
    """读 owner 的资源层数（effects[key].stacks；小数保真）。"""
    if not key:
        return 0.0
    e = (owner.get("effects") or {}).get(key)
    if not isinstance(e, dict):
        return 0.0
    try:
        return float(e.get("stacks", 0) or 0)
    except Exception:
        return 0.0


def _mount(owner, event: str, decl: dict) -> None:
    """挂触发器（幂等：同 action+key 只留一条，重复施放只刷新态）。"""
    lst = owner.setdefault("triggers", {}).setdefault(event, [])
    for t in lst:
        if (isinstance(t, dict) and t.get("action") == decl.get("action")
                and t.get("key") == decl.get("key")):
            t.update(decl)
            return
    lst.append(decl)


def _norm_pct(v: float) -> float:
    """百分比归一：>1 视为百分数（20 → 0.20）；负值/越界收敛到 [0, 0.9]。"""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0.0
    if v > 1.0:
        v = v / 100.0
    return max(0.0, min(v, 0.9))


# ============================================================
# 1. 通用团队面幅（面板类 *_all）
# ============================================================

@register_action("team_apply")
def team_apply(battle, caster, target, params, logs):
    """把引擎既有 `apply` 逐个发给同侧全队（面板增益类）。

    `atk_all` / `def_all` / `matk_all` / `crit_all` / `spd_all` / `atk_matk_all` /
    `dodge_reduce_all` 的面板段统一走这里——数值仍由 EFFECT_RULES 面板声明提供
    （引擎零改动；本动作只是把同一动作复制到每个队友身上）。
    """
    src = caster if isinstance(caster, dict) else target
    if src is None:
        return
    key = params.get("key") or ""
    if not key:
        return
    turns = _turns(params)
    inner = {"type": "apply", "key": key}
    if turns > 0:
        inner["turns"] = turns
    members = team_of(battle, src)
    if not members:
        return
    for a in members:
        apply_effects(battle, a, a, [dict(inner)], logs)
    logs.append(f"🛡️ {params.get('label') or key}：全队 {len(members)} 人获得增益")


# ============================================================
# 2. 护盾（百分比 / 按层递增 / 固定值；团队与自身两形态）
# ============================================================

def _stat_of(battle, actor, name: str) -> float:
    """读 actor 聚合面板某属性（atk/matk/…）——盾值按属性折算时用。"""
    if not name:
        return 0.0
    try:
        from saintess_engine import stats as _S
        st = _S.actor_stats(battle, actor) or {}
        return float(st.get(name, 0) or 0)
    except Exception:
        try:
            return float(actor.get(name, 0) or 0)
        except Exception:
            return 0.0


def _shield_value(battle, src, params) -> tuple:
    """算盾值与刻数。返回 (value, turns)；value <= 0 = 无此行为。

    基数 `shield_base_stat`：缺省 = 生命上限（`max_hp`）；也可给 `atk` / `matk`
    （如「每层充能转 8% 魔攻护盾」）。
    """
    info = _info(params)
    turns = _turns(params, info)
    base_stat = str(params.get("base_stat") or info.get("shield_base_stat") or "")
    if base_stat:
        base = _stat_of(battle, src, base_stat)
    else:
        try:
            base = float(src.get("max_hp", 1) or 1)
        except Exception:
            base = 1.0
    # 数值优先级（2026-09-11 修）：**技能数据声明了 shield_* 就以数据为准**——
    # 引擎 `_do_buff` 会给护盾类塞一个通用默认 `pct=0.20`（怪物盾「20% 生命护盾」在用），
    # 若与技能自己的 `shield_per_stack` 相加会污染（坚盾壁垒 0.20+0.30=0.50 的 bug）。
    # 只有技能**完全没声明**时，才用调用方传入的 pct/value（保持怪物盾旧行为）。
    info_pct = _num(info, "shield_pct")
    info_per = _num(info, "shield_per_stack")
    info_val = _num(info, "shield_value")
    if info_pct or info_per or info_val:
        pct, per, value = info_pct, info_per, int(info_val)
    else:
        pct = _num(params, "pct", "shield_pct", "value")
        per = _num(params, "per_stack", "shield_per_stack")
        value = int(_num(params, "value", "shield_value"))
    if per > 0:
        n = _num(params, "stacks")
        if n <= 0:
            n = _num(info, "shield_stacks")
        if n <= 0:
            n = _res_stacks(src, params.get("res_key") or info.get("shield_res_key") or "")
        pct = float(pct) + float(per) * float(n)
    if value <= 0 and pct > 0:
        value = int(base * _norm_pct(pct))
    return value, turns


@register_action("team_shield")
def team_shield(battle, caster, target, params, logs):
    """全队护盾（盾值口径见 `_shield_value`：pct / per_stack / value 三形态可叠加）。"""
    from saintess_engine.battle.effects import act_shield

    src = caster if isinstance(caster, dict) else target
    if src is None:
        return
    value, turns = _shield_value(battle, src, params)
    if value <= 0:
        return  # 缺字段 = 无此行为（零默认值铁律）
    turns = turns or 12
    key = params.get("key") or "shield"
    halve = bool(params.get("halve", False))
    members = team_of(battle, src)
    if not members:
        return
    for a in members:
        act_shield(battle, a, a, {"key": key, "value": value, "turns": turns, "halve": halve}, logs)
    logs.append(f"🛡️ {params.get('label') or '护盾'}：全队 {len(members)} 人各获 {value} 点护盾（{turns} 刻）")


@register_action("self_shield")
def self_shield(battle, caster, target, params, logs):
    """自身护盾（同口径；装备/药水/自身技能用）。"""
    from saintess_engine.battle.effects import act_shield

    src = caster if isinstance(caster, dict) else target
    if src is None:
        return
    value, turns = _shield_value(battle, src, params)
    if value <= 0:
        return
    turns = turns or 10
    key = params.get("key") or "shield"
    halve = bool(params.get("halve", False))
    act_shield(battle, src, src, {"key": key, "value": value, "turns": turns, "halve": halve}, logs)
    logs.append(f"🛡️ {params.get('label') or '护盾'}：获得 {value} 点护盾（{turns} 刻）")


# ============================================================
# 3. 全队减伤（乘算叠加；写态 + taken_calc 触发器）
# ============================================================

def _alt_reduce(src, params) -> float:
    """条件升档减伤（可选）：`reduce_alt` + `reduce_alt_res` + `reduce_alt_ge`。

    语义 =「资源 ≥ 阈值时，减伤由基础档升到 alt 档」（如不破壁垒：战意 ≥8 → 30%→50%）。
    资源层数读施法者 `effects[res].stacks`；缺任一字段 = 无升档（零默认值铁律）。
    """
    info = _info(params)
    alt = _num(params, "reduce_alt") or _num(info, "reduce_alt")
    if alt <= 0:
        return 0.0
    res = params.get("reduce_alt_res") or info.get("reduce_alt_res") or ""
    thr = _num(params, "reduce_alt_ge") or _num(info, "reduce_alt_ge")
    if not res or thr <= 0:
        return 0.0
    return _norm_pct(alt) if _res_stacks(src, res) >= thr else 0.0


def _reduce_of(params) -> float:
    """减伤比例：params/info 的 reduce|reduce_pct|value，或 mech_val 折算，或声明表。"""
    info = _info(params)
    r = _num(params, "reduce", "reduce_pct", "value") or _num(info, "reduce", "reduce_pct")
    if r <= 0:
        mv = _num(info, "mech_val")
        if mv > 1:
            r = mv / 100.0
        elif mv > 0:
            r = mv
    if r <= 0:
        from saintess_engine.battle.state_effects import state_def
        cfg = state_def(params.get("key") or params.get("type") or "") or {}
        r = float((cfg.get("stat_scale") or {}).get("reduce") or 0)
    return _norm_pct(r)


@register_action("team_taken_reduce")
def team_taken_reduce(battle, caster, target, params, logs):
    """全队减伤：给每个队友写 `team:reduce:<标签>` 态 + 挂 taken_calc 触发器。

    多个减伤来源各自一条态/触发器 → `ctx.mult` 连乘 = **乘算叠加**（鱼鱼拍板）。
    同一门技能重复施放只刷新态；不同技能（不同标签）叠加。
    """
    src = caster if isinstance(caster, dict) else target
    if src is None:
        return
    turns = _turns(params, _info(params))
    if turns <= 0:
        return
    r = _reduce_of(params)
    if r <= 0:
        return  # 缺字段 = 无此行为
    # 条件升档（不破壁垒「战意 ≥8 → 30%→50%」：两档取较高者）
    _alt = _alt_reduce(src, params)
    if _alt > r:
        r = _alt
    # 标签取**技能标识**（技能名优先）——不同技能的减伤各自一条态 → 乘算叠加；
    #   同一技能重复施放 = 同标签 = 刷新刻数（不重复叠乘）。用 effect 名词做标签会让
    #   两门都叫 reduce_all 的技能互相覆盖（叠加口径失效），故必须带技能名。
    tag = str(params.get("key") or _info(params).get("name") or params.get("type") or "reduce")
    state_key = f"{PREFIX}reduce:{tag}"
    members = team_of(battle, src)
    if not members:
        return
    now = _now(battle)
    for a in members:
        a.setdefault("effects", {})[state_key] = {"stacks": 1, "expire": now + turns, "reduce": r}
        _mount(a, "taken_calc", {"action": "team_ss_reduce_apply", "key": state_key})
    logs.append(f"🛡️ {params.get('label') or '减伤'}：全队 {len(members)} 人减伤 {int(r * 100)}%（{turns} 刻）")


@register_action("team_ss_reduce_apply")
def team_ss_reduce_apply(battle, caster, target, params, logs):
    """taken_calc 触发器：读持有者的减伤态 → `ctx.mult *= (1-reduce)`。"""
    ctx = getattr(battle, "_fire_ctx", None)
    if ctx is None:
        return
    holder = params.get("_owner")
    key = params.get("key") or ""
    e = (holder.get("effects") or {}).get(key) if isinstance(holder, dict) else None
    if not isinstance(e, dict):
        return  # 态已过期（引擎自动清理）= 无此行为
    r = _norm_pct(_num(e, "reduce"))
    if r <= 0:
        return
    ctx["mult"] = float(ctx.get("mult", 1.0) or 1.0) * (1.0 - r)


# ============================================================
# 4. 目标易伤（单体；写态 + taken_calc 挂到目标）
# ============================================================

@register_action("timed_vuln")
def timed_vuln(battle, caster, target, params, logs):
    """目标易伤（vuln）：目标受到的伤害 ×(1+amp)，持续 turns 刻。

    与 Boss 剧本的 `_dmg_taken_mult` 直写同语义，但**带刻数且自动过期**
    （态存目标 effects，引擎到期清理；不用上层记账）。
    """
    holder = target if isinstance(target, dict) else None
    if holder is None:
        return
    info = _info(params)
    turns = _turns(params, info)
    if turns <= 0:
        return
    amp = _norm_pct(_num(params, "amp", "vuln", "value") or _num(info, "vuln_amp"))
    if amp <= 0:
        return
    tag = str(params.get("key") or info.get("name") or params.get("type") or "vuln")
    state_key = f"{PREFIX}vuln:{tag}"
    holder.setdefault("effects", {})[state_key] = {
        "stacks": 1, "expire": _now(battle) + turns, "amp": amp}
    _mount(holder, "taken_calc", {"action": "timed_vuln_apply", "key": state_key})
    logs.append(f"💢 {holder.get('name', '目标')} 受到伤害 +{int(amp * 100)}%（{turns} 刻）")


@register_action("timed_vuln_apply")
def timed_vuln_apply(battle, caster, target, params, logs):
    """taken_calc 触发器：读易伤态 → `ctx.mult *= (1+amp)`。"""
    ctx = getattr(battle, "_fire_ctx", None)
    holder = params.get("_owner")
    key = params.get("key") or ""
    if ctx is None or not isinstance(holder, dict):
        return
    e = (holder.get("effects") or {}).get(key)
    if not isinstance(e, dict):
        return
    amp = _norm_pct(_num(e, "amp"))
    if amp <= 0:
        return
    ctx["mult"] = float(ctx.get("mult", 1.0) or 1.0) * (1.0 + amp)


# ============================================================
# 5. 全队伤害乘区（按伤害类型 / 目标标记过滤）
# ============================================================

@register_action("team_dmg_aura")
def team_dmg_aura(battle, caster, target, params, logs):
    """全队伤害乘区：给每个队友挂 dmg_calc 触发器（条件由技能数据声明）。

    过滤条件（全部可选，缺省 = 无条件）：
    - `aura_kind`:   伤害类型匹配才生效（str 或 list，如 ["魔法"]）
    - `aura_mark`:   目标带该标记（层数 > 0）才生效（如猎印 hunt_mark）
    - `aura_lock`:   目标带该锁定态才生效（星轨锁定）
    数值 = `aura_add`（乘区增量，0.20 = +20%）。
    """
    src = caster if isinstance(caster, dict) else target
    if src is None:
        return
    info = _info(params)
    turns = _turns(params, info)
    if turns <= 0:
        return
    add = _norm_pct(_num(params, "add", "mult") or _num(info, "aura_add"))
    if add <= 0:
        return
    tag = str(params.get("key") or info.get("name") or params.get("type") or "aura")
    state_key = f"{PREFIX}aura:{tag}"
    decl = {"action": "team_dmg_aura_apply", "key": state_key, "add": add,
            "aura_kind": params.get("dmg_kind") or info.get("aura_kind"),
            "aura_mark": params.get("target_mark") or info.get("aura_mark"),
            "aura_lock": params.get("target_lock") or info.get("aura_lock")}
    members = team_of(battle, src)
    if not members:
        return
    now = _now(battle)
    for a in members:
        a.setdefault("effects", {})[state_key] = {"stacks": 1, "expire": now + turns}
        _mount(a, "dmg_calc", dict(decl))
    logs.append(f"🔮 {params.get('label') or '全队增伤'}：全队 {len(members)} 人伤害 +{int(add * 100)}%（{turns} 刻）")


@register_action("team_dmg_aura_apply")
def team_dmg_aura_apply(battle, caster, target, params, logs):
    """dmg_calc 触发器：态在 + 条件满足 → `ctx.mult *= (1+add)`。"""
    ctx = getattr(battle, "_fire_ctx", None)
    holder = params.get("_owner")
    key = params.get("key") or ""
    if ctx is None or not isinstance(holder, dict):
        return
    if not isinstance((holder.get("effects") or {}).get(key), dict):
        return  # 态过期 = 无此行为
    kinds = params.get("aura_kind") or params.get("dmg_kind")
    if kinds:
        info = ctx.get("info") or {}
        k = str(info.get("kind") or "")
        if not isinstance(kinds, (list, tuple)):
            kinds = [kinds]
        if not any(str(x) and str(x) in k for x in kinds):
            return
    mark = params.get("aura_mark") or params.get("target_mark")
    if mark:
        tg = ctx.get("target") or {}
        e = (tg.get("effects") or {}).get(str(mark))
        if not (isinstance(e, dict) and _num(e, "stacks") > 0):
            return
    lock = params.get("aura_lock") or params.get("target_lock")
    if lock:
        tg = ctx.get("target") or {}
        if not isinstance((tg.get("effects") or {}).get(f"{PREFIX}lock:{lock}"), dict):
            return
    add = _norm_pct(_num(params, "add"))
    if add <= 0:
        return
    ctx["mult"] = float(ctx.get("mult", 1.0) or 1.0) * (1.0 + add)


@register_action("target_lock_mark")
def target_lock_mark(battle, caster, target, params, logs):
    """锁定标记（星轨锁定用）：给目标写带刻数的锁定态（供 `team_dmg_aura` 的 aura_lock 判定）。"""
    holder = target if isinstance(target, dict) else None
    if holder is None:
        return
    info = _info(params)
    turns = _turns(params, info)
    if turns <= 0:
        return
    tag = str(params.get("lock") or info.get("lock_tag") or params.get("key") or "star")
    holder.setdefault("effects", {})[f"{PREFIX}lock:{tag}"] = {
        "stacks": 1, "expire": _now(battle) + turns}
    logs.append(f"🎯 {holder.get('name', '目标')} 被锁定（{turns} 刻）")


# ============================================================
# 6. 免疫控制（写态；引擎控制落地处消费该态）
# ============================================================

@register_action("team_cc_immune")
def team_cc_immune(battle, caster, target, params, logs):
    """全队免疫控制：给每个队友写 `cc_immune` 态（带刻数）。

    消费点 = 引擎控制类效果落地前的免疫查询（`effects.act_apply` 的 mode 分支；
    引擎只读**态名**，不认游戏名词）。
    """
    src = caster if isinstance(caster, dict) else target
    if src is None:
        return
    turns = _turns(params, _info(params))
    if turns <= 0:
        return
    members = team_of(battle, src)
    if not members:
        return
    now = _now(battle)
    for a in members:
        a.setdefault("effects", {})["cc_immune"] = {"stacks": 1, "expire": now + turns}
    logs.append(f"✨ {params.get('label') or '免疫控制'}：全队 {len(members)} 人免疫控制（{turns} 刻）")


@register_action("self_cc_immune")
def self_cc_immune(battle, caster, target, params, logs):
    """自身免疫控制（潜行类技能的免疫段）。"""
    src = caster if isinstance(caster, dict) else target
    if src is None:
        return
    turns = _turns(params, _info(params))
    if turns <= 0:
        return
    src.setdefault("effects", {})["cc_immune"] = {
        "stacks": 1, "expire": _now(battle) + turns}
    logs.append(f"✨ {params.get('label') or '免疫控制'}（{turns} 刻）")


# ============================================================
# 7. 挡刀（protect：誓约之盾 / 守护誓言）
# ============================================================

@register_action("team_guard")
def team_guard(battle, caster, target, params, logs):
    """全队挡刀：给每个队友写 `guard_uid` = 施法者 uid（引擎承伤转移钩子读它）。

    - 引擎侧：`landing.deal_damage` 在**一切减免结算之前**检查 `target["guard_uid"]`，
      命中则问 `battle.redirect_hook` → 把这次伤害交给保护者（递归深度 1）。
    - 反伤：给保护者写 `team:guard:*` 态 + 挂 `on_taken` 反伤触发器（`guard_reflect`），
      态到期 = 反伤失效（引擎 effects 自动清理）。
    - 刻数到期清理队友的 `guard_uid`：挂 `time_advance` → `guard_expire`。
    """
    src = caster if isinstance(caster, dict) else target
    if src is None:
        return
    info = _info(params)
    turns = _turns(params, info)
    if turns <= 0:
        return
    uid = src.get("uid")
    if not uid:
        return
    now = _now(battle)
    tag = str(params.get("key") or info.get("name") or "guard")
    state_key = f"{PREFIX}guard:{tag}"
    # 保护者的反伤态（挡刀期间生效；reflect_pct 由技能数据给，缺省 = 只挡不反）
    reflect = _norm_pct(_num(params, "reflect_pct") or _num(info, "reflect_pct"))
    src.setdefault("effects", {})[state_key] = {
        "stacks": 1, "expire": now + turns, "reflect_pct": reflect}
    _mount(src, "on_taken", {"action": "guard_reflect", "key": state_key})
    # 队友身上写保护者 uid（含施法者自己？不含——自己不需要被自己挡）
    n = 0
    for a in team_of(battle, src):
        if a is src:
            continue
        a["guard_uid"] = uid
        _mount(a, "time_advance", {"action": "guard_expire", "key": state_key,
                                  "until": now + turns, "uid": uid})
        n += 1
    logs.append(f"🛡️ {params.get('label') or '守护'}：为 {n} 名队友挡刀（{turns} 刻"
                + (f"，反伤 {int(reflect * 100)}%" if reflect > 0 else "") + "）")


@register_action("guard_expire")
def guard_expire(battle, caster, target, params, logs):
    """time_advance 触发器：挡刀到期 → 清掉持有者身上的 `guard_uid`。"""
    holder = params.get("_owner")
    if not isinstance(holder, dict):
        return
    try:
        until = float(params.get("until", 0) or 0)
    except Exception:
        return
    if until and _now(battle) >= until:
        holder.pop("guard_uid", None)


@register_action("guard_reflect")
def guard_reflect(battle, caster, target, params, logs):
    """on_taken 触发器：挡刀期间受击 → 按 `reflect_pct` 反弹给攻击者。

    语义对齐 `passive_reflect_bar` / `we_reflect`：无来源（DOT/环境伤）不反制。
    """
    from saintess_engine.battle.actors import actor_alive
    from saintess_engine.battle.landing import deal_damage

    holder = params.get("_owner") or target
    key = params.get("key") or ""
    if not isinstance(holder, dict) or not actor_alive(holder):
        return
    e = (holder.get("effects") or {}).get(key)
    if not isinstance(e, dict):
        return  # 挡刀态已过期 = 不反伤
    pct = _norm_pct(_num(e, "reflect_pct"))
    if pct <= 0:
        return
    ctx = getattr(battle, "_fire_ctx", None) or {}
    attacker = ctx.get("source")
    if not isinstance(attacker, dict) or not actor_alive(attacker):
        return
    rd = max(1, int(int(ctx.get("dmg", 0) or 0) * pct))
    deal_damage(battle, holder, attacker, rd, logs)
    logs.append(f"⚔️ 守护反伤：反弹 {rd} 点伤害！")


# ============================================================
# 8. 格挡（block_reflect：铁山靠）
# ============================================================

@register_action("block_once")
def block_once(battle, caster, target, params, logs):
    """格挡 1 次攻击并反伤（铁山靠）：写格挡态 + 挂 taken_calc 触发器（命中即消耗）。"""
    src = caster if isinstance(caster, dict) else target
    if src is None:
        return
    info = _info(params)
    turns = _turns(params, info)
    if turns <= 0:
        return
    tag = str(params.get("key") or info.get("name") or "block")
    state_key = f"{PREFIX}block:{tag}"
    reflect = _norm_pct(_num(params, "reflect_pct") or _num(info, "reflect_pct"))
    src.setdefault("effects", {})[state_key] = {
        "stacks": 1, "expire": _now(battle) + turns, "reflect_pct": reflect}
    _mount(src, "taken_calc", {"action": "block_once_apply", "key": state_key})
    # 反伤走受击后事件（见 block_reflect_hit 的注释：taken_calc 里不可递归）
    _mount(src, "on_taken", {"action": "block_reflect_hit", "key": state_key,
                             "reflect_pct": reflect})
    logs.append(f"🛡️ {params.get('label') or '格挡'}：格挡下一次攻击"
                + (f"（反伤 {int(reflect * 100)}%）" if reflect > 0 else ""))


@register_action("block_once_apply")
def block_once_apply(battle, caster, target, params, logs):
    """taken_calc 触发器：格挡态在 → 本次伤害归零（引擎 clamp 到 1）+ 反伤 + 消耗态。"""
    from saintess_engine.battle.actors import actor_alive
    from saintess_engine.battle.landing import deal_damage

    ctx = getattr(battle, "_fire_ctx", None)
    holder = params.get("_owner")
    key = params.get("key") or ""
    if ctx is None or not isinstance(holder, dict):
        return
    e = (holder.get("effects") or {}).get(key)
    if not isinstance(e, dict):
        return  # 已消耗/过期
    # ⚠️ 事件分离铁律（实测踩坑）：反伤**不得在 taken_calc 里递归**——
    #   反伤递归调 deal_damage 会把 `battle._fire_ctx` 换成新 ctx，本次承伤归零随即失效。
    #   故：taken_calc 只做「格挡 + 记原始伤害」，反伤交给 on_taken（受击后事件，见
    #   block_reflect_hit）——那时本次结算已完成，换 ctx 无副作用。
    ctx["mult"] = 0.0                       # 本次承伤归零（引擎 clamp 到至少 1 点）
    holder["_block_base"] = int(ctx.get("dmg", 0) or 0)
    holder["effects"].pop(key, None)        # 1 次性：格挡后消耗
    logs.append(f"🛡️ 【{holder.get('name', '目标')}】格挡了这一击！")


@register_action("block_reflect_hit")
def block_reflect_hit(battle, caster, target, params, logs):
    """on_taken 触发器：格挡成功后按记录的原始伤害反伤攻击者（铁山靠 40%）。"""
    from saintess_engine.battle.actors import actor_alive
    from saintess_engine.battle.landing import deal_damage

    holder = params.get("_owner") or target
    if not isinstance(holder, dict) or not actor_alive(holder):
        return
    base = int(holder.pop("_block_base", 0) or 0)
    if base <= 0:
        return
    pct = _norm_pct(_num(params, "reflect_pct"))
    if pct <= 0:
        return
    ctx = getattr(battle, "_fire_ctx", None) or {}
    attacker = ctx.get("source")
    if not isinstance(attacker, dict) or not actor_alive(attacker):
        return
    rd = max(1, int(base * pct))
    deal_damage(battle, holder, attacker, rd, logs)
    logs.append(f"⚔️ 格挡反伤：{rd} 点！")


# 注：元素流转（`element_switch`）的完整实现在 `game/services/battle_element_procs.py`（主系切换 + 下次挂印转换 + 元素两轴）。

# ============================================================
# 10. 奥术力场（arcane_field：护盾 / 利刃 二选一）
# ============================================================

@register_action("arcane_field")
def arcane_field(battle, caster, target, params, logs):
    """奥术力场（lv88）：消耗 2 点充能，**按战前偏好**落地「护盾」或「利刃」档。

    档位来源：`actor["battle_prefs"]["arcane_field"]`（命令层 `战前力场 盾|刃` 设置，
    缺省 = 盾——保命优先）。
    - 盾档：按技能数据的三形态算盾（`shield_per_stack` 每层充能 ×8% 魔攻）
    - 刃档：写 `team:edge:arcane_field` 态 + 挂 dmg_calc 触发器 —— 下一次**奥术系**
      技能（`info.mech` 以 `arcane` 开头）伤害 ×1.3，随后消耗该态（一次性）
    - 两档都消耗 2 点充能（缺字段/不足 = `consume` 自身拦截，不白给）
    """
    src = caster if isinstance(caster, dict) else target
    if src is None:
        return
    info = _info(params)
    pref = str((src.get("battle_prefs") or {}).get("arcane_field") or "盾")
    # 充能消耗（两档共用；desc「消耗 2 点充能」）
    cost = int(_num(params, "res_cost") or _num(info, "field_cost") or 2)
    if cost > 0:
        apply_effects(battle, src, src,
                      [{"type": "consume", "key": "arcane", "amount": cost, "on": "caster"}],
                      logs)
    if pref == "刃":
        turns = _turns(params, info) or 10
        state_key = f"{PREFIX}edge:arcane_field"
        src.setdefault("effects", {})[state_key] = {
            "stacks": 1, "expire": _now(battle) + turns, "add": 0.30}
        _mount(src, "dmg_calc", {"action": "arcane_edge_apply", "key": state_key,
                                 "mech_prefix": "arcane", "add": 0.30})
        logs.append("🔮 奥术力场【利刃】：下次奥术技伤害 ×1.3")
        return
    self_shield(battle, caster, target, params, logs)
    logs.append("🔮 奥术力场【护盾】")


@register_action("arcane_edge_apply")
def arcane_edge_apply(battle, caster, target, params, logs):
    """dmg_calc：利刃态在 + 本次是**奥术系**技能 → 伤害 ×(1+add)，并消耗该态（一次性）。"""
    ctx = getattr(battle, "_fire_ctx", None)
    holder = params.get("_owner")
    key = params.get("key") or ""
    if ctx is None or not isinstance(holder, dict):
        return
    e = (holder.get("effects") or {}).get(key)
    if not isinstance(e, dict):
        return  # 态已过期/已消耗
    info = ctx.get("info") or {}
    pre = str(params.get("mech_prefix") or "arcane")
    if not str(info.get("mech") or "").startswith(pre):
        return  # 非奥术技：不消费、不生效（等下一次奥术技）
    add = _norm_pct(_num(e, "add") or _num(params, "add"))
    if add <= 0:
        return
    ctx["mult"] = float(ctx.get("mult", 1.0) or 1.0) * (1.0 + add)
    holder["effects"].pop(key, None)      # 一次性
    logs.append(f"🗡️ 奥术力场·利刃：本次奥术技伤害 +{int(add * 100)}%！")
