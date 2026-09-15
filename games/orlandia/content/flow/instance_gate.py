# -*- coding: utf-8 -*-
"""包内副本准入（`content/flow/instance_gate.py`）—— 逐字搬自游戏仓
`game/core/instance_gate.py`（366 行），只改「宿主耦合 → 调用方传参」+「文案口」两类东西。

真源（只读）：`qqbot/data/plugins/dragonfall/game/core/instance_gate.py`

宿主耦合替身接口（调用方传什么 / 缺省行为）
| 真源宿主耦合 | 包内替身 | 调用方传什么 | 缺省（不传） |
|---|---|---|---|
| `from . import texts as T` → `game/core/texts.py`（宿主聚合 + ERROR 日志） | 本文件自带 `_Texts`（`T`） | `set_text_table(TextTable(...))` 换表（可带 `on_miss` 打宿主日志） | 包内 `content/data/texts.json` + 引擎 `saintess_engine.text.TextTable` |
| `from .. import db` + `db.get_inventory(group_id, qq_id)`（:56/:61） | `find_instance_key_item(inventory, key_item, items=None)` | 背包条目 list（含 `key`/`data`/`count`） | `items=None` → 包内 `content/data/items.json` |
| `from .. import db` + `db.get_achievements(group_id, qq_id)`（:76/:79） | `instance_cleared(achievements, inst_key)` | 成就记录 list（含 `ach_key`/`progress`） | —— |
| 宿主内容层 `ITEMS` | `items=` 参数 | `dict`：物品 key → `{name: …}` | 包内 `content/data/items.json` |
其余（`saintess_engine.run.Admission` / `Rule`）不变。

★ 缺口：包内尚无统一文案装载模块（`content/texts.py`）——本文件是自带的最小装载口；
   真源缺 key 时打 ERROR 日志（宿主日志通道），包内不引宿主日志 → 由调用方经 `on_miss` 接。
"""
from __future__ import annotations

import json
import os

from saintess_engine.text import TextTable

_HERE = os.path.dirname(os.path.abspath(__file__))            # <pkg>/content/flow
_DATA_DIR = os.path.join(os.path.dirname(_HERE), "data")      # <pkg>/content/data


