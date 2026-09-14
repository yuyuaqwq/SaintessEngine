# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— smith_stock 核心域实现（B13-L5，2026-09-14）。

真源 = 宿主 `game/core/smith_stock.py`（原 438 行，v135 铁匠铺全服共享货架）**逐字搬**：
函数体一字未改，只换「宿主取件」。头注「全服共享限量货架…」整段随迁，见下：
全服共享限量货架（NPC 作品）：每城镇铁匠铺 4 件 = 2 武器 + 1 防具 + 1 饰品。
- 全服共享：event_state 用全局 key（不带 qq_id 后缀），所有玩家同一货架，先到先得
- 每日 0 点换货：读时惰性判定日期 ordinal 变化 → 全量重 roll
- 每 6 小时补货：restock_at 过期 → 保留未售罄件 + 补新品填满 4 件
- 品质权重：白 20 / 绿 25 / 蓝 35 / 紫 15 / 橙 5（紫橙可刷）
- 库存限购：每件 1~3 份（紫/橙 1 份，蓝绿 2-3 份），售罄即下架等补货
- 价格浮动：名册推导价 × 0.8~1.2 随机；保留 equip_resale_rate=0.5 防倒卖
- 命名：NPC 作品带『XX 的作品』后缀（SMITH_NPC_NAMES 按城镇映射）
- 随机池：EQUIP_ROSTER 按城镇等级 ±5 窗口 + 品质权重 sample，exclude 静态
  SHOP_EQUIP / SHOP_WEAPONS 已上架名册（避免与保底商店重复）

「宿主取件」对照（正文一行未改）
--------------------------------
| 真源写法 | 包内 | 依据 |
|---|---|---|
| `QUALITY_WEIGHTS` / `STOCK_COUNT` / `STOCK_WINDOW` / `RESTOCK_HOURS` / `_QTY_BY_QUALITY` / `SMITH_NPC_NAMES` / `_SMITH_TOWN_LEVELS`（源码字面量） | 包内域读口 `smith_stock`（`content/data/smith_stock.json`：`quality_weights` / `shelf_rules{stock_count,stock_window,restock_hours,qty_by_quality}` / `npc_names` / `town_levels`） | 域 = 这四组静态配置的**逐值镜像**（导出器 = 游戏仓 `scripts/export_domains/shop_econ.py:derive_smith_stock`）；对拍逐项相等，`overnight/w1213_l5_probe.py` P1 |
| `from ..data import SHOP_EQUIP, SHOP_WEAPONS` | 包内域读口 `shop`（`content/data/shop.json`，89 条店铺合表）→ `{k: v["equip"]}` / `{k: v["weapons"]}` | 合表是六张表并集（导出器 `derive_shop`）；对拍与宿主 `SHOP_EQUIP`/`SHOP_WEAPONS` 逐键相等（P8）。两者在正文里只用来**建静态店名册集合**（set），与键序无关 |
| `from ..data import EQUIP_ROSTER, EQUIP_ROSTER_BY_NAME` | `_HostAttr("data", …)` | **缺口**：`equip_roster` 域**不是字段级可逆投影**（I3）——域里被注入 `fixed_affixes`（622 条）/ `series_set`（397 条），实测 **665/687 条**与宿主真源不等，且外层键是字典序（宿主是源插入序，而 `roll_stock` 按插入序建候选池再 `random.choice`）→ 切了必改行为，本线不切 |
| `from ..data import QUALITY, ECON_CONFIG, WEAPON_FLAVOR` | `_HostAttr("data", …)` | **缺口**：三张表无同名域（BRIEF §5 对照表列明） |
| `from ..core.stats import equip_stats, equip_value` | `_HostAttr("core.stats", …)` | `core/stats.py` 属 **B13-L6** 线（并行未落地）→ 宿主句柄，落地后切包内直取 |
| `from .quality_tiers import QUALITY_TIERS` | `_HostAttr("core.quality_tiers", "QUALITY_TIERS")` | `core/quality_tiers.py` 属 **B13-L1** 线（并行未落地）→ 宿主句柄；正文 `QUALITY_TIERS.pick_weights(QUALITY_WEIGHTS, rng=random)` 一字未改（宿主源码级门禁指向本实现，见宿主壳头注） |
| `from .. import db`（函数内，惰性） | 模块级 `db = _HostMod("db")` | 正文 `db.get_event_state(...)` 未改；真源也只在 `get_smith_stock`/`buy_stock_item` 里用 db → 属性访问时解析，时机等价 |
| `from ..core.drops import generate_roster_equip`（`buy_stock_item` 函数内） | 同位置 `_host_attr("core.drops", …)` | **缺口**：`game/core/drops.py` 不在本线清单（别的线/B14 处理） |
| `from ..data import MAP_BY_ID, SUBAREAS`（`_ensure_maps()` 内，防循环） | 同位置 `_host_attr("data", …)` | 原样保留「延迟取 + 缓存」结构（真源注释：防循环） |

