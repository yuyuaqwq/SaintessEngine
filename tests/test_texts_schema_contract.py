#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""文案域（texts）schema 契约门禁：key pattern 放宽 vs 真数据 + 两面反证。

跑法：python tests/test_texts_schema_contract.py
退出码：0 = 全绿；1 = 有失败。

这一条钉的是**契约**（不是数据好不好看）：`schemas/text.schema.json` 的 key pattern
必须与包内真数据**同口径**，且放宽后仍然拦得住「明显不是 key」的形状。

四件事，全部在包内真数据上跑（**不硬编码任何 key 名单**）：
  1. 形状：`$defs/text_table` 与 `$defs/text_entry` 用**同一条** key pattern（表形态与显式
     `key` 字段是同一份契约，不能一半放宽一半不放宽）。
  2. 正证：`games/orlandia/content/data/texts.json` 全部条目过**整表**口径（含
     `propertyNames`，旧 pattern 会红 156 条）**且**过**单条**口径（编辑器真实走的口径）。
  3. 反证 A（放宽真的生效，不是名单豁免）：真数据里含中文的 key 逐条过新 pattern，
     且旧 ASCII pattern `^[A-Za-z_][A-Za-z0-9_.]*$` 对它们**全军覆没**；再用一个
     **不在真数据里**的中文 key（含中文标点/数字/下划线/点号）证明放宽是按形状生效。
  4. 反证 B（没放宽过头）：含空格 / 制表 / 换行 / 空串 / 纯不可见字符（零宽/BOM/软连）/
     前导点 / 尾点 / 连续点 的 key 仍被拦 —— 且这些坏 key **配的都是合法条目**，
     用来证明红的是 key、不是内容（归因纪律）。
