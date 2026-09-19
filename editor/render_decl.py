# -*- coding: utf-8 -*-
"""编辑器扩展面**第 3 层 · 批 1**：包侧渲染声明的 **schema 校验 + 白名单表**。

设计真源：`overnight/layer3-render-design.md` §9「批 1 · 声明面」
          + `overnight/layer3-render-contracts.md` §0（寻址/上限）与 §1（域声明字段表）。

本模块**只做纯函数**：吃一份已经 `json.load` 出来的原始声明 → 吐出**规范化后的声明**
（只留白名单内的东西）+ **一列可读告警**。它：

* **不读盘**（文件 IO 在 `editor/render.py`）、**不执行任何包代码**、**零引擎 import**；
* **永不抛**：坏形状一律「丢弃该项 + 告警」，与第 1/2 层同一条纪律（坏声明不 500、不白屏）；
* **不透传**：任何白名单外的键/槽位/钩子/块类型/派生函数名 → 丢弃 + 告警（透传 = 逃逸面）。

三条口径（照契约原文，别自己发挥）
--------------------------------
1. **块类型白名单只有 5 种**：`fields` / `text` / `list` / `table` / `kv`（`KINDS`）。
2. **路径文法**（契约 §2.3 H5）：`^[A-Za-z_][A-Za-z0-9_]*(\\.[A-Za-z_][A-Za-z0-9_]*|\\[\\d+\\]|\\[\\*\\])*$`
   —— 无 `..`、无 `/`、无 `\\`。根字段必须在该域 schema 的 `$defs[x-primary].properties` 里
   （契约 §0 R3，根字段判定，不递归判深层）。
3. **条件文法刻意极小**（契约 §1.1 `when` 深度 ≤ 4）：相等 / `in` / `truthy` / `exists` /
   白名单比较符 `gt/ge/lt/le/eq/ne` / `all` / `any`（各 ≤ 4 支）。**没有**脚本、没有函数调用、
   没有跨域引用。

对外接口
--------
    KINDS / DERIVE_FNS / HOOKS / SLOT_KEYS / WIDGETS / FORMATS / TONES / OPS   # 白名单表
    MAX_*                                                                     # 上限（与契约同源）
    valid_path(p) / path_depth(p) / root_field(p)                             # 路径文法
    norm_decl(raw, dom, fields, label="") -> (decl | None, [告警])            # ★ 主入口
    cond_ok(cond, data) -> bool                                               # 条件求值（纯函数）
    path_get(data, path) -> 值 | None                                         # 路径取值（只读）
    template_paths(text) -> [(path, zh), ...]                                 # 插值点抽取（给限额判定）
"""
from __future__ import annotations

import re

# ═══════════════════════════════ 一、白名单表 ═══════════════════════════════
#: 块形态（**只有这 5 种**；`kind` 不在表里 → 丢弃该块 + 告警）
KINDS = ("fields", "text", "list", "table", "kv")
#: `$extends`：与第 2 层 `views.json` 的关系（非法值 → 按 form + 告警）
EXTENDS = ("form", "view", "none")
#: `FieldOverride.widget` / glossary 控件白名单
WIDGETS = ("auto", "text", "textarea", "number", "slider", "select", "tags",
           "checkbox", "json")
#: 只读展示格式（不改数据）
FORMATS = ("plain", "number", "percent", "date")
#: 角标/面板色调
TONES = ("info", "ok", "warn", "bad")
#: `when` 里的比较运算符（**没有** `+ - * /`，没有函数调用）
OPS = ("gt", "ge", "lt", "le", "eq", "ne", "in", "truthy", "exists")
#: 校验钩子白名单（**只许点名**，包不能内联表达式/正则串）
HOOKS = ("primary_unique", "ref_exists", "range", "enum_closed", "not_blank", "regex")
#: 派生函数白名单（批 2 才执行；批 1 只校验名字，不计算）
DERIVE_FNS = ("count", "sum", "avg", "min", "max", "ratio", "percent_share",
              "weighted_total", "group_count", "lookup_label", "join_text", "fmt_number")
#: 受控交互槽（槽位名 + 每个槽位允许的键；未知槽位/未知键 → 丢弃 + 告警）
SLOT_KEYS = {
    "list_editor": ("field", "item_fields", "allow_add", "allow_del",
                    "allow_reorder", "min", "max"),
    "ref_picker": ("field", "domain", "by", "multiple", "searchable"),
    "code_editor": ("field", "language", "line_numbers"),
    "preview_panel": ("derive", "position", "collapsible"),
    "diff_view": ("field", "source"),
}
SLOT_DEFAULTS = {
    "list_editor": {"allow_add": True, "allow_del": True, "allow_reorder": False},
    "ref_picker": {"by": "key", "multiple": False, "searchable": True},
    "code_editor": {"language": "json", "line_numbers": True},
    "preview_panel": {"position": "right", "collapsible": True},
    "diff_view": {"source": "entry"},
}

# 顶层键（未知顶层键 → 丢弃 + 告警，**绝不透传**）
TOP_KEYS = ("$version", "$extends", "$allow_code", "title", "icon", "when", "layout",
            "sections", "fields", "slots", "derives", "hooks", "readonly", "$notes")
BLOCK_KEYS = ("id", "kind", "label", "icon", "note", "columns", "collapsed", "when",
              "fields", "text", "source", "item", "empty", "max_rows")
SECTION_KEYS = ("id", "label", "icon", "collapsed", "blocks", "when")
ITEM_KEYS = ("title", "subtitle", "badges", "fields", "columns")
BADGE_KEYS = ("text", "tone", "when")
FIELD_KEYS = ("readonly", "hidden", "label", "note", "widget", "options", "checks",
              "check_args", "format")
DERIVE_KEYS = ("fn", "args", "label", "format", "tone", "when")

