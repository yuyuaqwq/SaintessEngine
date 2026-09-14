# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— 成就条件注册表（B13-L4，2026-09-14）。

真源：游戏仓 `game/core/achievement_conds.py`（497 行 / v99.5 起）。本模块 = 那份文件的
**实现本体**（逐字搬：47 个条件类型注册、函数体、注释一字未改）。宿主 `game/core/achievement_conds.py`
现在只剩「加载包 + 同名单 re-export」，符号名 / 签名不变（`COND_CHECKS` / `register` / 各 `_c_*`）。

正文改动面（只有三类，替换表见 `overnight/w1213_b13l4_port.py`，每条都断言出现次数）
--------------------------------------------------------------------------------------
1. 宿主取件 → 惰性替身（同位置、调用时解析）：函数内 `from .. import content as C` /
   `from .. import db` 删除，改模块级 `C = _HostMod("content")` / `db = _HostMod("db")`；
   `from ..data.equip_roster import EQUIP_ROSTER` / `from ..data.hidden_monsters import
   HIDDEN_MONSTERS` / `from ..data import MAIN_QUESTS` → `_host_attr(...)`。
   ★ W6（2026-09-14）：上面这**三张数据表**改门面直取（宿主 `game/data` 删后本模块仍能活）——
   `EQUIP_ROSTER` → `catalog_items`（687 条，已剥导出期注入字段）、`HIDDEN_MONSTERS` →
   `catalog_b143`（`game_config.hidden_monsters`）、`MAIN_QUESTS` → `catalog_quests`（70 条，
   含键序）；门禁 `--names EQUIP_ROSTER,HIDDEN_MONSTERS,MAIN_QUESTS` 逐名 OK · 不等 0。
   切后 `_host_attr` 只剩函数 / 单例句柄（本线无）。
2. 包内直取（**本线模块**）：`from .achievements import _bestiary_kills / _monster_total`
   原样保留（真源也是函数内延迟 import，包内同样延迟 → 不成环）。
3. 读点切包内域读口（I1）：`C.PLAYER_SKILLS` / `C.BRANCH_SKILLS` → `from .skills import …`
   （实测与宿主 `C.PLAYER_SKILLS` / `C.BRANCH_SKILLS` **深等**，见报告步骤 A·5）。

⚠️ 读点现状（B14-2 · W6，2026-09-14）
  · 已切包内门面：`C.MAPS` → `content/catalog_space.py:MAPS`（门禁逐名 OK · 不等 0，含键序；
    `hidden` / `type` 字段实测保留 → 隐藏区域集合与切前逐元素相同：`lost_library` /
    `ember_corridor`）—— B13-L4 时期「maps 域是 nodes/roles 投影」的判断已随 B14-A 重造
    MAPS 失效；
  · W6：`C.HIDDEN_MAP_UNLOCK` → 门面 `content/catalog_b143.py:HIDDEN_MAP_UNLOCK`（B14-3 新建
    `game_config.maps` 域，外层键序由 `_ORDER_HIDDEN_MAP_UNLOCK` 还原；门禁
    `b14_catalog_gate.py --names HIDDEN_MAP_UNLOCK` → 不等 0），取值仍保留 `or {}` 兜底；
  · `C.display("skills", …)`（`_c_skill_has`）：宿主 `C.display` 走 `_INDEXES`（17 张表、
    `skills` 67 条、`monsters` 354 条），包内 `content/tables.display` 只认 classes/skills
    两个表名 → 两者**不同义**，本线两个模块统一保留宿主句柄（同函数在 achievements 里以
    `C.display("monsters", …)` 形态出现，单点切换会出现同名函数两种取数口；**函数名句柄不切**）。

