# -*- coding: utf-8 -*-
"""计时生产形状 —— `Job`（一次计时作业）+ `Jobs`（每人 1..N 槽的作业队列）。

**为什么有它**：真实项目里「开一轮等待、到点、收取」这件事长这样 —— 状态被塞进
事件域，时长公式写在命令层，结算既可能在回调里发生、也可能在下次读状态时补做，
而「读到残留但没结算」的数据一丢就是奖励丢失。把「产出的是什么」拿掉之后，
剩下的只有三件通用的事：**槽位**（同时能挂几条）、**到点判据**（谁按哪个时钟算）、
**收取**（到点才出队，未到点原样不动）。

**用法**::

    from saintess_engine.produce import AlreadyBusy, Job, Jobs

    c = Jobs(store, clock, max_slots=1, key=lambda o: f"jobs:{o}")
    c.begin("1001", Job(kind="k1", started_at=0, ends_at=100))   # -> Job（槽满 → AlreadyBusy）
    c.current("1001")        # 最早到点的那条（无 → None）
    c.all_of("1001")         # 该持有者的全部作业（保序）
    c.settle("1001")         # 到点 → 返回并清槽；未到点 → None 且**原样不动**
    c.due()                  # [(owner, job)] 到点清单（供 tick 批量结算，不清槽）
    c.clear("1001")          # 清空该持有者的全部作业

**绑定由内容给**（引擎不猜）::

    * `store` —— 内容侧的存储面（`MutableMapping`：事件域 / 存档域都行），
      引擎只做 `get / __setitem__ / __delitem__`，不认它的后端。
    * `key(owner) -> str` —— 存储键（缺省 = 持有者本身）；分域/分前缀由内容侧定。
    * `clock() -> int` —— 外部时钟（秒）。引擎不读系统时间、不建线程、不注册定时器：
      「到点」= `ends_at <= now`，`now` 由调用方给或由 `clock` 现取。
    * `kind` —— 作业种类标签（内容侧的词汇）。引擎只把它当字符串比较，不做任何映射。

有意不做的事
------------
* **不做时长公式**：`ends_at` 由调用方算（等级、系数、随机、保底都不进引擎）。
* **不做材料消耗 / 产出规则**：开一轮扣什么、到点给什么，是内容侧的事。
* **不做定时器 / 线程**：到点靠外部 `clock` 判定，引擎不持有回调、不 sleep、不起任务。
* **不做自动清理**：到点但未收取的作业**留在队列里**（`due()` 会一直点名它）——
  这样「到点未结算」不会因为一次读状态就消失，结算方拿得到原始载荷。
* **不做槽位抢占**：槽满 / 同类在跑时 `begin` 抛 `AlreadyBusy`，**绝不静默顶掉旧作业**。

存储布局（引擎**不解析、不裁剪、不兼容旧格式**）
------------------------------------------------
* 键值 —— `key(owner)`；一份作业表 = `[job.to_dict(), ...]`。
* 缺失键 —— 读成「没有作业」（空表）。
* 键在、值取不出作业表 —— **fail-closed**：抛 `ProduceStorageError`，绝不静默当成空
  （静默清空 = 在途作业与待收奖励一起蒸发）。
"""
from __future__ import annotations

import copy
import json
from collections.abc import Mapping, MutableMapping
from typing import Callable, Optional

from .._validators import clock_now, owner_key

__all__ = ["AlreadyBusy", "Job", "Jobs", "ProduceStorageError"]

#: 「键不在存储里」的哨兵 —— 与「键在但值是 None」区分开（后者是坏数据，要报错）。
_MISSING = object()


class ProduceStorageError(RuntimeError):
    """存储面里这份作业表取不出来（坏数据 / 非预期形态）—— fail-closed，不静默清空。"""


class AlreadyBusy(RuntimeError):
    """槽已满、或该持有者的这一类作业已在跑 —— **绝不静默顶掉**。"""


