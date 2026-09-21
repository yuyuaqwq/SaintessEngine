# -*- coding: utf-8 -*-
"""P4(E2) 冒烟：PanelStack 的三条定死语义 + 归因打印 + 有牙。

用法：  python _w3a/e2_smoke.py
真源：  12_迁移引擎评估/01_引擎提升设计_E1E2.md §2.2
"""
from __future__ import annotations

import sys

sys.path.insert(0, r"C:/Users/yuyu/framework-engine")

from saintess_engine.panel import PanelDeclError, PanelStack  # noqa: E402

FAIL: list[str] = []


def chk(label, got, want):
    ok = got == want
    if not ok:
        FAIL.append(label)
    print(f"  {'✅' if ok else '❌'} {label:<52} = {got!r:<18} 预期 {want!r}")


STACK = {
    "label": "标准角色面板", "version": 1,
    "base": {"mode": "value", "value": {"hp": 100, "atk": 12, "def": 60, "spd": 100}},
    "layers": [
        {"id": "lv", "src": "等级成长", "group": "base", "mode": "add",
         "keys": ["hp", "atk", "def"], "values": {"hp": 900, "atk": 88, "def": 940}},
        {"id": "gear_atk", "src": "武器", "group": "gear", "mode": "add",
         "keys": ["atk"], "values": {"atk": 200}},
        {"id": "gear_hp", "src": "上甲", "group": "gear", "mode": "add",
         "keys": ["hp"], "values": {"hp": 500}},
        {"id": "gear_hp2", "src": "下甲", "group": "gear", "mode": "add",
         "keys": ["hp"], "values": {"hp": 500}},
        {"id": "affix_def", "src": "词条·坚壁", "group": "affix", "mode": "mul",
         "keys": ["def"], "values": {"def": 1.10}},
        {"id": "buff_cap", "src": "增益·护盾", "group": "buff", "mode": "add",
         "keys": ["def"], "values": {"def": 9999}, "cap": 2500},
        {"id": "form", "src": "形态·狼", "group": "buff", "mode": "set",
         "keys": ["atk"], "values": {"atk": 5000}, "weight": 1,
         "when": {"form": "wolf"}, "note": "set 层不钳；weight 大者胜"},
        {"id": "form_b", "src": "形态·鹰", "group": "buff", "mode": "set",
         "keys": ["atk"], "values": {"atk": 3000}, "weight": 0,
         "when": {"form": "eagle"}},
        {"id": "off", "src": "已关掉的层", "group": "x", "mode": "add",
         "keys": ["atk"], "values": {"atk": 77777}, "status": "inactive"},
        {"id": "miss_key", "src": "缺键测试", "group": "x", "mode": "mul",
         "keys": ["nonexist"], "values": {"nonexist": 2.0}},
    ],
    "emit": {"int_keys": ["hp", "def", "atk"], "round": 6},
    "audit": {"targets": {"base": 0.40, "gear": 0.35}, "tolerance": 0.03, "max_share": 0.45},
}


