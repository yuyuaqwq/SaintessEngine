# -*- coding: utf-8 -*-
"""包内「地图随机事件菜单」数据口（`content/event_menu.py`）—— B8.2 线3（2026-09-13）。

用途：宿主命令层 `game/commands/event_menu.py`（『今日事件』『事件 <地图名>』『领取补给箱』）
薄壳化后的**唯一读表口**。本模块只做「读包内域 JSON + 还原真源形状/顺序 + 一条纯逻辑」，
**不含渲染**（拼串一字未改地留在命令层 —— 与 B8.2 线5 `commands/job_guide.py` 同款口径）。

真源 → 包内域（单向导出：游戏仓 `scripts/export_game_package.py` + `scripts/export_domains/`）
------------------------------------------------------------------------------------------
| 命令层原来读（宿主聚合层 `C`） | 包内域 | 本模块提供（B14-2 起的取值口） | 备注 |
|---|---|---|---|
| `MAPS`（121，**list**，源序） | `worlds` | `MAPS` ← **门面** `content/catalog_space.py`（源序）；本地序名 `MAP_ORDER` = 门面同名列 | 地图扁平表（`game/data/maps.py` 的 `MAPS`/`MAP_BY_ID`） |
| `MAP_BY_ID` | 同左 | `MAP_BY_ID` ← 门面 `catalog_space` | 渲染只用 `.get("name")` / `["id"]` |
| `EXPLORE_EVENTS`（100，源序） | `events`（`source=="explore"`） | `EXPLORE_EVENTS` ← **门面** `content/catalog_quests.py` | 档位 top6 并列时**靠源序**决胜 |
| `EXPLORE_EGG_EVENTS`（46，源序） | `events`（`source=="egg"`） | `EXPLORE_EGG_EVENTS` ← 门面 `catalog_quests` | 传闻取 `[:3]`/`[:2]` → 硬依赖源序 |
| `ITEMS` / `resolve("items",…)` | `items` | `ITEMS` ← **门面** `content/catalog_items.py` / `resolve_item()`（本模块索引） | 补给箱发放 |
| `game/core/texts.py`（文案表门面） | `texts` | **不搬**（调用点必须留命令层，见 §④） | `supply.*` 7 条由宿主文案表门禁对账 |

★ B14-2（2026-09-14，L4 线）读点现状
------------------------------------
宿主 `game/data` 要删 ⇒ 本模块原先「就地读域 + 自带序声明 + 自带重建」的五张表**全部改从
包内门面直取**（门面 = 同批 B14-A/B/C 建的门面，本批门禁 `overnight/b14_catalog_gate.py`
逐名 **OK · 不等 0（含键序）**，见 `overnight/W-B14-2-L4.md`）：
* 门面已按域序声明 `_ORDER_*` 且自带集合守卫（域多/少一条即 `raise`）⇒ 本模块原先的
  `MAP_ORDER` / `EXPLORE_EVENT_ORDER` / `EGG_EVENT_ORDER` 字面量与 `_ordered()` /
  `_maps_ordered()` / `_read_domain()` 重建函数**全部删除**（防同表两份定义）。
  `MAP_ORDER` 这个名字**保留**（`content/catalog_items.py:43` / `catalog_life.py:41` 引它作
  「顺序只能显式声明」的先例，`content/travel.py` 也曾 import 它）⇒ 改写成门面 `_cs.MAP_ORDER`
  的只读视图，名字与内容（121 条 id，序相同）不变。
* 两处**取值形状**与本地旧值不同的地方（都取「门面 = 真源形状」那一侧，实测已逐条核对）：
  ① `MAPS` / `MAP_BY_ID` 的门面条目**多一个注入键 `subareas`**（真源 `game/data/maps.py` 有；
     本地旧值 = `worlds` 域裸条目，缺这个键）—— 消费点只读 `name` / `id`（宿主命令层
     `game/commands/event_menu.py:105/136`）⇒ 无行为差异；
  ② `EXPLORE_EVENTS` / `EXPLORE_EGG_EVENTS` 的门面条目**已剥注入键 `source`**（本地旧值带）
     —— 逐条去掉 `source` 后与门面 **deep-equal**（100/100、46/46），且 id 序与
     `sorted(key=-weight)[:6]` 的 top6 顺序完全一致（并列决胜靠它）⇒ 无行为差异。
* 未切：`MATERIALS` 仍是**有意空表**（理由见 §③ 末段；门面有 598 条同名表，但本模块消费点
  只在「ITEMS 未命中」的兜底分支里 → 保留原样，登记给主 agent 裁）。

★ 顺序声明（`MAP_ORDER` / `EXPLORE_EVENT_ORDER` / `EGG_EVENT_ORDER`）——为什么必须有
----------------------------------------------------------------------------------
域文件外层键是**字典序**（导出契约 `sort_table`：幂等优先），而这三张表的真源是
**有序 list**：① 地图 `next(... name in …)` 子串匹配要按源序取首个命中（『事件 橡木』
命中橡木镇还是橡木平原，由源序决定）；② 探索档位 `sorted(..., key=-weight)[:6]` 是稳定排序，
并列时按源序；③ 彩蛋传闻取前 3/前 2 条。少一份顺序声明 → 玩家看到的行会变（逐字变）。
B14-2：真源序**已在门面里单点声明**（`catalog_space._explore_seq()` · `catalog_quests` 的
同名 `_ORDER`，都带集合守卫：「域里多一条/少一条就 `raise`」）⇒ 本模块不再各存一份字面量。
更彻底的做法是域侧补 `seq`/`ord` 字段（`weekly_quests`/`titles` 域已是这形状），
那样连门面的序表也能删 —— 属导出器批的活，本线禁改，登记给主 agent。

未进包（保留宿主直读，报告 §缺口）
----------------------------------
`DAILY_MAP_EVENTS`（`game/data/daily_events.py:18`，20 图）、`WORLD_EVENT_POOL`
（`game/data/world.py:8`，14 条）、`SUPPLY_BOX`（`game/data/quest_add_v140.py:121`，3 档）
—— 三个域都**未预声明**（B8.2 父任务：不许新建未预声明的域）。它们的表由命令层注入，
**只有纯逻辑 `daily_event_for()` 在本模块**（逐字搬 `game/core/daily_events.py:21 today_map_event`）。
"""
from __future__ import annotations

