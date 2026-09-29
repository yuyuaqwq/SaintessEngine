#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""常驻门禁：公式 `guard` 的键必须落在已声明的变量域里（审计 L995-4）。

跑法：python tests/test_formula_guard_domain_gate.py

背景
----
`_apply_guard`（`saintess_engine/formula/__init__.py`）的钳制循环第一句就是

    for name, g in guard.items():
        if name not in out:
            continue                       # ← 名字不存在就静默跳过

即 **`guard` 的键拼错 = 钳制样式写错 = 永不生效，且零报错**。
而装配期 V5（`_check_var_domain`）原先把 guard 的键**并进** `allowed`：

    allowed |= set((e.get("guard") or {}))

⇒ 等于**把打错的 guard 名当成合法名放行**。两处合起来构成一条完整的静默失效链：
装配期通过 → 运行期跳过 → 数值原样穿过。

实跑证据（台账 L995-4，本轮修复前）
--------------------------------
真实表 `F1_eff_def` 的 `pene_pct` 声明了 `guard: {"pene_pct": {"cap": 0.6}}`；
把 guard 的键拼成 `pene_pcts`（`vars`/`params` 里都没有这个名字）：

    修复前：装配期**通过**，运行期 `5.0` 原样穿过（钳制没生效）
    对照组：键拼对时 = `0.6`

判定
----
1. guard 键 ∈ `vars` ∪ `params`（**行为向**：打错的名字必须抛）
2. 拼对的 guard 键仍然正常装配（**收紧不得误伤合法声明**）
3. 合法 guard 真的在运行期生效（`cap` / `floor` 逐值钉死，防"只装配不钳制"）
4. 缺 guard 的条目逐字不变（老条目不许被这次收紧误伤）
5. **反证**：临时摘掉校验，判据必须转红 —— 证明它真在钉这件事
6. ★ **反面约束**：`guard` 键**不是**新变量，**不得**靠把它加进 `vars` 来"过门禁"
   —— 那是把静默失效换成了脏数据（本门禁第 1 条即为此设）
