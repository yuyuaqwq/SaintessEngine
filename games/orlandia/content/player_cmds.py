# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— player 命令域实现（B11 L3 薄壳化，2026-09-14）。

真源：游戏仓 `game/commands/player.py`（1932 行）的 `class PlayerCmds`。本模块 = 那个类的
**实现本体**（35 个方法逐字搬成模块级函数，只去 4 空格缩进）+ 3 个模块级项
（`_tutor_mentor` / `_RES_CN` / `_BRANCH_KEY_DISPLAY`）。宿主 `game/commands/player.py`
现在只剩 4 件事：命令注册（`@declared`）· 取玩家（`self._uid` / `self._player`）· 一行转发调包 · 渲染。

搬的边界
--------
* **搬**：35 个方法全部（22 个命令入口的**实现体** + 13 个私有方法），含 `register` / `evolve` /
  `_evolve_hidden_generic` / `_skill_detail_message` / `_skill_upgrade_gains` 等重逻辑。
* **不搬**：命令入口的装饰器与守卫（`@declared` 是宿主侧**注册**动作：正则来自
  `game/data/command_specs.json`，框架注册表 + `_registry` 都从它派生）；`tests/_command_table_freeze.json`
  锁的「有效指令表」逐字不变。

正文改动面（**只有五类，全部登记**；差异面自检 `overnight/w1213_l3_check.py`）
------------------------------------------------------------------------
1. 函数体内**宿主 import** → 同位置惰性替身（4 行）：
   `from . import _identity` → `_identity = _host_module("commands._identity")`；
   `from .combat import CombatCmds` → `CombatCmds = _host_attr("commands.combat", "CombatCmds")`；
   `from ..core.race_talent_display import format_talent`（2 处）→ `_host_attr(...)`；
   `from ..core.battle_cond_labels import COND_LABELS` → `_host_attr(...)`。
2. 命令开头那两行「取 (group_id, qq_id) + `self._player(...)`」→ 提到宿主薄壳当参数传进来（20 个命令；
   `bind_identity` / `races` 无此行，包内签名与宿主一致）。
3. 数据读口（I1）：`C.display(...)`（13）· `C.resolve("classes"/"skills", ...)`（4）·
   `C.CLASS_NOVICE`（7）· `C.PCT_STATS`（2）→ **包内读口** `content/tables.py` 的同名符号。
   等价性实测：`display`/`resolve` 在 classes 400 输入 / skills 415 输入上 **0 处不等**
   （`overnight/w1213_l3_probe.py`）。
4. `db` / `C`（宿主聚合层）→ `_HostMod` 惰性代理。**B14-2 L3（2026-09-14）已把本文件 63 处数据读点
   切到包内门面**（`from . import catalog_{core,quests,space} as _cat_*`；只改「取值来源」，
   数值 / 文案 / 遍历顺序一字未动）。残余 `C` 只服务函数读口 + 2 张缺口表（见下）。
5. 技能详情 `from .combat import CombatCmds` 那处：宿主 `CombatCmds._EFFECT_CN` 是**类级常量表**，
   B10 L5 已定「常量表原样留宿主类」（包内 `self._X` 读同一份）→ 本模块经上表第 1 类替身读同一对象。

⚠️ 缺口（报告同步登记）—— **没切**的读点及理由
--------------------------------------------------
* **B14-2 L3 已切**（门面 = `content/catalog_{core,quests,space}.py`；下面这段旧记录的「域是字典序 /
  声明序没处存」问题已由门面的显式声明序 `_ORDER_*` 解决，`b14_catalog_gate.py` 对 33 名实测
  **OK 29 · 门面缺 4 · 不等 0**）：`CLASSES` `RACES` `PLAYER_SKILLS` `BRANCH_SKILLS`
  `TUTOR_SKILLS` `START_MAP` `START_SUBAREA` `EVOLVE_LEVELS` `EVOLVE_FEES` `RESET_SKILL_COST`
  `OPTIONAL_STATS` `BUILDS` `MAP_BY_ID`（`CLASS_NOVICE` / `PCT_STATS` 走 `tables.py`，门面亦复用同源）。
* **残余 `C.<名>` —— ★ W4（2026-09-14）已清零（原缺口两名切包内门面）**：`C.QUALITY`（1 处：装备面板品质
  颜色/名）· `C.EQUIP_SLOTS`（2 处：装备面板槽位名）→ `content/catalog_b143.py`（B14-3 建 `equipment`
  域，门禁逐键逐值+键序不等 0）。真源宿主 `game/data/equipment.py`；原缺口见 `overnight/W-B14-B.md` / `W-B14-E.md`。
* 函数读口仍是宿主（同一批不改）：`C.resolve("races", …)`（1 处，包内 `tables.resolve` 无 races 索引）·
  `C.check_achievements` · `C.exp_to_next` · ~~`data.battle_rules.EFFECT_RULES`~~（★ W12 收口已切
  包内门面 `catalog_rules.EFFECT_RULES`）。
* **跨线依赖**（按 WAVE11-13_BRIEF §3-B-5：别线在并行搬 → 用宿主句柄惰性替身，别直接 import）：
  `format_talent` → 待 **B13-L6** 落地 `content/race_talent_display.py` 后切包内直取；
  `COND_LABELS` → 待 **B13-L6** 的 `content/battle_cond_labels.py`；
  `C.check_achievements` → 待 **B13-L4**（`achievement_conds` / `achievements` 进包）。
* `EFFECT_RULES`（模块级 `_RES_CN` 用）：宿主 `data/battle_rules.py` 表，包内无同名读口
  （包内 `content/rules/effect_rules.json` 是**引擎 hook 装配面**，不是读口）→ 惰性取宿主属性
  （与 `content/combat_cmds.py:337` 同款），待常数模块进包后切。

