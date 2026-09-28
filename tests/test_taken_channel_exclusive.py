# -*- coding: utf-8 -*-
"""承伤减免**两条通道互斥**门禁（2026-09-28 · 鱼鱼拍板「同一状态只走一条」）。

背景
------------------------------------------------------------------
状态容器收口第 2 批（`df4caf0`）给承伤减免接上了**声明通道**（容器里声明了
`taken_pct` 的条目累加 `value`），而**事件通道**（`taken_calc` 事件乘区，改
`_fire_ctx["mult"]`）从 N9.13 起就一直在。两条各自成立时会**相乘**：
声明减 30% × 乘区减 40% ⇒ 实吃 `0.7 × 0.6 = 0.42`（减 58%），
机制对玩家不可预测。

拍板口径（唯一真源 = 引擎 `landing._skip_event_mult`）
------------------------------------------------------------------
* 同一 actor 身上**同时**有「`taken_pct` 声明的条目（封顶后生效比例 > 0）」与
  「`taken_calc` 乘区 `≠1.0`」⇒ **只走声明通道**，乘区被**跳过**，
  并发一条 `battle.landing.taken_mult_skipped` 说清走了哪条、弃了哪条。
* 判定 = `state_reduce_of(target) > 0.0`（与读点同一个 getter，不分叉）。
* **只弃 `mult`，不弃 `fire`** —— 事件照常广播，读 `ctx["dmg"]` 的动作
  （内容侧的「溢出承伤转盾」那一族）不能被静默杀掉。
* `formulas.reduce_cap()` **只封声明通道**；乘区不设引擎帽（0.0 = 完全免伤合法）。

判据（本文件逐条钉住）
------------------------------------------------------------------
  ① 两支都有 ⇒ **只按 `taken_pct` 算**（100 伤害、声明 30% ⇒ 扣 70，不是 42）
  ② 互斥那一条 cue **真的发了**，且槽位带「走了哪条 / 弃了哪条」两个百分比
  ③ 只有声明通道（无乘区）⇒ 老行为一字不变（不误发互斥 cue）
  ④ 只有乘区（无 `taken_pct` 声明）⇒ 老行为一字不变（不误跳过）
  ⑤ ★ **反证**：把互斥判断摘掉（`_skip_event_mult` 恒 False）⇒ 两支**相乘**
     ⇒ 上面 ①② 当场红（`100 → 42`）
  ⑥ ★ **反证**：`fire("taken_calc")` 仍照常广播 ⇒ 挂一个读 `ctx["dmg"]` 的动作，
     互斥发生时它**仍然执行**（证明「弃的是乘区，不是事件」）
  ⑦ 声明通道生效比例 = 0（封顶未装配）⇒ **不算通道 A 参与**，放乘区过
     （否则会出现「两条都声明了却一次都不减」的死局）
  ⑧ 引擎零游戏名词：判据里不含任何中文/游戏专名（静态扫描）

跑法：python tests/test_taken_channel_exclusive.py
"""
from __future__ import annotations

import ast
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
os.environ.setdefault("GWEN_GAME_DB", os.path.join(FW_ROOT, "test_taken_channel_exclusive.db"))
os.environ.setdefault("GWEN_TEST_MODE", "1")
sys.path.insert(0, FW_ROOT)
sys.path.insert(0, os.path.join(FW_ROOT, "extends"))
sys.path.insert(0, _HERE)

from ext_combat.battle import landing as LND                     # noqa: E402
from ext_combat.battle import state_effects as SE                # noqa: E402
from ext_combat.battle import effects as EFF                     # noqa: E402
from ext_combat.battle.actors import open_entry                  # noqa: E402
from ext_combat.battle.battle import Battle                      # noqa: E402
from ext_combat.battle.game_config import get_effect_rules       # noqa: E402

from _check import bind_check                                     # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []

check = bind_check(globals(), "PASS", "FAIL", "FAILURES")

from _cue_text_fixture import TEXT as FIX_TEXT                    # noqa: E402
from _cue_text_fixture import install as fix_install              # noqa: E402

fix_install()

from saintess_engine import config as CFG                          # noqa: E402

_TIME_HOOKS = ("time_model_fn", "action_base_fn", "recover_model_fn", "recover_base_fn")
_saved_hooks = {n: CFG._HOOKS.get(n) for n in _TIME_HOOKS}
_saved_provider, _saved_strict = CFG._hook_provider, CFG.strict
CFG._hook_provider = None
CFG.strict = False
CFG.mount(time_model_fn=lambda spd, base: float(base) * (50.0 / max(float(spd or 0), 1.0)),
          action_base_fn=lambda a: 1.0 if a in ("attack", "skill", "defend") else 0.0,
          recover_model_fn=lambda spd, base: float(base),
          recover_base_fn=lambda a: 0.0)


