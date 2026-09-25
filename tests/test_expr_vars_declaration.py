#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：表达式**变量表**归内容侧声明（E4）—— 两态 + fail-closed + 反证。

为什么要它
------------------------------------------------------------------
E4 之前：`saintess_engine/expr/__init__.py` 自带 `VARIABLE_WHITELIST`（13 个变量名）+
`_VAR_CN`（中文显示名） ⇒ 引擎认得「一款游戏该有哪些变量」，换游戏就得改引擎。
E4 之后：引擎只留**读口**（`declared_vars()` / `variable_names()` / `labels_of()`），
表由内容侧 `config.mount(expr_vars_fn=...)` 声明；不装配 ⇒ 整表取 `_DEFAULT_EXPR_VARS`
（= 历史那一份，逐条相同 ⇒ 一字不变）。E4 车道交付时**没有常驻门禁**（只有一次性探针），
本文件补上 —— 不然「引擎又悄悄认回几个变量名」这种事没人拦。

判据
------------------------------------------------------------------
① 默认态：13 个名字 + 逐条显示名/来源与历史一致（`crit_mult` = 常量 1.5 ·
   `target_max_hp` 有 `else` 回落）。
② 声明态：换一张表 = 换一套变量集，引擎代码零改动（旧变量名不再出现在 `build_vars` 结果里）。
③ fail-closed：装了声明口却给不出可用表 ⇒ 抛 `EngineNotConfigured`，**不**静默退回默认表。
④ 反证：旧名 `VARIABLE_WHITELIST` 作为**名字**在引擎源码里零出现；
   声明口 `expr_vars_fn` 必须真在 `config._HOOKS` 白名单里（不在 ⇒ `mount` 会被静默忽略）。
⑤ 现场恢复：本文件跑完不许留下被改动的全局 hook。

