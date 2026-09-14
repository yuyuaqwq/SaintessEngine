# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— social 命令族的**世界事件 / 拍卖 / 竞拍**实现（B12-L1，2026-09-14）。

真源：游戏仓 `game/commands/social.py` 的 `class SocialCmds`（只读）。本模块 = 该文件里
**B9-L3 之后仍未搬的宿主独有实现**（世界事件惰性调度 / 事件面板 / 拍卖面板 / 竞拍状态机），
逐字搬成模块级函数；宿主 `game/commands/social.py` 现在只剩「注册 + 取玩家 + 一行转发 + 渲染」。

搬的边界
--------
* **搬**（真源行号 → 本模块）：
  `social.py:744-781 _maybe_roll_event` → `maybe_roll_event`
  `social.py:783-816 world_event`       → `world_event_run`
  `social.py:818-858 auction`           → `auction_run`
  `social.py:865-962 bid`               → `bid_run`
  （`social.py:860-863 _settle_auction` 是既有兼容壳，未搬；本模块直接调
   `services.auction.settle_auction`，与该壳同义。）
* **不搬（留宿主）**：命令注册（`@declared`）· `self._uid` / `self._player` 取玩家 ·
  `event.plain_result` 渲染 · `_strip_cmd` 解析 · `_tip` 随机提示壳 · `_broadcast`（平台发送）。

正文改动面（**只有两类**，与 `content/world_cmds.py` 同款）
----------------------------------------------------------
1. 命令方法开头那两行「取 (group_id, qq_id) + `self._player(...)`」→ 提到宿主薄壳当参数传进来；
   `self._player` 在正文里以 `player_lookup` 回调出现（拍卖最高价/被超越者姓名）。
2. 宿主模块引用 → 惰性替身：`from .. import db` → `db = _HostMod("db")`；
   `from .. import content as C` → `C = _HostMod("content")`；
   函数内 `from ..core.world_event_templates import INITIALIZERS/DISPLAYS`、
   `from ..services.auction import settle_auction/settle_expired_auction`
   → `_host_attr("core.world_event_templates", …)` / `_host_attr("services.auction", …)`（调用时解析）。

⚠️ 缺口（报告同步登记）
----------------------
* `C.WORLD_EVENT_POOL`（`game/data/world.py:8`，14 条）—— ★ W4（2026-09-14）已切包内门面
  `content/catalog_b143.py`（B14-3 建 `game_config.world` 组，门禁逐条逐序相等）。
  `C.generate_equip`（宿主 content 函数面，函数名不切）仍走宿主 `C` 句柄，不在包侧另起第二份表。
* `DISPLAYS` / `INITIALIZERS`（`game/core/world_event_templates.py`）归 **B13-L3**；
  `services.auction`（`settle_auction` / `settle_expired_auction`）归 **B12-L5** —— 两条线都未落地，
  本模块按跨线规则走**宿主句柄惰性替身**；待它们进包后，把 `_host_attr(...)` 换成包内直取即可。

用法::

    from content import social_cmds as SC
    SC.bind_host(db=db, content=C)                 # 宿主薄壳 import 期注入（幂等）
    notice = await SC.maybe_roll_event(group_id, broadcast=self._broadcast)
    for line in await SC.world_event_run(group_id, notice, self._broadcast, self):
        ...
