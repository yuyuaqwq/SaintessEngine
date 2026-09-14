# -*- coding: utf-8 -*-
"""编辑器扩展面**第 3 层 · 批 2**：派生值沙箱 —— **一次性子进程** + 白名单函数 + `__FW_RENDER__` 协议。

设计真源：`overnight/layer3-render-design.md` §5.1/§5.2（方案 A 子进程 + 能力收窄清单）
          + §9「批 2 · 派生值」；`overnight/layer3-render-contracts.md` §4（沙箱协议）+ §1.9（派生白名单）。

本批**只跑框架白名单函数**（`RD.DERIVE_FNS` 那 12 个），**绝不**执行包自带代码：
`<pkg>/editor/render/<域>.py`（代码档 = 批 3）**已砍** —— 本文件任何路径都不 import 它、
不按路径读它、也不把包目录交给子进程（`ALLOW_CODE = False`，`caps` 里没有 `"code"`）。

父侧入口（**本仓唯一**起渲染子进程的地方 —— `editor/render.py` 里零 `subprocess`）
------------------------------------------------------------------------------
    invoke(payload, timeout_ms=None, max_output_bytes=None) -> dict

它做的事，逐条按契约 §4.3：

| 项 | 做法 |
|---|---|
| 启动 | `[sys.executable, <本文件>]`（`play.py:74` 同款） |
| 输入 | stdin 一个 JSON |
| cwd | 新建空临时目录，请求结束即删（相对路径读写落在空目录里） |
| env | 清掉 `PYTHONPATH`/`PYTHONSTARTUP`/`PYTHONHOME`；只加 `PYTHONIOENCODING`/`PYTHONUTF8`；**不注入**任何包根 |
| 超时 | `FW_RENDER_TIMEOUT`（缺省 1500 ms）→ 到点掐死 + `stage="timeout"` |
| stdout 上限 | `FW_RENDER_MAX_OUTPUT`（缺省 1 MB）→ 超限掐死 + `stage="limit"` |
| stderr | 只留尾部 2000 字符（报错文案用） |
| 内存上限 | **不做**（U3 裁定）：不引 pywin32、不用 Job Object —— 见 `W-L3B2.md` |
| 复用 | **不复用**常驻进程（U4 裁定：接受一次性进程的冷启动） |

子侧（`python render_worker.py`）的收窄清单（设计 §5.2，逐条可断言）
-------------------------------------------------------------------
* `__builtins__` 换成白名单 dict（`SAFE_BUILTINS`）：**没有** `open/eval/exec/compile/__import__/
  globals/locals/getattr/setattr/input/breakpoint/vars/dir/type/object/super`；
* `sys.meta_path` 插 `_ImportGuard`：只放行 stdlib 白名单（`IMPORT_WHITELIST`），其余一律 `ImportError`；
* `sys.path` 收窄（去掉脚本目录 / `''`），**不加**包根、不加仓根；
* 派生派发 = **dict 查表**（`DERIVE_IMPL.get(fn)`）—— 名字不在白名单里就**没有**任何可调用对象，
  不走 `getattr` / `globals()` / 字符串求值；
* 子进程**零文件 IO**（只读 stdin / 只写 stdout）；包目录路径**不进 payload**。

诚实残留（照设计 §7.3，不许包装成「已解决」）
------------------------------------------
Windows 上纯 Python 沙箱**不是内核级隔离**。本批定位 = 「隔离 + 限额 + 不炸编辑器」：不写盘、
不开文件、不连网（import 白名单）、有墙钟与输出上限。但 CPython 的对象图反射（`object.__subclasses__()`、
`func.__globals__` 之类）在**真让包代码进来跑**（批 3）时堵不死 —— 本批没有任何包代码入口，
所以这些面只作为**已知残留**登记在 `_sandbox_report()["escape_*"]` 里，不当成「已解决」。
"""
from __future__ import annotations

# 白名单里的 stdlib 模块**在装 import 闸之前**先全部加载好（否则闸会拦住它们自己的依赖）
import collections          # noqa: F401  （白名单：给批 3 的受限执行面留的口子）
import datetime             # noqa: F401
import decimal              # noqa: F401
import functools            # noqa: F401
import itertools            # noqa: F401
import json
import math
import os
import re
import statistics           # noqa: F401
import sys
import textwrap             # noqa: F401
import time
import traceback
# ⚠ `shutil` / `subprocess` / `tempfile` / `threading` **不在模块级 import** —— 它们只属于
#   **父侧**（`invoke()` 里的局部 import）。理由：子进程与父侧共用这一个文件，模块级 import
#   会让子进程一启动就把「起进程 / 起线程 / 删目录」这些能力装进内存（`sys.modules` 命中就
#   绕过 import 闸）—— 那样「沙箱不许 import subprocess」会变成一句空话（见 `purge_loaded_modules`）。

