# -*- coding: utf-8 -*-
"""包内经济域命令（`content/cmds_economy.py`）—— 宿主 `game/commands/economy.py` 45 条命令的
**守卫声明 / 取参 / 业务调度 / 回话组装**（B18-L9，2026-09-15）。

本域的形状（真源 = `overnight/B18_TERMINAL_SHAPE.md` §1.2/§1.3）
--------------------------------------------------------------
宿主旧壳（B9 线 L1 薄壳，2026-09-13）每条命令体是**同一句**：

    @declared('<key>')
    @require_player()
    async def <key>(self, event):
        async for _item in _E.EconomyImpl.<m>(self, event):
            yield _item

实现正文（模块常量 / 物品详情渲染器 / `EconomyImpl` 的方法）早在 B9-L1 就整块搬进包内
`content/economy_cmds.py` 了；**本次只搬「壳」**——把守卫声明、取参口径、调包与回话
从宿主搬进本模块。因此 45 条命令的包内处理器形状**完全同构**：

    @_declare("<key>", guards=("hook:player",), params=("cmd=<命令词>",))
    async def <key>(env):
        return await _messages(_E.EconomyImpl.<m>(_shell(env), _event(env)))

**45 条全部走异步形状**（`_declare` + 宿主两行 `_BRIDGE.run_async`），没有一条走同步
`@register`——理由与 B18-L3c 战斗族同款（`content/cmds_combat.py` 头注）：

* `EconomyImpl` 的 45 个命令方法都是 **async generator**（`async def` + `yield
  event.plain_result(...)`；AST 实测 45/45 有 `Yield`），**只能用 `async for` 迭代**；
* 旧宿主壳正是 `async for _item in _E.EconomyImpl.<m>(self, event): yield _item` —— 一次
  `yield` = 一条消息。宿主侧用 `_BRIDGE.run_async` **逐段回话、不做 `"\\n".join` 合并**，
  与旧壳的逐条语义（含分支/异常提示的行序与消息切分）逐字节相同；
* 同步桥 `_BRIDGE.run` 会把 `fn(env)` 的返回值（async generator 对象）当文本 join —— 形状
  不对，故**不适用**（不是「漏搬」）。

守卫与取参（数据来源）
----------------------
* `guards=("hook:player",)`：逐条 = 旧宿主装饰器 `@require_player()`。判定与文案都在包侧
  `content/guards.py::GUARDS["player"]`（`NO_PLAYER_HINT` 逐字 = 宿主
  `base.REGISTER_HINT` = `CommandBase.register_hint`），故拦截回话一字不差。
  `game/data/command_specs.json` 里这 45 条的 `guards` 都是 `["player"]`，一一对应。
* `params`：`"cmd=<命令词>"` = 该命令的主用法词（= `command_specs.json` 的 `usage` 首词，
  也逐字等于实现体里 `self._strip_cmd(event, "<词>")` 的那个词）；`"page"` 只加在
  **确实把玩家参数当页码用**的命令上（实测 10 条：`alchemy` / `cooking_list` / `craft` /
  `encyclopedia` / `titles` / `inventory` / `bag_filter` / `bestiary` / `adventure_book` /
  `shop`）。`params` 是编辑器/校验用的元数据（`content/commands.py::register` 注释：
  「运行时取参走 `env.arg_text(...)` / `env.page(...)`」），本域取参仍在实现体里
  （`self._strip_cmd(event, ...)` / `event.get_message_str()`）**逐字未动**。

I2（包内不 import 宿主）
------------------------
宿主面一律经注入句柄：`env.state["shell"]` = 宿主壳对象（`EconomyCmds` 实例，与样板
`cmds_tower` / 战斗族同源的过渡能力口），`env.raw` = 平台事件原样透传。实现体
`content/economy_cmds.py` 本来就把 `self` 当宿主取件口用 —— 本模块只把它从 `env` 取出来
传下去，**不改实现体的任何调用点**（时序/注册顺序逐点不变）。

行为逐字节不变
--------------
证据 = `overnight/b18l9_snap.py` 的 142 场景快照（45 条命令 × 正常/边界/失败 + 追加边界；
sha256 改前 = 改后）+ `tests/test_texts_table.py` 的 `[13]` 段（`ECONOMY_FROZEN` /
`ECONOMY_DB_SHA`）。
"""
from __future__ import annotations

from . import economy_cmds as _E
from .commands import COMMANDS


