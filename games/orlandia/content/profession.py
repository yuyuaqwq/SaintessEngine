# -*- coding: utf-8 -*-
"""包内生活副业域（`content/profession.py`）—— 真源 `game/services/profession.py`（958 行）**逐字端口**。

真源（游戏仓 `qqbot/data/plugins/dragonfall`，**只读**）
--------------------------------------------------------
| 真源 | 行数 | 本文件搬什么 |
|---|---:|---|
| `game/services/profession.py` | 958 | **全文件**：挖矿疲劳常量 + 限定采集条件词注册表 + `gather_roll`/`gather_cond_roll` + 等待型副业状态机（`prof_wait_*` / `prof_settle` / `prof_wait_flow` / `prof_delayed_push`）+ 结算三件套（`settle_fishing` / `fishing_surprise_fn` / `collect_bonus_line` / `settle_gather` / `settle_mining`）+ 疲劳三件套 |

宿主耦合替身（**只改两类东西**：① 存储层 import 口 ② 读表口）
--------------------------------------------------------------
| 真源写法 | 包内写法 | 说明 |
|---|---|---|
| `from .. import db`（**函数体内**惰性 import） | 模块级 `db` = **惰性宿主代理** `_HostDB` | 正文里 `db.xxx(...)` **一行未改**；宿主由 `bind_host(db)` 注入，或按 `sys.modules` 找**已加载**的宿主模块（绝不 import，防在包侧另起一份宿主模块树） |
| `from .. import content as C`（模块级） | 模块级 `C` = **惰性宿主代理** `_HostMod` | 表读口（`MATERIALS`/`MAP_BY_ID`/`PROF_WAIT_BASE`/`price_band`/`roll_fish`/`RARE_MATERIAL_PRICE`/`DROP_POOLS` 派生…）仍在宿主内容聚合层；这些**域未进包**（fishing/gather 数据域的死角见报告 §缺口）。宿主在 import 期注入同一模块对象 |
| `from ..core import timed_events as _te`（模块级） | 模块级 `_te` = **包内**惰性句柄 `PkgModule("content.timed_events")`（★ P4′-W1-B） | `get_timed`/`set_timed`/`remove_timed` 三处调用名未改；宿主 `game.core.timed_events` 是**别名壳**（`sys.modules[__name__] = content.timed_events`）⇒ 逐字同一个模块对象 |
| `from ..log_setup import LOG`（模块级） | 告警改走**包内唯一日志取用口** `content/obs.py::log()`（★ P4′-W1-B；句柄由宿主 `bootstrap.bind_observability()` 在包加载期注入） | fail-closed **告警原文未改**，取用写法由 `LOG.warning` 改 `obs.log().warning`；包内不再出现第二个日志口 |
| `from ..drop_engine import expand_pool as _expand`（**函数体内**惰性 import，两处） | 模块级 `_expand` / `_expand_pool` = **惰性调用代理** | 每次调用解析宿主 `game.drop_engine.expand_pool`（与真源同：真源也是调用时才 import） |
| **模块级副作用** `_te.register_timed("prof_wait", …, on_expire=prof_wait_expire_cb)` | **留在宿主薄壳**（`game/services/profession.py`）注册，回调指向本模块的 `prof_wait_expire_cb` | 包被 `package_apply()` import 时宿主 `content`/`timed_events` 未必就绪；注册时机必须与真源一致（宿主模块 import 期）。回调体在本模块 |
| **模块级启动校验** `validate_gather_cond()`（import 期 fail-fast） | 函数体在本模块；**调用点留在宿主薄壳 import 期** | 同上：真源在宿主模块 import 时校验，行为逐字保持（异常文本也逐字相同） |

不变式
------
* 全部函数体逐行照搬（含注释/变量名/日志文本）；只删掉「宿主 import 口」那一行。
* `prof_wait_key` 的 `group_id` 兼容参数、`prof_wait_compat` 的三种缺键补齐、`settle_fishing`
  四个分支的文案拼接顺序、`fishing_surprise_fn` 的「图纸池空 → 不额外吃随机」等**全部原样**。
* 随机数消费序列与真源完全一致（同 seed 同结果）—— 快照脚本 `overnight/b9_l4_snap.py` 逐字节对拍。

用法::

    from content import profession as P
    P.bind_host(db, content=C, timed=_te, log=LOG, expand_pool=expand_pool)   # 宿主薄壳注入
    #   ★ P4′-W1-B 后 `timed` / `log` 仍可按协议传（形参在、值被忽略）；`_te` 已是包内句柄
    mats = P.gather_roll(20, 5, "oak_plain")
"""
from __future__ import annotations

import asyncio
import json
import random
import time

# ---- B14-2 L5：数据名读点切包内门面（`C.<数据名>` → 门面直取；函数名/缺口名仍留 `C.<名>`）----
from . import catalog_core as _cc     # 常量/职业/种族/面板公式
from . import catalog_items as _ci    # 物品/材料/符文/装备名册
from . import catalog_life as _cl     # 生活/副业/商店/宠物/经济配置
from . import catalog_space as _sp    # 地图/子区域
from . import catalog_b143 as _b143   # B14-3 收口名（FISH_EXP/QUALITY —— 原缺口名已建域）
from .prof_config import price_band  # ★ B15b：宿主函数进包（原 `C.price_band`，宿主已无对象）
# ★ P4′-W1-B（包侧去 shim）：① 包内惰性模块句柄（旧 `_HostMod` 的包内等价物；零依赖，
#   取件时机逐字相同 = 属性访问时解析）② 包内唯一日志取用口 `content/obs.py`。
from ._pkgref import PkgModule as _PkgModule
from . import obs
# ---- B14-2 L5 读点切换（2026-09-14）----
# 数据名读点（MATERIALS/RUNES · MAP_BY_ID · PROF_WAIT_BASE/PROF_WAIT_DECAY/PROF_WAIT_FLOOR/
# MINING_KEYWORDS/RARE_MATERIAL_PRICE · PET_EGG_ORANGE_CHANCE/PROF5_BONUS_CHANCE/RARE_MAT_CHANCE）
# 已切包内门面（见文件头 `_cc/_ci/_cl/_sp` import 块）。
# 仍留 `C.<名>` 的只有：① 宿主函数（price_band/roll_fish/check_achievements/make_pet_egg/…）
# ② 域缺口 `GATHER_COND_POOLS`（`getattr(C,…)` 形式，扫描器不计）——见 overnight/W-B14-2-L5.md §残余。
# ★ B14-3（2026-09-14）：FISH_EXP/QUALITY 两名已由门面 `catalog_b143` 补上 → 2 处切 `_b143`。

# ============================================================
# 宿主替身口（① 存储层 / ② 读表口；② 由宿主薄壳在 import 期注入同一模块对象）
# ============================================================
_HOST_DB = None            # 宿主存储层（真源 `from .. import db`）
_HOST_CONTENT = None       # 宿主内容聚合层（真源 `from .. import content as C`）
_HOST_EXPAND = None        # 宿主产出池展开函数（真源 `from ..drop_engine import expand_pool`）

# 宿主模块名（运行时 `main.py` 的模块路径 = `data.plugins.dragonfall`；测试同样）
_HOST_PKG = "data.plugins.dragonfall.game"
_HOST_PKG_FALLBACK = "game"


def bind_host(db=None, content=None, timed=None, log=None, expand_pool=None):
    """宿主替身注入（幂等；宿主薄壳 `game/services/profession.py` 在 import 期调用）。

    ★ P4′-W1-B：`timed` / `log` 两个形参按宿主薄壳的注入协议**保留**
      （`game/services/profession.py:57` 逐个关键字传参 —— 少了会 TypeError），
      但包内已不再持有它们的槽位：倒计时引擎改指包内 `content/timed_events.py`（`_te`），
      日志改走包内唯一取用口 `content/obs.py`。传进来的值被显式忽略。
    """
    global _HOST_DB, _HOST_CONTENT, _HOST_EXPAND
    if db is not None:
        _HOST_DB = db
    if content is not None:
        _HOST_CONTENT = content
    if expand_pool is not None:
        _HOST_EXPAND = expand_pool


def lazy_module(getter):
    """把「宿主模块取用 thunk」包成一个懒模块对象（宿主薄壳用它注入 `T`：真源 `from ..core import texts as T`）。"""
    return _LazyModule(getter)


