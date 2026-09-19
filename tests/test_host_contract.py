#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：**宿主契约**（HOST CONTRACT）—— 声明在包 / 守卫 / `Env` / 包内处理器 / 回话。

跑法：python tests/test_host_contract.py        （tests/run_all.py 里也算一份）
退出码：0 = 全绿；1 = 有断言失败。

为什么需要它
------------
2026-09-14 起，宿主运行时提升为引擎模块 `saintess_engine.host`，并且**命令处理器也进了包**：
    声明（`content/data/commands.json`）→ 路由（引擎）→ 守卫 → `Env` → **包内处理器**（`content/commands.py`）→ 回话
在此之前，`Host` 只做「声明回显 + 1 个示例处理器」（旧 README 的「长期项」）。
本门禁把这条链的每一环钉住，**不靠人看代码**：

【1】包内处理器被**解析并调用**（声明 → 命中 → `Env` → 输出文本段）
【2】`guards: ["player"]` 内置守卫：无档 → 拦截（文案属内容，由调用方/包给）
【3】`guards: ["hook:<名>"]` **包侧守卫**（`content/guards.py::GUARDS`）→ 拦截文案由包给
【4】`Env` 字段契约：`uid/group_id/key/text/raw/player/save/clock/rng/tlog/texts/blob_load/blob_save/state` 全在
【5】处理器返回值规整：`str` / `list` / 生成器 / `None` 都能收（`None` → 空回话）
【6】`env.save()` → **宿主落档**（改完必存）
【7】处理器引用坏掉 → **明确回话**（不静默吞；静默失效是本项目最怕的故障）
【8】`arg_text` / `page` / `page_items` 便捷方法接到引擎既有原语（`strip_command` / `parse_page` / `page_items`）
【9】包没给处理器（纯数据包）→ 回显声明（**降级说明**，不炸）

