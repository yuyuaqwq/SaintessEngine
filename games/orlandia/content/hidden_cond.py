# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— 隐藏怪环境条件注册表（B13 线3，2026-09-14）。

真源：游戏仓 `game/core/hidden_cond.py`（86 行）。本模块 = 那个模块的**实现本体**
（`ENV_KEYWORDS` / `CONDITIONS` / `register` / `HiddenCtx` / `envs_of` / 6 个条件函数 /
`check_cond` **逐字全搬，零改动面**）；宿主 `game/core/hidden_cond.py` 只剩再导出。

消灭 commands/combat.py _roll_hidden_monster() 里的关键词元组 + cond elif 链：
隐藏怪数据只声明 cond 名，环境判定统一走本模块注册表。

扩展方式：
- 加环境类型：ENV_KEYWORDS 加一组关键词 + CONDITIONS 注册一个函数（~5 行）
- 函数签名：fn(ctx) -> bool，ctx 为 HiddenCtx（mid/cur_map/is_night/envs）

消费者（两处，import 点零改动）
-------------------------------
    content/combat_cmds.py:915      `_host_attrs("core.hidden_cond", "envs_of", "check_cond", "HiddenCtx")`
                                    （B10 线5 产物：仍经宿主薄壳解析 —— 待收口为 `from .hidden_cond import …`）
    tests/test_v98_03_registry.py    `HC.ENV_KEYWORDS` / `HC.register` / `HC.envs_of` / `HC.check_cond`
                                    （注册新环境 + 关键词扩展，要求**同一批对象**：壳与包共享同一 dict ✅）
    tests/test_v97_06_eggs_hidden.py 经 `core/combat` 间接消费（隐藏怪 cond 判定）

本模块 **零宿主依赖**（无 db / 无 content 聚合层）—— 是 B13 线3 里唯一「一搬就完事」的一个。
等价证据：`overnight/w1213_b13l3_snap.py`（E4–E9：关键词表 / 6 图位图 / 全 cond × 上下文矩阵 /
未知 cond 按 any / 注册即生效 + 可撤销）· `overnight/W-B13-L3-events-dialogue.md`。
"""
# 地图 ID 关键词 → 环境分类（历史实现直接写在 combat.py，v98.3 数据化）
ENV_KEYWORDS = {
    "forest": ("forest", "wood", "glade"),
    # v110 审计修复：补 "trench"——深海鮟鱇 e_deep_angler 限定图 mist_trench（迷雾海沟）
    # 原无任何 water 关键词命中 → cond="water" 恒 False，该隐藏怪永刷不出（"击败全部
    # 25 种隐藏怪"成就与荧光鳞掉落不可达）；deep_dragon_palace/shipwreck_graveyard 为
    # 深海/沉船语义但 id 无关键词，仍由 mist_trench 命中补全可刷性
    "water": ("river", "lake", "sea", "reef", "dock", "swamp", "brook", "trench"),
    "ruin": ("ruin", "mine", "abyss", "battlefield", "altar", "tunnel", "crypt"),
}

CONDITIONS = {}


def register(name):
    """条件注册装饰器。"""
    def deco(fn):
        CONDITIONS[name] = fn
        return fn
    return deco


class HiddenCtx:
    """隐藏怪环境判定上下文。envs 为 {环境名: bool} 预计算位图。"""

    def __init__(self, mid, cur_map, is_night, envs):
        self.mid = mid
        self.cur_map = cur_map
        self.is_night = is_night
        self.envs = envs

    def env(self, name):
        return bool(self.envs.get(name))


def envs_of(mid: str) -> dict:
    """按地图 ID 计算环境位图（关键词包含匹配）。"""
    return {name: any(k in mid for k in keys) for name, keys in ENV_KEYWORDS.items()}


# ================= 条件实现 =================

@register("any")
def _c_any(ctx):
    return True


@register("forest_night")
def _c_forest_night(ctx):
    return ctx.env("forest") and ctx.is_night


@register("forest")
def _c_forest(ctx):
    return ctx.env("forest")


@register("water")
def _c_water(ctx):
    return ctx.env("water")


@register("ruin")
def _c_ruin(ctx):
    return ctx.env("ruin")


@register("night_any")
def _c_night_any(ctx):
    return ctx.is_night


def check_cond(cond: str, ctx) -> bool:
    """cond 名 → 判定；未知 cond 按 any 处理（与原实现一致：其他走无限制）。"""
    fn = CONDITIONS.get(cond or "any", CONDITIONS["any"])
    return fn(ctx)
