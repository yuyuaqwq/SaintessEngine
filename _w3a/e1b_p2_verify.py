# -*- coding: utf-8 -*-
"""E1b/P2 验收：`F2_damage_full` 全链 ≡ 手工三步组合（同输入、定种子）。

用法：  python _w3a/e1b_p2_verify.py

背景（见 `aetheran-designer/12_迁移引擎评估/04_E1b接线卡点与提案.md`）：
  声明是**原子**的 —— 从「level + 敌防」到「伤害」原本要调用方串 4 条。
  本批用**既有** `chain` 的 `use` 步把它们串成一条全链（零新语法）。

★ 这条验收的实质：证明"用 `use` 串起来"与"调用方手工串"**逐位同值**。

★★ 两个真实陷阱（第一版都踩了，都记在下面）：
  1. 声明里的变量名是 `def` —— Python **关键字** ⇒ 只能走**字典键**传，
     不能用关键字实参。第一版为了传参把它改名成 `dfn`，于是声明侧那个 `def`
     从未被提供，`expr` **静默按 0 算**（不报错、结果似是而非：150 而不是 100）。
  2. `F2_damage` 有 8 个输入变量，少给一个就按 0 参与乘法 ⇒ 必须**显式补全**。
"""
from __future__ import annotations

import json
import random
import sys

sys.path.insert(0, r"C:/Users/yuyu/framework-engine")

from saintess_engine.formula import FormulaTable                     # noqa: E402

PKG = r"C:/Users/yuyu/aetheran-package"
TPL = f"{PKG}/content/rules/formula_table.json"

FULL_CHAIN = {
    "kind": "chain",
    "label": "F2 全链（level + 敌防 → 最终伤害）",
    "version": 1,
    # ★ 必须显式声明：V1 的推导规则是"从**最后一步**的 returns 推"，
    #   而本链最后一步是 `use` 步（自己没有 returns）⇒ 推不出来，得写。
    #   （F2_damage 那条链不用写，因为它的最后一步是带 returns 的 expr 步。）
    "returns": "int",
    "vars": ["level", "def", "pene_pct", "pene_flat", "base", "mult_skill",
             "amp", "mitigation", "crit_mult", "elem_mult", "variance"],
    "steps": [
        {"id": "k_def",   "use": "F1_k_def",            "trace": "等级减伤常数 K"},
        {"id": "eff_def", "use": "F1_eff_def",          "trace": "有效防御（穿透后）"},
        {"id": "dr",      "use": "F1_damage_reduction", "trace": "减伤率"},
        {"id": "final",   "use": "F2_damage",           "trace": "乘区链（含克制区）"},
    ],
    "note": "★ 由 E1b/P2 加：把 4 条原子声明串成一条全链，供引擎按槽位 'damage' 调用。"
            "依赖 P4 的一处修正 —— `use` 步必须看到前面步的输出（原来传的是原始入参）。",
}

#: `F2_damage_full` 的**全部**输入变量及默认值。少给一个 ⇒ expr 静默按 0。
DFLT = {
    "level": 1, "def": 0, "base": 0,
    "mult_skill": 1.0, "amp": 0.0, "mitigation": 0.0,
    "crit_mult": 1.0, "elem_mult": 1.0,
    "pene_pct": 0.0, "pene_flat": 0.0, "variance": 0.0,
}

CASES = [
    ("Lv1 标准怪",          {"level": 1,   "def": 60,   "base": 100}),
    ("Lv50 标准怪",         {"level": 50,  "def": 550,  "base": 150}),
    ("Lv50 高防怪",         {"level": 50,  "def": 1650, "base": 150}),
    ("Lv100 标准怪",        {"level": 100, "def": 1050, "base": 300}),
    ("带穿透 20%",          {"level": 50,  "def": 1100, "base": 200, "pene_pct": 0.2}),
    ("穿透 20% + 固定 50",  {"level": 50,  "def": 1100, "base": 200,
                             "pene_pct": 0.2, "pene_flat": 50}),
    ("满乘区",              {"level": 50,  "def": 550,  "base": 150, "mult_skill": 1.2,
                             "amp": 0.3, "mitigation": 0.1, "crit_mult": 1.5,
                             "elem_mult": 1.25}),
    ("穿透 60% vs 低防",    {"level": 50,  "def": 100,  "base": 200, "pene_pct": 0.6}),
]

FAIL: list[str] = []


