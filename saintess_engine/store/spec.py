# -*- coding: utf-8 -*-
"""声明式建表 —— 列声明 + 表声明 + `declare()`（建表 / 补列 / 装配 Repository）。

**为什么有它**：`Database.register_schema` 收的是整段手写 DDL，`Repository` 子类还要手抄
`table` / `pk` 两行 —— 一张表的形状在两个地方各写一遍，改一处忘一处。本模块把「表长什么样」
压成一份声明，建表 SQL、补列迁移、访问骨架都从这一份声明派生。

**用法**::

    from saintess_engine.store import Column, Database, TableSpec, declare

    db = Database("/path/to/any.db")
    repo = declare(db, TableSpec("records", [
        Column("id", "TEXT", pk=True),
        Column("label", "TEXT", notnull=True, default=""),
        Column("payload", "TEXT", default="{}"),
    ]), json_fields=("payload",))

    with db.session() as conn:
        repo.upsert(conn, {"id": "r1", "label": "x", "payload": {"n": 1}})
        repo.get(conn, "r1")            # payload 自动 json 解码
        repo.count(conn); repo.all(conn); repo.delete(conn, "r1")

**形状在引擎、取值在调用方**：表名 / 列名 / 类型 / 默认值全由调用方给；引擎只认
「列 / 主键 / 非空 / 默认」四个通用性质。换个游戏照样成立的名字才配写在这里 ——
`name` / `label` / `payload` 成立，任何具体业务字段不成立（同 `run` / `loot` 的零知识纪律）。

**有意不做的事**
----------------
* **不做 ORM**：不生成 JOIN、不做关系映射、不猜查询 —— 业务 SQL 照旧手写（同 `Repository`）。
* **不改已存在的表结构**：`CREATE TABLE IF NOT EXISTS` 只管首建；已存在的表交给
  `migrate.ensure_columns` **缺才补**。`ALTER TABLE ADD COLUMN` 在 SQLite 上加不了主键，
  故「既有主键与声明不符」在 `declare` 当场报错（不静默交回一个写不进去的仓库）。
* **不碰事务边界**：提交仍由 `Database.init()` 掌握；`declare` 只注册并触发一次 `init()`
  （`init()` 自带幂等），不自己开事务、不自己 commit。
* **不读环境变量、不推导路径**：路径永远由调用方传给 `Database`（同 `Database` 的取舍）。
"""
from __future__ import annotations

import re
import threading
import weakref
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from .migrate import _check_ident, ensure_columns
from .repository import Repository

__all__ = ["Column", "TableSpec", "DeclaredRepository", "declare"]

# 列类型串白名单：词 + 可选长度/精度（`TEXT` / `INTEGER` / `DOUBLE PRECISION` / `VARCHAR(20)`）。
# 类型要拼进 DDL，收窄到「类型长什么样」才安全（与 `_check_ident` 防注入同一条纪律）。
_TYPE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:[ ]+[A-Za-z_][A-Za-z0-9_]*)*"
    r"(?:\(\s*\d+\s*(?:,\s*\d+\s*)?\))?$"
)


@dataclass
class Column:
    """一列的声明：名字 + SQL 类型 + 主键/非空/默认。

    * `type`    —— SQL 类型串（`TEXT` / `INTEGER` / `VARCHAR(20)` …），由调用方给
    * `pk`      —— 是否主键（复合主键就多列都写 `True`，主键顺序 = 声明顺序）
    * `notnull` —— 是否 `NOT NULL`
    * `default` —— 默认值；`None` = 不写 `DEFAULT`（`bool` 落 1/0，`str` 加引号并转义）
    """

    name: str
    type: str
    pk: bool = False
    default: Any = None
    notnull: bool = False

    def __post_init__(self) -> None:
        self.pk = bool(self.pk)
        self.notnull = bool(self.notnull)


