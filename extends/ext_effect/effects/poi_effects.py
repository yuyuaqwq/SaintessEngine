# -*- coding: utf-8 -*-
"""《奥兰迪亚》包内 **POI 效果层**（逐字搬自游戏仓 `game/core/poi_effects.py`，469 行）。

真源 `:22-469` 正文（`import json` → `execute_poi`，448 行）**逐字**搬入，只改两类东西：
  ① **import 层**（7 行）：宿主日志层 / 宿主数据域文案池 / 宿主副本运行态 → 调用方接口
  ② **宿主耦合**：写库动作（宿主 `game.db`）与内容域访问（宿主 `game.content` 薄聚合层 C
     / `game.data.pois` 池 / `game.core.instance_run` 名单视图）→ **调用方传入的接口**

生成 / 复核 / 验收
------------------
    PYTHONIOENCODING=utf-8 python overnight/_d3_port_effects.py     # 重新生成（逐字节可重算）
    PYTHONIOENCODING=utf-8 python overnight/d3_effects_verify.py    # 验收（A1 保真 + B/C 真数据对拍）

① import 层改动（逐条见 `overnight/_d3_effects_whitelist.json`）
| 真源写法 | 包内写法 | 说明 |
|---|---|---|
| `from ..log_setup import LOG` + `_logger = LOG`（:26-28） | **不搬** | 宿主日志层；`_logger` 在真源零读点（全文件仅此一处赋值） |
| `from ..data.pois import RUNE_POOL / NOTE_POOL / SIGHT_POOL`（:229 / :262 / :272） | `ctx.dom.pools("<池名>")` | 宿主数据域文案池；包内 `content/data/pois.json` 只有**放置表**（457 条子区域放置 = 世界 POI 名 789 处 + 副本内联 POI 66 处），无文案池 |
| `from . import instance_run as IR`（:385 / :449） | `ctx.dom.living_members / set_alive` | 副本运行态「名单视图」（v185，缺 `alive` 键 = 存活）；包内副本运行态未进包 |

② 宿主耦合替身接口（本文件**零 DB / 零平台 / 零墙上时间**——一律由调用方给对象）
| 真源宿主耦合 | 包内替身 | 调用方给什么 |
|---|---|---|
| `ctx._db()` → `from .. import db`（:78） | **`ctx.host`**（`PoiContext(..., host=…)`） | 写库五动词对象：`update_player(gid, qid, **fields)` · `add_item(gid, qid, iid, item, count=1)` · `set_event_state(k, v)` · `get_event_state(k)` · `set_talk_flag(gid, qid, flag, action)`（真源 = 宿主 `game.db`；live 消费端 = 宿主命令层 `game/commands/combat.py:982 _handle_poi`） |
| `ctx._C()` → `from .. import content as C`（:82） | **`ctx.dom`**（`PoiContext(..., dom=…)`） | 内容域访问：`CAMPFIRE_FOOD_POOL` · `HERB_POOL` · `pools(name)` · `resolve(table, name_or_id)` · `display(table, entity_id)` · `roll_blueprint(lv)` · `generate_equip(slot, lv, quality)` · `living_members(st)` · `set_alive(st, key, value)`（真源 = 宿主 `game.content` + `game.data.pois` + `game.core.instance_run`；文案池/图纸与装备生成器/副本运行态**未进包**）—— ★ B14-2 起 `MATERIALS` 不再走此接口，改包内门面 `catalog_items`（见文末「读点现状」） |
| `ctx.hooks["mark_used"] / ["player"]`（:90 / :96，真源本来就由命令层注入） | **逐字保留**（本来就是调用方接口） | 副本 POI 已使用标记 / 读 DB 最新玩家（命令层 `_mark_poi_used` / `_player`） |

⚠️ 不传 `host` / `dom` = `None`：handler 一旦用到即 **AttributeError（fail-loud）**——
   写库与查表是这层仅有的副作用出口，缺了必须报出来（不静默吞）。

⚠️ 不变式：`group_id` / `qq_id` 只是调用方给的普通字符串键，包内不解析平台语义
   （不认群号 / QQ 号；副本 POI 的 `st` 也是调用方 dict，包内不落盘）。

未搬（真源正文之外 / 不属于效果层）
-----------------------------------
* `from ..log_setup import LOG` + `_logger`（宿主日志层，零读点）
* 消费端 `game/commands/combat.py:_handle_poi`（宿主命令层：探索 15% 触发 / POI 每日重置
  `_poi_daily_used` / 未知 effect 告警文案）—— 本层只出「效果执行」半边，调用方接口已在 ② 列全
* 三张文案池本体 + `game/data/poi_pools.py` 的 `CAMPFIRE_FOOD_POOL` / `HERB_POOL` ——
  数据域导出批的活；本批走调用方接口 `dom.pools(...)` / `dom.CAMPFIRE_FOOD_POOL`

B14-2 读点现状（L4 线；宿主 `game/data` 删掉后本层仍能取值）
-----------------------------------------------------------
★ 2026-09-24 B7a 更新：下面这些「包内门面直取」**已全部改走注入面**
  （`ctx.dom.MATERIALS` / `ctx.dom.CAMPFIRE_FOOD_POOL` / `ctx.dom.HERB_POOL` /
   `ctx.text` / `ctx.static`）—— 本文件现在**零 import 数据包**，可整文件搬进扩展包。
  下方段落保留为**历史谱系**（当时为什么那样切），口径以本行为准。
* **已切包内门面**（真源 = 宿主聚合层同名表）：`from .. import catalog_items as _ci`（正文写
  `ctx.dom.MATERIALS`，6 处调用点：篝火/草药 各 2、副本宝箱 2）。门禁
  `overnight/b14_catalog_gate.py --names MATERIALS,…` 逐名 **OK · 不等 0（含键序）** —— 598 条与
  宿主同名表深比较相等，故 `mid in …` / `["price"]` 的判据与取值一字未变。
* **W5（2026-09-14）收口**：`CAMPFIRE_FOOD_POOL`(4 处) / `HERB_POOL`(5 处) 已切包内门面
  `from .. import catalog_b143 as _b143`（真源 `game/data/poi_pools.py:15/18` → `poi_pools` 域；
  门禁逐名深比较含键序 → **不等 0**；`WISH_POOL` 本层无读点）。
* **仍走调用方接口 `ctx.dom`（函数名缺口，本线不建第二份读口）**：`resolve("materials",…)` ·
  `display("materials",…)` · `roll_blueprint(lv)` · `generate_equip(slot,lv,quality)` ·
  `pools(name)` —— 权威索引在装配期宿主侧，图纸与装备生成器**未进包**
  （真源 `game/data/poi_pools.py` 等）。`:422` 注释里的 `QUALITY`（宿主聚合层同名表）
  也只是注释（该表 B14-B/E 已登记无域）。
"""

