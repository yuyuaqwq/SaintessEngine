# -*- coding: utf-8 -*-
"""E3 验收：6 个校验器自测 + **拿真实的 44 件装备跑一遍**。

用法：  python _w3a/e3_smoke.py

两段：
  ① 校验器自测（每个都给"通过"与"报红"两态 + 文案格式）
  ② ★ 真数据验收：把 `_work/W1D_pe_weights.json` 的 P1_44件 喂进 gates，
     按「装等+品阶+槽」分组跑极差、按 PE预算 跑单值预算 —— 这才是 E3 的意义。
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, r"C:/Users/yuyu/framework-engine")

from saintess_engine.gates import (  # noqa: E402
    monotone_by, share_within, spread_within, sum_within,
    within_budget, within_cap,
)

FAIL: list[str] = []


def chk(label, got, want):
    ok = got == want
    if not ok:
        FAIL.append(label)
    print(f"  {'✅' if ok else '❌'} {label:<46} = {got!r:<10} 预期 {want!r}")


def main():
    print("【1】within_budget：恰等于预算是允许的（严格大于才红）")
    chk("value < budget", within_budget(9.9, budget=10, label="A/x.pe"), [])
    chk("value == budget", within_budget(10, budget=10, label="A/x.pe"), [])
    r = within_budget(12.4, budget=11, label="装备/eq_xuan_tie_jian.pe")
    chk("value > budget ⇒ 1 条文案", len(r), 1)
    print(f"       文案: {r[0]}")
    chk("文案含「超预算」+ 百分比", ("超预算" in r[0] and "%" in r[0]), True)
    print()

    print("【2】spread_within：极差")
    chk("极差 5% 内通过", spread_within([("a", 10.0), ("b", 10.4)], tol=0.05, label="装备[装等50]"),
        [])
    r = spread_within([("eq_a", 12.4), ("eq_b", 10.1)], tol=0.05, label="装备[装等50/铭刻/武器]")
    chk("极差 18.5% ⇒ 报红", len(r), 1)
    print(f"       文案: {r[0]}")
    chk("文案含 max/min id", ("eq_a" in r[0] and "eq_b" in r[0]), True)
    chk("全零 ⇒ 极差 0 ⇒ 通过",
        spread_within([("a", 0.0), ("b", 0.0)], tol=0.05, label="X"), [])
    chk("全负 ⇒ 用 |min| 做分母（不除零）",
        len(spread_within([("a", -10.0), ("b", -5.0)], tol=0.05, label="X")), 1)
    print()

    print("【3】monotone_by：成长单调（返回 (errors, warns)）")
    rows = [(1, {"atk": 12}), (2, {"atk": 24}), (3, {"atk": 36})]
    chk("单调升 ⇒ errors 空", monotone_by(rows, keys=["atk"], label="职业/WDN")[0], [])
    # ★ 乱序输入 + 排序后**真的非单调**（Lv2=340 → Lv3=335 降了）。
    #   注意别写成 Lv3=340/Lv2=335 —— 那样排序后反而是单调升，测不到东西。
    bad = [(1, {"atk": 12}), (3, {"atk": 335}), (2, {"atk": 340})]
    e, w = monotone_by(bad, keys=["atk"], label="职业/cls_zhan_shi")
    chk("乱序输入按等级排序后检出非单调", len(e), 1)
    print(f"       文案: {e[0]}")
    e2, w2 = monotone_by([(1, {"atk": 1}), (2, {}), (3, {"atk": 3})], keys=["atk"], label="X")
    chk("缺字段 ⇒ 跳过该字段并记 warn", (len(e2), len(w2)), (0, 1))
    print(f"       warn: {w2[0]}")
    print()

    print("【4】within_cap：cap=None 永远通过（不许把 None 写成 0）")
    chk("cap=None ⇒ 通过", within_cap(999.0, cap=None, label="属性/haste"), [])
    chk("cap=0.5 且 0.5 ⇒ 通过", within_cap(0.5, cap=0.5, label="属性/crit"), [])
    r = within_cap(0.78, cap=0.75, label="属性/cls_you_xia.precise")
    chk("越界 ⇒ 报红", len(r), 1)
    print(f"       文案: {r[0]}")
    print()

    print("【5】share_within / 【6】sum_within")
    chk("主属性 61.3% > 60% ⇒ 报红",
        len(share_within([("main", 7.6)], total=12.4, cap=0.60, label="装备/eq_a")), 1)
    chk("主属性 48% ⇒ 通过", share_within([("main", 6.0)], total=12.4, cap=0.60, label="X"), [])
    chk("6 槽合计 34% ≤ 35% ⇒ 通过",
        sum_within([(f"s{i}", 5.6) for i in range(6)], budget=35, label="6 槽"), [])
    chk("6 槽合计 38% > 35% ⇒ 报红",
        len(sum_within([(f"s{i}", 6.4) for i in range(6)], budget=35, label="6 槽")), 1)
    print()

    print("【7】用法错 ⇒ 抛异常（数据错只给文案）")
    cases = [
        ("label 空串", lambda: within_budget(1, budget=2, label=""), TypeError),
        ("budget 为负", lambda: within_budget(1, budget=-1, label="X"), ValueError),
        ("value 是 bool", lambda: within_budget(True, budget=2, label="X"), ValueError),
        ("rows 为空", lambda: spread_within([], tol=0.05, label="X"), ValueError),
        ("rows 重复 id", lambda: spread_within([("a", 1), ("a", 2)], tol=0.05, label="X"), ValueError),
        ("tol > 1", lambda: spread_within([("a", 1)], tol=1.5, label="X"), ValueError),
        ("total ≤ 0", lambda: share_within([("a", 1)], total=0, cap=0.5, label="X"), ValueError),
        ("direction 非法", lambda: monotone_by([(1, {"a": 1})], keys=["a"], direction="up", label="X"),
         ValueError),
    ]
    for label, fn, exc in cases:
        try:
            fn()
            print(f"  ❌ {label} —— 居然通过了")
            FAIL.append(label)
        except exc:
            print(f"  ✅ {label} ⇒ {exc.__name__}")
        except Exception as e:                                    # noqa: BLE001
            print(f"  ❌ {label} —— 抛了 {type(e).__name__}（预期 {exc.__name__}）")
            FAIL.append(label)
    print()

    # ══════════════════════════════════════════════════════════
    print("【8】★ 真数据验收：拿 W1D 的 44 件装备跑 gates")
    src = r"C:/Users/yuyu/aetheran-designer/_work/W1D_pe_weights.json"
    with open(src, encoding="utf-8") as f:
        D = json.load(f)
    items = D["P1_44件"]
    print(f"     载入 {len(items)} 件（来源 W1D_equip_model.py）")

    # 8a 单值预算：PE ≤ PE预算 × (1+5%)（W1D 自己的门禁口径是 5% 容差）
    eb = []
    for it in items:
        tag = f"装备[{it['段']}段/{it['装等']}/{it['品阶']}/{it['槽']}] {it['名']}"
        eb += within_budget(it["PE"], budget=it["PE预算"] * 1.05, label=tag + ".pe")
    chk(f"8a 逐件 PE ≤ 预算×1.05 ⇒ 违规 {len(eb)}", len(eb), 0)
    for m in eb[:3]:
        print(f"       {m}")

    # 8b 同组极差（同装等+品阶+槽）5%
    groups: dict = {}
    for it in items:
        groups.setdefault((it["装等"], it["品阶"], it["槽"]), []).append((it["名"], it["PE"]))
    eh = []
    multi = {k: v for k, v in groups.items() if len(v) >= 2}
    for (lv, tier, slot), rows in sorted(multi.items(), key=lambda kv: str(kv[0])):
        eh += spread_within(rows, tol=0.05, label=f"装备[{lv}/{tier}/{slot}]")
    chk(f"8b 同组极差 ≤5%（{len(multi)} 个多件组）⇒ 违规 {len(eh)}", len(eh), 0)
    for m in eh[:3]:
        print(f"       {m}")

    # 8c 反证：故意把一件抬高 20% ⇒ 必须报红（门禁有牙）
    tampered = [dict(it) for it in items]
    tg = None
    for it in tampered:
        key = (it["装等"], it["品阶"], it["槽"])
        if len(groups[key]) >= 2:
            it["PE"] = it["PE"] * 1.20
            tg = (key, it["名"])
            break
    eh2 = []
    for (lv, tier, slot), rows0 in multi.items():
        rows = [(x["名"], x["PE"]) for x in tampered
                if (x["装等"], x["品阶"], x["槽"]) == (lv, tier, slot)]
        if len(rows) >= 2:
            eh2 += spread_within(rows, tol=0.05, label=f"装备[{lv}/{tier}/{slot}]")
    chk(f"8c 反证：故意抬价 20% ⇒ 报红（对象 {tg[1]}）", len(eh2) >= 1, True)
    if eh2:
        print(f"       {eh2[0]}")

    # 8d 真实成长单调：拿锚点表（Lv1..100）验 A 层 7 项
    print()
    print("【9】真数据：锚点表 Lv1–100 的 A 层字段成长单调")
    anchor = [(1, {"max_hp": 100, "atk": 12.0, "def": 60, "mdef": 60, "spd": 100.0}),
              (50, {"max_hp": 3487, "atk": 1038.5, "def": 550, "mdef": 550, "spd": 110.1}),
              (100, {"max_hp": 31623, "atk": 1901.9, "def": 1050, "mdef": 1050, "spd": 120.0})]
    e, w = monotone_by(anchor, keys=["max_hp", "atk", "def", "mdef", "spd"], label="数值/锚点表")
    chk("锚点表 5 项单调不降", (len(e), len(w)), (0, 0))

    print("\n" + "=" * 70)
    if FAIL:
        print(f"E3 ✗ 未过（{len(FAIL)} 项）：{FAIL}")
        return 1
    print("E3 ✅ 全绿（6 校验器自测 + 8 条用法错抛出 + 真数据 44 件零违规 + 反证有牙）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
