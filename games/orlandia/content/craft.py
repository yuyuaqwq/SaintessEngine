# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— craft 核心域实现（B13-L5，2026-09-14）。

真源 = 宿主 `game/core/craft.py`（原 67 行）**逐字搬**：函数体一字未改，只换「宿主取件」。

| 真源写法 | 包内 | 依据 |
|---|---|---|
| `from .drops import generate_equip, generate_roster_equip`（模块级） | `_HostAttr("core.drops", …)`（惰性替身） | **缺口**：`game/core/drops.py`（568 行，名册/随机装备生成 + 词条挂载）**不在本线清单**，且它自己 import `..content as C` / `..data` 一大片（B13 别的线在并行搬）→ 走宿主句柄，待其进包后再切包内直取 |
| `from ..data import CRAFT_RECIPES, CRAFT_RECIPE_ALIASES` | **仍走宿主句柄** `_HostAttr("data.craft", …)` | ⚠️ **本线实测的反例**：包内 `craft` 域（426 条）外层键是**字典序**（导出契约 `sort_table`），宿主 `CRAFT_RECIPES` 是**源插入序**——两者不是字段级可逆投影（I3）。迭代序会外泄到行为：`craft_recipe_search` 的子串兜底取「首次命中」、`craft_recipes_by_material` 的 `sort(key=lv)` 稳定排序并列项，实测 1325 条探针里 **检索 41 条 / 材料联想 87 条输出不同**（`overnight/w1213_l5_craft_order.py`）→ 切域 = 改行为，本线不切，登记缺口 |
| `from ..core.index import resolve, display as _display`（模块级） | `_HostAttr("core.index", …)`（惰性替身） | `game/core/index.py` 属 **B13-L7** 线（并行未落地）→ 按 SOP 用宿主句柄；另 `display("materials", …)` 依赖 `MATERIALS`（无同名域，§5 对照表列明）→ 落地后也仍要宿主面 |
| `from ..data import MATERIALS` | **未直接使用**（真源只在 `craft_recipe_make` 里算 `craft_cost`） | `MATERIALS` 在包内**无同名域**（BRIEF §5 列明）→ 不建第二份表 |

包内唯一直接取域的地方：无（本模块三张表/两个查询口全部走宿主句柄，理由如上）。