def _resolve_host(mod: str):
    """取宿主子模块：**已加载**的宿主模块（`sys.modules`，绝不 import）。"""
    import sys
    for name in ("%s.%s" % (_HOST_PKG, mod), "%s.%s" % (_HOST_PKG_FALLBACK, mod)):
        m = sys.modules.get(name)
        if m is not None:
            return m
    raise RuntimeError("profession：宿主模块 %s 不可用（未 bind_host 且未加载）—— 拒绝静默空跑" % mod)


class _LazyModule(object):
    """懒模块代理（`getter()` → 宿主模块；属性访问时才取）。"""

    def __init__(self, getter):
        self._getter = getter

    def __getattr__(self, name):
        return getattr(self._getter(), name)


class _HostMod(object):
    """惰性宿主模块代理 —— `C.xxx` / `_te.xxx` / `LOG.xxx` 正文一行不动，属性访问时解析。"""

    def __init__(self, slot, mod):
        self._slot = slot
        self._mod = mod

    def _target(self):
        obj = self._slot()
        return obj if obj is not None else _resolve_host(self._mod)

    def __getattr__(self, name):
        return getattr(self._target(), name)


class _HostDB(object):
    """惰性宿主存储层代理（真源 `from .. import db`）。"""

    def __getattr__(self, name):
        return getattr(_HOST_DB if _HOST_DB is not None else _resolve_host("db"), name)


db = _HostDB()
C = _HostMod(lambda: _HOST_CONTENT, "content")
# ★ P4′-W1-B：倒计时引擎改指**包内实现**。宿主 `game.core.timed_events` 是别名壳
#   （`sys.modules[__name__] = content.timed_events`）⇒ 与旧 `_te` 解析到的是**同一个模块
#   对象 / 同一批函数对象**；但包内不再经宿主命名空间取件。`PkgModule` 每次属性访问解析一次，
#   与旧 `_HostMod` 的取件时机逐字相同。
_te = _PkgModule("content.timed_events")


def _expand(*args, **kwargs):
    """产出池展开（真源 `from ..drop_engine import expand_pool`，函数体内惰性 import）。"""
    if _HOST_EXPAND is not None:
        return _HOST_EXPAND(*args, **kwargs)
    return getattr(_resolve_host("drop_engine"), "expand_pool")(*args, **kwargs)


_expand_pool = _expand


# ============================================================
# 真源正文（逐字；只删掉宿主 import 口那一行）
# ============================================================
# ============ 模块常量（economy.py 原样随迁） ============

# v105 M14 评估实现（19 章 §2.2 挖掘疲劳值）：连续挖掘 N 次进入疲劳，
# 疲劳期间稀有矿脉概率减半；10 分钟不挖掘自动恢复（与体力自然恢复节奏一致）。
# 存储用 event_state（mining_fatigue_{qq_id}），无 schema 变更。
MINING_FATIGUE_THRESHOLD = 5    # 连续挖掘 5 次进入疲劳
MINING_FATIGUE_RECOVER = 600    # 距上次挖掘超过 600s（10 分钟）计数重置

# v125.2 fail-closed：限定采集条件词注册表（GATHER_COND_POOLS 条件串 split('+') 后的词）。
# 判定统一走注册表：未收录词 → 本条不命中 + 告警日志（防拼写错误被静默放行造成
# 语义反转——旧实现未知词 ok 保持 True，新增 "fog" 等词反而必出）。
_GATHER_COND_CHECKERS = {
    "night": lambda period, season, weather: period == "night",
    "morning": lambda period, season, weather: period == "morning",
    "winter": lambda period, season, weather: season == "winter",
    "rain": lambda period, season, weather: weather == "rain",
}

# v125.2 启动校验：GATHER_COND_POOLS 全部条件词必须 ∈ 注册表（数据拼写错误启动即暴露，
# 与 data/__init__.py B4 池 id 校验同款 fail-fast 风格）


def validate_gather_cond():
    """v125.2 启动校验封装：GATHER_COND_POOLS 全部条件词必须 ∈ 注册表
    （数据拼写错误启动即暴露）。service 模块 import 时执行一次；命令层 economy
    模块 import/reload 时同样调用（P4-7 迁走后保持原 fail-fast 行为）。"""
    for _cond_map_id, _cond_entries in getattr(C, "GATHER_COND_POOLS", {}).items():
        for _cond_mid, _cond_w, _cond_str in _cond_entries:
            for _tok in str(_cond_str).split("+"):
                if _tok not in _GATHER_COND_CHECKERS:
                    raise RuntimeError(
                        f"[dragonfall] GATHER_COND_POOLS[{_cond_map_id}] 条件词 {_tok!r} 未注册"
                        f"（材料 {_cond_mid}）——请修正拼写或补入 _GATHER_COND_CHECKERS")



# ============ v168.2 垂钓惊喜盲盒（鱼鱼 2026-09-03 拍板，原 economy 类属性随迁） ============
# 惊喜不绑定宝箱：每次垂钓结算在既有内容之外做一次「惊喜判定」，按本次鱼获品质给概率：
#   白(垃圾)/0% · 绿 2% · 蓝 5% · 紫(含陈旧的宝箱) 15% · 鱼王/橙 30%
#   彩蛋收藏鱼命中 → 必给惊喜且升级「传说档」（必橙装）
# 惊喜内容池（按玩家等级合理出，克制不膨胀）：图纸 30% / 装备 25% / 稀有符文 20% /
# 原石宝石 15% / 罕见材料 10%。档位互斥、一杆最多一条惊喜；命中触发但内容池意外全空时
# 静默跳过（不喧宾夺主，也不造一句假惊喜）。
FISHING_SURPRISE_TRIGGER = {  # 鱼获品质 → 惊喜触发率
    "white": 0.0, "green": 0.02, "blue": 0.05, "purple": 0.15, "orange": 0.30,
}
# 内容池档位边界（累积）：图纸 30% / 装备 55% / 符文 75% / 宝石 90% / 罕见材料 100%
FISHING_SURPRISE_BP = 0.30
FISHING_SURPRISE_EQ = 0.55
FISHING_SURPRISE_RUNE = 0.75
FISHING_SURPRISE_GEM = 0.90


# ============ timed_events on_expire 注册（economy.py:53 原样随迁，模块顶层） ============

def prof_wait_expire_cb(group_id, qq_id, data):
    """v127.5 意见#6：引擎 refresh 物理删除到点 prof_wait 前的数据保全。

    把 {finish,type,spot_map} 平移到历史遗留键 prof_wait_{qq_id}，供
    prof_wait_residual 下次读取 → prof_wait_flow 惰性结算（入包+播报）。
    幂等：结算后 prof_wait_clear 清空该键，无双结算；重复触发仅覆盖同结构数据。
    """
    try:
        st = dict(data or {})
        if st.get("finish") and st.get("type") in ("gather", "fishing", "mining"):
            db.set_event_state(f"prof_wait_{qq_id}", json.dumps(st, ensure_ascii=False))
    except Exception:
        pass




# ============ 采集掷池（economy._gather_roll / _gather_cond_roll 原样随迁） ============

def gather_roll(level: int, prof_lv: int = 1, cur_map: str = "") -> list:
    """按等级采集材料：地图绑定池优先（19 章 §2.1）；未配置地图按地图等级价格区间兜底；
    副业等级提高产出数量与稀有度。

    v174 统一抽象：有地图池时走 drop_engine（数据源 DROP_POOLS）；无池走价格带兜底。
    """
    import random as _rnd
    cand = []
    _expanded = _expand(f"gather:{cur_map or ''}")
    if _expanded:
        cand = list(_expanded)
    else:
        # v97.2 兜底：按地图等级映射价格区间（修复原逻辑 Lv50+ 采不到 500+ 材料的问题）
        # v104 R3 M14 P1-2：兜底池排除强化石类消耗品（i_stone_* 是炼金/商店独占，禁止采集白嫖）
        # v125.2 B3：价格带公式数据下沉 prof_config.price_band（原 3+lv*4 / 20+lv*12 双处字面量）
        _map_lv = _sp.MAP_BY_ID.get(cur_map or "", {}).get("lv", level)
        _lo, _hi = price_band(_map_lv)
        cand = [name for name, m in _ci.MATERIALS.items()
                if _lo <= m["price"] <= _hi
                and name not in ("i_stone_upgrade", "i_stone_refine")]
        if not cand:
            # 空区间放宽为"全价段"，保证高等级副本/隐藏区域也有产出
            cand = [name for name, m in _ci.MATERIALS.items()
                    if m["price"] <= _hi
                    and name not in ("i_stone_upgrade", "i_stone_refine")]
        if not cand:
            cand = [n for n in _ci.MATERIALS
                    if n not in ("i_stone_upgrade", "i_stone_refine")]
    # v102.3 限定采集物（时机钩子）：当前时段/季节/天气命中 → 低权重追加
    special = gather_cond_roll(cur_map or "")
    if special:
        cand = cand + [special] if special not in cand else cand
    # 副业等级加成：Lv.3+ 概率采到 2 份材料；Lv.6+ 概率 3 份
    n = _rnd.randint(1, 2)
    if prof_lv >= 3 and _rnd.random() < 0.3:
        n += 1
    if prof_lv >= 6 and _rnd.random() < 0.25:
        n += 1
    return [_rnd.choice(cand) for _ in range(n)] if cand else []


