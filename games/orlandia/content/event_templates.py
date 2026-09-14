# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— 事件模板引擎实现（B13 线3，2026-09-14）。

真源：游戏仓 `game/core/event_templates.py`（530 行）——本模块 = 那个模块的**实现本体**
（19 个模板里的 **18 个**逐字搬成模块级函数，`EventContext` / `execute_event_template` /
`register` / `_add_bp_or_pages` / `_BP_PAGE_BY_QUALITY` 全部逐字搬）。宿主
`game/core/event_templates.py` 现在只剩：再导出（含键序还原）+ 一行委托 + **tpl_merchant**（见下）。

★ 故意留在宿主的那一个模板（宿主源码级门禁，不是偷懒）
----------------------------------------------------
`tpl_merchant`（流浪商人档位抽取）留在宿主文件里，理由 = `tests/test_v184_loot_tiers.py:690-709`
的**源码级绑定**断言：

    ("game/core/event_templates.py",
     'QUALITY_TIERS.pick_weights({"white": 45, "green": 40, "blue": 15}, rng=random)', True)
    ("game/core/event_templates.py", 'random.choices([…白/绿/蓝…]', False)
    ↑ 本行**故意不逐字抄**那条禁词（源码级门禁是朴素子串扫描，抄进头注会被判「实现里还有它」）

即「宿主本文件里 merchant 的档位必须走 `QUALITY_TIERS.pick_weights`」——把实现搬走后这句
字符串就不在宿主文件里了，门禁会红。与 B9 线2 `commands/world.py` 的 `quest_view` /
`_instance_gate_block`（同款「宿主源码级门禁」）处置口径一致：**该模板留宿主唯一一份**，
包内不再有第二份（无双源）。宿主薄壳把它注册进本模块的 `TEMPLATES`（19 键不变，
`register` 也是本模块导出的同一个装饰器）。

正文改动面（**只有三类**，与本波其它线同款）
--------------------------------------------
1. 宿主模块引用 → 惰性替身：`from .. import db` / `from .. import content as C` →
   `db = _HostMod("db")` / `C = _HostMod("content")`（正文 `db.xxx(...)` / `C.xxx` **一行未改**）。
2. 宿主边界函数 → 同名惰性包装 / 包内直取：
   · `from ..content_rules.gameplay import check_player_level_up`（写库 + 写背包，属「接人性」，
     真源 `content/gameplay.py` 归属表 :75 明写**不搬**）→ 模块级同名包装（`_host_attr`）；
   · `from ..content_rules.panel import race_stats` → **包内直取** `from .panel import race_stats`
     （`content/panel.py:83` 已端口；实测全种族逐值相等：0 不等，见报告 §1）。
3. 命令方法级「取玩家」那种改造：本模块无需（纯逻辑，ctx 由调用方构造）。

★ 数据读口（I1）：`C`（宿主聚合层）上只剩**函数** —— `C.resolve` / `C.display` /
`C.roll_blueprint` / `C.generate_equip`（函数名，按 B14 派工口径不切）：`resolve`/`display` 的权威索引
在装配期宿主侧（`content/quests_flow.py:_Dom.resolve` 同口径委托宿主）→ `C` 替身保留。
★ W4（2026-09-14）核对：原记「缺口常量」`QUALITY` / `AUCTION_POOL` 已由 B14-3 收口门面
`content/catalog_b143.py` 提供（门禁逐键逐值+键序 OK）；本文件**只有头注提到、无代码读点** → 未动。
B14-2（L7 线）已切门面：材料表 → `content/catalog_items.py:MATERIALS`（10 处调用点，门禁逐名
OK · 不等 0，含键序）；`TRADER_DEAL_CHANCE`（真源 `game/data/battle_config.py`）包内落在
`content/catalog_core.py`，但本文件**只在头注出现、无代码读点** → 未动。

