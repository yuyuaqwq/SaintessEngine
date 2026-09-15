# -*- coding: utf-8 -*-
"""包内杂项命令门面（`content/misc_cmds.py`）—— 帮助面板 / 新手指引 / 签到 / 成就面板 / 意见箱。

★ B9 L9（2026-09-13）命令层薄壳化：宿主 `game/commands/misc.py`（468 行）只留「注册 + 取玩家 +
调包 + 渲染」，**真实实现正文搬进本模块**。逐命令落点判定（详见 `overnight/B9-L9-misc.md`）：

    帮助 help_cmd      面板 11 份 + 主题表 + 兜底回执 → 本模块（`HELP_PANELS` / `HELP_MAP` / `help_reply`）
                       参数解析（`[At:…]` 前缀剥离 +「帮助/help」前缀）留宿主 = QQ 消息形态适配
    新手指引 game_tip   整段文案 → 本模块常量 `GAME_TIP`
    签到 signin         认领 / 运势 / 幸运符 / 金币 / 节日口径 → `signin_start()`；周奖励档位抽取留宿主
                        （源码级绑定门禁要求 `QUALITY_TIERS.pick_weights(_wq, rng=random)` 字面留在
                        命令层，见报告缺口 ④）；`signin.*` 十条文案留宿主（文案表按命令层 AST 对账）
    成就 achievements   分类 / 进度 / 奖励文案拼装 → `achievement_panel()`；「领取」回执 → `claim_reply()`
                        表与成就点仍由宿主取（源列表序 + `core/achievements.py:achievement_points`，
                        见报告缺口 ②③）
    意见 feedback_cmd   校验 / 频控（30s、≤200 字）/ 入库 → `feedback_precheck()` + `feedback_submit()`
                        Hermes webhook 通知留宿主（宿主集成，非游戏内容）

宿主替身（`bind_host`，与 `content/talk_actions.py` 同款）
--------------------------------------------------------
    `db` = 宿主存储层模块（真源 `from .. import db`）：正文 `db.xxx(...)` 一行未改；
    未注入时按 `sys.modules` 找**已加载**的宿主模块（绝不 import 宿主模块树）。

数据面（读包内域，不 import 宿主内容层）
----------------------------------------
    `content/data/items.json` ← 真源 `game/data/items.py ITEMS`（900 条；MATERIALS 598 条 ⊆ 它）
        · 成就奖励物品名解析（真源 `(C.ITEMS.get(k) or C.MATERIALS.get(k) or {}).get("name", k)`）

    ⚠️ 幸运符的**材料键由宿主给**（`signin_start(..., luck_mat=…)`）：包内没有 materials 域，而材料
    键集**无法从 items 域反推**（实测 598 个材料键里 7 个没有 `mat_` 前缀：`item_edmund_tag` /
    `item_thank_letter` / `i_stone_refine` / `i_stone_upgrade` / `item_dried_flower` /
    `i_stone_blessed` / `item_late_letter`；且 `type='任务道具'` 在材料 73 条与非材料 1 条之间**交叉**）
    —— 两套启发式都**不成立**，故不猜：宿主按 `C.resolve("materials", LUCK_MATERIAL_NAME)` +
    `key in C.MATERIALS` 求值后传入（全仓唯一一次该查表）。见报告 §缺口⑤。

签名里的三个宿主入参（`cfg` / `table` / `points`）分别是：签到数值配置（`game/data/signin_config.py`
SIGNIN_CONFIG，属 L7 域批次）、成就表（`C.ACHIEVEMENTS`，源列表序）、成就点（宿主 core 计算）——
三者的「该进包但还没有域」的理由逐条写在报告 §缺口里，本模块**不复制**任何一份数据。
第四个入参 `luck_mat` = 幸运符的材料键（见上「宿主给」那条）。

不改语义：命中 / 分支 / 阈值 / 文案一字未动；随机流与真源逐位一致（整条签到只 `random.random()` 一次）。
"""
from __future__ import annotations

