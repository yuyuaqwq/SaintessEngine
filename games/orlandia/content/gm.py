# -*- coding: utf-8 -*-
"""《奥兰迪亚·余烬纪年》GM/运营指令（`content/gm.py`）—— B9 线 L6 宿主薄壳化落点

真源（游戏仓 `dragonfall/`，**只读，本批零改动**）：`game/commands/gm.py`（857 行）。

搬了什么（逐字搬真源正文，只动「宿主取件」一类）
------------------------------------------------
    权限判定 gm_auth（真源 `GmCmds._gm_auth`）           ·
    目标解析 resolve_target（`_resolve_target`）         · 物品查找 find_item（`_find_item`）
    地图查找 find_map（`_find_map`）                     · 传送落点 default_subarea（`_default_subarea`）
    停服/开服/状态/广播 maintenance·open_server·status_text·broadcast
    玩家列表 players_text（`gm_players`）                · 玩家详情 query_text（`gm_query`）
    发金币/发物品/发经验/设等级/传送/体力/改名（`gm_give_*`·`gm_set_*`·`gm_teleport`·`gm_stamina`·`gm_rename`）
    GM 白名单 add_gm·del_gm（`gm_加GM`/`gm_删GM` + `_load_wl`/`_save_wl`）
    世界 Boss 伤害倍率 boss_dmg（`gm_伤害`）             · 帮助串 help_text（`gm_帮助`，逐字整段）

**没搬（宿主边界，逐条给理由）**
------------------------------------------------
| 真源 | 为什么不搬 |
|---|---|
| `_gm_auth` 的**调用点**（每条指令开头的 4 行守卫） | 命令层注册/守卫形状，属宿主（`_is_gm`/`_gm_whitelist` 真源在共享的 `commands/base.py`，禁改） |
| `gm_play`（`_run_shortcut` 转发指令） | 走宿主注册表/平台事件回环，非游戏内容 |
| `gm_spy` + `_chunk_text`/`_spy_to_role_cards`/`_spy_to_forward_nodes` | **调试/运维管道**：读 playtest 实录 md、拼 NapCat 合并转发节点、`context.send_message` 投递、写 `.spy_forward_state.json` —— 平台接人层（BRIEF §2.8：调试逻辑不进包） |
| `gm_bind_identity` / `gm_identity_table` | **平台身份**接人层：`event.get_sender_id()` 的 openid ↔ QQ 映射（`commands/_identity.py`），与游戏内容无关 |
| `GM_OWNER_QQ` / `_OWNER_GROUP` / `_PLATFORM_PREFIX` / `_SPY_DIR` | 平台配置常量（同上） |

宿主侧薄壳 = `game/commands/gm.py`：只留「命令注册（`@declared`）+ 取玩家/取参数（`_uid`/
`_strip_cmd`）+ 守卫 + 调包 + `yield event.plain_result(...)` 渲染」，含上面四类接人层。

宿主服务句柄 `host`（= 调用方传入，宿主薄壳 `_host()` 构造）
------------------------------------------------------------
    host.db                 宿主 `game.db`（存储层）
    host.C                  宿主 `game.content` 薄聚合层（ITEMS/MAPS/MAP_BY_ID/display）
    host.player_final_stats 宿主 `game/content_rules/panel.player_final_stats`（`gm_设等级` 重算）
    host.title_bonus        `(group_id, qq_id) -> dict`（宿主 `CommandBase._title_bonus`）

分页器直接用引擎 `saintess_engine.command.page_items`（真源 `self._page_items` 即它的转发壳）。
"""
from __future__ import annotations

import json
import time

from saintess_engine.command import page_items


# ============ 权限 / 目标解析 / 查找（真源 GmCmds 内部方法） ============

def gm_auth(is_gm, whitelist, qq_id):
    """返回 (ok, 错误消息)。白名单命中(库∪env)或 gm_ 测试身份放行。
    v104.1 M24 修复：白名单为空(库∪env 均未配置)时默认拒绝一切 GM 指令，
    不再回退私聊放行——防止任意私聊用户 gm_发金币/gm_设等级/gm_加GM 自举提权。"""
    if is_gm(qq_id):
        return True, ""
    if whitelist():
        return False, "⛔ GM 指令仅限管理员使用～"
    return False, "⛔ GM 未配置：请管理员先在环境变量 GWEN_GM_QQ 中配置 GM QQ～"


