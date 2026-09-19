# -*- coding: utf-8 -*-
"""编辑器扩展面**第 3 层 · 批 1/批 2**：包侧渲染声明的**读 + 规范化 + 告警 + 受限渲染树 +
派生值（沙箱）+ 限额**。

设计真源：`overnight/layer3-render-design.md` §9「批 1 · 声明面」/「批 2 · 派生值」
          （§3 字段级、§4 渲染树、§5.1/§5.2 沙箱、§6 降级）
          + `overnight/layer3-render-contracts.md` §0/§1/§2/§3/§4。

批 1 = **纯声明（D0）**；批 2 加**派生值**（`derives`）—— 值只在**一次性子进程**里由
**框架白名单函数**算出（`editor/render_worker.py`），本模块只负责：构造 payload、
把回程值**过一遍白名单/限额**、再把它们落进树。本模块**绝不**：

* 自己起进程（本文件里没有起进程的调用 —— 那条边界**只**在 `render_worker.py` 里；
  且对它是**惰性 import**，所以 `import editor.render` 不会把 worker 拉进内存）；
* 执行包里的任何东西（`<域>.py` / `.html.js` 只被**数一下存在性**，内容不读 —— 代码档
  **已砍**，见 `_load_all` 的「忽略并告警」）；
* import `saintess_engine`，也不 import `editor.packages`/`editor.relations`（前者会级联
  `install_engine()`，后者 import 前者）。

树里的每个文本叶都是**纯文本**（协议里没有 `html`/`style`/`class` 字段；未知键一律丢弃）；
插值（`{字段}` / `{字段|zh}` / `{derive:名}`）在**服务端**算完再进树 —— 前端只做转义渲染，
不做模板求值。

降级纪律（抄第 1/2 层，**永不 500、永不白屏**）
--------------------------------------------
| 档 | 触发 | 本模块的行为 |
|---|---|---|
| L0 | 无 `editor/render/<域>.json` | 什么都不做（调用方照旧走第 2 层/内置默认） |
| L1 | 声明**坏**（坏 JSON / 未知 `$version` / 未知键…） | 整份忽略 → 调用方回退第 2 层 + **可读告警** |
| L2 | 声明好、某块不合规 | 逐块降级：丢掉那一块 + 告警，其余照渲染 |
| L3 | 树构建不出（`when` 不满足 / 顶层不合规） | `ok:false` + `stage` → 调用方整域回退 + 黄条 |
| L3 | **派生期**失败（子进程超时 / 崩 / 输出超限 / 回程值不合规） | `derived()` 回 `ok:false` + `stage` → 调用方整域回退 + 黄条 |

声明签名缓存抄 `editor/relations.py:242-258`（`(mtime_ns, size)` 两文件签名）；
**渲染结果不缓存**（含数据与耗时），只在声明/schema 两层缓存。

对外接口
--------
    declarations(pkg_dir, domains=None) -> {domains, warnings, limits, code_enabled}
    declared(pkg_dir, dom, domains=None) -> (规范化声明 | None, [告警])
    active(pkg_dir, dom, domains=None) -> bool
    derived(pkg_dir, dom, key, data, domains=None, decl=None, timeout_ms=None,
            ref_values=None) -> {ok, stage, values, warnings, elapsed_ms, sandbox}
                                                     # ★批 2：派生值落**一次性子进程**
    build(pkg_dir, dom, key, data, domains=None, decl=None, derived=None) -> 树外壳
                                                     # `derived` 给了才用派生；不传 = 批 1 的 D0 语义
    tree_problems(tree) -> [可读问题]                            # ★批 2：父侧树校验（只报不改）
    render_warnings(pkg_dir, domains=None) -> [可读告警]        # 并入既有告警出口
    limits() -> dict                                            # /render 的 limits 小节
"""
from __future__ import annotations

import hashlib
import json
import os
import time

from . import render_decl as RD
from ._util import file_sig as _sig

HERE = os.path.dirname(os.path.abspath(__file__))
FRAMEWORK_ROOT = os.path.dirname(HERE)

RENDER_DIR_REL = "editor/render"          # 每域一份声明（定案）
LEGACY_REL = "editor/render.json"         # 历史单文件形态（弃用警告，仍读）
DOMAINS_REL = "editor/domains.json"
GLOSSARY_REL = "editor/glossary/{dom}.json"

RENDER_VERSION = 1
SOURCE = "package"                        # 树的 source（包声明生效）
MAX_WARNINGS = 64                         # 树/响应里的告警条数上限（契约 §2.1）
MAX_HINT = 200
TIMEOUT_ENV = "FW_RENDER_TIMEOUT"
TIMEOUT_DEFAULT_MS = 1500
MAX_DERIVE_STR = 200                      # 派生展示串上限（与 MAX_HINT 同源）
MAX_VALUE_ITEMS = 200                     # 回程值容器上限（契约 §4.4 的 list 项）
MAX_VALUE_DEPTH = 6                       # 回程值嵌套深度上限
MAX_VALUE_KEY = 80                        # 回程值字典键长上限

_CACHE: dict = {}                         # 包目录 -> (签名, 解析结果)
_CACHE_MAX = 500
_SCHEMA_CACHE: dict = {}                  # (包目录, 域) -> (签名, 字段集 | None, 必填集)
_SCHEMA_CACHE_MAX = 500


# ═══════════════════════════ 一、文件与解析（纯 stdlib，无包 import） ═══════════════════════════
def _key(pkg_dir) -> str:
    return os.path.normpath(os.path.abspath(str(pkg_dir))) if pkg_dir else ""


def decl_dir(pkg_dir: str) -> str:
    return os.path.join(pkg_dir, RENDER_DIR_REL)


def legacy_file(pkg_dir: str) -> str:
    return os.path.join(pkg_dir, LEGACY_REL)


def _read_text(path: str):
    """读一份声明文件 → `(文本 | None, 出错原因 | None)`。**不抛。**"""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read(), None
    except OSError as e:
        return None, str(e)


def _read_json(path: str):
    txt, err = _read_text(path)
    if txt is None:
        return None, None, f"读不了：{err}"
    try:
        return json.loads(txt), txt, None
    except json.JSONDecodeError as e:
        return None, txt, f"坏 JSON：{e}"


