# -*- coding: utf-8 -*-
"""E4 验收：解锁闸门 `Unlocks` —— 三档行为逐档可测 + 装配期 fail-closed。

用法：  python _w3a/e4_smoke.py
真源：  12_迁移引擎评估/02_引擎提升设计_E3E5E4.md §4
"""
from __future__ import annotations

import sys

sys.path.insert(0, r"C:/Users/yuyu/framework-engine")

from saintess_engine.conditions import Conditions, UnknownCondition          # noqa: E402
from saintess_engine.conditions.declarative import SpecError                 # noqa: E402
from saintess_engine.unlock import Locked, UnlockDeclError, Unlocks          # noqa: E402

FAIL: list[str] = []


def chk(label, got, want):
    ok = got == want
    if not ok:
        FAIL.append(label)
    print(f"  {'✅' if ok else '❌'} {label:<46} = {got!r:<22} 预期 {want!r}")


def chk_true(label, got):
    chk(label, bool(got), True)


def _ctx(**kw):
    return kw


def _conds():
    c = Conditions()
    c.register("flag_open", lambda ctx: bool(ctx.get("open")))
    c.register("lv5plus", lambda ctx: (ctx.get("lv") or 0) >= 5)
    return c


# 一条声明节点条件（读上下文的 lv）
DECL_LV8 = {"op": "ge", "left": {"field": [{"key": "lv"}]}, "right": {"const": 8}}


def _entries():
    return {
        "UN_lock_craft": {
            "condition_key": "lv5plus",
            "targets": [{"kind": "system", "id": "craft"},
                        {"kind": "command", "id": "craft"}],
            "label_key": "ui.craft.name", "locked_text": "ui.craft.locked",
            "progress_text": "ui.craft.progress", "order": 10,
        },
        "UN_lock_map_b": {
            "condition": DECL_LV8,
            "targets": [{"kind": "map", "id": "map_b"}],
            "label_key": "ui.mapb.name", "locked_text": "ui.mapb.locked",
            "order": 20,
        },
        # 同目标 second order 更小 ⇒ 应当赢
        "UN_lock_craft_early": {
            "condition_key": "flag_open",
            "targets": [{"kind": "system", "id": "craft"}],
            "label_key": "ui.craft.name", "locked_text": "ui.craft.locked_early",
            "order": 5,
        },
    }


