# -*- coding: utf-8 -*-
"""包内 player 命令域（`content/cmds_player.py`，B18-L4）—— 20 条玩家命令的守卫/取参/业务/**渲染**。

终态形状（真源 = `overnight/B18_TERMINAL_SHAPE.md` §1.2）：宿主 `game/commands/player.py` 里
每条命令只剩 `@declared("<key>")` + `_BRIDGE.run(self, "<key>", event)` 一行转发；
守卫声明（`hook:player` = 包侧 `content/guards.py::GUARDS["player"]`，文案与框架
`require_player` 的 `register_hint` 逐字同源）、取参、分支业务与渲染全在本模块。

本模块与既有实现体的关系（**搬家已完成**，这里只做形状适配）
------------------------------------------------------------
实现本体在 `content/player_cmds.py`（B11-L3 已逐字搬包，1954 行，**本线一字未改**）——
它是历史形状的 async generator（`yield event.plain_result(...)`），且**零 await**
（`grep -c "await " content/player_cmds.py` = 0）。终态形状要的是「同步 handler → 已渲染行」，
故本模块提供两个**过渡期适配件**（实现体改成同步直返后二者一并删除）：

    _Say      平台事件的最小替身：`plain_result(文本)` 收成「已渲染行」（= 测试宿主
              `FakeEvent.plain_result` 的既定语义），其余属性（`get_message_str` /
              `get_sender_id` / `stop_event` / 转发期的 `message_str` 赋值）**原样代理真事件**；
    _drain    同步取空「零 await 的 async generator」→ 其产出列表（命中真 await → fail-loud）。

包内不 import 宿主（I2）：宿主壳对象经 `env.state["shell"]` 取（桥接层透传），
`content/player_cmds.py` 侧原有的「宿主替身口」（`_host_attr` / `_HostMod`）一字未动。

行为逐字节不变；证据 = `overnight/W-B18-L4.md` 的 358 项三分支快照（sha256 改前 = 改后）。
"""
from __future__ import annotations

from . import player_cmds as _PC
from .commands import register


# ============================================================
# 过渡期适配件（见模块头注：只服务「实现体仍是 async generator」这一件事）
# ============================================================

class _Say:
    """`env.raw`（平台事件）的最小替身：`plain_result` → 已渲染行；其余原样代理。"""

    def __init__(self, ev):
        object.__setattr__(self, "_ev", ev)
        object.__setattr__(self, "lines", [])

    def plain_result(self, text):
        """把「一行文本」直接收起来 —— 玩家可见文案的落点由包内决定（此处只有行内容）。"""
        self.lines.append(text)
        return text

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_ev"), name)

    def __setattr__(self, name, value):        # 转发期 `message_str` 交换等语义逐字保留
        setattr(object.__getattribute__(self, "_ev"), name, value)


def _drain(agen) -> list:
    """把「零 await 的 async generator」同步取空 → 产出（已渲染行）列表。

    * 命中真 await（实现体后续引入了异步调用）→ 抛 `RuntimeError`（fail-closed，不静默吞）；
    * 只在本包既有实现体上使用（其零 await 由 `content/player_cmds.py` 的静态事实保证）。
    """
    out = []
    while True:
        coro = agen.__anext__()
        try:
            coro.send(None)
        except StopIteration as exc:            # 本次 yield 的值
            out.append(exc.value)
            continue
        except StopAsyncIteration:              # 生成器取空
            return out
        except Exception as exc:                # noqa: BLE001
            raise RuntimeError(
                "cmds_player：实现体同步驱动失败（新增了 await？）：%r" % (exc,))
        raise RuntimeError("cmds_player：协程未按预期结束（%r）" % (coro,))


def _shell(env):
    """宿主壳对象（桥接层经 `env.state["shell"]` 注入）——包内取宿主面的**唯一**口。"""
    return (env.state or {}).get("shell")


def _run(env, fn, *args) -> list:
    """跑一条既有实现体（`content/player_cmds.<fn>`）并同步取空 → 已渲染行。"""
    say = _Say(env.raw)
    out = _drain(fn(_shell(env), say, *args))
    return out or say.lines


# ============================================================
# 命令登记（key == 宿主 `@declared` 的 key == 方法名）
# ============================================================
@register("shortcut", guards=("hook:player",), params=("cmd=快捷绑定",))
def shortcut(env) -> list:
    """『快捷绑定/快捷列表/快捷删除/快捷清除』：快捷指令的绑定与查看。"""
    return _run(env, _PC.shortcut, env.group_id, env.uid, env.player)


