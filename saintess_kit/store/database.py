# -*- coding: utf-8 -*-
"""连接 / 锁 / 事务 / 建表注册 —— 存储骨架的核心。

设计取舍（都来自实测教训，不是偏好）
------------------------------------
* **RLock 而非 Lock**：读档可能触发惰性写（如惰性升级），同线程内会重入
  `session()`/`atomic()`；`threading.Lock` 会死锁。游戏侧历史坑 v105 P1(M01#11)。
* **锁是进程内的**：跨进程并发交给 SQLite 文件锁；需要「拿写锁」的场合用
  `atomic()`（它发 `BEGIN IMMEDIATE`）。
* **不预设路径**：`path` 由使用方传入。框架不读环境变量、不推导宿主目录。
* **建表顺序 = 注册顺序**：表间若有外键/依赖，注册顺序即执行顺序。
* **`init()` 幂等**：schema 一律用 `CREATE TABLE IF NOT EXISTS` 写（使用方责任），
  迁移器自身也是「缺才补」。
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from typing import Callable, Iterator, Optional

__all__ = ["Database"]


class Database:
    """一个 SQLite 库的连接/锁/事务/建表骨架。

    参数
    ----
    path:      数据库文件路径（`:memory:` 亦可）。使用方负责决定它放哪。
    timeout:   SQLite 连接超时（秒）—— 等锁时长。
    row_factory: 行工厂，默认 `sqlite3.Row`（按列名取值，`dict(row)` 即字典）。
    """

    def __init__(self, path: str, *, timeout: float = 10.0,
                 row_factory: Optional[Callable] = sqlite3.Row) -> None:
        self.path = path
        self.timeout = timeout
        self.row_factory = row_factory
        self._lock = threading.RLock()
        self._schemas: list[tuple[str, str]] = []
        self._migrations: list[Callable[[sqlite3.Connection], None]] = []

    # ---------------------------------------------------------------- 连接
    @property
    def lock(self) -> threading.RLock:
        """进程内重入锁。使用方直接 `with db.lock:` 做自己的临界区。"""
        return self._lock

    def connect(self) -> sqlite3.Connection:
        """开一条新连接（调用方负责关闭；一般用 session()/readonly()/atomic()）。"""
        conn = sqlite3.connect(self.path, timeout=self.timeout)
        if self.row_factory is not None:
            conn.row_factory = self.row_factory
        return conn

    # ---------------------------------------------------------------- 事务
    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        """临界区 + 单连接 + **自动提交**（异常回滚），退出必关连接。

        适合「一组读」或「一组写」。原代码里
        `with _lock: conn = _connect(); try: ...; conn.commit(); finally: conn.close()`
        的等价形态。
        """
        with self._lock:
            conn = self.connect()
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            finally:
                conn.close()

    @contextmanager
    def readonly(self) -> Iterator[sqlite3.Connection]:
        """临界区 + 单连接 + **不提交**，退出必关连接。

        与原「只 close（丢弃未提交写）」语义一致 —— 迁移期逐处对照原代码选用，
        避免把「本来会被丢弃的意外写」变成真写入。
        """
        with self._lock:
            conn = self.connect()
            try:
                yield conn
            finally:
                conn.close()

    @contextmanager
    def atomic(self) -> Iterator[sqlite3.Connection]:
        """临界区 + 单连接 + 单事务（`BEGIN IMMEDIATE` 拿写锁）—— **跨连接原子性**。

        与 `session()` 的差别：显式 `BEGIN IMMEDIATE`，在多进程/多连接并发时
        立刻拿写锁，保证「读-改-写」不被插队。代价是并发下更易失败重试，
        故只在需要原子写的地方用。
        """
        with self._lock:
            conn = self.connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            finally:
                conn.close()

    # ------------------------------------------------------------ 建表与迁移
    def register_schema(self, name: str, sql: str) -> None:
        """注册一段建表 SQL（`init()` 按注册顺序 `executescript`）。

        `name` 只是标识（便于排查/覆盖），同名**覆盖**后注册者 —— 测试重置可用。
        """
        self._schemas = [(n, s) for (n, s) in self._schemas if n != name]
        self._schemas.append((name, sql))

    def register_migration(self, fn: Callable[[sqlite3.Connection], None]) -> None:
        """注册一个迁移器（`init()` 在建表之后依次调用，传入同一连接）。

        惯例：迁移器应**幂等**且「缺才补」（见 `migrate.ensure_columns`）。
        """
        self._migrations.append(fn)

    @property
    def schema_names(self) -> list[str]:
        """已注册 schema 的名字（按执行顺序）—— 供诊断/测试断言。"""
        return [n for n, _ in self._schemas]

    def init(self) -> None:
        """建表 + 迁移（幂等；整体在一个锁内、一次提交）。

        顺序：注册序 executescript → 迁移器 → commit。
        """
        with self._lock:
            conn = self.connect()
            try:
                for _name, sql in self._schemas:
                    conn.executescript(sql)
                for fn in self._migrations:
                    fn(conn)
                conn.commit()
            finally:
                conn.close()
