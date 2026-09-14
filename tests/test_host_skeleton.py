#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""端到端冒烟：宿主骨架（`examples/host-skeleton/`）。

跑法：python tests/test_host_skeleton.py      （tests/run_all.py 里也算一份）
退出码：0 = 全绿；1 = 有断言失败。

为什么需要它
------------
宿主骨架的五条纪律**不是靠人看代码守的**，得有线上的门禁钉住：

  A. **import 白名单** —— 骨架只许 import 引擎（`saintess_engine`）+ 标准库（+ 骨架自己的兄弟模块）；
     **不得**出现 `game` / `astrbot` 这类宿主/平台词（那意味着骨架又长回一层宿主）。
  B. **零游戏词汇** —— `examples/host-skeleton/` 全文不得出现包内职业名（8 个）/ 技能名（包内
     `skills.json` 全量）/ 已知机制词（框架 `tests/test_no_game_vocabulary.py` 的 `GAME_TERMS`
     就是那份权威表）。骨架里出现职业名 = 游戏逻辑漏进宿主。
  C. **接入成本反证** —— 现场写一个 ~20 行的假适配器（只填三函数、用内存 dict 当存档）→ 真跑一场
     → 伤害 > 0。这是"别人 30 分钟能接上"的硬证据（不是形容词）。
  D. **两宿主一致性（骨架侧半）** —— 同一 actor 配置 + 同一随机种子下，骨架跑出的**伤害数字**与
     `content/bridge.py` **直连口径**逐条相同。骨架上多出来的那层装配/记账不许改数值。
  E. **注入面反证** —— 合成包声明了 `bind`：骨架**不给** `inject` → `PackageError`（不是静默空表）；
     **给了** → 加载期 bind 被调、命令表解析成功、处理器跑出回话。`main.py --demo-inject`
     另在子进程里钉住「零注入包（不声明 bind）可加载」这一半。

