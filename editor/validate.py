# -*- coding: utf-8 -*-
"""条目校验 —— JSON Schema 校验（有 jsonschema 用它，没有则内置最小校验器）。

与游戏仓 `schema/validate.py` 的区别：那个是**全量表审计**（ast 解析 py 表 +
跨表引用完整性，绑死该游戏自己的数据）；这里是**编辑器用**的单条校验（吃 JSON dict，
按域 schema 的 primary def 校验）。第三方游戏可以替换 `schemas/` 下的 schema。

对外接口：
    load_schema(dom, pkg_dir=None) -> dict | None
    schema_warnings(dom, pkg_dir=None) -> [可读告警]（坏 schema 降级时非空）
    primary_def(dom, pkg_dir=None) -> (schema, def_name) | (None, None)
    validate_entry(dom, data, pkg_dir=None) -> [错误文案]

`pkg_dir` 省略 = 只认框架内置域（旧行为逐字不变）。给了包目录 → 域元数据走
`packages.effective_domains(pkg_dir)`：包自带的域声明（`<pkg>/editor/domains.json`）
可以新增自己的域、或覆盖同名内置域的 schema；schema 文件按
`packages.schema_path()` 解析 —— **包内优先，框架回退**：

    <pkg>/schemas/<声明值>  →  <pkg>/<声明值>  →  框架 schemas/<声明值>  →  None（不校验）

包自带的那份 schema 读不了（坏 JSON / 权限）→ **不炸、不静默**：回退框架那份（若在）
并按框架规则校验，同时给一条可读告警（`schema_warnings()`）；框架那份也读不了 →
该域暂时不校验（编辑器照旧可增删改），告警照留。
"""
from __future__ import annotations

import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_DIR = os.path.join(os.path.dirname(HERE), "schemas")

try:                                     # 可选依赖：没有就走最小校验
    import jsonschema as _js            # type: ignore
except Exception:                        # noqa: BLE001
    _js = None

_cache: dict = {}
_CACHE_MAX = 500


