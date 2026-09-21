# -*- coding: utf-8 -*-
"""E2-P2 验收：面板栈**接线**的两态验证。

用法：  python _w3a/e2_wire_verify.py

两态（同一段代码，只差"装不装 hook"）：
  态 A（**不装** `panel_layers_fn`）⇒ 必须走原路 `panel_fn`（零回归路径）
  态 B（**装** `panel_layers_fn`）  ⇒ 必须走新形状 `PanelStack`
另加：装了但 actor 没给 `panel_stack` / 给了不存在的栈 ⇒ 必须 fail-closed 点名
"""
from __future__ import annotations

import sys

sys.path.insert(0, r"C:/Users/yuyu/framework-engine")

from saintess_engine import config                       # noqa: E402
from saintess_engine.battle import stats as S            # noqa: E402
from saintess_engine.panel import PanelDeclError         # noqa: E402

FAIL: list[str] = []


def chk(label, got, want):
    ok = got == want
    if not ok:
        FAIL.append(label)
    print(f"  {'✅' if ok else '❌'} {label:<50} = {got!r:<22} 预期 {want!r}")


class _B:
    title_bonus = {}


# 内容侧「整块面板函数」旧口（模拟既有包的 panel_fn）
def _old_panel_fn(class_name, level, equipment, tier, attrs, evolve, tb, race):
    return {"hp": 1000 + 10 * (level or 0), "atk": 50 + (level or 0),
            "src": f"旧口:{class_name}"}


# 新口：栈声明
STACK = {
    "version": 1,
    "base": {"mode": "value", "value": {"hp": 100, "atk": 12}},
    "layers": [
        {"id": "lv", "src": "等级成长", "group": "base", "mode": "add",
         "keys": ["hp", "atk"], "values": {"hp": 900, "atk": 88}},
        {"id": "gear", "src": "武器", "group": "gear", "mode": "add",
         "keys": ["atk"], "values": {"atk": 200}},
    ],
    "emit": {"int_keys": ["hp", "atk"]},
}


def main():
    actor = {"class_name": "WARDEN", "level": 10, "equipment": {}, "attributes": None,
             "class_tier": 0, "evolve_path": 0, "race": None}

    print("【态 A】不装 `panel_layers_fn` ⇒ 走原路 panel_fn（零回归路径）")
    config.set_hook("panel_fn", _old_panel_fn)
    config.set_hook("panel_layers_fn", None)
    chk("get_hook('panel_layers_fn') is None", config.get_hook("panel_layers_fn"), None)
    a = S._player_base_stats(_B(), actor)
    chk("面板来自旧口（hp = 1000 + 10×10）", a["hp"], 1100)
    chk("面板来自旧口（atk = 50 + 10）", a["atk"], 60)
    chk("面板带旧口的来源标签", a["src"], "旧口:WARDEN")
    print()

    print("【态 B】装 `panel_layers_fn` ⇒ 走新形状 PanelStack（同一段代码）")
    config.set_hook("panel_layers_fn", lambda sid: STACK if sid == "std" else None)
    actor_b = dict(actor, panel_stack="std")
    b = S._player_base_stats(_B(), actor_b)
    chk("面板来自栈（hp = 100 + 900）", b["hp"], 1000)
    chk("面板来自栈（atk = (12+88+200)）", b["atk"], 300)
    chk("旧口被**完全**绕过（没有 'src' 键）", "src" in b, False)
    chk("返回值是普通 dict（兼容下游 st.get 读法）", type(b).__name__, "dict")
    print()

    print("【态 B′】base.mode=actor ⇒ 从 actor 裸字段取基础值")
    st_actor_mode = {
        "version": 1,
        "base": {"mode": "actor", "keys": ["hp", "atk"]},
        "layers": [{"id": "g", "src": "装备", "group": "gear", "mode": "add",
                    "keys": ["atk"], "values": {"atk": 500}}],
        "emit": {"int_keys": ["hp", "atk"]},
    }
    config.set_hook("panel_layers_fn", lambda sid: st_actor_mode)
    c = S._player_base_stats(_B(), dict(actor, panel_stack="x", hp=777, atk=33))
    chk("基础值从 actor 取（hp=777）", c["hp"], 777)
    chk("基础值从 actor 取 + 层作用（atk=33+500）", c["atk"], 533)
    print()

    print("【fail-closed】装了新口但 actor 不配合 ⇒ 必须点名报错")
    # ★ hook 必须对**未知 sid** 返 None（否则"栈不存在"这一条根本测不到）
    config.set_hook("panel_layers_fn", lambda sid: STACK if sid == "std" else None)
    try:
        S._player_base_stats(_B(), actor)            # 没有 panel_stack
        print("  ❌ 缺 panel_stack 居然通过了")
        FAIL.append("缺 panel_stack")
    except PanelDeclError as e:
        print(f"  ✅ 缺 panel_stack ⇒ {str(e)[:66]}")
    try:
        S._player_base_stats(_B(), dict(actor, panel_stack="nope"))   # 栈不存在
        print("  ❌ 栈不存在 居然通过了")
        FAIL.append("栈不存在")
    except PanelDeclError as e:
        print(f"  ✅ 栈不存在   ⇒ {str(e)[:66]}")
    # base.mode=actor 但 actor 没那些键
    config.set_hook("panel_layers_fn", lambda sid: st_actor_mode if sid == "am" else None)
    try:
        S._player_base_stats(_B(), dict(actor, panel_stack="am"))     # 无 hp/atk
        print("  ❌ actor 缺声明键 居然通过了")
        FAIL.append("actor 缺键")
    except PanelDeclError as e:
        print(f"  ✅ actor 缺声明键 ⇒ {str(e)[:66]}")

    # 复位（避免影响同进程其它检查）
    config.set_hook("panel_layers_fn", None)

    print("\n" + "=" * 66)
    if FAIL:
        print(f"E2-P2 ✗ 未过（{len(FAIL)} 项）：{FAIL}")
        return 1
    print("E2-P2 ✅ 全绿（两态切换正确 + mode=actor/value 都对 + 3 条 fail-closed 点名）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
