# -*- coding: utf-8 -*-
"""官方宿主骨架 —— 存档：`load_player` / `save_player` 的 SQLite 实现（宿主侧，契约 §一②）。

**为什么它必须住在宿主**：接缝纪律说包内代码只拿普通 dict 进来、只交普通 dict 出去；
序列化 / 并发锁 / 落库 / 迁移全在宿主。这个文件就是那半边的最小可用实现：

    store = SQLiteStore("data/players.db")     # 建表（幂等）
    store.load_player("10001")                 # → dict | None（None = 新玩家）
    # 档在库里但解不开 → 抛 CorruptSaveError（**不是** None，见下）
    store.save_player("10001", data)           # 改完必存（一条消息一次）

三条实现取舍（读 README「常见坑」）
-----------------------------------
1. **JSON 列**（不是每字段一列）：档的形状随内容演进，宿主不该跟着改表 —— 加一列 = 迁移，
   加一个键 = 什么都不用做。代价是查不了单字段（要查就自己建索引表；现网宿主有专门索引）。
2. **一把锁 + `check_same_thread=False`**：一条消息一条事务，`BEGIN IMMEDIATE` 级别由
   `sqlite3` 自己保证；锁防的是同一进程多线程（多群并发消息）。
3. **`None` 只有一个含义 —— 「没有这个玩家」**：不预造空档（初始档属内容：
   见 `main.Package.initial_save`），免得把"新玩家"和"空档玩家"两件事混成一个。
   **另一半是 fail-closed**：档在库里、但解不开 / 不是 dict ⇒ 抛 `CorruptSaveError`，
   绝不回落成 `None`。这两种过去共用一个返回值，于是引擎的建档路径
   （`runtime.py::handle` 见 None → `initial_save` → `save_player`）会把残档直接覆盖掉
   —— 玩家数据不可逆地丢、且零日志。宁可炸在这儿，也不让它被建档吞掉。

扩展点：`load_blob` / `save_blob` 是契约 §二那对可选钩子的落地（组队/公会/世界状态这类
"不是单玩家档"的数据）。真不需要就删掉这对函数，骨架照样跑。
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time


class CorruptSaveError(RuntimeError):
    """玩家档**在库里、但解不开**（坏 JSON / 不是 dict）—— fail-closed 守门。

    它**不是**「没有这个玩家」：那种情况 `load_player` 返回 `None`，骨架据此造初始档。
    两者共用一个返回值时，下游把残档当新玩家，下一条 `save_player` 就把它覆盖掉了
    ⇒ 玩家进度不可逆地丢、且不留任何痕迹。这里选择**炸**：坏档要人来看，不是代码要猜。

    属性：`uid` / `raw`（原行原文，可直接手工修复）/ `reason`。**原行不会被改动。**
    """

    def __init__(self, uid: str, raw, reason: str):
        super().__init__(
            "玩家档 %r 在库里但解不开（%s）。原行未改动 —— 修好这条记录再发消息，"
            "**不要让建档路径把它覆盖掉**。原行：%.200r" % (uid, reason, raw))
        self.uid = uid
        self.raw = raw
        self.reason = reason


_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS players ("
    " uid TEXT PRIMARY KEY, data TEXT NOT NULL, updated REAL NOT NULL)",
    "CREATE TABLE IF NOT EXISTS blobs ("
    " key TEXT PRIMARY KEY, data TEXT NOT NULL, updated REAL NOT NULL)",
)


class SQLiteStore:
    """玩家档 / 额外 blob 的 SQLite 存储（线程安全；一条消息一条事务）。"""

    def __init__(self, path: str = ":memory:", *, timeout: float = 5.0):
        self.path = path
        self._lock = threading.RLock()
        if path != ":memory:":
            parent = os.path.dirname(os.path.abspath(path))
            if parent:
                os.makedirs(parent, exist_ok=True)
        self._conn = sqlite3.connect(path, timeout=float(timeout), check_same_thread=False)
        self.init_db()

    # ------------------------------------------------------------ 建表
    def init_db(self) -> "SQLiteStore":
        """建表（幂等）+ 打开外键（后续迁移挂点也在这里）。"""
        with self._lock:
            for statement in _SCHEMA:
                self._conn.execute(statement)
            self._conn.commit()
        return self

    # ------------------------------------------------------------ 三函数：读 / 写档
    def load_player(self, uid: str):
        """读档 → 普通 dict；**没有这个玩家 → None**（骨架会先造初始档）。

        **「档坏了」不是「没有这个玩家」**：库里那行解不开、或者解出来不是 dict 时
        抛 `CorruptSaveError`（原行原样留在库里）。回落成 `None` 会让引擎的建档路径
        把残档当新档覆盖掉 —— 那是不可逆丢档。
        """
        key = str(uid)
        with self._lock:
            row = self._conn.execute("SELECT data FROM players WHERE uid=?", (key,)).fetchone()
        if not row:
            return None
        try:
            data = json.loads(row[0])
        except (ValueError, TypeError) as exc:
            # json.loads 的「解不开」全集就是这两类（JSONDecodeError ⊂ ValueError）。
            raise CorruptSaveError(key, row[0], "JSON 解不开：%s" % (exc,)) from exc
        if not isinstance(data, dict):
            raise CorruptSaveError(key, row[0], "档不是 dict（%s）" % type(data).__name__)
        return data

    def save_player(self, uid: str, data: dict) -> None:
        """写档（upsert）。`data` 必须是 JSON 可序列化的普通 dict —— 不做鸭子类型兜底。"""
        if not isinstance(data, dict):
            raise TypeError("save_player 只收普通 dict（包内接缝纪律）")
        payload = json.dumps(data, ensure_ascii=False)
        key = str(uid)
        with self._lock:
            self._conn.execute(
                "INSERT INTO players(uid, data, updated) VALUES(?,?,?) "
                "ON CONFLICT(uid) DO UPDATE SET data=excluded.data, updated=excluded.updated",
                (key, payload, time.time()))
            self._conn.commit()

    # ------------------------------------------------------------ 额外 blob（可选钩子）
    def load_blob(self, key: str):
        with self._lock:
            row = self._conn.execute("SELECT data FROM blobs WHERE key=?", (str(key),)).fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except Exception:                                        # noqa: BLE001
            return None

    def save_blob(self, key: str, value) -> None:
        payload = json.dumps(value, ensure_ascii=False)
        with self._lock:
            self._conn.execute(
                "INSERT INTO blobs(key, data, updated) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET data=excluded.data, updated=excluded.updated",
                (str(key), payload, time.time()))
            self._conn.commit()

    # ------------------------------------------------------------ 收尾 / 自检
    def count(self) -> int:
        """档条数（冒烟自检 / 报告用）。"""
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM players").fetchone()[0])

    def close(self) -> None:
        with self._lock:
            self._conn.close()