@dataclass
class TableSpec:
    """一张表的声明：名字 + 列 + 附加迁移。

    * `columns`    —— 列声明（顺序即 DDL 列序）
    * `migrations` —— 附加迁移器（`fn(conn)`）；按声明序交给 `Database.register_migration`，
      在形状自带的「补缺列」迁移**之后**执行（补列是形状的活，附加迁移是调用方的活）
    """

    name: str
    columns: list
    migrations: list = field(default_factory=list)

    def __post_init__(self) -> None:
        self.columns = list(self.columns or ())
        self.migrations = list(self.migrations or ())

    def pk_columns(self) -> tuple:
        """主键列名（按声明顺序）。"""
        return tuple(c.name for c in self.columns if c.pk)


class DeclaredRepository(Repository):
    """由 `TableSpec` 装配的 `Repository`：`table` / `pk` 取自声明，`json_fields` 由调用方给。

    也可以直接用（不经过 `declare`）：只装配字段，**不建表、不注册迁移** ——
    建表与补列是 `declare` 的活。需要「一张表只声明一次」时用 `declare`。
    """

    def __init__(self, db, spec: TableSpec, *, json_fields: Iterable = ()) -> None:
        if not isinstance(spec, TableSpec):
            raise TypeError(f"spec 必须是 TableSpec，收到 {type(spec).__name__}")
        self.table = spec.name
        self.pk = spec.pk_columns()
        self.json_fields = tuple(json_fields or ())
        super().__init__(db)


# ───────────────────────────────────────────────────────────── 内部：渲染与校验
def _render_default(value: Any, where: str) -> str:
    """把默认值渲染成 SQL 字面量；不认识的类型**当场报错**（不猜、不字符串化）。"""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    raise TypeError(
        f"列 {where} 的默认值类型不支持：{type(value).__name__}"
        f"（只收 None / bool / int / float / str）"
    )


def _column_decl(col: Column, where: str) -> str:
    """一列的「类型 [NOT NULL] [DEFAULT …]」片段（建表与 ALTER 补列共用同一份）。"""
    decl = col.type.strip()
    if col.notnull:
        decl += " NOT NULL"
    if col.default is not None:
        decl += " DEFAULT " + _render_default(col.default, where)
    return decl


def _validate_spec(spec: TableSpec) -> None:
    """表名 / 列名 / 类型 / 默认值 / 重名 / 迁移器可调用性 —— 全过才允许注册。"""
    if not isinstance(spec, TableSpec):
        raise TypeError(f"spec 必须是 TableSpec，收到 {type(spec).__name__}")
    if not isinstance(spec.name, str):
        raise ValueError(f"非法表名：{spec.name!r}（只允许 [A-Za-z_][A-Za-z0-9_]*）")
    _check_ident(spec.name, "表名")
    if not spec.columns:
        raise ValueError(f"表 {spec.name} 没有任何列（空表声明无意义）")
    seen: set = set()
    for col in spec.columns:
        if not isinstance(col, Column):
            raise TypeError(f"表 {spec.name} 的列必须是 Column，收到 {type(col).__name__}")
        if not isinstance(col.name, str):
            raise ValueError(f"表 {spec.name} 非法列名：{col.name!r}（只允许 [A-Za-z_][A-Za-z0-9_]*）")
        _check_ident(col.name, "列名")
        if col.name in seen:
            raise ValueError(f"表 {spec.name} 列名重复：{col.name}")
        seen.add(col.name)
        if not isinstance(col.type, str) or not _TYPE.match(col.type.strip()):
            raise ValueError(
                f"非法列类型：{spec.name}.{col.name} {col.type!r}"
                f"（只收类型串，如 TEXT / INTEGER / VARCHAR(20)）"
            )
        if col.default is not None:
            _render_default(col.default, f"{spec.name}.{col.name}")   # 提前验可渲染性
    for fn in spec.migrations:
        if not callable(fn):
            raise TypeError(f"表 {spec.name} 的迁移器必须可调用，收到 {fn!r}")


