# -*- coding: utf-8 -*-
"""通用存储骨架 —— SQLite 连接 / 锁 / 事务 / 建表注册 / 列迁移。

这一层只提供**形状**，不提供内容：

| 提供（通用） | 不提供（使用方） |
|---|---|
| 连接工厂、进程内锁、事务上下文 | 数据库路径（宿主/游戏决定） |
| 建表 SQL 的**注册与执行顺序** | 表结构本身 |
| 列迁移的**检查补列机制** | 补哪些列 |
| 表级 CRUD 的通用形状（`Repository`） | 业务查询 |
| 建表 / 补列 / 仓库的**声明式装配**（`declare`） | 表与列的声明本身 |

典型用法::

    from saintess_engine.store import Database, ensure_columns

    db = Database("/path/to/game.db")
    db.register_schema("core", "CREATE TABLE IF NOT EXISTS players (...);")
    db.register_migration(lambda conn: ensure_columns(conn, "players", {"hp": "INTEGER DEFAULT 0"}))
    db.init()

    with db.session() as conn:                  # 写：自动 commit / 异常 rollback
        conn.execute("INSERT INTO players ...")

    with db.readonly() as conn:                 # 读：不提交（与原「只 close」语义一致）
        rows = conn.execute("SELECT ...").fetchall()

手写 DDL 嫌重复时，用声明式甜写法（`spec.Column` / `spec.TableSpec` / `spec.declare`）::

    from saintess_engine.store import Column, TableSpec, declare

    repo = declare(db, TableSpec("records", [
        Column("id", "TEXT", pk=True),
        Column("label", "TEXT", notnull=True, default=""),
    ]), json_fields=())
    # 等价于 register_schema(手写 DDL) + 手写 class Records(Repository) 两行；
    # 已存在的表只补缺列（migrate 路径），不重建、不改结构。
"""
from .database import Database  # noqa: F401
from .migrate import columns_of, ensure_columns  # noqa: F401
from .repository import Repository  # noqa: F401
from .spec import Column, DeclaredRepository, TableSpec, declare  # noqa: F401

__all__ = [
    "Database", "Repository", "columns_of", "ensure_columns",
    # 声明式建表（Column / TableSpec / declare / DeclaredRepository）
    "Column", "TableSpec", "DeclaredRepository", "declare",
]
