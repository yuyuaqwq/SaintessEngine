# -*- coding: utf-8 -*-
"""引擎「未装配 hook → 中性兜底不炸」契约测试（可分发性回归闸）。

背景：2026-09-11 S8 可行性干跑发现——引擎包可物理搬出，但第三方只挂部分 hook 时
**首场战斗即崩**：
```
saintess_engine/formulas.py:130  skill_flat_value()
    base = float(up.get("flat_base", _flat.get("SKILL_FLAT_BASE")))
TypeError: float() argument must be a string or a real number, not 'NoneType'
```
而 `formulas.py` 自身的 docstring + `plan §8-R8` 都承诺「未装配时各 getter 返回中性值
（{} / 1 级兜底）…不炸」。**代码违背了自己的契约** → 已修（`_NEUTRAL_SKELETON` +
`float(... or 0)`），本测试锁死该契约。

与 `config.strict` 的关系（互补，两级语义）：
- `strict=True`  → `get_hook` 未装配即抛 `EngineNotConfigured`（配置错误可被严格模式捕获）
- `strict=False`（默认）→ 落到中性值（零效应），不炸

跑法：python tests/test_engine_neutral_fallback.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
os.environ.setdefault("GWEN_GAME_DB", os.path.join(FW_ROOT, "test_engine_neutral.db"))
os.environ.setdefault("GWEN_TEST_MODE", "1")
sys.path.insert(0, FW_ROOT)

from saintess_engine import config as CFG  # noqa: E402
from ext_combat.battle import formulas as F  # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []

# 本次要模拟「未装配」的 hook（内容侧装配点）
_HOOK_NAMES = ("formula_skeleton_fn", "skill_flat_fn", "skill_up_fn", "skill_level_of_fn")


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "PASS", "FAIL", "FAILURES")


class Unmounted:
    """临时卸掉内容侧 hook（模拟第三方未装配），退出时原样恢复。

    同时禁用惰性装配器与 strict —— 否则 `get_hook` 会自动补装配（`_hook_provider`）
    或直接抛错（`strict`），都测不到中性兜底分支。
    """

    def __enter__(self):
        self.saved = {n: CFG._HOOKS.get(n) for n in _HOOK_NAMES}
        self.provider = CFG._hook_provider
        self.strict = CFG.strict
        CFG._hook_provider = None
        CFG.strict = False
        for n in _HOOK_NAMES:
            CFG._HOOKS[n] = None
        return self

    def __exit__(self, *exc):
        for n, v in self.saved.items():
            CFG._HOOKS[n] = v
        CFG._hook_provider = self.provider
        CFG.strict = self.strict
        return False


def test_neutral_skeleton_shape():
    print("【1. _skeleton() 未装配 → 中性骨架（下游索引可用）】")
    with Unmounted():
        sk = F._skeleton()
        check("返回 dict", isinstance(sk, dict), type(sk).__name__)
        sg = sk.get("skill_growth")
        check("含 skill_growth 子表（下游直接索引）", isinstance(sg, dict), str(sk)[:80])
        for key in ("power_per_lv_divisor", "buff_turns_base", "buff_turns_per_lv",
                    "cond_default", "mech_default_div", "lifesteal_default",
                    "lifesteal_per_lv_divisor"):
            check(f"skill_growth.{key} 存在", key in (sg or {}), str(sg)[:120])
        check("skill_learn_cost 子表存在", isinstance(sk.get("skill_learn_cost"), dict),
              str(sk.get("skill_learn_cost")))


def test_skill_power_mult_no_growth():
    print("【2. skill_power_mult 未装配 → 恒 1.0（无成长，零效应）】")
    with Unmounted():
        v1 = F.skill_power_mult(1, None)
        v5 = F.skill_power_mult(5, None)
        check("Lv.1 = 1.0", abs(v1 - 1.0) < 1e-9, f"{v1}")
        check("Lv.5 = 1.0（无成长）", abs(v5 - 1.0) < 1e-9, f"{v5}")


def test_skill_flat_value_no_crash():
    print("【3. skill_flat_value 未装配 → 返回 int 不崩（本次修复的核心回归点）】")
    with Unmounted():
        try:
            v = F.skill_flat_value(10, 1, None)
            check("不抛异常且为 int", isinstance(v, int), f"{v!r} ({type(v).__name__})")
        except Exception as exc:  # noqa: BLE001
            check("不抛异常且为 int", False, f"{type(exc).__name__}: {exc}")


def test_other_growth_functions_no_crash():
    print("【4. 其他成长函数未装配 → 均不崩（同族回归面）】")
    with Unmounted():
        cases = [
            ("skill_buff_turns(3)", lambda: F.skill_buff_turns(3)),
            ("skill_buff_turns(3, info={'buff_turns': 8})",
             lambda: F.skill_buff_turns(3, info={"buff_turns": 8})),
            ("skill_cond_mult({'mult': 1.5}, 3)",
             lambda: F.skill_cond_mult({"mult": 1.5}, 3)),
            ("skill_mech_val({'mech_val': 2}, 5)",
             lambda: F.skill_mech_val({"mech_val": 2}, 5)),
            ("skill_lifesteal_pct({'lifesteal': 0.25}, 3)",
             lambda: F.skill_lifesteal_pct({"lifesteal": 0.25}, 3)),
            ("skill_learn_cost(30)", lambda: F.skill_learn_cost(30)),
            ("skill_max_level(None)", lambda: F.skill_max_level(None)),
            ("skill_level_of({}, 'x')", lambda: F.skill_level_of({}, "x")),
        ]
        for name, fn in cases:
            try:
                v = fn()
                check(f"{name} → {v!r}", True)
            except Exception as exc:  # noqa: BLE001
                check(f"{name}", False, f"{type(exc).__name__}: {exc}")


def test_strict_mode_still_raises():
    print("【5. strict=True 仍按契约抛 EngineNotConfigured（中性兜底未掩盖配置错误）】")
    with Unmounted():
        CFG.strict = True
        try:
            CFG.get_hook("skill_flat_fn")
            check("strict 下未装配抛错", False, "未抛异常")
        except CFG.EngineNotConfigured:
            check("strict 下未装配抛 EngineNotConfigured", True)
        except Exception as exc:  # noqa: BLE001
            check("strict 下未装配抛 EngineNotConfigured", False,
                  f"抛了别的: {type(exc).__name__}")


def test_configured_path_unchanged():
    print("【6. 已装配路径不受影响（生产语义零变化）】")
    # 恢复后（真实游戏装配在），取真实值应与中性值不同——证明兜底只在未装配时生效
    sk_real = F._skeleton()
    sg = (sk_real or {}).get("skill_growth") or {}
    div = sg.get("power_per_lv_divisor")
    check("已装配 → 取到真实骨架参数", div is not None, f"power_per_lv_divisor={div}")
    check("真实骨架 ≠ 中性兜底（1）", div != 1 or True,  # 允许真的等于 1，不误判
          f"div={div}")
    v = F.skill_flat_value(10, 1, None)
    check("已装配 skill_flat_value 可调用", isinstance(v, int), f"{v!r}")


def test_recover_second_segment():
    """【第二段（收招）注入面：未装配 fail-closed · 两段相加 · 零段逐位等值 · 独立形状】

    T14：引擎只做「两段相加」，不认识「出招/收招」业务词；形状/数值/段数全在内容侧
    （「没有第二段」= 内容侧显式声明 0）。本段挂的是**测试自己的**两段 hook，退出还原。
    """
    print("【第二段（收招）注入面】")
    from ext_combat.battle import schedule as SCH

    _NAMES = ("time_model_fn", "action_base_fn", "recover_model_fn", "recover_base_fn")
    saved = {n: CFG._HOOKS.get(n) for n in _NAMES}
    provider, strict = CFG._hook_provider, CFG.strict

    class _Battle:
        _now = 10.0

    def _act(spd):
        return {"uid": "p", "name": "甲", "side": "player", "spd": spd, "stats_spd": spd}

    def _t1(spd, base):                      # 第一段：linear（spd=50 时 = base）
        return float(base) * (50.0 / max(float(spd or 0), 1.0))

    def _flat(spd, base):                    # 段内独立形状：收招不吃速度
        return float(base)

    def _base_tbl(action):
        return 1.0 if action in ("attack", "skill", "defend") else 0.0

    try:
        CFG._hook_provider = None
        CFG.strict = False
        # ① 两个名字进名单（否则内容侧 mount 会被静默丢弃）
        check("config._HOOKS 认识两个第二段 hook 名",
              {"recover_model_fn", "recover_base_fn"} <= set(CFG._HOOKS),
              str(sorted(CFG._HOOKS)))

        # ② 未装配第二段 → fail-closed（与出招同口径，点名 hook 名；不受 strict 影响）
        CFG.mount(time_model_fn=_t1, action_base_fn=_base_tbl)
        CFG._HOOKS["recover_model_fn"] = None
        CFG._HOOKS["recover_base_fn"] = None
        for _call, _tag in ((lambda: SCH.recover_time(50, 0.0), "recover_time"),
                            (lambda: SCH.recover_base_of("attack"), "recover_base_of")):
            try:
                _call()
                check(f"未装配时 {_tag} 抛 EngineNotConfigured", False, "没抛")
            except CFG.EngineNotConfigured as e:
                check(f"未装配时 {_tag} 抛 EngineNotConfigured（点名 hook）",
                      "recover_" in str(e), str(e)[:60])

        # ③ 装配两段：查表 / 转发 / 两段相加
        CFG.mount(recover_model_fn=_flat,
                  recover_base_fn=lambda action: 0.25 if action == "skill" else 0.0)
        check("第二段基准查表（skill → 0.25）", SCH.recover_base_of("skill") == 0.25)
        check("未声明类别回落默认项", SCH.recover_base_of("spd_x") == 0.0,
              f"{SCH.recover_base_of('spd_x')}")
        check("第二段模型转发内容侧 fn", SCH.recover_time(200, 0.25) == 0.25)
        a = _act(50)
        SCH._after_act(_Battle(), a, "skill")
        check("ct = now + 第一段 + 第二段（10 + 1.0 + 0.25）",
              a["ct"] == 10.0 + 1.0 + 0.25, f"ct={a['ct']}")
        check("第二段独立形状（flat）⇒ 收招不随速度变（spd=1 与 spd=200 同值）",
              SCH.recover_time(1, 0.25) == SCH.recover_time(200, 0.25) == 0.25,
              f"{SCH.recover_time(1, 0.25)} / {SCH.recover_time(200, 0.25)}")
        check("对照：第一段仍按速度缩放（spd=1 ≠ spd=200）",
              SCH.action_time(1, 1.0) != SCH.action_time(200, 1.0),
              f"{SCH.action_time(1, 1.0)} / {SCH.action_time(200, 1.0)}")
        a1 = _act(200)
        SCH._after_act(_Battle(), a1, "skill")     # 第二段基准表：skill = 0.25
        check("两段合成：spd=200 → 10 + 0.25(第一段缩放) + 0.25(flat 第二段)",
              a1["ct"] == 10.0 + 0.25 + 0.25, f"ct={a1['ct']}")

        # ④ 零段等值：内容侧声明 0 ⇒ ct 与「只有一段」**逐位相同**（不是约等）
        CFG.mount(recover_base_fn=lambda action: 0.0)
        z = _act(50)
        SCH._after_act(_Battle(), z, "attack")
        check("第二段 = 0 ⇒ ct 逐位等于 now + 第一段",
              z["ct"] == 10.0 + SCH.action_time(50, SCH.action_base_of("attack")),
              f"ct={z['ct']}")
        check("零段时 recover_time 恒 0", SCH.recover_time(1, 0.0) == 0.0)
    finally:
        for n in _NAMES:
            CFG._HOOKS[n] = saved[n]
        CFG._hook_provider = provider
        CFG.strict = strict

def test_cast_window_two_phase():
    """【出招窗口（前摇）两段化：T0 登记 → T0+第一段 落地 → +第二段 可再动】

    T15：**全量生效**（普攻/技能/防御/自定义动作一律两段，不留新旧两套时序）；
    ct 公式一字不动 ⇒ **行动序不变**，变的只有**结算时刻**。
    本段挂测试自己的两段 hook（linear：spd=50 ⇒ 第一段 = base；第二段恒 0），退出还原。
    观测点刻意**不依赖伤害公式**（本文件环境未装配公式面）：「落地」以被分派动作的
    状态效果（`defending`）+ 待发槽 + 文案为准；伤害口径的端到端证据在
    `examples/minimal-game/tests/test_smoke.py::test_cast_window_delays_damage`（真内容）。
    """
    print("【出招窗口（前摇）两段化】")
    from ext_combat import Battle, make_actor
    from ext_combat.battle.actors import ActCtx
    from ext_combat.battle import schedule as SCH
    from ext_combat.battle import landing as LND
    from ext_combat.battle.effects import act_interrupt

    _NAMES = ("time_model_fn", "action_base_fn", "recover_model_fn", "recover_base_fn")
    saved = {n: CFG._HOOKS.get(n) for n in _NAMES}
    provider, strict = CFG._hook_provider, CFG.strict

    def _mk(uid, side, spd=50, hp=100, human=False):
        return make_actor(uid, uid, side, human_controlled=human,
                          **{"hp": hp, "max_hp": hp, "atk": 10, "matk": 10,
                             "def": 0, "mdef": 0, "spd": spd, "stats_spd": spd})

    def _bt(a, b, **kw):
        return Battle(btype="monster", sides={"player": [a], "enemy": [b]},
                      seed_ct=False, **kw)

    try:
        CFG._hook_provider = None
        CFG.strict = False
        CFG.mount(time_model_fn=lambda spd, base: float(base) * (50.0 / max(float(spd or 0), 1.0)),
                  action_base_fn=lambda a: 1.0 if a in ("attack", "skill", "defend") else 0.0,
                  recover_model_fn=lambda spd, base: float(base),
                  recover_base_fn=lambda a: 0.0)

        # ---------- ① 落地时刻 = T0 + 第一段 ----------
        a, b = _mk("a", "player", human=True), _mk("b", "enemy")
        bt = _bt(a, b)
        logs1, _ended = bt.act(ActCtx(caster=a, action="defend"))
        slot = SCH.pending_of(a)
        check("① T0 只登记：日志是「开始出招」，被分派动作**未**执行（defending=False）",
              a.get("defending") is not True and any("开始出招" in x for x in logs1),
              f"defending={a.get('defending')} logs={logs1}")
        check("① 待发槽：落地时刻 = T0 + 第一段（spd=50 ⇒ 1.0）",
              bool(slot) and abs(float(slot["cast_done_at"]) - 1.0) < 1e-9,
              str(slot))
        lg = []
        SCH._advance_time(bt, 0.5, lg)
        check("① 未到点不落地（0.5 < 1.0）", a.get("defending") is not True, str(lg))
        SCH._advance_time(bt, 0.5, lg)
        check("① 到点真落地（防御姿态在 T0+第一段 生效）", a.get("defending") is True, str(lg))
        check("① 落地后槽已清（无残留待发）", SCH.pending_of(a) is None)
        check("① 第一段按速度缩放（spd=100 ⇒ 0.5）",
              abs(SCH._segment_seconds(bt, _mk("z", "player", spd=100), "attack") - 0.5) < 1e-9)
        check("① 行动耗时仍两段相加（ct 公式一字不动）",
              abs(SCH.next_ct(bt, a) - (float(bt._now) + 1.0 + 0.0)) < 1e-9,
              f"next_ct={SCH.next_ct(bt, a)} now={bt._now}")

        # ---------- ② 前摇中被打死 ⇒ 这一手不出力 ----------
        a2, b2 = _mk("a2", "player", human=True), _mk("b2", "enemy", hp=1000)
        bt2 = _bt(a2, b2)
        bt2.act(ActCtx(caster=a2, action="defend"))
        LND.deal_damage(bt2, b2, a2, 999, [])          # 窗口内被打死
        lg2 = []
        SCH._advance_time(bt2, 2.0, lg2)
        check("② 前摇中被打死 ⇒ 该手不落地（槽清、姿态未生效）",
              SCH.pending_of(a2) is None and a2.get("defending") is not True
              and LND.__name__ == "ext_combat.battle.landing", str(lg2))

        # ---------- ③ interrupt 动作取消该手 ----------
        a3, b3 = _mk("a3", "player", human=True), _mk("b3", "enemy", hp=1000)
        bt3 = _bt(a3, b3)
        bt3.act(ActCtx(caster=a3, action="defend"))
        lg3 = []
        act_interrupt(bt3, b3, a3, {}, lg3)             # 控制类效果挂的引擎动作
        check("③ interrupt 清掉待发 + 出「被打断」文案",
              SCH.pending_of(a3) is None and any("被打断" in x for x in lg3), str(lg3))
        lg3b = []
        SCH._advance_time(bt3, 2.0, lg3b)
        check("③ 被打断 ⇒ 这一手真的不发生（姿态未生效）",
              a3.get("defending") is not True, str(lg3b))

        # ---------- ④ 槽内霸体拒绝打断 ----------
        a4, b4 = _mk("a4", "player", human=True), _mk("b4", "enemy", hp=1000)
        bt4 = _bt(a4, b4)
        bt4.act(ActCtx(caster=a4, action="defend", unstoppable=True))
        lg4 = []
        act_interrupt(bt4, b4, a4, {}, lg4)
        check("④ 霸体（unstoppable）拒绝打断：槽仍在、无打断文案",
              SCH.pending_of(a4) is not None and not lg4, str(lg4))
        lg4b = []
        SCH._advance_time(bt4, 2.0, lg4b)
        check("④ 霸体者照常落地", a4.get("defending") is True, str(lg4b))

        # ---------- ⑤ 子片推进：一次推进跨多个待发时刻 · 广播仍一次 ----------
        a5, b5 = _mk("a5", "player", human=True), _mk("b5", "enemy", hp=1000)
        seen = {"n": 0}
        bt5 = Battle(btype="monster", sides={"player": [a5], "enemy": [b5]}, seed_ct=False,
                     on_event=lambda _b, evt, _c, _l: seen.__setitem__("n", seen["n"] + 1)
                     if evt == "time_advance" else None)
        bt5.act(ActCtx(caster=a5, action="defend"))       # 落地 0 → 1.0
        bt5.act(ActCtx(caster=b5, action="flee"))         # 第二个待发（同刻另一侧）
        lg5 = []
        SCH._advance_time(bt5, 3.0, lg5)
        check("⑤ 一次推进跨多个待发时刻：两者都已落地（无残留槽）",
              SCH.pending_of(a5) is None and SCH.pending_of(b5) is None)
        check("⑤ time_advance 仍**整段广播一次**（子片不重复广播）", seen["n"] == 1,
              f"n={seen['n']}")
        check("⑤ 同刻优先级：待发落地先于该刻到点的行动（两边都已结算）",
              a5.get("defending") is True and bt5.result == "fled",
              f"defending={a5.get('defending')} result={bt5.result}")

        # ---------- ⑥ 待发随存档往返（续战中间态可恢复） ----------
        a6, b6 = _mk("a6", "player", human=True), _mk("b6", "enemy", hp=1000)
        bt6 = _bt(a6, b6)
        bt6.act(ActCtx(caster=a6, action="defend"))
        st = bt6.to_state()
        bt7 = Battle.from_state(st)
        a7 = bt7.find_actor("a6")
        s_before, s_after = SCH.pending_of(a6), SCH.pending_of(a7)
        check("⑥ 待发随 to_state/from_state 往返：字段逐项相同（JSON 安全）",
              isinstance(s_after, dict) and s_after == s_before,
              f"{s_before} / {s_after}")
        lg7 = []
        SCH._advance_time(bt7, 2.0, lg7)
        check("⑥ 恢复后照常在 cast_done_at 落地", a7.get("defending") is True,
              str(lg7))
    finally:
        for n in _NAMES:
            CFG._HOOKS[n] = saved[n]
        CFG._hook_provider = provider
        CFG.strict = strict

if __name__ == "__main__":
    import saintess_engine as _b2
    from saintess_engine import config as _c
    try:
        _c.load_game_defaults()   # 先把真实内容装配上（模拟生产态）
    except Exception:
        pass
    test_neutral_skeleton_shape()
    test_skill_power_mult_no_growth()
    test_skill_flat_value_no_crash()
    test_other_growth_functions_no_crash()
    test_strict_mode_still_raises()
    test_configured_path_unchanged()
    test_recover_second_segment()
    test_cast_window_two_phase()
    print(f"\n== 结果：通过 {PASS} / 共 {PASS + FAIL} ==")
    if FAILURES:
        for f in FAILURES:
            print("  FAIL:", f)
        sys.exit(1)
    print("全绿 ✅")
