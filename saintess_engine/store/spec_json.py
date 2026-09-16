# -*- coding: utf-8 -*-
"""表结构声明的 JSON 装载口 —— 把「表长什么样」从 Python 挪到数据文件。

**为什么有它**：`spec.Column` / `spec.TableSpec` 把表结构压成一份声明，但新包作者仍要写
Python 才能在装配期 `declare`。本模块让声明驻留纯数据文件（JSON），包侧只剩「声明文件 +
一行 `declare_file(db, path)`」，换游戏照样成立 —— 文件里出现的表名/列名/类型全由调用方给。

**格式**::

    {
      "tables": [
        {"name": "records", "columns": [
            {"name": "id", "type": "TEXT", "pk": true},
            {"name": "label", "type": "TEXT", "notnull": true},
            {"name": "payload", "type": "TEXT", "default": "{}"}
        ]},
        {"name": "notes", "columns": [
            {"name": "id", "type": "INTEGER", "pk": true},
            {"name": "body", "type": "TEXT"}
        ], "migrations": ["CREATE INDEX IF NOT EXISTS idx_notes_body ON notes(body)"]}
      ]
    }

**键面**（多一个键即报错，防拼错静默生效）：

* 顶层：`tables`（对象，不是裸数组 —— 留出以后加键的余地）
* 表级：`name` / `columns` / `migrations`
* 列级：`name` / `type` / `pk` / `notnull` / `default`

**取值约定**：

* `default` 省略 = 不写 `DEFAULT`；`default: null` 同理（JSON 分不出「缺键」与「null」）
* `pk` / `notnull` 是布尔；`default` 是标量（bool / number / string），数组/对象一律报错
* `migrations` 是 **SQL 字符串数组**（如建索引）；载入时包成 `fn(conn): conn.execute(sql)`，
  与既有的 `TableSpec(migrations=…)` 口（`fn(conn)`）兼容，**不改既有签名与语义**
* 列序 = DDL 列序；表序 = 声明序

**fail-closed**：文件读不到、JSON 不合规、键/表/列形状不对 —— 全部当场报错（点名路径 / 键 /
表 / 表.列），不猜、不静默跳过。通过形状检查后再调既有的 `_validate_spec` 做二次校验（表名 /
列名 / 类型串 / 默认值可渲染性复用引擎既有口径，不另起一套）。
"""
from __future__ import annotations

import json
import os

from .spec import Column, TableSpec, _validate_spec, declare

__all__ = ["specs_from_json", "specs_from_file", "declare_file"]

# 各层允许出现的键（多一个即报错）
_TOP_KEYS = ("tables",)
_TABLE_KEYS = ("name", "columns", "migrations")
_COLUMN_KEYS = ("name", "type", "pk", "notnull", "default")


class _SqlMigration:
    """一条 SQL 字符串迁移：`fn(conn)` 口，且**按 SQL 文本判等**。

    判等是给 `declare` 的幂等语义用的 —— 同一声明文件装载两次必须得到
    「同一个声明」（否则重复 `declare_file` 会被当成同表不同声明而报错）。
    """

    __slots__ = ("sql",)

    def __init__(self, sql: str) -> None:
        self.sql = sql

    def __call__(self, conn) -> None:
        conn.execute(self.sql)

    def __eq__(self, other) -> bool:
        return isinstance(other, _SqlMigration) and self.sql == other.sql

    def __hash__(self) -> int:
        return hash((_SqlMigration, self.sql))

    def __repr__(self) -> str:
        return f"_SqlMigration({self.sql!r})"


def _bad(where: str, msg: str) -> ValueError:
    return ValueError(f"表结构声明 {where}：{msg}")


def _unknown_keys(obj: dict, allowed: tuple, where: str) -> None:
    unknown = [k for k in obj if k not in allowed]
    if unknown:
        raise _bad(where, f"出现未知键 {unknown[0]!r}（只认 {', '.join(allowed)}）")


