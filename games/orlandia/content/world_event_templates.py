# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— 世界事件展示 / 初始化注册表（B13 线3，2026-09-14）。

真源：游戏仓 `game/core/world_event_templates.py`（121 行）。本模块 = 那个模块的**实现本体**
（`DISPLAYS` 6 个展示函数 + `INITIALIZERS` 2 个初始化函数 + `register` / `register_init` 全搬）；
宿主 `game/core/world_event_templates.py` 只剩再导出（`game/commands/social.py:776/810`
的 import 点零改动 —— 消费方式是 `DISPLAYS.get(etype)` / `INITIALIZERS.get(etype)`，**按名取**，
键序无语义）。

正文改动面（**只有一类**：函数体内延迟 import 的宿主聚合层）
------------------------------------------------------------
| 真源写法 | 包内替身 |
|---|---|
| `from .. import content as C`（`_i_auction` / `_i_boss` 内，`C.AUCTION_POOL` / `C.generate_equip` / `C.WORLD_BOSS_POOL`） | `AUCTION_POOL` / `WORLD_BOSS_POOL` → **包内门面** `content/catalog_b143.py`（★ W4，2026-09-14）；`generate_equip` 是**函数名**（不切）→ 仍走模块级 `C = _HostMod("content")` | 只换「取值来源」：两张池子逐条逐序与宿主 `C` 相等 ⇒ 行为一字未变 |

★ 数据读口（I1）：`AUCTION_POOL` / `WORLD_BOSS_POOL` —— 原「包内无同名域」缺口已由 **B14-3**
（`game_config.world` 组）补齐 ⇒ ★ W4 切包内门面 `content/catalog_b143.py`。
`generate_equip` 是函数（掉落族，`content/loot.py` 已有端口但消费点仍是宿主聚合层）
→ 按 B14 派工口径**函数名不切**，继续走宿主 `C` 替身。

