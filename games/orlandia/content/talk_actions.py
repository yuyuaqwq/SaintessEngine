# -*- coding: utf-8 -*-
"""包内对话动作注册表（`content/talk_actions.py`）—— 真源 `game/commands/talk_actions.py`（385 行）逐字端口。

★ B8.2 线3（2026-09-13）：命令层 `commands/talk_actions.py` 薄壳化 = **只留「注册」**
（17 个 `@register(...)` 一行转发 + 消费端防御 `check_action_keys`），**动作实现正文搬进本模块**。
命令层命名与调用签名一字不变（`fn(world, group_id, qq_id, player, npc_id, action)` → `ACTIONS`），
所以 `commands/world.py:3577 _apply_talk_action_async` 的消费点零改动。

逐字搬的改动面（**只改两类**，与 `content/flow/weekly_progress.py`/`content/effects/poi_effects.py` 同款）
----------------------------------------------------------------------------------------------
| 真源写法 | 包内替身 | 说明 |
|---|---|---|
| `from .. import db` + `db.xxx(...)` | 模块级 `db` = 宿主存储层（`bind_host(db)` 注入；正文 `db.xxx(...)` **一行未改**） | 写库留宿主（`game/db.py`）；未注入时按 `sys.modules` 找**已加载**的宿主模块（绝不 import 宿主模块树） |
| 函数内 `from ..reward import grant_reward` | 模块级 `grant_reward`（`bind_host` 注入；缺省按 `sys.modules` 找宿主 `game.reward`） | 发放（金币/经验/物品）实现仍在宿主 |
| `from ..content_rules.skills import branch_skill_owner, skill_info` | `from .skills import branch_skill_owner, skill_info` | 包内已逐字端口（`content/skills.py:518/536`，D3 技能批）——技能查询链是内容 |
| `from .. import content as C` 的六处读点 | `NPCS` / `SIDE_QUESTS` → **共享门面** `catalog_quests`（`_cq`）；`CLASSES` → **共享门面** `catalog_core`（`_cc`）；`ALL_WILD` → ★ W4 切**包内读口** `content/wild.py`；`resolve` / `get_dialogue` 是**函数名** → 本文件 `class _Dom` + `C = _Dom()`（读包内域 JSON / 包内 `tables`） | ★ **B14-2 L6**：三张表切共享门面（门禁逐值 + 键序相等）；★ **W4（2026-09-14）**：`ALL_WILD` 切 `content/wild.py`（真源 `core/wild.py:26` 派生式，与宿主 `C.ALL_WILD` 键集/键序/逐条值全等）——本文件本地派生（`npcs` 域筛选）随之删除，防同表两份定义 |
| `from ..log_setup import LOG` | **不搬** | 宿主日志层；本文件正文零读点（唯一读点在 `check_action_keys`，它留在宿主薄壳） |

★ 顺序不变式（渲染逐字等价的关键）：`ACTIONS` 的**注册顺序 = 执行顺序**（`world.py:3579`
`for key, fn in ACTIONS.items()` 按序执行，条件型动作 `apprentice_check` 必须最先）——
宿主薄壳的 17 个 `@register` 与真源逐行同序；包内 `ACTIONS` 只作本模块自检用，宿主不读它。

★ 表读点的形状还原（JSON 只有字符串键 / dict 只剩字典序）
------------------------------------------------------------------
1. `CLASSES[cls]["evolve_branches"]` 的档位键真源是 **int**（`{1: [...], 2: [...], 3: [...]}`），
   落盘成 `"1"/"2"/"3"` —— 不还原：`tutor_skill` 的 `.get(need_tier)`（need_tier 来自
   `branch_skill_owner` 返回的 int 档位）恒取缺省 `[]` ⇒ 分支校验永远判「你走的是别的路线」
   （玩家：明明是狂战士却学不了狂战士技能）。**已实测**（快照矩阵覆盖 tutor_skill 全分支）。
   ★ B14-2 L6：`CLASSES` 已切共享门面 `content/catalog_core.py`，int 档位键由它还原
   （本文件原 `_Dom` 里的同名还原已删，防同表两份定义）；消费口径与还原结果不变。
2. `ALL_WILD`：真源 `game/core/wild.py:26 ALL_WILD = {**WILD_NPCS, **HIDDEN_NPCS}` 在
   `core.wild` import 期求值，而 `_assembly.py:161-163` 之后才把 6 条层内 NPC 并进
   `HIDDEN_NPCS` ⇒ 真源 `ALL_WILD` = wild(47) ∪ hidden(**16 条字面量**) = **63**，
   不含 6 条 `inst_stage` 层内 NPC（实测：`npc_abyss_seer` 等 6 条在 `HIDDEN_NPCS` 里、
   不在 `ALL_WILD` 里）。
   ★ W4（2026-09-14）：该派生式**包内已有单点实现** `content/wild.py:_ALL_WILD()`（B13-L2 搬包，
   用 `not inst_stage` 精确还原这 63 条）⇒ 本文件改读 `_wild.ALL_WILD`，原本地派生
   （`npcs` 域 `source` 筛 63 条）**删除**：值同源、消费口径不变，且顺带去掉本地版本多带的
   注入键 `source`（宿主 `C.ALL_WILD` 本就没有）。
"""
from __future__ import annotations