def _read_json(name: str, default):
    """读包内数据域 `content/data/<name>`（缺文件/坏 JSON → default，不抛）。"""
    try:
        with open(os.path.join(_DATA_DIR, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


class _Texts:
    """包内文案表口（替身：真源是 `game/core/texts.py` 的模块级 `text()/static()`）。

    真源读 `game/data/text_specs.json`，包内读 `content/data/texts.json`
    （同一份导出域；`instance.*` 26 条逐字相等，见验收【4】）。
    缺 key → 引擎 `TextTable.render` 的默认分支（返回 key 本身，玩家截图可见）。
    """

    def __init__(self):
        self._t = None

    def table(self) -> TextTable:
        if self._t is None:
            self._t = TextTable(_read_json("texts.json", {}) or {},
                                name="orlandia-texts")
        return self._t

    def set_table(self, table) -> None:
        self._t = table

    def text(self, key: str, **slots) -> str:
        return self.table().render(key, **slots)

    def static(self, key: str) -> str:
        return self.table().render(key)


T = _Texts()


def set_text_table(table) -> None:
    """换文案表（调用方挂 `on_miss` 打宿主 ERROR 日志 / 热重载用）。"""
    T.set_table(table)


def _default_items() -> dict:
    """包内物品域（真源经宿主内容层 `ITEMS` 取 —— 同源导出物）。"""
    return _read_json("items.json", {}) or {}


from typing import Optional

from saintess_engine.run import Admission, Rule

# 文案表：真源 `from . import texts as T`（game/core/texts.py）→ 包内 `T`（见文件头 §文案口）

# ======================================================================
# 一、钥匙与通关豁免（v141 抽出，v185 保持不变）
# ======================================================================


def find_instance_key_item(inventory, key_item: str, items=None) -> Optional[dict]:
    """三路匹配背包钥匙条目：data.name == key_item / it.key == key_item /
    ITEMS[key].name == key_item，count >= 1。命中返回背包条目 dict
    （含 key/data/count，供开本扣钥匙），未命中返回 None。

    宿主耦合替身：真源签名 `find_instance_key_item(group_id, qq_id, key_item)`，
    背包来自 `db.get_inventory(group_id, qq_id)`、ITEMS 映射来自宿主内容层
    `game.content.ITEMS` —— 包内两者都由调用方/包内数据给：`inventory` = 背包条目
    list（含 key/data/count）；`items` 缺省 = 包内 `content/data/items.json`
    （与宿主同源导出物）。
    """
    if not key_item:
        return None
    _items = _default_items() if items is None else (items or {})
    for it in (inventory or []):
        it_name = (it.get("data") or {}).get("name", "")
        if it_name == key_item or it.get("key") == key_item \
                or _items.get(it.get("key"), {}).get("name") == key_item:
            if (it.get("count") or 0) >= 1:
                return it
    return None


def instance_cleared(achievements, inst_key: str) -> bool:
    """玩家是否已通关某副本（inst_clear_<inst_key> 首通记录 progress >= 1）。

    与 instance.py 开本免钥匙 / world.py 门禁免钥匙同口径（成就表首通记录）。
    宿主耦合替身：真源签名 `instance_cleared_qq(group_id, qq_id, inst_key)` +
    `db.get_achievements(group_id, qq_id)`；包内成就记录由调用方给（普通 list，
    元素含 `ach_key` / `progress`）。
    """
    if not inst_key:
        return False
    return any(a.get("ach_key") == f"inst_clear_{inst_key}" and a.get("progress", 0) >= 1
               for a in (achievements or []))


# ======================================================================
# 二、措辞（**唯一真源 = game/data/text_specs.json**；本文件只传槽位）
# ======================================================================
# v185 起：原先逐字硬编码在这里的 26 条文案搬进 `game/data/text_specs.json`（文案表），
# 由 `game/core/texts.py` 装载引擎 `saintess_engine.text.TextTable` 渲染。
#   ⇒ 本文件**不再出现任何一句玩家可见文案**：改文案只动 JSON，改逻辑才动这里。
#   ⇒ 「一字未改」由 `tests/test_v185_instance_admission.py` 的 805 格逐格冻结比对证明
#     （对照物 = 旧实现冻结体里的同一句话，逐字）。


def stamina_short_msg(cost: int, cur: int, action: str = "行动") -> str:
    """体力不足提示（与 `commands/base._spend_stamina` 同源：唯一入口）。"""
    return T.text("instance.stamina_short", cost=cost, cur=cur, action=action)


def text_party_need(inst: dict, min_players: int, max_players: int) -> str:
    return T.text("instance.party_need", name=inst["name"],
                  min_players=min_players, max_players=max_players)


def text_leader_only() -> str:
    return T.static("instance.leader_only")


def text_too_few(inst: dict, min_players: int, have: int) -> str:
    return T.text("instance.too_few", name=inst["name"], min_players=min_players,
                  gap=min_players - have)


def text_too_many(inst: dict, max_players: int, have: int) -> str:
    return T.text("instance.too_many", name=inst["name"], max_players=max_players, have=have)


def text_member_no_char() -> str:
    return T.static("instance.member_no_char")


def text_member_level(name: str, level: int, need_lv: int) -> str:
    return T.text("instance.member_level", name=name, level=level, need_lv=need_lv)


def text_member_dead(name: str) -> str:
    return T.text("instance.member_dead", name=name)


def text_member_in_battle(name: str, roster: str) -> str:
    return T.text("instance.member_in_battle", name=name, roster=roster)


def text_member_prof_wait(name: str, prof_label: str, left: int) -> str:
    return T.text("instance.member_prof_wait", name=name, prof_label=prof_label, left=left)


def text_key_seal(inst: dict, key_item: str, key_source: str) -> str:
    return T.text("instance.key_seal", name=inst["name"], key_item=key_item,
                  key_source=key_source)


def text_entry_hint(inst: dict, map_name: str, subarea_name: str, subarea_id: str) -> str:
    # 子区域回退口径留在代码里（表只管句壳，不出现取值逻辑）
    return T.text("instance.entry_hint", map_name=map_name, sa=subarea_name or subarea_id,
                  name=inst["name"])


def text_walk_deny(inst_name: str, tip: str) -> str:
    return T.text("instance.walk_deny", inst_name=inst_name, tip=tip)


def text_bad_profile() -> str:
    """角色快照异常（`commands/instance.py` 兜底路径同源）。"""
    return T.static("instance.bad_profile")


# ======================================================================
# 三、开本链（instance.py『副本 <名字>』）
# ======================================================================


def resolve_open_members(inst: dict, my_key: str, party) -> tuple:
    """开本的**队伍解析**（旧 `_instance_start` 前段逐字搬来）。

    返回 `(members, deny_text)`：`deny_text` 非空表示这一关就被拒（调用方直接渲染）。
    语义（勿改）：
      - 纯单人副本（min≤1 且 max≤1）→ 无队也能开，成员 = 自己
      - 弹性副本（min≤1 < max）无队 → 成员 = 自己
      - 有队：非队长 → 拒；人数越界 → 拒（两条不同措辞）
    """
    min_players = inst.get("min_players", 2)
    max_players = inst.get("max_players", 3)
    members = [str(m) for m in (party or ())]
    if min_players <= 1 and max_players <= 1:
        return [str(my_key)], ""
    if not members:
        if min_players <= 1:
            return [str(my_key)], ""
        return [], text_party_need(inst, min_players, max_players)
    if str(members[0]) != str(my_key):
        return members, text_leader_only()
    if len(members) < min_players:
        return members, text_too_few(inst, min_players, len(members))
    if len(members) > max_players:
        return members, text_too_many(inst, max_players, len(members))
    return members, ""


def member_rule(member, ctx, *, with_prof_wait: bool = True) -> Rule:
    """单个成员的**一条规则**（等级 → 血量 → 战斗中 → 副业等待，逐字旧文案）。

    ★ 一个成员一条规则 = 保持旧的「按队员逐个过四关」顺序语义
    （若改成「按检查项逐个过队员」，m1 掉血 + m2 等级不够时会报 m2 的等级，
      与旧行为不同 —— 门禁把这个顺序钉住）。

    `with_prof_wait=False`：不开本场景（恢复旧进度）不查副业等待 —— 与旧实现一致，勿合并。
    """
    need_lv = int(ctx["inst"].get("lv", 0) or 0)
    roster = "、".join(
        (ctx["player_of"](mm) or {}).get("name", mm) for mm in (ctx.get("members") or [])
    )

    def _check(c):
        p = c["player_of"](member)
        if not p:
            return False
        if int(p.get("level", 0) or 0) < need_lv:
            return False
        if int(p.get("hp", 0) or 0) <= 0:
            return False
        if c["in_battle"](member):
            return False
        if with_prof_wait:
            _pw = c["prof_wait"](member)
            if _pw and int(_pw.get("finish", 0)) > int(c["now"]):
                return False
        return None

    def _reason(c):
        p = c["player_of"](member) or {}
        if not p:
            return text_member_no_char()
        if int(p.get("level", 0) or 0) < need_lv:
            return text_member_level(p.get("name", member), p.get("level", 0), need_lv)
        if int(p.get("hp", 0) or 0) <= 0:
            return text_member_dead(p.get("name", member))
        if c["in_battle"](member):
            return text_member_in_battle(p.get("name", member), roster)
        _pw = c["prof_wait"](member) or {}
        _left = int(_pw.get("finish", 0)) - int(c["now"])
        return text_member_prof_wait(p.get("name", member),
                                     c["prof_label"](_pw.get("type")), _left)

    return Rule(f"member:{member}", check=_check, reason=_reason)


def resume_admission(ctx: dict) -> Admission:
    """**恢复旧进度**的准入（旧语义，勿与开本合并）：
    人数在 `[min_players, max_players]` 内 + 每名成员「有角色 / 等级够 / 未倒 / 不在战斗中」。
    **不查副业等待**、**不查钥匙/位置/体力**（旧实现如此）。判定用 `v.ok`，理由仅作诊断。
    """
    inst = ctx["inst"]
    _min = int(inst.get("min_players", 2) or 0)
    _max = int(inst.get("max_players", 3) or 0)
    rules = [Rule("size", check=lambda c: _min <= len(c.get("members") or ()) <= _max,
                  reason="人数不符合副本要求")]
    rules += [member_rule(m, ctx, with_prof_wait=False) for m in (ctx.get("members") or ())]
    return Admission(rules, name="resume")


def key_free_note(ctx: dict) -> str:
    """开本时「已通关免钥匙」的提示（旧实现在钥匙关的 else 分支里给；无钥匙需求的副本 → ""）。"""
    inst = ctx.get("inst") or {}
    if not inst.get("key_item"):
        return ""
    return "" if (ctx.get("key_entry") is not None and not ctx.get("cleared")) else T.static("instance.key_free_note")


def key_rule(ctx) -> Rule:
    """钥匙关（判定 + 副作用）。副作用 `drop_key` **只在全过之后**执行（v185 修白扣）。"""
    _has_key = ctx.get("key_entry") is not None
    _cleared = bool(ctx.get("cleared"))
    inst = ctx["inst"]
    if not inst.get("key_item"):
        # 该副本本来就不需要钥匙（旧实现整段跳过）→ 无条件通过、无副作用
        return Rule("key", check=lambda c: True)
    return Rule(
        "key",
        check=lambda c: _has_key or _cleared,
        reason=lambda c: text_key_seal(inst, inst.get("key_item", ""),
                                       inst.get("key_source", "？？？")),
        # 有钥匙且未通关才扣；已通关免钥匙（旧口径）
        consume=(lambda c: c["drop_key"]()) if (_has_key and not _cleared) else None,
    )


def open_admission(ctx: dict) -> Admission:
    """开本准入链：成员规则（每队员一条）→ 钥匙 → 入口位置 → 体力。

    `ctx["members"]` 由 `resolve_open_members` 解析好后填入；
    副作用 `drop_key` / `pay_stamina` 由调用方提供（都在全过之后才被调）。
    ★ 措辞在**构建时**从 ctx 取好（check 时才用 `c`），于是「构建用的 ctx」与
      「check 传的 ctx」即使不是同一个对象，措辞也不会 KeyError。
    """
    rules = [member_rule(m, ctx) for m in (ctx.get("members") or ())]
    rules.append(key_rule(ctx))
    _entry_hint = ctx.get("entry_hint", "")
    _cost = int(ctx.get("stamina_cost", 20))
    rules.append(Rule("entry", check=lambda c: bool(c.get("entry_ok")),
                      reason=_entry_hint))
    rules.append(Rule(
        "stamina",
        check=lambda c: int(c.get("stamina", 0) or 0) >= _cost,
        reason=lambda c: stamina_short_msg(_cost, int(c.get("stamina", 0) or 0), "进入副本"),
        consume=lambda c: c["pay_stamina"](),
    ))
    return Admission(rules, name="open")


# ======================================================================
# 四、徒步进图链（world.py `_instance_gate_block`）
# ======================================================================


def walk_admission(ctx: dict) -> Admission:
    """徒步进图三档（任一满足即放行，**只校验持有、不扣钥匙**）：
    任务放行 → 持钥匙 → 已通关豁免 —— 三选一，故 `mode="any"`（旧实现是「任一命中即放行」）。"""
    _deny = text_walk_deny(ctx.get("inst_name") or "副本", ctx.get("tip", ""))
    return Admission([
        Rule("quest", check=lambda c: bool(c.get("quest_open")), reason=_deny),
        Rule("key", check=lambda c: bool(c.get("key_held")), reason=_deny),
        Rule("cleared", check=lambda c: bool(c.get("cleared")), reason=_deny),
    ], name="walk", mode="any", reason=_deny)


# ======================================================================
# 五、加入战斗链（instance.py `加入战斗`）
# ======================================================================


def join_admission(ctx: dict) -> Admission:
    """加入战斗准入链（顺序与措辞逐字旧版）：

    队伍 → 队员视角可加入（目标战斗存在 / 同一副本）→ 队长视角拒 →
    战斗状态（结束 / 已撤退 / 非副本）→ 重复加入 → 满员 → 敌方全灭 → 0 血 → 角色数据。

    `ctx` 键：`party_members`（原始队伍）/ `my_key` / `battle_of_leader()`（返回队长战斗行或 None）/
    `self_inst_id()`（自己所在副本 id 或 None）/ `st`（队员视角由链填入）/ `enemies_alive()` /
    `player`。链内会写 `ctx["st"]`（供调用方复用，避免二次取数）。
    """

    def _battle_ok(c):
        """队员视角：队长行存在且是副本战斗 → 把 state 填进 ctx。"""
        row = c["battle_of_leader"]()
        if not row or (row.get("state") or {}).get("type") != "instance":
            return False
        c["st"] = row["state"]
        return True

    def _same_inst(c):
        return c["self_inst_id"]() == (c["st"] or {}).get("inst_id")

    def _st_state(c):
        return c["st"] or {}

    return Admission([
        Rule("party", check=lambda c: bool(c.get("party_members")),
             reason=lambda c: T.static("instance.no_party")),
        Rule("member_view", check=lambda c: str((c.get("party_members") or [""])[0]) != str(c["my_key"]),
             reason=lambda c: T.static("instance.i_am_leader")),
        Rule("has_battle", check=_battle_ok, reason=lambda c: T.static("instance.no_joinable")),
        Rule("same_inst", check=_same_inst, reason=lambda c: T.static("instance.join_closed")),
        Rule("not_over", check=lambda c: not (_st_state(c).get("over") or _st_state(c).get("cleared")),
             reason=lambda c: T.static("instance.battle_over")),
        Rule("not_retreated", check=lambda c: not _st_state(c).get("retreated"),
             reason=lambda c: T.static("instance.battle_retreated")),
        Rule("is_instance", check=lambda c: _st_state(c).get("type") == "instance",
             reason=lambda c: T.static("instance.battle_not_instance")),
        Rule("not_dupe", check=lambda c: str(c["my_key"]) not in (_st_state(c).get("players") or {}),
             reason=lambda c: T.static("instance.already_in")),
        Rule("not_full", check=lambda c: len((_st_state(c).get("members") or [])) < 4,
             reason=lambda c: T.static("instance.battle_full")),
        Rule("enemy_alive", check=lambda c: bool(c["enemies_alive"]()),
             reason=lambda c: T.static("instance.no_enemy_left")),
        Rule("hp", check=lambda c: int((c.get("player") or {}).get("hp", 0) or 0) > 0,
             reason=lambda c: T.static("instance.join_dead")),
        Rule("profile", check=lambda c: bool(c.get("player")), reason=lambda c: T.static("instance.bad_profile")),
    ], name="join")
