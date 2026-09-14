# -*- coding: utf-8 -*-
"""引擎文档 wiki（编辑器内可访问的网页版）。

为什么在编辑器里再放一次 wiki
------------------------------
`docs/engine-wiki/` 是 markdown —— 在编辑器里配字段的人（正在写 `cap` / `passive.proc` 的人）
不会去翻 repo。所以编辑器里给一个 **📖 文档** 页：

  · 左导航（按 getting-started / concepts / guides / reference / architecture 分组）
  · 正文渲染（标题 / 表格 / 代码块 / 列表 / 引用 —— 零第三方依赖，自己渲染）
  · **代码直链**：正文里的 `effects.py:270` 可点 → 弹出该文件的真实源码片段（带行号）
  · **字段深链**：字段词典的 `wiki:` 链接按 `#find=<词>` 跳到正文里那处并高亮
  · 搜索：跨页找词（配字段时最常用的动作）

实现约束（与编辑器一致）：**零第三方依赖**，只用 stdlib 渲染 markdown。
mermaid 图默认显示源码；若浏览器能联网取到 mermaid 渲染器，前端会把它画出来（渐进增强）。

包自带 wiki（**包优先、框架兜底**）
----------------------------------
游戏包可以在自己目录里放 `<pkg>/docs/wiki/**.md`（相对路径沿用框架那套命名：`README.md` /
`getting-started/quickstart.md` / `reference/effect-rules.md` …）。四个接口都多一个
`pkg_dir=None`：

* 给了包 → **包内页 ∪ 框架页**；**同名页（相对路径相同）以包内那份为准**；包内没有的页
  回退框架页；两边都没有 = 照旧 `None`（**不抛、不 500**）。
* 不给包（`pkg_dir=None`）→ **与没有这个功能时逐字一致**（零回归是硬约束）。
* 包目录里没有 `docs/wiki/`（或缺了某一页）= 没声明 —— 走框架那份，逐项不变。

同一套纪律也用在 `code_ref`：包内源码（`<pkg>/**/*.py`）优先，框架源码兜底；都没有 →
照旧说「读不到」，**不猜**。

对外接口
--------
    tree(pkg_dir=None)                   -> [{path, title, group}]
    page(rel, pkg_dir=None)              -> {path, title, html, toc, prev, next} | None
    search(q, limit=60, pkg_dir=None)    -> [{path, title, line, text}]
    code_ref(ref, span=14, pkg_dir=None) -> {ok, file, line, lines, note}
    pkg_wiki_dir(pkg_dir)                -> `<pkg>/docs/wiki`（不给包 = ""）
    page_path(rel, pkg_dir=None)         -> 解析后的真实文件路径（两边都没有 = ""）
"""
from __future__ import annotations

import html
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(HERE)
WIKI_DIR = os.path.join(FW_ROOT, "docs", "engine-wiki")
# 包内 wiki 的相对路径（**目录**，与 `glossary.PKG_GLOSSARY_REL` 同一套纪律：真源在包）
PKG_WIKI_REL = ("docs", "wiki")

GROUPS = [
    ("", "首页"),
    ("getting-started", "上手"),
    ("concepts", "概念"),
    ("guides", "任务指南"),
    ("reference", "参考"),
    ("architecture", "架构"),
    ("contributing", "贡献"),
]

# 源码解析用的索引（basename → 相对路径），首次用时建
_src_index = None
_pkg_src_index: dict = {}                 # 包目录 → 源码索引（包内优先时用）


# ───────────────────────────────────────────────────────────────── 页面发现
def pkg_wiki_dir(pkg_dir) -> str:
    """`<pkg>/docs/wiki`（**不做存在性检查**；不给包 = "" —— 那就是没声明）。"""
    return os.path.join(str(pkg_dir), *PKG_WIKI_REL) if pkg_dir else ""


def _roots(pkg_dir=None) -> list:
    """页面根目录，**包优先 → 框架兜底**（不存在的根不进表）。不给包 = 只有框架那份。"""
    out = []
    if pkg_dir:
        d = pkg_wiki_dir(pkg_dir)
        if os.path.isdir(d):
            out.append(d)
    out.append(WIKI_DIR)
    return out


def _safe_page(root: str, rel) -> str:
    """root 下的页面绝对路径；越界（`../`）或文件不存在 → ""（路径逃逸防护）。"""
    p = os.path.normpath(os.path.join(root, *str(rel).split("/")))
    if not p.startswith(os.path.normpath(root)) or not os.path.isfile(p):
        return ""
    return p


def page_path(rel, pkg_dir=None) -> str:
    """解析一个相对页名 → 真实文件绝对路径（**包内优先 → 框架兜底**）；两边都没有 = ""。"""
    for root in _roots(pkg_dir):
        p = _safe_page(root, rel)
        if p:
            return p
    return ""