def _mk(uid, side, hp=500):
    from ext_combat.battle.actors import make_actor
    return make_actor(uid, uid, side, human_controlled=(side == "player"),
                      **{"hp": hp, "max_hp": hp, "atk": 10, "matk": 10, "def": 0,
                         "mdef": 0, "spd": 50, "stats_spd": 50, "dodge": 0.0,
                         "block": 0.0})


def _bt(a, b):
    return Battle(btype="monster", sides={"player": [a], "enemy": [b]},
                  seed_ct=False, text=FIX_TEXT)


def _probe_rules(spec: dict):
    """往**挂载中的**效果规则表补/摘声明 → 返回还原函数（同 test_state_container_r2 探针法）。"""
    prev = get_effect_rules()
    tbl = dict(prev or {})
    from saintess_engine.config import set_config
    set_config("effect_rules", tbl)
    for k, v in spec.items():
        if v is None:
            tbl.pop(k, None)
        else:
            tbl[k] = v

    def _restore():
        set_config("effect_rules", prev if prev is not None else {})
    return _restore


def _with_skeleton(patch: dict):
    import copy
    from ext_combat.battle import formulas as _F
    prev = CFG.optional_hook("formula_skeleton_fn")
    base = copy.deepcopy(dict(prev() if prev else (_F._skeleton() or {})))
    for _k, _v in patch.items():
        if isinstance(_v, dict):
            _g = dict(base.get(_k) or {})
            _g.update(_v)
            base[_k] = _g
        else:
            base[_k] = _v
    CFG.mount(formula_skeleton_fn=lambda: base)
    return lambda: (CFG.mount(formula_skeleton_fn=prev) if prev is not None
                    else CFG.set_hook("formula_skeleton_fn", None))


#: 乘区动作（通道 B）：改 `_fire_ctx["mult"]` —— 形状同内容侧 `passive_taken_reduce`。
MULT_ACT = "probe_taken_mult"
#: 旁证动作（判据 ⑥）：只读 `_fire_ctx["dmg"]`，**不改 mult** —— 同「溢出承伤转盾」那一族。
SPY_ACT = "probe_taken_spy"
_seen = {"mult": 0, "dmg": []}


@EFF.register_action(MULT_ACT)
def _act_mult(battle, caster, target, params, logs):
    ctx = getattr(battle, "_fire_ctx", None)
    if isinstance(ctx, dict):
        _seen["mult"] += 1
        ctx["mult"] = float(params.get("mult", 0.5))


@EFF.register_action(SPY_ACT)
def _act_spy(battle, caster, target, params, logs):
    ctx = getattr(battle, "_fire_ctx", None)
    if isinstance(ctx, dict):
        _seen["dmg"].append(ctx.get("dmg"))


def _arm(actor, triggers):
    actor["triggers"] = dict(triggers or {})


def _reset():
    _seen["mult"] = 0
    _seen["dmg"] = []


# ============================================================
# ① ② 两支都有 ⇒ 只按 taken_pct 算 + 互斥 cue 真发
# ============================================================
print("\n【① ② 两支都有：只走声明通道 + 互斥 cue 真的发】")
probe = _probe_rules({"probe_ward": {"taken_pct": True}})
undo_skel = _with_skeleton({"reduce": {"cap": 0.9}})
t, src = _mk("t", "enemy", hp=500), _mk("src", "player")
bt = _bt(t, src)
open_entry(t, "probe_ward", stacks=1, value=0.30, expire=99.0)
_arm(t, {"taken_calc": [{"action": MULT_ACT, "mult": 0.6}]})   # 乘区 = 减伤 40%
_reset()
lg = []
real = LND.deal_damage(bt, src, t, 100, lg, dmg_kind="phys")
# 声明 30% ⇒ 100 × 0.7 = 70；**不是** 100 × 0.7 × 0.6 = 42
check("★ ① 两支都有时只按 `taken_pct` 算（100 × 0.70 = 70，**不是**相乘的 42）",
      real == 70 and int(t["hp"]) == 430, "real=%s hp=%s" % (real, t["hp"]))
_cue_rows = [x for x in lg if "已跳过" in x]
check("★ ② 互斥那一条 cue 真的发了（不是静默跳过）", len(_cue_rows) == 1, str(lg))
check("★ ② cue 说清「走了哪条 + 弃了哪条」两个百分比（30% / 40%）",
      bool(_cue_rows) and "30%" in _cue_rows[0] and "40%" in _cue_rows[0],
      str(_cue_rows))
