# -*- coding: utf-8 -*-
"""编辑器扩展**第 2 层**：包侧声明面（引用关系 / 表单联动 / 视图分派）。

设计稿：工作区 `overnight/editor-extension-design.md` §二「第 2 层：半动态」。
一句话：把过去**写死在框架侧**的三样东西（字段↔域引用、表单联动/只读、域专属视图分派）
改成 **两层 = 包声明 > 框架默认**；包**不声明**时行为**逐项不变**（框架那份降级为默认值，
不删）。与第 1 层（`<pkg>/editor/domains.json`）同一套纪律：**坏声明只降级、绝不 500**。

包侧两个文件（都放在包的 `editor/` 下，可缺省）
------------------------------------------------

    <pkg>/editor/relations.json    字段↔域引用 + 联动/只读
    <pkg>/editor/views.json        域 → 内置视图名（包不写新代码）

`relations.json` 形状（所有键都可缺省；`*` = 对所有域生效，**只**用于联动）::

    {
      "$version": 1,
      "monsters": {
        "drop_pool":  {"ref": {"domain": "drop_pools"}},          # 引用 → 下拉 + 引用校验
        "elite_equip": {"ref": {"domain": "equip_roster", "by": "name"}},
        "is_boss":    {"when": {"is_boss": true},
                       "show": ["boss_equip"], "readonly": ["boss_equip"]}
      },
      "*": {"when": {"locked": true}, "readonly": ["name"]}
    }

* `ref.domain` = 目标域 id；`ref.by` = 拿目标条目的**哪个字段**当候选（`key`（缺省）| `name`）。
  **只有包声明的 ref 才做引用校验**；框架默认那份（`glossary.REF_DOMAINS`）只给候选、不校验
  —— 否则既有包的数据会被新校验判红（零回归是本层的硬约束）。
* `when` + `show` / `readonly` = 表单联动：`when` 里的字段取到所列值之一时，
  `show` 里的字段显示、`readonly` 里的字段只读。**纯声明**：服务端只回传，不替前端做判断
  （框架原来就没有联动逻辑 → 默认集为空 → 零回归）。

`views.json` 形状::

    {"talent_trees": {"view": "table"},
     "my_dungeons": {"view": "instance_view"}}

内置视图名（**只有这 5 个**，包不写新代码）：`loot_view` / `instance_view` / `space_view` /
`table` / `graph`（`graph` = `space_view` 的别名）。框架默认分派（改造前写死在
`server.py` 里的那三条）降级为 `BUILTIN_DEFAULT_VIEWS`：

    maps → space_view      drop_pools → loot_view      instances → instance_view

坏声明（坏 JSON / 未知 view 名 / 未知域 / 形状不对）→ 忽略该项（或整份）+ 一条**可读 warning**，
永不抛异常；该域仍走框架默认。

对外接口
--------
    relations_decl_path(pkg_dir) / views_decl_path(pkg_dir)
    package_relations(pkg_dir) -> dict            # 包声明（规范化后；含 "*"）
    relation_warnings(pkg_dir) -> [可读告警]
    declared_ref(pkg_dir, dom, path) -> {"domain","by"} | None      # **只认包声明**
    ref_candidates(pkg_dir, domain, by="key") -> [候选值]
    ref_errors(pkg_dir, dom, data) -> [可读校验错]                   # 只查包声明的 ref
    linkage_for(pkg_dir, dom) -> {字段: {when, show, readonly}}
    package_views(pkg_dir) -> dict
    view_warnings(pkg_dir) -> [可读告警]
    resolve_view(pkg_dir, dom) -> (视图名 | None, "package"|"builtin"|None, [告警])
    builtin_default_view(dom) -> 视图名 | None
    all_warnings(pkg_dir) -> [可读告警]（relations ∪ views，给概览页黄条）
"""
from __future__ import annotations

import json
import os

from . import packages as PK
from ._util import file_sig as _sig

RELATIONS_REL = "editor/relations.json"
VIEWS_REL = "editor/views.json"

# ---------------- 内置视图（包只能声明这些名字；实现全在框架侧） ----------------
VIEW_NAMES = ("loot_view", "instance_view", "space_view", "table", "graph")
VIEW_ALIASES = {"graph": "space_view"}          # graph = space_view 的别名（同一个实现）
# HTTP 路由后缀 → 视图名（编辑器既有三条域级路由 + 一条通用路由）
VIEW_ROUTES = {"space_view": "graph", "loot_view": "preview",
               "instance_view": "run", "table": "view"}