# ═══════════════════════════════ 二、上限（与契约 §0/§1/§4.4 同源） ═══════════════════════════════
MAX_FILE_BYTES = 256 * 1024      # 单份声明 ≤ 256 KB（超限 → 忽略该文件）
MAX_FILES = 128                  # 域声明文件数 ≤ 128
MAX_LAYOUT = 64                  # `layout` ≤ 64 块
MAX_SECTIONS = 32                # `sections` ≤ 32 组
MAX_SECTION_BLOCKS = 32          # 每组 `blocks` ≤ 32
MAX_BLOCKS_PER_TAB = 64          # 树里每个 tab 的块数（render.py 截断）
MAX_TABS = 6                     # 树里分页数 ≤ 6（契约 §2.1）
MAX_FIELDS_OVERRIDE = 128        # `fields` ≤ 128 键
MAX_BLOCK_FIELDS = 64            # `Block.fields` ≤ 64 项
MAX_SLOTS = 8                    # `slots` ≤ 8 键
MAX_DERIVES = 16                 # `derives` ≤ 16 键
MAX_HOOKS = 16                   # `hooks` ≤ 16 键
MAX_READONLY = 128               # `readonly` ≤ 128 项
MAX_TITLE = 80
MAX_LABEL = 80
MAX_ICON_CP = 2                  # 单 emoji（最多 2 个码点）
MAX_NOTE = 500
MAX_FIELD_NOTE = 300
MAX_FIELD_LABEL = 60
MAX_TEXT = 2000
MAX_NOTES = 2000
MAX_ITEM_TITLE = 120
MAX_ITEM_SUBTITLE = 160
MAX_BADGES = 4
MAX_BADGE_TEXT = 40
MAX_ITEM_FIELDS = 16
MAX_ITEM_COLUMNS = 12
MAX_COLUMNS = 4                  # `Block.columns` 1..4
MAX_ROWS_DEFAULT = 200
MAX_ROWS = 500
MAX_OPTIONS = 500
MAX_CHECKS = 8
MAX_INTERP = 8                   # 插值点 ≤ 8
MAX_PATH_DEPTH = 6               # 路径深度 ≤ 6
MAX_COND_DEPTH = 4               # `when` 深度 ≤ 4
MAX_COND_BRANCH = 4              # `all` / `any` 分支 ≤ 4
MAX_TREE_BYTES = 256 * 1024      # 树序列化字节 ≤ 256 KB（render.py 截断）
MAX_TREE_BLOCKS = 64
MAX_LIST_ITEMS = 200             # 树里 `list` 预渲染项 ≤ 200

_ID_RE = re.compile(r"^[a-z][a-z0-9_\-]{0,40}$")
_PATH_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*|\[\d+\]|\[\*\])*$")
#: 插值标记：`{{` / `}}` 是字面量；其余 `{...}` 是插值点
_INTERP_RE = re.compile(r"\{\{(?![{}])|\}\}|(?<!\{)\{([^{}]*)\}(?!\})")
_TOKENS = ("all", "any")


# ═══════════════════════════════ 三、小工具（全部纯函数） ═══════════════════════════════
def clip(s, n: int) -> str:
    """超长串截断（加省略号）—— 与 `table_view._short` 同一口径。"""
    s = str(s)
    return s if len(s) <= n else s[:max(1, n - 1)] + "…"


def valid_path(p) -> bool:
    """字段路径文法（契约 §2.3 H5）：不许 `..` / `/` / `\\`，只许 `.键` / `[n]` / `[*]`。"""
    return isinstance(p, str) and bool(_PATH_RE.match(p))


def path_depth(p: str) -> int:
    """路径深度 = `a.b[0].c` → 3（根字段算 1 层）。"""
    if not isinstance(p, str) or not p:
        return 0
    n = 1
    for ch in re.finditer(r"\.[A-Za-z_]|\[", p):
        n += 1
    return n


def root_field(p: str) -> str:
    """路径的根字段名（`a.b[0]` → `a`）。"""
    s = str(p or "")
    for i, ch in enumerate(s):
        if ch in ".[":
            return s[:i]
    return s


def split_path(p: str) -> list:
    """路径 → 段列表；`a.b[0].c` → `["a", "b", 0, "c"]`，`[*]` → `"*"`。"""
    out: list = []
    for seg in re.finditer(r"[A-Za-z_][A-Za-z0-9_]*|\[(\d+|\*)\]", str(p or "")):
        tok = seg.group(0)
        if tok.startswith("["):
            inner = tok[1:-1]
            out.append("*" if inner == "*" else int(inner))
        else:
            out.append(tok)
    return out


def path_get(data, path: str):
    """只读取值：`None` = 取不到。`[*]` → 把**剩余路径**映射到每个元素上（返回列表）。"""
    if not valid_path(path):
        return None
    return _get_segs(data, split_path(path))


def _get_segs(cur, segs: list):
    if not segs:
        return cur
    seg, rest = segs[0], segs[1:]
    if seg == "*":
        if not isinstance(cur, list):
            return None
        return [_get_segs(x, rest) for x in cur]
    if isinstance(seg, int):
        if not isinstance(cur, list) or not (0 <= seg < len(cur)):
            return None
        return _get_segs(cur[seg], rest)
    if not isinstance(cur, dict) or seg not in cur:
        return None
    return _get_segs(cur[seg], rest)


def template_paths(text) -> list:
    """抽插值点 → `[(路径, 是否 |zh), ...]`（`{{`/`}}` 不算；非法段一并回，便于告警）。"""
    out = []
    for m in _INTERP_RE.finditer(str(text or "")):
        body = m.group(1)
        if body is None:
            continue
        body = body.strip()
        if not body:
            continue
        if body.startswith("derive:"):
            out.append(("derive:" + body[len("derive:"):].strip(), False))
            continue
        zh = False
        if body.endswith("|zh"):
            zh, body = True, body[:-3].strip()
        out.append((body, zh))
    return out


