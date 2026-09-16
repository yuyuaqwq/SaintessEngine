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
    rows.reload()                  # 显式重载（原子换引用）→ {"roster": {"before": 3, "after": 4}}

    bag = RecordsSet(pkg_dir, {
        "roster": {"key_type": int, "order": (1, 2, 3)},
        "grade":  {"sub": "rules"},
    })
    bag.roster.get(3)              # 惰性读 + 缓存
    bag.grade.missing
    bag.missing_domains()          # 读不到的域（fail-closed 面）
    bag.unknown                    # AttributeError：未声明的域**不建空壳**
    bag.reload_all()               # 全部表一起重载（一份失败 → 一张也不换）
                                   # → {"roster": {"roster": {"before": 3, "after": 4}}, "grade": ...}

**包内域声明派生**（包布局的元数据只有一个源：`<pkg>/editor/domains.json`）::

    from saintess_engine.records import set_from_domains, orders_of

    bag = set_from_domains(pkg_dir, ("roster", "grade"),
                           overrides={"roster": {"key_type": int, "order": (1, 2, 3)}})
    # 落点 sub 由声明的 kind 派生（data→content/data，rules→content/rules）；
    # 声明缺项 / 文件缺 / 声明与磁盘不符 → RecordsDeclarationError（点名域与实际路径）。
    keys = orders_of(pkg_dir, "roster_first", domain="key_order")   # 命名序声明（可多段拼接）

**零知识**：引擎不认任何具体域、字段、条目含义 —— `domain` / `field` / `order` / `drop` /
`key_type` / 谓词 / `factory` 全由内容侧给；本形状不猜字段语义、不改写字段值。

**顺序是内容**：`order` 是内容侧的插入序声明。给了它就**按它排**；`set(order) != set(表)`
（多一条 / 少一条 / 声明里有重复键）→ `RecordsOrderMismatch` —— **不静默改序、不静默漏项**。

**fail-closed**（没有静默吞掉的路径）::

    域文件缺失 / 坏 JSON / 顶层不是映射  → 显式降级为空表：`missing` 为 True + 原因进 `problems`（不抛）
    顺序声明与域不符 / 声明有重复键      → 抛 `RecordsOrderMismatch`（表不发布，`missing` 仍为 True）
    条目被 `drop` 剥空                   → 移除该条目 + 留痕（不留空壳）
    索引时条目缺字段 / 值为 None / 不可哈希 → 不参与索引 + 留痕（查询期不抛）

**显式重载**（数据热更）::

    rows.reload()                  # 重新读盘 → **原子换引用**（全部读好、解析好、守卫过才换）
    bag.reload_all()               # 本集合全部表：先全部读好，再**一起**换（一份失败 → 一张也不换）

**跨集合重载（注册表）**::

    sets()                         # 已登记的 RecordsSet（**构建序**；返回副本）
    reload_all_sets()              # 全部已登记集合：先全部读好，再一起换（一张失败 → 一张也不换）
                                   # → {"RecordsSet#0[roster]": {"roster": {"before": 3, "after": 4}}}

* **自动登记**：`RecordsSet.__init__` 里弱引用登记 —— 调用方不用写任何登记代码；集合被回收，
  登记随之消失（**不强引用，不泄漏**）。
* 只由调用方触发：**不做自动 mtime 检查、不做自动失效**（热路径 stat 开销 + 阻塞 event loop +
  半写风险）—— 什么时候重读是宿主的决定。
* 任一步失败（读不到 / 坏 JSON / 顶层不是映射 / 顺序守卫不过）→ `RecordsReloadError`
  （点名域与原因）；**不替换、旧数据继续可读**（fail-closed：不许静默降级）。
* 成功返回变更摘要 `{"<域>": {"before": 旧条数, "after": 新条数}}` —— **没有变化的域也在**
  （供宿主打日志）。

**有意不做的事**
----------------
* **不做写入**：资料表只读。`all()` / `index_of()` 返回**内部表本身**（引擎不为十几个读口各留
  一份副本）；调用方不得就地改。
* **不做字段默认值**：`key_type` 还原不了的键**原样保留**（不丢、不猜）；条目缺字段就是不参与
  索引，引擎不替内容侧补 `None`。
* **不给 `factory` 传 id**：`into` 只把**条目**交给 `factory` —— `factory` 的签名只有一种，
  不靠参数嗅探分叉；需要 id 的变换自己遍历 `all()`。
