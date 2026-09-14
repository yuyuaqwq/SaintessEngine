# -*- coding: utf-8 -*-
"""包内「命令层公共规则」（`content/cmds_base_rules.py`）—— B18-L7：宿主 `game/commands/base.py`
的**游戏内容部分**整块进包（★ 非命令模块：本文件**不调** `register`，只为命令表之外的公共判定/
格式/守卫提供实现）。

搬什么、留什么（边界判据，逐条可复核）
------------------------------------
**留宿主**（`game/commands/base.py` 只余这些 + 一行转发）：
  * 注册装饰器 / 守卫骨架：`saintess_engine.command` 的 `require_player` / `require_battle` 再导出、
    `_GameCmdFilter` + `_maint_gate`（停服 gate：AstrBot `CustomFilter` + `event.stop_event` 平台面）；
  * **框架契约的「使用方钩子表」**（权威出处 = `saintess_engine/command/base.py` 模块头那张表）：
    `_uid` / `_player` / `_in_any_battle` / `_tip_pool_map` / `_record_state` /
    `_host_handler_finder` / `_build_static_handlers` / `_build_command_regex_strings`
    与 hint 类属性名（`register_hint` / `battle_none_hint` / `logger_name` / `command_aliases`）；
  * 已是一行转发的公共钩子：`_rule_fire` / `_title_bonus`（实现早在包内 `content/rule_engine` ·
    `content/stat_bonus`）；
  * **平台发送能力口** `_broadcast`（`self.context.send_message` + onebot 平台前缀 —— 包内
    `content/social_cmds.py` 头注同样把它记为「平台发送，留宿主」）。

**搬进本包**（判据三条命中任一 = 游戏内容）：
  ① 读**游戏表/名词**（`MAP_BY_ID` / `SUBAREA_KIND` / `ENHANCE_SMITH_MAPS` / `ALL_WILD` /
     `PROF_WAIT_BASE` / `PCT_STATS` / `STAT_NAMES`）；
  ② 业务判断的**判据是游戏机制**（铁匠/商店/旅店子区域、野外行商在场、体力上限 100+等级×2、
     等待型副业互斥）；
  ③ 产出**玩家可见句子/格式**（体力条、属性来源行、副业等待提示、「你还没有角色」提示）。
  ⇒ `at_smith` / `at_shop` / `sa_shop_kind` / `wild_trader_here` / `at_healer` / `facility_hint` /
     `fmt_stat_src` / `stamina_max` / `stamina` / `spend_stamina` / `add_stamina` / `stamina_bar` /
     `no_prof_waiting` + 三条文案（`REGISTER_HINT` / `BATTLE_NONE_HINT` / `COMMAND_ALIASES`）。

取件口径（搬包只动「宿主取件」→ 包内直连；正文逐字搬）
------------------------------------------------------
| 宿主旧取件 | 本包 | 证据 |
|---|---|---|
| `C.MAP_BY_ID` | `content.catalog_space.MAP_BY_ID` | 同一对象（`overnight/b18l7_probe.py`） |
| `C.SUBAREA_KIND` / `C.PROF_WAIT_BASE` | `content.catalog_life.*` | 同一对象 |
| `C.ENHANCE_SMITH_MAPS` | `content.catalog_items.ENHANCE_SMITH_MAPS` | 同一对象 |
| `C.PCT_STATS` | `content.catalog_core.PCT_STATS` | 同一对象 |
| `STAT_NAMES`（宿主薄壳） | `content.panel.STAT_NAMES` | 同一对象 |
| `C.ALL_WILD` / `C.npc_map_id` / `C.wild_npc_findable` | `content.wild.*` | 同一对象（63 条） |
| `db.update_player` | `content.persistence.update_player` | **同一个函数对象**（B17 存档归包） |
| `..core.instance_gate.stamina_short_msg` | `content.flow.instance_gate.stamina_short_msg` | 同一函数 |
| `C.TIPS`（框架钩子 `_tip_pool_map` 的来源） | `content.item_templates.TIPS` | 同一对象 |
| `base.REGISTER_HINT` 字面量 | `content/guards.NO_PLAYER_HINT`（唯一真源） | 逐字同句 |
| `base.battle_none_hint` 字面量 | `content/guards.BATTLE_NONE_HINT`（唯一真源） | 逐字同句 |
| `base.no_prof_waiting`（旧通道装饰器） | **转引** `content/guards.no_prof_waiting`（包侧同名守卫） | 逐字同句（见下） |

⚠️ **防包内双源**：`no_prof_waiting` 的判定与文案，L3c 线已作为**包侧守卫**
（`content/guards.py::no_prof_waiting`，env 面）落进包 —— 本模块因此**不重写**这条规则，
只把宿主旧通道的 `@no_prof_waiting()` 装饰器（`self` + AstrBot `event` 面）做成
**薄适配器**（`_LegacyShellEnv` 造最小 `Env` → 调同一个守卫）；句子也**转引**
`guards.BATTLE_NONE_HINT` / `guards.NO_PLAYER_HINT`，全包只有一份。

行为逐字节不变：证据 = `overnight/b18l7_snap.py` 的 **202 场景**（正常/边界/失败 + 真实副作用）
改前/改后同 sha256；本线报告 `overnight/W-B18-L7.md`。

文案仍为**包内字面量**（未挂文案表 key）：`battle_none_hint` / 副业等待句 / 体力条 / 属性来源行
本来就不在 `game/data/text_specs.json` 里（改造前同样是字面量），本波只做搬家不改形状；
登记见报告「未做与缺口」。
"""
from __future__ import annotations

