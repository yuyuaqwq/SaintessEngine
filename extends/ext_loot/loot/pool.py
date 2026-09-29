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



USES_KINDS = ("entries", "rolls", "none")


def _check_spec(name, fn, uses, *, needs_weights=False, expand=None):
    """**策略 spec 的唯一合法性判定**（审计 L573）。

    ★ 原缺陷：只有 register_strategy 那条入口做了校验，而 LootTable(strategies=...)
      的**构造期入口**零校验 —— 内容侧传 dict spec 时 uses 拼错（"entry"）
      既不报错、又让 audit() 的 entries / rolls **两个分支都不进**
      （探针实测：issue 列表为空 ⇒ 整张表「审计通过」而实际一条都没判）。
      修法 = 两条入口**共用这一份判定**（不留兼容分支、不加兜底）。
    """
    if not isinstance(name, str) or not name:
        raise ValueError("策略名必须是非空字符串")
    if not callable(fn):
        raise TypeError(
            f"策略必须可调用：fn(pool, ctx, table) -> list[dict]（{name!r} 收到 {fn!r}）")
    if uses not in USES_KINDS:
        raise ValueError(
            f"uses 只能是 {"/".join(USES_KINDS)}，收到 {uses!r}（策略 {name!r}）")
    if expand is not None and not callable(expand):
        raise TypeError(f"expand 必须可调用或为 None（策略 {name!r} 收到 {expand!r}）")
    return {"fn": fn, "uses": uses,
            "needs_weights": bool(needs_weights), "expand": expand}

def register_strategy(name: str, fn, *, doc: str = "", uses: str = "entries",
                      needs_weights: bool = False, expand=None, replace: bool = False):
    """注册一个策略。重名默认报错（防静默覆盖）；要覆盖写 `replace=True`。"""
    if name in STRATEGIES and not replace:
        raise ValueError(f"策略已注册：{name}（要覆盖请显式 replace=True）")
    spec = _check_spec(name, fn, uses, needs_weights=needs_weights, expand=expand)
    spec["doc"] = doc
    STRATEGIES[name] = spec
    return fn


def strategy_names() -> tuple:
    return tuple(sorted(STRATEGIES))


class UnknownStrategy(ValueError):
    """未知掉落策略 —— **不静默换策略**。

    ★ 为什么必须抛：`STRATEGIES.get(name) or STRATEGIES["weighted"]` 这种写法会把
      「按掉率逐项掷」（`table`）悄悄变成「必掉一件」（`weighted`）——
      加载期不报错、运行期语义变了，是查不出的哑弹。
      实证：`get_strategy("per_entry_roll")` 曾静默返回 `_s_weighted`。
    """


class EmptyPoolDef(ValueError):
    """池声明为空 —— **不静默变成「这次没掉」**（审计 L574 / L575）。

    ★ 为什么必须抛：strategy_of() 已经把「未知 type 静默回落 weighted」堵死了
      （UnknownStrategy，审计 L566）。但**同一条哑弹还有另一半** —— 池结构与策略名
      都对，唯独该策略要的那一档（rolls 族要 rolls / entries 族要 entries）
      **整档是空的**。旧写法 `pool.get("rolls", [])` 拿到空列表后 for 一次都不进，
      直接 return []：
        · uses=rolls 的 type=table / table_choice 实跑 = []（探针实测）
        · 玩家体感 = 池子配了却什么都没掉，无报错、无诊断、无从察觉。
      与 L566 同源同修法：**声明错就抛，不许兜底成一个合法外观的返回值**。
    """

def _lookup(name: str) -> dict:
    try:
        return STRATEGIES[name]
    except KeyError:
        raise UnknownStrategy(
            f"未知掉落策略 {name!r}；已注册 = {tuple(STRATEGIES)}。"
            "★ 不许静默回落 weighted —— 那会把「每项独立判定」静默变成「必掉一件」。"
            "（若本意就是「每项按 chance 独立掷」，请用 `table`。）") from None


def get_strategy(name: str):
    return _lookup(name)["fn"]


def strategy_spec(name: str) -> dict:
    return dict(_lookup(name))


