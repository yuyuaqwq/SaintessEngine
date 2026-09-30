# -*- coding: utf-8 -*-
"""日志门面 —— 命名、级别 / 格式 / 出口配置、结构化上下文绑定。

可拔插契约：「**不配置 = 不存在**」
--------------------------------
不调 `configure()` 时，本模块只是标准库 `logging` 的**薄封装**：

* `get_logger("x")` 返回的**就是** `logging.getLogger("<prefix>.x")` **本体**
  （`is` 同一对象，不是包装器）
* 不添加 handler、不改级别、不动 `propagate` —— 宿主自己的 logging 配置与现状**逐字一致**

于是「用不用这套门面」都不改变既有日志行为；要出口就显式 `configure(sinks=[...])`。
反过来 `configure(sinks=())` 也**不改任何出口**（空 sinks 不是「清空」，是「不管」）。

命名
----
    get_logger("battle.turn")   # → <prefix>.battle.turn，prefix 默认 "saintess_engine"

`prefix` 由宿主给（`configure(prefix="my_game")`），**应在装配早期设置** —— 它只影响
之后的 `get_logger` 调用（已建好的 logger 对象名字不会变）。

典型用法::

    from saintess_engine.log import get_logger, configure, FileSink, bind

    log = get_logger("battle")
    log.warning("回合超时 actor=%s", aid)          # 不配置 = 走宿主原有 logging

    configure(prefix="my_game", level="INFO", fmt="%(levelname)s %(name)s %(message)s",
              sinks=[FileSink("run/app.log", rotate="size")])

    bind(log, actor="p1", command="攻击").info("结算完成")   # actor/command 进 record 字段

零知识：不 import 宿主、不认玩家、不认任何游戏名词。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from .sinks import DEFAULT_FMT, SinkHandler

__all__ = [
    "DEFAULT_FMT", "DEFAULT_PREFIX", "RESERVED_KEYS",
    "ContextAdapter", "bind", "configure", "get_logger", "logger_name", "remove_sinks",
]

# 引擎自己的命名前缀（宿主可改：configure(prefix="my_game")）
DEFAULT_PREFIX = "saintess_engine"

# 模块级状态：当前 prefix + 已装出口（按 prefix 记，便于幂等与回收）
_state: dict = {"prefix": DEFAULT_PREFIX}
_installed: dict = {}


def _reserved_keys() -> frozenset:
    """`LogRecord` 自带的属性名 —— 上下文键与之冲突时标准库会 `KeyError`，故 fail-fast。"""
    r = logging.LogRecord("", 0, "", 0, "", (), None)
    return frozenset(set(vars(logging.LogRecord)) | set(r.__dict__)
                     | {"message", "asctime"})


RESERVED_KEYS = _reserved_keys()


def logger_name(name: str = "", *, prefix: Optional[str] = None) -> str:
    """算 logger 全名：`<prefix>.<name>`（`name` 为空则是 `<prefix>`）。"""
    p = prefix if prefix is not None else _state["prefix"]
    return f"{p}.{name}" if name else p


def get_logger(name: str = "", *, prefix: Optional[str] = None) -> logging.Logger:
    """取 logger（**不配置时等价于 `logging.getLogger(全名)`**）。

    `prefix` 显式给定时只影响本次取名，不改模块级状态。
    """
    return logging.getLogger(logger_name(name, prefix=prefix))


def _drop_installed(name: str) -> None:
    """摘掉 `name` 上**本门面装的** handler（removeHandler + close）—— 换 prefix 时用。

    ★ 审计 L1032（2026-09-30）：`_installed` 按 prefix 记 —— 换 prefix 后旧条目再也没有
    默认摘除路径（`remove_sinks()` 无参摘的是**新** prefix）⇒ 旧 handler 继续收日志、
    文件句柄永不 close（与「摘出口要 close」同族的漏洞）。修法：换 prefix 时按**旧
    prefix** 摘除 + close + 一条 warning（不静默）。宿主/别人自己 `addHandler` 的照旧不碰。
    """
    handler = _installed.pop(name, None)
    if handler is None:
        return
    logging.getLogger(name).removeHandler(handler)
    try:
        handler.close()
    except Exception:                                             # noqa: BLE001
        pass
    logging.getLogger(name).warning(
        "configure 换 prefix：旧 prefix %r 上本门面装的日志出口已摘除并关闭（不留孤儿 handler）",
        name)


def configure(*, level=None, fmt: Optional[str] = None, sinks=(),
              prefix: Optional[str] = None, propagate: Optional[bool] = None
              ) -> logging.Logger:
    """显式配置（★ 调了才生效 —— 可拔插的落点）。

    参数
    ----
    level:     级别（字符串或 int；None = 不动）
    fmt:       文本 sink 的排版（对实现了 `set_format()` 的 sink 生效；None = 不动）
    sinks:     出口序列；**空（默认）= 不动任何出口**，非空 = 换成本批出口（幂等：替换上次装的）
    prefix:    命名前缀（None = 不动；须为非空字符串）。★ 换 prefix 时（审计 L1032）：
               旧 prefix 上**本门面装的**出口会被摘除并关闭 + 一条 warning —— 换前缀即换
               出口归属，不留孤儿 handler（宿主自己 `addHandler` 的一律不碰）
    propagate: 是否向父 logger 冒泡（None = 不动）—— 宿主 root 另有 handler 时用它去重

    返回配好的 prefix logger。
    """
    if prefix is not None:
        if not isinstance(prefix, str) or not prefix.strip():
            raise ValueError(f"prefix 须为非空字符串，收到 {prefix!r}")
        old_name = _state["prefix"]
        if prefix != old_name:
            _drop_installed(old_name)          # 换 prefix：先收旧出口（审计 L1032）
        _state["prefix"] = prefix

    name = _state["prefix"]
    logger = logging.getLogger(name)

    # ★ 入口一次物化：`if sinks:` 对生成器恒真，而下面的 `for s in sinks` 会把它吃干，
    # 随后 SinkHandler 拿到 0 个 sink —— 且因为已判过真，不进 else、不报错，
    # 日志静默丢失（实测 buf 为空）。类型标注是 Sequence，但这是唯一公开装配口、没有门禁拦。
    sinks = list(sinks)
    if sinks:
        if fmt is not None:
            for s in sinks:
                setter = getattr(s, "set_format", None)
                if callable(setter):
                    setter(fmt)
        old = _installed.get(name)
        if old is not None:
            logger.removeHandler(old)
            try:
                old.close()
            except Exception:                                     # noqa: BLE001
                pass
        handler = SinkHandler(sinks)
        logger.addHandler(handler)
        _installed[name] = handler

    if level is not None:
        logger.setLevel(level)
    if propagate is not None:
        logger.propagate = bool(propagate)
    return logger


def remove_sinks(*, prefix: Optional[str] = None) -> int:
    """摘掉门面装过的出口（返回摘掉几个；用于测试复原与运行期关闭）。

    只动**本门面装过的** handler，宿主自己 `addHandler` 的一律不碰。
    """
    name = prefix if prefix is not None else _state["prefix"]
    handler = _installed.pop(name, None)
    if handler is None:
        return 0
    logging.getLogger(name).removeHandler(handler)
    try:
        handler.close()
    except Exception:                                             # noqa: BLE001
        pass
    return 1


class ContextAdapter(logging.LoggerAdapter):
    """带结构化上下文的 logger（`bind()` 返回它）。

    上下文进 `record.__dict__` —— sink 可据此落库 / 按字段查
    （`record.actor` / `record.command`）。`bind()` 可链式叠加（后写的覆盖先写的）。

    保留键冲突**构造期即 `ValueError`**（与 `bind()` 同一把尺）—— 裸构造也是正当入口。
    """

    def __init__(self, logger: logging.Logger, extra: Optional[dict] = None) -> None:
        # 保留键在这里 fail-fast —— 否则脏字段要到 emit 才由标准库抛 `KeyError`，
        # 且**级别不够高时连那个 KeyError 都没有**（整条静默混过）。
        _reject_reserved(extra or {})
        super().__init__(logger, dict(extra or {}))

    def process(self, msg, kwargs):
        extra = kwargs.get("extra")
        kwargs["extra"] = {**self.extra, **extra} if extra else dict(self.extra)
        return msg, kwargs

    def bind(self, **ctx) -> "ContextAdapter":
        _reject_reserved(ctx)
        return ContextAdapter(self.logger, {**self.extra, **ctx})


def _reject_reserved(ctx) -> None:
    bad = sorted(k for k in ctx if k in RESERVED_KEYS)
    if bad:
        raise ValueError(
            f"上下文键与 LogRecord 内置属性冲突：{bad}（标准库会因此 KeyError）——"
            f"请换个键名，如 actor / subject / command / duration")


def bind(logger: Any, **ctx) -> ContextAdapter:
    """给 logger 绑上下文，返回 `ContextAdapter`（也叫 bound logger）。

        log = bind(get_logger("battle"), actor="p1")
        log.info("命中")               # record.actor == "p1"
        bind(log, target="e9").info("连击")   # actor + target 都在

    保留键冲突**直接报错**（`ValueError`）—— 不静默吞掉用户的字段。
    """
    _reject_reserved(ctx)
    if isinstance(logger, ContextAdapter):
        return logger.bind(**ctx)
    if logger is None:
        logger = get_logger("")
    return ContextAdapter(logger, ctx)
