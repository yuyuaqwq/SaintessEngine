# -*- coding: utf-8 -*-
"""账本形状（`ext_achieve.ledger`）：**解锁 / 领取 / 计数**三段。

从数据包 `content/achievements.py` 抽入（2026-09-24 B2-S4）。进包的是**「怎么遍历、怎么判、
怎么写回、怎么算」**，不是「有哪些条目、发了什么」：

* `check(group_id, qq_id, player=None, extra=None)` —— 遍历条目表：未解锁且条件成立 ⇒ 落库
  解锁（`claimed=0` 待领取）并把奖励摘要挂到条目**副本**上返回（**不自动发放**，与真源
  v101.22 拍板一致）；落库失败某条 ⇒ 跳过该条继续往后判。
* `claim(group_id, qq_id)` —— 领取全部待领取：三态机筛可领档位 → 汇总三类奖励 → 发放 →
  升级结算 → 落库 → 拼回执。返回 `(lines, err)`（`err` 是**提示语**不是异常）。
* `labels(qq_id)` —— 已解锁条目的标签名列表（**源表序**，无标签的跳过）。
* `points(qq_id)` —— 已解锁条目的点数合计（每条的权重由调用方给）。
* `bind(...)` —— 装配期一次注入二十个句柄。

★ 本模块**零内容词表、零数据包 import**（本包门禁 `[5]` 是 AST 扫描）：条目表、条件判据、
存档读写、奖励发放、升级结算、文案、显示名一律由调用方注入 —— 形状只知道「表、判据、
存档口」三者之间的关系。装配前取用 ⇒ **当场报错**（`RuntimeError`），不给「空表 = 今天
没有可解锁的」这种把「装配忘了」伪装成「条件不满足」的降级（与 `rule` / `ext_effect` 同一套纪律）。

绑定面（二十个句柄，缺一不可）
--------------------------------
| 句柄 | 签名 | 它替掉的真源取件 |
|---|---|---|
| `entries` | 条目表（`list`/`tuple` 或 `() -> list`） | `ACHIEVEMENTS` |
| `ledger_of` | `(group_id, qq_id) -> list[{id, claimed, progress}]` | `db.get_achievements` + 三字段归一 |
| `mark` | `(gid, qid, key, progress, claimed)` | `db.set_achievement` |
| `player_of` | `(gid, qid) -> dict \| None` | `db.get_player` |
| `stats_of` | `(gid, qid) -> dict` | `db.get_stats` |
| `profs_of` | `(gid, qid) -> dict` | `db.get_professions` |
| `save_player` | `(gid, qid, player)` | `db.update_player(…11 个字段…)` |
| `cond_of` | `(player, stats, profs, extra, cond, gid) -> bool` | `cond_met` |
| `clear_of` | `(key) -> str \| None` | 「已通关记录键 → 副本 id」那套键名约定 |
| `weight_of` | `(entry) -> int` | 「普通 1 / 隐藏 2」的点数权重 |
| `label_of` | `(entry) -> str \| None` | 条目的标签名（`entry.get("title")`） |
| `name_of` | `(key) -> str` | 物品 key → 显示名（域读口） |
| `line_of` | `(entry) -> str` | 领取回执里的一行 |
| `reward_of` | `(entry) -> (exp, currency, items)` | 奖励 dict 的三条支路 |
| `phrase` | `(slot, **slots) -> str` | `texts.text/static`（文案真源在数据包） |
| `machine` | `(unlocked, claimed) -> 三态机` | `collect.TierBoard`（`.claim(entry) -> bool`，幂等） |
| `enrich` | `(gid, qid, player) -> dict` | 领奖前把加成字段挂到玩家副本上 |
| `grant` | `(gid, qid, items, lines) -> (lines, ok)` | `reward.grant_items_batch` |
| `levelup` | `(gid, qid, player) -> (lines, player)` | `gameplay_rules.check_player_level_up` |
| `payout` | `(gid, qid, player, exp, currency) -> dict` | 把两类奖励记进玩家记录的字段 |

条目表的**字段名**是形状契约（与 `ext_achieve.rule` 的 `cond` 字段同一性质）：`id` / `cond`；
奖励的三条支路由 `reward_of` 现取、字段名形状不认（那三个键名是这款游戏的 schema）。
`label_of` / `weight_of` 单列成句柄，正是因为「标签字段叫什么」「隐藏类怎么加权」是内容侧的活。
"""
from __future__ import annotations

