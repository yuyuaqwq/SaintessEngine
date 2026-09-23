# -*- coding: utf-8 -*-
"""引擎的包加载器 —— **唯一入口**：把一个「包栈」从目录加载成可用的内容模块。

栈的形状
--------
    引擎 → 扩展包（N 个，可互相依赖）→ 数据包（1 个）

* **数据包**（`game.json.kind` 缺省 / `"game"`）：一款游戏的**内容** —— 职业 / 技能 /
  怪物 / 地图 / 委托 / 文案 / 存档形状。**一个进程只有一个**：指令路由、动作注册表、
  文案表、存档、时钟都是进程级单例，两个数据包会互撞（要跑两款游戏 = 开两个进程）。
* **扩展包**（`kind == "extension"`）：游戏级**能力** —— 战斗 / 副本 / 任务 / 经济 / 图鉴 …
  可以装多个，可以互相依赖（副本包 depends 战斗包）。它不提供「身份」，只提供
  「这类事怎么做」；同一份战斗扩展包，任何数据包都能用。

依赖
----
* `game.json.depends`：本包依赖哪些扩展包（按 id 列出）。
* 允许：数据包 → 扩展包 · 扩展包 → 扩展包。**禁止**：扩展包 → 数据包（报错）。
* 加载顺序 = 拓扑序（被依赖者在前）；**成环 → `PackageError`**（fail-closed）。

命名空间
--------
* 数据包的 Python 命名空间固定为 `content`（进程内唯一，不与扩展包冲突，因此
  数据包内既有的 `from content.x import y` 一律不用改）。
* 扩展包的 Python 命名空间 = 它**包目录的目录名**（约定 `== id`）；扩展包因此必须
  直接躺在搜索路径的第一层、目录名与 id 同名（`<搜索路径>/rpg_combat/game.json`）。

域
--
* **声明分层**：引擎默认集 → 扩展包（拓扑序）→ 数据包；后层同名域**整体覆盖**前层
  （不做字段级补缺 —— 补缺是编辑器的活，它要在读声明时就报出「哪个字段写坏了」）。
* **数据分层**：同一个域出现多份文件时，**后层整份覆盖前层**（扩展包给默认值，
  数据包要用自己的就整份覆盖；只想改一条 = 把这个域搬进数据包再改）。
* 落点：数据包 `content/{data,rules}/<域>.json`；扩展包 `{data,rules}/<域>.json`。

契约（与 `docs/engine-wiki/reference/package-format.md` 一致）
------------------------------------------------------------
    包根/game.json              清单：id / kind / depends / engine / entry / domains / bind
    <entry>                     入口模块，提供
                                  install_engine()         全局一次、幂等
                                  apply_game_content(actor) 每 actor 一次、幂等
                                  可选 initial_save(uid, ctx) 新玩家初始档
    包内数据                     <域落点>/<域>.json
    可选半边                     bridge / settlement / loot / tlog_collect / guards / commands

加载**不抛异常以外的静默**：所有失败路径都给出可读错误（`PackageError` 或
`{"ok": False, "errors": [...]}`），不猜、不兜底、不静默降级。
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys

DEFAULT_ENTRY = "content/apply.py"
EXT_KIND = "extension"
GAME_KIND = "game"


class PackageError(RuntimeError):
    """包不可用：清单缺失 / 依赖不满足 / 声明了 entry 却没有文件 / 版本门槛不过 / 契约函数缺失。"""


# ============================================================
# 清单读取
# ============================================================

def read_json(path: str, default=None):
    """读一个 JSON 文件；读不到 / 坏 JSON → 返回 `default`（不抛）。"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                          # noqa: BLE001
        return default


def read_manifest(root: str) -> dict:
    """读包根清单（`game.json`）。缺失 / 坏 JSON / 顶层不是对象 → `PackageError`。"""
    path = os.path.join(root, "game.json")
    if not os.path.isfile(path):
        raise PackageError("不是包目录（缺 game.json）：%s" % root)
    data = read_json(path)
    if not isinstance(data, dict):
        raise PackageError("game.json 顶层必须是对象：%s" % path)
    return data


