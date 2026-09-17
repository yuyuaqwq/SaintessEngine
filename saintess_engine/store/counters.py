# -*- coding: utf-8 -*-
"""命名累计计数 —— `CounterSpec` / `Counters` / `declare_counters`（引擎零知识）。

**为什么有它**：同一套「一行（或 `(owner, subject)` 一格）上若干命名计数字段，取出来加一个增量」
的形状，在参考实现里手写了五遍，键形态三种（单主键单列 / 单主键多列 / 复合主键单列）、
校验两种（白名单 / 没有）。把「表名 / 列名 / 哪些列可加 / 谁是第二维」这些**取值**剥掉，
剩下的形状只有一件：**白名单 + `col = col + δ`**。

**形状（引擎认什么）**

| 层 | 字段（契约词汇） | 说明 |
|---|---|---|
| 表 | `owner` | 列名（主键第一列） |
| 表 | `fields` | 计数字段列名元组 = **白名单**（引擎不校验名字含义，只校验「在不在声明里」） |
| 表 | `subject` | 列名或 `None`；给了即复合主键 `(owner, subject)`，每条 subject 一行 |

注入面：`table` / `owner` / `fields` / `subject` / `extra`（附加列）/ `pk`。
`fields` 为空 → `ValueError`；`fields` 里有非法名、与 owner/subject 同列、重复 → `ValueError`。
引擎**不新开连接、不读环境变量、不推导路径、不 commit**（提交交调用方）。

**用法**::

    from saintess_engine.store.counters import CounterSpec, declare_counters

    cnt = declare_counters(db, CounterSpec(<表名>, owner=<列名>, fields=(<列名>, ...)))
    with db.session() as conn:
        cnt.init(conn, <owner>)                 # INSERT OR IGNORE：不覆盖既有值
        cnt.bump(conn, <owner>, <列名>=<增量>)   # 白名单外 → ValueError
        cnt.read(conn, <owner>)                 # 无行 → {}

**口径分歧及理由（故意不统一；逐条对应设计稿 §3.3）**

* ⑤ **「日」计数不做进本模块** —— 周期键 → 一格值、跨周期换键，是
  `periodic.PeriodCounter` 的活（上批已落地）。本模块**只收「永不归零的累计计数」**：
  日 / 周 / 月维度一律指向 `periodic`，本模块**不 import 它**（避让判据：不造第二套周期计数）。
* ⑥ **复合主键计数器单列** —— 每条 subject 一行、键空间随数据增长，与「一行多列」形状不同。
  `CounterSpec.subject` 显式承载，**不**把复合维挤进 `fields` 的列。
* ⑦ **白名单只在本形状里** —— 收 `**deltas`（动态列名）的接口**必须**白名单 fail-closed；
  写死一条 SQL、列名是字面量的调用点保持原样（本模块不改它们）。
* ⑧ **无行 → `{}` vs 建行** —— 「读」不产生副作用（不改库），「初始化」是显式动作。
  故 `read` 无行回 `{}`（逐字保留现状空值口径）、只有 `init` 才建行，两件事分开。

**为什么不复用 `periodic.PeriodCounter`**（就地复用评估结论，照该模块自述的写法）
----------------------------------------------------------------------------
* `PeriodCounter` 的键是**调用方拼的周期键**，它管的语义是「**换周期 = 换键**，新键天然为空，
  没有跨周期清理这回事」；本模块的键是**存档表里的主键**（owner / `(owner, subject)`），
  值的生命周期是**永久累计**。把累计计数塞进 `PeriodCounter` = 每次读写都要现拼一个假周期键
  → 存档键当场变样（玩家可见的累计值丢失），所以不能就地复用。
* 两者的存储面也不同：`PeriodCounter` 只经注入的 `read` / `write` 一对可调用（值形态由调用方定），
  本模块是**表形状**（多列、SQL 级 `col = col + δ` 原子自增、白名单校验）。同构套用会同时
  改存档布局与写入语义。
* 两者都保留：`periodic` 是「周期键 → 一格值」那一支，本模块是「表行 → 若干累计列」这一支，
  不重造对方已有的东西（`PeriodCounter.consume` 的「先判后写」纪律在本模块体现为 `next_of`：
  只读当前值 + 1，**不写**）。

**明确不做**
------------
* ❌ 表名 / 列名 / 主键 / 上限 / 周期归零规则进引擎 —— 全是取值。
* ❌ 跨周期归零（日 / 周 / 月）—— 归 `periodic.PeriodCounter`；本模块不 import 它。
* ❌ 实体宽表（一行几十列、一列一个玩家属性）—— 那是实体行，不是计数器行。
* ❌ 不做 SUM / JOIN / 复杂查询；只按主键与 `(owner, subject)` 定位。
* ❌ 不缓存、不自己开事务、不 `commit`。
"""
from __future__ import annotations

from .migrate import _check_ident
from .spec import Column, TableSpec, declare