def _md_files(pkg_dir=None) -> list:
    """页清单 = 框架页 ∪ 包内页（**同名以包内那份为准**，不重复列出）。不给包 = 旧的框架清单。"""
    seen: dict = {}
    for root in _roots(pkg_dir):
        for r, _dirs, files in os.walk(root):
            for f in sorted(files):
                if f.endswith(".md"):
                    rel = os.path.relpath(os.path.join(r, f), root).replace("\\", "/")
                    seen.setdefault(rel, root)          # 先到先得 = 包优先（_roots 包在前）
    return sorted(seen)


def _title_of(rel: str, pkg_dir=None) -> str:
    for line in _read(rel, pkg_dir).splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return rel


def _read(rel: str, pkg_dir=None) -> str:
    p = page_path(rel, pkg_dir)
    if not p:
        return ""
    with open(p, encoding="utf-8") as f:
        return f.read()


def _group_of(rel: str) -> str:
    return rel.split("/")[0] if "/" in rel else ""


def tree(pkg_dir=None) -> list:
    """[{path, title, group, group_label}]（保持 GROUPS 顺序，组内按文件名）。

    给了包 = **包内页 ∪ 框架页**（同名包内胜）；不给包 = 旧行为逐字不变。
    """
    order = {g: i for i, (g, _l) in enumerate(GROUPS)}
    rows = [{"path": r, "title": _title_of(r, pkg_dir), "group": _group_of(r)}
            for r in _md_files(pkg_dir)]
    for r in rows:
        r["group_label"] = dict(GROUPS).get(r["group"], r["group"] or "其他")
    rows.sort(key=lambda r: (order.get(r["group"], 99), r["path"]))
    return rows


def _neighbours(rel: str, pkg_dir=None):
    rows = [r["path"] for r in tree(pkg_dir)]
    if rel not in rows:
        return None, None
    i = rows.index(rel)
    return (rows[i - 1] if i > 0 else None, rows[i + 1] if i + 1 < len(rows) else None)


# ─────────────────────────────────────────────────────── 行内 markdown → html
CODE_REF = re.compile(r"([A-Za-z_][\w./-]*\.(?:py|js|json|md)):(\d+(?:[-–]\d+)?)")


def _inline(text: str) -> str:
    """行内渲染：先切出代码 span（里面的内容不再做 md 解析），其余做转义+强调+链接。"""
    parts = re.split(r"(`[^`]+`)", text)
    out = []
    for part in parts:
        if part.startswith("`") and part.endswith("`") and len(part) > 1:
            inner = part[1:-1]
            out.append(_code_chip(html.escape(inner), inner))
        else:
            out.append(_plain_inline(part))
    return "".join(out)


def _code_chip(escaped: str, raw: str) -> str:
    m = CODE_REF.fullmatch(raw.strip())
    if m and not m.group(1).endswith(".md"):
        return (f'<code class="ref-code" data-ref="{html.escape(raw.strip())}" '
                f'title="点击查看源码">{escaped}</code>')
    return f"<code>{escaped}</code>"


def _plain_inline(text: str) -> str:
    t = html.escape(text)
    # 标题锚点里的 `code` 在 _inline 已处理；这里只处理强调与链接
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", t)

    def link(m):
        label, url = m.group(1), m.group(2)
        if re.match(r"^https?://", url):
            return f'<a href="{url}" target="_blank" rel="noreferrer">{label}</a>'
        if url.startswith("#"):
            return f'<a href="{url}">{label}</a>'
        if re.match(r"^[\w./-]+\.md(#.*)?$", url) or url.startswith("../"):
            return f'<a href="#/wiki/{url}" class="wiki-link">{label}</a>'
        return f'<a href="{html.escape(url)}" class="wiki-link">{label}</a>'

    t = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, t)
    # 裸的 file.py:123（不在 code span 里的）也做成可点
    t = CODE_REF.sub(lambda m: (f'<code class="ref-code" data-ref="{m.group(0)}" '
                                f'title="点击查看源码">{m.group(0)}</code>'
                                if not m.group(1).endswith(".md") else m.group(0)), t)
    return t


# ──────────────────────────────────────────────────────────── 块级 markdown
def slug(text: str) -> str:
    s = re.sub(r"`([^`]*)`", r"\1", text)
    s = re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", s.strip()).strip("-").lower()
    return s or "sec"


