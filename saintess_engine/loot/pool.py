# -*- coding: utf-8 -*-
"""掉落池 —— 池集合 + 策略注册表 + 唯一入口 `roll()` / 展开 `expand()` / 结构审计 `audit()`。

**形状在哪**：一个池就是「说出什么」的一段数据；怎么从池里取（带权摸一个 / 多层概率表 /
互斥档 / 固定清单）是**策略**，可以注册任意多个。把池里的内容（物品、装备、金币…）拿掉，
只留 `key` / `w` / `n` / `ref` 这些**结构字段**，逻辑照旧成立。

**绑定由内容给**（引擎零知识）::

    t = LootTable(
        pools,                                   # {池key: 池数据}
        resolver=my_resolver,                    # ref → 实物（引擎只调它，不认识前缀）
        strategies={"fish": my_fish},            # 自定义策略（覆盖/新增内置）
        inline_prefixes=("gold:", "item:"),      # 哪些前缀算「内联引用」
        pool_key_prefixes=("weighted:",),        # 子池引用里可能出现的前缀
        special_refs=("bp", "gem"),              # 特殊 ref（审计时跳过解析检查）
    )
    t.roll("gather:oak_plain", ctx, qty=2)       # 唯一入口；池不存在/抽空 → []（不抛错）
    t.expand("chest:wild_low")                   # 带权展开候选
    t.audit()                                    # 断链 / 空池 / 权重和 / 子池缺失

内置策略（都不含游戏词）：

| 名字 | 语义 | 数据 |
|---|---|---|
| `weighted` | 带权摸一个（`qty` 次），带等级窗口过滤与兜底钩子 | `entries[{item,w,n,min_lv,max_lv}]` |
| `fixed` | 全给（必掉清单） | `entries[{item,n}]` |
| `table` | 多层概率表：每行独立判定 | `rolls[{pool,chance,n}]` |
| `table_choice` | 互斥档：累计 `cutoff` 或按序首个命中的 `chance` | `rolls[{pool,cutoff|chance,n,fallback}]` |

`register_strategy(name, fn, …)` 注册自定义策略；`fn(pool, ctx, table) -> list[dict]`，
可以用 `table.resolve / table.roll_sub / table.sub_ctx / table.rng`。
"""
from __future__ import annotations

import copy
import random as _random

from .pick import pick_weighted, roll_range

# ───────────────────────────────────────────────────────── 策略注册表
# spec = {"fn": callable, "doc": str, "uses": "entries"|"rolls",
#         "needs_weights": bool, "expand": callable|None}
STRATEGIES: dict = {}


def register_strategy(name: str, fn, *, doc: str = "", uses: str = "entries",
                      needs_weights: bool = False, expand=None, replace: bool = False):
    """注册一个策略。重名默认报错（防静默覆盖）；要覆盖写 `replace=True`。"""
    if not isinstance(name, str) or not name:
        raise ValueError("策略名必须是非空字符串")
    if name in STRATEGIES and not replace:
        raise ValueError(f"策略已注册：{name}（要覆盖请显式 replace=True）")
    if not callable(fn):
        raise TypeError("策略必须可调用：fn(pool, ctx, table) -> list[dict]")
    if uses not in ("entries", "rolls", "none"):
        raise ValueError(f"uses 只能是 entries/rolls/none，收到 {uses!r}")
    STRATEGIES[name] = {"fn": fn, "doc": doc, "uses": uses,
                        "needs_weights": bool(needs_weights), "expand": expand}
    return fn


def strategy_names() -> tuple:
    return tuple(sorted(STRATEGIES))


def get_strategy(name: str):
    spec = STRATEGIES.get(name) or STRATEGIES["weighted"]
    return spec["fn"]


def strategy_spec(name: str) -> dict:
    return dict(STRATEGIES.get(name) or STRATEGIES["weighted"])


class SimpleCtx:
    """极简上下文：属性缺失一律 None（不抛 AttributeError），`hooks` 恒为 dict。

    「内容侧策略要什么字段」是内容的事 —— 引擎只提供一个宽容的袋子。
    """

    def __init__(self, **kw):
        self.__dict__.update(kw)
        self.hooks = kw.get("hooks") or {}

    def __getattr__(self, name):
        return None


# ───────────────────────────────────────────────────────── 内置策略

