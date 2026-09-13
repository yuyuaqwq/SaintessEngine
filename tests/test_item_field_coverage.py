#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：包数据里的字段必须都在 schema 里声明（防「字段在编辑器里降级成 JSON 兜底」）。

为什么需要
----------
编辑器表单是 **schema 驱动** 的：schema 没声明的键在表单里没有专属控件、不进分组、
词典里也查不到中文名 —— 它只能落在折叠的「其他字段（schema 未声明，N 项）」JSON 兜底里。
也就是说：字段还留着，但**看不见、改不动、也没法按字段校验**；用户在兜底框里手改一次就
可能把它改没了。物品域做过一次全字段审计（参考实现 ITEMS/MATERIALS/CONSUMABLES 三表的
25 个字段逐个对 schema 核过，结论：0 缺口），本门禁把那次的结论固化成**可复跑**的检查：
以后往包数据里加字段、或改 schema 时，这里会直接红。

判据（数据 → schema 单向覆盖）
------------------------------
  1. 条目顶层键必须能在该域 schema 主 def 的 `properties` 里找到
  2. 已声明为对象（带 `properties`）的字段 → 递归检查子键
  3. 已声明为「对象数组」（`items` 带 `properties`）的字段 → 递归检查每个元素
  4. 自由结构（没有 `properties`，只声明 additionalProperties）→ **跳过**
     —— 表单对这类字段走 JSON 兜底渲染，键不会丢，所以不该在 schema 里逐个声明
  5. `required` 声明的字段必须在每条数据里出现（否则编辑器一点保存就被 schema 拦住）

严格域 vs 提示域
----------------
本门禁**只对 `STRICT_DOMAINS` 判红**（当前 = items：本次交付范围，已核到 0 缺口）。
其它域若也扫出未声明键，按 ⚠ 提示列出、不影响退出码 —— 那一侧的数据/ schema 归属别的
交付，等裁决后再把它加进 STRICT_DOMAINS（一行的事）。

覆盖范围：`games/<包>/content/{data,rules}/<域>.json`（域名 → schema 取自 editor/packages.py）。
本门禁只做结构对账，不评判值的语义 —— 语义归字段词典（editor/glossary.py）。

★ 2026-09-13 B2b：域的真源在包（框架内置集只留 8 个引擎域，内容域不内置）。
本门禁的扫描面因此从「内置域集」改成**每个包自己的有效域表**：schema 也按该包解析
（`packages.schema_path()`，包内优先 → 框架回退）。这样内容域（items / skills …）
照样被扫，而且扫的是这个包**自己**那份 schema —— 比改造前更准。

跑法：python tests/test_item_field_coverage.py
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
if FW_ROOT not in sys.path:
    sys.path.insert(0, FW_ROOT)
sys.path.insert(0, os.path.join(FW_ROOT, "editor"))

import editor.packages as PK          # noqa: E402
import editor.glossary as G           # noqa: E402

passed = failed = 0

REAL_PKG = os.path.join(FW_ROOT, "games", "orlandia")      # 内容域的真源样板（24 域）

# 判红的域（本次交付范围：物品域已核到 0 缺口）。其它域的同类差异先按 ⚠ 提示列出。
STRICT_DOMAINS = ("items",)


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name} {detail}")


def undeclared_keys(data, schema, pre=""):
    """数据里出现、但 schema 未声明的键路径（自由结构跳过）。"""
    bad = []
    props = schema.get("properties") or {}
    if not isinstance(data, dict):
        return bad
    for k, v in data.items():
        sub = props.get(k)
        if sub is None:
            bad.append(pre + str(k))
            continue
        if not isinstance(sub, dict):
            continue
        if isinstance(sub.get("properties"), dict):
            bad += undeclared_keys(v, sub, f"{pre}{k}.")
        elif (sub.get("type") == "array" and isinstance(sub.get("items"), dict)
                and isinstance(sub["items"].get("properties"), dict)):
            for el in (v if isinstance(v, list) else []):
                bad += undeclared_keys(el, sub["items"], f"{pre}{k}[].")
    return bad


def _allows_null(schema) -> bool:
    """该字段的 schema 是否**显式允许 null**（`type` 里含 "null"，或任何一支 anyOf/oneOf 允许）。"""
    if not isinstance(schema, dict):
        return False
    t = schema.get("type")
    if t == "null" or (isinstance(t, list) and "null" in t):
        return True
    for key in ("anyOf", "oneOf"):
        for sub in (schema.get(key) or []):
            if _allows_null(sub):
                return True
    return False


