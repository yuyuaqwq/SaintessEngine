# -*- coding: utf-8 -*-
"""版本与兼容性检查（框架契约的一部分）。

包版本语义 `major.minor.patch`。**1.0 之前 API 面仍可能变动**：
`__all__` 里的符号是稳定面，其余模块路径可能调整（调整会在 CHANGELOG 记录）。

0.2.0（2026-09-11）：新增**声明驱动**两类能力 —— `command.CommandRegistry`
（指令声明：装载/查询/匹配/派生/漂移自检）与 `text.TextTable`（文案模板：装载/
渲染/缺失自检）。均为**可拔插**：不装载 = 零行为，不改变既有 API 语义。

游戏包 → 框架的版本声明
-----------------------
游戏包清单 `game.json` 的 `engine` 字段声明它需要的框架版本，例如:

    "engine": ">=0.1"                 # 只要求不低于 0.1
    "engine": ">=0.1,<0.2"            # 区间
    "engine": "==0.1.0"               # 精确（不推荐，升级会卡住）

**约定（设计稿 framework-editor-design.md §1）**：不满足时调用方显式报错，
**不静默降级** —— 否则会变成「配了不生效」这类最难查的故障。

用法::

    from saintess_engine import version as V
    ok, note = V.check(">=0.1")        # → (True, "框架 0.1.0 满足 >=0.1")
    ok, note = V.check(">=9")          # → (False, "框架 0.1.0 不满足 >=9（需要 ≥9）")
"""
from __future__ import annotations

import re

__version__ = "0.2.0"

# 版本元组（便于程序比较）
VERSION_INFO: tuple = tuple(int(x) for x in re.findall(r"\d+", __version__)[:3]) or (0,)
VERSION_INFO = tuple(list(VERSION_INFO) + [0] * (3 - len(VERSION_INFO)))

_OPS = (">=", "<=", "==", "!=", ">", "<")
_CLAUSE = re.compile(r"^\s*(>=|<=|==|!=|>|<)?\s*v?(\d+(?:\.\d+)*)\s*$")


def parse(text: str) -> tuple:
    """'0.1.0' / 'v1.2' → (0,1,0) / (1,2)。非法输入抛 ValueError。"""
    parts = re.findall(r"\d+", str(text or ""))
    if not parts:
        raise ValueError(f"不是合法版本号：{text!r}")
    return tuple(int(x) for x in parts[:3])


def _cmp(a: tuple, b: tuple) -> int:
    """前缀语义比较：短的一方按 0 补齐（'0.1' == '0.1.0'）。"""
    n = max(len(a), len(b))
    a2 = tuple(list(a) + [0] * (n - len(a)))
    b2 = tuple(list(b) + [0] * (n - len(b)))
    return (a2 > b2) - (a2 < b2)


def satisfies(requirement: str, version: str | None = None) -> bool:
    """判断 `version`（默认当前框架版本）是否满足 `requirement`。

    支持逗号分隔的多条件（全部满足才算通过）、`v` 前缀、`>=0.1` 这类单侧约束。
    空需求视为满足（游戏包可以不声明）。
    """
    req = str(requirement or "").strip()
    if not req:
        return True
    cur = parse(version or __version__)
    for raw in req.split(","):
        m = _CLAUSE.match(raw)
        if not m:
            raise ValueError(f"无法解析版本需求片段：{raw!r}（示例：'>=0.1' 或 '>=0.1,<0.2'）")
        op, num = m.group(1) or "==", m.group(2)
        c = _cmp(cur, parse(num))
        # ⚠️ fail-closed（2026-09-18 修）：本表不得留「未知写法 → 放行」的口子——原表含
        #   `"": True`（未识别运算符被吞成恒真），与模块约定「不满足要显式报错、不静默
        #   降级」相悖。删掉并改用 .get(op, False)：未识别运算符一律不满足（绝不静默放行）。
        if not {">=": c >= 0, "<=": c <= 0, "==": c == 0, "!=": c != 0,
                ">": c > 0, "<": c < 0}.get(op, False):
            return False
    return True


def check(requirement: str, version: str | None = None) -> tuple:
    """→ (是否满足, 说明文案)。解析失败也算不满足（fail-closed，不静默放行）。"""
    cur = version or __version__
    req = str(requirement or "").strip()
    if not req:
        return True, f"框架 {cur}（游戏包未声明版本要求）"
    try:
        ok = satisfies(req, cur)
    except ValueError as e:
        return False, f"框架 {cur}；版本需求无法解析：{e}"
    if ok:
        return True, f"框架 {cur} 满足 {req}"
    return False, f"框架 {cur} **不满足** {req}（游戏包要求：{req}）"
