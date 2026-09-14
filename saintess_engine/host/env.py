# -*- coding: utf-8 -*-
"""宿主运行时 · 命令执行环境（`Env`）与守卫调度。

**为什么要有 `Env`**：包内命令处理器不能 import 宿主（I2 铁律），所以它需要的一切
（玩家档、存档回调、时钟、随机流、流水出口、文案表、额外持久化）都由引擎**注入**进来。
`Env` 就是那份注入面的**字段级契约**，字段只增不改语义。

纯形状：本模块零游戏知识、零平台知识（`raw` 只透传，引擎不解释它）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence


@dataclass
class Env:
    """一条消息一次的执行环境（引擎构造，交给包内处理器）。

    字段（固定契约，包内只读）：

        key        命中的指令声明 key（`command_specs` 里的键）
        uid        平台用户 id（已由宿主 identity 归一）
        group_id   群 / 私聊容器 id
        text       本条消息的**参数原文**（已 strip；剥指令别名的活儿包内自己做，见 `arg_text`）
        raw        平台原始事件对象（宿主透传；**包内禁解释它**，只允许原样传给包侧钩子）
        player     当前玩家档（普通 dict；宿主 `load_player` 的产出）
        save       改完必存回调（一条消息一次；包内改完 player 后必须调它）
        clock      墙上时间（秒）
        rng        随机流（可设种子 → 可复现；包内别用 `random` 模块全局）
        tlog       流水出口（`tlog(kind, **fields)`；落不落库由宿主钩子定）
        texts      文案表（`saintess_engine.text.TextTable` 或 None；包内文案调用走它）
        blob_load  额外持久化读（组队/世界状态这类「不是单玩家档」的数据）
        blob_save  额外持久化写
        state      引擎/宿主给的额外只读上下文（本轮调用方注入；不给就是空 dict）
    """

    key: str = ""
    uid: str = ""
    group_id: str = ""
    text: str = ""
    raw: Any = None
    player: dict = field(default_factory=dict)
    save: Optional[Callable[[], None]] = None
    clock: Optional[Callable[[], float]] = None
    rng: Any = None
    tlog: Optional[Callable[..., None]] = None
    texts: Any = None
    blob_load: Optional[Callable[[str], Any]] = None
    blob_save: Optional[Callable[[str, Any], None]] = None
    state: dict = field(default_factory=dict)

    # ------------------------------------------------------------ 便捷方法（薄，只调引擎既有原语）
    def arg_text(self, cmd: str = "", aliases: Sequence[str] = ()) -> str:
        """剥掉「@ 前缀」与「指令关键词/别名」后的参数原文。

        `cmd` = 该指令的主关键词（如 `"周常列表"`），`aliases` = 别名表；
        都给空 → 只剥 `@` 前缀。实现复用引擎 `command.strip_command` / `strip_at_prefix`，
        **不在宿主侧重造第二份**。
        """
        from ..command import strip_at_prefix, strip_command
        text = self.text or ""
        if cmd or aliases:
            text = strip_command(text, cmd, aliases)
        else:
            text = strip_at_prefix(text)
        return str(text or "").strip()

    def page(self, raw: str | None = None, default: int = 1) -> int:
        """解析页码（引擎 `command.parse_page`）；`raw=None` 时用本条的 `text`。

        通常先 `arg = env.arg_text("指令名")` 把指令关键词剥掉，再 `env.page(arg)`。
        """
        from ..command import parse_page
        text = self.text if raw is None else raw
        try:
            return int(parse_page(text or "") or default)
        except Exception:                                        # noqa: BLE001
            return int(default)

    def page_items(self, items: Sequence, page: int = 1, per_page: int = 10):
        """分页切片（引擎 `command.page_items`）：返回 `(本页条目, 总页数, 当前页)`。"""
        from ..command import page_items
        return page_items(items, page, per_page=per_page)

    def now_tlog(self, kind: str, **fields) -> None:
        """写一条流水（没给出口就静默丢弃 —— 与「可选钩子不给也能跑」一致）。"""
        if callable(self.tlog):
            try:
                self.tlog(kind, **fields)
            except Exception:                                    # noqa: BLE001
                pass


# ============================================================
# 守卫调度（声明驱动）
# ============================================================

#: 引擎认识的**内置守卫名**（实现由调用方注入；名字固定，语义只有一个）。
#:   player —— 玩家档必须存在（否则拦截）
#:   battle —— 必须在战斗中（否则拦截）
BUILTIN_GUARDS = ("player", "battle")

#: 包侧守卫钩子的声明前缀：`guards: ["hook:maint"]` → 读 `content/guards.py::GUARDS["maint"]`
HOOK_PREFIX = "hook:"


def run_guards(names: Sequence[str], env: Env, *, builtin: dict | None = None,
               hooks: dict | None = None) -> Optional[str]:
    """按声明顺序跑守卫；返回**第一条拦截回话**（已渲染文案），全过 → None。

    * 空名 / 未知名 → **跳过**（不炸；未知名在装配期由门禁点出来，不在运行期阻断玩家）
    * 内置名（`player`/`battle`）→ 走 `builtin[name](env)`
    * `hook:<名>` → 走包侧 `hooks[<名>](env, env.player)`（返回非空 = 拦截文案）
      —— 「停服拦截 / GM 放行 / 等待型副业互斥」这类**策略**都落在这里（策略属内容）
    """
    builtin = builtin or {}
    hooks = hooks or {}
    for raw in names or ():
        name = str(raw or "").strip()
        if not name:
            continue
        if name.startswith(HOOK_PREFIX):
            fn = hooks.get(name[len(HOOK_PREFIX):])
            if callable(fn):
                msg = fn(env, env.player)
                if msg:
                    return str(msg)
            continue
        fn = builtin.get(name)
        if callable(fn):
            msg = fn(env)
            if msg:
                return str(msg)
    return None
