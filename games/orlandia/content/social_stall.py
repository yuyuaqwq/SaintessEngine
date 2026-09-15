# -*- coding: utf-8 -*-
"""包内社交·市场/摆摊域（`content/social_stall.py`）—— 真源 `game/commands/social.py` 的市场/摊位编排。

真源（游戏仓 `qqbot/data/plugins/dragonfall`，**只读**）
--------------------------------------------------------
| 真源 | 本文件搬什么 |
|---|---|
| `game/commands/social.py:36-60 market` | 群市场面板行（卖家名回调；tip/记账留命令层） |
| `game/commands/social.py:176-209 _stall_parse_args` | 摆卖/摆换参数解析（价格上下限/数量 1~999） |
| `game/commands/social.py:211-242 _stall_resolve` | 按背包序号/名称解析目标物品（精确→同名列表→模糊→无） |
| `game/commands/social.py:244-277 _stall_place` | 摆摊落位（数量校验 / 地图与铺面校验 / 原子上架） |
| `game/commands/social.py:338-342 _stall_label` | 摊位价格标签（`N 金币` / `🔄 换`） |
| `game/commands/social.py:346-383 stall_view` | 摊位面板两分支（指定玩家 / 当前地图） |
| `game/commands/social.py:98-157` | 「下架/购入」的目标选取与守卫（所有权/换摊/异地/金币） |

宿主耦合替身（**只改两类东西**：① 存储层 ② 读表口 —— 表都属宿主 `*_config`/数据面）
------------------------------------------------------------------------------
| 真源写法 | 包内写法 | 说明 |
|---|---|---|
| `from .. import db` + `db.xxx(...)` | 模块级 `db` = 惰性宿主代理 `_HostDB` | 正文 `db.xxx` 一行未改；注入优先 → 已加载宿主模块（**不 import**） |
| `MAP_BY_ID` / `HOUSE_LEVELS` / `ECON_CONFIG`（真源写法 `C.<名>`） | **包内门面直取**：`catalog_space`（`_cs`）/ `catalog_life`（`_cl`） | ★ **B14-2 L6**：切共享门面（`b14_catalog_gate.py` 逐值 + 键序相等）；`bind_host(maps=…, house_levels=…, econ=…)` 三个注入位**保留（宿主薄壳仍在传）但本域不再取用** |
| `QUALITY`（真源写法 `C.<名>`） | `bind_host(quality=…)` → `_host_attr("QUALITY", …)` | **缺口**：包内无品质表域（B14-B/E 已登记）⇒ 仍走宿主句柄；缺注入且宿主无该名 → 抛（不静默空表） |

返回结构（与真源逐字一致）
--------------------------
`stall_parse_args(raw, is_sell)` → `(item_name, (price, count))` 或 `(None, err_msg)`；
`stall_resolve(inv, item_name)` → `(条目, None)` 或 `(None, err_msg)`；
`stall_place(...)` → `(True, (item_nm, cnt_s, map_name, tip))` 或 `(False, msg)`；
`stall_label(s)` → `str`；`market_*_lines(...)` / `stall_view_*_lines(...)` → `list[str]`；
`market_unsell_pick(items, mid, qq_id)` → `(ok, 条目, err)`；`market_buy_check(it, player)` → `(ok, err)`。

用法::

    from content import social_stall as SS
    SS.bind_host(db, quality=…)          # maps/house_levels/econ 注入位已不用（B14-2 L6）
    ok, res = SS.stall_place(group_id, qq_id, player, item_name, price, count)
"""
from __future__ import annotations

import re

# ★ B14-2 L6：数据表切包内门面（宿主 `game/data` 删掉后本域仍能活）
from . import catalog_life as _cl        # HOUSE_LEVELS / ECON_CONFIG
from . import catalog_space as _cs       # MAP_BY_ID

