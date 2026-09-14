# -*- coding: utf-8 -*-
"""宿主骨架 —— **引擎 host 的最小适配器示例**（2026-09-14 起）。

定位变更
--------
宿主运行时（`load_package` / `Host` / `Scenario` / `BattleOutcome` / `StandIns` / `Env`）
已**提升为引擎模块** `saintess_engine.host` —— 因为「同一个包能被多个宿主跑」的前提是
这份编排只有一份实现（否则 QQ 宿主 / 命令行 / 编辑器各写一遍 = 三处漂移）。

本目录因此从「第三个宿主实现」退回成**最小适配器示例**：演示
  ① 三函数怎么接（`recv` / `load_player`+`save_player` / `say` + 可选钩子）；
  ② 「声明在包 → 路由 → 处理器」这条链怎么走（本文件绑 1 条**示例**处理器）；
  ③ 门禁 `tests/test_host_skeleton.py` 五项（import 白名单 / 零游戏词汇 / 接入成本 /
     两宿主一致性 / 注入面反证）。

契约本体（引擎侧）
------------------
    from saintess_engine.host import Host, load_package, Scenario, BattleOutcome
三函数与 ctx 七字段、可选钩子、命令通道全在引擎那个模块的说明里 —— 本文件不重复抄一遍。

本文件只留**示例特有**的东西
----------------------------
    Host（示例宿主，继承引擎 Host）—— 绑一条示例指令 + 演示一场战斗供冒烟
    demo_zero_inject()            —— 零注入演示：`examples/minimal-game` 不声明 bind
    demo_bind_package()           —— 全链路演示：内联合成包「声明 bind + 提供 inject」
    demo_inject()                 —— 上面两条各跑一遍（`python main.py --demo-inject`）
    main()                        —— CLI 入口（见 `adapter_cli.py`）

宿主注入面（`inject`，三函数之外唯一要接的面）
---------------------------------------------
宿主用**一个 dict** 把「包运行期要用的宿主对象」交给引擎：

    Host(adapter, package_dir, inject={"store": my_store})     # 或 load_package(root, inject=...)

引擎在两处用它：① **加载期** —— 包若在 `game.json` 声明了 `bind`（形状见
`docs/engine-wiki/reference/package-format.md` §2.2），引擎在 import 包命令模块**之前**调
`bind_host(**inject)`；② **运行期** —— `inject` 并入每条消息的 `Env.state`（同名以注入为准）。

★ **宿主若不提供注入、而包又声明了 `bind` → 引擎明确报 `PackageError`**（不是静默空表、
  不是"先跑起来再说"）。这是有意的 fail-closed：与其让包在 import 期炸在包内某模块里，
  不如在加载处把根因说清楚。所以「包声明了 bind」时，给 `inject` 是宿主的义务。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile


def _ensure_engine_importable() -> None:
    """引擎可导入性：装过（pip/venv）就什么都不做；否则把仓库根放进 `sys.path`。

    本目录是**示例**（`<root>/examples/host-skeleton`），所以找得到 `<root>/saintess_engine`。
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

from saintess_engine.host import (  # noqa: E402,F401  （re-export：本示例是引擎 host 的入口）
    MINIMAL_SAVE_KEYS, BattleOutcome, Env, Host as EngineHost, Package, PackageError,
    Scenario, StandIns, load_package, run_guards,
)

# 示例平台（命令行 / 冒烟）用的「平台身份」键名。引擎默认 `uid`；示例沿用历史上的 `qq_id`，
# 以示**这个键名由适配器给**，引擎不认识它（零平台知识）。
ID_KEY = "qq_id"


class _DeclSpec:
    """示例宿主自己触发时的占位声明（不是包内声明，只让示例处理器有 key/desc 可回显）。"""

    def __init__(self, key, desc):
        self.key, self.desc, self.usage = key, desc, ""


