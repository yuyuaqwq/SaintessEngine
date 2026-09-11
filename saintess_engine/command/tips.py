# -*- coding: utf-8 -*-
"""提示语骨架 —— 从分类提示库里随机抽一条（面板底部引导那种）。

纯形状：分类 → 池 → 随机取一条 → 统一前缀。
**分类内容由使用方提供**（框架不预设任何提示文案）。
"""
from __future__ import annotations

import random
import re
from typing import Iterable, Mapping, Optional, Sequence

__all__ = ["pick_tip", "EMOJI_HEAD_RE"]

# 行首 emoji（含变体选择符）—— 条目自带 emoji 时不再叠加前缀，避免「💡 📖」双 emoji
EMOJI_HEAD_RE = re.compile(r"^[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]")

DEFAULT_PREFIX = "💡 "


def pick_tip(pool_map: Mapping[str, Sequence[str]], cat: str, *,
             common_key: str = "common",
             fallback: Optional[Iterable[str]] = None,
             prefix: str = DEFAULT_PREFIX) -> str:
    """从 `pool_map[cat]`（回退 `pool_map[common_key]`）随机抽一条并加前缀。

    * 两级回退：`cat` → `common_key` → `fallback`（默认单条兜底文案）
    * 条目自身以 emoji 开头 → 原样返回（不叠前缀）
    * 池为空且无兜底 → 返回空串（调用方据此可跳过该行）
    """
    pool = pool_map.get(cat) or pool_map.get(common_key) or ()
    if not pool:
        pool = tuple(fallback) if fallback else (DEFAULT_TIP,)
    if not pool:
        return ""
    t = random.choice(list(pool))
    if t and EMOJI_HEAD_RE.match(str(t)):
        return str(t)
    return prefix + str(t)


DEFAULT_TIP = "看看『帮助』了解更多"
