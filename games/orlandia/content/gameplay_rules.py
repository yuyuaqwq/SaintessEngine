# -*- coding: utf-8 -*-
"""《奥兰迪亚》玩法规则（元素反应 / 机制叠层 / 升级结算 / 掉落名解析）—— 包内**单源**。

真源：宿主 `game/content_rules/gameplay.py`（158 行）**逐字搬**（B12B13-TAIL 线 1，2026-09-14）。
宿主那份现在只剩**薄壳**（`from content.gameplay_rules import *`，同名同签名）。

取件口对照（**唯一改动面**：原文 `from .. import content as C` 一个聚合层符号 + 两处函数内宿主 import）
------------------------------------------------------------------------------------------------
| 真源写法 | 包内替身 | 说明 |
|---|---|---|
| `C.exp_to_next` | `from .catalog_core import exp_to_next` | 升级经验曲线；`catalog_core` 是**惰性门面**（`content/stats.py` 模块级要解宿主句柄，不能提前 import） |
| `C.EVOLVE_LEVELS` | `from .constants import EVOLVE_LEVELS` | 转职门槛（`{1:30,2:60,3:90}`，int 键） |
| `C.CHAPTER_PACK` | `from .catalog_b143 import CHAPTER_PACK` | 章节礼包（`chapters` 域；宿主聚合层取的就是这一份） |
| `C.resolve` / `C.display` | `from .index import resolve, display` | 名字索引（= 宿主 `game/core/index.py` 转发的那份，同一函数对象） |
| `C.ITEMS` / `C.MATERIALS` | `from .catalog_items import ITEMS, MATERIALS` | 物品域（同 `content/achievements.py` 的既有读口） |
| `from content.mech.class_data import MECH_CFG` | 同左（原样） | 机制参数表（元素反应 / 叠层上限） |
| 函数内 `from .. import db as _db` | `_db = _host_module("db")`（同位置、调用时解析） | 写 `event_state` 是宿主存储（判据 3「接人性」） |
| 函数内 `from ..store.inventory import add_item` | `from .persistence.inventory import add_item`（同位置惰性） | B17 存档层已归包；宿主 `game/store/inventory.py` 是它的薄壳 ⇒ **同一函数对象** |
| `ELEMENT_MARKS = {...}` 字面量 | `from .mech.element_procs import ELEMENT_MARKS` | **单源归位**：真源这份与 `game/services/battle_element_procs.py` / 包内 `content/mech/element_procs.py:35` 三处同值；包内不造第二份字面量 |

行为等价证据：`overnight/W-B12B13-L1.md`（109 例快照 before/after 逐字节相同：面板链 + 技能链 +
升级结算整库 dump + 掉落解析 + 元素反应）。
"""
from __future__ import annotations

import importlib
import sys

from .catalog_b143 import CHAPTER_PACK
from .catalog_core import exp_to_next
from .catalog_items import ITEMS, MATERIALS
from .constants import EVOLVE_LEVELS
from .index import display, resolve
from .mech.class_data import MECH_CFG
from .mech.element_procs import ELEMENT_MARKS
from .panel import player_base_stats, player_final_stats
from .skills import _sk_table


# ============================================================
# 宿主替身口（惰性；真源「函数内 `from .. import db as _db`」的同义替身）
# ============================================================
_HOST_PKG = "data.plugins.dragonfall.game"      # 运行时（main.py 的模块路径）
_HOST_PKG_FALLBACK = "game"                     # 测试/工具按 `game.xxx` 直接 import 时
_INJECTED = {}


def bind_host(**objs):
    """宿主薄壳 import 期注入（幂等）——键 = 模块名（`db`）。"""
    for k, v in (objs or {}).items():
        if v is not None:
            _INJECTED[k] = v


def _host_module(name: str):
    """取宿主子模块（真源 `from .. import <name>` 那一类）。取不到 → 抛，不静默空跑。"""
    if name in _INJECTED:
        return _INJECTED[name]
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        full = prefix if not name else "%s.%s" % (prefix, name)
        m = sys.modules.get(full)
        if m is not None:
            return m
    last = None
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        try:
            return importlib.import_module(prefix if not name else "%s.%s" % (prefix, name))
        except Exception as exc:                # noqa: BLE001
            last = exc
    raise RuntimeError("%s：宿主模块 %s 取不到（%s）——拒绝静默空跑" % (__name__, name, last))


