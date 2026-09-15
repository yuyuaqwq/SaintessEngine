# -*- coding: utf-8 -*-
"""包内文案表装载器（`content/texts.py`）—— 游戏仓 `game/core/texts.py`（96 行）**逐字端口**（B13-L7）。

**唯一真源已在包内**（★ P4′-B，2026-09-14）：`content/data/text_specs.json`
（对象 key 即文案标识；`_` 开头的是元信息，不入表）。本模块只做装载，一个字都没改文案
（铁律 2：数据一律导出器产出 / 代码只传槽位）。
本模块**自己定位**真源（`_HERE` 推出，不依赖宿主目录、不依赖任何环境变量），
宿主薄壳（`game/core/texts.py`）反过来取本模块的 `SPEC_PATH` 再注入（`bind_spec_path`，
取件式）—— 所以「宿主行为逐字不变」+「包自足」两条同时成立。
包内另有 `content/data/texts.json`：同一份声明的**导出投影**（无 `_meta`/`_categories`，
233 键逐值相同；给编辑器/域导出用，**不是**装载器真源）。

装载语义（与真源逐字相同）
--------------------------
* 引擎：`saintess_engine.text.TextTable`（纯计算、无 IO、无全局态）；
* 缺 key **不静默**：日志 ERROR + 返回 key 本身（玩家截图 + 值班日志双可见）；
* `reload()` 热重载；`audit()` 自检汇总；`load_error()` 最近一次装载失败原因。

⚠️ 路径取件为什么是「thunk」而不是常量
------------------------------------
`tests/test_texts_table.py` 会 `T.SPEC_PATH = 坏文件; T.reload()` 验证修复路径 ——
所以路径必须是**调用时**从宿主薄壳模块取的（`bind_spec_path(source=lambda: SPEC_PATH)`），
常量拷贝会让「改宿主 SPEC_PATH」失效（测试当场红）。

★ R5 修（P5D-2 §6.5：改 `SPEC_PATH` 后 `reload()` 不生效、`load_error` 恒空）
--------------------------------------------------------------------------
上一条 thunk 有个**反向**缺口：取件一旦注入，**包内常量就被永久遮蔽** ——
终态测试 `from content import texts as T` 改的是**包内** `SPEC_PATH`，而
`spec_path()` 直接返回注入取件（宿主壳那份），于是坏文件路径读不到：
`reload()` 照旧成功、`load_error()` 恒空、渲染照旧返回真文案（**静默**）。
修法是**单源裁定**（无开关、无第二份路径、无兜底）：

  ① 包内常量 `SPEC_PATH` **被显式改写** → 以包内为准（终态的唯一真源就是它）；
  ② 否则（包内常量仍是初始值）→ 用注入取件（宿主薄壳在位时 `T.SPEC_PATH` 可写，语义不变）。

判据：包内/宿主两侧「改谁的常量，谁生效」；`load_error()` 在坏文件下必须有原因。
"""
from __future__ import annotations

import json
import logging
import os

from saintess_engine.text import TextTable

_HOST_PKG = "data.plugins.dragonfall.game"
_HOST_PKG_FALLBACK = "game"

_HERE = os.path.dirname(os.path.abspath(__file__))          # <pkg>/content
# 包内真源：本模块自己定位（宿主 `game/data/text_specs.json` 只是构建期镜像）
SPEC_PATH = os.path.join(_HERE, "data", "text_specs.json")
#: 包内**初始**路径（`spec_path()` 的「包内常量是否被显式改写」判据；不随注入变）
_PKG_SPEC_PATH = SPEC_PATH
# 导出投影（编辑器/域导出用；非装载真源）
PROJECTION_PATH = os.path.join(_HERE, "data", "texts.json")

_SPEC_SOURCE = None     # 调用方注入的路径取件（宿主薄壳绑宿主模块的 SPEC_PATH）
_LOG_INJ = None         # 调用方注入的日志器（宿主 `log_setup.LOG`）
_TABLE = None           # type: TextTable | None
_LOAD_ERROR = ""        # 最近一次装载失败原因（空 = 正常）


def canonical_path() -> str:
    """真源路径的本包标识（不随注入变；门禁/运维用）。"""
    return SPEC_PATH


