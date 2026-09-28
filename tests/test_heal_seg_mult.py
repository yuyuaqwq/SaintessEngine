# -*- coding: utf-8 -*-
"""治疗段乘区门禁：`heal_formula` **段列表**的 `mult` 回落只认 `None`（审计 L251 同族）。

背景
----
`extends/ext_combat/battle/actions.py::_heal_amount` 的段求和循环里，两处段倍率写成
`float(hseg.get("mult", 1.0) or 1.0)`。`or` 会把**合法 0** 吞成 1.0，而
「段倍率」是乘区：0 与缺键语义完全相反（0 = 这一段不出治疗 / 缺键 = 按满倍率）。

缺陷实跑复现（改前，matk=100、单段 `{"stat":"matk","mult":0.0}`）：

    段 mult=0        -> 100   <- 应为 0（这一段被当成满倍率，静默放大）
    两段 0 + 1       -> 200   <- 应为 100（第一段白送 100）

零报错、零日志 —— 内容侧配出来的「某段不参与治疗」**做不出来**。

本门禁钉四件事（**缺一即红**）
------------------------------
A. 合法 0 被放行：单段 mult=0 => 0；两段 0+1 => 100（只有 1 那一段贡献）
B. 缺键仍回落 1.0；显式 1.0 / 2.0 / 0.5 逐字不变（证明「没改坏」）
C. 另外两个分支（`stat="max_hp"` / `stat="flat"`）同样只认 None
D. ★ 反证有牙：旧算法在同一组输入上必须给出旧缺陷值（100 / 200）

跑法：python tests/test_heal_seg_mult.py
"""
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, FW_ROOT)
sys.path.insert(0, os.path.join(FW_ROOT, "extends"))

import saintess_engine                                # noqa: E402,F401
from extends.ext_combat.battle import actions as A    # noqa: E402

from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

PASS = 0
FAIL = 0
FAILURES = []
check = bind_check(globals(), "PASS", "FAIL", "FAILURES")

_ST = {"matk": 100, "atk": 100}
_ACTOR = {"name": "A", "max_hp": 1000, "level": 1}


def _heal(segs):
    """走真实 _heal_amount（注入面齐备，不碰 cue 总线）。"""
    return A._heal_amount(_ST, _ACTOR, {"heal_formula": segs}, 1)


print("== A. 合法 0 被放行（原缺陷）==")
_got = _heal([{"stat": "matk", "mult": 0.0}])
check("单段 mult=0 => 0 治疗（原 100）", _got == 0, "got=%r" % (_got,))
_got2 = _heal([{"stat": "matk", "mult": 0.0}, {"stat": "matk", "mult": 1.0}])
check("两段 0 + 1 => 100（原 200）", _got2 == 100, "got=%r" % (_got2,))

print("== B. 缺键 / 显式非 0 逐字不变（没改坏）==")
for _segs, _want, _label in (
        ([{"stat": "matk"}], 100, "段 mult 缺键 => 100"),
        ([{"stat": "matk", "mult": 1.0}], 100, "段 mult=1.0 => 100"),
        ([{"stat": "matk", "mult": 2.0}], 200, "段 mult=2.0 => 200"),
        ([{"stat": "matk", "mult": 0.5}], 50, "段 mult=0.5 => 50")):
    _g = _heal(_segs)
    check(_label, _g == _want, "got=%r want=%r" % (_g, _want))

print("== C. 另外两个分支同样只认 None ==")
_g = _heal([{"stat": "max_hp", "mult": 0.0}])
check("stat=max_hp 段 mult=0 => 0（原 1000）", _g == 0, "got=%r" % (_g,))
_g = _heal([{"stat": "max_hp"}])
check("stat=max_hp 段 mult 缺键 => 1000", _g == 1000, "got=%r" % (_g,))
_g = _heal([{"stat": "flat", "flat": 0}])
check("stat=flat 段 flat=0 => 0", _g == 0, "got=%r" % (_g,))
_g = _heal([{"stat": "matk", "mult": 0.0},
            {"stat": "matk", "mult": 1.0},
            {"stat": "matk", "mult": 2.0}])
check("三段混合（0 + 1 + 2）=> 300", _g == 300, "got=%r" % (_g,))

print("== D. 反证：旧算法在同一组输入上必须给出旧缺陷值 ==")
# 直接量旧算法（`float(seg.get('mult', 1.0) or 1.0)`）—— 若它给出 100 / 200，
# 说明 A 的判据真的咬住了「合法 0 被吞成满倍率」这个缺陷，而不是恒真断言。
_old1 = int(100 * float({"stat": "matk", "mult": 0.0}.get("mult", 1.0) or 1.0))
check("反证·旧算法单段 mult=0 给 100（!= 新口径 0）", _old1 == 100, "got=%r" % (_old1,))
_old2 = int(100 * (float({"mult": 0.0}.get("mult", 1.0) or 1.0)
                   + float({"mult": 1.0}.get("mult", 1.0) or 1.0)))
check("反证·旧算法两段 0+1 给 200（!= 新口径 100）", _old2 == 200, "got=%r" % (_old2,))

# 源码面守卫：段倍率读点不得再出现 `or 1.0` 形态
_src = open(os.path.join(FW_ROOT, "extends", "ext_combat", "battle", "actions.py"),
            encoding="utf-8").read()
_bad = re.findall(r'get\("mult", 1\.0\)\s*or\s*1\.0', _src)
check("源码·段倍率读点已无 `or 1.0` 形态", not _bad, "hits=%r" % (_bad,))

print("\n== 结果：通过 %d / 共 %d ==" % (PASS, PASS + FAIL))
if FAIL:
    for _f in FAILURES:
        print("  FAIL: %s" % _f)
    sys.exit(1)
print("全绿 ✅")
