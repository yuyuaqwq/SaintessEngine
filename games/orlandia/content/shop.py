# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年 · 交易区服务实现（B9 线 L1 端口，2026-09-13）

真源 = 宿主 `game/services/shop.py`（496 行）**逐字端口**（P4-3 ShopService + TradeService 正文，
含常量 `SHOP_EQUIP_PRICE_MULT` / `_SHOP_EQUIP_PRICE_OVERRIDE` / `_MAT_FACILITY` /
`_MAT_FACILITY_HINT` 与定价/货架/回收/限购/序号分派函数），**只动 import 层**：
`from .. import content as C` → 本包惰性引用；函数体内 `from .. import db` / `from ..core…`
→ 取件器 `_h(...)`（同语义、缺件 fail-closed）。

消费端：宿主壳 `game/services/shop.py`（一行转发 + 再导出）与包内 `content/economy_cmds.py`
（`_shop_svc.*` 调用点照原样）。
"""
from .economy_host import _HostRef, _h  # noqa: F401

# ---- B14-2 L5：数据名读点切包内门面（`C.<数据名>` → 门面直取；函数名/缺口名仍留 `C.<名>`）----
from . import catalog_core as _cc     # 常量/职业/种族/面板公式
from . import catalog_items as _ci    # 物品/材料/符文/装备名册
from . import catalog_life as _cl     # 生活/副业/商店/宠物/经济配置
from . import catalog_space as _sp    # 地图/子区域
from . import catalog_b143 as _b143   # B14-3 收口名（QUALITY/WEAPON_FLAVOR）
# ---- B14-2 L5 读点切换（2026-09-14）----
# 数据名读点（SHOP_EQUIP/SHOP_WEAPONS/PAWN_RATES/ECON_CONFIG/FISH_POOL/MOUNT_BY_KEY ·
# EQUIP_ROSTER/EQUIP_ROSTER_BY_NAME/MATERIALS/MATERIALS_BY_NAME/ITEMS · MAP_BY_ID ·
# ITEM_TYPE_PET_EGG/ITEM_TYPE_MOUNT）已切包内门面（见文件头 `_cc/_ci/_cl/_sp` import 块）。
# 仍留 `C.<名>` 的只有：① 宿主函数（equip_stats/equip_value/generate_equip/mount_effects/
# get_dialogue/dialogue_node/roll_blueprint/generate_roster_equip）
# （② 域缺口 QUALITY/WEAPON_FLAVOR 已由 B14-3 门面 `catalog_b143` 补上 → 2026-09-14 切净）。

# ---- 宿主面（宿主壳 bind_host() 注入；顺序铁律见 economy_host 模块头）----
C = _HostRef("C")
db = _HostRef("db")
_ss = _HostRef("_ss")
_sshop = _HostRef("_sshop")
_eq_random_desc = _HostRef("_eq_random_desc")


# ============ 模块常量（economy.py 原样随迁） ============

# v101.25e 商店装备价格系数（鱼鱼拍板数值方案：商店价 = 确定性推导价 × 品质系数）
# v101.25h3 鱼鱼：品质价格差距调大——原白2.0/绿1.7/蓝1.5/紫1.3/橙1.2 递减系数把品质属性倍率抵消，
# 最终橙/白价格只差 1.2 倍（橙装属性 2 倍但价格几乎没差）。改为递增系数：
# 最终价格比（属性倍率×价格系数）：白2.0 / 绿3.12 / 蓝4.80 / 紫7.20 / 橙11.0（橙≈白 5.5 倍）
SHOP_EQUIP_PRICE_MULT = {"white": 2.0, "green": 2.4, "blue": 3.0, "purple": 4.0, "orange": 5.5}

# v130.2d R2：SHOP_EQUIP 条目可选 dict 覆盖价 {"rid": ..., "price": ...}
# （圣徽·誓约新手保底：推导价公式对低等级蓝装过贵；显示与购买同源取本表，事件折扣仍生效）
_SHOP_EQUIP_PRICE_OVERRIDE = {}
for _shop_list in _cl.SHOP_EQUIP.values():
    for _entry in _shop_list:
        if isinstance(_entry, dict) and _entry.get("rid") and _entry.get("price") is not None:
            _SHOP_EQUIP_PRICE_OVERRIDE[_entry["rid"]] = int(_entry["price"])

# v101.25e 材料类型 → 回收设施（鱼鱼拍板：不同设施收不同材料）
_MAT_FACILITY = {
    "矿石": "smith", "木材": "smith", "兽材": "smith", "宝石": "smith",
    "草药": "alchemy", "精华": "alchemy",
    "食材": "shop", "织物": "shop", "杂物": "shop",
    "收藏": "shop", "传说": "shop", "任务道具": "shop",
}

# q7-8：材料回收品类提示（新手按类型去对应柜台，防跑错店）——集中一处维护，出售提示复用
_MAT_FACILITY_HINT = ("材料按类型分店回收：矿石/木材/兽材/宝石→铁匠铺、"
                      "草药/精华→草药铺/炼金工坊、食材/织物/杂物→商店")


# ============ 装备属性需求（交易区共享：面板标注 + 武器推导） ============

def req_label(r: dict) -> str:
    """v101.28l #443：货架标注属性需求（防买了穿不上，船长帽事件）"""
    req = r.get("req") or {}
    if not req:
        return ""
    names = {"str": "力量", "agi": "敏捷", "int": "智力", "vit": "耐力"}
    return "需" + "、".join(f"{names.get(k, k)}{v}" for k, v in req.items())