MARKER = "__FW_RENDER__"
HERE = os.path.dirname(os.path.abspath(__file__))

TIMEOUT_ENV = "FW_RENDER_TIMEOUT"
TIMEOUT_DEFAULT_MS = 1500
MAX_OUTPUT_ENV = "FW_RENDER_MAX_OUTPUT"
MAX_OUTPUT_BYTES = 1024 * 1024                 # 1 MB（契约 §4.3/§4.4）
STDERR_TAIL = 2000                             # 契约 §4.2：stderr 只留尾部
MAX_ELEMENTS = 50000                           # 契约 §1.9：单次派生遍历元素 ≤ 50,000
MAX_LIST_ITEMS = 200                           # 契约 §4.4：容器条目上限（子侧**双保险**）
MAX_DEPTH = 6                                  # 契约 §1.5-ish：值深度 ≤ 6（子侧**双保险**）
MAX_STR = 2000                                 # 单值串长（子侧**双保险**）
MAX_KEY = 80                                   # 容器键长
STDOUT_TAIL = 3000                             # 崩溃时回给父侧的 stdout 尾巴

CAPS = ["decl", "derive"]                      # 能力档：批 2 = 声明 + 派生（**没有** code）
ALLOW_CODE = False                             # 批 3 已砍：本模块不执行任何包代码
#: `sys.executable` 跑本文件 —— 子进程侧没有命令行参数（协议全在 stdin JSON 里）
RUNNER = os.path.abspath(__file__)


# ══════════════════════════════════════════════════════════════════════════════
# 一、父侧：起一次性子进程 + 读回 `__FW_RENDER__` 行（契约 §4.3）
# ══════════════════════════════════════════════════════════════════════════════
def default_timeout_ms() -> int:
    """`FW_RENDER_TIMEOUT`（毫秒；坏值 → 缺省 1500）。"""
    try:
        return max(1, int(os.environ.get(TIMEOUT_ENV) or TIMEOUT_DEFAULT_MS))
    except (TypeError, ValueError):
        return TIMEOUT_DEFAULT_MS


def default_output_cap() -> int:
    """`FW_RENDER_MAX_OUTPUT`（字节；坏值 → 缺省 1 MB）。"""
    try:
        return max(64, int(os.environ.get(MAX_OUTPUT_ENV) or MAX_OUTPUT_BYTES))
    except (TypeError, ValueError):
        return MAX_OUTPUT_BYTES


def child_env() -> dict:
    """子进程环境：**清掉** `PYTHONPATH`/`PYTHONSTARTUP`/`PYTHONHOME`，不注入任何包根（契约 §4.3）。"""
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME")}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _kill(proc) -> None:
    try:
        proc.kill()
    except OSError:
        pass


def _rmtree(path) -> None:
    if not path:
        return
    try:
        import shutil                     # ← 父侧专用（本函数只在父侧跑）
        shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass


def _parse_marker_lines(blob: bytes):
    """stdout → `(done | None, [派生行])`：非 `MARKER` 行与坏 JSON 一律忽略（契约 §4.2）。"""
    done, rows = None, []
    for line in blob.decode("utf-8", "replace").splitlines():
        if not line.startswith(MARKER):
            continue
        try:
            obj = json.loads(line[len(MARKER):])
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        kind = obj.get("t")
        if kind == "done":
            done = obj
        elif kind == "derive":
            rows.append(obj)
    return done, rows