def _column(table: str, index: int, node) -> Column:
    if not isinstance(node, dict):
        raise _bad(f"表 {table}", f"第 {index} 列必须是对象，收到 {type(node).__name__}")
    _unknown_keys(node, _COLUMN_KEYS, f"表 {table} 第 {index} 列")
    name = node.get("name")
    if not isinstance(name, str) or not name:
        raise _bad(f"表 {table}", f"第 {index} 列缺 name（或不是非空字符串）")
    col_where = f"{table}.{name}"
    if "type" not in node:
        raise _bad(col_where, "缺 type")
    ctype = node["type"]
    if not isinstance(ctype, str) or not ctype:
        raise _bad(col_where, f"type 必须是非空字符串，收到 {ctype!r}")
    for flag in ("pk", "notnull"):
        if flag in node and not isinstance(node[flag], bool):
            raise _bad(col_where, f"{flag} 必须是布尔，收到 {type(node[flag]).__name__}")
    default = node.get("default")
    if isinstance(default, (list, dict)):
        raise _bad(col_where, f"default 只收标量（bool / number / string），收到 {type(default).__name__}")
    return Column(
        name,
        ctype,
        pk=node.get("pk", False),
        default=default,
        notnull=node.get("notnull", False),
    )


def _table(index: int, node, seen: set) -> TableSpec:
    if not isinstance(node, dict):
        raise _bad("tables", f"第 {index} 张表必须是对象，收到 {type(node).__name__}")
    name = node.get("name")
    if not isinstance(name, str) or not name:
        raise _bad("tables", f"第 {index} 张表缺 name（或不是非空字符串）")
    _unknown_keys(node, _TABLE_KEYS, f"表 {name}")
    if name in seen:
        raise _bad(f"表 {name}", "表名重复声明")
    seen.add(name)
    columns = node.get("columns")
    if not isinstance(columns, list):
        raise _bad(f"表 {name}", f"columns 必须是数组，收到 {type(columns).__name__}")
    migrations = node.get("migrations", [])
    if not isinstance(migrations, list):
        raise _bad(f"表 {name}", f"migrations 必须是数组，收到 {type(migrations).__name__}")
    runners = []
    for sql in migrations:
        if not isinstance(sql, str):
            raise _bad(f"表 {name}", f"migrations 元素必须是 SQL 字符串，收到 {type(sql).__name__}")
        runners.append(_SqlMigration(sql))
    return TableSpec(name, [_column(name, i, c) for i, c in enumerate(columns)],
                     migrations=runners)


def _specs_from_json(text, where: str) -> list:
    if isinstance(text, (bytes, bytearray)):
        try:
            text = bytes(text).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _bad(where, f"不是合法 UTF-8 文本（{exc}）") from exc
    if not isinstance(text, str):
        raise TypeError(f"表结构声明只收 str/bytes，收到 {type(text).__name__}")
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _bad(where, f"不是合法 JSON（{exc}）") from exc
    if not isinstance(doc, dict):
        raise _bad(where, f"顶层必须是对象，收到 {type(doc).__name__}")
    _unknown_keys(doc, _TOP_KEYS, where)
    if "tables" not in doc:
        raise _bad(where, "缺 'tables' 键")
    tables = doc["tables"]
    if not isinstance(tables, list):
        raise _bad(where, f"'tables' 必须是数组，收到 {type(tables).__name__}")
    if not tables:
        raise _bad(where, "'tables' 是空数组（没有任何表声明）")
    seen: set = set()
    specs = [_table(i, node, seen) for i, node in enumerate(tables)]
    for spec in specs:
        _validate_spec(spec)
    return specs


def specs_from_json(text) -> list:
    """JSON 文本/bytes → `TableSpec` 列表（声明序）。

    任何不合规**当场报错**（`ValueError` / `TypeError`），不猜、不静默跳过。
    """
    return _specs_from_json(text, "<json>")


def specs_from_file(path) -> list:
    """读文件再走 `specs_from_json`。

    文件不存在 / 不可读 → 报错（错误信息里带**绝对路径**）。
    """
    abs_path = os.path.abspath(path)
    try:
        with open(abs_path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        raise OSError(
            f"表结构声明文件读不到：{abs_path}（{exc.strerror or exc}）") from exc
    return _specs_from_json(raw, abs_path)


def declare_file(db, path, *, json_fields=()) -> list:
    """= 对 `specs_from_file(path)` 逐表 `declare(db, spec, json_fields=json_fields)`。

    返回仓库列表（**声明序**）。逐表调用走既有 `declare`：建表 SQL / 缺列自愈 / 附加迁移 /
    幂等去重全由它掌握，本函数只负责「文件 → 声明序」这一段。
    """
    return [declare(db, spec, json_fields=json_fields) for spec in specs_from_file(path)]
