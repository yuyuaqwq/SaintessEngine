# -*- coding: utf-8 -*-
"""宿主运行时 · `Host`（装配 + 会话循环 + 命令通道 + 战斗驱动 + 落档）。

**归属**：这是「通用那一半」——任何平台、任何包的宿主都要做的编排。平台三函数
（`recv` / `load_player`+`save_player` / `say`）与可选钩子由**适配器**提供，本模块不碰平台 SDK。

三条纪律
--------
1. **本模块零游戏知识**：不挑怪、不算数值、不写文案（文案属内容，包内渲染好交出来）。
2. **只依赖包契约**：`game.json.entry` 的两个函数 + 包内可选半边
   （`bridge` / `settlement` / `loot` / `tlog_collect` / `flow` / `effects` / **`commands`** / **`guards`**）。
3. **接人（平台 / DB / 时间 / 流水落库）全在适配器**：本模块通过钩子调用，没有就走默认（不给也能跑）。

命令通道（2026-09-14 起）
------------------------
声明在包（`content/data/commands.json`：正则 / desc / category / order / usage / guards），
**处理器也在包**（`content/commands.py::COMMANDS`：`:class:`Env` → `list[str]`）。
本模块只做四件事：命中声明 → 跑守卫（内置名 + 包侧 `hook:*`）→ 构造 `Env` → 调处理器 + 投递回话。
包没给处理器（纯数据包 / 尚未实现）→ 回显声明（**降级说明**，不是兼容壳）。
"""
from __future__ import annotations

import random
import time

from ..battle.battle import Battle
from ..command.registry import CommandRegistry
from ..tlog import KindTable, MemorySink, TLog
from .env import Env, run_guards
from .outcome import BattleOutcome, Scenario, StandIns
from .package import Package, PackageError, load_package

#: 默认「没有角色档」的拦截文案（中性，**不是**游戏文案；宿主/包可覆盖）
DEFAULT_REGISTER_HINT = "未找到你的角色档 —— 请先创建角色。"
#: 默认「不在战斗中」的拦截文案（同上）
DEFAULT_BATTLE_HINT = "你现在不在战斗中。"

#: 新玩家初始档的宿主侧最小键（真正的初始档属内容：包给了 `initial_save` 就用包里的）
MINIMAL_SAVE_KEYS = ("uid", "name", "level")

DEFAULTS_HINTS = {
    "clock": "time.time()",
    "rng": "系统随机（不可复现）",
    "on_tlog": "丢弃（流水不落库）",
    "load_blob": "进程内 dict（重启即失）",
    "on_event": "无（宿主不记账）",
}