宿主侧：`game/core/craft.py` 现在只剩「加载包 + 模块别名」薄壳，见那边头注。
"""
import importlib
import sys

# ============================================================
# ① 宿主替身口（注入优先 → sys.modules → importlib；**绝不静默空跑**）
#    抄 `content/world_cmds.py` 的同款写法（B9 线2 定的包内标准形状）
# ============================================================
_HOST_PKG = "data.plugins.dragonfall.game"      # 运行时（main.py 的模块路径）
_HOST_PKG_FALLBACK = "game"                     # 测试/工具按 `game.xxx` 直接 import 时
_INJECTED = {}
_MOD = "craft"


def bind_host(**objs):
    """宿主薄壳 import 期注入（幂等）——键 = `_HostMod` 的模块名。"""
    for k, v in (objs or {}).items():
        if v is not None:
            _INJECTED[k] = v


def _host_module(name: str):
    """取宿主子模块（`name` 为空 = 宿主 `game` 包本身）。"""
    if name in _INJECTED:
        return _INJECTED[name]
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        m = sys.modules.get(prefix if not name else "%s.%s" % (prefix, name))
        if m is not None:
            return m
    last = None
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        try:
            return importlib.import_module(prefix if not name else "%s.%s" % (prefix, name))
        except Exception as exc:                # noqa: BLE001
            last = exc
    raise RuntimeError("%s：宿主模块 %s 取不到（%s）——拒绝静默空跑" % (_MOD, name, last))


def _host_attr(mod: str, attr: str):
    """宿主模块属性 —— 真源「`from ..<mod> import <attr>`」的同义替身（调用时解析）。"""
    m = _host_module(mod)
    try:
        return getattr(m, attr)
    except AttributeError:
        for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
            try:
                return importlib.import_module(
                    "%s.%s" % (prefix if not mod else "%s.%s" % (prefix, mod), attr))
            except Exception:                   # noqa: BLE001
                continue
        raise


class _HostAttr:
    """宿主「模块属性」惰性替身 —— 真源模块级 `from ..data import X` / `from .drops import f`
    的同义替身：模块级名字不变、正文一字未改；取值在**首次被访问**时发生（不强求 import 期宿主就绪）。"""

    __slots__ = ("_mod", "_attr", "_val")

    def __init__(self, mod, attr):
        object.__setattr__(self, "_mod", mod)
        object.__setattr__(self, "_attr", attr)

    def _v(self):
        try:
            return object.__getattribute__(self, "_val")
        except AttributeError:
            v = _host_attr(object.__getattribute__(self, "_mod"),
                           object.__getattribute__(self, "_attr"))
            object.__setattr__(self, "_val", v)
            return v

    def __getattr__(self, name):
        return getattr(self._v(), name)

    def __getitem__(self, k):
        return self._v()[k]

    def __setitem__(self, k, v):
        self._v()[k] = v

    def __contains__(self, k):
        return k in self._v()

    def __iter__(self):
        return iter(self._v())

    def __len__(self):
        return len(self._v())

    def __bool__(self):
        return bool(self._v())

    def __call__(self, *a, **kw):
        return self._v()(*a, **kw)


# ============================================================
# ② 宿主取件（模块级名字与真源逐名相同；正文零改动）
# ============================================================
generate_equip = _HostAttr("core.drops", "generate_equip")
generate_roster_equip = _HostAttr("core.drops", "generate_roster_equip")
# ★ B16-W11d：三张数据表改包内门面直取（原 `_HostAttr("data…")`）——
#   `CRAFT_RECIPES`/`CRAFT_RECIPE_ALIASES` ← catalog_rules 的**插入序** dump（`craft` 域是字典序、不可逆）；
#   `MATERIALS` ← catalog_items（域 `items`）。
from . import catalog_items as _citems
from .catalog_rules import CRAFT_RECIPES, CRAFT_RECIPE_ALIASES
MATERIALS = _citems.MATERIALS
resolve = _HostAttr("core.index", "resolve")
_display = _HostAttr("core.index", "display")


"""奥兰迪亚·余烬纪年数据层 - craft.py(v48：输入中文名 → resolve 转 ID 查表；装备名 display 转中文)"""
def craft_recipe_make(name: str, affinity: str | None = None) -> dict | None:
    """按配方锻造一件装备（装备等级 = 配方 lv，名字 = 配方名）
    阶段八：名册配方（roster_id）走名册精确生成（词条 v2/需求/套装）；
    affinity = 词条倾向（20 章 4.3：攻击/防御/元素/机动）"""
    rec = CRAFT_RECIPES.get(name)
    if not rec:
        return None
    if rec.get("roster_id"):
        equip = generate_roster_equip(rec["roster_id"], affinity)
    else:
        # 兜底（无 roster_id 的旧配方）：随机生成 + 覆盖名
        equip = generate_equip(rec["slot"], rec["lv"], rec["quality"],
                               rec.get("weapon_type"))
        equip["name"] = _display("recipes", name)  # v48：配方名转中文（背包/存档显示用中文名）
    # v41：毕业套配方强制带套装归属（set 字段），生成时写入装备
    if rec.get("set"):
        equip["set"] = rec["set"]
    # M10 P1-2 锻造→卖店印钞修复：记录锻造成本（材料价+锻造费），
    # 卖店回收按此封顶（≤ 成本，杜绝 材料→锻造→卖店 金币永动机）
    equip["craft_cost"] = sum(MATERIALS.get(m, {}).get("price", 0) * n for m, n in rec["mats"].items()) + rec.get("gold", 0)
    return equip

def craft_recipe_search(text: str):
    """模糊查找配方：精确名 > 别名 > 包含匹配(v48：输入中文/ID 都 resolve)
    M10 P2 空参防御：空串/纯空白返回 None（否则空串包含匹配恒 True 误中第一个配方）"""
    text = (text or "").strip()
    if not text:
        return None
    rid = resolve("recipes", text)
    if rid in CRAFT_RECIPES:
        return rid
    for k, aliases in CRAFT_RECIPE_ALIASES.items():
        if text in aliases:
            return k
    for k in CRAFT_RECIPES:
        if text in _display("recipes", k):  # 中文名包含匹配
            return k
    return None

def craft_recipes_by_material(text: str, max_show: int = 8):
    """#24 材料关键词联想：按材料名模糊匹配，返回使用该材料的配方
    返回 [(name, rec), ...]（按 lv 升序），无匹配返回 []
    """
    out = []
    for name, rec in CRAFT_RECIPES.items():
        hit = False
        for m in rec["mats"]:
            m_cn = _display("materials", m)
            if text in m_cn or m_cn in text:
                hit = True
                break
        # 图纸也可联想：搜「图纸」或蓝图名时命中需图纸的配方
        if not hit and rec.get("blueprint"):
            if text == "图纸" or text in rec["blueprint"] or rec["blueprint"] in text:
                hit = True
        if hit:
            out.append((name, rec))
    out.sort(key=lambda x: x[1]["lv"])
    return out[:max_show]