def invoke(payload, timeout_ms=None, max_output_bytes=None) -> dict:
    """跑一次派生沙箱 → `{ok, stage, values, warnings, elapsed_ms, sandbox, ...}`。

    **永不抛**：超时 / 输出超限 / 崩溃 / 协议里没有末行 → 都回一个 `ok=False` + 可读 message
    （调用方按 L3 降级 + 黄条；绝不 500、绝不白屏）。
    """
    import shutil                     # ← 父侧专用（不进子进程内存：见文件头注）
    import subprocess
    import tempfile
    import threading
    tmo = int(timeout_ms) if timeout_ms else default_timeout_ms()
    cap = int(max_output_bytes) if max_output_bytes else default_output_cap()
    try:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        return {"ok": False, "stage": "crash", "message": f"渲染 payload 序列化失败：{exc}",
                "values": {}, "warnings": [], "elapsed_ms": None, "sandbox": None}
    cwd = None
    try:
        cwd = tempfile.mkdtemp(prefix="fw_render_cwd_")          # 空 cwd：相对路径读写落在这里
    except OSError:
        cwd = None
    try:
        proc = subprocess.Popen([sys.executable, RUNNER], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                bufsize=0, env=child_env(), cwd=cwd)
    except OSError as exc:
        _rmtree(cwd)
        return {"ok": False, "stage": "crash", "message": f"起不了渲染子进程：{exc}",
                "values": {}, "warnings": [], "elapsed_ms": None, "sandbox": None}

    state = {"over": False}
    out, err = bytearray(), bytearray()

    def _reader(pipe, sink, is_stdout):
        try:
            while True:
                chunk = pipe.read(65536)
                if not chunk:
                    break
                sink.extend(chunk)
                if is_stdout and len(sink) > cap:
                    state["over"] = True                          # 巨输出 → 掐死（契约 §4.3）
                    _kill(proc)
                    break
                if not is_stdout and len(sink) > 4 * STDERR_TAIL:
                    del sink[:len(sink) - STDERR_TAIL]             # stderr 只留尾巴
        except (OSError, ValueError):
            pass

    def _writer():
        try:
            pos = 0
            while pos < len(raw):
                n = proc.stdin.write(raw[pos:pos + 65536])
                if not n:
                    break
                pos += n
            proc.stdin.close()
        except (OSError, ValueError):
            pass

    threads = [threading.Thread(target=_reader, args=(proc.stdout, out, True), daemon=True),
               threading.Thread(target=_reader, args=(proc.stderr, err, False), daemon=True),
               threading.Thread(target=_writer, daemon=True)]
    for th in threads:
        th.start()
    deadline = time.monotonic() + (tmo / 1000.0)
    timed_out = False
    threads[0].join(max(0.0, deadline - time.monotonic()))
    if threads[0].is_alive():                                  # 墙钟到点 → 掐死
        timed_out = True
        _kill(proc)
        threads[0].join(2.0)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _kill(proc)
    for th in threads[1:]:
        th.join(2.0)

    stderr_tail = bytes(err).decode("utf-8", "replace")[-STDERR_TAIL:]
    _rmtree(cwd)                                               # 请求结束即删（契约 §4.3）
    base = {"values": {}, "warnings": [], "elapsed_ms": None, "sandbox": None,
            "stdout_bytes": len(out), "stderr_tail": stderr_tail, "tree": None}
    if state["over"]:
        return {**base, "ok": False, "stage": "limit",
                "message": f"渲染子进程输出超过上限（{cap} 字节）—— 已掐死并降级"}
    if timed_out:
        return {**base, "ok": False, "stage": "timeout",
                "message": f"渲染超时（{tmo} ms）—— 已掐死子进程并降级"
                           "（可能是派生数据太大或白名单函数在内层循环）"}
    done, rows = _parse_marker_lines(bytes(out))
    if done is None:
        return {**base, "ok": False, "stage": "crash",
                "message": "渲染子进程未返回结果（崩了或 stdout 被吞）",
                "stderr_tail": stderr_tail,
                "stdout_tail": bytes(out)[-STDOUT_TAIL:].decode("utf-8", "replace")}
    values = dict(done.get("values") or {}) if isinstance(done.get("values"), dict) else {}
    for row in rows:                                           # 派生行（可选）与末行取并集
        if isinstance(row.get("name"), str) and "value" in row:
            values.setdefault(row["name"], row["value"])
    if not done.get("ok"):
        return {**base, "ok": False, "stage": done.get("stage") or "derive",
                "message": done.get("message") or "渲染子进程报告失败",
                "warnings": list(done.get("warnings") or []), "values": values,
                "sandbox": done.get("sandbox")}
    return {**base, "ok": True, "stage": done.get("stage") or "done", "values": values,
            "warnings": list(done.get("warnings") or []),
            "elapsed_ms": done.get("elapsed_ms"), "sandbox": done.get("sandbox"),
            "echo": done.get("echo")}


