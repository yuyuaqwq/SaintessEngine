# -*- coding: utf-8 -*-
"""包内公会域（`content/social_guild.py`）—— 公会编排逻辑 + 公会面板，真源搬入。

真源（游戏仓 `qqbot/data/plugins/dragonfall`，**只读**）
--------------------------------------------------------
| 真源 | 行数 | 本文件搬什么 |
|---|---:|---|
| `game/services/guild.py` | 275 | **全文件**：建会/入会/退会/解散/签到/任务/捐献/排行/任命/免职/击杀推进 |
| `game/commands/social.py:620-652 guild_info` | — | 面板主体（成员分页行；tip/记账留在命令层） |
| `game/commands/social.py:734-804 guild_shop + _guild_shop_buy` | — | 商店面板 + 购买（扣积分/限购/发货） |
| `game/commands/social.py:809-827 guild_skill_view` | — | 技能面板（展示） |

宿主耦合替身（**只改两类东西**：① 存储层/读表口 ② 配置读口）
--------------------------------------------------------------
| 真源写法 | 包内写法 | 说明 |
|---|---|---|
| `from .. import db` + `db.xxx(...)` | 模块级 `db` = **惰性宿主代理** `_HostDB`（属性访问时才解析宿主模块） | 正文里 `db.xxx(...)` **一行未改**；宿主由 `bind_host(db)` 注入，或按 `sys.modules` 找**已加载**的宿主模块（绝不 import，防包侧另起一份宿主模块树） |
| `from ..store.social import guild_get_member / guild_set_role / guild_spend_contribute`（不在 `db` 门面上） | `_store_social()`（注入优先 → ★ REPOINT-PKG 起兜底**包内直取** `content/persistence/social.py`） | 这三个原语在宿主 `game/store/social.py`（= `from content.persistence.social import *` 的委托薄壳 ⇒ 同一批函数对象）；`game/db.py` 聚合面没导出 |
| `from .. import content as C` + `C.GUILD_CONFIG` | `_cfg()`（`bind_host(config=…)` 注入优先 → ★ W4 兜底改**包内门面** `content/catalog_b143.py:GUILD_CONFIG`） | 数值配置仍由宿主薄壳注入（L7 配置面）；原兜底读宿主 `game.data.guild.GUILD_CONFIG` 已切门面（门禁逐键逐值相等）⇒ `game/data` 删后本模块仍可活 |
| `from ..data import guild as _G` + `_G.GUILD_ROLES / GUILD_SHOP_ITEMS / GUILD_SKILLS` | 读包内 `content/data/guild.json`（`guild_roles()` / `guild_shop_items()` / `guild_skills()`） | 域真源 = `game/data/guild.py`，单向导出器 `scripts/export_domains/b9_social.py:derive_guild` |

⚠️ 读表坑：`guild.json` 的 `shop_items` 键是**字符串化整数**（JSON 只有字符串键，真源是 int 1..6）→
`guild_shop_items()` 读时**还原 int**。不还原 = `get(编号)` 恒 None = 「公会商店 1」全部报
「没有第 N 件商品」（与 `content/tables.py:ENHANCE_TABLE` 同族坑）。

返回结构（与真源逐字段/逐字一致）
----------------------------------
`guild_create_check(player)` → `(ok, err)`；`guild_create(...)` → `(ok, gid, err)`；
`guild_join(...)` → `(ok, g, err)`；`guild_leave_check(g, qq_id)` → `(blocked, msg)`；
`guild_sign(...)` → `(ok, lines, err)`；`guild_task_view(...)` → `(ok, lines, err)`；
`guild_donate(...)` → `(ok, lines, err, need, total)`；`guild_rank_lines()` → `list[str]`；
`guild_find_member(...)` → `(member, target, err)`；`guild_appoint(...)` → `(label, icon)`；
`guild_kill_progress(...)` → `(changed_lines, rewarded)`（combat 击杀结算侧消费）。
本包新搬的三个命令级函数返回**待 yield 的消息 list**（命令层只做「取玩家 → 调包 → yield」）：
`guild_shop_buy(...)` → `list[str]`；`guild_info_lines(...)` / `guild_shop_lines(...)` /
`guild_skill_lines(...)` → 面板行 `list[str]`（tip / `_record_list_state` 由命令层补）。

用法::

    from content import social_guild as SG
    SG.bind_host(db, config=C.GUILD_CONFIG)          # 宿主薄壳在 import 期注入
    ok, gid, err = SG.guild_create(group_id, qq_id, player, name)
"""
from __future__ import annotations

