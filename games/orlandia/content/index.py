# -*- coding: utf-8 -*-
"""包内名字索引（`content/index.py`）—— 游戏仓 `game/core/index.py`（56 行）**逐字端口**（B13-L7）。

正文一字未改，只换「宿主取件」：
    `from ..data import _INDEXES`  →  宿主 `data` 句柄（`_INDEXES` 是宿主运行期建的**同一只字典**，
                                      包内 `build_index` 写进去、`resolve/display` 读出来，
                                      对象身份不变 → 宿主侧 `C.resolve(...)` 行为逐字相同）

为什么 `_INDEXES` 不切包内域：它是**运行期索引**（`build_index` 的产物，不是声明表），
`editor/domains.json` 里没有对应域；宿主 `game/data/_assembly.py:179+` 用宿主表建它，
建完的索引对象就在宿主 `game.data._INDEXES` 上（消费者：`C.resolve/C.display`）。

⚠️ `pypinyin` 是第三方纯计算库（无 IO/无宿主知识）—— 包内直接用，与宿主同源同版本。
"""
from __future__ import annotations

import importlib
import sys

from pypinyin import lazy_pinyin

_HOST_PKG = "data.plugins.dragonfall.game"
_HOST_PKG_FALLBACK = "game"
_INJECTED = {}


def bind_host(**objs):
    """宿主替身注入（幂等）——键 = 模块名（`data`）。"""
    for k, v in (objs or {}).items():
        if v is not None:
            _INJECTED[k] = v


def lazy_host_module(full_name: str):
    """按**完整模块名**包一个惰性宿主模块句柄 —— 宿主薄壳用它注入自己那棵树的模块：:

        _M.bind_host(data=_M.lazy_host_module(__package__.rsplit(".", 1)[0] + ".data"))

    为什么必须由薄壳注入全名：同一进程里可能并存 `game.*` 与 `data.plugins.dragonfall.game.*`
    两套模块树（plan §8-R2；`tests/` 两种 import 都有）—— 写目标（`_INDEXES` / `MONSTER_LOCS` /
    派生表）必须落在**调用方那棵树**上，否则另一棵树读到空表。
    """
    import importlib

    class _Mod:
        def __getattr__(self, attr):
            return getattr(importlib.import_module(full_name), attr)

    return _Mod()


def _host_module(name: str):
    if name in _INJECTED:
        return _INJECTED[name]
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        m = sys.modules.get("%s.%s" % (prefix, name))
        if m is not None:
            return m
    last = None
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        try:
            return importlib.import_module("%s.%s" % (prefix, name))
        except Exception as exc:                # noqa: BLE001
            last = exc
    raise RuntimeError("index：宿主模块 %s 取不到（%s）——拒绝静默空跑" % (name, last))


def _indexes() -> dict:
    """宿主 `game.data._INDEXES`（**同一只字典**；包内写入宿主可见）。"""
    return _host_module("data")._INDEXES


def pinyin_id(name: str) -> str:
    """中文名 → 拼音 id：狼皮 → lang_pi；保留字母/数字"""
    parts = []
    for ch in name:
        if '\u4e00' <= ch <= '\u9fff':
            parts.append(lazy_pinyin(ch)[0])
        elif ch.isalnum() or ch == '_':
            parts.append(ch.lower())
    return "_".join(parts)


def build_index(table_name: str, table: dict, prefix: str = "", name_field: str = None):
    """从表构建 名字↔id 双向索引。

    table: 内容表（key 即显示名，或 value[name_field] 为显示名）
    prefix: id 前缀（如 mat_ / sk_ / rec_），无则直接用 pinyin_id
    name_field: 若 value 是 dict 且含该字段，用 value[name_field] 做显示名；
                否则 key 本身即显示名。

    v48：若 key 已是 ID（不含中文）→ 直接用 key 作为 id，不再从名字重新生成
    （旧版会把 i_treatment_potion 这类 ID key 再转一次，产生 it_i___t... 畸形 ID）
    """
    n2i, i2n = {}, {}
    for k, v in table.items():
        if name_field and isinstance(v, dict) and v.get(name_field):
            nm = v[name_field]
        else:
            nm = k
        if not any('\u4e00' <= ch <= '\u9fff' for ch in str(k)):
            eid = k  # v48：key 已是 ID，直接采用
        else:
            eid = f"{prefix}{pinyin_id(nm)}" if prefix else pinyin_id(nm)
        # 冲突时 id 保持稳定：若已存在同名 id，追加后缀
        if eid in i2n and i2n[eid] != nm:
            eid = f"{eid}_{len(i2n) + 1}"
        n2i[nm] = eid
        i2n[eid] = nm
    _indexes()[table_name] = {"name_to_id": n2i, "id_to_name": i2n}


def resolve(table_name: str, name_or_id: str):
    """统一解析：输入名字或 id，都返回 id(找不到原样返回)"""
    idx = _indexes().get(table_name, {}).get("name_to_id", {})
    return idx.get(name_or_id, name_or_id)


def display(table_name: str, entity_id: str):
    """id → 显示名(找不到原样返回)"""
    idx = _indexes().get(table_name, {}).get("id_to_name", {})
    return idx.get(entity_id, entity_id)


__all__ = ["pinyin_id", "build_index", "resolve", "display", "bind_host"]
