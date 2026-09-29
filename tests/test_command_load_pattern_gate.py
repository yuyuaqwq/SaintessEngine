#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""常驻门禁：指令声明的**非法正则在装载期 fail-closed**（审计批次 4）。

跑法：python tests/test_command_load_pattern_gate.py

缺陷（本条修的真因）
------------------
`saintess_engine/host/runtime.py:150` 的线上装载是

    CommandRegistry(name=...).load(stack.command_declarations())

**不经过 `validate()`** —— 引擎另有 `build_registry()` 会 `validate()` 并抛，
但线上不走它。旧实现只在 `validate()`（**只报告**）里查非法正则，于是：

    load({"ok": {"patterns": ["^ok$"]}, "bad": {"patterns": ["^(unclosed"]}})

⇒ **boot 不抛、注册表照样装进 2 条**；而匹配期 `_any_hit()` 的
`except re.error: continue` 让那条声明**静默永不命中**
⇒ 玩家视角 = 「这条指令不存在」，启动期零痕迹、零日志。

修法 = 装载漏斗 `register()`（本类所有声明的唯一入口）逐条 `re.compile`，
失败点名抛 `ValueError`；**不给 `load()` 加宽容开关**（那会是第二个静默入口）。

判定
----
1. 非法正则 → 装载期点名抛，串里带 key / 正则原文 / 「非法」措辞
2. 抛在**装载期**，不是第一次匹配时（与旧实现的关键差别）
3. 坏声明抛错后**注册表未被污染**（没半装载进去）
4. 三种声明形态都受检（dict / 简写串 / 序列 / 单数别名键）
5. 非字符串正则项点名抛，不静默 `str()` 掉
6. **合法面逐字不变**：真实 orlandia 声明表照常装载、validate 仍为空、路由照常命中；
   合法空包不误伤；空 pattern 串不抛（归 validate() 报）
