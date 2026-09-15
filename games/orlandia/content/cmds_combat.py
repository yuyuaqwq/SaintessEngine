# -*- coding: utf-8 -*-
"""包内战斗族命令（`content/cmds_combat.py`）—— 宿主 `game/commands/combat.py` 15 条命令的
**守卫声明 / 取参 / 业务调度 / 回话组装**（B18 L3c，2026-09-14）。

终态形状（真源 = `overnight/B18_TERMINAL_SHAPE.md` §1.2）在本族的**一处已登记差异**
------------------------------------------------------------------------------
样板（`cmds_weekly` / `cmds_tower` / `cmds_collection`）的处理器是**同步** `fn(env) -> list[str]`：
命令体是纯同步分支，`render_panel` 把行拼成一条消息。

战斗族**不是**同步的：实现体（`content/combat_cmds.py`，B10 L5 逐字搬包）是 **async generator**
（`async for _r in self._instance_router(...)` / `await self._broadcast(...)` —— 宿主
`_instance_router`（`game/commands/instance_router.py`）与 `_broadcast`（`game/commands/base.py`）
都是 async，命门在宿主能力口，本线不搬；B18_DESIGN §7「不适合这套的类别」第 1/3 条
（多消息 / 开战装配类）正是本族）。

所以本模块**照抄样板的表形状**——`COMMANDS[key] = {"guards", "params", "handler"}`，
守卫文案在包、取参在包、渲染在包、宿主零游戏知识——只把处理器写成 `async def fn(env) -> list[str]`：
宿主侧 `_host_bridge.run_async` **逐段回话**（一条 = 一条消息），**不做 `"\\n".join` 合并**
—— 对齐改造前 `async for _r in _CC.<cmd>(...): yield _r` 的逐条语义（含分支/异常提示行序）。
现状实测：本线 141 场景快照里 157 次命令驱动**全部 = 1 条消息**（多段合并与否同形）。

宿主零游戏知识（本线的验收线）
------------------------------
改造前宿主壳里残留的**游戏字面量**全部随本线进包：
* 4 处 `self._strip_cmd(event, "许愿" / "攻击" / "技能" / "荣誉")`（指令词写在宿主）；
* 3 处 `"战前形态" / "战前阈值" / "战前力场"` 分参字面量 + `(event.get_message_str() or "").strip()`；
* 15 组守卫装饰器（`@require_player` / `@require_battle` / `@no_prof_waiting`）。
宿主 `game/commands/combat.py` 每条命令只剩 `@declared("key")` + 一行转发
（`async for _r in _BRIDGE.run_async(self, "key", event): yield _r`）。

I2（包内不 import 宿主）
-----------------------
宿主面一律经注入句柄：`env.state["shell"]` = 宿主壳对象（与样板 `cmds_tower` 同源的过渡能力口）。
实现体 `content/combat_cmds.py` 本来就把 `self` 当宿主取件口用 —— 本模块只把它从 `env` 取出来
传下去，**不改实现体的任何调用点**（时序/注册顺序逐点不变）。

行为逐字节不变：证据 = `overnight/b18l3c_snap.py` 的 141 场景快照（sha256 改前 = 改后）。
"""
from __future__ import annotations

from . import combat_cmds as _CC
from .commands import COMMANDS


# ============================================================
# 取件口（env → 改造前命令体的实参）
# ============================================================
def _shell(env):
    """宿主壳对象（桥接层经 `env.state["shell"]` 注入）：实现体经它做宿主取件。"""
    return (env.state or {}).get("shell")


