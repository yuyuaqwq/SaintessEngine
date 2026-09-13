# -*- coding: utf-8 -*-
"""官方宿主骨架 —— 装配 + 会话循环（P5 交付物；契约 `overnight/p5-host-shell-contract.md`）。

这个目录回答一个问题：**第三方拿到一个内容包，写多少代码能跑起来？**
答案 = 三个函数（收消息 / 读档 / 写档 / 回话）。本文件是与游戏无关的那层"壳"：

    加载包 → install_engine → 开一场 → 走完 → 落档 → 回话

平台、存储、时间、流水出口全在适配器里（`adapter_cli.py` / `adapter_template.py`）。

四条纪律（契约 §三）
--------------------
1. **骨架里没有游戏逻辑** —— 通用形状 → 引擎（`saintess_engine/`）；内容 → 包（`game.json` 那个目录）；
   接人（平台 / DB / 时间 / 流水落库）→ 本目录。
2. **只依赖包契约** —— `game.json.entry` 的两个函数（`install_engine()` / `apply_game_content(actor)`）
   + 引擎 `saintess_engine.__all__` 的公开面。
3. **不动现网宿主** —— 本骨架是"同一个包能被两个宿主跑"的证据，不是第三层宿主。
4. **指令处理器不是骨架的活**（长期项）—— 骨架只读包内 `commands.json` 的**声明**做路由，
   并绑定 1 条示例指令（谁绑由宿主给，见 `example_command`）。

接缝纪律（不可谈判，契约 §一②）
--------------------------------
包内代码**只拿普通 dict 进来、只交普通 dict 出去**；序列化 / 并发锁 / 落库 / 迁移全在宿主侧
（本目录 `store_sqlite.py`）。别把 ORM 对象或连接句柄递给包 —— 那会让包重新依赖宿主。

可选钩子（契约 §二）：`clock` / `rng` / `on_tlog` / `load_blob`+`save_blob` / `on_event`
（另加骨架自己的扩展面 `should_stop`，用于优雅停机）。不给也能跑，给了省事。
"""
from __future__ import annotations

import importlib
import json
import os
import random
import sys
import time
from datetime import date


def _ensure_engine_importable() -> None:
    """引擎可导入性：装过（pip/venv）就什么都不做；否则把仓库根放进 `sys.path`。

    本目录是框架仓里的**示例**（`<root>/examples/host-skeleton`），所以找得到 `<root>/saintess_engine`。
    接自己的项目时引擎一般是依赖包，这一段会被跳过 —— 它不是契约的一部分。
    """
    try:
        import saintess_engine  # noqa: F401
        return
    except ImportError:
        pass
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if os.path.isdir(os.path.join(root, "saintess_engine")) and root not in sys.path:
        sys.path.insert(0, root)


_ensure_engine_importable()

from saintess_engine import Battle, CommandRegistry, config as engine_config  # noqa: E402
from saintess_engine import version as engine_version  # noqa: E402

# 包侧数据约定：玩家档里"平台身份"那个键名（包内桥读它；宿主只搬运，不解释平台语义）
ID_KEY = "qq_id"

# 新玩家初始档的**宿主侧最小形状**（真正的初始档属内容：包给了 initial_save 就用包里的）
_MINIMAL_SAVE = ("uid", ID_KEY, "name", "level")

DEFAULTS_HINTS = {
    "clock": "time.time()",
    "rng": "系统随机（不可复现）",
    "on_tlog": "丢弃（流水不落库）",
    "load_blob": "进程内 dict（重启即失）",
    "on_event": "无（宿主不记账）",
}


class PackageError(RuntimeError):
    """包不可用：清单缺失 / 声明了 entry 却没有文件 / 版本门槛不过 / 契约函数缺失。"""