def _domain_decls(pkg_dir: str):
    """扫 `editor/render/` → `(文件表 {域: (路径, 字节数)}, [告警])`。

    R1：按**字典序**扫（稳定顺序 → 稳定告警顺序）；`$schema.json` 不是域声明；R5：单文件 ≤ 256 KB、
    文件数 ≤ 128；R4：文件名大小写敏感（Windows 上仍按实际文件名）。
    """
    d = decl_dir(pkg_dir)
    warns: list = []
    out: dict = {}
    if not os.path.isdir(d):
        return out, warns
    try:
        names = sorted(os.listdir(d))
    except OSError as e:
        return out, [f"渲染声明目录读不了（{RENDER_DIR_REL}）：{e} —— 视为无声明"]
    json_names = []
    for n in names:
        full = os.path.join(d, n)
        if not os.path.isfile(full):
            continue
        if n.endswith(".json") and n != "$schema.json":
            json_names.append((n, full))
    if len(json_names) > RD.MAX_FILES:
        warns.append(f"渲染声明文件数超过 {RD.MAX_FILES}（实为 {len(json_names)}）"
                     f" —— 只读前 {RD.MAX_FILES} 个（字典序）")
        json_names = json_names[:RD.MAX_FILES]
    for n, full in json_names:
        dom = n[:-len(".json")]
        try:
            size = os.path.getsize(full)
        except OSError:
            continue
        if size > RD.MAX_FILE_BYTES:
            warns.append(f"渲染声明 {n} 超过 {RD.MAX_FILE_BYTES // 1024} KB（实为 {size} 字节）"
                         " —— 该文件已忽略")
            continue
        out[dom] = (full, size)
    return out, warns


def _legacy_decls(pkg_dir: str, domains: dict):
    """读历史形态 `editor/render.json` → `({域: (原始声明, 路径)}, [告警])`。"""
    path = legacy_file(pkg_dir)
    if not os.path.exists(path):
        return {}, []
    warns = [f"渲染声明：`{LEGACY_REL}` 是**已弃用**形态 —— 请改用 "
             f"`{RENDER_DIR_REL}/<域>.json`（本次仍会读，同名域以每域文件为准）"]
    raw, _txt, err = _read_json(path)
    if err is not None:
        warns.append(f"渲染声明读不了（{LEGACY_REL}）：{err} —— 该文件已忽略")
        return {}, warns
    if not isinstance(raw, dict):
        warns.append(f"渲染声明形状不对（{LEGACY_REL}）：顶层需为 {{{{域: 声明}}}} 对象"
                     f"（实为 {type(raw).__name__}）—— 该文件已忽略")
        return {}, warns
    if "$version" in raw and raw["$version"] != 1:
        warns.append(f"渲染声明 {LEGACY_REL}：$version={raw['$version']!r} 不认识（只认 1）"
                     " —— 该文件已忽略")
        return {}, warns
    out = {}
    for dom, obj in raw.items():
        if dom == "$version":
            continue
        if dom not in domains:
            warns.append(f"渲染声明：域 {dom!r} 不在该包的有效域表里 —— 该条已忽略")
            continue
        if not isinstance(obj, dict):
            warns.append(f"渲染声明 {LEGACY_REL}.{dom}：需为对象 —— 该条已忽略")
            continue
        out[dom] = ({**obj}, path)
    return out, warns


# ═══════════════════════════ 二、域表 / schema / 词汇表（零引擎 import） ═══════════════════════════
def domains_minimal(pkg_dir: str) -> dict:
    """**只读包自带** `editor/domains.json` 的域表（调用方没给 `domains` 时的兜底）。

    HTTP 路径由 `server.py` 传 `PK.effective_domains()`（含内置默认域）—— 那份才是真源；
    这里只是「不带 server 也能用」的最小兜底，绝不 import `editor.packages`。
    """
    raw, _txt, _err = _read_json(os.path.join(pkg_dir, DOMAINS_REL))
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items()
            if isinstance(k, str) and not k.startswith("$") and isinstance(v, dict)}


def _safe_rel(fn: str) -> bool:
    if not isinstance(fn, str) or not fn or os.path.isabs(fn):
        return False
    if ".." in fn.replace("\\", "/").split("/"):
        return False
    return not (len(fn) > 1 and fn[1] == ":")


def _schema_path(pkg_dir, dom: str, domains: dict | None):
    """schema 文件路径：**包内优先 → 框架回退**（抄 `packages.schema_path()` 的口径，
    6 行逻辑重复一次是**故意的代价**：换来 `render.py` 零 `editor.packages` import）。"""
    meta = (domains or {}).get(dom) or {}
    fn = meta.get("schema")
    if not fn or not _safe_rel(fn):
        return None
    if pkg_dir:
        for cand in (os.path.join(pkg_dir, "schemas", fn),
                     os.path.join(pkg_dir, fn.replace("\\", "/"))):
            if os.path.isfile(cand):
                return cand
    fw = os.path.join(FRAMEWORK_ROOT, "schemas", fn)
    return fw if os.path.exists(fw) else None


def _resolve_ref(node, schema):
    """`{"$ref": "#/$defs/X"}` → 该 def（只认**本文档内**的 `$defs` 引用）。"""
    if isinstance(node, dict) and isinstance(node.get("$ref"), str) \
            and node["$ref"].startswith("#/$defs/"):
        return (schema.get("$defs") or {}).get(node["$ref"].rsplit("/", 1)[-1]) or {}
    return node if isinstance(node, dict) else {}


def _sub_fields(schema, root: str):
    """根字段是数组时，取**元素对象**的属性名集合（`ItemSpec` 相对路径的根，契约 §1.3）。"""
    props = (((schema.get("$defs") or {}).get(schema.get("x-primary") or "") or {})
             .get("properties") or {})
    node = _resolve_ref(props.get(root), schema)
    if not node:
        return None
    if node.get("type") == "array" or "items" in node:
        items = _resolve_ref(node.get("items"), schema)
        p = items.get("properties") if isinstance(items, dict) else None
        return set(p) if isinstance(p, dict) else None
    return None


def _schema_info(pkg_dir, dom: str, domains: dict | None):
    """`(根字段集 | None, 必填集, 子字段表, 告警)`；根字段集 `None` = **不做**根字段校验（不拦）。"""
    path = _schema_path(pkg_dir, dom, domains)
    if not path:
        return None, set(), {}, [f"渲染声明 {dom}：该域没有可用 schema —— 字段路径**未做**根字段"
                                 "校验（不拦，照渲染）"]
    key = (_key(pkg_dir), dom)
    sig = _sig(path)
    hit = _SCHEMA_CACHE.get(key)
    if hit is not None and hit[0] == sig:
        return hit[1], set(hit[2]), dict(hit[3]), []
    raw, _txt, err = _read_json(path)
    if err is not None or not isinstance(raw, dict):
        return None, set(), {}, [f"渲染声明 {dom}：schema 读不了（{os.path.basename(path)}："
                                 f"{err or '形状不对'}）—— 字段路径未做根字段校验（不拦）"]
    meta = (domains or {}).get(dom) or {}
    primary = meta.get("primary") or raw.get("x-primary")
    d = ((raw.get("$defs") or {}).get(primary) or {}) if primary else {}
    props = d.get("properties")
    if not isinstance(props, dict) or not props:
        return None, set(), {}, [f"渲染声明 {dom}：schema 里找不到 $defs[{primary!r}].properties"
                                 " —— 字段路径未做根字段校验（不拦）"]
    fields = {k for k in props if isinstance(k, str)}
    required = {k for k in (d.get("required") or []) if isinstance(k, str)}
    subs = {}
    for root in fields:
        sub = _sub_fields(raw, root)
        if sub:
            subs[root] = sub
    if len(_SCHEMA_CACHE) > _SCHEMA_CACHE_MAX:
        _SCHEMA_CACHE.clear()
    _SCHEMA_CACHE[key] = ((sig), fields, tuple(sorted(required)), subs)
    return fields, required, subs, []