def main():
    st = PanelStack.from_decl(STACK)
    print("【1】装配成功")
    print()

    print("【2】求值（无形态 flag）")
    p = st.resolve({})
    chk("hp = 100 + 900 + 500 + 500（int_keys ⇒ int）", p["hp"], 2000)
    chk("atk = 12 + 88 + 200（未触 set 层）", p["atk"], 300)
    chk("def = (60 + 940) × 1.10 = 1100 ⇒ 再加 9999 后被 cap 到 2500", p["def"], 2500)
    chk("spd = 100（没层碰它）", p["spd"], 100.0)
    chk("★ mul 的键不在基础里 ⇒ 结果 0（不改成 ×1）", p.get("nonexist"), 0)
    chk("★ inactive 层被跳过（否则 atk 会 +77777）", p["atk"] != 78077, True)
    print()

    print("【3】set 层 + when 判据 + weight 竞争")
    pw = st.resolve({}, {"flags": {"form": "wolf"}})
    chk("when={'form':'wolf'} 命中 ⇒ atk 被 set 成 5000", pw["atk"], 5000)
    pe = st.resolve({}, {"flags": {"form": "eagle"}})
    chk("when={'form':'eagle'} 命中 ⇒ atk 被 set 成 3000", pe["atk"], 3000)
    pn = st.resolve({}, {"flags": {"form": "bear"}})
    chk("when 写了但不认识 ⇒ 不命中（fail-closed）", pn["atk"], 300)
    p2 = st.resolve({}, {"flags": {"form": "wolf", "unused": 1}})
    chk("多 flag 时按命中的那条走", p2["atk"], 5000)
    # 两个 set 同时命中 ⇒ weight 大者胜
    st2 = PanelStack.from_decl(dict(
        STACK, layers=[L for L in STACK["layers"] if L["id"] in ("form", "form_b")]
        + [{"id": "f_a", "src": "A", "group": "g", "mode": "set", "keys": ["atk"],
            "values": {"atk": 111}, "weight": 0, "when": {"form": "wolf"}},
           {"id": "f_b", "src": "B", "group": "g", "mode": "set", "keys": ["atk"],
            "values": {"atk": 222}, "weight": 5, "when": {"form": "wolf"}}]))
    chk("★ 同键多个 set 同时命中 ⇒ weight 大者胜", st2.resolve({}, {"flags": {"form": "wolf"}})["atk"], 222)
    print()

    print("【4】ref 取数 + 取不到即报错")
    st3 = PanelStack.from_decl({
        "version": 1, "base": {"mode": "value", "value": {"atk": 100}},
        "layers": [{"id": "eq", "src": "装备", "group": "gear", "mode": "add",
                    "keys": ["atk"], "ref": "$eq.atk"}],
    })
    chk("ref 接通（ctx['refs']['eq']['atk'] = 250）",
        st3.resolve({}, {"refs": {"eq": {"atk": 250}}})["atk"], 350)
    try:
        st3.resolve({}, {"refs": {}})
        print("  ❌ ref 取不到 居然通过了（门禁没牙）")
        FAIL.append("ref 取不到")
    except PanelDeclError as e:
        print(f"  ✅ ref 取不到 ⇒ 报错点名: {str(e)[:70]}")
    print()

    print("【5】归因打印：trace + shares")
    for r in p.trace("atk"):
        d = dict(r)
        print(f"     {d['layer']:<10} {d['src']:<10} {d['mode']:<4} "
              f"in={d['in']:<8} out={d['out']:<8} Δ={d['delta']}")
    sh = p.shares("atk")
    print(f"     shares('atk') = {sh}   ← 只算 add 层（占比的语义是'贡献了多少点'）")
    ok = abs(sum(v for v in sh.values()) - 1.0) < 1e-6 or len(sh) == 0
    print(f"  {'✅' if ok else '❌'} shares 合计 = 1.0（或空）")
    if not ok:
        FAIL.append("shares")
    print()

    print("【6】有牙：非法声明必须装配期报错（抽查 8 条）")
    cases = [
        ("version 缺/非法", {"base": {"mode": "value", "value": {"a": 1}}, "layers": []}, "version"),
        ("base.mode 非法", {"version": 1, "base": {"mode": "x"}, "layers": []}, "base.mode"),
        ("actor 模式未列 keys", {"version": 1, "base": {"mode": "actor"}, "layers": []}, "base.keys"),
        ("层 mode 非法", {"version": 1, "base": {"mode": "value", "value": {"a": 1}},
                          "layers": [{"id": "L", "src": "s", "group": "g", "mode": "pow",
                                      "keys": ["a"], "values": {"a": 1}}]}, "mode"),
        ("层 id 重复", {"version": 1, "base": {"mode": "value", "value": {"a": 1}},
                        "layers": [{"id": "L", "src": "s", "group": "g", "mode": "add",
                                    "keys": ["a"], "values": {"a": 1}},
                                   {"id": "L", "src": "s", "group": "g", "mode": "add",
                                    "keys": ["a"], "values": {"a": 1}}]}, "重复"),
        ("层 src 空白", {"version": 1, "base": {"mode": "value", "value": {"a": 1}},
                         "layers": [{"id": "L", "src": "  ", "group": "g", "mode": "add",
                                     "keys": ["a"], "values": {"a": 1}}]}, "src"),
        ("values 与 ref 同现", {"version": 1, "base": {"mode": "value", "value": {"a": 1}},
                                "layers": [{"id": "L", "src": "s", "group": "g", "mode": "add",
                                            "keys": ["a"], "values": {"a": 1}, "ref": "$x.a"}]},
         "恰好"),
        ("order 重号", {"version": 1, "base": {"mode": "value", "value": {"a": 1}},
                        "layers": [{"id": "L1", "src": "s", "group": "g", "mode": "add",
                                    "keys": ["a"], "values": {"a": 1}, "order": 0},
                                   {"id": "L2", "src": "s", "group": "g", "mode": "add",
                                    "keys": ["a"], "values": {"a": 1}, "order": 0}]}, "重号"),
    ]
    for label, decl, kw in cases:
        try:
            PanelStack.from_decl(decl)
            print(f"  ❌ {label} —— 居然通过了")
            FAIL.append(label)
        except PanelDeclError as e:
            hit = kw in str(e)
            print(f"  {'✅' if hit else '❌'} {label} —— 点名: {str(e)[:72]}")
            if not hit:
                FAIL.append(label)
        except Exception as e:                                        # noqa: BLE001
            print(f"  ❌ {label} —— 抛了非 PanelDeclError: {type(e).__name__}: {e}")
            FAIL.append(label)

    print("\n" + "=" * 68)
    if FAIL:
        print(f"E2-P1 ✗ 未过（{len(FAIL)} 项）：{FAIL}")
        return 1
    print("E2-P1 ✅ 全绿（求值 + 三条定死语义 + when/weight/status + ref + 归因打印 + 8 条校验有牙）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
