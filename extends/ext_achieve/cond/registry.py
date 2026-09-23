# -*- coding: utf-8 -*-
"""条件注册表形状（`ext_achieve` ①）：名字 → 判定函数，外加「未知名按默认键兜底」这条口径。

数据包侧的用法（原 `content/hidden_cond.py` 那套写法一字不用改）：

    from ext_achieve.cond import Registry

    _REG = Registry(default_key="any")
    CONDITIONS = _REG.table                 # 旧名保留：普通 dict，就地维护
    register = _REG.register
    _REG.register_specs(_load_specs("hidden"))    # 声明表整表装配（编译交给引擎）
    ...
    _REG.check(cond_name, ctx)

口径（逐条对着原地实现，不是「顺手改成更合理的样子」）
------------------------------------------------------
· **注册即落表**：`table[name] = fn`，**后注册者胜**；已存在的键不搬家（位置随首次插入）。
· **查表**：`table.get(name or 默认键, table[默认键])` —— 与原地 `CONDITIONS.get(cond or "any",
  CONDITIONS["any"])` 逐字同口径：默认键缺失时**当场炸**（KeyError），不返回「静默不满足」。
· **表是普通 dict**：调用方照旧可以 `CONDITIONS["x"] = fn` / `.update(...)` / `.pop(...)`；
  形状不另设私有层 —— 「注册即生效 / 注册可撤销」两条都因为它是同一份 dict 而白拿。

为什么编译交给引擎：声明节点（`const` / `field` / `op` …）的形状与算子表是**引擎协议**
（`saintess_engine.conditions.declarative`）；本形状只负责「登记进哪张表 + 怎么查」。
"""
from __future__ import annotations

from saintess_engine.conditions.declarative import register_specs as _register_specs

__all__ = ["Registry"]


class Registry:
    """一张「名字 → 判定函数」的表 + 一条默认键兜底口径。

    `default_key` 是**口径的一部分**，不是可选项：查一个未注册的名字时用它兜底
    （「未知即放行 / 未知即拦截」各自的玩法不同，故由调用方定，形状不预设）。
    """

    def __init__(self, default_key: str):
        if not isinstance(default_key, str) or not default_key:
            raise ValueError("default_key 必须是非空字符串：%r" % (default_key,))
        self.table: dict = {}
        self.default_key = default_key

    # ── 登记 ────────────────────────────────────────────────────────────────
    def register(self, name, fn=None):
        """装饰器 / 直接两用：`@REG.register("k")` 或 `REG.register("k", fn)`。

        重复登记 = 后者胜（与原地 `CONDITIONS[name] = fn` 同）；要撤销就 `REG.table.pop(name)`。
        """
        if fn is None:
            def _deco(f):
                self.table[name] = f
                return f
            return _deco
        self.table[name] = fn
        return fn

    def register_specs(self, table, names=None):
        """声明表**整表**装配：任一条不合法 ⇒ 一条都不登记（先编译后登记，见引擎实现）。

        `table` = 引擎声明节点表；`names` = 多参旧签名的形参名序列（口径见
        `saintess_engine.conditions.declarative.register_specs`）。
        """
        return _register_specs(self.register, table, names)

    # ── 查表 / 求值 ─────────────────────────────────────────────────────────
    def has(self, name) -> bool:
        return name in self.table

    def names(self) -> tuple:
        """已登记的名字（声明序 = 登记序）。"""
        return tuple(self.table)

    def get(self, name):
        """取判定函数；未登记 → None（不抛，供调用方自行兜底）。"""
        return self.table.get(name)

    def check(self, name, ctx) -> bool:
        """`name`（空 / None → 默认键）→ 判定函数 → `fn(ctx)`。

        ★ 默认值是**立即求值**的：默认键没登记时，即便 `name` 命中了也会抛 KeyError ——
        与原地写法逐字同口径（「默认键必须存在」是装配期契约，不是求值期的意外）。
        """
        table = self.table
        fn = table.get(name or self.default_key, table[self.default_key])
        return fn(ctx)
