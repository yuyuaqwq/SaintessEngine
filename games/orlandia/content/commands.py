# -*- coding: utf-8 -*-
"""包内命令表（`content/commands.py`）——**终态形状**（B18 样板定形，2026-09-14）。

形状真源 = `overnight/B18_TERMINAL_SHAPE.md` §1.1；收敛理由见该文 §0（B18a 的
`Ctx`/`say()`/`Args`/`bind_host`/`_TABLE` 那套机制层**已删**，与 B19a 的引擎 host 契约
合并成**一套表**）。

一套表，两处用
--------------
* 宿主运行时：引擎 `saintess_engine.host.Package.command_handlers()` 直接读本模块的 `COMMANDS`
  （→ 守卫 → `Env` → handler → 回话）；
* 编辑器（B20）：同一张表拿指令清单，不必另抄一份。

形状（只剩两件事）
------------------
    COMMANDS: dict      # key -> {"guards": (...), "handler": fn, "params": (...)}
    register(...)       # 装饰器：登记命令；handler 写「面板节点列表」或「已渲染行」
    text/static/raw     # 面板节点写法（行序一眼可见）
    render_panel(...)   # 节点 → **已渲染文本段**（渲染点唯一 = 包内 `content/texts.py`）

渲染归属（铁律）
----------------
句子一律走包内 `content/texts.py`：
* handler 里直接 `T.text("<key>", 槽位…)` / `T.static("<key>")`（最简单，**推荐**）——
  这样文案门禁（`tests/test_texts_table.py` 的 AST 扫 `T.text/T.static` 调用点）能对账槽位；
* 或返回面板节点 `text("<key>", …)` / `static("<key>")`，交给 `render_panel` 落渲染
  （节点只表达「这行用什么 key + 什么槽位」，不落任何玩家可见句子）；
* `raw(<串>)` **只放排版常量**（分隔线 / 空行），禁放句子。
缺 key 的 fail-closed 行为不变：`content/texts.py::_on_miss` → ERROR 日志 + 返回 key 本身。

I2（包内不 import 宿主）
------------------------
handler 只吃引擎 `Env`（`uid` / `group_id` / `player` / `text` / `save` / `state` …）；
宿主面（存储 / 发奖 / 表读 / 可选能力）一律由**调用方注入**（过渡期见各 `cmds_<域>.py` 的
「宿主替身口」注记；B17 已把存档归包 `content/persistence`）。
"""
from __future__ import annotations

__all__ = ["COMMANDS", "register", "text", "static", "raw", "render_panel"]

#: 命令表：key（= 宿主声明表 `command_specs.json` 的 key）→ 声明项
COMMANDS: dict = {}


def register(key: str, guards=(), params=()):
    """登记一条命令（装饰器）。

    `guards`：声明驱动守卫（引擎 `run_guards`）—— 内置名 `player`/`battle`、
    包侧钩子 `hook:<名>`（读 `content/guards.py::GUARDS`）。
    `params`：取参槽位（`"cmd=<命令词>"` / `"page"`）—— 元数据，编辑器/校验用；
    运行时取参走 `env.arg_text(...)` / `env.page(...)`。
    """
    def deco(fn):
        if key in COMMANDS:
            raise KeyError("content.commands：命令 %r 重复登记" % key)
        COMMANDS[key] = {"guards": tuple(guards),
                         "handler": (lambda env, _fn=fn: render_panel(_fn(env), env)),
                         "params": tuple(params)}
        return fn
    return deco


# ============================================================
# 面板节点（渲染节点：只说「这行用什么 key + 什么槽位」）
# ============================================================
def text(key: str, **slots):
    """渲染槽节点：`("t", key, {槽位})` → `content/texts.py::text(key, **槽位)`。"""
    return ("t", key, slots)


def static(key: str):
    """渲染槽节点（无槽位）：`("t", key, {})` → `content/texts.py::static(key)`。"""
    return ("t", key, {})


def raw(s: str):
    """原样行（排版常量：分隔线 / 空行）。**禁放句子**。"""
    return ("raw", s, None)


