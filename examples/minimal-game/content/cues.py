# -*- coding: utf-8 -*-
"""表现事件（cue）订阅声明 —— 「结算发事实、表现由订阅方渲染」的内容半边。

引擎侧迁移一个点位之后就不再自己拼那句话：它发一条 cue，由**本表声明的订阅者**渲染。
措辞**不在这里** —— 它在 `content/texts.py` 的文案表里（`Battle(text=…)` 注入）；
本表只写 key。表里缺一条已迁移的 key ⇒ 引擎**报错**（诊断 + 一行可读坏数据），
不会有任何引擎兜底。

形状与硬规矩（同步就地 / 只读契约 / fail-closed）见 `saintess_engine/cues.py`。
本表的一处声明 = `{"kind": "text", "key": <文案表 key>}`；key 与 cue 同名（同名即接口，
不造映射表）。
"""
from __future__ import annotations

from .texts import TEMPLATES

#: cue 名 → 订阅者（顺序 = 渲染顺序）。**已迁移的点位必须在这里各有一条**，
#: 否则引擎装配期对账会抛（缺订阅 = 玩家会丢行，不许静默）。
#: ★ 直接由文案表的 key 生成：**订阅表与文案表同源**，加一条文案就自动多一条订阅
#:   （两张表各自手写一份 = 双源，正是要防的）。
SUBS = {key: ({"kind": "text", "key": key},) for key in TEMPLATES}


def cue_subs() -> dict:
    """引擎 hook `cue_subs_fn` 的供体（装配点见 `content/apply.py::install_engine`）。"""
    return SUBS


__all__ = ["SUBS", "cue_subs"]
