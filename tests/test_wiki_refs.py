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
  的文件（如 `class_mech_proc.py`、`battle2_rules.py`、`game/content_rules/apply.py`）；
  那些不在框架仓，属预期。带路径的引用按**尾部路径**解析，不退化到 basename
  （否则 `game/content_rules/apply.py` 会被糊到框架仓的示例包 → 误报越界）。
- 纯行号无符号线索的引用跳过（无法判定，不猜）。
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOL = os.path.join(ROOT, "tools", "check_wiki_refs.py")


def main() -> int:
    if not os.path.exists(TOOL):
        print(f"❌ 找不到工具：{TOOL}")
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


if __name__ == "__main__":
    sys.exit(main())