import datetime
import json
import os

# ★ W4（2026-09-14）：`C.GUILD_CONFIG` 兜底 → 包内门面（真源 `game/data/guild.py:3`）
from . import catalog_b143 as _cat_b143

# ============================================================
# ① 宿主替身口（存储层 / 公会原语 / 数值配置）
# ============================================================
_HOST_DB = None            # 宿主存储层（真源 `from .. import db`）
_HOST_STORE_SOCIAL = None  # 注入槽：`game.store.social`（公会三原语）—— 未注入 → 包内直取 `content/persistence/social.py`
_CONFIG = None             # GUILD_CONFIG——宿主薄壳注入优先；未注入 → 包内门面 `catalog_b143`（★ W4）

_HOST_PKG = "data.plugins.dragonfall.game"
_HOST_PKG_FALLBACK = "game"


def bind_host(db=None, config=None, store_social=None):
    """宿主替身注入（幂等；宿主薄壳在 import 期调用）。

    - `db`：存储层模块（`game/db.py` 门面）
    - `config`：`GUILD_CONFIG` dict（L7 配置面，本域不搬）
    - `store_social`：`game.store.social` 模块（公会原语不在 `db` 门面上）
    """
    global _HOST_DB, _HOST_STORE_SOCIAL, _CONFIG
    if db is not None:
        _HOST_DB = db
    if config is not None:
        _CONFIG = config
    if store_social is not None:
        _HOST_STORE_SOCIAL = store_social


def _resolve_host(mod: str):
    """取宿主子模块：注入优先 → 已加载的宿主模块（`sys.modules`，**不 import**）。"""
    import sys
    for name in (f"{_HOST_PKG}.{mod}", f"{_HOST_PKG_FALLBACK}.{mod}"):
        m = sys.modules.get(name)
        if m is not None:
            return m
    raise RuntimeError(f"social_guild：宿主模块 {mod} 不可用（未 bind_host 且未加载）—— 拒绝静默空跑")


class _HostDB:
    """惰性宿主存储层代理（真源 `from .. import db`）——`db.xxx` 正文不动，属性访问时解析。"""

    def __getattr__(self, name):
        return getattr(_HOST_DB if _HOST_DB is not None else _resolve_host("db"), name)


db = _HostDB()


def _store_social():
    """公会三个原语（`guild_get_member` / `guild_set_role` / `guild_spend_contribute`）。

    ★ REPOINT-PKG（2026-09-15，B4R B 组第 5 项）：兜底由「宿主子模块 `game.store.social`」
      改为**包内直取** `content/persistence/social.py`（B17 已整域进包；宿主
      `game/store/social.py` 只剩 `from content.persistence.social import *` 的委托薄壳
      ⇒ 同一批函数对象）。注入槽 `bind_host(store_social=…)` 原样保留；
      取件时机 = 调用时（与旧 `_resolve_host` 口径一致）。
    """
    if _HOST_STORE_SOCIAL is not None:
        return _HOST_STORE_SOCIAL
    from .persistence import social as _pkg_social   # 包内直取（调用时取件，与旧口径同时机）
    return _pkg_social


def _cfg():
    """`GUILD_CONFIG`（注入优先 → 包内门面 `content/catalog_b143.py`；真源 `game/data/guild.py:3`）。"""
    if _CONFIG is not None:
        return _CONFIG
    return _cat_b143.GUILD_CONFIG


# ============================================================
# ② 读表口：包内 `guild` 域（真源 `game/data/guild.py`）
# ============================================================
_DOMAIN_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "guild.json")
_DOMAIN = None

