#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：**引擎按包内声明的 `priority` 定命中先后**（B19d，宿主排序语义不再靠宿主硬编码）。

背景（为什么有这条线）
----------------------
包内 `content/data/commands.json` 里早就有 4 条 `priority` 声明
（`_maint_gate` 100 · `item_view_mode_cmd` 50 · `npc_quick_dialog` 100 · `stall_deprecated` 5），
但引擎过去**不读它**：`CommandSpec.from_dict()` 认不得、`to_dict()` 回写会把它丢掉，
`hits()` 只按**注册序**返回、`hit()` 取第一条 ⇒ 换宿主（编辑器试玩 / 任何新宿主）就丢排序语义，
只剩宿主 `game/commands/_platform.py` 自己按 priority 排（P5′ 要删掉它）。
本线把排序语义**收回引擎**，本门禁把这件事钉住。

判据（五条硬要求 + 两条加固）
------------------------------
  ① 同一条文本被两条声明命中 → **priority 高的胜出，与注册序无关**
     （把低优先级的注册在前也要高优先级赢；两种注册序都验）
  ② 同 priority → **注册序不变**（稳定排序：注册序反过来，结果也跟着反过来）
  ③ `from_dict → to_dict` 往返**保留 priority**（反「丢字段」）；缺省 0；容忍 "50" / 50 两种写法
  ④ 真包：`games/orlandia/content/data/commands.json` 的 4 条 priority **逐条相符**，
     并在真表上验一次「高优先级压过先注册的低优先级」+ 真表往返不丢
  ⑤ 反证（**内存对拍，不碰盘**）：把某条 priority 从声明里删掉 → 该条退回注册序；
     且删除只改顺序、不改命中集合
  ⑥ （加固）`priority` 只排命中 —— `visible()` 仍按 `order`、`to_data()/patterns()` 仍按注册序
  ⑦ （加固）没有新增开关：`hits()` / `hit()` 的签名仍只有 `text`（+ 既有 `mode`）

