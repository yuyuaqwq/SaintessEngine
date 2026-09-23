# -*- coding: utf-8 -*-
"""`ext_effect` 的入口 —— 按包契约提供 `install_engine()`。

本包当前是**纯形状库**（场景交互效果层：`POI_EFFECTS` 注册表 + `PoiContext` + `execute_poi`）：
它不往引擎任何注册表里塞东西 —— 装不装这个包，引擎其它部分行为一致。所以这里没有
「安装动作」；入口存在是为了满足包契约（扩展包版 `apply.py`，惯例在包根），并让
`load_stack()` 的加载链对两种包完全同形。

数据包要用它：在 `game.json` 里声明 `"depends": ["ext_effect"]`，然后

    from ext_effect.effects import POI_EFFECTS, PoiContext, execute_poi

★ 注入面（本包**只**读这三样，其余一律不 import）：
  · `ctx.host`   —— 写库五动词（真源 = 宿主的库）
  · `ctx.dom`    —— 内容域访问（材料表 / 两个文案池 / 图纸与装备生成器 / 副本名单视图）
  · `ctx.text` / `ctx.static` —— 文案渲染（真源 = 数据包的文案表）
三者缺一个 ⇒ `AttributeError`（fail-loud，不静默吞）。
"""
from __future__ import annotations


def install_engine() -> None:
    """本包没有引擎级装配（纯形状库）—— 保留函数体为空且显式说明，不留含糊的空壳。"""
    return None
