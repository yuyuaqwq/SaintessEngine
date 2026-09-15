# -*- coding: utf-8 -*-
"""包内每日任务域（`content/profession_quests.py`）—— 真源 `game/services/quests.py`（231 行）**逐字端口**。

文件名说明：本模块由 B9 **L4（生活副业线）** 端口，与 `content/profession.py` 同批 / 同源目录，
故沿用 `profession_*` 前缀（避免与别的线的 `content/quests*.py` 撞名）。

真源（游戏仓 `qqbot/data/plugins/dragonfall`，**只读**）
--------------------------------------------------------
| 真源 | 行数 | 本文件搬什么 |
|---|---:|---|
| `game/services/quests.py` | 231 | **全文件**：每日任务常量（重复衰减档 / 元数据键 / 单日上限）+ `daily_repeat_pct` + `daily_need` + `settle_daily_quest`（达标结算单点）+ `bump_daily_progress`（非击杀推进）+ `daily_pool`（等级过滤）+ `draw_daily`（抽取/衰减/发布）+ 六个下划线兼容别名 |

宿主耦合替身（**只改一类东西**：宿主 import 口）
------------------------------------------------
真源里**所有**宿主依赖都是**函数体内**惰性 import（存储层 / 文案表 / 升级 / 面板加成 / 内容聚合）：

| 真源写法（函数体内） | 包内写法 | 说明 |
|---|---|---|
| `from .. import db` | 模块级 `db` = 惰性宿主代理 `_HostDB` | `db.xxx(...)` 正文一行未改 |
| `from .. import content as C` | ★ B14-2 L8：**已切净**（`C.DAILY_QUESTS` → 包内门面 `catalog_quests.DAILY_QUESTS`）⇒ `C` 替身删；`bind_host(content=…)` 注入面按宿主薄壳协议保留 | 读 `DAILY_QUESTS`，源序 = `_DAILY_QUESTS_ORDER`（门禁逐值+列表序 OK） |
| `from ..core import texts as T` | 模块级 `T` = **包内**惰性句柄 `PkgModule("content.texts")`（★ P4′-W1-B） | `T.text(...)` / `T.static(...)` 一字未改；宿主 `game.core.texts` 的 `text`/`static` 是**同一批函数对象**（探针实测 `is` 为真）|
| `from ..core.stat_bonus import stat_bonus` | 模块级 `stat_bonus` = 惰性调用代理 → ★ REPOINT-PKG 起兜底**包内直取** `content/stat_bonus.py` | 称号加成，签名/语义不变（宿主 `game/core/stat_bonus.py` 是同名单再导出 ⇒ 同一函数对象） |
| `from ..content_rules.gameplay import check_player_level_up` | 模块级 `check_player_level_up` = 惰性调用代理 → ★ REPOINT-PKG 起兜底**包内直取** `content/gameplay_rules.py` | 升级判定，返回 `(logs, player)` 不变（宿主 `game/content_rules/gameplay.py` 是同名单再导出 ⇒ 同一函数对象） |

不变式
------
* 函数体逐行照搬（含注释/文案槽位名/`lines` 追加顺序）。
* `random.sample` / 衰减乘算 / `daily[f"d{i}"]` 键序与真源完全一致。
* `DAILY_QUESTS` 的**源顺序**参与 `daily_pool` 过滤 + `random.sample` 抽样 → 顺序敏感；
  ★ B14-2 L8（2026-09-14）：切包内门面 `catalog_quests.DAILY_QUESTS`（按 `_DAILY_QUESTS_ORDER` 声明序
  重建 → **列表序 == 源序**，门禁 `b14_catalog_gate.py` 逐条+序 OK），旧注「包内 JSON 是字典序故仍读宿主 C」**已作废**。

用法::

    from content import profession_quests as Q
    Q.bind_host(db, content=C, texts=T, level_up=check_player_level_up, stat_bonus=stat_bonus)
    ok, txt = Q.draw_daily(group_id, qq_id, player)
"""
from __future__ import annotations

import random

# ★ P4′-W1-B（包侧去 shim）：包内惰性模块句柄（旧 `_HostMod` 的包内等价物；零依赖，
#   取件时机逐字相同 = 属性访问时解析）。
from ._pkgref import PkgModule as _PkgModule

