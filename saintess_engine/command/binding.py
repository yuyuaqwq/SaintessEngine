# -*- coding: utf-8 -*-
"""指令**声明式绑定** —— 声明表里一条命令直接点名「实现体 + 参数 + 调用模式」。

要解决的问题
------------
声明表已经能描述「一条指令长什么样」（正则 / 分类 / 顺序 / 守卫名），但**实现体**还得
由使用方写一段薄壳把它接上去：取参 → 调实现体 → 驱动 → 收集回话。几十上百条命令就是
几十上百段同构的壳，改一次调用约定要改一百处。

本模块把那段壳收成**数据**：声明条目上多一个可选键 `bind`：

    "shortcut": {
      "patterns": ["…"], "desc": "…", "guards": ["…"], "order": 12,
      "bind": {"handler": "content.player_cmds:shortcut",
               "call": "run",
               "args": ["group_id", "uid", "player"]}
    }

三个键就是全部词汇表（**不扩张**）：

* ``handler`` —— ``"<模块>:<限定名>"``（限定名可带点，如 ``EconomyImpl.gather``）；
  解析不到 / 不可调用 → 装载期抛 `BindError`（fail-closed，绝不静默少一条命令）。
* ``call``    —— 调用模式，只有三种：

  ==========  ==================================================================
  ``run``     同步驱动 async generator；用 `TextSink` 接住 ``yield`` 出来的行，
              返回行列表（取空后若没有 yield 值则退回替身收集到的行）。
              ``await <纯协程>`` 递归驱动后回送（纯协程链）；真挂起 → 报错。
  ``messages``  ``await`` 消费 async generator（或 await 一个协程），返回行列表。
  ``sync``    同步取空「零 ``await`` 的 async generator」；命中真 ``await`` → 报错（fail-closed）。
  ==========  ==================================================================

* ``args``    —— 取参槽位，取值只有 ``group_id`` / ``uid`` / ``player``（按名从 `Env` 取）；
  其余一律报错点名。

调用帧
------
三种模式统一按同一帧调用实现体::

    handler(*lead(env), sink, *args)

``lead`` 是使用方给的前导实参工厂（缺省空元组）—— 「宿主注入的取件口」属内容/宿主侧约定，
引擎不认名字，只原样摆在最前面；``sink`` 是 `TextSink`（文本收集替身）；其后是 ``args``。

零知识
------
本模块只认「模块名 / 限定名 / 三个槽位名 / 三种驱动模式」，不认任何具体指令、文案或守卫语义；
`TextSink` 只接管 ``plain_result`` 这一个写口，其余属性一律原样代理它包住的对象。
"""
from __future__ import annotations

import importlib
import inspect
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence

__all__ = [
    "ARG_TOKENS", "CALL_MODES", "BindError", "BindSpec", "TextSink",
    "resolve_handler", "bind_handler", "drive_generator", "collect_messages",
]

#: `bind.args` 的取值词汇表（引擎不解释语义，只按名从 `Env` 取；其余报错点名）
ARG_TOKENS = ("group_id", "uid", "player")

#: `bind.call` 的调用模式词汇表
CALL_MODES = ("run", "messages", "sync")

#: `bind` 条目的全部合法键（多一个都报错 —— 拼错 `handler` 不许静默变成「没绑定」）
_BIND_KEYS = ("handler", "call", "args")

_DEFAULT_CALL = "run"

#: 「本替身没有本地覆盖过这个属性」的哨兵
_MISSING = object()


class BindError(ValueError):
    """`bind` 声明不合法 / 处理器解析不到：装载期 fail-closed，绝不静默降级。"""


# ============================================================ 声明
def _where(key: str, where: str) -> str:
    parts = []
    if where:
        parts.append(str(where))
    if key:
        parts.append("key=%r" % (key,))
    return "（%s）" % "，".join(parts) if parts else ""