import functools
import time

from . import catalog_core as _ccore
from . import catalog_items as _cat_items
from . import catalog_life as _cat_life
from . import catalog_space as _cat_space
from . import guards as _guards
from . import wild as _wild
from .item_templates import TIPS
from .panel import STAT_NAMES
from .persistence import update_player

__all__ = [
    "REGISTER_HINT", "BATTLE_NONE_HINT", "COMMAND_ALIASES", "TIP_POOL",
    "at_smith", "at_shop", "sa_shop_kind", "wild_trader_here", "at_healer",
    "facility_hint", "fmt_stat_src", "stamina_max", "stamina", "spend_stamina",
    "add_stamina", "stamina_bar", "no_prof_waiting",
]

# v95.26 统一注册引导：所有"没角色"拦截只走这一处文案，改格式只动这里
# v105 P3(M01)：与注册错误提示格式统一（『注册 <名字> <性别> [种族]』），防两处格式串不一致
# ★ B18-L7：唯一真源 = 包内 `content/guards.py::NO_PLAYER_HINT`（宿主 `base.REGISTER_HINT` 转引本名）
REGISTER_HINT = _guards.NO_PLAYER_HINT

#: 框架钩子 `battle_none_hint`（战斗守卫拦截句；★ 唯一真源 = `content/guards.py::BATTLE_NONE_HINT`）
BATTLE_NONE_HINT = _guards.BATTLE_NONE_HINT

#: 框架钩子 `command_aliases`（剥参数时的指令别名；逐字 = 宿主旧 `base.CommandBase.command_aliases`）
COMMAND_ALIASES = ("我的角色", "位置", "主线", "help")

#: 框架钩子 `_tip_pool_map` 的来源（提示语分类库）
TIP_POOL = TIPS


class _LegacyShellEnv:
    """旧通道（宿主壳 `self` + AstrBot `event`）→ 引擎 `Env` 口径的**最小适配**。

    只为把宿主装饰器接到包侧守卫（`content/guards.py::no_prof_waiting`）的入参形状上：
    该守卫只读 `state["shell"]` / `group_id` / `uid` / `clock` 四个字段（其余字段给同形默认值，
    与 `_host_bridge.run` 造的 `Env` 同口径：uid/group_id 转 str、clock = `time.time`）。
    """

    def __init__(self, shell, event):
        group_id, qq_id = shell._uid(event)
        self.state = {"shell": shell}
        self.group_id = str(group_id)
        self.uid = str(qq_id)
        self.clock = time.time
        self.key = ""
        self.text = (event.get_message_str() or "").strip()
        self.raw = event
        self.player = None