def _glossary(pkg_dir, dom: str) -> dict:
    """包自带词汇表 `editor/glossary/<域>.json` → `{字段: {zh, note}}`（缺/坏 → `{}`，不告警）。"""
    path = os.path.join(pkg_dir, GLOSSARY_REL.format(dom=dom))
    raw, _txt, _err = _read_json(path)
    if not isinstance(raw, dict):
        return {}
    fields = raw.get("fields")
    if not isinstance(fields, dict):
        return {}
    return {k: v for k, v in fields.items() if isinstance(v, dict)}


# ═══════════════════════════ 三、声明解析（缓存 + 全部告警） ═══════════════════════════
def _load_all(pkg_dir, domains: dict | None):
    """读该包全部 render 声明 → `(结果 dict, [告警])`（按签名缓存）。

    结果：`{"decls": {域: 声明}, "info": {域: DomainRenderInfo}, "warnings": [...],
             "code_enabled": bool}`。
    """
    key = _key(pkg_dir)
    if not key:
        return {"decls": {}, "info": {}, "warnings": [], "code_enabled": False}, []
    doms = domains if domains is not None else domains_minimal(key)
    files, warns = _domain_decls(key)
    legacy, legacy_w = _legacy_decls(key, doms)
    warns = warns + legacy_w
    _have = {d: f for d, (f, _s) in files.items()}
    _have.update({d: p for d, (_o, p) in legacy.items()})
    sig = (tuple(sorted((d, _sig(p)) for d, p in _have.items())),
           _sig(os.path.join(key, DOMAINS_REL)),
           tuple(sorted((d, _sig(_schema_path(key, d, doms) or "")) for d in sorted(doms))))
    hit = _CACHE.get(key)
    if hit is not None and hit[0] == sig:
        return hit[1], list(hit[2])
    out = {"decls": {}, "info": {}, "warnings": [], "code_enabled": False}
    # ① 每域文件（字典序）—— 同名域以它为准
    for dom, (path, _size) in sorted(files.items()):
        rel = f"{RENDER_DIR_REL}/{os.path.basename(path)}"
        raw, txt, err = _read_json(path)
        if err is not None:
            warns.append(f"包渲染声明读不了（{rel}）：{err} —— 已回退第 2 层视图")
            out["info"][dom] = _bad_info(rel, [warns[-1]])
            continue
        if dom not in doms:
            msg = (f"渲染声明：域 {dom!r} 不在该包的有效域表里 —— 该文件已忽略")
            warns.append(msg)
            out["info"][dom] = _bad_info(rel, [msg])
            continue
        _one_decl(out, warns, key, dom, raw, rel, doms, hashlib.sha1(
            (txt or "").encode("utf-8")).hexdigest()[:16])
    # ② 历史形态（同名域已在上一步赢）
    for dom, (raw, path) in sorted(legacy.items()):
        rel = LEGACY_REL
        if dom in out["decls"] or (dom in out["info"] and out["info"][dom].get("file") != rel):
            warns.append(f"渲染声明 {dom}：`{LEGACY_REL}` 与 `{RENDER_DIR_REL}/{dom}.json` 同时"
                         "存在 —— 以每域文件为准（该条已忽略）")
            continue
        txt = json.dumps(raw, ensure_ascii=False)
        _one_decl(out, warns, key, dom, {**raw}, rel, doms,
                  hashlib.sha1(txt.encode("utf-8")).hexdigest()[:16])
    # ③ 代码面存在性（**只看文件名，不读内容**）
    #    ★ 批 2 口径（作业书 §1 裁定）：**批 3（代码档）已砍** —— `render/<域>.py` 一律
    #    「明确忽略 + 告警，绝不执行」；`$allow_code:true` 同样只记存在性、不发车。
    for dom in sorted(doms):
        d = decl_dir(key)
        for suffix, flag in ((".py", "has_code"), (".html.js", "has_iframe")):
            p = os.path.join(d, f"{dom}{suffix}")
            if not os.path.isfile(p):
                continue
            info = out["info"].get(dom)
            if info is None:
                info = out["info"][dom] = _bad_info(f"{RENDER_DIR_REL}/{dom}{suffix}", [])
            info[flag] = True
            out["code_enabled"] = True
            if suffix == ".py":
                msg = (f"渲染声明：`{RENDER_DIR_REL}/{dom}.py`（代码档）存在，但**批 3 已砍**"
                       " —— 本批只记存在性：**忽略该文件、绝不执行**（值一律走白名单派生）")
                warns.append(msg)
                info["warnings"].append(msg)
    for dom, info in out["info"].items():
        if (out["decls"].get(dom) or {}).get("allow_code"):
            out["code_enabled"] = True
            msg = (f"渲染声明 {dom}：`$allow_code: true`，但**批 3（代码档）已砍** —— "
                   "本批忽略该开关：**绝不执行包内任何函数**")
            warns.append(msg)
            info["warnings"].append(msg)
    out["warnings"] = list(warns)
    if len(_CACHE) > _CACHE_MAX:
        _CACHE.clear()
    _CACHE[key] = (sig, out, warns)
    return out, list(warns)


def _bad_info(rel: str, warns: list) -> dict:
    return {"file": rel, "version": None, "extends": None, "active": False,
            "has_code": False, "has_iframe": False, "allow_code": False,
            "blocks": 0, "slots": [], "derives": [], "warnings": list(warns)}


def _one_decl(out: dict, warns: list, pkg_dir: str, dom: str, raw, rel: str,
              domains: dict, sha: str) -> None:
    fields, _required, subs, sw = _schema_info(pkg_dir, dom, domains)
    warns.extend(sw)
    decl, dw = RD.norm_decl(raw, dom, fields, sub_fields=subs)
    if decl is None:
        warns.extend(dw)
        out["info"][dom] = _bad_info(rel, dw)
        return
    decl["file"] = rel
    decl["decl_sha"] = sha
    decl["fields_known"] = sorted(fields) if fields is not None else None
    out["decls"][dom] = decl
    out["info"][dom] = {
        "file": rel, "version": decl["version"], "extends": decl["extends"], "active": True,
        "has_code": bool(decl.get("allow_code")), "has_iframe": False,
        "blocks": len(decl["layout"]) + sum(len(s["blocks"]) for s in decl["sections"]),
        "slots": sorted(decl["slots"]), "derives": sorted(decl["derives"]),
        "warnings": list(dw) + list(sw)}
    # 声明级告警也要进总出口（黄条），但不重复 in info
    warns.extend(w for w in dw if w not in warns)