class Host(EngineHost):
    """示例宿主：引擎 host + 一条示例指令绑定 + 一场演示战斗。

    引擎已经负责「命中声明 → 守卫 → 构造 Env → 调**包内处理器** → 投递」。
    本示例额外绑一条**示例处理器**：不依赖包内实现，用来演示
    「声明（包）→ 路由（引擎）→ 处理器」这条链，并给冒烟提供一场真战斗。
    """

    def __init__(self, *args, example_command=None, inject=None, **kwargs):
        kwargs.setdefault("id_key", ID_KEY)
        # `inject` = 宿主注入面（三函数之外唯一要接的面）：原样透传给引擎 Host ——
        # 加载期交给包声明的 bind，运行期并入 Env.state。缺省 None = 本实例不提供注入。
        super().__init__(*args, inject=inject, **kwargs)
        self.example_command = example_command or ""

    def boot(self) -> Package:
        pkg = super().boot()
        if not self.example_command:
            visible = self.commands.visible()
            self.example_command = visible[0].key if visible else ""
        return pkg

    # ------------------------------------------------------------ 路由：示例处理器优先
    def route(self, ctx: dict, player: dict, text: str) -> list:
        text = str(text or "").strip()
        if text.startswith(self.prefix):
            return self.host_command(text[len(self.prefix):].strip(), ctx, player)
        spec = self.declared_hit(text)
        if spec is not None and spec.key == self.example_command:
            return self.example_handler(ctx, player, spec)
        return super().route(ctx, player, text)      # ← 引擎 host 的路径（包内处理器）

    def example_handler(self, ctx: dict, player: dict, spec) -> list:
        """**示例处理器**：跑一场演示战斗，演示「声明 → 路由 → 处理器」。"""
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
            if key in player or key in MINIMAL_SAVE_KEYS:
                player[key] = value
        for key in ("hp", "mp", "max_hp", "max_mp", "effects", "shields", "cooldown", "ct"):
            if key in merged:
                player[key] = merged[key]
        return out

    def host_command(self, name: str, ctx: dict, player: dict) -> list:
        """示例宿主的管理命令：在引擎的 `help`/`quit` 之外多一个演示战斗。"""
        word = (name.split() or [""])[0].lower()
        if word in ("battle", "demo"):
            return self.example_handler(ctx, player, _DeclSpec("(宿主触发)", "宿主触发"))
        return super().host_command(name, ctx, player)


# ============================================================
# 宿主注入面演示（`inject`）：① 零注入  ② 声明 bind + 提供 inject 全链路
# ============================================================

#: 零注入演示用的包：`examples/minimal-game` —— 它**不声明 bind**，所以不需要注入。
MINIMAL_GAME_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "minimal-game")

#: 内联合成演示包的身份与命令 key（通用词；不含任何游戏内容）。
DEMO_PACKAGE_ID = "host-inject-demo"
DEMO_COMMAND = "hello"

#: 演示用哨兵：把「示例宿主绑的示例指令」指到一个不可能命中的 key ——
#: 这样合成包的 `hello` 会走引擎的**包内处理器**路径，而不是本示例的演示战斗处理器。
_DISABLE_EXAMPLE = "(no-example-command)"

_DEMO_APPLY_SRC = '''# -*- coding: utf-8 -*-
"""装配入口（合成演示包）：install_engine 只回执，不碰引擎全局表。"""


def install_engine():
    return {"installed": True}


def initial_save(uid, ctx=None):
    return {"uid": uid, "n": 0}
'''

_DEMO_INDEX_SRC = '''# -*- coding: utf-8 -*-
"""注入中间人（合成演示包）：宿主对象只从这里进来；取不到 → 抛（fail-closed）。"""
_HOST = {}


def bind_host(**objs):
    """引擎在 import content/commands.py **之前**调它（时序即契约）。"""
    for key, value in objs.items():
        if value is not None:
            _HOST[key] = value


def get(key):
    if key not in _HOST:
        raise RuntimeError("index：宿主对象 %s 取不到 —— 拒绝静默空跑" % key)
    return _HOST[key]
'''

_DEMO_COMMANDS_SRC = '''# -*- coding: utf-8 -*-
"""命令模块（合成演示包）：**import 期就要求已注入** —— 这正是真包的行为。"""
from . import index

_WHO = index.get("who")                 # 宿主没给注入 → RuntimeError 指到本行


def hello(env):
    return ["hello from %s（加载期注入）；Env.state 同名以注入为准：%s"
            % (_WHO, env.state.get("who"))]


COMMANDS = {"__CMD__": {"handler": "content.commands:hello"}}
'''

_DEMO_DECL = {
    DEMO_COMMAND: {"patterns": ["^(?:hello|hi)$"], "desc": "inject demo",
                   "category": "demo", "order": 1},
}


def _demo_package_files() -> dict:
    """内联合成包的全部文件（**现写进临时目录**，不新增示例包目录）。"""
    return {
        "game.json": {
            "id": DEMO_PACKAGE_ID,
            "name": "宿主注入演示包",
            "desc": "演示 game.json 的 bind 声明 + 宿主 inject 全链路（无任何游戏内容）",
            "engine": ">=0.1",
            "entry": "content/apply.py",
            "domains": ["commands"],
            "bind": {"module": "content/index.py", "func": "bind_host"},
            "created": "2026-09-14T00:00:00",
        },
        "content/__init__.py": "",
        "content/apply.py": _DEMO_APPLY_SRC,
        "content/index.py": _DEMO_INDEX_SRC,
        "content/commands.py": _DEMO_COMMANDS_SRC.replace("__CMD__", DEMO_COMMAND),
        "content/data/commands.json": _DEMO_DECL,
    }


