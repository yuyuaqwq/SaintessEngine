# -*- coding: utf-8 -*-
"""档位阶梯 —— 有序档位（品质/稀有度那一类）+ 按等级插值的权重表 + 抽档 / 升档 / 条数。

**形状在哪**：把「普通/精良/稀有」这些**取值**拿掉，剩下的是一件通用东西 ——
一串**有序档位**，每档挂一份自定义信息（倍率、显示名、颜色…由内容给），
可以「按权重抽一档」「往上升 N 档」「看它排第几」，以及「按等级查一张权重表并插值」。

**用法**::

    T = TierTable(["t1", "t2", "t3", "t4", "t5"],          # 档位取值由内容侧给，引擎不认含义
                  info={"t1": {"mult": 1.0, "name": "首档"}, ...},
                  weights_by_level={1: [70, 20, 8, 2, 0], 3: [...], 9: [...]},
                  aliases={"t1": "低", "t5": "高"})
    T.weights_at(4)                                  # 等级 → 权重行（相邻两档线性插值）
    T.pick(level=4, exclude=("t5",), rng=rng)        # 按权重抽一档
    T.next_tier("t2")                                # → "t3"（越界封顶）
    T.upgrade("t2", chance=0.05, steps=1, rng=rng)   # 以概率升档
    count_for({"t1": 0, "t5": [3, 4]}, "t5", extra_chance=0.20, rng=rng)   # 条数规则

**零知识**：引擎不认「品质」二字，也不认任何档位取值 —— 顺序与取值都由内容给。
"""
from __future__ import annotations

import random as _random

from .pick import pick_weighted


