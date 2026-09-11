# -*- coding: utf-8 -*-
"""编辑提示（编辑器用）—— 从**包内已有数据**推导联想，而不是硬编码游戏词汇。

为什么这样做
------------
- 硬编码「技能的种类有：物理/魔法/…」= 把某个游戏的知识写进框架（`tests/test_no_game_vocabulary.py`
  正为此设闸）。而**用包自己的数据**做建议：第三方做什么游戏，建议就跟着变，零框架知识。
- 联想的是**真实存在的东西**：`monsters.skills` 里能选的技能名，就是 `content/data/skills.json`
  里真有的技能 —— 拼错当场可避免（引擎那边静默空放，最难查）。

产出三类（`build(pkg_dir)`）
---------------------------
    refs   {域: [条目 key, ...]}        跨域引用候选（技能/物品/职业…的真 key）
    values {域: {字段路径: [值, ...]}}  同域已有取值（kind / element / effect / mech …）
    keys   {域: {字段路径: [键, ...]}}  对象型字段**已用过的键**（channels / stat_scale / judge …）

`values` / `keys` 只收标量与键名，按出现次数排序（常用在前），各自截断 60 条。
"""
from __future__ import annotations

from . import packages as PK

_MAX = 60


def _bump(bucket: dict, key: str, val) -> None:
    """计数：同值多条目时排前面。"""
    slot = bucket.setdefault(key, {})
    slot[val] = slot.get(val, 0) + 1


def _walk(node, path: str, values: dict, keys: dict) -> None:
    """收集**标量取值**（values）：kind / element / effect / mech 这类自由串的已有写法。"""
    if isinstance(node, dict):
        for k, v in node.items():
            sub = f"{path}.{k}" if path else k
            if isinstance(v, dict):
                _walk(v, sub, values, keys)
            elif isinstance(v, list):
                for x in v:
                    if isinstance(x, (dict, list)):
                        _walk(x, sub, values, keys)
                    elif x not in (None, ""):
                        _bump(values, sub, str(x))
            elif v not in (None, ""):
                _bump(values, sub, str(v))
    elif isinstance(node, list):
        for x in node:
            _walk(x, path, values, keys)


def _collect_obj_keys(node, path: str, keys: dict) -> None:
    """专门收集「对象型字段的键」（channels / stat_scale / judge / cond …）。"""
    if isinstance(node, dict):
        for k, v in node.items():
            sub = f"{path}.{k}" if path else k
            if isinstance(v, dict):
                for kk in v:
                    _bump(keys, sub, kk)
                _collect_obj_keys(v, sub, keys)
            elif isinstance(v, list):
                for x in v:
                    _collect_obj_keys(x, sub, keys)


def _top(bucket: dict, limit: int = _MAX) -> dict:
    """计数桶 → 排序后的名字列表（多的在前，同频按字母）。"""
    out = {}
    for path, counts in bucket.items():
        out[path] = [k for k, _n in sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0])))[:limit]]
    return out


def build(pkg_dir: str) -> dict:
    """给一个包目录算提示表。空表包 → 三类都是空（前端退回纯手填，不报错）。"""
    refs: dict = {}
    values: dict = {}
    keys: dict = {}
    for dom in PK.DOMAINS:
        try:
            table = PK.read_json(PK.domain_path(pkg_dir, dom), {})
        except Exception:                                    # noqa: BLE001
            table = {}
        if not isinstance(table, dict):
            table = {}
        refs[dom] = sorted(str(k) for k in table)[:400]
        v_bucket: dict = {}
        k_bucket: dict = {}
        for entry in table.values():
            if isinstance(entry, dict):
                _walk(entry, "", v_bucket, k_bucket)
                _collect_obj_keys(entry, "", k_bucket)
        values[dom] = _top(v_bucket)
        keys[dom] = _top(k_bucket)
    return {"refs": refs, "values": values, "keys": keys}


def flatten_for_ui(hints: dict) -> dict:
    """给前端的形态：字段路径 → 候选列表（把 values 与 keys 合成一张便于前端一次查）。"""
    val, keyd = hints.get("values") or {}, hints.get("keys") or {}
    out = {}
    for dom in set(val) | set(keyd):
        merged: dict = {}
        for path, vs in (val.get(dom) or {}).items():
            merged.setdefault(path, {})["v"] = vs
        for path, ks in (keyd.get(dom) or {}).items():
            merged.setdefault(path, {})["k"] = ks
        out[dom] = merged
    return {"fields": out, "refs": hints.get("refs") or {}}
