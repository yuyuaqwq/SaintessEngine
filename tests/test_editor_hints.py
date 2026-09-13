# -*- coding: utf-8 -*-
"""编辑提示（editor/hints.py）回归 —— 联想候选必须**真来自包内数据**。

守的底线
--------
1. **诚实**：refs 是该域真 key；values 是该字段真出现过的取值；keys 是对象字段真用过的键。
   （联想列表里出现包内不存在的东西 = 引导用户填错，比不给联想更糟。）
2. **排序**：出现频次高的在前（常用写法先出现）。
3. **不硬编码游戏词汇**：hints 只搬运包内数据，框架里零游戏名词（另有中立性门禁兜底）。
4. **空包不炸**：新包（全空表）→ 三类都是空，前端退回纯手填。

跑法：python tests/test_editor_hints.py
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

from editor import hints as HN          # noqa: E402
from editor import packages as PK       # noqa: E402
import _domain_fixtures as FX           # noqa: E402  （内容域只能由包声明：B2b）

PASS = 0
FAIL = 0
FAILURES = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        FAILURES.append(f"{name} {detail}")
        print(f"  ❌ {name} {detail}")


def main() -> int:
    print("== 编辑提示（联想候选）回归 ==")
    gd = tempfile.mkdtemp(prefix="fw_hints_")
    try:
        pkg = os.path.join(gd, "t_game")
        os.makedirs(os.path.join(pkg, "content", "data"), exist_ok=True)
        os.makedirs(os.path.join(pkg, "content", "rules"), exist_ok=True)
        # ★ B2b：skills / items / monsters 是**内容域**（框架内置集只留引擎域）→ 由包声明
        FX.declare(pkg, "skills", "items", "monsters")
        PK.write_json(PK.manifest_path(pkg), {"id": "t_game", "name": "t", "engine": ">=0.1",
                                              "domains": list(PK.DOMAINS)
                                              + ["skills", "items", "monsters"]})
        PK.write_json(PK.domain_path(pkg, "skills"), {
            "sk_fire": {"name": "火球", "kind": "魔法", "lv": 1, "desc": "d",
                        "exprs": ["matk*1.4"], "res_cost": {"mana": 3}},
            "sk_hit": {"name": "重击", "kind": "物理", "lv": 1, "desc": "d",
                       "exprs": ["atk*1.2"], "chance": 0.25},
            "sk_heal": {"name": "治疗", "kind": "魔法", "lv": 2, "desc": "d"},
        })
        PK.write_json(PK.domain_path(pkg, "items"), {
            "it_potion": {"name": "药水", "desc": "d", "price": 10},
        })
        PK.write_json(PK.domain_path(pkg, "monsters"), {
            "mob_1": {"name": "小怪", "kind": "normal", "desc": "d", "skills": ["火球"], "drops": ["药水"]},
        })
        PK.write_json(PK.domain_path(pkg, "effect_rules"), {
            "burn": {"name": "灼烧", "cap": 3, "channels": {"attack_hit": 1}, "stat_scale": {"atk": 0.03}},
            "haste": {"name": "疾行", "channels": {"turn_start": 1}},
        })
        # 空包（只有清单）
        empty = os.path.join(gd, "empty")
        os.makedirs(empty, exist_ok=True)
        PK.write_json(PK.manifest_path(empty), {"id": "empty", "name": "e"})

        h = HN.build(pkg)

        # 1. refs = 真 key
        check("refs.skills = 真技能 key（排序稳定）",
              h["refs"]["skills"] == ["sk_fire", "sk_heal", "sk_hit"], f"{h['refs']['skills']}")
        check("refs.items 含真物品 key", h["refs"]["items"] == ["it_potion"], f"{h['refs']['items']}")
        check("refs 覆盖全部 7 域（没数据的域 = 空表）",
              all(d in h["refs"] for d in PK.DOMAINS), f"{sorted(h['refs'])}")

        # 2. values = 真取值 + 频次排序
        kinds = h["values"]["skills"]["kind"]
        check("自由串取值（kind：魔法 2 次 > 物理 1 次）", kinds == ["魔法", "物理"], f"{kinds}")
        check("数值也算取值（chance=0.25 记到它自己的路径）",
              h["values"]["skills"].get("chance") == ["0.25"], f"{h['values']['skills'].get('chance')}")
        check("嵌套路径单独记（不糊到父字段）",
              h["values"]["skills"].get("res_cost.mana") == ["3"]
              and "res_cost" not in h["values"]["skills"], f"{list(h['values']['skills'])[:6]}")
        check("数组元素记在数组路径下（skills 里的技能名）",
              h["values"]["monsters"].get("skills") == ["火球"], f"{h['values']['monsters'].get('skills')}")
        check("布尔/空串不进候选（不给人添乱）",
              not [p for p, vs in h["values"]["skills"].items() if "" in vs])

        # 3. keys = 对象字段真用过的键
        ch = h["keys"]["effect_rules"].get("channels")
        check("对象字段用过的键（channels：attack_hit / turn_start）",
              sorted(ch or []) == ["attack_hit", "turn_start"], f"{ch}")
        check("stat_scale 的键（atk）", h["keys"]["effect_rules"].get("stat_scale") == ["atk"],
              f"{h['keys']['effect_rules'].get('stat_scale')}")

        # 4. 前端形态
        ui = HN.flatten_for_ui(h)
        check("flatten 给字段级 {v,k}（可一次查）",
              ui["fields"]["skills"]["kind"]["v"] == ["魔法", "物理"]
              and ui["fields"]["effect_rules"]["channels"]["k"] == ["attack_hit", "turn_start"],
              f"{ui['fields']['skills'].get('kind')} / {ui['fields']['effect_rules'].get('channels')}")
        check("flatten 带上 refs", ui["refs"]["skills"] == ["sk_fire", "sk_heal", "sk_hit"])

        # 5. 上限与空包
        check("候选截断在 60 条内（不把界面撑爆）",
              all(len(v) <= 60 for dom in h["values"].values() for v in dom.values()))
        he = HN.build(empty)
        check("空包不炸：三类皆空",
              all(not he["values"][d] for d in PK.DOMAINS) and all(not he["values"][d] for d in he["values"]))
        check("空包 refs 也是空表（不是缺键）", all(he["refs"][d] == [] for d in PK.DOMAINS))

        # 6. 键名重复出现时排序（多条目都用 attack_hit → 排前）
        PK.write_json(PK.domain_path(pkg, "effect_rules"), {
            "a": {"name": "A", "channels": {"skill_hit": 1}},
            "b": {"name": "B", "channels": {"skill_hit": 1}},
            "c": {"name": "C", "channels": {"attack_hit": 1}},
        })
        h2 = HN.build(pkg)
        check("常用键排前（skill_hit 2 次 > attack_hit 1 次）",
              h2["keys"]["effect_rules"]["channels"] == ["skill_hit", "attack_hit"],
              f"{h2['keys']['effect_rules']['channels']}")
    finally:
        shutil.rmtree(gd, ignore_errors=True)

    print(f"\n{'-' * 46}\n通过 {PASS} / 失败 {FAIL}")
    for f in FAILURES:
        print("  ❌", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
