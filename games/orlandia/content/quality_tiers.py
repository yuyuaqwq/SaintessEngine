# -*- coding: utf-8 -*-
"""品质档位阶梯（B13-L1 端口，2026-09-14）—— 全项目**唯一**一份档位表构造点。

真源：游戏仓 `game/core/quality_tiers.py`（40 行）；下面是真源 docstring 的逐字保留，本文件
在其后补「惰性构造」实现（见下）。宿主同名文件已改薄壳。

为什么这里要**惰性构造**（与其它模块「惰性句柄」同一手法，只是形状是对象不是函数）
--------------------------------------------------------------------------
真源在**模块级**用 `QUALITY_ORDER` + `QUALITY` + `QUALITY_CN` 建档位表；而四张数据表
（`QUALITY` / `QUALITY_ORDER` / `QUALITY_CN` / `FISH_QUALITY_WEIGHTS`）**没有同名域**
（`editor/domains.json` 66 域无 `quality*`），只能走宿主句柄 —— 宿主句柄必须**调用时**解析
（包加载早于 `game.data` 就绪；`game.data → _assembly → core.class_sets → game.core` 这条
EAGER 链上任何 import 期宿主取件都会撞半初始化的 `game.data`）。所以 `QUALITY_TIERS` /
`FISH_TIERS` 是**惰性代理**：第一次属性访问才用宿主表构造，之后缓存同一对象。
`TierTable` 的全部用法（`.order` / `.info_of` / `.next_tier` / `.upgrade` / `.resolve` /
`.weights_at` / `.pick` / `.pick_weights`）都是属性访问 → 代理零缝合。

⚠️ 宿主**源码级门禁**：`tests/test_v184_loot_tiers.py:671` 扫 `<插件>/game/**` 里的
`TierTable(` 字面并要求**只有** `game/core/quality_tiers.py` 一处 —— 宿主薄壳因此
**不出现该字面**（只再导出）✓。

缺口：`QUALITY*` / `FISH_QUALITY_WEIGHTS` 四张表无域 → 宿主句柄（报告 §5）。
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

_D = _HostMod("data")   # 宿主数据层（QUALITY 四张表无域 → 见头注缺口）


def _build_tier_table(kind):
    """真源 :26-30 两行的构造本体（取件换宿主句柄；调用时解析）。"""
    if kind == "QUALITY_TIERS":
        # 装备/通用品质档位（顺序 = QUALITY_ORDER；每档信息 = QUALITY[key]，含倍率/颜色/中文名）
        return TierTable(_D.QUALITY_ORDER, info=_D.QUALITY, aliases=_D.QUALITY_CN)
    # 垂钓档位（顺序同 QUALITY_ORDER；权重表按钓点等级，内容侧策略把等级夹在 1..9）
    return TierTable(_D.QUALITY_ORDER, info=_D.QUALITY, aliases=_D.QUALITY_CN,
                     weights_by_level=_D.FISH_QUALITY_WEIGHTS, clamp=(1, 9))


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
