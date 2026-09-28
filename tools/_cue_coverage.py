# -*- coding: utf-8 -*-
"""cue **覆盖尺**（设计案 `cue-decoupling.md` §3.2③「不许放过」那一半）。

为什么要有它
------------------------------------------------------------------
`tools/_cue_freeze.py` 的 5 组战斗是**逐字节冻结基线**（改脚本 = 毁基线），
它们只覆盖 61 条 cue 里的 45 条 —— 剩下 16 条「这 5 组打不到」。
设计案的判据是：**每条被迁移的 cue 计数必须 ≥1，打不到的必须补场景，不许放过**。
本工具就是「补场景」：**不动那 5 组**，另建一批最小场景，逐条把剩下的 cue 打到。
（判据 = `union(冻结 5 组, 本工具) == CUE_NAMES`；每条要么被驱动、要么在
`NEED_DRIVE` 里逐条写清够不着的原因 —— 第三态当场红。）

诚实性要求（★ 别把这条工具做成「自证」）
------------------------------------------------------------------
每个驱动函数都必须**走引擎真实的结算路径**（`deal_damage` / `_deal_hit` / `_do_heal` /
`_do_buff` / `_settle_lifesteal` / `heal_actor` / `gauge.bar_gain` / `bar_*_act` …），
不许直接调 `cue(...)` 把那一行凭空发出来 —— 那样只证明「总线通」，不证明「那条路真会发」。
每个驱动函数的 docstring 里写明**它触发的引擎发射点**（文件:行 或 函数名），便于复核。

跑法
------------------------------------------------------------------
    python tools/_cue_coverage.py                    # 用仓库自身树
    python tools/_cue_coverage.py --tree <另一棵树>
    python tools/_cue_coverage.py --json out.json    # 落档
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import _cue_freeze as F          # noqa: E402 —— 复用尺子的路径装配 / SpyText / 文本表 / 5 组基线

MISS = "   "


# ============================================================
# 驾驶舱：造人 / 造怪 / 造战斗 + 一张「哪些 cue 打到了」的账
# ============================================================

class Rig:
    def __init__(self, tree: str):
        F._setup_path(tree)
        from ext_combat import Battle
        from ext_combat.battle import actions as A
        from ext_combat.battle import effects as EFF
        from ext_combat.battle import landing as LAND
        from ext_combat.battle.cues import CUE_NAMES
        from content import apply_game_content
        from content.data.classes import build_player
        from content.data.monsters import build_monster

        self.Battle, self.A, self.EFF, self.LAND = Battle, A, EFF, LAND
        #: ★ 声明面用引擎自己的 `CUE_NAMES`（唯一真源）。
        #:  不用 `_cue_freeze` 的 `key_inventory` —— 那份是按 AST 扫**调用点**得出的，
        #:  B4/B5 之后引擎侧已无 `render_via(...)` 这类键化调用点，它只剩 `cue.render_failed` 一条。
        self.names = tuple(str(x) for x in CUE_NAMES)
        self.apply = apply_game_content
        self.mk_player_raw, self.mk_monster_raw = build_player, build_monster
        self.spy = F.SpyText(F._content_text_table())

    # ---- 造物 ----
    def player(self, uid="p1", name="探针", level=8, hp=900, cls="cls_kiln"):
        a = self.mk_player_raw(cls, uid, name, level=level)
        self.apply(a)
        a["max_hp"] = a["hp"] = int(hp)
        return a

    def mob(self, key="rustmite", uid="e1", hp=2000, **fields):
        e = self.mk_monster_raw(key, uid)
        self.apply(e)
        if hp:
            e["max_hp"] = e["hp"] = int(hp)
        for k, v in fields.items():
            e[k] = v
        return e

    def stat(self, actor, key, value):
        """写**面板词条**（引擎 `stats.actor_stats` 会把它并进承伤/吸血那一路）。"""
        actor.setdefault("stats", {})[key] = value
        return actor

    def state(self, actor, key, value):
        actor.setdefault("effects", {})[key] = ({"stacks": int(value)}
                                                if isinstance(value, int) else dict(value))
        return actor

    def battle(self, players, enemies):
        return self.Battle(btype="monster",
                           sides={"player": list(players), "enemy": list(enemies)},
                           text=self.spy)

    def out(self, lines):
        """把某条路的输出接进 spy 账（引擎把行 append 进传入的 list）。"""
        return lines if lines is not None else []

    # ---- 账 ----
    def hit(self, key) -> bool:
        return bool((self.spy.counts or {}).get(key))


DRIVERS = {}


def driver(key):
    def _wrap(fn):
        DRIVERS[key] = fn
        return fn
    return _wrap


# ============================================================
# 逐条驱动（15 条）
# ============================================================

@driver("battle.landing.block_reduce")
def _d_block_reduce(rig):
    """引擎发射点：`landing._apply_taken_reductions` 里 `block` 词条命中的那一支
    （`landing.py` 的 `_cue(battle, logs, "battle.landing.block_reduce", …)`）。

    条件 = `dmg_kind` 非真伤 · 承伤者 `block` 词条 > 0 · `random.random() < cap`（随机）。
    `block` 读的是**顶层字段**（`stats._monster_base_stats` 走 `actor.get("block", 0)`）——
    不是 `actor["stats"]` 那个容器（踩过一次）。拉满 + 多试几次保证命中；
    顺带把 `dodge` 拉 0，免得闪避把这一手吞掉。
    概率上限 `block.cap` 来自内容侧骨架表（示例包没声明 ⇒ 默认 0 ⇒ 永不格挡）⇒ 临时补上。
    """
    undo = _with_skeleton(rig, {"block": {"cap": 0.5, "reduce": 0.5}})
    try:
        logs = []
        for _ in range(40):
            p = rig.mob(key="rustmite", uid="p1")        # 攻击者也用怪：闪避/命中都好控
            p["dodge"] = 0.0
            e = rig.mob(hp=5000)
            e["block"] = 1.0
            bt = rig.battle([p], [e])
            rig.LAND.deal_damage(bt, bt.find_actor("p1"), bt.find_actor("e1"), 30, logs,
                                 dmg_kind="phys")
            if rig.hit("battle.landing.block_reduce"):
                return
    finally:
        undo()


@driver("battle.landing.woken")
def _d_woken(rig):
    """引擎发射点：`landing.deal_damage` 的「受击打醒」段（读 `EFFECT_RULES[key].wake_on_hit`）。

    条件 = 承伤者身上有一个**规则里声明了 `wake_on_hit: true`** 的状态。
    示例包没有睡眠类机制 ⇒ 进程内往效果规则表里补一条探针规则（用完还原，不动数据文件）。
    """
    from ext_combat.battle import state_effects as SE
    tbl = SE.get_effect_rules()
    tbl["probe_wake"] = {"wake_on_hit": True}
    try:
        p = rig.stat(rig.player(), "dodge", 0.0)
        e = rig.state(rig.mob(hp=900), "probe_wake", 1)
        bt = rig.battle([p], [e])
        rig.LAND.deal_damage(bt, p, e, 12, [], dmg_kind="phys")
    finally:
        tbl.pop("probe_wake", None)


@driver("battle.landing.heal_forbid")
def _d_heal_forbid(rig):
    """引擎发射点：`landing.heal_actor` 的禁疗段（`heal_down` 层 × 每层比例 → cap）。"""
    p = rig.player(hp=900)
    t = rig.state(rig.player(uid="p2", name="靶"), "heal_down", 3)
    bt = rig.battle([p, t], [rig.mob()])
    rig.LAND.heal_actor(bt, t, 100, [])


@driver("battle.landing.heal_wound")
def _d_heal_wound(rig):
    """引擎发射点：`landing.heal_actor` 的重伤段（`_anti_heal_pct` 内嵌 `value.pct` → cap）。"""
    p = rig.player(hp=900)
    t = rig.state(rig.player(uid="p2", name="靶"), "_anti_heal_pct", {"value": {"pct": 0.5}})
    bt = rig.battle([p, t], [rig.mob()])
    rig.LAND.heal_actor(bt, t, 100, [])


@driver("battle.landing.taken_reduce")
def _d_taken_reduce(rig):
    """引擎发射点：`landing.deal_damage` 的**承伤减免读点**（`state_reduce_of` 那一段，
    收口第 2 批新增：原先这一族只有写、没有读）。

    条件 = 承伤者身上有一条**规则里声明了 `taken_pct: true`** 的条目 + 内容侧骨架表
    声明了 `reduce.cap`（示例包没声明 ⇒ 中性 0.0 ⇒ 封到 0 = 不减伤）⇒ 两处都要补。
    补的是**输入声明**（效果规则 + 公式骨架），发射点仍是 `landing` 里的真代码。
    """
    from ext_combat.battle import state_effects as SE
    tbl = SE.get_effect_rules()
    tbl["probe_ward"] = {"taken_pct": True}
    undo = _with_skeleton(rig, {"reduce": {"cap": 0.9}})
    try:
        p = rig.stat(rig.player(), "dodge", 0.0)
        t = rig.state(rig.mob(hp=900), "probe_ward", {"value": 0.30, "expire": 999999.0})
        bt = rig.battle([p], [t])
        rig.LAND.deal_damage(bt, p, t, 100, [], dmg_kind="phys")
    finally:
        undo()
        tbl.pop("probe_ward", None)


@driver("battle.landing.taken_mult_skipped")
def _d_taken_mult_skipped(rig):
    """引擎发射点：`landing._skip_event_mult`（承伤减免**两条通道互斥**那一支）。

    条件 = 承伤者身上**同时**有 ① 一条声明了 `taken_pct` 的容器条目（通道 A · 声明）
    与 ② 一条 `taken_calc` 事件乘区把 `_fire_ctx["mult"]` 改成 ≠1.0（通道 B · 事件）
    ⇒ 乘区被**跳过**，改发这一条 cue（说清走了哪条、弃了哪条）。

    补的是**内容侧本该有的两类声明**（效果规则 + 公式骨架封顶 + 乘区动作），
    发射点仍是 `landing` 里的真代码；`taken_calc` 仍**照常 fire**（只有 `mult` 被弃），
    这一点由 `tests/test_taken_channel_exclusive.py` 另钉（那里挂了一个读 `dmg` 的旁证动作）。
    """
    from ext_combat.battle import effects as EFF
    from ext_combat.battle import state_effects as SE
    tbl = SE.get_effect_rules()
    tbl["probe_ward"] = {"taken_pct": True}
    undo = _with_skeleton(rig, {"reduce": {"cap": 0.9}})

    @EFF.register_action("probe_taken_mult")
    def _probe_taken_mult(battle, caster, target, params, logs):
        """内容侧**乘区动作**（同奥兰迪亚 `we_taken_mult_cond` 的形状）：改 ctx["mult"]。"""
        ctx = getattr(battle, "_fire_ctx", None)
        if isinstance(ctx, dict):
            ctx["mult"] = 0.5          # 通道 B：事件乘区 0.5（= 减伤 50%）

    try:
        p = rig.stat(rig.player(), "dodge", 0.0)
        t = rig.state(rig.mob(hp=900), "probe_ward", {"value": 0.30, "expire": 999999.0})
        t.setdefault("triggers", {})["taken_calc"] = [
            {"action": "probe_taken_mult"}]
        bt = rig.battle([p], [t])
        rig.LAND.deal_damage(bt, p, t, 100, [], dmg_kind="phys")
    finally:
        EFF.ACTION_HANDLERS.pop("probe_taken_mult", None)
        undo()
        tbl.pop("probe_ward", None)


@driver("battle.actions.no_target")
def _d_no_target(rig):
    """引擎发射点：`actions` 里「没有可攻击目标」那一支（**返回值式**：`return [...]`）。

    条件 = 出手时敌侧一个活人都没有 ⇒ 先把唯一敌人做掉，再出手。
    """
    p = rig.player()
    e = rig.mob(hp=1)
    bt = rig.battle([p], [e])
    rig.LAND.deal_damage(bt, p, e, 999, [], dmg_kind="phys")
    got, _ended, _who = bt.human_act("attack", None, actor=bt.find_actor("p1"))
    rig.out(got)


@driver("battle.actions.lifesteal")
def _d_lifesteal(rig):
    """引擎发射点：`actions._settle_lifesteal`（面板 `lifesteal` 词条 → 回血那一支）。

    ★ 示例包的面板里没有 `lifesteal` 这个词条（内容侧没声明）⇒ 本驱动**只补输入**：
    临时把 `stats.actor_stats` 包一层，给攻击者补上 `lifesteal=0.5`；其余路径（`_settle_lifesteal`
    自己算率、`landing.heal_actor` 落地、发 cue）全是引擎真代码。用完还原。
    （不许直接发 cue —— 这里补的是**内容侧本该给的输入**，不是那一行。）
    """
    from ext_combat.battle import stats as S
    orig = S.actor_stats

    def _patched(battle, actor):
        st = dict(orig(battle, actor))
        if actor is not None and actor.get("uid") == "p1":
            st["lifesteal"] = 0.5
        return st

    S.actor_stats = _patched
    try:
        p = rig.player(hp=900)
        p["hp"] = 300
        e = rig.mob(hp=2000)
        bt = rig.battle([p], [e])
        rig.A._settle_lifesteal(bt, bt.find_actor("p1"), 120, "phys", [])
    finally:
        S.actor_stats = orig


@driver("battle.actions.enchant_followup")
def _d_enchant_followup(rig):
    """引擎发射点：`actions._single_target_pipeline` 尾部「出手附伤」段（`hit.bonus_atk_pct` > 0）。

    条件 = 出手者身上有一个带 `hit` 子键的消费型效果（`bonus_atk_pct` + `bonus_tag`）。
    ★ 走的是**单目标完整伤害管线**（`_deal_hit` 只是它的薄包装，消费型 buff 在管线里读）。
    """
    p = rig.player()
    rig.state(p, "probe_hit", {"stacks": 1, "hit": {"bonus_atk_pct": 0.5, "bonus_tag": "⚡"}})
    e = rig.mob(hp=5000)
    e["dodge"] = 0.0
    bt = rig.battle([p], [e])
    info = {"name": "探针一击", "exprs": ["atk*0.05"]}
    rig.A._single_target_pipeline(bt, bt.find_actor("p1"), bt.find_actor("e1"), info, 1)


def _heal_skill(rig, leftover: int):
    """把 `_do_heal` 这条真实治疗路跑一遍：target 血量 = max - leftover（决定满额/不足）。"""
    from ext_combat.battle.actors import ActCtx
    p = rig.player(hp=900)
    t = rig.player(uid="p2", name="靶", hp=900)
    t["hp"] = max(1, int(t["max_hp"]) - int(leftover))
    bt = rig.battle([p, t], [rig.mob()])
    info = {"name": "探针治疗", "hp_pct": 0.6}
    ctx = ActCtx(caster=p, action="skill", skill_name="探针治疗", info=info, target=t)
    rig.A._do_heal(bt, ctx, p, info, [])


@driver("battle.actions.skill_heal_full")
def _d_skill_heal_full(rig):
    """引擎发射点：`actions._do_heal` 结尾「满额治疗」那一支（`_real >= heal` ⇒ full）。"""
    _heal_skill(rig, leftover=880)      # 缺口 880 > 治疗量（≈540）⇒ 一定满额


@driver("battle.actions.skill_heal")
def _d_skill_heal(rig):
    """引擎发射点：`actions._do_heal` 结尾「治疗被 clamp」那一支（`_real < heal`）。"""
    _heal_skill(rig, leftover=1)        # 只差 1 点血 ⇒ 治疗量被 clamp 到 1 < heal


@driver("battle.actions.skill_cast")
def _d_skill_cast(rig):
    """引擎发射点：`actions._do_buff` 结尾那句 `skill_cast`（增益技能落地后）。"""
    from ext_combat.battle.actors import ActCtx
    p = rig.player()
    bt = rig.battle([p], [rig.mob()])
    info = {"name": "探针增益"}
    ctx = ActCtx(caster=p, action="skill", skill_name="探针增益", info=info, target=p)
    rig.A._do_buff(bt, ctx, p, info, [])


# ---- gauge（5 条）----
#  条侧要一个 `ENEMY_BAR_CFG` 声明（示例包没声明）⇒ 进程内把 `mech_cfg_fn` 包一层，
#  只加一条探针条；用完还原。驱动走的是 gauge 自己的公开函数 / 注册动作（不是直接发 cue）。

_BAR = {
    "name": "探针条",
    "max": 100,
    "threshold_base": 10,
    "threshold_inc": 1.5,
    "trigger_effect": "skip_turn",
    "phase_preserve_pct": 50,
    "reflect_pct": 0.5,
    "decay_per_turn": 0,
}


def _with_bar(rig):
    """装探针条配置 → 返回还原函数。"""
    from saintess_engine import config as CFG
    prev = CFG.optional_hook("mech_cfg_fn")

    def _mc(name):
        if name == "enemy_bar":
            return {"probe": dict(_BAR)}
        return (prev or (lambda _n: {}))(name)

    CFG.mount(mech_cfg_fn=_mc)
    return lambda: (CFG.mount(mech_cfg_fn=prev) if prev is not None
                    else CFG.set_hook("mech_cfg_fn", None))


def _with_skeleton(rig, patch: dict):
    """把**公式骨架**里缺的那几格临时补上（内容侧本该声明的东西）→ 返回还原函数。

    示例包的骨架表是"最小可跑"那一档：`block.cap` 之类没声明 ⇒ 引擎按中性值 0 走
    （`_skel_sub_num(..., 0.0)`），于是「格挡」那条路永远不亮。补的是**输入声明**，
    不是那行 cue（发射点仍是 `landing` 里的真代码）。
    """
    import copy
    from saintess_engine import config as CFG
    from ext_combat.battle import formulas as _F
    prev = CFG.optional_hook("formula_skeleton_fn")
    base = copy.deepcopy(dict(prev() if prev else (_F._skeleton() or {})))
    for _k, _v in patch.items():
        if isinstance(_v, dict):
            _grp = base.get(_k)
            _grp = dict(_grp) if isinstance(_grp, dict) else {}
            _grp.update(_v)
            base[_k] = _grp
        else:
            base[_k] = _v
    CFG.mount(formula_skeleton_fn=lambda: base)
    return lambda: (CFG.mount(formula_skeleton_fn=prev) if prev is not None
                    else CFG.set_hook("formula_skeleton_fn", None))


@driver("battle.gauge.gain")
def _d_gauge_gain(rig):
    """引擎发射点：`gauge.bar_gain`（模块级，B4 起第一个参数 = 战斗本体）。"""
    from ext_combat import gauge as G
    undo = _with_bar(rig)
    try:
        p = rig.player()
        e = rig.mob(hp=900)
        bt = rig.battle([p], [e])
        G.bar_gain(bt, bt.find_actor("e1"), "probe", 12, [], now=0.0)
    finally:
        undo()


@driver("battle.gauge.trigger")
def _d_gauge_trigger(rig):
    """引擎发射点：`gauge.bar_trigger`（过阈值 → 触发行）。"""
    from ext_combat import gauge as G
    undo = _with_bar(rig)
    try:
        p = rig.player()
        e = rig.mob(hp=900)
        bt = rig.battle([p], [e])
        host = bt.find_actor("e1")
        G.bar_gain(bt, host, "probe", 50, [], now=0.0)      # 先积到阈值之上
        G.bar_trigger(bt, host, "probe", [], now=0.0)
        G.bar_trigger(bt, host, "probe", [], now=0.0)
    finally:
        undo()


@driver("battle.gauge.shaken")
def _d_gauge_shaken(rig):
    """引擎发射点：`gauge.actions._settle` 的 `trigger_effect == "skip_turn"` 那一支
    （受控行 = `battle.gauge.shaken`）。走注册动作 `bar_time_settle_act`（真消费端）。"""
    from ext_combat import gauge as G
    undo = _with_bar(rig)
    try:
        p = rig.player()
        e = rig.mob(hp=900)
        bt = rig.battle([p], [e])
        host = bt.find_actor("e1")
        G.bar_gain(bt, host, "probe", 50, [], now=0.0)
        G.actions.bar_time_settle_act(bt, host, None, {"key": "probe"}, [])
    finally:
        undo()


@driver("battle.gauge.phase_preserve")
def _d_gauge_phase_preserve(rig):
    """引擎发射点：`gauge.actions.bar_phase_preserve_act` 的阶段更迭那一支。"""
    from ext_combat import gauge as G
    undo = _with_bar(rig)
    try:
        p = rig.player()
        e = rig.mob(hp=900)
        bt = rig.battle([p], [e])
        host = bt.find_actor("e1")
        G.bar_gain(bt, host, "probe", 40, [], now=0.0)
        G.actions.bar_phase_preserve_act(bt, None, None, {"_owner": host}, [])
    finally:
        undo()


@driver("battle.gauge.reflect")
def _d_gauge_reflect(rig):
    """引擎发射点：`gauge.actions.passive_reflect_bar_act`（受击反制 → 反弹行 + 反推条）。

    反弹比例来自 **params `reflect_pct`**（不是条配置里的键 —— 踩过一次），
    攻击者从 `battle._fire_ctx["source"]` 取。
    """
    from ext_combat import gauge as G
    undo = _with_bar(rig)
    try:
        p = rig.player()
        e = rig.mob(hp=900)
        bt = rig.battle([p], [e])
        dfd = bt.find_actor("e1")
        atk = bt.find_actor("p1")
        bt._fire_ctx = {"source": atk, "dmg": 40, "target": dfd}
        G.actions.passive_reflect_bar_act(
            bt, None, dfd, {"_owner": dfd, "reflect_pct": 0.5, "key": "probe", "gain": 3}, [])
    finally:
        undo()


#: ★ 够不着的登记表（与阿斯特兰包 `probe_elements ⑨-4` 同款口径）：
#:   逐条写清「为什么本工具打不到」；登记了却驱动到了 ⇒ 也红（两态互锁）。
NEED_DRIVE: dict = {}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="cue 覆盖尺（设计 §3.2③）")
    ap.add_argument("--tree", default=os.path.dirname(HERE),
                    help="代码树（默认 = 本工具的上一级目录）")
    ap.add_argument("--json", default=None, help="结果 JSON 落档路径")
    args = ap.parse_args(argv)

    tree = os.path.abspath(args.tree)
    print("cue 覆盖尺 —— 冻结 5 组打不到的，逐条补驱动")
    print("树：%s" % tree)

    base = F.collect(tree, "none")
    rig = Rig(tree)
    inv = base["key_inventory"]
    names = sorted(rig.names)                     # 声明面 = 引擎 `CUE_NAMES`（见 Rig 里的说明）
    covered = set(base["observed_keys"])
    todo = [k for k in names if k not in covered]
    print("引擎声明 %d 条 cue；冻结 5 组已覆盖 %d 条；待补 %d 条"
          % (len(names), len(covered), len(todo)))

    got = {}
    for k in todo:
        fn = DRIVERS.get(k)
        if fn is None:
            continue
        before = set(rig.spy.counts or {})
        try:
            fn(rig)
        except Exception as exc:                     # noqa: BLE001 —— 驱动失败要说清楚是哪一条
            print("%s✗ %s 驱动抛异常：%s: %s" % (MISS, k, type(exc).__name__, exc))
            continue
        if rig.hit(k):
            got[k] = fn.__doc__.strip().splitlines()[0]
    undriven = [k for k in todo if k not in got]

    print()
    print("── 补驱动结果 ──")
    for k in todo:
        print("%s%s %s%s" % ("  ", "✅" if k in got else "·", k,
                             "" if k in got else "  （见登记表）"))
    print()
    reg_bad = sorted(set(undriven) ^ set(NEED_DRIVE))
    ok = (not reg_bad) and (not [k for k in NEED_DRIVE if k in got])
    print("冻结 5 组 %d + 本工具 %d + 登记 %d = %d / 声明 %d"
          % (len(covered), len(got), len(NEED_DRIVE),
             len(covered) + len(got) + len(NEED_DRIVE), len(names)))
    print("登记表差集（登记了没驱动到 / 驱动到了没登记）：%s" % (reg_bad or "无"))
    print("结果：%s" % ("全覆盖 ✓" if ok and len(covered) + len(got) + len(NEED_DRIVE) == len(names)
                        else "有缺口 ✗"))

    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"tree": tree, "tree_head": base.get("tree_head"),
                       "declared": names, "frozen_covered": sorted(covered),
                       "extra_covered": {k: got[k] for k in sorted(got)},
                       "need_drive": NEED_DRIVE, "undriven": undriven,
                       "union": sorted(covered | set(got) | set(NEED_DRIVE))},
                      f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
        print("json → %s" % args.json)
    return 0 if (ok and len(covered) + len(got) + len(NEED_DRIVE) == len(names)) else 1


if __name__ == "__main__":
    sys.exit(main())