def missing_required(data, schema, pre=""):
    """schema.required 里声明、但数据缺的字段路径（**只查已声明的对象层级**）。

    ⚠️ 2026-09-13 修：原来把 `值 is None` 也算「缺」—— 但 JSON Schema 的 `required` 只管
    **键在不在**，「必填但可空」是合法组合（`type: ["integer","null"]`：键必须在，值可以是 null，
    编辑器**不会**因此被拦）。原来的口径比编辑器更严 → 对「隐藏怪专属条目 lv 用 null」这类
    正当数据**假红**。现在：值为 null 只在 schema **不允许 null** 时才算缺。
    """
    out = []
    if not isinstance(data, dict):
        return out
    props = schema.get("properties") or {}
    for k in (schema.get("required") or []):
        if k not in data:
            out.append(pre + str(k))
            continue
        v = data[k]
        if v is None and not _allows_null(props.get(k)):
            out.append(pre + str(k))
        elif isinstance(v, str) and v.strip() == "":
            out.append(pre + str(k))
    for k, sub in (schema.get("properties") or {}).items():
        if not isinstance(sub, dict) or k not in data:
            continue
        if isinstance(sub.get("properties"), dict):
            out += missing_required(data[k], sub, f"{pre}{k}.")
        elif (sub.get("type") == "array" and isinstance(sub.get("items"), dict)
                and isinstance(sub["items"].get("properties"), dict)):
            for el in (data[k] if isinstance(data[k], list) else []):
                out += missing_required(el, sub["items"], f"{pre}{k}[].")
    return out


def load_schema(dom, pkg_dir=None):
    """该域在**这个包视角下**的 schema 主 def（包内优先 → 框架回退）。

    ★ B2b：不带包时只认内置（引擎）域 —— 内容域必须带包目录（真源在包）。
    """
    meta = PK.domain_meta(pkg_dir, dom) or {}
    fname = meta.get("schema")
    if not fname:
        return None, None
    path = PK.schema_path(pkg_dir, dom)
    if not path or not os.path.exists(path):
        return None, fname
    doc = json.load(open(path, encoding="utf-8"))
    defs = doc.get("$defs") or {}
    prim = doc.get("x-primary") or meta.get("primary")
    d = defs.get(prim) if prim else None
    if not isinstance(d, dict) or not isinstance(d.get("properties"), dict):
        d = next((x for x in defs.values()
                  if isinstance(x, dict) and isinstance(x.get("properties"), dict)), None)
    return d, fname


def schema_top_keys(fname):
    """schema 里会被表单渲染出来的顶层字段名（与 tests/test_editor_glossary.py 同口径）。"""
    s = json.load(open(os.path.join(FW_ROOT, "schemas", fname), encoding="utf-8"))
    out = []
    for _name, d in (s.get("$defs") or {}).items():
        for k in (d.get("properties") or {}):
            if k not in out:
                out.append(k)
    return out


def package_dirs():
    root = PK.ensure_games_dir()
    out = []
    for name in sorted(os.listdir(root)):
        p = os.path.join(root, name)
        if os.path.isdir(p):
            out.append(p)
    return out


