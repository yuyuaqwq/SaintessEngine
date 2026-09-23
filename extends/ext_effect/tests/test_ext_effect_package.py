# -*- coding: utf-8 -*-
"""`ext_effect` 扩展包门禁（B7a：场景交互效果层 POI 从数据包抽进扩展包）。

钉四件事：

1. **包契约**：`game.json` 的 `id` / `kind` / `entry` 自洽；`install_engine()` 是**显式空实现**
   （纯形状库 —— 不留含糊空壳）。
2. **形状可用**：`POI_EFFECTS` 注册表非空、`PoiContext` / `execute_poi` / `register` 都在；
   现场 `register` 一个演示效果 → `execute_poi` 能取到并返回它给的东西；未注册的键 → `None`。
3. ★ **注入面 fail-loud**：`ctx.text` / `ctx.static` 不传 = **访问即** `AttributeError`（带指引）；
   `ctx.host` / `ctx.dom` 不传 = `None`（逐字继承原契约：**用起来才炸**）—— 四样都是这层仅有的
   「读」出口，缺了必炸、绝不静默吞。
4. ★ **可换游戏**：本包（含子目录）的 `.py` **零 import 数据包**（`content` / `content.*`）——
   AST 扫描 + 两条反证。

跑法：python extends/ext_effect/tests/test_ext_effect_package.py
"""
from __future__ import annotations

import ast
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG_DIR = os.path.dirname(HERE)                       # extends/ext_effect
FW_ROOT = os.path.dirname(os.path.dirname(PKG_DIR))   # 引擎仓根
for _p in (HERE, FW_ROOT, os.path.join(FW_ROOT, "extends")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _check import bind_check                          # noqa: E402

PASS = 0
FAILS: list = []
check = bind_check(globals(), "PASS", failures="FAILS")


def content_imports(src: str) -> list:
    """源码里所有「导入数据包」的模块名（`content` / `content.*`）。"""
    out = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return ["<语法错误>"]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names
                    if a.name == "content" or a.name.startswith("content.")]
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level:                                # 包内相对导入：本包局部的活
                continue
            if mod == "content" or mod.startswith("content."):
                out.append(mod)
    return out


def pack_sources() -> list:
    out = []
    for dp, dn, fn in os.walk(PKG_DIR):
        dn[:] = [d for d in dn if d != "__pycache__"]
        for f in fn:
            if f.endswith(".py"):
                out.append(os.path.join(dp, f))
    return sorted(out)


