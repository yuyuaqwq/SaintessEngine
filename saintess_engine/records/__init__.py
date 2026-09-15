# -*- coding: utf-8 -*-
"""资料表读口 —— 域 JSON → 只读资料表 + 索引 + 查询原语（引擎零字段知识）。

**为什么有它**：包内十几处各自重复同样四件事 ——

  ① **读域文件**：`<root>/<sub>/<域>.json`，缺文件 / 坏 JSON / 顶层不是映射 → 空表（不抛）；
  ② **键型还原**：JSON 只有字符串键，真源却按 `int` 查 —— 不还原 = 恒取缺省 = **静默错值**；
  ③ **顺序声明**：落盘顺序是字典序（导出契约要幂等），真源是插入序 —— 不声明 = 顺序悄悄漂移；
  ④ **建索引 / 分组 / 过滤 / 投影**：按某字段查一条、分组、谓词过滤、逐条变换。

本形状把这四件事收成一处，各处只声明「哪张表、什么键型、什么序、剥哪些字段」。

**用法**::

    from saintess_engine.records import Records, RecordsSet

    rows = Records(pkg_dir, "roster", sub="data", key_type=int,
                   order=(1, 2, 3), drop=("_injected",))
    rows.load()                    # 幂等；缺文件 / 坏 JSON → {}（不抛，missing 为 True）
    rows.missing                   # True = 空表（fail-closed 用）
    rows.problems                  # 显式降级留痕（空 = 干净）
    rows.all()                     # {id: 字段 dict}（保序）
    rows.get(3)                    # by id（键型已还原）
    rows.by("name", "alice")       # 单字段索引（惰性建；重名取表序首个）
    rows.group_by("kind")          # {字段值: {id: 条目}}
    rows.where(lambda e: e["n"] > 1)   # 谓词过滤（保序）
    rows.index_of("name")          # {字段值: [id]}（**重名收全**）
    rows.into(dict)                # {id: factory(条目)}（保序保键）

    bag = RecordsSet(pkg_dir, {
        "roster": {"key_type": int, "order": (1, 2, 3)},
        "grade":  {"sub": "rules"},
    })
    bag.roster.get(3)              # 惰性读 + 缓存
    bag.grade.missing
    bag.missing_domains()          # 读不到的域（fail-closed 面）
    bag.unknown                    # AttributeError：未声明的域**不建空壳**

**零知识**：引擎不认任何具体域、字段、条目含义 —— `domain` / `field` / `order` / `drop` /
`key_type` / 谓词 / `factory` 全由内容侧给；本形状不猜字段语义、不改写字段值。

**顺序是内容**：`order` 是内容侧的插入序声明。给了它就**按它排**；`set(order) != set(表)`
（多一条 / 少一条 / 声明里有重复键）→ `RecordsOrderMismatch` —— **不静默改序、不静默漏项**。

**fail-closed**（没有静默吞掉的路径）::

    域文件缺失 / 坏 JSON / 顶层不是映射  → 显式降级为空表：`missing` 为 True + 原因进 `problems`（不抛）
    顺序声明与域不符 / 声明有重复键      → 抛 `RecordsOrderMismatch`（表不发布，`missing` 仍为 True）
    条目被 `drop` 剥空                   → 移除该条目 + 留痕（不留空壳）
    索引时条目缺字段 / 值为 None / 不可哈希 → 不参与索引 + 留痕（查询期不抛）

**有意不做的事**
----------------
* **不做写入**：资料表只读。`all()` / `index_of()` 返回**内部表本身**（引擎不为十几个读口各留
  一份副本）；调用方不得就地改。
* **不做字段默认值**：`key_type` 还原不了的键**原样保留**（不丢、不猜）；条目缺字段就是不参与
  索引，引擎不替内容侧补 `None`。
* **不给 `factory` 传 id**：`into` 只把**条目**交给 `factory` —— `factory` 的签名只有一种，
  不靠参数嗅探分叉；需要 id 的变换自己遍历 `all()`。
* **不做缓存失效**：`load()` 只读一次（幂等）。域文件改了要重读 = 新建一个 `Records`。
* **不做多域装配猜测**：`RecordsSet` 只认 `spec` 里声明过的域；没声明的域**报错**（不建空壳、
  不静默给空表）。
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable, Iterable, Optional

__all__ = ["Records", "RecordsSet", "RecordsOrderMismatch"]

_UNSET: Any = object()


class RecordsOrderMismatch(RuntimeError):
    """顺序声明的条数/成员与域不符时抛（**不许静默改序**）。"""


class Records:
    """一个域 = 一张只读资料表（id → 字段 dict）+ 索引 + 查询原语。引擎零字段知识。

    `root` / `domain` / `sub` 定位文件 `<root>/<sub>/<domain>.json`，顶层是 `{id: {...}}`。
    `key_type` 是**键还原目标**（`int` = 把 `"3"` 还原成 `3`；还原不了的原样保留）。
    `order` 是插入序声明（给了就按它排 + 集合守卫）。`drop` 是剥掉的注入型字段。
    `default` 是查询未命中时的返回值（`get` / `by` 用；也可在调用点覆盖）。
    """

    def __init__(self, root, domain, *, sub: str = "data",
                 key_type: Callable = str,
                 order: Optional[Iterable] = None,
                 drop: Iterable = (),
                 default: Any = None) -> None:
        self.root = root
        self.domain = domain
        self.sub = sub
        self.key_type = key_type
        self.order = tuple(order) if order is not None else None
        self.drop = tuple(drop or ())
        self.default = default
        #: 显式降级留痕（空列表 = 干净）。读/建索引期的每一次「显式降级」都会写一条。
        self.problems: list = []
        self._table: dict = {}
        self._indices: dict = {}
        self._loaded = False

    # ------------------------------------------------------------ 定位 / 读
    @property
    def path(self) -> str:
        """域文件路径（`<root>/<sub>/<domain>.json`）。"""
        return os.path.join(self.root, self.sub, "%s.json" % (self.domain,))

    def _read(self):
        """读域文件 → `(数据, 留痕)`；读不了 → `(None, 原因)`（**不抛**）。"""
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return None, "域文件不存在：%s → 空表" % (self.path,)
        except Exception as exc:                                  # noqa: BLE001
            return None, "域文件读不了 / 坏 JSON：%s（%s: %s）→ 空表" % (
                self.path, type(exc).__name__, exc)
        if not isinstance(data, dict):
            return None, "域顶层不是 {id: 字段 dict} 映射：%s（是 %s）→ 空表" % (
                self.path, type(data).__name__)
        return data, None

    def _restore_keys(self, raw: dict) -> dict:
        """键型还原（**与包内 `_int_keys` 同口径**：还原不了的键原样保留，不静默丢）。"""
        out: dict = {}
        for k, v in raw.items():
            try:
                out[self.key_type(k)] = v
            except (TypeError, ValueError):
                out[k] = v
        return out

    def _apply_drop(self, table: dict) -> dict:
        """剥掉注入型字段（整键移除，**其余字段及其顺序原样**）。

        条目被剥空（原本非空、剥完全空）→ 移除该条目并留痕（**不留空壳**；少一条不静默）。
        """
        if not self.drop:
            return table
        dropped = frozenset(self.drop)
        out: dict = {}
        for k, ent in table.items():
            if not isinstance(ent, dict):
                out[k] = ent                                   # 非映射条目原样（引擎不认识形状）
                continue
            kept = {fk: fv for fk, fv in ent.items() if fk not in dropped}
            if ent and not kept:
                self.problems.append(
                    "%s[%r]：条目全部字段都在 drop=%r 里 → 已移除条目（不留空壳）"
                    % (self.domain, k, list(self.drop)))
                continue
            out[k] = kept
        return out

    def _check_order(self, table: dict) -> None:
        """顺序声明守卫：多一条 / 少一条 / 声明重复键 → `RecordsOrderMismatch`。"""
        keys = list(self.order)
        if len(set(keys)) != len(keys):
            raise RecordsOrderMismatch(
                "%s：顺序声明有重复键（%d 条 / %d 个不同）—— 拒绝静默取首个"
                % (self.domain, len(keys), len(set(keys))))
        have = set(table)
        want = set(keys)
        miss = [k for k in keys if k not in have]              # 声明里有、域里没有
        extra = [k for k in table if k not in want]            # 域里有、声明里没有
        if miss or extra:
            raise RecordsOrderMismatch(
                "%s：域键集与顺序声明不一致（声明有域没有 %d 条 %r / 域有声明没有 %d 条 %r）"
                "—— 拒绝静默改序、拒绝静默漏项"
                % (self.domain, len(miss), miss[:5], len(extra), extra[:5]))

    def load(self) -> "Records":
        """读表（幂等：只读一次）。

        缺文件 / 坏 JSON / 顶层不是映射 → 空表（**不抛**，`missing` 为 True，原因进 `problems`）。
        顺序声明与域不符 / 声明有重复键 → **抛** `RecordsOrderMismatch`（表不发布，`missing`
        仍为 True；原因也进 `problems`）。空表不做顺序守卫（与包内 `_ordered` 同口径）。
        """
        if self._loaded:
            return self
        self._loaded = True
        raw, problem = self._read()
        if problem is not None:
            self.problems.append(problem)
            self._table = {}
            return self
        table = self._apply_drop(self._restore_keys(raw))
        if self.order is not None and table:
            try:
                self._check_order(table)
            except RecordsOrderMismatch as exc:
                self.problems.append(str(exc))
                self._table = {}
                raise
            table = {k: table[k] for k in self.order}
        self._table = table
        return self

    # ------------------------------------------------------------ 表
    @property
    def missing(self) -> bool:
        """空表（供 fail-closed 用）：域读不到 / 坏 JSON / 顺序不符 → True。"""
        self.load()
        return not self._table

    def all(self) -> dict:
        """整张表 `{id: 字段 dict}`（**保序**；返回内部表本身，不得就地改）。"""
        self.load()
        return self._table

    def get(self, key, default: Any = _UNSET):
        """按 id 取条目（`key` 按 `key_type` 还原后的形态传；未命中 → `default`）。"""
        self.load()
        fallback = self.default if default is _UNSET else default
        try:
            return self._table[key]
        except KeyError:
            return fallback

    # ------------------------------------------------------------ 索引 / 查询
    def _index(self, field) -> dict:
        """`{字段值: [id]}`（惰性建 + 缓存；重名收全，值序 = 表序）。

        条目缺该字段 / 值为 `None` / 非映射 / 值不可哈希 → **不参与索引**，并留痕一条
        （查询期不抛、不猜默认值）。
        """
        if field in self._indices:
            return self._indices[field]
        idx: dict = {}
        skipped = 0
        for k, ent in self._table.items():
            if not isinstance(ent, dict) or field not in ent or ent[field] is None:
                skipped += 1
                continue
            try:
                idx.setdefault(ent[field], []).append(k)
            except TypeError:                                  # 值不可哈希
                skipped += 1
        if skipped:
            self.problems.append(
                "%s：建 %r 索引时跳过 %d 条（缺字段 / 值为 None / 非映射 / 不可哈希）"
                % (self.domain, field, skipped))
        self._indices[field] = idx
        return idx

    def by(self, field, value, default: Any = _UNSET):
        """单字段索引查一条（未命中 → `default`）。

        重名（同一字段值对应多条）→ 取**表序首个**；要全部用 `index_of(field)`。
        """
        self.load()
        fallback = self.default if default is _UNSET else default
        key = field
        try:
            ids = self._index(key).get(value)
        except TypeError:                                      # value 不可哈希 → 必然查不到
            return fallback
        if not ids:
            return fallback
        return self._table.get(ids[0], fallback)

    def group_by(self, field) -> dict:
        """按字段值分组 `{字段值: {id: 条目}}`（组序 = 首见序，组内 = 表序）。"""
        self.load()
        return {v: {k: self._table[k] for k in ids} for v, ids in self._index(field).items()}

    def where(self, pred: Callable) -> dict:
        """谓词过滤 `{id: 条目}`（**保序**）；谓词收条目本身。"""
        self.load()
        return {k: v for k, v in self._table.items() if pred(v)}

    def index_of(self, field) -> dict:
        """`{字段值: [id]}`（**重名收全**；值序 = 表序；返回内部索引本身，不得就地改）。"""
        self.load()
        return self._index(field)

    def into(self, factory: Callable) -> dict:
        """逐条变换 `{id: factory(条目)}`（保序保键；`factory` 只收条目，不收 id）。"""
        self.load()
        return {k: factory(v) for k, v in self._table.items()}

    def __repr__(self) -> str:  # pragma: no cover - 调试用（不触发 load，repr 不许抛）
        return "Records(%s/%s/%s, key_type=%s, order=%s, loaded=%s, n=%d)" % (
            self.root, self.sub, self.domain,
            getattr(self.key_type, "__name__", self.key_type),
            "无" if self.order is None else len(self.order),
            self._loaded, len(self._table))


class RecordsSet:
    """一组域 = 一个 `RecordsSet`：`spec = {域: {sub/key_type/order/drop/default}}`。

    `rs.<域>` 惰性建 + 缓存 `Records` 并 `load()`；**未声明的域报 `AttributeError`**
    （不建空壳、不静默给空表）。`missing_domains()` 是 fail-closed 面：哪几个声明过的域读不到。
    """

    def __init__(self, root, spec: dict) -> None:
        self._root = root
        self._spec = {str(d): dict(cfg or {}) for d, cfg in dict(spec or {}).items()}
        self._tables: dict = {}

    def __getattr__(self, domain):
        if domain.startswith("_"):
            raise AttributeError(domain)
        obj = object.__getattribute__(self, "__dict__")
        spec = obj.get("_spec") or {}
        if domain not in spec:
            raise AttributeError(
                "RecordsSet：未声明的域 %r —— 不建空壳（已声明：%r）"
                % (domain, sorted(spec)))
        tables = obj["_tables"]
        if domain not in tables:
            tables[domain] = Records(obj["_root"], domain, **spec[domain])
        return tables[domain].load()

    def missing_domains(self) -> list:
        """声明过的域里读不到的（缺文件 / 坏 JSON / 顺序不符，即 `Records.missing`）。"""
        return sorted(d for d in self._spec if getattr(self, d).missing)

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return "RecordsSet(domains=%r)" % (sorted(self._spec),)