import json
import random
import time
import uuid

# ★ 2026-09-24 B7a：本层**不再 import 数据包**（抽包进 `extends/ext_effect/` 的前置）——
#   材料表 / 两个文案池 / 文案表全部改走**调用方注入**：`ctx.dom.MATERIALS` ·
#   `ctx.dom.CAMPFIRE_FOOD_POOL` · `ctx.dom.HERB_POOL` · `ctx.text(...)` · `ctx.static(...)`。
#   （替换口径：原 `_ci.MATERIALS` 7 点 / `_b143.*` 2 点 / `_T.text|static` 34 点，逐点同名等价；
#     取件对象由调用方 `content/combat_cmds.py::_PoiDom` 与 ctx 构造处给，数据源一字未换。）
# ⚠️ 真源 `from ..log_setup import LOG` + `_logger = LOG` **不搬**：宿主日志层，
#    且 `_logger` 在真源里零读点（全文件仅此一处赋值）。

POI_EFFECTS = {}


def register(name):
    """POI 效果注册装饰器。"""
    def deco(fn):
        POI_EFFECTS[name] = fn
        return fn
    return deco


class PoiContext:
    """POI 效果执行上下文（世界/副本 POI 共用）。"""

    def __init__(self, group_id, qq_id, player, cur_map, poi_id, poi,
                 st=None, hooks=None, host=None, dom=None, text=None, static=None):
        self.group_id = group_id
        self.qq_id = qq_id
        self._focus = player    # 世界 POI：DB 玩家 dict（快照）；副本 POI：队长玩家 dict
        self.cur_map = cur_map  # 世界 POI：地图 dict；副本 POI：stage dict
        self.poi_id = poi_id
        self.poi = poi
        self.st = st            # 副本 POI：副本战斗状态（stage_idx/players/alive/members）
        self.hooks = hooks or {}
        # ⚠️ 宿主耦合替身（真源没有这两个参数——`_db()`/`_C()` 直接延迟导入宿主模块）：
        #    host ↔ 宿主 `game.db`（写库五动词，见文件头 ②）；dom ↔ 宿主内容域访问。
        #    不传 = None：handler 一旦用到即 AttributeError（fail-loud，不静默吞）。
        self.host = host
        self.dom = dom
        # ★ 2026-09-24 B7a：文案注入句柄（本层不 import 包内文案表）——
        #   与 host/dom 同款 fail-loud：不传 = None，一旦用到就 AttributeError（见下面属性）。
        self._text = text
        self._static = static

    # ---- 注入句柄（文案）----
    @property
    def text(self):
        """文案渲染（带槽位）：由调用方注入（真源 = 包内 `content/texts.py::text`）。

        不传 ⇒ AttributeError（fail-loud）—— 与 `host` / `dom` 同口径：这层仅有的三个
        「读」出口缺一个都必须当场报出来，不静默吞。
        """
        if self._text is None:
            raise AttributeError("POI 文案注入面缺失：请用 PoiContext(..., text=<texts.text>) 构造")
        return self._text

    @property
    def static(self):
        """文案渲染（无槽位）：由调用方注入（真源 = 包内 `content/texts.py::static`）。"""
        if self._static is None:
            raise AttributeError("POI 文案注入面缺失：请用 PoiContext(..., static=<texts.static>) 构造")
        return self._static

    # ---- 便捷访问 ----
    @property
    def icon(self):
        return self.poi.get("icon", "🌿")

    @property
    def pname(self):
        return self.poi.get("name", "探索点")

    @property
    def loc(self):
        """世界 POI 展示地名：地图名·子区域名（无子区域则仅地图名）。"""
        cur_map = self.cur_map or {}
        name = cur_map.get("name", "此地")
        sub_name = ""
        cur_sa_id = (self._focus or {}).get("cur_subarea") or ""
        for _sa in (cur_map.get("subareas") or []):
            if _sa["id"] == cur_sa_id:
                sub_name = _sa.get("name", "")
                break
        return f"{name}·{sub_name}" if sub_name else name

    def _db(self):
        """宿主存储层替身（真源 `from .. import db` —— 延迟导入宿主模块）。

        = 调用方传入的 `host`（写库五动词：update_player / add_item /
        set_event_state / get_event_state / set_talk_flag）。真源那个宿主模块
        在包内不存在，**写库动作全部改走调用方接口**（见文件头 ②）。
        """
        return self.host

    def _C(self):
        """内容域访问替身（真源 `from .. import content as C` —— 宿主薄聚合层 C）。

        = 调用方传入的 `dom`（*_POOL / pools / resolve / display /
        roll_blueprint / generate_equip）。包内尚未导出这些域（文案池 / 图纸与装备
        生成器），一律走调用方接口（见文件头 ②）。★ B14-2 起 `MATERIALS` 不走这里，
        改包内门面 `content/catalog_items.py`（见文末读点现状）。
        """
        return self.dom

    # ---- 副本 POI 辅助 ----
    @property
    def sidx(self):
        return (self.st or {}).get("stage_idx", 0)

    def mark_used(self, poi_id=None):
        """标记副本 POI 已使用（命令层 _mark_poi_used 经 hooks 注入）。"""
        fn = self.hooks.get("mark_used")
        if fn:
            fn(self.st, self.sidx, poi_id or self.poi_id)

    def db_player(self):
        """读 DB 最新玩家（命令层 _player 经 hooks 注入，副本 chest 发金币用）。"""
        fn = self.hooks.get("player")
        if fn:
            return fn(self.group_id, self.qq_id)
        return None