class _Say:
    """`env.raw`（平台事件）的最小替身：`plain_result(文本)` → **文本行**（返回 text 本身）。

    ★ W-L9 定点修（2026-09-15）：本族 handler 是 async generator，实现体是历史形状
    `yield event.plain_result(文本)`。此前 `_event()` 把**真事件**原样交给实现体 ⇒ `yield`
    出来的是**平台结果对象**（`MessageEventResult`），引擎 `Host._as_replies` 再 `str()` 它
    ⇒ 交付面成了 dataclass repr（实测 `str(MessageEventResult().message('hello'))` =
    `MessageEventResult(chain=[Plain(...)])`），**不是文案** —— 违反交付契约「只交 list[str]」。

    与 `content/cmds_player.py::_Say` / `content/cmds_world.py::_Say` 同形：`plain_result`
    收成已渲染行并返回文本；其余属性原样代理真事件（`get_message_str` / 壳的 `_strip_cmd` /
    转发期 `message_str` 赋值 / `stop_event` 全部照旧）⇒ 实现体**零改动**。
    """

    def __init__(self, ev):
        object.__setattr__(self, "_ev", ev)
        object.__setattr__(self, "lines", [])

    def plain_result(self, text):
        """把「一行文本」收起来并**返回文本本身**（实现体的 `yield` 值 = 一行文案）。"""
        self.lines.append(text)
        return text

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_ev"), name)

    def __setattr__(self, name, value):        # 转发期 `message_str` 交换等语义逐字保留
        setattr(object.__getattribute__(self, "_ev"), name, value)


def _event(env):
    """实现体看到的「平台事件」= **文本收集替身**（`plain_result` 落文本；其余代理真事件）。"""
    return _Say(env.raw)


def _message_text(env) -> str:
    """本条消息原文（已 strip）= 改造前 `(event.get_message_str() or "").strip()`。"""
    return str(env.text or "")


async def _messages(agen) -> list:
    """async generator → `list[str]`（**每条 = 改造前的一次 `yield`** = 一条消息）。"""
    out = []
    async for _r in agen:
        out.append(_r)
    return out


def _declare(key, guards=(), params=()):
    """登记一条战斗族命令（表形状与 `content/commands.py::register` 逐字段相同）。

    唯一差异 = 处理器是 `async def`（见模块头注），故不经 `register()`（它把 handler 包成
    同步 `render_panel(fn(env), env)`）；`guards` / `params` 的语义与声明表
    （`content/data/commands.json`）逐字对齐。重复 key 直接抛（与 `register()` 同口径）。
    """
    def deco(fn):
        if key in COMMANDS:
            raise KeyError("content.commands：命令 %r 重复登记" % key)
        COMMANDS[key] = {"guards": tuple(guards), "params": tuple(params), "handler": fn}
        return fn
    return deco


# ============================================================
# 探索族
# ============================================================
@_declare("explore", guards=("hook:player", "hook:no_prof_waiting"), params=("cmd=探索",))
async def explore(env):
    """『探索』（旧宿主体：`@require_player` + `@no_prof_waiting` → 取玩家 → 调包）。"""
    return await _messages(_CC.explore(_shell(env), _event(env),
                                       env.group_id, env.uid, env.player))


@_declare("wild_king_chest", guards=("hook:player",), params=("cmd=摸宝箱",))
async def wild_king_chest(env):
    """『摸宝箱』（旧宿主体：`@require_player` → 取玩家 → 调包）。"""
    return await _messages(_CC.wild_king_chest(_shell(env), _event(env),
                                               env.group_id, env.uid, env.player))


# ============================================================
# 冒险族（许愿 / 商人确认 / 复活确认）
# ============================================================
@_declare("wish", guards=("hook:player",), params=("cmd=许愿",))
async def wish(env):
    """『许愿 [类型]』（旧宿主体：`opt = self._strip_cmd(event, "许愿").strip()`）。"""
    opt = env.arg_text("许愿")
    return await _messages(_CC.wish(_shell(env), _event(env),
                                    env.group_id, env.uid, env.player, opt))


@_declare("trader_confirm", guards=("hook:player",), params=("cmd=确认购买",))
async def trader_confirm(env):
    """『确认购买 / 拒绝』（旧宿主体：**不取玩家档**，只取 uid —— 逐字保留）。"""
    return await _messages(_CC.trader_confirm(_shell(env), _event(env),
                                              env.group_id, env.uid))


@_declare("revive_confirm", guards=("hook:player",), params=("cmd=使用复活羽毛",))
async def revive_confirm(env):
    """『使用复活羽毛 / 放弃复活』（旧宿主体：**不取玩家档**，只取 uid —— 逐字保留）。"""
    return await _messages(_CC.revive_confirm(_shell(env), _event(env),
                                              env.group_id, env.uid))


