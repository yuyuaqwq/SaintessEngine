# -*- coding: utf-8 -*-
"""编辑器「试玩」· 子进程侧 —— 在本进程里装配引擎 + 游戏包 + **宿主面**，跑一条条命令。

入参（stdin JSON）
------------------
    {
      "pkg_dir":   "<游戏包目录：game.json 所在>",     # 必填（也读环境变量 FW_PKG_DIR）
      "host_root": "<宿主插件目录：game/ 的父目录>",   # 必填（也读 B20_HOST_ROOT）——包内
                                                        # `content/**` 的宿主替身口要靠它接线
      "engine_root": "<saintess_engine 所在目录>",      # 缺省读 FW_FRAMEWORK_ROOT
      "commands":  ["注册 试玩 男", "背包", ...],       # 命令序列（原样喂，含 @ 前缀/参数）
      "uid": "...", "group_id": "...",
      "seed": 1,                                        # 固定种子（同种子可复现）
      "db": "<sqlite 路径>",                            # 缺省 <db_dir>/play.db
      "echo": "last|all|null"                          # 每条打印多少（缺省 all）
    }

出参（stdout 每行 MARKER+JSON，最后一行 summary）
------------------------------------------------
    每条命令一行：{"i":0,"text":"注册 试玩 男","key":"...","segments":[...],
                   "state_sha":"<sha256>","ok":true}
    末行：       {"ok":true,"stage":"done","pkg":...,"count":194,"ran":N,
                  "commands_sha":"<全序列逐字节 sha256>"}
    失败：       {"ok":false,"stage":"load|engine|host|version|crash","message":...}

为什么必须子进程
----------------
与 `simulate.py` / `simulate_worker.py` 同款三条理由（装配副作用 / 隔离兜底 / 循环导入），
另加本条：**宿主面注入会污染进程级全局**（`bind_host()` 是模块级登记），所以试玩一律
在一次性子进程里做，编辑器主进程零 `saintess_engine`。

宿主面怎么来（关键设计）
------------------------
包内 `content/**` 大量走「宿主替身口」（`_HostMod("db")` / `_host_attr("core.stats", …)` /
`Function` 句柄 `bind_host(db=…, C=…)`）：这些**不是**引擎 host 契约的一部分，而是平台插件
（`host_root`）在装配期注入的。所以本 worker 的装配顺序照 **QQ 宿主同款**：

    ① 引擎根 + 插件根 + 插件 framework 根 → sys.path
    ② `GWEN_GAME_DB` → 独立库（缺省 <db_dir>/play.db；绝不碰真仓任何库）
    ③ `import game`（插件装配入口：装引擎 hook + 加载包 + 宿主替身口注入）
    ④ `saintess_engine.host.load_package(pkg_dir, inject=…)` + `install_engine()`（引擎官方包
       加载器）—— ★ W2a：包声明了 `bind`，注入面（库路径/时钟/日志/流水 sink）从这里给
    ⑤ `PlayHost(Host)` 覆写 `build_env`：把 `env.state["shell"]` 换成 `PlayShell`
       —— 包内实现体经它做宿主取件（`_uid/_player/_strip_cmd/_page_items/_tip/_broadcast`…）
    ⑥ 逐条 `host.handle(ctx)` → 收 `say()` 段 → 打印 JSON 行

`PlayShell` 只实现包内实现体真正用到的 ~20 个宿主壳方法（清单来源：AST 扫
`content/**` 的 `self./_shell(env).` 访问 ∩ 插件 `game/**` 的同名实现），
纯函数口径逐字照插件实现；平台侧动作（广播 / webhook）落成「记录 + 无网络副作用」。
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import random
import sys
import time
import traceback

MARKER = "__B20_PLAY__"
FW_ROOT = os.environ.get("FW_FRAMEWORK_ROOT") or ""
PKG_DIR = os.environ.get("FW_PKG_DIR") or ""
HOST_ROOT = os.environ.get("B20_HOST_ROOT") or ""


# ============================================================
# 引擎注入面（★ W2a：包清单声明了 `bind` ⇒ load_package / Host.boot 必须给 inject）
# ============================================================
class _PlayLog(object):
    """最小日志门面（包内唯一取用口 `content/obs.py` 只要 `.warning/.info/...`）。"""

    def _emit(self, *a, **k):
        return None

    debug = info = warning = error = critical = exception = _emit


class _PlayTLog(object):
    """最小流水控制面：`enabled()=False` + `tlog()=None` = 宿主契约里的「未启用」（零行为）。"""

    def enabled(self) -> bool:
        return False

    def tlog(self):
        return None

    def emit(self, kind, actor="", **fields):
        return None


# ============================================================
# 输出
# ============================================================
def emit(obj: dict) -> None:
    sys.stdout.write(MARKER + json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n")
    sys.stdout.flush()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _dump(obj) -> str:
    """稳定序列化（键序固定 + 非 ASCII 不转义）——对拍基准的一部分。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _state_sha(adapter) -> str:
    """状态指纹：**整个存档库**（每表每行，键序确定性）+ 进程内 blob。

    为什么不是「只拍 player 一行」：包内存档层的真源是库（`content/persistence`），
    非玩家档的状态（背包/任务/签到/图鉴/event_state …）同样影响后续命令 —— 只拍 player
    会让「签到发奖」这类差异漏掉。SQLite 行序不稳 → 先按各表主键排序再序列化。
    """
    import sqlite3
    db_path = os.environ.get("GWEN_GAME_DB") or ""
    snap = {"blobs": adapter.blobs if adapter is not None else {}}
    if db_path and os.path.isfile(db_path):
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            tables = {}
            for (name,) in conn.execute(
                    "select name from sqlite_master where type='table' order by name"):
                if str(name).startswith("sqlite_"):
                    continue
                rows = [list(r) for r in conn.execute('select * from "%s"' % name)]
                tables[str(name)] = rows
            conn.close()
            snap["tables"] = tables
        except Exception as e:            # noqa: BLE001
            snap["tables_error"] = repr(e)
    return _sha(_dump(snap))


