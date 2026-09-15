# -*- coding: utf-8 -*-
"""数值修正容器（Bonus）—— 三档域（panel / cap / cost）+ 来源标签 + 分层合并 + 来源撤销。

**形状在哪**：把「一堆修正叠加成一个数值」这件事从项目里拎出来，去掉「修正是什么」
之后只剩四件通用的事 —— **分域**、**来源标签**、**合并顺序**、**按来源撤销**。
真实项目里它表现为散落在各处的聚合循环（每档域一份、各自手写、各自决定先后），
本模块把**写侧**收成一个容器：写入只走 `add`，读取只走 `resolve`。

**用法**::

    from saintess_engine.bonus import Bonus

    b = Bonus()
    b.add("panel", "src_a", 3)                  # 来源标签不透明，引擎不解释
    b.add("panel", "src_b", 5)
    b.add("panel", "src_c", 1.5, mode="mul")
    b.add("cap",   "src_a", 2)
    b.resolve("panel")                          # (3 + 5) × 1.5 = 12
    b.resolve("cap")                            # 2
    b.resolve("cost")                           # 0（空域 = 0，不是 None）
    b.sources("panel")                          # ['src_a', 'src_b', 'src_c']
    b.drop("src_a")                             # 按来源撤销（来源退场）—— 三档域一起撤
    b.snapshot()                                # {'panel': 12, 'cap': 0, 'cost': 0}
    d = b.to_dict(); Bonus.from_dict(d)         # 结构往返（存档）
    Bonus({"panel": {"src_a": 3}})              # 播种：每域 {来源标签: 值}

**合并顺序（只有一种，测试钉死）**：同一档域内

    先全部 add 累加 → 再全部 mul 连乘 → 最后 set 覆盖

* 累加起点 = 0；空域 = 0。`mul` 乘的是「累加后的值」：域内只有 `mul` 而没有 `add`
  ⇒ `0 × m = 0`（与读侧「基础值缺省 0 时乘算仍为 0」一致 —— 要表达倍率，就先给一个
  `add` 基值来源，基础值本身不在本容器内）。
* `set` 一旦出现即覆盖前两者；多个 `set` 取**登记序**最后一个（同 `(domain, src)`
  重复 `add` 不改登记序，只改值与模式）。
* 同 `(domain, src)` 重复 `add` = **幂等覆盖**：只留最后一次写入，绝不叠加两次。
  这对应「按当前来源全量重算」的写侧口径 —— 重算不会翻倍。

**零知识**：引擎不认修正来自哪里，只认来源标签（不透明字符串）；域名单固定三档
（`DOMAINS`）。新增一类修正 = 加一档域，不新增散落的顶层字段。

**有意不做的事**
----------------
* **不做域内分键**：一档域一个数（`resolve` 返回标量）。「哪个键各是多少」是内容侧
  的事（用多档域表达，或把键并进来源标签），引擎不猜键集。
* **不做基础值**：容器只合并「修正量」；基数由调用方自己叠加 —— 容器不认识基数。
* **不做静默兜底**：非法域 / 非法 mode / 非数值 / 非有限数一律当场报错，不吞成 0、
  不静默丢弃（`from_dict` 读到未登记域同样报错 —— 丢掉一条修正就是丢数值）。
* **不做兼容壳**：没有旧键名回落、没有开关、没有兼容分支，语义只留一种。
"""
from __future__ import annotations

from collections.abc import Mapping

__all__ = ["Bonus"]

# 合并模式（写侧只认这三个词；非法值报错，不静默当 add）
_MODES = ("add", "mul", "set")


def _label(src) -> str:
    """来源标签规范化：空标签 = 撤不掉的来源 ⇒ 当场报错。"""
    if src is None or not str(src).strip():
        raise ValueError("来源标签不能为空")
    return str(src)


def _value(v):
    """修正值校验：只收有限数字（bool 不算数字；NaN/Inf 会污染整个域的合并结果）。"""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise TypeError(f"修正值必须是 int/float，收到 {type(v).__name__}")
    f = float(v)
    if f != f or f in (float("inf"), float("-inf")):
        raise ValueError(f"修正值必须是有限数字，收到 {v!r}")
    return v


def _norm(v):
    """合并结果归一：整值落 int（观感）；小数 round(6) 清二进制尾差。"""
    if isinstance(v, float):
        if v.is_integer():
            return int(v)
        return round(v, 6)
    return v


