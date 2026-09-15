# -*- coding: utf-8 -*-
"""《奥兰迪亚·余烬纪年》包内**掉落策略/解析器半边**（逐字搬自游戏仓 `game/drop_engine.py`）。

来源与范围
----------
真源 = 宿主 `game/drop_engine.py`（v184 收口版 **495 行**，2026-09-14 B12B13-TAIL 线3 起该文件
已改成**薄壳**）：引擎实例装配（池数据源 / 引用解析 / 专属策略 / 四入口 / 全量审计）**全搬**；
正文 `def _randint` → EOF（438 行）除「宿主取件 4 行 + fish 守卫 1 行」外逐行未改
（白名单门禁见 `overnight/d3_loot_verify.py` A1 节）。
真源的**形状层**（`LootTable` 池与策略注册表 / 展开 / 审计 / `SimpleCtx` / `TierTable`）不在这里 ——
v184 起它已在引擎 `saintess_engine.loot`（引擎零知识），真源与本文件都只是**引它**。

本文件 = 真源逐字搬入，只改三类东西：
  ① **import 层**：`from saintess_engine.loot import LootTable, SimpleCtx` 原样（唯一包外依赖 = 引擎）；
     另加 `TierTable`（垂钓档位表替身要用）
  ② **宿主耦合**：真源 `import game.content as C`（宿主内容 API）/ `from .data.drop_pools import
     DROP_POOLS`（宿主数据层）/ `game/core/quality_tiers.FISH_TIERS`（宿主档位表）
     → 改成「**调用方传 dict/回调**」（替身接口见下表）
  ③ **未搬**：真源之外的**写库/落包半边**（把产出发给玩家的消费端，属宿主事件）—— 一行不搬。

❷（2026-09-14 · B12B13-TAIL 线3）**宿主 `game/drop_engine.py` 已成薄壳**（模块别名到本文件）
   —— 宿主那份的「宿主取件」原文（`_get_pools()` 的宿主数据层优先分支 / `_fish_tiers()` 的
   本树装配分支 / 函数内 `import game.content as C`）搬进薄壳的三个 thunk，经
   `install_pools_source` / `install_quality_tiers_source` / `install_content_api_source` 挂进来
   （「活源」= 每次调用问一次，取数时机与打桩可见性逐字保留）。宿主薄壳文件：
   `<宿主>/game/drop_engine.py`（模块别名 + 三个 thunk + 源码探针）。

方向只有一个：**内容 → 引擎**（本文件只 `import saintess_engine`，引擎零游戏知识）。

① import 层改动（与真源逐行对拍见 `overnight/d3_loot_verify.py` A1 节）
| 真源写法 | 包内写法 | 说明 |
|---|---|---|
| `from saintess_engine.loot import LootTable, SimpleCtx`（:52） | 同左 + `TierTable` | 引擎；本文件唯一包外依赖 |
| `import game.content as C`（:67 / :445，**函数内**） | `C = _content_api(ctx)` / `C = _content_api()` | ② 宿主内容 API → 调用方给（替身接口） |
| `from .data.drop_pools import DROP_POOLS`（:207） | `_package_pools()` 读包内 `content/data/drop_pools.json`（宿主侧走活源） | ② 宿主数据层 → 包内同源数据（或 `install_pools` / `install_pools_source`） |
| `from .core.quality_tiers import FISH_TIERS`（:236/239） | `_QUALITY_TIERS`（`install_quality_tiers` / `install_quality_tiers_source` 挂） | ② 宿主档位表 → 调用方给 |

② 宿主耦合替身接口（本文件**不 import 宿主** —— 一律由调用方给 dict / 回调；三对挂载口）
| 真源宿主耦合 | 包内替身 | 调用方给什么 |
|---|---|---|
| `game.data.drop_pools.DROP_POOLS`（596 池数据） | `install_pools(pools)` / `install_pools_source(fn)`（活源优先）；未挂 → 包内 `content/data/drop_pools.json` | 池 dict（`{池key: {type, entries/rolls/…}}`），与真源数据逐条同源 |
| `game.content`：`ITEMS` / `EQUIP_ROSTER` / `RUNES` / `roll_blueprint` / `roll_gem_drop` / `roll_drop_equip` / `generate_roster_equip` / `generate_equip` / `rune_item` / `make_pet_egg` | `install_content_api(api)`（**模块 or 普通对象**，只按属性取） / `install_content_api_source(fn)`；也认 `ctx.content_api`（逐次覆盖）。未挂 → 包内默认 `_PackageContent` | 见 `content_api_keys()`：十支键**全部**转引包内真源（`ITEMS`/`EQUIP_ROSTER`/`RUNES` ← `content/catalog_items.py`；构造器七支 ← `content/{drops,gems,runes,pets}.py`）。★ R4（2026-09-15）：B14-2 时构造器七支还留在宿主（当时按「半边未搬」返 None/抛），C2/B15b 落地后已补齐，不再有「无人注入 = 该条出不来」的缺口 |
| `game.core.quality_tiers.FISH_TIERS`（垂钓档位表） | `install_quality_tiers(order, info=…, weights_by_level=…, aliases=…, clamp=…)`（或直接给 `TierTable`） / `install_quality_tiers_source(fn)` | 档位表；未挂 → **包内真源** `content/quality_tiers.py::FISH_TIERS`（★ R4 补齐；此前回落空表 ⇒ `_roll_fish` 抽空） |
| 事件钩子（真源 `ctx.hooks[hook]`） | **不变**（引擎 `SimpleCtx.hooks` 恒为 dict） | `special:xxx` 的 hook 表，由调用方塞进 ctx |

⚠️ 不变式：`ctx` 只是**调用方给的普通袋子**（引擎 `SimpleCtx`：缺属性 → None）。本文件不读玩家 DB /
   不认平台字段；`player_level` / `monster_lv` / `gold_base` / `prof_lv` / `bait` / `map_id` / `season`
   全是调用方塞的值。`season` 缺省时真源内联按**墙上时间**算季节（原样保留，不改成包内时间源）。

⚠️ 未搬（半边的界）：**写库/落包半边** —— 谁拿到 `roll()` 的产出、怎么发到玩家包里、落了哪张表，
   属宿主事件（游戏仓在命令层 `_handle_victory` 一族消费）。本文件只到「产出 dict 列表」为止，
   不写 DB、不发包、不碰存档。清单见 `overnight/d3-loot-port.md` §4。
"""
from __future__ import annotations

