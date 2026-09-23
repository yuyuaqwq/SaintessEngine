# -*- coding: utf-8 -*-
"""槽位挂载 —— 「固定几条 + 随机补足 + 不可重复」这一种挂载形状。

**形状在哪**：装备挂词条 / 怪物挂技能 / 宝箱挂赠品 —— 都是同一件事：
先放**指定**的几条（主题锚点、必给项），再从**池子**里补到目标条数，补的时候不重复。
把「词条」「技能」这些取值拿掉，逻辑照旧成立。

**用法**::

    draw_slots(pool_ids, 3, fixed=("series_mark",), rng=rng)
    # → ["series_mark", <随机>, <随机>]（池子不够就给尽，不抛错、不补 None）
"""
from __future__ import annotations

import random as _random

from .pick import pick_many


def draw_slots(pool, count: int, *, fixed=(), no_dup: bool = True, weighted: bool = False,
               where=None, weight_key: str = "w", rng=None) -> list:
    """先按顺序放 `fixed`，再从 `pool` 抽到 `count` 条（**不足给尽**）。

    * `count <= 0` → 返回 `fixed`（不抽）
    * `no_dup=True` → `fixed` 内部去重，且随机抽取时跳过已在结果里的项
    * `weighted=True` → 随机部分带权（否则等概率）
    * 返回顺序 = 固定项在前、随机项按抽出顺序在后（**与参考实现的「固定 + 随机补足」一致**）
    """
    r = rng or _random
    out = []
    for f in (fixed or ()):
        if no_dup and f in out:
            continue
        out.append(f)
    need = int(count or 0) - len(out)
    if need <= 0:
        return out
    cand = [e for e in (pool or ()) if (where is None or where(e))]
    if no_dup:
        cand = [e for e in cand if e not in out]
    if not cand:
        return out
    out.extend(pick_many(cand, need, weighted=weighted, replace=not no_dup,
                         weight_key=weight_key, rng=r))
    return out
