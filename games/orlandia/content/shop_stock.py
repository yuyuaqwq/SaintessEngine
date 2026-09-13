# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— shop_stock 核心域实现（B13-L5，2026-09-14）。

真源 = 宿主 `game/core/shop_stock.py`（原 228 行）**逐字搬**：函数体一字未改，只换「宿主取件」：

| 真源写法 | 包内 | 依据 |
|---|---|---|
| `from ..data.shop_limit import SHOP_LIMIT`（`get_limit` 函数内） | 模块级 `SHOP_LIMIT` = 包内域读口 `shop_stock`（`content/data/shop_stock.json`） | 域 = 商品限购配置 35 条；对拍与宿主 `data.shop_limit.SHOP_LIMIT` **逐键相等**，`overnight/w1213_l5_probe.py` P2 |
| `from .. import db`（三个函数内，惰性） | 模块级 `db = _HostMod("db")` | 正文里 `db.get_event_state(...)` 一字未改（抄 `content/world_cmds.py` 的替身形状）；**真源本来就把 db 放在函数体内**，本模块改成模块级惰性代理 = 同一个时机（属性访问时取） |
| —（模块无其它宿主依赖） | — | 时间/随机全部走 stdlib（`time`/`datetime`/`json`），无 DB 之外的双源风险 |

⚠️ 与真源语义完全一致的两点（照抄，不是新行为）：
  · `get_limit` 仍返回 `dict(SHOP_LIMIT.get(key) or {})`（**拷贝**）—— 调用方改返回值不会写脏域表；
  · `_now_ts()` / `_today()` 仍是模块级函数 —— `tests/test_v166_shop_limit.py:97` 用
    `mock.patch.object(SS, "_now_ts", …)` 打补丁，本模块与宿主壳**是同一个模块对象**
    （宿主壳只做模块别名），补丁打在实现本体的模块全局上，语义不变。