# ============================================================
# 取件口（env → 改造前命令体的实参）
# ============================================================
def _shell(env):
    """宿主壳对象（桥接层经 `env.state["shell"]` 注入）：实现体经它做宿主取件。"""
    return (env.state or {}).get("shell")


class _Say:
    """`env.raw`（平台事件）的最小替身：`plain_result(文本)` → **文本行**（返回 text 本身）。

    ★ W-L9 定点修（2026-09-15）：本族 handler 是 async generator，实现体是历史形状
    `yield event.plain_result(文本)`。此前 `_event()` 把**真事件**原样交给实现体 ⇒ `yield`
    出来的是**平台结果对象**（`MessageEventResult`），引擎 `Host._as_replies` 再 `str()` 它
    ⇒ 交付面成了 dataclass repr（实测 `str(MessageEventResult().message('hello'))` =
    `MessageEventResult(chain=[Plain(...)])`），**不是文案** —— 违反交付契约「只交 list[str]」。

    与 `content/cmds_player.py::_Say` / `content/cmds_world.py::_Say` 同形：`plain_result`
    收成已渲染行并返回文本；其余属性原样代理真事件（`get_message_str` / 壳的 `_strip_cmd` /
    转发期 `message_str` 赋值 / `stop_event` 全部照旧）⇒ 实现体**零改动**。
    """

    def __init__(self, ev):
        object.__setattr__(self, "_ev", ev)
        object.__setattr__(self, "lines", [])

    def plain_result(self, text):
        """把「一行文本」收起来并**返回文本本身**（实现体的 `yield` 值 = 一行文案）。"""
        self.lines.append(text)
        return text

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_ev"), name)

    def __setattr__(self, name, value):        # 转发期 `message_str` 交换等语义逐字保留
        setattr(object.__getattribute__(self, "_ev"), name, value)


def _event(env):
    """实现体看到的「平台事件」= **文本收集替身**（`plain_result` 落文本；其余代理真事件）。"""
    return _Say(env.raw)


async def _messages(agen) -> list:
    """async generator → `list[str]`（**每条 = 改造前的一次 `yield`** = 一条消息）。"""
    out = []
    async for _r in agen:
        out.append(_r)
    return out


def _declare(key, guards=(), params=()):
    """登记一条经济域命令（表形状与 `content/commands.py::register` 逐字段相同）。

    唯一差异 = 处理器是 `async def`（见模块头注：实现体是 async generator），故不经
    `register()`（它把 handler 包成同步 `render_panel(fn(env), env)`）；`guards` / `params`
    的语义与声明表（`game/data/command_specs.json` / 包内 `content/data/commands.json`）
    逐字对齐。重复 key 直接抛（与 `register()` 同口径）——见 `content/cmds_combat.py::_declare`
    与 `content/cmds_social.py::_declare` 同款先例。
    """
    def deco(fn):
        if key in COMMANDS:
            raise KeyError("content.commands：命令 %r 重复登记" % key)
        COMMANDS[key] = {"guards": tuple(guards), "params": tuple(params), "handler": fn}
        return fn
    return deco


# ============================================================
# ① 副业：采集 / 挖掘 / 炼金 / 烹饪 / 图纸 / 副业面板
# ============================================================
@_declare("gather", guards=("hook:player",), params=("cmd=采集",))
async def gather(env):
    """『采集』（旧宿主体：`@require_player()` → 取玩家 → 调包）。"""
    return await _messages(_E.EconomyImpl.gather(_shell(env), _event(env)))


@_declare("mining", guards=("hook:player",), params=("cmd=挖掘",))
async def mining(env):
    """『挖掘』（旧宿主体：`@require_player()` → 取玩家 → 调包）。"""
    return await _messages(_E.EconomyImpl.mining(_shell(env), _event(env)))


@_declare("alchemy", guards=("hook:player",), params=("cmd=炼金", "page"))
async def alchemy(env):
    """『炼金 [提纯] [页]』（旧宿主体：`self._strip_cmd(event, "炼金").strip()`）。"""
    return await _messages(_E.EconomyImpl.alchemy(_shell(env), _event(env)))


@_declare("alchemy_craft", guards=("hook:player",), params=("cmd=合成",))
async def alchemy_craft(env):
    """『合成 <药水>』（旧宿主体：`self._strip_cmd(event, "合成").strip()`）。"""
    return await _messages(_E.EconomyImpl.alchemy_craft(_shell(env), _event(env)))