def render_warnings(pkg_dir, domains=None) -> list:
    """该包渲染声明面的**全部**可读告警（并入既有告警出口；没声明 = `[]`）。"""
    return list(_load_all(pkg_dir, domains)[1])


def declarations(pkg_dir, domains=None) -> dict:
    """`GET /api/package/<id>/render` 的内容（**只读声明，不读条目数据**）。"""
    out, warns = _load_all(pkg_dir, domains)
    return {"domains": {d: dict(i) for d, i in sorted(out["info"].items())},
            "warnings": list(warns), "limits": limits(),
            "code_enabled": bool(out["code_enabled"])}


def declared(pkg_dir, dom: str, domains=None):
    """该域的**可激活**声明 → `(声明 | None, [告警])`。"""
    out, warns = _load_all(pkg_dir, domains)
    return out["decls"].get(dom), list(warns)


def active(pkg_dir, dom: str, domains=None) -> bool:
    """该域有没有**解析成功**的 render 声明（`when` 的条目级判定在 `build()` 里做）。"""
    return dom in _load_all(pkg_dir, domains)[0]["decls"]


def limits() -> dict:
    """`/render` 的 `limits` 小节（前端显示/自检用）。"""
    ms = TIMEOUT_DEFAULT_MS
    try:
        ms = int(os.environ.get(TIMEOUT_ENV) or TIMEOUT_DEFAULT_MS)
    except (TypeError, ValueError):
        ms = TIMEOUT_DEFAULT_MS
    return {"max_tree_bytes": RD.MAX_TREE_BYTES, "max_blocks": RD.MAX_TREE_BLOCKS,
            "max_list_items": RD.MAX_LIST_ITEMS, "timeout_ms": ms}


# ═══════════════════════════ 四、渲染树（纯声明 D0） ═══════════════════════════
def _to_text(v) -> str:
    """值 → 展示串（**纯文本**；容器转紧凑 JSON 并截断）。"""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "是" if v else "否"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else repr(v)
    if isinstance(v, str):
        return v
    try:
        s = json.dumps(v, ensure_ascii=False)
    except (TypeError, ValueError):
        s = repr(v)
    return s if len(s) <= MAX_HINT else s[:MAX_HINT - 1] + "…"


def _interp(text, ctx) -> str:
    """插值（**服务端**完成）：`{字段}` / `{字段|zh}` / `{derive:名}`；`{{`/`}}` = 字面量。"""
    s = str(text or "")
    out = []
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch == "{" and i + 1 < n and s[i + 1] == "{":
            out.append("{")
            i += 2
            continue
        if ch == "}" and i + 1 < n and s[i + 1] == "}":
            out.append("}")
            i += 2
            continue
        if ch == "{":
            j = s.find("}", i + 1)
            if j < 0:
                out.append(ch)
                i += 1
                continue
            out.append(_interp_one(s[i + 1:j], ctx))
            i = j + 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _interp_one(body: str, ctx) -> str:
    body = (body or "").strip()
    if not body:
        return ""
    if body.startswith("derive:"):
        name = body[len("derive:"):].strip()
        got = (ctx.get("derived_display") or {}).get(name)
        if got is not None:
            return got                                # ★批 2：派生展示串（沙箱算好、父侧已校验）
        ctx["warn"](f"插值 {{derive:{name}}}：派生值属**批 2** 的沙箱路径"
                    "（本次调用没请求派生 = D0）—— 该插值点渲染为空")
        return ""
    zh = False
    if body.endswith("|zh"):
        zh, body = True, body[:-3].strip()
    if not RD.valid_path(body):
        ctx["warn"](f"插值路径 {body!r} 不合规 —— 该插值点渲染为空")
        return ""
    data = ctx["data"]
    got = RD.path_get(data, body)
    if got is None:
        src = RD.root_field(body)
        if isinstance(data, dict) and src in data:
            return ""                                       # 字段在、值就是空 → 静默
        ctx["warn"](f"插值 {{{body}}} 在条目里取不到 —— 该插值点渲染为空")
        return ""
    if zh:
        ent = ctx["gloss"].get(body) or ctx["gloss"].get(RD.root_field(body)) or {}
        name = ent.get("zh")
        if isinstance(name, str) and name:
            return name
    return _to_text(got)


def _field_ref(path: str, decl: dict, data, gloss: dict, required: set, warn) -> dict:
    ov = (decl.get("fields") or {}).get(path) or {}
    leaf = path.split(".")[-1]
    ent = gloss.get(path) or gloss.get(leaf) or {}
    label = ov.get("label") or ent.get("zh") or leaf
    val = RD.path_get(data, path)
    ref = {"path": path, "label": _to_text(label) if not isinstance(label, str) else label,
           "widget": ov.get("widget") or "auto",
           "readonly": bool(ov.get("readonly") or path in (decl.get("readonly") or [])),
           "hidden": bool(ov.get("hidden")),
           "required": bool(RD.root_field(path) in (required or set())),
           "has_value": val is not None and val != "" and val != [] and val != {}}
    note = ov.get("note") or ent.get("note")
    if isinstance(note, str) and note.strip():
        ref["hint"] = RD.clip(note.strip(), MAX_HINT)
    if ov.get("format"):
        ref["format"] = ov["format"]
    return ref


def _default_item_title(obj, idx: int) -> str:
    """没给 `item` 模板时的兜底标题（标量原样；对象取 name/id；都没有 → 第 N 项）。"""
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        t = _to_text(obj)
        return t or f"第 {idx + 1} 项"
    if isinstance(obj, dict):
        for k in ("name", "title", "id", "key"):
            v = obj.get(k)
            if isinstance(v, str) and v:
                return v
    return f"第 {idx + 1} 项"


def _build_item(spec: dict | None, obj, idx: int, ctx) -> dict:
    warn = ctx["warn"]
    if spec is None:
        return {"title": _default_item_title(obj, idx), "row_index": idx}
    out: dict = {}
    title_t = spec.get("title")
    title = _interp(title_t, {**ctx, "data": obj}) if title_t else _default_item_title(obj, idx)
    out["title"] = title or _default_item_title(obj, idx)
    for key in ("subtitle",):
        t = spec.get(key)
        if t:
            v = _interp(t, {**ctx, "data": obj})
            if v:
                out[key] = v
    badges = []
    for bd in (spec.get("badges") or []):
        if not RD.cond_ok(bd.get("when"), obj):
            continue
        b = {"text": _interp(bd.get("text") or "", {**ctx, "data": obj}),
             "tone": bd.get("tone") or "info"}
        if b["text"]:
            badges.append(b)
    if badges:
        out["badges"] = badges
    flds = []
    for p in (spec.get("fields") or []):
        flds.append(_field_ref(p, ctx["decl"], obj, ctx["gloss"], set(), warn))
    if flds:
        out["fields"] = flds
    out["row_index"] = idx
    return out


