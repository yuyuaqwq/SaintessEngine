# -*- coding: utf-8 -*-
"""E5 验收：技能 7 维 schema（住包）+ 两个新守卫 + 四条反证。

用法：  python _w3a/e5_smoke.py

★ E5 的裁决是 **schema 住包**（引擎默认域集不新增技能域）。
  引擎侧只补两样：`_validators.segment_of / layer_of` 两个守卫 + `segment_plan_fn` 这个 hook。
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, r"C:/Users/yuyu/framework-engine")

from saintess_engine._validators import layer_of, segment_of   # noqa: E402

PKG = r"C:/Users/yuyu/aetheran-package"
FAIL: list[str] = []


def chk(label, got, want):
    ok = got == want
    if not ok:
        FAIL.append(label)
    print(f"  {'✅' if ok else '❌'} {label:<48} = {got!r:<24} 预期 {want!r}")


def _validator():
    """优先用 jsonschema（引擎 editor/validate.py 也走它）；没装则报明。"""
    try:
        import jsonschema                                        # noqa: PLC0415
        return jsonschema.Draft202012Validator, None
    except ImportError as e:                                     # noqa: BLE001
        return None, e


GOOD = {
    "name": "誓约壁垒", "kind": "主动", "lv": 12, "desc": "守卫格挡并立誓",
    "cd": 19, "cast": {"base": 0.8}, "recover": 0.4, "range": 1,
    "mp": 0, "res_cost": {"oath": 30}, "power": 0.0,
    "owner_class": "CLS_WARDEN", "lv_band": "L1-20",
    "effect": "taunt", "mech": "shield", "mech_val": 0.5, "buff_turns": 2,
    "element": "ELE_HOLY", "target": "self",
}


def main():
    V, err = _validator()
    if V is None:
        print(f"  ❌ 需要 jsonschema 才能验 schema：{err}")
        return 1
    with open(f"{PKG}/schemas/skill.schema.json", encoding="utf-8") as f:
        schema = json.load(f)
    # ★ 与引擎口径一致：`editor/validate.py` 是拿 `$defs[primary]` 校验**表里一条**的值，
    #   不是拿顶层（顶层是"条目表"形状：{条目id: 条目}）。
    #   我第一版验了顶层 ⇒ 报 "1 is not of type 'object'"（把条目的字段值当成了条目）。
    prim = schema.get("x-primary", "skill")
    v = V(schema["$defs"][prim])
    print(f"     校验器：$defs[{prim!r}]（与 editor/validate.py 同口径）")

    print("【1】合法条目 ⇒ 通过")
    e = list(v.iter_errors(GOOD))
    chk("7 维齐备的合法技能", len(e), 0)
    for x in e[:3]:
        print(f"       {x.message[:110]}")
    print()

    print("【2】★ 反证 B1：`cast` 写成枚举名（\"快速\"）—— 两层都要拦")
    b1 = dict(GOOD, cast="快速")
    chk("B1a schema 拦下（anyOf 全不通过）", len(list(v.iter_errors(b1))) >= 1, True)
    try:
        segment_of("快速", "技能/誓约壁垒.cast")
        print("  ⚠️  B1b `segment_of(\"快速\")` 通过了 —— 这是**有意**的：")
        print("       `str` 形态的语义是「行动类别名」，由**内容侧时间模型**决定它合不合法。")
        print("       ⇒ schema 层的枚举收紧应写在包内数据词表，不在引擎守卫里。")
    except Exception as ex:                                       # noqa: BLE001
        print(f"  ✅ B1b segment_of 抛 {type(ex).__name__}: {str(ex)[:60]}")
    print()

    print("【3】★ 反证 B2：`range` = 0 或 \"near\" ⇒ schema 报红")
    chk("B2a range=0（minimum:1）", len(list(v.iter_errors(dict(GOOD, range=0)))) >= 1, True)
    chk("B2b range=\"near\"（type:integer）", len(list(v.iter_errors(dict(GOOD, range="near")))) >= 1, True)
    try:
        layer_of("near", "技能/x.reach")
        print("  ❌ layer_of 居然接受了字符串")
        FAIL.append("B2c")
    except TypeError as ex:
        print(f"  ✅ B2c layer_of 抛 TypeError 点名: {str(ex)[:64]}")
    chk("B2d layer_of(3) 原样返回", layer_of(3, "x.reach"), 3)
    chk("B2e layer_of(None, default=3) 走默认", layer_of(None, "x.reach", default=3), 3)
    print()

    print("【4】★ 反证 B3：缺 `recover`（旧包 305 条全缺）⇒ 新包 schema 报必填缺失")
    no_rec = {k: val for k, val in GOOD.items() if k != "recover"}
    e3 = list(v.iter_errors(no_rec))
    chk("B3 缺 recover ⇒ 报红", len(e3) >= 1, True)
    print(f"       {e3[0].message[:110] if e3 else ''}")
    print()

    print("【5】★ 反证 B4：字段名写错（`castt`）⇒ additionalProperties:false 报红")
    typo = dict(GOOD, castt=0.5)
    e4 = list(v.iter_errors(typo))
    chk("B4 多余字段 ⇒ 报红（框架那份 true 则不报，这正是要收紧的点）", len(e4) >= 1, True)
    print(f"       {e4[0].message[:110] if e4 else ''}")
    print()

    print("【6】segment_of 四种形态（前摇/后摇统一形状）")
    chk("None ⇒ None", segment_of(None, "x.cast"), None)
    chk("str ⇒ 原样类别名", segment_of("skill", "x.cast"), "skill")
    chk("number ⇒ float 绝对秒", segment_of(0.5, "x.cast"), 0.5)
    chk("{\"base\":n} ⇒ 基准秒（过模型）", segment_of({"base": 0.8}, "x.cast"), {"base": 0.8})
    chk("int 也算数值 ⇒ float", segment_of(2, "x.cast"), 2.0)
    bad = [("空串类别名", "", ValueError), ("负数", -1, ValueError),
           ("多带键", {"base": 1, "x": 2}, ValueError), ("缺 base", {"nope": 1}, ValueError),
           ("base 非数值", {"base": "1"}, TypeError), ("bool", True, TypeError),
           ("列表", [1], TypeError)]
    for label, val, exc in bad:
        try:
            segment_of(val, "x.cast")
            print(f"  ❌ {label} —— 居然通过了")
            FAIL.append(label)
        except exc:
            print(f"  ✅ {label} ⇒ {exc.__name__}")
        except Exception as ex:                                   # noqa: BLE001
            print(f"  ❌ {label} —— 抛了 {type(ex).__name__}（预期 {exc.__name__}）")
            FAIL.append(label)
    print()

    print("【7】hook 已进名单（不配 = 不存在）")
    from saintess_engine import config                            # noqa: PLC0415
    chk("segment_plan_fn 在 _HOOKS 名单里", "segment_plan_fn" in config._HOOKS, True)
    chk("默认未装配 ⇒ None", config._HOOKS["segment_plan_fn"], None)
    chk("hook 总数", len(config._HOOKS), 20)
    print()

    print("【8】包侧：skills 域声明 + schema 可被引擎解析")
    g = json.load(open(f"{PKG}/game.json", encoding="utf-8"))
    d = json.load(open(f"{PKG}/editor/domains.json", encoding="utf-8"))
    chk("game.json 含 skills 域", "skills" in g["domains"], True)
    chk("domains.json 的 skills 指向包内 schema",
        d["skills"]["schema"], "schemas/skill.schema.json")
    print(f"       domains = {g['domains']}")

    print("\n" + "=" * 70)
    if FAIL:
        print(f"E5 ✗ 未过（{len(FAIL)} 项）：{FAIL}")
        return 1
    print("E5 ✅ 全绿（7 维 schema + 四条反证 + segment_of 7 种非法 + layer_of + hook + 包侧域声明）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
