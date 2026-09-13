# -*- coding: utf-8 -*-
"""游戏包加载器 —— **唯一入口**：把一个包从「目录」加载成「可用的内容模块」。

为什么需要它（2026-09-13）：在此之前有三处加载器各写一套，而且都按**顶层模块**加载
（`sys.path.insert(包/content)` + `import apply`）—— 于是包内一旦写 `from .mech import actions`
这类**包内相对导入**就会炸：轻则 `ImportError`，重则被 `except ImportError` 吞掉、
**动作静默不注册**（表现是"战斗里什么都没发生"，不报错）。第三方照抄导出包里那套加载代码，
会把同一个坑带进自己的包。

本模块把这件事收成一处：

    from saintess_engine import package as pkg_loader
    info = pkg_loader.load(pkg_dir)          # 路径 → game.json → 版本门禁 → import → install_engine()
    if not info["ok"]:
        print(info["errors"])

约定（与 `docs/engine-wiki/reference/package-format.md` 一致）：

* 包根必须有 `game.json`（`id` / `engine` / 可选 `entry`）；`entry` 缺省按 `content/apply.py`。
* `content/apply.py` 提供 **`install_engine()`**（全局一次、幂等）；`apply_game_content(actor)` 由宿主调，
  不在本加载器职责内。
* 版本：`game.json.engine` 形如 `">=0.1"`；空/缺省视为满足。
* 加载**不抛异常**：调用方多是子进程与工具，需要的是可读的错误，不是栈。

实现要点：
1. 先 `sys.path` 加**包根**（不是 `content/`）→ `content` 成为命名空间包 → `import content.apply`
   → 包内相对导入正常；
2. 兼容旧写法：包根导入失败时退回「`content/` 进 path + 顶层 `import apply`」，并在返回值里
   记 `import_style`（`"package"` / `"top-level"`），方便把旧包迁移过来；
3. 已加载过同一个包的 `content.apply` 会命中 `sys.modules` → `install_engine()` 靠它自身幂等，
   这里不额外做去重（重复 import 是便宜的，重复装配不幂等才是坑）。
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import traceback

from . import version as _version

DEFAULT_ENTRY = "content/apply.py"


def read_manifest(pkg_dir: str) -> tuple:
    """读 `game.json` → `(manifest, error_or_None)`。缺文件/坏 JSON/不是对象 都给出可读错误。"""
    path = os.path.join(pkg_dir, "game.json")
    if not os.path.isfile(path):
        return {}, f"包根没有 game.json：{path}"
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:                                     # noqa: BLE001
        return {}, f"game.json 读不了（{e}）：{path}"
    if not isinstance(data, dict):
        return {}, f"game.json 顶层必须是对象：{path}"
    return data, None


def load(pkg_dir: str, *, install: bool = True, load_config: bool = True) -> dict:
    """加载游戏包。返回（**不抛**）：

        {
          "ok": bool, "pkg_dir": str, "manifest": dict, "engine": str,
          "apply": module | None, "import_style": "package" | "top-level" | None,
          "installed": bool, "errors": [str…],
        }
    """
    out = {"ok": False, "pkg_dir": pkg_dir, "manifest": {}, "engine": "", "apply": None,
           "import_style": None, "installed": False, "errors": []}
    if not pkg_dir or not os.path.isdir(pkg_dir):
        out["errors"].append(f"包目录不存在：{pkg_dir!r}")
        return out
    pkg_dir = os.path.abspath(pkg_dir)

    manifest, err = read_manifest(pkg_dir)
    out["manifest"] = manifest
    if err:
        out["errors"].append(err)
        return out
    out["engine"] = str(manifest.get("engine") or "")

    # ---- 版本门禁（不满足就别往下走：装配半个引擎比不装配更难查） ----
    cur = getattr(_version, "VERSION", None) or getattr(_version, "__version__", "?")
    try:
        if not _version.satisfies(out["engine"]):
            out["errors"].append(f"包要求引擎 {out['engine']}，当前 {cur} —— 不满足")
            return out
    except Exception as e:                                     # noqa: BLE001
        out["errors"].append(f"game.json.engine 不是合法版本需求（{e}）")
        return out

    entry = str(manifest.get("entry") or DEFAULT_ENTRY)
    entry_path = os.path.join(pkg_dir, entry.replace("/", os.sep))
    if not os.path.isfile(entry_path):
        out["errors"].append(f"入口不存在：{entry}（game.json 声明了就必须有）")
        return out

    # ---- 导入（包根进 path → `content` 成命名空间包 → 包内相对导入可用） ----
    for p in (pkg_dir, os.path.join(pkg_dir, "content")):
        if p and os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)
    mod = None
    rel = entry.replace("\\", "/")
    if rel.startswith("content/") and rel.endswith(".py"):
        name = "content." + rel[len("content/"):-3].replace("/", ".")
        try:
            mod = importlib.import_module(name)
            out["import_style"] = "package"
        except Exception:                                      # noqa: BLE001  退回旧写法
            mod = None
    if mod is None:                                            # 旧写法：顶层 `import apply`
        for cand in (rel[:-3].replace("/", "."), os.path.splitext(os.path.basename(rel))[0]):
            try:
                mod = importlib.import_module(cand)
                out["import_style"] = "top-level"
                break
            except Exception:                                  # noqa: BLE001
                mod = None
    if mod is None:
        out["errors"].append(f"导入入口失败：{entry}\n{traceback.format_exc(limit=3)}")
        return out
    out["apply"] = mod

    fn = getattr(mod, "install_engine", None)
    if not callable(fn):
        out["errors"].append(f"{entry} 里没有 install_engine()（包的对外约定只有这两个函数）")
        return out
    if install:
        try:
            fn()
            out["installed"] = True
        except Exception:                                      # noqa: BLE001
            out["errors"].append(f"install_engine() 抛错：\n{traceback.format_exc(limit=4)}")
            return out
    out["ok"] = True
    return out
