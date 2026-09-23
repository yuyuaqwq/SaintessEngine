# -*- coding: utf-8 -*-
"""机制动作清单（编辑器用）—— 包装框架工具 `tools/export_actions.py`。

用途：编辑器在编辑声明表（`passive_proc` / `effect_rules`）时，把自由字符串字段
`action` 变成「从真实注册的动作里选」，并按该动作的**实际消费参数**给出提示。

数据来源 = **静态 AST 扫描源码**（不是另行维护的声明表）：
  - 框架内置动作：`saintess_engine/**` 与 `extends/**`（扩展包）里的 `@register_action`
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


def _src_stamp(pkg_dir: str | None):
    """被扫源码树的**内容戳** =（`.py` 文件数, 最新 mtime）。

    ★ 为什么按戳缓存（2026-09-15 实测优化）：原实现「带包一律不缓存」，理由是
    「包内动作是用户正在写的代码，缓存会看到过期清单（曾踩：服务先起、后写的 mech 扫不出来）」。
    代价是**每次切换包都全扫**（orlandia 155 个包文件 + 引擎 → `/api/actions?pkg=orlandia` **6.0s**，
    其余接口均 0.01–0.07s）。
    改用内容戳后：**改了文件 ⇒ 戳变 ⇒ 重扫**（原意保留，编辑即刻可见）；**没改 ⇒ 复用缓存**
    （切包从 6s 降到毫秒级）。`use_cache=False`（`?fresh=1`）仍强制重扫。
    """
    n = 0
    newest = 0.0
    roots = [r for r in (pkg_dir, os.path.join(FW_ROOT, "saintess_engine")) if r and os.path.isdir(r)]
    # 扩展包里的机制动作也算「框架侧内置」（2026-09-23 包栈重构：战斗/任务这些
    # 能力包从引擎抽到 extends/，编辑器要给联想就得跟着扫）。
    _ext = os.path.join(FW_ROOT, "extends")
    if os.path.isdir(_ext):
        for _name in sorted(os.listdir(_ext)):
            _d = os.path.join(_ext, _name)
            if os.path.isdir(_d):
                roots.append(_d)
    for root_dir in roots:
        for dirpath, dirnames, filenames in os.walk(root_dir):
            dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".git", "node_modules")]
            for fn in filenames:
                if not fn.endswith(".py"):
                    continue
                n += 1
                try:
                    mt = os.path.getmtime(os.path.join(dirpath, fn))
                except OSError:
                    continue
                if mt > newest:
                    newest = mt
    return (n, round(newest, 3))


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

    **缓存策略（2026-09-15 改）**：按**内容戳**缓存（见 `_src_stamp`）——
    戳 =（`.py` 文件数, 最新 mtime），改文件即失效 ⇒「正在写的代码立刻可见」的原意保留，
    同时切包不再每次全扫（实测 orlandia 6.0s → 毫秒级）。`use_cache=False`（`?fresh=1`）强制重扫。
    """
    stamp = _src_stamp(pkg_dir) if use_cache else None
    key = (pkg_dir or "", stamp)
    if use_cache and stamp is not None and key in _cache:
        return _cache[key]
    tool = _load_tool()
    if tool is None:
        return {"ok": False, "message": "未找到 tools/export_actions.py", "actions": [], "count": {}}
    try:
        rep = tool.export(pkg_dir)
    except Exception as e:                                  # noqa: BLE001
        return {"ok": False, "message": f"动作扫描失败：{e}", "actions": [], "count": {}}
    rep["ok"] = True
    if use_cache and stamp is not None:
        _cache[key] = rep
        if len(_cache) > 8:                                 # 防无限增长（切换多个包/多轮编辑）
            for k in list(_cache)[:-4]:
                _cache.pop(k, None)
    return rep


def find(actions: list, name: str):
    for a in actions or []:
        if a.get("name") == name:
            return a
    return None


# 声明表里「引用动作名」的字段（新增声明表时在这里登记，别让收集逻辑散落）
_PROC_ACTION_FIELD = "action"          # passive_proc.<key>.action = 动词名
_PROC_ALSO_FIELD = "also"              # passive_proc.<key>.also = [{event, action, …}, …]


def declared_action_names(pkg_dir: str) -> dict:
    """包内**声明表**引用到的动作名（声明说「用哪个动词」，动词得有人实现）。

    目前来源：`passive_proc` 的 `action` 与 `also[].action`（`also` 可能是 dict、也可能是 list）。
    返回 `{declared: [名字…], sources: {名字: [条目 key…]}}`（排序稳定，便于门禁比对）。
    """
    try:
        from editor import packages as PK
        tbl = PK.read_json(PK.domain_path(pkg_dir, "passive_proc"), {})
    except Exception:                                          # noqa: BLE001
        tbl = {}
    src: dict = {}

    def take(v, key):
        if isinstance(v, str) and v.strip():
            src.setdefault(v.strip(), set()).add(key)

    for key, e in (tbl.items() if isinstance(tbl, dict) else []):
        if not isinstance(e, dict):
            continue
        take(e.get(_PROC_ACTION_FIELD), str(key))
        also = e.get(_PROC_ALSO_FIELD)
        for one in (also if isinstance(also, list) else [also]):
            if isinstance(one, dict):
                take(one.get(_PROC_ACTION_FIELD), str(key))
    return {"declared": sorted(src), "sources": {k: sorted(v) for k, v in sorted(src.items())}}


def declared_missing(pkg_dir: str) -> dict:
    """声明里引用、但**没有实现**的动作（引擎内置 + 包内 `mech/` 都算实现）。

    为什么要它：`fire()` 对没注册的动作名是**静默跳过**（不报错、不触发）——
    「声明了没实现」应该在加载/检查期就能回答，而不是等它静默不生效。
    返回 `{declared: n, implemented: n, missing: [名字…], sources: {名字: [条目…]}, ok: bool}`。
    """
    inv = inventory(pkg_dir)
    have = {a.get("name") for a in (inv.get("actions") or []) if isinstance(a, dict)}
    dec = declared_action_names(pkg_dir)
    missing = [n for n in dec["declared"] if n not in have]
    return {"declared": len(dec["declared"]), "implemented": len(have),
            "missing": missing, "sources": {n: dec["sources"][n] for n in missing},
            "ok": not missing}


def suggest_keys(action: dict | None) -> list:
    """必填参数键（供「一键补键」）。"""
    if not action:
        return []
    return [p["key"] for p in (action.get("params") or []) if p.get("required")]