import json
import os
import random
from collections.abc import Mapping
from typing import Any

from saintess_engine.loot import LootTable, SimpleCtx, TierTable

# B14-2（L7 线）：包内默认内容 API 的**数据来源**切到包内门面（原就地读 content/data/*.json）
from .catalog_items import EQUIP_ROSTER, ITEMS, RUNES   # 真源 `game.content`:ITEMS / :EQUIP_ROSTER；B15b 补 RUNES

# ============================================================
# 搬运头：替身接口落点（包内新增，非真源正文）
# ============================================================

_HERE = os.path.dirname(os.path.abspath(__file__))          # <pkg>/content
_DATA_DIR = os.path.join(_HERE, "data")

# 调用方挂载口（None = 未挂 → 走包内默认）
_POOLS_OVERRIDE = None
_CONTENT_API = None
_QUALITY_TIERS = None
# 调用方挂载口「活源」（None = 未挂 → 走上面的静态挂载值，再退包内默认）
#   —— 等价真源三处「函数内惰性 import 宿主」（每次调用才解析；宿主薄壳把那段原文搬进 thunk）
_POOLS_SOURCE = None
_CONTENT_API_SOURCE = None
_QUALITY_TIERS_SOURCE = None

# 包内缓存（惰性：import 期不拉数据，与真源取数时机一致）
_POOLS_CACHE = None
_PACKAGE_CONTENT = None

# 调用方显式 `install_quality_tiers(None)` 时挂的空表（`_roll_fish` 守卫读它 → 抽不出；
# 不是「等权兜底」那种静默降级）。未挂任何值时不再走它 —— R4 起默认 = 包内真源 FISH_TIERS。
_EMPTY_TIERS = TierTable(())