class SimpleCtx:
    """极简上下文：属性缺失一律 None（不抛 AttributeError），`hooks` 恒为 dict。

    「内容侧策略要什么字段」是内容的事 —— 引擎只提供一个宽容的袋子。
    """

    def __init__(self, **kw):
        self.__dict__.update(kw)
        self.hooks = kw.get("hooks") or {}

    def __getattr__(self, name):
        # ★ 宽容**只对数据属性**（2026-09-28，审计 L568，批次 1）。dunder 一律走正常查找链
        #   （缺失就抛 AttributeError）—— 否则 `copy` 的协议探针
        #   （`__copy__` → `__reduce_ex__` → `__setstate__`）拿到的全是 **None**
        #   （不是「调用它」），标准库于是抛 `TypeError: 'NoneType' object is not callable`。
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return None


# ───────────────────────────────────────────────────────── 内置策略

def _count_of(value, label: str) -> int:
    """数量格取值：**回落只认 `None`**（缺项给 `1`；`0` 是合法值，不被吞）。

    ★ 这一族三处（`ctx.qty` / entry `n` / entry `w`）原先都是 `int(x.get(k, 1) or 1)`：
      falsy 的合法值（`qty=0` / `n=0` / `w=0`）一律被吞成 1 —— `qty=0` 实跑出 1 条
      （台账 ext_loot `pool.py:113` 探针 P5）。收敛到本函数一份判定。
    """
    if value is None:
        return 1
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} 必须是数值（数量），收到 {value!r}")
    return int(value)


def _ctx_level(ctx):
    """等级窗口的判定值：**显式区分「没有」与「0」**（`None` = 上下文没给等级）。

    ★ 口径裁定（2026-09-28，台账 ext_loot `pool.py:115,120-122`「静默放过」条）：
      旧写法 `int(getattr(ctx,"player_level",0) or getattr(ctx,"monster_lv",0) or 0)` 把
      「玩家等级 0」「没给等级」和 `min_lv/max_lv` 全都短路掉 —— 探针 P6 实测
      `min_lv:50` 的条目在 `player_level=0` 时**照样掉**（玩家没到等级也拿得到）。
      裁定 = **「不启用窗口」**（缺等级时不按等级筛），理由：
        ① 掉落上下文是**内容侧每次 roll 现给的**，等级是**玩家侧**的值 —— 怪物掉落
           （`monster_lv` 口径）在拿不到玩家等级时本就该按怪物等级走，两者都缺才没得筛；
        ② 反过来「全被滤」会把「没给等级」变成「掉不出东西」—— 那是拿一个**缺失值**
           换一次玩家可见的「什么也没掉」，属最贵的一类静默；
        ③ 本仓生产数据里 entry 级 `min_lv`/`max_lv` **零出现**（实测 1435 条 entry：
           min_lv 0 / max_lv 0，见 `games/orlandia/content/data/drop*.json`）
           ⇒ 判「不启用」不改变任何现有内容的行为。
      但**这一格必须是显式的一份判定**，不能靠 `or` 链短路 ⇒ 缺等级返回 `None`。
    """
    for attr in ("player_level", "monster_lv"):
        value = getattr(ctx, attr, None)
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"ctx.{attr} 必须是数值（等级），收到 {value!r}")
            return int(value)
    return None            # ★ 显式「没给等级」= 不启用窗口（不是 0、也不是被吞）


def _s_weighted(pool: dict, ctx, table) -> list:
    """带权抽取：抽 `ctx.qty` 次；等级窗口过滤；抽空走 `ctx.fallback_roll` 钩子。"""
    # ★ 回落只认 `None`：`qty=0` 是合法值（这一抽就是「不要东西」），旧的 `or 1`
    #   把它吞成 1（探针 P5：`qty=0` 实跑出 1 条）。`qty=""` 之类坏值另行报错。
    raw_qty = getattr(ctx, "qty", None)
    if raw_qty is None:
        qty = 1
    elif isinstance(raw_qty, bool) or not isinstance(raw_qty, (int, float)):
        raise TypeError(f"ctx.qty 必须是数值（抽多少条），收到 {raw_qty!r}")
    else:
        qty = int(raw_qty)
    if qty < 0:
        raise ValueError(f"ctx.qty 不能为负，收到 {raw_qty!r}")
    entries = pool.get("entries", [])
    lv = _ctx_level(ctx)
    cand = []
    for e in entries:
        min_lv = e.get("min_lv")
        max_lv = e.get("max_lv")
        if lv is not None:
            if min_lv and lv < int(min_lv):
                continue
            if max_lv and lv > int(max_lv):
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
                # ★ `n` 回落只认 `None`：`n=0` 是合法值（这条就是不给），旧 `or 1` 吞成 1
                r["count"] = r.get("count", 1) * _count_of(pick.get("n"), "n")
                out.append(r)
    return out


