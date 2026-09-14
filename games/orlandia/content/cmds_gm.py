# -*- coding: utf-8 -*-
"""包内 GM/运营命令域（`content/cmds_gm.py`，B18-L4）—— 19 条 `gm_*` 命令的守卫/取参/业务/**渲染**。

终态形状（真源 = `overnight/B18_TERMINAL_SHAPE.md` §1.2）：宿主 `game/commands/gm.py` 里
每条命令只剩 `@declared("gm_<key>")` + `_BRIDGE.run(self, "gm_<key>", event)` 一行转发。

**GM 权限判定 = 守卫形状（本线关键口径）**
------------------------------------------
判定实现**唯一真源**仍在包内 `content/gm.py::gm_auth`（「白名单为空 → 默认拒绝一切 GM 指令」的
v104.1 M24 语义，含两条逐字提示语）。本模块把它接到**守卫**：`guards=("hook:gm",)` →
包侧 `content/guards.py::GUARDS["gm"]` → 无权玩家**在 handler 之前**被拦下并原样回话，
宿主里**不再有**「取 uid → 判权限 → 分支回话」这段业务分支（旧宿主每条命令开头 4 行）。

宿主面（**过渡期**，I2：包内不 import 宿主，只经下面几个口取件；宿主壳对象经
`env.state["shell"]` 透传，与 tower 的 `_open_tower_battle` 同款）：
  * 身份判定能力：`shell._is_gm(qq_id)` / `shell._gm_whitelist()`（真源在宿主共享
    `game/commands/base.py`，本批禁改 → 经能力口取；判定策略仍在包内 `gm_auth`）；
  * 停服状态：`shell._server_down()` / `shell._server_down_msg()`（同上，base.py 真源）；
  * 属性重算句柄：`shell._title_bonus(gid, qid)`（`gm_设等级` 用，真源宿主 `CommandBase`）；
  * 平台身份映射：`shell._identity_ops()`（`commands/_identity.py`，openid ↔ QQ）；
  * 全服广播：`shell._broadcast(text)`（async → **fire-and-forget** `asyncio.create_task`，
    与包内既有同款先例一致：`content/economy_cmds._fish_legend_broadcast`，
    v104 R3 M15 P2-1「有事件循环则 create_task，无（测试环境）静默跳过」）。
数据句柄走包内既有「宿主替身口」：`content/persistence/handles._HostMod("db")`（= 宿主 `game.db`，
与桥接层 `_save_player` 同源）；`display` / `player_final_stats` 取**包内门面**
（`content/tables.display` · `content/panel.player_final_stats`，B14-2/D3 已端口，等价性已实测）。

**没搬（宿主侧保留，逐条给理由 —— 均属 B18_DESIGN §7 明确列出的「不适合本形状」类）**
  * `gm_play` —— 转发任意游戏指令，走宿主注册表（`_find_handler` / `_run_shortcut`，async
    generator）：§7.1「多消息」+ §7.2「依赖 AstrBot 注册表」；终态形状（同步 handler → 单条
    plain_result）装不下，且包内没有注册表。
  * `gm_spy` + `_chunk_text` / `_spy_to_role_cards` —— 调试/运维管道：读 playtest 实录 md、
    拼 NapCat 合并转发节点、`await context.send_message` 多卡投递（含 `await asyncio.sleep`）、
    写 `.spy_forward_state.json` —— §7.1「多消息/富文本」+ 平台 I/O。

行为逐字节不变；证据 = `overnight/W-B18-L4.md` 的 358 项三分支快照（sha256 改前 = 改后）。
"""
from __future__ import annotations

import asyncio

from . import gm as _G
from .commands import register
from .panel import player_final_stats as _player_final_stats
from .persistence.handles import _HostMod as _HostMod
from .tables import display as _display

_db = _HostMod("db")                     # 宿主 `game.db`（= 桥接层 `_save_player` 的同一个）


class _CHost:
    """`content/gm.py` 的 `C` 参数（宿主内容薄聚合层 —— B14-2 起只剩 `display`）。"""

    display = staticmethod(_display)


class _Host:
    """`content/gm.py` 认识的宿主句柄（形状与旧宿主 `_Host` 逐字相同）。"""

    db = _db
    C = _CHost

    def __init__(self, shell):
        self.player_final_stats = _player_final_stats
        tb = getattr(shell, "_title_bonus", None)
        self.title_bonus = tb if callable(tb) else (lambda group_id, qq_id: {})


def _shell(env):
    """宿主壳对象（桥接层经 `env.state["shell"]` 注入）——包内取宿主面的**唯一**口。"""
    return (env.state or {}).get("shell")


