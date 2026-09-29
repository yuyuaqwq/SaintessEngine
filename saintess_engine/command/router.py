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

import inspect
import logging
import re
from typing import Any, Callable, NamedTuple, Optional, Sequence

from ..log import get_logger

__all__ = ["HandlerHit", "find_static", "matches_any", "run_shortcut", "PatternSet"]

_log = get_logger("command")


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

    ★ 本类是**独立于 `CommandRegistry` 的第二条编译入口**（注册表那条走
      `register()` 的漏斗），因此本类**自带**逐条编译校验、不复用注册表那份 ——
      复用会引入跨模块顶层 import（`registry` 并不 import `router`，反之亦然，
      但仓内判据存在「单文件装载」用法，顶层 import 会打红它们），
      故两处各自守自己那一口，口径与错误串保持逐字同形。
    """

    def __init__(self, patterns_getter: Callable[[], Sequence[str]]) -> None:
        self._get = patterns_getter
        self._compiled: Optional[list] = None

    def patterns(self) -> list:
        if self._compiled is None:
            self._compiled = []
            for pat in self._get() or ():
                # ★ 非法正则**点名抛**（2026-09-29 审计 · 同 L5577 装载期 fail-closed 同族）。
                #   原写法 `except re.error: continue` 是**静默丢弃**：本类被宿主的
                #   「是不是游戏指令」过滤器（`host/_platform._GameCmdFilter`）**直接使用**，
                #   而那条声明的正则若非法，玩家那条指令在过滤器眼里**根本不是游戏指令**
                #   —— 停服 gate 拦不住它、日常消息走不到它的 handler，全程零异常零日志。
                #   与同仓 `find_static` 的 L298 fail-closed（静态表方法名取不到 ⇒ 抛，
                #   不与「没命中」同形）同一判据：**认不出就点名，不与「没这条」同形**。
                #   错误串沿用注册表 `_reject_bad_patterns` 的同一形态，便于两处对读。
                if not isinstance(pat, str):
                    raise TypeError("指令正则必须是非空字符串：%r" % (pat,))
                # ★ **空串不跳过**：空模式是**合法的零宽正则**（re.compile('') 合法），
                #   本类的 skip_empty 开关就是为它准备的（零宽匹配默认不算命中）——
                #   把它当「非法/空声明」丢掉会改掉既有语义。
                #   注册表那条漏斗之所以跳过空串，是因为它**逐条**编译；
                #   本类要保留它们交给 matches_any 的 skip_empty 判定。两者口径不同是有理由的。
                try:
                    self._compiled.append(re.compile(pat))
                except re.error as e:
                    raise ValueError("指令正则非法（%s）—— %s" % (e, pat)) from e
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
            # ★ fail-closed（台账 L298）：静态表里写着的方法名在 owner 上取不到，
            #   那是**声明与实现不一致**（改名/拼错/忘了继承），不是「这条没命中」。
            #   原写法 return None 让它与「整表扫完都没命中」**完全同形** ⇒
            #   玩家只看到「快捷指令无法识别」，维护者拿不到任何线索，
            #   而这条指令在静态表里明明挂着。认不出就抛（本作核心铁律）。
            raise AttributeError(
                "静态表里的 handler 名在 owner 上取不到（声明与实现不一致）"
                "：method=%r owner=%r pattern=%r" % (name, type(owner).__name__, getattr(regex, "pattern", regex))
            )
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
        # ★ 2026-09-28 审计 L288-2：异常**详情**只进日志，玩家那一行只给通用句。
        #   原写法 f"{error_prefix}{e}" 把 KeyError('dungeon_floor_id') 这类内部细节
        #   （机器键 / 字段名 / 内部路径）直接印给玩家，违反「玩家可见文本禁机器键」。
        #   日志侧补 exc_info 让 traceback 也可追（原先只有 str(e)，丢栈）。
        lg.warning("[saintess_engine.command] 快捷转发失败 %s: %s", text, e, exc_info=True)
        yield event.plain_result(error_prefix + "（详情见服务端日志）")
    finally:
        if orig is not None:
            setattr(event, swap_attr, orig)
