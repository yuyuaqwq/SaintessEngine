#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""`ext_achieve` 门禁：包契约 / 条件注册表 / 环境位图 / 零内容知识。

跑法：python extends/ext_achieve/tests/test_ext_achieve_package.py
退出码：0 = 全绿；1 = 有失败。

四类判据（判据只加强不削弱）
---------------------------
  ① **包契约**：`game.json` 字段齐 · `apply.install_engine()` 可调且真的不装任何东西 ·
     门面把 `cond` 的子模块与公开符号转出去。
  ② **形状语义**：`Registry` 的登记/覆盖/兜底/fail-loud 逐条对着原地口径 · `register_specs`
     整表装配（坏一条 ⇒ 一条都不登记）· `envs_of` 位图 · `EnvCtx.env` 缺项 False。
     · `rule` 的 `match_cond` 逐字段判定 / `fire` 触发序列（命中即止 · 计数 gte 触发并清零 ·
     chance 边界 · 七个句柄全注入 · 未装配 fail-loud）。
  ③ **零内容知识**：本包源码**不 import 任何数据包**（AST 扫 Import/ImportFrom）·
     代码常量里**没有内容侧取值**（AST 扫字符串字面量，跳过 docstring；注释本就不在 AST 里）。
  ④ **有牙**：把「带内容词 / 带数据包 import」的伪造源码喂给同一套扫描器 ⇒ 必须点名
     （判据本身要能红，不是打印一行「OK」）。
