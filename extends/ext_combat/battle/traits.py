# -*- coding: utf-8 -*-
"""actor 身上的**内容侧标签**（traits）—— 引擎只做「有没有这个标签」的判定，不认标签叫什么。

★ 2026-09-25（引擎审计 E3）：原先引擎里写死 `is_boss or role == "boss"`（控制时长减半、
  DoT 对 boss/elite 打折）—— 引擎认得「boss」这个游戏概念 ✗。
  现在两处都改成：**标签名单由声明给**（控制的 `ctrl_half_traits` / DoT 周期的 `trait_tags`），
  引擎只问 `traits.has_any(actor, 名单)`。标签名（"boss"/"elite"/别的）全是内容侧的事。

口径
----
* actor 上的载体 = `actor["traits"]`（list/tuple/set 皆可；内容侧写，引擎只读）。
* 空名单 / 无该字段 / 空标签 ⇒ 一律 False（**不声明 = 这条规则不适用于任何人**，零兜底）。
"""
from __future__ import annotations

__all__ = ["of", "has", "has_any"]


def of(actor) -> tuple:
    """这个 actor 身上的标签（元组；没有就是空）。"""
    if not actor:
        return ()
    t = actor.get("traits")
    if not t:
        return ()
    if isinstance(t, (list, tuple, set, frozenset)):
        return tuple(str(x) for x in t if str(x))
    return (str(t),)


def has(actor, tag) -> bool:
    """身上有没有 `tag` 这个标签（`tag` 为空 ⇒ False）。"""
    t = str(tag or "")
    return bool(t) and t in of(actor)


def has_any(actor, tags) -> bool:
    """名单里有没有一个命中的（名单为空 ⇒ False）。"""
    want = {str(x) for x in (tags or ()) if str(x)}
    return bool(want) and bool(want & set(of(actor)))