@_declare("cooking_list", guards=("hook:player",), params=("cmd=烹饪列表", "page"))
async def cooking_list(env):
    """『烹饪列表 [页]』（旧宿主体：`self._strip_cmd(event, "烹饪列表").strip()`）。"""
    return await _messages(_E.EconomyImpl.cooking_list(_shell(env), _event(env)))


@_declare("cooking", guards=("hook:player",), params=("cmd=烹饪",))
async def cooking(env):
    """『烹饪 [料理名]』（旧宿主体：`self._strip_cmd(event, "烹饪").strip()`）。"""
    return await _messages(_E.EconomyImpl.cooking(_shell(env), _event(env)))


@_declare("bp_craft", guards=("hook:player",), params=("cmd=图纸合成",))
async def bp_craft(env):
    """『图纸合成 <图纸名/序号>』（旧宿主体：`self._strip_cmd(event, "图纸合成").strip()`）。"""
    return await _messages(_E.EconomyImpl.bp_craft(_shell(env), _event(env)))


@_declare("profession_view", guards=("hook:player",), params=("cmd=副业",))
async def profession_view(env):
    """『副业』（旧宿主体：`self._strip_cmd(event, "副业").strip()`）。"""
    return await _messages(_E.EconomyImpl.profession_view(_shell(env), _event(env)))


@_declare("prof_forget", guards=("hook:player",), params=("cmd=遗忘副业",))
async def prof_forget(env):
    """『遗忘副业 <名称>』（旧宿主体：`self._strip_cmd(event, "遗忘副业").strip()`）。"""
    return await _messages(_E.EconomyImpl.prof_forget(_shell(env), _event(env)))


@_declare("daily_prof", guards=("hook:player",), params=("cmd=副业任务",))
async def daily_prof(env):
    """『副业任务』（旧宿主体：`@require_player()` → 取玩家 → 调包）。"""
    return await _messages(_E.EconomyImpl.daily_prof(_shell(env), _event(env)))


@_declare("fishing", guards=("hook:player",), params=("cmd=垂钓",))
async def fishing(env):
    """『垂钓 [选择]』（旧宿主体：`@require_player()` → 取玩家 → 调包）。"""
    return await _messages(_E.EconomyImpl.fishing(_shell(env), _event(env)))


# ============================================================
# ② 锻造 / 强化 / 升级 / 原石 / 符文 / 重锻 / 炼成 / 附魔
# ============================================================
@_declare("craft", guards=("hook:player",), params=("cmd=锻造", "page"))
async def craft(env):
    """『锻造 [装备名/全部/配方] [页]』（旧宿主体：`self._strip_cmd(event, "锻造")`）。"""
    return await _messages(_E.EconomyImpl.craft(_shell(env), _event(env)))


@_declare("craft_commission", guards=("hook:player",), params=("cmd=代工",))
async def craft_commission(env):
    """『代工 <装备名>』（旧宿主体：`self._strip_cmd(event, "代工").strip()`）。"""
    return await _messages(_E.EconomyImpl.craft_commission(_shell(env), _event(env)))


@_declare("learn", guards=("hook:player",), params=("cmd=学习",))
async def learn(env):
    """『学习 <图纸名>』（旧宿主体：`self._strip_cmd(event, "学习").strip()`）。"""
    return await _messages(_E.EconomyImpl.learn(_shell(env), _event(env)))


@_declare("recipe_list", guards=("hook:player",), params=("cmd=配方",))
async def recipe_list(env):
    """『配方 / 图纸列表』（旧宿主体：`self._strip_cmd(event, "配方")`）。"""
    return await _messages(_E.EconomyImpl.recipe_list(_shell(env), _event(env)))


@_declare("enhance", guards=("hook:player",), params=("cmd=强化",))
async def enhance(env):
    """『强化 <装备>』（旧宿主体：`self._strip_cmd(event, "强化")`）。"""
    return await _messages(_E.EconomyImpl.enhance(_shell(env), _event(env)))


@_declare("equip_upgrade", guards=("hook:player",), params=("cmd=升级",))
async def equip_upgrade(env):
    """『升级 <装备>』（旧宿主体：`self._strip_cmd(event, "升级")`）。"""
    return await _messages(_E.EconomyImpl.equip_upgrade(_shell(env), _event(env)))


@_declare("gem_drill", guards=("hook:player",), params=("cmd=打孔",))
async def gem_drill(env):
    """『打孔 <装备>』（旧宿主体：`self._strip_cmd(event, "打孔")`）。"""
    return await _messages(_E.EconomyImpl.gem_drill(_shell(env), _event(env)))