本测试**自带一个临时最小包**（不依赖任何具体游戏包）→ 顺带证明「引擎 host 不认识任何具体游戏」。
"""
from __future__ import annotations

import os
import sys
import tempfile
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import saintess_engine as engine                                    # noqa: E402
from saintess_engine.host import Env, Host, load_package, run_guards  # noqa: E402
from _check import bind_check


FAILS: list = []
PASSED = 0


# ★ 审计 P0-1 单源化：断言助手唯一实现 = tests/_check.py
#   （原先本文件手抄一份 def check；差异项已作为 bind_check 参数写出）
check = bind_check(globals(), "PASSED", failures="FAILS")


# ============================================================
# 临时最小包（自包含；内容用一个与游戏无关的计数器演示）
# ============================================================

_PKG_SRC = {
    "game.json": """{
  "id": "contract-demo",
  "name": "宿主契约演示包",
  "desc": "只用来验证宿主契约（声明/守卫/Env/处理器/回话）的最小包",
  "engine": ">=0.1",
  "entry": "content/apply.py",
  "domains": ["commands", "texts"],
  "created": "2026-09-14T00:00:00"
}
""",
    "content/apply.py": '''# -*- coding: utf-8 -*-
"""契约演示包 · 装配入口。"""
_APPLIED = set()


def install_engine():
    """全局一次、幂等（内容侧往引擎注入 hook 的地方；演示包无 hook）。"""
    return {"installed": True}


def apply_game_content(actor: dict):
    """每个 actor 一次、幂等。"""
    if isinstance(actor, dict) and id(actor) not in _APPLIED:
        _APPLIED.add(id(actor))
        actor.setdefault("_content_applied", True)
    return actor


def initial_save(uid, ctx=None):
    """新玩家初始档（内容定形状；宿主只保证「有档可用」）。"""
    return {"uid": uid, "counter": 0, "name": "demo-%s" % uid}
''',
    "content/cmds.py": '''# -*- coding: utf-8 -*-
"""契约演示包 · 命令处理器（只吃 Env，只交 list[str]）。"""
import random


def ping_cmd(env):
    """返回**多段文本**（list[str]）。"""
    return ["pong uid=%s" % env.uid, "counter=%s" % env.player.get("counter")]


def count_cmd(env):
    """改档 + `env.save()`（改完必存）+ 返回单段 str。"""
    env.player["counter"] = int(env.player.get("counter") or 0) + 1
    env.save()
    return "counter=%d" % env.player["counter"]


def args_cmd(env):
    """验证 `arg_text` / `page` / `page_items` 三个便捷方法。"""
    arg = env.arg_text("参数", ("别名",))
    page = env.page(arg)                     # ← 先剥指令关键词，再解析页码
    items, pages, cur = env.page_items(list(range(1, 11)), page, per_page=3)
    return "arg=%r page=%d pages=%d items=%r" % (arg, page, pages, items)


def gen_cmd(env):
    """返回**生成器**（引擎要能消费）。"""
    for i in range(3):
        yield "g%d" % i


def none_cmd(env):
    """返回 None（= 空回话，不投递）。"""
    return None


def env_fields_cmd(env):
    """把 Env 的字段面报出来（字段契约的硬证据）。"""
    needed = ("key", "uid", "group_id", "text", "raw", "player", "save", "clock", "rng",
              "tlog", "texts", "blob_load", "blob_save", "state")
    missing = [n for n in needed if not hasattr(env, n)]
    if missing:
        return "MISSING=%s" % missing
    return "fields=ok save_callable=%s clock=%s rng=%s" % (
        callable(env.save), isinstance(float(env.clock()), float), env.rng is random)


def tlog_cmd(env):
    """写一条流水（出口由适配器给）。"""
    env.now_tlog("demo_event", n=7)
    return "tlogged"
''',
    "content/guards.py": '''# -*- coding: utf-8 -*-
"""契约演示包 · 包侧守卫钩子（策略属内容）。"""


def block(env, player):
    """返回非空 = 拦截并把它当回话。"""
    if "放我过去" in str(env.text or ""):
        return None
    return "⛔ 包侧守卫拦下了（text=%r）" % env.text


GUARDS = {"block": block}
''',
    "content/commands.py": '''# -*- coding: utf-8 -*-
"""契约演示包 · 命令表（声明 key → 守卫 + 处理器引用）。

