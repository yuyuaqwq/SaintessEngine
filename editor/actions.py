# -*- coding: utf-8 -*-
"""机制动作清单（编辑器用）—— 包装框架工具 `tools/export_actions.py`。

用途：编辑器在编辑声明表（`passive_proc` / `effect_rules`）时，把自由字符串字段
`action` 变成「从真实注册的动作里选」，并按该动作的**实际消费参数**给出提示。

数据来源 = **静态 AST 扫描源码**（不是另行维护的声明表）：
  - 框架内置动作：`saintess_engine/**` 里的 `@register_action`
  - 游戏包动作：包目录里的 `@register_action`
由此得到的信息天然与实现一致，不会漂移。

对外接口：
    inventory(pkg_dir=None) -> dict      # 完整清单（同 export_actions.export）
    find(actions, name) -> dict | None   # 按名查一个动作
    suggest_keys(action) -> list         # 该动作的必填参数键（一键补键用）
"""
from __future__ import annotations

import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(HERE)

_cache: dict = {}


def _load_tool():
    """按路径加载 `tools/export_actions.py`（工具目录不是包，不能直接 import）。"""
    path = os.path.join(FW_ROOT, "tools", "export_actions.py")
    if not os.path.exists(path):
        return None
    spec = importlib.util.spec_from_file_location("_fw_export_actions", path)
    if not spec or not spec.loader:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def inventory(pkg_dir: str | None = None, *, use_cache: bool = True) -> dict:
    """动作清单。`pkg_dir` 给游戏包目录（额外扫它的 mech/）。

    **缓存策略**：只缓存「无包」（纯引擎内置 —— 跟框架版本走，很少变）。
    带包时**每次都重扫**：包内动作是用户正在写的代码，缓存会让人看到过期的动作清单
    （实测踩过：服务先启动、之后才写的 mech/actions.py 扫不出来，排查半天）。
    `use_cache=False` 可强制连引擎那份也重扫。
    """
    key = pkg_dir or ""
    cacheable = (not pkg_dir) and use_cache          # 只有纯引擎清单可缓存
    if cacheable and key in _cache:
        return _cache[key]
    tool = _load_tool()
    if tool is None:
        return {"ok": False, "message": "未找到 tools/export_actions.py", "actions": [], "count": {}}
    try:
        rep = tool.export(pkg_dir)
    except Exception as e:                                  # noqa: BLE001
        return {"ok": False, "message": f"动作扫描失败：{e}", "actions": [], "count": {}}
    rep["ok"] = True
    if cacheable:
        _cache[key] = rep
    return rep


def find(actions: list, name: str):
    for a in actions or []:
        if a.get("name") == name:
            return a
    return None


def suggest_keys(action: dict | None) -> list:
    """必填参数键（供「一键补键」）。"""
    if not action:
        return []
    return [p["key"] for p in (action.get("params") or []) if p.get("required")]


def default_value(p: dict):
    """参数的推荐初始值（按推断类型给零值）。"""
    t = (p or {}).get("type")
    if (p or {}).get("default") is not None:
        return p["default"]
    return {"number": 0, "int": 0, "float": 0.0, "string": "", "bool": False,
            "array": [], "object": {}}.get(t, "")