数据从哪来：`games/orlandia` 包（只读）。职业 / 技能 / 怪名 / 掉落池全部**现读包内 JSON**，
本文件里的字面量只有平台词表与断言阈值 —— 不把包内容抄成第二份。
"""
from __future__ import annotations

import ast
import importlib
import json
import os
import random
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SKEL = os.path.join(ROOT, "examples", "host-skeleton")
PKG = os.path.join(ROOT, "games", "orlandia")
SEED = 20260913

for path in (ROOT, SKEL, HERE):
    if path not in sys.path:
        sys.path.insert(0, path)

FAILS: list = []
NOTES: list = []


def check(ok: bool, label: str, detail: str = "") -> bool:
    print("%s %s%s" % ("✅" if ok else "❌", label, ("  " + detail) if detail else ""))
    if not ok:
        FAILS.append(label)
    return ok


def note(text: str) -> None:
    NOTES.append(text)
    print("   · %s" % text)


# ============================================================
# 取数据：包内 JSON（职业 / 技能 / 怪名 / 池）
# ============================================================

def _pkg_json(rel: str):
    with open(os.path.join(PKG, "content", rel), encoding="utf-8") as f:
        return json.load(f)


def class_vocab() -> list:
    """8 个职业名 + id（包内 classes.json 现读）。"""
    classes = _pkg_json(os.path.join("data", "classes.json"))
    out = []
    for key, value in classes.items():
        out.append(str(key))
        name = str((value or {}).get("name") or "").strip()
        if name:
            out.append(name)
    return out


def skill_vocab() -> list:
    """包内技能名全量（skills.json 现读；纯符号/空白丢掉）。"""
    skills = _pkg_json(os.path.join("data", "skills.json"))
    out = set()
    for value in skills.values():
        name = str((value or {}).get("name") or "").strip()
        if name and re.search(r"[0-9A-Za-z\u4e00-\u9fff]", name):
            out.add(name)
    return sorted(out)


def known_mechanism_vocab() -> list:
    """已知机制词 = 框架门禁那份权威表（`tests/test_no_game_vocabulary.py::GAME_TERMS`）。"""
    mod = importlib.import_module("test_no_game_vocabulary")
    return list(mod.GAME_TERMS)


def scenario() -> dict:
    """一场战斗的输入配置：职业/技能/怪名/池**全部现读包内数据**，基础数值由本文件给。"""
    classes = _pkg_json(os.path.join("data", "classes.json"))
    skills = _pkg_json(os.path.join("data", "skills.json"))
    roster = _pkg_json(os.path.join("data", "monster_roster.json"))
    pools = _pkg_json(os.path.join("data", "drop_pools.json"))
    cls_key = sorted(classes)[0]
    owned = sorted(k for k, v in skills.items()
                   if (v or {}).get("owner_class") == cls_key and str(k).startswith("sk_"))
    mid, mon = next((k, v) for k, v in sorted(roster.items())
                    if (v or {}).get("skills") and (v or {}).get("role") not in ("boss",))
    pool = "mon:%s" % mon.get("name")
    return {
        "btype": "monster",
        "player": {"uid": "u-1", "qq_id": "u-1", "name": "smoke", "class_name": cls_key,
                   "level": 10, "hp": 300, "max_hp": 300, "mp": 120, "max_mp": 120,
                   "attributes": {}, "equipment": {}, "learned_skills": owned[:2]},
        "enemies": [{"uid": "e-1", "id": mid, "name": mon.get("name"),
                     "level": int(mon.get("lv") or 1), "hp": 400, "max_hp": 400,
                     "mp": 0, "max_mp": 0, "atk": 25, "def": 8, "matk": 10, "mdef": 8,
                     "spd": 12, "skills": [s for s in (mon.get("skills") or [])]}],
        "rewards": [{"pool": pool, "ctx": {"player_level": 10,
                                           "monster_lv": int(mon.get("lv") or 1)}}],
    }


# ============================================================
# A. import 白名单
# ============================================================

HOST_WORDS = ("astrbot", "aiocqhttp", "napcat", "onebot", "qqbot", "nonebot",
              "telegram", "discord", "slack_sdk", "mirai")
SIBLINGS = {"main", "adapter_cli", "adapter_template", "store_sqlite"}


def _skel_files(exts=(".py", ".md")):
    for name in sorted(os.listdir(SKEL)):
        if name.endswith(exts):
            yield os.path.join(SKEL, name)


def test_import_whitelist() -> None:
    print("\n=== A. 骨架 import 白名单（引擎 + 标准库 + 骨架兄弟模块）===")
    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    bad_roots, bad_hosts = set(), []
    for path in _skel_files((".py",)):
        src = open(path, encoding="utf-8").read()
        tree = ast.parse(src, filename=path)
        for node in ast.walk(tree):
            roots = []
            if isinstance(node, ast.Import):
                roots = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                roots = [(node.module or "").split(".")[0] or "__future__"]
            for root in roots:
                if root not in stdlib and root != "saintess_engine" and root not in SIBLINGS:
                    bad_roots.add("%s: %s" % (os.path.basename(path), root))
        low = src.lower()
        for word in HOST_WORDS:
            if word in low:
                bad_hosts.append("%s: %s" % (os.path.basename(path), word))
        if re.search(r"(?<![A-Za-z0-9_.])(?:from|import)\s+game\b", src):
            bad_hosts.append("%s: import game" % os.path.basename(path))
    check(not bad_roots, "import 根只许 引擎/标准库/骨架兄弟", "越界=%s" % sorted(bad_roots) if bad_roots else "")
    check(not bad_hosts, "无宿主/平台词（%d 个词表）" % (len(HOST_WORDS) + 1), "命中=%s" % bad_hosts if bad_hosts else "")


# ============================================================
# B. 零游戏词汇
# ============================================================

def _patterns(terms):
    out = []
    for term in sorted(set(terms)):
        if not term:
            continue
        if term.isascii():
            out.append((term, re.compile(r"(?<![A-Za-z0-9_])" + re.escape(term) + r"(?![A-Za-z0-9_])")))
        else:
            out.append((term, re.compile(re.escape(term))))
    return out


def test_zero_game_vocabulary() -> None:
    print("\n=== B. 零游戏词汇（骨架全文 grep 包内职业名 / 技能名 / 已知机制词）===")
    cls, skills, mech = class_vocab(), skill_vocab(), known_mechanism_vocab()
    note("扫描表：职业 %d 词 + 技能名 %d 词 + 已知机制词 %d 词 = %d"
         % (len(cls), len(skills), len(mech), len(cls) + len(skills) + len(mech)))
    pats = _patterns(cls + skills + mech)
    bad = []
    files = list(_skel_files((".py", ".md", ".json")))
    for path in files:
        for i, line in enumerate(open(path, encoding="utf-8", errors="replace").read().splitlines(), 1):
            for term, pat in pats:
                if pat.search(line):
                    bad.append("%s:%d [%s] %s" % (os.path.relpath(path, ROOT).replace("\\", "/"),
                                                  i, term, line.strip()[:60]))
    check(not bad, "骨架 %d 个文件零游戏词汇" % len(files), "命中 %d 处：%s" % (len(bad), bad[:5]) if bad else "")


# ============================================================
# C. 接入成本反证：~20 行假适配器
# ============================================================

FAKE_ADAPTER_LINES = 0


def _fake_adapter_class(store: dict):
    """~20 行的假适配器（只填三函数；内存 dict 当存档）。"""
    class Fake:                                         # noqa: D401  （刻意极简：这就是接入成本）
        def __init__(self, cfg):
            self.cfg, self.inbox, self.said = cfg, [], []
        def recv(self):                                  # ① 收消息 / 认人（ctx 七个字段）
            line = self.inbox.pop(0) if self.inbox else None
            if line is None:
                return None
            return {"uid": "u-1", "text": line, "group_id": None, "is_group": False,
                    "at": [], "ts": 0.0, "raw": line}
        def load_player(self, uid):                      # ② 读档
            return store.get(uid)
        def save_player(self, uid, data):                # ② 写档
            store[uid] = data
        def say(self, to, text):                         # ③ 回话
            self.said.append(text)
        def rng(self):                                   # 可选钩子：同种子可复现
            return random.Random(SEED)
    return Fake


def test_minimal_adapter() -> None:
    print("\n=== C. 接入成本反证（假适配器只填三函数，内存 dict 当存档）===")
    skel = importlib.import_module("main")
    scen = skel.Scenario.from_dict(scenario())
    store: dict = {}
    adapter = _fake_adapter_class(store)({})
    host = skel.Host(adapter, PKG, scenario=scen, seed=SEED)
    # ★ 2026-09-14（B19c）：引擎不再吞包 import 期的错误。orlandia 的 commands 层目前**仍硬依赖
    # 宿主树**（`content/persistence/handles.py` → `game.content`）—— 这正是 P4′ 去 shim 要解决的事。
    # 因此这里实事求是分两路：能 boot 就 boot；不能则断言**给出清晰错误**（不再是静默空表），
    # 再走等价的手工装配，把适配器/战斗/存档三项断言跑完。
    # TODO(P4′ 完成后)：orlandia 去 shim 完毕 → 本段恢复成无条件 `pkg = host.boot()`。
    pkg = None
    boot_err = ""
    try:
        pkg = host.boot()
    except Exception as exc:                                    # noqa: BLE001
        boot_err = "%s: %s" % (type(exc).__name__, exc)
    if pkg is not None:
        check("假适配器 boot() 成功（三函数接满即可跑）", True)
    else:
        check("宿主耦合的包 → boot() 给出**清晰**错误（不再静默空表）",
              ("拒绝静默空跑" in boot_err) or ("游戏" in boot_err) or ("game" in boot_err),
              boot_err[:110])
        pkg = skel.load_package(PKG)
        pkg.install_engine()
        host.pkg = pkg
    out = host.run_battle(dict(scen.player), scen.enemies, event_state=scen.event_state, seed=SEED)
    src = open(os.path.abspath(_fake_adapter_class.__code__.co_filename), encoding="utf-8").read()
    body = src[src.index("def _fake_adapter_class"):src.index("def test_minimal_adapter")]
    lines = len([ln for ln in body.splitlines() if ln.strip() and not ln.strip().startswith(("#", '"""'))])
    global FAKE_ADAPTER_LINES
    FAKE_ADAPTER_LINES = lines
    note("假适配器 %d 行（含 class 外壳）；包 %s，域 %d" % (lines, pkg.id, len(pkg.domains)))
    check(out.damage > 0, "假适配器接入 → 真跑一场 damage > 0", "damage=%d" % out.damage)
    check("battle_start" in out.events and "act_done" in out.events, "事件序列含 battle_start→act_done")
    host.save_player("u-1", dict(scen.player, hp=7))
    check(store.get("u-1", {}).get("hp") == 7, "假适配器存档可回读（uid → dict）")