def gather_cond_roll(cur_map: str):
    """v102.3 限定采集物判定：返回命中的材料 ID（未命中返回 None）。

    条件：night=20:00-05:00 / morning=05:00-08:00 / winter=冬季 / rain=雨天；
    组合条件用 '+'（如 "winter+night" 需全部命中）。命中后按权重随机选一个。
    v125.2 fail-closed：条件词查 _GATHER_COND_CHECKERS 注册表，未收录词
    本条不命中 + 告警日志（防未知词静默放行导致语义反转：新词反而必出）。
    """
    import random as _rnd
    pool = getattr(C, "GATHER_COND_POOLS", {}).get(cur_map or "")
    if not pool:
        return None
    period = C.current_period()
    season = C.current_season()
    weather = C.today_weather(cur_map or None)
    hit = []
    for mid, w, cond in pool:
        ok = True
        for p in str(cond).split("+"):
            chk = _GATHER_COND_CHECKERS.get(p)
            if chk is None:
                # fail-closed：未知条件词 → 本条不命中 + 告警（防语义反转）
                ok = False
                obs.log().warning(
                    "[dragonfall] 采集条件词 %r 未注册（地图 %s 材料 %s），fail-closed 不命中——"
                    "请检查 GATHER_COND_POOLS 或 _GATHER_COND_CHECKERS", p, cur_map, mid)
                continue
            if not chk(period, season, weather):
                ok = False
        if ok:
            hit.extend([mid] * w)
    if not hit:
        return None
    return _rnd.choice(hit)


# ============ 等待型副业状态机（v55：垂钓/采集/挖掘；v127.5 懒计时引擎收编） ============
# 基准等待（秒）随机范围：fish/gather 45~75，mining 65~115；副业等级每级 -5%（上限 -50%），保底 10 秒

def prof_wait_key(group_id, qq_id):
    # v83: 去掉 group_id —— 等待型副业按玩家全局互斥，防止跨群双开多刷
    # v127.5：仅保留作为历史遗留键（v127.5 前的在途等待迁移/清理用），主体存储已走引擎
    return f"prof_wait_{qq_id}"


def prof_wait_ev_name(qq_id):
    # timed_events 引擎的玩家事件存储 key（与 engine 内部 _PLAYER_KEY 同一模板）
    return f"timed_events_{qq_id}"


def prof_wait_compat(ev):
    """引擎事件 → 兼容 st 形状 {finish,type,…extra}（data 平铺 + finish/type 补齐）"""
    st = dict(ev.get("data") or {})
    if not st.get("finish"):
        st["finish"] = ev.get("expire")
    if st.get("type") is None:
        st["type"] = ev.get("type")
    return st if st.get("finish") else None


def prof_wait_residual(group_id, qq_id):
    """非破坏读『到点但未结算』的残留等待数据（惰性结算兜底数据源）。

    v127.5：引擎 expire = 完成时间，到点即被 get_timed/_maint_gate refresh 惰性清除；
    但结算需要事件数据（type/spot/spot_map/finish），清除即丢 → 从这里按引擎存储布局
    非破坏回读残留（不清除），供 prof_wait_flow/prof_delayed_push/prof_forget 兜底。
    顺序：timed_events 引擎残留 → v127.5 前历史遗留 prof_wait_{qq}（迁移）。
    """
    raw = db.get_event_state(prof_wait_ev_name(qq_id))
    if raw:
        try:
            d = json.loads(raw)
        except (ValueError, TypeError):
            d = None
        ev = ((d or {}).get("prof_wait")) if isinstance(d, dict) else None
        if isinstance(ev, dict):
            st = prof_wait_compat(ev)
            if st:
                return st
    # v127.5 前历史遗留键（旧格式 {finish,type,…extra}）——迁移兜底
    raw = db.get_event_state(prof_wait_key(group_id, qq_id))
    if not raw:
        return None
    try:
        st = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if isinstance(st, dict) and st.get("finish"):
        return st
    return None


def prof_wait_state(group_id, qq_id):
    """读取进行中的等待型副业状态(无/损坏返回 None)。v127.5 改走 timed_events 引擎。

    未过期 → 兼容 st 形状 {finish,type,…extra}（data 平铺 + finish=expire）；
    已到点/无 → None（引擎 lazy 清除，与惰性语义一致——到点即视为不在等待中）。
    注意：调用方如需结算『到点但未结算』的数据，用 prof_wait_residual。
    """
    raw = _te.get_timed(group_id, qq_id, "prof_wait")
    if not raw:
        return None
    return prof_wait_compat(raw)


def prof_wait_clear(group_id, qq_id):
    _te.remove_timed(group_id, qq_id, "prof_wait")
    # 顺手清历史遗留键，防 v127.5 前残留状态串台
    db.set_event_state(prof_wait_key(group_id, qq_id), "")


def prof_wait_duration(prof_type, prof_lv):
    """等待时长：基准随机范围 ±25%，副业等级每级－5%(上限－50%)，保底 10 秒
    v125：衰减/保底数据下沉 prof_config.PROF_WAIT_DECAY / PROF_WAIT_FLOOR"""
    low, high, _ = _cl.PROF_WAIT_BASE[prof_type]
    wait = random.randint(low, high)
    wait = int(wait * (1 - _cl.PROF_WAIT_DECAY * min(prof_lv, 10)))
    return max(wait, _cl.PROF_WAIT_FLOOR)


def prof_wait_begin(group_id, qq_id, prof_type, extra=None, *,
                    delayed_push=None, duration=None):
    """开始一轮等待型副业：挂 timed_events 引擎倒计时 + 尽力而为的延迟推送(失败由惰性结算兜底)。

    v127.5：set_timed(key="prof_wait", type_key="prof_wait", duration_sec=wait)
    → 引擎 expire = 真实完成时间；data 平铺 {finish,type,…extra} 供结算取用。

    命令层能力注入（§2.4）：delayed_push=命令层 async 推送壳（收 group_id/qq_id/st/wait），
    由命令层内部 create_task(self._prof_delayed_push(...))；缺省 None = 不推送
    （无事件循环/测试环境 → 惰性结算兜底，与原 try/except 静默等价）。
    duration=等待时长注入（收 prof_type/prof_lv → 秒；测试 monkeypatch 经命令层壳转发，
    等价原 economy 直接改 self._prof_wait_duration 的测试手法）；缺省 None 走模块实现。
    """
    prof_lv = db.get_prof_level(group_id, qq_id, prof_type)
    if duration is not None:
        wait = duration(prof_type, prof_lv)
    else:
        wait = prof_wait_duration(prof_type, prof_lv)
    finish = int(time.time()) + wait
    data = {"finish": finish, "type": prof_type}
    if extra:
        data.update(extra)
    _te.set_timed(group_id, qq_id, key="prof_wait", type_key="prof_wait",
                  data=data, duration_sec=wait)
    # 历史遗留键清空：新轮已挂引擎，防止 v127.5 前残留/测试残留后续被 residual 误读
    db.set_event_state(prof_wait_key(group_id, qq_id), "")
    st = dict(data)  # 兼容形状（延迟推送/结算用）
    try:
        asyncio.get_running_loop()
        if delayed_push is not None:
            delayed_push(group_id, qq_id, st, wait)
    except Exception:
        pass  # 无事件循环（测试环境）或任务创建失败 → 惰性结算兜底
    return wait