def chk(label, got, want, tol=0.0):
    ok = (abs(got - want) <= tol) if isinstance(got, (int, float)) else (got == want)
    if not ok:
        FAIL.append(label)
    print(f"  {'✅' if ok else '❌'} {label:<34} = {got!r:>14} 预期 {want!r}")


def full(kw):
    return dict(DFLT, **kw)


def manual_three_step(t, v):
    """调用方手工串（= E1b 之前只能这么干）：
    F1_k_def → F1_eff_def → F1_damage_reduction → F2_damage。"""
    k_def = t.eval("F1_k_def", {"level": v["level"]})
    eff_def = t.eval("F1_eff_def", {"def": v["def"], "pene_pct": v["pene_pct"],
                                    "pene_flat": v["pene_flat"]})
    dr = t.eval("F1_damage_reduction", {"eff_def": eff_def, "k_def": k_def})
    out, _ = t.run("F2_damage", {"base": v["base"], "mult_skill": v["mult_skill"],
                                 "amp": v["amp"], "dr": dr, "mitigation": v["mitigation"],
                                 "crit_mult": v["crit_mult"], "elem_mult": v["elem_mult"],
                                 "variance": v["variance"]})
    return out, k_def, eff_def, dr


def main():
    with open(TPL, encoding="utf-8") as f:
        decl = json.load(f)
    # ★ 本脚本即 F2_damage_full 的**真源**：每次都覆盖写。
    #   （第一版写成"缺了才写" ⇒ 改定义后重跑读到的还是旧内容，白改一轮。）
    before = json.dumps(decl.get("F2_damage_full"), ensure_ascii=False, sort_keys=True)
    after = json.dumps(FULL_CHAIN, ensure_ascii=False, sort_keys=True)
    decl["F2_damage_full"] = FULL_CHAIN
    with open(TPL, "w", encoding="utf-8", newline="\n") as f:
        json.dump(decl, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"  F2_damage_full {'已刷新' if before != after else '未变（内容相同）'}\n")

    t = FormulaTable.from_decl(decl)
    print(f"  装配 {len(t.ids())} 条声明（含 F2_damage_full）\n")

    print("【1】★ 主验收：全链 ≡ 手工三步（同输入、variance=0 ⇒ 确定性）")
    for label, kw in CASES:
        v = full(kw)
        want, k_def, eff_def, dr = manual_three_step(t, v)
        got, _ = t.run("F2_damage_full", v)
        chk(label, got, want)
        print(f"       K={k_def:<7.4g} eff_def={eff_def:<7.4g} DR={dr:.4%} "
              f"⇒ 全链={got} 手工={want}")
    print()

    print("【2】逐步打印：全链 4 步（每一环都能单独算给玩家看）")
    _, rows = t.run("F2_damage_full", full(CASES[1][1]))
    for r in rows:
        print(f"       {r['step']:<10} out={r['out']!r:<12} delta={r['delta_pct']}%")
    chk("步数", len(rows), 4)
    chk("步 id 序列", [r["step"] for r in rows], ["k_def", "eff_def", "dr", "final"])
    print()

    print("【3】波动：variance>0 时全链与手工三步**同种子同值**（且贴基准 ±5%）")
    v = full(dict(CASES[1][1], variance=0.05))
    a_list, b_list = [], []
    for seed in (11, 22, 33, 44, 55):
        random.seed(seed)
        a_list.append(t.run("F2_damage_full", v)[0])
        random.seed(seed)
        b_list.append(manual_three_step(t, v)[0])
    chk("★ 同种子 ⇒ 逐次同值", a_list == b_list, True)
    print(f"       全链 = {a_list}")
    print(f"       手工 = {b_list}")
    base_v = manual_three_step(t, full(CASES[1][1]))[0]
    chk("★ 波动后仍贴基准 ±5%",
        all(abs(x - base_v) / base_v <= 0.05 for x in a_list), True)
    chk("★ 波动时结果不全同（确实在动）", len(set(a_list)) > 1, True)
    print()

    print("【4】回归：既有 26 条声明逐条仍可求值（加全链没打坏任何一条）")
    probes = {
        "F1_k_def": {"level": 50}, "F1_damage_reduction": {"eff_def": 550, "k_def": 1100},
        "F1_eff_def": {"def": 550, "pene_pct": 0.0, "pene_flat": 0},
        "F2_variance": {"var_roll": 0.0}, "F3_eff_dodge": {"dodge": 100, "prec": 30},
        "F3_miss": {"eff_dodge": 100, "level": 1, "diff_mod": 1.0},
        "F1_k_def_rate": {"level": 50}, "F4_crit_pct": {"crit_r": 800, "k_rate": 1800},
        "F4_crit_mult": {"crit_dmg": 1.0}, "F5_act_time": {"base": 1.0, "spd": 100},
        "F7_haste_pct": {"haste": 500, "k_rate": 1000}, "F7_cd": {"cd_base": 10, "cdr": 0.2},
        "F8_cast_time": {"t_base": 1.0, "cast_spd": 500},
        "F9_heal": {"matk": 1000, "mult": 1.2, "heal_amp": 0.1, "heal_down": 0.3},
        "F9_shield": {"matk": 1000, "mult": 1.0, "shield_amp": 0.0},
        "F9_reflect": {"taken_final": 300, "reflect_rate": 0.2},
        "F10_resource_gain": {"gain_base": 10, "channel_mult": 1.0, "gain_amp": 0.0},
        "F10_ult_frequency": {"pool": 160, "gain_per_action": 20},
        "F11_threat": {"final_dmg": 300, "coef": 3.0, "flat": 0, "threat_amp": 0.0},
        "F11_threat_share": {"my_threat": 250, "team_threat": 1000},
        "F12_drop_rate": {"daily_target": 3, "daily_kills": 40},
        # ★ 这两条走 `param.` ref ⇒ 必须给 ctx["tables"]（不给就装配期抛，不是静默 0）
        "F12_exp_per_kill": {"mob_hp": 590, "k": 0.32},
        "F12_level_req": {"level": 20},
        "F6_mitigation": {"mitigations": [0.2, 0.3]},
        "F2_damage": {"base": 150, "mult_skill": 1.0, "amp": 0.0, "dr": 0.333333,
                      "mitigation": 0.0, "crit_mult": 1.0, "elem_mult": 1.0,
                      "variance": 0.0},
    }
    CTX = {"tables": {"curve": {"k_exp": 0.32, "k_level": 45, "p_level": 1.5}}}
    bad = []
    for eid, kw2 in probes.items():
        try:
            # ★ chain 只能用 .run()（.eval() 会明确报错让改口径，不会静默给错值）
            if t._e[eid]["kind"] == "chain":                              # noqa: SLF001
                v = t.run(eid, kw2, ctx=CTX)[0]
            else:
                v = t.eval(eid, kw2, ctx=CTX)
            if v is None and eid != "F6_mitigation":
                bad.append(f"{eid}: None")
        except Exception as ex:                                          # noqa: BLE001
            bad.append(f"{eid}: {type(ex).__name__}: {ex}")
    chk("逐条求值无异常", bad, [])
    # ★ F6 = 1 - ∏(1-x)：[0.2,0.3] ⇒ 1 - 0.8*0.7 = 0.44（不是 0.75 —— 那是 [0.5,0.5] 的值）
    chk("F6 聚合仍可求值（[.2,.3] ⇒ 1-0.8*0.7）", t.eval("F6_mitigation", {"mitigations": [0.2, 0.3]}), 0.44, 1e-9)
    chk("F6 聚合（[.5,.5] ⇒ 0.75）", t.eval("F6_mitigation", {"mitigations": [0.5, 0.5]}), 0.75, 1e-9)
    print()

    print("【5】★ 登记盲区（V5 拦不住的那种）")
    print("       V5 只校验**本链自己**的 expr 变量域；`use` 步引用的条目需要什么变量，")
    print("       V5 **不查** ⇒ 串链少给一个变量时，`expr` 静默按 0 算（不报错）。")
    print("       实证：把 `def` 写错成 `dfn` ⇒ 全链给 150（=不减伤），手工给 100。")
    try:
        t.run("F2_damage_full", {"level": 50, "base": 150})          # 只给 2 个变量
        print("       ⚠️  少给 9 个变量仍然跑通（静默按 0）—— 这就是盲区的形状")
    except Exception as ex:                                          # noqa: BLE001
        print(f"       少给变量 ⇒ {type(ex).__name__}: {str(ex)[:60]}")
    print()

    print("=" * 70)
    if FAIL:
        print(f"E1b/P2 ✗ 未过（{len(FAIL)} 项）：{FAIL}")
        return 1
    print("E1b/P2 ✅ 全绿（全链 ≡ 手工三步 8 组 · 逐步打印 · 波动同种子同值 · 27 条回归）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
