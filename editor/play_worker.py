# -*- coding: utf-8 -*-
"""编辑器「试玩」· 子进程侧 —— 在本进程里装配引擎 + 游戏包 + **宿主面**，跑一条条命令。

入参（stdin JSON）
------------------
    {
      "pkg_dir":   "<游戏包目录：game.json 所在>",     # 必填（也读环境变量 FW_PKG_DIR）
      "host_root": "<宿主插件目录：game/ 的父目录>",   # 可选（也读 B20_HOST_ROOT）——**只**为
                                                        # 「与 QQ 侧逐字节对拍」用；缺省空 = 纯试玩
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
`Function` 句柄 `bind_host(db=…, C=…)`）：这些**不是**引擎 host 契约的一部分。
★ T7 第 3 轮（2026-09-20 · 编辑器试玩「脱宿主」）之后，它们由**引擎包加载器 + 包清单声明**
（`bind`）在装配期注入 —— **QQ 插件不再参与装配**（旧 `import game` / `game.commands` 两处
实测皆空转，已删）。所以本 worker 的装配顺序：

    ① 引擎根 → sys.path（**只在**给了 `host_root` 时才额外挂插件根，见下「对拍通路」）
    ② `GWEN_GAME_DB` → 独立库（缺省 <db_dir>/play.db；绝不碰真仓任何库）
    ③ `saintess_engine.host.load_stack(pkg_dir, inject=…)` + `install_engine()`（引擎官方包
       加载器）—— ★ W2a：包声明了 `bind`，注入面（库路径/时钟/日志/流水 sink）从这里给
    ④ `PlayHost(Host)` 覆写 `build_env`：把 `env.state["shell"]` 换成壳
       —— 包内实现体经它做宿主取件（`_uid/_player/_strip_cmd/_page_items/_tip/_broadcast`…）
    ⑤ 逐条 `host.handle(ctx)` → 收 `say()` 段 → 打印 JSON 行

壳（`env.state["shell"]`）**恒为引擎侧** `editor/play_shell.py::PlayShell`：引擎
`ShellBase`（取件管道 / 包内内容半边转发 / 环境位）+ 试玩平台半边（广播·通知落记录，
身份面 fail-closed）。**只有显式给了 `host_root`** 才换成插件 `host.shell.HostShell`
（同继承 `ShellBase`）—— 那是**对拍专用**通路（「无宿主 vs 有宿主」逐字节比），
编辑器正常跑不走它。旧的手搓 stub（33 个方法，缺 `__getattr__` 动态解析 ⇒ `背包` 必红）
已删。
"""
from __future__ import annotations