# ★ 框架**默认**分派 —— 改造前写死在 `editor/server.py` 的 `dom != "drop_pools"` /
#   `dom != "instances"` 两处 + `maps` 的 graph 路由。这里把它登记成**默认值**：
#   包不声明 `editor/views.json` 时逐项等价（drop_pools 仍走 loot_view、instances 仍走
#   instance_view、maps 仍走 space_view），包声明同名域时以包为准并记 warning。
BUILTIN_DEFAULT_VIEWS = {
    "maps": "space_view",
    "drop_pools": "loot_view",
    "instances": "instance_view",
}

# 全局（对所有域生效）联动键；兼容设计稿里写的 "any"
_GLOBAL_KEYS = ("*", "any")
_REF_BYS = ("key", "name")

_CACHE: dict = {}                  # 包目录 -> (rel_sig, views_sig, ...归一化结果)
_CACHE_MAX = 500


def _key(pkg_dir) -> str:
    return os.path.normpath(os.path.abspath(str(pkg_dir))) if pkg_dir else ""


def relations_decl_path(pkg_dir: str) -> str:
    return os.path.join(pkg_dir, RELATIONS_REL)


def views_decl_path(pkg_dir: str) -> str:
    return os.path.join(pkg_dir, VIEWS_REL)


def _read_json_rel(path: str, label: str):
    """读一份声明文件 → `(对象 | None, [可读告警])`。**缺文件 = 没声明（正常，不告警）。**"""
    if not os.path.exists(path):
        return None, []
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return None, [f"包声明读不了（{label}）：{e} —— 已回退框架默认"]
    if not isinstance(raw, dict):
        return None, [f"包声明形状不对（{label}）：顶层需为对象，实为 {type(raw).__name__}"
                      " —— 已回退框架默认"]
    return raw, []


# ---------------- relations.json ----------------
def _norm_rule(dom: str, field: str, meta, warns: list, domains: dict):
    """规范化一条字段规则 → `{ref, when, show, readonly}`（坏的部分忽略 + warning）。"""
    out = {"ref": None, "when": None, "show": [], "readonly": []}
    where = f"{dom}.{field}"
    if not isinstance(meta, dict):
        warns.append(f"引用声明 {where}：形状不对（需为对象，可含 ref/when/show/readonly）"
                     " —— 该条已忽略")
        return None
    ref = meta.get("ref")
    if ref is not None:
        if not isinstance(ref, dict) or not isinstance(ref.get("domain"), str) \
                or not ref.get("domain"):
            warns.append(f"引用声明 {where}：ref 需为 {{\"domain\": \"…\", \"by\": \"key|name\"}}"
                         f"（实为 {ref!r}）—— 该字段的引用已忽略")
        else:
            tdom = ref["domain"]
            by = ref.get("by", "key")
            if by not in _REF_BYS:
                warns.append(f"引用声明 {where}：by={by!r} 非法（只能是 key / name）"
                             " —— 按 key 处理")
                by = "key"
            if tdom not in domains:
                warns.append(f"引用声明 {where}：目标域 {tdom!r} 不在该包的有效域表里"
                             " —— 该字段的引用已忽略（仍可选，但不会有下拉与校验）")
            else:
                out["ref"] = {"domain": tdom, "by": by}
    when = meta.get("when")
    if when is not None:
        if isinstance(when, dict) and when:
            out["when"] = {str(k): v for k, v in when.items()}
        else:
            warns.append(f"联动声明 {where}：when 需为非空对象 {{字段: 值}}"
                         f"（实为 {when!r}）—— 该条件已忽略")
    for k in ("show", "readonly"):
        v = meta.get(k)
        if v is None:
            continue
        if isinstance(v, list) and all(isinstance(x, str) for x in v):
            out[k] = list(v)
        else:
            warns.append(f"联动声明 {where}：{k} 需为字符串数组（实为 {v!r}）—— 已忽略")
    if not any((out["ref"], out["when"], out["show"], out["readonly"])):
        return None
    return out


def _read_relations(pkg_dir: str, domains: dict):
    """真读一次 `<pkg>/editor/relations.json` → (规范化声明, [可读告警])。**只降级，不抛。**"""
    raw, warns = _read_json_rel(relations_decl_path(pkg_dir), RELATIONS_REL)
    out: dict = {}
    if raw is None:
        return out, warns
    for dom, fields in raw.items():
        if dom == "$version":
            continue
        if dom in _GLOBAL_KEYS:
            dom_key = "*"
        elif isinstance(dom, str) and dom in domains:
            dom_key = dom
        else:
            warns.append(f"引用声明：域 {dom!r} 不在该包的有效域表里 —— 该域整段已忽略")
            continue
        if not isinstance(fields, dict):
            warns.append(f"引用声明 {dom}：形状不对（需为 {{字段: {{…}}}}，实为 "
                         f"{type(fields).__name__}）—— 该域整段已忽略")
            continue
        # 两种写法都认：① 域作用域联动（值里直接写 when/show/readonly）② 字段规则
        if any(k in fields for k in ("when", "show", "readonly")) \
                and not isinstance(fields.get("ref"), dict):
            rule = _norm_rule(dom_key, "*", {k: fields[k] for k in
                                            ("ref", "when", "show", "readonly") if k in fields},
                              warns, domains)
            if rule:
                out.setdefault(dom_key, {})["*"] = rule
            continue
        rules = {}
        for field, meta in fields.items():
            rule = _norm_rule(dom_key, field, meta, warns, domains)
            if rule:
                rules[str(field)] = rule
        if rules:
            out.setdefault(dom_key, {}).update(rules)
    return out, warns


