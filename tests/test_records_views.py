#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：records/views.py 视图注册表 —— 登记 / 弱引用 / 别名回填 / 容器就地 / fail-closed。

跑法：python tests/test_records_views.py（退出码 0 = 全绿）。

为什么要有这一支（审计 L381 · 中）
-----------------------------------
tests/test_records_registry.py 的 32 条断言全在 __init__.py 的注册表/重载；
全仓 tests/ 对 apply_replacements / update_in_place / placeholder / 别名回填
grep = 0 命中 => 本模块零门禁覆盖。L376「别名回填按 id(None) 把模块里所有恰好为
None 的无关全局名批量改写成同一个新对象」能活到现在就是这么来的 —— 它静默、不抛、
还「看起来正常」。补门禁先于改判据。

钉住的判据
----------
① 占位对象不参与回填：placeholder() 实例进 replacements => 跳过、返回 0 条。
② ★ old is None 不参与回填（L376 修复面）：[(None, 新值)] => 模块里每一个恰好为
   None 的无关全局名都必须原样不动。None 是内容侧 catalog_*.py 的「这一格没抓到
   旧值」起手形，不是「有个名字指着它」。
③ 正常别名回填按身份生效：new is old => 跳过（首次构建）；两条 old 允许 == 相等
   （按身份逐条处理，序列不去重）；旧对象可不可哈希都不限。
