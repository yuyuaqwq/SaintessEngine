# -*- coding: utf-8 -*-
"""《奥兰迪亚·余烬纪年》包内**种族天赋展示格式化注册表**（逐字搬自游戏仓
`game/core/race_talent_display.py`，195 行）。

真源 = 「天赋 key → 展示文案」注册表（`DISPLAY` + `register` + `format_talent`），消灭
`commands/player.py races()` 里的 if-elif 硬编码。宿主 `game/core/race_talent_display.py`
现在是薄壳（全名单再导出），消费者 2 处（`game/commands/player.py:417/697`，函数内
`from ..core.race_talent_display import format_talent`）零改动。

正文改动面（3 处宿主取件，其余逐字）：
  ① `format_talent` 内 `from ..log_setup import LOG` → `LOG = _host_attr("log_setup", "LOG")`（平台/运维面，留宿主）
  ②/③ `_d_berserk_hp` / `_d_timid_hp` 内 `from ..data.races import RACE_ATTACK_MULT`
     → ★ **B16-W11b（2026-09-14）**：`from .catalog_rules import RACE_ATTACK_MULT`（包内门面）
     —— `races` 域只有 `name/icon/desc/talents/talent_names`（无攻击系数表）⇒ 门面字面量、登记 `NOT_YET_DOMAINED`。
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
"""奥兰迪亚·余烬纪年核心层 - race_talent_display.py（v98.3：种族天赋展示格式化注册表）

消灭 commands/player.py races() 里的 if-elif 硬编码：
天赋数据只声明 key → 值，展示文案统一走本模块注册表。

