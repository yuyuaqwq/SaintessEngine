# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— **存档层 inventory 域**（B17，2026-09-14）。

真源：宿主 `game/store/inventory.py`（逐字端口：正文一字未改，**只动「取件」**）。
宿主 `game/store/inventory.py` 现在只剩一层**委托薄壳**（`from content.persistence.inventory import *`）。

| 真源写法 | 包内替身 | 为什么 |
|---|---|---|
| `from .connection import _connect, _lock[, atomic]` | `from .handles import ...` | 连接/锁/事务三个句柄由**注入面**给（宿主工厂注入 db_path） |
| `from .. import content as C` | `from .handles import C`（`_HostMod("content")`） | 包内禁 import 宿主（I2）；宿主内容面走既有句柄约定 |
| 函数内 `from ..<宿主模块> import <名>` | `_host_attr("…", "…")` / `_host_attrs(...)` | 同位置、调用时解析（与真源「函数内惰性 import」同刻） |
| `time.time()` | `clock()` | 时钟是四个注入点之一（默认 = stdlib `time.time`，行为零变化） |

**注入面**：`content/persistence/handles.py`（`bind(db_path=…, clock=…, flush_log=…, lock=…)`）；
宿主装配点 = `game/store/store_factory.py`。纯包环境（编辑器）需注入自己的句柄 —— 见 B19/B20 接点。
"""
import json
import time
from .handles import _connect, _lock, atomic, clock
from .handles import C

"""奥兰迪亚·余烬纪年存储层 - inventory

v126.3 存储瘦身 + 个体属性对象包装（鱼鱼拍板形态）：
  - item_data 不再存类属性（name/type/price/stackable），统一读配置（_hydrate 水合补全）
  - 个体属性存 item_data["tags"]（对象包装，未来可在 tags 旁扩展其它个体字段）：
      堆叠个体物（鱼）→ item_data = {"tags": [{"size":..,"weight":..}, ...]}（元素数 <= count）
      装备等单体个体 → item_data = {slot/affixes/enhance/...}（对象，动态生成无配置）
      普通材料/物品 → item_data = {}（类属性读配置）
  - 所有扣 count 路径（remove/sell/仓库/市场/摆摊/赠送）必须同步截断 tags（FIFO），
    不变量：len(tags) 恒 <= count（裸 SQL 路径见 world._storage_* / social._inv_*）