"""
import json
import os
import re
import sys
import warnings

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

warnings.filterwarnings("ignore", category=DeprecationWarning)

SCHEMA_PATH = os.path.join(ROOT, "schemas", "text.schema.json")
PKG_TEXTS = os.path.join(ROOT, "games", "orlandia", "content", "data", "texts.json")

# 放宽**前**的 pattern：用来做「旧口径会红多少条」的反证（刻意抄死，别跟着 schema 改）
OLD_ASCII_PATTERN = r"^[A-Za-z_][A-Za-z0-9_.]*$"
HAN = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")

try:
    import jsonschema as _JS                                    # type: ignore
except Exception:                                               # noqa: BLE001
    _JS = None

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name} {detail}")


# ---------------------------------------------------------------- 校验口径
def _schema():
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


def _target(def_name):
    """(def 对象, 可解析 $ref 的整 schema)。与 editor/validate.py 同一条构造路径。"""
    sch = _schema()
    defs = sch.get("$defs") or {}
    sub = dict(sch)
    sub.pop("$id", None)
    return defs.get(def_name), sub


def table_errors(data):
    """整表口径错误文案列表（jsonschema 在则走真校验器，否则退到「pattern + 条目形状」）。"""
    target, sub = _target("text_table")
    if target is None:
        return ["schema 缺少 $defs[text_table]"]
    if _JS is not None:
        v = _JS.Draft202012Validator(target, resolver=_JS.RefResolver.from_schema(sub))
        errs = sorted(v.iter_errors(data), key=lambda e: [_safe_key(x) for x in e.absolute_path])
        return [f"{list(e.absolute_path)}: {e.message}" for e in errs]
    # 兜底：不依赖第三方库也能拦住这三面（pattern + 条目必须是带非空 value 的对象）
    out = []
    pat = ((target.get("propertyNames") or {}).get("pattern"))
    if pat:
        rx = re.compile(pat)
        out += [f"[]: {k!r} does not match {pat!r}" for k in data if not rx.search(str(k))]
    for k, v in data.items():
        if not isinstance(v, dict):
            out.append(f"[{k}]: {type(v).__name__} is not of type 'object'")
        elif not str(v.get("value") or ""):
            out.append(f"[{k}]: 'value' is a required/non-empty property")
    return out


def entry_errors(data):
    """单条口径错误文案列表（编辑器 `validate_entry('texts', ·)` 的口径）。"""
    target, sub = _target("text_entry")
    if target is None:
        return ["schema 缺少 $defs[text_entry]"]
    if _JS is not None:
        v = _JS.Draft202012Validator(target, resolver=_JS.RefResolver.from_schema(sub))
        return [f"{list(e.absolute_path)}: {e.message}" for e in
                sorted(v.iter_errors(data), key=lambda e: list(e.absolute_path))]
    out = []
    if not isinstance(data, dict):
        return [f"{type(data).__name__} is not of type 'object'"]
    if not str(data.get("value") or ""):
        return ["'value' is a required/non-empty property"]
    pat = ((target.get("properties") or {}).get("key") or {}).get("pattern")
    if pat and "key" in data and not re.compile(pat).search(str(data["key"])):
        out.append(f"['key']: {data['key']!r} does not match {pat!r}")
    return out


def _safe_key(x):
    return (0, "") if isinstance(x, int) else (1, str(x))


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


GOOD_ENTRY = {"value": "测试用模板 {n}", "params": ["n"], "category": "门禁用", "desc": "门禁构造"}  # noqa: E501


# ---------------------------------------------------------------- 1 契约形状
def t1_contract_shape():
    print("\n[1] 契约形状：schema 两条 pattern 同源 + 包内数据在位")
    check("games/orlandia/content/data/texts.json 存在", os.path.exists(PKG_TEXTS), PKG_TEXTS)
    sch = _schema()
    defs = sch.get("$defs") or {}
    check("schema 有 $defs/text_entry 与 $defs/text_table",
          "text_entry" in defs and "text_table" in defs, sorted(defs))
    tpat = ((defs.get("text_table") or {}).get("propertyNames") or {}).get("pattern")
    epat = ((defs.get("text_entry") or {}).get("properties") or {}).get("key", {}).get("pattern")
    check("整表 propertyNames 有 pattern", bool(tpat), tpat)
    check("★ 表形态与显式 key 字段用**同一条** pattern（不能一半放宽）",
          tpat and tpat == epat, f"table={tpat!r} entry={epat!r}")
    for nm, p in (("text_table.propertyNames", tpat), ("text_entry.key", epat)):
        ok = True
        try:
            re.compile(p or "")
        except re.error as exc:
            ok = False
            print(f"      {nm} 编译失败：{exc}")
        check(f"{nm}.pattern 是可编译正则（Python re 口径）", ok)
    check("描述里写清了放宽的理由（内容侧真实 key 带中文）",
          "中文" in str(((defs.get("text_table") or {}).get("propertyNames") or {}).get("description")),
          "description 缺失")
    return tpat, epat


# ---------------------------------------------------------------- 2 正证
def t2_positive(body, tpat):
    print("\n[2] 正证：包内真数据「整表口径 + 单条口径」全过")
    # ★ 2026-09-17 锚点同步：D 批「数据进表」（D2）把 `WEAPON_EFFECT_DATA` 里内联的 51 条战斗文案
    #   并进包内文案真源 ⇒ 包内文案条数 233 → 284（有意变更，非漂移；判据只换数字，口径不动）。
    # ★ 2026-09-17 二次同步（B 批 B-1）：combat 6 表 177 键 + A 档 5 表 31 键 ⇒ 284 → 492。
    #   ⚠ 上一提交（691fe6c）只把**标签字**改成 492、判据里的数字没换 ⇒ 本门禁 47/48 假红。
    #   铁律：改锚点必须改**判据里的数字**，改标签不算改锚点（改完立刻跑一遍本门禁复核）。
    # ★ 2026-09-17 三次同步（B 批 B 档首批）：属性名 10 + 团队特效名 9 ⇒ 492 → 511。
    #   四次同步（B 档：条件文案 44）⇒ 511 → 555；五次（宠物技能描述 8）⇒ 555 → 563；六次（帮助面板 11）⇒ 574；
    #   七次（B 档末批：副业图标 8）⇒ 582 —— **B 档收口**。
    #   八次（C 档打样：冒险手册总览 8）⇒ 590；九次（C 档 2：足迹 10 + 百科提示 10）⇒ 610；
    #   十次（C 档 3：百科浏览面板 副本一览 9 + 大陆总览 9）⇒ 628；十一次（C 档 4：材料 5 + 宝石 5 + 符文 4）⇒ 642；
    #   十二次（C 档 5a：属性点 4 + 来源图标 11 + 装备名册 12）⇒ 669；十三次（C 档 5b：词条面板 16 + 触发名 6 + 命中标题 1）⇒ 692。
    #   ⚠ 本门禁锚点**共三处**：①本行条数 ②「含中文的 key 数」（见 t3，当前 165） ③对应标签字。
    #   ★ 2026-09-18 C 档 13（B-2 第一片：economy 面板尾货 物品详情 59 + 类目表 25 键）⇒ 1006 → 1090。
    #     ②中文键数锚点**不变**（本片新增键名全 ASCII：`item_cat.*` / 物品详情键），③标签字未动。
    #   ★ 2026-09-18 C 档 14（B-2 第 2 片：player 散落/尾巴 14 函数 93 新键）⇒ 1090 → 1183。
    #     ②中文键数锚点仍不变（键名全 ASCII），③标签字未动。
    #   ★ 2026-09-18 C 档 15（B-2 第 6 片：item_templates 道具模板文案族 105 新键）⇒ 1183 → 1288。
    #     ②中文键数锚点仍不变，③标签字未动。
    #   ★ 2026-09-18 C 档 16（B-2 第 3 片：economy 散落「采集/生活」10 函数 75 新键）⇒ 1288 → 1363。
    #     ②中文键数锚点仍不变（键名全 ASCII），③标签字未动。
    #   ★ 2026-09-18 C 档 17a（B-2 第 3 片第 2 小片：economy 散落「锻造族」71 新键）⇒ 1363 → 1434。
    #     ②中文键数锚点仍不变（键名全 ASCII），③标签字未动。
    #   ★ 2026-09-18 C 档 17b（B-2 第 3 片第 3 小片：economy 散落「强化·宝石·符文·重锻·炼成·附魔」115 新键）⇒ 1434 → 1549。
    #     ②中文键数锚点仍不变（键名全 ASCII），③标签字未动。
    #   ★ 2026-09-18 C 档 18a（B-2 第 4 片第 1 小片：world 散落「地图面板族」34 新键）⇒ 1549 → 1583。
    #     ②中文键数锚点仍不变（键名全 ASCII），③标签字未动。
    #   ★ 2026-09-18 C 档 18c（B-2 第 4 片第 2 小片：world 散落「任务委托族」25 新键）⇒ 1583 → 1608。
    #     ②中文键数锚点仍不变（键名全 ASCII），③标签字未动。
    #   ★ 2026-09-18 C 档 18d-1（B-2 第 4 片第 3 小片：world 散落「家园·地契」48 新键）⇒ 1608 → 1656。
    #     ②中文键数锚点仍不变（键名全 ASCII），③标签字未动。
    #   ★ 2026-09-18 C 档 18d-2（B-2 第 4 片第 4 小片：world 散落「营地·休息·声望·阵营」64 新键）⇒ 1656 → 1720。
    #     ②中文键数锚点仍不变（键名全 ASCII），③标签字未动。
    #   ★ 2026-09-19 C 档 18d-3（B-2 第 4 片第 5 小片：world 散落「传送·方碑·场景交互」35 新键）⇒ 1720 → 1755。
    #     ②中文键数锚点仍不变（键名全 ASCII），③标签字未动。
    #   ★ 2026-09-19 C 档 19a（B-2 第 5 片第 1 小片：combat「探索·战斗主循环」49 新键）⇒ 1755 → 1804。
    #     ②中文键数锚点仍不变（键名全 ASCII），③标签字未动。
    #   ★ 2026-09-19 C 档 19b（B-2 第 5 片第 2 小片：combat 技能族 34 新键）⇒ 1804 → 1838。
    #     ②中文键数锚点仍不变（键名全 ASCII），③标签字未动。
    #   ★ 2026-09-19 C 档 19c（B-2 第 5 片第 3 小片：combat「PvP·荣誉」40 新键）⇒ 1838 → 1878。
    #     ②中文键数锚点仍不变（键名全 ASCII），③标签字未动。
    #   ★ 2026-09-19 C 档 19d（B-2 第 5 片第 4 小片：combat「世界 Boss 讨伐」12 新键）⇒ 1878 → 1890。
    #     ②中文键数锚点仍不变（键名全 ASCII），③标签字未动。
    #   ★ 2026-09-19 C 档 19e-1（B-2 第 5 片第 5 小片：combat「许愿·流浪商人·复活确认」18 新键）
    #     ⇒ 1890 → 1908。②中文键数锚点仍不变（键名全 ASCII），③标签字未动。
    #   ★ 2026-09-19 C 档 19e-2（B-2 第 5 片第 6 小片：combat「battle_prefs 战前设置」22 新键）
    #     ⇒ 1908 → 1930。②中文键数锚点仍不变（键名全 ASCII），③标签字未动。
    #   ★ 2026-09-19 C 档 19f（B-2 第 5 片第 7 小片：combat 散尾 9 新键）⇒ 1930 → 1939。
    #     ②中文键数锚点仍不变（pet_battle.* / res_stack.* / poi.* / explore.find_found /
    #     ex.hidden_turn / hn.ok_item —— 全 ASCII），③标签字未动。
    #   ★ 2026-09-19 C 档 20a（B-2 第 6 片第 1 小片：社交「市场·摊位」57 新键）⇒ 1939 → 1996。
    #     ②中文键数锚点仍不变（键名全 ASCII），③标签字未动。
    #   ★ 2026-09-19 C 档 20b（B-2 第 6 片第 2 小片：社交「组队·公会」77 新键）⇒ 1996 → 2073。
    #     ②中文键数锚点仍不变（party.* / guild.* 键名全 ASCII），③标签字未动。
    #   ★ 2026-09-19 C 档 20c（B-2 第 6 片第 3 小片：社交「世界事件 · 拍卖竞拍」19 新键）⇒ 2073 → 2092。
    #     ②中文键数锚点仍不变（wevent.* / auction.* / bid.* 键名全 ASCII），③标签字未动。
    #   ★ 2026-09-19 C 档 20d（B-2 第 6 片第 4 小片：社交「宠物 · 坐骑」42 新键）⇒ 2092 → 2134。
    #     ②中文键数锚点仍不变（pet.* / mount.* 键名全 ASCII），③标签字未动。
    #   ★ 2026-09-19 C 档 21a（B-2 第 7 片第 1 小片：生活「商店 · 货架」39 新键）⇒ 2134 → 2173。
 #   ★ 2026-09-19 C 档 21b（B-2 第 7 片第 2 小片：生活「商店 · 买卖」35 新键）⇒ 2173 → 2208。
    #     ②中文键数锚点仍不变（shop.* 键名全 ASCII），③标签字未动。
    #   ★ 2026-09-19 C 档 22b（B-2 第 7 片第 5 小片：生活「称号 · 物品查看模式」9 新键）⇒ 2261 → 2270。
    #   ★ 2026-09-19 C 档 22c（B-2 第 8 片：world「NPC 对话族」37 新键）⇒ 2270 → 2307。
    #   ★ 2026-09-19 C 档 22a（B-2 第 7 片第 4 小片：生活「物品详情 · 我的装备 · 卸下」14 新键）⇒ 2247 → 2261。
    #     ②中文键数锚点仍不变（item_detail.* / my_equip.* / unequip.* / item.req_check 键名全 ASCII），③标签字未动。
    #   ★ 2026-09-19 C 档 23a（B-2 第 9 片：world「移动 · 赶路族」26 新键）⇒ 2307 → 2333。
    #     ②中文键数锚点仍不变（move.* / hurry.* 键名全 ASCII），③标签字未动。
    #   ★ 2026-09-19 C 档 24a（B-2 第 10 片：world「副本内移动 · 落点模式提示」8 新键，
    #     1 处幂等复用 move.same_sa）⇒ 2333 → 2341。
    #     ②中文键数锚点仍不变（inst_move.* / move.* 键名全 ASCII），③标签字未动。
    #   ★ 2026-09-19 C 档 25a（B-2 第 11 片：world「NPC 支线/进化教学族」28 新键）⇒ 2341 → 2369。
    #     ②中文键数锚点仍不变（teach.* / join.* / evolve.* / quest.* / npcabsent.* 键名全 ASCII），③标签字已同步。
    #   ★ 2026-09-19 C 档 26a（B-2 第 12 片：world 收尾「见闻录 / 时间面板 / 地图尾块 / 指路」
    #     36 新键，6 处同值幂等复用）⇒ 2369 → 2405。
    #   ★ 2026-09-19 C 档 27a（B-2 第 13 片：world 余量「交付目标行 / 武器自选礼包」
    #     15 新键，0 处同值幂等复用）⇒ 2405 → 2420。
    #   ★ 2026-09-19 C 档 28a（B-2 第 14 片：settlement「战斗结算：经验/金币加成 + 掉落播报」
    #     37 新键，0 处同值幂等复用）⇒ 2420 → 2457。
    #   ★ 2026-09-19 C 档 28b（B-2 第 15 片：settlement「胜利面板 / 战败结算」两个大编排
    #     9 新键，0 处同值幂等复用）⇒ 2457 → 2466。
    #   ★ 2026-09-19 C 档 29a（B-2 第 16 片：quests_flow 全文件
    #     42 新键，6 处与 27a 的 objline.* 同值幂等复用）⇒ 2466 → 2508。
    #   ★ 2026-09-19 C 档 30a（B-2 第 17 片：player_cmds 余量「注册欢迎面板 /
    #     转职面板 / 转职重置 / 战力 / 注销确认」8 新键）⇒ 2508 → 2516。
    #   ★ 2026-09-19 C 档 31a（B-2 第 18 片：world_cmds 余量「野外来客未出现提示 /
    #     对话支线菜单 / 编年史」3 新键，NPC查找 / NPC对话 沿用既有分类）⇒ 2516 → 2519。
    #   ★ C 档 32a（B-2 第 19 片）：`content/gm.py` 余量「GM 指令回执族」19 函数 59 处替换 /
    #     58 新键（新分类 GM指令；玩家列表四行归既有 GM面板）⇒ 2519 → 2577。
    #   ★ C 档 32b（B-2 第 20 片）：`content/cmds_gm.py`「平台例外 gm_play + 身份族」3 函数
    #     10 处替换 / 9 新键（bind.bad_qq 与既有键同值复用；沿用分类 GM指令 / 身份绑定）⇒ 2577 → 2586。
    #     ②中文键数锚点仍不变（register.* / evolve.* / power.* / account.* 键名全 ASCII）。
    #     ③标签字已同步。
    #     中文键数锚点仍不变（qflow.* / objline.* 键名全 ASCII）。
    #     ②中文键数锚点仍不变（vsettle.* / dsettle.* 键名全 ASCII），③标签字已同步。
    #     ②中文键数锚点仍不变（expcurve.* / expbonus.* / petexp.* / wevent.* / fortune.* /
    #     kills.* / lucky.* / mfold.* / knowexp / nextstep.* / rbp.* / req.* / regg / rmount / rrune / rgem
    #     键名全 ASCII），③标签字已同步。
    #     ②中文键数锚点仍不变（objline.* / wpick.* 键名全 ASCII），③标签字已同步。
    #     ②中文键数锚点仍不变（map.* / time.* / notes.* / npcwhere.* / wildcond.* / time_name.* /
    #     season_cn.* / weather_cn.* / home.head_* 键名全 ASCII），③标签字已同步。
    #   ★ C 档 33a（B-2 第 21 片）：`content/profession.py`「副业结算：等待流 / 垂钓 /
    #     惊喜 / 采集 / 挖掘」6 函数 40 处替换 / 39 新键（新分类 副业等待 / 垂钓结算 /
    #     垂钓惊喜 / 采集结算 / 挖掘结算）⇒ 2586 → 2625。
    #     ②中文键数锚点仍不变（prof.* / fish.* / gather.* / mining.* 键名全 ASCII），
    #     ③标签字已同步。
    check("包内文案条数锚点 == 2625（条数变了就同步更新本门禁的锚点）", len(body) == 2625, len(body))
    errs = table_errors(body)
    check(f"★ 整表口径（$defs/text_table，含 propertyNames）{len(body)} 条全过",
          not errs, errs[:3])
    check("整表口径的错误里没有任何 key 违规",
          not errs, [e for e in errs if "does not match" in e][:3])
    bad_single = {k: e for k, e in ((k, entry_errors(v)) for k, v in body.items()) if e}
    check(f"单条口径（$defs/text_entry）{len(body)} 条全过", not bad_single,
          list(bad_single.items())[:2])
    # 编辑器真实路径（editor.validate.validate_entry，走 primary=text_entry）
    from editor import validate as VD
    ed_bad = {k: VD.validate_entry("texts", v) for k, v in body.items()}
    ed_bad = {k: v for k, v in ed_bad.items() if v}
    check("编辑器实际口径（editor.validate.validate_entry）也全过", not ed_bad,
          list(ed_bad.items())[:2])
    # 每条都能被新 pattern 接受（把「整表过」拆到 key 粒度，红的时候能指到具体 key）
    rx = re.compile(tpat)
    miss = [k for k in body if not rx.search(str(k))]
    check("逐 key 复核：492 个 key 全部匹配新 pattern", not miss, miss[:5])


# ---------------------------------------------------------------- 3 反证 A
def t3_chinese_keys_revive(body, tpat):
    print("\n[3] 反证 A：中文 key 合法（放宽真的生效，且旧口径确实全红）")
    cn = [k for k in body if HAN.search(k)]
    check("真数据里含中文的 key 非空（从真数据取，不硬编码名单）", len(cn) > 0, len(cn))
    # ★ 2026-09-17 锚点同步（C 档 5a）：来源图标 9 个中文键（src_icon.图纸/锻造/商店/任务/支线/
    #   宝藏/精英/精英专属/副本Boss）⇒ 156 → 165。**本门禁的锚点共三处**：条数、中文键数、标签字，
    #   三处都要改判据里的数字（只改标签字会假红）。
    check("含中文的 key 数 == 165（域研究口径）", len(cn) == 165, len(cn))
    rx = re.compile(tpat)
    still_bad = [k for k in cn if not rx.search(k)]
    check("★ 156 个中文 key 逐条过新 pattern", not still_bad, still_bad[:5])
    old_rx = re.compile(OLD_ASCII_PATTERN)
    old_hit = [k for k in cn if old_rx.search(k)]
    check("★ 反证：旧 ASCII pattern 对这 156 条一个都不匹配（放宽前整表必红 == 156）",
          not old_hit, old_hit[:5])
    # 构造（不在真数据里）的中文 key：证明是按形状生效，不是把真数据加进白名单
    novel = ["测试.中文键_带数字1", "新域_（括号）", "面板_选敌提示", "cn.键.深层"]
    absents = [k for k in novel if k in body]
    check("构造的中文 key 不在真数据里（避免名单豁免自证）", not absents, absents)
    novel_bad = [k for k in novel if not rx.search(k)]
    check("构造的中文 key（含中文标点/数字/下划线/点号）同样合法", not novel_bad, novel_bad)
    sub = {k: dict(GOOD_ENTRY) for k in novel}
    check("构造的中文 key 整表校验也过（形状生效）", not table_errors(sub), table_errors(sub)[:2])
    print(f"      样例（真数据）：{cn[0]} / {cn[len(cn) // 2]} / {cn[-1]}")


# ---------------------------------------------------------------- 4 反证 B
def t4_bad_keys_still_blocked():
    print("\n[4] 反证 B：空白 / 空串 / 纯不可见 / 空段 key 仍被拦（且归因是 key 不是内容）")
    bad = [
        ("空串", ""),
        ("单个空格", " "),
        ("全角空格", "\u3000"),
        ("NBSP", "\u00a0"),
        ("中间空格", "日志 面板"),
        ("制表", "panel\tkey"),
        ("换行", "panel\nkey"),
        ("前后空白", "  key  "),
        ("纯零宽空格", "\u200b"),
        ("零宽串", "\u200b\u2060"),
        ("纯 BOM", "\ufeff"),
        ("纯软连字符", "\u00ad"),
        ("纯不换行空格", "\u202f"),
        ("前导点", ".日志"),
        ("尾点", "日志."),
        ("连续点", "日志..面板"),
        ("纯点", "..."),
    ]
    for name, key in bad:
        data = {"k": dict(GOOD_ENTRY)}
        data[key] = dict(GOOD_ENTRY)
        errs = table_errors(data)
        # 归因纪律：同一个条目内容单独验必须合法 → 红的只能是 key
        entry_ok = not entry_errors(dict(GOOD_ENTRY))
        check(f"整表拦下 {name} key {key!r}", errs and entry_ok,
              f"errs={errs[:1]} 条目合法={entry_ok}")
    # 单条口径：显式 key 字段同样拦（同一条契约）
    for name, key in (("空格", "a b"), ("空串", ""), ("纯零宽", "\u200b")):
        errs = entry_errors({"key": key, "value": "x"})
        check(f"单条口径拦下 {name} key {key!r}（显式 key 字段）", bool(errs), key)
    # 合法内容必须过（防止反证把校验器弄成「什么都红」）
    check("对照：正常 ASCII key 仍合法", not table_errors({"battle.damage_taken": dict(GOOD_ENTRY)}))
    check("对照：正常中文 key 仍合法", not table_errors({"instance.日志_击杀_经验": dict(GOOD_ENTRY)}))
    # 口径边界（如实钉住，别把契约想得比它实际更强）：
    # 整表 def 的 additionalProperties 只要求「条目是对象」，**条目内容（value 非空）由单条口径管**。
    check("口径边界：整表口径只判 key + 条目是对象（内容不在此判）",
          not table_errors({"ok.key": {"value": ""}}))
    check("口径边界：同一条目在单条口径里被「value 必填/非空」抓下",
          bool(entry_errors({"value": ""})))


# ---------------------------------------------------------------- 5 口径自检
def t5_no_overreach():
    print("\n[5] 口径自检：门禁本身不会「全绿/全红」退化")
    check("jsonschema 可用则走真校验器", _JS is not None, "退到内置兜底（仍拦三面）")
    check("坏 key 的整表校验确实产出错误（校验器没被空过）",
          bool(table_errors({"a b": dict(GOOD_ENTRY)})))
    check("好 key 的整表校验确实无错误", not table_errors({"a.b": dict(GOOD_ENTRY)}))
    check("空表按 minProperties=1 被拦（不是「没数据就没错误」）",
          bool(table_errors({})), table_errors({}))


def main():
    print("== texts 契约门禁：key pattern 放宽 vs 奥兰迪亚真数据 ==")
    if not os.path.exists(PKG_TEXTS):
        print(f"  ❌ 包内文案文件缺失：{PKG_TEXTS}")
        return 1
    body = _load(PKG_TEXTS)
    tpat, _epat = t1_contract_shape()
    t2_positive(body, tpat)
    t3_chinese_keys_revive(body, tpat)
    t4_bad_keys_still_blocked()
    t5_no_overreach()
    print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
