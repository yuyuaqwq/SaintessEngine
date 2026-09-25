# -*- coding: utf-8 -*-
"""行为彩蛋「规则触发」形状（`ext_achieve` ③）：条件判定 + 触发序列。

从数据包 `content/rule_engine.py` 抽入（2026-09-24 B2b）。进包的只有**「怎么判、按什么序判」**：

* `match_cond` —— 一条规则的条件字典逐字段判定
* `fire`       —— 触发器入口：按表序取该 trigger 下第一条命中的规则，交给调用方执行

★ 本模块**零内容词表、零数据包 import**。搬之前它读的七样东西全是这款游戏自己的（下详），
现在一律由调用方 `bind(...)` 注入 —— 形状只知道「有条规则命中 ⇒ 请执行这个模板」。

条件字段（**数据里写什么，形状就读什么**；改名等于改数据 ⇒ 属于形状契约，不是实现细节）：

    map / map_type          场地 id / 场地类型（str 或 list）
    time                    时段名（怎么判交给注入的 `is_time`）
    level_min / level_max   等级区间
    item                    持有物（走注入的 `count_item`）
    flag                    对白旗标已置（走注入的 `talk_flag`）
    event                   事件特征（str 或 list）
    enemy_tag               敌人特征：boss / elite / 名称 / id / tags（子串命中）
    hp_pct_max              残血比例上限
    random_chance           条件级概率

规则字段：`trigger` / `enabled` / `cond` / `count{key,gte}`（连续命中计数：命中累计、
`>=gte` 触发并清零、未命中清零）/ `chance`（额外概率，与 `count` 二选一）/ `action{template,params}`。

绑定面（`bind(...)` 七个句柄，缺一不可 —— 未装配就取用 ⇒ **当场报错**，不给
「空表 = 静默不触发」这种把「装配忘了」伪装成「今天没彩蛋」的降级）：

    rules        () -> list 或 list 本身   规则表（给 list 时形状持有**同一份对象**，就地改即刻生效）
    is_time      (span) -> bool            时段判定（白天/夜晚的钟点边界是玩法的设定 ⇒ 调用方定）
    counter_get  (gid, qid, key) -> int    连续命中计数读
    counter_set  (gid, qid, key, val)      连续命中计数写
    count_item   (gid, qid, item) -> int   背包持有数
    talk_flag    (gid, qid, flag) -> bool  对白旗标是否已置
    fire_event   (template, params, gid, qid, player, cur_map, hooks) -> str   执行动作模板

为什么是这七样：搬前它们分别是 `_rules()` · `_is_time` · `_get_counter` · `_set_counter` ·
`db.count_item` · `db.get_talk_flags` · `EventContext + execute_event_template` ——
前六样读的是这款游戏自己的数据与存档，末一样要在游戏侧拼事件上下文。
"""
from __future__ import annotations

import random

__all__ = ["bind", "fire", "match_cond"]

#: 注入的句柄表；`None` = 未装配（取用即报错）
_INJ = None


def bind(rules, is_time, counter_get, counter_set, count_item, talk_flag, fire_event):
    """注入七个句柄（装配期一次；重复 bind 以最后一次为准）。

    `rules` 例外：可以是**规则表本身**（容器，形状持有同一份对象）或返回它的零参可调用
    （惰性取值，逐次现读）。其余六个必须是可调用。
    """
    global _INJ
    if not callable(rules) and not isinstance(rules, (list, tuple)):
        raise TypeError("rules 必须是规则表容器或返回它的零参可调用，收到 %s"
                        % type(rules).__name__)
    given = {"rules": rules, "is_time": is_time, "counter_get": counter_get,
             "counter_set": counter_set, "count_item": count_item,
             "talk_flag": talk_flag, "fire_event": fire_event}
    for name, fn in given.items():
        if name != "rules" and not callable(fn):
            raise TypeError("句柄 %s 必须是可调用，收到 %s" % (name, type(fn).__name__))
    _INJ = given