# ═══════════════════════════════ 四、条件（when） ═══════════════════════════════
def _norm_cond(obj, where: str, warns: list, depth: int = 1):
    """条件对象 → 规范化条件 | None（坏形状 → 丢弃该项 + 告警）。"""
    if obj is None:
        return None                                     # 没写 = 没有条件（正常，不告警）
    if not isinstance(obj, dict) or not obj:
        warns.append(f"{where}：when 需为非空对象（实为 {obj!r}）—— 该条件已忽略")
        return None
    if depth > MAX_COND_DEPTH:
        warns.append(f"{where}：when 嵌套超过 {MAX_COND_DEPTH} 层 —— 该条件已忽略")
        return None
    for key in _TOKENS:
        if key in obj:
            branch = obj[key]
            if not isinstance(branch, list) or not branch:
                warns.append(f"{where}：when.{key} 需为非空数组 —— 该条件已忽略")
                return None
            if len(branch) > MAX_COND_BRANCH:
                warns.append(f"{where}：when.{key} 分支超过 {MAX_COND_BRANCH} 个"
                             f"（实为 {len(branch)}）—— 只取前 {MAX_COND_BRANCH} 个")
                branch = branch[:MAX_COND_BRANCH]
            subs = [_norm_cond(b, where, warns, depth + 1) for b in branch]
            subs = [s for s in subs if s is not None]
            return {key: subs} if subs else None
    if len(obj) != 1:
        warns.append(f"{where}：when 只支持「一个字段一个条件」或 all/any（实为 {obj!r}）"
                     " —— 该条件已忽略")
        return None
    path, want = next(iter(obj.items()))
    if not valid_path(path) or path_depth(path) > MAX_PATH_DEPTH:
        warns.append(f"{where}：when 的字段路径 {path!r} 不合规（或深度 > {MAX_PATH_DEPTH}）"
                     " —— 该条件已忽略")
        return None
    if isinstance(want, dict):
        if len(want) != 1 or next(iter(want)) not in OPS:
            warns.append(f"{where}：when.{path} 的运算符不在白名单 "
                         f"（{' / '.join(OPS)}）—— 该条件已忽略")
            return None
        op, val = next(iter(want.items()))
        if op == "in":
            if not isinstance(val, list) or not val:
                warns.append(f"{where}：when.{path}.in 需为非空数组 —— 该条件已忽略")
                return None
        elif op in ("truthy", "exists"):
            if not isinstance(val, bool):
                val = True
        elif not isinstance(val, (int, float, str, bool)):
            warns.append(f"{where}：when.{path}.{op} 只能比标量 —— 该条件已忽略")
            return None
        return {"path": path, "op": op, "value": val}
    return {"path": path, "op": "eq", "value": want}


def _match_one(got, op, want) -> bool:
    if op == "exists":
        ok = got is not None and got != "" and got != [] and got != {}
        return (not ok) if want is False else ok
    if op == "truthy":
        return (not bool(got)) if want is False else bool(got)
    if op == "in":
        vals = want if isinstance(want, list) else [want]
        return got in vals
    if op in ("gt", "ge", "lt", "le"):
        if not isinstance(got, (int, float)) or isinstance(got, bool):
            return False
        if not isinstance(want, (int, float)) or isinstance(want, bool):
            return False
        return {"gt": got > want, "ge": got >= want,
                "lt": got < want, "le": got <= want}[op]
    if op == "ne":
        return got != want
    return got == want


def cond_ok(cond, data) -> bool:
    """条件求值（纯函数；**永不抛**）。空 / 坏条件 → True（「没条件 = 显示」）。

    `[*]` 命中的是**列表** → 按「任一项命中」出布尔（契约 §3.4：数组条件只出布尔）。
    """
    if not isinstance(cond, dict) or not cond:
        return True
    if "all" in cond:
        return all(cond_ok(c, data) for c in (cond.get("all") or []))
    if "any" in cond:
        return any(cond_ok(c, data) for c in (cond.get("any") or []))
    got = path_get(data, cond.get("path") or "")
    op, want = cond.get("op"), cond.get("value")
    if isinstance(got, list):
        if not got:                       # 空数组按「值本身」判（exists:false → 命中）
            return _match_one(got, op, want)
        return any(_match_one(g, op, want) for g in got)
    return _match_one(got, op, want)


# ═══════════════════════════════ 五、各层字段校验 ═══════════════════════════════
def _str_field(meta, key, warns, where, limit=0, default=None):
    v = meta.get(key)
    if v is None:
        return default
    if not isinstance(v, str) or not v.strip():
        warns.append(f"{where}：{key} 需为非空字符串 —— 已忽略")
        return default
    if limit and len(v) > limit:
        warns.append(f"{where}：{key} 超过 {limit} 字（实为 {len(v)}）—— 已截断")
        return clip(v, limit)
    return v


def _icon_field(meta, key, warns, where):
    v = meta.get(key)
    if v is None:
        return None
    if not isinstance(v, str):
        warns.append(f"{where}：{key} 需为单个 emoji 字符串 —— 已忽略")
        return None
    if len(v) > MAX_ICON_CP:
        warns.append(f"{where}：{key} 超过 {MAX_ICON_CP} 个码点（实为 {len(v)}）—— 已忽略")
        return None
    return v


def _bool_field(meta, key, warns, where, default=False):
    v = meta.get(key)
    if v is None:
        return default
    if not isinstance(v, bool):
        warns.append(f"{where}：{key} 需为 true/false —— 按 {default} 处理")
        return default
    return v


def _check_template(text: str, fields, warns, where: str) -> bool:
    """插值点限额 + 路径合法性（不合法 → 该项被忽略）。"""
    pts = template_paths(text)
    if len(pts) > MAX_INTERP:
        warns.append(f"{where}：插值点超过 {MAX_INTERP} 个（实为 {len(pts)}）—— 该项已忽略")
        return False
    for path, _zh in pts:
        if path.startswith("derive:"):
            continue                                    # 派生名的存在性在 render.py 判
        if not valid_path(path):
            warns.append(f"{where}：插值路径 {path!r} 不合规（无 .. / / / \\\\）—— 该项已忽略")
            return False
        if path_depth(path) > MAX_PATH_DEPTH:
            warns.append(f"{where}：插值路径 {path!r} 深度超过 {MAX_PATH_DEPTH} —— 该项已忽略")
            return False
        if "[*]" in path:
            warns.append(f"{where}：插值路径 {path!r} 含 [*]（插值不支持通配）—— 该项已忽略")
            return False
        if fields is not None and root_field(path) not in fields:
            warns.append(f"{where}：插值字段 {root_field(path)!r} 不在该域 schema 里"
                         " —— 该项已忽略")
            return False
    return True


def _check_field_path(path, fields, warns, where: str) -> bool:
    """R3：路径文法 + 深度 + 根字段必须在该域 schema 里。"""
    if not valid_path(path):
        warns.append(f"{where}：字段路径 {path!r} 不合规（无 .. / / / \\\\）—— 该项已忽略")
        return False
    if path_depth(path) > MAX_PATH_DEPTH:
        warns.append(f"{where}：字段路径 {path!r} 深度超过 {MAX_PATH_DEPTH} —— 该项已忽略")
        return False
    if fields is not None and root_field(path) not in fields:
        warns.append(f"{where}：字段 {root_field(path)!r} 不在该域 schema 里 —— 该项已忽略")
        return False
    return True