等价证据：`overnight/w1213_b13l3_snap.py`（改前/改后 124 用例逐字节快照，含真实副作用）
· `overnight/W-B13-L3-events-dialogue.md`。
"""
from __future__ import annotations

import importlib
import random
import sys


# ============================================================
# ① 宿主替身口（注入优先 → sys.modules → importlib；**绝不静默空跑**）
#    与 `content/world_cmds.py` / `content/combat_cmds.py` 同款
# ============================================================
_HOST_PKG = "data.plugins.dragonfall.game"      # 运行时（main.py 的模块路径）
_HOST_PKG_FALLBACK = "game"                     # 测试/工具按 `game.xxx` 直接 import 时
_INJECTED = {}


def bind_host(**objs):
    """宿主薄壳 import 期注入（幂等）——键 = `_HostMod` 的模块名（`content` / `db`）。"""
    for k, v in (objs or {}).items():
        if v is not None:
            _INJECTED[k] = v


def _host_module(name: str):
    """取宿主子模块（`name` 为空 = 宿主 `game` 包本身，真源 `from .. import X` 那一类）。"""
    if name in _INJECTED:
        return _INJECTED[name]
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        full = prefix if not name else "%s.%s" % (prefix, name)
        m = sys.modules.get(full)
        if m is not None:
            return m
    last = None
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        try:
            return importlib.import_module(prefix if not name else "%s.%s" % (prefix, name))
        except Exception as exc:                # noqa: BLE001
            last = exc
    raise RuntimeError("event_templates：宿主模块 %s 取不到（%s）——拒绝静默空跑" % (name, last))


def _host_attr(mod: str, attr: str):
    """宿主模块属性 —— 真源「函数内 `from ..<mod> import <attr>`」的同义替身（调用时解析）。"""
    m = _host_module(mod)
    try:
        return getattr(m, attr)
    except AttributeError:
        for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
            try:
                return importlib.import_module("%s.%s" % (
                    prefix if not mod else "%s.%s" % (prefix, mod), attr))
            except Exception:                   # noqa: BLE001
                continue
        raise


class _HostMod:
    """宿主模块替身（`C` / `db`）——`C.xxx` / `db.xxx` 正文一字未改，属性访问时解析。"""

    def __init__(self, name):
        self._name = name

    def __getattr__(self, attr):
        return getattr(_host_module(self._name), attr)


C = _HostMod("content")         # 真源 `from .. import content as C`
from ._pkgref import DB as db

# B14-2（L7 线）：数据名读点切包内门面 —— 原 `C.MATERIALS` 直取换成门面同名绑定
from .catalog_items import MATERIALS   # 真源 `C.MATERIALS`


def check_player_level_up(group_id, qq_id, player):
    """升级结算（真源 `from ..content_rules.gameplay import check_player_level_up` 的**同义包装**）

    **宿主边界**：写 `db` / 写背包 / 读章节礼包 —— `content/gameplay.py` 归属表 :75 明写「不搬
    （宿主边界）」，`content/combat_cmds.py:192` 同款处置（`_host_attr` 调用时解析）。
    """
    from .gameplay_rules import check_player_level_up as _pkg_level_up
    return _pkg_level_up(group_id, qq_id, player)


# ============================================================
# ② 模板注册表（真源逐字）
# ============================================================
TEMPLATES = {}


def register(name):
    """模板注册装饰器。"""
    def deco(fn):
        TEMPLATES[name] = fn
        return fn
    return deco


# v101.25 #349：探索宝箱/宝匣图纸掉落与战斗同规则——已学图纸折算为图纸残页，未学整张入包
# （playtest round72 小蓝抓包：宝箱掉『海风长弓图纸』已学仍整张入包，背包白占格子）
_BP_PAGE_BY_QUALITY = {"white": 1, "green": 1, "blue": 2, "purple": 4, "orange": 6}


def _add_bp_or_pages(ctx, db, bp):
    """已学图纸 → 图纸残页入包；未学 → 整张图纸入包。返回 (is_learned, bp_name, pages)。"""
    import uuid
    _learned = ctx._focus.get("learned_blueprints") or []
    if bp.get("blueprint_for") in _learned:
        _pages = _BP_PAGE_BY_QUALITY.get(bp.get("quality", "white"), 1)
        db.add_item(ctx.group_id, ctx.qq_id, "mat_tu_zhi_can_ye",
                    {"name": "图纸残页", "type": "材料", "stackable": True, "price": 10},
                    count=_pages)
        return True, bp["name"], _pages
    db.add_item(ctx.group_id, ctx.qq_id, f"eq_{uuid.uuid4().hex[:8]}", bp)
    return False, bp["name"], 0


class EventContext:
    """模板执行上下文。"""

    def __init__(self, group_id, qq_id, player, cur_map, params=None,
                 name="此地", hooks=None, loot_mult=None, pref_mats=None):
        self.group_id = group_id
        self.qq_id = qq_id
        self._focus = player
        self.cur_map = cur_map
        self.params = params or {}
        self.name = name
        self.hooks = hooks or {}
        # v115 今日奇遇：loot_mult=金币/材料倍率，pref_mats=材料倾向池（combat.py explore() 注入）
        self.loot_mult = loot_mult
        self.pref_mats = pref_mats or []

    # ---- 便捷访问 ----
    @property
    def lv(self):
        return self._focus.get("level", 1)

    def _db(self):
        return db            # 真源 `from .. import db; return db`（本模块级 = 宿主替身）

    def _C(self):
        return C             # 真源 `from .. import content as C; return C`

    def param(self, key, default=None):
        return self.params.get(key, default)

    # ---- v115 今日奇遇：材料倾向池 ----
    def mat_choice_pool(self, pool):
        """当日奇遇材料倾向：pref_mats 与传入池(显示名列表)有交集时优先从交集抽取，
        交集为空回退原池（数据依赖：daily_events.py 的 mats 与材料池同用显示名）。"""
        pref = self.pref_mats or []
        if not pref:
            return pool
        inter = [x for x in (pool or []) if x in pref]
        return inter if inter else (pool or [])


# ================= 模板实现 =================

@register("loot_gold")
def tpl_loot_gold(ctx):
    """金币：gold = randint(min,max) + lv*scale_lv。params: min/max/scale_lv/header
    v109.3 P0 修复：基数从 DB 读最新 gold（原用 ctx._focus 陈旧对象——调用方在
    _rule_fire 前可能已通过其他路径加过金币（如 _complete_side_quest 的行会委托
    在 _bump_daily_progress 落库），旧 dict 覆盖会吞掉金币——combat.py:1779 同型
    问题 v105 M18 已修，quest 路径漏网导致 test_v104_quests 30% 偶发失败）"""
    db = ctx._db()
    gold = random.randint(ctx.param("min", 10), ctx.param("max", 40)) + ctx.lv * ctx.param("scale_lv", 1)
    gold = int(gold * (ctx.loot_mult or 1.0))  # v115 今日奇遇 loot_mult 倍率
    cur = db.get_player(ctx.group_id, ctx.qq_id).get("gold", 0)
    db.update_player(ctx.group_id, ctx.qq_id, gold=cur + gold)
    header = ctx.param("header", "💰 你捡到了一些金币！")
    return header.replace("{name}", ctx.name).replace("{gold}", str(gold))


@register("loot_materials")
def tpl_loot_materials(ctx):
    """材料：从 mats 池随机 n 份入包，可带蓝图概率。params: mats/n/blueprint_chance/header
    v101.30d #O29：支持 cap_name/cap_count/fallback_mats——指定材料已有 cap_count 份时
    改掉 fallback 池（防任务/准入材料重复拾取，如泛黄书页满 3 张不再出）"""
    import uuid
    db = ctx._db()
    C = ctx._C()
    mats_pool = ctx.param("mats", ["草药"])
    cap_name = ctx.param("cap_name", "")
    if cap_name:
        have = db.count_item(ctx.group_id, ctx.qq_id, cap_name)
        if have >= ctx.param("cap_count", 1):
            mats_pool = ctx.param("fallback_mats", ["古木枝"])
    n = ctx.param("n", 1)
    # v115 今日奇遇：pref_mats 与池有交集时优先抽（交集为空回退原池）
    mats_choice = ctx.mat_choice_pool(mats_pool)
    got = []
    for _ in range(n):
        m = random.choice(mats_choice)
        mid = C.resolve("materials", m)
        if mid in MATERIALS:
            db.add_item(ctx.group_id, ctx.qq_id, mid,
                        {"name": C.display("materials", mid), "type": "材料",
                         "stackable": True, "price": MATERIALS[mid]["price"]})
            got.append(C.display("materials", mid))
    extra = ""
    bp_chance = ctx.param("blueprint_chance", 0)
    if bp_chance and random.random() < bp_chance:
        bp = C.roll_blueprint(max(1, ctx.lv))
        _learned, _bpn, _pages = _add_bp_or_pages(ctx, db, bp)
        if _learned:
            extra = (f"\n📜 图纸『{_bpn}』你已经学会了，化作 {_pages} 张图纸残页"
                     f"（『出售 图纸残页』变现）！")
        else:
            extra = ctx.param("bp_line", "\n📜 还翻出一张图纸：{bp}！").replace("{bp}", _bpn)
    header = ctx.param("header", "🎒 获得材料：{mats}！{extra}")
    return header.replace("{name}", ctx.name) \
                 .replace("{mats}", "、".join(got)) \
                 .replace("{extra}", extra)


@register("loot_gold_mats")
def tpl_loot_gold_mats(ctx):
    """金币+材料（可带图纸概率）。params: min/max/scale_lv/mats/blueprint_chance/header"""
    import uuid
    db = ctx._db()
    C = ctx._C()
    from .panel import race_stats  # 真源 `from ..content_rules.panel import race_stats`（包内已端口）
    gold = random.randint(ctx.param("min", 50), ctx.param("max", 120)) + ctx.lv * ctx.param("scale_lv", 5)
    gold = int(gold * (ctx.loot_mult or 1.0))  # v115 今日奇遇 loot_mult 倍率
    # v110 P0-1：与 tpl_loot_gold 同型修复——读 DB 最新 gold 再累加，防陈旧 dict 覆盖吞金币
    cur = db.get_player(ctx.group_id, ctx.qq_id).get("gold", 0)
    db.update_player(ctx.group_id, ctx.qq_id, gold=cur + gold)
    mat_line = ""
    mats_pool = ctx.param("mats", [])
    # v115 今日奇遇：pref_mats 与池有交集时优先抽（交集为空回退原池）
    mats_choice = ctx.mat_choice_pool(mats_pool)
    if mats_choice:
        mid = C.resolve("materials", random.choice(mats_choice))
        if mid in MATERIALS:
            db.add_item(ctx.group_id, ctx.qq_id, mid,
                        {"name": C.display("materials", mid), "type": "材料",
                         "stackable": True, "price": MATERIALS[mid]["price"]})
            mat_line = ctx.param("mat_line", "\n🎒 还得到一份材料：{mat}！").replace("{mat}", C.display("materials", mid))
    bp_line = ""
    bp_chance = ctx.param("blueprint_chance", 0)
    # v94 图纸经济：宝箱为图纸主要来源；阶段九：精灵森林之友——探索获得物品概率 +10%
    if ctx.param("explore_item_bonus", False):
        bp_chance = bp_chance + (0.10 if race_stats(ctx._focus.get("race")).get("explore_item") else 0)
    if bp_chance and random.random() < bp_chance:
        bp = C.roll_blueprint(max(1, ctx.lv))
        _learned, _bpn, _pages = _add_bp_or_pages(ctx, db, bp)
        if _learned:
            bp_line = (f"\n📜 里面有一张图纸『{_bpn}』——你已经学会了，化作 {_pages} 张图纸残页"
                       f"（『出售 图纸残页』变现）！")
        else:
            bp_line = ctx.param("bp_line", "\n📜 里面还有一张泛黄的图纸：{bp}！").replace("{bp}", _bpn)
    header = ctx.param("header", "💰 获得 {gold} 金币！{mat_line}{bp_line}")
    return header.replace("{name}", ctx.name) \
                 .replace("{gold}", str(gold)) \
                 .replace("{mat_line}", mat_line) \
                 .replace("{bp_line}", bp_line)


@register("exp_gain")
def tpl_exp_gain(ctx):
    """经验 + 升级检查（沿用原 omen 逻辑）。params: min/max/scale_lv/header"""
    db = ctx._db()
    C = ctx._C()
    # 真源此处 `from ..content_rules.gameplay import check_player_level_up`（宿主边界，见头注）
    exp_gain = ctx.param("min", 15) + ctx.lv * ctx.param("scale_lv", 3)
    # v110 审计修复：从 DB 读最新 exp 再累加（防 ctx._focus 陈旧 dict 覆盖吞经验——
    # 与 v109.3 loot_gold 同型），并回写 ctx._focus 引用（#262：战斗结算进度条
    # 显示依赖同一 player dict，保持引用同步）
    cur_exp = int(db.get_player(ctx.group_id, ctx.qq_id).get("exp", 0))
    ctx._focus["exp"] = cur_exp + exp_gain
    db.update_player(ctx.group_id, ctx.qq_id, exp=ctx._focus["exp"])
    player = db.get_player(ctx.group_id, ctx.qq_id)
    player["_title_bonus"] = ctx.hooks.get("title_bonus", lambda q: None)(ctx.qq_id)
    lines = [ctx.param("header", "✨ 经验 +{exp}").replace("{name}", ctx.name).replace("{exp}", str(exp_gain))]
    lv_logs, player = check_player_level_up(ctx.group_id, ctx.qq_id, player)
    if lv_logs:
        lines += [""] + lv_logs
        db.update_player(ctx.group_id, ctx.qq_id, level=player["level"], exp=player["exp"],
                         hp=player["hp"], mp=player["mp"], max_hp=player["max_hp"],
                         max_mp=player["max_mp"], skills=player["skills"],
                         attr_pts=player.get("attr_pts", 0), skill_points=player.get("skill_points", 0),
                         learned_skills=player.get("learned_skills", []))
        # F1 P1-2（report_02）：升级后把最新 level/exp 等同步回调用方 player dict
        # （ctx._focus 与调用方同引用）——否则战斗胜利主流程随后再次 check_player_level_up
        # 会用陈旧 level/exp 重复升级 → 升级公告双打印
        for _k in ("level", "exp", "hp", "mp", "max_hp", "max_mp", "skills",
                   "attr_pts", "skill_points", "learned_skills"):
            ctx._focus[_k] = player.get(_k, ctx._focus.get(_k))
    return "\n".join(lines)


@register("heal_full")
def tpl_heal_full(ctx):
    """回满血蓝。params: header"""
    db = ctx._db()
    db.update_player(ctx.group_id, ctx.qq_id, hp=ctx._focus["max_hp"], mp=ctx._focus["max_mp"])
    header = ctx.param("header", "❤️ 生命全满！💙 魔力全满！")
    return header.replace("{name}", ctx.name)


@register("damage")
def tpl_damage(ctx):
    """扣血（陷阱类）。params: pct/min/header"""
    db = ctx._db()
    dmg = int(ctx._focus["max_hp"] * ctx.param("pct", 0.15)) + ctx.param("min", 5)
    new_hp = max(1, ctx._focus["hp"] - dmg)
    db.update_player(ctx.group_id, ctx.qq_id, hp=new_hp)
    header = ctx.param("header", "你摔伤了，损失 {dmg} 点生命(当前 ❤️ {hp}/{max_hp})")
    return header.replace("{name}", ctx.name) \
                 .replace("{dmg}", str(dmg)) \
                 .replace("{hp}", str(new_hp)) \
                 .replace("{max_hp}", str(ctx._focus["max_hp"]))


@register("set_state")
def tpl_set_state(ctx):
    """写入 event_state。params: key(可含 {gid}/{qid})/value/header
    value 支持特殊值 'ts'（存 {"ts": 当前时间戳}），或 dict / callable(ctx)。"""
    import json, time
    db = ctx._db()
    key = ctx.param("key", "").replace("{gid}", str(ctx.group_id)).replace("{qid}", str(ctx.qq_id))
    value = ctx.param("value", {})
    if value == "ts":
        value = {"ts": time.time()}
    elif callable(value):
        value = value(ctx)
    db.set_event_state(key, json.dumps(value, ensure_ascii=False))
    header = ctx.param("header", "")
    return header.replace("{name}", ctx.name)


@register("set_flag")
def tpl_set_flag(ctx):
    """写入隐藏线 talk_flag。params: flag/key/header"""
    db = ctx._db()
    db.set_talk_flag(ctx.group_id, ctx.qq_id, ctx.param("flag"), ctx.param("key"))
    header = ctx.param("header", "")
    return header.replace("{name}", ctx.name)


@register("dialog")
def tpl_dialog(ctx):
    """纯文案（变体池随机）。params: texts(必填)"""
    texts = ctx.param("texts", [])
    if not texts:
        return ""
    return random.choice(texts).replace("{name}", ctx.name)


@register("mystery_chest")
def tpl_mystery_chest(ctx):
    """神秘宝匣：金币 + 当前地图怪物掉落池随机材料 + 必掉图纸。沿用原逻辑。"""
    import uuid
    db = ctx._db()
    C = ctx._C()
    gold = random.randint(50, 120) + ctx.lv * 5
    gold = int(gold * (ctx.loot_mult or 1.0))  # v115 今日奇遇 loot_mult 倍率
    # v110 审计修复：与 tpl_loot_gold 同型——读 DB 最新 gold 再累加，防 ctx._focus
    # 陈旧 dict 覆盖吞金币（v109.3 P0 同类事故的漏网模板）
    cur = db.get_player(ctx.group_id, ctx.qq_id).get("gold", 0)
    db.update_player(ctx.group_id, ctx.qq_id, gold=cur + gold)
    mat_line = ""
    # v105 M23 P1-4：材料源改当前子区域怪物掉落池（与 combat.py 探索遇怪同源）——
    # v87.6 后怪物全部下沉子区域，地图级 monsters 0/116 全空，原宝匣材料行静默失效（只掉金币+图纸）
    cur_sa_id = ctx._focus.get("cur_subarea") or ""
    mon_src = None
    for _sa in (ctx.cur_map.get("subareas") or []):
        if _sa["id"] == cur_sa_id:
            mon_src = _sa.get("monsters")
            break
    if mon_src is None:
        mon_src = ctx.cur_map.get("monsters", [])
    pool = [m[5] for m in mon_src]
    mats = [x for sub in pool for x in sub if x and "图纸" not in x]
    # v115 今日奇遇：pref_mats 与掉落池有交集时优先抽（交集为空回退原池）
    mats = ctx.mat_choice_pool(mats)
    if mats:
        mid = C.resolve("materials", random.choice(mats))
        if mid in MATERIALS:
            db.add_item(ctx.group_id, ctx.qq_id, mid,
                        {"name": C.display("materials", mid), "type": "材料",
                         "stackable": True, "price": MATERIALS[mid]["price"]})
            mat_line = f"\n🎒 还得到一份材料：{C.display('materials', mid)}！"
    bp = C.roll_blueprint(max(1, ctx.lv))
    _learned, _bpn, _pages = _add_bp_or_pages(ctx, db, bp)
    if _learned:
        bp_txt = (f"📜 里面还有一张图纸『{_bpn}』——你已经学会了，化作 {_pages} 张图纸残页"
                  f"（『出售 图纸残页』变现）！")
    else:
        bp_txt = f"📜 里面还有一张泛黄的图纸：{_bpn}！"
    return (f"📦 【神秘宝匣】你在{ctx.name}的角落发现一只埋藏千年的宝匣！\n"
            f"💰 打开：{gold} 金币！{mat_line}\n"
            f"{bp_txt}")


# ★ tpl_merchant（流浪商人）：**故意留在宿主** `game/core/event_templates.py`
#   理由 = tests/test_v184_loot_tiers.py:690-709 的源码级绑定断言（见本模块头注 ★）。
#   宿主薄壳用本模块的 `register` 把它注册进同一个 `TEMPLATES`（19 键不变）。


@register("wandering")
def tpl_wandering(ctx):
    """迷路的旅人：限一次谢礼。沿用原 wandering 逻辑。"""
    db = ctx._db()
    C = ctx._C()
    player = db.get_player(ctx.group_id, ctx.qq_id)
    if player.get("explore_wandering"):
        return "🧭 【迷路的旅人】旅人认出了你，笑着摆摆手：'缘分到此为止，下次有缘再见！'"
    # v102.2：特殊物品用 key（i_scroll_escape），材料保留中文名（resolve 按名解析）
    rewards = ["克罗的罗盘碎片", "i_scroll_escape", "谷地露水"]
    rw = random.choice(rewards)
    if rw == "i_scroll_escape":
        db.add_item(ctx.group_id, ctx.qq_id, "i_scroll_escape",
                    {"name": "回城卷轴", "type": "消耗品", "stackable": True,
                     "effect": "return_vila", "price": 500})
    else:
        mid = C.resolve("materials", rw)
        if mid in MATERIALS:
            db.add_item(ctx.group_id, ctx.qq_id, mid,
                        {"name": C.display("materials", mid), "type": "材料",
                         "stackable": True, "price": MATERIALS[mid]["price"]})
    db.update_player(ctx.group_id, ctx.qq_id, explore_wandering=1)
    # v105 M23 P3-2：rw 为 key（i_scroll_escape）时原样输出会泄漏内部 ID，改显示中文名
    rw_disp = "回城卷轴" if rw == "i_scroll_escape" else rw
    return (f"🧭 【迷路的旅人】一位旅人感激你的指路，硬塞给你一件谢礼！\n"
            f"🎒 获得：{rw_disp}")


@register("combo")
def tpl_combo(ctx):
    """组合模板：steps 顺序执行，拼接文本。params: steps: [{template, params, header?...}]"""
    lines = []
    for i, step in enumerate(ctx.param("steps", [])):
        sub_params = dict(ctx.params)
        sub_params.update(step.get("params", {}))
        sub_ctx = EventContext(ctx.group_id, ctx.qq_id, ctx._focus, ctx.cur_map,
                               params=sub_params, name=ctx.name, hooks=ctx.hooks)
        fn = TEMPLATES.get(step.get("template"))
        if fn:
            text = fn(sub_ctx)
            if text:
                lines.append(text)
    return "\n".join(lines)


@register("random_choice")
def tpl_random_choice(ctx):
    """v97.4 概率分支：chance 命中执行 hit 子模板，否则 miss。params: chance/hit/miss
    hit/miss 为 {template, params}（与 combo 的 step 同构），支持嵌套。"""
    branch = ctx.param("hit" if random.random() < ctx.param("chance", 0.5) else "miss", None)
    if not branch:
        return ""
    sub_params = dict(ctx.params)
    sub_params.update(branch.get("params", {}))
    sub_ctx = EventContext(ctx.group_id, ctx.qq_id, ctx._focus, ctx.cur_map,
                           params=sub_params, name=ctx.name, hooks=ctx.hooks)
    fn = TEMPLATES.get(branch.get("template"))
    if fn:
        text = fn(sub_ctx)
        return text or ""
    return ""


@register("stamina_cost")
def tpl_stamina_cost(ctx):
    """v97.4 扣体力（浮桥落水等）。params: cost/header
    体力下限 0，上限 100 + lv*2（与 base.py _stamina_max 一致）。"""
    db = ctx._db()
    cost = ctx.param("cost", 5)
    max_st = 100 + ctx.lv * 2
    cur = int(ctx._focus.get("stamina") or 0)
    new = max(0, cur - cost)
    db.update_player(ctx.group_id, ctx.qq_id, stamina=new)
    header = ctx.param("header", "⚡ 体力 -{cost}（当前 ⚡ {stamina}/{max}）")
    return (header.replace("{name}", ctx.name)
                  .replace("{cost}", str(cost))
                  .replace("{stamina}", str(new))
                  .replace("{max}", str(max_st)))


# ============ v115 探索体验扩容：4 个新增模板 ============

@register("region_lore")
def tpl_region_lore(ctx):
    """v115 区域见闻：纯氛围文案 + 记入见闻录 flag。
    params: flag/texts/seen_texts/header（可选）
    首次触发写 event_state lore_{flag}_{qq_id}="1" 并取 texts 一条；
    重复触发（flag 已存在）从 seen_texts（缺省回退 texts）里换一条。
    """
    db = ctx._db()
    key = f"lore_{ctx.param('flag', 'default')}_{ctx.qq_id}"
    seen = bool(db.get_event_state(key))
    if not seen:
        db.set_event_state(key, "1")
    pool = ctx.param("seen_texts") if (seen and ctx.param("seen_texts")) else ctx.param("texts", [])
    if not pool:
        return ""
    return random.choice(pool).replace("{name}", ctx.name)


@register("stamina_gift")
def tpl_stamina_gift(ctx):
    """v115 体力馈赠：随机回复体力 5-10（可自定义 min/max）。
    params: min/max/header
    体力封顶 100 + lv*2（与 base.py _stamina_max 一致）。
    """
    db = ctx._db()
    gain = random.randint(ctx.param("min", 5), ctx.param("max", 10))
    max_st = 100 + ctx.lv * 2
    cur = int(ctx._focus.get("stamina") or 0)
    new = min(max_st, cur + gain)
    if new != cur:
        import time as _time
        db.update_player(ctx.group_id, ctx.qq_id, stamina=new, stamina_ts=int(_time.time()))
        ctx._focus["stamina"] = new  # 同步上下文，避免跨事件陈旧值
    header = ctx.param("header", "⚡ 体力 +{gain}（当前 ⚡ {stamina}/{max}）")
    return (header.replace("{name}", ctx.name)
                  .replace("{gain}", str(new - cur))
                  .replace("{stamina}", str(new))
                  .replace("{max}", str(max_st)))


@register("shrine_bless")
def tpl_shrine_bless(ctx):
    """v115 神龛祝福：写 event_state bless_{qq_id}，下次战斗攻击 +pct%。
    battle.py 现有 echo_bless 机制读键 bless_{qid}（本场攻击 ×1.05，一次性消费）；
    此处复用同款键命名习惯——params: pct/header
    """
    import json as _json
    db = ctx._db()
    pct = ctx.param("pct", 5)
    db.set_event_state(f"bless_{ctx.qq_id}", _json.dumps({"pct": pct}, ensure_ascii=False))
    header = ctx.param("header", "🔮 神龛祝福降临！✨ 下次战斗攻击力 +{pct}% ！")
    return header.replace("{name}", ctx.name).replace("{pct}", str(pct))


@register("rare_find")
def tpl_rare_find(ctx):
    """v115 稀有发现：从 params.mats 稀有材料池随机抽 n 份入包（复用 loot_materials 思路）。
    params: mats/n/header（header 可含 {mats}/{extra} 占位）
    """
    import uuid
    db = ctx._db()
    C = ctx._C()
    mats_pool = ctx.param("mats", ["秘银", "星辉石"])
    n = ctx.param("n", 1)
    got = []
    for _ in range(n):
        m = random.choice(mats_pool)
        mid = C.resolve("materials", m)
        if mid in MATERIALS:
            db.add_item(ctx.group_id, ctx.qq_id, mid,
                        {"name": C.display("materials", mid), "type": "材料",
                         "stackable": True, "price": MATERIALS[mid]["price"]})
            got.append(C.display("materials", mid))
    header = ctx.param("header", "✨ 稀有发现！🎒 获得稀有材料：{mats}！{extra}")
    return (header.replace("{name}", ctx.name)
                  .replace("{mats}", "、".join(got))
                  .replace("{extra}", ""))


def execute_event_template(template_name, ctx):
    """执行模板；未注册返回 None（调用方兜底）。"""
    fn = TEMPLATES.get(template_name)
    if not fn:
        return None
    return fn(ctx)