包内直取（**不是**宿主）：`display` / `resolve` / `CLASS_NOVICE` / `PCT_STATS`（`content/tables.py`）·
`player_final_stats` / `player_stats_detail` / `race_name` / `race_stats` / `skill_learn_cost_for`
（`content/panel.py`，D3 批逐字端口）· `_sk_table` / `branch_path_index` / `branch_skill_owner` /
`is_skill_learned` / `skill_info` / `skill_level_of` / `skill_upgrade_cost`（`content/skills.py`，同批端口）·
`skill_*` 纯公式 / `translate_expr` / `Battle` / `actor_stats`（引擎公开 API）。
"""
from __future__ import annotations

import importlib
import json
import re
import sys
import time

from saintess_engine.battle.formulas import skill_buff_turns, skill_cond_mult, skill_expr_preview, skill_formula_expr, skill_formula_expr_for_seg, skill_lifesteal_pct, skill_max_level, skill_mech_val, skill_power_mult

from .panel import player_final_stats, player_stats_detail, race_name, race_stats, skill_learn_cost_for
from .skills import _sk_table, branch_path_index, branch_skill_owner, is_skill_learned, skill_info, skill_level_of, skill_upgrade_cost
from .tables import CLASS_NOVICE, PCT_STATS, display, resolve

# B14-2 L3：数据读点切包内门面（宿主 game/data 删后仍可活；缺口名仍走 C）
from . import catalog_core as _cat_core
from . import catalog_quests as _cat_quests
from . import catalog_space as _cat_space
# ★ W4（2026-09-14）：原缺口两名切包内门面 —— `QUALITY` / `EQUIP_SLOTS`
from . import catalog_b143 as _cat_b143


# ============================================================
# ① 宿主替身口（注入优先 → sys.modules → importlib；**绝不静默空跑**）
#    —— 与 `content/world_cmds.py` / `content/combat_cmds.py` 同款（B8.2 线3 `bind_host` 约定）
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
    raise RuntimeError("player_cmds：宿主模块 %s 取不到（%s）——拒绝静默空跑" % (name, last))


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


C = _HostMod("content")     # 真源 `from .. import content as C`（聚合层**同对象**）
db = _HostMod("db")         # 真源 `from .. import db`

# W12 收口：真源宿主顶层 `from ..data.battle_rules import EFFECT_RULES`（资源名单源）
#   → 包内门面直取（`rules/effect_rules.json`，85 条；键序由门面序声明守卫）
#   对拍：`overnight/_w12_precheck_sources.py` B → OK（逐值 + 键序，对真源模块；宿主聚合层未导出该名）
from . import catalog_rules as _cat_rules   # noqa: E402
EFFECT_RULES = _cat_rules.EFFECT_RULES


# ============================================================
# ② 模块级项（逐字搬自宿主 player.py 顶层；原文顺序 + 原文注释）
# ============================================================

# v101.20 职业导师专属技能：TUTOR_SKILLS 只能导师教学学会，
# 『技能学习』拦截提示（不进技能列表/不可技能点学）
# v112 数据驱动收敛（D4）：导师名/地点下沉 CLASSES[职业]["tutor"]，逻辑层只读数据
def _tutor_mentor(cls_id: str):
    """职业导师 (导师名, 所在城市)。未配置兜底通用文案。"""
    return _cat_core.CLASSES.get(cls_id, {}).get("tutor", ("职业导师", "各城"))


# v112：核心资源 key → 中文名（skill 消耗展示用，新增资源只改数据）
# v181.M-R2c：数据源改 EFFECT_RULES（battle_rules.py 资源名/cap 单源；原 data/core_resources.py
#   已退役删除）。只收带 name 的效果条目（dragon_mark/curse/burn 等效果类无 name 不参与资源名展示，
#   同旧表「仅职业/副资源条目有 name」口径并扩及 zhan_yi/连段/奥术 等新注册名）；未命中 key 兜底原样。
_RES_CN = {k: v.get("name") for k, v in EFFECT_RULES.items() if v.get("name")}


# v130.2f.2 苦修档位改名收尾（展示层）：evolve_branches 分支 key（与 skills.py BRANCH_SKILLS
# 强耦合、绝不可动）→ 新档位展示名。仅苦修线：T1 武僧→淬势者、T2 大地武僧→锻势行者
# （T3「撼岳者」key=展示名无需映射）；其他线分支 key 即展示名，不映射、不动。
_BRANCH_KEY_DISPLAY = {
    "武僧": "淬势者",
    "大地武僧": "锻势行者",
}


# ============================================================
# ③ 类方法（35 个 = 命令 22 + 私有 13）—— 逐字搬自宿主 `class PlayerCmds`
# ============================================================


async def shortcut(self, event: AstrMessageEvent, group_id, qq_id, player):
    """快捷指令：绑定数字一键执行常用指令(如『快捷绑定 1 探索』，之后发『1』=探索)"""
    shortcuts = player.get("shortcuts") or {}
    args = self._strip_cmd(event, "快捷").strip()
    # 子命令：绑定/列表/删除/清除
    sub = ""
    rest = args
    for s in ("绑定", "删除", "清除", "列表"):
        if args.startswith(s):
            sub = s
            rest = args[len(s):].strip()
            break
    if sub == "绑定":
        parts = rest.split(maxsplit=1)
        if len(parts) < 2:
            yield event.plain_result("📎 用法：『快捷绑定 <数字/字母/符号> <指令>』，如『快捷绑定 1 探索』『快捷绑定 n 前往』『快捷绑定 . 攻击』\n数字 0-99 全量触发；字母/符号可带参数（绑『n 前往』发『n3』=前往 3）")
            return
        # v123b：数字 key 限 1-2 位（0-99 全量匹配）；字母 key 1-8 位（字母开头可带数字，
        # 前缀匹配+后缀透传）；单字符符号 key（v123c，排除翻页/At 冲突符号）。全角数字归一，字母统一小写。
        key = parts[0].strip()
        if key.isdigit() or (key and all(ch in "０-９" for ch in key)):
            key = str(int(key))
            if len(key) > 2:
                yield event.plain_result("❌ 快捷数字限 1-2 位（0-99）～（3 位以上数字只能全量匹配，发『13』不会拆成『1』+『3』）")
                return
        elif re.fullmatch(r"[a-zA-Z][a-zA-Z0-9]{0,7}", key):
            key = key.lower()
        elif len(key) == 1 and not key.isdigit() and key not in "+＋-－=＝@[／/" \
                and not ("\u4e00" <= key <= "\u9fff"):
            # v123c：单字符符号键（含全角标点），排除翻页快捷键（+－-=＝）、
            # At/引用前缀（@[）、斜杠（潜在消息解析冲突）、中文汉字（正则层不支持，防死绑定）
            pass
        else:
            yield event.plain_result("📎 快捷键限：数字 0-99（全量触发）、1-8 位字母开头键、或单字符符号（如 . ! # *）～（+ - = 是翻页快捷键，@ [ / 不可用）")
            return
        cmd_text = parts[1].strip()
        if len(cmd_text) > 30:
            yield event.plain_result("❌ 指令太长啦(≤30 字)～")
            return
        if cmd_text.isdigit():
            yield event.plain_result("❌ 不能绑定纯数字指令，防止连环跳转～")
            return
        if self._find_handler(cmd_text) is None:
            yield event.plain_result(f"❌ 『{cmd_text}』不是有效指令，先看看『帮助』确认指令名～")
            return
        shortcuts[key] = cmd_text
        db.update_player(group_id, qq_id, shortcuts=shortcuts)
        yield event.plain_result(f"✅ 快捷 {key} → 『{cmd_text}』 绑定成功！以后直接发『{key}』就行✂️")
        return
    if sub == "删除":
        num = rest.split()[0] if rest else ""
        if num and num in shortcuts:
            del shortcuts[num]
            db.update_player(group_id, qq_id, shortcuts=shortcuts)
            yield event.plain_result(f"🗑️ 快捷 {num} 已删除～")
        else:
            yield event.plain_result("❌ 没有这个快捷绑定。『快捷列表』看看～")
        return
    if sub == "清除":
        if not shortcuts:
            yield event.plain_result("还没有任何快捷绑定～")
            return
        db.update_player(group_id, qq_id, shortcuts={})
        yield event.plain_result("🧹 全部快捷已清除～")
        return
    # 默认：列表
    if not shortcuts:
        yield event.plain_result(
            "⚡ 快捷指令：把常用指令绑到数字/字母，一键执行！\n"
            "用法：『快捷绑定 1 探索』→ 之后发『1』就是探索（数字全量匹配，绑『13』发『13』才触发）\n"
            "『快捷绑定 n 前往』→ 发『n』=前往，发『n3』=前往 3（字母支持后缀参数）\n"
            "『快捷绑定 2 技能1』→ 发『2』= 技能栏第 1 格\n"
            "支持：快捷列表 / 快捷删除 <键> / 快捷清除"
        )
        return
    lines = [f"⚡ {qq_id} 的快捷({len(shortcuts)} 个)："]
    for num in sorted(shortcuts.keys(), key=lambda x: (0, int(x)) if x.isdigit() else (1, x)):
        lines.append(f"  {num} → {shortcuts[num]}")
    lines.append("『快捷绑定 <数字/字母> <指令>』新增，『快捷删除 <键>』删除")
    yield event.plain_result("\n".join(lines))

async def shortcut_trigger(self, event: AstrMessageEvent, group_id, qq_id, player):
    """数字/字母开头消息：查玩家的快捷绑定并转发执行（v123b 数字全量/字母前缀）"""
    if not player:
        return
    shortcuts = player.get("shortcuts") or {}
    msg = event.get_message_str().strip()
    msg = re.sub(r"^\[At:[^\]]*\]\s*", "", msg).strip()
    if not msg:
        return
    # 内置英文指令保护：gm_ 系列 / help 不进快捷（玩家绑『g』『h』也不抢）
    if msg.startswith("gm_") or msg == "help" or msg.startswith("help "):
        return
    # v123c 防御：翻页快捷键（+－-=＝）/ At / 引用 / 斜杠 开头不进快捷（正则层已排除，此处双保险）
    if msg[0] in "+＋-－=＝@[/":
        return
    m = re.match(r"([0-9０-９]\d*|[a-zA-Z][a-zA-Z0-9]*|[^\s0-9０-９a-zA-Z\u4e00-\u9fff])", msg)
    if not m:
        return
    head = m.group(1)
    tail = msg[m.end():].strip()
    if head[0].isdigit():
        # 数字：全量匹配——整段归一查表，不拆后缀（绑『13』发『13』触发；绑『1』发『13』静默）
        num = str(int(head))
        cmd_text = shortcuts.get(num)
        if cmd_text is None:
            return
        async for r in self._run_shortcut(event, cmd_text):
            yield r
        return
    # 字母/符号/中文单字：最长前缀匹配（goto3 → goto → got → ...），剩余部分并入后缀；
    # 字母统一小写归一，符号/中文原样查表（v123c）
    h = head.lower() if re.fullmatch(r"[a-zA-Z][a-zA-Z0-9]*", head) else head
    key = None
    suffix = tail
    for i in range(len(h), 0, -1):
        cand = h[:i]
        if cand in shortcuts:
            key = cand
            suffix = (h[i:] + " " + tail).strip()
            break
    if key is None:
        return
    cmd_text = shortcuts[key]
    if suffix:
        # v123b/c：字母/符号/中文键后缀透传（『n3』→『前往 3』，『.3』→『攻击 3』）
        async for r in self._run_shortcut(event, f"{cmd_text} {suffix}"):
            yield r
    else:
        async for r in self._run_shortcut(event, cmd_text):
            yield r

async def page_flip(self, event: AstrMessageEvent, group_id, qq_id):
    """v123 翻页快捷键：+ 下一页 / - 上一页 / =n 跳页（转发重建指令执行，零侵入渲染）

    v127.4：去掉 @require_player()——翻页是列表序号的延续交互（已注册玩家专属，
    靠 last_list_{qq_id} 状态），未注册用户发『+』『-』不应被"你还没有角色"打扰
    （鱼鱼反馈，与 npc_quick_dialog 同类），改为函数内对未注册静默 return。
    """
    # v127.4：未注册玩家无列表可翻 → 静默放行，免"未注册"打扰
    if not self._player(group_id, qq_id):
        return
    msg = event.get_message_str().strip()
    msg = re.sub(r"^\[At:[^\]]*\]\s*", "", msg)
    op = msg[0]
    digits = msg[1:].strip()
    # v123：+/- 无数字 → ±1 页；= 无数字 → 提示用法
    n = int(digits) if digits else (1 if op in "+＋-－" else None)
    if op in "=＝" and n is None:
        yield event.plain_result("📄 跳页用法：『=页数』，如『=3』跳第 3 页～")
        self._stop_event_safe(event)
        return
    saved = {}
    try:
        raw = db.get_event_state(f"last_list_{qq_id}")
        if raw:
            saved = json.loads(raw)
    except Exception:
        saved = {}
    cmd = saved.get("cmd")
    if not cmd:
        yield event.plain_result("📄 先打开一个列表（『背包』『技能列表』『任务』等）再发翻页快捷键～")
        self._stop_event_safe(event)
        return
    page = int(saved.get("page") or 1)
    pages = int(saved.get("pages") or 1)
    if op in "+＋":
        new_page = page + n
    elif op in "-－":
        new_page = page - n
    else:
        new_page = n
    new_page = max(1, min(new_page, pages))
    text = f"{cmd} {new_page}"
    async for r in self._run_shortcut(event, text):
        yield r
    self._stop_event_safe(event)

async def register(self, event: AstrMessageEvent, group_id, qq_id):
    _args = self._strip_cmd(event, "注册").split(maxsplit=3)
    first = _args[0] if _args else ""
    rest = _args[1] if len(_args) > 1 else ""
    race_arg = _args[2] if len(_args) > 2 else ""
    gender_arg = _args[3] if len(_args) > 3 else ""
    if self._player(group_id, qq_id):
        yield event.plain_result("你已经注册过角色啦！输入『角色』查看～")
        return
    first = first.strip()
    # v95.23 双格式注册：
    #   旧格式 注册 <职业> <名字> [种族] —— 兼容保留（直接带职业）
    #   新格式 注册 <名字> [种族] —— 见习冒险者，去行会/导师处就职职业
    # v95.24 性别系统：注册必选性别（男/女），种族从剩余参数中解析。
    #   旧格式 注册 <职业> <名字> [种族] <性别>；新格式 注册 <名字> <性别> [种族]。
    #   种族与性别可任意顺序，种族可省略（默认人类），性别必选（v95.26 强制），
    #   如『注册 格温 女 精灵』『注册 格温 女』『注册 战士 勇者 男』。
    GENDER_MAP = {"男": "male", "male": "male", "♂": "male", "m": "male",
                  "女": "female", "female": "female", "♀": "female", "f": "female"}
    cls_id = resolve("classes", first)
    class_name = first
    name = rest
    glued = False
    if cls_id not in _cat_core.CLASSES:
        # 无空格注册兼容：职业名与角色名粘在一起（如"注册战士格温"）
        for cid, cinfo in _cat_core.CLASSES.items():
            cn = cinfo.get("name", cid)
            if first.startswith(cn) and len(first) > len(cn) + 1:
                # v105 P1(M01#3)：粘连剩余段必须 ≥2 字才算旧格式粘连——
                # 『注册 战士格温 女』→ 名字"格温"；『注册 战士长 女』『注册 法师塔 男』
                # 剩余 1 字是名字尾巴（用户本意新格式见习+名字"战士长/法师塔"），
                # 按新格式处理（下方 v105 P2 分支把 1 字剩余解除粘连）。
                # v104 P1：名字只取职业名之后部分，rest 保留给下方性别/种族解析。
                # 旧实现把 rest 拼进名字（"注册 战士格温 女" → 名字变"格温 女"），
                # 且非见习分支 extra 不含 rest → 性别丢失恒报"请选择性别"。
                name = first[len(cn):]
                glued = True
                cls_id = cid
                class_name = cn
                break
        else:
            # v95.23 新格式：名字 [种族] → 见习冒险者（剩余参数统一在下方解析种族/性别）
            cls_id = CLASS_NOVICE
            class_name = ""
            name = first
    # v105 P1(M01#3)：粘连剩余段仅 1 字 → 解除粘连，整词按新格式名字处理
    # （『注册 战士长 女』名字=战士长/见习；『注册 法师塔 男』名字=法师塔/见习）
    if glued and len(name) < 2:
        glued = False
        cls_id = CLASS_NOVICE
        class_name = ""
        name = first
    # v105 P2(M01)：角色名恰等于职业名（『注册 战士 女』）——名字槽是性别词/空时
    # 旧格式解析必失败（"名字不能为空"），按新格式处理：名字=职业名，职业转见习。
    # 注：性别词永不可能成为合法名字槽（性别强制必选），故可安全拦截。
    if not glued and cls_id in _cat_core.CLASSES and cls_id != CLASS_NOVICE:
        _nm = (name or "").strip()
        if not _nm or _nm.lower() in GENDER_MAP:
            cls_id = CLASS_NOVICE
            class_name = ""
            name = first
    if cls_id not in _cat_core.CLASSES:
        avail = "、".join(cinfo.get("name", cid) for cid, cinfo in _cat_core.CLASSES.items())
        yield event.plain_result(f"未知职业『{class_name}』！可选职业：{avail}")
        return
    # v83 22 章：隐藏职业不可直接注册（需传承解锁）
    if _cat_core.CLASSES.get(cls_id, {}).get("hidden"):
        avail = "、".join(cinfo.get("name", cid) for cid, cinfo in _cat_core.CLASSES.items())
        yield event.plain_result(
            f"『{class_name}』是传说中才会出现的隐藏职业，普通人无法选择……\n"
            f"💡 世界深处藏着它的线索(隐藏成就/隐藏区域)。可选职业：{avail}"
        )
        return
    # v95.24 性别系统：注册必选性别（男/女），种族从剩余参数中解析。
    #   旧格式 注册 <职业> <名字> [种族] <性别>；新格式 注册 <名字> <性别> [种族]。
    #   种族与性别可任意顺序，种族可省略（默认人类），性别必选（v95.26 强制），
    #   如『注册 格温 女 精灵』『注册 格温 女』『注册 战士 勇者 男』。
    #   （GENDER_MAP 定义见上方解析段，v105 上移供旧格式名字槽判定复用）
    race_id = "human"
    race_display = ""
    gender_id = ""
    _race_done = False
    # 新格式下 rest 可能是种族也可能是性别（如『注册 格温 男』）
    # v104 P1：无空格旧格式（『注册 战士格温 女』）rest 是性别/种族词，必须参与解析；
    # 带空格旧格式（『注册 战士 格温 女』）rest 是名字，种族/性别从 _args[2]/[3] 取。
    extra = [rest, race_arg, gender_arg] if (cls_id == CLASS_NOVICE or glued) else [race_arg, gender_arg]
    for tok in extra:
        if not tok:
            continue
        if not _race_done:
            r = C.resolve("races", tok)
            if r not in _cat_core.RACES:
                # 简称兼容：输入"精灵"匹配"银月精灵"
                r = next((rid for rid, ri in _cat_core.RACES.items() if tok in ri["name"]), r)
            if r in _cat_core.RACES:
                race_id = r
                race_display = _cat_core.RACES[r]["name"]
                _race_done = True
                continue
        g = GENDER_MAP.get(tok.strip().lower())
        if g and not gender_id:
            gender_id = g
            continue
        races_avail = "、".join(ri.get("name", rid) for rid, ri in _cat_core.RACES.items())
        yield event.plain_result(
            f"未知种族或性别『{tok}』！可选种族：{races_avail}，性别：男/女\n"
            f"格式：注册 <名字> <性别> [种族]，如『注册 格温 女 精灵』"
        )
        return
    # v105 P2(M01)：名字超 12 字静默截断 → 显式提示（原实现截断无任何提示）
    _name_raw = name.strip()
    trunc_hint = ""
    if len(_name_raw) > 12:
        name = _name_raw[:12]
        trunc_hint = f"⚠️ 名字超过 12 字，已截断为『{name}』\n\n"
    else:
        name = _name_raw
    # v104 P3：名字槽位是纯性别关键词（如『注册 男』『注册   女 精灵』）→ 视为没起名，
    # 优先报"名字不能为空"而不是"请选择性别"（文案错位）。
    # 注意：性别词永不可能成为合法名字槽（性别强制必选），故可安全拦截。
    if not name or name.lower() in GENDER_MAP:
        yield event.plain_result("名字不能为空！格式：注册 <名字> <性别> [种族]，如『注册 格温 女 精灵』")
        return
    # v95.26 性别强制：注册必须选性别（男/女），无性别直接拒
    if not gender_id:
        yield event.plain_result(
            "请选择性别！格式：注册 <名字> <性别> [种族]，如『注册 格温 女 精灵』（男/女）"
        )
        return
    # v130.7 意见#29：注册重名检查——精确重名即拒（同音/相似名不拦），不落库
    if db.find_player_by_name(name):
        yield event.plain_result("这个名字已经有人用啦，换一个吧～")
        return
    cls = _cat_core.CLASSES[cls_id]
    cls_display = cls.get("name", cls_id)
    # v100.7 注册初始血量必须乘种族倍率（银月精灵月缺 HP-5% 等），否则初始当前生命 > 上限
    st0, _ = player_stats_detail(cls_id, 1, {}, 0, None, 0, None, race_id)
    db.create_player(group_id, qq_id, name, cls_id, cls["base"], st0["max_hp"], st0["max_mp"], race_id, gender_id)
    # v95 #47：注册送 1 技能点 → Lv.1 有 1 点、Lv.2 有 2 点正好学第一个技能（Lv.1/Lv.2 技能 cost=2），断层消除
    db.update_player(group_id, qq_id, skill_points=1)
    # v86 子区域：新手出生落中心广场
    db.update_player(group_id, qq_id, cur_map=_cat_core.START_MAP, cur_subarea=_cat_core.START_SUBAREA)
    db.init_stats(group_id, qq_id)
    db.add_portal(qq_id, _cat_core.START_MAP)  # v10：新手自动激活橡木镇方碑（v83：原维拉方碑旧地图）
    # v12：自动学会初始技能（职业 Lv.1 技能），后续技能用技能点学习
    sk_table = _cat_core.PLAYER_SKILLS.get(cls_id, {}).get("skills", {}) if isinstance(_cat_core.PLAYER_SKILLS.get(cls_id), dict) and "skills" in _cat_core.PLAYER_SKILLS.get(cls_id) else _cat_core.PLAYER_SKILLS.get(cls_id, {})
    init_skills = [s for s, info in sk_table.items() if info["lv"] <= 1]
    if init_skills:
        db.update_player(group_id, qq_id, learned_skills=init_skills)
        # v52 Build：初始技能自动装进技能栏前几格
        bar = list(init_skills[:6])
        while len(bar) < 6:
            bar.append(None)
        db.set_skill_bar(qq_id, bar)
    player = self._player(group_id, qq_id)
    # 阶段九：注册成就（14 章 2.3 冒险者起步）
    C.check_achievements(group_id, qq_id, player)
    init_display = "、".join(display("skills", s) for s in init_skills)
    # 注册欢迎语种族行：图标+名称+天赋明细（#50 种族说明模糊——原本只有一行哲学 desc，
    # 玩家看不出种族实际给什么；改为把天赋逐条列在注册回执，与『种族』一览同口径）
    race_line = ""
    if race_id in _cat_core.RACES:
        _rd = _cat_core.RACES[race_id]
        _tnames = _rd.get("talent_names", {})
        format_talent = _host_attr("core.race_talent_display", "format_talent")
        _tl = []
        for _tk, _tv in (_rd.get("talents") or {}).items():
            _txt = format_talent(_tk, _tv, _tnames.get(_tk, _tk))
            if _txt:
                _tl.append(_txt)
        _talent_s = "；".join(_tl) if _tl else _rd.get("desc", "")
        race_line = (f"种族：{_rd['icon']} {_rd['name']}（{_rd.get('desc','')}）\n"
                     f"   · 天赋：{_talent_s}\n")
    gender_line = f"性别：{'♂ 男' if gender_id == 'male' else '♀ 女'}\n" if gender_id else ""
    if cls_id == CLASS_NOVICE:
        # v95.23 见习冒险者：无职业技能，引导去行会/导师就职
        yield event.plain_result(
            trunc_hint + f"✨ 欢迎来到奥兰迪亚大陆，{name}！\n"
            f"职业：🧭 见习冒险者\n"
            f"{race_line}{gender_line}"
            f"你还没有正式职业，先四处走走、熟悉一下这个世界吧。\n"
            f"━━━━━━━━━━━━\n"
            f"📍 出生点：橡木镇·冒险者广场\n"
            f"　· 『前往 镇长办公处』→『对话 镇长』接取第一个任务\n"
            f"　· 『地图』查看周边\n"
            f"━━━━━━━━━━━━\n"
            f"🌅 广场中央的【橡木方碑】已为你激活！\n"
            f"　· 『方碑』查看详情\n"
            f"　· 『传送』可前往各地路标\n"
            f"━━━━━━━━━━━━\n"
            f"⚔️ 见习冒险者无法学习职业技能，就职后解锁！\n"
            f"　· 去广场找『行会接待员·小艾』就职职业（战士/法师/游侠/牧师/刺客/拳师）\n"
            f"　· 各城还藏着职业导师，可学进阶技能与转职\n"
            f"━━━━━━━━━━━━\n"
            f"🔨 副业系统\n"
            f"　· 『副业』查看状态；找导师『对话 <导师名>』拜师解锁（附近：橡木镇·草药师·艾琳 教采集）\n"
            f"━━━━━━━━━━━━\n"
            f"冒险者，你的故事开始了！"
        )
        return
    yield event.plain_result(
        trunc_hint + f"✨ 欢迎来到奥兰迪亚大陆，{name}！\n"
        f"职业：{cls['icon']} {cls_display}\n"
        f"{race_line}{gender_line}"
        f"『{cls['desc']}』\n"
        f"━━━━━━━━━━━━\n"
        f"📍 出生点：橡木镇·冒险者广场\n"
        f"　· 『前往 镇长办公处』→『对话 镇长』接取第一个任务\n"
        f"　· 『地图』查看周边\n"
        f"━━━━━━━━━━━━\n"
        f"🌅 广场中央的【橡木方碑】已为你激活！\n"
        f"　· 『方碑』查看详情\n"
        f"　· 『传送』可前往各地路标\n"
        f"━━━━━━━━━━━━\n"
        f"⚔️ 已学会初始技能：{init_display}\n"
        f"　· 升级获得技能点，『技能学习 <技能名>』学新技能\n"
        f"　· 各城职业导师可学进阶技能，Lv.30/60/90 可转职\n"
        f"━━━━━━━━━━━━\n"
        f"🔨 副业系统\n"
        f"　· 『副业』查看状态；找导师『对话 <导师名>』拜师解锁（附近：橡木镇·草药师·艾琳 教采集）\n"
        f"━━━━━━━━━━━━\n"
        f"冒险者，你的故事开始了！"
    )

async def bind_identity(self, event: AstrMessageEvent):
    _identity = _host_module("commands._identity")
    raw_sender = event.get_sender_id() or ""
    # 已经是 QQ 号（旧平台或已映射）→ 无需绑定
    if not _identity.is_openid(raw_sender):
        group_id, qq_id = self._uid(event)
        yield event.plain_result(
            f"✅ 你当前的平台身份 {raw_sender} 已是 QQ 号，无需绑定～"
            if _identity.is_qq_id(raw_sender)
            else "⚠️ 当前消息没有识别到 openid，请确认是在新的官方 bot 上发送。"
        )
        return
    args = self._strip_cmd(event, "绑定身份").split(maxsplit=2)
    if len(args) < 2:
        yield event.plain_result(
            "📎 老玩家身份认领：『绑定身份 <QQ号> <角色名>』\n"
            "例：『绑定身份 1454832774 鱼冻不冻阿』\n"
            "绑定后你的等级/装备/金币会以老角色继续～\n"
            "（需 QQ号+角色名 匹配验证，防冒领；不确定角色名可先问 GM）"
        )
        return
    qq_target, name_target = args[0].strip(), args[1].strip()
    if not _identity.is_qq_id(qq_target):
        yield event.plain_result(f"❌ {qq_target} 不是合法 QQ 号～")
        return
    # 校验：该 QQ 号下的角色名是否匹配
    hit = db.find_player_by_name(name_target)
    if not hit:
        yield event.plain_result(
            f"❌ 没找到叫『{name_target}』的冒险者。\n"
            f"检查角色名是否一致（含符号/空格）；若确实没有老角色，直接『注册』开新号即可。"
        )
        return
    if str(hit.get("qq_id")) != qq_target:
        yield event.plain_result(
            f"❌ 『{name_target}』不是 QQ {qq_target} 的角色，绑定失败（防冒领）。\n"
            f"确认你的老 QQ 号和角色名是否记错；仍无法绑定可找 GM 用 gm_绑身份 处理。"
        )
        return
    # 双重校验：若目标 QQ 已有其他 openid 绑定，提示先解绑（避免一人多号混淆）
    old_oid = _identity.qq_to_openid(qq_target)
    if old_oid and old_oid != raw_sender:
        yield event.plain_result(
            f"⚠️ QQ {qq_target} 已被另一个 openid（{old_oid[:8]}…）绑定。\n"
            f"如果你就是本人（换设备/重复绑定），找 GM 确认后处理，防止误绑。"
        )
        return
    _identity.bind(raw_sender, qq_target)
    yield event.plain_result(
        f"✅ 绑定成功！你将以 QQ {qq_target} 的身份继续冒险～\n"
        f"角色『{hit.get('name')}』的数据（等级/装备/金币/任务）已续接，输入『角色』查看！"
    )

async def profile(self, event: AstrMessageEvent, group_id, qq_id, player):
    cls = _cat_core.CLASSES.get(player["class_name"], {})  # v105 P1(M01#10)：脏 class_name 兜底
    # v55.2：属性也统一「总值(+加成)」格式，每项单独一行（与『属性』面板一致）
    st, sources = player_stats_detail(
        player["class_name"], player["level"], player["equipment"],
        player.get("class_tier", 0), player.get("attributes"), player.get("evolve_path", 0),
        self._title_bonus(group_id, qq_id), player.get("race"),
        player.get("learned_skills", []),  # v110.4 X2 P1-2：面板接入已学属性被动
    )
    base = next((s["stats"] for s in sources if s["name"] == "基础"), {})
    # O114 修复：副本战斗中『角色』位置与副本状态同步——显示"副本战斗中"而非旧地点
    # （playtest O114 洛洛实测：移动中被拉入副本，位置仍显示原城镇）
    _inst_row = self._instance_battle_for(group_id, qq_id)
    if _inst_row:
        cur_map = "副本战斗中"
    else:
        cur_map = (_cat_space.MAP_BY_ID.get(player["cur_map"]) or _cat_space.MAP_BY_ID.get(_cat_core.START_MAP, {}))
        cur_map = cur_map.get("name", "橡木镇")
    # 装备展示（v33：固定部位顺序，空位显示 —）
    eq_lines = []
    for slot in ["weapon", "helm", "armor", "legs", "boots", "ring", "necklace"]:
        item = player["equipment"].get(slot)
        if item:
            q = _cat_b143.QUALITY[item["quality"]]
            enh = item.get("enhance", 0)
            enh_str = f" +{enh}" if enh > 0 else ""
            eq_lines.append(f"  {_cat_b143.EQUIP_SLOTS[slot]}：{q['color']}{item['name']}{enh_str}")
        else:
            eq_lines.append(f"  {_cat_b143.EQUIP_SLOTS[slot]}：—")
    eq_str = "\n".join(eq_lines) if eq_lines else "  无"
    need = C.exp_to_next(player["level"])
    exp_pct = min(100, int(player["exp"] / need * 100)) if need else 0
    lines = [
        f"⚔️ 【{player['name']}】",
        f"🛡 Lv.{player['level']} {display('classes', player['class_name'])}",
    ]
    # v95.24 性别 + v100.8 种族性别合并一行：🧬 银月精灵 · ♂男（存量档无性别则只显示种族）
    g = player.get("gender") or ""
    race_s = race_name(player.get('race'))
    gender_s = f"{'♂' if g == 'male' else '♀'} {'男' if g == 'male' else '女'}" if g else ""
    if race_s and gender_s:
        lines.append(f"🧬 {race_s} · {gender_s}")
    elif race_s:
        lines.append(f"🧬 {race_s}")
    elif gender_s:
        lines.append(f"🧬 {gender_s}")
    lines.append("━━━━━━━━━━━━")
    # 阶段九：装备称号显示在角色名前（14 章 3.4）
    eq_title = player.get("equipped_title") or ""
    if eq_title:
        lines[0] = f"⚔️ [{eq_title}] 【{player['name']}】"
    # v100.10 角色面板瘦身：只保留生命/魔力（当前/上限状态）+ 4 项基础属性（纯数值），
    # 战斗属性（攻击/防御/暴击等）详情去『属性』面板看，避免角色面板过于拥挤
    stat_rows = [
        ("❤️", "hp", "max_hp", "生命"),
        ("💙", "mp", "max_mp", "魔力"),
    ]
    for icon, skey, fkey, cname in stat_rows:
        final = st[fkey]
        bonus = final - base.get(skey, 0)
        # v105 P3(M01)：当前值双保险 clamp（get_player 已裁上限；此处防负数/脏档超限）
        cur = min(max(int(player.get(skey, 0) or 0), 0), int(final))
        if skey in PCT_STATS:
            lines.append(f"{icon} {cname}：{cur}/{int(final*100)}%({int(bonus*100):+d}%)")
        else:
            lines.append(f"{icon} {cname}：{cur}/{final}({int(bonus):+d})")
    attr = player.get("attributes") or {}
    if isinstance(attr, str):
        try:
            import json
            attr = json.loads(attr) or {}
        except Exception:
            attr = {}
    for icon, cname, key in (
        ("💪", "力量", "str"),
        ("🏃", "敏捷", "agi"),
        ("🧠", "智力", "int"),
        ("🧱", "耐力", "vit"),
    ):
        lines.append(f"{icon} {cname}：{attr.get(key, 0)}")
    # 资源块（金币/位置/技能点/EXP 独立成块，每项单独一行）
    lines.append("━━━━━━━━━━━━")
    lines.append(f"💰 金币：{player['gold']}")
    # v94 体力：角色面板显示体力（v100.8 冒号格式与全面板统一）
    lines.append(self._stamina_bar(player, sep="："))
    lines.append(f"📍 位置：{cur_map}")
    lines.append(f"💡 技能点：{player.get('skill_points', 0)}")
    lines.append(f"✨ EXP：{player['exp']}/{need} ({exp_pct}%)")
    lines.append("━━━━━━━━━━━━")
    lines.append(f"装备：\n{eq_str}")
    yield event.plain_result("\n".join(lines))

async def leaderboard(self, event: AstrMessageEvent, group_id, qq_id):
    raw = self._strip_cmd(event, "排行").strip()
    medals = ["🥇", "🥈", "🥉", "4.", "5.", "6.", "7.", "8.", "9.", "10."]
    # v83.1：『排行 副业』→ 副业排行（原『副业 排行』参数保留兼容）
    if "副业" in raw:
        yield event.plain_result(self._prof_rank_text(group_id))
        return
    # v104R3 P2：『排行 战力』→ 战力榜（原实现静默落等级榜，与帮助文案「等级/战力/副业」不符）
    if "战力" in raw:
        rows = db.all_players(group_id)
        if not rows:
            yield event.plain_result("还没有人注册角色，快来当第一名！『注册 <名字> <性别>』")
            return

        def _pw(p):
            try:
                eq = json.loads(p.get("equipment") or "{}")
                attrs = json.loads(p.get("attributes") or '{"str":0,"agi":0,"int":0,"vit":0}')
            except (ValueError, TypeError):
                eq, attrs = {}, {"str": 0, "agi": 0, "int": 0, "vit": 0}
            try:
                st = player_final_stats(p["class_name"], p["level"], eq,
                                          p.get("class_tier", 0), attrs,
                                          p.get("evolve_path", 0), None, p.get("race"))
                return int(st["atk"] * 2 + st["matk"] * 2 + st["def"] * 1.5
                           + st["mdef"] * 1.5 + st["max_hp"] / 10
                           + st["max_mp"] / 10 + st["spd"] * 3)
            except Exception:
                return 0

        ranked = sorted(rows, key=_pw, reverse=True)[:10]
        lines = ["🏆 【奥兰迪亚战力榜】 🏆", "━━━━━━━━━━━━"]
        for i, p in enumerate(ranked):
            lines.append(f"{medals[i]} {_pw(p):,} 战力 Lv.{p['level']} "
                         f"{_cat_core.CLASSES[p['class_name']]['icon']}{p['name']} ({display('classes', p['class_name'])})")
        lines.append("")
        lines.append(self._tip("rank"))
        yield event.plain_result("\n".join(lines))
        return
    tops = db.top_players(group_id, 10)
    if not tops:
        yield event.plain_result("还没有人注册角色，快来当第一名！『注册 <名字> <性别>』")
        return
    lines = ["🏆 【奥兰迪亚强者榜】 🏆", "━━━━━━━━━━━━"]
    for i, p in enumerate(tops):
        _ci = _cat_core.CLASSES.get(p['class_name'], {})  # v105 P1(M01#10)：脏 class_name 兜底
        lines.append(f"{medals[i]} Lv.{p['level']} {_ci.get('icon', '❓')}{p['name']} ({display('classes', p['class_name'])})")
    lines.append("")
    lines.append(self._tip("rank"))
    yield event.plain_result("\n".join(lines))

async def races(self, event: AstrMessageEvent):
    """阶段九：种族一览(08 章，注册前查看 6 族天赋)"""
    lines = ["🧬 【种族】6 大种族各有取舍(注册时选择：注册 <名字> <性别> <种族>)", "━━━━━━━━━━━━"]
    for rid, r in _cat_core.RACES.items():
        t = r["talents"]
        tnames = r.get("talent_names", {})
        # v98.3：展示格式化全数据化 → core/race_talent_display.py
        format_talent = _host_attr("core.race_talent_display", "format_talent")
        # v113.6 排版优化：种族描述一行 + 每个天赋独立一行（此前 '，'.join 全挤一行）
        lines.append(f"{r['icon']} {r['name']}：{r['desc']}")
        for k, v in t.items():
            nm = tnames.get(k, k)
            text = format_talent(k, v, nm)
            if text is not None:
                lines.append(f"  · {text}")
        lines.append("")
    lines.append("━━━━━━━━━━━━")
    lines.append("💡 种族天赋 = 有得有失，负面已配正面补偿(净强度≈不变)，选取舍不选碾压！")
    yield event.plain_result("\n".join(lines))

async def evolve(self, event: AstrMessageEvent, group_id, qq_id, player):
    _raw0 = self._strip_cmd(event, "转职").strip()
    # v108 职业树：隐藏职业统一路由（『转职 <档位名>』T1/T2/T3 全名 + 短别名）
    # v112 主题线制：路由带流派索引（档位名 → (cls_id, tier, path)）
    routes = self._hidden_class_routes()
    if _raw0 in routes:
        cls_id, tgt_tier, _path = routes[_raw0]
        async for r in self._evolve_hidden_generic(event, group_id, qq_id, player, cls_id, tgt_tier, _path):
            yield r
        return
    alias = self._hidden_alias_map().get(_raw0)
    if alias:
        alias_cls, alias_path = alias
        # v109.2 P3-8：别名按等级继承档位（90 级『转职 龙血』=T3，不再强制 T1）
        _tlv = self._hidden_tier_levels(alias_cls)
        _cur = player.get("class_tier", 0)
        _tgt = _cur + 1
        while _tgt <= 3 and player["level"] >= _tlv.get(_tgt, 99999):
            _tgt += 1
        _tgt -= 1
        if _tgt <= _cur:
            _tgt = _cur + 1  # 下一阶都不够 → 交给 generic 报等级不足
        async for r in self._evolve_hidden_generic(event, group_id, qq_id, player, alias_cls, _tgt, alias_path):
            yield r
        return
    # v109.2 P2-6：隐藏职业玩家『转职 <未识别名>』拦截——防落基础路径错门槛/导师断链
    if _raw0 and _cat_core.CLASSES.get(player["class_name"], {}).get("hidden"):
        yield event.plain_result(
            f"⚠️ 未识别『{_raw0}』！你已踏上传承之路，『转职』可查看下一阶传承。")
        return
    # 隐藏职业玩家『转职』(无参数)：显示传承之路（下一阶/已满）
    if not _raw0 and _cat_core.CLASSES.get(player["class_name"], {}).get("hidden"):
        async for r in self._evolve_hidden_status(event, group_id, qq_id, player):
            yield r
        return
    cls = _cat_core.CLASSES[player["class_name"]]
    tier = player.get("class_tier", 0)
    # 转职等级门槛：tier 1→30级 / tier 2→60级 / tier 3→90级（21 章三转体系）
    next_tier = tier + 1
    need_lv = _cat_core.EVOLVE_LEVELS.get(next_tier)
    branches = cls.get("evolve_branches", {}).get(next_tier, [])
    # 已满级转职
    if not need_lv:
        yield event.plain_result(
            f"👑 你已完成全部转职！{self._tier_title(player['class_name'], tier, player.get('evolve_path', 0))}\n"
            f"当前职业：{cls['icon']} {self._branch_title(player['class_name'], tier, player.get('evolve_path', 0))}(Lv.{player['level']})"
        )
        return
    # 等级不足
    if player["level"] < need_lv:
        line = f"{cls['icon']}{display('classes', player['class_name'])}"
        evo_lines = []
        for t, branch_list in cls.get("evolve_branches", {}).items():
            lv = _cat_core.EVOLVE_LEVELS[t]
            tagged = []
            for i, b in enumerate(branch_list):
                tag = "攻" if i == 0 else "守"
                # v130.2f.2 苦修改名收尾：分支 key → 展示名（武僧→淬势者、大地武僧→锻势行者）
                tagged.append(f"{_BRANCH_KEY_DISPLAY.get(b, b)}({tag})")
            evo_lines.append(f"Lv.{lv} → {' / '.join(tagged)}")
        yield event.plain_result(
            f"{line} 的进化之路：\n"
            f"━━━━━━━━━━━━\n"
            f"{chr(10).join(evo_lines)}\n\n"
            f"🔒 达到 {need_lv} 级可转职，当前 Lv.{player['level']}，继续加油！\n"
            f"🍃 传闻大陆深处还藏着古老传承，若有缘自会相遇……"
        )
        return
    # 可以转职：v95.23 改为找职业导师 NPC 转职（不再直接指令转职）
    # v112 D4：导师表下沉 CLASSES[职业]["tutor"]
    tname, tloc = _cat_core.CLASSES.get(player["class_name"], {}).get("tutor", ("职业导师", "对应城市"))
    # v130.2f.2 苦修改名收尾：分支 key → 展示名（武僧→淬势者、大地武僧→锻势行者）
    branch_names = " / ".join(_BRANCH_KEY_DISPLAY.get(b, b) for b in branches) if branches else "对应分支"
    yield event.plain_result(
        f"🌟 {cls['icon']}{display('classes', player['class_name'])} 达到了 {need_lv} 级，可以转职！\n"
        f"━━━━━━━━━━━━\n"
        f"🔀 可选路线：{branch_names}\n\n"
        f"🧭 去 {tloc} 找 {tname}，由导师为你举行转职仪式吧！\n"
        f"(『对话 {tname}』→ 对话选择转职路线)\n"
        f"🍃 传闻大陆深处还藏着古老传承，若有缘自会相遇……"
    )
    return

def _branch_title(self, class_name: str, tier: int, evolve_path: int = 0) -> str:
    """分支称号：优先返回所选分支的名字，否则默认第一条"""
    cls = _cat_core.CLASSES.get(class_name, {})
    # F1 P1-1（report_02）：未转职(tier=0)时显示基础职业名，不再取 evolve[-1] 最高阶称号
    if int(tier or 0) <= 0:
        return display("classes", class_name) if isinstance(class_name, str) else class_name
    branches = cls.get("evolve_branches", {})
    if tier > 0 and tier in branches and branches[tier]:
        # v112：多分支索引通用化（基础攻/守 path=1/2；隐藏流派 path=1/2/3）
        idx = max(0, int(evolve_path or 0) - 1)
        lst = branches[tier]
        if 0 <= idx < len(lst):
            # v130.2f.2 苦修改名收尾：分支 key → 展示名（武僧→淬势者、大地武僧→锻势行者）
            return _BRANCH_KEY_DISPLAY.get(lst[idx], lst[idx])
    evolve = cls.get("evolve", [])
    if tier - 1 < len(evolve):
        return evolve[tier - 1].split("(")[0]
    return display("classes", class_name) if isinstance(class_name, str) else class_name

def _hidden_alias_map(self) -> dict:
    """全局短别名表：短别名 → (cls_id, 流派索引)。数据源 CLASSES[线]["aliases"]"""
    out = {}
    for cid, cinfo in _cat_core.CLASSES.items():
        for alias, path in (cinfo.get("aliases") or {}).items():
            out[alias] = (cid, int(path))
    return out

def _hidden_class_routes(self) -> dict:
    """动态构建：隐藏职业档位全名 → (cls_id, tier, 流派索引)（evolve_branches 反查）
    v112：档位名按流派对齐，索引即流派（『转职 符文剑士』→ 龙裔线 T2 龙咒流派）"""
    routes = {}
    for cls_id, cls in _cat_core.CLASSES.items():
        if not cls.get("hidden"):
            continue
        for tier, names in (cls.get("evolve_branches") or {}).items():
            for i, n in enumerate(names):
                routes[n] = (cls_id, int(tier), i + 1)
    return routes

def _hidden_tier_levels(self, cls_id: str) -> dict:
    """隐藏线档位门槛：CLASSES["tier_levels"] 配置优先，缺省 40/60/90"""
    return _cat_core.CLASSES.get(cls_id, {}).get("tier_levels") or {1: 40, 2: 60, 3: 90}

async def _evolve_hidden_status(self, event, group_id, qq_id, player):
    """隐藏职业玩家『转职』(无参数)：显示传承之路（下一阶/已满）"""
    cls_id = player["class_name"]
    cls = _cat_core.CLASSES[cls_id]
    tier = player.get("class_tier", 0)
    tlv = self._hidden_tier_levels(cls_id)
    next_tier = tier + 1
    need_lv = tlv.get(next_tier)
    if not need_lv:
        yield event.plain_result(f"👑 你已完成全部传承！{self._tier_title(cls_id, tier, 1)}")
        return
    names = cls.get("evolve_branches", {}).get(next_tier, [])
    # v112：按玩家当前流派显示下一阶（3 流派线 T2/T3 名称按流派对齐）
    _p = max(0, int(player.get("evolve_path", 1) or 1) - 1)
    nname = names[_p] if _p < len(names) else (names[0] if names else "下一阶")
    # v130.2f.2 苦修改名收尾：下一阶展示名走 key→展示名映射（武僧→淬势者、大地武僧→锻势行者）；
    # 『转职 <展示名>』命令由 aliases（淬势者/锻势行者）路由可达，展示与命令口径一致
    nname = _BRANCH_KEY_DISPLAY.get(nname, nname)
    if player["level"] < need_lv:
        yield event.plain_result(
            f"{cls['icon']} 传承之路：下一阶【{nname}】需要 Lv.{need_lv}，当前 Lv.{player['level']}。")
        return
    yield event.plain_result(
        f"{cls['icon']} 传承之路：下一阶【{nname}】(Lv.{need_lv})已就绪！\n"
        f"『转职 {nname}』接受传承。")

async def _evolve_hidden_generic(self, event, group_id, qq_id, player, cls_id, tgt_tier, req_path=1):
    """v108 职业树：隐藏职业通用传承转职（修为继承）。
    校验：解锁 + 等级 >= 目标档门槛 + 档位状态合法（同职业只能逐阶升）。
    修为继承：目标档位由命令名决定、等级门槛校验——60 级『转职 奥法大师』= 直接 T2。
    技能继承：线级基础 + 本流派分支技能中 lv <= 当前等级的全部（v112 主题线制：
    流派 = evolve_path 1/2/3，传承按所选流派授予，其余流派技能不可习得）。"""
    cls = _cat_core.CLASSES[cls_id]
    cname = cls["name"]
    icon = cls.get("icon", "✨")
    unlocks = player.get("hidden_class_unlock", [])
    if cls_id not in unlocks:
        hint = cls.get("hint") or f"💡 {cls.get('desc', '').split('。')[0]}。\n🔍 前往对应导师处完成试炼即可解锁传承。"
        yield event.plain_result(f"{icon} {cname}的传承还未向你敞开……\n{hint}")
        return
    # v108.2 血缘限制：只有渊源根基职业（含其分支线）可传承，杜绝"全系奇遇"
    # v112.1：src_base 为空的"中立线"跳过血缘检查（当前无中立线，预留通用性）
    src = cls.get("src_base", "")
    if src and player["class_name"] != cls_id and player["class_name"] != src:
        src_name = _cat_core.CLASSES.get(src, {}).get("name", "对应职业")
        # v109.2 P3-7：同源隐藏玩家拒绝文案区分（魔剑→龙血 不再说"先以战士身份历练"误导）
        if _cat_core.CLASSES.get(player["class_name"], {}).get("hidden"):
            cur_name = _cat_core.CLASSES.get(player["class_name"], {}).get("name", "当前职业")
            yield event.plain_result(
                f"{icon} {cname}的传承与你的血脉有所共鸣，但一脉相承不可兼得……\n"
                f"💡 你已踏上【{cur_name}】之路，若想改换门庭可『转职重置』回到{src_name}一脉再传承。")
        else:
            yield event.plain_result(
                f"{icon} {cname}的传承只向{src_name}一脉的传人敞开……\n"
                f"💡 先以{src_name}的身份历练，再寻访这份传承。")
        return
    # v113 种族限制：src_race 指定了血脉种族（如龙裔誓约 = 龙裔）——非该种族拒绝传承
    src_race = cls.get("src_race", "")
    if src_race:
        cur_race = player.get("race") or "human"
        if cur_race != src_race:
            need_cn = (_cat_core.RACES.get(src_race) or {}).get("name", "对应种族")
            cur_cn = (_cat_core.RACES.get(cur_race) or {}).get("name", "未知种族")
            yield event.plain_result(
                f"{icon} {cname}的传承需要{need_cn}的血脉才能唤醒……\n"
                f"💡 你身为{cur_cn}，与这份力量格格不入。")
            return
    tlv = self._hidden_tier_levels(cls_id)
    need_lv = tlv.get(tgt_tier)
    if not need_lv:
        yield event.plain_result(f"{icon} {cname}的传承之路已到尽头。")
        return
    if player["level"] < need_lv:
        yield event.plain_result(
            f"{icon} 这一阶传承需要 Lv.{need_lv} 历练，当前 Lv.{player['level']}，先游历四方吧。")
        return
    cur_tier = player.get("class_tier", 0)
    _same_class = (player.get("class_name") == cls_id)
    if _same_class:
        # v112 流派：同职业升档流派不变（改流派 = 『转职重置』后重新传承，P0-4a 两步走）
        path = max(1, int(player.get("evolve_path", 1) or 1))
        if cur_tier >= tgt_tier:
            yield event.plain_result(
                f"{icon} 你已是{cname}（{self._branch_title(cls_id, cur_tier, path)}）。")
            return
        if cur_tier != tgt_tier - 1:
            yield event.plain_result("时机未到，先巩固当前境界吧。")
            return
    else:
        path = max(1, int(req_path or 1))  # 跨职业进入：按所选档位名定流派
        # v110 审计修复：跨职业（基础→隐藏）转职补降档守卫——同职业块有
        # `cur_tier != tgt_tier-1` 拦截，跨职业路径此前无任何守卫：已达 T2 的战士
        # 用 T1 全名『转职 龙血战士』会被静默降成 T1（分支技能整体清空），而别名
        # 路由（按等级继承档位）会拒绝——全名/别名行为不一致，高阶位阶进度可意外回退
        if cur_tier > tgt_tier:
            yield event.plain_result(
                f"{icon} {cname}的传承位阶（{tgt_tier} 阶）低于你当前的境界（{cur_tier} 阶）——"
                f"传承无法倒退，请以与之相称的位阶再续传承。")
            return
    # 技能继承：线级基础 + 本流派分支（v112）中 lv <= 当前等级的全部。
    # v109：同职业升档保留已学+只补未学——已付费技能不因升档重复发放
    # v110.4 X2 P1-1：grant 为技能 key（基础表 sk_ ID、分支表中文名）、kept 为显示名
    # （get_player 已 C.display）——先把 kept 统一 resolve 再求并/差，避免混型致重复条目
    sk_table = _cat_core.PLAYER_SKILLS.get(cls_id, {}).get("skills", {})
    grant = [s for s, info in sk_table.items() if info["lv"] <= player.get("level", 1)]
    _eb = cls.get("evolve_branches", {})
    _br = _cat_core.BRANCH_SKILLS.get(cls_id, {}).get("branches", {})
    for _t in range(1, tgt_tier + 1):
        _names = _eb.get(_t, [])
        if path - 1 < len(_names):
            _bname = _names[path - 1]
            _bskills = (_br.get(_t, {}) or {}).get(_bname, {})
            grant += [s for s, info in _bskills.items() if info["lv"] <= player.get("level", 1)]
    if _same_class:
        kept = [resolve("skills", s) for s in player.get("learned_skills", []) if s]
        kept = [s for s in kept if s]
        init_skills = sorted(set(kept) | set(grant))
        new_grant = [s for s in grant if s not in kept]
    else:
        init_skills = grant
        new_grant = grant
    st = player_final_stats(
        cls_id, player["level"], player.get("equipment", {}), tgt_tier,
        player.get("attributes"), path,
        self._title_bonus(group_id, qq_id), player.get("race"))
    db.update_player(group_id, qq_id,
                     class_name=cls_id, class_tier=tgt_tier, evolve_path=path,
                     max_hp=st["max_hp"], max_mp=st["max_mp"], hp=st["max_hp"], mp=st["max_mp"],
                     learned_skills=init_skills)
    player = self._player(group_id, qq_id)
    C.check_achievements(group_id, qq_id, player)
    learned = [display('skills', sk) for sk in new_grant]
    title = self._branch_title(cls_id, tgt_tier, path)
    lore = cls.get("lore", "")
    lines = [f"{icon} 传承完成！你成为了【{icon}{title}】！", "━━━━━━━━━━━━"]
    if lore:
        lines.append(lore)
    lines.append(f"🌟 领悟：{'、'.join(learned) if learned else '（本次无新技能）'}")
    if not _same_class and player.get("learned_skills"):
        lines.append("♻️ 旧职业技能已随传承清空，可『技能洗点』返还技能点")
    if _same_class and kept:
        lines.append(f"🔒 已学技能保留 {len(kept)} 个（含此前『技能学习』习得，不重复发放）")
    if _same_class:
        lines.append(f"💡 流派【{self._branch_title(cls_id, 1, path)}】已定，改选流派可『转职重置』回根基职业后重新传承")
    yield event.plain_result("\n".join(lines))

def _evolve_auto_skills(self, player: dict, next_tier: int) -> list:
    """转职自动获得的技能(二转被动 60 级 / 三转奥义 90 级)"""
    if next_tier not in (2, 3):
        return []
    cls = player.get("class_name", "")
    path = player.get("evolve_path", 0)
    branches = _cat_core.BRANCH_SKILLS.get(cls, {}).get("branches", {})
    tier_branches = branches.get(next_tier, {})
    names = list(tier_branches.keys())
    if not names:
        return []
    # v112：多分支索引通用化（攻/守 path=1/2；隐藏流派 path=1/2/3）
    idx = max(0, int(path or 0) - 1)
    if idx >= len(names):
        return []
    target_lv = 60 if next_tier == 2 else 90
    out = []
    for sname, sinfo in tier_branches[names[idx]].items():
        # v151 3-key 表：t2 从 lv58 起、t3 从 lv92 起，多数分支无恰 lv60/90 技能——
        # 取「达到目标等级后的最低等级技能」（二转取 lv≥60 最小、三转取 lv≥90 最小）作为
        # 自动获得技能（原 lv==target_lv 硬匹配在 v151 表下多数分支落空）
        if sinfo.get("lv") >= target_lv:
            out.append((sinfo.get("name", sname), int(sinfo.get("lv", 0) or 0)))
    if not out:
        return []
    out.sort(key=lambda x: x[1])
    return [out[0][0]]

def _tier_title(self, class_name: str, tier: int, evolve_path: int = 0) -> str:
    """职业进阶称号(v25：按分支返回)"""
    return f"{_cat_core.CLASSES.get(class_name, {}).get('icon', '')} {self._branch_title(class_name, tier, evolve_path)}"

async def attributes(self, event: AstrMessageEvent, group_id, qq_id, player):
    # v55.2：每个属性单独一行，格式「总值(+加成)」——加成为基础以外全部来源之和
    # #96 修复（战斗中属性面板非实时）：玩家处于战斗（普通/世界Boss/副本）时，
    # 用战斗实时属性渲染（含战斗内 buff/减益/叠层乘区，与『攻击』实际伤害同口径）；
    # 脱战仍显示静态养成面板。来源明细只用来取"基础"行做加成差值基准。
    _battle_st = None
    if self._in_any_battle(group_id, qq_id):
        try:
            _bstate = db.get_battle(group_id, qq_id)
            if _bstate and _bstate.get("state"):
                # N5b4-6：saintess_engine 实时面板（state sides-only → from_state → actor_stats；
                # 旧格式无 sides → 回落静态养成面板）
                _st_src = _bstate["state"]
                if _st_src.get("sides"):
                    from saintess_engine import Battle as _B2
                    from saintess_engine.battle.stats import actor_stats as _as
                    _b = _B2.from_state(_st_src)
                    _my = None
                    for _a in _b.sides_of("player"):
                        if str(_a.get("qq_id") or "") == str(qq_id):
                            _my = _a
                            break
                    if _my is None:
                        _my = _b.focus()
                    if _my is not None:
                        _battle_st = _as(_b, _my)
        except Exception:
            _battle_st = None
    st, sources = player_stats_detail(
        player["class_name"], player["level"], player["equipment"],
        player.get("class_tier", 0), player.get("attributes"), player.get("evolve_path", 0),
        self._title_bonus(group_id, qq_id), player.get("race"),
        player.get("learned_skills", []),  # v110.4 X2 P1-2：面板接入已学属性被动
    )
    if _battle_st is not None:
        # 战斗内实时属性为权威值；缺键（如基础行里有的特殊键）回退静态，防 KeyError
        for _k in list(st):
            if _k in _battle_st:
                st[_k] = _battle_st[_k]
    base = next((s["stats"] for s in sources if s["name"] == "基础"), {})
    attr = player.get("attributes") or {}  # v105 P1(M01#9)：attributes=None 脏档兜底
    lines = [
        f"📊 【{player['name']} 属性面板】 Lv.{player['level']}{'（⚔️战斗内实时值，含 buff/减益）' if _battle_st is not None else ''}",
        "━━━━━━━━━━━━",
    ]
    stat_rows = [
        ("❤️", "hp", "max_hp", "生命"),
        ("💙", "mp", "max_mp", "魔力"),
        ("⚔️", "atk", "atk", "攻击"),
        ("🛡️", "def", "def", "防御"),
        ("🔮", "matk", "matk", "魔攻"),
        ("✨", "mdef", "mdef", "魔防"),
        ("💨", "spd", "spd", "速度"),
        ("💥", "crit", "crit", "暴击"),
        ("🌀", "dodge", "dodge", "闪避"),
        ("🎯", "precise", "precise", "精准"),
        # v106 穿透/韧性/幸运
        ("🗡️", "pene_phys", "pene_phys", "物穿"),
        ("🔮", "pene_magi", "pene_magi", "法穿"),
        ("🪓", "pene_flat", "pene_flat", "固定物穿"),
        ("🪄", "pene_mflat", "pene_mflat", "固定法穿"),
        ("🧱", "tenacity", "tenacity", "韧性"),
        ("🍀", "luck", "luck", "幸运"),
        # v106.1 冷却/抗性/成长
        ("⏱️", "cdr", "cdr", "冷却缩减"),
        ("🌡️", "elem_res", "elem_res", "元素抗性"),
        ("🌑", "abyss_res", "abyss_res", "深渊抗性"),
        ("📚", "exp_bonus", "exp_bonus", "经验加成"),
        ("💰", "gold_bonus", "gold_bonus", "金币加成"),
        # v106.2 治疗/护盾强度
        ("💚", "heal_power", "heal_power", "治疗强度"),
        ("🛡️", "shield_power", "shield_power", "护盾强度"),
        # v106.3 吸血/暴击伤害/格挡
        ("🩸", "lifesteal", "lifesteal", "吸血"),
        ("💢", "crit_dmg", "crit_dmg", "暴击伤害"),
        ("🧱", "block", "block", "格挡"),
        # v106.4 反伤/物魔免/物法吸
        ("🌵", "thorns", "thorns", "反伤"),
        ("🪨", "phys_reduce", "phys_reduce", "物理免伤"),
        ("🛡️", "magic_reduce", "magic_reduce", "魔法免伤"),
        ("🩸", "lifesteal_phys", "lifesteal_phys", "物理吸血"),
        ("🔮", "lifesteal_magi", "lifesteal_magi", "法术吸血"),
        ("🧙", "summon_power", "summon_power", "召唤强化"),  # v107 召唤物系统
    ]
    for icon, skey, fkey, cname in stat_rows:
        final = st.get(fkey, 0)  # v105：precise 无来源时 st 无键，.get 兜底（防 KeyError）
        # v106.4：特殊属性 0 时不显示（有加成才显示，防面板爆炸）
        if skey in _cat_core.OPTIONAL_STATS and not final:
            continue
        bonus = final - base.get(skey, 0)
        if skey in PCT_STATS:
            lines.append(f"{icon} {cname}：{final*100:.1f}%({bonus*100:+.1f}%)")
        else:
            lines.append(f"{icon} {cname}：{final}({int(bonus):+d})")
    lines.append("━━━━━━━━━━━━")
    lines.append(f"🎯 自由属性点：{player.get('attr_pts', 0)}")
    # 加点分配（每项单独一行，说明换行缩进——v100.9 排版优化；v100.10 冒号统一）
    lines.append(f"💪 力量：{attr.get('str', 0)}\n   ·每点＋1 攻击")
    lines.append(f"🏃 敏捷：{attr.get('agi', 0)}\n   ·每点＋0.8 速度 ＋ 0.4% 暴击")
    lines.append(f"🧠 智力：{attr.get('int', 0)}\n   ·每点＋1 魔攻 ＋ 1.5 魔力")
    lines.append(f"🧱 耐力：{attr.get('vit', 0)}\n   ·每点＋6 生命")
    lines.append("━━━━━━━━━━━━")
    lines.append(self._tip("attr"))
    yield event.plain_result("\n".join(lines))

async def add_attr(self, event: AstrMessageEvent, group_id, qq_id, player):
    args = self._strip_cmd(event, "加点").split()
    if len(args) < 2 or not args[1].isdigit():
        yield event.plain_result("格式：加点 <力量/敏捷/智力/耐力> <点数>，如『加点 力量 5』")
        return
    key_map = {"力量": "str", "敏捷": "agi", "智力": "int", "耐力": "vit"}
    key = key_map.get(args[0])
    if not key:
        yield event.plain_result("可选：力量 / 敏捷 / 智力 / 耐力")
        return
    n = int(args[1])
    if n <= 0:
        yield event.plain_result("点数必须是正整数！")
        return
    pts = player.get("attr_pts", 0)
    if n > pts:
        yield event.plain_result(f"属性点不足！你只有 {pts} 点，需要 {n} 点。")
        return
    attr = dict(player.get("attributes") or {})  # v105 P1(M01#9)：attributes=None 脏档兜底
    attr[key] = attr.get(key, 0) + n
    import json
    db.update_player(group_id, qq_id, attr_pts=pts - n, attributes=json.dumps(attr, ensure_ascii=False))
    names = {"str": "力量", "agi": "敏捷", "int": "智力", "vit": "耐力"}
    yield event.plain_result(f"✅ 加点成功！{names[key]} +{n}，剩余属性点 {pts - n}\n『属性』查看效果～")

async def reset_skill(self, event: AstrMessageEvent, group_id, qq_id, player):
    """技能洗点(v27 独立指令)：花 500 金币返还全部已花费技能点(学习+升级)，清空已学技能与等级"""
    if not player.get("learned_skills"):
        yield event.plain_result("你还没有学习过任何技能，无需洗点～")
        return
    cost = _cat_core.RESET_SKILL_COST
    if player["gold"] < cost:
        yield event.plain_result(f"技能洗点需要 {cost} 金币，你只有 {player['gold']} 金币。")
        return
    spent = player.get("skill_spent", 0)
    cls = player["class_name"]
    init_skills = [display("skills", s) for s, info in _sk_table(cls).items() if info["lv"] <= 1]
    db.update_player(group_id, qq_id, gold=player["gold"] - cost,
                     skill_points=player.get("skill_points", 0) + spent,
                     skill_spent=0,
                     learned_skills=init_skills,
                     skill_levels={})
    # v52 Build：洗点后技能栏重置为初始技能
    bar = list(init_skills[:6])
    while len(bar) < 6:
        bar.append(None)
    db.set_skill_bar(qq_id, bar)
    yield event.plain_result(
        f"🔄 技能洗点成功！返还 {spent} 技能点(花费 {cost} 金币)\n"
        f"已学技能清空(保留初始技能：{'、'.join(init_skills) or '无'})，技能等级已重置，『技能学习』重新规划 build 吧～"
    )

async def evolve_reset(self, event: AstrMessageEvent, group_id, qq_id, player):
    """转职重置(21 章 §8)：付费清空转职分支，保留等级，可重新选择分支"""
    tier = player.get("class_tier", 0)
    if tier <= 0:
        yield event.plain_result("你还没有转职过，无需重置～『转职』查看路线。")
        return
    cost = _cat_core.EVOLVE_FEES.get(tier, 500)
    if player["gold"] < cost:
        yield event.plain_result(f"转职重置需要 {cost} 金币(当前 {tier} 转)，你只有 {player['gold']} 金币。")
        return
    # 清除分支技能（learned_skills 中属于分支的）+ 分支技能等级
    cls = player["class_name"]
    cls_meta = _cat_core.CLASSES.get(cls, {})
    if cls_meta.get("hidden"):
        # v108 职业树：隐藏职业重置 = 回到渊源根基职业（付费反悔通道）
        src = cls_meta.get("src_base", "cls_zhan_shi")
        src_cls = _cat_core.CLASSES.get(src, {})
        src_table = _cat_core.PLAYER_SKILLS.get(src, {})
        if isinstance(src_table, dict) and "skills" in src_table:
            src_table = src_table["skills"]
        init_skills = [s for s, info in src_table.items() if info["lv"] <= 1]
        st = player_final_stats(
            src, player["level"], player.get("equipment", {}), 0,
            player.get("attributes"), 0,
            self._title_bonus(group_id, qq_id), player.get("race"))
        db.update_player(group_id, qq_id,
                         gold=player["gold"] - cost,
                         class_name=src, class_tier=0, evolve_path=0,
                         max_hp=st["max_hp"], max_mp=st["max_mp"],
                         hp=st["max_hp"], mp=st["max_mp"],
                         learned_skills=init_skills,
                         skill_levels={})  # v109.2 P2-7：重置一并清技能等级（防再转回白拿旧升级）
        try:
            bar = db.get_skill_bar(qq_id) or []
            nbar = [b if (b is None or b in init_skills) else None for b in bar]
            db.set_skill_bar(qq_id, nbar)
        except Exception:
            pass
        old_title = self._tier_title(cls, tier, player.get("evolve_path", 0))
        cname = cls_meta.get("name", cls)
        yield event.plain_result(
            f"🔄 转职重置成功！(花费 {cost} 金币)\n"
            f"━━━━━━━━━━━━\n"
            f"{old_title} → 回到根基职业【{src_cls.get('icon', '')} {src_cls.get('name', src)}】\n"
            f"✨ 等级保留，{cls_meta.get('name', cls)} 的传承已散去\n"
            f"💡 已解锁的传承仍在：『转职 {cname}』可再次接受传承！"
        )
        return
    learned = list(player.get("learned_skills", []))
    keep = []
    removed = []
    for s in learned:
        if branch_skill_owner(cls, s):
            removed.append(s)
        else:
            keep.append(s)
    slv = dict(player.get("skill_levels", {}) or {})
    for s in removed:
        slv.pop(s, None)
    # v105 P1(M01#1)：转职重置后重算上限并落库——TIER_GROWTH 随阶位归零，
    # 不重算会让存档 max_hp/max_mp 高于计算上限 → 面板倒挂（❤️ 1941/1331）
    # 且住宿/回家/药水按存档旧上限回血，倒挂永久复发。
    # 参照 world.py:_do_evolve_via_npc 同款写法（重算+满血）。
    st = player_final_stats(
        cls, player["level"], player.get("equipment", {}), 0,
        player.get("attributes"), 0,
        self._title_bonus(group_id, qq_id), player.get("race"))
    db.update_player(group_id, qq_id,
                     gold=player["gold"] - cost,
                     class_tier=0,
                     evolve_path=0,
                     max_hp=st["max_hp"], max_mp=st["max_mp"],
                     hp=st["max_hp"], mp=st["max_mp"],
                     learned_skills=keep,
                     skill_levels=slv)
    # 技能栏清除被移除的分支技能
    try:
        bar = db.get_skill_bar(qq_id) or []
        nbar = [b if (b is None or b in keep) else None for b in bar]
        db.set_skill_bar(qq_id, nbar)
    except Exception:
        pass
    old_title = self._tier_title(cls, tier, player.get("evolve_path", 0))
    yield event.plain_result(
        f"🔄 转职重置成功！(花费 {cost} 金币)\n"
        f"━━━━━━━━━━━━\n"
        f"{old_title} → 回到基础职业\n"
        f"✨ 等级与基础技能保留，分支技能已清除({'、'.join(removed) or '无'})\n"
        f"💡 到 30/60/90 级可重新『转职』选择新分支！"
    )

async def reset_attr(self, event: AstrMessageEvent, group_id, qq_id, player):
    raw = self._strip_cmd(event, "洗点").strip()
    # v27：技能洗点已拆分为独立指令『技能洗点』，避免与属性洗点混淆
    if "技能" in raw:
        yield event.plain_result("技能洗点是独立指令：『技能洗点』(500金币返还技能点)～『洗点』只重置属性点。")
        return
    attr = player.get("attributes") or {}  # v105 P1(M01#9)：attributes=None 脏档兜底
    used = sum(attr.values())
    if used == 0:
        yield event.plain_result("你还没有分配过属性点，无需洗点～")
        return
    cost = _cat_core.RESET_SKILL_COST
    if player["gold"] < cost:
        yield event.plain_result(f"洗点需要 {cost} 金币，你只有 {player['gold']} 金币。")
        return
    import json
    attrs0 = {"str": 0, "agi": 0, "int": 0, "vit": 0}
    # v95r76 #381b：洗点后当前 hp/mp 必须裁剪到新上限——attributes 清零 → max_hp 下降
    # （如 956→796），当前值不裁剪会倒挂（小白实测『角色』面板"❤️ 生命：956/796"）。
    # 用实时计算上限（DB max_hp 换装备后过时，面板也走 player_stats_detail 计算值）
    # v105 P1(M01#2)：新上限一并落库——v95r76 只裁剪 hp/mp 不同步 max_hp，
    # 住宿(world.py 按存档 max_hp 全回)/回家(回至存档 max×50%)/药水(按存档 max 比例)
    # 任一都会把 hp 抬回旧上限 → 倒挂复发；称号加成与面板同口径。
    _st0 = player_final_stats(player["class_name"], player["level"], player.get("equipment", {}),
                               player.get("class_tier", 0), attrs0,
                               player.get("evolve_path", 0), self._title_bonus(group_id, qq_id),
                               player.get("race"))
    new_hp = min(int(player.get("hp", 0)), int(_st0.get("max_hp", player.get("max_hp", 100))))
    new_mp = min(int(player.get("mp", 0)), int(_st0.get("max_mp", player.get("max_mp", 100))))
    # #108 修复（洗点强穿）：洗点清零属性后，身上不再满足属性需求(req)的装备
    # 一律自动卸下回背包——防玩家"先加点穿上→洗点白嫖高属性装备"。
    # 设计口径：穿戴属性需求是持续约束，不是穿上那一刻的一次性门槛；
    # 卸下后玩家可『装备 <名称>』手动穿回（属性达标才穿得上）。
    equipment = dict(player.get("equipment") or {})
    dropped = []
    for _slot, _item in list(equipment.items()):
        _req = (_item or {}).get("req") or {}
        if not _req:
            continue
        if any((attrs0 or {}).get(_rk, 0) < _rv for _rk, _rv in _req.items()):
            dropped.append((_slot, _item))
            import uuid as _uuid2
            db.add_item(group_id, qq_id, f"eq_{_uuid2.uuid4().hex[:8]}", _item)
            equipment[_slot] = None
    # 有自动卸下 → 重算一次无该装备的属性上限（洗点上限计算本就基于穿后属性）
    if dropped:
        _st0 = player_final_stats(player["class_name"], player["level"], equipment,
                                    player.get("class_tier", 0), attrs0,
                                    player.get("evolve_path", 0), self._title_bonus(group_id, qq_id),
                                    player.get("race"))
        new_hp = min(int(player.get("hp", 0)), int(_st0.get("max_hp", player.get("max_hp", 100))))
        new_mp = min(int(player.get("mp", 0)), int(_st0.get("max_mp", player.get("max_mp", 100))))
    db.update_player(group_id, qq_id, gold=player["gold"] - cost,
                     attr_pts=player.get("attr_pts", 0) + used,
                     attributes=json.dumps(attrs0, ensure_ascii=False),
                     equipment=equipment,
                     max_hp=_st0["max_hp"], max_mp=_st0["max_mp"],
                     hp=new_hp, mp=new_mp)
    _drop_txt = ""
    if dropped:
        _dnames = "、".join(f"{_it.get('name', _sl)}" for _sl, _it in dropped)
        _drop_txt = f"\n⚔️ 属性不足，以下装备自动卸下回背包：{_dnames}\n（『加点』后可用『装备 <名称>』重新穿上）"
    yield event.plain_result(f"🔄 洗点成功！返还 {used} 点属性点(花费 {cost} 金币){_drop_txt}\n『加点』重新分配～")

async def power(self, event: AstrMessageEvent, group_id, qq_id, player):
    st = player_final_stats(player["class_name"], player["level"], player["equipment"], player.get("class_tier", 0), player.get("attributes"), player.get("evolve_path", 0), self._title_bonus(group_id, qq_id), player.get("race"))
    pw = int(st["atk"] * 2 + st["matk"] * 2 + st["def"] * 1.5 + st["mdef"] * 1.5
            + st["max_hp"] / 10 + st["max_mp"] / 10 + st["spd"] * 3)
    tier = player.get("class_tier", 0)
    title = self._tier_title(player["class_name"], tier)
    yield event.plain_result(
        f"⚡ 【战力】{player['name']}({title} Lv.{player['level']})\n"
        f"战斗力：{pw:,}\n"
        f"━━━━━━━━━━━━\n"
        f"❤️ {st['max_hp']} ｜ ⚔️ {st['atk']} ｜ 🔮 {st['matk']} ｜ 🛡️ {st['def']} ｜ 💨 {st['spd']}\n"
        f"💡 升级、装备、转职、加点都能提升战力！"
    )

async def skill_detail(self, event: AstrMessageEvent, group_id, qq_id, player):
    skill_name = self._strip_cmd(event, "技能详情").strip()
    if not skill_name:
        yield event.plain_result("格式：技能详情 <技能名/序号>，如『技能详情 火球术』或『技能详情 5』")
        return
    # 序号查看：『技能详情 5』→ 技能列表第 5 个技能
    if skill_name.isdigit():
        skills = self._player_skill_table(player)
        skill_items = list(skills.keys())
        idx = int(skill_name)
        if idx < 1 or idx > len(skill_items):
            yield event.plain_result(f"你的职业只有 {len(skill_items)} 个技能！『技能列表』查看全部～")
            return
        skill_name = skill_items[idx - 1]
    msg = self._skill_detail_message(player, skill_name)
    if msg is None:
        yield event.plain_result(f"你的职业没有『{skill_name}』技能！『技能列表』查看全部～")
        return
    yield event.plain_result(msg)

def _skill_detail_message(self, player: dict, skill_name: str) -> str | None:
    """v134.6 通用技能详情渲染（供 skill_detail / item_detail『查看』共用）：
    返回详情文本；技能不存在返回 None。player 须含 class_name/level/learned_skills/skill_levels。"""
    skill_name = skill_name.strip()
    # 序号查看：『技能详情 5』→ 技能列表第 5 个技能
    if skill_name.isdigit():
        skills = self._player_skill_table(player)
        skill_items = list(skills.keys())
        idx = int(skill_name)
        if idx < 1 or idx > len(skill_items):
            return f"你的职业只有 {len(skill_items)} 个技能！『技能列表』查看全部～"
        skill_name = skill_items[idx - 1]
    info = skill_info(player["class_name"], skill_name)
    if not info:
        return None
    # v56.1：显示一律用中文名（info 里带 name，序号查询进来的是 sk_xxx ID）
    display_name = info.get("name", skill_name)
    learned = player.get("learned_skills", [])
    is_learned = is_skill_learned(player["class_name"], player["level"], skill_name, learned)
    mx = skill_max_level(info)
    if is_learned:
        slv = skill_level_of(player, skill_name)  # #259：兼容 skill_levels key 为中文名
        status = f"✅ 已学会 Lv.{slv}/{mx}"
    elif info["lv"] <= player["level"]:
        status = f"📖 可学习(Lv.{info['lv']})"
    else:
        status = f"🔒 未学会(Lv.{info['lv']} 解锁)"
    # v104 R3 P2-3：消耗行同源展示（mp + res_cost + 精力），与 combat.py 技能列表口径一致
    # v112：资源中文名数据驱动（v181.M-R2c 源 = EFFECT_RULES，新增资源只改数据）
    # v161 意见#70：消耗显示与技能列表统一——资源项带 `-` 前缀（消耗=扣减，与 res_gain 的 `+` 区分）
    _costs = []
    if info.get("mp"):
        _costs.append(f"{info['mp']} 魔力")
    for _rk, _rv in (info.get("res_cost") or {}).items():
        # v81 消耗格式统一：『x 精力』（原名在资源名后带 -x，玩家读起来像属性扣减歧义；
        # 与技能列表『消耗：精力 -22』口径仍一致，但详情行用直白语序）
        _cn = _RES_CN.get(_rk, _rk)
        _costs.append(f"{_rv} {_cn}")
    _cost_txt = " + ".join(_costs) if _costs else "无"  # v104 R3 P3-1：零消耗显示"无"（与技能列表口径一致）
    lines = [
        f"📜 【{display_name}】｜{status}",
        f"━━━━━━━━━━━━",
        # v161 意见#71：移除冗余"需求等级"（状态行已显示 Lv.X 解锁/可学习）
        f"类型：{info.get('kind','')} ｜ 消耗：{_cost_txt}",
        # v173.3 意见#94：技能详情补出招时间（cast 基准秒 @速度50，v154 速度折算）
        f"⚡ 出招：{self._skill_cast_text(info)}",
        # v162 回滚：desc 已通过 buff_turns 字段真实对齐（铁壁 buff_turns=8 真持续 8 刻），
        # 不再展示层替换（原 _desc_align_turns 会把 8 错改成 3）
        f"效果：{info['desc']}",
    ]
    # v160 表达式技能：公式翻译展示（exprs 逐级显示当前级公式；单条 expr 显示公式本身）
    _expr_show = self._skill_formula_text(info, slv if is_learned else 1)
    if _expr_show:
        lines.append(f"📐 公式：{_expr_show}")
    # 玩家当前属性（表达式代入用；面板口径与战斗一致——称号加成省略，
    # 展示目的是比较各级数值曲线，非精确面板；learned_skills 传入让属性被动生效）
    # 仅表达式技能需要（旧百分比技能无玩家属性代入，省一次属性计算）
    _stats = None
    if (info.get("exprs") or info.get("expr")
            or info.get("heal_formula") or info.get("heal_expr") or info.get("heal_exprs")):
        _stats = player_final_stats(
            player["class_name"], player["level"], player.get("equipment", {}),
            player.get("class_tier", 0), player.get("attributes"),
            player.get("evolve_path", 0), None,
            player.get("race"), player.get("learned_skills"))
        _stats["_player_lv"] = int(player.get("level", 1) or 1)
    if info.get("kind") != "被动" and mx > 1:
        # v134.5 意见#57：LOL 式逐级数值——每级一行，展示 Lv.1→满级全部数值
        # （原只显示当前级单行）。维度与 _skill_upgrade_gains 同源。
        # v160：未学技能也显示（意见#64『技能详情没学也应该显示各个等级的数值』）
        lines.append("📈 数值成长：")
        for _lv in range(1, mx + 1):
            _gains = self._skill_upgrade_gains(info, _lv, _stats)
            _mark = "▶" if (is_learned and _lv == slv) else " "
            if _gains:
                lines.append(f"  {_mark} Lv.{_lv}: {' · '.join(_gains)}")
            else:
                lines.append(f"  {_mark} Lv.{_lv}: (无成长数值)")
    owner = branch_skill_owner(player["class_name"], skill_name)
    if owner:
        # v130.2f.2 苦修改名收尾：专属归属分支 key → 展示名（武僧→淬势者、大地武僧→锻势行者）
        # v174 精确化：牧师/诗人档位名按 tier 从 classes.evolve_branches 取（大主教/圣光先知/
        # 晨曦歌者/天籁颂者等），避免 60 级"大主教"却看到技能标"神谕者专属"
        _own_tier, _own_key = owner[0], owner[1]
        _disp_branch = _own_key
        try:
            _eb_paths = _cat_core.CLASSES.get(player["class_name"], {}).get("evolve_branches", {})
            _eb_list = _eb_paths.get(_own_tier, [])
            # owner key 是该 tier 分支表 key（如"神谕者"），定位其在分支组的位置 → 取同 index 档位名
            _cand_path = branch_path_index(player["class_name"], _own_tier, _own_key)
            if _cand_path is not None and 0 <= _cand_path < len(_eb_list):
                _disp_branch = _BRANCH_KEY_DISPLAY.get(_eb_list[_cand_path], _eb_list[_cand_path])
        except Exception:
            pass
        lines.append(f"专属：{_disp_branch}(Lv.{_cat_core.EVOLVE_LEVELS[_own_tier]} 转职解锁)")
    _multi_disp = int(info.get("multi") or info.get("hits") or 0)
    if _multi_disp > 1:
        lines.append(f"连击：x{_multi_disp}")
    if info.get("pierce"):
        lines.append("特性：无视防御")
    if info.get("effect"):
        # v63/#99 汉化：effect key → 中文 tag（与技能列表 _skill_tag 同源映射；
        # 此前 spd_buff/atk_all 等英文 key 原样泄漏到『技能详情·特效』行）
        CombatCmds = _host_attr("commands.combat", "CombatCmds")
        eff_cn = CombatCmds._EFFECT_CN.get(info["effect"], info["effect"])
        lines.append(f"特效：{eff_cn}")
    if info.get("team"):
        team_cn = {"heal_all": "治疗全队", "def_all": "防御全队", "reduce_all": "减伤全队",
                   "shield_all": "护盾全队", "matk_all": "魔攻全队", "crit_all": "暴击全队",
                   "spd_all": "速度全队", "poison_all": "毒伤全队", "taunt": "嘲讽"}
        lines.append(f"团队：{team_cn.get(info['team'], info['team'])}(副本中广播全队)")
    if info.get("cond"):
        cond = info["cond"]
        ctype = cond.get("type")
        mult = cond.get("mult", 1.0)
        label = cond.get("label", "")
        # v101.2 条件显示文案数据化 → battle_cond_labels.py COND_LABELS
        #（v181 拆分：判定在 services/battle_cond_procs.py，文案在本表）
        COND_LABELS = _host_attr("core.battle_cond_labels", "COND_LABELS")
        label_fn = COND_LABELS.get(ctype)
        ctext = label_fn(cond) if label_fn else ctype
        lines.append(f"⚔️ 条件转化：{ctext}时激活『{label}』(威力 ×{mult})")
    if not is_learned and info["lv"] <= player["level"]:
        cost = skill_learn_cost_for(player, info["lv"])
        lines.append(f"💡 『技能学习 {display_name}』消耗 {cost} 技能点学会(当前 {player.get('skill_points',0)} 点)")
    elif is_learned:
        slv = skill_level_of(player, skill_name)  # #259：兼容 skill_levels key 为中文名
        # v101.28l #439：被动技能详情不再提示升级（与『技能升级』的"无需升级"一致）+ 括号闭合
        if info.get("kind") == "被动":
            lines.append("⚙️ 被动技能，无需升级——学会后战斗自动生效")
        elif slv < mx:
            cost = skill_upgrade_cost(slv, info)
            nxt = " · ".join(self._skill_upgrade_gains(info, slv + 1))
            lines.append(f"💡 『技能升级 {display_name}』花 {cost} 点升到 Lv.{slv + 1}（{nxt}，当前 {player.get('skill_points',0)} 点）")
        else:
            lines.append("✨ 已满级！")
    return "\n".join(lines)

async def skill_learn(self, event: AstrMessageEvent, group_id, qq_id, player):
    """技能学习(v12)：等级门槛 + 消耗技能点学会，学会永久可用"""
    skill_name = self._strip_cmd(event, "技能学习")
    yield event.plain_result(self._skill_learn_msg(group_id, player, skill_name))

def _skill_learn_msg(self, group_id, player: dict, skill_name: str) -> str:
    """技能学习核心逻辑(v12：等级门槛 + 技能点学会，学会永久可用)"""
    skill_name = (skill_name or "").strip()
    # v95.23 见习冒险者：无职业技能，先就职
    if player.get("class_name") == CLASS_NOVICE:
        return "🧭 见习冒险者还没有职业技能！去广场找『行会接待员·小艾』就职后就能学习技能了～"
    if not skill_name:
        return "格式：技能学习 <技能名/序号>，如『技能学习 裂空斩』或『技能学习 3』"
    # 序号学习：『技能学习 3』→ 技能列表第 3 个技能（与『技能详情』一致）
    if skill_name.isdigit():
        skills = self._player_skill_table(player)
        skill_items = list(skills.keys())
        idx = int(skill_name)
        if idx < 1 or idx > len(skill_items):
            return f"你的职业只有 {len(skill_items)} 个技能！『技能列表』查看全部～"
        skill_name = skill_items[idx - 1]
    info = skill_info(player["class_name"], skill_name)
    if not info:
        return f"你的职业没有『{skill_name}』技能！『技能列表』查看全部～"
    # v56.1：显示一律用中文名（序号学习进来的是 sk_xxx ID）
    display_name = info.get("name", skill_name)
    learned = player.get("learned_skills", [])
    if is_skill_learned(player["class_name"], player["level"], skill_name, learned):
        return f"『{display_name}』你已学会了，去战斗里试试吧～"
    # v101.20 职业导师专属技能拦截：TUTOR_SKILLS 只能找导师学，技能点学不到
    _sid = resolve("skills", skill_name)
    if _sid in ((_cat_core.TUTOR_SKILLS or {}).get(player["class_name"], {}) or {}):
        _mname, _mcity = _tutor_mentor(player["class_name"])
        return f"『{display_name}』是 {_mname}({_mcity}) 的看家本领，普通学习学不到——去{_mcity}找{_mname}请教吧～"
    # v26 分支专属技能门槛：必须先转职到对应分支
    owner = branch_skill_owner(player["class_name"], skill_name)
    if owner:
        need_tier, bname = owner
        # v130.2f.2 苦修改名收尾：分支 key → 展示名（武僧→淬势者、大地武僧→锻势行者）
        bname = _BRANCH_KEY_DISPLAY.get(bname, bname)
        my_tier = player.get("class_tier", 0)
        my_path = player.get("evolve_path", 0)
        if my_tier < need_tier or not my_path:
            return f"『{display_name}』是 {bname} 的专属技能，需要先转职为 {bname} 才能学习！(Lv.30/60/90 可转职)"
        branches = _cat_core.CLASSES[player["class_name"]].get("evolve_branches", {}).get(need_tier, [])
        # v112：多分支索引通用化（攻/守 path=1/2；隐藏流派 path=1/2/3）
        idx = max(0, int(my_path or 0) - 1)
        # v130.2f.2 苦修改名收尾：当前流派分支 key → 展示名（与 bname 同口径比较）
        my_branch = _BRANCH_KEY_DISPLAY.get(branches[idx], branches[idx]) if idx < len(branches) else ""
        if my_branch != bname:
            return f"『{display_name}』是 {bname} 的专属技能，你走的是 {my_branch} 路线，学不了～"
    need_lv = info["lv"]
    if player["level"] < need_lv:
        return f"『{display_name}』需要 Lv.{need_lv} 才能学习，你才 Lv.{player['level']}——升级吧！(每级＋1 技能点)"
    cost = skill_learn_cost_for(player, need_lv)
    pts = player.get("skill_points", 0)
    if pts < cost:
        return (
            f"学习『{display_name}』需要 {cost} 技能点(技能 Lv.{need_lv})，你只有 {pts} 点——升级可获得技能点(每级＋1)～"
        )
    learned = list(learned) + [skill_name]
    spent = player.get("skill_spent", 0) + cost
    db.update_player(group_id, player["qq_id"], skill_points=pts - cost, learned_skills=learned, skill_spent=spent)
    # 阶段九：学习技能成就判定
    C.check_achievements(group_id, player["qq_id"], player)
    if info.get("kind") == "被动":
        return (
            f"✨ 消耗 {cost} 技能点，学会了被动技能『{display_name}』！\n"
            f"⚙️ 被动技能无需施放，战斗自动生效！剩余技能点 {pts - cost}\n"
            f"「{info['desc']}」"
        )
    return (
        f"✨ 消耗 {cost} 技能点，学会了『{display_name}』！\n"
        f"现在 Lv.{player['level']} 就能使用它了，剩余技能点 {pts - cost}\n"
        f"💡 记得『设置技能 <槽位> {display_name}』放入技能栏，战斗中『技能 <槽位>』即可施放～"
    )

def _skill_cast_text(self, info: dict) -> str:
    """v173.3 意见#94：技能出招耗时文案。

    cast = 基准出招秒（速度 50 时实际耗时 = cast；速度越快越短，折算见 battle
    _ct_cost √(50/spd)）。被动技能无出招概念；无 cast 字段的技能回落普攻基准 1.0s。
    """
    if info.get("kind") == "被动":
        return "被动即时生效"
    _c = float(info.get("cast") or 0)
    if _c <= 0:
        # 增益/治疗/嘲讽等即时类（v154 立即生效不读条）
        return "即时生效"
    return f"约 {_c:g} 秒(速度 50 基准，速度越快越快)"

def _skill_formula_text(self, info: dict, lv: int = 1) -> str:
    """v160 表达式技能公式展示：exprs/expr/heal_formula 翻译成中文公式。

    返回 '' 表示该技能无表达式（调用方不显示公式行）。
    - 单条 expr：翻译整个公式
    - exprs 逐级：显示『Lv.N：公式』（当前级；超过条数显示最后一条）
    - heal_formula 字符串数组：同 exprs 逐级
    - heal_formula 段列表：逐段翻译并用 + 连接
    """
    from saintess_engine.expr import translate_expr
    _expr = skill_formula_expr(info, lv)
    if _expr and isinstance(_expr, str):
        return translate_expr(_expr)
    # 治疗逐级
    _hf = info.get("heal_formula") or info.get("heal_expr")
    _he = info.get("heal_exprs")
    if isinstance(_he, list) and _he:
        _lvx = max(1, min(int(lv or 1), len(_he)))
        return translate_expr(_he[_lvx - 1])
    if isinstance(_hf, str):
        return translate_expr(_hf)
    if isinstance(_hf, list):
        if _hf and all(isinstance(_x, str) for _x in _hf):
            _lvx = max(1, min(int(lv or 1), len(_hf)))
            return translate_expr(_hf[_lvx - 1])
        # 段列表：逐段翻译
        _parts = []
        for _seg in _hf:
            if isinstance(_seg, dict):
                _se = skill_formula_expr_for_seg(_seg, lv)
                if _se:
                    _t = translate_expr(_se)
                    _m = float(_seg.get("mult", 1.0) or 1.0)
                    if _m != 1.0:
                        _t = f"{_t}×{_m:g}"
                    _parts.append(_t)
        return " + ".join(_parts)
    return ""

def _skill_upgrade_gains(self, info: dict, lv: int, stats: dict | None = None) -> list:
    """技能升级多维成长描述(v56.1)：按技能单独策划的成长配置列出各维度提升"""
    parts = []
    kind = info.get("kind", "")
    # v160 表达式技能：按玩家属性代入显示实际数值（替代百分比）
    _has_expr = (info.get("exprs") or info.get("expr")
                 or info.get("heal_formula") or info.get("heal_expr") or info.get("heal_exprs"))
    if _has_expr:
        _val = skill_expr_preview(info, lv, stats)
        if _val > 0:
            # v162 修复：攻击类显示伤害/治疗类显示治疗，增益/嘲讽等不显示数值
            if kind == "治疗":
                parts.append(f"治疗 ≈ {int(round(_val))}")
            elif kind in ("物理", "魔法", "真伤") or kind.startswith(("物理", "魔法")):
                parts.append(f"伤害 ≈ {int(round(_val))}")
    # v161：表达式技能已显示实际数值，跳过 power 百分比（避免 305 vs 101% 双数值矛盾）
    if info.get("power") and not _has_expr:
        # v162 修复：只有攻击类（物理/魔法/真伤）显示"伤害"，增益/嘲讽/被动不该显示伤害
        # （铁壁等增益技能带 power 字段，此前误显示"伤害 100%"）
        if kind in ("物理", "魔法", "真伤") or kind.startswith(("物理", "魔法")):
            label = "治疗" if kind == "治疗" else "伤害"
            # v101.25b #339：显示总伤害倍率 power×mult（此前只显示 mult 倍率——
            # 圣光术 desc 115% vs 升级预览 110% 玩家以为升级降伤害）
            parts.append(f"{label} {int(info['power'] * skill_power_mult(lv, info) * 100)}%")
    if kind in ("增益", "嘲讽"):
        parts.append(f"持续 {skill_buff_turns(lv)} 刻")
    if info.get("cond"):
        parts.append(f"条件 ×{skill_cond_mult(info['cond'], lv, info):g}")
    if info.get("mech_val"):
        # v162：effect=reduce 的 mech_val 是减伤百分比（铁壁 45 = 减伤45%），显示"减伤 X%"而非"叠层 X"
        if info.get("effect") == "reduce":
            mv = float(info.get("mech_val") or 0)
            mv = (mv / 100.0) if mv > 1 else mv
            parts.append(f"减伤 {int(round(mv * 100))}%")
        else:
            parts.append(f"叠层 {skill_mech_val(info, lv)}")
    # v104 R3 P2-10：吸血成长预览同 battle 口径——按 lifesteal 数据字段判定
    # （原只认 effect=="lifesteal"，全表无技能带此 effect → 嗜血斩升级预览漏显示吸血）
    if info.get("lifesteal"):
        parts.append(f"吸血 {int(skill_lifesteal_pct(info, lv) * 100)}%")
    return parts

async def skill_upgrade(self, event: AstrMessageEvent, group_id, qq_id, player):
    """技能升级(v27)：已学技能花技能点升级，攻击/治疗 power 提升、增益刻延长"""
    skill_name = self._strip_cmd(event, "技能升级").strip()
    if not skill_name:
        yield event.plain_result("格式：技能升级 <技能名/序号>，如『技能升级 火球术』或『技能升级 3』")
        return
    # 序号升级：『技能升级 3』→ 技能列表第 3 个技能（与『技能详情/学习』一致）
    if skill_name.isdigit():
        skills = self._player_skill_table(player)
        skill_items = list(skills.keys())
        idx = int(skill_name)
        if idx < 1 or idx > len(skill_items):
            yield event.plain_result(f"你的职业只有 {len(skill_items)} 个技能！『技能列表』查看全部～")
            return
        skill_name = skill_items[idx - 1]
    info = skill_info(player["class_name"], skill_name)
    if not info:
        yield event.plain_result(f"你的职业没有『{skill_name}』技能！『技能列表』查看全部～")
        return
    learned = player.get("learned_skills", [])
    if not is_skill_learned(player["class_name"], player["level"], skill_name, learned):
        yield event.plain_result(f"『{skill_name}』还没学会！先『技能学习 {skill_name}』学会后才能升级～")
        return
    # v64 被动技能：不可升级（learned 后即满效果）
    if info.get("kind") == "被动":
        yield event.plain_result(
            f"⚙️ 『{info.get('name', skill_name)}』是被动技能，无需升级——学会后战斗自动生效！"
        )
        return
    levels = dict(player.get("skill_levels") or {})
    cur_lv = skill_level_of(player, skill_name)  # #259：兼容 key 为中文名，升级判定/写入统一
    mx = skill_max_level(info)
    if cur_lv >= mx:
        yield event.plain_result(f"『{skill_name}』已经是满级 Lv.{mx} 啦，不能再升了～")
        return
    cost = skill_upgrade_cost(cur_lv, info)
    pts = player.get("skill_points", 0)
    if pts < cost:
        yield event.plain_result(
            f"升级『{skill_name}』到 Lv.{cur_lv + 1} 需要 {cost} 技能点，你只有 {pts} 点——升级可获得技能点(每级＋1)～"
        )
        return
    levels[resolve("skills", skill_name)] = cur_lv + 1  # #259：key 统一 ID（写库 resolve 幂等，防中文/ID 双 key）
    spent = player.get("skill_spent", 0) + cost
    refund = 0
    # v134.1 人类 博学者：首次升级某技能返还 1 技能点（每技能一次，原 cur_lv=1 时）
    #   （鱼鱼拍板：学习-1/升级-1 太离谱 → 削成首次升级返还 1 点，鼓励尝试新技能）
    if cur_lv == 1:
        fur = race_stats(player.get("race")).get("first_upgrade_refund")
        if fur:
            refund = int(fur)
    db.update_player(group_id, player["qq_id"], skill_points=pts - cost + refund,
                     skill_levels=levels, skill_spent=spent)
    display_name = info.get("name", skill_name)
    gains = self._skill_upgrade_gains(info, cur_lv + 1)
    desc = " · ".join(gains)
    next_cost = skill_upgrade_cost(cur_lv + 1, info)
    tail = f"｜ 升到 Lv.{cur_lv + 2} 需 {next_cost} 点" if next_cost else "｜ 已满级！"
    refund_txt = f"（人类博学者：首次升级返还 1 点）" if refund else ""
    yield event.plain_result(
        f"⬆️ 『{display_name}』升级到 Lv.{cur_lv + 1}({desc})！消耗 {cost} 技能点，剩余 {pts - cost + refund} 点{refund_txt}{tail}"
    )

async def skill_bar_view(self, event: AstrMessageEvent, group_id, qq_id, player):
    bar = db.get_skill_bar(qq_id)
    lines = ["🎛️ 【技能栏】(战斗中『技能 <槽位>』快捷施放)", "━━━━━━━━━━━━"]
    for i in range(6):
        sname = bar[i] if i < len(bar) else None
        if sname:
            info = skill_info(player["class_name"], sname)
            kind = info.get("kind", "") if info else ""
            lines.append(f" {i+1}. {display('skills', sname)}({kind})")
        else:
            lines.append(f" {i+1}. (空)")
    lines.append("━━━━━━━━━━━━")
    lines.append(self._tip("skill"))
    yield event.plain_result("\n".join(lines))

async def skill_bar_set(self, event: AstrMessageEvent, group_id, qq_id, player):
    raw = self._strip_cmd(event, "设置技能").strip()
    parts = raw.split(maxsplit=1)
    if len(parts) < 2 or not parts[0].isdigit():
        yield event.plain_result("格式：设置技能 <槽位1－6> <技能名>，如『设置技能 1 火球术』")
        return
    slot = int(parts[0])
    if slot < 1 or slot > 6:
        yield event.plain_result("技能栏只有 6 个槽位(1~6)！")
        return
    sname = parts[1].strip()
    info = skill_info(player["class_name"], sname)
    if not info:
        yield event.plain_result(f"你的职业没有『{sname}』技能！『技能列表』查看～")
        return
    if not is_skill_learned(player["class_name"], player["level"], sname, player.get("learned_skills", [])):
        yield event.plain_result(f"『{sname}』还没学会！『技能学习 {sname}』消耗技能点学会后再设置～")
        return
    bar = db.get_skill_bar(qq_id)
    while len(bar) < 6:
        bar.append(None)
    bar[slot - 1] = sname
    db.set_skill_bar(qq_id, bar)
    yield event.plain_result(f"✅ 技能栏 {slot} 号位 → 『{sname}』！战斗中『技能 {slot}』即可施放～")

async def build_view(self, event: AstrMessageEvent, group_id, qq_id, player):
    """流派(v52 Build 系统)：查看本职业流派 / 一键配置技能栏"""
    raw = self._strip_cmd(event, "流派").strip()
    cid = player["class_name"]
    builds = _cat_quests.BUILDS.get(cid, {})
    if not builds:
        yield event.plain_result("你的职业暂时没有流派方案～")
        return
    # 无参 → 流派列表
    if not raw:
        lines = [f"⚔️ 【{display('classes', cid)}流派】—— 同一职业，不同打法！", "━━━━━━━━━━━━"]
        for name, info in builds.items():
            learned_cnt = sum(1 for s in info["skills"] if is_skill_learned(cid, player["level"], s, player.get("learned_skills", [])))
            lines.append(f"{info.get('icon','')} {name}(已学 {learned_cnt}/{len(info['skills'])})")
            lines.append(f"    {info['desc']}")
        lines.append("━━━━━━━━━━━━")
        lines.append(self._tip("build"))
        yield event.plain_result("\n".join(lines))
        return
    # 配置指定流派
    name = raw
    if name not in builds:
        yield event.plain_result(f"没有『{name}』流派！你的流派：{'、'.join(builds.keys())}")
        return
    info = builds[name]
    bar = []
    missing = []
    for sname in info["skills"]:
        if is_skill_learned(cid, player["level"], sname, player.get("learned_skills", [])):
            bar.append(sname)
        else:
            need = skill_info(cid, sname)
            need_lv = need["lv"] if need else 0
            missing.append(f"『{sname}』(Lv.{need_lv})")
    while len(bar) < 6:
        bar.append(None)
    db.set_skill_bar(qq_id, bar)
    lines = [f"✅ 已切换为【{info.get('icon','')} {name}】流派！技能栏已配置："]
    for i, sname in enumerate(info["skills"], 1):
        if sname in bar:
            lines.append(f"  {i}. ⚔️ {sname}")
        else:
            lines.append(f"  {i}. 🔒 {sname}(未学会)")
    if missing:
        lines.append(f"⚠️ 还没学会：{'、'.join(missing)}——『技能学习 <名称>』学会后重新『流派 {name}』即可补上")
    lines.append(f"💡 打法：{info['desc']}")
    yield event.plain_result("\n".join(lines))

async def delete_account(self, event: AstrMessageEvent, group_id, qq_id, player):
    """注销角色：删除全部数据，可重新注册（v62 群友想切职业）。

    两步确认防误删：『注销』→ 提示确认；10 分钟内『注销 确认』才真正删除。
    确认状态存 event_state（key: del_confirm_<qq_id>），过期自动失效。
    """
    arg = self._strip_cmd(event, "注销").strip()
    # 『注销 确认』：执行删除（10 分钟内有效）
    if arg == "确认":
        key = f"del_confirm_{qq_id}"
        state = db.get_event_state(key)
        if not state:
            yield event.plain_result("没有待确认的注销请求。输入『注销』发起注销～")
            return
        try:
            if int(time.time()) - int(state) > 600:
                db.delete_event_state(key)
                yield event.plain_result("注销确认已过期，请重新输入『注销』发起～")
                return
        except (TypeError, ValueError):
            pass
        db.delete_player(qq_id)
        db.delete_event_state(key)
        yield event.plain_result(
            f"🗡️ 冒险者 {player['name']} 的故事就此落幕……\n"
            f"所有角色数据已删除，可以重新『注册 <名字> <性别>』开始新旅程！"
        )
        return
    # 发起注销：写确认状态（10 分钟有效）
    db.set_event_state(f"del_confirm_{qq_id}", int(time.time()))
    yield event.plain_result(
        f"⚠️ 真的要注销角色【{player['name']}】吗？\n"
        f"删除后将失去：等级/装备/背包/金币/技能/副业/宠物/公会 全部数据！\n"
        f"━━━━━━━━━━━━\n"
        f"确认请回复：『注销 确认』(10 分钟内有效)\n"
        f"想切职业也可以直接注销后重新注册～"
    )

__all__ = ["_tutor_mentor", "_RES_CN", "_BRANCH_KEY_DISPLAY", "shortcut", "shortcut_trigger", "page_flip", "register", "bind_identity", "profile", "leaderboard", "races", "evolve", "_branch_title", "_hidden_alias_map", "_hidden_class_routes", "_hidden_tier_levels", "_evolve_hidden_status", "_evolve_hidden_generic", "_evolve_auto_skills", "_tier_title", "attributes", "add_attr", "reset_skill", "evolve_reset", "reset_attr", "power", "skill_detail", "_skill_detail_message", "skill_learn", "_skill_learn_msg", "_skill_cast_text", "_skill_formula_text", "_skill_upgrade_gains", "skill_upgrade", "skill_bar_view", "skill_bar_set", "build_view", "delete_account"]