import json
import os
import sys

from .skills import branch_skill_owner, skill_info  # noqa: F401  (包内端口，不是宿主)

# ★ B14-2 L6：数据表切包内门面（宿主 `game/data` 删掉后本文件仍能活）
from . import catalog_core as _cc        # CLASSES
from . import catalog_quests as _cq      # NPCS / SIDE_QUESTS
# ★ W4（2026-09-14）：`C.ALL_WILD` → 包内读口（真源 `core/wild.py:26` 派生式）
from . import wild as _wild

_HERE = os.path.dirname(os.path.abspath(__file__))          # <pkg>/content
_ROOT = os.path.dirname(_HERE)                             # <pkg>


def _read_domain(domain: str, sub: str = "data", default=None):
    """读包内 `content/<sub>/<domain>.json`（缺文件 / 坏 JSON → default，不抛）。"""
    try:
        with open(os.path.join(_HERE, sub, "%s.json" % domain), encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                       # noqa: BLE001
        return {} if default is None else default


# ============================================================
# 宿主替身口（存储层 + 发放函数）—— 正文里 `db.xxx(...)` / `grant_reward(...)` 一行未改
# ============================================================
_HOST_DB = None            # 宿主存储层模块（真源 `from .. import db`）
_HOST_GRANT = None         # 宿主发放函数（真源 `from ..reward import grant_reward`）
# 宿主模块名（运行时 `main.py` 的模块路径 = `data.plugins.dragonfall`；测试同样）—— 与
# `content/flow/weekly_progress.py` 同口径（B8.2 线1 立的规矩）
_HOST_PKG = "data.plugins.dragonfall.game"
_HOST_PKG_FALLBACK = "game"


def bind_host(db=None, grant_reward=None) -> None:
    """宿主替身注入（幂等；宿主薄壳在 import 期调用）。

    `db` = 宿主存储层模块（真源 `from .. import db`）；`grant_reward` = 宿主发放函数
    （真源 `from ..reward import grant_reward`，函数体内 import）。
    """
    global _HOST_DB, _HOST_GRANT
    if db is not None:
        _HOST_DB = db
    if grant_reward is not None:
        _HOST_GRANT = grant_reward


def _resolve_host(mod: str):
    """取宿主子模块：注入优先 → 已加载的宿主模块（`sys.modules`，**不 import**）。"""
    for name in ("%s.%s" % (_HOST_PKG, mod), "%s.%s" % (_HOST_PKG_FALLBACK, mod)):
        m = sys.modules.get(name)
        if m is not None:
            return m
    raise RuntimeError(
        "talk_actions：宿主模块 %s 不可用（未 bind_host 且未加载）—— 拒绝静默空跑" % mod)


class _HostDB:
    """惰性宿主存储层代理（真源 `from .. import db`）——`db.xxx` 正文不动，属性访问时解析。"""

    def __getattr__(self, name):
        return getattr(_HOST_DB if _HOST_DB is not None else _resolve_host("db"), name)


db = _HostDB()


def grant_reward(*args, **kwargs):
    """宿主发放函数（真源 函数体内 `from ..reward import grant_reward`）—— 正文调用点不动。"""
    fn = _HOST_GRANT if _HOST_GRANT is not None else getattr(_resolve_host("reward"), "grant_reward")
    return fn(*args, **kwargs)


# ============================================================
# 包内域门面（替身：宿主薄聚合层 `C`）—— W4 后只剩 resolve / get_dialogue（函数名）
# ============================================================
class _Dom:
    """本文件仍走包内小门面的两处：`resolve` / `get_dialogue`（函数名，B14 派工口径下
    不做函数单元）。真源里的 `NPCS` / `SIDE_QUESTS` / `CLASSES` 三张表已切共享门面
    （B14-2 L6）；`ALL_WILD` 已切 `content/wild.py`（★ W4，见文件头表）。"""

    def __init__(self):
        self.dialogues: dict = _read_domain("dialogues")

    @staticmethod
    def resolve(table_name: str, name_or_id: str):
        """`game/core/index.py:47 resolve`（只用到 skills —— 包内 `content/tables.py` 的同义口）。"""
        from . import tables as _T
        return _T.resolve(table_name, name_or_id)

    def get_dialogue(self, npc_id: str):
        """`game/core/dialogue.py get_dialogue`：无对话树返回 None。"""
        dlg = self.dialogues.get(npc_id)
        return dlg if dlg else None

    def display(self, table_name: str, entity_id: str):
        """`game/core/index.py:52 display`（只用到 skills/materials —— 走 `content/tables.py`）。"""
        from . import tables as _T
        return _T.display(table_name, entity_id)


C = _Dom()

# v130.2f.2 苦修档位展示名映射（分支 key 不动，仅展示层；与 player.py _BRANCH_KEY_DISPLAY 同源）
_BRANCH_DISPLAY = {"武僧": "淬势者", "大地武僧": "锻势行者"}

ACTIONS = {}


def register(key):
    """动作注册装饰器。"""
    def deco(fn):
        ACTIONS[key] = fn
        return fn
    return deco


# ================= 动作实现 =================

# 注册顺序 = 执行顺序。apprentice_check 必须最先注册：它是条件型动作（闸门），
# 判定失败/副业未解锁时设置 world._talk_route，消费端据此中断后续动作链——
# 与 v101.23d 前 talk_choice 特判"失败路径零动作执行（consume_item 不扣料）"一致。


@register("apprentice_check")
def action_apprentice_check(world, group_id, qq_id, player, npc_id, action):
    """v81 导师进修：考验判定（检查背包材料）——由 talk_choice 主循环特判迁入注册表。

    条件型动作：判定结果经 world._talk_route / world._talk_tail 通道传出，
    _apply_talk_action_async 返回路由，talk_choice 主循环只做通用分发：
      _talk_route = "__end__" → 副业未解锁直接结束对话（#101.29，不再渲染 fail 节点）
      _talk_route = "fail"    → 材料不足，走选项 fail_next
      通过（不设 route）     → 成功提示放 _talk_tail，待全部动作行之后追加
                                （与旧特判 notices.append("✅…") 的输出顺序一致）
    交互行为（选项显示/失败提示/通过流程）与 v101.23d 前内联特判完全一致。
    """
    check = action["apprentice_check"]
    # #255: 副业未解锁（未拜师）时考验提前拦截——遍历对话树找 unlock_prof 目标副业，
    # 未解锁则材料也不收，避免玩家交完材料才被拦白跑。
    # v167：副业数量上限已解除，此拦截只剩"未拜师"一种情况（位满分支已随上限移除）。
    # #417: 遍历层级 bug——dlg 顶层是 {start, nodes}，必须遍历 nodes 子表
    prof_target = None
    dlg = C.get_dialogue(npc_id)
    for _nid, _node in ((dlg.get("nodes") or {}).items()):
        if not isinstance(_node, dict):
            continue  # 对话树部分节点为纯字符串（跳转别名）
        for _o in (_node.get("options") or []):
            _ua = (_o.get("action") or {}).get("unlock_prof")
            if _ua:
                prof_target = _ua
                break
        if prof_target:
            break
    _npc = _cq.NPCS.get(npc_id) or _wild.ALL_WILD.get(npc_id) or {}
    _name = _npc.get("name", npc_id)
    if prof_target:
        _okp, _msgp = world._prof_active_check(group_id, qq_id, prof_target)
        if not _okp:
            # v101.29：副业未解锁拦截直接结束对话（不再渲染 fail 节点）——旧代码跳
            # fail_next 会渲染"材料凑不齐"类台词，与"副业未解锁先不收材料"的拦截
            # 归因矛盾（小红实测梅尔文交付被抓包）。v167 起仅剩未拜师场景，
            # 提示语已由 _prof_active_check 输出"先去拜师"引导。
            world._talk_route = "__end__"
            return [_msgp + "（这次考验先不收材料，先去拜师解锁再来吧）"]
    have = db.count_item(group_id, qq_id, check.get("item", ""))
    need = int(check.get("count", 1))
    if have >= need:
        world._talk_tail = [f"✅ {_name}满意地点了点头。"]
        return []
    world._talk_route = "fail"
    return [f"{_name}摇头：还差 {need - have} 份{check.get('item', '材料')}，备齐了再来。"]


@register("set_flag")
def action_set_flag(world, group_id, qq_id, player, npc_id, action):
    db.set_talk_flag(group_id, qq_id, npc_id, action["set_flag"])
    return []


@register("give_gold")
def action_give_gold(world, group_id, qq_id, player, npc_id, action):
    # v174 统一抽象：走 grant_reward（保持加金币语义）
    gold = int(action["give_gold"])
    lines = grant_reward({"gold": gold}, group_id, qq_id, player=player)
    return lines or [f"💰 获得金币 ×{gold}"]


@register("give_exp")
def action_give_exp(world, group_id, qq_id, player, npc_id, action):
    # v105 M21 P2：补升级结算——此前只写 exp 不触发 check_player_level_up，
    # 数据一旦使用会跳过升级（潜在雷）；与成就奖励领取同源结算（achievements.py:195-203）
    # v174 统一抽象：走 grant_reward（自动含升级结算）
    exp = int(action["give_exp"])
    lines = grant_reward({"exp": exp}, group_id, qq_id, player=player)
    if not lines:
        lines = [f"✨ 获得经验 +{exp}"]
    return lines


@register("give_item")
def action_give_item(world, group_id, qq_id, player, npc_id, action):
    # #260: 拜师动作同时带 unlock_prof 时，副业未解锁则不发材料（此前 give_item 先于
    # unlock_prof 执行，拦截后材料照发、与解锁不同步）
    skip_give = False
    _up = action.get("unlock_prof")
    if _up:
        _okp, _ = world._prof_active_check(group_id, qq_id, _up)
        skip_give = not _okp
    if skip_give:
        return []
    item = action["give_item"]
    key = item.get("key", "")
    count = int(item.get("count", 1))
    if not key:
        return []
    # v174 统一抽象：走 grant_reward 物品发放（含 data 补全）
    lines = grant_reward({"items": [{"item": key, "n": count}]}, group_id, qq_id, player=player)
    if lines:
        return lines
    return [f"🎒 获得 {key} ×{count}"]


@register("open_shop")
def action_open_shop(world, group_id, qq_id, player, npc_id, action):
    if not action.get("open_shop"):
        return []
    return ["🏪 输入『商店』可以买东西"]


@register("hint")
def action_hint(world, group_id, qq_id, player, npc_id, action):
    if not action.get("hint"):
        return []
    return [action["hint"]]


@register("quest_take")
def action_quest_take(world, group_id, qq_id, player, npc_id, action):
    # 主线：pending → 接取；ready → 交付领奖（_take_main_quest 自动分流）
    if not action.get("quest_take"):
        return []
    npc = _cq.NPCS.get(npc_id) or _wild.ALL_WILD.get(npc_id) or {}
    if not npc:
        return []
    return world._take_main_quest(group_id, qq_id, npc_id, npc)


@register("side_take")
def action_side_take(world, group_id, qq_id, player, npc_id, action):
    # 支线：交付该 NPC 名下所有可交支线（v104 M20 P2：原只交第一条即 break，
    # 玛莎同挂 s1 与 s_board_cat 时寻猫 ready 需重复进对话；现循环交付全部可交）
    if not action.get("side_take"):
        return []
    quests = db.get_quests(group_id, qq_id)
    lines = []
    for sid, sq in list((quests.get("side") or {}).items()):
        sqd = next((q for q in _cq.SIDE_QUESTS if q["id"] == sid), None)
        if not sqd or sqd.get("giver") != npc_id:
            continue
        if sq.get("status") == "done":  # v95.12：已交付支线不再提示/交付
            continue
        obj = sqd.get("objective", {})
        if obj.get("collect"):
            # v104 M20 P2：收集门槛统一 collect_count 优先（与 world.py 面板/交付一致；
            # 复合目标如魔剑士试炼 collect_count=2/count=3，旧口径 count=3 会拒收背包 2/3 的玩家）
            if db.count_item(group_id, qq_id, obj["collect"]) >= obj.get("collect_count", obj.get("count", 1)):
                lines += world._complete_side_quest(group_id, qq_id, sid)
                # 交付后标记本地快照，防同一轮重复交付（_complete_side_quest 已重读 DB 保存）
                sq["status"] = "done"
        elif sq.get("status") == "ready":
            lines += world._complete_side_quest(group_id, qq_id, sid)
            sq["status"] = "done"
    return lines


@register("side_offer")
def action_side_offer(world, group_id, qq_id, player, npc_id, action):
    # v95r65 #288：支线接取入口（有对话树 NPC 的『有活儿要交给我吗』选项）。
    # 走 _offer_side_quests 接该 NPC 名下未接支线（已过滤告示板委托 #295）
    if not action.get("side_offer"):
        return []
    npc = _cq.NPCS.get(npc_id) or _wild.ALL_WILD.get(npc_id) or {}
    if not npc:
        return []
    return world._offer_side_quests(group_id, qq_id, npc_id, npc)


@register("side_take_one")
def action_side_take_one(world, group_id, qq_id, player, npc_id, action):
    """v127.6：对话 side_menu 子选项——单条支线接取（自选，不再全接）。

    与 side_offer 对称，但只接 action['side_take_one'] 指定的那一条；
    走 world._offer_side_quest 校验 sid 在当前可接清单内才落地（防越权）。
    """
    sid = action.get("side_take_one")
    npc = _cq.NPCS.get(npc_id) or _wild.ALL_WILD.get(npc_id) or {}
    if not npc or not sid:
        return []
    return world._offer_side_quest(group_id, qq_id, npc_id, sid)


@register("consume_item")
def action_consume_item(world, group_id, qq_id, player, npc_id, action):
    ci = action["consume_item"]
    key = ci.get("item", "")
    count = int(ci.get("count", 1))
    if not key:
        return []
    db.remove_item(group_id, qq_id, key, count)
    return [f"🎒 交出 {key} ×{count}"]


@register("unlock_prof")
def action_unlock_prof(world, group_id, qq_id, player, npc_id, action):
    prof = action["unlock_prof"]
    appr = list(player.get("apprentices", []))
    if prof in appr:
        return [f"你已经拜过{db.PROF_FIELDS.get(prof, prof)}的导师了。"]
    ok, act_msg = world._prof_active_check(group_id, qq_id, prof)
    if not ok:
        return [act_msg]
    appr.append(prof)
    db.update_player(group_id, qq_id, apprentices=appr)
    # 入门礼：副业经验（unlock_prof 配套 give_prof_exp 时由命令层统一给）
    exp = action.get("give_prof_exp")
    lines = []
    if exp:
        lv, _ = db.add_prof_exp(group_id, qq_id, prof, int(exp))
        lines.append(f"🎓 拜师成功！解锁副业「{db.PROF_FIELDS.get(prof, prof)}」(副业经验 +{exp})")
    else:
        lines.append(f"🎓 拜师成功！解锁副业「{db.PROF_FIELDS.get(prof, prof)}」")
    lines.append(world._tip("profession"))
    return lines


@register("give_prof_exp")
def action_give_prof_exp(world, group_id, qq_id, player, npc_id, action):
    """unlock_prof 的配套参数键（拜师礼副业经验，实际由 unlock_prof 动作消费）。

    v124.3（审计）：注册为 no-op 仅为让 ACTIONS 覆盖数据中全部动作键，
    防 check_action_keys 未知键告警误报（拜师选项均带此键）。"""
    return []


@register("unlock_class")
def action_unlock_class(world, group_id, qq_id, player, npc_id, action):
    # 行会就职：见习冒险者 → 基础职业（属性按新职业重算 + 初始技能）
    new_cls = action["unlock_class"]
    return world._do_join_class(group_id, qq_id, player, new_cls)


@register("tutor_skill")
def action_tutor_skill(world, group_id, qq_id, player, npc_id, action):
    # 导师进阶技能教学：等级门槛 + 金币学费 → 直接学会（不耗技能点）
    # v104 R3 P1-5 修复：对话树写死的 need_lv 可被绕过（实测 Lv.6 学 45 级三连射），
    # 改以 skill_info 真实 lv + branch_skill_owner 转职校验（与 player.py _skill_learn_msg 同源）
    ts = action["tutor_skill"]
    sk_id = ts.get("skill", "")
    cost = int(ts.get("cost", 0))
    info = skill_info(player.get("class_name", ""), sk_id)
    if not info:
        return ["这位导师似乎还没准备好教你……"]
    need_lv = int(info.get("lv", ts.get("need_lv", 1)))
    if player.get("level", 0) < need_lv:
        return [f"导师摇摇头：这套本事要 Lv.{need_lv} 才学得动，你才 Lv.{player.get('level', 1)}，先练练基本功。"]
    # v26 分支专属技能门槛：必须先转职到对应分支（与技能点学习同源）
    owner = branch_skill_owner(player.get("class_name", ""), sk_id)
    if owner:
        need_tier, bname = owner
        my_tier = player.get("class_tier", 0)
        my_path = player.get("evolve_path", 0)
        # v130.2f.2 苦修档位展示名映射（与 player.py _BRANCH_KEY_DISPLAY 同源；分支 key 不动）
        _dn = _BRANCH_DISPLAY.get(bname, bname)
        if my_tier < need_tier or not my_path:
            return [f"导师摇摇头：『{info.get('name', sk_id)}』是 {_dn} 的专属技能，需要先转职为 {_dn} 才能学习！(Lv.30/60/90 可转职)"]
        branches = _cc.CLASSES[player["class_name"]].get("evolve_branches", {}).get(need_tier, [])
        # v112：多分支索引通用化（攻/守 path=1/2；隐藏流派 path=1/2/3）
        idx = max(0, int(my_path or 0) - 1)
        my_branch = branches[idx] if idx < len(branches) else ""
        if my_branch != bname:
                return [f"导师摇摇头：『{info.get('name', sk_id)}』是 {_dn} 的专属技能，你走的是 {_BRANCH_DISPLAY.get(my_branch, my_branch)} 路线，学不了～"]
    if (player.get("gold", 0) or 0) < cost:
        return [f"导师伸出三根手指：学费 {cost} 金币，少一个子儿都不行。(你现在有 {player.get('gold', 0)} 金币)"]
    learned = list(player.get("learned_skills", []))
    sname = info.get("name", sk_id)
    if C.resolve("skills", sname) in [C.resolve("skills", s) for s in learned if s]:
        return [f"『{sname}』你已经学会了，再多练练吧。"]
    db.update_player(group_id, qq_id, gold=(player.get("gold", 0) or 0) - cost,
                     learned_skills=learned + [sname])
    return [
        f"💰 支付学费 {cost} 金币",
        f"✨ 导师悉心传授，你学会了进阶技能『{sname}』！",
        f"「{info['desc']}」",
        world._tip("skill_set"),
    ]


@register("evolve_class")
def action_evolve_class(world, group_id, qq_id, player, npc_id, action):
    # 导师转职：Lv.30/60/90 找对应职业导师对话转职
    ev = action["evolve_class"]
    next_tier = int(ev.get("tier", 1))
    path = int(ev.get("path", 1))
    return world._do_evolve_via_npc(group_id, qq_id, player, next_tier, path)


@register("hidden_evolve")
async def action_hidden_evolve(world, group_id, qq_id, player, npc_id, action):
    # v113 血脉传承：隐藏线导师对话『接受传承』——复用 _evolve_hidden_generic（异步 generator）
    # 种族校验由对话树 need（race_is）前置 + _evolve_hidden_generic 内 src_race 双保险
    # tier 语义：>0 显式指定档位；0/缺省 = 按等级修为继承（40→T1 / 60→T2 / 90→T3）
    ev = action["hidden_evolve"]
    cls_id = ev.get("cls", "")
    tier = int(ev.get("tier", 0) or 0)
    path = int(ev.get("path", 1))
    if tier <= 0:
        # 修为继承：与『转职 别名』同源——当前阶 +1 起，逐档看等级门槛
        _tlv = world._hidden_tier_levels(cls_id)
        _cur = player.get("class_tier", 0)
        _tgt = _cur + 1
        while _tgt <= 3 and player["level"] >= _tlv.get(_tgt, 99999):
            _tgt += 1
        _tgt -= 1
        if _tgt <= _cur:
            _tgt = _cur + 1  # 下一阶都不够 → 交给 generic 报等级不足
        tier = _tgt

    class _Sink:
        """收集 _evolve_hidden_generic 的 plain_result 文本（event 只用于输出）"""
        def __init__(self):
            self.lines = []
        def plain_result(self, text):
            self.lines.append(text)
            return text

    sink = _Sink()
    async for _ in world._evolve_hidden_generic(sink, group_id, qq_id, player, cls_id, tier, path):
        pass
    return sink.lines