# 职位词 → role key（真源 `game/services/guild.py:195 ROLE_MAP`，逻辑常量，不是数据表）
ROLE_MAP = {"副会长": "vice_leader", "精英": "elite"}
# 可任命目标职位（真源同名单：真源 `game/services/guild.py:196 APPOINTABLE_ROLES`；
# 与域里 `roles.appointable` 同源，域是权威 → 本常量只作无域时的兜底说明，不在判定里用）
APPOINTABLE_ROLES = ("vice_leader", "elite")


def _read_domain() -> dict:
    """读包内 `content/data/guild.json`（缺文件/坏 JSON/空表 → 抛，不静默空表）。"""
    with open(_DOMAIN_JSON, encoding="utf-8") as f:
        tbl = json.load(f)
    if not isinstance(tbl, dict) or not tbl:
        raise RuntimeError(f"guild 域文件不可用（{_DOMAIN_JSON}）—— 空表 = 静默无职位/无商店")
    return tbl


def _domain() -> dict:
    global _DOMAIN
    if _DOMAIN is None:
        _DOMAIN = _read_domain()
    return _DOMAIN


def _reload_domain():
    """清空域缓存（换盘/测试用）。"""
    global _DOMAIN
    _DOMAIN = None


def _int_keys(tbl) -> dict:
    """字符串键 → int 键（JSON 只有 str 键；非整数键**原样保留**，不静默丢）。"""
    out: dict = {}
    for k, v in (tbl or {}).items():
        try:
            out[int(k)] = v
        except (TypeError, ValueError):
            out[k] = v
    return out


def guild_roles() -> dict:
    """`{role: [职位名, 图标]}`（真源 `GUILD_ROLES`；真源是 tuple，JSON 落 list —— 解包语义同）。"""
    return dict((_domain().get("roles") or {}).get("map") or {})


def guild_appointable() -> tuple:
    """会长可任命的 role 元组（真源 `GUILD_APPOINTABLE`）。"""
    return tuple((_domain().get("roles") or {}).get("appointable") or ())


def guild_shop_items() -> dict:
    """公会商店 `{编号(int): 条目}`（⚠️ 键还原 int，见模块 docstring）。"""
    return _int_keys(_domain().get("shop_items") or {})


def guild_skills() -> dict:
    """公会技能 `{技能 key: 条目}`（真源 `GUILD_SKILLS`）。"""
    return dict(_domain().get("skills") or {})


# ============================================================
# ③ 公会编排（真源 `game/services/guild.py` 逐字；只把 import 换成上面的替身）
# ============================================================

def _today():
    return datetime.date.today().isoformat()


def _is_leader(g, qq_id):
    return str(g.get("leader")) == str(qq_id)


def guild_get_member(gid, qq_id):
    """公会成员行取值（包内 `content/persistence/social.py` 直取；不在 `db` 门面上）。"""
    return _store_social().guild_get_member(gid, qq_id)


def guild_create_check(player):
    """创建公会前置校验（纯读）：返回 (ok, err)。已入会/等级/金币门槛在调用方查完再进。

    注意：『已在一个公会』校验依赖 db.guild_get_by_member(qq_id)，由命令层先查后调
    （本函数收 player 快照避免重复读）。返回 ok=False 时 err 为可直接 yield 的拒绝文案。
    """
    cfg = _cfg()
    if player["level"] < cfg["create_level"]:
        return False, f"创建公会需要 {cfg['create_level']} 级！你才 {player['level']} 级，先去冒险吧～"
    if player["gold"] < cfg["create_cost"]:
        return False, f"创建公会需要 {cfg['create_cost']} 金币！你只有 {player['gold']} 金币。"
    return True, None


def guild_create(group_id, qq_id, player, name):
    """创建公会：扣金币 → 建会。返回 (ok, gid, err)。

    - guild_create 重名返回 None → err='已存在' 文案。
    - 成功后扣 create_cost 金币（v105 M18 P2：成就判定由命令层在成功后做）。
    """
    cfg = _cfg()
    gid = db.guild_create(name, qq_id, desc=f"{player['name']} 创立的公会")
    if not gid:
        return False, None, f"公会『{name}』已存在！换个名字吧～"
    db.update_player(group_id, qq_id, gold=player["gold"] - cfg["create_cost"])
    return True, gid, None


