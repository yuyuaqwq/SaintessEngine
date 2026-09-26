# -*- coding: utf-8 -*-
"""宿主命令壳的**通用半边**（`ShellBase`）—— 任何平台、任何包的宿主壳都共有的那一层。

它是什么
--------
引擎 host 契约把「一条消息 → `Env` → 包内 handler」打通；包内 handler 的**实现体**仍需要
一个「平台能力面」对象（历史形态 = 宿主 Mixin 壳，包内一律经 `env.state["shell"]` 取它）。
本文件提供那只壳里**与平台无关**的那一半：

| 面 | 归谁 |
|---|---|
| 分页 / 页码 / 文本剥离 / 提示抽取 / handler 路由 / `_run_shortcut` | 引擎 `command.base.CommandBase`（父类） |
| 取件管道（`bind_package` / `_sub` / `__getattr__` 按名解析 / `_package_modules` …） | **本文件** |
| 包内内容半边转发（体力族 / 设施判定 / 面板增幅 / 行为规则 / 翻页族 …） | **本文件**（值仍取包内真源） |
| 写档半边取件（`store_half`） | **本文件** |
| 环境位（GM 白名单 / 停服位） | **本文件**（只读环境变量 + 存档半边） |
| 平台动作的**扇出 + 记录口径**（广播 / 通知 ⇒ 逐群 `_deliver`） | **本文件**（平台无关；记录形状的**唯一**落点 `_record_deliver`） |
| 真投递面（发送 / 停服投递 / 平台身份 / 窥探投递） | 各平台的宿主子类（如 QQ 宿主 `host/shell.py::HostShell`） |

零平台 / 零包名的口径
--------------------
本文件**零平台 import**（无 astrbot、无 openid、无发送面），**零包名**：包内半边一律按
**半边名**（契约里的半边名，不是模块路径）经 `Package.optional_submodule(name)` 取；
模块扫描根从包清单 `entry` 派生。

为什么「内容半边转发」在引擎而不在各宿主各抄一份
------------------------------------------------
这些转发是「包内真源 → 壳上同名口」的一行搬用（`self._sub(<半边>).<函数>(...)`），与平台无关、
与包名无关；抄在宿主里 = 每换一个宿主就多一份漂移源（实测：试玩侧手搓壳缺 `_bag_view`
就是漂移结果）。转发名沿用历史壳的名字（包内实现体与包内文案按这些名字取件），**值一律仍住包内**：
引擎不存任何内容数据，也不出现任何游戏专有名词（`tests/test_no_game_vocabulary.py` 盯着）。

谁继承它
--------
    host/shell.py::HostShell(ShellBase)          # 真平台面（某宿主）
    editor/play_shell.py::PlayShell(ShellBase)   # 编辑器试玩面（记录式平台半边 + 身份面 fail-closed）
"""
from __future__ import annotations

import functools
import importlib
import json
import os
import pkgutil

from ..command import CommandBase as _EngineCommandBase
from ..session import SessionAdapter

__all__ = ["ShellBase", "ShellEnv", "store_half"]

#: 包内模块缓存（`{包根: [模块…]}`）——助手按名解析用；前缀从包清单 entry 派生，**不写包名**
_HELPER_MODULES: dict = {}


