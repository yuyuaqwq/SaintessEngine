# -*- coding: utf-8 -*-
"""包内今日事件命令（`content/cmds_event.py`）—— 『今日事件』『事件 <地图名>』『领取补给箱』
的守卫/取参/业务/**渲染**（v140 波3.7 地图随机事件菜单 + 波3.3 每日补给箱）。

方案 3（deleg方案-2）：『今日事件』指令 = 全服总览三栏（今日奇遇/世界事件/彩蛋线索）；
『事件 <地图名>』深查 = 单图事件详情（今日奇遇 + POI 清单 + 彩蛋传闻）。
概率模糊带：只给档位不给数值（较高/较低/罕见），防止把随机当保底刷。

终态形状（B18；真源 = `overnight/B18_TERMINAL_SHAPE.md` §1.2）：
* handler 签名 `fn(env) -> list[str]`，**直接返回已渲染行**；文案调用点（`supply.*` 7 条）随渲染
  一起进包（`content/texts.py`，宿主薄壳注入 SPEC_PATH）—— 宿主 `game/commands/event_menu.py`
  里已无任何文案调用点。
* 取参：`env.text`（= 旧 `event.message_str` 同口径，已 strip）+ `env.arg_text("事件")`
  （= 旧 `self._strip_cmd(event, "事件")` 同口径）。
* 读表全走包内：`content/event_menu.py`（MAPS / MAP_BY_ID / EXPLORE_EVENTS / EXPLORE_EGG_EVENTS /
  ITEMS / resolve_item / resolve_material / display_material / daily_event_for）+
  `content/catalog_rules.py`（DAILY_MAP_EVENTS / SUPPLY_BOX）+ `content/catalog_b143.py`
  （WORLD_EVENT_POOL）—— 与改造前宿主 `C.*` 同名同值同序（B14 收口的单向门面）。
* 副作用（发物 / 每日·每周限额）走**包内存档层** `content/persistence/`（B17 归包）：宿主
  `db.add_item` / `db.get_event_state` / `db.set_event_state` 就是它的同名转发。

★ 文案表口径（`tests/test_texts_table.py`）：`补给箱` 域的调用点真源 = **本文件**
（`WIRED["补给箱"] = [宿主, 包内]` 两侧）—— 迁移前 7 条 `supply.*` 声明与调用点逐条对账不变。

行为逐字节不变（三栏行序 / 档位带 / 限额分支 / 补给箱三连领发物清单 = 改造前逐行）；证据 =
`overnight/W-B18-L6.md` 的 34 场景快照（sha256 改前 = 改后，含背包/event_state 逐行 dump）。
"""
from __future__ import annotations

import datetime

from . import event_menu as _EM
from . import texts as T
from .catalog_b143 import WORLD_EVENT_POOL as _WORLD_EVENT_POOL
from .catalog_rules import DAILY_MAP_EVENTS as _DAILY_MAP_EVENTS
from .catalog_rules import SUPPLY_BOX as _SUPPLY_BOX
from .commands import register
from .persistence.inventory import add_item
from .persistence.world import get_event_state, set_event_state


def _fx_label(effects: dict) -> str:
    """今日奇遇效果 → 概率模糊带文案（只给档位不给数值，防把随机当保底刷）。"""
    notes = []
    _er = float(effects.get("encounter_rate", 0) or 0)
    if _er > 0.08:
        notes.append("遇怪率↑↑(较高)")
    elif _er > 0:
        notes.append("遇怪率↑(较低)")
    elif _er < -0.08:
        notes.append("遇怪率↓↓(较低)")
    elif _er < 0:
        notes.append("遇怪率↓(较低)")
    _ec = float(effects.get("event_chance", 0) or 0)
    if _ec > 0:
        notes.append("事件率↑")
    _el = float(effects.get("elite_chance", 0) or 0)
    if _el > 0:
        notes.append("精英出没")
    _lm = float(effects.get("loot_mult", 1.0) or 1.0)
    if _lm > 1.3:
        notes.append("掉落丰收")
    elif _lm > 1.0:
        notes.append("掉落略增")
    _mats = effects.get("mats") or []
    if _mats:
        notes.append(f"材料倾向：{'、'.join(str(m) for m in _mats[:3])}")
    return "，".join(notes) if notes else "风平浪静"