# ══════════════════════════════════════════════════════════════════════════════
# 二、子侧：能力收窄（白名单 builtins / import 闸 / sys.path）
# ══════════════════════════════════════════════════════════════════════════════
#: 白名单 builtins（**照设计 §5.2 的表，多一个都不给**）
SAFE_BUILTINS = {
    "len": len, "range": range, "str": str, "int": int, "float": float, "bool": bool,
    "list": list, "dict": dict, "set": set, "tuple": tuple, "sorted": sorted,
    "min": min, "max": max, "sum": sum, "abs": abs, "round": round,
    "enumerate": enumerate, "zip": zip, "any": any, "all": all, "isinstance": isinstance,
    "print": print,
}
#: 明确**拿掉**的内置（逃逸面 / IO 面 / 反射面）—— 报告里逐条可断言
BLOCKED_BUILTINS = ("__import__", "open", "eval", "exec", "compile", "globals", "locals",
                    "getattr", "setattr", "delattr", "vars", "dir", "type", "object",
                    "super", "memoryview", "input", "breakpoint", "help", "exit", "quit")
#: import 白名单（**只有这些** stdlib 根；其余一律 ImportError）
IMPORT_WHITELIST = ("json", "re", "math", "decimal", "datetime", "collections",
                    "itertools", "functools", "statistics", "textwrap")
#: 子进程启动后允许留在 `sys.modules` 里的**非白名单**根（解释器/框架已绑定的引用；
#: 沙箱代码拿不到**新** import —— 新 import 一律走闸）
_KEEP_ROOTS = {"builtins", "sys", "__main__", "_io", "codecs", "encodings", "io"}

ESCAPE_PROBES = ("__import__", "open", "eval", "exec", "compile", "getattr", "setattr",
                 "globals", "locals", "vars", "dir", "type", "object",
                 "object.__subclasses__", "importlib.import_module", "os.system",
                 "subprocess", "open/../../etc/passwd")
IMPORT_PROBES = ("urllib.request", "subprocess", "os", "socket", "threading",
                 "multiprocessing", "asyncio", "ctypes", "importlib", "inspect",
                 "shutil", "tempfile", "http.client")


class ImportDenied(ImportError):
    """沙箱：import 不在白名单里（设计 §5.2 的 import 面收窄）。"""


class _ImportGuard:
    """`sys.meta_path` 上的闸：白名单外的模块根一律 `ImportError`。"""

    def find_spec(self, name, path=None, target=None):
        root = str(name).split(".")[0]
        if root in IMPORT_WHITELIST or root in _KEEP_ROOTS:
            return None                                    # 放行 → 交给后面的 finder
        raise ImportDenied(
            f"渲染沙箱：import {name!r} 不在白名单里（只放行 "
            f"{' / '.join(IMPORT_WHITELIST)}）")

    def find_module(self, name, path=None):                # 老式 API 兜底
        self.find_spec(name, path)
        return None


def purge_loaded_modules() -> list:
    """把**白名单外**的模块从 `sys.modules` 里摘掉（框架已绑定的模块引用仍然可用）。

    为什么必须做：`import X` **先查 `sys.modules`，命中就不走 import 闸** —— 不摘掉的话，
    「`import subprocess` 被拒」只是空话（子进程框架自己 import 过，就永远在缓存里）。
    摘掉之后，沙箱侧任何**新** import 都走闸 → 白名单外必 `ImportError`（设计 §5.2）。
    """
    gone = []
    for name in list(sys.modules):
        root = str(name).split(".")[0]
        if root in IMPORT_WHITELIST or root in _KEEP_ROOTS:
            continue
        sys.modules.pop(name, None)
        gone.append(name)
    return gone


def restricted_ns() -> dict:
    """受限命名空间（给批 3 的受限执行面留的口子）：白名单 builtins + 白名单模块。"""
    ns = {"__builtins__": dict(SAFE_BUILTINS)}
    for name in IMPORT_WHITELIST:
        ns[name] = sys.modules.get(name)
    return ns


def install_guard():
    guard = _ImportGuard()
    sys.meta_path.insert(0, guard)
    return guard


def remove_guard(guard) -> None:
    try:
        sys.meta_path.remove(guard)
    except ValueError:
        pass


def harden_path() -> list:
    """`sys.path` 收窄：去掉脚本目录 / `''`（**不加**包根、不加仓根）。回收窄后的表。"""
    drop = {os.path.abspath(HERE), os.path.abspath(os.getcwd())}
    keep = [p for p in sys.path if os.path.abspath(p or os.getcwd()) not in drop]
    sys.path[:] = keep or sys.path
    return list(sys.path)


def _guard_denies(name: str) -> bool:
    """**走真的闸**探一次：这个模块名会被拒吗（报告用）。"""
    try:
        _ImportGuard().find_spec(name)
        return False
    except ImportError:
        return True