# ============================================================
# 宿主替身口（全部对应真源的**函数体内**惰性 import → 包内改模块级惰性代理）
# ============================================================
_HOST_DB = None            # 真源 `from .. import db`
_HOST_CONTENT = None       # 真源 `from .. import content as C`
_HOST_LEVEL_UP = None      # 注入槽（真源 `from ..content_rules.gameplay import …`）—— 未注入 → 包内直取 `content/gameplay_rules.py`
_HOST_STAT_BONUS = None    # 注入槽（真源 `from ..core.stat_bonus import stat_bonus`）—— 未注入 → 包内直取 `content/stat_bonus.py`

_HOST_PKG = "data.plugins.dragonfall.game"
_HOST_PKG_FALLBACK = "game"


def bind_host(db=None, content=None, texts=None, level_up=None, stat_bonus=None):
    """宿主替身注入（幂等；宿主薄壳 `game/services/quests.py` 在 import 期调用）。

    ★ P4′-W1-B：`texts` 形参按宿主薄壳的注入协议**保留**
      （`game/services/quests.py:71` 用 `texts=_pkg.lazy_module(_host_texts)` 传参 —— 少了会
      TypeError），但包内已不再持有它的槽位：文案表改指包内 `content/texts.py`（`T`）。
      传进来的值被显式忽略。
    """
    global _HOST_DB, _HOST_CONTENT, _HOST_LEVEL_UP, _HOST_STAT_BONUS
    if db is not None:
        _HOST_DB = db
    if content is not None:
        _HOST_CONTENT = content
    if level_up is not None:
        _HOST_LEVEL_UP = level_up
    if stat_bonus is not None:
        _HOST_STAT_BONUS = stat_bonus


def lazy_module(getter):
    """把「宿主模块取用 thunk」包成懒模块对象（宿主薄壳注入 `T` 用）。"""
    return _LazyModule(getter)


def _resolve_host(mod: str):
    """取宿主子模块：**已加载**的宿主模块（`sys.modules`，绝不 import）。"""
    import sys
    for name in ("%s.%s" % (_HOST_PKG, mod), "%s.%s" % (_HOST_PKG_FALLBACK, mod)):
        m = sys.modules.get(name)
        if m is not None:
            return m
    raise RuntimeError("quests：宿主模块 %s 不可用（未 bind_host 且未加载）—— 拒绝静默空跑" % mod)


class _LazyModule(object):
    def __init__(self, getter):
        self._getter = getter

    def __getattr__(self, name):
        return getattr(self._getter(), name)


class _HostDB(object):
    def __getattr__(self, name):
        return getattr(_HOST_DB if _HOST_DB is not None else _resolve_host("db"), name)


# ★ P4′-W1-B：`_HostMod` 样板随唯一使用点（旧 `T = _HostMod(...)`）变死 → 已删
#   （本文件其余读点均为包内直取 / 注入槽直调，无宿主模块句柄需求）。
db = _HostDB()
# ★ P4′-W1-B：文案表改指**包内实现** `content/texts.py`。宿主 `game.core.texts` 是拷贝壳，
#   其 `text` / `static` 与包内是**同一批函数对象**（探针实测 `is` 为真）⇒ 逐字同一实现；
#   包内不再经宿主命名空间取件。`PkgModule` 每次属性访问解析一次（与旧 `_HostMod` 同时机）。
T = _PkgModule("content.texts")
# ★ B14-2 L8（2026-09-14）：`C` 替身已删（唯一读点 `C.DAILY_QUESTS` 切包内门面）。`bind_host(content=…)`
#   形参按宿主薄壳 `game/services/quests.py:71` 的注入协议**保留**（少了它会 TypeError）。
from . import catalog_quests as _cq          # noqa: E402  DAILY_QUESTS（源序 = _DAILY_QUESTS_ORDER）


def check_player_level_up(*args, **kwargs):
    """真源 `from ..content_rules.gameplay import check_player_level_up`（函数体内惰性 import）。

    ★ REPOINT-PKG（2026-09-15，B4R B 组第 2 项）：兜底由宿主子模块
      `game.content_rules.gameplay` 改**包内直取** `content/gameplay_rules.py`
      （宿主是同名单再导出 ⇒ 同一函数对象）。注入槽 `bind_host(level_up=…)` 原样保留。
    """
    if _HOST_LEVEL_UP is not None:
        return _HOST_LEVEL_UP(*args, **kwargs)
    from .gameplay_rules import check_player_level_up as _fn   # 包内直取
    return _fn(*args, **kwargs)


