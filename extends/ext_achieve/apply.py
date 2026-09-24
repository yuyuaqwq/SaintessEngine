# -*- coding: utf-8 -*-
"""`ext_achieve` 的入口 —— 按包契约提供 `install_engine()`。

本包是**纯形状库**（条件注册表 / 环境位图 / 规则触发 / 逐条求值 / 账本）：
判定函数、环境词表、声明表、条目表、文案全部由调用方给（注册进来 / 注入进来），
装不装这个包，引擎其它部分行为一致 ⇒ 没有「安装动作」可做。

入口存在是为了满足包契约（包根 `apply.py` + `install_engine()`），
让 `load_stack()` 的加载链对「能力包」与「形状包」完全同形。

数据包要用它：在 `game.json` 里声明 `"depends": ["ext_achieve"]`，然后

    from ext_achieve.cond import EnvCtx, Registry, bind_envs, envs_of
    from ext_achieve.rule import bind, fire
    from ext_achieve.earn import EvalCtx, ParamCond, bind, earned_flags
    from ext_achieve.ledger import bind, check, claim, labels, points

★ 装配纪律（本包三块形状 `cond` / `rule` / `earn` / `ledger` 同一套）：**未装配即取用当场报错** ——
不许出现「空表 ⇒ 静默全 False」这种把「装配忘了」伪装成「判定不满足」的降级。
"""
from __future__ import annotations


def install_engine() -> None:
    """本包没有引擎级装配（纯形状库）—— 保留函数体为空且显式说明，不留含糊的空壳。"""
    return None