__all__ = ["CounterSpec", "Counters", "declare_counters"]


class CounterSpec:
    """一张「owner 行 / `(owner, subject)` 行 → 若干命名计数列」表的声明（**形状**，不含取值）。

    * `owner` / `fields` 必填；`fields` 即**白名单**（非空、无重复、不含 owner/subject）
    * `subject` 给了 → 复合主键 `(owner, subject)`；`None` → 单主键 `(owner,)`
    * `extra` = 附加列声明（`Column`）；`pk` 给了必须等于默认主键（形状不可两说）
    """

    def __init__(self, table: str, *, owner: str, fields, subject: str | None = None,
                 extra: tuple = (), pk: tuple | None = None) -> None:
        _check_ident(table, "表名")
        _check_ident(owner, "owner 列名")
        if subject is not None:
            _check_ident(subject, "subject 列名")
            if subject == owner:
                raise ValueError(f"表 {table}：subject 与 owner 同列（{owner!r}）")
        if isinstance(fields, (str, bytes)):
            raise TypeError(f"表 {table} 的 fields 要列名序列，收到字符串")
        fields = tuple(fields or ())
        if not fields:
            raise ValueError(
                f"表 {table} 的 fields 不能为空 —— 白名单为空等于没有可加的列（空声明无意义）")
        for name in fields:
            _check_ident(name, "计数字段名")
        dup = sorted({n for n in fields if fields.count(n) > 1})
        if dup:
            raise ValueError(f"表 {table} 的 fields 重复：{dup}")
        if owner in fields:
            raise ValueError(f"表 {table} 的 fields 与 owner 同列：{owner!r}")
        if subject is not None and subject in fields:
            raise ValueError(f"表 {table} 的 fields 与 subject 同列：{subject!r}")

        if isinstance(extra, (str, bytes)):
            raise TypeError(f"表 {table} 的 extra 要列声明序列，收到字符串")
        extra = tuple(extra or ())
        for col in extra:
            if not isinstance(col, Column):
                raise TypeError(
                    f"表 {table} 的 extra 只能是 Column，收到 {type(col).__name__}")

        names = [owner] + list(fields)
        if subject is not None:
            names.append(subject)
        names.extend(c.name for c in extra)
        dup = sorted({n for n in names if names.count(n) > 1})
        if dup:
            raise ValueError(f"表 {table} 列名重复：{dup}")

        want_pk = (owner, subject) if subject is not None else (owner,)
        if pk is not None:
            if isinstance(pk, (str, bytes)):
                raise TypeError(f"表 {table} 的 pk 要元组，收到字符串")
            given = tuple(pk)
            if given != want_pk:
                raise ValueError(
                    f"表 {table} 的主键只能是 {want_pk!r}，收到 {given!r} —— "
                    f"复合维用 subject 声明，别自己拼主键"
                )

        self.table = table
        self.owner = owner
        self.fields = fields
        self.subject = subject
        self.extra = extra
        self.pk = want_pk

    def __repr__(self) -> str:
        return (f"CounterSpec({self.table!r}, owner={self.owner!r}, "
                f"fields={self.fields!r}, subject={self.subject!r})")


def _table_spec(spec: CounterSpec) -> TableSpec:
    """声明 → `store.spec.TableSpec`（计数列一律 `INTEGER NOT NULL DEFAULT 0`）。"""
    cols = [Column(spec.owner, "TEXT", pk=True)]
    cols.extend(Column(name, "INTEGER", notnull=True, default=0) for name in spec.fields)
    if spec.subject is not None:
        cols.append(Column(spec.subject, "TEXT", pk=True))
    cols.extend(spec.extra)
    return TableSpec(spec.table, cols)


def declare_counters(db, spec: CounterSpec, *, repo=None) -> "Counters":
    """用 `store.spec.declare` 建表/补列，返回命名计数读写口。

    * `db` 是既有的 `Database` 实例（**不新开连接、不读环境变量、不推导路径**）
    * `repo` 给了就用它（已声明过的表），否则现声明一张
    """
    if not isinstance(spec, CounterSpec):
        raise TypeError(f"spec 必须是 CounterSpec，收到 {type(spec).__name__}")
    if repo is None:
        repo = declare(db, _table_spec(spec))
    return Counters(repo, spec)