# ============ 商店装备定价 / 货架 / 生成（economy._shop_equip_* 原样随迁） ============

def equip_price(slot: str, lv: int, quality: str, weapon_type: str | None = None,
                rid: str | None = None) -> int:
    """v101.25e 商店装备价：确定性基础推导价（含武器类型风味，不含随机词条）× 品质系数。
    显示价与购买价同源，避免词条随机导致价格漂移。
    v130.2d R2：rid 命中 SHOP_EQUIP 覆盖价（{"rid":..,"price":..}）时直接返回覆盖价。"""
    if rid and rid in _SHOP_EQUIP_PRICE_OVERRIDE:
        return _SHOP_EQUIP_PRICE_OVERRIDE[rid]
    stats = C.equip_stats(slot, lv, quality)
    flavor = _b143.WEAPON_FLAVOR.get(weapon_type, {}) if slot == "weapon" else {}
    for fk, fv in flavor.items():
        if fk == "desc" or not isinstance(fv, (int, float)):
            continue
        if fk == "crit":
            stats["crit"] = round(stats.get("crit", 0) + fv, 3)
        elif fk == "spd_fix":
            stats["spd"] = stats.get("spd", 0) + int(fv)
        elif fk == "hp_fix":
            stats["hp"] = stats.get("hp", 0) + int(fv)
        else:
            stats[fk] = stats.get(fk, 0) + int(stats.get(fk, 0) * fv)
    base = int(C.equip_value(stats) * (_cl.ECON_CONFIG["shop_equip_price_base"] + lv * _cl.ECON_CONFIG["shop_equip_price_lv"]) * _b143.QUALITY[quality]["mult"])
    return int(base * SHOP_EQUIP_PRICE_MULT.get(quality, 1.5))


def equip_roster(player: dict, equip_items: list) -> list:
    """v101.25e 商店装备列表 = 静态配置 ∪ 动态补档（玩家 lv±2 内 商店/锻造 源名册装备，最多 3 件）。
    修 #298 商店装备等级断层：每个等级都有装备可买（Lv.30+ 防具走锻造/图纸/副本经济，不破坏专属掉落）。
    v130.2d R2：静态条目支持 {"rid":..,"price":..} 覆盖价 dict——此处统一归一为 rid 字符串，
    覆盖价由 _SHOP_EQUIP_PRICE_OVERRIDE（模块级）读取，列表/购买逻辑无感。"""
    base = [e["rid"] if isinstance(e, dict) else e for e in equip_items]
    exist = set(base)
    # v101.28m #440：排除 SHOP_WEAPONS 已上架的武器名册（圣光长剑重复上架事件——
    # 静态武器表与动态补档各加一次，同价 7998G 出现两行）
    cur = player.get("cur_map", "")
    _area_id = _sp.MAP_BY_ID.get(cur, {}).get("area", cur)
    for wname, *_rest in (_cl.SHOP_WEAPONS.get(cur) or _cl.SHOP_WEAPONS.get(_area_id, [])):
        for _rid in _ci.EQUIP_ROSTER_BY_NAME.get(wname, []):
            exist.add(_rid)
    plv = player["level"]
    cands = sorted(
        (rid for rid, r in _ci.EQUIP_ROSTER.items()
         if r.get("source") in ("商店", "锻造") and abs(r["lv"] - plv) <= 2 and rid not in exist),
        key=lambda rid: abs(_ci.EQUIP_ROSTER[rid]["lv"] - plv),
    )
    return base + cands[:3]