def write_bind_demo_package(root: str) -> str:
    """把一个内联合成包写到 `root`（声明 `bind`；命令模块 import 期取注入对象）。"""
    for rel, payload in _demo_package_files().items():
        path = os.path.join(root, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            if isinstance(payload, str):
                fh.write(payload)
            else:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
    return root


class _DemoAdapter:
    """演示用最小适配器（三函数 + 内存 dict 当存档；与门禁里那个假适配器同形）。"""

    def __init__(self):
        self.store: dict = {}
        self.said: list = []

    def recv(self):
        return None

    def load_player(self, uid):
        return self.store.get(uid)

    def save_player(self, uid, data):
        self.store[uid] = data

    def say(self, to, text):
        self.said.append(text)


def _drop_content_modules() -> None:
    """清掉已导入的 `content*`：两个演示包都用 `content` 作 import 根，而引擎的契约是
    **「一个进程一个包」**（真实宿主换包请重启进程）—— 演示函数要能自包含、可反复调用，
    所以每次装载前先清一次；包自己的错误不会被这套清理吞掉（它发生在 import 期）。"""
    for name in [n for n in list(sys.modules) if n == "content" or n.startswith("content.")]:
        del sys.modules[name]


def demo_zero_inject(package_dir: str | None = None):
    """① **零注入演示**：`examples/minimal-game` 不声明 `bind` → 不给 inject 也能加载。

    只**加载**（不 install_engine / 不 boot）：把「不声明 bind 的包零注入合法」这条演示干净，
    `inject` 缺省对它没有任何影响。要真跑起来请用 `adapter_cli.py`。
    """
    _drop_content_modules()
    return load_package(package_dir or MINIMAL_GAME_DIR)


def demo_bind_package(root: str, *, inject=None) -> dict:
    """② **全链路演示**：内联合成包「声明 `bind` + 提供 `inject`」→ 装包 → 跑一条消息。

    * 不给 `inject` → 引擎抛 `PackageError`（**原样上抛**；本函数不替宿主兜底）；
    * 给了 → 加载期 `bind_host(**inject)` 被调 → 命令表解析成功 → 处理器跑出回话。

    返回证据 dict（包 id / bind 声明 / 处理器 key / 回话段 / 建档的 uid）。
    """
    _drop_content_modules()
    package_dir = write_bind_demo_package(root)
    adapter = _DemoAdapter()
    host = Host(adapter, package_dir, inject=inject,           # ← inject 透传给引擎 Host
                example_command=_DISABLE_EXAMPLE)              # 让合成包自己的处理器接管
    pkg = host.boot()
    host.handle({"uid": "demo-1", "group_id": None, "text": DEMO_COMMAND, "raw": DEMO_COMMAND})
    return {"package": pkg.id, "bind": pkg.bind_decl(),
            "handlers": sorted(pkg.command_handlers()),
            "said": list(adapter.said), "saved": sorted(adapter.store)}


def demo_inject(argv=None) -> int:
    """`python main.py --demo-inject`：零注入 + 反证 + 全链路各跑一遍并打印证据。"""
    print("== 宿主骨架 · 注入演示（inject）==", flush=True)
    pkg = demo_zero_inject()
    print("① 零注入：包 %s 不声明 bind（bind_decl=%r）→ inject 缺省即可加载（%d 域）"
          % (pkg.id, pkg.bind_decl(), len(pkg.domains)), flush=True)
    root = os.path.join(tempfile.mkdtemp(prefix="host_skeleton_inject_"), "bind-demo")
    try:
        demo_bind_package(root)                            # 同一份合成包，故意不给 inject
        print("② 反证：声明 bind 却不给 inject → 竟然没报错 ❌", flush=True)
        return 1
    except PackageError as exc:
        print("② 反证：声明 bind 却不给 inject → PackageError ✅ %s" % exc, flush=True)
    out = demo_bind_package(root, inject={"who": "宿主注入对象"})
    print("③ 全链路：声明 bind + 提供 inject → 处理器 %s；回话 %s"
          % (out["handlers"], out["said"]), flush=True)
    return 0 if out["said"] and "宿主注入对象" in out["said"][0] else 1


def main(argv=None) -> int:
    """`python main.py …` = 用命令行适配器跑起宿主（见 `adapter_cli.py`）。

    另加一个自包含入口：`python main.py --demo-inject` = 注入面演示（零注入 / 反证 / 全链路）。
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if "--demo-inject" in args:
        return demo_inject(args)
    from adapter_cli import main as cli_main
    return cli_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