def guild_join(group_id, qq_id, name):
    """加入公会：按名查会 → 入会。返回 (ok, g, err)。成功 g=公会 dict（命令层取 g['name'] 拼文案）。"""
    g = db.guild_get_by_name(name)
    if not g:
        return False, None, f"找不到公会『{name}』！输入『公会排行』看看有哪些公会～"
    db.guild_join(g["gid"], qq_id)
    return True, g, None


def guild_leave_check(g, qq_id):
    """退出公会前置守卫：会长不能直接退会（须解散）。返回 (blocked, msg)。"""
    if _is_leader(g, qq_id):
        # v105 M18 P2：全仓无『转让会长』命令，提示只指向真实命令，避免误导
        return True, "你是会长！会长不能直接退会，请『解散公会』（公会随之解散）～"
    return False, None


def guild_leave(g, qq_id):
    """退出公会（db.guild_leave：leader 离开即解散，由 store 原语处理）。"""
    db.guild_leave(g["gid"], qq_id)


def guild_disband(g, qq_id):
    """解散公会（leader 离开即解散）。"""
    db.guild_leave(g["gid"], qq_id)  # leader 离开即解散


def guild_sign(group_id, qq_id, g):
    """公会签到（每日一次）：写签到日期 → 公会经验/个人贡献/金币。

    返回 (ok, lines, err)。ok=False 时 err=拒绝文案（今日已签/无公会由调用方先查）。
    数值全部来自 GUILD_CONFIG（sign_exp/sign_contribute/sign_gold）。
    """
    cfg = _cfg()
    today = _today()
    if db.guild_get_sign(g["gid"], qq_id) == today:
        return False, None, "今天已经公会签过到啦！明天再来～"
    db.guild_set_sign(g["gid"], qq_id, today)
    db.guild_add_exp(g["gid"], cfg["sign_exp"], member_qq=qq_id, contribute=cfg["sign_contribute"])
    player = db.get_player(group_id, qq_id)
    db.update_player(group_id, qq_id, gold=(player or {}).get("gold", 0) + cfg["sign_gold"])
    return True, [
        f"📅 【公会签到】在【{g['name']}】报到！\n"
        f"🏰 公会经验 +{cfg['sign_exp']} ｜ 个人贡献 +{cfg['sign_contribute']}\n"
        f"💰 金币 +{cfg['sign_gold']}"
    ], None


def guild_task_view(group_id, qq_id, g):
    """公会任务面板（击杀型，跨天重置）：返回 (ok, lines, err)。

    击杀自动推进由 combat 侧调 guild_kill_progress；此处仅读当前进度。
    """
    need = _cfg()["kill_task"]
    tdate, tprog = db.guild_get_task(g["gid"], qq_id)
    if tdate != _today():
        tdate, tprog = _today(), 0
    if tprog >= need:
        return False, None, "今天的公会任务已完成！明天再来～"
    return True, [
        f"🎯 【公会任务】击杀 {need} 只怪物(当前 {tprog}/{need})\n"
        f"💡 击杀会自动结算奖励！"
    ], None


def guild_donate_inventory(group_id, qq_id):
    """公会捐献可上交材料清单（v46 材料统一 mat_ 前缀；v104R3 P1-3 排除任务道具）。"""
    return [it for it in db.get_inventory(group_id, qq_id)
            if it["key"].startswith("mat_") and it["data"].get("type") != "任务道具"]


def guild_donate_total(mats):
    return sum(it["count"] for it in mats)