#: 本机路径长相（用于「payload 里不许有本机路径」的探针；`"/"` 这种分隔符常量不算）
_ABS_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/(?:home|Users|tmp|var|usr|opt|mnt|media|etc)(?:/|$))")


def _path_scan(payload) -> list:
    """payload 里出现的**本机绝对路径**（键路径清单）—— 契约 §4.1：不该有。"""
    hits: list = []

    def walk(v, key):
        if isinstance(v, str):
            if _ABS_RE.match(v):
                hits.append(key)
        elif isinstance(v, dict):
            for k, x in v.items():
                walk(x, f"{key}.{k}")
        elif isinstance(v, list):
            for x in v:
                walk(x, key)

    for k, v in (payload or {}).items():
        walk(v, str(k))
    return hits


def _subclasses_walk_attempt() -> bool:
    """**尽力而为**的反射逃逸探针（设计 §7.3 的**已知残留**，不许包装成「已解决」）。

    纯 Python 里 `(1).__class__.__mro__[1].__subclasses__()` 总能拿到 —— 本批的防线**不是**
    「语言层堵死」，而是「**没有包代码入口**」：`fn` 只走白名单 dict 查表，代码档已砍。
    """
    try:
        return bool((1).__class__.__mro__[1].__subclasses__())
    except Exception:                                      # noqa: BLE001
        return False


def _env_echo() -> dict:
    """子进程实际拿到的环境（证明 `PYTHONPATH` 等已被清掉、没注入任何包根）。"""
    fw = sorted(k for k in os.environ
                if k.startswith("FW_PKG") or k.startswith("FW_FRAMEWORK") or k.startswith("B20_"))
    return {"has_pythonpath": bool(os.environ.get("PYTHONPATH")),
            "has_pythonstartup": bool(os.environ.get("PYTHONSTARTUP")),
            "has_pythonhome": bool(os.environ.get("PYTHONHOME")),
            "framework_env_keys": fw,
            "pythonioencoding": os.environ.get("PYTHONIOENCODING") or "",
            "cwd": os.getcwd()}