def no_prof_waiting():
    """等待型副业（v55：垂钓/采集/挖掘）进行中时拦截该命令。

    装饰 async generator 命令方法（命令类方法都是 yield event.plain_result 的 async generator）。
    用法（@filter.regex 的下方）：
        @filter.regex(r"...")
        @no_prof_waiting()
        async def move(self, event): ...
    以后任何"会换场景/进战斗"的命令（副本、探索、世界 Boss 等）要跟副业互斥，
    加这一行装饰器即可，检查逻辑只维护这一处。

    ★ B18-L7：装饰器实现由宿主 `game/commands/base.py` 搬进包（宿主改为同名再导出）；
    **判定与文案不在此处重写** —— 唯一真源 = 包侧同名守卫 `content/guards.py::no_prof_waiting`
    （L3c 线已落包，env 面）。本函数只是把旧通道的 `self` + `event` 形状适配过去，
    回话逐字 = 旧装饰器（`⏳ 你还在{tname}呢，再有 {left} 秒完成！…`，两次独立取时口径保留）。
    """
    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(self, event, *args, **kwargs):
            blocked = _guards.no_prof_waiting(_LegacyShellEnv(self, event), None)
            if blocked:
                yield event.plain_result(blocked)
                return
            async for item in fn(self, event, *args, **kwargs):
                yield item
        return wrapper
    return deco


# ---------- v87.17 设施子区域判定（游戏内容）----------
def at_smith(player: dict) -> bool:
    """当前是否在铁匠铺/锻造坊/工坊/军械/强化类子区域（锻造/代工/强化/附魔场所）。
    v87.6 子区域化：不再地图级一刀切（广场/旅店不能锻造）。
    v125：关键词嗅探 + white_deer_8 特判 → 读 shop.SUBAREA_KIND（smith/enhance）。
    ★ B18-L7：逐字 = 宿主旧 `base.CommandBase._at_smith`。"""
    cur_map = player.get("cur_map", "")
    if cur_map not in _cat_items.ENHANCE_SMITH_MAPS:
        return False
    sa_id = player.get("cur_subarea") or ""
    if not sa_id:
        return False
    cm = _cat_space.MAP_BY_ID.get(cur_map, {})
    for sa in (cm.get("subareas") or []):
        if sa["id"] == sa_id:
            # craft funcs 结构判断保留（炼金工坊 dawn_city_5 等双职能店可锻造）
            if "craft" in (sa.get("funcs") or []):
                return True
            # 鹿角淬火坊(white_deer_8) 为 enhance（强化/附魔可用但非铁匠铺）
            return _cat_life.SUBAREA_KIND.get(sa_id) in ("smith", "enhance")
    return False


def at_shop(player: dict, group_id: str = "", qq_id: str = "") -> bool:
    """v87.17 当前子区域是否有商店（shop: true 或 funcs 含 shop）。
    设施子区域绑定铁律：商店命令只在有商店的子区域放行。
    v95.4：野外行商（trade funcs）在场时也可交易。
    v101.25h：草药铺（alchemy）/ 酒馆旅店（heal）也是可交易子区域（按类型配货）。
    ★ B18-L7：逐字 = 宿主旧 `base.CommandBase._at_shop`。"""
    cur_map = player.get("cur_map", "")
    sa_id = player.get("cur_subarea") or ""
    if sa_id:
        cm = _cat_space.MAP_BY_ID.get(cur_map, {})
        for sa in (cm.get("subareas") or []):
            if sa["id"] == sa_id:
                funcs = sa.get("funcs") or []
                if sa.get("shop") or "shop" in funcs or "alchemy" in funcs or "heal" in funcs or sa.get("healer"):
                    # v104 M09 P1 修复：补 healer key——铁锚酒馆(ironharbor_5, shop=False, healer=True)
                    #   有配货却因 _at_shop 不查 healer 而『商店』报"这里没有商店"（_sa_shop_kind 已判 tavern）
                    return True
                break  # v95.4：当前子区域不是商店 → 继续查野外行商
    # v95.4：不在城镇设施 → 看是否有野外行商在场
    return wild_trader_here(player, group_id, qq_id)


