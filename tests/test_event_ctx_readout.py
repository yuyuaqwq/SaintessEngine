# -*- coding: utf-8 -*-
"""事件上下文公开读口（`event_ctx`）门禁 —— 钉住四条不许退化的性质。

背景（审计 L5618）：事件数值（`dmg` / `heal` / `mult` / `dt` / `source` …）过去只放在
`battle._fire_ctx` 私槽上，内容侧与示例样板只能 `getattr(battle, "_fire_ctx", None)`
—— 越过 API 读引擎内部。引擎已把它提为公开读口 `event_ctx(battle)`
（`extends/ext_combat/battle/effect_triggers.py`）。

本门禁钉的四条（任一条退化的表现写在各条后面）：

  ① **返回本尊，不是副本** —— 乘区钩子（`dmg_calc`/`taken_calc`/`heal_calc`）的设计是
     「handler 原地改 `ctx["mult"]`，调用方读**同一个对象**」。一旦 event_ctx 改成
     `dict(...)` 复制，所有乘区修正**静默丢失**（不报错，玩家少掉伤害/少掉减免）。
  ② **未 fire 过 ⇒ 空 dict，且不是同一个对象**（空读安全；调用方据此判「本次事件没给这个键」）。
  ③ **公开面齐整**：`from ext_combat import event_ctx` 可导入，且在 `__all__` 里。
  ④ **机器门禁：`examples/minimal-game/` 这份「第三方抄写样板」里不得再出现
     `getattr(battle, "_fire_ctx"`** —— 样板教人读私槽 = 契约失真（这正是 L5618 的原判）。

反证（改坏哪条会红）：
  · ① 把 `return ctx if isinstance(ctx, dict) else {}` 改成 `return dict(ctx)` ⇒ ①/② 红
  · ② 把空读回落改成 `None` ⇒ ② 红
  · ③ 从 `__all__` 删 `event_ctx` ⇒ ③ 红
  · ④ 在示例里写回私槽读法 ⇒ ④ 红

跑法：python tests/test_event_ctx_readout.py
"""
import io
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
os.environ.setdefault("GWEN_TEST_MODE", "1")
# ext_combat 等能力包在仓内 extends/ 下（run_all 的 _ext_path 口径）—— 单跑也要能 import。
sys.path.insert(0, FW_ROOT)
sys.path.insert(0, os.path.join(FW_ROOT, "extends"))

from ext_combat import event_ctx                                # noqa: E402
from ext_combat.battle import effect_triggers as ET             # noqa: E402
import ext_combat as _pkg                                       # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []

from _check import bind_check                                     # noqa: E402

check = bind_check(globals(), "PASS", "FAIL", "FAILURES")


class _FakeBattle:
    """最小 stand-in：只提供 event_ctx 真正读的那一个属性。"""
    pass


# ① 返回本尊（不复制）—— 乘区钩子的命门
b = _FakeBattle()
b._fire_ctx = {"dmg": 12, "mult": 0.5}
got = event_ctx(b)
check("① 返回本尊：改 mult 后原 ctx 同步变化（复制则红）",
      got is b._fire_ctx, f"id={id(got)} vs {id(b._fire_ctx)}")
got["mult"] = 0.25
check("① 乘区写入被调用方读到（钩子改的就是同一个对象）",
      b._fire_ctx["mult"] == 0.25, f"mult={b._fire_ctx.get('mult')}")

# ② 未 fire 过 ⇒ 空 dict；且每次给新对象（调用方不得把它当可写私槽缓存）
b2 = _FakeBattle()
e1, e2 = event_ctx(b2), event_ctx(b2)
check("② 未 fire 过 ⇒ 空 dict", e1 == {} and isinstance(e1, dict), repr(e1))
check("② 空读不是私槽本身（不会把调用方的写入漏进战斗状态）",
      e1 is not None and not hasattr(b2, "_fire_ctx"), "私槽不应被本就读空创建出来")
# 非 dict 的私槽（历史遗留/第三方塞坏）⇒ 同样空读安全，不把坏值交给内容侧
b3 = _FakeBattle()
b3._fire_ctx = ["坏值"]
check("② 私槽非 dict ⇒ 回落空 dict（不把坏值透给内容侧）",
      event_ctx(b3) == {}, repr(event_ctx(b3)))

# ③ 公开面齐整
check("③ 在 ext_combat.__all__ 里（包作者 import 得到）",
      "event_ctx" in _pkg.__all__, str(_pkg.__all__[:5]))
check("③ 与 fire 同模块（读口与事件总线同源，不另立一份语义）",
      ET.event_ctx is event_ctx and ET.fire.__module__ == ET.__name__)

# ④ 机器门禁：样板包不得教人读私槽
EX = os.path.join(FW_ROOT, "examples", "minimal-game")
_hits = []
for _root, _dirs, _files in os.walk(EX):
    _dirs[:] = [d for d in _dirs if d != "__pycache__"]
    for _fn in _files:
        if not _fn.endswith(".py"):
            continue
        _p = os.path.join(_root, _fn)
        for _i, _line in enumerate(io.open(_p, encoding="utf-8"), 1):
            if 'getattr(battle, "_fire_ctx"' in _line or "getattr(battle, '_fire_ctx'" in _line:
                _hits.append(f"{os.path.relpath(_p, FW_ROOT)}:{_i}")
check("④ 样板包 examples/minimal-game 不再出现私槽读法",
      not _hits, " | ".join(_hits))

# 同一族：内容侧 orlandia 也不该再新增私槽读法（本条只报数，不判红 ——
# 它是 C 车道文件面，收口归那条线；此处留个可见度，免得悄悄扩散）
_PKG = os.path.join(FW_ROOT, "games", "orlandia", "content")
_cnt = 0
for _root, _dirs, _files in os.walk(_PKG):
    _dirs[:] = [d for d in _dirs if d != "__pycache__"]
    for _fn in _files:
        if _fn.endswith(".py"):
            _txt = io.open(os.path.join(_root, _fn), encoding="utf-8").read()
            _cnt += _txt.count('"_fire_ctx"') + _txt.count("'_fire_ctx'")
print(f"  （可见度 · 非判据）orlandia/content 现有私槽读法 {_cnt} 处，收口归 orlandia 车道")

print()
print("\n===== 结果：通过 %d / 失败 %d =====" % (PASS, FAIL))
if FAILURES:
    for _f in FAILURES:
        print("  " + _f)
    sys.exit(1)
sys.exit(0)
