# -*- coding: utf-8 -*-
"""battle2 引擎 support 子包（S3 通用件归位）。

迁入的通用件（原 game/core/，零游戏知识/参数化）：
- formula_expr.py  安全表达式解释器（纯数学）
- formation.py     站位/射程/AOE 目标选择纯函数
- skill_kinds.py   技能类型域枚举（kind 值由内容侧 config 注入语义）
- battle_bars.py   挂敌身条 / 蓄力三律纯函数（配置读点走 config 注入面）

旧路径（game/core/X.py）保留兼容 shim（plan §7-S3）；S9 收口时删。
"""