"""
from __future__ import annotations

import io
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "extends"))

from _check import bind_check                                    # noqa: E402
from saintess_engine.formula import FormulaTable                  # noqa: E402

FAILS: list = []
PASS = 0
check = bind_check(globals(), "PASS", "FAIL", "FAILS")

_SRC = os.path.join(_ROOT, "saintess_engine", "formula", "__init__.py")
_src = io.open(_SRC, encoding="utf-8").read()


def _tbl(guard, expr, variables, params=None, version=1, returns="number"):
    e = {"kind": "formula", "version": version, "returns": returns,
         "vars": list(variables), "expr": expr}
    if guard is not None:
        e["guard"] = guard
    if params:
        e["params"] = params
    return {"e1": e}


def _raises(table):
    """装配该表 → 返回 (是否抛, 错误串首段)。"""
    try:
        FormulaTable.from_decl(table)
        return False, ""
    except Exception as ex:                                  # noqa: BLE001
        return True, "%s: %s" % (type(ex).__name__, ex)


print("== A. guard 键必须落在已声明变量域（打错即抛）==")
_r, _m = _raises(_tbl({"def": {"cap": 0.6}, "pene_pcts": {"cap": 0.6}}, "def * 2", ["def"]))
check("guard 键拼错（pene_pcts 不在 vars/params）装配期抛错", _r, "拼错的 guard 名被放行了")

_r, _m = _raises(_tbl({"def": {"cap": 0.6}, "spd_": {"floor": 1.0}}, "def * 2", ["def"]))
check("guard 键拼错（spd_ 尾缀多一个下划线）装配期抛错", _r, "拼错的 guard 名被放行了")

_r, _m = _raises(_tbl({"not_declared": {"cap": 0.6}}, "def * 2", ["def"]))
check("guard 键完全未声明时抛错", _r, "未声明的 guard 名被放行了")

_r, _m = _raises(_tbl({"def": {"cap": 0.6}}, "def * 2", ["def"]))
check("★ 对照：guard 键拼对时**不得**抛（收紧不得误伤合法声明）", not _r, "got=%s" % _m)

_r, _m = _raises(_tbl({"spd": {"floor": 1.0}}, "spd * 2", ["atk"], {"spd": {"ref": "const.zero"}}))
check("★ 对照：guard 键落在 params 上合法（vars/params 同一口径）", not _r, "got=%s" % _m)


print("")
print("== B. 合法 guard 真的在运行期生效（cap / floor 逐值钉死）==")
_t = FormulaTable.from_decl(_tbl({"def": {"cap": 0.6}}, "def * 2", ["def"]))
check("cap 生效：def=5.0 → 0.6（乘 2 得 1.2）",
      abs(_t.eval("e1", {"def": 5.0}) - 1.2) < 1e-9,
      "got=%r" % _t.eval("e1", {"def": 5.0}))

_t = FormulaTable.from_decl(_tbl({"def": {"floor": 3.0}}, "def * 2", ["def"]))
check("floor 生效：def=1.0 → 3.0（乘 2 得 6.0）",
      abs(_t.eval("e1", {"def": 1.0}) - 6.0) < 1e-9,
      "got=%r" % _t.eval("e1", {"def": 1.0}))

_t = FormulaTable.from_decl(_tbl({"def": {"cap": 0.6}}, "def * 2", ["def"]))
check("cap 不误伤低于上限的值：def=0.1 → 0.2",
      abs(_t.eval("e1", {"def": 0.1}) - 0.2) < 1e-9,
      "got=%r" % _t.eval("e1", {"def": 0.1}))


print("")
print("== C. 无 guard 的老条目逐字不变（本次收紧不得误伤）==")
_r, _m = _raises(_tbl(None, "def * 2", ["def"]))
check("没有 guard 键的条目照常装配", not _r, "got=%s" % _m)
_t = FormulaTable.from_decl(_tbl(None, "def * 2", ["def"]))
check("没有 guard 键的条目求值不变（5.0 → 10.0）",
      abs(_t.eval("e1", {"def": 5.0}) - 10.0) < 1e-9,
      "got=%r" % _t.eval("e1", {"def": 5.0}))

_r, _m = _raises(_tbl({}, "def * 2", ["def"]))
check("guard 为空对象时照常装配", not _r, "got=%s" % _m)


print("")
print("== D. 静态向：guard 的键不得再被并进 allowed ==")
check("源码里不再有 `allowed |= set((e.get(\"guard\") or {}))` 这一形态",
      'allowed |= set((e.get("guard") or {}))' not in _src,
      "静默失效链的第一环还在：打错的 guard 名仍会被当成合法名")

check("源码里保留着 guard 键的 fail-closed 校验",
      "guard 键" in _src and "不在 vars/params 里" in _src,
      "找不到 guard 键的装配期校验")


print("")
print("== E. 两向反证：摘掉校验必须转红（证明本门禁真在钉这件事）==")
_orig = io.open(_SRC, encoding="utf-8", newline="").read()
try:
    # 把 fail-closed 那一段整段摘掉（模拟"这轮没修"）⇒ 第 A 组三条必须转红。
    _start = _orig.find("    guard = e.get(\"guard\") or {}\n")
    _end = _orig.find("    allowed = set(e.get(\"vars\") or [])\n", _start)
    _cut = _orig[:_start] + _orig[_end:] if (_start != -1 and _end > _start) else None
    check("★ 反证前提：能在源码里定位到 guard 校验段", _cut is not None,
          "定位不到 ⇒ 反证无效（门禁可能根本没钉住东西）")
    if _cut is not None:
        io.open(_SRC, "w", encoding="utf-8", newline="").write(_cut)
        for m in list(sys.modules):
            if m.startswith("saintess_engine.formula"):
                del sys.modules[m]
        import importlib
        _mod = importlib.import_module("saintess_engine.formula")
        _r2, _m2 = (False, "")
        try:
            _mod.FormulaTable.from_decl(
                _tbl({"def": {"cap": 0.6}, "pene_pcts": {"cap": 0.6}}, "def * 2", ["def"]))
        except Exception as ex:                              # noqa: BLE001
            _r2, _m2 = True, "%s" % ex
        check("★ 反证：摘掉校验后「guard 键拼错」重新被放行（= 判据转红）", not _r2,
              "摘掉校验后仍然抛错 ⇒ 本门禁没钉住这件事")
finally:
    io.open(_SRC, "w", encoding="utf-8", newline="").write(_orig)
    for m in list(sys.modules):
        if m.startswith("saintess_engine.formula"):
            del sys.modules[m]

# 复原后必须仍能跑（证明 finally 复原成功）
_r, _m = _raises(_tbl({"def": {"cap": 0.6}, "pene_pcts": {"cap": 0.6}}, "def * 2", ["def"]))
check("★ 反证收尾：源码复原后判据重新生效（拼错仍抛）", _r, "复原失败，源码可能已被反证写坏")


print("")
print("=== PASS=%d FAIL=%d ===" % (PASS, len(FAILS)))
sys.exit(1 if FAILS else 0)