def _s_weighted(pool: dict, ctx, table) -> list:
    """带权抽取：抽 `ctx.qty` 次；等级窗口过滤；抽空走 `ctx.fallback_roll` 钩子。"""
    qty = int(getattr(ctx, "qty", 1) or 1)
    entries = pool.get("entries", [])
    lv = int(getattr(ctx, "player_level", 0) or getattr(ctx, "monster_lv", 0) or 0)
    cand = []
    for e in entries:
        min_lv = e.get("min_lv")
        max_lv = e.get("max_lv")
        if min_lv and lv and lv < int(min_lv):
            continue
        if max_lv and lv and lv > int(max_lv):
            continue
        cand.append(e)
    if not cand:
        return table.fallback(pool, ctx)
    out = []
    for _ in range(qty):
        pick = pick_weighted(cand, rng=table.rng)
        if pick:
            r = table.resolve(pick["item"], ctx)
            if r:
                r["count"] = r.get("count", 1) * int(pick.get("n", 1) or 1)
                out.append(r)
    return out


def _s_fixed(pool: dict, ctx, table) -> list:
    """固定掉落：entries 全给。"""
    out = []
    for e in pool.get("entries", []):
        r = table.resolve(e["item"], ctx)
        if r:
            r["count"] = r.get("count", 1) * int(e.get("n", 1) or 1)
            out.append(r)
    return out


def _s_table(pool: dict, ctx, table) -> list:
    """多层概率表：每行独立判定（`chance` 不中即跳过）。"""
    out = []
    for roll_cfg in pool.get("rolls", []):
        chance = float(roll_cfg.get("chance", 1.0))
        if chance < 1.0 and table.rng.random() >= chance:
            continue
        out.extend(table.roll_cfg(roll_cfg, ctx))
    return out


def _s_table_choice(pool: dict, ctx, table) -> list:
    """互斥档：一次只进一档。

    * `cutoff` 累计概率优先（末档 cutoff 不足 1.0 时容错兜底 —— 数据小瑕疵不吞奖励）
    * 否则按序首个命中的 `chance`
    """
    rolls = pool.get("rolls", [])
    if any("cutoff" in rc for rc in rolls):
        total = table.rng.random()
        acc = 0.0
        for i, rc in enumerate(rolls):
            acc += float(rc.get("cutoff", 0))
            if total < acc or i == len(rolls) - 1:
                return table.roll_cfg(rc, ctx)
        return []
    for rc in rolls:
        c = float(rc.get("chance", 0))
        if c > 0 and table.rng.random() < c:
            return table.roll_cfg(rc, ctx)
    return []


def _expand_weighted(pool: dict, table) -> list:
    """带权展开候选：`[item] × w`，单条权重上限 1000（防异常数据撑爆内存）。"""
    out = []
    for e in pool.get("entries", []):
        it = e.get("item", "")
        if not it:
            continue
        w = min(int(e.get("w", 1) or 1), 1000)
        out.extend([it] * w)
    return out


def _expand_fixed(pool: dict, table) -> list:
    return [e.get("item", "") for e in pool.get("entries", []) if e.get("item")]


def _expand_rolls(pool: dict, table) -> list:
    out = []
    for rc in pool.get("rolls") or []:
        sub = rc.get("pool", "")
        if sub in table.pools:
            out.extend(table.expand(sub))
        elif sub.startswith(tuple(table.inline_prefixes)):
            out.append(sub)
    return out


register_strategy("weighted", _s_weighted, uses="entries", needs_weights=True,
                  expand=_expand_weighted, doc="带权抽取：抽 qty 次，带等级窗口过滤与兜底钩子")
register_strategy("fixed", _s_fixed, uses="entries", expand=_expand_fixed, doc="固定掉落：entries 全给")
register_strategy("table", _s_table, uses="rolls", expand=_expand_rolls,
                  doc="多层概率表：每行独立判定（chance）")
register_strategy("table_choice", _s_table_choice, uses="rolls", expand=_expand_rolls,
                  doc="互斥档：累计 cutoff 或按序首个命中的 chance，一次只进一档")