# ============================================================
# 平台事件替身（鸭子类型；包内只调这些方法）
# ============================================================
class PlayEvent:
    """最小平台事件（契约 = 引擎 `session.adapter.PlainEvent`，另加包内用到的两个访问点）。"""

    def __init__(self, text: str, group_id: str, qq_id: str):
        self.message_str = text
        self._g = group_id
        self._q = qq_id
        self.stopped = False

    def get_message_str(self):
        return self.message_str or ""

    def get_group_id(self):
        return self._g

    def get_sender_id(self):
        return self._q

    def plain_result(self, text):
        return str(text)

    def stop_event(self):
        self.stopped = True


# ============================================================
# 宿主壳（包内 `env.state["shell"]`）
# ============================================================
class PlayShell:
    """无平台宿主壳 —— 只提供包内实现体真正取用的那批方法。

    口径来源（逐条对照插件实现，行号见注释）：
      `_uid`/`_player`/`_in_any_battle`  ← `game/commands/base.py:323/332/335`
      `_stamina*`/`_spend_stamina`/`_add_stamina`/`_at_*`/`_sa_shop_kind`/`_wild_trader_here`
      /`_facility_hint`                  ← `game/commands/base.py:349-407` 家族，
                                           实现真源在包内 `content/cmds_base_rules.py`
      `_strip_cmd`/`_page_items`/`_parse_page`/`_tip` ← 引擎原语 + 插件同名薄壳
      `_broadcast`/`_notify_hermes`      ← `game/commands/base.py:301` / `misc.py:56`
                                           （平台动作 → 落成记录，无网络副作用）
    """

    def __init__(self, host, session, events: list):
        self.host = host                  # PlayHost（拿 pkg / db / blobs）
        self.session = session            # 引擎 SessionAdapter（组/用户归一）
        self.events = events              # 平台动作记录（回话之外的动作）
        self._db = None

    # ---------- 取件 ----------
    def _pkg_mod(self, dotted):
        return importlib.import_module(dotted)

    @property
    def db(self):
        if self._db is None:
            # 插件 `game.db` 与包内 `content.persistence` 是**同一只库**（B17）
            self._db = importlib.import_module("game.db")
        return self._db

    def _rules(self):
        return self._pkg_mod("content.cmds_base_rules")

    # ---------- 认人 / 读档 ----------
    def _uid(self, event):
        return self.session.uid(event)

    def _player(self, group_id, qq_id):
        from content.persistence import get_player
        return get_player(group_id, qq_id)

    def _in_any_battle(self, group_id, qq_id) -> bool:
        if self.db.get_battle(group_id, qq_id):
            return True
        f = getattr(self, "_instance_battle_for", None)
        if f is None:                     # 包内实现另有同名方法（副本战斗）
            return False
        try:
            return bool(f(group_id, qq_id))
        except Exception:                 # noqa: BLE001
            return False

    # ---------- 取参 / 分页 / 提示（引擎原语） ----------
    def _strip_cmd(self, event, cmd="", aliases=()):
        from saintess_engine.command import strip_command
        return strip_command(event.get_message_str() or "", cmd, aliases).strip()

    def _page_items(self, items, page=1, per_page=10):
        from saintess_engine.command import page_items
        return page_items(items, page, per_page=per_page)

    def _parse_page(self, text, default=1):
        from saintess_engine.command import parse_page
        try:
            return int(parse_page(text or "") or default)
        except Exception:                 # noqa: BLE001
            return int(default)

    def _tip_pool_map(self) -> dict:
        return self._rules().TIP_POOL

    def _tip(self, name, key="", **kw):
        """面板底部引导提示（v127 数据驱动）——引擎 `pick_tip` + 包侧提示库。"""
        pool = self._tip_pool_map()
        if isinstance(name, str) and name in pool:
            pool, name = pool.get(name), key
        try:
            from saintess_engine.command import pick_tip
            return pick_tip(pool, name, **kw)
        except Exception:                 # noqa: BLE001
            return ""

    def _record_state(self, key: str, value) -> None:
        self.db.set_event_state(key, value)

    # ---------- 体力 / 设施（实现真源在包内） ----------
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

    # ---------- 规则 / 称号 ----------
    def _title_bonus(self, group_id, qq_id):
        """外部面板增益聚合（真源 = 包内 `stat_bonus`；与线上 `host/shell.py::_title_bonus` 同款）。

        ★ 2026-09-15 修：此前写的是 `mod.title_bonus(...)` —— **包内没有这个名字**（线上壳用的是
        `stat_bonus(gid, qid, player)`）⇒ 试玩一走到玩家/战斗路径就报
        `AttributeError: module 'content.stat_bonus' has no attribute 'title_bonus'`。
        """
        mod = self._pkg_mod("content.stat_bonus")
        return mod.stat_bonus(group_id, qq_id, self._player(group_id, qq_id) or {})

    def _rule_fire(self, trigger, group_id, qq_id, player, cur_map, evt=None):
        mod = self._pkg_mod("content.rule_engine")
        return mod.fire(group_id, qq_id, player, cur_map, trigger, evt or {},
                        hooks={"title_bonus": lambda q: self._title_bonus(group_id, q)})

    # ---------- GM / 停服（照插件判定，无平台依赖） ----------
    def _gm_whitelist(self) -> set:
        wl = set()
        for x in (os.environ.get("GWEN_GM_QQ") or "").split(","):
            x = x.strip()
            if x:
                wl.add(x)
        try:
            raw = self.db.get_event_state("gm_whitelist")
            if raw:
                for x in json.loads(raw):
                    wl.add(str(x))
        except Exception:                 # noqa: BLE001
            pass
        return wl

    def _is_gm(self, qq_id) -> bool:
        qq_id = str(qq_id)
        if qq_id.startswith("gm_"):
            return True
        return qq_id in self._gm_whitelist()

    @staticmethod
    def _server_down() -> bool:
        try:
            from content.persistence import get_event_state
            return get_event_state("server_maintenance") == "1"
        except Exception:                 # noqa: BLE001
            return False

    @staticmethod
    def _server_down_msg() -> str:
        try:
            from content.persistence import get_event_state
            return get_event_state("server_maintenance_msg") or ""
        except Exception:                 # noqa: BLE001
            return ""

    # ---------- 平台动作（试玩里只记录，不外发） ----------
    async def _broadcast(self, text, exclude_group=None):
        self.events.append({"action": "broadcast", "text": str(text),
                            "exclude": str(exclude_group or "")})

    async def _notify_hermes(self, group_id, qq_id, content, msg_type):
        self.events.append({"action": "hermes", "content": str(content),
                            "msg_type": str(msg_type)})

    def _instance_battle_for(self, group_id, qq_id):
        """副本内战斗查询（包内实现同名方法；缺件 → False，不发明分支）。"""
        mod = getattr(self, "_instance_mod", None)
        if mod is None:
            try:
                mod = self._pkg_mod("content.instance_cmds")
            except Exception:             # noqa: BLE001
                return False
            self._instance_mod = mod
        fn = getattr(mod, "instance_battle_for", None)
        return bool(fn(group_id, qq_id)) if callable(fn) else False