@register("event_menu", guards=("hook:player",), params=("cmd=今日事件",))
def event_menu(env) -> list:
    """『今日事件』总览 / 『事件 <地图名>』深查 / 『领取补给箱』每日领取。"""
    msg = env.text or ""
    # 『领取补给箱』：每日补给箱领取（SUPPLY_BOX 3 档限额）
    if "领取补给箱" in msg:
        return _claim_supply_box(env)
    # 『今日事件』→ 总览；『事件 <地图名>』→ 深查（裸『事件』由 world_event 占用）
    if "今日事件" in msg:
        raw = ""
    else:
        raw = env.arg_text("事件").strip()
    # 『事件 <地图名>』深查
    if raw:
        map_name = raw.strip()
        _maps = _EM.MAPS
        target = next((m for m in _maps
                       if m.get("name") == map_name or map_name in str(m.get("name", ""))), None)
        if not target:
            return [f"🗺️ 没找到地图『{map_name}』，试试『今日事件』看全部～"]
        return _map_event_detail(env, target)
    # 总览
    return _overview(env)


def _today_event_for(map_id: str):
    """取今日奇遇（逻辑在包 `content/event_menu.py:daily_event_for`；表由本模块注入）。"""
    try:
        return _EM.daily_event_for(map_id, _DAILY_MAP_EVENTS)
    except Exception:
        return None


def _overview(env) -> list:
    """全服总览：今日奇遇/世界事件/彩蛋线索三栏。"""
    lines = ["📅 【今日事件】", "━━━━━━━━━━━━"]
    # 一、今日奇遇（遍历全部配置了 DAILY_MAP_EVENTS 的野外图）
    daily_map = _DAILY_MAP_EVENTS or {}
    ev_maps = []
    if daily_map:
        for mid, variants in daily_map.items():
            ev = _today_event_for(mid)
            if not ev or not ev.get("name"):
                continue
            mname = (_EM.MAP_BY_ID or {}).get(mid, {}).get("name", mid)
            note = _fx_label(ev.get("effects") or {})
            ev_maps.append(f"  🌤 {mname}：{ev['name']}——{ev.get('desc', '')}（{note}）")
    if ev_maps:
        lines.append("【今日奇遇】")
        lines.extend(ev_maps)
    else:
        lines.append("【今日奇遇】")
        lines.append("  今日风平浪静，暂无特别奇遇～")
    # 二、世界事件（当前进行中的，由 WORLD_EVENT_POOL + social 管理）
    lines.append("")
    lines.append("【世界事件】")
    wpool = _WORLD_EVENT_POOL or []
    if isinstance(wpool, dict):
        wpool = list(wpool.values())
    active = [e for e in wpool if e.get("active")]
    if active:
        for e in active[:5]:
            lines.append(f"  🌋 {e.get('name', '未知事件')}：{e.get('desc', '')}")
    else:
        lines.append("  暂无世界事件进行中。")
    # 三、彩蛋线索（酒馆传闻式：只给方向不给答案）
    lines.append("")
    lines.append("【彩蛋线索】")
    egg_events = _EM.EXPLORE_EGG_EVENTS or []
    if egg_events:
        hints = [e for e in egg_events if e.get("hint")]
        shown = hints[:3] if hints else egg_events[:3]
        for e in shown:
            lines.append(f"  🥚 {e.get('hint') or e.get('desc', '有人在野外见过不寻常的东西…')}")
    else:
        lines.append("  旅人们传言，最近野外有些动静……")
    lines.append("")
    lines.append("💡 『事件 <地图名>』查看单图详情（如：事件 橡木平原）")
    return lines