等价证据：`overnight/w1213_b13l3_snap.py`（B1–B8 共 11 例：6 展示 × 边界 + 2 初始化 + 未知降级）
· `overnight/W-B13-L3-events-dialogue.md`。
"""
from __future__ import annotations

import importlib
import sys

# ★ W4（2026-09-14）：`C.AUCTION_POOL` / `C.WORLD_BOSS_POOL` → 包内门面（真源 `game/data/world.py:110/123`）
from . import catalog_b143 as _cat_b143


# ============================================================
# ① 宿主替身口（与 content/world_cmds.py 同款）
# ============================================================
_HOST_PKG = "data.plugins.dragonfall.game"
_HOST_PKG_FALLBACK = "game"
_INJECTED = {}


def bind_host(**objs):
    """宿主薄壳 import 期注入（幂等）——键 = `_HostMod` 的模块名（`content`）。"""
    for k, v in (objs or {}).items():
        if v is not None:
            _INJECTED[k] = v


def _host_module(name: str):
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
    raise RuntimeError("world_event_templates：宿主模块 %s 取不到（%s）——拒绝静默空跑" % (name, last))


class _HostMod:
    """宿主模块替身（`C`）——`C.xxx` 正文一字未改，属性访问时解析。"""

    def __init__(self, name):
        self._name = name

    def __getattr__(self, attr):
        return getattr(_host_module(self._name), attr)


C = _HostMod("content")     # 真源 `from .. import content as C`（延迟导入防循环 → 惰性替身同义）


DISPLAYS = {}


def register(etype):
    """展示注册装饰器。"""
    def deco(fn):
        DISPLAYS[etype] = fn
        return fn
    return deco


@register("auction")
def _d_auction(self, cur, lines, group_id):
    """拍卖：列出在拍物品 + 当前最高价"""
    items = cur["data"].get("items", [])
    for it in items:
        top = max(it["bids"].values()) if it["bids"] else 0
        top_name = ""
        if it["bids"]:
            top_qq = max(it["bids"], key=it["bids"].get)
            top_name = self._player(group_id, top_qq)
            top_name = top_name["name"] if top_name else top_qq
        lines.append(f"📦 {it['id']}. {it['name']} ｜ 底价 {it['base']}｜ 最高 {top_name or '无人出价'}：{top}")
        lines.append(f"   💰 一口价 {it['buyout']}｜『竞拍 {it['id']} <金币>』")


@register("boss")
def _d_boss(self, cur, lines, group_id):
    """世界 Boss：当前血量 + 讨伐入口"""
    b = cur["data"].get("boss", {})
    pct = max(0, int(b.get("hp", 0) / max(1, b.get("max_hp", 1)) * 100))
    lines.append(f"{b.get('icon', '')} {b.get('name', '')} Lv.{b.get('lv', 1)}")
    lines.append(f"❤️ 剩余血量 {max(0, b.get('hp', 0)):,} / {b.get('max_hp', 0):,}({pct}%)")
    lines.append(f"⚔️ 输入『讨伐』参与战斗！贡献越高奖励越丰厚！")


@register("merchant")
def _d_merchant(self, cur, lines, group_id):
    """行商：全商店 8 折"""
    lines.append("🎁 所有商店 8 折优惠进行中！『商店』查看，『购买 <物品>』扫货！")


@register("omen")
def _d_omen(self, cur, lines, group_id):
    """凶兆：经验金币 +50%"""
    lines.append("🌧️ 经验与金币收益＋50%！快去『探索』打怪吧！")


@register("swarm")
def _d_swarm(self, cur, lines, group_id):
    """兽潮：怪物经验 +30%，击杀声望双倍"""
    lines.append("⚔️ 怪物经验＋30%，击杀声望双倍！守护大陆！")


@register("festival")
def _d_festival(self, cur, lines, group_id):
    """庆典：签到奖励翻倍，金币掉落增加"""
    lines.append("🎉 『签到』奖励翻倍！金币掉落增加！")


# ============ 事件初始化注册表（v100.2）============
# 消灭 commands/social.py 事件触发时 data 生成的 etype if-elif（原 2 分支）。
# 与 DISPLAYS 对称：加新事件类型 = WORLD_EVENT_POOL 加数据 + register 展示 + register_init 初始化。
# 函数签名：fn(rnd) -> data dict（rnd 为 random 模块/实例，social.py 传入函数内局部 _rnd）
# 约定：未知 etype 不注册 → 返回空 data（与旧代码非 auction/boss 分支 data={} 一致）
INITIALIZERS = {}


def register_init(etype):
    """初始化注册装饰器。"""
    def deco(fn):
        INITIALIZERS[etype] = fn
        return fn
    return deco


@register_init("auction")
def _i_auction(rnd):
    """拍卖：随机抽 3 件高品质装备作拍卖品"""
    # 真源此处 `from .. import content as C`（延迟导入防循环）→ 本模块级 `C` 替身，同义
    items = []
    pool = rnd.sample(_cat_b143.AUCTION_POOL, min(3, len(_cat_b143.AUCTION_POOL)))
    for i, ap in enumerate(pool, 1):
        equip = C.generate_equip(ap["slot"], ap["lv"], ap["quality"])
        items.append({
            "id": i, "name": equip["name"], "slot": ap["slot"],
            "stats": equip.get("stats", {}), "desc": equip.get("desc", ""),
            # v104 P1：存完整 equip，结算/一口价直接发放（修复成交发 lv30 紫装与展示不符）
            "equip": equip,
            "base": ap["base"], "buyout": ap["buyout"],
            "bids": {},  # qq -> amount
        })
    return {"items": items}


@register_init("boss")
def _i_boss(rnd):
    """世界 Boss：随机抽取一只并初始化讨伐状态"""
    # 真源此处 `from .. import content as C`（延迟导入防循环）→ 本模块级 `C` 替身，同义
    b = rnd.choice(_cat_b143.WORLD_BOSS_POOL)
    return {"boss": {"name": b["name"], "icon": b["icon"], "lv": b["lv"],
                     "hp": b["hp"], "max_hp": b["hp"],
                     "reward": b["reward"], "contrib": {},
                     "mech": b.get("mech", ""),
                     "map": b.get("map", ""), "map_name": b.get("map_name", "")}}
