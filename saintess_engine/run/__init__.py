# -*- coding: utf-8 -*-
"""运行形状（run）—— 一次运行的三件事：**谁能进** · **谁在里面** · **打到哪了**。

**零知识**：引擎不认「副本 / 层 / 房间 / 队伍 / 队长 / 钥匙」，只认
`rule` / `node` / `pool` / `budget` / `member` / `leader`。取值与措辞全由内容侧给。

对外三件东西::

    from saintess_engine.run import Admission, Rule, Progress, Roster

    adm = Admission([Rule("size", check=size_ok, reason="人数不够"),
                     Rule("key", check=has_key, reason=key_text, consume=deduct_key)])
    v = adm.check(ctx)          # 首拒即返；consume 延迟到全过才执行一次
    if not v.ok:
        show(v.reason)          # 措辞由内容侧给

    p = Progress([{"key": "l1"}, {"key": "l2"}])
    p.push("l1", "units", mon); p.take("l1", "units"); p.left("l1", "units")
    p.node_cleared("l1"); p.is_last(); p.advance(); p.goto("l1")
    p.set_budget("coin", 500); p.spend("coin", 300)     # 不足只给剩余

    r = Roster(["1", "2"], leader="1")
    r.alive("2"); r.living(); r.keep(lambda m: m in party); r.sort_by(key, reverse=True)

细节见 `admission.Rule` / `progress.Progress` / `roster.Roster`；
形状判据与门禁口径见 `docs/engine-wiki/reference/run.md`。
"""
from __future__ import annotations

from .admission import DENY, PASS, SKIP, Admission, Rule, Verdict
from .progress import Progress
from .roster import Roster

__all__ = [
    # 准入链
    "Admission", "Rule", "Verdict", "PASS", "DENY", "SKIP",
    # 进度 / 名单
    "Progress", "Roster",
]