__all__ = ["bind", "check", "claim", "labels", "points"]

#: 注入的句柄表；`None` = 未装配（取用即报错）
_INJ = None

#: 二十个句柄的名字（bind 的必填面 + 门禁的 fail-loud 面共用同一份）
REQUIRED = (
    "entries", "ledger_of", "mark", "player_of", "stats_of", "profs_of",
    "save_player", "cond_of", "clear_of", "weight_of", "label_of", "name_of",
    "line_of", "reward_of", "phrase", "machine", "enrich", "grant", "levelup",
    "payout",
)


def bind(**handles):
    """注入句柄（装配期一次；重复 bind 以最后一次为准）。

    `entries` 例外：可以是**条目表本身**（容器，形状持有同一份对象，就地改即刻生效）或返回
    它的零参可调用（惰性取值，逐次现读）。其余句柄必须是可调用；多给/少给都当场报错
    （少给会变成「某条路静默不走」，那正是本形状拒绝的降级）。
    """
    global _INJ
    missing = [n for n in REQUIRED if n not in handles]
    if missing:
        raise TypeError("bind 缺句柄：%s（二十个句柄缺一不可）" % ", ".join(missing))
    unknown = sorted(set(handles) - set(REQUIRED))
    if unknown:
        raise TypeError("bind 收到未知句柄：%s" % ", ".join(unknown))
    for name in REQUIRED:
        fn = handles[name]
        if name == "entries":
            if not callable(fn) and not isinstance(fn, (list, tuple)):
                raise TypeError("entries 必须是条目表容器或返回它的零参可调用，收到 %s"
                                % type(fn).__name__)
        elif not callable(fn):
            raise TypeError("句柄 %s 必须是可调用，收到 %s" % (name, type(fn).__name__))
    _INJ = dict(handles)


def _h(name):
    """取句柄；未装配 ⇒ 当场报错。"""
    if _INJ is None:
        raise RuntimeError(
            "%s 未装配：先 bind(%s) 再取用（fail-loud）"
            % (__name__, ", ".join(REQUIRED)))
    return _INJ[name]


def _entries():
    e = _h("entries")
    return e() if callable(e) else e


def _rows(group_id, qq_id):
    """账本行（归一到 `{id, claimed, progress}`）；读口异常**不吞**（各调用点自己定口径）。"""
    return list(_h("ledger_of")(group_id, qq_id) or [])


def _unlocked_loose(qq_id) -> set:
    """宽松口径的已解锁集合：读口异常 ⇒ 空集（真源 `labels` / `points` 两处同款）。"""
    try:
        return {r["id"] for r in _rows(None, qq_id)}
    except Exception:
        return set()


def labels(qq_id) -> list:
    """已解锁条目的标签名列表（源表序；无标签的条目跳过）。"""
    unlocked = _unlocked_loose(qq_id)
    return [lb for lb in (_h("label_of")(a) for a in _entries()
                          if a["id"] in unlocked) if lb]


def points(qq_id) -> int:
    """已解锁条目的点数合计（每条的权重由调用方给）。"""
    unlocked = _unlocked_loose(qq_id)
    return sum(_h("weight_of")(a) for a in _entries() if a["id"] in unlocked)


def _reward_txt(entry) -> str:
    """奖励摘要（`经验 +N、币 +M、物品名×K…` + 领取提示）；无可发之物 ⇒ 空串。"""
    exp, currency, items = _h("reward_of")(entry)
    if not (exp or currency or items):
        return ""
    parts = []
    if exp:
        parts.append(_h("phrase")("reward_exp", exp=exp))
    if currency:
        parts.append(_h("phrase")("reward_currency", amount=currency))
    if items:
        for key, count in items.items():
            parts.append("%s×%s" % (_h("name_of")(key), count))
    return "、".join(parts) + _h("phrase")("claim_hint")


