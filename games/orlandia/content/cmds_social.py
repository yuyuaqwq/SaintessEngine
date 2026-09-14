# -*- coding: utf-8 -*-
"""包内社交域命令（`content/cmds_social.py`）—— 原宿主 `game/commands/social.py` 的
**33 条命令**的守卫 / 取参 / 分支业务 / 面板行序 / 渲染整块搬入（B18-L8）。

终态形状（真源 = `overnight/B18_TERMINAL_SHAPE.md` §1.2）：
宿主 `game/commands/social.py` 每条命令只剩 `@declared("<key>")` +
`_BRIDGE.run(self, "<key>", event)` 一行转发；守卫声明、取参、分支、文案全在本模块
（宿主里**零** 文案调用点：`grep -c 'T\\.text\\|T\\.static' game/commands/social.py` = 0）。

本模块与既有实现体的关系（搬家不是重写）
----------------------------------------
B9-L3 / B12-L1 / B12-L4 已经把社交域**大部分实现体**搬进包内，本线只把宿主里**剩下的编排**
（守卫、取参、分支顺序、提示行、列表记账）整块收进来，逐字搬、不改字：

| 既存包内模块 | 本模块用到的东西 |
|---|---|
| `content/social_stall.py` | `market_view_lines` / `market_sell_place` / `market_unsell_pick` / `market_buy_check` / `stall_parse_args` / `stall_place` / `stall_label` / `stall_view_player_lines` / `stall_view_here_lines` / `stall_exchange_check` |
| `content/social_guild.py` | 经宿主同名薄壳 `game/services/guild.py` 取（`_gsd(...)`，与原 `_GSD.<名>` 同一函数对象） |
| `content/social_pet.py` | `pet_view` / `pet_rename_run` / `pet_feed` / `pet_release_run` / `mount_run` |
| `content/social_cmds.py` | `maybe_roll_event` / `world_event_run` / `auction_run` / `bid_run` |
| `content/party.py` | 经宿主同名薄壳 `game/services/party.py` 取（`_party(...)`） |

宿主替身口（包内不 import 宿主，I2）
-----------------------------------
`C` / `db` / `_host_attr` 直接复用 `content/social_cmds.py` 的替身口（与 `cmds_world.py`
复用 `world_cmds` 的替身口同款）；宿主壳对象经 `env.state["shell"]` 取（桥接层透传），
用于**平台/命令层能力**：`_strip_cmd` / `_parse_page` / `_page_items` / `_tip` /
`_record_list_state` / `_player` / `_broadcast` / `_instance_battle_for` / `_unlock_battle`。
用宿主壳同名方法（而不是另写一份）是**逐字节不变**的要求：`_strip_cmd` 要带
`command_aliases`、`_tip` 要读宿主提示池，各写一份必然漂移。

⚠️ 三条命令的处理器是 `async def`（`world_event` / `auction` / `bid`：实现体 `await`
`broadcast` 等平台能力，**真挂起**，同步驱动器不能跑）—— 故按 B18-L3c 战斗族的既有先例
用本地 `_declare` 登记为异步处理器，宿主壳对这三条用 `_BRIDGE.run_async`
（逐条 `yield`，与改造前 `for _line in await …: yield` 的消息切分逐字相同）；
其余 30 条一律同步 `@register` + 宿主壳一行 `_BRIDGE.run`。

行为逐字节不变；证据 = `out/snap_after.json` 对 `out/snap_before.json` 的 129 例
（正常/边界/失败 × 33 条命令，文本 + yield 段数 + stopped + DB 逐行 dump）sha256 相同。
"""
from __future__ import annotations

from . import social_cmds as _SC
from . import social_pet as _SP
from . import social_stall as _SS
from .commands import COMMANDS, register
# 宿主替身口：与 `content/social_cmds.py` 同一份（`C` / `db` 正文一字未改；见该模块头注）
from .social_cmds import C, db, _host_attr


# ============================================================
# ① 取件口（env → 改造前命令体的实参）
# ============================================================
def _shell(env):
    """宿主壳对象（桥接层经 `env.state["shell"]` 注入）——包内取宿主面的**唯一**口。"""
    return (env.state or {}).get("shell")


def _gsd(name):
    """宿主 `game/services/guild.py` 上的一个名字 —— 真源 `_GSD.<name>` 的同义替身。

    `game/services/guild.py` 是 `content/social_guild.py` 的同名单 re-export 薄壳
    （并在 import 期 `bind_host`），故取到的就是原 `_GSD.<name>` 那一个函数对象，
    **且顺带保证包内 `social_guild` 的宿主替身已注入**（惰性解析，调用时才 import）。
    """
    from . import social_guild as _sg
    return getattr(_sg, name)


def _party(name):
    """宿主 `game/services/party.py` 上的一个名字（= 原函数内 `from ..services.party import X`）。"""
    from . import party as _pt
    return getattr(_pt, name)


def _snapshot_one(item_data):
    """宿主 `store.inventory._snapshot_one`（v126.4 单件回流快照裁剪）——调用时解析。"""
    from .persistence.inventory import _snapshot_one
    return _snapshot_one(item_data)