# ============================================================
# 宿主（引擎 Host 的试玩覆写：只加「注入宿主壳」一件事）
# ============================================================
def _make_host_class():
    """运行期派生引擎 `Host`（覆写点两个：`build_env` 塞 `state["shell"]`、`invoke` 支持
    `async def` handler）。

    `async` 覆写为什么必要：包内 45 条经济命令 + 战斗族 + 副本族的 handler 是
    `async def fn(env) -> list[str]`（`content/cmds_*.py::_declare` 登记），而引擎
    `Host.invoke` 是同步的（W-B18-L3c §「未做」已登记该缺口）。宿主桥
    （`game/commands/_host_bridge.py::run_async`）自己 `await`，本 worker 同法补齐 ——
    **不改引擎**，在子进程侧派生覆写。
    """
    from saintess_engine.host import Host as EngineHost

    class _PlayHost(EngineHost):
        shell = None

        def build_env(self, key, spec, ctx, player, *, raw=None):
            env = super().build_env(key, spec, ctx, player, raw=raw)
            if self.shell is not None:
                env.state = dict(env.state or {})
                env.state["shell"] = self.shell
            return env

        def invoke(self, spec, ctx, player, *, raw=None):
            """与引擎 `Host.invoke` 同序（见 runtime.py:227-248），只在**调用处理器**那一步
            补 async 分支（`async def handler` → 跑完事件循环再收段）。"""
            key = str(getattr(spec, "key", "") or "")
            entry = self.handlers.get(key) if self.pkg else None
            if not entry:
                return self.declared_echo(spec)
            fn = self.pkg.resolve_handler(entry.get("handler")) if self.pkg else None
            if fn is None:
                return ["【%s】包内处理器未解析：%r（检查 content/commands.py 的 handler 引用）"
                        % (key, entry.get("handler"))]
            env = self.build_env(key, spec, ctx, player, raw=raw)
            guards = entry.get("guards")
            if guards is None:
                guards = list(getattr(spec, "guards", ()) or ())
            from saintess_engine.host import run_guards
            blocked = run_guards(guards, env, builtin=self.builtin_guards(),
                                 hooks=(self.pkg.guard_hooks() if self.pkg else {}))
            if blocked:
                return [blocked]
            out = fn(env)
            if hasattr(out, "__await__"):
                import asyncio
                out = asyncio.run(out)
            return self._as_replies(out)

    return _PlayHost


