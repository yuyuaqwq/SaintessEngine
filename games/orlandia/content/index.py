# -*- coding: utf-8 -*-
"""包内名字索引（`content/index.py`）—— 游戏仓 `game/core/index.py`（56 行）**逐字端口**（B13-L7）。

正文（`pinyin_id` / `build_index` / `resolve` / `display`）一字未改；本文件另管**索引归属**：

归属变化（B15-W1，2026-09-14）
------------------------------
* **改前**：`_INDEXES` 是**宿主装配产物** —— 宿主 `game/data/_assembly.py:179-278` 用宿主表建好，
  放在宿主 `game.data._INDEXES` 上；包内 `_indexes()` 反向去读宿主（`data` 句柄的 `_INDEXES`）
  ⇒ 删掉宿主 `game/data`，`resolve/display` 立刻死。
* **改后**：`_INDEXES` = **包内自建**（`content/index_build.py` 逐字端口那份构建逻辑，表来源 = 包内
  门面 / 域读口）；`_indexes()` 首次访问时构建一次，之后同一只字典（宿主 `_assembly` 的
  `build_index(...)` 调用也落在它上面 —— 写入语义与改前「包内写、宿主读同一只字典」等价）。
  **不再有「读宿主 data」的路径**。

兼容面（宿主薄壳 `game/core/index.py` 仍在调，签名/行为保持）
----------------------------------------------------------
* `bind_host(data=…)` / `lazy_host_module(全名)`：保留。**主构建路径不碰它**——唯一消费者是
  `_host_data()`，只给 3 张**无域缺口表**（`WEAPON_TYPES` / `WT_CN` / `QUALITY_CN`）兜底，
  见 `content/index_build.py` 头注「缺口」与报告 `overnight/_w1_index_to_pkg.md`。
* `content/index_build.py::GAP_SOURCES` 记录每张缺口表的实际来源（探针/报告取证用）。

⚠️ `pypinyin` 是第三方纯计算库（无 IO/无宿主知识）—— 包内直接用，与宿主同源同版本。
"""
from __future__ import annotations

import importlib
import sys

from pypinyin import lazy_pinyin

_HOST_PKG = "data.plugins.dragonfall.game"
_HOST_PKG_FALLBACK = "game"
_INJECTED = {}

# 包内自建索引（`content/index_build.build_into` 的产物；模块级唯一一份）
_INDEXES: dict = {}
_BUILT = False


def bind_host(**objs):
    """宿主替身注入（幂等）——键 = 模块名（`data`）。

    兼容注入口：宿主薄壳 `game/core/index.py` 仍按老签名调它（不让宿主 import 炸）。
    **索引构建不依赖它**（15/17 张表全部来自包内）；只有「无域缺口表」在包内无源时才经它兜底。
    """
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


def _data_mod():
    """宿主 `data` 模块句柄（决策项 U1；接口表第 9 行冻结机制 = 注入名 `data`）。"""
    if "data" in _INJECTED:
        return _INJECTED["data"]
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        m = sys.modules.get("%s.data" % prefix)
        if m is not None:
            return m
    raise RuntimeError("index：宿主 `data` 句柄未注入（宿主薄壳 bind_host(data=…) 负责）——拒绝静默空跑")


def _host_data():
    """宿主 `data` 模块 —— **只给「无域缺口表」兜底 + 宿主兼容镜像**（`index_build._gap_tables` 第 ③ 级、
    `_mirror_to_host`）。主构建路径（15/17 张表）的**取值**完全不碰宿主；宿主不可导入 → 抛，
    调用处各自吞掉（缺口表 → `missing`；镜像 → 跳过）。

    决策项 U1（接口表第 9 行）：`game.data` 与 `game.content.py` 谁是真源**不在本波裁定**；
    本波只落**机制** = 注入句柄 `data`（宿主薄壳 `game/core/index.py:28` 注入）→ `sys.modules`
    已加载的宿主 `data`（**不 import 宿主模块树**）→ 抛（不静默空跑）。"""
    return _data_mod()


def _indexes() -> dict:
    """包内自建的名字索引（`content/index_build.build_into` 的产物）。

    首次访问触发构建（惰性：包 import 期不读任何域文件，也不会撞宿主半初始化）；
    构建恰好一次 —— `_BUILT` 先置位再进 `build_into`，故其内部的 `build_index(...)` 重入是安全的。
    """
    global _BUILT
    if not _BUILT:
        _BUILT = True
        from . import index_build as _index_build
        _index_build.build_into(_INDEXES, _host_getter=_host_data)
    return _INDEXES


def _mirror_to_host(table_name: str) -> None:
    """宿主兼容镜像（写入方向，宿主不在就跳过）—— 为什么必须有、为什么是**同一对象**：

    宿主 `game/data/_assembly.py:179-278` 混用两种写法：`build_index(...)` 建表之后
    **直接对 `_INDEXES[...]` 下标读写**（`:193` 写 quality、`:203` 又要 `build_index("weapon_types",…)`、
    `:204/:205` 用 `dict(WT_CN)` 覆盖该表的两个子键、`:252/:260/:268/:278` 写 monsters/fish/npcs/shop_weapons）。
    改前两处指向**同一只 dict**；产物搬到包内 dict 后若不同步，宿主 `:204` 会 `KeyError: 'weapon_types'`，
    而且 `:203` 的裸 `build_index` 会**覆盖掉包内已建好的那把（含 WT_CN 覆盖）**、`:204` 又修不回来
    （实测症状：`C.display("weapon_types","sword")` 由 `剑` 退化成 `sword`）。

    所以镜像写的是**同一只子 dict 对象**（不是拷贝）：宿主随后的子键覆盖 (`:204/:205`) 就落在包内那份上，
    与改前「一只 dict」的语义逐字等价。宿主删掉后这里静默跳过 —— `resolve/display` 不依赖它。
    """
    try:
        host_dict = getattr(_host_data(), "_INDEXES", None)
        if isinstance(host_dict, dict):
            host_dict[table_name] = _INDEXES[table_name]
    except Exception:                                        # noqa: BLE001
        pass


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
    _mirror_to_host(table_name)          # 宿主兼容镜像（宿主 `_assembly` 仍直接下标读写宿主 dict）


def resolve(table_name: str, name_or_id: str):
    """统一解析：输入名字或 id，都返回 id(找不到原样返回)"""
    idx = _indexes().get(table_name, {}).get("name_to_id", {})
    return idx.get(name_or_id, name_or_id)


def display(table_name: str, entity_id: str):
    """id → 显示名(找不到原样返回)"""
    idx = _indexes().get(table_name, {}).get("id_to_name", {})
    return idx.get(entity_id, entity_id)


__all__ = ["pinyin_id", "build_index", "resolve", "display", "bind_host", "_INDEXES", "_indexes"]