def _map_event_detail(env, target) -> list:
    """单图事件详情：今日奇遇 + 探索事件池 + 彩蛋传闻。"""
    mid = target.get("id", "")
    lines = [f"🗺️ 【{target.get('name', mid)}】事件", "━━━━━━━━━━━━"]
    # 今日奇遇
    ev = _today_event_for(mid)
    if ev and ev.get("name"):
        note = _fx_label(ev.get("effects") or {})
        lines.append(f"🌤 今日奇遇：{ev['name']}——{ev.get('desc', '')}（{note}）")
    else:
        lines.append("🌤 今日奇遇：无特别效果，风平浪静。")
    # 探索事件池（EXPLORE_EVENTS 该图可用事件——按地图匹配近似展示，只给档位）
    lines.append("")
    lines.append("📦 探索事件（随机触发，概率模糊带）：")
    explore = _EM.EXPLORE_EVENTS or []
    if explore:
        # 展示高频档位（weight 排序，不泄露精确概率）
        top = sorted(explore, key=lambda e: -e.get("weight", 0))[:6]
        for e in top:
            band = "较高" if e.get("weight", 0) >= 15 else ("普通" if e.get("weight", 0) >= 8 else "罕见")
            lines.append(f"  {e.get('name', '?')}（{band}）")
    else:
        lines.append("  （暂无探索事件配置）")
    # 彩蛋传闻
    lines.append("")
    lines.append("🥚 彩蛋传闻：")
    egg_events = _EM.EXPLORE_EGG_EVENTS or []
    if egg_events:
        hints = [e for e in egg_events if e.get("hint")]
        for e in (hints or egg_events)[:2]:
            lines.append(f"  {e.get('hint') or e.get('desc', '…')}")
    else:
        lines.append("  传闻这里埋着不寻常的东西……")
    return lines


# ================= v140 波3.3：每日补给箱领取（SUPPLY_BOX） =================

def _grant_items(env, items) -> list:
    """发放物品列表（兼容 items/materials 双表），返回实际发放清单。"""
    got = []
    for iname in items:
        _iid = _EM.resolve_item(iname)
        if _iid in _EM.ITEMS:
            add_item(env.group_id, env.uid, _iid, _EM.ITEMS[_iid])
            got.append(iname)
        else:
            # 材料兜底：真源 `C.MATERIALS`（材料域未进包 —— 见 `content/event_menu.py` §缺口）。
            # 该分支在真源数据下**结构性不可达**（证明见 `content/event_menu.py` ③）：
            # 实测 SUPPLY_BOX 三档 9/9 物品名都命中上面的 ITEMS 分支。
            _imid = _EM.resolve_material(iname)
            if _imid in _EM.MATERIALS:
                add_item(env.group_id, env.uid, _imid, {
                    "name": _EM.display_material(_imid),
                    "type": _EM.MATERIALS[_imid].get("type", "材料"),
                    "stackable": True, "price": _EM.MATERIALS[_imid]["price"]})
                got.append(iname)
    return got


def _claim_supply_box(env) -> list:
    """领取每日补给箱（SUPPLY_BOX 3 档，限额用 event_state 记日期/周）。

    限额口径（方案 3.8）：
    - supply_mat 材料箱：每日 1 个
    - supply_tool 道具箱：每日 1 个（原设计累计 3 个每日任务，简化按日限）
    - supply_rich 豪华箱：每周 ≤2 个（原设计累计 7 个每日任务，简化按周限）
    """
    qq_id = env.uid
    today = datetime.date.today().isoformat()
    # 周起始（周一）
    monday = (datetime.date.today() - datetime.timedelta(days=datetime.date.today().weekday())).isoformat()
    boxes = _SUPPLY_BOX or []
    if not boxes:
        return [T.static("supply.missing")]
    lines = [T.static("supply.title"), "━━━━━━━━━━━━"]
    claimed_any = False
    for box in boxes:
        bid = box.get("id", "")
        limit = box.get("limit", "")
        # 限额判定
        if limit == "daily_1":
            key = f"supply_{bid}_{qq_id}_{today}"
            if get_event_state(key):
                lines.append(T.text("supply.daily_done", name=box.get("name", bid)))
                continue
            set_event_state(key, "1")
        elif limit == "daily3":
            key = f"supply_{bid}_{qq_id}_{today}"
            if get_event_state(key):
                lines.append(T.text("supply.daily_done", name=box.get("name", bid)))
                continue
            set_event_state(key, "1")
        elif limit == "weekly2_daily7":
            # 每周 ≤2：数本周已领次数
            wk = f"supply_{bid}_{qq_id}_wk_{monday}"
            cnt = int(get_event_state(wk) or 0)
            if cnt >= 2:
                lines.append(T.text("supply.weekly_done", name=box.get("name", bid),
                                    cnt=cnt))
                continue
            set_event_state(wk, str(cnt + 1))
        else:
            continue
        # 发放
        got = _grant_items(env, box.get("items", []))
        claimed_any = True
        if got:
            lines.append(T.text("supply.granted", name=box.get("name", bid),
                                items="、".join(got)))
    if not claimed_any:
        lines.append(T.static("supply.all_done"))
    lines.append("")
    lines.append(T.static("supply.tip"))
    return lines