def main() -> int:
    print("=== ext_effect 扩展包门禁（包契约 · 形状可用 · 注入面 fail-loud · 零数据包依赖）===")

    # ------------------------------------------------------------ 1. 包契约
    with open(os.path.join(PKG_DIR, "game.json"), encoding="utf-8") as f:
        man = json.load(f)
    check("game.json id == ext_effect（目录名 = id = 命名空间）",
          man.get("id") == "ext_effect", man.get("id"))
    check("kind == extension（扩展包）", man.get("kind") == "extension", man.get("kind"))
    check("entry == apply.py（包根入口惯例）", man.get("entry") == "apply.py", man.get("entry"))

    from ext_effect.apply import install_engine
    check("install_engine() 是显式空实现（返回 None，不往引擎塞东西）",
          callable(install_engine) and install_engine() is None, None)

    # ------------------------------------------------------------ 2. 形状可用
    from ext_effect.effects import POI_EFFECTS, PoiContext, execute_poi, register
    check("POI_EFFECTS 是非空注册表（16+ 个效果键）",
          isinstance(POI_EFFECTS, dict) and len(POI_EFFECTS) >= 16, len(POI_EFFECTS))
    check("PoiContext / execute_poi / register 三个名字都在",
          all(callable(x) for x in (PoiContext, execute_poi, register)), None)
    check("未注册的效果键 → None（调用方显式告警，不静默 fallback）",
          execute_poi("__不存在的效果__", None) is None, None)

    @register("__demo_effect__")
    def _demo(ctx):
        """演示效果：只回一行文案（证明注册表 → 执行器这条链是活的）。"""
        return ctx.text("demo.key", n=ctx.poi.get("n"))

    class _Ctx:
        """最小替身：只有 `poi` 与 `text`（execute_poi 只要求 handler 拿得到 ctx）。"""

        poi = {"n": 7}
        text = staticmethod(lambda key, **slots: "%s|%s" % (key, sorted(slots.items())))

    check("register 进去的效果能被 execute_poi 取到并执行（链是活的）",
          execute_poi("__demo_effect__", _Ctx()) == "demo.key|[('n', 7)]",
          execute_poi("__demo_effect__", _Ctx()))
    POI_EFFECTS.pop("__demo_effect__", None)              # 跑完还原，不污染注册表
    check("演示效果已从注册表移除（不留测试残留）", "__demo_effect__" not in POI_EFFECTS, None)

    # ------------------------------------------------------------ 3. 注入面 fail-loud
    def _mk(**kw):
        return PoiContext("g", "u", {}, {}, "p1", {"name": "演示点"}, **kw)

    # text / static：**访问即炸**（本层新增的属性，报错带可读指引）
    for attr in ("text", "static"):
        ctx = _mk()
        try:
            getattr(ctx, attr)
            err = None
        except AttributeError as exc:
            err = str(exc)
        check("不传 %-6s ⇒ 访问即 AttributeError（fail-loud）" % attr, bool(err), err)
        check("不传 %-6s 的报错带可读指引（说清怎么补）" % attr,
              bool(err) and "注入面缺失" in err, err)

    # host / dom：**用起来才炸**（逐字继承原契约：不传 = None，取件即 None.xxx → AttributeError）
    for attr in ("host", "dom"):
        ctx = _mk()
        check("不传 %-6s ⇒ 取值是 None（原契约：用到才炸）" % attr,
              getattr(ctx, attr) is None, getattr(ctx, attr))
        try:
            getattr(getattr(ctx, attr), "任意属性")
            err2 = None
        except AttributeError as exc:
            err2 = str(exc)
        check("不传 %-6s 时一旦真用它 ⇒ AttributeError" % attr, bool(err2), err2)

    sentinel = object()
    check("传了 text ⇒ 原样返回（不是包装层）", _mk(text=sentinel).text is sentinel, None)
    check("传了 static ⇒ 原样返回", _mk(static=sentinel).static is sentinel, None)
    check("传了 host / dom ⇒ 原样可用", _mk(host=sentinel, dom=sentinel).dom is sentinel, None)

    # ------------------------------------------------------------ 5. 药水半边（B7b）：模块级注入面
    from ext_effect.effects import potion_effects as PE

    check("POTION_EFFECTS 注册表非空（36 键药水效果）",
          isinstance(PE.POTION_EFFECTS, dict) and len(PE.POTION_EFFECTS) >= 30,
          len(PE.POTION_EFFECTS))

    def _raises(fn) -> str:
        try:
            fn()
        except Exception as exc:                                  # noqa: BLE001
            return "%s: %s" % (type(exc).__name__, exc)
        return ""

    check("★ 未 bind 时文案句柄**取用即报错**（fail-loud，不给空串）",
          bool(_raises(lambda: PE._T.text("potion.任意"))),
          _raises(lambda: PE._T.text("potion.任意")))
    check("★ 未 bind 时 `_resolve()` 报错（不给空表 → 不静默失效）",
          bool(_raises(lambda: PE._resolve(None, "rage"))),
          _raises(lambda: PE._resolve(None, "rage")))
    check("★ 未 bind 时域读口报错（items / rules / neg_keys 三处同款）",
          all(_raises(fn) for fn in (PE._items_domain, PE._effect_rules,
                                     PE._purify_neg_keys)), None)

    _d_obj = PE.DEFAULTS                                    # 记住对象身份（下面验「就地刷新」）
    PE.bind(text=lambda k, **s: "T:" + k,
            static=lambda k: "S:" + k,
            items={"__demo_item__": {"effect": "heal_up", "effect_data": {"pct": 5}}},
            rules={"rage": {"name": "怒气", "cap": 10}},
            neg_keys={"purify_neg_keys": {"keys": ["poison", "burn"]}})
    check("★ bind 后 DEFAULTS **就地刷新**（同一 dict 对象 ⇒ `from … import DEFAULTS` 的消费方也看得到新值）",
          PE.DEFAULTS is _d_obj and bool(PE.DEFAULTS), (PE.DEFAULTS is _d_obj, len(PE.DEFAULTS)))
    check("bind 后文案渲染走**注入的**函数（不是第二份文案表）",
          PE._T.text("k1", n=1) == "T:k1" and PE._T.static("k2") == "S:k2",
          (PE._T.text("k1"), PE._T.static("k2")))
    check("bind 后域读口返回注入值（items / rules）",
          "__demo_item__" in PE._items_domain() and PE._effect_rules().get("rage", {}).get("cap") == 10,
          None)
    check("bind 后 `_purify_neg_keys()` 序 = 注入表内序（净化回显按此序 join）",
          PE._purify_neg_keys() == ("poison", "burn"), PE._purify_neg_keys())
    check("坏形状的 neg_keys ⇒ bind 当场报错（拒绝静默空表）",
          bool(_raises(lambda: PE.bind(text=lambda *a, **k: "", static=lambda *a, **k: "",
                                       items={}, rules={},
                                       neg_keys={"purify_neg_keys": {"keys": []}}))), None)

    # ------------------------------------------------------------ 6. 可换游戏（零数据包依赖）
    bad = []
    for path in pack_sources():
        with open(path, encoding="utf-8") as f:
            hits = content_imports(f.read())
        if hits:
            bad.append((os.path.relpath(path, PKG_DIR), hits))
    check("本包 .py 里零 import 数据包（content / content.*）—— 换游戏不用改本包",
          not bad, bad)
    check("扫描面覆盖到本包全部 .py（≥3 个：apply / effects/__init__ / effects/poi_effects / tests）",
          len(pack_sources()) >= 4, [os.path.relpath(p, PKG_DIR) for p in pack_sources()])

    proof = content_imports("from content import catalog_items\nimport content.texts\n")
    check("反证：扫描器对 `from content import …` / `import content.*` 报红",
          sorted(proof) == ["content", "content.texts"], proof)
    check("反证：包内相对导入（`from . import x`）不算数据包依赖",
          content_imports("from . import poi_effects\n") == [], None)

    print("\n通过 %d / 失败 %d" % (PASS, len(FAILS)))
    if FAILS:
        for line in FAILS:
            print("❌ %s" % line)
        return 1
    print("✅ ext_effect 包门禁全绿")
    return 0


if __name__ == "__main__":
    sys.exit(main())
