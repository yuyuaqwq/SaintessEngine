#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""指令声明表装载门禁：派生语义 / 与注册表同源 / fail-closed / 真数据。

跑法：python tests/test_command_spec_loader.py
退出码：0 = 全绿；1 = 有失败。

四处专门钉住的地方（都是「改了就静默变行为」的）：
  ① **派生语义**：单正则逐字、多条 → `(?:a)|(?:b)`；用**独立实现**逐条对拍 195 条真声明
  ② **单一来源**：有效表必须与注册表同源（`pattern_map() == {k: spec.combined()}`）
  ③ **fail-closed**：缺文件/空表/坏 JSON/key 重复/正则非法 → 抛错（反证：**不是**返回空表）
  ④ **薄表场景**：`pattern_map_from_table()` 纯函数（不读盘、不 import 平台）
"""
import json
import os
import re
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from saintess_engine.command import (  # noqa: E402
    CommandSpecSource, build_registry, catalog_of, load_table, pattern_map_from_table,
)

PKG_CMD = os.path.join(ROOT, "games", "orlandia", "content", "data", "commands.json")

passed = 0
failed = 0


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "passed", "failed")


def _ref_combine(pats):
    """独立参考实现（不 import 引擎）：单条逐字 / 多条 (?:a)|(?:b) / 空 → \"\"。"""
    pats = [p for p in pats if p]
    if not pats:
        return ""
    if len(pats) == 1:
        return pats[0]
    return "|".join("(?:%s)" % p for p in pats)


# ============================================================ ① 派生语义
def t1_derivation():
    print("\n-- ① 派生语义（纯函数，不读盘）")
    table = {
        "solo": "^(?:x)$",
        "alias": ["a", "b", "c"],
        "dict": {"patterns": ["d", "e"], "desc": "两条"},
        "single_list": ["only"],
        "empty_pat": ["", ""],
        "blank_pat": ["  "],
        "none": None,
        "num": 3,
    }
    got = pattern_map_from_table(table)
    check("单正则逐字保留", got.get("solo") == "^(?:x)$", got.get("solo"))
    check("dict 形态也能派生", got.get("dict") == "(?:d)|(?:e)", got.get("dict"))
    check("单元素列表 = 该正则", got.get("single_list") == "only")
    check("全空正则 → 不进有效表", "empty_pat" not in got)
    # 空白串是**合法正则**（匹配两个空格），这里与宿主语义一致地保留它（口径：`if p` 只滤空串）
    check("空白串保留（与宿主 `if p` 口径一致）", got.get("blank_pat") == "  ", got.get("blank_pat"))
    check("整表派生 = 逐 key 逐字期望值（不多不少）",
          got == {"solo": "^(?:x)$", "alias": "(?:a)|(?:b)|(?:c)", "dict": "(?:d)|(?:e)",
                  "single_list": "only", "blank_pat": "  "}, got)
    check("None / 非标量 → 不进有效表（由注册表校验点名）", "none" not in got and "num" not in got)
    # 与独立实现逐条对拍真数据
    if os.path.exists(PKG_CMD):
        data = json.load(open(PKG_CMD, encoding="utf-8"))
        mine = pattern_map_from_table(data)
        ref = {}
        for k, v in data.items():
            pats = v.get("patterns", v.get("pattern")) if isinstance(v, dict) else v
            if isinstance(pats, str):
                pats = [pats]
            c = _ref_combine(pats or ())
            if c:
                ref[str(k)] = c
        diff = [k for k in set(mine) | set(ref) if mine.get(k) != ref.get(k)]
        check(f"{len(ref)} 条真声明逐条对拍独立实现", diff == [], diff[:3])
        check("真声明派生条数 = 声明条数", len(mine) == len(data), f"{len(mine)} vs {len(data)}")
    else:
        check("包内 commands.json 存在（真数据对拍）", False, PKG_CMD)


# ============================================================ ② 同源
def t2_single_source():
    print("\n-- ② 有效表与注册表**同源**（不许第二份正则）")
    data = json.load(open(PKG_CMD, encoding="utf-8"))
    reg = build_registry(data, name="gate.pkg_commands")
    pm = reg.pattern_map()
    from_spec = {s.key: s.combined() for s in reg.specs()}
    check("pattern_map() == {key: spec.combined()}", pm == from_spec)
    check("键集相同", set(pm) == set(reg.keys()))
    src = CommandSpecSource(PKG_CMD, name="gate.source")
    check("CommandSpecSource.pattern_map() 与上面一致", src.pattern_map() == pm)
    cat = src.catalog()
    cat_keys = [s.key for specs in cat.values() for s in specs]
    check("目录里的声明全来自同一注册表的 visible 集，且一条不漏",
          set(cat_keys) == {s.key for s in src.visible()} and len(cat_keys) == len(src.visible()),
          f"目录 {len(cat_keys)} vs visible {len(src.visible())}")
    check("catalog 分组数 = 可见声明用到的分类数",
          len(cat) == len({s.category or '其他' for s in src.visible()}), list(cat))


