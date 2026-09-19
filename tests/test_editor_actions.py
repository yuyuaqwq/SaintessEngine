# -*- coding: utf-8 -*-
"""机制动作清单（E4）门禁：AST 提取 + 编辑器接线（端到端，真起 HTTP）。

守四件事：
  1. **引擎内置动作扫得到**（8 个 `@register_action`）
  2. **参数从实现反推正确** —— 直接下标 → 必填；有默认值 → 类型/默认值正确
  3. **内部参数被过滤**（`_owner` 等装配器注入键不该进配置表单）
  4. **API 接线**（`/api/actions`，含 `--pkg` 与 `fresh`）

为什么这些值得守：编辑器把 `action` 变成「从真实动作里选」，如果扫描悄悄失效，
用户会看到空的候选列表，或更糟 —— 看到**过时的**参数清单（配了不生效）。
"""
import json
import os
import sys
import tempfile
import textwrap
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

from editor import actions as AC            # noqa: E402
from editor import server as SRV            # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "PASS", "FAIL", "FAILURES")


PKG_SRC = '''
from saintess_engine import register_action


@register_action("tst_plain")
def tst_plain(battle, caster, target, params, logs):
    """无参数动作。"""
    return


@register_action("tst_opts")
def tst_opts(battle, caster, target, params, logs):
    """多形态参数：必填 / 默认值 / 内部键。"""
    need = params["must_key"]                 # 直接下标 → 必填
    chance = params.get("chance", 0.25)       # 有默认值 → float
    turns = params.get("turns", 3)            # 有默认值 → int
    label = params.get("label", "x")          # 有默认值 → string
    flag = params.get("forever", False)       # 有默认值 → bool
    owner = params.get("_owner")              # 内部键 → 应被过滤
    return need, chance, turns, label, flag, owner
'''