④ __ 开头的全局名不回填（模块元信息不是派生名）。
⑤ 容器替换不许走别名映射 => TypeError 点名（容器请用 update_in_place）。
⑥ update_in_place 只对同型 dict/list/set 生效（身份不变、内容换新）；不同型抛。
⑦ 登记序 = (order, 登记序) 升序；registered_views() 返回副本。
⑧ 弱引用不泄漏：登记的函数被回收 => 登记随之消失。
⑨ 一坏即抛 ViewsRebuildError：点名函数 qualname / 登记序 / 原因 / 已完成数。
"""
from __future__ import annotations

import gc
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from saintess_engine.records import (                                      # noqa: E402
    ViewsRebuildError, apply_replacements, placeholder, rebuild_views,
    register_view, registered_views, update_in_place,
)

PASS = 0
FAIL = 0

from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "PASS", "FAIL")

_SEQ = 0


def _mk(*items):
    """运行时构造一个元组（**与写死字面量不是同一只对象**）。

    ★ 为什么必须这样：本门禁要验「别名回填按**身份**（`id()`）而不是按相等」——
      而 CPython 里有两条会把「== 相等」悄悄变成「id 相同」的规则：
      ① 编译期常量元组 interning（`("a", 1) is ("a", 1)` 实测 True）；
      ② 常量表达式折叠（`("a",) + (1,)` 编译期就折成常量元组，同样进池）。
      两者都会让本该「身份不同」的两个值 `id` 相同 ⇒ 断言拿到假绿。
      走一次函数调用绕过折叠，才造得出真正两个对象。
    """
    return tuple(items)


def _probe_module(tag: str) -> types.ModuleType:
    """造一个带唯一前缀的假内容模块并登记进 sys.modules（module_prefix 按前缀捞）。

    用 probe_views_<tag> 而不是 probepkg：module_prefix 是前缀匹配
    （name == prefix or name.startswith(prefix + ".")）=> 多个用例各占一个前缀，
    互不看见对方的全局名，回填断言才是真的。
    """
    global _SEQ
    _SEQ += 1
    name = "probe_views_%s_%d" % (tag, _SEQ)
    module = types.ModuleType(name)
    sys.modules[name] = module
    return module


# ============================================================ ① 占位对象不参与回填
def t1_placeholder_skipped():
    print("\n【① placeholder() 进 replacements => 跳过、零条】")
    mod = _probe_module("ph")
    ph = placeholder("Z")
    mod.Z = ph
    n = apply_replacements([(ph, ("z", 9))], mod.__name__)
    check("占位对象回填返回 0 条", n == 0, n)
    check("★ 占位对象本身原样保留（没被换成新值）", mod.Z is ph, mod.Z)


# ============================================================ ② ★ old is None 不回填
def t2_none_not_rebound():
    print("\n【② ★ old is None => 无关的 None 全局名一律不动（L376）】")
    mod = _probe_module("none")
    mod.N = None
    mod.OTHER = None
    mod.KEEP = ("a", 1)
    mod.UNAFFECTED = None
    n = apply_replacements([(None, ("beta", 2))], mod.__name__)
    check("None 替换本身被受理（返回 1 条）", n == 1, n)
    check("★ N 原样仍是 None（没被写成 ('beta',2)）", mod.N is None, mod.N)
    check("★ OTHER 原样仍是 None（同身份也不回填）", mod.OTHER is None, mod.OTHER)
    check("★ 第三个 None 全局名同样不受影响", mod.UNAFFECTED is None, mod.UNAFFECTED)
    check("★ 无关真值名原样不动", mod.KEEP == ("a", 1), mod.KEEP)

    other = _probe_module("none_other")
    other.N = None
    apply_replacements([(None, ("beta", 3))], mod.__name__)
    check("★ 只作用于 module_prefix 命中的模块", other.N is None, other.N)


# ============================================================ ③ 正常别名回填按身份
def t3_alias_rebind():
    print("\n【③ 正常别名回填：按对象身份改指全局名】")
    mod = _probe_module("alias")
    # ★ 旧对象必须是**运行时构造**的：字面量元组会被 CPython 内部驻留
    #   （实测 ("a",1) 与 ("a",1) 的 id 相同）⇒ 用它测「身份口径」会给出假绿/假红。
    old = _mk("a", 1)
    mod.X = old
    mod.SAME = old
    mod.UNRELATED = _mk("a", 1)
    mod.OTHER = 12345
    n = apply_replacements([(old, ("a", 2))], mod.__name__)
    check("返回 1 条", n == 1, n)
    check("★ X 改指新对象", mod.X == ("a", 2), mod.X)
    check("★ 同一对象的第二个名字 SAME 也改指（身份口径非相等口径）", mod.SAME == ("a", 2), mod.SAME)
    check("★ == 但身份不同的 UNAFFECTED 不动", mod.UNRELATED == ("a", 1), mod.UNRELATED)
    check("无关数字名不动", mod.OTHER == 12345, mod.OTHER)

    mod2 = _probe_module("identity")
    same = ("s", 1)
    mod2.P = same
    n2 = apply_replacements([(same, same)], mod2.__name__)
    check("new is old => 跳过、返回 0 条", n2 == 0, n2)
    check("★ 跳过时全局名原样不动", mod2.P is same, mod2.P)

    mod3 = _probe_module("dupeq")
    o1, o2 = _mk("d", 1), _mk("d", 1)
    mod3.A, mod3.B = o1, o2
    n3 = apply_replacements([(o1, ("d", 2)), (o2, ("d", 3))], mod3.__name__)
    check("两条 == 相等的 old 各自成一条（序列不去重）", n3 == 2, n3)
    check("★ A / B 各自改指自己的新值", mod3.A == ("d", 2) and mod3.B == ("d", 3),
          (mod3.A, mod3.B))

    # 不可哈希的旧对象：用 tuple 里装 list（list 不可哈希、tuple 可哈希且身份唯一）
    mod4 = _probe_module("unhash")
    holder = _mk(["u"])
    mod4.L = holder
    n4 = apply_replacements([(holder, _mk(["v"]))], mod4.__name__)
    check("★ 旧对象含不可哈希成员也能按身份回填",
          n4 == 1 and mod4.L == _mk(["v"]), (n4, mod4.L))
    check("★ 换指后是新对象（旧的不被就地改）", mod4.L is not holder, mod4.L)


# ============================================================ ④ __ 开头的全局名不回填
def t4_dunder_skipped():
    print("\n【④ __ 开头的全局名不回填（模块元信息不是派生名）】")
    mod = _probe_module("dunder")
    target = ("t", 1)
    mod.__custom__ = target
    mod.Y = target
    n = apply_replacements([(target, ("t", 2))], mod.__name__)
    check("返回 1 条", n == 1, n)
    check("★ __custom__ 原样不动", mod.__custom__ == ("t", 1), mod.__custom__)
    check("★ 普通名照常改指", mod.Y == ("t", 2), mod.Y)


# ============================================================ ⑤ 容器替换不许走别名映射
def t5_container_rejected():
    print("\n【⑤ 容器替换走别名映射 => TypeError（该用 update_in_place）】")
    for label, old, new in (("dict", {"a": 1}, {"b": 2}),
                            ("list", [1], [2]),
                            ("set", {1}, {2})):
        try:
            apply_replacements([(old, new)], "probe_views_container")
        except TypeError as exc:
            check("★ %s => %s 抛错并点名「就地更新」" % (label, label),
                  "就地更新" in str(exc), str(exc)[:80])
        else:
            check("★ %s 容器替换必须抛 TypeError" % label, False, "没抛")


# ============================================================ ⑥ update_in_place
def t6_update_in_place():
    print("\n【⑥ update_in_place：同型就地换内容、身份不变；不同型抛错】")
    d = {"a": 1}
    ref = d
    update_in_place(d, {"b": 2})
    check("dict：内容换新", d == {"b": 2}, d)
    check("★ dict：外部持有的还是同一只对象（身份不变）", ref is d, ref)

    lst = [1]
    lref = lst
    update_in_place(lst, [2, 3])
    check("list：内容换新", lst == [2, 3], lst)
    check("★ list：身份不变", lref is lst, lref)

    st = {1}
    sref = st
    update_in_place(st, {2})
    check("set：内容换新", st == {2}, st)
    check("★ set：身份不变", sref is st, sref)

    for label, old, new in (("dict vs list", {"a": 1}, [1]),
                            ("list vs dict", [1], {"a": 1}),
                            ("dict vs set", {"a": 1}, {1}),
                            ("dict vs tuple", {"a": 1}, (1,)),
                            ("dict vs None", {"a": 1}, None)):
        try:
            update_in_place(old, new)
        except TypeError as exc:
            check("★ %s => TypeError 并点名两个类型" % label,
                  "同型" in str(exc) or "dict/list/set" in str(exc), str(exc)[:70])
        else:
            check("★ %s 必须抛 TypeError" % label, False, "没抛")


# ============================================================ ⑦ 登记序 + 副本
def t7_registry_order():
    print("\n【⑦ 登记序 = (order, 登记序) 升序；registered_views() 返回副本】")
    seen = []

    def f_a():
        seen.append("a")
    def f_b():
        seen.append("b")
    def f_b2():
        seen.append("b2")
    for fn in (f_a, f_b, f_b2):
        fn.__name__ = fn.__qualname__ = "probe_" + fn.__name__
        fn.__module__ = __name__

    register_view(f_b, order=10)
    register_view(f_b2, order=10)
    register_view(f_a, order=1)
    del seen[:]
    n = rebuild_views()
    check("三个函数都跑到", n >= 3, n)
    check("★ 小的 order 在前，同 order 按登记先后",
          seen[:3] == ["a", "b", "b2"], seen[:6])

    listed = registered_views()
    check("registered_views() 返回 list", isinstance(listed, list), type(listed).__name__)
    listed.clear()
    check("★ 改返回值不动注册表（是副本）", len(registered_views()) >= 3,
          len(registered_views()))
    del f_a, f_b, f_b2


# ============================================================ ⑧ 弱引用不泄漏
def t8_weakref_released():
    print("\n【⑧ 登记是弱引用：函数被回收 => 登记随之消失】")
    before = len(registered_views())
    _probe_module("weak")

    def _f():
        return None
    _f.__name__ = _f.__qualname__ = "probe_weak_f"
    _f.__module__ = __name__
    register_view(_f, order=99)
    during = len(registered_views())
    check("登记后多出一条", during == before + 1, (before, during))
    del _f
    gc.collect()
    after = len(registered_views())
    check("★ 函数回收后登记随之消失（不泄漏）", after == before, (before, after))


# ============================================================ ⑨ 一坏即抛（fail-closed）
def t9_fail_closed():
    print("\n【⑨ 任一重建函数抛错 => ViewsRebuildError（不吞成成功）】")

    def _ok():
        return None
    def _bad():
        raise ValueError("故意的坏重建")
    for fn in (_ok, _bad):
        fn.__name__ = fn.__qualname__ = "probe_fc_" + fn.__name__
        fn.__module__ = __name__

    register_view(_ok, order=5)
    register_view(_bad, order=6)
    try:
        rebuild_views()
    except ViewsRebuildError as exc:
        msg = str(exc)
        check("★ 抛 ViewsRebuildError", True)
        check("★ 报错点名出错的函数", "probe_fc__bad" in msg, msg[:120])
        check("★ 报错带登记序", "登记序 6" in msg, msg[:120])
        check("★ 报错带原始原因", "故意的坏重建" in msg, msg[:120])
        check("★ 报错带已完成数量", "已完成" in msg, msg[:120])
    else:
        check("★ 重建函数抛错必须冒泡成 ViewsRebuildError", False, "没抛")
    del _ok, _bad
    gc.collect()


def main() -> int:
    print("== 门禁：视图注册表（别名回填 / 容器就地 / fail-closed）==")
    t1_placeholder_skipped()
    t2_none_not_rebound()
    t3_alias_rebind()
    t4_dunder_skipped()
    t5_container_rejected()
    t6_update_in_place()
    t7_registry_order()
    t8_weakref_released()
    t9_fail_closed()
    print("-" * 56)
    print("通过 %d · 失败 %d" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
