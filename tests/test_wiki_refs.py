#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""wiki 行号引用门禁：文档里的 `file.py:NNN` 必须仍指向它声称的符号。

跑法：python tests/test_wiki_refs.py
退出码：0 = 零 drift；1 = 有 drift（打印清单）。

为什么需要它
------------
`docs/engine-wiki/` 用 `file.py:行号` 指位（792 处）。引擎一改，行号整体漂移，
文档就把读者带到错误的行。本门禁把 `tools/check_wiki_refs.py` 的判定接进回归，
让「改了引擎却忘了校准文档」当场变红。

判据（2026-09-11 三轮修正 + 分层，均有实测依据）
--------------------------------------------------
1. 行号落在**符号区间**内即通过 —— wiki 大量引用的是**函数体内的触发点/分支**
   （如 `battle.py:517` 点的 `_fire("battle_start")`），不是 def 行。
   首版按「必须等于 def 行」判定，抽检 3/3 全假阳性（181 处误报）。
2. 一行提到多个符号时，**任一**候选符号区间命中即通过 —— 如
   「26 个事件名（`EVENTS`）+ `fire()`」，行号指的是 `EVENTS`。
   只认「最近的符号」时误报剩 57 处，改为任一命中后降到 41 处。
3. **词部件重叠**：行号处那行确实在讲该符号即通过 —— 如文档行提
   `_aoe_falloff_apply`，行号却指 `info.get("aoe_falloff")` 那行（共享 `falloff`）。
   加此判据后 41 → 19 处。
4. **分层**（定案）：
   - **确定性 drift** = 行号越界或落在空行 → **阻断**（零假阳性，这是行号失效的硬症状）
   - **语义存疑** = 行号有效但检查器无法自动判定语义（模块 docstring / 注释块 /
     函数体内点位）→ **只报告**，列出供人工抽查
   - 为什么分层：后一类检查器本质上无从判定（如 `effect_triggers.py:5-11` 引用的是
     模块 docstring「原文」），一律阻断会造成十几处噪声 → 门禁被无视（狼来了）。
     「整体位移」（函数上移 N 行）由 `tools/remap_wiki_refs.py`（内容锚定位移）负责抓。

已知边界（有意不阻断）
----------------------
- **未解析文件**（basename 不在本仓）只报告不失败：wiki 会引用**游戏侧参考实现**
  的文件（如 `class_mech_proc.py`、`battle_rules.py`、`game/content_rules/apply.py`）；
  那些不在框架仓，属预期。带路径的引用按**尾部路径**解析，不退化到 basename
  （否则 `game/content_rules/apply.py` 会被糊到框架仓的示例包 → 误报越界）。
- 纯行号无符号线索的引用跳过（无法判定，不猜）。**但**带「本小节标题写了文件名」
  （`### `effects.py``）+ 表格行里有符号名 的引用**不跳**：2026-09-25 起补了第二档，
  用标题补上下文后照 `file.py:NNN` 同判（硬失效=空行/越界 → 阻断）。补这一档前
  实测 67 行里 17 行早已指向空行，而门禁一直绿（真盲区）。