def buy_weapon(wname: str, wtype: str, wlv: int, wq: str) -> dict:
    """阶段八：商店武器生成。名册名走名册精确生成（正确 req + 固定词条），
    非名册武器名（兜底）走随机生成再覆盖名。"""
    _eq_random_desc = _h('_eq_random_desc')  # ← from ..core.drops import _eq_random_desc  # 原 economy.py:22 模块级 import（函数内等位）
    ids = _ci.EQUIP_ROSTER_BY_NAME.get(wname, [])
    if ids:
        return C.generate_roster_equip(ids[0])
    eq = C.generate_equip("weapon", wlv, wq, wtype)
    eq["name"] = wname
    # v103.0 修复（round103 小蓝抓包）：generate_equip 的 desc 用随机 roll 出的名字生成
    # （如"烈焰长弓"），覆盖固定名后必须同步重写 desc，否则物品名与描述不符
    # （硬木战弓 desc 曾写"烈焰长弓——冒险途中得来"）
    eq["desc"] = _eq_random_desc(wname, "weapon", wtype)
    return eq


# ============ 出售域（sell） ============

def cur_subarea(player: dict) -> dict:
    """当前所在子区域 dict（无则 {}）。"""
    cur_map = player.get("cur_map", "")
    sa_id = player.get("cur_subarea") or ""
    cm = _sp.MAP_BY_ID.get(cur_map, {})
    for sa in (cm.get("subareas") or []):
        if sa["id"] == sa_id:
            return sa
    return {}


def is_smith_shop(player: dict) -> bool:
    """v92 铁匠类商店：craft 场所只卖武器+锻造材料。
    炼金/草药类除外——funcs 含 alchemy 或名字含『草药/炼金』（如晨曦药剂坊 dawn_city_5）
    均不算 smith（炼金卖药剂合理，v104 M09 P1 修复）。"""
    sa = cur_subarea(player)
    if not sa:
        return False
    # v104 M09 P1 修复：herb 判定与 _sa_shop_kind 同源（alchemy funcs / 草药·炼金名），
    #   否则晨曦药剂坊(dawn_city_5, shop+craft+alchemy)被误判 smith → 卖武器/图纸（策划案 07 章 6.2 草药铺不卖武器）
    if "alchemy" in (sa.get("funcs") or []) or any(k in sa.get("name", "") for k in ("草药", "炼金")):
        return False
    funcs = sa.get("funcs") or []
    if "craft" in funcs:
        return True
    return any(k in sa.get("name", "") for k in ("铁匠", "锻造", "军械", "工坊", "强化"))


