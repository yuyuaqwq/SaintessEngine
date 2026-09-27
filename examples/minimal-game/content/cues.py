# -*- coding: utf-8 -*-
"""表现事件（cue）订阅声明 —— 「结算发事实、表现由订阅方渲染」的内容半边。

引擎侧迁移一个点位之后就不再自己拼那句话：它发一条 cue，由**本表声明的订阅者**渲染。
措辞**不在这里** —— 它走注入给 `Battle(text=…)` 的文案表（本示例未注入文案表 ⇒
引擎过渡期的兜底模板，输出与迁移前逐字节相同）。

形状与三条硬规矩（同步就地 / 只读契约 / fail-closed 三层）见 `saintess_engine/cues.py`。
本表的一处声明 = `{"kind": "text", "key": <文案表 key>}`；key 与 cue 同名（同名即接口，
不造映射表）。
"""
from __future__ import annotations

#: cue 名 → 订阅者（顺序 = 渲染顺序）。**已迁移的点位必须在这里各有一条**，
#: 否则引擎装配期对账会抛（缺订阅 = 玩家会丢行，不许静默）。
SUBS = {
    "battle.landing.dodged": ({"kind": "text", "key": "battle.landing.dodged"},),
    "battle.landing.element_immune": ({"kind": "text", "key": "battle.landing.element_immune"},),
    "battle.landing.resist_reduce": ({"kind": "text", "key": "battle.landing.resist_reduce"},),
}


def cue_subs() -> dict:
    """引擎 hook `cue_subs_fn` 的供体（装配点见 `content/apply.py::install_engine`）。"""
    return SUBS


__all__ = ["SUBS", "cue_subs"]
