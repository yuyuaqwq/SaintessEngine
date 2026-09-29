#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""常驻门禁：指令正则的第二条编译入口也 fail-closed（审计批次 1 · 同 L5577 同族）。

跑法：python tests/test_command_patternset_failclosed.py

缺陷（本条修的真因）
------------------
上一笔（5db0d12）把非法正则的 fail-closed 挂到装载漏斗
CommandRegistry.register() 上，docstring 写「本类所有声明的唯一入口」。
逐条核实后发现漏了一半，两处漏法都是玩家可见的静默失效：

(1) command/router.PatternSet 是独立于注册表的第二条编译入口。
    它被宿主 host/_platform._GameCmdFilter（停服维护 gate 的
    「是不是游戏指令」过滤器）直接使用，而原写法是
    except re.error: continue —— 非法正则被静默丢弃。
    玩家视角：那条指令在过滤器眼里根本不是游戏指令 ⇒
    停服期间它拦不住、日常消息也走不到它的 handler，零异常零日志。

(2) 装载漏斗只逐条编译，而宿主过滤器吃的是 spec.combined() 这合并串。
    combine_patterns 把多条用 (?:...) 串起来 ⇒ 同名命名组重复会让合并串
    re.error，而每一条单独编译都是绿的（实测：两条 (?P<act>攻击) /
    (?P<act>防御) 逐条合法，合并后 redefinition of group name）。
    ⇒ 那种声明能过 (1) 之外的装载漏斗、装载成功，却死在 PatternSet
    那条独立入口上被静默丢弃。★ 这是本条比上一笔更值钱的一半：
    上一笔的判据对它完全无感。

修法（两处各自守自己那一口，不复用同一份实现）
----------------------------------------------
- router.PatternSet.patterns() 逐条编译、失败点名抛（口径沿用注册表同形串）。
- 注册表漏斗在逐条之后再验合并串，失败点名抛并说明「单条各自合法」。
★ 不共用一份实现：registry 与 router 互不 import，但仓内存在
  「单文件装载」用法的判据，跨模块顶层 import 会打红它们 ⇒
  两处各自守，错误串保持逐字同形便于对读。

判定
----
1. 非法正则 ⇒ PatternSet 点名抛（串里带正则原文 + 「非法」措辞）
2. 抛在编译期（patterns()），不是第一次 matches() 时
3. 逐条合法但合并后非法 ⇒ 注册表漏斗点名抛（★ 上一笔的判据对此无感）
4. 合法面逐字不变：真实 orlandia 声明表 196 条照常编译（零丢弃）、
   路由照常命中、validate 仍为空；单条声明不因新增合并校验重复报错
5. 空串不抛（归既有「未声明任何正则」那条判据）
6. 源码面 AST 自证：PatternSet.patterns 里不得再有吞 re.error 的 continue
7. 有牙反证：摘掉两处守卫 ⇒ 判据必须转红；变异只落模块属性上、
   真仓零写入、finally 必定还原
