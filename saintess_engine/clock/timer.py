# -*- coding: utf-8 -*-
"""懒计时器骨架 —— 「限时存在 / 限时有效 / 到时触发」的统一机制。

模式（不跑后台定时器）
----------------------
* **懒计时**：不常驻 timer；读的时候校验过期，任何一次「刷新」物理清理
* **一致性铁律**：显示出口与查找出口**都走同一个读方法** → 过期即不可见，
  不存在「过期了还看得见」的窗口
* **回调不绕路**：`get` / `items` / `refresh` 三条删除路径**都必须**触发
  `on_expire`，否则带副作用的清理（如作废会话、平移结算数据）会被读路径绕过

存储由使用方注入
----------------
三个回调决定「存哪里、什么 key」，框架不假设任何存储形态：

    load(owner) -> dict          读该主体的全部计时事件（无 → 空 dict）
    save(owner, events) -> None  写回
    remove(owner) -> None        删除该主体的整条记录（事件清空时调用）

典型用法::

    timers = LazyTimers(load=..., save=..., remove=...)
    timers.register("encounter", duration_sec=3600, on_expire=clear_session)
    timers.set(owner, "spot:old_trader", "encounter", data={"map": "oak"})
    ev = timers.get(owner, "spot:old_trader")      # 过期 → None（并已触发回调）
    timers.refresh(owner)                           # 全量惰性清理
"""
from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any, Callable, Optional

from .._validators import int_of
from ..log import get_logger
from ..log.warn import WarnMixin

__all__ = ["LazyTimers", "TimerStorageError"]

_LOG = get_logger("clock")


class TimerStorageError(RuntimeError):
    """事件表里某条记录取不出可用的过期时间 —— fail-closed，不静默当已过期。

    为什么要 fail-closed：`expire` 缺失/非整数时，原写法 `.get("expire", 0)` 会让
    `now >= 0` **恒真** ⇒ 一行坏数据被当成「已过期」静默物理删除并触发 `on_expire`
    （作废会话、平移结算数据这类副作用会在无人察觉时发生）；而 `expire=None` 则抛
    裸 `TypeError`、事件卡在表里出不来。两种都不对。存的是坏数据就要**点名是谁**。

    **本类是该形状的唯一异常类型**（跨层单源）：`ext_life.timers.Timers` 是同一形状的
    另一层实现，它**导入本类**而不另立一个同名类 —— 两层各自的 `except` 才能互相兜住。
    同名不同类（`is` 为 False）会让人写 `except TimerStorageError` 时漏捕另一层的错，
    而两层的触发条件都是「存的是坏数据」⇒ 漏捕 = 坏数据一路冒到顶层、零诊断。
    """


