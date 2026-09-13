# -*- coding: utf-8 -*-
"""包内社交·宠物/坐骑域（`content/social_pet.py`）—— 真源 `game/commands/social.py` 的宠物/坐骑编排。

真源（游戏仓 `qqbot/data/plugins/dragonfall`，**只读**）
--------------------------------------------------------
| 真源 | 本文件搬什么 |
|---|---|
| `game/commands/social.py:672-729 pet_view` | 宠物面板（饱食度衰减结算+持久化 / 品质 / 出处 / 技能 / 亲密度 / 加成行） |
| `game/commands/social.py:751-898 pet_feed` | 喂养全族：无参食物清单 / 批量双格式解析 / 食物白名单 / 单次与批量结算（升级循环） |
| `game/commands/social.py:917-993 mount_cmd` | 骑乘/下马/坐骑面板（拥有校验 / 获取渠道提示 / 等级门槛 / 面板行） |

**未搬**（留在命令层的 IO/渲染壳）：`pet_rename`、`pet_release`（各 5~8 行，纯文案）、
`_tip(...)` 随机提示行、`_strip_cmd` 解析、`yield event.plain_result`。

宿主耦合替身（**只改两类东西**：① 存储层 ② 读表口）
----------------------------------------------------
| 真源写法 | 包内写法 | 说明 |
|---|---|---|
| `from .. import db` + `db.xxx(...)` | 模块级 `db` = 惰性宿主代理 `_HostDB` | 正文 `db.xxx` 一行未改；注入优先 → 已加载宿主模块（**不 import**） |
| `C.PET_POOL` / `C.PET_MAX_LEVEL` / `C.pet_exp_need()` / `C.pet_exp_bonus()` / `C.pct_str()` / `C.pet_skill_label()` / `C.PET_SKILL_UNLOCK_LV` / `C.pet_quality_label()` / `C.ITEMS` / `C.MATERIALS` / `C.MOUNT_BY_KEY` / `C.MOUNT_POOL` | `bind_host(content=C)` 注入的**读表口** `_content()` | 类型/数值表都属宿主内容面（L7 与各数据域），本域不搬 |
| `from ..data.equipment import QUALITY as _Q`（坐骑面板品质色） | `QUALITY()`（`bind_host(quality=C.QUALITY)` 注入） | 同上一条：只搬运不复制 |

返回结构（与真源逐字一致）
--------------------------
`pet_view(qq_id)` → `(lines, has_pet)`：`has_pet=True` 时 lines = 面板主体行（**未含** `_tip` 行，
由命令层补）；`False` 时 lines = `[无宠物文案]`（含图鉴行时是**一条**含 `\n` 的消息）。
`pet_feed(group_id, qq_id, mat_name)` → 待 yield 的**消息 list**（真源每个分支 yield 一条 → 单元素 list）。
`mount_run(group_id, qq_id, player, raw, cmd)` → 同上（面板分支是**一条多行消息**）。

用法::

    from content import social_pet as SP
    SP.bind_host(db, content=C, quality=C.QUALITY)
    lines, has_pet = SP.pet_view(qq_id)
"""
from __future__ import annotations

# ============================================================
# ① 宿主替身口（存储层 / 读表口 / 品质色表）
# ============================================================
_HOST_DB = None
_C = None               # 宿主 content 读表口（C）
_QUALITY = None         # C.QUALITY（装备品质色表，坐骑面板用）

_HOST_PKG = "data.plugins.dragonfall.game"
_HOST_PKG_FALLBACK = "game"


def bind_host(db=None, content=None, quality=None):
    """宿主替身注入（幂等；宿主薄壳在 import 期调用）。"""
    global _HOST_DB, _C, _QUALITY
    if db is not None:
        _HOST_DB = db
    if content is not None:
        _C = content
    if quality is not None:
        _QUALITY = quality


def _resolve_host(mod: str):
    """取宿主子模块：注入优先 → 已加载的宿主模块（`sys.modules`，**不 import**）。"""
    import sys
    for name in (f"{_HOST_PKG}.{mod}", f"{_HOST_PKG_FALLBACK}.{mod}"):
        m = sys.modules.get(name)
        if m is not None:
            return m
    raise RuntimeError(f"social_pet：宿主模块 {mod} 不可用（未 bind_host 且未加载）—— 拒绝静默空跑")