def _final_stats():
    """宿主 `content_rules.panel.player_final_stats`（队伍面板速度值）——调用时解析。"""
    from .panel import player_final_stats
    return player_final_stats


def _declare(key, guards=(), params=()):
    """登记一条**异步**命令（表形状与 `content/commands.py::register` 逐字段相同）。

    唯一差异 = 处理器是 `async def`（`world_event` / `auction` / `bid` 要 `await` 平台广播），
    故不经 `register()`（它把 handler 包成同步 `render_panel(fn(env), env)`）。
    重复 key 直接抛（与 `register()` 同口径）——见 `content/cmds_combat.py::_declare` 同款先例。
    """
    def deco(fn):
        if key in COMMANDS:
            raise KeyError("content.commands：命令 %r 重复登记" % key)
        COMMANDS[key] = {"guards": tuple(guards), "params": tuple(params), "handler": fn}
        return fn
    return deco


# ============================================================
# ② 市场（`market` / `market_sell` / `market_unsell` / `market_buy`）
# ============================================================
@register("market", guards=("hook:player",), params=("cmd=市场", "page"))
def market(env):
    """『市场』：寄售列表（空市 / 分页面板 + tip + 列表记账）。"""
    shell = _shell(env)
    group_id, qq_id = env.group_id, env.uid
    player = env.player
    items = db.market_list(group_id)
    if not items:
        return ["🏪 市场空空如也。『上架 <物品> <价格>』寄售你的宝贝！"]
    raw = shell._strip_cmd(env.raw, "市场")
    page = shell._parse_page(raw)
    page_items, pages, page = shell._page_items(items, page, per_page=5)
    # B9-L3：面板主体在包内（行首编号直接用 DB id，与『购入 <编号>』『下架 <编号>』解析同基准；
    #   原双编号在有过删除/翻页后必然错位 —— report_12 P1-1：『购入 1』买不到第 1 行）。
    lines = _SS.market_view_lines(items, page_items, page, pages, shell._player, group_id)
    lines.append(shell._tip("market"))
    shell._record_list_state(qq_id, "市场", page, pages)
    return ["\n".join(lines)]


@register("market_sell", guards=("hook:player",), params=("cmd=上架",))
def market_sell(env):
    """『上架 <物品名> <价格>』：格式/下限/上限守卫 → 单事务原子上架。"""
    shell = _shell(env)
    group_id, qq_id = env.group_id, env.uid
    player = env.player
    args = shell._strip_cmd(env.raw, "上架").rsplit(None, 1)
    if len(args) < 2 or not args[1].isdigit() or int(args[1]) < C.ECON_CONFIG["market_min_price"]:
        return ["格式：上架 <物品名> <价格>，如『上架 铁剑 500』；价格至少 1 金币"]
    item_name = args[0]
    price = int(args[1])
    # v104R3 P2：上架价格上限——防止 999999999 恶意占坑/诱导高价（上限远超任何物品价值）
    if price > C.ECON_CONFIG["market_price_cap"]:
        return [f"价格太高啦！上架价最多 {C.ECON_CONFIG['market_price_cap']} 金币～"]
    # B9-L3：按名找背包物品 + 单事务原子上架在包内（真源 market_sell 的解析/落库段）
    ok, nm, err = _SS.market_sell_place(group_id, qq_id, item_name, price)
    if not ok:
        return [err]
    return [f"📦 已上架【{nm}】，定价 {price} 金币！\n『市场』查看，『下架 <编号>』撤回"]


@register("market_unsell", guards=("hook:player",), params=("cmd=下架",))
def market_unsell(env):
    """『下架 <编号>』：编号格式 → 目标选取/所有权守卫 → 退还背包（单件快照）。"""
    shell = _shell(env)
    group_id, qq_id = env.group_id, env.uid
    args = shell._strip_cmd(env.raw, "下架").split()
    if not args or not args[0].isdigit():
        return ["格式：下架 <编号>，『市场』查看编号"]
    mid = int(args[0])
    # B9-L3：目标选取 + 所有权守卫在包内
    ok, it, err = _SS.market_unsell_pick(db.market_list(group_id), mid, qq_id)
    if not ok:
        return [err]
    db.market_remove(mid)
    # v126.4 审计 P1：下架回流按 1 件，快照只带 1 条个体（防旧整堆快照破坏不变量）
    db.add_item(group_id, qq_id, it["item_key"], _snapshot_one(it["item_data"]), count=1)
    return [f"↩️ 已下架【{it['item_data'].get('name','?')}】，物品退回背包"]


@register("market_buy", guards=("hook:player",), params=("cmd=购入",))
def market_buy(env):
    """『购入 <编号>』：编号格式 → 存在 → 自买/换摊/异地/金币守卫 → F1 原子购入。"""
    shell = _shell(env)
    group_id, qq_id = env.group_id, env.uid
    player = env.player
    args = shell._strip_cmd(env.raw, "购入").split()
    if not args or not args[0].isdigit():
        return ["格式：购入 <编号>，『市场』查看编号"]
    mid = int(args[0])
    it = db.market_get(mid)
    if not it:
        return ["没有这个物品！可能已被买走。"]
    # B9-L3：自买/换摊/异地/金币守卫在包内
    ok, err = _SS.market_buy_check(it, player, qq_id)
    if not ok:
        return [err]
    # F1 P0-2：原子购入（事务内 校验→扣款→删单→发货），替代原 4 次独立 commit
    ok, err, item_name = db.market_buy_atomic(group_id, qq_id, mid)
    if not ok:
        return [err]
    return [f"🛒 购入成功！【{item_name}】已放入背包(花费 {it['price']} 金币)"]


