# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— auction 服务域实现（B12 线 L5，2026-09-14）。

真源：游戏仓 `game/services/auction.py`（103 行，v181 P4-5 拍卖状态机服务层收敛点）。
本模块 = 那个模块的**逐字端口**（正文从 `# 拍卖到期结算` 起一字未改）；宿主
`game/services/auction.py` 现在只剩：加载包 + 注入宿主替身 + 一行转发 re-export。

消费者（零改动）：`game/commands/social.py:19`（模块级 `settle_expired_auction`）/
`:862`（惰性 `settle_auction`）· `game/services/__init__.py:37`（3 个名字）·
`tests/test_services_auction.py`。

正文改动面（**只有一类**，可复算见 `overnight/w1213_b12l5_gen.py`）
------------------------------------------------------------------
函数体内 `from .. import db` / `from .. import content as C`（共 4 行）**删行** ——
替身改由模块级 `db = _HostMod("db")` / `C = _HostMod("content")` 承担（属性访问时解析，
时机与真源「函数体内惰性 import」等价）。**其余一字未改**（含注释与文案字面量）。

宿主替身口（注入优先；宿主薄壳 `bind_host(db=…, content=…)`）
-------------------------------------------------------------
| 真源写法 | 包内替身 |
|---|---|
| 函数内 `from .. import db`（3 处） | 模块级 `db = _HostMod("db")` |
| 函数内 `from .. import content as C`（1 处） | 模块级 `C = _HostMod("content")` |