@dataclass(frozen=True)
class BindSpec:
    """一条 `bind` 声明：实现体引用 + 调用模式 + 取参槽位。字段全为**通用形状**。

    * `handler` —— ``"<模块>:<限定名>"``；解析动作在 `bind_handler()`（装载期，fail-closed）
    * `call`    —— `CALL_MODES` 之一
    * `args`    —— `ARG_TOKENS` 的子集（按声明顺序取参）
    """
    handler: str
    call: str = _DEFAULT_CALL
    args: tuple = ()

    # ---------- 装载 ----------
    @classmethod
    def from_data(cls, raw: Any, *, key: str = "", where: str = "") -> "BindSpec":
        """dict → 声明。**任何不合词汇表的写法都在这里抛 `BindError`**（不返回半成品）。"""
        if not isinstance(raw, Mapping):
            raise BindError("指令绑定必须是对象：%r%s" % (raw, _where(key, where)))
        unknown = [k for k in raw if k not in _BIND_KEYS]
        if unknown:
            raise BindError("指令绑定出现未知键 %s（只认 %s）%s"
                            % (sorted(unknown), list(_BIND_KEYS), _where(key, where)))

        handler = raw.get("handler")
        if not isinstance(handler, str) or not handler.strip():
            raise BindError("指令绑定的 handler 必须是非空字符串：%r%s"
                            % (handler, _where(key, where)))

        call = raw.get("call", _DEFAULT_CALL)
        if call not in CALL_MODES:
            raise BindError("指令绑定的 call 未知：%r（只认 %s）%s"
                            % (call, list(CALL_MODES), _where(key, where)))

        raw_args = raw.get("args", ())
        if raw_args is None:
            raw_args = ()
        if isinstance(raw_args, str) or not isinstance(raw_args, (list, tuple)):
            raise BindError("指令绑定的 args 必须是序列：%r%s" % (raw_args, _where(key, where)))
        args = []
        for token in raw_args:
            if token not in ARG_TOKENS:
                raise BindError("指令绑定的 args 出现未知槽位：%r（只认 %s）%s"
                                % (token, list(ARG_TOKENS), _where(key, where)))
            args.append(str(token))
        return cls(handler=handler.strip(), call=str(call), args=tuple(args))

    def to_data(self) -> dict:
        """回写成 JSON 友好结构（round-trip 稳定）。"""
        return {"handler": self.handler, "call": self.call, "args": list(self.args)}


# ============================================================ 文本收集替身
class TextSink:
    """实现体看到的「平台事件」替身：`plain_result(文本)` 收成一行并原样返回。

    为什么需要它：历史形状的实现体是 ``yield event.plain_result(文本)`` —— 直接交**真事件**
    会让 ``yield`` 出来的是平台结果对象而不是文案。本替身把那一句收成「一行文案」。

    与真对象的关系（三个写口，其余全代理）：
    * ``plain_result``  —— 收进 `lines` 并返回文本（实现体的 `yield` 值 = 一行文案）；
    * ``message_str``   —— **未本地赋值时读真对象**；本地赋值后以本地为准，且不写回真对象
      （实现体自己改写「本条消息」的语义照旧，外部看到的真对象一字未动）；
    * 其余属性 / 方法（`stop_event()` / `get_sender_id()` / 各类注入口）—— 逐字代理真对象，
      读写都落到真对象上。
    """

    def __init__(self, ev: Any) -> None:
        object.__setattr__(self, "_ev", ev)
        object.__setattr__(self, "lines", [])
        object.__setattr__(self, "_ms", _MISSING)

    # ---------- 被接管的两个口 ----------
    def plain_result(self, text):
        """把「一行文本」收起来并**返回文本本身**（`yield` 值 = 一行文案）。"""
        object.__getattribute__(self, "lines").append(text)
        return text

    def get_message_str(self):
        """本条消息原文：本地赋值过就用本地的，否则问真对象（没有该方法则读属性）。"""
        ms = object.__getattribute__(self, "_ms")
        if ms is not _MISSING:
            return ms
        ev = object.__getattribute__(self, "_ev")
        getter = getattr(ev, "get_message_str", None)
        if callable(getter):
            return getter()
        return getattr(ev, "message_str", "") or ""

    def __getattr__(self, name):
        if name == "message_str":
            ms = object.__getattribute__(self, "_ms")
            if ms is not _MISSING:
                return ms
        return getattr(object.__getattribute__(self, "_ev"), name)

    def __setattr__(self, name, value):
        if name == "lines":
            object.__setattr__(self, name, value)
        elif name == "message_str":
            object.__setattr__(self, "_ms", value)
        else:
            setattr(object.__getattribute__(self, "_ev"), name, value)


# ============================================================ 处理器解析
def resolve_handler(ref: Any, *, resolve: Optional[Callable] = None,
                    where: str = "") -> Callable:
    """把 ``"<模块>:<限定名>"`` 解析成可调用；解析不到 / 不可调用 → `BindError`。

    `resolve` 由使用方给时优先（宿主/包自己的取件口径）；给不出可调用一律抛错 ——
    这里**不存在**「返回 None 让调用方自己兜底」的路径（那正是静默少一条命令的入口）。
    """
    fn = None
    cause = None
    if resolve is not None:
        try:
            fn = resolve(ref)
        except Exception as exc:                                 # noqa: BLE001  原因原样带进报错
            cause = exc
    else:
        fn, cause = _import_ref(ref)
    if not callable(fn):
        extra = "" if cause is None else "（原因：%r）" % (cause,)
        raise BindError("指令绑定：handler 解析不到或不可调用：%r%s%s"
                        % (ref, extra, where))
    return fn


def _import_ref(ref: Any):
    """``"pkg.mod:Name.attr"`` / ``"pkg.mod.Name"`` → (对象, 失败原因)。"""
    if not isinstance(ref, str) or not ref.strip():
        return None, None
    ref = ref.strip()
    mod_name, sep, attr = ref.partition(":")
    if not sep:
        mod_name, sep, attr = ref.rpartition(".")
    if not mod_name or not attr:
        return None, None
    try:
        obj = importlib.import_module(mod_name)
    except Exception as exc:                                     # noqa: BLE001
        return None, exc
    for part in attr.split("."):
        obj = getattr(obj, part, None)
        if obj is None:
            return None, None
    return obj, None