class Job:
    """一次计时作业：`kind` + 起止时刻 + 载荷。**可变**（`begin` 会回填 `started_at`）。

    * `kind` —— 种类标签（内容侧词汇；引擎只做字符串比较）
    * `started_at` / `ends_at` —— 时刻（秒，整数；同一根外部时钟）
    * `payload` —— 载荷（映射；结算方要的数据都放这里，引擎不看内容）。
      **存副本**：队列与调用方手里的对象不共享内部结构（谁改谁都不串）。
    """

    __slots__ = ("kind", "started_at", "ends_at", "payload")

    def __init__(self, kind: str, started_at: int, ends_at: int,
                 payload: Optional[Mapping] = None) -> None:
        self.kind = kind
        self.started_at = int(started_at)
        self.ends_at = int(ends_at)
        self.payload = copy.deepcopy(dict(payload or {}))

    # ---------------------------------------------------------------- 到点
    def done(self, now: int) -> bool:
        """到点判据：`now >= ends_at`（`now` = 外部时钟给的当前时刻）。"""
        return int(now) >= self.ends_at

    def residual(self, now: int) -> int:
        """剩余秒数；已到点 → 0（不出现负数）。"""
        return max(0, self.ends_at - int(now))

    # ---------------------------------------------------------------- 往返
    def to_dict(self) -> dict:
        return {"kind": self.kind, "started_at": self.started_at,
                "ends_at": self.ends_at, "payload": copy.deepcopy(self.payload)}

    @classmethod
    def from_dict(cls, data: Mapping) -> "Job":
        """从 `to_dict()` 的形状还原；缺 `started_at` → 当作 0。"""
        if not isinstance(data, Mapping):
            raise ProduceStorageError(f"作业表条目不是映射：{type(data).__name__}")
        payload = data.get("payload")
        return cls(kind=data.get("kind"), started_at=data.get("started_at") or 0,
                   ends_at=data.get("ends_at"), payload=payload or {})

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return (f"Job(kind={self.kind!r}, started_at={self.started_at}, "
                f"ends_at={self.ends_at}, payload_keys={sorted(self.payload)})")


