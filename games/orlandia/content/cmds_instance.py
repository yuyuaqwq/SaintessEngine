# -*- coding: utf-8 -*-
"""包内副本命令域（`content/cmds_instance.py`）—— B18-L5 整块搬包（2026-09-14）· B18-L10 进引擎通道。

副本族 8 条命令（`join_battle` / `instance_cmd` / `instance_advance` / `instance_map_view_cmd` /
`instance_investigate` / `instance_retreat` / `instance_retreat_confirm` / `instance_leave`）的
**命令清单 + 守卫声明 + 调包 + 回话**。宿主壳 `game/commands/instance.py` 每条命令只剩：

    @declared("instance_cmd")            # 真注册（正则来自声明表 command_specs.json）
    async def instance_cmd(self, event):
        async for _r in _BRIDGE.run_async(self, "instance_cmd", event):   # ★ 两行转发
            yield _r

分工（与 `content/commands.py` 的终态形状同精神：**命令表在包、注册副作用在宿主**）
----------------------------------------------------------------------------------
* **本模块**：域的**命令清单** `COMMAND_KEYS`（与宿主声明表逐字相等的 key）+ **声明视图**
  `DECLARED`（guards / params，是 `command_specs.json` 的**派生视图**，不重造口径）+
  **8 条 `@_declare` 处理器**（唯一映射点：key → 包内实现方法；宿主壳不再认识实现方法名）+
  **兼容转发口** `forward(shell, key, event)`（B18-L5 起的历史接口，宿主已不再调用，
  保留给既有调用点/工具）；
* **包内实现**：`content/instance_cmds.py::InstanceImpl`（B11-L1 整块搬入：8 个命令入口
  + 57 个私有助手，3315 行）+ `content/cmds_instance_router.py::InstanceRouterImpl`
  （B18-L5 整块搬入：副本行动路由，458 行类体逐字）；
* **宿主**：`@declared` 真注册（引擎侧装饰器）——注册副作用**必须**留宿主：包内再触发会让
  同一指令注册两遍（B11-L1 起即如此，本线不动）。

B18-L10：为什么从「同义一行转发」改成 `_BRIDGE.run_async`
--------------------------------------------------------
B18-L5～L9 期间宿主壳是 `async for _r in _CMDS.forward(self, key, event): yield _r` —— 那只是
**宿主内部的转发口**，不是引擎通道：编辑器试玩（B20）与换包实证（P6）都跑不到这 8 条。
B18-L10 把守卫声明与调包**搬进包内本模块**（终态形状），宿主退化为两行 `_BRIDGE.run_async`。

形状选择：8 条实现方法（`InstanceImpl.<key>(self, event)`）都是 **async generator**
（`async def` + `yield event.plain_result(...)`，AST 实测 8/8 带 `Yield`），只能用 `async for`
迭代 —— 与 B18-L3c 战斗族（`content/cmds_combat.py`）、B18-L9 经济族
（`content/cmds_economy.py`）同款：

    @_declare("<key>", guards=("hook:player", "hook:no_prof_waiting"), params=(...))
    async def <key>(env):
        return await _messages(InstanceImpl.<key>(_shell(env), _event(env)))

宿主侧 `_BRIDGE.run_async` **逐段回话、不做 `"\\n".join` 合并** —— 与旧壳
`async for _r in _CMDS.forward(...): yield _r` 的逐条语义（分支/异常提示的行序与消息切分）
逐字节相同。同步桥 `_BRIDGE.run`（join 成一条）形状不适用，故**不适用**（不是「漏搬」）。

守卫与取参（数据来源）
----------------------
* `guards=("hook:player", "hook:no_prof_waiting")`：逐条 = 旧宿主装饰器
  `@require_player()` + `@no_prof_waiting()`（**顺序同声明表**：`command_specs.json` 这 8 条的
  `guards` 都是 `["player", "no_prof_waiting"]`，与宿主装饰器的施加顺序
  `require_player(no_prof_waiting(fn))` 逐位一致）。判定与文案都在包侧
  `content/guards.py::GUARDS`（`player` 的 `NO_PLAYER_HINT` 逐字 = 宿主
  `base.REGISTER_HINT`；`no_prof_waiting` 的实现本就与宿主再导出同源），故拦截回话一字不差。
* `params`：`"cmd=<命令词>"` = `command_specs.json` 的 `usage` 首词；`name` / `floor` / `target`
  照 `DECLARED` 派生视图逐字保留。`params` 是编辑器/校验用的元数据；**取参仍在实现体里**
  （`self._strip_cmd(event, ...)`）**逐字未动**。
* 模块末尾有**声明视图对账**（`DECLARED` ↔ `COMMANDS` 的 guards/params 逐格相等），
  不一致直接抛 —— fail-closed，防「登记了但没接线」。

I2（包内不 import 宿主）
------------------------
宿主面一律经注入句柄：`env.state["shell"]` = 宿主壳对象（`InstanceCmds` 实例，与样板
`cmds_combat` / `cmds_economy` 同源的过渡能力口），`env.raw` = 平台事件原样透传。实现体
`content/instance_cmds.py` 本来就把 `self` 当宿主取件口用 —— 本模块只把它从 `env` 取出来
传下去，**不改实现体的任何调用点**（时序/注册顺序逐点不变）。

行为逐字节不变
--------------
证据 = `out/b18l10_snap.py` 的 74 场景快照（8 条命令 × 正常/边界/失败；sha256 改前 = 改后，
含逐表 DB dump）+ 3 硬门禁 + 10 副本定向 + 数值门禁，全部照 B18-L9 口径。
"""
from __future__ import annotations

