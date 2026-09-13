# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— crafting 服务域实现（B12 线 L5，2026-09-14）。

真源：游戏仓 `game/services/crafting.py`（86 行，v181 P4-4 CraftingService 装备养成域）。
本模块 = 那个模块的**逐字端口**（正文从 `# 强化石 key 收敛` 起一字未改）；宿主
`game/services/crafting.py` 现在只剩：加载包 + 一行转发 re-export（**零宿主面注入**）。

消费者（零改动）：`game/services/__init__.py:33`（5 个名字）·
`game/commands/economy.py:28`（`from ..services import crafting as _craft_svc` → 绑进
`content/economy_host.py` 的 `_craft_svc` 键，供包内 `content/economy_cmds.py` 的
enhance 命令调用）· `tests/test_services_crafting.py`。

正文改动面（**只有两类**，可复算见 `overnight/w1213_b12l5_gen.py`）
------------------------------------------------------------------
1. 模块级 `from .. import content as C`（1 行）→ 不 import 宿主。
2. 唯一的数据读点 `C.ENHANCE_FAIL_DROP`（真源 `game/data/enhance.py:24`）→ **切包内常量域读口**
   （I1）：`content/rules/game_config.json` 的 `enhance` 组，走 `content/config.py`（B9-L7 立的
   常量域唯一读口）并**还原 int 键**（不还原 → `.get(5)` 恒 `None` → 静默不掉级）。
   正文里只有那一行的取值口变了：`drop = C.ENHANCE_FAIL_DROP.get(cur_enh, 0)`
   → `drop = _FAIL_DROP.get(cur_enh, 0)`；**其余一字未改**（含注释与文案字面量）。

等值证据：`overnight/w1213_b12l5_check.py`【⑤】逐键对拍（真源 `{5: 1, 6: 1}` ↔ 读口还原后）
+ `overnight/w1213_b12l5_snap.py` 的 K04（全等级档 × 有无保护石，改前改后逐字节相同）。

本模块**零宿主面**（无 `bind_host`）—— 数据只经包内域读口进出。
"""
from __future__ import annotations

from .config import const as _cfg_const, int_keys as _cfg_int_keys


# 数据读口（I1）：真源 `C.ENHANCE_FAIL_DROP`（宿主 `game/data/enhance.py:24`，1 个读点）
# → 包内常量域读口 `<包>/content/rules/game_config.json` 的 `enhance` 组（域归属 L7）。
# `int_keys` 必须还原：JSON 键是字符串，`.get(5)` 会恒 None → 静默不掉级。
_FAIL_DROP = _cfg_int_keys(_cfg_const("enhance", "ENHANCE_FAIL_DROP"))


# ============ 强化石 key 收敛（原 economy.py enhance 散点字面量单点化） ============

# v101.30 炼金强化材料接入（economy.py enhance 原内联字面量，逐字符等价收敛）：
#   "i_stone_refine"   精炼强化石 = 成功率 +25%（自动消耗）
#   "i_stone_blessed"  祝福符石   = 成功率 +15%（自动消耗，与精炼石叠加，上限 100%）
#   "i_stone_upgrade"  强化石     = 失败保护（失败不掉级，消耗 1 个）
ENHANCE_STONE_REFINE = "i_stone_refine"
ENHANCE_STONE_BLESSED = "i_stone_blessed"
ENHANCE_STONE_PROTECT = "i_stone_upgrade"


def compute_enhance_rate(base_rate, prof_lv, *, boost=False,
                         has_refine=False, has_blessed=False):
    """强化成功率纯规则（v113.3 副业渐进加成 + v101.30/v105/v113.3 强化石叠加）。

    原 economy.enhance L3085-3105 内联段逐行 copy（行为零变化）：
      - 副业加成：强化师每级 +0.5%（Lv.10 = +5%，原仅 Lv.10 一档）
      - 精炼强化石：成功率 +25%（星铁必成(_boost)或成功率已 100% 时不再消耗）
      - 祝福符石：成功率 +15%（自动消耗，与精炼石叠加，上限 100%）
    返回 dict：
      rate        最终成功率（0~1）
      craft_line  手艺加成行文案（无加成 = ""；原 _craft_line，升级当次重算用）
      stones_used 实际消耗的石料 key 列表（按原判定顺序：refine → blessed），
                  命令层逐项 remove 等价于原内联扣料
      boost       星铁必成标记（原样透传，成功判定用）
    """
    rate = base_rate
    _rate_bonus = min(prof_lv, 10) * 0.005
    # O108 修复：手艺加成行单独存（_craft_line），升级当次用新等级重算后再拼回
    _craft_line = ""
    if _rate_bonus > 0:
        rate = min(1.0, rate + _rate_bonus)
        _craft_line = f"\n🛠️ 强化师 Lv.{prof_lv} 的手艺：成功率 +{_rate_bonus*100:.1f}%！"
    # v105 M11 P2：星铁必成(_boost)或成功率已 100% 时不再消耗精炼强化石（+25% 纯浪费）
    stones_used = []
    if not boost and rate < 1.0 and has_refine:
        rate = min(1.0, rate + 0.25)
        stones_used.append(ENHANCE_STONE_REFINE)
    # v113.3 祝福符石：成功率 +15%（自动消耗，与精炼石叠加，上限 100%）
    if not boost and rate < 1.0 and has_blessed:
        rate = min(1.0, rate + 0.15)
        stones_used.append(ENHANCE_STONE_BLESSED)
    return {"rate": rate, "craft_line": _craft_line, "stones_used": stones_used,
            "boost": boost}


def enhance_fail_floor(cur_enh, *, has_protect=False):
    """强化失败结算纯规则（原 economy.enhance 失败分支 L3144-3145 逐行 copy）。

    - v104 M11：+1~+4 失败不掉级（策划 19 章"纯亏金币"），+5 起才掉级
    - v113.3：+5/+6 失败掉 1 级；+7/+8 失败不掉级（大师工艺保底）
      保级/降级 = ENHANCE_FAIL_DROP 表查当前等级；保护石存在且会掉级时 → 保住等级。
    返回 (new_enh, protect_used)：
      new_enh      结算后强化等级（失败但保护/不掉级 = cur_enh）
      protect_used 是否消耗保护石（True → 命令层 remove 1 个 i_stone_upgrade）
    """
    drop = _FAIL_DROP.get(cur_enh, 0)
    new_enh = max(0, cur_enh - drop)
    if has_protect and new_enh != cur_enh:
        return cur_enh, True
    return new_enh, False