# ================= 世界 POI（effect 键） =================

@register("recover")
def poi_recover(ctx):
    """篝火：恢复 30% 生命/魔力 + 随机烹饪食材。"""
    db = ctx._db()
    C = ctx._C()
    player = ctx._focus
    hp_gain = int(player["max_hp"] * 0.30)
    mp_gain = int(player["max_mp"] * 0.30)
    db.update_player(ctx.group_id, ctx.qq_id,
                     hp=min(player["max_hp"], player["hp"] + hp_gain),
                     mp=min(player["max_mp"], player["mp"] + mp_gain))
    # v101.4：篝火食材池数据化 → data/poi_pools.py CAMPFIRE_FOOD_POOL
    fd = random.choice(ctx.dom.CAMPFIRE_FOOD_POOL)
    mid = C.resolve("materials", fd)
    got = ""
    if mid in ctx.dom.MATERIALS:
        db.add_item(ctx.group_id, ctx.qq_id, mid,
                    {"name": C.display("materials", mid), "type": "材料",
                     "stackable": True, "price": ctx.dom.MATERIALS[mid]["price"]})
        got = C.display("materials", mid)
    return (ctx.text("poi.recover", icon=ctx.icon, name=ctx.pname, loc=ctx.loc, hp=hp_gain, mp=mp_gain,
                item=got))