宿主侧：`game/core/shop_stock.py` 现在只剩「加载包 + 模块别名」薄壳，见那边头注。
"""
import importlib
import json
import os
import sys
import time
from datetime import date

# ============================================================
# ① 宿主替身口（注入优先 → sys.modules → importlib；**绝不静默空跑**）
#    抄 `content/world_cmds.py` 的同款写法（B9 线2 定的包内标准形状）
# ============================================================
_HOST_PKG = "data.plugins.dragonfall.game"      # 运行时（main.py 的模块路径）
_HOST_PKG_FALLBACK = "game"                     # 测试/工具按 `game.xxx` 直接 import 时
_INJECTED = {}
_MOD = "shop_stock"


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


class _HostMod:
    """宿主模块替身（`db`）——正文里 `db.xxx` 照原样写，属性访问时解析。"""

    def __init__(self, name):
        self._name = name

    def __getattr__(self, attr):
        return getattr(_host_module(self._name), attr)


db = _HostMod("db")

# ============================================================
# ② 包内域读口 —— 商店限购配置（域 `shop_stock`；真源 = `game/data/shop_limit.py:39 SHOP_LIMIT`，
#    导出器 = 游戏仓 `scripts/export_domains/shop_econ.py:derive_shop_stock`）
# ============================================================
_HERE = os.path.dirname(os.path.abspath(__file__))


def _read_domain(domain: str, sub: str = "data"):
    """读包内 `content/<sub>/<domain>.json`（缺文件/坏 JSON → {}，不抛，与 tables.py 同款）。"""
    try:
        with open(os.path.join(_HERE, sub, "%s.json" % domain), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:                            # noqa: BLE001
        return {}


SHOP_LIMIT: dict = _read_domain("shop_stock")


def _now_ts() -> int:
    return int(time.time())

def _today() -> str:
    return date.today().isoformat()

def _load_state(db, key: str):
    raw = db.get_event_state(key)
    if not raw:
        return None
    try:
        st = json.loads(raw)
        return st if isinstance(st, dict) else None
    except (ValueError, TypeError):
        return None

def _save_state(db, key: str, st: dict):
    db.set_event_state(key, json.dumps(st, ensure_ascii=False))

# ================= 配置读取 =================

def get_limit(key: str) -> dict:
    """读商品限购配置（来自包内 `shop_stock` 域 = 真源 `data.shop_limit.SHOP_LIMIT`）。
    key 形如 'item:i_x' / 'mat:mat_x' / 'equip:eq_x' / 'weapon:武器名'。
    未配置 → 返回空 dict（不限购）。"""
    return dict(SHOP_LIMIT.get(key) or {})

def _limit_of(prefix: str, ident: str) -> dict:
    return get_limit(f"{prefix}:{ident}")

# ================= 库存状态（店内共享） =================

def _stock_key(sa_id: str, key: str) -> str:
    """店内共享库存 key：shop_stock_{子区域}_{商品key}（带子区域=各店独立）"""
    return f"shop_stock_{sa_id}_{key}"

def _is_restock_due(st: dict, cfg: dict, now: int) -> bool:
    """判断是否需要补货：restock_hours 到点 / restock_at 每日时刻到点"""
    if not cfg.get("restock_hours") and not cfg.get("restock_at"):
        return False
    last = st.get("last_restock", 0)
    if cfg.get("restock_hours") and now - last >= float(cfg["restock_hours"]) * 3600:
        return True
    ra = cfg.get("restock_at")
    if ra:
        # 每日固定时刻：今天 HH:MM 对应 epoch > last_restock 且 ≤ now
        import datetime
        try:
            hh, mm = ra.split(":")
            today_dt = datetime.datetime.now().replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
            target = int(today_dt.timestamp())
        except (ValueError, OSError):
            return False
        if target > last and target <= now:
            return True
    return False

def stock_state(sa_id: str, key: str, cfg: dict | None = None) -> dict:
    """读该店该商品共享库存状态；惰性初始化/补货后写回。
    返回 {left, max, last_restock}。未配置 stock → left=None（不限量）。"""
    cfg = cfg if cfg is not None else get_limit(key)
    max_stock = cfg.get("stock")
    if max_stock is None:
        return {"left": None, "max": None, "last_restock": _now_ts()}
    skey = _stock_key(sa_id, key)
    now = _now_ts()
    st = _load_state(db, skey)
    if not st:
        st = {"left": int(max_stock), "last_restock": now}
        _save_state(db, skey, st)
        return {"left": int(max_stock), "max": int(max_stock), "last_restock": now}
    left = st.get("left", int(max_stock))
    if _is_restock_due(st, cfg, now):
        left = int(max_stock)
        st = {"left": left, "last_restock": now}
        _save_state(db, skey, st)
    return {"left": left, "max": int(max_stock), "last_restock": st.get("last_restock", now)}

def _consume_shared(db, sa_id: str, key: str, cfg: dict, qty: int) -> bool:
    """原子扣店内共享库存 qty 件（先到先得）。不足返回 False。"""
    max_stock = cfg.get("stock")
    if max_stock is None:
        return True  # 不限量
    skey = _stock_key(sa_id, key)
    now = _now_ts()
    st = _load_state(db, skey) or {"left": int(max_stock), "last_restock": now}
    # 读时补货
    if _is_restock_due(st, cfg, now):
        st = {"left": int(max_stock), "last_restock": now}
    if st.get("left", 0) < qty:
        _save_state(db, skey, st)
        return False
    st["left"] = int(st.get("left", 0)) - qty
    _save_state(db, skey, st)
    return True

# ================= 个人每日限购 =================

def _day_key(group_id: str, qq_id: str, sa_id: str, key: str) -> str:
    """个人每日限购 key：shop_day_{gid}_{qid}_{sa}_{key}"""
    return f"shop_day_{group_id}_{qq_id}_{sa_id}_{key}"

def _day_bought(db, group_id: str, qq_id: str, sa_id: str, key: str) -> int:
    """查个人今日在该店该商品已购件数（跨天自动 0）。"""
    dk = _day_key(group_id, qq_id, sa_id, key)
    st = _load_state(db, dk)
    if not st or st.get("date") != _today():
        return 0
    return int(st.get("bought", 0))

def _bump_day(db, group_id: str, qq_id: str, sa_id: str, key: str, qty: int):
    """个人今日已购件数 +qty（跨天重置）。"""
    dk = _day_key(group_id, qq_id, sa_id, key)
    st = _load_state(db, dk)
    if not st or st.get("date") != _today():
        st = {"date": _today(), "bought": 0}
    st["bought"] = int(st.get("bought", 0)) + qty
    _save_state(db, dk, st)

# ================= 对外主入口 =================

def check_and_consume(group_id: str, qq_id: str, sa_id: str, key: str, qty: int) -> tuple:
    """购买前检查 + 原子扣减（店内共享库存 + 个人日限）。

    参数：
      sa_id  当前子区域（店铺）ID
      key    商品 key（'item:x'/'mat:x'/'equip:x'/'weapon:名'）
      qty    本次想买数量
    返回 (ok, reason, can_qty)：
      ok=True       可买（已扣库存+记日限），reason=''
      ok=False      不可买，reason 中文提示（'售罄'/'今日限购已达上限'等）
      can_qty       当前最多可买件数（qty 超限时的钳制值，供提示；不可买时=0）
    """
    cfg = get_limit(key)
    # 未配置任何限购 → 直接放行
    if not cfg:
        return True, "", qty

    per_day = cfg.get("per_day")
    stock = cfg.get("stock")
    # 计算可买量：min(日限余量, 库存余量, qty)
    day_left = None
    if per_day is not None:
        bought = _day_bought(db, group_id, qq_id, sa_id, key)
        day_left = max(0, int(per_day) - bought)
        if day_left <= 0:
            return False, f"今日限购已达上限（每人每日 {per_day} 件）", 0
    stock_left = None
    if stock is not None:
        st = stock_state(sa_id, key, cfg)
        stock_left = st["left"]
        if stock_left is None:
            stock_left = qty
        if stock_left <= 0:
            return False, "该商品今日已售罄，等补货再来吧～", 0

    # 可买量 = min(day_left, stock_left, qty)
    can = qty
    if day_left is not None:
        can = min(can, day_left)
    if stock_left is not None:
        can = min(can, stock_left)
    if can <= 0:
        return False, "该商品暂时买不了，稍后再试～", 0
    if can < qty:
        # 整批购买语义：不足则不部分成交，给明确提示（与『购买 X 数量』显式报错风格一致）
        if day_left is not None and day_left < qty and (stock_left is None or stock_left >= qty):
            return False, f"今日限购还剩 {day_left} 件额度，明日再来吧～", day_left
        if stock_left is not None and stock_left < qty:
            return False, f"该店库存只剩 {stock_left} 件，等补货后再来多买吧～", stock_left
        return False, "数量超出可购上限，请分批购买～", can

    # 扣共享库存
    if stock is not None:
        if not _consume_shared(db, sa_id, key, cfg, can):
            return False, "手慢了！该商品已被别的冒险者买走，等补货吧～", 0
    # 记个人日限
    if per_day is not None:
        _bump_day(db, group_id, qq_id, sa_id, key, can)
    return True, "", can

# ================= 展示辅助 =================

def limit_label(sa_id: str, key: str) -> str:
    """商品行尾标注（如：『库存 3/5 · 今日限 1』），未配置返回 ''。"""
    cfg = get_limit(key)
    if not cfg:
        return ""
    parts = []
    if cfg.get("stock") is not None:
        try:
            st = stock_state(sa_id, key, cfg)
            left = st["left"] if st["left"] is not None else cfg["stock"]
            parts.append(f"库存 {left}/{cfg['stock']}")
        except Exception:
            parts.append(f"库存 {cfg['stock']}")
    if cfg.get("per_day") is not None:
        parts.append(f"今日限 {cfg['per_day']}")
    return " · ".join(parts) if parts else ""
