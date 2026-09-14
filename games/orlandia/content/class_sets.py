# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— 名册套装装配器（B13-L1 端口，2026-09-14）。

真源：游戏仓 `game/core/class_sets.py`（61 行）**逐字端口**。宿主同名文件已改薄壳。

取件（★ B16-W11 收口 · 2026-09-14：`SERIES_SETS` / `SERIES_SET_BONUS` 归包）
1. `from .index import pinyin_id` → **包内直取**（`content/index.py` = B13-L7 线已落地的
   逐字端口，`pinyin_id` 纯计算）。
2. `SERIES_SETS` → 包内门面 `content/catalog_rules.py`（真源 `game/data/equip_roster.py:510`，
   deep-equal）。`SERIES_SET_BONUS`（v181-P2A 下沉的数值表，真源 `game/data/set_bonus_data.py:35`）
   → 同门面（包内**无域** ⇒ 值随代码 dump，已登记 `NOT_YET_DOMAINED`），仍走
   `_series_set_bonus()` **惰性取件**（EAGER 环纪律见下）。
3. ★ **`SETS` 必须仍是宿主同一只字典**（唯一保留的宿主数据句柄 `_D.SETS`）：
   `_build_class_sets` 是**写入型装配器**（`SETS[set_id] = entry`），宿主 `game/data/_assembly.py:91`
   调它、宿主面板（`game/content_rules/panel.py`）读 `C.SETS` —— 若改成包内
   `content/data/sets.json` 的副本，套装的 2/4/5 件加成就对宿主侧**静默消失**。
   （登记给收口方：B15「包内装配器写包内 SETS + 宿主读包」的系统活，非本线。）

缺口：`sets` 域是**导出后的镜像**（92 条含名册套装），与「装配器写宿主 SETS」是两条路 ——
本线保宿主真源（写入语义所系）。
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
"""奥兰迪亚·余烬纪年核心层 - class_sets.py（阶段八重写，2026-08-06）

10 章五节名册套装注册：9 系列 5 件套（头盔/胸甲/护腿/鞋子/项链）。
- bonus_2：2 件属性百分比（引擎 set_bonus_2 消费）
- bonus_4_stats：4 件属性百分比（engine.set_bonus_2 叠加，>=4 件生效）
- bonus_4.effect：4 件特效（战斗触发型，保留旧结构兼容）
- bonus_5：5 件效果（v104 起战斗落地：battle 对敌增伤/元素增伤、battle_mech 抗寒）
- 治疗加成（圣光套 2 件）由 battle 治疗段消费（bonus_2.heal 字段）

⚠️ 旧世界毕业套（CLASS_SET_THEMES 6 职业×5 阶段）已废弃：不再动态合并进 CRAFT_RECIPES，
锻造配方 = 10 章名册（craft.py）。旧 SETS 42 条仍残留在 data/sets.py（兼容旧档 set 字段，
待确认后清理）；名册套装由 _assembly 调 _build_class_sets 注册/覆盖同名 key，不删除旧数据。

v181-P2A：套装数值表 _SERIES_SET_BONUS 已原值下沉 game/data/set_bonus_data.py
（SERIES_SET_BONUS，纯搬移零逻辑）——本模块保留装配器 _build_class_sets（注册进
SETS 的装配行为是逻辑，留在 core），经别名 _SERIES_SET_BONUS 消费数据表。
"""

from .index import pinyin_id                 # B13-L7 线已落地的包内逐字端口

from .catalog_rules import SERIES_SETS      # 包内门面（B16-W11：真源 equip_roster.py:510）

_D = _HostMod("data")   # ★ 只服务 `SETS` 写入：必须**宿主同一只字典**（写入型装配器，见头注）


def _series_set_bonus():
    """真源 `_SERIES_SET_BONUS`（v181-P2A 下沉的 `data/set_bonus_data.SERIES_SET_BONUS`）。

    **惰性**取件：`game.data → _assembly → core.class_sets` EAGER 环里 import 期取会撞
    半初始化的 `game.data`。
    """
    from .catalog_rules import SERIES_SET_BONUS     # 包内门面（B16-W11：dump 字面量）
    return SERIES_SET_BONUS


def _build_class_sets():
    """注册 10 章名册套装到 SETS(幂等：key 唯一，重复运行覆盖同名)。"""
    for series, set_name in SERIES_SETS.items():
        b = _series_set_bonus()[series]
        set_id = f"set_{pinyin_id(set_name)}"
        entry = {
            "quality": b["quality"],
            "icon": b["icon"],
            "bonus_2": dict(b["bonus_2"]),
            "name": set_name,
        }
        # v136 Phase6：职业套装归属（本职业 100% / 非本职业 60% 职业折扣）
        if b.get("class"):
            entry["class"] = b["class"]
        # v181-A1：圣光套任意件数持有加成（piece_heal_power）随套装注册（battle 治疗段泛读）
        if b.get("piece_heal_power") is not None:
            entry["piece_heal_power"] = b["piece_heal_power"]
        if b.get("bonus_4_stats"):
            entry["bonus_4_stats"] = dict(b["bonus_4_stats"])
        if b.get("bonus_4"):
            entry["bonus_4"] = dict(b["bonus_4"])
        if b.get("bonus_3"):
            entry["bonus_3"] = dict(b["bonus_3"])
        if b.get("bonus_3_stats"):
            entry["bonus_3_stats"] = dict(b["bonus_3_stats"])
        if b.get("bonus_5"):
            entry["bonus_5"] = dict(b["bonus_5"])
        if b.get("bonus_5_ctrl_immune"):
            # v180-B ②：5 件套控制免疫（霜狼抗寒等）随套装注册数据化
            entry["bonus_5_ctrl_immune"] = list(b["bonus_5_ctrl_immune"])
        if b.get("bonus_5_cond"):
            # v126 数值下沉：5 件战斗条件（enemy_contains/player_hp_below/dmg_mult/tag）随套装注册
            entry["bonus_5_cond"] = dict(b["bonus_5_cond"])
        _D.SETS[set_id] = entry      # 写入宿主 `C.SETS` 同一只字典