def stat_bonus(*args, **kwargs):
    """真源 `from ..core.stat_bonus import stat_bonus`（函数体内惰性 import）。

    ★ REPOINT-PKG（2026-09-15，B4R B 组第 3 项）：兜底由宿主子模块 `game.core.stat_bonus`
      改**包内直取** `content/stat_bonus.py`（宿主是同名单再导出 ⇒ 同一函数对象）。
      注入槽 `bind_host(stat_bonus=…)` 原样保留。
    """
    if _HOST_STAT_BONUS is not None:
        return _HOST_STAT_BONUS(*args, **kwargs)
    from .stat_bonus import stat_bonus as _fn                  # 包内直取
    return _fn(*args, **kwargs)


# ============================================================
# 真源正文（逐字；只删掉宿主 import 口那一行）
# ============================================================
# v116 每日任务重复衰减档位：第 N 次完成同任务 → 奖励乘数
# （0 = 首刷 100%，1 = 第 2 次 60%，2 = 第 3 次 30%，≥3 = 第 4 次起 10%）
DAILY_REPEAT_FACTORS = (1.0, 0.6, 0.3, 0.1)
# daily 字典内保留元数据键（跨天字段/完成计数/重复计数），任务面板与抽取逻辑一律跳过
DAILY_META_KEYS = ("_date", "_completed", "_repeat")
# v116 任务系统定稿 §3.4：每日任务单日完成上限（防刷）——达到后『每日』不再抽新任务
DAILY_LIMIT = 10

# 兼容别名：原命令层下划线私有名 → services 公开名（world/combat 旧引用已改 import，
# 别名仅为 P4-2 QuestService 全量前外部存档/工具引用兜底）
_DAILY_REPEAT_FACTORS = DAILY_REPEAT_FACTORS
_DAILY_META_KEYS = DAILY_META_KEYS


def daily_repeat_pct(repeat):
    """重复完成同日常任务 → 衰减后的发奖比例（百分比）。repeat = 今日已完成的次数。
    第 1 次 100%、第 2 次 60%、第 3 次 30%、第 4 次起 10%（§3.4 板规则）。"""
    f = DAILY_REPEAT_FACTORS[repeat] if repeat < len(DAILY_REPEAT_FACTORS) else DAILY_REPEAT_FACTORS[-1]
    return int(round(f * 100))


def _daily_repeat_pct(repeat):
    """（P4-1 兼容别名，见 DAILY_REPEAT_FACTORS 注释）"""
    return daily_repeat_pct(repeat)


def daily_need(dq):
    """每日任务需求数（面板显示用）。objective 单键值即达标数（kill_any:10 等）。
    v125.1 P2：存档缺 objective 时回读 DAILY_QUESTS 定义；仍无定义返回 None，
    面板只显示实际进度，不再兜底假 99。"""
    dobj = (dq or {}).get("objective") or {}
    for _v in dobj.values():
        if isinstance(_v, int) and _v > 0:
            return _v
    _def = next((q for q in _cq.DAILY_QUESTS if q.get("name") == (dq or {}).get("name")), None)
    if _def:
        for _v in (_def.get("objective") or {}).values():
            if isinstance(_v, int) and _v > 0:
                return _v
    return None


def _daily_need(dq):
    """（P4-1 兼容别名，见 DAILY_REPEAT_FACTORS 注释）"""
    return daily_need(dq)