# ============================================================
# 适配器（三函数 + 可选钩子）
# ============================================================
class PlayAdapter:
    """适配器：**玩家档 = 包内存档层**（与 QQ 宿主 `db.get_player` 同源），blob 走内存。

    为什么玩家档必须走包内 `content.persistence`（= 插件 `game.db`）：包内 handler 的
    权威玩家档是**落库的那一行**（`register` / `move` / `use` … 都直接写库）。若这里另存
    一份内存 dict，第一条命令之后就与库漂移（实测：`角色` 拿不到 `class_name`）。
    这与引擎契约不冲突：`load_player/save_player` 只是「读档/落档」两个口，
    形状仍是普通 dict（不含 ORM/连接句柄）。
    """

    def __init__(self, uid, group_id, seed):
        self.uid = str(uid)
        self.group_id = str(group_id)
        self.seed = seed
        self.players: dict = {}           # 兜底（包内存档层不可用时）
        self.blobs: dict = {}
        self.said: list = []
        self.events: list = []
        self.tlogs: list = []
        self._store = None

    # ---------- 存档层（包内 content.persistence） ----------
    def _persistence(self):
        if self._store is None:
            from content import persistence
            self._store = persistence
        return self._store

    # ① 收消息（本 worker 不用 serve_forever，保留形状）
    def recv(self):
        return None

    # ② 读档 / 写档
    def load_player(self, uid):
        try:
            row = self._persistence().get_player(self.group_id, str(uid))
        except Exception:                 # noqa: BLE001
            row = None
        return row if row else self.players.get(str(uid))

    def save_player(self, uid, data):
        self.players[str(uid)] = data
        if not isinstance(data, dict):
            return
        try:
            self._persistence().update_player(self.group_id, str(uid), **data)
        except Exception:                 # noqa: BLE001  （字段非法 → 只留内存，测试可见）
            pass

    # ③ 回话
    def say(self, to, text):
        self.said.append(str(text))

    # 可选钩子
    def clock(self):
        return self.clock_value

    def rng(self):
        return random.Random(self.seed)

    def on_tlog(self, record):
        self.tlogs.append(record)

    def load_blob(self, key):
        return self.blobs.get(key)

    def save_blob(self, key, value):
        self.blobs[key] = value

    clock_value = float(os.environ.get("B20_CLOCK") or 1700000000.0)


# ============================================================
# 装配
# ============================================================
def _setup_paths(pkg_dir: str, host_root: str, engine_root: str) -> None:
    roots = []
    if engine_root:
        roots.append(engine_root)
    if host_root:
        if os.path.isdir(os.path.join(host_root, "framework")):
            roots.append(os.path.join(host_root, "framework"))
        roots.append(host_root)
        # 平台适配层替身（插件测试同款；`game/**` 的 `_platform.py` 自带等价实现，此处是
        # 条件性 import 的兜底）。只在有 astrbot 词的字面 import 时才被命中。
        shim = os.path.join(host_root, "tests", "shim_astrbot")
        if os.path.isdir(shim):
            roots.append(shim)
    if os.path.isdir(os.path.join(pkg_dir, "content")):
        roots.append(os.path.join(pkg_dir, "content"))
    roots.append(pkg_dir)
    for p in roots:
        if p and os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)


def _setup_db(payload: dict) -> str:
    db = payload.get("db") or ""
    if not db:
        db_dir = payload.get("db_dir") or os.path.join(os.path.expanduser("~"), ".b20")
        os.makedirs(db_dir, exist_ok=True)
        db = os.path.join(db_dir, "play.db")
    os.environ["GWEN_GAME_DB"] = db
    os.environ.setdefault("GWEN_TEST_MODE", "1")
    return db


