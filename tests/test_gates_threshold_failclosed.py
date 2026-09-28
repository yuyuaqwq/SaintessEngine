#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""gates 门禁：六个校验器的「用法错抛异常 / 数据错给文案」边界（审计 L1742 · L1743）。

跑法：python tests/test_gates_threshold_failclosed.py
退出码：0 = 全绿；1 = 有失败。

本文件钉的是模块 docstring 亲自承诺的那条契约（`gates/__init__.py:18`）：

    `label` 空串 / 非 str ⇒ 抛 `TypeError`；`budget`/`tol`/`cap` 非法 ⇒ 抛 `ValueError`。

实测修前两处**承诺未兑现**（同一形状的邻座都有守卫，只有这两处漏了）：
  ① `sum_within(budget=-10)` → 不抛，报红文案写「上限 -10（超出 inf%）」
     —— 负预算不是「算得紧」，是配平脚本自己把阈值写反了；
  ② `spread_within(tol=-0.5)` → 不抛，`r <= t` 恒假 ⇒ **每次跑都全组报红**。

★ 判据钉的是**性质**（非法阈值必抛），不是源码形态：把守卫换成 `if t < 0: raise`
或塞进 `_num` 里都应照样绿。合法阈值的行为一个字未动。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from saintess_engine import gates  # noqa: E402

from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

passed = failed = 0
check = bind_check(globals(), "passed", "failed")

GOOD = [("a", 1.0), ("b", 3.0)]


# ---------------------------------------------------------------- L1742 · 负/零预算
for bad in (-10.0, -0.0001, -1):
    try:
        gates.sum_within([("a", 5.0)], budget=bad, label="L1")
    except ValueError:
        ok = True
    except Exception as e:  # noqa: BLE001
        ok = False
    else:
        ok = False
    check(f"sum_within 负预算 {bad!r} 抛 ValueError（修前静默报红）", ok)

# ★ `budget=0` 是**合法**阈值（合���上限本就可以是 0），邻座 `within_budget`
# 同样放行并用同一套 `inf%` 口径处理 ⇒ 这里钉「与邻座同口径」，不是钉抛。
check("sum_within budget=0 仍照旧报红且与 within_budget 同口径（合法阈值不许被收紧）",
      len(gates.sum_within([("a", 5.0)], budget=0.0, label="L1")) == 1
      and gates.within_budget(5.0, budget=0.0, label="L1")[0].endswith("inf%）"))

check("sum_within 合法阈值下行为不变（Σ=2 恰等于 budget=2 ⇒ 通过）",
          gates.sum_within([("a", 1.0), ("b", 1.0)], budget=2.0, label="L1") == [])
check("sum_within 超预算仍照旧报红（数据错给文案，不抛）",
          len(gates.sum_within([("a", 3.0)], budget=2.0, label="L1")) == 1)


# ---------------------------------------------------------------- L1743 · 负容差
for bad in (-0.5, -0.001, -1e-9):
    try:
        gates.spread_within(GOOD, tol=bad, label="L1")
    except ValueError:
        ok = True
    except Exception:  # noqa: BLE001
        ok = False
    else:
        ok = False
    check(f"spread_within 负容差 tol={bad!r} 抛 ValueError（修前恒全组报红）", ok)

check("spread_within tol=1.0 仍通过（合法上界）",
          gates.spread_within(GOOD, tol=1.0, label="L1") == [])
check("spread_within tol=0.0 仍照旧报红（零容差 = 极差必须为 0）",
          len(gates.spread_within(GOOD, tol=0.0, label="L1")) == 1)
try:
    gates.spread_within(GOOD, tol=1.0001, label="L1")
    oku = False
except ValueError:
    oku = True
except Exception:  # noqa: BLE001
    oku = False
check("spread_within tol>1 仍抛（既有上界守卫未被本次改动削弱）", oku)


# ---------------------------------------------------------------- 邻座守卫未被削弱
for name, kw, call in (
    ("within_budget", {"budget": -1.0}, lambda: gates.within_budget(1.0, budget=-1.0, label="L1")),
    ("within_cap", {"cap": -1.0}, lambda: gates.within_cap(1.0, cap=-1.0, label="L1")),
    ("share_within", {"cap": -0.5}, lambda: gates.share_within([("a", 1.0)], total=1.0, cap=-0.5, label="L1")),
):
    try:
        call()
    except ValueError:
        ok = True
    except Exception:  # noqa: BLE001
        ok = False
    else:
        ok = False
    check(f"{name} 负阈值 {kw} 仍抛 ValueError（同族不得被本次改动放过）", ok)


# ---------------------------------------------------------------- 门禁本身不空转
try:
    gates.sum_within([("a", 5.0)], budget=-1.0, label="L1")
    notraised = False
except ValueError:
    notraised = True
check("反证锚点可达：修前这条调用返回而不抛（判据会红）", notraised)

print(f"  passed={passed}  failed={failed}")
sys.exit(1 if failed else 0)