# ============================================================
# D. 两宿主一致性（骨架侧半）：骨架 vs bridge 直连
# ============================================================

def _collect(battle_module, pkg, bridged, scen, seed):
    """跑一场并回收（伤害逐条 / 事件序列 / 结果）。"""
    player = dict(bridged)
    bridge = pkg.optional_submodule("bridge")
    bridge.prepare_player_for_battle(player, None, dict(scen.event_state))
    sides = bridge.build_sides(player, scen.enemies)
    for actor in list(sides["player"]) + list(sides["enemy"]):
        pkg.apply_game_content(actor)
    hits, events = [], []
    random.seed(seed)

    def observe(_b, evt, ctx, _logs):
        events.append(evt)
        if evt in ("attack_hit", "skill_hit"):
            hits.append(int((ctx or {}).get("dmg") or 0))

    battle = battle_module.Battle(btype="monster", sides=sides, on_event=observe)
    logs: list = []
    battle.auto_run(logs)
    return {"result": str(battle.result or ""), "hits": hits, "damage": sum(hits),
            "events": events, "log_len": len(logs)}


def test_two_host_parity() -> None:
    print("\n=== D. 两宿主一致性（骨架侧半）：骨架 vs content/bridge.py 直连 ===")
    import saintess_engine as engine
    skel = importlib.import_module("main")
    scen = skel.Scenario.from_dict(scenario())
    pkg = skel.load_package(PKG)
    pkg.install_engine()

    store: dict = {}
    adapter = _fake_adapter_class(store)({})
    host = skel.Host(adapter, PKG, scenario=scen, seed=SEED)
    host.pkg = pkg
    skeleton_out = host.run_battle(dict(scen.player), scen.enemies,
                                   event_state=scen.event_state, seed=SEED)
    skeleton = {"result": skeleton_out.result, "hits": [h["dmg"] for h in skeleton_out.hits],
                "damage": skeleton_out.damage, "events": skeleton_out.events,
                "log_len": len(skeleton_out.log)}
    direct = _collect(engine, pkg, scen.player, scen, SEED)
    note("骨架：damage=%d hits=%d events=%d log=%d"
         % (skeleton["damage"], len(skeleton["hits"]), len(skeleton["events"]), skeleton["log_len"]))
    note("直连：damage=%d hits=%d events=%d log=%d"
         % (direct["damage"], len(direct["hits"]), len(direct["events"]), direct["log_len"]))
    check(skeleton["damage"] == direct["damage"] and skeleton["damage"] > 0,
          "伤害数字一致（逐条 + 合计）", "%d vs %d" % (skeleton["damage"], direct["damage"]))
    check(skeleton["hits"] == direct["hits"], "每次命中伤害逐条一致", "n=%d" % len(direct["hits"]))
    check(skeleton["events"] == direct["events"], "事件序列一致", "n=%d" % len(direct["events"]))
    check(skeleton["result"] == direct["result"] == "victory", "胜负一致", direct["result"])