def manifest_of(root: str) -> dict:
    """清单 + 派生字段（`kind` / `id` / `namespace`），供加载计划使用。"""
    m = read_manifest(root)
    kind = str(m.get("kind") or GAME_KIND).strip().lower()
    if kind not in (GAME_KIND, EXT_KIND):
        raise PackageError("包 %s 的 kind=%r 不认识（只认 %r / %r）"
                           % (root, m.get("kind"), GAME_KIND, EXT_KIND))
    pid = str(m.get("id") or os.path.basename(os.path.abspath(root))).strip()
    if kind == EXT_KIND:
        ns = str(m.get("namespace") or pid).strip()
        if os.path.basename(os.path.abspath(root)) != ns:
            raise PackageError(
                "扩展包 %s 的命名空间 %r 必须等于它包目录的目录名 %r —— "
                "扩展包靠目录名在 sys.path 上取唯一 import 名（不与数据包的 content 冲突）"
                % (pid, ns, os.path.basename(os.path.abspath(root))))
    else:
        ns = "content"
    return {"kind": kind, "id": pid, "namespace": ns, "depends": list(m.get("depends") or []),
            "manifest": m, "root": os.path.abspath(root)}


# ============================================================
# 扩展包发现 + 依赖解析
# ============================================================

def discover_extensions(paths) -> dict:
    """扫扩展包搜索路径（每个条目是「装扩展包目录的父目录」）→ `{id: root}`。

    只认「第一层目录里带 game.json 且 kind=extension」的目录；同名 id 冲突 → `PackageError`
    （不静默取后见的那个）。
    """
    found: dict = {}
    for base in paths or ():
        base = os.path.abspath(str(base))
        if not os.path.isdir(base):
            raise PackageError("扩展包搜索路径不存在：%s" % base)
        for name in sorted(os.listdir(base)):
            root = os.path.join(base, name)
            if not os.path.isdir(root) or not os.path.isfile(os.path.join(root, "game.json")):
                continue
            info = manifest_of(root)
            if info["kind"] != EXT_KIND:
                continue
            if info["id"] in found and os.path.abspath(found[info["id"]]) != info["root"]:
                raise PackageError("扩展包 id 冲突：%r 同时出现在 %s 与 %s"
                                   % (info["id"], found[info["id"]], info["root"]))
            found[info["id"]] = info["root"]
    return found


def default_ext_dirs(game_dir: str = "") -> list:
    """扩展包搜索路径的**约定默认**（调用方没显式给 `exts` 时用它）。

    按优先级：

      ① 环境变量 `SAINTESS_EXTENDS` —— `os.pathsep` 分隔，部署与测试可覆盖
      ② 数据包同级的 `../extends` —— 游戏仓把扩展包放这儿时最省事
      ③ 引擎仓根下的 `extends/` —— 引擎自带的扩展包（ext_combat / ext_quest / …）

    只返回**存在**的目录；顺序即发现优先级。显式传 `exts=[...]` 时本函数不参与，
    传 `exts=[]` 即「不搜任何扩展包」（门禁要的严格模式）。
    """
    out = []
    env = os.environ.get("SAINTESS_EXTENDS", "").strip()
    if env:
        out += [x for x in env.split(os.pathsep) if x.strip()]
    if game_dir:
        out.append(os.path.join(os.path.dirname(os.path.abspath(game_dir)), "extends"))
    out.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "extends"))
    seen, keep = set(), []
    for d in out:
        d = os.path.abspath(d)
        if d in seen or not os.path.isdir(d):
            continue
        seen.add(d); keep.append(d)
    return keep


def _exts_or_default(exts, game_dir):
    """`exts=None` → 约定默认；`exts=[]` → 显式空（不搜）；否则原样。"""
    return default_ext_dirs(game_dir) if exts is None else list(exts)


