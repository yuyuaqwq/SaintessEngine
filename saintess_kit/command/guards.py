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

DEFAULT_REGISTER_HINT = "你还没有角色！"
DEFAULT_BATTLE_HINT = "你附近没有敌人！"


def require_player(hint: Optional[str] = None):
    """玩家存在性守卫（装饰 `async generator` 命令方法）。

    用法::

        @filter.regex(r"...")
        @require_player()
        async def move(self, event): ...

    文案优先级：`hint` 参数 > `self.register_hint` > 框架默认。
    """
    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(self, event, *args, **kwargs):
            group_id, qq_id = self._uid(event)
            if not self._player(group_id, qq_id):
                text = hint if hint is not None else getattr(
                    self, "register_hint", DEFAULT_REGISTER_HINT)
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
                base = getattr(self, "battle_none_hint", DEFAULT_BATTLE_HINT)
                yield event.plain_result(base + hint)
                return
            async for item in fn(self, event, *args, **kwargs):
                yield item
        return wrapper
    return deco