class TierTable:
    """有序档位阶梯。构造后不可变。"""

    def __init__(self, order, *, info=None, weights_by_level=None, aliases=None, clamp=None):
        self._order = tuple(order or ())
        self._index = {k: i for i, k in enumerate(self._order)}
        if len(self._index) != len(self._order):
            raise ValueError("档位 key 有重复")
        self._info = {k: dict(v) for k, v in dict(info or {}).items()}
        self._aliases = dict(aliases or {})
        # 别名表形态 = {档位key: 别名}；反查表给 resolve() 用（别名 → key）
        self._alias_rev = {v: k for k, v in self._aliases.items()}
        self._clamp = tuple(clamp) if clamp else None
        self._wl = {}
        for lv, row in dict(weights_by_level or {}).items():
            row = list(row)
            if len(row) != len(self._order):
                raise ValueError(f"等级 {lv} 的权重行长度 {len(row)} ≠ 档位数 {len(self._order)}")
            self._wl[int(lv)] = row
        if self._aliases:
            for k in self._aliases:
                if k not in self._index:
                    raise ValueError(f"别名指向未知档位：{k}")

    # ────────────────────────────────── 读
    @property
    def order(self) -> tuple:
        """档位序列（顺序即数据；首档最低、末档最高）。"""
        return self._order

    @property
    def levels(self) -> tuple:
        """权重表上出现过的等级（升序；无权重表 → 空）。"""
        return tuple(sorted(self._wl))

    def __len__(self):
        return len(self._order)

    def __contains__(self, key):
        return key in self._index

    def index(self, key) -> int:
        """档位序号（0 = 首档）；未知 → -1（**不抛错**：内容侧拿它做"未知就放过"的判断）。"""
        return self._index.get(key, -1)

    def tier_at(self, i) -> str | None:
        """第 i 档（负索引可从头数）；越界 → None。"""
        if not self._order:
            return None
        if -len(self._order) <= i < len(self._order):
            return self._order[i]
        return None

    def info_of(self, key) -> dict:
        """该档的自定义信息（**副本**，改它不影响表）；未知档 → {}。"""
        return dict(self._info.get(key, {}))

    def alias_of(self, key) -> str | None:
        """档位 key → 别名（如 "blue" → 「蓝」）；没配 → None。"""
        return self._aliases.get(key)

    def resolve(self, word) -> str | None:
        """玩家输入/别名 → 档位 key（先当 key，再查别名表）；认不出 → None。"""
        if word in self._index:
            return word
        return self._alias_rev.get(word)

    def next_tier(self, key, steps: int = 1) -> str | None:
        """往上升 steps 档，**封顶在末档**；未知档 → None（-1 步可往下，floor 在首档）。"""
        i = self.index(key)
        if i < 0:
            return None
        return self._order[min(len(self._order) - 1, max(0, i + steps))]

    def upgrade(self, key, *, chance: float = 1.0, steps: int = 1, rng=None) -> str | None:
        """以 `chance` 概率升 `steps` 档（升到顶就停在顶）；未命中 → 原档；未知档 → None。

        「概率升档」是形状（罗盘/道具/锻造都用它），`chance` 是多少是内容。
        """
        if self.index(key) < 0:
            return None
        r = rng or _random
        if chance < 1.0 and r.random() >= chance:
            return key
        return self.next_tier(key, steps)

    # ────────────────────────────────── 权重
    def weights_at(self, level, *, clamp=None, default=None) -> list:
        """等级 → 权重行（长度 = 档位数）。

        * 落在表内两个等级之间 → **线性插值**（浮点，不取整 —— 取整会改概率分布）
        * 低于最小 / 高于最大等级 → 取端点行
        * 无权重表 → `default`（给了就用，没给 → 等权 [1]*n）

        `clamp=(a, b)`：把等级先夹到 [a, b]（参考实现的「副业等级 1..9」就是它）。
        """
        if not self._order:
            return []
        if not self._wl:
            return list(default) if default is not None else [1] * len(self._order)
        lv = level
        cl = clamp if clamp is not None else self._clamp
        if cl:
            lv = max(cl[0], min(cl[1], lv))
        lv = int(lv)
        keys = sorted(self._wl)
        if lv <= keys[0]:
            return list(self._wl[keys[0]])
        if lv >= keys[-1]:
            return list(self._wl[keys[-1]])
        for a, b in zip(keys, keys[1:]):
            if a <= lv <= b:
                wa, wb = self._wl[a], self._wl[b]
                t = (lv - a) / (b - a)
                return [wa[i] + (wb[i] - wa[i]) * t for i in range(len(wa))]
        return list(self._wl[keys[0]])

    def weights_from(self, spec, *, level=None, clamp=None) -> list:
        """把「权重」归一成与档位对齐的行：list（直接用）/ dict（按 key 取，缺 → 0）。"""
        if spec is None:
            return self.weights_at(level, clamp=clamp) if level is not None else [1] * len(self._order)
        if isinstance(spec, dict):
            return [int(spec.get(k, 0) or 0) for k in self._order]
        row = list(spec)
        if len(row) < len(self._order):
            row = row + [0] * (len(self._order) - len(row))
        return row

    def pick_weights(self, weights, *, exclude=(), rng=None) -> str | None:
        """按权重行抽一档（`exclude` 里的档位权重置 0，全被排除 → None）。"""
        row = self.weights_from(weights)
        ex = set(exclude or ())
        pairs = [{"k": k, "w": (0 if k in ex else row[i])} for i, k in enumerate(self._order)]
        hit = pick_weighted(pairs, weight_key="w", rng=rng)
        return hit["k"] if hit else None

    def pick(self, *, level=None, weights=None, exclude=(), rng=None) -> str | None:
        """抽一档：给了 `weights` 用它，否则按 `level` 查权重表（都没有 → 等权）。"""
        row = self.weights_from(weights, level=level)
        return self.pick_weights(row, exclude=exclude, rng=rng)

    def sort_key(self, key) -> int:
        """排序用（升档方向为正）；未知档 → -1。"""
        return self.index(key)


def count_for(counts, tier, *, extra_chance: float = 0.0, rng=None) -> int:
    """档位 → 条数。

    `counts` 两种形态（内容数据）：

    * `int`            → 就是它
    * `[a, b]`（≥2）   → 以 `extra_chance` 概率取上界 b，否则取下界 a

    典型用法：最高档「20% 概率多一条」= `{"t5": [3, 4]}` + `extra_chance=0.20`。
    未知档位 → 0（零默认值：没声明 = 0 条）。
    """
    cfg = (counts or {}).get(tier, 0)
    if isinstance(cfg, (list, tuple)) and len(cfg) >= 2:
        r = rng or _random
        return int(cfg[1]) if r.random() < extra_chance else int(cfg[0])
    try:
        return int(cfg or 0)
    except (TypeError, ValueError):
        return 0
