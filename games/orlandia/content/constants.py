# -*- coding: utf-8 -*-
"""《奥兰迪亚·余烬纪年》包内**全局常量单源**（逐字搬自游戏仓 `game/core/constants.py`，208 行）。

真源 = 「改新手村/默认城镇/平衡参数/类型文案只改这一处」的常量收敛点（v98.2/v99.3/v102.x/v138.2/
v181.P2B），外加唯一函数 `prof_exp_need`。宿主 `game/core/constants.py` 现在是薄壳（全名单再导出）。

数值/文案一字未改（数值权威 = 策划案仓 `32_数值设计.md`）。正文改动面：
  ① `CLASS_NOVICE` / `PCT_STATS` / `PCT_CAPS` / `PENE_PCT_STATS` → **切包内读口**
     `content/tables.py`（BRIEF §5「有同名域，可直接切包内读口」；该读口读
     `content/rules/panel_rules.json`，值与本文件原字面量实测逐项相同）——包内不再留第二份。
  ② `ACT_TICK` → `from .mech.we_data import ACT_TICK`（B10 时该常量已随 `WEAPON_EFFECT_DATA`
     落进包内 `content/mech/we_data.py:22`，仍是字面量单源）；宿主薄壳**另留一份字面量**
     `ACT_TICK = 1.0`，因为 `tests/test_package_mech_ports.py:256` 的 TABLES 用 AST **静态读
     宿主文件模块级字面量**与包内 we_data 对拍（宿主改成再导出 → 该门禁报「取不到」）。
     该门禁本身就是这两份的漂移守卫。
  ③ `prof_exp_need` 内 `from ..data import FORMULA_SKELETON` → `_host_attr("data", "FORMULA_SKELETON")`
     （表在宿主数据层；包内 `content/mech/params.py::FORMULA_SKELETON` 是**子集**，只留引擎读的两段）。

缺口（报告登记）：`FORMULA_SKELETON`（宿主句柄，待 B14）；其余常量（约 50 个）是纯值，随本文件
进包后宿主只剩再导出——`scripts/export_game_package.py:684/:2511` 读 `game.core.constants` 的
`SUB_TYPE_*` / `PCT_STATS` / `PCT_CAPS` / `PENE_PCT_STATS`，走薄壳再导出后语义不变（已实测
`--domain panel_rules --check` 与 `--domain maps --check` 同值）。
"""

# ============================================================
# ① 宿主替身口（注入优先 → sys.modules → importlib；**绝不静默空跑**）
#    形状逐字抄 `content/world_cmds.py`（B9 线2 定稿）
# ============================================================
import importlib as _importlib
import sys as _sys

_HOST_PKG = "data.plugins.dragonfall.game"      # 运行时（main.py 的模块路径）
_HOST_PKG_FALLBACK = "game"                     # 测试/工具按 `game.xxx` 直接 import 时
_INJECTED = {}


def bind_host(**objs):
    """宿主薄壳 import 期注入（幂等）——键 = `_HostMod` 的模块名（`content` / `db` / `data`）。"""
    for k, v in (objs or {}).items():
        if v is not None:
            _INJECTED[k] = v


def _host_module(name: str):
    """取宿主子模块（`name` 为空 = 宿主 `game` 包本身）。"""
    if name in _INJECTED:
        return _INJECTED[name]
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        m = _sys.modules.get(prefix if not name else "%s.%s" % (prefix, name))
        if m is not None:
            return m
    last = None
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        try:
            return _importlib.import_module(prefix if not name else "%s.%s" % (prefix, name))
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
                return _importlib.import_module("%s.%s" % (
                    prefix if not mod else "%s.%s" % (prefix, mod), attr))
            except Exception:                   # noqa: BLE001
                continue
        raise


class _HostMod:
    """宿主模块替身（`C` / `db` / `data`）——`C.xxx` 正文一字未改，属性访问时解析。"""

    def __init__(self, name):
        self._name = name

    def __getattr__(self, attr):
        return getattr(_host_module(self._name), attr)

# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年核心层 - constants.py（v98.2：全局常量收敛）

原魔法字符串（"oak_town" 等）散落 8 处代码 + 1 处 SQL，收敛后：
- 改新手村/默认城镇 = 只改这里
- 建号默认值从 SQL 字符串提到代码（可测试、可配置）
"""
# 新手村/默认地图（死亡复活、回城兜底、建号出生点）
START_MAP = "oak_town"
START_SUBAREA = "oak_town_1"

# 建号默认值（原写死在 store/players.py SQL 字符串里）
DEFAULT_GOLD = 50
DEFAULT_ATTR_PTS = 9
DEFAULT_STAMINA = 100

# ================= v99.3 战斗/流程概率常量 =================
# （原散落各文件的裸数字，集中后改平衡参数只动这里）
FLEE_CHANCE = 0.75             # battle.py:538 战斗逃跑成功率
# v130.7 意见#28：逃跑成功率随等级差/速度差修正（battle.py _do_flee：
# 基础 FLEE_CHANCE ± 等级差×FLEE_LEVEL_STEP ± 速度差×FLEE_SPD_STEP，clamp 到 [FLEE_MIN, FLEE_MAX]）
FLEE_LEVEL_STEP = 0.05         # 每 1 级等级差（玩家-敌）修正 ±5%
FLEE_SPD_STEP = 0.01           # 每 1 点速度差（玩家-敌）修正 ±1%
FLEE_MIN = 0.15                # 逃跑成功率下限（敌高我低保底，防完全跑不掉）
FLEE_MAX = 0.95                # 逃跑成功率上限（不保 100% 脱身）
MON_SKILL_CHANCE = 0.3         # battle.py:1294 怪物技能使用概率
MON_SKILL_CRIT = 0.1           # battle.py:1308 怪物技能暴击率
SHIELD_COUNTER_CHANCE = 0.6    # battle.py:1597 v51 盾牌反击概率（反击 120% 伤害）
REFLECT_CHANCE = 0.25          # battle.py:1605 龙鳞套反弹概率（反弹 25% 伤害）
ENCOUNTER_EVENT_CHANCE = 0.35  # combat.py:95 探索随机事件概率（野外/外郊/核心区）
SA_BOSS_CHANCE = 0.05          # combat.py:125/202 子区域 Boss 出现概率
ENCOUNTER_LOW_CHANCE = 0.5     # combat.py:144 普通怪低概率（新手保护）
FISH_RARE_CHANCE = 0.6         # economy.py:785 垂钓宝物箱图纸概率（v135：50% → 60%）
PET_EGG_ORANGE_CHANCE = 0.15   # economy.py:240 月光兔蛋（垂钓传说档）概率
RARE_MAT_CHANCE = 0.10         # economy.py:280 稀有材料额外掉落概率
PROF5_BONUS_CHANCE = 0.3       # economy.py:306 副业 5 级额外产出概率
INST_EVENT_CHANCE = 0.5        # instance.py:278 副本探索事件概率（v141 审计 2026-08-30：
                               # 仍被消费——instance.py:809 陷阱 POI 踩中概率；副本遇怪/事件
                               # 主概率已走 dungeon.discovery_agro 配置 + core/encounter.py
                               # encounter_chance(map_dict, default=0.85)，本常量保留勿删；
                               # 代码默认值只维护在 encounter.py，不在此新增副本遇怪默认值）
MOVE_ENCOUNTER_CHANCE = 0.25   # world.py:2026 移动撞怪概率（world._travel_ambush 用，保留）
# v101.5 新增
STARFALL_STUN_CHANCE = 0.20    # battle_mech.py:258 星陨斩眩晕概率
BOSS_BP_DROP_CHANCE = 0.10    # drops.py:69 Boss 图纸惊喜掉率（v135：5% → 10%，×（1+幸运≤50%）最高 15%）
TRADER_DEAL_CHANCE = 0.5       # event_templates.py:253 流浪商人成交概率
CHEST_BP_CHANCE = 0.85         # item_templates.py:611 探索宝箱图纸概率（v135：50% → 85%）
INSTANCE_BP_CHANCE = 0.10      # instance.py:2390 副本通关全员图纸小概率（v135：每名存活成员独立判定）
# v174 精英专属掉落率（combat.py 击杀精英：名册 ELITE_EQUIP_DROP 命中专属的判定率，
# 与 drops.roll_drop_equip 的 elite 档 15% 一致，防双池叠加膨胀）
ELITE_EQ_DROP_CHANCE = 0.15

# 配方副业等级阶梯（economy.py _craft_prof_need：装备等级 → 副业门槛）
RECIPE_LV_TIERS = (10, 30, 50, 70, 90)

# ================= v102.1 地图/子区域类型常量 =================
# （v102 审计：代码层 15+ 处裸比较中文字符串，收敛后改类型名只动数据+这里）
# 地图 type（data/maps.py）
MAP_TYPE_TOWN = "城镇区域"       # 安全区：可触发 POI，无怪
MAP_TYPE_FIELD = "野外"
MAP_TYPE_INSTANCE = "副本"
MAP_TYPE_HIDDEN = "隐藏区域"
# 子区域 type（data/subareas.py）
SUB_TYPE_TOWN = "城镇"           # 中心广场（首个子区域）
SUB_TYPE_STREET = "城镇街道"     # 如东大街：连广场 + 城镇出口
SUB_TYPE_GATE = "城镇出口"       # 如镇郊：出城/进城落点

# ================= v102.2 物品 type 常量 =================
# （item_templates.infer_template 原裸比较中文 type，收敛后改类型文案只动数据+这里）
ITEM_TYPE_PET_EGG = "宠物蛋"
ITEM_TYPE_MOUNT = "坐骑"

# ================= v126.3 材料大类归并集合 =================
# 配置 type 细分为 18 种（兽材/矿石/草药/精华/宝石/织物/木材/食材/杂物/图纸/鱼/材料/
# 垃圾/宝物/鱼王/收藏/传说/任务道具），『背包 材料』筛选/『使用』材料兜底按大类归并。
# 归并集合 = 采集/掉落可堆叠材料；图纸/鱼/收藏/传说/宝物/鱼王 保留各自类别（专属筛选）。
MATERIAL_KIND_TYPES = frozenset({
    "兽材", "杂物", "食材", "精华", "织物", "宝石", "木材", "矿石",
    "草药", "材料", "任务道具", "垃圾",
})

# ================= v102.3 职业 ID 常量 =================
# （逻辑层 7 处裸比较 class_name == "cls_novice"，收敛后改职业 ID 只动数据+这里）
# ★ B13-L6：原字面量随文件进包即删 → 改读包内读口（`content/tables.py:45 CLASS_NOVICE`，同值）
from .tables import CLASS_NOVICE  # noqa: E402  见习冒险者（行会就职判定/隐藏职业解锁）

# ================= v102.6 属性集合常量 =================
# （19 处裸写 ("crit","dodge") 判断"百分比显示属性"，收敛后改显示规则只动这里）
# ★ B13-L6：23 项原字面量随文件进包即删 → 改读包内读口 `content/tables.py:102`
#   （解 `content/rules/panel_rules.json` 的 `pct_stats`；值实测逐项相同）。
#   原顺序：crit|dodge|precise|pene_phys|pene_magi|tenacity|luck|cdr|elem_res|abyss_res|
#   exp_bonus|gold_bonus|heal_power|shield_power|lifesteal|crit_dmg|block|thorns|
#   phys_reduce|magic_reduce|lifesteal_phys|lifesteal_magi|summon_power
#   （v106.2 治疗/护盾强度 / v106.3 吸血·暴击伤害·格挡 / v106.4 反伤·物魔免·物法吸 + v107 召唤强化）
#   再导出在文件末尾（与 PCT_CAPS / PENE_PCT_STATS 同处）。

# v106：百分比属性上限表（面板聚合 cap 用；crit 0.5 / dodge 0.4 / 其余 0.6 的旧三目表达式统一收敛）
# ★ B13-L6：原字面量（23 项 cap，v106.3/v106.4 吸血30/暴伤100/格挡40/反伤50/物魔免40/
#   物法吸30 + v107 召唤50）随文件进包即删 → 改读包内读口（`content/tables.py:101`，
#   解 `content/rules/panel_rules.json` 的 `pct_caps`；值实测逐项相同）。再导出在文件末尾。

# v106.4：特殊属性——面板 0 时不显示，有加成才显示（防面板爆炸，鱼鱼拍板）
OPTIONAL_STATS = ("lifesteal", "crit_dmg", "block", "thorns", "phys_reduce", "magic_reduce",
                  "lifesteal_phys", "lifesteal_magi", "summon_power",
                  "pene_flat", "pene_mflat",  # v109.2 固定穿透 0 隐藏
                  # v109.2 P1-5：0 值隐藏推广到全部特殊属性（防面板 13 行 0 值爆炸）
                  "pene_phys", "pene_magi", "tenacity", "luck", "cdr",
                  "elem_res", "abyss_res", "exp_bonus", "gold_bonus",
                  "heal_power", "shield_power",
                  "precise")  # v110 P2：精准 0 值隐藏收尾（与 P1-5 同规则）

# v106：百分比穿透属性（多来源乘算合成 1-Π(1-pᵢ)，不加法）
# ★ B13-L6：原字面量随文件进包即删 → 改读包内读口（`content/tables.py:103`，解同 JSON 的
#   `pene_pct_stats`；值实测逐项相同）。再导出在文件末尾。

# ================= v103.3 B3 整数魔法数字 =================
# （第三轮审计 B3：等级阈值/容量/奖励量裸数字，收敛后改数值只动这里）
EVOLVE_LEVELS = {1: 30, 2: 60, 3: 90}      # 转职等级门槛（player.py:405/419/828、world.py:2153、engine.py:633）
EVOLVE_FEES = {1: 500, 2: 2000, 3: 5000}   # 转职重置费用（按当前 tier，player.py:695）
RESET_SKILL_COST = 500                     # 技能洗点费用（player.py:660/752）
DEFAULT_MAX_MP = 50                        # 面板/战斗 max_mp 兜底（battle.py:92/262、combat.py:1329、instance.py:764/765）
PVP_TIMEOUT_SEC = 300                      # PVP 超时秒：5 分钟无行动自动解除（combat.py:1731）
GUILD_EXP_BASE = 300                       # 公会升级经验 = 等级 * 300（social.py:490、store/social.py:394/395）
PROF_EXP_BASE = 20                         # 遗留常量（v105 起由 prof_exp_need 二次曲线取代，保留兼容外部引用）

# ================= vF3 体验调整常量 =================
# （F3 修复 Agent：体验与战斗数值修复（除 Boss 血量）新增的平衡/封顶常量）
STAMINA_RECOVER_INTERVAL = 60               # 体力自然恢复间隔：60s（1 分钟）+1（原 300s 5 分钟，v166 鱼鱼拍板加速）
                                           # 消费点：store/players.py 惰性恢复（:158/:161 已同步使用本常量）
SKILL_PMULT_CAP = 6.0                      # 技能伤害倍率连乘上限（battle.py 阶段七 pmult 封顶，防高倍率配置失控；
                                           # 仅 clamp 技能伤害倍率，不影响暴击/暴伤/幸运一击独立乘区）

# ================= v181.P2B 引擎刻度常量（原 battle.py 模块级 → core 权威单源） =================
# 背景：weapon_effects.py L37 顶层 from ..battle import ACT_TICK + battle_mech.py 六处函数内
# from ..battle import BUFF_TURNS/DEBUFF_TURNS —— core → battle 反向 import。这些是引擎固有
# 刻度常量（非内容数值），收进 core/constants.py 作权威定义；battle.py 改从这里 import
# （保留对外名字），core 各模块也从这里 import——消除 core → battle 反向依赖。
BUFF_TURNS = 3        # 增益默认持续刻
DEBUFF_TURNS = 2      # 减益默认持续刻
# v121 CTB 行动时间轴：全局行动消耗常量
# v152 鱼鱼拍板：总耗时 = 行动间隔（BASE_DELAY/spd）+ 固定动作耗时。
# BASE_DELAY=40 经 sim 标定：普通怪战斗 ~49s（60s 内），紧凑不拖沓。
# （旧 100 在新模型下战斗拖到 113s 太长；40 平衡节奏与速度差稀释）
BASE_DELAY = 40.0     # 行动间隔基数（v152 标定：40 保持战斗节奏）
SPD_CT_CAP = 80.0     # 参与 ct 计算的 spd 软上限（min(spd, cap)）
# v154 鱼鱼拍板：速度影响自己的出招(cast)和收招(recovery)，出招跑完=命中。
# 恢复间隔取消——总行动周期 = 出招 + 收招，速度收益全部收敛到动作快慢。
# SPD_REF = 基准速度：速度 50 时动作耗时 = 数据基础值；>50 变快，<50 变慢。
SPD_REF = 50.0        # v154 基准速度（= v152 参考档）
# v152 CTB 彻底化：刻 → 时刻。ACT_TICK = 1 刻对应的全局时刻数。
# 鱼鱼拍板（2026-08-31）：1 刻 = 1 游戏秒（对齐秒，玩家直观）。
# 所有"持续 N 刻 / CD N 刻"换算为 N × ACT_TICK = N 时刻 = N 游戏秒。
# 引擎内部无"刻"概念，只有全局绝对时刻 _now；"刻"是玩家可见的换算单位（1 刻 = 1 秒）。
from .mech.we_data import ACT_TICK  # noqa: E402  1 刻 = 1.0 时刻 = 1 游戏秒（鱼鱼拍板对齐秒）
# ★ B13-L6：ACT_TICK 的字面量单源已在包内 `content/mech/we_data.py:22`（B10 落），
#   本文件不再留第二份；宿主薄壳**另留一份字面量** `ACT_TICK = 1.0`，因为
#   `tests/test_package_mech_ports.py:256` TABLES 用 AST 静态读宿主文件模块级字面量与
#   包内 we_data 对拍（宿主改纯再导出 → 该门禁报「取不到」）——该门禁即两份的漂移守卫。
# v154：CAST_* 语义从"固定动作耗时"改为"基准耗时"（速度 50 时 = 该值）。
# 实际耗时 = 基准耗时 × (SPD_REF / 实际速度)；速度 50 时 = 基准值。
CAST_ATK = 1.0        # 普攻基准耗时（1 秒 @spd50）
CAST_SKILL = 1.6      # 技能基准耗时（1.6 秒 @spd50，出手更慢）
CAST_ITEM = 1.0       # 道具基准耗时（1 秒 @spd50）
CAST_FOOD = 1.0       # 食物基准耗时（1 秒 @spd50）
CAST_DEFEND = 0.6     # 防御基准耗时（0.6 秒 @spd50，快动作）
CAST_FLEE = 2.0       # 逃跑基准耗时（2 秒 @spd50，慢，易被打断）
CAST_PET_SKILL = 0.8  # 宠物技能基准耗时（0.8 秒 @spd50，出手快）——v154 宠物独立读条

# ================= v138.2 异常体系五律（docs/COMBAT_ENRICH_v138.md §二） =================
# 借鉴《云海猎团》04 章 M4.2「九态异常：积蓄-触发-衰减」三律，加固现有毒/灼烧/流血 DOT：
#   律一 阈值递增：同一异常每次触发后阈值 ×DOT_THRESHOLD_MULT，封顶 DOT_THRESHOLD_CAP 倍基准——
#         防同一构筑「无限复读同一异常」（数值结合 v133 峰值红线精神：连击越久收益越摊薄）
#   律二 每场上限+饱和：每异常每场最多触发 DOT_MAX_TRIGGER[k] 次，达上限置饱和标记；
#         饱和后控制类（freeze/stun/sleep）不再结算（Boss 永不被无限控死），
#         伤害类（poison/burn/bleed/corros）照常结算（异常仍是输出轴）
#   律三 跨阶段保留：阶段转换时 _preserve_debuffs 保留 DOT_PRESERVE_PCT 层数（向下取整）、
#         阈值 ×(1+DOT_PRESERVE_THRESHOLD_BONUS)（进度遗产：转阶段前攒的异常条不白费）
#   律四 异常直伤独立结算：DOT_DEFS 带 true_dmg 的类型走真伤分支——绕过 _enemy_mitigate 的
#         def/mdef 削减（仍走免疫检查 + Boss 护盾层吸收），使异常流成为第二条独立输出轴
#   律五 饱和阈值收敛：饱和后 saturate_mult 逐次 ×DOT_SATURATE_MULT（0.8^t），
#         防极端构筑把异常乘区叠爆（对应 v133 峰值红线 40% 精神）
DOT_THRESHOLD_MULT = 1.3                   # 律一：阈值递增倍率（每次触发后 ×1.3）
DOT_THRESHOLD_CAP = 3.0                    # 律一：阈值封顶（相对首触基准 ×3.0，防无限复读被倍率反噬）
DOT_MAX_TRIGGER = {                        # 律二：每场上限（达上限置饱和标记）
    "poison": 5, "burn": 5, "bleed": 5,    #   伤害类 5 次：单轴输出天花板，配合层数上限 5 层双保险
    "corros": 5,                           #   腐蚀（真伤轴）同样 5 次，与伤害类对齐
    "freeze": 2, "stun": 2, "sleep": 2,    #   控制类 2 次：Boss 每场最多被控 2 次，永不被锁死
}
DOT_PRESERVE_PCT = 0.5                     # 律三：跨阶段保留比例（层数保留 50%，向下取整）
DOT_PRESERVE_THRESHOLD_BONUS = 0.15        # 律三：跨阶段阈值 +15%（新阶段对同一异常略微更抗）
DOT_SATURATE_MULT = 0.8                    # 律五：饱和后乘区收敛倍率（逐次 ×0.8，指数衰减防叠爆）


def prof_exp_need(lv):
    """副业升级经验需求（v105 平衡曲线）：need(lv) = 5*lv² + 15*lv

    P2F-1：系数 a/b 进 data/formula_skeleton.py（FORMULA_SKELETON["prof_exp_need"]，默认 a=5/b=15）。
    函数本体留在 core/constants.py（全文件唯一函数待后续清理批）；延迟导入防装配期循环
    （data._assembly → core.maps → 本模块 时 game.data 尚未完成初始化，同 skill_flat_value 式函数内导入）
    设计意图（2026-08-13 鱼鱼拍板"无脑 x20 不合适"）：
    - 累计 2100 满级（原线性累计 900，无脑 x20 前期过快后期无爬升感）
    - 前期快：Lv.1→2 仅 20（新手第一天解锁基础配方），拜师礼 50 可跳 Lv.2
    - 中段平滑爬升：Lv.2→3=50 / Lv.3→4=90 / Lv.4→5=140 / Lv.5→6=200 / Lv.6→7=270
    - 后期冲刺感：Lv.7→8=350 / Lv.8→9=440 / Lv.9→10=540（史诗→传说配方门槛）
    - 满级周期估算：等待型（可挂机）约 1 个月，制造型（体力限制）约 2-3 个月
    - 存量玩家兼容：exp 按级内进度存储，曲线变更只影响后续升级需求，已满级不受影响
    """
    from .catalog_rules import FORMULA_SKELETON   # ★ B16-W11d：包内门面（原 `_host_attr("data", …)` 检测器盲区形态）
    _p = FORMULA_SKELETON["prof_exp_need"]
    return _p["a"] * lv * lv + _p["b"] * lv


# ------------------------------------------------------------
# 包内读口再导出（BRIEF §5「有同名域，可直接切包内读口」）——原字面量已删，防包内双源
# ------------------------------------------------------------
from .tables import PCT_CAPS, PCT_STATS, PENE_PCT_STATS  # noqa: E402,F401