def guild_donate(group_id, qq_id, g):
    """公会捐献（每日一次，event_state 记日期）：够料则扣料 → 公会经验/贡献/金币。

    返回 (ok, lines, err, need, total)：ok=False 时 err=拒绝/不足文案（含 need/total 供面板）。
    扣料顺序：从背包靠前的材料开始扣（与旧命令层逐项 remove_item 等价）。
    """
    cfg = _cfg()
    need = cfg["donate_items"]
    key = f"guild_donate:{g['gid']}:{qq_id}"
    if db.get_event_state(key) == _today():
        return False, None, "今天的公会捐献已完成！明天再来～", need, None
    mats = guild_donate_inventory(group_id, qq_id)
    total = guild_donate_total(mats)
    if total < need:
        return False, None, f"🎯 【公会捐献】需要上交 {need} 份材料(当前 {total}/{need})！\n", need, total
    remain = need
    for it in mats:
        if remain <= 0:
            break
        take = min(it["count"], remain)
        db.remove_item(group_id, qq_id, it["key"], take)
        remain -= take
    db.guild_add_exp(g["gid"], cfg["task_exp"], member_qq=qq_id, contribute=cfg["task_contribute"])
    player = db.get_player(group_id, qq_id)
    db.update_player(group_id, qq_id, gold=(player or {}).get("gold", 0) + cfg["task_gold"])
    db.set_event_state(key, _today())
    return True, [
        f"🎁 【公会捐献完成】上交 {need} 份材料，为公会贡献力量！\n"
        f"🏰 公会经验 +{cfg['task_exp']} ｜ 个人贡献 +{cfg['task_contribute']}\n"
        f"💰 金币 +{cfg['task_gold']}"
    ], None, need, total


def guild_rank_lines():
    """公会排行榜行（db.guild_top(10)）。无公会时返回 []（命令层给空榜文案）。"""
    tops = db.guild_top(10)
    if not tops:
        return []
    lines = ["🏆 【公会排行榜】", "━━━━━━━━━━━━"]
    for i, g in enumerate(tops, 1):
        lines.append(f"{i}. {g['icon']} {g['name']} Lv.{g['level']}({g['members']}人)")
    return lines


def guild_appoint_check_role(role_arg):
    """职位词 → role key；不支持返回 None（命令层给『可任命职位』文案）。"""
    return ROLE_MAP.get(role_arg)


def guild_appoint_level_ok(g, role):
    """任命等级门槛：副会长需公会 Lv.3（GUILD_CONFIG.vice_leader_level），精英无门槛。

    返回 (ok, err)：ok=False 时 err 为可直接 yield 的文案（含门槛值与当前公会等级）。
    """
    cfg = _cfg()
    if role == "vice_leader" and g["level"] < cfg.get("vice_leader_level", 3):
        return False, f"任命副会长需要公会 Lv.{cfg.get('vice_leader_level', 3)}！本公会才 Lv.{g['level']}～"
    return True, None


def guild_find_member(g, target_name):
    """按玩家名查公会成员。返回 (member, target, err)：

    - 查无此玩家 → err='没找到玩家' 文案；
    - 玩家不在本公会 → err='不在本公会' 文案（member=None, target 有值）。
    """
    target = db.find_player_by_name(target_name)
    if not target:
        return None, None, f"没找到玩家『{target_name}』！"
    tm = guild_get_member(g["gid"], target["qq_id"])
    if not tm:
        return None, target, f"『{target['name']}』不在本公会里～"
    return tm, target, None


def guild_appoint(g, target, role):
    """执行任命（写 role）。返回 (label, icon)（命令层拼晋升文案）。"""
    _store_social().guild_set_role(g["gid"], target["qq_id"], role)
    return tuple(guild_roles()[role])


def guild_demote(g, target):
    """执行免职（降回 member）。"""
    _store_social().guild_set_role(g["gid"], target["qq_id"], "member")


# ---- 公会任务击杀推进（combat 击杀结算侧消费；跨天重置 v43）----


