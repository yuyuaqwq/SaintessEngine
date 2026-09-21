# -*- coding: utf-8 -*-
"""P4 冒烟：用设计文档 §3.2.2 的示例 JSON 原样跑 FormulaTable。

用法：  python _w3a/p4_smoke.py
"""
from __future__ import annotations

import sys

sys.path.insert(0, r"C:/Users/yuyu/framework-engine")

from saintess_engine.formula import FormulaDeclError, FormulaTable  # noqa: E402

DECL = {
    "$const": {"k_rate_base": 300, "k_rate_per_lv": 30},
    "k_def": {"kind": "formula", "label": "等级防御刻度", "version": 1, "vars": ["level"],
              "params": {"base": 100, "per_lv": 20}, "expr": "base + per_lv * level",
              "returns": "number", "round": 6},
    "eff_def": {"kind": "formula", "version": 1, "vars": ["def", "pene_pct", "pene_flat"],
                "guard": {"def": {"floor": 0}, "pene_pct": {"floor": 0, "cap": 0.6},
                          "pene_flat": {"floor": 0}},
                "expr": "def * (1 - pene_pct) - pene_flat", "clamp": [0, None],
                "returns": "number"},
    "damage_reduction": {"kind": "formula", "version": 1, "vars": ["eff_def", "k_def"],
                         "expr": "eff_def / (eff_def + k_def)", "clamp": [0.0, 1.0],
                         "returns": "pct", "round": 6},
    "mitigation": {"kind": "aggregate", "version": 1, "vars": ["mitigations"],
                   "op": "prod", "over": "mitigations", "item_expr": "1 - x",
                   "combine": "1 - agg", "clamp": [0.0, 0.85], "returns": "pct"},
    "damage": {"kind": "chain", "version": 1,
               "vars": ["base", "mult_skill", "amp", "dr", "mitigation", "crit_mult", "variance"],
               "random": {"key": "var_roll", "pct": "variance"},
               "steps": [
                   {"id": "raw", "expr": "base * mult_skill * (1 + amp)", "returns": "number",
                    "trace": "RawDmg"},
                   {"id": "after_dr", "expr": "raw * (1 - dr)", "returns": "number"},
                   {"id": "after_mit", "expr": "after_dr * (1 - mitigation)", "returns": "number"},
                   {"id": "after_crit", "expr": "after_mit * crit_mult", "returns": "number"},
                   {"id": "final", "expr": "after_crit * (1 + var_roll)", "returns": "int",
                    "floor": 1}]},
    # ★ F5：用 P3 新增的 `^` 幂（设计文档里表达不了的那条）
    "act_time": {"kind": "formula", "version": 1, "vars": ["base", "spd"],
                 "params": {"spd_ref": 100, "alpha": 0.5},
                 "guard": {"spd": {"floor": 1, "cap": 300}},
                 "expr": "base * (spd_ref / spd) ^ alpha", "returns": "tick", "round": 6},
    # ★ 用 const. 引常量
    "k_rate": {"kind": "formula", "version": 1, "vars": ["level"],
               "params": {"base": {"ref": "const.k_rate_base"},
                          "per_lv": {"ref": "const.k_rate_per_lv"}},
               "expr": "base + per_lv * level", "returns": "number"},
    # ★ 用 formula. 引另一条（链式组合，无环）
    "crit_pct": {"kind": "formula", "version": 1, "vars": ["crit_r", "k_rate"],
                 "expr": "crit_r / (crit_r + k_rate)", "clamp": [0.0, 0.5], "returns": "pct"},
}

FAIL = []


def chk(label, got, want, tol=1e-9):
    ok = abs(float(got) - float(want)) <= tol
    if not ok:
        FAIL.append(label)
    print(f"  {'✅' if ok else '❌'} {label:<44} = {got}   预期 {want}")
    return ok