def main():
    print("== 包数据字段覆盖门禁（数据 → schema） ==")

    # 1. 检查器自检（防「永远绿」的空转）：故意带未声明键的合成数据必须被抓出来
    fix_schema = {
        "required": ["a"],
        "properties": {"a": {"type": "string"},
                       "obj": {"type": "object", "properties": {"x": {"type": "string"}}},
                       "free": {"type": "object", "additionalProperties": True},
                       "arr": {"type": "array", "items": {"type": "object",
                                                          "properties": {"y": {"type": "string"}}}}},
    }
    good = {"a": "1", "obj": {"x": "1"}, "free": {"任意键": 1}, "arr": [{"y": "1"}]}
    bad_data = {"a": "1", "obj": {"x": "1", "偷偷加的": 1}, "free": {"任意键": 1},
                "arr": [{"y": "1"}], "顶层野字段": 1}
    check("检查器自检：合法数据 0 报错", undeclared_keys(good, fix_schema) == [],
          f"{undeclared_keys(good, fix_schema)}")
    got = sorted(undeclared_keys(bad_data, fix_schema))
    check("检查器自检：抓到顶层 + 嵌套未声明键", got == ["obj.偷偷加的", "顶层野字段"], f"{got}")
    check("检查器自检：自由结构键不误报（JSON 兜底渲染，不丢）",
          all("free." not in x for x in got), f"{got}")
    check("检查器自检：required 缺失能报", missing_required({"a": ""}, fix_schema) == ["a"],
          f"{missing_required({'a': ''}, fix_schema)}")
    # required 的语义 = 键在不在（JSON Schema 口径）；「必填但可空」不该被误报
    nullable = {"required": ["lv"], "properties": {"lv": {"type": ["integer", "null"]}}}
    not_nullable = {"required": ["lv"], "properties": {"lv": {"type": "integer"}}}
    check("检查器自检：必填 + 可空（type 含 null）→ 值为 null **不算缺**",
          missing_required({"lv": None}, nullable) == [], f"{missing_required({'lv': None}, nullable)}")
    check("检查器自检：必填 + 不可空 → 值为 null 算缺",
          missing_required({"lv": None}, not_nullable) == ["lv"],
          f"{missing_required({'lv': None}, not_nullable)}")
    check("检查器自检：键整个缺失 → 两种 schema 下都算缺",
          missing_required({}, nullable) == ["lv"] and missing_required({}, not_nullable) == ["lv"])

    # 2. schema 侧体检：物品域的 primary def 可解析
    #    ★ B2b：items 是**内容域** —— schema 由包提供（orlandia 自带 `schemas/item.schema.json`）
    item_def, item_fname = load_schema("items", REAL_PKG)
    check("items 域 schema 可解析（$defs + properties；包声明 + 包内 schema 优先）",
          bool(item_def), f"{item_fname}")
    check("items 域框架侧不再是内置域（真源在包）", "items" not in PK.DOMAINS)
    if not item_def:
        return finish()

    # 3. 逐包逐域对账
    scanned = entries = 0
    bad_cov, bad_req, unreadable = [], [], []
    soft = []
    for pkg_dir in package_dirs():
        pkg = os.path.basename(pkg_dir)
        # ★ B2b：扫描面 = **该包自己的有效域表**（内置引擎域 ∪ 包声明的内容域）——
        #   过去问内置域集，瘦身后会漏掉 items/skills 这些内容域的数据。
        for dom in sorted(PK.effective_domains(pkg_dir)[0]):
            sdef, fname = load_schema(dom, pkg_dir)
            if not sdef:
                continue
            path = PK.domain_path(pkg_dir, dom)
            if not os.path.exists(path):
                continue
            try:
                data = json.load(open(path, encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                unreadable.append(f"{pkg}/{dom}: {e}")
                continue
            if not isinstance(data, dict):
                continue
            scanned += 1
            entries += len(data)
            sink = bad_cov if dom in STRICT_DOMAINS else soft
            for key, ent in data.items():
                if not isinstance(ent, dict):
                    sink.append(f"{pkg}/{dom}/{key} 不是对象")
                    continue
                for p in undeclared_keys(ent, sdef):
                    sink.append(f"{pkg}/{dom}/{key}.{p}")
                for p in missing_required(ent, sdef):
                    bad_req.append(f"{pkg}/{dom}/{key}.{p}")
    check(f"包数据均可解析（{scanned} 个域文件 / {entries} 条条目）", not unreadable, f"{unreadable[:4]}")
    check(f"严格域（{'/'.join(STRICT_DOMAINS)}）数据字段全覆盖于 schema（未声明键 0 个）",
          not bad_cov, f"未声明：{sorted(set(bad_cov))[:10]}")
    check("schema.required 在数据里都满足（缺了会被编辑器拦）",
          not bad_req, f"缺失：{sorted(set(bad_req))[:10]}")
    check("门禁真的扫到了数据（不是空转）", scanned > 0 and entries > 0,
          f"scanned={scanned} entries={entries}")
    if soft:
        print(f"  ⚠ 提示（非严格域，未计入失败）：{len(set(soft))} 处未声明键，"
              f"例：{sorted(set(soft))[:6]}")
        print("     → 这些字段在编辑器里只能靠「其他字段」JSON 兜底编辑；"
              "裁决后把该域加进 STRICT_DOMAINS 即可判红。")

    # 4. 物品域单点确认：schema 声明的字段名与词典字段名一一对上（含顶层分组）
    top = schema_top_keys("item.schema.json")
    keys_from_glossary = [k for g in G.groups_for("items") for k in g["fields"]]
    check(f"物品域 schema 字段全部有中文名（{len(top)} 个）",
          all((G.lookup("items", k) or {}).get("zh") for k in top),
          f"{[k for k in top if not (G.lookup('items', k) or {}).get('zh')]}")
    check("物品域 schema 字段全部分到表单分组（无「未分组」残渣）",
          sorted(set(top) - set(keys_from_glossary)) == [],
          f"漏：{sorted(set(top) - set(keys_from_glossary))}")

    return finish()


def finish():
    print(f"\n{'-' * 46}\n通过 {passed} / 失败 {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