# ============================================================ 驱动
def drive_generator(agen, *, allow_await: bool = True, where: str = "") -> list:
    """**同步**驱动一个 async generator 取空 → 产出列表。

    * `allow_await=True`：``await <协程>`` 递归驱动后把结果回送（纯协程链）；
      `yield` 出非可等待对象 / 需要事件循环的对象 → `BindError`（真挂起，不静默吞）。
    * `allow_await=False`：只跑**零 await** 的生成器；命中真 ``await`` → `BindError`。
    """
    out = []
    while True:
        try:
            step = agen.__anext__()
        except StopAsyncIteration:
            return out
        try:
            out.append(_drive_coro(step, allow_await=allow_await, where=where))
        except StopAsyncIteration:                               # 生成器取空（`__anext__` 的收尾）
            return out


def _drive_coro(coro, *, allow_await: bool, where: str):
    """把一个协程驱动到「本次产出」并返回其值（`allow_await=False` 时命中 await 即报错）。"""
    to_send, to_throw = None, None
    while True:
        try:
            item = coro.throw(to_throw) if to_throw is not None else coro.send(to_send)
        except StopIteration as stop:
            return stop.value
        if not allow_await:
            raise BindError("指令绑定：sync 模式要求实现体零 await，但它挂起了（yield %r）%s"
                            % (item, where))
        if not inspect.isawaitable(item):
            raise BindError("指令绑定：实现体真挂起（yield 出非可等待对象 %r）%s" % (item, where))
        if not hasattr(item, "send"):
            raise BindError("指令绑定：实现体 await 了需要事件循环的对象（%s）%s"
                            % (type(item).__name__, where))
        try:
            to_send, to_throw = _drive_coro(item, allow_await=allow_await, where=where), None
        except BaseException as exc:                             # noqa: BLE001  按 await 语义回注
            to_send, to_throw = None, exc


async def collect_messages(value, *, where: str = "") -> list:
    """`messages` 模式：``await`` 消费 async generator（或 await 一个协程）→ 行列表。

    两者都不是 → `BindError`（与「拿 async generator 去 ``async for``」同口径：fail-closed）。
    """
    if hasattr(value, "__aiter__"):
        out = []
        async for item in value:
            out.append(item)
        return out
    if inspect.isawaitable(value):
        return await value
    raise BindError("指令绑定：messages 模式要求实现体交 async generator / 协程，拿到 %r%s"
                    % (type(value).__name__, where))


# ============================================================ 绑定
def _env_args(env, tokens: Sequence[str]) -> tuple:
    """按槽位名从 `Env` 取参（词汇表已在校验期锁死，这里只按名取）。"""
    return tuple(getattr(env, token) for token in tokens)


def bind_handler(spec: BindSpec, *, resolve: Optional[Callable] = None,
                 lead: Optional[Callable] = None,
                 where: str = "") -> Callable:
    """一条 `bind` 声明 → 可调用处理器 ``fn(env) -> list``（包内不写薄壳）。

    * `resolve` —— 处理器取件口（缺省按 ``"<模块>:<限定名>"`` 直接 import）
    * `lead`    —— 前导实参工厂 ``env -> tuple``（缺省空）；调用帧 = ``handler(*lead(env), sink, *args)``
    * 返回的可调用：`messages` 模式是 ``async def``（调用方 `await`），另两种是同步 ``def``
      —— 与「包内 handler 交 `list[str]`」的既有约定一致。
    """
    fn = resolve_handler(spec.handler, resolve=resolve, where=where)
    lead = lead or _no_lead
    if spec.call == "messages":
        async def handler(env):
            sink = TextSink(getattr(env, "raw", None))
            out = fn(*tuple(lead(env)), sink, *_env_args(env, spec.args))
            return await collect_messages(out, where=where)
    else:
        allow_await = spec.call == "run"

        def handler(env):
            sink = TextSink(getattr(env, "raw", None))
            out = fn(*tuple(lead(env)), sink, *_env_args(env, spec.args))
            lines = drive_generator(out, allow_await=allow_await, where=where)
            return lines or object.__getattribute__(sink, "lines")

    handler.__name__ = getattr(fn, "__name__", "") or _leaf(spec.handler)
    handler.__qualname__ = handler.__name__
    handler.__doc__ = "声明式绑定的处理器（%s 模式 → %s）。" % (spec.call, spec.handler)
    return handler


def _no_lead(env) -> tuple:
    return ()


def _leaf(ref: str) -> str:
    """``"a.b:C.d"`` → ``"d"``（只用于给生成的处理器起名，便于漂移自检按名对账）。"""
    return str(ref).rpartition(":")[2].rsplit(".", 1)[-1] or str(ref)