# ============================================================
# ① 宿主替身口（存储层 / 宿主常量）
# ============================================================
_HOST_DB = None
_HOST_STORE_SOCIAL = None   # 注入槽：`game.store.social`—— 未注入 → 包内直取 `content/persistence/social.py`（market_sell_atomic 不在 db 门面上）
_MAPS = None            # 遗留注入位（B14-2 L6 起 `MAP_BY_ID()` 走包内门面 catalog_space）
_HOUSE_LEVELS = None    # 遗留注入位（B14-2 L6 起 `HOUSE_LEVELS()` 走包内门面 catalog_life）
_QUALITY = None         # `QUALITY`（装备品质色表）—— 包内无域 ⇒ 仍走宿主句柄（缺口）
_ECON = None            # 遗留注入位（B14-2 L6 起 `ECON_CONFIG()` 走包内门面 catalog_life）

_HOST_PKG = "data.plugins.dragonfall.game"
_HOST_PKG_FALLBACK = "game"


def bind_host(db=None, maps=None, house_levels=None, quality=None, econ=None, store_social=None):
    """宿主替身注入（幂等；宿主薄壳在 import 期调用）。"""
    global _HOST_DB, _MAPS, _HOUSE_LEVELS, _QUALITY, _ECON, _HOST_STORE_SOCIAL
    if db is not None:
        _HOST_DB = db
    if maps is not None:
        _MAPS = maps
    if house_levels is not None:
        _HOUSE_LEVELS = house_levels
    if quality is not None:
        _QUALITY = quality
    if econ is not None:
        _ECON = econ
    if store_social is not None:
        _HOST_STORE_SOCIAL = store_social


def _resolve_host(mod: str):
    """取宿主子模块：注入优先 → 已加载的宿主模块（`sys.modules`，**不 import**）。"""
    import sys
    for name in (f"{_HOST_PKG}.{mod}", f"{_HOST_PKG_FALLBACK}.{mod}"):
        m = sys.modules.get(name)
        if m is not None:
            return m
    raise RuntimeError(f"social_stall：宿主模块 {mod} 不可用（未 bind_host 且未加载）—— 拒绝静默空跑")


class _HostDB:
    """惰性宿主存储层代理（真源 `from .. import db`）——`db.xxx` 正文不动，属性访问时解析。"""

    def __getattr__(self, name):
        return getattr(_HOST_DB if _HOST_DB is not None else _resolve_host("db"), name)


db = _HostDB()


def _host_attr(name: str, injected):
    """宿主常量取值：注入优先 → 已加载的宿主 `game.content` → 抛（不静默空表）。

    B14-2 L6 后只剩 `QUALITY`（包内无域）走这里；另三张表已切包内门面。
    """
    if injected is not None:
        return injected
    c = _resolve_host("content")
    if not hasattr(c, name):
        raise RuntimeError(f"social_stall：宿主 content 缺 {name} —— 拒绝用空表继续")
    return getattr(c, name)


def MAP_BY_ID() -> dict:
    """★ B14-2 L6：包内门面直取（`maps` 注入值保留兼容、不再取用）。"""
    return _cs.MAP_BY_ID


def HOUSE_LEVELS() -> dict:
    """★ B14-2 L6：包内门面直取（`house_levels` 注入值保留兼容、不再取用）。"""
    return _cl.HOUSE_LEVELS


def QUALITY() -> dict:
    """装备品质色表 —— **缺口**（包内无域）：仍走宿主句柄。"""
    if _QUALITY is not None:          # 注入位优先（真源语义），B1：兜底切包内门面
        return _QUALITY
    from .catalog_b143 import QUALITY as _cb_quality   # 与宿主 `C.QUALITY` 同对象（is）
    return _cb_quality


def ECON_CONFIG() -> dict:
    """★ B14-2 L6：包内门面直取（`econ` 注入值保留兼容、不再取用）。"""
    return _cl.ECON_CONFIG


# ============================================================
# ② 摆摊（真源 `social.py:159-432`）
# ============================================================

