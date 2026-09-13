# -*- coding: utf-8 -*-
"""《奥兰迪亚·余烬纪年》包内**行为彩蛋规则引擎**（逐字搬自游戏仓 `game/core/rule_engine.py`，201 行）。

真源 = 规则（条件→反应）执行半边：`_match_cond` 条件判定 + `fire` 触发器入口（命中执行 action，
复用事件模板引擎）。宿主 `game/core/rule_engine.py` 现在是薄壳（全名单再导出），消费者 2 处
（`game/commands/base.py:511` 函数内、`game/services/battle_settlement.py:36` 顶层）零改动。

正文改动面（**只有宿主取件**，判定/触发逻辑一字未改）：
  ① `_rules()` 的 `from ..data.rules import RULES` → `_host_attr("data.rules", "RULES")`（规则表在宿主数据层）
  ② `_db()` 的 `from .. import db` → 模块级 `db = _HostMod("db")`
  ③ `fire()` 内 `from ..core.event_templates import EventContext, execute_event_template`
     → `_host_attr("core.event_templates", …)`（**跨线**：event_templates 归 B13-L3，别线正在并行搬
       → 按 BRIEF §3 B-5 用宿主句柄；L3 落地后切包内直取）
  ④ 时段判定改经 `_time_check()` 取件（**本线新增 8 行桥**）：`tests/test_v97_05_rule_engine.py:35`
     用 `RE._is_time = lambda span: span == "day"` 覆盖**宿主模块属性**钉死时段；原实现里
     `_match_cond` 直接调本模块全局 `_is_time`，搬包后若仍读包内全局，该覆盖会失效（测试必红）。
     取件优先读宿主薄壳同名函数（它就是包内这一份的再导出），被覆盖时拿到覆盖值。

缺口（报告登记）：规则表 `data/rules.py:RULES`（20 条）包内无域（`content/rules/effect_rules.json`
是另一张表：引擎效果规则 85 条）；`event_templates` 待 L3；计数落库 `event_state` 属存档面（留宿主）。
"""

# ============================================================
# ① 宿主替身口（注入优先 → sys.modules → importlib；**绝不静默空跑**）
#    形状逐字抄 `content/world_cmds.py`（B9 线2 定稿）
# ============================================================
import importlib as _importlib
import sys as _sys

_HOST_PKG = "data.plugins.dragonfall.game"      # 运行时（main.py 的模块路径）
_HOST_PKG_FALLBACK = "game"                     # 测试/工具按 `game.xxx` 直接 import 时
_INJECTED = {}


def bind_host(**objs):
    """宿主薄壳 import 期注入（幂等）——键 = `_HostMod` 的模块名（`content` / `db` / `data`）。"""
    for k, v in (objs or {}).items():
        if v is not None:
            _INJECTED[k] = v


def _host_module(name: str):
    """取宿主子模块（`name` 为空 = 宿主 `game` 包本身）。"""
    if name in _INJECTED:
        return _INJECTED[name]
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        m = _sys.modules.get(prefix if not name else "%s.%s" % (prefix, name))
        if m is not None:
            return m
    last = None
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        try:
            return _importlib.import_module(prefix if not name else "%s.%s" % (prefix, name))
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
                return _importlib.import_module("%s.%s" % (
                    prefix if not mod else "%s.%s" % (prefix, mod), attr))
            except Exception:                   # noqa: BLE001
                continue
        raise


class _HostMod:
    """宿主模块替身（`C` / `db` / `data`）——`C.xxx` 正文一字未改，属性访问时解析。"""

    def __init__(self, name):
        self._name = name

    def __getattr__(self, attr):
        return getattr(_host_module(self._name), attr)

# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年核心层 - rule_engine.py（v97.5：行为彩蛋规则引擎）

规则 = 条件→反应，挂在"触发器"上（策划案 2.1/2.2）：
- 玩家每次关键动作后，引擎检查该动作的规则表，命中则触发惊喜
- 规则纯数据（data/rules.py），加规则 = 加一条 dict，零代码

规则结构：
{
    "id": "rule_xxx",
    "trigger": "explore_done",          # 触发器（见下）
    "cond": {...},                       # 条件（全部可选，组合）
    "chance": 0.5,                       # 额外概率（默认 1.0）
    "count": {"key": "xxx", "gte": 3},   # 连续命中计数：cond 连续命中 gte 次才触发，中断清零
    "action": {"template": "dialog", "params": {...}},  # 复用事件模板引擎
}

cond 支持字段：
- map / map_type      : 地图 id / 类型（str 或 list）
- time                : day(6-18) / night / deep_night(23-5)
- level_min / level_max: 玩家等级区间
- item                : 背包持有物（中文名）
- flag                : 隐藏线 talk_flag 已激活
- event               : 挂点事件特征（如 explore_done 的 empty；battle_win 的 win/lose）
- enemy_tag           : 敌人特征（boss/elite/名称关键词，str 或 list）
- hp_pct_max          : 残血（玩家 hp/max_hp <= 值）
- random_chance       : 条件级概率（与规则级 chance 二选一即可）