def _host(env) -> "_Host":
    return _Host(_shell(env))


def _cap(shell, name: str):
    """取宿主能力口；缺 → fail-loud（不静默改语义）。"""
    fn = getattr(shell, name, None)
    if not callable(fn):
        raise RuntimeError("cmds_gm：宿主能力口 %r 缺失（过渡期契约，见模块头注）" % name)
    return fn


def _broadcast_soon(shell, text) -> None:
    """全服广播（fire-and-forget）—— 有事件循环则 create_task，无（测试环境）静默跳过。"""
    if not text:
        return
    try:
        asyncio.get_running_loop()
        asyncio.create_task(shell._broadcast(text))
    except Exception:                    # noqa: BLE001
        pass                             # 与包内既有广播先例同款（economy_cmds 传说广播）


# ============================================================
# 服务器族
# ============================================================
@register("gm_maintenance", guards=("hook:gm",), params=("cmd=gm_停服",))
def gm_maintenance(env) -> list:
    """『gm_停服 [理由]』：写停服状态 + 全服广播。"""
    text, broadcast = _G.maintenance(_host(env), env.arg_text("gm_停服"))
    _broadcast_soon(_shell(env), broadcast)
    return [text]


@register("gm_open", guards=("hook:gm",), params=("cmd=gm_开服",))
def gm_open(env) -> list:
    """『gm_开服』：清停服状态 + （原为停服时）全服广播。"""
    shell = _shell(env)
    was_down = bool(_cap(shell, "_server_down")())
    text, broadcast = _G.open_server(_host(env), was_down)
    if was_down:
        _broadcast_soon(shell, broadcast)
    return [text]


@register("gm_status", guards=("hook:gm",), params=("cmd=gm_状态",))
def gm_status(env) -> list:
    """『gm_状态』：服务器状态 / 玩家数 / 最高等级 / GM 名单。"""
    shell = _shell(env)
    return [_G.status_text(_host(env), env.group_id,
                           bool(_cap(shell, "_server_down")()),
                           _cap(shell, "_server_down_msg")(),
                           _cap(shell, "_gm_whitelist")())]


@register("gm_broadcast", guards=("hook:gm",), params=("cmd=gm_广播",))
def gm_broadcast(env) -> list:
    """『gm_广播 <内容>』：全服公告（空内容 → 格式提示）。"""
    text, broadcast = _G.broadcast(_host(env), env.arg_text("gm_广播"))
    if broadcast is not None:
        _broadcast_soon(_shell(env), broadcast)
    return [text]


# ============================================================
# 玩家查询族
# ============================================================
@register("gm_players", guards=("hook:gm",), params=("cmd=gm_玩家",))
def gm_players(env) -> list:
    """『gm_玩家 [关键词] [页码]』：玩家列表（每页 10）。"""
    return [_G.players_text(_host(env), env.group_id, env.arg_text("gm_玩家"))]


@register("gm_query", guards=("hook:gm",), params=("cmd=gm_查询",))
def gm_query(env) -> list:
    """『gm_查询 <QQ/名字>』：玩家详情。"""
    return [_G.query_text(_host(env), env.arg_text("gm_查询"))]


# ============================================================
# 玩家操作族
# ============================================================
@register("gm_give_gold", guards=("hook:gm",), params=("cmd=gm_发金币",))
def gm_give_gold(env) -> list:
    """『gm_发金币 <QQ/名字> <数量>』。"""
    return [_G.give_gold(_host(env), env.arg_text("gm_发金币"))]


@register("gm_give_item", guards=("hook:gm",), params=("cmd=gm_发物品",))
def gm_give_item(env) -> list:
    """『gm_发物品 <QQ/名字> <物品名> [数量]』。"""
    return [_G.give_item(_host(env), env.arg_text("gm_发物品"))]


@register("gm_give_exp", guards=("hook:gm",), params=("cmd=gm_发经验",))
def gm_give_exp(env) -> list:
    """『gm_发经验 <QQ/名字> <经验值>』。"""
    return [_G.give_exp(_host(env), env.arg_text("gm_发经验"))]


@register("gm_set_level", guards=("hook:gm",), params=("cmd=gm_设等级",))
def gm_set_level(env) -> list:
    """『gm_设等级 <QQ/名字> <等级>』：重算属性回满血。"""
    return [_G.set_level(_host(env), env.arg_text("gm_设等级"))]


@register("gm_teleport", guards=("hook:gm",), params=("cmd=gm_传送",))
def gm_teleport(env) -> list:
    """『gm_传送 <QQ/名字> <地图名>』：落点设默认子区域。"""
    return [_G.teleport(_host(env), env.arg_text("gm_传送"))]