class _HostDB:
    """惰性宿主存储层代理（真源 `from .. import db`）——`db.xxx` 正文不动，属性访问时解析。"""

    def __getattr__(self, name):
        return getattr(_HOST_DB if _HOST_DB is not None else _resolve_host("db"), name)


db = _HostDB()


def _content():
    """宿主内容读表口（真源 `from .. import content as C`）。"""
    return _C if _C is not None else _resolve_host("content")


def QUALITY() -> dict:
    """装备品质色表（真源 `from ..data.equipment import QUALITY`；注入优先）。"""
    if _QUALITY is not None:
        return _QUALITY
    return getattr(_resolve_host("data.equipment"), "QUALITY")


# ============================================================
# ② 宠物面板（真源 `social.py:672-729 pet_view`）
# ============================================================

def pet_view(qq_id):
    """宠物面板行。返回 `(lines, has_pet)`。

    - 无宠物：`lines = [文案]`（含图鉴收集行时是**一条**含 `\\n` 的消息）、`has_pet=False`；
    - 有宠物：`lines` = 面板主体行（未含 `_tip`），且**先落库饱食度衰减**（真源同序）。
    """
    C = _content()
    pet = db.pet_get(qq_id)
    # 饱食度自然衰减（每小时 -1）先结算再展示
    pet = db.pet_decay_satiety(pet)
    if not pet:
        dex = db.pet_dex_get(qq_id)
        dex_line = ""
        if dex:
            names = [next((p["name"] for p in C.PET_POOL if p["key"] == k), k) for k in dex]
            dex_line = f"\n📖 图鉴收集：{'、'.join(names)}"
        return [f"你还没有宠物！打怪有概率掉落宠物蛋，『使用 宠物蛋』孵化～{dex_line}"], False
    pdef = next((p for p in C.PET_POOL if p["key"] == pet["pet_key"]), None)
    icon = pdef["icon"] if pdef else "🐾"
    # 饱食度衰减持久化
    db.pet_update(qq_id, satiety=pet["satiety"], last_sat_time=pet["last_sat_time"])
    sat = pet["satiety"]
    # v104 M17 P2：面板加成按饱食度显示实际值（与战斗实算一致：饱食度=0 减半）
    # v133.2：品质分级加成（pet_exp_bonus），显示去尾零（白宠 0.5%/级 → +0.5%）
    _pb = C.pet_exp_bonus(pet)
    if sat <= 0:
        _pb = _pb / 2
    bonus = C.pct_str(_pb)
    skill_line = ""
    if pdef:
        skill_line = f"\n🎯 技能：{C.pet_skill_label(pet['pet_key'])} (Lv.{int(C.PET_SKILL_UNLOCK_LV)} 解锁)"
    if sat <= 0:
        skill_line = "\n😵 技能失效(饱食度归零)"
    lines = [
        f"{icon} 【宠物 · {pdef['name'] if pdef else pet['name']}】",
        f"━━━━━━━━━━━━",
        f"名字：{pet['name']} | Lv.{pet['level']}/{C.PET_MAX_LEVEL}",
    ]
    # v101.14 品质/出处展示
    if pdef:
        ql = C.pet_quality_label(pet["pet_key"])
        if ql:
            lines.append(f"📖 品质：{ql}")
        if pdef.get("source"):
            lines.append(f"📍 出处：{pdef['source']}")
    if skill_line:
        lines.append(skill_line.lstrip("\n"))
    lines.append(f"❤️ 饱食度：{sat}/100")
    # v104 M17 P3：亲密度展示（bond 原本只写不读）
    bond = pet.get("bond", 0)
    bond_line = f"💕 亲密度：{bond}/100"
    if bond >= 50:
        bond_line += "（羁绊生效：战斗经验 +5%）"
    lines.append(bond_line)
    lines.append(f"✨ 经验加成：+{bonus}%(主人战斗经验)" + ("(饱食度归零，加成减半)" if sat <= 0 else ""))
    lines.append("━━━━━━━━━━━━")
    return lines, True


