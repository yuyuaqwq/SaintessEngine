#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：框架编辑器「包自带词汇表」—— `<pkg>/editor/glossary/<域>.json`。

为什么需要
----------
字段的中文名/注脚/分组/控件过去是**框架侧硬编码**（`editor/glossary.py` 的
`GLOSSARY` / `GROUPS` / `WIDGETS`）—— 游戏专属词汇住在框架里 = 「加一个域就得改框架」。
本层把这三样也搬到包侧，与第 2 层（`editor/relations.json`）同一套纪律：

    <pkg>/editor/glossary/<域>.json     fields（zh/note/widget/group/ref）+ groups

**包声明 > 框架默认**；包不声明时逐项等于改造前（框架那三份降级为默认值，不删）。

本门禁钉住五件事
----------------
  (a) **零回归**：包不声明（或缺目录）时逐项等于不带包；orlandia 没声明时照此
  (b) **包声明优先**：`lookup` / `all_entries` / `groups_for` / `all_groups` /
      `widget_for` / `all_widgets` / `suggest_meta` / `friendly` / `missing_required`
      都认包词汇表；`groups` 是**整表替换**（不合并）、`fields` 条目**整条替换**
      （不做字段级合并 —— 包写了 zh 没写 note 就是「这条没注脚」）
  (c) **坏声明不炸**：坏 JSON / 顶层非对象 / 未知域 / 元非对象 / widget 不在词表 /
      ref 形状不对 / 组形状不对 → 丢那部分 + 一条可读 warning，其余照用，绝不抛
  (d) **降级可见**：告警从 `glossary_warnings` 取；HTTP 面 `/api/glossary` 与包概览带回前端
  (e) **HTTP 零 500**：好包/坏包都 200；包词汇表的中文名进报错翻译与必填体检

跑法：python tests/test_editor_glossary_pkg.py
退出码：0 = 全过；1 = 有失败。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

from editor import glossary as GL          # noqa: E402
from editor import packages as PK          # noqa: E402
from editor import server as SRV           # noqa: E402
import _domain_fixtures as FX              # noqa: E402  （内容域只能由包声明：B2b）

REAL_ORLANDIA = os.path.join(ROOT, "games", "orlandia")

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