def resolve_target(host, raw: str):
    """解析 GM 指令的目标玩家：纯数字 → qq_id；否则先按角色名、再按 qq_id 精确匹配。
    返回 (qq_id, 显示名) 或 (None, 错误消息)。"""
    db = host.db
    raw = (raw or "").strip()
    if not raw:
        return None, "格式：gm_<指令> <QQ号/角色名> ..."
    if raw.isdigit():
        p = db.get_player("", raw)
        if not p:
            return None, f"❌ 没有找到 QQ {raw} 的角色～"
        return raw, p.get("name") or raw
    hit = db.find_player_by_name(raw)
    if hit:
        return hit["qq_id"], hit["name"]
    # 名字查不到 → 回退按 qq_id 精确匹配（测试号/特殊 ID 场景）
    p = db.get_player("", raw)
    if p:
        return raw, p.get("name") or raw
    return None, f"❌ 没有找到叫『{raw}』的玩家～"


def find_item(host, name: str):
    """按名称查找物品定义(材料/消耗品)，返回 (item_key, item_data) 或 None。"""
    C = host.C
    for k, v in C.ITEMS.items():
        if v.get("name") == name:
            return k, dict(v)
    # 模糊包含匹配（唯一时才用）
    hits = [(k, v) for k, v in C.ITEMS.items() if name in (v.get("name") or "")]
    if len(hits) == 1:
        return hits[0][0], dict(hits[0][1])
    return None, None


def find_map(host, name: str):
    """按名称/别名查找地图，返回 map_id 或 None。"""
    C = host.C
    for m in C.MAPS:
        if m.get("name") == name or name in (m.get("alias") or []):
            return m["id"]
    hits = [m for m in C.MAPS if name in (m.get("name") or "")]
    if len(hits) == 1:
        return hits[0]["id"]
    return None


def default_subarea(host, mid: str) -> str:
    """gm_传送落点：优先广场，其次第一个非出口子区域；无子区域 → 空。"""
    C = host.C
    m = C.MAP_BY_ID.get(mid, {})
    subs = m.get("subareas") or []
    for sa in subs:
        if sa.get("type") != "城镇出口" and "广场" in sa.get("name", ""):
            return sa["id"]
    for sa in subs:
        if sa.get("type") != "城镇出口":
            return sa["id"]
    return ""


# ============ 停服 / 开服 / 状态 / 广播 ============

def maintenance(host, raw: str):
    """gm_停服：写停服状态 + 返回 (玩家回执, 全服广播文本)。"""
    db = host.db
    db.set_event_state("server_maintenance", "1")
    db.set_event_state("server_maintenance_msg", raw)
    text = (
        "🔧 服务器已停服！\n" + (f"📢 公告：{raw}\n" if raw else "") +
        "现在只有 GM 可以操作游戏，玩家指令会被拦截～"
    )
    broadcast = (
        "🔧【服务器维护公告】\n服务器已进入维护状态，暂时无法游玩～\n"
        + (f"📢 {raw}\n" if raw else "")
        + "开服后会第一时间广播通知，请耐心等待～"
    )
    return text, broadcast


def open_server(host, was_down: bool):
    """gm_开服：清停服状态 + 返回 (玩家回执, 全服广播文本或 None)。"""
    db = host.db
    db.delete_event_state("server_maintenance")
    db.delete_event_state("server_maintenance_msg")
    text = ("✅ 服务器已开服！所有玩家可以正常游玩啦～"
            if was_down else "ℹ️ 服务器本来就在运行中，无需开服～")
    return text, ("✅【服务器公告】\n维护结束，服务器已开服！欢迎回来冒险～" if was_down else None)


def status_text(host, group_id, down: bool, msg: str, gms) -> str:
    """gm_状态：服务器状态/玩家数/最高等级/GM 名单。"""
    db = host.db
    players = db.all_players(group_id)
    gm_names = []
    for g in sorted(gms):
        p = db.get_player("", g)
        gm_names.append(f"{p.get('name') or g}({g})" if p else g)
    lines = [
        "🖥️ 【服务器状态】",
        f"状态：{'🔧 维护中' if down else '✅ 运行中'}",
        f"公告：{msg}" if msg else None,
        f"玩家数：{len(players)} 人",
        f"最高等级：{players[0]['name']} Lv.{players[0]['level']}" if players else None,
        f"GM 名单：{'、'.join(gm_names) if gm_names else '(未配置，默认拒绝)'}",
    ]
    return "\n".join(x for x in lines if x)