async def prof_delayed_push(group_id, qq_id, st, wait, *, settle=None, send=None):
    """延迟结算并主动推送结果(尽力而为；进程重启/推送失败由惰性结算兜底)。

    v127.5：到点后引擎已 lazy 清除事件，结算数据从 prof_wait_residual（引擎存储残留）取。
    settle：结算注入（收 group_id/qq_id/st → 文本）；send：推送注入（收 text，命令层
    event.send(MessageChain([Plain(text)])) 壳）——缺省 None 不推送（service 不 import
    commands._platform，纯 I/O 留命令层，行为与原 economy._prof_delayed_push 等价）。
    """
    try:
        await asyncio.sleep(wait)
        cur = prof_wait_state(group_id, qq_id) or prof_wait_residual(group_id, qq_id)
        if not cur or cur.get("finish") != st.get("finish"):
            return  # 已被惰性结算/开新轮
        text = ""
        if settle is not None:
            text = settle(group_id, qq_id, cur)
        if text and send is not None:
            await send(text)
    except Exception:
        pass


def prof_settle(group_id, qq_id, st, *,
                rule_fire=None,
                settle_fishing=None, settle_gather=None, settle_mining=None,
                clear=None):
    """结算等待型副业(入包/经验/每日任务)，返回结果文本；先清状态防双结算

    rule_fire：命令层 v97.5 行为彩蛋（rule_engine.fire 封装）注入，收
    (trigger, group_id, qq_id, player, cur_map, evt) → 文本；缺省 None 不触发彩蛋
    （原 self._rule_fire 恒由命令层提供；service 缺省 = 不触发，无副作用）。
    settle_fishing/gather/mining：命令层结算转发注入；clear：命令层清状态注入。
    """
    if clear is not None:
        clear(group_id, qq_id)
    else:
        prof_wait_clear(group_id, qq_id)
    prof_type = st.get("type")
    if prof_type == "fishing":
        text = settle_fishing(group_id, qq_id, st) if settle_fishing else None
    elif prof_type == "gather":
        text = settle_gather(group_id, qq_id, st) if settle_gather else None
    elif prof_type == "mining":
        text = settle_mining(group_id, qq_id, st) if settle_mining else None
    else:
        return None
    if text:
        # v97.5 行为彩蛋规则：副业结算后（采集/挖掘/垂钓统一挂点）
        _p = db.get_player(group_id, qq_id)
        _cm = _sp.MAP_BY_ID.get(_p.get("cur_map"), {}) if _p else {}
        if rule_fire is not None:
            _rule_txt = rule_fire("gather_done", group_id, qq_id, _p, _cm, {"event": prof_type})
            if _rule_txt:
                text += "\n" + _rule_txt
    return text


def prof_wait_flow(group_id, qq_id, prof_type, extra=None, begin_text="", *,
                   settle=None, begin=None):
    """等待型副业统一流程：进行中→提示剩余；到期→先结算再开新一轮；无→开新一轮。
    返回 (回复文本, 是否开启新一轮)。

    v127.5 惰性结算兜底：引擎 expire=完成时间，到点事件已被 get_timed/_maint_gate
    refresh lazy 清除，旧轮结算数据只剩引擎存储残留可取 → 先 prof_wait_residual
    非破坏读一次再走 prof_wait_state，防『到点但未结算』被吞（奖励丢失）。

    settle/begin：命令层结算/开轮注入（收 group_id/qq_id/…）；缺省 None 时回退
    本模块纯实现（prof_settle/prof_wait_begin，等价 economy 原自调用）。
    """
    _settle = settle or (lambda g, q, s: prof_settle(g, q, s))
    _begin = begin or (lambda g, q, pt, ex: prof_wait_begin(g, q, pt, ex))
    leftover = prof_wait_residual(group_id, qq_id)
    st = prof_wait_state(group_id, qq_id)
    now = int(time.time())
    if st and st["finish"] > now:
        left = st["finish"] - now
        tname = _cl.PROF_WAIT_BASE.get(st["type"], (0, 0, "副业"))[2]
        return f"⏳ 你还在{tname}呢，再有 {left} 秒就完成啦～(完成会自动入包)", False
    settle_text = None
    if st:
        settle_text = _settle(group_id, qq_id, st)
    elif leftover and int(leftover.get("finish", 0)) <= now:
        # 到点但引擎已惰性清 → 残留数据结算（防吞旧轮产出）
        settle_text = _settle(group_id, qq_id, leftover)
    wait = _begin(group_id, qq_id, prof_type, extra)
    head = f"{settle_text}\n" if settle_text else ""
    return f"{head}{begin_text}{wait} 秒后完成，自动入包～", True


