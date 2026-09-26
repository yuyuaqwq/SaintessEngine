#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：两段耗时（E6）—— 声明四形态 + `segment_plan_fn` 接线 + 射程守卫。

为什么要它（E6 · 2026-09-25）
------------------------------------------------------------------
审计 §五「空形状」：`config._HOOKS` 里的 `segment_plan_fn` **全仓零调用方** ——
它就是「技能自己声明两段耗时（cast / recover）」的接口，`docs/engine-wiki/reference/
skill-dimensions.md` §2 把它写成了技能 7 维的引擎侧落点，但引擎里没人问它。
同批查出两处**更硬的洞**：
  ① `schedule._segment_seconds` 只认 `str` / 数字 —— 文档写明的第三形态
     `{"base": n}`（基准秒，吃速度）会掉进 `float(dict)` 抛 `TypeError`；
  ② `_validators.segment_of` / `layer_of` 两个守卫**写好了却零调用方**（`actions.py` 里
     仍在写 `int(info.get("reach") or 3)`：射程写成 `"near"` ⇒ 裸 `ValueError`，不点名）。
本门禁钉住：四形态都对、坏形状点名现形、`segment_plan_fn` 两态（不配 = 逐字不变）、
射程走守卫。

跑法：`python tests/test_segment_declaration.py`；退出码 0 = 全绿 · 1 = 有失败。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
for _p in (ROOT, os.path.join(ROOT, "extends")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ext_combat import Battle, make_actor                          # noqa: E402
from ext_combat.battle import schedule as SCH                      # noqa: E402
from ext_combat.battle.actors import ActCtx                        # noqa: E402
from saintess_engine import config as CFG                          # noqa: E402
from saintess_engine import _validators as V                       # noqa: E402

passed = failed = 0
DETAIL = []

from _check import bind_check  # noqa: E402

check = bind_check(globals(), "passed", "failed", "DETAIL")

_HOOK_NAMES = ("time_model_fn", "action_base_fn", "recover_model_fn", "recover_base_fn",
               "segment_plan_fn")
_saved = {n: CFG._HOOKS.get(n) for n in _HOOK_NAMES}
_provider, _strict = CFG._hook_provider, CFG.strict

#: 内容侧时间模型（测试自己的）：线性 —— spd=50 时正好 = base（便于算期望值）
_T1 = lambda spd, base: float(base) * (50.0 / max(float(spd or 0), 1.0))       # noqa: E731
_BASE = lambda action: {"attack": 1.0, "skill": 1.5, "defend": 1.0}.get(action, 1.0)  # noqa: E731
_FLAT = lambda spd, base: float(base)                                          # noqa: E731
_RB = lambda action: 0.0                                                       # noqa: E731


def _mount(**kw):
    CFG.mount(time_model_fn=_T1, action_base_fn=_BASE,
              recover_model_fn=_FLAT, recover_base_fn=_RB, **kw)


def _battle(spd=50):
    pa = make_actor("p1", "甲", "player", kind="player", human_controlled=True,
                    hp=100, max_hp=100, atk=20, spd=spd)
    ea = make_actor("e1", "怪", "enemy", kind="monster", hp=500, max_hp=500, atk=10, spd=5)
    return Battle(btype="monster", sides={"player": [pa], "enemy": [ea]},
                  seed_ct=False), pa


def _solo(spd=5):
    """观察用最小场：怪 spd=0（它的第一段被拉到 50 秒，不会插进来）、玩家 spd 低
    ⇒ 玩家的第一段很长，`human_act` 返回时**待发槽还在**（还没到点），可以直接读槽。"""
    pa = make_actor("p1", "甲", "player", kind="player", human_controlled=True,
                    hp=100, max_hp=100, atk=20, spd=spd)
    ea = make_actor("e1", "怪", "enemy", kind="monster", hp=500, max_hp=500, atk=10, spd=0)
    return Battle(btype="monster", sides={"player": [pa], "enemy": [ea]},
                  seed_ct=False), pa


def _raises(fn):
    try:
        fn()
    except BaseException as e:                                     # noqa: BLE001
        return True, e
    return False, None


try:
    CFG._hook_provider = None
    CFG.strict = False

    # ---------------------------------------------------------------- ① 四形态
    print("【1. 一段耗时的四形态（`_segment_seconds` 过 `_validators.segment_of`）】")
    _mount()
    b50, a50 = _battle(50)
    _sec = SCH._segment_seconds
    check("str = 行动类别名 ⇒ 过时间模型", _sec(b50, a50, "skill") == 1.5, repr(_sec(b50, a50, "skill")))
    check("数字 = 绝对秒", _sec(b50, a50, 0.5) == 0.5, repr(_sec(b50, a50, 0.5)))
    check("{\"base\": n} = 基准秒 ⇒ 过时间模型（★ 原先会 float(dict) 抛 TypeError）",
          _sec(b50, a50, {"base": 2.0}) == 2.0, repr(_sec(b50, a50, {"base": 2.0})))
    check("None ⇒ DEFAULT_ACTION 类别",
          _sec(b50, a50, None) == _BASE(SCH.DEFAULT_ACTION), repr(_sec(b50, a50, None)))
    b200, a200 = _battle(200)
    check("★ 基准秒**吃速度**：spd 50→200（4×）⇒ 秒数 ÷4",
          abs(_sec(b200, a200, {"base": 2.0}) - 0.5) < 1e-9, repr(_sec(b200, a200, {"base": 2.0})))
    check("★ 绝对秒**不吃速度**：同 spd 变化下不变",
          _sec(b200, a200, 2.0) == 2.0, repr(_sec(b200, a200, 2.0)))
    for _label, _bad in (("列表", [1]), ("负数", -1), ("空串", ""),
                         ("{\"base\": 字符串}", {"base": "x"}),
                         ("{\"base\":…, 多键}", {"base": 1, "x": 2}),
                         ("缺 base 键", {"base2": 1})):
        _ok, _err = _raises(lambda v=_bad: _sec(b50, a50, v, "技能甲的第一段耗时（cast）"))
        check("坏形状「%s」⇒ 抛且点名 label" % _label,
              _ok and "技能甲的第一段耗时（cast）" in str(_err), "%s: %s" % (type(_err).__name__, _err))

    # ---------------------------------------------------------------- ② 守卫本身有牙
    print("\n【2. `_validators.segment_of` / `layer_of` 直接判（零调用方 → 现在有调用方）】")
    check("segment_of(None) = None（本次不声明）", V.segment_of(None, "x") is None)
    check("segment_of(0) = 0.0（0 也是合法绝对秒）", V.segment_of(0, "x") == 0.0)
    _ok, _err = _raises(lambda: V.segment_of(True, "射程 x"))
    check("bool 不算数值 ⇒ 抛 TypeError", _ok and isinstance(_err, TypeError), repr(_err))
    check("layer_of(3) = 3", V.layer_of(3, "x") == 3)
    check("layer_of(None, default=3) = 3（原 `or 3` 的语义）", V.layer_of(None, "x", default=3) == 3)
    _ok, _err = _raises(lambda: V.layer_of("near", "AOE 技能射程 reach（技能甲）"))
    check("layer_of(\"near\") ⇒ 抛且点名（原先是裸 ValueError，栈里看不出哪条技能）",
          _ok and "技能甲" in str(_err), "%s: %s" % (type(_err).__name__, _err))

    # ---------------------------------------------------------------- ③ segment_plan_fn 两态
    print("\n【3. `segment_plan_fn` 两态：不配 = 不存在（连问都不问）· 配了 = 内建动作也按条目声明】")
    CFG._HOOKS["segment_plan_fn"] = None
    check("不配 ⇒ segment_plan_of 返回 None（落回行动类别基准）",
          SCH.segment_plan_of(b50, a50, "defend", {}) is None)
    _mount(segment_plan_fn=lambda actor, action, entry: None)
    check("配了但回执 None ⇒ 仍 None（内容侧用「这次不声明」表达回落）",
          SCH.segment_plan_of(b50, a50, "defend", {}) is None)
    _mount(segment_plan_fn=lambda actor, action, entry: {})
    check("配了但回执空 dict ⇒ 仍 None", SCH.segment_plan_of(b50, a50, "defend", {}) is None)
    _mount(segment_plan_fn=lambda actor, action, entry: {"cast": {"base": 2.0}, "recover": 0.0})
    _plan = SCH.segment_plan_of(b50, a50, "defend", {})
    check("配了 ⇒ 回执按声明给（并过守卫归一）",
          _plan == {"cast": {"base": 2.0}, "recover": 0.0}, repr(_plan))
    _mount(segment_plan_fn=lambda actor, action, entry: {"cast": [1], "recover": None})
    _ok, _err = _raises(lambda: SCH.segment_plan_of(b50, a50, "defend", {}))
    check("回执里坏形状 ⇒ 抛且点名段位（ASCII 段位标签，便于 grep）",
          _ok and "segment_plan_fn.cast" in str(_err), repr(_err))

    # ---------------------------------------------------------------- ④ 端到端两态
    print("\n【4. 端到端：内建动作 `defend` 的两段耗时（不配 ⇒ 逐字不变）】")
    CFG._HOOKS["segment_plan_fn"] = None
    _mount()
    b1, p1 = _solo()
    _t0 = float(b1._now)
    # 直调 `act()`（T0 快照）：`human_act` 会在 act 之后推进 ct，待发槽可能已被解算掉，
    # 只有 act 直调才能干净读到「登记那一刻」的槽。
    b1.act(ActCtx(caster=p1, action="defend", info={}, target=None))
    s1 = p1.get("charging") or {}
    exp1 = SCH._segment_seconds(b1, p1, "defend")
    got1 = float(s1.get("cast_done_at", -1)) - _t0
    check("T0 之后待发槽已登记（观察前提成立）", bool(s1), repr(s1)[:80])
    check("不配 hook ⇒ 第一段 = 行动类别基准（与旧口径同值）", abs(got1 - exp1) < 1e-9,
          "%r vs %r" % (got1, exp1))
    check("不配 hook ⇒ 第一段声明就是本次行动类别（`cast_base` = \"defend\"）",
          s1.get("cast_base") == "defend", repr(s1.get("cast_base")))
    check("不配 hook ⇒ 第二段不声明（`recover_base` 为 None）", s1.get("recover_base") is None,
          repr(s1.get("recover_base")))
    _mount(segment_plan_fn=lambda actor, action, entry: {"cast": {"base": 2.0}, "recover": 0.0})
    b2, p2 = _solo()
    _t0b = float(b2._now)
    b2.act(ActCtx(caster=p2, action="defend", info={}, target=None))
    s2 = p2.get("charging") or {}
    got2 = float(s2.get("cast_done_at", -1)) - _t0b
    check("配了 hook ⇒ 第一段改成声明的声明值（`cast_base` = {\"base\": 2.0}）",
          s2.get("cast_base") == {"base": 2.0}, repr(s2.get("cast_base")))
    check("★ 两态真的不同（否则就是没接线）", abs(got2 - got1) > 1e-6, "%r vs %r" % (got1, got2))
    check("第二段声明带进待发槽（B 段据此推进 ct）", s2.get("recover_base") == 0.0,
          repr(s2.get("recover_base")))
    check("不配 hook 的那场零诊断", not (getattr(b1, "diagnostics", None) or []), "")

    # ---------------------------------------------------------------- ⑤ 射程守卫接线
    print("\n【5. 射程走守卫：坏形状点名技能（原先是裸 ValueError）】")
    src = open(os.path.join(ROOT, "extends", "ext_combat", "battle", "actions.py"),
               encoding="utf-8").read()
    check("`actions.py` 里旧写法 `attacker = {\"reach\": int(...)}` 整句已消失（注释里提旧写法不算）",
          'attacker = {"reach": int(' not in src)
    check("改走 `_V.layer_of(...)`", "_V.layer_of(info.get(\"reach\")" in src, "")
    b3, a3 = _battle(50)
    from ext_combat.battle import actions as _ACT
    _ok5, _err5 = _raises(lambda: _ACT._deal_aoe(b3, a3, a3,
                                                {"name": "技能甲", "aoe": "all",
                                                 "reach": "near"}, 10))
    check("AOE 结算：reach 写成 \"near\" ⇒ 抛且点名技能（不是裸 ValueError 无上下文）",
          _ok5 and "技能甲" in str(_err5), "%s: %s" % (type(_err5).__name__, _err5))
finally:
    for _n, _v in _saved.items():
        CFG._HOOKS[_n] = _v
    CFG._hook_provider, CFG.strict = _provider, _strict

print("\n【6. 现场恢复】")
check("segment_plan_fn 还原", CFG._HOOKS.get("segment_plan_fn") == _saved["segment_plan_fn"])
check("时间模型四个 hook 还原", all(CFG._HOOKS.get(n) == _saved[n] for n in _HOOK_NAMES[:4]))

print("\n" + "=" * 56)
print("通过 %d · 失败 %d" % (passed, failed))
for _d in DETAIL:
    print("  " + _d)
sys.exit(1 if failed else 0)
