# -*- coding: utf-8 -*-
"""对话树与会话游标形状 —— 扩展包 `ext_dialogue`。

原在 `saintess_engine/` 里，2026-09-23 包栈重构时抽成扩展包（模块内容未改，只改
了指向引擎的相对导入）。数据包要用：`game.json` 里声明 `"depends": ["ext_dialogue"]`。

★ 审计 L1185 第 4 条（2026-09-29 修复）：本文件原先是一层**门面 re-export**
  （`from .dialogue import (Dialogue, Cursor, END_KEY)` + `__all__`），而它的
  原文 docstring 教人把引擎门面导入改到**本包根**（该建议已作废，见下）
  —— **这条建议至今无人执行**：全仓（含 orlandia 与全部测试）grep
  `from ext_dialogue import` = **0 处**，所有人都走 `ext_dialogue.dialogue.*` 子路径。

⇒ 按「不留兼容壳」把门面**删净**（不留别名、不留兼容分支），并同步改掉两处
  仍在教人走门面的文字：
  · 本文件 docstring —— 改成实况（唯一取件口 = `ext_dialogue.dialogue`）；
  · `docs/engine-wiki/reference/api.md` —— 那一行 import 改逐字真路径。
  装配入口 `ext_dialogue/apply.py::install_engine()` 不受影响（它在本包内）。

判据：`tests/test_dialogue_facade_surface.py` —— 钉住「包根不得再导出那三个名字」
（门面复活即判红），并断言文档与 apply.py 的 import 写法与实际取件口一致。
"""