def _read_views(pkg_dir: str, domains: dict):
    """真读一次 `<pkg>/editor/views.json` → ({域: 视图名}, [可读告警])。**只降级，不抛。**"""
    raw, warns = _read_json_rel(views_decl_path(pkg_dir), VIEWS_REL)
    out: dict = {}
    if raw is None:
        return out, warns
    for dom, meta in raw.items():
        if dom == "$version":
            continue
        if not isinstance(dom, str) or dom not in domains:
            warns.append(f"视图声明：域 {dom!r} 不在该包的有效域表里 —— 该条已忽略")
            continue
        name = meta.get("view") if isinstance(meta, dict) else meta
        if not isinstance(name, str) or name not in VIEW_NAMES:
            warns.append(f"视图声明 {dom}：view={name!r} 不是内置视图（只能是 "
                         f"{' / '.join(VIEW_NAMES)}）—— 已回退框架默认"
                         f"（{BUILTIN_DEFAULT_VIEWS.get(dom) or '无'}）")
            continue
        out[dom] = name
    return out, warns


def _cached(pkg_dir) -> tuple:
    """(规范化 relations, relations 告警, views 声明, views 告警) —— 按两份文件的签名失效。"""
    key = _key(pkg_dir)
    if not key:
        return {}, [], {}, []
    rel_path, viw_path = relations_decl_path(key), views_decl_path(key)
    sig = (_sig(rel_path), _sig(viw_path))
    hit = _CACHE.get(key)
    if hit is not None and hit[0] == sig:
        return hit[1], list(hit[2]), hit[3], list(hit[4])
    domains = PK.effective_domains(key)[0]
    rel, rel_w = _read_relations(key, domains)
    viw, viw_w = _read_views(key, domains)
    if len(_CACHE) > _CACHE_MAX:
        _CACHE.clear()
    _CACHE[key] = (sig, rel, rel_w, viw, viw_w)
    return rel, rel_w, viw, viw_w


# ---------------- 对外：引用关系 ----------------
def package_relations(pkg_dir) -> dict:
    """包自带的引用/联动声明（规范化后；`"*"` = 全局联动）。缺文件 / 坏声明 → `{}`。"""
    rel = _cached(pkg_dir)[0]
    return {d: {f: dict(r) for f, r in rules.items()} for d, rules in rel.items()}


def relation_warnings(pkg_dir) -> list:
    """读 `editor/relations.json` 时的可读告警（空 = 没声明或声明没问题）。"""
    return _cached(pkg_dir)[1]


def declared_ref(pkg_dir, dom: str, path: str):
    """**只认包声明**的引用 → `{"domain": ..., "by": ...}` | None。

    框架默认那份（`glossary.REF_DOMAINS`）**不在这里** —— 它是"默认值"，由调用方
    （`glossary.suggest_meta`）在包没声明时兜底；两者的区别是**只有包声明的 ref 会进校验**。
    """
    rules = _cached(pkg_dir)[0].get(dom) or {}
    r = rules.get(str(path)) or rules.get(str(path).split(".")[-1])
    return dict(r["ref"]) if r and r.get("ref") else None


def linkage_for(pkg_dir, dom: str) -> dict:
    """该域的表单联动/只读（全局 `"*"` 与域内规则合并；同名字段域内优先）。"""
    rel = _cached(pkg_dir)[0]
    out: dict = {}
    for scope in ("*", dom):
        for field, rule in (rel.get(scope) or {}).items():
            if rule.get("when") or rule.get("show") or rule.get("readonly"):
                out[field] = {"when": rule.get("when"), "show": list(rule.get("show") or []),
                              "readonly": list(rule.get("readonly") or [])}
    return out