"""

# v126.2 个体属性上限：单物品最多保留 500 条个体标记（防 item_data 膨胀），
# 超出丢最旧（FIFO 语义：先钓的先卖，但囤积量级下截断最旧影响可忽略）
FISH_TAGS_MAX = 500


def _snapshot_one(item_data):
    """v126.4 单件流转快照裁剪：市场/摆摊/仓库/交换 每次流转 1 件，只带 1 条个体
    tags（FIFO 头）。防整堆 tags 快照回流破坏 len(tags)<=count 不变量（审计实测：
    上架 5 条整堆快照 → 买家 count=1 却拿到 5 条 tags，幻影 tags 可被加权出售）。
    无 tags / 非 dict 原样返回。"""
    if isinstance(item_data, dict) and isinstance(item_data.get("tags"), list) \
            and item_data["tags"]:
        out = dict(item_data)
        out["tags"] = item_data["tags"][:1]
        return out
    return item_data

# v126.3 类属性白名单：这些字段不落库（统一读配置），item_data 只存个体属性
_CLASS_FIELDS = {"name", "type", "price", "stackable", "quality"}


def _class_attrs(key):
    """v126.3 类属性统一读配置：返回 {name,type,stackable,price}（读不到回 {}）。

    查链：MATERIALS/ITEMS 按 key 直查 → 显示名反查 MATERIALS_BY_NAME → FISH_POOL 按名。
    """
    c = C.MATERIALS.get(key) or C.ITEMS.get(key)
    if c:
        return {"name": c.get("name", key), "type": c.get("type", "材料"),
                "stackable": c.get("stackable", True), "price": c.get("price", 0),
                "quality": c.get("quality", "white")}
    nm = C.display("materials", key)
    c = C.MATERIALS_BY_NAME.get(nm)
    if c:
        return {"name": c.get("name", nm), "type": c.get("type", "材料"),
                "stackable": c.get("stackable", True), "price": c.get("price", 0),
                "quality": c.get("quality", "white")}
    for f in C.FISH_POOL:
        if f["name"] in (key, nm):
            return {"name": f["name"], "type": f.get("type", "鱼"),
                    "stackable": True, "price": f.get("price", 0),
                    "quality": f.get("quality", "white")}
    return {}


def _slim(item_key, item_data, tag=None):
    """v126.3 存储瘦身：item_data 只存个体属性（类属性不落库）。

    - tag 非 None（堆叠个体物入包，如鱼）→ {"tags": [tag]} 对象包装
    - 已有 tags key（仓库/市场/赠送回流的快照）→ 只保留 {"tags": [...]}（去类属性）
    - 裸数组（防御兼容）→ 包成 {"tags": [...]}
    - 含非类属性字段（装备词条/强化等动态个体）→ 保留对象
    - 纯类属性 → {}（配置命中才瘦身；配置查不到 = 动态/测试物品，保留完整 data）
    """
    if tag is not None:
        if _class_attrs(item_key):
            return {"tags": [tag]}
        # 配置未命中（动态鱼）：保留类属性供水合残留兜底
        out = {k: v for k, v in (item_data or {}).items() if k in _CLASS_FIELDS}
        out["tags"] = [tag]
        return out
    d = item_data or {}
    if isinstance(d, list):
        return {"tags": d}
    if isinstance(d, dict) and d.get("tags") is not None:
        return {"tags": d["tags"]}
    if isinstance(d, dict) and any(k not in _CLASS_FIELDS for k in d):
        return d
    if _class_attrs(item_key):
        return {}
    return d


def _trim_individuals(data, consumed):
    """v126.3 扣 count 后同步截断 tags（FIFO：先扣的先删个体标记）。

    返回新 item_data：
      - 带 tags 的对象 → 截断后剩余；截空移除 tags key（有 count 无个体，按原价兜底）
      - 裸数组（防御）→ 包对象截断
      - 非个体数据 → 原样
    """
    tags = None
    if isinstance(data, dict):
        tags = data.get("tags")
    elif isinstance(data, list):
        tags = data
    if not tags:
        return data
    rest = tags[consumed:]
    if isinstance(data, list):
        return {"tags": rest} if rest else {}
    out = dict(data)
    if rest:
        out["tags"] = rest
    else:
        out.pop("tags", None)
    return out


def _migrate_upgrade_lv(d: dict) -> dict:
    """v172 真等级化存量迁移：旧档装备 upgrade_lv=N → lv += N（补偿到位），随后删除该字段。

    原 v135 upgrade_lv 是倍率层（属性 ×1.00~1.35），v172 起升级 = 装备 lv 真实 +1，
    属性随 equip_stats 重算。玩家已叠的升级层数转成 lv 补差，不沉没。
    迁移只在内存生效；装备下次写回（update_item_data/update_player equipment=）时自然落库。
    """
    try:
        if isinstance(d, dict) and d.get("slot") and d.get("upgrade_lv"):
            _u = int(d.get("upgrade_lv") or 0)
            if _u > 0:
                d["lv"] = int(d.get("lv", 0) or 0) + _u
            d.pop("upgrade_lv", None)
    except Exception:
        pass
    return d


def _hydrate(key, data):
    """v126.3 读取水合：瘦身数据补全类属性（配置 → 残留旧字段 → key 兜底）。

    - 带 tags → {类属性, "tags": 数组}（下游读 data["tags"] 计价/展示无感）
    - dict（装备个体对象/普通物）→ name 缺失时按配置反查补全（保留 v104R3 兜底链）
    """
    if isinstance(data, list):  # 防御：裸数组
        data = {"tags": data}
    if isinstance(data, dict) and data.get("tags") is not None:
        out = _class_attrs(key)
        # v126.4 审计 P2：兜底元组补 quality——配置未命中的动态带 tag 物品
        # （测试/动态鱼）水合后 quality 丢失会退化成无名无品质
        for _k in ("name", "type", "price", "stackable", "quality"):
            if _k not in out and _k in data:
                out[_k] = data[_k]  # 残留兜底（动态/测试物品配置未命中）
        out["tags"] = data["tags"]
        return out
    d = dict(data or {})
    if not d:
        # v126.3 瘦身后 {}（纯类属性已清）→ 全量水合类属性；
        # v126.4 审计 P2：配置也未命中时兜底 name=key（防下游 d["name"] KeyError）
        return _class_attrs(key) or {"name": key, "type": "材料", "stackable": True,
                                     "price": 0, "quality": "white"}
    if not d.get("name"):
        d["name"] = C.display("materials", key)
        if d["name"] == key:
            d["name"] = C.display("items", key)
    return _migrate_upgrade_lv(d)


def _key_to_id(item_key, item_data=None):
    """v46：把「名字型」物品 key 转成稳定 ID（存档只存 ID）。


    规则：
      - 已有前缀 id（eq_/petegg_/mountrein_/rune_/it_/mat_英文/...）原样返回
      - mat_中文名 → mat_拼音；rec_中文名 → rec_拼音；fish_中文名 → fish_拼音
      - 纯中文名（装备/材料/消耗品/图纸）→ 查索引转 ID
    """
    if not item_key:
        return item_key
    # 已是纯 ID（含英文前缀）：mat_lang_pi / eq_xxx / i_treatment_potion 等
    if item_key.startswith(("eq_", "petegg_", "mountrein_", "rune_", "i_", "npc_", "m_")):
        return item_key
    # mat_ / rec_ / fish_ 前缀：后面已是英文拼音（无中文）→ 原样返回
    for pfx in ("mat_", "rec_", "fish_"):
        if item_key.startswith(pfx):
            rest = item_key[len(pfx):]
            if not any("\u4e00" <= ch <= "\u9fff" for ch in rest):
                return item_key
    # mat_ / rec_ / fish_ 前缀 + 中文 → 拼音 id
    for pfx, tbl in (("mat_", "materials"), ("rec_", "recipes"), ("fish_", "fish")):
        if item_key.startswith(pfx):
            cn = item_key[len(pfx):]
            rid = C.resolve(tbl, cn)
            if rid != cn:
                return f"{pfx}{rid}" if not rid.startswith(pfx) else rid
            return f"{pfx}{C.pinyin_id(cn)}"
    # 纯中文名 → 查索引（材料/配方/物品/鱼）
    for tbl in ("materials", "recipes", "items", "fish"):
        rid = C.resolve(tbl, item_key)
        if rid != item_key:
            return rid
    # 兜底：装备/图纸等直接给名字当 key 的，保持原样（外部 data 里有 name）
    return item_key


# ================= v168 冒险手册：曾拥有物品（possessed） =================
# 语义：物品首次进入玩家背包（INSERT 该格）时记一条稳定 key，碰过=拥有，永久不回退。
# 埋点：add_item 与 social._inv_upsert（市场/摆摊接手）在 INSERT 前调用 record_possessed_conn；
#       home_storage 取仓 = 纯中转不埋（物品存仓前必然 add_item 过）。

# 装备实例 uuid 形态：eq_ + 8 位 hex（如 eq_72d48ebe）；原型 id 为 eq_拼音词（如 eq_tie_jian）
_UUID_HEX = set("0123456789abcdef")


def _is_equip_uuid_key(item_key: str) -> bool:
    """判断 item_key 是否为装备实例 uuid（eq_ + 8hex）。"""
    if not item_key or not item_key.startswith("eq_"):
        return False
    rest = item_key[3:]
    return len(rest) == 8 and all(ch in _UUID_HEX for ch in rest)


def _possessed_key(item_key, item_data=None):
    """把入包 key 归一化成图鉴用的稳定『原型 key』；无法识别返回 None（跳过不阻塞）。

    - 材料/消耗品/收藏/符文/宠物蛋/坐骑缰绳（mat_/i_/rune_/petegg_/mountrein_）→ key 即稳定 ID
    - 装备原型 id（eq_拼音词）→ 直接用
    - 装备实例 uuid（eq_+8hex）→ item_data.name 反查 EQUIP_ROSTER；查不到跳过
    - 其他（无前缀自定义 key）→ 有 name 且反查命中装备则记原型，否则跳过
    """
    if not item_key:
        return None
    if not _is_equip_uuid_key(item_key):
        # 非 uuid 形态：非装备前缀稳定直接收；eq_ 原型 id 也直接收
        if item_key.startswith(("mat_", "i_", "rune_", "petegg_", "mountrein_", "eq_", "it_")):
            return item_key
        # 无前缀/其它（如任务道具 uuid）：尝试按 name 反查装备
    # uuid 装备实例 / 其它动态 key：按名字反查装备原型
    try:
        nm = (item_data or {}).get("name") or ""
        if not nm:
            return None
        rev = _EQUIP_NAME_REV.get()
        if rev is None:
            roster = getattr(C, "EQUIP_ROSTER", None) or {}
            rev = {_v.get("name"): _k for _k, _v in roster.items()}
            _EQUIP_NAME_REV.set(rev)
        return rev.get(nm)
    except Exception:
        return None


class _LazyDict:
    """线程安全惰性缓存容器（反查表只在首次需要时构建一次）。"""
    def __init__(self):
        self._v = None
        self._lock = _lock

    def get(self):
        with self._lock:
            return self._v

    def set(self, v):
        with self._lock:
            self._v = v


_EQUIP_NAME_REV = _LazyDict()


def record_possessed_conn(conn, qq_id, item_key, item_data=None, got_at=None):
    """事务连接上记一条曾拥有（INSERT OR IGNORE，幂等；不自己开事务）。

    conn：已开启的事务连接（add_item / social._inv_upsert 的 atomic 事务内调用）。
    装备实例 uuid 会先归一化原型 key；无法识别（非装备/无原型）则静默跳过。
    """
    try:
        k = _possessed_key(item_key, item_data)
        if not k:
            return
        ts = got_at if got_at is not None else int(clock())
        conn.execute(
            "INSERT OR IGNORE INTO possessed (qq_id, item_key, got_at) VALUES (?,?,?)",
            (str(qq_id), k, ts),
        )
    except Exception:
        # 曾拥有记录是附加功能，绝不影响物品入包主流程
        pass


def record_possessed(group_id, qq_id, item_key, item_data=None):
    """独立事务版本（供不持有 conn 的调用方）。"""
    try:
        with atomic() as conn:
            record_possessed_conn(conn, qq_id, item_key, item_data)
    except Exception:
        pass


def get_possessed(qq_id):
    """返回该玩家曾拥有物品 key 集合 {item_key, ...}。"""
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT item_key FROM possessed WHERE qq_id=?", (str(qq_id),)
            ).fetchall()
            return {r["item_key"] for r in rows}
        finally:
            conn.close()


def get_possessed_rows(qq_id):
    """返回 [(item_key, got_at), ...]（按 got_at 升序）。"""
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT item_key, got_at FROM possessed WHERE qq_id=? ORDER BY got_at",
                (str(qq_id),),
            ).fetchall()
            return [(r["item_key"], r["got_at"]) for r in rows]
        finally:
            conn.close()


def count_possessed(qq_id) -> int:
    """曾拥有物品种类计数。"""
    return len(get_possessed(qq_id))

def add_item(group_id, qq_id, item_key, item_data: dict, count=1, tag: dict | None = None):
    """item_key: 唯一键(装备用 uuid 或 材料/消耗品用 id)；v46 自动转 ID 存储

    v126.2 tag：个体属性标记（鱼获重量/大小）——随 count 同生共死（remove/sell 按 FIFO
    截断），count 恒 >= len(tags)。
    v126.3 瘦身：存储时类属性不落库（_slim），个体属性存 item_data["tags"] 对象包装，
    读取时 _hydrate 水合补全类属性。
    """
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0 or count > 9999999:
        # F1 P1-3：数量非法（<=0 / 超大）直接拒绝，防负资产/内存膨胀
        return False
    item_key = _key_to_id(item_key, item_data)
    slim = _slim(item_key, item_data, tag)
    stackable = item_data.get("stackable", True) if isinstance(item_data, dict) else True
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT count, item_data FROM inventory WHERE qq_id=? AND item_key=?",
                (qq_id, item_key),
            ).fetchone()
            if row and stackable:
                if isinstance(slim, dict) and slim.get("tags") is not None:
                    # 堆叠 + 个体数据：合并 tags 数组（上限截断丢最旧）
                    _old = json.loads(row["item_data"])
                    _old_tags = _old.get("tags", []) if isinstance(_old, dict) else (
                        _old if isinstance(_old, list) else [])
                    _new_tags = (_old_tags + slim["tags"])[-FISH_TAGS_MAX:]
                    # v126.4 审计 P2：合并只写 {"tags": ...} 会丢 _slim 为配置未命中
                    # 动态物品保留的类属性兜底 → 保留 slim 的非 tags 字段（正常配置命中时为空）
                    _merged = {k: v for k, v in slim.items() if k != "tags"}
                    _merged["tags"] = _new_tags
                    conn.execute(
                        "UPDATE inventory SET count=count+?, item_data=? WHERE qq_id=? AND item_key=?",
                        (count, json.dumps(_merged, ensure_ascii=False), qq_id, item_key),
                    )
                else:
                    conn.execute(
                        "UPDATE inventory SET count=count+? WHERE qq_id=? AND item_key=?",
                        (count, qq_id, item_key),
                    )
            elif row:
                # v110 审计修复：同 key 已存在且不可堆叠（如重复 uuid 场景）——
                # 原裸 INSERT 撞主键抛 sqlite3.IntegrityError，公共函数应设防，退化累加
                conn.execute(
                    "UPDATE inventory SET count=count+? WHERE qq_id=? AND item_key=?",
                    (count, qq_id, item_key),
                )
            else:
                # v168 冒险手册：物品首次入包（新格 INSERT）→ 记曾拥有（永久）
                record_possessed_conn(conn, qq_id, item_key, item_data)
                conn.execute(
                    "INSERT INTO inventory (qq_id, item_key, item_data, count) VALUES (?,?,?,?)",
                    (qq_id, item_key, json.dumps(slim, ensure_ascii=False), count),
                )
            conn.commit()
        finally:
            conn.close()

def get_inventory(group_id, qq_id):
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT item_key, item_data, count FROM inventory WHERE qq_id=? ORDER BY rowid",
                (qq_id,),
            ).fetchall()
            out = []
            for r in rows:
                # v126.3 水合：瘦身数据补全类属性（配置 → 残留 → key 兜底），
                # 下游读 name/price/tags 与 v126.2 完全一致（v104R3 M11 P2-9 兜底链保留）
                d = _hydrate(r["item_key"], json.loads(r["item_data"]))
                out.append({"key": r["item_key"], "data": d, "count": r["count"]})
            return out
        finally:
            conn.close()

def count_item(group_id, qq_id, name):
    """按物品名称/ID 统计背包中数量(材料类，key 为 mat_名称)"""
    kid = _key_to_id(name)
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT item_key, item_data, count FROM inventory WHERE qq_id=?",
                (qq_id,),
            ).fetchall()
            total = 0
            for r in rows:
                d = _hydrate(r["item_key"], json.loads(r["item_data"]))
                if d.get("name") == name or r["item_key"] == kid:
                    total += r["count"]
            return total
        finally:
            conn.close()

def remove_item(group_id, qq_id, item_key, count=1):
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0 or count > 9999999:
        # F1 P1-3：非法数量直接拒绝（<=0 会误删整堆或增库存；超大 count 有溢出/DoS 面）
        return False
    item_key = _key_to_id(item_key)
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT count, item_data FROM inventory WHERE qq_id=? AND item_key=?",
                (qq_id, item_key),
            ).fetchone()
            if not row:
                return False
            if row["count"] <= count:
                conn.execute(
                    "DELETE FROM inventory WHERE qq_id=? AND item_key=?",
                    (qq_id, item_key),
                )
            else:
                # v126.2/126.3 同步截断个体数组（FIFO：先扣的先删个体标记，count >= len(tags) 恒成立）
                _new = _trim_individuals(json.loads(row["item_data"]), count)
                conn.execute(
                    "UPDATE inventory SET count=count-?, item_data=? WHERE qq_id=? AND item_key=?",
                    (count, json.dumps(_new, ensure_ascii=False), qq_id, item_key),
                )
            conn.commit()
            return True
        finally:
            conn.close()


def update_item_data(group_id, qq_id, item_key, new_data: dict):
    """F1 P0-1：单条原子 UPDATE 覆盖某格 item_data（强化/附魔写回装备用）。

    比 remove_item+add_item 两步非原子替换更安全（后者中途崩会丢格/建重复格），
    且保留原格 count 与 rowid。装备所在格 key 为 uuid（get_inventory 原样返回），
    此处经 _key_to_id 归一化后仍命中同一格——key 语义与 remove/add 一致。
    v126.3 写入前 _slim 瘦身（装备对象原样保留；水合对象自动提取 tags）。
    命中返回 True，否则 False（该格不存在，不做写入）。
    """
    item_key = _key_to_id(item_key, new_data)
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute(
                "UPDATE inventory SET item_data=? WHERE qq_id=? AND item_key=?",
                (json.dumps(_slim(item_key, new_data), ensure_ascii=False), qq_id, item_key),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


def sell_item_atomic(group_id, qq_id, item_key, count, gold_gain):
    """F1 P0-2：原子出售单件（单事务：校验货存→加金币→扣包），替代 _sell_one 的两步独立 commit。

    返回 True 表示扣款发货成功；False 表示该格不存在/不足（命令层已有 rate/价格校验，
    此处仅防护并发 sold-out 造成的重复加钱）。item_key 由命令层按 get_inventory 语义给出。
    """
    item_key = _key_to_id(item_key)
    with atomic() as conn:
        row = conn.execute(
            "SELECT count, item_data FROM inventory WHERE qq_id=? AND item_key=?",
            (qq_id, item_key),
        ).fetchone()
        if not row:
            return False
        if row["count"] <= count:
            conn.execute("DELETE FROM inventory WHERE qq_id=? AND item_key=?", (qq_id, item_key))
        else:
            # v126.2/126.3 同步截断个体数组（FIFO：先卖的先删个体标记）
            _new = _trim_individuals(json.loads(row["item_data"]), count)
            conn.execute(
                "UPDATE inventory SET count=count-?, item_data=? WHERE qq_id=? AND item_key=?",
                (count, json.dumps(_new, ensure_ascii=False), qq_id, item_key),
            )
        conn.execute("UPDATE players SET gold=gold+? WHERE qq_id=?", (gold_gain, qq_id))
    return True

__all__ = [
    "json",
    "time",
    "_connect",
    "_lock",
    "atomic",
    "C",
    "FISH_TAGS_MAX",
    "_snapshot_one",
    "_CLASS_FIELDS",
    "_class_attrs",
    "_slim",
    "_trim_individuals",
    "_migrate_upgrade_lv",
    "_hydrate",
    "_key_to_id",
    "_UUID_HEX",
    "_is_equip_uuid_key",
    "_possessed_key",
    "_LazyDict",
    "_EQUIP_NAME_REV",
    "record_possessed_conn",
    "record_possessed",
    "get_possessed",
    "get_possessed_rows",
    "count_possessed",
    "add_item",
    "get_inventory",
    "count_item",
    "remove_item",
    "update_item_data",
    "sell_item_atomic",
]