def render_md(text: str, cur_page: str = "") -> tuple:
    """markdown → (html, toc)。支持：标题/表格/代码块/列表/引用/分隔线/段落。"""
    lines = text.splitlines()
    out, toc = [], []
    i, n = 0, len(lines)

    def _resolve_link_url(url: str) -> str:
        """相对 .md 链接按当前页目录解析（页内导航用 #/wiki/<path>）。"""
        if re.match(r"^[\w./-]+\.md(#.*)?$", url) or url.startswith("../"):
            base = os.path.dirname(cur_page)
            frag = ""
            if "#" in url:
                url, _, frag = url.partition("#")
                frag = "#" + frag
            rel = os.path.normpath(os.path.join(base, url)).replace("\\", "/")
            return f"#/wiki/{rel}{frag}"
        return url

    while i < n:
        line = lines[i]
        # fenced code
        if line.startswith("```"):
            lang = line[3:].strip()
            i += 1
            buf = []
            while i < n and not lines[i].startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            code = "\n".join(buf)
            if lang == "mermaid":
                out.append(f'<div class="mermaid" data-src="{html.escape(code)}"></div>'
                           f'<details class="mermaid-src-wrap"><summary>mermaid 图源码</summary>'
                           f'<pre class="code mermaid-src"><code>{html.escape(code)}</code></pre></details>')
            else:
                out.append(f'<pre class="code" data-lang="{html.escape(lang)}">'
                           f'<code>{html.escape(code)}</code></pre>')
            continue
        # heading
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            lvl = len(m.group(1))
            raw = m.group(2).strip()
            sid = slug(raw)
            toc.append({"level": lvl, "text": re.sub(r"`", "", raw), "id": sid})
            out.append(f'<h{lvl} id="{sid}">{_inline(raw)}</h{lvl}>')
            i += 1
            continue
        # hr
        if re.match(r"^(-{3,}|\*{3,})$", line.strip()):
            out.append("<hr>")
            i += 1
            continue
        # table
        if line.lstrip().startswith("|") and i + 1 < n and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            head = _cells(line)
            i += 2
            rows = []
            while i < n and lines[i].lstrip().startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            th = "".join(f"<th>{_inline(c)}</th>" for c in head)
            body = "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in rows)
            out.append(f'<div class="md-table-wrap"><table class="md-table"><thead><tr>{th}</tr></thead>'
                       f'<tbody>{body}</tbody></table></div>')
            continue
        # blockquote
        if line.lstrip().startswith(">"):
            buf = []
            while i < n and lines[i].lstrip().startswith(">"):
                buf.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            out.append("<blockquote>" + render_md("\n".join(buf), cur_page)[0] + "</blockquote>")
            continue
        # list（- / * / 数字，缩进两级）
        if re.match(r"^\s*([-*]|\d+\.)\s+", line):
            buf, base = [], None
            while i < n and (re.match(r"^\s*([-*]|\d+\.)\s+", lines[i]) or not lines[i].strip()):
                if not lines[i].strip():
                    i += 1
                    continue
                indent = len(lines[i]) - len(lines[i].lstrip())
                if base is None:
                    base = indent
                buf.append((indent, lines[i].strip()))
                i += 1
            out.append(_render_list(buf, base, cur_page))
            continue
        if not line.strip():
            i += 1
            continue
        # paragraph（连续非空行合并）
        buf = [line]
        i += 1
        while i < n and lines[i].strip() and not re.match(r"^(#{1,6}\s|```|\s*[-*]\s|\s*\d+\.\s|\||>)", lines[i]):
            buf.append(lines[i])
            i += 1
        out.append("<p>" + _inline(" ".join(x.strip() for x in buf)) + "</p>")

    htmlout = "\n".join(out)
    # 把链接的 .md 相对路径改写成页内路由（_plain_inline 里只做了粗判）
    htmlout = re.sub(r'href="#/wiki/([\w./-]+\.md)(#[^"]*)?"',
                     lambda m: 'href="%s"' % _resolve_link_url(m.group(1) + (m.group(2) or "")),
                     htmlout)
    return htmlout, toc


def _cells(line: str) -> list:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _render_list(items: list, base: int, cur_page: str) -> str:
    out, stack = [], []          # stack: ['ul'|'ol']
    for indent, raw in items:
        m = re.match(r"^([-*]|\d+\.)\s+(.*)$", raw)
        if not m:
            continue
        ordered = m.group(1).endswith(".")
        tag = "ol" if ordered else "ul"
        level = 0 if indent <= base else 1
        while len(stack) > level + 1:
            out.append(f"</{stack.pop()}>")
        while len(stack) < level + 1:
            stack.append(tag)
            out.append(f"<{tag} class='md-list'>")
        if stack[-1] != tag:
            out.append(f"</{stack.pop()}>")
            stack.append(tag)
            out.append(f"<{tag} class='md-list'>")
        out.append(f"<li>{_inline(m.group(2))}</li>")
    while stack:
        out.append(f"</{stack.pop()}>")
    return "".join(out)