def _target_values(pkg_dir, domain: str, by: str) -> list:
    """目标域里「能当选者的值」：`by=key` → 表主键；`by=name` → 条目的 name。"""
    domains = PK.effective_domains(pkg_dir)[0]
    if domain not in domains:
        return []
    try:
        table = PK.read_json(PK.domain_path(pkg_dir, domain, domains), {})
    except Exception:                                        # noqa: BLE001
        return []
    if not isinstance(table, dict):
        return []
    out = []
    for k, v in table.items():
        if not PK.is_entry_key(k):
            continue                      # 私有 / 文件级元信息键不是条目 —— 与 PK.domain_status 同口径
        if by == "name":
            if isinstance(v, dict) and isinstance(v.get("name"), str) and v["name"]:
                out.append(v["name"])
        else:
            out.append(str(k))
    return sorted(dict.fromkeys(out))


def ref_candidates(pkg_dir, domain: str, by: str = "key") -> list:
    """某个域「按某字段」的候选值（给下拉用；目标域不存在 / 读不了 → 空表，不抛）。"""
    if by not in _REF_BYS:
        by = "key"
    return _target_values(pkg_dir, domain, by)


def _walk_values(node, leaf: str, path: str, out: list) -> None:
    """在一条数据里找出 `leaf`（叶名或全路径）对应的标量值（含数组元素）。"""
    if isinstance(node, dict):
        for k, v in node.items():
            sub = f"{path}.{k}" if path else k
            if k == leaf or sub == leaf:
                if isinstance(v, list):
                    out.extend(x for x in v if isinstance(x, str) and x)
                elif isinstance(v, str) and v:
                    out.append(v)
            if isinstance(v, (dict, list)):
                _walk_values(v, leaf, sub, out)
    elif isinstance(node, list):
        for x in node:
            _walk_values(x, leaf, path, out)


def ref_errors(pkg_dir, dom: str, data: dict) -> list:
    """**只查包声明的 ref**：值必须能在目标域里找到（`by` 决定比 key 还是比 name）。

    包没声明（或该域没声明）→ `[]`（**零回归**：既有包不会被新增校验判红）。
    目标域读不到 / 空表 → 不报错（候选拿不到就不该判红 —— 与 `validate` 的
    「宁放过不假红」同一条底线）。
    """
    rules = _cached(pkg_dir)[0].get(dom) or {}
    if not isinstance(data, dict) or not rules:
        return []
    errs: list = []
    for field, rule in rules.items():
        ref = rule.get("ref")
        if not ref or field == "*":
            continue
        leaf = str(field)
        vals: list = []
        _walk_values(data, leaf, "", vals)
        if not vals:
            continue
        allowed = _target_values(pkg_dir, ref["domain"], ref["by"])
        if not allowed:
            continue                                  # 目标域空 / 不可读 → 不判
        by = ref["by"]
        for v in dict.fromkeys(vals):
            if v not in allowed:
                errs.append(f"{field}: 引用 {ref['domain']}（by {by}）里没有 {v!r}"
                            " —— 该字段填的应当是目标域里真实存在的条目")
    return errs


# ---------------- 对外：视图分派 ----------------
def package_views(pkg_dir) -> dict:
    """包自带的视图声明 `{域: 视图名}`（只含**合法**项）。缺文件 / 坏声明 → `{}`。"""
    return dict(_cached(pkg_dir)[2])


def view_warnings(pkg_dir) -> list:
    """读 `editor/views.json` 时的可读告警（空 = 没声明或声明没问题）。"""
    return _cached(pkg_dir)[3]


def builtin_default_view(dom: str):
    """框架**默认**视图分派（改造前写死的那三条；其它域 = None = 没有专属视图）。"""
    name = BUILTIN_DEFAULT_VIEWS.get(dom)
    return name


def resolved_name(name: str):
    """内置视图名 → 规范实现名（`graph` → `space_view`）。"""
    return VIEW_ALIASES.get(name, name)


def resolve_view(pkg_dir, dom: str):
    """该域的视图分派 → `(视图名 | None, "package" | "builtin" | None, [可读告警])`。

    两层：**包声明优先**（`editor/views.json`）→ 框架默认（`BUILTIN_DEFAULT_VIEWS`）。
    包不声明时返回值与改造前逐项一致。未知 view 名已在读声明时降级 + 记 warning。
    """
    rel, rel_w, views, views_w = _cached(pkg_dir)
    if dom in views:
        return views[dom], "package", list(views_w)
    d = builtin_default_view(dom)
    if d:
        return d, "builtin", []
    return None, None, []


def all_warnings(pkg_dir) -> list:
    """relations ∪ views 的全部可读告警（概览页黄条用；没声明 = `[]`）。"""
    rel, rel_w, _v, viw_w = _cached(pkg_dir)
    return list(rel_w) + list(viw_w)