# ============================================================
# ③ v66 摆摊系统（v167 拆分为 摆卖/摆换 两指令，鱼鱼拍板）
# ============================================================
# 『摆卖 <物/背包序号> <单价> [数量]』= 摆摊出售（金币）
# 『摆换 <物/背包序号> [数量]』       = 摆摊以物换物（无金币价）
# 『收摊』『摊位』『换 <编号> <物品>』 维持不变
# 说明：v167 起废弃老『摆摊』一词（它同时承载卖/换两种语义靠有无价格区分，
# 与数量参数互相歧义——一介散人『咕噜的皇冠』同名事件暴露按名匹配的坑）。
# 现在卖/换动作词分开，参数互不冲突；物品支持背包全局序号（『背包』看到的序号）
# 或名称；同名多件按名会列出候选。老『摆摊』仅作引导提示（v167.1 意见：不静默消失）。
# ★ B9-L3：解析（`_stall_parse_args`）/按序名解析（`_stall_resolve`）/落位
#   （`_stall_place`）/价格标签（`_stall_label`）已进包 `content/social_stall.py`。
@register("stall_deprecated", guards=("hook:player",), params=("cmd=摆摊",))
def stall_deprecated(env):
    """『摆摊』旧词引导（v167 已拆成 摆卖/摆换，不静默消失；priority=5 让位给新指令）。"""
    return ["『摆摊』已拆成两条指令啦：\n"
            "· 摆卖 = 卖金币：『摆卖 <物品/背包序号> <单价> [数量]』\n"
            "· 摆换 = 以物换物：『摆换 <物品/背包序号> [数量]』\n"
            "例：『摆卖 3 500 5』(背包第3件×5个，单价500)｜『摆换 铁剑』"]


@register("stall_sell", guards=("hook:player",), params=("cmd=摆卖",))
def stall_sell(env):
    """『摆卖 <物品/背包序号> <单价> [数量]』：解析 → 必须有金币价 → 落位。"""
    shell = _shell(env)
    group_id, qq_id = env.group_id, env.uid
    player = env.player
    raw = shell._strip_cmd(env.raw, "摆卖").strip()
    parsed = _SS.stall_parse_args(raw, is_sell=True)
    if parsed[0] is None:
        return [parsed[1]]
    item_name, (price, count) = parsed
    if price <= 0:
        return ["摆卖要带金币价！想以物换物用『摆换 <物品> [数量]』～"]
    ok, res = _SS.stall_place(group_id, qq_id, player, item_name, price, count)
    if not ok:
        return [res]
    item_nm, cnt_s, map_name, tip = res
    head = f"🏪 你在『{map_name}』支起了摊位，出售【{item_nm}{cnt_s}】定价 {price} 金币！{tip}\n"
    tail = "『收摊』收摊，『摊位』看看本地谁在摆摊"
    return [head + tail]


@register("stall_exchange_pawn", guards=("hook:player",), params=("cmd=摆换",))
def stall_exchange_pawn(env):
    """『摆换 <物品/背包序号> [数量]』：解析 → 落位（price=0 的换摊）。"""
    shell = _shell(env)
    group_id, qq_id = env.group_id, env.uid
    player = env.player
    raw = shell._strip_cmd(env.raw, "摆换").strip()
    parsed = _SS.stall_parse_args(raw, is_sell=False)
    if parsed[0] is None:
        return [parsed[1]]
    item_name, (price, count) = parsed
    ok, res = _SS.stall_place(group_id, qq_id, player, item_name, 0, count)
    if not ok:
        return [res]
    item_nm, cnt_s, map_name, tip = res
    head = f"🔄 你在『{map_name}』支起了换摊——【{item_nm}{cnt_s}】只换不卖！{tip}\n"
    tail = "『收摊』收摊，别人可用『换 <编号> <物品名>』跟你交换"
    return [head + tail]


@register("stall_close", guards=("hook:player",), params=("cmd=收摊",))
def stall_close(env):
    """『收摊』：无摊位提示 → 逐个回流背包（v126.4 单件快照）。"""
    shell = _shell(env)
    group_id, qq_id = env.group_id, env.uid
    player = env.player
    removed = db.market_remove_by_seller(group_id, qq_id)
    if not removed:
        return ["你现在没有摊位。『摆摊 <物品> <价格>』支起摊位～"]
    for s in removed:
        # v126.4 审计 P1：收摊回流按 1 件，快照只带 1 条个体
        db.add_item(group_id, qq_id, s["item_key"], _snapshot_one(s["item_data"]), count=1)
    names = "、".join(s["item_data"].get("name", "?") for s in removed)
    return [f"🏪 收摊！【{names}】退回背包"]