# ============================================================
# 战斗族
# ============================================================
@_declare("attack", guards=("hook:player",), params=("cmd=攻击",))
async def attack(env):
    """『攻击 [目标]』（旧宿主体：`target_arg = self._strip_cmd(event, "攻击").strip()`）。"""
    target_arg = env.arg_text("攻击")
    return await _messages(_CC.attack(_shell(env), _event(env),
                                      env.group_id, env.uid, env.player, target_arg))


@_declare("skill", guards=("hook:player",), params=("cmd=技能",))
async def skill(env):
    """『技能 <名称/槽位> [目标]』（旧宿主体：`skill_name = self._strip_cmd(event, "技能")`）。"""
    skill_name = env.arg_text("技能")
    return await _messages(_CC.skill(_shell(env), _event(env),
                                     env.group_id, env.uid, env.player, skill_name))


@_declare("defend", guards=("hook:player", "hook:battle"), params=("cmd=防御",))
async def defend(env):
    """『防御』（旧宿主体：`@require_player` + `@require_battle` → 取玩家 → 调包）。"""
    return await _messages(_CC.defend(_shell(env), _event(env),
                                      env.group_id, env.uid, env.player))


@_declare("flee", guards=("hook:player", "hook:battle"), params=("cmd=逃跑",))
async def flee(env):
    """『逃跑』（旧宿主体：`@require_player` + `@require_battle` → 取玩家 → 调包）。"""
    return await _messages(_CC.flee(_shell(env), _event(env),
                                    env.group_id, env.uid, env.player))


@_declare("hunt_boss", guards=("hook:player", "hook:no_prof_waiting"), params=("cmd=讨伐",))
async def hunt_boss(env):
    """『讨伐』（旧宿主体：`@require_player` + `@no_prof_waiting` → 取玩家 → 调包）。"""
    return await _messages(_CC.hunt_boss(_shell(env), _event(env),
                                         env.group_id, env.uid, env.player))


@_declare("honor_shop", guards=("hook:player",), params=("cmd=荣誉",))
async def honor_shop(env):
    """『荣誉 [兑换 <编号>]』（旧宿主体：`raw = self._strip_cmd(event, "荣誉").strip()`）。"""
    raw = env.arg_text("荣誉")
    return await _messages(_CC.honor_shop(_shell(env), _event(env),
                                          env.group_id, env.uid, env.player, raw))


# ============================================================
# v139 战前指令（双形态预设 / 终结阈值 / 奥术力场 / 查看）
# ============================================================
@_declare("battle_prefs_form", guards=("hook:player",), params=("cmd=战前形态",))
async def battle_prefs_form(env):
    """『战前形态 [值]』（旧宿主体：`text.split("战前形态", 1)[1].strip()`，非该词 → ""）。"""
    text = _message_text(env)
    arg = text.split("战前形态", 1)[1].strip() if "战前形态" in text else ""
    return await _messages(_CC.battle_prefs_form(_shell(env), _event(env),
                                                 env.group_id, env.uid, env.player, arg))


@_declare("battle_prefs_finisher", guards=("hook:player",), params=("cmd=战前阈值",))
async def battle_prefs_finisher(env):
    """『战前阈值 [值]』（旧宿主体：`text.split("战前阈值", 1)[1].strip()`，非该词 → ""）。"""
    text = _message_text(env)
    arg = text.split("战前阈值", 1)[1].strip() if "战前阈值" in text else ""
    return await _messages(_CC.battle_prefs_finisher(_shell(env), _event(env),
                                                     env.group_id, env.uid, env.player, arg))


@_declare("battle_prefs_arcane_field", guards=("hook:player",), params=("cmd=战前力场",))
async def battle_prefs_arcane_field(env):
    """『战前力场 [盾/刃]』（旧宿主体：`text.split("战前力场", 1)[1].strip()`，非该词 → ""）。"""
    text = _message_text(env)
    arg = text.split("战前力场", 1)[1].strip() if "战前力场" in text else ""
    return await _messages(_CC.battle_prefs_arcane_field(_shell(env), _event(env),
                                                         env.group_id, env.uid, env.player, arg))


@_declare("battle_prefs_view", guards=("hook:player",), params=("cmd=战前指令",))
async def battle_prefs_view(env):
    """『战前指令』（旧宿主体：`@require_player` → 取玩家 → 调包）。"""
    return await _messages(_CC.battle_prefs_view(_shell(env), _event(env),
                                                 env.group_id, env.uid, env.player))