宿主侧：`game/core/smith_stock.py` 现在只剩「加载包 + 模块别名 + 源码探针」薄壳，见那边头注。
"""
import importlib
import json
import os
import random
import sys
import time
from datetime import date

# ============================================================
# ① 宿主替身口（注入优先 → sys.modules → importlib；**绝不静默空跑**）
#    抄 `content/world_cmds.py` 的同款写法（B9 线2 定的包内标准形状）
# ============================================================
_HOST_PKG = "data.plugins.dragonfall.game"      # 运行时（main.py 的模块路径）
_HOST_PKG_FALLBACK = "game"                     # 测试/工具按 `game.xxx` 直接 import 时
_INJECTED = {}
_MOD = "smith_stock"


def bind_host(**objs):
    """宿主薄壳 import 期注入（幂等）——键 = `_HostMod` 的模块名。"""
    for k, v in (objs or {}).items():
        if v is not None:
            _INJECTED[k] = v


def _host_module(name: str):
    """取宿主子模块（`name` 为空 = 宿主 `game` 包本身）。"""
    if name in _INJECTED:
        return _INJECTED[name]
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        m = sys.modules.get(prefix if not name else "%s.%s" % (prefix, name))
        if m is not None:
            return m
    last = None
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        try:
            return importlib.import_module(prefix if not name else "%s.%s" % (prefix, name))
        except Exception as exc:                # noqa: BLE001
            last = exc
    raise RuntimeError("%s：宿主模块 %s 取不到（%s）——拒绝静默空跑" % (_MOD, name, last))


def _host_attr(mod: str, attr: str):
    """宿主模块属性 —— 真源「函数内 `from ..<mod> import <attr>`」的同义替身（调用时解析）。"""
    m = _host_module(mod)
    try:
        return getattr(m, attr)
    except AttributeError:
        for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
            try:
                return importlib.import_module(
                    "%s.%s" % (prefix if not mod else "%s.%s" % (prefix, mod), attr))
            except Exception:                   # noqa: BLE001
                continue
        raise


class _HostMod:
    """宿主模块替身（`db`）——正文里 `db.xxx` 照原样写，属性访问时解析。"""

    def __init__(self, name):
        self._name = name

    def __getattr__(self, attr):
        return getattr(_host_module(self._name), attr)


class _HostAttr:
    """宿主「模块属性」惰性替身 —— 真源模块级 `from ..data import X` / `from ..core.X import f`
    的同义替身：模块级名字不变、正文一字未改；取值在**首次被访问/调用**时发生。"""

    __slots__ = ("_mod", "_attr", "_val")

    def __init__(self, mod, attr):
        object.__setattr__(self, "_mod", mod)
        object.__setattr__(self, "_attr", attr)

    def _v(self):
        try:
            return object.__getattribute__(self, "_val")
        except AttributeError:
            v = _host_attr(object.__getattribute__(self, "_mod"),
                           object.__getattribute__(self, "_attr"))
            object.__setattr__(self, "_val", v)
            return v

    def __getattr__(self, name):
        return getattr(self._v(), name)

    def __getitem__(self, k):
        return self._v()[k]

    def __setitem__(self, k, v):
        self._v()[k] = v

    def __contains__(self, k):
        return k in self._v()

    def __iter__(self):
        return iter(self._v())

    def __len__(self):
        return len(self._v())

    def __bool__(self):
        return bool(self._v())

    def __call__(self, *a, **kw):
        return self._v()(*a, **kw)


db = _HostMod("db")
# ★ B16-W11d：五张表改包内门面直取（原 `_HostAttr("data", …)` 盲区形态）
from .catalog_b143 import QUALITY, WEAPON_FLAVOR
from .catalog_items import EQUIP_ROSTER, EQUIP_ROSTER_BY_NAME
from . import catalog_life as _clife
ECON_CONFIG = _clife.ECON_CONFIG
equip_stats = _HostAttr("core.stats", "equip_stats")
equip_value = _HostAttr("core.stats", "equip_value")
QUALITY_TIERS = _HostAttr("core.quality_tiers", "QUALITY_TIERS")

# ============================================================
# ② 包内域读口（域 `smith_stock` + `shop`；导出器 = 游戏仓
#    `scripts/export_domains/shop_econ.py:derive_smith_stock / derive_shop`）
# ============================================================
_HERE = os.path.dirname(os.path.abspath(__file__))


def _read_domain(domain: str, sub: str = "data"):
    """读包内 `content/<sub>/<domain>.json`（缺文件/坏 JSON → {}，不抛，与 tables.py 同款）。"""
    try:
        with open(os.path.join(_HERE, sub, "%s.json" % domain), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:                            # noqa: BLE001
        return {}


_SMITH_CFG: dict = _read_domain("smith_stock")
_SHELF_RULES: dict = _SMITH_CFG["shelf_rules"]   # 取不到就 KeyError（不静默给 0 件货架）

# v184：品质档位唯一真相源（TierTable）——顺序/别名/抽取都在这里，本模块不再自建档位表
# v135 铁匠铺货架品质权重（白/绿/蓝/紫/橙，鱼鱼拍板：紫橙可刷）
QUALITY_WEIGHTS = dict(_SMITH_CFG["quality_weights"])

STOCK_COUNT = _SHELF_RULES["stock_count"]    # 每城镇铁匠铺货架件数 = 2 武器 + 3 防具 + 2 饰品 + 1 随机（v170 扩品）
STOCK_WINDOW = _SHELF_RULES["stock_window"]  # 城镇等级 ±5 窗口
RESTOCK_HOURS = _SHELF_RULES["restock_hours"]  # 售罄后补货周期（小时）

# 库存限购：紫/橙 1 份，蓝/绿 2-3 份（白 2-3 份同蓝绿）
_QTY_BY_QUALITY = dict(_SHELF_RULES["qty_by_quality"])

# 城镇铁匠 NPC 名字映射（v135 装备特色：NPC 作品命名）
SMITH_NPC_NAMES = dict(_SMITH_CFG["npc_names"])

# 城镇推荐等级（v135 方案文档权威等级窗口的中心值，±5 = 文档窗口：
# 橡木1-7/白鹿3-13/铁港13-23/晨曦25-35/翡翠30-40/月语47-57/霜角60-70/龙脊80-90/风翼85-95）
# v168 补两城：铁盾镇/铁砧要塞有 craft 铁匠铺但此前不在表 → 锻造分阶段漏网（F 报告），
# 按地图推荐等级 30/65 补入（铁盾≈晨曦段、铁砧≈霜角段）。
_SMITH_TOWN_LEVELS = dict(_SMITH_CFG["town_levels"])

# 静态商店名册（SHOP_EQUIP + SHOP_WEAPONS 已上架名册 → 货架排除，避免重复上架）
# 表体 = 包内 `shop` 域（89 条店铺合表）的两个切片；本模块只用来建集合（与键序无关）。
_SHOP_CFG: dict = _read_domain("shop")
SHOP_EQUIP: dict = {k: v["equip"] for k, v in _SHOP_CFG.items() if "equip" in v}
SHOP_WEAPONS: dict = {k: v["weapons"] for k, v in _SHOP_CFG.items() if "weapons" in v}
_MAP_BY_ID = {}
_SUBAREAS = {}


def _ensure_maps():
    global _MAP_BY_ID, _SUBAREAS
    if not _MAP_BY_ID:
        from . import catalog_space as _cs          # ★ B16-W11d：包内门面（原 `_host_attr("data", …)`）
        _MAP_BY_ID = _cs.MAP_BY_ID
        _SUBAREAS = _cs.SUBAREAS


# db 惰性：模块级 `db = _HostMod("db")`（见上），正文 `db.xxx` 一字未改。
# v135：仅 get_smith_stock/buy_stock_item 用到 db，代理在属性访问时才解析宿主模块。

_STATIC_SHOP_RIDS = None


def _static_shop_rids() -> set:
    """懒构建：静态 SHOP_EQUIP（含 dict 覆盖价条目）+ SHOP_WEAPONS 武器名册名。"""
    global _STATIC_SHOP_RIDS
    if _STATIC_SHOP_RIDS is None:
        s = set()
        for _lst in SHOP_EQUIP.values():
            for _e in _lst:
                s.add(_e["rid"] if isinstance(_e, dict) else _e)
        for _lst in SHOP_WEAPONS.values():
            for _wname, *_rest in _lst:
                for _rid in EQUIP_ROSTER_BY_NAME.get(_wname, []):
                    s.add(_rid)
        _STATIC_SHOP_RIDS = s
    return _STATIC_SHOP_RIDS


def town_level(map_id: str) -> int:
    """城镇推荐等级：优先 SMITH_TOWN_LEVELS 表（方案文档权威窗口中心值，
    文档窗口：橡木1-7/白鹿3-13/铁港13-23/晨曦25-35/翡翠30-40/月语47-57/霜角60-70/
    龙脊80-90/风翼85-95），兜底取 MAP_BY_ID[map_id].lv（无 lv 时按子区域怪物等级估算）。"""
    if map_id in _SMITH_TOWN_LEVELS:
        return _SMITH_TOWN_LEVELS[map_id]
    _ensure_maps()
    m = _MAP_BY_ID.get(map_id, {})
    lv = m.get("lv")
    if lv:
        return int(lv)
    # 子区域怪物等级估算兜底
    lvs = []
    for _sa in m.get("subareas") or []:
        _sad = _SUBAREAS.get(_sa) or {}
        _m = _sad.get("monsters") or []
        for _mi in _m:
            if isinstance(_mi, dict) and _mi.get("lv"):
                lvs.append(int(_mi["lv"]))
    return int(sum(lvs) / len(lvs)) if lvs else 1


def _pick_weighted_quality() -> str:
    """按品质权重随机一个品质（白20/绿25/蓝35/紫15/橙5）。

    v184：抽取形状走唯一真相源 `QUALITY_TIERS.pick_weights`（权重行按档位序对齐；
    档位取值与顺序只有一份）。旧实现是「randint(1, 总和) + 手写累加」，
    概率分布完全相同（都是等比例切段），但消费的随机数不是同一个——逐次同种子
    结果会变，分布不变（门禁 tests/test_v184_loot_tiers.py 有分区等价证明）。
    """
    return QUALITY_TIERS.pick_weights(QUALITY_WEIGHTS, rng=random)


def roll_stock(map_id: str, town_lv: int) -> list:
    """roll STOCK_COUNT 件货架：2 武器 + 3 防具 + 2 饰品 + 1 随机（等级窗口 ±5 + 品质权重）。

    每件 {"rid", "qty", "price_mult"}：
    - qty：紫/橙 1 份，蓝绿 2-3 份（random 2~3）
    - price_mult：0.8~1.2 随机（保留 1 位小数）
    v170：货架 4→8（2武器+3防具+2饰品+1随机），随机件在三个池间再抽。
    """
    lo, hi = town_lv - STOCK_WINDOW, town_lv + STOCK_WINDOW
    exclude = _static_shop_rids()
    pools = {"weapon": [], "armor": [], "trinket": []}
    for rid, r in EQUIP_ROSTER.items():
        if rid in exclude:
            continue
        # v172 路B：source=重锻 装备（仅『装备重锻』可得）不进铁匠铺货架随机池
        if r.get("source") == "重锻":
            continue
        if not (lo <= r["lv"] <= hi):
            continue
        if r["slot"] == "weapon":
            pools["weapon"].append(rid)
        elif r["slot"] in ("armor", "helm", "boots", "legs"):
            pools["armor"].append(rid)
        elif r["slot"] in ("ring", "necklace"):
            pools["trinket"].append(rid)
    # 保证货架件数：等级窗口候选不足时逐级放宽（窗口±6→全档低段→全局低段），
    # 品质权重只做倾向（未命中权重品质的槽位直接取候选池首位），不缩水货架数量
    need_map = {"weapon": 2, "armor": 3, "trinket": 2}
    for _ in range(6):
        if all(len(p) >= n for p, n in ((pools["weapon"], 2), (pools["armor"], 3), (pools["trinket"], 2))):
            break
        extra = [rid for rid, r in EQUIP_ROSTER.items()
                 if rid not in exclude and rid not in pools["weapon"] + pools["armor"] + pools["trinket"]
                 and r.get("source") != "重锻"  # v172 路B：重锻专属不进货架
                 and (lo - 6 <= r["lv"] <= hi + 6)]
        if not extra:
            break
        rid = random.choice(extra)
        r = EQUIP_ROSTER[rid]
        if r["slot"] == "weapon":
            pools["weapon"].append(rid)
        elif r["slot"] in ("armor", "helm", "boots", "legs"):
            pools["armor"].append(rid)
        elif r["slot"] in ("ring", "necklace"):
            pools["trinket"].append(rid)
    # 等级窗口候选不足时，最后兜底从全局低等级名册补足（优先低级，防新手镇出高等级装）
    if not all(len(p) >= n for p, n in ((pools["weapon"], 2), (pools["armor"], 3), (pools["trinket"], 2))):
        missing_kinds = []
        if len(pools["weapon"]) < 2:
            missing_kinds.append("weapon")
        if len(pools["armor"]) < 3:
            missing_kinds.append("armor")
        if len(pools["trinket"]) < 2:
            missing_kinds.append("trinket")
        # 兜底池：窗口内 > 邻近 ±3 > 全局低段（lv ≤ town_lv+10，越近越好）
        def _near(rid):
            return abs(EQUIP_ROSTER[rid]["lv"] - town_lv)
        glob_cands = sorted(
            (rid for rid, r in EQUIP_ROSTER.items()
             if rid not in exclude and rid not in pools["weapon"] + pools["armor"] + pools["trinket"]
             and r.get("source") != "重锻"  # v172 路B：重锻专属不进货架
             and (lo <= r["lv"] <= hi or (lo - 3 <= r["lv"] <= hi + 3) or r["lv"] <= town_lv + 10)),
            key=lambda rid: (0 if lo <= EQUIP_ROSTER[rid]["lv"] <= hi
                             else (1 if lo - 3 <= EQUIP_ROSTER[rid]["lv"] <= hi + 3 else 2), _near(rid)))
        for mk in missing_kinds:
            for rid in glob_cands:
                r = EQUIP_ROSTER[rid]
                if mk == "weapon" and r["slot"] == "weapon":
                    pools["weapon"].append(rid)
                    break
                elif mk == "armor" and r["slot"] in ("armor", "helm", "boots", "legs"):
                    pools["armor"].append(rid)
                    break
                elif mk == "trinket" and r["slot"] in ("ring", "necklace"):
                    pools["trinket"].append(rid)
                    break
        # 若仍缺（如 Lv.1-9 无任何饰品名册），放宽 lv 上限到 town_lv + 20（新手镇也能挂上低档饰品）
        if not all(len(p) >= n for p, n in ((pools["weapon"], 2), (pools["armor"], 3), (pools["trinket"], 2))):
            glob_cands = sorted(
                (rid for rid, r in EQUIP_ROSTER.items()
                 if rid not in exclude and rid not in pools["weapon"] + pools["armor"] + pools["trinket"]
                 and r.get("source") != "重锻"),  # v172 路B：重锻专属不进货架
                key=lambda rid: (abs(EQUIP_ROSTER[rid]["lv"] - town_lv)))
            for mk in missing_kinds:
                for rid in glob_cands:
                    r = EQUIP_ROSTER[rid]
                    if mk == "weapon" and r["slot"] == "weapon":
                        pools["weapon"].append(rid)
                        break
                    elif mk == "armor" and r["slot"] in ("armor", "helm", "boots", "legs"):
                        pools["armor"].append(rid)
                        break
                    elif mk == "trinket" and r["slot"] in ("ring", "necklace"):
                        pools["trinket"].append(rid)
                        break
    items = []
    for kind, need in (("weapon", 2), ("armor", 3), ("trinket", 2)):
        cands = list(pools[kind])
        for _ in range(need):
            if not cands:
                break
            # 品质权重分层 → 每层再按权重抽 1 件（保持品质分布，防同品质挤占）
            picked = None
            for _try in range(40):
                q = _pick_weighted_quality()
                layer = [rid for rid in cands if EQUIP_ROSTER[rid]["quality"] == q]
                if not layer:
                    continue
                picked = random.choice(layer)
                break
            if picked is None:
                picked = random.choice(cands)
            cands.remove(picked)
            q = EQUIP_ROSTER[picked]["quality"]
            qty = _QTY_BY_QUALITY.get(q, random.randint(2, 3))
            items.append({
                "rid": picked,
                "qty": qty,
                "price_mult": round(random.uniform(0.8, 1.2), 1),
            })
    # 第 8 件（随机）：从非空池抽 1 件不重复件（v170 扩品）
    spare_cands = [it["rid"] for it in items]
    _extra_pool = []
    for kind in ("weapon", "armor", "trinket"):
        for rid in pools[kind]:
            if rid not in spare_cands:
                _extra_pool.append(rid)
    if _extra_pool:
        rid = random.choice(_extra_pool)
        r8 = EQUIP_ROSTER[rid]
        q8 = r8["quality"]
        items.append({
            "rid": rid,
            "qty": _QTY_BY_QUALITY.get(q8, random.randint(2, 3)),
            "price_mult": round(random.uniform(0.8, 1.2), 1),
        })
    random.shuffle(items)
    return items


def _now_ts() -> int:
    return int(time.time())


def get_smith_stock(map_id: str, town_lv: int | None = None) -> list:
    """读时惰性刷新全服共享货架（event_state key f"smith_stock_{map_id}"，全局共享）。

    - 无存储 → 初始化 roll 并落库
    - day 与今日 ordinal 不同 → 每日 0 点换货（全量重 roll）
    - restock_at 过期 → 补货：保留未售罄件 + 补新品填满 STOCK_COUNT
    """
    key = f"smith_stock_{map_id}"
    town_lv = town_level(map_id) if town_lv is None else town_lv
    today = date.today().toordinal()
    now = _now_ts()
    raw = db.get_event_state(key)
    st = None
    if raw:
        try:
            st = json.loads(raw)
        except (ValueError, TypeError):
            st = None
    if not st or not isinstance(st, dict):
        st = {"items": roll_stock(map_id, town_lv), "day": today,
              "restock_at": now + RESTOCK_HOURS * 3600}
        db.set_event_state(key, json.dumps(st, ensure_ascii=False))
        return list(st["items"])
    items = st.get("items") or []
    if st.get("day") != today:
        # 每日 0 点换货：全量重 roll
        st = {"items": roll_stock(map_id, town_lv), "day": today,
              "restock_at": now + RESTOCK_HOURS * 3600}
        db.set_event_state(key, json.dumps(st, ensure_ascii=False))
        return list(st["items"])
    if now >= st.get("restock_at", 0):
        # 6h 补货：保留未售罄件（qty>0），补新品填满 STOCK_COUNT
        kept = [it for it in items if it.get("qty", 0) > 0]
        missing = STOCK_COUNT - len(kept)
        if missing > 0:
            have = {it["rid"] for it in kept}
            # 复用 roll 但排除已在架名册 → 用临时逻辑补抽（roll 已 exclude 静态店名册）
            lo, hi = town_lv - STOCK_WINDOW, town_lv + STOCK_WINDOW
            cands = [rid for rid, r in EQUIP_ROSTER.items()
                     if rid not in _static_shop_rids() and rid not in have
                     and r.get("source") != "重锻"  # v172 路B：重锻专属不进货架
                     and lo <= r["lv"] <= hi]
            for _ in range(missing):
                if not cands:
                    break
                rid = random.choice(cands)
                cands.remove(rid)
                r = EQUIP_ROSTER[rid]
                q = r["quality"]
                kept.append({
                    "rid": rid,
                    "qty": _QTY_BY_QUALITY.get(q, random.randint(2, 3)),
                    "price_mult": round(random.uniform(0.8, 1.2), 1),
                })
        st["items"] = kept
        st["restock_at"] = now + RESTOCK_HOURS * 3600
        db.set_event_state(key, json.dumps(st, ensure_ascii=False))
    return list(st["items"])


def _smith_equip_price(rid: str) -> int:
    """名册推导价（economy._shop_equip_price 同公式：确定性基础推导价 × 品质系数）。"""
    r = EQUIP_ROSTER[rid]
    stats = equip_stats(r["slot"], r["lv"], r["quality"])
    flavor = WEAPON_FLAVOR.get(r.get("weapon_type"), {}) if r["slot"] == "weapon" else {}
    for fk, fv in flavor.items():
        if fk == "desc" or not isinstance(fv, (int, float)):
            continue
        if fk == "crit":
            stats["crit"] = round(stats.get("crit", 0) + fv, 3)
        elif fk == "spd_fix":
            stats["spd"] = stats.get("spd", 0) + int(fv)
        elif fk == "hp_fix":
            stats["hp"] = stats.get("hp", 0) + int(fv)
        else:
            stats[fk] = stats.get(fk, 0) + int(stats.get(fk, 0) * fv)
    base = int(equip_value(stats)
               * (ECON_CONFIG["shop_equip_price_base"] + r["lv"] * ECON_CONFIG["shop_equip_price_lv"])
               * QUALITY[r["quality"]]["mult"])
    # 品质价格系数与 economy.py SHOP_EQUIP_PRICE_MULT 同源（白2.0/绿2.4/蓝3.0/紫4.0/橙5.5）
    _pm = {"white": 2.0, "green": 2.4, "blue": 3.0, "purple": 4.0, "orange": 5.5}
    return int(base * _pm.get(r["quality"], 1.5))


def smith_stock_price(rid: str, price_mult: float) -> int:
    """货架售价：名册推导价 × 浮动系数（economy 面板显示与购买同源）。"""
    return int(_smith_equip_price(rid) * price_mult)


def buy_stock_item(map_id: str, town_lv: int | None, rid: str):
    """原子扣减全服共享货架一件。

    返回 (ok, item_data, price)：
    - ok=True：qty-1 写回，item_data = C.generate_roster_equip(rid)（名字带『XX 的作品』后缀），
      price = 名册推导价 × price_mult（含浮动，rounded）
    - ok=False：未找到 / 售罄（rid 不在货架或 qty<=0）
    """
    key = f"smith_stock_{map_id}"
    town_lv = town_level(map_id) if town_lv is None else town_lv
    today = date.today().toordinal()
    now = _now_ts()
    # 惰性刷新（换货/补货）后做原子读-判-写
    raw = db.get_event_state(key)
    st = None
    if raw:
        try:
            st = json.loads(raw)
        except (ValueError, TypeError):
            st = None
    if not st or not isinstance(st, dict):
        st = {"items": roll_stock(map_id, town_lv), "day": today,
              "restock_at": now + RESTOCK_HOURS * 3600}
    items = st.get("items") or []
    if st.get("day") != today:
        st = {"items": roll_stock(map_id, town_lv), "day": today,
              "restock_at": now + RESTOCK_HOURS * 3600}
        items = st["items"]
    elif now >= st.get("restock_at", 0):
        kept = [it for it in items if it.get("qty", 0) > 0]
        missing = STOCK_COUNT - len(kept)
        if missing > 0:
            have = {it["rid"] for it in kept}
            lo, hi = town_lv - STOCK_WINDOW, town_lv + STOCK_WINDOW
            cands = [rid_ for rid_, r in EQUIP_ROSTER.items()
                     if rid_ not in _static_shop_rids() and rid_ not in have
                     and r.get("source") != "重锻"  # v172 路B：重锻专属不进货架
                     and lo <= r["lv"] <= hi]
            for _ in range(missing):
                if not cands:
                    break
                rid_ = random.choice(cands)
                cands.remove(rid_)
                r = EQUIP_ROSTER[rid_]
                q = r["quality"]
                kept.append({
                    "rid": rid_,
                    "qty": _QTY_BY_QUALITY.get(q, random.randint(2, 3)),
                    "price_mult": round(random.uniform(0.8, 1.2), 1),
                })
        st["items"] = kept
        st["restock_at"] = now + RESTOCK_HOURS * 3600
    # 原子扣减
    for it in st.get("items") or []:
        if it.get("rid") == rid and it.get("qty", 0) > 0:
            it["qty"] -= 1
            db.set_event_state(key, json.dumps(st, ensure_ascii=False))
            generate_roster_equip = _host_attr("core.drops", "generate_roster_equip")
            item = generate_roster_equip(rid)
            npc = SMITH_NPC_NAMES.get(map_id, "铁匠")
            item["name"] = f"{item['name']}（{npc}的作品）"
            price = int(_smith_equip_price(rid) * it["price_mult"])
            return True, item, price
    # 未找到或售罄：仍把当前状态落库（防陈旧）
    db.set_event_state(key, json.dumps(st, ensure_ascii=False))
    return False, None, 0