"""
from __future__ import annotations

import importlib
import sys
import time

# ★ W4（2026-09-14）：`C.WORLD_EVENT_POOL` → 包内门面（真源 `game/data/world.py:8`）
from . import catalog_b143 as _cat_b143


# ============================================================
# ① 宿主替身口（注入优先 → sys.modules → importlib；**绝不静默空跑**）
# ============================================================
_HOST_PKG = "data.plugins.dragonfall.game"      # 运行时（main.py 的模块路径）
_HOST_PKG_FALLBACK = "game"                     # 测试/工具按 `game.xxx` 直接 import 时
_INJECTED = {}


def bind_host(**objs):
    """宿主薄壳 import 期注入（幂等）——键 = `_HostMod` 的模块名（`content` / `db`）。"""
    for k, v in (objs or {}).items():
        if v is not None:
            _INJECTED[k] = v


def _host_module(name: str):
    """取宿主子模块（`name` 为空 = 宿主 `game` 包本身，真源 `from .. import X` 那一类）。"""
    if name in _INJECTED:
        return _INJECTED[name]
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        full = prefix if not name else "%s.%s" % (prefix, name)
        m = sys.modules.get(full)
        if m is not None:
            return m
    last = None
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        try:
            return importlib.import_module(prefix if not name else "%s.%s" % (prefix, name))
        except Exception as exc:                # noqa: BLE001
            last = exc
    raise RuntimeError("social_cmds：宿主模块 %s 取不到（%s）——拒绝静默空跑" % (name, last))


def _host_attr(mod: str, attr: str):
    """宿主模块属性 —— 真源「函数内 `from ..<mod> import <attr>`」的同义替身（调用时解析）。"""
    m = _host_module(mod)
    try:
        return getattr(m, attr)
    except AttributeError:
        for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
            try:
                return importlib.import_module("%s.%s" % (
                    prefix if not mod else "%s.%s" % (prefix, mod), attr))
            except Exception:                   # noqa: BLE001
                continue
        raise


class _HostMod:
    """宿主模块替身（`C` / `db`）——`C.xxx` / `db.xxx` 正文一字未改，属性访问时解析。"""

    def __init__(self, name):
        self._name = name

    def __getattr__(self, attr):
        return getattr(_host_module(self._name), attr)


C = _HostMod("content")     # 真源 `from .. import content as C`
db = _HostMod("db")         # 真源 `from .. import db`


# ============================================================
# ② 世界事件惰性调度（真源 `social.py:744-781 _maybe_roll_event`）
# ============================================================

async def maybe_roll_event(group_id: str, broadcast) -> str:
    """惰性事件调度：无事件且冷却到期 → 概率触发新事件。返回公告文本(无则空串)。

    `broadcast` = 命令层 `self._broadcast`（平台发送能力，留宿主）；
    过期拍卖结算走 `services.auction.settle_auction`（他线 B12-L5，宿主句柄惰性取）。
    """
    import random as _rnd
    cur = db.get_world_event(include_expired=True)
    now = int(time.time())
    # 当前事件过期 → 清除（v104R3 P1-1：过期拍卖必须先走结算——
    # 否则出价金币随 bids 记录一起销毁，永久丢失；Boss 事件由各自指令处理）
    if cur and now >= cur["ends_at"]:
        if cur["etype"] == "auction":
            # v181 P4-5：结算本体+过期判定已下沉 services.auction；过期拍卖在此先结算后清槽
            try:
                _lines = _host_attr("services.auction", "settle_auction")(cur, group_id)
                if _lines:
                    await broadcast(f"🏪 【拍卖行 · 落槌结算】\n{_lines}")
            except Exception as _e:                 # noqa: BLE001
                pass
        db.clear_world_event()
        cur = None
    if cur:
        return ""
    # 冷却检查：上次事件结束时间 + 随机 30~90 分钟
    last_end = db.get_event_state("last_event_end")
    cooldown = 1800 + _rnd.randint(0, 3600)
    if last_end and now < int(last_end) + cooldown:
        return ""
    # 60% 概率触发
    if _rnd.random() > 0.6:
        db.set_event_state("last_event_end", str(now))
        return ""
    evt = _rnd.choice(_cat_b143.WORLD_EVENT_POOL)
    ends = now + evt["duration"]
    # v100.2：事件 data 初始化数据化 → core/world_event_templates.py INITIALIZERS
    init_fn = _host_attr("core.world_event_templates", "INITIALIZERS").get(evt["type"])
    data = init_fn(_rnd) if init_fn else {}
    db.save_world_event(evt["type"], ends, data)
    db.set_event_state("last_event_end", str(ends))
    return f"\n🌍 【世界事件】{evt['icon']} {evt['name']}！\n{evt['desc']}"


# ============================================================
# ③ 事件面板（真源 `social.py:783-816 world_event`）—— 返回待 yield 的消息 list
# ============================================================

async def world_event_run(group_id: str, notice: str, broadcast, host_self):
    """『事件』：先惰性调度（notice 由 `maybe_roll_event` 产出）→ 事件面板。

    `host_self` = 宿主命令实例（`DISPLAYS` 的展示函数签名是 `fn(self, cur, lines, group_id)`，
    真源就是命令类实例 —— 见 `game/core/world_event_templates.py` 头注）。
    """
    # 新事件刚触发 → 广播到所有注册群（当前群已通过 yield 看到）
    if notice.strip():
        try:
            await broadcast(notice.strip(), exclude_group=group_id)
        except Exception as _e:                     # noqa: BLE001
            pass
    cur = db.get_world_event()
    now = int(time.time())
    if not cur:
        return ["🌍 大陆风平浪静……\n" + notice]
    evt = next((e for e in _cat_b143.WORLD_EVENT_POOL if e["type"] == cur["etype"]), None)
    left = max(0, cur["ends_at"] - now)
    mm, ss = divmod(left, 60)
    lines = [f"🌍 【世界事件】{evt['icon']} {evt['name']}(剩余 {mm}分{ss}秒)" if evt else "🌍 世界事件",
             f"━━━━━━━━━━━━"]
    if evt:
        lines.append(evt["desc"])
    lines.append("")
    # v98.5：etype 展示数据化 → core/world_event_templates.py DISPLAYS
    disp_fn = _host_attr("core.world_event_templates", "DISPLAYS").get(cur["etype"])
    if disp_fn:
        disp_fn(host_self, cur, lines, group_id)
    lines.append("")
    lines.append(notice)
    return ["\n".join(lines)]


# ============================================================
# ④ 拍卖面板（真源 `social.py:818-858 auction`）—— 返回待 yield 的消息 list
# ============================================================

async def auction_run(group_id: str, player_lookup, tip_fn, broadcast):
    """『拍卖』：未开张时先结过期拍卖；开张则列在拍物品与当前最高价。

    `player_lookup` = `self._player`（查最高价者姓名）；`tip_fn` = `lambda: self._tip("auction")`
    （**惰性**：真源只在「开张」分支取随机提示，过期结算分支返回前不取 —— 提前取会多消耗一次
    `random` 抽签，提示池随机序列错位）。
    """
    cur = db.get_world_event()
    now = int(time.time())
    if not cur:
        # 是否有过期的拍卖待结算（过期结算+清槽收敛至 services.auction.settle_expired_auction）
        lines = _host_attr("services.auction", "settle_expired_auction")(group_id)
        if lines:
            broadcast_text = f"🏪 【拍卖行 · 落槌结算】\n{lines}"
            try:
                await broadcast(broadcast_text)
            except Exception:                       # noqa: BLE001
                pass
            return [broadcast_text]
        return ["🏪 拍卖行暂未开张。世界事件出现『神秘拍卖行』时再来吧！(『事件』查看)"]
    if cur["etype"] != "auction":
        return ["🏪 拍卖行暂未开张。世界事件出现『神秘拍卖行』时再来吧！(『事件』查看)"]
    items = cur["data"].get("items", [])
    left = cur["ends_at"] - now
    mm, ss = divmod(left, 60)
    lines = [f"🏪 【神秘拍卖行】(剩余 {mm}分{ss}秒)", "━━━━━━━━━━━━"]
    for it in items:
        top = max(it["bids"].values()) if it["bids"] else 0
        top_name = "无人出价"
        if it["bids"]:
            top_qq = max(it["bids"], key=it["bids"].get)
            tp = player_lookup(group_id, top_qq)
            top_name = f"{tp['name'] if tp else top_qq}({top})"
        lines.append(f"📦 {it['id']}. {it['name']}")
        lines.append(f"   底价 {it['base']} ｜ 最高：{top_name} ｜ 一口价 {it['buyout']}")
        lines.append(f"   『竞拍 {it['id']} <金币>』出价")
    lines.append("")
    lines.append(tip_fn())
    return ["\n".join(lines)]


# ============================================================
# ⑤ 竞拍状态机（真源 `social.py:865-962 bid`）—— 返回待 yield 的消息 list
# ============================================================

async def bid_run(group_id: str, qq_id: str, player, args, player_lookup, broadcast):
    """『竞拍 <编号> <金币>』：冻金 / 被超越退还 / 自己重复出价退旧扣新 / 一口价立即成交。

    `player` = 命令层取到的玩家快照（真源 `self._player(group_id, qq_id)`）；
    `args` = `self._strip_cmd(event, "竞拍").split()`；`player_lookup` = `self._player`。
    """
    cur = db.get_world_event()
    now = int(time.time())
    if not cur:
        # 过期的拍卖待结算（过期结算+清槽收敛至 services.auction.settle_expired_auction）
        lines = _host_attr("services.auction", "settle_expired_auction")(group_id)
        if lines:
            broadcast_text = f"🏪 【拍卖行 · 落槌结算】\n{lines}"
            try:
                await broadcast(broadcast_text)
            except Exception:                       # noqa: BLE001
                pass
            return [broadcast_text]
        return ["🏪 拍卖行暂未开张。"]
    if cur["etype"] != "auction":
        return ["🏪 拍卖行暂未开张。"]
    if len(args) < 2 or not args[0].isdigit() or not args[1].isdigit():
        return ["格式：竞拍 <编号> <金币>，如『竞拍 1 5000』(『拍卖』查看编号)"]
    item_id = int(args[0])
    amount = int(args[1])
    items = cur["data"].get("items", [])
    it = next((x for x in items if x["id"] == item_id), None)
    if not it:
        return ["没有这个拍卖品！『拍卖』查看当前物品～"]
    if amount < it["base"]:
        return [f"出价不能低于底价 {it['base']} 金币！"]
    if player["gold"] < amount:
        return [f"你只有 {player['gold']} 金币，出不起 {amount}！"]
    # 自己重复出价：新价不能低于自己当前出价（防刷金币：先退旧价再扣新价 = 净赚差价）
    if str(qq_id) in it["bids"] and amount < it["bids"][str(qq_id)]:
        return [f"不能低于自己当前出价 {it['bids'][str(qq_id)]} 金币！"]
    # v104R3 P2：新出价必须严格超过当前最高价（同价出价无意义且锁金币到结算——先到者胜，
    # 后到者金币被冻结直到结算/被超越；直接拒绝，复验点5）
    if it["bids"] and str(qq_id) not in it["bids"]:
        _top_qq = max(it["bids"], key=it["bids"].get)
        if it["bids"][_top_qq] >= amount:
            _tp = player_lookup(group_id, _top_qq)
            _top_name = _tp["name"] if _tp else _top_qq
            return [f"当前最高出价是 {_top_name} 的 {it['bids'][_top_qq]} 金币——出价必须超过最高价！"]
    # 被超越 → 退还当前最高出价者（并移除其出价记录）
    if it["bids"]:
        top_qq = max(it["bids"], key=it["bids"].get)
        if it["bids"][top_qq] < amount and top_qq != str(qq_id):
            p_top = player_lookup(group_id, top_qq)
            if p_top:
                db.update_player(group_id, top_qq, gold=p_top["gold"] + it["bids"][top_qq])
            del it["bids"][top_qq]
    # 自己重复出价 → 退还自己的先前出价
    if str(qq_id) in it["bids"]:
        prev = it["bids"][str(qq_id)]
        db.update_player(group_id, qq_id, gold=player["gold"] + prev)
        del it["bids"][str(qq_id)]
        player = player_lookup(group_id, qq_id)
    # 扣款并记录
    db.update_player(group_id, qq_id, gold=player["gold"] - amount)
    it["bids"][str(qq_id)] = amount
    db.save_world_event(cur["etype"], cur["ends_at"], cur["data"])
    # 一口价立即成交
    if amount >= it["buyout"]:
        # 退还其他出价者
        for qq2, amt2 in it["bids"].items():
            if qq2 != str(qq_id):
                p2 = player_lookup(group_id, qq2)
                if p2:
                    db.update_player(group_id, qq2, gold=p2["gold"] + amt2)
        equip = it.get("equip") or C.generate_equip(it["slot"], it.get("lv", 30), it.get("quality", "purple"))
        import uuid as _uuid2
        db.add_item(group_id, qq_id, f"eq_{_uuid2.uuid4().hex[:8]}", equip, count=1)
        it["bids"] = {str(qq_id): amount}
        cur["data"]["items"] = [x for x in items if x["id"] != item_id]
        db.save_world_event(cur["etype"], cur["ends_at"], cur["data"])
        return [f"💰 一口价成交！你以 {amount} 金币拍得【{it['name']}】！\n📦 装备已放入背包(『背包』查看)"]
    # v104 P1：出价后如实提示——未超过当前最高(含同价被先到者压)则提示"当前最高仍是 X"，
    # 不再无条件谎报"当前最高"
    _top_qq = max(it["bids"], key=it["bids"].get)
    if _top_qq == str(qq_id):
        return [f"💰 出价成功！你在【{it['name']}】上出价 {amount} 金币，当前最高！\n(若被超越将自动退还)"]
    _tp = player_lookup(group_id, _top_qq)
    _top_name = _tp["name"] if _tp else _top_qq
    return [f"💰 出价成功！你在【{it['name']}】上出价 {amount} 金币，当前最高仍是 {_top_name}({it['bids'][_top_qq]})。\n(若被超越将自动退还)"]