def guild_kill_progress(group_id, qq_id, g, lines=None):
    """击杀推进公会任务：跨天重置 → +1 → 达标发奖（公会经验/贡献/金币）。

    返回 (changed_lines, rewarded)：changed_lines 为击杀侧要追加的战斗结算行
    （进度行或完成行），rewarded=True 表示本次击杀达成任务并已发奖。
    无公会成员资格（g=None）返回 ([], False)。v43：跨天重置而非跳过。
    """
    cfg = _cfg()
    tdate, tprog = db.guild_get_task(g["gid"], qq_id)
    if tdate != _today():
        tprog = 0  # 新的一天/新成员：重置进度
    if tprog < cfg["kill_task"]:
        tprog += 1
        db.guild_set_task(g["gid"], qq_id, _today(), tprog)
        if tprog >= cfg["kill_task"]:
            db.guild_add_exp(g["gid"], cfg["task_exp"], member_qq=qq_id, contribute=cfg["task_contribute"])
            # v105 M18 P2：先刷新 player 再写金币——player dict 在战斗结算中段刷新后，
            # _rule_fire("battle_win")（Boss 巢穴私藏金币等 loot_gold 彩蛋）可能已落库加金币，
            # 直接用旧 dict 值覆盖会丢掉同场彩蛋金币
            player = db.get_player(group_id, qq_id)
            db.update_player(group_id, qq_id, gold=(player or {}).get("gold", 0) + cfg["task_gold"])
            return [f"🎯 【公会任务完成】击杀 {cfg['kill_task']} 只达成！公会经验 +{cfg['task_exp']} 贡献 +{cfg['task_contribute']} 金币 +{cfg['task_gold']}"], True
        return [f"🎯 公会任务进度 {tprog}/{cfg['kill_task']}"], False
    return [], False


# ============================================================
# ④ 面板/购买（真源 `game/commands/social.py` 的公会命令编排）
# ============================================================

def guild_info_lines(group_id, g, members, page_items, page, pages, player_lookup,
                     exp_need, per_page=5):
    """公会面板**主体行**（真源 `social.py:633-649`）。

    真源在命令层用 `self._player` 查成员名、`self._page_items` 分页、`self._tip` 补提示、
    `self._record_list_state` 记账 —— 分页/提示/记账留在命令层（通用底座 + IO），
    本函数收「已分页好的 page_items」与 `player_lookup` 回调，只拼主体行。

    `exp_need` = 升级所需经验（真源命令层 `g["level"] * GUILD_EXP_BASE`；该常量包内**已有门面**
    `content/catalog_core.py:GUILD_EXP_BASE`，但按 B14-2 L6 派工本域不搬数据 → 由命令层算好传入）。

    返回 `list[str]`（未含 tip 行）。
    """
    roles = guild_roles()
    count = len(members)
    lines = [
        f"{g['icon']} 【{g['name']}】Lv.{g['level']}",
        f"━━━━━━━━━━━━",
        f"👥 成员 {count} 人 ｜ 经验 {g['exp']}/{exp_need}",
        f"📜 {g['desc'] or '暂无宣言'}",
        f"💡 公会加成：打怪经验 +{guild_exp_bonus_pct(g)}%",
        f"━━━━━━━━━━━━",
        f"成员(第 {page}/{pages} 页)：",
    ]
    for i, m in enumerate(page_items, (page - 1) * per_page + 1):
        p = player_lookup(group_id, m["qq_id"])
        _label, _icon = roles.get(m["role"], ("成员", "⚔️"))
        name = p["name"] if p else m["qq_id"]
        lines.append(f"{i:>2}. {_icon} {name}({_label}) Lv.{p['level'] if p else '?'} ｜ 贡献 {m['contribute']}")
    lines.append("")
    if pages > 1 and page < pages:
        lines.append(f"💡 『公会 {page+1}』看下一页(共 {pages} 页)")
    return lines


def guild_exp_bonus_pct(g):
    """公会等级 → 打怪经验加成百分比（真源 `social.py:638` 的 min(int(…), int(…)) 原式）。

    真源：`min(int(g['level'] * C.GUILD_CONFIG['exp_bonus_per_level'] * 100), int(C.GUILD_CONFIG['max_bonus'] * 100))`
    —— 浮点乘算与取整次序**逐字保留**（改次序会改变边界等级上的取值）。
    """
    cfg = _cfg()
    return min(int(g["level"] * cfg["exp_bonus_per_level"] * 100), int(cfg["max_bonus"] * 100))