真源原文头注（逐字保留）
------------------------
    奥兰迪亚·余烬纪年核心层 - achievement_conds.py（v99.5：成就条件注册表）
    
    消灭 core/achievements.py cond_met() 的 41 种类型 if 硬编码：
    成就数据只声明 cond={"type": ..., "value": ...}，判定统一走本模块注册表。
    
    扩展方式：
    - 加成就条件类型：register 一个函数（~5 行），之后成就数据直接可用
    - 函数签名：fn(player, stats, profs, extra, cond) -> bool
      player 玩家 dict / stats 统计 dict / profs 副业 dict / extra 事件上下文 / cond 条件 dict
    - 未知 type / 异常 → False（与旧 if 链兜底一致，由调用方 cond_met 统一 try/except）
    
    约定：
    - db 访问在函数内延迟 import（防 core→content→core 循环）
    - v105 M18 P1 修复：main_done 补 group_id（原 TypeError 恒 False）；flag 改查 db
      talk_flags（原 extra.flags 无调用方传参恒 False）；event_all 接 stats.world_events；
      goblin_trade 无交易计数数据源 → 成就 ach_goblin_friend 改判 world_event（注册已删除）；
      hidden_area 改统计真实隐藏区域（HIDDEN_MAP_UNLOCK∪hidden 标记地图），普通区域到访不再计数
      （原与 visited 实现完全相同，ach_mythril/ach_hidden3 被普通区域误解锁）
    - quest_done/item_has/main_quest_done/branch_skills 依赖 extra._group_id（check_achievements 注入）"""

from __future__ import annotations

import importlib
import sys


# ============================================================
# 宿主替身口（**惰性**：属性访问时才解析宿主模块；绝不 import 宿主模块树、绝不静默空跑）
# 真源写法 → 包内替身：`from .. import content as C` → `C = _HostMod("content")`；
# `from .. import db` → `db = _HostMod("db")`。函数内那几行 import 已按原位置删除，
# 所有调用点 `C.xxx` / `db.xxx` **一行未改**（与 `content/world_cmds.py` / `talk_actions.py` 同款）。
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
    raise RuntimeError("%s：宿主模块 %s 取不到（%s）——拒绝静默空跑" % (__name__, name, last))


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


C = _HostMod("content")     # 真源 `from .. import content as C`
from ._pkgref import DB as db

from .skills import PLAYER_SKILLS, BRANCH_SKILLS   # 包内读口（实测与宿主深等）
from .catalog_space import MAPS                    # B14-2：真源 `C.MAPS`（门禁 OK，含键序）
from .catalog_b143 import HIDDEN_MAP_UNLOCK        # W6：真源 `C.HIDDEN_MAP_UNLOCK`（门禁 OK，含键序）
from .catalog_b143 import HIDDEN_MONSTERS          # W6：真源 `_host_attr("data.hidden_monsters", …)`（门禁 OK）
from .catalog_items import EQUIP_ROSTER            # W6：真源 `_host_attr("data.equip_roster", …)`（门禁 OK）
from .catalog_quests import MAIN_QUESTS            # W6：真源 `_host_attr("data", …)`（门禁 OK，含键序）

COND_CHECKS = {}


def register(key):
    """条件注册装饰器。"""
    def deco(fn):
        COND_CHECKS[key] = fn
        return fn
    return deco


def _value(cond):
    return cond.get("value", 0)


# ================= 角色成长类 =================

@register("registered")
def _c_registered(player, stats, profs, extra, cond):
    """已注册角色"""
    return bool(player)


@register("level")
def _c_level(player, stats, profs, extra, cond):
    """达到等级"""
    return player.get("level", 0) >= _value(cond)


@register("evolve")
def _c_evolve(player, stats, profs, extra, cond):
    """转职阶数（v110 审计修复：原判 evolve_path——该字段只存分支序号(1/2)，
    导致 ach_evolve3 永不可达、ach_evolve2 被 30 级一转防御分支误解锁；
    改判 class_tier 档位（1/2/3 = 一/二/三转），隐藏线 60/75/90 档同步成立）"""
    return player.get("class_tier", 0) >= _value(cond)


@register("learned")
def _c_learned(player, stats, profs, extra, cond):
    """学习技能数"""
    return len(player.get("learned_skills", []) or []) >= _value(cond)


@register("learned_all")
def _c_learned_all(player, stats, profs, extra, cond):
    """学完全职业技能"""
    total = 0
    cls = player.get("class_name", "")
    t1 = PLAYER_SKILLS.get(cls, {})          # ← 包内读口（content/skills.py，实测深等）
    if isinstance(t1, dict) and "skills" in t1:
        total += len(t1["skills"])
    bt = BRANCH_SKILLS.get(cls, {})          # ← 包内读口（content/skills.py，实测深等）
    if isinstance(bt, dict) and "branches" in bt:
        for tier in bt["branches"].values():
            for skills in tier.values():
                total += len(skills)
    return total > 0 and len(player.get("learned_skills", []) or []) >= total


@register("skill_has")
def _c_skill_has(player, stats, profs, extra, cond):
    """习得指定关键词技能"""
    learned = [C.display("skills", s) for s in (player.get("learned_skills", []) or []) if s]
    return any(cond.get("keyword", "") in s for s in learned)


@register("branch_skills")
def _c_branch_skills(player, stats, profs, extra, cond):
    """掌握分支技能数（v105 M18 P1-3 新增：原 ach_dragon_skill 查'龙语'技能，全库无 → 恒 False）
    分支技能以中文名为 key（skills.py BRANCH_SKILLS），learned_skills 中分支技能存中文名
    （_skill_learn_msg/_evolve_auto_skills 均追加 name），统计 learned ∩ 本职业分支技能名。"""
    cls = player.get("class_name", "")
    bt = BRANCH_SKILLS.get(cls, {})          # ← 包内读口（content/skills.py，实测深等）
    if not isinstance(bt, dict):
        return False
    names = set()
    for tier in (bt.get("branches") or {}).values():
        for skills in tier.values():
            if not isinstance(skills, dict):
                continue
            names.update(skills.keys())
            for s in skills.values():
                if isinstance(s, dict) and s.get("name"):
                    names.add(s["name"])
    if not names:
        return False
    learned = set(player.get("learned_skills", []) or [])
    return len(learned & names) >= _value(cond)


@register("hidden_class")
def _c_hidden_class(player, stats, profs, extra, cond):
    """解锁隐藏职业"""
    return cond.get("key") in (player or {}).get("hidden_class_unlock", [])


@register("hidden_class_lv")
def _c_hidden_class_lv(player, stats, profs, extra, cond):
    """隐藏职业达到等级"""
    return (player or {}).get("class_name") == cond.get("key") and (player or {}).get("level", 0) >= cond.get("value", 0)


# ================= 战斗统计类 =================

@register("kills")
def _c_kills(player, stats, profs, extra, cond):
    """击杀数（no_death 时要求零死亡）"""
    if cond.get("no_death"):
        return stats.get("kills", 0) >= _value(cond) and stats.get("deaths", 0) == 0
    return stats.get("kills", 0) >= _value(cond)


@register("elite")
def _c_elite(player, stats, profs, extra, cond):
    """精英击杀数"""
    return stats.get("elite_kills", 0) >= _value(cond)


@register("boss")
def _c_boss(player, stats, profs, extra, cond):
    """Boss 击杀数"""
    return stats.get("boss_kills", 0) >= _value(cond)


@register("kills_type")
def _c_kills_type(player, stats, profs, extra, cond):
    """指定怪物类型击杀"""
    from .achievements import _bestiary_kills  # 延迟引用（运行时 achievements 已加载）
    kws = cond.get("keywords") or [cond["keyword"]]
    return any(_bestiary_kills(player["qq_id"], kw) >= _value(cond) for kw in kws)


# ================= 副业/养成类 =================

@register("prof_lv")
def _c_prof_lv(player, stats, profs, extra, cond):
    """副业等级"""
    p = (profs or {}).get(cond["key"], {})
    return int(p.get("lv", 0) or 0) >= _value(cond)


@register("prof_any10")
def _c_prof_any10(player, stats, profs, extra, cond):
    """任意副业 10 级"""
    return any(int(p.get("lv", 0) or 0) >= 10 for p in (profs or {}).values())


@register("prof_count")
def _c_prof_count(player, stats, profs, extra, cond):
    """副业次数统计"""
    return stats.get(cond["key"], 0) >= _value(cond)


@register("apprentice")
def _c_apprentice(player, stats, profs, extra, cond):
    """收徒数"""
    return len(player.get("apprentices", []) or []) >= _value(cond)


@register("set_has")
def _c_set_has(player, stats, profs, extra, cond):
    """装备套装收集数"""
    eqs = (player or {}).get("equipment", {}) or {}
    cnt = 0
    for _slot, _eq in eqs.items():
        if isinstance(_eq, dict) and _eq.get("set") == cond.get("key"):
            cnt += 1
    return cnt >= cond.get("value", 4)


# ================= 地图/副本类 =================

@register("visited")
def _c_visited(player, stats, profs, extra, cond):
    """到访区域数"""
    try:
        return db.get_visited_count("", player["qq_id"]) >= _value(cond)
    except Exception:
        return stats.get("visited_areas", 0) >= _value(cond)


@register("hidden_area")
def _c_hidden_area(player, stats, profs, extra, cond):
    """隐藏区域到访数（v105 M18 P1 修复：仅统计真实隐藏区域）

    隐藏区域集合 = HIDDEN_MAP_UNLOCK 解锁表 key（v104 P2 清理后 2 个：
    lost_library/ember_corridor；旧 5 条死条目 dragon_sanctum 等已删）∪ maps 中
    hidden=True 或 type="隐藏区域" 的地图。旧实现与 visited 完全相同（到访普通区域
    也计数）→ 秘境猎手 3 个普通区域即解锁、ach_mythril 到访 1 个任意
    区域即送，隐藏成就贬值。修复后仅到访隐藏区域才计数。
    """
    hidden = set(HIDDEN_MAP_UNLOCK or {})            # W6：门面 catalog_b143（原 `getattr(C, …)`）
    for m in (MAPS or []):
        if m.get("hidden") or m.get("type") == "隐藏区域":
            hidden.add(m["id"])
    if not hidden:
        return False
    # ★ PFIX P5：改走**公共口** `db.get_visited_maps`（`content/persistence/world.py`）。
    #   原实现直插 `db._lock` / `db._connect()` —— 宿主 `game/db.py` 时代这两个内部句柄
    #   确实存在；B1 把存储层搬进包后 `content/_pkgref.DB`（= `content.persistence`）
    #   **不导出**它们 ⇒ AttributeError ⇒ `except` 兜底恒 False ⇒ 隐藏区域成就永不可达。
    #   公共口内部用的是同一把 `_lock` + 同一个 `_connect()`（查询逐字同款）。
    try:
        cnt = sum(1 for m in db.get_visited_maps(player["qq_id"]) if m in hidden)
        return cnt >= _value(cond)
    except Exception:
        return False


@register("inst_clear")
def _c_inst_clear(player, stats, profs, extra, cond):
    """副本通关数"""
    return stats.get("inst_clears", 0) >= _value(cond)


@register("inst_id")
def _c_inst_id(player, stats, profs, extra, cond):
    """通关指定副本"""
    return bool(extra.get("inst_ids", set()) and cond.get("inst") in extra["inst_ids"])


@register("inst_all8")
def _c_inst_all8(player, stats, profs, extra, cond):
    """通关全部 8 副本"""
    return len(extra.get("inst_ids", set()) or set()) >= 8


@register("flawless")
def _c_flawless(player, stats, profs, extra, cond):
    """无伤通关（extra）"""
    return bool(extra.get("flawless"))


# ================= 图鉴/收集类 =================

@register("bestiary")
def _c_bestiary(player, stats, profs, extra, cond):
    """图鉴收集数"""
    return len(db.get_bestiary("", player["qq_id"])) >= _value(cond)


@register("bestiary_all")
def _c_bestiary_all(player, stats, profs, extra, cond):
    """图鉴全收集"""
    from .achievements import _monster_total  # 延迟引用（运行时 achievements 已加载）
    return len(db.get_bestiary("", player["qq_id"])) >= _monster_total()


@register("item_has")
def _c_item_has(player, stats, profs, extra, cond):
    """持有指定物品（v100.3b 修复：原代码引用未定义 group_id → NameError→False 恒 False）
    key 为装备 id（如 eq_starfall_sword）或物品名；背包与已装备槽位双查。"""
    gid = extra.get("_group_id")
    if not gid:
        return False  # 无群上下文时保持旧行为（恒 False）
    key = cond.get("key")
    name = EQUIP_ROSTER.get(key, {}).get("name", key)
    if db.count_item(gid, player["qq_id"], name) > 0:
        return True
    for slot, item in (player.get("equipment") or {}).items():
        if item and item.get("name") == name:
            return True
    return False


@register("hidden_monsters_all")
def _c_hidden_monsters_all(player, stats, profs, extra, cond):
    """击败全部隐藏怪物"""
    hm = extra.get("defeated_hidden_monsters") or set()
    return len(hm & set(HIDDEN_MONSTERS.keys())) >= len(HIDDEN_MONSTERS)


# ================= 社交/公会类 =================

@register("party")
def _c_party(player, stats, profs, extra, cond):
    """组队次数"""
    return stats.get("party_count", 0) >= _value(cond)


@register("guild")
def _c_guild(player, stats, profs, extra, cond):
    """加入公会"""
    return bool(db.guild_get_by_member(player["qq_id"]))


@register("guild_lv")
def _c_guild_lv(player, stats, profs, extra, cond):
    """公会等级"""
    g = db.guild_get_by_member(player["qq_id"])
    return bool(g) and int(g.get("level", 0) or 0) >= _value(cond)


@register("faction")
def _c_faction(player, stats, profs, extra, cond):
    """v116 解锁（原国战延迟恒 False）：已加入某可选阵营（players.faction 非空）。
    加入阵营命令『加入阵营 <编号>』写 players.faction（见 world.py camp_join）。"""
    return bool((player or {}).get("faction"))


def _faction_contribute(player, extra):
    """读取玩家累计阵营贡献。阵营贡献结算数据存 event_state 键 faction_camp_{gid}_{qq} 的
    JSON（contrib=贡献 / tasks=今日任务 / done_total=历史完成数），由命令层 camp_join/camp_task 维护。"""
    gid = extra.get("_group_id")
    if not gid:
        return 0
    try:
        raw = db.get_event_state(f"faction_camp_{gid}_{player['qq_id']}")
    except Exception:
        return 0
    if not raw:
        return 0
    try:
        import json
        data = json.loads(raw)
    except (ValueError, TypeError):
        return 0
    return int(data.get("contrib", 0) or 0)


@register("faction_top")
def _c_faction_top(player, stats, profs, extra, cond):
    """v116 解锁（原国战延迟恒 False）：阵营先锋——阵营贡献 ≥ 100。
    阈值沿用现有成就风格（ach_faction_top 无 value，取缺省 100）。"""
    return _faction_contribute(player, extra) >= int(cond.get("value", 100))


@register("faction_rank1")
def _c_faction_rank1(player, stats, profs, extra, cond):
    """v116 解锁（原国战延迟恒 False）：大陆之柱——阵营贡献 ≥ 500。
    简化判定：原策划「所属阵营国战排名第 1」依赖周结算排名（二期未实装），
    此处以贡献阈值近似（大陆之柱≈对阵营的深厚贡献）。"""
    return _faction_contribute(player, extra) >= int(cond.get("value", 500))


# ================= 世界事件/活动类 =================

@register("world_event")
def _c_world_event(player, stats, profs, extra, cond):
    """参与世界事件数"""
    return stats.get("world_events", 0) >= _value(cond)


@register("event_all")
def _c_event_all(player, stats, profs, extra, cond):
    """世界事件深度参与（v105 M18 P1-4 修复：原恒 False，现接 stats.world_events，
    由 combat.py 世界事件期间战斗结算 bump，与 world_event 条件共用计数）"""
    return stats.get("world_events", 0) >= _value(cond)


@register("fish_king")
def _c_fish_king(player, stats, profs, extra, cond):
    """钓到鱼王（extra）"""
    return bool(extra.get("fish_king"))


@register("collect_fish")
def _c_collect_fish(player, stats, profs, extra, cond):
    """钓到指定鱼（extra）"""
    return extra.get("collect_fish") == cond.get("key")


@register("wish_met")
def _c_wish_met(player, stats, profs, extra, cond):
    """许愿实现（extra）"""
    return bool(extra.get("wish_met"))


@register("worldboss")
def _c_worldboss(player, stats, profs, extra, cond):
    """参与世界 Boss（extra）"""
    return bool(extra.get("worldboss"))


# ================= 任务/剧情类 =================

@register("quest_done")
def _c_quest_done(player, stats, profs, extra, cond):
    """已完成隐藏任务（v100.3b 修复：原代码引用未定义 group_id → NameError→False 恒 False）
    优先走 extra 显式上下文；否则查 quests.side[key].status == \"done\"。"""
    if extra.get("quest_done") == cond.get("key"):
        return True
    gid = extra.get("_group_id")
    if not gid:
        return False  # 无群上下文时保持旧行为（恒 False）
    q = db.get_quests(gid, player["qq_id"])
    return bool(q and q.get("side", {}).get(cond.get("key"), {}).get("status") == "done")


