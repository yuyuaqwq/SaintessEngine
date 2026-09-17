# -*- coding: utf-8 -*-
"""owner 键单行快照仓储 —— `SnapshotSpec` / `SnapshotRepo` / `declare_snapshot`（引擎零知识）。

**为什么有它**：同一套「一张表 + 主键是 owner + 一列存整段 JSON + 一个可选时间戳 + 一个可选
过期门」的形状，在参考实现里被手写了三遍（战斗快照 / 副本大陆 / 元素使用记录）。三份的差别
全在**取值**：表名、列名、时间戳基准（列 vs 载荷内键）、TTL 数值、过期之后干什么。
把取值剥掉，形状只剩一件：**owner → 一行 JSON；时间戳可有可无；过期门可有可无**。

**形状（引擎认什么）**

| 层 | 字段（契约词汇） | 说明 |
|---|---|---|
| 表 | `owner` | 列名（主键，单列）；引擎**不写死任何键名** |
| 表 | `blob` | 列名；该列存 JSON 文本（复用 `Repository` 的 `json_fields` 编解码） |
| 表 | `stamp` | 列名或 `None`；时间戳落在**列**里时用它 |
| 载荷 | `stamp_key` | 键名或 `None`；时间戳落在**载荷里**时用它（与 `stamp` **二选一**） |
| 载荷 | `expired_key` | 键名或 `None`；`keep` 判真时打这个标记 |

注入面（引擎零默认取值）：`table` / `owner` / `blob` / `stamp` / `stamp_key` / `expired_key` /
`extra`（附加列，如展示名）/ `pk` · `prepare`（写入前的清洗回调）· `now`（调用方传钟，
引擎不读时间库）· `ttl`（数值）· `keep`（「哪些过期也不删」的内容判据）·
`on_expire`（过期动作回调）。引擎**不新开连接、不读环境变量、不推导路径、不 commit**。

**用法**::

    from saintess_engine.store.snapshots import SnapshotSpec, declare_snapshot

    snap = declare_snapshot(db, SnapshotSpec("some_table", owner=<列名>, blob=<列名>,
                                             stamp=<列名>, expired_key=<标记键>),
                            prepare=<清洗函数>)
    with db.session() as conn:
        snap.put(conn, <owner>, {<载荷>}, stamp=<时间戳>)
        snap.get(conn, <owner>, now=<调用方的钟>, ttl=<秒>,
                 keep=<判据>, on_expire=<回调>)
        snap.drop(conn, <owner>); snap.sweep(conn, now=..., ttl=..., keep=...)

**口径分歧及理由（故意不统一；逐条对应设计稿 §3.3）**

* ① **`ttl` 基准：列 vs 载荷键** —— 前者是「最后活动」，后者是「创建时刻」，语义不同
  （副本大陆「开本后一段时间内一直活着」是刻意的）。故 `stamp` / `stamp_key` **二选一显式承载**，
  不给默认：两者同给当场 `ValueError`，两者都没声明还传 `ttl` 也当场 `ValueError`
  （不静默「永不过期」）。
* ② **过期动作三态** —— 删行 / 打标保留 / 删键（外加回调里触发销毁）。「过期之后怎么办」是
  内容语义，引擎只给 `keep` + `on_expire` 两个注入口，**默认 = 删**。
* ③ **打标不改 `stamp`** —— 标记是幂等的、可重复观察的；若顺手更新 stamp，「过期标记」会被
  自己续命。故打标只写 `blob` 列/载荷，绝不碰时间戳。
* ④ **`put` 只收 dict** —— 标量文本（`str(value)` 那一支口径）不进本形状：标量走 `counters`，
  或由内容侧自己转文本。两种口径不混进一个方法。
* ⑨ **`prepare` 是「清 set」而不是「拒收」** —— 历史档把 `set` 落成过字符串（修过 bug）；
  转是修复口径，拒收会让老档读不出来。清洗规则是内容现状，故注入；默认 `None`（= 不清）。
* ⑩ **`sweep` 只扫自己那张表** —— 按**键前缀**扫共享 KV 表是内容协议（且那张表上钉着别的门禁），
  引擎不该知道谁的键长什么样。前缀扫描留在内容侧。

**明确不做**
------------
* ❌ 表名 / 列名 / 主键 / `ttl` 数值 / 清洗规则 / 过期动作 / `keep` 判据进引擎 —— 全是取值。
* ❌ 不带 `now` 的隐式时钟：不 import 任何时间/日期库，`now` 一律调用方传。
* ❌ 不做后台定时清扫（不注册回调、不引 `timers`）：现状就是惰性读门 + 显式 `sweep`。
* ❌ 不拼存档键、不认键格式（键是内容协议，引擎只当不透明字符串）。
* ❌ 不缓存：每次都现读现算；不自己开事务、不 `commit`（事务边界交调用方）。
* ❌ 不做 ORM / JOIN / 复杂查询；`owners(prefix=)` 之外的查询面一概不提供。
"""
from __future__ import annotations