@_declare("gem_socket", guards=("hook:player",), params=("cmd=镶嵌",))
async def gem_socket(env):
    """『镶嵌 <装备> <原石> [孔位]』（旧宿主体：`self._strip_cmd(event, "镶嵌")`）。"""
    return await _messages(_E.EconomyImpl.gem_socket(_shell(env), _event(env)))


@_declare("gem_remove", guards=("hook:player",), params=("cmd=拆卸",))
async def gem_remove(env):
    """『拆卸 <装备> [孔位]』（旧宿主体：`self._strip_cmd(event, "拆卸")`）。"""
    return await _messages(_E.EconomyImpl.gem_remove(_shell(env), _event(env)))


@_declare("gem_combine", guards=("hook:player",), params=("cmd=原石合成",))
async def gem_combine(env):
    """『原石合成 [原石]』（旧宿主体：`self._strip_cmd(event, "原石合成")`）。"""
    return await _messages(_E.EconomyImpl.gem_combine(_shell(env), _event(env)))


@_declare("gem_view", guards=("hook:player",), params=("cmd=原石",))
async def gem_view(env):
    """『原石』（旧宿主体：`@require_player()` → 取玩家 → 调包）。"""
    return await _messages(_E.EconomyImpl.gem_view(_shell(env), _event(env)))


@_declare("rune_craft", guards=("hook:player",), params=("cmd=符文制作",))
async def rune_craft(env):
    """『符文制作 [符文名]』（旧宿主体：`self._strip_cmd(event, "符文制作").strip()`）。"""
    return await _messages(_E.EconomyImpl.rune_craft(_shell(env), _event(env)))


@_declare("rune_remove", guards=("hook:player",), params=("cmd=符文拆卸",))
async def rune_remove(env):
    """『符文拆卸 <装备>』（旧宿主体：`self._strip_cmd(event, "符文拆卸")`）。"""
    return await _messages(_E.EconomyImpl.rune_remove(_shell(env), _event(env)))


@_declare("refine_equip", guards=("hook:player",), params=("cmd=装备重锻",))
async def refine_equip(env):
    """『装备重锻 <装备>』（旧宿主体：`self._strip_cmd(event, "装备重锻").strip()`）。"""
    return await _messages(_E.EconomyImpl.refine_equip(_shell(env), _event(env)))


@_declare("calamity_forge", guards=("hook:player",), params=("cmd=炼成",))
async def calamity_forge(env):
    """『炼成 <装备>』（旧宿主体：`self._strip_cmd(event, "炼成").strip()`）。"""
    return await _messages(_E.EconomyImpl.calamity_forge(_shell(env), _event(env)))


@_declare("enchant", guards=("hook:player",), params=("cmd=附魔",))
async def enchant(env):
    """『附魔 <装备> <属性/符文名>』（旧宿主体：`self._strip_cmd(event, "附魔")`）。"""
    return await _messages(_E.EconomyImpl.enchant(_shell(env), _event(env)))


@_declare("set_view", guards=("hook:player",), params=("cmd=套装",))
async def set_view(env):
    """『套装』（旧宿主体：`@require_player()` → 取玩家 → 调包）。"""
    return await _messages(_E.EconomyImpl.set_view(_shell(env), _event(env)))


# ============================================================
# ③ 图鉴 / 手册 / 百科 / 称号
# ============================================================
@_declare("monster", guards=("hook:player",), params=("cmd=怪物",))
async def monster(env):
    """『怪物 [名字]』（旧宿主体：`self._strip_cmd(event, "怪物").strip()`）。"""
    return await _messages(_E.EconomyImpl.monster(_shell(env), _event(env)))


@_declare("adventure_book", guards=("hook:player",), params=("cmd=冒险手册", "page"))
async def adventure_book(env):
    """『冒险手册 [分区] [页]』（旧宿主体：`self._strip_cmd(event, "冒险手册").strip()`）。"""
    return await _messages(_E.EconomyImpl.adventure_book(_shell(env), _event(env)))


@_declare("footprint", guards=("hook:player",), params=("cmd=足迹",))
async def footprint(env):
    """『足迹』（旧宿主体：`@require_player()` → 取玩家 → 调包）。"""
    return await _messages(_E.EconomyImpl.footprint(_shell(env), _event(env)))