def pawn_rate(player: dict, d: dict, *, is_smith_shop_=None, at_shop=None):
    """v101.21 出售地点限制：装备→铁匠/工坊（原价）；材料→按类型分设施（v101.25e 鱼鱼拍板）：
    矿石/木材/兽材/宝石→铁匠铺(0.9)；草药/精华→炼金铺(0.9)；食材/织物/杂物→商店(0.8)；其他→1.0。
    F1 P1-5：无 slot 消耗品（药水/食物/卷轴/炼金/烹饪产物）回收由 1.0 全价下调到 0.85——
    原回落 1.0 与材料 0.8~0.9 明显倒挂，白送金币（与造物成本封顶互补，_sell_one 还有 craft_cost 封顶兜底）。
    v125：回收率数据下沉 prof_config.PAWN_RATES。
    is_smith_shop_/at_shop：命令层位置守卫注入（base._is_smith_shop/_at_shop 语义），缺省回退本模块纯 C 判定。"""
    if is_smith_shop_ is None:
        is_smith_shop_ = is_smith_shop
    if d.get("slot"):  # 装备必须去铁匠铺卖（回收装备是铁匠的活）
        if is_smith_shop_(player):
            return _cl.PAWN_RATES["equip"]
        return None
    # v105 M17 P3-3：宠物蛋/坐骑缰绳回收折价 0.5（此前无 slot 且非材料 → 1.0 全价，
    # 掉落蛋/缰绳=白送金币；与装备回收同档，防刷钱。宠物蛋按品质已分档定价 100~500）
    if d.get("type") in (_cc.ITEM_TYPE_PET_EGG, _cc.ITEM_TYPE_MOUNT):
        return _cl.PAWN_RATES["pet_mount"]
    # v95.32 #397b：材料判定按名查表（data.type 可能是分类名如"精华/草药"，非"材料"）
    mm = _ci.MATERIALS_BY_NAME.get(d.get("name", "")) or {}
    if not mm:
        # F1 P1-5：非材料、非装备（药水/食物/卷轴/炼金/烹饪产物等消耗品）回收 0.85，
        # 与材料档对齐，避免白送金币（收藏鱼等特殊物在 _sell_one 单独置回 1.0）
        return _cl.PAWN_RATES["consumable"]
    mtype = mm.get("type", "杂物")
    need = _MAT_FACILITY.get(mtype, "shop")
    sa = cur_subarea(player)
    if not sa:
        return None
    name = sa.get("name", "")
    funcs = sa.get("funcs") or []
    if need == "alchemy" and ("炼金" in name or "alchemy" in funcs):
        return _cl.PAWN_RATES["mat_alchemy"]
    if need == "smith" and is_smith_shop_(player):
        return _cl.PAWN_RATES["mat_smith"]
    if need == "shop" and at_shop(player):
        return _cl.PAWN_RATES["mat_shop"]
    return None


def is_quest_item(d: dict) -> bool:
    """v104 M08 P0-1：任务道具判定（批量/单件出售保护共用）。

    双判据：背包 data.type 直接标注 或 按名查 MATERIALS_BY_NAME 定义兜底。
    （发放路径入包只拷 name/price 时 type 被写死为"材料"——world.py 支线奖励/
    采集/挖掘/副本拾取等均如此，仅靠 data.type 会漏判，烬火信标即可被『出售 全部』误卖。）
    """
    if d.get("type", "") == "任务道具":
        return True
    mm = _ci.MATERIALS_BY_NAME.get(d.get("name", ""))
    return bool(mm and mm.get("type") == "任务道具")


def fish_weight_max(d: dict):
    """v126.1 大鱼卖更贵：鱼种 weight_range 上限（kg）——FISH_POOL 按名反查；
    非鱼种/未配区间返回 None（按原价 1.0 系数）。"""
    for f in _cl.FISH_POOL:
        if f.get("name") == d.get("name"):
            wr = f.get("weight_range")
            return wr[1] if wr and len(wr) > 1 else None
    return None