def plan_stack(game_dir: str, *, exts=None) -> list:
    """依赖解析 + 拓扑排序 → 加载计划（被依赖者在前，数据包在最后）。

    * `exts`：扩展包搜索路径（目录）序列；不在计划里的扩展包不会被加载。
    * `depends` 指向的扩展包找不到 → `PackageError`（点名「谁要的、要谁」）。
    * 成环 → `PackageError`（点名环上的 id）。
    * 扩展包声明 `depends` 的数据包 id → `PackageError`（扩展包不许依赖数据包）。
    """
    game = manifest_of(game_dir)
    if game["kind"] != GAME_KIND:
        raise PackageError("plan_stack 的第一个参数必须是数据包（kind=game），给的是 %r：%s"
                           % (game["kind"], game_dir))
    if not game["manifest"].get("entry"):
        raise PackageError("数据包 %s 没声明 entry（纯数据导出包不能当栈的底）" % game["id"])
    exts = _exts_or_default(exts, game_dir)

    pool = discover_extensions(exts)
    plan: list = []
    state: dict = {}          # 0 = 访问中（在栈上）, 1 = 已完成
    stack_path: list = []

    def visit(info, want: str):
        pid = info["id"]
        if state.get(pid) == 1:
            return
        if state.get(pid) == 0:
            cycle = stack_path[stack_path.index(pid):] + [pid]
            raise PackageError("扩展包依赖成环：%s" % " → ".join(cycle))
        state[pid] = 0
        stack_path.append(pid)
        for dep in info["depends"]:
            dep = str(dep)
            if dep == game["id"]:
                raise PackageError("扩展包 %s 依赖数据包 %s —— 方向错了"
                                   "（只允许 数据包 → 扩展包 与 扩展包 → 扩展包）" % (pid, dep))
            if dep not in pool:
                raise PackageError("扩展包 %s 依赖 %r，但它不在扩展包搜索路径里"
                                   "（搜索路径：%r）" % (pid, dep, list(exts or ())))
            visit(manifest_of(pool[dep]), pid)
        stack_path.pop()
        state[pid] = 1
        plan.append(manifest_of(pool[pid]))

    for dep in game["depends"]:
        dep = str(dep)
        if dep not in pool:
            raise PackageError("数据包 %s 依赖扩展包 %r，但它不在扩展包搜索路径里"
                               "（搜索路径：%r）" % (game["id"], dep, list(exts or ())))
        visit(manifest_of(pool[dep]), game["id"])
    plan.append(game)
    return plan


# ============================================================
# 包对象
# ============================================================