def stall_parse_args(raw: str, is_sell: bool):
    """解析摆卖/摆换参数。返回 (item_name, price, count) 或 (None, err_msg)。

    is_sell=True: 『摆卖 <物> <单价> [数量]』数字 = 单价[, 数量]
    is_sell=False: 『摆换 <物> [数量]』数字 = 数量（无单价）
    """
    econ = ECON_CONFIG()
    if not raw:
        if is_sell:
            return None, ("格式：摆卖 <物品名/背包序号> <单价> [数量]\n"
                          "例：『摆卖 3 500 5』(背包第3件×5个，单价500)｜『摆卖 铁剑 500』")
        return None, ("格式：摆换 <物品名/背包序号> [数量]\n"
                      "例：『摆换 3 5』(背包第3件拿5个出来换)｜『摆换 铁剑』(换1件)")
    parts = re.split(r"[\s*]+", raw)
    item_name = parts[0]
    rest = parts[1:]
    price, count = 0, 1
    if rest:
        num_tokens = [t for t in rest if t.isdigit()]
        if not num_tokens:
            if is_sell:
                return None, "价格要用数字！例『摆卖 铁剑 500』『摆卖 3 500 5』"
            return None, "数量要用数字！例『摆换 3 5』"
        if is_sell:
            price = int(num_tokens[0])
            count = int(num_tokens[1]) if len(num_tokens) >= 2 else 1
        else:
            count = int(num_tokens[0])
        if price > 0:
            if price < econ["market_min_price"]:
                return None, "价格至少 1 金币！"
            if price > econ["market_price_cap"]:
                return None, f"价格太高啦！摆摊价最多 {econ['market_price_cap']} 金币～"
        if count < 1 or count > 999:
            return None, "摆摊数量请填 1~999 之间！"
    return item_name, (price, count)


def stall_resolve(inv, item_name):
    """按背包序号/名称解析目标物品。返回 (inv 条目, None) 或 (None, 错误文案)。"""
    quality = QUALITY()
    if item_name.isdigit():
        idx = int(item_name)
        if idx < 1 or idx > len(inv):
            return None, f"背包里没有第 {idx} 件物品（共 {len(inv)} 件）！『背包』查看序号～"
        return inv[idx - 1], None
    # 按名：精确名优先，同名多件列出让玩家选（对齐『出售』）
    exact = [it for it in inv if it["data"].get("name") == item_name]
    if len(exact) == 1:
        return exact[0], None
    if len(exact) > 1:
        flines = [f"❓ 找到 {len(exact)} 件同名『{item_name}』，用背包序号指定摆哪件（『摆卖 <序号> <价>』/『摆换 <序号>』）："]
        for i, it in enumerate(exact, 1):
            fd = it["data"]
            _q = quality[fd["quality"]] if fd.get("quality") and fd.get("slot") else None
            fname_s = f"{_q['color']}【{fd['name']}】" if _q else fd["name"]
            flines.append(f"  {i}. {fname_s} ×{it['count']}")
        return None, "\n".join(flines)
    fuzzy = [it for it in inv if item_name in it["data"].get("name", "")]
    if len(fuzzy) == 1:
        return fuzzy[0], None
    if len(fuzzy) > 1:
        flines = [f"❓ 找到 {len(fuzzy)} 件名字含『{item_name}』的物品，用全名或背包序号指定："]
        for i, it in enumerate(fuzzy, 1):
            fd = it["data"]
            _q = quality[fd["quality"]] if fd.get("quality") and fd.get("slot") else None
            fname_s = f"{_q['color']}【{fd['name']}】" if _q else fd["name"]
            flines.append(f"  {i}. {fname_s} ×{it['count']}")
        return None, "\n".join(flines)
    return None, f"背包里没有『{item_name}』！『背包』查看～"