from .commands import COMMANDS
from .instance_cmds import InstanceImpl

__all__ = ["COMMAND_KEYS", "DECLARED", "forward",
           "join_battle", "instance_cmd", "instance_advance", "instance_map_view_cmd",
           "instance_investigate", "instance_retreat", "instance_retreat_confirm",
           "instance_leave"]


# ============================================================
# 取件口（env → 改造前命令体的实参）
# ============================================================
def _shell(env):
    """宿主壳对象（桥接层经 `env.state["shell"]` 注入）：实现体经它做宿主取件。"""
    return (env.state or {}).get("shell")


def _event(env):
    """平台事件原样透传（包内禁解释，只原样交给实现体 —— 与改造前同一个对象）。"""
    return env.raw


async def _messages(agen) -> list:
    """async generator → `list[str]`（**每条 = 改造前的一次 `yield`** = 一条消息）。"""
    out = []
    async for _r in agen:
        out.append(_r)
    return out


def _declare(key, guards=(), params=()):
    """登记一条副本命令（表形状与 `content/commands.py::register` 逐字段相同）。

    唯一差异 = 处理器是 `async def`（见模块头注：实现体是 async generator），故不经
    `register()`（它把 handler 包成同步 `render_panel(fn(env), env)`）；`guards` / `params`
    的语义与声明表（`game/data/command_specs.json`）逐字对齐。重复 key 直接抛（与
    `register()` 同口径）——同款先例：`content/cmds_combat.py::_declare` /
    `content/cmds_economy.py::_declare` / `content/cmds_social.py::_declare`。
    """
    def deco(fn):
        if key in COMMANDS:
            raise KeyError("content.commands：命令 %r 重复登记" % key)
        COMMANDS[key] = {"guards": tuple(guards), "params": tuple(params), "handler": fn}
        return fn
    return deco


# ============================================================
# ① 域清单 + 声明视图（B18-L5 起：真源 = command_specs.json 的派生视图）
# ============================================================
#: 副本族命令清单 —— key 与宿主声明表 `game/data/command_specs.json` **逐字相等**（8 条）
COMMAND_KEYS = (
    "join_battle",               # 『加入战斗』
    "instance_cmd",              # 『副本 [名字]』
    "instance_advance",          # 『深入 [第N层]』
    "instance_map_view_cmd",     # 『副本地图』
    "instance_investigate",      # 『调查 [目标]』
    "instance_retreat",          # 『撤退』
    "instance_retreat_confirm",  # 『确认撤退』
    "instance_leave",            # 『离开副本』
)

#: 声明视图（`command_specs.json` 的派生视图；由 `overnight/b18l5_checks.py` 复算逐字相等）
#:   guards = 宿主壳上的装饰器（引擎守卫名，登记时加 `hook:` 前缀）· params 的 `cmd=<词>` == `usage` 首词
DECLARED = {
    "join_battle": {"guards": ("player", "no_prof_waiting"), "params": ("cmd=加入战斗",)},
    "instance_cmd": {"guards": ("player", "no_prof_waiting"), "params": ("cmd=副本", "name")},
    "instance_advance": {"guards": ("player", "no_prof_waiting"), "params": ("cmd=深入", "floor")},
    "instance_map_view_cmd": {"guards": ("player", "no_prof_waiting"), "params": ("cmd=副本地图",)},
    "instance_investigate": {"guards": ("player", "no_prof_waiting"), "params": ("cmd=调查", "target")},
    "instance_retreat": {"guards": ("player", "no_prof_waiting"), "params": ("cmd=撤退",)},
    "instance_retreat_confirm": {"guards": ("player", "no_prof_waiting"), "params": ("cmd=确认撤退",)},
    "instance_leave": {"guards": ("player", "no_prof_waiting"), "params": ("cmd=离开副本",)},
}


