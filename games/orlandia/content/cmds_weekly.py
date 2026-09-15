# -*- coding: utf-8 -*-
"""包内周常命令（`content/cmds_weekly.py`）—— 『周常』『周常列表』的守卫/取参/业务/**渲染**。

终态形状（B18 样板定形；真源 = `overnight/B18_TERMINAL_SHAPE.md` §1.2）：
* handler 签名 `fn(env) -> list[str]`，**直接返回已渲染行**（`T.text/T.static` + 分隔线常量）——
  渲染点唯一 = 包内 `content/texts.py`（宿主 `game/commands/weekly.py` 里已无任何文案调用点）。
* 取参走引擎 `Env`：`env.arg_text("周常列表")`（= 旧 `self._strip_cmd(event, …)` 同口径）、
  `env.page(raw)`、`env.page_items(items, page, per_page=4)`。
* 数据/状态来自包内 `content/flow/weekly_progress.py`（周状态族 + 发布构造 + 悬赏池；
  宿主面由它自己的「宿主替身口」解析，本模块不 import 宿主）。

行为逐字节不变（面板行序 / 行内容 / 分支条件 = 改造前逐行）；证据 = `overnight/W-B18-样板.md`
的 62 场景快照（sha256 改前 = 改后）。
"""
from __future__ import annotations

from . import texts as T
from .commands import register
from .flow import weekly_progress as _WP

_SEP = "━━━━━━━━━━━━"


def _obj_label(obj: dict) -> str:
    """objective → 中文目标短标（面板行用）。"""
    if obj.get("kill_any"):
        return T.text("weekly.obj_kill_any", n=obj["kill_any"])
    if obj.get("kill_elite"):
        return T.text("weekly.obj_kill_elite", n=obj["kill_elite"])
    if obj.get("kill_boss"):
        return T.text("weekly.obj_kill_boss", n=obj["kill_boss"])
    return T.static("weekly.obj_other")


@register("weekly_cmd", guards=("hook:player",))
def weekly_cmd(env) -> list:
    """『周常』：Lv50 门槛 → 本周首查自动发布 → 进度面板（行序 = 旧命令体逐行）。"""
    qq_id = env.uid
    player = env.player
    lv = int(player.get("level") or 1)
    if lv < _WP.WEEKLY_MIN_LV:
        return [T.text("weekly.locked", min_lv=_WP.WEEKLY_MIN_LV)]
    st = _WP._week_state(qq_id)
    if not st or not st.get("tasks"):
        # 本周首查 → 自动发布
        st = {"tasks": _WP._assign_week(player), "done_n": 0}
        _WP._save_week_state(qq_id, st)
        lines = [T.static("weekly.title_new"), _SEP]
        for i, (tname, task) in enumerate(st["tasks"].items(), 1):
            lines.append(T.text("weekly.item_new", i=i, tname=tname, desc=task["desc"]))
            lines.append(T.text("weekly.item_line", obj=_obj_label(task["objective"]),
                                exp=task["reward_exp"], gold=task["reward_gold"]))
        lines.append("")
        lines.append(T.static("weekly.tip_new"))
        return lines
    # 查看进度
    tasks = st["tasks"]
    done_n = int(st.get("done_n", 0) or 0)
    lines = [T.text("weekly.title_progress", done_n=done_n, total=len(tasks)), _SEP]
    for i, (tname, task) in enumerate(tasks.items(), 1):
        prog = int(task.get("prog", 0) or 0)
        need = int(task.get("need") or 1)
        if task.get("done"):
            lines.append(T.text("weekly.item_done", i=i, tname=tname))
        else:
            lines.append(T.text("weekly.item_todo", i=i, tname=tname, prog=prog, need=need))
            lines.append(T.text("weekly.item_line", obj=_obj_label(task["objective"]),
                                exp=task["reward_exp"], gold=task["reward_gold"]))
    if done_n < len(tasks):
        lines.append("")
        lines.append(T.static("weekly.tip_progress"))
    return lines


@register("weekly_list", guards=("hook:player",), params=("cmd=周常列表", "page"))
def weekly_list(env) -> list:
    """『周常列表 [页]』：全部悬赏池总览（分页 4 条/页；池序 = 包内域源列表序）。"""
    player = env.player
    lv = int(player.get("level") or 1)
    raw_arg = env.arg_text("周常列表")            # = 旧 `self._strip_cmd(event, "周常列表")`
    all_pool = _WP.weekly_pool()
    page_items, pages, page = env.page_items(all_pool, env.page(raw_arg), per_page=4)
    lines = [T.text("weekly.pool_title", page=page, pages=pages, pick=_WP.WEEKLY_PICK),
             _SEP]
    for q in page_items:
        lv_req = int(q.get("min_lv") or 0)
        lock = " 🔒" if lv < lv_req else ""
        lines.append(T.text("weekly.pool_item", name=q["name"], lv_req=lv_req,
                            lock=lock, desc=q["desc"]))
        lines.append(T.text("weekly.pool_reward", exp=q["reward_exp"], gold=q["reward_gold"]))
    lines.append("")
    lines.append(T.static("weekly.pool_tip"))
    if pages > 1:
        lines.append(T.text("weekly.pool_more",
                            next_page=(page + 1 if page < pages else 1)))
    return lines
