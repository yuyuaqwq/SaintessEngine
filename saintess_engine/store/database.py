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

import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Callable, Iterator, Optional

__all__ = ["Database"]


def _tune_file_conn(conn: sqlite3.Connection, timeout: float) -> None:
    """文件库连接调优：只做**语义无关**的性能设置。

    ★ 2026-09-18（实测驱动）：包内持久化层是「每次操作开连接 → commit → 关连接」
    的写法（如 `content/persistence/inventory.py`），在 SQLite 默认
    `journal_mode=DELETE` + `synchronous=FULL` 下**每次 commit 都要 fsync 落盘**：
    单文件门禁实测 18610 次 commit 耗 128.5s（6.9ms/次，占该测试总耗时 66%），
    25998 次 connect 又占 14.9s。

    `WAL` 让写事务顺序追加到 `-wal` 文件（checkpoint 时才回写主库）⇒ commit 不再
    逐次 fsync。语义仍是 ACID（崩溃后可恢复），只换日志模式；对「短连接、读多写少」
    的既有用法没有可观察行为差异（`-wal`/`-shm` 是 SQLite 自管文件）。

    `journal_mode` 是**持久属性**（写进库文件头，后续连接自动继承），重复设置无害。
    只读挂载 / 网络盘等不支持 WAL 的场合静默回退默认行为，不阻断初始化。
    """
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=%d" % max(0, int(timeout * 1000)))
        # ★ 2026-09-18 二次调优（实测驱动）：6 个门禁并发时 **CPU 只占 19%、
        #   磁盘队列 1~6（饱和）** ⇒ 瓶颈在磁盘 IO 而非 CPU。三条都不动耐久性：
        #   · wal_autocheckpoint 1000 → 4000 页（≈4MB → 16MB）：checkpoint 要回写主库
        #     并 fsync，降低频率直接砍掉一块磁盘压力（留有限值，不像 0 那样让 WAL 无限涨）。
        #   · temp_store=MEMORY：临时表 / 排序不进磁盘。
        #   · cache_size=-8000（8MB）：减少重复页读。
        conn.execute("PRAGMA wal_autocheckpoint=4000")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-8000")
        # ★ 同步模式开关（**默认不动 = FULL**，耐久性最高）。
        #   测试跑器可设 `GWEN_SQLITE_SYNC=NORMAL`：WAL 下只在 checkpoint 时 fsync，
        #   commit 不再逐次落盘 —— 崩溃极端情况下可能丢最近若干事务（库不会损坏），
        #   对一次性的测试库零风险；真实运行默认保持 FULL。
        _sync = os.environ.get("GWEN_SQLITE_SYNC", "").strip().upper()
        if _sync in ("FULL", "NORMAL", "OFF"):
            conn.execute("PRAGMA synchronous=%s" % _sync)
    except sqlite3.Error:
        pass


class Database:
    """一个 SQLite 库的连接/锁/事务/建表骨架。

    参数
    ----
    path:      数据库文件路径（`:memory:` 亦可——同一实例的连接共享同一个内存库）。
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
        # `:memory:` 支持（2026-09-18 修）：此前每次 connect() 都是**独立空库** ——
        # init()（建表）的连接一关，表就没了（declare / 会话全断，与文档承诺矛盾）。
        # 现在：所有连接走同一条共享缓存 URI（同一内存库）+ 保活连接 —— 内存库在
        # 最后一条连接关闭时销毁，没有 keeper，init() 一返回库就没了。
        self._mem_uri: Optional[str] = None
        self._keeper: Optional[sqlite3.Connection] = None
        if str(path) == ":memory:":
            self._mem_uri = "file:saintess_mem_%x?mode=memory&cache=shared" % id(self)
            self._keeper = sqlite3.connect(self._mem_uri, uri=True, timeout=timeout)

    # ---------------------------------------------------------------- 连接
    @property
    def lock(self) -> threading.RLock:
        """进程内重入锁。使用方直接 `with db.lock:` 做自己的临界区。"""
        return self._lock

    def connect(self) -> sqlite3.Connection:
        """开一条新连接（调用方负责关闭；一般用 session()/readonly()/atomic()）。"""
        if self._mem_uri is not None:                 # `:memory:`：同一共享内存库
            conn = sqlite3.connect(self._mem_uri, uri=True, timeout=self.timeout)
        else:
            conn = sqlite3.connect(self.path, timeout=self.timeout)
            _tune_file_conn(conn, self.timeout)      # ★ 文件库：WAL（见下）
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
