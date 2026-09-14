# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— 符文数值/物品构造（B13-L1 端口，2026-09-14）。

真源：游戏仓 `game/core/runes.py`（52 行）**逐字端口**。宿主同名文件已改薄壳。

取件（★ B16-W11 收口 · 2026-09-14：四个名字全数归包，本模块零宿主数据句柄）
* `RUNES` / `RUNE_CONFLICTS` → 包内门面 `content/catalog_items.py`（`runes` 域）：
  `lvl` **int 键已还原**（不还原 = 数值恒 0）· 外层键序 = 真源插入序（B13 头注的「序 ≠ 域序」缺口已闭）·
  `RUNE_CONFLICTS` 由域条目对称 `conflicts` 字段按真源符文序重建（3 对，逐位相同）。
* `RUNE_LEVEL_ROMAN`（`game_config.runes`）· `QUALITY`（`equipment`）→ 包内门面 `content/catalog_b143.py`。
* 逐名 deep-equal（含键序 / int 键 / list 元素序）：门禁 `0 不等`（见报告 `_w11_gems_runes_affix.md`）。

正文一字未改：只换「取值来源」（原 `_D.<名>` → 同名门面名）；「首个 effect 命中即返回」的遍历序不变。
"""


# -*- coding: utf-8 -*-

# ---- 包内门面（B16-W11：四个名字全数归包）----
from .catalog_b143 import RUNE_LEVEL_ROMAN, QUALITY          # `game_config.runes` / `equipment`
from .catalog_items import RUNES, RUNE_CONFLICTS             # `runes` 域（int 键 / 插入序 / 冲突对）


"""奥兰迪亚·余烬纪年数据层 - runes.py"""
def rune_value(effect: str, lvl: int):
    """符文效果数值：effect + 等级 → 数值(用于战斗结算)"""
    for name, r in RUNES.items():
        if r["effect"] == effect:
            return r["lvl"].get(lvl, r["lvl"].get(1, 0))
    return 0

def rune_conflict(effect_a: str, effect_b: str) -> bool:
    """两个符文效果是否冲突(同件装备不能共存)"""
    if effect_a == effect_b:
        return False
    for (x, y) in RUNE_CONFLICTS:
        if (effect_a == x and effect_b == y) or (effect_a == y and effect_b == x):
            return True
    return False

def rune_item(effect: str, lvl: int = 1) -> dict:
    """构造符文物品 data(掉落/奖励用)"""
    for name, r in RUNES.items():
        if r["effect"] == effect:
            lv = min(3, max(1, lvl))
            roman = RUNE_LEVEL_ROMAN[lv]
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
                "name": f"{QUALITY[r['quality']]['name']}符文·{r.get('name', name)} {roman}",
                "type": "符文",
                "effect": effect,
                "lvl": lv,
                "quality": r["quality"],
                "price": r["cost"] // 2,
                "desc": desc,
            }
    return None

