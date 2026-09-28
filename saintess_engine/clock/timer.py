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
from typing import Any, Callable, Optional

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


class LazyTimers(WarnMixin):
    _warn_logger = _LOG                    # 未注入 logger 时的兜底（见 log.warn）
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
        self.default_duration_sec = default_duration_sec
        self._types: dict[str, dict] = {}
        self._logger = logger

    # ------------------------------------------------------------ 类型注册
    def register(self, type_key: str, *, duration_sec: Optional[int] = None,
                 on_expire: Optional[Callable[[str, dict], None]] = None) -> None:
        """注册/覆盖一个计时事件类型。

        `on_expire(owner, data) -> None` 在该类型的实例过期被清理时调用
        （三条清理路径都会走到它）。异常被容忍（log + 跳过）。
        """
        if not type_key:
            raise ValueError("type_key 不得为空")
        self._types[type_key] = {"duration_sec": duration_sec, "on_expire": on_expire}

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
        dur = duration_sec
        if dur is None:
            dur = self._spec(type_key).get("duration_sec")
        if dur is None:
            dur = self.default_duration_sec
        expire = int(self._clock()) + max(1, int(dur))
        events = self._load(owner) or {}
        events[key] = {"type": type_key, "data": data or {}, "expire": expire}
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
        return {"type": ev.get("type"), "data": ev.get("data", {}),
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
            if data_match and not all(ev.get("data", {}).get(dk) == dv
                                      for dk, dv in data_match.items()):
                continue
            out.append({"key": k, "type": ev.get("type"), "data": ev.get("data", {}),
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
            cb(owner, ev.get("data", {}) or {})
        except Exception:
            self._warn("on_expire 回调失败（type=%r）", ev.get("type"))