@register("buff")
def poi_buff(ctx):
    """神龛/祭坛：随机 buff（攻击/防御/速度 +10% 持续 5 次战斗）。"""
    db = ctx._db()
    buffs = [("攻击", "atk"), ("防御", "def"), ("速度", "spd")]
    bname, bkey = random.choice(buffs)
    # v104 M23 修复只写不读：battle.py 战斗开始时读取（玩家级键 poi_buff_{qq_id}——
    # battle 无 group_id 上下文，与 echo_bless bless_{qq_id} 同款全局键），
    # 应用 mult 并递减 left，用完删除 key
    db.set_event_state(f"poi_buff_{ctx.qq_id}",
                       json.dumps({"stat": bkey, "mult": 1.10, "left": 5, "name": bname},
                                  ensure_ascii=False))
    return (ctx.text("poi.buff", icon=ctx.icon, name=ctx.pname, loc=ctx.loc, buff=bname))


@register("merchant")
def poi_merchant(ctx):
    """v115 行商营地：随机金币（图等级×5~×10）或一张图纸（简化版，不做强卖流程）。"""
    db = ctx._db()
    C = ctx._C()
    player = ctx._focus
    map_lv = (ctx.cur_map or {}).get("lv", 1)
    if random.random() < 0.5:
        gold = random.randint(map_lv * 5, map_lv * 10)
        db.update_player(ctx.group_id, ctx.qq_id, gold=player["gold"] + gold)
        return (ctx.text("poi.merchant_gold", icon=ctx.icon, name=ctx.pname, loc=ctx.loc, gold=gold, lv=map_lv))
    bp = C.roll_blueprint(max(1, player["level"]))
    _learned = player.get("learned_blueprints") or []
    if bp.get("blueprint_for") in _learned:
        _bpq = bp.get("quality", "white")
        _pages = {"white": 1, "green": 1, "blue": 2, "purple": 4, "orange": 6}.get(_bpq, 1)
        db.add_item(ctx.group_id, ctx.qq_id, "mat_tu_zhi_can_ye", {
            "name": "图纸残页", "type": "材料", "stackable": True, "price": 10}, count=_pages)
        return (ctx.text("poi.merchant_learned", icon=ctx.icon, name=ctx.pname, bp=bp['name'], pages=_pages))
    db.add_item(ctx.group_id, ctx.qq_id, f"eq_{uuid.uuid4().hex[:8]}", bp)
    return (ctx.text("poi.merchant_blueprint", icon=ctx.icon, name=ctx.pname, bp=bp['name']))


