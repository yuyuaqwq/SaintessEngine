# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— portals 域实现（B13-L5，2026-09-14）。

真源 = 宿主 `game/core/portals.py`（原 6 行）**逐字搬**（函数体一字未改）。
原模块头那句 `数据层 - portals.py` 的归属标注随迁作注释保留。

为什么这个模块零宿主替身
------------------------
`portal_cost` 是**纯函数**：只读传进来的 `target_map` dict（`lv` 字段），不碰数据表 /
DB / 墙上时间 / 随机数 —— 真源本来就没有任何 import。所以包内不建读口、不注入句柄，
`content/data/portals.json`（方碑域，域归属 = 本线）由**消费方**读：`content/world_cmds.py`
与 `content/travel.py` 各自的 `PORTALS` 读口（本模块不用它）。

宿主侧：`game/core/portals.py` 现在只剩「加载包 + 模块别名」的薄壳，见那边头注。
"""


def portal_cost(target_map: dict) -> int:
    """传送费用：50 + 目标地图等级 * 5(低图便宜，高图贵，防滥用)"""
    return 50 + target_map.get("lv", 1) * 5