import datetime

# ★ B14-2（L4）：五张表改从**包内门面**直取（宿主 `game/data` 删掉后本模块仍能活）；
#   门面自带域序声明 + 集合守卫 ⇒ 本模块原先的序字面量与重建函数已删（见文件头「读点现状」）。
from . import catalog_items as _ci         # ITEMS
from . import catalog_quests as _cq        # EXPLORE_EVENTS / EXPLORE_EGG_EVENTS
from . import catalog_space as _cs         # MAPS / MAP_BY_ID / MAP_ORDER


# ============================================================
# ① 地图（worlds 域 = 扁平地图表）
# ============================================================
MAP_ORDER: list = list(_cs.MAP_ORDER)       # 真源 `game/data/maps.py:3 MAPS` 的列表插入序（121）
MAPS: list = _cs.MAPS                       # 121（门面条目带注入键 `subareas`，与真源逐条相等）
MAP_BY_ID: dict = _cs.MAP_BY_ID             # {地图 id: 地图条目}

# ============================================================
# ② 事件池（events 域 = 探索池 + 彩蛋池；门面已剥注入字段 `source` 并按源序还原）
# ============================================================
EXPLORE_EVENTS: list = _cq.EXPLORE_EVENTS           # 100（探索池，源序）
EXPLORE_EGG_EVENTS: list = _cq.EXPLORE_EGG_EVENTS   # 46（彩蛋池，源序）

# ============================================================
# ③ 物品（items 域 = MATERIALS ∪ CONSUMABLES ∪ 追加条目的合表 900）
# ============================================================
ITEMS: dict = _ci.ITEMS                     # 900（与宿主聚合层同名表逐条相等，门禁 EQ）