def settle_fishing(group_id, qq_id, st, *, hooks=None,
                   collect_bonus=None, fishing_surprise=None,
                   daily_prof_bump=None):
    """垂钓结算（economy._settle_fishing 原样随迁，逐行等价）。

    hooks 注入（§2.4）：hooks={"legend": callable} 传说档全服广播（鱼王出水/古代鱼骨，
    callable 收 group_id/qq_id/player/fname/spot），缺省无副作用（等价原
    _fish_legend_broadcast 在测试/无广播环境的静默）。
    collect_bonus/fishing_surprise：命令层注入（收 (group_id, qq_id, player, …)），
    缺省 None 时回退本模块纯实现（collect_bonus_line / fishing_surprise 同体）。
    daily_prof_bump：每日副业任务推进注入（收 group_id/qq_id/tkey → (done,msg)）。
    """
    player = db.get_player(group_id, qq_id)
    if not player:
        return None
    prof_lv = db.get_prof_level(group_id, qq_id, "fishing")
    spot = st.get("spot", "水边")
    # v102.3 鱼饵：使用鱼饵后本次垂钓品质/品种加权（一次性，结算后清除）
    bait = None
    bait_line = ""
    _braw = db.get_event_state(f"bait_{qq_id}")
    if _braw:
        try:
            _b = json.loads(_braw)
            # v104 R3 M15 P2-4：鱼饵 24 小时过期——挂饵后长期不垂钓不再无限期生效
            # （挂饵时写入 ts，读取时校验；无 ts 的历史状态视为未过期——一次性消耗不构成长期滞留）
            if isinstance(_b, dict) and _b.get("ts") and time.time() - float(_b["ts"]) > 86400:
                _b = None
            bait = _b.get("kind") if _b else None
        except (ValueError, TypeError):
            bait = None
        db.set_event_state(f"bait_{qq_id}", "")
        if bait:
            _bait_cn = {"glow": "萤光鱼饵", "dough": "面团鱼饵", "blood": "血饵"}
            bait_line = f"\n✨ 鱼饵【{_bait_cn.get(bait, bait)}】生效了！"
    # v83 16 章 4.x：彩蛋收藏鱼（独立判定，纯收藏惊喜）
    _cf = C.roll_collect_fish(st.get("spot_map"), C.current_period() == "night")
    # 9.3：钓点差异化（禁出档位 + 品种限定水域），roll_fish 按 16 章五档权重表；v102.3 带鱼饵
    fish = C.roll_fish(prof_lv, st.get("spot_map"), bait)
    db.bump_fishing(group_id, qq_id)
    fname = fish["name"]
    fq = fish.get("quality", "white")
    # 品质标记：白档不显示，绿/蓝/紫/橙 ✦品质（16 章 1.1 定稿）
    q_mark = "" if fq == "white" else f"✦{_b143.QUALITY.get(fq, {}).get('name', fq)}"
    q_name = f"{q_mark}·{fname}" if q_mark else fname
    # 垂钓经验：白 1 / 绿 1 / 蓝 2 / 紫 3 / 橙 5（16 章 2.6）
    f_exp = _b143.FISH_EXP.get(fq, 1)
    # 出货文案按档位（16 章 2.6）
    _catch_line = {
        "blue": "水面泛起奇异的光晕…",
        "purple": "鱼线猛地绷紧！",
        "orange": "一道金光破水而出——",
    }.get(fq, "")
    catch_pre = f"{_catch_line}\n" if _catch_line else ""
    # 鱼王：全服公告 + 鱼王计数（v168.2：鱼王/橙档惊喜层统一在下方普通路径收尾判定）
    if fish["type"] == "鱼王":
        db.bump_fish_king(group_id, qq_id)
        gold = 300 + player["level"] * 10
        db.update_player(group_id, qq_id, gold=player["gold"] + gold)
        new_lv, leveled = db.add_prof_exp(group_id, qq_id, "fishing", f_exp)
        lv_msg = f"\n🌟 垂钓等级提升到 Lv.{new_lv}！" if leveled else ""
        # v104 M15 修复：鱼王分支同样推进每日副业任务（原漏计）
        if daily_prof_bump is not None:
            _done, _msg = daily_prof_bump(group_id, qq_id, "fishing")
            lv_msg += _msg
        # 阶段九：垂钓次数 + 鱼王成就
        db.bump_stats(group_id, qq_id, fish_count=1)
        C.check_achievements(group_id, qq_id, player, {"fish_king": True})
        # v104 R3 M15 P2-1：鱼王出水全服广播（13 章 2.6 传说档广播）
        _legend = (hooks or {}).get("legend")
        if _legend is not None:
            _legend(group_id, qq_id, player, fname, spot)
        _cf_fn = collect_bonus if collect_bonus is not None else collect_bonus_line
        _cf_line = _cf_fn(group_id, qq_id, player, _cf)
        # v168.2：鱼王也走统一惊喜层（鱼王 type=鱼王、quality=orange → 橙档 30% 触发；
        # 若同杆还中了彩蛋收藏鱼（force_legend）则直接传说档必橙装，不重复 roll）
        _sv_fn = fishing_surprise if fishing_surprise is not None else fishing_surprise_fn
        _sv_line = _sv_fn(group_id, qq_id, player, fish, force_legend=bool(_cf))
        return (f"🐉 天啊！你在{spot}钓上了【{q_name}】！！\n"
                f"鱼王出水，水波震荡，岸边的旅人都看呆了！\n"
                f"💰 获得 {gold} 金币的赏金！{_sv_line}{lv_msg}\n"
                f"📜 你的图鉴记下了这传说的一笔……{_cf_line}{bait_line}")
    # 宝物宝箱：立即开（金币保底；惊喜层由收尾统一判定，v168.2 垂钓盲盒不再独占图纸档）
    # 宝箱本体不入包（type=宝物 无售价，MATERIALS 已登记 price=0）；金币即其固定内容
    if fish["type"] == "宝物":
        gold = random.randint(30, 80) + player["level"] * 3
        db.update_player(group_id, qq_id, gold=player["gold"] + gold)
        new_lv, leveled = db.add_prof_exp(group_id, qq_id, "fishing", f_exp)
        lv_msg = f"\n🌟 垂钓等级提升到 Lv.{new_lv}！" if leveled else ""
        # v104 M15 修复：宝物分支同样推进每日副业任务（原漏计）
        if daily_prof_bump is not None:
            _done, _msg = daily_prof_bump(group_id, qq_id, "fishing")
            lv_msg += _msg
        db.bump_stats(group_id, qq_id, fish_count=1)
        C.check_achievements(group_id, qq_id, player)
        # 宝箱本体不再入包（type=宝物 固定内容=金币）；惊喜层在收尾统一判定
        _cf_fn = collect_bonus if collect_bonus is not None else collect_bonus_line
        _cf_line = _cf_fn(group_id, qq_id, player, _cf)
        # v168.2：宝物箱也走统一惊喜层（type=宝物 quality=purple → 紫档 15% 触发；
        # 若同杆还中了彩蛋收藏鱼 force_legend=True → 直接传说档必橙装）
        _sv_fn = fishing_surprise if fishing_surprise is not None else fishing_surprise_fn
        _sv_line = _sv_fn(group_id, qq_id, player, fish, force_legend=bool(_cf))
        return (f"{catch_pre}🎣 你在{spot}钓上来了一个【{q_name}】！\n"
                f"打开一看：💰 {gold} 金币！{_sv_line}{_cf_line}{lv_msg}{bait_line}")
    # 垃圾：直接报（type=垃圾 恒 white 档——惊喜触发率 0%，不走收尾惊喜层；
    # 收藏鱼 _cf 彩蛋走 collect_bonus_line 入图鉴，纯收藏不触发惊喜档）
    if fish["type"] == "垃圾":
        new_lv, leveled = db.add_prof_exp(group_id, qq_id, "fishing", f_exp)
        lv_msg = f"\n🌟 垂钓等级提升到 Lv.{new_lv}！" if leveled else ""
        # v104 M15 修复：垃圾分支同样推进每日副业任务（原漏计）
        if daily_prof_bump is not None:
            _done, _msg = daily_prof_bump(group_id, qq_id, "fishing")
            lv_msg += _msg
        db.bump_stats(group_id, qq_id, fish_count=1)
        C.check_achievements(group_id, qq_id, player)
        _cf_fn = collect_bonus if collect_bonus is not None else collect_bonus_line
        _cf_line = _cf_fn(group_id, qq_id, player, _cf)
        return f"🎣 你在{spot}钓上来一个【{q_name}】……唉，今天的运气不太好。{lv_msg}{_cf_line}{bait_line}"
    # 鱼/材料入背包（9.3：mat_ ID 入包 + quality 字段，16 章 2.7 禁动态中文 key）
    mat_key = C.resolve("materials", fname)
    # v126.2 个体属性 tags：roll 尺寸/重量 → 随 add_item 入包（tag 存 item_data.tags，
    # 出售按 FIFO 加权"大鱼更贵"，任务扣料 remove_item 自动同步截断）
    _sw = C.roll_fish_size_weight(fish)
    db.add_item(group_id, qq_id, mat_key,
                {"name": fname, "type": fish["type"], "stackable": True,
                 "price": fish["price"], "quality": fq},
                tag=_sw)
    if _sw:
        _size_line = f"（{_sw['size']:.1f}cm/{_sw['weight']}kg）"
    else:
        _size_line = ""
    # ============ v168.2 垂钓惊喜层（鱼鱼 2026-09-03 拍板） ============
    # 惊喜不绑定宝箱：鱼获品质→触发率（白/垃圾 0%·绿 2%·蓝 5%·紫 15%·鱼王/橙 30%；
    # 彩蛋收藏鱼命中→必给且升级传说档=必橙装），与图纸/宠物蛋/坐骑等既有产出互相独立。
    # 走到这里的 = 普通鱼/材料（鱼王/宝物/垃圾分支各自 return 且已含惊喜行）。
    _sv_line = ""
    if fq not in ("white",):
        _sv_fn = fishing_surprise if fishing_surprise is not None else fishing_surprise_fn
        _sv_line = _sv_fn(group_id, qq_id, player, fish, force_legend=bool(_cf))
    new_lv, leveled = db.add_prof_exp(group_id, qq_id, "fishing", f_exp)
    lv_msg = f"\n🌟 垂钓等级提升到 Lv.{new_lv}！" if leveled else ""
    if daily_prof_bump is not None:
        _done, _msg = daily_prof_bump(group_id, qq_id, "fishing")
        lv_msg += _msg
    # 阶段九：垂钓次数 + 成就判定
    db.bump_stats(group_id, qq_id, fish_count=1)
    C.check_achievements(group_id, qq_id, player)
    _cf_fn = collect_bonus if collect_bonus is not None else collect_bonus_line
    _cf_line = _cf_fn(group_id, qq_id, player, _cf)
    # v104 R3 M15 P2-1：古代鱼骨全服广播（13 章 2.6 传说档广播，与鱼王同级）
    if fname == "古代鱼骨":
        _legend = (hooks or {}).get("legend")
        if _legend is not None:
            _legend(group_id, qq_id, player, fname, spot)
    # 24 章二：月光兔蛋特殊渠道——垂钓传说档（orange）15% 概率（真稀有原则）
    _pet_egg_line = ""
    if fq == "orange" and random.random() < _cc.PET_EGG_ORANGE_CHANCE:
        egg = C.make_pet_egg("pet_rabbit")
        db.add_item(group_id, qq_id, f"petegg_pet_rabbit", egg)
        _pet_egg_line = f"\n🥚 咦？鱼肚子里藏着一枚【{egg['name']}】！『使用 宠物蛋』孵化！"
    # v101.15 生活渠道：垂钓品质档特殊产出（稀缺品走生活渠道，不走战斗掉落）
    _life_line = ""
    if fq == "blue":
        if random.random() < 0.08:  # 铁壳龟蛋
            egg = C.make_pet_egg("pet_turtle")
            db.add_item(group_id, qq_id, f"petegg_pet_turtle", egg)
            _life_line += f"\n🥚 水草缠着一枚【{egg['name']}】！『使用 宠物蛋』孵化！"
        if random.random() < 0.05:  # 圣光鸽蛋
            egg = C.make_pet_egg("pet_dove")
            db.add_item(group_id, qq_id, f"petegg_pet_dove", egg)
            _life_line += f"\n🥚 水面上漂来一枚【{egg['name']}】！『使用 宠物蛋』孵化！"
        # v110 审计修复：驼马缰绳档位对齐 31 章设计（稀有级 blue 垂钓 5%）——
        # 原实现错标 purple 档（史诗档出绿色坐骑缰绳，档位与坐骑品质倒挂）
        if random.random() < 0.05:  # 铁港驼马缰绳
            rein = C.make_mount_rein("mount_camel")
            db.add_item(group_id, qq_id, f"mountrein_mount_camel", rein)
            _life_line += f"\n🐫 鱼肚子里卷着一根【{rein['name']}】！『使用 缰绳』驯服！"
    # v110 审计修复：purple 档原驼马条目已移入 blue 档（档位对齐 31 章设计），此档暂空
    elif fq == "orange":
        if random.random() < 0.08:  # 森林独角兽缰绳
            rein = C.make_mount_rein("mount_unicorn")
            db.add_item(group_id, qq_id, f"mountrein_mount_unicorn", rein)
            _life_line += f"\n🦄 传说之鱼口中衔着【{rein['name']}】！『使用 缰绳』驯服！"
        if random.random() < 0.08:  # 星灵蝶蛋
            egg = C.make_pet_egg("pet_starbutterfly")
            db.add_item(group_id, qq_id, f"petegg_pet_starbutterfly", egg)
            _life_line += f"\n🥚 鱼肚子里泛着星光——是【{egg['name']}】！『使用 宠物蛋』孵化！"
    # v101.13 坐骑 fish_bonus：概率额外多一条（骑乘钓鱼类坐骑）
    _mount_fish_line = ""
    meff = C.mount_effects(player)
    fb = float(meff.get("fish_bonus", 0) or 0)
    if fb > 0 and random.random() < fb:
        # v126.2 坐骑叼回：同样 roll 个体属性入 tags
        _sw2 = C.roll_fish_size_weight(fish)
        db.add_item(group_id, qq_id, mat_key,
                    {"name": fname, "type": fish["type"], "stackable": True,
                     "price": fish["price"], "quality": fq},
                    tag=_sw2)
        _mount_fish_line = f"\n🐾 坐骑帮你多叼回一条【{fname}】！"
    # v101.30b Lv.10 深海渔神：一杆双鱼（15% 概率多一条同品质渔获）
    _master_line = ""
    if prof_lv >= 10 and random.random() < 0.15:
        # v126.2 渔神双鱼：同样 roll 个体属性入 tags
        _sw3 = C.roll_fish_size_weight(fish)
        db.add_item(group_id, qq_id, mat_key,
                    {"name": fname, "type": fish["type"], "stackable": True,
                     "price": fish["price"], "quality": fq},
                    tag=_sw3)
        _master_line = f"\n🐟 渔神出手，一杆双鱼！又一条【{fname}】入网！"
    return (f"{catch_pre}🎣 你在{spot}钓上来一条【{q_name}】{_size_line}！\n"
            f"📦 {fish['desc']}(可『出售 {fname}』，标价 {fish['price']} 金币，实收按店铺 8~9 折)"
            f"{_sv_line}{lv_msg}{_cf_line}{_mount_fish_line}{_master_line}{_pet_egg_line}{_life_line}{bait_line}")