def sa_shop_kind(player: dict) -> str | None:
    """v101.28o 当前子区域商店类型（决定配货；2026-08-12 鱼鱼抓"鹿香灶坊卖装备"后收紧）：
    smith（铁匠/锻造/军械/工坊/强化）→ 武器+材料+装备；
    herb（草药/炼金）→ 只卖药剂；
    tavern（酒馆/旅店/客栈）→ 只卖食物；
    cook（灶坊/烹饪/食铺/磨坊）→ 只卖食物配货，不挂武器；
    general（集市/商行/码头/商店/杂货/补给/营地）→ 卷轴/杂物+武器；
    misc（其他 shop=True 无关键词，如拍卖行/渔港/强化坊）→ 只卖配货，不挂武器；
    非商店子区域 → None。
    ⚠️ 禁止把 shop=True 兜底成 general——否则灶坊/拍卖行全挂武器（#443 同源教训）。
    ★ B18-L7：逐字 = 宿主旧 `base.CommandBase._sa_shop_kind`。"""
    cur_map = player.get("cur_map", "")
    sa_id = player.get("cur_subarea") or ""
    if not sa_id:
        return None
    cm = _cat_space.MAP_BY_ID.get(cur_map, {})
    for sa in (cm.get("subareas") or []):
        if sa["id"] != sa_id:
            continue
        # v125：kind 数据下沉 shop.SUBAREA_KIND（旧关键词嗅探全量迁移，含优先级：
        # herb>smith>tavern>cook>general>misc 已烘焙进表值）；未入表子区域按 funcs 兜底
        kind = _cat_life.SUBAREA_KIND.get(sa_id)
        if kind:
            return kind
        funcs = sa.get("funcs") or []
        if "alchemy" in funcs:
            return "herb"
        if "craft" in funcs:
            return "smith"
        if sa.get("healer") or "heal" in funcs:
            return "tavern"
        if sa.get("shop") or "shop" in funcs:
            return "misc"
        return None
    return None


def wild_trader_here(player: dict, group_id: str = "", qq_id: str = "") -> str | None:
    """v95.4：当前地图是否有可交易的野外行商（funcs 含 trade 且出现条件满足）。
    #151 修复：返回命中的 NPC id（用于货摊标题显示正确 NPC 名），无则 None。
    ★ B18-L7：逐字 = 宿主旧 `base.CommandBase._wild_trader_here`。"""
    if not (group_id and qq_id):
        return None
    cur = player.get("cur_map", "")
    for nid, wnpc in _wild.ALL_WILD.items():
        if "trade" not in (wnpc.get("funcs") or []):
            continue
        if _wild.npc_map_id(nid, wnpc) != cur:
            continue
        if _wild.wild_npc_findable(nid, wnpc, player, group_id, qq_id):
            return nid
    return None


def at_healer(player: dict) -> bool:
    """v87.17 当前子区域是否有旅店（healer: true 或 funcs 含 heal）。
    设施子区域绑定铁律：住宿只在旅店子区域放行。
    ★ B18-L7：逐字 = 宿主旧 `base.CommandBase._at_healer`。"""
    cur_map = player.get("cur_map", "")
    sa_id = player.get("cur_subarea") or ""
    if not sa_id:
        return False
    cm = _cat_space.MAP_BY_ID.get(cur_map, {})
    for sa in (cm.get("subareas") or []):
        if sa["id"] == sa_id:
            if sa.get("healer"):
                return True
            return "heal" in (sa.get("funcs") or [])
    return False


