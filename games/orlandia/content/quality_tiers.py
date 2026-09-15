# -*- coding: utf-8 -*-
"""品质档位阶梯（B13-L1 端口，2026-09-14）—— 全项目**唯一**一份档位表构造点。

真源：游戏仓 `game/core/quality_tiers.py`（40 行）；下面是真源 docstring 的逐字保留，本文件
在其后补「惰性构造」实现（见下）。宿主同名文件已改薄壳。

取件（★ B16-W11 收口 · 2026-09-14：四张表全数归包）
* `QUALITY_ORDER` / `QUALITY` / `QUALITY_CN` → 包内门面 `content/catalog_b143.py`（`equipment` 域）。
* `FISH_QUALITY_WEIGHTS`（真源 `game/data/fishing.py:73`）→ 包内门面 `content/catalog_rules.py`
  （包内**无域** ⇒ 值随代码 dump、非手抄；已登记 `NOT_YET_DOMAINED`；注意真源是**字符串键** `"1"…"9"`，原样保留）。

时序**一字不变**：仍是模块级惰性代理 —— 第一次属性访问才用上述表建档位表，之后缓存同一对象
（`_build_tier_table` 的取件换了、时机没换；真源那把「模块级建档」的等价性由本代理兑现）。
真源理由（逐字保留）：包加载早于宿主数据就绪，`game.data → _assembly → core.class_sets → game.core`
这条 EAGER 链上任何 import 期宿主取件都会撞半初始化的 `game.data`。

⚠️ 宿主**源码级门禁**：`tests/test_v184_loot_tiers.py:671` 扫 `<插件>/game/**` 里的
`TierTable(` 字面并要求**只有** `game/core/quality_tiers.py` 一处 —— 宿主薄壳因此
**不出现该字面**（只再导出）✓。本文件是包内那份（唯一建档位表）。
"""


# -*- coding: utf-8 -*-
"""品质档位阶梯（v184 搬形状）—— 全项目**唯一**一份档位表。

v184 之前，「品质五档」的顺序/倍率/颜色/中文名 + 各处的权重表在**四处各自维护**：
装备（`data/equipment.QUALITY`）、垂钓（`data/fishing.FISH_QUALITY_WEIGHTS` 与它那份内联副本）、
锻造货架（`core/smith_stock.QUALITY_WEIGHTS`）、签到（`SIGNIN_CONFIG.week_quality_weights`），
外加坐骑/宠物又各抄一遍顺序。现在**顺序与取值只有一份**，全部经 `saintess_engine.loot.TierTable`
读取 —— 引擎不认识「品质」二字，它只按档位算。

用法::

    from ..core.quality_tiers import QUALITY_TIERS, FISH_TIERS, quality_of, quality_up
    QUALITY_TIERS.order                       # ('white','green','blue','purple','orange')
    QUALITY_TIERS.info_of("blue")["mult"]     # 1.55
    QUALITY_TIERS.next_tier("blue")           # 'purple'（封顶）
    QUALITY_TIERS.upgrade("blue", chance=0.05)  # 概率升档
    QUALITY_TIERS.resolve("蓝")               # 'blue'（玩家输入别名 → 档位 key）
    FISH_TIERS.weights_at(4)                  # 垂钓等级 → 五档权重（相邻两档线性插值，clamp 1..9）
    FISH_TIERS.pick(level=4, exclude=("orange",))   # 按权重抽一档
"""
from saintess_engine.loot import TierTable

# ---- 包内门面（B16-W11：档位四表全数归包）----
from .catalog_b143 import QUALITY, QUALITY_ORDER, QUALITY_CN  # `equipment` 域
from .catalog_rules import FISH_QUALITY_WEIGHTS               # 包内无域 → dump 字面量


def _build_tier_table(kind):
    """真源 :26-30 两行的构造本体（取件换宿主句柄；调用时解析）。"""
    if kind == "QUALITY_TIERS":
        # 装备/通用品质档位（顺序 = QUALITY_ORDER；每档信息 = QUALITY[key]，含倍率/颜色/中文名）
        return TierTable(QUALITY_ORDER, info=QUALITY, aliases=QUALITY_CN)
    # 垂钓档位（顺序同 QUALITY_ORDER；权重表按钓点等级，内容侧策略把等级夹在 1..9）
    return TierTable(QUALITY_ORDER, info=QUALITY, aliases=QUALITY_CN,
                     weights_by_level=FISH_QUALITY_WEIGHTS, clamp=(1, 9))


class _LazyTierTable:
    """`TierTable` 惰性代理：首次属性访问时用宿主表构造，之后返回同一对象。"""

    __slots__ = ("_kind", "_obj")

    def __init__(self, kind):
        self._kind = kind
        self._obj = None

    def _get(self):
        if self._obj is None:
            self._obj = _build_tier_table(self._kind)
        return self._obj

    def __getattr__(self, attr):
        return getattr(self._get(), attr)

    def __repr__(self):
        return "<_LazyTierTable %s>" % (self._kind,)


QUALITY_TIERS = _LazyTierTable("QUALITY_TIERS")

FISH_TIERS = _LazyTierTable("FISH_TIERS")


def quality_of(word):
    """玩家输入 → 档位 key（先当 key，再查中文别名）；认不出 → None。"""
    return QUALITY_TIERS.resolve(word)


def quality_up(quality, *, chance=1.0, steps=1, rng=None):
    """概率升档（封顶）；未知档位 → None。`chance` 与 `rng` 由调用方给（可复现）。"""
    return QUALITY_TIERS.upgrade(quality, chance=chance, steps=steps, rng=rng)
