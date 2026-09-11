# -*- coding: utf-8 -*-
"""表级访问骨架 —— `Repository` 基类（薄，可选）。

定位：提供「一张表」最常见的几件事，业务查询仍自己写 SQL。

    class PlayerRepo(Repository):
        table = "players"
        pk = ("qq_id",)
        json_fields = ("equipment", "attributes")   # 自动 json 编解码

    repo = PlayerRepo(db)
    with db.session() as conn:
        repo.upsert(conn, {"qq_id": "1001", "equipment": {"sword": 1}})
        row = repo.get(conn, "1001")

有意不做的事
------------
* **不做 ORM**：不生成复杂查询、不做 JOIN、不做关系映射 —— 业务 SQL 手写更清楚。
* **不做连接管理**：方法都接收 `conn`，事务边界由使用方（`db.session()`）掌握。
  这样「一组写要么全成要么全不成」的语义留在业务侧，不被基类偷偷开事务破坏。
* **不做列自动迁移**：用 `migrate.ensure_columns`。
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterable, Optional

from .migrate import _check_ident, columns_of

__all__ = ["Repository"]


class Repository:
    """一张表的通用访问骨架。

    子类必须声明：
    * `table`：表名
    * `pk`：主键列（元组；复合主键按顺序写）

    可选声明：
    * `json_fields`：需要自动 `json` 编解码的列（存 TEXT，读出即对象）
    """

    table: str = ""
    pk: tuple[str, ...] = ()
    json_fields: tuple[str, ...] = ()

    def __init__(self, db) -> None:
        self.db = db
        if not self.table:
            raise ValueError(f"{type(self).__name__} 未声明 table")
        _check_ident(self.table, "表名")
        for c in self.pk:
            _check_ident(c, "主键列")
        for c in self.json_fields:
            _check_ident(c, "列名")

    # ------------------------------------------------------------ 编解码
    def _encode(self, data: dict) -> dict:
        """写出前：`json_fields` 里的对象 → JSON 文本。"""
        out = dict(data)
        for f in self.json_fields:
            if f in out and not isinstance(out[f], (str, type(None))):
                out[f] = json.dumps(out[f], ensure_ascii=False)
        return out

    def _decode(self, row: Optional[sqlite3.Row]) -> Optional[dict]:
        """读入后：`json_fields` 里的 JSON 文本 → 对象（解析失败保持原值）。"""
        if row is None:
            return None
        d = dict(row)
        for f in self.json_fields:
            if f in d and isinstance(d[f], str):
                try:
                    d[f] = json.loads(d[f])
                except Exception:
                    pass
        return d

    # ------------------------------------------------------------ 查询
    def columns(self, conn: sqlite3.Connection) -> set[str]:
        """表的现有列（用于过滤写入字段）。"""
        return columns_of(conn, self.table)

    def _where_pk(self) -> str:
        if not self.pk:
            raise ValueError(f"{type(self).__name__} 未声明 pk")
        return " AND ".join(f"{c}=?" for c in self.pk)

    def get(self, conn: sqlite3.Connection, *pk_values: Any) -> Optional[dict]:
        """按主键取一行（不存在 → None）。"""
        row = conn.execute(
            f"SELECT * FROM {self.table} WHERE {self._where_pk()}", pk_values
        ).fetchone()
        return self._decode(row)

    def all(self, conn: sqlite3.Connection, *, order_by: Optional[str] = None,
            limit: Optional[int] = None) -> list[dict]:
        """取全表（可选排序/限行）。`order_by` 需为受信字符串（由代码写死，勿拼用户输入）。"""
        sql = f"SELECT * FROM {self.table}"
        if order_by:
            sql += f" ORDER BY {order_by}"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        return [self._decode(r) for r in conn.execute(sql).fetchall()]

    def count(self, conn: sqlite3.Connection) -> int:
        return int(conn.execute(f"SELECT COUNT(*) FROM {self.table}").fetchone()[0])

    # ------------------------------------------------------------ 写入
    def upsert(self, conn: sqlite3.Connection, data: dict) -> None:
        """按主键 INSERT，冲突则 UPDATE 其余列。

        * `data` 里不属于该表的列会被**静默丢弃**（防止拼错列名写坏 SQL）
        * 主键列必须齐（否则无法定位冲突目标）
        * 不自己开事务 —— 与调用方的事务边界一致
        """
        if not self.pk:
            raise ValueError(f"{type(self).__name__} 未声明 pk")
        missing = [c for c in self.pk if c not in data]
        if missing:
            raise ValueError(f"upsert 缺主键列：{missing}")
        cols = self.columns(conn)
        payload = self._encode({k: v for k, v in data.items() if k in cols})
        if not payload:
            raise ValueError(f"upsert 无有效列：{sorted(data)} vs 表 {self.table}")
        names = list(payload)
        holders = ",".join("?" for _ in names)
        updates = [f"{c}=excluded.{c}" for c in names if c not in self.pk]
        sql = f"INSERT INTO {self.table} ({','.join(names)}) VALUES ({holders})"
        if updates:
            sql += f" ON CONFLICT({','.join(self.pk)}) DO UPDATE SET {','.join(updates)}"
        else:
            sql += f" ON CONFLICT({','.join(self.pk)}) DO NOTHING"
        conn.execute(sql, [payload[c] for c in names])

    def delete(self, conn: sqlite3.Connection, *pk_values: Any) -> int:
        """按主键删一行，返回受影响行数。"""
        cur = conn.execute(
            f"DELETE FROM {self.table} WHERE {self._where_pk()}", pk_values
        )
        return cur.rowcount

    def upsert_many(self, conn: sqlite3.Connection, rows: Iterable[dict]) -> int:
        """批量 upsert（同一事务内），返回条数。"""
        n = 0
        for r in rows:
            self.upsert(conn, r)
            n += 1
        return n