class Package:
    """栈里的一个包（数据包或扩展包）—— 宿主眼里它**只有**契约面。"""

    def __init__(self, info: dict):
        self.kind = info["kind"]
        self.id = info["id"]
        self.namespace = info["namespace"]
        self.root = info["root"]
        self.manifest = info["manifest"]
        self.depends = list(info["depends"])
        self.module = None
        self.entry_dotted: str = ""
        self._subs: dict = {}
        self._handlers = None
        self._guards = None
        self._bound = False

    # ------------------------------------------------------------ 清单
    @property
    def is_game(self) -> bool:
        return self.kind == GAME_KIND

    @property
    def entry(self) -> str:
        """入口相对路径（数据包惯例 `content/apply.py`，扩展包惯例 `apply.py`）。"""
        return str(self.manifest.get("entry") or (DEFAULT_ENTRY if self.is_game else "apply.py"))

    @property
    def domains(self) -> list:
        return list(self.manifest.get("domains") or [])

    def check_engine(self) -> str:
        """引擎版本门槛（不满 = 显式报错，不静默降级）。返回说明文案。"""
        from .version import check as _check
        req = str(self.manifest.get("engine") or "").strip()
        ok, note = _check(req) if req else (True, "包未声明版本要求")
        if not ok:
            raise PackageError("包 %s 的引擎门槛不满足：%s" % (self.id, note))
        return note

    # ------------------------------------------------------------ 加载（import + 注入）
    def load(self, inject=None) -> "Package":
        """把包 import 进来：命名空间 + 入口 + 宿主注入（顺序是契约）。"""
        entry = self.entry
        entry_path = os.path.join(self.root, entry.replace("/", os.sep))
        if not os.path.isfile(entry_path):
            raise PackageError("包 %s 声明了 entry=%s，但文件不存在" % (self.id, entry))
        # 命名空间落点：数据包 = 包根（`content`），扩展包 = 包根的**父目录**（目录名即 ns）
        path_root = self.root if self.is_game else os.path.dirname(self.root)
        if path_root not in sys.path:
            sys.path.insert(0, path_root)
        dotted = entry[:-3].replace("/", ".") if entry.endswith(".py") else entry.replace("/", ".")
        self.entry_dotted = self._full(dotted)
        self.module = importlib.import_module(self.entry_dotted)
        self.apply_bind(inject)          # ★ 必须在命令模块被 import 之前（见 apply_bind）
        self.check_engine()
        return self

    def install_engine(self):
        """全局一次的装配（幂等由包自己保证）。"""
        fn = self.entry_fn("install_engine")
        if fn is None:
            raise PackageError("包 %s 的 entry=%s 未提供 install_engine()" % (self.id, self.entry))
        return fn()

    # ------------------------------------------------------------ 宿主注入面
    def bind_decl(self) -> dict:
        """清单里的注入声明：`"bind": {"module": "content/index.py", "func": "bind_host"}`。"""
        decl = self.manifest.get("bind")
        return dict(decl) if isinstance(decl, dict) else {}

    def apply_bind(self, inject) -> None:
        """把宿主注入对象交给包声明的中间人（未声明 → 不调）。

        声明了却没给注入 → `PackageError`：包自己会在 import 期因为取不到宿主对象而炸在
        包内某模块里（错误信息指不到根因）—— 这里**拒绝静默空跑**。
        """
        decl = self.bind_decl()
        if not decl:
            return
        if not inject:
            raise PackageError("包 %s 声明了 bind=%s，但宿主未提供注入对象（拒绝静默空跑）"
                               % (self.id, decl))
        mod_name = str(decl.get("module") or "")
        fn_name = str(decl.get("func") or "")
        if not mod_name or not fn_name:
            raise PackageError("包 %s 的 bind 声明不完整（需 module + func）：%s" % (self.id, decl))
        fn = getattr(self._decl_module(mod_name), fn_name, None)
        if not callable(fn):
            raise PackageError("包 %s 的 bind.func 不可调用：%s:%s" % (self.id, mod_name, fn_name))
        fn(**inject)
        self._bound = True

    def _full(self, dotted: str) -> str:
        """包内相对模块名 → **全名**：数据包原样（`content`），扩展包加命名空间前缀。

        命名空间是「同一进程装多个包」的地基：数据包固定 `content`（进程内唯一），
        扩展包各自用自己的 id ⇒ 两边、以及扩展包之间，模块全名永不撞。
        """
        if not dotted:
            return dotted
        if self.is_game:
            return dotted
        head = dotted.split(".", 1)[0]
        return dotted if head == self.namespace else "%s.%s" % (self.namespace, dotted)

    def _decl_module(self, mod_name: str):
        """按包根解析声明里的模块路径（`content/index.py` → `content.index`；
        扩展包 `helper.py` → `<ns>.helper`）。"""
        dotted = (mod_name[:-3] if mod_name.endswith(".py") else mod_name).replace("/", ".")
        return importlib.import_module(self._full(dotted))

    # ------------------------------------------------------------ 契约面
    def entry_fn(self, name: str):
        """入口模块上的一个可调用（没有 → None）。"""
        fn = getattr(self.module, name, None) if self.module is not None else None
        return fn if callable(fn) else None

    def apply_game_content(self, actor: dict):
        fn = self.entry_fn("apply_game_content")
        if fn is None:
            raise PackageError("包 %s 的 entry=%s 未提供 apply_game_content(actor)"
                               % (self.id, self.entry))
        return fn(actor)

    def initial_save(self, uid: str, ctx: dict | None = None, *, id_key: str = "uid") -> dict:
        """新玩家初始档：包给了 `initial_save(uid, ctx)` 就用包里的（内容），
        否则用宿主侧最小形状。真正的初始档属**内容**；宿主只保证「有档可用」。

        包**显式**返回 None / 非 dict = 「本包要求先注册」→ 空档（由 `player` 守卫拦截）。
        """
        fn = self.entry_fn("initial_save")
        if fn is not None:
            data = fn(uid, ctx or {})
            return dict(data) if isinstance(data, dict) else {}
        return {"uid": uid, id_key: uid, "name": "player-%s" % uid, "level": 1}

    # ------------------------------------------------------------ 域落点
    def kind_dirs(self) -> dict:
        """`kind` → 本包内的相对落点。数据包 `content/{data,rules}`；扩展包 `{data,rules}`。"""
        base = "content/" if self.is_game else ""
        default = {"data": base + "data", "rules": base + "rules"}
        decl = self.manifest.get("domain_dirs")
        if isinstance(decl, dict):
            default.update({str(k): str(v) for k, v in decl.items()})
        return default

    def domain_path(self, domain: str, kind: str) -> str:
        """本包内该域的文件路径（**不判存在**，由调用方按层序取第一份）。"""
        sub = self.kind_dirs().get(str(kind))
        if not sub:
            raise PackageError("包 %s 的域 %r 用了未知 kind=%r" % (self.id, domain, kind))
        return os.path.join(self.root, sub.replace("/", os.sep), "%s.json" % domain)

    def domain_decl_path(self) -> str:
        """本包的域声明文件路径。数据包惯例 `editor/domains.json`；扩展包 `domains.json`。"""
        rel = self.manifest.get("domain_decl")
        if rel:
            return os.path.join(self.root, str(rel).replace("/", os.sep))
        return os.path.join(self.root, "editor/domains.json" if self.is_game else "domains.json")

    # ------------------------------------------------------------ 包内数据（只读）
    def domain(self, domain: str, kind: str = "data") -> dict:
        """读**本包**内的一个域文件（不跨层）。要分层取值请走 `PackageStack.domain()`。"""
        return read_json(self.domain_path(domain, kind), {}) or {}

    def command_declarations(self) -> dict:
        """包内指令**声明**（正则/desc/category/order/usage/guards）—— 平台无关的指令元数据。"""
        return self.domain("commands", "data")

    def command_handlers(self) -> dict:
        """包内**命令处理器表**（`<entry 同级>/commands.py::COMMANDS`）。缺 → `{}`。"""
        if self._handlers is None:
            self._handlers = {}
            mod = self.optional_submodule("commands")
            table = getattr(mod, "COMMANDS", None) if mod is not None else None
            if isinstance(table, dict):
                self._handlers = {str(k): (v if isinstance(v, dict) else {"handler": v})
                                  for k, v in table.items()}
        return self._handlers

    def guard_hooks(self) -> dict:
        """包侧**守卫钩子表**（`<entry 同级>/guards.py::GUARDS`）：`{name: callable(env, player)}`。"""
        if self._guards is None:
            self._guards = {}
            mod = self.optional_submodule("guards")
            table = getattr(mod, "GUARDS", None) if mod is not None else None
            if isinstance(table, dict):
                self._guards = {str(k): v for k, v in table.items() if callable(v)}
        return self._guards

    def provides(self) -> dict:
        """清单里的**能力提供者**声明：`{"battle": "ext_combat.battle.battle:Battle"}`。

        引擎**不解释键名**（零游戏词汇）—— 谁提供什么、键叫什么，全由包声明；
        引擎只做两件事：按层找到最近的声明，把引用解析成对象。
        这样宿主/内容要拿「某个能力」时不必写死 import，也不必让引擎认识那个词。
        """
        decl = self.manifest.get("provides")
        return {str(k): str(v) for k, v in decl.items()} if isinstance(decl, dict) else {}

    def resolve_ref(self, ref, *, what: str = "引用"):
        """解析 `"模块:属性"` / `"模块.属性"` 引用 → 对象。

        **声明了却解析不到 = 报错**（fail-closed）：静默给 None 会把「配错了」变成
        「这个能力不存在」，两种故障分不清。
        """
        obj = self.resolve_handler(ref)
        if obj is None:
            raise PackageError("包 %s 的%s解析不到：%r" % (self.id, what, ref))
        return obj

    def resolve_handler(self, ref):
        """处理器引用 → 可调用：`"content.cmds.x:fn"` / `"content.cmds.x.fn"` / callable。"""
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
        """入口同级的可选半边（`bridge` / `settlement` / `loot` / `tlog_collect` / `guards`
        / `commands` …）；没有 → None（可拔插半边）。

        **存在性用 `find_spec` 判，不拿异常当信号**（否则「模块自身 import 失败」会被误当成
        「包没有这个模块」而静默吞掉 —— 这是旧版 `except Exception` 的病根）。
        """
        if name in self._subs:
            return self._subs[name]
        dotted = self.entry_dotted if getattr(self, "entry_dotted", None) else ""
        mod = None
        if dotted:
            target = (dotted.rsplit(".", 1)[0] + "." + name) if "." in dotted else (dotted + "." + name)
            if importlib.util.find_spec(target) is not None:
                mod = importlib.import_module(target)     # 包自己的错误原样抛
        self._subs[name] = mod
        return mod

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return "Package(%s:%s)" % (self.kind, self.id)


