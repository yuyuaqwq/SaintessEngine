# -*- coding: utf-8 -*-
"""倒计时事件 —— 类型注册 + 实例挂载/刷新 + 懒过期 + 过期回调。无后台定时器。

形状
----
一份**倒计时事件表**挂在**主体**（owner）上：主体由调用方给，引擎原样透传、不做解释。
一个主体的表里可以有多个**事件**，各以 `key` 区分，各属于一个已注册的**类型**（`type_key`）::

    register(type_key, duration=..., on_expire=...)    # 类型：兜底时长 + 过期回调
    set(owner, key, type_key, data=..., duration=...)  # 挂载 / 顶替刷新，返回 expire 时间戳
    get(owner, key) / due(owner) / refresh(owner)      # 三条读路径：过期即清 + 回调
    remove(owner, key, fire=False)                     # 主动删除（缺省不回调）

懒计时（无后台定时器）
----------------------
引擎不建线程、不 sleep、不注册任何系统定时器：**时间只在被调用时读一次**，
「过期」= `now >= expire`。`now` 可由调用方显式传入，缺省取注入的 `clock()`。
于是「过期了还看得见」的窗口从形状上不存在 —— 三条读路径都在**同一个调用**里完成
「判定过期 → 物理清除 → 触发回调」。

一个事件过期，回调**至多触发一次**
----------------------------------
`on_expire(owner, key, data) -> None` 在该类型的实例**被清除时**调用一次；
`get` / `due` / `refresh` 三条路径都会走到它（读路径不得绕过）。
实现上**先清除并落盘、再触发回调** ⇒ 回调里再读同一个 key 只会拿到「没有」，
不会二次触发。回调自身抛错也不会让同一个事件再过期一次（仍至多一次）：
失败记 WARNING 留痕，且**不阻断**同一批里其余事件的回调 —— 清理副作用不会
因为一个内容侧回调 bug 而整批消失，也绝不静默。

存储由调用方注入
----------------
`store` 是内容侧给的**可读写映射**（事件域 / 存档域都行），引擎只做
`get / __setitem__ / __delitem__ / __contains__`，不认它的后端。布局：

* 键 —— `key(owner)`（缺省 = 主体本身）
* 值 —— `{事件 key: {"type": str, "data": dict, "expire": int}}`
* 缺失键 —— 读成「没有事件」（空表）
* 键在、值取不出来 —— **fail-closed**：抛 `TimerStorageError` 并点名该键，
  绝不静默当空（静默清空 = 在途倒计时与待触发的清理副作用一起蒸发）
* 表清空 —— 删掉该键（不留空壳）

有意不做的事
------------
* **不做时长公式**：`expire = clock() + duration` 现算；系数 / 随机 / 递进都不进引擎。
* **不做定时器 / 线程 / sleep**：过期只在被调用时判定。
* **不做游戏词汇**：`type_key` / `key` / `data` 全是内容侧词汇，引擎只当不透明载荷搬运。
* **不做写路径的顺带清理**：`set` 只顶替自己那一格；别的过期格留给读路径处理。
* **不做「过期不可见」以外的隐藏语义**：过期即不可见、不可查（`get` → None、`due` 不含它）。

典型用法::

    from saintess_engine.timers import Timers

    timers = Timers(store, clock, default_duration=60)
    timers.register("effect_x", duration=300, on_expire=clear_side_state)
    expire = timers.set("acct-1", "slot:a", "effect_x", data={"n": 1})
    timers.get("acct-1", "slot:a")     # 未过期 → {type,data,expire,remain}；过期 → None
    timers.due("acct-1")               # 该主体当前在列的清单（顺带清掉过期项并回调）
    timers.refresh("acct-1")           # 只做惰性清理
    timers.remove("acct-1", "slot:a")  # 主动删除，缺省**不**触发回调
"""
from __future__ import annotations

import copy
import json
from collections.abc import Mapping, MutableMapping
from typing import Any, Callable, Optional

from ..log import get_logger
from ..log.warn import WarnMixin

__all__ = ["TimerStorageError", "Timers"]

_LOG = get_logger("timers")

#: 「键不在存储里」的哨兵 —— 与「键在但值是 None/空串」区分开（后两者按无事件读）。
_MISSING = object()


class TimerStorageError(RuntimeError):
    """该主体的事件表取不出来（坏数据 / 非预期形态）—— fail-closed，不静默当空。"""


