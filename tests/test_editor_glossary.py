# -*- coding: utf-8 -*-
"""字段词典门禁（editor/glossary.py）。

守住三条（对应「字段加翻译 / 加注脚 / 能跳文档」这个需求的质量底线）：
  1. **覆盖率**：schema 里每个能被表单渲染的字段，都要有中文名。少一个 = 用户看到英文。
     ★ 2026-09-13 B2b：框架内置集**只留 8 个引擎域**（`G.DOMAIN_SCHEMA` 随之内缩）；
     内容域（skills / items …）的「面板不空白」改由**包这一层**守（见下面「旗舰包合成覆盖」）。
  2. **出处不许编**：词典里的每条 wiki 引用，页面必须存在、`find` 词必须真在页里
     （否则点「📖 打开文档」跳过去什么都没有——比没有链接更糟）。
  3. **报错翻译**：schema 英文报错 → 中文可读，且带字段中文名（用户「不知道什么规则」的正面回答）。

跑法：python tests/test_editor_glossary.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

from editor import glossary as G          # noqa: E402
from editor import packages as PK         # noqa: E402

# 框架词典（第 3 层，**未随内置集瘦身**）里带默认词条的域；"*" = 通用叶名那份
FW_VOCAB_DOMAINS = set(G.GLOSSARY) - {"*"}

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


def field_paths(fname: str) -> list:
    """schema 里会被表单渲染出来的字段路径（与 schema_form.js 的渲染规则对齐）。"""
    s = json.load(open(os.path.join(ROOT, "schemas", fname), encoding="utf-8"))
    out = []

    def walk(props, pre):
        for k, v in props.items():
            out.append(pre + k)
            if isinstance(v, dict) and isinstance(v.get("properties"), dict):
                walk(v["properties"], pre + k + ".")
    for _name, d in (s.get("$defs") or {}).items():
        walk(d.get("properties") or {}, "")
    return list(dict.fromkeys(out))


def _fields_in(path: str) -> list:
    """任意 schema 文件（含包内那份）里会被表单渲染的字段路径（口径同 `field_paths`）。"""
    s = json.load(open(path, encoding="utf-8"))
    out: list = []

    def walk(props, pre):
        for k, v in (props or {}).items():
            out.append(pre + k)
            if isinstance(v, dict) and isinstance(v.get("properties"), dict):
                walk(v["properties"], pre + k + ".")

    for _name, d in (s.get("$defs") or {}).items():
        walk(d.get("properties") or {}, "")
    return list(dict.fromkeys(out))


def top_keys(fname: str) -> list:
    """顶层字段名（分组只管顶层；嵌套子键在它所属对象的卡片里渲染）。"""
    s = json.load(open(os.path.join(ROOT, "schemas", fname), encoding="utf-8"))
    out = []
    for _name, d in (s.get("$defs") or {}).items():
        for k in (d.get("properties") or {}):
            if k not in out:
                out.append(k)
    return out


def main() -> int:
    print("== 字段词典门禁 ==")

    # 1. 覆盖率：每个字段都有中文名
    total = 0
    nozh = []
    for dom, fname in G.DOMAIN_SCHEMA.items():
        for p in field_paths(fname):
            total += 1
            e = G.lookup(dom, p)
            if not e or not e.get("zh"):
                nozh.append(f"{dom}.{p}")
    check(f"字段中文名覆盖 {total} 个字段（0 缺口）", not nozh, f"缺：{nozh[:12]}")

    # ★ 2026-09-13 收口：**包侧词汇表**上线后，「面板不空白」的覆盖口径 = 框架默认 ∪ 包声明。
    #   字段的真源在包（`<pkg>/editor/glossary/<域>.json`），框架那份只是回退；所以旗舰包必须
    #   逐域逐字段都能查到中文名（来自哪一层不限），否则编辑器里会有裸字段。
    pk_dir = os.path.join(ROOT, "games", "orlandia")
    if os.path.isdir(pk_dir):
        print("\n-- 旗舰包 games/orlandia：框架默认 ∪ 包声明的合成覆盖")
        total_p, gaps_p = 0, []
        for dom, meta in PK.effective_domains(pk_dir)[0].items():
            fn = meta.get("schema")
            if not fn:
                continue
            for rel in (os.path.join("schemas", fn), fn):
                fp = os.path.join(pk_dir, rel)
                if os.path.isfile(fp):
                    break
            else:
                continue
            for p in _fields_in(fp):
                total_p += 1
                e = G.lookup(dom, p, pk_dir)
                if not e or not e.get("zh"):
                    gaps_p.append(f"{dom}.{p}")
        check(f"旗舰包合成覆盖 {total_p} 个字段（0 缺口；中文名可来自框架默认或包词汇表）",
              not gaps_p, f"缺：{gaps_p[:12]}")
        check("包词汇表零告警（坏声明不静默）", G.glossary_warnings(pk_dir) == [],
              G.glossary_warnings(pk_dir))

    # 2. 出处门禁：wiki 页面存在 + find 词真的在页里
    refs = 0
    bad = []
    for dom, tbl in G.GLOSSARY.items():
        for key, ent in tbl.items():
            ref = ent.get("ref")
            if not ref:
                continue
            refs += 1
            page, term = ref
            fp = G.wiki_path(page)
            if not os.path.isfile(fp):
                bad.append(f"{dom}.{key} → 页面不存在 {page}")
                continue
            if term not in open(fp, encoding="utf-8").read():
                bad.append(f"{dom}.{key} → {page} 里没有「{term}」")
    check(f"wiki 引用可解析（{refs} 条，逐条核到页内文字）", not bad, f"坏引用：{bad[:6]}")

    # 3. 没出处也要有注脚（不许留空壳）
    hollow = [f"{dom}.{k}" for dom, tbl in G.GLOSSARY.items()
              for k, e in tbl.items() if not (e.get("note") or "").strip()]
    check("每条词典都有注脚（没文档出处的也不留空）", not hollow, f"空注脚：{hollow[:8]}")

    # 4. 「静默不生效」类字段被标注（这批字段最坑，必须显式提示）
    #    2026-09-11：debuff_scale / period.dmg_type 已接线（标注转 ✅）→ 从名单移除。
    #    名单 = 当前**仍未接线**的死字段；接线一个就从这里删一个、发现新的就加进来。
    _KNOWN_DEAD = ["on_threshold", "period.per_layer", "period.type"]
    deadish = [k for k, e in G.GLOSSARY["effect_rules"].items()
               if "无消费者" in (e.get("note") or "")]
    check(f"死字段已标注（{len(deadish)} 个：{', '.join(sorted(deadish))}）",
          sorted(deadish) == sorted(_KNOWN_DEAD),
          f"实际={sorted(deadish)} 期待={sorted(_KNOWN_DEAD)}")

    # 5. 报错翻译：原始形态 + dict 形态
    f1 = G.friendly("skills", ["desc: '' should be non-empty"])
    check("英文报错 → 中文", bool(f1) and "不能为空" in f1[0]["message"], f"{f1}")
    check("中文报错带字段中文名", "描述" in f1[0]["display"], f"{f1[0].get('display')}")
    f2 = G.friendly("skills", [{"path": "lv", "message": "1 is less than the minimum of 3"}])
    check("dict 形态 + 范围报错", "不能小于 3" in f2[0]["message"], f"{f2}")
    f3 = G.friendly("effect_rules", ["period.type: is not one of ['a', 'b']"])
    check("枚举报错带允许值", "必须是" in f3[0]["message"] and "a" in f3[0]["message"], f"{f3}")

    # 6. 必填体检（新建条目被拦的真原因就该由它说清楚）
    schema = json.load(open(os.path.join(ROOT, "schemas", "skill.schema.json"), encoding="utf-8"))
    sdef = schema["$defs"]["skill"]
    miss = G.missing_required("skills", {"kind": "魔法"}, sdef)
    paths = [m["path"] for m in miss]
    check("必填体检列全（name/desc/lv，kind 已给不算）",
          sorted(paths) == ["desc", "lv", "name"], f"{paths}")
    check("必填体检顺序 = schema.required 顺序（定位时从上往下走）",
          paths == [k for k in sdef["required"] if k != "kind"], f"{paths}")
    labels = {m["path"]: m["label"] for m in miss}
    check("必填体检带中文名", labels == {"name": "名称", "lv": "技能等级", "desc": "描述"}, f"{labels}")
    check("补全后无必填缺口",
          not G.missing_required("skills", {"name": "x", "desc": "d", "lv": 1, "kind": "魔法"}, sdef))

    # 7. 查询回退顺序：域内精确 → 域内叶名 → 通用叶名
    a = G.lookup("effect_rules", "period.dir")
    check("精确路径优先（period.dir ≠ 通用 dir）",
          a and a["zh"] == "周期方向" and a.get("matched") == "period.dir", f"{a}")
    b = G.lookup("monsters", "name")
    check("叶名回退到通用（monsters.name → 名称）", b and b["zh"] == "名称" and b.get("generic"), f"{b}")
    check("未知字段 → None", G.lookup("skills", "no_such_field_xyz") is None)

    # 8. 前端消费的形态
    all_e = G.all_entries()
    check("all_entries 覆盖 7 域（含通用）", set(all_e) >= {"*", "skills", "effect_rules", "passive_proc"})
    check("wiki 深链格式 = wiki:页#find=词",
          G.ref_url(G.GLOSSARY["effect_rules"]["cap"]) == "wiki:reference/effect-rules.md#find=cap",
          G.ref_url(G.GLOSSARY["effect_rules"]["cap"]))
    check("无出处字段不产出链接", G.ref_url(G.GLOSSARY["skills"]["buff_turns"]) is None)

    # 9. 表单分组（字段按语义分块）
    uncovered, ghost, no_label, dup_ids, empty = [], [], [], [], []
    for dom, fname in G.DOMAIN_SCHEMA.items():
        keys = top_keys(fname)
        gs = G.groups_for(dom)
        listed = [k for g in gs for k in g["fields"]]
        uncovered += [f"{dom}.{k}" for k in keys if k not in listed]
        ghost += [f"{dom}.{k}" for k in listed if k not in keys]
        dup_ids += [f"{dom}.{g['id']}" for g in gs if
                    [x["id"] for x in gs].count(g["id"]) > 1]
        no_label += [f"{dom}.{g['id']}" for g in gs if not g.get("label")]
        empty += [f"{dom}.{g['id']}" for g in gs if not g.get("fields")]
    total_top = sum(len(top_keys(f)) for f in G.DOMAIN_SCHEMA.values())
    check(f"顶层字段全部分到组里（{total_top} 个，无「未分组」残渣）", not uncovered, f"漏：{uncovered[:8]}")
    check("分组里没有 schema 不存在的字段（防拼错）", not ghost, f"幽灵：{ghost[:8]}")
    check("分组 id 唯一且都有标签", not dup_ids and not no_label, f"{dup_ids[:4]} {no_label[:4]}")
    check("没有空分组", not empty, f"{empty}")
    check(f"分组数与规模合理（{len(G.DOMAIN_SCHEMA)} 域 ≥ 3 组/域）",
          all(len(G.groups_for(d)) >= 3 for d in G.DOMAIN_SCHEMA), 
          {d: len(G.groups_for(d)) for d in G.DOMAIN_SCHEMA})
    check("groups_for 返回深拷贝（改调用方不污染全局）",
          (lambda a: (a[0]["fields"].append("__x__"), "__x__" not in G.groups_for("skills")[0]["fields"])[1])(
              G.groups_for("skills")))
    # ★ B2b：`G.DOMAIN_SCHEMA` 从**内置域集**派生（只留 8 个引擎域），而框架词典 `GROUPS`
    #   仍为内容域保留默认分组（第 3 层未随瘦身）→ 两者不再等价。口径改成两条：
    #     ① 每个内置引擎域（有 schema）必须有分组；
    #     ② 框架词典里出过词条的每个域也必须有分组（防漏分组 / 拼错域名）。
    check(f"all_groups 覆盖全部 {len(G.DOMAIN_SCHEMA)} 个内置（引擎）域",
          set(G.DOMAIN_SCHEMA) <= set(G.all_groups()),
          sorted(set(G.DOMAIN_SCHEMA) - set(G.all_groups())))
    check(f"框架词典的 {len(FW_VOCAB_DOMAINS)} 个域都有分组（内容域词条仍在框架默认层）",
          FW_VOCAB_DOMAINS <= set(G.all_groups()),
          sorted(FW_VOCAB_DOMAINS - set(G.all_groups())))

    # 10. 控件形态与跨域引用（长文案给大框 / 比值给滑杆 / 引用取真 key）
    ALLOWED = {"textarea", "lines", "chips", "pct"}
    bad_w = [f"{d}.{k}={w}" for d, tbl in G.all_widgets().items()
             for k, m in tbl.items() if m.get("widget") and m["widget"] not in ALLOWED]
    check(f"控件形态取值合法（{sorted(ALLOWED)}）", not bad_w, f"{bad_w[:5]}")
    check("长文案字段给大框（desc / flavor / heal_formula）",
          all(G.widget_for(d, k) == "textarea"
              for d, f in G.DOMAIN_SCHEMA.items()
              for k in top_keys(f) if k in ("desc", "flavor", "heal_formula")),
          {d: [k for k in top_keys(f) if G.widget_for(d, k) == "textarea"]
           for d, f in G.DOMAIN_SCHEMA.items()})
    check("表达式列表给「一行一条」", G.widget_for("skills", "exprs") == "lines")
    check("0~1 比值给滑杆", all(G.widget_for("skills", k) == "pct"
                                for k in ("mech_chance", "lifesteal"))
          and G.widget_for("effect_rules", "guard_hp_pct") == "pct")
    check("枚举数组给多选标签", G.widget_for("affixes", "qualities") == "chips")
    # ★ B2b：框架默认引用表指向的域可能是**内容域**（不在内置集里）—— 真源在包，
    #   所以判据 = 内置引擎域 ∪ 旗舰内容包声明的域（orlandia 的 editor/domains.json）。
    _fp = os.path.join(ROOT, "games", "orlandia")
    KNOWN_DOMAINS = set(PK.DOMAINS) | set(PK.effective_domains(_fp)[0])
    bad_ref = [f"{k}→{v}" for k, v in G.REF_DOMAINS.items() if v not in KNOWN_DOMAINS]
    check(f"跨域引用指向的域都真实存在（判据 = 内置 {len(PK.DOMAINS)} 引擎域 ∪ 旗舰包声明的域）",
          not bad_ref, f"{bad_ref}")
    check("引用类字段解析出目标域（monsters.skills → skills / start_classes → classes）",
          G.ref_domain_for("monsters", "skills") == "skills"
          and G.ref_domain_for("effect_rules", "start_classes") == "classes"
          and G.ref_domain_for("passive_proc", "cap_key") == "effect_rules")
    check("非引用字段不误判（skills.kind 不是引用）", G.ref_domain_for("skills", "kind") is None)
    check("面板键候选存在且都是框架协议名（ASCII）",
          G.PANEL_KEYS and all(str(k).isascii() for k in G.PANEL_KEYS), f"{G.PANEL_KEYS}")
    check("stat_scale 标记 panel（用面板键做候选）", G.suggest_meta("effect_rules", "stat_scale")["panel"])

    print(f"\n{'-' * 46}\n通过 {PASS} / 失败 {FAIL}")
    for f in FAILURES:
        print("  ❌", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