def _ddl(spec: TableSpec) -> str:
    """建表 SQL：`CREATE TABLE IF NOT EXISTS <name> (列…, PRIMARY KEY (…))`。"""
    lines = [f"{c.name} {_column_decl(c, f'{spec.name}.{c.name}')}" for c in spec.columns]
    pk = spec.pk_columns()
    if pk:
        lines.append("PRIMARY KEY (" + ", ".join(pk) + ")")
    return "CREATE TABLE IF NOT EXISTS {} (\n    {}\n);".format(
        spec.name, ",\n    ".join(lines))


def _column_migration(spec: TableSpec) -> Callable:
    """形状自带的补列迁移：缺才补（列定义与建表同源）。"""
    decls = {c.name: _column_decl(c, f"{spec.name}.{c.name}") for c in spec.columns}

    def _migrate(conn) -> None:
        ensure_columns(conn, spec.name, decls)

    return _migrate


def _verify_pk(db, name: str, want: tuple) -> None:
    """既有表的主键必须覆盖声明 —— ALTER 加不了主键，不符即当场报错。"""
    if not want:
        return
    with db.readonly() as conn:
        rows = conn.execute(f"PRAGMA table_info({name})").fetchall()
    have = [r[1] for r in rows if r[5]]
    if sorted(have) != sorted(want):
        raise ValueError(
            f"表 {name} 的既有主键 {have or '（无）'} 与声明 {list(want)} 不符："
            f"ALTER TABLE 加不了主键 —— 已存在的表只做缺列自愈，改主键请显式迁移"
        )


# ───────────────────────────────────────────────────────────── 注册表（幂等）
# 一个 Database 上「哪张表已经声明过什么」。弱引用键：db 被回收，登记随之消失，
# 不跨库串味（两个 Database 各自 declare 同名表互不影响）。
_DECLARED: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()
_LOCK = threading.Lock()


def declare(db, spec: TableSpec, *, json_fields: Iterable = ()) -> DeclaredRepository:
    """声明即建表：注册建表 SQL + 补列迁移，建好表，返回该表的 `DeclaredRepository`。

    * 建表 SQL 由 `spec.columns` 生成；已存在的表**不改结构**，缺列由
      `migrate.ensure_columns` 补（缺才补）
    * **幂等**：同一个 `spec`（同表名 + 同列声明）重复 declare → 不重复注册、不重建、
      不抛错，返回同一个仓库实例（换 `json_fields` 则回一个按新 `json_fields` 装配的）
    * **同表不同声明** → `ValueError`（不静默覆盖语义；改结构请显式迁移）
    * 表名 / 列名 / 类型串 / 默认值不过校验 → `ValueError` / `TypeError`，**注册前**就抛
    * `db.init()` 在这里触发一次（它自带幂等）—— 所以 `declare` 应在建库装配期调用，
      不要塞进已开的 `db.session()` 写事务里
    """
    _validate_spec(spec)
    repo = DeclaredRepository(db, spec, json_fields=json_fields)
    with _LOCK:
        reg = _DECLARED.get(db)
        if reg is None:
            reg = {}
            _DECLARED[db] = reg
        prev = reg.get(spec.name)
        if prev is not None:
            if prev[0] != spec:
                raise ValueError(
                    f"表 {spec.name} 已在本 Database 上声明过，且本次声明不同："
                    f"既有列 {[c.name for c in prev[0].columns]} vs 本次 "
                    f"{[c.name for c in spec.columns]}"
                    f"（同表不同声明不静默覆盖：改表名或写显式迁移）"
                )
            if prev[1].json_fields == repo.json_fields:
                return prev[1]
            reg[spec.name] = (spec, repo)
            return repo
        db.register_schema(spec.name, _ddl(spec))
        db.register_migration(_column_migration(spec))
        for fn in spec.migrations:
            db.register_migration(fn)
        db.init()
        _verify_pk(db, spec.name, spec.pk_columns())
        reg[spec.name] = (spec, repo)
    return repo