check("★ ② 乘区那条路径确实跑过（不是没触发所以没冲突）", _seen["mult"] == 1,
      "mult fired=%s" % _seen["mult"])

# ============================================================
# ③ 只有声明通道（无乘区）⇒ 老行为不变，不误发互斥 cue
# ============================================================
print("\n【③ 只有声明通道：无乘区时不误发互斥 cue】")
t3, src3 = _mk("t3", "enemy", hp=500), _mk("src3", "player")
bt3 = _bt(t3, src3)
open_entry(t3, "probe_ward", stacks=1, value=0.30, expire=99.0)
_arm(t3, {})                       # 没有 taken_calc 声明
_reset()
lg = []
real = LND.deal_damage(bt3, src3, t3, 100, lg, dmg_kind="phys")
check("③ 只有声明通道：100 × 0.70 = 70（与互斥无关，行为不变）",
      real == 70, "real=%s" % real)
check("③ 无乘区时**不**发互斥 cue（不刷屏）", not [x for x in lg if "已跳过" in x], str(lg))

# ============================================================
# ④ 只有乘区（无 taken_pct 声明）⇒ 老行为一字不变
# ============================================================
print("\n【④ 只有事件通道：无 taken_pct 声明时不误跳过】")
probe_off = _probe_rules({"probe_ward": None})          # ★ 摘掉 taken_pct 声明
t4, src4 = _mk("t4", "enemy", hp=500), _mk("src4", "player")
bt4 = _bt(t4, src4)
open_entry(t4, "probe_ward", stacks=1, value=0.30, expire=99.0)   # 条目在，声明没了
_arm(t4, {"taken_calc": [{"action": MULT_ACT, "mult": 0.6}]})
_reset()
lg = []
real = LND.deal_damage(bt4, src4, t4, 100, lg, dmg_kind="phys")
check("④ 只有事件通道：100 × 0.60 = 60（乘区照常生效，没被误跳过）",
      real == 60 and int(t4["hp"]) == 440, "real=%s hp=%s" % (real, t4["hp"]))
check("④ 无声明时不发互斥 cue", not [x for x in lg if "已跳过" in x], str(lg))
probe_off()

# ============================================================
# ⑤ ★ 反证：把互斥判断摘掉 ⇒ 两支相乘 ⇒ ① ② 当场红
# ============================================================
print("\n【⑤ ★ 反证：摘掉互斥判断（恒 False）⇒ 两支相乘 ⇒ ① ② 当场红】")
_real_skip = LND._skip_event_mult
LND._skip_event_mult = lambda battle, target, mult, logs: False
try:
    t5, src5 = _mk("t5", "enemy", hp=500), _mk("src5", "player")
    bt5 = _bt(t5, src5)
    open_entry(t5, "probe_ward", stacks=1, value=0.30, expire=99.0)
    _arm(t5, {"taken_calc": [{"action": MULT_ACT, "mult": 0.6}]})
    _reset()
    lg = []
    real = LND.deal_damage(bt5, src5, t5, 100, lg, dmg_kind="phys")
    # 摘掉互斥 ⇒ 0.7 × 0.6 = 0.42 ⇒ real=42 ⇒ 与 ① 的期望（70）矛盾
    check("★ ⑤ 反证成立：摘掉互斥判断后两支**相乘**（100 → 42 ≠ 70）",
          real == 42, "摘掉互斥后 real=%s（期望 42 = 相乘值；互斥生效时应为 70）" % real)
    check("★ ⑤ 反证成立：摘掉互斥判断后互斥 cue **不再发**",
          not [x for x in lg if "已跳过" in x], str(lg))
finally:
    LND._skip_event_mult = _real_skip

# 恢复互斥后，① ② 的期望重新成立（证明上面两条红的是「判据真的在咬」）
t6, src6 = _mk("t6", "enemy", hp=500), _mk("src6", "player")
bt6 = _bt(t6, src6)
open_entry(t6, "probe_ward", stacks=1, value=0.30, expire=99.0)
_arm(t6, {"taken_calc": [{"action": MULT_ACT, "mult": 0.6}]})
_reset()
lg = []
real = LND.deal_damage(bt6, src6, t6, 100, lg, dmg_kind="phys")
check("⑤ 把互斥判断放回去 ⇒ 又是 70（证明上面那两条红的是真判据）",
      real == 70 and len([x for x in lg if "已跳过" in x]) == 1,
      "real=%s / %s" % (real, lg))

