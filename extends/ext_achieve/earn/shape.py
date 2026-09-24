# -*- coding: utf-8 -*-
"""逐条求值形状（`ext_achieve` ④）：判定上下文外壳 + 注册表求值 + 参数化条件兜底。

本模块收「一族条目（每条一个 id）逐条判是否达成」这台机器（2026-09-24 B2-S3 从数据包抽入）。
**条目表、判定函数、参数化条件的口径全部由调用方给** —— 形状只提供三件事：

* `EvalCtx`      —— 判定上下文外壳：一组由内容侧定名的字段 + 钩子表（命令层专属能力）
  + 一个**注入的读口**（`_db()`）。字段名 / 位置参数序是形状契约（判定函数按名取）。
* `ParamCond`    —— **参数化条件**：id 形如「前缀 + 类别 + 数字」⇒ 读「该类别等级 ≥ 数字」。
  前缀 / 类别集合 / 等级读取器都由调用方给（形状零内容词表）。
* `earned_flags` —— 逐条求值器：注册表命中 ⇒ 调判定函数；否则参数化兜底匹配 ⇒ 调它；
  都不中 ⇒ `False`（未知 id 安全降级）。返回与输入**同长同序**的真值列表。

装配纪律（与本包其它形状同一套，fail-loud）
-----------------------------------------
`bind(db=…)` 未装配就取读口 ⇒ **当场报错**：不给「空读口 ⇒ 一条都不达成」这种把
「装配忘了」伪装成「条件不满足」的降级。注入的是**对象本身**（不复制、不包壳）。

★ 本模块零内容词表：id 形态、类别名、条目表、判定函数一律调用方注入。
"""
from __future__ import annotations

import re

__all__ = ["EvalCtx", "ParamCond", "bind", "earned_flags"]

_DB = None      # 注入的读口（存档 / 目录 / 任何调用方定义的取数面）


def bind(db=None) -> None:
    """注入读口（= `EvalCtx._db()` 的返回物）。

    `None` = 清空 —— 回到未装配态（取用即报错）；只收位置/关键字 `db`，不设第二个注入口。
    """
    global _DB
    _DB = db


class EvalCtx:
    """判定上下文外壳。

    * 位置参数序 `(group_id, qq_id, player, stats, rep, quests, hooks)` 与字段名
      （含 `_focus`）都是**形状契约**：数据侧的判定函数按名取它们，改名 / 改序 = 改契约。
    * `hooks` = 命令层专属能力表（`{名字: 可调用}`）；`hook()` 只做「有就转给、没有回 `None`」，
      形状不解释任何钩子名。
    * `_db()` = 注入的读口；未 `bind` ⇒ 当场报错。
    """

    def __init__(self, group_id, qq_id, player, stats, rep, quests, hooks=None):
        self.group_id = group_id
        self.qq_id = qq_id
        self._focus = player or {}
        self.stats = stats or {}
        self.rep = rep or {}
        self.quests = quests or {}
        self.hooks = hooks or {}

    def _db(self):
        """注入的读口（未装配 ⇒ 当场报错，不返回空壳）。"""
        if _DB is None:
            raise RuntimeError("%s 未装配：先 bind(db=…) 再取用（fail-loud）" % __name__)
        return _DB

    def hook(self, name, *args, **kwargs):
        """调用命令层钩子：有则转给，没有回 `None`（不抛、不猜）。"""
        fn = self.hooks.get(name)
        if fn:
            return fn(*args, **kwargs)
        return None

    def __repr__(self) -> str:
        return "EvalCtx(group_id=%r, qq_id=%r)" % (self.group_id, self.qq_id)


class ParamCond:
    """参数化条件：`<prefix><类别><数字>` ⇒ 「该类别的等级 ≥ 数字」。

    * `prefix`   —— 前缀（内容侧的 id 命名约定）
    * `keys`     —— 允许的类别集合（内容侧键名）
    * `level_of` —— 读取器 `(ctx, key) -> 等级`

    前缀不匹配 / 类别不在集合里 / 形状不是「前缀 + 小写字母 + 数字」⇒ 一律 `False`
    （不抛、不点名：与「未知 id 不达成」的原地兜底同口径）。
    """

    def __init__(self, prefix, keys, level_of):
        if not isinstance(prefix, str) or not prefix:
            raise ValueError("prefix 必须是非空字符串：%r" % (prefix,))
        if not callable(level_of):
            raise TypeError("level_of 必须可调用，收到 %s" % type(level_of).__name__)
        self.prefix = prefix
        self.keys = frozenset(keys)
        self._level_of = level_of
        self._re = re.compile(r"^%s([a-z]+)(\d+)$" % re.escape(prefix))

    def parse(self, tid):
        """id → `(类别, 阈值)`；不匹配 / 类别未知 ⇒ `None`。"""
        m = self._re.match(tid) if isinstance(tid, str) else None
        if m is None:
            return None
        key = m.group(1)
        if key not in self.keys:
            return None
        return key, int(m.group(2))

    def matches(self, tid) -> bool:
        """这条 id 是否归本条件管（供求值器挑兜底）。"""
        return self.parse(tid) is not None

    def check(self, tid, ctx) -> bool:
        """判定一条 id：读到的等级 ≥ 阈值。"""
        parsed = self.parse(tid)
        if parsed is None:
            return False
        key, need = parsed
        return self._level_of(ctx, key) >= need

    def __repr__(self) -> str:
        return "ParamCond(prefix=%r, keys=%r)" % (self.prefix, tuple(sorted(self.keys)))


def _id_of(entry):
    """条目 → id：`dict` 取 `"id"`（缺键照旧抛 `KeyError`）、其余原样（字符串 id 即 id）。"""
    return entry["id"] if isinstance(entry, dict) else entry


def earned_flags(entries, ctx, conditions, fallback=None):
    """逐条求值：注册表命中 ⇒ 调判定函数；否则参数化兜底 ⇒ 调它；都不中 ⇒ `False`。

    * `entries`    —— 条目序列（`dict` 取 `"id"`，或直接是 id 串），**输入序即返回序**
    * `conditions` —— 注册表（有 `get(name) -> fn | None`，如引擎 `saintess_engine.conditions.Conditions`）
    * `fallback`   —— 参数化条件（有 `matches(id)` / `check(id, ctx)`，如 `ParamCond`）

    返回列表与 `entries` **同长同序**；判定函数的返回值**原样收进来**（不替内容侧做布尔归一）。
    """
    out = []
    for entry in entries:
        tid = _id_of(entry)
        fn = conditions.get(tid)
        if fn is not None:
            out.append(fn(ctx))
        elif fallback is not None and fallback.matches(tid):
            out.append(fallback.check(tid, ctx))
        else:
            out.append(False)
    return out