def fishing_surprise_fn(group_id, qq_id, player, fish, force_legend=False):
    """v168.2 垂钓惊喜层：按鱼获品质判定触发，命中后从内容池掷一档惊喜入包。

    触发判定只吃 1 次 random.random()；内容档位各吃 1 次（总消耗可预期，不影响
    垂钓其余随机序列）。装备档品质 roll 蓝50/紫35/橙15（鱼鱼拍板，克制不膨胀），
    名册 roll_drop_equip('elite') 命中即用、未命中兜底 generate_equip 随机部位，
    保证装备档永不空开。
    force_legend=True（彩蛋收藏鱼命中）：必给惊喜且内容池固定为「传说档」= 必橙装
    （鱼鱼拍板：收藏鱼是垂钓最高彩蛋，惊喜也拉满——不出图纸/符文等次档）。
    """
    if not player:
        return ""
    q = fish.get("quality", "white")
    if not force_legend:
        chance = FISHING_SURPRISE_TRIGGER.get(q, 0.0)
        if chance <= 0 or random.random() >= chance:
            return ""
    # 命中惊喜：从内容池掷一档（force_legend=收藏鱼命中 → 直接必橙装传说档）
    import uuid
    lv = max(1, int(player.get("level") or 1))
    if force_legend:
        # 传说档：必橙装。名册就近（roll_drop_equip('elite')）命中即用，落空兜底
        # generate_equip 橙装——两路都只可能出橙装（收藏鱼是垂钓最高彩蛋，惊喜拉满）
        eq = C.roll_drop_equip(lv, "elite")
        if not eq or eq.get("quality") != "orange":
            slot = random.choice(
                ["weapon", "helm", "armor", "legs", "boots", "ring", "necklace"])
            eq = C.generate_equip(slot, lv + random.randint(-3, 3), "orange")
        db.add_item(group_id, qq_id, f"eq_{uuid.uuid4().hex[:8]}", eq)
        _qmark = {"green": "🟢", "blue": "🔵", "purple": "✨🟣", "orange": "🌟🟠"}.get(
            eq.get("quality", ""), "")
        return (f"\n🎏 一道金光从鱼腹中迸出——【{_qmark}{eq['name']}】静静躺在"
                f"水草间，传说中的宝物现世了！(已收入背包)")
    roll = random.random()
    if roll < FISHING_SURPRISE_BP:      # 图纸档 30%
        bp = C.roll_blueprint(lv)
        if bp:
            db.add_item(group_id, qq_id, f"eq_{uuid.uuid4().hex[:8]}", bp)
            return (f"\n🎏 惊喜！鱼肚子里还藏着一张泛黄的纸——【{bp['name']}】！"
                    f"(『背包 使用』学习锻造配方)")
        roll = FISHING_SURPRISE_BP  # 图纸池空（无配方可出）→ 落入装备档，不额外吃随机
    if roll < FISHING_SURPRISE_EQ:      # 装备档 25%
        _q = "blue" if random.random() < 0.50 else (
            "purple" if random.random() < 0.70 else "orange")
        eq = C.roll_drop_equip(lv, "elite")
        if eq is None:
            slot = random.choice(
                ["weapon", "helm", "armor", "legs", "boots", "ring", "necklace"])
            eq = C.generate_equip(slot, lv + random.randint(-3, 3), _q)
        db.add_item(group_id, qq_id, f"eq_{uuid.uuid4().hex[:8]}", eq)
        _qmark = {"green": "🟢", "blue": "🔵", "purple": "✨🟣", "orange": "🌟🟠"}.get(
            eq.get("quality", ""), "")
        if eq.get("quality") == "orange":
            return (f"\n🎏 一道金光从鱼腹中迸出——【{_qmark}{eq['name']}】静静躺在"
                    f"水草间，传说中的宝物现世了！(已收入背包)")
        if eq.get("quality") == "purple":
            return f"\n🎏 紫光流转——【{_qmark}{eq['name']}】夹在鱼鳃里闪闪发亮！(已收入背包)"
        return f"\n🎏 惊喜！鱼肚子里卷着一件装备——【{_qmark}{eq['name']}】！(已收入背包)"
    if roll < FISHING_SURPRISE_RUNE:    # 稀有符文档 20%（蓝/紫品质符文）
        rare_runes = [k for k, r in _ci.RUNES.items()
                      if (r.get("quality") or "") in ("blue", "purple")]
        if rare_runes:
            rk = random.choice(rare_runes)
            r_def = _ci.RUNES[rk]
            rune_data = C.rune_item(r_def["effect"], random.randint(1, 2))
            if rune_data:
                # key 与战斗掉落一致（rune_<effect>_<lvl>，同键可叠加）
                db.add_item(group_id, qq_id,
                            f"rune_{r_def['effect']}_{rune_data['lvl']}", rune_data)
                return (f"\n🎏 鱼腹泛起微光——一枚刻着古老铭文的【{rune_data['name']}】"
                        f"随水流漂出！(『背包 使用』附魔到装备)")
        roll = FISHING_SURPRISE_RUNE  # 蓝紫符文池空 → 落入宝石档，不额外吃随机
    if roll < FISHING_SURPRISE_GEM:     # 原石宝石档 15%（必给 1 颗原石，层数 1-6）
        # roll_gem_drop 带 normal 2% 底率——宝石惊喜档命中了却大概率空手（98% miss 会
        # 顺落罕见材料档，实测材料占比 24.7% 膨胀 2.5 倍）。改为：优先 roll_gem_drop
        # （对照 instance.py 原石掉落写法），未命中直接 roll_gem 兜底——宝石档=必给原石。
        _gem = C.roll_gem_drop({"lv": lv, "is_boss": False, "name": fish.get("name", "")},
                               boss_fixed={})
        if not _gem:
            _gem = C.roll_gem(1, 6)
        if _gem:
            db.add_item(group_id, qq_id, f"gem_{uuid.uuid4().hex[:8]}", _gem)
            return f"\n💎 惊喜！鱼肚子里嵌着一颗【{_gem['name']}】——原石入包，可『原石』镶嵌到装备孔位！"
    # 罕见材料档 10%（type in 传说/宝石/精华 且 价≥150 的 MATERIALS 池）
    rare_pool = {k: v for k, v in _ci.MATERIALS.items()
                 if v.get("type") in ("传说", "宝石", "精华")
                 and (v.get("price") or 0) >= 150}
    if rare_pool:
        _mkey = random.choice(list(rare_pool))
        _mdef = rare_pool[_mkey]
        _mname = C.display("materials", _mkey)
        db.add_item(group_id, qq_id, _mkey, {
            "name": _mname, "type": _mdef.get("type", "材料"),
            "stackable": True, "price": _mdef.get("price", 0),
        })
        return f"\n🎁 惊喜！水底沉着稀罕的材料——【{_mname}】！(已收入背包)"
    return ""  # 罕见材料池意外为空 → 静默（不再造一句假惊喜）