def _duration_of(value: Any, label: str) -> int:
    """校验时长：正整数秒（bool 不算整数）。"""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} 必须是整数秒，收到 {type(value).__name__}：{value!r}")
    if value <= 0:
        raise ValueError(f"{label} 必须是正整数秒，收到 {value!r}")
    return int(value)


def _type_key_of(type_key: Any) -> str:
    if not isinstance(type_key, str):
        raise TypeError(f"type_key 必须是字符串（类型标签由内容侧给），"
                        f"收到 {type(type_key).__name__}：{type_key!r}")
    if not type_key.strip():
        raise ValueError("type_key 必须是非空字符串（类型标签由内容侧给）")
    return type_key


def _event_key_of(key: Any) -> str:
    if not isinstance(key, str):
        raise TypeError(f"事件 key 必须是字符串，收到 {type(key).__name__}：{key!r}")
    if not key.strip():
        raise ValueError("事件 key 必须是非空字符串")
    return key


def _event_of(event_key: str, raw: Any) -> dict:
    """把存储里的一条事件校验成规范形状；坏数据 → `TimerStorageError`（点名 key）。"""
    if not isinstance(raw, Mapping):
        raise TimerStorageError(
            f"事件 {event_key!r} 不是映射：{type(raw).__name__}")
    type_key = raw.get("type")
    if not isinstance(type_key, str) or not type_key.strip():
        raise TimerStorageError(
            f"事件 {event_key!r} 的 type 不是非空字符串：{type_key!r}")
    expire = raw.get("expire")
    if isinstance(expire, bool) or not isinstance(expire, int):
        raise TimerStorageError(
            f"事件 {event_key!r} 的 expire 不是整数秒：{expire!r}")
    data = raw.get("data")
    if data is None:
        data = {}
    if not isinstance(data, Mapping):
        raise TimerStorageError(
            f"事件 {event_key!r} 的 data 不是映射：{type(data).__name__}")
    return {"type": type_key, "data": copy.deepcopy(dict(data)), "expire": int(expire)}


def _view(ev: Mapping, at: int, *, key: Optional[str] = None) -> dict:
    """读出口的视图：**新建**字典（改它不影响存储），`data` 是深拷贝。"""
    out: dict = {}
    if key is not None:
        out["key"] = key
    out["type"] = ev["type"]
    out["data"] = copy.deepcopy(ev["data"])
    out["expire"] = ev["expire"]
    out["remain"] = int(ev["expire"]) - int(at)
    return out