@register("stall_view", guards=("hook:player",), params=("cmd=摊位",))
def stall_view(env):
    """『摊位 [玩家名]』：指定玩家 → 看他的摊位；无参 → 当前地图所有摊位。"""
    shell = _shell(env)
    group_id, qq_id = env.group_id, env.uid
    player = env.player
    raw = shell._strip_cmd(env.raw, "摊位").strip()
    # 指定玩家 → 看他的摊位
    if raw:
        target = db.find_player_by_name(raw)
        if not target:
            return [f"没找到玩家『{raw}』！"]
        target_id = target["qq_id"]
        tp = db.get_player(group_id, target_id)
        if tp:
            db.market_sync_stall(target_id, tp.get("cur_map", ""))  # 摊位惰性跟随
        stalls = [s for s in db.market_list_by_seller(group_id, target_id) if s.get("map_id")]
        if not stalls:
            return [f"{target['name']} 没有在摆摊。"]
        # B9-L3：面板行在包内
        return ["\n".join(_SS.stall_view_player_lines(target, stalls))]
    # 无参 → 当前地图所有摊位
    cur_map = player.get("cur_map", "")
    stalls = db.market_list(group_id, cur_map)
    if not stalls:
        return ["此地没有摊位。『摆摊 <物品> [价格]』支起你的小摊(不带价格 = 换摊)！"]
    return ["\n".join(_SS.stall_view_here_lines(cur_map, stalls, shell._player, group_id))]


@register("stall_exchange", guards=("hook:player",), params=("cmd=换",))
def stall_exchange(env):
    """以物换物：『换 <摊位编号> <物品名>』——对方摆摊不带价格(换摊)时，用背包物品当面交换。"""
    shell = _shell(env)
    group_id, qq_id = env.group_id, env.uid
    player = env.player
    args = shell._strip_cmd(env.raw, "换").split(None, 1)
    if len(args) < 2 or not args[0].isdigit():
        return ["格式：换 <摊位编号> <物品名>，如『换 3 狼皮』(对方摆摊不带价格 = 换摊)"]
    mid, give_name = int(args[0]), args[1].strip()
    it = db.market_get(mid)
    if not it:
        return [f"没有编号 {mid} 的摊位！『摊位』看看～"]
    # B9-L3：寄售/异地/自己/出售中/背包守卫在包内
    ok, give, err = _SS.stall_exchange_check(it, player, qq_id, group_id, give_name)
    if not ok:
        return [err]
    # F1 P0-2：原子换摊（单事务：删摊主单→摊主货给买家→扣买家给物→给物送摊主），
    # 替代原 4 次独立 commit（并发双请求只首个成交）
    ok, _ename = db.market_exchange_atomic(group_id, qq_id, mid, give["key"], give["data"])
    if not ok:
        return [_ename]
    return [
        f"🔄 交换成功！你用【{give['data']['name']}】换到了【{it['item_data'].get('name','?')}】！\n"
        f"对方的东西已放进你背包，你的【{give['data']['name']}】已送到对方背包～"
    ]


# ============================================================
# ④ 组队（`party` / `party_leave`）
# ============================================================
@register("party", guards=("hook:player",), params=("cmd=组队",))
def party(env):
    """『组队 [对方名字]』：面板 / 创建队伍 / 队长拉人（含战斗与副本守卫）。"""
    shell = _shell(env)
    group_id, qq_id = env.group_id, env.uid
    raw_target = shell._strip_cmd(env.raw, "组队").strip()
    # P4-6：目标解析/战斗守卫/拉人落库收敛 services.party（resolve_party_target/
    # target_in_battle/party_join）；本命令只留解析后分派 + 文案壳。
    resolve_party_target = _party("resolve_party_target")
    party_in_battle = _party("party_in_battle")
    target_in_battle = _party("target_in_battle")
    party_view_lines = _party("party_view_lines")
    party_join = _party("party_join")
    target_qq, err = resolve_party_target(group_id, qq_id, raw_target)
    members = db.party_members(group_id, qq_id)
    if target_qq is None and err is not None:
        return [err]
    if target_qq is None:
        # 面板（无目标）
        if members:
            lines = party_view_lines(group_id, members, get_player=shell._player,
                                     final_stats=_final_stats(), display=C.display)
            return ["\n".join(lines)]
        return ["你还没有队伍～『组队 <对方名字>』邀请同群玩家组队！\n"
                "💡 组队打怪经验＋10%（野外各自为战，仅经验加成，副本内才并肩作战）"]
    if str(target_qq) == str(qq_id):
        return ["不能和自己组队！"]
    tname = shell._player(group_id, target_qq)
    tname_str = tname["name"] if tname else raw_target
    # v104 M04 P1：战斗/副本中禁止组队/拉人——防把副本队长/队员拉走（原队伍解散→副本僵尸化）、
    # 战斗中拉新人（新人未上锁可双线野外战斗）。队员的副本 battle 行存队长名下，
    # 须用 _instance_battle_for 查副本归属；retreated（撤退保留进度）不算战斗中。
    if party_in_battle(group_id, qq_id):
        return ["⚔️ 你正在战斗中！先打完再组队吧～"]
    _tb_state = target_in_battle(group_id, target_qq, inst_battle_hook=shell._instance_battle_for)
    if _tb_state:
        if _tb_state == "instance":
            return [f"⚔️ {tname_str} 正在副本战斗中！等 TA 打完再组队吧～"]
        return [f"⚔️ {tname_str} 正在战斗中！等 TA 打完再组队吧～"]
    # v49：已有队伍时，队长用『组队 <名字>』拉新人（上限 4 人）
    if members:
        if str(members[0]) != str(qq_id):
            return ["你已在队伍中，让队长『组队 <名字>』拉人吧～"]
        ok, lines, _my = party_join(group_id, qq_id, target_qq, tname_str, members,
                                    check_achievements=C.check_achievements)
        if ok:
            return list(lines)
        return [lines[0]]
    # 无队伍：创建 2 人队（store.party_create 内做战斗/已有队伍闸）
    ok, lines, _my = party_join(group_id, qq_id, target_qq, tname_str, members,
                                check_achievements=C.check_achievements)
    if ok:
        return list(lines)
    return [lines[0]]