def _rows_from(source_field, data, decl, gloss, warn, kv_mode: bool):
    """`kv` 的行 / `list|table` 的原始值列表。

    `kv`：对象 → `{键: 值}` 逐行（键取词汇表中文名）；数组 → 每项 `{label, value}` 的按原样用、
    标量按「第 N 项」；标量 → 单行。
    """
    val = RD.path_get(data, source_field)
    if val is None:
        warn(f"数据来源 {{{source_field}}} 在条目里取不到 —— 该块渲染为空")
        return [] if kv_mode else None
    if isinstance(val, dict):
        if not kv_mode:
            return list(val.values())
        rows = []
        for k, v in val.items():
            leaf = str(k)
            ent = gloss.get(leaf) or {}
            label = ent.get("zh") if isinstance(ent.get("zh"), str) and ent.get("zh") else leaf
            rows.append({"label": label, "value": _to_text(v)})
        return rows
    if isinstance(val, list):
        if not kv_mode:
            return val
        rows = []
        for i, item in enumerate(val):
            if isinstance(item, dict) and isinstance(item.get("label"), str):
                rows.append({"label": _to_text(item["label"]),
                             "value": _to_text(item.get("value"))})
                continue
            leaf = str(source_field).split(".")[-1]
            rows.append({"label": f"{leaf} {i + 1}", "value": _to_text(item)})
        return rows
    if kv_mode:
        return [{"label": RD.clip(str(source_field).split(".")[-1], RD.MAX_LABEL),
                 "value": _to_text(val)}]
    warn(f"数据来源 {{{source_field}}} 不是数组/对象（实为 {type(val).__name__}）"
         " —— 该块按空处理")
    return []


def _derive_items(value):
    """派生值 → `list/table` 的原始项列表（对象 → 键值项 `{"name": 键, "value": 值}`）。"""
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [{"name": k, "value": v} for k, v in value.items()]
    return [value]


def _derive_kv_rows(name: str, value) -> list:
    """派生值 → `kind=kv` 的 `{label, value}` 行（全是展示串）。"""
    if isinstance(value, dict):
        return [{"label": _to_text(k), "value": _to_text(v)} for k, v in value.items()]
    if isinstance(value, list):
        return [{"label": f"{name} {i + 1}", "value": _to_text(v)} for i, v in enumerate(value)]
    return [{"label": name, "value": "—" if value is None else _to_text(value)}]


def _build_block(blk: dict, ctx) -> dict | None:
    if not RD.cond_ok(blk.get("when"), ctx["data"]):
        return None
    kind = blk["kind"]
    out = {"id": blk["id"], "kind": kind, "collapsed": bool(blk.get("collapsed"))}
    for k in ("label", "icon", "note"):
        if blk.get(k):
            out[k] = _interp(blk[k], ctx) if k == "label" else blk[k]
    if kind == "fields":
        out["columns"] = blk.get("columns") or 1
        out["items"] = [_field_ref(p, ctx["decl"], ctx["data"], ctx["gloss"],
                                   ctx["required"], ctx["warn"])
                        for p in (blk.get("fields") or [])]
        return out
    if kind == "text":
        out["text"] = _interp(blk.get("text") or "", ctx)
        return out
    src = blk.get("source") or {}
    dname = src.get("derive")
    d_raw = ctx.get("derived_raw") or {}
    if dname is not None and dname in d_raw:
        # ★批 2：数据来源 = 沙箱派生值（父侧已过白名单 + 限额）
        value = d_raw[dname]
        if kind == "kv":
            out["rows"] = _derive_kv_rows(dname, value)
            if not out["rows"]:
                out["empty"] = blk.get("empty") or "（空）"
            return out
        vals = _derive_items(value)
    elif dname is not None:
        ctx["warn"](f"块 {blk['id']}：数据来源 {{derive:{dname}}} 属**批 2** 的沙箱路径"
                    "（本次调用没请求派生 = D0）—— 该块已略过")
        return None
    else:
        field = src.get("field")
        if kind == "kv":
            rows = _rows_from(field, ctx["data"], ctx["decl"], ctx["gloss"], ctx["warn"], True)
            rows = rows if isinstance(rows, list) else []
            # 2026-09-18 修：kv 块同样受 `max_rows` 约束 —— 原实现在此**提前 return**，
            #   走不到下面的 limit 计算 ⇒ 声明了 max_rows 也被静默忽略（数据多时整块全量下发）。
            #   契约把 `max_rows` 定义为**块级**键（render_decl 对所有 kind 归一化，
            #   默认 MAX_ROWS_DEFAULT / 上限 MAX_ROWS），故此处补齐截断 + 告警，口径与 list/table 一致。
            _kv_limit = int(blk.get("max_rows") or RD.MAX_ROWS_DEFAULT)
            if len(rows) > _kv_limit:
                ctx["warn"](f"块 {blk['id']}：数据 {len(rows)} 项超过上限 {_kv_limit} —— "
                            f"已截断到前 {_kv_limit} 项")
                rows = rows[:_kv_limit]
                out["truncated"] = True
            out["rows"] = rows
            if not out["rows"]:
                out["empty"] = blk.get("empty") or "（空）"
            return out
        vals = _rows_from(field, ctx["data"], ctx["decl"], ctx["gloss"], ctx["warn"], False)
        vals = vals if isinstance(vals, list) else []
    limit = int(blk.get("max_rows") or RD.MAX_ROWS_DEFAULT)
    if kind == "list":
        limit = min(limit, RD.MAX_LIST_ITEMS)
    truncated = len(vals) > limit
    if truncated:
        ctx["warn"](f"块 {blk['id']}：数据 {len(vals)} 项超过上限 {limit} —— "
                    f"已截断到前 {limit} 项")
    vals = vals[:limit]
    if kind == "table":
        cols = (blk.get("item") or {}).get("columns") or []
        header = []
        for p in cols:
            leaf = p.split(".")[-1]
            ent = ctx["gloss"].get(p) or ctx["gloss"].get(leaf) or {}
            header.append(ent.get("zh") if isinstance(ent.get("zh"), str) and ent.get("zh") else leaf)
        # ⚠ `headers` 不在契约 §2.2 的树字段表里（表头无处可放）—— 本批新增的**只读展示**键，
        #   已写进 W-L3B1 的「未做项 / 待拍板」；`columns` 保持契约语义（int，1..4）。
        out["headers"] = header
        out["rows"] = [{"cells": [_to_text(RD.path_get(v, p)) for p in cols]} for v in vals]
    else:
        out["list"] = [_build_item(blk.get("item"), v, i, ctx) for i, v in enumerate(vals)]
    if not (out.get("rows") or out.get("list")):
        out["empty"] = blk.get("empty") or "（空）"
    if truncated:
        out["truncated"] = True
    return out