扩展方式：
- 加天赋类型：data/races.py 加字段 + 本文件 register 一个格式化函数（~5 行）
- 函数签名：fn(v, name) -> str（name 为天赋显示名，来自 races talent_names）
"""
DISPLAY = {}


def register(key):
    """展示格式化注册装饰器。"""
    def deco(fn):
        DISPLAY[key] = fn
        return fn
    return deco


def format_talent(k, v, name):
    """返回天赋展示文本；未知 key 返回 None（不显示，与原 elif 链无 else 一致）。

    v105 P3(M01)：未知 key 打告警日志（原静默缺失）——races.py 新增天赋忘记
    注册展示文案时日志可见，防无声缺失。
    """
    fn = DISPLAY.get(k)
    if fn is None:
        LOG = _host_attr("log_setup", "LOG")
        LOG.warning(
            f"[dragonfall] 种族天赋无展示注册: {k}（data/races.py 新增天赋需在 "
            "race_talent_display.py 注册 format 函数）"
        )
        return None
    return fn(v, name)


# ================= 格式化实现（文案与原实现逐字一致） =================

@register("hp_mult")
def _d_hp_mult(v, name):
    pct = int((v - 1) * 100)
    # v113.6 描述补全：明确"最大生命"（此前只有 ±% 看不出是血量）
    return f"{'🔻' if v < 1 else ''}{name} 最大生命{pct:+d}%"


@register("growth_mult")
def _d_growth_mult(v, name):
    pct = int((v - 1) * 100)
    # v113.6 描述补全：明确"全属性成长"
    return f"{'🔻' if v < 1 else ''}{name} 全属性成长{pct:+d}%"


@register("spd_mult")
def _d_spd_mult(v, name):
    pct = int((v - 1) * 100)
    # v113.6 描述补全：明确"先手速度"
    return f"{'🔻' if v < 1 else ''}{name} 先手速度{pct:+d}%"


@register("crit_add")
def _d_crit_add(v, name):
    return f"{name} 暴击+{int(v*100)}%"


@register("phys_reduce")
def _d_phys_reduce(v, name):
    if v > 0:
        # v113.6 描述补全：明确"受物理伤害"
        return f"{name} 受物理伤害-{int(v*100)}%"
    return f"🔻{name} 受物理伤害+{int(-v*100)}%"


@register("magic_reduce")
def _d_magic_reduce(v, name):
    if v > 0:
        # v113.6 描述补全：明确"受魔法伤害"
        return f"{name} 受魔法伤害-{int(v*100)}%"
    return f"🔻{name} 受魔法伤害+{int(-v*100)}%"


@register("heal_received")
def _d_heal_received(v, name):
    if v > 0:
        return f"{name} 受疗+{int(v*100)}%"
    return f"🔻{name} 受疗{int(v*100)}%"


@register("berserk_hp")
def _d_berserk_hp(v, name):
    # v181.D（P1-D）：倍率读 data/races.py RACE_ATTACK_MULT（原从 battle 反向 import，
    # 随 battle 常量下沉改读数据单源；调值只改 races.py，本展示与 battle 结算自动同步）
    from .catalog_rules import RACE_ATTACK_MULT   # ★ B16-W11b：包内门面（真源 game/data/races.py:115）
    pct = round((RACE_ATTACK_MULT["berserk"] - 1) * 100)
    return f"{name} 残血攻＋{pct}%"


@register("timid_hp")
def _d_timid_hp(v, name):
    # v181.D（P1-D）：倍率读 data/races.py RACE_ATTACK_MULT（原从 battle 反向 import，
    # 随 battle 常量下沉改读数据单源；调值只改 races.py，本展示与 battle 结算自动同步）
    from .catalog_rules import RACE_ATTACK_MULT   # ★ B16-W11b：包内门面（真源 game/data/races.py:115）
    pct = round((1 - RACE_ATTACK_MULT["timid"]) * 100)
    return f"🔻{name} 残血攻－{pct}%"


@register("first_hit")
def _d_first_hit(v, name):
    return f"{name} 首击+{int(v*100)}%"


@register("learn_discount")
def _d_learn_discount(v, name):
    return f"{name} 学习-{int(v*100)}%"


@register("first_upgrade_refund")
def _d_first_upgrade_refund(v, name):
    # v134.1 人类·博学者：首次升级技能返还 1 技能点（每技能一次）。展示补全（此前缺注册
    # → 人类『种族』一览/注册种族说明里该天赋整条不显示，反馈#50「种族说明模糊」）
    n = int(v or 0)
    return f"{name} 每技能首次升级返还 {n} 技能点"


@register("prof_bonus")
def _d_prof_bonus(v, name):
    # v134.1 人类·副业亲和：副业经验 +10%（professions.add_prof_exp 消费）
    return f"{name} 副业经验+{int(v*100)}%"


# A0-C1 深潜：v106.2 半身人"幸运儿"已由 gold_bonus 改用于 luck（见 data/races.py 半身人
# talents）；全库种族已无 gold_bonus 天赋 key，原 @register("gold_bonus") 展示注册为死代码，
# 故删除。若未来种族复用"金币+"天赋，于此重新 register 即可。


# v110 审计修复：补 v106.2/3 新增 5 条正面天赋的展示注册（此前缺注册 →
# format_talent 返 None → 『种族』命令静默不显示，仅 stderr 告警）
@register("exp_bonus")
def _d_exp_bonus(v, name):
    return f"{name} 经验+{int(v*100)}%"


@register("crit_dmg")
def _d_crit_dmg(v, name):
    return f"{name} 暴伤+{int(v*100)}%"


@register("block")
def _d_block(v, name):
    return f"{name} 格挡+{int(v*100)}%"


@register("lifesteal")
def _d_lifesteal(v, name):
    return f"{name} 吸血+{int(v*100)}%"


@register("luck")
def _d_luck(v, name):
    return f"{name} 幸运+{int(v*100)}%"


@register("item_effect")
def _d_item_effect(v, name):
    return f"{name} 消耗品+{int(v*100)}%"


@register("craft_bonus")
def _d_craft_bonus(v, name):
    return f"{name} 锻造经验+{int(v*100)}%"


@register("explore_item")
def _d_explore_item(v, name):
    return f"{name} 探索物品+{int(v*100)}%"


# ============ v181.D 引擎结算标签键（不参与玩家可见天赋展示） ============
# 以下键为 battle._race_attack_mult 结算标签用（数据驱动），非玩家天赋：注册返回 None
# 使其在『种族』/面板展示中静默隐藏（format_talent 未知键会打告警日志，需显式注册占位）。

@register("berserk_tag")
def _d_berserk_tag(v, name):
    return None


@register("timid_tag")
def _d_timid_tag(v, name):
    return None


@register("first_hit_tag")
def _d_first_hit_tag(v, name):
    return None