class Bonus:
    """三档域修正容器（**可变**）。域的最终值只由 `resolve(domain)` 给出。"""

    DOMAINS = ("panel", "cap", "cost")

    def __init__(self, seed: Mapping | None = None) -> None:
        """空容器；`seed` 非空则播种。

        `seed` 两种形态（未登记域 / 非法值一律报错，不静默跳过）：
        * `{域: {来源标签: 值}}`，值也可写成 `{"value": 值, "mode": "add|mul|set"}`
        * `to_dict()` 的结构形 `{"domains": {域: {来源标签: {...}}}}`
        """
        self._entries: dict[str, dict[str, dict]] = {d: {} for d in self.DOMAINS}
        if seed is not None:
            self._load(seed)

    # ------------------------------------------------------------ 校验
    @classmethod
    def _check_domain(cls, domain) -> str:
        if domain not in cls.DOMAINS:
            raise ValueError(f"未登记的域：{domain!r}（只认 {cls.DOMAINS}）")
        return domain

    # ------------------------------------------------------------ 写入
    def add(self, domain, src, value, *, mode: str = "add") -> None:
        """写一条修正。同 `(domain, src)` **幂等覆盖**（不叠加）。

        * `mode="add"` 累加 / `"mul"` 连乘 / `"set"` 覆盖（顺序见模块 docstring）
        * `src` 是来源标签（不透明，撤销按它）；重复写同一个来源 = 覆盖值/模式
        * `domain` 未登记 → `ValueError`；`mode` 非法 → `ValueError`；
          值非数字 → `TypeError`；值非有限 → `ValueError`
        """
        self._check_domain(domain)
        if mode not in _MODES:
            raise ValueError(f"mode 只能是 {_MODES}，收到 {mode!r}")
        self._entries[domain][_label(src)] = {"value": _value(value), "mode": mode}

    # ------------------------------------------------------------ 读取
    def resolve(self, domain):
        """合并一档域的修正量（空域 → `0`，不是 `None`）。

        顺序：`add` 全累加 → `mul` 全连乘 → `set` 覆盖（见模块 docstring）。
        整值落 int，小数 round(6)。
        """
        self._check_domain(domain)
        entries = self._entries[domain].values()
        total = 0
        for e in entries:
            if e["mode"] == "add":
                total = total + e["value"]
        for e in entries:
            if e["mode"] == "mul":
                total = total * e["value"]
        for e in entries:
            if e["mode"] == "set":
                total = e["value"]
        return _norm(total)

    def sources(self, domain=None) -> list:
        """来源标签列表（登记序）。

        * `domain` 给定 → 该域内的来源标签
        * `domain=None` → 全部域的并集（按 `DOMAINS` 顺序，首次出现序去重）
        """
        if domain is None:
            out: dict = {}
            for d in self.DOMAINS:
                for s in self._entries[d]:
                    out.setdefault(s, None)
            return list(out)
        self._check_domain(domain)
        return list(self._entries[domain])

    def snapshot(self) -> dict:
        """`{域: 最终值}`（三档域齐全，空域 0）—— 落盘/对账用的一眼视图。

        结构往返（含 mode/来源标签）用 `to_dict()` / `from_dict()`。
        """
        return {d: self.resolve(d) for d in self.DOMAINS}

    # ------------------------------------------------------------ 撤销
    def drop(self, src) -> None:
        """按来源撤销：把该标签从**全部**域里摘掉（不在 → 无操作，幂等）。"""
        label = _label(src)
        for d in self.DOMAINS:
            self._entries[d].pop(label, None)

    # ------------------------------------------------------------ 往返
    def to_dict(self) -> dict:
        """结构形（含来源标签与 mode）—— 存档往返用 `from_dict()`。"""
        return {"domains": {
            d: {s: {"value": e["value"], "mode": e["mode"]}
                for s, e in self._entries[d].items()}
            for d in self.DOMAINS}}

    @classmethod
    def from_dict(cls, data) -> "Bonus":
        """`to_dict()` 的结构形 → 新容器（也收播种形；`None` = 空容器）。"""
        b = cls()
        if data is not None:
            b._load(data)
        return b

    def _load(self, data) -> None:
        """播种内核：结构形（`{"domains": ...}`）与播种形（`{域: {来源: 值|声明}}`）都收。"""
        if not isinstance(data, Mapping):
            raise TypeError(f"播种/往返数据必须是映射，收到 {type(data).__name__}")
        inner = data["domains"] if "domains" in data else data
        if not isinstance(inner, Mapping):
            raise TypeError(f"域表必须是映射，收到 {type(inner).__name__}")
        for domain, srcs in inner.items():
            self._check_domain(domain)
            if not isinstance(srcs, Mapping):
                raise TypeError(f"域 {domain!r} 的来源表必须是映射，收到 {type(srcs).__name__}")
            for src, spec in srcs.items():
                if isinstance(spec, Mapping):
                    self.add(domain, src, spec.get("value"), mode=spec.get("mode", "add"))
                else:
                    self.add(domain, src, spec)

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return (f"Bonus(panel={len(self._entries['panel'])}, "
                f"cap={len(self._entries['cap'])}, "
                f"cost={len(self._entries['cost'])})")