def collect_bonus_line(group_id, qq_id, player, cf):
    """彩蛋收藏鱼入包 + 计数 + 成就，返回提示行(未命中返回空串)"""
    if not cf:
        return ""
    db.add_item(group_id, qq_id, cf["id"],
                {"name": cf["name"], "type": "收藏", "stackable": True, "price": 1})
    db.bump_stats(group_id, qq_id, catch_collect=1)
    C.check_achievements(group_id, qq_id, player, {"collect_fish": cf["id"]})
    return (f"\n🌈 水面忽然泛起奇异的光——【{cf['name']}】跃出水面！\n"
            f"　它美得不像凡物，你小心翼翼地收进了图鉴(彩蛋收藏品，回收仅 1 金币)")


def settle_gather(group_id, qq_id, st, *, daily_prof_bump=None,
                  collect_any_bump=None, tip=None):
    """结算采集等待（economy._settle_gather 原样随迁，逐行等价）。

    daily_prof_bump：每日副业任务推进注入（收 group_id/qq_id/tkey → (done,msg)）。
    collect_any_bump：『每日 采集任务』collect_any 进度推进注入（收 group_id/qq_id/obj_key/lines）。
    tip：命令层 _tip("gather") 注入（收 cat → 提示行）。
    """
    player = db.get_player(group_id, qq_id)
    if not player:
        return None
    prof = db.get_prof_level(group_id, qq_id, "gather")
    # v105R3 M13 P2-4：结算用等待开始时存储的地图（重启后玩家已移动也不串池），
    # 无存储（旧状态）才回退当前地图
    _map_id = st.get("spot_map") or player.get("cur_map", "")
    mats = gather_roll(player["level"], prof, _map_id)
    got = {}
    for mat in mats:
        mname = C.display("materials", mat)
        # v104 M08 P0-1：type 从 MATERIALS 定义取（防任务道具类材料被写死为"材料"）
        db.add_item(group_id, qq_id, mat, {"name": mname, "type": _ci.MATERIALS[mat].get("type", "材料"), "stackable": True, "price": _ci.MATERIALS[mat]["price"]})
        # v105R3 M14 P3-1：重复材料合并计数（原逐条"草药x1、草药x1"）
        got[mname] = got.get(mname, 0) + 1
    new_lv, leveled = db.add_prof_exp(group_id, qq_id, "gather", 1)
    lv_msg = f"\n🌟 采集等级提升到 Lv.{new_lv}！" if leveled else ""
    if daily_prof_bump is not None:
        _done, _msg = daily_prof_bump(group_id, qq_id, "gather")
        lv_msg += _msg
    # v101.13 坐骑 collect_bonus：概率额外采一份（骑乘采集类坐骑）
    _mount_bonus_line = ""
    meff = C.mount_effects(player)
    cb = float(meff.get("collect_bonus", 0) or 0)
    if cb > 0 and random.random() < cb:
        # B3 修复：坐骑 collect_bonus 不再重新掷池（gather_roll 可能抽到与本次非同
        # 类的材料），改从本次 mats 中取样，保证『🐾 坐骑帮你多叼回一份』与实入包同物
        mat = random.choice(mats) if mats else None
        if mat:
            mname = C.display("materials", mat)
            db.add_item(group_id, qq_id, mat, {"name": mname, "type": _ci.MATERIALS[mat].get("type", "材料"), "stackable": True, "price": _ci.MATERIALS[mat]["price"]})
            got[mname] = got.get(mname, 0) + 1
            _mount_bonus_line = f"\n🐾 坐骑帮你多叼回一份【{mname}】！"
    # 阶段九：采集次数 + 成就判定
    db.bump_stats(group_id, qq_id, gather_count=1)
    C.check_achievements(group_id, qq_id, player)
    cur_map = _sp.MAP_BY_ID.get(_map_id, {})
    # 24 章二：月光兔蛋特殊渠道——采集稀有产出 10% 概率（稀有材料判定参考 gather_roll 的高价段）
    _pet_egg_line = ""
    # v125.2 B3：稀有阈值数据下沉 prof_config.RARE_MATERIAL_PRICE（原字面量 150）
    rare_hit = any(_ci.MATERIALS[m].get("price", 0) >= _cl.RARE_MATERIAL_PRICE for m in mats)
    # v101.30b Lv.10 万物采集大师：稀有惊喜概率翻倍（兔蛋 10%→20%）
    _rare_ch = 0.20 if prof >= 10 else _cc.RARE_MAT_CHANCE
    if rare_hit and random.random() < _rare_ch:
        egg = C.make_pet_egg("pet_rabbit")
        db.add_item(group_id, qq_id, "petegg_pet_rabbit", egg)
        _pet_egg_line = f"\n🥚 草丛深处有一枚【{egg['name']}】！『使用 宠物蛋』孵化！"
    # v101.15 生活渠道：北境采集稀有产出驯鹿缰绳 5%（稀缺品走生活渠道）
    _life_line = ""
    # v101.30b Lv.10：驯鹿缰绳 5%→10%
    _rein_ch = 0.10 if prof >= 10 else 0.05
    # v104 M17 P2：驯鹿缰绳仅限北境区域采集稀有产出（desc「北境采集稀有产出『驯鹿缰绳』」）
    # 非北境地图（region 不以"北境"开头）即使采到稀有材料也不出驯鹿缰绳
    _is_north = str(cur_map.get("region", "")).startswith("北境")
    if rare_hit and _is_north and random.random() < _rein_ch:
        rein = C.make_mount_rein("mount_reindeer")
        db.add_item(group_id, qq_id, "mountrein_mount_reindeer", rein)
        _life_line = f"\n🦌 树根下缠着一根【{rein['name']}】！『使用 缰绳』驯服！"
    # v104 M20 P1：每日『采集任务』(collect_any) 进度推进——主采集动作接线
    # （此前只有城镇场景元素「交互 草药柜」每日 1 次推进，野外『采集』恒 0/5）
    _daily_lines = []
    if collect_any_bump is not None:
        collect_any_bump(group_id, qq_id, "collect_any", _daily_lines)
    _daily_txt = "".join(f"\n{l}" for l in _daily_lines) if _daily_lines else ""
    # q7-9：满级采集彩蛋（兔蛋/驯鹿缰绳）只绑稀有产出（价格≥150），低等级图无稀有材料
    # 恒 0%——本次未采到稀有材料时提示去高级图（纯文案，不动数值）
    _rare_hint = (f"\n💡 稀有产出需前往产出价≥{_cl.RARE_MATERIAL_PRICE} 材料的区域（高级图）" if not rare_hit else "")
    # v105R3 M14 P3-2：材料每项单独一行（对齐物品详情排版规范 v101.21）
    _got_txt = "".join(f"\n{m}x{c}" for m, c in got.items())
    # v169.x 意见#101：采集完成消息顶部加玩家名（同文件 791 行『玩家 {pname}』口径：
    # player.name 优先，缺省回退 qq_id）
    _pname = (player or {}).get("name") or str(qq_id)
    _tip_txt = tip("gather") if tip is not None else ""
    return (f"🌿 采集完成！玩家【{_pname}】在【{cur_map.get('name', '？')}】采到了：{_got_txt}\n"
            + _tip_txt + f"{lv_msg}{_mount_bonus_line}{_pet_egg_line}{_life_line}{_rare_hint}{_daily_txt}")


