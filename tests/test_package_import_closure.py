#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""包内 import 面自洽门禁（跨线接口漂移的常驻哨兵）。

为什么有这条门禁（2026-09-14 B2 四线并行的实测教训）
----------------------------------------------------
B2 四条簇线并行时：
  · C2 把 `games/orlandia/content/event_templates.py` 的取件口指向
    `content/reward.py:_host_content`（**写在函数体内**的延迟 import）；
  · C4 在改 `content/reward.py` 时把这个名字删了。
两条线各自都「合理」，合起来把引用打断了 —— 只有跑到那两个具体测试
（`test_v83_explore_egg` / `test_v97_03_event_templates`）才炸 ImportError。
⇒ 静态门禁在**落地前**就能抓到这类错位，不必等测试跑到那一行。

本门禁扫什么（纯 AST，不 import 任何包内模块）
---------------------------------------------
对每个内容包的每个 `.py`：
  · `from .x import A, B` / `from ..y import C` / `from . import z` / `import content.q`
    —— **函数体 / 条件分支 / try 块里的延迟 import 一样扫**（今晚那处正是这种形态：
      grep 看得见、只在调用时炸、静态 import 检查常常漏掉）；
  · 断言 a) 目标模块文件存在（`content/q.py` 或 `content/q/__init__.py`）；
  · 断言 b) 被 import 的**名字**在目标模块的**导出面**内：
      静态导出面 = 模块级 `def` / `class` / `赋值` / `import` 绑定 / `__all__`
                   / 模块级 `__getattr__` 里做常量比较产出的名字；
      动态导出面 = 显式 `__all__`、`__all__ +=`、模块级 `__getattr__`（PEP 562）、
                   `globals().update(...)`、`import *`，以及**照代码事实登记**、
                   带「为什么它算动态」理由的白名单（`DYNAMIC_EXPORT_RULES`）；
                   还可用环境变量 `IMPGATE_DYNAMIC_RULES` 追加（JSON，每条要理由 +
                   **原文锚点**，锚点对不上即报红，0 命中的条目也会被点名）。

不改包内任何文件：门禁只读；反证在**副本**里做（`IMPGATE_PKG_ROOT` 指过去）。

运行
----
    python tests/test_package_import_closure.py            # 真仓（只读）
    python tests/test_package_import_closure.py --json     # 机器可读清单（给报告用）
    python tests/test_package_import_closure.py --list     # 只列将扫的包/文件

退出码：0 = 包内 import 面自洽；1 = 有缺口
        （逐条打印「文件:行 · import 语句 · 缺失的名字 · 目标模块现有名字数」）

环境变量（反证 / 副本用；真仓不需要）
------------------------------------
    IMPGATE_PKG_ROOT     只扫这一个包目录（默认：`games/` 下所有带 game.json 的包 + `examples/minimal-game`）
    IMPGATE_REPO_ROOT    换仓库根（默认 = 本文件上两级）
    IMPGATE_EXTRA_PKGS   `;` 分隔的额外包目录
    IMPGATE_DYNAMIC_RULES JSON 数组，追加动态导出白名单（字段见 `DYNAMIC_EXPORT_RULES`）
