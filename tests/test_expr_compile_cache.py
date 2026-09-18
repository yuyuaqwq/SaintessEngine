#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""expr 编译缓存门禁：同串复用同一份操作数栈（纯数据、只读），且不改变任何求值结果。

为什么钉这一条（都是「改了就静默变行为」的口子）：
  ① **命中 ≡ 重编译**：同串两次 `compile_expr` 逐项相等，且是同一对象（缓存真的生效）。
  ② **缓存不污染求值**：同一份 code 换 `vars` 反复求值 = 每次现编译再求值（逐值相等）。
  ③ **有上界**：条目数超过 `_COMPILE_CACHE_MAX` 即清空（内容侧动态拼串不许把内存顶爆）。
  ④ **失败不缓存**：语法错的串每次都必须抛 `ExprError`（不许把失败「缓存成通过」）。

跑法：python tests/test_expr_compile_cache.py
退出码：0 = 全绿；1 = 有失败。
"""
import os
import random
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from saintess_engine import expr as EX  # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name} {detail}")


print("【1. 命中缓存 = 同一对象（纯数据复用）】")
EX._COMPILE_CACHE.clear()
a = EX.compile_expr("atk*1.5 + 12 + player_lv*4.5")
b = EX.compile_expr("atk*1.5 + 12 + player_lv*4.5")
check("同串两次结果逐项相等", a == b, f"a={a} b={b}")
check("同串两次是同一对象（命中缓存）", a is b)
check("缓存条目 = 1", len(EX._COMPILE_CACHE) == 1, len(EX._COMPILE_CACHE))

print("【2. 归一化：首尾空白同键】")
c = EX.compile_expr("   atk*1.5 + 12 + player_lv*4.5  ")
check("带空白串命中同一条", c is a)
check("缓存条目仍 = 1", len(EX._COMPILE_CACHE) == 1, len(EX._COMPILE_CACHE))
check("空串 / None → None（原行为不变）",
      EX.compile_expr("") is None and EX.compile_expr(None) is None)

print("【3. 缓存不污染求值：同 code 换 vars ≡ 现编译】")
random.seed(20260919)
bad = 0
for _ in range(200):
    v = {"atk": random.uniform(0, 999), "player_lv": random.randint(1, 60),
         "skill_lv": random.randint(1, 9), "max_hp": random.uniform(1, 9999)}
    got = EX.eval_expr(a, v)                       # 走缓存的那份 code
    ref = EX.eval_expr(EX.compile_expr("atk*1.5 + 12 + player_lv*4.5"), v)   # 命中同一对象
    ref2 = 1.5 * v["atk"] + 12 + 4.5 * v["player_lv"]                        # 手算参照
    if abs(got - ref) > 1e-9 or abs(got - ref2) > 1e-9:
        bad += 1
check("200 组随机 vars：缓存值与手算逐值相等", bad == 0, f"bad={bad}")

print("【4. 逐级公式串（exprs 数组）+ 不同串不同结果】")
d1 = EX.eval_expr(EX.compile_expr("matk*1.4 + 15 + skill_lv*12"), {"matk": 100, "skill_lv": 4})
d2 = EX.eval_expr(EX.compile_expr("matk*1.4 + 15 + skill_lv*10"), {"matk": 100, "skill_lv": 4})
check("不同串 → 不同结果（未串键）", abs(d1 - d2 - 8.0) < 1e-9, f"{d1} {d2}")
check("缓存条目 = 3（三串各自一条）", len(EX._COMPILE_CACHE) == 3, len(EX._COMPILE_CACHE))

print("【5. 失败不缓存：语法错每次都抛】")
n0 = len(EX._COMPILE_CACHE)
raises = 0
for _ in range(3):
    try:
        EX.compile_expr("(1+2")
    except EX.ExprError:
        raises += 1
check("3 次都抛 ExprError", raises == 3, f"raises={raises}")
check("失败不进缓存", len(EX._COMPILE_CACHE) == n0, len(EX._COMPILE_CACHE))

print("【6. 上界：超 _COMPILE_CACHE_MAX 即清空，不无界增长】")
EX._COMPILE_CACHE.clear()
MAX = EX._COMPILE_CACHE_MAX
for i in range(MAX + 100):
    EX.compile_expr(f"atk*1 + {i}")
n_after = len(EX._COMPILE_CACHE)
check(f"条目数 <= {MAX}", n_after <= MAX, n_after)
check("清空后仍能编译新串（值正确）",
      abs(EX.eval_expr(EX.compile_expr("atk*2 + 7"), {"atk": 10}) - 27.0) < 1e-9)
EX._COMPILE_CACHE.clear()

print(f"\n结果: {passed} 通过 / {failed} 失败")
sys.exit(1 if failed else 0)