@register("herb")
def poi_herb(ctx):
    """草药丛/鸟巢：1-2 份炼金材料。"""
    db = ctx._db()
    C = ctx._C()
    got = []
    for _ in range(random.randint(1, 2)):
        h = random.choice(ctx.dom.HERB_POOL)  # v101.4：草药丛材料池数据化 → data/poi_pools.py HERB_POOL
        mid = C.resolve("materials", h)
        if mid in ctx.dom.MATERIALS:
            db.add_item(ctx.group_id, ctx.qq_id, mid,
                        {"name": C.display("materials", mid), "type": "材料",
                         "stackable": True, "price": ctx.dom.MATERIALS[mid]["price"]})
            got.append(C.display("materials", mid))
    return (ctx.text("poi.herb", icon=ctx.icon, name=ctx.pname, loc=ctx.loc, got='、'.join(got)))


@register("loot")
def poi_loot(ctx):
    """可疑包裹/龙骸/沉船：金币 / 图纸 / 陷阱（扣血）。"""
    db = ctx._db()
    C = ctx._C()
    player = ctx._focus
    r = random.random()
    if r < 0.6:
        gold = random.randint(20, 80) + player["level"] * 3
        db.update_player(ctx.group_id, ctx.qq_id, gold=player["gold"] + gold)
        return (ctx.text("poi.loot_gold", icon=ctx.icon, name=ctx.pname, loc=ctx.loc, gold=gold))
    if r < 0.85:
        bp = C.roll_blueprint(max(1, player["level"]))
        # v101.25 #293：探索掉落已学图纸不再重复入包——与战斗掉落同款折算
        _learned = player.get("learned_blueprints") or []
        if bp.get("blueprint_for") in _learned:
            _bpq = bp.get("quality", "white")
            _pages = {"white": 1, "green": 1, "blue": 2, "purple": 4, "orange": 6}.get(_bpq, 1)
            db.add_item(ctx.group_id, ctx.qq_id, "mat_tu_zhi_can_ye", {
                "name": "图纸残页", "type": "材料", "stackable": True, "price": 10}, count=_pages)
            return (ctx.text("poi.loot_learned", icon=ctx.icon, name=ctx.pname, bp=bp['name'], pages=_pages))
        db.add_item(ctx.group_id, ctx.qq_id, f"eq_{uuid.uuid4().hex[:8]}", bp)
        return (ctx.text("poi.loot_blueprint", icon=ctx.icon, name=ctx.pname, bp=bp['name']))
    dmg = int(player["max_hp"] * 0.10) + 5
    new_hp = max(1, player["hp"] - dmg)
    db.update_player(ctx.group_id, ctx.qq_id, hp=new_hp)
    # #256: 陷阱触发文案带先兆（包裹缝隙的寒光）——此前无任何提示直接扣血
    return (ctx.text("poi.loot_trap", name=ctx.pname, dmg=dmg, hp=new_hp, max_hp=player['max_hp']))


@register("rune")
def poi_rune(ctx):
    """符文石：图鉴/隐藏线索。"""
    db = ctx._db()
    # 真源 `from ..data.pois import RUNE_POOL`（宿主数据域）→ 调用方接口 dom
    txt = random.choice(ctx.dom.pools("RUNE_POOL"))
    db.set_talk_flag(ctx.group_id, ctx.qq_id, "poi_rune_read", "read_rune")
    return (ctx.text("poi.rune", icon=ctx.icon, name=ctx.pname, loc=ctx.loc, txt=txt))


@register("fish")
def poi_fish(ctx):
    """鱼群聚集：免费垂钓次数（v104 M23 消费契约——垂钓命令读取方：
    key poi_fish_{gid}_{qid}，value {"ts": float, "window": 1800}，
    ts 在 1800s 窗口内 → 免冷却/免体力垂钓一次并删除该 key）。"""
    db = ctx._db()
    db.set_event_state(f"poi_fish_{ctx.group_id}_{ctx.qq_id}",
                       json.dumps({"ts": time.time(), "window": 1800}))
    return (ctx.text("poi.fish", icon=ctx.icon, name=ctx.pname, loc=ctx.loc))