def broadcast(host, raw: str):
    """gm_广播：返回 (玩家回执, 全服广播文本或 None)；空内容 → (格式提示, None)。"""
    db = host.db
    if not raw:
        return "格式：gm_广播 <公告内容>", None
    return f"📢 已广播到全服 {len(db.get_player_groups())} 个群！", f"📢【全服公告】\n{raw}"


# ============ 玩家查询 ============

def players_text(host, group_id, raw: str) -> str:
    """gm_玩家 [关键词] [页码]：玩家列表（每页 10）。"""
    db = host.db
    kw = ""
    page = 1
    for tok in raw.split():
        if tok.isdigit():
            page = int(tok)
        else:
            kw = tok
    players = db.all_players(group_id)
    if kw:
        players = [p for p in players if kw in (p.get("name") or "") or kw in (p.get("qq_id") or "")]
    page_items_list, pages, page = page_items(players, page, per_page=10)
    lines = [f"👥 玩家列表({len(players)}人" + (f"，关键词『{kw}』" if kw else "") + f"，第{page}/{pages}页)："]
    for p in page_items_list:
        lines.append(
            f"Lv.{p.get('level', 1):>3} {p.get('name') or '?'} 金币{p.get('gold', 0)} "
            f"{(host.C.display('classes', p.get('class_name')) if p.get('class_name') else '')} | {p.get('qq_id')}"
        )
    return "\n".join(lines)


def query_text(host, raw: str) -> str:
    """gm_查询 <QQ/名字>：玩家详情。"""
    db, C = host.db, host.C
    tgt, terr = resolve_target(host, raw)
    if not tgt:
        return terr
    p = db.get_player("", tgt)
    if not p:
        return "❌ 目标玩家不存在～"
    cls = C.display("classes", p.get("class_name") or "") if p.get("class_name") else ""
    sub = p.get("cur_subarea") or ""
    loc = (C.MAP_BY_ID.get(p.get("cur_map") or "", {}) or {}).get("name") or p.get("cur_map") or "?"
    if sub:
        cm = C.MAP_BY_ID.get(p.get("cur_map") or "", {})
        for sa in (cm.get("subareas") or []):
            if sa.get("id") == sub:
                loc += f"·{sa.get('name')}"
                break
    lines = [
        f"🔍 【{p.get('name')}】({p.get('qq_id')})",
        f"职业：{cls}｜种族：{p.get('race') or 'human'}｜性别：{p.get('gender') or '-'}",
        f"等级：Lv.{p.get('level', 1)}｜经验：{p.get('exp', 0)}",
        f"金币：{p.get('gold', 0)}｜体力：{p.get('stamina', 0)}/{100 + (p.get('level') or 1) * 2}",
        f"HP：{p.get('hp')}/{p.get('max_hp')}｜MP：{p.get('mp')}/{p.get('max_mp')}",
        f"位置：{loc or '?'}｜转职：T{p.get('class_tier', 0)}",
        f"注册于：{p.get('created_at')}｜最近活跃：{p.get('last_active')}",
    ]
    return "\n".join(lines)


# ============ 玩家操作 ============

def give_gold(host, raw: str) -> str:
    """gm_发金币 <QQ/名字> <数量>"""
    db = host.db
    parts = raw.split()
    if len(parts) < 2:
        return "格式：gm_发金币 <QQ号/角色名> <数量>"
    tgt, terr = resolve_target(host, parts[0])
    if not tgt:
        return terr
    try:
        n = int(parts[1])
    except ValueError:
        return "数量必须是整数！"
    if n < 0:
        return "数量不能为负！"
    p = db.get_player("", tgt)
    db.update_player("", tgt, gold=(p.get("gold") or 0) + n)
    return f"💰 已给 {p.get('name')} 发放 {n} 金币(现在 {p.get('gold', 0) + n})！"


def give_item(host, raw: str) -> str:
    """gm_发物品 <QQ/名字> <物品名> [数量]"""
    db = host.db
    parts = raw.split()
    if len(parts) < 2:
        return "格式：gm_发物品 <QQ号/角色名> <物品名> [数量]"
    tgt, terr = resolve_target(host, parts[0])
    if not tgt:
        return terr
    item_name = parts[1]
    count = 1
    if len(parts) >= 3:
        try:
            count = max(1, int(parts[2]))
        except ValueError:
            return "数量必须是整数！"
    key, data = find_item(host, item_name)
    if not key:
        return f"❌ 找不到物品『{item_name}』(材料/消耗品)，试试更精确的名字～"
    db.add_item("", tgt, key, data, count)
    return f"📦 已给 {db.get_player('', tgt)['name']} 发放 {data['name']} ×{count}！"


