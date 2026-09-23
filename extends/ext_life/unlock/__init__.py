# -*- coding: utf-8 -*-
"""解锁闸门（E4）—— 把「这块内容现在开放没有」做成引擎形状。

设计真源：`aetheran-designer/12_迁移引擎评估/02_引擎提升设计_E3E5E4.md` §4。

## 为什么建

引擎已有 `run` / `quest` / `presence` 三个子包，但**都不是解锁闸门**：
`run` 管一次战斗流程、`quest` 管任务状态机、`presence` 管在场集合 ——
没有任何一个的语义是「**这个东西对玩家开放了没有**」。

于是内容侧会把判据散在各自的命令分支里：同一道门槛在两个命令里写两遍，
改一处漏一处；更糟的是**判不成立时静默 return**（玩家看到"什么都没发生"）。

## 本模块的零游戏词汇口径

引擎**不出现**「阶段 / 地图 / 指令 / 系统」这些字面量：
`targets` 里的 `kind` 取值集合**由包声明**（包的 `unlock_kinds` 域），
引擎只把它当**不透明字符串**做等值匹配。引擎也不知道"什么才算解锁"——
条件真源一律是 `conditions.Conditions`（声明节点或已注册 key），本模块不新造判据语言。

## 三档行为（fail-closed，必须逐档可测）

| 档 | 情形 | 行为 |
|---|---|---|
| ① | 目标**未被任何条目覆盖** | **放行** —— R1「不配 = 不存在」。★ 不许把「没声明」当「没解锁」 |
| ② | 目标被覆盖，但条件**未注册 / 声明形状不合法** | **装配期抛**（`UnknownCondition` / `SpecError`）。★ 不许把「没实现」伪装成「未满足」 |
| ③ | 目标被覆盖，条件判**不成立** | `gate()` 返回 `Locked`（**结构**，不是渲染好的字符串）；命令层必须回执并 `return` |
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping, Optional

from saintess_engine.conditions import Conditions, UnknownCondition
from saintess_engine.conditions.declarative import SpecError, compile_spec

__all__ = ["Locked", "UnlockDeclError", "Unlocks"]


class UnlockDeclError(ValueError):
    """解锁条目声明不合法（装配期抛，不静默跳过）。"""


class Locked:
    """未解锁回执 —— **结构**，不是渲染后的字符串。

    引擎只把"该说哪句话"的**槽位**给出来（`label_key` / `locked_text` /
    `progress_text` 都是**文案表 key**），具体行文由内容侧文案表渲染
    （`text_specs.json` 是文案真源，引擎不生成自然语言）。

    用 `__slots__` 且不可变字段：回执会被上层塞进日志，不希望被就地改坏。
    """

    __slots__ = ("target", "entry_id", "label_key", "locked_text",
                 "progress_text", "order")

    def __init__(self, *, target: tuple, entry_id: str, label_key: str,
                 locked_text: str, progress_text: Optional[str],
                 order: int) -> None:
        self.target = target
        self.entry_id = entry_id
        self.label_key = label_key
        self.locked_text = locked_text
        self.progress_text = progress_text
        self.order = order

    def __repr__(self) -> str:
        return (f"Locked({self.target!r} ← {self.entry_id!r}, "
                f"label={self.label_key!r}, text={self.locked_text!r})")


def _as_target(target: Any, where: str) -> tuple:
    """把 `(kind, id)` 规整成 `(str, str)` 元组（引擎只做等值匹配，不解释语义）。"""
    if isinstance(target, str):
        raise UnlockDeclError(
            f"{where} 的 target 必须是 (kind, id) 二元组，收到裸字符串 {target!r}。"
            "★ 裸 id 会逼引擎猜「这个 id 属于哪种目标」——引擎不许猜。")
    try:
        kind, ident = target
    except (TypeError, ValueError) as e:
        raise UnlockDeclError(
            f"{where} 的 target 必须是 (kind, id) 二元组，收到 {target!r}") from e
    if not isinstance(kind, str) or not kind.strip():
        raise UnlockDeclError(f"{where} 的 target.kind 必须是非空字符串，收到 {kind!r}")
    if not isinstance(ident, str) or not ident.strip():
        raise UnlockDeclError(f"{where} 的 target.id 必须是非空字符串，收到 {ident!r}")
    return (kind, ident)


def _require_key(entry: Mapping, field: str, eid: str) -> str:
    v = entry.get(field)
    if not isinstance(v, str) or not v.strip():
        raise UnlockDeclError(
            f"解锁条目 {eid!r} 的 {field!r} 必须是非空字符串（文案表 key），收到 {v!r}")
    return v


def _optional_key(entry: Mapping, field: str, eid: str) -> Optional[str]:
    v = entry.get(field)
    if v is None:
        return None
    if not isinstance(v, str) or not v.strip():
        raise UnlockDeclError(
            f"解锁条目 {eid!r} 的 {field!r} 若给就必须是非空字符串，收到 {v!r}")
    return v


class Unlocks:
    """解锁闸门。**装配期把错误全部拦下**，运行期只做等值匹配 + 条件求值。

    :param entries: ``{解锁条目 id: 条目 dict}``（包数据，见模块 docstring 的字段表）
    :param conditions: ``conditions.Conditions`` 实例（条件真源）
    :param condition_key_of: 可选 ``fn(entry_id, entry) -> str``。
        不给 ⇒ 从条目里读 ``condition_key``；给了 ⇒ 由它决定（可做命名规范）
    :param text_of: 可选 ``fn(key) -> str``：把文案表 key 换成自然语言。
        **引擎不生成行文**，只负责把 key 交出来；不装 ⇒ 渲染结果就是 key 本身
    """

    def __init__(self, entries: Mapping[str, Mapping], *,
                 conditions: Conditions,
                 condition_key_of: Optional[Callable[[str, Mapping], str]] = None,
                 text_of: Optional[Callable[[str], str]] = None) -> None:
        if not isinstance(entries, Mapping):
            raise UnlockDeclError(f"entries 必须是映射，收到 {type(entries).__name__}")
        if not isinstance(conditions, Conditions):
            raise UnlockDeclError(
                f"conditions 必须是 conditions.Conditions 实例，收到 {type(conditions).__name__}")
        self._cond = conditions
        self._text_of = text_of
        self._entries: dict[str, Mapping] = {}
        self._cond_fn: dict[str, Callable] = {}
        self._by_target: dict[tuple, list[str]] = {}
        self._order: dict[str, int] = {}
        self._decl_seq: dict[str, int] = {}      # ★ 声明序副键：同 order 时靠它定取条顺序

        for eid, entry in entries.items():
            self._install(eid, entry, condition_key_of)

        # 同目标多条覆盖：按 (order, 声明序) 排 —— 不猜，顺序由数据给
        for tgt, ids in self._by_target.items():
            ids.sort(key=lambda e: (self._order[e], self._decl_seq[e]))

    # ── 装配期 ──────────────────────────────────────────────────────────
    def _install(self, eid: Any, entry: Any,
                 condition_key_of: Optional[Callable]) -> None:
        if not isinstance(eid, str) or not eid.strip():
            raise UnlockDeclError(f"解锁条目 id 必须是非空字符串，收到 {eid!r}")
        if not isinstance(entry, Mapping):
            raise UnlockDeclError(f"解锁条目 {eid!r} 必须是映射，收到 {type(entry).__name__}")
        if eid in self._entries:
            raise UnlockDeclError(f"解锁条目 id 重复：{eid!r}")

        label_key = _require_key(entry, "label_key", eid)
        locked_text = _require_key(entry, "locked_text", eid)
        progress_text = _optional_key(entry, "progress_text", eid)

        order = entry.get("order", 0)
        if isinstance(order, bool) or not isinstance(order, int):
            raise UnlockDeclError(f"解锁条目 {eid!r} 的 order 必须是整数，收到 {order!r}")

        # 条件：`condition_key`（引用已注册）与 `condition`（声明节点）二选一
        has_key = entry.get("condition_key") is not None
        has_decl = entry.get("condition") is not None
        if has_key and has_decl:
            raise UnlockDeclError(
                f"解锁条目 {eid!r} 同时写了 condition_key 与 condition（声明自相矛盾）")
        if not has_key and not has_decl:
            raise UnlockDeclError(
                f"解锁条目 {eid!r} 必须给 condition_key 或 condition 之一")
        key = condition_key_of(eid, entry) if condition_key_of else entry.get("condition_key")
        if has_key:
            if not isinstance(key, str) or not key.strip():
                raise UnlockDeclError(
                    f"解锁条目 {eid!r} 的条件 key 必须是非空字符串，收到 {key!r}")
            if not self._cond.has(key):
                # ★ 档 ②：不许把「没实现」伪装成「未满足」
                raise UnknownCondition(
                    f"解锁条目 {eid!r} 引用了未注册的条件 {key!r}；"
                    f"已注册 = {sorted(self._cond.keys())}")
            self._cond_fn[eid] = self._cond.get(key)
        else:
            try:
                self._cond_fn[eid] = compile_spec(entry["condition"])
            except SpecError as e:
                # ★ 档 ②：声明形状不合法 → 装配期抛，不静默当"未满足"
                raise SpecError(f"解锁条目 {eid!r} 的 condition 声明不合法：{e}") from e

        targets = entry.get("targets")
        if not isinstance(targets, (list, tuple)) or not targets:
            raise UnlockDeclError(
                f"解锁条目 {eid!r} 的 targets 必须是非空数组（≥1），收到 {targets!r}")
        seen: list[tuple] = []
        for t in targets:
            if not isinstance(t, Mapping):
                raise UnlockDeclError(
                    f"解锁条目 {eid!r} 的 targets 每项必须是 {{kind, id}} 映射，收到 {t!r}")
            extra = set(t) - {"kind", "id"}
            if extra:
                raise UnlockDeclError(
                    f"解锁条目 {eid!r} 的 target 只允许键 kind/id，多出：{sorted(extra)}")
            tg = _as_target((t.get("kind"), t.get("id")), f"解锁条目 {eid!r}")
            if tg in seen:
                raise UnlockDeclError(f"解锁条目 {eid!r} 的 targets 重复：{tg!r}")
            seen.append(tg)

        self._entries[eid] = dict(entry, label_key=label_key,
                                  locked_text=locked_text,
                                  progress_text=progress_text, order=order)
        self._order[eid] = order
        self._decl_seq[eid] = len(self._decl_seq)
        for tg in seen:
            self._by_target.setdefault(tg, []).append(eid)

    # ── 查询面 ──────────────────────────────────────────────────────────
    def ids(self) -> list:
        return list(self._entries)

    def targets(self) -> list:
        return list(self._by_target)

    def entry_of(self, target: Any) -> Optional[str]:
        """同一目标被多条覆盖时取**声明序首条**（`order` 小者优先，再按声明序）。"""
        tg = _as_target(target, "entry_of()")
        ids = self._by_target.get(tg)
        return ids[0] if ids else None

    def is_unlocked(self, target: Any, ctx: Any = None) -> bool:
        """★ 档 ①：目标**未被任何条目覆盖** ⇒ 返回 True（R1「不配 = 不存在」）。"""
        tg = _as_target(target, "is_unlocked()")
        ids = self._by_target.get(tg)
        if not ids:
            return True
        return bool(self._cond_fn[ids[0]](ctx))

    def gate(self, target: Any, ctx: Any = None) -> Optional[Locked]:
        """放行 ⇒ `None`；未解锁 ⇒ `Locked`（**结构**，命令层拿它去回执并 `return`）。"""
        tg = _as_target(target, "gate()")
        ids = self._by_target.get(tg)
        if not ids:
            return None
        eid = ids[0]
        if self._cond_fn[eid](ctx):
            return None
        e = self._entries[eid]
        return Locked(target=tg, entry_id=eid, label_key=e["label_key"],
                      locked_text=e["locked_text"],
                      progress_text=e["progress_text"], order=e["order"])

    def render(self, locked: Locked) -> dict:
        """把回执的三个 key 换成自然语言（`text_of` 未装时原样返回 key）。

        **引擎不生成行文** —— 缺 key 时原样透出，让上层一眼看出文案表漏了哪条。
        """
        f = self._text_of
        return {
            "label": f(locked.label_key) if f else locked.label_key,
            "locked": f(locked.locked_text) if f else locked.locked_text,
            "progress": (f(locked.progress_text) if (f and locked.progress_text)
                         else locked.progress_text),
        }

    def audit(self) -> list:
        """只报不改（对齐既有 `admission` 的自检口径）。三类问题：

        1. 同目标多条覆盖且 `order` 相同 ⇒ 取条顺序只靠声明序，**脆**
        2. 同目标多条覆盖 ⇒ 提示（可能是有意的分层，也可能漏了 order）
        3. 同条目内三个文案 key 两两相同 ⇒ 多半是复制粘贴没改
        """
        out: list[str] = []
        for tg, ids in sorted(self._by_target.items()):
            if len(ids) > 1:
                orders = [self._order[e] for e in ids]
                if len(set(orders)) != len(orders):
                    dup = sorted({o for o in orders if orders.count(o) > 1})
                    out.append(
                        f"目标 {tg!r} 被 {len(ids)} 条覆盖但 order 重复 {dup} "
                        f"⇒ 取条顺序只靠声明序（脆）：{ids}")
                else:
                    out.append(f"目标 {tg!r} 被 {len(ids)} 条覆盖（取 order 最小者 {ids[0]!r}）")
        for eid, e in self._entries.items():
            keys = [e["label_key"], e["locked_text"], e["progress_text"]]
            keys = [k for k in keys if k]
            if len(set(keys)) != len(keys):
                out.append(f"解锁条目 {eid!r} 的文案 key 有重复 ⇒ 多半是复制粘贴没改：{keys}")
        return out