def settle_daily_quest(group_id, qq_id, daily, dq, lines=None):
    """v125.1 P2：每日任务达标结算单点（world._bump_daily_progress 与 combat._update_quests
    双副本收敛）。职责：完成计数(_completed)/重复衰减计数(_repeat)、经验金币发放、升级、
    通知行。调用方负责进度 +1 与达标判断，结算后自行 del 任务键；lines=None 时不输出通知。"""
    daily["_completed"] = int(daily.get("_completed", 0) or 0) + 1
    rpt = int(daily.get("_repeat", {}).get(dq["name"], 0) or 0)
    _rep = dict(daily.get("_repeat", {}) or {})
    _rep[dq["name"]] = rpt + 1
    daily["_repeat"] = _rep
    if lines is not None:
        _dec = dq.get("repeat", 0)
        if _dec:
            _pct = daily_repeat_pct(_dec)
            lines.append(T.text("quests.done_decay", name=dq["name"], pct=_pct,
                                exp=dq["reward_exp"], gold=dq["reward_gold"]))
        else:
            lines.append(T.text("quests.done", name=dq["name"], exp=dq["reward_exp"],
                                gold=dq["reward_gold"]))
    player = db.get_player(group_id, qq_id)
    player["exp"] += dq["reward_exp"]
    player["gold"] += dq["reward_gold"]
    player["_title_bonus"] = stat_bonus(group_id, qq_id, player)
    lv_logs, player = check_player_level_up(group_id, qq_id, player)
    db.update_player(group_id, qq_id, exp=player["exp"], gold=player["gold"], level=player["level"], hp=player["hp"], mp=player["mp"], max_hp=player["max_hp"], max_mp=player["max_mp"], skills=player["skills"], attr_pts=player.get("attr_pts", 0), skill_points=player.get("skill_points", 0), learned_skills=player.get("learned_skills", []))
    if lines is not None and lv_logs:
        lines.append("")
        lines += lv_logs


def _settle_daily_quest(inst, group_id, qq_id, daily, dq, lines=None):
    """（P4-1 兼容别名：旧 inst 签名壳 → services 无 inst 版。仅外部存档/工具兜底，
    world/combat 内部调用点已全部改走 services 直调。）"""
    settle_daily_quest(group_id, qq_id, daily, dq, lines)


def bump_daily_progress(group_id, qq_id, obj_key, lines=None):
    """v104 M20 修复：非击杀类每日任务进度推进（行会委托=完成支线 / 采集任务=采集材料）。

    与 combat.py 击杀分支（kill_any/kill_elite/kill_boss）互补：
    匹配 objective[obj_key] 的每日任务 +1，达标即发奖并从今日列表移除。
    调用点：_complete_side_quest（complete_side）、interact_prop 材料元素（collect_any）。
    """
    quests = db.get_quests(group_id, qq_id)
    daily = dict(quests.get("daily", {}) or {})
    if not daily:
        return
    changed = False
    for dkey, dq in list(daily.items()):
        if dkey in DAILY_META_KEYS:  # 跨天/计数元数据，不是任务
            continue
        dobj = dq.get("objective") or {}
        need = dobj.get(obj_key)
        if not need:
            continue
        dq["progress"] = int(dq.get("progress", 0)) + 1
        changed = True
        if dq["progress"] >= need:
            # v125.1 P2：发奖结算统一走 settle_daily_quest（与 combat._update_quests 同单点）
            settle_daily_quest(group_id, qq_id, daily, dq, lines)
            del daily[dkey]
    if changed:
        # 保留 _date/_completed/_repeat（active 任务清空后仍须持续生效防刷/衰减计数）
        quests["daily"] = daily
        db.save_quests(group_id, qq_id, quests)


def _bump_daily_progress(inst, group_id, qq_id, obj_key, lines=None):
    """（P4-1 兼容别名：旧 inst 签名壳 → services 无 inst 版。仅外部存档/工具兜底，
    world/economy 内部调用点已全部改走 services 直调。）"""
    bump_daily_progress(group_id, qq_id, obj_key, lines)


def daily_pool(player, dq):
    """v94 每日任务按等级过滤：低等级不抽打不到的任务（修复 #45）。
    通用任意怪任务全等级可做；精英 Lv.6+、Boss Lv.10+；
    区域任务按奖励分档（reward_exp 与区域怪物等级强相关）。
    v169.1 成长模型：DAILY_QUESTS 四档等级池（新手/中坚 Lv20/高阶 Lv50/终局 Lv80），
    任务带 min_lv 字段 → 直接按玩家等级过滤（高于 min_lv 才可抽），
    且高 reward_exp 任务不再被旧 cap 表误放行（旧 cap Lv30+ 变 10 亿导致 Lv30 抽 Lv80 任务）。
    """
    lv = int(player.get("level") or 1)
    obj = dq.get("objective", {})
    exp = int(dq.get("reward_exp") or 0)
    # v169.1：显式 min_lv 字段优先（新等级池）
    _mlv = dq.get("min_lv")
    if isinstance(_mlv, int):
        return lv >= _mlv
    if "kill_any" in obj:
        return True
    if "kill_elite" in obj:
        return lv >= 6
    if "kill_boss" in obj:
        return lv >= 10
    if lv < 3:
        return False
    cap = 400
    for min_lv, c in ((3, 400), (6, 800), (10, 1200), (15, 1600), (20, 2000), (25, 2600), (30, 1000000000)):
        if lv >= min_lv:
            cap = c
    return exp <= cap