def _norm_override(path: str, meta, fields, warns: list, where: str):
    if not isinstance(meta, dict):
        warns.append(f"{where}：字段覆盖需为对象 —— 该项已忽略")
        return None
    for k in meta:
        if k not in FIELD_KEYS:
            warns.append(f"{where}：未知键 {k!r}（白名单：{' / '.join(FIELD_KEYS)}）—— 已忽略")
    out = {"readonly": _bool_field(meta, "readonly", warns, where, False),
           "hidden": _bool_field(meta, "hidden", warns, where, False)}
    lab = _str_field(meta, "label", warns, where, MAX_FIELD_LABEL)
    if lab:
        out["label"] = lab
    note = _str_field(meta, "note", warns, where, MAX_FIELD_NOTE)
    if note:
        out["note"] = note
    widget = meta.get("widget")
    if widget is not None:
        if widget not in WIDGETS:
            warns.append(f"{where}：widget={widget!r} 不在白名单（{' / '.join(WIDGETS)}）"
                         " —— 按 auto 处理")
            widget = "auto"
        out["widget"] = widget
    fmt = meta.get("format")
    if fmt is not None:
        if fmt not in FORMATS:
            warns.append(f"{where}：format={fmt!r} 不在白名单（{' / '.join(FORMATS)}）"
                         " —— 按 plain 处理")
            fmt = "plain"
        out["format"] = fmt
    opts = meta.get("options")
    if opts is not None:
        if isinstance(opts, list) and all(isinstance(x, str) for x in opts):
            if len(opts) > MAX_OPTIONS:
                warns.append(f"{where}：options 超过 {MAX_OPTIONS} 项 —— 只取前 {MAX_OPTIONS}")
                opts = opts[:MAX_OPTIONS]
            out["options"] = list(opts)
        elif isinstance(opts, dict) and isinstance(opts.get("ref"), dict) \
                and isinstance(opts["ref"].get("domain"), str) and opts["ref"]["domain"]:
            by = opts["ref"].get("by", "key")
            if by not in ("key", "name"):
                warns.append(f"{where}：options.ref.by={by!r} 非法（key / name）—— 按 key")
                by = "key"
            out["options"] = {"ref": {"domain": opts["ref"]["domain"], "by": by}}
        else:
            warns.append(f"{where}：options 需为字符串数组或 {{\"ref\": {{\"domain\": …}}}}"
                         f"（实为 {opts!r}）—— 已忽略")
    checks = meta.get("checks")
    if checks is not None:
        if not isinstance(checks, list) or not all(isinstance(x, str) for x in checks):
            warns.append(f"{where}：checks 需为字符串数组 —— 已忽略")
        else:
            keep = []
            if len(checks) > MAX_CHECKS:
                warns.append(f"{where}：checks 超过 {MAX_CHECKS} 项 —— 只取前 {MAX_CHECKS}")
                checks = checks[:MAX_CHECKS]
            for c in checks:
                if c in HOOKS:
                    keep.append(c)
                else:
                    warns.append(f"{where}：未知校验钩子 {c!r}（白名单：{' / '.join(HOOKS)}）"
                                 " —— 已忽略")
            if keep:
                out["checks"] = keep
    args = meta.get("check_args")
    if isinstance(args, dict) and args:
        bad = [k for k in args if k not in HOOKS]
        for k in bad:
            warns.append(f"{where}：check_args 里的键 {k!r} 不是白名单钩子名 —— 已忽略")
        keep_args = {k: v for k, v in args.items() if k in HOOKS}
        if keep_args:
            out["check_args"] = keep_args
    elif args is not None:
        warns.append(f"{where}：check_args 需为对象 —— 已忽略")
    return out


def _norm_badges(spec, fields, warns, where):
    raw = spec.get("badges")
    if raw is None:
        return []
    if not isinstance(raw, list):
        warns.append(f"{where}：badges 需为数组 —— 已忽略")
        return []
    if len(raw) > MAX_BADGES:
        warns.append(f"{where}：badges 超过 {MAX_BADGES} 个 —— 只取前 {MAX_BADGES}")
        raw = raw[:MAX_BADGES]
    out = []
    for i, b in enumerate(raw, 1):
        w = f"{where}.badges[{i}]"
        if not isinstance(b, dict):
            warns.append(f"{w}：需为对象 —— 已忽略")
            continue
        for k in b:
            if k not in BADGE_KEYS:
                warns.append(f"{w}：未知键 {k!r}（白名单：{' / '.join(BADGE_KEYS)}）—— 已忽略")
        text = _str_field(b, "text", warns, w, MAX_BADGE_TEXT)
        if not text:
            warns.append(f"{w}：缺 text —— 已忽略")
            continue
        if not _check_template(text, fields, warns, w):
            continue
        tone = b.get("tone", "info")
        if tone not in TONES:
            warns.append(f"{w}：tone={tone!r} 不在白名单（{' / '.join(TONES)}）—— 按 info")
            tone = "info"
        out.append({"text": text, "tone": tone, "when": _norm_cond(b.get("when"), w, warns)})
    return out


