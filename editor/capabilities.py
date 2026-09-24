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


_REF_CACHE: dict = {}          # pkg_dir → ((戳, 目标集), {ext_id: {count, files, top}})


def _scan_files(pkg_dir: str):
    """本包会被扫的 .py（`_SCAN_DIRS` 下，跳 `__pycache__`，按名排序保证可复现）。"""
    for sub in _SCAN_DIRS:
        base = os.path.join(pkg_dir, sub)
        if not os.path.isdir(base):
            continue
        for dp, dn, fn in os.walk(base):
            if "__pycache__" in dp:
                continue
            for f in sorted(fn):
                if f.endswith(".py"):
                    yield os.path.join(dp, f)


def content_stamp(pkg_dir: str) -> tuple:
    """内容戳 =（被扫 `.py` 的个数, 最新 mtime）—— 增 / 删 / 改任一文件都会变。

    用**内容戳**而不是「带项目就不缓存」：改了文件即失效（编辑即刻可见），没改即复用。
    """
    n = 0
    latest = 0.0
    for p in _scan_files(pkg_dir):
        n += 1
        try:
            mt = os.path.getmtime(p)
        except OSError:
            continue
        if mt > latest:
            latest = mt
    return (n, round(latest, 3))


def clear_cache(pkg_dir: str | None = None) -> None:
    """清引用缓存（`?fresh=1` 的逃生口；不给就全清）。"""
    if pkg_dir is None:
        _REF_CACHE.clear()
    else:
        _REF_CACHE.pop(os.path.abspath(pkg_dir), None)


def refs_all(pkg_dir: str, ext_ids=None, fresh: bool = False) -> dict:
    """`{ext_id: {count, files, top}}` —— **一次解析**同时统计所有目标包，按内容戳缓存。

    ★ 2026-09-24 性能修复：老实现 `refs_of` 每调一次就把整个包 AST 解析一遍，而
    `/capabilities` 对 10 个扩展包各调一次 ⇒ 实测单包 1.6s × 10（接口冷 36s / 热 32s）。
    现在：① 一次遍历统计全部目标包（10× → 1×）；② 结果按**内容戳**缓存。

    ★ 缓存只有**一档（按包）**，且存的是**全量扫描结果** —— 调用方要哪几个包只是**过滤**，
    不会因为「目标集不同」把彼此顶掉（那是「来回切就慢」的老坑）。
    `ext_ids` 不给 ⇒ 返回本包已知的全部扩展包；`fresh=True` ⇒ 先清缓存再扫。
    """
    pkg_key = os.path.abspath(pkg_dir)
    if fresh:
        clear_cache(pkg_key)
    stamp = content_stamp(pkg_dir)
    cached = _REF_CACHE.get(pkg_key)
    if cached is None or cached[0] != stamp:
        # 扫哪些包 = 本包已知的扩展包 ∪ 调用方点名要的（点名要的一定扫，哪怕 extends 里没有）
        targets = set(ext_roots(pkg_dir))
        targets |= {str(x) for x in (ext_ids or [])}
        table: dict = {ext: {} for ext in targets}
        for p in _scan_files(pkg_dir):
            try:
                tree = ast.parse(io.open(p, encoding="utf-8", errors="ignore").read())
            except (SyntaxError, OSError):
                continue
            rel = os.path.relpath(p, pkg_dir).replace(os.sep, "/")
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    mods.append(node.module)
                elif isinstance(node, ast.Import):
                    mods.extend(a.name for a in node.names)
                for mod in mods:
                    root = mod.split(".")[0]
                    if root in targets:
                        table[root].setdefault(rel, []).append(getattr(node, "lineno", 0))
        out: dict = {}
        for ext_id, by_file in table.items():
            out[ext_id] = {"count": sum(len(v) for v in by_file.values()), "files": by_file,
                           "top": sorted(by_file.items(), key=lambda kv: -len(kv[1]))[:8]}
        cached = (stamp, out)
        _REF_CACHE[pkg_key] = cached

    if ext_ids is None:
        return cached[1]
    empty = {"count": 0, "files": {}, "top": []}
    return {str(e): cached[1].get(str(e), dict(empty)) for e in ext_ids}


def refs_of(pkg_dir: str, ext_id: str) -> dict:
    """单个扩展包的引用（**返回形状与旧实现逐键一致**：`count` / `files` / `top`）。

    数据包里 import 这个扩展包的位置（**关掉它真正会断的地方**）；只认静态 import。
    """
    return refs_all(pkg_dir, [ext_id]).get(ext_id, {"count": 0, "files": {}, "top": []})


def _pkg_decls(pkg_dir: str) -> dict:
    """包自己的域声明（`editor/domains.json`，剥掉 `$builtin` 开关）。"""
    d = _read_json(os.path.join(pkg_dir, "editor", "domains.json")) or {}
    if isinstance(d, dict):
        d.pop("$builtin", None)
    return d


def effects(pkg_dir: str, disable=None, fresh: bool = False) -> dict:
    """**试算**：把 `disable` 里的扩展包当作没装，看域表与各包状态怎么变。

    不写任何文件；域表一律走 `layered_decls()`（唯一源）。
    `fresh=True` ⇒ 引用扫描不吃缓存（`?fresh=1` 逃生口）。
    """
    roots = ext_roots(pkg_dir)
    manifest = PK.load_manifest(pkg_dir) or {}
    want = [str(x) for x in (manifest.get("depends") or [])]
    known = [d for d in want if d in roots]
    disable = [d for d in (disable or []) if d in known]

    decl = _pkg_decls(pkg_dir)
    full_meta = layered_decls(pkg_dir, decl)
    now_list = sorted(d for d in known if d in roots)

    # ★ 2026-09-24：一次扫描统计**所有**扩展包的引用（原来每包各扫一遍整包 ⇒ 10× 代价）
    refs_table = refs_all(pkg_dir, roots.keys(), fresh=fresh)

    rows = []
    for ext_id in sorted(roots):
        info = describe(pkg_dir, ext_id, roots[ext_id])
        info["enabled"] = ext_id in known
        refs = refs_table.get(ext_id) or {"count": 0, "files": {}, "top": []}
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
