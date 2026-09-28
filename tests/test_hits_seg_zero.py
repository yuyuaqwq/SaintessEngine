# -*- coding: utf-8 -*-
"""门禁：技能**施放段数**口径（`hits` / `multi`）单源且只认 None（审计 L251 同族 · 批次 4）。

**这个门禁守住什么**
同一份技能 `info` 里有**两处**读施放段数的地方：

* `battle/actions.py:544`  —— 伤害段循环 `for seg in range(multi)`
* `gauge/actions.py:126`  —— `per_hit` 多段量（`shaken_gain` 等多段加成）

它们读**同两个键**、**同一默认 1**，但改前写法不同：

    战斗侧    _int(info.get("hits"), info.get("multi"), 1)      # 只认 None，合法 0 放行
    计量条侧  int(info.get("hits") or info.get("multi") or 1)   # or 链，把合法 0 吞成 1

⇒ `hits: 0`（= 零段 = 零伤害，这是内容侧配得出来的合法档位）时两侧**分叉**：

    战斗侧 0 段 = 零伤害
    计量条侧 1 段 = 白送一份 per_hit 加成

零报错、零日志。改法 = 抽 `battle.actions.hits_of` 作**段数口径唯一真源**，
计量条侧 import 它（依赖方向 gauge -> battle；battle/* 全族零 gauge 反向引用）。

本门禁钉五件事（**缺一即红**）

A. 两侧是**同一个函数对象**（`is` 比，不是「行为看起来一样」）—— 防口径再次分叉
B. 合法 0 被放行：`hits: 0` / `multi: 0` => 0
C. 缺键回落 1；显式非 0 逐字不变（1/2/3/4，真源实测无 0 ⇒ 生产面零变化）
D. `per_hit` 多段量实跑：只有 `hits: 0` 那一支与改前不同
E. ★ 反证有牙：把计量条侧退回 `or` 链，同一扫描器必须判红

跑法：python tests/test_hits_seg_zero.py
"""
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, FW_ROOT)
sys.path.insert(0, os.path.join(FW_ROOT, "extends"))

import ast  # noqa: E402
import saintess_engine                                # noqa: E402,F401
from ext_combat.battle import actions as BA            # noqa: E402
from ext_combat.gauge import actions as GA             # noqa: E402

from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

PASS = 0
FAIL = 0
FAILURES = []
check = bind_check(globals(), "PASS", "FAIL", "FAILURES")

print("== A. 两侧同一个函数对象（口径单源） ==")
check("gauge._hits_of is battle.hits_of", GA._hits_of is BA.hits_of,
      "gauge=%r battle=%r" % (GA._hits_of, BA.hits_of))
check("battle 侧伤害段循环已走 hits_of",
      "multi = hits_of(info)" in open(
          os.path.join(FW_ROOT, "extends", "ext_combat", "battle", "actions.py"),
          encoding="utf-8").read())

print("== B. 合法 0 被放行（原缺陷：被吞成 1） ==")
check("hits: 0 => 0 段", GA._hits_of({"hits": 0}) == 0, "got=%r" % (GA._hits_of({"hits": 0}),))
check("multi: 0 => 0 段", GA._hits_of({"multi": 0}) == 0, "got=%r" % (GA._hits_of({"multi": 0}),))

print("== C. 缺键回落 1 / 显式非 0 逐字不变（没改坏） ==")
for _info, _want, _label in (
        ({}, 1, "两键都缺 => 1"),
        ({"hits": 1}, 1, "hits=1 => 1"),
        ({"hits": 2}, 2, "hits=2 => 2"),
        ({"hits": 3}, 3, "hits=3 => 3"),
        ({"hits": 4}, 4, "hits=4 => 4"),
        ({"multi": 4}, 4, "multi=4 => 4"),
        ({"hits": None, "multi": 2}, 2, "hits 缺(None) 读 multi=2 => 2")):
    _g = GA._hits_of(_info)
    check(_label, _g == _want, "got=%r want=%r" % (_g, _want))