def _norm_item(spec, kind: str, fields, warns, where, rel_fields=None):
    """`ItemSpec`（list/table 的单项模板）。

    `rel_fields` = **单项内部**路径的根字段集（「路径根 = 单项的键」，契约 §1.3）；`None` =
    取不到单项结构 → 内部路径**只判文法与深度**（不猜）。
    """
    if spec is None:
        return None
    if not isinstance(spec, dict):
        warns.append(f"{where}：item 需为对象 —— 已忽略")
        return None
    for k in spec:
        if k not in ITEM_KEYS:
            warns.append(f"{where}：item 未知键 {k!r}（白名单：{' / '.join(ITEM_KEYS)}）"
                         " —— 已忽略")
    rel = rel_fields                     # None = 取不到单项结构 → 只判文法与深度（不猜）
    out: dict = {}
    title = _str_field(spec, "title", warns, where, MAX_ITEM_TITLE)
    if title and _check_template(title, rel, warns, where + ".title"):
        out["title"] = title
    sub = _str_field(spec, "subtitle", warns, where, MAX_ITEM_SUBTITLE)
    if sub and _check_template(sub, rel, warns, where + ".subtitle"):
        out["subtitle"] = sub
    badges = _norm_badges(spec, rel, warns, where)
    if badges:
        out["badges"] = badges
    flds = spec.get("fields")
    if flds is not None:
        if not isinstance(flds, list) or not all(isinstance(x, str) for x in flds):
            warns.append(f"{where}：item.fields 需为字符串数组 —— 已忽略")
        else:
            if len(flds) > MAX_ITEM_FIELDS:
                warns.append(f"{where}：item.fields 超过 {MAX_ITEM_FIELDS} 项"
                             f" —— 只取前 {MAX_ITEM_FIELDS}")
                flds = flds[:MAX_ITEM_FIELDS]
            keep = [p for p in flds
                    if _check_field_path(p, rel, warns, where + ".fields")]
            if keep:
                out["fields"] = keep
    cols = spec.get("columns")
    if cols is not None:
        if not isinstance(cols, list) or not all(isinstance(x, str) for x in cols):
            warns.append(f"{where}：item.columns 需为字符串数组 —— 已忽略")
        elif kind == "table":
            if len(cols) > MAX_ITEM_COLUMNS:
                warns.append(f"{where}：item.columns 超过 {MAX_ITEM_COLUMNS} 列"
                             f" —— 只取前 {MAX_ITEM_COLUMNS}")
                cols = cols[:MAX_ITEM_COLUMNS]
            keep = [p for p in cols
                    if _check_field_path(p, rel, warns, where + ".columns")]
            if keep:
                out["columns"] = keep
        else:
            warns.append(f"{where}：item.columns 只用于 kind=table —— 已忽略")
    if kind == "table" and not out.get("columns"):
        warns.append(f"{where}：kind=table 的 item 缺 columns（表头）—— 该块已忽略")
        return None
    return out


def _norm_source(src, fields, warns, where):
    if not isinstance(src, dict) or len(src) != 1:
        warns.append(f"{where}：source 需为 {{\"field\": 路径}} 或 {{\"derive\": 名字}}"
                     f"（实为 {src!r}）—— 该块已忽略")
        return None
    if "field" in src:
        p = src["field"]
        if not _check_field_path(p, fields, warns, where + ".source"):
            return None
        return {"field": p}
    if "derive" in src:
        name = src["derive"]
        if not isinstance(name, str) or not name.strip():
            warns.append(f"{where}：source.derive 需为非空字符串 —— 该块已忽略")
            return None
        return {"derive": name.strip()}
    warns.append(f"{where}：source 只许 field / derive（实为 {list(src)}）—— 该块已忽略")
    return None


def _norm_block(blk, idx: int, fields, warns: list, where: str, sub_fields=None):
    """一个 `Block` → 规范化块 | None（None = 该块被忽略，调用方跳过并已记告警）。

    `sub_fields` = `{根数组字段: 元素属性名集合}`（单项模板的相对路径校验用；缺省 = 不猜）。
    """
    w = f"{where}[{idx}]"
    if not isinstance(blk, dict):
        warns.append(f"{w}：块需为对象 —— 该块已忽略")
        return None
    for k in blk:
        if k not in BLOCK_KEYS:
            warns.append(f"{w}：未知键 {k!r}（白名单：{' / '.join(BLOCK_KEYS)}）—— 已忽略")
    kind = blk.get("kind", "fields")
    if kind not in KINDS:
        warns.append(f"{w}：未知块类型 kind={kind!r}（白名单只有 {' / '.join(KINDS)}）"
                     " —— 该块已忽略")
        return None
    bid = blk.get("id")
    if bid is None:
        bid = f"b{idx}"
    elif not isinstance(bid, str) or not _ID_RE.match(bid):
        warns.append(f"{w}：块 id={bid!r} 不合规（^[a-z][a-z0-9_\\-]{{0,40}}$）—— 按 b{idx}")
        bid = f"b{idx}"
    out = {"id": bid, "kind": kind,
           "collapsed": _bool_field(blk, "collapsed", warns, w, False),
           "when": _norm_cond(blk.get("when"), w, warns)}
    lab = _str_field(blk, "label", warns, w, MAX_LABEL)
    if lab:
        if _check_template(lab, fields, warns, w + ".label"):
            out["label"] = lab
    icon = _icon_field(blk, "icon", warns, w)
    if icon:
        out["icon"] = icon
    note = _str_field(blk, "note", warns, w, MAX_NOTE)
    if note:
        out["note"] = note
    if kind == "fields":
        flds = blk.get("fields")
        if not isinstance(flds, list) or not all(isinstance(x, str) for x in flds):
            warns.append(f"{w}：kind=fields 需要 fields 字符串数组 —— 该块已忽略")
            return None
        if len(flds) > MAX_BLOCK_FIELDS:
            warns.append(f"{w}：fields 超过 {MAX_BLOCK_FIELDS} 项 —— 只取前 {MAX_BLOCK_FIELDS}")
            flds = flds[:MAX_BLOCK_FIELDS]
        keep = [p for p in flds if _check_field_path(p, fields, warns, w + ".fields")]
        if not keep:
            warns.append(f"{w}：kind=fields 但没有任何合法字段 —— 该空块已跳过")
            return None
        out["fields"] = keep
        cols = blk.get("columns", 1)
        if not isinstance(cols, int) or isinstance(cols, bool) or not (1 <= cols <= MAX_COLUMNS):
            warns.append(f"{w}：columns 需为 1..{MAX_COLUMNS} 的整数（实为 {cols!r}）—— 按 1")
            cols = 1
        out["columns"] = cols
    elif kind == "text":
        text = blk.get("text")
        if not isinstance(text, str) or not text.strip():
            warns.append(f"{w}：kind=text 需要非空 text —— 该块已忽略")
            return None
        text = clip(text, MAX_TEXT)
        if not _check_template(text, fields, warns, w + ".text"):
            return None
        out["text"] = text
    else:                                                   # list / table / kv
        src = _norm_source(blk.get("source"), fields, warns, w)
        if src is None:
            return None
        out["source"] = src
        rel = None
        if "field" in src and isinstance(sub_fields, dict):
            rel = sub_fields.get(root_field(src["field"]))
        if kind in ("list", "table"):
            item = _norm_item(blk.get("item"), kind, fields, warns, w + ".item", rel)
            if kind == "table" and item is None:
                if not any("kind=table" in x and w in x for x in warns):
                    warns.append(f"{w}：kind=table 需要 item.columns（表头）—— 该块已忽略")
                return None
            if item:
                out["item"] = item
        empty = _str_field(blk, "empty", warns, w, MAX_LABEL)
        if empty:
            out["empty"] = empty
        rows = blk.get("max_rows", MAX_ROWS_DEFAULT)
        if not isinstance(rows, int) or isinstance(rows, bool) or not (1 <= rows <= MAX_ROWS):
            warns.append(f"{w}：max_rows 需为 1..{MAX_ROWS} 的整数（实为 {rows!r}）"
                         f" —— 按 {MAX_ROWS_DEFAULT}")
            rows = MAX_ROWS_DEFAULT
        out["max_rows"] = rows
    return out