def _read_json(name: str, default):
    """读 `content/data/<name>`（缺文件 / 坏 JSON → default，不抛）。"""
    try:
        with open(os.path.join(_DATA_DIR, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                        # noqa: BLE001
        return default


class _PackageContent:
    """包内默认内容 API —— **十支键全部转引包内真源**（R4 2026-09-15 补齐）。

    为什么必须补（实测，`out/texts_diffs.txt` + `out/logs/*/test_numeric_drop_unify.py.log`）：
    B14-2 时只有 `ITEMS` / `EQUIP_ROSTER`（+ B15b `RUNES`）进了包，装备/图纸/宝石/符文/
    宠物蛋**构造器**七支还留在宿主（`game.content` / `game.drop_engine`），本类当时按
    「半边未搬」返回 `None` / 抛 —— 那是**过渡期**口径。C2（`content/drops.py`）·
    `content/gems.py` · `content/rune*`（`content/runes.py`）· `content/pets.py` 落地后，
    这七支在包内都有逐字真源 ⇒ 终态默认**必须转引它们**；否则无人注入时：

      · `equip:` 引用一律 `None`（`generate_roster_equip` 抛）⇒ 副本 Boss 装备掉落整族消失
        （实测：`test_texts_table` [10] IN16 少 `⚔️ 拾取 Boss 珍藏`、IN20 少 `⚔️/👑` 两行，
        且 random 消耗位次变化 → 后续图纸/原石档位整片漂移）；
      · `roll_drop_equip` / `roll_blueprint` / `roll_gem_drop` 返 `None` ⇒ 精英专属出装、
        垂钓档、暗格装备/符文/蛋五档全抽不出（实测 `test_numeric_drop_unify` 4 条红）。

    取件韧性：惰性 `from . import …`（不在 import 期拉构造器模块，与真源「函数内 import
    宿主」同时机）；真源模块缺名 → `AttributeError` 原样抛（不静默造空实现）。
    """

    def __init__(self, items: dict, roster: dict):
        self.ITEMS = items
        self.EQUIP_ROSTER = roster
        self.RUNES = RUNES          # 包内 `catalog_items.RUNES`（B15b 真源；原为恒空表）

    @staticmethod
    def roll_blueprint(monster_lv):                          # 真源 `game.content:roll_blueprint`
        from . import drops as _d                             # → 包内 `content/drops.py`
        return _d.roll_blueprint(monster_lv)

    @staticmethod
    def roll_gem_drop(mon):                                  # 真源 `game.content:roll_gem_drop`
        from . import gems as _g                              # → 包内 `content/gems.py`
        return _g.roll_gem_drop(mon)

    @staticmethod
    def roll_drop_equip(monster_lv, role):                   # 真源 `game.drop_engine` 同名
        from . import drops as _d                             # → 包内 `content/drops.py`
        return _d.roll_drop_equip(monster_lv, role)

    @staticmethod
    def generate_roster_equip(rid):
        from . import drops as _d                             # → 包内 `content/drops.py`
        return _d.generate_roster_equip(rid)

    @staticmethod
    def generate_equip(slot, lv, quality):                   # noqa: ARG004
        from . import drops as _d                             # → 包内 `content/drops.py`
        return _d.generate_equip(slot, lv, quality)

    @staticmethod
    def rune_item(effect, lv):                               # 真源 `game.content:rune_item`
        from . import runes as _r                             # → 包内 `content/runes.py`
        return _r.rune_item(effect, lv)

    @staticmethod
    def make_pet_egg(pet_id):                                # 真源 `game.content:make_pet_egg`
        from . import pets as _p                              # → 包内 `content/pets.py`
        return _p.make_pet_egg(pet_id)


def _package_content() -> _PackageContent:
    """包内默认内容 API（惰性单例：第一次解析引用时才取门面）。

    B14-2（L7 线）：数据来源由「就地读 `content/data/{items,equip_roster}.json`」切到
    **包内门面** `content/catalog_items.py`（实测键集 900 / 687 与本文件直读 JSON 全等，
    本文件对这两表只做 `in` 成员判定 → 逐条同果）。`_PackageContent.RUNES` 默认空表
    **保持原样**（引擎侧约定：包内默认不产符文；真源 `C.RUNES` 由调用方
    `install_content_api()` 注入，见模块头 ②）。
    """
    global _PACKAGE_CONTENT
    if _PACKAGE_CONTENT is None:
        _PACKAGE_CONTENT = _PackageContent(ITEMS, EQUIP_ROSTER)
    return _PACKAGE_CONTENT


def _package_pools() -> dict:
    """包内池数据（惰性单例：第一次取池时才读 `content/data/drop_pools.json`）。"""
    global _POOLS_CACHE
    if _POOLS_CACHE is None:
        _POOLS_CACHE = _read_json("drop_pools.json", {}) or {}
    return _POOLS_CACHE


def _content_api(ctx=None):
    """内容 API 解析：`ctx.content_api` > 调用方 `install_content_api` 挂的 >
    `install_content_api_source` 挂的**活源**（每次调用问一次）> 包内默认。

    替身接口（真源 = 函数内 `import game.content as C`）：只按属性取，不要求是模块 ——
    普通对象 / `SimpleNamespace` / 模块都行；缺某个属性时由调用点决定后果（`ITEMS` /
    `EQUIP_ROSTER` / `RUNES` 三条在默认实现里已齐）。
    """
    if ctx is not None:
        api = getattr(ctx, "content_api", None)
        if api is not None:
            return api
    if _CONTENT_API is not None:
        return _CONTENT_API
    if _CONTENT_API_SOURCE is not None:                      # 活源：每次解析都问一次（真源同款时机）
        return _CONTENT_API_SOURCE()
    return _package_content()


def install_pools(pools=None) -> dict:
    """替身接口：调用方直接给池 dict（等价真源 `game.data.drop_pools.DROP_POOLS`）。

    传 `None` → 撤下，回落包内 `content/data/drop_pools.json`。返回挂上的池 dict。
    """
    global _POOLS_OVERRIDE
    _POOLS_OVERRIDE = pools
    return pools if pools is not None else _package_pools()


def install_content_api(api=None):
    """替身接口：挂内容 API（等价真源 `game.content` 的只读子集，键见 `content_api_keys()`）。

    传 `None` → 撤下，回落包内默认（十支键全部转引包内真源，见 `_PackageContent`）。
    """
    global _CONTENT_API
    _CONTENT_API = api
    return api


def install_quality_tiers(order=None, *, info=None, weights_by_level=None, aliases=None,
                          clamp=None) -> TierTable:
    """替身接口：挂垂钓档位表（等价真源 `game/core/quality_tiers.py:29 FISH_TIERS`）。

    两种用法：直接给 `TierTable` 实例，或按参构造（`order` + 三张数据表）。
    传 `order=None` → 空档位表（`_roll_fish` 抽不出，不抛）。
    """
    global _QUALITY_TIERS
    if isinstance(order, TierTable):
        _QUALITY_TIERS = order
    else:
        _QUALITY_TIERS = TierTable(order or (), info=info, weights_by_level=weights_by_level,
                                   aliases=aliases, clamp=clamp)
    return _QUALITY_TIERS


def content_api_keys() -> tuple:
    """内容 API 的**契约清单**（真源 `game/content.py` 里被本文件用到的属性，共 10 个）。"""
    return ("ITEMS", "EQUIP_ROSTER", "RUNES", "roll_blueprint", "roll_gem_drop",
            "roll_drop_equip", "generate_roster_equip", "generate_equip",
            "rune_item", "make_pet_egg")


def install_pools_source(fn=None):
    """替身接口：挂「**活**池源」（每次取池时调用一次，返回值 = 池 dict）。

    与 `install_pools(pools)`（静态值）并存：活源优先。真源 `_get_pools()` 本身就是
    「每次调用去问宿主数据层 / 包内门面」—— 宿主薄壳把那段原文搬进 thunk 后挂在这里，
    取数时机与打桩可见性（`sys.modules`/模块属性被换掉也看得见）逐字保留。
    传 `None` → 撤下。
    """
    global _POOLS_SOURCE
    _POOLS_SOURCE = fn
    return fn


def install_content_api_source(fn=None):
    """替身接口：挂「**活**内容 API 源」（每次解析引用时调用一次；等价真源函数内
    `import game.content as C`）。与 `install_content_api(api)` 并存：活源后判。传 `None` → 撤下。"""
    global _CONTENT_API_SOURCE
    _CONTENT_API_SOURCE = fn
    return fn


def install_quality_tiers_source(fn=None):
    """替身接口：挂「**活**档位表源」（每次取表时调用一次；等价真源函数内
    `from .core.quality_tiers import FISH_TIERS`）。与 `install_quality_tiers(...)` 并存：
    活源优先。传 `None` → 撤下。"""
    global _QUALITY_TIERS_SOURCE
    _QUALITY_TIERS_SOURCE = fn
    return fn


# ============================================================
# 基础工具（↓ 以下逐字真源正文）

def _randint(a: int, b: int) -> int:
    return random.randint(a, b)


def _resolve_item_ref(ref: str, ctx: Any) -> dict | None:
    """把条目引用解析为实物。返回统一产出 dict 或 None（池空/失败优雅跳过）。

    产出 dict 形态：{"type": "item"/"equip"/"bp"/"gem"/"gold"/"rune", "name":..., "data":..., "count":...}
    """
    C = _content_api(ctx)  # 替身：真源 `import game.content as C`（宿主内容 API → 调用方给）

    if ref == "bp":
        bp = C.roll_blueprint(max(1, int(getattr(ctx, "player_level", 1) or 1)))
        return {"type": "bp", "data": bp} if bp else None
    if ref == "gem":
        mon = {"lv": getattr(ctx, "monster_lv", None) or getattr(ctx, "player_level", 30),
               "is_boss": True, "map_area": "field"}
        gem = C.roll_gem_drop(mon)
        return {"type": "gem", "data": gem} if gem else None
    if ref == "rune":
        # 稀有符文：蓝/紫品质随机（v168 语义：随机取蓝/紫符文 1 级）
        pool = [k for k, r in RUNES.items() if (r.get("quality") or "") in ("blue", "purple")]
        if not pool:
            return None
        rk = random.choice(pool)
        r_def = RUNES[rk]
        rune_data = C.rune_item(r_def["effect"], random.randint(1, 2))
        return {"type": "rune", "data": rune_data} if rune_data else None
    if ref.startswith("gold:"):
        # gold:300:600
        parts = ref.split(":")
        a, b = int(parts[1]), int(parts[2]) if len(parts) > 2 else int(parts[1])
        return {"type": "gold", "count": _randint(a, b)}
    if ref.startswith("gold_pct:"):
        # gold_pct:30 = ctx.gold_base × 30%（战利品堆金币=通关奖金×30%）
        pct = float(ref.split(":", 1)[1])
        base = int(getattr(ctx, "gold_base", 0) or 0)
        return {"type": "gold", "count": max(10, int(base * pct / 100.0))}
    if ref.startswith("rune:"):
        # rune:blue / rune:purple（指定品质符文）；rune = 蓝紫混合
        q = ref.split(":", 1)[1] if ":" in ref else None
        pool = [k for k, r in RUNES.items()
                if (r.get("quality") or "") == q] if q else \
               [k for k, r in RUNES.items() if (r.get("quality") or "") in ("blue", "purple")]
        if not pool:
            return None
        rk = random.choice(pool)
        r_def = RUNES[rk]
        rune_data = C.rune_item(r_def["effect"], random.randint(1, 2))
        return {"type": "rune", "data": rune_data} if rune_data else None
    if ref == "equip_drop_mix":
        # 混合装备：60% boss 池 / 40% elite 池；所选池 None → 换另一池；仍 None → None
        # （暗格宝箱语义：40% 装备档永不空开——双池都失败由调用方兜底材料）
        lv = int(getattr(ctx, "monster_lv", None) or getattr(ctx, "player_level", 1) or 1)
        first_role = "boss" if random.random() < 0.60 else "elite"
        second_role = "elite" if first_role == "boss" else "boss"
        eq = C.roll_drop_equip(lv, first_role)
        if eq is None:
            eq = C.roll_drop_equip(lv, second_role)
        if eq:
            return {"type": "equip", "data": eq}
        return None
    if ref.startswith("equip:"):
        rid = ref.split(":", 1)[1]
        try:
            eq = C.generate_roster_equip(rid)
            return {"type": "equip", "data": eq}
        except Exception:
            return None
    if ref.startswith("equip_drop:"):
        # 通用装备掉落（随机）：equip_drop:elite / equip_drop:boss（走 roll_drop_equip 白名单+等级就近）
        role = ref.split(":", 1)[1]
        lv = int(getattr(ctx, "monster_lv", None) or getattr(ctx, "player_level", 1) or 1)
        eq = C.roll_drop_equip(lv, role)
        if eq:
            return {"type": "equip", "data": eq}
        # 兜底：随机生成同品质装备（与旧逻辑 generate_equip 一致）
        if role == "boss":
            slot = random.choice(["weapon", "helm", "armor", "legs", "boots", "ring", "necklace"])
            eq = C.generate_equip(slot, lv + random.randint(-3, 3), "orange")
        elif role == "elite":
            slot = random.choice(["weapon", "helm", "armor", "legs", "boots", "ring", "necklace"])
            eq = C.generate_equip(slot, lv + random.randint(-3, 3), "purple")
        return {"type": "equip", "data": eq} if eq else None
    if ref.startswith("petegg:"):
        # 宠物蛋：petegg:pet_xxx（C.make_pet_egg 构造）
        pet_id = ref.split(":", 1)[1]
        try:
            egg = C.make_pet_egg(pet_id)
            return {"type": "petegg", "data": egg} if egg else None
        except Exception:
            return None
    if ref.startswith("item:"):
        iid = ref.split(":", 1)[1]
        return {"type": "item", "item_id": iid}
    if ref.startswith("special:"):
        hook = ref.split(":", 1)[1]
        if hasattr(ctx, "hooks") and hook in (ctx.hooks or {}):
            try:
                return ctx.hooks[hook](ctx)
            except Exception:
                return None
        return None
    # 普通物品 ID
    return {"type": "item", "item_id": ref}


# ============================================================
# 内容侧词汇表（引擎零知识：认得出什么前缀、什么算内联引用，由这里声明）
# ============================================================

# 内联引用前缀：审计时"这些 ref 由 resolver 直接解析，不查池、不判断链"。
# ⚠️ 与 v174 audit_all 的白名单逐项一致，唯 **不含 `equip:`** —— 名册引用要**查名册**，
#    而引擎的 inline_prefixes 是"命中即跳过"，装不下这条判定；故 equip: 交给 resolvable 判。
_INLINE_PREFIXES = ("gold:", "gold_pct:", "item:", "special:", "equip_drop:", "petegg:", "rune:")

# 精确值特殊引用（不会断链）：图纸 / 幸运宝石 / 符文 / 混合装备
_SPECIAL_REFS = ("bp", "gem", "rune", "equip_drop_mix")

# 子池 key 可能带的前缀（v174 的 expand_pool / 审计里对 'weighted:xxx' / 'fixed:xxx' 的处理）
_POOL_KEY_PREFIXES = ("weighted:", "fixed:")

# `table` 池**展开**时的内联引用白名单：**逐字保留 v174 行为**。
# v174 的 expand_pool 对 table 池只外列 equip:/item:/gold: 三种，比审计白名单窄
# （gold_pct:/equip_drop:/petegg:/rune: 不外列）——两者本来就不是一个集合；
# 用引擎默认展开会认全部 inline_prefixes，`loot_pile:*` 会凭空多出 'gold_pct:30'，
# 故这里按旧白名单展开（对外行为一字不变）。
_EXPAND_INLINE_PREFIXES = ("equip:", "item:", "gold:")


def _get_pools() -> dict:
    """池数据源。替身接口（优先级）：`install_pools_source(fn)`（**活源**，每次取池问一次 ——
    宿主薄壳把真源 `_get_pools()` 的「宿主数据层优先 → 包内门面回退」两支搬进 thunk）>
    `install_pools(pools)`（静态值）> 包内 `content/data/drop_pools.json`（惰性缓存）。"""
    if _POOLS_SOURCE is not None:
        return _POOLS_SOURCE()
    if _POOLS_OVERRIDE is not None:
        return _POOLS_OVERRIDE
    return _package_pools()


class _LazyPools(Mapping):
    """惰性池视图：每次访问才去取 `DROP_POOLS`（保持 v174 的取数时机，import 期不拉数据）。"""

    def __getitem__(self, key):
        return _get_pools()[key]

    def __iter__(self):
        return iter(_get_pools())

    def __len__(self):
        return len(_get_pools())


# ============================================================
# 内容专属策略：fish（垂钓）
# ============================================================

def _fish_tiers():
    """垂钓档位表（真源唯一真相源 `game/core/quality_tiers.py:29 FISH_TIERS`）。

    替身接口（宿主耦合 → 调用方给）：`install_quality_tiers(order=…, info=…, weights_by_level=…,
    aliases=…, clamp=(1, 9))` 挂**真源那份档位表**，或 `install_quality_tiers_source(fn)` 挂**活源**
    （每次取表问一次；真源 `_fish_tiers()` 的「先确保本树数据层装配 → 取档位表」原文搬进 thunk）。

    ★ R4（2026-09-15）：未挂时的默认从「空表」改为**包内真源**
    `content/quality_tiers.py::FISH_TIERS`（B16-W11 档位四表已全数归包）——空表会让
    `_roll_fish` 首行守卫直接 `[]`（实测 `test_numeric_drop_unify` 的 `fish 垂钓出鱼` 红）。
    显式 `install_quality_tiers(None)` 仍挂**空表**（调用方要「抽不出」时照旧）。
    """
    if _QUALITY_TIERS_SOURCE is not None:
        return _QUALITY_TIERS_SOURCE()
    if _QUALITY_TIERS is not None:
        return _QUALITY_TIERS
    from .quality_tiers import FISH_TIERS as _PKG_FISH_TIERS
    return _PKG_FISH_TIERS


def _roll_fish(pool: dict, ctx: Any, table) -> list[dict]:
    """垂钓（内容专属策略，签名 = 引擎策略契约 `fn(pool, ctx, table)`）。

    先按钓点禁档/鱼饵/等级定质量档，再从该档品种按权重摸 1 条。

    pool.spot_cfg: {min_lv, ban_quality, subarea}
    pool.quality_weights: {钓点等级: [白绿蓝紫橙五档权重]}（缺省全局 FISH_QUALITY_WEIGHTS）
    pool.entries: [{"item": mat_id, "name":..., "quality":..., "w":..., "spots":...,
                    "season":..., "season_boost":..., "size_range":..., "weight_range":..., ...}]

    ⚠️ 两处抽档**仍是 `random.choices`**（经 `table.rng`，即标准库 random 模块本体）：
    权重行是**浮点**（等级插值），引擎 `pick_weighted` 会对权重做 `int()` 截断 → 改概率分布。
    权重**行**已收口到 `FISH_TIERS.weights_at()`（与旧 `_quality_weights_inline` 位级一致）。
    """
    FISH_TIERS = _fish_tiers()
    FISH_QUALITY_ORDER = FISH_TIERS.order
    if not FISH_QUALITY_ORDER:               # 替身守卫：档位表未挂（调用方没给）→ 抽不出（不抛）
        return []                            # noqa: 档位表未挂（不静默等权兜底）
    rng = table.rng
    spot_cfg = pool.get("spot_cfg") or {}
    ban = set(spot_cfg.get("ban_quality", []))
    prof_lv = int(getattr(ctx, "prof_lv", 1) or 1)
    bait = getattr(ctx, "bait", None)
    spot_id = getattr(ctx, "map_id", None)
    season = getattr(ctx, "season", None)
    if not season:
        # 内联季节计算（等价 core.time_weather.current_season，纯 datetime 防循环 import）
        try:
            import datetime
            _m = datetime.datetime.now().month
            season = {3: "spring", 4: "spring", 5: "spring",
                      6: "summer", 7: "summer", 8: "summer",
                      9: "autumn", 10: "autumn", 11: "autumn",
                      12: "winter", 1: "winter", 2: "winter"}.get(_m, "spring")
        except Exception:
            season = None

    # v184：权重行问 TierTable.weights_at()（旧 _quality_weights_inline 内联副本已删）
    weights = list(FISH_TIERS.weights_at(prof_lv))
    for i, q in enumerate(FISH_QUALITY_ORDER):
        if q in ban:
            weights[i] = 0.0
    if bait == "glow":
        for i, q in enumerate(FISH_QUALITY_ORDER):
            if q in ("purple", "orange"):
                weights[i] *= 2.0
    elif bait == "dough":
        for i, q in enumerate(FISH_QUALITY_ORDER):
            if q in ("green", "blue"):
                weights[i] *= 1.5
    quality = rng.choices(FISH_QUALITY_ORDER, weights=weights, k=1)[0]

    def _spots_ok(f):
        sp = f.get("spots")
        return not sp or (spot_id and spot_id in sp)

    def _season_ok(f):
        return not f.get("season") or f.get("season") == season

    entries = pool.get("entries", [])
    pool_by_q = [f for f in entries if f.get("quality") == quality and _spots_ok(f) and _season_ok(f)]
    if not pool_by_q:
        pool_by_q = [f for f in entries if f.get("quality") == quality and _spots_ok(f)]
    if not pool_by_q:
        pool_by_q = [f for f in entries if f.get("quality") == quality]
    if not pool_by_q:
        return []
    # 血饵稀有 ×3
    if bait == "blood":
        pool_w = [int(f.get("w", 1)) * (3 if int(f.get("w", 1)) <= 15 else 1) for f in pool_by_q]
    else:
        pool_w = [int(f.get("w", 1)) for f in pool_by_q]
    # 季节偏好 ×1.5
    if season:
        pool_w = [w * 1.5 if f.get("season_boost") == season else w
                  for f, w in zip(pool_by_q, pool_w)]
    pick = rng.choices(pool_by_q, weights=pool_w, k=1)[0]
    # 构造鱼条目返回（与旧 fishing.roll_fish 同形态：含 name/quality/type/price/size_range...）
    fish = dict(pick)
    fish["name"] = fish.get("name") or fish.get("item")
    return [{"type": "fish", "data": fish}]


def _expand_table(pool: dict, table) -> list:
    """`table` 池的展开：递归子池 + 内联引用原样外列（`_EXPAND_INLINE_PREFIXES` 白名单）。

    为什么不用引擎默认展开：引擎 `_expand_rolls` 认**全部** `inline_prefixes`，
    见 `_EXPAND_INLINE_PREFIXES` 的说明 —— 这里要的是 v174 的窄白名单。
    """
    out = []
    for rc in pool.get("rolls") or []:
        sub = rc.get("pool", "")
        if table.pools.get(sub) is not None:      # 旧语义：池表原样 key（不剥前缀）
            out.extend(table.expand(sub))
        elif isinstance(sub, str) and sub.startswith(_EXPAND_INLINE_PREFIXES):
            out.append(sub)
    return out


# ============================================================
# 引擎实例（池 + 引用解析 + 策略绑定）
# ============================================================

_TABLE = LootTable(
    _LazyPools(),                       # 惰性池视图（不 import 期拉 DROP_POOLS）
    resolver=_resolve_item_ref,         # 内容侧解析器（引擎只调它，不认识前缀）
    strategies={
        # 内容专属策略：uses/needs_weights/expand 是给审计与展开看的**元数据**
        "fish": {"fn": _roll_fish, "uses": "entries", "needs_weights": True, "expand": None,
                 "doc": "垂钓：质量档 → 品种（季节/水域/鱼饵），权重行问 TierTable"},
        # table 展开按 v174 窄白名单（见 _EXPAND_INLINE_PREFIXES）
        "table": {"expand": _expand_table},
        # table_choice 的 v174 展开走 entries 带权展开（暗格宝箱没有 entries → []）
        "table_choice": {"expand": None},
    },
    inline_prefixes=_INLINE_PREFIXES,
    pool_key_prefixes=_POOL_KEY_PREFIXES,
    special_refs=_SPECIAL_REFS,
    rng=random,                         # ★ 标准库模块本体：随机流与 v174 逐格对齐
)


class _StrategyMap(Mapping):
    """`POOL_STRATEGIES` 的只读转发（v184）。

    旧名字保留（有人 import 它），但**不是第二份真相源**：策略表活在 `_TABLE` 里，
    这里只是一层视图 —— `POOL_STRATEGIES[name]` → 引擎实例注册的策略函数。
    """

    def __init__(self, table: LootTable):
        self._table = table

    def __getitem__(self, name):
        spec = self._table._strategies.get(name)
        if spec is None:
            raise KeyError(name)
        return spec["fn"]

    def __iter__(self):
        return iter(self._table._strategies)

    def __len__(self):
        return len(self._table._strategies)


POOL_STRATEGIES = _StrategyMap(_TABLE)


# 旧名字保留：instance.py / fishing.py / wild_king.py 都在用 `_SimpleCtx(...)`。
# 语义与 v174 逐字相同（引擎 SimpleCtx = 同一份实现：缺属性 → None，hooks 恒为 dict）。
_SimpleCtx = SimpleCtx


# ============================================================
# 统一入口
# ============================================================

def roll(pool_key: str, ctx: Any = None, **kw) -> list[dict]:
    """任何池子唯一抽取入口。

    用法：
      roll("gather:oak_plain", ctx)                     # ctx 带 map_id/player_level/...
      roll("gather:oak_plain", ctx, qty=2)
      roll("chest:wild_low", ctx)
    返回产出 dict 列表；池不存在/抽空返回 []（优雅跳过，不抛错）。
    """
    # 旧语义：只认 `DROP_POOLS` 里的原样 key（不剥 weighted:/fixed: 前缀），空池也当"没有"
    if not _get_pools().get(pool_key):
        return []
    return _TABLE.roll(pool_key, ctx, **kw)


def expand_pool(pool_key: str) -> list:
    """返回池的带权展开候选 ID 列表（weighted 池按权重展开；fixed 池返回全部）。

    用途：命令层需要"候选池 + 自己多次 choice"的旧语义时（如采集按副业等级选 N 份），
    数据源统一走 DROP_POOLS。池不存在返回 []（调用方走兜底）。
    """
    if not _get_pools().get(pool_key):
        return []
    return _TABLE.expand(pool_key)


# ============================================================
# 全量审计
# ============================================================

def _resolvable(ref, pool) -> object:
    """引擎审计的**引用判定 + 措辞**（内容侧词汇表）—— `audit_all` 的"什么算断链、怎么说"都在这里。

    返回值四态（引擎 `LootTable.audit(resolvable=…)` 契约）：

      * `True`  —— 解得开
      * `False` —— 断链（引擎给通用措辞）
      * `str`   —— 断链，且**这句就是措辞**（本游戏用自己的说法：物品缺失 / 名册缺失 / 子池缺失）
      * `None`  —— 这条引用内容侧自己管，不判

    v184 之前这段判定散在 `audit_all` 里的两套分支（条目 ref / roll 子池 ref，措辞各一套），
    这里按池的策略元数据 `uses` 归一（`_TABLE.strategy_of(pool)["uses"]`）：
      `uses=entries` → 「物品缺失 / equip 名册缺失 / 引用无法解析」
      `uses=rolls`   → 「table 子池缺失 / table 子池未知」
    裸名册 id（`eq_xxx`）两条都认（INSTANCE_BOSS_EQUIP_DROP 老数据就是裸名册 id）；
    真实池数据里条目 ref 无裸名册 id（0/1435），见门禁 §7 登记。
    """
    C = _content_api()  # 替身：真源 `import game.content as C`（判定只看 ITEMS / EQUIP_ROSTER）
    if not isinstance(ref, str):
        return False
    uses = _TABLE.strategy_of(pool or {}).get("uses", "entries")
    if ref.startswith(_POOL_KEY_PREFIXES):
        key = ref.split(":", 1)[1]
        pools = _get_pools()
        if key in pools or any(k.endswith(key) for k in pools):
            return True
        return f"table 子池缺失: {ref}"
    if ref.startswith("equip:"):
        rid = ref.split(":", 1)[1]
        return True if rid in EQUIP_ROSTER else f"equip 名册缺失: {rid}"
    if ref in ITEMS or ref in EQUIP_ROSTER:
        return True
    if uses == "rolls":
        return f"table 子池未知: {ref}"
    if ref.startswith("mat_"):
        return f"物品缺失: {ref}"
    return f"引用无法解析: {ref}"


def audit_all() -> dict:
    """全量审计：断链/空池/权重/等级匹配/重复。

    返回 {"issues": [...], "pool_count": N, "entry_count": M}
    每个 issue: (级别, 池key, 描述)

    v184：判定**与措辞**都交给引擎 `LootTable.audit(resolvable=_resolvable)` ——
    本游戏的说法（物品缺失 / 名册缺失 / 子池缺失）由 `_resolvable` 直接给出，
    不再需要"事后把引擎文案改写回旧文案"那种字符串兼容壳；本函数只剔掉引擎多出的 `ok` 键，
    返回的三个键一字不变。
    """
    rep = _TABLE.audit(resolvable=_resolvable)
    return {
        "issues": list(rep["issues"]),
        "pool_count": rep["pool_count"],
        "entry_count": rep["entry_count"],
    }


def audit_pretty() -> str:
    """人类可读审计报告。"""
    rep = audit_all()
    lines = [f"DROP_POOLS 审计: {rep['pool_count']} 池 / {rep['entry_count']} 条目"]
    if not rep["issues"]:
        lines.append("✅ 0 问题")
    else:
        for lvl, key, msg in rep["issues"]:
            lines.append(f"  ⚠️ [{lvl}] {key}: {msg}")
    return "\n".join(lines)


__all__ = [
    "roll", "expand_pool", "audit_all", "audit_pretty", "POOL_STRATEGIES",
    "install_pools", "install_content_api", "install_quality_tiers", "content_api_keys",
]