# ============================================================
# 元素系统
# ============================================================
# 元素亲和可切换的系（法师）
ELEMENT_OPTIONS = ["fire", "ice", "thunder"]
ELEMENT_CN = {"fire": "火", "ice": "冰", "thunder": "雷"}
# 元素印记 key（存敌方 actor buffs，层数）—— 单源 = `content/mech/element_procs.py`（见模块头注）

# ============================================================
# v2.0 元素反应（12 章 3.1，严格按策划案表）——定义见 data/battle_config.py
# 当前系 × 目标印记 → 反应：蒸发 / 超载 / 冻结（预留，法师暂无水系技能）/ 感电
# ============================================================
# （ELEMENT_REACTIONS 表本体 v125.2 B1 已下沉 data/battle_config.py，顶部 import 保持对外接口）


def element_reaction(cur_element: str, target_marks: dict) -> dict | None:
    """判定元素反应。
    cur_element: 当前系 fire/ice/thunder
    target_marks: 敌方印记 dict（key 见 ELEMENT_MARKS，值为层数）
    返回反应 dict 或 None：{"name", "mult", "clear", "extra"}
    """
    for mark_key, layers in target_marks.items():
        if layers and layers > 0:
            r = MECH_CFG["element"]["reactions"].get((cur_element, mark_key))
            if r:
                return r
    return None


def element_mark_apply(target_marks: dict, element: str, layers: int = 1, max_layers: int = 5) -> dict:
    """给目标挂元素印记(带上限)。返回更新后的印记 dict。"""
    mark_key = ELEMENT_MARKS.get(element, "")
    if not mark_key:
        return target_marks
    target_marks[mark_key] = min(max_layers, target_marks.get(mark_key, 0) + layers)
    return target_marks


# v181.M-R2b：core_resource_def / core_resource_def_by_key 已退役删除（旧 core_resources.py
# 按 class/key 查资源定义——文件本体已随 v181.M-R2c 退役删除；现资源名/cap 单源 = EFFECT_RULES（game/data/battle_rules.py），
# 展示名查 EFFECT_RULES[key].name、上限查 cap——脱战校验/技能表/药水调用点已全部改读新源）。


def mech_stack_gain(mech: str, p_mech: dict, mval: int) -> int:
    """叠层(带上限)。返回新层数。未配上限的机制不限制。"""
    cap = MECH_CFG["mech_stack"]["max"].get(mech, 99)
    return min(cap, p_mech.get(mech, 0) + mval)


# ============================================================
# 升级 / 掉落
# ============================================================