# ============================================================
# ③ 喂养（真源 `social.py:751-898 pet_feed`）—— 返回待 yield 的消息 list
# ============================================================

def pet_feed(group_id, qq_id, mat_name: str):
    """喂养：无参列食物 / 批量双格式 / 白名单校验 / 结算（含升级循环）。

    真源每个分支 yield 一条 → 本函数**单元素 list**（命令层 `for ln in …: yield`）。
    """
    C = _content()
    pet = db.pet_get(qq_id)
    # 饱食度自然衰减先结算
    pet = db.pet_decay_satiety(pet)
    if not pet:
        return ["你还没有宠物！打怪有概率掉落宠物蛋，『使用 宠物蛋』孵化～"]
    db.pet_update(qq_id, satiety=pet["satiety"], last_sat_time=pet["last_sat_time"])
    if not mat_name:
        # #117 喂养列表看不见：无参『喂养』列出背包可喂食物（名+数量+序号），照抄即可喂
        def _is_feed_food(it):
            d = it["data"]
            if d.get("food") or d.get("type") == "鱼":
                return True
            cfg = C.ITEMS.get(it["key"]) or C.MATERIALS.get(it["key"]) or {}
            return bool(cfg.get("food"))

        _foods = [it for it in db.get_inventory(group_id, qq_id) if _is_feed_food(it)]
        if _foods:
            _food_lines = "、".join(
                f"{i}.{it['data'].get('name', it['key'])}×{it.get('count', 1)}"
                for i, it in enumerate(_foods, 1)
            )
            return [
                f"🍖 『喂养 <食物名/序号>』喂宠物（饱食度 +30 / 亲密度 +5 / 经验 +10）\n"
                f"背包可喂食物：{_food_lines}\n"
                f"例：『喂养 1』或『喂养 {_foods[0]['data'].get('name', '')}』"
                "(打怪/采集/垂钓可获得食物)"
            ]
        return [
            "格式：喂养 <食物名/序号>，如『喂养 烤鸟肉』或『喂养 1』\n"
            "背包里还没有可喂食的食物——打怪、『采集』、『垂钓』可获得食物，"
            "『烹饪』能做更顶饱的料理！"
        ]
    # v130.7 意见#21：批量喂养『喂养 <名>*<数量>』/『喂养 <名> <数量>』双格式
    # （对齐 v130.4『使用』批量解析）；名字后带数量时名字按子串/序号匹配
    qty = 1
    _qty_raw = None

    def _is_qty_token(tok: str) -> bool:
        return tok.isdecimal() or (tok.startswith("-") and len(tok) > 1 and tok[1:].isdecimal())

    _it_parts = mat_name.split()
    if len(_it_parts) >= 2 and _is_qty_token(_it_parts[-1]):
        _qty_raw = _it_parts[-1]
        mat_name = " ".join(_it_parts[:-1])
    elif "*" in mat_name:
        _head, _, _tail = mat_name.rpartition("*")
        _tail = _tail.strip()
        if _is_qty_token(_tail):
            _qty_raw = _tail
            mat_name = _head.strip()
        else:
            return ["数量格式不对！例：『喂养 银鳞鱼*5』或『喂养 银鳞鱼 5』～"]
    if _qty_raw is not None:
        try:
            qty = int(_qty_raw)
        except ValueError:
            return ["数量不合法！请输入正整数，如『喂养 银鳞鱼 5』～"]
        if qty < 1:
            return ["数量至少 1 个！大批量喂养用『喂养 <食物> 数量』或『喂养 <食物>*数量』～"]
    # v130.7 意见#22：喂养只能吃食物——白名单 = 带 food 标记的食物 + 鱼（原"材料/鱼中非食物"已剔除）
    items = db.get_inventory(group_id, qq_id)
    FOOD_TYPES = {"鱼"}

    def _is_feed_food(it):
        d = it["data"]
        if d.get("food") or d.get("type") in FOOD_TYPES:
            return True
        # v126.3 瘦身存储水合只带类字段，food 标记按 key 回查配置表（材料/消耗品同一判定）
        cfg = C.ITEMS.get(it["key"]) or C.MATERIALS.get(it["key"]) or {}
        return bool(cfg.get("food"))

    target = None
    if mat_name.isdigit():
        mats = [it for it in items if _is_feed_food(it)]
        idx = int(mat_name)
        if idx < 1 or idx > len(mats):
            return [f"背包里没有第 {idx} 个食物(共 {len(mats)} 个)！打怪、『采集』、『垂钓』可获得食物。"]
        target = mats[idx - 1]
    else:
        for it in items:
            d = it["data"]
            if _is_feed_food(it) and mat_name in d["name"]:
                target = it
                break
    if not target:
        return [f"背包里没有可喂食的食物『{mat_name}』！打怪、『采集』、『垂钓』可获得食物。"]
    # v130.7 意见#21：批量喂养（对齐 v130.4『使用』批量模板）——
    # 数量超持有显式报错不扣物；循环每次扣 1 + 喂 1 次（饱食度 +30 上限 100、
    # 亲密度 +5 封顶 100、经验 +10），饱食度到 100 自动停，超上限部分不扣物品
    if qty > 1:
        if qty > target.get("count", 1):
            return [f"最多喂养 {target.get('count', 1)} 个『{target['data']['name']}』！"]
        fed = 0
        _lv0 = pet["level"]
        _lv_end = _lv0
        for _k in range(qty):
            if pet["satiety"] >= 100:
                break
            db.remove_item(group_id, qq_id, target["key"])
            _sat = min(100, pet["satiety"] + 30)
            # v105 M17 P3-6：亲密度封顶 100（面板显示 x/100，此前 99→104 显示 104/100）
            _bond = min(100, pet["bond"] + 5)
            _exp = pet["exp"] + 10
            _lv = pet["level"]
            while _lv < C.PET_MAX_LEVEL and _exp >= C.pet_exp_need(_lv):
                _exp -= C.pet_exp_need(_lv)
                _lv += 1
            if _lv >= C.PET_MAX_LEVEL:
                _exp = min(_exp, C.pet_exp_need(C.PET_MAX_LEVEL) - 1)
            db.pet_update(qq_id, satiety=_sat, bond=_bond, exp=_exp, level=_lv)
            pet = {**pet, "satiety": _sat, "bond": _bond, "exp": _exp, "level": _lv}
            _lv_end = _lv
            fed += 1
        _lv_s = f"\n🎉 宠物升级到 Lv.{_lv_end}！" if _lv_end > _lv0 else ""
        _full_s = "（饱食度已满）" if fed < qty and pet["satiety"] >= 100 else ""
        return [
            f"🍖 你喂了【{pet['name']}】{fed} 份{target['data']['name']}！\n"
            f"✅ 已喂食 {fed}/{qty} 份{_full_s}{_lv_s}"
        ]
    # 喂食：饱食度 +30（24 章四），亲密度 +5，经验 +10
    db.remove_item(group_id, qq_id, target["key"])
    sat = min(100, pet["satiety"] + 30)
    # v105 M17 P3-6：亲密度封顶 100（面板显示 x/100，此前 99→104 显示 104/100）
    bond = min(100, pet["bond"] + 5)
    exp = pet["exp"] + 10
    lv = pet["level"]
    while lv < C.PET_MAX_LEVEL and exp >= C.pet_exp_need(lv):
        exp -= C.pet_exp_need(lv)
        lv += 1
    if lv >= C.PET_MAX_LEVEL:
        exp = min(exp, C.pet_exp_need(C.PET_MAX_LEVEL) - 1)
    db.pet_update(qq_id, satiety=sat, bond=bond, exp=exp, level=lv)
    lv_str = f"\n🎉 宠物升级到 Lv.{lv}！" if lv > pet["level"] else ""
    return [f"🍖 你喂了【{pet['name']}】一份{target['data']['name']}！\n😋 饱食度 +30 ｜ 💕 亲密度 +5 ｜ ✨ 经验 +10{lv_str}"]


