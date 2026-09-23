# -*- coding: utf-8 -*-
"""`ext_dialogue` 的入口 —— 按包契约提供 `install_engine()`。

对话形状是**纯形状库**（`Dialogue` / `Cursor` / `END_KEY`），不往引擎任何注册表里塞东西：
- **零取值**：结束哨兵、兜底台词、条件名、自动文本源取值全在调用方的**注入面**上给，
  模块里没有任何一个游戏取值字面量；
- **零引擎依赖**：本模块只 import 标准库（`collections.abc.Mapping`），不 import 引擎任何模块，
  也不 import 内容侧的谓词注册表（条件口只要求鸭子类型的 `get(key)`）；
- **构造 O(1)**：`Dialogue(...)` 只存引用 + 校验注入面，不遍历树、不建索引、不落盘。

所以这里没有「安装动作」—— 入口存在是为了满足包契约（`content/apply.py` 惯例的扩展包版本：
包根 `apply.py`），并让 `load_stack()` 的加载链对两种包完全同形。
真正要装配的是**台词、条件谓词、动作表与存档键名**，那些属数据包（内容取值）。

数据包要用它：在 `game.json` 里声明 `"depends": ["ext_dialogue"]`，
然后 `from ext_dialogue.dialogue import END_KEY, Cursor, Dialogue` 直接取用
（对话树本体、NPC id、结束哨兵由数据包的 `content/data/*.json` 给）。
"""
from __future__ import annotations


def install_engine() -> None:
    """本包没有引擎级装配（纯形状库，无注册表副作用）—— 保留函数体为空且显式说明。"""
    return None