def guild_shop_lines(g, member):
    """公会商店面板行（真源 `social.py:755-763`；`_tip` 由命令层补）。"""
    contribute = member.get("contribute", 0)
    lines = [f"🛒 【公会商店】Lv.{g['level']} ｜ 公会积分：{contribute}", "━━━━━━━━━━━━"]
    for i, it in guild_shop_items().items():
        locked = g["level"] < it["min_level"]
        tag = "🔒" if locked else f"{it['cost']} 积分"
        lines.append(f"{i}. {it['name']} ｜ {tag}")
        limit = f"每日限购 {it['daily_limit']}" if it.get("daily_limit") else "不限购"
        lines.append(f"   {it['item_data'].get('desc', '')} ｜ 需公会 Lv.{it['min_level']} ｜ {limit}")
    lines.append("━━━━━━━━━━━━")
    return lines


def guild_shop_buy(group_id, qq_id, g, member, num):
    """公会商店购买：扣成员贡献积分 → 发包件物品。返回**待 yield 的消息 list**（真源逐字）。

    真源 `game/commands/social.py:766-804 _guild_shop_buy`（每个分支 yield 一条 → 本函数返回
    单元素 list，命令层 `for ln in …: yield`）。每日限购用 event_state 记录 key（非 schema 改动）。
    """
    _dt = datetime
    it = guild_shop_items().get(num)
    if not it:
        return [f"没有第 {num} 件商品！『公会商店』查看～"]
    if not member:
        return ["你不是公会正式成员～"]
    if g["level"] < it["min_level"]:
        return [f"【{it['name']}】需要公会 Lv.{it['min_level']}！本公会才 Lv.{g['level']}～"]
    contribute = member.get("contribute", 0)
    if contribute < it["cost"]:
        return [f"公会积分不足！购买【{it['name']}】需要 {it['cost']} 积分，你只有 {contribute}。"]
    # 每日限购（用 event_state 记录 key，非 schema 改动）
    if it.get("daily_limit"):
        today = _dt.date.today().isoformat()
        key = f"guild_shop:{g['gid']}:{qq_id}:{num}"
        if db.get_event_state(key) == today:
            return [f"今天【{it['name']}】已买满(每日限购 {it['daily_limit']})！明天再来～"]
    # 正式扣积分（贡献充足性在事务内复核）
    if not _store_social().guild_spend_contribute(g["gid"], qq_id, it["cost"]):
        return ["积分扣除失败！可能积分变动，请重试～"]
    # v116 审计修复 A0-A1：直接使用 GUILD_SHOP_ITEMS 的稳定 item_key（gs_*），
    # 去掉随机 uuid 后缀——否则 stackable 商品每次购买生成新 key，永不合并堆叠。
    # 商品 key 全表唯一，此处直接引用即可（add_item 按其 key 堆叠合并）。
    item_key = it.get("item_key", "gs_")
    db.add_item(group_id, qq_id, item_key, it["item_data"], count=1)
    if it.get("daily_limit"):
        db.set_event_state(f"guild_shop:{g['gid']}:{qq_id}:{num}", _dt.date.today().isoformat())
    return [
        f"🛒 购买成功！【{it['name']}】(花费 {it['cost']} 公会积分)\n"
        f"{it.get('msg', '')}"
    ]


def guild_skill_lines(g):
    """公会技能面板行（真源 `social.py:819-826`；`_tip`/开发中提示由命令层补）。"""
    lines = [f"📖 【公会技能】Lv.{g['level']}", "━━━━━━━━━━━━"]
    for key, sk in guild_skills().items():
        lines.append(f"💡 {sk['name']}：{sk['desc']}/级(最高 {sk['max_level']} 级)")
        costs = " → ".join(str(c) for c in sk["level_costs"][1:])
        requires = " → ".join(f"Lv.{l}" for l in sk["level_guild_lv"][1:])
        lines.append(f"   积分需求：{costs} ｜ 公会等级：{requires}")
    lines.append("━━━━━━━━━━━━")
    return lines