# ───────────────────────────────────────────────────────────────────── 对外
def page(rel: str, pkg_dir=None):
    """渲染一页。给了包 → **包内同名页优先**，没有则回退框架页；两边都没有 = None。"""
    text = _read(rel, pkg_dir)
    if not text:
        return None
    body, toc = render_md(text, rel)
    prev, nxt = _neighbours(rel, pkg_dir)
    return {"path": rel, "title": _title_of(rel, pkg_dir), "html": body, "toc": toc,
            "group_label": dict(GROUPS).get(_group_of(rel), ""),
            "prev": prev, "prev_title": _title_of(prev, pkg_dir) if prev else "",
            "next": nxt, "next_title": _title_of(nxt, pkg_dir) if nxt else ""}


def search(q: str, limit: int = 60, pkg_dir=None) -> list:
    """跨页搜词。给了包 → 搜**包内页 ∪ 框架页**（同名页只搜包内那份）。"""
    q = (q or "").strip()
    if len(q) < 2:
        return []
    ql = q.lower()
    hits = []
    for rel in _md_files(pkg_dir):
        title = _title_of(rel, pkg_dir)
        for i, line in enumerate(_read(rel, pkg_dir).splitlines(), 1):
            if ql in line.lower():
                hits.append({"path": rel, "title": title, "line": i,
                             "text": line.strip()[:220]})
                if len(hits) >= limit:
                    return hits
    return hits


def _index_sources(root: str) -> dict:
    """一个根目录下源码 basename → 相对路径列表。"""
    idx: dict = {}
    skip = {".git", "__pycache__", ".venv", "node_modules"}
    for r, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip]
        for f in files:
            if f.endswith((".py", ".js", ".json")):
                rel = os.path.relpath(os.path.join(r, f), root).replace("\\", "/")
                idx.setdefault(f, []).append(rel)
    return idx


def _src_files() -> dict:
    """仓库内源码 basename → 相对路径（框架仓 + 示例/游戏包）。"""
    global _src_index
    if _src_index is not None:
        return _src_index
    _src_index = _index_sources(FW_ROOT)
    return _src_index


def _pkg_src_files(pkg_dir) -> dict:
    """包内源码索引（按包目录缓存）。包目录不能读 → 空表（= 走框架兜底，不抛）。"""
    key = os.path.normpath(os.path.abspath(str(pkg_dir)))
    if key not in _pkg_src_index:
        try:
            _pkg_src_index[key] = _index_sources(key)
        except OSError:
            _pkg_src_index[key] = {}
    return _pkg_src_index[key]


def code_ref(ref: str, span: int = 14, pkg_dir=None):
    """`effects.py:270` → 该文件的真实源码片段（带行号，标出目标行）。

    给了包 → **包内源码优先**（`<pkg>/**/effects.py`），框架源码兜底；
    找不到（例如指向**游戏仓**的文件）→ ok=False + 说明，**不猜**。
    """
    m = CODE_REF.fullmatch((ref or "").strip())
    if not m:
        return {"ok": False, "reason": f"不是可解析的引用：{ref}"}
    fname, rng = m.group(1), m.group(2)
    first = int(re.split(r"[-–]", rng)[0])
    root, cands = FW_ROOT, _src_files().get(os.path.basename(fname), [])
    if pkg_dir:
        pc = _pkg_src_files(pkg_dir).get(os.path.basename(fname), [])
        if pc:                                     # 包内命中 → 用包里的那份（框架不再参与）
            root, cands = os.path.normpath(os.path.abspath(str(pkg_dir))), pc
    if not cands:
        return {"ok": False, "reason": f"本仓没有 {fname}——多是**游戏仓（使用本框架的那个游戏）**侧的文件；"
                                       "本 wiki 允许引用它，但编辑器只读得到本仓源码",
                "crossrepo": True}
    # 带路径的引用优先按尾部路径匹配，避免同名文件糊到别处
    pick = None
    if "/" in fname:
        tail = fname.lstrip("./")
        for c in cands:
            if c.endswith(tail):
                pick = c
                break
    if pick is None:
        pick = sorted(cands, key=lambda p: (0 if p.startswith("saintess_engine/") else 1, len(p)))[0]
    path = os.path.join(root, *pick.split("/"))
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError as e:                                  # noqa: BLE001
        return {"ok": False, "reason": f"读取失败：{e}"}
    lo = max(1, first - span)
    hi = min(len(lines), first + span)
    out = {"ok": True, "file": pick, "line": first, "lo": lo, "hi": hi,
           "total": len(lines), "candidates": cands,
           "lines": [{"n": i, "t": lines[i - 1], "hit": i == first} for i in range(lo, hi + 1)]}
    if root != FW_ROOT:                        # 明确标注「这段来自游戏包」；不给包时不出现该键
        out["root"] = "package"
    return out