# ============================================================
# ④ 坐骑（真源 `social.py:917-993 mount_cmd`）—— 返回待 yield 的消息 list
# ============================================================

def mount_run(group_id, qq_id, player, raw: str, msg: str, cmd: str, tip_fn):
    """骑乘 / 下马 / 坐骑面板。返回待 yield 的**消息 list**（真源每个分支 yield 一条）。

    三个 I/O 读数与一个提示壳由命令层给（本域不碰事件对象）：
      · `raw` = `self._strip_cmd(event, "骑乘")`（仅当消息以 骑乘/[At: 开头时非空）
      · `msg` = `event.get_message_str()`（**未 strip** —— 真源的 `startswith` 判据就是它）
      · `cmd` = `event.get_message_str().strip()`（下马前缀判据）
      · `tip_fn` = `self._tip("mount")` 的**惰性**壳（`lambda: self._tip("mount")`）——
        面板「有坐骑」分支才调用它。惰性是硬要求：真源也只在该分支取随机提示，
        提前调用会多消耗一次 `random` 抽签（提示池随机序列错位）。
    """
    C = _content()
    # 下马
    if cmd.startswith("下马") or raw.startswith("下马"):
        mounts = player.get("mounts") or {}
        if mounts.get("active"):
            mounts["active"] = None
            db.update_player(group_id, qq_id, mounts=mounts)
            return ["🛑 你翻身下马，坐骑回到了马厩。"]
        return ["你现在没有骑乘任何坐骑～"]
    # 骑乘/购买（带参数）
    if msg.startswith(("骑乘", "[At:")) or raw:
        name = (raw or "").strip()
        mounts = player.get("mounts") or {}
        owned = mounts.get("owned") or []
        # 骑乘
        if name:
            target = None
            for mk in owned:
                m = C.MOUNT_BY_KEY.get(mk)
                if m and name in (m["name"], mk):
                    target = m
                    break
            if not target:
                # 未拥有的坐骑 → 提示
                for m in C.MOUNT_POOL:
                    if name in (m["name"], m["key"]):
                        # v105 M17 P3-4：提示按真实渠道（商店直购/desc 括号渠道），
                        # 此前驼马/驯鹿/独角兽等生活渠道坐骑也提示打精英/Boss，误导玩家
                        if (m.get("price") or 0) > 0:
                            _tip = f"去商店『购买 {m['name']}』"
                        else:
                            _d = m.get("desc", "")
                            _ch = _d[_d.rindex("(") + 1:] if "(" in _d else ""
                            if "『" in _ch:
                                _ch = _ch.split("『")[0]
                            _tip = f"{_ch or '打精英/Boss 掉缰绳'}后用『使用 缰绳』解锁"
                        return [f"你还没有『{m['name']}』！{_tip}～"]
                return [f"没有叫『{name}』的坐骑～『坐骑』查看全部"]
            if player["level"] < target["lv"]:
                return [f"『{target['name']}』需要 Lv.{target['lv']} 才能骑乘，你才 Lv.{player['level']}！"]
            mounts["active"] = target["key"]
            db.update_player(group_id, qq_id, mounts=mounts)
            return [f"{target['icon']} 你骑上了【{target['name']}】！{target['desc']}"]
    # 坐骑面板
    mounts = player.get("mounts") or {}
    owned = mounts.get("owned") or []
    active = mounts.get("active")
    _Q = QUALITY()

    def _q_label(m):
        q = _Q.get(m.get("quality", "white"), {})
        return f"{q.get('color', '⚪')}{q.get('name', '普通')}"

    lines = ["🐾 【坐骑】", "━━━━━━━━━━━━"]
    if not owned:
        lines.append("你还没有坐骑。去橡木镇商店『购买 老马』，或者打精英/Boss 碰碰运气！")
    for mk in owned:
        m = C.MOUNT_BY_KEY.get(mk)
        if not m:
            continue
        mark = " 🟢 骑乘中" if active == mk else ""
        lines.append(f"{_q_label(m)} {m['icon']} {m['name']}{mark} — {m['desc']}")
    if owned:
        lines.append("")
        lines.append(tip_fn())
    else:
        lines.append("")
        lines.append("💡 可获得的坐骑：" + "、".join(f"{_q_label(m)}{m['name']}" for m in C.MOUNT_POOL))
    return ["\n".join(lines)]