# ============================================================
# ② 8 条处理器（B18-L10：进引擎通道 —— 守卫/调包/回话都在包内）
# ============================================================
@_declare("join_battle", guards=("hook:player", "hook:no_prof_waiting"),
          params=("cmd=加入战斗",))
async def join_battle(env):
    """『加入战斗』（旧宿主体：`@require_player` + `@no_prof_waiting` → 取玩家 → 调包）。"""
    return await _messages(InstanceImpl.join_battle(_shell(env), _event(env)))


@_declare("instance_cmd", guards=("hook:player", "hook:no_prof_waiting"),
          params=("cmd=副本", "name"))
async def instance_cmd(env):
    """『副本 [名字]』（旧宿主体：取玩家 → 列表/开本/状态/恢复进度）。"""
    return await _messages(InstanceImpl.instance_cmd(_shell(env), _event(env)))


@_declare("instance_advance", guards=("hook:player", "hook:no_prof_waiting"),
          params=("cmd=深入", "floor"))
async def instance_advance(env):
    """『深入 [第N层]』（旧宿主体：清完当前层后推进一层）。"""
    return await _messages(InstanceImpl.instance_advance(_shell(env), _event(env)))


@_declare("instance_map_view_cmd", guards=("hook:player", "hook:no_prof_waiting"),
          params=("cmd=副本地图",))
async def instance_map_view_cmd(env):
    """『副本地图』（旧宿主体：当前层小地图全景）。"""
    return await _messages(InstanceImpl.instance_map_view_cmd(_shell(env), _event(env)))


@_declare("instance_investigate", guards=("hook:player", "hook:no_prof_waiting"),
          params=("cmd=调查", "target"))
async def instance_investigate(env):
    """『调查 [目标]』（旧宿主体：与当前层 POI 互动）。"""
    return await _messages(InstanceImpl.instance_investigate(_shell(env), _event(env)))


@_declare("instance_retreat", guards=("hook:player", "hook:no_prof_waiting"),
          params=("cmd=撤退",))
async def instance_retreat(env):
    """『撤退』（旧宿主体：弹二次确认，不真正放弃）。"""
    return await _messages(InstanceImpl.instance_retreat(_shell(env), _event(env)))


@_declare("instance_retreat_confirm", guards=("hook:player", "hook:no_prof_waiting"),
          params=("cmd=确认撤退",))
async def instance_retreat_confirm(env):
    """『确认撤退』（旧宿主体：真正放弃本局进度）。"""
    return await _messages(InstanceImpl.instance_retreat_confirm(_shell(env), _event(env)))


@_declare("instance_leave", guards=("hook:player", "hook:no_prof_waiting"),
          params=("cmd=离开副本",))
async def instance_leave(env):
    """『离开副本』（旧宿主体：通关后传出，保留战利品）。"""
    return await _messages(InstanceImpl.instance_leave(_shell(env), _event(env)))


# ============================================================
# ③ 兼容转发口（B18-L5 起的历史接口；宿主 B18-L10 后不再调用，保留给既有调用点/工具）
# ============================================================
def forward(shell, key: str, event):
    """宿主壳 → 包内实现的转发口（返回包内实现方法的 async generator）。

    B18-L10 后宿主壳走 `_BRIDGE.run_async`（引擎通道），本函数只为兼容保留：
    `key` 不在清单里 → fail-closed 抛错（不静默吞：静默会让一条指令变成哑巴）。
    """
    if key not in COMMAND_KEYS:
        raise KeyError("content.cmds_instance：未知副本命令 %r（已知：%s）"
                       % (key, ", ".join(COMMAND_KEYS)))
    return getattr(InstanceImpl, key)(shell, event)


# ============================================================
# ④ 声明视图对账（fail-closed）：DECLARED ↔ COMMANDS 逐格相等
# ============================================================
def _audit_declarations():
    """8 条全部登记进 `COMMANDS`，且 guards/params 与 `DECLARED` 派生视图逐格相等。"""
    missing = [k for k in COMMAND_KEYS if k not in COMMANDS]
    if missing:
        raise RuntimeError("content.cmds_instance：副本命令未登记进 COMMANDS：%s" % missing)
    for key, decl in DECLARED.items():
        entry = COMMANDS.get(key) or {}
        want_guards = tuple("hook:" + g for g in decl["guards"])
        want_params = tuple(decl["params"])
        if tuple(entry.get("guards") or ()) != want_guards:
            raise RuntimeError("content.cmds_instance：%s 的守卫与声明视图不一致（%r ≠ %r）"
                               % (key, entry.get("guards"), want_guards))
        if tuple(entry.get("params") or ()) != want_params:
            raise RuntimeError("content.cmds_instance：%s 的取参与声明视图不一致（%r ≠ %r）"
                               % (key, entry.get("params"), want_params))
    return tuple(sorted(DECLARED))


DECLARED_AUDITED = _audit_declarations()
