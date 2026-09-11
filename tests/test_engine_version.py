# -*- coding: utf-8 -*-
"""版本与兼容性检查门禁（saintess_engine.version）。

三条不变量：
  1. 包门面导出 __version__ / VERSION_INFO / version 模块
  2. 比较语义正确（含"前缀补齐"：0.1 == 0.1.0）
  3. **fail-closed**：无法解析的版本需求算不满足（绝不静默放行）
     这条对应设计约定「不满足要显式报错，不静默降级」。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
if FW_ROOT not in sys.path:
    sys.path.insert(0, FW_ROOT)

import saintess_engine as E                     # noqa: E402
from saintess_engine import version as V        # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name} {detail}")


print("== 版本与兼容性门禁 ==")

# 1. 门面导出
check("包门面导出 __version__（形如 x.y.z）",
      isinstance(getattr(E, "__version__", None), str)
      and len(E.__version__.split(".")) >= 2, getattr(E, "__version__", None))
check("VERSION_INFO 是 3 元整数元组",
      isinstance(E.VERSION_INFO, tuple) and len(E.VERSION_INFO) == 3
      and all(isinstance(x, int) for x in E.VERSION_INFO), E.VERSION_INFO)
check("version 模块可从门面取到", hasattr(E, "version") and E.version is V)

# 2. 比较语义（★ 用例**版本相对**：从实际版本推导，升版不红）
#    旧版把 0.1.0 的期望写死 → 版本一动（0.1.0→0.2.0）整片假红，与「门禁查语义」的初衷无关。
MAJ, MIN, PAT = E.VERSION_INFO
cur = f"{MAJ}.{MIN}.{PAT}"
same_short = f"{MAJ}.{MIN}"           # 前缀补齐：0.2 == 0.2.0
lower = f"{MAJ}.{max(0, MIN - 1)}"     # 低于当前（同主版本）
next_minor = f"{MAJ}.{MIN + 1}"        # 高于当前（同主版本）
CASES = [
    (f">={same_short}", True),                      # 前缀补齐也算满足
    (f">={cur}", True),
    (f"=={cur}", True),
    (f"=={same_short}", True),                      # 0.2 == 0.2.0
    (f"!={same_short}", False),
    (f">{same_short}", False),                      # 不快于自身
    (f"<{same_short}", False),
    (f">={MAJ}.{MIN - 1 if MIN > 0 else 0},<{next_minor}", True),   # 区间含当前
    (f">={MAJ + 1}", False),                        # 主版本超前 → 不满足
    (f">=0.0.1", True),                             # 极老需求 → 满足
    (f">=v{same_short}", True),                     # 允许 v 前缀
    ("", True),                                     # 空需求 = 不约束
]
bad = [(r, V.satisfies(r)) for r, want in CASES if V.satisfies(r) is not want]
check(f"比较语义 {len(CASES)} 例（版本相对，含前缀补齐 {same_short} == {cur}）",
      not bad, f"bad={bad}（当前 {cur}）")
check("前缀补齐：'==0.1' 与 '==0.1.0' 等价",
      V.satisfies("==0.1", "0.1.0") and V.satisfies("==0.1.0", "0.1"))
check("区间 '>=0.1,<0.2' 对 0.1.x 成立（与当前版本无关的固定语义）",
      V.satisfies(">=0.1,<0.2", "0.1.0") is True)

# 3. fail-closed
ok, note = V.check("bogus")
check("无法解析的需求 → 不满足（fail-closed）", ok is False, note)
ok2, _ = V.check(">=")
check("残缺需求（'>= ' 无版本号）→ 不满足", ok2 is False)
ok3, note3 = V.check(">=0.1")
check("满足时给出可读说明（含实际版本）", ok3 is True and V.__version__ in note3, note3)

# 4. 编辑器接线（engine_check 不阻断：框架不可用时应返回 ok=None 而非抛错）
try:
    sys.path.insert(0, os.path.join(FW_ROOT, "editor"))
    from editor import packages as PK
    r_ok = PK.engine_check({"engine": ">=0.1"})
    r_bad = PK.engine_check({"engine": ">=9"})
    r_none = PK.engine_check({})
    check("engine_check：满足 → ok=True", r_ok.get("ok") is True, r_ok)
    check("engine_check：不满足 → ok=False", r_bad.get("ok") is False, r_bad)
    check("engine_check：未声明 → ok=True", r_none.get("ok") is True, r_none)
except Exception as e:                                   # noqa: BLE001
    check("engine_check 可导入且不抛错", False, repr(e))

print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
sys.exit(1 if failed else 0)