def _norm_section(sec, idx: int, fields, warns: list, where: str, sub_fields=None):
    w = f"{where}[{idx}]"
    if not isinstance(sec, dict):
        warns.append(f"{w}：分组需为对象 —— 该组已忽略")
        return None
    for k in sec:
        if k not in SECTION_KEYS:
            warns.append(f"{w}：未知键 {k!r}（白名单：{' / '.join(SECTION_KEYS)}）—— 已忽略")
    lab = _str_field(sec, "label", warns, w, MAX_LABEL)
    if not lab:
        warns.append(f"{w}：分组缺 label —— 该组已忽略")
        return None
    sid = sec.get("id")
    if sid is None:
        sid = f"s{idx}"
    elif not isinstance(sid, str) or not _ID_RE.match(sid):
        warns.append(f"{w}：分组 id={sid!r} 不合规 —— 按 s{idx}")
        sid = f"s{idx}"
    blocks = sec.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        warns.append(f"{w}：分组需要非空 blocks —— 该组已忽略")
        return None
    if len(blocks) > MAX_SECTION_BLOCKS:
        warns.append(f"{w}：blocks 超过 {MAX_SECTION_BLOCKS} 个 —— 只取前 {MAX_SECTION_BLOCKS}")
        blocks = blocks[:MAX_SECTION_BLOCKS]
    keep = []
    for i, b in enumerate(blocks, 1):
        nb = _norm_block(b, i, fields, warns, f"{w}.blocks")
        if nb is not None:
            keep.append(nb)
    if not keep:
        warns.append(f"{w}：分组里没有合法块 —— 该组已忽略")
        return None
    return {"id": sid, "label": lab, "icon": _icon_field(sec, "icon", warns, w),
            "collapsed": _bool_field(sec, "collapsed", warns, w, True),
            "when": _norm_cond(sec.get("when"), w, warns), "blocks": keep}


def _norm_derive(name: str, spec, warns: list, where: str, fields):
    w = f"{where}.{name}"
    if not isinstance(spec, dict):
        warns.append(f"{w}：派生需为对象 —— 已忽略")
        return None
    for k in spec:
        if k not in DERIVE_KEYS:
            warns.append(f"{w}：未知键 {k!r}（白名单：{' / '.join(DERIVE_KEYS)}）—— 已忽略")
    fn = spec.get("fn")
    if fn not in DERIVE_FNS:
        warns.append(f"{w}：派生函数 fn={fn!r} 不在白名单（{' / '.join(DERIVE_FNS)}）"
                     " —— 已忽略")
        return None
    args = spec.get("args", {})
    if not isinstance(args, dict):
        warns.append(f"{w}：args 需为对象 —— 按空参数处理")
        args = {}
    nargs = {}
    for k, v in args.items():
        if isinstance(v, dict) and len(v) == 1 and "field" in v:
            if _check_field_path(v["field"], fields, warns, w + f".args.{k}"):
                nargs[str(k)] = {"field": v["field"]}
        elif isinstance(v, dict) and len(v) == 1 and "derive" in v:
            if isinstance(v["derive"], str) and v["derive"].strip():
                nargs[str(k)] = {"derive": v["derive"].strip()}
            else:
                warns.append(f"{w}：args.{k}.derive 需为非空字符串 —— 已忽略")
        elif isinstance(v, (str, int, float, bool)) or v is None:
            nargs[str(k)] = v
        else:
            warns.append(f"{w}：args.{k} 只能是常量 / {{\"field\": …}} / {{\"derive\": …}}"
                         " —— 已忽略")
    label = _str_field(spec, "label", warns, w, MAX_LABEL)
    out = {"fn": fn, "args": nargs}
    if label:
        if _check_template(label, fields, warns, w + ".label"):
            out["label"] = label
    fmt = spec.get("format", "plain")
    if fmt not in FORMATS:
        warns.append(f"{w}：format={fmt!r} 不在白名单 —— 按 plain")
        fmt = "plain"
    out["format"] = fmt
    tone = spec.get("tone", "info")
    if tone not in TONES:
        warns.append(f"{w}：tone={tone!r} 不在白名单 —— 按 info")
        tone = "info"
    out["tone"] = tone
    out["when"] = _norm_cond(spec.get("when"), w, warns)
    return out