def sell_one(group_id, qq_id, player, it, rate, *, is_smith_shop_=None, at_shop=None):
    """出售单件物品（按回收价），返回 (名称, 数量, 金币) 或 None。
    v101.13 坐骑 sell_bonus：骑乘驮兽类坐骑出售价格加成。"""
    db = _h('db')  # ← from .. import db  # 惰性导入
    d = it["data"]
    meff = C.mount_effects(player)
    sell_mult = 1.0 + float(meff.get("sell_bonus", 0) or 0)
    # v101.25e 装备回收价：掉落装备卖商店 = 推导价 × 0.5（装备掉落是锦上添花，不能成主要收入）
    # v101.27 鱼鱼拍板上调：0.3 → 0.5（playtest 观察"回收≈买入价15%"，旧库存只回 3 金，
    # 装备误购回收惨淡；0.5 仍低于买入价，不构成刷钱渠道）
    # v95.32 #397b：判据用 slot 而非 quality——v101.25e 起材料也注入全服品质字段，材料被打 0.3 折是 bug
    if d.get("slot"):
        rate = min(rate, _cl.ECON_CONFIG["equip_resale_rate"])
    # M10 P1-2 锻造→卖店印钞修复：锻造产物（craft_cost=材料价+锻造费）卖店最多回本，
    # 杜绝 材料→锻造→卖店 金币永动机（104/114 配方净赚，最高 +1234%）。
    # F1 P1-5：原仅覆盖装备分支持有 craft_cost 的造物，现扩展到炼金/烹饪等带 craft_cost 的
    # 消耗品造物——与 _pawn_rate 0.85 档互补，杜绝「低材→高值消耗品→卖店」利润通道。
    cc = d.get("craft_cost")
    if cc and d.get("price"):
        rate = min(rate, cc / d["price"])
    # v104 M15 修复：彩蛋收藏鱼（type=收藏）跳过 0.8 折扣按 1 金币原价回收
    # （原 int(1×0.8)=0 返回 None，收藏鱼永久占包无法回收）
    # v104 R3 M15 P1-1：双判据按名兜底——v98.1 采集池可采出星骸遗鳞时期入包的
    # 历史堆 data.type 被写死为"材料"，仅判 data.type 仍卖不掉（0.8 折 int(0.8)=0）
    if d.get("type") == "收藏" or (_ci.MATERIALS_BY_NAME.get(d.get("name", "")) or {}).get("type") == "收藏":
        rate = 1.0
    price = int(d.get("price", 0) * rate * sell_mult)
    if price <= 0:
        return None
    # v126.2 大鱼卖更贵：鱼获个体属性在 item_data.tags（FIFO），单条实收 = int(base × (0.5 + w/wmax))，
    # 无 tag 的鱼（老数据/非鱼材料）按原价（1.0 系数）；remove_item 扣包时自动同步截断 tags
    _tags = (it["data"].get("tags") or [])[:it["count"]]
    gold = price * it["count"]
    if _tags and isinstance(_tags, list):
        _wmax = fish_weight_max(d)
        # v126.4 拍板项 1：只对 type=鱼 加权（渔获材料回归原价——同材料垂钓所得
        # vs 采集所得售价一致，避免"材料按类型折价"与"个体波动"语义混叠）
        if _wmax and d.get("type") == "鱼":
            # v126.4 审计 P2：t.get("weight", 0) 防损坏 tag 缺键直接 KeyError 崩出售
            gold = sum(int(price * (0.5 + (t.get("weight") or 0) / _wmax)) for t in _tags if isinstance(t, dict))
            gold += (it["count"] - len(_tags)) * price
    # F1 P0-2：原子出售（单事务：校验货存→加金币→扣包），替代原两步独立 commit
    ok = db.sell_item_atomic(group_id, qq_id, it["key"], it["count"], gold)
    return (d["name"], it["count"], gold)


def apprentice_protect_mats(group_id, qq_id) -> dict:
    """v101.25 #305：当前对话树节点（拜师考验）需要的材料名 → 数量。

    玩家正在导师考验节点（apprentice_check 选项）时，批量出售不能误卖这些
    材料——round68 小红实锤：『出售 材料』把铁矿石×7 混卖，挖掘拜师直接卡死。
    返回 {材料名: 需要数量}，无考验返回 {}。
    """
    db = _h('db')  # ← from .. import db  # 惰性导入
    st = db.get_talk_state(group_id, qq_id)
    if not st:
        return {}
    npc_id = st.get("npc", "")
    node_id = st.get("node", "")
    dlg = C.get_dialogue(npc_id)
    if not dlg:
        return {}
    node = C.dialogue_node(dlg, node_id)
    if not isinstance(node, dict):
        return {}
    mats = {}
    for o in (node.get("options") or []):
        ac = (o.get("action") or {}).get("apprentice_check")
        if ac:
            mats[ac.get("item", "")] = int(ac.get("count", 1))
    return mats


# ============ v166 商店限购（店内共享库存 + 每日个人限购） ============

