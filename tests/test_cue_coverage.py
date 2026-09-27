# -*- coding: utf-8 -*-
"""门禁：cue **覆盖尺** —— 61 条声明，每条至少被真驱动一次（设计案 §3.2③「不许放过」）。

判据
----
1. `tools/_cue_coverage.py` 必须绿：`union(冻结 5 组, 覆盖尺补驱动, 登记表) == CUE_NAMES`
   （= 每条 cue 要么被真驱动过、要么在登记表里逐条写明为什么够不着 —— **没有第三态**）。
2. 覆盖尺里的每个驱动函数都必须指向一条**真 cue 名**（不许有野驱动），登记表同理。
3. 覆盖尺的驱动**不许直接发 cue**：驱动函数体里出现 `cue(`/`_cue(` 字样 ⇒ 红
   （那会变成"自证"：只证明总线通，不证明那条路真会发）。

为什么这条门禁必须有
--------------------
`tools/_cue_freeze.py` 的 5 组战斗是**逐字节冻结基线**（改脚本 = 毁基线），只覆盖 45/61；
剩下 16 条如果没人管，就是「迁移了但等价性没被验证」的灰区。覆盖尺补的就是这 15 条。
"""
import ast
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_ROOT, os.path.join(_ROOT, "extends"), _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ext_combat.battle.cues import CUE_NAMES                                # noqa: E402

passed = failed = 0


def check(label, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print("  ✅ %s%s" % (label, ("  —— %s" % extra) if extra else ""))
    else:
        failed += 1
        print("  ❌ %s%s" % (label, ("  —— %s" % extra) if extra else ""))
    return bool(cond)


_TOOL = os.path.join(_ROOT, "tools", "_cue_coverage.py")
print("【1. 覆盖尺本体：跑一遍，必须「全覆盖」】")
_res = subprocess.run([sys.executable, _TOOL, "--tree", _ROOT],
                      capture_output=True, text=True, encoding="utf-8")
_out = (_res.stdout or "") + (_res.stderr or "")
_lines = [ln.strip() for ln in _out.splitlines() if ln.strip()]
_sum = [ln for ln in _lines if "冻结 5 组" in ln and "声明" in ln]
check("覆盖尺 EXIT=0（union == CUE_NAMES）", _res.returncode == 0,
      (_sum[-1] if _sum else _out[-200:]))
check("读到的汇总行含「全覆盖 ✓」", "全覆盖 ✓" in _out,
      (_sum[-1] if _sum else "（没读到汇总行）"))
if _sum:
    check("并集条数 == 声明条数 == %d" % len(CUE_NAMES),
          ("/ 声明 %d" % len(CUE_NAMES)) in _sum[-1], _sum[-1])

print("\n【2. 静态：驱动/登记只许指向真 cue 名】")
_src = open(_TOOL, encoding="utf-8").read()
_tree = ast.parse(_src)
_drv = set()
for _n in ast.walk(_tree):
    if isinstance(_n, ast.Call) and isinstance(_n.func, ast.Name) and _n.func.id == "driver":
        if _n.args and isinstance(_n.args[0], ast.Constant):
            _drv.add(_n.args[0].value)
_names = set(CUE_NAMES)
check("驱动函数数 > 0（覆盖尺不是在空转）", len(_drv) > 0, "%d 个" % len(_drv))
check("★ 每个驱动都指向一条真 cue 名（无野驱动）", _drv <= _names,
      str(sorted(_drv - _names))[:120])

print("\n【3. 静态：驱动不许「直接发 cue」（防自证）】")
_bad = []
for _n in ast.walk(_tree):
    if not isinstance(_n, ast.FunctionDef) or _n.name not in {d for d in _drv}:
        continue
    for _sub in ast.walk(_n):
        if isinstance(_sub, ast.Call):
            _f = _sub.func
            _nm = _f.attr if isinstance(_f, ast.Attribute) else (
                _f.id if isinstance(_f, ast.Name) else "")
            if _nm in ("cue", "_cue", "emit"):
                _bad.append("%s():%d" % (_n.name, _sub.lineno))
check("★ 驱动函数体里零 `cue(...)` / `emit(...)` 调用（只走引擎真结算路径）", not _bad,
      str(_bad[:5]))

print("\n===== 结果：通过 %d / %d =====" % (passed, passed + failed))
sys.exit(1 if failed else 0)