def sandbox_report(purged=None) -> dict:
    """沙箱现状（随末行回给父侧；门禁据此做**运行时**硬断言，而不是只读源码）。"""
    ns = restricted_ns()
    builtins = ns["__builtins__"]
    return {
        "caps": list(CAPS),
        "allow_code": ALLOW_CODE,
        "builtins_allowed": sorted(builtins),
        "builtins_blocked": sorted(n for n in BLOCKED_BUILTINS if n not in builtins),
        # ① 白名单函数之外的名字：派发路径（dict 查表）**取不到任何可调用对象**
        "escape_dispatch": {n: DERIVE_IMPL.get(n) is not None for n in ESCAPE_PROBES},
        # ② 受限 builtins 里到底有没有这些反射/IO 名字
        "escape_builtins": {n: (n in builtins) for n in BLOCKED_BUILTINS},
        # ③ import 闸：白名单外的模块根一律 ImportError（**已摘缓存**，命中它才算数）
        "imports_allowed": list(IMPORT_WHITELIST),
        "imports_probe": {n: {"policy_denied": _guard_denies(n),
                              "already_loaded": str(n).split(".")[0] in sys.modules}
                          for n in IMPORT_PROBES},
        "purged_roots": sorted({str(n).split(".")[0] for n in (purged or [])}),
        # 已知残留（设计 §7.3）：语言层可达 ≠ 本批有入口 —— 如实报告，不粉饰
        "subclasses_walk": _subclasses_walk_attempt(),
        "sys_path": list(sys.path),
        "env": _env_echo(),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 三、路径取值（子进程自带的小实现 —— **不 import 仓里的任何模块**）
# ══════════════════════════════════════════════════════════════════════════════
_SEG_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\[(\d+|\*)\]")


def split_path(path: str) -> list:
    """`a.b[0].c` → `["a", "b", 0, "c"]`；`[*]` → `"*"`（与 `render_decl.split_path` 同口径）。"""
    out = []
    for seg in _SEG_RE.finditer(str(path or "")):
        tok = seg.group(0)
        if tok.startswith("["):
            inner = tok[1:-1]
            out.append("*" if inner == "*" else int(inner))
        else:
            out.append(tok)
    return out


def _walk(cur, segs):
    if not segs:
        return cur
    seg, rest = segs[0], segs[1:]
    if seg == "*":
        if not isinstance(cur, list):
            return None
        return [_walk(x, rest) for x in cur]
    if isinstance(seg, int):
        if not isinstance(cur, list) or not (0 <= seg < len(cur)):
            return None
        return _walk(cur[seg], rest)
    if not isinstance(cur, dict) or seg not in cur:
        return None
    return _walk(cur[seg], rest)


def dig(data, path):
    """只读取值（`None` = 取不到）。"""
    if not isinstance(path, str) or not path:
        return None
    return _walk(data, split_path(path))


def sub_of(item, name):
    """单项里的子字段（`of` / `weight` / `by`）：`None`/空 = 取单项自身。"""
    if name is None or name == "":
        return item
    if isinstance(item, dict):
        return dig(item, name) if isinstance(name, str) else None
    return None


# ══════════════════════════════════════════════════════════════════════════════
# 四、白名单派生函数（契约 §1.9 的 12 个；**纯函数、无 IO、无 import**）
# ══════════════════════════════════════════════════════════════════════════════
class _Budget(Exception):
    """单次派生遍历元素超 50,000（契约 §1.9）。"""


def _more(ctx, n=1) -> None:
    ctx["elements"] += n
    if ctx["elements"] > ctx["max_elements"]:
        raise _Budget()


def _as_num(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        try:
            return float(v) if ("." in v or "e" in v.lower()) else int(v)
        except ValueError:
            return None
    return None


def _key_str(v) -> str:
    if isinstance(v, str):
        return v
    if v is None:
        return ""
    if isinstance(v, bool):
        return "是" if v else "否"
    if isinstance(v, (int, float)):
        return str(v)
    try:
        return json.dumps(v, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return repr(v)


def _text(v) -> str:
    return _key_str(v)


def _seq(a):
    """取数组（对象 → 取 values；其它 → `None`）。"""
    v = a.get("field")
    if isinstance(v, list):
        return v
    if isinstance(v, dict):
        return list(v.values())
    return None


def _nums(items, key, ctx):
    out = []
    for it in items:
        _more(ctx)
        v = sub_of(it, key)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        out.append(v)
    return out


def _d_count(a, ctx):
    v = a.get("field")
    if isinstance(v, (list, tuple, dict, str)):
        return len(v)
    return 0


def _agg(kind):
    def impl(a, ctx):
        items = _seq(a)
        if items is None:
            return None
        nums = _nums(items, a.get("of"), ctx)
        if kind == "sum":
            return sum(nums)
        if not nums:
            return None
        if kind == "avg":
            return sum(nums) / len(nums)
        if kind == "min":
            return min(nums)
        return max(nums)
    return impl


def _d_ratio(a, ctx):
    num, den = _as_num(a.get("num")), _as_num(a.get("den"))
    if num is None or not den:
        return None
    scale = _as_num(a.get("scale"))
    return (num / den) * (scale if scale is not None else 1)


def _d_percent_share(a, ctx):
    items = _seq(a)
    if items is None:
        return None
    part = sum(_nums(items, a.get("of"), ctx))
    total = _as_num(a.get("total"))
    if total is None:
        total = part
    if not total:
        return None
    return part / total


def _d_weighted_total(a, ctx):
    items = _seq(a)
    if items is None:
        return None
    return sum(_nums(items, a.get("weight"), ctx))


def _d_group_count(a, ctx):
    items = _seq(a)
    if items is None:
        return None
    key = a.get("by")
    out = {}
    for it in items:
        _more(ctx)
        k = _key_str(sub_of(it, key))
        out[k] = out.get(k, 0) + 1
    return out


def _d_lookup_label(a, ctx):
    ref = a.get("ref")
    ref_key = ref if isinstance(ref, str) else _key_str(ref)
    vals = (ctx.get("ref_values") or {}).get(ref_key)
    if isinstance(vals, list) and vals:
        if ref_key in vals:
            return ref_key
        return str(vals[0])
    return ref_key


def _d_join_text(a, ctx):
    items = a.get("field")
    if not isinstance(items, list):
        return None
    limit = a.get("limit")
    if not isinstance(limit, int) or isinstance(limit, bool) or not (1 <= limit <= 50):
        limit = 50
    sep = a.get("sep")
    sep = sep if isinstance(sep, str) else "、"
    parts = []
    for it in items[:limit]:
        _more(ctx)
        parts.append(_text(it))
    if len(items) > limit:
        ctx["warns"].append(f"join_text：数组 {len(items)} 项超过 limit={limit} —— 只拼前 "
                            f"{limit} 项")
    return sep.join(parts)


def _d_fmt_number(a, ctx):
    v = a.get("value")
    num = _as_num(v)
    if num is None:
        return _text(v)
    digits = a.get("digits")
    thousands = bool(a.get("thousands"))
    if isinstance(num, float) and digits is None and num.is_integer():
        num = int(num)
    if isinstance(digits, int) and not isinstance(digits, bool) and 0 <= digits <= 10:
        body = (f"{num:,.{digits}f}" if thousands else f"{num:.{digits}f}")
    else:
        body = (f"{num:,}" if thousands else str(num))
        if body.endswith(".0"):
            body = body[:-2]
    return body


#: ★ 白名单派发表（**唯一**的函数查找路径：dict 查表 —— 没有 `getattr`/`globals()`/字符串求值）
DERIVE_IMPL = {
    "count": _d_count,
    "sum": _agg("sum"),
    "avg": _agg("avg"),
    "min": _agg("min"),
    "max": _agg("max"),
    "ratio": _d_ratio,
    "percent_share": _d_percent_share,
    "weighted_total": _d_weighted_total,
    "group_count": _d_group_count,
    "lookup_label": _d_lookup_label,
    "join_text": _d_join_text,
    "fmt_number": _d_fmt_number,
}


# ══════════════════════════════════════════════════════════════════════════════
# 五、子侧主流程：解析派生声明 → 白名单求值 → 回 `__FW_RENDER__` 行
# ══════════════════════════════════════════════════════════════════════════════
def _emit(obj: dict) -> None:
    sys.stdout.write(MARKER + json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _order(derives: dict) -> list:
    """依赖序（`{"derive": 名}` 边）；成环 → 剩下的按声明序跟上（父侧已剔除环）。"""
    names = [n for n in derives]
    deps = {}
    for n in names:
        spec = derives.get(n)
        args = (spec.get("args") or {}) if isinstance(spec, dict) else {}
        deps[n] = [v["derive"] for v in args.values()
                   if isinstance(v, dict) and isinstance(v.get("derive"), str)]
    out, done, pending = [], set(), list(names)
    while pending:
        progressed = False
        for n in list(pending):
            if all(d in done or d not in derives for d in deps.get(n, [])):
                out.append(n)
                done.add(n)
                pending.remove(n)
                progressed = True
        if not progressed:
            out.extend(pending)
            break
    return out


def _resolve_args(args: dict, data, values: dict, warns: list, name: str):
    """`args` → 实参值（契约 §1.9 的两种写法，别混）：

    * `{"field": 路径, "of"/"weight"/"by": 子字段}` —— 这些参数的值就是**路径字符串**：
      `field` 解成**条目里的那个值**，`of`/`weight`/`by` 是**单项内的子路径**（原样交 impl）；
    * `{"num"/"den"/"total"/"value": 值引用}` —— 值引用 = 常量 | `{"field": 路径}` |
      `{"derive": 名字}`，这一层才按引用解。
    """
    out = {}
    for k, v in (args or {}).items():
        key = str(k)
        if key == "field":                        # ★ `field` 参数：值是路径（不是值引用）
            if isinstance(v, dict) and "field" in v:
                v = v["field"]                    # 容错：写成值引用也认
            out[key] = dig(data, v) if isinstance(v, str) else None
            continue
        if isinstance(v, dict) and len(v) == 1 and "field" in v:
            out[key] = dig(data, v["field"])
        elif isinstance(v, dict) and len(v) == 1 and "derive" in v:
            ref = v["derive"]
            if ref in values:
                out[key] = values[ref]
            else:
                warns.append(f"派生 {name}：参数 {k} 引用的派生 {ref!r} 没有值（when 不满足"
                             " 或它本身失败）—— 该派生显示为「—」")
                return None
        elif isinstance(v, (str, int, float, bool)) or v is None:
            out[key] = v
        else:
            warns.append(f"派生 {name}：参数 {k} 形状不合规 —— 该派生显示为「—」")
            return None
    return out


def _cap_value(v, warns: list, depth: int = 0):
    """子侧**自限额**（契约 §4.1 的「双保险」）：串 ≤ `MAX_STR`、容器 ≤ `MAX_LIST_ITEMS`、
    深度 ≤ `MAX_DEPTH`；截断时留一条可读告警（**不静默**）。父侧另有一遍等价的硬判。
    """
    if v is None or isinstance(v, (bool, int, float)):
        return v
    if isinstance(v, str):
        if len(v) > MAX_STR:
            _capwarn(warns, f"沙箱上限：字符串超过 {MAX_STR} 字 —— 已截断")
            return v[:MAX_STR]
        return v
    if depth >= MAX_DEPTH:
        _capwarn(warns, f"沙箱上限：值嵌套超过 {MAX_DEPTH} 层 —— 已截断")
        return None
    if isinstance(v, list):
        if len(v) > MAX_LIST_ITEMS:
            _capwarn(warns, f"沙箱上限：数组 {len(v)} 项超过 {MAX_LIST_ITEMS} —— 已截断")
        return [_cap_value(x, warns, depth + 1) for x in v[:MAX_LIST_ITEMS]]
    if isinstance(v, dict):
        if len(v) > MAX_LIST_ITEMS:
            _capwarn(warns, f"沙箱上限：对象 {len(v)} 键超过 {MAX_LIST_ITEMS} —— 已截断")
        out = {}
        for k, x in list(v.items())[:MAX_LIST_ITEMS]:
            out[str(k)[:MAX_KEY]] = _cap_value(x, warns, depth + 1)
        return out
    _capwarn(warns, f"沙箱上限：值类型 {type(v).__name__} 不在白名单 —— 已丢弃")
    return None


def _capwarn(warns: list, msg: str) -> None:
    if msg not in warns:
        warns.append(msg)


def compute(payload) -> dict:
    """按 payload 算派生值 → `{values, warnings, sandbox, echo}`（**不抛**：异常交给末行）。"""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    decl = payload.get("decl") if isinstance(payload.get("decl"), dict) else {}
    derives = decl.get("derives") or {}
    compute_names = payload.get("compute")
    if compute_names is None:
        compute_names = list(derives)
    ref_values = payload.get("ref_values") if isinstance(payload.get("ref_values"), dict) else {}
    limits = payload.get("limits") if isinstance(payload.get("limits"), dict) else {}
    max_elements = limits.get("max_elements")
    if not isinstance(max_elements, int) or max_elements <= 0:
        max_elements = MAX_ELEMENTS
    warns: list = []
    values: dict = {}
    harden_path()
    purged = purge_loaded_modules()
    guard = install_guard()
    try:
        ctx = {"warns": warns, "elements": 0, "max_elements": max_elements,
               "ref_values": ref_values}
        for name in _order(derives):
            if name not in compute_names:
                continue
            spec = derives.get(name)
            if not isinstance(spec, dict):
                warns.append(f"派生 {name}：声明不是对象 —— 已忽略")
                continue
            fn = spec.get("fn")
            impl = DERIVE_IMPL.get(fn)                     # ★ 白名单查表：不在表里 = 无路可走
            if impl is None:
                warns.append(f"派生 {name}：函数 {fn!r} 不在白名单里"
                             f"（{' / '.join(sorted(DERIVE_IMPL))}）—— 该派生显示为「—」")
                continue
            ctx["elements"] = 0
            try:
                a = _resolve_args(spec.get("args") or {}, data, values, warns, name)
                if a is None:
                    continue
                val = impl(a, ctx)
            except _Budget:
                warns.append(f"派生 {name}：单次遍历元素超过 {max_elements} —— 该派生显示为「—」")
                continue
            except Exception as exc:                       # noqa: BLE001 —— 单个派生失败不拖垮整体
                warns.append(f"派生 {name}：计算失败（{type(exc).__name__}: {exc}）"
                             " —— 该派生显示为「—」")
                continue
            val = _cap_value(val, warns)                   # 子侧双保险（父侧还会再判一遍）
            _emit({"t": "derive", "name": name, "value": val})
            values[name] = val
    finally:
        remove_guard(guard)
    return {"values": values, "warnings": warns, "sandbox": sandbox_report(purged),
            "echo": {"keys": sorted(payload), "caps": payload.get("caps") or [],
                     "allow_code": bool(payload.get("allow_code")),
                     "abs_paths": _path_scan(payload), "env": _env_echo(),
                     "sys_path": list(sys.path)}}


def main() -> int:
    t0 = time.monotonic()
    try:
        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
        payload = json.loads(raw or "{}")
        if not isinstance(payload, dict):
            raise ValueError("payload 需为一个 JSON 对象")
        res = compute(payload)
        res["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
        _emit({"t": "done", "stage": "done", "ok": True, "tree": None, **res})
        return 0
    except Exception as exc:                               # noqa: BLE001
        _emit({"t": "done", "stage": "crash", "ok": False,
               "message": f"渲染子进程异常（{type(exc).__name__}: {exc}）",
               "traceback": traceback.format_exc()[-2000:],
               "warnings": [], "values": {}})
        return 1


if __name__ == "__main__":
    sys.exit(main())
