# -*- coding: utf-8 -*-
"""包栈加载器门禁（`saintess_engine/package.py`）。

守三件事：

1. **栈的形状** —— 扩展包（可互相依赖，按拓扑序加载）+ 数据包（进程内唯一，永远最后）。
2. **命名空间隔离** —— 数据包固定 `content`；扩展包用自己的 id 作命名空间 ⇒
   同一进程里装多个扩展包不会撞名（这是「一个进程一个数据包 + 多个扩展包」的地基）。
3. **域分层** —— 引擎默认集 → 扩展包（默认值）→ 数据包（真源，**整份覆盖**前层）；
   声明与数据都分层，取值取层序里最靠后的那一份。

错误路径全部 fail-closed（可读错误、点名到底哪一层出的问题）：
缺 game.json / 声明了入口却缺文件 / 版本门槛不过 / 缺 install_engine /
依赖的扩展包找不到 / 依赖成环 / 扩展包依赖数据包 / `kind` 不认识。

跑法：python tests/test_package_stack.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

PASS = 0
FAIL = 0
FAILURES = []
check = bind_check(globals(), "PASS", "FAIL", "FAILURES")

# ---- 探针源 ----

GAME_ENTRY = '''# -*- coding: utf-8 -*-
"""探针数据包：注册一个动作 + 声明自己的域 + 覆盖扩展包给的默认域。"""
from ext_combat import register_action


@register_action("probe_game_verb")
def probe_game_verb(battle, caster, target, params, logs):     # noqa: ARG001
    logs.append("game")


def install_engine() -> None:
    import ext_combat.battle.formulas as formulas
    from saintess_engine import config
    config.mount(formulas=formulas)


def apply_game_content(actor):
    return actor
'''

EXT_ENTRY = '''# -*- coding: utf-8 -*-
"""探针扩展包：注册一个动作（用**自己命名空间**的模块），证明命名空间隔离。"""
from ext_combat import register_action
from . import helper          # 包内相对导入（命名空间不同也不冲突）


@register_action("probe_ext_verb")
def probe_ext_verb(battle, caster, target, params, logs):      # noqa: ARG001
    logs.append(helper.TAG)


def install_engine() -> None:
    return None
'''

EXT_HELPER = '''# -*- coding: utf-8 -*-
TAG = "ext"
'''


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def make_game(root, *, manifest=None, domains=None, data=None, entry=GAME_ENTRY, with_entry=True,
              builtin=False):
    """造一个数据包（`content/` 布局）。

    `builtin`：写进 `editor/domains.json` 的 `$builtin` 值（缺省 `False` = 本文件历史口径）；
    传 `None` ⇒ 写一份**不带 `$builtin` 键**的声明（= 引擎默认域照常兜底）。★ P-3 门禁要造
    「关掉默认集」与「默认集在册」两种包，故这个键可拨；`domains` 不给 ⇒ 照样不写声明文件。
    """
    man = {"id": "probe_game", "name": "探针数据包", "engine": ">=0.1", "entry": "content/apply.py"}
    man.update(manifest or {})
    _write(os.path.join(root, "game.json"), json.dumps(man, ensure_ascii=False))
    if with_entry:
        _write(os.path.join(root, "content", "apply.py"), entry)
    if domains:
        decl = {} if builtin is None else {"$builtin": builtin}
        decl.update(domains)
        _write(os.path.join(root, "editor", "domains.json"), json.dumps(decl, ensure_ascii=False))
    for kind, table in (data or {}).items():
        for name, value in table.items():
            _write(os.path.join(root, "content", kind, "%s.json" % name),
                   json.dumps(value, ensure_ascii=False))
    return root


def make_ext(extends_dir, ext_id, *, manifest=None, domains=None, data=None, entry=EXT_ENTRY):
    """造一个扩展包（目录名 == id —— 命名空间靠它取唯一 import 名）。"""
    root = os.path.join(extends_dir, ext_id)
    man = {"id": ext_id, "kind": "extension", "name": ext_id, "engine": ">=0.1", "entry": "apply.py"}
    man.update(manifest or {})
    _write(os.path.join(root, "game.json"), json.dumps(man, ensure_ascii=False))
    _write(os.path.join(root, "apply.py"), entry)
    _write(os.path.join(root, "helper.py"), EXT_HELPER)
    if domains:
        _write(os.path.join(root, "domains.json"), json.dumps(dict({"$builtin": False}, **domains),
                                                             ensure_ascii=False))
    for kind, table in (data or {}).items():
        for name, value in table.items():
            _write(os.path.join(root, kind, "%s.json" % name), json.dumps(value, ensure_ascii=False))
    return root


PROBE = '''
import json, sys
sys.path.insert(0, {root!r})
from saintess_engine.package import load_stack, plan_stack, PackageError
out = {{}}
try:
    plan = plan_stack({game!r}, exts={exts!r})
    out["ordered"] = [[p["kind"], p["id"], p["namespace"]] for p in plan]
    stack = load_stack({game!r}, exts={exts!r})
    from ext_combat.battle.effects import action_names
    out["ok"] = True
    out["ids"] = stack.ids
    out["actions"] = sorted(action_names())
    # ★ P-3（2026-09-26）：装载告警（只读；合并/取值路径一字不动）
    out["warnings"] = list(stack.warnings())
    out["decl_keys"] = sorted(stack.domain_decl())
    try:
        from saintess_engine.package import probe_stack
        _info = probe_stack({game!r}, exts={exts!r})
        out["probe_ok"] = _info.get("ok")
        out["probe_errors"] = list(_info.get("errors") or [])
        out["probe_warnings"] = list(_info.get("warnings") or [])
    except Exception as e:
        out["probe_err"] = "%s: %s" % (type(e).__name__, e)
    try:
        out["layered"] = stack.domain("probe_rules")
        out["layers"] = [list(x) for x in stack.domain_layers("probe_rules")]
    except Exception as e:
        out["layered_err"] = str(e)
    try:
        out["ext_only"] = stack.domain("ext_only_domain")
    except Exception as e:
        out["ext_only_err"] = str(e)
except PackageError as e:
    out["ok"] = False
    out["err"] = str(e)
except Exception as e:
    out["ok"] = False
    out["err"] = "%s: %s" % (type(e).__name__, e)
print("__R__" + json.dumps(out, ensure_ascii=False))
'''


def run_probe(game, exts=()):
    """在**子进程**里跑（一个进程只装一个数据包 + 命名空间靠 sys.modules 缓存，必须隔离）。"""
    code = PROBE.format(root=ROOT, game=game, exts=list(exts))
    # cwd 必须是**干净的仓根**：临时目录里若有同名 .py（历史上真出现过 types.py）
    # 会以 sys.path[0] 的身份抢先导入，把子进程毒成 import 失败。
    pr = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                        timeout=240, cwd=ROOT)
    line = ""
    for ln in (pr.stdout or "").splitlines():
        if ln.startswith("__R__"):
            line = ln[5:]
    try:
        return json.loads(line)
    except Exception:                                          # noqa: BLE001
        return {"ok": False, "err": (pr.stderr or "")[-400:]}


RULE_DECL = {"probe_rules": {"label": "探针规则", "kind": "rules", "schema": "x.json",
                             "primary": "probe_rule", "icon": "📜"}}
EXT_DECL = dict(RULE_DECL, **{"ext_only_domain": {"label": "扩展包独有域", "kind": "data",
                                                  "schema": "y.json", "primary": "z", "icon": "🧩"}})


def main():
    print("== 包栈加载器门禁（saintess_engine/package.py）==")
    tmp = tempfile.mkdtemp(prefix="fw_stack_")
    ext_dir = os.path.join(tmp, "extends")
    game = make_game(os.path.join(tmp, "probe_game"),
                     manifest={"depends": ["ext_a", "ext_b"]},
                     domains=RULE_DECL,
                     data={"rules": {"probe_rules": {"src": "game", "v": 2}}})
    make_ext(ext_dir, "ext_a", domains=EXT_DECL,
             data={"rules": {"probe_rules": {"src": "ext_a", "v": 1}},
                   "data": {"ext_only_domain": {"x": 1}}})
    make_ext(ext_dir, "ext_b", manifest={"depends": ["ext_a"]})

    r = run_probe(game, exts=[ext_dir])
    check("① 栈加载成功", r.get("ok") is True, str(r)[:300])
    ids = r.get("ids") or []
    check("② 拓扑序：被依赖者在前、数据包永远最后",
          ids == ["ext_a", "ext_b", "probe_game"], str(ids))
    check("③ 命名空间：数据包 = content，扩展包 = 自己的 id",
          r.get("ordered") == [["extension", "ext_a", "ext_a"], ["extension", "ext_b", "ext_b"],
                               ["game", "probe_game", "content"]], str(r.get("ordered")))
    acts = r.get("actions") or []
    check("④ 两层的动作都注册进了引擎（数据包 + 扩展包，命名空间互不冲突）",
          "probe_game_verb" in acts and "probe_ext_verb" in acts, str(acts[-8:]))
    check("⑤ 域分层：数据包那份**整份覆盖**扩展包的默认值",
          (r.get("layered") or {}).get("src") == "game", str(r.get("layered")))
    check("⑥ 域分层：扩展包独有的域照样读得到（数据包不用重复声明数据）",
          (r.get("ext_only") or {}) == {"x": 1}, str(r.get("ext_only")) or str(r.get("ext_only_err")))
    check("⑦ 能查出该域的值到底来自哪几层（审计用）",
          [x[0] for x in (r.get("layers") or [])] == ["ext_a", "probe_game"],
          str(r.get("layers")))

    # ---- ★ P-3（2026-09-26）装载口告警：只加警告，语义/逐文件作用域一字不动 ----
    print("\n【P-3. 装载告警（只报不改语义）】")
    w = r.get("warnings") or []
    check("⑯ `$builtin:false` 不再静默跳过：告警点名「哪一层写的 + 被跳过的域」",
          any("$builtin" in x and "probe_game" in x and "commands" in x and "texts" in x
              and "tlogs" in x for x in w), str(w))
    check("⑯b 告警**不改语义**：有效域表仍只有两层声明的那两个（引擎默认域照旧被跳过）",
          set(r.get("decl_keys") or []) == {"probe_rules", "ext_only_domain"},
          str(r.get("decl_keys")))
    check("⑯c `probe_stack` 也把告警带出来，且 ok / errors 口径不变（只加了 `warnings` 键）",
          r.get("probe_ok") is True and r.get("probe_errors") == []
          and any("$builtin" in x for x in (r.get("probe_warnings") or [])),
          f"ok={r.get('probe_ok')} errors={r.get('probe_errors')} "
          f"warnings={r.get('probe_warnings')}")

    g10 = make_game(os.path.join(tmp, "probe_game10"), domains=RULE_DECL, builtin=None)
    r10 = run_probe(g10)
    w10 = r10.get("warnings") or []
    check("⑰ 引擎默认域「在册但所有层都没有文件」⇒ 装载时就报出来（点名三个域）",
          r10.get("ok") is True
          and sum("声明的文件在**所有层**里都不存在" in x for x in w10) == 3
          and all(d in " ".join(w10) for d in ("commands", "texts", "tlogs")), str(w10))
    check("⑰b 没写 `$builtin` 键 ⇒ 不产「关掉默认集」那条（告警是判别的，不是恒亮）",
          not any("$builtin" in x for x in w10), str(w10))
    check("⑰c 域表照旧兜底引擎默认集（三域在册，读法一字没变）",
          {"commands", "texts", "tlogs"} <= set(r10.get("decl_keys") or []),
          str(r10.get("decl_keys")))

    g11 = make_game(os.path.join(tmp, "probe_game11"), domains=RULE_DECL, builtin=None,
                    data={"data": {"commands": {}, "texts": {}, "tlogs": {}}})
    r11 = run_probe(g11)
    check("⑱ 反证（两态）：同一份包把三张表都建出来 ⇒ 那三条告警消失（有牙）",
          r11.get("ok") is True
          and not any("不存在" in x for x in (r11.get("warnings") or [])),
          str(r11.get("warnings")))
    check("⑱b `$builtin:false` 那条也不亮（它没写这个键）",
          not any("$builtin" in x for x in (r11.get("warnings") or [])),
          str(r11.get("warnings")))

    # ---- 错误路径 ----
    g2 = make_game(os.path.join(tmp, "probe_game2"), manifest={"depends": ["nope"]})
    r2 = run_probe(g2, exts=[ext_dir])
    check("⑧ 依赖的扩展包找不到 → 报错并点名「谁要的、要谁」",
          r2.get("ok") is False and "nope" in (r2.get("err") or ""), str(r2.get("err"))[:160])

    cycle_dir = os.path.join(tmp, "cycle")
    make_ext(cycle_dir, "cyc_a", manifest={"depends": ["cyc_b"]})
    make_ext(cycle_dir, "cyc_b", manifest={"depends": ["cyc_a"]})
    g3 = make_game(os.path.join(tmp, "probe_game3"), manifest={"depends": ["cyc_a"]})
    r3 = run_probe(g3, exts=[cycle_dir])
    check("⑨ 依赖成环 → 报错并打印环",
          r3.get("ok") is False and "环" in (r3.get("err") or ""), str(r3.get("err"))[:160])

    back_dir = os.path.join(tmp, "backward")
    make_ext(back_dir, "back_ext", manifest={"depends": ["probe_game"]})
    g4 = make_game(os.path.join(tmp, "probe_game4"), manifest={"depends": ["back_ext"]})
    r4 = run_probe(g4, exts=[back_dir])
    check("⑩ 扩展包依赖数据包 → 报错（方向错了）",
          r4.get("ok") is False and "方向" in (r4.get("err") or ""), str(r4.get("err"))[:160])

    bad_kind_dir = os.path.join(tmp, "badkind")
    root_bk = make_ext(bad_kind_dir, "bk")
    _write(os.path.join(root_bk, "game.json"),
           json.dumps({"id": "bk", "kind": "plugin", "entry": "apply.py"}, ensure_ascii=False))
    g5 = make_game(os.path.join(tmp, "probe_game5"), manifest={"depends": ["bk"]})
    r5 = run_probe(g5, exts=[bad_kind_dir])
    check("⑪ kind 不认识 → 报错（只认 game / extension）",
          r5.get("ok") is False and "kind" in (r5.get("err") or ""), str(r5.get("err"))[:160])

    empty_dir = os.path.join(tmp, "empty")
    os.makedirs(empty_dir, exist_ok=True)
    g6 = make_game(os.path.join(tmp, "probe_game6"))
    r6 = run_probe(g6, exts=[empty_dir])
    check("⑫ 无扩展包也能跑（纯数据包的老用法不被破坏）",
          r6.get("ok") is True and (r6.get("ids") or []) == ["probe_game"], str(r6)[:200])

    g7 = make_game(os.path.join(tmp, "probe_game7"), with_entry=False)
    r7 = run_probe(g7)
    check("⑬ 声明了 entry 却缺文件 → 报错",
          r7.get("ok") is False and "不存在" in (r7.get("err") or ""), str(r7.get("err"))[:160])

    g8 = make_game(os.path.join(tmp, "probe_game8"), manifest={"engine": ">=99.0"})
    r8 = run_probe(g8)
    check("⑭ 版本门槛不过 → 报错（装配半个引擎比不装配更难查）",
          r8.get("ok") is False and "门槛" in (r8.get("err") or ""), str(r8.get("err"))[:160])

    g9 = os.path.join(tmp, "probe_nomanifest")
    os.makedirs(os.path.join(g9, "content"), exist_ok=True)
    r9 = run_probe(g9)
    check("⑮ 缺 game.json → 报错并点名文件",
          r9.get("ok") is False and "game.json" in (r9.get("err") or ""), str(r9.get("err"))[:160])

    print(f"\n===== 结果：通过 {PASS} / {PASS + FAIL} =====")
    for f in FAILURES:
        print("  ·", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