"""
from __future__ import annotations

import ast
import io
import json
import os
import sys

# ============================================================
# 路径 / 口径常量
# ============================================================

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.getenv("IMPGATE_REPO_ROOT") or os.path.dirname(HERE)

# 输出统一 UTF-8（Windows 控制台默认 GBK/cp936，中文细节会被编码搞坏）：
# 直接把源码里的中文以 UTF-8 字节写到底层 buffer，行尾再统一成 '\n'。
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace", newline="\n")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace", newline="\n")
except Exception:                                                  # noqa: BLE001
    pass

SKIP_DIRS = {"__pycache__", ".git", ".pytest_cache", "node_modules", ".venv"}
#: 宿主侧测试树不是包内容（那里是包外测试的 import 口径，不适用本条门禁）
SKIP_SUBTREES = ("tests", "test")

# 反证用 overlay（**可选**；真仓/CI 不设这两个变量就完全不用）：
#   IMPGATE_OVERLAY_DIR    一个目录，里面放若干「同名文件的副本」
#   IMPGATE_OVERLAY_FILES  `;` 分隔的相对包内路径（如 `content/reward.py`）
# 命中的文件在扫描时**优先读 overlay 的副本**（内容不同会写进日志）。
# 这样反证完全不碰真仓、也不需要在真仓目录里造可写副本（沙箱下更干净）。
OVERLAY_DIR = os.getenv("IMPGATE_OVERLAY_DIR") or ""
OVERLAY_FILES = {p.strip().replace("\\", "/")
                 for p in (os.getenv("IMPGATE_OVERLAY_FILES") or "").split(";") if p.strip()}

# ============================================================
# 动态导出面白名单 —— **照代码事实登记，每条必须写「为什么它算动态」**
# ============================================================
# 字段：
#   module  : 包内模块全名（`content.xxx`；子包用 `content.sub.xxx`）
#   kind    : getattr | all | globals_update
#   names   : 该机制产出的名字（kind=getattr：`__getattr__` 里做相等比较的名字）
#   prefix  : 该机制产出的名字前缀（`name.startswith("X")` 形态）
#   from_mod: 该机制把名字**转发给**哪个包内模块（`getattr(mod, name)`）；
#             给了它就按「那个模块的导出面 ∩ (prefix 或 names)」判定，不写死名字表
#   reason  : 为什么它算动态（必填，会打进日志）
#   evidence: 原文锚点（该模块源码里必须出现的唯一片段；对不上 → 门禁自检报红）
#   note    : 可选的补充说明
DYNAMIC_EXPORT_RULES: tuple = (
    {
        "module": "content.daily_events",
        "kind": "getattr",
        "names": ["DAILY_MAP_EVENTS"],
        "from_mod": "content.catalog_rules",
        "reason": "PEP 562 模块级 __getattr__：只对 `DAILY_MAP_EVENTS` 一个名字做相等比较后"
                  "转发 `content/catalog_rules.py` 的惰性表（其余名字一律 AttributeError，"
                  "不是开放式兜底）；转发对象是包内模块 ⇒ 按 catalog_rules 的导出面核对，不写死值。",
        "evidence": 'if name == "DAILY_MAP_EVENTS":',
    },
    {
        "module": "content.wild",
        "kind": "getattr",
        "names": ["WILD_NPCS", "HIDDEN_NPCS", "ALL_WILD"],
        "reason": "PEP 562 模块级 __getattr__：三个真源顶层名（`WILD_NPCS` / `HIDDEN_NPCS` / `ALL_WILD`）"
                  "惰性解析成包内表派生结果，其余名字抛 AttributeError。产出物是**派生表**"
                  "（`{**WILD_NPCS, ...}`）不是模块对象 ⇒ 无法用 from_mod 表达，按名字逐条登记。"
                  "实证：`content/wild.py:184-192`；`overnight/w6_allwild_check.py` 63 条键集/键序/逐值深等。",
        "evidence": "def __getattr__(name):",
        "note": "三个名字的实现都在本模块内（`_wild_tables()` / `_ALL_WILD()`），不是转发。",
    },
    {
        "module": "content.wild_king",
        "kind": "getattr",
        "prefix": "WILD_KING",
        "from_mod": "content.catalog_rules",
        "reason": "PEP 562 模块级 __getattr__：`name.startswith(\"WILD_KING\")` 时"
                  "`getattr(content.catalog_rules, name)` —— 产出的名字集 = 该前缀 ∩ 包内门面导出面；"
                  "其余名字抛 AttributeError（不是开放式兜底）。",
        "evidence": 'if name.startswith("WILD_KING"):',
    },
)


# ============================================================
# 数据结构
# ============================================================

class ExportSurface:
    """一个模块的导出面（静态 + 动态），外加「为什么放行」的登记（可打印、可审计）。"""

    def __init__(self, module: str):
        self.module = module
        self.static: set = set()          # 模块级 def/class/赋值/import 绑定/__all__
        self.exec_time: set = set()       # `__all__ += [...]` 追加的名字
        self.dynamic: set = set()         # 模块级 __getattr__ 常量比较产出的名字（须过白名单）
        self.delegations: list = []       # [(from_alias, prefixes|None, evidence_line)]
        self.open_rules: list = []        # 不可枚举的动态面 [(机制说明, 证据行)]
        self.mechanisms: list = []        # 人类可读的机制列表（报告用）
        self.unparsed_all: str = ""       # `__all__` 不是字面量时的说明

    def has(self, name: str) -> bool:
        return name in self.static or name in self.exec_time

    def count(self) -> int:
        return len(self.static | self.exec_time | self.dynamic)


class ImportRef:
    """一条包内 import 记录（含函数体内的延迟 import）。"""

    def __init__(self, src_file: str, src_module: str, line: int, text: str,
                 target: str, name: str, star: bool = False):
        self.src_file = src_file
        self.src_module = src_module
        self.line = line
        self.text = text
        self.target = target
        self.name = name
        self.star = star

    def where(self) -> str:
        return "%s:%d" % (self.src_file, self.line)


class Gap:
    """一处不自洽（门禁红项）。"""

    def __init__(self, kind: str, ref: ImportRef, detail: str, avail: int = -1,
                 extra: str = ""):
        self.kind = kind          # missing_module | missing_name | star_empty | syntax
        self.ref = ref
        self.detail = detail
        self.avail = avail
        self.extra = extra

    def render(self) -> str:
        """逐条缺口的一行式输出（ASCII 前缀，便于各控制台/日志编码）。"""
        head = "GAP %s | %s | %s" % (self.ref.where(), self.ref.text.strip(), self.detail)
        if self.avail >= 0:
            head += " | target module name count=%d" % self.avail
        if self.extra:
            head += " | %s" % self.extra
        return head


# ============================================================
# AST 工具
# ============================================================

def _const_strs(node) -> "list | None":
    """尽量把表达式还原成字符串列表（`__all__` 用）。还原不了返回 None（不猜）。"""
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        out = []
        for el in node.elts:
            got = _const_strs(el)
            if got is None:
                return None
            out.extend(got)
        return out
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _const_strs(node.left), _const_strs(node.right)
        if left is None or right is None:
            return None
        return left + right
    if isinstance(node, ast.Starred):
        return _const_strs(node.value)
    return None


def _is_name(node, what: str) -> bool:
    return isinstance(node, ast.Name) and node.id == what


def _is_globals(node) -> bool:
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "globals" and not node.args)


def _is_globals_update(node) -> bool:
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "update" and _is_globals(node.func.value))


def _is_getattr_call(node):
    """`getattr(obj, name)` → (obj, name)；否则 None。"""
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "getattr" and len(node.args) >= 2):
        return node.args[0], node.args[1]
    return None


def _sub_bodies(node) -> list:
    """语句节点里的分支体（if/for/while/try/with），函数/类体不在此列。"""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return []
    out = []
    for field in ("body", "orelse", "finalbody"):
        sub = getattr(node, field, None)
        if isinstance(sub, list):
            out.append(sub)
    for handler in getattr(node, "handlers", []) or []:
        out.append(handler.body)
    return out


# ============================================================
# 模块导出面提取
# ============================================================

def _collect_function(fn, surface: ExportSurface) -> None:
    """函数名进导出面；`__getattr__` 额外做动态产出分析。"""
    surface.static.add(fn.name)
    if fn.name != "__getattr__":
        return
    line = fn.lineno
    params = list(getattr(fn.args, "posonlyargs", [])) + list(fn.args.args)
    if not params:
        surface.open_rules.append(("模块级 __getattr__ 没有名字参数 ⇒ 产出名字不可枚举", line))
        surface.mechanisms.append("__getattr__@%d（不可枚举）" % line)
        return
    pname = params[0].arg
    names: set = set()
    prefixes: set = set()
    delegations: list = []           # [(alias_or_expr, evidence_line)]
    open_hits: list = []
    aliases: set = {pname}

    def record(obj, key, ev_line):
        is_name_key = _is_name(key, pname) or (isinstance(key, ast.Name) and key.id in aliases)
        if is_name_key:
            if isinstance(obj, ast.Name):
                delegations.append((obj.id, ev_line))
            else:
                open_hits.append(("`getattr(<非模块表达式>, <名字>)` ⇒ 产出名字不可静态枚举", ev_line))
        else:
            got = _const_strs(key)
            if got:
                names.update(got)

    def walk_body(stmts) -> None:
        for st in stmts:
            # 别名绑定：`cur = name` / `q = 别的别名`
            if isinstance(st, (ast.Assign, ast.AnnAssign)) and st.value is not None:
                targets = st.targets if isinstance(st, ast.Assign) else [st.target]
                value = st.value
                if isinstance(value, ast.Name):
                    for t in targets:
                        if not isinstance(t, ast.Name):
                            continue
                        if value.id in aliases:
                            aliases.add(t.id)
                        else:
                            aliases.discard(t.id)
            for node in ast.walk(st):
                if isinstance(node, ast.Compare):
                    for op, comp in zip(node.ops, node.comparators):
                        if isinstance(op, ast.Eq) and _is_name(node.left, pname):
                            got = _const_strs(comp)
                            if got:
                                names.update(got)
                        if isinstance(op, ast.Eq) and _is_name(comp, pname):
                            got = _const_strs(node.left)
                            if got:
                                names.update(got)
                        if isinstance(op, ast.In) and _is_name(node.left, pname):
                            got = _const_strs(comp)
                            if got:
                                names.update(got)
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "startswith" and node.args
                        and _is_name(node.func.value, pname)):
                    got = _const_strs(node.args[0])
                    if got:
                        prefixes.update(got)
                    else:
                        open_hits.append(("`name.startswith(<非常量>)` ⇒ 前缀不可静态枚举",
                                          getattr(node, "lineno", line)))
                got = _is_getattr_call(node)
                if got:
                    record(got[0], got[1], getattr(node, "lineno", line))
            for sub in _sub_bodies(st):
                walk_body(sub)

    walk_body(fn.body)
    if names:
        # ★ 这些名字是 __getattr__ **算出来**的，不是模块级绑定 ⇒ 只进 dynamic 面，
        #   必须由 `DYNAMIC_EXPORT_RULES`（带理由 + 原文锚点 + 命中计数）放行，
        #   不许悄悄混进 static 面（否则白名单就成了摆设）。
        surface.dynamic.update(names)
        surface.mechanisms.append("__getattr__@%d 相等比较→%d 名（走白名单）" % (line, len(names)))
    for prefix in sorted(prefixes):
        surface.delegations.append(("__PREFIX__:" + prefix, [prefix], line))
        surface.mechanisms.append('__getattr__ startswith("%s")' % prefix)
    for alias, ev in delegations:
        surface.delegations.append((alias, None, ev))
        surface.mechanisms.append("__getattr__→getattr(%s, name)@%d" % (alias, ev))
    surface.open_rules.extend(open_hits)
    if not (names or prefixes or delegations or open_hits):
        surface.open_rules.append(
            ("模块级 __getattr__ 的产出名字无法静态枚举（没有任何常量比较）", line))
        surface.mechanisms.append("__getattr__@%d（不可枚举）" % line)


def _process_all_target(surface: ExportSurface, value, line: int) -> None:
    got = _const_strs(value)
    if got is None:
        surface.unparsed_all = ("`__all__` 不是字面量（第 %d 行）⇒ 取不到 __all__ 名字" % line)
        surface.mechanisms.append("__all__@%d（非字面量，未展开）" % line)
        return
    surface.static.update(got)
    surface.mechanisms.append("__all__@%d（%d 名）" % (line, len(got)))


def _scan_module_node(node, surface: ExportSurface) -> None:
    """模块级绑定（含 if/try 分支里的绑定 —— import 期都会/可能执行）。"""
    if isinstance(node, ast.Assign):
        for t in node.targets:
            if _is_name(t, "__all__"):
                _process_all_target(surface, node.value, node.lineno)
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id != "__all__":
                surface.static.add(t.id)
        return
    if isinstance(node, ast.AnnAssign):
        if isinstance(node.target, ast.Name):
            surface.static.add(node.target.id)
        return
    if isinstance(node, ast.AugAssign) and _is_name(node.target, "__all__"):
        got = _const_strs(node.value)
        if got is None:
            surface.unparsed_all = ("`__all__ +=` 不是字面量（第 %d 行）" % node.lineno)
        else:
            surface.exec_time.update(got)
            surface.mechanisms.append("__all__+=@%d（%d 名）" % (node.lineno, len(got)))
        return
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        _collect_function(node, surface)
        return
    if isinstance(node, ast.ClassDef):
        surface.static.add(node.name)
        return
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        for alias in node.names:
            if alias.name == "*":
                continue
            surface.static.add(alias.asname or alias.name.split(".")[0])
        return
    if isinstance(node, ast.Expr) and _is_globals_update(node.value):
        arg = node.value.args[0] if node.value.args else None
        if isinstance(arg, ast.Dict):
            got_keys, unknown = [], False
            for key in arg.keys:
                got = _const_strs(key)
                if got is None:
                    unknown = True
                    continue
                got_keys.extend(got)
            if got_keys:
                surface.static.update(got_keys)
                surface.mechanisms.append("globals().update@%d（%d 名）" % (node.lineno, len(got_keys)))
            if unknown:
                surface.open_rules.append(
                    ("`globals().update({...})` 含非字面量键 ⇒ 名字不可枚举", node.lineno))
        else:
            surface.open_rules.append(
                ("`globals().update(<非字面量字典>)` ⇒ 名字不可枚举", node.lineno))
        return
    for sub in _sub_bodies(node):
        for st in sub:
            _scan_module_node(st, surface)


def scan_exports(module: str, tree) -> ExportSurface:
    surface = ExportSurface(module)
    for node in getattr(tree, "body", []):
        _scan_module_node(node, surface)
    return surface


# ============================================================
# 包 / 模块索引
# ============================================================

class Package:
    """一个内容包：扫 <pkg>/**/*.py，把 `content.*` 认成包内模块。"""

    def __init__(self, pkg_dir: str, pydir_name: str, root_name: str):
        self.dir = os.path.abspath(pkg_dir)
        self.pydir = os.path.join(self.dir, pydir_name)
        self.root_name = root_name
        self.pydir_name = pydir_name          # 目录真名（可能是 hyphen）
        self.real_dir = os.path.normcase(os.path.realpath(self.dir))
        self.files: list = []
        self.module_files: dict = {}
        self.surfaces: dict = {}
        self.trees: dict = {}
        self.sources: dict = {}
        self.gaps: list = []
        self.import_refs: list = []
        self.rules: list = []

    # ---------- 发现 ----------
    def discover(self) -> None:
        self._seen: set = set()
        for dirpath, dirnames, filenames in os.walk(self.dir):
            rel = os.path.relpath(dirpath, self.dir).replace("\\", "/")
            dirnames[:] = sorted(d for d in dirnames
                                 if d not in SKIP_DIRS
                                 and not (rel == "." and d in SKIP_SUBTREES))
            for fn in sorted(filenames):
                if not fn.endswith(".py"):
                    continue
                full = os.path.join(dirpath, fn)
                r = os.path.relpath(full, self.dir).replace("\\", "/")
                if OVERLAY_DIR and r in OVERLAY_FILES and not os.path.isfile(
                        os.path.join(OVERLAY_DIR, *r.split("/"))):
                    continue               # overlay 明确声明了这个文件但副本里没有 ⇒ 模块被判不存在
                if os.path.normcase(os.path.realpath(full)) in self._seen:
                    continue               # 重复路径（junction/多入口）只算一次
                self._seen.add(os.path.normcase(os.path.realpath(full)))
                self.files.append(r)
                mod = self._module_of(r)
                if mod:
                    self.module_files[mod] = r          # 存**包内相对路径**（overlay 靠它命中）
        self._discover_overlay_only()

    def _discover_overlay_only(self) -> None:
        """overlay 里**新加**的包内文件（不在真仓里）也要被扫到（反证 D 组用）。

        只在显式设了 `IMPGATE_OVERLAY_DIR` / `IMPGATE_OVERLAY_FILES` 时生效；
        真仓/CI 不设 → 完全不进这条分支。
        """
        if not OVERLAY_DIR:
            return
        for rel in sorted(OVERLAY_FILES):
            cap = rel[:-3] + ".py" if rel.endswith(".pyc") else rel
            if not cap.endswith(".py") or cap in self.files:
                continue
            path = os.path.join(OVERLAY_DIR, *cap.split("/"))
            if not os.path.isfile(path):
                continue
            mod = self._module_of(cap)
            if mod:
                self.files.append(cap)
                self.module_files[mod] = cap

    def _module_of(self, rel: str) -> str:
        """包内相对路径 → 模块全名（`content/a/b.py` → `content.a.b`）。"""
        parts = rel[:-3].split("/")
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if not parts:
            return ""
        if parts[0] == self.pydir_name:
            parts = [self.root_name] + parts[1:]
        elif parts[0] != self.root_name:
            return ""                      # 只认 import 根名那一支（docs/editor 之类不参与）
        return ".".join(parts)

    def rel_of(self, abs_path: str) -> str:
        return os.path.relpath(abs_path, self.dir).replace("\\", "/")

    def module_of_path(self, abs_path: str) -> str:
        rel = os.path.relpath(abs_path, self.dir).replace("\\", "/")
        if rel in self.files:
            return self._module_of(rel)
        for mod, r in self.module_files.items():
            if os.path.normcase(os.path.join(self.dir, r)) == os.path.normcase(abs_path):
                return mod
        return ""

    def load_sources(self) -> None:
        """读全部 .py + 解析 AST（语法错误进缺口；白名单锚点自检也读它）。"""
        self.sources, self.trees, self.surfaces = {}, {}, {}
        self.overlaid = sorted(rel for rel in self.files if self._overlay_for(rel))
        for rel in self.files:
            mod = self._module_of(rel)
            if not mod:
                continue
            path = self._overlay_for(rel) or os.path.join(self.dir, rel)
            src = self.read_file(rel)
            self.sources[mod] = src
            try:
                self.trees[mod] = ast.parse(src, filename=path)
            except SyntaxError as exc:
                self.gaps.append(Gap("syntax",
                                     ImportRef(rel, "", exc.lineno or 0, "<parse>", rel, ""),
                                     "语法错误：%s" % exc.msg))
                continue
            self.surfaces[mod] = scan_exports(mod, self.trees[mod])

    # ---------- 名字解析 ----------
    def resolve(self, module: str) -> "str | None":
        """模块全名 → 存在的落点（`a/b.py` / `a/b/__init__.py` / 命名空间包目录 `a/b/`）。

        本仓的 `content/`、`content/data/`、`content/mech/` … **没有 `__init__.py`**
        （`saintess_engine/package.py:26` 的口径：包根进 `sys.path` → `content` 是命名空间包），
        所以「目录存在」也算模块存在 —— 这是 Python 的命名空间包语义，实测见
        `proof/probe_ns_pkg.py`（`import content.data` / `from .data import classes` 都成立）。

        反证 overlay：`IMPGATE_OVERLAY_FILES` 里声明过的文件，命中的一律按 overlay 落点算
        （这样副本里删掉一个模块，门禁看到的才是副本的事实，而不是真仓的）。
        """
        rel = self.module_files.get(module)
        if rel:
            over = self._overlay_for(rel)
            return over or os.path.join(self.dir, rel)
        return self._pkg_path(module)

    def _pkg_path(self, module: str) -> "str | None":
        """包内模块全名 → 磁盘落点（文件 / `__init__.py` / 命名空间包目录）。

        `module` 用的是 import 根名（`content.a.b`），磁盘上是 `<pkg>/<内容目录名>/a/b`；
        「目录存在」也算（命名空间包，本仓 `content/data/`、`content/mech/` 就是这样）。
        """
        parts = module.split(".")
        if parts and parts[0] == self.root_name and self.pydir_name != self.root_name:
            parts = [self.pydir_name] + parts[1:]
        cand = os.path.join(self.dir, *parts)
        if os.path.isfile(cand + ".py"):
            return cand + ".py"
        if os.path.isfile(os.path.join(cand, "__init__.py")):
            return os.path.join(cand, "__init__.py")
        if os.path.isdir(cand):
            return cand
        return None

    # ---------- 反证 overlay（可选） ----------
    def _overlay_for(self, rel: str) -> "str | None":
        if not OVERLAY_DIR:
            return None
        rel = rel.replace("\\", "/")
        if rel not in OVERLAY_FILES:
            return None
        cand = os.path.join(OVERLAY_DIR, *rel.split("/"))
        # 副本里**删掉**的文件也算「命中」——但那个模块就该判成不存在（A4 反证要的正是这个）。
        return cand

    def read_file(self, rel: str) -> str:
        """读包内文件；命中的 overlay 副本优先（真仓那份永远只读）。"""
        path = self._overlay_for(rel) or os.path.join(self.dir, rel)
        with io.open(path, encoding="utf-8") as f:
            return f.read()

    def child_module(self, module: str, name: str) -> "str | None":
        cand = "%s.%s" % (module, name) if module else name
        return self.resolve(cand)

    def label_of(self, abs_path: str) -> str:
        return os.path.relpath(abs_path, self.dir).replace("\\", "/")

    def available(self, module: str) -> set:
        s = self.surfaces.get(module)
        return (s.static | s.exec_time | s.dynamic) if s else set()

    def has_name(self, module: str, name: str) -> "tuple":
        """(是否存在, 理由)。理由非空 = 由动态面放行（会打印出来，可审计）。

        `module` 可能是**命名空间包目录**（`content` / `content.data`，没有 `__init__.py`）——
        那种包没有自己的绑定面，能取到的只有它的子模块，所以先判子模块。
        """
        if self.child_module(module, name) is not None:
            return True, "子模块文件（%s.%s）" % (module, name)
        s = self.surfaces.get(module)
        if s is None:
            return False, ""
        if s.has(name):
            return True, "静态导出面"
        for rule in self._rule_for(module):
            if rule["kind"] != "getattr":
                continue
            prefixes = rule.get("prefix") or []
            names = rule.get("names") or []
            if not (name in names or any(name.startswith(p) for p in prefixes)):
                continue
            from_mod = rule.get("from_mod")
            if from_mod and name not in self.available(from_mod):
                return False, ""
            rule["hits"].append((name, rule.get("evidence", "")))
            return True, "动态导出白名单（%s · %s）" % (rule["module"], rule["kind"])
        for from_alias, prefixes, ev in s.delegations:
            if from_alias.startswith("__PREFIX__:"):
                continue
            resolved = self._alias_to_module(module, from_alias)
            if resolved is None:
                continue
            if prefixes and not any(name.startswith(p) for p in prefixes):
                continue
            if name in self.available(resolved):
                return True, "动态委托 %s→%s" % (from_alias, resolved)
        return False, ""

    def _rule_for(self, module: str) -> list:
        return [r for r in self.rules if r["module"] == module]

    def _alias_to_module(self, module: str, alias: str) -> "str | None":
        """把 `__getattr__` 里 `getattr(alias, name)` 的 alias 还原成包内模块全名。"""
        tree = self.trees.get(module)
        if tree is None:
            return None
        pkgs = module.split(".")[:-1]
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                base = node.module or ""
                level = node.level or 0
                if level:
                    keep = len(pkgs) - (level - 1)
                    if keep < 0:
                        continue
                    base = ".".join(pkgs[:keep] + ([base] if base else []))
                elif base and not (base == self.root_name or base.startswith(self.root_name + ".")):
                    continue
                for a in node.names:
                    if a.name == "*":
                        continue
                    if (a.asname or a.name.split(".")[0]) == alias:
                        cand = "%s.%s" % (base, a.name) if base else a.name
                        if cand in self.module_files:
                            return cand
            if isinstance(node, ast.Import):
                for a in node.names:
                    if (a.asname or a.name.split(".")[0]) == alias and a.name in self.module_files:
                        return a.name
        return None

    def open_surface(self, module: str) -> "str | None":
        s = self.surfaces.get(module)
        if s and s.open_rules:
            return "%s（%s:%s）" % (s.open_rules[0][0], module, s.open_rules[0][1])
        return None


# ============================================================
# import 采集（含函数体内的延迟 import）
# ============================================================

def _import_text(lines: list, node) -> str:
    try:
        return lines[node.lineno - 1].strip()
    except Exception:                                              # noqa: BLE001
        return "<import>"


def _resolve_base(pkg: Package, src_module: str, level: int, module: "str | None") -> "str | None":
    """import 语句 → 目标模块全名（包外/越界 → None）。

    相对导入基准铁律：`__init__.py` 的模块**就是包本身**（`content/effects/__init__.py`
    → 模块 `content.effects`），所以 1 个点 = `content.effects`；普通模块（`content/effects/x.py`
    → 模块 `content.effects.x`）1 个点才是 `content.effects`。
    两种情形的差别就在这里（写错过一次：`from .poi_effects import …` 被判成 `content.poi_effects`）。
    """
    if level <= 0:
        if not module:
            return None
        if module == pkg.root_name or module.startswith(pkg.root_name + "."):
            return module
        return None
    if not src_module:
        return None
    parts = src_module.split(".")
    is_pkg_init = os.path.basename(pkg.resolve(src_module) or "").lower() == "__init__.py"
    body = parts if is_pkg_init else parts[:-1]
    drop = level - 1                       # 1 个点 = 当前包；2 个点 = 上一层
    if drop > len(body):
        return None
    base_parts = body[:len(body) - drop] if drop else body
    if not base_parts:
        return None
    base = ".".join(base_parts)
    if module:
        base = "%s.%s" % (base, module)
    return base


def collect_imports(pkg: Package, abs_path: str, tree, lines: list) -> list:
    src_module = pkg.module_of_path(abs_path)
    refs: list = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == pkg.root_name or alias.name.startswith(pkg.root_name + "."):
                    refs.append(ImportRef(pkg.rel_of(abs_path), src_module, node.lineno,
                                          _import_text(lines, node), alias.name,
                                          alias.asname or alias.name.split(".")[0]))
            continue
        if isinstance(node, ast.ImportFrom):
            base = _resolve_base(pkg, src_module, node.level or 0, node.module)
            if base is None:
                continue
            for alias in node.names:
                refs.append(ImportRef(pkg.rel_of(abs_path), src_module, node.lineno,
                                      _import_text(lines, node), base,
                                      alias.name, star=(alias.name == "*")))
    seen, uniq = set(), []
    for r in refs:
        key = (r.src_file, r.line, r.target, r.name)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    uniq.sort(key=lambda r: (r.line, r.name))
    return uniq


# ============================================================
# 包发现
# ============================================================

def _import_root_name(pkg_dir: str) -> str:
    """包内模块的**顶层 import 名**。

    口径来自加载器本身（`saintess_engine/package.py:26`）：
    「先 `sys.path` 加**包根**（不是 `content/`）→ `content` 成为命名空间包 → `import content.apply`」。
    所以包内 import 的顶层名一律是**包根下的那个目录名**（本仓 = `content`），
    与 `game.json.id`（包 id，带 hyphen 时还不是合法标识符）**无关**。
    `content` 目录名本身理论上也能换（加载器用 `game.json.entry` 认入口），
    这里按 `entry` 的目录段还原；再不行才退回内容目录名。
    """
    manifest = os.path.join(pkg_dir, "game.json")
    entry = ""
    if os.path.isfile(manifest):
        try:
            with open(manifest, encoding="utf-8") as f:
                entry = str(json.load(f).get("entry") or "").strip()
        except Exception:                                          # noqa: BLE001
            entry = ""
    if entry:
        head = entry.replace("\\", "/").split("/")[0]
        if head and os.path.isdir(os.path.join(pkg_dir, head)):
            return head
    content = os.path.join(pkg_dir, "content")
    if os.path.isdir(content):
        return "content"
    return os.path.basename(pkg_dir)


def _mk_pkg(pkg_dir: str) -> "Package | None":
    pkg_dir = os.path.abspath(pkg_dir)
    if not os.path.isdir(pkg_dir):
        print("❌ 不是目录：%s" % pkg_dir)
        return None
    content = os.path.join(pkg_dir, "content")
    if not os.path.isdir(content):
        return None
    return Package(pkg_dir, "content", _import_root_name(pkg_dir))


def discover_packages() -> list:
    override = os.getenv("IMPGATE_PKG_ROOT")
    if override:
        out = [_mk_pkg(override)]
        for p in (os.getenv("IMPGATE_EXTRA_PKGS") or "").split(";"):
            if p.strip():
                out.append(_mk_pkg(p.strip()))
        return _dedupe([p for p in out if p])
    out = []
    games = os.path.join(REPO_ROOT, "games")
    if os.path.isdir(games):
        for name in sorted(os.listdir(games)):
            d = os.path.join(games, name)
            if os.path.isdir(d) and os.path.isfile(os.path.join(d, "game.json")):
                out.append(_mk_pkg(d))
    mini = os.path.join(REPO_ROOT, "examples", "minimal-game")
    if os.path.isdir(mini) and os.path.isfile(os.path.join(mini, "game.json")):
        out.append(_mk_pkg(mini))
    return _dedupe([p for p in out if p])


def _dedupe(pkgs: list) -> list:
    """同一个真实目录只扫一遍（overlay 连结 / 参数重复都可能指同一份）。"""
    seen, out = set(), []
    for p in pkgs:
        if p.real_dir in seen:
            continue
        seen.add(p.real_dir)
        out.append(p)
    return out


# ============================================================
# 动态导出白名单装载（内置 + override，含锚点自检）
# ============================================================

def load_rules(sources: dict) -> "list | None":
    rules = [dict(r, hits=[], source="builtin") for r in DYNAMIC_EXPORT_RULES]
    raw = os.getenv("IMPGATE_DYNAMIC_RULES")
    if raw:
        try:
            extra = json.loads(raw)
        except Exception as exc:                                   # noqa: BLE001
            print("❌ IMPGATE_DYNAMIC_RULES 不是合法 JSON：%s" % exc)
            return None
        for r in extra:
            miss = [k for k in ("module", "kind", "reason", "evidence") if not r.get(k)]
            if miss:
                print("❌ IMPGATE_DYNAMIC_RULES 条目缺字段 %s：%r" % (miss, r))
                return None
            if r["kind"] not in ("getattr", "all", "globals_update"):
                print("❌ IMPGATE_DYNAMIC_RULES kind 非法：%r" % (r["kind"],))
                return None
            if not (r.get("names") or r.get("prefix")):
                print("❌ IMPGATE_DYNAMIC_RULES 条目既无 names 也无 prefix：%r" % (r,))
                return None
            rules.append(dict(r, hits=[], source="override"))
    # 锚点自检：原文必须真的出现（防「白名单写了个不存在的机制」）
    ok = True
    for r in rules:
        mod = r["module"]
        if mod not in sources:
            print("❌ 动态白名单条目指向不存在的模块：%s" % mod)
            ok = False
            continue
        if r.get("from_mod") and r["from_mod"] not in sources:
            print("❌ 动态白名单条目 %s 的 from_mod 不存在：%s" % (mod, r["from_mod"]))
            ok = False
        if r["evidence"] not in sources[mod]:
            print("❌ 动态白名单条目 %s 的原文锚点对不上（源码里找不到）：%r" % (mod, r["evidence"]))
            ok = False
    return rules if ok else None


# ============================================================
# 主流程
# ============================================================

def scan_package(pkg: Package, rules: list) -> None:
    pkg.rules = rules
    pkg.files, pkg.module_files = [], {}
    pkg.gaps, pkg.import_refs = [], []
    pkg.discover()
    pkg.load_sources()

    for rel in pkg.files:
        path = os.path.join(pkg.dir, rel)
        mod = pkg._module_of(rel)
        tree = pkg.trees.get(mod)
        if tree is None:
            continue
        lines = pkg.sources[mod].splitlines()
        for ref in collect_imports(pkg, path, tree, lines):
            pkg.import_refs.append(ref)
            target_path = pkg.resolve(ref.target)
            if target_path is None:
                pkg.gaps.append(Gap(
                    "missing_module", ref,
                    "target module %s does not exist (no %s.py and no %s/__init__.py)"
                    % (ref.target, ref.target.replace(".", "/"), ref.target.replace(".", "/"))))
                continue
            if ref.star:
                if not pkg.available(ref.target):
                    pkg.gaps.append(Gap(
                        "star_empty", ref,
                        "`import *` target module has an empty export surface "
                        "(no static name / no __all__ / no dynamic face)", 0))
                continue
            found, why = pkg.has_name(ref.target, ref.name)
            if found:
                if why.startswith("动态"):
                    print("   * [dynamic-face allow] %s | %s | %s -> %s"
                          % (ref.where(), ref.text.strip(), ref.name, why))
                continue
            if pkg.open_surface(ref.target):
                continue          # 目标模块有不可枚举的动态导出面 → 不算缺口（下面会点名）
            surface = pkg.surfaces.get(ref.target)
            extra = ""
            if surface and surface.mechanisms:
                extra = "target module mechanisms: %s" % "，".join(surface.mechanisms[:3])
            pkg.gaps.append(Gap(
                "missing_name", ref,
                "`%s` not found in target module %s (%s)"
                % (ref.name, ref.target, pkg.label_of(target_path)),
                len(pkg.available(ref.target)), extra=extra))

    # 兜底去重（同一处 import 的同一名字只留一条，绝不重复计数）
    seen, uniq = set(), []
    for g in pkg.gaps:
        key = (g.kind, g.ref.src_file, g.ref.line, g.ref.target, g.ref.name)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(g)
    pkg.gaps = uniq


# ============================================================
# 输出
# ============================================================

def banner(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def print_rule_ledger(rules: list) -> None:
    print("\n[动态导出面白名单 / dynamic-export whitelist]"
          "（照代码事实登记；每条必须能说出为什么它算动态）")
    if not rules:
        print("  (none)")
        return
    for r in rules:
        names = r.get("names") or []
        pfx = r.get("prefix") or ""
        print("  * %s <- kind=%s%s%s  [%s]"
              % (r["module"], r["kind"],
                 (" names=%s" % (names,)) if names else "",
                 (" prefix=%r" % pfx) if pfx else "",
                 r.get("source", "builtin")))
        print("      理由 / reason：%s" % r["reason"])
        if r.get("from_mod"):
            print("      转发目标（按那个模块的导出面判定，不写死名单）：%s" % r["from_mod"])
        print("      原文锚点 / evidence：%r · 本次命中 hits=%d"
              % (r["evidence"], len(r.get("hits") or [])))
        if r.get("note"):
            print("      备注 / note：%s" % r["note"])
        if not (r.get("hits") or []):
            print("      [WARN] 本次 0 命中（留档；不是用来掩盖缺口）")


def print_open_surfaces(packages: list) -> None:
    hits = []
    for pkg in packages:
        for mod, s in sorted(pkg.surfaces.items()):
            for why, line in s.open_rules:
                hits.append("  * %s:%s  %s" % (mod, line, why))
    if hits:
        print("\n[不可静态枚举的动态导出面 / unenumerable faces]"
              "（这些模块的名字断言按「放行 + 点名」处理，原因照实打印）")
        for h in hits:
            print(h)


def print_delegations(packages: list) -> None:
    lines = []
    for pkg in packages:
        for mod, s in sorted(pkg.surfaces.items()):
            for from_alias, prefixes, ev in s.delegations:
                if from_alias.startswith("__PREFIX__:"):
                    continue
                resolved = pkg._alias_to_module(mod, from_alias)
                lines.append("  * %s: line %s `__getattr__` delegates to %s%s => copy its surface"
                             % (mod, ev, resolved or from_alias,
                                "" if not prefixes else " (prefix %r)" % prefixes[0]))
    if lines:
        print("\n[动态面：模块级 __getattr__ 的委托 / getattr delegation]")
        for line in lines:
            print(line)


def main(argv) -> int:
    packages = discover_packages()
    if not packages:
        print("[FAIL] no content package found (need a dir with game.json + content/)")
        return 1

    # 先读原文（白名单锚点自检要源码）—— 与正式扫描同一发现口径（含 overlay）
    sources = {}
    for pkg in packages:
        pkg.discover()
        for rel in pkg.files:
            mod = pkg._module_of(rel)
            if not mod:
                continue
            sources[mod] = pkg.read_file(rel)

    rules = load_rules(sources)
    if rules is None:
        print("[FAIL] dynamic-export whitelist failed to load (anchors/refs) -- treated RED")
        return 1

    if "--list" in argv:
        for pkg in packages:
            pkg.discover()
            print("package %s (import root=%r, %d .py)" % (pkg.dir, pkg.root_name, len(pkg.files)))
            for rel in pkg.files:
                print("   ", rel)
        return 0

    banner("包内 import 面自洽门禁（AST · 含函数体内延迟 import）"
           " / intra-package import closure gate")
    print("仓库根 repo root：%s" % REPO_ROOT)
    for pkg in packages:
        print("包 package：%s（import 根名 %r）" % (pkg.dir, pkg.root_name))
    for pkg in packages:
        scan_package(pkg, rules)

    overlaid = sorted({rel for p in packages for rel in getattr(p, "overlaid", [])})
    if overlaid:
        print("\n[反证 overlay] 本次扫描用副本替换了 %d 个文件（真仓只读）：%s"
              % (len(overlaid), "，".join(overlaid)))

    total_files = sum(len(p.files) for p in packages)
    total_imports = sum(len(p.import_refs) for p in packages)
    total_gaps = sum(len(p.gaps) for p in packages)

    print("\n扫描面 scan surface：%d 个包 · %d 个 .py · %d 条包内 import"
          % (len(packages), total_files, total_imports))
    if total_files == 0 or total_imports == 0:
        print("[FAIL] scan surface is empty -- the gate scanned nothing (broken口径) -> RED")
        return 1

    print_rule_ledger(rules)
    print_delegations(packages)

    for pkg in packages:
        if pkg.gaps:
            banner("[FAIL] %s：%d 处包内 import 面不自洽 / closure gaps"
                   % (pkg.dir, len(pkg.gaps)))
            for g in sorted(pkg.gaps, key=lambda x: (x.ref.src_file, x.ref.line)):
                print("  %s" % g.render())
        else:
            print("\n[OK] %s：%d 条包内 import 全部自洽" % (pkg.dir, len(pkg.import_refs)))

    print_open_surfaces(packages)

    payload = {
        "repo_root": REPO_ROOT,
        "packages": [{
            "dir": pkg.dir,
            "root_name": pkg.root_name,
            "files": len(pkg.files),
            "imports": len(pkg.import_refs),
            "gaps": [{"file": g.ref.src_file, "line": g.ref.line,
                      "import": g.ref.text.strip(), "target": g.ref.target,
                      "missing": g.ref.name if g.kind == "missing_name" else g.ref.target,
                      "kind": g.kind, "detail": g.detail, "target_names": g.avail}
                     for g in pkg.gaps],
        } for pkg in packages],
        "rules": [{"module": r["module"], "kind": r["kind"], "names": r.get("names"),
                   "prefix": r.get("prefix"), "from_mod": r.get("from_mod"),
                   "reason": r["reason"], "evidence": r["evidence"],
                   "source": r.get("source"), "hits": len(r.get("hits") or [])}
                  for r in rules],
    }
    if "--json" in argv or os.getenv("IMPGATE_JSON"):
        print("\n--- JSON ---")
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    print("\n" + "=" * 72)
    if total_gaps:
        print("[FAIL] 包内 import 面自洽门禁：%d 处缺口"
              "（kind=missing_module / missing_name；逐条见上）" % total_gaps)
        return 1
    print("[OK] 包内 import 面自洽门禁：全绿（%d 个包 · %d 个文件 · %d 条 import）"
          % (len(packages), total_files, total_imports))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