def _read_schema_file(path: str):
    """读一份 schema 文件 → (schema | None, 出错原因)。**不抛。**"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), ""
    except (OSError, json.JSONDecodeError) as e:
        return None, f"{os.path.basename(path)} 读不了：{e}"


def _resolve_schema(dom: str, pkg_dir=None):
    """按 `packages.schema_path()` 的**包内优先 → 框架回退**读 schema
    → `(schema | None, [可读告警])`。**坏 schema 不炸**（见模块 docstring）。"""
    from . import packages as P
    p = P.schema_path(pkg_dir, dom)
    if not p:
        return None, []                    # 没声明 / 找不到 → 不校验（旧行为）
    out, err = _read_schema_file(p)
    if out is not None:
        return out, []
    # 包内那份坏了 → 降级回退框架那份（并说清楚，不静默）
    warns = [f"域 {dom} 的 schema 读不了（{err}）"]
    # ★ B2b：回退那份按**包声明的 schema 文件名**找（`framework_schema_path()`）——
    #   不能再问「域名在不在内置集里」：内容域（skills / items …）由包声明，内置集已没有它们。
    fw = P.framework_schema_path(pkg_dir, dom) if pkg_dir else P.schema_path(None, dom)
    if fw and os.path.normpath(fw) != os.path.normpath(p):
        out, err2 = _read_schema_file(fw)
        if out is not None:
            warns.append(f"已回退框架 schemas/{os.path.basename(fw)}"
                         "（该域仍按框架规则校验）")
            return out, warns
        warns.append(f"框架 schemas/{os.path.basename(fw)} 也读不了（{err2}）")
    warns.append("该域暂时不校验（编辑器仍可增删改，不会 500）")
    return None, warns


def schema_info(dom: str, pkg_dir=None) -> tuple:
    """`(schema | None, [可读告警])` —— 带缓存（键含包目录）。"""
    key = (str(pkg_dir or ""), dom)
    hit = _cache.get(key)
    if hit is not None:
        return hit[0], list(hit[1])
    out, warns = _resolve_schema(dom, pkg_dir)
    if len(_cache) > _CACHE_MAX:
        _cache.clear()
    _cache[key] = (out, warns)
    return out, list(warns)


def load_schema(dom: str, pkg_dir=None):
    """该域生效的 schema（包内优先 → 框架回退）；没有 → None（= 不校验）。"""
    return schema_info(dom, pkg_dir)[0]


def schema_warnings(dom: str, pkg_dir=None) -> list:
    """读该域 schema 时的可读告警（空 = 一切正常）。坏包自带 schema → 降级说明。"""
    return schema_info(dom, pkg_dir)[1]


def primary_def(dom: str, pkg_dir=None):
    from . import packages as P
    d = P.domain_meta(pkg_dir, dom) or {}
    name = d.get("primary")
    schema = load_schema(dom, pkg_dir)
    if not schema or not name:
        return None, None
    return schema, name


def _path_join(path: list) -> str:
    out = ""
    for p in path:
        out += f"[{p}]" if isinstance(p, int) else (f".{p}" if out else str(p))
    return out or "(根)"


def validate_entry(dom: str, data: dict, pkg_dir=None) -> list:
    """返回错误文案列表（空 = 通过）。`pkg_dir` 省略 = 只认框架内置域。"""
    schema, name = primary_def(dom, pkg_dir)
    if not schema or not name:
        return []                        # 无 schema 的域 = 不校验（编辑器仍可增删改）
    defs = (schema.get("$defs") or {})
    target = defs.get(name)
    if not target:
        return [f"schema 缺少 $defs[{name}]"]
    sub = dict(schema)
    sub["$defs"] = defs
    sub.pop("$id", None)
    if _js is not None:
        v = _js.Draft202012Validator(target, resolver=_js.RefResolver.from_schema(sub))
        errs = sorted(v.iter_errors(data), key=lambda e: list(e.absolute_path))
        return [f"{_path_join(list(e.absolute_path))}: {e.message}" for e in errs]
    return _mini_validate(target, data, defs, [])


# ───────────────── 内置极简校验器（没装 jsonschema 时的 fallback）─────────────────
# 设计底线（**与 jsonschema 行为逐例等价；无法等价处一律「放过」**）：
#   编辑器里**假红比漏报贵得多** —— 漏报只是少拦一条脏数据；假红会让用户以为好数据
#   坏了、甚至逼内容侧去「修」本来正确的数据。所以本实现只报「jsonschema 也一定会
#   报」的错，宁可少报。
#
# 已实现（与 jsonschema 的 Draft2020-12 语义对齐）：
#   $ref / type / enum / const / allOf / anyOf / oneOf / required / properties /
#   patternProperties / additionalProperties / propertyNames / minProperties /
#   maxProperties / items / prefixItems / minItems / maxItems / uniqueItems /
#   minLength / maxLength / pattern / minimum / maximum / exclusiveMinimum /
#   exclusiveMaximum / boolean schema（true / false）
#
# **有意不实现**（宁放过不假红，写在这里免得后人当漏项补上去）：
#   · `not` / `if-then-else` / `dependentRequired` / `dependentSchemas`：语义是
#     「子 schema **不**通过 → 报错」，而本校验器内部刻意偏保守（遇到没实现的关键字
#     倾向判「通过」）→ 装进 `not`/`if` 会被**反向放大成假红**，所以整条不判。
#   · `contains` / `minContains` / `maxContains`：同上（「存在一根……」配保守内部有假红风险）。
#   · `unevaluatedProperties` / `unevaluatedItems`：需要完整求值轨迹，做不精确就会假红。
#   · `multipleOf`：浮点容差口径易与 jsonschema 差一点点 → 会造成假红。
#   · `format`：jsonschema 默认（不挂 format_checker）也不校验，等价于不判。
#   · 认不出的 schema 形态（非 dict/dict 里的陌生关键字、外部 `$ref`）一律放过。
#
# 注：`_mini_validate` 的签名保持 `(sch, val, defs, path)` 兼容（第 5 个参数是内部
# 递归用的纯 `$ref` 链防护，正常调用不用传）。

_TRUE_SENTINEL = object()
_FALSE_SENTINEL = object()


def _mini_unbool(x):
    """把 True/False 换成唯一哨兵 —— 免得 `True == 1`（与 jsonschema `_utils.unbool` 同义）。"""
    if x is True:
        return _TRUE_SENTINEL
    if x is False:
        return _FALSE_SENTINEL
    return x


def _mini_eq(a, b) -> bool:
    """与 jsonschema `_utils.equal` 同义的相等判定（bool 不与 0/1 混同，容器逐元素递归）。"""
    if a is b:
        return True
    if isinstance(a, str) or isinstance(b, str):
        return a == b
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_mini_eq(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(_mini_eq(a[k], b[k]) for k in a)
    return _mini_unbool(a) == _mini_unbool(b)


def _mini_is_integer(v) -> bool:
    """jsonschema draft6+ 口径：`True` 不算；`3.0` 算（小数部分为 0 的 float 是整数）。"""
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return True
    return isinstance(v, float) and v.is_integer()


def _mini_is_number(v) -> bool:
    """jsonschema `is_number`：bool 不算 number。"""
    if isinstance(v, bool):
        return False
    return isinstance(v, (int, float))


def _mini_type_ok(t, v) -> bool:
    if t == "object":
        return isinstance(v, dict)
    if t == "array":
        return isinstance(v, list)
    if t == "string":
        return isinstance(v, str)
    if t == "boolean":
        return isinstance(v, bool)
    if t == "null":
        return v is None
    if t == "integer":
        return _mini_is_integer(v)
    if t == "number":
        return _mini_is_number(v)
    return True                       # 认不出的 type 名 → 放过（保守）


def _mini_match(pattern, text):
    """`pattern` 用 `re.search`（与 jsonschema 同一套实现）。

    返回 True/False；**坏事（正则坏掉）返回 None** —— 调用方一律跳过（保守，不因自己解析不了就报红）。
    """
    try:
        return re.search(pattern, text) is not None
    except re.error:
        return None


def _mini_ref_def(defs: dict, ref: str):
    """只解析本文件内的 `#/$defs/NAME` 类引用；解析不了（外部 ref / 陌生写法）返回 None = 放过。"""
    if not isinstance(ref, str) or not ref.startswith("#"):
        return None
    tail = ref.lstrip("#").lstrip("/")
    if not tail:
        return None
    name = tail.split("/")[-1].replace("~1", "/").replace("~0", "~")
    out = defs.get(name)
    return out if isinstance(out, (dict, bool)) else None


def _mini_propnames(pn, key, defs, path, refs) -> list:
    """`propertyNames`：拿键名当实例去校验（报错路径挂在宿主对象上，并点名是键名的问题）。"""
    inner = _mini_validate(pn, key, defs, [], refs)
    return [f"{_path_join(path)}: 键名 {key!r} 不合法（propertyNames）—— {m}" for m in inner]


def _mini_validate(sch, val, defs: dict, path: list, _refs: tuple = ()) -> list:
    """最小校验器：与 jsonschema 语义逐例对齐（见本段抬头注释），全部偏「放过」。

    返回错误文案列表（空 = 通过）。`defs` 是所属 schema 的 `$defs`。
    """
    errs: list = []
    if sch is True or sch is None:
        return errs
    if sch is False:                                  # boolean schema false：什么都不允许
        return [f"{_path_join(path)}: 该位置不允许出现任何值（schema 为 false）"]
    if not isinstance(sch, dict):
        return errs

    # ── $ref：先走引用目标；2020-12 里 $ref 的兄弟关键字同样生效 ──
    if "$ref" in sch:
        target = _mini_ref_def(defs, sch.get("$ref"))
        if target is None:
            return errs                               # 解析不了 → 放过（不冒假红风险）
        name = str(sch.get("$ref")).split("/")[-1]
        if name in _refs:
            return errs                               # 纯 $ref 环（数据没往下走）→ 放过
        errs += _mini_validate(target, val, defs, path, _refs + (name,))
        rest = {k: v for k, v in sch.items() if k != "$ref"}
        if rest:
            errs += _mini_validate(rest, val, defs, path, _refs)
        return errs

    # ── 组合关键字 ─────────────────────────────────────────────
    for sub in sch.get("allOf") or []:                # 全部都要过 → 错误累加（本来的行为就对）
        errs += _mini_validate(sub, val, defs, path, _refs)

    if isinstance(sch.get("anyOf"), list):            # 任一支通过即通过（全失败才报错）
        branches = sch["anyOf"]
        if not any(not _mini_validate(b, val, defs, path, _refs) for b in branches):
            errs.append(f"{_path_join(path)}: 不满足 anyOf 的任一分支（{len(branches)} 支全不通过）")

    if isinstance(sch.get("oneOf"), list):            # 恰好一支通过
        branches = sch["oneOf"]
        n_ok = sum(1 for b in branches if not _mini_validate(b, val, defs, path, _refs))
        if n_ok == 0:
            errs.append(f"{_path_join(path)}: 不满足 oneOf 的任一分支（需恰好 1 支通过，实际 0 支）")
        elif n_ok > 1:
            errs.append(f"{_path_join(path)}: 有 {n_ok} 支同时通过 oneOf（需恰好 1 支）")

    # ── type（不早退：jsonschema 里 type 错与 enum/const 错会一起报）──────
    t = sch.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(_mini_type_ok(x, val) for x in types):
            want = "/".join(str(x) for x in types)
            errs.append(f"{_path_join(path)}: 期望 {want}，实为 {type(val).__name__}")

    # ── enum / const（不限类型；用 jsonschema 的相等口径）─────────────
    if isinstance(sch.get("enum"), list):
        if not any(_mini_eq(val, e) for e in sch["enum"]):
            errs.append(f"{_path_join(path)}: 取值 {val!r} 不在枚举内")
    if "const" in sch and not _mini_eq(val, sch["const"]):
        errs.append(f"{_path_join(path)}: 取值 {val!r} ≠ const {sch['const']!r}")

    # ── 字符串 ─────────────────────────────────────────────────
    if isinstance(val, str):
        mn, mx = sch.get("minLength"), sch.get("maxLength")
        if isinstance(mn, int) and not isinstance(mn, bool) and len(val) < mn:
            errs.append(f"{_path_join(path)}: 长度需 ≥ {mn}（实为 {len(val)}）")
        if isinstance(mx, int) and not isinstance(mx, bool) and len(val) > mx:
            errs.append(f"{_path_join(path)}: 长度需 ≤ {mx}（实为 {len(val)}）")
        if isinstance(sch.get("pattern"), str) and _mini_match(sch["pattern"], val) is False:
            errs.append(f"{_path_join(path)}: 不匹配 pattern {sch['pattern']}")

    # ── 数字（bool 不算 number，与 jsonschema 一致）──────────────────
    if _mini_is_number(val):
        for kw, bad, msg in (("minimum", lambda x, b: x < b, "需 ≥"),
                             ("exclusiveMinimum", lambda x, b: x <= b, "需 >"),
                             ("maximum", lambda x, b: x > b, "需 ≤"),
                             ("exclusiveMaximum", lambda x, b: x >= b, "需 <")):
            b = sch.get(kw)
            if _mini_is_number(b) and bad(val, b):
                errs.append(f"{_path_join(path)}: {msg} {b}")

    # ── 对象 ──────────────────────────────────────────────────
    if isinstance(val, dict):
        for r in sch.get("required") or []:
            if isinstance(r, str) and r not in val:
                errs.append(f"{_path_join(path + [r])}: 必填字段缺失")
        mp, xp = sch.get("minProperties"), sch.get("maxProperties")
        if isinstance(mp, int) and not isinstance(mp, bool) and len(val) < mp:
            errs.append(f"{_path_join(path)}: 字段数需 ≥ {mp}（实为 {len(val)}）")
        if isinstance(xp, int) and not isinstance(xp, bool) and len(val) > xp:
            errs.append(f"{_path_join(path)}: 字段数需 ≤ {xp}（实为 {len(val)}）")

        props = sch.get("properties") if isinstance(sch.get("properties"), dict) else {}
        pat_props = sch.get("patternProperties") if isinstance(sch.get("patternProperties"), dict) else {}
        add = sch.get("additionalProperties", True)
        pn = sch.get("propertyNames")
        for k, v in val.items():
            if not isinstance(k, str):                # JSON 对象的键必为 str；异常形态放过
                continue
            hit = False
            if k in props:
                hit = True
                errs += _mini_validate(props[k], v, defs, path + [k], _refs)
            for pat, sub in pat_props.items():
                if isinstance(pat, str) and _mini_match(pat, k) is True:
                    hit = True
                    errs += _mini_validate(sub, v, defs, path + [k], _refs)
            if not hit:
                if add is False:
                    errs.append(f"{_path_join(path + [k])}: 不允许的字段")
                elif isinstance(add, (dict, bool)):
                    errs += _mini_validate(add, v, defs, path + [k], _refs)
            if pn is not None:
                errs += _mini_propnames(pn, k, defs, path, _refs)

    # ── 数组 ──────────────────────────────────────────────────
    if isinstance(val, list):
        mn, mx = sch.get("minItems"), sch.get("maxItems")
        if isinstance(mn, int) and not isinstance(mn, bool) and len(val) < mn:
            errs.append(f"{_path_join(path)}: 元素数需 ≥ {mn}（实为 {len(val)}）")
        if isinstance(mx, int) and not isinstance(mx, bool) and len(val) > mx:
            errs.append(f"{_path_join(path)}: 元素数需 ≤ {mx}（实为 {len(val)}）")

        pi = sch.get("prefixItems")
        start = 0
        if isinstance(pi, list):
            for i, sub in enumerate(pi):
                if i < len(val):
                    errs += _mini_validate(sub, val[i], defs, path + [i], _refs)
            start = len(pi)                          # 2020-12：`items` 只作用于 prefixItems 之后
        items = sch.get("items", True)
        if items is False:
            if len(val) > start:
                errs.append(f"{_path_join(path)}: 第 {start} 个元素之后不允许再有元素")
        elif isinstance(items, (dict, bool)):
            for i in range(start, len(val)):
                errs += _mini_validate(items, val[i], defs, path + [i], _refs)

        if sch.get("uniqueItems") is True:
            for i in range(len(val)):
                for j in range(i + 1, len(val)):
                    if _mini_eq(val[i], val[j]):
                        errs.append(f"{_path_join(path)}: 元素需互不相同（[{i}] 与 [{j}] 重复）")
                        break
                else:
                    continue
                break
    return errs