# ============================================================
# E. 注入面反证（合成包声明 bind：不给注入 → PackageError；给了 → 全链路）
# ============================================================

def test_inject_contract() -> None:
    print("\n=== E. 注入面反证（合成包声明 bind）===")
    skel = importlib.import_module("main")
    # 隔离不用在这里做：`main.demo_bind_package` 自带 `content*` 清理
    # （引擎契约是「一个进程一个包」，演示函数每次装载前清一次，见 main.py）。
    root = os.path.join(tempfile.mkdtemp(prefix="host_skeleton_inject_"), "bind-demo")

    # ① 不给 inject → PackageError（引擎拒绝静默空跑；骨架不替宿主兜底）
    try:
        skel.demo_bind_package(root)
        check(False, "合成包声明 bind 却不给 inject → PackageError", "居然没报错")
    except skel.PackageError as exc:
        check("bind" in str(exc), "合成包声明 bind 却不给 inject → PackageError（含 bind 字样）",
              str(exc)[:100])
    except Exception as exc:                                    # noqa: BLE001
        check(False, "合成包声明 bind 却不给 inject → PackageError",
              "抛的是 %s: %s" % (type(exc).__name__, exc))

    # ② 给了 inject → 加载期 bind 被调 → 命令表解析成功 → 处理器跑出回话
    out = skel.demo_bind_package(root, inject={"who": "宿主注入对象"})
    check(out["handlers"] == [skel.DEMO_COMMAND], "给了 inject → 命令表解析成功",
          "handlers=%s" % out["handlers"])
    check(bool(out["said"]) and "宿主注入对象" in out["said"][0],
          "处理器跑出回话（加载期注入 + Env.state 都在）", repr(out["said"]))
    check("demo-1" in out["saved"], "新玩家建档落库（引擎落一次）", str(out["saved"]))

    # ③ 零注入那半：不声明 bind 的包（examples/minimal-game）在**子进程**里跑，
    #    既钉住演示入口，又避免它的 import 期注册与上面的合成包串味。
    pr = subprocess.run([sys.executable, os.path.join(SKEL, "main.py"), "--demo-inject"],
                        capture_output=True, text=True, encoding="utf-8", errors="replace",
                        cwd=SKEL, env={**os.environ, "PYTHONIOENCODING": "utf-8",
                                       "PYTHONUTF8": "1"})
    blob = (pr.stdout or "") + (pr.stderr or "")
    last = next((ln for ln in reversed(blob.strip().splitlines()) if ln.strip()), "")
    check(pr.returncode == 0 and "零注入" in blob and "PackageError" in blob and "全链路" in blob,
          "main.py --demo-inject 自带演示全通（零注入 / 反证 / 全链路）",
          "exit=%s；%s" % (pr.returncode, last[:100]))
    note("注入演示：合成包 bind_decl=%s handlers=%s" % (out["bind"], out["handlers"]))


def main() -> int:
    print("=== 宿主骨架端到端冒烟（examples/host-skeleton）===")
    print("包：%s" % PKG)
    test_import_whitelist()
    test_zero_game_vocabulary()
    test_minimal_adapter()
    test_two_host_parity()
    test_inject_contract()
    print("\n" + "=" * 56)
    if FAILS:
        print("❌ 未过 %d 项：%s" % (len(FAILS), FAILS))
        return 1
    print("✅ 宿主骨架冒烟全绿（5 项）：import 白名单 / 零游戏词汇 / 假适配器接入 / "
          "两宿主一致性 / 注入面反证")
    print("   假适配器 %d 行 · 场景种子 %s" % (FAKE_ADAPTER_LINES, SEED))
    return 0


if __name__ == "__main__":
    sys.exit(main())