def stall_place(group_id, qq_id, player, item_name, price, count):
    """摆摊落位公共逻辑：解析物品→数量校验→地图/铺面校验→原子上架。

    返回 (True, (item_nm, cnt_s, map_name, tip)) 或 (False, msg)（与真源 `_stall_place` 逐字同）。
    """
    maps = MAP_BY_ID()
    house_levels = HOUSE_LEVELS()
    found, err = stall_resolve(db.get_inventory(group_id, qq_id), item_name)
    if not found:
        return False, err
    if count > (found["count"] or 1):
        return False, f"『{found['data'].get('name','?')}』你只有 {found['count']} 个，摆不了 {count} 个！"
    cur_map = player.get("cur_map", "")
    map_obj = maps.get(cur_map, {})
    if not map_obj and not cur_map.startswith("home_"):
        return False, "这里没法摆摊……换个地方试试。"
    if cur_map.startswith("home_"):
        map_name = "家里"
    else:
        map_name = map_obj.get("name", cur_map)
    old = [s for s in db.market_list_by_seller(group_id, qq_id) if s.get("map_id")]
    _home_stall = cur_map.startswith("home_")
    if _home_stall:
        dlv = int(player.get("deed_lv", 1) or 1)
        hl = house_levels.get(dlv, house_levels[1])
        slots = hl.get("stall_slots", 0)
        if slots <= 0:
            return False, "🏠 木屋没有铺面挂机位！『地契 升级』到石屋解锁 1 个挂机位～"
        if len(old) >= slots:
            return False, f"🏪 铺面挂机位已满({len(old)}/{slots})！先『收摊』腾位置，或升级房屋获得更多挂机位～"
    _old_items = [] if _home_stall else [s for s in old]
    db.market_stall_sell_atomic(
        group_id, qq_id, found["key"], found["data"], price, cur_map, _old_items, count=count
    )
    tip = f"(旧摊位已收摊，{len(old)} 件物品退回背包)" if (old and not _home_stall) else ""
    item_nm = found["data"].get("name", "?")
    cnt_s = f" ×{count}" if count > 1 else ""
    return True, (item_nm, cnt_s, map_name, tip)


def stall_label(s):
    """摊位价格标签：price>0 → 'N 金币'；price=0 → '🔄 换'(以物换物)"""
    price = s.get("price") or 0
    return f"{price} 金币" if price > 0 else "🔄 换"


# ============================================================
# ③ 面板行（真源 `market` / `stall_view`）
# ============================================================

def market_view_lines(items, page_items, page, pages, seller_lookup, seller_group_id):
    """群市场面板主体行（真源 `social.py:46-57`；`_tip`/`_record_list_state` 留命令层）。

    真源逐字：行首编号直接用 DB id（与『购入 <编号>』『下架 <编号>』解析同基准）。
    """
    lines = [f"🏪 【群友市场】(第 {page}/{pages} 页 · 共 {len(items)} 件)", "━━━━━━━━━━━━"]
    for it in page_items:
        seller = seller_lookup(seller_group_id, it["seller"])
        sname = seller["name"] if seller else it["seller"]
        d = it["item_data"]
        lines.append(f"#{it['id']} {d.get('name','?')} ｜ {it['price']} 金币 ｜ 卖家 {sname}")
    lines.append("")
    if pages > 1 and page < pages:
        lines.append(f"💡 『市场 {page+1}』看下一页(共 {pages} 页)")
    return lines


def stall_view_player_lines(target, stalls):
    """『摊位 <玩家名>』面板行（真源 `social.py:364-368`）。"""
    maps = MAP_BY_ID()
    lines = [f"🏪 【{target['name']} 的摊位】", "━━━━━━━━━━━━"]
    for s in stalls:
        map_name = maps.get(s.get("map_id", ""), {}).get("name", "？")
        lines.append(f"#{s['id']} {s['item_data'].get('name','?')} ｜ {stall_label(s)} ｜ 在 {map_name}")
    lines.append("💡 标 🔄 的是换摊：『换 <编号> <物品名>』当面交换；其他『购入 <编号>』(需在同一位置)")
    return lines


def stall_view_here_lines(cur_map, stalls, player_lookup, group_id):
    """『摊位』（无参）本地摊位面板行（真源 `social.py:377-382`）。"""
    maps = MAP_BY_ID()
    lines = [f"🏪 【此地摊位】({maps.get(cur_map, {}).get('name', '这里')})", "━━━━━━━━━━━━"]
    for s in stalls:
        seller = player_lookup(group_id, s["seller"])
        sname = seller["name"] if seller else s["seller"]
        lines.append(f"#{s['id']} {s['item_data'].get('name','?')} ｜ {stall_label(s)} ｜ {sname}")
    lines.append("💡 标 🔄 的是换摊：『换 <编号> <物品名>』当面交换；其他『购入 <编号>』，『摊位 <玩家名>』看指定摊位")
    return lines


# ============================================================
# ④ 下架 / 购入 的选取与守卫（真源 `social.py:98-157`）
# ============================================================

