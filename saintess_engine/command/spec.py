# -*- coding: utf-8 -*-
"""指令声明表装载 —— 「一份声明表 → 注册表 + 有效表 + 目录」的统一形状。

为什么要有它
------------
声明驱动的做法（正则只在表里写一份）宿主已经落地，但**装载这段形状**原先住在宿主：
读 JSON、建 `CommandRegistry`、校验、派生有效表、拼目录 —— 语义相同而各写各的，
fail-closed 的口径也各写各的，迟早分叉（典型症状：一处「表坏了返回空表」、
另一处「表坏了抛错」，于是「配了不生效」只在某条路径上静默）。

本模块把**形状**收进引擎；宿主只提供两样东西：

* **表在哪**（路径；内容随游戏，不进引擎）
* **注册动作**（宿主平台的装饰器，例如把正则接到平台的注册表）

铁律（fail-closed，全部照 `version.py` 的同名条款）
--------------------------------------------------
1. 表缺失 / 为空 / JSON 坏 / 结构不对 / 正则非法 / key 重复 → **抛错**，不静默降级。
2. **单一来源**：有效表与注册表是同一份声明派生出来的
   （`source.pattern_map() == {k: spec.combined() for ...}`，门禁锁死）。
3. `pattern_map_from_table()` 是**纯函数**（不读文件、不碰磁盘）—— 给「只能标准库直载」
   的薄表场景用，避免为了派生一张表去 import 平台相关代码。

表的结构（宽容读入，写死的是「读不出来就抛」）
----------------------------------------------
    {"<key>": "正则"}                                   # 单正则简写
    {"<key>": ["正则", "别名正则"]}                      # 多正则（别名）
    {"<key>": {"patterns": [...], "desc": ..., "category": ..., "order": ...}}

用法::

    from saintess_engine.command import CommandSpecSource

    src = CommandSpecSource("data/command_specs.json", name="mygame.commands")
    src.pattern_map()        # {key: 合并正则}（多条 → (?:a)|(?:b)）
    src.spec("weekly")       # 拿一条声明的细节；没有 → KeyError（fail-closed）
    src.catalog()            # {分类: [声明, ...]}（仅 visible，按 order）
"""
from __future__ import annotations

import json
import os
from typing import Optional

from .registry import CommandRegistry, CommandSpec, combine_patterns

__all__ = [
    "load_table", "build_registry", "pattern_map_from_table", "catalog_of",
    "CommandSpecSource",
]


# ============================================================ 读表
def load_table(path: str) -> dict:
    """读声明表（原始 dict）。缺失 / 为空 / JSON 坏 / 结构不对 → 抛。"""
    if not path:
        raise ValueError("指令声明表路径为空")
    if not os.path.exists(path):
        raise FileNotFoundError("指令声明表不存在：%s" % path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not data:
        raise ValueError("指令声明表为空或格式不对（应为 {key: 声明}）：%s" % path)
    return data


def build_registry(table, *, name: str = "") -> CommandRegistry:
    """声明表 → `CommandRegistry`（顺手 `validate()`，有问题就抛，不留半成品）。"""
    reg = CommandRegistry.from_data(table, name=name)
    problems = reg.validate()
    if problems:
        raise ValueError("指令声明表有问题（%s）：%s" % (name or "<table>", "；".join(problems)))
    return reg


# ============================================================ 纯派生（不碰磁盘）
def pattern_map_from_table(table) -> dict:
    """声明表 → `{key: 合并正则}`（纯函数；多条正则 → `(?:a)|(?:b)`）。

    空正则 / 非字符串的项**跳过**（该项会在 `build_registry` 的校验里被点名）。
    """
    out = {}
    for key, val in (table or {}).items():
        if isinstance(val, str):
            pats = [val]
        elif isinstance(val, dict):
            pats = val.get("patterns", val.get("pattern"))
        else:
            # 非 str/dict 的项：只认序列（其余形状一律跳过，交给 build_registry 的校验点名）
            pats = val if isinstance(val, (list, tuple, set)) else ()
        if isinstance(pats, str):
            pats = [pats]
        combined = combine_patterns([p for p in (pats or ()) if isinstance(p, str) and p])
        if combined:
            out[str(key)] = combined
    return out


def catalog_of(registry: CommandRegistry) -> dict:
    """注册表 → `{分类: [声明, ...]}`（仅 visible，组内保持声明顺序）。"""
    out: dict = {}
    for spec in registry.visible():
        out.setdefault(spec.category or "其他", []).append(spec)
    return out


# ============================================================ 装载器（懒 + 缓存）
class CommandSpecSource:
    """一份声明表的装载器：注册表 / 有效表 / 目录 / 取声明，都从**同一份表**来。"""

    def __init__(self, path: str, *, name: str = "", registry: Optional[CommandRegistry] = None):
        self.path = os.path.abspath(path) if path else ""
        self.name = name or "command.spec"
        self._registry = registry

    # -------------------------------------------------- 内部
    def _reg(self) -> CommandRegistry:
        if self._registry is None:
            self._registry = build_registry(load_table(self.path), name=self.name)
        return self._registry

    # -------------------------------------------------- 读
    def table(self) -> dict:
        """原始声明表（每次都读盘：诊断/热更新看最新）。"""
        return load_table(self.path)

    def registry(self) -> CommandRegistry:
        """注册表（懒构建 + 缓存）。"""
        return self._reg()

    def reload(self) -> CommandRegistry:
        """丢掉缓存重建（改了表要生效时调用）。"""
        self._registry = None
        return self._reg()

    # -------------------------------------------------- 取/派生
    def spec(self, key: str) -> CommandSpec:
        """取一条声明。表里没有该 key → **抛 KeyError**（别让指令静默消失）。"""
        found = self._reg().get(key)
        if found is None:
            raise KeyError("指令声明表里没有 %r（表：%s）" % (key, self.path))
        return found

    def get(self, key: str) -> Optional[CommandSpec]:
        """软取（缺 → `None`），给「可有可无」的查询用。"""
        return self._reg().get(key)

    def pattern_map(self) -> dict:
        """有效表 `{key: 合并正则}`（与注册表同源）。"""
        return self._reg().pattern_map()

    def keys(self) -> tuple:
        return self._reg().keys()

    def visible(self) -> tuple:
        return self._reg().visible()

    def catalog(self) -> dict:
        """帮助/目录：`{分类: [声明, ...]}`。"""
        return catalog_of(self._reg())
