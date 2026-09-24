# -*- coding: utf-8 -*-
"""逐条求值形状 —— `ext_achieve.earn` 的门面。

* `shape.bind`         注入读口（`EvalCtx._db()` 的返回物）；未装配就取用 ⇒ 当场报错
* `shape.EvalCtx`      判定上下文外壳（字段 + 钩子表 + 注入读口）
* `shape.ParamCond`    参数化条件：`<前缀><类别><数字>` ⇒ 「类别等级 ≥ 数字」
* `shape.earned_flags` 逐条求值器：注册表命中 → 判定函数 / 参数化兜底 / 都不中 → `False`

数据包要用它：

    from ext_achieve.earn import EvalCtx, ParamCond, bind, earned_flags
    bind(db=<读口>)
    ctx = EvalCtx(gid, qid, player, stats, rep, quests, hooks={...})
    flags = earned_flags(TABLE, ctx, CONDITIONS, fallback=<ParamCond 实例>)

本包**零游戏专名**（id 形态 / 类别名 / 条目表 / 判定函数一律调用方给）、**不 import 任何数据包**。
"""
from .shape import EvalCtx, ParamCond, bind, earned_flags
from . import shape

__all__ = [
    "shape",
    "EvalCtx", "ParamCond", "bind", "earned_flags",
]
