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
  ③ 门禁 `tests/test_host_skeleton.py` 四项（import 白名单 / 零游戏词汇 / 接入成本 / 两宿主一致性）。

契约本体（引擎侧）
------------------
    from saintess_engine.host import Host, load_package, Scenario, BattleOutcome
三函数与 ctx 七字段、可选钩子、命令通道全在引擎那个模块的说明里 —— 本文件不重复抄一遍。

本文件只留**示例特有**的东西
----------------------------
    Host（示例宿主，继承引擎 Host）—— 绑一条示例指令 + 演示一场战斗供冒烟
    main()                        —— CLI 入口（见 `adapter_cli.py`）
"""
from __future__ import annotations

import os
import sys


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

    def __init__(self, *args, example_command=None, **kwargs):
        kwargs.setdefault("id_key", ID_KEY)
        super().__init__(*args, **kwargs)
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


def main(argv=None) -> int:
    """`python main.py …` = 用命令行适配器跑起宿主（见 `adapter_cli.py`）。"""
    from adapter_cli import main as cli_main
    return cli_main(argv if argv is not None else sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