from .migrate import _check_ident
from .spec import Column, TableSpec, declare

__all__ = ["SnapshotSpec", "SnapshotRepo", "declare_snapshot"]


def _nonempty_text(value, what: str) -> str:
    """载荷内的键名（非 SQL 标识符）：只要求非空字符串。"""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{what} 必须是非空字符串，收到 {value!r}")
    return value


class SnapshotSpec:
    """一张「owner 键 → 单行 JSON 快照」表的声明（**形状**，不含取值）。

    * `table` / `owner` / `blob` 必填（合法 SQL 标识符）
    * `stamp`（列名）与 `stamp_key`（载荷内的键）**二选一**；都不给 = 无时间维度
    * `expired_key` 给定时，`keep` 判真的过期行会在载荷里被打上该键（值 `True`）
    * `extra` = 附加列声明（`Column`），如展示名；`pk` = 主键列（本形状只支持
      「主键就是 owner」的单行语义，给了也必须等于 `(owner,)`）
    """

    def __init__(self, table: str, *, owner: str, blob: str,
                 stamp: str | None = None, stamp_key: str | None = None,
                 extra: tuple = (), pk: tuple | None = None,
                 expired_key: str | None = None) -> None:
        _check_ident(table, "表名")
        _check_ident(owner, "owner 列名")
        _check_ident(blob, "blob 列名")
        if stamp is not None:
            _check_ident(stamp, "stamp 列名")
        if stamp is not None and stamp_key is not None:
            raise ValueError(
                f"表 {table}：stamp 与 stamp_key 二选一（stamp={stamp!r} / "
                f"stamp_key={stamp_key!r}）—— 时间戳基准是内容口径，引擎不替调用方挑"
            )
        if stamp_key is not None:
            _nonempty_text(stamp_key, f"表 {table} 的 stamp_key")
        if expired_key is not None:
            _nonempty_text(expired_key, f"表 {table} 的 expired_key")

        if isinstance(extra, (str, bytes)):
            raise TypeError(f"表 {table} 的 extra 要列声明序列，收到字符串")
        extra = tuple(extra or ())
        for col in extra:
            if not isinstance(col, Column):
                raise TypeError(
                    f"表 {table} 的 extra 只能是 Column，收到 {type(col).__name__}")

        names = [owner, blob]
        if stamp is not None:
            names.append(stamp)
        names.extend(c.name for c in extra)
        dup = sorted({n for n in names if names.count(n) > 1})
        if dup:
            raise ValueError(f"表 {table} 列名重复：{dup}")

        if pk is None:
            want_pk = (owner,)
        else:
            if isinstance(pk, (str, bytes)):
                raise TypeError(f"表 {table} 的 pk 要元组，收到字符串")
            want_pk = tuple(pk)
        if want_pk != (owner,):
            raise ValueError(
                f"表 {table} 的快照主键只能是 ({owner!r},)，收到 {want_pk!r} —— "
                f"单行快照一个 owner 一行，复合主键请用 counters"
            )

        self.table = table
        self.owner = owner
        self.blob = blob
        self.stamp = stamp
        self.stamp_key = stamp_key
        self.expired_key = expired_key
        self.extra = extra
        self.pk = want_pk

    def __repr__(self) -> str:
        return (f"SnapshotSpec({self.table!r}, owner={self.owner!r}, "
                f"blob={self.blob!r}, stamp={self.stamp!r}, "
                f"stamp_key={self.stamp_key!r}, expired_key={self.expired_key!r})")


def _table_spec(spec: SnapshotSpec) -> TableSpec:
    """声明 → `store.spec.TableSpec`（建表与补列全部复用既有 `declare`）。"""
    cols = [Column(spec.owner, "TEXT", pk=True),
            Column(spec.blob, "TEXT", default="{}")]
    if spec.stamp is not None:
        cols.append(Column(spec.stamp, "INTEGER"))
    cols.extend(spec.extra)
    return TableSpec(spec.table, cols)