def check_player_level_up(group_id, qq_id, player: dict) -> tuple[list, dict]:
    """检查是否升级(处理多次连升)。返回 (log列表, 更新后的player)"""
    logs = []
    # v95.12 #143：消费读档惰性升级暂存的提示（get_player 已静默升级写回，这里补回提示）
    if player.get("_lv_logs"):
        logs = player.pop("_lv_logs")
    # v110 审计修复：100 级硬顶（07 章"以 100 为终极等级"，成就"达到100级"为里程碑）——
    # 原实现可无限升级为空成长；达 100 级后经验不再消费
    while player["level"] < 100 and player["exp"] >= exp_to_next(player["level"]):
        player["exp"] -= exp_to_next(player["level"])
        player["level"] += 1
        tier = player.get("class_tier", 0)
        prev_base = player_base_stats(player["class_name"], player["level"] - 1, tier)
        # v101.28l #419：升级横幅差值必须同口径裸装对比（此前新级最终属性−旧级裸装，
        # 装备/属性点/称号加成全被算进"升级成长"→ playtest 实锤虚高 50 倍/40 倍）
        new_base = player_base_stats(player["class_name"], player["level"], tier)
        # v94 #41：升级重算必须传全 7 参数（race/evolve_path/title_bonus 漏传 → 写入值与面板/战斗重算不一致）
        st = player_final_stats(player["class_name"], player["level"], player.get("equipment", {}), tier, player.get("attributes"), player.get("evolve_path", 0), player.get("_title_bonus", {}) or {}, player.get("race"))
        player["attr_pts"] = player.get("attr_pts", 0) + 3  # 每级 +3 自由属性点
        player["skill_points"] = player.get("skill_points", 0) + 1  # 每级 +1 技能点
        player["max_hp"] = st["max_hp"]
        player["max_mp"] = st["max_mp"]
        player["hp"] = st["max_hp"]
        player["mp"] = st["max_mp"]
        # v12：等级只解锁"可学习资格"，不再自动学会（要花技能点学）
        # v95 #136：available 是 sk_xxx ID，learned_now 是中文名（v46 内存层转名），
        # 必须取 info["name"] 比较，否则已学技能也计入"可学"（s not in learned_now 恒 True）
        available = [info.get("name", s) for s, info in _sk_table(player["class_name"]).items()
                     if info["lv"] <= player["level"]]
        learned_now = set(player.get("learned_skills", []))
        can_learn = [s for s in available if s not in learned_now]
        logs.append(
            f"🎉 恭喜升级！现在 {player['level']} 级！"
            f"(生命上限 +{new_base['hp'] - prev_base['hp']}, 攻击 +{new_base['atk'] - prev_base['atk']})"
            f"\n📌 属性点 +3、技能点 +1(『属性』加点 / 『技能学习 <名称>』学技能)"
        )
        if can_learn:
            # v101.30d #O54：提示语修正——可学的含 5 技能点被动（风行步/狩猎咆哮等），
            # 不再叫"新技能"误导（playtest 小蓝：提示与"新技能"概念出入）
            logs.append(f"📖 有 {len(can_learn)} 个技能可学习（含被动）！『技能学习 <技能名>』消耗技能点学会(『技能列表』查看)")
        if player["level"] == EVOLVE_LEVELS[1]:
            logs.append(f"🌟 你已达到 {player['level']} 级，可以转职了！(输入『转职』查看)")
        # v140 波3.3：章节礼包——每 10 级里程碑发放一次（event_state 防重复）
        if player["level"] % 10 == 0:
            try:
                from ._pkgref import DB as _db
                _ck = f"chapter_pack_{player['level']}_{qq_id}"
                if not _db.get_event_state(_ck):
                    _packs = {p["lv"]: p for p in CHAPTER_PACK}
                    _pack = _packs.get(player["level"])
                    if _pack:
                        from .persistence.inventory import add_item as _add_item
                        _got = []
                        for _iname in _pack.get("items", []):
                            _iid = resolve("items", _iname)
                            if _iid in ITEMS:
                                _add_item(group_id, qq_id, _iid, ITEMS[_iid])
                                _got.append(_iname)
                            else:
                                _imid = resolve("materials", _iname)
                                if _imid in MATERIALS:
                                    _add_item(group_id, qq_id, _imid, {"name": display("materials", _imid), "type": MATERIALS[_imid].get("type", "材料"), "stackable": True, "price": MATERIALS[_imid]["price"]})
                                    _got.append(_iname)
                        if _got:
                            _db.set_event_state(_ck, "1")
                            logs.append(f"🎁 章节里程碑达成！获得【{_pack.get('name', '礼包')}】：{'、'.join(_got)}！")
            except Exception:
                pass
    return logs, player


def resolve_drop(name: str):
    """v110 审计修复：掉落名解析——材料优先，其次 ITEMS（消耗品/副本钥匙 i_key_* 等）。

    战斗/副本掉落结算原先只认 MATERIALS，钥匙类消耗品（29 章入场钥匙）结构上发不出
    （D11 P0-2：设计 29:505「遗骸搜出龙宫宝珠」在当前架构不可实现）。返回 item ID。
    """
    mid = resolve("materials", name)
    if mid in MATERIALS:
        return mid
    for _k, _v in ITEMS.items():
        if _v.get("name") == name:
            return _k
    return None


__all__ = [
    "ELEMENT_OPTIONS", "ELEMENT_CN", "ELEMENT_MARKS",
    "element_reaction", "element_mark_apply", "mech_stack_gain",
    "check_player_level_up", "resolve_drop",
]
