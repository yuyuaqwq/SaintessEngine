# -*- coding: utf-8 -*-
"""宿主运行时 · 包加载（`Package` / `load_package`）。

**归属**：通用形状 → 引擎。这里只有「一个内容包长什么样、怎么装」，
零游戏知识、零平台知识（平台身份键名之类一律由调用方给）。

包契约（唯一面，见 `docs/engine-wiki/reference/package-format.md`）：
    game.json                清单（id / name / engine / entry / domains / …）
    <entry>                  入口模块（惯例 `content/apply.py`），提供
                             `install_engine()`（全局一次、幂等）
                             `apply_game_content(actor)`（每 actor 一次、幂等）
                             可选 `initial_save(uid, ctx)`（新玩家初始档 = 内容）
    content/data/<域>.json   域数据（`kind=data`）
    content/rules/<域>.json  域数据（`kind=rules`）
    content/commands.py      可选的**命令表**（`COMMANDS`：声明 key → 守卫 + 处理器引用）
    content/guards.py        可选的**包侧守卫钩子**（`GUARDS`：name → callable）
    content/<同名模块>       可选的契约半边（bridge / settlement / loot / tlog_collect / flow / effects …）

⚠️ **一个进程一个包**：entry 的 import 名（惯例 `content`）是包内相对导入的根，
`load_package()` 会把包目录放进 `sys.path`。要同时挂两个包请开两个进程
（「换包能跑」= 换配置 + 重启进程，不是同进程热切换）。
"""
from __future__ import annotations

import importlib
import json
import os
import sys


class PackageError(RuntimeError):
    """包不可用：清单缺失 / 声明了 entry 却没有文件 / 版本门槛不过 / 契约函数缺失。"""


def read_json(path, default=None):
    """读 JSON（缺文件 / 坏 JSON → default，不抛）。"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                            # noqa: BLE001
        return default


def _engine_version():
    from ..version import check as _check          # 直接子模块（不反向依赖包门面）
    return _check


class Package:
    """一个内容包（`game.json` 那个目录）—— 宿主眼里它**只有**契约面。"""

    def __init__(self, root: str, manifest: dict, module):
        self.root = root
        self.manifest = manifest or {}
        self.module = module
        self._subs: dict = {}
        self._handlers: dict | None = None
        self._guards: dict | None = None

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
        ok, note = _engine_version()(req) if req else (True, "包未声明版本要求")
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

    def initial_save(self, uid: str, ctx: dict | None = None, *, id_key: str = "uid") -> dict:
        """新玩家初始档：包给了 `initial_save(uid, ctx)` 就用包里的（内容），
        否则用宿主侧最小形状（`{uid, <id_key>, name, level}`）。

        真正的初始档属**内容**（职业/属性/技能都在这层定）；宿主只保证「有档可用」。
        """
        fn = self.entry_fn("initial_save")
        if fn is not None:
            data = fn(uid, ctx or {})
            # 包**显式**返回 None / 非 dict = 「本包要求先注册」→ 空档（由 `player` 守卫拦截）。
            # 这是内容侧的策略选择：想让新玩家先注册的包就该这么写。
            return dict(data) if isinstance(data, dict) else {}
        return {"uid": uid, id_key: uid, "name": "player-%s" % uid, "level": 1}

    # ------------------------------------------------------------ 包内数据（只读）
    def domain(self, domain: str, kind: str = "data") -> dict:
        """读包内一个域文件（`content/<data|rules>/<domain>.json`）。"""
        sub = "rules" if str(kind) == "rules" else "data"
        return read_json(os.path.join(self.root, "content", sub, "%s.json" % domain), {}) or {}

    def command_declarations(self) -> dict:
        """包内指令**声明**（`content/data/commands.json`）—— 正则/desc/category/order/usage/guards。

        平台无关的指令元数据；**处理器**在同名的 `content/commands.py::COMMANDS`（见 `command_handlers()`）。
        """
        return self.domain("commands")

    def command_handlers(self) -> dict:
        """包内**命令处理器表**（`content/commands.py::COMMANDS`）。缺 → `{}`（纯数据包没有处理器）。

        形状：`{key: {"guards": ["player", "hook:<包侧守卫名>", …],
                      "handler": "content.cmds.x:fn" | <callable>}}`
        引擎负责解析与调用；**处理器只吃 `Env`、只交 `list[str]`**（已渲染文本段）。
        """
        if self._handlers is None:
            self._handlers = {}
            mod = self.optional_submodule("commands")
            table = getattr(mod, "COMMANDS", None) if mod is not None else None
            if isinstance(table, dict):
                self._handlers = {str(k): (v if isinstance(v, dict) else {"handler": v})
                                  for k, v in table.items()}
        return self._handlers

    def guard_hooks(self) -> dict:
        """包侧**守卫钩子表**（`content/guards.py::GUARDS`）：`{name: callable(env, player) -> str|None}`。

        返回非空字符串 = 拦截并把它当回话（文案属内容）。缺 → `{}`。
        """
        if self._guards is None:
            self._guards = {}
            mod = self.optional_submodule("guards")
            table = getattr(mod, "GUARDS", None) if mod is not None else None
            if isinstance(table, dict):
                self._guards = {str(k): v for k, v in table.items() if callable(v)}
        return self._guards

    def resolve_handler(self, ref):
        """把处理器引用解析成可调用：`"content.cmds.x:fn"` / `"content.cmds.x.fn"` / callable。

        解析不到 → None（由调用方决定是否记桩/报错）。
        """
        if callable(ref):
            return ref
        if not isinstance(ref, str) or not ref.strip():
            return None
        ref = ref.strip()
        if ":" in ref:
            mod_name, _, attr = ref.partition(":")
        else:
            mod_name, _, attr = ref.rpartition(".")
        if not mod_name or not attr:
            return None
        try:
            mod = importlib.import_module(mod_name)
        except Exception:                                        # noqa: BLE001
            return None
        fn = getattr(mod, attr, None)
        return fn if callable(fn) else None

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
    """按包契约加载一个包目录（清单 → entry → import）。"""
    root = os.path.abspath(root)
    manifest = read_json(os.path.join(root, "game.json"))
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