@register("gm_stamina", guards=("hook:gm",), params=("cmd=gm_体力",))
def gm_stamina(env) -> list:
    """『gm_体力 <QQ/名字> [数值]』：不填 = 回满。"""
    return [_G.stamina(_host(env), env.arg_text("gm_体力"))]


@register("gm_rename", guards=("hook:gm",), params=("cmd=gm_改名",))
def gm_rename(env) -> list:
    """『gm_改名 <QQ/名字> <新名字>』。"""
    return [_G.rename(_host(env), env.arg_text("gm_改名"))]


# ============================================================
# GM 白名单族
# ============================================================
@register("gm_add_gm", guards=("hook:gm",), params=("cmd=gm_加GM",))
def gm_add_gm(env) -> list:
    """『gm_加GM <QQ号>』：加入库内白名单。"""
    return [_G.add_gm(_host(env), env.arg_text("gm_加GM"))]


@register("gm_del_gm", guards=("hook:gm",), params=("cmd=gm_删GM",))
def gm_del_gm(env) -> list:
    """『gm_删GM <QQ号>』：移出库内白名单。"""
    return [_G.del_gm(_host(env), env.arg_text("gm_删GM"))]


# ============================================================
# 帮助 / 世界 Boss 伤害倍率
# ============================================================
@register("gm_help", guards=("hook:gm",), params=("cmd=gm_帮助",))
def gm_help(env) -> list:
    """『gm_帮助』：GM 指令一览（逐字真源整段）。"""
    return [_G.help_text()]


@register("gm_boss_dmg", guards=("hook:gm",), params=("cmd=gm_伤害",))
def gm_boss_dmg(env) -> list:
    """『gm_伤害 [倍率]』：世界 Boss 伤害倍率（0.1－100）。"""
    return [_G.boss_dmg(_host(env), env.uid, env.arg_text("gm_伤害"))]


# ============================================================
# 平台身份族（判定与文案在包，平台映射能力经 `shell._identity_ops()` 取）
# ============================================================
@register("gm_bind_identity", guards=("hook:gm",), params=("cmd=gm_绑身份",))
def gm_bind_identity(env) -> list:
    """『gm_绑身份 <QQ号>』：把当前发送者（官方 bot openid）绑定到指定 QQ 号。"""
    idm = _cap(_shell(env), "_identity_ops")()
    raw = env.arg_text("gm_绑身份")
    if not raw:
        return ["格式：gm_绑身份 <QQ号>\n"
                "说明：把当前私聊/群内发送者的 openid 绑定到指定 QQ 号，\n"
                "绑定后该玩家在新 bot 上报到老 QQ 号，老角色/GM 权限直接续接。"]
    qq_target = raw.split()[0].strip()
    if not idm.is_qq_id(qq_target):
        return [f"❌ {qq_target} 不是合法 QQ 号～"]
    openid = env.raw.get_sender_id() or ""
    if not openid or not idm.is_openid(openid):
        # 非官方平台（如测试/旧链）没有 openid，直接提示无法绑定
        return [f"⚠️ 当前事件 sender={openid!r} 不是 openid，可能不在官方 bot 平台。\n"
                "请在官方 bot 的会话里执行本指令。"]
    idm.bind(openid, qq_target)
    old = idm.openid_to_qq(openid)
    return [
        f"✅ 已把 openid {openid[:8]}…{openid[-6:]} 绑定到 QQ {qq_target}。\n"
        f"该玩家现在会以 QQ {qq_target} 的身份游玩（老角色自动续接）～"
        + (f"\n(原绑定 QQ {old} 已覆盖)" if old and old != qq_target else "")
    ]


@register("gm_identity_table", guards=("hook:gm",), params=("cmd=gm_身份表",))
def gm_identity_table(env) -> list:
    """『gm_身份表』：openid ↔ QQ 绑定表（最多 30 条）。"""
    idm = _cap(_shell(env), "_identity_ops")()
    try:
        rows = idm.query_all()
    except Exception:                    # noqa: BLE001
        return ["⚠️ identity_map 查询失败（表可能未初始化）"]
    if not rows:
        return ["📋 当前无任何 openid 绑定。"]
    lines = [f"📋 身份映射表（共 {len(rows)} 条）："]
    for r in rows[:30]:
        oid = r.get("openid", "")
        lines.append(f"{oid[:8]}…{oid[-6:]} → QQ {r.get('qq_id')} ({r.get('platform')})")
    return lines