触发器（v97.5 已挂）：explore_done / battle_win / gather_done / move_enter / craft_done / quest_deliver
"""
import random

# 延迟导入 data.rules（避免 data 层循环）
RULES = None


def _rules():
    global RULES
    if RULES is None:
        RULES = _host_attr("data.rules", "RULES")   # 真源 `from ..data.rules import RULES as _R`
    return RULES


db = _HostMod("db")          # 真源 `from .. import db`（函数内惰性取件）


def _db():
    return db


def _counter_key(group_id, qq_id, key):
    return f"rule_cnt_{key}_{group_id}_{qq_id}"


def _get_counter(group_id, qq_id, key) -> int:
    db = _db()
    try:
        return int(db.get_event_state(_counter_key(group_id, qq_id, key)) or 0)
    except Exception:
        return 0


def _set_counter(group_id, qq_id, key, val):
    _db().set_event_state(_counter_key(group_id, qq_id, key), str(val))


def _is_time(span: str) -> bool:
    import datetime
    h = datetime.datetime.now().hour
    if span == "day":
        # v105 M23 P2-6：与 time_weather.py 口径对齐（白天 08-18 + 清晨 05-08 + 黄昏 18-20，
        # 即非夜晚时段；night = 20:00-5:00）。原 day 6-18 与 night 18-6 与『时间』面板观感冲突
        return 5 <= h < 20
    if span == "night":
        return h >= 20 or h < 5
    if span == "deep_night":
        return h >= 23 or h < 5
    return True


def _time_check(span: str) -> bool:
    """时段判定取件（本线新增桥，见头注 ④）：宿主薄壳同名函数优先 ——
    `tests/test_v97_05_rule_engine.py:35` 用 `RE._is_time = lambda span: span == "day"`
    覆盖宿主模块属性钉死时段；取不到宿主那份时回落包内 `_is_time`（真源逐字实现）。"""
    try:
        fn = _host_attr("core.rule_engine", "_is_time")
    except Exception:                                # noqa: BLE001
        fn = None
    return (fn or _is_time)(span)


def _match_cond(cond: dict, group_id, qq_id, player: dict, cur_map: dict, evt: dict) -> bool:
    """条件判定；cond 为 None/{} 恒真。"""
    if not cond:
        return True
    # 地图
    if "map" in cond:
        cur = (cur_map or {}).get("id")
        want = cond["map"]
        if isinstance(want, list):
            if cur not in want:
                return False
        elif cur != want:
            return False
    # 地图类型
    if "map_type" in cond:
        cur = (cur_map or {}).get("type")
        want = cond["map_type"]
        if isinstance(want, list):
            if cur not in want:
                return False
        elif cur != want:
            return False
    # 时段
    if "time" in cond and not _time_check(cond["time"]):
        return False
    # 等级
    if "level_min" in cond and int(player.get("level", 1)) < int(cond["level_min"]):
        return False
    if "level_max" in cond and int(player.get("level", 1)) > int(cond["level_max"]):
        return False
    # 持有物
    if "item" in cond:
        db = _db()
        want = cond["item"]
        if isinstance(want, list):
            if not any(db.count_item(group_id, qq_id, i) > 0 for i in want):
                return False
        elif db.count_item(group_id, qq_id, want) <= 0:
            return False
    # 隐藏线 flag
    if "flag" in cond:
        db = _db()
        if not db.get_talk_flags(group_id, qq_id, cond["flag"]):
            return False
    # 事件特征
    if "event" in cond:
        want = cond["event"]
        got = evt.get("event")
        if isinstance(want, list):
            if got not in want:
                return False
        elif got != want:
            return False
    # 敌人特征
    if "enemy_tag" in cond:
        enemy = evt.get("enemy") or {}
        tags = []
        if enemy.get("is_boss"):
            tags.append("boss")
        if enemy.get("is_elite"):
            tags.append("elite")
        tags.append(enemy.get("name", ""))
        tags.append(enemy.get("id", ""))
        tags += [t for t in (enemy.get("tags") or [])]
        want = cond["enemy_tag"]
        if isinstance(want, list):
            if not any(w in tags or any(w in t for t in tags if t) for w in want):
                return False
        elif want not in tags and not any(want in t for t in tags if t):
            return False
    # 残血
    if "hp_pct_max" in cond:
        pct = player.get("hp", 0) / max(1, player.get("max_hp", 1))
        if pct > float(cond["hp_pct_max"]):
            return False
    # 条件级概率
    if "random_chance" in cond and random.random() >= float(cond["random_chance"]):
        return False
    return True


def fire(group_id, qq_id, player, cur_map, trigger, evt=None, hooks=None) -> str:
    """触发器入口：检查该 trigger 下所有规则，命中执行 action（复用事件模板）。

    返回触发文本（同一 trigger 最多触发 1 条，按规则表顺序命中即止）；
    无命中返回 ""。
    """
    evt = evt or {}
    for rule in _rules():
        if rule.get("trigger") != trigger or rule.get("enabled") is False:
            continue
        cond = rule.get("cond") or {}
        matched = _match_cond(cond, group_id, qq_id, player, cur_map, evt)
        count_cfg = rule.get("count")
        if count_cfg:
            # 连续命中计数：cond 命中累计，>=gte 触发并清零；未命中清零（连续中断）
            key = count_cfg["key"]
            cur = _get_counter(group_id, qq_id, key)
            cur = cur + 1 if matched else 0
            _set_counter(group_id, qq_id, key, cur)
            if not (matched and cur >= int(count_cfg.get("gte", 3))):
                continue
            _set_counter(group_id, qq_id, key, 0)  # 触发后清零
        else:
            if not matched:
                continue
            if random.random() >= float(rule.get("chance", 1.0)):
                continue
        # 执行 action（复用事件模板引擎）
        action = rule.get("action") or {}
        tpl = action.get("template")
        if not tpl:
            continue
        EventContext = _host_attr("core.event_templates", "EventContext")
        execute_event_template = _host_attr("core.event_templates", "execute_event_template")
        ctx = EventContext(group_id, qq_id, player, cur_map,
                           params=action.get("params") or {},
                           name=(cur_map or {}).get("name", "此地"),
                           hooks=hooks or {})
        text = execute_event_template(tpl, ctx)
        if text:
            return text
    return ""