# ---------- v105 挖掘疲劳值（19 章 §2.2；M14 P2-4 最小实现） ----------
# 连续挖掘计数存 event_state（mining_fatigue_{qq_id}），无 schema 变更；
# 疲劳效果：稀有矿脉概率减半；恢复：10 分钟不挖掘自动清零（食物解除待后续版本）。

def mining_fatigue_state(group_id, qq_id):
    """读取疲劳状态 {cnt, ts}；无/损坏返回 None"""
    raw = db.get_event_state(f"mining_fatigue_{qq_id}")
    if not raw:
        return None
    try:
        st = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(st, dict) or "cnt" not in st or "ts" not in st:
        return None
    return st


def mining_fatigue_tick(group_id, qq_id):
    """发起一轮挖掘时计数：距上次挖掘超过恢复窗口则重置为 1，否则 +1。
    返回 (cnt, fatigued)。"""
    now = int(time.time())
    st = mining_fatigue_state(group_id, qq_id)
    if st and now - st.get("ts", 0) <= MINING_FATIGUE_RECOVER:
        cnt = st.get("cnt", 0) + 1
    else:
        cnt = 1
    db.set_event_state(f"mining_fatigue_{qq_id}",
                       json.dumps({"cnt": cnt, "ts": now}, ensure_ascii=False))
    return cnt, cnt >= MINING_FATIGUE_THRESHOLD


def mining_fatigued(group_id, qq_id):
    """结算时判定是否处于疲劳：连续挖掘 ≥ 阈值且距上次挖掘在恢复窗口内"""
    st = mining_fatigue_state(group_id, qq_id)
    if not st:
        return False
    return (st.get("cnt", 0) >= MINING_FATIGUE_THRESHOLD
            and int(time.time()) - st.get("ts", 0) <= MINING_FATIGUE_RECOVER)


def settle_mining(group_id, qq_id, st, *, daily_prof_bump=None):
    """结算挖掘等待（economy._settle_mining 原样随迁，逐行等价）。

    daily_prof_bump：每日副业任务推进注入（收 group_id/qq_id/tkey → (done,msg)）。
    """
    player = db.get_player(group_id, qq_id)
    if not player:
        return None
    prof = db.get_prof_level(group_id, qq_id, "mining")
    # v125：挖掘矿石关键词数据下沉 prof_config.MINING_KEYWORDS（原 _ORE_KW）
    # v105R3 M13 P2-4：结算用等待开始时存储的地图（重启后玩家已移动也不串池），
    # 无存储（旧状态）才回退当前地图
    cur_map = st.get("spot_map") or player.get("cur_map", "")
    # v102.3 深矿池优先：矿洞类地图（山丘矿洞/深隧/海蚀洞窟）按权重出专属矿
    # v174 统一抽象：数据源走 drop_engine（mine:{map} / gather:{map}）
    deep_ores = _expand_pool(f"mine:{cur_map}")
    if deep_ores:
        ores = deep_ores
    else:
        # v101.28k 地图矿石池优先：复用该地图采集池里的矿石类材料（矿场图=矿池，
        # 植物图无矿则按地图等级价格区间兜底）→ 不同地图挖到不同档次的矿
        gather_ores = [m for m in _expand_pool(f"gather:{cur_map}")
                       if any(k in _ci.MATERIALS.get(m, {}).get("name", "") for k in _cl.MINING_KEYWORDS)]
        if gather_ores:
            ores = gather_ores
        else:
            ores = []
        if not ores:
            # v104 R3 M14 P1-2：兜底排除强化石类消耗品（i_stone_* 是炼金/商店独占，禁止挖掘白嫖）
            ores = [m for m, mm in _ci.MATERIALS.items()
                    if any(k in mm.get("name", "") for k in _cl.MINING_KEYWORDS)
                    and m not in ("i_stone_upgrade", "i_stone_refine")]
            _map_lv = _sp.MAP_BY_ID.get(cur_map, {}).get("lv", player["level"])
            # v125.2 B3：价格带公式数据下沉 prof_config.price_band（原 3+lv*4 / 20+lv*12 双处字面量）
            _lo, _hi = price_band(_map_lv)
            cand = [m for m in ores if _lo <= _ci.MATERIALS[m]["price"] <= _hi]
            if cand:
                ores = cand
    # 稀有矿脉：副业 Lv.4+ 概率（15% / Lv.7+ 30%），只在当前地图池内选稀有
    # v101.30b Lv.10 群山之王：稀有矿脉 50%
    # v105 疲劳值（19 章 §2.2）：疲劳期间稀有矿脉概率减半
    # v125.2 B3：稀有阈值数据下沉 prof_config.RARE_MATERIAL_PRICE（原字面量 150）
    rare = [m for m in ores if _ci.MATERIALS[m]["price"] >= _cl.RARE_MATERIAL_PRICE]
    is_rare = False
    fatigued = mining_fatigued(group_id, qq_id)
    _rare_ch = 0.15 if prof < 7 else (0.50 if prof >= 10 else 0.30)
    if fatigued:
        _rare_ch *= 0.5
    if prof >= 4 and rare and random.random() < _rare_ch:
        ore = random.choice(rare)
        is_rare = True
    else:
        ore = random.choice(ores)
    n = random.randint(1, 2)
    if prof >= 5 and random.random() < _cc.PROF5_BONUS_CHANCE:
        n += 1
    oname = C.display("materials", ore)
    db.add_item(group_id, qq_id, ore, {"name": oname, "type": _ci.MATERIALS[ore].get("type", "材料"), "stackable": True, "price": _ci.MATERIALS[ore]["price"]}, count=n)
    new_lv, leveled = db.add_prof_exp(group_id, qq_id, "mining", 1)
    lv_msg = f"\n🌟 挖掘等级提升到 Lv.{new_lv}！" if leveled else ""
    if daily_prof_bump is not None:
        _done, _msg = daily_prof_bump(group_id, qq_id, "mining")
        lv_msg += _msg
    # 阶段九：挖掘次数 + 成就判定
    db.bump_stats(group_id, qq_id, mine_count=1)
    C.check_achievements(group_id, qq_id, player)
    # v101.28k 挖掘演出：稀有矿脉 / 多份暴击 / 普通
    if is_rare:
        head = "💎 矿脉深处泛起宝光，一锤下去竟是稀有矿脉！"
    elif n >= 3:
        head = "⛏️ 这一锤又准又狠，矿脉整个崩开了！"
    else:
        head = "⛏️ 矿脉敲开了！"
    # v105 疲劳值：结算附疲劳提示（疲劳只降稀有概率，不影响正常产出）
    _fat_line = ("\n💤 连续挖掘让你手臂发酸，稀有矿脉更难挖到了……休息 10 分钟（不挖掘）疲劳自会消退！"
                 if fatigued else "")
    # q7-9：满级挖掘稀有矿脉只绑价格≥150 的矿，低等级图矿池无稀有矿则彩蛋恒 0%——
    # 本次无稀有矿可挖时提示去高级图（纯文案，不动数值）
    _rare_hint = (f"\n💡 稀有产出需前往产出价≥{_cl.RARE_MATERIAL_PRICE} 材料的区域（高级图）" if not rare else "")
    return f"{head}\n你获得了 {oname} x{n}！(『背包』查看){lv_msg}{_fat_line}{_rare_hint}"