def _expire_of(ev: dict, key: Any, owner: Any) -> int:
    """取一条事件的过期时间戳（整数秒）。

    缺键 / 非整数 / `bool` ⇒ 抛 `TimerStorageError`，文案点名 `owner` 与 `key`。
    取值口径与 `_validators.clock_now` 同源（`bool` 不算整数）。
    """
    if not isinstance(ev, dict):
        raise TimerStorageError(
            f"事件记录不是映射（owner={owner!r} key={key!r}）：{type(ev).__name__}")
    if "expire" not in ev:
        raise TimerStorageError(f"事件记录缺 expire 键（owner={owner!r} key={key!r}）")
    value = ev["expire"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TimerStorageError(
            f"expire 必须是整数秒（owner={owner!r} key={key!r}）："
            f"{type(value).__name__}：{value!r}")
    return int(value)


def _data_of(ev: dict, key: Any, owner: Any) -> dict:
    """取一条事件的 `data`：必须是映射；缺键 / `None` 归一为 `{}`。

    为什么要 fail-closed：`data` 是本表里唯一**内容侧完全自持**的载荷（`type`/`expire`
    都被本模块校验过，只有它一路裸奔）。原实现两处缺口：

    ① `set()` 的 `data or {}` —— 任何非映射（`'坏字符串'` / `123` / `['x']`）都能落盘，
       零报错；同一形状的另一份实现（`ext_life.timers.Timers.set`）当场 TypeError。
    ② `items(data_match=…)` 的 `ev.get("data", {}).get(dk)` —— 直接对存储给的东西
       调 `.get`，非映射存储一进来就是 `AttributeError: 'str' object has no
       attribute 'get'`，**报在引擎内部**、不点名 owner/key，玩家侧只看到一次无来由的
       崩溃（实测复现，键名与归属都丢了）。

    与 `_expire_of` 同口径：坏数据点名 `owner` 与 `key` 后抛 `TimerStorageError`，
    不静默当空载荷（静默会把「数据坏了」伪装成「这条事件没有额外条件」）。
    `Mapping` 而非 `dict`：与 `ext_life.timers._event_of` 取同一集合。
    """
    if not isinstance(ev, dict):
        raise TimerStorageError(
            f"事件记录不是映射（owner={owner!r} key={key!r}）：{type(ev).__name__}")
    data = ev.get("data")
    if data is None:
        return {}
    if not isinstance(data, Mapping):
        raise TimerStorageError(
            f"事件的 data 不是映射（owner={owner!r} key={key!r}）："
            f"{type(data).__name__}：{data!r}")
    return dict(data)


def _type_key_of(type_key: Any) -> str:
    """校验类型标签：非空字符串（类型标签由内容侧给）。

    为什么要 fail-closed：`LazyTimers` 与 `ext_life.timers.Timers` 是**同一形状的两份实现**，
    而只有后者校验类型标签 —— 原来这里直接 `self._types.get(type_key)` 放行，于是
    `set(owner, key, 123)` 会把 `{"type": 123}` **原样落盘**、只留一条 WARNING。
    拼错类型名的后果在到期时才现形：`_fire_expire` 查不到回调 ⇒ 事件被物理删除、**零回调**
    （挂在该类型上的清理副作用无声蒸发）。两份实现必须是同一份判据。
    """
    if not isinstance(type_key, str):
        raise TypeError(f"type_key 必须是字符串（类型标签由内容侧给），"
                        f"收到 {type(type_key).__name__}：{type_key!r}")
    if not type_key.strip():
        raise ValueError("type_key 必须是非空字符串（类型标签由内容侧给）")
    return type_key


def _event_key_of(key: Any) -> str:
    """校验事件 key：非空字符串。

    空串与 `7` 原本都能落盘并读得回来（`get("")` 命中），但内容侧按名字取事件时
    空串与「没有名字」的东西同形，`7` 与字符串 key 混在一张表里 —— 同一形状的另一份实现
    （`ext_life.timers`）早就 fail-closed 拒绝这两种，收口到同一口径。
    """
    if not isinstance(key, str):
        raise TypeError(f"事件 key 必须是字符串，收到 {type(key).__name__}：{key!r}")
    if not key.strip():
        raise ValueError("事件 key 必须是非空字符串")
    return key


def _duration_of(value: Any, label: str) -> int:
    """校验时长：正整数秒（`bool` 不算整数）。

    为什么要 fail-closed：原写法 `max(1, int(dur))` 会把**负时长 / `bool` / `0` 一律压成 1 秒**
    （`duration_sec=-500` -> 过期戳只比现在大 1 秒），把「配置笔误（`-1` 想写永久）」变成
    「1 秒后静默过期并触发 `on_expire`」—— 行为与意图完全相反且不报错；`"600"` 这种字符串
    也会被 `int()` 悄悄收下。存进去的是**坏时长**就要点名是谁。
    取值口径与 `ext_life.timers._duration_of` 同源（两处必须是同一份判据）。
    """
    return int_of(value, label, minimum=1)


class LazyTimers(WarnMixin):
    """主体维度的懒计时器。

    参数
    ----
    load / save / remove: 存储三件套（见模块 docstring）。`owner` 是**归属主体标识**——
                          可以是任意可哈希对象（用户 id / 公会 id / `(群, 用户)` 元组…），
                          框架原样透传给三个回调与 `on_expire`，不做任何解释。
    clock:                取当前时间戳的函数（默认 `time.time` 取整）——
                          **可注入**，测试可控时间。
    default_duration_sec: 未显式给时长、且类型也没注册时长时的兜底（默认 60）。
    logger:               传入 logger；None → 用门面 logger（`<prefix>.clock`）。
    """
    _warn_logger = _LOG                    # 未注入 logger 时的兜底（见 log.warn）
                                        # 必须在 docstring 之**后**：放在类首行会把 docstring 挤成一句哑字面量（`LazyTimers.__doc__ is None`）。

    def __init__(self, *, load: Callable[[str], dict],
                 save: Callable[[str, dict], None],
                 remove: Callable[[str], None],
                 clock: Optional[Callable[[], float]] = None,
                 default_duration_sec: int = 60,
                 logger=None) -> None:
        self._load = load
        self._save = save
        self._remove = remove
        self._clock = clock or (lambda: int(time.time()))
        self.default_duration_sec = _duration_of(default_duration_sec,
                                                   "default_duration_sec")
        self._types: dict[str, dict] = {}
        self._logger = logger

    # ------------------------------------------------------------ 类型注册
    def register(self, type_key: str, *, duration_sec: Optional[int] = None,
                 on_expire: Optional[Callable[[str, dict], None]] = None) -> None:
        """注册/覆盖一个计时事件类型。

        `on_expire(owner, data) -> None` 在该类型的实例过期被清理时调用
        （三条清理路径都会走到它）。异常被容忍（log + 跳过）。
        """
        _type_key_of(type_key)
        dur = None if duration_sec is None else _duration_of(
            duration_sec, f"duration_sec（类型 {type_key!r}）")
        self._types[type_key] = {"duration_sec": dur, "on_expire": on_expire}

    @property
    def registered_types(self) -> tuple:
        return tuple(self._types)

    def _spec(self, type_key: str) -> dict:
        return self._types.get(type_key, {})

    # ------------------------------------------------------------ 写
    def set(self, owner: Any, key: str, type_key: str, *,
            data: Optional[dict] = None,
            duration_sec: Optional[int] = None) -> int:
        """挂载/刷新一个计时事件，返回过期时间戳。

        * 同 `key` 重复挂载 = 顶替刷新（新过期时间）
        * 时长优先级：`duration_sec` 参数 > 类型注册值 > `default_duration_sec`
        """
        _event_key_of(key)
        _type_key_of(type_key)
        if data is not None and not isinstance(data, Mapping):
            raise TypeError(f"data 必须是映射，收到 {type(data).__name__}：{data!r}")
        spec = self._types.get(type_key)
        if spec is None:
            # 未注册类型：按 `ext_life.timers` 同一口径取兜底时长并**留痕**（不是静默）。
            # 静默的后果实测得出：类型名拼错 -> 到期时 `on_expire` 查不到回调 -> 事件被
            # 物理删除、**零回调**，挂在该类型上的清理副作用（作废会话一类）无声蒸发。
            self._warn("未注册的类型 %r：取兜底时长 %s 秒"
                       "（owner=%r key=%r）—— 类型级时长与过期回调都会缺省",
                       type_key, self.default_duration_sec, owner, key)
            spec = {}
        dur = duration_sec
        if dur is not None:
            dur = _duration_of(dur, f"duration_sec（owner={owner!r} key={key!r}）")
        elif spec.get("duration_sec") is not None:
            dur = spec["duration_sec"]
        else:
            dur = self.default_duration_sec
        expire = int(self._clock()) + dur
        events = self._load(owner) or {}
        events[key] = {"type": type_key,
                       "data": dict(data) if data is not None else {},
                       "expire": expire}
        self._save(owner, events)
        return expire

    def remove(self, owner: Any, key: str) -> bool:
        """主动删除一个事件（返回是否删掉了）。**不触发** on_expire（主动结束，非过期）。"""
        events = self._load(owner) or {}
        if key not in events:
            return False
        events.pop(key, None)
        self._persist(owner, events)
        return True

    # ------------------------------------------------------------ 读
    def get(self, owner: Any, key: str) -> Optional[dict]:
        """读单个事件：未过期 → {type,data,expire,remain}；过期 → 惰性清除并返回 None。

        过期清除**会触发** on_expire。
        """
        events = self._load(owner) or {}
        ev = events.get(key)
        if not ev:
            return None
        now = int(self._clock())
        if now >= _expire_of(ev, key, owner):
            events.pop(key, None)
            self._persist(owner, events)
            self._fire_expire(owner, ev)
            return None
        expire = _expire_of(ev, key, owner)
        return {"type": ev.get("type"), "data": _data_of(ev, key, owner),
                "expire": expire, "remain": expire - now}

    def items(self, owner: Any, *, type_key: Optional[str] = None,
              data_match: Optional[dict] = None) -> list:
        """列出未过期事件（可按时长键/数据子集过滤），顺带惰性清除过期项。

        `data_match`：`data` 子集匹配（如 `{"map": "oak"}` → 只留该地图的）。
        返回 `[{key,type,data,expire,remain}, ...]`。过期清除**会触发** on_expire。
        """
        events = self._load(owner) or {}
        now = int(self._clock())
        expired = {k: ev for k, ev in events.items()
                    if now >= _expire_of(ev, k, owner)}
        for k in expired:
            events.pop(k, None)
        if expired:
            self._persist(owner, events)
            for _k, ev in expired.items():
                self._fire_expire(owner, ev)
        out = []
        for k, ev in events.items():
            if type_key is not None and ev.get("type") != type_key:
                continue
            if data_match and not all(_data_of(ev, k, owner).get(dk) == dv
                                      for dk, dv in data_match.items()):
                continue
            out.append({"key": k, "type": ev.get("type"), "data": _data_of(ev, k, owner),
                        "expire": _expire_of(ev, k, owner),
                        "remain": _expire_of(ev, k, owner) - now})
        return out

    def refresh(self, owner: Any) -> int:
        """全量惰性清理：过期项执行 on_expire + 物理删除。返回清理条数。"""
        events = self._load(owner) or {}
        now = int(self._clock())
        expired = {k: ev for k, ev in events.items()
                    if now >= _expire_of(ev, k, owner)}
        if not expired:
            return 0
        for k in expired:
            events.pop(k, None)
        self._persist(owner, events)
        for _k, ev in expired.items():
            self._fire_expire(owner, ev)
        return len(expired)

    # ------------------------------------------------------------ 内部
    def _persist(self, owner: Any, events: dict) -> None:
        """事件清空 → 删整条记录；否则写回。"""
        if events:
            self._save(owner, events)
        else:
            self._remove(owner)

    def _fire_expire(self, owner: Any, ev: dict) -> None:
        cb = self._spec(ev.get("type")).get("on_expire")
        if not cb:
            return
        try:
            cb(owner, _data_of(ev, ev.get("type"), owner))
        except Exception:
            self._warn("on_expire 回调失败（type=%r）", ev.get("type"))

