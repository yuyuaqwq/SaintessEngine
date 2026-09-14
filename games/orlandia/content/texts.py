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
    """当前生效的声明文件路径（宿主薄壳注入的取件优先）。"""
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