def _norm_slot(name: str, spec, warns: list, where: str, fields=None, sub_fields=None):
    w = f"{where}.{name}"
    allowed = SLOT_KEYS[name]
    if not isinstance(spec, dict):
        warns.append(f"{w}：槽位需为对象 —— 已忽略")
        return None
    for k in spec:
        if k not in allowed:
            warns.append(f"{w}：槽位 {name} 不允许键 {k!r}（允许：{' / '.join(allowed)}）"
                         " —— 已忽略")
    out = dict(SLOT_DEFAULTS.get(name) or {})
    req = {"list_editor": "field", "ref_picker": ("field", "domain"),
           "code_editor": "field", "preview_panel": "derive", "diff_view": None}[name]
    need = req if isinstance(req, tuple) else ((req,) if req else ())
    for k in need:
        v = spec.get(k)
        if not isinstance(v, str) or not v.strip():
            warns.append(f"{w}：槽位 {name} 缺必填 {k} —— 该槽位已忽略")
            return None
        out[k] = v.strip()
    if name == "list_editor":
        if not _check_field_path(out["field"], fields, warns, w + ".field"):
            return None
        itf = spec.get("item_fields")
        if not isinstance(itf, list) or not itf or not all(isinstance(x, str) for x in itf):
            warns.append(f"{w}：list_editor 需要非空 item_fields 字符串数组 —— 该槽位已忽略")
            return None
        if len(itf) > MAX_ITEM_FIELDS:
            warns.append(f"{w}：item_fields 超过 {MAX_ITEM_FIELDS} 项 —— 只取前 {MAX_ITEM_FIELDS}")
            itf = itf[:MAX_ITEM_FIELDS]
        rel = None
        if isinstance(sub_fields, dict):
            rel = sub_fields.get(root_field(out["field"]))
        keep = [p for p in itf if _check_field_path(p, rel, warns, w + ".item_fields")]
        if not keep:
            warns.append(f"{w}：list_editor 的 item_fields 全不合法 —— 该槽位已忽略")
            return None
        out["item_fields"] = keep
        for b in ("allow_add", "allow_del", "allow_reorder"):
            if b in spec:
                out[b] = _bool_field(spec, b, warns, w, out.get(b, False))
        for n in ("min", "max"):
            if n in spec:
                v = spec[n]
                if not isinstance(v, int) or isinstance(v, bool) or v < 0 or v > MAX_ROWS:
                    warns.append(f"{w}：{n} 需为 0..{MAX_ROWS} 的整数 —— 已忽略")
                else:
                    out[n] = v
    elif name == "ref_picker":
        if not _check_field_path(out["field"], fields, warns, w + ".field"):
            return None
        by = spec.get("by", "key")
        if by not in ("key", "name"):
            warns.append(f"{w}：by={by!r} 非法 —— 按 key")
            by = "key"
        out["by"] = by
        for b in ("multiple", "searchable"):
            if b in spec:
                out[b] = _bool_field(spec, b, warns, w, out.get(b, False))
    elif name == "code_editor":
        if not _check_field_path(out["field"], fields, warns, w + ".field"):
            return None
        lang = spec.get("language", "json")
        if lang not in ("json", "text"):
            warns.append(f"{w}：language={lang!r} 非法（json / text）—— 按 json")
            lang = "json"
        out["language"] = lang
        out["line_numbers"] = _bool_field(spec, "line_numbers", warns, w, True)
    elif name == "preview_panel":
        pos = spec.get("position", "right")
        if pos not in ("top", "right", "bottom"):
            warns.append(f"{w}：position={pos!r} 非法（top / right / bottom）—— 按 right")
            pos = "right"
        out["position"] = pos
        out["collapsible"] = _bool_field(spec, "collapsible", warns, w, True)
    else:                                                   # diff_view
        fld = spec.get("field")
        if fld is not None:
            if not _check_field_path(fld, fields, warns, w + ".field"):
                return None
            out["field"] = fld
        src = spec.get("source", "entry")
        if src not in ("entry", "derive"):
            warns.append(f"{w}：source={src!r} 非法（entry / derive）—— 按 entry")
            src = "entry"
        out["source"] = src
    return out


def _derive_cycles(derives: dict) -> list:
    """找出**循环引用**的派生名（纯静态：只读 `args` 里的 `{"derive": 名}` 边）。

    批 1 不执行派生，但循环引用是**声明本身的坏**（`a` 引用 `b`、`b` 引用 `a`）→ 忽略并告警。
    """
    edges = {}
    for name, spec in derives.items():
        if not isinstance(spec, dict):
            continue
        args = spec.get("args") if isinstance(spec.get("args"), dict) else {}
        edges[name] = [v["derive"] for v in args.values()
                       if isinstance(v, dict) and isinstance(v.get("derive"), str)]
    bad: list = []
    for start in edges:
        seen, stack = set(), [start]
        while stack:
            cur = stack.pop()
            for nxt in edges.get(cur, []):
                if nxt == start or nxt in seen:
                    if nxt == start:
                        bad.append(start)
                        stack = []
                        break
                    continue
                seen.add(nxt)
                stack.append(nxt)
    return sorted(set(bad))


