# -*- coding: utf-8 -*-
"""handler 路由骨架 —— 按文本找到该由谁处理，并把文本转发给它。

场景：宿主把「快捷指令 / 别名 / 后缀」当普通消息发来时，需要**找到真正的
handler 并转发**（临时替换消息文本让它正确解析参数）。

框架不认识宿主的注册表，所以**宿主探测函数由使用方注入**：

    finder(text) -> HandlerHit | None

未注入（或探测失败）时回退到**静态正则表**（使用方给的
`[(已编译正则, 方法名)]`）—— 测试环境与静态分析下没有宿主注册表，靠它兜底。

`HandlerHit` 是 `NamedTuple`（不是 dataclass）—— 保 `hit[0]` 取到 **handler 名**：
调用方/测试已有 `hit[0]` 取名字的写法，形状不能变。
"""
from __future__ import annotations

import functools
import inspect
import logging
import re
from typing import Any, Callable, NamedTuple, Optional, Sequence

__all__ = ["HandlerHit", "find_static", "matches_any", "run_shortcut", "PatternSet"]

_log = logging.getLogger("saintess_kit.command")


class HandlerHit(NamedTuple):
    """一次命中的处理器。

    * `handler_name`：处理器名（诊断/测试用；`hit[0]` 即它）
    * `fn`：可直接调用的callable（是否已绑定见 `prebound`）
    * `prebound`：True → `fn(event)`；False → `fn(self, event)`
    * `raw`：宿主原始元数据（框架不解释，透传给调用方备查）
    """
    handler_name: str
    fn: Callable
    prebound: bool
    raw: Any = None


def matches_any(text: str, patterns: Sequence, *, skip_empty: bool = True) -> bool:
    """文本是否命中任一正则。

    `skip_empty=True`（默认）：**跳过零宽匹配** —— 有些仅用于挂载的正则
    （如「任意消息」那种）会零宽命中，若不跳过则日常聊天全被命中。
    """
    for pat in patterns:
        try:
            m = pat.search(text)
        except re.error:
            continue
        if m and (m.group(0) or not skip_empty):
            return True
    return False


class PatternSet:
    """懒编译 + 缓存的命令正则集合（供宿主的 filter 类调用）。

    使用方给「取正则字符串的函数」，本类负责编译与缓存一次。
    """

    def __init__(self, patterns_getter: Callable[[], Sequence[str]]) -> None:
        self._get = patterns_getter
        self._compiled: Optional[list] = None

    def patterns(self) -> list:
        if self._compiled is None:
            self._compiled = []
            for pat in self._get() or ():
                try:
                    self._compiled.append(re.compile(pat))
                except re.error:
                    continue
        return self._compiled

    def matches(self, text: str, *, skip_empty: bool = True) -> bool:
        return matches_any(text or "", self.patterns(), skip_empty=skip_empty)

    def reset(self) -> None:
        self._compiled = None


def find_static(text: str, static_handlers: Sequence, owner: Any) -> Optional[HandlerHit]:
    """在静态表 `[(已编译正则, 方法名)]` 里找；命中则取出 `owner` 上的绑定方法。"""
    for entry in static_handlers or ():
        try:
            regex, name = entry
        except (TypeError, ValueError):
            continue
        try:
            if not regex.search(text):
                continue
        except re.error:
            continue
        fn = getattr(owner, name, None)
        if fn is None:
            return None
        return HandlerHit(name, fn, True, raw=regex)
    return None


async def run_shortcut(owner: Any, event: Any, text: str, finder: Callable[[str], Optional[HandlerHit]], *,
                       not_found_msg: str = "❌ 快捷指令『{text}』无法识别，请先确认指令存在～",
                       error_prefix: str = "❌ 快捷指令执行出错：",
                       swap_attr: str = "message_str",
                       logger: Optional[logging.Logger] = None):
    """把 `text` 当指令转发给命中的 handler（async generator，逐条 yield 其产物）。

    * 转发期间**临时把 `event.<swap_attr>` 换成 `text`**，结束后恢复（让目标 handler
      按预期解析参数）
    * 兼容「async generator」（逐条 yield）与「coroutine」（await 后 yield 结果）
    * 找不到 / 执行异常 → yield 一条提示，不抛
    """
    lg = logger or _log
    hit = finder(text)
    if not hit:
        yield event.plain_result(not_found_msg.format(text=text))
        return

    orig = getattr(event, swap_attr, None)
    try:
        setattr(event, swap_attr, text)
        if hit.prebound:
            gen = hit.fn(event)
        else:
            gen = hit.fn(owner, event)
        if inspect.isasyncgen(gen):
            async for r in gen:
                yield r
        else:
            r = await gen
            if r:
                yield r
    except Exception as e:  # noqa: BLE001
        lg.warning("[saintess_kit.command] 快捷转发失败 %s: %s", text, e)
        yield event.plain_result(f"{error_prefix}{e}")
    finally:
        if orig is not None:
            setattr(event, swap_attr, orig)