def buy_index_dispatch(key, group_id, qq_id, player, qty, discount, *,
                       shop_items, materials, weapons, equip_items, smith_items,
                       sa_id, area_id, cur, is_smith, evt_tip,
                       limit_guard=None, at_shop=None, smith_stock=None, buy_weapon=None,
                       roll_blueprint=None, uuid=None, add_item=None, update_player=None,
                       generate_roster_equip=None, ec=None):
    """v181.P4-3：buy 序号购买 key 分派（bp:/m:/w:/mount:/e:/s:/消耗品 巨型 if 原样下沉）。

    等价于原 economy.buy 序号分支（L7230 起逐 key 判断 + 原子写 + 文案）——
    成交/拦截文案逐字符等价，分支穷尽终结（每 key 命中即 return）。

    返回 (result, msg)：
      msg 非 None = 拦截/提示文案，调用方 yield 后 return
      msg None    = 命中并完成成交（service 已扣金币并发物品），调用方直接 return
    （result 恒 None，保留双值槽位便于将来返回结构化结算供命令层拼扩展文案）

    注入参数（命令层能力边界 §2.4）：limit_guard=_shop_limit_buy_guard（限购扣减）、
    at_shop=base._at_shop、smith_stock=core.smith_stock（货架原子购买）、
    buy_weapon=命令层 _buy_weapon 转发（等价 service buy_weapon）；其余数据/引擎原子全 C/db。
    """
    try:                                       # 流水埋点（未启用 = 零行为）
        _tlog = _h('tlog_setup')  # ← from .. import tlog_setup as _tlog
        _tlog.emit("shop.buy", actor=qq_id, key=str(key), qty=qty,
                   discount=float(discount or 1))
    except Exception:
        pass
    db = _h('db')  # ← from .. import db  # 惰性导入
    _ss = _h('_ss')  # ← from ..core import smith_stock as _ss  # v135 铁匠铺全服共享货架（注入缺省）
    _ec = ec or _cl.ECON_CONFIG
    _limit_guard = limit_guard or (lambda *a, **k: (True, ""))
    _at_shop = at_shop or (lambda p: False)
    _ss = smith_stock or _ss
    _buy_weapon = buy_weapon or buy_weapon_fn
    _add_item = add_item or db.add_item
    _upd_player = update_player or db.update_player
    _roll_bp = roll_blueprint or C.roll_blueprint
    _gen_eq = generate_roster_equip or C.generate_roster_equip
    _uuid = uuid or __import__("uuid")
    _gold = player["gold"]
    if key == "bp:rand":
        # v94 图纸经济：铁匠铺随机图纸（价格 = 图纸价×3，商队集市 8 折）
        bp_price = int((max(1, player["level"]) * _ec["bp_price_per_lv"]
                        + _ec["bp_price_base"]) * _ec["bp_smith_mult"] * discount)
        # v105 M09 P3-9：图纸单件商品，数量参数不适用（此前 qty 被静默忽略）
        if qty > 1:
            return None, "神秘锻造图纸只能买 1 张！想再买一张就再输一次～"
        if _gold < bp_price:
            return None, f"金币不足！需要 {bp_price} 金币。"
        _upd_player(group_id, qq_id, gold=_gold - bp_price)
        bp = _roll_bp(max(1, player["level"]))
        _add_item(group_id, qq_id, f"eq_{_uuid.uuid4().hex[:8]}", bp)
        return None, f"✅ 你买到一张【{bp['name']}】！{evt_tip}"
    if str(key).startswith("m:"):
        # 锻造材料购买
        mid = str(key)[2:]
        mt = _ci.MATERIALS[mid]
        price = int(mt["price"] * discount)
        total = price * qty
        if _gold < total:
            return None, f"金币不足！需要 {total} 金币。"
        # v166 商店限购：材料限购（店内共享库存+每日个人限购）
        _l_ok, _l_msg = _limit_guard(group_id, qq_id, sa_id, f"mat:{mid}", qty)
        if not _l_ok:
            return None, _l_msg
        _upd_player(group_id, qq_id, gold=_gold - total)
        # v104 修 M09-P3：材料购买全量拷贝定义字段（补 quality 等），不再丢字段
        _add_item(group_id, qq_id, mid, {**mt, "type": "材料", "stackable": True, "price": price}, count=qty)
        qty_str = f" ×{qty}"  # #254: 单件购买也回显数量（此前 qty=1 无回显）
        return None, f"✅ 你购买了【{mt['name']}】{qty_str}！{evt_tip}"
    if str(key).startswith("w:"):
        wname = str(key)[2:]
        wt = next((w for w in weapons if w[0] == wname), None)
        if not wt:
            return None, f"商店里没有『{wname}』！输入『商店』查看商品。"
        wname, wtype, wlv, wq = wt
        price = int(equip_price("weapon", wlv, wq, wtype) * discount)
        # v105 M09 P3-9：武器单件商品（此前『购买 铁剑 3』静默只买 1 把）
        if qty > 1:
            return None, f"『{wname}』是武器，只能单件购买！需要几把就再买几次～"
        if _gold < price:
            return None, f"金币不足！需要 {price} 金币。"
        # v166 商店限购：商店武器（店内共享库存+每日个人限购）
        _l_ok, _l_msg = _limit_guard(group_id, qq_id, sa_id, f"weapon:{wname}", 1)
        if not _l_ok:
            return None, _l_msg
        # 阶段八：武器不锁职业（20 章），名册名走名册精确生成
        _upd_player(group_id, qq_id, gold=_gold - price)
        equip_item = _buy_weapon(wname, wtype, wlv, wq)
        # v21 防刷钱：商店装备卖出价 = 买入价一半（否则属性推导价远高于买入价，可无限倒卖刷钱）
        equip_item["price"] = int(price * _ec["equip_resale_rate"])
        _add_item(group_id, qq_id, f"eq_{_uuid.uuid4().hex[:8]}", equip_item)
        return None, f"✅ 你购买了【{wname}】！放到背包了，输入『装备 {wname}』使用。"
    if str(key).startswith("mount:"):
        # v104 修 M17-P2：序号购买坐骑（老马/小毛驴，与面板序号一致，仅橡木镇可买）
        mdef = _cl.MOUNT_BY_KEY[str(key)[6:]]
        mounts = player.get("mounts") or {}
        if mdef["key"] in (mounts.get("owned") or []):
            return None, f"你已经拥有{mdef['name']}了！"
        # v104 M17 P2-1：购买时同步校验骑乘等级（此前买完骑不了才发现）
        if player["level"] < mdef["lv"]:
            return None, f"『{mdef['name']}』需要 Lv.{mdef['lv']} 才能骑乘，你才 Lv.{player['level']}！先升级再来买吧～"
        price = int(mdef["price"] * discount)
        if _gold < price:
            return None, f"金币不足！{mdef['name']}要 {price} 金币。"
        _upd_player(group_id, qq_id, gold=_gold - price)
        mounts = dict(player.get("mounts") or {})
        owned = list(mounts.get("owned") or [])
        owned.append(mdef["key"])
        mounts["owned"] = owned
        _upd_player(group_id, qq_id, mounts=mounts)
        return None, (f"{mdef['icon']} 你买了{mdef['name']}！缰绳交到你手里，它打了个响鼻。\n"
                      f"💡 『骑乘 {mdef['name']}』骑上它，『坐骑』查看全部！")
    if str(key).startswith("e:"):
        # 名册装备购买（铁匠铺全套装备）
        rid = str(key)[2:]
        r = _ci.EQUIP_ROSTER[rid]
        price = int(equip_price(r["slot"], r["lv"], r["quality"], r.get("weapon_type"), rid) * discount)
        # v105 M09 P3-9：装备单件商品（数量参数不适用）
        if qty > 1:
            return None, f"『{r['name']}』是装备，只能单件购买！需要几件就再买几次～"
        if _gold < price:
            return None, f"金币不足！需要 {price} 金币。"
        # v166 商店限购：名册装备（店内共享库存+每日个人限购）
        _l_ok, _l_msg = _limit_guard(group_id, qq_id, sa_id, f"equip:{rid}", 1)
        if not _l_ok:
            return None, _l_msg
        _upd_player(group_id, qq_id, gold=_gold - price)
        equip_item = _gen_eq(rid)
        # v21 防刷钱：商店装备卖出价 = 买入价一半
        equip_item["price"] = int(price * _ec["equip_resale_rate"])
        _add_item(group_id, qq_id, f"eq_{_uuid.uuid4().hex[:8]}", equip_item)
        return None, f"✅ 你购买了【{r['name']}】！放到背包了，输入『装备 {r['name']}』使用。"
    if str(key).startswith("s:"):
        # v135 铁匠铺货架（全服共享）：先到先得，原子扣减库存
        rid = str(key)[2:]
        town_lv = _ss.town_level(cur)
        ok, item_data, price = _ss.buy_stock_item(cur, town_lv, rid)
        if not ok:
            return None, "😢 这件作品已被别的冒险者买走了，售罄等补货吧～"
        if _gold < price:
            return None, f"金币不足！需要 {price} 金币。"
        _upd_player(group_id, qq_id, gold=_gold - price)
        # v21 防刷钱：货架装备卖出价 = 买入价一半（含浮动）
        item_data["price"] = int(price * _ec["equip_resale_rate"])
        _add_item(group_id, qq_id, f"eq_{_uuid.uuid4().hex[:8]}", item_data)
        return None, f"✅ 你买下了【{item_data['name']}】！铁匠的手艺交到你手里，输入『装备』查看。"
    # else：普通消耗品（iid = key，非冒号前缀 key）
    iid = key
    it = _ci.ITEMS[iid]
    price = int(it["price"] * discount)
    total = price * qty
    if _gold < total:
        return None, f"金币不足！需要 {total} 金币。"
    # v166 商店限购：消耗品（店内共享库存+每日个人限购）
    _l_ok, _l_msg = _limit_guard(group_id, qq_id, sa_id, f"item:{iid}", qty)
    if not _l_ok:
        return None, _l_msg
    _upd_player(group_id, qq_id, gold=_gold - total)
    # v21 防刷钱：消耗品卖出价 = 实际支付价（商队 8 折时不能原价卖出套利）
    # v104 修 M09-P0：全量拷贝 ITEMS 定义字段（hot/hot_turns/hot_mana/food_effect/effect），
    #   否则 9 种店售食物丢 hot 字段 → infer_template 判为药水，战斗内持续恢复失效
    _add_item(group_id, qq_id, iid, {**it, "type": "消耗品", "stackable": True, "price": price}, count=qty)
    qty_str = f" ×{qty}"  # #254: 单件购买也回显数量（此前 qty=1 无回显）
    return None, f"✅ 你购买了【{it['name']}】{qty_str}！{evt_tip}"