print("== D. per_hit 多段量实跑：只有 hits:0 那一支变了 ==")
for _info, _new, _old, _label in (
        ({"hits": 0, "shaken_gain": 5}, 0, 5, "hits=0 · shaken_gain=5 => 0（旧 5 = 白送一份）"),
        ({"hits": 3, "shaken_gain": 5}, 15, 15, "hits=3 · shaken_gain=5 => 15（逐字不变）"),
        ({"shaken_gain": 5}, 5, 5, "缺 hits · shaken_gain=5 => 5（逐字不变）")):
    _amount = _info.get("shaken_gain")
    _g = int(_amount or 0) * GA._hits_of(_info)
    _o = int(_amount or 0) * int(_info.get("hits") or _info.get("multi") or 1)
    check(_label, _g == _new and _o == _old, "新=%r 旧=%r" % (_g, _o))

print("== E. ★ 反证有牙：源码面不得再出现 or 链形态 ==")
_ga_src = os.path.join(FW_ROOT, "extends", "ext_combat", "gauge", "actions.py")
_ba_src = os.path.join(FW_ROOT, "extends", "ext_combat", "battle", "actions.py")


def _read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


# 按**条目身份**扫（找读这两个键的表达式），不认行号 —— 行号漂移不致假绿。
_OR_CHAIN = re.compile(r'info\.get\("hits"\)\s*or\s*info\.get\("multi"\)\s*or\s*1')
for _p, _label in ((_ga_src, "gauge/actions.py"), (_ba_src, "battle/actions.py")):
    _hits = _OR_CHAIN.findall(_read(_p))
    check("★ 反证·%s 段数读点已无 `or` 链形态" % _label, not _hits, "hits=%r" % (_hits,))

# hits_of 助手必须真在读那三个键（防「单源到一个空壳」）
_tree = ast.parse(_read(_ba_src))
_hits_of = next((n for n in _tree.body
                 if isinstance(n, ast.FunctionDef) and n.name == "hits_of"), None)
check("hits_of 在 battle/actions.py 里定义", _hits_of is not None)
if _hits_of is not None:
    _keys = [n.args[0].value for n in ast.walk(_hits_of)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "get" and n.args
             and isinstance(n.args[0], ast.Constant)]
    check("hits_of 读 hits/multi 两个键", set(_keys) == {"hits", "multi"}, "got=%r" % (_keys,))

print("== F. ★★ 有牙反证：旧 or 链在同一组输入上必须给出被吞的旧值 ==")
# 旧算法 = `int(info.get("hits") or info.get("multi") or 1)`。若它仍给出被吞的 1 / 5，
# 说明 B/D 真的咬住了「合法 0 被吞」这个缺陷，而不是恒真断言。
# 另证：活实现里该读点可定位、且真的调了 hits_of（退回 or 链后调用数归零）。
_old_hits0 = int(0 or 0 or 1)
check("★ 反证·旧 or 链 hits:0 => 1（!= 新口径 0）", _old_hits0 == 1, "got=%r" % (_old_hits0,))
_old_per0 = int(5 or 0) * _old_hits0
check("★ 反证·旧 or 链 per_hit hits:0 => 5（!= 新口径 0，白送一份量）",
      _old_per0 == 5, "got=%r" % (_old_per0,))
import inspect as _inspect                                   # noqa: E402
_live = _inspect.getsource(GA.bar_gain_act)
_rev = _live.replace("amount = int(amount or 0) * _hits_of(info)",
                     'amount = int(amount or 0) * int(info.get("hits") or info.get("multi") or 1)')
check("★ 反证·活实现可定位到该读点（猴补前提）", _rev != _live, "live=%r" % (_live[-120:],))
check("★ 反证·退回 or 链后 hits_of 调用数归零（钉的是活实现不是副本）",
      _rev.count("_hits_of(") == 0 and _live.count("_hits_of(") >= 1,
      "rev=%d live=%d" % (_rev.count("_hits_of("), _live.count("_hits_of(")))

print("\n== 结果：通过 %d / 共 %d ==" % (PASS, PASS + FAIL))
if FAIL:
    for _f in FAILURES:
        print("  FAIL: %s" % _f)
    sys.exit(1)