def main():
    c = _conds()
    u = Unlocks(_entries(), conditions=c)
    print(f"  装配 {len(u.ids())} 条；覆盖目标 {len(u.targets())} 个\n")

    print("【1】★ 档① —— 目标**未被任何条目覆盖** ⇒ 放行（R1「不配 = 不存在」）")
    chk("gate 未知目标 ⇒ None", u.gate(("system", "never_declared")), None)
    chk("is_unlocked 未知目标 ⇒ True", u.is_unlocked(("map", "never_declared")), True)
    chk("entry_of 未知目标 ⇒ None", u.entry_of(("system", "never_declared")), None)
    print("       ★ 不许把「没声明」当「没解锁」—— 未声明的 target 一律开放\n")

    print("【2】★ 档② —— 条件未注册 / 声明不合法 ⇒ **装配期抛**（不许伪装成未满足）")
    try:
        Unlocks({"UN_x": {"condition_key": "nope", "targets": [{"kind": "s", "id": "x"}],
                          "label_key": "a", "locked_text": "b"}}, conditions=c)
        print("  ❌ 未注册条件居然通过了"); FAIL.append("2a")
    except UnknownCondition as e:
        print(f"  ✅ 未注册条件 ⇒ UnknownCondition：{str(e)[:66]}")
    try:
        Unlocks({"UN_y": {"condition": {"op": "bogus", "left": {"const": 1}},
                          "targets": [{"kind": "s", "id": "y"}],
                          "label_key": "a", "locked_text": "b"}}, conditions=c)
        print("  ❌ 非法声明节点居然通过了"); FAIL.append("2b")
    except SpecError as e:
        print(f"  ✅ 非法声明节点 ⇒ SpecError：{str(e)[:62]}")
    print()

    print("【3】★ 档③ —— 条件判不成立 ⇒ `Locked`（**结构**，不是渲染好的字符串）")
    lo = u.gate(("map", "map_b"), _ctx(lv=3))
    chk_true("lv=3 ⇒ gate 返回 Locked", isinstance(lo, Locked))
    chk("  Locked.target 是规整二元组", lo.target, ("map", "map_b"))
    chk("  Locked.entry_id 点名到条目", lo.entry_id, "UN_lock_map_b")
    chk("  label_key 槽位", lo.label_key, "ui.mapb.name")
    chk("  locked_text 槽位", lo.locked_text, "ui.mapb.locked")
    chk("  progress_text 未声明 ⇒ None", lo.progress_text, None)
    u2 = Unlocks(_entries(), conditions=c)
    chk("lv=9 ⇒ gate 放行", u2.gate(("map", "map_b"), _ctx(lv=9)), None)
    print(f"       repr = {lo!r}")
    print()

    print("【4】同目标多条覆盖 ⇒ 取 order 最小者（不猜，顺序由数据给）")
    chk("entry_of(craft) 取 order=5 那条", u.entry_of(("system", "craft")), "UN_lock_craft_early")
    chk("声明顺序反着来也一样（order 说话）",
        Unlocks(dict(reversed(list(_entries().items()))), conditions=c)
        .entry_of(("system", "craft")), "UN_lock_craft_early")
    print()

    print("【5】render —— 引擎**不生成行文**；装 text_of 才换自然语言")
    chk("未装 text_of ⇒ 原样透 key", u.render(lo), {"label": "ui.mapb.name",
                                                     "locked": "ui.mapb.locked",
                                                     "progress": None})
    t = {"ui.mapb.name": "边境哨站", "ui.mapb.locked": "路还没通到这里",
         "ui.craft.progress": "已收集 3/10"}
    u3 = Unlocks(_entries(), conditions=c, text_of=lambda k: t.get(k, f"<缺key:{k}>"))
    chk("装了 text_of ⇒ 换成行文", u3.render(lo),
        {"label": "边境哨站", "locked": "路还没通到这里", "progress": None})
    lo2 = u3.gate(("system", "craft"), _ctx(lv=0, open=False))
    chk("  craft 未解锁（early 条 flag_open=False）", lo2.entry_id, "UN_lock_craft_early")
    chk("  其 progress_text 未声明 ⇒ None", u3.render(lo2)["progress"], None)
    print()

    print("【6】装配期 fail-closed：结构错一律抛（逐条）")
    base = {"condition_key": "lv5plus", "targets": [{"kind": "s", "id": "x"}],
            "label_key": "a", "locked_text": "b"}
    bad = [
        ("target 是裸字符串", dict(base, targets=["craft"])),
        ("targets 空数组", dict(base, targets=[])),
        ("targets 缺 id", dict(base, targets=[{"kind": "s"}])),
        ("target 多带键", dict(base, targets=[{"kind": "s", "id": "x", "z": 1}])),
        ("kind 空串", dict(base, targets=[{"kind": "", "id": "x"}])),
        ("label_key 缺失", {k: v for k, v in base.items() if k != "label_key"}),
        ("locked_text 空串", dict(base, locked_text="")),
        ("progress_text 空串", dict(base, progress_text="")),
        ("条件两个都写", dict(base, condition={"const": True})),
        ("条件一个都不写", {k: v for k, v in base.items() if k != "condition_key"}),
        ("order 非整数", dict(base, order="10")),
        ("targets 内部重复", dict(base, targets=[{"kind": "s", "id": "x"},
                                                {"kind": "s", "id": "x"}])),
    ]
    for label, e in bad:
        try:
            Unlocks({"UN_z": e}, conditions=c)
            print(f"  ❌ {label} —— 居然通过了"); FAIL.append(label)
        except UnlockDeclError as ex:
            print(f"  ✅ {label:<24} ⇒ 点名: {str(ex)[:62]}")
        except Exception as ex:                                     # noqa: BLE001
            print(f"  ❌ {label:<24} ⇒ 抛了 {type(ex).__name__}（预期 UnlockDeclError）")
            FAIL.append(label)
    for label, bad_args in [("entries 不是映射", ("x",)),
                            ("conditions 不是 Conditions", ({"UN_a": base},))]:
        try:
            if label.startswith("entries"):
                Unlocks(bad_args[0], conditions=c)
            else:
                Unlocks(bad_args[0], conditions=None)
            print(f"  ❌ {label} —— 居然通过了"); FAIL.append(label)
        except UnlockDeclError as ex:
            print(f"  ✅ {label:<24} ⇒ 点名: {str(ex)[:62]}")
    print()

    print("【7】audit 三类问题（只报不改）")
    au = Unlocks({
        "A_dup_order": {"condition_key": "lv5plus", "order": 0,
                        "targets": [{"kind": "s", "id": "same"}],
                        "label_key": "k1", "locked_text": "k2"},
        "B_dup_order": {"condition_key": "lv5plus", "order": 0,
                        "targets": [{"kind": "s", "id": "same"}],
                        "label_key": "k3", "locked_text": "k4"},
        "C_same_text": {"condition_key": "lv5plus", "order": 1,
                        "targets": [{"kind": "s", "id": "other"}],
                        "label_key": "same.k", "locked_text": "same.k"},
    }, conditions=c)
    rep = au.audit()
    for line in rep:
        print(f"       · {line}")
    chk_true("报出 order 重复（取条顺序脆）", any("order 重复" in x for x in rep))
    chk_true("报出文案 key 重复", any("复制粘贴" in x for x in rep))
    chk("干净的表 audit 为空", Unlocks(_entries(), conditions=c).audit() != [], True)
    print()

    print("=" * 70)
    if FAIL:
        print(f"E4 ✗ 未过（{len(FAIL)} 项）：{FAIL}")
        return 1
    print("E4 ✅ 全绿（三档行为 + 取条顺序 + render + 12 种结构错 + audit 三类）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