import json
import os
import random
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))          # <pkg>/content
_DATA_DIR = os.path.join(_HERE, "data")

# 宿主模块名（运行时 `main.py` 的模块路径 = `data.plugins.dragonfall`；测试同样）—— 与
# `content/talk_actions.py` 同口径（B8.2 线1 立的规矩）
_HOST_PKG = "data.plugins.dragonfall.game"
_HOST_PKG_FALLBACK = "game"


def _read_json(path: str, default):
    """读一个 JSON 文件（缺文件 / 坏 JSON / 权限 → default，不抛 —— 与 `content/tables.py` 同款）。"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                        # noqa: BLE001
        return default


# ============================================================
# 宿主替身口（存储层）—— 正文里 `db.xxx(...)` 一行未改
# ============================================================
_HOST_DB = None            # 宿主存储层模块（真源 `from .. import db`）


def bind_host(db=None) -> None:
    """宿主替身注入（幂等；宿主薄壳在 import 期调用）。`db` = 宿主存储层模块。"""
    global _HOST_DB
    if db is not None:
        _HOST_DB = db


def _resolve_host(mod: str):
    """取宿主子模块：注入优先 → 已加载的宿主模块（`sys.modules`，**不 import**）。"""
    for name in ("%s.%s" % (_HOST_PKG, mod), "%s.%s" % (_HOST_PKG_FALLBACK, mod)):
        m = sys.modules.get(name)
        if m is not None:
            return m
    raise RuntimeError(
        "misc_cmds：宿主模块 %s 不可用（未 bind_host 且未加载）—— 拒绝静默空跑" % mod)


class _HostDB:
    """惰性宿主存储层代理（真源 `from .. import db`）——`db.xxx` 正文不动，属性访问时解析。"""

    def __getattr__(self, name):
        return getattr(_HOST_DB if _HOST_DB is not None else _resolve_host("db"), name)


db = _HostDB()


# ============================================================
# ① 帮助面板（11 份，内容侧文本；真源 = 原 `commands/misc.py` 类属性，逐字节照搬）
# ============================================================
CMD_HELP = """⚔️《奥兰迪亚：余烬纪年》指令大全
📌 【常用指令】
━━━━━━━━━━━━
『探索』 去附近转转（遇怪/偶遇） ｜ 『打怪』 战斗入口
『地图』 看周围 ｜ 『位置』 精简导航
『状态』 看属性 ｜ 『背包』 看物品
『物品详情 <名称>』 看详情 ｜ 『技能列表』 看技能
『采集』 『挖掘』 『垂钓』 收集材料 ｜ 『商店』 买东西
『锻造』 做装备 ｜ 『副本』 组队闯关 ｜ 『帮助 <分类>』 分类指令大全
━━━━━━━━━━━━
以下是全部指令：
📚『帮助 <分类>』看该分类全部指令
👥角色系统  🤝 冒险系统
⚔️战斗系统  ✨技能系统
🔨副业系统  🎒物品系统
👫社交系统  🗺️世界系统
❓其他"""

CMD_HELP_CHAR = """⚔️ 【角色】指令
━━━━━━━━━━━━
『注册 <名字> <性别> [种族]』 创建角色（性别必选；职业去行会就职）
『角色』 角色面板（等级/属性/装备/位置）
『属性』 属性明细（基础+加成来源）
『加点 <属性> [次数]』 分配属性点
『洗点』 金币重置属性点
『种族』 种族介绍与天赋
『职业 [名称]』 12 职业速查一览/单职业详情（v130.2g 玩家意见 #1）
『转职』 查看/执行转职（30 级起）
『转职重置』 付费清空转职分支，重新选择
『战力』 战力评估
『排行 [类别]』 等级/战力/副业排行
『注销』 删除角色（二次确认）
💡 属性加点优先级：先看角色面板缺什么，战士加力量、法师加智力"""

CMD_HELP_ADV = """🗺️ 【冒险】指令
━━━━━━━━━━━━
『地图』 当前区域全景（设施/场景/NPC/怪物/可前往）
『位置』 当前精简导航；想赶路请发『赶路』（v128.2 起移除回复 0 捷径）
『赶路 [NPC/怪物/场景/设施]』 只看对应内容+通道，回复序号直接赶路，0 结束（v128.1）
『前往 <地名或序号>』 前往相邻区域
『寻路 <地名>』 查当前位置到目标的最短路径（『问路』同效）
『探索』 野外遇怪/偶遇/事件（城镇安全区无怪）
『休息』 野外露营（恢复部分状态）
『住宿』 城镇旅店（全额恢复）
『时间』 当前时间/季节/天气
『许愿 <经验/金币/材料>』 向流星许愿（探索偶遇流星后限时；许愿井彩蛋走『交互 许愿井』，每日一次）——v105 M23 P2-2 帮助文案与实现对齐
『见闻录』 野外 NPC 见闻收集
『足迹』 我去过的区域明细（城镇/野外子区域+首访日期） 『冒险手册』 冒险经历总览
💡 移动可能撞怪：等级低于地图容易被拦路，高级玩家威慑低级怪"""

CMD_HELP_BATTLE = """⚔️ 【战斗】指令
━━━━━━━━━━━━
『探索』 在野外寻找敌人（城镇安全区无怪）
『攻击』 攻击当前敌人；野外『攻击 @玩家』可发起 PK
『技能 <名称/槽位>』 战斗中使用技能
『技能 <槽位> <编号>』 指定目标：a1/a2敌方、b1/b2友方（『技能1 a2』打2号）
『防御』 本刻减伤 50%
『逃跑』 脱离战斗（Boss/副本锁定无法逃跑）
『使用 <药水>』 战斗中用恢复药水算一刻
『讨伐』 挑战世界 Boss（需到达指定地点）