class Jobs:
    """每个持有者 1..N 个槽的作业队列。存储与时钟都由内容侧注入。

    * `max_slots` —— 每个持有者的槽数上限（缺省 1）。槽在**收取**时释放：到点但未收取
      的作业仍占着槽（`due()` 一直在点名它），这是「到点未结算不丢」的代价与保证。
    * 同一持有者的同一 `kind` **同时只允许一条**（已在跑 → `AlreadyBusy`）。
    """

    def __init__(self, store: MutableMapping, clock: Callable[[], int], *,
                 max_slots: int = 1,
                 key: Optional[Callable[[str], str]] = None) -> None:
        if int(max_slots) < 1:
            raise ValueError(f"max_slots 至少为 1，收到 {max_slots!r}")
        self.store = store
        self.clock = clock
        self.max_slots = int(max_slots)
        self.key = key or (lambda owner: str(owner))
        self._validate()

    def _validate(self) -> None:
        """装配即校验：拿不到注入面 / 注入面不合规 → **立刻报错**（不拖到第一次调用）。"""
        for name in ("get", "__setitem__", "__delitem__", "__contains__"):
            if not callable(getattr(self.store, name, None)):
                raise TypeError(
                    f"store 必须是可读写映射（缺 {name}）—— 拿不到注入面就 fail-closed，"
                    f"不要传 None/半个壳：{type(self.store).__name__}")
        if not callable(self.clock):
            raise TypeError("clock 必须是可调用（收无参、返回当前秒）")
        clock_now(self.clock, None)          # 探一次：时钟取不到整数 → 当场报错
        self._key_of("\x00probe")            # 探一次：键不合规 → 当场报错

    # ---------------------------------------------------------------- 读
    def current(self, owner: str) -> Optional[Job]:
        """最早到点的**未收取**作业（并列 → 先开始的在前；无 → None）。

        到点但未收取的作业**仍算在列**（结算方靠它拿到原始载荷）。
        """
        jobs = self._load(owner)
        if not jobs:
            return None
        return min(jobs, key=lambda j: (j.ends_at, j.started_at))

    def all_of(self, owner: str) -> list:
        """该持有者的全部未收取作业（保序：先是先开始的）。"""
        return self._load(owner)

    def due(self, *, now: Optional[int] = None) -> list:
        """到点清单 `[(owner, job), ...]`（**不清槽**，供 tick 批量结算）。

        顺序稳定：持有者键升序，同一持有者内按存放顺序。
        """
        at = clock_now(self.clock, now)
        out = []
        for owner_key in sorted(self._keys()):
            jobs = self._load_by_key(owner_key)
            for job in jobs:
                if job.done(at):
                    out.append((owner_key, job))
        return out

    # ---------------------------------------------------------------- 写
    def begin(self, owner: str, job: Job) -> Job:
        """开一条作业；返回**同一个** `Job` 对象（`started_at` 已回填为当前时刻）。

        * 该持有者的槽已满 → `AlreadyBusy`
        * 该持有者的同一 `kind` 已在跑 → `AlreadyBusy`
        * `ends_at <= started_at` → `ValueError`（不做「零时长也算一轮」的静默降级）

        抛 `AlreadyBusy` 时**一个字节都不写**（校验全过才落盘）。
        """
        if not isinstance(job, Job):
            raise TypeError(f"job 必须是 Job，收到 {type(job).__name__}")
        if not isinstance(job.kind, str) or not job.kind:
            raise ValueError("job.kind 必须是非空字符串（种类标签由内容侧给）")
        if not isinstance(job.payload, dict):
            raise TypeError(f"job.payload 必须是映射，收到 {type(job.payload).__name__}")
        self._key_of(owner)
        at = clock_now(self.clock, None)
        if job.ends_at <= at:
            raise ValueError(f"ends_at({job.ends_at}) 必须晚于当前时刻({at})")
        jobs = self._load(owner)
        if len(jobs) >= self.max_slots:
            raise AlreadyBusy(
                f"槽已满：owner={self._key_of(owner)!r} 已有 {len(jobs)} 条作业"
                f"（max_slots={self.max_slots}），先收取再开新的")
        running = [j.kind for j in jobs]
        if job.kind in running:
            raise AlreadyBusy(
                f"该类作业已在跑：owner={self._key_of(owner)!r} kind={job.kind!r}"
                f"（进行中：{running}）")
        job.started_at = at
        jobs.append(job)
        self._save(owner, jobs)
        return job

    def settle(self, owner: str, *, now: Optional[int] = None) -> Optional[Job]:
        """到点 → 取走**最早到点**的那条并清掉它；未到点 → None 且**原样不动**。

        只动这一条：同一持有者的其它作业（未到点 / 别类）留在队列里。
        """
        at = clock_now(self.clock, now)
        jobs = self._load(owner)
        hit = next((j for j in sorted(jobs, key=lambda j: (j.ends_at, j.started_at))
                    if j.done(at)), None)
        if hit is None:
            return None
        rest = [j for j in jobs if j is not hit]
        self._save(owner, rest)
        return hit

    def clear(self, owner: str) -> None:
        """清空该持有者的全部作业（键不在 → 无事发生）。"""
        owner_key = self._key_of(owner)
        if owner_key in self.store:
            del self.store[owner_key]

    # ---------------------------------------------------------------- 内部
    def _key_of(self, owner: str) -> str:
        """本形状的取键口径：**先 `str(owner)` 再问 `key`**（守卫单源 = `_validators.owner_key`）。"""
        return owner_key(self.key, str(owner))

    def _keys(self) -> list:
        for name in ("keys", "__iter__"):
            if callable(getattr(self.store, name, None)):
                return list(self.store.keys() if name == "keys" else iter(self.store))
        raise TypeError(f"store 不支持枚举（缺 keys/__iter__）：{type(self.store).__name__}")

    def _load(self, owner: str) -> list:
        return self._load_by_key(self._key_of(owner))

    def _load_by_key(self, owner_key: str) -> list:
        """按存储键读作业表。缺失 → 空表；在但坏 → fail-closed 抛错。"""
        raw = self.store.get(owner_key, _MISSING)
        if raw is _MISSING or raw is None or raw == "":
            return []
        if isinstance(raw, (list, tuple)):
            data = list(raw)
        elif isinstance(raw, (str, bytes, bytearray)):
            try:
                data = json.loads(raw)
            except (ValueError, TypeError) as exc:
                raise ProduceStorageError(
                    f"作业表取不出来（键 {owner_key!r}）：{exc}") from exc
        else:
            raise ProduceStorageError(
                f"作业表形态不对（键 {owner_key!r}）：{type(raw).__name__}")
        if not isinstance(data, (list, tuple)):
            raise ProduceStorageError(
                f"作业表不是列表（键 {owner_key!r}）：{type(data).__name__}")
        return [item if isinstance(item, Job) else Job.from_dict(item) for item in data]

    def _save(self, owner: str, jobs: list) -> None:
        """写回作业表；空表 → 删键（不留空壳）。"""
        owner_key = self._key_of(owner)
        if not jobs:
            if owner_key in self.store:
                del self.store[owner_key]
            return
        self.store[owner_key] = [j.to_dict() for j in jobs]