def _s_fixed(pool: dict, ctx, table) -> list:
    """固定掉落：entries 全给。"""
    out = []
    for e in pool.get("entries", []):
        r = table.resolve(e["item"], ctx)
        if r:
            # ★ 同 `_s_weighted`：`n` 回落只认 `None`，`n=0` 不被吞成 1
            r["count"] = r.get("count", 1) * _count_of(e.get("n"), "n")
            out.append(r)
    return out


def _rolls_of(pool: dict, strategy: str) -> list:
    """取 rolls 族的档位表：**缺档 / 空档 / 非列表一律抛**（审计 L574 / L575）。

    * `strategy` 只用于报错定位（type=table / type=table_choice）。
    * 不用 `pool.get("rolls", [])` 的默认值：缺键与空列表**报同一条**。
    """
    if "rolls" not in pool:
        raise EmptyPoolDef(
            f"type={strategy!r} 的池缺 rolls 字段（现有字段 {sorted(pool)}）；"
            "★ 缺这一档等于「什么都不掉」，不静默返回空列表")
    rolls = pool["rolls"]
    if not isinstance(rolls, list):
        raise EmptyPoolDef(
            f"type={strategy!r} 的池 rolls 必须是列表，收到 {type(rolls).__name__}")
    if not rolls:
        raise EmptyPoolDef(
            f"type={strategy!r} 的池 rolls 为空 —— 整池永远抽不出东西；"
            "★ 这是数据缺陷，不是一次「没命中」")
    return rolls

