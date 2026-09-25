# -*- coding: utf-8 -*-
"""命令守卫骨架 —— 「不满足条件就拦下并提示」的装饰器工厂。

宿主命令方法通常是 `async generator`（`yield event.plain_result(...)`），
守卫包一层：条件不满足 → yield 一条提示并 return；否则原样转发下游产物。

判定与文案都由**使用方**通过钩子/参数给（框架不认识「角色」「战斗」这些概念）：
* `require_player` → 调 `self._player(group_id, qq_id)`；文案取 `hint` 或 `self.register_hint`
* `require_battle` → 调 `self._in_any_battle(group_id, qq_id)`；文案取 `self.battle_none_hint` + hint
"""
from __future__ import annotations

import functools
from typing import Optional

__all__ = ["require_player", "require_battle"]

# ★ 2026-09-25（审计 E2b）：引擎**不带玩家可见文案**。这两句原先是引擎自带的游戏口气
#   （「你还没有角色！」这类是内容侧的话），现改为**必须由使用方声明**：
#   `self.register_hint` / `self.battle_none_hint`（内容侧/宿主给）。没声明 ⇒ 当场抛
#   `EngineNotConfigured`（fail-closed）——绝不静默给一句引擎自己编的玩家文案。
from ..config import EngineNotConfigured as _NotConfigured


def _hint_of(owner, attr: str, what: str) -> str:
    """取使用方声明的守卫文案；没声明 = 装配漏了（fail-closed，不当场编一句）。"""
    text = str(getattr(owner, attr, "") or "")
    if not text:
        raise _NotConfigured(
            "命令守卫文案没声明（%s）：请在命令基类/宿主上声明 `%s` —— "
            "守卫拦截句属内容侧文案，引擎不带玩家可见文案。" % (what, attr))
    return text


def require_player(hint: Optional[str] = None):
    """玩家存在性守卫（装饰 `async generator` 命令方法）。

    用法::

        @filter.regex(r"...")
        @require_player()
        async def move(self, event): ...

    文案优先级：`hint` 参数 > `self.register_hint`（内容侧声明；都没给 ⇒ 抛 `EngineNotConfigured`）。
    """
    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(self, event, *args, **kwargs):
            group_id, qq_id = self._uid(event)
            if not self._player(group_id, qq_id):
                text = hint if hint is not None else _hint_of(
                    self, "register_hint", "require_player")
                yield event.plain_result(text)
                return
            async for item in fn(self, event, *args, **kwargs):
                yield item
        return wrapper
    return deco


def require_battle(hint: str = ""):
    """战斗中守卫（装饰 `async generator` 命令方法）。

    文案 = `self.battle_none_hint` + `hint`（hint 用于追加场景化补充，如「技能列表」）。
    handler 内仍自行查询战斗对象（装饰器只做拦截判断）。
    """
    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(self, event, *args, **kwargs):
            group_id, qq_id = self._uid(event)
            if not self._in_any_battle(group_id, qq_id):
                base = _hint_of(self, "battle_none_hint", "require_battle")
                yield event.plain_result(base + hint)
                return
            async for item in fn(self, event, *args, **kwargs):
                yield item
        return wrapper
    return deco