@register("party_leave", guards=("hook:player",), params=("cmd=退队",))
def party_leave(env):
    """『退队』：副本进行中队长禁止退队 → 退队 + 战斗锁/大陆回滚清理。"""
    shell = _shell(env)
    group_id, qq_id = env.group_id, env.uid
    # P4-6：退队守卫/副本成员判定/清理落库收敛 services.party（party_leave_check/
    # party_leave_inst_member/party_leave_execute）；本命令只留文案壳。
    party_leave_check = _party("party_leave_check")
    party_leave_inst_member = _party("party_leave_inst_member")
    party_leave_execute = _party("party_leave_execute")
    # v104 P1：副本进行中禁止退队——副本 battle 只存队长名下，队长退队会删光队伍行，
    # 之后 _instance_current_members 返回 [] → Boss 不再攻击、击杀/通关零奖励（副本僵尸化）。
    # 非队长（队员）不受限：v104 设计允许队员退队，结算自动剔除退队者。
    blocked, msg = party_leave_check(group_id, qq_id)
    if blocked:
        return [msg]
    # v104 P1：退队者若正挂在副本队伍中（战斗记录存队长名下）→ 退队后同步清其战斗锁
    # （内存锁 + 可能残留的 battle 行），防 24h 锁残留（_in_battle 自愈只在下次交互才触发）
    inst_member = party_leave_inst_member(group_id, qq_id)
    left, ok_lines, err_lines = party_leave_execute(
        group_id, qq_id, inst_member,
        unlock_battle_hook=shell._unlock_battle, player_hook=shell._player,
    )
    if left:
        return [ok_lines[0]]
    return [err_lines[0]]


# ============================================================
# ⑤ 公会（创建/加入/退出/解散/面板/签到/任务/捐献/排行）
# ============================================================
@register("guild_create_cmd", guards=("hook:player",), params=("cmd=创建公会",))
def guild_create_cmd(env):
    """『创建公会 <名字>』：名字 1-8 字 → 已在会 → 等级/金币门槛 → 建会 → 立即判成就。"""
    shell = _shell(env)
    group_id, qq_id = env.group_id, env.uid
    player = env.player
    name = shell._strip_cmd(env.raw, "创建公会").strip()[:8]  # 策划 11 章 3.1：公会名 1-8 字
    if not name:
        return ["格式：创建公会 <名字>，如『创建公会 屠龙勇士』"]
    if db.guild_get_by_member(qq_id):
        return ["你已经在一个公会里啦！先『退出公会』再加入新的～"]
    # B9-L3：等级/金币门槛 + 扣款建会在包内（content/social_guild.py）
    ok, err = _gsd("guild_create_check")(player)
    if not ok:
        return [err]
    ok, gid, err = _gsd("guild_create")(group_id, qq_id, player, name)
    if not ok:
        return [err]
    # v105 M18 P2：创建公会立即判定成就（ach_guild1「加入公会」无需等下次事件）
    C.check_achievements(group_id, qq_id)
    return [
        f"🏰 【公会创建成功】『{name}』！\n"
        f"你成为了公会会长！\n"
        f"{shell._tip('guild')}"
    ]


@register("guild_join_cmd", guards=("hook:player",), params=("cmd=加入公会",))
def guild_join_cmd(env):
    """『加入公会 <公会名>』：名字非空 → 已在会 → 按名查会 + 入会 → 立即判成就。"""
    shell = _shell(env)
    group_id, qq_id = env.group_id, env.uid
    player = env.player
    name = shell._strip_cmd(env.raw, "加入公会").strip()
    if not name:
        return ["格式：加入公会 <公会名>，如『加入公会 屠龙勇士』"]
    if db.guild_get_by_member(qq_id):
        return ["你已经在一个公会里啦！"]
    # B9-L3：按名查会 + 入会在包内
    ok, g, err = _gsd("guild_join")(group_id, qq_id, name)
    if not ok:
        return [err]
    # v105 M18 P2：加入公会立即判定成就（ach_guild1「加入公会」无需等下次事件）
    C.check_achievements(group_id, qq_id)
    return [f"🏰 欢迎加入公会【{g['name']}】！\n{shell._tip('guild')}"]


