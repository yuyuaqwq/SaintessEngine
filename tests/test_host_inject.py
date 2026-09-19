# -*- coding: utf-8 -*-
"""B19c 门禁：**宿主注入面**（加载期 bind + 运行期 Env.state）+ 存档语义（引擎不代劳）。

五项：
  1. 时序：包声明的 `bind` 在 **import 包命令模块之前** 被调（假包自己在 import 期断言，否则抛错）
  2. 声明未满足：包声明了 bind 但宿主没给注入 → `PackageError`（**不是**静默空表）
  3. 注入面进 `Env.state`（与引擎自有键 spec/prefix/package 共存；同名以注入为准）
  4. 反证：`bind` 自己抛错 → 引擎**原样抛出**（不再被 `except Exception` 吞掉）
  5. 存档：处理器**不调** `env.save()` → 适配器 `save_player` **不被调**；调了 → 恰好一次

实现注意：包布局照约定用 `content/`（引擎的 `Package.domain()` 写死这个目录）；
不同用例之间**清 `sys.modules` 里的 `content*`** 并把当前根插到 `sys.path[0]`，避免同名串味。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from saintess_engine.host import Host, PackageError, load_package   # noqa: E402
from _check import bind_check


FAILS: list = []
PASSED = 0


# ★ 审计 P0-1 单源化：断言助手唯一实现 = tests/_check.py
#   （原先本文件手抄一份 def check；差异项已作为 bind_check 参数写出）
check = bind_check(globals(), "PASSED", failures="FAILS")


def _index_src(boom: bool = False) -> str:
    body = 'raise RuntimeError("bind boom")' if boom else 'BOUND_ORDER.append("bind")'
    return '''# -*- coding: utf-8 -*-
"""注入中间人（合成包）：宿主对象经这里进来；取不到 → 抛（fail-closed）。"""
_INJECTED = {}
BOUND_ORDER = []


def bind_host(**objs):
    %s
    for k, v in (objs or {}).items():
        if v is not None:
            _INJECTED[k] = v


def bound(name):
    return name in _INJECTED


def get(name):
    if name not in _INJECTED:
        raise RuntimeError("index：宿主对象 %%s 取不到 —— 拒绝静默空跑" %% name)
    return _INJECTED[name]
''' % body


_APPLY = '''# -*- coding: utf-8 -*-
"""装配入口（合成包）。"""


def install_engine():
    return {"installed": True}


def initial_save(uid, ctx=None):
    return {"uid": uid, "n": 0}
'''

_CMDS = '''# -*- coding: utf-8 -*-
"""命令模块（合成包）：**import 期就要求已注入** —— 这正是真包的行为。"""
from . import index as _idx

if not _idx.bound("db"):
    raise RuntimeError("commands: 宿主注入缺失 —— 拒绝静默空跑")

_id = _idx.get("db")


def look(env):
    return ["db=%s n=%s state_has_db=%s" % (_id, env.player.get("n"),
                                            env.state.get("db") is _id)]


def bump(env):
    env.player["n"] = int(env.player.get("n") or 0) + 1
    env.save()                                  # 改完必存（契约第 6 条）
    return ["n=%s" % env.player["n"]]


def silent(env):
    env.player["n"] = 999                       # 故意改了档但不调 env.save()
    return ["silent"]


COMMANDS = {
    "look": {"guards": ["player"], "handler": "content.commands:look"},
    "bump": {"guards": ["player"], "handler": "content.commands:bump"},
    "silent": {"guards": ["player"], "handler": "content.commands:silent"},
}
'''

_DECL = {
    "look": {"patterns": ["^(?:看|look)$"], "desc": "看", "category": "演示",
             "guards": ["player"], "order": 1},
    "bump": {"patterns": ["^(?:敲|bump)$"], "desc": "改档并落档", "category": "演示",
             "guards": ["player"], "order": 2},
    "silent": {"patterns": ["^(?:静|silent)$"], "desc": "改档但不落档", "category": "演示",
               "guards": ["player"], "order": 3},
}


def _write_pkg(root: str, *, boom: bool = False) -> str:
    os.makedirs(os.path.join(root, "content", "data"), exist_ok=True)
    manifest = {
        "id": "inject-demo-%s" % os.path.basename(root), "name": "注入演示包", "engine": ">=0.1",
        "entry": "content/apply.py", "domains": ["commands"],
        "bind": {"module": "content/index.py", "func": "bind_host"},
        "created": "2026-09-14T00:00:00",
    }
    for rel, obj in (("game.json", manifest),
                     ("content/data/commands.json", _DECL)):
        with open(os.path.join(root, rel.replace("/", os.sep)), "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)
    for name, src in (("index.py", _index_src(boom)), ("apply.py", _APPLY),
                      ("commands.py", _CMDS)):
        with open(os.path.join(root, "content", name), "w", encoding="utf-8") as fh:
            fh.write(src)
    return root


def _fresh(root: str, **kw):
    """清掉上一用例的 `content*` 模块 + 把当前根插到 sys.path[0]，再加载（用例间隔离）。"""
    for name in [n for n in list(sys.modules) if n == "content" or n.startswith("content.")]:
        del sys.modules[name]
    sys.path.insert(0, root)
    return load_package(root, **kw)


class FakeAdapter:
    """假适配器：三函数 + say；`save_player` 记调用次数。"""

    def __init__(self, players=None):
        self.players = dict(players or {})
        self.saves = []
        self.said = []

    def recv(self, ctx):
        return ctx

    def load_player(self, uid):
        return dict(self.players.get(uid) or {"uid": uid, "n": 0})

    def save_player(self, uid, data):
        self.saves.append((uid, dict(data or {})))
        self.players[uid] = dict(data or {})

    def say(self, to, text):
        self.said.append((dict(to), text))


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="host_inject_")
    pkg_a = _write_pkg(os.path.join(tmp, "A"))
    pkg_b = _write_pkg(os.path.join(tmp, "B"))
    pkg_c = _write_pkg(os.path.join(tmp, "C"), boom=True)

    print("=== 1. 时序：bind 在 import 命令模块**之前**被调 ===")
    try:
        pkg = _fresh(pkg_a, inject={"db": "DB-OBJ"})
        handlers = pkg.command_handlers()
        check("注入后命令表解析出 3 条（不再静默空表）", len(handlers) == 3, "得到 %d 条" % len(handlers))
        idx = sys.modules.get("content.index")
        check("bind 在命令模块 import 之前就被调用过一次",
              getattr(idx, "BOUND_ORDER", []) == ["bind"], str(getattr(idx, "BOUND_ORDER", None)))
        check("声明表也读到了（routes 可用）", len(pkg.command_declarations()) == 3,
              str(sorted(pkg.command_declarations()))[:70])
    except Exception as exc:                                    # noqa: BLE001
        check("注入后能加载包", False, "%s: %s" % (type(exc).__name__, exc))

    print("\n=== 2. 声明未满足 → PackageError（不是静默空表）===")
    try:
        _fresh(pkg_b)                                           # 不给 inject
        check("声明了 bind 但没注入 → 报错", False, "居然没报错")
    except PackageError as exc:
        check("声明了 bind 但没注入 → PackageError（含 bind 字样）", "bind" in str(exc), str(exc)[:80])
    except Exception as exc:                                    # noqa: BLE001
        check("声明了 bind 但没注入 → PackageError", False, "抛的是 %s" % type(exc).__name__)

    print("\n=== 3. 注入面进 Env.state ===")
    _fresh(pkg_a, inject={"db": "DB-OBJ"})
    ad = FakeAdapter({"u1": {"uid": "u1", "n": 1}})
    host = Host(ad, pkg_a, inject={"db": "DB-OBJ", "prefix": "INJECTED-PREFIX"})
    host.boot()
    env = host.build_env("look", host.commands.get("look"), {"uid": "u1", "text": "看"},
                         ad.load_player("u1"))
    check("注入键进入 Env.state", env.state.get("db") == "DB-OBJ", str(sorted(env.state))[:80])
    check("引擎自有键仍在（spec/package）", "spec" in env.state and "package" in env.state)
    check("同名以注入为准（prefix 被覆盖）", env.state.get("prefix") == "INJECTED-PREFIX",
          "prefix=%s" % env.state.get("prefix"))

    print("\n=== 4. 反证：bind 抛错 → 引擎原样抛出（不被吞）===")
    try:
        _fresh(pkg_c, inject={"db": "DB-OBJ"})
        check("bind 抛错 → 引擎原样抛出", False, "居然没抛")
    except RuntimeError as exc:
        check("bind 抛错 → RuntimeError 原样透出（不静默）", "bind boom" in str(exc), str(exc)[:60])
    except Exception as exc:                                    # noqa: BLE001
        check("bind 抛错 → RuntimeError 原样透出", False, "抛的是 %s" % type(exc).__name__)

    print("\n=== 5. 存档：引擎不代劳 + 路由确实命中 ===")
    _fresh(pkg_a, inject={"db": "DB-OBJ"})
    ad2 = FakeAdapter({"u1": {"uid": "u1", "n": 0}})
    host2 = Host(ad2, pkg_a, inject={"db": "DB-OBJ"})
    host2.boot()
    host2.handle({"uid": "u1", "group_id": "g1", "text": "看"})       # look：不调 env.save()
    check("路由命中 look（回话含注入对象）", ad2.said and "db=DB-OBJ" in ad2.said[-1][1],
          str(ad2.said[-1][1])[:60] if ad2.said else "无回话")
    check("处理器不调 env.save() → 适配器 save_player 不被调", len(ad2.saves) == 0,
          "被调 %d 次" % len(ad2.saves))
    host2.handle({"uid": "u1", "group_id": "g1", "text": "敲"})       # bump：调了 env.save()
    check("处理器调了 env.save() → 恰好一次", len(ad2.saves) == 1,
          "被调 %d 次；回话=%s" % (len(ad2.saves), ad2.said[-1][1] if ad2.said else "-"))
    check("落档内容来自处理器改后的档", ad2.players["u1"].get("n") == 1,
          str(ad2.players.get("u1")))

    print("\n" + "=" * 60)
    print("通过 %d / 失败 %d" % (PASSED, len(FAILS)))
    for f in FAILS:
        print("  ❌", f)
    print("→ 宿主注入面门禁%s" % ("全绿 ✅" if not FAILS else "有红 ❌"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
