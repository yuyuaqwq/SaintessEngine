# -*- coding: utf-8 -*-
"""包内爬塔命令（`content/cmds_tower.py`）—— 『爬塔』的守卫/取参/业务/**渲染**。

终态形状（B18 样板定形；真源 = `overnight/B18_TERMINAL_SHAPE.md` §1.2）：
* handler 签名 `fn(env) -> list[str]`，**直接返回已渲染行**（本命令全 f-string，不涉文案表 →
  字面量随业务一起进包，宿主 `game/commands/tower.py` 里已无任何渲染代码）。
* 取参走引擎 `Env`：`env.arg_text("爬塔")`（= 旧 `self._strip_cmd(event, "爬塔")` 同口径）。
* 分支：等级门槛 → 战斗中拦截 → 目标层解析（1..30、只能挑战已突破层的下一层）→ 每日上限
  → 同层幂等 → 塔层查询 → 塔卫构造 → **开战装配（宿主能力）** → 开战面板。

1. `build_monster` → **包内直取** `content/drops.py`（B2-C2 真搬：drops 8 个真函数已进包；
   调用点用函数内 import，与原 `_host_*("core.drops", …)` 的「调用时解析」同刻）。
2. 开战装配（`Battle` + `battle_bridge` + `db.save_battle` + 单进程锁 + 阵型面板 =
   「必须认识活人世界」）→ 宿主壳对象上的可选能力 `_open_tower_battle`，由桥接层经
   `env.state["shell"]` 透传（与 B18a 的 `ctx.cap("_open_tower_battle")` 同源；P2 后由引擎
   Host 的能力口取代）。缺能力 → `None`（与真源 try/except 同效）。

行为逐字节不变；证据 = `overnight/W-B18-样板.md` 的 62 场景快照（sha256 改前 = 改后）。
"""
from __future__ import annotations

from .commands import register
from .flow import tower_progress as _TP

_SEP = "━━━━━━━━━━━━"


def _shell(env):
    """宿主壳对象（桥接层经 `env.state["shell"]` 注入）——可选能力面；无 → None。"""
    return (env.state or {}).get("shell")


def _tower_start(d: dict) -> str:
    """开战面板：7 行模板 + 战斗阵型面板插到第 4 行后（真源同款行序）。"""
    lines = [
        f"🏯 【修炼塔·{d['fl_name']}】",
        f"你踏入第 {d['floor']} 层，一个身影从阴影中浮现——",
        f"👤 【{d['guard_name']}】Lv.{d['guard_lv']}（建议 Lv.{d['suggest_lv']}）",
        f"📜 {d['desc']}",
        f"{_SEP}",
        f"奖励：经验 +{d['reward_exp']} 金币 +{d['reward_gold']}（击败后自动入账）",
        f"你的行动：『攻击』『技能 <名称>』『防御』『逃跑』",
    ]
    if d["panel"] is not None:
        lines.insert(4, d["panel"])
    return "\n".join(lines)


@register("tower_cmd", guards=("hook:player",), params=("cmd=爬塔",))
def tower_cmd(env) -> list:
    qq_id = env.uid
    group_id = env.group_id
    player = env.player
    lv = int(player.get("level") or 1)
    min_lv = int(getattr(_TP, "TRIAL_MIN_LV", 70) or 70)
    max_floor = int(getattr(_TP, "TRIAL_MAX_FLOOR", 30) or 30)
    daily_limit = int(getattr(_TP, "TRIAL_DAILY_LIMIT", 3) or 3)
    if lv < min_lv:
        return [f"🏯 修炼塔的门扉紧闭——塔灵的低语传来：『未至 {min_lv} 级者，不可窥见登天之路。』\n"
                f"💡 先完成『周常』悬赏和主线提升，到了 Lv.{min_lv} 再来挑战吧～"]
    shell = _shell(env)
    if shell is not None and shell._in_any_battle(group_id, qq_id):
        return ["⚔️ 你正在战斗中！先解决眼前的敌人再说～(『攻击』『技能 <名称>』『防御』)"]
    st = _TP._tower_state(qq_id)
    today_cleared = [int(x) for x in (st.get("cleared_today") or [])]
    cur = int(st.get("cur") or 0)
    max_reached = cur
    # 『爬塔』默认目标：已突破最高层的下一层（线性推进；每日最多 3 个新层）
    raw_arg = env.arg_text("爬塔")               # = 旧 `self._strip_cmd(event, "爬塔")`
    if raw_arg.isdigit():
        floor = int(raw_arg)
        if floor < 1 or floor > max_floor:
            return [f"🏯 修炼塔共 {max_floor} 层，没有第 {floor} 层哦～(『爬塔 层数』1-{max_floor})"]
        if floor != max_reached + 1:
            return [f"🏯 你还没解锁第 {floor} 层——塔灵只放行已突破层数的下一层。\n"
                    f"💡 回复『爬塔』挑战第 {max_reached + 1} 层～"]
    else:
        if max_reached >= max_floor:
            return ["👑 你已登顶修炼塔之巅！这座塔已没有能拦住你的楼层了——"
                    "强者无需重复登顶，把传说留给后来者吧。"]
        floor = max_reached + 1
    # 每日上限：今日已通 >=3 → 拦截新层（已通层同层不可重刷：进度线性、防刷经验）
    if len(today_cleared) >= daily_limit:
        return [f"🌙 今日修炼已通过 {len(today_cleared)}/{daily_limit} 层，塔灵说该歇息了——明日再来！\n"
                f"🏯 当前进度：已突破至第 {cur} 层（明日『爬塔』挑战第 {cur + 1} 层）"]
    if floor in today_cleared:
        return [f"🏯 第 {floor} 层今日已突破过——塔灵只认新的挑战。\n"
                f"💡 回复『爬塔』挑战第 {max_reached + 1} 层，或明日再来～"]
    fd = _TP._floor_def(floor)
    if not fd:
        return ["🏯 塔灵正在重构试炼……稍后再来挑战吧～"]
    from .drops import build_monster as _build_monster   # B2-C2 包内直取（原宿主句柄；调用时解析）
    guard = _TP.build_tower_guard(floor, _build_monster)
    guard_name = guard.get("name", "塔卫")
    # 开战装配 = 宿主能力（本线不搬）：返回「插入到第 4 行后的阵型面板串」，无 → None
    open_battle = getattr(shell, "_open_tower_battle", None) if shell is not None else None
    panel_str = open_battle(group_id, qq_id, player, guard) if open_battle else None
    return [_tower_start({
        "fl_name": (fd.get("name") or f"第{floor}层"),
        "floor": floor,
        "guard_name": guard_name,
        "guard_lv": guard.get("lv"),
        "suggest_lv": fd.get("lv"),
        "desc": (fd.get("desc") or ""),
        "reward_exp": int(fd.get("reward_exp") or 0),
        "reward_gold": int(fd.get("reward_gold") or 0),
        "panel": panel_str,
    })]