# ============================================================
# 包栈
# ============================================================

class PackageStack:
    """一次加载的包栈：**扩展包（拓扑序）+ 数据包**。

    域与装配都从栈上走 —— 单个包不知道自己上面/下面是谁，分层口径只有这里一份。
    """

    def __init__(self, plan: list, *, inject=None):
        self.packages = [Package(i) for i in plan]
        if not self.packages or not self.packages[-1].is_game:
            raise PackageError("包栈的最后一层必须是数据包（kind=game）")
        self.game = self.packages[-1]
        self.exts = self.packages[:-1]
        self._inject = inject

    # ------------------------------------------------------------ 加载
    def load(self) -> "PackageStack":
        """按拓扑序逐个 import（含注入与版本门槛）。"""
        for pkg in self.packages:
            pkg.load(self._inject)
        return self

    def install(self) -> "PackageStack":
        """按拓扑序 `install_engine()`（扩展包在前 —— 它们注册的动作/规则先就位）。"""
        for pkg in self.packages:
            pkg.install_engine()
        return self

    def find(self, pid: str):
        for pkg in self.packages:
            if pkg.id == pid:
                return pkg
        return None

    @property
    def ids(self) -> list:
        return [p.id for p in self.packages]

    # ------------------------------------------------------------ 能力提供者（分层）
    def provider(self, key: str, default=None):
        """取一个**能力提供者**：数据包优先，其次扩展包（离数据包近的先）。

        返回第一个在 `game.json.provides` 里声明了 `key` 的包所指向的对象；
        没有任何层声明 → `default`。声明了却解析不到 → `PackageError`（不静默）。
        """
        for pkg in reversed(self.packages):
            ref = pkg.provides().get(str(key))
            if ref:
                return pkg.resolve_ref(ref, what="能力提供者 provides.%s" % key)
        return default

    def providers(self) -> dict:
        """**逐层合并**后的能力提供者表（键 → `(包 id, 引用)`），近数据包者胜 —— 审计用。"""
        out: dict = {}
        for pkg in self.packages:
            for k, v in pkg.provides().items():
                out[k] = (pkg.id, v)
        return out

    # ------------------------------------------------------------ 域（分层）
    def domain_decl(self) -> dict:
        """**分层合并**的域声明：引擎默认集 → 扩展包（拓扑序）→ 数据包（后层整域覆盖前层）。

        每层只读它自己的声明文件；文件**不存在**的层跳过（扩展包可以不带声明）；
        文件在、但坏 JSON / 顶层不是对象 → `PackageError`（不静默）。
        """
        from .domains import decl_switch, merge_decls
        layers = []
        use_builtin = True
        for pkg in self.packages:
            path = pkg.domain_decl_path()
            if not os.path.isfile(path):
                continue                                     # 这一层没带声明 —— 正常（扩展包可不带）
            raw = read_json(path, None)
            if not isinstance(raw, dict) or not raw:
                raise PackageError("包 %s 的域声明顶层不是非空映射：%s" % (pkg.id, path))
            decls, ub = decl_switch(raw)
            # `$builtin` 只管「引擎默认集」那一层，**不是**「清空下面各层」：
            # 任何一层声明关掉它 ⇒ 整个栈就不带默认集（否则包会莫名其妙拿不到引擎默认域）。
            if not ub:
                use_builtin = False
            layers.append(decls)
        out = merge_decls({}, use_builtin=use_builtin)        # ① 引擎默认集（或空）
        for decls in layers:                                  # ② 扩展包（拓扑序）→ ③ 数据包
            out = merge_decls(decls, builtin=out)             #    同名域整体覆盖前层
        return out

    def domain_sources(self, domain: str):
        """该域在各层的候选文件（**按层序，数据包在最后**）→ `[(包, 路径), …]`。"""
        decl = self.domain_decl()
        entry = decl.get(domain)
        if not isinstance(entry, dict):
            raise PackageError("域 %r 既不在任何包的声明里、也不在引擎默认集里 —— "
                               "声明缺项，拒绝装载（不静默给空表）" % (domain,))
        kind = entry.get("kind")
        if not isinstance(kind, str) or not kind:
            raise PackageError("域 %r 的声明缺 kind（无法派生落点）" % (domain,))
        return [(pkg, pkg.domain_path(domain, kind)) for pkg in self.packages]

    def domain_path(self, domain: str, *, required: bool = True):
        """该域**生效**的文件（层序里最靠后的那一份）。

        `required=True`（缺省）：域不在任何声明里 / 一层文件都没有 → `PackageError`
        （fail-closed：声明缺项或文件缺失都是配置错误，不许静默给空表）。
        `required=False`：同上情形 → 返回 None（用于**可选半边**，如文案表、扩展包默认值）。
        """
        try:
            cands = self.domain_sources(domain)
        except PackageError:
            if required:
                raise
            return None
        for _pkg, path in reversed(cands):
            if os.path.isfile(path):
                return path
        if required:
            raise PackageError("域 %r 声明的文件在所有层里都不存在（找过：%r）"
                               % (domain, [p for _pk, p in cands]))
        return None

    def domain(self, domain: str, *, required: bool = True, default=None) -> dict:
        """**分层读**一个域的数据：后层整份覆盖前层 ⇒ 取层序里最靠后的那份文件。

        `required=True`（缺省）：读不到 → `PackageError`（fail-closed）。
        `required=False`：读不到 → 返回 `default`（**可选半边**专用：文案表、
        扩展包提供的默认域…调用方要显式说明「这个域可以没有」）。
        """
        path = self.domain_path(domain, required=required)
        if path is None:
            return default if default is not None else {}
        data = read_json(path, default)
        return data if data is not None else (default if default is not None else {})

    def domain_layers(self, domain: str) -> list:
        """该域**实际存在**的每一层 → `[(包 id, 路径), …]`（按层序，数据包在最后）。

        用途：审计「这个域的值到底来自哪一层」；只取值请用 `domain()`。
        """
        return [(pkg.id, path) for pkg, path in self.domain_sources(domain) if os.path.isfile(path)]

    # ------------------------------------------------------------ 转发到数据包
    @property
    def id(self) -> str:
        """栈的身份 = 数据包的身份（扩展包不提供身份）。"""
        return self.game.id

    @property
    def domains(self) -> list:
        return self.game.domains

    @property
    def manifest(self) -> dict:
        return self.game.manifest

    @property
    def root(self) -> str:
        return self.game.root

    @property
    def entry(self) -> str:
        return self.game.entry

    def entry_fn(self, name: str):
        return self.game.entry_fn(name)

    def apply_game_content(self, actor: dict):
        return self.game.apply_game_content(actor)

    def initial_save(self, uid: str, ctx: dict | None = None, **kw) -> dict:
        return self.game.initial_save(uid, ctx, **kw)

    def optional_submodule(self, name: str):
        return self.game.optional_submodule(name)

    # ------------------------------------------------------------ 指令（分层）
    def _merge_command_layer(self, attr: str, what: str) -> dict:
        """逐层合并一层指令表（扩展包拓扑序 → 数据包最后）。

        规则与 `providers()` / `domain_decl()` 同源：**近数据包者胜**。

        * 数据包覆盖扩展包同 key：**允许** —— 数据包是这套指令的最终真源
          （想让某条命令换 patterns / guards / 处理器，在数据包里重声明即可）
        * **两个扩展包声明同 key**：`PackageError` —— 谁提供这条指令必须唯一，
          不许静默覆盖（否则「装了 A 包结果 B 包的指令失效」这类故障查不出来）

        每层都是「该包自己的表」：扩展包**可以不带** `commands` 域/`commands.py`
        （`Package.command_declarations()` 读不到就是 `{}`）；数据包照旧自己声明。
        """
        out: dict = {}
        owner: dict = {}
        for pkg in self.packages:
            table = getattr(pkg, attr)() or {}
            for key, value in table.items():
                key = str(key)
                if key in out and pkg is not self.game and owner[key] is not self.game:
                    raise PackageError(
                        "%s 里的 %r 同时由扩展包 %s 与 %s 声明：扩展包之间不许覆盖同 key —— "
                        "请把其中一份改名，或交给数据包声明"
                        % (what, key, owner[key].id, pkg.id))
                out[key] = value
                owner[key] = pkg
        return out

    def command_declarations(self) -> dict:
        """**逐层合并**的指令声明表（扩展包 → 数据包）。

        扩展包带自己的指令是**能力的一部分**（副本/经济/社交各自那几条命令），
        数据包留最终覆盖权。合并结果对数据包的旧行为**逐字不变**：
        数据包声明了哪些 key，谁都没声明过，结果就还是那批 key。
        """
        return self._merge_command_layer("command_declarations", "指令声明表 commands")

    def command_handlers(self) -> dict:
        """**逐层合并**的处理器表（`<entry 同级>/commands.py::COMMANDS`）。"""
        return self._merge_command_layer("command_handlers", "命令处理器表 COMMANDS")

    def guard_hooks(self) -> dict:
        """**逐层合并**的守卫钩子表（`<entry 同级>/guards.py::GUARDS`）。"""
        return self._merge_command_layer("guard_hooks", "守卫钩子表 GUARDS")

    def resolve_handler(self, ref):
        """处理器引用 → 可调用：逐层问（近数据包者先）。

        `ref` 自带命名空间（数据包 `content.*` / 扩展包 `ext_X.*`），所以每层都能
        独立解析；`reversed(self.packages)` = 先问数据包，再往回问扩展包。
        都没有 → `None`（调用方按既有口径处置，不在这里报错）。
        """
        for pkg in reversed(self.packages):
            fn = pkg.resolve_handler(ref)
            if fn is not None:
                return fn
        return None

    def bind_decl(self) -> dict:
        """数据包的 `bind` 声明（宿主注入面的契约形状）—— 转发给数据包。

        `bind` 只有**数据包**会声明（扩展包是纯能力，不接宿主注入面），
        所以这里转发 `self.game` 而不是逐层找。
        """
        return self.game.bind_decl()

    def check_engine(self) -> None:
        """逐个包核引擎版本门槛。任一不满足即抛 —— 不做「第一个通过就算过」。

        `Package.load()` 里已经逐个查过；这个方法留给**装配前想先探一遍**的调用方
        （骨架的 info 打印、编辑器自检），语义与 load 期一致。
        """
        for pkg in self.packages:
            pkg.check_engine()

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return "PackageStack(%s)" % " → ".join(self.ids)