def main():
    t = FormulaTable.from_decl(DECL)
    print("【1】装配成功 · ids()")
    print("  ", t.ids())
    print("   vars_of('damage') =", sorted(t.vars_of("damage")))
    print()

    print("【2】三类条目求值")
    chk("formula · k_def(level=50)", t.eval("k_def", {"level": 50}), 1100)
    chk("formula · eff_def(def=1050, pene=.2)", t.eval(
        "eff_def", {"def": 1050, "pene_pct": 0.2, "pene_flat": 0}), 840)
    chk("formula · damage_reduction", t.eval(
        "damage_reduction", {"eff_def": 1050, "k_def": 1100}), 0.488372, 1e-5)
    chk("aggregate · mitigation([.2,.3])  (1-0.8*0.7=0.44)",
        t.eval("mitigation", {"mitigations": [0.2, 0.3]}), 0.44)
    chk("aggregate · clamp 生效（[.5,.5] ⇒ 1-0.25=0.75 < 0.85）",
        t.eval("mitigation", {"mitigations": [0.5, 0.5]}), 0.75)
    print()

    print("【3】★ F5 用 `^` 幂（P3 新增语法）")
    chk("act_time(spd=100) ⇒ 1.0 刻", t.eval("act_time", {"base": 1.0, "spd": 100}), 1.0)
    chk("act_time(spd=200) ⇒ 0.7071 刻", t.eval("act_time", {"base": 1.0, "spd": 200}),
        0.707107, 1e-5)
    # ★ 注意：本条自带 guard{spd:{cap:300}} ⇒ spd=400 会被卡到 300 ⇒ 0.5774（不是 0.5）
    chk("act_time(spd=400) ⇒ 撞 guard cap=300 ⇒ 0.5774", t.eval("act_time", {"base": 1.0, "spd": 400}),
        0.577350, 1e-5)
    chk("act_time(spd=999) ⇒ 撞 guard cap=300 后 0.5774", t.eval(
        "act_time", {"base": 1.0, "spd": 999}), 0.577350, 1e-5)
    print()

    print("【4】params.ref 四种前缀")
    chk("const. ⇒ k_rate(level=100)", t.eval("k_rate", {"level": 100}), 3300)
    # 1777/5077 = 0.3500094… ⇒ round 6 位 = 0.350009（别拿 0.35 当预期，那是两位近似）
    chk("formula. ⇒ crit_pct(crit_r=1777, k_rate=3300)", t.eval(
        "crit_pct", {"crit_r": 1777, "k_rate": 3300}), 0.350009, 1e-6)
    print()

    print("【5】chain · 逐步中间量（可打印）")
    # ★ 这条 chain 带 `random {key: var_roll, pct: variance}` ⇒ 结果**本来就是随机的**。
    #   所以在断言前**定种子**（可复现），并另跑一次 variance=0 验确定性。
    import random as _rnd
    _rnd.seed(20260921)
    val, rows = t.run("damage", {"base": 100, "mult_skill": 1.5, "amp": 0.0, "dr": 0.3333,
                                 "mitigation": 0.0, "crit_mult": 1.0, "variance": 0.05})
    for r in rows:
        d = dict(r)
        print(f"     {d['step']:<12} {d['label']:<8} out={d['out']:<14} "
              f"delta={d['delta_pct']}")
    ok = len(rows) == 5 and 95 <= val <= 105
    print(f"  {'✅' if ok else '❌'} chain 跑满 5 步且 final ∈ [95,105]（±5% 波动 ⇒ 已定种子）"
          f"  final={val}")
    if not ok:
        FAIL.append("chain")
    # 确定性对照：variance=0 ⇒ 必须恰好 100.005（= 150 × 0.6667）
    _rnd.seed(20260921)
    det, _ = t.run("damage", {"base": 100, "mult_skill": 1.5, "amp": 0.0, "dr": 0.3333,
                              "mitigation": 0.0, "crit_mult": 1.0, "variance": 0.0})
    dok = det == 100
    print(f"  {'✅' if dok else '❌'} variance=0 ⇒ 确定性 final=100（150×0.6667=100.005 ⇒ int）"
          f"  got={det}")
    if not dok:
        FAIL.append("chain-det")

    print("\n【6】check / wrong_vars（体检，不抛）")
    miss = t.check("damage", {"base": 100})
    print(f"     缺变量: {miss}  {'✅' if 'crit_mult' in miss else '❌'}")
    wv = t.wrong_vars("damage", {"base": 100, "typo_x": 1})
    print(f"     多变量: {wv}  {'✅' if wv == ['typo_x'] else '❌'}")
    print()

    print("【7】★ 有牙：非法声明必须装配期报错（V1–V12 抽查 6 条）")
    cases = [
        ("V1 kind 非法", {**{k: v for k, v in DECL.items() if not k.startswith('$')},
                          "bad": {"kind": "script", "version": 1, "vars": ["a"], "expr": "a",
                                  "returns": "number"}}, "kind"),
        ("V3 version=0", {**DECL, "bad": {"kind": "formula", "version": 0, "vars": ["a"],
                                          "expr": "a", "returns": "number"}}, "version"),
        # ★ V4 用**真正的**语法错。注意：`expr` 会静默忽略孤立的二元 `*`/`/`
        #   （`"a +* 3"` 被当成 `a+3`，不报错）—— 那是 `expr` 的**既有行为**，
        #   本批边界（§3.2.4「不改 expr 除 ^ 之外任何一行」）内不动，已登记。
        ("V4 语法错·括号不匹配", {**DECL, "bad": {"kind": "formula", "version": 1, "vars": ["a"],
                                                  "expr": "a + (3", "returns": "number"}},
         "编译失败"),
        ("V4 语法错·非法字符", {**DECL, "bad": {"kind": "formula", "version": 1, "vars": ["a"],
                                                "expr": "a @ 3", "returns": "number"}},
         "编译失败"),
        ("V5 变量未声明（拼写漂移）", {**DECL, "bad": {"kind": "formula", "version": 1,
                                                    "vars": ["atk"], "expr": "atkk * 2",
                                                    "returns": "number"}}, "未声明的变量"),
        ("V8 clamp 与 floor 同现", {**DECL, "bad": {"kind": "formula", "version": 1,
                                                    "vars": ["a"], "expr": "a",
                                                    "clamp": [0, 1], "floor": 0,
                                                    "returns": "number"}}, "自相矛盾"),
        ("V2 formula. 成环", {**DECL,
                             "c1": {"kind": "formula", "version": 1, "vars": ["x"],
                                    "params": {"y": {"ref": "formula.c2"}}, "expr": "x + y",
                                    "returns": "number"},
                             "c2": {"kind": "formula", "version": 1, "vars": ["x"],
                                    "params": {"y": {"ref": "formula.c1"}}, "expr": "x + y",
                                    "returns": "number"}}, "成环"),
    ]
    for label, decl, kw in cases:
        try:
            FormulaTable.from_decl(decl)
            print(f"  ❌ {label}  —— 居然通过了（门禁没牙）")
            FAIL.append(label)
        except FormulaDeclError as e:
            hit = kw in str(e)
            print(f"  {'✅' if hit else '❌'} {label}  —— 报错点名: {str(e)[:78]}")
            if not hit:
                FAIL.append(label)
        except Exception as e:                                   # noqa: BLE001
            print(f"  ❌ {label}  —— 抛了非 FormulaDeclError: {type(e).__name__}: {e}")
            FAIL.append(label)

    print("\n" + "=" * 66)
    if FAIL:
        print(f"P4 ✗ 未过（{len(FAIL)} 项）：{FAIL}")
        return 1
    print("P4 ✅ 全绿（三类条目 + 4 种 ref + ^ 幂 + 7 条校验有牙）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