def main():
    print("== 机制动作清单（E4）门禁 ==")

    # ---------- 1. 引擎内置 ----------
    inv = AC.inventory(None, use_cache=False)
    check("清单 ok=True", inv.get("ok") is True, inv.get("message"))
    names = {a["name"] for a in inv["actions"]}
    eng = [a for a in inv["actions"] if a["source"] == "engine"]
    check(f"引擎内置动作 ≥ 8（实际 {len(eng)}）", len(eng) >= 8)
    for expect in ("apply", "consume", "shield", "cleanse", "cleanse_all",
                   "heal", "interrupt", "damage"):
        check(f"含内置动作 {expect!r}", expect in names)
    check("每条都有 name/source/file/line/func",
          all(a.get("name") and a.get("source") and a.get("file")
              and a.get("line") and a.get("func") for a in inv["actions"]))

    # ---------- 2. 包内动作 + 参数反推 ----------
    pkg = tempfile.mkdtemp(prefix="fw_actions_pkg_")
    mech = os.path.join(pkg, "mech")
    os.makedirs(mech, exist_ok=True)
    with open(os.path.join(mech, "actions.py"), "w", encoding="utf-8") as f:
        f.write(textwrap.dedent(PKG_SRC))

    inv2 = AC.inventory(pkg, use_cache=False)
    pkg_acts = {a["name"]: a for a in inv2["actions"] if a["source"] == "package"}
    check("扫到 2 个包内动作", len(pkg_acts) == 2, sorted(pkg_acts))
    check("包内动作来源标记 = package",
          all(a["source"] == "package" for a in pkg_acts.values()))

    plain = pkg_acts.get("tst_plain")
    check("无参数动作 → params 空", plain is not None and plain["params"] == [],
          plain and plain["params"])

    opts = pkg_acts.get("tst_opts")
    check("有参数动作被找到", opts is not None)
    if opts:
        pm = {p["key"]: p for p in opts["params"]}
        check("参数名集合正确（过滤内部键后）",
              set(pm) == {"must_key", "chance", "turns", "label", "forever"},
              sorted(pm))
        check("内部键 `_owner` 已被过滤", "_owner" not in pm)
        check("直接下标 → 必填", pm.get("must_key", {}).get("required") is True)
        check("有默认值 → 非必填",
              all(pm[k]["required"] is False for k in ("chance", "turns", "label", "forever")))
        check("float 默认值 → type=float + 值 0.25",
              pm["chance"]["type"] == "float" and abs(pm["chance"]["default"] - 0.25) < 1e-9,
              pm["chance"])
        check("int 默认值 → type=int + 值 3",
              pm["turns"]["type"] == "int" and pm["turns"]["default"] == 3, pm["turns"])
        check("string 默认值 → type=string",
              pm["label"]["type"] == "string" and pm["label"]["default"] == "x", pm["label"])
        check("bool 默认值 → type=bool + 值 False",
              pm["forever"]["type"] == "bool" and pm["forever"]["default"] is False,
              pm["forever"])
        check("必填参数排在前面", opts["params"][0]["key"] == "must_key",
              [x["key"] for x in opts["params"]])
        check("docstring 被提取（首段）",
              "多形态参数" in (opts.get("doc") or ""), opts.get("doc"))
    check("suggest_keys 只给必填键", AC.suggest_keys(opts) == ["must_key"],
          AC.suggest_keys(opts))

    # ---------- 3. 缓存策略 ----------
    inv3a = AC.inventory(pkg)                 # 带包 → 不缓存
    with open(os.path.join(mech, "extra.py"), "w", encoding="utf-8") as f:
        f.write('from saintess_engine import register_action\n\n\n'
                '@register_action("tst_added")\n'
                "def tst_added(b, c, t, params, logs):\n"
                '    """后加的动作。"""\n')
    inv3b = AC.inventory(pkg)                 # 应看到新动作（不被缓存挡住）
    check("带包清单**不缓存**（新增动作立刻可见）",
          any(a["name"] == "tst_added" for a in inv3b["actions"]),
          [a["name"] for a in inv3b["actions"] if a["source"] == "package"])
    check("纯引擎清单走缓存（同一对象）", AC.inventory(None) is AC.inventory(None))
    check("use_cache=False 可强制重扫", AC.inventory(None, use_cache=False) is not AC.inventory(None))

    # ---------- 3b. 声明表引用的动作是否都实现了（「声明了没实现」不该静默） ----------
    #   为什么守：`fire()` 对没注册的动作名**静默跳过**（不报错、不触发）——
    #   声明表说「用 passive_xxx」，而没人实现它时，玩法只是"没效果"，没有任何提示。
    rules_dir = os.path.join(pkg, "content", "rules")
    os.makedirs(rules_dir, exist_ok=True)
    with open(os.path.join(rules_dir, "passive_proc.json"), "w", encoding="utf-8") as f:
        json.dump({"p_ok_pkg": {"action": "tst_plain"},                       # 包内实现 ✓
                   "p_ok_engine": {"action": "damage"},                       # 引擎内置 ✓
                   "p_bad": {"action": "nope_verb"},                          # 没实现 ✗
                   "p_bad_also": {"action": "damage",                         # also 里的坏名字也要抓
                                  "also": [{"event": "act_done", "action": "bad_verb"}]}},
                  f, ensure_ascii=False)
    dec = AC.declared_action_names(pkg)
    check("收集到声明引用的动作名（含 also 里的）",
          dec["declared"] == ["bad_verb", "damage", "nope_verb", "tst_plain"], dec["declared"])
    dm = AC.declared_missing(pkg)
    check("★ 只报「没实现」的（包内实现与引擎内置都不报）",
          dm["missing"] == ["bad_verb", "nope_verb"] and dm["ok"] is False, dm["missing"])
    check("报缺口时带上引用它的条目 key（便于定位）",
          dm["sources"].get("nope_verb") == ["p_bad"] and dm["sources"].get("bad_verb") == ["p_bad_also"],
          dm["sources"])

    # 真包当前进度（P4 的进度条：声明了 N 个动作 / 实现了 M 个 / 缺 K 个）
    # ⚠️ 2026-09-13（P4-D2 搬完 96 个动作）后本断言更新为「缺 0」：
    #    此前是「一个都没实现（= 还没搬 mech/）」——那是搬之前的临时事实，别改回去。
    real = AC.declared_missing(os.path.join(ROOT, "games", "orlandia"))
    check("真包：声明引用的动作**全部有实现**（P4-D2 已搬完；缺 0）",
          real["ok"] is True and real["missing"] == [] and real["declared"] > 0,
          f"declared={real['declared']} implemented={real['implemented']} "
          f"missing={len(real['missing'])} {real['missing'][:5]}")
    print(f"    （真包进度：声明 {real['declared']} 个动作 / 已实现 {real['implemented']} 个"
          f"（引擎内置+包内）/ 缺 {len(real['missing'])} 个）")

    # ---------- 4. API 接线 ----------
    gd = tempfile.mkdtemp(prefix="fw_actions_games_")
    SRV.GAMES_DIR = gd
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), SRV.H)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    def get(path):
        try:
            with urllib.request.urlopen(base + path, timeout=60) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, {}

    st, j = get("/api/actions")
    check("GET /api/actions → 200 且 ok", st == 200 and j.get("ok") is True, st)
    check("无包时只有引擎动作", j.get("count", {}).get("package") == 0, j.get("count"))
    check("返回 engine_version", bool(j.get("engine_version")), j.get("engine_version"))

    # 在临时包目录里建一个包 + 一个动作，验证 --pkg 路径
    st, j = get("/api/actions?pkg=nope&fresh=1")
    check("未知包 → 仍返回引擎动作（不炸）", st == 200 and j.get("count", {}).get("engine", 0) >= 8, st)
    httpd.shutdown()

    print(f"\n===== 结果：通过 {PASS} / {PASS + FAIL} =====")
    if FAILURES:
        print("失败项：")
        for f in FAILURES:
            print("  ·", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
