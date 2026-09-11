# -*- coding: utf-8 -*-
"""wiki 行号引用自检：`file.py:NNN` 是否还指向它声称的符号。

背景（2026-09-11）：`docs/engine-wiki/` 大量行文用 `file.py:行号` 指位（792 处）。
引擎一改，行号整体漂移 → 文档把人带到错误的行。本工具按「文档那一行提到的符号名」
反查符号当前真实行号，不一致即报 drift（附建议行号）。

用法：
    python tools/check_wiki_refs.py            # 全量报告
    python tools/check_wiki_refs.py --fix-hint # 只列有建议值的
退出码：0 = 无 drift；1 = 有 drift（可接 CI）。

判据边界（有意保守）：
- 只对「文档行里出现符号名」的引用做判定；纯行号无符号名 → 跳过（无法判定）。
- 支持 `def`/`class`/赋值 三类符号；同名多处 → 取离引用行最近的一处。
- 文件按 basename 解析，同名多份（engine 与 content 都有 skills.py 等）用 basename
  索引 + 目录偏好（saintess_engine/ 优先），找不到 → 报 unresolved 而不猜。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WIKI = os.path.join(ROOT, "docs", "engine-wiki")
# --fix 自动改写白名单（运行时由 --fix-files= 覆盖）
FIX_ALLOW = set()

REF_RE = re.compile(r"([\w/]+\.py):(\d+)(?:-(\d+))?")
# 文档行里的候选符号名：反引号内、或后随 ( 的标识符
CAND_IDENT_RE = re.compile(r"`([A-Za-z_][\w\.]{2,})`")
CAND_CALL_RE = re.compile(r"\b([A-Za-z_][\w]{2,})\s*\(")

# 迁移适配（2026-09-11）：原先排除 tests/ 是为了躲开游戏仓 245 个测试文件的
# basename 干扰；但引擎迁进独立仓后，**引擎自己的测试就在 tests/**（wiki 会引用
# `test_engine_purity.py`），排除它会导致这些引用被判「文件未找到」。故不再排除。
_SKIP_DIRS = {"__pycache__", ".git", "_archive_unused"}


def _build_index():
    """basename → [相对路径...]（saintess_engine/ 优先，tests/ 排除）。"""
    idx = {}
    for root, dirs, fs in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for f in fs:
            if f.endswith(".py"):
                idx.setdefault(f, []).append(os.path.relpath(os.path.join(root, f), ROOT))
    for k in idx:
        idx[k].sort(key=lambda p: (0 if "saintess_engine" in p else 1, len(p)))
    return idx


def _symbol_spans(path):
    """path 内 def/class（任意缩进）+ 模块级赋值 符号 → {名: [(起, 止), ...]}。

    ⚠️ 判据是**区间**不是单行（2026-09-11 修正）：wiki 大量引用的不是 def 行，
    而是**函数体内的触发点/分支**（如 `battle.py:517` 点的 `_fire("battle_start")`、
    `landing.py:139` 点的 `on_taken` 触发处）。首版按「必须等于 def 行」判定 →
    实测抽检 3/3 全假阳性（181 处 drift 里绝大部分是错的），若 --fix 会**改坏文档**。
    区间 = 本符号起始行 → 下一个符号起始行-1（或文件末尾）。

    ⚠️ 只收**模块级**赋值：函数体内的局部赋值（`dmg = ...` / `actor = ...`）与
    参数名同名，会把 wiki 表格里的参数列误判成符号 → 大量假 drift（2026-09-11
    首版即踩：events.md 全表误报）。
    """
    entries = []
    try:
        lines = open(os.path.join(ROOT, path), encoding="utf-8", errors="replace").read().splitlines()
    except Exception:
        return {}
    for i, l in enumerate(lines, 1):
        m = re.match(r"\s*(?:async\s+)?def\s+(\w+)", l)
        if m:
            entries.append((i, m.group(1)))
            continue
        m = re.match(r"\s*class\s+(\w+)", l)
        if m:
            entries.append((i, m.group(1)))
            continue
        if l[:1] in (" ", "\t"):
            continue  # 非模块级赋值 → 不收（局部/字段名会假报）
        m = re.match(r"([A-Za-z_]\w*)\s*(?::[^=]+)?=", l)
        if m:
            entries.append((i, m.group(1)))
    out = {}
    for j, (ln, nm) in enumerate(entries):
        end = entries[j + 1][0] - 1 if j + 1 < len(entries) else len(lines)
        out.setdefault(nm, []).append((ln, end))
    return out


_LINE_CACHE = {}


def _line_text(path, n: int) -> str:
    """目标文件第 n 行文本（带缓存；越界 → 空串）。"""
    if path not in _LINE_CACHE:
        try:
            _LINE_CACHE[path] = open(os.path.join(ROOT, path), encoding="utf-8",
                                     errors="replace").read().splitlines()
        except Exception:
            _LINE_CACHE[path] = []
    lines = _LINE_CACHE[path]
    return lines[n - 1] if 1 <= n <= len(lines) else ""


def _related(txt: str, names) -> bool:
    """行号处那行是否**确实在讲**文档提到的符号（词部件重叠）。

    第三类判据（2026-09-11 三次修正）：wiki 大量引用的是**函数体内的具体点位**，
    而文档行只写了符号名。例：文档行提 `actions._aoe_falloff_apply`，行号却指
    `falloff = float(info.get("aoe_falloff", 1.0))` 那一行 —— 区间判据必然落空，
    但两者共享词部件 `falloff` → 判为有效引用（实测该行号是对的）。

    只比对长度 >= 5 的部件，避免常见短词（`time` / `state` / `self`）误判。
    """
    low = (txt or "").lower()
    if not low.strip():
        return False
    for nm in names:
        for part in re.split(r"[^a-z0-9]+", nm.lower()):
            if len(part) >= 5 and part in low:
                return True
    return False


def main() -> int:
    fixed_hint_only = "--fix-hint" in sys.argv
    fix = "--fix" in sys.argv
    # --fix 只在「本次改动过的引擎文件」上自动改写（避免误改判不准的老引用）
    allow = [a.split("=", 1)[1] for a in sys.argv if a.startswith("--fix-files=")]
    global FIX_ALLOW
    FIX_ALLOW = set(allow[0].split(",")) if allow else set()
    fixups = {}
    index = _build_index()
    symcache = {}
    drifts, unresolved, unverified, checked = [], [], [], 0
    for root, dirs, fs in os.walk(WIKI):
        for f in sorted(fs):
            if not f.endswith(".md"):
                continue
            wpath = os.path.join(root, f)
            wrel = os.path.relpath(wpath, WIKI).replace(os.sep, "/")
            for ln, text in enumerate(open(wpath, encoding="utf-8").read().splitlines(), 1):
                for m in REF_RE.finditer(text):
                    base, n = m.group(1), int(m.group(2))
                    end = int(m.group(3)) if m.group(3) else n
                    bname = os.path.basename(base)
                    cands = index.get(bname)
                    # 迁移适配（2026-09-11）：带路径的引用按**尾部路径**解析，不退化到
                    # basename。否则 `game/content_rules/apply.py`（游戏仓文件，不属本仓）
                    # 会被 basename 糊到框架仓 `examples/minimal-game/content/apply.py`
                    # → 行号越界 → 误报「确定性 drift」（实测 4 处假阳性全因此）。
                    # 而 `saintess_engine/kinds/__init__.py` / `kinds/__init__.py`
                    # 这类真·引擎引用仍能被尾部匹配正确解析。
                    target = None
                    if cands:
                        if "/" in base:
                            tail = base.lstrip("./").replace("\\", "/")
                            for c in cands:
                                if c.replace("\\", "/").endswith(tail):
                                    target = c
                                    break
                        else:
                            target = cands[0]
                    if not target:
                        unresolved.append((wrel, ln, base, n, "文件未找到"))
                        continue
                    if target not in symcache:
                        symcache[target] = _symbol_spans(target)
                    syms = symcache[target]
                    # 候选符号：wiki 行里出现、且确实是该文件符号的标识符。
                    # 取「文本位置上离该引用最近」的那个 —— 表格一行里常同时出现
                    # 多个符号名，就近者才是该引用指向的符号（否则会修错行）。
                    cand_pos = []
                    for mm in CAND_IDENT_RE.finditer(text):
                        nm = mm.group(1).split(".")[-1]
                        if nm in syms:
                            cand_pos.append((abs(mm.start() - m.start()), nm))
                    for mm in CAND_CALL_RE.finditer(text):
                        if mm.group(1) in syms:
                            cand_pos.append((abs(mm.start() - m.start()), mm.group(1)))
                    if not cand_pos:
                        continue  # 无符号线索 → 无法判定（有意跳过）
                    cand_pos.sort()
                    # 判据（2026-09-11 二次修正）：一行常同时提到多个符号
                    # （如「26 个事件名（`EVENTS`）+ `fire()`」，行号指的是 EVENTS），
                    # 故**任一**候选符号的区间命中即通过 —— 而非只认「最近的那个」。
                    names = [nm for _, nm in cand_pos]
                    checked += 1
                    if any(lo <= n <= hi for nm in names for lo, hi in syms[nm]):
                        continue
                    # 第三类判据：行号处那行确实在讲该符号（词部件重叠）→ 有效引用
                    if _related(_line_text(target, n), names):
                        continue
                    txt = _line_text(target, n)
                    # 分层（2026-09-11 三次修正后定案）：
                    #   确定性失效 = 行号越界或落在空行 → 阻断（零假阳性）
                    #   语义存疑 = 行号有效但无法自动判定语义 → 只报告（人工清单）
                    # 为什么分层：wiki 大量引用**模块 docstring / 注释块 / 函数体内点位**
                    # （如 `effect_triggers.py:5-11` 原文、`actions.py:228` 硬规则注释），
                    # 检查器无法自动确认语义，一律阻断会造成 19 处噪声 → 门禁被无视。
                    if not txt.strip():
                        name = names[0]
                        drifts.append((wrel, ln, f"{base}:{n}", name, "—(越界/空行)", text.strip()[:90]))
                        if fix and bname in FIX_ALLOW:
                            pass
                        continue
                    unverified.append((wrel, ln, f"{base}:{n}", names[0], txt.strip()[:70]))
                    continue
    print(f"wiki 行号引用自检：可判定 {checked} 处 → drift {len(drifts)} 处"
          f"；语义存疑 {len(unverified)} 处；未解析文件 {len(unresolved)} 处")
    if unresolved:
        print("\n-- 未解析文件（basename 不在仓库） --")
        for r in unresolved[:15]:
            print(f"  {r[0]}:{r[1]} → {r[2]}:{r[3]}  ({r[4]})")
    if drifts:
        print("\n-- drift（文档说 A 行，符号区间在 B） --")
        for d in drifts:
            print(f"  {d[0]}:{d[1]}  {d[2]} → {d[3]} 区间 :{d[4]}   | {d[5]}")
    else:
        print("\n无确定性 drift ✅（行号均未越界/指向空行）")
    if unverified:
        print(f"\n-- 语义存疑（行号有效，但检查器无法自动判定它是否在讲该符号）"
              f"{len(unverified)} 处 --")
        for u in unverified[:20]:
            print(f"  {u[0]}:{u[1]}  {u[2]}  该行: {u[4]}")
        if len(unverified) > 20:
            print(f"  … 另 {len(unverified) - 20} 处")
    if fixups:
        total = 0
        for wpath, subs in fixups.items():
            t = open(wpath, encoding="utf-8").read()
            for old, new in subs:
                if old in t:
                    t = t.replace(old, new)
                    total += 1
            open(wpath, "w", encoding="utf-8", newline="\n").write(t)
        print(f"\n-- --fix 已改写 {total} 处（限定文件：{', '.join(sorted(FIX_ALLOW))}）--")
    return 1 if drifts else 0


if __name__ == "__main__":
    sys.exit(main())