⚠️ 缺口（报告同步登记）：`C.generate_equip`（装备生成器，宿主 `game/core/drops.py`）**无同名域**
→ 按 BRIEF §5 判断口径走宿主句柄 + 缺口登记；B14 切读点/裁缺口时统一处置。本线**不建第二份**。
"""
from __future__ import annotations

import importlib
import sys

import time
import uuid as _uuid


# ============================================================
# ① 宿主替身口（注入优先 → sys.modules → importlib；**绝不静默空跑**）
#    形状照抄包内参考实现 `content/world_cmds.py`（B9 线2 产物）
# ============================================================
_HOST_PKG = "data.plugins.dragonfall.game"      # 运行时（main.py 的模块路径）
_HOST_PKG_FALLBACK = "game"                     # 测试/工具按 `game.xxx` 直接 import 时
_INJECTED = {}


def bind_host(**objs):
    """宿主薄壳 import 期注入（幂等）——键 = `_HostMod` 的模块名（`content` / `db`）。"""
    for k, v in (objs or {}).items():
        if v is not None:
            _INJECTED[k] = v


def _host_module(name: str):
    """取宿主子模块（`name` 为空 = 宿主 `game` 包本身，真源 `from .. import X` 那一类）。"""
    if name in _INJECTED:
        return _INJECTED[name]
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        full = prefix if not name else "%s.%s" % (prefix, name)
        m = sys.modules.get(full)
        if m is not None:
            return m
    last = None
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        try:
            return importlib.import_module(prefix if not name else "%s.%s" % (prefix, name))
        except Exception as exc:                # noqa: BLE001
            last = exc
    raise RuntimeError("%s：宿主模块 %s 取不到（%s）——拒绝静默空跑" % (__name__, name, last))


def _host_attr(mod: str, attr: str):
    """宿主模块属性 —— 真源「函数内 `from ..<mod> import <attr>`」的同义替身（调用时解析）。"""
    m = _host_module(mod)
    try:
        return getattr(m, attr)
    except AttributeError:
        for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
            try:
                return importlib.import_module("%s.%s" % (
                    prefix if not mod else "%s.%s" % (prefix, mod), attr))
            except Exception:                   # noqa: BLE001
                continue
        raise


class _HostMod:
    """宿主模块替身（`C` / `db`）——`C.xxx` / `db.xxx` 正文一字未改，属性访问时解析。"""

    def __init__(self, name):
        self._name = name

    def __getattr__(self, attr):
        return getattr(_host_module(self._name), attr)



C = _HostMod("content")     # 真源 函数内 `from .. import content as C`
db = _HostMod("db")         # 真源 函数内 `from .. import db`


# ============================================================
# 拍卖到期结算（原 social._settle_auction，逐行等价搬移）
# ============================================================

def settle_auction(cur, group_id: str) -> str:
    """拍卖到期结算：最高价者得物品，其余退还。返回结算文本"""
    if not cur or cur["etype"] != "auction":
        return "拍卖行已关闭。"
    items = cur["data"].get("items", [])
    lines = []
    for it in items:
        if it["bids"]:
            top_qq = max(it["bids"], key=it["bids"].get)
            amount = it["bids"][top_qq]
            # 发放装备（v48：品质档英文 ID；key 用唯一 id 而非装备名）
            # v104 P1：直接发放初始化时存好的完整 equip（展示什么发什么），
            # 不再以 lv30/purple 重新生成；旧数据(无 equip)按存字段兜底
            equip = it.get("equip") or C.generate_equip(it["slot"], it.get("lv", 30), it.get("quality", "purple"))
            db.add_item(group_id, top_qq, f"eq_{_uuid.uuid4().hex[:8]}", equip, count=1)
            p = db.get_player(group_id, top_qq)
            name = p["name"] if p else top_qq
            lines.append(f"🎉 {name} 以 {amount} 金币拍得【{it['name']}】！")
            # 退还其他出价者
            for qq2, amt2 in it["bids"].items():
                if qq2 != top_qq:
                    p2 = db.get_player(group_id, qq2)
                    if p2:
                        db.update_player(group_id, qq2, gold=p2["gold"] + amt2)
                        lines.append(f"↩️ 退还 {p2['name']} {amt2} 金币")
        else:
            lines.append(f"💤 【{it['name']}】无人出价，流拍。")
    # v104R3 P2：落槌价去向说明（复验点12：赢家金币为系统回收，无文案说明）
    if any(it.get("bids") for it in items):
        lines.append("💰 落槌价已由拍卖行收讫(系统回收)，未成交者的出价已全额退还。")
    return "\n".join(lines)


def _settle_auction(cur, group_id: str) -> str:
    """（P4-5 兼容别名，见模块 docstring；social 旧引用已改调 settle_auction）"""
    return settle_auction(cur, group_id)


# ============================================================
# 过期拍卖结算 + 事件槽清理（原 social auction/bid 命令的双份重复检查收敛）
# ============================================================

def settle_expired_auction(group_id: str) -> str:
    """当前事件槽为过期拍卖 → 结算 + 清事件槽。返回结算文本(无则空串)。

    收敛 social._settle_auction 调用前的"读 include_expired + etype 判定 + 清槽"
    重复块（auction/bid 双命令同款）。过期拍卖必须先走结算（v104R3 P1-1），
    否则出价金币随 bids 一起销毁。非 auction 过期事件不清槽——Boss 事件由
    hunt_boss 指令处理，_maybe_roll_event 的"任意过期事件清槽"控制流留在命令层。
    """
    cur = db.get_world_event(include_expired=True)
    now = int(time.time())
    if not cur or cur["etype"] != "auction" or now < cur["ends_at"]:
        return ""
    lines = settle_auction(cur, group_id)
    db.clear_world_event()
    return lines


# ============================================================
# 拍卖进度持久化（原 social.bid 内 db.save_world_event 直调 ×2 收进 service）
# ============================================================

def save_auction_state(cur) -> None:
    """把拍卖进度(出价/一口价成交后物品移除)持久化回 world_event 槽。

    原命令层直调 db.save_world_event(cur["etype"], cur["ends_at"], cur["data"])——
    etype/ends_at/data 三者原样回写（store.save_world_event 先 DELETE 再 INSERT），
    槽读写语义收进 service 后由命令层在每次变更 bids 后调用。
    """
    db.save_world_event(cur["etype"], cur["ends_at"], cur["data"])