"""
import ast
import importlib
import json
import os
import sys

_HERE_DIR = os.path.dirname(os.path.abspath(__file__))    # extends/ext_achieve/tests
_PKG_ROOT = os.path.dirname(_HERE_DIR)                    # extends/ext_achieve
_EXT_BASE = os.path.dirname(_PKG_ROOT)                    # extends
ROOT = os.path.dirname(_EXT_BASE)                         # 引擎根
for _p in (ROOT, _EXT_BASE, _HERE_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

passed = failed = 0

from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "passed", "failed")


# ================================================= ④ 扫描器（先定义：③ 用它，④ 反证它）
#: 内容侧取值词表（形状包里出现 = 把某款游戏焊进底座）
BANNED = (
    # 中文：内容分类名
    "材料", "地图", "技能", "名册", "任务", "称号", "成就", "隐藏",
    "森林", "水域", "遗迹", "怪物", "装备", "金币", "职业", "副本",
    # ASCII：同上（小写后子串匹配；刻意**不含** map/instance/item —— 它们是
    # `Mapping` / `isinstance` / `items()` 的子串，会造出假阳性）
    "material", "forest", "water", "ruin", "monster", "npc",
    "skill", "quest", "title", "achievement", "achievements", "equip",
    "gold", "dungeon",   # 注：本包自己的名字 `ext_achieve` 不在此列（它不是内容词）
)

#: 允许的绝对导入根（其余一律「越界」：数据包 / 宿主 / 别的扩展包）
ALLOWED_ROOTS = frozenset((
    "saintess_engine", "ext_achieve",
    "__future__", "typing", "collections", "functools", "itertools",
    "json", "os", "re", "copy", "math", "dataclasses", "enum", "abc",
    "contextlib", "time", "random", "string", "types", "inspect",
))


def _docstrings(tree):
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            d = ast.get_docstring(node, clean=False)
            if d is not None:
                docs.add(d)
    return docs


def scan_text(src, name, banned=BANNED):
    """扫一段源码 → `(越界导入, 内容词命中)`；两项都是 `"<名>:<行>:<内容>"`。"""
    tree = ast.parse(src, filename=name)
    docs = _docstrings(tree)
    bad_imports, bad_words = [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:                      # 包内相对导入（`.envs`）：合法
                continue
            root = (node.module or "").split(".")[0]
            if root and root not in ALLOWED_ROOTS:
                bad_imports.append("%s:%d:%s" % (name, node.lineno, node.module))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in ALLOWED_ROOTS:
                    bad_imports.append("%s:%d:%s" % (name, node.lineno, alias.name))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in docs:
                continue                        # docstring 要能解释形状类比本身
            low = node.value.lower()
            for b in banned:
                if (b in node.value) if not b.isascii() else (b in low):
                    bad_words.append("%s:%d:%s" % (name, node.lineno, b))
    return bad_imports, bad_words


def _shape_sources():
    """本包「形状层」源码：除 `tests/` 之外的全部 .py。"""
    out = []
    for dirpath, dirs, files in os.walk(_PKG_ROOT):
        dirs[:] = [d for d in sorted(dirs) if d not in {"__pycache__", "tests"}]
        for fn in sorted(files):
            if fn.endswith(".py"):
                out.append(os.path.join(dirpath, fn))
    return out


def t1_contract():
    print("\n[1] 包契约：game.json / apply.py / 门面")
    mf = json.loads(open(os.path.join(_PKG_ROOT, "game.json"), encoding="utf-8").read())
    check("game.json 字段齐（id/kind/name/desc/engine/entry/created）",
          all(k in mf for k in ("id", "kind", "name", "desc", "engine", "entry", "created")),
          str(sorted(mf)))
    check("id == ext_achieve / kind == extension",
          mf["id"] == "ext_achieve" and mf["kind"] == "extension", str(mf.get("id")))
    check("entry 指的入口文件在包根且存在",
          mf["entry"] == "apply.py" and os.path.isfile(os.path.join(_PKG_ROOT, mf["entry"])),
          str(mf.get("entry")))
    apply_mod = importlib.import_module("ext_achieve.apply")
    check("入口暴露 install_engine 且可调", callable(getattr(apply_mod, "install_engine", None)))
    check("install_engine() 纯形状库：返回 None（不往引擎塞任何东西）",
          apply_mod.install_engine() is None)
    EXT = importlib.import_module("ext_achieve")
    sub = importlib.import_module("ext_achieve.cond")
    check("`ext_achieve.cond` 是同一模块对象", EXT.cond is sub)
    for sym in ("Registry", "EnvCtx", "bind_envs", "envs_of"):
        check("门面转出 %s" % sym, hasattr(EXT, sym) and getattr(EXT, sym) is getattr(sub, sym))
    check("`from ext_achieve.cond import …` 可用（__all__ 齐）",
          all(x in sub.__all__ for x in ("Registry", "EnvCtx", "bind_envs", "envs_of")))


def t2_registry():
    print("\n[2] 条件注册表：登记 / 覆盖 / 兜底 / fail-loud")
    from ext_achieve.cond import Registry
    try:
        Registry(default_key="")
        check("default_key 空串 → 报错（兜底键是契约，不是可选项）", False)
    except ValueError:
        check("default_key 空串 → 报错（兜底键是契约，不是可选项）", True)

    reg = Registry(default_key="any")
    reg.register("any", lambda ctx: True)      # ★ 默认键先登记（见下方「默认键必须存在」）

    @reg.register("hit")
    def _hit(ctx):
        return ctx["v"] > 1

    check("装饰器路：登记后 names() 含它", "hit" in reg.names() and reg.has("hit"))
    check("check 命中：走登记的函数",
          reg.check("hit", {"v": 2}) is True and reg.check("hit", {"v": 0}) is False)
    check("判定返回值**原样**转出（不归一成 bool）",
          reg.register("raw", lambda ctx: "现场措辞") is not None
          and reg.check("raw", {}) == "现场措辞")
    check("直接路：register(name, fn) 同实现",
          reg.register("direct", lambda ctx: False) is not None
          and reg.check("direct", {}) is False)

    check("未知名 → 默认键", reg.check("future_cond", {}) is True)
    check("空名 → 默认键", reg.check("", {}) is True)
    check("None → 默认键", reg.check(None, {}) is True)

    order = reg.names()
    reg.register("hit", lambda ctx: "second")
    check("★ 后注册者胜（重登记不报错）", reg.check("hit", {"v": 9}) == "second")
    check("重登记不搬家（键序不变）", reg.names() == order, str(reg.names()))

    reg.table["outside"] = lambda ctx: 7
    check("★ 表是同一份 dict：外部直接写即可用", reg.check("outside", {}) == 7)
    reg.table.pop("outside")
    check("外部 pop 即撤销", not reg.has("outside") and reg.check("outside", {}) is True)
    check("names() 保序（登记序）", reg.names() == ("any", "hit", "raw", "direct"),
          str(reg.names()))
    check("get 未登记 → None（不抛）", reg.get("nope") is None)

    # ★ 默认键必须存在：查表用的默认值是**立即求值**的 —— 即便名字命中，默认键缺了也当场炸
    #   （逐字同原地 `CONDITIONS.get(cond or "any", CONDITIONS["any"])`；不是「顺手改合理」的地方）
    bare = Registry(default_key="any")
    bare.register("known", lambda ctx: True)
    try:
        bare.check("known", {})
        check("★ 未知名 → 默认键兜底，默认键缺 → 当场炸（含名字命中的情形）", False)
    except KeyError:
        check("★ 未知名 → 默认键兜底，默认键缺 → 当场炸（含名字命中的情形）", True)
    bare.register("any", lambda ctx: True)
    check("补上默认键后同一张表立刻可用", bare.check("known", {}) is True
          and bare.check("unknown", {}) is True)


def t3_register_specs():
    print("\n[3] 声明表整表装配：合法表并入 / 坏一条 ⇒ 一条都不登记")
    from ext_achieve.cond import Registry
    reg = Registry(default_key="any")
    reg.register_specs({
        "any": {"const": True},
        "by_field": {"field": [{"key": "envs"}, {"key": "demo", "default": None}]},
    })
    check("整表并入：常量声明可用", reg.check("any", {}) is True)
    check("整表并入：field 步链可用", reg.check("by_field", {"envs": {"demo": 1}}) == 1)
    check("整表并入：步链缺字段走 default", reg.check("by_field", {"envs": {}}) is None)

    reg2 = Registry(default_key="any")
    try:
        reg2.register_specs({"ok": {"const": True}, "bad": {"op": "no_such_op"}})
        check("★ 坏一条 ⇒ 整表不装（先编译后登记）", False)
    except Exception as exc:                                            # noqa: BLE001
        check("★ 坏一条 ⇒ 整表不装（先编译后登记）",
              type(exc).__name__ == "SpecError" and reg2.names() == (),
              "%s / %r" % (type(exc).__name__, reg2.names()))


def t4_envs():
    print("\n[4] 环境位图：未装配 fail-loud / 注入即用 / 就地改表即生效")
    import ext_achieve.cond as C
    from ext_achieve.cond import EnvCtx

    C.bind_envs({})                      # 显式空装配（本门禁进程独占，下面各段自己收尾）
    check("空表装配可用（位图全 False，不报错）", C.envs_of("whatever") == {})
    try:
        C.bind_envs("不是表")
        check("词表只收映射 / 零参可调用", False)
    except TypeError:
        check("词表只收映射 / 零参可调用", True)

    table = {"demo": ("demo", "sample"), "other": ("zz",)}
    C.bind_envs(table)
    check("注入后即用：关键词包含匹配",
          C.envs_of("xx_demo_yy") == {"demo": True, "other": False},
          str(C.envs_of("xx_demo_yy")))
    check("位图键集 = 词表键集（保序）", list(C.envs_of("none").keys()) == ["demo", "other"])

    table["third"] = ("tri",)            # ★ 就地改表（不重新 bind）
    check("★ 注入的是对象本身（就地改表即刻生效，形状不复制）",
          C.envs_of("tri_beach")["third"] is True)

    C.bind_envs(lambda: table)           # 零参可调用也收（惰性取值）
    check("零参可调用：每次取用时现读", C.envs_of("tri_x")["third"] is True)

    ctx = EnvCtx("xx_demo_yy", {"id": "xx_demo_yy"}, False, C.envs_of("xx_demo_yy"))
    check("EnvCtx.env 取位图真值", ctx.env("demo") is True and ctx.env("other") is False)
    check("EnvCtx.env 缺项 → False（不 KeyError）", ctx.env("nope") is False)
    check("EnvCtx 保留 is_night / envs 两个声明表取数键",
          ctx.is_night is False and isinstance(ctx.envs, dict))

    # 未装配 fail-loud：另开一个进程内直接看模块变量（不 bind 就取用）
    import importlib
    import ext_achieve.cond.envs as _envs_mod
    importlib.reload(_envs_mod)
    try:
        _envs_mod.envs_of("whatever")
        check("★ 未装配就取用 ⇒ 当场报错（不返回空位图）", False)
    except RuntimeError:
        check("★ 未装配就取用 ⇒ 当场报错（不返回空位图）", True)


def t5_zero_knowledge():
    print("\n[5] 零内容知识：不 import 数据包 / 代码常量无内容侧取值")
    bad_imports, bad_words = [], []
    for path in _shape_sources():
        with open(path, encoding="utf-8") as f:
            src = f.read()
        name = os.path.relpath(path, ROOT).replace("\\", "/")
        bi, bw = scan_text(src, name)
        bad_imports += bi
        bad_words += bw
    check("★ 形状层不 import 数据包 / 宿主 / 别的扩展包（零越界导入）",
          not bad_imports, str(bad_imports[:6]))
    check("★ 代码常量里无内容侧取值（取值/词表只由调用方给）",
          not bad_words, str(bad_words[:6]))
    check("扫描面非空（真的扫到了形状层源码）", len(_shape_sources()) >= 4,
          str(sorted(os.path.basename(p) for p in _shape_sources())))


def t6_teeth():
    print("\n[6] ★ 有牙：同一套扫描器喂伪造源码 ⇒ 必须点名")
    bi, _ = scan_text("import content.hidden_cond\n", "fake.py")
    check("越界导入被抓（数据包）", bi == ["fake.py:1:content.hidden_cond"], str(bi))
    bi2, _ = scan_text("from ext_loot import loot\n", "fake.py")
    check("越界导入被抓（别的扩展包：没写 depends 就是偷引用）",
          bi2 == ["fake.py:1:ext_loot"], str(bi2))
    _, bw2 = scan_text("TABLE = {'森林': ('wood',)}\n", "fake.py")
    check("内容词被抓（中文分类名）", any("森林" in x for x in bw2), str(bw2))
    _, bw3 = scan_text('X = "water"\n', "fake.py")
    check("内容词被抓（ASCII 关键词）", any("water" in x for x in bw3), str(bw3))
    _, bw4 = scan_text('"""docstring 里可以提森林/water（形状类比）"""\n', "fake.py")
    check("docstring 不误伤（文档要能解释类比）", bw4 == [], str(bw4))
    bi5, bw5 = scan_text("from saintess_engine.conditions.declarative import x\n", "fake.py")
    check("引擎导入不误伤", not bi5 and not bw5, "%r %r" % (bi5, bw5))


def t7_rule():
    print("\n[7] 规则触发形状：绑定面 / 条件判定逐字段 / 计数与概率 / 触发序列")
    import importlib

    import ext_achieve.rule as R
    import ext_achieve.rule.engine as _eng

    EXT = importlib.import_module("ext_achieve")
    check("`ext_achieve.rule` 是同一模块对象", EXT.rule is R)
    check("门面转出 bind / fire / match_cond",
          all(hasattr(EXT.rule, s) for s in ("bind", "fire", "match_cond")))
    check("`from ext_achieve.rule import …` 可用（__all__ 齐）",
          all(x in R.__all__ for x in ("bind", "fire", "match_cond")))

    counters = {}
    items = {("g", "q"): {"demo_mat": 2}}
    flags = {("g", "q"): {"talk_demo": True}}
    fired = []

    def _fire_event(template, params, gid, qid, player, cur_map, hooks):
        fired.append((template, params, gid, qid, hooks))
        return "现场措辞"

    RULES = [
        {"id": "r_off", "trigger": "t", "enabled": False,
         "action": {"template": "should_never_run"}},
        {"id": "r_hit", "trigger": "t", "cond": {"event": "empty"},
         "action": {"template": "tmpl_hit", "params": {"k": 1}}},
    ]
    R.bind(rules=lambda: RULES,
           is_time=lambda span: span == "day",
           counter_get=lambda g, q, k: counters.get((g, q, k), 0),
           counter_set=lambda g, q, k, v: counters.__setitem__((g, q, k), v),
           count_item=lambda g, q, i: items.get((g, q), {}).get(i, 0),
           talk_flag=lambda g, q, f: bool(flags.get((g, q), {}).get(f)),
           fire_event=_fire_event)

    print("  -- 条件判定逐字段（字段名 = 形状契约）")
    mc = R.match_cond
    m_ab = {"id": "a", "type": "field"}
    check("cond 为 None ⇒ 恒真", mc(None, "g", "q", {}, {}, {}) is True)
    check("cond 为 {} ⇒ 恒真", mc({}, "g", "q", {}, {}, {}) is True)
    check("map（list）命中 / 不命中",
          mc({"map": ["a", "b"]}, "g", "q", {}, m_ab, {}) is True
          and mc({"map": ["b"]}, "g", "q", {}, m_ab, {}) is False)
    check("map（单值）命中 / 不命中",
          mc({"map": "a"}, "g", "q", {}, m_ab, {}) is True
          and mc({"map": "b"}, "g", "q", {}, m_ab, {}) is False)
    check("map_type（list / 单值）",
          mc({"map_type": ["field"]}, "g", "q", {}, m_ab, {}) is True
          and mc({"map_type": "town"}, "g", "q", {}, m_ab, {}) is False)
    check("cur_map 为 None ⇒ 地图字段判不命中（不炸）",
          mc({"map": "a"}, "g", "q", {}, None, {}) is False)
    check("★ time 走注入的 is_time（形状里没有钟点边界）",
          mc({"time": "day"}, "g", "q", {}, m_ab, {}) is True
          and mc({"time": "deep_night"}, "g", "q", {}, m_ab, {}) is False)
    check("level_min / level_max",
          mc({"level_min": 5, "level_max": 10}, "g", "q", {"level": 5}, m_ab, {}) is True
          and mc({"level_min": 6}, "g", "q", {"level": 5}, m_ab, {}) is False
          and mc({"level_max": 4}, "g", "q", {"level": 5}, m_ab, {}) is False)
    check("item 走注入的 count_item（单值 / list）",
          mc({"item": "demo_mat"}, "g", "q", {}, m_ab, {}) is True
          and mc({"item": "nope"}, "g", "q", {}, m_ab, {}) is False
          and mc({"item": ["nope", "demo_mat"]}, "g", "q", {}, m_ab, {}) is True)
    check("flag 走注入的 talk_flag",
          mc({"flag": "talk_demo"}, "g", "q", {}, m_ab, {}) is True
          and mc({"flag": "talk_none"}, "g", "q", {}, m_ab, {}) is False)
    check("event（单值 / list）",
          mc({"event": "empty"}, "g", "q", {}, m_ab, {"event": "empty"}) is True
          and mc({"event": ["empty", "battle"]}, "g", "q", {}, m_ab, {"event": "battle"}) is True
          and mc({"event": "battle"}, "g", "q", {}, m_ab, {"event": "empty"}) is False)
    check("enemy_tag：boss / elite 特征",
          mc({"enemy_tag": "boss"}, "g", "q", {}, m_ab,
             {"enemy": {"name": "某", "is_boss": True}}) is True
          and mc({"enemy_tag": "elite"}, "g", "q", {}, m_ab,
                 {"enemy": {"name": "某", "is_elite": True}}) is True
          and mc({"enemy_tag": "boss"}, "g", "q", {}, m_ab,
                 {"enemy": {"name": "某"}}) is False)
    check("enemy_tag：名称 / id / tags 子串 + list 任一",
          mc({"enemy_tag": "史"}, "g", "q", {}, m_ab, {"enemy": {"name": "史莱姆"}}) is True
          and mc({"enemy_tag": ["nope", "e_x"]}, "g", "q", {}, m_ab,
                 {"enemy": {"id": "e_x"}}) is True
          and mc({"enemy_tag": "zz"}, "g", "q", {}, m_ab, {"enemy": {"name": "史莱姆"}}) is False)
    check("hp_pct_max（残血）",
          mc({"hp_pct_max": 0.3}, "g", "q", {"hp": 20, "max_hp": 100}, m_ab, {}) is True
          and mc({"hp_pct_max": 0.3}, "g", "q", {"hp": 80, "max_hp": 100}, m_ab, {}) is False)
    check("random_chance 边界：0 ⇒ 必不满足 / 1 ⇒ 必满足",
          mc({"random_chance": 0}, "g", "q", {}, m_ab, {}) is False
          and mc({"random_chance": 1}, "g", "q", {}, m_ab, {}) is True)

    print("  -- 触发序列：命中即止 / 计数 / 概率 / 执行器透传")
    fired[:] = []
    txt = R.fire("g", "q", {}, m_ab, "t", {"event": "empty"})
    check("命中 ⇒ 执行 action 并返回执行器文本", txt == "现场措辞", repr(txt))
    check("enabled=False 的规则被跳过（执行器收到的是命中那条）",
          fired == [("tmpl_hit", {"k": 1}, "g", "q", None)], str(fired))
    check("hooks 原样透传（默认 None）",
          R.fire("g", "q", {}, m_ab, "t", {"event": "empty"}, {"h": 1}) == "现场措辞"
          and fired[-1][4] == {"h": 1}, str(fired[-1]))
    fired[:] = []
    check("无命中 ⇒ 空串且不执行", R.fire("g", "q", {}, m_ab, "t", {"event": "battle"}) == ""
          and fired == [])
    check("trigger 不同的规则不上钩", R.fire("g", "q", {}, m_ab, "other", {"event": "empty"}) == "")

    call_log = []

    def _fe2(template, params, gid, qid, player, cur_map, hooks):
        call_log.append(template)
        return "" if template == "tmpl_blank" else "got:" + template

    R.bind(rules=[
        {"id": "r_notpl", "trigger": "s", "action": {"params": {}}},
        {"id": "r_blank", "trigger": "s", "action": {"template": "tmpl_blank"}},
        {"id": "r_first", "trigger": "s", "action": {"template": "tmpl_first"}},
        {"id": "r_second", "trigger": "s", "action": {"template": "tmpl_second"}},
    ], is_time=lambda span: True,
        counter_get=lambda g, q, k: counters.get((g, q, k), 0),
        counter_set=lambda g, q, k, v: counters.__setitem__((g, q, k), v),
        count_item=lambda g, q, i: 0,
        talk_flag=lambda g, q, f: False,
        fire_event=_fe2)
    call_log[:] = []
    out = R.fire("g", "q", {}, m_ab, "s", {})
    check("无 template 的条目跳过；执行器返回空串继续往后找；★ 命中即止",
          out == "got:tmpl_first" and call_log == ["tmpl_blank", "tmpl_first"], str(call_log))

    counters.clear()
    R.bind(rules=[{"id": "r_cnt", "trigger": "c", "count": {"key": "k1", "gte": 3},
                   "cond": {"event": "empty"}, "action": {"template": "tmpl_cnt"}}],
           is_time=lambda span: True,
           counter_get=lambda g, q, k: counters.get((g, q, k), 0),
           counter_set=lambda g, q, k, v: counters.__setitem__((g, q, k), v),
           count_item=lambda g, q, i: 0, talk_flag=lambda g, q, f: False,
           fire_event=lambda t, p, g, q, pl, m, h: "got:" + t)
    o1 = R.fire("g", "q", {}, m_ab, "c", {"event": "empty"})
    o2 = R.fire("g", "q", {}, m_ab, "c", {"event": "empty"})
    check("计数：第 1/2 次不触发，计数 1 → 2",
          o1 == "" and o2 == "" and counters[("g", "q", "k1")] == 2, str(counters))
    o3 = R.fire("g", "q", {}, m_ab, "c", {"event": "empty"})
    check("计数：第 3 次触发并清零",
          o3 == "got:tmpl_cnt" and counters[("g", "q", "k1")] == 0, str(counters))
    R.fire("g", "q", {}, m_ab, "c", {"event": "empty"})
    R.fire("g", "q", {}, m_ab, "c", {"event": "battle"})
    check("计数：条件中断 ⇒ 清零（读→算→写，逐字同原地）",
          counters[("g", "q", "k1")] == 0, str(counters))
    check("计数规则不走 chance 分支（cond 不命中 ⇒ 不触发）",
          R.fire("g", "q", {}, m_ab, "c", {"event": "battle"}) == "")

    R.bind(rules=[{"id": "r_c0", "trigger": "p", "chance": 0,
                   "action": {"template": "tmpl_c0"}},
                  {"id": "r_c1", "trigger": "q1", "chance": 1,
                   "action": {"template": "tmpl_c1"}}],
           is_time=lambda span: True,
           counter_get=lambda g, q, k: 0, counter_set=lambda g, q, k, v: None,
           count_item=lambda g, q, i: 0, talk_flag=lambda g, q, f: False,
           fire_event=lambda t, p, g, q, pl, m, h: "got:" + t)
    check("chance=0 ⇒ 不触发", R.fire("g", "q", {}, m_ab, "p", {}) == "")
    check("chance=1 ⇒ 触发", R.fire("g", "q", {}, m_ab, "q1", {}) == "got:tmpl_c1")

    print("  -- 注入面：形参校验 / 对象共享 / 未装配 fail-loud")
    try:
        R.bind(rules=123, is_time=lambda s: True, counter_get=lambda *a: 0,
               counter_set=lambda *a: None, count_item=lambda *a: 0,
               talk_flag=lambda *a: False, fire_event=lambda *a: "")
        check("rules 只收容器 / 零参可调用（数字 ⇒ TypeError）", False)
    except TypeError:
        check("rules 只收容器 / 零参可调用（数字 ⇒ TypeError）", True)
    try:
        R.bind(rules=[], is_time="x", counter_get=lambda *a: 0, counter_set=lambda *a: None,
               count_item=lambda *a: 0, talk_flag=lambda *a: False, fire_event=lambda *a: "")
        check("句柄必须可调用（字符串 ⇒ TypeError）", False)
    except TypeError:
        check("句柄必须可调用（字符串 ⇒ TypeError）", True)

    shared = [{"id": "r_live", "trigger": "L", "action": {"template": "tmpl_live"}}]
    R.bind(rules=shared, is_time=lambda span: True, counter_get=lambda *a: 0,
           counter_set=lambda *a: None, count_item=lambda *a: 0,
           talk_flag=lambda *a: False, fire_event=lambda *a: "live")
    first = R.fire("g", "q", {}, m_ab, "L", {})
    shared.append({"id": "r_live2", "trigger": "L2", "action": {"template": "tmpl_live2"}})
    check("rules 收 list 本身 ⇒ 就地改表即刻生效（同一份对象）",
          first == "live" and R.fire("g", "q", {}, m_ab, "L2", {}) == "live")

    fresh = importlib.reload(_eng)
    check("reload 后回到未装配态（本段收尾；与 t4 同法）", fresh._INJ is None)
    try:
        fresh.fire("g", "q", {}, m_ab, "t", {})
        check("★ 未装配就 fire ⇒ 当场报错（不返回空串）", False)
    except RuntimeError:
        check("★ 未装配就 fire ⇒ 当场报错（不返回空串）", True)
    try:
        fresh.match_cond({"time": "day"}, "g", "q", {}, m_ab, {})
        check("★ 未装配就 match_cond ⇒ 取件点当场报错", False)
    except RuntimeError:
        check("★ 未装配就 match_cond ⇒ 取件点当场报错", True)


def t8_earn():
    print("\n[8] 逐条求值形状：上下文外壳 / 参数化条件 / 求值器 / 注入面 fail-loud")
    import ext_achieve.earn as E

    def _boom(fn):
        try:
            fn()
        except Exception as exc:                      # noqa: BLE001
            return type(exc).__name__
        return "<没报错>"

    # -- ① 上下文外壳：位置参数序 / 字段名 / 缺省归一 / 钩子
    ctx = E.EvalCtx("g", "q", {"cnt": 3}, {"k": 1}, {"f": 2}, {"side": {}},
                    hooks={"ping": lambda a, b: a + b})
    check("EvalCtx 位置参数序 (group_id, qq_id, player, stats, rep, quests, hooks) 生效",
          (ctx.group_id, ctx.qq_id, ctx._focus, ctx.stats, ctx.rep, ctx.quests)
          == ("g", "q", {"cnt": 3}, {"k": 1}, {"f": 2}, {"side": {}}),
          repr((ctx.group_id, ctx.qq_id, ctx._focus, ctx.stats, ctx.rep, ctx.quests)))
    blank = E.EvalCtx("g", "q", None, None, None, None)
    check("EvalCtx 缺省归一：player/stats/rep/quests/hooks ⇒ 各自 {}",
          blank._focus == {} and blank.stats == {} and blank.rep == {}
          and blank.quests == {} and blank.hooks == {},
          repr((blank._focus, blank.stats, blank.rep, blank.quests, blank.hooks)))
    check("hook() 有则转给（实参原样透传）", ctx.hook("ping", 1, 2) == 3, repr(ctx.hook("ping", 1, 2)))
    check("hook() 没有 ⇒ None（不抛）", ctx.hook("nope") is None)

    # -- ② 注入面（fail-loud + 同一对象 + 可清空）
    check("★ 未 bind 就取读口 ⇒ 当场报错（不返回空壳）",
          _boom(blank._db) == "RuntimeError", _boom(blank._db))
    box = {"read": True}
    E.bind(db=box)
    check("bind 后 _db() 返回**同一对象**（不复制、不包壳）",
          E.EvalCtx("g", "q", {}, {}, {}, {})._db() is box)
    E.bind(db=None)
    check("bind(None) 清空 ⇒ 回到未装配态（取用照旧报错）",
          _boom(blank._db) == "RuntimeError", _boom(blank._db))

    # -- ③ 参数化条件：解析 / 类别集合 / 边界 / 兜底
    seen = []
    cond = E.ParamCond("pro_", ("gather", "mining"),
                       lambda c, k: seen.append((c, k)) or {"gather": 3, "mining": 1}.get(k, 0))
    check("ParamCond.parse：前缀 + 类别 + 数字 ⇒ (类别, 阈值)",
          cond.parse("pro_gather3") == ("gather", 3), repr(cond.parse("pro_gather3")))
    check("parse：前缀不匹配 ⇒ None（不抛）",
          cond.parse("gather3") is None and cond.parse("prox_gather3") is None)
    check("parse：类别不在注入集合里 ⇒ None（集合是内容侧的活）",
          cond.parse("pro_fishing3") is None and not cond.matches("pro_fishing3"))
    check("parse：形状不是「前缀+小写字母+数字」⇒ None（大小写敏感 / 尾部残留）",
          cond.parse("pro_Gather3") is None and cond.parse("pro_gather3x") is None
          and cond.parse("pro_gather") is None)
    check("parse：非字符串 / None ⇒ None（不抛）",
          cond.parse(None) is None and cond.parse(3) is None)
    check("check：阈值边界 —— 等级 == 阈值 达标 / 差 1 不达标",
          cond.check("pro_gather3", blank) is True and cond.check("pro_mining2", blank) is False)
    check("check：本条件不管的 id ⇒ False（不抛）",
          cond.check("ach_whatever", blank) is False and cond.check(7, blank) is False)
    check("check：等级读取器拿到 (ctx, 类别) 两参（形状不自己读存档）",
          seen[-1][0] is blank and seen[-1][1] in ("gather", "mining"), repr(seen[-1]))
    check("ParamCond 构造校验：空前缀 ⇒ ValueError", _boom(lambda: E.ParamCond("", (), lambda c, k: 0)) == "ValueError")
    check("ParamCond 构造校验：level_of 不可调用 ⇒ TypeError",
          _boom(lambda: E.ParamCond("pro_", (), "x")) == "TypeError")

    # -- ④ 逐条求值器：注册表命中 / 参数化兜底 / 未知 ⇒ False / 同长同序
    class Reg:
        """最小注册表替身（形状只要求 `get(name) -> fn | None`）。"""

        def __init__(self, table):
            self._t = table

        def get(self, name):
            return self._t.get(name)

    class Ctl:
        """判定函数替身：记调用次数，返回调用方给的值（可非 bool）。"""

        def __init__(self, value):
            self.value = value
            self.calls = 0

        def __call__(self, ctx):
            self.calls += 1
            return self.value

    hit = Ctl("raw-value")            # ★ 返回值原样收（不做 bool 归一）
    raw = Ctl(None)
    reg = Reg({"k_hit": hit, "k_raw": raw})
    fall = E.ParamCond("pro_", ("gather",), lambda c, k: 5)
    table = [{"id": "k_hit"}, {"id": "pro_gather2"}, {"id": "pro_gather9"},
             {"id": "pro_unknown1"}, {"id": "k_raw"}, {"id": "nope"}]
    out = E.earned_flags(table, blank, reg, fall)
    check("earned_flags：同长同序（命中 / 兜底达标 / 兜底不达标 / 兜底不管 / 命中 / 都没有）",
          out == ["raw-value", True, False, False, None, False], repr(out))
    check("★ 判定函数返回值**原样收进来**（不做 bool 归一：None 就是 None）",
          out[4] is None and out[0] == "raw-value")
    check("注册表命中时不问兜底（两条路互斥，各调一次）",
          hit.calls == 1 and raw.calls == 1, (hit.calls, raw.calls))
    check("字符串条目也收（`dict` 取 \"id\" / 其余原样即 id）",
          E.earned_flags(["k_hit"], blank, reg, fall) == ["raw-value"])
    check("fallback=None ⇒ 只剩注册表那条路（未命中一律 False）",
          E.earned_flags(table, blank, reg, None) == ["raw-value", False, False, False, None, False])
    check("`dict` 缺 \"id\" ⇒ KeyError（与原地 `t[\"id\"]` 同口径，不静默降级）",
          _boom(lambda: E.earned_flags([{}], blank, reg, fall)) == "KeyError")
    check("空条目表 ⇒ 空结果（同长同序的退化情形）",
          E.earned_flags([], blank, reg, fall) == [])


def main():
    print("== ext_achieve 门禁：包契约 / 条件注册表 / 环境位图 / 规则触发 / 逐条求值 / 零内容知识 ==")
    t1_contract()
    t2_registry()
    t3_register_specs()
    t4_envs()
    t5_zero_knowledge()
    t6_teeth()
    t7_rule()
    t8_earn()
    print("\n===== 结果：通过 %d / %d =====" % (passed, passed + failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
