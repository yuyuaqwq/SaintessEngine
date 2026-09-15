# -*- coding: utf-8 -*-
"""包内收藏册命令（`content/cmds_collection.py`）—— 『收藏册』的守卫/取参/业务/**渲染**。

终态形状（B18 样板定形；真源 = `overnight/B18_TERMINAL_SHAPE.md` §1.2）：
* handler 签名 `fn(env) -> list[str]`，**直接返回已渲染行**（本命令全 f-string，不涉文案表 →
  字面量随业务一起进包，宿主 `game/commands/collection.py` 里已无任何渲染代码）。
* 取参走引擎 `Env`：`env.arg_text("收藏册")`（= 旧 `self._strip_cmd(event, "收藏册")` 同口径）。

数据口（包内直连・不再靠宿主注入）
----------------------------------
* 背包 / 图鉴读写 = 包内存档层 `content/persistence`（B17 归包；与宿主 `db.*` **同一批函数对象**）；
* 显示名索引 = 包内 `content/index.py::display`（与宿主 `C.display` 同一个函数）；
* 读表与收藏判定 = 包内 `content/collection.py`。

行为逐字节不变（含宝箱入包副作用）；证据 = `overnight/W-B18-样板.md` 的 62 场景快照
（sha256 改前 = 改后）。
"""
from __future__ import annotations

from . import collection as _LIB
from .commands import register
from .index import display as _display
from .persistence import add_item, get_bestiary, get_inventory

_SEP = "━━━━━━━━━━━━"


def _inv_names(group_id, qq_id) -> set:
    """背包持有物品名集合（key 转 display 名）—— 真源 `CollectionCmds._inv_names` 逐行。"""
    names = set()
    try:
        for it in get_inventory(group_id, qq_id):
            nm = (it.get("data") or {}).get("name") or it.get("key")
            if nm:
                names.add(str(nm))
            if it.get("key"):
                names.add(str(it["key"]))
    except Exception:                                        # noqa: BLE001
        pass
    return names


def _bestiary_names(group_id, qq_id) -> set:
    """图鉴击杀怪物名集合（bestiary key → display 名）—— 真源 `_bestiary_names` 逐行。"""
    names = set()
    try:
        for r in get_bestiary("", qq_id):
            nm = _display("monsters", r["monster"])
            names.add(str(nm))
            names.add(str(r["monster"]))
    except Exception:                                        # noqa: BLE001
        pass
    return names


def _progress(group_id, qq_id, book) -> tuple:
    """`(已收集数, 总条目数)` —— 判定归包（`content.collection.book_progress`）。"""
    return _LIB.book_progress(book, _inv_names(group_id, qq_id),
                              _bestiary_names(group_id, qq_id))


def _reward_line(rw: dict) -> str:
    """满套奖励行：宝箱 / 称号 / 永久属性 —— 真源 `_book_detail` 尾部逐行。"""
    rw_txt = []
    if rw.get("chest"):
        rw_txt.append("宝箱×1")
    if rw.get("title"):
        rw_txt.append(f"称号『{rw['title']}』")
    if rw.get("bonus"):
        rw_txt.append("永久属性(%s)" % "、".join(f"{k}+{v}" for k, v in rw["bonus"].items()))
    return "🎁 满套奖励：" + "、".join(rw_txt)


@register("collection", guards=("hook:player",), params=("cmd=收藏册",))
def collection(env) -> list:
    """『收藏册 [套名]』/『收藏册 领取 [套名]』：总览 / 明细 / 满套领奖。"""
    group_id = env.group_id
    qq_id = env.uid
    raw_arg = env.arg_text("收藏册")             # = 旧 `self._strip_cmd(event, "收藏册")`
    books = _LIB.books()                         # 包内表（源列表序）
    if not books:
        return ["📖 收藏册数据缺失，请联系管理～"]
    # 『收藏册 领取』：满套册领宝箱
    if raw_arg.startswith("领取"):
        return _claim(group_id, qq_id, raw_arg, books)
    # 指定册名
    if raw_arg:
        target = next((b for b in books if b["name"] in raw_arg or raw_arg in b["name"]), None)
        if not target:
            return [f"📖 没找到收藏册『{raw_arg}』，试试『收藏册』看全部～"]
        return _detail(group_id, qq_id, target)
    # 总览
    lines = ["📖 【冒险者收藏册】", _SEP]
    for b in books:
        got, total = _progress(group_id, qq_id, b)
        mark = "✅" if got == total else "⬜"
        lines.append(f"{mark} {b['name']}：{got}/{total}(『收藏册 {b['name']}』查看)")
    lines.append("")
    lines.append("💡 收集各册条目，集齐后可『收藏册 领取』领宝箱奖励！")
    return lines


def _detail(group_id, qq_id, book) -> list:
    """单册明细面板 —— 真源 `CollectionCmds._book_detail` 逐行。"""
    inv = _inv_names(group_id, qq_id)
    best = _bestiary_names(group_id, qq_id)
    got, total = _LIB.book_progress(book, inv, best)
    rw = book.get("reward") or {}
    lines = [f"📖 【{book['name']}】{got}/{total}", book.get("desc", ""), _SEP]
    for e in _LIB.entries(book):
        ok = _LIB.entry_collected(e, inv, best)
        mark = "✅" if ok else "⬜"
        nm = e.get("name", "")
        hint = e.get("hint", "")
        lines.append(f"{mark} {nm}（{hint}）" if hint else f"{mark} {nm}")
    if got == total:
        lines.append("🎉 集齐了！可用『收藏册 领取』领奖！")
    if rw.get("chest") or rw.get("title") or rw.get("bonus"):
        lines.append(_reward_line(rw))
    return lines


def _claim(group_id, qq_id, raw_arg, books) -> list:
    """满套领取面板 —— 真源 `CollectionCmds._claim_book_reward` 逐行（含宝箱入包副作用）。"""
    name = raw_arg.replace("领取", "", 1).strip()
    if name:
        books = [b for b in books if b["name"] in name or name in b["name"]]
    if not books:
        return ["📖 没有可领取的收藏册奖励（指定册名或全领）～"]
    lines = []
    for b in books:
        got, total = _progress(group_id, qq_id, b)
        if got < total:
            lines.append(f"⬜ {b['name']} 未集齐({got}/{total})，无法领取")
            continue
        rw = b.get("reward") or {}
        chest = rw.get("chest")
        if chest:
            try:
                idata = _LIB.item_info(chest)     # 包内 items 域（真源 C.ITEMS/C.MATERIALS）
                if idata is None:
                    idata = {"name": chest, "type": "消耗品", "stackable": True, "price": 0}
                add_item(group_id, qq_id, chest, idata, count=1)
                lines.append(f"🎁 {b['name']} 集齐奖励：{idata.get('name', chest)}×1 已入包！")
            except Exception:                            # noqa: BLE001
                lines.append(f"⚠️ {b['name']} 宝箱发放失败，请联系管理")
        else:
            lines.append(f"📖 {b['name']} 已集齐（无宝箱奖励配置）")
    return lines
