# -*- coding: utf-8 -*-
"""列迁移骨架 —— 「缺才补」的 ALTER 机制。

原代码里这类逻辑是**手写几十行**逐一判断：

    pcols = [r[1] for r in conn.execute("PRAGMA table_info(players)").fetchall()]
    if "class_tier" not in pcols:
        conn.execute("ALTER TABLE players ADD COLUMN class_tier INTEGER DEFAULT 0")
    if "attr_pts" not in pcols:
        ...    # × 30 遍

本模块把它压成一次调用：

    ensure_columns(conn, "players", {
        "class_tier": "INTEGER DEFAULT 0",
        "attr_pts":   "INTEGER DEFAULT 0",
    })

只提供机制，不提供**补哪些列** —— 那是使用方的内容。
"""
from __future__ import annotations

import re
import sqlite3
from typing import Iterable, Mapping

__all__ = ["columns_of", "ensure_columns"]

# 标识符白名单：表名/列名要拼进 SQL，务必校验（防注入 / 防拼错）
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _check_ident(name: str, what: str) -> str:
    if not _IDENT.match(name or ""):
        raise ValueError(f"非法{what}：{name!r}（只允许 [A-Za-z_][A-Za-z0-9_]*）")
    return name


def columns_of(conn: sqlite3.Connection, table: str) -> set[str]:
    """表的现有列名集合（表不存在 → 空集）。

    两种 row_factory 都支持：走索引取第 1 列（`name`），不依赖列名访问。
    """
    _check_ident(table, "表名")
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1] for r in rows}


def ensure_columns(conn: sqlite3.Connection, table: str,
                   spec: Mapping[str, str]) -> list[str]:
    """`spec` = {列名: "列定义"}（如 ``{"hp": "INTEGER DEFAULT 0"}``）。

    缺的列按 `spec` 顺序 `ALTER TABLE ADD COLUMN`；已有的跳过。
    返回**本次实际补上的列名列表**（便于测试断言与日志）。

    注意：`ALTER TABLE ADD COLUMN` 在 SQLite 上无法加 `PRIMARY KEY`/`UNIQUE`；
    索引请用 `CREATE INDEX IF NOT EXISTS` 单独建。
    """
    _check_ident(table, "表名")
    have = columns_of(conn, table)
    added: list[str] = []
    for col, decl in spec.items():
        _check_ident(col, "列名")
        if col in have:
            continue
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        have.add(col)
        added.append(col)
    return added


def missing_columns(conn: sqlite3.Connection, table: str,
                    spec: Iterable[str]) -> list[str]:
    """只查不补：`spec` 里哪些列当前缺失（供校验/报告用）。"""
    _check_ident(table, "表名")
    have = columns_of(conn, table)
    return [c for c in spec if c not in have]