@_declare("bestiary", guards=("hook:player",), params=("cmd=图鉴", "page"))
async def bestiary(env):
    """『图鉴 [类别/页]』（旧宿主体：`self._strip_cmd(event, "图鉴").strip()`）。"""
    return await _messages(_E.EconomyImpl.bestiary(_shell(env), _event(env)))


@_declare("encyclopedia", guards=("hook:player",), params=("cmd=百科", "page"))
async def encyclopedia(env):
    """『百科 <关键词> [页]』（旧宿主体：`self._strip_cmd(event, "百科").strip()`）。"""
    return await _messages(_E.EconomyImpl.encyclopedia(_shell(env), _event(env)))


@_declare("titles", guards=("hook:player",), params=("cmd=称号", "page"))
async def titles(env):
    """『称号 [名称/页]』（旧宿主体：`self._strip_cmd(event, "称号").strip()`）。"""
    return await _messages(_E.EconomyImpl.titles(_shell(env), _event(env)))


# ============================================================
# ④ 物品：背包 / 详情 / 装备 / 使用 / 出售 / 商店
# ============================================================
@_declare("inventory", guards=("hook:player",), params=("cmd=背包", "page"))
async def inventory(env):
    """『背包 [类型] [页数]』（旧宿主体：`self._strip_cmd(event, "背包")`）。"""
    return await _messages(_E.EconomyImpl.inventory(_shell(env), _event(env)))


@_declare("bag_filter", guards=("hook:player",), params=("cmd=背包筛选", "page"))
async def bag_filter(env):
    """『背包筛选 <类型> [页]』（旧宿主体：`self._strip_cmd(event, "背包筛选")`）。"""
    return await _messages(_E.EconomyImpl.bag_filter(_shell(env), _event(env)))


@_declare("item_view_mode_cmd", guards=("hook:player",), params=("cmd=物品详情开始",))
async def item_view_mode_cmd(env):
    """『物品详情开始 / 物品详情结束』（旧宿主体：`event.get_message_str().strip()` 直读）。"""
    return await _messages(_E.EconomyImpl.item_view_mode_cmd(_shell(env), _event(env)))


@_declare("item_detail", guards=("hook:player",), params=("cmd=物品详情",))
async def item_detail(env):
    """『物品详情 / 查看 <名称/序号>』（旧宿主体：`self._strip_cmd(event, "物品详情"/"查看")`）。"""
    return await _messages(_E.EconomyImpl.item_detail(_shell(env), _event(env)))


@_declare("my_equipment", guards=("hook:player",), params=("cmd=我的装备",))
async def my_equipment(env):
    """『我的装备』（旧宿主体：`@require_player()` → 取玩家 → 调包）。"""
    return await _messages(_E.EconomyImpl.my_equipment(_shell(env), _event(env)))


@_declare("equip", guards=("hook:player",), params=("cmd=装备",))
async def equip(env):
    """『装备 <序号/名称>』（旧宿主体：`self._strip_cmd(event, "装备")` + `我的装备` 直读）。"""
    return await _messages(_E.EconomyImpl.equip(_shell(env), _event(env)))


@_declare("unequip", guards=("hook:player",), params=("cmd=卸下",))
async def unequip(env):
    """『卸下 <部位>』（旧宿主体：`self._strip_cmd(event, "卸下").strip()`）。"""
    return await _messages(_E.EconomyImpl.unequip(_shell(env), _event(env)))


@_declare("use", guards=("hook:player",), params=("cmd=使用",))
async def use(env):
    """『使用 <物品>』（旧宿主体：`self._strip_cmd(event, "使用")`）。"""
    return await _messages(_E.EconomyImpl.use(_shell(env), _event(env)))


@_declare("sell", guards=("hook:player",), params=("cmd=出售",))
async def sell(env):
    """『出售 <名称/序号/类别> [数量]』（旧宿主体：`self._strip_cmd(event, "出售")`）。"""
    return await _messages(_E.EconomyImpl.sell(_shell(env), _event(env)))


@_declare("shop", guards=("hook:player",), params=("cmd=商店", "page"))
async def shop(env):
    """『商店 [页]』（旧宿主体：`self._strip_cmd(event, "商店")`）。"""
    return await _messages(_E.EconomyImpl.shop(_shell(env), _event(env)))


@_declare("buy", guards=("hook:player",), params=("cmd=购买",))
async def buy(env):
    """『购买 <物品> [数量]』（旧宿主体：`self._strip_cmd(event, "购买")`）。"""
    return await _messages(_E.EconomyImpl.buy(_shell(env), _event(env)))