# ============================================================ ③ fail-closed（反证）
def t3_fail_closed():
    print("\n-- ③ fail-closed：坏输入一律抛（反证：不静默给空表）")
    tmp = tempfile.mkdtemp(prefix="cmdspec_")
    missing = os.path.join(tmp, "nope.json")
    try:
        load_table(missing)
        check("缺文件 → 抛", False)
    except FileNotFoundError:
        check("缺文件 → FileNotFoundError", True)
    empty = os.path.join(tmp, "empty.json")
    open(empty, "w", encoding="utf-8").write("{}")
    try:
        load_table(empty)
        check("空表 → 抛", False)
    except ValueError:
        check("空表 → ValueError（反证：不是返回 {}）", True)
    bad = os.path.join(tmp, "bad.json")
    open(bad, "w", encoding="utf-8").write("{oops")
    try:
        load_table(bad)
        check("坏 JSON → 抛", False)
    except json.JSONDecodeError:
        check("坏 JSON → JSONDecodeError", True)
    try:
        build_registry({"a": "(?:ok)", "b": "(?:ok)"}, name="dup_regex")
        check("正则被两条声明共用 → 抛", False)
    except ValueError as e:
        check("正则被两条声明共用 → ValueError（validate 抓到）", "共用" in str(e), str(e)[:60])
    try:
        build_registry({"a": {"patterns": ["([unclosed"]}})
        check("正则非法 → 抛", False)
    except ValueError as e:
        check("正则非法 → ValueError", "非法" in str(e), str(e)[:60])
    try:
        build_registry({"a": {"patterns": [""]}})
        check("未声明有效正则 → 抛", False)
    except ValueError as e:
        check("未声明有效正则 → ValueError", "未声明" in str(e), str(e)[:60])
    src = CommandSpecSource(PKG_CMD)
    try:
        src.spec("绝对不存在的指令key")
        check("取不存在的 key → 抛", False)
    except KeyError:
        check("取不存在的 key → KeyError（不含糊给 None）", True)
    check("软取接口 get() 缺 → None", src.get("绝对不存在的指令key") is None)


# ============================================================ ④ 装载器行为
def t4_source():
    print("\n-- ④ 装载器：懒构建 / reload 拿到新值 / 目录分组")
    tmp = tempfile.mkdtemp(prefix="cmdspec_")
    p = os.path.join(tmp, "specs.json")
    json.dump({"one": {"patterns": ["^一"], "category": "甲", "order": 2},
               "two": {"patterns": ["^二", "^twо"], "category": "甲", "order": 1},
               "hid": {"patterns": ["^隐"], "category": "乙", "visible": False}},
              open(p, "w", encoding="utf-8"), ensure_ascii=False)
    src = CommandSpecSource(p, name="gate.tmp")
    check("懒构建：keys 命中 3 条", len(src.keys()) == 3, src.keys())
    check("别名合并 (?:a)|(?:b)", src.pattern_map()["two"] == "(?:^二)|(?:^twо)",
          src.pattern_map()["two"])
    cat = src.catalog()
    check("目录按 category 分组", set(cat) == {"甲"}, set(cat))
    check("visible=False 不进目录", len(cat.get("甲", [])) == 2, len(cat.get("甲", [])))
    check("组内按 order 排", [s.key for s in cat["甲"]] == ["two", "one"],
          [s.key for s in cat["甲"]])
    json.dump({"one": {"patterns": ["^壹"], "category": "甲"}}, open(p, "w", encoding="utf-8"),
              ensure_ascii=False)
    check("reload 前旧缓存仍生效（懒+缓存）", src.pattern_map()["one"] == "^一")
    src.reload()
    check("reload 后拿到新值", src.pattern_map()["one"] == "^壹")
    check("reload 后只剩 1 条", len(src.keys()) == 1)
    check("catalog_of 与 source.catalog() 同形", catalog_of(src.registry()) == src.catalog())


# ============================================================ ⑤ 不碰平台
def t5_no_platform():
    print("\n-- ⑤ 装载器不碰平台（宿主只注入「表在哪 + 注册动作」）")
    src = open(os.path.join(ROOT, "saintess_engine", "command", "spec.py"), encoding="utf-8").read()
    bad = [w for w in ("astrbot", "AstrBot", "Dragonfall", "dragonfall", "奥兰迪亚") if w in src]
    check("源码里没有宿主/游戏字样", bad == [], bad)
    check("没有包内相对越界导入（只用 .registry）",
          re.search(r"from \.\w+ import", src) is not None
          and "from .." not in src)
    check("纯派生函数不读盘（源码里无 open( ）",
          "open(" not in src.split("def pattern_map_from_table")[1].split("def catalog_of")[0])


def main():
    print("== 指令声明表装载门禁：派生 / 同源 / fail-closed / 真数据 ==")
    t1_derivation()
    t2_single_source()
    t3_fail_closed()
    t4_source()
    t5_no_platform()
    print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