@register("note")
def poi_note(ctx):
    """神秘字条：隐藏线索；traveler_grave 特例（见闻 flag，区分首祭/再经）。"""
    db = ctx._db()
    # v115 旅者之墓：见闻 flag（grave_<map>_<qid>）
    if ctx.poi_id == "traveler_grave":
        _gkey = f"grave_{(ctx.cur_map or {}).get('id', '')}_{ctx.qq_id}"
        if not db.get_event_state(_gkey):
            db.set_event_state(_gkey, "1")
            return (ctx.text("poi.grave_first", icon=ctx.icon, name=ctx.pname, loc=ctx.loc,
                        player=ctx._focus['name']))
        return (ctx.text("poi.grave_again", icon=ctx.icon, name=ctx.pname, loc=ctx.loc))
    # 真源 `from ..data.pois import NOTE_POOL`（宿主数据域）→ 调用方接口 dom
    txt = random.choice(ctx.dom.pools("NOTE_POOL"))
    db.set_talk_flag(ctx.group_id, ctx.qq_id, "poi_note_found", "found_note")
    return (ctx.text("poi.note", icon=ctx.icon, name=ctx.pname, loc=ctx.loc, txt=txt))


@register("sight")
def poi_sight(ctx):
    """v87.9 风景 POI：纯氛围观景（无数值收益）。"""
    # 真源 `from ..data.pois import SIGHT_POOL`（宿主数据域）→ 调用方接口 dom
    txt = random.choice(ctx.dom.pools("SIGHT_POOL"))
    return (ctx.text("poi.sight", icon=ctx.icon, name=ctx.pname, loc=ctx.loc, txt=txt))


# ================= 副本内联 POI（inst:<type> 键） =================

def _need_block(ctx):
    """副本 POI 前置条件（need）：未满足返回锁定文案，否则 None。"""
    need = ctx.poi.get("need") or {}
    if need:
        unlocks = (ctx.st or {}).get("poi_unlocks", {})
        if need.get("poi_read") and not unlocks.get(need["poi_read"]):
            return ctx.text("poi.locked_clue", name=ctx.pname)
        if need.get("unlock") and not unlocks.get(need["unlock"]):
            return ctx.text("poi.locked_item", name=ctx.pname)
    return None


def _act_flag(key):
    """子键动作工厂：置位 st[key] = True。"""
    def act(st, eff):
        st[key] = True
    return act


def _act_unlock(st, eff):
    """子键动作：poi_unlocks[eff.unlock] = True。"""
    st.setdefault("poi_unlocks", {})[eff["unlock"]] = True


def _act_avoid_trap(st, eff):
    """子键动作：poi_unlocks[avoid_<id>] = True。"""
    st.setdefault("poi_unlocks", {})[f"avoid_{eff['avoid_trap']}"] = True


# 机关 effect 子键分发表（数据声明）：{子键: (动作函数, 文案 key)}
# ★ 2026-09-19（C 档另案）：值由「播报文案」改为**文案 key** —— 本表在模块级（import 期），
#   若此处直接 `ctx.static(...)` 会把文案在 import 期定稿、`texts.reload()` 热更失效；
#   故改「dict 存 key、调用点 `logs.append(ctx.static(line))` 渲染」（渲染发生在运行时）。
_MECHANISM_ACTIONS = {
    "open_secret": (_act_flag("stage_secret_found"), "poi.mech_open_secret"),
    "skip_elite": (_act_flag("skip_elite_next"), "poi.mech_skip_elite"),
    "skip_wave": (_act_flag("skip_wave_next"), "poi.mech_skip_wave"),
    "unlock": (_act_unlock, "poi.mech_unlock"),
}

# 石碑 effect 子键分发表（数据声明）：{子键: (动作函数, 文案 key)}（同 _MECHANISM_ACTIONS 口径）
_RUNE_STONE_ACTIONS = {
    "unlock": (_act_unlock, "poi.rune_unlock"),
    "avoid_trap": (_act_avoid_trap, "poi.rune_avoid_trap"),
    "boss_buff": (_act_flag("boss_buff_next"), "poi.rune_boss_buff"),
}