跑法：`python tests/test_host_priority_route.py`（exit=0 全绿）
"""
from __future__ import annotations

import copy
import inspect
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from saintess_engine.command import CommandRegistry, CommandSpec  # noqa: E402

PKG_SPEC = os.path.join(ROOT, "games", "orlandia", "content", "data", "commands.json")

passed = 0
failed = 0


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "passed", "failed")


# ============================================================ ③ 字段与往返
def t1_field_roundtrip():
    print("\n【③ 字段与往返：from_dict 读 / to_dict 回写 / 缺省 0】")
    d_str = CommandSpec.from_dict({"key": "k", "pattern": "^k$", "priority": "50"})
    d_int = CommandSpec.from_dict({"key": "k", "pattern": "^k$", "priority": 50})
    d_miss = CommandSpec.from_dict({"key": "k", "pattern": "^k$"})
    check('from_dict 认字符串 "50"', d_str.priority == 50, repr(d_str.priority))
    check("from_dict 认整数 50", d_int.priority == 50, repr(d_int.priority))
    check("缺省 → 0", d_miss.priority == 0, repr(d_miss.priority))
    check("dataclass 默认值 0", CommandSpec(key="k").priority == 0)
    check("坏值降级不抛（'x' → 0）",
          CommandSpec.from_dict({"key": "k", "priority": "x"}).priority == 0)

    check("to_dict 回写 priority（不许丢字段）", d_str.to_dict().get("priority") == 50,
          d_str.to_dict())
    check("往返保留 priority：spec → dict → spec",
          CommandSpec.from_dict(d_str.to_dict()).priority == 50)
    reg = CommandRegistry.from_data([{"key": "k", "pattern": "^k$", "priority": 50},
                                     {"key": "z", "pattern": "^z$"}])
    data = reg.to_data()
    check("registry.to_data() 里 priority 还在",
          [d.get("priority") for d in data] == [50, None], data)
    back = CommandRegistry.from_data(data)
    check("registry 往返：priority 逐条不变（含缺省 0）",
          back.get("k").priority == 50 and back.get("z").priority == 0)
    d0 = CommandSpec(key="z", patterns=("^z$",)).to_dict()
    check("缺省 0 的语义往返不丢（不写也读回 0，与 order 同款约定）",
          d0.get("priority", 0) == 0 and CommandSpec.from_dict(d0).priority == 0, d0)


# ============================================================ ①② 排序
def t2_order():
    print("\n【① 双命中：priority 高的胜出（与注册序无关）】")
    low = {"key": "low", "pattern": "^dup$", "priority": 5}
    high = {"key": "high", "pattern": "^dup$", "priority": 100}
    low_first = CommandRegistry.from_data([low, high])      # 低优先级注册在前
    high_first = CommandRegistry.from_data([high, low])     # 高优先级注册在前
    check("低优先注册在前 → 命中 high",
          low_first.hit("dup") is not None and low_first.hit("dup").key == "high",
          [s.key for s in low_first.hits("dup")])
    check("高优先注册在前 → 命中 high（换注册序不改结论）",
          high_first.hit("dup") is not None and high_first.hit("dup").key == "high",
          [s.key for s in high_first.hits("dup")])
    check("hits() 顺序 = priority 降序",
          [s.key for s in low_first.hits("dup")] == ["high", "low"],
          [s.key for s in low_first.hits("dup")])
    check("hit() == hits()[0]",
          low_first.hit("dup").key == low_first.hits("dup")[0].key)

    trio = CommandRegistry.from_data([{"key": "zero", "pattern": "^t$"},
                                      {"key": "neg", "pattern": "^t$", "priority": -5},
                                      {"key": "big", "pattern": "^t$", "priority": 50}])
    check("多档按值降序（正值 / 缺省 0 / 负值）",
          [s.key for s in trio.hits("t")] == ["big", "zero", "neg"],
          [s.key for s in trio.hits("t")])
    check("缺省 0 也参与排序（不是「没写就不排」）", trio.hit("t").key == "big")

    print("\n【② 同 priority → 注册序不变（稳定）】")
    a = {"key": "a", "pattern": "^s$", "priority": 7}
    b = {"key": "b", "pattern": "^s$", "priority": 7}
    c = {"key": "c", "pattern": "^s$", "priority": 7}
    fwd = CommandRegistry.from_data([a, b, c])
    rev = CommandRegistry.from_data([c, b, a])
    check("同值 → 注册序（a,b,c）", [s.key for s in fwd.hits("s")] == ["a", "b", "c"],
          [s.key for s in fwd.hits("s")])
    check("同值 → 注册序反过来结果也反过来（证明确实按注册序、不是按 key）",
          [s.key for s in rev.hits("s")] == ["c", "b", "a"],
          [s.key for s in rev.hits("s")])
    mixed = CommandRegistry.from_data([a, {"key": "hi", "pattern": "^s$", "priority": 9}, c])
    check("同值稳定 + 高优先级插队：组内仍保注册序",
          [s.key for s in mixed.hits("s")] == ["hi", "a", "c"],
          [s.key for s in mixed.hits("s")])

    print("\n【⑥ 加固：priority 只排命中，不碰别的排序/派生】")
    reg = CommandRegistry.from_data([
        {"key": "p_hi", "pattern": "^v$", "order": 9, "priority": 100},
        {"key": "p_lo", "pattern": "^v$", "order": 1, "priority": 0},
    ])
    check("visible() 仍按 order 升序（priority 不参与帮助排序）",
          [s.key for s in reg.visible()] == ["p_lo", "p_hi"],
          [s.key for s in reg.visible()])
    check("to_data() 仍按注册序（priority 不参与回写顺序）",
          [d["key"] for d in reg.to_data()] == ["p_hi", "p_lo"])
    check("specs()/keys() 仍按注册序",
          reg.keys() == ("p_hi", "p_lo") and [s.key for s in reg.specs()] == ["p_hi", "p_lo"])
    check("hits() 只换顺序、不换命中集合",
          {s.key for s in reg.hits("v")} == {"p_hi", "p_lo"})

    print("\n【⑦ 加固：没有新增开关】")
    check("hits() 签名 = (text, *, mode) —— 无新参数",
          list(inspect.signature(CommandRegistry.hits).parameters) == ["self", "text", "mode"],
          str(inspect.signature(CommandRegistry.hits)))
    check("hit() 签名 = (text, *, mode) —— 无新参数",
          list(inspect.signature(CommandRegistry.hit).parameters) == ["self", "text", "mode"],
          str(inspect.signature(CommandRegistry.hit)))


# ============================================================ ④ 真包
EXPECT_PRIORITY = {"_maint_gate": 100, "item_view_mode_cmd": 50,
                   "npc_quick_dialog": 100, "stall_deprecated": 5}
OVERLAP_TEXT = "物品详情开始"      # 命中 item_detail(0, 先注册) + item_view_mode_cmd(50)


def load_pkg_table():
    if not os.path.exists(PKG_SPEC):
        check("包内声明表存在（真数据对拍）", False, PKG_SPEC)
        return None
    with open(PKG_SPEC, encoding="utf-8") as f:
        return json.load(f)


def t3_real_package(tbl):
    print("\n【④ 真包：4 条 priority 逐条相符 + 真表上验排序】")
    declared = {k: v["priority"] for k, v in tbl.items()
                if isinstance(v, dict) and "priority" in v}
    check("真表里含 priority 的条目 = 4 条（口径：逐条对）",
          set(declared) == set(EXPECT_PRIORITY), declared)
    bad = sorted(k for k, v in EXPECT_PRIORITY.items() if declared.get(k) != v)
    check("4 条 key 的 priority 逐条等于表值 %s" % EXPECT_PRIORITY, bad == [], bad)

    reg = CommandRegistry.from_data(tbl)
    got = {k: (reg.get(k).priority if reg.get(k) else None) for k in EXPECT_PRIORITY}
    check("装进注册表后 priority 逐条相符", got == EXPECT_PRIORITY, got)
    check("注册表里 priority 非 0 的声明正好这 4 条",
          sorted(s.key for s in reg.specs() if s.priority) == sorted(EXPECT_PRIORITY),
          sorted(s.key for s in reg.specs() if s.priority))
    # 双向加固：表里**每一条**写了 priority 的，引擎读数都必须一致（不只上面硬编码的 4 条）
    check("真表里每一条含 priority 的声明都被引擎读回同值",
          {k: reg.get(k).priority for k in declared} == declared,
          {k: (reg.get(k).priority, declared[k]) for k in declared
           if reg.get(k).priority != declared[k]})

    rt = CommandRegistry.from_data(reg.to_data())
    check("真表 to_data → 重载：4 条 priority 仍逐条相同",
          {k: rt.get(k).priority for k in EXPECT_PRIORITY} == EXPECT_PRIORITY,
          {k: rt.get(k).priority for k in EXPECT_PRIORITY})
    check("真表往返后每一条含 priority 的声明都不丢",
          {k: rt.get(k).priority for k in declared} == declared,
          {k: (rt.get(k).priority, declared[k]) for k in declared
           if rt.get(k).priority != declared[k]})

    reg_order = [s.key for s in reg.specs() if s.hits(OVERLAP_TEXT)]
    check("前置：'%s' 在真表里确实双命中（注册序 %s）" % (OVERLAP_TEXT, reg_order),
          "item_detail" in reg_order and "item_view_mode_cmd" in reg_order, reg_order)
    check("前置：item_detail 确实注册在 item_view_mode_cmd **之前**（否则证明不了与注册序无关）",
          reg_order.index("item_detail") < reg_order.index("item_view_mode_cmd"), reg_order)
    hits_keys = [s.key for s in reg.hits(OVERLAP_TEXT)]
    check("真表 hits()：item_view_mode_cmd(50) 排在 item_detail(0) 前面",
          hits_keys.index("item_view_mode_cmd") < hits_keys.index("item_detail"), hits_keys)

    # 真表里 _maint_gate(100) 设计上匹配一切消息 ⇒ hit() 取它是「最高优先级」的正确结果
    check("真表 hit('%s') = 最高 priority 的 _maint_gate(100)" % OVERLAP_TEXT,
          reg.hit(OVERLAP_TEXT) is not None and reg.hit(OVERLAP_TEXT).key == "_maint_gate",
          [s.key for s in reg.hits(OVERLAP_TEXT)])

    # 去掉「匹配一切」的 gate 后，看干净的两条对照（声明表里其余一字不改）
    clean_tbl = {k: v for k, v in tbl.items() if k != "_maint_gate"}
    clean = CommandRegistry.from_data(clean_tbl)
    check("真表（去 gate）hit('%s') = item_view_mode_cmd" % OVERLAP_TEXT,
          clean.hit(OVERLAP_TEXT) is not None
          and clean.hit(OVERLAP_TEXT).key == "item_view_mode_cmd",
          [s.key for s in clean.hits(OVERLAP_TEXT)])
    check("真表（去 gate）裸数字：npc_quick_dialog(100) 压过 shortcut_trigger(0)",
          clean.hit("5") is not None and clean.hit("5").key == "npc_quick_dialog",
          [s.key for s in clean.hits("5")])
    return reg, clean_tbl


# ============================================================ ⑤ 反证
def t4_counterproof(reg, clean_tbl):
    print("\n【⑤ 反证（内存对拍）：删掉 priority → 该条退回注册序】")
    clean = CommandRegistry.from_data(clean_tbl)
    check("前置：带 priority 时命中 item_view_mode_cmd(50)",
          clean.hit(OVERLAP_TEXT) is not None
          and clean.hit(OVERLAP_TEXT).key == "item_view_mode_cmd",
          [s.key for s in clean.hits(OVERLAP_TEXT)])

    mut = copy.deepcopy(clean_tbl)
    mut["item_view_mode_cmd"].pop("priority", None)   # 数据被改坏时也要报红，不炸
    mreg = CommandRegistry.from_data(mut)
    check("删掉 item_view_mode_cmd 的 priority → 该文本退回注册序（item_detail 先中）",
          mreg.hit(OVERLAP_TEXT) is not None and mreg.hit(OVERLAP_TEXT).key == "item_detail",
          [s.key for s in mreg.hits(OVERLAP_TEXT)])
    check("删掉只改顺序、不改命中集合",
          {s.key for s in mreg.hits(OVERLAP_TEXT)} == {s.key for s in clean.hits(OVERLAP_TEXT)},
          [s.key for s in mreg.hits(OVERLAP_TEXT)])
    check("还原（带 priority）→ 高优先级复赢",
          clean.hit(OVERLAP_TEXT) is not None
          and clean.hit(OVERLAP_TEXT).key == "item_view_mode_cmd",
          [s.key for s in clean.hits(OVERLAP_TEXT)])
    # 有牙：改值也要被抓到
    mut2 = copy.deepcopy(clean_tbl)
    mut2["item_view_mode_cmd"]["priority"] = 1     # 改值：仍高于 item_detail(0)
    m2 = CommandRegistry.from_data(mut2)
    check("改值也被抓到（50 → 1 时 priority 读数跟着变，且仍赢 item_detail）",
          m2.get("item_view_mode_cmd").priority == 1
          and m2.hit(OVERLAP_TEXT).key == "item_view_mode_cmd"
          and reg.get("item_view_mode_cmd").priority == 50)


def main():
    print("=" * 74)
    print("引擎按包内 priority 定命中先后（B19d）")
    print("=" * 74)
    print("  包内声明表 = %s" % PKG_SPEC)
    print("")
    t1_field_roundtrip()
    t2_order()
    tbl = load_pkg_table()
    if tbl is None:
        print("\n===== 结果：通过 %d / 共 %d =====" % (passed, passed + failed))
        return 1
    reg, clean_tbl = t3_real_package(tbl)
    t4_counterproof(reg, clean_tbl)
    print("\n===== 结果：通过 %d / 共 %d =====" % (passed, passed + failed))
    if failed:
        return 1
    print("全绿 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