def check(group_id, qq_id, player=None, extra=None) -> list:
    """事件后调用：返回本次新解锁的条目（副本，带奖励摘要 `_reward_txt`）。

    `player` 缺省 ⇒ 走 `player_of` 现取（取不到 ⇒ 空结果，不抛）；
    `extra` 会被补上 `inst_ids` = 账本里 `clear_of` 认出来的 + 本次事件自带的 `inst_id`
    （条件判据读它，所以这一格必须在判定前写好）。
    """
    if player is None:
        player = _h("player_of")(group_id, qq_id)
    if not player:
        return []
    player["qq_id"] = player.get("qq_id") or qq_id
    stats = _h("stats_of")(group_id, qq_id) or {}
    profs = _h("profs_of")(group_id, qq_id) or {}
    extra = extra or {}
    try:
        unlocked = {r["id"] for r in _rows(group_id, qq_id)}
    except Exception:
        unlocked = set()
    cleared = set()
    for key in unlocked:
        cid = _h("clear_of")(key)
        if cid:
            cleared.add(cid)
    if extra.get("inst_id"):
        cleared.add(extra["inst_id"])
    extra["inst_ids"] = cleared
    new_ones = []
    for a in _entries():
        if a["id"] in unlocked:
            continue
        if not _h("cond_of")(player, stats, profs, extra, a["cond"], group_id):
            continue
        try:
            _h("mark")(group_id, qq_id, a["id"], 1, 0)
        except Exception:
            continue
        unlocked.add(a["id"])
        a = dict(a)
        a["_reward_txt"] = _reward_txt(a)
        new_ones.append(a)
    return new_ones


def claim(group_id, qq_id) -> tuple:
    """领取全部待领取的奖励；返回 `(lines, err)`（`err` 非空 = 提示语，不是异常）。

    三态机（`machine`）只负责「这一档现在能不能领」的幂等判定；账目汇总、发放、升级结算、
    落库、拼回执都在本形状。**形状不吞异常** —— 降级策略交给调用方（本游戏的调用方保留了
    真源那套「记日志 + 回一句失败文案」的兜底）。
    """
    rows = _rows(group_id, qq_id)
    pending = [r for r in rows if not r.get("claimed")]
    if not pending:
        return [], _h("phrase")("none")
    machine = _h("machine")({r["id"] for r in rows},
                            {r["id"] for r in rows if r.get("claimed")})
    table = {a["id"]: a for a in _entries()}
    claimable = []
    for r in pending:
        a = table.get(r["id"])
        if a is not None and machine.claim(a):
            claimable.append(a)
    if not claimable:
        # 没有可领之物的待领项直接落成「已领」，免得永久挂在待领位（与真源同口径）
        for r in pending:
            try:
                _h("mark")(group_id, qq_id, r["id"], r.get("progress", 1), 1)
            except Exception:
                pass
        return [], _h("phrase")("none")
    player = _h("player_of")(group_id, qq_id)
    if not player:
        return [], _h("phrase")("need_register")
    player = _h("enrich")(group_id, qq_id, dict(player))
    exp_gain = 0
    currency_gain = 0
    all_items = {}
    for a in claimable:
        exp, currency, items = _h("reward_of")(a)
        exp_gain += exp
        currency_gain += currency
        for key, count in (items or {}).items():
            all_items[key] = int(all_items.get(key, 0)) + int(count)
    item_lines = []
    reward_ok = True
    if all_items:
        try:
            item_lines, reward_ok = _h("grant")(group_id, qq_id, all_items, item_lines)
        except Exception:
            reward_ok = False
    player = _h("payout")(group_id, qq_id, player, exp_gain, currency_gain)
    lv_logs, player = _h("levelup")(group_id, qq_id, player)
    _h("save_player")(group_id, qq_id, player)
    for a in claimable:
        _h("mark")(group_id, qq_id, a["id"], 1, 1)
    head = _h("phrase")("claim_head", exp=exp_gain)
    if currency_gain:
        head += _h("phrase")("claim_currency", amount=currency_gain)
    lines = [head]
    if item_lines:
        lines.append(_h("phrase")("items_head"))
        lines += item_lines
        if not reward_ok:
            lines.append(_h("phrase")("items_partial_fail"))
    for a in claimable:
        lines.append(_h("line_of")(a))
    lines.append("")
    lines += lv_logs
    return lines, ""
