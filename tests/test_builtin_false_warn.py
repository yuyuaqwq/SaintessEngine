# -*- coding: utf-8 -*-
"""`$builtin: false` 全栈作用域门禁 —— 把「整栈总闸」这件事钉死，钉到**两个方向**。

背景
----
`editor/domains.json`（或 `extends/*/domains.json`）里写 `\"$builtin\": false`，
**任何一层**写了它，**整个包栈**都不再带引擎默认域 `commands` / `texts` / `tlogs` ——
因为 `PackageStack.domain_decl()` 逐层 `decl_switch` 之后，共用**一个** `use_builtin`
布尔（先被置 `False` 就再也回不来）。它**不是**「只关掉写它的那一层」。

这个键的**现有语义是公开契约**（`examples/minimal-game` 就在用）⇒ **不改语义**。
本门禁钉的是**两件已经做到、但没被独立钉住的事**：

  ① **响**：某层写了它 ⇒ 装载口发**可读告警**，点名「哪一层写的 + 被跳过的域」。
     静默变响，但**域还是照样丢**（`test_package_stack.py` ⑯b 钉住「不改语义」，
     本文件 §2 从另一头再钉一次）。
  ② **哑**（默认形态）：**不写这个键** ⇒ 零告警、引擎默认域照常在册。
     这条是「不要顺手把开关加进向导」的预防 —— 编辑器「新建包」向导
     （`editor/packages.py::create_package` / `_write_domains_decl`）**不许**写它。

反证（改的时候手验过，本文件把它们钉住）
----------------------------------------
  · 把 `package.py::_domain_warnings` 里 ① 那条 `warns.append(...)` 去掉
    ⇒ §1 的 ① 立刻红（域照样丢，但**没人说话了** = 退化成原来那个静默陷阱）。
  · 让 §1 的告警判据被 monkeypatch 成空 ⇒ 同样红（证明判据真在读 `warnings()`，
    不是自己在旁边另算一份）。
  · 让编辑器向导写 `$builtin` ⇒ §3 的「向导不许写它」当场红。
  · 删掉本文件对 `warnings()` 的依赖、改成直接看域表 ⇒ §1 ① 红
    （域表里域确实没了 —— 只有「响」这条通路能把它变成可发现的）。

跑法：python tests/test_builtin_false_warn.py
"""
import io
import json
import os
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
os.environ.setdefault("GWEN_TEST_MODE", "1")
sys.path.insert(0, FW_ROOT)

from saintess_engine.domains import BUILTIN_DEFAULT_DOMAINS     # noqa: E402
from saintess_engine.package import load_stack, PackageError    # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []

from _check import bind_check                                     # noqa: E402

check = bind_check(globals(), "PASS", "FAIL", "FAILURES")

# 引擎默认域三件 —— 本门禁的「被跳过的东西」必须逐个点名，不能含糊成「少了几个域」。
TRIO = ["commands", "texts", "tlogs"]

GAME_ENTRY = '''# -*- coding: utf-8 -*-
"""探针数据包：什么都不干（域声明的口径验证不需要真装引擎）。"""


def install_engine() -> None:
    return None
'''

EXT_ENTRY = '''# -*- coding: utf-8 -*-
"""探针扩展包：同样什么都不干。"""


def install_engine() -> None:
    return None
'''

# 一个内容域（真源在包）—— 用来证明「扩展包域照旧生效」这半句仍然成立。
SKILL = {"label": "技能", "kind": "data", "schema": "s.json", "primary": "skill"}
EXT_DOMAIN = {"label": "探针域", "kind": "data", "schema": "e.json", "primary": "probe"}


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(text)


def make_game(root, *, domains=None, builtin="unset", depends=(), with_decls=True):
    """造一个数据包。

    `builtin`：`"unset"` = **不写** `$builtin` 键（= 默认形态，①期望零告警）；
    传 `False` = 写 `\"$builtin\": false`；传 `True` = 写 `\"$builtin\": true`。
    刻意支持「不写」这一档 —— 门禁 ② 的全部意义就在「键缺失是默认形态」。
    """
    man = {"id": os.path.basename(root), "name": "探针数据包", "engine": ">=0.1",
           "entry": "content/apply.py"}
    if depends:
        man["depends"] = list(depends)
    _write(os.path.join(root, "game.json"), json.dumps(man, ensure_ascii=False))
    _write(os.path.join(root, "content", "apply.py"), GAME_ENTRY)
    if with_decls:
        decl = {} if builtin == "unset" else {"$builtin": builtin}
        decl.update(domains or {})
        _write(os.path.join(root, "editor", "domains.json"),
               json.dumps(decl, ensure_ascii=False))
    return root


