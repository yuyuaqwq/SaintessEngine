# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— 符文数值/物品构造（B13-L1 端口，2026-09-14）。

真源：游戏仓 `game/core/runes.py`（52 行）**逐字端口**。宿主同名文件已改薄壳。

搬的边界 / 正文改动面：`from ..data import RUNES, RUNE_CONFLICTS, RUNE_LEVEL_ROMAN, QUALITY`
→ 宿主数据层惰性替身 `_D = _HostMod("data")`，引用改 `_D.<名>`（正文其余一字未改）。

缺口（**runes 域存在但本线不切**，理由留给收口方复核）
* `content/data/runes.json`（16 条）**迭代序 ≠ 宿主 `RUNES` 插入序**（域文件按键排序：JSON 是
  `rn_armor_pierce…` 字典序，宿主是 `rn_brutal, rn_armor_pierce, …`）——`rune_item` /
  `rune_value` 都是「首个 `effect` 命中即返回」，序变了行为可能变（本线实测 16 条 effect
  互异 → 当下结果同，但这是**巧合不是契约**）。
* `lvl` 键型：宿主是 int 键 `{1:…}`，JSON 是字符串键 `{"1":…}` —— 不还原 int 键，
  `r["lvl"].get(lvl)` 恒回 0（**符文数值静默归零**，B14 切点时的头号坑）。
* `RUNE_CONFLICTS` 在域里被拆成每条 `conflicts` 字段（形状可逆但需重建对表）。
⇒ 三条都属「切读点」活（B14 的 437 读点同批），本线**不猜**，留宿主句柄 + 登记。
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

_D = _HostMod("data")   # 宿主数据层（runes 域存在但迭代序/键型不等 → 不切，见头注缺口）


"""奥兰迪亚·余烬纪年数据层 - runes.py"""
def rune_value(effect: str, lvl: int):
    """符文效果数值：effect + 等级 → 数值(用于战斗结算)"""
    for name, r in _D.RUNES.items():
        if r["effect"] == effect:
            return r["lvl"].get(lvl, r["lvl"].get(1, 0))
    return 0

def rune_conflict(effect_a: str, effect_b: str) -> bool:
    """两个符文效果是否冲突(同件装备不能共存)"""
    if effect_a == effect_b:
        return False
    for (x, y) in _D.RUNE_CONFLICTS:
        if (effect_a == x and effect_b == y) or (effect_a == y and effect_b == x):
            return True
    return False

def rune_item(effect: str, lvl: int = 1) -> dict:
    """构造符文物品 data(掉落/奖励用)"""
    for name, r in _D.RUNES.items():
        if r["effect"] == effect:
            lv = min(3, max(1, lvl))
            roman = _D.RUNE_LEVEL_ROMAN[lv]
            desc = r["desc"]
            if "{" in desc:
                try:
                    if "v1" in desc:
                        v1, v2 = r["lvl"][lv]
                        desc = desc.format(v1=int(v1 * 100), v2=int(v2 * 100))
                    else:
                        v = r["lvl"][lv]
                        if isinstance(v, float) and v < 1:
                            v = int(v * 100)
                        desc = desc.format(v=v)
                except Exception:
                    pass
            return {
                "name": f"{_D.QUALITY[r['quality']]['name']}符文·{r.get('name', name)} {roman}",
                "type": "符文",
                "effect": effect,
                "lvl": lv,
                "quality": r["quality"],
                "price": r["cost"] // 2,
                "desc": desc,
            }
    return None

