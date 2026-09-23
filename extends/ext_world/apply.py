# -*- coding: utf-8 -*-
"""`ext_world` 的入口 —— 按包契约提供 `install_engine()`。

本包是**纯形状库**（`Space` / `Admission` / `Progress` / `Roster` + 拓扑注册表），
零引擎依赖（只 import `__future__` 与 `typing`）：

* 空间形状在被**构造**的那一刻才算（`Space(nodes=…, topology=…)`）；拓扑注册表 `TOPOLOGIES`
  是**内容侧**通过 `register_topology()` 按需填的 —— 引擎不预设形状集合，
  因此没有「全局一次」的装配动作可做。
* 运行形状（准入链 / 进度 / 名单）同样是内容侧持实例、按需取用的形状，
  判定与措辞分离（`check` 说通过与否，`reason` 负责怎么说），不碰引擎任何注册表。

所以这里没有安装动作 —— 入口存在是为了满足包契约（包根 `apply.py` + `install_engine()`），
并且让 `load_stack()` 的加载链对「能力包」与「形状包」完全同形；
将来本包真需要引擎级装配时，落点是这个函数，而不是靠猜 import 顺序。

数据包要用它：在 `game.json` 里声明 `"depends": ["ext_world"]`，
然后 `from ext_world.space import Space` / `from ext_world.run import Progress` 直接取用。
"""
from __future__ import annotations


def install_engine() -> None:
    """本包没有引擎级装配（纯形状库）—— 保留函数体为空且显式说明，不留含糊的空壳。"""
    return None