@register("guild_leave_cmd", guards=("hook:player",), params=("cmd=退出公会",))
def guild_leave_cmd(env):
    """『退出公会』：无会提示 → 会长守卫 → 退会。"""
    shell = _shell(env)
    group_id, qq_id = env.group_id, env.uid
    player = env.player
    g = db.guild_get_by_member(qq_id)
    if not g:
        return ["你不在任何公会里～"]
    # B9-L3：会长守卫 + 退会在包内
    blocked, msg = _gsd("guild_leave_check")(g, qq_id)
    if blocked:
        return [msg]
    _gsd("guild_leave")(g, qq_id)
    return [f"👋 你已退出公会【{g['name']}】。江湖再见！"]


@register("guild_disband_cmd", guards=("hook:player",), params=("cmd=解散公会",))
def guild_disband_cmd(env):
    """『解散公会』：仅会长（leader 离开即解散）。"""
    shell = _shell(env)
    group_id, qq_id = env.group_id, env.uid
    player = env.player
    g = db.guild_get_by_leader(qq_id)
    if not g:
        return ["只有会长才能解散公会！"]
    # B9-L3：解散落库在包内（leader 离开即解散）
    _gsd("guild_disband")(g, qq_id)
    return [f"🏚️ 公会【{g['name']}】已解散……"]


@register("guild_info", guards=("hook:player",), params=("cmd=公会", "page"))
def guild_info(env):
    """『公会 [页]』：成员面板（头/加成/成员行）+ tip + 列表记账。"""
    shell = _shell(env)
    group_id, qq_id = env.group_id, env.uid
    player = env.player
    g = db.guild_get_by_member(qq_id)
    if not g:
        return ["你还没有公会！『创建公会 <名字>』(30级＋1000金币)或『加入公会 <名字>』"]
    members = db.guild_members(g["gid"])
    page = shell._parse_page(shell._strip_cmd(env.raw, "公会"))
    page_items, pages, page = shell._page_items(members, page, per_page=5)
    # B9-L3：面板主体（头/加成/成员行）在包内；分页用引擎底座、tip 与列表记账是命令层 IO
    lines = _gsd("guild_info_lines")(group_id, g, members, page_items, page, pages,
                                     shell._player, g["level"] * C.GUILD_EXP_BASE)
    lines.append(shell._tip("guild"))
    shell._record_list_state(qq_id, "公会", page, pages)
    return ["\n".join(lines)]


@register("guild_sign", guards=("hook:player",), params=("cmd=公会签到",))
def guild_sign(env):
    """『公会签到』：无会提示 → 签到判定/落库（每日一次）。"""
    shell = _shell(env)
    group_id, qq_id = env.group_id, env.uid
    player = env.player
    g = db.guild_get_by_member(qq_id)
    if not g:
        return ["你还没有公会！先『加入公会 <名字>』吧～"]
    # B9-L3：签到判定/落库在包内（含每日一次；数值全走 GUILD_CONFIG）
    ok, lines, err = _gsd("guild_sign")(group_id, qq_id, g)
    if ok:
        return [lines[0]]
    return [err]


@register("guild_task", guards=("hook:player",), params=("cmd=公会任务",))
def guild_task(env):
    """『公会任务』：无会提示 → 任务进度（跨天重置）面板。"""
    shell = _shell(env)
    group_id, qq_id = env.group_id, env.uid
    player = env.player
    g = db.guild_get_by_member(qq_id)
    if not g:
        return ["你还没有公会！先『加入公会 <名字>』吧～"]
    # B9-L3：任务进度（跨天重置）在包内
    ok, lines, err = _gsd("guild_task_view")(group_id, qq_id, g)
    if ok:
        return [lines[0]]
    return [err]


@register("guild_donate_cmd", guards=("hook:player",), params=("cmd=公会捐献",))
def guild_donate_cmd(env):
    """公会捐献：上交材料为公会做贡献，每日一次。

    策划 11 章 4 种公会任务（讨伐/捐献/金币/副本）→ 简化落地：讨伐（击杀自动推进）+ 捐献（上交 3 份材料）。
    进度用 event_state 单独记录（key=guild_donate:{gid}:{qq_id}，值=日期），不与击杀任务共用 task_progress。
    """
    shell = _shell(env)
    group_id, qq_id = env.group_id, env.uid
    player = env.player
    g = db.guild_get_by_member(qq_id)
    if not g:
        return ["你还没有公会！先『加入公会 <名字>』吧～"]
    # B9-L3：捐献判定/扣料/落库在包内（不足文案里的 _tip('guild_donate') 是命令层随机提示壳）
    ok, lines, err, need, total = _gsd("guild_donate")(group_id, qq_id, g)
    if ok:
        return [lines[0]]
    if total is not None:
        # 材料不足（need/total 由包内带回）
        return [err + f"{shell._tip('guild_donate')}"]
    return [err]


@register("guild_rank", guards=(), params=("cmd=公会排行",))
def guild_rank(env):
    """『公会排行』：空榜提示 / 排行行（**无守卫**：注册前可查，声明里也不给 guards）。"""
    shell = _shell(env)
    # B9-L3：排行行在包内
    lines = _gsd("guild_rank_lines")()
    if not lines:
        return ["还没有公会成立！『创建公会 <名字>』建立第一个公会吧～"]
    return ["\n".join(lines)]


