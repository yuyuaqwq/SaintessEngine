# -*- coding: utf-8 -*-
"""标签机制（tag）—— 注册表 + 统一查询面 + 层级匹配（引擎零游戏名词）。

照 GAS `GameplayTag` 那三件东西，落在本引擎既有的形状上：

  ① **注册表**：层级 tag 名（点分 `A.B.C`，父级 = 去掉最后一段）。名字的来源全在引擎之外或
     声明表里 —— 状态声明表（`EFFECT_RULES` 的键）、内容侧身份标签（`actor["traits"]`）、
     以及引擎**固定词汇表**那几个槽位名（`slots`）。引擎只做「名字 → 祖先/前缀」的结构运算，
     不认识任何游戏名词。
  ② **授予 / 撤销**：actor 身上的 tag 来自三处，查询口把它们合成**一个面**：
       · `actor["traits"]` —— 内容侧写的身份标签（扁平名）
       · `effects` 容器的**条目 key** —— 状态本身就是标签
       · 条目里的 `grants` —— 一条状态额外代表哪些 tag（一个状态授多个标签；见
         `actors.open_entry(..., grants=[...])`）
     **撤销** = 条目被清（时间到期 / 被消费 / 离场作废）即随之消失，不另开接口 ——
     标签的生命周期跟着状态容器走，不靠谁记得撤。
  ③ **查询**：`has` = GAS 的 HasTag 语义（**父级查得到子级**：查 `control` 命中 `control.stun`），
     `has_exact` 只认精确，另有 `has_any` / `has_all` / `match`；`sources_of` 报「哪几个来源
     授的这个 tag」（排障用）。空 tag / 空名单 ⇒ False（**不声明 = 这条规则不适用于任何人**）。

与 `traits`（身份标签）的关系：`traits.of/has/has_any` 保留为**精确面**（现行行为一字不动，
扁平名不受层级影响）；**全来源 + 层级**的判定一律走本模块。引擎新读点走本模块；老的散点按
`slots` 收口（名字归内容侧声明，引擎只按槽位取名字）。
"""
from __future__ import annotations

from typing import Iterable, Optional

from .diagnostics import diag as _diag      # 阶段/钩子出错的诊断通道（P-44）

TAG_SEP = "."

__all__ = [
    "TAG_SEP", "DEFAULT_SLOTS",
    "ancestors", "root_of", "name_match",
    "register", "register_many", "registered", "reset_registry",
    "slot", "of", "sources_of", "has", "has_exact", "has_any", "has_all", "match",
]

# 引擎**固定词汇表**里的槽位：槽位名（引擎词）→ 具体 tag 名（缺省 = 今天的名字）。
# 内容侧要换名 / 挂层级（例如把控制免疫改叫 `immune.control`）就在装配面声明
# `tag_slots_fn`（`saintess_engine.config.mount(tag_slots_fn=…)` ⇒ {槽位: tag}），
# 引擎只按槽位取名字，不认游戏名词。
DEFAULT_SLOTS = {
    "immune_control": "cc_immune",     # 控制免疫态（effects 条目，带刻数）
    "immune_dots": "immune_dots",      # DOT 免疫名单（actor 字段，值是类型名列表）
}

#: 已注册的 tag 名（内容侧声明过的）。注册只影响 `registered()` 这一面（审计/文档用），
#: 查询本身不要求先注册（**不声明 ≠ 不存在**：状态条目自己就是标签）。
_registry: set = set()


# ============================================================
# 名字结构（层级）
# ============================================================

def ancestors(tag) -> tuple:
    """`A.B.C` ⇒ `("A.B.C", "A.B", "A")`；空名 ⇒ 空元组。"""
    t = str(tag or "")
    if not t:
        return ()
    parts = t.split(TAG_SEP)
    return tuple(TAG_SEP.join(parts[:i]) for i in range(len(parts), 0, -1))


def root_of(tag) -> str:
    """一级前缀（`control.stun` ⇒ `control`）；没有点分 ⇒ 自身；空 ⇒ `""`。"""
    t = str(tag or "")
    return t.split(TAG_SEP, 1)[0] if t else ""


def name_match(name, query) -> bool:
    """名字层面的「含」判定：`query` 精确等于 `name`，或 `name` 是 `query` 的**子级**
    （按 `.` 边界；`controlx` 不算 `control` 的子级）。空 query ⇒ False。"""
    n, q = str(name or ""), str(query or "")
    if not n or not q:
        return False
    return n == q or n.startswith(q + TAG_SEP)


# ============================================================
# 注册表（内容侧声明的名字集合）
# ============================================================