def bind_spec_path(source=None, path=None) -> None:
    """文案声明文件路径注入（幂等）。

    * `source`：**取件函数**（调用时求值）；宿主薄壳绑 `lambda: <宿主模块>.SPEC_PATH`
      —— 保持「宿主模块常量可被测试改写」的真源语义。
    * `path`：直接给常量路径（包内独立运行用）。
    """
    global _SPEC_SOURCE, SPEC_PATH
    if source is not None:
        _SPEC_SOURCE = source
    elif path is not None:
        _SPEC_SOURCE = None
        SPEC_PATH = path


def bind_log(log=None) -> None:
    """宿主日志器注入（幂等；缺省 → 宿主 `log_setup.LOG` → stdlib logger）。"""
    global _LOG_INJ
    if log is not None:
        _LOG_INJ = log


def spec_path() -> str:
    """当前生效的声明文件路径（单源裁定，见模块头注「★ R5 修」）。

    ① 包内 `SPEC_PATH` 被显式改写（`T.SPEC_PATH = …`，终态测试/编辑器路径）→ 以包内为准；
    ② 否则用宿主薄壳注入的取件（`bind_spec_path(source=…)`，其常量同样可写）。
    """
    if SPEC_PATH != _PKG_SPEC_PATH:
        return SPEC_PATH
    if _SPEC_SOURCE is not None:
        return _SPEC_SOURCE()
    return SPEC_PATH


def _log():
    """日志口：注入优先 → 宿主 `log_setup.LOG`（已加载时）→ stdlib logger。"""
    if _LOG_INJ is not None:
        return _LOG_INJ
    import sys
    for name in ("%s.log_setup" % _HOST_PKG, "%s.log_setup" % _HOST_PKG_FALLBACK):
        m = sys.modules.get(name)
        if m is not None and getattr(m, "LOG", None) is not None:
            return m.LOG
    return logging.getLogger("orlandia.texts")


def _on_miss(key, slots):
    """缺 key：打 ERROR 日志（唯一日志入口），返回值 None → 引擎继续走 fallback 分支
    （本表未配 fallback ⇒ 最终把 key 本身返回给玩家，看得见）。"""
    _log().error("文案缺 key：%s —— 请查 %s（槽位 %s）", key, spec_path(), sorted(slots or {}))
    return None


def _load_specs() -> dict:
    """读声明文件（唯一 IO 点）。任何异常 → 空表 + ERROR 日志，绝不静默吞掉。"""
    global _LOAD_ERROR
    path = spec_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception as exc:                        # 文件缺失/语法错
        _LOAD_ERROR = "%s: %s" % (type(exc).__name__, exc)
        _log().error("文案表装载失败（%s）：%s", path, _LOAD_ERROR)
        return {}
    if not isinstance(raw, dict):
        _LOAD_ERROR = "顶层不是对象"
        _log().error("文案表格式错误：顶层应为对象（%s）", path)
        return {}
    _LOAD_ERROR = ""
    return {k: v for k, v in raw.items() if not str(k).startswith("_")}


def table() -> TextTable:
    """文案表（懒建 + 缓存；此时内容层已就绪，无导入环）。"""
    global _TABLE
    if _TABLE is None:
        _TABLE = TextTable(_load_specs(), name="dragonfall-texts", on_miss=_on_miss)
    return _TABLE


def reload() -> TextTable:
    """热重载：丢掉缓存重新读文件（编辑器/测试改完 JSON 用）。"""
    global _TABLE
    _TABLE = None
    return table()


def text(key: str, **slots) -> str:
    """渲染带槽位的文案。"""
    return table().render(key, **slots)


def static(key: str) -> str:
    """渲染无槽位的文案（句壳固定）。"""
    return table().render(key)


def audit() -> dict:
    """自检汇总：{total, requested, missing, unused, problems}（门禁/值班用，只报告不抛）。"""
    return table().audit()


def load_error() -> str:
    """最近一次装载失败原因（空 = 正常）。"""
    return _LOAD_ERROR


__all__ = ["SPEC_PATH", "PROJECTION_PATH", "spec_path", "canonical_path",
           "bind_spec_path", "bind_log",
           "table", "reload", "text", "static", "audit", "load_error"]
