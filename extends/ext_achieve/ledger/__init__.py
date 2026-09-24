# -*- coding: utf-8 -*-
"""账本形状 —— `ext_achieve.ledger` 的门面。

* `shape.bind`   注入二十个句柄（条目表 / 账本读写 / 判据 / 文案 / 三态机 / 奖励发放…）
* `shape.check`  遍历判定 → 落库解锁 → 返回新解锁条目（带奖励摘要）
* `shape.claim`  领取全部待领取（三态机筛档位 → 汇总 → 发放 → 升级结算 → 落库 → 回执）
* `shape.labels` 已解锁条目的标签名列表（源表序）
* `shape.points` 已解锁条目的点数合计（权重由调用方给）

数据包要用它：

    from ext_achieve.ledger import bind, check, claim, labels, points
    bind(entries=lambda: TABLE, ledger_of=…, mark=…, …)

本包**零游戏专名**（条目 / 判据 / 存档 / 文案 / 权重一律调用方给）、**不 import 任何数据包**。
"""
from .shape import REQUIRED, bind, check, claim, labels, points
from . import shape

__all__ = [
    "shape",
    "bind", "check", "claim", "labels", "points",
]