def _s_table(pool: dict, ctx, table) -> list:
    """多层概率表：每行独立判定（`chance` 不中即跳过）。"""
    rolls = _rolls_of(pool, "table")
    out = []
    for roll_cfg in rolls:
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
    rolls = _rolls_of(pool, "table_choice")
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
        # ★ 同上：`w` 回落只认 `None`（`w=0` = 这条权重为零，不该被吞成 1）
        w = min(_count_of(e.get("w"), "w"), 1000)
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
                 pool_key_prefixes=(), special_refs=(), rng=None, strict: bool = True,
                 fallback_attr: str = "fallback_roll"):
        self._pools = pools if pools is not None else {}
        self._resolver = resolver
        self._strategies = dict(STRATEGIES)
        for k, v in dict(strategies or {}).items():
            if callable(v):
                # 裸可调用 = 「entries 族、无 expand」的简写（既有语义）
                self._strategies[k] = _check_spec(k, v, "entries")
                continue
            if not isinstance(v, dict):
                raise TypeError(
                    f"strategies[{k!r}] 必须是可调用或 dict spec，收到 {v!r}"
                    "（可调用 = entries 族简写；dict = fn/uses/expand）")
            merged = dict(STRATEGIES.get(k) or {})
            merged.update(v)
            # ★ 与内置策略**用同一份判定**（审计 L573）——原先这条路径零校验
            # ★ 2026-09-29 收口修复：`_check_spec` 返回的是**整个 spec dict**；旧写法把它
            #   直接塞进 `spec["fn"]` ⇒ 凡「覆盖内置策略」的实例（奥兰迪亚的
            #   `{"table": {"expand": ...}}` 即此形态），该策略一被 roll 就
            #   `TypeError: 'dict' object is not callable` ⇒ 副本战利品堆等所有
            #   `type=table` 的池摸不出东西。改为以其规范化结果**更新四键**。
            merged.update(_check_spec(
                k, merged.get("fn"), merged.get("uses", "entries"),
                needs_weights=merged.get("needs_weights", False),
                expand=merged.get("expand")))
            self._strategies[k] = merged
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
        """池对象（不存在 → None；`weighted:xxx` 这类前缀会先剥掉再查）。

        ★ 前缀**按声明的前缀本身**切，不再写死 `":"`（L-audit2 同族）：
          写死分隔符时，前缀若不含 `:`（内容侧声明 `("side.",)` 这类命名空间前缀），
          `split(":", 1)[1]` 会切在**池名自己的冒号**上 ⇒ 查出**另一个池**（静默给错池），
          而前缀恰好等于整串时直接 `IndexError`。本函数「不存在 → None、不抛错」的契约两种都被破。
        切完剩空串 ⇒ 没有池名可查 ⇒ None（**不是** IndexError）。
        """
        if pool_key in self._pools:
            return self._pools[pool_key]
        for p in self.pool_key_prefixes:
            if isinstance(pool_key, str) and pool_key.startswith(p):
                name = pool_key[len(p):]
                return self._pools.get(name) if name else None
        return None

    def has_pool(self, pool_key) -> bool:
        return self.pool(pool_key) is not None

    def strategy_of(self, pool: dict, *, strict: bool = True) -> dict:
        """池的 `type` → 策略 spec。

        ★ 缺 `type` ⇒ 回落 `weighted`（**有意**：旧池没写 type 时的既有语义）。
        ★ 写了 `type` 但没注册 ⇒ **抛 `UnknownStrategy`**（不静默回落 ——
          那是「声明错」被当成「默认策略」，语义会静默变）。

        `strict=False`（**只给诊断面用**，如 `audit`）：未注册 ⇒ 回落 weighted 以便
        把整个池的形状渲染出来；运行期（`roll_pool` / `expand`）必须保持 `strict=True`。
        """
        name = pool.get("type")
        if name is None:
            return self._strategies["weighted"]
        spec = self._strategies.get(name)
        if spec is None:
            if not strict:
                return self._strategies["weighted"]   # 仅诊断面（audit）用；运行期一律抛
            raise UnknownStrategy(
                f"未知掉落策略 {name!r}；已注册 = {tuple(sorted(self._strategies))}。"
                "★ 不许静默回落 weighted —— 那会把「每项独立判定」静默变成「必掉一件」。"
                "（若本意就是「每项按 chance 独立掷」，请用 `table`。）")
        return spec

    def resolve(self, ref, ctx):
        """调内容侧解析器（未配置 → None，等于"这条出不来"）。

        ★ 返回前**深拷贝**（审计 L565）：`r["count"] = r.get("count",1) * n` 这三处写口
          （`_s_weighted` / `_s_fixed` / `roll_sub`）都**就地改**解析器返回的那个 dict。
          解析器若返的是**域表里的共享对象**（`return TABLE.get(ref)` 这种现实写法），
          第一次 roll 把 count 从 1 写成 4、第二次写 16、第三次 64 —— **数据表被永久污染**，
          且**自污染**（第二次跑数值已经错，同一局内先掉的东西和后掉的不一样）。
          拷贝在**唯一入口**做一次：内容侧拿到深拷贝、行为逐值不变，域表不再被写回。
          判据：extends/ext_loot/tests/test_loot.py `t3_roll` 的「域表不被写回」组。
        """
        if self._resolver is None:
            return None
        got = self._resolver(ref, ctx)
        if not got:
            return None                     # None / {} / 空容器 = 这条出不来（口径不变）
        return copy.deepcopy(got)            # ★ 写口只改副本（深拷贝：data 子层也不共享）
    
    # ────────────────────────────── 抽取
    def sub_ctx(self, ctx, qty):
        """子池上下文：复制一份改 `qty`（不动原 ctx）。

        ★ 复制失败**抛**，不静默改原对象（2026-09-28，审计 L568）：
          旧写法 `except Exception: return ctx` 表面兜底、实则把「子池按自己的 n 抽」
          悄悄降成「子池按外层 ctx 的 qty 抽」——`n:[3,7]` 整段失效、玩家少掉，
          而全程零报错（`SimpleCtx.__getattr__` 吞 dunder 让这一支**恒**命中）。
          `copy` 支持的协议只有 `__copy__` / `__reduce_ex__` / `__reduce__` / `__getstate__`；
          别的类型不给这些**不是错**（自定义 ctx 类完全合法），但**不许悄悄拿原对象顶替**。
        """
        c = copy.copy(ctx)
        c.qty = qty
        return c

    def fallback(self, pool, ctx, key: str = "fallback") -> list:
        """池抽空时的兜底钩子（`ctx.fallback_roll(pool, fallback声明, ctx)`）。

        ★ 钩子抛错**按 `strict` 分流**（2026-09-29，审计 L566 的同族收口）。旧写法是
          **无条件** `except Exception: return []` —— 它把 `roll_pool` 上一轮刚立起来的
          `strict=True` 契约在**兜底这条支上又漏掉了**：钩子是**内容侧写的**回调
          （`ctx.fallback_roll`），池抽空时若它抛（写错条目名 / 造档顺序不对 /
          自己内部 KeyError），玩家看到的只是「这次没掉」—— 与 `strict=True` 要防的
          形态**逐字同一种**，而且这条支只由 `weighted` 表池抽空走到，出错率低 ⇒ 更难被发现。
          ⇒ `strict=True`（默认）**上抛**；`strict=False` 仍可优雅跳过，但必须是
          **显式选择**（与 `roll_pool` 同一口径，不留「某条支偷偷宽松」的缝）。
        """
        fb = pool.get(key)
        hook = getattr(ctx, self.fallback_attr, None)
        if fb and callable(hook):
            if self.strict:
                return hook(pool, fb, ctx) or []
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
        """按池的 `type` 分派策略；`strict` **默认 True**（审计 L566）⇒ 策略抛错一律上抛。

        ★ 为什么默认严格：旧默认 `False` 把掉落层**任何**异常降级成「这次没掉」——
          内容侧 `LootTable(...)` 构造时没传 `strict`（奥兰迪亚 `content/loot.py:561` 即如此）
          ⇒ 线上跑的全是"吞异常"那一支：一个笔误 / 一行坏数据 ⇒ 玩家看到的只是**什么都没掉**，
          无报错、无诊断、无从察觉（判据 2「不静默」的教科书形态）。
        ★ `strict=False` 仍在，但它现在是**显式选择**（要"优雅跳过某个池"就自己写出来），
          不再是「不写就默认降级」。
        ★ 「未知策略」是**声明错**，不是运行期掉落失败 ⇒ 两种模式都上抛（`UnknownStrategy`）。
          否则它会被当成"这次没掉"，等价于把声明错误静默变成空掉落。
        """
        fn = self.strategy_of(pool)["fn"]            # 未知策略在此已抛
        if self.strict:
            return fn(pool, ctx, self) or []
        try:
            return fn(pool, ctx, self) or []
        except UnknownStrategy:
            raise
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
            # ★ 诊断面：未注册的 type 也要能把整张表审计完（报成 issue），
            #   不能因为一个坏池就中断审计。运行期 `roll_pool` 那边保持严格。
            #
            # ★ 这里**故意不把「未知」报成 issue**：内容侧可以用 `register_strategy`
            #   注册自己的策略名；而 `audit()` 可能跑在一张**没拿到内容侧注册表**的表上
            #   （如引擎侧用例）⇒ 此时把内容侧注册过的名字报成 error 就是误报。
            #   ⇒ 「未知」的可见性交给 ①运行期 `roll_pool` 抛 `UnknownStrategy`
            #     ②编辑器预览的警告行，各管一段。
            spec = self.strategy_of(pool, strict=False)
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

    def audit_pretty(self, header: str = "掉落池审计", **kw) -> str:
        """人类可读审计报告。`header` 由调用方给（引擎不认识具体池名/文件名的说法）。"""
        rep = self.audit(**kw)
        lines = [f"{header}: {rep['pool_count']} 池 / {rep['entry_count']} 条目"]
        if not rep["issues"]:
            lines.append("✅ 0 问题")
        else:
            for lvl, key, msg in rep["issues"]:
                lines.append(f"  ⚠️ [{lvl}] {key}: {msg}")
        return "\n".join(lines)