# ───────────────────────────────────────────────────────── LootTable
class LootTable:
    """一张掉落表（池集合 + 引用解析器 + 策略）。构造后不可变；`roll()` 是唯一入口。"""

    def __init__(self, pools, *, resolver=None, strategies=None, inline_prefixes=(),
                 pool_key_prefixes=(), special_refs=(), rng=None, strict: bool = False,
                 fallback_attr: str = "fallback_roll"):
        self._pools = pools if pools is not None else {}
        self._resolver = resolver
        self._strategies = dict(STRATEGIES)
        for k, v in dict(strategies or {}).items():
            if callable(v):
                self._strategies[k] = {"fn": v, "doc": "", "uses": "entries",
                                       "needs_weights": False, "expand": None}
            else:
                spec = dict(STRATEGIES.get(k) or {})
                spec.update(v or {})
                self._strategies[k] = spec
        self.inline_prefixes = tuple(inline_prefixes)
        self.pool_key_prefixes = tuple(pool_key_prefixes)
        self.special_refs = frozenset(special_refs)
        self.rng = rng or _random
        self.strict = bool(strict)
        self.fallback_attr = fallback_attr

    # ────────────────────────────── 读
    @property
    def pools(self) -> dict:
        return self._pools

    def pool(self, pool_key) -> dict | None:
        """池对象（不存在 → None；`weighted:xxx` 这类前缀会先剥掉再查）。"""
        if pool_key in self._pools:
            return self._pools[pool_key]
        for p in self.pool_key_prefixes:
            if isinstance(pool_key, str) and pool_key.startswith(p):
                return self._pools.get(pool_key.split(":", 1)[1])
        return None

    def has_pool(self, pool_key) -> bool:
        return self.pool(pool_key) is not None

    def strategy_of(self, pool: dict) -> dict:
        return self._strategies.get(pool.get("type", "weighted")) or self._strategies["weighted"]

    def resolve(self, ref, ctx):
        """调内容侧解析器（未配置 → None，等于"这条出不来"）。"""
        if self._resolver is None:
            return None
        return self._resolver(ref, ctx)

    # ────────────────────────────── 抽取
    def sub_ctx(self, ctx, qty):
        """子池上下文：复制一份改 `qty`（不动原 ctx）；复制不了就改原对象。"""
        try:
            c = copy.copy(ctx)
            c.qty = qty
            return c
        except Exception:                                     # noqa: BLE001
            return ctx

    def fallback(self, pool, ctx, key: str = "fallback") -> list:
        """池抽空时的兜底钩子（`ctx.fallback_roll(pool, fallback声明, ctx)`）。"""
        fb = pool.get(key)
        hook = getattr(ctx, self.fallback_attr, None)
        if fb and callable(hook):
            try:
                return hook(pool, fb, ctx) or []
            except Exception:                                 # noqa: BLE001
                return []
        return []

    def roll_cfg(self, roll_cfg: dict, ctx, *, fallback_key: str = "fallback",
                 fallback_n_key: str = "fallback_n") -> list:
        """抽一行 roll 配置（`{pool, n, fallback, fallback_n}`）——`table*` 策略的基本单元。"""
        sub = roll_cfg.get("pool", "")
        qty = roll_range(roll_cfg.get("n"), rng=self.rng)
        res = self.roll_sub(sub, ctx, qty)
        if not res and roll_cfg.get(fallback_key):
            fb = roll_cfg[fallback_key]
            return self.roll_sub(fb, ctx, roll_cfg.get(fallback_n_key, qty))
        return res

    def roll_sub(self, ref, ctx, qty: int = 1) -> list:
        """抽一个「子池 key 或内联引用」。子池 → 递归走它自己的策略；引用 → 交给解析器。"""
        if not ref:
            return []
        sub_pool = self.pool(ref)
        if sub_pool is not None:
            fn = self.strategy_of(sub_pool)["fn"]
            return fn(sub_pool, self.sub_ctx(ctx, qty), self) or []
        r = self.resolve(ref, ctx)
        if r:
            r["count"] = r.get("count", 1) * qty
            return [r]
        return []

    def roll_pool(self, pool: dict, ctx) -> list:
        """按池的 `type` 分派策略；策略抛错时：非严格模式吞掉返回 []（优雅跳过）。"""
        fn = self.strategy_of(pool)["fn"]
        if self.strict:
            return fn(pool, ctx, self) or []
        try:
            return fn(pool, ctx, self) or []
        except Exception:                                     # noqa: BLE001
            return []

    def roll(self, pool_key, ctx=None, **kw) -> list:
        """唯一入口。

        * `ctx` 缺省 → 用 `SimpleCtx(**kw)`；`ctx` 与 `kw` 都给 → 把 kw 设到 ctx 上（**就地改**，
          与参考实现一致，勿改成复制 —— 调用方依赖这个行为）
        * 池不存在 / 抽空 → `[]`（不抛错）
        """
        pool = self.pool(pool_key)
        if pool is None:
            return []
        if ctx is None:
            ctx = SimpleCtx(**kw)
        elif kw:
            for k, v in kw.items():
                setattr(ctx, k, v)
        return self.roll_pool(pool, ctx)

    # ────────────────────────────── 展开
    def expand(self, pool_key) -> list:
        """带权展开候选（`fixed` = 全给；`weighted` 类 = 按权重重复；`table` 类 = 递归子池）。"""
        pool = self.pool(pool_key)
        if pool is None:
            return []
        spec = self.strategy_of(pool)
        fn = spec.get("expand") or _expand_weighted
        return fn(pool, self)

    # ────────────────────────────── 审计
    def audit(self, *, resolvable=None, pool_of=None) -> dict:
        """结构审计：断链 / 空池 / 权重和 / 子池缺失。

        * `resolvable(ref, pool) -> True | False | None | str` —— **内容侧提供的引用判定**
          （引擎不认识前缀/取值）：
          `True` 解得开；`False` 断链（引擎给通用措辞）；
          **字符串 = 断链且用这句措辞**（内容侧自己的词汇表说话："物品缺失 / 名册缺失 / 子池缺失"）；
          `None` = 这条引用内容侧自己管，不判
        * `pool_of(key) -> dict|None` —— 覆盖池查找（默认用本表的池集合，含前缀剥离）

        返回 `{"issues": [(级别, 池key, 描述)], "pool_count": N, "entry_count": M, "ok": bool}`
        """
        pools = self._pools
        get = pool_of or self.pool
        issues = []
        for pool_key, pool in pools.items():
            spec = self.strategy_of(pool)
            uses = spec.get("uses", "entries")
            entries = pool.get("entries") or []
            if uses == "entries":
                for e in entries:
                    ref = e.get("item", "")
                    if not ref:
                        issues.append(("断链", pool_key, f"条目缺 item 字段: {e}"))
                        continue
                    self._audit_ref(ref, pool_key, pool, issues, resolvable)
                if not entries:
                    issues.append(("空池", pool_key, "entries 为空"))
                if spec.get("needs_weights"):
                    from .pick import total_weight
                    if total_weight(entries) <= 0:
                        issues.append(("空池", pool_key, "权重和 ≤ 0"))
            elif uses == "rolls":
                for rc in pool.get("rolls") or []:
                    sub = rc.get("pool", "")
                    if not sub:
                        issues.append(("断链", pool_key, "roll 无 pool"))
                        continue
                    if get(sub) is not None:
                        continue
                    # 内联前缀在 roll 行同样默认跳过；但内容侧声明了「这族内联引用有域落点」时照判
                    # （与 `_audit_ref` 里的例外同一开关：回调上的 `judged_inline_prefixes`）
                    if sub.startswith(self.inline_prefixes):
                        judged = (getattr(resolvable, "judged_inline_prefixes", ())
                                  if resolvable is not None else ())
                        if not any(str(sub).startswith(p) for p in (judged or ())):
                            continue
                    # roll 的 pool 字段是「子池 key 或引用」：两者都不是 → 断链
                    # （参考实现同样把"既不在池表、也不是内联引用/特殊值"的 roll 判为断链）
                    self._audit_ref(sub, pool_key, pool, issues, resolvable, strict=True)
        return {"issues": issues, "pool_count": len(pools),
                "entry_count": sum(len((p.get("entries") or [])) for p in pools.values()),
                "ok": not issues}

    def _audit_ref(self, ref, pool_key, pool, issues, resolvable, *, strict: bool = False):
        """引用审计。

        * `strict=True`（roll 的子池字段用）：回调说"不认识"（`None`）也算断链
        * 回调返回**字符串** → 用它当措辞（内容侧自己的词汇表说话，引擎不猜）
        * **内联前缀的例外**：内联前缀默认「内容侧自管、审计跳过」（它们还参与 `expand()` 外列）。
          但内容侧可以**额外**声明「这族内联引用其实指向某个域」——做法是给回调挂一个
          `judged_inline_prefixes`（前缀元组），命中它的内联引用**照判**（更严）。
          没挂这个属性 = 完全维持旧行为（不判），所以对既有包零影响。
        """
        if ref in self.special_refs:
            return
        if isinstance(ref, str) and ref.startswith(self.inline_prefixes):
            judged = getattr(resolvable, "judged_inline_prefixes", ()) if resolvable is not None else ()
            if not any(str(ref).startswith(p) for p in (judged or ())):
                return
        if self.pool(ref) is not None:
            return
        if resolvable is None:
            if strict:
                issues.append(("断链", pool_key, f"子池/引用未知: {ref}"))
            return
        try:
            verdict = resolvable(ref, pool)
        except Exception:                                     # noqa: BLE001
            verdict = None
        if isinstance(verdict, str) and verdict:
            issues.append(("断链", pool_key, verdict))
            return
        if verdict is False or (strict and verdict is None):
            issues.append(("断链", pool_key, f"引用无法解析: {ref}"))

    def audit_pretty(self, **kw) -> str:
        rep = self.audit(**kw)
        lines = [f"掉落池审计: {rep['pool_count']} 池 / {rep['entry_count']} 条目"]
        if not rep["issues"]:
            lines.append("✅ 0 问题")
        else:
            for lvl, key, msg in rep["issues"]:
                lines.append(f"  ⚠️ [{lvl}] {key}: {msg}")
        return "\n".join(lines)
