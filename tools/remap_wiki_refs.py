# -*- coding: utf-8 -*-
"""wiki 行号引用的**内容锚定位移**：`file.py:NNN` 按「旧行文本」重新定位。

为什么不用 difflib 行映射（本工具 v1）：代码里重复行极多（`}`、`try:`、`def `、
文档字符串行），SequenceMatcher 会给出**错位 equal 块** → 实测把 `def alive_sides`
映到 `def sides_of`（v1 的 20 处错改即此因）。

本版做法（确定性、可逐条验证）：
  1. 取 `--rev`（默认 HEAD）版本源文件 A，与工作区版本 B；
  2. 对每条引用 `file.py:NNN`：old_text = A[NNN]（去首尾空白）；
  3. 在 B 里找与 old_text **精确相等**的行号集合；
  4. 取离 NNN 最近的那个（窗口 `--window`，默认 120 行）→ 新行号；
     - 精确唯一命中 → 直接改；
     - 同窗口内多命中 → 记为 ambiguous（不改，列清单人工核）；
     - 无命中（该行在本次改动中被删/改写）→ 记为 unresolved（不改，列清单）。
  改写前后**行文本逐字相同** → 每条位移都可自证。

用法：
    python tools/remap_wiki_refs.py --check --files=framework/battle2/actions.py,...
    python tools/remap_wiki_refs.py --files=... [--rev=HEAD] [--window=120]
    python tools/remap_wiki_refs.py --files=... --exclude=reference/xxx.md
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WIKI = os.path.join(ROOT, "docs", "engine-wiki")
REF_RE = re.compile(r"([\w/]+\.py):(\d+)(?:-(\d+))?")


def _git_show(rev: str, rel: str):
    r = subprocess.run(["git", "-C", ROOT, "show", f"{rev}:{rel}"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout.splitlines() if r.returncode == 0 else None


def _prepare(rev: str, rel: str, window: int):
    """→ (old_lines, text→[新行号], 说明)"""
    old = _git_show(rev, rel)
    if old is None:
        return None, None, "git 取不到旧版本"
    new = open(os.path.join(ROOT, rel), encoding="utf-8", errors="replace").read().splitlines()
    index = {}
    for i, l in enumerate(new, 1):
        index.setdefault(l.strip(), []).append(i)
    return old, index, f"旧 {len(old)} 行 / 新 {len(new)} 行 / 行文本索引 {len(index)} 种"


def _locate(old_lines, index, n: int, window: int):
    """旧行号 n → (新行号 | None, 状态)。状态：same / moved / ambiguous / unresolved

    窗口逐级收窄（window → /3 → /6）：间距小于本次改动规模的同文本行才是同名锚点；
    仍多命中 → ambiguous（宁可不改，交人工核）。
    """
    try:
        txt = old_lines[n - 1].strip()
    except IndexError:
        return None, "unresolved"
    if not txt:
        return None, "unresolved"   # 空行/纯缩进行：无法锚定
    cands = index.get(txt) or []
    if not cands:
        return None, "unresolved"
    for w in (window, max(1, window // 3), max(1, window // 6)):
        near = [c for c in cands if abs(c - n) <= w]
        if len(near) == 1:
            c = near[0]
            return (c, "same") if c == n else (c, "moved")
    if any(abs(c - n) <= window for c in cands):
        return None, "ambiguous"
    return None, "unresolved"


def main() -> int:
    args = sys.argv[1:]
    check = "--check" in args
    rev, window = "HEAD", 120
    files, skip_docs = [], set()
    for a in args:
        if a.startswith("--rev="):
            rev = a.split("=", 1)[1]
        elif a.startswith("--window="):
            window = int(a.split("=", 1)[1])
        elif a.startswith("--files="):
            files = [x for x in a.split("=", 1)[1].split(",") if x]
        elif a.startswith("--exclude="):
            skip_docs = {x for x in a.split("=", 1)[1].split(",") if x}
    if not files:
        print(__doc__)
        return 2

    tables = {}
    for rel in files:
        old, index, note = _prepare(rev, rel, window)
        if old is None:
            print(f"跳过 {rel}：{note}")
            continue
        tables[os.path.basename(rel)] = (rel, old, index)
        print(f"{rel}：{note}")

    moved = same = 0
    ambiguous, unresolved = [], []
    touched = set()
    for root, _dirs, fs in os.walk(WIKI):
        for f in sorted(fs):
            if not f.endswith(".md"):
                continue
            wpath = os.path.join(root, f)
            wrel = os.path.relpath(wpath, WIKI).replace(os.sep, "/")
            if wrel in skip_docs:
                continue
            text = open(wpath, encoding="utf-8").read()

            def _sub(mm):
                nonlocal moved, same
                base_, n = mm.group(1), int(mm.group(2))
                end = int(mm.group(3)) if mm.group(3) else None
                hit = tables.get(os.path.basename(base_))
                if not hit:
                    return mm.group(0)
                _rel, old_lines, index = hit
                n2, st = _locate(old_lines, index, n, window)
                tag = f"{wrel}  {base_}:{n}" + (f"-{end}" if end else "")
                if st == "same":
                    same += 1
                    return mm.group(0)
                if st == "ambiguous":
                    ambiguous.append(tag); return mm.group(0)
                if st == "unresolved":
                    unresolved.append(tag); return mm.group(0)
                e2 = None
                if end is not None:
                    e2, st2 = _locate(old_lines, index, end, window)
                    if st2 not in ("same", "moved"):
                        ambiguous.append(tag + " (区间右端无法锚定)"); return mm.group(0)
                moved += 1
                touched.add(wpath)
                return f"{base_}:{n2}-{e2}" if end is not None else f"{base_}:{n2}"

            new_text = REF_RE.sub(_sub, text)
            if new_text != text and not check:
                open(wpath, "w", encoding="utf-8", newline="\n").write(new_text)

    print(f"\n{'待' if check else '已'}位移：{moved} 处；未动 {same} 处；"
          f"涉及文档 {len(touched)} 个")
    if ambiguous:
        print(f"\n-- ambiguous（窗口内同文本行多命中，未改，需人工核）{len(ambiguous)} 处 --")
        for t in ambiguous[:40]:
            print("  ", t)
    if unresolved:
        print(f"\n-- unresolved（该行在本次改动中被删/改写，未改）{len(unresolved)} 处 --")
        for t in unresolved[:40]:
            print("  ", t)
    return 0


if __name__ == "__main__":
    sys.exit(main())