【PVP】野外可袭击其他玩家；等级差 >10 不能打；击杀变红名 30 分钟（红名不能进安全区），击杀红名者得荣誉；PVP 可『逃跑』脱离，5 分钟无行动自动解除，脱离/击杀后 2 分钟袭击 CD
【副本战斗】2-3 人轮流出手，Boss 有仇恨机制（伤害/治疗拉仇恨，『防御』嘲讽）；超时 2 分钟自动防御"""

CMD_HELP_SKILL = """⚔️ 【技能系统】指令
━━━━━━━━━━━━
『技能』 技能面板（技能点/已学数量）
『技能列表』 全部技能（可翻页『技能列表 2』）
『技能详情 <名称>』 查看单个技能
『技能学习 <名称>』 消耗技能点学会技能
『技能升级 <名称>』 消耗技能点升级（满级依技能 3~5，每级增益增强）
『技能洗点』 500 金币重置技能点
『技能栏』 查看快捷栏（6 格）
『设置技能 <槽位> <技能名>』 配置快捷栏
『流派』 流派方案（一键配置）
💡 战斗中『技能 <槽位>』或『技能 <名称>』施放；学会才能用
💡 转职（30 级）解锁分支专属技能，分支技能强于基础技能；部分技能带【团队】标记，组队副本中全队生效"""

CMD_HELP_PROF = """⚔️ 【副业】指令
━━━━━━━━━━━━
『副业』 副业面板（等级/经验/已激活条数）
『采集』 『挖掘』 『垂钓』 野外副业，越高级地图产出越好
『副业任务』 今日随机 3 选 1 副业任务
『遗忘副业 <名称>』 放弃一条副业（等级清零，重新学/重新选）
『烹饪』 烹饪面板 『烹饪列表』 全部食谱（鱼+药材→料理）
『炼金』 炼金面板 『合成 <药水>』 炼制药水（高等级配方要炼金等级）
『锻造』 当前可锻造列表 『锻造 全部』 全部配方 『锻造 <装备名>』 锻造
『代工 <装备名>』 铁匠代工（材料+3倍金币，不用图纸/锻造等级）
『学习 <图纸名>』 消耗图纸永久解锁套装配方
『配方 <装备名>』 详情
『强化 <装备>』 强化装备（要强化副业 Lv.N 才能强化 +N）
『附魔 <装备> <属性/符文名>』 附魔装备（要附魔副业 Lv.2，属性附魔或打符文）
『套装』 套装查看
💡 副业没有数量限制，可以拜师学全部生活职业，慢慢练级
💡 副业 Lv.3/6/10 有成就和专属称号（大师称号有属性加成）"""

CMD_HELP_ITEM = """🎒 【物品】指令
━━━━━━━━━━━━
『背包 [类型] [页数]』 背包列表（类型：装备/材料/消耗品/符文/宠物蛋/坐骑/图纸/鱼）
『背包筛选 <类型>』 只看某类物品（同『背包 材料』）
『物品详情 <名称/序号>』 查看物品详情
『装备 <序号>』 穿戴 『卸下 <部位>』 脱下
『出售 <名称/序号> [数量]』 卖物品 『出售 材料/装备/全部』 一键批量卖（自动跳过任务/考验材料）
『仓库』 房产仓库 『取出 <序号>』 仓库取物
『商店』 商店列表 『购买 <物品>』 购买商品
『市场』 玩家市场 『上架 <物品> <价格>』 『下架 <编号>』 『购入 <编号>』
『摆卖 <物品/背包序号> <单价> [数量]』 摆摊卖（序号可避免同名；家里=铺面挂机）
『摆换 <物品/背包序号> [数量]』 摆摊以物换物（不带价=只换不卖）
『收摊』 『摊位』 『换 <编号> <物品>』
『拍卖』 神秘拍卖行 『竞拍 <编号> <金币>』
💡 背包翻页：『背包 2』『背包 材料』『背包 装备 2』
💡 购买容错：『购买 治疗药水（中）』全角括号自动转半角，照常买到"""

CMD_HELP_INSTANCE = """🏰 【组队副本】指令
━━━━━━━━━━━━
『组队 <对方名字>』 创建队伍（2 人）
『组队 <对方名字>』 队长再发一次可拉人（上限 4 人）
『队伍』 查看队伍成员 『退队』 离开（队长退队解散）
『副本』 副本列表 / 战斗中查看进度
『副本 <名字>』 开本（单人副本免组队；多人副本需队伍人数达标）
『深入』 副本分层：清完当前层小怪/精英后，推进到下一层
副本内: 『副本地图』 查看当前层地图 『调查 <目标>』 探索机关/宝箱 『撤退』 保留进度离开副本
💡 部分高难/外域副本需要钥匙/信物才能进（『副本 <名字>』可看获取途径；已通关免钥匙）
💡 轮流出手：队员A行动 → 队员B行动 → Boss行动 → 下一轮
💡 Boss 有仇恨：打伤害/奶人会拉仇恨，『防御』嘲讽拉怪并减伤
💡 超时 60 秒自动防御；Boss 锁定无法逃跑；通关有材料/图纸/成就"""

CMD_HELP_SOCIAL = """🤝 【社交】指令
━━━━━━━━━━━━
【阵营】加入阵营 <编号> 阵营任务 阵营商店 阵营排行（Lv.20 起选四大阵营；任务/商店/排行）
【公会】公会 创建公会 加入公会 退出公会 解散公会 公会签到 公会任务 公会捐献 公会排行
【宠物】宠物 宠物改名 喂养 放生（宠物蛋打怪掉落）
【坐骑】坐骑 骑乘 <名称> 下马（精英/Boss 掉缰绳解锁，传送省钱）
【快捷】快捷 快捷绑定 <数字> <指令> 快捷删除 <数字> 快捷清除（发数字即触发）
【冒险手册】冒险手册（冒险经历总览） 足迹（我去过的区域） 图鉴（怪物图鉴别名） 百科 意见 <内容>"""

CMD_HELP_WORLD = """🗺️ 【世界】指令
━━━━━━━━━━━━
【地图】地图 位置 移动 <名称/序号> 探索 休息 住宿 探索进度（查看全大陆探索度）
【见闻】见闻录（野外 NPC 见闻收集） 编年史
【传送】方碑（查看激活列表） 激活（解锁传送点） 传送 <名称/序号>（付费直达）
【任务】任务 主线 每日 接取 对话 <NPC> 交付任务
【事件】事件（查看当前世界事件） 讨伐（世界 Boss，需到达指定地点）
【房产】地契（在售/我的） 买房 <编号> 卖房 回家 出门 拜访 <玩家> 仓库 取出
【探索】探索进度（区域探索度） 足迹（区域足迹明细） 冒险手册（总览/物品/收藏）
【声望】声望 百科（查材料/怪物/地图掉落来源）；声望商店 <势力名>（声望等级解锁专属商品）
【排行】排行 战力
💡 移动可能撞怪：等级低于地图容易被拦路，高级玩家威慑低级怪不撞"""

CMD_HELP_OTHER = """❓ 【其他】指令
━━━━━━━━━━━━
『帮助 <分类>』 指令大全（本分类即『帮助 其他』）
『意见 <内容>』 向格温提建议（会转达给鱼鱼～）
『签到』 每日签到（金币/运势）
『成就』 成就列表 『成就 领取』 一键领取成就奖励
『称号』 称号查看/佩戴 『冒险手册』 冒险总览（区域/怪物/物品/收藏） 『足迹』 区域明细
『图鉴』 怪物图鉴（=『冒险手册 怪物』） 『百科 <关键词>』 查材料/怪物/地图掉落来源
『排行 [类别]』 等级/战力/副业排行"""

# 面板登记（**注册顺序 = 渲染顺序**；宿主薄壳的类属性 = 这里逐个 re-export）
HELP_PANELS = {
    "CMD_HELP": CMD_HELP, "CMD_HELP_CHAR": CMD_HELP_CHAR, "CMD_HELP_ADV": CMD_HELP_ADV,
    "CMD_HELP_BATTLE": CMD_HELP_BATTLE, "CMD_HELP_SKILL": CMD_HELP_SKILL,
    "CMD_HELP_PROF": CMD_HELP_PROF, "CMD_HELP_ITEM": CMD_HELP_ITEM,
    "CMD_HELP_INSTANCE": CMD_HELP_INSTANCE, "CMD_HELP_SOCIAL": CMD_HELP_SOCIAL,
    "CMD_HELP_WORLD": CMD_HELP_WORLD, "CMD_HELP_OTHER": CMD_HELP_OTHER,
}

# 主题 → 面板（真源 `commands/misc.py:_HELP_MAP`，18 键逐条照搬；值 = 上面的面板名）
_HELP_TOPIC_2_PANEL = {
    "角色": "CMD_HELP_CHAR",
    "人物": "CMD_HELP_CHAR",
    "冒险": "CMD_HELP_ADV",
    "世界": "CMD_HELP_WORLD",
    "地图": "CMD_HELP_ADV",
    "战斗": "CMD_HELP_BATTLE",
    "pvp": "CMD_HELP_BATTLE",
    "技能": "CMD_HELP_SKILL",
    "技能系统": "CMD_HELP_SKILL",
    "副业": "CMD_HELP_PROF",
    "生活": "CMD_HELP_PROF",
    "物品": "CMD_HELP_ITEM",
    "背包": "CMD_HELP_ITEM",
    "副本": "CMD_HELP_INSTANCE",
    "组队": "CMD_HELP_INSTANCE",
    "社交": "CMD_HELP_SOCIAL",
    "公会": "CMD_HELP_SOCIAL",
    "其他": "CMD_HELP_OTHER"
}

HELP_MAP = {k: HELP_PANELS[v] for k, v in _HELP_TOPIC_2_PANEL.items()}

# 兜底回执里那句「可用主题」——**逐字**取自真源（顺序即真源字符串的顺序）
HELP_TOPICS = "角色 冒险 战斗 技能 副业 物品 社交 世界 其他"


def help_reply(arg: str) -> str:
    """`帮助 <主题>` 的一整条回执（空主题 → 总览；未收录主题 → 兜底 + 总览）。

    真源 `commands/misc.py:help_cmd` 的 :213-222 逐行等价（宿主只做参数解析后调本函数）。
    """
    if not arg:
        return CMD_HELP
    panel = HELP_MAP.get(arg)
    if panel:
        return panel
    return "没有『%s』帮助主题～可用：%s\n\n%s" % (arg, HELP_TOPICS, CMD_HELP)


# ============================================================
# ② 新手指引（`游戏提示` 命令整段文案；真源 = 原 `commands/misc.py:game_tip` 的字符串）
# ============================================================
GAME_TIP = """📖 【新手指引】刚来到奥兰迪亚的你，可以这样开始：
━━━━━━━━━━━━
① 开局流程：『注册 <名字> <性别>』创建角色 → 在城镇找 NPC 接任务（『任务』看主线）
　 · 打怪练级：『探索』遇敌 → 战斗中用『技能 <名称/序号>』输出
　 · 30 级可『转职』选择职业分支，技能/属性更专精
② 体力规则：探索/战斗/采集等消耗体力，体力为 0 会困在野外
　 · 恢复：城镇『休息』/『住宿』、吃食物（『背包』里的烤肉串等）
③ 常用指令：『背包』看物品 ｜ 『技能列表』看技能 ｜ 『地图』看周围
　 · 『商店』买补给 ｜ 『锻造』做装备 ｜ 『副本』组队闯关
④ 快捷操作：『设置技能 <槽位> <技能名>』放技能栏，战斗中『技能 <槽位>』秒放
　 · 列表类指令（背包/技能/任务）可发『+/-』翻页，发序号可快捷查看
⑤ 副本钥匙：高难副本需要钥匙/信物才能进（如『王陵钥匙』）
　 · 『副本』看每本需求 ｜ 『百科 <钥匙名>』查获取途径 ｜ 已通关可免钥匙
━━━━━━━━━━━━
💡 更多指令见『帮助』；卡住时试试『百科 <材料/怪物/地图/钥匙>』查询～"""


# ============================================================
# ③ 签到（`签到` 命令：认领 + 运势 + 幸运符 + 金币 + 节日口径）
# ============================================================
# 幸运符（内容侧物品名；材料键由宿主求值传入 —— 见文件头「宿主给」那条）
LUCK_MATERIAL_NAME = "幸运符"


def signin_start(group_id, qq_id, today: str, yesterday: str, cfg: dict, luck_mat=None):
    """签到第 1 段：原子认领 → 运势 → 幸运符消解 → 记运势 → 金币（真源 :259-290 逐行等价）。

    返回 `None` = 今日已签（调用方回 `signin.already` 并结束）；
    否则 `{"streak", "total", "fortune", "gold", "festival"}`（周奖励的档位抽取与文案全留宿主）。

    `luck_mat` = 幸运符的材料键（宿主 `C.resolve("materials", LUCK_MATERIAL_NAME)` +
    `key in C.MATERIALS` 求值；包内不猜材料归属，见文件头）。`None` = 真源里「不在 MATERIALS」那支。

    异常**不吞**：`signin_claim`/运势/幸运符/金币这几段在真源里就不在 try 内，异常照原样上抛。
    随机流与真源逐位一致：本函数只抽 1 次 `random.random()`（运势），且用的就是 `random` 模块本身
    （测试对 `random.random` 打桩、对 `random.seed` 定种都照旧生效）。
    """
    _claimed, streak, total = db.signin_claim(group_id, qq_id, today, yesterday)
    if not _claimed:
        return None
    # v87 02 章 7.6：每日运势（签到随机三档：大吉/平/小凶；幸运符可+1 档）
    # v125：阈值数据下沉 signin_config.SIGNIN_CONFIG
    fortune_roll = random.random()
    if fortune_roll < cfg["fortune_bad_th"]:
        fortune = "小凶"   # 15%：当日金币 -10%
    elif fortune_roll < cfg["fortune_good_th"]:
        fortune = "平"     # 40%：无效果
    else:
        fortune = "大吉"   # 45%：当日经验 +10%
    # 幸运符：使用后当日运势+1 档（小凶→平→大吉→大吉）
    if fortune == "小凶":
        if luck_mat is not None and db.count_item(group_id, qq_id, luck_mat) > 0:
            db.remove_item(group_id, qq_id, luck_mat)
            fortune = "平"
    elif fortune == "平":
        if luck_mat is not None and db.count_item(group_id, qq_id, luck_mat) > 0:
            db.remove_item(group_id, qq_id, luck_mat)
            fortune = "大吉"
    db.set_event_state("daily_fortune_%s_%s" % (group_id, qq_id),
                       json.dumps({"date": today, "fortune": fortune}))
    # 连续签到（streak/total 已由 signin_claim 原子算好）
    # v125：奖励数值数据下沉 signin_config.SIGNIN_CONFIG
    gold = cfg["base_gold"] + streak * cfg["streak_gold_step"]
    # 节日庆典：签到奖励翻倍
    cur_evt = db.get_world_event()
    festival = bool(cur_evt and cur_evt["etype"] == "festival")
    if festival:
        gold *= cfg["festival_mult"]
    return {"streak": streak, "total": total, "fortune": fortune, "gold": gold,
            "festival": festival}


# ============================================================
# ④ 成就面板（`成就 [分类|领取]`：总览 / 分类明细 / 领取回执）
# ============================================================
# 成就分类（**顺序 = 面板渲染顺序**，真源 `commands/misc.py:achievements` 的 `cats`）
ACH_CATS = ["战斗", "成长", "探索", "副业", "社交", "隐藏"]
# 奖励 key → 中文（真源 `_RW_CN`）
_RW_CN = {"exp": "经验", "gold": "金币"}


def achievement_panel(raw: str, table, unlocked, claimed, points: int) -> list:
    """成就面板行（真源 `commands/misc.py:achievements` 的 :340-390 逐行等价）。

    `table` = 成就表（`[{id,cat,name,desc,cond,points,reward,…}]`，**源列表序** —— 分类明细的
    渲染顺序即它）；`unlocked`/`claimed` = 已解锁 / 已领取的成就 id 集合（宿主从 DB 取）；
    `points` = 成就点（宿主 core 算）。返回行列表（宿主还要补 "" + 底部随机提示行）。
    """
    cat = raw if raw in ACH_CATS else ""
    achs = [a for a in table if (not cat or a["cat"] == cat)]
    if cat:
        title = "🏅 【成就·%s】" % cat
    else:
        title = "🏅 【成就】"
    total_all = len(table)
    got_all = len(unlocked)
    pending_cnt = len([a for a in table
                       if a["id"] in unlocked and a["id"] not in claimed and a.get("reward")])
    lines = [title, "━━━━━━━━━━━━"]
    if pending_cnt:
        lines.append("🎁 %d 个成就奖励待领取！『成就 领取』一键领取" % pending_cnt)
    if cat:
        lines.append("解锁 %d/%d 个" % (sum(1 for a in achs if a["id"] in unlocked), len(achs)))
        for a in achs:
            mark = "✅" if a["id"] in unlocked else "⬜"
            rw = a.get("reward") or {}
            # v105 M18 P3：奖励 key 显示中文（经验/金币），对齐解锁提示 _reward_txt
            # v140 波2：items 物品奖励也显示（《物品名》×N）
            rw_parts = []
            for k, v in rw.items():
                if k == "items":
                    for _ik, _ic in (v or {}).items():
                        rw_parts.append("%s×%s" % (item_name(_ik), _ic))
                else:
                    rw_parts.append("%s+%s" % (_RW_CN.get(k, k), v))
            rw_txt = "（%s）" % "、".join(rw_parts) if rw_parts else ""
            if a["id"] in unlocked and a["id"] not in claimed and rw:
                mark = "🎁"
            lines.append("%s %s：%s%s" % (mark, a["name"], a["desc"], rw_txt))
    else:
        lines.append("总进度：%d/%d　🏆 成就点：%s" % (got_all, total_all, points))
        for c in ACH_CATS:
            sub = [a for a in table if a["cat"] == c]
            got_c = sum(1 for a in sub if a["id"] in unlocked)
            lines.append("%s %s：%d/%d(『成就 %s』查看明细)"
                         % ("✅" if got_c == len(sub) else "⬜", c, got_c, len(sub), c))
    return lines


def claim_reply(lines, err) -> str:
    """『成就 领取』的一整条回执（真源 :334-338 逐行等价）。"""
    return ("🎁 %s" % err) if err else "\n".join(lines)


# ============================================================
# ⑤ 意见箱（`意见 <内容>`：校验 / 频控 / 入库）
# ============================================================
FEEDBACK_CD_SECONDS = 30           # 同 qq 30 秒内限 1 条（真源 :407 的注释口径）
FEEDBACK_MAX_LEN = 200             # 单条上限（真源 :404）
MSG_EMPTY = """📮 想给格温提建议？发『意见 <你的想法>』就行～
例：『意见 希望能出个坐骑系统』"""
MSG_TOO_LONG = """❌ 意见太长啦(≤200 字)，精简一下再说～"""
MSG_TOO_FAST = """意见发送太频繁，请稍后再试～"""
MSG_SAVE_FAIL = """❌ 意见保存失败，稍后再试试～"""


def _fb_cd_key(qq_id) -> str:
    return "fb_cd_%s" % qq_id


def feedback_precheck(args: str, qq_id, now_ts: float):
    """意见箱前置校验（真源 :401-416 逐行等价）：返回拒绝文案；放行 → `None`。

    频控读 `event_state`（`fb_cd_<qq>`）；读失败/值坏 → 视为「没提过」（真源同款 try/except）。
    """
    if not args:
        return MSG_EMPTY
    if len(args) > FEEDBACK_MAX_LEN:
        return MSG_TOO_LONG
    # q11 低风险项：同 qq 30 秒内限 1 条（意见箱防刷屏），沿用 event_state 存末次提交时间戳
    try:
        _last_ts = float(db.get_event_state(_fb_cd_key(qq_id)) or 0)
    except (TypeError, ValueError):
        _last_ts = 0.0
    if now_ts - _last_ts < FEEDBACK_CD_SECONDS:
        return MSG_TOO_FAST
    return None


def feedback_submit(group_id, qq_id, args: str, now_ts: float) -> dict:
    """入库 + 记频控时间戳 + 回执文案（真源 :417-425 逐行等价；异常**不吞**，调用方记日志 + 回执）。"""
    fid = db.add_feedback(qq_id, group_id, args)
    # 持续成功的频控：仅成功后更新时间戳，避免失败的尝试锁住玩家再次提交
    db.set_event_state(_fb_cd_key(qq_id), str(now_ts))
    text = ("📮 收到你的意见啦！(编号 #%s)\n「%s」\n\n"
            "我会整理给鱼鱼看的，感谢你让这个世界变得更好✂️" % (fid, args))
    return {"fid": fid, "text": text}


# ============================================================
# ⑥ 物品域读口（items.json；惰性加载）
# ============================================================
_ITEMS = None


def _items() -> dict:
    """包内 items 域（`content/data/items.json`，900 条）—— 惰性加载（没用到就不读）。"""
    global _ITEMS
    if _ITEMS is None:
        _ITEMS = _read_json(os.path.join(_DATA_DIR, "items.json"), {}) or {}
    return _ITEMS


def item_name(key: str) -> str:
    """物品 key → 显示名；查不到 / 非对象 → **原样返回 key**。

    真源 `(C.ITEMS.get(k) or C.MATERIALS.get(k) or {}).get("name", k)` 的等价口：items 域 =
    `ITEMS` 全量且 `MATERIALS ⊆ ITEMS`（导出器已证），故一次查表与真源两次查表逐条等价。
    """
    ent = _items().get(key)
    if isinstance(ent, dict):
        return ent.get("name", key)
    return key
