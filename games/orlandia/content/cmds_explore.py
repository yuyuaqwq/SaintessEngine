# -*- coding: utf-8 -*-
"""包内探索进度命令（`content/cmds_explore.py`）—— 『探索进度』的守卫/取参/业务/**渲染**。

终态形状（B18；真源 = `overnight/B18_TERMINAL_SHAPE.md` §1.2）：
* handler 签名 `fn(env) -> list[str]`，**直接返回已渲染行**（本命令全 f-string 字面量 → 随业务进包，
  宿主 `game/commands/exploration.py` 里已无任何渲染代码，`grep T.text|T.static` → 0）。
* 区域聚合 = 包内 `content/exploration.py`（`region_progress(visited)` / `overall_progress(visited)`，
  数据 = `content/data/exploration.json`）；到访状态 = 包内存档层
  `content/persistence/world.py::get_visited_subareas(qq_id)`（B17 已归包；宿主 `db.get_visited_subareas`
  就是它的同名转发）—— **包内直连，不经宿主**。
* 面板底部随机提示：取**宿主壳同款** `_tip("explore")`（`Env.state["shell"]` 透传的可选能力口，
  与 `cmds_tower._open_tower_battle` 同源）—— 保证提示池对象与随机流逐字同源；
  无宿主壳（编辑器试玩）→ 回退包内同源提示池 `content/item_templates.TIPS`。

行为逐字节不变（面板行序 / 分隔线宽度 / 百分比取整 / 隐藏点括号 = 改造前逐行）；证据 =
`overnight/W-B18-L6.md` 的 34 场景快照（sha256 改前 = 改后）。
"""
from __future__ import annotations

from . import exploration as _EX
from .commands import register
from .persistence.world import get_visited_subareas

SEP = "━━━━━━━━━━━━━━"


def _tip(env, cat: str) -> str:
    """面板底部提示 —— 宿主壳 `_tip` 优先（同池同随机流）；无壳 → 包内同源 TIPS 池。"""
    shell = (getattr(env, "state", None) or {}).get("shell")
    fn = getattr(shell, "_tip", None)
    if callable(fn):
        return fn(cat)
    from .item_templates import _rand_tip
    return _rand_tip(cat)


@register("explore_progress", guards=("hook:player",), params=("cmd=探索进度",))
def explore_progress(env) -> list:
    """v115 探索见闻：『探索进度』指令（区域探索度明细 + 全大陆汇总）。"""
    qq_id = env.uid
    visited = get_visited_subareas(qq_id)            # 到访表（键 = "地图:子区域"）
    regions = _EX.region_progress(visited)
    overall = _EX.overall_progress(visited)

    lines = [
        "🗺️ 探索进度",
        SEP,
    ]
    for r in regions:
        total = r["total"]
        visited_n = r["visited"]
        if total <= 0:
            continue
        pct = int(round(visited_n * 100.0 / total))
        if pct >= 100:
            mark = "🟢"
        elif pct >= 50:
            mark = "🟡"
        else:
            mark = "⚪"
        row = f"{mark} {r['region']}   {visited_n}/{total}"
        if r["hidden_total"] > 0:
            row += f"（隐藏 {r['hidden_found']}/{r['hidden_total']}）"
        lines.append(row)

    lines.append(SEP)
    lines.append(
        f"全大陆探索度 {overall['pct']}%（{overall['visited']}/{overall['total']}）"
    )
    lines.append(_tip(env, "explore"))
    return lines