def make_ext(extends_dir, ext_id, *, domains=None, builtin="unset", data=None):
    """造一个扩展包（目录名 == id）。`domains` 写进扩展包自己的 `domains.json`。"""
    root = os.path.join(extends_dir, ext_id)
    _write(os.path.join(root, "game.json"),
           json.dumps({"id": ext_id, "kind": "extension", "name": ext_id,
                       "engine": ">=0.1", "entry": "apply.py"}, ensure_ascii=False))
    _write(os.path.join(root, "apply.py"), EXT_ENTRY)
    if domains is not None:
        decl = {} if builtin == "unset" else {"$builtin": builtin}
        decl.update(domains)
        _write(os.path.join(root, "domains.json"), json.dumps(decl, ensure_ascii=False))
    for kind, table in (data or {}).items():
        for k, v in table.items():
            _write(os.path.join(root, kind, "%s.json" % k), json.dumps(v, ensure_ascii=False))
    return root


def read_decl(stack):
    return sorted(stack.domain_decl())


def warns_of(stack):
    return list(stack.warnings())


def main():
    tmp = tempfile.mkdtemp(prefix="builtin_false_")
    try:
        run(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n===== 结果：通过 %d / %d =====" % (PASS, PASS + FAIL))
    for f in FAILURES:
        print("  · " + f)
    return 1 if FAIL else 0


def run(tmp):
    gd = os.path.join(tmp, "games")
    exts = os.path.join(tmp, "extends")
    os.makedirs(gd)
    os.makedirs(exts)

    # ---------------------------------------------------------------- §1
    print("\n【1. 某层写了 `$builtin: false` ⇒ 警告必须发出，且点名后果】")

    # ① 数据包自己写了它
    g1 = make_game(os.path.join(gd, "off_data"), domains={"skills": SKILL}, builtin=False)
    st1 = load_stack(g1, exts=[exts])
    w1 = warns_of(st1)
    d1 = read_decl(st1)
    check("① 数据包写 `$builtin:false` ⇒ 装载口发告警",
          any("$builtin" in x for x in w1), w1)
    check("① 告警点名**哪一层**写的（是包 id，不是泛泛而谈）",
          any("$builtin" in x and "off_data" in x for x in w1), w1)
    check("① 告警逐个点名**被跳过的三个引擎默认域**（不写「少了几个域」）",
          all(any("$builtin" in x and t in x for x in w1) for t in TRIO), w1)
    check("① ★ 域**确实丢了**（这次是『响的』丢，不是静默丢）",
          not any(t in d1 for t in TRIO) and "skills" in d1, d1)
    check("① 扩展包域不受影响那半句仍成立（没有扩展包时域表 = 引擎默认集 + 自带域）",
          set(d1) == {"skills"}, d1)

    # ② ★ 扩展包那一层写了它 ⇒ 整栈丢（这是「全栈作用域」最反直觉的一格：
    #    写它的甚至不是数据包，而是 depends 进来的扩展包）
    g2 = make_game(os.path.join(gd, "off_ext"), domains={"skills": SKILL}, depends=["ext_off"])
    make_ext(exts, "ext_off", domains={"probe_ext_dom": EXT_DOMAIN}, builtin=False)
    st2 = load_stack(g2, exts=[exts])
    w2 = warns_of(st2)
    d2 = read_decl(st2)
    check("② ★ 扩展包写 `$builtin:false` ⇒ **整栈**丢引擎默认域（不是「只影响那层」）",
          not any(t in d2 for t in TRIO) and "skills" in d2, d2)
    check("② 该告警点名的是**扩展包**的 id",
          any("$builtin" in x and "ext_off" in x for x in w2), w2)
    check("② 扩展包自己声明的域照旧在册（② 那一层不受 `$builtin` 影响）",
          "probe_ext_dom" in d2, d2)

    # ③ 多层里只有一层写了它 ⇒ 照样点名那一层
    g3 = make_game(os.path.join(gd, "off_multi"), domains={"skills": SKILL},
                   depends=["ext_ok", "ext_off2"])
    make_ext(exts, "ext_ok", domains={"probe_ok_dom": EXT_DOMAIN})
    make_ext(exts, "ext_off2", domains={"probe_off_dom": EXT_DOMAIN}, builtin=False)
    st3 = load_stack(g3, exts=[exts])
    w3 = warns_of(st3)
    check("③ 多个扩展包、只有一个写了它 ⇒ 点名那一个，不牵连别人",
          any("$builtin" in x and "ext_off2" in x and "ext_ok" not in x for x in w3), w3)

    # ④ 告警**不改变 ok/errors 口径**（只是响，不是一错）
    from saintess_engine.package import probe_stack
    info = probe_stack(g1, exts=[exts])
    check("④ `probe_stack` 也把它带出来，且 `ok=True` / `errors=[]`（**只报不抛**）",
          info.get("ok") is True and info.get("errors") == []
          and any("$builtin" in x for x in (info.get("warnings") or [])),
          "ok=%s errors=%s warnings=%s"
          % (info.get("ok"), info.get("errors"), info.get("warnings")))

    # ⑤ 真去读一个丢掉的域 ⇒ fail-closed（警告是预告，抛错是兑现）
    try:
        st1.domain_path("commands")
        got = "没抛（不对）"
    except PackageError as e:
        got = "PackageError: %s" % e
    check("⑤ 真去读丢掉的 `commands` ⇒ `PackageError`（fail-closed，不静默给空表）",
          got.startswith("PackageError") and "commands" in got, got)

    # ---------------------------------------------------------------- §2
    print("\n【2. 不写这个键 ⇒ 默认形态：零告警 + 零行为变化（★ 不许顺手加开关）】")

    g6 = make_game(os.path.join(gd, "no_key"), domains={"skills": SKILL}, builtin="unset")
    st6 = load_stack(g6, exts=[exts])
    w6 = warns_of(st6)
    d6 = read_decl(st6)
    check("②a 声明里**没有** `$builtin` 键 ⇒ 引擎默认域三件照常在册",
          all(t in d6 for t in TRIO) and "skills" in d6, d6)
    check("②b 声明里**没有** `$builtin` 键 ⇒ **零** `$builtin` 告警",
          not any("$builtin" in x for x in w6), w6)
    check("②c 声明里**没有** `$builtin` 键 ⇒ 真去读 `commands` 不抛（有兜底声明在册）",
          _read_ok(st6, "commands"), "读不到")
    # 显式写 true 与「不写」等价 —— 证明**键缺失**才是默认形态，两种写法同解
    g7 = make_game(os.path.join(gd, "true_key"), domains={"skills": SKILL}, builtin=True)
    st7 = load_stack(g7, exts=[exts])
    check("②d 显式 `$builtin: true` 与「键缺失」同解（域表与告警都一致）",
          read_decl(st7) == d6 and not any("$builtin" in x for x in warns_of(st7)),
          "%s vs %s" % (read_decl(st7), d6))

    # ---------------------------------------------------------------- §3
    print("\n【3. ★ 编辑器侧预防：向导/写路径**不许**写出 `$builtin`（键缺失 = 默认形态）】")

    sys.path.insert(0, os.path.join(FW_ROOT, "editor"))
    sys.path.insert(0, os.path.join(FW_ROOT, "extends"))
    import editor.packages as EP                                 # noqa: E402

    check("③a 编辑器 `create_package` / `_write_domains_decl` 源码里不出现 `$builtin` 赋值",
          not _src_emits_builtin_key(), _SRC_HITS)

    # 真跑一次向导，产物里不许有这个键
    gd_wiz = os.path.join(tmp, "wiz_games")
    os.makedirs(gd_wiz)
    made = EP.create_package("wiz_probe", "向导探针", domains=["commands"],
                             games_dir_=gd_wiz)
    decl_path = os.path.join(gd_wiz, "wiz_probe", "editor", "domains.json")
    raw = json.loads(io.open(decl_path, encoding="utf-8").read())
    check("③b 向导产出的 `editor/domains.json` 里**没有** `$builtin` 键",
          "$builtin" not in raw, sorted(raw))
    check("③c 向导产出的声明里**至少带上引擎默认域三件**（不然新生包一出生就吃告警）",
          all(t in raw for t in TRIO), sorted(raw))
    check("③d 向导产物可直接装载且**零** `$builtin` 告警",
          not any("$builtin" in x
                  for x in load_stack(os.path.join(gd_wiz, "wiz_probe"),
                                      exts=[exts, os.path.join(FW_ROOT, "extends")]).warnings()),
          "产物 id=%s" % made.get("id"))
    check("③e 向导产物不带 `$builtin_defaults` 键（两个开关名都不许写）",
          "$builtin_defaults" not in raw, sorted(raw))


def _read_ok(stack, dom):
    try:
        stack.domain_path(dom, required=False)
        return True
    except Exception:                                              # noqa: BLE001
        return False


# ── 源码扫描：编辑器**写**路径不许出现 `$builtin` 键（读侧 pop / 告警文案不算）──
_SRC_HITS = []


def _src_emits_builtin_key():
    """扫 `editor/*.py`：除了「读（pop / in / .get）」与告警文案，**不许**写出这个键。"""
    _SRC_HITS.clear()
    ed = os.path.join(FW_ROOT, "editor")
    for fn in sorted(os.listdir(ed)):
        if not fn.endswith(".py"):
            continue
        with io.open(os.path.join(ed, fn), encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                if "$builtin" not in line:
                    continue
                s = line.strip()
                # 读侧（剥键 / 判存在 / 报错文案）与纯注释一律不算「写」
                if s.startswith("#"):
                    continue
                if any(k in s for k in ('.pop(', 'in holder', 'if opt in',
                                        'f"', "f'", 'warns.append', '"""')):
                    continue
                _SRC_HITS.append("%s:%d %s" % (fn, i, s))
    return not _SRC_HITS


if __name__ == "__main__":
    sys.exit(main())
