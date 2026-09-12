# -*- coding: utf-8 -*-
"""随机产出原语 —— 加权抽取（最小形状）。

**为什么单独一层**：全项目「按权重摸一个」的写法散在掉落池 / 采集 / 商店货架 / 签到 /
事件模板里，各自 `random.choices(weights=…)` 或手写累加 —— 差别只在数据和过滤条件，
逻辑一模一样。抽出来之后，「摸一个」只有一份实现，且**随机源可注入**（可复现、可逐格比对）。

**语义（逐字对齐参考实现的手写累加版，勿"优化"成 `random.choices`）**：

```
权重和 ≤ 0 或空表 → None
否则 roll = rng.random() × 权重和；按声明序累加，首个 acc > roll 者中选；
浮点误差导致谁都没中 → 兜底返回**最后一个**（不是第一个）
```

改成 `random.choices` 会改随机流（消费的随机数个数不同）→ 同一个种子抽出不同结果，
迁移期的「逐格一致」比对会当场红。这是**故意的**保守。
"""
from __future__ import annotations

import random as _random


def _weight_of(entry, weight_key, default_weight) -> int:
    """条目权重（缺失 → default_weight；None/非法 → 0）——与参考实现的 `int(e.get(w,1) or 0)` 等价。"""
    try:
        return int(entry.get(weight_key, default_weight) or 0)
    except (TypeError, ValueError, AttributeError):
        return 0


def weigh(entries, *, weight_key: str = "w", default_weight: int = 1) -> list:
    """按声明序给出权重列表（供审计/展开用，不做抽取）。"""
    return [_weight_of(e, weight_key, default_weight) for e in (entries or ())]


def total_weight(entries, *, weight_key: str = "w", default_weight: int = 1) -> int:
    return sum(weigh(entries, weight_key=weight_key, default_weight=default_weight))


def pick_weighted(entries, *, weight_key: str = "w", default_weight: int = 1, rng=None):
    """按权重抽一个条目；空表/权重和 ≤ 0 → None。返回的是**原条目对象**（不是副本）。"""
    if not entries:
        return None
    r = rng or _random
    weights = weigh(entries, weight_key=weight_key, default_weight=default_weight)
    total = sum(weights)
    if total <= 0:
        return None
    roll = r.random() * total
    acc = 0.0
    for entry, w in zip(entries, weights):
        acc += w
        if roll < acc:
            return entry
    return entries[-1]


def pick_index(entries, *, weight_key: str = "w", default_weight: int = 1, rng=None):
    """同 `pick_weighted`，但返回下标（带权不放回抽样时按**下标**删，避免 dict 判等删错元素）。"""
    if not entries:
        return None
    r = rng or _random
    weights = weigh(entries, weight_key=weight_key, default_weight=default_weight)
    total = sum(weights)
    if total <= 0:
        return None
    roll = r.random() * total
    acc = 0.0
    for i, w in enumerate(weights):
        acc += w
        if roll < acc:
            return i
    return len(entries) - 1


def pick_many(entries, n: int, *, weighted: bool = False, replace: bool = False,
              where=None, weight_key: str = "w", default_weight: int = 1, rng=None) -> list:
    """抽 n 个。

    * `weighted=False`（等概率）+ `replace=False` → 直接委托 `rng.sample`
      （与参考实现的 `random.sample` **同一个调用**，随机流一致）
    * `weighted=True` + `replace=False` → 逐个带权抽、抽走即从候选里删（带权不放回）
    * `replace=True` → 每次独立抽（带权走累加法，等概率走 `rng.choice`）
    * `where` → 先过滤候选（不改动原列表）

    实际给不满（候选不够）时给尽，不抛错、不补 None。
    """
    r = rng or _random
    cand = [e for e in (entries or ()) if (where is None or where(e))]
    if n is None or n <= 0 or not cand:
        return []
    if not replace:
        if not weighted:
            return list(r.sample(cand, min(n, len(cand))))
        pool = list(cand)
        out = []
        for _ in range(min(n, len(pool))):
            i = pick_index(pool, weight_key=weight_key, default_weight=default_weight, rng=r)
            if i is None:
                break
            out.append(pool.pop(i))
        return out
    out = []
    for _ in range(n):
        if weighted:
            e = pick_weighted(cand, weight_key=weight_key, default_weight=default_weight, rng=r)
        else:
            e = r.choice(cand) if cand else None
        if e is None:
            break
        out.append(e)
    return out


def roll_range(spec, *, rng=None, default=1) -> int:
    """数量/区间展开：`int` → 本身；`[a, b]`(≥2 元素) → 闭区间随机；其它 → default。

    参考实现里 `n` 的两种形态（副本 Boss 的 `n: [1,2]` 与固定 `n: 3`）就在这里收口。
    """
    r = rng or _random
    if isinstance(spec, bool):
        return int(spec)
    if isinstance(spec, (list, tuple)):
        if len(spec) >= 2:
            return r.randint(int(spec[0]), int(spec[1]))
        if len(spec) == 1:
            return int(spec[0])
        return int(default or 1)
    if isinstance(spec, int):
        return spec
    if spec is None:
        return int(default or 1)
    try:
        return int(spec)
    except (TypeError, ValueError):
        return int(default or 1)