def _fold_blank_segments(seq) -> list:
    """把「空行段」（`""` 元素）折进相邻段 —— 等价旧桥 `"\\n".join(seq)` 的**逐字节**结果。

    ★ R4（2026-09-15）实测（P6_BEHAVIOR_PROBES §3 A 组 5 条里的 3 条）：
    迁移前宿主桥 `game/commands/_host_bridge.py::run` 是
    `"\\n".join(str(x) for x in out if x is not None)` —— **只滤 `None`，保留 `""`**，
    于是 `lines.append("")` 的空行段渲染成真·空行（`…\\n\\n💡…`）。
    终态引擎通道 `saintess_engine/host/runtime.py::_as_replies` 把 `None` 与 `""` **一起滤掉**，
    空行随之消失 ⇒ 「周常 4/6 · 补给箱 3/3 · 任务面板 4/4」共 11 个冻结分支逐字不一致
    （实测 `out/texts_diffs.txt`，差异段全是 `-<空行>`）。

    本函数在**包内渲染单点**把空行编码回段内换行，使 `"\\n".join(结果) == "\\n".join(原序列)`：

        ["A", "", "B"] → ["A\\n", "B"]      （join = "A\\n\\nB"）
        ["A", "", ""]  → ["A\\n\\n"]        （join = "A\\n\\n"）
        ["", "A"]      → ["\\nA"]            （join = "\\nA"）
        [""]           → [""]               （join = ""）

    为什么改包内而不是引擎：三个通道（QQ 适配器 loopback / 编辑器试玩 / 引擎直调）都经包内
    `render_panel` 渲染面板，改这里一次覆盖三通道；引擎 `_as_replies` 的「空段不是一条回话」
    口径不必动（异步族逐段投递不受影响：`_declare` 族不经本函数）。
    """
    res = []
    lead = 0
    for s in seq:
        if s == "":
            if res:
                res[-1] = res[-1] + "\n"
            else:
                lead += 1
            continue
        res.append(("\n" * lead) + s)
        lead = 0
    if lead:
        if res:
            res[-1] = res[-1] + ("\n" * lead)
        else:
            res.append("\n" * (lead - 1))
    return res


def render_panel(panel, env=None) -> list:
    """面板 → **已渲染文本段**（`list[str]`，元素顺序 = 输出行序）。

    元素三种形态都收：`str`（已渲染，原样保留）/ 面板节点 / `None`（跳过）。
    渲染点唯一 = 包内 `content/texts.py`（宿主 SPEC_PATH 由宿主薄壳 `game/core/texts.py` 注入）。

    末尾按 `_fold_blank_segments` 折叠空行段（与旧宿主桥 `"\\n".join` 逐字节等价）。
    """
    from . import texts as _texts
    out = []
    for item in (panel or ()):
        if item is None:
            continue
        if isinstance(item, str):
            out.append(item)
            continue
        kind, key, slots = item                       # 面板节点（text/static/raw 三态）
        if kind == "raw":
            out.append(key)
        else:
            out.append(_texts.text(key, **(slots or {})))
    return _fold_blank_segments(out)


# ============================================================
# 域模块登记（**自动发现** `content/cmds_*.py`）
# ============================================================
# 加命令 = **只加文件**（`content/cmds_<域>.py`，内含 `@register` 装饰器），**不动本文件**
# —— B18 全量推广是 7 路并发，原来手写 import 行会让 7 条线改同一行（必冲突），故改自动发现。
# 登记顺序 = 模块名序（只影响 `COMMANDS` 的键序；`register()` 对重复 key 直接抛，防撞车）。
def load_domain_modules():
    """import 本包下所有 `cmds_<域>.py`（幂等：`importlib` 自带模块缓存）。返回登记顺序。"""
    import importlib
    import pkgutil
    import sys as _sys
    pkg = _sys.modules[__package__]
    names = sorted(m.name for m in pkgutil.iter_modules(pkg.__path__)
                   if m.name.startswith("cmds_"))
    for n in names:
        importlib.import_module("." + n, __package__)
    return names


LOADED_DOMAIN_MODULES = load_domain_modules()