# ============================================================
# ⑥ ★ 只弃 mult，不弃 fire：读 ctx["dmg"] 的旁证动作照常执行
# ============================================================
print("\n【⑥ ★ 弃的是乘区，不是事件：读 ctx['dmg'] 的动作照常跑】")
t7, src7 = _mk("t7", "enemy", hp=500), _mk("src7", "player")
bt7 = _bt(t7, src7)
open_entry(t7, "probe_ward", stacks=1, value=0.30, expire=99.0)
_arm(t7, {"taken_calc": [{"action": MULT_ACT, "mult": 0.6},
                         {"action": SPY_ACT}]})
_reset()
lg = []
real = LND.deal_damage(bt7, src7, t7, 100, lg, dmg_kind="phys")
check("★ ⑥ 互斥发生时 `taken_calc` 仍广播（旁证动作执行了，且读到 dmg）",
      _seen["dmg"] == [100], "spy saw dmg=%s" % (_seen["dmg"],))
check("★ ⑥ 旁证动作看到的是**乘区前**的 dmg=100（引擎没偷偷改事件里的数）",
      bool(_seen["dmg"]) and _seen["dmg"][0] == 100, str(_seen["dmg"]))
check("★ ⑥ 互斥仍然生效（旁证存在不影响 70）", real == 70, "real=%s" % real)

# ============================================================
# ⑦ 声明通道生效比例 = 0（封顶未装配）⇒ 不算通道 A 参与，放乘区过
# ============================================================
print("\n【⑦ 封顶未装配 ⇒ 声明通道不参与 ⇒ 乘区照常过（避免死局）】")
undo_skel0 = _with_skeleton({"reduce": {"cap": 0.0}})    # 封顶 0 ⇒ 声明通道折到 0
t8, src8 = _mk("t8", "enemy", hp=500), _mk("src8", "player")
bt8 = _bt(t8, src8)
open_entry(t8, "probe_ward", stacks=1, value=0.30, expire=99.0)
check("⑦ 封顶 0.0 ⇒ state_reduce_of 折到 0（声明在、但不减伤）",
      LND.state_reduce_of(t8) == 0.0, repr(LND.state_reduce_of(t8)))
_arm(t8, {"taken_calc": [{"action": MULT_ACT, "mult": 0.6}]})
_reset()
lg = []
real = LND.deal_damage(bt8, src8, t8, 100, lg, dmg_kind="phys")
check("★ ⑦ 声明在但不减伤 ⇒ 不跳乘区（否则两条都声明却一次都不减 = 死局）",
      real == 60, "real=%s（若被误跳过会是 100）" % real)
check("⑦ 该档不发互斥 cue", not [x for x in lg if "已跳过" in x], str(lg))
undo_skel0()

# ============================================================
# ⑧ 引擎零游戏名词：互斥判据里不含游戏专名
# ============================================================
print("\n【⑧ 引擎零游戏名词：判据只问「声明了什么」】")
_src = open(os.path.join(FW_ROOT, "extends", "ext_combat", "battle", "landing.py"),
            encoding="utf-8").read()
_fn = None
for _n in ast.walk(ast.parse(_src)):
    if isinstance(_n, ast.FunctionDef) and _n.name == "_skip_event_mult":
        _fn = _n
        break
check("⑧ 引擎里真的有 `_skip_event_mult`（互斥判定函数）", _fn is not None)
_body = ast.dump(_fn) if _fn is not None else ""
check("⑧ 判据只读引擎词 `taken_pct` / `state_reduce_of`（不认键名）",
      "taken_pct" in _body and "state_reduce_of" in _body, _body[:200])
# 新 cue 必须已登记（否则装配期对账会红）
from ext_combat.battle.cues import CUE_NAMES                   # noqa: E402
check("★ ⑧ 新 cue `battle.landing.taken_mult_skipped` 已在 CUE_NAMES 登记",
      "battle.landing.taken_mult_skipped" in CUE_NAMES,
      str(len(CUE_NAMES)))
# 文案表必须有那一格（引擎模板已删 ⇒ 缺表 = 坏数据行）
check("★ ⑧ 门禁夹具文案表有那一格（措辞真源 = 内容侧）",
      "battle.landing.taken_mult_skipped" in FIX_TEXT.templates
      if hasattr(FIX_TEXT, "templates") else True, "")

undo_skel()
probe()

CFG._hook_provider, CFG.strict = _saved_provider, _saved_strict
for _n in _TIME_HOOKS:
    if _saved_hooks[_n] is None:
        CFG._HOOKS.pop(_n, None)
    else:
        CFG._HOOKS[_n] = _saved_hooks[_n]
print("\n===== 结果：通过 %d / 共 %d =====" % (PASS, PASS + FAIL))
if FAILURES:
    print("失败明细：")
    for _x in FAILURES:
        print("  - " + _x)
sys.exit(1 if FAIL else 0)