def _h(name):
    """取句柄；未装配 ⇒ 当场报错。"""
    if _INJ is None:
        raise RuntimeError(
            "ext_achieve.rule 未装配：先 bind(rules=…, is_time=…, counter_get=…, counter_set=…, "
            "count_item=…, talk_flag=…, fire_event=…) 再取用（fail-loud）")
    return _INJ[name]


def _rules():
    r = _h("rules")
    return r() if callable(r) else r


def match_cond(cond: dict, group_id, qq_id, player: dict, cur_map: dict, evt: dict) -> bool:
    """条件判定；cond 为 None/{} 恒真（逐字搬自数据包 `_match_cond`，只有取件点换成注入句柄）。"""
    if not cond:
        return True
    # 场地
    if "map" in cond:
        cur = (cur_map or {}).get("id")
        want = cond["map"]
        if isinstance(want, list):
            if cur not in want:
                return False
        elif cur != want:
            return False
    # 场地类型
    if "map_type" in cond:
        cur = (cur_map or {}).get("type")
        want = cond["map_type"]
        if isinstance(want, list):
            if cur not in want:
                return False
        elif cur != want:
            return False
    # 时段（钟点边界在注入方）
    if "time" in cond and not _h("is_time")(cond["time"]):
        return False
    # 等级
    if "level_min" in cond and int(player.get("level", 1)) < int(cond["level_min"]):
        return False
    if "level_max" in cond and int(player.get("level", 1)) > int(cond["level_max"]):
        return False
    # 持有物
    if "item" in cond:
        count_item = _h("count_item")
        want = cond["item"]
        if isinstance(want, list):
            if not any(count_item(group_id, qq_id, i) > 0 for i in want):
                return False
        elif count_item(group_id, qq_id, want) <= 0:
            return False
    # 对白旗标
    if "flag" in cond:
        if not _h("talk_flag")(group_id, qq_id, cond["flag"]):
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
        # ★ 2026-09-25（审计 E3）：原先这里把 `is_boss` / `is_elite` 两个**游戏字段**映射成
        #   "boss" / "elite" 两个**游戏标签** —— 引擎替内容做了命名 ✗。现在标签由内容侧写在
        #   `enemy["traits"]`（或 `enemy["tags"]`）上，引擎**原样透传**，判定交给规则声明。
        tags = [t for t in (enemy.get("traits") or [])]
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
    """触发器入口：检查该 trigger 下所有规则，命中执行 action（执行器由调用方注入）。

    返回触发文本（同一 trigger 最多触发 1 条，按规则表顺序命中即止）；
    无命中返回 ""。
    """
    evt = evt or {}
    for rule in _rules():
        if rule.get("trigger") != trigger or rule.get("enabled") is False:
            continue
        cond = rule.get("cond") or {}
        matched = match_cond(cond, group_id, qq_id, player, cur_map, evt)
        count_cfg = rule.get("count")
        if count_cfg:
            # 连续命中计数：cond 命中累计，>=gte 触发并清零；未命中清零（连续中断）
            key = count_cfg["key"]
            cur = _h("counter_get")(group_id, qq_id, key)
            cur = cur + 1 if matched else 0
            _h("counter_set")(group_id, qq_id, key, cur)
            if not (matched and cur >= int(count_cfg.get("gte", 3))):
                continue
            _h("counter_set")(group_id, qq_id, key, 0)  # 触发后清零
        else:
            if not matched:
                continue
            if random.random() >= float(rule.get("chance", 1.0)):
                continue
        # 执行 action（模板执行器由调用方注入）
        action = rule.get("action") or {}
        tpl = action.get("template")
        if not tpl:
            continue
        text = _h("fire_event")(tpl, action.get("params") or {}, group_id, qq_id,
                                player, cur_map, hooks)
        if text:
            return text
    return ""