# ═══════════════════════════════ 六、主入口 ═══════════════════════════════
def norm_decl(raw, dom: str, fields=None, label: str = "", sub_fields=None):
    """原始声明 → `(规范化声明 | None, [可读告警])`。

    `fields` = 该域 schema 的根字段名集合（R3 用）；`None` = 取不到 schema → **不做根字段校验**
    （由 `render.py` 记一条「未校验」告警，绝不因此整份丢掉）；`label` 只用于告警措辞。
    `sub_fields` = `{根数组字段: 元素属性名集合}` —— `ItemSpec` 里的路径是**相对单项**取值
    （契约 §1.3「路径根 = 单项的键」），拿不到就只判文法与深度（不猜）。
    """
    warns: list = []
    where = f"渲染声明 {dom}"
    if not isinstance(raw, dict):
        return None, [f"{where} 形状不对：顶层需为对象，实为 {type(raw).__name__}"
                      " —— 已回退第 2 层视图"]
    version = raw.get("$version", 1)
    if not isinstance(version, int) or isinstance(version, bool) or version != 1:
        return None, [f"{where}：$version={version!r} 不认识（只认 1）—— 已回退第 2 层视图"]
    for k in raw:
        if k not in TOP_KEYS:
            warns.append(f"{where}：未知键 {k!r}（白名单：{' / '.join(TOP_KEYS)}）—— 已忽略")
    extends = raw.get("$extends", "form")
    if extends not in EXTENDS:
        warns.append(f"{where}：$extends={extends!r} 非法（{' / '.join(EXTENDS)}）—— 按 form 处理")
        extends = "form"
    allow_code = raw.get("$allow_code", False)
    if not isinstance(allow_code, bool):
        warns.append(f"{where}：$allow_code 需为 true/false —— 按 false 处理")
        allow_code = False
    out = {"version": 1, "extends": extends, "allow_code": allow_code,
           "title": _str_field(raw, "title", warns, where, MAX_TITLE),
           "icon": _icon_field(raw, "icon", warns, where),
           "when": _norm_cond(raw.get("when"), where, warns),
           "layout": [], "sections": [], "fields": {}, "slots": {}, "derives": {},
           "hooks": {}, "readonly": [],
           "notes": _str_field(raw, "$notes", warns, where, MAX_NOTES)}
    title = out.get("title")
    if title and not _check_template(title, fields, warns, where + ".title"):
        out["title"] = None

    layout = raw.get("layout")
    sections = raw.get("sections")
    if layout and sections:
        warns.append(f"{where}：layout 与 sections 同时给了 —— **layout 优先**，sections 已忽略")
        sections = None
    if layout is not None:
        if not isinstance(layout, list):
            warns.append(f"{where}：layout 需为数组 —— 已忽略")
        else:
            if len(layout) > MAX_LAYOUT:
                warns.append(f"{where}：layout 超过 {MAX_LAYOUT} 块（实为 {len(layout)}）"
                             f" —— 只取前 {MAX_LAYOUT} 块（truncated）")
                layout = layout[:MAX_LAYOUT]
            for i, blk in enumerate(layout, 1):
                nb = _norm_block(blk, i, fields, warns, f"{where}.layout", sub_fields)
                if nb is not None:
                    out["layout"].append(nb)
    if sections is not None:
        if not isinstance(sections, list):
            warns.append(f"{where}：sections 需为数组 —— 已忽略")
        else:
            if len(sections) > MAX_SECTIONS:
                warns.append(f"{where}：sections 超过 {MAX_SECTIONS} 组 —— 只取前 {MAX_SECTIONS}")
                sections = sections[:MAX_SECTIONS]
            for i, sec in enumerate(sections, 1):
                ns = _norm_section(sec, i, fields, warns, f"{where}.sections", sub_fields)
                if ns is not None:
                    out["sections"].append(ns)

    flds = raw.get("fields")
    if flds is not None:
        if not isinstance(flds, dict):
            warns.append(f"{where}：fields 需为对象 —— 已忽略")
        else:
            if len(flds) > MAX_FIELDS_OVERRIDE:
                warns.append(f"{where}：fields 超过 {MAX_FIELDS_OVERRIDE} 键"
                             f" —— 只取前 {MAX_FIELDS_OVERRIDE}")
                flds = dict(list(flds.items())[:MAX_FIELDS_OVERRIDE])
            for path, meta in flds.items():
                w = f"{where}.fields.{path}"
                if not _check_field_path(path, fields, warns, w):
                    continue
                ov = _norm_override(path, meta, fields, warns, w)
                if ov:
                    out["fields"][path] = ov

    slots = raw.get("slots")
    if slots is not None:
        if not isinstance(slots, dict):
            warns.append(f"{where}：slots 需为对象 —— 已忽略")
        else:
            if len(slots) > MAX_SLOTS:
                warns.append(f"{where}：slots 超过 {MAX_SLOTS} 键 —— 只取前 {MAX_SLOTS}")
                slots = dict(list(slots.items())[:MAX_SLOTS])
            for name, spec in slots.items():
                if name not in SLOT_KEYS:
                    warns.append(f"{where}：未知槽位 {name!r}（白名单："
                                 f"{' / '.join(SLOT_KEYS)}）—— 已忽略")
                    continue
                ns = _norm_slot(name, spec, warns, f"{where}.slots", fields, sub_fields)
                if ns:
                    out["slots"][name] = ns

    derives = raw.get("derives")
    if derives is not None:
        if not isinstance(derives, dict):
            warns.append(f"{where}：derives 需为对象 —— 已忽略")
        else:
            if len(derives) > MAX_DERIVES:
                warns.append(f"{where}：derives 超过 {MAX_DERIVES} 键 —— 只取前 {MAX_DERIVES}")
                derives = dict(list(derives.items())[:MAX_DERIVES])
            for name, spec in derives.items():
                if not isinstance(name, str) or not name.strip():
                    warns.append(f"{where}：派生名需为非空字符串（实为 {name!r}）—— 已忽略")
                    continue
                nd = _norm_derive(name.strip(), spec, warns, f"{where}.derives", fields)
                if nd:
                    out["derives"][name.strip()] = nd
            for cyc in _derive_cycles(out["derives"]):
                warns.append(f"{where}：派生 {cyc!r} 存在**循环引用**（args 里的 derive 成环）"
                             " —— 该派生已忽略")
                out["derives"].pop(cyc, None)

    hooks = raw.get("hooks")
    if hooks is not None:
        if not isinstance(hooks, dict):
            warns.append(f"{where}：hooks 需为对象 —— 已忽略")
        else:
            if len(hooks) > MAX_HOOKS:
                warns.append(f"{where}：hooks 超过 {MAX_HOOKS} 键 —— 只取前 {MAX_HOOKS}")
                hooks = dict(list(hooks.items())[:MAX_HOOKS])
            for k, v in hooks.items():
                if k not in HOOKS or v != k:
                    warns.append(f"{where}：未知校验钩子 {k!r}（白名单只许点名："
                                 f"{' / '.join(HOOKS)}）—— 已忽略")
                    continue
                out["hooks"][k] = k

    ro = raw.get("readonly")
    if ro is not None:
        if not isinstance(ro, list) or not all(isinstance(x, str) for x in ro):
            warns.append(f"{where}：readonly 需为字符串数组 —— 已忽略")
        else:
            if len(ro) > MAX_READONLY:
                warns.append(f"{where}：readonly 超过 {MAX_READONLY} 项 —— 只取前 {MAX_READONLY}")
                ro = ro[:MAX_READONLY]
            for p in ro:
                if _check_field_path(p, fields, warns, f"{where}.readonly"):
                    out["readonly"].append(p)
    return out, warns


def decl_paths(decl) -> list:
    """该声明里**所有**字段路径（用于 `$extends:"form"` 补全「没提到的字段」）。"""
    out: list = []

    def add(p):
        if isinstance(p, str) and p and p not in out:
            out.append(p)

    def walk_block(b):
        for p in (b.get("fields") or []):
            add(p)
        for path, _zh in template_paths(b.get("label") or ""):
            add(path)
        for path, _zh in template_paths(b.get("text") or ""):
            add(path)
        if isinstance(b.get("when"), dict):
            add(b["when"].get("path"))
        src = b.get("source") or {}
        if src.get("field"):
            add(src["field"])
        item = b.get("item") or {}
        for p in (item.get("fields") or []) + (item.get("columns") or []):
            add(p)
        for path, _zh in template_paths(item.get("title") or ""):
            add(path)
        for path, _zh in template_paths(item.get("subtitle") or ""):
            add(path)
        for bd in (item.get("badges") or []):
            for path, _zh in template_paths(bd.get("text") or ""):
                add(path)

    for blk in (decl.get("layout") or []):
        walk_block(blk)
    for sec in (decl.get("sections") or []):
        for blk in (sec.get("blocks") or []):
            walk_block(blk)
    for p in decl.get("fields") or {}:
        add(p)
    for p in decl.get("readonly") or []:
        add(p)
    for path, _zh in template_paths(decl.get("title") or ""):
        add(path)
    for name, spec in (decl.get("derives") or {}).items():
        for v in (spec.get("args") or {}).values():
            if isinstance(v, dict) and v.get("field"):
                add(v["field"])
    return out