def load_stack(game_dir: str, *, exts=None, inject=None) -> PackageStack:
    """**唯一入口**：加载一个包栈（扩展包 + 数据包）。

        from saintess_engine.package import load_stack
        stack = load_stack("path/to/game", exts=["path/to/extends"], inject={"store": ...})
        stack.install()

    依赖解析 / 拓扑 / 环检测见 `plan_stack()`；失败一律 `PackageError`（可读，不猜）。
    `exts` 缺省（`None`）时按 `default_ext_dirs()` 的约定搜索；传 `[]` 即不搜。
    """
    plan = plan_stack(game_dir, exts=exts)
    return PackageStack(plan, inject=inject).load()


def probe_stack(game_dir: str, *, exts=None, inject=None, install: bool = False) -> dict:
    """工具 / 子进程 / 编辑器用：加载包栈**不抛**，把结果与错误装进一个 dict。

    `install=True`：顺带跑 `install_engine()`（编辑器「试玩/自检」要的是「能装配」，
    不只是「能 import」）；失败同样装进 `errors`，不抛。

        {"ok": bool, "stack": PackageStack | None, "errors": [str, …],
         "plan": [{"kind", "id", "namespace"}, …]}

    「不抛」是这类调用方的真实需要（它们要的是一条可读的错误，不是栈）；
    宿主初始化请用 `load_stack()`（那里要的就是抛）。
    """
    out = {"ok": False, "stack": None, "errors": [], "plan": []}
    try:
        plan = plan_stack(game_dir, exts=exts)
    except PackageError as e:
        out["errors"].append(str(e))
        return out
    except Exception as e:                                     # noqa: BLE001
        out["errors"].append("%s: %s" % (type(e).__name__, e))
        return out
    out["plan"] = [{"kind": i["kind"], "id": i["id"], "namespace": i["namespace"]} for i in plan]
    try:
        out["stack"] = PackageStack(plan, inject=inject).load()
        if install:
            out["stack"].install()
        out["ok"] = True
    except PackageError as e:
        out["errors"].append(str(e))
    except Exception as e:                                     # noqa: BLE001
        out["errors"].append("%s: %s" % (type(e).__name__, e))
    return out
