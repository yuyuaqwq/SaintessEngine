# -*- coding: utf-8 -*-
"""门禁：包根发现口 + 包内一行声明读表口。

为什么有它（2026-09-20 T4 第 4 轮 · W8「包可减代码」）
------------------------------------------------------
包内 13 个模块各自手抄同一段装配样板 ——

    _HERE = os.path.dirname(os.path.abspath(__file__))     # <pkg>/content
    _PKG_ROOT = os.path.dirname(_HERE)                     # <pkg>
    _R = set_from_domains(_PKG_ROOT, ("maps", "subareas"))

其中「包根 = 最近含包内域声明的那一层」这个约定本来就是引擎的（DEFAULT_DECL =
editor/domains.json，read_domain_decl 已按它读）。本门禁钉住把它收成引擎口之后的语义：

  A. package_root_of(模块文件)：从模块所在目录从近到远取第一层含声明的目录；
     深度无关（content/x.py 与 content/flow/deep/x.py 同根）；
  B. 最近者胜：嵌套包（内层自己也有声明）取内层 —— 部署里包被检进别的树时不会误取外层；
  C. fail-closed：找不到 → RecordsDeclarationError（点名起点与试过的层）；
     不返回空串、不返回当前目录兜底；limit 上限生效；
  D. set_from_module(...) 与 set_from_domains(package_root_of(...), ...) 逐字等价
     （同一份表；声明缺项 / 缺文件两边同样抛）；
  E. decl= 可覆盖（包改布局时两边一起改）。

跑法：python tests/test_records_from_module.py
退出码：0 = 全过；1 = 有失败。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

PASS = 0
FAIL = 0
FAILURES = []

from _check import bind_check                                  # noqa: E402
check = bind_check(globals(), "PASS", "FAIL", "FAILURES")

from saintess_engine import records as R                       # noqa: E402
import _domain_fixtures as FX                                  # noqa: E402

def _canon(o) -> str:
    return json.dumps(o, ensure_ascii=False, separators=(",", ":"), sort_keys=False, default=str)


def _sha(o) -> str:
    return hashlib.sha256(_canon(o).encode("utf-8")).hexdigest()[:16]


def _raises(fn) -> bool:
    """调 fn；抛 RecordsDeclarationError 记 True（其它异常 / 不抛都记 False）。"""
    try:
        fn()
    except R.RecordsDeclarationError:
        return True
    except Exception:                                          # noqa: BLE001
        return False
    return False


def _mkpkg(root, doms=("items",), rows=None):
    """造合成包：<root>/editor/domains.json + <root>/content/data/<域>.json。"""
    FX.declare(root, *doms)
    ddir = os.path.join(root, "content", "data")
    os.makedirs(ddir, exist_ok=True)
    for d in doms:
        with open(os.path.join(ddir, "%s.json" % (d,)), "w", encoding="utf-8") as f:
            json.dump(rows or {"it_a": {"name": "甲"}, "it_b": {"name": "乙"}}, f,
                      ensure_ascii=False)
    return root


def _decl_then_missing(tmp):
    """声明里有 classes 但盘上没有该文件 ⇒ 应当抛（D4 用）。"""
    pkg2 = os.path.join(tmp, "pkg2")
    FX.declare(pkg2, "classes")
    os.makedirs(os.path.join(pkg2, "content", "data"), exist_ok=True)
    return R.set_from_module(os.path.join(pkg2, "content", "x.py"), ("classes",))

def main() -> int:
    tmp = tempfile.mkdtemp(prefix="t4r4_recmod_")
    cwd0 = os.getcwd()
    try:
        pkg = _mkpkg(os.path.join(tmp, "pkg"))
        src = os.path.join(pkg, "content", "x.py")
        open(src, "w", encoding="utf-8").close()

        # ---- A. 基本 + 深度无关 + 相对路径 ----
        check("A1 包根 = 最近含声明的祖先目录", R.package_root_of(src) == pkg,
              R.package_root_of(src))
        deep = os.path.join(pkg, "content", "flow", "deep", "y.py")
        os.makedirs(os.path.dirname(deep), exist_ok=True)
        open(deep, "w", encoding="utf-8").close()
        check("A2 深度无关（content/flow/deep/y.py 同根）",
              R.package_root_of(deep) == pkg, R.package_root_of(deep))
        os.chdir(tmp)
        check("A3 相对路径也认（内部先 abspath）",
              R.package_root_of(os.path.join("pkg", "content", "x.py")) == pkg)
        os.chdir(cwd0)

        # ---- B. 最近者胜 ----
        inner = _mkpkg(os.path.join(pkg, "inner"))
        isrc = os.path.join(inner, "content", "x.py")
        open(isrc, "w", encoding="utf-8").close()
        check("B1 嵌套包取内层（最近者胜，不误取外层）",
              R.package_root_of(isrc) == inner, R.package_root_of(isrc))

        # ---- C. fail-closed ----
        bare = os.path.join(tmp, "bare", "content")
        os.makedirs(bare, exist_ok=True)
        bsrc = os.path.join(bare, "z.py")
        open(bsrc, "w", encoding="utf-8").close()
        try:
            got = R.package_root_of(bsrc)
            check("C1 找不到声明 → 必须抛（不返回兜底）", False, "返回了 %r" % (got,))
        except R.RecordsDeclarationError as exc:
            msg = str(exc)
            check("C1 找不到声明 → 抛 RecordsDeclarationError", True)
            flat = msg.replace(chr(92), "/")
            check("C2 报错点名起点与试过的层",
                  bare.replace(chr(92), "/") in flat and "试过" in msg, msg[:140])
        check("C3 limit 生效（limit=0 只看起点 ⇒ 够不着包根）",
              _raises(lambda: R.package_root_of(src, limit=0)))
        check("C4 limit=1 够得着（起点 content/ 的上一层就是 pkg/）",
              R.package_root_of(src, limit=1) == pkg)

        # ---- D. 一行式 == 两步式（逐字等价） ----
        one = R.set_from_module(src, ("items",))
        two = R.set_from_domains(R.package_root_of(src), ("items",))
        a1, b1 = one.items.all(), two.items.all()
        check("D1 set_from_module 表 == set_from_domains(package_root_of) 表",
              _sha(a1) == _sha(b1), "%s vs %s" % (_sha(a1), _sha(b1)))
        check("D2 表内容真的是包内那份（不是空表）",
              len(one.items.all()) == 2 and one.items.get("it_a")["name"] == "甲",
              one.items.all())
        check("D3 未声明的域：两边同样抛（fail-closed 没放松）",
              _raises(lambda: R.set_from_module(src, ("skills",)))
              and _raises(lambda: R.set_from_domains(pkg, ("skills",))))
        check("D4 声明了但文件缺：两边同样抛（不静默空表）",
              _raises(lambda: _decl_then_missing(tmp)))

        # ---- E. decl= 覆盖 ----
        shutil.copyfile(os.path.join(pkg, "editor", "domains.json"),
                        os.path.join(pkg, "editor", "other.json"))
        check("E1 decl= 覆盖时按自定义声明找根",
              R.package_root_of(src, decl="editor/other.json") == pkg)
        try:
            R.package_root_of(src, decl="editor/nope.json")
            check("E2 自定义 decl 不存在 → 抛", False)
        except R.RecordsDeclarationError:
            check("E2 自定义 decl 不存在 → 抛", True)

        # ---- F. 真包交叉核（在位才跑） ----
        real = os.path.join(ROOT, "games", "orlandia")
        if os.path.isfile(os.path.join(real, "editor", "domains.json")):
            probe = os.path.join(real, "content", "index_build.py")
            check("F1 真包：content/index_build.py → 包根",
                  R.package_root_of(probe) == real, R.package_root_of(probe))
            realr = R.set_from_module(probe, ("equipment",))
            check("F2 真包：一行式能建 equipment 读口（非空）",
                  len(realr.equipment.all()) > 0, len(realr.equipment.all()))
        else:
            print("  （真包 games/orlandia 不在位 ⇒ F 段跳过）")
    finally:
        os.chdir(cwd0)
        shutil.rmtree(tmp, ignore_errors=True)

    print("")
    print("===== 结果：通过 %d / %d =====" % (PASS, PASS + FAIL))
    for f in FAILURES:
        print("  · " + f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())