def declare_snapshot(db, spec: SnapshotSpec, *, prepare=None,
                     repo=None) -> "SnapshotRepo":
    """用 `store.spec.declare` 建表/补列，返回 owner 键快照仓储。

    * `db` 是既有的 `Database` 实例（**不新开连接、不读环境变量、不推导路径**）
    * `repo` 给了就用它（已声明过的表），否则现声明一张：`blob` 一律走 `json_fields`
    * `prepare` 是写入前的清洗回调（可调用或 `None`）
    """
    if not isinstance(spec, SnapshotSpec):
        raise TypeError(f"spec 必须是 SnapshotSpec，收到 {type(spec).__name__}")
    if repo is None:
        repo = declare(db, _table_spec(spec), json_fields=(spec.blob,))
    return SnapshotRepo(repo, spec, prepare=prepare)


class SnapshotRepo:
    """owner 键 → 单行 JSON 快照：读 / 写 / 删 / TTL 惰性回收。**不缓存、不自开事务**。

    所有出口都接收 `conn`；提交由调用方掌握（`db.session()` / `atomic()`）。
    过期门只在 `get` / `sweep` 上，`raw` / `stamp_of` 无副作用。
    """

    def __init__(self, repo, spec: SnapshotSpec, *, prepare=None, label=None) -> None:
        if not isinstance(spec, SnapshotSpec):
            raise TypeError(f"spec 必须是 SnapshotSpec，收到 {type(spec).__name__}")
        if prepare is not None and not callable(prepare):
            raise TypeError(f"prepare 必须可调用，收到 {type(prepare).__name__}")
        if getattr(repo, "table", None) != spec.table:
            raise ValueError(
                f"传入的 repo 表 {getattr(repo, 'table', None)!r} 与声明 {spec.table!r} 不符")
        if tuple(getattr(repo, "pk", ())) != spec.pk:
            raise ValueError(
                f"传入的 repo 主键 {tuple(getattr(repo, 'pk', ()))!r} 与声明 {spec.pk!r} 不符")
        if spec.blob not in tuple(getattr(repo, "json_fields", ())):
            raise ValueError(
                f"传入的 repo 未把 {spec.blob!r} 声明为 json_fields —— "
                f"快照载荷需要 JSON 编解码，否则 dict 写不进去"
            )
        self.repo = repo
        self.spec = spec
        self.prepare = prepare
        self.label = label if label is not None else spec.table
        self.table = spec.table
        self.owner_col = spec.owner
        self.blob_col = spec.blob

    def __repr__(self) -> str:
        return (f"SnapshotRepo({self.label!r}, table={self.table!r}, "
                f"owner={self.owner_col!r}, blob={self.blob_col!r})")

    # ------------------------------------------------------------ 内部
    def _payload_of(self, row):
        if not row:
            return None
        payload = row.get(self.blob_col)
        return payload if isinstance(payload, dict) else None

    def _stamp_of_row(self, row):
        if not row:
            return None
        if self.spec.stamp is not None:
            return row.get(self.spec.stamp)
        if self.spec.stamp_key is not None:
            payload = row.get(self.blob_col)
            if isinstance(payload, dict):
                return payload.get(self.spec.stamp_key)
        return None

    def _require_stamp(self, ttl):
        if self.spec.stamp is None and self.spec.stamp_key is None:
            raise ValueError(
                f"表 {self.spec.table} 未声明 stamp/stamp_key，无法判过期（ttl={ttl!r}）—— "
                f"要么补声明，要么不传 ttl"
            )

    def _require_writable_stamp(self):
        if self.spec.stamp is None and self.spec.stamp_key is None:
            raise ValueError(
                f"表 {self.spec.table} 未声明 stamp/stamp_key，不能写 stamp —— "
                f"要么补声明，要么不传 stamp"
            )

    def _mark_expired(self, conn, owner, payload: dict) -> dict:
        """打过期标记：只写载荷，**不碰时间戳**（口径分歧 ③）。未声明标记键则只保留。"""
        key = self.spec.expired_key
        if not key:
            return payload
        payload[key] = True
        self.repo.upsert(conn, {self.spec.owner: owner, self.blob_col: dict(payload)})
        return payload

    def _expire_row(self, conn, owner, payload: dict, *, keep, on_expire):
        """过期行的落地动作：`keep` 判真 → 打标保留；否则 `on_expire` 之后删行（默认动作）。"""
        if keep is not None and keep(owner, payload):
            payload = self._mark_expired(conn, owner, payload)
            if on_expire is not None:
                on_expire(owner, payload)
            return None
        if on_expire is not None:
            on_expire(owner, payload)
        self.drop(conn, owner)
        return None

    # ------------------------------------------------------------ 读
    def raw(self, conn, owner):
        """读载荷（不过期、无副作用；无行 / JSON 坏值 → `None`）。"""
        return self._payload_of(self.repo.get(conn, owner))

    def get(self, conn, owner, *, now, ttl=None, keep=None, on_expire=None):
        """带过期门地读载荷。

        * `ttl is None` → 不过期门（等价 `raw`）
        * 未过期（含时间戳缺失/为 0）→ 载荷
        * 过期且 `keep(owner, payload)` 为假 → `on_expire(owner, payload)` + 删行 → `None`
        * 过期且 `keep` 为真 → 打 `expired_key` 标记（**不改 stamp**）+ `on_expire` → `None`
        * 载荷 JSON 坏值 → `None`，**且不删行**（与 `sweep` 同一条保守口径）
        """
        if ttl is None:
            return self.raw(conn, owner)
        self._require_stamp(ttl)
        row = self.repo.get(conn, owner)
        payload = self._payload_of(row)
        if payload is None:
            return None
        stamp = self._stamp_of_row(row)
        if not stamp or now - stamp <= ttl:
            return payload
        return self._expire_row(conn, owner, payload, keep=keep, on_expire=on_expire)

    def stamp_of(self, conn, owner):
        """该行的时间戳（列或载荷键；无行/无时间维度 → `None`）。无副作用。"""
        return self._stamp_of_row(self.repo.get(conn, owner))

    # ------------------------------------------------------------ 写
    def put(self, conn, owner, payload, *, stamp=None) -> None:
        """整行 upsert（写入前过 `prepare`）。`stamp` 给了就写时间戳列/载荷键。"""
        if not isinstance(payload, dict):
            raise TypeError(
                f"快照载荷必须是 dict，收到 {type(payload).__name__} —— "
                f"标量文本请走 counters 或内容侧自己转"
            )
        if stamp is not None:
            self._require_writable_stamp()
        body = dict(payload)
        if self.prepare is not None:
            body = self.prepare(body)
            if not isinstance(body, dict):
                raise TypeError(
                    f"prepare 必须回 dict，收到 {type(body).__name__}")
        row = {self.spec.owner: owner}
        if stamp is not None and self.spec.stamp_key is not None:
            body[self.spec.stamp_key] = stamp
        if stamp is not None and self.spec.stamp is not None:
            row[self.spec.stamp] = stamp
        row[self.blob_col] = body
        self.repo.upsert(conn, row)

    def merge(self, conn, owner, patch, *, stamp=None) -> dict:
        """读 → 浅合并 → 写；返回合并后的载荷（供「继承旧字段」用）。"""
        if not isinstance(patch, dict):
            raise TypeError(f"patch 必须是 dict，收到 {type(patch).__name__}")
        body = self.raw(conn, owner) or {}
        body.update(patch)
        self.put(conn, owner, body, stamp=stamp)
        return body

    def drop(self, conn, owner) -> int:
        """按 owner 删行，返回受影响行数。"""
        return self.repo.delete(conn, owner)

    # ------------------------------------------------------------ 清扫
    def sweep(self, conn, *, now, ttl, keep=None, on_expire=None) -> list:
        """全表扫过期 → `[(owner, 过期时的载荷)]`（表序）。

        `keep(owner, payload)` 为真者**只打标不删**（内存存活优先的注入口）；
        为假者 `on_expire` 之后删行。JSON 坏值的行**保守不动**（不猜、不删）。
        """
        self._require_stamp(ttl)
        out = []
        for row in self.repo.all(conn):
            payload = self._payload_of(row)
            if payload is None:
                continue
            stamp = self._stamp_of_row(row)
            if not stamp or now - stamp <= ttl:
                continue
            owner = row.get(self.spec.owner)
            out.append((owner, dict(payload)))
            self._expire_row(conn, owner, payload, keep=keep, on_expire=on_expire)
        return out

    def owners(self, conn, *, prefix=None) -> list:
        """列全部 owner（`prefix` 给了就按前缀过滤；前缀是内容协议，引擎不解释）。"""
        sql = f"SELECT {self.spec.owner} FROM {self.spec.table}"
        params = ()
        if prefix is not None:
            sql += f" WHERE {self.spec.owner} LIKE ?"
            params = (str(prefix) + "%",)
        return [r[0] for r in conn.execute(sql, params).fetchall()]

    def count(self, conn) -> int:
        return int(conn.execute(
            f"SELECT COUNT(*) FROM {self.spec.table}").fetchone()[0])