# ---------------- v116 公会成长纵深：公会商店 / 公会技能 / 职位体系 ----------------
@register("guild_shop", guards=("hook:player",), params=("cmd=公会商店",))
def guild_shop(env):
    """公会商店：『公会商店』查看，『公会商店 <编号>』用公会积分购买。

    v116 公会成长纵深：积分 = 成员贡献（guild_members.contribute），
    由『公会签到』『公会捐献』获得。B9-L3 起面板/购买在包内（content/social_guild.py）。
    """
    shell = _shell(env)
    group_id, qq_id = env.group_id, env.uid
    g = db.guild_get_by_member(qq_id)
    if not g:
        return ["你还没有公会！先『加入公会 <名字>』吧～"]
    from .persistence.social import guild_get_member as _guild_get_member
    member = _guild_get_member(g["gid"], qq_id)
    raw = shell._strip_cmd(env.raw, "公会商店").strip()
    # 带编号 → 购买
    if raw.isdigit():
        return list(_gsd("guild_shop_buy")(group_id, qq_id, g, member, int(raw)))
    if not member:
        return ["你不是公会正式成员～"]
    lines = _gsd("guild_shop_lines")(g, member)
    lines.append(shell._tip("guild_shop"))
    return ["\n".join(lines)]


@register("guild_skill_view", guards=("hook:player",), params=("cmd=公会技能",))
def guild_skill_view(env):
    """公会技能：查看技能列表与等级门槛/积分价目。

    v116 说明：技能购买记录无处可靠持久化（guild_members 无通用 JSON 列，
    且本轮禁改 connection.py 表结构），故本轮只做【展示 + 数据】，购买落地留待下轮。
    战斗加成挂接同样延后（需在战斗结算统一钩取成员已学技能）。B9-L3 起面板在包内。
    """
    shell = _shell(env)
    group_id, qq_id = env.group_id, env.uid
    g = db.guild_get_by_member(qq_id)
    if not g:
        return ["你还没有公会！先『加入公会 <名字>』吧～"]
    lines = _gsd("guild_skill_lines")(g)
    lines.append("💡 技能经会长安排后逐步开放；战斗加成的挂接正在开发中～")
    return ["\n".join(lines)]


@register("guild_appoint", guards=("hook:player",), params=("cmd=公会任命",))
def guild_appoint(env):
    """公会任命：会长任命成员为 副会长/精英。

    用法：『公会任命 <成员名> <职位>』；职位可选 副会长/精英。
    门槛：副会长需公会 Lv.3（GUILD_CONFIG.vice_leader_level），精英无门槛。
    """
    shell = _shell(env)
    group_id, qq_id = env.group_id, env.uid
    g = db.guild_get_by_leader(qq_id)
    if not g:
        return ["只有会长才能任命职位！"]
    raw = shell._strip_cmd(env.raw, "公会任命").strip()
    parts = raw.rsplit(None, 1)
    if len(parts) < 2:
        return ["格式：公会任命 <成员名> <职位>，职位=副会长/精英"]
    name_arg, role_arg = parts
    # B9-L3：role 映射/等级门槛/成员校验/任命落库全在包内
    role = _gsd("guild_appoint_check_role")(role_arg)
    if not role:
        return ["可任命职位：副会长、精英。成员是默认职，不需任命～"]
    ok, err = _gsd("guild_appoint_level_ok")(g, role)
    if not ok:
        return [err]
    tm, target, err = _gsd("guild_find_member")(g, name_arg)
    if err:
        return [err]
    if target["qq_id"] == qq_id:
        return ["会长不需要任命自己～"]
    if tm["role"] == role:
        return [f"『{target['name']}』已经是{role_arg}了～"]
    _label, _icon = _gsd("guild_appoint")(g, target, role)
    return [f"{_icon} 任命成功！『{target['name']}』已晋升为公会【{_label}】！"]


@register("guild_demote", guards=("hook:player",), params=("cmd=公会免职",))
def guild_demote(env):
    """公会免职：会长将 副会长/精英 降回成员。用法：『公会免职 <成员名>』。"""
    shell = _shell(env)
    group_id, qq_id = env.group_id, env.uid
    g = db.guild_get_by_leader(qq_id)
    if not g:
        return ["只有会长才能免职！"]
    name_arg = shell._strip_cmd(env.raw, "公会免职").strip()
    if not name_arg:
        return ["格式：公会免职 <成员名>"]
    # B9-L3：成员校验/免职落库在包内
    tm, target, err = _gsd("guild_find_member")(g, name_arg)
    if err:
        return [err]
    if tm["role"] not in ("vice_leader", "elite"):
        return [f"『{target['name']}』是成员，无需免职～"]
    _gsd("guild_demote")(g, target)
    return [f"📉 已免去『{target['name']}』的职位，降回普通成员～"]