7. **源码面**：`register()` 的漏斗调用不得被摘掉（AST 静态自证）
8. **有牙反证**：把漏斗摘掉 ⇒ 判据必须转红；且**变异只落在副本上**（真仓零写入）
"""
from __future__ import annotations

import ast
import io
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (os.path.join(_ROOT, "tests"), _ROOT, os.path.join(_ROOT, "extends")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ★ 反证子进程必须把**副本**的 saintess_engine 顶到最前，且必须插在
#   下面任何 import **之前** —— 否则真仓的 registry 先被 import 进 sys.modules，
#   变异施加了也测不到（实测踩过：反证报 STILL_RAISES，白跑一轮）。
_SHADOW = os.environ.get("PATTERN_GATE_SHADOW")
if _SHADOW and _SHADOW not in sys.path:
    sys.path.insert(0, _SHADOW)

from _check import bind_check                                    # noqa: E402


FAILS: list = []
PASS = 0
check = bind_check(globals(), "PASS", "FAIL", "FAILS")

from saintess_engine.command.registry import CommandRegistry     # noqa: E402

_REG = os.path.join(_ROOT, "saintess_engine", "command", "registry.py")
BROKEN = "^(unclosed"
MUTANT = "        _reject_bad_patterns(spec.patterns, spec.key)"


def _loads(data):
    return CommandRegistry(name="t").load(data)


print("\n【1. 装载期 fail-closed（缺陷本体）】")
try:
    _loads({"ok": {"patterns": ["^ok$"]}, "bad": {"patterns": [BROKEN]}})
    check("非法正则 → 装载期抛（不是静默装进注册表）", False, "load() 没抛")
except ValueError as e:
    check("非法正则 → 装载期抛", True)
    check("错误串点名声明 key", "bad" in str(e), str(e)[:70])
    check("错误串带正则原文（可定位到哪一行写错）", BROKEN in str(e), str(e)[:70])
    check("错误串用「非法」措辞（与 validate() 同口径）", "非法" in str(e), str(e)[:70])

print("\n【2. 抛在装载期，不是第一次匹配时】")
r = CommandRegistry(name="t")
try:
    r.register({"key": "ok", "patterns": ["^ok$"]})
    check("合法声明经 register 正常登记", len(r.specs()) == 1, r.specs())
except Exception as e:                                             # noqa: BLE001
    check("合法声明经 register 正常登记", False, repr(e))
try:
    r.register({"key": "bad", "patterns": [BROKEN]})
    check("非法正则经 register 立刻抛（还没到匹配期）", False, "register() 没抛")
except ValueError:
    check("非法正则经 register 立刻抛（还没到匹配期）", True)
check("抛错后注册表未被污染（坏声明没半装载进去）",
      [s.key for s in r.specs()] == ["ok"], [s.key for s in r.specs()])

print("\n【3. 四种声明形态都受检】")
for _label, _data in (
        ("简写形态 {key: 正则}", {"short": BROKEN}),
        ("序列形态 [{key, patterns}]", [{"key": "seq", "patterns": [BROKEN]}]),
        ("单数别名键 pattern", {"key": "strp", "pattern": BROKEN}),
        ("别名键 regex", {"key": "rx", "regex": BROKEN}),
):
    try:
        _loads(_data)
        check(_label + " 同样受检", False, "没抛")
    except ValueError:
        check(_label + " 同样受检", True)

print("\n【4. 非字符串正则项点名抛（不静默 str() 掉）】")
# ★ 走**可达路径**：`from_dict` 的既有口径是把 patterns 逐个 `str()`（声明层容错，
#   只有 `visible` / `bind` 是 fail-closed），所以走装载表形态拿不到非字符串项；
#   能把非字符串 patterns 送进漏斗的是**直接构造 CommandSpec** 这条路。
from saintess_engine.command.registry import CommandSpec        # noqa: E402
try:
    CommandRegistry(name="t").register(CommandSpec(key="n", patterns=(5,)))
    check("非字符串正则 → 点名抛（不静默 str() 掉）", False, "没抛")
except TypeError as e:
    check("非字符串正则 → 点名抛（不静默 str() 掉）", True, repr(e)[:60])
    check("非字符串正则在错误串里点名声明 key", "n" in str(e), str(e)[:60])
check("声明层既有容错口径未动：patterns 里的数字仍按 str() 收（from_dict 口径不变）",
      CommandSpec.from_dict({"key": "z", "patterns": [5]}).patterns == ("5",),
      CommandSpec.from_dict({"key": "z", "patterns": [5]}).patterns)

print("\n【5. 合法面逐字不变（收紧不得误伤）】")
check("合法空包正常装载（0 条声明，不抛）", len(_loads({}).specs()) == 0)
check("空 pattern 串不抛（由 validate() 报「未声明任何正则」，不在漏斗）",
      len(_loads({"e": {"patterns": [""]}}).specs()) == 1)
good = _loads({"go": {"patterns": [r"^go(?:\s+(\w+))?$"], "desc": "走", "category": "移动"}})
check("合法声明照常装出", good.get("go").desc == "走", good.get("go"))
check("合法声明照常命中", good.first_hit("go north") is not None)
check("合法声明的未命中面照常为空", good.first_hit("看") is None)

_REAL = os.path.join(_ROOT, "games", "orlandia", "content", "data", "commands.json")
if os.path.exists(_REAL):
    d = json.load(io.open(_REAL, encoding="utf-8"))
    reg = _loads(d)
    check("真实 orlandia 声明表照常装载（条数逐条对得上）",
          len(reg.specs()) == len(d), (len(reg.specs()), len(d)))
    check("真实声明表 validate 仍为空（收紧不制造新告警）",
          reg.validate() == [], reg.validate()[:3])
    _hit = reg.first_hit("技能升级 烈焰斩", visible_only=True)
    check("真实声明表路由照常命中",
          _hit is not None and _hit.key == "skill_upgrade", _hit)
else:
    check("真实 orlandia 声明表存在（扫描面非空，防恒绿）", False, _REAL)

print("\n【6. 源码面：漏斗不得被摘掉（AST 静态自证）】")
src = io.open(_REG, encoding="utf-8").read()
check("★ 真仓守卫调用在位（先记下，改完后面再核）", MUTANT in src)
tree = ast.parse(src)
_reg_fn = None
for _n in ast.walk(tree):
    if (isinstance(_n, ast.FunctionDef) and _n.name == "register"
            and _n.args.args and _n.args.args[0].arg == "self"):
        _reg_fn = _n
        break
check("找得到 CommandRegistry.register", _reg_fn is not None)
if _reg_fn is not None:
    _calls = [n.func.id for n in ast.walk(_reg_fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    check("register() 调了非法正则守卫 _reject_bad_patterns",
          "_reject_bad_patterns" in _calls, _calls)
    _raises = [n for n in ast.walk(_reg_fn) if isinstance(n, ast.Raise)]
    check("register() 自身有 raise（不是只靠下游抛）", len(_raises) >= 1, len(_raises))

print("\n【7. 有牙反证：把漏斗摘掉 → 本门禁必须转红】")

# ★ 用**进程内**换掉漏斗函数，而不是起子进程去改副本：
#   上一版走「子进程 + 影子树」，实测反证报 STILL_RAISES —— 子进程照样 import 到真仓的
#   registry（sys.path 装配顺序问题），变异施加了却测不到，白跑一轮；
#   而「子进程跑本门禁 ⇒ 本门禁又跑子进程」的自举形态，正是本车道上一轮炸出
#   28 个残留进程、差点把生产码守卫删掉提交进去的那次事故的成因。
#   ⇒ 现在**完全不起子进程**（无自举、无残留进程、真仓零写入）。
#   进程内换掉模块属性：同一份代码、同一进程，**真仓零写入、无子进程、无残留**。
import saintess_engine.command.registry as _R            # noqa: E402

_orig = _R._reject_bad_patterns
try:
    _R._reject_bad_patterns = lambda *a, **k: None        # 模拟「漏斗被摘掉」
    _silent = False
    try:
        _loads({"bad": {"patterns": [BROKEN]}})
        _silent = True
    except ValueError:
        _silent = False
    check("反证：摘掉漏斗后**静默装进注册表**（证明判据真在钉这件事，不是恒绿）",
          _silent, "摘掉漏斗后仍抛 ⇒ 抛的不是这个漏斗，判据钉错了东西")
finally:
    _R._reject_bad_patterns = _orig                    # 必定还原（异常路径也还原）

check("★ 还原后守卫仍在（反证没留下残态）",
      _R._reject_bad_patterns is _orig)
try:
    _loads({"bad2": {"patterns": [BROKEN]}})
    check("★ 还原后缺陷形状重新点名抛（反证收干净了）", False, "还原后没抛")
except ValueError:
    check("★ 还原后缺陷形状重新点名抛（反证收干净了）", True)
check("★ 真仓零写入：守卫调用仍在源码里",
      MUTANT in io.open(_REG, encoding="utf-8").read())

print("\n结果：通过 %d / %d" % (PASS, PASS + len(FAILS)))
sys.exit(1 if FAILS else 0)