def _read_json(path, default=None):
    """读 JSON（缺文件 / 坏 JSON → default，不抛）。"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                            # noqa: BLE001
        return default


class Package:
    """一个内容包（`game.json` 那个目录）—— 宿主眼里它**只有**契约面。

        pkg = load_package(dir)
        pkg.install_engine()              # 全局一次（幂等）
        pkg.apply_game_content(actor)     # 每个 actor 一次（幂等）
    """

    def __init__(self, root: str, manifest: dict, module):
        self.root = root
        self.manifest = manifest or {}
        self.module = module
        self._subs: dict = {}

    # ------------------------------------------------------------ 清单
    @property
    def id(self) -> str:
        return str(self.manifest.get("id") or os.path.basename(self.root))

    @property
    def entry(self) -> str:
        return str(self.manifest.get("entry") or "")

    @property
    def domains(self) -> list:
        return list(self.manifest.get("domains") or [])

    def check_engine(self) -> str:
        """引擎版本门槛（不满 = 显式报错，不静默降级）。返回说明文案。"""
        req = str(self.manifest.get("engine") or "").strip()
        ok, note = engine_version.check(req) if req else (True, "包未声明版本要求")
        if not ok:
            raise PackageError("包 %s 的引擎门槛不满足：%s" % (self.id, note))
        return note

    # ------------------------------------------------------------ 契约面
    def entry_fn(self, name: str):
        """包入口模块上的一个可调用（没有 → None）。"""
        fn = getattr(self.module, name, None)
        return fn if callable(fn) else None

    def install_engine(self):
        fn = self.entry_fn("install_engine")
        if fn is None:
            raise PackageError("包 %s 的 entry=%s 未提供 install_engine()" % (self.id, self.entry))
        return fn()

    def apply_game_content(self, actor: dict):
        fn = self.entry_fn("apply_game_content")
        if fn is None:
            raise PackageError("包 %s 的 entry=%s 未提供 apply_game_content(actor)" % (self.id, self.entry))
        return fn(actor)

    def initial_save(self, uid: str, ctx: dict | None = None) -> dict:
        """新玩家初始档：包给了 initial_save 就用包里的；否则用宿主侧最小形状。

        （真正的初始档属**内容**——职业/属性/技能都在这层定；宿主只保证"有档可用"。）
        """
        fn = self.entry_fn("initial_save")
        if fn is not None:
            data = fn(uid, ctx or {})
            if isinstance(data, dict):
                return data
        return {"uid": uid, ID_KEY: uid, "name": "player-%s" % uid, "level": 1}

    # ------------------------------------------------------------ 包内数据（只读）
    def domain(self, domain: str, kind: str = "data") -> dict:
        """读包内一个域文件（`content/<data|rules>/<domain>.json`）。"""
        sub = "rules" if str(kind) == "rules" else "data"
        return _read_json(os.path.join(self.root, "content", sub, "%s.json" % domain), {}) or {}

    def command_declarations(self) -> dict:
        """包内指令**声明**（`content/data/commands.json`）—— 处理器在宿主/长期项，声明在包。"""
        return self.domain("commands")

    def optional_submodule(self, name: str):
        """入口的同级模块（如包内 `content/bridge.py`）；没有 → None（可拔插半边）。"""
        if name in self._subs:
            return self._subs[name]
        mod = None
        dotted = self.entry[:-3].replace("/", ".") if self.entry.endswith(".py") else ""
        if dotted and "." in dotted:
            try:
                mod = importlib.import_module(dotted.rsplit(".", 1)[0] + "." + name)
            except Exception:                                    # noqa: BLE001
                mod = None
        self._subs[name] = mod
        return mod


def load_package(root: str) -> Package:
    """按包契约加载一个包目录（清单 → entry → import）。

    ⚠️ 一个进程一个包：entry 的 import 名（惯例 `content`）是**包内相对导入的根**，
    `sys.path` 里也因此放了包目录。要同时挂两个包请开两个进程。
    """
    root = os.path.abspath(root)
    manifest = _read_json(os.path.join(root, "game.json"))
    if not isinstance(manifest, dict):
        raise PackageError("不是包目录（缺 game.json）：%s" % root)
    entry = str(manifest.get("entry") or "").strip()
    module = None
    if entry:
        path = os.path.join(root, entry.replace("/", os.sep))
        if not os.path.isfile(path):
            raise PackageError("包 %s 声明了 entry=%s，但文件不存在" % (manifest.get("id"), entry))
        if root not in sys.path:
            sys.path.insert(0, root)
        dotted = entry[:-3].replace("/", ".") if entry.endswith(".py") else entry.replace("/", ".")
        module = importlib.import_module(dotted)
    pkg = Package(root, manifest, module)
    pkg.check_engine()
    return pkg


# ============================================================
# 场景：一场战斗的**输入数据**（宿主侧给；内容侧以后可从流程里产）
# ============================================================

class Scenario:
    """一场战斗的输入配置（玩家档 + 敌组 + 可选掉落池请求）。

    为什么它是"数据"不是"逻辑"：宿主不挑怪、不算数值、不选池——这三件事都是内容策略。
    包内目前**没有**怪物构造器（契约 §五 待接点：副本入口/流程），所以本骨架把这场战斗的
    输入当**调用方给的数据**收下来；包补齐后改为问包要（`entry.open_encounter`）。
    """

    def __init__(self, player=None, enemies=None, rewards=None, event_state=None, btype="monster"):
        self.player = dict(player or {})
        self.enemies = list(enemies or [])
        self.rewards = list(rewards or [])           # [{"pool": 池key, "ctx": {...}}]
        self.event_state = dict(event_state or {})   # 包内桥的 event_state 替身（普通 dict）
        self.btype = str(btype or "monster")

    @classmethod
    def from_dict(cls, data) -> "Scenario":
        data = data or {}
        return cls(data.get("player"), data.get("enemies"), data.get("rewards"),
                   data.get("event_state"), data.get("btype") or "monster")

    @classmethod
    def from_file(cls, path) -> "Scenario":
        return cls.from_dict(_read_json(path, {}))


# ============================================================
# 一场战斗的结果（宿主记账用——数字全部来自引擎事件，骨架不自己算）
# ============================================================

class BattleOutcome:
    """一场战斗的账：结果 / 伤害数字 / 事件序列 / 日志 / 掉落（若包已进包）。"""

    HIT_EVENTS = ("attack_hit", "skill_hit")

    def __init__(self, result="", damage=0, hits=None, events=None, log=None,
                 loot=None, stubs=None, settlement=None, elapsed=0.0):
        self.result = result
        self.damage = int(damage or 0)
        self.hits = list(hits or [])          # [{"event", "by", "to", "dmg", "crit"}]
        self.events = list(events or [])      # 引擎事件名序列（含 battle_start / act_done）
        self.log = list(log or [])            # 引擎已渲染的战场日志（宿主只投递）
        self.loot = list(loot or [])          # 掉落产出（池 key 由场景给；发放属宿主）
        self.settlement = dict(settlement or {})   # 结算计划（包内 settlement.py；经验/金币）
        self.stubs = list(stubs or [])        # 留桩说明（包内半边未进包时写清位置）
        self.elapsed = float(elapsed or 0.0)

    @property
    def actors(self) -> dict:
        return {"hits": len(self.hits), "events": len(self.events)}

    def summary(self) -> str:
        line = ("battle=%s damage=%d hits=%d events=%d loot=%d"
                % (self.result or "?", self.damage, len(self.hits), len(self.events), len(self.loot)))
        if self.settlement:
            line += " exp=%s gold=%s" % (self.settlement.get("exp"), self.settlement.get("gold"))
        if "battle_start" in self.events and "act_done" in self.events:
            line += " (battle_start→act_done ✅)"
        if self.stubs:
            line += " stubs=%d" % len(self.stubs)
        return line


class _StandIns(dict):
    """宿主替身袋子：包内要什么读什么，**宿主没有的给中性值**（None）。

    * 键名与包内某个域同名 → 现读包内该域（`content/<data|rules>/<域>.json`）
    * `final_stats` → 引擎**已挂**的面板 hook（`panel_fn`）按引擎契约算好的面板
    * 其余键（公会/宠物/坐骑/世界事件…宿主自己没有的东西）→ None
      —— 骨架**不抄**包模块那份键清单（那是包的事，见各模块 §二）；缺什么包自己会喊，
      喊不出来（异常）就由 `Host._settle` 记桩，**不编数字**。
    """

    def __init__(self, pkg: "Package", host: "Host", player: dict, uid: str = ""):
        super().__init__()
        for name in pkg.domains:
            self[name] = pkg.domain(name)
        self["party_members"] = [uid] if uid else []
        self["now"] = host.clock()
        self["today"] = date.today().isoformat()
        self["rng"] = random.Random(host.seed) if host.seed is not None else random.Random()
        panel = engine_config.get_hook("panel_fn")
        if callable(panel):
            try:
                self["final_stats"] = panel(player.get("class_name"), int(player.get("level", 1) or 1),
                                            player.get("equipment") or {},
                                            int(player.get("class_tier", 0) or 0),
                                            player.get("attributes"),
                                            int(player.get("evolve_path", 0) or 0), {}, player.get("race"))
            except Exception:                                    # noqa: BLE001
                self["final_stats"] = {}

    def __missing__(self, key):                                  # 未知键 → 中性值（不炸）
        return None


class Host:
    """宿主骨架：包装配 + 会话循环 + 战斗驱动 + 落档。

    参数
    ----
    adapter    : 三函数适配器（`recv` / `load_player` / `save_player` / `say` + 可选钩子）
    package_dir: 包目录（`game.json` 所在）
    scenario   : 演示战斗的输入（`Scenario`；包补齐流程后可改为问包要）
    example_command: 绑定示例处理器的**声明 key**（缺省 = 包内第一条可见声明）
    prefix     : 宿主自己的管理命令前缀（缺省 `/`）
    seed       : 固定随机种子（同种子可复现同一场；None = 走适配器 `rng` 钩子/系统随机）
    """

    def __init__(self, adapter, package_dir, *, scenario=None, example_command=None,
                 prefix="/", seed=None, idle_sleep=0.05, echo_battle=True, tlog_limit=500):
        self.adapter = adapter
        self.package_dir = package_dir
        self.scenario = scenario or Scenario()
        self.prefix = prefix or "/"
        self.seed = seed
        self.idle_sleep = float(idle_sleep)
        self.echo_battle = bool(echo_battle)
        self.tlog_limit = int(tlog_limit)
        self.pkg: Package | None = None
        self.commands = CommandRegistry(name="host-skeleton")
        self.example_command = example_command
        self._messages = 0
        self._blobs: dict = {}
        self._tlog_sink = None

    # ------------------------------------------------------------ 装配
    def boot(self) -> Package:
        """加载包 → 装引擎 → 装载指令声明（声明驱动路由：声明在包，处理器在宿主）。"""
        self.pkg = load_package(self.package_dir)
        self.pkg.install_engine()
        try:
            self.commands = CommandRegistry(name=self.pkg.id).load(self.pkg.command_declarations())
        except Exception:                                        # noqa: BLE001
            self.commands = CommandRegistry(name=self.pkg.id)
        if not self.example_command:
            visible = self.commands.visible()
            self.example_command = visible[0].key if visible else ""
        return self.pkg

    # ------------------------------------------------------------ 可选钩子（契约 §二）
    def _hook(self, name: str):
        fn = getattr(self.adapter, name, None)
        return fn if callable(fn) else None

    def clock(self) -> float:
        fn = self._hook("clock")
        return float(fn()) if fn else time.time()

    def seed_now(self, seed=None) -> float | None:
        """本场的随机种子：显式 > 适配器 `rng()` 钩子 > None（系统随机，不可复现）。

        引擎用模块级随机流，所以宿主取到种子后 `random.seed(...)` —— 这就是适配器
        `rng()` 钩子"同种子复现一场"的落地点（引擎零改动）。
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
        """额外持久化（组队/公会/世界状态这类"不是单玩家档"的数据）。"""
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
        from saintess_engine.tlog import KindTable, MemorySink, TLog
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

    # ---- 战斗末段：结算（包内 settlement.py，策略半边）------------------
    def _settle(self, out: BattleOutcome, player: dict, monster, sides: dict) -> None:
        """结算：调包内 `settlement` 的策略半边，拿回**计划**（经验/金币/入包 grants）。

        宿主只给"替身"（它自己的存储没有的 → 中性值；包内键清单在包模块 §二，骨架不抄第二份），
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
        io = _StandIns(self.pkg, self, player, uid=str(player.get("uid") or ""))
        try:
            plan = fn(player, mon, out.result or "victory", io) or {}
        except Exception as e:                                   # noqa: BLE001
            out.stubs.append("settlement: 已接但调用未完成（%r）—— 缺的替身见包模块 §二" % e)
            return
        out.settlement = {"exp": plan.get("exp"), "gold": plan.get("gold"),
                          "exp_after": plan.get("exp_after"),
                          "lines": len(plan.get("lines") or []),
                          "grants": len(plan.get("grants") or [])}

    def _stub_missing(self, out: BattleOutcome, name: str) -> None:
        out.stubs.append("%s: 包内 content/%s 未进包 → 留桩（契约 §五 待接点）" % (name, name))

    # ---- 战斗末段：掉落（包内 loot.py）---------------------------------
    def _post_battle(self, out: BattleOutcome, player: dict, enemies: list) -> None:
        loot_mod = self.pkg.optional_submodule("loot")
        if loot_mod is None:
            out.stubs.append("loot: 包内 content/loot.py 缺失 → 未掉宝（契约 §五 待接点）")
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
        if self.pkg.optional_submodule("flow") is None:
            self._stub_missing(out, "flow")
        else:
            out.stubs.append("flow: 包内 content/flow/ 已进包；接入点是副本入口"
                             "（instance_gate/router + Battle.script_hook/on_event）—— 骨架无副本指令 → 留桩")
        if self.pkg.optional_submodule("effects") is None:
            self._stub_missing(out, "effects")
        else:
            out.stubs.append("effects: 包内 content/effects/ 已进包；接入点是宿主事件"
                             "（谁交互/谁用药水）+ host/dom 两套替身 —— 骨架无该事件 → 留桩")

    # ------------------------------------------------------------ 一条消息
    def handle(self, ctx: dict) -> None:
        """处理一条消息：认人 → 读档 → 路由 → （改档）→ **落档** → 回话。"""
        ctx = ctx or {}
        uid = str(ctx.get("uid") or "")
        to = {"uid": uid, "group_id": ctx.get("group_id")}
        text = str(ctx.get("text") or "").strip()
        player = self.load_player(uid)
        if player is None:
            player = self.pkg.initial_save(uid, ctx)             # 新玩家：先造初始档
        replies = self.route(ctx, player, text)
        self.save_player(uid, player)                            # 一条消息处理完存一次
        for part in replies:
            self.say(to, part)

    def declared_hit(self, text: str):
        """按**可见**声明顺序匹配（不可见声明 = 平台内部 gate，不是玩家指令）。"""
        text = (text or "").strip()
        if not text:
            return None
        for spec in self.commands.visible():
            try:
                if spec.hits(text, mode="search"):
                    return spec
            except Exception:                                    # noqa: BLE001
                continue
        return None

    def route(self, ctx: dict, player: dict, text: str) -> list:
        """路由：包内声明 → 处理器；宿主前缀 → 管理命令。返回回话（已渲染文本列表）。"""
        if text.startswith(self.prefix):
            return self.host_command(text[len(self.prefix):].strip(), ctx, player)
        spec = self.declared_hit(text)
        if spec is not None:
            if spec.key == self.example_command:
                return self.example_handler(ctx, player, spec)
            return self.declared_echo(spec)
        if not text:
            return []
        return ["（宿主骨架：本条没有命中包内任何指令声明；输入 %shelp 看宿主命令）" % self.prefix]

    def declared_echo(self, spec) -> list:
        """声明回显：骨架**只读声明**（usage/desc/正则条数），不含任何处理器实现。"""
        usage = getattr(spec, "usage", "") or ""
        desc = getattr(spec, "desc", "") or ""
        return ["【%s】(包内声明) %s" % (spec.key, desc),
                "用法：%s" % (usage or "—")]

    def example_handler(self, ctx: dict, player: dict, spec) -> list:
        """**示例指令**（骨架唯一的处理器）：跑一场演示战斗，演示"声明 → 路由 → 处理器"。"""
        out = self.run_demo_battle(player, ctx)
        lines = list(self.declared_echo(spec))
        lines.append("示例处理器已跑一场演示战斗：%s" % out.summary())
        return lines + out.log if self.echo_battle else lines

    def run_demo_battle(self, player: dict, ctx: dict | None = None) -> BattleOutcome:
        """跑演示战斗：玩家档 = 存档 ∪ 场景玩家配置；敌组/掉落池请求来自场景。"""
        uid = str(player.get("uid") or player.get(ID_KEY) or "")
        merged = {**player, **{k: v for k, v in self.scenario.player.items() if v not in (None, "")}}
        merged["uid"] = uid or merged.get("uid", "")
        merged.setdefault(ID_KEY, merged.get("uid", ""))
        out = self.run_battle(merged, self.scenario.enemies,
                              event_state=self.scenario.event_state,
                              seed=self.seed, btype=self.scenario.btype)
        for key, value in merged.items():
            if key in player or key in _MINIMAL_SAVE:
                player[key] = value
        for key in ("hp", "mp", "max_hp", "max_mp", "effects", "shields", "cooldown", "ct"):
            if key in merged:
                player[key] = merged[key]
        return out

    def host_command(self, name: str, ctx: dict, player: dict) -> list:
        """宿主自己的管理命令（平台侧，与包无关）。"""
        word = (name.split() or [""])[0].lower()
        if word in ("help", "帮助"):
            return self.help_text()
        if word in ("battle", "demo"):
            return self.example_handler(ctx, player, _DeclSpec("(宿主触发)", "宿主触发"))
        if word == "quit":
            return []
        spec = self.commands.get(name)
        if spec is not None:
            return self.declared_echo(spec)
        return ["未知宿主命令：%s（%shelp）" % (name, self.prefix)]

    def help_text(self) -> list:
        visible = self.commands.visible()
        return ["宿主骨架：包 %s（%d 域 / %d 条指令声明，示例指令 = %s）"
                % (self.pkg.id, len(self.pkg.domains), len(self.commands), self.example_command),
                "宿主命令：%shelp · %sbattle · %squit · %s<包内指令 key>" % ((self.prefix,) * 4),
                "可选钩子：%s" % "、".join("%s=%s" % (k, ("适配器已给" if self._hook(k) else DEFAULTS_HINTS[k]))
                                          for k in DEFAULTS_HINTS)]

    # ------------------------------------------------------------ 循环
    def serve_forever(self, max_messages: int | None = None, idle_timeout: float | None = None) -> int:
        """会话循环：recv（None = 没有新消息，自旋）→ handle。

        停机条件：适配器 `should_stop()`（骨架扩展面，如 CLI 收到 EOF）/ `max_messages` /
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


class _DeclSpec:
    """宿主自己触发时的占位声明（不是包内声明，只让示例处理器有 key/desc 可回显）。"""

    def __init__(self, key, desc):
        self.key, self.desc, self.usage = key, desc, ""


def main(argv=None) -> int:
    """`python main.py …` = 用命令行适配器跑起骨架（见 `adapter_cli.py`）。"""
    from adapter_cli import main as cli_main
    return cli_main(argv if argv is not None else sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
