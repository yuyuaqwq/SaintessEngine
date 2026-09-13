# -*- coding: utf-8 -*-
"""包内收藏册域门面（`content/collection.py`）—— 冒险者收藏册的**唯一读表口 + 收藏判定**。

服务对象：宿主命令 `game/commands/collection.py`（B8.2 薄壳化：命令只留
「注册 / 解析参数 / 取玩家 / 调包 / 拼文案」；读表与内容逻辑归包）。

数据（包内，自包含；真源 = 游戏仓，单向导出 = `scripts/export_domains/collection_exploration.py`）
---------------------------------------------------------------------------------------------------
    content/data/collection_books.json   ← 游戏仓 `game/data/collection_book.py:20 COLLECTION_BOOKS`
                                           5 套 / 42 条目；导出形状 = **表**（键 = 册 id）+ 注入 `order`
    content/data/items.json              ← 游戏仓 `game/data/items.py ITEMS`（900 条，含 MATERIALS
                                           全部键）—— 满套宝箱的**物品定义**（只按 key 取，不展开引用）

形状
----
    {book_id: {id, name, desc, entries: [{key, name, hint}], reward: {chest, title, bonus}, order}}
    `order` = 源**列表**下标（导出期注入）：总览逐册渲染按它排（JSON 表按键落盘会丢列表序，
    实测源序与键字典序不同 —— 见导出插件文件头 ①）。

判定（语义逐字取自游戏仓 `game/commands/collection.py:_book_progress`，2026-09-13）
----------------------------------------------------------------------------------
    一条 `entry` 算「已收集」当且仅当它的 `key` 或 `name` 命中**背包持有名集合**或**图鉴怪名集合**。
    这两个集合由**调用方**给（宿主读 db + 显示名索引）—— 本模块不读玩家 DB（与 `content/bridge.py`
    同款替身接口：包内不认宿主存储，只认普通集合）。

不改形状：不补默认值、不改类型、不展开 `key` 里的引用串（`mat_*` / `i_*` 一律留原文，
闭合由消费端查 items 域 / 宿主索引）。
"""
from __future__ import annotations

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))          # <pkg>/content
_DATA_DIR = os.path.join(_HERE, "data")


def _read_json(path: str, default):
    """读一个 JSON 文件（缺文件 / 坏 JSON / 权限 → default，不抛 —— 与 `content/tables.py` 同款）。"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                        # noqa: BLE001
        return default


# ============================================================
# ① 收藏册表（content/data/collection_books.json）
# ============================================================
_BOOK_TABLE = _read_json(os.path.join(_DATA_DIR, "collection_books.json"), {})

# 按源列表序（`order`）还原：总览/领取的遍历序 = 源 `COLLECTION_BOOKS` 的列表序。
_BOOKS = sorted((b for b in (_BOOK_TABLE or {}).values() if isinstance(b, dict)),
                key=lambda b: b.get("order", 0))


def books() -> list:
    """全部收藏册（**源列表序**）；读不到表 → 空列表（宿主据此走「数据缺失」分支）。"""
    return list(_BOOKS)


def entries(book) -> list:
    """一册的条目列表（缺失/非法 → 空列表）。"""
    e = (book or {}).get("entries")
    return list(e) if isinstance(e, (list, tuple)) else []


def entry_collected(entry, inv_names, best_names) -> bool:
    """一条收藏条目是否已收集（`key`/`name` 任一命中背包名或图鉴怪名）。"""
    k = (entry or {}).get("key", "") or ""
    nm = (entry or {}).get("name", "") or ""
    return bool(k in inv_names or nm in inv_names or k in best_names or nm in best_names)


def book_progress(book, inv_names, best_names) -> tuple:
    """返回 `(已收集数, 总条目数)` —— 判定口径见本文件头。"""
    rows = entries(book)
    got = sum(1 for e in rows if entry_collected(e, inv_names, best_names))
    return got, len(rows)


# ============================================================
# ② 物品定义（content/data/items.json；只读 key，惰性加载）
# ============================================================
_ITEMS = None


def _items() -> dict:
    """包内 items 域（`content/data/items.json`）—— 惰性加载（900 条，没用到就不读）。"""
    global _ITEMS
    if _ITEMS is None:
        _ITEMS = _read_json(os.path.join(_DATA_DIR, "items.json"), {}) or {}
    return _ITEMS


def item_info(key: str):
    """按 key 取物品定义；查不到 → `None`（调用方给兜底，不在这里编数据）。

    消费端语义：真源 `game/commands/collection.py` 满套宝箱写的是
    `C.ITEMS.get(chest) or C.MATERIALS.get(chest)` —— items 域 = `ITEMS` 全量
    （`ITEMS = MATERIALS ∪ CONSUMABLES ∪ …`，MATERIALS 键 100% 在其中），
    故一次查 items 域与真源两次查**逐一等价**（导出器 `derive_items` 的 docstring 已证）。
    """
    return _items().get(key)