"""
import io
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOL = os.path.join(ROOT, "tools", "check_wiki_refs.py")


def main() -> int:
    if not os.path.exists(TOOL):
        print(f"❌ 找不到工具：{TOOL}")

    # ★ `--check` 只读开关（审计 L216）：先跑这条 —— 它守的是本门禁自己的读出口径，
    #   若这层红，后面那份 drift 报告的真假已经无意义。
    bad = check_readonly_switch()
    if bad:
        print("\n❌ `--check` 只读开关判据未通过（%d 条）" % bad)
        return 1
        return 1

    pr = subprocess.run([sys.executable, TOOL], capture_output=True, text=True,
                        encoding="utf-8", errors="replace",
                        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    out = (pr.stdout or "") + (pr.stderr or "")

    # 首行是汇总：wiki 行号引用自检：可判定 N 处 → drift M 处；未解析文件 K 处
    head = out.strip().splitlines()[0] if out.strip() else "(无输出)"
    print(f"=== wiki 行号引用门禁 ===\n{head}")

    if pr.returncode == 0:
        print("\n✅ 零 drift（文档行号与代码一致）")
        return 0

    print("\n❌ 有 drift —— 文档行号已与代码脱节，请校准后重跑：")
    print(out.strip()[-6000:])
    print("\n修法：按工具给出的「符号区间」修正文档行号；")
    print("      改了引擎文件整体位移时可用 tools/remap_wiki_refs.py（内容锚定位移）。")
    return 1




def _bare_row_inject(wpath):
    """把「小节标题带文件名」那一节里第一处纯行号引用改成越界值。

    没有硬失效（空行/越界）就没有改写建议 ⇒ 那样判据会恒绿，所以必须先造一个。
    标题行本身**不含**纯行号（文件名写在标题、`:NNN` 写在下面的表格行）⇒
    这里要跨行扫，不能只看标题那一行 —— 首版就栽在这（永远找不到样本 ⇒ 判据静默跳过）。
    返回 (原文, 注入后)；找不到返回 (None, None)。"""
    import re
    orig = io.open(wpath, encoding="utf-8", newline="").read()
    lines = orig.split(chr(10))
    in_sec = False
    for i, ln in enumerate(lines):
        if re.match("^###", ln.strip()):
            in_sec = True
            continue
        if not in_sec or "|" not in ln:
            continue
        m = re.search(r'`:(\d+)`', ln)
        if m:
            lines[i] = ln.replace("`:%s`" % m.group(1),
                                      "`:99999`", 1)
            return orig, chr(10).join(lines)
    return None, None


def _run_tool(args):
    return subprocess.run([sys.executable, TOOL] + list(args), capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          env={**os.environ, "PYTHONIOENCODING": "utf-8",
                               "PYTHONUTF8": "1"})


def _find_writable_sample():
    """找一个「注入越界后工具真会给出改写建议」的 wiki 样本。

    ★ 为什么不能取「第一个匹配行」：不是每个小节标题的符号都能在本仓解析到，
      解析不到就没有建议可改 ⇒ 工具**正确地不写**（实测 `docs/engine-wiki/_selfcheck.md`
      的 `bar_should_trigger` 那一节注入后 rc=0、「已改写」为无、文件逐字节未变）。
      拿那种样本当判据 = 把「工具什么都没做」当成「功能被误伤」⇒ **假红**。
    逐个试，返回 (路径, 原文, 注入后)；全仓都没有可写样本 ⇒ 返回 None。
    每个候选都先备份、试完立刻还原。
    """
    import importlib.util, os, re
    pat = re.compile(r'`:(\d+)`')
    py = sys.executable
    for dirpath, _d, files in os.walk(os.path.join(ROOT, "docs", "engine-wiki")):
        for f in sorted(files):
            if not f.endswith(".md"):
                continue
            p = os.path.join(dirpath, f)
            orig = io.open(p, encoding="utf-8", newline="").read()
            lines = orig.split(chr(10))
            sec = False
            for i, ln in enumerate(lines):
                if re.match("^###", ln.strip()):
                    sec = True
                    continue
                if not sec or "|" not in ln:
                    continue
                m = pat.search(ln)
                if not m:
                    continue
                lines[i] = ln.replace("`:%s`" % m.group(1),
                                          "`:99999`", 1)
                inj = chr(10).join(lines)
                try:
                    io.open(p, "w", encoding="utf-8", newline="").write(inj)
                    r = subprocess.run([py, TOOL, "--fix-bare"], capture_output=True,
                                       text=True, encoding="utf-8", errors="replace",
                                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
                    if io.open(p, encoding="utf-8", newline="").read() != inj:
                        return (p, orig, inj)
                finally:
                    io.open(p, "w", encoding="utf-8", newline="").write(orig)
    return None
def check_readonly_switch() -> int:
    """`--check` 是全局只读开关（审计 L216）。返回失败条数。

    钉的是**性质**而非源码形态，三条：
      ① `--check` + 任一改写开关 ⇒ 磁盘零变化；
      ② 建议照旧打印（只读 ≠ 不诊断）；
      ③ 不带 `--check` 时改写能力**必须仍在**（不许把只读做成什么都不做）。
    在真 wiki 上跑 ⇒ 每次先备份原字节、finally 必还原，并断言还原后逐字节相同。
    """
    import re
    fails = []
    wiki = os.path.join(ROOT, "docs", "engine-wiki")
    probe = _find_writable_sample()
    if probe is None:
        print("  （未找到可注入的纯行号档表格行 ⇒ 样本为空，跳过；判据不许空转恒绿）")
        return 0
    p, orig, injected = probe
    try:
        io.open(p, "w", encoding="utf-8", newline="").write(injected)
        r1 = _run_tool(["--check", "--fix-bare"])
        if io.open(p, encoding="utf-8", newline="").read() != injected:
            fails.append("`--check --fix-bare` 仍然写了文件（只读开关失效）")
        if not re.search("只读检查", r1.stdout):
            fails.append("`--check` 运行时未说明「本次为只读检查」")
        if "drift" not in (r1.stdout or ""):
            fails.append("`--check` 下报告没有 drift 汇总（诊断被一并关掉）")

        io.open(p, "w", encoding="utf-8", newline="").write(injected)
        r2 = _run_tool(["--check", "--fix-bare-all"])
        if io.open(p, encoding="utf-8", newline="").read() != injected:
            fails.append("`--check --fix-bare-all` 仍然写了文件")

        io.open(p, "w", encoding="utf-8", newline="").write(injected)
        r3 = _run_tool(["--fix-bare"])
        if io.open(p, encoding="utf-8", newline="").read() == injected:
            fails.append("不带 --check 时 --fix-bare 不再改写（功能被误伤）")
        if not re.search("已改写", r3.stdout):
            fails.append("不带 --check 时报告里没有「已改写」提示")
    finally:
        io.open(p, "w", encoding="utf-8", newline="").write(orig)
        if io.open(p, encoding="utf-8", newline="").read() != orig:
            fails.append("探针跑完没能把 %s 还原成原文" % os.path.relpath(p, ROOT))
    for f in fails:
        print("  ❌ " + f)
    return len(fails)

if __name__ == "__main__":
    sys.exit(main())
