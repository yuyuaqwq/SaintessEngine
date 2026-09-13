# -*- coding: utf-8 -*-
"""B9 线 L1 宿主注入面 —— 交易区/经济命令「包内实现 ↔ 宿主」的唯一替身登记处。

为什么要有它
============
宿主 `game/commands/economy.py`（6,849 行）与 `game/services/shop.py`（496 行）的实现正文
**逐字搬进本包**（`content/economy_cmds.py` / `content/shop.py`），宿主文件只留
「命令注册 + 从 DB 取玩家 + 调包 + 渲染消息」。包**不 import 宿主**（方向铁律：内容 → 引擎；
引擎/包侧零宿主依赖），改由宿主壳在 `bind_host(...)` 里把需要的宿主面**注入**进来：

    content/economy_host.py   本模块：注入登记 + 惰性引用 `_HostRef` + 取件器 `_h()`
    content/economy_cmds.py   economy 实现（模块级常量/渲染器 + `EconomyImpl` 混合类）
    content/shop.py           交易区实现（原 `game/services/shop.py` 正文）

⚠️ 顺序铁律：`bind_host()` 必须在 `import content.economy_cmds` / `import content.shop`
   **之前**调用 —— 两者模块级代码就要读宿主面（`C.CRAFT_RECIPES`、`_shop_svc._MAT_FACILITY`、
   `C.SHOP_EQUIP` 等），惰性引用在 import 期即被求值。未绑定 → `RuntimeError`（fail-closed，
   不静默给空表：空表会让商店卖空、渲染缺行，比报错难查得多）。

⚠️ 注入的是**宿主模块对象本身**（同一模块树，不是第二份副本）—— 数据 / 数值 / 文案真源仍唯一，
   包内因此**不产生任何第二份表**（域导出物与本注入面并存时以域为编辑器口径，见 B9-L1 报告
   「未做与缺口」）。
"""

_HOST = {}
_BOUND_ORDER = []
_CONFLICTS = []


class _HostRef:
    """宿主面惰性引用（模块级 `C.ITEMS` / `_ss.town_level` / `db.get_player` 照原样写）。

    取件在**访问时**发生（不是绑定时），因此宿主壳可以在 `import content.*` 之前
    一次性注入；`__getattr__` 转发到真对象，`__call__` 让函数/类可直接调用，
    容器方法（`items()` / `get()` / `values()`）同样可用。
    """

    __slots__ = ("_key",)

    def __init__(self, key):
        object.__setattr__(self, "_key", key)

    def _value(self):
        key = object.__getattribute__(self, "_key")
        try:
            return _HOST[key]
        except KeyError:
            raise RuntimeError(
                "宿主面 %r 未注入：宿主壳需先调 bind_host()（见 content/economy_host.py 模块头）"
                % (key,))

    def __getattr__(self, name):
        return getattr(self._value(), name)

    def __getitem__(self, name):
        return self._value()[name]

    def __call__(self, *args, **kwargs):
        return self._value()(*args, **kwargs)

    # ⚠️ 刻意**不**实现 `__len__` / `__iter__` / `__contains__`：真源里存在
    #    `x = y or _ss`（注入缺省的写法，见 `content/shop.py:326 buy_index_dispatch`）——
    #    若代理实现了 `__len__`，`or` 的真值判定会走 `len(module)` → TypeError
    #    （2026-09-13 实测：`buy 1` 直接抛，快照 before/after 差 2 例）。代理恒为真值即可，
    #    容器语义（`len(C.X)` / `for it in C.X` / `k in C.X`）走 `__getattr__` 拿真对象，不受影响。

    def __repr__(self):
        return "<HostRef %r>" % (object.__getattribute__(self, "_key"),)


def bind_host(**kw):
    """登记宿主面（幂等；**首绑优先**）。

    ⚠️ 双模块树（`docs/ENGINE_CONTENT_SPLIT_PLAN.md §8-R2`）：本仓并存
    `game.*` 与 `data.plugins.dragonfall.game.*` 两套 import 路径（同一份文件的两个模块
    对象），而包 `content.*` 是**单例**——两个树的壳都会绑一次，对象不同但内容同源。
    因此这里**首绑优先**：后续不同对象只记进 `_CONFLICTS`（`conflicts()` 可查），不抛
    ——若抛，测试进程里「命令层走 data.plugins 树 + 某处 `from game.x import y`」会当场炸，
    而这不是本线的错。真静默失效（键缺失 / 面是空表）仍由 `_HostRef` / `_h` fail-closed 兜住。
    """
    for key, val in kw.items():
        if key in _HOST and _HOST[key] is not val:
            _CONFLICTS.append((key, _HOST[key], val))
            continue
        _HOST[key] = val
        if key not in _BOUND_ORDER:
            _BOUND_ORDER.append(key)
    return tuple(_BOUND_ORDER)


def conflicts():
    """首绑被忽略的异对象绑定（双模块树诊断用）。"""
    return list(_CONFLICTS)


def _h(name):
    """取件器：包内正文里「函数体内 `from ..xxx import name`」的等位替代。

    语义与惰性 import 等位（原写法就是函数内 import → 调用时绑定），未注入 → 抛。
    """
    try:
        return _HOST[name]
    except KeyError:
        raise RuntimeError("宿主面 %r 未注入（包内正文原为 `from .. import %s`）" % (name, name))


def bound():
    """当前注入面（自检/测试用：键 → 对象）。"""
    return {k: _HOST[k] for k in _BOUND_ORDER}
