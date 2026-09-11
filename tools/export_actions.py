#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""机制动作清单导出器 —— 给编辑器渲染「动作选择器 + 参数表单」。

为什么用**静态 AST 扫描**而不是在引擎里加注册表
------------------------------------------------
设计稿曾建议在 `@register_action` 时把 `(name, params, doc)` 记进引擎注册表。
但那样 ① 要改引擎核心（需审批）② 声明与实现可能漂移。

本工具改为**从实现反推**：扫装饰器拿动作名 + docstring，再扫函数体里
`params.get("key")` / `params["key"]` 的**实际消费点**拿参数名与默认值 ——
天然与实现一致，不会漂移，且引擎零改动。

参数类型推断（够渲染表单用）
----------------------------
| 源码形态 | 推断 |
|---|---|
| `params["k"]` | 必填（直接下标 = 假定存在） |
| `params.get("k")` 且随后 `if not k: return` | 必填（缺字段=无此行为） |
| `params.get("k", 1)` / `("k", 0.5)` | 数字（int / float 按字面量） |
| `params.get("k", "s")` | 字符串 |
| `params.get("k", True/False)` | 布尔 |
| `params.get("k", [...])` / `({...})` | 列表 / 对象 |
| 其他 | 未知（表单给文本框） |

用法
----
    python tools/export_actions.py                          # 只导引擎内置动作
    python tools/export_actions.py --pkg <游戏包目录>        # 引擎 + 该包 mech/
    python tools/export_actions.py --pkg X --out actions.json
    python tools/export_actions.py --selfcheck              # 自检（断言基本盘）
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(HERE)
ENGINE_DIR = os.path.join(FW_ROOT, "saintess_engine")

ACTION_DECORATOR = "register_action"
# 动作函数统一签名 (battle, caster, target, params, logs)
PARAM_ARG_INDEX = 3


# ───────────────────────── 参数提取 ─────────────────────────
def _lit(node):
    """字面量 → python 值；非字面量返回哨兵。"""
    try:
        return ast.literal_eval(node)
    except Exception:                                      # noqa: BLE001
        return _NO_LITERAL


class _No:
    def __repr__(self):  # pragma: no cover
        return "<non-literal>"


_NO_LITERAL = _No()


def _kind_of(v) -> str:
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "string"
    if isinstance(v, (list, tuple)):
        return "array"
    if isinstance(v, dict):
        return "object"
    return "unknown"


def _params_name(fn: ast.AST) -> str | None:
    a = fn.args
    names = [x.arg for x in a.args]
    return names[PARAM_ARG_INDEX] if len(names) > PARAM_ARG_INDEX else None


