# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— 附魔数值（B13-L1 端口，2026-09-14）。

真源：游戏仓 `game/core/enchant.py`（46 行）**逐字端口**。宿主同名文件已改薄壳。

搬的边界 / 正文改动面（三类取件）
1. `from .affix import _affix_base_value` → **本线包内直取**（`content/affix.py`）。
2. `from .constants import PCT_STATS` → **包内读口** `from .tables import PCT_STATS`
   （`content/rules/panel_rules.json` → `content/tables.py`；与宿主 `core/constants.PCT_STATS`
   逐值逐序对拍相等）。
3. `from .stats import equip_stats` → 宿主句柄 `_host_attr("core.stats", "equip_stats")`；
   `from ..data import ENCHANT_MAX_VALUE / ENCHANT_RECIPES` → 宿主数据层替身
   `_D = _HostMod("data")` 取 `_D.ENCHANT_*`。

缺口：`enchant` 域不存在（66 域里没有）→ 配方/上限表走宿主句柄；`core/stats.py` 归 B13-L6。
"""

import importlib
import sys

# ============================================================
# 宿主替身口（`content/index.py` / `content/world_cmds.py` 同款：注入优先 → sys.modules →
# importlib；**绝不静默空跑**）
# ============================================================
_HOST_PKG = "data.plugins.dragonfall.game"      # 运行时（main.py 的模块路径）
_HOST_PKG_FALLBACK = "game"                     # 测试/工具按 `game.xxx` 直接 import 时
_INJECTED = {}


def bind_host(**objs):
    """宿主薄壳 import 期注入（幂等）——键 = 宿主模块名（`data` / `content` / `db`）。"""
    for k, v in (objs or {}).items():
        if v is not None:
            _INJECTED[k] = v


def _host_module(name: str):
    """取宿主子模块（`name` 为空 = 宿主 `game` 包本身）。"""
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
    raise RuntimeError("%s：宿主模块 %s 取不到（%s）——拒绝静默空跑" % (__name__, name, last))


def _host_attr(mod: str, attr: str):
    """宿主模块属性 —— 真源「函数内 `from ..<mod> import <attr>`」的同义替身（调用时解析）。"""
    m = _host_module(mod)
    try:
        return getattr(m, attr)
    except AttributeError:
        for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
            try:
                return importlib.import_module("%s.%s" % (
                    prefix if not mod else "%s.%s" % (prefix, mod), attr))
            except Exception:                   # noqa: BLE001
                continue
        raise


class _HostMod:
    """宿主模块替身（`C` / `db` / `_D`）——`C.xxx` / `db.xxx` / `_D.xxx` 属性访问时解析。"""

    def __init__(self, name):
        self._name = name

    def __getattr__(self, attr):
        return getattr(_host_module(self._name), attr)

# -*- coding: utf-8 -*-

from .affix import _affix_base_value          # B13-L1：本线包内直取
from .tables import PCT_STATS                  # 包内读口（与宿主 constants.PCT_STATS 逐值相等）

_D = _HostMod("data")                          # 宿主数据层（enchant 域不存在 → 报告缺口）


"""奥兰迪亚·余烬纪年数据层 - enchant.py"""
def enchant_value(slot: str, lv: int, stat: str, big: bool = False) -> int | float:
    """附魔数值：白板基础 * ratio；大成功 1.5x；crit/dodge 固定小值"""
    equip_stats = _host_attr("core.stats", "equip_stats")   # B13-L6 线在搬；落地后切包内直取
    rec = _D.ENCHANT_RECIPES.get(stat)
    if not rec:
        return 0
    if stat in PCT_STATS:
        v = rec["ratio"]
    else:
        base = equip_stats(slot, lv, "white").get(stat, 0)
        if base <= 0:
            base = _affix_base_value(slot, lv, stat)
        v = max(1, int(base * rec["ratio"]))
    if big:
        v = v * 1.5
        if stat in PCT_STATS:
            v = round(v, 3)
    if stat in _D.ENCHANT_MAX_VALUE:
        v = min(v, _D.ENCHANT_MAX_VALUE[stat])
    return v

def enchant_match_material(stat: str, items: list) -> str | None:
    """从背包物品里找第一个匹配该附魔系的材料名(无则 None)"""
    rec = _D.ENCHANT_RECIPES.get(stat)
    if not rec:
        return None
    for it in items:
        d = it.get("data", {})
        # F2-3：材料判定放宽——gm/部分发放路径材料入包缺 type 字段（或 type=兽材，
        #   如余烬甲片），原按 type==\"材料\" 过滤导致背包有材料却报\"没有材料\"（report_11 P1-1）。
        #   改按材料 key 规范 mat_ 前缀兜底（全库材料 key 均 mat_ 开头，v48 ID 规范）。
        if d.get("type") != "材料" and not str(it.get("key", "")).startswith("mat_"):
            continue
        name = d.get("name", "")
        if any(kw in name for kw in rec["mats"]):
            return name
    return None