def buy_weapon_fn(wname: str, wtype: str, wlv: int, wq: str) -> dict:
    """v181.P4-3：buy_index_dispatch 缺省兜底武器生成（= buy_weapon 同实现）。"""
    return buy_weapon(wname, wtype, wlv, wq)


# ============ v166 商店限购（店内共享库存 + 每日个人限购） ============

def limit_buy_guard(group_id: str, qq_id: str, sa_id: str, key: str, qty: int):
    """商店限购统一拦截（在购买成交前调用，扣库存+记日限）。

    返回 (ok, msg)：
      ok=True  已通过限购检查并完成扣减（可继续扣金币发物品）
      ok=False 被限购拦截，msg 为提示文案（yield 后 return）
    注意：调用方必须保证本次真的成交（后续金币不足时已先于本函数校验，
    或本函数之后仍可能因金币失败——由调用方保证扣款顺序）。
    """
    _sshop = _h('_sshop')  # ← from ..core import shop_stock as _sshop  # v166 商店限购（店内共享库存+每日个人限购）
    ok, reason, can = _sshop.check_and_consume(group_id, qq_id, sa_id, key, qty)
    if not ok:
        return False, reason
    return True, ""


def limit_label(sa_id: str, key: str) -> str:
    """商品面板限购标注（未配置返回 ''）。"""
    _sshop = _h('_sshop')  # ← from ..core import shop_stock as _sshop
    return _sshop.limit_label(sa_id, key)