def facility_hint(player: dict, kind: str) -> str:
    """v87.17 提示最近设施所在子区域（kind: shop/healer）。
    返回如『去 老铁铁匠铺 或 草药铺 看看』，无则空串。
    ★ B18-L7：逐字 = 宿主旧 `base.CommandBase._facility_hint`。"""
    cur_map = player.get("cur_map", "")
    cm = _cat_space.MAP_BY_ID.get(cur_map, {})
    names = []
    for sa in (cm.get("subareas") or []):
        if kind == "shop":
            if sa.get("shop") or "shop" in (sa.get("funcs") or []):
                names.append(sa.get("name", ""))
        elif kind == "healer":
            if sa.get("healer") or "heal" in (sa.get("funcs") or []):
                names.append(sa.get("name", ""))
        elif kind == "craft":
            # v101.21 铁匠类场所（装备回收/锻造），炼金工坊除外
            # v125：关键词嗅探 → shop.SUBAREA_KIND（炼金工坊 dawn_city_5 为 herb 自然排除）
            if "craft" in (sa.get("funcs") or []) or _cat_life.SUBAREA_KIND.get(sa.get("id")) == "smith":
                names.append(sa.get("name", ""))
    if not names:
        return ""
    uniq = []
    for n in names:
        if n and n not in uniq:
            uniq.append(n)
    return "去 " + " 或 ".join(uniq[:3]) + " 看看"


def fmt_stat_src(src: dict) -> str:
    """格式化单条属性来源：『来源名: 攻击＋8 生命＋40 暴击＋5%』
    ★ B18-L7：逐字 = 宿主旧 `base.CommandBase._fmt_stat_src`（全仓无调用点，纯搬家）。"""
    parts = []
    for k, v in src["stats"].items():
        name = STAT_NAMES.get(k, k)
        if k in _ccore.PCT_STATS:
            sign = "+" if v >= 0 else ""
            pct = "+" if src.get("pct") and k not in _ccore.PCT_STATS else ""
            parts.append(f"{name}{pct}{sign}{int(v*100)}%")
        else:
            sign = "+" if v >= 0 else ""
            if src.get("pct"):
                parts.append(f"{name}+{int(v*100)}%")
            else:
                parts.append(f"{name}{sign}{v}")
    return f"{src['name']}: {' '.join(parts)}" if parts else ""


# ---------- v94 体力系统 ----------
def stamina_max(player: dict) -> int:
    """体力上限：100 + 等级×2（★ B18-L7：逐字 = 宿主旧 `base._stamina_max`）"""
    return 100 + (player.get("level") or 1) * 2


def stamina(player: dict) -> int:
    """★ B18-L7：逐字 = 宿主旧 `base._stamina`"""
    return int(player.get("stamina") or 0)


def spend_stamina(group_id, qq_id, cost: int, player: dict, action: str = "行动") -> tuple:
    """扣体力；不足返回 (False, 提示)。够则落库并返回 (True, 剩余)。

    v185：不足的措辞改为 `content.flow.instance_gate.stamina_short_msg`（副本开本链同源，
    措辞只剩一处来源）。函数内延迟 import —— 避免包内模块环。
    ★ B18-L7：逐字 = 宿主旧 `base._spend_stamina`（唯一改动 = 取件：宿主 `db.update_player`
    → 包内 `content.persistence.update_player`，同一函数对象；宿主 `core.instance_gate`
    → 包内 `content.flow.instance_gate`，同一函数对象）。"""
    cur = stamina(player)
    if cur < cost:
        from .flow import instance_gate
        return False, instance_gate.stamina_short_msg(cost, cur, action)
    update_player(group_id, qq_id, stamina=cur - cost)
    return True, cur - cost


def add_stamina(group_id, qq_id, amount: int, player: dict) -> int:
    """加体力（封顶上限），返回实际增加量。
    ★ B18-L7：逐字 = 宿主旧 `base._add_stamina`。"""
    cur = stamina(player)
    mx = stamina_max(player)
    new = min(mx, cur + amount)
    if new != cur:
        update_player(group_id, qq_id, stamina=new, stamina_ts=int(time.time()))
        player["stamina"] = new  # v95.16 #80：同步 player dict，st_msg 显示恢复后值而非旧值
    return new - cur


def stamina_bar(player: dict, sep: str = " ") -> str:
    """体力显示条：⚡ 82/102（sep 可传『：』统一标签冒号格式）
    ★ B18-L7：逐字 = 宿主旧 `base._stamina_bar`。"""
    return f"⚡ 体力{sep}{stamina(player)}/{stamina_max(player)}"
