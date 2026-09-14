# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— craft 核心域实现（B13-L5，2026-09-14）。

真源 = 宿主 `game/core/craft.py`（原 67 行）**逐字搬**：函数体一字未改，只换「宿主取件」。

| 真源写法 | 包内 | 依据 |
|---|---|---|
| `from .drops import generate_equip, generate_roster_equip`（模块级） | `_drops().generate_equip` / `_drops().generate_roster_equip`（**包内直取** `content/drops.py`） | **缺口已闭合**：`game/core/drops.py`（568 行）属 **B2-C2 线**，其冻结落点 `content/drops.py` **已落地**（框架仓提交 `99258b0`）⇒ 本模块两个孤儿读点（B2-C4 接手的 R2 登记项）实际取到包内实现；宿主同对象回退仅作过渡保险 |
| `from ..data import CRAFT_RECIPES, CRAFT_RECIPE_ALIASES` | **包内门面直取**（B16-W11d 已切：`catalog_rules` 的插入序 dump） | ⚠️ **反例保留在案**：包内 `craft` 域（426 条）外层键是**字典序**（导出契约 `sort_table`），不可逆 ⇒ **不切域**；切的是 `catalog_rules` 的**源插入序** dump（门禁逐值/逐序不等 0） |
| `from ..core.index import resolve, display as _display`（模块级） | **包内直取** `from .index import resolve, display`（B2-C4） | B13-L7 已落地 `content/index.py`（与宿主 `game/core/index.py` 薄壳**同一对象**，证据 `out/evidence/hostface_map.txt`） |
| `from ..data import MATERIALS` | **未直接使用**（真源只在 `craft_recipe_make` 里算 `craft_cost`） | `MATERIALS` 在包内**无同名域**（BRIEF §5 列明）→ 不建第二份表 |

包内唯一直接取域的地方：`catalog_items` / `catalog_rules`（B16-W11d）+ `content/index.py`（B2-C4）。

宿主侧：`game/core/craft.py` 现在只剩「加载包 + 模块别名」薄壳，见那边头注。
"""
import importlib
import sys

# ============================================================
# ① 包内取件（B2-C4 收口：`core.index` 已落地 → 包内直取；`core.drops` 待 B2-C2 落地）
# ============================================================
#: `core.drops` 面的包内落点（接口表第 5 行冻结：`content/drops.py`，B2-C2 线负责落地）
_DROPS_PKG = "content.drops"
_DROPS = None


def _drops():
    """`core.drops` 取件口（B2-C4）—— **包内直取** `content/drops.py`（接口表第 5 行冻结落点，
    B2-C2 已落地）；宿主 `game.core.drops` 为同对象过渡保险。

    判据 `out/evidence/identity_map.txt`：落地前 `C.generate_equip` / `C.generate_roster_equip`
    / `C.build_monster_group` / `C.roll_blueprint` 在包内**无同对象**（真源属 B2-C2 线）；
    C2 落地 `content/drops.py`（提交 `99258b0`）后本口自动切到包内实现。
    """
    global _DROPS
    if _DROPS is None:
        try:
            _DROPS = importlib.import_module(_DROPS_PKG)
        except ImportError:
            last = None
            for prefix in ("data.plugins.dragonfall.game", "game"):
                m = sys.modules.get("%s.core.drops" % prefix)
                if m is not None:
                    _DROPS = m
                    break
            if _DROPS is None:
                for prefix in ("data.plugins.dragonfall.game", "game"):
                    try:
                        _DROPS = importlib.import_module("%s.core.drops" % prefix)
                        break
                    except Exception as exc:                    # noqa: BLE001
                        last = exc
            if _DROPS is None:
                raise RuntimeError("craft：core.drops 取不到（%s）——拒绝静默空跑" % (last,))
    return _DROPS


# ============================================================
# ② 取件（模块级名字与真源逐名相同；正文零改动）
# ============================================================
# ★ B16-W11d：三张数据表改包内门面直取（原宿主句柄）——
#   `CRAFT_RECIPES`/`CRAFT_RECIPE_ALIASES` ← catalog_rules 的**插入序** dump（`craft` 域是字典序、不可逆）；
#   `MATERIALS` ← catalog_items（域 `items`）。
from . import catalog_items as _citems
from .catalog_rules import CRAFT_RECIPES, CRAFT_RECIPE_ALIASES
MATERIALS = _citems.MATERIALS
# ★ B2-C4：`core.index` 已落地（B13-L7）→ 包内直取（同一对象，证据 `hostface_map.txt`）
from .index import display as _display          # noqa: E402
from .index import resolve                      # noqa: E402


def generate_equip(*args, **kwargs):
    """真源模块级 `from .drops import generate_equip` —— B2-C4：包内 `content/drops.py` 优先。

    （B2-C2 线尚未落地该模块 → 过渡期回退宿主 `game.core.drops` 同对象；见 `_drops()`。）
    """
    return _drops().generate_equip(*args, **kwargs)


def generate_roster_equip(*args, **kwargs):
    """真源模块级 `from .drops import generate_roster_equip` —— 同上。"""
    return _drops().generate_roster_equip(*args, **kwargs)


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
