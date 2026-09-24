# -*- coding: utf-8 -*-
"""条件判定与规则触发形状 —— 扩展包 `ext_achieve` 的门面。

本包收「条件类」的通用形状（2026-09-24 起从数据包抽入，一个形状一步）：

* `cond.registry` —— 条件注册表：名字 → 判定函数（未知名按默认键兜底 · 声明表整表装配）
* `cond.envs`     —— 环境位图：场地 id × 注入的词表 → `{环境名: bool}`，配 `EnvCtx` 判定上下文
* `rule.engine`   —— 规则触发形状：`match_cond` 条件判定 + `fire` 触发序列（七个句柄全注入）
* `earn.shape`    —— 逐条求值形状：上下文外壳（钩子表 + 注入读口）+ 参数化条件 + `earned_flags`
* `ledger.shape`  —— 账本形状：解锁遍历 / 领取（三态机筛选 + 汇总发放 + 升级结算）/ 标签名 / 点数

数据包要用它：`game.json` 里声明 `"depends": ["ext_achieve"]`，然后

    from ext_achieve.cond import EnvCtx, Registry, bind_envs, envs_of
    from ext_achieve.rule import bind, fire
    from ext_achieve.earn import EvalCtx, ParamCond, bind, earned_flags
    from ext_achieve.ledger import bind, check, claim, labels, points

本包**零游戏专名**（词表与判定函数一律由调用方给）、**不 import 任何数据包**。
"""
from .cond import EnvCtx, Registry, bind_envs, envs_of
from . import cond, earn, ledger, rule

__all__ = [
    "cond", "earn", "ledger", "rule",
    "Registry",
    "EnvCtx", "bind_envs", "envs_of",
]