def _append_rest_fields(blocks: list, ctx, fields) -> None:
    """`$extends:"form"`：`layout` 没提到的字段**追加**到最后一个 `kind=fields` 块的末尾。"""
    if not fields:
        return
    decl, gloss, warn = ctx["decl"], ctx["gloss"], ctx["warn"]
    used = set(RD.decl_paths(decl))
    rest = [f for f in sorted(fields) if f not in used and "[" not in f]
    if not rest:
        return
    target = None
    for b in reversed(blocks):
        if b.get("kind") == "fields":
            target = b
            break
    if target is None:
        blocks.append({"id": "b_rest", "kind": "fields", "collapsed": False,
                       "columns": 1, "items": []})
        target = blocks[-1]
    have = {it["path"] for it in target.get("items") or []}
    for f in rest:
        if f in have:
            continue
        target.setdefault("items", []).append(
            _field_ref(f, decl, ctx["data"], gloss, ctx["required"], warn))


def _shrink(tree: dict, warn) -> None:
    """树序列化字节超 256 KB → 从末尾丢块（**不报错**，把已渲染部分给用户）。"""
    def size(obj) -> int:
        try:
            return len(json.dumps(obj, ensure_ascii=False).encode("utf-8"))
        except (TypeError, ValueError):
            return 0

    if size(tree) <= RD.MAX_TREE_BYTES:
        return
    tree["truncated"] = True
    warn(f"渲染树超过 {RD.MAX_TREE_BYTES // 1024} KB —— 已从末尾丢弃块（truncated）")
    dropped = 0
    while size(tree) > RD.MAX_TREE_BYTES:
        tabs = tree.get("tabs") or []
        if not tabs or not (tabs[-1].get("blocks")):
            if len(tabs) > 1:
                tabs.pop()
                dropped += 1
                continue
            break
        tabs[-1]["blocks"].pop()
        dropped += 1
    if dropped:
        warn(f"渲染树共丢弃 {dropped} 个块")


#: 协议里**不允许**出现在树里的键（契约 §2.3 H1：出现即丢弃；树 ≠ HTML）
FORBIDDEN_TREE_KEYS = ("html", "innerhtml", "style", "class", "script", "src",
                       "onerror", "onload", "srcdoc")


def tree_problems(tree) -> list:
    """父侧**树校验**（契约 §2/H1 + §5.1 的回程校验）：纯函数，返回可读问题清单（`[]` = 干净）。

    只**报**不**改**：树的构建者是框架自己（`build()`），这里防的是两件事 ——
    ① 将来有人不小心把 `html`/`style`/`script` 之类的键塞进树（H1 不可协商）；
    ② 顶层形状退化（`tabs` 空 / 分页或块数超限 / 块类型不在白名单）。**不静默**：问题清单由
    调用方并进告警（`server._run_view` 就是那条路）。
    """
    probs: list = []
    if not isinstance(tree, dict):
        return ["渲染树不是对象"]
    stack = [(tree, "tree")]
    guard = 0
    while stack and guard < 20000:
        node, path = stack.pop()
        guard += 1
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(k, str) and k.lower() in FORBIDDEN_TREE_KEYS:
                    probs.append(f"{path}.{k}：协议里不允许这个键（H1：出现即丢弃）")
                if isinstance(v, (dict, list)):
                    stack.append((v, f"{path}.{k}"))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                if isinstance(v, (dict, list)):
                    stack.append((v, f"{path}[{i}]"))
    tabs = tree.get("tabs")
    if not isinstance(tabs, list) or not tabs:
        probs.append("tree.tabs：需为非空数组（契约 §2.1）")
    else:
        if len(tabs) > RD.MAX_TABS:
            probs.append(f"tree.tabs：{len(tabs)} 页超过上限 {RD.MAX_TABS}")
        for i, tab in enumerate(tabs):
            if not isinstance(tab, dict) or not isinstance(tab.get("id"), str) or not tab.get("id"):
                probs.append(f"tree.tabs[{i}]：缺 id（契约 §2.1）")
                continue
            blocks = tab.get("blocks")
            if not isinstance(blocks, list):
                probs.append(f"tree.tabs[{i}].blocks：需为数组")
            elif len(blocks) > RD.MAX_BLOCKS_PER_TAB:
                probs.append(f"tree.tabs[{i}].blocks：{len(blocks)} 块超过上限 "
                             f"{RD.MAX_BLOCKS_PER_TAB}")
            for j, blk in enumerate(blocks if isinstance(blocks, list) else []):
                if not isinstance(blk, dict) or blk.get("kind") not in RD.KINDS:
                    probs.append(f"tree.tabs[{i}].blocks[{j}]：块类型不在白名单"
                                 f"（{' / '.join(RD.KINDS)}）")
    return probs[:16]


# ═══════════════════ 四之二、派生值（批 2：一次性子进程 + 父侧回程硬判） ═══════════════════
def _fmt_date(value) -> str:
    """`format:"date"`：数字（unix 秒）→ `YYYY-MM-DD`；字符串原样。"""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            t = time.gmtime(value)
            return "%04d-%02d-%02d" % (t.tm_year, t.tm_mon, t.tm_mday)
        except (OSError, ValueError, OverflowError):
            pass
    return _to_text(value)


def _fmt_derive(value, fmt: str, name: str, warn) -> str:
    """沙箱回程值 → 展示串（契约 §2.1：`derives.*.value` 是**展示串**）。"""
    if value is None:
        warn(f"派生 {name}：没有值（数据取不到 / 除零 / 计算失败）—— 显示为「—」")
        return "—"
    num = isinstance(value, (int, float)) and not isinstance(value, bool)
    if fmt == "percent" and num:
        s = f"{value * 100:.1f}%"
    elif fmt == "number" and num:
        s = f"{value:,}" if isinstance(value, int) else \
            (f"{value:,.2f}".rstrip("0").rstrip("."))
    elif fmt == "date":
        s = _fmt_date(value)
    else:
        s = _to_text(value)
    if len(s) > MAX_DERIVE_STR:
        warn(f"派生 {name}：展示串超过 {MAX_DERIVE_STR} 字 —— 已截断")
        s = s[:MAX_DERIVE_STR]
    return s