class Counters:
    """命名计数的读写（**白名单 fail-closed**；`+δ` 单条 UPDATE；不缓存）。

    所有出口都接收 `conn`；提交由调用方掌握。`read` **不产生副作用**（无行回 `{}`），
    建行是显式的 `init`。
    """

    def __init__(self, repo, spec: CounterSpec) -> None:
        if not isinstance(spec, CounterSpec):
            raise TypeError(f"spec 必须是 CounterSpec，收到 {type(spec).__name__}")
        if getattr(repo, "table", None) != spec.table:
            raise ValueError(
                f"传入的 repo 表 {getattr(repo, 'table', None)!r} 与声明 {spec.table!r} 不符")
        if tuple(getattr(repo, "pk", ())) != spec.pk:
            raise ValueError(
                f"传入的 repo 主键 {tuple(getattr(repo, 'pk', ()))!r} 与声明 {spec.pk!r} 不符")
        self.repo = repo
        self.spec = spec

    def __repr__(self) -> str:
        return f"Counters({self.spec.table!r}, fields={self.spec.fields!r})"

    @property
    def fields(self) -> tuple:
        """声明的计数字段（白名单），不含 `owner` / `subject` / `extra`。"""
        return self.spec.fields

    # ------------------------------------------------------------ 内部
    def _subject_of(self, subject):
        """主键形态只认一种：单键表不接受 subject，复合键表必须给 subject。"""
        if self.spec.subject is None:
            if subject is not None:
                raise ValueError(
                    f"表 {self.spec.table} 是单键计数表，不接受 subject（收到 {subject!r}）")
            return None
        if subject is None:
            raise ValueError(
                f"表 {self.spec.table} 是复合键计数表，必须给 subject")
        return subject

    def _where(self, owner, subject):
        if subject is None:
            return f" WHERE {self.spec.owner}=?", (owner,)
        return (f" WHERE {self.spec.owner}=? AND {self.spec.subject}=?",
                (owner, subject))

    def _whitelist(self, cols, what: str) -> tuple:
        bad = [c for c in cols if c not in self.spec.fields]
        if bad:
            raise ValueError(f"{what} 非法字段: {bad}（不在声明白名单）")
        if not cols:
            raise ValueError(f"{what} 至少给一个字段（空调用不拼 SQL）")
        return tuple(cols)

    # ------------------------------------------------------------ 读
    def read(self, conn, owner, *, subject=None) -> dict:
        """该行全部列；**无行 → `{}`**（读不建行、无副作用）。"""
        subj = self._subject_of(subject)
        where, args = self._where(owner, subj)
        row = conn.execute(
            f"SELECT * FROM {self.spec.table}{where}", args).fetchone()
        return dict(row) if row else {}

    def read_subject(self, conn, owner, *, order_by=None, limit=None) -> list:
        """该 owner 下全部 subject 行（复合键表专用）。`order_by` 需为受信字符串。"""
        if self.spec.subject is None:
            raise ValueError(
                f"表 {self.spec.table} 是单键计数表，没有 subject 维度可列举")
        sql = f"SELECT * FROM {self.spec.table} WHERE {self.spec.owner}=?"
        if order_by:
            sql += f" ORDER BY {order_by}"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        return [dict(r) for r in conn.execute(sql, (owner,)).fetchall()]

    def next_of(self, conn, owner, field, *, subject=None) -> int:
        """当前值 + 1（**不写**）—— 供「先判后写」的调用点用。无行 → 1。"""
        if field not in self.spec.fields:
            raise ValueError(f"非法计数字段: {field!r}（不在声明白名单）")
        subj = self._subject_of(subject)
        where, args = self._where(owner, subj)
        row = conn.execute(
            f"SELECT {field} FROM {self.spec.table}{where}", args).fetchone()
        if row is None or row[0] is None:
            return 1
        return int(row[0]) + 1

    # ------------------------------------------------------------ 写
    def init(self, conn, owner, *, subject=None) -> None:
        """`INSERT OR IGNORE` 建行（**不覆盖既有值** —— 与现状初始化同口径）。"""
        subj = self._subject_of(subject)
        cols = [self.spec.owner]
        vals = [owner]
        if subj is not None:
            cols.append(self.spec.subject)
            vals.append(subj)
        holders = ",".join("?" for _ in cols)
        conn.execute(
            f"INSERT OR IGNORE INTO {self.spec.table} ({','.join(cols)}) "
            f"VALUES ({holders})", tuple(vals))

    def bump(self, conn, owner, *, subject=None, **deltas) -> None:
        """`col = col + δ` 单条 UPDATE。**声明外字段 → `ValueError`**（fail-closed）。"""
        subj = self._subject_of(subject)
        cols = self._whitelist(list(deltas), "bump")
        sets = ", ".join(f"{c}={c}+?" for c in cols)
        where, args = self._where(owner, subj)
        conn.execute(
            f"UPDATE {self.spec.table} SET {sets}{where}",
            tuple(deltas[c] for c in cols) + tuple(args))

    def reset(self, conn, owner, *, subject=None, fields=None) -> None:
        """清零（不给 `fields` = 全部声明列；给了也必须落在白名单里）。"""
        subj = self._subject_of(subject)
        cols = self._whitelist(
            list(self.spec.fields if fields is None else fields), "reset")
        sets = ", ".join(f"{c}=0" for c in cols)
        where, args = self._where(owner, subj)
        conn.execute(f"UPDATE {self.spec.table} SET {sets}{where}", tuple(args))