"""
from __future__ import annotations

import ast
import io
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (os.path.join(_ROOT, "tests"), _ROOT, os.path.join(_ROOT, "extends")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _check import bind_check                                    # noqa: E402

FAILS: list = []
PASS = 0
check = bind_check(globals(), "PASS", "FAIL", "FAILS")

from saintess_engine.command.registry import CommandRegistry     # noqa: E402
from saintess_engine.command import registry as _REG_M          # noqa: E402
from saintess_engine.command.router import PatternSet            # noqa: E402

BROKEN = "^(unclosed"
DUP_A = r"^(?P<act>攻击)$"
DUP_B = r"^(?P<act>防御)$"
_GOOD = "^背包$"
_ROUTER = os.path.join(_ROOT, "saintess_engine", "command", "router.py")
_REG = os.path.join(_ROOT, "saintess_engine", "command", "registry.py")

print("== A. PatternSet 非法正则 fail-closed ==")
_raised = None
try:
    PatternSet(lambda: [_GOOD, BROKEN]).patterns()
except ValueError as e:
    _raised = e
check("A1 非法正则 → 点名抛（不是静默丢弃）", _raised is not None, "未抛")
check("A2 抛错带正则原文 + 「非法」措辞",
      _raised is not None and BROKEN in str(_raised) and "非法" in str(_raised),
      str(_raised) if _raised else "无异常")

_raised2 = None
try:
    PatternSet(lambda: [BROKEN]).matches(BROKEN)     # 旧实现在这里才第一次碰到正则
except ValueError as e:
    _raised2 = e
check("A3 直接 matches() 也当场抛（不推迟到别处）", _raised2 is not None, "未抛")
check("A4 抛错点名的是这条正则", _raised2 is not None and BROKEN in str(_raised2))

_nc = None
try:
    PatternSet(lambda: [123]).patterns()
except TypeError as e:
    _nc = e
check("A5 非字符串正则项点名抛（不静默 str 掉）", _nc is not None, "未抛")

print("== B. 抛错不留毒缓存 ==")
_ps = PatternSet(lambda: [BROKEN])
try:
    _ps.patterns()
except ValueError:
    pass
check("B1 修好后同形状 PatternSet 逐条判定不受污染", len(PatternSet(lambda: [_GOOD]).patterns()) == 1)
_ps.reset()
_rebad = False
try:
    _ps.patterns()
    _rebad = False
except ValueError:
    _rebad = True
check("B2 reset() 后重编译仍点名抛（没被毒缓存永久卡死或静默放过）", _rebad)

print("== C. 合并后非法（★ 上一笔的判据对此完全无感）==")
_c = None
try:
    CommandRegistry(name="t").load({"skill": {"patterns": [DUP_A, DUP_B]}})
except ValueError as e:
    _c = e
check("C1 逐条合法但合并后非法 → 装载期点名抛", _c is not None, "未抛（漏斗没管合并串）")
check("C2 抛错点名合并串 + 说明「合并」",
      _c is not None and "合并" in str(_c) and DUP_A in str(_c), str(_c) if _c else "无异常")
check("C3 错误串点名 key", _c is not None and "skill" in str(_c))
_d = None
try:
    CommandRegistry(name="t").load({"bad": {"patterns": [BROKEN]}})
except ValueError as e:
    _d = e
check("C4 逐条非法仍走原来那条措辞（不因新增合并校验而改口）",
      _d is not None and "正则非法" in str(_d) and "合并" not in str(_d),
      str(_d) if _d else "无异常")

print("== D. 合法面逐字不变 ==")
_dj = os.path.join(_ROOT, "games", "orlandia", "content", "data", "commands.json")
if not os.path.isfile(_dj):
    _dj = os.path.join(_ROOT, "games", "orlandia", "framework", "games", "orlandia",
                       "content", "data", "commands.json")
check("D0 真实 commands.json 可定位（门禁不许空转恒绿）", os.path.isfile(_dj), _dj)
if os.path.isfile(_dj):
    with io.open(_dj, encoding="utf-8") as f:
        decls = json.load(f)
    _pats = []
    for _k, _v in decls.items():
        if isinstance(_v, dict):
            _pats += [p for p in (_v.get("patterns") or []) if p]
        elif isinstance(_v, str):
            _pats.append(_v)
    _got = PatternSet(lambda: _pats).patterns()
    check("D1 真实声明表 PatternSet 零丢弃（编译条数 == 输入条数）",
          len(_got) == len(_pats), "编译 %d / 输入 %d" % (len(_got), len(_pats)))
    try:
        _reg = CommandRegistry(name="real").load(decls)
        check("D2 真实声明表照常装载 + validate() 仍为空", _reg.validate() == [],
              str(_reg.validate())[:200])
        _hit = [t for t in ("背包", "技能列表", "装备重锻", "公会任命", "属性", "商店")
                if _reg.first_hit(t, visible_only=True)]
        check("D3 路由照常命中（逐条点名）", len(_hit) == 6, "命中 %d/6" % len(_hit))
    except Exception as e:                                    # noqa: BLE001
        check("D2 真实声明表照常装载 + validate() 仍为空", False, repr(e))
    try:
        CommandRegistry(name="t").load({"solo": {"patterns": [_GOOD]}})
        check("D4 单条声明不因新增的合并校验重复报错", True)
    except Exception as e:                                    # noqa: BLE001
        check("D4 单条声明不因新增的合并校验重复报错", False, repr(e))

print("== E. 空串是合法零宽正则（不许被当成非法丢掉）==")
# ★ 自抓的一处真回归：第一版这里写的是「空串跳过」，结果把 **合法零宽正则**
#   （re.compile('') 合法、skip_empty 开关正是为它准备的）整个丢掉 ⇒
#   test_command 的「skip_empty=False 时零宽正则会命中」当场红。
#   ⇒ 判据改成钉**真实语义**：空串要**留下**，交给 matches_any 的 skip_empty 判。
try:
    _empty_kept = PatternSet(lambda: [""]).patterns()
    check("E1 空串**保留**（合法零宽正则，不当非法丢掉）",
          len(_empty_kept) == 1, "编译出 %d 条" % len(_empty_kept))
    check("E2 零宽语义由 skip_empty 决定（默认不算命中）",
          not PatternSet(lambda: [""]).matches("随便聊聊"))
    check("E3 skip_empty=False 时零宽正则命中（钉住既有语义不被改掉）",
          PatternSet(lambda: [""]).matches("随便聊聊", skip_empty=False))
except Exception as e:                                        # noqa: BLE001
    check("E1 空串**保留**（合法零宽正则，不当非法丢掉）", False, repr(e))
_et = None
try:
    CommandRegistry(name="t").load({"blank": {"patterns": [""]}})
except ValueError as e:
    _et = e
check("E4 空串不触发合并校验的报错（combined 为空串）",
      _et is None or "合并" not in str(_et), str(_et) if _et else "")

print("== F. 源码面 AST 自证 ==")
def _swallows(fn_node):
    for _n in ast.walk(fn_node):
        if not isinstance(_n, ast.Try):
            continue
        for _h in _n.handlers:
            _t = _h.type
            _names = [_t.id] if isinstance(_t, ast.Name) else (
                [_t.attr] if isinstance(_t, ast.Attribute) else [])
            if not any("error" in x for x in _names):
                continue
            if any(isinstance(_b, ast.Continue) for _b in _h.body):
                return True
    return False

_src = io.open(_ROUTER, encoding="utf-8").read()
_tree = ast.parse(_src)
_cls = next((n for n in _tree.body
             if isinstance(n, ast.ClassDef) and n.name == "PatternSet"), None)
check("F1 能定位到 PatternSet 类（门禁不许空转恒绿）", _cls is not None)
_fn = next((n for n in (_cls.body if _cls else [])
            if isinstance(n, ast.FunctionDef) and n.name == "patterns"), None)
check("F2 能定位到 patterns() 方法", _fn is not None)
check("F3 patterns() 不再静默吞 re.error（无 except re.error: continue）",
      _fn is not None and not _swallows(_fn))
check("F4 patterns() 自己必须带 raise（真在点名，不是删了检查）",
      _fn is not None and any(isinstance(n, ast.Raise) for n in ast.walk(_fn)))
_reg_src = io.open(_REG, encoding="utf-8").read()
check("F5 注册表漏斗验了合并串（源码里真的在验）",
      "combine_patterns(patterns)" in _reg_src and "合并正则非法" in _reg_src)

print("== G. 有牙反证（变异只落模块属性，真仓零写入）==")
_orig_reject = _REG_M._reject_bad_patterns
try:
    _REG_M._reject_bad_patterns = lambda *a, **k: None
    _s1 = False
    try:
        CommandRegistry(name="t").load({"bad": {"patterns": [BROKEN]}})
        _s1 = True
    except ValueError:
        _s1 = False
    check("G1 摘掉注册表漏斗 → 逐条非法被静默装进（证明判据真在钉这件事）",
          _s1, "摘掉后仍抛 ⇒ 抛的不是这个漏斗，判据钉错了东西")
    _s2 = False
    try:
        CommandRegistry(name="t").load({"skill": {"patterns": [DUP_A, DUP_B]}})
        _s2 = True
    except ValueError:
        _s2 = False
    check("G2 摘掉漏斗后合并非法也静默通过（正是本条修的那一半）", _s2)
finally:
    _REG_M._reject_bad_patterns = _orig_reject
check("G3 还原后守卫仍在（反证没留下残态）", _REG_M._reject_bad_patterns is _orig_reject)

_orig_patterns = PatternSet.patterns
def _old_patterns(self):
    if self._compiled is None:
        self._compiled = []
        for pat in self._get() or ():
            try:
                self._compiled.append(re.compile(pat))
            except re.error:
                continue
    return self._compiled
try:
    PatternSet.patterns = _old_patterns
    _s3 = False
    try:
        PatternSet(lambda: [BROKEN]).patterns()
        _s3 = True
    except ValueError:
        _s3 = False
    check("G4 换回旧实现 → 非法正则被静默丢弃（证明 A 段钉的是这条）",
          _s3, "旧实现竟然抛了 ⇒ 反证样本无效")
finally:
    PatternSet.patterns = _orig_patterns
_s4 = False
try:
    PatternSet(lambda: [BROKEN]).patterns()
    _s4 = True
except ValueError:
    _s4 = False
check("G5 还原后缺陷形状重新点名抛（反证收干净了）", not _s4)
check("G6 真仓零写入：两处守卫仍在源码里",
      "合并正则非法" in _reg_src and "指令正则非法" in _src)

print(chr(10) + "结果：通过 %d / %d" % (PASS, PASS + len(FAILS)))
sys.exit(1 if FAILS else 0)