@register("inst:chest")
@register("inst:supply")
@register("inst:corpse")
def inst_loot(ctx):
    """宝箱 / 补给 / 遗骸：给 loot（金币 + 材料；v168 起约 12% 额外翻出白/绿/蓝低品质装备）。"""
    db = ctx._db()
    C = ctx._C()
    block = _need_block(ctx)
    if block:
        return block
    logs = []
    loot = ctx.poi.get("loot") or {}
    gold = loot.get("gold", 0)
    mats = loot.get("materials") or []
    p = ctx.db_player()
    if gold > 0 and p:
        db.update_player(ctx.group_id, ctx.qq_id, gold=p["gold"] + gold)
        logs.append(ctx.text("poi.inst_gold", name=ctx.pname, gold=gold))
    for mn in mats:
        mid = C.resolve("materials", mn)
        if mid in ctx.dom.MATERIALS:
            mname = C.display("materials", mid)
            db.add_item(ctx.group_id, ctx.qq_id, mid, {
                "name": mname, "type": "材料", "stackable": True,
                "price": ctx.dom.MATERIALS[mid]["price"],
            })
            logs.append(ctx.text("poi.inst_pickup", item=mname))
    # v168 副本宝箱低品质装备档（鱼鱼拍板：非 Boss 房宝箱也开得出装备，不再只有图纸）：
    # 副本房间内宝箱/补给/遗骸约 12% 概率额外翻出一件装备——先 roll 品质
    # （白 40% / 绿 35% / 蓝 25%，仅低品质三档），再按玩家等级就近随机部位生成
    # （lv = 玩家等级 ±3，clamp 到 [1, ∞)，贴合当前等级养成；只吃 1 次 random，
    # 不影响 inst_loot 其余随机序列）。命中不额外占副本 stage 事件，仍只 mark_used 一次。
    if random.random() < 0.12:
        _q_roll = random.random()
        if _q_roll < 0.40:
            _eq_q = "white"
        elif _q_roll < 0.75:
            _eq_q = "green"
        else:
            _eq_q = "blue"
        _slot = random.choice(["weapon", "helm", "armor", "legs", "boots", "ring", "necklace"])
        _lv = max(1, (ctx._focus or {}).get("level", 1) + random.randint(-3, 3))
        eq = C.generate_equip(_slot, _lv, _eq_q)
        db.add_item(ctx.group_id, ctx.qq_id, f"eq_{uuid.uuid4().hex[:8]}", eq)
        # 白 🎒 / 绿 🟢 / 蓝 🔵：品质色块 + 装备名（与 QUALITY 档位色一致 —— 宿主聚合层同名表）
        _emoji = {"white": "🎒", "green": "🟢", "blue": "🔵"}.get(eq.get("quality", "white"), "🎒")
        logs.append(ctx.text("poi.inst_equip", emoji=_emoji, name=ctx.pname, equip=eq['name']))
    ctx.mark_used()
    head = ctx.text("poi.inst_corpse_head", name=ctx.pname) if ctx.poi.get("type") == "corpse" else f"📦 {ctx.pname}："
    return "\n".join([head] + logs)


@register("inst:campfire")
def inst_campfire(ctx):
    """副本篝火：全队回血（heal_pct 消费 POI effect 配置，缺省 0.2）。"""
    block = _need_block(ctx)
    if block:
        return block
    logs = []
    st = ctx.st
    # v185：名单视图（存活者；缺 alive 键 = 存活）——真源 `from . import instance_run as IR`，
    # 包内副本运行态未进包 → 走调用方接口 ctx.dom（见文件头 ②）
    for m in ctx.dom.living_members(st):
        snap = st["players"].get(str(m), {})
        if snap.get("hp") is not None:
            # R3 P3-3：heal_pct 消费 POI effect 配置（instance_stage_maps.py
            # 篝火 heal_pct: 0.2 此前是死配置，硬编码 0.2 未来调参会脱钩）
            _pct = (ctx.poi.get("effect") or {}).get("heal_pct", 0.2)
            heal = max(1, int(snap.get("max_hp", snap["hp"]) * _pct))
            snap["hp"] = min(snap.get("max_hp", snap["hp"]), snap["hp"] + heal)
            logs.append(ctx.text("poi.inst_campfire", name=snap.get('name', m), poi=ctx.pname, heal=heal))
    ctx.mark_used()
    return "\n".join(logs)