def req(base, method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(base + path, data=data, method=method,
                               headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(r, timeout=180) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"raw": raw}


# ───────────────────────── 测试用包 ─────────────────────────
NEW_DOMS = {"my_items": {"label": "自定物品", "kind": "data", "icon": "🎒",
                         "schema": "schemas/my_items.schema.json", "primary": "my_item"}}

MY_SCHEMA = {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "my_items",
             "$defs": {"my_item": {
                 "type": "object", "required": ["name"],
                 "properties": {"name": {"type": "string", "minLength": 1},
                                "tip": {"type": "string"},
                                "cost": {"type": "number"}},
                 "additionalProperties": True}}}

MY_DATA = {"k1": {"name": "示例物品", "tip": "旧提示", "cost": 3}}

# 干净的声明（(b) 用）：覆盖框架域 `items` + 包自带域 `my_items`
GOOD = {
    "items": {"fields": {
        "effect_data": {"zh": "包·效果参数", "note": "包侧注脚", "widget": "kv", "group": "use"},
        "desc": {"zh": "包·描述"},                                   # 只给 zh → 注脚不补
        "rid": {"zh": "包·产出 id", "ref": {"domain": "equip_roster", "by": "name"}},
        "pick_options.rid": {"zh": "包·选项产出 id"},                 # 精确路径优先
    }},
    "my_items": {
        "fields": {"name": {"zh": "包·名称", "note": "自定域注脚", "group": "base",
                            "wiki": ["reference/loot.md", "entries"]},
                   "cost": {"zh": "包·费用", "widget": "pct"},
                   "tip": {"zh": "包·提示", "widget": "textarea"}},
        "groups": [{"id": "base", "label": "包分组", "icon": "🧪", "fields": ["name", "cost"]},
                   {"id": "more", "label": "其它", "icon": "", "fields": ["tip"]}],
    },
}


def make_pkg(root, pid, *, domains=None, schemas=None, data=None, glossary=None,
             relations=None, extra_files=None):
    """建一个最小包。`glossary` = {域: 对象|原始字符串}（字符串按原字节写，喂坏 JSON 用）。

    默认带上 `my_items` 的 schema + 一条数据（坏声明包也要能继续编辑 = 门禁要验的那条）。
    """
    schemas = {"my_items.schema.json": MY_SCHEMA} if schemas is None else schemas
    data = {"my_items": MY_DATA} if data is None else data
    pkg = os.path.join(root, pid)
    os.makedirs(os.path.join(pkg, "content", "data"), exist_ok=True)
    # ★ B2b：本门禁的域名里 items / skills / equip_roster 是**内容域**（框架内置集只留引擎域）
    #   —— 只能由包声明；不声明的话包词汇表/引用会被整域忽略（那是设计行为，不是这里要测的）。
    content_decl = FX.declare(None, "items", "skills", "equip_roster")
    decl_default = {**content_decl, **NEW_DOMS}
    if isinstance(domains, str):
        decl_out = domains                                   # 原始字节（坏 JSON 用例）
    else:
        decl_out = {**content_decl, **(domains or NEW_DOMS)}
    PK.save_manifest(pkg, {"id": pid, "name": pid, "desc": "词汇表门禁", "engine": ">=0.1",
                           "domains": list(PK.DOMAINS) + list(decl_default),
                           "entry": "content/apply.py", "created": "2026-09-13 00:00:00"})
    drafts = [("editor/domains.json", decl_out),
              ("editor/relations.json", relations)]
    drafts += [("editor/glossary/%s.json" % d, obj) for d, obj in (glossary or {}).items()]
    for rel, obj in drafts:
        if obj is None:
            continue
        p = os.path.join(pkg, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(obj if isinstance(obj, str)
                    else json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    for rel, text in (extra_files or {}).items():                     # 任意附加文件（原字节）
        p = os.path.join(pkg, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    for name, doc in (schemas or {}).items():
        os.makedirs(os.path.join(pkg, "schemas"), exist_ok=True)
        with open(os.path.join(pkg, "schemas", name), "w", encoding="utf-8", newline="\n") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
    for dom, doc in (data or {}).items():
        PK.write_json(os.path.join(pkg, "content", "data", f"{dom}.json"), doc)
    return pkg


def main() -> int:
    gd = tempfile.mkdtemp(prefix="fw_pkg_vocab_")
    SRV.GAMES_DIR = gd
    print(f"== 包自带词汇表门禁（临时包目录 {gd}）==")

    ok = make_pkg(gd, "vocab_ok", schemas={"my_items.schema.json": MY_SCHEMA},
                  data={"my_items": MY_DATA}, glossary=GOOD)
    plain = make_pkg(gd, "vocab_plain", schemas={"my_items.schema.json": MY_SCHEMA},
                     data={"my_items": MY_DATA})
    bad_json = make_pkg(gd, "vocab_badjson", glossary={"items": "{oops"})
    bad_top = make_pkg(gd, "vocab_badtop", glossary={"items": "[1, 2]"})
    bad_fields = make_pkg(gd, "vocab_badfields",
                          glossary={"items": {"fields": ["nope"],
                                              "groups": [{"id": "g", "label": "G", "fields": ["desc"]}]}})
    bad_meta = make_pkg(gd, "vocab_badmeta",
                        glossary={"items": {"fields": {"desc": "不是对象",
                                                       "name": {"zh": "包·名称"}}}})
    bad_widget = make_pkg(gd, "vocab_badwidget",
                          glossary={"items": {"fields": {"desc": {"zh": "包·描述", "widget": "nope_ctl"}}}})
    bad_ref = make_pkg(gd, "vocab_badref", glossary={"items": {"fields": {
        "legendary": {"zh": "包·传说", "ref": {"domain": "zzz_nope"}},          # 目标域不认识
        "roster_id": {"zh": "包·名册", "ref": {"domain": "equip_roster", "by": "weird"}},  # by 非法
        "cap": {"zh": "包·上限", "ref": "不是对象"},                            # ref 形状不对
    }}})
    bad_groups = make_pkg(gd, "vocab_badgroups",
                          glossary={"items": {"groups": "不是数组",
                                              "fields": {"desc": {"zh": "包·描述"}}}})
    bad_group_items = make_pkg(gd, "vocab_badgroupitems", glossary={"my_items": {
        "groups": [{}, {"id": "a"}, {"id": "a", "fields": ["x"]}, {"id": "a", "fields": ["z"]},
                   {"id": "b", "fields": []}, {"id": "c", "fields": ["y", ""]}, "不是对象"],
        "fields": {"name": {"zh": "包·名称"}}}})
    bad_group_all = make_pkg(gd, "vocab_badgroupall",
                             glossary={"items": {"groups": ["不是对象", {"id": ""}]}})
    unknown_dom = make_pkg(gd, "vocab_unknowndom",
                           glossary={"zzz_nope": {"fields": {"name": {"zh": "X"}}}})
    skip_only = make_pkg(gd, "vocab_skiponly", extra_files={
        "editor/glossary/_example.json": json.dumps({"fields": {"name": {"zh": "示例"}}}, ensure_ascii=False),
        "editor/glossary/.hidden.json": "{}",
        "editor/glossary/notes.txt": "这不是声明",
        "editor/glossary/sub/items.json": "{}",
    })
    rel_over = make_pkg(gd, "vocab_relover",
                        relations={"items": {"effect_data": {"ref": {"domain": "skills"}}}},
                        glossary={"items": {"fields": {"effect_data": {
                            "zh": "包·效果参数", "ref": {"domain": "drop_pools"}},
                            "tip": {"zh": "包·提示", "ref": {"domain": "items"}}}}})
    gr_table = make_pkg(gd, "vocab_grtable",
                        glossary={"items": {"groups": [{"id": "only", "label": "独占组", "icon": "📌",
                                                        "fields": ["name", "desc"]}]}})

    # ═══════════ (a) 零回归 ═══════════
    print("\n【(a) 零回归：包不声明 = 逐项等于改造前】")
    check("缺目录 → 声明空、0 告警", GL.package_glossary(plain) == {}
          and GL.glossary_warnings(plain) == [], GL.glossary_warnings(plain))
    check("六面 API 与不带包逐项相同（包自带新域多出的键不算回归）",
          GL.all_entries(plain) == GL.all_entries()
          and GL.all_groups(plain) == GL.all_groups()
          and {d: GL.all_widgets(plain)[d] for d in GL.DOMAIN_SCHEMA} == GL.all_widgets()
          and GL.lookup("items", "effect_data", plain) == GL.lookup("items", "effect_data")
          and GL.groups_for("items", plain) == GL.groups_for("items")
          and GL.widget_for("items", "desc", plain) == GL.widget_for("items", "desc"))
    check("不给包 = 只认框架那份（source 标记不出现）",
          "source" not in (GL.lookup("items", "effect_data") or {})
          and GL.suggest_meta("items", "rid")["ref_source"] == "builtin"
          and GL.widget_for("items", "desc") == "textarea")
    check("friendly / missing_required 不给包 = 旧行为",
          GL.friendly("skills", ["desc: '' should be non-empty"])[0]["display"].startswith("desc（描述）")
          and [m["label"] for m in GL.missing_required(
              "skills", {"kind": "魔法"}, {"required": ["name", "desc"]})] == ["名称", "描述"])
    if not os.path.isdir(GL.pkg_glossary_dir(REAL_ORLANDIA)):
        check("orlandia 当前没声明词汇表 → 六面 API 也逐项等于不带包",
              GL.all_entries(REAL_ORLANDIA) == GL.all_entries()
              and GL.all_groups(REAL_ORLANDIA) == GL.all_groups()
              and {d: GL.all_widgets(REAL_ORLANDIA)[d] for d in GL.DOMAIN_SCHEMA} == GL.all_widgets()
              and GL.glossary_warnings(REAL_ORLANDIA) == [])
    else:
        check("orlandia 已声明词汇表 → 读取不抛、告警是 list、分组表每域可读",
              isinstance(GL.glossary_warnings(REAL_ORLANDIA), list)
              and all(isinstance(GL.groups_for(d, REAL_ORLANDIA), list) for d in GL.DOMAIN_SCHEMA))
    _files = GL._pkg_json_files(GL.pkg_glossary_dir(REAL_ORLANDIA))
    _consumed = set(GL.package_glossary(REAL_ORLANDIA))
    _w = GL.glossary_warnings(REAL_ORLANDIA)
    check(f"真实包 orlandia：{len(_files)} 个词汇表文件**一个都不静默丢**（丢必有告警点名）",
          all(n[:-5] in _consumed or any(n in x for x in _w) for n in _files),
          [n for n in _files if n[:-5] not in _consumed and not any(n in x for x in _w)])

    # ═══════════ (b) 包声明优先 ═══════════
    print("\n【(b) 包声明优先：包写了的都算数】")
    gl = GL.package_glossary(ok)
    check("读得出规范化声明（域 → fields/groups；$version 之类不进）",
          set(gl) == {"items", "my_items"} and set(gl["items"]) == {"fields"}
          and set(gl["my_items"]) == {"fields", "groups"}, {d: sorted(t) for d, t in gl.items()})
    check("规范化形状：zh/note/widget/group/ref 齐备、缺省填空值",
          gl["items"]["fields"]["effect_data"]["widget"] == "kv"
          and gl["items"]["fields"]["effect_data"]["group"] == "use"
          and gl["items"]["fields"]["desc"]["note"] == ""
          and gl["my_items"]["fields"]["name"]["ref"] is None)
    check("干净声明 → 0 告警（好包不该有黄条）", GL.glossary_warnings(ok) == [], GL.glossary_warnings(ok))

    e = GL.lookup("items", "effect_data", ok)
    check("lookup：包条目优先 + source=package + matched=命中键",
          e and e["zh"] == "包·效果参数" and e["note"] == "包侧注脚" and e["source"] == "package"
          and e["matched"] == "effect_data" and e["dom"] == "items", e)
    check("lookup：**整条替换**（包只给 zh → 注释不拿框架的补）",
          GL.lookup("items", "desc", ok)["zh"] == "包·描述"
          and GL.lookup("items", "desc", ok)["note"] == ""
          and GL.lookup("items", "desc", ok)["matched"] == "desc")
    check("lookup：精确路径优先于叶名（pick_options.rid ≠ rid）",
          GL.lookup("items", "pick_options.rid", ok)["zh"] == "包·选项产出 id"
          and GL.lookup("items", "其它.rid", ok)["zh"] == "包·产出 id")
    check("lookup：包没写的字段照旧回退框架（items.name → 通用「名称」）",
          GL.lookup("items", "name", ok)["zh"] == "名称"
          and GL.lookup("items", "name", ok).get("source") is None)
    check("lookup：包自带新域也认（my_items.name）",
          GL.lookup("my_items", "name", ok)["zh"] == "包·名称"
          and GL.lookup("my_items", "no_such", ok) is None)

    check("widget_for：包声明的控件生效（含框架没有的形态 kv），且压过框架 WIDGETS 的叶名",
          GL.widget_for("items", "effect_data", ok) == "kv"
          and GL.widget_for("items", "effect_data") == "textarea")
    check("widget_for：包的声明**压过**框架 WIDGETS 叶名表（desc 明明是 textarea）",
          GL.widget_for("my_items", "cost", ok) == "pct"
          and GL.widget_for("my_items", "cost") is None)
    check("widget_for：包没声明的字段照旧走框架",
          GL.widget_for("items", "desc", ok) == "textarea")

    gr = GL.groups_for("items", gr_table)
    check("groups_for：groups 是**整表替换**（包只给一组 → 框架 items 那三组不合并进来）",
          [g["id"] for g in gr] == ["only"]
          and [g["id"] for g in GL.groups_for("items")] == ["base", "use", "special"], gr)
    g2 = GL.groups_for("my_items", ok)
    check("groups_for：包的 groups 原样可用（id/label/icon/fields 深拷贝）",
          g2 == [{"id": "base", "label": "包分组", "icon": "🧪", "fields": ["name", "cost"]},
                 {"id": "more", "label": "其它", "icon": "", "fields": ["tip"]}], g2)
    check("groups_for：包没给 groups 的域照旧框架分组（items 仍是框架那份）",
          GL.groups_for("items", ok) == GL.groups_for("items"))
    check("groups_for：深拷贝（改调用方不污染缓存）",
          (lambda a: (a[0]["fields"].append("__x__"), "__x__" not in GL.groups_for("my_items", ok)[0]["fields"])[1])(
              GL.groups_for("my_items", ok)))
    check("all_groups：包自带域也在表里，且框架各域不丢",
          set(GL.all_groups()) <= set(GL.all_groups(ok)) and GL.all_groups(ok)["my_items"] == g2)

    ae = GL.all_entries(ok)
    check("all_entries：包条目并进对应域（zh/note/wiki 形态与前端一致）",
          ae["items"]["effect_data"]["zh"] == "包·效果参数"
          and set(ae["items"]["effect_data"]) == {"zh", "note", "wiki"}
          and ae["my_items"]["cost"]["zh"] == "包·费用"
          and ae["items"]["effect_data"]["note"] == "包侧注脚"
          and ae["*"]["name"]["zh"] == "名称"                       # 通用叶名那份没被动
          and GL.lookup("items", "name", ok)["zh"] == "名称")       # 前端叶名回退照旧
    check("all_entries：包新域也列出来（前端 tab 才不空白）", "my_items" in ae)
    check("ref_url：包条目的 wiki 出处出深链；**跨域 ref 不冒充文档出处**",
          ae["my_items"]["name"]["wiki"] == "wiki:reference/loot.md#find=entries"
          and ae["items"]["rid"]["wiki"] is None
          and GL.ref_url(GL.GLOSSARY["effect_rules"]["cap"]) == "wiki:reference/effect-rules.md#find=cap")

    aw = GL.all_widgets(ok)
    check("all_widgets：包的 widget/ref 进表（ref_source=package_vocab）",
          aw["items"]["effect_data"]["widget"] == "kv"
          and aw["items"]["rid"]["ref"] == "equip_roster"
          and aw["items"]["rid"]["ref_by"] == "name"
          and aw["items"]["rid"]["ref_source"] == "package_vocab", aw["items"].get("rid"))
    check("suggest_meta：包词汇表压过框架默认（rid 默认是 builtin/equip_roster）",
          GL.suggest_meta("items", "rid", ok)["ref_source"] == "package_vocab"
          and GL.suggest_meta("items", "rid", ok)["ref_by"] == "name"
          and GL.suggest_meta("items", "rid")["ref_source"] == "builtin")
    check("suggest_meta：包词汇表**不进**引用校验（校验面归 relations.json）",
          __import__("editor.relations", fromlist=["x"]).ref_errors(ok, "items", {"rid": "根本不存在的 id"}) == [])
    sm = GL.suggest_meta("items", "effect_data", rel_over)
    check("suggest_meta：两处包声明同场时 relations.json 优先（package > package_vocab）",
          sm["ref"] == "skills" and sm["ref_source"] == "package", sm)
    check("suggest_meta：只有词汇表声明的 ref 走 package_vocab（tip → items）",
          GL.suggest_meta("items", "tip", rel_over)["ref"] == "items"
          and GL.suggest_meta("items", "tip", rel_over)["ref_source"] == "package_vocab"
          and GL.suggest_meta("items", "tip", rel_over)["widget"] is None)

    fr = GL.friendly("my_items", ["name: '' should be non-empty"], ok)
    check("friendly：报错带包词汇表的中文名", "包·名称" in fr[0]["display"], fr[0].get("display"))
    mr = GL.missing_required("my_items", {"tip": "x"}, {"required": ["name", "cost"]}, ok)
    check("missing_required：必填体检用包词汇表的中文名/注脚",
          [m["label"] for m in mr] == ["包·名称", "包·费用"] and mr[0]["note"] == "自定域注脚", mr)

    # ═══════════ (c) 坏声明只降级 ═══════════
    print("\n【(c) 坏声明：丢坏的部分 + 可读告警，其余照用，绝不抛】")
    w = GL.glossary_warnings(bad_json)
    check("坏 JSON → 空声明 + 告警点名文件与回退",
          GL.package_glossary(bad_json) == {} and len(w) == 1
          and "items.json" in w[0] and "回退" in w[0], w)
    check("坏 JSON → 该域字段照旧回退框架（不因为声明坏就丢词条）",
          GL.lookup("items", "effect_data", bad_json)["zh"] == "效果参数")
    w = GL.glossary_warnings(bad_top)
    check("顶层非对象（数组）→ 当作没声明 + 告警",
          GL.package_glossary(bad_top) == {} and any("顶层" in x for x in w), w)
    check("fields 不是对象 → 丢字段表 + 告警，**groups 照用**",
          any("fields" in x for x in GL.glossary_warnings(bad_fields))
          and GL.groups_for("items", bad_fields)[0]["id"] == "g"
          and GL.lookup("items", "desc", bad_fields)["zh"] == "描述",
          GL.glossary_warnings(bad_fields))
    check("元不是对象 → 该条丢、兄弟条目留",
          GL.lookup("items", "name", bad_meta)["zh"] == "包·名称"
          and GL.lookup("items", "desc", bad_meta)["zh"] == "描述"
          and any("desc" in x for x in GL.glossary_warnings(bad_meta)),
          GL.glossary_warnings(bad_meta))
    check("widget 不在词表 → 丢该属性 + 告警，zh 照用、控件回退",
          GL.lookup("items", "desc", bad_widget)["zh"] == "包·描述"
          and GL.widget_for("items", "desc", bad_widget) == "textarea"
          and any("widget" in x and "nope_ctl" in x for x in GL.glossary_warnings(bad_widget)),
          GL.glossary_warnings(bad_widget))
    w = GL.glossary_warnings(bad_ref)
    check("ref 坏形态逐条降级：目标域不认识 / by 非法 / ref 不是对象（都有告警）",
          all(any(k in x for x in w) for k in ("zzz_nope", "by", "ref")), w)
    br = GL.package_glossary(bad_ref)["items"]["fields"]
    check("ref：by 非法 → 按 key 收下（不是整条丢）", br["roster_id"]["ref"] == {"domain": "equip_roster", "by": "key"})
    check("ref：目标域不认识 / 形状坏 → 该字段的 ref 为 None，zh 仍在",
          br["legendary"]["ref"] is None and br["legendary"]["zh"] == "包·传说"
          and br["cap"]["ref"] is None and br["cap"]["zh"] == "包·上限")
    check("ref 降级后 suggest_meta 退回框架默认（不会给出一个假候选源）",
          GL.suggest_meta("items", "legendary", bad_ref)["ref"] == "legendary_effects"
          and GL.suggest_meta("items", "legendary", bad_ref)["ref_source"] == "builtin")
    check("groups 不是数组 → 告警 + 该域回退框架分组",
          any("groups" in x for x in GL.glossary_warnings(bad_groups))
          and GL.groups_for("items", bad_groups) == GL.groups_for("items")
          and GL.lookup("items", "desc", bad_groups)["zh"] == "包·描述",
          GL.glossary_warnings(bad_groups))
    w = GL.glossary_warnings(bad_group_items)
    check("组逐条降级：缺 id / fields 坏 / 同 id 重复 / 空 fields / 非字符串元素 / 非对象 —— 各一条告警",
          all(any(f"[{i}]" in x for x in w) for i in (0, 1, 3, 4, 5, 6))
          and any("重复" in x for x in w), w)
    check("组逐条降级：好的那组照旧收下（不因为邻居坏就整段丢）",
          [g["id"] for g in GL.groups_for("my_items", bad_group_items)] == ["a"]
          and GL.lookup("my_items", "name", bad_group_items)["zh"] == "包·名称")
    check("组全坏 → 该域分组回退框架默认（items 那三组照旧）",
          any("一组都没收下" in x for x in GL.glossary_warnings(bad_group_all))
          and [g["id"] for g in GL.groups_for("items", bad_group_all)] == ["base", "use", "special"],
          GL.glossary_warnings(bad_group_all))
    check("未知域文件 → 告警 + 忽略（不污染别的域）",
          GL.package_glossary(unknown_dom) == {}
          and any("zzz_nope" in x for x in GL.glossary_warnings(unknown_dom)),
          GL.glossary_warnings(unknown_dom))
    check("`_` / `.` 开头的文件与非 json 不算声明（示例文件不产黄条）",
          GL.package_glossary(skip_only) == {} and GL.glossary_warnings(skip_only) == [],
          GL.glossary_warnings(skip_only))
    check("任何坏包都不抛：六面 API 都能跑完",
          all(isinstance(f, dict) for f in (
              GL.all_entries(p) for p in (bad_json, bad_top, bad_fields, bad_meta))))
    check("package_glossary 返回深拷贝（改调用方不污染缓存）",
          (lambda d: (d["items"]["fields"].pop("desc"), "desc" in GL.package_glossary(ok)["items"]["fields"])[1])(
              GL.package_glossary(ok)))
    check("词表取值 = 约定那 7 种", set(GL.PKG_WIDGETS) == {"textarea", "lines", "pct", "chips",
                                                          "rows", "kv", "select"}, GL.PKG_WIDGETS)

    # ═══════════ (d)(e) HTTP ═══════════
    print("\n【(d)(e) HTTP：好包/坏包都 200，中文名与告警都送到前端】")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), SRV.H)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        st, j = req(base, "GET", "/api/glossary?pkg=vocab_ok")
        check("GET /glossary?pkg= → 200 且包条目在 domains（含新域）",
              st == 200 and j.get("ok") and j["domains"]["items"]["effect_data"]["zh"] == "包·效果参数"
              and j["domains"]["my_items"]["cost"]["zh"] == "包·费用", f"{st}")
        check("/glossary?pkg= → groups：包给分组的域吃包那份，没给的域照旧框架",
              [g["id"] for g in j["groups"]["my_items"]] == ["base", "more"]
              and [g["id"] for g in j["groups"]["items"]] == ["base", "use", "special"],
              {k: [g["id"] for g in v] for k, v in list(j["groups"].items())[:3]})
        st, jg = req(base, "GET", "/api/glossary?pkg=vocab_grtable")
        check("/glossary?pkg= → groups 是**整表替换**（框架 items 三组不合并）",
              st == 200 and [g["id"] for g in jg["groups"]["items"]] == ["only"], f"{st}")
        check("/glossary?pkg= → widgets 认包声明（kv / pct / ref_source=package_vocab）",
              j["widgets"]["items"]["effect_data"]["widget"] == "kv"
              and j["widgets"]["my_items"]["cost"]["widget"] == "pct"
              and j["widgets"]["items"]["rid"]["ref_source"] == "package_vocab", f"{st}")
        check("好包 → warnings 空（没降级就别吓人）", j.get("warnings") == [], j.get("warnings"))

        st, j = req(base, "GET", "/api/glossary?pkg=vocab_plain")
        st0, j0 = req(base, "GET", "/api/glossary")
        check("零回归：不声明的包 → 接口回传逐项等于不带包那份",
              st == 200 and st0 == 200 and j["domains"] == j0["domains"]
              and {d: j["groups"][d] for d in j0["groups"]} == j0["groups"]
              and {d: j["widgets"][d] for d in GL.DOMAIN_SCHEMA} == j0["widgets"]
              and j.get("warnings") == [], f"{st}/{st0}")

        for pid in ("vocab_badjson", "vocab_badtop", "vocab_badfields", "vocab_badmeta",
                    "vocab_badwidget", "vocab_badref", "vocab_badgroups", "vocab_badgroupitems",
                    "vocab_unknowndom"):
            st1, j1 = req(base, "GET", f"/api/glossary?pkg={pid}")
            st2, j2 = req(base, "GET", f"/api/package/{pid}")
            st3, j3 = req(base, "GET", f"/api/package/{pid}/d/my_items/k1")
            check(f"{pid}：/glossary 200 + 告警送到前端 + 概览黄条也有 + 编辑不受拖累",
                  st1 == 200 and j1.get("warnings") and st2 == 200
                  and any(w in j2.get("domain_warnings") or [] for w in j1["warnings"])
                  and st3 == 200, f"{st1}/{st2}/{st3} warn={j1.get('warnings')}")

        st, j = req(base, "PUT", "/api/package/vocab_ok/d/my_items/k2",
                    {"data": {"name": "", "tip": "x"}})
        fr = (j.get("validation") or {}).get("friendly") or []
        ms = (j.get("validation") or {}).get("missing") or []
        check("PUT 校验拦下 → 422；friendly 报错带**包词汇表**的中文名",
              st == 422 and any("包·名称" in (x.get("display") or "") for x in fr)
              and any(m.get("label") == "包·名称" for m in ms), f"{st} {fr}")
        st, j = req(base, "PUT", "/api/package/vocab_ok/d/my_items/k2",
                    {"data": {"name": "合法", "tip": "x"}})
        check("PUT 合法 → 200 落盘（包声明不影响写入）", st == 200 and j.get("ok"), f"{st}")
    finally:
        httpd.shutdown()
        httpd.server_close()
        shutil.rmtree(gd, ignore_errors=True)

    print(f"\n===== 结果：通过 {PASS} / {PASS + FAIL} =====")
    for f in FAILURES:
        print("  ❌", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
