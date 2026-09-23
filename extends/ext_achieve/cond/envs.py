# -*- coding: utf-8 -*-
"""环境位图形状（`ext_achieve` ②）：场地 id → `{环境名: bool}`，按「关键词包含」分类。

★ 本模块**零内容词表**：`forest` / `water` / `ruin` 那类环境名和它们的关键词都是
**某款游戏的内容**（地名怎么起名、有哪些环境族），一律由调用方注入 ——
形状只提供「**id × 词表 → 位图**」这台机器。

用法：

    from ext_achieve.cond import EnvCtx, bind_envs, envs_of

    bind_envs(ENV_KEYWORDS)        # {环境名: (关键词, ...)}；也收「零参可调用」（惰性取值）
    envs = envs_of(场地_id)         # {环境名: bool}
    ctx  = EnvCtx(场地_id, 载体, is_night, envs)
    ctx.env("forest")              # 位图取真值（缺项 = False）

装配纪律（fail-loud）
---------------------
未装配就取用 ⇒ **当场报错**。不给「空表 ⇒ 全 False」这种静默降级：那会把
「装配忘了」伪装成「环境不匹配」，而环境不匹配的后果是「某条判定永不成立」这种
只能靠翻数据才能发现的错。
"""
from __future__ import annotations

from collections.abc import Mapping

__all__ = ["EnvCtx", "bind_envs", "envs_of"]

_INJ = None      # 注入的环境词表：Mapping 或 零参可调用


def bind_envs(table) -> None:
    """注入环境词表（`{环境名: (关键词, ...)}`，或返回它的零参可调用）。

    ★ 注入的是**对象本身**，形状**不复制**：调用方后续就地改表（加环境族 / 补关键词）
    立刻生效 —— 与原地「模块级表 + 调用时读」的行为同。
    """
    global _INJ
    if not isinstance(table, Mapping) and not callable(table):
        raise TypeError("环境词表必须是映射或零参可调用，收到 %s" % type(table).__name__)
    _INJ = table


def _table():
    if _INJ is None:
        raise RuntimeError(
            "ext_achieve.cond 未装配：先 bind_envs({环境名: (关键词, ...)}) 再取用（fail-loud）")
    return _INJ() if callable(_INJ) else _INJ


def envs_of(subject_id: str) -> dict:
    """按场地 id 计算环境位图（关键词**包含**匹配）—— 词表完全来自注入。"""
    return {name: any(k in subject_id for k in keys) for name, keys in _table().items()}


class EnvCtx:
    """判定上下文：场地 id / 场地载体 / 是否夜间 / 预计算位图。

    字段名 `envs` / `is_night` 是**声明表能取到的两个键**（数据里的 `field` 步链就写它们），
    改名等于改数据 —— 故这两个名字属于形状契约，不是实现细节。
    """

    def __init__(self, subject_id, subject, is_night, envs):
        self.subject_id = subject_id
        self.subject = subject
        self.is_night = is_night
        self.envs = envs

    def env(self, name) -> bool:
        """读位图（缺项 = False；None 值也归一成 False，口径同原地 `bool(...)`）。"""
        return bool(self.envs.get(name))

    def __repr__(self) -> str:
        return "EnvCtx(subject_id=%r, is_night=%r, envs=%r)" % (
            self.subject_id, self.is_night, self.envs)