import hashlib
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
# 引擎注入面（★ W2a：包清单声明了 `bind` ⇒ load_stack / Host.boot 必须给 inject）
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
# 宿主（引擎 Host 的试玩覆写：只加「注入宿主壳」一件事）
# ============================================================
def _make_host_class():
    """运行期派生引擎 `Host`（**覆写点只剩一个**：`build_env` 塞 `state["shell"]`）。

    ★ W-B18-L3c（2026-09-19 收口）：`async def` handler 的分支**已在引擎**
    （`saintess_engine/host/runtime.py::Host._resolve_async` / `_run_async`）——awaitable 与
    async generator 都在引擎侧跑完再收段，且在「已在事件循环里」时另起线程（不炸
    `loop already running`）、认宿主给的 `async_runner`。原先本处那份「逐字抄一遍
    `invoke` 再补 `asyncio.run`」的覆写已删：三处派生 Host 各抄一份 invoke 正是该缺口
    的成因，缺口既然在引擎里补上了，抄的那份就是纯重复。
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


def _make_host_shell(host_root: str, adapter, pkg=None):
    """**真宿主壳**（插件 `host.shell.HostShell`）—— 只在显式给了 `host_root` 时装配。

    唯一用途：与 QQ 侧**逐字节对拍**（同一份壳 + 同一份包 + 同 seed + 同固定墙钟）。
    编辑器正常跑（`host_root` 缺省为空）用 `editor/play_shell.py::PlayShell`；两者同继承引擎
    `saintess_engine.host.shell.ShellBase`，差异只剩「真平台面」那几个方法（广播 / 通知 /
    停服投递 / 身份映射 / 窥探投递 / 平台例外 `_maint_gate`·`gm_play`·`gm_spy`）。

    ★ 不回退、不静默：宿主根给了却装不起来 ⇒ 直接抛（调用处收成 `stage="host"` 报错），
      不假装成试玩壳 —— 否则「对拍」会退化成「两个试玩壳互相比」的假绿。
    """
    if not host_root or not os.path.isdir(os.path.join(host_root, "game")):
        return None
    from host.shell import HostShell          # 装不起来就抛（调用处报 stage="host"）
    return HostShell(pkg=pkg, events=adapter.events)


def run(payload: dict) -> int:
    pkg_dir = payload.get("pkg_dir") or PKG_DIR
    # host_root 三态（与 `editor/play.py::discover` 同口径）：键在 payload 里 → 以它为准
    # （"" = 显式无宿主）；键缺 → 落环境变量 `B20_HOST_ROOT`。
    host_root = payload.get("host_root")
    if host_root is None:
        host_root = HOST_ROOT
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

    # ---- ① 宿主插件：**已删**（T7 第 3 轮 · 实测两处皆空转）----
    # 旧写法 = `import game` + `game.commands`（据称是「宿主替身口的注入点」）。实测：插件树
    # `game/` 下已无任何 `.py`（只剩 `data/` 与 `*.db`）⇒ `game.commands` 不存在、恒返回 `[]`；
    # 而宿主替身口现在由**引擎包加载器 + 包清单声明**（`bind`）注入，与插件无关。
    # 故整段删除（不留兼容壳）：试玩装配不再依赖任何插件文件。
    mods = []

    # ---- ② 引擎包加载器（官方口径）----
    try:
        from saintess_engine.package import load_stack
        info = load_stack(pkg_dir)
        if not info.get("ok"):
            emit({"ok": False, "stage": "load", "message": "游戏包装配失败",
                  "traceback": "\n".join(info.get("errors") or [])})
            return 0
        from saintess_engine.package import load_stack   # 包对象（审计/摘要用；与 Host.boot 同一个）
        primary = load_stack(pkg_dir, inject=inject)
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
        from saintess_engine.host import Host
        from saintess_engine.package import load_stack
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
    #   上面那次 `_freeze_clock` 跑在 `host.boot()` 之前，而 `load_stack` **不**物化命令模块
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
        total = len(load_stack(pkg_dir).command_declarations())
    except Exception:                     # noqa: BLE001
        total = declared

    # ★ 壳装配：**已物化的包对象**交给壳（壳的存档半边 = 包内 `persistence`）。
    #   缺省 = 引擎试玩壳（`editor/play_shell.py`）；只有给了 `host_root` 才换真宿主壳（对拍通路）。
    try:
        shell = _make_host_shell(host_root, adapter, pkg=pkg_obj)
    except Exception:
        emit({"ok": False, "stage": "host", "message": "宿主壳装配失败（host.shell.HostShell）",
              "traceback": traceback.format_exc()})
        return 0
    if shell is None:
        from editor.play_shell import PlayShell       # 子进程侧才允许 import 引擎
        shell = PlayShell(pkg=pkg_obj, events=adapter.events)
    else:
        mods.append("host.shell")
    host.shell = shell
    adapter.shell = shell

    # ---- ④ 逐条命令 ----
    cmds = list(payload.get("commands") or [])
    lines = []
    ran = 0
    for i, text in enumerate(cmds):
        text = str(text)
        adapter.said = []
        # ★ 2026-09-20（T7-B）：**就地清空**，不是重绑 —— 壳装配时拿到的是同一个 list
        #   对象（`PlayShell(events=adapter.events)` / `HostShell(events=...)`），
        #   重绑后壳仍往**旧表**里记，`list(adapter.events)` 恒为空 ⇒ 平台动作
        #   （广播 / 通知 / 投递）**从未进入对拍**。
        del adapter.events[:]
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