def _clean_value(v, depth: int = 0, where: str = "值"):
    """回程值 → `(干净值, 可用?, [告警])`：**父侧硬判**类型/串长/条目数/深度（契约 §5.1 的①②③④⑦）。"""
    probs: list = []
    if v is None or isinstance(v, bool):
        return v, True, probs
    if isinstance(v, (int, float)):
        if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
            probs.append(f"{where}：非有限浮点（NaN/Inf）—— 已丢弃该派生")
            return None, False, probs
        return v, True, probs
    if isinstance(v, str):
        if len(v) > MAX_DERIVE_STR:
            probs.append(f"{where}：字符串超过 {MAX_DERIVE_STR} 字 —— 已截断")
            return v[:MAX_DERIVE_STR], True, probs
        return v, True, probs
    if depth >= MAX_VALUE_DEPTH:
        probs.append(f"{where}：嵌套超过 {MAX_VALUE_DEPTH} 层 —— 已丢弃该派生")
        return None, False, probs
    if isinstance(v, list):
        if len(v) > MAX_VALUE_ITEMS:
            probs.append(f"{where}：数组 {len(v)} 项超过上限 {MAX_VALUE_ITEMS} —— 已截断")
            v = v[:MAX_VALUE_ITEMS]
        out, ok = [], True
        for x in v:
            cv, cok, p = _clean_value(x, depth + 1, where)
            probs.extend(p)
            ok = ok and cok
            out.append(cv)
        return (out if ok else None), ok, probs
    if isinstance(v, dict):
        if len(v) > MAX_VALUE_ITEMS:
            probs.append(f"{where}：对象 {len(v)} 键超过上限 {MAX_VALUE_ITEMS} —— 已截断")
            v = dict(list(v.items())[:MAX_VALUE_ITEMS])
        out, ok = {}, True
        for k, x in v.items():
            key = k if isinstance(k, str) else _to_text(k)
            if len(key) > MAX_VALUE_KEY:
                key = key[:MAX_VALUE_KEY]
            cv, cok, p = _clean_value(x, depth + 1, where)
            probs.extend(p)
            ok = ok and cok
            out[key] = cv
        return (out if ok else None), ok, probs
    probs.append(f"{where}：值类型 {type(v).__name__} 不在白名单"
                 "（只许 null/bool/数/串/数组/对象）—— 已丢弃该派生")
    return None, False, probs


def derived(pkg_dir, dom: str, key: str, data, domains=None, decl=None,
            timeout_ms=None, ref_values=None) -> dict:
    """★批 2：该域的派生值 —— 在**一次性子进程**里跑**框架白名单函数**（契约 §4）。

    `ok=False`（超时 / 崩 / 输出超限）→ 调用方按 L3 **整域**降级 + 黄条；没有派生声明 →
    `ok=True` + 空 `values`（**不起子进程**，零冷启动成本）。**永不抛。**

    payload 里**没有**包目录/仓根等任何本机路径（契约 §4.1），`allow_code` 恒 `False`
    （批 3 已砍 —— 子进程没有执行包代码的入口）。
    """
    out, all_w = _load_all(pkg_dir, domains)
    if decl is None:
        decl = out["decls"].get(dom)
    if decl is None:
        return {"ok": False, "stage": "decl", "values": {}, "elapsed_ms": None, "sandbox": None,
                "message": f"域 {dom} 没有可用的渲染声明（或声明已损坏）—— 已回退内置视图",
                "warnings": list(all_w)}
    warns = list(all_w)
    for w in ((out["info"].get(dom) or {}).get("warnings") or []):
        if w not in warns:
            warns.append(w)
    if decl.get("when") and not RD.cond_ok(decl["when"], data):
        return {"ok": False, "stage": "decl", "values": {}, "elapsed_ms": None, "sandbox": None,
                "message": f"域 {dom} 的 render 声明 when 条件不满足 —— 本次回退内置视图",
                "warnings": warns}
    # `when` 由**父侧**求值（子进程不做条件判断：少一门语义就少一个逃逸面）
    specs, compute = {}, []
    for name, spec in (decl.get("derives") or {}).items():
        if not isinstance(spec, dict):
            continue
        if spec.get("when") and not RD.cond_ok(spec["when"], data):
            continue
        specs[name] = {"fn": spec.get("fn"), "args": dict(spec.get("args") or {})}
        compute.append(name)
    if not specs:
        return {"ok": True, "stage": "done", "values": {}, "warnings": warns,
                "elapsed_ms": 0, "sandbox": None, "skipped": True}
    from . import render_worker as RW          # ★惰性：`import editor.render` 不拉 worker 进内存
    tmo = int(timeout_ms) if timeout_ms else RW.default_timeout_ms()
    payload = {
        "pkg_id": os.path.basename(os.path.normpath(str(pkg_dir or ""))) or "",
        "dom": dom, "key": str(key),
        "data": data if isinstance(data, dict) else {},
        "decl": {"version": decl.get("version") or 1, "extends": decl.get("extends"),
                 "decl_sha": decl.get("decl_sha") or "", "derives": specs},
        "compute": compute,
        "schema_digest": {"primary": "", "fields": list(decl.get("fields_known") or [])},
        "glossary": {},                        # 词表只在**父侧**用（展示层），子进程不需要
        "ref_values": dict(ref_values or {}),  # `lookup_label` 的候选值：父进程预读（契约 §1.9）
        "limits": {"max_output_bytes": RW.MAX_OUTPUT_BYTES, "max_elements": RW.MAX_ELEMENTS,
                   "max_depth": MAX_VALUE_DEPTH, "timeout_ms": tmo},
        "caps": list(RW.CAPS),                 # ["decl","derive"] —— **没有** "code"
        "allow_code": False,                   # ★批 3 已砍：恒 False（声明写 true 也不发车）
    }
    res = RW.invoke(payload, timeout_ms=tmo)
    if not res.get("ok"):
        return {"ok": False, "stage": res.get("stage") or "derive", "values": {},
                "elapsed_ms": res.get("elapsed_ms"), "sandbox": res.get("sandbox"),
                "message": res.get("message") or "派生沙箱子进程失败 —— 已回退内置视图",
                "warnings": warns + [w for w in (res.get("warnings") or []) if w not in warns]}
    raw = res.get("values") if isinstance(res.get("values"), dict) else {}
    clean: dict = {}
    for name in specs:
        if name not in raw:
            continue
        cv, ok, probs = _clean_value(raw[name], where=f"派生 {name}")
        for p in probs:
            if p not in warns:
                warns.append(p)
        if ok:
            clean[name] = cv
    for name in raw:                           # 回程里**声明外**的名字 → 丢弃 + 告警（绝不透传）
        if name not in specs:
            msg = f"派生沙箱回了声明外的名字 {name!r} —— 已丢弃（绝不透传）"
            if msg not in warns:
                warns.append(msg)
    for w in (res.get("warnings") or []):
        if w not in warns:
            warns.append(w)
    return {"ok": True, "stage": "done", "values": clean, "warnings": warns,
            "elapsed_ms": res.get("elapsed_ms"), "sandbox": res.get("sandbox"),
            "echo": res.get("echo")}