# ============================================================
# ⑥ 宠物与坐骑（`pet_view` / `pet_rename` / `pet_feed` / `pet_release` / `mount_cmd`）
# ============================================================
@register("pet_view", guards=("hook:player",), params=("cmd=宠物",))
def pet_view(env):
    """『宠物』：面板（含饱食度衰减结算+持久化 / 品质·出处 / 技能 / 亲密度 / 加成行）。"""
    shell = _shell(env)
    group_id, qq_id = env.group_id, env.uid
    player = env.player
    # B9-L3：面板（含饱食度衰减结算+持久化 / 品质·出处 / 技能 / 亲密度 / 加成行）在包内
    lines, has_pet = _SP.pet_view(qq_id)
    if not has_pet:
        return ["\n".join(lines)]
    lines.append(shell._tip("pet"))
    return ["\n".join(lines)]


@register("pet_rename", guards=("hook:player",), params=("cmd=宠物改名",))
def pet_rename(env):
    """『宠物改名 <名字>』：存在守卫 / 取前 8 字 / 落库全在包内。"""
    shell = _shell(env)
    group_id, qq_id = env.group_id, env.uid
    player = env.player
    # B12-L1：存在守卫 / 取前 8 字 / 落库在包内（content/social_pet.py:pet_rename_run）
    raw_name = shell._strip_cmd(env.raw, "宠物改名")
    return list(_SP.pet_rename_run(qq_id, raw_name))


@register("pet_feed", guards=("hook:player",), params=("cmd=喂养",))
def pet_feed(env):
    """『喂养 <食物>』：无参食物清单 / 批量双格式解析 / 白名单 / 喂养结算全在包内。"""
    shell = _shell(env)
    group_id, qq_id = env.group_id, env.uid
    player = env.player
    mat_name = shell._strip_cmd(env.raw, "喂养").strip()
    # B9-L3：无参食物清单 / 批量双格式解析 / 食物白名单 / 喂养结算（含升级循环）全在包内
    return list(_SP.pet_feed(group_id, qq_id, mat_name))


@register("pet_release", guards=("hook:player",), params=("cmd=放生",))
def pet_release(env):
    """『放生』：存在守卫 + 放生落库 + 文案在包内（图鉴记录保留）。"""
    shell = _shell(env)
    group_id, qq_id = env.group_id, env.uid
    player = env.player
    # B12-L1：存在守卫 + 放生落库 + 文案在包内（content/social_pet.py:pet_release_run）
    # 图鉴记录保留（24 章三：放生后宠物蛋可重新掉落，图鉴记录保留）
    return list(_SP.pet_release_run(qq_id))


@register("mount_cmd", guards=("hook:player",), params=("cmd=坐骑",))
def mount_cmd(env):
    """『坐骑 / 骑乘 <名称> / 下马』：骑乘/下马/面板三支全在包内。"""
    shell = _shell(env)
    group_id, qq_id = env.group_id, env.uid
    player = env.player
    msg = env.raw.get_message_str()
    raw = shell._strip_cmd(env.raw, "骑乘") if msg.startswith(("骑乘", "[At:")) else ""
    # B9-L3：骑乘/下马/面板三支的判定与文案全在包内；`_tip("mount")` 包内按需惰性取
    #（「有坐骑」分支才取随机提示 —— 提前取会多消耗一次 random 抽签）
    return list(_SP.mount_run(group_id, qq_id, player, raw, msg, msg.strip(),
                              lambda: shell._tip("mount")))


# ============================================================
# ⑦ 世界事件 / 拍卖 / 竞拍（实现体 `await` 平台广播 → 异步处理器，见模块头注）
# ============================================================
@_declare("world_event", guards=("hook:player",), params=("cmd=事件",))
async def world_event(env):
    """『事件』：先惰性调度（notice 由 maybe_roll_event 产出）→ 事件面板。"""
    shell = _shell(env)
    group_id = env.group_id
    # B12-L1：惰性调度（含过期拍卖先结算后清槽）/ 事件面板 / DISPLAYS 展示全在包内
    notice = await _SC.maybe_roll_event(group_id, shell._broadcast)
    return await _SC.world_event_run(group_id, notice, shell._broadcast, shell)


@_declare("auction", guards=("hook:player",), params=("cmd=拍卖",))
async def auction(env):
    """『拍卖』：面板主体 / 过期结算+广播全在包内；`_tip("auction")` 按真源**惰性**取。"""
    shell = _shell(env)
    # B12-L1：面板主体 / 过期结算+广播全在包内；`_tip("auction")` 按真源**惰性**取
    #（只有「开张」分支才抽提示，提前取会多消耗一次 random 抽签）
    return await _SC.auction_run(env.group_id, shell._player,
                                 lambda: shell._tip("auction"), shell._broadcast)


@_declare("bid", guards=("hook:player",), params=("cmd=竞拍",))
async def bid(env):
    """『竞拍 <编号> <金币>』：底价/金币/重复出价守卫 + 被超越退还 + 一口价 + 过期结算。"""
    shell = _shell(env)
    args = shell._strip_cmd(env.raw, "竞拍").split()
    # B12-L1：底价/金币/自己重复出价守卫 + 被超越退还 + 一口价成交 + 过期结算全在包内
    return await _SC.bid_run(env.group_id, env.uid, env.player, args,
                             shell._player, shell._broadcast)