class Timers(WarnMixin):
    _warn_logger = _LOG                    # 未注入 logger 时的兜底（见 log.warn）
    """主体维度的倒计时事件表：类型注册 + 挂载刷新 + 懒过期 + 过期回调。

    * `store` —— 内容侧的存储面（`MutableMapping`）。引擎只做 `get / __setitem__ /
      __delitem__ / __contains__`，不认它的后端（事件域 / 存档域都行）。
    * `clock() -> int` —— 外部时钟（整数秒）。引擎不读系统时间、不建线程、不注册定时器。
    * `default_duration` —— 兜底时长（秒）：既没显式给 `duration`、类型也没声明时长时用它。
    * `key(owner) -> str` —— 存储键（缺省 = 主体本身）；分域 / 分前缀由内容侧定。
      它的产物在**每次调用时**校验（装配时不拿假主体试探 —— 那会把只认真实主体的键函数误判非法）。
    * `log` —— 传入 logger 就写它；None → 写门面 logger（`saintess_engine.timers`）。

    公开面只有六个方法：`register` / `set` / `get` / `due` / `remove` / `refresh`。
    """

    def __init__(self, store: MutableMapping, clock: Callable[[], int], *,
                 default_duration: int = 60,
                 key: Optional[Callable[[Any], str]] = None,
                 log=None) -> None:
        for name in ("get", "__setitem__", "__delitem__", "__contains__"):
            if not callable(getattr(store, name, None)):
                raise TypeError(
                    f"store 必须是可读写映射（缺 {name}）—— 拿不到注入面就 fail-closed，"
                    f"不要传 None/半个壳：{type(store).__name__}")
        if not callable(clock):
            raise TypeError("clock 必须是可调用（收无参、返回当前整数秒）")
        if key is not None and not callable(key):
            raise TypeError(f"key 必须是可调用 owner -> str，收到 {type(key).__name__}")
        self.store = store
        self.clock = clock
        self.default_duration = _duration_of(default_duration, "default_duration")
        self.key = key or (lambda owner: str(owner))
        self._logger = log
        self._types: dict = {}
        self._now(None)                       # 探一次：时钟给不出整数秒 → 装配即报错

    # ---------------------------------------------------------------- 类型注册
    def register(self, type_key: str, *, duration: Optional[int] = None,
                 on_expire: Optional[Callable[[Any, str, Any], None]] = None) -> None:
        """注册 / 覆盖一个倒计时类型。

        * `duration` —— 该类型的缺省时长（秒；None = 没有类型级时长，落回 `default_duration`）
        * `on_expire(owner, key, data) -> None` —— 该类型的实例被惰性清除时调用
          （`get` / `due` / `refresh` 三条路径都会走到它，读路径不得绕过）

        同 `type_key` 重复 `register` = 覆盖（时长与回调都换成新的）。
        """
        _type_key_of(type_key)
        dur = None if duration is None else _duration_of(duration, "duration")
        if on_expire is not None and not callable(on_expire):
            raise TypeError(f"on_expire 必须是可调用，收到 {type(on_expire).__name__}")
        self._types[type_key] = {"duration": dur, "on_expire": on_expire}

    @property
    def registered_types(self) -> tuple:
        """已注册的类型标签（注册序）—— 供内容侧自检「声明的类型都注册了吗」。"""
        return tuple(self._types)

    # ---------------------------------------------------------------- 写
    def set(self, owner: Any, key: str, type_key: str, *,
            data: Optional[Mapping] = None,
            duration: Optional[int] = None) -> int:
        """挂载 / 刷新一个倒计时实例，返回 `expire` 时间戳。

        * 同 `key` 重复 `set` = **顶替刷新**（该格只有一条，新 `expire`；不产生第二条）
        * 时长优先级：`duration` 参数 > 类型注册值 > `default_duration`
        * **未注册类型**：按规格取兜底时长，并记 WARNING 留痕（不是静默）
        * 写路径只动这一格：别的过期格留给读路径（懒计时）
        """
        _event_key_of(key)
        _type_key_of(type_key)
        if data is not None and not isinstance(data, Mapping):
            raise TypeError(f"data 必须是映射，收到 {type(data).__name__}")
        owner_key = self._key_of(owner)
        now = self._now(None)
        if duration is not None:
            dur = _duration_of(duration, "duration")
        else:
            spec = self._types.get(type_key)
            if spec is None:
                dur = self.default_duration
                self._warn("未注册的类型 %r：取兜底时长 %s 秒"
                           "（owner=%r key=%r）—— 类型级时长与过期回调都会缺省",
                           type_key, dur, owner, key)
            else:
                dur = spec["duration"] if spec["duration"] is not None else self.default_duration
        expire = now + dur
        events = self._load(owner_key)
        events[key] = {"type": type_key,
                       "data": copy.deepcopy(dict(data)) if data else {},
                       "expire": expire}
        self._persist(owner_key, events)
        return expire

    def remove(self, owner: Any, key: str, *, fire: bool = False) -> None:
        """主动删除一个实例（缺省 **不**触发 `on_expire` —— 主动结束不是过期）。

        `fire=True` 才触发该实例的回调（此时 `owner` / `key` / `data` 原样给回调）。
        `key` 不在表里 → 无事发生（一个字节都不写，也不触发任何回调）。
        """
        _event_key_of(key)
        if not isinstance(fire, bool):
            raise TypeError(f"fire 必须是布尔，收到 {type(fire).__name__}：{fire!r}")
        owner_key = self._key_of(owner)
        events = self._load(owner_key)
        ev = events.pop(key, None)
        if ev is None:
            return
        self._persist(owner_key, events)
        if fire:
            self._fire(owner, key, ev)

    # ---------------------------------------------------------------- 读
    def get(self, owner: Any, key: str, *, now: Optional[int] = None) -> Optional[dict]:
        """读单个实例：未过期 → `{type, data, expire, remain}`；过期 → 惰性清除并返回 None。

        **过期清除会触发 `on_expire`（至多一次）**。`now` 缺省取 `clock()`。
        """
        _event_key_of(key)
        owner_key = self._key_of(owner)
        events = self._load(owner_key)
        ev = events.get(key)
        if ev is None:
            return None
        at = self._now(now)
        if at >= ev["expire"]:
            del events[key]
            self._persist(owner_key, events)
            self._fire(owner, key, ev)
            return None
        return _view(ev, at)

    def due(self, owner: Any, *, now: Optional[int] = None) -> list:
        """该主体**当前在列**的实例清单 `[{key, type, data, expire, remain}, ...]`。

        同一次调用里顺带惰性清除该主体的过期项并触发 `on_expire`（读路径不得绕过）；
        顺序 = 事件在表里的存放序（稳定，`set` 顶替不改位置）。`now` 缺省取 `clock()`。
        """
        owner_key = self._key_of(owner)
        events = self._load(owner_key)
        at = self._now(now)
        self._purge(owner, owner_key, events, at)
        return [_view(ev, at, key=k) for k, ev in events.items()]

    def refresh(self, owner: Any, *, now: Optional[int] = None) -> None:
        """惰性全量刷新：扫该主体所有实例，过期的触发 `on_expire` + 物理清除。

        读路径不得绕过它 —— 任何「到点该发生的清理」都从这里（或 `get` / `due`）发生。
        `now` 缺省取 `clock()`。
        """
        owner_key = self._key_of(owner)
        events = self._load(owner_key)
        at = self._now(now)
        self._purge(owner, owner_key, events, at)

    # ---------------------------------------------------------------- 内部
    def _purge(self, owner: Any, owner_key: str, events: dict, at: int) -> None:
        """清掉过期项：**先落盘、再回调**（回调里再读同一 key 不会二次触发）。"""
        expired = [(k, ev) for k, ev in events.items() if at >= ev["expire"]]
        if not expired:
            return
        for k, _ev in expired:
            del events[k]
        self._persist(owner_key, events)
        for k, ev in expired:
            self._fire(owner, k, ev)

    def _now(self, now: Optional[int]) -> int:
        value = self.clock() if now is None else now
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"时钟必须给整数秒，收到 {type(value).__name__}：{value!r}")
        return int(value)

    def _key_of(self, owner: Any) -> str:
        owner_key = self.key(owner)
        if not isinstance(owner_key, str):
            raise TypeError(f"key(owner) 必须返回 str，"
                            f"收到 {type(owner_key).__name__}：{owner_key!r}")
        if not owner_key.strip():
            raise ValueError(f"key(owner) 返回空键（owner={owner!r}）—— 拒绝落到无名存储位上")
        return owner_key

    def _load(self, owner_key: str) -> dict:
        """按存储键读事件表。缺失 → 空表；在但取不出来 → fail-closed 抛错。"""
        raw = self.store.get(owner_key, _MISSING)
        if raw is _MISSING or raw is None or raw == "":
            return {}
        if isinstance(raw, (str, bytes, bytearray)):
            try:
                raw = json.loads(raw)
            except (ValueError, TypeError) as exc:
                raise TimerStorageError(
                    f"事件表取不出来（键 {owner_key!r}）：{exc}") from exc
        if not isinstance(raw, Mapping):
            raise TimerStorageError(
                f"事件表不是映射（键 {owner_key!r}）：{type(raw).__name__}")
        out: dict = {}
        for k, ev in raw.items():
            if not isinstance(k, str) or not k.strip():
                raise TimerStorageError(
                    f"事件表里有非字符串键（键 {owner_key!r}）：{k!r}")
            out[k] = _event_of(k, ev)
        return out

    def _persist(self, owner_key: str, events: dict) -> None:
        """写回事件表（可 JSON 往返的纯数据）；空表 → 删键（不留空壳）。"""
        if not events:
            if owner_key in self.store:
                del self.store[owner_key]
            return
        self.store[owner_key] = {
            k: {"type": ev["type"], "data": copy.deepcopy(ev["data"]),
                "expire": ev["expire"]}
            for k, ev in events.items()}

    def _fire(self, owner: Any, key: str, ev: Mapping) -> None:
        """触发某类型的过期回调。回调抛错 → 记 WARNING 留痕后继续（不阻断同批其余回调）。"""
        spec = self._types.get(ev["type"])
        cb = spec["on_expire"] if spec else None
        if cb is None:
            return
        try:
            cb(owner, key, copy.deepcopy(ev["data"]))
        except Exception as exc:                                        # noqa: BLE001
            self._warn("过期回调失败（type=%r key=%r owner=%r）：%s",
                       ev["type"], key, owner, exc)