@register("register", params=("cmd=注册",))
def register_(env) -> list:
    """『注册 <名字> <性别> [种族]』：建号（含双格式兼容与校验）。"""
    return _run(env, _PC.register, env.group_id, env.uid)


@register("bind_identity", params=("cmd=绑定身份",))
def bind_identity(env) -> list:
    """『绑定身份 <QQ号> <角色名>』：官方 bot openid → 老 QQ 号（续接老角色）。"""
    return _run(env, _PC.bind_identity)


@register("profile", guards=("hook:player",), params=("cmd=角色",))
def profile(env) -> list:
    """『角色』：角色面板。"""
    return _run(env, _PC.profile, env.group_id, env.uid, env.player)


@register("leaderboard", params=("cmd=排行",))
def leaderboard(env) -> list:
    """『排行 [类别]』：等级榜/战力榜/副业榜。"""
    return _run(env, _PC.leaderboard, env.group_id, env.uid)


@register("races", params=("cmd=种族",))
def races(env) -> list:
    """『种族 [id]』：种族一览 / 单族详情。"""
    return _run(env, _PC.races)


@register("evolve", guards=("hook:player",), params=("cmd=转职",))
def evolve(env) -> list:
    """『转职』：职业分支/进阶（含隐藏职业路由）。"""
    return _run(env, _PC.evolve, env.group_id, env.uid, env.player)


@register("attributes", guards=("hook:player",), params=("cmd=属性",))
def attributes(env) -> list:
    """『属性』：属性面板（含加点区）。"""
    return _run(env, _PC.attributes, env.group_id, env.uid, env.player)


@register("add_attr", guards=("hook:player",), params=("cmd=加点",))
def add_attr(env) -> list:
    """『加点 <属性> [次数]』：分配属性点。"""
    return _run(env, _PC.add_attr, env.group_id, env.uid, env.player)


@register("reset_skill", guards=("hook:player",), params=("cmd=技能洗点",))
def reset_skill(env) -> list:
    """『技能洗点』：重置技能点。"""
    return _run(env, _PC.reset_skill, env.group_id, env.uid, env.player)


@register("evolve_reset", guards=("hook:player",), params=("cmd=转职重置",))
def evolve_reset(env) -> list:
    """『转职重置』：退回本级分支重选。"""
    return _run(env, _PC.evolve_reset, env.group_id, env.uid, env.player)


@register("reset_attr", guards=("hook:player",), params=("cmd=洗点",))
def reset_attr(env) -> list:
    """『洗点 [确认]』：重置已分配属性点。"""
    return _run(env, _PC.reset_attr, env.group_id, env.uid, env.player)


@register("power", guards=("hook:player",), params=("cmd=战力",))
def power(env) -> list:
    """『战力』：战力构成面板。"""
    return _run(env, _PC.power, env.group_id, env.uid, env.player)


@register("skill_detail", guards=("hook:player",), params=("cmd=技能详情",))
def skill_detail(env) -> list:
    """『技能详情 <名称/序号>』：技能逐级数值详情。"""
    return _run(env, _PC.skill_detail, env.group_id, env.uid, env.player)


@register("skill_learn", guards=("hook:player",), params=("cmd=技能学习",))
def skill_learn(env) -> list:
    """『技能学习 <名称>』：学习技能。"""
    return _run(env, _PC.skill_learn, env.group_id, env.uid, env.player)


@register("skill_upgrade", guards=("hook:player",), params=("cmd=技能升级",))
def skill_upgrade(env) -> list:
    """『技能升级 <名称>』：技能升级。"""
    return _run(env, _PC.skill_upgrade, env.group_id, env.uid, env.player)


@register("skill_bar_view", guards=("hook:player",), params=("cmd=技能栏",))
def skill_bar_view(env) -> list:
    """『技能栏』：技能栏视图。"""
    return _run(env, _PC.skill_bar_view, env.group_id, env.uid, env.player)


@register("skill_bar_set", guards=("hook:player",), params=("cmd=设置技能",))
def skill_bar_set(env) -> list:
    """『设置技能 <槽位> <技能名>』：设置技能栏槽位。"""
    return _run(env, _PC.skill_bar_set, env.group_id, env.uid, env.player)


@register("build_view", guards=("hook:player",), params=("cmd=流派",))
def build_view(env) -> list:
    """『流派 [名称]』：流派一览 / 单流派详情。"""
    return _run(env, _PC.build_view, env.group_id, env.uid, env.player)


@register("delete_account", guards=("hook:player",), params=("cmd=注销",))
def delete_account(env) -> list:
    """『注销 [确认]』：注销角色（二次确认）。"""
    return _run(env, _PC.delete_account, env.group_id, env.uid, env.player)