def give_exp(host, raw: str) -> str:
    """gm_发经验 <QQ/名字> <经验值>"""
    db = host.db
    parts = raw.split()
    if len(parts) < 2:
        return "格式：gm_发经验 <QQ号/角色名> <经验值>"
    tgt, terr = resolve_target(host, parts[0])
    if not tgt:
        return terr
    try:
        n = int(parts[1])
    except ValueError:
        return "经验值必须是整数！"
    if n < 0:
        return "经验值不能为负！"
    p = db.get_player("", tgt)
    db.update_player("", tgt, exp=(p.get("exp") or 0) + n)
    # 读档惰性升级会在下次 get_player 时结算
    return f"✨ 已给 {p.get('name')} 发放 {n} 经验(下次读档自动结算升级)！"


def set_level(host, raw: str) -> str:
    """gm_设等级 <QQ/名字> <等级>（重算属性回满血；v113.2 QA 修复：补属性点/技能点）"""
    db = host.db
    parts = raw.split()
    if len(parts) < 2:
        return "格式：gm_设等级 <QQ号/角色名> <等级>"
    tgt, terr = resolve_target(host, parts[0])
    if not tgt:
        return terr
    try:
        n = int(parts[1])
    except ValueError:
        return "等级必须是整数！"
    if not 1 <= n <= 99:
        return "等级范围 1－99！"
    p = db.get_player("", tgt)
    try:
        st = host.player_final_stats(
            p["class_name"], n, p.get("equipment", {}), p.get("class_tier", 0),
            p.get("attributes"), p.get("evolve_path", 0), host.title_bonus("", tgt),
            p.get("race"))
    except Exception:
        return "⚠️ 属性重算失败，等级未修改～"
    # v113.2 QA 修复：GM 造号补属性点/技能点（对齐升级链 每级+3属性点/每级+1技能点），
    # 取 max 保留玩家已用/已有点数，避免"等级到了但没点数"的测试污染
    db.update_player("", tgt, level=n, exp=0, max_hp=st["max_hp"], max_mp=st["max_mp"],
                     hp=st["max_hp"], mp=st["max_mp"],
                     attr_pts=max(p.get("attr_pts", 0), (n - 1) * 3),
                     skill_points=max(p.get("skill_points", 0), n - 1))
    return f"⬆️ 已把 {p.get('name')} 设为 Lv.{n}(HP/MP 已按新等级重算回满)！"


def teleport(host, raw: str) -> str:
    """gm_传送 <QQ/名字> <地图名>（v101.28p：落点设默认子区域）"""
    db = host.db
    parts = raw.split()
    if len(parts) < 2:
        return "格式：gm_传送 <QQ号/角色名> <地图名>"
    tgt, terr = resolve_target(host, parts[0])
    if not tgt:
        return terr
    map_name = " ".join(parts[1:])
    mid = find_map(host, map_name)
    if not mid:
        return f"❌ 找不到地图『{map_name}』～"
    # v101.28p：传送落点设默认子区域（优先广场），否则 cur_subarea 空=卡城镇总览无法进子区域
    db.update_player("", tgt, cur_map=mid, cur_subarea=default_subarea(host, mid))
    p = db.get_player("", tgt)
    return f"🌀 已把 {p.get('name')} 传送到【{host.C.MAP_BY_ID[mid]['name']}】！"


def stamina(host, raw: str) -> str:
    """gm_体力 <QQ/名字> [数值]（不填=回满）"""
    db = host.db
    parts = raw.split()
    if not parts:
        return "格式：gm_体力 <QQ号/角色名> [数值](不填=回满)"
    tgt, terr = resolve_target(host, parts[0])
    if not tgt:
        return terr
    p = db.get_player("", tgt)
    mx = 100 + (p.get("level") or 1) * 2
    if len(parts) >= 2:
        try:
            n = int(parts[1])
        except ValueError:
            return "数值必须是整数！"
        n = max(0, min(n, mx))
    else:
        n = mx
    db.update_player("", tgt, stamina=n, stamina_ts=int(time.time()))
    return f"⚡ 已把 {p.get('name')} 的体力设为 {n}/{mx}！"


def rename(host, raw: str) -> str:
    """gm_改名 <QQ/名字> <新名字>"""
    db = host.db
    parts = raw.split()
    if len(parts) < 2:
        return "格式：gm_改名 <QQ号/角色名> <新名字>"
    tgt, terr = resolve_target(host, parts[0])
    if not tgt:
        return terr
    new_name = " ".join(parts[1:]).strip()
    if not new_name or len(new_name) > 12:
        return "新名字 1－12 个字符！"
    p = db.get_player("", tgt)
    db.update_player("", tgt, name=new_name)
    return f"✏️ 已把 {p.get('name')} 改名为『{new_name}』！"


