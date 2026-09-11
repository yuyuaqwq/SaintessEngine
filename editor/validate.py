# -*- coding: utf-8 -*-
"""条目校验 —— JSON Schema 校验（有 jsonschema 用它，没有则内置最小校验器）。

与游戏仓 `schema/validate.py` 的区别：那个是**全量表审计**（ast 解析 py 表 +
跨表引用完整性，绑死该游戏自己的数据）；这里是**编辑器用**的单条校验（吃 JSON dict，
按域 schema 的 primary def 校验）。第三方游戏可以替换 `schemas/` 下的 schema。

对外接口：
    load_schema(dom) -> dict | None
    primary_def(dom) -> (schema, def_name) | (None, None)
    validate_entry(dom, data) -> [错误文案]
"""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_DIR = os.path.join(os.path.dirname(HERE), "schemas")

try:                                     # 可选依赖：没有就走最小校验
    import jsonschema as _js            # type: ignore
except Exception:                        # noqa: BLE001
    _js = None

_cache: dict = {}


def load_schema(dom: str):
    if dom in _cache:
        return _cache[dom]
    from . import packages as P
    d = P.DOMAINS.get(dom) or {}
    fn = d.get("schema")
    out = None
    if fn:
        p = os.path.join(SCHEMA_DIR, fn)
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    out = json.load(f)
            except (OSError, json.JSONDecodeError):
                out = None
    _cache[dom] = out
    return out


def primary_def(dom: str):
    from . import packages as P
    d = P.DOMAINS.get(dom) or {}
    name = d.get("primary")
    schema = load_schema(dom)
    if not schema or not name:
        return None, None
    return schema, name


def _path_join(path: list) -> str:
    out = ""
    for p in path:
        out += f"[{p}]" if isinstance(p, int) else (f".{p}" if out else str(p))
    return out or "(根)"


def validate_entry(dom: str, data: dict) -> list:
    """返回错误文案列表（空 = 通过）。"""
    schema, name = primary_def(dom)
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


def _mini_validate(sch: dict, val, defs: dict, path: list) -> list:
    """最小校验器：type / required / enum / minLength（够编辑器拦常见脏数据）。"""
    errs = []
    if not isinstance(sch, dict):
        return errs
    if "$ref" in sch:
        ref = sch["$ref"].split("/")[-1]
        return _mini_validate(defs.get(ref, {}), val, defs, path)
    for key in ("allOf", "anyOf", "oneOf"):
        if key in sch:
            for s in sch[key]:
                errs += _mini_validate(s, val, defs, path)

    t = sch.get("type")
    if t == "object" and not isinstance(val, dict):
        return [f"{_path_join(path)}: 期望 object，实为 {type(val).__name__}"]
    if t == "array" and not isinstance(val, list):
        return [f"{_path_join(path)}: 期望 array，实为 {type(val).__name__}"]
    if t == "string" and not isinstance(val, str):
        return [f"{_path_join(path)}: 期望 string，实为 {type(val).__name__}"]
    if t in ("number", "integer") and not isinstance(val, (int, float)):
        return [f"{_path_join(path)}: 期望 {t}，实为 {type(val).__name__}"]
    if t == "boolean" and not isinstance(val, bool):
        return [f"{_path_join(path)}: 期望 boolean"]

    if isinstance(val, str):
        if sch.get("minLength") and len(val) < sch["minLength"]:
            errs.append(f"{_path_join(path)}: 长度需 ≥ {sch['minLength']}")
        if sch.get("enum") and val not in sch["enum"]:
            errs.append(f"{_path_join(path)}: 取值 {val!r} 不在枚举内")
    elif isinstance(val, (int, float)) and not isinstance(val, bool):
        if sch.get("minimum") is not None and val < sch["minimum"]:
            errs.append(f"{_path_join(path)}: 需 ≥ {sch['minimum']}")
        if sch.get("maximum") is not None and val > sch["maximum"]:
            errs.append(f"{_path_join(path)}: 需 ≤ {sch['maximum']}")

    if isinstance(val, dict):
        for r in sch.get("required", []):
            if r not in val:
                errs.append(f"{_path_join(path + [r])}: 必填字段缺失")
        props = sch.get("properties") or {}
        for k, v in val.items():
            if k in props:
                errs += _mini_validate(props[k], v, defs, path + [k])
            elif sch.get("additionalProperties") is False:
                errs.append(f"{_path_join(path + [k])}: 不允许的字段")
    if isinstance(val, list) and sch.get("items"):
        for i, x in enumerate(val):
            errs += _mini_validate(sch["items"], x, defs, path + [i])
    return errs
