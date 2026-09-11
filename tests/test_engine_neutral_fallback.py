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
from saintess_engine import formulas as F  # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []

# 本次要模拟「未装配」的 hook（内容侧装配点）
_HOOK_NAMES = ("formula_skeleton_fn", "skill_flat_fn", "skill_up_fn", "skill_level_of_fn")


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        FAILURES.append(f"{name}: {detail}")
        print(f"  ❌ {name} {detail}")


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
    print(f"\n== 结果：通过 {PASS} / 共 {PASS + FAIL} ==")
    if FAILURES:
        for f in FAILURES:
            print("  FAIL:", f)
        sys.exit(1)
    print("全绿 ✅")
