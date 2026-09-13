# -*- coding: utf-8 -*-
"""包内宠物读口（`content/pets.py`）—— 游戏仓 `game/core/pets.py`（9 行）**逐字端口**（B13-L7）。

真源 `game/core/pets.py` 本身**没有实现**：它是一行 re-export（`from ..data.pets import …`），
注释写明「24 章宠物系统：统一从数据层（game/data/pets.py）re-export」。所以本模块的搬法 =
**同名读口**：包内侧唯一名字面，取值/实现仍指向宿主 `game/data/pets.py`（数据层真源，B14 迁）。

为什么不做成二份实现：`game/data/pets.py`（252 行）是**数据层**的宠物表 + 纯函数，宿主各处
仍从它取（`game/data/__init__.py:105`、`game/core/__init__.py:114`）；本线把它整体抄进包 =
在包里造第二个定义点（双源）。按 BRIEF §3.5 跨线/跨层规则：**别层的搬动不归本线**。

包内已进包的相关域：`content/data/pets.json`（16 条宠物行 + `egg_roll`，`derive_pets` 单向导出）
—— B14 把 `game/data/pets.py` 的逻辑搬进包时，本模块就是它的落点（届时
`pet_exp_need` / `pet_exp_mult` / `make_pet_egg` 等在这里实现、改读 pets 域）。

缺口：`PET_POOL` / `PET_EGG_ROLL` / `PET_MAX_LEVEL` / `make_pet_egg` / `pet_exp_need` /
`pet_exp_mult` / `pet_skill_label` / `pet_quality_label` / `pet_line` / `pet_exp_bonus` /
`pct_str` 全部仍是宿主 `game/data/pets.py` 的实现（**宿主句柄**）→ 待 B14。
"""
from __future__ import annotations

import importlib
import sys

_HOST_PKG = "data.plugins.dragonfall.game"
_HOST_PKG_FALLBACK = "game"
_HOST_PETS = None                    # 宿主 `game.data.pets` 模块（注入优先）


def bind_host(pets=None):
    """宿主 `game.data.pets` 注入（幂等）。"""
    global _HOST_PETS
    if pets is not None:
        _HOST_PETS = pets


def lazy_host_module(full_name: str):
    """按**完整模块名**包一个惰性宿主模块句柄 —— 宿主薄壳用它注入自己那棵树的模块：:

        _pkg.bind_host(pets=_pkg.lazy_host_module(__package__.rsplit(".", 1)[0] + ".data.pets"))

    为什么必须由薄壳注入全名：同一进程可能并存 `game.*` 与 `data.plugins.dragonfall.game.*`
    两套模块树（plan §8-R2；`tests/` 两种 import 都有）。
    """
    import importlib

    class _Mod:
        def __getattr__(self, attr):
            return getattr(importlib.import_module(full_name), attr)

    return _Mod()


def _pets():
    """宿主 `game.data.pets`（真源 `from ..data.pets import …`）。"""
    if _HOST_PETS is not None:
        return _HOST_PETS
    for name in ("%s.data.pets" % _HOST_PKG, "%s.data.pets" % _HOST_PKG_FALLBACK):
        m = sys.modules.get(name)
        if m is not None:
            return m
    last = None
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        try:
            return importlib.import_module("%s.data.pets" % prefix)
        except Exception as exc:                # noqa: BLE001
            last = exc
    raise RuntimeError("pets：宿主模块 data.pets 取不到（%s）——拒绝静默空跑" % (last,))


def __getattr__(name: str):
    """同名读口：`content.pets.<名>` 直通宿主 `game/data/pets.py`（PEP 562，调用时解析）。"""
    return getattr(_pets(), name)


# 真源 re-export 的 11 个名字（供静态检查/文档；取值仍走 __getattr__ 直通宿主）
__all__ = [
    "PET_POOL", "PET_EGG_ROLL", "PET_MAX_LEVEL",
    "make_pet_egg", "pet_exp_need", "pet_exp_mult", "pet_skill_label",
    "pet_quality_label", "pet_line", "pet_exp_bonus", "pct_str",
    "bind_host",
]