def _freeze_clock(ts: float) -> None:
    """把包内各实现模块的**墙钟读取点**钉死到 `ts`（B20 对拍用；缺省不调用）。

    为什么需要：包内实现体直接 `time.time()` / `datetime.date.today()`（`content/**`
    尚未全部改走引擎 `saintess_engine.clock` 假钟出口 —— 见报告「未能确认的事」），
    而 `时间` / 天气 / 冷却 / 「今日」这类命令的输出与**当前时刻**有关。
    对拍（同 seed + 同命令序列 → 逐字节）必须在两侧用同一个固定时刻，否则
    `🕰️ 18:24` 与 `18:26` 这种天然差异会淹没真实差异。

    口径：只替换**已 import 的 `content.*` 模块**里对 `time` / `datetime` 的模块级引用
    （`mod.time.time`、`mod.datetime.now/date.today`），不动 stdlib 全局，
    也不碰引擎 —— 引擎 `clock.set_provider()` 另设（同一时刻）。
    """
    import datetime as _dt
    import time as _time_mod

    class _FrozenDateTime(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.fromtimestamp(ts, tz) if tz else cls.fromtimestamp(ts)

    class _FrozenDate(_dt.date):
        @classmethod
        def today(cls):
            return cls.fromtimestamp(ts)

    class _ClockProxy:
        def __getattr__(self, name):
            return getattr(_time_mod, name)

        @staticmethod
        def time():
            return ts

    for name, mod in list(sys.modules.items()):
        if not (name == "content" or name.startswith("content.")) or mod is None:
            continue
        if getattr(mod, "time", None) is _time_mod:
            mod.time = _ClockProxy()
        if getattr(mod, "datetime", None) is _dt:
            proxy = type("_dt_proxy", (), {})()
            proxy.datetime = _FrozenDateTime
            proxy.date = _FrozenDate
            proxy.timedelta = _dt.timedelta
            proxy.time = _dt.time
            proxy.timezone = _dt.timezone
            mod.datetime = proxy
    # 宿主存档层工厂（`game.store.store_factory`）把 stdlib `time.time` 作为 clock 句柄注入
    # 包内存档层（`handles._H["clock"]`）→ 落库时间戳会走真墙钟；对拍两侧必须同刻。
    # 该句柄是**函数对象**而非模块引用，所以只能改注入值本身（`handles.bind(clock=…)`，
    # 与宿主工厂同一个注入口，不新增第三套）。
    for _name in ("content.persistence.handles", "game.store.store_factory",
                  "game.store.connection"):
        mod = sys.modules.get(_name)
        if mod is not None and getattr(mod, "time", None) is _time_mod:
            mod.time = _ClockProxy()
    try:
        import content.persistence.handles as _handles
        if not _handles._H.get("clock"):
            _handles.bind(clock=lambda: float(ts))
        else:
            _handles.bind(clock=lambda: float(ts))
    except Exception:                     # noqa: BLE001
        pass
    try:
        from saintess_engine import clock as _clock
        _clock.set_provider(lambda: float(ts))
    except Exception:                     # noqa: BLE001
        pass


def _import_host(host_root: str):
    """照 QQ 宿主装配口径 import 插件（`game`）——引擎 hook 装配入口。"""
    if not host_root or not os.path.isdir(os.path.join(host_root, "game")):
        return None
    return importlib.import_module("game")


def _import_host_commands(host_root: str):
    """import 插件的命令层（`game.commands`）——**宿主替身口的注入点**。

    这一步是包内命令表可加载的前提（见 run() 里的顺序铁律）：各 `game/commands/*.py`
    在模块级调 `content.economy_host.bind_host(...)` / `content.<域>.bind_host(...)`，
    把宿主侧的表/句柄注入包内替身口。缺了它，包内 `cmds_economy` 等模块 import 即抛。
    返回实际 import 到的模块名（证据用）。
    """
    if not host_root or not os.path.isdir(os.path.join(host_root, "game", "commands")):
        return []
    mod = importlib.import_module("game.commands")
    names = [getattr(mod, "__name__", "game.commands")]
    for name in sorted(os.listdir(os.path.join(host_root, "game", "commands"))):
        if name.endswith(".py") and not name.startswith("__"):
            names.append(name[:-3])
    return names


def _make_platform_shell(host_root: str, adapter, seed, pkg=None):
    """平台宿主壳（`env.state["shell"]`）。

    为什么用真的壳而不是手搓 stub：包内实现体（`economy_cmds.EconomyImpl` /
    `world_cmds` / `player_cmds` / `combat_cmds` / `instance_cmds` 的模块级函数）以
    `self` = 壳调用 **~235 个宿主私有方法**（`_bag_view` / `_craft_line` / `_instance_*` …），
    它们不是引擎 host 契约的一部分，手搓 stub 等于把宿主命令层再抄一遍（不可避免的漂移）。
    试玩侧与 QQ 侧共用**同一个壳类**：差异只剩「事件对象」（`PlayEvent` vs AstrBot 事件）
    与「驱动方式」（引擎 `Host.handle` vs 通道派发）。

    ★ 终态装配（2026-09-15，P5C/P5F 删壳后）——「测试装配差」修正
    ----------------------------------------------------------
    宿主壳已从「`game/commands/**` 194 个 Mixin 汇编」收编为**单文件**
    `host/shell.py::HostShell`（通用半边在引擎 `CommandBase`，内容半边经
    `Package.optional_submodule` 转引包内真源）。旧写法 `import game.commands` 取 Mixin 类，
    在删壳后的树上拿到的是**空 namespace package**（`game/commands/` 只剩两个孤立 `.pyc`，
    零 `.py`）⇒ `bases=()` ⇒ `type("B20PlayShell", (), {})` ⇒ 壳上 `_uid/_player/_db/...`
    全缺。**实测**（本文件修改前，`work/host/framework/tests/test_editor_play.py`）：
    44 条对拍样本里 **34 条** play 侧红，典型
    `AttributeError: 'B20PlayShell' object has no attribute '_uid'` /
    `RuntimeError: cmds_player：实现体同步驱动失败：KeyError('class_name')`；且
    `试玩侧注册建档` 首条就红（共同起点建不出来）⇒ 7 条断言连锁红。

    故**先建终态壳**；仅当宿主树里没有 `host/shell.py`（删壳前的旧树）才回落旧 Mixin 汇编。
    两条路都要求包已物化：终态壳的存档半边经 `pkg.optional_submodule("persistence")` 取
    （调用方传 `pkg`）。

    `_static_source`（平台例外命令的静态兜底表）**故意不装**：它要宿主插件包的
    `registration` 模块在 sys.path 上，而本 worker 只按「host_root 直接可 import」装配
    （与该函数历史上只 import `game` 的口径一致）；对拍样本里没有平台例外命令。
    缺省 `None` ⇒ 空静态表（引擎静态路由仍按包内声明工作）。
    """
    if not host_root or not os.path.isdir(os.path.join(host_root, "game")):
        return None
    # ---- ① 终态宿主壳（删壳后唯一落点）----
    try:
        from host.shell import HostShell
    except Exception:                     # noqa: BLE001  旧树（删壳前）没有 host/shell.py
        HostShell = None
    if HostShell is not None:
        try:
            from saintess_engine.session import SessionAdapter
            _session = SessionAdapter(private_fallback="private", unknown_fallback="unknown")
        except Exception:                 # noqa: BLE001
            _session = None
        return HostShell(pkg=pkg, events=adapter.events, session=_session)
    # ---- ② 旧树回退：`game.commands` 的 `Main` Mixin 汇编（删壳前）----
    # 插件宿主类 `Main` 的 MRO（`main.py:285`）：按声明序多继承全部命令 Mixin
    # （与插件自己的 `Main` 逐位同序；不 import `main.py`：它顶部 `from astrbot.api import star`
    #  + `AstrMain` 注册壳属平台面，试玩不需要）。
    names = ("PlayerCmds", "WorldCmds", "CombatCmds", "EconomyCmds", "SocialCmds", "MiscCmds",
             "InstanceCmds", "GmCmds", "ExplorationCmds", "JobGuideCmds", "CollectionCmds",
             "WeeklyCmds", "TowerCmds", "EventMenuCmds")
    cmds = importlib.import_module("game.commands")
    bases = tuple(getattr(cmds, n) for n in names if hasattr(cmds, n))
    shell_cls = type("B20PlayShell", bases, {})
    shell = shell_cls()
    try:
        from saintess_engine.session import SessionAdapter
        shell._session = SessionAdapter(private_fallback="private", unknown_fallback="unknown")
    except Exception:                     # noqa: BLE001
        pass
    return shell


def run(payload: dict) -> int:
    pkg_dir = payload.get("pkg_dir") or PKG_DIR
    host_root = payload.get("host_root") or HOST_ROOT
    engine_root = payload.get("engine_root") or FW_ROOT
    if not pkg_dir or not os.path.isdir(pkg_dir):
        emit({"ok": False, "stage": "load", "message": "包目录不存在：%s" % pkg_dir})
        return 0
    if not os.path.isfile(os.path.join(pkg_dir, "game.json")):
        emit({"ok": False, "stage": "load", "message": "不是游戏包（缺 game.json）：%s" % pkg_dir})
        return 0
    db = _setup_db(payload)
    _setup_paths(pkg_dir, host_root, engine_root)
    # ★ W2a（2026-09-15）：包清单声明了 `bind`（`content/facade.py::bind_host`）⇒ 引擎在
    #   import 包命令模块**之前**要拿到注入面。真·宿主能力只有四类：库路径 / 时钟 /
    #   日志 / 流水 sink（发奖实现住在包内 `content/reward.py`，扇出里自解析）。
    #   ① 的插件装配（`game.commands`）仍在前面：它按平台口径注入宿主替身口（首绑优先）。
    #   ★ 时钟**必须与 B20 的「墙钟钉死」同刻**：`host.boot()` 会在 `_freeze_clock()` 之后
    #     再跑一次 `bind_host` —— 若这里给 `time.time`，会把冻结值重新拨回真墙钟，
    #     对拍假红（实测：`created_at` 逐秒漂移）。
    _clock_raw = payload.get("clock") or os.environ.get("B20_CLOCK") or ""
    try:
        _clock_fixed = float(_clock_raw) if _clock_raw not in (None, "") else None
    except (TypeError, ValueError):
        _clock_fixed = None
    inject = {"db_path": db,
              "clock": (lambda _ts=_clock_fixed: _ts) if _clock_fixed is not None else time.time,
              "log": _PlayLog(), "tlog": _PlayTLog()}

    # ---- ① 插件宿主面（宿主替身口；缺 → 包内数据链会 fail-closed）----
    # ★ 顺序铁律（实测得出的硬约束）：包内 `content/commands.py` 的命令表**只能在宿主
    #   替身口注入完成之后**才 import 得动 —— 它模块级就 `import content.cmds_*.py`，而那些
    #   文件模块级即读 `economy_host._HostRef("_shop_svc")`（未注入 → RuntimeError）。
    #   故这里先按**平台插件自己的装配顺序** import `game.commands`（各 Mixin 模块级
    #   `_EH.bind_host(...)` / `_WC.bind_host(...)` / `_PC.bind_host(...)` …），
    #   之后的 `load_package` / `host.boot()` 才能拿到 194 条处理器。
    try:
        game = _import_host(host_root)
        mods = _import_host_commands(host_root) if game is not None else []
    except Exception:
        emit({"ok": False, "stage": "host", "message": "宿主插件装配失败（game.commands 装配入口抛异常）",
              "traceback": traceback.format_exc()})
        return 0

    # ---- ② 引擎包加载器（官方口径）----
    try:
        from saintess_engine import package as pkg_loader
        info = pkg_loader.load(pkg_dir)
        if not info.get("ok"):
            emit({"ok": False, "stage": "load", "message": "游戏包装配失败",
                  "traceback": "\n".join(info.get("errors") or [])})
            return 0
        from saintess_engine.host import load_package   # 包对象（审计/摘要用；与 Host.boot 同一个）
        primary = load_package(pkg_dir, inject=inject)
        primary.install_engine()
    except Exception:
        emit({"ok": False, "stage": "load", "message": "游戏包装配失败",
              "traceback": traceback.format_exc()})
        return 0

    if payload.get("audit"):
        # 覆盖率审计：逐 key 回报「声明 / 处理器 / 解析到的可调用」——不跑 handler。
        decls = primary.command_declarations()
        rows = []
        for key in sorted(decls):
            entry = dict(primary.command_handlers().get(key) or {})
            ref = entry.get("handler")
            fn = primary.resolve_handler(ref) if ref is not None else None
            rows.append({"key": key, "has_handler": bool(entry),
                         "resolved": bool(fn), "guards": list(entry.get("guards") or [])})
        emit({"ok": True, "stage": "audit", "count": len(rows),
              "declared": len(decls), "handlers": len(primary.command_handlers()),
              "resolved": sum(1 for r in rows if r["resolved"]),
              "rows": rows})
        return 0

    # ---- ③ 宿主运行时 ----
    try:
        from saintess_engine.host import Host, load_package
        from saintess_engine.session import SessionAdapter
        from saintess_engine import version as _V
    except Exception:
        emit({"ok": False, "stage": "engine", "message": "引擎 import 失败",
              "traceback": traceback.format_exc()})
        return 0

    # 存档表：包内 `content.persistence` 只吃注入句柄（库路径 + 连接骨架），建表由
    # `init_db()` 触发（= 插件 `game.db.init_db()` 的同源口径，同一个函数对象）。
    try:
        from content.persistence import init_db as _init_db
        _init_db()
    except Exception:
        emit({"ok": False, "stage": "load", "message": "存档库初始化失败（content.persistence.init_db）",
              "traceback": traceback.format_exc()})
        return 0

    req = ""
    try:
        with open(os.path.join(pkg_dir, "game.json"), encoding="utf-8") as f:
            req = str((json.load(f) or {}).get("engine") or "")
    except Exception:                     # noqa: BLE001
        req = ""
    ok, note = _V.check(req)
    if not ok:
        emit({"ok": False, "stage": "version", "message": note})
        return 0

    seed = payload.get("seed")
    try:
        seed_val = float(seed) if seed is not None else 1.0
    except Exception:                     # noqa: BLE001
        seed_val = 1.0
    random.seed(seed_val)

    # 墙钟钉死（可选）：`B20_CLOCK=<unix ts>` / payload["clock"] —— 对拍与复现用。
    # （值已在注入面构造处解析成 `_clock_fixed`；这里把**模块级墙钟读取点**也钉死。）
    # ★ 必须在 `host.boot()` 之前跑一次：boot 会经 `bind_host` 再注入时钟句柄，
    #   提前冻住可保证注入面拿到的是同刻值。
    if _clock_fixed is not None:
        try:
            _freeze_clock(_clock_fixed)
        except Exception:                 # noqa: BLE001
            pass

    uid = str(payload.get("uid") or "u1")
    group_id = str(payload.get("group_id") or "g1")
    adapter = PlayAdapter(uid, group_id, seed_val)
    host_cls = _make_host_class()
    host = host_cls(adapter, pkg_dir, seed=seed_val, id_key="qq_id", inject=inject)
    try:
        pkg_obj = host.boot()
    except Exception:
        emit({"ok": False, "stage": "load", "message": "Host.boot() 失败",
              "traceback": traceback.format_exc()})
        return 0

    # ★ 2026-09-15 修（对拍态差根因，见 out/W-CLEANUP.md ③）：**物化后再冻一次时钟**。
    #   上面那次 `_freeze_clock` 跑在 `host.boot()` 之前，而 `load_package` **不**物化命令模块
    #   （处理器按名惰性解析，`host.boot()`/首次派发时才 import）⇒ boot 之后才 import 的
    #   `content.cmds_misc` 拿到的是**真** `datetime` 模块，`datetime.date.today()` = 真墙钟
    #   （实测 2026-09-15）；而 QQ 侧（`b20_qq_ref.py`）是 **boot() 之后**才冻，`cmds_misc`
    #   已被 patch ⇒ 拿到 1700000000 → 2023-11-15。两条签到派生列
    #   （`signin.last_date` / `event_state.daily_fortune_<gid>_<qid>`）因此逐字节不同 ⇒
    #   对拍里 `签到` 的 state_sha 差，`见闻录` 只是继承上一条的库状态（文本逐字节相同）。
    #   `_freeze_clock` 幂等（只替换仍指向 stdlib 的模块属性）⇒ 再冻一次 = 与 QQ 侧同序。
    if _clock_fixed is not None:
        try:
            _freeze_clock(_clock_fixed)
        except Exception:                 # noqa: BLE001
            pass

    handlers = len(host.handlers)
    declared = len(host.commands)
    try:
        total = len(pkg_loader.load(pkg_dir).command_declarations())
    except Exception:                     # noqa: BLE001
        total = declared

    # ★ 终态装配：把**已物化的包对象**交给壳（终态壳的存档半边 = 包内 `persistence`）
    shell = _make_platform_shell(host_root, adapter, seed_val, pkg=pkg_obj)
    if shell is None:
        shell = PlayShell(host, SessionAdapter(private_fallback="private", unknown_fallback="unknown"),
                          adapter.events)
    host.shell = shell
    adapter.shell = shell

    # ---- ④ 逐条命令 ----
    cmds = list(payload.get("commands") or [])
    lines = []
    ran = 0
    for i, text in enumerate(cmds):
        text = str(text)
        adapter.said = []
        adapter.events = []
        ctx = {"uid": uid, "group_id": group_id, "text": text,
               "raw": PlayEvent(text, group_id, uid)}
        rec = {"i": i, "text": text, "key": "", "segments": [], "message": "", "actions": [],
               "state_sha": "", "ok": True}
        try:
            host.handle(ctx)
            rec["segments"] = list(adapter.said)
            rec["message"] = "\n".join(str(x) for x in adapter.said if x not in (None, ""))
            rec["actions"] = list(adapter.events)
            spec = host.declared_hit(text)
            rec["key"] = str(getattr(spec, "key", "") or "")
            rec["state_sha"] = _state_sha(adapter)
            # 对拍基准：key + **已渲染的一条消息**（宿主 `_host_bridge.run` 的 join 口径）
            # + 平台动作 + 状态指纹，拼一条（LF 连接，逐字节）
            rec["digest"] = _sha("\n".join(
                [rec["key"], rec["message"]]
                + [_dump(a) for a in rec["actions"]] + [rec["state_sha"]]))
            ran += 1
        except Exception as e:            # noqa: BLE001
            rec["ok"] = False
            rec["error"] = "%s: %s" % (type(e).__name__, e)
            rec["traceback"] = traceback.format_exc()[-3000:]
            rec["digest"] = ""
        lines.append(rec)
        emit(rec)

    emit({"ok": True, "stage": "done", "pkg": pkg_obj.id, "db": db,
          "count": total, "declared": declared, "handlers": handlers, "ran": ran,
          "host_modules": len(mods), "seed": seed_val, "uid": uid, "group_id": group_id,
          "commands_sha": _sha("\n".join(str(c) for c in cmds)),
          "digests_sha": _sha("\n".join(r.get("digest", "") for r in lines))})
    return 0


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:                     # noqa: BLE001
        payload = {}
    return run(payload if isinstance(payload, dict) else {})


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:                     # noqa: BLE001
        emit({"ok": False, "stage": "crash", "message": "子进程异常",
              "traceback": traceback.format_exc()})
        sys.exit(1)
