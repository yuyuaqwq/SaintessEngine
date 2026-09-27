# -*- coding: utf-8 -*-
"""v181.P4 saintess_engine 引擎——actor 模型层（纯数据，无逻辑）。

按 docs/archive/REFACTOR_v181P4_FULL_PLAN.md Part 1/2 实现：
- actor = 全同构 dict（无身份逻辑；class_name 只选面板公式，side 只分组）
- sides = {side名: [actor, ...]}（唯一容器）
- ActCtx = 每次行动上下文（显式 caster/target/scope，消灭隐式全局目标）
- 引擎逻辑只用字段值，不按字段猜身份
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# ============================================================
# ActCtx：行动上下文（每次行动新建）
# ============================================================

@dataclass
class ActCtx:
    """一次行动的全部上下文。命令层/AI 先决定 ctx（选目标），再交给 Battle.act()。"""
    caster: dict                          # 施法者 actor（谁在行动）
    action: str = "attack"                # attack|skill|defend|flee|use_item|auto
    skill_name: Optional[str] = None      # 技能名（action=skill 时）
    info: Optional[dict] = None           # 技能/动作配置（技能 dict）
    target: Optional[dict] = None         # 单目标 actor（伤害/debuff 对象）
    target_side: Optional[str] = None     # 范围目标（AOE 打哪个 side；"all"=敌对全阵营）
    scope: str = "single"                 # single|all|front|side:<name>|self
    unstoppable: bool = False             # 出招窗口霸体（内容侧声明的布尔；
                                          #   真 = 前摇期不被任何效果打断 —— T15 §0 D15 ③）

    def __post_init__(self):
        # 信息冗余防御：action=skill 但 info 为空时尝试从 caster.skills 索引
        # （数据桥在 Battle 构造时把技能 dict 挂到 actor["_skill_index"]）
        if self.action == "skill" and self.info is None and self.skill_name:
            _idx = (self.caster or {}).get("_skill_index") or {}
            self.info = _idx.get(self.skill_name) or {}
        # scope 缺省推导：有 target_side / scope=all 语义保留；纯单目标默认 single
        if self.scope == "single" and self.target_side:
            self.scope = self.target_side if self.target_side != "all" else "all"


# ============================================================
# actor 构造
# ============================================================

# 播种的战斗可变状态键（全部 actor 同构）
# V 系列统一：state/buffs/hot/debuffs 四容器 → 单 effects 容器
#   effects[key] = {"stacks": N, "expire": t|None, ...效果快照字段}
# shields（承伤资源）/ cooldown（调度）保留独立容器（见设计文档 §2.5）
_MUTABLE_KEYS = {
    "effects": dict,
    "shields": dict,
    "cooldown": dict,
    "charging": None,
}


def make_actor(
    uid: str,
    name: str,
    side: str,
    kind: str = "monster",
    human_controlled: bool = False,
    class_name: Optional[str] = None,
    level: int = 1,
    equipment: Optional[dict] = None,
    skills: Optional[list] = None,
    learned_skills: Optional[list] = None,
    auto_act: Optional[dict] = None,
    **stats,
) -> dict:
    """构造一个全同构 actor dict。

    - 播种全部战斗可变状态键（buffs/state/shields/...）
    - 玩家面板字段（hp/mp/atk/def/spd/crit/...）由调用方按需传入（make_player 之类工厂）；
      引擎不在构造时做玩家面板聚合（那是 stats.py actor_stats 的活）。
    - 普通怪（无 class_name）：stats 里直接给 atk/def/matk/mdef/spd/crit/... 字段。
    - 玩家（有 class_name）：stats 给基础字段；聚合面板用 actor_stats()（stats.py）。
    - ⚠️ 等级字段统一 level：引擎不认 lv。旧怪模板 lv 由数据桥入口翻译，这里不做兼容。
    """
    actor: dict = {
        # ① 身份/数据标签
        "uid": uid,
        "name": name,
        "side": side,
        "kind": kind,
        "human_controlled": bool(human_controlled),
        # ② 面板基础字段（实时 hp/mp 直接读写；聚合见 stats.actor_stats）
        "hp": int(stats.get("hp", stats.get("max_hp", 1))),
        "max_hp": int(stats.get("max_hp", 1)),
        "mp": int(stats.get("mp", 0)),
        "max_mp": int(stats.get("max_mp", 0)),
        "atk": int(stats.get("atk", 0)),
        "matk": int(stats.get("matk", 0)),
        "def": int(stats.get("def", 0)),
        "mdef": int(stats.get("mdef", 0)),
        "spd": int(stats.get("spd", 0)),
        "crit": float(stats.get("crit", 0.0)),
        "dodge": float(stats.get("dodge", 0.0)),
        "crit_dmg": float(stats.get("crit_dmg", 0.0)),
        "luck": float(stats.get("luck", 0.0)),
        "tenacity": float(stats.get("tenacity", 0.0)),
        "block": float(stats.get("block", 0.0)),
        "pene": float(stats.get("pene", 0.0)),
        "race": stats.get("race"),
        # ③ 战斗可变状态（播种）
        # V 系列统一：单 effects 容器（原 state/buffs/hot/debuffs 四键合并）
        #   条目形态 effects[key] = {"stacks": 叠层, "expire": 绝对时刻|None, "value": 动态数值|None}
        #   + 运行时辅助 last_tick/hits_left（schedule/消费点自管，可缺省）
        #   行为/数值/周期/消费全查 EFFECT_RULES[key] 声明（引擎零名词）
        "effects": dict(stats.get("effects") or {}),
        # 承伤资源（吸收伤害的护盾量值；与效果正交，保留独立——见设计 §2.5）
        "shields": dict(stats.get("shields") or {}),
        # 调度资源（技能下次可用时刻；保留独立——见设计 §2.5）
        "cooldown": dict(stats.get("cooldown") or {}),
        "charging": stats.get("charging"),
        "ct": float(stats.get("ct", 0.0)),
        "poi_buff": stats.get("poi_buff"),
        # 事件触发声明（N8）：{事件名: [效果名词 dict, ...]}——数据桥/上层构造时
        # 把装备特效/词条/套装/被动翻译挂上；引擎 fire() 匹配后走名词→动词翻译。
        # 引擎不认识事件效果内容（零游戏知识），只分发。
        "triggers": dict(stats.get("triggers") or {}),
        # ④ 配置/能力
        "class_name": class_name,
        "level": int(stats.get("level", level)),
        "equipment": dict(equipment or stats.get("equipment") or {}),
        "skills": list(skills or stats.get("skills") or []),
        "learned_skills": list(learned_skills or stats.get("learned_skills") or []),
        "auto_act": auto_act or stats.get("auto_act"),
        # 技能索引（Battle 构造时灌入：技能名 → 技能 dict）
        "_skill_index": {},
        # 外部扩展区（引擎绝不读；职业/机制自定义状态放这里，命名空间自管）
        "ext": {},
    }
    # 携带的额外字段（rank/reach/role/traits/exp/gold/drops 等数据标签或旧怪字段；★ 引擎只看 `traits` 判定标签，见 traits.py）
    for k, v in stats.items():
        if k not in actor:
            actor[k] = v
    # 面板配置透传（旧玩家 dict 字段：evolve_path/class_tier/attributes 供 stats 重算用）
    for k in ("evolve_path", "class_tier", "attributes"):
        if k in stats and k not in actor:
            actor[k] = stats[k]
    return actor


# ============================================================
# 纯 helper（读 actor 状态）
# ============================================================

def actor_alive(actor: dict) -> bool:
    """actor 存活判定：hp > 0。"""
    return bool(actor) and int(actor.get("hp", 0) or 0) > 0


def actor_dead(actor: dict) -> bool:
    return not actor_alive(actor)


def effects_of(actor: dict) -> dict:
    """actor 统一效果容器。make_actor/from_state 已播种；纯读兜底。"""
    if actor is None:
        return {}
    ef = actor.get("effects")
    return ef if isinstance(ef, dict) else {}


# ============================================================
# effects 容器：条目词表 + 唯一写入口 + 查询口（引擎中性词表，零游戏名词）
# ============================================================
# actor 的**一切**临时状态都住在这个容器里（`effects[tag] = entry`）：tag 名由内容侧/调用方
# 自起（引擎只认结构，不认游戏名词）；条目的**生命周期是容器第一类属性** —— 写在条目里、
# 由统一的消费段执行，**不靠「谁记得清」**（防御姿态那个 bug = 到期没人清）：
#
#   | 字段 | 语义 | 谁消费 |
#   |---|---|---|
#   | `stacks` | 层数（纯计数/叠层资源） | 各消费点按声明读写 |
#   | `expire` | **时间到期**：绝对时刻 | `schedule._settle_time_effects`（每个时间片） |
#   | `until`  | **边界到期**：帧名（如 `own_act`） | 那一帧的通用消费段 `consume_windows` / 离场 `drop_windows` |
#   | `period` | 周期结算声明（dot/hot/gain…） | `_settle_time_effects` 的周期段 |
#   | `grants` | **授予标签**：本条目额外代表哪些 tag | 查询口 `has_tag`（层级 = `.` 边界前缀） |
#   | `mode`   | **控制**语义（skip / no_skill） | `Battle.act` 的控制消费段 + `effects.py` 落地前免疫查询 |
#   | 其余键    | 数值/来源快照（`value` / `src` / …） | 各自的读点 |
#
# ★ 「窗口」= `until` 那一类：从现在起到某个**边界帧**为止有效的临时状态（防御姿态是第一个
#   实例）。`until` 的取值是**引擎词表**（不是游戏名词）：`own_act` = 「到你自己的这一帧为止」。
# ★ 为什么窗口不借用 `mode`：`mode` 是**控制效果**的命名空间（`effects.py` 的免疫控制查询点按
#   `mode != None` 判「控制类」；`Battle.act` 的消费段按 mode=skip/no_skill 执行）—— 窗口条目
#   借它会被当成控制效果。故另起中性字段，语义单一。
STACKS_FIELD = "stacks"
EXPIRE_FIELD = "expire"
PERIOD_FIELD = "period"
WINDOW_FIELD = "until"
GRANTS_FIELD = "grants"
TAG_SEP = "."                    # 层级分隔：查 `control` 命中 `control.stun`

WINDOW_OWN_ACT = "own_act"       # 边界名：行动者自己的这一帧
DEFEND_TAG = "defend"            # 引擎内置动作类别 `defend` 的窗口 tag（引擎词，非游戏专名）


def open_entry(actor: dict, tag: str, *, stacks: int = 1, expire=None, until: str = None,
               period: dict = None, grants=None) -> dict:
    """容器条目的**唯一写入口**（引擎侧）：只落**声明了的**字段（None 不写键）。

    重复写同一个 tag = 覆盖（刷新语义归调用点声明：窗口重开 = 覆盖，与原「再敲一次防御」
    同口径）。容器缺失当场补（这是**写**路径，不是读兜底）。
    """
    ef = actor.get("effects")
    if not isinstance(ef, dict):
        ef = actor["effects"] = {}
    entry: dict = {STACKS_FIELD: int(stacks)}
    if expire is not None:
        entry[EXPIRE_FIELD] = expire
    if until:
        entry[WINDOW_FIELD] = until
    if period:
        entry[PERIOD_FIELD] = period
    if grants:
        entry[GRANTS_FIELD] = list(grants)
    ef[tag] = entry
    return entry


def open_window(actor: dict, tag: str, until: str = WINDOW_OWN_ACT, **kw) -> dict:
    """开一个**窗口条目**（= `until` 那一类，引擎侧唯一入口）。"""
    return open_entry(actor, tag, until=until, **kw)


def window_open(actor: dict, tag: str) -> bool:
    """窗口条目是否开着（**读容器一次**；裸 bool 兄弟字段已不存在）。"""
    return isinstance(effects_of(actor).get(tag), dict)


def _frame_match(until, want) -> bool:
    """边界名匹配：`want` 空 = 任何边界都算。"""
    if not want:
        return True
    return str(until) == str(want)


def consume_windows(actor: dict, until: str = WINDOW_OWN_ACT) -> list:
    """消费「到这一帧为止」的窗口条目（边界帧的**通用**消费段；返回被清掉的 tag）。

    引擎不认哪个 tag 是防御 —— 只认条目自己的边界声明。
    """
    ef = effects_of(actor)
    gone = []
    for _tag in list(ef.keys()):
        _e = ef.get(_tag)
        if isinstance(_e, dict) and _e.get(WINDOW_FIELD) and _frame_match(_e[WINDOW_FIELD], until):
            ef.pop(_tag, None)
            gone.append(_tag)
    return gone


def drop_windows(actor: dict) -> list:
    """actor 离场（死亡）：容器里所有窗口条目作废（按声明清，不认 tag 名）。"""
    ef = effects_of(actor)
    gone = []
    for _tag in list(ef.keys()):
        _e = ef.get(_tag)
        if isinstance(_e, dict) and _e.get(WINDOW_FIELD):
            ef.pop(_tag, None)
            gone.append(_tag)
    return gone


# ---- 查询口：tag（薄壳 —— 实现全在 `tags` 模块：注册表 + 统一面 + 层级）------

def tags_of(actor: dict) -> set:
    """actor 身上**当前**的全部 tag（= `tags.of`：traits ∪ 容器 key ∪ 条目 `grants`）。"""
    from . import tags as _T
    return set(_T.of(actor))


def has_tag(actor: dict, tag: str) -> bool:
    """actor 身上有没有这个 tag（= `tags.has`）—— **引擎侧唯一查询口**。

    层级：查 `control` 命中 `control.stun`（按 `.` 边界的前缀，父级查得到子级）；
    `control.stun` 不命中 `control`。引擎零游戏知识：tag 名全由内容侧起。
    """
    from . import tags as _T
    return _T.has(actor, tag)


def actor_ext(actor: dict) -> dict:
    """actor 外部扩展区（惰性播种）。职业/机制自定义状态写这里，引擎不读。"""
    if actor is None:
        return {}
    e = actor.get("ext")
    if not isinstance(e, dict):
        e = actor["ext"] = {}
    return e


def actor_side_of(battle, actor: dict) -> Optional[str]:
    """查 actor 属于哪个阵营（以 battle.sides 权威；actor.side 兜底）。"""
    if actor is None:
        return None
    sid = actor.get("side")
    if sid and sid in getattr(battle, "sides", {}):
        return sid
    # 找不到（actor 不在 sides 或没带 side）→ 按引用扫描一次
    for _sn, _acts in (getattr(battle, "sides", {}) or {}).items():
        for _a in _acts:
            if _a is actor or _a.get("uid") == actor.get("uid"):
                return _sn
    return sid  # 兜底 actor.side（无 sides 上下文时）


def hostile_sides(battle, side: str) -> list:
    """side 的敌对阵营名列表。

    简化规则（按 side 名推导，数据可在 Battle 构造时覆盖 hostile_map）：
    - 引擎不预设玩家/怪身份 → 敌对关系由 Battle.hostile_map 显式定义
    - 默认：除自己外的全部阵营
    """
    hm = getattr(battle, "hostile_map", None)
    if hm and side in hm:
        return list(hm[side])
    return [s for s in (battle.sides or {}).keys() if s != side]


def hostile_actors(battle, side: str) -> list:
    """side 的敌对阵营存活 actor 列表（AI 选目标用）。"""
    out = []
    for _sn in hostile_sides(battle, side):
        for _a in (battle.sides or {}).get(_sn, []):
            if actor_alive(_a):
                out.append(_a)
    return out