@register("inst:rune_stone")
def inst_rune_stone(ctx):
    """副本石碑：读 lore（可反复读，不标 used）；effect 子键解锁/避陷阱/Boss 祝福。"""
    logs = []
    st = ctx.st
    lore = ctx.poi.get("lore", ctx.static("poi.rune_lore_default"))
    logs.append(ctx.text("poi.inst_rune_read", name=ctx.pname))
    logs.append(f"  “{lore}”")
    eff = ctx.poi.get("effect") or {}
    # R3 P1-1：读取石碑即记录自身 poi id——need.poi_read 机关（旧王陵王座机关
    # /龙之墓暗门机关）依赖此标记解锁；此前只写 effect.unlock，无 unlock 的
    # 石碑（如墓志铭石碑）永远无法解锁 poi_read 机关
    st.setdefault("poi_unlocks", {})[ctx.poi_id] = True
    for key, (act, line) in _RUNE_STONE_ACTIONS.items():
        if eff.get(key):
            act(st, eff)
            logs.append(ctx.static(line))
    return "\n".join(logs)


@register("inst:mechanism")
def inst_mechanism(ctx):
    """副本机关：desc + effect 子键（开隐藏房/跳精英/减波次/解锁）。"""
    block = _need_block(ctx)
    if block:
        return block
    logs = []
    st = ctx.st
    desc = ctx.poi.get("desc", ctx.text("poi.inst_mech_desc", name=ctx.pname))
    logs.append(f"⚙️ {desc}")
    eff = ctx.poi.get("effect") or {}
    for key, (act, line) in _MECHANISM_ACTIONS.items():
        if eff.get(key):
            act(st, eff)
            logs.append(ctx.static(line))
    ctx.mark_used()
    return "\n".join(logs)


@register("inst:trap")
def inst_trap(ctx):
    """副本陷阱：可拆解（有石碑线索 avoid_<id>）或全队受伤 10% 最大生命。"""
    block = _need_block(ctx)
    if block:
        return block
    st = ctx.st
    if st.get("poi_unlocks", {}).get(f"avoid_{ctx.poi_id}"):
        ctx.mark_used()
        return ctx.text("poi.trap_disarmed", name=ctx.pname)
    logs = [ctx.text("poi.trap_triggered", name=ctx.pname)]
    # v185：名单视图（存活者；缺 alive 键 = 存活）——真源 `from . import instance_run as IR`，
    # 包内副本运行态未进包 → 走调用方接口 ctx.dom（见文件头 ②）
    for m in ctx.dom.living_members(st):
        snap = st["players"].get(str(m), {})
        if snap.get("hp") is not None:
            dmg = max(1, int(snap.get("max_hp", snap["hp"]) * 0.1))
            snap["hp"] = max(0, snap["hp"] - dmg)
            if snap["hp"] <= 0:
                ctx.dom.set_alive(st, m, False)
                logs.append(ctx.text("poi.trap_down", name=snap.get('name', m)))
            else:
                logs.append(ctx.text("poi.trap_hp", name=snap.get('name', m), hp=snap['hp'], max_hp=snap['max_hp']))
    ctx.mark_used()
    return "\n".join(logs)


def execute_poi(effect_name, ctx):
    """执行 POI 效果；未注册返回 None（调用方显式告警，不再静默 fallback）。"""
    fn = POI_EFFECTS.get(effect_name)
    if not fn:
        return None
    return fn(ctx)


__all__ = [
    "POI_EFFECTS", "register", "PoiContext", "execute_poi",
]
