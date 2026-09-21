# -*- coding: utf-8 -*-
"""E1b/P3 验收：`calc_damage` 的声明优先分支（两态 A/B）。

用法：  python _w3a/e1b_p3_verify.py

态 A（**不绑**）⇒ 走旧路径 `atk²/(atk+def)`（未装配路径零回归的证据见 82 个测试）
态 B（**绑**）  ⇒ 走声明链 `F2_damage_full`
"""
from __future__ import annotations

import json
import random
import sys

sys.path.insert(0, r"C:/Users/yuyu/framework-engine")

from saintess_engine import config                                    # noqa: E402
from saintess_engine.battle.formulas import calc_damage               # noqa: E402
from saintess_engine.formula import FormulaDeclError, FormulaTable    # noqa: E402

PKG = r"C:/Users/yuyu/aetheran-package"
FAIL: list[str] = []


def chk(label, got, want, tol=0.0):
    ok = (abs(got - want) <= tol) if isinstance(got, (int, float)) else (got == want)
    if not ok:
        FAIL.append(label)
    print(f"  {'✅' if ok else '❌'} {label:<44} = {got!r:>12} 预期 {want!r}")


def main():
    with open(f"{PKG}/content/rules/formula_table.json", encoding="utf-8") as f:
        decl = json.load(f)
    t = FormulaTable.from_decl(decl)

    print("【1】态 A：不绑（`formula_bindings_fn` 未装配）⇒ 旧路径，一字不动")
    random.seed(7)
    legacy = calc_damage(150, 550, level=50)
    random.seed(7)
    legacy_nolevel = calc_damage(150, 550)
    chk("给不给 level 都一样（旧路径不读它）", legacy, legacy_nolevel)
    chk("旧公式 = 150²/(150+550) ± 波动 ⇒ 落在 [30,34]",
        30 <= legacy <= 34, True)
    print(f"       旧路径实测 = {legacy}")
    print()

    print("【2】态 B：绑定后走声明链")
    config.mount(formula_table_fn=lambda: t,
                 formula_bindings_fn=lambda s: {"damage": "F2_damage_full"}.get(s))
    try:
        # 声明链是确定性的（variance=0 时），旧路径有随机 ⇒ 只比"链路是否改走声明"
        random.seed(7)
        got = calc_damage(150, 550, level=50, variance=0.0)
        want = int(t.run("F2_damage_full", {
            "level": 50.0, "def": 550.0, "base": 150.0, "mult_skill": 1.0, "amp": 0.0,
            "mitigation": 0.0, "crit_mult": 1.0, "elem_mult": 1.0, "variance": 0.0,
            "pene_pct": 0.0, "pene_flat": 0.0})[0])
        chk("★ 与声明链同值（Lv50/def550/base150）", got, want)
        chk("  = 100（150×0.667，双曲线减伤 33.33%）", got, 100)
        print(f"       声明路径实测 = {got}")
        print()

        print("【3】声明路径的逐项行为")
        chk("Lv1 标准 ⇒ 66", calc_damage(100, 60, level=1, variance=0.0), 66)
        chk("Lv100 标准 ⇒ 200", calc_damage(300, 1050, level=100, variance=0.0), 200)
        chk("高防怪 ⇒ 60", calc_damage(150, 1650, level=50, variance=0.0), 60)
        chk("暴击 ×1.5（crit_mult 走声明）",
            calc_damage(150, 550, is_crit=True, level=50, variance=0.0), 150)
        chk("穿透 20% ⇒ 111",
            calc_damage(200, 1100, level=50, variance=0.0, pene_pct=0.2), 111)
        chk("★ 真伤 ⇒ 绕过减伤（def 映射为 0）",
            calc_damage(150, 550, level=50, variance=0.0, dmg_type="true"), 150)
        chk("★ 穿透 ⇒ 同上", calc_damage(150, 550, level=50, variance=0.0, pierce=True), 150)
        print()

        print("【4】★ fail-closed：绑了但调用方没给 level ⇒ **抛**（不猜默认等级）")
        try:
            calc_damage(150, 550)
            print("  ❌ 没给 level 居然通过了"); FAIL.append("4")
        except FormulaDeclError as ex:
            print(f"  ✅ 抛 FormulaDeclError：{str(ex)[:66]}")
        print()

        print("【5】★ 表与绑定必须同给（绑了但表没挂 ⇒ 抛，不静默回落）")
        config.mount(formula_table_fn=None)
        try:
            calc_damage(150, 550, level=50)
            print("  ❌ 表没挂居然通过了"); FAIL.append("5")
        except FormulaDeclError as ex:
            print(f"  ✅ 抛 FormulaDeclError：{str(ex)[:66]}")
        config.mount(formula_table_fn=lambda: t)
        print()
    finally:
        config.mount(formula_table_fn=None, formula_bindings_fn=None)

    print("【6】撤绑 ⇒ 逐值回到旧路径（R1「不配 = 不存在」的判据）")
    random.seed(7)
    back = calc_damage(150, 550, level=50)
    chk("与态 A 同种子逐值相同", back, legacy)
    random.seed(7)
    chk("且与『从不曾绑定』一致", calc_damage(150, 550), legacy)
    print()

    print("=" * 70)
    if FAIL:
        print(f"E1b/P3 ✗ 未过（{len(FAIL)} 项）：{FAIL}")
        return 1
    print("E1b/P3 ✅ 全绿（两态 A/B · 真伤/穿透映射 · fail-closed 两条 · 撤绑回退逐值一致）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
