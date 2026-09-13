# -*- coding: utf-8 -*-
# ==============================================================================
# 包内实现（唯一真源）· B13-L2（2026-09-14）—— 逐字搬自宿主
#   `qqbot/data/plugins/dragonfall/game/core/encounter.py`
# 搬运改动面**只有「宿主取件」**一类：无（零宿主取件，逐字原样搬入）
# 宿主同名文件 = 薄壳（指向本模块，见那边的头注）。
# ==============================================================================
"""奥兰迪亚·余烬纪年 核心层 - encounter.py（v141 审计：副本遇怪概率配置化）

副本/地图遇怪概率统一入口：读数据表 dungeon.discovery_agro 配置（数据表驱动）。

与野外等级差模型（world._travel_ambush）互为设计差异——副本开本已校验等级，
固定高遇怪是设计意图，勿合并概率模型（详见 docstring）。
"""
from __future__ import annotations

from typing import Optional


def encounter_chance(map_dict: Optional[dict] = None, default: float = 0.85) -> float:
    """副本/地图遇怪概率：读 dungeon.discovery_agro 配置（数据表驱动）。

    数据表 22 个副本 maps 已显式配置 discovery_agro: 0.85（保留），
    命令层双份硬编码默认值统一收口到本函数——改配置即改遇怪，不单独写代码。

    与野外等级差模型（world._travel_ambush）互为设计差异：副本开本已校验等级，
    固定高遇怪是设计意图，勿合并概率模型。

    无配置 / 非法值（非数字字符串等）回退默认 default（0.85）。
    """
    _dun = (map_dict or {}).get("dungeon") or {}
    try:
        return float(_dun.get("discovery_agro", default))
    except (TypeError, ValueError):
        return default