* **不做自动失效**：`load()` 只读一次（幂等）；域文件改了要生效 = 调用方**显式** `reload()` /
  `reload_all()`（引擎不看 mtime、不自己决定时机）。
* **不做多域装配猜测**：`RecordsSet` 只认 `spec` 里声明过的域；没声明的域**报错**（不建空壳、
  不静默给空表）。
"""
from __future__ import annotations

import json
import os
import weakref
from typing import Any, Callable, Iterable, Optional

__all__ = ["Records", "RecordsSet", "RecordsOrderMismatch", "RecordsReloadError",
           "sets", "reload_all_sets",
           "RecordsDeclarationError", "read_domain_decl", "domain_sub",
           "resolve_domain", "records_from_domain", "set_from_domains", "orders_of",
           "DEFAULT_DECL", "DEFAULT_KIND_DIRS"]

_UNSET: Any = object()

#: 已登记集合的**弱**引用（构建序）—— 集合被回收，登记随之消失（不强引用、不泄漏）。
_REGISTRY: list = []


def _register(rs: "RecordsSet") -> None:
    """自动登记一个集合（`RecordsSet.__init__` 调用；包作者不用写登记代码）。"""
    _REGISTRY.append(weakref.ref(rs))


def sets() -> list:
    """已登记的 `RecordsSet`（**构建序**；返回副本，不是内部容器）。

    已回收的登记顺手清掉（弱引用语义：集合没了，登记就不该留着）。
    """
    live = []
    for ref in list(_REGISTRY):
        rs = ref()
        if rs is not None:
            live.append(rs)
    if len(live) != len(_REGISTRY):
        _REGISTRY[:] = [ref for ref in _REGISTRY if ref() is not None]
    return live


def _label(index: int, rs: "RecordsSet") -> str:
    """集合在结果里的标识：注册序 + 声明域（集合没有名字，这两个够唯一且可读）。"""
    return "RecordsSet#%d[%s]" % (index, ",".join(rs._spec))


def reload_all_sets() -> dict:
    """重载**全部已登记集合**的全部表（**跨集合全有或全无**）。

    先把所有集合的所有表 `_prepare()` 好，再一起 `_commit()`：任一张失败 → 抛
    `RecordsReloadError`（点名域与原因），**一张也不替换**（所有集合保持重载前状态）。
    返回 `{集合标识: {域: {"before": 旧条数, "after": 新条数}}}`；**零集合 → `{}`**（不是报错）。
    """
    live = sets()
    if not live:
        return {}
    # 预热：先把各集合**当前**的表读起来，让下面 `_prepare()` 记的 `before` 是「进程此刻真正在用的条数」。
    # 不预热 ⇒ 没读过的集合 `before` 恒为 0，报告里会出现「0 → N」的**假变化**（GM 据此看不出到底变没变）。
    # `Records.load()` 幂等（只读一次），故这里对已读过的集合是零成本。
    for rs in live:
        for domain in rs._spec:
            rs._records(domain).load()
    prepared = []
    for index, rs in enumerate(live):
        rows = []
        for domain in rs._spec:
            rec = rs._records(domain)
            rows.append((rec,) + rec._prepare())        # 失败：此时还没动过任何表
        prepared.append((_label(index, rs), rows))
    out: dict = {}
    for label, rows in prepared:
        per: dict = {}
        for rec, table, problems in rows:
            per.update(rec._commit(table, problems))
        out[label] = per
    return out


class RecordsOrderMismatch(RuntimeError):
    """顺序声明的条数/成员与域不符时抛（**不许静默改序**）。"""


class RecordsReloadError(RuntimeError):
    """重载失败：点名域与原因；调用方数据保持重载前的状态（**不替换、旧数据继续可用**）。

    `domain` = 出错的域；`reason` = 人读原因；`problems` = 失败前已积累的显式降级留痕（可空）。
    """

    def __init__(self, domain: str, reason: str, *, problems=None) -> None:
        self.domain = domain
        self.reason = reason
        self.problems = list(problems or [])
        msg = "%s：重载失败（%s）—— 未替换，旧数据保持可用" % (domain, reason)
        if self.problems:
            msg += "；留痕 %d 条：%r" % (len(self.problems), self.problems[:3])
        super().__init__(msg)


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
        #: `(表, 索引)` —— **一次换引用**发布整版状态（读方只看旧的整版或新的整版）。
        self._state: tuple = ({}, {})
        self._loaded = False

    # ------------------------------------------------------------ 定位 / 读
    @property
    def path(self) -> str:
        """域文件路径（`<root>/<sub>/<domain>.json`）。"""
        return os.path.join(self.root, self.sub, "%s.json" % (self.domain,))

    @property
    def _table(self) -> dict:
        """当前表（与索引同处一份 `_state`，随它一起换）。"""
        return self._state[0]

    @property
    def _indices(self) -> dict:
        """当前索引缓存（随表一起换引用）。"""
        return self._state[1]

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

    def _apply_drop(self, table: dict, problems: Optional[list] = None) -> dict:
        """剥掉注入型字段（整键移除，**其余字段及其顺序原样**）。

        条目被剥空（原本非空、剥完全空）→ 移除该条目并留痕（**不留空壳**；少一条不静默）。
        `problems` 缺省写本对象留痕；重载的预备读法传自己的局部留痕（失败不污染旧状态）。
        """
        if not self.drop:
            return table
        log = self.problems if problems is None else problems
        dropped = frozenset(self.drop)
        out: dict = {}
        for k, ent in table.items():
            if not isinstance(ent, dict):
                out[k] = ent                                   # 非映射条目原样（引擎不认识形状）
                continue
            kept = {fk: fv for fk, fv in ent.items() if fk not in dropped}
            if ent and not kept:
                log.append(
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
            self._state = ({}, {})
            return self
        table = self._apply_drop(self._restore_keys(raw))
        if self.order is not None and table:
            try:
                self._check_order(table)
            except RecordsOrderMismatch as exc:
                self.problems.append(str(exc))
                self._state = ({}, {})
                raise
            table = {k: table[k] for k in self.order}
        self._state = (table, {})
        return self

    # ------------------------------------------------------------ 重载
    def _prepare(self) -> tuple:
        """读 + 键还原 + 剥字段 + 顺序守卫 → `(新表, 新留痕)`；任一步失败 → `RecordsReloadError`。

        **只读盘、只建新对象**：失败时本对象的表 / 索引 / 留痕 / `_loaded` 全都不动（fail-closed）。
        """
        raw, problem = self._read()
        if problem is not None:
            raise RecordsReloadError(self.domain, problem)
        problems: list = []
        table = self._apply_drop(self._restore_keys(raw), problems)
        if self.order is not None and table:
            try:
                self._check_order(table)
            except RecordsOrderMismatch as exc:
                raise RecordsReloadError(self.domain, str(exc), problems=problems) from exc
            table = {k: table[k] for k in self.order}
        return table, problems

    def _commit(self, table: dict, problems: list) -> dict:
        """发布新表（**一次换引用**）→ 该域的变更摘要 `{"<域>": {"before": N, "after": M}}`。"""
        before = len(self._table)
        self._state = (table, {})
        self.problems = problems
        self._loaded = True
        return {self.domain: {"before": before, "after": len(table)}}

    def reload(self) -> dict:
        """按当前声明重新读表（**原子**：全部读好、解析好、守卫过才整体换引用）。

        返回 `{"<域>": {"before": 旧条数, "after": 新条数}}`（**含未变化项**：before == after 也在）。
        任一步失败（读不到 / 坏 JSON / 顶层不是映射 / 顺序守卫不过）→ 抛 `RecordsReloadError`
        （点名域与原因），**内部数据保持重载前的状态**（旧表、旧索引、旧留痕都继续可用）。
        """
        table, problems = self._prepare()
        return self._commit(table, problems)

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
        _register(self)

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

    # ------------------------------------------------------------ 重载
    def _records(self, domain) -> "Records":
        """取（或建）域对象，**不触发 `load()`**（重载走自己的读盘路径）。"""
        obj = object.__getattribute__(self, "__dict__")
        tables = obj["_tables"]
        if domain not in tables:
            tables[domain] = Records(obj["_root"], domain, **obj["_spec"][domain])
        return tables[domain]

    def reload_all(self) -> dict:
        """重载本集合内全部表（**全有或全无**：先全部读好、解析好，再一起换引用）。

        返回 `{表名: 该表的 reload() 结果}`。任一张失败 → 抛 `RecordsReloadError`（点名该域），
        **一张也不替换**（所有表保持重载前的状态；未读过的域也会读入）。
        """
        prepared = []
        for domain in self._spec:
            rec = self._records(domain)
            prepared.append((rec,) + rec._prepare())       # 失败：此时还没动过任何表
        out: dict = {}
        for rec, table, problems in prepared:
            out[rec.domain] = rec._commit(table, problems)
        return out

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return "RecordsSet(domains=%r)" % (sorted(self._spec),)


# ============================================================
# 包内域声明派生（`<pkg>/editor/domains.json` = 域元数据的**唯一源**）
# ============================================================
# 为什么有它：包内十几个模块各自抄一遍「域 id + 落点 + kind + 文件名」的元数据 ——
# 同一张域在两处写法不一致时，装载期**看不出来**（两边都读得到文件），直到行为漂移。
# 本段把「域 id → 落点子目录」的推导收成一处：调用方只声明**我要哪些域**，
# 落点由包内域声明的 `kind` 派生，且**声明缺项 / 文件缺 / 声明与磁盘不符一律报错**。

#: 包内域声明的默认相对路径（内容侧约定；引擎只读调用方给的那一份，不猜别处）。
DEFAULT_DECL = "editor/domains.json"
#: `kind` → 落点子目录（内容侧布局约定，调用方可覆盖；引擎不写死某个包的布局）。
DEFAULT_KIND_DIRS = {"data": "content/data", "rules": "content/rules"}


class RecordsDeclarationError(RuntimeError):
    """包内域声明 / 磁盘落点与声明不符时抛（fail-closed：不静默给空表、不猜路径）。"""


def _kind_dirs(kind_dirs=None) -> dict:
    dirs = dict(DEFAULT_KIND_DIRS)
    if kind_dirs:
        dirs.update(kind_dirs)
    return dirs


def read_domain_decl(pkg_root, *, decl: str = DEFAULT_DECL) -> dict:
    """读包内域声明（`<pkg>/<decl>`，默认 `editor/domains.json`）→ `{域: 声明 dict}`。

    缺文件 / 坏 JSON / 顶层不是非空映射 → `RecordsDeclarationError`（**不静默空表**）。
    """
    path = os.path.join(pkg_root, decl)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise RecordsDeclarationError("包内域声明文件不存在：%s" % (path,))
    except Exception as exc:                                  # noqa: BLE001
        raise RecordsDeclarationError(
            "包内域声明读不了 / 坏 JSON：%s（%s: %s）" % (path, type(exc).__name__, exc))
    if not isinstance(data, dict) or not data:
        raise RecordsDeclarationError(
            "包内域声明顶层不是非空映射：%s（是 %s）" % (path, type(data).__name__))
    return data


def domain_sub(entry, domain: str, *, kind_dirs=None) -> str:
    """一条域声明的 `kind` → 落点子目录（缺 kind / 未知 kind → `RecordsDeclarationError`）。"""
    dirs = _kind_dirs(kind_dirs)
    kind = entry.get("kind") if isinstance(entry, dict) else None
    if not isinstance(kind, str) or not kind:
        raise RecordsDeclarationError("域 %r 的声明缺 kind（无法派生落点）" % (domain,))
    if kind not in dirs:
        raise RecordsDeclarationError(
            "域 %r 的 kind=%r 没有对应落点（已知 kind → %r）" % (domain, kind, sorted(dirs)))
    return dirs[kind]


def resolve_domain(pkg_root, domain: str, *, decl: str = DEFAULT_DECL,
                   kind_dirs=None, declaration: Optional[dict] = None) -> str:
    """**声明 → 磁盘**的单域校验：返回落点子目录；任一不满足即 `RecordsDeclarationError`。

    ① 域在声明里（声明缺项 → 报错，不静默）；
    ② 声明带 `kind` 且 kind 有落点；
    ③ `<pkg>/<落点>/<域>.json` 在盘上（缺文件 → 报错，**不静默给空表**）；
    ④ 声明与磁盘不符（同名文件落在**别的** kind 目录）→ 单独点名「表名与域不符」。
    """
    decl_table = read_domain_decl(pkg_root, decl=decl) if declaration is None else declaration
    if domain not in decl_table:
        raise RecordsDeclarationError(
            "域 %r 不在包内域声明里（%s）—— 声明缺项，拒绝装载（不静默给空表）"
            % (domain, os.path.join(pkg_root, decl)))
    sub = domain_sub(decl_table[domain], domain, kind_dirs=kind_dirs)
    path = os.path.join(pkg_root, sub, "%s.json" % (domain,))
    if not os.path.isfile(path):
        elsewhere = sorted(
            d for d in set(_kind_dirs(kind_dirs).values())
            if d != sub and os.path.isfile(os.path.join(pkg_root, d, "%s.json" % (domain,))))
        if elsewhere:
            raise RecordsDeclarationError(
                "域 %r 的落点与声明不符：声明 kind=%r ⇒ %s，同名文件却在 %r —— "
                "表名与域不符（改声明或搬文件，不静默）"
                % (domain, decl_table[domain].get("kind"), path, elsewhere))
        raise RecordsDeclarationError(
            "域 %r 声明的文件不在盘上：%s —— 缺表即报错，不许静默给空表" % (domain, path))
    return sub


def records_from_domain(pkg_root, domain: str, *, decl: str = DEFAULT_DECL, kind_dirs=None,
                        **cfg) -> "Records":
    """单个域 → `Records`（同 `set_from_domains` 的 fail-closed 校验；**不登记集合**）。

    `cfg` 是调用方自己的派生参数（`order` / `drop` / `key_type` / `default`）；
    `sub` 不许给：落点由声明的 `kind` 派生。
    """
    if "sub" in cfg:
        raise RecordsDeclarationError(
            "域 %r 的 cfg 里给了 sub —— 落点由声明的 kind 派生，不许手抄" % (domain,))
    sub = resolve_domain(pkg_root, domain, decl=decl, kind_dirs=kind_dirs)
    return Records(pkg_root, domain, sub=sub, **cfg)


def set_from_domains(pkg_root, domains, *, decl: str = DEFAULT_DECL, kind_dirs=None,
                     overrides: Optional[dict] = None) -> "RecordsSet":
    """包内域声明 + 磁盘 → `RecordsSet`（通用、零游戏知识、fail-closed）。

    * `domains`：本模块**要哪些域**（域 id 序列，如 `("items", "game_config")`）。
    * `overrides`：`{域: {order/drop/key_type/default}}` —— **本模块自己的派生参数**
      （内容侧声明的一部分，不是域元数据）。`sub` **不许在这里给**：落点一律由声明的
      `kind` 派生（手抄 `sub` = 又一处会漂的元数据）。
    * `decl` / `kind_dirs`：包布局约定，package 侧可覆盖（引擎不写死某个包）。

    每条域都过 `resolve_domain` 的四道校验（见其文档）；任一不满足即
    `RecordsDeclarationError`（点名域与实际路径）。
    """
    declaration = read_domain_decl(pkg_root, decl=decl)
    overrides = dict(overrides or {})
    spec: dict = {}
    for name in domains:
        sub = resolve_domain(pkg_root, name, decl=decl, kind_dirs=kind_dirs,
                             declaration=declaration)
        cfg = dict(overrides.pop(name, None) or {})
        if "sub" in cfg:
            raise RecordsDeclarationError(
                "域 %r 的 overrides 里给了 sub —— 落点由声明的 kind 派生，不许手抄" % (name,))
        cfg["sub"] = sub
        spec[name] = cfg
    if overrides:
        raise RecordsDeclarationError(
            "overrides 里有**没有请求**的域：%r（不静默忽略）" % (sorted(overrides),))
    return RecordsSet(pkg_root, spec)


def orders_of(pkg_root, *names, domain: str, decl: str = DEFAULT_DECL,
              kind_dirs=None) -> list:
    """按名读包内**序声明**：`<pkg>/<domain 落点>/<domain>.json[名]["keys"]`（可多段拼接）。

    序声明是内容（「这张表的源迭代序」），不是引擎概念：域 id / 条目名都由调用方给，
    引擎只负责「按声明的落点读、按名取、形状不对就炸」。

    fail-closed（任一不满足即 `RecordsDeclarationError`，点名声与路径）：
    声明域不在域声明里 / 落点文件不在盘上 / 文件读不到 / 条目缺 / 形状不是 `{keys: [...]}`。
    """
    if not names:
        raise RecordsDeclarationError("orders_of 至少要一个序声明名")
    sub = resolve_domain(pkg_root, domain, decl=decl, kind_dirs=kind_dirs)
    path = os.path.join(pkg_root, sub, "%s.json" % (domain,))
    rec = Records(pkg_root, domain, sub=sub)
    table = rec.all()
    if rec.missing:
        raise RecordsDeclarationError(
            "序声明域 %r 读不到内容：%s（留痕：%r）" % (domain, path, rec.problems[:3]))
    out: list = []
    for name in names:
        ent = table.get(name)
        keys = ent.get("keys") if isinstance(ent, dict) else None
        if not isinstance(keys, list) or not keys:
            raise RecordsDeclarationError(
                "序声明 %r 缺条目 / 形状不是 {keys: [...]}（域 %r，%s）—— "
                "序读不到不许静默空表" % (name, domain, path))
        out.extend(keys)
    return out
