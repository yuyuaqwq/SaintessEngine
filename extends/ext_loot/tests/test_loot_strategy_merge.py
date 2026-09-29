#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""loot 门禁补丁：`strategies=...` 合并 spec 后 `fn` 必须仍可调用（收口 · 2026-09-29）。

★ 真缺陷（实跑复现 · 玩家可见面 = 副本战利品堆 / 一切 type=table 的池）
------------------------------------------------------------------
`LootTable.__init__` 的 dict spec 合并路径，旧写法：

    merged["fn"] = _check_spec(k, merged.get("fn"), ...)

而 `_check_spec` 的契约是「校验并返回**整个 spec dict**」（{"fn", "uses",
"needs_weights", "expand"}），不是返回 fn ⇒ 凡「以 dict spec 覆盖策略」的实例
（奥兰迪亚 `content/loot.py` 的 `{"table": {"expand": _expand_table}}` 即此形态：
只换 expand、不给 fn），其被覆盖策略的 `spec["fn"]` 里躺着 dict：

    roll 到该策略 → TypeError: 'dict' object is not callable

· strict=True（现行默认）：直接抛；
· strict=False（旧默认形态）：被 except 吞成「这次没掉」——零痕迹。

★ 为什么 t12（L573 同批门禁）没抓到：它检查的是「uses 被改对」与
  「**没有覆盖 strategies 的**实例能不能 roll」——`spec["fn"]` 被写坏这一格
  两处都碰不到。本文件专门补这一格：**合并后 spec["fn"] 的可调用性 +
  端到端 roll**。

判据（只加强零放宽）
------------------------------------------------------------------
A 段：覆盖内置策略（只换 expand）后 —— fn 可调用、仍与内置同一、expand 已替换
B 段：端到端 —— type=table 的池真 roll 出产物（修复前在此炸 TypeError）
C 段：给 fn 的自定义 dict spec —— 合并后 fn 可调用、uses 归一（不误伤既有语义）
D 段：裸可调用简写 —— 仍走 entries 族（既有语义不许被打断）
"""
import os
import sys

_HERE_DIR = os.path.dirname(os.path.abspath(__file__))   # extends/ext_loot/tests
_PKG_ROOT = os.path.dirname(_HERE_DIR)                   # extends/ext_loot
_EXT_BASE = os.path.dirname(_PKG_ROOT)                   # extends
ROOT = os.path.dirname(_EXT_BASE)                        # 引擎根
for _p in (ROOT, _EXT_BASE, _HERE_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ext_loot.loot.pool import LootTable, STRATEGIES     # noqa: E402

passed = failed = 0

from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "passed", "failed")


def t_merge_fn_callable():
    print("\n[A] 覆盖内置策略（只换 expand、不给 fn）")
    def _my_expand(table, pool):
        return []
    t = LootTable(
        {"p": {"type": "table", "rolls": [{"pool": "sub", "chance": 1.0}]},
         "sub": {"type": "fixed", "entries": [{"item": "item:x"}]}},
        resolver=lambda ref, ctx: {"item": ref, "count": 1},
        strategies={"table": {"expand": _my_expand}})
    spec = t._strategies["table"]
    check("A1 合并后 spec['fn'] 可调用（修复前是 dict）", callable(spec["fn"]))
    check("A2 fn 仍与内置同一（覆盖只换 expand，不得换 fn）",
          spec["fn"] is STRATEGIES["table"]["fn"])
    check("A3 expand 换成了内容侧给的", spec["expand"] is _my_expand)
    return t


def t_merge_roll_end_to_end(t):
    print("\n[B] 端到端 roll（修复前：TypeError: 'dict' object is not callable）")
    try:
        got = t.roll("p")
    except Exception as e:                       # noqa: BLE001 —— 抛出来就是判据
        check(f"B1 type=table 的池能 roll 出（实测抛 {type(e).__name__}: {e}）", False)
        return
    check("B1 type=table 的池能 roll 出", [r.get("item") for r in got] == ["item:x"])
    check("B2 产出条数与 fixed 子池一致（1 条）", len(got) == 1)


def t_custom_dict_spec():
    print("\n[C] 自定义 dict spec（给了 fn）")
    def _fn(pool, ctx, table):
        return []
    t = LootTable({"p": {"type": "ok", "entries": []}},
                  strategies={"ok": {"fn": _fn, "uses": "none"}})
    spec = t.strategy_of({"type": "ok"})
    check("C1 合并后 fn 可调用且就是原 callable",
          callable(spec["fn"]) and spec["fn"] is _fn)
    check("C2 uses 归一保留", spec["uses"] == "none")


def t_shorthand():
    print("\n[D] 裸可调用简写（既有语义）")
    def _fn(pool, ctx, table):
        return []
    t = LootTable({"p": {"type": "cf", "entries": []}}, strategies={"cf": _fn})
    spec = t.strategy_of({"type": "cf"})
    check("D1 简写 fn 就是那个 callable", spec["fn"] is _fn)
    check("D2 简写仍走 entries 族", spec["uses"] == "entries")


def main():
    print("== loot 门禁补丁：strategies= 合并后 spec['fn'] 可调用 + 端到端 ==")
    t = t_merge_fn_callable()
    t_merge_roll_end_to_end(t)
    t_custom_dict_spec()
    t_shorthand()
    print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
