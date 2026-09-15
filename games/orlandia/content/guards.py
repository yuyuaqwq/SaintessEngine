# -*- coding: utf-8 -*-
"""包侧守卫（`content/guards.py`）—— 守卫的**判定 + 文案**都属内容（宿主/引擎只转发）。

引擎契约（`saintess_engine.host.env.guard_hooks()`）：
    GUARDS: dict[str, callable(env, player) -> str | None]
    —— 返回非空字符串 = **拦截**，并把它当作回话（玩家看到的就是这句）；返回 None = 放行。

两种用法（声明在 `content/commands.py::COMMANDS[key]["guards"]`）
----------------------------------------------------------------
*   `"player"`    内置守卫名：判定由引擎/宿主给（玩家档存在与否），**文案取本模块** ——
    桥接层（宿主 `game/commands/_host_bridge.py`）与引擎 `Host` 都从 `GUARDS` 取提示语，
    所以「你还没有角色」这句话**只住在包里**，宿主面不再有一份。
*   `"hook:<名>"` 纯包侧守卫：判定 + 文案都在本模块（「停服拦截 / GM 放行 / 等待型副业互斥」
    这类**策略**都放这里 —— 策略属内容）。

备注：`NO_PLAYER_HINT` 逐字 = 宿主旧真源 `game/commands/base.py::REGISTER_HINT`
（v95.26 起全游戏只有这一句「没角色」提示；本模块收的是同一个句子，等 L7 把 `base.py`
的游戏内容整块进包后，这一处即成为唯一真源）。
"""
from __future__ import annotations

__all__ = ["GUARDS", "NO_PLAYER_HINT", "player"]

#: 「玩家档不存在」的拦截回话（逐字 = 宿主 `base.REGISTER_HINT`）
NO_PLAYER_HINT = "你还没有角色！输入『注册 <名字> <性别> [种族]』创建吧～"


def player(env, player=None):
    """玩家档必须存在 —— 没有档 → 返回提示语（拦截）。"""
    target = getattr(env, "player", None) if player is None else player
    if target:
        return None
    return NO_PLAYER_HINT


#: 守卫钩子表（name → callable(env, player) -> str|None）
GUARDS = {"player": player}


# ============================================================
# B18 L3c（战斗族）追加段 —— **只追加**，不动上面任何一行（7 路并发避冲突）
# ============================================================
# 本段收的是宿主两个**非 player** 守卫的「判定 + 文案」（策略属内容）：
#   · `battle`          = 旧宿主 `saintess_engine.command.require_battle`（文案 = `battle_none_hint`）
#   · `no_prof_waiting` = 旧宿主 `game/commands/base.py::no_prof_waiting`（等待型副业互斥）
# 两者判定都要「活人世界」（battle_state 行 / 副业等待状态）→ 经 `env.state["shell"]`
# （宿主壳对象，桥接层注入的过渡能力口，与 `content/cmds_tower.py` 同源）取件；
# **文案与分支逐字 = 旧装饰器**，故改造前后玩家看到的整句一字不差。
#
# 备注：`battle` 用**包侧同名钩子**（`hook:battle`）而非引擎内置名 —— 与样板选
# `hook:player` 同理（判定 + 文案同源在包；宿主 `_host_bridge` 对内置名也只做「转发到包侧
# 同名钩子」的兜底，故两条通道回话逐字相同）。

#: 「不在战斗中」的拦截回话（逐字 = 宿主 `CommandBase.battle_none_hint`，`require_battle` 的 hint 为空）
BATTLE_NONE_HINT = "你附近没有敌人！输入『探索』寻找敌人～"


def _shell(env):
    """宿主壳对象（桥接层经 `env.state["shell"]` 注入）——过渡能力口；无 → None。"""
    return (env.state or {}).get("shell")


def _now(env) -> int:
    """当前秒（宿主注入的 `time.time` 优先）= 旧装饰器里的 `int(time.time())`。"""
    import time
    clock = getattr(env, "clock", None)
    return int(clock() if callable(clock) else time.time())


def battle(env, player=None):
    """战斗中守卫 —— 判定 = 宿主壳 `_in_any_battle`（普通战斗 or 副本战斗），文案逐字同旧。"""
    shell = _shell(env)
    fn = getattr(shell, "_in_any_battle", None) if shell is not None else None
    if callable(fn) and fn(env.group_id, env.uid):
        return None
    return BATTLE_NONE_HINT


def no_prof_waiting(env, player=None):
    """等待型副业（垂钓/采集/挖掘）进行中 → 拦截（判定 + 文案逐字 = 宿主旧装饰器）。

    旧实现（`game/commands/base.py::no_prof_waiting`）：
        st = self._prof_wait_state(group_id, qq_id)
        if st and st["finish"] > int(time.time()):
            left = st["finish"] - int(time.time())     # ← 两次独立取时（逐字保留）
            tname = C.PROF_WAIT_BASE.get(st["type"], (0, 0, "副业"))[2]
            ... 两句提示 ...
    """
    from .catalog_life import PROF_WAIT_BASE
    shell = _shell(env)
    fn = getattr(shell, "_prof_wait_state", None) if shell is not None else None
    if not callable(fn):
        return None
    st = fn(env.group_id, env.uid)
    if st and st["finish"] > _now(env):
        left = st["finish"] - _now(env)
        tname = PROF_WAIT_BASE.get(st["type"], (0, 0, "副业"))[2]
        # v101.25 #307：等待期互斥是设计使然（防结算错乱），提示说清等待期能做什么
        return (f"⏳ 你还在{tname}呢，再有 {left} 秒完成！(完成后自动入包)\n"
                f"💡 等待期间可以『背包』『属性』『任务』，但移动/探索/战斗要等{tname}结束～")
    return None


GUARDS.update({"battle": battle, "no_prof_waiting": no_prof_waiting})
__all__ += ["BATTLE_NONE_HINT", "battle", "no_prof_waiting"]


# ============================================================
# ★ B18-L4 追加（本段起为新增；上面一律未改）：GM 权限守卫
# ============================================================
def gm(env, player=None):
    """GM 权限守卫（声明 `hook:gm`）—— 判定 + 文案都在包内。

    * **判定唯一真源** = `content/gm.py::gm_auth`（v104.1 M24：白名单为空 ⇒ 默认拒绝一切
      GM 指令），本函数只负责「从哪拿身份」这一件事；
    * 身份来源 = 宿主共享 `game/commands/base.py` 的 `_is_gm` / `_gm_whitelist`（本批禁改），
      经 `env.state["shell"]` 这个过渡期能力口取（与 tower 的 `_open_tower_battle` 同款）；
    * 缺宿主身份能力（编辑器/独立运行）→ **fail-closed**：按「白名单为空」处理，
      回话仍是包内那条（不静默放行）。
    """
    shell = (getattr(env, "state", None) or {}).get("shell")
    is_gm = getattr(shell, "_is_gm", None)
    wl = getattr(shell, "_gm_whitelist", None)
    if not callable(is_gm) or not callable(wl):
        is_gm, wl = (lambda qq_id: False), (lambda: set())
    from .gm import gm_auth                       # 函数内 import：守卫装载期不拉数据域
    ok, err = gm_auth(is_gm, wl, getattr(env, "uid", ""))
    return None if ok else err


GUARDS["gm"] = gm