def _binds_shell(fn) -> bool:
    """包内函数是否以「宿主壳」为第一参数（`def fn(self, …)` / `def fn(shell, …)`）。"""
    import inspect
    try:
        params = list(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        return False
    return bool(params) and params[0] in ("self", "shell")


def store_half(pkg):
    """取包内存档半边（`persistence`），包未绑定 → None（装配处随后补）。"""
    if pkg is None:
        return None
    half = pkg.optional_submodule("persistence")
    if half is None:
        raise RuntimeError("ShellBase：包内存档半边 `persistence` 取不到（包契约缺件）")
    return half


class ShellEnv(object):
    """包内守卫钩子要的最小 `Env` 面（`uid` / `group_id` / `text` / `state["shell"]`）。"""

    def __init__(self, *, uid="", group_id="", text="", shell=None):
        self.uid = str(uid)
        self.group_id = str(group_id)
        self.text = str(text)
        self.player = None
        self.state = {"shell": shell}


class ShellBase(_EngineCommandBase):
    """宿主壳的通用半边：`env.state["shell"]`（引擎 `Host.build_env` 之前由装配处注入 `inject`）。

    平台子类只补「真平台面」；内容半边一律经 `_sub(<半边名>)` 取包内真源。
    """

    def __init__(self, *, pkg=None, store=None, context=None, session=None,
                 events=None, finder=None):
        self._pkg = pkg
        #: 存档半边门面（`store_half(pkg)` 或等价物；`_player` / `_record_state` 用）
        self._store = store or store_half(pkg)
        self.context = context                      # 平台发送面（由平台子类解释）
        self._events = events if events is not None else []   # 平台动作记录（广播 / 通知）
        self._finder = finder                       # 平台 handler 探测器（不给 → 引擎静态兜底）
        self._session = session or SessionAdapter(
            private_fallback="private", unknown_fallback="unknown")

    # ============================================================
    # 包内半边取件（按名、懒取；不写包内模块字面量）
    # ============================================================
    def bind_package(self, pkg) -> "ShellBase":
        """装配处绑定引擎 `Package`（幂等；绑定后各半边按名解析）。"""
        self._pkg = pkg
        if self._store is None:
            self._store = store_half(pkg)
        return self

    def _sub(self, name):
        """包内半边（`Package.optional_submodule`）；包未绑定 → 抛（拒绝静默空跑）。"""
        if self._pkg is None:
            raise RuntimeError("%s：未绑定引擎包（装配处应先 `bind_package(pkg)`）"
                               % type(self).__name__)
        mod = self._pkg.optional_submodule(name)
        if mod is None:
            raise RuntimeError("%s：包内半边 %r 不存在（包契约缺件）"
                               % (type(self).__name__, name))
        return mod

    def _rules(self):
        """内容规则半边（体力 / 设施 / 提示库 / 别名）。"""
        return self._sub("cmds_base_rules")

    # ---- 框架钩子：文案 / 别名 / 提示库（值取包内真源，本地零句子）----
    @property
    def register_hint(self):
        return self._rules().REGISTER_HINT

    @property
    def battle_none_hint(self):
        return self._rules().BATTLE_NONE_HINT

    @property
    def command_aliases(self):
        return self._rules().COMMAND_ALIASES

    def _tip_pool_map(self):
        return self._rules().TIP_POOL

    # ---- 框架钩子：认人 / 读档 / 战斗 / 状态 ----
    def _uid(self, event):
        return self._session.uid(event)

    def _player(self, group_id, qq_id):
        return self._store.get_player(group_id, qq_id)

    def _record_state(self, key, value):
        self._store.set_event_state(key, value)

    def _in_any_battle(self, group_id, qq_id):
        if self._store.get_battle(group_id, qq_id):
            return True
        fn = getattr(self, "_instance_battle_for", None)
        if fn is None:
            return False
        try:
            return bool(fn(group_id, qq_id))
        except Exception:                                        # noqa: BLE001
            return False

    # ---- 框架钩子：静态正则表 / 平台注册表探测 ----
    @classmethod
    def _build_static_handlers(cls):
        """静态兜底表 = 包内声明表（`content/data/commands.json` 的正则 → key）。"""
        mod = cls._static_source
        return mod() if mod is not None else []

    #: 装配处注入的「静态表供体」（`() -> [(compiled_re, key)]`）；不给 → 空表
    _static_source = None

    def _host_handler_finder(self):
        return self._finder

    # ---- 引擎钩子：包内游戏规则（全部转引包内真源，零重写）----
    def _at_smith(self, player):
        return self._rules().at_smith(player)

    def _at_shop(self, player, group_id="", qq_id=""):
        return self._rules().at_shop(player, group_id, qq_id)

    def _sa_shop_kind(self, player):
        return self._rules().sa_shop_kind(player)

    def _wild_trader_here(self, player, group_id="", qq_id=""):
        return self._rules().wild_trader_here(player, group_id, qq_id)

    def _at_healer(self, player):
        return self._rules().at_healer(player)

    def _facility_hint(self, player, kind):
        return self._rules().facility_hint(player, kind)

    def _stamina_max(self, player):
        return self._rules().stamina_max(player)

    def _stamina(self, player):
        return self._rules().stamina(player)

    def _spend_stamina(self, group_id, qq_id, cost, player, action="行动"):
        return self._rules().spend_stamina(group_id, qq_id, cost, player, action)

    def _add_stamina(self, group_id, qq_id, amount, player):
        return self._rules().add_stamina(group_id, qq_id, amount, player)

    def _stamina_bar(self, player, sep=" "):
        return self._rules().stamina_bar(player, sep)

    def _panel_bonus(self, group_id, qq_id):
        """外部面板增益聚合（真源 = 包内 `stat_bonus`）。"""
        return self._sub("stat_bonus").stat_bonus(
            group_id, qq_id, self._player(group_id, qq_id) or {})

    def _rule_fire(self, trigger, group_id, qq_id, player, cur_map, evt=None):
        return self._sub("rule_engine").fire(
            group_id, qq_id, player, cur_map, trigger, evt or {},
            hooks={"panel_bonus": lambda q: self._panel_bonus(group_id, q)})

    # ---- 摊位标签（逐字 = 原宿主指令壳里的同名静态口）----
    @staticmethod
    def _stall_label(stall):
        """摊位标签。"""
        if not stall:
            return ""
        return stall.get("title") or stall.get("name") or "货摊"

    # ============================================================
    # 包内助手按名解析（终态壳的「私有方法面」）
    # ------------------------------------------------------------
    # 旧壳里除命令入口外还有 ~258 个**非命令助手**（`_bag_view` / `_skill_panel` /
    # `_instance_battle_for` …）：包内实现体以 `self.<名>(…)` 调用它们。终态壳不把这 258 个
    # 名字抄一遍（那就是第二份漂移源），改为**按名向包内解析** —— 模块前缀从包清单 `entry`
    # 派生（`content/apply.py` → `content`），所以宿主里**零包名**。
    #
    # 解析顺序（与 tests/_engine_harness.py 的同名能力**同序**）：
    #   ① 包内模块级函数（`content/xxx.py::_bag_view`）
    #   ② 包内模块级类的同名方法（`content/economy_cmds.py::EconomyImpl._bag_view`）
    # 都取不到 → `AttributeError`（不静默造空实现）。
    # ============================================================
    def _package_modules(self) -> list:
        """包内模块清单（懒扫 + 缓存；扫描根 = 包清单 entry 的同级包）。"""
        pkg = self.__dict__.get("_pkg")
        if pkg is None:
            return []
        key = str(getattr(pkg, "root", "") or id(pkg))
        cached = _HELPER_MODULES.get(key)
        if cached is not None:
            return cached
        mods = []
        entry = str(getattr(pkg, "entry", "") or "")
        if entry.endswith(".py") and "/" in entry:
            prefix = entry[:-3].replace("/", ".").rsplit(".", 1)[0]
            try:
                root = importlib.import_module(prefix)
                for info in pkgutil.walk_packages(root.__path__, prefix + "."):
                    try:
                        mods.append(importlib.import_module(info.name))
                    except Exception:                            # noqa: BLE001
                        continue
            except Exception:                                    # noqa: BLE001
                self._warn("包内模块扫描失败（助手按名解析不可用）", exc_info=True)
        _HELPER_MODULES[key] = mods
        return mods

    def _package_helper(self, name):
        """按名找包内助手 —— **两遍解析**：先自绑壳候选，再自由函数；找不到 → None。

        ★ 为什么必须两遍（实测定性，反证见包侧探针 `probe3d_bump_repro.py`）——
        包内有**两个同名** `_bump_daily_progress`：
          · `content/world_cmds.py::_bump_daily_progress(self, group_id, qq_id, obj_key, lines=None)`
            （`_binds_shell=True`，壳应以 `self` 绑定后调用 = 模块扫序 **152**）
          · `content/profession_quests.py::_bump_daily_progress(inst, group_id, qq_id, obj_key, lines=None)`
            （首参名 `inst` ⇒ `_binds_shell=False` = 模块扫序 **122**）
        旧的「第 1 遍按模块扫序取模块级函数」会取中**扫序在前**的那个 ⇒ 命中非自绑的
        `profession_quests` 版；调用方按 `(group_id, qq_id, obj_key, lines)` 传四参 ⇒
        实参整体左移一位（`inst=group_id, group_id=qq_id, …`）⇒ 包内入口查不到 daily
        ⇒ **静默 return**（`lines==[]`、`_completed` 不 +1、金币不涨、**无异常**）。
        影响面：全包 143 条同名碰撞里只有这一条实取候选与自绑候选**形参个数相同**，
        其余 142 条形参个数不同（调用即 `TypeError`，吵闹但不静默）——
        见包侧 `out/probes/probe3e_helper_collisions.json`。

        修法 = 与 `tests/_engine_harness.py::Main.__getattr__` 同序：
        **pass 1 只收 `_binds_shell(fn)` 的候选**（模块级函数在前、模块级类的同名方法在后），
        pass 2 再回退自由函数（保持原有「模块扫序先落者胜」口径不变）。
        """
        mods = self._package_modules()
        # ---- pass 1：自绑壳候选（`def fn(self, …)` / `def fn(shell, …)`）----
        for mod in mods:
            fn = getattr(mod, name, None)
            if callable(fn) and getattr(fn, "__module__", "") == mod.__name__ and _binds_shell(fn):
                return fn
        for mod in mods:
            for value in vars(mod).values():
                if not isinstance(value, type):
                    continue
                if getattr(value, "__module__", "") != mod.__name__:
                    continue
                attr = getattr(value, name, None)
                if callable(attr) and _binds_shell(attr):
                    return attr
        # ---- pass 2：自由函数（不绑壳；候选按模块扫序，取先落者）----
        for mod in mods:
            fn = getattr(mod, name, None)
            if callable(fn) and getattr(fn, "__module__", "") == mod.__name__:
                return fn
        for mod in mods:
            for value in vars(mod).values():
                if not isinstance(value, type):
                    continue
                if getattr(value, "__module__", "") != mod.__name__:
                    continue
                attr = getattr(value, name, None)
                if callable(attr):
                    return attr
        return None

    def __getattr__(self, name):
        """缺失属性 → 包内助手（非命令）。双下划线名直接拒绝，避免干扰 copy/pickle 探测。"""
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        helper = self._package_helper(name)
        if helper is None:
            raise AttributeError(
                "%s has no attribute %r（包内无同名落点）" % (type(self).__name__, name))
        return functools.partial(helper, self) if _binds_shell(helper) else helper

    # ============================================================
    # 平台动作：**扇出 + 记录口径**（平台无关）—— 真投递落子类 `_deliver`
    # ============================================================
    # 为什么在引擎：同一件事（广播 / 通知）两侧壳各写一遍 ⇒ 记录形状必然漂移（实测 T7-C：
    # QQ 记 `say`、试玩记 `broadcast` ⇒「有动作的样本」进不了对拍）。扇出（按群表逐群）与
    # 记录形状写在**引擎一处** ⇒ 两侧按构造逐字节相同；平台子类只留 `_deliver` 的真投递
    # （与可选的「群表取值口」覆盖）。
    async def _broadcast(self, text, exclude_group=None):
        """全服广播：按**群表**逐群扇出 ⇒ 每群一条 `_deliver`（`exclude_group` = 不发的那群）。"""
        for gid in self._group_table():
            if exclude_group and str(gid) == str(exclude_group):
                continue
            await self._deliver(str(gid), str(text))

    async def _notify_hermes(self, group_id, qq_id, content, msg_type):
        """Hermes webhook 通知：与广播**同一条落点**（`_deliver` ⇒ 一条记录）。"""
        await self._deliver(str(group_id), str(content))

    def _group_table(self):
        """群表取值口（平台无关的缺省）：存档半边的玩家群列表；平台群表不同则子类覆盖它。"""
        if self._store is None:
            raise RuntimeError(
                "%s：未绑定存档半边，取不到广播群表（装配处应先 `bind_package(pkg)`）"
                % type(self).__name__)
        return [str(g) for g in (self._store.get_player_groups() or [])]

    def _record_deliver(self, group_id, text):
        """单群投递的**记录** —— 记录形状的**唯一**落点（两侧按构造逐字节相同）。"""
        self._events.append({"action": "deliver", "group_id": str(group_id),
                             "text": str(text)})

    # ============================================================
    # 环境位（GM 白名单 / 停服位）—— 只读环境变量 + 存档半边，平台无关
    # ============================================================
    def _gm_whitelist(self):
        wl = set()
        for x in (os.environ.get("GWEN_GM_QQ") or "").split(","):
            x = x.strip()
            if x:
                wl.add(x)
        try:
            raw = self._store.get_event_state("gm_whitelist")
            if raw:
                for x in json.loads(raw):
                    wl.add(str(x))
        except Exception:                                        # noqa: BLE001
            self._warn("读取 GM 白名单失败，回退环境变量", exc_info=True)
        return wl

    def _is_gm(self, qq_id):
        qq_id = str(qq_id)
        return qq_id.startswith("gm_") or qq_id in self._gm_whitelist()

    def _server_down(self):
        return self._store.get_event_state("server_maintenance") == "1"

    def _server_down_msg(self):
        return self._store.get_event_state("server_maintenance_msg") or ""

    # ============================================================
    # 包内实现体的两条平台例外入口（内容在包内，壳侧只转发）
    # ============================================================
    async def page_flip(self, event):
        """翻页快捷键（平台例外）：转发包内实现。"""
        gid, qid = self._uid(event)
        async for r in self._sub("player_cmds").page_flip(self, event, gid, qid):
            yield r

    async def shortcut_trigger(self, event):
        """裸数字快捷触发（平台例外）：转发包内实现。"""
        gid, qid = self._uid(event)
        player = self._player(gid, qid)
        async for r in self._sub("player_cmds").shortcut_trigger(self, event, gid, qid, player):
            yield r

    def _guard_hook(self, name, *, uid="", group_id="", text=""):
        """跑包内一条守卫钩子（判定与文案都在包）；包内没有 → None（不拦）。

        平台例外命令（如 `gm_play` / `gm_spy`）**不进**引擎的 `Host.invoke`，所以它们的权限
        判定由本方法显式补一次——否则这两条会绕过包内 `hook:gm`（形同后门）。
        """
        hooks = self._pkg.guard_hooks() if self._pkg is not None else {}
        fn = hooks.get(name) if isinstance(hooks, dict) else None
        if not callable(fn):
            return None
        env = ShellEnv(uid=uid, group_id=group_id, text=text, shell=self)
        return fn(env, None) or None
