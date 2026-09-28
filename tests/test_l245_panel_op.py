# -*- coding: utf-8 -*-
"""L245 门禁：面板折算的减益口径**只认 `op`**，条目名不参与判定（引擎零游戏名词）。

背景
----
`ext_combat/battle/stats.py::_apply_effects` 的面板快照型折算原判据是::

    if key == "spd_down" or _op == "reduce":
        st[entry_stat] = int(st[entry_stat] * (1.0 - min(float(entry_mult), 0.9)))
    elif _op == "add": ...
    else:              st[entry_stat] = int(st[entry_stat] * float(entry_mult))

它把两件事混成一条：
① **这个条目是不是减益**（`key == "spd_down"` —— 硬编码游戏名词，违反准则 1）
② **乘区本身是不是「减掉的比例」**（`_op == "reduce"` —— 这才是口径）

而 `spd_down` 的**全部生产写口**（`games/orlandia/content/mech/class_mech.py:1527`、
`we_procs.py:700`、`:1267`）传的都是 `op:"mul", mult:1-pct` ——
`mult` **已经是「×几」**（0.7 = 减速 30%）。原分支又取一次 `1.0-mult`：

| 减速 | 写口 `mult` | 玩家应得 spd | 原实现实跑 | 错成 |
|---|---|---|---|---|
| 10% | 0.90 | 90 | 10 | -90% |
| 30% | 0.70 | 70 | 30 | -70% |
| 50% | 0.50 | 50 | 50 | 对（×0.5 两次同值）|
| 6%  | 0.94 | 94 |  6 | -94% |

即「减速越弱、扣得越狠」——**反向**。真源侧已有反证钉着 `mult=0.7` 这一形态
（`games/orlandia/tests/test_passive_p6.py:113` 「spd_down 减速 30%（spd×0.7）」）。

本门禁钉四件事（**缺一即红**）
--------------------------------
A. **减益写口（`op:"mul"`, `mult=1-pct`）按 `mult` 直乘** —— 玩家可见行为修正确。
B. **`op:"reduce"` 那一支语义不变** —— `mult` 确实是「减掉的比例」时仍走 `1-mult`
   （本门禁不删这一支，只把它从「按条目名触发」改成「按 op 触发」）。
C. **增益两支零变化** —— `add`（加值）与 `mul`（放大）逐值不变。
D. **源码判据里零游戏条目名** —— `stats.py` 不再出现 `"spd_down"`
   （这是准则 1 的可执行形态；`docs/` 里的举例不算）。

跑法：python tests/test_l245_panel_op.py
"""
import io
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, FW_ROOT)
sys.path.insert(0, os.path.join(FW_ROOT, "extends"))

from extends.ext_combat.battle.stats import _apply_effects  # noqa: E402

PASS = 0
FAIL = 0
STATS_PY = os.path.join(FW_ROOT, "extends", "ext_combat", "battle", "stats.py")


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s" % label)
    else:
        FAIL += 1
        print("  [FAIL] %s %s" % (label, extra))


def fold(entry, base=100):
    """折算单个面板条目，返回 stat 终值。"""
    st = {"spd": base, "atk": base, "crit": 0.05, "def": base}
    _apply_effects(st, {"effects": {"probe_key": entry}})
    return st


print("== A. 减益写口 op=mul / mult=1-pct：按 mult 直乘（减速越弱扣得越轻）==")
for pct in (0.06, 0.10, 0.30, 0.50, 0.80):
    got = fold({"stat": "spd", "op": "mul", "mult": round(1.0 - pct, 4)})["spd"]
    want = int(100 * (1.0 - pct))
    check("减速 %d%% ⇒ spd %d" % (int(pct * 100), want), abs(got - want) <= 1,
          "实跑 spd=%d" % got)

print("== B. op=reduce（mult 本身就是减掉的比例）语义不变 ==")
for red in (0.30, 0.60, 0.90):
    got = fold({"stat": "atk", "op": "reduce", "mult": red})["atk"]
    want = int(100 * (1.0 - red))
    check("reduce %d%% ⇒ atk %d" % (int(red * 100), want), abs(got - want) <= 1,
          "实跑 atk=%d" % got)

print("== C. 增益两支零变化 ==")
got = fold({"stat": "crit", "op": "add", "mult": 0.3})["crit"]
check("add +0.3 ⇒ crit 0.35", abs(got - 0.35) < 1e-9, "实跑 %r" % got)
got = fold({"stat": "atk", "op": "mul", "mult": 1.3})["atk"]
check("mul ×1.3 ⇒ atk 130", got == 130, "实跑 %d" % got)
got = fold({"stat": "atk", "op": "mul", "mult": 0.7})["atk"]
check("mul ×0.7（增益侧同形）⇒ atk 70", got == 70, "实跑 %d" % got)

print("== D. 源码判据零游戏条目名（准则 1 可执行形态）==")
src = io.open(STATS_PY, encoding="utf-8").read()
# 只看 _apply_effects 函数体（判据就在那儿）
fn_start = src.find("def _apply_effects")
fn_src = src[fn_start:src.find("\ndef ", fn_start + 10)] if fn_start >= 0 else ""
# 注释里引用了旧写法（那是**取证记录**，不是判据）⇒ 扫条目名前先剥掉注释
fn_code = re.sub(r"#.*", "", fn_src)
check("stats.py 定位到 _apply_effects", bool(fn_src))
for name in ("spd_down", "death_guard", "mortal_wound", "atk_down", "def_down"):
    check("_apply_effects 判据内零 %r" % name, ('"%s"' % name) not in fn_code,
          "仍硬编码游戏条目名")
check("判据形如 `if _op == \"reduce\"`", 'if _op == "reduce":' in fn_code)

print("\n结果: %d 通过 / %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