# ============ GM 白名单管理 ============

def load_whitelist(host) -> list:
    """读库内白名单（真源 `_load_wl`）。"""
    try:
        raw = host.db.get_event_state("gm_whitelist")
        return [str(x) for x in json.loads(raw)] if raw else []
    except Exception:
        return []


def save_whitelist(host, wl: list) -> None:
    """写库内白名单（真源 `_save_wl`）。"""
    host.db.set_event_state("gm_whitelist", json.dumps(wl, ensure_ascii=False))


def add_gm(host, raw: str) -> str:
    """gm_加GM <QQ号>"""
    if not raw or not raw.isdigit():
        return "格式：gm_加GM <QQ号>"
    wl = load_whitelist(host)
    if raw not in wl:
        wl.append(raw)
        save_whitelist(host, wl)
    return f"👑 已把 QQ {raw} 添加为 GM！({len(wl)} 人白名单)"


def del_gm(host, raw: str) -> str:
    """gm_删GM <QQ号>"""
    if not raw or not raw.isdigit():
        return "格式：gm_删GM <QQ号>"
    wl = load_whitelist(host)
    if raw in wl:
        wl.remove(raw)
        save_whitelist(host, wl)
    return f"🗑️ 已把 QQ {raw} 移出 GM 名单！({len(wl)} 人白名单)"


# ============ 世界 Boss 伤害倍率 / 帮助 ============

def boss_dmg(host, qq_id, raw: str) -> str:
    """gm_伤害 [倍率]：世界 Boss 伤害倍率（0.1－100）。"""
    db = host.db
    cur = db.get_boss_dmg_mult(qq_id)
    if not raw:
        return f"⚔️ 你当前的世界 Boss 伤害倍率：×{cur}(默认 1)\n『gm_伤害 <倍率>』修改(0.1－100)"
    try:
        m = float(raw)
    except ValueError:
        return "格式：gm_伤害 <倍率>，如 『gm_伤害 10』(10 倍)"
    if not 0.1 <= m <= 100:
        return "范围 0.1－100！"
    m = round(m, 2)
    db.set_event_state(f"boss_dmg_{qq_id}", m)
    return f"⚔️ 世界 Boss 伤害倍率已设为 ×{m}(原 ×{cur})！『讨伐』时生效"


def help_text() -> str:
    """gm_帮助：GM 指令一览（逐字真源整段）。"""
    return (
        "🛠️ 【GM 指令】(运营/调试用，仅管理员)\n"
        "━━━━━━━━━━━━\n"
        "🏮 服务器\n"
        "『gm_停服 [公告]』 停服(玩家无法游玩，自动广播)\n"
        "『gm_开服』 开服(自动广播)\n"
        "『gm_状态』 服务器状态/玩家数/GM 名单\n"
        "『gm_广播 <内容>』 全服公告\n"
        "━━━━━━━━━━━━\n"
        "👥 玩家管理\n"
        "『gm_玩家 [关键词] [页码]』 玩家列表\n"
        "『gm_查询 <QQ/名字>』 玩家详情\n"
        "『gm_发金币 <QQ/名字> <数量>』 发金币\n"
        "『gm_发物品 <QQ/名字> <物品名> [数量]』 发物品(材料/消耗品)\n"
        "『gm_发经验 <QQ/名字> <经验>』 发经验\n"
        "『gm_设等级 <QQ/名字> <等级>』 设等级(重算属性回满血)\n"
        "『gm_传送 <QQ/名字> <地图名>』 传送\n"
        "『gm_体力 <QQ/名字> [数值]』 设体力(默认回满)\n"
        "『gm_改名 <QQ/名字> <新名字>』 改名\n"
        "━━━━━━━━━━━━\n"
        "👑 权限管理\n"
        "『gm_加GM <QQ>』『gm_删GM <QQ>』 管理 GM 白名单\n"
        "━━━━━━━━━━━━\n"
        "🧪 调试\n"
        "『gm_伤害 [倍率]』 世界 Boss 伤害倍率(0.1-100)\n"
        "『gm_play <指令>』 转发指令给引擎(真实链路体验)\n"
        "💡 目标可以是 QQ 号或角色名；白名单存数据库，重启不丢"
    )