@register("main_done")
def _c_main_done(player, stats, profs, extra, cond):
    """主线完成（v105 M18 P1-1 修复：原 db.get_quests 缺 group_id → TypeError 被吞恒 False）
    v124.3 数据驱动：completed_main 包含主线链尾任务 id（MAIN_QUESTS 中 next 为空的
    任务，当前 = q12_6『黎明之后』）即判定完成——主线链增删任务自动跟随，不再硬编码 id。
    （不采用 len(completed_main)>=len(MAIN_QUESTS)：存档容错重置主线起点时 completed_main
    保留旧条目、重打会产生重复 id，长度判定会提前误判。）"""
    gid = extra.get("_group_id")
    if not gid:
        return False  # 无群上下文时保持旧行为（恒 False）
    try:
        q = db.get_quests(gid, player["qq_id"])
    except Exception:
        return False
    try:
        tail_id = next((qd["id"] for qd in MAIN_QUESTS if not qd.get("next")), None)
    except Exception:
        return False
    if not tail_id:
        return False
    return tail_id in (q.get("completed_main") or [])


@register("main_quest_done")
def _c_main_quest_done(player, stats, profs, extra, cond):
    """完成指定主线任务（v105 M18 P1-2 新增：completed_main 含任务 id）。
    用于 ach_saint_save 圣女守护者（救下圣女 = q6_1 圣女的信任交付）。"""
    gid = extra.get("_group_id")
    if not gid:
        return False
    try:
        q = db.get_quests(gid, player["qq_id"])
    except Exception:
        return False
    return cond.get("key") in (q.get("completed_main") or [])


@register("flag")
def _c_flag(player, stats, profs, extra, cond):
    """剧情标记（v105 M18 P1-2 修复：原只读 extra.flags，而 25 处 check_achievements
    调用无一传 flags → 恒 False 死锁）。
    判定顺序：① extra.flags（事件上下文，测试兼容）② db talk_flags（与对话系统共用，
    event_state key = talkflags_{gid}_{qid}，跨 NPC 扁平查）。"""
    flag = cond.get("flag")
    flags = extra.get("flags") or {}
    if flags.get(flag):
        return True
    gid = extra.get("_group_id")
    if not gid:
        return False
    try:
        raw = db.get_event_state(f"talkflags_{gid}_{player['qq_id']}")
    except Exception:
        return False
    if not raw:
        return False
    try:
        import json
        data = json.loads(raw)
    except (ValueError, TypeError):
        return False
    for npc_flags in data.values():
        if flag in (npc_flags or []):
            return True
    return False
