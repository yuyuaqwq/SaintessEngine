# -*- coding: utf-8 -*-
"""`container` 容器的 `strict=True` 守卫门禁（审计修复 · 批次4）。

背景
----
`Slots.load` / `Stack.load` 的 `strict=True` 是「读 -> 改 -> 写回」那条链上唯一
防「坏档静默清空 -> 写回把玩家整仓覆盖」的守卫。模块 docstring 自陈的实测现场：
坏档 + 存 1 个木头 => 写回 `[{"key":"wood",...}]`，原仓内容**永久消失**，
全程零异常零回话。

★ 立项的**实测依据**（不是推断）：把 `slots.py` 里 strict 的两条 `raise` 整块删掉
（等价于「守卫没生效」）后，`tests/test_container.py` **仍然 100% 全绿**
=> 全仓 `strict=True` 在 Slots/Stack 上**零断言**。守卫从未被验证过。

锁死的契约
----------
1. `strict=True` + 坏 JSON => 抛 `ValueError`，**不回退空容器**；
2. `strict=True` + 顶层不是列表 => 抛 `ValueError`；
3. `strict=False`（默认）**保持原行为**：坏档 -> 空容器（纯读调用方不该崩）——
   门禁钉「严格不放松」，不是「全都抛」；
4. **没有存档不算坏档**：`None` / 空串 在 `strict=True` 下**照常返回空容器**；
5. `Stack.load` 与 `Slots.load` 同口径（同一族两个实现，逐条对拍）；
6. ★ 读改写链复现：坏档 + 存 1 件 => 被守卫挡住，原仓**永不**被覆盖；
   合法档走同一条链则原仓 2 件 + 新增 1 件 = 3（守卫不误伤正常路径）。

零游戏、零宿主：只用标准库 + 被测模块。
判据只加强：本文件是**新增**门禁，未改任何既有判据或冻结基线。
跑法：python tests/test_container_strict_shape.py
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
for _p in (FW_ROOT, os.path.join(FW_ROOT, "extends")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from saintess_engine.container.slots import Slots          # noqa: E402
from saintess_engine.container.stack import Stack          # noqa: E402

from _check import bind_check  # noqa: E402  断言助手单源：tests/_check.py

PASS = 0
FAIL = 0
FAILURES = []
TOTAL = 0

check = bind_check(globals(), "PASS", "FAIL", "FAILURES", total="TOTAL")


def raises(fn):
    """返回异常对象；不抛则 None。"""
    try:
        fn()
    except BaseException as exc:            # noqa: BLE001 —— 判据要认全部异常类
        return exc
    return None


# ---------------------------------------------------------------- 1. 坏 JSON
BAD_JSON = ["{不是 json", "[[[", "{'a': 1,", "nul", '{"key": "a"']
for _i, _raw in enumerate(BAD_JSON):
    _e = raises(lambda r=_raw: Slots.load(r, strict=True))
    check("★ Slots strict=True 坏 JSON 抛 ValueError（#%d %r）" % (_i, _raw[:14]),
          isinstance(_e, ValueError), "拿到 %r" % (_e,))
    _e2 = raises(lambda r=_raw: Stack.load(r, strict=True, marks="m"))
    check("★ Stack strict=True 坏 JSON 抛 ValueError（#%d %r）" % (_i, _raw[:14]),
          isinstance(_e2, ValueError), "拿到 %r" % (_e2,))

# ---------------------------------------------------------------- 2. 顶层不是列表
# ★ 不含 "null"：json.loads("null") -> None = 「没有存档」，按本仓契约不抛
#   （docstring：「raw 为 None / 空串（没有存档）不抛 —— 那是空仓，不是坏档」）。
#   它属于下面第 4 组「没有存档 != 坏档」，不属「坏档」。
NOT_LIST = ['{"a": 1}', '"一串"', "123", "3.5", "true"]
for _i, _raw in enumerate(NOT_LIST):
    _e = raises(lambda r=_raw: Slots.load(r, strict=True))
    check("★ Slots strict=True 顶层非列表抛 ValueError（#%d %r）" % (_i, _raw[:14]),
          isinstance(_e, ValueError), "拿到 %r" % (_e,))
    _e2 = raises(lambda r=_raw: Stack.load(r, strict=True, marks="m"))
    check("★ Stack strict=True 顶层非列表抛 ValueError（#%d %r）" % (_i, _raw[:14]),
          isinstance(_e2, ValueError), "拿到 %r" % (_e2,))

# ---------------------------------------------------------------- 3. strict=False 保持原行为
check("★ Slots strict=False 坏 JSON 仍塌成空容器（不放松既有契约）",
      len(Slots.load("{不是 json")) == 0)
check("★ Slots strict=False 顶层非列表仍塌成空容器",
      len(Slots.load('{"a":1}')) == 0)
check("★ Stack strict=False 坏 JSON 仍塌成空容器",
      len(Stack.load("{不是 json", marks="m")) == 0)

# ---------------------------------------------------------------- 4. 没有存档 != 坏档
# ★ "null" 一并钉进来：它是「JSON 层的没有存档」，不是「顶层不是列表的坏档」。
for _i, _none in enumerate([None, "", b"", "null"]):
    _s = Slots.load(_none, strict=True)
    check("★ 无存档不抛：Slots strict=True #%d %r" % (_i, _none),
          isinstance(_s, Slots) and len(_s) == 0, repr(_none))
    _k = Stack.load(_none, strict=True, marks="m")
    check("★ 无存档不抛：Stack strict=True #%d %r" % (_i, _none),
          isinstance(_k, Stack) and len(_k) == 0, repr(_none))

# ---------------------------------------------------------------- 5. 正常档逐字不变
_GOOD = json.dumps([{"key": "a", "data": {"x": 1}, "count": 2}])
_s = Slots.load(_GOOD, strict=True)
check("合法档 strict=True 逐字不变（Slots）",
      len(_s) == 1 and _s.peek_at(1) == {"key": "a", "data": {"x": 1}, "count": 2},
      repr(_s.entries()))
_k = Stack.load(_GOOD, strict=True, marks="m")
check("合法档 strict=True 逐字不变（Stack）",
      len(_k) == 1 and _k.count_of("a") == 2, repr(_k.entries()))
check("合法档 strict=True 空列表 -> 空容器",
      len(Slots.load("[]", strict=True)) == 0
      and len(Stack.load("[]", strict=True, marks="m")) == 0)

# ---------------------------------------------------------------- 6. ★ 读改写链现场复现
def _read_modify_write(raw, item_key):
    """docstring 记录的现场：坏档 + 存 1 件 => 守卫在则抛，写回永不发生。"""
    lst = Slots.load(raw, strict=True)
    lst.add(item_key, {}, 1)
    return lst.dump()


_TWO_ITEMS = '[{"key":"木头","count":3},{"key":"石头","count":5}]'
_BROKEN = _TWO_ITEMS[:-1]                    # 少一个 ] => 坏档
_e = raises(lambda: _read_modify_write(_BROKEN, "新东西"))
check("★★ 读改写链：坏档被守卫挡住，原仓永不覆盖成 1 件",
      isinstance(_e, ValueError), "拿到 %r" % (_e,))
_ok = json.loads(_read_modify_write(_TWO_ITEMS, "新东西"))
check("读改写链：合法档 -> 原 2 件 + 新 1 件 = 3（守卫不误伤正常路径）",
      len(_ok) == 3 and [x["key"] for x in _ok] == ["木头", "石头", "新东西"],
      repr(_ok))

print("PASS=%s FAIL=%s" % (PASS, FAIL))
if FAILURES:
    print("FAILURES:")
    for _f in FAILURES[:12]:
        print("  -", _f)
raise SystemExit(1 if FAIL else 0)