def draw_daily(group_id, qq_id, player):
    """v94『每日』抽取/衰减/发布：读 DAILY_QUESTS → 等级过滤 → random.sample 抽 2 个
    → 按今日已完成的同任务次数算衰减 factor 乘算奖励 → 写回 quests.daily。

    v116 保留今日已完成/重复计数（active 任务清空后重新抽取时不可归零，防刷衰减判定持续有效）。
    返回 (ok, text)：ok=False 时 text 为拒绝提示（红名守卫/上限/已有任务由调用方命令层负责，
    此处只管发布）；ok=True 时 text 为发布面板行（\n 拼接前不含尾行）。"""
    import datetime as _dt
    quests = db.get_quests(group_id, qq_id)
    # v94 跨天清理：昨天的任务过期，先清空再判断（旧存档无 _date 视为过期）
    if db.expire_daily(quests):
        db.save_quests(group_id, qq_id, quests)
    daily = quests.get("daily") or {}
    # v116 §3.4 每日防刷：已完成任务（_completed 计数）≥ 上限 → 不再抽新任务
    completed = int(daily.get("_completed", 0) or 0)
    if completed >= DAILY_LIMIT:
        return False, T.text("quests.limit", completed=completed, limit=DAILY_LIMIT)
    if any(k not in DAILY_META_KEYS for k in daily):
        return False, T.static("quests.have")
    # v116 保留今日已完成/重复计数（active 任务清空后重新抽取时不可归零，防刷衰减判定持续有效）
    base_completed = completed
    repeat = dict(daily.get("_repeat", {}) or {})
    # v94 随机抽 2 个每日任务（按等级过滤：低等级不抽打不到的任务）
    pool = [dq for dq in _cq.DAILY_QUESTS if daily_pool(player, dq)]
    chosen = random.sample(pool, min(2, len(pool)))
    daily = {"_date": _dt.date.today().isoformat(),
             "_completed": base_completed, "_repeat": repeat}
    for i, dq in enumerate(chosen):
        rpt = int(repeat.get(dq["name"], 0) or 0)  # 今日已完成的同任务次数 → 衰减档
        factor = DAILY_REPEAT_FACTORS[rpt] if rpt < len(DAILY_REPEAT_FACTORS) else DAILY_REPEAT_FACTORS[-1]
        daily[f"d{i}"] = {"name": dq["name"], "desc": dq["desc"], "objective": dq["objective"],
                          "reward_exp": int(dq["reward_exp"] * factor),
                          "reward_gold": int(dq["reward_gold"] * factor),
                          "repeat": rpt, "progress": 0}
    quests["daily"] = daily
    db.save_quests(group_id, qq_id, quests)
    lines = [T.static("quests.published"), "━━━━━━━━━━━━"]
    _daily_n = 0  # v125.1 P2：序号仅计实际任务（跨 _date/_completed/_repeat 元数据键）
    for dkey, dq in daily.items():
        if dkey in DAILY_META_KEYS:
            continue
        _daily_n += 1
        _dec = dq.get("repeat", 0)
        lines.append(T.text("quests.item", n=_daily_n, name=dq["name"], desc=dq["desc"]))
        if _dec:
            _pct = daily_repeat_pct(_dec)
            lines.append(T.text("quests.item_decay", pct=_pct, exp=dq["reward_exp"],
                                gold=dq["reward_gold"]))
        else:
            lines.append(T.text("quests.item_reward", exp=dq["reward_exp"],
                                gold=dq["reward_gold"]))
    if base_completed:
        lines.append(T.text("quests.progress_note", base=base_completed,
                            limit=DAILY_LIMIT))
    return True, "\n".join(lines)
