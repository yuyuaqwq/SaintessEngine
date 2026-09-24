# -*- coding: utf-8 -*-
"""能力开关 —— 扩展包的「装了 / 没装」差在哪，以及关掉它的代价。

给编辑器的「包设置 · 能力开关」块用。两个用途共用同一份口径：

* **试算**（不改包）：`effects(pkg_dir, disable=["ext_world"])` —— 若关掉它，
  会失去哪些域、哪些能力；不动 `game.json`，纯粹算给你看。
* **实关**（改包）：确认真要关时，前端把新的 `depends` 走已有的
  `PUT /api/package/<id>/manifest` 落盘。本模块**不写任何文件**。

三条纪律（2026-09-23 包栈重构定的）：

1. **域表的唯一源是 `saintess_engine.domains.layered_decls()`** —— 试算必须调它，
   不许在这里另拼一套（编辑器与装载口口径漂过一次，踩过）。
2. **看三个维度，别只看域表**：域表反映不了「指令 / 机制」这类能力
   （ext_dialogue 关掉后域表一个不变，但对话功能全没了）。
3. **内容侧引用是硬代价**：数据包 `content/` 里 import 这个扩展包的处数。
   0 处 = 关掉只少能力；上百处 = 关掉包大概率跑不起来。
"""
from __future__ import annotations

import ast
import io
import json
import os
from typing import Any

from saintess_engine.domains import layered_decls

from . import packages as PK

#: 数据包里可能出现 import 扩展包的地方（相对包根）
_SCAN_DIRS = ("content", "tests", "editor")


def ext_roots(pkg_dir: str) -> dict:
    """扩展包搜索路径里能看到的全部扩展包 → `{id: 目录}`（复用包栈那套约定路径）。"""
    from saintess_engine.package import default_ext_dirs
    found: dict = {}
    for base in default_ext_dirs(pkg_dir):
        try:
            names = sorted(os.listdir(base))
        except OSError:
            continue
        for name in names:
            d = os.path.join(base, name)
            mf = os.path.join(d, "game.json")
            if not os.path.isdir(d) or not os.path.isfile(mf):
                continue
            try:
                with io.open(mf, encoding="utf-8") as fh:
                    m = json.load(fh)
            except (OSError, ValueError):
                continue
            if str(m.get("kind") or "") != "extension":
                continue
            found.setdefault(name, d)
    return found


def _read_json(path: str):
    try:
        with io.open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def describe(pkg_dir: str, ext_id: str, root: str) -> dict:
    """一个扩展包的身份证：名字 · 模块 · 提供的域 · 提供的能力键 · 依赖。"""
    m = _read_json(os.path.join(root, "game.json")) or {}
    decl = _read_json(os.path.join(root, "domains.json")) or {}
    decl.pop("$builtin", None)
    mods = sorted(d for d in os.listdir(root)
                  if os.path.isdir(os.path.join(root, d))
                  and d not in ("__pycache__", "tests")
                  and os.path.isfile(os.path.join(root, d, "__init__.py")))
    lines = 0
    for dp, dn, fn in os.walk(root):
        if "__pycache__" in dp or os.sep + "tests" in dp:
            continue
        for f in fn:
            if f.endswith(".py"):
                try:
                    lines += sum(1 for _ in io.open(os.path.join(dp, f), encoding="utf-8", errors="ignore"))
                except OSError:
                    pass
    return {
        "id": ext_id,
        "name": str(m.get("name") or ext_id),
        "desc": str(m.get("desc") or ""),
        # ★ 2026-09-24：清单元数据（详情面板要用；缺失给空串，不编造）
        "kind": str(m.get("kind") or "game"),
        "version": str(m.get("version") or ""),
        "author": str(m.get("author") or ""),
        "engine": str(m.get("engine") or ""),
        "entry": str(m.get("entry") or ""),
        "created": str(m.get("created") or ""),
        "modules": mods,
        "lines": lines,
        "domains": sorted(decl.keys()),
        "provides": sorted((m.get("provides") or {}).keys()),
        "depends": [str(x) for x in (m.get("depends") or [])],
    }