跑法：`python tests/test_expr_vars_declaration.py`；退出码 0 = 全绿 · 1 = 有失败。
"""
import ast
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from saintess_engine import config as _cfg                       # noqa: E402
from saintess_engine import expr as EX                           # noqa: E402

passed = failed = 0
DETAIL = []

from _check import bind_check  # noqa: E402

check = bind_check(globals(), "passed", "failed", "DETAIL")

#: 历史白名单的 13 个名字（旧 `VARIABLE_WHITELIST` 逐字）
HISTORIC_NAMES = ("atk", "matk", "def", "mdef", "max_hp", "hp", "spd", "crit",
                  "player_lv", "skill_lv", "crit_mult", "target_max_hp", "base")


def _mount(fn):
    _cfg.mount(expr_vars_fn=fn)


def _restore():
    _cfg.set_hook("expr_vars_fn", None)


def _raises(fn):
    """跑一个函数，返回 (是否抛, 异常)"""
    try:
        fn()
    except BaseException as e:                                   # noqa: BLE001
        return True, e
    return False, None


# ---------------------------------------------------------------- ① 默认态
print("【1. 默认态（不装配）：13 个名字 + 逐条与历史一致】")
_restore()
d = EX.declared_vars()
check("declared_vars() 就是默认表本身（未装配不复制、不改造）", d == EX._DEFAULT_EXPR_VARS)
check("名字顺序与历史白名单逐个相同", tuple(d) == HISTORIC_NAMES, repr(tuple(d)))
check("每一条都有 source（表结构完整）", all(isinstance(v.get("source"), dict) for v in d.values()))
check("每条都有 label（历史中文显示名）", all(v.get("label") for v in d.values()))
check("crit_mult = 常量 1.5（原写死在 build_vars 里）",
      d["crit_mult"]["source"] == {"from": "const", "value": 1.5}, repr(d["crit_mult"]["source"]))
check("target_max_hp 带 else 回落（原来的 `target_max_hp or stats[max_hp]`）",
      d["target_max_hp"]["source"].get("else") == {"from": "stat", "key": "max_hp"},
      repr(d["target_max_hp"]["source"]))
v = EX.build_vars({"atk": 11, "matk": 12, "def": 13, "mdef": 14, "max_hp": 300, "hp": 250,
                   "spd": 15, "crit": 0.2}, player_lv=7, skill_lv=3, base=1.25)
check("build_vars 的键集 = 当前变量表（不是写死的集合）", tuple(v) == HISTORIC_NAMES, repr(tuple(v)))
check("stat 来源取值正确", (v["atk"], v["hp"], v["max_hp"], v["spd"]) == (11, 250, 300, 15), repr(v))
check("input 来源取值正确", (v["player_lv"], v["skill_lv"], v["base"]) == (7, 3, 1.25), repr(v))
check("const 来源取值正确", v["crit_mult"] == 1.5, repr(v["crit_mult"]))
check("target_max_hp 没给 ⇒ 回落 stats[max_hp]", v["target_max_hp"] == 300, repr(v["target_max_hp"]))
v2 = EX.build_vars({"max_hp": 300}, target_max_hp=99)
check("target_max_hp 给了 ⇒ 用它", v2["target_max_hp"] == 99, repr(v2["target_max_hp"]))
check("translate_expr 用默认表的中文名",
      EX.translate_expr("atk*0.8 + player_lv*5") == "攻击×0.8 + 玩家等级×5",
      EX.translate_expr("atk*0.8 + player_lv*5"))
check("translate_expr 保括号（源码里有括号才出括号）",
      EX.translate_expr("(atk*0.8 + player_lv*5) * (1 + skill_lv*0.1)")
      == "(攻击×0.8 + 玩家等级×5) × (1 + 技能等级×0.1)",
      EX.translate_expr("(atk*0.8 + player_lv*5) * (1 + skill_lv*0.1)"))
check("labels_of() 覆盖全部 13 条", set(EX.labels_of()) == set(HISTORIC_NAMES), repr(sorted(EX.labels_of())))

# ---------------------------------------------------------------- ② 声明态
print("\n【2. 声明态：换一张表 = 换一套变量集（引擎零改动）】")
_mount(lambda: {"pow": {"label": "威力", "source": {"from": "stat", "key": "atk"}},
                "leg": {"label": "腿力", "source": {"from": "const", "value": 2}}})
check("variable_names() 跟声明走", EX.variable_names() == ("pow", "leg"), repr(EX.variable_names()))
vb = EX.build_vars({"atk": 7, "hp": 999})
check("build_vars 只出声明过的变量（历史 13 个不再出现）", tuple(vb) == ("pow", "leg"), repr(tuple(vb)))
check("stat 来源按声明的 key 取值", vb["pow"] == 7, repr(vb))
check("const 来源取值", vb["leg"] == 2, repr(vb))
check("新变量能真参与表达式求值",
      abs(EX.eval_expr(EX.compile_expr("pow + leg"), vb) - 9) < 1e-9)
check("translate_expr 用声明表的中文名", EX.translate_expr("pow*2 + leg") == "威力×2 + 腿力",
      EX.translate_expr("pow*2 + leg"))
check("labels_of() 跟声明走", EX.labels_of() == {"pow": "威力", "leg": "腿力"}, repr(EX.labels_of()))
_restore()

# ---------------------------------------------------------------- ③ fail-closed
print("\n【3. fail-closed：声明了但坏 ⇒ 抛 EngineNotConfigured（不静默退回默认表）】")
for label, bad in (("返回 None", lambda: None),
                   ("返回空 dict", lambda: {}),
                   ("返回非 dict（列表）", lambda: ["atk"]),
                   ("条目不是 dict", lambda: {"x": "atk"}),
                   ("条目缺 source", lambda: {"x": {"label": "甲"}}),
                   ("source 类别不认", lambda: {"x": {"source": {"from": "lvl"}}}),
                   ("else 里类别不认", lambda: {"x": {"source": {"from": "input", "key": "base",
                                                                 "else": {"from": "nope"}}}})):
    _mount(bad)
    raised, err = _raises(EX.declared_vars)
    ok = raised and isinstance(err, _cfg.EngineNotConfigured)
    check("坏声明「%s」⇒ 抛 EngineNotConfigured" % label, ok, repr(err))
    raised2, err2 = _raises(lambda: EX.build_vars({}))
    check("  同一张坏表走 build_vars 也抛（不是只在读口抛）", raised2, repr(err2))
_restore()

# ---------------------------------------------------------------- ④ 反证
print("\n【4. 反证：旧名不许回归 · 声明口必须在 hook 白名单里（有牙）】")
check("expr_vars_fn 在 config._HOOKS 白名单里（不在 ⇒ mount 会被静默忽略）",
      "expr_vars_fn" in _cfg._HOOKS, "")
_names = []
for _dirpath, _dn, _fns in os.walk(os.path.join(ROOT, "saintess_engine")):
    for _fn in _fns:
        if not _fn.endswith(".py"):
            continue
        _p = os.path.join(_dirpath, _fn)
        try:
            _t = ast.parse(open(_p, encoding="utf-8").read(), filename=_p)
        except SyntaxError:
            continue
        for _n in ast.walk(_t):
            if isinstance(_n, ast.Name) and _n.id == "VARIABLE_WHITELIST":
                _names.append("%s:%d" % (os.path.relpath(_p, ROOT), _n.lineno))
            elif isinstance(_n, ast.Attribute) and _n.attr == "VARIABLE_WHITELIST":
                _names.append("%s:%d" % (os.path.relpath(_p, ROOT), _n.lineno))
check("旧名 VARIABLE_WHITELIST 作为名字零出现（只剩注释/docstring 可接受）", not _names, repr(_names[:4]))
_mount(lambda: {"x": {"source": {"from": "const", "value": 3}}})
check("有牙：换表后旧变量名真的不在了（build_vars 键集 = 声明键集）",
      tuple(EX.build_vars({"atk": 1})) == ("x",), repr(tuple(EX.build_vars({"atk": 1}))))
_restore()

# ---------------------------------------------------------------- ⑤ 现场恢复
print("\n【5. 现场恢复：本文件不许留下被改动的全局 hook】")
check("恢复后 declared_vars() 回到默认表", EX.declared_vars() == EX._DEFAULT_EXPR_VARS)
check("恢复后 variable_names() == 历史 13 名", EX.variable_names() == HISTORIC_NAMES, repr(EX.variable_names()))

print("\n" + "=" * 56)
print("通过 %d · 失败 %d" % (passed, failed))
for _d in DETAIL:
    print("  " + _d)
sys.exit(1 if failed else 0)
