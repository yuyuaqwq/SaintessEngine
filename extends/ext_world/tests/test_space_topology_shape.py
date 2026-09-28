# -*- coding: utf-8 -*-
"""`space/graph.py` **派生拓扑返回值**的形状守卫门禁（审计修复 · 批次4）。

背景
----
`SpaceGraph._take_topology` 是「第三方（内容侧）注册的拓扑函数」与引擎之间的
**唯一**接缝：拓扑函数返回什么，引擎就直接建什么图。台账 L535 修之前的实现是
`dict(out.get("links") or {})` + `out.get("gate", self._root)`，把三种错一起吞了：
返回 `{}` ⇒ 静默空图；漏 `gate` ⇒ 静默回落到 root（内容侧的出图点意图被顶掉）；
`gate` 给不存在的 id ⇒ 落点指向不存在的节点，玩家「出图」落空。

★ 立项的**实测依据**（变异法，非推断）：把本文件 4 条守卫逐条换成静默 `return`，
`test_space.py` 的 **86 条断言里 0 条转红**（另外 3 条守卫有牙）⇒ 这 4 条
**从未被验证过**。commit 8928189 补过 54 行测试，但只覆盖了 `gate()`/显式
`links` 那条路，**派生拓扑这条路一条都没钉**。

锁死的契约
----------
1. 返回非映射 → `ValueError`（点名拓扑名 + 实际类型）；
2. 缺 `links` 键 → `ValueError`（键名一字不差，报出实际键集）；
3. `links` 不是 dict → `ValueError`；
4. `gate` 给了但不在节点表里 → `ValueError`（悬空落点 = 玩家出图落空）；
5. ★ 合法档逐字放行：`links` 照用、`gate` 照用；
6. ★ **空节点表是合法输入**（`gate()` 对外承诺返回 `""`）⇒ 没有可校验的成员时
   不判悬空（这与「缺 gate 就回落 root」是**两件事**，门禁分开钉）；
7. 缺 `gate`（键不存在）→ 回落 root，**这是有意契约**（守卫只判「给了但错」）。

零游戏、零宿主：只用标准库 + 被测包。跑法：
python extends/ext_world/tests/test_space_topology_shape.py
"""
import os
import sys

# 本文件位于 extends/ext_world/tests/ ⇒ 往上四级才是**引擎根**（照 test_space.py 的推导）
_HERE_DIR = os.path.dirname(os.path.abspath(__file__))   # extends/ext_world/tests
_PKG_ROOT = os.path.dirname(_HERE_DIR)                   # extends/ext_world
_EXT_BASE = os.path.dirname(_PKG_ROOT)                   # extends
FW_ROOT = os.path.dirname(_EXT_BASE)                    # 引擎根
for _p in (FW_ROOT, _EXT_BASE, _HERE_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ext_world.space import MESH, Space, register_topology          # noqa: E402
import ext_world.space.topology as T                                # noqa: E402

from _check import bind_check  # noqa: E402  断言助手单源（tests/_check.py）

PASS = 0
FAIL = 0
FAILURES = []
TOTAL = 0

check = bind_check(globals(), "PASS", "FAIL", "FAILURES", total="TOTAL")

_NODES = [{"id": "a", "role": "start"}, {"id": "b", "role": "town"},
          {"id": "c", "role": "wild"}]


def raises(fn):
    try:
        fn()
    except BaseException as exc:            # noqa: BLE001 —— 判据要认全部异常类
        return exc
    return None


# ---------------------------------------------------------------- 1. 返回非映射
for _i, _ret in enumerate([None, "一串", 123, ["a"], ("a",), True, 3.5]):
    register_topology("bad_ret_%d" % _i, lambda *a, **k: _ret)
    _e = raises(lambda: Space(_NODES, topology="bad_ret_%d" % _i))
    check("★ 返回非映射抛 ValueError（#%d %r）" % (_i, _ret),
          isinstance(_e, ValueError), "拿到 %r" % (_e,))
    check("  · 报错点名拓扑名（#%d）" % _i,
          isinstance(_e, ValueError) and "bad_ret_%d" % _i in str(_e), str(_e))

# ---------------------------------------------------------------- 2. 缺 links 键
for _i, _ret in enumerate([{}, {"gate": "a"}, {"links2": {"a": ["b"]}}, {"gat": "a"}]):
    register_topology("no_links_%d" % _i, lambda *a, **k: _ret)
    _e = raises(lambda: Space(_NODES, topology="no_links_%d" % _i))
    check("★ 缺 'links' 键抛 ValueError（#%d %r）" % (_i, _ret),
          isinstance(_e, ValueError), "拿到 %r" % (_e,))

# ---------------------------------------------------------------- 3. links 非 dict
for _i, _bad in enumerate([["a"], "a-b", 5, None, True]):
    register_topology("bad_links_%d" % _i, lambda *a, **k: {"links": _bad, "gate": "a"})
    _e = raises(lambda: Space(_NODES, topology="bad_links_%d" % _i))
    check("★ 'links' 非 dict 抛 ValueError（#%d %r）" % (_i, _bad),
          isinstance(_e, ValueError), "拿到 %r" % (_e,))

# ---------------------------------------------------------------- 4. gate 悬空
for _i, _g in enumerate(["zzz", "A", 0, ""]):
    register_topology("bad_gate_%d" % _i,
                      lambda *a, **k: {"links": {"a": ["b"]}, "gate": _g})
    _e = raises(lambda: Space(_NODES, topology="bad_gate_%d" % _i))
    check("★ gate 不在节点表抛 ValueError（悬空落点）（#%d %r）" % (_i, _g),
          isinstance(_e, ValueError), "拿到 %r" % (_e,))

# ---------------------------------------------------------------- 5. 合法档逐字放行
register_topology("good", lambda *a, **k: {"links": {"a": ["b"], "b": ["a", "c"]},
                                           "gate": "b"})
_g = Space(_NODES, topology="good")
check("合法档：links 照用", _g.links("a") == ["b"] and _g.links("b") == ["a", "c"],
      repr(_g.adjacency()))
check("合法档：gate 照用", _g.gate() == "b", repr(_g.gate()))

register_topology("good2", lambda *a, **k: {"links": {"a": ["b"]}})
_g2 = Space(_NODES, topology="good2")
check("★ 缺 gate 键 → 回落 root（有意契约：守卫只判「给了但错」）",
      _g2.gate() == "a", repr(_g2.gate()))

# ---------------------------------------------------------------- 6. 空节点表合法
register_topology("empty_nodes", lambda *a, **k: {"links": {}, "gate": None})
_g3 = Space([], topology="empty_nodes")
check("★ 空节点表合法：gate 返回 ''（不判悬空）", _g3.gate() == "", repr(_g3.gate()))
check("★ 空节点表合法：links 为空表", _g3.links("x") == [] and _g3.adjacency() == {})

# ---------------------------------------------------------------- 7. 悬空边归 audit 报、不在构造期炸
register_topology("dangling_edge", lambda *a, **k: {"links": {"a": ["不存在的节点"]},
                                                     "gate": "a"})
_g4 = Space(_NODES, topology="dangling_edge")
check("★ 悬空边不在构造期炸（补边是内容决策，构造期只管形状）",
      _g4.links("a") == ["不存在的节点"], repr(_g4.links("a")))

print("PASS=%s FAIL=%s" % (PASS, FAIL))
if FAILURES:
    print("FAILURES:")
    for _f in FAILURES[:12]:
        print("  -", _f)
raise SystemExit(1 if FAIL else 0)