def refs_of(pkg_dir: str, ext_id: str) -> dict:
    """数据包里 import 这个扩展包的位置（**关掉它真正会断的地方**）。

    只扫静态 import（`import ext_x` / `from ext_x… import`），按文件归组。
    """
    hits: list = []
    for sub in _SCAN_DIRS:
        base = os.path.join(pkg_dir, sub)
        if not os.path.isdir(base):
            continue
        for dp, dn, fn in os.walk(base):
            if "__pycache__" in dp:
                continue
            for f in sorted(fn):
                if not f.endswith(".py"):
                    continue
                p = os.path.join(dp, f)
                try:
                    tree = ast.parse(io.open(p, encoding="utf-8", errors="ignore").read())
                except (SyntaxError, OSError):
                    continue
                for node in ast.walk(tree):
                    mod = None
                    if isinstance(node, ast.ImportFrom) and node.module:
                        mod = node.module
                    elif isinstance(node, ast.Import):
                        for a in node.names:
                            if a.name.split(".")[0] == ext_id:
                                hits.append((os.path.relpath(p, pkg_dir).replace(os.sep, "/"),
                                             getattr(node, "lineno", 0)))
                                break
                    if mod and mod.split(".")[0] == ext_id:
                        hits.append((os.path.relpath(p, pkg_dir).replace(os.sep, "/"),
                                     getattr(node, "lineno", 0)))
    by_file: dict = {}
    for rel, ln in hits:
        by_file.setdefault(rel, []).append(ln)
    return {"count": len(hits), "files": by_file,
            "top": sorted(by_file.items(), key=lambda kv: -len(kv[1]))[:8]}


def _pkg_decls(pkg_dir: str) -> dict:
    """包自己的域声明（`editor/domains.json`，剥掉 `$builtin` 开关）。"""
    d = _read_json(os.path.join(pkg_dir, "editor", "domains.json")) or {}
    if isinstance(d, dict):
        d.pop("$builtin", None)
    return d


def effects(pkg_dir: str, disable=None) -> dict:
    """**试算**：把 `disable` 里的扩展包当作没装，看域表与各包状态怎么变。

    不写任何文件；域表一律走 `layered_decls()`（唯一源）。
    """
    roots = ext_roots(pkg_dir)
    manifest = PK.load_manifest(pkg_dir) or {}
    want = [str(x) for x in (manifest.get("depends") or [])]
    known = [d for d in want if d in roots]
    disable = [d for d in (disable or []) if d in known]

    decl = _pkg_decls(pkg_dir)
    full_meta = layered_decls(pkg_dir, decl)
    now_list = sorted(d for d in known if d in roots)

    rows = []
    for ext_id in sorted(roots):
        info = describe(pkg_dir, ext_id, roots[ext_id])
        info["enabled"] = ext_id in known
        refs = refs_of(pkg_dir, ext_id)
        info["refs"] = refs["count"]
        info["ref_files"] = refs["top"]           # [(文件, [行号…])] 前 8 个
        info["ref_all"] = sorted(refs["files"])   # 全部文件名（算「关掉会断哪些文件」）
        # 关掉它（单独关）会失去哪些域 —— 只对当前已装的包算
        if ext_id in known:
            after = layered_decls(pkg_dir, decl,
                                  depends=[d for d in known if d != ext_id])
            info["loses_domains"] = sorted(set(full_meta) - set(after))
        else:
            info["loses_domains"] = []
        rows.append(info)

    after_meta = layered_decls(pkg_dir, decl,
                               depends=[d for d in known if d not in disable])
    return {
        "pkg": os.path.basename(os.path.normpath(pkg_dir)),
        "enabled": known,
        "extensions": rows,
        "trial": {
            "disable": disable,
            "domains_before": len(full_meta),
            "domains_after": len(after_meta),
            "loses_domains": sorted(set(full_meta) - set(after_meta)),
            "refs_cut": sum(r["refs"] for r in rows if r["id"] in disable),
            "ref_files_cut": sorted({f for r in rows if r["id"] in disable
                                     for f in r["ref_all"]}),
            "provides_cut": sorted({k for r in rows if r["id"] in disable
                                    for k in r["provides"]}),
        },
        "all_ids": now_list,
    }