def market_unsell_pick(items, mid, qq_id):
    """下架目标选取 + 所有权守卫。返回 (ok, 条目, err)（真源 `social.py:106-113` 逐字）。"""
    it = next((x for x in items if x["id"] == mid), None)
    if not it:
        return False, None, "没有这个上架物品！"
    if str(it["seller"]) != str(qq_id):
        return False, None, "只能下架自己的物品！"
    return True, it, None


def market_sell_place(group_id, qq_id, item_name, price):
    """上架落库：按名找背包物品 → 单事务原子上架。返回 (ok, 物品显示名, err)（真源 `social.py:78-93`）。"""
    inv = db.get_inventory(group_id, qq_id)
    found = None
    for it in inv:
        if it["data"].get("name") == item_name:
            found = (it["key"], it["data"])
            break
    if not found:
        return False, item_name, f"背包里没有『{item_name}』！『背包』查看～"
    item_key, data = found
    # v116 审计修复 H0-A2：原 market_add + remove_item 两次独立调用，崩溃会致
    # 物品复制/少货得金。改走 store.social.market_sell_atomic 单事务原子上架。
    # ★ REPOINT-PKG（2026-09-15，B4R B 组第 5 项）：兜底由宿主子模块 `game.store.social`
    #   改**包内直取** `content/persistence/social.py`（宿主那边是 `import *` 委托薄壳
    #   ⇒ 同一函数对象）；注入槽 `bind_host(store_social=…)` 原样保留。
    _store_social = _HOST_STORE_SOCIAL
    if _store_social is None:
        from .persistence import social as _store_social   # 包内直取（调用时取件，与旧口径同时机）
    if not _store_social.market_sell_atomic(group_id, qq_id, item_key, data, price):
        return False, item_name, f"背包里没有『{item_name}』！『背包』查看～"
    return True, data["name"], None


def stall_exchange_check(it, player, qq_id, group_id, give_name):
    """换摊前置守卫（寄售品/异地/自己/出售中/背包无给物）。返回 (ok, 给物条目, err)。

    真源 `social.py:396-422` 逐字：先判摊位存在（命令层），再判寄售→异地→自己→出售中→背包。
    """
    maps = MAP_BY_ID()
    if not it.get("map_id"):
        return False, None, "这是群市场寄售，不参与交换——用『购入 <编号>』金币购买～"
    # 当面交换：双方必须同地图
    if player.get("cur_map", "") != it["map_id"]:
        map_name = maps.get(it["map_id"], {}).get("name", "那里")
        return False, None, (f"这是【{it['item_data'].get('name','?')}】的换摊，需要到『{map_name}』"
                             f"当面交换～")
    if str(it["seller"]) == str(qq_id):
        return False, None, "不能和自己交换！"
    if (it.get("price") or 0) > 0:
        return False, None, (f"【{it['item_data'].get('name','?')}】是出售中的({it['price']} 金币)，"
                             f"用『购入 {it['id']}』购买～")
    inv = db.get_inventory(group_id, qq_id)
    give = next((x for x in inv if x["data"].get("name") == give_name), None)
    if not give:
        return False, None, f"背包里没有『{give_name}』！『背包』查看～"
    return True, give, None


def market_buy_check(it, player, qq_id):
    """购入前置守卫（自买/换摊/异地/金币）。返回 (ok, err)（真源 `social.py:134-151` 逐字）。

    - 自己买自己 → err；price<=0（换摊）→ err（指向『换』）；
    - 摊位货（有 map_id）需同地图；金币不足 → err。
    """
    maps = MAP_BY_ID()
    if str(it["seller"]) == str(qq_id):
        return False, "不能买自己的物品！"
    if (it.get("price") or 0) <= 0:
        return False, (f"【{it['item_data'].get('name','?')}】是换摊(只换不卖)——"
                       f"用『换 {it['id']} <物品名>』提出交换！")
    # v66：摊位货必须当面买（摆摊在当前位置，需要同地图）
    if it.get("map_id"):
        if player.get("cur_map") != it["map_id"]:
            map_name = maps.get(it["map_id"], {}).get("name", "那里")
            return False, (f"这是【{it['item_data'].get('name','?')}】的摊位货，需要到『{map_name}』"
                           f"当面购入～(『摊位』看看谁在摆摊)")
    if player["gold"] < it["price"]:
        return False, f"金币不足！需要 {it['price']} 金币。"
    return True, None