def build(pkg_dir, dom: str, key: str, data, domains=None, decl=None, derived=None) -> dict:
    """声明 → 受限渲染树。

    * 不给 `derived` = **批 1 的 D0 语义**（派生值一行不算、`{derive:…}` 渲染为空 + 告警）；
    * 给 `derived`（`{派生名: 回程值}`，来自 `derived()` = 沙箱子进程）→ 落 `tree["derives"]`、
      `{derive:名}` 插值、`source:{derive:名}` 块。

    `derived` 的每个值都**已经**在 `derived()` 里过完白名单/类型/长度/深度判；本函数只做
    「有没有这个键」的判定，绝不对沙箱回程值做**求值**（不能求值 = 没有代码入口）。
    返回 `{ok, ...}`：`ok=False` 时带 `stage` 与 `message`（调用方按 L3 降级 + 黄条）；
    任何坏输入都**不抛**。
    """
    t0 = time.perf_counter()
    warns: list = []
    seen: set = set()
    state = {"cut": False}

    def warn(msg: str) -> None:
        if msg in seen:
            return
        seen.add(msg)
        if len(warns) >= MAX_WARNINGS:
            state["cut"] = True
            return
        warns.append(msg)

    out, all_w = _load_all(pkg_dir, domains)
    if decl is None:
        decl = out["decls"].get(dom)
    if decl is None:
        return {"ok": False, "stage": "decl",
                "message": f"域 {dom} 没有可用的渲染声明（或声明已损坏）—— 已回退内置视图",
                "warnings": list(all_w), "view": None, "domain": dom, "key": key}
    # 声明级告警（未知块/未知键/R3 忽略…）也进树 —— 前端黄条据此可见，**不许静默**
    for w in ((out["info"].get(dom) or {}).get("warnings") or []):
        warn(w)
    if decl.get("when") and not RD.cond_ok(decl["when"], data):
        return {"ok": False, "stage": "decl",
                "message": f"域 {dom} 的 render 声明 when 条件不满足 —— 本次回退内置视图",
                "warnings": list(all_w), "view": None, "domain": dom, "key": key}
    fields, required, _subs, sw = _schema_info(pkg_dir, dom, domains)
    for w in sw:
        warn(w)
    gloss = _glossary(pkg_dir, dom)
    d_raw = derived if isinstance(derived, dict) else {}
    # ★批 2：派生展示串（父侧格式化；`when` 不满足 / 沙箱没回值 → 不进树、不显示）
    d_disp = {}
    for name, spec in (decl.get("derives") or {}).items():
        if name not in d_raw:
            continue
        if spec.get("when") and not RD.cond_ok(spec["when"], data):
            continue
        entry = {"label": name, "value": _fmt_derive(d_raw[name], spec.get("format") or "plain",
                                                     name, warn)}
        if spec.get("tone") and spec["tone"] != "info":
            entry["tone"] = spec["tone"]
        if spec.get("format") and spec["format"] != "plain":
            entry["format"] = spec["format"]
        d_disp[name] = entry
    ctx = {"data": data if isinstance(data, dict) else {}, "decl": decl, "gloss": gloss,
           "required": required, "warn": warn,
           "derived_raw": d_raw, "derived_display": {k: v["value"] for k, v in d_disp.items()}}
    for name, spec in (decl.get("derives") or {}).items():        # 标签也能插值（含 {derive:…}）
        if name in d_disp and spec.get("label"):
            d_disp[name]["label"] = _interp(spec["label"], ctx)
    blocks: list = []
    for blk in (decl["layout"] or []):
        nb = _build_block(blk, ctx)
        if nb is not None:
            blocks.append(nb)
    tabs: list = []
    if decl["sections"]:
        for sec in decl["sections"]:
            if not RD.cond_ok(sec.get("when"), ctx["data"]):
                continue
            sblocks = []
            for blk in sec.get("blocks") or []:
                nb = _build_block(blk, ctx)
                if nb is not None:
                    sblocks.append(nb)
            tabs.append({"id": sec["id"], "label": _interp(sec.get("label") or sec["id"], ctx),
                         **({"icon": sec["icon"]} if sec.get("icon") else {}),
                         "blocks": sblocks[:RD.MAX_BLOCKS_PER_TAB]})
    else:
        tabs.append({"id": "main",
                     "label": _interp(decl.get("title") or "", ctx) or None,
                     "blocks": blocks[:RD.MAX_BLOCKS_PER_TAB]})
    truncated = False
    if len(blocks) > RD.MAX_BLOCKS_PER_TAB and not decl["sections"]:
        warn(f"块数超过 {RD.MAX_BLOCKS_PER_TAB} —— 已截断（truncated）")
        truncated = True
    if len(tabs) > RD.MAX_TABS:                     # 契约 §2.1：`tabs` ≤ 6
        warn(f"分组数超过 {RD.MAX_TABS} —— 多出的分组已并入最后一个分页（truncated）")
        head, rest = tabs[:RD.MAX_TABS], tabs[RD.MAX_TABS:]
        last = head[-1]
        for t in rest:
            for b in (t.get("blocks") or []):
                if len(last.setdefault("blocks", [])) >= RD.MAX_BLOCKS_PER_TAB:
                    break
                last["blocks"].append(b)
        tabs = head
        truncated = True
    if decl["extends"] == "form" and fields:
        for t in tabs:
            _append_rest_fields(t.get("blocks") or [], ctx, fields)
    for t in tabs:
        if t.get("label") is None:
            t.pop("label", None)

    title = _interp(decl.get("title") or "", ctx)
    meta = (domains or domains_minimal(pkg_dir)).get(dom) or {}
    over = {}
    for path, ov in (decl.get("fields") or {}).items():
        keep = {k: ov[k] for k in ("label", "note", "widget", "hidden", "format") if ov.get(k)}
        if keep:
            over[path] = keep
    ro = list(decl.get("readonly") or [])
    for path, ov in (decl.get("fields") or {}).items():
        if ov.get("readonly") and path not in ro:
            ro.append(path)
    tree = {"ok": True, "render_version": RENDER_VERSION, "domain": dom, "key": key,
            "source": SOURCE, "decl_sha": decl.get("decl_sha") or "",
            "title": title or meta.get("label") or dom,
            "icon": decl.get("icon") or meta.get("icon") or None,
            "tabs": tabs, "readonly_paths": ro, "field_overrides": over,
            "warnings": warns, "elapsed_ms": 0, "truncated": truncated}
    if d_disp:                                     # ★批 2：派生结果（value 是**展示串**）
        tree["derives"] = d_disp
    _shrink(tree, warn)
    tree["warnings"] = warns
    if state["cut"]:
        tree["warnings_truncated"] = True
    tree["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
    return tree