class Host:
    """宿主运行时：装配 + 会话循环 + 命令通道 + 战斗驱动 + 落档。

    参数
    ----
    adapter     : 三函数适配器（`recv` / `load_player` / `save_player` / `say` + 可选钩子）
    package_dir : 包目录（`game.json` 所在）
    scenario    : 演示战斗的输入（`Scenario`；包补齐流程后可改为问包要）
    prefix      : 宿主自己的管理命令前缀（缺省 `/`）
    seed        : 固定随机种子（同种子可复现同一场；None = 走适配器 `rng` 钩子/系统随机）
    id_key      : 玩家档里「平台身份」那个键名（**平台相关 → 由调用方给**，缺省 `uid`）
    register_hint / battle_hint : 内置守卫的拦截文案（属内容；此处只给中性默认）
    battle_check: `(uid, group_id) -> bool`，「在不在战斗中」的查询（宿主给；不给则 `battle` 守卫不拦）
    texts_domain: 包内文案域名（缺省 `texts`；读不到 → `Env.texts=None`，包内自行兜底）
    """

    def __init__(self, adapter, package_dir, *, scenario=None, prefix="/", seed=None,
                 idle_sleep=0.05, echo_battle=True, tlog_limit=500, id_key="uid",
                 register_hint=DEFAULT_REGISTER_HINT, battle_hint=DEFAULT_BATTLE_HINT,
                 battle_check=None, texts_domain="texts", inject=None):
        self.adapter = adapter
        self.package_dir = package_dir
        self.scenario = scenario or Scenario()
        self.prefix = prefix or "/"
        self.seed = seed
        self.idle_sleep = float(idle_sleep)
        self.echo_battle = bool(echo_battle)
        self.tlog_limit = int(tlog_limit)
        self.id_key = str(id_key or "uid")
        self.register_hint = str(register_hint or "")
        self.battle_hint = str(battle_hint or "")
        self.battle_check = battle_check
        self.texts_domain = str(texts_domain or "texts")
        #: **宿主注入面**：一个 dict，两处用 —— ① 加载期交给包声明的 `bind` 钩子（在 import
        #: 包命令模块之前）② 每轮消息并入 `Env.state`。引擎**不解释**其键值（零游戏知识）。
        self.inject: dict = dict(inject or {})
        self.pkg: Package | None = None
        self.commands = CommandRegistry(name="host")
        self.handlers: dict = {}          # 包内命令处理器表（content/commands.py::COMMANDS）
        self.texts = None                 # 包内文案表（content/data/texts.json → TextTable）
        self._messages = 0
        self._blobs: dict = {}
        self._tlog_sink = None

    # ------------------------------------------------------------ 装配
    def boot(self) -> Package:
        """加载包 → 装引擎 → 装载「声明 + 处理器 + 守卫钩子 + 文案表」。"""
        self.pkg = load_package(self.package_dir, inject=self.inject or None)
        self.pkg.install_engine()
        try:
            self.commands = CommandRegistry(name=self.pkg.id).load(self.pkg.command_declarations())
        except Exception:                                        # noqa: BLE001
            self.commands = CommandRegistry(name=self.pkg.id)
        self.handlers = dict(self.pkg.command_handlers())
        self.texts = self._load_texts()
        return self.pkg

    def _load_texts(self):
        """包内文案表（读不到 → None：文案是可选半边，缺了由包内自行兜底）。"""
        data = self.pkg.domain(self.texts_domain) if self.pkg else {}
        if not isinstance(data, dict) or not data:
            return None
        try:
            from ..text import TextTable
            return TextTable.from_data(data, name=self.pkg.id)
        except Exception:                                        # noqa: BLE001
            return None

    # ------------------------------------------------------------ 可选钩子
    def _hook(self, name: str):
        fn = getattr(self.adapter, name, None)
        return fn if callable(fn) else None

    def clock(self) -> float:
        fn = self._hook("clock")
        return float(fn()) if fn else time.time()

    def seed_now(self, seed=None):
        """本场的随机种子：显式 > 适配器 `rng()` 钩子 > None（系统随机，不可复现）。

        引擎用模块级随机流，所以宿主取到种子后 `random.seed(...)` —— 这就是适配器
        `rng()` 钩子「同种子复现一场」的落地点（引擎零改动）。
        """
        if seed is not None:
            value = float(seed)
            random.seed(value)
            return value
        fn = self._hook("rng")
        if fn is None:
            return None
        value = float(fn().random())
        random.seed(value)
        return value

    def blob(self, key: str):
        """额外持久化（组队/公会/世界状态这类「不是单玩家档」的数据）。"""
        fn = self._hook("load_blob")
        if fn is not None:
            return fn(key)
        return self._blobs.get(key)

    def put_blob(self, key: str, value) -> None:
        fn = self._hook("save_blob")
        if fn is not None:
            fn(key, value)
        else:
            self._blobs[key] = value

    def tlog_write(self, kind: str, **fields) -> None:
        """流水出口（适配器 `on_tlog` 的实现；没有就丢弃 —— 可选钩子的约定）。"""
        fn = self._hook("on_tlog")
        if fn is None:
            return
        try:
            fn({"kind": kind, **fields})
        except Exception:                                        # noqa: BLE001
            pass

    # ------------------------------------------------------------ 三函数的宿主调用点
    def recv(self):
        return self.adapter.recv()

    def load_player(self, uid: str):
        return self.adapter.load_player(uid)

    def save_player(self, uid: str, data: dict) -> None:
        self.adapter.save_player(uid, data)

    def say(self, to: dict, text: str) -> None:
        """回话出口：**text 已是玩家可见字符串**（渲染属内容，投递属宿主）。"""
        if text:
            self.adapter.say({"uid": str(to.get("uid") or ""),
                              "group_id": to.get("group_id")}, str(text))

    # ============================================================
    # 命令通道（声明在包 → 守卫 → Env → 包内处理器 → 回话）
    # ============================================================
    def builtin_guards(self) -> dict:
        """引擎认识的**内置守卫实现**（名固定：`player` / `battle`）。"""
        return {"player": self._guard_player, "battle": self._guard_battle}

    def _guard_player(self, env: Env):
        """玩家档必须存在（否则拦截，文案由调用方给）。"""
        if not env.player:
            return self.register_hint or DEFAULT_REGISTER_HINT
        return None

    def _guard_battle(self, env: Env):
        """必须在战斗中（`battle_check` 不给 → 不拦）。"""
        if self.battle_check is None:
            return None
        try:
            ok = bool(self.battle_check(env.uid, env.group_id))
        except Exception:                                        # noqa: BLE001
            ok = False
        return None if ok else (self.battle_hint or DEFAULT_BATTLE_HINT)

    def build_env(self, key: str, spec, ctx: dict, player: dict, *, raw=None) -> Env:
        """构造一条消息的执行环境（字段契约见 `Env`）。"""
        ctx = ctx or {}
        uid = str(ctx.get("uid") or "")
        env = Env(
            key=str(key or ""),
            uid=uid,
            group_id=str(ctx.get("group_id") or ""),
            text=str(ctx.get("text") or "").strip(),
            raw=(ctx.get("raw") if raw is None else raw),
            player=player if isinstance(player, dict) else {},
            clock=self.clock,
            rng=random,                                   # 模块级流（`seed_now()` 设种子 → 可复现）
            tlog=self.tlog_write,
            texts=self.texts,
            blob_load=self.blob,
            blob_save=self.put_blob,
            state={"spec": spec, "prefix": self.prefix,
                   "package": (self.pkg.id if self.pkg else ""), **self.inject},
        )
        # 两段式：`save` 存的是 **env.player 的当前值**（处理器可整体替换 player 对象）
        env.save = lambda: self.save_player(env.uid, env.player)
        return env

    def invoke(self, spec, ctx: dict, player: dict, *, raw=None) -> list:
        """把一条命中的声明派给**包内处理器**：守卫 → Env → 处理器 → 回话段。

        返回 `list[str]`（已渲染文本段）。包没给处理器 → 回显声明（降级说明）。
        """
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
        blocked = run_guards(guards, env, builtin=self.builtin_guards(),
                             hooks=(self.pkg.guard_hooks() if self.pkg else {}))
        if blocked:
            return [blocked]
        return self._as_replies(fn(env))

    @staticmethod
    def _as_replies(out) -> list:
        """把处理器返回值规整成 `list[str]`（None / str / 可迭代 / 生成器都收）。"""
        if out is None:
            return []
        if isinstance(out, str):
            return [out] if out else []
        if isinstance(out, (list, tuple, set)):
            return [str(x) for x in out if x not in (None, "")]
        if hasattr(out, "__iter__") and not isinstance(out, (dict, bytes)):
            return [str(x) for x in out if x not in (None, "")]
        return [str(out)]

    def declared_hit(self, text: str):
        """按**可见**声明路由匹配（不可见声明 = 平台内部 gate，不是玩家指令）。

        口径与注册表**同源、只有一份**：直接调 `CommandRegistry.first_hit(text, visible_only=True)`
        —— `priority` 降序、同值按注册序。此前这里按 `visible()`（= `order` 升序）逐条试，
        与 `hit()` 的口径不一致（同一份包在编辑器试玩与引擎注册表下可能命中不同声明，B19e 修）。
        本方法只做「去空白 + 取首条」，**不再自带遍历/排序**（那正是缺口的成因）。
        容错同旧实现：坏声明不阻断整条命令通道（非法正则已由匹配层容忍）。
        """
        text = (text or "").strip()
        if not text:
            return None
        try:
            return self.commands.first_hit(text, visible_only=True)
        except Exception:                                        # noqa: BLE001
            return None

    def route(self, ctx: dict, player: dict, text: str) -> list:
        """路由：宿主前缀 → 管理命令；否则包内声明 → **包内处理器**。返回回话（已渲染文本段）。"""
        text = str(text or "").strip()
        if text.startswith(self.prefix):
            return self.host_command(text[len(self.prefix):].strip(), ctx, player)
        spec = self.declared_hit(text)
        if spec is not None:
            return self.invoke(spec, ctx, player)
        if not text:
            return []
        return ["（没有命中包内任何指令声明；输入 %shelp 看宿主命令）" % self.prefix]

    def declared_echo(self, spec) -> list:
        """声明回显（**降级说明**：包没给处理器时，把声明本身告诉玩家/开发者）。"""
        usage = getattr(spec, "usage", "") or ""
        desc = getattr(spec, "desc", "") or ""
        return ["【%s】(包内声明) %s" % (getattr(spec, "key", "?"), desc),
                "用法：%s" % (usage or "—"),
                "（该声明未提供处理器：包内 content/commands.py 里没有它的 handler）"]

    # ------------------------------------------------------------ 战斗
    def run_battle(self, player: dict, enemies: list, *, event_state=None, seed=None,
                   btype="monster") -> BattleOutcome:
        """开一场（构造半边在包 `bridge`）→ 装内容 → 跑完 → 战斗末段（流水/掉落/结算）。

        顺序即契约顺序：`install_engine()` → 开战仪式 → `build_sides` → `apply_game_content`
        → 首动前设种子 → `Battle` → `auto_run`。
        """
        pkg = self.pkg or self.boot()
        bridge = pkg.optional_submodule("bridge")
        stubs: list = []
        if bridge is None and pkg.entry_fn("build_sides") is None:
            raise PackageError("包 %s 既无 content/bridge.py 也无 entry.build_sides —— 无法开战" % pkg.id)
        build = pkg.entry_fn("build_sides") or bridge.build_sides
        prepare = pkg.entry_fn("prepare_player_for_battle") or getattr(
            bridge, "prepare_player_for_battle", None)

        event_state = dict(event_state or {})
        player = player if isinstance(player, dict) else {}
        if prepare is not None:
            prepare(player, None, event_state)        # 开战仪式（纯数据搬运，见包内桥 docstring）
        sides = build(player, list(enemies or []))
        for actor in list(sides.get("player") or []) + list(sides.get("enemy") or []):
            pkg.apply_game_content(actor)             # 内容装配（幂等；契约唯一入口）

        events: list = []
        hits: list = []

        def observe(_battle, evt, ctx, _logs):
            events.append(evt)
            if evt in BattleOutcome.HIT_EVENTS:
                hits.append({"event": evt, "by": str((ctx or {}).get("actor", {}).get("uid", "")),
                             "to": str((ctx or {}).get("target", {}).get("uid", "")),
                             "dmg": int((ctx or {}).get("dmg") or 0),
                             "crit": False})
            elif evt == "crit" and hits:
                hits[-1]["crit"] = True
            bookkeeping = self._hook("on_event")
            if bookkeeping is not None:
                bookkeeping(evt, {"battle": btype, **{k: v for k, v in (ctx or {}).items()
                                                      if isinstance(v, (str, int, float, bool))}})

        real_seed = self.seed_now(seed)
        battle = Battle(btype=btype, sides=sides, on_event=observe)
        tlog = self._attach_tlog(battle, player, enemies, real_seed)
        logs: list = []
        battle.auto_run(logs)
        out = BattleOutcome(result=str(battle.result or ""), damage=sum(h["dmg"] for h in hits),
                            hits=hits, events=events, log=logs, stubs=stubs,
                            elapsed=float(getattr(battle, "_now", 0.0) or 0.0))
        self._close_tlog(tlog, battle, out)
        self._post_battle(out, player, enemies)
        self._settle(out, player, (enemies or [{}])[0], sides)
        self.sync_player(player, sides)
        return out

    def sync_player(self, player: dict, sides: dict) -> dict:
        """战斗内 actor → 玩家档的**回写半边**（属宿主侧契约；包内桥只搬构造半边）。

        只做字段搬运，零数值计算。写回后由调用方 `save_player` 落盘。
        """
        actors = sides.get("player") or []
        actor = actors[0] if actors else None
        if not isinstance(actor, dict):
            return player
        for key in ("hp", "mp", "max_hp", "max_mp", "effects", "shields", "cooldown",
                    "charging", "defending", "ct", "act_count"):
            if key in actor:
                player[key] = actor[key]
        return player

    # ---- 战斗末段：流水（可选钩子）------------------------------------
    def _attach_tlog(self, battle, player, enemies, seed):
        hook = self._hook("on_tlog")
        if hook is None:
            return None
        collector_mod = self.pkg.optional_submodule("tlog_collect")
        if collector_mod is None:
            return None
        table = KindTable.from_data(self.pkg.domain("tlogs"), name=self.pkg.id)
        sink = MemorySink(limit=self.tlog_limit)
        tlog = TLog(sinks=[sink], kinds=table)
        collector = collector_mod.BattleTLog(tlog=tlog, name="%s" % self.pkg.id)
        collector.attach(battle, btype="monster", seed=seed, player=player, enemies=list(enemies or []))
        self._tlog_sink = sink
        return collector, tlog

    def _close_tlog(self, handle, battle, out) -> None:
        if not handle:
            return
        collector, tlog = handle
        try:
            collector.on_end(battle, result=battle.result)
        except Exception:                                        # noqa: BLE001
            pass
        hook = self._hook("on_tlog")
        try:
            tlog.flush()
            for record in self._tlog_sink.read_records():
                hook(record.to_dict())
        except Exception:                                        # noqa: BLE001
            pass

    # ---- 战斗末段：结算（包内 settlement，策略半边）------------------
    def _settle(self, out: BattleOutcome, player: dict, monster, sides: dict) -> None:
        """结算：调包内 `settlement` 的策略半边，拿回**计划**（经验/金币/入包 grants）。

        宿主只给「替身」（它自己的存储没有的 → 中性值；包内键清单在包模块），
        并把引擎已挂的面板 hook 算好的面板塞进去。跑不出来就**记桩**（不编数字）。
        """
        mod = self.pkg.optional_submodule("settlement")
        if mod is None or not isinstance(monster, dict):
            self._stub_missing(out, "settlement")
            return
        fn = getattr(mod, "victory_settle_plan", None) or getattr(mod, "settle", None)
        if not callable(fn):
            out.stubs.append("settlement: 包内 content/settlement.py 无 victory_settle_plan/settle")
            return
        mon = dict(monster)
        mon.setdefault("lv", mon.get("level", 1))
        io = StandIns(self.pkg, self, player, uid=str(player.get("uid") or ""))
        try:
            plan = fn(player, mon, out.result or "victory", io) or {}
        except Exception as e:                                   # noqa: BLE001
            out.stubs.append("settlement: 已接但调用未完成（%r）—— 缺的替身见包模块" % e)
            return
        out.settlement = {"exp": plan.get("exp"), "gold": plan.get("gold"),
                          "exp_after": plan.get("exp_after"),
                          "lines": len(plan.get("lines") or []),
                          "grants": len(plan.get("grants") or [])}

    def _stub_missing(self, out: BattleOutcome, name: str) -> None:
        out.stubs.append("%s: 包内 content/%s 未进包 → 留桩" % (name, name))

    # ---- 战斗末段：掉落（包内 loot）---------------------------------
    def _post_battle(self, out: BattleOutcome, player: dict, enemies: list) -> None:
        loot_mod = self.pkg.optional_submodule("loot")
        if loot_mod is None:
            out.stubs.append("loot: 包内 content/loot.py 缺失 → 未掉宝")
        else:
            for req in self.scenario.rewards:
                pool = str((req or {}).get("pool") or "")
                if not pool:
                    continue
                ctx = dict((req or {}).get("ctx") or {})
                try:
                    out.loot.extend(list(loot_mod.roll(pool, ctx) or []))
                except Exception as e:                           # noqa: BLE001
                    out.stubs.append("loot: 池 %s 抽取异常 %r" % (pool, e))
            if not self.scenario.rewards:
                out.stubs.append("loot: 场景未给掉落池请求（池 key 属内容策略）→ 未掉宝")

    # ------------------------------------------------------------ 一条消息
    def handle(self, ctx: dict) -> None:
        """处理一条消息：认人 → 读档 → 路由 → 回话。

        **落档由处理器自己负责**：改完档调 `env.save()`（引擎契约第 6 条）。引擎**不代劳** ——
        历史上这里每条消息无条件整档回写，与契约文档矛盾（且与宿主"按需存 + 剔身份字段"的
        既有实现不一致）。
        """
        ctx = ctx or {}
        uid = str(ctx.get("uid") or "")
        to = {"uid": uid, "group_id": ctx.get("group_id")}
        text = str(ctx.get("text") or "").strip()
        player = self.load_player(uid)
        if player is None:
            # 新玩家：先造初始档（内容给 `initial_save`；它显式返回空 = 「本包要求先注册」）
            player = self.pkg.initial_save(uid, ctx, id_key=self.id_key) or {}
            if not isinstance(player, dict):
                player = {}
            if player:
                # **建档是引擎级副作用**：新档必须落库一次，否则"这个人是新玩家"永远是瞬时判断。
                # 注意与"每条消息整档回写"的区别 —— 后者已删（落档归处理器，见 handle 文档串）。
                self.save_player(uid, player)
        replies = self.route(ctx, player, text)
        for part in replies:
            self.say(to, part)

    def host_command(self, name: str, ctx: dict, player: dict) -> list:
        """宿主自己的管理命令（平台侧，与包无关）。子类/适配器可扩展。"""
        word = (name.split() or [""])[0].lower()
        if word in ("help", "帮助"):
            return self.help_text()
        if word == "quit":
            return []
        spec = self.commands.get(name)
        if spec is not None:
            return self.declared_echo(spec)
        return ["未知宿主命令：%s（%shelp）" % (name, self.prefix)]

    def help_text(self) -> list:
        visible = self.commands.visible()
        return ["宿主：包 %s（%d 域 / %d 条指令声明 / %d 条已实现处理器）"
                % (self.pkg.id, len(self.pkg.domains), len(self.commands), len(self.handlers)),
                "宿主命令：%shelp · %squit · %s<包内指令 key>" % ((self.prefix,) * 3),
                "可选钩子：%s" % "、".join("%s=%s" % (k, ("适配器已给" if self._hook(k) else DEFAULTS_HINTS[k]))
                                          for k in DEFAULTS_HINTS)]

    # ------------------------------------------------------------ 循环
    def serve_forever(self, max_messages=None, idle_timeout=None) -> int:
        """会话循环：recv（None = 没有新消息，自旋）→ handle。

        停机条件：适配器 `should_stop()`（扩展面，如 CLI 收到 EOF）/ `max_messages` /
        `idle_timeout` 秒没有新消息。返回处理过的消息条数。
        """
        last = time.time()
        while True:
            if max_messages is not None and self._messages >= int(max_messages):
                break
            stop = self._hook("should_stop")
            if stop is not None and stop():
                break
            ctx = self.recv()
            if ctx is None:
                if idle_timeout is not None and (time.time() - last) >= float(idle_timeout):
                    break
                time.sleep(self.idle_sleep)
                continue
            last = time.time()
            self._messages += 1
            self.handle(ctx)
        return self._messages