def register(name) -> None:
    """登记一个 tag 名（内容侧声明）。空名忽略。"""
    t = str(name or "")
    if t:
        _registry.add(t)


def register_many(names: Iterable) -> None:
    for n in (names or ()):
        register(n)


def registered() -> frozenset:
    """已登记的名字（只读快照）。"""
    return frozenset(_registry)


def reset_registry() -> None:
    """清空注册表（测试/重装内容用）。"""
    _registry.clear()


# ============================================================
# 槽位（引擎固定词汇表 ↔ 具体 tag 名）
# ============================================================

def _slot_hook():
    """装配面的槽位声明（`tag_slots_fn -> {槽位: tag}`）；未装配 ⇒ None（用内建缺省）。"""
    try:
        from saintess_engine import config as _cfg
        fn = _cfg.optional_hook("tag_slots_fn")
    except Exception as _e:
        _diag(None, "tags._slot_hook", _e)
        return None
    if fn is None:
        return None
    try:
        got = fn()
    except Exception as _e:
        _diag(None, "tags._slot_hook · 取回执", _e)
        return None
    return got if isinstance(got, dict) else None


def slot(name: str) -> str:
    """槽位名（引擎词）→ 具体 tag 名。装配面没声明 ⇒ 内建缺省；槽位不存在 ⇒ KeyError
    （fail-closed：引擎不猜名字）。"""
    got = _slot_hook()
    if got and str(got.get(name) or "").strip():
        return str(got[name])
    return str(DEFAULT_SLOTS[name])


# ============================================================
# 统一查询面（traits ∪ effects 条目 key ∪ 条目 grants）
# ============================================================

_SRC_TRAITS = "traits"
_SRC_EFFECTS = "effects"
_SRC_GRANTS = "grants"


def _traits_of(actor) -> tuple:
    if not actor:
        return ()
    t = actor.get("traits")
    if not t:
        return ()
    if isinstance(t, (list, tuple, set, frozenset)):
        return tuple(str(x) for x in t if str(x))
    return (str(t),)


def _grants_of(entry) -> tuple:
    if not isinstance(entry, dict):
        return ()
    g = entry.get("grants")
    if not g:
        return ()
    if isinstance(g, (list, tuple, set, frozenset)):
        return tuple(str(x) for x in g if str(x))
    return (str(g),)


def of(actor, sources=("traits", "effects", "grants")) -> frozenset:
    """actor 身上**当前**的全部 tag（默认三个来源全算）。"""
    want = {str(s) for s in (sources or ())}
    out = set()
    if _SRC_TRAITS in want:
        out.update(_traits_of(actor))
    if _SRC_EFFECTS in want or _SRC_GRANTS in want:
        ef = (actor or {}).get("effects")
        if isinstance(ef, dict):
            for k, v in ef.items():
                if _SRC_EFFECTS in want:
                    out.add(str(k))
                if _SRC_GRANTS in want:
                    out.update(_grants_of(v))
    return frozenset(out)


def sources_of(actor, tag) -> tuple:
    """哪些来源授了这个 tag（排障/审计用）：`("traits",)` / `("effects", "grants")` …。"""
    t = str(tag or "")
    if not t:
        return ()
    hit = []
    if t in _traits_of(actor):
        hit.append(_SRC_TRAITS)
    ef = (actor or {}).get("effects")
    if isinstance(ef, dict):
        if t in {str(k) for k in ef}:
            hit.append(_SRC_EFFECTS)
        elif any(t in _grants_of(v) for v in ef.values()):
            hit.append(_SRC_GRANTS)
    return tuple(hit)


def has(actor, tag) -> bool:
    """身上有没有这个 tag —— **父级查得到子级**：查 `control` 命中 `control.stun`。
    空 tag ⇒ False。"""
    q = str(tag or "")
    if not q:
        return False
    return any(name_match(n, q) for n in of(actor))


def match(actor, tag) -> bool:
    """`has` 的别名（GAS 那边这个动作叫 MatchesTag）。"""
    return has(actor, tag)


def has_exact(actor, tag) -> bool:
    """只认精确名（不看子级、不看父级）。"""
    t = str(tag or "")
    return bool(t) and t in of(actor)


def has_any(actor, tags) -> bool:
    """名单里任意一个命中（层级语义同 `has`）；名单为空 ⇒ False。"""
    return any(has(actor, t) for t in (tags or ()) if str(t or ""))


def has_all(actor, tags) -> bool:
    """名单全部命中；名单为空 ⇒ False（空名单 = 不适用，不是「恒真」）。"""
    want = [t for t in (tags or ()) if str(t or "")]
    return bool(want) and all(has(actor, t) for t in want)