def collect_params(fn: ast.AST) -> list:
    """扫函数体里对 params 的消费点 → [{key, required, default, type, sources}]。"""
    pname = _params_name(fn)
    if not pname:
        return []
    found = {}

    def note(key, **kw):
        d = found.setdefault(key, {"key": key, "required": False,
                                   "default": None, "type": "unknown",
                                   "hint": ""})
        for k, v in kw.items():
            if k == "required" and v:
                d["required"] = True
            elif k in ("default", "type", "hint") and v not in (None, "") and d.get(k) in (None, "", "unknown"):
                d[k] = v

    class V(ast.NodeVisitor):
        def visit_Subscript(self, node):
            # params["k"]
            if isinstance(node.value, ast.Name) and node.value.id == pname:
                sl = node.slice
                if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                    note(sl.value, required=True, hint="直接下标取值（代码假定必填）")
            self.generic_visit(node)

        def visit_Call(self, node):
            # params.get("k"[, default])
            f = node.func
            if (isinstance(f, ast.Attribute) and f.attr == "get"
                    and isinstance(f.value, ast.Name) and f.value.id == pname
                    and node.args and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                key = node.args[0].value
                if len(node.args) >= 2:
                    dv = _lit(node.args[1])
                    if dv is _NO_LITERAL:
                        note(key, hint="默认值非字面量，运行期决定")
                    else:
                        note(key, default=dv, type=_kind_of(dv),
                             hint=f"缺省 {dv!r}")
                else:
                    note(key, hint="无默认值")
            self.generic_visit(node)

    V().visit(fn)
    out = [d for d in found.values() if not _is_internal_key(d["key"])]
    for d in out:
        if d["type"] == "unknown":
            d["type"] = _guess_kind(d["key"])
    return sorted(out, key=lambda x: (not x["required"], x["key"]))


# 内部/装配器注入键：不面向配置者（`_owner` 等），不进表单
_INTERNAL_PREFIX = "_"
_INTERNAL_KEYS = {"_owner", "info", "_battle", "_ctx", "battle", "logs"}


def _is_internal_key(k: str) -> bool:
    return k.startswith(_INTERNAL_PREFIX) or k in _INTERNAL_KEYS


# 名字启发式（**只作输入框提示，不作强校验** —— 前端仍按用户输入的实际内容定型）
_NUM_HINT = ("pct", "chance", "mult", "amount", "value", "rate", "ratio",
             "cost", "gain", "min", "max", "cap", "turn", "turns", "count",
             "threshold", "level", "lv", "cd", "stack", "stacks", "hit", "hits",
             "power", "bonus", "reduce", "add", "div", "sec", "interval")
_STR_HINT = ("key", "tag", "cond", "mode", "kind", "on", "dir", "stat", "type",
             "field", "name", "side", "target", "res", "bar", "dot", "mech",
             "prefix", "suffix", "when", "op", "from", "to", "id")
_BOOL_HINT = ("is_", "has_", "forever", "halve", "not_basic", "once", "silent", "force")


def _guess_kind(key: str) -> str:
    k = key.lower()
    if any(h in k for h in _BOOL_HINT):
        return "bool"
    if any(k == h or k.endswith(h) or k.startswith(h) for h in _STR_HINT):
        return "string"
    if any(h in k for h in _NUM_HINT):
        return "number"
    return "unknown" 


def _line_of(node: ast.AST) -> int:
    return getattr(node, "lineno", 0) or 0


# ───────────────────────── 单文件扫描 ─────────────────────────
def scan_file(path: str, source_tag: str, rel: str) -> list:
    """扫一个 .py 文件里的全部 @register_action。"""
    try:
        src = open(path, encoding="utf-8").read()
        tree = ast.parse(src, filename=path)
    except (OSError, SyntaxError):
        return []

    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            hit = None
            if isinstance(dec, ast.Call):
                f = dec.func
                if isinstance(f, ast.Name) and f.id == ACTION_DECORATOR and dec.args:
                    a0 = dec.args[0]
                    if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                        hit = a0.value
                elif isinstance(f, ast.Attribute) and f.attr == ACTION_DECORATOR and dec.args:
                    a0 = dec.args[0]
                    if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                        hit = a0.value
            if not hit:
                continue
            doc = (ast.get_docstring(node) or "").strip()
            out.append({
                "name": hit,
                "source": source_tag,             # engine | package
                "file": rel,
                "line": _line_of(node),
                "func": node.name,
                "doc": doc.split("\n\n")[0].strip() if doc else "",
                "doc_full": doc,
                "params": collect_params(node),
            })
    return out


def _walk_py(root: str):
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git", "_archive_unused")]
        for f in sorted(files):
            if f.endswith(".py"):
                yield os.path.join(dirpath, f)


# ───────────────────────── 导出 ─────────────────────────
def export(pkg_dir: str | None = None) -> dict:
    actions, files = [], []
    # ① 框架内置动作
    for p in _walk_py(ENGINE_DIR):
        rel = os.path.relpath(p, FW_ROOT).replace("\\", "/")
        got = scan_file(p, "engine", rel)
        if got:
            actions += got
            files.append(rel)
    # ② 游戏包自带动作（content/mech/*.py 及包内任意 .py 的 register_action）
    if pkg_dir and os.path.isdir(pkg_dir):
        for p in _walk_py(pkg_dir):
            rel = os.path.relpath(p, pkg_dir).replace("\\", "/")
            got = scan_file(p, "package", rel)
            if got:
                actions += got
                files.append(rel)
    actions.sort(key=lambda a: (a["source"] != "engine", a["name"]))
    return {
        "engine_version": _engine_version(),
        "package": os.path.basename(pkg_dir) if pkg_dir else "",
        "scanned_files": files,
        "count": {"engine": sum(1 for a in actions if a["source"] == "engine"),
                  "package": sum(1 for a in actions if a["source"] == "package"),
                  "total": len(actions)},
        "actions": actions,
    }


def _engine_version() -> str:
    try:
        sys.path.insert(0, FW_ROOT)
        from saintess_engine import version as V
        return V.__version__
    except Exception:                                      # noqa: BLE001
        return ""


def selfcheck() -> int:
    """自检：基本盘必须成立（引擎内置动作存在且参数提取有效）。"""
    rep = export(None)
    ok = fail = 0

    def ck(name, cond, detail=""):
        nonlocal ok, fail
        if cond:
            ok += 1
            print(f"  ✅ {name}")
        else:
            fail += 1
            print(f"  ❌ {name} {detail}")

    names = {a["name"] for a in rep["actions"]}
    ck("扫到引擎内置动作 ≥ 8", rep["count"]["engine"] >= 8, f"实际 {rep['count']['engine']}")
    for expect in ("apply", "consume", "shield", "cleanse", "heal", "damage"):
        ck(f"含内置动作 {expect!r}", expect in names)
    ck("每个动作都有 source/file/line/func",
       all(a["source"] and a["file"] and a["line"] and a["func"] for a in rep["actions"]))
    ck("动作名唯一", len(names) == len(rep["actions"]), f"{len(names)} vs {len(rep['actions'])}")
    # 参数提取有效性：至少有几个动作能提出参数
    withp = [a for a in rep["actions"] if a["params"]]
    ck("至少 4 个动作提取到参数（证明消费点扫描有效）", len(withp) >= 4, f"实际 {len(withp)}")
    # apply 的核心参数 key 应出现（effects 写入动词必读 key）
    apply_a = next((a for a in rep["actions"] if a["name"] == "apply"), None)
    ck("apply 提取到参数 key", bool(apply_a and any(p["key"] == "key" for p in apply_a["params"])),
       apply_a["params"] if apply_a else None)
    print(f"\n动作 {rep['count']['total']} 个（内置 {rep['count']['engine']}）"
          f"；含参数提取的 {len(withp)} 个")
    print(f"===== 自检：通过 {ok} / {ok + fail} =====")
    return 1 if fail else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="机制动作清单导出（编辑器用）")
    ap.add_argument("--pkg", default=None, help="游戏包目录（额外扫它的 mech/）")
    ap.add_argument("--out", default=None, help="输出 JSON 路径（缺省打印摘要）")
    ap.add_argument("--selfcheck", action="store_true")
    args = ap.parse_args(argv)
    if args.selfcheck:
        return selfcheck()

    rep = export(args.pkg)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"已写出 {args.out}")
    print(f"引擎 {rep['engine_version'] or '?'} · 内置动作 {rep['count']['engine']}"
          f" · 包内动作 {rep['count']['package']} · 合计 {rep['count']['total']}")
    for a in rep["actions"]:
        ps = ", ".join(p["key"] + ("*" if p["required"] else "") for p in a["params"][:6])
        print(f"  [{a['source']:<7}] {a['name']:<26} {a['file']}:{a['line']}"
              + (f"  参数({len(a['params'])}): {ps}" if ps else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