# 名字 → id（`game/core/index.py:19 build_index` 同口径；**实测 900 条名字零重名**
# —— 所以「首/末次命中赢」这个差别不存在；仍按源顺序赋值，行为与真源一致）。
_ITEM_BY_NAME = {}
for _k, _v in ITEMS.items():
    if isinstance(_v, dict) and _v.get("name"):
        _ITEM_BY_NAME[_v["name"]] = _k

# ★ 材料域**未进包**（`content/data/` 无 materials.json；`MATERIALS`(598) ⊊ `ITEMS`(900)）。
#   真源 `_grant_items` 的「材料兜底」分支在真源数据下**结构性不可达**：
#   两张名字索引都建于同一批表（`game/data/_assembly.py:179` materials / `:183` items），
#   而 `ITEMS = dict(MATERIALS); ITEMS.update(...)`（`items.py:3057-3058`）⇒ 任何材料名都在
#   items 索引里，且解析出的 id 必然 ∈ ITEMS ⇒ 永远走第一分支。实测：SUPPLY_BOX 三档
#   9/9 物品名全部命中 ITEMS 分支。故此处给空表 + 保留分支形状（不静默造假表）。
#   ★ B14-2：**不切门面**——`catalog_items.MATERIALS` 是 598 条**材料段**表，而本模块的读点
#   只在「`resolve_item` 未命中 ITEMS」的兜底分支里（`_imid in MATERIALS`，`_imid` 是中文名
#   而 MATERIALS 键是 id）⇒ 换表既不改判定结果、又会让文档里的「结构性不可达」证明失真。
#   保留空表，登记为本线「未切项」（见报告「未做与缺口」）。
MATERIALS: dict = {}


def resolve_item(name_or_id: str):
    """物品名 → id（找不到**原样返回**；`game/core/index.py:47 resolve("items",…)` 同义）。"""
    return _ITEM_BY_NAME.get(name_or_id, name_or_id)


def resolve_material(name_or_id: str):
    """材料名 → id（真源 `resolve("materials",…)` 的包内替身；表未进包 ⇒ 只知道 id 原样返回）。"""
    return name_or_id


def display_material(entity_id: str) -> str:
    """材料 id → 显示名（真源 `display("materials",…)`；表未进包 ⇒ 原样返回 id）。"""
    return entity_id


# ============================================================
# ④ 文案（texts 域）—— **本模块不提供读口**
# ------------------------------------------------------------
# 补给箱那 7 条 `supply.*` 文案的 `T.static/T.text` 调用点**必须留在命令层**：
# `tests/test_texts_table.py:81 WIRED` 把 `game/commands/event_menu.py` 当「补给箱」域的
# 调用点真源，`t2` 双向对账（声明↔调用点）—— 调用点搬进包 ⇒ 表里 7 条立刻变「死文案」，
# 门禁红。故文案表口径不动（与 B8.2 线1 `commands/weekly.py` 同款：渲染留宿主）。
# ============================================================


# ============================================================
# ⑤ 今日奇遇（纯逻辑；`game/core/daily_events.py:21 today_map_event` 逐字搬）
# ============================================================
def _day_hash(seed: int, salt: str = "") -> int:
    h = seed * 2654435761 + (sum(ord(c) for c in salt) if salt else 0)
    return h & 0x7FFFFFFF


def daily_event_for(map_id, daily_map, now=None):
    """今日奇遇（日期哈希选中，同一天全服一致）。

    真源 `game/core/daily_events.py:21 today_map_event(map_id, now=None)`；本包版把
    `DAILY_MAP_EVENTS` 表改为**调用方传入**（该域未进包，见文件头）。返回选中的变体 dict
    （含 id/name/desc/effects），无配置返回 None —— 与真源逐字同义。
    """
    variants = (daily_map or {}).get(map_id)
    if not variants:
        return None
    _now = now or datetime.date.today()
    if isinstance(_now, datetime.datetime):
        ordinal = _now.date().toordinal()
    else:
        ordinal = _now.toordinal()
    # 用 map_id 作 salt，避免不同图同 seed 顶到同一下标的比例失配
    idx = _day_hash(ordinal, "daily:" + map_id) % len(variants)
    return variants[idx]