处理器引用形态：`"<模块>:<函数>"`（也接受 `"<模块>.<函数>"` 与直接 callable）。
"""
COMMANDS = {
    "ping": {"guards": ["player"], "handler": "content.cmds:ping_cmd"},
    "count": {"guards": ["player"], "handler": "content.cmds:count_cmd"},
    "args": {"handler": "content.cmds:args_cmd"},
    "gen": {"handler": "content.cmds:gen_cmd"},
    "nothing": {"handler": "content.cmds:none_cmd"},
    "fields": {"handler": "content.cmds:env_fields_cmd"},
    "tlogging": {"handler": "content.cmds:tlog_cmd"},
    "gate": {"guards": ["hook:block"], "handler": "content.cmds:ping_cmd"},
    "broken": {"handler": "content.cmds:没有这个函数"},
    "dataonly": {},                                   # 只有声明、没有 handler → 回显
}
''',
    "content/data/commands.json": """{
  "ping": {"patterns": ["^测试"], "desc": "契约演示：回显", "category": "契约", "usage": "测试", "order": 1},
  "count": {"patterns": ["^计数"], "desc": "契约演示：改档必存", "category": "契约", "usage": "计数", "order": 2},
  "args": {"patterns": ["^参数(?:\\\\s+(.*))?$"], "desc": "契约演示：取参与分页", "category": "契约", "usage": "参数 [页]", "order": 3},
  "gen": {"patterns": ["^生成"], "desc": "契约演示：生成器返回", "category": "契约", "usage": "生成", "order": 4},
  "nothing": {"patterns": ["^静默"], "desc": "契约演示：空回话", "category": "契约", "usage": "静默", "order": 5},
  "fields": {"patterns": ["^字段"], "desc": "契约演示：Env 字段面", "category": "契约", "usage": "字段", "order": 6},
  "tlogging": {"patterns": ["^流水"], "desc": "契约演示：写流水", "category": "契约", "usage": "流水", "order": 7},
  "gate": {"patterns": ["^守卫"], "desc": "契约演示：包侧守卫", "category": "契约", "usage": "守卫 <口令>", "order": 8},
  "broken": {"patterns": ["^坏引用"], "desc": "契约演示：坏处理器引用", "category": "契约", "usage": "坏引用", "order": 9},
  "dataonly": {"patterns": ["^纯声明"], "desc": "契约演示：纯数据包降级", "category": "契约", "usage": "纯声明", "order": 10}
}
""",
}


def _write_pkg(root: str) -> str:
    for rel, src in _PKG_SRC.items():
        path = os.path.join(root, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(src)
    return root


class FakeAdapter:
    """最小适配器（三函数 + 若干钩子；内存 dict 当存档）。"""

    def __init__(self, store: dict):
        self.store = store
        self.said: list = []
        self.tlogs: list = []
        self.saved: list = []

    def recv(self):
        return None

    def load_player(self, uid):
        return self.store.get(uid)

    def save_player(self, uid, data):
        self.store[uid] = data
        self.saved.append(uid)

    def say(self, to, text):
        self.said.append(text)

    def on_tlog(self, record):
        self.tlogs.append(record)


def main() -> int:
    print("=== 宿主契约门禁（声明 → 守卫 → Env → 包内处理器 → 回话）===")
    tmp = tempfile.mkdtemp(prefix="host_contract_")
    pkg_dir = _write_pkg(os.path.join(tmp, "contract-demo"))

    store: dict = {}
    adapter = FakeAdapter(store)
    host = Host(adapter, pkg_dir, register_hint="⚠️ 还没有档", battle_hint="⚠️ 不在战斗中")
    pkg = host.boot()
    check("包加载（id 来自 game.json）", pkg.id == "contract-demo", pkg.id)
    check("声明装载（10 条）", len(host.commands) == 10, str(len(host.commands)))
    check("包内命令表装载（10 条）", len(host.handlers) == 10, str(len(host.handlers)))

    def run(text: str, uid: str = "u-1"):
        adapter.said.clear()
        host.handle({"uid": uid, "text": text, "group_id": "g-1", "raw": text})
        return list(adapter.said)

    # 【1】包内处理器被解析并调用
    print("\n【1】包内处理器（声明 → 命中 → Env → 输出）")
    store["u-1"] = {"uid": "u-1", "counter": 0}
    out = run("测试")
    check("多段输出（list[str]）", len(out) == 2 and out[0] == "pong uid=u-1", repr(out))
    check("处理器读到玩家档", out[1] == "counter=0", repr(out[1]))

    # 【2】新玩家自动造档 + 「包要求先注册」时空档拦截
    print("\n【2】新玩家自动造档 / 空档 → player 守卫拦截")
    out = run("测试", uid="u-new")
    check("新玩家 → 包 initial_save 造档 → 处理器照跑", bool(out) and out[0] == "pong uid=u-new", repr(out))
    check("新档已落库", store.get("u-new", {}).get("counter") == 0, repr(store.get("u-new")))
    _orig_entry_fn = host.pkg.entry_fn
    host.pkg.entry_fn = lambda name: ((lambda uid, ctx=None: None) if name == "initial_save" else None)
    check("包显式返回 None → 空档（= 本包要求先注册）", host.pkg.initial_save("u-x") == {})
    env_empty = Env(uid="u-x", player={}, text="测试")
    check("空档 → player 守卫拦截（文案来自调用方）",
          run_guards(["player"], env_empty, builtin=host.builtin_guards()) == "⚠️ 还没有档")
    host.pkg.entry_fn = _orig_entry_fn

    # 【3】包侧守卫 hook:
    print("\n【3】包侧守卫（guards: [\"hook:block\"] → content/guards.py::GUARDS）")
    out = run("守卫 口令")
    check("包侧守卫拦截（文案由包给）", out and out[0].startswith("⛔ 包侧守卫拦下了"), repr(out))
    out = run("守卫 放我过去")
    check("包侧守卫放行 → 处理器照跑", out and out[0].startswith("pong"), repr(out))

    # 【4】Env 字段契约
    print("\n【4】Env 字段契约")
    out = run("字段")
    check("字段齐 + save/clock/rng 可用", out == ["fields=ok save_callable=True clock=True rng=True"], repr(out))

    # 【5】返回值规整
    print("\n【5】处理器返回值规整（str / list / 生成器 / None）")
    out = run("生成")
    check("生成器被消费成文本段", out == ["g0", "g1", "g2"], repr(out))
    out = run("静默")
    check("None → 空回话（不投递）", out == [], repr(out))

    # 【6】改完必存
    print("\n【6】env.save() → 宿主落档")
    adapter.saved.clear()
    out = run("计数")
    check("返回最新值", out == ["counter=1"], repr(out))
    check("档已落库（counter=1）", store["u-1"]["counter"] == 1, repr(store["u-1"]))
    check("宿主 save_player 被调用", "u-1" in adapter.saved, repr(adapter.saved))
    run("计数")
    check("连续两条各存一次", store["u-1"]["counter"] == 2, repr(store["u-1"]))

    # 【7】坏引用 → 明确回话
    print("\n【7】处理器引用坏掉 → 明确回话（不静默）")
    out = run("坏引用")
    check("明确报出未解析", bool(out) and "处理器未解析" in out[0], repr(out))

    # 【8】便捷方法接到引擎原语
    print("\n【8】arg_text / page / page_items（引擎既有原语）")
    out = run("参数 2")
    check("页码解析 + 分页切片", out and "page=2" in out[0] and "items=[4, 5, 6]" in out[0], repr(out))

    # 【9】纯数据包（无处理器）→ 回显声明
    print("\n【9】纯声明无处理器 → 回显（降级说明）")
    out = run("纯声明")
    check("回显声明", len(out) >= 2 and out[0].startswith("【dataonly】"), repr(out)[:120])

    # 【10】流水出口
    print("\n【10】流水出口（适配器 on_tlog）")
    out = run("流水")
    check("流水经适配器出口",
          out == ["tlogged"] and adapter.tlogs and adapter.tlogs[0].get("kind") == "demo_event", repr(adapter.tlogs[:1]))

    # 【11】守卫调度直测（独立于路由）
    print("\n【11】run_guards 直测（内置 + 包侧 + 未知名跳过）")
    env = Env(uid="u-1", player={"uid": "u-1"}, text="x")
    check("有档 → 过", run_guards(["player"], env, builtin=host.builtin_guards()) is None)
    env2 = Env(uid="u-9", player={}, text="x")
    check("无档 → 拦", run_guards(["player"], env2, builtin=host.builtin_guards()) == "⚠️ 还没有档")
    check("未知名 → 跳过（不炸）", run_guards(["unknown_guard"], env, builtin=host.builtin_guards()) is None)
    check("battle 守卫没给 battle_check → 不拦",
          run_guards(["battle"], env, builtin=host.builtin_guards()) is None)

    print("\n" + "=" * 56)
    if FAILS:
        print("❌ 未过 %d 项：" % len(FAILS))
        for f in FAILS:
            print("   ·", f)
        return 1
    print("✅ 宿主契约全绿（%d 项）：声明/守卫/Env/处理器/回话/落档/降级" % PASSED)
    return 0


if __name__ == "__main__":
    sys.exit(main())
